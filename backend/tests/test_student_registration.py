"""SAATHI-421/448 — student registration schema, service and API tests."""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1.auth_student import router as auth_student_router
from app.core.crypto import decrypt, keyed_hash, otp_verifier
from app.db.base import Base
from app.db.session import get_session
import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.models.registration import StudentAuditEvent, GuardianConsent, OtpChallenge, StudentRegistration
from app.schemas.registration import StudentRegisterRequest
from app.services.registration_service import RegistrationError, register_student


def _req(**over):
    base = dict(
        first_name="Aditi", middle_name="Rani", last_name="Nair",
        mobile="9876543210", dob="2004-03-14", college="NLSIU",
        consent={"accepted": True, "policy_version": "dpdp-2023.v1"},
    )
    base.update(over)
    return StudentRegisterRequest(**base)


# ---- schema validation (422-equivalent) -----------------------------------
@pytest.mark.parametrize("bad", ["", "987654321", "98765432101", "987654321012", "98765abc10", "+919876543210"])
def test_mobile_rejected(bad):
    with pytest.raises(ValidationError):
        _req(mobile=bad)


def test_mobile_exact_10_ok():
    assert _req(mobile="9876543210").mobile == "9876543210"


@pytest.mark.parametrize("bad", ["2030-01-01", "2030-12-31"])
def test_future_dob_rejected(bad):
    with pytest.raises(ValidationError):
        _req(dob=bad)


def test_impossible_dob_rejected():
    with pytest.raises(ValidationError):
        _req(dob="2026-02-31")


@pytest.mark.parametrize("field,val", [("first_name", ""), ("last_name", ""), ("first_name", "12345"), ("first_name", "<script>")])
def test_name_rejected(field, val):
    with pytest.raises(ValidationError):
        _req(**{field: val})


def test_middle_optional():
    assert _req(middle_name="").middle_name is None


# ---- service (transactional persistence) ----------------------------------
def test_register_persists_encrypted_and_hashed(db_session: Session):
    reg = register_student(db_session, _req())
    assert isinstance(reg.id, uuid.UUID)
    assert reg.status == "otp_pending"
    # Mobile stored as keyed hash + ciphertext, never plaintext.
    assert reg.mobile_hash == keyed_hash("9876543210")
    assert reg.mobile_ct != "9876543210" and decrypt(reg.mobile_ct) == "9876543210"
    assert decrypt(reg.dob_ct) == "2004-03-14"


def test_missing_consent_rejected(db_session: Session):
    with pytest.raises(RegistrationError) as e:
        register_student(db_session, _req(consent={"accepted": False}))
    assert e.value.status_code == 422 and e.value.code == "consent_required"


def test_mobile_conflict(db_session: Session):
    register_student(db_session, _req())
    with pytest.raises(RegistrationError) as e:
        register_student(db_session, _req())
    assert e.value.status_code == 409


def test_idempotent_replay_single_row(db_session: Session):
    a = register_student(db_session, _req(), idempotency_key="req-1")
    b = register_student(db_session, _req(), idempotency_key="req-1")
    assert a.id == b.id
    rows = db_session.scalars(select(StudentRegistration)).all()
    assert len(rows) == 1


def test_minor_creates_guardian_gate(db_session: Session):
    reg = register_student(db_session, _req(dob="2012-01-01"))
    assert reg.is_minor is True
    gc = db_session.scalars(select(GuardianConsent).where(GuardianConsent.registration_id == reg.id)).all()
    assert len(gc) == 1 and gc[0].verified is False


def test_no_raw_otp_persisted(db_session: Session):
    reg = register_student(db_session, _req())
    otp = db_session.scalar(select(OtpChallenge).where(OtpChallenge.registration_id == reg.id))
    assert otp is not None
    assert len(otp.verifier_hash) == 64  # HMAC hex, not a 6-digit code
    assert not otp.verifier_hash.isdigit()
    # The verifier is not recomputable without the (unknown) salt+code pair.
    assert otp.verifier_hash != otp_verifier("000000", salt=otp.metadata_json["salt"])


def test_audit_snapshot_has_no_pii(db_session: Session):
    reg = register_student(db_session, _req())
    ev = db_session.scalar(select(StudentAuditEvent).where(StudentAuditEvent.entity_id == reg.id))
    assert ev is not None
    blob = str(ev.redacted_meta)
    assert "9876543210" not in blob and "Aditi" not in blob and "Nair" not in blob


# ---- HTTP status codes -----------------------------------------------------
@pytest.fixture()
def client(engine):
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def _override():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app = FastAPI()
    app.include_router(auth_student_router, prefix="/api/v1")
    app.dependency_overrides[get_session] = _override
    yield TestClient(app)
    Base.metadata.drop_all(engine)


def test_http_201_and_422_and_409(client):
    ok = client.post("/api/v1/auth/student/register", json={
        "first_name": "Aditi", "last_name": "Nair", "mobile": "9876543210",
        "dob": "2004-03-14", "consent": {"accepted": True},
    })
    assert ok.status_code == 201
    assert uuid.UUID(ok.json()["registration_id"])

    bad = client.post("/api/v1/auth/student/register", json={
        "first_name": "Aditi", "last_name": "Nair", "mobile": "98765",
        "dob": "2004-03-14", "consent": {"accepted": True},
    })
    assert bad.status_code == 422

    conflict = client.post("/api/v1/auth/student/register", json={
        "first_name": "Other", "last_name": "Person", "mobile": "9876543210",
        "dob": "2001-01-01", "consent": {"accepted": True},
    })
    assert conflict.status_code == 409
