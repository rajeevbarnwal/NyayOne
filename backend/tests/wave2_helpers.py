"""Shared builders for the Wave 2 P2 service tests (SAATHI-123 / SAATHI-127).

Deliberately NOT named ``test_*`` so pytest does not collect it. Everything here
goes through the REAL services (holds, orders, verified webhooks) rather than
inserting rows by hand: a test that fabricates a "paid" session would prove
nothing about the frozen "only a verified payment creates a session" rule.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import event, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.db.models.audit import AuditEvent
from app.models.registration import User
from app.models.wave2 import TutorAvailabilitySlot, TutoringOutbox, TutorProfile
from app.services.providers.payment_provider import (
    DeterministicPaymentAdapter,
    TOKEN_SUCCESS,
)
from app.services.tutoring import booking, outbox_relay, payments, sessions

#: Fixed anchor so every assertion about windows/DST is reproducible.
T0 = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
AMOUNT_PAISE = 250_000  # Rs 2,500.00 as INTEGER paise. Never a float.


@dataclass
class World:
    """The actors + calendar one test needs."""

    student_id: uuid.UUID
    other_student_id: uuid.UUID
    tutor_user_id: uuid.UUID
    other_tutor_user_id: uuid.UUID
    admin_id: uuid.UUID
    tutor_id: uuid.UUID
    slots: tuple[uuid.UUID, ...]

    @property
    def slot_id(self) -> uuid.UUID:
        return self.slots[0]


def build_world(
    session: Session,
    *,
    now: datetime = T0,
    slot_starts: tuple[datetime, ...] | None = None,
    iana_timezone: str = "Asia/Kolkata",
) -> World:
    """One active tutor, two students, an admin and a handful of free slots."""
    student_id, other_student_id = uuid.uuid4(), uuid.uuid4()
    tutor_user_id, other_tutor_user_id = uuid.uuid4(), uuid.uuid4()
    admin_id = uuid.uuid4()
    for user_id, role in (
        (student_id, "student"),
        (other_student_id, "student"),
        (tutor_user_id, "lawyer"),
        (other_tutor_user_id, "lawyer"),
        (admin_id, "admin"),
    ):
        session.add(User(id=user_id, role=role, status="active"))
    tutor = TutorProfile(
        user_id=tutor_user_id,
        display_name="Adv. Meera Iyer",
        headline="Constitutional law",
        experience_years=11,
        verified_identity=True,
        verified_credentials=True,
        status="active",
    )
    session.add(tutor)
    session.flush()
    starts = slot_starts or tuple(
        now + timedelta(days=days, hours=1) for days in (10, 11, 12, 13)
    )
    slot_ids: list[uuid.UUID] = []
    for start in starts:
        slot = TutorAvailabilitySlot(
            tutor_id=tutor.id,
            start_utc=start,
            end_utc=start + timedelta(minutes=60),
            iana_timezone=iana_timezone,
            status="available",
        )
        session.add(slot)
        session.flush()
        slot_ids.append(slot.id)
    session.commit()
    return World(
        student_id=student_id,
        other_student_id=other_student_id,
        tutor_user_id=tutor_user_id,
        other_tutor_user_id=other_tutor_user_id,
        admin_id=admin_id,
        tutor_id=tutor.id,
        slots=tuple(slot_ids),
    )


@dataclass
class Booked:
    """A confirmed session plus everything the flow produced."""

    tutoring_session: object
    order: object
    hold: object
    adapter: DeterministicPaymentAdapter
    intents: list


def place_hold(
    session: Session,
    world: World,
    *,
    slot_id: uuid.UUID | None = None,
    student_user_id: uuid.UUID | None = None,
    now: datetime = T0,
    key: str | None = None,
):
    return booking.create_hold(
        session,
        slot_id=slot_id or world.slot_id,
        student_user_id=student_user_id or world.student_id,
        idempotency_key=key or f"hold-{uuid.uuid4()}",
        now=now,
    )


def open_order(
    session: Session,
    world: World,
    hold,
    *,
    adapter: DeterministicPaymentAdapter | None = None,
    amount_paise: int = AMOUNT_PAISE,
    now: datetime = T0,
    student_user_id: uuid.UUID | None = None,
):
    adapter = adapter or DeterministicPaymentAdapter()
    created = payments.create_order(
        session,
        hold_id=hold.id,
        student_user_id=student_user_id or world.student_id,
        amount_paise=amount_paise,
        idempotency_key=f"order-{hold.id}",
        provider=adapter,
        now=now,
    )
    return adapter, created.order


def deliver_paid_event(
    session: Session,
    adapter: DeterministicPaymentAdapter,
    order,
    *,
    amount_paise: int = AMOUNT_PAISE,
    now: datetime = T0,
    token: str = TOKEN_SUCCESS,
    event_id: str | None = None,
):
    raw, signature = adapter.make_event_body(
        provider_order_ref=order.provider_order_ref,
        amount_paise=amount_paise,
        token=token,
        event_id=event_id,
    )
    return payments.handle_event(
        session, signature=signature, raw_body=raw, provider=adapter, now=now
    )


def book_session(
    session: Session,
    world: World,
    *,
    slot_id: uuid.UUID | None = None,
    student_user_id: uuid.UUID | None = None,
    amount_paise: int = AMOUNT_PAISE,
    now: datetime = T0,
    commit: bool = True,
) -> Booked:
    """Hold -> order -> VERIFIED paid webhook -> confirmed session."""
    hold = place_hold(
        session, world, slot_id=slot_id, student_user_id=student_user_id, now=now
    )
    adapter, order = open_order(
        session,
        world,
        hold,
        amount_paise=amount_paise,
        now=now,
        student_user_id=student_user_id,
    )
    outcome = deliver_paid_event(
        session, adapter, order, amount_paise=amount_paise, now=now
    )
    if commit:
        session.commit()
    return Booked(
        tutoring_session=outcome.tutoring_session,
        order=order,
        hold=hold,
        adapter=adapter,
        intents=list(outcome.intents),
    )


def complete_and_confirm(
    session: Session,
    world: World,
    sess,
    *,
    now: datetime | None = None,
) -> datetime:
    """Record attendance after the scheduled end and have the student confirm it."""
    from app.services.tutoring import attendance

    after_end = now or (sessions._aware(sess.end_utc) + timedelta(minutes=5))
    attendance.record(
        session,
        sess.id,
        actor_user_id=world.tutor_user_id,
        actor_role="tutor",
        now=after_end,
    )
    attendance.confirm(
        session, sess.id, actor_user_id=world.student_id, now=after_end
    )
    session.commit()
    return after_end


# --------------------------------------------------------------------------- #
# Transaction / dispatch harness
# --------------------------------------------------------------------------- #


def commit_and_dispatch(
    session: Session,
    intents,
    dispatcher: outbox_relay.OutboxDispatcher,
    *,
    now: datetime | None = None,
) -> list[bool]:
    """Exactly what an endpoint does: commit FIRST, dispatch afterwards."""
    session.commit()
    return [
        outbox_relay.run_delivery(session, intent, dispatcher, now=now)
        for intent in intents
    ]


class failing_commit:
    """Context manager that makes the next ``session.commit()`` fail for real.

    Uses SQLAlchemy's ``before_commit`` hook, so the failure happens at commit
    time (after the flush) exactly as a disk/connection failure would — which is
    the only honest way to prove "a failed commit leaves no partial write and no
    outbox side effect".
    """

    def __init__(self, session: Session, *, exc: BaseException | None = None) -> None:
        self._session = session
        self._exc = exc or RuntimeError("simulated commit failure")

    def _boom(self, _session) -> None:
        raise self._exc

    def __enter__(self) -> "failing_commit":
        event.listen(self._session, "before_commit", self._boom)
        return self

    def __exit__(self, *_args) -> bool:
        event.remove(self._session, "before_commit", self._boom)
        return False


# --------------------------------------------------------------------------- #
# Assertion helpers
# --------------------------------------------------------------------------- #


def outbox_rows(
    session: Session, *, kind: str | None = None
) -> list[TutoringOutbox]:
    stmt = select(TutoringOutbox).order_by(
        TutoringOutbox.created_at, TutoringOutbox.id
    )
    if kind:
        stmt = stmt.where(TutoringOutbox.kind == kind)
    return list(session.scalars(stmt).all())


def audit_actions(session: Session) -> list[str]:
    return [
        row.action
        for row in session.scalars(
            select(AuditEvent).order_by(AuditEvent.created_at, AuditEvent.id)
        ).all()
    ]


def audit_rows(session: Session, action: str) -> list[AuditEvent]:
    return [
        row
        for row in session.scalars(select(AuditEvent)).all()
        if row.action == action
    ]
