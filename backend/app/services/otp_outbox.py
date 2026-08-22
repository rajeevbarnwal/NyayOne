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
from typing import TypeVar

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


@dataclass(frozen=True)
class _LockedDeliveryGraph:
    authority: OtpPurposeAuthority
    flows: tuple[OtpFlow, ...]
    challenge: OtpChallenge
    row: OtpOutbox


@dataclass(frozen=True)
class _UnavailableDelivery:
    reason: str


class OtpFlowUnavailable(OtpSendError):
    """A delivery lost its live browser capability before activation."""

    def __init__(self, reason: str) -> None:
        super().__init__("otp delivery flow unavailable")
        self.reason = reason


_CURRENT_FLOW_STATES = ("pending", "code_sent", "verified", "locked")
_DELIVERY_FLOW_STATES = ("pending", "code_sent", "locked")
_FLOW_UNAVAILABLE_REASONS = frozenset(
    {
        "otp_flow_ambiguous",
        "otp_flow_expired",
        "otp_flow_missing",
        "otp_flow_unavailable",
    }
)
_EarlyResult = TypeVar("_EarlyResult")


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
) -> _LockedDeliveryGraph | None:
    """Lock one relay graph in authority -> flow -> challenge -> outbox order."""

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
    if authority is None:
        return None
    flows = tuple(
        session.scalars(
            select(OtpFlow)
            .where(OtpFlow.authority_id == authority_id)
            .order_by(OtpFlow.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    challenges = tuple(
        session.scalars(
            select(OtpChallenge)
            .where(
                OtpChallenge.authority_id == authority_id,
                (
                    (OtpChallenge.id == challenge_id)
                    | OtpChallenge.delivery_state.in_(
                        ("active", "pending_delivery")
                    )
                ),
            )
            .order_by(OtpChallenge.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    challenge = next(
        (candidate for candidate in challenges if candidate.id == challenge_id),
        None,
    )
    challenge_ids = tuple(candidate.id for candidate in challenges)
    outboxes = tuple(
        session.scalars(
            select(OtpOutbox)
            .where(OtpOutbox.challenge_id.in_(challenge_ids))
            .order_by(OtpOutbox.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ) if challenge_ids else ()
    row = next(
        (candidate for candidate in outboxes if candidate.id == outbox_id),
        None,
    )
    if (
        challenge is None
        or row is None
        or challenge.authority_id != authority.id
        or row.challenge_id != challenge.id
        or challenge.registration_id != authority.registration_id
        or challenge.purpose != authority.purpose
        or row.purpose != authority.purpose
    ):
        return None
    return _LockedDeliveryGraph(
        authority=authority,
        flows=flows,
        challenge=challenge,
        row=row,
    )


def _authorized_delivery_flow(
    graph: _LockedDeliveryGraph,
    *,
    now: datetime,
) -> tuple[OtpFlow | None, str | None]:
    current = tuple(
        flow for flow in graph.flows if flow.state in _CURRENT_FLOW_STATES
    )
    if not current:
        if any(flow.state == "expired" for flow in graph.flows):
            return None, "otp_flow_expired"
        return None, "otp_flow_missing"
    if len(current) != 1:
        return None, "otp_flow_ambiguous"
    flow = current[0]
    if (
        flow.authority_id != graph.authority.id
        or flow.subject_hash != graph.authority.subject_hash
        or flow.registration_id != graph.authority.registration_id
        or flow.registration_id != graph.challenge.registration_id
        or flow.purpose != graph.authority.purpose
        or flow.purpose != graph.challenge.purpose
    ):
        return None, "otp_flow_ambiguous"
    if flow.state not in _DELIVERY_FLOW_STATES:
        return None, "otp_flow_unavailable"
    if _as_utc(flow.expires_at) <= now:
        return None, "otp_flow_expired"
    return flow, None


def _flow_unavailability_reason(
    graph: _LockedDeliveryGraph,
    *,
    now: datetime,
) -> str | None:
    return _authorized_delivery_flow(graph, now=now)[1]


def _expire_current_flows(
    graph: _LockedDeliveryGraph,
    *,
    now: datetime,
) -> None:
    for flow in graph.flows:
        # A delayed resend callback can observe that the original verifier won
        # while provider I/O was in flight.  ``verified`` is then an independent
        # recovery proof, not delivery authority for this stale candidate.  Fence
        # only states that can still authorize delivery; never revoke that proof.
        if flow.state not in _DELIVERY_FLOW_STATES:
            continue
        flow.state = "expired"
        flow.consumed_at = now
        flow.destination_masked_ct = None
        flow.key_version = None


def _fence_unavailable_delivery(
    session: Session,
    graph: _LockedDeliveryGraph,
    *,
    now: datetime,
    reason: str,
) -> None:
    """Erase every relay/verifier under an unavailable browser capability."""

    target_was_relayable = graph.row.status in {"pending", "claimed", "failed"}
    _expire_current_flows(graph, now=now)
    fence_expired_flow_deliveries(session, graph.authority, now=now)
    # The broad fence only discovers active/pending challenges. A relayable
    # target can have become inactive in a competing lifecycle transaction, so
    # explicitly clear its payload, claim, and retry deadline as well. Sent
    # history remains terminal and untouched.
    if target_was_relayable:
        _void(
            graph.authority,
            graph.challenge,
            graph.row,
            now=now,
            reason=reason,
        )
    session.flush()


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


def _finish_early_delivery(
    session: Session,
    result: _EarlyResult,
    *,
    commit: bool,
    mutated: bool = False,
) -> _EarlyResult:
    """Release an owned transaction, or preserve caller-owned transaction mode."""

    if commit:
        session.commit()
    elif mutated:
        session.flush()
    return result


def _claim(
    session: Session,
    intent: DeliveryIntent,
    *,
    now: datetime | None,
    commit: bool,
) -> _DeliveryClaim | _UnavailableDelivery | bool:
    graph = _locked_graph(session, intent.outbox_id)
    if graph is None:
        return _finish_early_delivery(session, False, commit=commit)
    authority, challenge, row = (
        graph.authority,
        graph.challenge,
        graph.row,
    )
    if row.status == "sent":
        return _finish_early_delivery(session, True, commit=commit)
    if row.status == "void":
        result: _UnavailableDelivery | bool = False
        if row.last_error in _FLOW_UNAVAILABLE_REASONS:
            result = _UnavailableDelivery(row.last_error)
        return _finish_early_delivery(session, result, commit=commit)
    operation_now = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    unavailable_reason = _flow_unavailability_reason(
        graph,
        now=operation_now,
    )
    if unavailable_reason is not None:
        _fence_unavailable_delivery(
            session,
            graph,
            now=operation_now,
            reason=unavailable_reason,
        )
        return _finish_early_delivery(
            session,
            _UnavailableDelivery(unavailable_reason),
            commit=commit,
            mutated=True,
        )
    if (
        row.status == "claimed"
        and row.lease_expires_at is not None
        and _as_utc(row.lease_expires_at) > operation_now
    ):
        return _finish_early_delivery(session, False, commit=commit)
    if (
        row.status == "failed"
        and row.next_attempt_at is not None
        and _as_utc(row.next_attempt_at) > operation_now
    ):
        return _finish_early_delivery(session, False, commit=commit)
    if row.attempts >= row.max_attempts:
        was_candidate = challenge.delivery_state == "pending_delivery"
        _void(
            authority,
            challenge,
            row,
            now=operation_now,
            reason="provider_attempts_exhausted",
        )
        if was_candidate:
            _reconcile_voided_candidate(session, authority, challenge)
        return _finish_early_delivery(
            session,
            False,
            commit=commit,
            mutated=True,
        )
    if (
        challenge.delivery_state not in {"active", "pending_delivery"}
        or _as_utc(challenge.expires_at) <= operation_now
    ):
        was_candidate = challenge.delivery_state == "pending_delivery"
        _void(
            authority,
            challenge,
            row,
            now=operation_now,
            reason=(
                "challenge_expired"
                if _as_utc(challenge.expires_at) <= operation_now
                else "challenge_inactive"
            ),
        )
        if was_candidate:
            _reconcile_voided_candidate(session, authority, challenge)
        return _finish_early_delivery(
            session,
            False,
            commit=commit,
            mutated=True,
        )
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
            now=operation_now,
            reason="delivery_payload_invalid",
        )
        if was_candidate:
            _reconcile_voided_candidate(session, authority, challenge)
        return _finish_early_delivery(
            session,
            False,
            commit=commit,
            mutated=True,
        )

    token = secrets.token_urlsafe(32)
    token_hash = _claim_hash(token)
    destination = decrypt(row.destination_ct)
    code = decrypt(row.code_ct)
    row.status = "claimed"
    row.claim_token_hash = token_hash
    row.claimed_at = operation_now
    row.lease_expires_at = operation_now + timedelta(
        seconds=settings.otp_outbox_lease_seconds
    )
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
    authorized_flow: OtpFlow,
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
    # Provider acceptance can start a fresh challenge lifetime, but it cannot
    # extend the exact browser capability that authorized this delivery.
    candidate.expires_at = min(
        now + timedelta(seconds=settings.otp_challenge_ttl_seconds),
        _as_utc(authorized_flow.expires_at),
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
    now: datetime | None,
    commit: bool,
) -> _UnavailableDelivery | bool:
    graph = _locked_graph(session, claim.outbox_id)
    if graph is None:
        return _finish_early_delivery(session, False, commit=commit)
    authority, challenge, row = (
        graph.authority,
        graph.challenge,
        graph.row,
    )
    if (
        row.status != "claimed"
        or row.claim_token_hash is None
        or not hmac.compare_digest(row.claim_token_hash, claim.token_hash)
    ):
        return _finish_early_delivery(
            session,
            False,
            commit=commit,
        )
    operation_now = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    authorized_flow, unavailable_reason = _authorized_delivery_flow(
        graph,
        now=operation_now,
    )
    if unavailable_reason is not None:
        _fence_unavailable_delivery(
            session,
            graph,
            now=operation_now,
            reason=unavailable_reason,
        )
        return _finish_early_delivery(
            session,
            _UnavailableDelivery(unavailable_reason),
            commit=commit,
            mutated=True,
        )
    assert authorized_flow is not None
    _activate_candidate(
        session,
        authority,
        challenge,
        authorized_flow,
        operation_now,
    )
    row.status = "sent"
    row.last_error = None
    row.delivered_at = operation_now
    row.next_attempt_at = None
    row.provider_receipt_hash = _receipt_hash(receipt) if receipt else None
    row.provider_receipt_key_version = "v1" if receipt else None
    _clear_claim(row)
    _erase_payload(row)
    authorized_flow.challenge_id = challenge.id
    authorized_flow.state = "code_sent"
    if commit:
        session.commit()
    else:
        session.flush()
    return True


def _finalize_failure(
    session: Session,
    claim: _DeliveryClaim,
    *,
    now: datetime | None,
    commit: bool,
) -> _UnavailableDelivery | None:
    graph = _locked_graph(session, claim.outbox_id)
    if graph is None:
        return _finish_early_delivery(session, None, commit=commit)
    authority, challenge, row = (
        graph.authority,
        graph.challenge,
        graph.row,
    )
    if (
        row.status != "claimed"
        or row.claim_token_hash is None
        or not hmac.compare_digest(row.claim_token_hash, claim.token_hash)
    ):
        return _finish_early_delivery(session, None, commit=commit)
    operation_now = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    unavailable_reason = _flow_unavailability_reason(
        graph,
        now=operation_now,
    )
    if unavailable_reason is not None:
        _fence_unavailable_delivery(
            session,
            graph,
            now=operation_now,
            reason=unavailable_reason,
        )
        return _finish_early_delivery(
            session,
            _UnavailableDelivery(unavailable_reason),
            commit=commit,
            mutated=True,
        )
    _clear_claim(row)
    if row.attempts >= row.max_attempts:
        was_candidate = challenge.delivery_state == "pending_delivery"
        _void(
            authority,
            challenge,
            row,
            now=operation_now,
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
        row.next_attempt_at = operation_now + timedelta(seconds=delay)
    if commit:
        session.commit()
    else:
        session.flush()
    return None


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
    claimed = _claim(session, intent, now=clock_override, commit=True)
    if claimed is True:
        # Terminal observation is success for idempotent reconciliation, but it
        # is not a newly delivered message and must not inflate relay counts.
        return False
    if claimed is False:
        if raise_on_failure:
            raise OtpSendError("otp delivery intent unavailable")
        return False
    if isinstance(claimed, _UnavailableDelivery):
        if raise_on_failure:
            raise OtpFlowUnavailable(claimed.reason)
        return False
    try:
        receipt = _provider_send(sender, claimed)
    except OtpSendError as exc:
        failure = _finalize_failure(
            session,
            claimed,
            now=clock_override,
            commit=True,
        )
        if isinstance(failure, _UnavailableDelivery):
            if raise_on_failure:
                raise OtpFlowUnavailable(failure.reason) from exc
            return False
        if raise_on_failure:
            raise
        return False
    finalized = _finalize_success(
        session,
        claimed,
        receipt=receipt,
        now=clock_override,
        commit=True,
    )
    if isinstance(finalized, _UnavailableDelivery):
        if raise_on_failure:
            raise OtpFlowUnavailable(finalized.reason)
        return False
    return finalized


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
        for row in outboxes:
            if row.status in {"pending", "claimed", "failed"}:
                _void(
                    authority,
                    challenge,
                    row,
                    now=now,
                    reason="otp_flow_expired",
                )
        if challenge.delivery_state in {"active", "pending_delivery"}:
            challenge.delivery_state = "void"
            challenge.consumed_at = challenge.consumed_at or now
        authority.active_expires_at = None
    session.flush()
