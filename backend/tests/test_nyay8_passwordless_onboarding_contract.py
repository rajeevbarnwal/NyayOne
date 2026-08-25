"""Tests-first contracts for NYAY-8 passwordless onboarding.

These tests deliberately describe the accepted NYAY-8 boundary before the
GREEN implementation exists.  They reuse the already-sealed NYAY-4 account
fixture so failures are attributable to the new contract, not to a parallel
OTP implementation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie

import pytest
from fastapi import Response
from sqlalchemy import func, select

from app.api.v1 import auth_student
from app.core.auth_cookies import clear_auth_session_cookie
from app.core.config import settings
from app.models.registration import (
    AuthSession,
    OtpChallenge,
    OtpFlow,
    RegistrationIdempotencyRecord,
)
from app.schemas.registration import StudentRegisterRequest
from app.services import otp_flow_service
from tests import test_student_login_session as login_contract


@pytest.fixture()
def nyay8_context():
    context = login_contract._context()
    try:
        yield context
    finally:
        context[0].close()
        context[1].dispose()


def _cookie_contract(header: str) -> dict[str, object]:
    parsed = SimpleCookie()
    parsed.load(header)
    morsel = parsed[settings.auth_session_cookie_name]
    return {
        "host_only": morsel["domain"] == "",
        "http_only": bool(morsel["httponly"]),
        "path": morsel["path"],
        "same_site": morsel["samesite"].casefold(),
        "secure": bool(morsel["secure"]),
    }


@pytest.mark.parametrize(
    ("app_env", "secure"),
    (("testing", False), ("production", True)),
)
def test_server_issued_onboarding_cookie_has_the_exact_nyay8_scope(
    monkeypatch: pytest.MonkeyPatch,
    app_env: str,
    secure: bool,
) -> None:
    """The opaque session is browser-wide and hardened outside local tests."""

    monkeypatch.setattr(settings, "app_env", app_env)
    response = Response()
    auth_student._set_session_cookie(response, "opaque-test-session")
    auth_headers = [
        header
        for header in response.headers.getlist("set-cookie")
        if header.startswith(f"{settings.auth_session_cookie_name}=")
    ]
    assert len(response.headers.getlist("set-cookie")) == 2
    assert len(auth_headers) == 2
    issuance = [
        header
        for header in auth_headers
        if "Max-Age=0" not in header
    ]
    legacy_clear = [
        header
        for header in auth_headers
        if "Max-Age=0" in header and "Path=/api/v1" in header
    ]
    assert len(issuance) == 1
    assert len(legacy_clear) == 1
    assert "HttpOnly" in legacy_clear[0]
    assert "SameSite=strict" in legacy_clear[0]
    assert "Domain=" not in legacy_clear[0]
    assert ("Secure" in legacy_clear[0]) is secure
    observed = _cookie_contract(issuance[0])

    assert observed == {
        "host_only": True,
        "http_only": True,
        "path": "/",
        "same_site": "lax",
        "secure": secure,
    }


def test_session_issuance_and_clear_expire_the_legacy_api_path_cookie() -> None:
    """A pre-NYAY-8 actor cookie cannot reappear after rotation or logout."""

    issued = Response()
    auth_student._set_session_cookie(issued, "opaque-new-session")
    issuance_headers = issued.headers.getlist("set-cookie")
    assert len(issuance_headers) == 2
    assert any(
        header.startswith(f"{settings.auth_session_cookie_name}=opaque-new-session")
        and "Path=/" in header
        and "SameSite=lax" in header
        for header in issuance_headers
    )
    assert any(
        header.startswith(f'{settings.auth_session_cookie_name}=""')
        and "Max-Age=0" in header
        and "Path=/api/v1" in header
        for header in issuance_headers
    )

    cleared = Response()
    clear_auth_session_cookie(cleared)
    clear_headers = cleared.headers.getlist("set-cookie")
    assert len(clear_headers) == 2
    assert any(
        header.startswith(f'{settings.auth_session_cookie_name}=""')
        and "Max-Age=0" in header
        and "Path=/;" in header
        for header in clear_headers
    )
    assert any(
        header.startswith(f'{settings.auth_session_cookie_name}=""')
        and "Max-Age=0" in header
        and "Path=/api/v1" in header
        for header in clear_headers
    )


@pytest.mark.parametrize("purpose", ("signup", "login"))
def test_change_cancels_the_current_flow_and_old_code_cannot_authenticate(
    nyay8_context,
    purpose: str,
) -> None:
    """S-05 Change retires server state; clearing React state is insufficient."""

    client, _, factory, sender = nyay8_context
    if purpose == "signup":
        started = client.post(
            "/api/v1/auth/student/register",
            json=login_contract._registration_body(),
            headers={"Idempotency-Key": "nyay8-signup-cancel"},
        )
        assert started.status_code == 202
        flow_token = client.cookies.get(settings.otp_flow_cookie_name)
        code = sender.sent[-1][1]
        verify_endpoint = "/api/v1/auth/student/otp/verify"
    else:
        login_contract._create_account(client, sender)
        flow_token, code = login_contract._start_login(client, sender)
        verify_endpoint = "/api/v1/auth/student/login/otp/verify"
    assert flow_token and code

    cancelled = client.post(
        "/api/v1/auth/student/otp/cancel",
        json={},
    )
    cookie_after_cancel = client.cookies.get(
        settings.otp_flow_cookie_name,
        domain="testserver.local",
        path="/api/v1",
    )
    signup_restart_cookie = client.cookies.get(
        settings.otp_flow_cookie_name,
        domain="testserver.local",
        path="/api/v1/auth/student/register",
    )
    restart_cookie_headers = [
        header
        for header in cancelled.headers.get_list("set-cookie")
        if header.startswith(f"{settings.otp_flow_cookie_name}={flow_token}")
    ]
    with factory() as session:
        flow_after_cancel = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash
                == otp_flow_service.flow_token_hash(flow_token)
            )
        )
        assert flow_after_cancel is not None
        state_after_cancel = flow_after_cancel.state
        masked_identity_retained = (
            flow_after_cancel.destination_masked_ct is not None
        )

    # A captured pre-cancel cookie and its matching code are both retired.
    login_contract._use_flow_cookie(client, flow_token)
    old_code_result = client.post(verify_endpoint, json={"code": code})
    auth_cookie_after_old_code = client.cookies.get(
        settings.auth_session_cookie_name
    )

    observed = {
        "cancel_status": cancelled.status_code,
        "cancel_projection": cancelled.json(),
        "cookie_cleared": cookie_after_cancel is None,
        "signup_restart_cookie": signup_restart_cookie,
        "signup_restart_cookie_restricted": (
            len(restart_cookie_headers) == 1
            and "Path=/api/v1/auth/student/register" in restart_cookie_headers[0]
            and "HttpOnly" in restart_cookie_headers[0]
            and "SameSite=strict" in restart_cookie_headers[0]
        ),
        "flow_state": state_after_cancel,
        "masked_identity_retained": masked_identity_retained,
        "old_code_status": old_code_result.status_code,
        "auth_cookie_minted": auth_cookie_after_old_code is not None,
    }
    assert observed == {
        "cancel_status": 200,
        "cancel_projection": otp_flow_service.unavailable_state(),
        "cookie_cleared": True,
        "signup_restart_cookie": flow_token if purpose == "signup" else None,
        "signup_restart_cookie_restricted": purpose == "signup",
        "flow_state": "consumed",
        "masked_identity_retained": False,
        "old_code_status": 401,
        "auth_cookie_minted": False,
    }


def test_stale_consumed_token_cannot_cancel_a_new_login_challenge(
    nyay8_context,
) -> None:
    """An older flow cannot use the shared authority to retire its successor."""

    client, _, factory, sender = nyay8_context
    login_contract._create_account(client, sender)
    stale_token, active_code = login_contract._start_login(client, sender)
    assert stale_token and active_code

    replacement = client.post(
        "/api/v1/auth/student/login/otp/start",
        json={"mobile": "9876543210"},
    )
    current_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert replacement.status_code == 202
    assert current_token and current_token != stale_token

    login_contract._use_flow_cookie(client, stale_token)
    stale_cancel = client.post("/api/v1/auth/student/otp/cancel", json={})
    with factory() as session:
        current_flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash
                == otp_flow_service.flow_token_hash(current_token)
            )
        )
        assert current_flow is not None
        current_challenge = session.get(OtpChallenge, current_flow.challenge_id)
        current_state_after_stale_cancel = current_flow.state
        challenge_state_after_stale_cancel = (
            current_challenge.delivery_state if current_challenge else None
        )

    login_contract._use_flow_cookie(client, current_token)
    verified = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": active_code},
    )

    assert stale_cancel.status_code == 200
    assert stale_cancel.json() == otp_flow_service.unavailable_state()
    assert current_state_after_stale_cancel in {"pending", "code_sent", "locked"}
    assert challenge_state_after_stale_cancel == "active"
    assert verified.status_code == 200
    assert client.cookies.get(settings.auth_session_cookie_name)


def test_signup_cancel_retires_pending_identity_so_a_fresh_signup_can_complete(
    nyay8_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persona Change must not strand the mobile behind a decoy registration."""

    client, _, _, sender = nyay8_context
    fixed = datetime.now(timezone.utc)
    clock = {"now": fixed}
    monkeypatch.setattr(auth_student, "_now", lambda: clock["now"])
    first = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-cancelled-signup-first"},
    )
    first_token = client.cookies.get(settings.otp_flow_cookie_name)
    first_code = sender.sent[-1][1]
    assert first.status_code == 202
    assert first_token and first_code

    cancelled = client.post("/api/v1/auth/student/otp/cancel", json={})
    clock["now"] = fixed + timedelta(
        seconds=settings.otp_resend_cooldown_seconds + 1
    )
    sent_before_restart = len(sender.sent)
    restarted = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-cancelled-signup-restart"},
    )
    replacement_token = client.cookies.get(settings.otp_flow_cookie_name)
    replacement_code = sender.sent[-1][1]
    verified = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"code": replacement_code},
    )

    assert cancelled.status_code == 200
    assert restarted.status_code == 202
    assert len(sender.sent) == sent_before_restart + 1
    assert replacement_token and replacement_token != first_token
    assert replacement_code != first_code
    assert verified.status_code == 200
    assert client.cookies.get(settings.auth_session_cookie_name)


def test_signup_restart_preserves_the_existing_otp_cooldown(
    nyay8_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel cannot become a resend-cooldown bypass."""

    client, _, _, sender = nyay8_context
    fixed = datetime.now(timezone.utc)
    monkeypatch.setattr(auth_student, "_now", lambda: fixed)
    started = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-cooldown-first"},
    )
    assert started.status_code == 202 and sender.sent
    cancelled = client.post("/api/v1/auth/student/otp/cancel", json={})
    sent_before_restart = len(sender.sent)
    restarted = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-cooldown-second"},
    )

    assert cancelled.status_code == 200
    assert restarted.status_code == 429
    assert restarted.json()["detail"]["code"] == "resend_cooldown"
    assert int(restarted.headers["retry-after"]) >= 1
    assert len(sender.sent) == sent_before_restart


def test_signup_restart_capability_is_bound_to_the_exact_cancelled_request(
    nyay8_context,
) -> None:
    """A captured restart bearer cannot rewrite provisional identity data."""

    client, _, factory, sender = nyay8_context
    first = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-restart-binding-first"},
    )
    flow_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert first.status_code == 202 and flow_token
    cancelled = client.post("/api/v1/auth/student/otp/cancel", json={})
    sent_before_mismatch = len(sender.sent)

    mismatch = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(first_name="Changed"),
        headers={"Idempotency-Key": "nyay8-restart-binding-mismatch"},
    )
    with factory() as session:
        cancelled_flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash
                == otp_flow_service.flow_token_hash(flow_token)
            )
        )
        marker = dict(cancelled_flow.metadata_json or {}) if cancelled_flow else {}

    assert cancelled.status_code == 200
    assert mismatch.status_code == 202
    assert len(sender.sent) == sent_before_mismatch
    assert marker.get("terminal_reason") == "user_cancelled"
    assert len(marker.get("request_fingerprint", "")) == 64
    assert "Aditi" not in str(marker)
    assert "9876543210" not in str(marker)


def test_non_restart_signup_cookie_cannot_intercept_fresh_registration(
    nyay8_context,
) -> None:
    """Only the exact cancellation marker may enter restart graph validation."""

    client, _, factory, sender = nyay8_context
    login_contract._create_account(client, sender)
    duplicate = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-neutralized-cookie-first"},
    )
    stale_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert duplicate.status_code == 202 and stale_token

    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash
                == otp_flow_service.flow_token_hash(stale_token)
            )
        )
        assert flow is not None
        assert flow.registration_id is None
        record = session.get(
            RegistrationIdempotencyRecord,
            flow.registration_idempotency_record_id,
        )
        assert record is not None and record.state == "neutralized"
        # Model the existing NYAY-4 lifecycle tombstone while the browser still
        # carries its broad OTP cookie. It is intentionally not a restart marker;
        # the stale flow/terminal-ledger graph must never enter restart validation.
        record.state = "retired"
        record.request_fingerprint = None
        record.request_fingerprint_version = None
        record.registration_id = None
        record.outbox_id = None
        record.outcome_code = "registration_replay_expired"
        session.commit()

    sent_before_fresh_request = len(sender.sent)
    fresh = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-neutralized-cookie-second"},
    )

    assert fresh.status_code == 202
    assert len(sender.sent) == sent_before_fresh_request


def test_exact_restart_marker_still_uses_strict_graph_validation(
    nyay8_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The marker preflight must not mask integrity failures in a real capability."""

    client, _, factory, sender = nyay8_context
    started = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-strict-restart-first"},
    )
    assert started.status_code == 202 and sender.sent
    restart_token = client.cookies.get(settings.otp_flow_cookie_name)
    cancelled = client.post("/api/v1/auth/student/otp/cancel", json={})
    assert cancelled.status_code == 200 and restart_token

    def reject_invalid_graph(*_args, **_kwargs):
        raise RuntimeError("strict restart graph sentinel")

    monkeypatch.setattr(otp_flow_service, "resolve_flow", reject_invalid_graph)
    with factory() as session, pytest.raises(
        RuntimeError,
        match="strict restart graph sentinel",
    ):
        otp_flow_service.restart_cancelled_signup(
            session,
            restart_token,
            StudentRegisterRequest.model_validate(
                login_contract._registration_body()
            ),
            "nyay8-strict-restart-second",
            now=auth_student._now(),
        )


def test_signup_cancel_cannot_extend_the_original_flow_expiry(
    nyay8_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancellation preserves—not renews—the server-owned bearer lifetime."""

    client, _, factory, sender = nyay8_context
    fixed = datetime.now(timezone.utc)
    clock = {"now": fixed}
    monkeypatch.setattr(auth_student, "_now", lambda: clock["now"])
    started = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-expiring-restart-first"},
    )
    flow_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert started.status_code == 202 and flow_token

    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash
                == otp_flow_service.flow_token_hash(flow_token)
            )
        )
        assert flow is not None
        flow.expires_at = fixed + timedelta(seconds=1)
        session.commit()

    cancelled = client.post("/api/v1/auth/student/otp/cancel", json={})
    restart_headers = [
        header
        for header in cancelled.headers.get_list("set-cookie")
        if header.startswith(f"{settings.otp_flow_cookie_name}={flow_token}")
    ]
    assert len(restart_headers) == 1
    assert "Max-Age=1" in restart_headers[0]

    sent_before_expired_restart = len(sender.sent)
    clock["now"] = fixed + timedelta(seconds=2)
    expired_restart = client.post(
        "/api/v1/auth/student/register",
        json=login_contract._registration_body(),
        headers={"Idempotency-Key": "nyay8-expiring-restart-second"},
    )

    assert expired_restart.status_code == 202
    assert len(sender.sent) == sent_before_expired_restart


@pytest.mark.parametrize(
    ("extra_name", "extra_value"),
    (("password", "not-an-authenticator"), ("email", "aditi@example.test")),
)
def test_login_start_rejects_password_and_alternate_identity_extras_without_state(
    nyay8_context,
    extra_name: str,
    extra_value: str,
) -> None:
    client, _, factory, _ = nyay8_context
    response = client.post(
        "/api/v1/auth/student/login/otp/start",
        json={"mobile": "9876543210", extra_name: extra_value},
    )
    assert response.status_code == 422
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OtpFlow)) == 0
        assert (
            session.scalar(select(func.count()).select_from(AuthSession)) == 0
        )


@pytest.mark.parametrize(
    ("extra_name", "extra_value"),
    (("password", "not-an-authenticator"), ("mobile", "9876543210")),
)
def test_login_verify_rejects_password_and_identity_extras_atomically(
    nyay8_context,
    extra_name: str,
    extra_value: str,
) -> None:
    client, _, factory, sender = nyay8_context
    login_contract._create_account(client, sender)
    flow_token, code = login_contract._start_login(client, sender)
    assert flow_token and code

    with factory() as session:
        active_sessions_before = session.scalar(
            select(func.count())
            .select_from(AuthSession)
            .where(AuthSession.status == "active")
        )
    rejected = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": code, extra_name: extra_value},
    )
    assert rejected.status_code == 422

    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash
                == otp_flow_service.flow_token_hash(flow_token)
            )
        )
        assert flow is not None and flow.state in {"pending", "code_sent"}
        challenge = session.get(OtpChallenge, flow.challenge_id)
        assert challenge is not None and challenge.consumed_at is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuthSession)
                .where(AuthSession.status == "active")
            )
            == active_sessions_before
        )
    assert client.cookies.get(settings.auth_session_cookie_name) is None
