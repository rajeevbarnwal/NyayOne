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
from app.services import otp_outbox, otp_service

LOGIN_COOLDOWN_SECONDS = 30


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
    user = session.get(User, registration.user_id) if registration is not None else None
    eligible = bool(
        registration
        and registration.status in {"otp_verified", "active"}
        and user
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
        challenge, intent = otp_service.issue_challenge(
            session,
            registration.id,
            now,
            purpose="login",
            destination=decrypt(registration.mobile_ct),
        )
        attempt.challenge_id = challenge.id
    return attempt.opaque_id, intent


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
    user = session.get(User, registration.user_id) if registration is not None else None
    if (
        registration is None
        or user is None
        or registration.status not in {"otp_verified", "active"}
        or user.status in {"suspended", "deleted"}
    ):
        session.rollback()
        raise LoginError()

    # Successful login rotates prior active sessions for this user. This makes
    # copied/stale cookies stop authorising immediately after a fresh login.
    for prior in session.scalars(
        select(AuthSession)
        .where(AuthSession.user_id == user.id, AuthSession.status == "active")
        .with_for_update()
    ):
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
    return raw_token, auth_session


def _active_session(
    session: Session, raw_token: str | None, now: datetime
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
        row.status = "expired"
        session.commit()
        return None
    return row


def session_claims(
    session: Session, raw_token: str | None, now: datetime
) -> dict[str, object] | None:
    """Resolve an HttpOnly-cookie token into the existing actor-claims shape."""
    now = _as_utc(now)
    auth_session = _active_session(session, raw_token, now)
    if auth_session is None:
        return None
    user = session.get(User, auth_session.user_id)
    if user is None or user.status != "active":
        return None
    registration = session.scalar(
        select(StudentRegistration)
        .where(StudentRegistration.user_id == user.id)
        .order_by(StudentRegistration.created_at.desc())
    )
    if registration is None or registration.status not in {"otp_verified", "active"}:
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
    auth_session.last_seen_at = now
    session.commit()
    return {
        "sub": str(user.id),
        "roles": ["student"],
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
