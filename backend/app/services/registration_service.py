"""Server-authoritative student registration (SAATHI-421/448).

Transactional persistence of a registration + consent + OTP challenge (verifier
only) + audit event. Sensitive fields are keyed-hashed for uniqueness and
Fernet-encrypted for display; raw mobile/DOB/OTP never touch plaintext columns,
logs or the audit snapshot.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt, keyed_hash
from app.db.models.audit import AuditEvent
from app.models.registration import (
    Consent,
    GuardianConsent,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.schemas.registration import StudentRegisterRequest

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
    session: Session, req: StudentRegisterRequest, idempotency_key: str | None = None,
    now: datetime | None = None, sender=None,
) -> StudentRegistration:
    now = now or datetime.now(timezone.utc)
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

        session.add(
            Consent(
                registration_id=reg.id,
                purpose="registration",
                accepted=True,
                policy_version=req.consent.policy_version,
                accepted_at=now,
            )
        )

        # OTP challenge via the shared lifecycle service (persists only a keyed
        # verifier; the raw code leaves only through an injectable sender).
        from app.services.otp_service import issue_challenge

        send = (lambda code: sender.send(req.mobile, code)) if sender is not None else None
        issue_challenge(session, reg.id, now, send=send)

        if minor:
            session.add(GuardianConsent(registration_id=reg.id, status="pending", verified=False))

        # Academic profile (SAATHI-421 legacy fields) — encrypted + keyed hash for
        # the sensitive identifiers; plain college/year for display.
        session.add(
            StudentProfile(
                registration_id=reg.id,
                college=req.college,
                year_of_study=req.year_of_study,
                enrolment_ct=encrypt(req.enrolment_number) if req.enrolment_number else None,
                enrolment_hash=keyed_hash(req.enrolment_number) if req.enrolment_number else None,
                institutional_email_ct=encrypt(req.institutional_email) if req.institutional_email else None,
                institutional_email_hash=keyed_hash(req.institutional_email, lower=True) if req.institutional_email else None,
                bar_enrolment_ct=encrypt(req.bar_enrolment_number) if req.bar_enrolment_number else None,
            )
        )
        # Pending verification record (institutional email by default).
        session.add(StudentVerification(registration_id=reg.id, method="institutional_email", status="pending"))

        # Redacted, non-PII audit snapshot on the shared audit_events table.
        session.add(
            AuditEvent(
                actor_role="student",
                action="student.register",
                resource_type="student_registration",
                resource_id=reg.id,
                after_state={"status": reg.status, "is_minor": minor},
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
