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

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.registration import (
    OtpChallenge,
    OtpOutbox,
    RecoverySession,
    RegistrationIdempotencyRecord,
    StudentProfile,
    StudentRegistration,
    User,
)
from app.db.models.audit import AuditEvent
from app.services import registration_service

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


def _anonymise_locked(
    session: Session,
    reg: StudentRegistration,
    idempotency_record: RegistrationIdempotencyRecord | None,
) -> None:
    registration_service.terminalize_registration_idempotency(
        session,
        reg,
        state="erased",
        locked_record=idempotency_record,
    )
    session.flush()
    reg.mobile_hash = f"{ANONYMISED}:{reg.id}"  # keep uniqueness, drop linkability
    reg.mobile_ct = ANONYMISED
    reg.dob_hash = f"{ANONYMISED}:{reg.id}"
    reg.dob_ct = ANONYMISED
    reg.dob_hash_state = "erased"
    reg.institution_ref = None
    reg.idempotency_key = None
    reg.idempotency_key_legacy = False
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


def anonymise_registration(session: Session, reg: StudentRegistration) -> None:
    """Scrub one subject unconditionally under ledger -> registration locks."""

    locked, idempotency_record = (
        registration_service.lock_registration_with_idempotency(session, reg.id)
    )
    if locked is None:
        return
    _anonymise_locked(session, locked, idempotency_record)


def _delete_locked(
    session: Session,
    reg: StudentRegistration,
    idempotency_record: RegistrationIdempotencyRecord | None,
) -> None:
    registration_service.terminalize_registration_idempotency(
        session,
        reg,
        state="erased",
        locked_record=idempotency_record,
    )
    # Materialise the tombstone and clear its FK links before deleting any
    # linked registration graph rows. This ordering is required on PostgreSQL
    # and must not depend on ORM unit-of-work sorting.
    session.flush()

    from app.models.registration import (
        Consent,
        GuardianConsent,
        OtpChallenge,
        RegistrationDobReconciliation,
        StudentVerification,
    )

    ch_ids = [
        c.id
        for c in session.scalars(
            select(OtpChallenge).where(OtpChallenge.registration_id == reg.id)
        )
    ]
    if ch_ids:
        for o in session.scalars(
            select(OtpOutbox).where(OtpOutbox.challenge_id.in_(ch_ids))
        ):
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
        for row in session.scalars(
            select(model).where(model.registration_id == reg.id)
        ):
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


def delete_registration(session: Session, reg: StudentRegistration) -> None:
    """Hard-delete one subject under ledger -> registration locks."""

    locked, idempotency_record = (
        registration_service.lock_registration_with_idempotency(session, reg.id)
    )
    if locked is None:
        return
    _delete_locked(session, locked, idempotency_record)


def _purge_expired_challenge(
    session: Session,
    challenge_id,
    cutoff: datetime,
    mode: str,
) -> tuple[int, int]:
    """Purge one old challenge without bypassing a NYAY-17 ledger claim.

    Discovery reads do not take a child lock. Any associated ledger is locked
    first, followed by registration, challenge, and outbox. A still-active
    signup challenge owned by a pending ledger is terminalized as a uniform
    erased tombstone and its unusable bootstrap graph is compensated
    atomically; ordinary consumed/history rows are deleted in the same order.
    """

    registration_id = session.scalar(
        select(OtpChallenge.registration_id).where(OtpChallenge.id == challenge_id)
    )
    if registration_id is None:
        return 0, 0
    linked_outboxes = select(OtpOutbox.id).where(
        OtpOutbox.challenge_id == challenge_id
    )
    record_ids = list(
        session.scalars(
            select(RegistrationIdempotencyRecord.id)
            .where(
                or_(
                    RegistrationIdempotencyRecord.registration_id
                    == registration_id,
                    RegistrationIdempotencyRecord.outbox_id.in_(linked_outboxes),
                )
            )
            .order_by(RegistrationIdempotencyRecord.id)
            .limit(2)
        )
    )
    if len(record_ids) > 1:
        return 0, 0
    record = None
    if record_ids:
        record = session.scalar(
            select(RegistrationIdempotencyRecord)
            .where(RegistrationIdempotencyRecord.id == record_ids[0])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    registration = session.scalar(
        select(StudentRegistration)
        .where(StudentRegistration.id == registration_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    challenge = session.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.id == challenge_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if challenge is None or challenge.registration_id != registration_id:
        return 0, 0
    created_at = challenge.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if created_at >= cutoff:
        return 0, 0
    outboxes = list(
        session.scalars(
            select(OtpOutbox)
            .where(OtpOutbox.challenge_id == challenge_id)
            .order_by(OtpOutbox.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    outbox_ids = {row.id for row in outboxes}

    if record is not None and record.state in {"pending", "succeeded"}:
        if record.registration_id != registration_id or registration is None:
            return 0, 0
        linked_active = (
            record.state == "pending"
            and challenge.consumed_at is None
            and challenge.purpose == "signup"
            and registration.status == "otp_pending"
            and registration.deleted_at is None
            and registration.dob_hash_state == "verified"
            and record.outbox_id in outbox_ids
        )
        if linked_active:
            linked = next(
                (row for row in outboxes if row.id == record.outbox_id),
                None,
            )
            if linked is None or linked.purpose != "signup":
                return 0, 0
            if linked.status == "sent":
                if linked.code_ct is not None:
                    return 0, 0
                # Reconcile the narrow post-provider/pre-ledger-commit crash
                # window. Delivery succeeded, so preserve the registration and
                # close the claim before deleting expired OTP history.
                record.state = "succeeded"
                record.outbox_id = None
                record.updated_at = datetime.now(timezone.utc)
                for outbox in outboxes:
                    session.delete(outbox)
                session.delete(challenge)
                return 1, 0
            if linked.status not in {"pending", "failed"}:
                return 0, 0
            deleted_count = len(
                list(
                    session.scalars(
                        select(OtpChallenge.id).where(
                            OtpChallenge.registration_id == registration.id
                        )
                    )
                )
            )
            session.add(
                AuditEvent(
                    actor_role="system",
                    action="student.registration.otp_retention_expired",
                    resource_type="student_registration",
                    resource_id=registration.id,
                    after_state={"mode": mode},
                )
            )
            if mode == "delete":
                _delete_locked(session, registration, record)
            else:
                _anonymise_locked(session, registration, record)
            return deleted_count, 1
        if (
            record.state == "pending"
            and challenge.consumed_at is None
            and challenge.purpose == "signup"
            and registration.status == "otp_pending"
        ):
            # The sole active signup child does not match the pending ledger's
            # outbox. This is structural drift, not disposable history.
            return 0, 0
        if record.outbox_id in outbox_ids:
            # A pending authority still points at this child but its lifecycle
            # graph is inconsistent. Preserve it unchanged for investigation.
            return 0, 0

    for outbox in outboxes:
        session.delete(outbox)
    session.delete(challenge)
    return 1, 0


def purge_expired(session: Session, now: datetime | None = None, policy: RetentionPolicy | None = None) -> dict[str, int]:
    """Apply the configured retention windows. Returns a per-category count.

    Categories with an unset window are skipped entirely. Idempotent and safe to
    run on a schedule.
    """
    now = now or datetime.now(timezone.utc)
    policy = policy or RetentionPolicy.from_settings()
    if policy.mode not in {"anonymise", "delete"}:
        raise ValueError("retention mode must be anonymise or delete")
    counts = {"registrations": 0, "otp_challenges": 0, "recovery_sessions": 0}

    def _apply(
        registration_id,
        *,
        statuses: set[str],
        cutoff: datetime,
        timestamp_field: str,
    ) -> None:
        reg, idempotency_record = (
            registration_service.lock_registration_with_idempotency(
                session, registration_id
            )
        )
        if (
            reg is None
            or reg.deleted_at is not None
            or reg.status not in statuses
        ):
            return
        observed = getattr(reg, timestamp_field)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        if observed >= cutoff:
            # Re-check after waiting for the lifecycle lock. A concurrent OTP
            # activation can make the stale candidate ineligible.
            return
        if policy.mode == "delete":
            _delete_locked(session, reg, idempotency_record)
        else:
            _anonymise_locked(session, reg, idempotency_record)
        counts["registrations"] += 1

    pending_cut = _cutoff(now, policy.registration_pending_days)
    if pending_cut is not None:
        candidate_ids = list(
            session.scalars(
                select(StudentRegistration.id).where(
                    StudentRegistration.status == "otp_pending",
                    StudentRegistration.created_at < pending_cut,
                    StudentRegistration.deleted_at.is_(None),
                ).order_by(StudentRegistration.id)
            )
        )
        for registration_id in candidate_ids:
            _apply(
                registration_id,
                statuses={"otp_pending"},
                cutoff=pending_cut,
                timestamp_field="created_at",
            )

    inactive_cut = _cutoff(now, policy.registration_inactive_days)
    if inactive_cut is not None:
        candidate_ids = list(
            session.scalars(
                select(StudentRegistration.id).where(
                    StudentRegistration.status.in_(("otp_verified", "active")),
                    StudentRegistration.updated_at < inactive_cut,
                    StudentRegistration.deleted_at.is_(None),
                ).order_by(StudentRegistration.id)
            )
        )
        for registration_id in candidate_ids:
            _apply(
                registration_id,
                statuses={"otp_verified", "active"},
                cutoff=inactive_cut,
                timestamp_field="updated_at",
            )

    otp_cut = _cutoff(now, policy.otp_challenge_days)
    if otp_cut is not None:
        challenge_ids = list(
            session.scalars(
                select(OtpChallenge.id)
                .where(OtpChallenge.created_at < otp_cut)
                .order_by(OtpChallenge.id)
            )
        )
        for challenge_id in challenge_ids:
            challenge_count, registration_count = _purge_expired_challenge(
                session, challenge_id, otp_cut, policy.mode
            )
            counts["otp_challenges"] += challenge_count
            counts["registrations"] += registration_count

    rec_cut = _cutoff(now, policy.recovery_session_days)
    if rec_cut is not None:
        for rs in session.scalars(
            select(RecoverySession).where(RecoverySession.created_at < rec_cut)
        ):
            session.delete(rs)
            counts["recovery_sessions"] += 1

    session.flush()
    return counts
