"""Focused current-head HTTP contract for NYAY-4 cookie-owned OTP flows."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import auth_student, student_settings
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.session import get_session
from app.models.registration import (
    OtpFlow,
    OtpRateLimitBucket,
    RegistrationIdempotencyRecord,
    StudentRegistration,
)
from app.services import otp_flow_service, registration_service
from app.services.otp_sender import CapturingSender
from tests import dbtemplate


_KEYS = {
    "attempts_left",
    "destination_masked",
    "expires_in_seconds",
    "locked_for_seconds",
    "purpose",
    "resend_allowed",
    "resend_in_seconds",
    "status",
}


def _context(*, sender=None):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    dbtemplate.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def request_session():
        with factory() as session:
            try:
                yield session
            finally:
                session.rollback()

    sender = sender or CapturingSender()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_student.router, prefix="/api/v1")
    app.include_router(student_settings.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[auth_student.get_otp_sender] = lambda: sender
    app.dependency_overrides[
        auth_student.get_outbox_session_factory
    ] = lambda: factory
    client = TestClient(app, raise_server_exceptions=False)
    client.headers["Origin"] = settings.cors_origins[0]
    return client, engine, factory, sender


class _FailingIdempotentSender:
    def send_idempotent(
        self, destination: str, code: str, *, idempotency_token: str
    ) -> str:
        del destination, code, idempotency_token
        from app.services.otp_sender import OtpSendError

        raise OtpSendError("seeded provider failure")


def _registration(mobile: str = "9876543210") -> dict:
    return {
        "first_name": "Aditi",
        "last_name": "Nair",
        "mobile": mobile,
        "dob": "2004-03-14",
        "terms_accepted": True,
        "terms_version": "terms.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy.v1",
    }


def _assert_registration_accepted(state: dict) -> None:
    assert state == {
        "status": "accepted",
        "next": "otp",
        "expires_in_seconds": 300,
        "resend_after_seconds": 30,
    }


def _assert_pending(state: dict, purpose: str, last4: str) -> None:
    assert set(state) == _KEYS
    assert state["status"] == "pending"
    assert state["purpose"] == purpose
    assert state["destination_masked"] == f"••••••{last4}"
    for field in (
        "attempts_left",
        "expires_in_seconds",
        "locked_for_seconds",
        "resend_in_seconds",
    ):
        assert isinstance(state[field], int) and state[field] >= 0
    assert isinstance(state["resend_allowed"], bool)


def test_signup_replay_reissues_cookie_with_zero_database_and_provider_delta():
    client, engine, factory, sender = _context()
    try:
        headers = {"Idempotency-Key": "nyay4-signup-replay-0001"}
        first = client.post(
            "/api/v1/auth/student/register",
            headers=headers,
            json=_registration(),
        )
        assert first.status_code == 202
        _assert_registration_accepted(first.json())
        _assert_pending(
            client.get("/api/v1/auth/student/otp/state").json(),
            "signup",
            "3210",
        )
        assert len(sender.sent) == 1
        cookie = client.cookies.get(settings.otp_flow_cookie_name)
        assert cookie
        flow_cookie = first.headers.get_list("set-cookie")[0]
        assert "Path=/api/v1" in flow_cookie
        assert "HttpOnly" in flow_cookie
        assert "SameSite=strict" in flow_cookie
        assert "Secure" not in flow_cookie

        with factory() as session:
            before = (
                session.scalar(select(func.count(StudentRegistration.id))),
                session.scalar(select(func.count(OtpFlow.id))),
            )
        client.cookies.clear()
        replay = client.post(
            "/api/v1/auth/student/register",
            headers=headers,
            json=_registration(),
        )
        assert replay.status_code == 202
        _assert_registration_accepted(replay.json())
        _assert_pending(
            client.get("/api/v1/auth/student/otp/state").json(),
            "signup",
            "3210",
        )
        assert client.cookies.get(settings.otp_flow_cookie_name) == cookie
        assert len(sender.sent) == 1
        with factory() as session:
            after = (
                session.scalar(select(func.count(StudentRegistration.id))),
                session.scalar(select(func.count(OtpFlow.id))),
            )
        assert after == before
    finally:
        client.close()
        engine.dispose()


def test_signup_verify_uses_code_only_and_returns_terminal_projection():
    client, engine, _, sender = _context()
    try:
        created = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": "nyay4-signup-verify-0001"},
            json=_registration(),
        )
        assert created.status_code == 202
        code = sender.sent[-1][1]
        verified = client.post(
            "/api/v1/auth/student/otp/verify", json={"code": code}
        )
        assert verified.status_code == 200
        terminal = verified.json()
        onboarding = terminal.pop("onboarding")
        assert terminal == {
            "status": "authenticated",
            "purpose": "signup",
            "destination_masked": None,
            "attempts_left": None,
            "expires_in_seconds": None,
            "resend_in_seconds": None,
            "locked_for_seconds": None,
            "resend_allowed": False,
        }
        assert onboarding["profile_version"] == 1
        assert onboarding["completion_percent"] == 0
        assert onboarding["next_incomplete_section"] == "personal"
        assert onboarding["profile"]["personal"]["first_name"] == "Aditi"
        state = client.get("/api/v1/auth/student/otp/state")
        assert state.status_code == 200
        assert state.json()["status"] == "unavailable"
        assert client.cookies.get(settings.auth_session_cookie_name)
        assert client.cookies.get(settings.otp_flow_cookie_name) is None
        cookies = verified.headers.get_list("set-cookie")
        assert len(cookies) == 3
        session_headers = [
            item
            for item in cookies
            if item.startswith(f"{settings.auth_session_cookie_name}=")
        ]
        assert len(session_headers) == 2
        session_cookie = next(
            item for item in session_headers if "Max-Age=0" not in item
        )
        legacy_clear = next(
            item
            for item in session_headers
            if "Max-Age=0" in item and "Path=/api/v1" in item
        )
        assert "Path=/" in session_cookie
        assert "HttpOnly" in session_cookie
        assert "SameSite=lax" in session_cookie
        assert "Domain=" not in session_cookie
        assert "HttpOnly" in legacy_clear
        assert "SameSite=strict" in legacy_clear
        flow_clear = [
            item
            for item in cookies
            if item.startswith(f"{settings.otp_flow_cookie_name}=")
        ]
        assert len(flow_clear) == 1
        assert "Max-Age=0" in flow_clear[0]
        assert "Path=/api/v1" in flow_clear[0]
        assert "SameSite=strict" in flow_clear[0]
    finally:
        client.close()
        engine.dispose()


def test_duplicate_mobile_gets_same_safe_shape_without_rotating_real_flow():
    client, engine, factory, sender = _context()
    try:
        first = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": "nyay4-real-0001"},
            json=_registration(),
        )
        assert first.status_code == 202
        real_cookie = client.cookies.get(settings.otp_flow_cookie_name)
        delivered = len(sender.sent)

        duplicate = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": "nyay4-decoy-0001"},
            json={**_registration(), "first_name": "Different"},
        )
        assert duplicate.status_code == 202
        _assert_registration_accepted(duplicate.json())
        _assert_pending(
            client.get("/api/v1/auth/student/otp/state").json(),
            "signup",
            "3210",
        )
        assert len(sender.sent) == delivered
        assert client.cookies.get(settings.otp_flow_cookie_name) != real_cookie
        with factory() as session:
            assert session.scalar(select(func.count(StudentRegistration.id))) == 1
            assert session.scalar(select(func.count(OtpFlow.id))) == 2

        decoy_cookie = client.cookies.get(settings.otp_flow_cookie_name)
        with factory() as session:
            before = tuple(
                session.scalar(select(func.count(model.id)))
                for model in (StudentRegistration, OtpFlow)
            )
        replay = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": "nyay4-decoy-0001"},
            json={**_registration(), "first_name": "Different"},
        )
        assert replay.status_code == 202
        assert replay.json() == duplicate.json()
        assert client.cookies.get(settings.otp_flow_cookie_name) == decoy_cookie
        assert len(sender.sent) == delivered
        with factory() as session:
            after = tuple(
                session.scalar(select(func.count(model.id)))
                for model in (StudentRegistration, OtpFlow)
            )
        assert after == before

        mismatch = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": "nyay4-decoy-0001"},
            json={**_registration(), "first_name": "Mutated"},
        )
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "idempotency_conflict"
        assert len(sender.sent) == delivered
        with factory() as session:
            unchanged = tuple(
                session.scalar(select(func.count(model.id)))
                for model in (StudentRegistration, OtpFlow)
            )
        assert unchanged == before
    finally:
        client.close()
        engine.dispose()


def test_preflight_to_register_race_replays_neutral_winner_without_provider(
    tmp_path,
    monkeypatch,
):
    """A peer neutral winner after preflight is a typed replay, never a 500."""

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'neutral-winner-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    dbtemplate.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def request_session():
        with factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    sender = CapturingSender()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_student.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[auth_student.get_otp_sender] = lambda: sender
    app.dependency_overrides[
        auth_student.get_outbox_session_factory
    ] = lambda: factory
    origin = settings.cors_origins[0]
    race_key = "nyay4-neutral-preflight-register-race-0001"
    headers = {"Origin": origin, "Idempotency-Key": race_key}
    payload = {**_registration(), "first_name": "Duplicate"}
    fixed_now = datetime(2026, 8, 21, 14, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(auth_student, "_now", lambda: fixed_now)

    try:
        with TestClient(app, raise_server_exceptions=False) as seed_client:
            seeded = seed_client.post(
                "/api/v1/auth/student/register",
                headers={
                    "Origin": origin,
                    "Idempotency-Key": "nyay4-neutral-race-real-seed",
                },
                json=_registration(),
            )
            seeded_second = seed_client.post(
                "/api/v1/auth/student/register",
                headers={
                    "Origin": origin,
                    "Idempotency-Key": "nyay4-neutral-race-real-seed-2",
                },
                json=_registration("9876543211"),
            )
        assert seeded.status_code == seeded_second.status_code == 202
        delivered = len(sender.sent)

        original = registration_service.resolve_idempotent_replay
        checked = threading.Event()
        release = threading.Event()
        guard = threading.Lock()
        armed = True

        def pause_after_empty_preflight(session, key, request, *, now=None):
            nonlocal armed
            should_pause = False
            if key == race_key:
                with guard:
                    if armed:
                        armed = False
                        should_pause = True
            resolved = original(session, key, request, now=now)
            if should_pause:
                assert resolved is None
                # SQLite needs the read transaction released so the peer can
                # durably establish the exact winner at this deterministic gap.
                session.rollback()
                checked.set()
                assert release.wait(timeout=10)
            return resolved

        monkeypatch.setattr(
            registration_service,
            "resolve_idempotent_replay",
            pause_after_empty_preflight,
        )

        def target_request():
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/v1/auth/student/register",
                    headers=headers,
                    json=payload,
                )
                return (
                    response.status_code,
                    response.json(),
                    client.cookies.get(settings.otp_flow_cookie_name),
                )

        with ThreadPoolExecutor(max_workers=1) as executor:
            target = executor.submit(target_request)
            assert checked.wait(timeout=10)
            with TestClient(app, raise_server_exceptions=False) as peer_client:
                peer = peer_client.post(
                    "/api/v1/auth/student/register",
                    headers=headers,
                    json=payload,
                )
                peer_cookie = peer_client.cookies.get(
                    settings.otp_flow_cookie_name
                )
            release.set()
            target_status, target_body, target_cookie = target.result(timeout=10)

        assert peer.status_code == target_status == 202
        assert peer.json() == target_body
        assert peer_cookie == target_cookie
        assert len(sender.sent) == delivered
        key_hash = registration_service.registration_idempotency_key_hash(
            race_key
        )
        with factory() as session:
            record = session.scalar(
                select(RegistrationIdempotencyRecord).where(
                    RegistrationIdempotencyRecord.idempotency_key_hash
                    == key_hash
                )
            )
            assert record is not None and record.state == "neutralized"
            assert record.registration_id is None and record.outbox_id is None
            assert (
                session.scalar(
                    select(func.count(OtpFlow.id)).where(
                        OtpFlow.registration_idempotency_record_id == record.id
                    )
                )
                == 1
            )
            before = (
                session.scalar(select(func.count(StudentRegistration.id))),
                session.scalar(select(func.count(OtpFlow.id))),
                session.scalar(
                    select(func.count(RegistrationIdempotencyRecord.id))
                ),
            )

        with TestClient(app, raise_server_exceptions=False) as replay_client:
            exact = replay_client.post(
                "/api/v1/auth/student/register",
                headers=headers,
                json=payload,
            )
            mismatch = replay_client.post(
                "/api/v1/auth/student/register",
                headers=headers,
                json={**payload, "first_name": "Mutated"},
            )
        assert exact.status_code == 202 and exact.json() == target_body
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == "idempotency_conflict"
        assert len(sender.sent) == delivered
        with factory() as session:
            after = (
                session.scalar(select(func.count(StudentRegistration.id))),
                session.scalar(select(func.count(OtpFlow.id))),
                session.scalar(
                    select(func.count(RegistrationIdempotencyRecord.id))
                ),
            )
        assert after == before

        # Repeat the same deterministic gap with a different canonical body.
        # The paused request must observe the peer's fingerprint binding and
        # return typed 409 after preserving its already-consumed abuse budget.
        race_key = "nyay4-neutral-preflight-register-race-mismatch"
        headers = {"Origin": origin, "Idempotency-Key": race_key}
        bound_payload = {
            **_registration("9876543211"),
            "first_name": "Bound",
        }
        payload = {**bound_payload, "first_name": "CanonicalMutation"}
        checked = threading.Event()
        release = threading.Event()
        armed = True
        with factory() as session:
            rate_before = int(
                session.scalar(
                    select(
                        func.coalesce(
                            func.sum(OtpRateLimitBucket.request_count), 0
                        )
                    )
                )
                or 0
            )
            graphs_before = (
                session.scalar(select(func.count(StudentRegistration.id))),
                session.scalar(select(func.count(OtpFlow.id))),
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            target = executor.submit(target_request)
            assert checked.wait(timeout=10)
            with TestClient(app, raise_server_exceptions=False) as peer_client:
                peer = peer_client.post(
                    "/api/v1/auth/student/register",
                    headers=headers,
                    json=bound_payload,
                )
            release.set()
            target_status, target_body, target_cookie = target.result(timeout=10)

        assert peer.status_code == 202
        assert target_status == 409
        assert target_body["detail"]["code"] == "idempotency_conflict"
        assert target_body["detail"]["field"] == "Idempotency-Key"
        assert target_cookie is None
        assert len(sender.sent) == delivered
        key_hash = registration_service.registration_idempotency_key_hash(
            race_key
        )
        with factory() as session:
            record = session.scalar(
                select(RegistrationIdempotencyRecord).where(
                    RegistrationIdempotencyRecord.idempotency_key_hash
                    == key_hash
                )
            )
            assert record is not None and record.state == "neutralized"
            assert (
                session.scalar(
                    select(func.count(OtpFlow.id)).where(
                        OtpFlow.registration_idempotency_record_id == record.id
                    )
                )
                == 1
            )
            assert (
                session.scalar(select(func.count(StudentRegistration.id))),
                session.scalar(select(func.count(OtpFlow.id))),
            ) == (graphs_before[0], graphs_before[1] + 1)
            rate_after = int(
                session.scalar(
                    select(
                        func.coalesce(
                            func.sum(OtpRateLimitBucket.request_count), 0
                        )
                    )
                )
                or 0
            )
        assert rate_after - rate_before == 6

        # Force the alternate mobile-decoy dispatch gap: the route has already
        # classified the target as a duplicate before a peer binds the key.
        # A mismatched target must translate the unified resolver's typed 409,
        # not let RegistrationError escape as middleware 500.
        monkeypatch.setattr(
            registration_service,
            "resolve_idempotent_replay",
            original,
        )
        race_key = "nyay4-neutral-decoy-dispatch-race-mismatch"
        headers = {"Origin": origin, "Idempotency-Key": race_key}
        bound_payload = {**_registration(), "first_name": "DispatchBound"}
        payload = {**bound_payload, "first_name": "DispatchMutation"}
        checked = threading.Event()
        release = threading.Event()
        armed = True
        original_decoy = auth_student._decoy_signup_flow

        def pause_before_neutral_reservation(
            session,
            *,
            payload,
            idempotency_key,
            now,
        ):
            nonlocal armed
            should_pause = False
            if idempotency_key == race_key:
                with guard:
                    if armed:
                        armed = False
                        should_pause = True
            if should_pause:
                checked.set()
                assert release.wait(timeout=10)
            return original_decoy(
                session,
                payload=payload,
                idempotency_key=idempotency_key,
                now=now,
            )

        monkeypatch.setattr(
            auth_student,
            "_decoy_signup_flow",
            pause_before_neutral_reservation,
        )
        with factory() as session:
            rate_before = int(
                session.scalar(
                    select(
                        func.coalesce(
                            func.sum(OtpRateLimitBucket.request_count), 0
                        )
                    )
                )
                or 0
            )
            graphs_before = (
                session.scalar(select(func.count(StudentRegistration.id))),
                session.scalar(select(func.count(OtpFlow.id))),
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            target = executor.submit(target_request)
            assert checked.wait(timeout=10)
            with TestClient(app, raise_server_exceptions=False) as peer_client:
                peer = peer_client.post(
                    "/api/v1/auth/student/register",
                    headers=headers,
                    json=bound_payload,
                )
            release.set()
            target_status, target_body, target_cookie = target.result(timeout=10)

        assert peer.status_code == 202
        assert target_status == 409
        assert target_body["detail"]["code"] == "idempotency_conflict"
        assert target_body["detail"]["field"] == "Idempotency-Key"
        assert target_cookie is None
        assert len(sender.sent) == delivered
        key_hash = registration_service.registration_idempotency_key_hash(
            race_key
        )
        with factory() as session:
            record = session.scalar(
                select(RegistrationIdempotencyRecord).where(
                    RegistrationIdempotencyRecord.idempotency_key_hash
                    == key_hash
                )
            )
            assert record is not None and record.state == "neutralized"
            assert (
                session.scalar(
                    select(func.count(OtpFlow.id)).where(
                        OtpFlow.registration_idempotency_record_id == record.id
                    )
                )
                == 1
            )
            assert (
                session.scalar(select(func.count(StudentRegistration.id))),
                session.scalar(select(func.count(OtpFlow.id))),
            ) == (graphs_before[0], graphs_before[1] + 1)
            rate_after = int(
                session.scalar(
                    select(
                        func.coalesce(
                            func.sum(OtpRateLimitBucket.request_count), 0
                        )
                    )
                )
                or 0
            )
        assert rate_after - rate_before == 6
    finally:
        if "release" in locals():
            release.set()
        engine.dispose()


def test_exact_real_replay_does_not_require_a_provider_binding():
    client, engine, _, sender = _context()
    try:
        headers = {"Idempotency-Key": "nyay4-no-provider-replay-0001"}
        first = client.post(
            "/api/v1/auth/student/register",
            headers=headers,
            json=_registration(),
        )
        assert first.status_code == 202
        assert len(sender.sent) == 1
        client.app.dependency_overrides[auth_student.get_otp_sender] = lambda: None
        replay = client.post(
            "/api/v1/auth/student/register",
            headers=headers,
            json=_registration(),
        )
        assert replay.status_code == 202
        assert replay.json() == first.json()
        assert len(sender.sent) == 1
    finally:
        client.close()
        engine.dispose()


def test_every_flow_mutation_requires_one_trusted_origin_with_zero_rows():
    client, engine, factory, _ = _context()
    try:
        del client.headers["Origin"]
        rejected = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": "nyay4-no-origin-0001"},
            json=_registration(),
        )
        assert rejected.status_code == 403
        assert rejected.json()["detail"]["code"] == "csrf_origin_required"
        with factory() as session:
            assert session.scalar(select(func.count(StudentRegistration.id))) == 0
            assert session.scalar(select(func.count(OtpFlow.id))) == 0
    finally:
        client.close()
        engine.dispose()


def test_missing_flow_verify_is_typed_and_never_raises_internal_type_error():
    client, engine, _, _ = _context()
    try:
        rejected = client.post(
            "/api/v1/auth/student/otp/verify", json={"code": "123456"}
        )
        assert rejected.status_code == 401
        detail = rejected.json()["detail"]
        assert detail["code"] == "otp_failed"
        assert detail["otp_state"] == {
                "status": "unavailable",
                "purpose": None,
                "destination_masked": None,
                "attempts_left": None,
                "expires_in_seconds": None,
                "resend_in_seconds": None,
                "locked_for_seconds": None,
                "resend_allowed": False,
        }
    finally:
        client.close()
        engine.dispose()


def _terminal_erasure_parts(*, state: str, hard_deleted: bool):
    record = SimpleNamespace(
        id="ledger-row",
        state=state,
        registration_id=None,
        outbox_id=None,
        request_fingerprint=None,
        request_fingerprint_version=None,
        outcome_code="registration_replay_expired",
    )
    registration = None
    if not hard_deleted:
        registration = SimpleNamespace(
            status="deleted",
            deleted_at=datetime.now(timezone.utc),
            dob_hash_state="erased",
        )
    return record, registration


def test_complete_terminal_erasure_is_the_only_missing_flow_graph_denial():
    for state in ("retired", "erased"):
        for hard_deleted in (False, True):
            record, registration = _terminal_erasure_parts(
                state=state,
                hard_deleted=hard_deleted,
            )
            assert otp_flow_service._terminal_erasure_won(
                record=record,
                record_id="ledger-row",
                registration=registration,
                authority=None,
                flow=None,
            )

    record, registration = _terminal_erasure_parts(
        state="retired",
        hard_deleted=False,
    )
    malformed = (
        ("state", "pending"),
        ("registration_id", "registration-row"),
        ("outbox_id", "outbox-row"),
        ("request_fingerprint", "0" * 64),
        ("request_fingerprint_version", "v1"),
        ("outcome_code", "otp_delivery_failed"),
    )
    for field, unsafe in malformed:
        mutant = SimpleNamespace(**vars(record))
        setattr(mutant, field, unsafe)
        assert not otp_flow_service._terminal_erasure_won(
            record=mutant,
            record_id="ledger-row",
            registration=registration,
            authority=None,
            flow=None,
        )
    assert not otp_flow_service._terminal_erasure_won(
        record=record,
        record_id="different-ledger-row",
        registration=registration,
        authority=None,
        flow=None,
    )
    assert not otp_flow_service._terminal_erasure_won(
        record=record,
        record_id="ledger-row",
        registration=SimpleNamespace(
            status="otp_pending",
            deleted_at=None,
            dob_hash_state="verified",
        ),
        authority=None,
        flow=None,
    )
    for authority, flow in ((object(), None), (None, object()), (object(), object())):
        assert not otp_flow_service._terminal_erasure_won(
            record=record,
            record_id="ledger-row",
            registration=registration,
            authority=authority,
            flow=flow,
        )


def _activate_signup(client: TestClient, sender: CapturingSender) -> None:
    created = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": "nyay4-activate-signup-0001"},
        json=_registration(),
    )
    assert created.status_code == 202
    verified = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"code": sender.sent[-1][1]},
    )
    assert verified.status_code == 200


def test_login_flow_has_no_javascript_visible_handle_and_rotates_session():
    client, engine, _, sender = _context()
    try:
        _activate_signup(client, sender)
        before = len(sender.sent)
        started = client.post(
            "/api/v1/auth/student/login/otp/start",
            json={"mobile": "9876543210"},
        )
        assert started.status_code == 202
        _assert_pending(started.json(), "login", "3210")
        assert "login_id" not in started.text
        assert len(sender.sent) == before + 1
        verified = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"code": sender.sent[-1][1]},
        )
        assert verified.status_code == 200
        assert verified.json()["status"] == "authenticated"
        assert verified.json()["purpose"] == "login"
        assert verified.headers["cache-control"] == "private, no-store"
        assert verified.headers["vary"] == "Cookie"
    finally:
        client.close()
        engine.dispose()


def test_recovery_verified_cookie_is_reissued_and_deletion_consumes_proof():
    client, engine, _, sender = _context()
    try:
        _activate_signup(client, sender)
        started = client.post(
            "/api/v1/auth/student/recovery/start",
            json={"mobile": "9876543210"},
        )
        assert started.status_code == 202
        _assert_pending(started.json(), "recovery", "3210")
        verified = client.post(
            "/api/v1/auth/student/recovery/verify",
            json={"code": sender.sent[-1][1]},
        )
        assert verified.status_code == 200
        assert verified.json()["status"] == "verified"
        proof_cookie = next(
            item
            for item in verified.headers.get_list("set-cookie")
            if item.startswith(f"{settings.otp_flow_cookie_name}=")
        )
        assert (
            f"Max-Age={settings.otp_recovery_proof_ttl_seconds}"
            in proof_cookie
        )
        assert "Path=/api/v1" in proof_cookie
        assert "SameSite=strict" in proof_cookie

        deleted = client.post(
            "/api/v1/student/privacy/delete",
            json={"confirmation": "DELETE"},
        )
        assert deleted.status_code == 202
        assert set(deleted.json()) == {"request_id", "status"}
        assert client.cookies.get(settings.otp_flow_cookie_name) is None
        assert client.get("/api/v1/auth/student/otp/state").json()["status"] == "unavailable"
        replay = client.post(
            "/api/v1/student/privacy/delete",
            json={"confirmation": "DELETE"},
        )
        assert replay.status_code == 401
        assert replay.json()["detail"]["code"] == "authentication_required"
    finally:
        client.close()
        engine.dispose()


def test_repeated_login_start_has_identical_known_and_decoy_public_expiry(
    monkeypatch,
):
    client, engine, _, sender = _context()
    base = datetime.now(timezone.utc).replace(microsecond=0)
    clock = [base]
    monkeypatch.setattr(auth_student, "_now", lambda: clock[0])
    try:
        _activate_signup(client, sender)
        clock[0] = base + timedelta(seconds=1)
        known_first = client.post(
            "/api/v1/auth/student/login/otp/start",
            json={"mobile": "9876543210"},
        )
        decoy_first = client.post(
            "/api/v1/auth/student/login/otp/start",
            json={"mobile": "1111113210"},
        )
        assert known_first.status_code == decoy_first.status_code == 202
        assert known_first.json() == decoy_first.json()

        clock[0] = base + timedelta(
            seconds=settings.otp_resend_cooldown_seconds + 2
        )
        known_second = client.post(
            "/api/v1/auth/student/login/otp/start",
            json={"mobile": "9876543210"},
        )
        decoy_second = client.post(
            "/api/v1/auth/student/login/otp/start",
            json={"mobile": "1111113210"},
        )
        assert known_second.status_code == decoy_second.status_code == 202
        assert known_second.json() == decoy_second.json()
        assert (
            known_second.json()["expires_in_seconds"]
            == settings.otp_challenge_ttl_seconds
        )
    finally:
        client.close()
        engine.dispose()


def test_undelivered_real_and_decoy_signup_verify_fail_identically(monkeypatch):
    fixed = datetime.now(timezone.utc).replace(microsecond=0)
    monkeypatch.setattr(auth_student, "_now", lambda: fixed)
    client, engine, _, _ = _context(sender=_FailingIdempotentSender())
    try:
        real = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": "nyay4-provider-failure-real-0001"},
            json=_registration(),
        )
        assert real.status_code == 202
        real_failure = client.post(
            "/api/v1/auth/student/otp/verify", json={"code": "123456"}
        )

        decoy = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": "nyay4-provider-failure-decoy-0001"},
            json={**_registration(), "first_name": "Different"},
        )
        assert decoy.status_code == 202
        assert decoy.json() == real.json()
        decoy_failure = client.post(
            "/api/v1/auth/student/otp/verify", json={"code": "123456"}
        )

        assert real_failure.status_code == decoy_failure.status_code == 401
        assert real_failure.json() == decoy_failure.json()
        assert real_failure.json()["detail"]["code"] == "incorrect_otp"
        assert real_failure.json()["detail"]["otp_state"]["attempts_left"] == 2
    finally:
        client.close()
        engine.dispose()


def test_undelivered_real_and_decoy_login_recovery_fail_identically(
    monkeypatch,
):
    fixed = datetime.now(timezone.utc).replace(microsecond=0)
    monkeypatch.setattr(auth_student, "_now", lambda: fixed)
    cases = (
        (
            "/api/v1/auth/student/login/otp/start",
            "/api/v1/auth/student/login/otp/verify",
            "login_failed",
        ),
        (
            "/api/v1/auth/student/recovery/start",
            "/api/v1/auth/student/recovery/verify",
            "recovery_failed",
        ),
    )
    for start_path, verify_path, expected_code in cases:
        client, engine, _, sender = _context()
        try:
            _activate_signup(client, sender)
            client.app.dependency_overrides[
                auth_student.get_otp_sender
            ] = lambda: _FailingIdempotentSender()

            known = client.post(start_path, json={"mobile": "9876543210"})
            assert known.status_code == 202
            known_failure = client.post(
                verify_path, json={"code": "123456"}
            )

            decoy = client.post(start_path, json={"mobile": "1111113210"})
            assert decoy.status_code == 202
            assert decoy.json() == known.json()
            decoy_failure = client.post(
                verify_path, json={"code": "123456"}
            )

            assert known_failure.status_code == decoy_failure.status_code == 401
            assert known_failure.json() == decoy_failure.json()
            assert known_failure.json()["detail"]["code"] == expected_code
            assert (
                known_failure.json()["detail"]["otp_state"]["attempts_left"]
                == 2
            )
        finally:
            client.close()
            engine.dispose()
