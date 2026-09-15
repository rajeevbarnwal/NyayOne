"""NYAY-85 F3: Change number retires the server-side recovery capability."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.api.v1 import auth_student
from app.core.config import settings
from app.models.registration import OtpChallenge, OtpFlow, OtpOutbox
from app.services import otp_flow_service
from tests import test_student_login_session as login_contract


@pytest.fixture()
def recovery_context():
    context = login_contract._context()
    try:
        yield context
    finally:
        context[0].close()
        context[1].dispose()


def _start_recovery(client, sender, *, known: bool = True):
    if known:
        login_contract._create_account(client, sender)
    started = client.post(
        "/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"}
    )
    assert started.status_code == 202
    token = client.cookies.get(settings.otp_flow_cookie_name)
    assert token
    return token, sender.sent[-1][1] if known else "123456"


@pytest.mark.parametrize("already_verified", (False, True))
def test_change_number_retires_pending_and_verified_recovery_capabilities(
    recovery_context, already_verified: bool
) -> None:
    client, _, factory, sender = recovery_context
    saved_token, code = _start_recovery(client, sender)
    if already_verified:
        verified = client.post(
            "/api/v1/auth/student/recovery/verify", json={"code": code}
        )
        assert verified.status_code == 200
        assert verified.json()["status"] == "verified"

    cancelled = client.post("/api/v1/auth/student/otp/cancel", json={})
    assert cancelled.status_code == 200
    assert cancelled.json() == otp_flow_service.unavailable_state()
    assert client.cookies.get(settings.otp_flow_cookie_name) is None
    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash == otp_flow_service.flow_token_hash(saved_token)
            )
        )
        assert flow is not None
        assert flow.state == "consumed"
        assert flow.consumed_at is not None
        assert flow.destination_masked_ct is None
        challenge = session.get(OtpChallenge, flow.challenge_id)
        assert challenge is not None
        assert challenge.consumed_at is not None
        assert challenge.delivery_state != "active"

    # Replaying the saved HttpOnly cookie is denied by server state, not merely
    # by the response's cookie deletion. Verified recovery cannot complete, and
    # an unverified code cannot create a new proof after cancellation.
    for endpoint, body in (
        ("complete", {}),
        ("verify", {"code": code}),
        ("complete", {}),
    ):
        login_contract._use_flow_cookie(client, saved_token)
        replay = client.post(f"/api/v1/auth/student/recovery/{endpoint}", json=body)
        assert replay.status_code == 401
        assert replay.json()["detail"]["code"] == "recovery_failed"
    assert client.cookies.get(settings.auth_session_cookie_name) is None


def test_change_number_retires_decoy_recovery_without_disclosing_identity(
    recovery_context,
) -> None:
    client, _, factory, sender = recovery_context
    token, _ = _start_recovery(client, sender, known=False)
    assert sender.sent == []
    cancelled = client.post("/api/v1/auth/student/otp/cancel", json={})
    assert cancelled.status_code == 200
    assert cancelled.json() == otp_flow_service.unavailable_state()
    assert client.cookies.get(settings.otp_flow_cookie_name) is None
    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash == otp_flow_service.flow_token_hash(token)
            )
        )
        assert flow is not None
        assert flow.state == "consumed"
        assert flow.consumed_at is not None
        assert flow.registration_id is None
        assert flow.challenge_id is None
        assert flow.destination_masked_ct is None


def test_change_number_fences_pending_recovery_delivery(
    recovery_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, factory, sender = recovery_context
    login_contract._create_account(client, sender)
    monkeypatch.setattr(auth_student, "deliver_after_response", lambda *args: None)
    started = client.post(
        "/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"}
    )
    assert started.status_code == 202
    token = client.cookies.get(settings.otp_flow_cookie_name)
    assert token
    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash == otp_flow_service.flow_token_hash(token)
            )
        )
        challenge_id = flow.challenge_id
        assert session.get(OtpChallenge, challenge_id).delivery_state == "pending_delivery"

    cancelled = client.post("/api/v1/auth/student/otp/cancel", json={})
    assert cancelled.status_code == 200
    with factory() as session:
        challenge = session.get(OtpChallenge, challenge_id)
        assert challenge.delivery_state == "void"
        assert challenge.consumed_at is not None
        outboxes = list(
            session.scalars(select(OtpOutbox).where(OtpOutbox.challenge_id == challenge_id))
        )
        assert len(outboxes) == 1
        assert outboxes[0].status == "void"
        assert outboxes[0].claim_token_hash is None


def test_consumed_recovery_cookie_cannot_cancel_its_successor(recovery_context) -> None:
    client, _, factory, sender = recovery_context
    stale_token, code = _start_recovery(client, sender)
    replaced = client.post(
        "/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"}
    )
    assert replaced.status_code == 202
    current_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert current_token and current_token != stale_token
    login_contract._use_flow_cookie(client, stale_token)
    cancelled = client.post("/api/v1/auth/student/otp/cancel", json={})
    assert cancelled.status_code == 200
    assert cancelled.json() == otp_flow_service.unavailable_state()
    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.token_hash == otp_flow_service.flow_token_hash(current_token)
            )
        )
        assert flow is not None
        assert flow.state in {"pending", "code_sent"}
        assert session.get(OtpChallenge, flow.challenge_id).delivery_state == "active"
    login_contract._use_flow_cookie(client, current_token)
    verified = client.post("/api/v1/auth/student/recovery/verify", json={"code": code})
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
