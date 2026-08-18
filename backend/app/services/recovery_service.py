"""Account-recovery lifecycle (SAATHI-448 Workstream B2-B5).

Anti-enumeration by construction:
- EVERY ``start`` — known or unknown mobile — persists a RecoverySession with a
  fresh opaque id (never the registration UUID) and returns an identical shape.
- No synchronous provider call is on the response path: delivery is deferred to
  the outbox after commit and is fire-and-forget, so a provider outage cannot
  produce a different status for known vs unknown.
- ``verify`` / ``complete`` return a UNIFORM failure for unknown, decoy, expired,
  consumed or wrong-code sessions, so an attacker cannot distinguish them.

A recovery challenge uses ``purpose="recovery"`` so it never supersedes or is
superseded by the active signup challenge.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, keyed_hash
from app.models.registration import OtpChallenge, RecoverySession, StudentRegistration
from app.services import otp_outbox, otp_service

RECOVERY_TTL_SECONDS = 600
RECOVERY_COOLDOWN_SECONDS = 30


class RecoveryError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def start(session: Session, mobile: str, now: datetime) -> tuple[str, otp_outbox.DeliveryIntent | None]:
    """Begin recovery. Returns (opaque_id, delivery_intent_or_None).

    Always persists a session and returns a fresh opaque id. Only a known mobile
    outside the cooldown produces a real challenge + delivery intent.
    """
    now = _as_utc(now)
    opaque_id = uuid.uuid4().hex
    lookup_hash = keyed_hash(mobile)
    reg = session.scalar(
        select(StudentRegistration).where(
            StudentRegistration.mobile_hash == lookup_hash,
            StudentRegistration.dob_hash_state == "verified",
        )
    )
    rs = RecoverySession(
        opaque_id=opaque_id,
        lookup_hash=lookup_hash,
        registration_id=reg.id if reg is not None else None,
        status="pending",
        expires_at=now + timedelta(seconds=RECOVERY_TTL_SECONDS),
    )
    session.add(rs)
    session.flush()

    intent: otp_outbox.DeliveryIntent | None = None
    if reg is not None and not _recent_recovery_excluding(
        session, lookup_hash, rs.id, now
    ):
        ch, intent = otp_service.issue_challenge(
            session, reg.id, now, purpose="recovery", destination=decrypt(reg.mobile_ct)
        )
        rs.challenge_id = ch.id
    return opaque_id, intent


def _recent_recovery_excluding(
    session: Session,
    lookup_hash: str,
    exclude_id: uuid.UUID,
    now: datetime,
) -> bool:
    now = _as_utc(now)
    last = session.scalar(
        select(RecoverySession)
        .where(
            RecoverySession.lookup_hash == lookup_hash,
            RecoverySession.id != exclude_id,
        )
        .order_by(RecoverySession.created_at.desc())
    )
    if last is None:
        return False
    return (now - _as_utc(last.created_at)).total_seconds() < RECOVERY_COOLDOWN_SECONDS


def _load_usable(session: Session, opaque_id: str, now: datetime) -> RecoverySession:
    """Load a session that is real (not decoy), unexpired and unconsumed, else a
    uniform failure. Never accepts a registration UUID (looks up opaque_id only)."""
    now = _as_utc(now)
    rs = session.scalar(select(RecoverySession).where(RecoverySession.opaque_id == opaque_id))
    if rs is None or rs.registration_id is None or rs.challenge_id is None:
        raise RecoveryError(401, "recovery_failed")
    registration = session.get(StudentRegistration, rs.registration_id)
    if registration is None or registration.dob_hash_state != "verified":
        raise RecoveryError(401, "recovery_failed")
    if rs.status == "consumed" or rs.consumed_at is not None:
        raise RecoveryError(401, "recovery_failed")
    if _as_utc(rs.expires_at) <= now:
        rs.status = "expired"
        session.commit()
        raise RecoveryError(401, "recovery_failed")
    return rs


def verify(session: Session, opaque_id: str, code: str, now: datetime) -> None:
    """Verify a recovery OTP. Uniform failure for unknown/decoy/expired/wrong."""
    now = _as_utc(now)
    rs = _load_usable(session, opaque_id, now)
    try:
        otp_service.verify(session, rs.registration_id, code, now, purpose="recovery")
    except otp_service.OtpError as exc:
        # Uniform response — do not leak whether the session/mobile was real.
        raise RecoveryError(401, "recovery_failed") from exc
    rs.status = "verified"
    session.commit()


def complete(session: Session, opaque_id: str, now: datetime) -> None:
    """Consume a verified recovery session (where a real reset would occur)."""
    now = _as_utc(now)
    rs = session.scalar(select(RecoverySession).where(RecoverySession.opaque_id == opaque_id))
    if rs is None or rs.registration_id is None or rs.status != "verified":
        raise RecoveryError(401, "recovery_failed")
    registration = session.get(StudentRegistration, rs.registration_id)
    if registration is None or registration.dob_hash_state != "verified":
        raise RecoveryError(401, "recovery_failed")
    rs.status = "consumed"
    rs.consumed_at = now
    session.commit()
