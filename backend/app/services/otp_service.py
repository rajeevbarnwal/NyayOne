"""Server-authoritative OTP lifecycle (SAATHI-448 Workstream B).

issue / verify / resend(cooldown) / lockout / recovery. Only a keyed verifier is
persisted — the raw code is passed to an injectable sender and never stored,
returned or logged. All time comparisons use timezone-aware values supplied by
the caller (deterministic + testable).
"""
from __future__ import annotations

import secrets
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import keyed_hash, otp_verifier
from app.models.registration import OtpChallenge, StudentRegistration

OTP_TTL_SECONDS = 300
RESEND_COOLDOWN_SECONDS = 30
LOCKOUT_SECONDS = 900
MAX_ATTEMPTS = 3

Sender = Callable[[str], None]


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


def _active(session: Session, registration_id: uuid.UUID) -> OtpChallenge | None:
    return session.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.registration_id == registration_id, OtpChallenge.consumed_at.is_(None))
        .order_by(OtpChallenge.expires_at.desc())
    )


def issue_challenge(
    session: Session, registration_id: uuid.UUID, now: datetime, send: Sender | None = None
) -> OtpChallenge:
    now = now.astimezone(timezone.utc)
    # Supersede any prior un-consumed challenge so only one is ever active.
    for prior in session.scalars(
        select(OtpChallenge).where(
            OtpChallenge.registration_id == registration_id, OtpChallenge.consumed_at.is_(None)
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
        verifier_hash=otp_verifier(code, salt=salt),
        attempts=0,
        max_attempts=MAX_ATTEMPTS,
        expires_at=now + timedelta(seconds=OTP_TTL_SECONDS),
        metadata_json={"salt": salt, "issued_at": now.isoformat()},
    )
    session.add(ch)
    session.flush()
    if send is not None:
        send(code)  # e.g. SMS provider; raw code leaves only via the sender
    del code
    return ch


def verify(session: Session, registration_id: uuid.UUID, code: str, now: datetime) -> OtpChallenge:
    now = _as_utc(now)
    ch = _active(session, registration_id)
    if ch is None:
        raise OtpError(404, "no_active_challenge")
    if ch.locked_until is not None and _as_utc(ch.locked_until) > now:
        raise OtpError(423, "locked")
    if _as_utc(ch.expires_at) <= now:
        raise OtpError(410, "expired")
    salt = (ch.metadata_json or {}).get("salt", "")
    if otp_verifier(code, salt=salt) == ch.verifier_hash:
        ch.consumed_at = now
        reg = session.get(StudentRegistration, registration_id)
        if reg is not None and reg.status == "otp_pending":
            reg.status = "otp_verified"
        return ch
    ch.attempts += 1
    if ch.attempts >= ch.max_attempts:
        ch.locked_until = now + timedelta(seconds=LOCKOUT_SECONDS)
        raise OtpError(423, "locked", attempts_left=0)
    raise OtpError(401, "incorrect_otp", attempts_left=ch.max_attempts - ch.attempts)


def resend(
    session: Session, registration_id: uuid.UUID, now: datetime, send: Sender | None = None
) -> OtpChallenge:
    now = _as_utc(now)
    last = session.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.registration_id == registration_id)
        .order_by(OtpChallenge.expires_at.desc())
    )
    if last is not None:
        issued = (last.metadata_json or {}).get("issued_at")
        if issued:
            elapsed = (now - _as_utc(datetime.fromisoformat(issued))).total_seconds()
            if elapsed < RESEND_COOLDOWN_SECONDS:
                raise OtpError(429, "resend_cooldown")
    return issue_challenge(session, registration_id, now, send)


def start_recovery(session: Session, mobile: str, now: datetime, send: Sender | None = None) -> str:
    """Anti-enumeration: always return an opaque recovery id; only issue a real
    challenge when the mobile maps to an existing registration."""
    reg = session.scalar(
        select(StudentRegistration).where(StudentRegistration.mobile_hash == keyed_hash(mobile))
    )
    if reg is not None:
        issue_challenge(session, reg.id, now, send)
        return str(reg.id)
    return str(uuid.uuid4())  # opaque, no existence leak
