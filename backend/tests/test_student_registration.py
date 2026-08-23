"""SAATHI-421/448 — student registration schema, service and API tests."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.auth_student import router as auth_student_router
from app.core.crypto import decrypt, keyed_hash, otp_verifier
from app.db.session import get_session
import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.db.models.audit import AuditEvent
from app.models.registration import (
    Consent,
    GuardianConsent,
    OtpChallenge,
    OtpOutbox,
    RegistrationIdempotencyRecord,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
)
from app.schemas.registration import StudentRegisterRequest
from app.services import otp_flow_service, otp_service
from app.services.registration_service import RegistrationError, register_student

# Schema builder: a create_all-equivalent template copy (see tests/dbtemplate.py).
from tests import dbtemplate


def _req(**over):
    base = dict(
        first_name="Aditi", middle_name="Rani", last_name="Nair",
        mobile="9876543210", dob="2004-03-14",
        terms_accepted=True,
        terms_version="terms-2026-08.v1",
        privacy_notice_acknowledged=True,
        privacy_notice_version="privacy-2026-08.v1",
    )
    base.update(over)
    return StudentRegisterRequest(**base)


def _req_v2(**over):
    return _req(**over)


# ---- schema validation (422-equivalent) -----------------------------------
@pytest.mark.parametrize("bad", ["", "987654321", "98765432101", "987654321012", "98765abc10", "+919876543210"])
def test_mobile_rejected(bad):
    with pytest.raises(ValidationError):
        _req(mobile=bad)


def test_mobile_exact_10_ok():
    assert _req(mobile="9876543210").mobile == "9876543210"


@pytest.mark.parametrize("bad", ["2030-01-01", "2030-12-31"])
def test_future_dob_rejected(bad):
    request = _req(dob=bad)
    assert request.dob.isoformat() == bad


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
def _reg(session: Session, **over):
    return register_student(session, _req(**over)).registration


def test_register_persists_encrypted_and_hashed(db_session: Session):
    reg = _reg(db_session)
    assert isinstance(reg.id, uuid.UUID)
    assert reg.status == "otp_pending"
    # Mobile stored as keyed hash + ciphertext, never plaintext.
    assert reg.mobile_hash == keyed_hash("9876543210")
    assert reg.mobile_ct != "9876543210" and decrypt(reg.mobile_ct) == "9876543210"
    assert decrypt(reg.dob_ct) == "2004-03-14"
    # DOB now has a keyed lookup hash (SAATHI-366 C1) + version stamp (C2).
    assert reg.dob_hash == keyed_hash("2004-03-14") and reg.dob_hash != "2004-03-14"
    assert reg.key_version == "v1"
    assert reg.mobile_ct.startswith("v1:") and reg.dob_ct.startswith("v1:")


def test_missing_consent_rejected(db_session: Session):
    with pytest.raises(RegistrationError) as e:
        register_student(db_session, _req(consent={"accepted": False}))
    assert e.value.status_code == 422 and e.value.code == "consent_required"


def test_registration_v2_service_persists_two_legal_rows_and_v2_fingerprint(
    db_session: Session,
):
    result = register_student(
        db_session,
        _req_v2(),
        idempotency_key="registration-v2-service",
        now=datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
    )

    rows = db_session.scalars(
        select(Consent)
        .where(Consent.registration_id == result.registration.id)
        .order_by(Consent.purpose)
    ).all()
    assert [(row.purpose, row.policy_version) for row in rows] == [
        ("privacy_notice", "privacy-2026-08.v1"),
        ("terms", "terms-2026-08.v1"),
    ]
    ledger = db_session.scalar(select(RegistrationIdempotencyRecord))
    assert ledger is not None
    assert ledger.request_fingerprint_version == "v2"


def test_mobile_conflict(db_session: Session):
    _reg(db_session)
    with pytest.raises(RegistrationError) as e:
        register_student(db_session, _req())
    assert e.value.status_code == 409


def test_idempotent_replay_single_row(db_session: Session):
    first = register_student(db_session, _req(), idempotency_key="req-1")
    a = first.registration
    assert first.delivery is not None
    outbox = db_session.get(OtpOutbox, first.delivery.outbox_id)
    assert outbox is not None
    challenge = db_session.get(OtpChallenge, outbox.challenge_id)
    assert challenge is not None
    now = datetime.now(timezone.utc)
    authority = otp_service.authority_for_registration(
        db_session, a, "signup", now
    )
    otp_flow_service.create_flow(
        db_session,
        authority,
        now=now,
        destination="9876543210",
        challenge=challenge,
        registration_id=a.id,
        registration_idempotency_record_id=(
            first.idempotency_record.id
            if first.idempotency_record is not None
            else None
        ),
        raw_token=otp_flow_service.deterministic_signup_token("req-1"),
    )
    db_session.flush()
    b = register_student(db_session, _req(), idempotency_key="req-1")
    assert a.id == b.registration.id
    # A still-pending crash-resume returns the same persisted delivery intent;
    # only the serialized HTTP finalizer can execute it.
    assert b.replayed is True
    assert b.delivery is not None and first.delivery is not None
    assert b.delivery.outbox_id == first.delivery.outbox_id
    rows = db_session.scalars(select(StudentRegistration)).all()
    assert len(rows) == 1


def test_minor_creates_guardian_gate(db_session: Session):
    reg = _reg(db_session, dob="2012-01-01")
    assert reg.is_minor is True
    gc = db_session.scalars(select(GuardianConsent).where(GuardianConsent.registration_id == reg.id)).all()
    assert len(gc) == 1 and gc[0].verified is False


def test_no_raw_otp_persisted(db_session: Session):
    reg = _reg(db_session)
    otp = db_session.scalar(select(OtpChallenge).where(OtpChallenge.registration_id == reg.id))
    assert otp is not None
    assert len(otp.verifier_hash) == 64  # HMAC hex, not a 6-digit code
    assert not otp.verifier_hash.isdigit()
    # The verifier is not recomputable without the (unknown) salt+code pair.
    assert otp.verifier_hash != otp_verifier("000000", salt=otp.metadata_json["salt"])


def test_audit_snapshot_has_no_pii(db_session: Session):
    reg = _reg(db_session)
    ev = db_session.scalar(select(AuditEvent).where(AuditEvent.resource_id == reg.id))
    assert ev is not None and ev.action == "student.register"
    blob = str(ev.after_state)
    assert "9876543210" not in blob and "Aditi" not in blob and "Nair" not in blob


def test_academic_profile_requires_authenticated_versioned_boundary(db_session: Session):
    with pytest.raises(RegistrationError) as caught:
        _reg(
            db_session,
            college="NLSIU",
            year_of_study="3rd", enrolment_number="KA/1234/2023",
            institutional_email="aditi@nls.ac.in", bar_enrolment_number="D/1/2020",
        )
    assert (caught.value.status_code, caught.value.code) == (
        422,
        "profile_fields_require_authenticated_session",
    )
    assert db_session.scalar(select(StudentRegistration)) is None

    reg = _reg(db_session)
    prof = db_session.scalar(select(StudentProfile).where(StudentProfile.registration_id == reg.id))
    assert prof is not None
    assert prof.profile_version == 1
    assert prof.college is None and prof.year_of_study is None
    assert prof.enrolment_ct is None and prof.institutional_email_ct is None
    assert prof.bar_enrolment_ct is None
    assert reg.institution_ref is None
    ver = db_session.scalar(select(StudentVerification).where(StudentVerification.registration_id == reg.id))
    assert ver is not None and ver.status == "pending"


def test_unknown_field_rejected():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _req(nickname="hacker")


# ---- HTTP status codes -----------------------------------------------------
@pytest.fixture()
def client(engine):
    dbtemplate.create_all(engine)
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

    # OTP delivery must be provided or the API fails closed (503). Inject a
    # capturing test sender so the happy-path 201 can be exercised.
    from app.api.v1 import auth_student as _ep

    class _Cap:
        def send_idempotent(
            self,
            destination: str,
            code: str,
            *,
            idempotency_token: str,
        ) -> str:  # noqa: D401
            return "test-receipt"

    app.dependency_overrides[_ep.get_otp_sender] = lambda: _Cap()
    app.dependency_overrides[_ep.get_outbox_session_factory] = lambda: factory
    from app.core.config import settings

    yield TestClient(app, headers={"Origin": settings.cors_origins[0]})
    # The shared session engine is reset to an empty schema at the START of
    # every fixture that uses it (conftest.db_session and this fixture), so
    # demolishing it here proved nothing and cost ~10 ms per test.


def test_http_202_and_422_and_neutral_duplicate(client):
    ok = client.post("/api/v1/auth/student/register", json={
        "first_name": "Aditi", "last_name": "Nair", "mobile": "9876543210",
        "dob": "2004-03-14", "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    })
    assert ok.status_code == 202
    assert ok.json()["status"] == "accepted"

    bad = client.post("/api/v1/auth/student/register", json={
        "first_name": "Aditi", "last_name": "Nair", "mobile": "98765",
        "dob": "2004-03-14", "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    })
    assert bad.status_code == 422

    conflict = client.post("/api/v1/auth/student/register", json={
        "first_name": "Other", "last_name": "Person", "mobile": "9876543210",
        "dob": "2001-01-01", "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    })
    assert conflict.status_code == 202
    assert conflict.json().keys() == ok.json().keys()
