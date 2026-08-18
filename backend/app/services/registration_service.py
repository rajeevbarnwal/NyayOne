"""Server-authoritative student registration (SAATHI-421/448).

Transactional persistence of a registration + consent + OTP challenge (verifier
only) + outbox delivery intent + audit event. Sensitive fields are keyed-hashed
for uniqueness and Fernet-encrypted (version-stamped) for display; raw
mobile/DOB/OTP/enrolment never touch plaintext columns, logs or the audit
snapshot.

This function performs all writes and FLUSHES but does NOT commit — the caller
(endpoint) commits and then delivers the OTP via the outbox, so an OTP is never
handed to a provider before the transaction commits. It returns a
``RegistrationResult`` carrying the registration and an optional DeliveryIntent
(absent on idempotent replay, which never re-delivers).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import active_key_version, encrypt, keyed_hash
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
from app.services import otp_outbox, otp_service

AGE_OF_MAJORITY = 18


class RegistrationError(Exception):
    def __init__(self, status_code: int, code: str, field: str | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.field = field


@dataclass
class RegistrationResult:
    registration: StudentRegistration
    delivery: otp_outbox.DeliveryIntent | None  # None on idempotent replay


def _is_minor(dob: date, today: date | None = None) -> bool:
    today = today or date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return years < AGE_OF_MAJORITY


def find_by_idempotency_key(session: Session, key: str) -> StudentRegistration | None:
    return session.scalar(
        select(StudentRegistration).where(StudentRegistration.idempotency_key == key)
    )


def find_by_mobile(session: Session, mobile: str) -> StudentRegistration | None:
    return session.scalar(
        select(StudentRegistration).where(StudentRegistration.mobile_hash == keyed_hash(mobile))
    )


def compensate_delete(session: Session, registration_id: uuid.UUID) -> None:
    """Undo a just-committed registration after OTP delivery fails.

    Dialect-safe explicit teardown (does not rely on ON DELETE cascade being
    enabled on SQLite). Leaves the append-only audit row in place. Runs in its
    own committed transaction so the observable end state is "no rows" — there is
    no committed-but-unusable challenge.
    """
    from app.models.registration import (
        Consent as _C,
        GuardianConsent as _G,
        OtpChallenge as _Ch,
        OtpOutbox as _O,
        StudentProfile as _P,
        StudentVerification as _V,
    )

    reg = session.get(StudentRegistration, registration_id)
    if reg is None:
        return
    ch_ids = [c.id for c in session.scalars(select(_Ch).where(_Ch.registration_id == registration_id))]
    if ch_ids:
        for o in session.scalars(select(_O).where(_O.challenge_id.in_(ch_ids))):
            session.delete(o)
    for model in (_Ch, _C, _P, _V, _G):
        for row in session.scalars(select(model).where(model.registration_id == registration_id)):
            session.delete(row)
    user_id = reg.user_id
    session.delete(reg)
    session.flush()
    user = session.get(User, user_id)
    if user is not None:
        session.delete(user)
    # Record the failed-delivery compensation for auditability (non-PII).
    session.add(
        AuditEvent(
            actor_role="system",
            action="student.register.delivery_failed_rollback",
            resource_type="student_registration",
            resource_id=registration_id,
            after_state={"result": "rolled_back"},
        )
    )
    session.commit()


def register_student(
    session: Session,
    req: StudentRegisterRequest,
    idempotency_key: str | None = None,
    now: datetime | None = None,
) -> RegistrationResult:
    now = now or datetime.now(timezone.utc)
    if not req.consent.accepted:
        raise RegistrationError(422, "consent_required", "consent")

    # Idempotent replay: a repeated key returns the same registration and does
    # NOT re-deliver an OTP.
    if idempotency_key:
        existing = find_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            return RegistrationResult(registration=existing, delivery=None)

    mobile_hash = keyed_hash(req.mobile)
    if session.scalar(select(StudentRegistration).where(StudentRegistration.mobile_hash == mobile_hash)):
        raise RegistrationError(409, "mobile_already_registered", "mobile")

    minor = _is_minor(req.dob)
    key_version = active_key_version()
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
        dob_hash=keyed_hash(req.dob.isoformat()),
        dob_ct=encrypt(req.dob.isoformat()),
        dob_hash_state="verified",
        key_version=key_version,
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

    # OTP challenge via the shared lifecycle service (persists a keyed verifier
    # plus a pending outbox row with a short-lived encrypted delivery payload).
    _, intent = otp_service.issue_challenge(
        session, reg.id, now, purpose="signup", destination=req.mobile
    )

    if minor:
        session.add(GuardianConsent(registration_id=reg.id, status="pending", verified=False))

    # Academic profile (SAATHI-421) — encrypted + keyed hash for sensitive
    # identifiers; plain college/year for display; version-stamped.
    session.add(
        StudentProfile(
            registration_id=reg.id,
            college=req.college,
            year_of_study=req.year_of_study,
            key_version=key_version,
            enrolment_ct=encrypt(req.enrolment_number) if req.enrolment_number else None,
            enrolment_hash=keyed_hash(req.enrolment_number) if req.enrolment_number else None,
            institutional_email_ct=encrypt(req.institutional_email) if req.institutional_email else None,
            institutional_email_hash=keyed_hash(req.institutional_email, lower=True) if req.institutional_email else None,
            bar_enrolment_ct=encrypt(req.bar_enrolment_number) if req.bar_enrolment_number else None,
            bar_enrolment_hash=keyed_hash(req.bar_enrolment_number) if req.bar_enrolment_number else None,
        )
    )
    session.add(StudentVerification(registration_id=reg.id, method="institutional_email", status="pending"))

    # Redacted, non-PII audit snapshot on the shared audit_events table.
    session.add(
        AuditEvent(
            actor_role="student",
            action="student.register",
            resource_type="student_registration",
            resource_id=reg.id,
            after_state={"status": reg.status, "is_minor": minor, "key_version": key_version},
        )
    )
    session.flush()
    return RegistrationResult(registration=reg, delivery=intent)
