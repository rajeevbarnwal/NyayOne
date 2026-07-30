"""Wave 2 session lifecycle proofs (SAATHI-123/127 P2, matrix C3 + D1-D3 + J1).

Every test drives the REAL services against a real (SQLite) database: holds are
placed by ``booking.create_hold``, money moves only through
``payments.handle_event`` with a genuinely signed body, and nothing is inserted
by hand. A test that fabricated a paid session would prove nothing about the
frozen "only a verified payment creates a session" decision.

Frozen decisions proved here
----------------------------
* only a signature-VERIFIED ``paid`` provider event converts a hold into a
  session; failure/expiry releases the slot; a payment after the hold TTL books
  nothing;
* money is integer paise, INR only;
* cancel/reschedule at EXACTLY 24h is outside the window (free / full refund) and
  one minute later is inside it (no automatic refund, no free reschedule) — the
  boundary is asserted from BOTH sides;
* an authorised admin exception is the only way through the window, and it is
  audited;
* a tutor cancellation always refunds in full;
* the status-transition graph is enforced in the service;
* instants are UTC with a retained IANA zone, including ambiguous and
  non-existent DST local times;
* dispatch happens only AFTER commit, and a failed commit leaves no partial
  write and no outbox side effect;
* no PAN / CVV / OTP / raw join token / SDP / ICE / device label ever reaches a
  persisted row, an outbox payload, an audit row or a log record.
"""
from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.wave2 import (
    BookingEvent,
    BookingHold,
    PaymentEvent,
    PaymentOrder,
    PaymentRefund,
    SessionCancellation,
    TutorAvailabilitySlot,
    TutoringSession,
)
from app.services.providers import payment_provider as pp
from app.services.providers import video_provider as vp
from app.services.tutoring import booking, errors, outbox_relay, payments, reminders
from app.services.tutoring import seed as tutoring_seed
from app.services.tutoring import sessions as sessions_service
from tests.wave2_helpers import (
    AMOUNT_PAISE,
    T0,
    audit_rows,
    book_session,
    build_world,
    commit_and_dispatch,
    deliver_paid_event,
    failing_commit,
    open_order,
    outbox_rows,
    place_hold,
)

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.fixture()
def world(db_session: Session):
    return build_world(db_session, now=T0)


# --------------------------------------------------------------------------- #
# C3 — creation only on a verified payment, atomically with hold consumption
# --------------------------------------------------------------------------- #


def test_verified_payment_creates_confirmed_session_atomically(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session

    assert sess.status == "confirmed" and sess.version == 1
    assert sess.order_id == booked.order.id
    assert sess.student_user_id == world.student_id
    assert sess.tutor_id == world.tutor_id
    assert sess.iana_timezone == "Asia/Kolkata"

    # Hold consumed and slot booked in the SAME transaction as the session.
    hold = db_session.get(BookingHold, booked.hold.id)
    assert (hold.status, hold.active_slot_id) == ("consumed", None)
    assert db_session.get(TutorAvailabilitySlot, sess.slot_id).status == "booked"

    history = sessions_service.status_history(db_session, sess.id)
    assert [(h.from_status, h.to_status) for h in history] == [(None, "confirmed")]

    kinds = {
        row.kind
        for row in db_session.scalars(select(BookingEvent)).all()
    }
    assert {"hold_created", "payment_initiated", "hold_consumed", "session_confirmed",
            "payment_succeeded"} <= kinds
    # Outbox rows exist, still PENDING: nothing was dispatched inside the tx.
    assert {(r.kind, r.status) for r in outbox_rows(db_session)} == {
        ("booking_confirmed", "pending"),
        ("payment_captured", "pending"),
    }


def test_session_creation_requires_a_verified_paid_event(db_session, world):
    """Flipping ``payment_orders.status`` by hand must NOT manufacture a session."""
    hold = place_hold(db_session, world, now=T0)
    _adapter, order = open_order(db_session, world, hold, now=T0)

    # (a) order not paid at all.
    with pytest.raises(errors.PaymentUnverified) as unpaid:
        sessions_service.create_from_paid_hold(
            db_session, hold=hold, order=order, now=T0
        )
    assert unpaid.value.code == "PAYMENT_UNVERIFIED"

    # (b) order 'paid' but no VERIFIED provider event exists.
    order.status = "paid"
    db_session.flush()
    with pytest.raises(errors.PaymentUnverified):
        sessions_service.create_from_paid_hold(
            db_session, hold=hold, order=order, now=T0
        )
    db_session.rollback()
    assert db_session.scalars(select(TutoringSession)).all() == []


def test_forged_signature_never_touches_the_database(db_session, world):
    hold = place_hold(db_session, world, now=T0)
    adapter, order = open_order(db_session, world, hold, now=T0)
    db_session.commit()
    raw, _valid = adapter.make_event_body(
        provider_order_ref=order.provider_order_ref, amount_paise=AMOUNT_PAISE
    )
    with pytest.raises(errors.PaymentUnverified):
        payments.handle_event(
            db_session,
            signature="deadbeef" * 8,
            raw_body=raw,
            provider=adapter,
            now=T0,
        )
    db_session.rollback()
    assert db_session.scalars(select(PaymentEvent)).all() == []
    assert db_session.scalars(select(TutoringSession)).all() == []
    assert db_session.get(PaymentOrder, order.id).status == "created"


def test_declined_payment_releases_the_slot_and_books_nothing(db_session, world):
    hold = place_hold(db_session, world, now=T0)
    adapter, order = open_order(db_session, world, hold, now=T0)
    outcome = deliver_paid_event(
        db_session, adapter, order, now=T0, token=pp.TOKEN_DECLINED
    )
    db_session.commit()
    assert outcome.event_type == pp.EVENT_FAILED and outcome.slot_released is True
    assert outcome.tutoring_session is None
    assert db_session.get(PaymentOrder, order.id).status == "failed"
    assert db_session.get(BookingHold, hold.id).status == "released"
    assert db_session.get(TutorAvailabilitySlot, world.slot_id).status == "available"
    assert db_session.scalars(select(TutoringSession)).all() == []


def test_payment_arriving_after_hold_expiry_books_nothing(db_session, world):
    hold = place_hold(db_session, world, now=T0)
    adapter, order = open_order(db_session, world, hold, now=T0)
    db_session.commit()
    late = T0 + timedelta(minutes=11)  # booking_hold_minutes = 10

    with pytest.raises(errors.HoldExpired) as expired:
        deliver_paid_event(db_session, adapter, order, now=late)
    assert expired.value.code == "HOLD_EXPIRED"
    db_session.rollback()

    assert db_session.scalars(select(TutoringSession)).all() == []
    assert db_session.get(PaymentOrder, order.id).status == "created"
    # The sweeper then frees the slot for the next student.
    assert booking.expire_holds(db_session, now=late) == 1
    db_session.commit()
    assert db_session.get(BookingHold, hold.id).status == "expired"
    assert db_session.get(TutorAvailabilitySlot, world.slot_id).status == "available"


def test_duplicate_provider_event_produces_no_second_session(db_session, world):
    booked = book_session(db_session, world, now=T0)
    with pytest.raises(errors.DuplicateEvent):
        deliver_paid_event(db_session, booked.adapter, booked.order, now=T0)
    db_session.rollback()
    assert len(db_session.scalars(select(TutoringSession)).all()) == 1
    assert len(db_session.scalars(select(PaymentEvent)).all()) == 1


def test_money_is_integer_paise_and_inr_only(db_session, world):
    hold = place_hold(db_session, world, now=T0)
    for bad in (2500.0, Decimal("2500"), True, "2500"):
        with pytest.raises(errors.ValidationError):
            payments.create_order(
                db_session,
                hold_id=hold.id,
                student_user_id=world.student_id,
                amount_paise=bad,  # type: ignore[arg-type]
                idempotency_key=f"bad-{bad!r}",
                now=T0,
            )
    with pytest.raises(errors.ValidationError):
        payments.create_order(
            db_session,
            hold_id=hold.id,
            student_user_id=world.student_id,
            amount_paise=100,
            currency="USD",
            idempotency_key="usd",
            now=T0,
        )


# --------------------------------------------------------------------------- #
# D1 — reads, strictly isolated and non-enumerating
# --------------------------------------------------------------------------- #


def test_reads_are_cross_user_isolated_and_non_enumerating(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session

    assert sessions_service.get_session(
        db_session, sess.id, user_id=world.student_id, role="student"
    ).id == sess.id
    assert sessions_service.get_session(
        db_session, sess.id, user_id=world.tutor_user_id, role="tutor"
    ).id == sess.id
    assert sessions_service.get_session(db_session, sess.id, role="admin").id == sess.id

    unknown_id = uuid.uuid4()
    with pytest.raises(errors.NotFound) as absent:
        sessions_service.get_session(
            db_session, unknown_id, user_id=world.student_id, role="student"
        )
    for user_id, role in (
        (world.other_student_id, "student"),
        (world.other_tutor_user_id, "tutor"),
    ):
        with pytest.raises(errors.NotFound) as foreign:
            sessions_service.get_session(
                db_session, sess.id, user_id=user_id, role=role
            )
        # Identical code AND message: no enumeration oracle.
        assert foreign.value.code == absent.value.code
        assert foreign.value.message == absent.value.message
        assert foreign.value.to_dict() == absent.value.to_dict()

    assert [s.id for s in sessions_service.list_sessions(
        db_session, user_id=world.student_id, role="student")] == [sess.id]
    assert [s.id for s in sessions_service.list_sessions(
        db_session, user_id=world.tutor_user_id, role="tutor")] == [sess.id]
    assert sessions_service.list_sessions(
        db_session, user_id=world.other_student_id, role="student") == ()
    assert sessions_service.list_sessions(
        db_session, user_id=world.other_tutor_user_id, role="tutor") == ()
    with pytest.raises(errors.Forbidden):
        sessions_service.list_sessions(db_session, role="student")
    with pytest.raises(errors.ValidationError):
        sessions_service.list_sessions(db_session, user_id=world.student_id, role="root")
    with pytest.raises(errors.ValidationError):
        sessions_service.list_sessions(
            db_session, user_id=world.student_id, role="student", statuses=("nope",)
        )


# --------------------------------------------------------------------------- #
# D2 — reschedule
# --------------------------------------------------------------------------- #


def test_reschedule_outside_window_is_free_and_revokes_stale_reminders(
    db_session, world
):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    old_slot_id = sess.slot_id
    before = reminders.list_jobs(db_session, sess.id, statuses=("scheduled",))
    assert {job.offset_kind for job in before} == {"7d", "1d", "3h"}

    result = sessions_service.reschedule(
        db_session,
        sess.id,
        new_slot_id=world.slots[1],
        actor_user_id=world.student_id,
        actor_role="student",
        expected_version=sess.version,
        now=T0,
    )
    db_session.commit()

    assert result.tutoring_session.status == "rescheduled"
    assert result.tutoring_session.version == 2
    assert result.tutoring_session.slot_id == world.slots[1]
    assert result.reminders_revoked == 3 and result.reminders_scheduled == 3
    # No REFUND is involved in a free reschedule.
    assert db_session.scalars(select(PaymentRefund)).all() == []
    assert db_session.get(TutorAvailabilitySlot, world.slots[1]).status == "booked"
    assert db_session.get(TutorAvailabilitySlot, old_slot_id).status == "available"

    scheduled = reminders.list_jobs(db_session, sess.id, statuses=("scheduled",))
    revoked = reminders.list_jobs(db_session, sess.id, statuses=("revoked",))
    assert len(scheduled) == 3 and len(revoked) == 3
    new_start = sessions_service._aware(result.tutoring_session.start_utc)
    assert {job.scheduled_for.replace(tzinfo=None) for job in scheduled} == {
        (new_start - reminders.parse_offset(kind)).replace(tzinfo=None)
        for kind in ("7d", "1d", "3h")
    }
    assert {(h.from_status, h.to_status) for h in
            sessions_service.status_history(db_session, sess.id)} == {
        (None, "confirmed"), ("confirmed", "rescheduled")
    }


def test_reschedule_boundary_exactly_24h_is_free_and_inside_is_refused(db_session):
    """The exactly-24h boundary, asserted from BOTH sides."""
    start = T0 + timedelta(days=20)
    world = build_world(
        db_session,
        now=T0,
        slot_starts=(start, start + timedelta(days=1), start + timedelta(days=2)),
    )
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session

    inside = start - timedelta(hours=24) + timedelta(minutes=1)
    with pytest.raises(errors.RescheduleWindowClosed) as closed:
        sessions_service.reschedule(
            db_session,
            sess.id,
            new_slot_id=world.slots[1],
            actor_user_id=world.student_id,
            actor_role="student",
            now=inside,
        )
    assert Decimal(closed.value.extra["hours_before_start"]) < 24
    db_session.rollback()

    boundary = start - timedelta(hours=24)  # EXACTLY 24.00h: still free
    assert sessions_service.hours_before_start(sess, boundary) == Decimal("24.00")
    result = sessions_service.reschedule(
        db_session,
        sess.id,
        new_slot_id=world.slots[1],
        actor_user_id=world.student_id,
        actor_role="student",
        now=boundary,
    )
    db_session.commit()
    assert result.tutoring_session.slot_id == world.slots[1]
    assert result.tutoring_session.status == "rescheduled"


def test_reschedule_inside_window_needs_an_audited_admin_exception(db_session):
    start = T0 + timedelta(days=20)
    world = build_world(db_session, now=T0, slot_starts=(start, start + timedelta(days=1)))
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    inside = start - timedelta(hours=3)

    # A student cannot self-authorise the exception.
    with pytest.raises(errors.AdminExceptionUnauthorised):
        sessions_service.reschedule(
            db_session,
            sess.id,
            new_slot_id=world.slots[1],
            actor_user_id=world.student_id,
            actor_role="student",
            admin_exception=True,
            now=inside,
        )
    db_session.rollback()
    # An admin exception must name the admin.
    with pytest.raises(errors.AdminExceptionUnauthorised):
        sessions_service.reschedule(
            db_session,
            sess.id,
            new_slot_id=world.slots[1],
            actor_user_id=world.admin_id,
            actor_role="admin",
            admin_exception=True,
            admin_actor_id=None,
            now=inside,
        )
    db_session.rollback()

    sessions_service.reschedule(
        db_session,
        sess.id,
        new_slot_id=world.slots[1],
        actor_user_id=world.admin_id,
        actor_role="admin",
        admin_exception=True,
        admin_actor_id=world.admin_id,
        now=inside,
    )
    db_session.commit()
    audited = audit_rows(db_session, "tutoring.session.reschedule_exception")
    assert len(audited) == 1
    assert audited[0].after_state["admin_actor_id"] == str(world.admin_id)
    assert audited[0].after_state["admin_exception"] is True


def test_reschedule_rejects_stale_version_and_bad_targets(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session

    with pytest.raises(errors.SessionStaleVersion) as stale:
        sessions_service.reschedule(
            db_session,
            sess.id,
            new_slot_id=world.slots[1],
            actor_user_id=world.student_id,
            actor_role="student",
            expected_version=sess.version + 7,
            now=T0,
        )
    assert stale.value.code == "SESSION_STALE_VERSION"
    db_session.rollback()

    with pytest.raises(errors.ValidationError):  # same slot
        sessions_service.reschedule(
            db_session, sess.id, new_slot_id=sess.slot_id,
            actor_user_id=world.student_id, actor_role="student", now=T0,
        )
    db_session.rollback()
    with pytest.raises(errors.NotFound):  # unknown slot
        sessions_service.reschedule(
            db_session, sess.id, new_slot_id=uuid.uuid4(),
            actor_user_id=world.student_id, actor_role="student", now=T0,
        )
    db_session.rollback()
    # A slot that another student has already booked is not a valid target.
    book_session(
        db_session, world, slot_id=world.slots[1],
        student_user_id=world.other_student_id, now=T0,
    )
    with pytest.raises(errors.SlotUnavailable):
        sessions_service.reschedule(
            db_session, sess.id, new_slot_id=world.slots[1],
            actor_user_id=world.student_id, actor_role="student", now=T0,
        )
    db_session.rollback()
    # A slot in the past is never a valid target, even for an admin exception
    # (the window check is satisfied, so SLOT_UNAVAILABLE is what surfaces).
    with pytest.raises(errors.SlotUnavailable):
        sessions_service.reschedule(
            db_session, sess.id, new_slot_id=world.slots[2],
            actor_user_id=world.admin_id, actor_role="admin",
            admin_exception=True, admin_actor_id=world.admin_id,
            now=sessions_service._aware(
                db_session.get(TutorAvailabilitySlot, world.slots[2]).start_utc
            ) + timedelta(hours=1),
        )
    db_session.rollback()
    # Another tutor's slot is never a valid target.
    other = TutorAvailabilitySlot(
        tutor_id=uuid.uuid4(),
        start_utc=T0 + timedelta(days=30),
        end_utc=T0 + timedelta(days=30, hours=1),
        iana_timezone="Asia/Kolkata",
        status="available",
    )
    db_session.add(other)
    db_session.flush()
    with pytest.raises(errors.ValidationError):
        sessions_service.reschedule(
            db_session, sess.id, new_slot_id=other.id,
            actor_user_id=world.student_id, actor_role="student", now=T0,
        )
    db_session.rollback()


# --------------------------------------------------------------------------- #
# D3 — cancellation and refund policy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("offset", "decision", "expected_paise", "expected_hours"),
    [
        (timedelta(hours=24), "full_refund", AMOUNT_PAISE, Decimal("24.00")),
        (timedelta(hours=24) - timedelta(minutes=1), "no_auto_refund", 0, Decimal("23.98")),
    ],
    ids=["exactly_24h_full_refund", "one_minute_inside_no_auto_refund"],
)
def test_cancel_refund_policy_at_the_24h_boundary(
    db_session, offset, decision, expected_paise, expected_hours
):
    start = T0 + timedelta(days=20)
    world = build_world(db_session, now=T0, slot_starts=(start,))
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session

    result = sessions_service.cancel(
        db_session,
        sess.id,
        actor_user_id=world.student_id,
        actor_role="student",
        now=start - offset,
    )
    db_session.commit()

    assert result.refund_assessment.decision == decision
    assert result.refund_assessment.amount_paise == expected_paise
    assert result.refund_assessment.hours_before_start == expected_hours
    assert result.tutoring_session.status == "cancelled"
    assert result.reminders_revoked == 3
    assert reminders.list_jobs(db_session, sess.id, statuses=("scheduled",)) == ()
    assert db_session.get(TutorAvailabilitySlot, sess.slot_id).status == "cancelled"

    row = db_session.scalars(select(SessionCancellation)).one()
    assert row.cancelled_by_role == "student"
    assert row.refund_decision == decision
    assert Decimal(row.hours_before_start) == expected_hours
    assert row.audited is True
    assert row.admin_actor_id is None

    refunds = db_session.scalars(select(PaymentRefund)).all()
    if expected_paise:
        assert [(r.amount_paise, r.reason, r.status) for r in refunds] == [
            (AMOUNT_PAISE, "cancel_ge_24h", "succeeded")
        ]
        assert refunds[0].succeeded_order_id == booked.order.id
    else:
        assert refunds == []
    assert {r.kind for r in outbox_rows(db_session)} >= {"booking_cancelled"}


def test_tutor_cancellation_always_refunds_in_full(db_session):
    start = T0 + timedelta(days=20)
    world = build_world(db_session, now=T0, slot_starts=(start,))
    booked = book_session(db_session, world, now=T0)
    result = sessions_service.cancel(
        db_session,
        booked.tutoring_session.id,
        actor_user_id=world.tutor_user_id,
        actor_role="tutor",
        now=start - timedelta(minutes=30),  # deep inside the window
    )
    db_session.commit()
    assert result.refund_assessment.decision == "full_refund"
    assert result.refund_assessment.reason == "tutor_cancelled"
    assert result.refund_assessment.amount_paise == AMOUNT_PAISE
    refund = db_session.scalars(select(PaymentRefund)).one()
    assert (refund.reason, refund.status) == ("tutor_cancelled", "succeeded")


def test_admin_exception_inside_window_is_authorised_and_audited(db_session):
    start = T0 + timedelta(days=20)
    world = build_world(db_session, now=T0, slot_starts=(start,))
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    inside = start - timedelta(hours=2)

    with pytest.raises(errors.AdminExceptionUnauthorised):
        sessions_service.cancel(
            db_session, sess.id, actor_user_id=world.student_id,
            actor_role="student", admin_exception=True, now=inside,
        )
    db_session.rollback()

    result = sessions_service.cancel(
        db_session,
        sess.id,
        actor_user_id=world.admin_id,
        actor_role="admin",
        admin_exception=True,
        admin_actor_id=world.admin_id,
        exception_amount_paise=AMOUNT_PAISE,
        now=inside,
    )
    db_session.commit()
    assert result.refund_assessment.decision == "admin_exception"
    row = db_session.scalars(select(SessionCancellation)).one()
    assert row.refund_decision == "admin_exception"
    assert row.admin_actor_id == world.admin_id and row.audited is True
    audited = audit_rows(db_session, "tutoring.session.cancel_exception")
    assert len(audited) == 1
    assert audited[0].after_state["admin_actor_id"] == str(world.admin_id)
    refund = db_session.scalars(select(PaymentRefund)).one()
    assert (refund.reason, refund.amount_paise) == ("admin_exception", AMOUNT_PAISE)
    # An exception may never exceed the captured amount.
    with pytest.raises(errors.AmountMismatch):
        payments.assess_refund(
            captured_paise=AMOUNT_PAISE,
            hours_before_start=Decimal("1.00"),
            cancelled_by_role="student",
            admin_exception=True,
            admin_actor_id=world.admin_id,
            exception_amount_paise=AMOUNT_PAISE + 1,
        )


def test_duplicate_refund_is_prevented(db_session):
    start = T0 + timedelta(days=20)
    world = build_world(db_session, now=T0, slot_starts=(start,))
    booked = book_session(db_session, world, now=T0)
    sessions_service.cancel(
        db_session,
        booked.tutoring_session.id,
        actor_user_id=world.student_id,
        actor_role="student",
        now=start - timedelta(days=2),
    )
    db_session.commit()
    with pytest.raises(errors.RefundDuplicate):
        payments.refund(
            db_session,
            order_id=booked.order.id,
            amount_paise=AMOUNT_PAISE,
            reason="cancel_ge_24h",
            now=T0,
        )
    db_session.rollback()
    assert len(db_session.scalars(select(PaymentRefund)).all()) == 1


def test_cancelled_session_is_terminal(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    sessions_service.cancel(
        db_session, sess.id, actor_user_id=world.student_id,
        actor_role="student", now=T0,
    )
    db_session.commit()
    for call in (
        lambda: sessions_service.cancel(
            db_session, sess.id, actor_user_id=world.student_id,
            actor_role="student", now=T0),
        lambda: sessions_service.reschedule(
            db_session, sess.id, new_slot_id=world.slots[1],
            actor_user_id=world.student_id, actor_role="student", now=T0),
    ):
        with pytest.raises(errors.SessionStateInvalid):
            call()
        db_session.rollback()


def test_status_transition_graph_is_enforced_in_the_service():
    graph = sessions_service.LEGAL_TRANSITIONS
    assert graph["cancelled"] == ()
    for from_status, allowed in graph.items():
        for to_status in allowed:
            sessions_service.assert_transition(from_status, to_status)
        for to_status in set(graph) - set(allowed):
            with pytest.raises(errors.SessionStateInvalid) as bad:
                sessions_service.assert_transition(from_status, to_status)
            assert bad.value.extra["from_status"] == from_status
    with pytest.raises(errors.SessionStateInvalid):
        sessions_service.assert_transition("not_a_status", "confirmed")


# --------------------------------------------------------------------------- #
# Time model: UTC instants + retained IANA zone, including DST hazards
# --------------------------------------------------------------------------- #


def test_dst_ambiguous_and_nonexistent_local_times_are_resolved_and_retained(
    db_session,
):
    from app.services.tutoring import availability

    # A month before the fall-back transition, so both probe slots are bookable.
    now = T0.replace(month=10, day=1)
    world = build_world(db_session, now=T0)
    probes = tutoring_seed.dst_probe_slots(db_session, world.tutor_id)
    db_session.commit()

    ambiguous = availability.resolve_local_instant(
        tutoring_seed.DST_AMBIGUOUS_LOCAL, tutoring_seed.DST_ZONE
    )
    nonexistent = availability.resolve_local_instant(
        tutoring_seed.DST_NONEXISTENT_LOCAL, tutoring_seed.DST_ZONE
    )
    # Fall-back overlap: BOTH folds are valid; policy keeps the EARLIER one.
    assert ambiguous.classification == availability.AMBIGUOUS
    assert ambiguous.resolved_local.replace(tzinfo=None) == tutoring_seed.DST_AMBIGUOUS_LOCAL
    assert ambiguous.instant_utc.utcoffset().total_seconds() == 0
    assert ambiguous.resolved_local.utcoffset() == timedelta(hours=-4)  # still EDT
    # Spring-forward gap: 02:30 never happens; policy pushes past the gap.
    assert nonexistent.classification == availability.NONEXISTENT
    assert nonexistent.resolved_local.replace(tzinfo=None) == nonexistent.requested_local.replace(hour=3)
    assert nonexistent.resolved_local.utcoffset() == timedelta(hours=-4)

    for label, slot in probes.items():
        stored = db_session.get(TutorAvailabilitySlot, slot.id)
        assert stored.iana_timezone == tutoring_seed.DST_ZONE  # zone RETAINED
        rendered = availability.to_local(
            sessions_service._aware(stored.start_utc), stored.iana_timezone
        )
        assert rendered.utcoffset() is not None

    # A DST slot books like any other, and the session keeps the zone.
    booked = book_session(db_session, world, slot_id=probes["ambiguous"].id, now=now)
    sess = booked.tutoring_session
    assert sess.iana_timezone == tutoring_seed.DST_ZONE
    assert sessions_service._aware(sess.start_utc) == ambiguous.instant_utc
    # Reminders are computed off the UTC instant, never off the wall clock.
    for job in reminders.list_jobs(db_session, sess.id, statuses=("scheduled",)):
        assert sessions_service._aware(job.scheduled_for) == (
            ambiguous.instant_utc - reminders.parse_offset(job.offset_kind)
        )


# --------------------------------------------------------------------------- #
# Failure injection: providers, commit failure, post-commit dispatch
# --------------------------------------------------------------------------- #


def test_provider_unavailable_and_timeout_surface_as_typed_errors(
    db_session, world, monkeypatch
):
    hold = place_hold(db_session, world, now=T0)
    with pytest.raises(errors.ProviderUnavailable) as unavailable:
        payments.create_order(
            db_session,
            hold_id=hold.id,
            student_user_id=world.student_id,
            amount_paise=AMOUNT_PAISE,
            idempotency_key="provider-down",
            provider=pp.FailingPaymentAdapter(retryable=True, code="PROVIDER_TIMEOUT"),
            now=T0,
        )
    assert unavailable.value.code == "PROVIDER_UNAVAILABLE"
    assert unavailable.value.retryable is True
    assert unavailable.value.extra["provider_code"] == "PROVIDER_TIMEOUT"
    db_session.rollback()
    assert db_session.scalars(select(PaymentOrder)).all() == []

    # An unconfigured provider fails closed rather than guessing an outcome.
    from app.core.config import settings as live_settings

    monkeypatch.setattr(live_settings, "payment_provider", "none", raising=False)
    with pytest.raises(errors.ProviderUnavailable) as closed:
        payments._resolve_provider(None)
    assert closed.value.retryable is False
    monkeypatch.setattr(live_settings, "payment_provider", "deterministic")

    # The video seam is typed and retry-flagged the same way.
    with pytest.raises(vp.VideoProviderError) as video:
        vp.FailingVideoAdapter(retryable=True).issue_credential(
            uuid.uuid4(), "participant-1", "publish,subscribe", 300
        )
    assert video.value.retryable is True


def test_retryable_refund_failure_persists_a_pending_refund(db_session):
    start = T0 + timedelta(days=20)
    world = build_world(db_session, now=T0, slot_starts=(start,))
    booked = book_session(db_session, world, now=T0)
    result = sessions_service.cancel(
        db_session,
        booked.tutoring_session.id,
        actor_user_id=world.student_id,
        actor_role="student",
        provider=pp.FailingPaymentAdapter(retryable=True, code="PROVIDER_TIMEOUT"),
        now=start - timedelta(days=2),
    )
    db_session.commit()
    refund = db_session.scalars(select(PaymentRefund)).one()
    assert refund.status == "pending" and refund.provider_refund_ref is None
    assert refund.succeeded_order_id is None  # the marker stays clear
    assert result.refund_assessment.decision == "full_refund"
    assert {r.kind for r in outbox_rows(db_session)} >= {"refund_issued"}


def test_non_retryable_refund_failure_aborts_the_cancellation(db_session):
    start = T0 + timedelta(days=20)
    world = build_world(db_session, now=T0, slot_starts=(start,))
    booked = book_session(db_session, world, now=T0)
    with pytest.raises(errors.ProviderUnavailable) as fatal:
        sessions_service.cancel(
            db_session,
            booked.tutoring_session.id,
            actor_user_id=world.student_id,
            actor_role="student",
            provider=pp.FailingPaymentAdapter(retryable=False, code="PROVIDER_REJECTED"),
            now=start - timedelta(days=2),
        )
    assert fatal.value.retryable is False
    db_session.rollback()
    assert db_session.scalars(select(PaymentRefund)).all() == []
    assert db_session.scalars(select(SessionCancellation)).all() == []
    assert db_session.get(TutoringSession, booked.tutoring_session.id).status == "confirmed"


def test_commit_failure_leaves_no_partial_write_and_no_outbox_side_effect(
    db_session, world
):
    hold = place_hold(db_session, world, now=T0)
    adapter, order = open_order(db_session, world, hold, now=T0)
    db_session.commit()  # the hold + order are durable

    dispatcher = outbox_relay.CapturingDispatcher()
    outcome = deliver_paid_event(db_session, adapter, order, now=T0)
    intents = list(outcome.intents)
    assert intents and dispatcher.attempts == 0  # nothing dispatched inside the tx

    with failing_commit(db_session):
        with pytest.raises(RuntimeError):
            db_session.commit()
    db_session.rollback()

    assert db_session.scalars(select(TutoringSession)).all() == []
    assert db_session.scalars(select(PaymentEvent)).all() == []
    assert outbox_rows(db_session) == []
    assert db_session.get(BookingHold, hold.id).status == "active"
    assert db_session.get(TutorAvailabilitySlot, world.slot_id).status == "held"
    assert db_session.get(PaymentOrder, order.id).status == "created"
    # The intents point at rows that never existed: dispatch is a no-op.
    assert [outbox_relay.run_delivery(db_session, i, dispatcher) for i in intents] == [
        False for _ in intents
    ]
    assert dispatcher.delivered == [] and dispatcher.attempts == 0


def test_dispatch_happens_only_after_commit(db_session, world):
    hold = place_hold(db_session, world, now=T0)
    adapter, order = open_order(db_session, world, hold, now=T0)
    dispatcher = outbox_relay.CapturingDispatcher()
    outcome = deliver_paid_event(db_session, adapter, order, now=T0)

    # Pre-commit: rows are pending, the dispatcher has not been called.
    assert {r.status for r in outbox_rows(db_session)} == {"pending"}
    assert dispatcher.attempts == 0

    assert commit_and_dispatch(db_session, outcome.intents, dispatcher) == [True, True]
    assert {kind for kind, _agg, _payload in dispatcher.delivered} == {
        "booking_confirmed",
        "payment_captured",
    }
    assert {r.status for r in outbox_rows(db_session)} == {"sent"}
    assert all(r.delivered_at is not None for r in outbox_rows(db_session))


# --------------------------------------------------------------------------- #
# J1 — privacy canaries
# --------------------------------------------------------------------------- #

PAN = "4111111111111111"
CVV = "123"
PAYMENT_OTP = "654321"
SDP = "v=0\r\no=- 4611731400430051336 2 IN IP4 127.0.0.1\r\ns=-"
ICE = "candidate:842163049 1 udp 1677729535 192.0.2.1 54321 typ srflx"
DEVICE_LABEL = "MacBook Pro Microphone (Built-in)"


def _every_persisted_value(session: Session) -> str:
    """Every TEXT/JSON value in the database, as one scannable blob.

    Restricted to ``str`` / ``dict`` / ``list`` values on purpose: those are the
    only shapes a canary could be smuggled in (a ``Uuid`` or ``DateTime`` column
    cannot hold "4111111111111111"), and scanning UUID/timestamp reprs as text
    would make a 3-digit CVV canary collide with random hex by chance.
    """
    chunks: list[str] = []
    for table in Base.metadata.sorted_tables:
        for row in session.execute(select(table)).mappings():
            for column, value in row.items():
                if isinstance(value, (str, dict, list)):
                    chunks.append(f"{table.name}.{column}={value!r}")
    return "\n".join(chunks)


def test_no_card_media_or_token_canary_can_reach_storage_logs_or_payloads(
    db_session, world, caplog
):
    caplog.set_level(logging.DEBUG)

    # (1) The provider seams REFUSE card data and media-plane data outright.
    for value in (PAN, CVV, PAYMENT_OTP):
        with pytest.raises(pp.PaymentProviderError) as refused:
            pp._reject_card_data(value)
        assert refused.value.code == "CARD_DATA_REFUSED"
        assert value not in str(refused.value)
    for key, value in (
        ("sdp", SDP), ("ice_candidate", ICE), ("device_label", DEVICE_LABEL),
    ):
        with pytest.raises(vp.VideoProviderError) as media:
            vp._reject_media_payload({"room": "r", key: value})
        assert media.value.code == "MEDIA_DATA_REFUSED"
        assert value not in str(media.value)

    # (2) A raw join token is never persistable: only its SHA-256 hash is, and
    #     the credential's repr redacts the token.
    credential = vp.DeterministicVideoAdapter().issue_credential(
        uuid.uuid4(), "participant-abc", "publish,subscribe", 300
    )
    assert credential.raw_token.startswith("join_")
    assert credential.token_hash == vp.hash_token(credential.raw_token)
    assert len(credential.token_hash) == 64
    assert credential.raw_token not in repr(credential)
    assert "[redacted]" in repr(credential)

    # (3) The outbox refuses a forbidden key OR a credential/PAN-shaped value.
    for payload in (
        {"pan": PAN}, {"cvv": CVV}, {"otp": PAYMENT_OTP}, {"sdp": SDP},
        {"ice_candidate": ICE}, {"device_label": DEVICE_LABEL},
        {"join_token": credential.raw_token}, {"note": PAN},
        {"credential": credential.raw_token},
    ):
        with pytest.raises(errors.ValidationError):
            outbox_relay.assert_payload_safe(payload)

    # (4) A full, real booking flow persists none of the canaries anywhere.
    booked = book_session(db_session, world, now=T0)
    sessions_service.cancel(
        db_session,
        booked.tutoring_session.id,
        actor_user_id=world.student_id,
        actor_role="student",
        now=T0,
    )
    dispatcher = outbox_relay.CapturingDispatcher()
    db_session.commit()
    outbox_relay.relay_pending(db_session, dispatcher)

    blob = _every_persisted_value(db_session)
    logs = "\n".join(record.getMessage() for record in caplog.records)
    payload_blob = repr([payload for _k, _a, payload in dispatcher.delivered])
    for canary in (PAN, CVV, PAYMENT_OTP, SDP, ICE, DEVICE_LABEL, credential.raw_token):
        assert canary not in blob
        assert canary not in logs
        assert canary not in payload_blob
    # Only issuer display crumbs are stored for the card.
    order = db_session.get(PaymentOrder, booked.order.id)
    assert (order.brand, order.masked_last4) == ("TESTCARD", "4242")
    assert order.masked_last4 is not None and len(order.masked_last4) == 4
