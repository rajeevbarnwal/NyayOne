"""Slot holds: atomic allocation, TTL enforcement, sweeper (SAATHI-123/127 P2).

Frozen decisions implemented here
---------------------------------
* Hold TTL is ``settings.booking_hold_minutes`` (10). The DATABASE cannot expire
  a row on its own, so the SERVICE enforces the TTL on every read/transition and
  a sweeper (:func:`expire_holds`) releases abandoned slots.
* Slot allocation is ATOMIC: one winner, every competitor gets a typed
  ``HOLD_CONFLICT``, and a replay of the same idempotency key returns the SAME
  hold rather than a second one.

How "exactly one winner" is achieved (three layers, all portable)
----------------------------------------------------------------
1. **One conditional statement.** The hold is created by a single
   ``INSERT ... SELECT ... WHERE NOT EXISTS (an active hold marker for this slot)
   AND EXISTS (the slot is still 'available')`` — the guard is evaluated by the
   database inside the same statement, so no caller can act on a stale read.
   ``rowcount == 0`` means "someone else won" -> ``HoldConflict``.
2. **The schema's marker + UNIQUE.** The statement writes
   ``active_slot_id = slot_id``, which is covered by
   ``uq_booking_holds_active_slot_id`` (plus the partial unique index
   ``uq_booking_holds_one_active_per_slot``). Under a weaker isolation level
   where two inserts could both pass the guard, the second one is rejected by
   the constraint and the ``IntegrityError`` is translated to ``HoldConflict``.
3. **The slot transition is part of the same transaction.** The follow-up
   ``UPDATE ... SET status='held' WHERE id = :slot AND status='available'`` must
   affect exactly one row; if it does not, the whole transaction (hold row
   included) is abandoned with ``HoldConflict``. Hold row and slot status can
   never disagree.

Because layers 1 and 3 are conditional statements and layer 2 is a constraint,
the invariant holds on SQLite and PostgreSQL alike — no advisory locks, no
``SELECT ... FOR UPDATE`` requirement, no dialect-specific SQL.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.types import DateTime, String, Uuid

from app.core.config import settings
from app.models.wave2 import BookingEvent, BookingHold, TutorAvailabilitySlot
from app.services.audit_service import record_audit_event
from app.services.tutoring.errors import (
    HoldConflict,
    HoldExpired,
    IdempotencyKeyReuse,
    NotFound,
    SlotUnavailable,
    ValidationError,
)

_UUID = Uuid(as_uuid=True)
_TS = DateTime(timezone=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; normalise to UTC-aware."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def hold_ttl() -> timedelta:
    minutes = int(getattr(settings, "booking_hold_minutes", 10))
    if minutes <= 0:
        raise ValidationError("booking_hold_minutes must be positive", field="ttl")
    return timedelta(minutes=minutes)


def is_expired(hold: BookingHold, *, now: datetime | None = None) -> bool:
    """TTL check. The DB cannot do this, so every code path must ask."""
    now = now or utcnow()
    expires_at = _aware(hold.expires_at)
    return expires_at is not None and expires_at <= now


def _booking_event(
    session: Session,
    *,
    kind: str,
    actor_role: str,
    hold_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    payload: dict | None = None,
    now: datetime | None = None,
) -> BookingEvent:
    """Append a non-PII booking-trail row (ids and codes only)."""
    row = BookingEvent(
        session_id=session_id,
        hold_id=hold_id,
        kind=kind,
        actor_role=actor_role,
        at=now or utcnow(),
        payload_json=payload,
    )
    session.add(row)
    return row


# --------------------------------------------------------------------------- #
# TTL enforcement helpers
# --------------------------------------------------------------------------- #


def _expire_active_holds(
    session: Session,
    *,
    now: datetime,
    slot_id: uuid.UUID | None = None,
) -> list[BookingHold]:
    """Mark timed-out ACTIVE holds expired and clear their marker, atomically.

    One statement per batch: ``UPDATE ... SET status='expired',
    active_slot_id=NULL WHERE status='active' AND expires_at <= :now``. Clearing
    the marker is what frees the slot for the next holder (NULLs are distinct in
    the UNIQUE constraint), and the CHECK constraint keeps status/marker honest.
    """
    stmt = select(BookingHold).where(
        BookingHold.status == "active", BookingHold.expires_at <= now
    )
    if slot_id is not None:
        stmt = stmt.where(BookingHold.slot_id == slot_id)
    stale = list(session.scalars(stmt.order_by(BookingHold.expires_at, BookingHold.id)).all())
    if not stale:
        return []
    ids = [row.id for row in stale]
    session.execute(
        sa.update(BookingHold)
        .where(BookingHold.id.in_(ids), BookingHold.status == "active")
        .values(status="expired", active_slot_id=None, updated_at=now)
    )
    # Release each slot that is still parked on the dead hold.
    session.execute(
        sa.update(TutorAvailabilitySlot)
        .where(
            TutorAvailabilitySlot.id.in_([row.slot_id for row in stale]),
            TutorAvailabilitySlot.status == "held",
        )
        .values(status="available", updated_at=now)
    )
    for row in stale:
        _booking_event(
            session,
            kind="hold_expired",
            actor_role="system",
            hold_id=row.id,
            payload={"slot_id": str(row.slot_id), "reason": "ttl_elapsed"},
            now=now,
        )
    session.flush()
    for row in stale:
        session.refresh(row)
    return stale


def expire_holds(session: Session, *, now: datetime | None = None) -> int:
    """Sweeper: expire every timed-out hold and release its slot. Idempotent.

    Returns the number of holds expired. Writes one audit row summarising the
    pass (ids only) so an operator can see the sweeper ran. Does NOT commit —
    the caller (worker tick / endpoint) owns the transaction.
    """
    now = now or utcnow()
    expired = _expire_active_holds(session, now=now)
    if expired:
        record_audit_event(
            session,
            action="tutoring.hold.expired_sweep",
            resource_type="booking_hold",
            actor_role="system",
            after_state={
                "expired_count": len(expired),
                "hold_ids": [str(row.id) for row in expired],
            },
        )
    return len(expired)


# --------------------------------------------------------------------------- #
# Hold creation
# --------------------------------------------------------------------------- #


def _replay(
    session: Session,
    *,
    idempotency_key: str,
    slot_id: uuid.UUID,
    student_user_id: uuid.UUID,
    now: datetime,
) -> BookingHold | None:
    """Return the existing hold for an identical replay, or raise on misuse."""
    existing = session.scalars(
        select(BookingHold).where(BookingHold.idempotency_key == idempotency_key)
    ).first()
    if existing is None:
        return None
    if existing.slot_id != slot_id or existing.student_user_id != student_user_id:
        # The same key MUST NOT mean two different things.
        raise IdempotencyKeyReuse(
            "idempotency key already used for a different slot/student",
            hold_id=str(existing.id),
        )
    if existing.status == "active" and is_expired(existing, now=now):
        raise HoldExpired("hold has expired", hold_id=str(existing.id))
    if existing.status in ("expired", "released"):
        raise HoldExpired(
            "hold is no longer live", hold_id=str(existing.id), status=existing.status
        )
    # 'active' (live) or 'consumed' -> identical key returns the SAME result.
    return existing


def create_hold(
    session: Session,
    *,
    slot_id: uuid.UUID,
    student_user_id: uuid.UUID,
    idempotency_key: str,
    now: datetime | None = None,
    ttl: timedelta | None = None,
) -> BookingHold:
    """Atomically place the one allowed active hold on a slot.

    Exactly one of N concurrent callers gets a hold; the others get
    ``HoldConflict``. Replaying the same ``idempotency_key`` returns the same
    hold object rather than creating a second one. Does not commit.
    """
    now = now or utcnow()
    key = (idempotency_key or "").strip()
    if not key or len(key) > 200:
        raise ValidationError(
            "idempotency_key must be 1..200 chars", field="idempotency_key"
        )
    replayed = _replay(
        session,
        idempotency_key=key,
        slot_id=slot_id,
        student_user_id=student_user_id,
        now=now,
    )
    if replayed is not None:
        return replayed

    # Self-heal first: an abandoned hold must not block the slot forever.
    _expire_active_holds(session, now=now, slot_id=slot_id)

    slot = session.get(TutorAvailabilitySlot, slot_id)
    if slot is None or slot.deleted_at is not None:
        raise NotFound("slot not found", resource="slot")
    if slot.status in ("booked", "cancelled", "expired"):
        raise SlotUnavailable(
            "slot is not bookable", slot_id=str(slot_id), status=slot.status
        )
    start_utc = _aware(slot.start_utc)
    if start_utc is not None and start_utc <= now:
        raise SlotUnavailable("slot is in the past", slot_id=str(slot_id))

    hold_id = uuid.uuid4()
    expires_at = now + (ttl or hold_ttl())

    # -- layer 1: ONE conditional INSERT carrying the marker --------------- #
    guard_no_active_hold = ~sa.exists(
        sa.select(BookingHold.id)
        .where(BookingHold.active_slot_id == sa.literal(slot_id, _UUID))
        .correlate(None)
    )
    guard_slot_available = sa.exists(
        sa.select(TutorAvailabilitySlot.id)
        .where(
            TutorAvailabilitySlot.id == sa.literal(slot_id, _UUID),
            TutorAvailabilitySlot.status == sa.literal("available", String(16)),
        )
        .correlate(None)
    )
    stmt = sa.insert(BookingHold).from_select(
        [
            "id",
            "created_at",
            "updated_at",
            "slot_id",
            "student_user_id",
            "status",
            "expires_at",
            "idempotency_key",
            "active_slot_id",
        ],
        sa.select(
            sa.literal(hold_id, _UUID),
            sa.literal(now, _TS),
            sa.literal(now, _TS),
            sa.literal(slot_id, _UUID),
            sa.literal(student_user_id, _UUID),
            sa.literal("active", String(16)),
            sa.literal(expires_at, _TS),
            sa.literal(key, String(200)),
            # The marker: equal to slot_id while active, guarded by UNIQUE.
            sa.literal(slot_id, _UUID),
        ).where(guard_no_active_hold, guard_slot_available),
    )
    try:
        result = session.execute(stmt)
    except IntegrityError as exc:
        # -- layer 2: the UNIQUE marker rejected the loser ----------------- #
        session.rollback()
        raise HoldConflict(
            "another student is holding this slot", slot_id=str(slot_id)
        ) from exc
    if (result.rowcount or 0) == 0:
        raise HoldConflict(
            "another student is holding this slot", slot_id=str(slot_id)
        )

    # -- layer 3: slot transition in the SAME transaction ------------------ #
    moved = session.execute(
        sa.update(TutorAvailabilitySlot)
        .where(
            TutorAvailabilitySlot.id == slot_id,
            TutorAvailabilitySlot.status == "available",
        )
        .values(status="held", updated_at=now)
    )
    if (moved.rowcount or 0) != 1:
        raise HoldConflict(
            "slot changed state while holding", slot_id=str(slot_id)
        )

    session.flush()
    hold = session.get(BookingHold, hold_id)
    if hold is None:  # pragma: no cover - defensive
        raise HoldConflict("hold could not be created", slot_id=str(slot_id))
    _booking_event(
        session,
        kind="hold_created",
        actor_role="student",
        hold_id=hold.id,
        payload={
            "slot_id": str(slot_id),
            "expires_at": expires_at.isoformat(),
            "ttl_minutes": int((expires_at - now).total_seconds() // 60),
        },
        now=now,
    )
    record_audit_event(
        session,
        action="tutoring.hold.created",
        resource_type="booking_hold",
        resource_id=hold.id,
        actor_user_id=student_user_id,
        actor_role="student",
        after_state={
            "slot_id": str(slot_id),
            "status": "active",
            "expires_at": expires_at.isoformat(),
        },
    )
    session.flush()
    return hold


# --------------------------------------------------------------------------- #
# Reads / release
# --------------------------------------------------------------------------- #


def get_hold(
    session: Session,
    hold_id: uuid.UUID,
    *,
    student_user_id: uuid.UUID | None = None,
    now: datetime | None = None,
    require_live: bool = False,
) -> BookingHold:
    """Fetch a hold, optionally owner-scoped and optionally TTL-enforced."""
    hold = session.get(BookingHold, hold_id)
    if hold is None:
        raise NotFound("hold not found", resource="booking_hold")
    if student_user_id is not None and hold.student_user_id != student_user_id:
        # Owner scoping: do not leak the existence of another student's hold.
        raise NotFound("hold not found", resource="booking_hold")
    if require_live:
        if hold.status != "active":
            raise HoldExpired(
                "hold is not active", hold_id=str(hold.id), status=hold.status
            )
        if is_expired(hold, now=now):
            raise HoldExpired("hold has expired", hold_id=str(hold.id))
    return hold


def release_hold(
    session: Session,
    hold_id: uuid.UUID,
    *,
    reason: str,
    actor_role: str = "system",
    actor_user_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> BookingHold:
    """Release an active hold and return its slot to ``available``. Idempotent.

    Used by the payment-failure / payment-expiry paths (frozen decision: a failed
    or expired payment RELEASES the slot) and by explicit student abandonment.
    """
    now = now or utcnow()
    hold = session.get(BookingHold, hold_id)
    if hold is None:
        raise NotFound("hold not found", resource="booking_hold")
    if hold.status != "active":
        return hold  # already consumed/expired/released: nothing to do
    session.execute(
        sa.update(BookingHold)
        .where(BookingHold.id == hold_id, BookingHold.status == "active")
        .values(status="released", active_slot_id=None, updated_at=now)
    )
    session.execute(
        sa.update(TutorAvailabilitySlot)
        .where(
            TutorAvailabilitySlot.id == hold.slot_id,
            TutorAvailabilitySlot.status == "held",
        )
        .values(status="available", updated_at=now)
    )
    _booking_event(
        session,
        kind="hold_released",
        actor_role=actor_role,
        hold_id=hold_id,
        payload={"slot_id": str(hold.slot_id), "reason": reason},
        now=now,
    )
    record_audit_event(
        session,
        action="tutoring.hold.released",
        resource_type="booking_hold",
        resource_id=hold_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        before_state={"status": "active"},
        after_state={"status": "released", "reason": reason},
    )
    session.flush()
    session.refresh(hold)
    return hold
