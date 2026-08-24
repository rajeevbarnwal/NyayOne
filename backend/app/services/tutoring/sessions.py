"""Tutoring session lifecycle (SAATHI-123 / SAATHI-127 P2, matrix C3 + D1-D3).

Frozen decisions implemented here
---------------------------------
* **Only a signature-VERIFIED provider payment event converts a hold into a
  session.** :func:`create_from_paid_hold` refuses unless the order is ``paid``
  AND a ``payment_events`` row exists for it with ``signature_verified`` true and
  the provider-neutral ``paid`` event type. Setting ``payment_orders.status`` by
  hand is therefore NOT enough to manufacture a session.
* **Hold consumption is atomic with session creation.** The hold is consumed by
  a conditional ``UPDATE ... WHERE status='active'``, the slot by
  ``UPDATE ... WHERE status='held'``, and the session row is protected by
  ``uq_tutoring_sessions_slot_id``. All three are in the caller's single
  transaction, so a session can never exist without its hold being consumed and
  a slot can never back two sessions.
* **A payment that arrives after the hold TTL elapsed does not book anything** —
  ``HOLD_EXPIRED``; the slot has already been (or is now) released.
* **Reschedule / cancel >= 24h before start** (``settings.refund_free_cancel_hours``)
  is free / fully refunded. **Inside the window** there is NO automatic refund and
  no free reschedule: the ONLY way through is an authorised admin exception, which
  is written to ``session_cancellations`` (``admin_actor_id`` + ``audited``) and to
  ``audit_events``. A TUTOR cancellation is always a full refund. The boundary is
  inclusive: exactly 24.00h before start is still "outside the window".
* **Reschedule and cancel REVOKE stale reminder jobs** before new ones are
  scheduled, so a cancelled session can never notify.
* Every status change appends ``session_status_history`` AND ``booking_events``.

Status transition graph
-----------------------
``tutoring_sessions.status`` has a CHECK on its finite domain, but a database
cannot express "confirmed may become cancelled while cancelled may not become
completed". That graph is therefore enforced HERE, by
:func:`assert_transition`, and every mutation in this package routes through
:func:`transition` so no code path can bypass it::

    pending_provider -> confirmed | cancelled
    confirmed        -> rescheduled | cancelled | completed | disputed
    rescheduled      -> rescheduled | cancelled | completed | disputed
    completed        -> disputed                  (student raises a dispute)
    disputed         -> completed                 (admin resolves it)
    cancelled        -> (terminal)

Reads are strictly isolated: a student sees only their own sessions, a tutor only
sessions on their own profile, and an unauthorised id is reported as ``NOT_FOUND``
with the same shape as an unknown id, so the API cannot be used to enumerate.
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
    BookingHold,
    PaymentEvent,
    PaymentOrder,
    SessionCancellation,
    SessionStatusHistory,
    TutorAvailabilitySlot,
    TutoringSession,
    TutorProfile,
)
from app.services.audit_service import record_audit_event
from app.services.providers.payment_provider import EVENT_PAID, PaymentProvider
from app.services.tutoring import booking, outbox_relay, payments, reminders
from app.services.tutoring.errors import (
    AdminExceptionUnauthorised,
    Forbidden,
    HoldExpired,
    NotFound,
    PaymentUnverified,
    RescheduleWindowClosed,
    SessionStaleVersion,
    SessionStateInvalid,
    SlotUnavailable,
    ValidationError,
)
from app.services.tutoring.outbox_relay import OutboxIntent

#: Legal ``status`` moves. The DB CHECK guards the DOMAIN; this guards the GRAPH.
LEGAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "pending_provider": ("confirmed", "cancelled"),
    "confirmed": ("rescheduled", "cancelled", "completed", "disputed"),
    "rescheduled": ("rescheduled", "cancelled", "completed", "disputed"),
    "completed": ("disputed",),
    "disputed": ("completed",),
    "cancelled": (),
}
#: Statuses in which a session is still "live" (reschedulable / cancellable).
LIVE_STATUSES = ("pending_provider", "confirmed", "rescheduled")
ACTOR_ROLES = ("student", "tutor", "admin")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; normalise to UTC-aware."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def refund_window_hours() -> int:
    return int(getattr(settings, "refund_free_cancel_hours", 24))


# --------------------------------------------------------------------------- #
# Result objects (uniform shape across the package)
# --------------------------------------------------------------------------- #


@dataclass
class SessionCreated:
    """Result of :func:`create_from_paid_hold`. ``intents`` dispatch AFTER commit."""

    tutoring_session: TutoringSession
    intents: list[OutboxIntent] = field(default_factory=list)
    reminder_jobs: int = 0
    replayed: bool = False


@dataclass
class SessionMutation:
    """Result of a reschedule / cancel / status transition."""

    tutoring_session: TutoringSession
    intents: list[OutboxIntent] = field(default_factory=list)
    refund_assessment: payments.RefundAssessment | None = None
    refund_id: uuid.UUID | None = None
    reminders_revoked: int = 0
    reminders_scheduled: int = 0
    cancellation: SessionCancellation | None = None


# --------------------------------------------------------------------------- #
# Transition graph + history
# --------------------------------------------------------------------------- #


def assert_transition(from_status: str, to_status: str) -> None:
    """Enforce the legal status graph (not expressible as a DB constraint)."""
    allowed = LEGAL_TRANSITIONS.get(from_status)
    if allowed is None:
        raise SessionStateInvalid(
            "unknown session status", from_status=from_status, to_status=to_status
        )
    if to_status not in allowed:
        raise SessionStateInvalid(
            "illegal session status transition",
            from_status=from_status,
            to_status=to_status,
            allowed=list(allowed),
        )


def _history(
    session: Session,
    *,
    session_id: uuid.UUID,
    from_status: str | None,
    to_status: str,
    actor_role: str,
    now: datetime,
    reason: str | None = None,
) -> SessionStatusHistory:
    row = SessionStatusHistory(
        session_id=session_id,
        from_status=from_status,
        to_status=to_status,
        at=now,
        actor_role=actor_role,
        # VARCHAR(200) and reachable by operators: codes only, never narrative.
        reason=(reason[:200] if reason else None),
    )
    session.add(row)
    return row


def transition(
    session: Session,
    sess: TutoringSession,
    *,
    to_status: str,
    actor_role: str,
    expected_version: int | None = None,
    now: datetime | None = None,
    reason: str | None = None,
    extra_values: dict | None = None,
    booking_event_kind: str | None = None,
    booking_event_payload: dict | None = None,
) -> TutoringSession:
    """Move a session to ``to_status`` with graph + optimistic-version checks.

    The update is ONE conditional statement
    (``... WHERE id = :id AND version = :expected``), so two concurrent callers
    cannot both win: the loser sees ``rowcount == 0`` and gets
    ``SESSION_STALE_VERSION``.
    """
    now = now or utcnow()
    if actor_role not in ("student", "tutor", "admin", "system"):
        raise ValidationError("unknown actor role", field="actor_role")
    from_status = sess.status
    assert_transition(from_status, to_status)
    expected = sess.version if expected_version is None else int(expected_version)
    values: dict = {"status": to_status, "version": expected + 1, "updated_at": now}
    if extra_values:
        values.update(extra_values)
    result = session.execute(
        sa.update(TutoringSession)
        .where(TutoringSession.id == sess.id, TutoringSession.version == expected)
        .values(**values)
    )
    if (result.rowcount or 0) != 1:
        raise SessionStaleVersion(
            "session was modified by someone else",
            session_id=str(sess.id),
            expected_version=expected,
        )
    _history(
        session,
        session_id=sess.id,
        from_status=from_status,
        to_status=to_status,
        actor_role=actor_role,
        now=now,
        reason=reason,
    )
    if booking_event_kind:
        booking._booking_event(
            session,
            kind=booking_event_kind,
            actor_role=actor_role,
            session_id=sess.id,
            payload=booking_event_payload,
            now=now,
        )
    session.flush()
    session.refresh(sess)
    return sess


# --------------------------------------------------------------------------- #
# Creation (matrix C3)
# --------------------------------------------------------------------------- #


def _verified_paid_event(session: Session, order: PaymentOrder) -> PaymentEvent | None:
    return session.scalars(
        select(PaymentEvent).where(
            PaymentEvent.order_id == order.id,
            PaymentEvent.signature_verified.is_(True),
            PaymentEvent.event_type == EVENT_PAID,
        )
    ).first()


def create_from_paid_hold(
    session: Session,
    *,
    hold: BookingHold,
    order: PaymentOrder,
    now: datetime | None = None,
) -> SessionCreated:
    """Convert a held slot into a confirmed session. Atomic; does not commit.

    Refuses (typed, no partial write) when:

    * the order is not ``paid`` or carries no VERIFIED ``paid`` provider event
      (``PAYMENT_UNVERIFIED``) — this is the frozen "only a verified payment
      creates a session" rule,
    * the order does not belong to this hold/student (``VALIDATION_ERROR``),
    * the hold is not active or its TTL elapsed (``HOLD_EXPIRED``),
    * the slot moved out of ``held`` or already backs a session
      (``SLOT_UNAVAILABLE``).
    """
    now = now or utcnow()
    if order.hold_id != hold.id:
        raise ValidationError(
            "payment order does not belong to this hold", field="hold_id"
        )
    if order.student_user_id != hold.student_user_id:
        raise ValidationError(
            "payment order does not belong to this student", field="student_user_id"
        )
    if order.status != "paid":
        raise PaymentUnverified(
            "session creation requires a paid order",
            order_id=str(order.id),
            status=order.status,
        )
    if _verified_paid_event(session, order) is None:
        raise PaymentUnverified(
            "session creation requires a verified provider payment event",
            order_id=str(order.id),
        )

    # Idempotent replay: the hold was already consumed by this order.
    existing = session.scalars(
        select(TutoringSession).where(TutoringSession.slot_id == hold.slot_id)
    ).first()
    if existing is not None:
        if existing.order_id == order.id:
            return SessionCreated(tutoring_session=existing, replayed=True)
        raise SlotUnavailable(
            "slot already backs another session", slot_id=str(hold.slot_id)
        )

    if hold.status != "active":
        raise HoldExpired(
            "hold is no longer active", hold_id=str(hold.id), status=hold.status
        )
    if booking.is_expired(hold, now=now):
        # Frozen: a payment that lands after the TTL books NOTHING. Release the
        # slot in the same breath so it is not stranded.
        raise HoldExpired("hold has expired", hold_id=str(hold.id))

    slot = session.get(TutorAvailabilitySlot, hold.slot_id)
    if slot is None or slot.deleted_at is not None:
        raise NotFound("slot not found", resource="slot")

    # -- consume the hold (conditional: exactly one winner) ---------------- #
    consumed = session.execute(
        sa.update(BookingHold)
        .where(BookingHold.id == hold.id, BookingHold.status == "active")
        .values(status="consumed", active_slot_id=None, updated_at=now)
    )
    if (consumed.rowcount or 0) != 1:
        raise HoldExpired("hold was consumed or released concurrently", hold_id=str(hold.id))

    # -- book the slot (conditional) --------------------------------------- #
    booked = session.execute(
        sa.update(TutorAvailabilitySlot)
        .where(
            TutorAvailabilitySlot.id == slot.id,
            TutorAvailabilitySlot.status == "held",
        )
        .values(status="booked", updated_at=now)
    )
    if (booked.rowcount or 0) != 1:
        raise SlotUnavailable("slot is no longer held", slot_id=str(slot.id))

    sess = TutoringSession(
        slot_id=slot.id,
        tutor_id=slot.tutor_id,
        student_user_id=hold.student_user_id,
        order_id=order.id,
        start_utc=_aware(slot.start_utc),
        end_utc=_aware(slot.end_utc),
        iana_timezone=slot.iana_timezone,
        status="confirmed",
        version=1,
    )
    session.add(sess)
    try:
        session.flush()
    except IntegrityError as exc:  # uq_tutoring_sessions_slot_id
        session.rollback()
        raise SlotUnavailable(
            "slot already backs another session", slot_id=str(slot.id)
        ) from exc

    _history(
        session,
        session_id=sess.id,
        from_status=None,
        to_status="confirmed",
        actor_role="system",
        now=now,
        reason="payment_verified",
    )
    booking._booking_event(
        session,
        kind="hold_consumed",
        actor_role="system",
        hold_id=hold.id,
        session_id=sess.id,
        payload={"slot_id": str(slot.id), "order_id": str(order.id)},
        now=now,
    )
    booking._booking_event(
        session,
        kind="session_confirmed",
        actor_role="system",
        session_id=sess.id,
        payload={
            "slot_id": str(slot.id),
            "order_id": str(order.id),
            "start_utc": _aware(slot.start_utc).isoformat(),
        },
        now=now,
    )
    scheduled = reminders.schedule_for_session(session, sess, now=now)
    intents = [
        outbox_relay.enqueue(
            session,
            kind="booking_confirmed",
            aggregate_id=sess.id,
            payload={
                "session_id": str(sess.id),
                "tutor_id": str(sess.tutor_id),
                "start_utc": _aware(sess.start_utc).isoformat(),
                "iana_timezone": sess.iana_timezone,
                "reminder_jobs": len(scheduled),
            },
        )
    ]
    record_audit_event(
        session,
        action="tutoring.session.created",
        resource_type="tutoring_session",
        resource_id=sess.id,
        actor_user_id=hold.student_user_id,
        actor_role="system",
        after_state={
            "status": "confirmed",
            "slot_id": str(slot.id),
            "hold_id": str(hold.id),
            "order_id": str(order.id),
            "amount_paise": order.amount_paise,
            "currency": order.currency,
        },
    )
    session.flush()
    session.refresh(hold)
    return SessionCreated(
        tutoring_session=sess, intents=intents, reminder_jobs=len(scheduled)
    )


# --------------------------------------------------------------------------- #
# Reads (matrix D1) — strict, non-enumerating isolation
# --------------------------------------------------------------------------- #


def _not_found() -> NotFound:
    # One shape for "does not exist" and "not yours": no enumeration oracle.
    return NotFound("session not found", resource="tutoring_session")


def get_session(
    session: Session,
    session_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    role: str = "student",
    for_update: bool = False,
) -> TutoringSession:
    """Fetch one session the caller is entitled to see, else ``NOT_FOUND``."""
    if role not in ACTOR_ROLES:
        raise ValidationError("unknown actor role", field="role")
    if for_update:
        sess = session.scalar(
            select(TutoringSession)
            .where(TutoringSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    else:
        sess = session.get(TutoringSession, session_id)
    if sess is None or sess.deleted_at is not None:
        raise _not_found()
    if role == "admin":
        return sess
    if user_id is None:
        raise Forbidden("an actor id is required for a scoped read")
    if role == "student":
        if sess.student_user_id != user_id:
            raise _not_found()
        return sess
    tutor = session.get(TutorProfile, sess.tutor_id)
    if tutor is None or tutor.user_id != user_id:
        raise _not_found()
    return sess


def list_sessions(
    session: Session,
    *,
    user_id: uuid.UUID | None = None,
    role: str = "student",
    statuses: tuple[str, ...] | None = None,
    from_utc: datetime | None = None,
    to_utc: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[TutoringSession, ...]:
    """List the caller's sessions, newest start first, deterministically paged."""
    if role not in ACTOR_ROLES:
        raise ValidationError("unknown actor role", field="role")
    if limit <= 0 or limit > 200:
        raise ValidationError("limit must be between 1 and 200", field="limit")
    if offset < 0:
        raise ValidationError("offset must not be negative", field="offset")
    filters = [TutoringSession.deleted_at.is_(None)]
    if role == "student":
        if user_id is None:
            raise Forbidden("an actor id is required for a scoped read")
        filters.append(TutoringSession.student_user_id == user_id)
    elif role == "tutor":
        if user_id is None:
            raise Forbidden("an actor id is required for a scoped read")
        filters.append(
            select(TutorProfile.id)
            .where(
                TutorProfile.id == TutoringSession.tutor_id,
                TutorProfile.user_id == user_id,
            )
            .exists()
        )
    if statuses:
        unknown = sorted(set(statuses) - set(LEGAL_TRANSITIONS))
        if unknown:
            raise ValidationError(
                f"unknown session status filter: {','.join(unknown)}", field="statuses"
            )
        filters.append(TutoringSession.status.in_(statuses))
    if from_utc is not None:
        filters.append(TutoringSession.start_utc >= from_utc)
    if to_utc is not None:
        filters.append(TutoringSession.start_utc <= to_utc)
    rows = session.scalars(
        select(TutoringSession)
        .where(*filters)
        # Total order so page 1 and page 2 never disagree.
        .order_by(TutoringSession.start_utc.desc(), TutoringSession.id.asc())
        .limit(limit)
        .offset(offset)
    ).all()
    return tuple(rows)


# --------------------------------------------------------------------------- #
# Policy window helper (matrix D2/D3)
# --------------------------------------------------------------------------- #


def hours_before_start(sess: TutoringSession, now: datetime) -> Decimal:
    return payments.hours_before(_aware(sess.start_utc), now)


def _assert_actor(
    session: Session,
    sess: TutoringSession,
    *,
    actor_user_id: uuid.UUID | None,
    actor_role: str,
) -> None:
    """Role + ownership gate shared by reschedule and cancel."""
    if actor_role not in ACTOR_ROLES:
        raise ValidationError("unknown actor role", field="actor_role")
    if actor_role == "admin":
        if actor_user_id is None:
            raise Forbidden("an admin action must name the acting admin")
        return
    if actor_user_id is None:
        raise Forbidden("an actor id is required")
    if actor_role == "student" and sess.student_user_id != actor_user_id:
        raise _not_found()
    if actor_role == "tutor":
        tutor = session.get(TutorProfile, sess.tutor_id)
        if tutor is None or tutor.user_id != actor_user_id:
            raise _not_found()


# --------------------------------------------------------------------------- #
# Reschedule (matrix D2)
# --------------------------------------------------------------------------- #


def reschedule(
    session: Session,
    session_id: uuid.UUID,
    *,
    new_slot_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    actor_role: str = "student",
    expected_version: int | None = None,
    admin_exception: bool = False,
    admin_actor_id: uuid.UUID | None = None,
    reason: str | None = None,
    now: datetime | None = None,
) -> SessionMutation:
    """Move a live session onto another available slot of the SAME tutor.

    ``>= refund_free_cancel_hours`` before start: free. Inside the window the
    reschedule is refused (``RESCHEDULE_WINDOW_CLOSED``) unless an ADMIN grants
    an audited exception (``admin_exception=True`` with ``actor_role='admin'``).
    Stale reminder jobs are revoked and fresh ones scheduled off the new start.
    """
    now = now or utcnow()
    sess = get_session(session, session_id, user_id=actor_user_id, role=actor_role)
    _assert_actor(session, sess, actor_user_id=actor_user_id, actor_role=actor_role)
    if sess.status not in LIVE_STATUSES:
        raise SessionStateInvalid(
            "only a live session can be rescheduled", status=sess.status
        )
    window = refund_window_hours()
    hrs = hours_before_start(sess, now)
    inside_window = hrs < window
    if inside_window:
        if not admin_exception:
            raise RescheduleWindowClosed(
                "a free reschedule requires more notice",
                hours_before_start=str(hrs),
                policy_window_hours=window,
            )
        if actor_role != "admin" or admin_actor_id is None:
            raise AdminExceptionUnauthorised(
                "only an authorised admin may reschedule inside the window",
                field="admin_actor_id",
            )
    if new_slot_id == sess.slot_id:
        raise ValidationError("new slot must differ from the current slot", field="new_slot_id")

    new_slot = session.get(TutorAvailabilitySlot, new_slot_id)
    if new_slot is None or new_slot.deleted_at is not None:
        raise NotFound("slot not found", resource="slot")
    if new_slot.tutor_id != sess.tutor_id:
        raise ValidationError("new slot belongs to another tutor", field="new_slot_id")
    new_start = _aware(new_slot.start_utc)
    if new_start is None or new_start <= now:
        raise SlotUnavailable("slot is in the past", slot_id=str(new_slot_id))
    # An abandoned hold must not block a reschedule forever.
    booking._expire_active_holds(session, now=now, slot_id=new_slot_id)
    moved = session.execute(
        sa.update(TutorAvailabilitySlot)
        .where(
            TutorAvailabilitySlot.id == new_slot_id,
            TutorAvailabilitySlot.status == "available",
        )
        .values(status="booked", updated_at=now)
    )
    if (moved.rowcount or 0) != 1:
        raise SlotUnavailable("slot is not bookable", slot_id=str(new_slot_id))
    old_slot_id = sess.slot_id
    # The vacated slot becomes sellable again (no session points at it now).
    session.execute(
        sa.update(TutorAvailabilitySlot)
        .where(
            TutorAvailabilitySlot.id == old_slot_id,
            TutorAvailabilitySlot.status == "booked",
        )
        .values(status="available", updated_at=now)
    )

    revoked = reminders.revoke_for_session(
        session, sess.id, now=now, reason="rescheduled"
    )
    try:
        transition(
            session,
            sess,
            to_status="rescheduled",
            actor_role=actor_role,
            expected_version=expected_version,
            now=now,
            reason=reason or ("admin_exception" if inside_window else "reschedule"),
            extra_values={
                "slot_id": new_slot_id,
                "start_utc": new_start,
                "end_utc": _aware(new_slot.end_utc),
                "iana_timezone": new_slot.iana_timezone,
            },
            booking_event_kind="session_rescheduled",
            booking_event_payload={
                "from_slot_id": str(old_slot_id),
                "to_slot_id": str(new_slot_id),
                "hours_before_start": str(hrs),
                "admin_exception": bool(inside_window),
            },
        )
    except IntegrityError as exc:  # pragma: no cover - uq slot_id race
        session.rollback()
        raise SlotUnavailable(
            "slot already backs another session", slot_id=str(new_slot_id)
        ) from exc
    scheduled = reminders.schedule_for_session(session, sess, now=now)
    intents = [
        outbox_relay.enqueue(
            session,
            kind="booking_confirmed",
            aggregate_id=sess.id,
            payload={
                "session_id": str(sess.id),
                "reason": "rescheduled",
                "start_utc": new_start.isoformat(),
                "iana_timezone": sess.iana_timezone,
                "reminder_jobs": len(scheduled),
            },
        )
    ]
    record_audit_event(
        session,
        action=(
            "tutoring.session.reschedule_exception"
            if inside_window
            else "tutoring.session.rescheduled"
        ),
        resource_type="tutoring_session",
        resource_id=sess.id,
        actor_user_id=admin_actor_id or actor_user_id,
        actor_role=actor_role,
        before_state={"slot_id": str(old_slot_id), "status": "confirmed"},
        after_state={
            "slot_id": str(new_slot_id),
            "status": "rescheduled",
            "hours_before_start": str(hrs),
            "policy_window_hours": window,
            "admin_exception": bool(inside_window),
            "admin_actor_id": str(admin_actor_id) if admin_actor_id else None,
            "reminders_revoked": revoked,
            "reminders_scheduled": len(scheduled),
        },
    )
    session.flush()
    return SessionMutation(
        tutoring_session=sess,
        intents=intents,
        reminders_revoked=revoked,
        reminders_scheduled=len(scheduled),
    )


# --------------------------------------------------------------------------- #
# Cancel (matrix D3)
# --------------------------------------------------------------------------- #


def cancel(
    session: Session,
    session_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None,
    actor_role: str = "student",
    expected_version: int | None = None,
    admin_exception: bool = False,
    admin_actor_id: uuid.UUID | None = None,
    exception_amount_paise: int | None = None,
    reason: str | None = None,
    provider: PaymentProvider | None = None,
    now: datetime | None = None,
) -> SessionMutation:
    """Cancel a live session and apply the frozen refund policy. No commit.

    Policy (delegated to :func:`payments.assess_refund` so it stays one testable
    function): tutor cancellation -> full refund always; admin exception ->
    the named amount (default full), REQUIRES ``actor_role='admin'`` plus an
    ``admin_actor_id``, and is written to ``session_cancellations`` and
    ``audit_events``; otherwise ``>= window`` -> full refund, ``< window`` ->
    ``no_auto_refund``. Reminder jobs are revoked; the slot is retired to
    ``cancelled`` (never back to ``available``, because
    ``uq_tutoring_sessions_slot_id`` would make a re-booking of it unsatisfiable).
    """
    now = now or utcnow()
    sess = get_session(session, session_id, user_id=actor_user_id, role=actor_role)
    _assert_actor(session, sess, actor_user_id=actor_user_id, actor_role=actor_role)
    if sess.status not in LIVE_STATUSES:
        raise SessionStateInvalid(
            "only a live session can be cancelled", status=sess.status
        )
    if admin_exception and (actor_role != "admin" or admin_actor_id is None):
        raise AdminExceptionUnauthorised(
            "only an authorised admin may grant a refund exception",
            field="admin_actor_id",
        )
    hrs = hours_before_start(sess, now)
    order = session.get(PaymentOrder, sess.order_id) if sess.order_id else None
    captured = int(order.amount_paise) if (order and order.status == "paid") else 0
    assessment = payments.assess_refund(
        captured_paise=captured,
        hours_before_start=hrs,
        cancelled_by_role=actor_role,
        admin_exception=admin_exception,
        admin_actor_id=admin_actor_id,
        exception_amount_paise=exception_amount_paise,
        window_hours=refund_window_hours(),
    )

    cancellation = SessionCancellation(
        session_id=sess.id,
        cancelled_by_role=actor_role,
        hours_before_start=hrs,
        refund_decision=assessment.decision,
        admin_actor_id=admin_actor_id,
        # Every cancellation writes an audit_events row; an admin exception
        # additionally names the authorising admin (DB CHECK enforces that).
        audited=True,
    )
    session.add(cancellation)
    revoked = reminders.revoke_for_session(session, sess.id, now=now, reason="cancelled")
    transition(
        session,
        sess,
        to_status="cancelled",
        actor_role=actor_role,
        expected_version=expected_version,
        now=now,
        reason=reason or assessment.decision,
        booking_event_kind="session_cancelled",
        booking_event_payload={
            "cancelled_by_role": actor_role,
            "hours_before_start": str(hrs),
            "refund_decision": assessment.decision,
            "refund_amount_paise": assessment.amount_paise,
        },
    )
    session.execute(
        sa.update(TutorAvailabilitySlot)
        .where(TutorAvailabilitySlot.id == sess.slot_id)
        .values(status="cancelled", updated_at=now)
    )

    intents: list[OutboxIntent] = []
    refund_id: uuid.UUID | None = None
    if assessment.refund_due and order is not None and assessment.reason is not None:
        issued = payments.refund(
            session,
            order_id=order.id,
            amount_paise=assessment.amount_paise,
            reason=assessment.reason,
            actor_role=actor_role,
            actor_user_id=admin_actor_id or actor_user_id,
            provider=provider,
            now=now,
            # A retryable provider failure must not lose the promise: the refund
            # is persisted 'pending' and the durable relay finishes it.
            allow_pending_on_provider_failure=True,
        )
        refund_id = issued.refund.id
        intents.extend(issued.intents)
    intents.append(
        outbox_relay.enqueue(
            session,
            kind="booking_cancelled",
            aggregate_id=sess.id,
            payload={
                "session_id": str(sess.id),
                "cancelled_by_role": actor_role,
                "refund_decision": assessment.decision,
                "refund_amount_paise": assessment.amount_paise,
                "reminders_revoked": revoked,
            },
        )
    )
    record_audit_event(
        session,
        action=(
            "tutoring.session.cancel_exception"
            if assessment.decision == "admin_exception"
            else "tutoring.session.cancelled"
        ),
        resource_type="tutoring_session",
        resource_id=sess.id,
        actor_user_id=admin_actor_id or actor_user_id,
        actor_role=actor_role,
        before_state={"status": "confirmed"},
        after_state={
            "status": "cancelled",
            "cancelled_by_role": actor_role,
            "admin_actor_id": str(admin_actor_id) if admin_actor_id else None,
            "audited": True,
            "reminders_revoked": revoked,
            **assessment.as_dict(),
        },
    )
    session.flush()
    return SessionMutation(
        tutoring_session=sess,
        intents=intents,
        refund_assessment=assessment,
        refund_id=refund_id,
        reminders_revoked=revoked,
        cancellation=cancellation,
    )


# --------------------------------------------------------------------------- #
# Introspection helper used by attendance / reviews
# --------------------------------------------------------------------------- #


def has_ended(sess: TutoringSession, *, now: datetime | None = None) -> bool:
    """True once the SCHEDULED end has passed (inclusive of the exact instant)."""
    now = now or utcnow()
    end_utc = _aware(sess.end_utc)
    return end_utc is not None and now >= end_utc


def status_history(
    session: Session, session_id: uuid.UUID
) -> tuple[SessionStatusHistory, ...]:
    return tuple(
        session.scalars(
            select(SessionStatusHistory)
            .where(SessionStatusHistory.session_id == session_id)
            .order_by(SessionStatusHistory.at.asc(), SessionStatusHistory.id.asc())
        ).all()
    )
