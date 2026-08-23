"""SAATHI-448 — HTTP-boundary contract tests (critical #1-#4).

Uses the real router + a PRODUCTION-STYLE session dependency (commit on success,
rollback on error) and opens a FRESH session after each request to prove the
persisted truth — service-only single-session assertions are insufficient.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register tables)
from app.api.v1 import auth_student as ep
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.session import get_session
from app.db.models.audit import AuditEvent
from app.models.registration import (
    Consent,
    OtpChallenge,
    OtpFlow,
    OtpOutbox,
    OtpPurposeAuthority,
    OtpRateLimitBucket,
    RegistrationIdempotencyRecord,
    StudentProfile,
    StudentRegistration,
    User,
)
from app.services import otp_authority
from app.services.otp_sender import OtpSendError

# Schema builder: a create_all-equivalent template copy (see tests/dbtemplate.py).
from tests import dbtemplate


class Capturing:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._receipts: dict[str, tuple[str, str, str]] = {}

    def send_idempotent(
        self, destination: str, code: str, *, idempotency_token: str
    ) -> str:
        existing = self._receipts.get(idempotency_token)
        if existing is not None:
            assert existing[:2] == (destination, code)
            return existing[2]
        receipt = f"test-{len(self._receipts) + 1}"
        self._receipts[idempotency_token] = (destination, code, receipt)
        self.sent.append((destination, code))
        return receipt


class Failing:
    def send_idempotent(
        self, destination: str, code: str, *, idempotency_token: str
    ) -> None:
        raise OtpSendError("provider down")


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    dbtemplate.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def prod_session():  # mirrors app.db.session.get_session
        s = SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    sender = Capturing()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(ep.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = prod_session
    app.dependency_overrides[ep.get_otp_sender] = lambda: sender
    app.dependency_overrides[ep.get_outbox_session_factory] = lambda: SessionLocal
    client = TestClient(app, headers={"Origin": settings.cors_origins[0]})
    yield client, engine, SessionLocal, sender, app
    # Per-test engine: dispose() is the cleanup that matters. The old
    # drop_all here re-walked all 53 tables (~10 ms) to demolish a database
    # that was about to be discarded anyway.
    engine.dispose()


def _fresh(SessionLocal):
    return SessionLocal()


def _register(client, mobile="9876543210"):
    return client.post("/api/v1/auth/student/register", json={
        "first_name": "Aditi", "last_name": "Nair", "mobile": mobile,
        "dob": "2004-03-14", "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    })


def _registration_v2_body(**overrides):
    body = {
        "first_name": "Aditi",
        "middle_name": None,
        "last_name": "Nair",
        "mobile": "9876543210",
        "dob": "2004-03-14",
        "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    }
    body.update(overrides)
    return body


_REGISTRATION_ACCEPTED = {
    "status": "accepted",
    "next": "otp",
    "expires_in_seconds": 300,
    "resend_after_seconds": 30,
}


def test_registration_v2_returns_uniform_safe_202_and_persists_separate_legal_rows(
    ctx,
):
    client, _engine, SessionLocal, sender, _app = ctx

    response = client.post(
        "/api/v1/auth/student/register",
        headers={"Idempotency-Key": "reg-v2-legal-contract"},
        json=_registration_v2_body(),
    )

    assert response.status_code == 202
    assert response.json() == _REGISTRATION_ACCEPTED
    assert len(sender.sent) == 1
    with _fresh(SessionLocal) as session:
        consents = session.scalars(select(Consent).order_by(Consent.purpose)).all()
        assert [
            (row.purpose, row.accepted, row.policy_version)
            for row in consents
        ] == [
            ("privacy_notice", True, "privacy-2026-08.v1"),
            ("terms", True, "terms-2026-08.v1"),
        ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("terms_accepted", None),
        ("terms_accepted", False),
        ("terms_version", None),
        ("terms_version", ""),
        ("privacy_notice_acknowledged", None),
        ("privacy_notice_acknowledged", False),
        ("privacy_notice_version", None),
        ("privacy_notice_version", ""),
    ],
)
def test_registration_v2_rejects_missing_or_false_legal_authority_without_writes(
    ctx, field, value
):
    client, _engine, SessionLocal, sender, _app = ctx
    body = _registration_v2_body()
    if value is None:
        body.pop(field)
    else:
        body[field] = value

    response = client.post("/api/v1/auth/student/register", json=body)

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == field
    assert sender.sent == []
    with _fresh(SessionLocal) as session:
        for model in (
            StudentRegistration,
            Consent,
            OtpChallenge,
            OtpOutbox,
            AuditEvent,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    ("field", "omit", "code"),
    [
        pytest.param(
            "terms_accepted",
            True,
            "terms_acceptance_required",
            id="missing-terms",
        ),
        pytest.param(
            "terms_accepted",
            False,
            "terms_acceptance_required",
            id="false-terms",
        ),
        pytest.param(
            "privacy_notice_acknowledged",
            True,
            "privacy_notice_acknowledgement_required",
            id="missing-privacy",
        ),
        pytest.param(
            "privacy_notice_acknowledged",
            False,
            "privacy_notice_acknowledgement_required",
            id="false-privacy",
        ),
    ],
)
@pytest.mark.parametrize("hostile_precondition", ["sender-unavailable", "rate-exhausted"])
def test_fresh_legal_validation_precedes_sender_and_rate_budget_work(
    ctx,
    monkeypatch,
    field,
    omit,
    code,
    hostile_precondition,
):
    client, _engine, SessionLocal, sender, app = ctx
    body = _registration_v2_body()
    if omit:
        body.pop(field)
    else:
        body[field] = False

    if hostile_precondition == "sender-unavailable":
        app.dependency_overrides[ep.get_otp_sender] = lambda: None
    else:

        def exhausted_budget(*_args, **_kwargs):
            raise otp_authority.RateLimitExceeded(retry_after_seconds=60)

        monkeypatch.setattr(
            ep.otp_authority,
            "consume_rate_budgets",
            exhausted_budget,
        )

    response = client.post("/api/v1/auth/student/register", json=body)

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": code,
        "field": field,
        "message": "Request failed",
    }
    assert sender.sent == []
    with _fresh(SessionLocal) as session:
        for model in (
            User,
            StudentRegistration,
            StudentProfile,
            Consent,
            RegistrationIdempotencyRecord,
            OtpPurposeAuthority,
            OtpFlow,
            OtpChallenge,
            OtpOutbox,
            OtpRateLimitBucket,
            AuditEvent,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def test_registration_known_mobile_has_same_safe_contract_without_overwrite(ctx):
    client, _engine, SessionLocal, sender, _app = ctx
    first = client.post(
        "/api/v1/auth/student/register", json=_registration_v2_body()
    )
    second = client.post(
        "/api/v1/auth/student/register",
        json=_registration_v2_body(
            first_name="Other", last_name="Person", dob="2001-01-01"
        ),
    )

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json() == _REGISTRATION_ACCEPTED
    with _fresh(SessionLocal) as session:
        rows = session.scalars(select(StudentRegistration)).all()
        assert len(rows) == 1
        assert rows[0].first_name == "Aditi"


def test_lockout_persists_across_http_errors(ctx):
    client, engine, SessionLocal, sender, app = ctx
    r = _register(client)
    assert r.status_code == 202
    assert len(sender.sent) == 1  # OTP delivered exactly once on register
    with _fresh(SessionLocal) as s:
        registration = s.scalar(select(StudentRegistration))
        assert registration is not None
        registration_id = registration.id

    for expected_attempts in (1, 2):
        resp = client.post(
            "/api/v1/auth/student/otp/verify", json={"code": "000000"}
        )
        assert resp.status_code in (401, 423)
        with _fresh(SessionLocal) as s:  # FRESH session proves persistence
            authority = s.scalar(
                select(OtpPurposeAuthority).where(
                    OtpPurposeAuthority.registration_id == registration_id,
                    OtpPurposeAuthority.purpose == "signup",
                )
            )
            assert authority is not None
            assert authority.failed_attempts == expected_attempts
    # 3rd wrong → lockout persisted
    resp = client.post(
        "/api/v1/auth/student/otp/verify", json={"code": "111111"}
    )
    assert resp.status_code == 423
    with _fresh(SessionLocal) as s:
        authority = s.scalar(
            select(OtpPurposeAuthority).where(
                OtpPurposeAuthority.registration_id == registration_id,
                OtpPurposeAuthority.purpose == "signup",
            )
        )
        assert authority is not None
        assert authority.failed_attempts == 3
        assert authority.locked_until is not None
    # Correct OTP now blocked by lockout
    code = sender.sent[-1][1]
    resp = client.post("/api/v1/auth/student/otp/verify", json={"code": code})
    assert resp.status_code == 423 and resp.json()["detail"]["code"] == "locked"


def test_recovery_indistinguishable_known_vs_unknown(ctx):
    client, engine, SessionLocal, sender, app = ctx
    _register(client, mobile="9876543210")
    known_states = []
    for _ in range(2):
        rk = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"})
        assert rk.status_code == 202
        known_states.append(rk.json())
    unknown_states = []
    for _ in range(2):
        ru = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9999993210"})
        assert ru.status_code == 202
        unknown_states.append(ru.json())
    assert known_states == unknown_states
    serialized = str(known_states + unknown_states)
    assert "registration_id" not in serialized
    assert "recovery_id" not in serialized


@pytest.mark.parametrize("bad", ["987654321", "98765432101", "987654321012", "98765abc10", ""])
def test_recovery_mobile_validation(ctx, bad):
    client, *_ = ctx
    assert client.post("/api/v1/auth/student/recovery/start", json={"mobile": bad}).status_code == 422


def test_fail_closed_when_no_provider(ctx):
    client, engine, SessionLocal, sender, app = ctx
    app.dependency_overrides[ep.get_otp_sender] = lambda: None
    r = _register(client)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "otp_delivery_unavailable"
    with _fresh(SessionLocal) as s:
        assert s.scalar(select(StudentRegistration)) is None  # nothing persisted


def test_sender_failure_preserves_safe_retryable_flow(ctx):
    client, engine, SessionLocal, sender, app = ctx
    app.dependency_overrides[ep.get_otp_sender] = lambda: Failing()
    r = _register(client)
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"
    with _fresh(SessionLocal) as s:
        assert s.scalar(select(StudentRegistration)) is not None
        outbox = s.scalar(select(OtpOutbox))
        assert outbox is not None and outbox.status == "failed"


def test_register_conflict_and_idempotent_replay(ctx):
    client, engine, SessionLocal, sender, app = ctx
    a = client.post("/api/v1/auth/student/register", headers={"Idempotency-Key": "k1"}, json=_registration_v2_body())
    assert a.status_code == 202
    b = client.post("/api/v1/auth/student/register", headers={"Idempotency-Key": "k1"}, json=_registration_v2_body())
    assert b.status_code == 202 and b.json() == a.json()
    mismatch = client.post("/api/v1/auth/student/register", headers={"Idempotency-Key": "k1"}, json=_registration_v2_body(first_name="Other", last_name="Person", dob="2001-01-01"))
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "idempotency_conflict"
    c = client.post("/api/v1/auth/student/register", json=_registration_v2_body(first_name="Other", last_name="Person", dob="2001-01-01"))
    assert c.status_code == 202
    assert c.json().keys() == a.json().keys()
    with _fresh(SessionLocal) as s:
        assert len(s.scalars(select(StudentRegistration)).all()) == 1


@pytest.mark.parametrize(
    ("payload", "field", "forbidden_value"),
    [
        ({"mobile": "987654321"}, "mobile", "987654321"),
        ({"mobile": "98765432101"}, "mobile", "98765432101"),
        ({"mobile": "987654321012"}, "mobile", "987654321012"),
        ({"dob": "2030-01-01"}, "dob", "2030-01-01"),
        ({"first_name": ""}, "first_name", ""),
        ({"first_name": "Aditi<script>"}, "first_name", "Aditi<script>"),
        ({"first_name": "A" * 101}, "first_name", "A" * 101),
    ],
)
def test_production_validation_errors_are_typed_without_pii_echo(
    ctx, payload, field, forbidden_value
):
    client, *_ = ctx
    body = {
        "first_name": "Aditi",
        "last_name": "Nair",
        "mobile": "9876543210",
        "dob": "2004-03-14",
        "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
        **payload,
    }
    response = client.post("/api/v1/auth/student/register", json=body)
    assert response.status_code == 422
    result = response.json()
    assert result["detail"]["code"] == (
        "invalid_date_of_birth" if field == "dob" else "validation_error"
    )
    assert result["detail"]["field"] == field
    serialized = response.text
    if forbidden_value:
        assert forbidden_value not in serialized
    assert "input" not in serialized


def test_production_http_errors_preserve_typed_endpoint_contract(ctx):
    client, *_ = ctx
    response = client.post(
        "/api/v1/auth/student/register",
        json={
            "first_name": "Aditi",
            "last_name": "Nair",
            "mobile": "9876543210",
            "dob": "2004-03-14",
            "terms_accepted": False,
            "terms_version": "terms-2026-08.v1",
            "privacy_notice_acknowledged": True,
            "privacy_notice_version": "privacy-2026-08.v1",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "terms_acceptance_required"
