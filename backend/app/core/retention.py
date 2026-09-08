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

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import keyed_hash
from app.models.registration import (
    AuthSession,
    GuardianConsent,
    LoginAttempt,
    OtpChallenge,
    OtpFlow,
    OtpOutbox,
    OtpPurposeAuthority,
    OtpRateLimitBucket,
    ProfileMutationIdempotencyRecord,
    RecoverySession,
    RegistrationIdempotencyRecord,
    StudentProfile,
    StudentProfileGoal,
    StudentProfileInterest,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.db.models.audit import AuditEvent
from app.services import login_service, otp_authority, otp_outbox, registration_service

# Marker written into scrubbed ciphertext/hash columns after anonymisation.
ANONYMISED = "[erased]"


def _prelock_subject_mentor_erasure(
    session: Session,
    registration_id,
    *,
    now: datetime | None = None,
):
    """Acquire NYAY-22 advisory scopes before any legacy erasure row lock."""

    from app.services import mentor_ceremony

    return mentor_ceremony.lock_subject_mentor_erasure_boundary(
        session, registration_id, now=now
    )


@dataclass(frozen=True)
class RetentionPolicy:
    """Immutable snapshot of the configured retention windows (in days)."""

    registration_pending_days: int | None
    registration_inactive_days: int | None
    otp_challenge_days: int | None
    recovery_session_days: int | None
    audit_events_days: int | None
    mode: str  # "anonymise" | "delete"
    login_attempt_days: int | None = None
    auth_session_days: int | None = None
    email_identity_terminal_days: int | None = None

    @classmethod
    def from_settings(cls) -> "RetentionPolicy":
        return cls(
            registration_pending_days=settings.retention_days_registration_pending,
            registration_inactive_days=settings.retention_days_registration_inactive,
            otp_challenge_days=settings.retention_days_otp_challenge,
            recovery_session_days=settings.retention_days_recovery_session,
            audit_events_days=settings.retention_days_audit_events,
            mode=settings.retention_mode or "anonymise",
            login_attempt_days=settings.retention_days_login_attempt,
            auth_session_days=settings.retention_days_auth_session,
            email_identity_terminal_days=settings.retention_days_email_identity_terminal,
        )


def _cutoff(now: datetime, days: int | None) -> datetime | None:
    if days is None:
        return None
    return now - timedelta(days=days)


def _validated_policy(policy: RetentionPolicy) -> RetentionPolicy:
    """Validate every policy value before the first retention mutation."""

    if policy.mode not in {"anonymise", "delete"}:
        raise ValueError("retention mode must be anonymise or delete")
    for value in (
        policy.registration_pending_days,
        policy.registration_inactive_days,
        policy.otp_challenge_days,
        policy.recovery_session_days,
        policy.audit_events_days,
        policy.login_attempt_days,
        policy.auth_session_days,
        policy.email_identity_terminal_days,
    ):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= 36_500
        ):
            raise ValueError("retention days must be a positive bounded integer")
    return policy


def _expire_active_auth_sessions(session: Session, *, now: datetime) -> int:
    """Expire live bearers under the stable User -> AuthSession lock order."""

    candidate_ids = list(
        session.scalars(
            select(AuthSession.id)
            .where(
                AuthSession.status == "active",
                AuthSession.expires_at <= now,
            )
            .order_by(AuthSession.id)
        )
    )
    expired = 0
    for session_id in candidate_ids:
        user_id = session.scalar(
            select(AuthSession.user_id).where(AuthSession.id == session_id)
        )
        if user_id is None:
            continue
        user = login_service.lock_user_for_session_rotation(session, user_id)
        row = session.scalar(
            select(AuthSession)
            .where(AuthSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            user is None
            or row is None
            or row.user_id != user_id
            or row.status != "active"
            or _as_retention_utc(row.expires_at) > now
        ):
            continue
        login_service.clear_profile_prompts(session, [row.id])
        row.status = "expired"
        row.revoked_at = row.expires_at
        expired += 1
    return expired


def _as_retention_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _purge_auth_security_history(
    session: Session,
    *,
    now: datetime,
    policy: RetentionPolicy,
) -> dict[str, int]:
    """Apply bounded auth retention and return aggregate counts only."""

    expired_sessions = 0
    login_attempts = 0
    auth_sessions = 0

    # Pending real and decoy attempts share the same expiry transition.  This
    # sweep is security lifecycle, not counsel-selected history erasure.
    pending_ids = list(
        session.scalars(
            select(LoginAttempt.id)
            .where(
                LoginAttempt.status == "pending",
                LoginAttempt.expires_at <= now,
            )
            .order_by(LoginAttempt.id)
        )
    )
    expired_attempts = 0
    for attempt_id in pending_ids:
        row = session.scalar(
            select(LoginAttempt)
            .where(LoginAttempt.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            row is None
            or row.status != "pending"
            or _as_retention_utc(row.expires_at) > now
        ):
            continue
        row.status = "expired"
        row.consumed_at = row.expires_at
        expired_attempts += 1

    # The session factory deliberately disables autoflush. Persist attempt
    # expiry before the terminal-history candidate query in this same run.
    session.flush()

    attempt_cutoff = _cutoff(now, policy.login_attempt_days)
    if attempt_cutoff is not None:
        candidate_ids = list(
            session.scalars(
                select(LoginAttempt.id)
                .where(
                    LoginAttempt.status.in_(("consumed", "expired")),
                    LoginAttempt.consumed_at < attempt_cutoff,
                )
                .order_by(LoginAttempt.id)
            )
        )
        for attempt_id in candidate_ids:
            row = session.scalar(
                select(LoginAttempt)
                .where(LoginAttempt.id == attempt_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                row is None
                or row.status not in {"consumed", "expired"}
                or row.consumed_at is None
                or _as_retention_utc(row.consumed_at) >= attempt_cutoff
            ):
                continue
            if policy.mode == "delete":
                session.delete(row)
            else:
                login_service.erase_login_attempt(row)
            login_attempts += 1

    # Preserve the global auth lock order used by login verification and
    # registration erasure: LoginAttempt precedes User -> AuthSession.  These
    # locks are retained until the caller commits, so session work must follow
    # every attempt mutation even though the two scans are otherwise disjoint.
    expired_sessions = _expire_active_auth_sessions(session, now=now)
    session.flush()

    session_cutoff = _cutoff(now, policy.auth_session_days)
    if session_cutoff is not None:
        candidate_ids = list(
            session.scalars(
                select(AuthSession.id)
                .where(
                    AuthSession.status.in_(("revoked", "expired")),
                    AuthSession.revoked_at < session_cutoff,
                )
                .order_by(AuthSession.id)
            )
        )
        for auth_session_id in candidate_ids:
            user_id = session.scalar(
                select(AuthSession.user_id).where(
                    AuthSession.id == auth_session_id
                )
            )
            if user_id is None:
                continue
            user = login_service.lock_user_for_session_rotation(session, user_id)
            row = session.scalar(
                select(AuthSession)
                .where(AuthSession.id == auth_session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                user is None
                or row is None
                or row.user_id != user_id
                or row.status not in {"revoked", "expired"}
                or row.revoked_at is None
                or _as_retention_utc(row.revoked_at) >= session_cutoff
            ):
                continue
            if policy.mode == "delete":
                session.delete(row)
            else:
                login_service.erase_auth_session(row)
            auth_sessions += 1

    if expired_sessions or expired_attempts or login_attempts or auth_sessions:
        session.add(
            AuditEvent(
                actor_role="system",
                action="student.auth.retention_applied",
                resource_type="auth_security_history",
                after_state={
                    "mode": policy.mode,
                    "expired_sessions": expired_sessions,
                    "expired_attempts": expired_attempts,
                    "login_attempts": login_attempts,
                    "auth_sessions": auth_sessions,
                },
            )
        )
    session.flush()
    return {
        "auth_sessions_expired": expired_sessions,
        "login_attempts_expired": expired_attempts,
        "login_attempts": login_attempts,
        "auth_sessions": auth_sessions,
    }


def _erase_registration_otp_security_graph(
    session: Session,
    reg: StudentRegistration,
    *,
    original_mobile_hash: str,
    mode: str,
) -> None:
    """Remove every registration-bound OTP/session capability in lock order.

    The caller already holds ledger -> registration.  We then lock stable OTP
    authorities before flows/challenges/outboxes, and erase browser/session
    capability hashes plus the subject's identity rate buckets.  IP/global
    abuse history remains aggregate and expires through its own bounded policy.
    """

    authorities = list(
        session.scalars(
            select(OtpPurposeAuthority)
            .where(OtpPurposeAuthority.registration_id == reg.id)
            .order_by(OtpPurposeAuthority.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    authority_ids = [row.id for row in authorities]
    authority_rate_subjects = [
        (row.subject_hash, row.purpose) for row in authorities
    ]
    flow_filter = OtpFlow.registration_id == reg.id
    if authority_ids:
        flow_filter = or_(
            flow_filter,
            OtpFlow.authority_id.in_(authority_ids),
        )
    flows = list(
        session.scalars(
            select(OtpFlow)
            .where(flow_filter)
            .order_by(OtpFlow.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    challenges = list(
        session.scalars(
            select(OtpChallenge)
            .where(OtpChallenge.registration_id == reg.id)
            .order_by(OtpChallenge.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    challenge_ids = [row.id for row in challenges]
    outboxes = (
        list(
            session.scalars(
                select(OtpOutbox)
                .where(OtpOutbox.challenge_id.in_(challenge_ids))
                .order_by(OtpOutbox.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if challenge_ids
        else []
    )
    recovery_rows = list(
        session.scalars(
            select(RecoverySession)
            .where(
                or_(
                    RecoverySession.registration_id == reg.id,
                    RecoverySession.lookup_hash == original_mobile_hash,
                )
            )
            .order_by(RecoverySession.id)
            .with_for_update()
        )
    )
    login_rows = list(
        session.scalars(
            select(LoginAttempt)
            .where(
                or_(
                    LoginAttempt.registration_id == reg.id,
                    LoginAttempt.lookup_hash == original_mobile_hash,
                )
            )
            .order_by(LoginAttempt.id)
            .with_for_update()
        )
    )
    user = login_service.lock_user_for_session_rotation(session, reg.user_id)
    auth_sessions = list(
        session.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == reg.user_id)
            .order_by(AuthSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    login_service.clear_profile_prompts(
        session, [row.id for row in auth_sessions]
    )
    identity_subjects = [
        keyed_hash(
            "nyayone:otp-rate-identity:v1:"
            f"{purpose}:{subject}"
        )
        for subject, purpose in authority_rate_subjects
    ]
    rate_rows = (
        list(
            session.scalars(
                select(OtpRateLimitBucket)
                .where(
                    OtpRateLimitBucket.scope == "identity",
                    OtpRateLimitBucket.subject_hash.in_(identity_subjects),
                )
                .order_by(OtpRateLimitBucket.id)
                .with_for_update()
            )
        )
        if identity_subjects
        else []
    )
    for collection in (
        flows,
        outboxes,
        challenges,
        authorities,
        recovery_rows,
        rate_rows,
    ):
        for row in collection:
            session.delete(row)
    if mode == "delete":
        for row in (*login_rows, *auth_sessions):
            session.delete(row)
    else:
        for row in login_rows:
            login_service.erase_login_attempt(row)
        for row in auth_sessions:
            login_service.erase_auth_session(row)
        if user is not None:
            user.status = "deleted"
    session.flush()


def _purge_terminal_otp_graphs(
    session: Session,
    *,
    cutoff: datetime,
) -> tuple[int, int]:
    """Delete bounded, payload-free OTP history in canonical lock order."""

    candidate_ids = list(
        session.scalars(
            select(OtpChallenge.id)
            .where(
                OtpChallenge.created_at < cutoff,
                or_(
                    OtpChallenge.delivery_state.in_(
                        ("consumed", "superseded", "void")
                    ),
                    (
                        (OtpChallenge.delivery_state == "active")
                        & (OtpChallenge.expires_at < cutoff)
                    ),
                ),
            )
            .order_by(OtpChallenge.id)
        )
    )
    challenge_count = 0
    outbox_count = 0
    for challenge_id in candidate_ids:
        discovery = session.execute(
            select(
                OtpChallenge.registration_id,
                OtpChallenge.authority_id,
            ).where(OtpChallenge.id == challenge_id)
        ).one_or_none()
        if discovery is None:
            continue
        registration_id, authority_id = discovery
        outbox_ids = list(
            session.scalars(
                select(OtpOutbox.id)
                .where(OtpOutbox.challenge_id == challenge_id)
                .order_by(OtpOutbox.id)
            )
        )
        record_ids = list(
            session.scalars(
                select(RegistrationIdempotencyRecord.id)
                .where(
                    or_(
                        RegistrationIdempotencyRecord.registration_id
                        == registration_id,
                        RegistrationIdempotencyRecord.outbox_id.in_(outbox_ids)
                        if outbox_ids
                        else False,
                    )
                )
                .order_by(RegistrationIdempotencyRecord.id)
                .limit(2)
            )
        )
        if len(record_ids) > 1:
            continue
        record = None
        if record_ids:
            record = session.scalar(
                select(RegistrationIdempotencyRecord)
                .where(
                    RegistrationIdempotencyRecord.id == record_ids[0]
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if record is not None and (
                record.state == "pending"
                or record.outbox_id in set(outbox_ids)
            ):
                continue
        session.scalar(
            select(StudentRegistration)
            .where(StudentRegistration.id == registration_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        authority = session.scalar(
            select(OtpPurposeAuthority)
            .where(OtpPurposeAuthority.id == authority_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        challenge = session.scalar(
            select(OtpChallenge)
            .where(OtpChallenge.id == challenge_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if authority is None or challenge is None:
            continue
        if session.scalar(
            select(OtpFlow.id)
            .where(OtpFlow.challenge_id == challenge.id)
            .limit(1)
        ) is not None:
            continue
        outboxes = list(
            session.scalars(
                select(OtpOutbox)
                .where(OtpOutbox.challenge_id == challenge.id)
                .order_by(OtpOutbox.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if any(
            row.status not in {"sent", "void"}
            or row.code_ct is not None
            or row.destination_ct is not None
            or row.legacy_destination_retained
            or row.claim_token_hash is not None
            for row in outboxes
        ):
            continue
        for row in outboxes:
            session.delete(row)
        session.delete(challenge)
        outbox_count += len(outboxes)
        challenge_count += 1
        session.flush()
    return challenge_count, outbox_count


def purge_otp_security_state(
    session: Session,
    *,
    now: datetime,
    registration_mode: str | None = None,
) -> dict[str, int]:
    """Erase expired pre-auth displays and bounded NYAY-4 security history.

    Output is aggregate counts only. Raw identifiers, masked destinations,
    provider receipts and bucket subjects never leave the database boundary.
    """

    mode = registration_mode or settings.retention_mode
    if mode not in {"anonymise", "delete"}:
        raise ValueError("retention mode must be anonymise or delete")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    expired_flow_ids = list(
        session.scalars(
            select(OtpFlow.id)
            .where(
                OtpFlow.expires_at <= now,
                OtpFlow.state.in_(("pending", "code_sent", "verified", "locked")),
            )
            .order_by(OtpFlow.id)
        )
    )
    expired_flows = 0
    expired_registrations = 0
    for flow_id in expired_flow_ids:
        discovery = session.execute(
            select(
                OtpFlow.registration_idempotency_record_id,
                OtpFlow.registration_id,
                OtpFlow.authority_id,
            ).where(OtpFlow.id == flow_id)
        ).one_or_none()
        if discovery is None:
            continue
        record_id, registration_id, authority_id = discovery
        mentor_boundary = (
            _prelock_subject_mentor_erasure(
                session, registration_id, now=now
            )
            if registration_id is not None
            else None
        )
        record = None
        if record_id is not None:
            record = session.scalar(
                select(RegistrationIdempotencyRecord)
                .where(RegistrationIdempotencyRecord.id == record_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        registration = None
        if registration_id is not None:
            registration = session.scalar(
                select(StudentRegistration)
                .where(StudentRegistration.id == registration_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        authority = session.scalar(
            select(OtpPurposeAuthority)
            .where(OtpPurposeAuthority.id == authority_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        flow = session.scalar(
            select(OtpFlow)
            .where(OtpFlow.id == flow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if flow is None or authority is None or flow.authority_id != authority.id:
            continue
        expires_at = flow.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > now or flow.state not in {
            "pending",
            "code_sent",
            "verified",
            "locked",
        }:
            continue
        if flow.purpose == "signup":
            # Fence the provider claim before unlinking the ledger or browser
            # capability.  A provider call already outside the transaction may
            # complete physically, but its stale fencing token can no longer
            # activate this verifier or be counted as accepted delivery.
            registration_service.close_expired_signup_delivery(
                session,
                record,
                (authority, flow),
                now=now,
            )
        else:
            otp_outbox.fence_expired_flow_deliveries(
                session,
                authority,
                now=now,
            )
            flow.state = "expired"
            flow.consumed_at = now
            flow.destination_masked_ct = None
            flow.key_version = None
        expired_flows += 1
        if (
            flow.purpose == "signup"
            and registration is not None
            and registration.status == "otp_pending"
            and registration.deleted_at is None
        ):
            erased = (
                _delete_locked(
                    session, registration, record, mentor_boundary
                )
                if mode == "delete"
                else
                _anonymise_locked(
                    session, registration, record, mentor_boundary
                )
            )
            if not erased:
                continue
            session.add(
                AuditEvent(
                    actor_role="system",
                    action="student.registration.otp_retention_expired",
                    resource_type="student_registration",
                    resource_id=registration.id,
                    after_state={"mode": mode},
                )
            )
            expired_registrations += 1
            continue
        if (
            flow.purpose == "signup"
            and record is not None
            and record.state in {"pending", "succeeded", "neutralized"}
        ):
            record.state = "retired"
            record.request_fingerprint = None
            record.request_fingerprint_version = None
            record.outcome_code = "registration_replay_expired"
            record.registration_id = None
            record.outbox_id = None
            record.updated_at = now
    session.flush()
    legacy_destinations = otp_outbox.purge_legacy_destinations(
        session,
        now=now,
        retention_seconds=(
            settings.otp_outbox_legacy_destination_retention_seconds
        ),
    )
    terminal_cutoff = now - timedelta(
        seconds=settings.otp_security_state_retention_seconds
    )
    terminal_flow_ids = list(
        session.scalars(
            select(OtpFlow.id)
            .where(
                OtpFlow.state.in_(("expired", "consumed", "failed")),
                OtpFlow.consumed_at < terminal_cutoff,
            )
            .order_by(OtpFlow.id)
        )
    )
    terminal_flows_deleted = 0
    for flow_id in terminal_flow_ids:
        links = session.execute(
            select(
                OtpFlow.registration_idempotency_record_id,
                OtpFlow.authority_id,
            ).where(OtpFlow.id == flow_id)
        ).one_or_none()
        if links is None:
            continue
        record_id, authority_id = links
        record = None
        if record_id is not None:
            record = session.scalar(
                select(RegistrationIdempotencyRecord)
                .where(RegistrationIdempotencyRecord.id == record_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if record is None or record.state not in {"retired", "erased"}:
                continue
        session.scalar(
            select(OtpPurposeAuthority)
            .where(OtpPurposeAuthority.id == authority_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        flow = session.scalar(
            select(OtpFlow)
            .where(OtpFlow.id == flow_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            flow is None
            or flow.state not in {"expired", "consumed", "failed"}
            or flow.consumed_at is None
            or (
                flow.consumed_at.replace(tzinfo=timezone.utc)
                if flow.consumed_at.tzinfo is None
                else flow.consumed_at.astimezone(timezone.utc)
            )
            >= terminal_cutoff
        ):
            continue
        session.delete(flow)
        terminal_flows_deleted += 1
    session.flush()
    terminal_challenges_deleted, terminal_outboxes_deleted = (
        _purge_terminal_otp_graphs(
            session,
            cutoff=terminal_cutoff,
        )
    )
    authority_ids = list(
        session.scalars(
            select(OtpPurposeAuthority.id)
            .where(OtpPurposeAuthority.updated_at < terminal_cutoff)
            .order_by(OtpPurposeAuthority.id)
        )
    )
    authorities_deleted = 0
    for authority_id in authority_ids:
        authority = session.scalar(
            select(OtpPurposeAuthority)
            .where(OtpPurposeAuthority.id == authority_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if authority is None:
            continue
        has_flow = session.scalar(
            select(OtpFlow.id)
            .where(OtpFlow.authority_id == authority.id)
            .limit(1)
        )
        has_challenge = session.scalar(
            select(OtpChallenge.id)
            .where(OtpChallenge.authority_id == authority.id)
            .limit(1)
        )
        if has_flow is not None or has_challenge is not None:
            continue
        session.delete(authority)
        authorities_deleted += 1
    session.flush()
    rate_buckets = otp_authority.purge_expired_rate_buckets(
        session, now=now
    )
    return {
        "otp_flows": expired_flows,
        "otp_terminal_flows": terminal_flows_deleted,
        "otp_authorities": authorities_deleted,
        "otp_terminal_challenges": terminal_challenges_deleted,
        "otp_terminal_outboxes": terminal_outboxes_deleted,
        "otp_expired_registrations": expired_registrations,
        "otp_rate_limit_buckets": rate_buckets,
        "otp_legacy_destinations": legacy_destinations,
    }


def _dispose_email_identity_graph(session: Session, user_id, *, now: datetime, mode: str) -> None:
    """NYAY-12: dispose the subject's complete email-identity graph in this transaction.

    Runs after the OTP/LoginAttempt -> User -> AuthSession and NYAY-11 authority
    boundaries and before the aggregate audit row, so the caller's mentor
    DEFER decision and lock order are preserved. Identities become unlinkable
    tombstones (no decryptable address, per-row erased hash, no primary, no
    challenge), sealed ledger outcomes are deleted, and reconciliation records
    lose this party's link; a record with no remaining party is resolved with an
    unlinkable hash. ``mode="delete"`` performs the same disposition before the
    User row (and its CASCADE) is removed so no partial state can survive.
    """

    from app.models.email_identity import (
        EmailIdentityMutation,
        EmailIdentityReconciliation,
        UserEmailIdentity,
    )
    from app.services.email_identity_service import tombstone_identity

    identities = list(
        session.scalars(
            select(UserEmailIdentity)
            .where(UserEmailIdentity.user_id == user_id)
            .order_by(UserEmailIdentity.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for row in identities:
        tombstone_identity(row, now=now)
    session.execute(
        delete(EmailIdentityMutation).where(EmailIdentityMutation.user_id == user_id)
    )
    reconciliations = list(
        session.scalars(
            select(EmailIdentityReconciliation)
            .where(
                (EmailIdentityReconciliation.holder_user_id == user_id)
                | (EmailIdentityReconciliation.claimant_user_id == user_id)
            )
            .order_by(EmailIdentityReconciliation.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for record in reconciliations:
        if record.holder_user_id == user_id:
            record.holder_user_id = None
        if record.claimant_user_id == user_id:
            record.claimant_user_id = None
        if record.holder_user_id is None and record.claimant_user_id is None:
            record.email_hash = keyed_hash(
                f"nyay12:email-reconciliation-erased:v1:{record.id}"
            )
            record.state = "resolved"
            record.resolved_at = now
            record.metadata_json = {"resolution": "subjects_erased"}
        record.updated_at = now
    if mode == "delete":
        # Hard deletion: the tombstones and ledger rows must not depend on the
        # User CASCADE (absent on the SQLite oracle) to disappear.
        session.execute(
            delete(UserEmailIdentity).where(UserEmailIdentity.user_id == user_id)
        )
    session.flush()


def _purge_email_identity_terminal_state(
    session: Session, *, now: datetime, days: int | None
) -> dict[str, int]:
    """Bounded terminal retention for NYAY-12 tombstones, ledgers and resolved records."""

    from app.models.email_identity import (
        EmailIdentityMutation,
        EmailIdentityReconciliation,
        UserEmailIdentity,
    )

    counts = {
        "email_identity_tombstones": 0,
        "email_identity_mutations": 0,
        "email_identity_reconciliations": 0,
    }
    cutoff = _cutoff(now, days)
    if cutoff is None:
        return counts
    tombstones = list(
        session.scalars(
            select(UserEmailIdentity)
            .where(
                UserEmailIdentity.state == "removed",
                UserEmailIdentity.removed_at.is_not(None),
                UserEmailIdentity.removed_at < cutoff,
            )
            .order_by(UserEmailIdentity.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for row in tombstones:
        if _as_retention_utc(row.removed_at) >= cutoff:
            continue
        session.delete(row)
        counts["email_identity_tombstones"] += 1
    ledgers = list(
        session.scalars(
            select(EmailIdentityMutation)
            .where(EmailIdentityMutation.created_at < cutoff)
            .order_by(EmailIdentityMutation.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for row in ledgers:
        if _as_retention_utc(row.created_at) >= cutoff:
            continue
        session.delete(row)
        counts["email_identity_mutations"] += 1
    resolved = list(
        session.scalars(
            select(EmailIdentityReconciliation)
            .where(
                EmailIdentityReconciliation.state == "resolved",
                EmailIdentityReconciliation.resolved_at.is_not(None),
                EmailIdentityReconciliation.resolved_at < cutoff,
            )
            .order_by(EmailIdentityReconciliation.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for row in resolved:
        if _as_retention_utc(row.resolved_at) >= cutoff:
            continue
        session.delete(row)
        counts["email_identity_reconciliations"] += 1
    session.flush()
    return counts


def _anonymise_locked(
    session: Session,
    reg: StudentRegistration,
    idempotency_record: RegistrationIdempotencyRecord | None,
    mentor_boundary,
) -> bool:
    from app.services import mentor_ceremony

    mentor_ceremony.validate_subject_mentor_erasure_boundary(
        session, mentor_boundary, reg.id
    )
    approval = mentor_ceremony.prepare_subject_mentor_registration_erasure(
        session, mentor_boundary, reg
    )
    if approval == "DEFER":
        return False
    mentor_ceremony.consume_subject_mentor_erasure_approval(
        session, approval, reg.id
    )
    registration_service.terminalize_registration_idempotency(
        session,
        reg,
        state="erased",
        locked_record=idempotency_record,
    )
    session.flush()
    original_mobile_hash = reg.mobile_hash
    _erase_registration_otp_security_graph(
        session,
        reg,
        original_mobile_hash=original_mobile_hash,
        mode="anonymise",
    )
    # Keep OTP/LoginAttempt -> User -> AuthSession before NYAY-11 dependent
    # authority rows. Review holds the same reviewer User/session boundary
    # before its email proofs and target state; reversing that order deadlocks
    # reviewer erasure against an in-flight institutional review. This helper
    # has not deleted User/registration, so their proof links remain available
    # for explicit revocation and aggregate audit in this same transaction.
    from app.services.student_authority import erase_owner_authority
    erase_owner_authority(session, reg.user_id, now=datetime.now(timezone.utc))
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
    # Preserve the canonical NYAY-5 graph order after the registration lock:
    # profile -> institutional verification -> guardian.  A concurrent review
    # cannot leave authoritative email proof attached to an anonymised profile.
    prof = session.scalar(
        select(StudentProfile)
        .where(StudentProfile.registration_id == reg.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    verification = session.scalar(
        select(StudentVerification)
        .where(StudentVerification.registration_id == reg.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    session.scalar(
        select(GuardianConsent)
        .where(GuardianConsent.registration_id == reg.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if verification is not None:
        verification.status = "revoked"
        verification.verified_email_hash = None
        verification.metadata_json = None
    if prof is not None:
        prof.college = None
        prof.year_of_study = None
        prof.city = None
        prof.preferred_language = None
        prof.pronouns = None
        prof.metadata_json = None
        for col in ("enrolment_ct", "institutional_email_ct", "bar_enrolment_ct"):
            setattr(prof, col, ANONYMISED)
        for col in ("enrolment_hash", "institutional_email_hash", "bar_enrolment_hash"):
            setattr(prof, col, None)
        session.execute(
            delete(StudentProfileInterest).where(
                StudentProfileInterest.profile_id == prof.id
            )
        )
        session.execute(
            delete(StudentProfileGoal).where(StudentProfileGoal.profile_id == prof.id)
        )
    mutation_ledgers = list(
        session.scalars(
            select(ProfileMutationIdempotencyRecord)
            .where(
                ProfileMutationIdempotencyRecord.actor_user_id == reg.user_id
            )
            .order_by(ProfileMutationIdempotencyRecord.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    erased_at = datetime.now(timezone.utc)
    for ledger in mutation_ledgers:
        ledger.idempotency_key_hash = keyed_hash(
            f"profile-mutation-erased:v1:{ledger.id}"
        )
        ledger.request_fingerprint = None
        ledger.request_fingerprint_version = None
        ledger.state = "erased"
        ledger.outcome_status = None
        ledger.outcome_ct = None
        ledger.key_version = None
        ledger.profile_version = None
        ledger.updated_at = erased_at
    # NYAY-12: the email-identity graph is disposed after the NYAY-11 authority
    # boundary and the profile ledgers, inside this same transaction.
    _dispose_email_identity_graph(
        session, reg.user_id, now=erased_at, mode="anonymise"
    )
    session.add(
        AuditEvent(
            actor_role="system",
            action="student.registration.anonymised",
            resource_type="student_registration",
            resource_id=reg.id,
            after_state={"status": "deleted"},
        )
    )
    return True


def anonymise_registration(session: Session, reg: StudentRegistration) -> bool:
    """Scrub one subject under ledger -> registration locks.

    Return ``True`` only after anonymisation completes. Return ``False`` when
    the registration no longer exists or the mentor authority graph defers
    erasure.
    """

    mentor_boundary = _prelock_subject_mentor_erasure(session, reg.id)
    locked, idempotency_record = (
        registration_service.lock_registration_with_idempotency(session, reg.id)
    )
    if locked is None:
        return False
    return _anonymise_locked(session, locked, idempotency_record, mentor_boundary)


def _delete_locked(
    session: Session,
    reg: StudentRegistration,
    idempotency_record: RegistrationIdempotencyRecord | None,
    mentor_boundary,
) -> bool:
    from app.services import mentor_ceremony

    mentor_ceremony.validate_subject_mentor_erasure_boundary(
        session, mentor_boundary, reg.id
    )
    approval = mentor_ceremony.prepare_subject_mentor_registration_erasure(
        session, mentor_boundary, reg
    )
    if approval == "DEFER":
        return False
    mentor_ceremony.consume_subject_mentor_erasure_approval(
        session, approval, reg.id
    )
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
    _erase_registration_otp_security_graph(
        session,
        reg,
        original_mobile_hash=reg.mobile_hash,
        mode="delete",
    )
    # The security graph acquires the existing OTP/LoginAttempt -> User ->
    # AuthSession order without deleting User/registration. Retire dependent
    # authority only after that reviewer serialization boundary, and before
    # User deletion can SET NULL the links needed for revocation/audit.
    from app.services.student_authority import erase_owner_authority
    erase_owner_authority(session, reg.user_id, now=datetime.now(timezone.utc))
    # NYAY-12: explicit disposition before User deletion so reconciliation links
    # are severed deterministically rather than by SET NULL, and no ledger or
    # decryptable identity can outlive a failed CASCADE.
    _dispose_email_identity_graph(
        session, reg.user_id, now=datetime.now(timezone.utc), mode="delete"
    )

    from app.models.registration import (
        Consent,
        GuardianConsent,
        RegistrationDobReconciliation,
        StudentVerification,
    )

    profile_ids = list(
        session.scalars(
            select(StudentProfile.id).where(
                StudentProfile.registration_id == reg.id
            )
        )
    )
    if profile_ids:
        session.execute(
            delete(StudentProfileInterest).where(
                StudentProfileInterest.profile_id.in_(profile_ids)
            )
        )
        session.execute(
            delete(StudentProfileGoal).where(
                StudentProfileGoal.profile_id.in_(profile_ids)
            )
        )

    for model in (
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
    return True


def delete_registration(session: Session, reg: StudentRegistration) -> bool:
    """Hard-delete one subject under ledger -> registration locks.

    Return ``True`` only after deletion completes. Return ``False`` when the
    registration no longer exists or the mentor authority graph defers
    erasure.
    """

    mentor_boundary = _prelock_subject_mentor_erasure(session, reg.id)
    locked, idempotency_record = (
        registration_service.lock_registration_with_idempotency(session, reg.id)
    )
    if locked is None:
        return False
    return _delete_locked(session, locked, idempotency_record, mentor_boundary)


def _purge_expired_challenge(
    session: Session,
    challenge_id,
    cutoff: datetime,
    mode: str,
    *,
    now: datetime | None = None,
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
    mentor_boundary = _prelock_subject_mentor_erasure(
        session, registration_id, now=now
    )
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
            erased = (
                _delete_locked(
                    session, registration, record, mentor_boundary
                )
                if mode == "delete"
                else
                _anonymise_locked(
                    session, registration, record, mentor_boundary
                )
            )
            if not erased:
                return 0, 0
            session.add(
                AuditEvent(
                    actor_role="system",
                    action="student.registration.otp_retention_expired",
                    resource_type="student_registration",
                    resource_id=registration.id,
                    after_state={"mode": mode},
                )
            )
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
    now = _as_retention_utc(now)
    policy = _validated_policy(policy or RetentionPolicy.from_settings())
    security_counts = purge_otp_security_state(
        session,
        now=now,
        registration_mode=policy.mode,
    )
    counts = {
        "registrations": security_counts["otp_expired_registrations"],
        "otp_challenges": 0,
        "recovery_sessions": 0,
        **security_counts,
    }

    def _apply(
        registration_id,
        *,
        statuses: set[str],
        cutoff: datetime,
        timestamp_field: str,
    ) -> None:
        mentor_boundary = _prelock_subject_mentor_erasure(
            session, registration_id, now=now
        )
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
        erased = (
            _delete_locked(
                session, reg, idempotency_record, mentor_boundary
            )
            if policy.mode == "delete"
            else
            _anonymise_locked(
                session, reg, idempotency_record, mentor_boundary
            )
        )
        if erased:
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
                session, challenge_id, otp_cut, policy.mode, now=now
            )
            counts["otp_challenges"] += challenge_count
            counts["registrations"] += registration_count

    rec_cut = _cutoff(now, policy.recovery_session_days)
    if rec_cut is not None:
        recovery_ids = list(
            session.scalars(
                select(RecoverySession.id)
                .where(RecoverySession.created_at < rec_cut)
                .order_by(RecoverySession.id)
            )
        )
        for recovery_id in recovery_ids:
            rs = session.scalar(
                select(RecoverySession)
                .where(
                    RecoverySession.id == recovery_id,
                    RecoverySession.created_at < rec_cut,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if rs is None or _as_retention_utc(rs.created_at) >= rec_cut:
                continue
            session.delete(rs)
            counts["recovery_sessions"] += 1
        # Registration erasure holds RecoverySession before LoginAttempt.
        # Materialize these deletes before the auth sweep acquires attempt
        # locks, preventing deferred-flush lock inversion on PostgreSQL.
        session.flush()

    counts.update(
        _purge_auth_security_history(session, now=now, policy=policy)
    )
    counts.update(
        _purge_email_identity_terminal_state(
            session, now=now, days=policy.email_identity_terminal_days
        )
    )
    session.flush()
    return counts
