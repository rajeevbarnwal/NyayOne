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
from app.models.registration import (
    OtpChallenge,
    OtpFlow,
    RecoverySession,
    StudentRegistration,
)
from app.services import (
    otp_authority,
    otp_flow_service,
    otp_outbox,
    otp_service,
)

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
            StudentRegistration.mobile_hash == lookup_hash
        )
    )
    if not otp_service.registration_is_authorizable(reg):
        reg = None
    if reg is not None:
        # The stable parent lock must cover the recent-request decision, not
        # merely the later child insert, to prevent duplicate deliveries.
        reg = otp_service.lock_registration_for_update(session, reg.id)
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
        try:
            ch, intent = otp_service.issue_challenge(
                session,
                reg.id,
                now,
                purpose="recovery",
                destination=decrypt(reg.mobile_ct),
            )
        except otp_service.OtpError as exc:
            if exc.code != "otp_issue_conflict":
                raise
            # Keep the known-mobile path indistinguishable from a decoy/cooldown
            # request while retaining the outer RecoverySession transaction.
            intent = None
        else:
            rs.challenge_id = ch.id
    return opaque_id, intent


def start_flow(
    session: Session,
    mobile: str,
    now: datetime,
) -> tuple[str, OtpFlow, otp_outbox.DeliveryIntent | None]:
    """Create a cookie-owned real or decoy recovery flow."""

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
    eligible = bool(
        registration is not None
        and otp_service.registration_is_authorizable(registration)
        and registration.status in {"otp_verified", "active"}
    )
    if not eligible:
        subject = otp_authority.authority_subject_from_mobile_hash(
            keyed_hash(f"nyayone:otp-recovery-decoy:v1:{mobile}")
        )
    authority = otp_authority.lock_or_create_authority(
        session,
        subject_hash=subject,
        purpose="recovery",
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
            purpose="recovery",
            destination=decrypt(registration.mobile_ct),
        )
        if authority.generation == generation:
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
        challenge=active or candidate,
        registration_id=(registration.id if eligible and registration else None),
    )
    return raw_token, flow, intent


def verify_flow(
    session: Session,
    raw_flow_token: str | None,
    code: str,
    now: datetime,
) -> OtpFlow:
    now = _as_utc(now)
    graph = otp_flow_service.resolve_flow(session, raw_flow_token)
    if graph is None:
        raise RecoveryError(401, "recovery_failed")
    authority, flow = graph
    if (
        flow.purpose != "recovery"
        or flow.state not in {"pending", "code_sent", "locked"}
        or _as_utc(flow.expires_at) <= now
    ):
        raise RecoveryError(401, "recovery_failed")
    if flow.registration_id is None or flow.challenge_id is None:
        try:
            otp_service.record_failed_attempt(session, authority, now=now)
        except otp_service.OtpError as exc:
            raise RecoveryError(401, "recovery_failed") from exc
        raise RecoveryError(401, "recovery_failed")
    try:
        otp_service.verify(
            session,
            flow.registration_id,
            code,
            now,
            purpose="recovery",
            challenge_id=flow.challenge_id,
            commit_on_success=False,
        )
    except otp_service.OtpError as exc:
        if exc.code not in {"incorrect_otp", "locked"}:
            try:
                otp_service.record_failed_attempt(
                    session, authority, now=now
                )
            except otp_service.OtpError as uniform_exc:
                raise RecoveryError(401, "recovery_failed") from uniform_exc
        raise RecoveryError(401, "recovery_failed") from exc
    otp_flow_service.mark_recovery_verified(flow, now=now)
    session.commit()
    return flow


def complete_flow(
    session: Session,
    raw_flow_token: str | None,
    now: datetime,
) -> None:
    graph = otp_flow_service.resolve_flow(session, raw_flow_token)
    if graph is None:
        raise RecoveryError(401, "recovery_failed")
    _, flow = graph
    if flow.registration_id is None:
        raise RecoveryError(401, "recovery_failed")
    try:
        otp_flow_service.consume_recovery_proof(
            session,
            raw_flow_token,
            registration_id=flow.registration_id,
            now=now,
        )
    except ValueError as exc:
        raise RecoveryError(401, "recovery_failed") from exc
    session.commit()


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
    registration = otp_service.lock_registration_for_update(
        session, rs.registration_id
    )
    if registration is None:
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
    registration = otp_service.lock_registration_for_update(
        session, rs.registration_id
    )
    if registration is None:
        raise RecoveryError(401, "recovery_failed")
    rs.status = "consumed"
    rs.consumed_at = now
    session.commit()
