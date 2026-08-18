"""Server-authoritative OTP lifecycle (SAATHI-448 Workstream B).

issue / verify / resend(cooldown) / lockout. Only a keyed verifier is persisted
in the challenge. A short-lived encrypted OTP outbox payload is created in the
same transaction and is delivered only AFTER commit; the ciphertext is erased
after successful delivery. Raw OTP values are never persisted, returned or
logged. All time comparisons use timezone-aware values supplied by the caller
(deterministic + testable).

Challenges are scoped by ``purpose`` ("signup" | "recovery" | "login") so a
code issued for one security boundary can never authenticate another.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt, otp_verifier
from app.models.registration import OtpChallenge
from app.models.registration import StudentRegistration
from app.services import otp_outbox

OTP_TTL_SECONDS = 300
RESEND_COOLDOWN_SECONDS = 30
LOCKOUT_SECONDS = 900
MAX_ATTEMPTS = 3


class OtpError(Exception):
    def __init__(self, status_code: int, code: str, attempts_left: int | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.attempts_left = attempts_left


def _gen_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _as_utc(dt: datetime) -> datetime:
    """Normalize to aware UTC. DB backends (e.g. SQLite) return naive datetimes
    for stored UTC values; treat those as UTC rather than local (avoids a
    tz-shift that could falsely expire a challenge)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _active(
    session: Session,
    registration_id: uuid.UUID,
    purpose: str = "signup",
    *,
    challenge_id: uuid.UUID | None = None,
    for_update: bool = False,
) -> OtpChallenge | None:
    statement = (
        select(OtpChallenge)
        .where(
            OtpChallenge.registration_id == registration_id,
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
        )
        .order_by(OtpChallenge.expires_at.desc())
    )
    if challenge_id is not None:
        statement = statement.where(OtpChallenge.id == challenge_id)
    if for_update:
        # PostgreSQL serialises concurrent verification attempts for the same
        # challenge, preventing lost attempt increments / lockout bypass.
        statement = statement.with_for_update()
    return session.scalar(statement)


def issue_challenge(
    session: Session,
    registration_id: uuid.UUID,
    now: datetime,
    *,
    purpose: str = "signup",
    destination: str,
    destination_ct: str | None = None,
) -> tuple[OtpChallenge, otp_outbox.DeliveryIntent]:
    """Issue a fresh challenge of ``purpose`` and enqueue delivery in the outbox.

    Supersedes any prior un-consumed challenge OF THE SAME PURPOSE so only one is
    active per purpose. Returns (challenge, DeliveryIntent). The intent carries
    only an opaque outbox identifier; the delivery payload is encrypted.
    """
    now = _as_utc(now)
    for prior in session.scalars(
        select(OtpChallenge).where(
            OtpChallenge.registration_id == registration_id,
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
        )
    ):
        prior.consumed_at = now
        meta = dict(prior.metadata_json or {})
        meta["superseded"] = True
        prior.metadata_json = meta
    code = _gen_code()
    salt = str(uuid.uuid4())
    ch = OtpChallenge(
        registration_id=registration_id,
        purpose=purpose,
        verifier_hash=otp_verifier(code, salt=salt),
        attempts=0,
        max_attempts=MAX_ATTEMPTS,
        expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
        metadata_json={"salt": salt, "issued_at": now.isoformat()},
    )
    session.add(ch)
    session.flush()
    intent = otp_outbox.enqueue(
        session,
        ch,
        destination_ct=destination_ct if destination_ct is not None else encrypt(destination),
        code=code,
        purpose=purpose,
    )
    return ch, intent


def verify(
    session: Session,
    registration_id: uuid.UUID,
    code: str,
    now: datetime,
    *,
    purpose: str = "signup",
    challenge_id: uuid.UUID | None = None,
    commit_on_success: bool = True,
) -> OtpChallenge:
    now = _as_utc(now)
    registration = session.get(StudentRegistration, registration_id)
    if registration is None or registration.dob_hash_state != "verified":
        # Match the pre-existing unknown/no-challenge shape so quarantine does
        # not create a registration-existence oracle.
        raise OtpError(404, "no_active_challenge")
    ch = _active(
        session,
        registration_id,
        purpose,
        challenge_id=challenge_id,
        for_update=True,
    )
    if ch is None:
        raise OtpError(404, "no_active_challenge")
    if ch.locked_until is not None and _as_utc(ch.locked_until) > now:
        raise OtpError(423, "locked")
    if _as_utc(ch.expires_at) <= now:
        raise OtpError(410, "expired")
    salt = (ch.metadata_json or {}).get("salt", "")
    if otp_verifier(code, salt=salt) == ch.verifier_hash:
        ch.consumed_at = now
        if registration.status == "otp_pending" and purpose == "signup":
            registration.status = "otp_verified"
        if commit_on_success:
            session.commit()
        return ch
    # Persist the failed attempt / lockout ATOMICALLY before signalling the
    # error — the HTTP layer returns an error status and its request-scoped
    # session would otherwise roll this back (critical #1).
    ch.attempts += 1
    if ch.attempts >= ch.max_attempts:
        ch.locked_until = now + timedelta(seconds=LOCKOUT_SECONDS)
        session.commit()
        raise OtpError(423, "locked", attempts_left=0)
    session.commit()
    raise OtpError(401, "incorrect_otp", attempts_left=ch.max_attempts - ch.attempts)


def within_cooldown(session: Session, registration_id: uuid.UUID, now: datetime, purpose: str = "signup") -> bool:
    """True if the most recent challenge of ``purpose`` is still within cooldown."""
    now = _as_utc(now)
    last = session.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.registration_id == registration_id, OtpChallenge.purpose == purpose)
        .order_by(OtpChallenge.expires_at.desc())
    )
    if last is None:
        return False
    issued = (last.metadata_json or {}).get("issued_at")
    if not issued:
        return False
    elapsed = (now - _as_utc(datetime.fromisoformat(issued))).total_seconds()
    return elapsed < RESEND_COOLDOWN_SECONDS


def resend(
    session: Session,
    registration_id: uuid.UUID,
    now: datetime,
    *,
    purpose: str = "signup",
    destination: str,
    destination_ct: str | None = None,
) -> tuple[OtpChallenge, otp_outbox.DeliveryIntent]:
    registration = session.get(StudentRegistration, registration_id)
    if registration is None or registration.dob_hash_state != "verified":
        raise OtpError(404, "no_active_challenge")
    if within_cooldown(session, registration_id, now, purpose):
        raise OtpError(429, "resend_cooldown")
    return issue_challenge(
        session, registration_id, now, purpose=purpose, destination=destination, destination_ct=destination_ct
    )
