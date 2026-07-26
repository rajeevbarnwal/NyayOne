"""SAATHI-448 adversarial HTTP-contract suite.

Ports every case from the independent QA probe
(`engineer_861b9f9_independent_qa_2026-07-26/native/http_contract_probe.json`)
into the repository test suite, asserting the CLOSED behaviour. Uses the real
router, a production-style session dependency (commit on success / rollback on
error) and a FRESH session after each request to prove persisted truth.
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
from app.db.base import Base
from app.db.session import get_session
from app.core.crypto import decrypt
from app.models.registration import (
    OtpChallenge,
    OtpOutbox,
    RecoverySession,
    StudentProfile,
    StudentRegistration,
)
from app.services import otp_outbox
from app.services.otp_sender import OtpSendError
from app.workers.otp_outbox_relay import relay_pending


class Capturing:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, destination: str, code: str) -> None:
        self.sent.append((destination, code))


class Failing:
    def send(self, destination: str, code: str) -> None:
        raise OtpSendError("provider down")


class _CommitFailSession(Session):
    """Session whose first commit() raises once, to force a commit failure."""

    arm = False

    def commit(self):  # type: ignore[override]
        if type(self).arm:
            type(self).arm = False
            raise RuntimeError("forced commit failure")
        return super().commit()


def _make_ctx(session_class=Session, sender=None, raise_server_exceptions=True):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=session_class)

    def prod_session():
        s = SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    sender = sender if sender is not None else Capturing()
    app = FastAPI()
    app.include_router(ep.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = prod_session
    app.dependency_overrides[ep.get_otp_sender] = lambda: sender
    app.dependency_overrides[ep.get_outbox_session_factory] = lambda: SessionLocal
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    return client, engine, SessionLocal, sender, app


@pytest.fixture()
def ctx():
    client, engine, SessionLocal, sender, app = _make_ctx()
    yield client, engine, SessionLocal, sender, app
    Base.metadata.drop_all(engine)


def _fresh(SessionLocal):
    return SessionLocal()


def _register(client, mobile="9876543210", key=None):
    headers = {"Idempotency-Key": key} if key else {}
    return client.post("/api/v1/auth/student/register", headers=headers, json={
        "first_name": "Aditi", "last_name": "Nair", "mobile": mobile,
        "dob": "2004-03-14", "consent": {"accepted": True},
    })


# --- probe: configured_provider_resolution --------------------------------- #
def test_configured_provider_resolves_non_none(monkeypatch):
    from app.core.config import settings
    from app.services import otp_sender

    monkeypatch.setattr(settings, "otp_delivery_enabled", True, raising=False)
    monkeypatch.setattr(settings, "otp_provider", "capturing", raising=False)
    assert otp_sender.build_otp_sender() is not None
    # http provider needs a URL, else fail closed
    monkeypatch.setattr(settings, "otp_provider", "http", raising=False)
    monkeypatch.setattr(settings, "otp_provider_url", None, raising=False)
    assert otp_sender.build_otp_sender() is None
    monkeypatch.setattr(settings, "otp_provider_url", "https://provider.example/send", raising=False)
    assert otp_sender.build_otp_sender() is not None


# --- probe: registration + exactly-one delivery ---------------------------- #
def test_register_delivers_exactly_once(ctx):
    client, engine, SessionLocal, sender, app = ctx
    r = _register(client)
    assert r.status_code == 201
    assert len(sender.sent) == 1  # exactly one delivery after commit
    with _fresh(SessionLocal) as s:
        ob = s.scalar(select(OtpOutbox))
        assert ob.status == "sent" and ob.delivered_at is not None
        assert ob.code_ct is None


def test_outbox_delivery_is_idempotent(ctx):
    client, engine, SessionLocal, sender, app = ctx
    r = _register(client)
    assert r.status_code == 201 and len(sender.sent) == 1
    with _fresh(SessionLocal) as s:
        ob = s.scalar(select(OtpOutbox))
        assert ob is not None
        assert otp_outbox.run_delivery(
            s, otp_outbox.DeliveryIntent(outbox_id=ob.id), sender, raise_on_failure=True
        )
    assert len(sender.sent) == 1


def test_failed_outbox_is_relayed_once_after_provider_recovers():
    client, engine, SessionLocal, sender, app = _make_ctx(sender=Failing())
    try:
        # Registration compensates provider failure, so exercise the durable
        # relay against a recovery outbox whose failure is intentionally hidden
        # from the anti-enumeration response.
        app.dependency_overrides[ep.get_otp_sender] = lambda: Capturing()
        registered = _register(client)
        reg_id = registered.json()["registration_id"]
        with SessionLocal() as session:
            reg = session.get(StudentRegistration, uuid.UUID(reg_id))
            reg.status = "otp_verified"
            session.commit()
        failing = Failing()
        app.dependency_overrides[ep.get_otp_sender] = lambda: failing
        response = client.post(
            "/api/v1/auth/student/recovery/start",
            json={"mobile": "9876543210"},
        )
        assert response.status_code == 202
        with SessionLocal() as session:
            failed = session.scalar(
                select(OtpOutbox)
                .where(OtpOutbox.purpose == "recovery")
                .order_by(OtpOutbox.created_at.desc())
            )
            assert failed is not None and failed.status == "failed"
            assert failed.code_ct is not None

        recovered = Capturing()
        first = relay_pending(
            session_factory=SessionLocal,
            sender=recovered,
        )
        second = relay_pending(
            session_factory=SessionLocal,
            sender=recovered,
        )
        assert first.delivered == 1 and first.failed == 0
        assert second.examined == 0
        assert len(recovered.sent) == 1
        with SessionLocal() as session:
            row = session.get(OtpOutbox, failed.id)
            assert row is not None and row.status == "sent" and row.code_ct is None
    finally:
        Base.metadata.drop_all(engine)


# --- probe: no_provider_fail_closed ---------------------------------------- #
def test_fail_closed_when_no_provider(ctx):
    client, engine, SessionLocal, sender, app = ctx
    app.dependency_overrides[ep.get_otp_sender] = lambda: None
    r = _register(client)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "otp_delivery_unavailable"
    with _fresh(SessionLocal) as s:
        assert s.scalar(select(StudentRegistration)) is None
    assert sender.sent == []


# --- probe: delivery_before_commit (forced commit failure) ------------------ #
def test_no_delivery_and_no_rows_on_commit_failure():
    _CommitFailSession.arm = True
    client, engine, SessionLocal, sender, app = _make_ctx(
        session_class=_CommitFailSession, raise_server_exceptions=False
    )
    try:
        r = _register(client)
        # Commit failed → server error, and critically:
        assert r.status_code == 500
        assert sender.sent == []  # zero delivery — never sent before commit
        with _fresh(SessionLocal) as s:
            assert s.scalar(select(StudentRegistration)) is None  # zero rows
    finally:
        _CommitFailSession.arm = False
        Base.metadata.drop_all(engine)


# --- probe: provider failure → rollback / no unusable committed challenge --- #
def test_provider_failure_leaves_no_rows(ctx):
    client, engine, SessionLocal, sender, app = ctx
    app.dependency_overrides[ep.get_otp_sender] = lambda: Failing()
    r = _register(client)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "otp_delivery_failed"
    with _fresh(SessionLocal) as s:
        # Compensating delete ran: no committed-but-unusable challenge remains.
        assert s.scalar(select(StudentRegistration)) is None
        assert s.scalar(select(OtpChallenge)) is None


# --- probe: idempotent_replay_without_provider ------------------------------ #
def test_idempotent_replay_without_provider(ctx):
    client, engine, SessionLocal, sender, app = ctx
    a = _register(client, key="k1")
    assert a.status_code == 201 and len(sender.sent) == 1
    # Provider now unavailable; replay must still succeed and NOT re-deliver.
    app.dependency_overrides[ep.get_otp_sender] = lambda: None
    b = _register(client, key="k1")
    assert b.status_code == 201
    assert b.json()["registration_id"] == a.json()["registration_id"]
    assert len(sender.sent) == 1  # no repeat delivery


# --- probe: otp_format (malformed → 422, no attempt consumed) --------------- #
@pytest.mark.parametrize("bad", ["x", "", "12345", "1234567", "12a456", "  "])
def test_otp_format_rejected_without_consuming_attempt(ctx, bad):
    client, engine, SessionLocal, sender, app = ctx
    r = _register(client)
    reg_id = r.json()["registration_id"]
    resp = client.post("/api/v1/auth/student/otp/verify", json={"registration_id": reg_id, "code": bad})
    assert resp.status_code == 422
    with _fresh(SessionLocal) as s:
        ch = s.scalar(select(OtpChallenge).where(OtpChallenge.registration_id == uuid.UUID(reg_id)))
        assert ch.attempts == 0  # malformed code never consumed an attempt


# --- probe: lockout persists across HTTP errors ----------------------------- #
def test_lockout_persists_across_http_errors(ctx):
    client, engine, SessionLocal, sender, app = ctx
    r = _register(client)
    reg_id = r.json()["registration_id"]
    for expected in (1, 2):
        resp = client.post("/api/v1/auth/student/otp/verify", json={"registration_id": reg_id, "code": "000000"})
        assert resp.status_code in (401, 423)
        with _fresh(SessionLocal) as s:
            ch = s.scalar(select(OtpChallenge).where(OtpChallenge.registration_id == uuid.UUID(reg_id), OtpChallenge.consumed_at.is_(None)))
            assert ch.attempts == expected
    resp = client.post("/api/v1/auth/student/otp/verify", json={"registration_id": reg_id, "code": "111111"})
    assert resp.status_code == 423
    code = sender.sent[-1][1]
    resp = client.post("/api/v1/auth/student/otp/verify", json={"registration_id": reg_id, "code": code})
    assert resp.status_code == 423 and resp.json()["detail"]["code"] == "locked"


# --- probe: recovery_identifier_shape + recovery_completion ----------------- #
def test_recovery_start_verify_complete(ctx):
    client, engine, SessionLocal, sender, app = ctx
    _register(client, mobile="9876543210")
    sender.sent.clear()
    start = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"})
    assert start.status_code == 202
    rid = start.json()["recovery_id"]
    # opaque id is never the registration UUID
    with _fresh(SessionLocal) as s:
        reg = s.scalar(select(StudentRegistration))
        assert rid != str(reg.id) and rid != reg.id.hex
    # a recovery OTP was delivered
    assert len(sender.sent) == 1
    code = sender.sent[-1][1]
    ok = client.post("/api/v1/auth/student/recovery/verify", json={"recovery_id": rid, "code": code})
    assert ok.status_code == 200 and ok.json()["status"] == "verified"
    done = client.post("/api/v1/auth/student/recovery/complete", json={"recovery_id": rid})
    assert done.status_code == 200


def test_recovery_rejects_registration_uuid_as_id(ctx):
    client, engine, SessionLocal, sender, app = ctx
    r = _register(client)
    reg_id = r.json()["registration_id"]
    # Using the registration UUID as a recovery id must fail uniformly.
    resp = client.post("/api/v1/auth/student/recovery/verify", json={"recovery_id": reg_id, "code": "123456"})
    assert resp.status_code == 401 and resp.json()["detail"]["code"] == "recovery_failed"


def test_recovery_wrong_and_unknown_uniform_failure(ctx):
    client, engine, SessionLocal, sender, app = ctx
    _register(client, mobile="9876543210")
    sender.sent.clear()
    start = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"})
    rid = start.json()["recovery_id"]
    wrong = client.post("/api/v1/auth/student/recovery/verify", json={"recovery_id": rid, "code": "000000"})
    unknown = client.post("/api/v1/auth/student/recovery/verify", json={"recovery_id": uuid.uuid4().hex, "code": "000000"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": {"code": "recovery_failed"}}


# --- probe: recovery_cooldown_abuse_control --------------------------------- #
def test_recovery_cooldown_limits_delivery(ctx):
    client, engine, SessionLocal, sender, app = ctx
    _register(client, mobile="9876543210")
    sender.sent.clear()
    a = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"})
    b = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"})
    assert a.status_code == b.status_code == 202
    assert a.json()["recovery_id"] != b.json()["recovery_id"]  # symmetric shape preserved
    assert len(sender.sent) == 1  # second immediate request is rate-limited (no new send)


# --- probe: recovery_provider_failure_enumeration --------------------------- #
def test_recovery_provider_failure_indistinguishable(ctx):
    client, engine, SessionLocal, sender, app = ctx
    _register(client, mobile="9876543210")
    app.dependency_overrides[ep.get_otp_sender] = lambda: Failing()
    known = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"})
    unknown = client.post("/api/v1/auth/student/recovery/start", json={"mobile": "9999999999"})
    # Provider outage must not change status/shape for known vs unknown.
    assert known.status_code == unknown.status_code == 202
    assert set(known.json().keys()) == set(unknown.json().keys()) == {"recovery_id"}


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
    assert len(ids) == 4
    with _fresh(SessionLocal) as s:
        reg = s.scalar(select(StudentRegistration))
    assert str(reg.id) not in ids and reg.id.hex not in ids


@pytest.mark.parametrize("bad", ["987654321", "98765432101", "987654321012", "98765abc10", ""])
def test_recovery_mobile_validation(ctx, bad):
    client, *_ = ctx
    assert client.post("/api/v1/auth/student/recovery/start", json={"mobile": bad}).status_code == 422


# --- guardian consent + verification status endpoints ----------------------- #
def test_guardian_consent_completion(ctx):
    client, engine, SessionLocal, sender, app = ctx
    r = client.post("/api/v1/auth/student/register", json={
        "first_name": "Minor", "last_name": "Student", "mobile": "9000000000",
        "dob": "2012-01-01", "consent": {"accepted": True}})
    reg_id = r.json()["registration_id"]
    done = client.post("/api/v1/auth/student/guardian-consent/complete", json={"registration_id": reg_id})
    assert done.status_code == 200 and done.json()["status"] == "verified"


def test_guardian_consent_not_required_for_adult(ctx):
    client, engine, SessionLocal, sender, app = ctx
    r = _register(client)
    reg_id = r.json()["registration_id"]
    resp = client.post("/api/v1/auth/student/guardian-consent/complete", json={"registration_id": reg_id})
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "guardian_consent_not_required"


def test_verification_status_transitions(ctx):
    client, engine, SessionLocal, sender, app = ctx
    r = _register(client)
    reg_id = r.json()["registration_id"]
    got = client.get("/api/v1/auth/student/verification/status", params={"registration_id": reg_id})
    assert got.status_code == 200 and got.json()["status"] == "pending"
    ok = client.post("/api/v1/auth/student/verification/status", json={"registration_id": reg_id, "status": "in_review"})
    assert ok.status_code == 200 and ok.json()["status"] == "in_review"
    ok2 = client.post("/api/v1/auth/student/verification/status", json={"registration_id": reg_id, "status": "verified"})
    assert ok2.status_code == 200
    # verified is terminal — cannot go back to pending
    bad = client.post("/api/v1/auth/student/verification/status", json={"registration_id": reg_id, "status": "pending"})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "invalid_transition"


def test_register_conflict_and_idempotent_replay(ctx):
    client, engine, SessionLocal, sender, app = ctx
    a = _register(client, key="k1")
    assert a.status_code == 201
    b = _register(client, key="k1")
    assert b.status_code == 201 and b.json()["registration_id"] == a.json()["registration_id"]
    c = client.post("/api/v1/auth/student/register", json={
        "first_name": "Other", "last_name": "Person", "mobile": "9876543210",
        "dob": "2001-01-01", "consent": {"accepted": True}})
    assert c.status_code == 409
    with _fresh(SessionLocal) as s:
        assert len(s.scalars(select(StudentRegistration)).all()) == 1


def test_academic_profile_requires_verified_otp_and_persists_encrypted(ctx):
    client, engine, SessionLocal, sender, app = ctx
    registered = _register(client)
    reg_id = registered.json()["registration_id"]
    payload = {
        "registration_id": reg_id,
        "college": "National Law School of India University",
        "year_of_study": "3rd year",
        "enrolment_number": "KA/1234/2023",
        "institutional_email": "aditi@nls.ac.in",
        "bar_enrolment_number": "D/1234/2024",
    }
    blocked = client.patch("/api/v1/auth/student/profile", json=payload)
    assert blocked.status_code == 403
    verified = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"registration_id": reg_id, "code": sender.sent[-1][1]},
    )
    assert verified.status_code == 200
    saved = client.patch("/api/v1/auth/student/profile", json=payload)
    assert saved.status_code == 200 and saved.json() == {"status": "saved"}
    with _fresh(SessionLocal) as s:
        profile = s.scalar(
            select(StudentProfile).where(
                StudentProfile.registration_id == uuid.UUID(reg_id)
            )
        )
        assert profile is not None
        assert decrypt(profile.enrolment_ct or "") == "KA/1234/2023"
        assert decrypt(profile.institutional_email_ct or "") == "aditi@nls.ac.in"
        persisted = " ".join(
            str(value)
            for value in (
                profile.enrolment_ct,
                profile.enrolment_hash,
                profile.institutional_email_ct,
                profile.institutional_email_hash,
                profile.bar_enrolment_ct,
                profile.bar_enrolment_hash,
            )
        )
        assert "KA/1234/2023" not in persisted
        assert "aditi@nls.ac.in" not in persisted
