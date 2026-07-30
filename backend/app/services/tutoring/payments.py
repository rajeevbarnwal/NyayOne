"""Payments: order creation, webhook application, refunds (SAATHI-123/127 P2).

Frozen decisions implemented here
---------------------------------
* **INR integer paise only.** No floats anywhere in this module.
* **Only a signature-VERIFIED provider event converts a hold into a session.**
  :func:`handle_event` verifies the signature FIRST and refuses to touch the
  database on failure, so a forged webhook can never book a slot.
* **Payment failure or expiry RELEASES the slot** (via ``booking.release_hold``).
* **Replay protection** is the ``payment_events.provider_event_id`` UNIQUE
  constraint plus an explicit pre-check: an already-applied event raises
  ``DUPLICATE_EVENT`` and produces no second side effect.
* **Refund policy** (:func:`assess_refund`):
  ``>=settings.refund_free_cancel_hours`` (24) before start -> full refund;
  ``<24h`` -> NO automatic refund unless an authorised admin grants an audited
  exception; a TUTOR cancellation -> full refund regardless of the window.
* **A refund can never exceed the captured amount**, counting refunds already
  pending/processing/succeeded, and at most ONE succeeded refund may exist per
  order (``payment_refunds.succeeded_order_id`` marker + UNIQUE).

Card-data rules: nothing in this module accepts a PAN, a CVV or a payment OTP.
Only the provider's token id crosses the boundary, and only issuer display
crumbs (brand / last four / expiry) are persisted, because those are the only
columns ``payment_orders`` has.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.wave2 import (
    REFUND_REASONS,
    PaymentEvent,
    PaymentOrder,
    PaymentRefund,
)
from app.services.audit_service import record_audit_event
from app.services.providers.payment_provider import (
    EVENT_EXPIRED,
    EVENT_FAILED,
    EVENT_PAID,
    EVENT_PENDING,
    PaymentEventData,
    PaymentProvider,
    PaymentProviderError,
    build_payment_provider,
)
from app.services.tutoring import booking, outbox_relay
from app.services.tutoring.errors import (
    AdminExceptionUnauthorised,
    AmountMismatch,
    DuplicateEvent,
    Forbidden,
    NotFound,
    PaymentUnverified,
    ProviderUnavailable,
    RefundDuplicate,
    RefundNotAllowed,
    ValidationError,
)
from app.services.tutoring.outbox_relay import OutboxIntent

#: Refund amounts that already count against the captured total.
_LIVE_REFUND_STATUSES = ("pending", "processing", "succeeded")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def assert_paise(amount_paise: int, *, field_name: str = "amount_paise") -> int:
    """INR integer paise, non-negative. Rejects bool/float/Decimal outright."""
    if isinstance(amount_paise, bool) or not isinstance(amount_paise, int):
        raise ValidationError("amount must be integer paise", field=field_name)
    if amount_paise < 0:
        raise ValidationError("amount must not be negative", field=field_name)
    return amount_paise


def _resolve_provider(provider: PaymentProvider | None) -> PaymentProvider:
    """Fail closed: an unconfigured provider is PROVIDER_UNAVAILABLE, never a guess."""
    resolved = provider or build_payment_provider()
    if resolved is None:
        raise ProviderUnavailable(
            "payment provider is not configured", retryable=False
        )
    return resolved


# --------------------------------------------------------------------------- #
# Refund policy calculator
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RefundAssessment:
    """The policy decision for one cancellation. Amount is integer paise."""

    decision: str  # full_refund | no_auto_refund | admin_exception
    amount_paise: int
    reason: str | None  # a REFUND_REASONS value, or None when nothing is due
    hours_before_start: Decimal
    policy_window_hours: int

    @property
    def refund_due(self) -> bool:
        return self.decision != "no_auto_refund" and self.amount_paise > 0

    def as_dict(self) -> dict:
        return {
            "decision": self.decision,
            "amount_paise": self.amount_paise,
            "reason": self.reason,
            "hours_before_start": str(self.hours_before_start),
            "policy_window_hours": self.policy_window_hours,
        }


def hours_before(start_utc: datetime, now: datetime) -> Decimal:
    """Whole-and-fractional hours from ``now`` to ``start_utc``, never negative."""
    start_utc = _aware(start_utc)
    delta = (start_utc - now).total_seconds() / 3600.0
    if delta < 0:
        delta = 0.0
    # Numeric(8,2) on session_cancellations: quantise to 2dp deterministically.
    return Decimal(f"{delta:.2f}")


def assess_refund(
    *,
    captured_paise: int,
    hours_before_start: Decimal | float,
    cancelled_by_role: str,
    admin_exception: bool = False,
    admin_actor_id: uuid.UUID | None = None,
    exception_amount_paise: int | None = None,
    window_hours: int | None = None,
) -> RefundAssessment:
    """Pure policy function. No DB, no provider — trivially table-testable.

    Precedence (frozen): tutor cancellation > admin exception > 24h window.
    A tutor cancellation is always a full refund; an admin exception is the ONLY
    way money moves inside the window and it MUST name the admin; otherwise the
    window decides. The result can never exceed ``captured_paise``.
    """
    captured = assert_paise(captured_paise, field_name="captured_paise")
    window = int(
        window_hours
        if window_hours is not None
        else getattr(settings, "refund_free_cancel_hours", 24)
    )
    hrs = (
        hours_before_start
        if isinstance(hours_before_start, Decimal)
        else Decimal(f"{float(hours_before_start):.2f}")
    )
    if cancelled_by_role == "tutor":
        return RefundAssessment(
            decision="full_refund",
            amount_paise=captured,
            reason="tutor_cancelled",
            hours_before_start=hrs,
            policy_window_hours=window,
        )
    if admin_exception:
        if admin_actor_id is None:
            raise AdminExceptionUnauthorised(
                "an admin refund exception must name the authorising admin",
                field="admin_actor_id",
            )
        amount = captured if exception_amount_paise is None else assert_paise(
            exception_amount_paise, field_name="exception_amount_paise"
        )
        if amount > captured:
            raise AmountMismatch(
                "refund may not exceed the captured amount",
                captured_paise=captured,
                requested_paise=amount,
            )
        return RefundAssessment(
            decision="admin_exception",
            amount_paise=amount,
            reason="admin_exception",
            hours_before_start=hrs,
            policy_window_hours=window,
        )
    if hrs >= window:
        return RefundAssessment(
            decision="full_refund",
            amount_paise=captured,
            reason="cancel_ge_24h",
            hours_before_start=hrs,
            policy_window_hours=window,
        )
    return RefundAssessment(
        decision="no_auto_refund",
        amount_paise=0,
        reason=None,
        hours_before_start=hrs,
        policy_window_hours=window,
    )


# --------------------------------------------------------------------------- #
# Order creation
# --------------------------------------------------------------------------- #


@dataclass
class OrderCreated:
    """Result of :func:`create_order`: the order plus after-commit intents.

    ``intents`` is intentionally empty in the normal path: ``OUTBOX_KINDS`` has
    no value for "a payment was merely initiated", and notifying a student before
    money moves would be wrong. The field exists so every mutating service in
    this package returns the SAME shape — the caller always commits and then
    hands ``intents`` to ``outbox_relay.run_delivery``.
    """

    order: PaymentOrder
    intents: list[OutboxIntent] = field(default_factory=list)
    replayed: bool = False


def create_order(
    session: Session,
    *,
    hold_id: uuid.UUID,
    student_user_id: uuid.UUID,
    amount_paise: int,
    idempotency_key: str,
    currency: str = "INR",
    provider: PaymentProvider | None = None,
    now: datetime | None = None,
) -> OrderCreated:
    """Create a payment order against a LIVE hold. Does not commit.

    The hold's TTL is enforced here (the DB cannot): paying against an expired
    hold raises ``HOLD_EXPIRED`` rather than silently reviving a released slot.
    """
    now = now or utcnow()
    assert_paise(amount_paise)
    if currency != "INR":
        raise ValidationError("only INR is supported", field="currency")
    key = (idempotency_key or "").strip()
    if not key or len(key) > 200:
        raise ValidationError(
            "idempotency_key must be 1..200 chars", field="idempotency_key"
        )

    existing = session.scalars(
        select(PaymentOrder).where(PaymentOrder.idempotency_key == key)
    ).first()
    if existing is not None:
        if (
            existing.hold_id != hold_id
            or existing.student_user_id != student_user_id
            or existing.amount_paise != amount_paise
        ):
            raise ValidationError(
                "idempotency key already used for a different order",
                field="idempotency_key",
                order_id=str(existing.id),
            )
        return OrderCreated(order=existing, replayed=True)

    hold = booking.get_hold(
        session, hold_id, student_user_id=student_user_id, now=now, require_live=True
    )
    resolved = _resolve_provider(provider)
    try:
        provider_order = resolved.create_order(
            amount_paise=amount_paise,
            currency=currency,
            idempotency_key=key,
            # Receipt reference: opaque ids only, never a student name.
            reference=f"ls-hold-{hold.id}",
        )
    except PaymentProviderError as exc:
        raise ProviderUnavailable(
            f"payment provider rejected the order ({exc.code})",
            retryable=exc.retryable,
            provider_code=exc.code,
        ) from exc

    order = PaymentOrder(
        hold_id=hold.id,
        student_user_id=student_user_id,
        provider=resolved.name,
        provider_order_ref=provider_order.provider_order_ref,
        amount_paise=amount_paise,
        currency=currency,
        status="created",
        idempotency_key=key,
    )
    session.add(order)
    session.flush()
    booking._booking_event(
        session,
        kind="payment_initiated",
        actor_role="student",
        hold_id=hold.id,
        payload={
            "order_id": str(order.id),
            "amount_paise": amount_paise,
            "currency": currency,
            "provider": resolved.name,
        },
        now=now,
    )
    record_audit_event(
        session,
        action="tutoring.payment.order_created",
        resource_type="payment_order",
        resource_id=order.id,
        actor_user_id=student_user_id,
        actor_role="student",
        after_state={
            "hold_id": str(hold.id),
            "amount_paise": amount_paise,
            "currency": currency,
            "provider": resolved.name,
            "status": "created",
        },
    )
    session.flush()
    return OrderCreated(order=order)


def order_for_hold(
    session: Session,
    hold_id: uuid.UUID,
    *,
    student_user_id: uuid.UUID | None = None,
) -> PaymentOrder:
    """The order that governs a hold: the CAPTURED one if one exists.

    A student may legitimately open more than one order against a hold (an
    abandoned attempt then a successful one), so "which order does this hold
    belong to" is a policy question and therefore lives here rather than in the
    API layer. ``paid`` wins; otherwise the newest attempt is returned.

    Owner scoping is non-enumerating: another student's order is reported as
    ``NOT_FOUND``, never ``FORBIDDEN``.
    """
    rows = list(
        session.scalars(
            select(PaymentOrder)
            .where(PaymentOrder.hold_id == hold_id)
            # Total order so "the newest attempt" is reproducible.
            .order_by(PaymentOrder.created_at.desc(), PaymentOrder.id.desc())
        ).all()
    )
    if student_user_id is not None:
        rows = [row for row in rows if row.student_user_id == student_user_id]
    if not rows:
        raise NotFound("payment order not found", resource="payment_order")
    for row in rows:
        if row.status == "paid":
            return row
    return rows[0]


# --------------------------------------------------------------------------- #
# Webhook application
# --------------------------------------------------------------------------- #


@dataclass
class PaymentEventOutcome:
    """What applying one verified provider event did."""

    order: PaymentOrder
    event: PaymentEvent
    event_type: str
    tutoring_session: object | None = None
    slot_released: bool = False
    intents: list[OutboxIntent] = field(default_factory=list)
    #: True when a VERIFIED event was recorded but deliberately NOT applied
    #: because it was superseded by a capture that already landed (see the
    #: out-of-order guard in :func:`handle_event`).
    out_of_order: bool = False


def handle_event(
    session: Session,
    *,
    signature: str,
    raw_body: bytes,
    provider: PaymentProvider | None = None,
    expected_student_user_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> PaymentEventOutcome:
    """Verify, de-duplicate and APPLY one provider payment event.

    Order of operations is the security contract:

    1. resolve the provider (fail closed),
    2. **verify the signature** — on failure raise ``PAYMENT_UNVERIFIED`` having
       touched NOTHING in the database,
    3. resolve the order by ``(provider, provider_order_ref)``,
    4. reject an already-recorded ``provider_event_id`` (``DUPLICATE_EVENT``) —
       no second side effect, ever,
    5. assert order/user/amount/currency agreement,
    6. record the ledger row, then apply the state change.

    Step 6's ledger row is inserted BEFORE the amount assertion so a caller that
    chooses to commit on rejection keeps the forensic trail; a caller that rolls
    back loses it and will reject an identical retry identically.
    """
    now = now or utcnow()
    resolved = _resolve_provider(provider)

    # 2. signature FIRST.
    try:
        data: PaymentEventData = resolved.verify_event(signature, raw_body)
    except PaymentProviderError as exc:
        if exc.retryable:
            raise ProviderUnavailable(
                f"payment provider could not verify the event ({exc.code})",
                retryable=True,
                provider_code=exc.code,
            ) from exc
        raise PaymentUnverified(
            "payment event signature verification failed", provider_code=exc.code
        ) from exc
    if not data.signature_verified:  # pragma: no cover - adapters raise instead
        raise PaymentUnverified("payment event was not verified")

    # 3. order match.
    order = session.scalars(
        select(PaymentOrder).where(
            PaymentOrder.provider == data.provider,
            PaymentOrder.provider_order_ref == data.provider_order_ref,
        )
    ).first()
    if order is None:
        raise NotFound("payment order not found", resource="payment_order")

    # 4. replay protection.
    duplicate = session.scalars(
        select(PaymentEvent).where(
            PaymentEvent.provider_event_id == data.provider_event_id
        )
    ).first()
    if duplicate is not None:
        raise DuplicateEvent(
            "provider event has already been applied",
            provider_event_id=data.provider_event_id,
            order_id=str(order.id),
        )

    # 5. user match.
    if (
        expected_student_user_id is not None
        and order.student_user_id != expected_student_user_id
    ):
        raise Forbidden("payment event does not belong to this user")

    # 6. ledger row, then assertions, then apply.
    event = PaymentEvent(
        order_id=order.id,
        provider_event_id=data.provider_event_id,
        event_type=data.event_type,
        signature_verified=True,
        payload_digest=data.payload_digest,
        received_at=now,
    )
    session.add(event)
    try:
        session.flush()
    except IntegrityError as exc:  # concurrent duplicate delivery
        session.rollback()
        raise DuplicateEvent(
            "provider event has already been applied",
            provider_event_id=data.provider_event_id,
        ) from exc

    if data.currency != order.currency:
        raise AmountMismatch(
            "event currency does not match the order",
            expected=order.currency,
            observed=data.currency,
        )
    if data.event_type in (EVENT_PAID, EVENT_PENDING) and (
        data.amount_paise != order.amount_paise
    ):
        raise AmountMismatch(
            "event amount does not match the order",
            expected_paise=order.amount_paise,
            observed_paise=data.amount_paise,
        )

    # Issuer display crumbs only (brand / last four / expiry) — never card data.
    if data.brand:
        order.brand = str(data.brand)[:24]
    if data.masked_last4:
        order.masked_last4 = str(data.masked_last4)[-4:]
    if data.expiry_month:
        order.expiry_month = int(data.expiry_month)
    if data.expiry_year:
        order.expiry_year = int(data.expiry_year)

    outcome = PaymentEventOutcome(order=order, event=event, event_type=data.event_type)

    # 6a. OUT-OF-ORDER DELIVERY GUARD (matrix C2).
    #
    # Providers do not guarantee ordering, so a 'failed' / 'expired' / 'pending'
    # event can arrive AFTER the capture that superseded it. Without this guard
    # the branches below would set a CAPTURED order's status to failed/expired/
    # pending and, for failed/expired, attempt to release a hold that already
    # backs a confirmed session — leaving the payment ledger contradicting a
    # live booking and emitting a 'payment_failed' audit trail for money we
    # actually took. The verified event is still recorded (the ledger row above
    # is already flushed, so the same delivery can never be applied twice) and
    # NOTHING else changes.
    if order.status == "paid" and data.event_type != EVENT_PAID:
        outcome.out_of_order = True
        record_audit_event(
            session,
            action="tutoring.payment.event_out_of_order",
            resource_type="payment_order",
            resource_id=order.id,
            actor_role="system",
            after_state={
                "status": order.status,
                "ignored_event_type": data.event_type,
                "provider_event_id": data.provider_event_id,
                "applied": False,
            },
        )
        session.flush()
        return outcome

    if data.event_type == EVENT_PAID:
        # Local import: sessions imports payments for the refund path.
        from app.services.tutoring import sessions as sessions_service

        order.status = "paid"
        hold = session.get(booking.BookingHold, order.hold_id)
        if hold is None:  # pragma: no cover - FK RESTRICT prevents this
            raise NotFound("hold not found", resource="booking_hold")
        created = sessions_service.create_from_paid_hold(
            session, hold=hold, order=order, now=now
        )
        outcome.tutoring_session = created.tutoring_session
        outcome.intents.extend(created.intents)
        booking._booking_event(
            session,
            kind="payment_succeeded",
            actor_role="system",
            hold_id=hold.id,
            session_id=created.tutoring_session.id,
            payload={"order_id": str(order.id), "amount_paise": order.amount_paise},
            now=now,
        )
        outcome.intents.append(
            outbox_relay.enqueue(
                session,
                kind="payment_captured",
                aggregate_id=order.id,
                payload={
                    "order_id": str(order.id),
                    "session_id": str(created.tutoring_session.id),
                    "amount_paise": order.amount_paise,
                    "currency": order.currency,
                },
            )
        )
        record_audit_event(
            session,
            action="tutoring.payment.captured",
            resource_type="payment_order",
            resource_id=order.id,
            actor_role="system",
            before_state={"status": "created"},
            after_state={
                "status": "paid",
                "session_id": str(created.tutoring_session.id),
                "amount_paise": order.amount_paise,
                "provider_event_id": data.provider_event_id,
            },
        )
    elif data.event_type in (EVENT_FAILED, EVENT_EXPIRED):
        order.status = "failed" if data.event_type == EVENT_FAILED else "expired"
        booking.release_hold(
            session,
            order.hold_id,
            reason=f"payment_{data.event_type}",
            actor_role="system",
            now=now,
        )
        outcome.slot_released = True
        booking._booking_event(
            session,
            kind="payment_failed",
            actor_role="system",
            hold_id=order.hold_id,
            payload={"order_id": str(order.id), "outcome": data.event_type},
            now=now,
        )
        record_audit_event(
            session,
            action=f"tutoring.payment.{data.event_type}",
            resource_type="payment_order",
            resource_id=order.id,
            actor_role="system",
            after_state={
                "status": order.status,
                "slot_released": True,
                "provider_event_id": data.provider_event_id,
            },
        )
    else:  # EVENT_PENDING — record it, change nothing else.
        order.status = "pending"
        record_audit_event(
            session,
            action="tutoring.payment.pending",
            resource_type="payment_order",
            resource_id=order.id,
            actor_role="system",
            after_state={
                "status": "pending",
                "provider_event_id": data.provider_event_id,
            },
        )
    session.flush()
    return outcome


# --------------------------------------------------------------------------- #
# Refunds
# --------------------------------------------------------------------------- #


def refunded_paise(session: Session, order_id: uuid.UUID) -> int:
    """Sum of refunds already pending/processing/succeeded for an order."""
    total = session.scalar(
        select(sa.func.coalesce(sa.func.sum(PaymentRefund.amount_paise), 0)).where(
            PaymentRefund.order_id == order_id,
            PaymentRefund.status.in_(_LIVE_REFUND_STATUSES),
        )
    )
    return int(total or 0)


@dataclass
class RefundIssued:
    refund: PaymentRefund
    intents: list[OutboxIntent] = field(default_factory=list)
    pending_retry: bool = False


def refund(
    session: Session,
    *,
    order_id: uuid.UUID,
    amount_paise: int,
    reason: str,
    actor_role: str = "system",
    actor_user_id: uuid.UUID | None = None,
    provider: PaymentProvider | None = None,
    now: datetime | None = None,
    allow_pending_on_provider_failure: bool = False,
) -> RefundIssued:
    """Issue a refund with duplicate / over-amount guards. Does not commit.

    Guards, in order:

    * the order must actually be ``paid`` (nothing to refund otherwise),
    * ``reason`` must be a ``REFUND_REASONS`` value,
    * the amount must be positive and, added to refunds already live, must not
      exceed the captured amount (``AMOUNT_MISMATCH``),
    * an existing succeeded refund for the order is ``REFUND_DUPLICATE``; the
      ``succeeded_order_id`` UNIQUE marker enforces the same thing at the DB
      level, and its ``IntegrityError`` is translated to the same typed error.

    The provider is called BEFORE any row is written, so a provider failure
    leaves no phantom reservation. With
    ``allow_pending_on_provider_failure=True`` (used by the cancellation path) a
    retryable provider failure instead persists a ``pending`` refund plus a
    ``refund_issued`` outbox row so the durable relay can finish the job.
    """
    now = now or utcnow()
    assert_paise(amount_paise)
    if reason not in REFUND_REASONS:
        raise ValidationError(f"unknown refund reason: {reason}", field="reason")
    order = session.get(PaymentOrder, order_id)
    if order is None:
        raise NotFound("payment order not found", resource="payment_order")
    if order.status != "paid":
        raise RefundNotAllowed(
            "only a paid order can be refunded", status=order.status
        )
    if amount_paise == 0:
        raise ValidationError("refund amount must be positive", field="amount_paise")

    already_succeeded = session.scalars(
        select(PaymentRefund).where(
            PaymentRefund.order_id == order_id, PaymentRefund.status == "succeeded"
        )
    ).first()
    if already_succeeded is not None:
        raise RefundDuplicate(
            "this order has already been refunded",
            refund_id=str(already_succeeded.id),
            amount_paise=already_succeeded.amount_paise,
        )
    already = refunded_paise(session, order_id)
    if already + amount_paise > order.amount_paise:
        raise AmountMismatch(
            "refund would exceed the captured amount",
            captured_paise=order.amount_paise,
            already_refunded_paise=already,
            requested_paise=amount_paise,
        )

    resolved = _resolve_provider(provider)
    idempotency_key = f"rfnd-{order_id}-{amount_paise}-{reason}"
    provider_ref: str | None = None
    status = "succeeded"
    pending_retry = False
    try:
        result = resolved.refund(
            provider_order_ref=order.provider_order_ref or "",
            amount_paise=amount_paise,
            idempotency_key=idempotency_key,
            reason=reason,
        )
        provider_ref = result.provider_refund_ref
        status = "succeeded" if result.status == "succeeded" else "pending"
    except PaymentProviderError as exc:
        if not (allow_pending_on_provider_failure and exc.retryable):
            raise ProviderUnavailable(
                f"refund provider call failed ({exc.code})",
                retryable=exc.retryable,
                provider_code=exc.code,
            ) from exc
        status = "pending"
        pending_retry = True

    row = PaymentRefund(
        order_id=order_id,
        amount_paise=amount_paise,
        reason=reason,
        status=status,
        provider_refund_ref=provider_ref,
        succeeded_order_id=(order_id if status == "succeeded" else None),
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise RefundDuplicate(
            "this order has already been refunded", order_id=str(order_id)
        ) from exc

    intents = [
        outbox_relay.enqueue(
            session,
            kind="refund_issued",
            aggregate_id=order_id,
            payload={
                "order_id": str(order_id),
                "refund_id": str(row.id),
                "amount_paise": amount_paise,
                "reason": reason,
                "status": status,
                "retry_pending": pending_retry,
            },
        )
    ]
    booking._booking_event(
        session,
        kind="refund_succeeded" if status == "succeeded" else "refund_requested",
        actor_role=actor_role if actor_role in ("student", "tutor", "admin") else "system",
        hold_id=order.hold_id,
        payload={
            "order_id": str(order_id),
            "refund_id": str(row.id),
            "amount_paise": amount_paise,
            "reason": reason,
        },
        now=now,
    )
    record_audit_event(
        session,
        action="tutoring.refund.issued",
        resource_type="payment_refund",
        resource_id=row.id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        after_state={
            "order_id": str(order_id),
            "amount_paise": amount_paise,
            "reason": reason,
            "status": status,
            "captured_paise": order.amount_paise,
        },
    )
    session.flush()
    return RefundIssued(refund=row, intents=intents, pending_retry=pending_retry)
