"""Config-driven retention / deletion / anonymisation (SAATHI-366 C5, DPDP).

NO statutory duration is hard-coded. Each data category's retention window is
read from settings; an unset window (None) means "retain until explicit erasure"
and the purge job is a no-op for that category. Operators set the windows their
counsel approves. When a window elapses the policy either ANONYMISES (scrub
PII/ciphertext, keep the row for analytics/audit integrity) or hard-DELETES,
selected by `settings.retention_mode`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.registration import (
    OtpChallenge,
    OtpOutbox,
    RecoverySession,
    StudentProfile,
    StudentRegistration,
    User,
)
from app.db.models.audit import AuditEvent

# Marker written into scrubbed ciphertext/hash columns after anonymisation.
ANONYMISED = "[erased]"


@dataclass(frozen=True)
class RetentionPolicy:
    """Immutable snapshot of the configured retention windows (in days)."""

    registration_pending_days: int | None
    registration_inactive_days: int | None
    otp_challenge_days: int | None
    recovery_session_days: int | None
    audit_events_days: int | None
    mode: str  # "anonymise" | "delete"

    @classmethod
    def from_settings(cls) -> "RetentionPolicy":
        return cls(
            registration_pending_days=settings.retention_days_registration_pending,
            registration_inactive_days=settings.retention_days_registration_inactive,
            otp_challenge_days=settings.retention_days_otp_challenge,
            recovery_session_days=settings.retention_days_recovery_session,
            audit_events_days=settings.retention_days_audit_events,
            mode=settings.retention_mode or "anonymise",
        )


def _cutoff(now: datetime, days: int | None) -> datetime | None:
    if days is None:
        return None
    return now - timedelta(days=days)


def anonymise_registration(session: Session, reg: StudentRegistration) -> None:
    """Scrub PII-bearing columns on a registration + its profile, keep the row.

    Deletion/anonymisation HOOK: safe to call directly for a DPDP erasure
    request against a single subject.
    """
    reg.mobile_hash = f"{ANONYMISED}:{reg.id}"  # keep uniqueness, drop linkability
    reg.mobile_ct = ANONYMISED
    reg.dob_hash = f"{ANONYMISED}:{reg.id}"
    reg.dob_ct = ANONYMISED
    reg.dob_hash_state = "erased"
    reg.institution_ref = None
    reg.idempotency_key = None
    reg.first_name = ANONYMISED
    reg.middle_name = None
    reg.last_name = ANONYMISED
    reg.status = "deleted"
    reg.deleted_at = datetime.now(timezone.utc)
    prof = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == reg.id))
    if prof is not None:
        prof.college = None
        prof.year_of_study = None
        for col in ("enrolment_ct", "institutional_email_ct", "bar_enrolment_ct"):
            setattr(prof, col, ANONYMISED)
        for col in ("enrolment_hash", "institutional_email_hash", "bar_enrolment_hash"):
            setattr(prof, col, None)
    challenge_ids = [
        row.id
        for row in session.scalars(
            select(OtpChallenge).where(OtpChallenge.registration_id == reg.id)
        )
    ]
    if challenge_ids:
        for row in session.scalars(
            select(OtpOutbox).where(OtpOutbox.challenge_id.in_(challenge_ids))
        ):
            session.delete(row)
    for model in (OtpChallenge, RecoverySession):
        for row in session.scalars(
            select(model).where(model.registration_id == reg.id)
        ):
            session.delete(row)
    session.add(
        AuditEvent(
            actor_role="system",
            action="student.registration.anonymised",
            resource_type="student_registration",
            resource_id=reg.id,
            after_state={"status": "deleted"},
        )
    )


def delete_registration(session: Session, reg: StudentRegistration) -> None:
    """Hard-delete a registration and its dependent rows.

    Explicit dialect-safe teardown (does not rely on ON DELETE cascade being
    enabled on SQLite; Postgres cascades additionally). The append-only audit
    trail is retained.
    """
    from app.models.registration import (
        Consent,
        GuardianConsent,
        OtpChallenge,
        RegistrationDobReconciliation,
        StudentVerification,
    )

    ch_ids = [c.id for c in session.scalars(select(OtpChallenge).where(OtpChallenge.registration_id == reg.id))]
    if ch_ids:
        for o in session.scalars(select(OtpOutbox).where(OtpOutbox.challenge_id.in_(ch_ids))):
            session.delete(o)
    for model in (
        RecoverySession,
        OtpChallenge,
        Consent,
        RegistrationDobReconciliation,
        StudentProfile,
        StudentVerification,
        GuardianConsent,
    ):
        for row in session.scalars(select(model).where(model.registration_id == reg.id)):
            session.delete(row)
    user_id = reg.user_id
    session.flush()
    session.delete(reg)
    session.flush()
    user = session.get(User, user_id)
    if user is not None:
        session.delete(user)
    session.add(
        AuditEvent(
            actor_role="system",
            action="student.registration.deleted",
            resource_type="student_registration",
            resource_id=reg.id,
            after_state={"status": "deleted"},
        )
    )


def purge_expired(session: Session, now: datetime | None = None, policy: RetentionPolicy | None = None) -> dict[str, int]:
    """Apply the configured retention windows. Returns a per-category count.

    Categories with an unset window are skipped entirely. Idempotent and safe to
    run on a schedule.
    """
    now = now or datetime.now(timezone.utc)
    policy = policy or RetentionPolicy.from_settings()
    counts = {"registrations": 0, "otp_challenges": 0, "recovery_sessions": 0}

    def _apply(reg: StudentRegistration) -> None:
        if policy.mode == "delete":
            delete_registration(session, reg)
        else:
            anonymise_registration(session, reg)
        counts["registrations"] += 1

    pending_cut = _cutoff(now, policy.registration_pending_days)
    if pending_cut is not None:
        for reg in session.scalars(
            select(StudentRegistration).where(
                StudentRegistration.status == "otp_pending",
                StudentRegistration.created_at < pending_cut,
                StudentRegistration.deleted_at.is_(None),
            )
        ):
            _apply(reg)

    inactive_cut = _cutoff(now, policy.registration_inactive_days)
    if inactive_cut is not None:
        for reg in session.scalars(
            select(StudentRegistration).where(
                StudentRegistration.status.in_(("otp_verified", "active")),
                StudentRegistration.updated_at < inactive_cut,
                StudentRegistration.deleted_at.is_(None),
            )
        ):
            _apply(reg)

    otp_cut = _cutoff(now, policy.otp_challenge_days)
    if otp_cut is not None:
        for ch in session.scalars(
            select(OtpChallenge).where(OtpChallenge.created_at < otp_cut)
        ):
            session.delete(ch)
            counts["otp_challenges"] += 1

    rec_cut = _cutoff(now, policy.recovery_session_days)
    if rec_cut is not None:
        for rs in session.scalars(
            select(RecoverySession).where(RecoverySession.created_at < rec_cut)
        ):
            session.delete(rs)
            counts["recovery_sessions"] += 1

    session.flush()
    return counts
