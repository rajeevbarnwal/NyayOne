"""Server-authoritative student registration (SAATHI-421/448).

Transactional persistence of a registration + consent + OTP challenge (verifier
only) + audit event. Sensitive fields are keyed-hashed for uniqueness and
Fernet-encrypted for display; raw mobile/DOB/OTP never touch plaintext columns,
logs or the audit snapshot.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt, keyed_hash, otp_verifier
from app.models.registration import (
    StudentAuditEvent,
    Consent,
    GuardianConsent,
    OtpChallenge,
    StudentRegistration,
    User,
)
from app.schemas.registration import StudentRegisterRequest

OTP_TTL_SECONDS = 300
AGE_OF_MAJORITY = 18


class RegistrationError(Exception):
    def __init__(self, status_code: int, code: str, field: str | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.field = field


def _is_minor(dob: date, today: date | None = None) -> bool:
    today = today or date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years < AGE_OF_MAJORITY


def register_student(
    session: Session, req: StudentRegisterRequest, idempotency_key: str | None = None
) -> StudentRegistration:
    if not req.consent.accepted:
        raise RegistrationError(422, "consent_required", "consent")

    # Idempotent replay: a repeated key returns the same registration.
    if idempotency_key:
        existing = session.scalar(
            select(StudentRegistration).where(StudentRegistration.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing

    mobile_hash = keyed_hash(req.mobile)
    if session.scalar(select(StudentRegistration).where(StudentRegistration.mobile_hash == mobile_hash)):
        raise RegistrationError(409, "mobile_already_registered", "mobile")

    try:
        minor = _is_minor(req.dob)
        user = User(role="student", status="pending")
        session.add(user)
        session.flush()

        reg = StudentRegistration(
            user_id=user.id,
            first_name=req.first_name,
            middle_name=req.middle_name,
            last_name=req.last_name,
            mobile_hash=mobile_hash,
            mobile_ct=encrypt(req.mobile),
            dob_ct=encrypt(req.dob.isoformat()),
            institution_ref=req.college,
            status="otp_pending",
            is_minor=minor,
            idempotency_key=idempotency_key,
        )
        session.add(reg)
        session.flush()

        now = datetime.now(timezone.utc)
        session.add(
            Consent(
                registration_id=reg.id,
                purpose="registration",
                accepted=True,
                policy_version=req.consent.policy_version,
                accepted_at=now,
            )
        )

        # OTP challenge: generate server-side, persist ONLY a keyed verifier.
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = str(uuid.uuid4())
        session.add(
            OtpChallenge(
                registration_id=reg.id,
                verifier_hash=otp_verifier(code, salt=salt),
                attempts=0,
                max_attempts=3,
                expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
                metadata_json={"salt": salt},
            )
        )
        del code  # raw OTP is never stored, logged or returned

        if minor:
            session.add(GuardianConsent(registration_id=reg.id, status="pending", verified=False))

        # Redacted, non-PII audit snapshot.
        session.add(
            StudentAuditEvent(
                action="student.register",
                entity="student_registration",
                entity_id=reg.id,
                redacted_meta={"status": reg.status, "is_minor": minor},
            )
        )
        session.commit()
        return reg
    except RegistrationError:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
