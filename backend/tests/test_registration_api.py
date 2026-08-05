"""SAATHI-448 — HTTP-boundary contract tests (critical #1-#4).

Uses the real router + a PRODUCTION-STYLE session dependency (commit on success,
rollback on error) and opens a FRESH session after each request to prove the
persisted truth — service-only single-session assertions are insufficient.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register tables)
from app.api.v1 import auth_student as ep
from app.core.exceptions import register_exception_handlers
from app.db.base import Base
from app.db.session import get_session
from app.models.registration import OtpChallenge, StudentRegistration
from app.services.otp_sender import OtpSendError

# Schema builder: a create_all-equivalent template copy (see tests/dbtemplate.py).
from tests import dbtemplate


class Capturing:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, destination: str, code: str) -> None:
        self.sent.append((destination, code))


class Failing:
    def send(self, destination: str, code: str) -> None:
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
    client = TestClient(app)
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
        "dob": "2004-03-14", "consent": {"accepted": True},
    })


def test_lockout_persists_across_http_errors(ctx):
    client, engine, SessionLocal, sender, app = ctx
    r = _register(client)
    assert r.status_code == 201
    reg_id = r.json()["registration_id"]
    assert len(sender.sent) == 1  # OTP delivered exactly once on register

    for expected_attempts in (1, 2):
        resp = client.post("/api/v1/auth/student/otp/verify", json={"registration_id": reg_id, "code": "000000x"[:6]})
        assert resp.status_code in (401, 423)
        with _fresh(SessionLocal) as s:  # FRESH session proves persistence
            ch = s.scalar(select(OtpChallenge).where(OtpChallenge.registration_id == uuid.UUID(reg_id), OtpChallenge.consumed_at.is_(None)))
            assert ch.attempts == expected_attempts
    # 3rd wrong → lockout persisted
    resp = client.post("/api/v1/auth/student/otp/verify", json={"registration_id": reg_id, "code": "111111"})
    assert resp.status_code == 423
    with _fresh(SessionLocal) as s:
        ch = s.scalar(select(OtpChallenge).where(OtpChallenge.registration_id == uuid.UUID(reg_id), OtpChallenge.consumed_at.is_(None)))
        assert ch.attempts == 3 and ch.locked_until is not None
    # Correct OTP now blocked by lockout
    code = sender.sent[-1][1]
    resp = client.post("/api/v1/auth/student/otp/verify", json={"registration_id": reg_id, "code": code})
    assert resp.status_code == 423 and resp.json()["detail"]["code"] == "locked"


def test_recovery_indistinguishable_known_vs_unknown(ctx):
    client, engine, SessionLocal, sender, app = ctx
    _register(client, mobile="9876543210")
    ids = set()
    for _ in range(2):
        rk = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"})
        assert rk.status_code == 202
        ids.add(rk.json()["recovery_id"])
    for _ in range(2):
        ru = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9999999999"})
        assert ru.status_code == 202
        ids.add(ru.json()["recovery_id"])
    assert len(ids) == 4  # every id distinct → repetition cannot infer known/unknown
    reg = None
    with _fresh(SessionLocal) as s:
        reg = s.scalar(select(StudentRegistration))
    assert str(reg.id) not in ids and reg.id.hex not in ids  # never the registration UUID


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


def test_sender_failure_rolls_back(ctx):
    client, engine, SessionLocal, sender, app = ctx
    app.dependency_overrides[ep.get_otp_sender] = lambda: Failing()
    r = _register(client)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "otp_delivery_failed"
    with _fresh(SessionLocal) as s:
        assert s.scalar(select(StudentRegistration)) is None  # transactional rollback


def test_register_conflict_and_idempotent_replay(ctx):
    client, engine, SessionLocal, sender, app = ctx
    a = client.post("/api/v1/auth/student/register", headers={"Idempotency-Key": "k1"}, json={
        "first_name": "Aditi", "last_name": "Nair", "mobile": "9876543210", "dob": "2004-03-14", "consent": {"accepted": True}})
    assert a.status_code == 201
    b = client.post("/api/v1/auth/student/register", headers={"Idempotency-Key": "k1"}, json={
        "first_name": "Aditi", "last_name": "Nair", "mobile": "9876543210", "dob": "2004-03-14", "consent": {"accepted": True}})
    assert b.status_code == 201 and b.json()["registration_id"] == a.json()["registration_id"]  # idempotent replay
    reg_id = uuid.UUID(a.json()["registration_id"])
    with _fresh(SessionLocal) as s:
        reg = s.get(StudentRegistration, reg_id)
        if reg:
            reg.status = "otp_verified"
            s.commit()
    c = client.post("/api/v1/auth/student/register", json={
        "first_name": "Other", "last_name": "Person", "mobile": "9876543210", "dob": "2001-01-01", "consent": {"accepted": True}})
    assert c.status_code == 409  # mobile conflict
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
        "consent": {"accepted": True},
        **payload,
    }
    response = client.post("/api/v1/auth/student/register", json=body)
    assert response.status_code == 422
    result = response.json()
    assert result["detail"]["code"] == "validation_error"
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
            "consent": {"accepted": False},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "consent_required"
