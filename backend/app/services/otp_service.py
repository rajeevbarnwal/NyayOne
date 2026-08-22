"""Server-authoritative OTP lifecycle with stable purpose authority (NYAY-4)."""
from __future__ import annotations

import math
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import encrypt, otp_verifier
from app.models.registration import (
    OtpChallenge,
    OtpFlow,
    OtpOutbox,
    OtpPurposeAuthority,
)
from app.models.registration import StudentRegistration
from app.services import integrity_errors, otp_authority, otp_outbox
from app.services import registration_service

OTP_TTL_SECONDS = 300
RESEND_COOLDOWN_SECONDS = 30
LOCKOUT_SECONDS = 900
MAX_ATTEMPTS = 3
ACTIVE_OTP_CONSTRAINT = "uq_otp_challenges_one_active_per_registration_purpose"
PENDING_OTP_CONSTRAINT = "uq_otp_challenges_one_pending_delivery_per_authority"
_CURRENT_FLOW_STATES = ("pending", "code_sent", "verified", "locked")
_DELIVERY_FLOW_STATES = ("pending", "code_sent", "locked")


class OtpError(Exception):
    def __init__(self, status_code: int, code: str,
                 attempts_left: int | None = None, *,
                 retry_after_seconds: int | None = None) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.attempts_left = attempts_left
        self.retry_after_seconds = retry_after_seconds


def registration_is_authorizable(registration: StudentRegistration | None) -> bool:
    return bool(registration is not None and registration.deleted_at is None
                and registration.status != "deleted"
                and registration.dob_hash_state == "verified")


def registration_authority_filters() -> tuple[object, ...]:
    return (StudentRegistration.deleted_at.is_(None),
            StudentRegistration.status != "deleted",
            StudentRegistration.dob_hash_state == "verified")


def registration_accepts_otp_purpose(registration: StudentRegistration | None,
                                     purpose: str) -> bool:
    return bool(registration_is_authorizable(registration)
                and (purpose != "signup" or registration.status == "otp_pending"))


def _gen_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def lock_registration_for_update(session: Session, registration_id: uuid.UUID) -> StudentRegistration | None:
    registration, _ = registration_service.lock_registration_with_idempotency(session, registration_id)
    return registration if registration_is_authorizable(registration) else None


def authority_for_registration(session: Session, registration: StudentRegistration,
                               purpose: str, now: datetime) -> OtpPurposeAuthority:
    return otp_authority.lock_or_create_registration_authority(
        session, registration, purpose, _as_utc(now)
    )


def _active(session: Session, authority: OtpPurposeAuthority, *,
            challenge_id: uuid.UUID | None = None,
            for_update: bool = False) -> OtpChallenge | None:
    statement = select(OtpChallenge).where(
        OtpChallenge.authority_id == authority.id,
        OtpChallenge.delivery_state == "active",
        OtpChallenge.consumed_at.is_(None),
    )
    if challenge_id is not None:
        statement = statement.where(OtpChallenge.id == challenge_id)
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalar(statement)


def _pending(session: Session, authority: OtpPurposeAuthority,
             *, for_update: bool = False) -> OtpChallenge | None:
    statement = select(OtpChallenge).where(
        OtpChallenge.authority_id == authority.id,
        OtpChallenge.delivery_state == "pending_delivery",
    )
    if for_update:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return session.scalar(statement)


def active_challenges_for_replacement(session: Session, registration_id: uuid.UUID,
                                      purpose: str) -> list[OtpChallenge]:
    """Compatibility inspection seam; 0019 never replaces before delivery."""
    return list(session.scalars(select(OtpChallenge).where(
        OtpChallenge.registration_id == registration_id,
        OtpChallenge.purpose == purpose,
        OtpChallenge.delivery_state == "active",
        OtpChallenge.consumed_at.is_(None),
    ).with_for_update().execution_options(populate_existing=True)))


def _pending_intent(session: Session, authority: OtpPurposeAuthority
                    ) -> tuple[OtpChallenge, otp_outbox.DeliveryIntent] | None:
    candidate = _pending(session, authority, for_update=True)
    if candidate is None:
        return None
    row = session.scalar(select(OtpOutbox).where(
        OtpOutbox.challenge_id == candidate.id
    ).with_for_update().execution_options(populate_existing=True))
    if (row is None or row.purpose != authority.purpose
            or row.status not in {"pending", "claimed", "failed"}
            or row.code_ct is None or row.destination_ct is None):
        raise RuntimeError("OTP staged delivery graph is invalid")
    return candidate, otp_outbox.DeliveryIntent(outbox_id=row.id)


def _validate_signup_ledger_delivery(
    session: Session,
    registration: StudentRegistration,
    authority: OtpPurposeAuthority,
    idempotency_record,
) -> None:
    """Reject a cross-linked NYAY-17 outbox before any resend mutation."""

    if idempotency_record is None or idempotency_record.state != "pending":
        return
    if idempotency_record.outbox_id is None:
        raise RuntimeError("registration idempotency delivery graph is invalid")
    graph = session.execute(
        select(
            OtpOutbox.challenge_id,
            OtpOutbox.purpose,
            OtpChallenge.registration_id,
            OtpChallenge.authority_id,
            OtpChallenge.purpose,
        )
        .join(OtpChallenge, OtpChallenge.id == OtpOutbox.challenge_id)
        .where(OtpOutbox.id == idempotency_record.outbox_id)
    ).one_or_none()
    if graph is None:
        raise RuntimeError("registration idempotency delivery graph is invalid")
    (
        _,
        outbox_purpose,
        challenge_registration_id,
        challenge_authority_id,
        challenge_purpose,
    ) = graph
    if (
        challenge_registration_id != registration.id
        or challenge_authority_id != authority.id
        or outbox_purpose != "signup"
        or challenge_purpose != "signup"
    ):
        raise RuntimeError("registration idempotency delivery graph is invalid")


def _raise_if_locked(authority: OtpPurposeAuthority, now: datetime) -> None:
    seconds = otp_authority.locked_for_seconds(authority, now)
    if seconds:
        raise OtpError(423, "locked", 0, retry_after_seconds=seconds)


def _locked_resend_flow_deadline(
    session: Session,
    authority: OtpPurposeAuthority,
    registration: StudentRegistration,
    *,
    now: datetime,
) -> datetime:
    """Return the sole live browser-capability deadline for a resend.

    The authority row is already locked. Lock every flow for that authority
    before touching a pending challenge or outbox, then fail closed unless one
    delivery-capable flow has the exact authority/subject/registration/purpose
    graph. Candidate challenge IDs are deliberately not flow authority.
    """

    flows = tuple(
        session.scalars(
            select(OtpFlow)
            .where(OtpFlow.authority_id == authority.id)
            .order_by(OtpFlow.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    current = tuple(
        flow for flow in flows if flow.state in _CURRENT_FLOW_STATES
    )
    if len(current) != 1:
        raise OtpError(401, "otp_flow_unavailable")
    flow = current[0]
    deadline = _as_utc(flow.expires_at)
    if (
        flow.authority_id != authority.id
        or flow.subject_hash != authority.subject_hash
        or flow.registration_id != authority.registration_id
        or flow.registration_id != registration.id
        or flow.purpose != authority.purpose
        or flow.state not in _DELIVERY_FLOW_STATES
        or deadline <= now
    ):
        raise OtpError(401, "otp_flow_unavailable")
    return deadline


def issue_challenge(session: Session, registration_id: uuid.UUID, now: datetime, *,
                    purpose: str = "signup", destination: str,
                    destination_ct: str | None = None
                    ) -> tuple[OtpChallenge, otp_outbox.DeliveryIntent]:
    """Stage one candidate; activate it only after fenced provider success."""
    now = _as_utc(now)
    registration, idempotency_record = registration_service.lock_registration_with_idempotency(
        session, registration_id
    )
    if not registration_accepts_otp_purpose(registration, purpose):
        raise OtpError(404, "no_active_challenge")
    assert registration is not None
    authority = authority_for_registration(session, registration, purpose, now)
    _raise_if_locked(authority, now)
    if purpose == "signup":
        _validate_signup_ledger_delivery(
            session,
            registration,
            authority,
            idempotency_record,
        )
    existing = _pending_intent(session, authority)
    if existing is not None:
        return existing
    try:
        with session.begin_nested():
            code, salt = _gen_code(), str(uuid.uuid4())
            candidate = OtpChallenge(
                registration_id=registration_id, authority_id=authority.id,
                purpose=purpose, verifier_hash=otp_verifier(code, salt=salt),
                attempts=authority.failed_attempts, max_attempts=authority.max_attempts,
                expires_at=now + timedelta(seconds=settings.otp_challenge_ttl_seconds),
                consumed_at=now, locked_until=authority.locked_until,
                delivery_state="pending_delivery",
                metadata_json={"salt": salt, "issued_at": now.isoformat()},
            )
            session.add(candidate)
            session.flush()
            intent = otp_outbox.enqueue(
                session, candidate,
                destination_ct=destination_ct if destination_ct is not None else encrypt(destination),
                code=code, purpose=purpose,
            )
            authority.last_issued_at = now
            authority.cooldown_until = now + timedelta(seconds=settings.otp_resend_cooldown_seconds)
            authority.generation += 1
            authority.updated_at = now
            if (purpose == "signup" and idempotency_record is not None
                    and idempotency_record.state == "pending"):
                if idempotency_record.registration_id != registration_id:
                    raise RuntimeError("registration idempotency authority is ambiguous")
                idempotency_record.outbox_id = intent.outbox_id
                idempotency_record.updated_at = now
    except IntegrityError as exc:
        if integrity_errors.constraint_name(exc) in {ACTIVE_OTP_CONSTRAINT, PENDING_OTP_CONSTRAINT}:
            raise OtpError(409, "otp_issue_conflict") from exc
        raise
    return candidate, intent


def _void_relayable_payloads(session: Session, challenge: OtpChallenge) -> None:
    for row in session.scalars(select(OtpOutbox).where(
        OtpOutbox.challenge_id == challenge.id,
        OtpOutbox.status.in_(("pending", "claimed", "failed")),
    ).with_for_update()):
        row.status = "void"
        row.code_ct = row.destination_ct = None
        row.legacy_destination_retained = False
        row.claim_token_hash = row.claimed_at = row.lease_expires_at = None
        row.next_attempt_at = None
        row.last_error = "challenge_consumed"
        row.delivered_at = None


def verify(session: Session, registration_id: uuid.UUID, code: str, now: datetime, *,
           purpose: str = "signup", challenge_id: uuid.UUID | None = None,
           commit_on_success: bool = True) -> OtpChallenge:
    now = _as_utc(now)
    registration, idempotency_record = registration_service.lock_registration_with_idempotency(
        session, registration_id
    )
    if not registration_accepts_otp_purpose(registration, purpose):
        raise OtpError(404, "no_active_challenge")
    assert registration is not None
    authority = authority_for_registration(session, registration, purpose, now)
    _raise_if_locked(authority, now)
    challenge = _active(session, authority, challenge_id=challenge_id, for_update=True)
    if challenge is None:
        raise OtpError(404, "no_active_challenge")
    if _as_utc(challenge.expires_at) <= now:
        challenge.delivery_state, challenge.consumed_at = "void", now
        authority.active_expires_at = None
        session.commit()
        raise OtpError(410, "expired")
    salt = (challenge.metadata_json or {}).get("salt", "")
    if otp_verifier(code, salt=salt) == challenge.verifier_hash:
        challenge.delivery_state, challenge.consumed_at = "consumed", now
        challenge.attempts, challenge.locked_until = authority.failed_attempts, None
        authority.failed_attempts = 0
        authority.locked_until = authority.attempt_window_started_at = None
        authority.active_expires_at = None
        authority.updated_at = now
        _void_relayable_payloads(session, challenge)
        if registration.status == "otp_pending" and purpose == "signup":
            registration.status = "otp_verified"
            registration_service.terminalize_registration_idempotency(
                session, registration, state="retired", locked_record=idempotency_record
            )
        session.commit() if commit_on_success else session.flush()
        return challenge
    record_failed_attempt(session, authority, now=now, challenge=challenge)
    raise AssertionError("failed OTP attempt must raise")


def record_failed_attempt(
    session: Session,
    authority: OtpPurposeAuthority,
    *,
    now: datetime,
    challenge: OtpChallenge | None = None,
) -> None:
    """Consume the stable attempt authority for real and decoy flows alike."""

    now = _as_utc(now)
    _raise_if_locked(authority, now)
    started = authority.attempt_window_started_at
    if started is None or _as_utc(started) + timedelta(seconds=settings.otp_attempt_window_seconds) <= now:
        authority.failed_attempts = 0
        authority.attempt_window_started_at = now
        authority.max_attempts = settings.otp_max_attempts
    authority.failed_attempts += 1
    if challenge is not None:
        challenge.attempts = authority.failed_attempts
        challenge.max_attempts = authority.max_attempts
    authority.updated_at = now
    if authority.failed_attempts >= authority.max_attempts:
        authority.locked_until = now + timedelta(seconds=settings.otp_lockout_seconds)
        if challenge is not None:
            challenge.locked_until = authority.locked_until
        session.commit()
        raise OtpError(423, "locked", 0, retry_after_seconds=settings.otp_lockout_seconds)
    if challenge is not None:
        challenge.locked_until = None
    attempts_left = authority.max_attempts - authority.failed_attempts
    session.commit()
    raise OtpError(401, "incorrect_otp", attempts_left)


def within_cooldown(session: Session, registration_id: uuid.UUID, now: datetime,
                    purpose: str = "signup") -> bool:
    registration = session.get(StudentRegistration, registration_id)
    if not registration_is_authorizable(registration):
        return False
    authority = authority_for_registration(session, registration, purpose, now)  # type: ignore[arg-type]
    return bool(authority.cooldown_until is not None
                and _as_utc(authority.cooldown_until) > _as_utc(now))


def consume_resend_window(authority: OtpPurposeAuthority, now: datetime) -> None:
    now = _as_utc(now)
    started = authority.resend_window_started_at
    if started is None or _as_utc(started) + timedelta(seconds=settings.otp_resend_window_seconds) <= now:
        authority.resend_window_started_at = now
        authority.resend_count = 0
        authority.max_resends = settings.otp_max_resends_per_window
    if authority.resend_count >= authority.max_resends:
        end = _as_utc(authority.resend_window_started_at) + timedelta(seconds=settings.otp_resend_window_seconds)  # type: ignore[arg-type]
        raise OtpError(429, "resend_rate_limited",
                       retry_after_seconds=max(1, math.ceil((end - now).total_seconds())))
    authority.resend_count += 1
    authority.updated_at = now


def resend(session: Session, registration_id: uuid.UUID, now: datetime, *,
           purpose: str = "signup", destination: str,
           destination_ct: str | None = None
           ) -> tuple[OtpChallenge, otp_outbox.DeliveryIntent]:
    now = _as_utc(now)
    registration, idempotency_record = (
        registration_service.lock_registration_with_idempotency(
            session, registration_id
        )
    )
    if not registration_accepts_otp_purpose(registration, purpose):
        raise OtpError(404, "no_active_challenge")
    assert registration is not None
    authority = authority_for_registration(session, registration, purpose, now)  # type: ignore[arg-type]
    if purpose == "signup":
        _validate_signup_ledger_delivery(
            session,
            registration,
            authority,
            idempotency_record,
        )
    _raise_if_locked(authority, now)
    flow_deadline = _locked_resend_flow_deadline(
        session,
        authority,
        registration,
        now=now,
    )
    pending = _pending_intent(session, authority)
    if authority.cooldown_until is not None and _as_utc(authority.cooldown_until) > now:
        retry = max(1, math.ceil((_as_utc(authority.cooldown_until) - now).total_seconds()))
        raise OtpError(429, "resend_cooldown", retry_after_seconds=retry)
    consume_resend_window(authority, now)
    if pending is not None:
        candidate, intent = pending
        # An explicit retry retains the exact candidate/provider key but applies
        # the same resend authority as a decoy request. Refresh only its finite
        # relay deadline; the verifier TTL still begins on provider acceptance.
        note_decoy_issue(authority, now=now)
        candidate.expires_at = min(
            now + timedelta(seconds=settings.otp_challenge_ttl_seconds),
            flow_deadline,
        )
        return candidate, intent
    # ``issue_challenge`` re-enters the canonical registration/authority lock
    # seam with populate_existing=True. Persist the serialized resend-window
    # increment first so that refresh cannot restore the pre-increment bytes.
    session.flush()
    candidate, intent = issue_challenge(
        session,
        registration_id,
        now,
        purpose=purpose,
        destination=destination,
        destination_ct=destination_ct,
    )
    candidate.expires_at = min(
        now + timedelta(seconds=settings.otp_challenge_ttl_seconds),
        flow_deadline,
    )
    return candidate, intent


def note_decoy_issue(authority: OtpPurposeAuthority, *, now: datetime) -> None:
    now = _as_utc(now)
    _raise_if_locked(authority, now)
    authority.last_issued_at = now
    authority.cooldown_until = now + timedelta(seconds=settings.otp_resend_cooldown_seconds)
    authority.generation += 1
    authority.updated_at = now


def resend_decoy(authority: OtpPurposeAuthority, *, now: datetime) -> None:
    """Apply the exact lock/cooldown/resend authority to a decoy flow."""

    now = _as_utc(now)
    _raise_if_locked(authority, now)
    if authority.cooldown_until is not None and _as_utc(authority.cooldown_until) > now:
        retry = max(1, math.ceil((_as_utc(authority.cooldown_until) - now).total_seconds()))
        raise OtpError(429, "resend_cooldown", retry_after_seconds=retry)
    consume_resend_window(authority, now)
    note_decoy_issue(authority, now=now)
