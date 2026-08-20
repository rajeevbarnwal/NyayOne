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

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt, keyed_hash
from app.db.models.audit import AuditEvent
from app.models.registration import (
    AuthSession,
    Consent,
    LoginAttempt,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.services import integrity_errors, otp_outbox, otp_service

LOGIN_COOLDOWN_SECONDS = 30
ACTIVE_SESSION_CONSTRAINT = "uq_auth_sessions_one_active_per_user"


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
        select(StudentRegistration).where(StudentRegistration.mobile_hash == lookup)
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
        )
    )


def rotate_authenticated_session(
    session: Session,
    registration: StudentRegistration,
    now: datetime,
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

    for prior in active_sessions_for_rotation(session, user.id):
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
    attempt = session.scalar(
        select(LoginAttempt)
        .where(LoginAttempt.opaque_id == opaque_id)
        .with_for_update()
    )
    if (
        attempt is None
        or attempt.registration_id is None
        or attempt.challenge_id is None
        or attempt.status != "pending"
        or attempt.consumed_at is not None
    ):
        raise LoginError()
    if _as_utc(attempt.expires_at) <= now:
        attempt.status = "expired"
        session.commit()
        raise LoginError()

    try:
        otp_service.verify(
            session,
            attempt.registration_id,
            code,
            now,
            purpose="login",
            challenge_id=attempt.challenge_id,
            commit_on_success=False,
        )
    except otp_service.OtpError as exc:
        # One typed response for wrong, expired, locked and replayed codes.
        raise LoginError() from exc

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

    registration = session.get(StudentRegistration, attempt.registration_id)
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
    row = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == keyed_hash(raw_token))
    )
    if row is None or row.status != "active":
        return None
    if _as_utc(row.expires_at) <= now:
        if touch:
            row.status = "expired"
            session.commit()
        return None
    return row


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
            "verified" if verification and verification.status == "verified" else "draft"
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
