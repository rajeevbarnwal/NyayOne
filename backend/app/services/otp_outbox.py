"""Leased, fenced and provider-idempotent OTP transactional outbox (NYAY-4).

Invariant: an OTP is NEVER handed to a provider before the registration/challenge
transaction commits. The service writes an ``otp_outbox`` row (status=pending)
with a short-lived encrypted payload in the SAME transaction as the challenge
and returns an opaque ``DeliveryIntent``. The endpoint commits, then calls
``run_delivery``:

- commit fails  → the outbox row is never persisted and ``run_delivery`` is never
  reached → zero delivery, zero rows.
- commit succeeds → exactly one ``sender.send`` is attempted; the outbox row is
  marked ``sent`` (or ``failed`` with a non-PII error) in its own transaction.

The raw code and plaintext destination are never persisted or logged. Both are
stored only as version-stamped ciphertext until the row is delivered, at which
point the OTP ciphertext is erased. This permits a committed pending row to be
relayed after a process crash without persisting a plaintext OTP.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import active_key_version, decrypt, encrypt, keyed_hash
from app.models.registration import (
    OtpChallenge,
    OtpFlow,
    OtpOutbox,
    OtpPurposeAuthority,
)
from app.services.otp_sender import IdempotentOtpSender, OtpSendError

_PROVIDER_KEY_DOMAIN = b"nyayone:otp-provider-idempotency:v1"


@dataclass
class DeliveryIntent:
    """Opaque reference to a persisted delivery instruction."""

    outbox_id: uuid.UUID


@dataclass(frozen=True)
class _DeliveryClaim:
    outbox_id: uuid.UUID
    challenge_id: uuid.UUID
    token_hash: str
    provider_key: str
    destination: str
    code: str


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def provider_idempotency_key(outbox_id: uuid.UUID) -> str:
    """Deterministic 64-hex token stable across every lease and retry."""

    return hmac.new(
        _PROVIDER_KEY_DOMAIN,
        str(outbox_id).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _claim_hash(token: str) -> str:
    return keyed_hash(f"otp-outbox-claim:v1:{token}")


def _receipt_hash(receipt: str) -> str:
    return keyed_hash(f"otp-provider-receipt:v1:{receipt}")


def enqueue(
    session: Session,
    challenge: OtpChallenge,
    *,
    destination_ct: str,
    code: str,
    purpose: str,
) -> DeliveryIntent:
    """Write the pending outbox row in the challenge's transaction; return intent."""
    row_id = uuid.uuid4()
    row = OtpOutbox(
        id=row_id,
        challenge_id=challenge.id,
        destination_ct=destination_ct,
        code_ct=encrypt(code),
        key_version=active_key_version(),
        purpose=purpose,
        status="pending",
        attempts=0,
        max_attempts=settings.otp_outbox_max_attempts,
        provider_idempotency_key=provider_idempotency_key(row_id),
        claim_token_hash=None,
        claimed_at=None,
        lease_expires_at=None,
        next_attempt_at=None,
        provider_receipt_hash=None,
        provider_receipt_key_version=None,
        legacy_destination_retained=False,
    )
    session.add(row)
    session.flush()
    return DeliveryIntent(outbox_id=row.id)


def _graph_ids(
    session: Session, outbox_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID] | None:
    challenge_id = session.scalar(
        select(OtpOutbox.challenge_id).where(OtpOutbox.id == outbox_id)
    )
    if challenge_id is None:
        return None
    authority_id = session.scalar(
        select(OtpChallenge.authority_id).where(OtpChallenge.id == challenge_id)
    )
    if authority_id is None:
        return None
    return challenge_id, authority_id


def _locked_graph(
    session: Session, outbox_id: uuid.UUID
) -> tuple[OtpPurposeAuthority, OtpChallenge, OtpOutbox] | None:
    ids = _graph_ids(session, outbox_id)
    if ids is None:
        return None
    challenge_id, authority_id = ids
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
    row = session.scalar(
        select(OtpOutbox)
        .where(OtpOutbox.id == outbox_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        authority is None
        or challenge is None
        or row is None
        or challenge.authority_id != authority.id
        or row.challenge_id != challenge.id
        or challenge.registration_id != authority.registration_id
        or challenge.purpose != authority.purpose
        or row.purpose != authority.purpose
    ):
        return None
    return authority, challenge, row


def _clear_claim(row: OtpOutbox) -> None:
    row.claim_token_hash = None
    row.claimed_at = None
    row.lease_expires_at = None


def _erase_payload(row: OtpOutbox) -> None:
    row.code_ct = None
    row.destination_ct = None
    row.legacy_destination_retained = False


def _void(
    authority: OtpPurposeAuthority,
    challenge: OtpChallenge,
    row: OtpOutbox,
    *,
    now: datetime,
    reason: str,
) -> None:
    row.status = "void"
    row.last_error = reason
    row.next_attempt_at = None
    _clear_claim(row)
    _erase_payload(row)
    was_active = challenge.delivery_state == "active"
    if challenge.delivery_state in {"active", "pending_delivery"}:
        challenge.delivery_state = "void"
        challenge.consumed_at = challenge.consumed_at or now
    if was_active:
        authority.active_expires_at = None


def _reconcile_voided_candidate(
    session: Session,
    authority: OtpPurposeAuthority,
    candidate: OtpChallenge,
) -> None:
    """Keep an old delivered verifier authoritative after candidate failure."""

    prior = session.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.authority_id == authority.id,
            OtpChallenge.delivery_state == "active",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    for flow in session.scalars(
        select(OtpFlow)
        .where(
            OtpFlow.authority_id == authority.id,
            OtpFlow.registration_id == authority.registration_id,
            OtpFlow.state.in_(("pending", "code_sent", "locked")),
        )
        .with_for_update()
    ):
        if prior is None:
            # Keep the real flow externally indistinguishable from a decoy
            # until its common public TTL. The exhausted candidate is no
            # longer verifiable, but the cookie may stage a fresh candidate
            # through the normal cooldown/resend authority using the same
            # registration/idempotency graph.
            flow.state = "pending"
            flow.challenge_id = None
            flow.consumed_at = None
        else:
            flow.challenge_id = prior.id
            flow.state = "code_sent"


def _claim(
    session: Session,
    intent: DeliveryIntent,
    *,
    now: datetime,
    commit: bool,
) -> _DeliveryClaim | bool:
    graph = _locked_graph(session, intent.outbox_id)
    if graph is None:
        return False
    authority, challenge, row = graph
    if row.status == "sent":
        return True
    if row.status == "void":
        return False
    if (
        row.status == "claimed"
        and row.lease_expires_at is not None
        and _as_utc(row.lease_expires_at) > now
    ):
        return False
    if (
        row.status == "failed"
        and row.next_attempt_at is not None
        and _as_utc(row.next_attempt_at) > now
    ):
        return False
    if row.attempts >= row.max_attempts:
        was_candidate = challenge.delivery_state == "pending_delivery"
        _void(
            authority,
            challenge,
            row,
            now=now,
            reason="provider_attempts_exhausted",
        )
        if was_candidate:
            _reconcile_voided_candidate(session, authority, challenge)
        if commit:
            session.commit()
        else:
            session.flush()
        return False
    if (
        challenge.delivery_state not in {"active", "pending_delivery"}
        or _as_utc(challenge.expires_at) <= now
    ):
        was_candidate = challenge.delivery_state == "pending_delivery"
        _void(
            authority,
            challenge,
            row,
            now=now,
            reason=(
                "challenge_expired"
                if _as_utc(challenge.expires_at) <= now
                else "challenge_inactive"
            ),
        )
        if was_candidate:
            _reconcile_voided_candidate(session, authority, challenge)
        if commit:
            session.commit()
        else:
            session.flush()
        return False
    if (
        not row.code_ct
        or not row.destination_ct
        or len(row.provider_idempotency_key) != 64
    ):
        was_candidate = challenge.delivery_state == "pending_delivery"
        _void(
            authority,
            challenge,
            row,
            now=now,
            reason="delivery_payload_invalid",
        )
        if was_candidate:
            _reconcile_voided_candidate(session, authority, challenge)
        if commit:
            session.commit()
        else:
            session.flush()
        return False

    token = secrets.token_urlsafe(32)
    token_hash = _claim_hash(token)
    destination = decrypt(row.destination_ct)
    code = decrypt(row.code_ct)
    row.status = "claimed"
    row.claim_token_hash = token_hash
    row.claimed_at = now
    row.lease_expires_at = now + timedelta(seconds=settings.otp_outbox_lease_seconds)
    row.next_attempt_at = None
    row.attempts += 1
    if commit:
        session.commit()
    else:
        session.flush()
    return _DeliveryClaim(
        outbox_id=row.id,
        challenge_id=challenge.id,
        token_hash=token_hash,
        provider_key=row.provider_idempotency_key,
        destination=destination,
        code=code,
    )


def _provider_send(
    sender: IdempotentOtpSender, claim: _DeliveryClaim
) -> str | None:
    method = getattr(sender, "send_idempotent", None)
    if not callable(method):
        raise OtpSendError("OTP provider lacks the idempotency contract")
    receipt = method(
        claim.destination,
        claim.code,
        idempotency_token=claim.provider_key,
    )
    if receipt is not None and (
        not isinstance(receipt, str)
        or not receipt
        or len(receipt) > 512
        or any(ord(character) < 0x20 for character in receipt)
    ):
        raise OtpSendError("OTP provider returned an invalid receipt")
    return receipt


def _activate_candidate(
    session: Session,
    authority: OtpPurposeAuthority,
    candidate: OtpChallenge,
    now: datetime,
) -> None:
    if candidate.delivery_state != "pending_delivery":
        return
    prior = session.scalar(
        select(OtpChallenge)
        .where(
            OtpChallenge.authority_id == authority.id,
            OtpChallenge.delivery_state == "active",
            OtpChallenge.id != candidate.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if prior is not None:
        prior.delivery_state = "superseded"
        prior.consumed_at = now
        meta = dict(prior.metadata_json or {})
        meta["superseded"] = True
        prior.metadata_json = meta
        session.flush()
    candidate.delivery_state = "active"
    candidate.consumed_at = None
    # Verification lifetime starts only after provider acceptance.  The
    # staging expiry remains a finite relay deadline while the payload waits.
    candidate.expires_at = now + timedelta(
        seconds=settings.otp_challenge_ttl_seconds
    )
    candidate.attempts = authority.failed_attempts
    candidate.max_attempts = authority.max_attempts
    candidate.locked_until = authority.locked_until
    authority.active_expires_at = candidate.expires_at


def _finalize_success(
    session: Session,
    claim: _DeliveryClaim,
    *,
    receipt: str | None,
    now: datetime,
    commit: bool,
) -> bool:
    graph = _locked_graph(session, claim.outbox_id)
    if graph is None:
        return False
    authority, challenge, row = graph
    if (
        row.status != "claimed"
        or row.claim_token_hash is None
        or not hmac.compare_digest(row.claim_token_hash, claim.token_hash)
    ):
        return row.status == "sent"
    _activate_candidate(session, authority, challenge, now)
    row.status = "sent"
    row.last_error = None
    row.delivered_at = now
    row.next_attempt_at = None
    row.provider_receipt_hash = _receipt_hash(receipt) if receipt else None
    row.provider_receipt_key_version = "v1" if receipt else None
    _clear_claim(row)
    _erase_payload(row)
    for flow in session.scalars(
        select(OtpFlow)
        .where(
            OtpFlow.authority_id == authority.id,
            OtpFlow.registration_id == authority.registration_id,
            OtpFlow.state.in_(("pending", "code_sent", "locked")),
        )
        .with_for_update()
    ):
        flow.challenge_id = challenge.id
        flow.state = "code_sent"
    if commit:
        session.commit()
    else:
        session.flush()
    return True


def _finalize_failure(
    session: Session,
    claim: _DeliveryClaim,
    *,
    now: datetime,
    commit: bool,
) -> None:
    graph = _locked_graph(session, claim.outbox_id)
    if graph is None:
        return
    authority, challenge, row = graph
    if (
        row.status != "claimed"
        or row.claim_token_hash is None
        or not hmac.compare_digest(row.claim_token_hash, claim.token_hash)
    ):
        return
    _clear_claim(row)
    if row.attempts >= row.max_attempts:
        was_candidate = challenge.delivery_state == "pending_delivery"
        _void(
            authority,
            challenge,
            row,
            now=now,
            reason="provider_attempts_exhausted",
        )
        if was_candidate:
            _reconcile_voided_candidate(session, authority, challenge)
    else:
        delay = min(
            settings.otp_outbox_retry_max_seconds,
            settings.otp_outbox_retry_base_seconds
            * (
                2
                ** min(
                    max(0, row.attempts - 1),
                    settings.otp_outbox_max_attempts - 1,
                )
            ),
        )
        row.status = "failed"
        row.last_error = "provider_send_failed"
        row.next_attempt_at = now + timedelta(seconds=delay)
    if commit:
        session.commit()
    else:
        session.flush()


def run_delivery(
    session: Session,
    intent: DeliveryIntent,
    sender: IdempotentOtpSender,
    *,
    raise_on_failure: bool,
    commit: bool = True,
    now: datetime | None = None,
) -> bool:
    """Claim, idempotently deliver, and fenced-finalize one intent.

    ``now`` is an explicit deterministic clock override for the whole
    operation.  Production callers omit it, in which case finalization captures
    a fresh wall-clock time after provider I/O so delivery timestamps and retry
    backoff never inherit a stale claim-start instant.
    """

    if not commit:
        raise RuntimeError(
            "OTP provider I/O requires a committed durable lease"
        )
    clock_override = _as_utc(now) if now is not None else None
    claim_now = clock_override or datetime.now(timezone.utc)
    claimed = _claim(session, intent, now=claim_now, commit=True)
    if claimed is True:
        # Terminal observation is success for idempotent reconciliation, but it
        # is not a newly delivered message and must not inflate relay counts.
        return False
    if claimed is False:
        if raise_on_failure:
            raise OtpSendError("otp delivery intent unavailable")
        return False
    try:
        receipt = _provider_send(sender, claimed)
    except OtpSendError:
        finalized_at = clock_override or datetime.now(timezone.utc)
        _finalize_failure(
            session,
            claimed,
            now=_as_utc(finalized_at),
            commit=True,
        )
        if raise_on_failure:
            raise
        return False
    finalized_at = clock_override or datetime.now(timezone.utc)
    return _finalize_success(
        session,
        claimed,
        receipt=receipt,
        now=finalized_at,
        commit=True,
    )


def purge_legacy_destinations(
    session: Session,
    *,
    now: datetime,
    retention_seconds: int,
) -> int:
    """Explicitly erase grandfathered terminal destination ciphertext."""

    if retention_seconds <= 0:
        raise ValueError("OTP outbox destination retention must be positive")
    cutoff = _as_utc(now) - timedelta(seconds=retention_seconds)
    rows = list(
        session.scalars(
            select(OtpOutbox)
            .where(
                OtpOutbox.legacy_destination_retained.is_(True),
                OtpOutbox.status.in_(("sent", "void")),
                OtpOutbox.updated_at < cutoff,
            )
            .with_for_update()
        )
    )
    for row in rows:
        row.destination_ct = None
        row.legacy_destination_retained = False
    session.flush()
    return len(rows)


def fence_expired_flow_deliveries(
    session: Session,
    authority: OtpPurposeAuthority,
    *,
    now: datetime,
) -> None:
    """Make every verifier/relay candidate for one expired flow unusable.

    The caller owns the authority lock. Challenges and outboxes are then locked
    in canonical order. A stale provider completion cannot activate a candidate
    because its claim hash/status are cleared before the maintenance commit.
    """

    now = _as_utc(now)
    challenges = list(
        session.scalars(
            select(OtpChallenge)
            .where(
                OtpChallenge.authority_id == authority.id,
                OtpChallenge.delivery_state.in_(("active", "pending_delivery")),
            )
            .order_by(OtpChallenge.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for challenge in challenges:
        outboxes = list(
            session.scalars(
                select(OtpOutbox)
                .where(OtpOutbox.challenge_id == challenge.id)
                .order_by(OtpOutbox.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if challenge.delivery_state == "pending_delivery":
            for row in outboxes:
                if row.status in {"pending", "claimed", "failed"}:
                    _void(
                        authority,
                        challenge,
                        row,
                        now=now,
                        reason="otp_flow_expired",
                    )
            if challenge.delivery_state == "pending_delivery":
                challenge.delivery_state = "void"
                challenge.consumed_at = challenge.consumed_at or now
        else:
            challenge.delivery_state = "void"
            challenge.consumed_at = now
            authority.active_expires_at = None
    session.flush()
