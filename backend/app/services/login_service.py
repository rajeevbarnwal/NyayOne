"""Non-enumerating student OTP login and server-side cookie sessions.

The client receives two opaque values only: a one-use login-attempt id in JSON
and, after successful verification, a random bearer token in an HttpOnly cookie.
The database stores keyed hashes of mobiles/session tokens and never stores an
OTP or session token in plaintext.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt, keyed_hash
from app.core.student_verification_authority import (
    has_authoritative_institutional_email_proof,
)
from app.db.models.audit import AuditEvent
from app.models.registration import (
    AuthSession,
    AuthSessionProfilePrompt,
    Consent,
    LoginAttempt,
    OtpChallenge,
    OtpFlow,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.services import (
    integrity_errors,
    otp_authority,
    otp_flow_service,
    otp_outbox,
    otp_service,
    registration_service,
)

LOGIN_COOLDOWN_SECONDS = 30
ACTIVE_SESSION_CONSTRAINT = "uq_auth_sessions_one_active_per_user"
ERASED_LIFECYCLE_AT = datetime(1970, 1, 1, tzinfo=timezone.utc)


class LoginError(Exception):
    """Uniform login failure; callers must not expose its internal cause."""

    def __init__(self, status_code: int = 401, code: str = "login_failed") -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _recent_attempt(
    session: Session,
    lookup_hash: str,
    excluded_id: uuid.UUID,
    now: datetime,
) -> bool:
    prior = session.scalar(
        select(LoginAttempt)
        .where(
            LoginAttempt.lookup_hash == lookup_hash,
            LoginAttempt.id != excluded_id,
        )
        .order_by(LoginAttempt.created_at.desc())
    )
    return bool(
        prior
        and (now - _as_utc(prior.created_at)).total_seconds()
        < LOGIN_COOLDOWN_SECONDS
    )


def start(
    session: Session,
    mobile: str,
    now: datetime,
) -> tuple[str, otp_outbox.DeliveryIntent | None]:
    """Persist a real or decoy attempt and optionally enqueue a login OTP.

    Known and unknown mobiles receive the same status and response shape. A
    cooldown request also receives a fresh decoy-shaped attempt, so it cannot
    supersede or reveal the prior real challenge.
    """
    now = _as_utc(now)
    lookup = keyed_hash(mobile)
    registration = session.scalar(
        select(StudentRegistration).where(
            StudentRegistration.mobile_hash == lookup,
            *otp_service.registration_authority_filters(),
        )
    )
    if not otp_service.registration_is_authorizable(registration):
        registration = None
    if registration is not None:
        # Serialize the cooldown decision as well as the eventual replacement;
        # locking only in issue_challenge would allow two deliverable codes.
        registration = otp_service.lock_registration_for_update(
            session, registration.id
        )
    user = session.get(User, registration.user_id) if registration is not None else None
    eligible = bool(
        registration
        and otp_service.registration_is_authorizable(registration)
        and registration.status in {"otp_verified", "active"}
        and user
        and user.role == "student"
        and user.status not in {"suspended", "deleted"}
    )

    attempt = LoginAttempt(
        opaque_id=uuid.uuid4().hex,
        lookup_hash=lookup,
        registration_id=registration.id if eligible and registration else None,
        status="pending",
        expires_at=now + timedelta(seconds=settings.login_attempt_ttl_seconds),
    )
    session.add(attempt)
    session.flush()

    intent: otp_outbox.DeliveryIntent | None = None
    if eligible and registration is not None and not _recent_attempt(
        session, lookup, attempt.id, now
    ):
        try:
            challenge, intent = otp_service.issue_challenge(
                session,
                registration.id,
                now,
                purpose="login",
                destination=decrypt(registration.mobile_ct),
            )
        except otp_service.OtpError as exc:
            if exc.code != "otp_issue_conflict":
                raise
            # Preserve the endpoint's non-enumerating 202 response. The
            # savepoint in issue_challenge left this attempt transaction usable.
            intent = None
        else:
            attempt.challenge_id = challenge.id
    return attempt.opaque_id, intent


def start_flow(
    session: Session,
    mobile: str,
    now: datetime,
) -> tuple[str, OtpFlow, otp_outbox.DeliveryIntent | None]:
    """Create one cookie-owned real or decoy login flow with identical shape."""

    now = _as_utc(now)
    lookup = keyed_hash(mobile)
    subject = otp_authority.authority_subject_from_mobile_hash(lookup)
    registration = session.scalar(
        select(StudentRegistration).where(
            StudentRegistration.mobile_hash == lookup,
            *otp_service.registration_authority_filters(),
        )
    )
    if registration is not None:
        registration = otp_service.lock_registration_for_update(
            session, registration.id
        )
    user = session.get(User, registration.user_id) if registration is not None else None
    eligible = bool(
        registration is not None
        and otp_service.registration_is_authorizable(registration)
        and registration.status in {"otp_verified", "active"}
        and user is not None
        and user.role == "student"
        and user.status not in {"suspended", "deleted"}
    )
    if not eligible:
        # Unknown and ineligible/deleted lookups use the same stable decoy
        # domain. They must never rediscover an old registration-bound
        # authority (and its active challenge) with registration_id=None.
        subject = otp_authority.authority_subject_from_mobile_hash(
            keyed_hash(f"nyayone:otp-login-decoy:v1:{mobile}")
        )
    authority = otp_authority.lock_or_create_authority(
        session,
        subject_hash=subject,
        purpose="login",
        registration_id=registration.id if eligible and registration else None,
        now=now,
    )
    cooldown = bool(
        authority.cooldown_until is not None
        and _as_utc(authority.cooldown_until) > now
    )
    locked = otp_authority.locked_for_seconds(authority, now) > 0
    intent: otp_outbox.DeliveryIntent | None = None
    candidate = None
    active = session.scalar(
        select(OtpChallenge).where(
            OtpChallenge.authority_id == authority.id,
            OtpChallenge.delivery_state == "active",
        )
    )
    repeated_issue = authority.last_issued_at is not None
    if eligible and registration is not None and not cooldown and not locked:
        if repeated_issue:
            otp_service.consume_resend_window(authority, now)
            session.flush()
        generation = authority.generation
        candidate, intent = otp_service.issue_challenge(
            session,
            registration.id,
            now,
            purpose="login",
            destination=decrypt(registration.mobile_ct),
        )
        if authority.generation == generation:
            # Reusing the exact pending provider intent is still a public
            # issuance and advances the same stable cooldown/window as decoy.
            otp_service.note_decoy_issue(authority, now=now)
    elif not cooldown and not locked:
        if repeated_issue:
            otp_service.consume_resend_window(authority, now)
        otp_service.note_decoy_issue(authority, now=now)
    raw_token, flow = otp_flow_service.create_flow(
        session,
        authority,
        now=now,
        destination=mobile,
        # A staged replacement never displaces the prior usable challenge in
        # browser authority before provider success.
        challenge=active or candidate,
        registration_id=(registration.id if eligible and registration else None),
    )
    return raw_token, flow, intent


def verify_flow(
    session: Session,
    raw_flow_token: str | None,
    code: str,
    now: datetime,
    *,
    commit_on_success: bool = True,
) -> tuple[str, AuthSession, OtpFlow]:
    """Verify a cookie flow, consuming the same decoy budget on every miss."""

    now = _as_utc(now)
    graph = otp_flow_service.resolve_flow(session, raw_flow_token)
    if graph is None:
        raise LoginError()
    authority, flow = graph
    if (
        flow.purpose != "login"
        or flow.state not in {"pending", "code_sent", "locked"}
        or _as_utc(flow.expires_at) <= now
    ):
        raise LoginError()
    if flow.registration_id is None or flow.challenge_id is None:
        try:
            otp_service.record_failed_attempt(session, authority, now=now)
        except otp_service.OtpError as exc:
            raise LoginError() from exc
        raise LoginError()
    try:
        otp_service.verify(
            session,
            flow.registration_id,
            code,
            now,
            purpose="login",
            challenge_id=flow.challenge_id,
            commit_on_success=False,
        )
    except otp_service.OtpError as exc:
        if exc.code not in {"incorrect_otp", "locked"}:
            # An undelivered, missing or expired real verifier must consume the
            # same stable authority attempt as a decoy.  Otherwise provider
            # state becomes visible through attempts_left on the uniform API.
            try:
                otp_service.record_failed_attempt(
                    session, authority, now=now
                )
            except otp_service.OtpError as uniform_exc:
                raise LoginError() from uniform_exc
        raise LoginError() from exc
    registration = session.get(StudentRegistration, flow.registration_id)
    if not otp_service.registration_is_authorizable(registration):
        session.rollback()
        raise LoginError()
    # Flow retirement is part of the same commit as challenge consumption and
    # authenticated-session rotation; no crash window leaves both capabilities.
    otp_flow_service.mark_authenticated(flow, now=now)
    raw_session, auth_session = rotate_authenticated_session(
        session,
        registration,  # type: ignore[arg-type]
        now,
        commit_on_success=commit_on_success,
    )
    return raw_session, auth_session, flow


def lock_user_for_session_rotation(
    session: Session,
    user_id: uuid.UUID,
) -> User | None:
    """Lock the stable session parent, including the zero-child case."""

    return session.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def active_sessions_for_rotation(
    session: Session,
    user_id: uuid.UUID,
) -> list[AuthSession]:
    """Materialize the active children only after the stable parent is locked."""

    return list(
        session.scalars(
            select(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.status == "active",
            )
            .order_by(AuthSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def erase_login_attempt(attempt: LoginAttempt) -> None:
    """Replace one terminal attempt with a non-linkable fixed-time tombstone."""

    attempt.opaque_id = keyed_hash(
        f"nyayone:login-attempt-erased-opaque:v1:{attempt.id}"
    )
    attempt.lookup_hash = keyed_hash(
        f"nyayone:login-attempt-erased-lookup:v1:{attempt.id}"
    )
    attempt.registration_id = None
    attempt.challenge_id = None
    attempt.status = "erased"
    attempt.expires_at = ERASED_LIFECYCLE_AT
    attempt.consumed_at = ERASED_LIFECYCLE_AT
    attempt.created_at = ERASED_LIFECYCLE_AT
    attempt.updated_at = ERASED_LIFECYCLE_AT
    attempt.deleted_at = ERASED_LIFECYCLE_AT
    attempt.metadata_json = None


def erase_auth_session(auth_session: AuthSession) -> None:
    """Destroy every bearer/user/time link while retaining a unique row."""

    auth_session.user_id = None
    auth_session.token_hash = keyed_hash(
        f"nyayone:auth-session-erased-token:v1:{auth_session.id}"
    )
    auth_session.status = "erased"
    auth_session.expires_at = ERASED_LIFECYCLE_AT
    auth_session.last_seen_at = ERASED_LIFECYCLE_AT
    auth_session.revoked_at = ERASED_LIFECYCLE_AT
    auth_session.created_at = ERASED_LIFECYCLE_AT
    auth_session.updated_at = ERASED_LIFECYCLE_AT
    auth_session.deleted_at = ERASED_LIFECYCLE_AT
    auth_session.metadata_json = None


def clear_profile_prompts(
    session: Session,
    auth_session_ids: list[uuid.UUID] | tuple[uuid.UUID, ...],
) -> None:
    """Remove session-scoped profile UI state before session retirement.

    Prompt dismissal is deliberately scoped to one active bearer session.  A
    revoked, expired, rotated, or erased session must therefore take its
    dismissal row with it instead of leaking UI state into lifecycle history.
    """

    session_ids = tuple(dict.fromkeys(auth_session_ids))
    if session_ids:
        session.execute(
            delete(AuthSessionProfilePrompt).where(
                AuthSessionProfilePrompt.auth_session_id.in_(session_ids)
            )
        )


def suspend_user_and_revoke_sessions(
    session: Session,
    user_id: uuid.UUID,
    now: datetime,
) -> int:
    """Freeze account login authority without committing the caller's unit.

    The stable User row is locked before its session children.  Privacy-delete
    uses this inside the same transaction as recovery-proof consumption and
    DSR creation, so failure rolls every part back together.
    """

    now = _as_utc(now)
    user = lock_user_for_session_rotation(session, user_id)
    if user is None:
        raise LoginError()
    rows = list(
        session.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.status == "active",
            )
            .order_by(AuthSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    clear_profile_prompts(session, [row.id for row in rows])
    for row in rows:
        if _as_utc(row.expires_at) <= now:
            row.status = "expired"
            row.revoked_at = row.expires_at
        else:
            row.status = "revoked"
            row.revoked_at = now
    user.status = "suspended"
    return len(rows)


def rotate_authenticated_session(
    session: Session,
    registration: StudentRegistration,
    now: datetime,
    *,
    commit_on_success: bool = True,
) -> tuple[str, AuthSession]:
    """Serialize and atomically replace the active session for one user.

    The stable ``users`` row is the lock authority even when no active child
    session exists.  Keeping this operation separate from OTP proof lets the
    PostgreSQL gate exercise the rotation invariant directly without weakening
    the login attempt/challenge boundary.
    """

    now = _as_utc(now)
    user = lock_user_for_session_rotation(session, registration.user_id)
    if (
        user is None
        or user.role != "student"
        or not otp_service.registration_is_authorizable(registration)
        or registration.status not in {"otp_verified", "active"}
        or user.status in {"suspended", "deleted"}
    ):
        session.rollback()
        raise LoginError()

    prior_sessions = active_sessions_for_rotation(session, user.id)
    clear_profile_prompts(session, [prior.id for prior in prior_sessions])
    for prior in prior_sessions:
        prior.status = "revoked"
        prior.revoked_at = now

    raw_token = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=keyed_hash(raw_token),
        status="active",
        expires_at=now + timedelta(seconds=settings.auth_session_ttl_seconds),
        last_seen_at=now,
    )
    session.add(auth_session)
    registration.status = "active"
    user.status = "active"
    try:
        session.flush()
        session.add(
            AuditEvent(
                actor_user_id=user.id,
                actor_role="student",
                action="student.auth.login_succeeded",
                resource_type="auth_session",
                resource_id=auth_session.id,
                after_state={"method": "otp", "rotated": True},
            )
        )
        if commit_on_success:
            session.commit()
    except IntegrityError as exc:
        session.rollback()
        if integrity_errors.constraint_name(exc) == ACTIVE_SESSION_CONSTRAINT:
            raise LoginError(409, "login_conflict") from exc
        raise
    return raw_token, auth_session


def verify(
    session: Session,
    opaque_id: str,
    code: str,
    now: datetime,
) -> tuple[str, AuthSession]:
    """Consume one login attempt and atomically create a rotated auth session."""
    now = _as_utc(now)
    discovery = session.execute(
        select(
            LoginAttempt.id,
            LoginAttempt.registration_id,
            LoginAttempt.challenge_id,
            LoginAttempt.status,
            LoginAttempt.expires_at,
            LoginAttempt.consumed_at,
        ).where(LoginAttempt.opaque_id == opaque_id)
    ).one_or_none()
    if (
        discovery is None
        or discovery.registration_id is None
        or discovery.challenge_id is None
        or discovery.status != "pending"
        or discovery.consumed_at is not None
    ):
        raise LoginError()
    registration, _ = registration_service.lock_registration_with_idempotency(
        session, discovery.registration_id
    )
    if registration is None:
        raise LoginError()
    if _as_utc(discovery.expires_at) <= now:
        attempt = session.scalar(
            select(LoginAttempt)
            .where(LoginAttempt.id == discovery.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            attempt is None
            or attempt.registration_id != discovery.registration_id
            or attempt.challenge_id != discovery.challenge_id
            or attempt.status != "pending"
            or attempt.consumed_at is not None
        ):
            raise LoginError()
        attempt.status = "expired"
        attempt.consumed_at = attempt.expires_at
        session.commit()
        raise LoginError()

    try:
        otp_service.verify(
            session,
            discovery.registration_id,
            code,
            now,
            purpose="login",
            challenge_id=discovery.challenge_id,
            commit_on_success=False,
        )
    except otp_service.OtpError as exc:
        # One typed response for wrong, expired, locked and replayed codes.
        raise LoginError() from exc

    # OTP authority/challenge are locked before the legacy attempt child, the
    # same order registration erasure uses. A concurrent attempt-retention
    # winner is revalidated here and causes the whole proof transaction to
    # roll back instead of minting a session.
    attempt = session.scalar(
        select(LoginAttempt)
        .where(LoginAttempt.id == discovery.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        attempt is None
        or attempt.registration_id != discovery.registration_id
        or attempt.challenge_id != discovery.challenge_id
        or attempt.status != "pending"
        or attempt.consumed_at is not None
        or _as_utc(attempt.expires_at) <= now
    ):
        session.rollback()
        raise LoginError()

    # Claim-after-proof, exactly once. PostgreSQL's row locks serialise this;
    # the conditional UPDATE additionally makes the invariant executable on
    # SQLite and protects against any future caller that omits the lock.
    claimed = session.execute(
        update(LoginAttempt)
        .where(LoginAttempt.id == attempt.id, LoginAttempt.status == "pending")
        .values(status="consumed", consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        session.rollback()
        raise LoginError()

    if not otp_service.registration_is_authorizable(registration):
        session.rollback()
        raise LoginError()
    return rotate_authenticated_session(session, registration, now)


def _active_session(
    session: Session,
    raw_token: str | None,
    now: datetime,
    *,
    touch: bool = True,
) -> AuthSession | None:
    if not raw_token:
        return None
    now = _as_utc(now)
    token_hash = keyed_hash(raw_token)
    row = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash)
    )
    if row is None or row.status != "active" or row.user_id is None:
        return None
    if _as_utc(row.expires_at) <= now:
        if touch:
            user = lock_user_for_session_rotation(session, row.user_id)
            row = session.scalar(
                select(AuthSession)
                .where(
                    AuthSession.id == row.id,
                    AuthSession.user_id == row.user_id,
                    AuthSession.token_hash == token_hash,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if user is None or row is None or row.status != "active":
                session.rollback()
                return None
            if _as_utc(row.expires_at) > now:
                return row
            clear_profile_prompts(session, [row.id])
            row.status = "expired"
            row.revoked_at = row.expires_at
            session.commit()
        return None
    if touch:
        user = lock_user_for_session_rotation(session, row.user_id)
        row = session.scalar(
            select(AuthSession)
            .where(
                AuthSession.id == row.id,
                AuthSession.user_id == row.user_id,
                AuthSession.token_hash == token_hash,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None or row is None or row.status != "active":
            session.rollback()
            return None
        if _as_utc(row.expires_at) <= now:
            clear_profile_prompts(session, [row.id])
            row.status = "expired"
            row.revoked_at = row.expires_at
            session.commit()
            return None
    return row


def lock_presented_session_for_effect(
    session: Session,
    raw_token: str | None,
    *,
    expected_user_id: uuid.UUID,
    now: datetime,
    allowed_roles: frozenset[str],
) -> AuthSession | None:
    """Lock and revalidate the exact cookie authority before a domain effect.

    Callers first lock their canonical domain graph (registration/profile or
    credential/review target), then call this helper before any replay return,
    CAS, audit, mutation, or commit.  Inside the helper, lock the stable
    ``User`` parent before the exact ``AuthSession`` row.  Logout and every
    session rotation use that same User -> AuthSession order, so an effect that
    later inserts a user-FK row cannot deadlock with session revocation.  The
    exact session lock still linearizes the effect against logout, rotation,
    suspension, expiry, and erasure.

    The initial token lookup is discovery only.  Every security decision is
    repeated from ``populate_existing`` rows after the session lock is held.
    No lifecycle state is changed and the caller owns commit/rollback.
    """

    if not raw_token:
        return None
    now = _as_utc(now)
    token_hash = keyed_hash(raw_token)
    candidate = session.execute(
        select(AuthSession.id, AuthSession.user_id).where(
            AuthSession.token_hash == token_hash
        )
    ).one_or_none()
    if candidate is None or candidate.user_id != expected_user_id:
        return None
    user = lock_user_for_session_rotation(session, expected_user_id)
    if (
        user is None
        or user.status != "active"
        or user.role not in allowed_roles
    ):
        return None
    auth_session = session.scalar(
        select(AuthSession)
        .where(
            AuthSession.id == candidate.id,
            AuthSession.user_id == expected_user_id,
            AuthSession.token_hash == token_hash,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        auth_session is None
        or auth_session.status != "active"
        or auth_session.deleted_at is not None
        or _as_utc(auth_session.expires_at) <= now
    ):
        return None
    return auth_session


def session_claims(
    session: Session,
    raw_token: str | None,
    now: datetime,
    *,
    touch: bool = True,
) -> dict[str, object] | None:
    """Resolve an HttpOnly-cookie token into the existing actor-claims shape.

    ``touch=False`` is the authorization-dependency path: it must be a pure
    read so a subsequently denied request cannot change session lifecycle or
    telemetry. Explicit session discovery retains the default lifecycle touch.
    """
    now = _as_utc(now)
    auth_session = _active_session(session, raw_token, now, touch=touch)
    if auth_session is None:
        return None
    user = session.get(User, auth_session.user_id)
    if user is None or user.status != "active":
        if touch:
            clear_profile_prompts(session, [auth_session.id])
            auth_session.status = "revoked"
            auth_session.revoked_at = now
            session.commit()
        return None
    # Internal identities are provisioned by the trusted staff identity layer,
    # not by the student OTP flow. They still use the same opaque, hashed,
    # HttpOnly session record once authenticated, so every downstream endpoint
    # consumes one server-authoritative ActorContext.
    if user.role in {"admin", "moderator", "safety_officer", "legal_reviewer"}:
        if touch:
            auth_session.last_seen_at = now
            session.commit()
        return {
            "sub": str(user.id),
            "roles": [user.role],
            "student_profile_id": None,
            "student_verification": "draft",
            "is_minor": False,
            "consent_state": [],
        }
    if user.role != "student":
        return None
    candidates = list(
        session.scalars(
            select(StudentRegistration)
            .where(
                StudentRegistration.user_id == user.id,
                *otp_service.registration_authority_filters(),
            )
            .order_by(StudentRegistration.created_at.desc())
            .limit(2)
        )
    )
    registration = candidates[0] if len(candidates) == 1 else None
    if (
        registration is None
        or registration.status != "active"
    ):
        return None
    profile = session.scalar(
        select(StudentProfile).where(StudentProfile.registration_id == registration.id)
    )
    verification = session.scalar(
        select(StudentVerification).where(
            StudentVerification.registration_id == registration.id
        )
    )
    consent_state = sorted(
        {
            row.purpose
            for row in session.scalars(
                select(Consent).where(
                    Consent.registration_id == registration.id,
                    Consent.accepted.is_(True),
                )
            )
        }
    )
    if touch:
        auth_session.last_seen_at = now
        session.commit()
    return {
        "sub": str(user.id),
        "roles": [user.role],
        "student_profile_id": str(profile.id) if profile is not None else None,
        "student_verification": (
            "verified"
            if has_authoritative_institutional_email_proof(
                verification, profile
            )
            else "draft"
        ),
        "is_minor": registration.is_minor,
        "consent_state": consent_state,
    }


def logout(session: Session, raw_token: str | None, now: datetime) -> None:
    """Revoke the presented session when present; otherwise remain idempotent."""
    now = _as_utc(now)
    row = _active_session(session, raw_token, now)
    if row is None:
        return
    clear_profile_prompts(session, [row.id])
    row.status = "revoked"
    row.revoked_at = now
    session.add(
        AuditEvent(
            actor_user_id=row.user_id,
            actor_role="student",
            action="student.auth.logout",
            resource_type="auth_session",
            resource_id=row.id,
            after_state={"revoked": True},
        )
    )
    session.commit()
