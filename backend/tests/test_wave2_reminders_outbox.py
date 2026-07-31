"""Wave 2 reminder scheduling + durable outbox proofs (SAATHI-123/127, matrix G1).

Frozen decisions proved here
----------------------------
* reminders exist at exactly 7d / 1d / 3h before ``start_utc``, at the correct
  instants, and ``settings.reminder_offsets`` selects which of them a deployment
  schedules (an unknown offset is a configuration error, never a silent skip);
* an offset whose instant is already in the past AT SCHEDULING TIME is not
  scheduled — the boundary (``scheduled_for == now``) is asserted too;
* a reschedule REVOKES the stale jobs (the rows survive as ``revoked``, they are
  not silently deleted) and schedules fresh ones off the new start; a cancel
  revokes every pending job; revocation is idempotent;
* delivery is through the DURABLE OUTBOX: the row is written in the SAME
  transaction as the state change, nothing is dispatched before that transaction
  commits, and a failed commit leaves NO outbox row AND no claimed job;
* a retry of a failed dispatch produces no duplicate side effect, repeated relay
  passes are idempotent, and an exhausted row is dead-lettered rather than
  retried forever;
* a reminder payload carries ids, a code and instants only — no name, email,
  mobile or token.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings as live_settings
from app.models.wave2 import REMINDER_OFFSETS, SessionReminderJob, TutoringOutbox
from app.services.tutoring import attendance as attendance_service
from app.services.tutoring import errors, outbox_relay, reminders
from app.services.tutoring import sessions as sessions_service
from tests.wave2_helpers import (
    T0,
    book_session,
    build_world,
    commit_and_dispatch,
    failing_commit,
    outbox_rows,
)

pytestmark = pytest.mark.usefixtures("db_session")

ALL_OFFSETS = ("7d", "1d", "3h")


@pytest.fixture()
def world(db_session: Session):
    return build_world(db_session, now=T0)


def _start(sess):
    return sessions_service._aware(sess.start_utc)


def _jobs(db_session, sess, status: str | None = None):
    """(offset_kind, scheduled_for) -> status, as aware instants."""
    rows = reminders.list_jobs(
        db_session, sess.id, statuses=(status,) if status else None
    )
    return {
        (row.offset_kind, reminders._aware(row.scheduled_for)): row.status
        for row in rows
    }


def _expected(start, offsets=ALL_OFFSETS):
    return {(kind, start - reminders.OFFSET_DELTAS[kind]) for kind in offsets}


def _reminder_rows(db_session):
    return outbox_rows(db_session, kind="session_reminder")


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #


def test_offsets_are_exactly_7d_1d_3h(db_session, world):
    assert REMINDER_OFFSETS == ALL_OFFSETS
    assert reminders.OFFSET_DELTAS == {
        "7d": timedelta(days=7),
        "1d": timedelta(days=1),
        "3h": timedelta(hours=3),
    }
    assert reminders.configured_offsets() == ALL_OFFSETS

    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    start = _start(sess)

    assert set(_jobs(db_session, sess)) == _expected(start)
    assert set(_jobs(db_session, sess).values()) == {"scheduled"}
    confirmed = [
        row for row in outbox_rows(db_session) if row.kind == "booking_confirmed"
    ]
    assert confirmed[0].payload_json["reminder_jobs"] == 3


def test_scheduling_is_idempotent(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    replay = reminders.schedule_for_session(db_session, sess, now=T0)
    db_session.commit()
    assert len(replay) == 3
    assert len(db_session.scalars(select(SessionReminderJob)).all()) == 3
    assert set(_jobs(db_session, sess)) == _expected(_start(sess))


@pytest.mark.parametrize(
    ("delta", "expected_offsets"),
    [
        (timedelta(days=7), ("1d", "3h")),  # 7d instant == now: already due
        (timedelta(days=2, hours=1), ("1d", "3h")),  # 7d instant is in the past
        (timedelta(hours=4), ("3h",)),  # only the 3h reminder survives
    ],
    ids=["exactly_7d_boundary", "two_days_out", "four_hours_out"],
)
def test_an_offset_already_due_at_scheduling_time_is_not_scheduled(
    db_session, delta, expected_offsets
):
    """FROZEN: "a reminder that is already due is not a reminder"."""
    start = T0 + delta
    world = build_world(db_session, now=T0, slot_starts=(start,))
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session

    assert set(_jobs(db_session, sess)) == _expected(_start(sess), expected_offsets)
    # The skipped offsets left NO row at all (not a row in some other status).
    assert len(db_session.scalars(select(SessionReminderJob)).all()) == len(
        expected_offsets
    )


def test_configured_offsets_select_which_reminders_are_scheduled(
    db_session, world, monkeypatch
):
    monkeypatch.setattr(live_settings, "reminder_offsets", ["3h", "7d"])
    # Canonical order regardless of how the deployment lists them.
    assert reminders.configured_offsets() == ("7d", "3h")
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    assert set(_jobs(db_session, sess)) == _expected(_start(sess), ("7d", "3h"))


def test_an_unknown_or_empty_offset_configuration_is_an_error(monkeypatch):
    with pytest.raises(errors.ValidationError) as unknown:
        reminders.parse_offset("2h")
    assert unknown.value.extra["field"] == "reminder_offsets"
    assert unknown.value.extra["allowed"] == list(REMINDER_OFFSETS)

    monkeypatch.setattr(live_settings, "reminder_offsets", [])
    with pytest.raises(errors.ValidationError):
        reminders.configured_offsets()
    monkeypatch.setattr(live_settings, "reminder_offsets", ["2h"])
    with pytest.raises(errors.ValidationError):
        reminders.configured_offsets()


def test_a_non_remindable_session_gets_no_jobs(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    sessions_service.cancel(
        db_session, sess.id, actor_user_id=world.student_id,
        actor_role="student", now=T0,
    )
    db_session.commit()
    assert reminders.schedule_for_session(db_session, sess, now=T0) == []
    assert reminders.list_jobs(db_session, sess.id, statuses=("scheduled",)) == ()


# --------------------------------------------------------------------------- #
# Revocation on reschedule / cancel
# --------------------------------------------------------------------------- #


def test_reschedule_revokes_the_stale_jobs_and_schedules_new_ones(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    old_expected = _expected(_start(sess))
    assert set(_jobs(db_session, sess, "scheduled")) == old_expected

    result = sessions_service.reschedule(
        db_session,
        sess.id,
        new_slot_id=world.slots[1],
        actor_user_id=world.student_id,
        actor_role="student",
        now=T0,
    )
    db_session.commit()
    new_expected = _expected(_start(result.tutoring_session))
    assert new_expected != old_expected

    jobs = _jobs(db_session, sess)
    # The stale rows are REVOKED, not deleted: the trail survives for audit.
    assert {key: jobs[key] for key in old_expected} == dict.fromkeys(
        old_expected, "revoked"
    )
    assert {key: jobs[key] for key in new_expected} == dict.fromkeys(
        new_expected, "scheduled"
    )
    assert len(jobs) == 6
    assert (result.reminders_revoked, result.reminders_scheduled) == (3, 3)


def test_rescheduling_back_onto_an_abandoned_instant_reinstates_its_job(
    db_session, world
):
    """Regression: A -> B -> A must leave the A reminders ACTUALLY scheduled.

    ``schedule_for_session`` reuses the existing row for an
    (session, offset, instant) triple. When that row had been REVOKED by the
    first reschedule, returning it unchanged reported "3 reminders scheduled"
    while every job stayed ``revoked`` — the session would never notify.
    """
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    original = _expected(_start(sess))

    moved = sessions_service.reschedule(
        db_session, sess.id, new_slot_id=world.slots[1],
        actor_user_id=world.student_id, actor_role="student", now=T0,
    )
    db_session.commit()
    detour = _expected(_start(moved.tutoring_session))
    assert set(_jobs(db_session, sess, "revoked")) == original
    assert set(_jobs(db_session, sess, "scheduled")) == detour

    back = sessions_service.reschedule(
        db_session, sess.id, new_slot_id=world.slots[0],
        actor_user_id=world.student_id, actor_role="student", now=T0,
    )
    db_session.commit()

    assert sessions_service._aware(back.tutoring_session.start_utc) == _start(sess)
    assert back.reminders_scheduled == 3
    # The REPORTED count and the OBSERVABLE state agree: the original instants
    # are live again and only the abandoned detour stays revoked.
    assert set(_jobs(db_session, sess, "scheduled")) == original
    assert set(_jobs(db_session, sess, "revoked")) == detour
    # No duplicate row was created for the reinstated instants.
    assert len(db_session.scalars(select(SessionReminderJob)).all()) == 6
    # ...and the reinstated jobs really do become due and dispatch.
    batch = reminders.enqueue_due(db_session, now=_start(sess))
    db_session.commit()
    assert batch.enqueued == 3


def test_a_sent_reminder_is_never_reinstated_by_a_reschedule(db_session, world):
    """A delivered reminder for an instant must not be resurrected and re-sent."""
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    start = _start(sess)
    due_at = start - reminders.OFFSET_DELTAS["7d"]
    reminders.enqueue_due(db_session, now=due_at)  # the 7d reminder is delivered
    db_session.commit()
    assert _jobs(db_session, sess)[("7d", due_at)] == "sent"

    sessions_service.reschedule(
        db_session, sess.id, new_slot_id=world.slots[1],
        actor_user_id=world.student_id, actor_role="student", now=due_at,
    )
    db_session.commit()
    sessions_service.reschedule(
        db_session, sess.id, new_slot_id=world.slots[0],
        actor_user_id=world.student_id, actor_role="student", now=due_at,
    )
    db_session.commit()

    assert _jobs(db_session, sess)[("7d", due_at)] == "sent"
    assert len(_reminder_rows(db_session)) == 1  # exactly one 7d delivery, ever


def test_cancel_revokes_every_pending_job(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    result = sessions_service.cancel(
        db_session, sess.id, actor_user_id=world.student_id,
        actor_role="student", now=T0,
    )
    db_session.commit()
    assert result.reminders_revoked == 3
    assert reminders.list_jobs(db_session, sess.id, statuses=("scheduled",)) == ()
    assert set(_jobs(db_session, sess).values()) == {"revoked"}
    # Revocation is idempotent: a second pass revokes nothing.
    assert reminders.revoke_for_session(db_session, sess.id, now=T0) == 0
    db_session.commit()


def test_revocation_can_target_specific_offsets(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    assert reminders.revoke_for_session(
        db_session, sess.id, now=T0, offset_kinds=("7d",)
    ) == 1
    db_session.commit()
    assert {kind for kind, _at in _jobs(db_session, sess, "scheduled")} == {"1d", "3h"}
    assert {kind for kind, _at in _jobs(db_session, sess, "revoked")} == {"7d"}


# --------------------------------------------------------------------------- #
# Durable outbox: same transaction, dispatch strictly after commit
# --------------------------------------------------------------------------- #


def test_due_job_writes_its_outbox_row_in_the_same_transaction(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    due_at = _start(sess) - reminders.OFFSET_DELTAS["7d"]  # exactly the 7d instant
    dispatcher = outbox_relay.CapturingDispatcher()

    batch = reminders.enqueue_due(db_session, now=due_at)
    # Pre-commit: the job claim AND the outbox row are visible in this
    # transaction only, and nothing has been dispatched.
    assert (batch.enqueued, batch.revoked) == (1, 0)
    assert [i.kind for i in batch.intents] == ["session_reminder"]
    rows = _reminder_rows(db_session)
    assert [(r.kind, r.status, r.attempts) for r in rows] == [
        ("session_reminder", "pending", 0)
    ]
    assert _jobs(db_session, sess)[("7d", due_at)] == "sent"
    assert dispatcher.attempts == 0 and dispatcher.delivered == []

    # Dispatch happens strictly AFTER the commit.
    assert commit_and_dispatch(db_session, batch.intents, dispatcher, now=due_at) == [
        True
    ]
    assert [kind for kind, _agg, _p in dispatcher.delivered] == ["session_reminder"]
    assert [r.status for r in _reminder_rows(db_session)] == ["sent"]
    assert _reminder_rows(db_session)[0].delivered_at is not None


def test_a_failed_commit_leaves_no_outbox_row_and_no_claimed_job(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    due_at = _start(sess) - reminders.OFFSET_DELTAS["7d"]
    dispatcher = outbox_relay.CapturingDispatcher()

    batch = reminders.enqueue_due(db_session, now=due_at)
    assert batch.enqueued == 1 and len(_reminder_rows(db_session)) == 1

    with failing_commit(db_session):
        with pytest.raises(RuntimeError):
            db_session.commit()
    db_session.rollback()

    # Neither the state change nor its outbox row survived.
    assert _reminder_rows(db_session) == []
    assert _jobs(db_session, sess)[("7d", due_at)] == "scheduled"
    # The intent points at a row that never existed: dispatch is a no-op.
    assert [
        outbox_relay.run_delivery(db_session, i, dispatcher, now=due_at)
        for i in batch.intents
    ] == [False]
    assert dispatcher.attempts == 0 and dispatcher.delivered == []


def test_retry_of_a_failed_dispatch_produces_no_duplicate_side_effect(
    db_session, world
):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    due_at = _start(sess) - reminders.OFFSET_DELTAS["7d"]
    batch = reminders.enqueue_due(db_session, now=due_at)
    db_session.commit()
    intent = batch.intents[0]
    dispatcher = outbox_relay.CapturingDispatcher(fail_times=1)

    # First attempt fails: the row is retryable-'failed', nothing was delivered.
    assert outbox_relay.run_delivery(db_session, intent, dispatcher, now=due_at) is False
    row = db_session.get(TutoringOutbox, intent.outbox_id)
    assert (row.status, row.attempts, row.last_error) == ("failed", 1, "transient")
    assert row.delivered_at is None and dispatcher.delivered == []

    # The durable relay finishes the promise exactly once.
    report = outbox_relay.relay_pending(
        db_session, dispatcher, kinds=("session_reminder",), now=due_at
    )
    assert (report.claimed, report.sent, report.failed) == (1, 1, 0)
    assert len(dispatcher.delivered) == 1
    assert db_session.get(TutoringOutbox, intent.outbox_id).status == "sent"

    # Retrying the relay AND the single-intent delivery cannot deliver twice.
    again = outbox_relay.relay_pending(
        db_session, dispatcher, kinds=("session_reminder",), now=due_at
    )
    assert (again.claimed, again.sent) == (0, 0)
    assert outbox_relay.run_delivery(db_session, intent, dispatcher, now=due_at) is True
    assert len(dispatcher.delivered) == 1
    assert dispatcher.attempts == 2  # one failure + one success, never a third


def test_an_exhausted_outbox_row_is_dead_lettered_not_retried_forever(
    db_session, world
):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    due_at = _start(sess) - reminders.OFFSET_DELTAS["7d"]
    reminders.enqueue_due(db_session, now=due_at)
    db_session.commit()
    dispatcher = outbox_relay.CapturingDispatcher(fail_times=99)

    first = outbox_relay.relay_pending(
        db_session, dispatcher, kinds=("session_reminder",), max_attempts=2, now=due_at
    )
    assert (first.failed, first.dead_lettered) == (1, 0)
    second = outbox_relay.relay_pending(
        db_session, dispatcher, kinds=("session_reminder",), max_attempts=2, now=due_at
    )
    assert (second.failed, second.dead_lettered) == (0, 1)
    assert _reminder_rows(db_session)[0].status == "void"
    third = outbox_relay.relay_pending(
        db_session, dispatcher, kinds=("session_reminder",), max_attempts=2, now=due_at
    )
    assert (third.claimed, third.sent, third.dead_lettered) == (0, 0, 0)
    assert dispatcher.attempts == 2
    assert dispatcher.delivered == []


def test_due_job_selection_is_idempotent_under_repeated_relay_runs(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    at_start = _start(sess)  # every offset instant has passed

    assert {j.offset_kind for j in reminders.due_jobs(db_session, now=at_start)} == set(
        ALL_OFFSETS
    )
    first = reminders.enqueue_due(db_session, now=at_start)
    db_session.commit()
    assert (first.enqueued, first.revoked) == (3, 0)
    assert len(_reminder_rows(db_session)) == 3
    assert set(_jobs(db_session, sess).values()) == {"sent"}

    # A second pass finds nothing due and writes no second row.
    second = reminders.enqueue_due(db_session, now=at_start)
    db_session.commit()
    assert (second.enqueued, second.revoked) == (0, 0)
    assert second.intents == []
    assert reminders.due_jobs(db_session, now=at_start) == ()
    assert len(_reminder_rows(db_session)) == 3

    dispatcher = outbox_relay.CapturingDispatcher()
    run_one = outbox_relay.relay_pending(
        db_session, dispatcher, kinds=("session_reminder",), now=at_start
    )
    run_two = outbox_relay.relay_pending(
        db_session, dispatcher, kinds=("session_reminder",), now=at_start
    )
    assert (run_one.claimed, run_one.sent) == (3, 3)
    assert (run_two.claimed, run_two.sent) == (0, 0)
    assert len(dispatcher.delivered) == 3
    assert {r.status for r in _reminder_rows(db_session)} == {"sent"}


def test_a_job_for_a_no_longer_remindable_session_is_revoked_not_enqueued(
    db_session, world
):
    """Documented rule: a completed/cancelled session's due job is REVOKED."""
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = sessions_service._aware(sess.end_utc) + timedelta(minutes=5)
    attendance_service.record(
        db_session, sess.id, actor_user_id=world.tutor_user_id,
        actor_role="tutor", now=after_end,
    )
    db_session.commit()
    assert db_session.get(type(sess), sess.id).status == "completed"
    # Completion does not itself revoke reminders, so the jobs are still due...
    assert len(reminders.due_jobs(db_session, now=after_end)) == 3

    batch = reminders.enqueue_due(db_session, now=after_end)
    db_session.commit()
    assert (batch.enqueued, batch.revoked) == (0, 3)
    assert batch.intents == []
    assert _reminder_rows(db_session) == []
    assert set(_jobs(db_session, sess).values()) == {"revoked"}


def test_due_and_batch_limits_are_validated(db_session):
    for limit in (0, -1, 501):
        with pytest.raises(errors.ValidationError):
            reminders.due_jobs(db_session, now=T0, limit=limit)
        with pytest.raises(errors.ValidationError):
            reminders.enqueue_due(db_session, now=T0, limit=limit)


# --------------------------------------------------------------------------- #
# Privacy of the reminder payload (J1)
# --------------------------------------------------------------------------- #


def test_reminder_payload_carries_ids_codes_and_instants_only(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    at_start = _start(sess)
    batch = reminders.enqueue_due(db_session, now=at_start)
    dispatcher = outbox_relay.CapturingDispatcher()
    commit_and_dispatch(db_session, batch.intents, dispatcher, now=at_start)

    payloads = [payload for _k, _a, payload in dispatcher.delivered]
    assert len(payloads) == 3
    for payload in payloads:
        assert set(payload) == {
            "session_id", "offset_kind", "start_utc", "iana_timezone",
        }
        assert payload["session_id"] == str(sess.id)
        assert payload["offset_kind"] in ALL_OFFSETS
        assert payload["start_utc"] == at_start.isoformat()
        assert payload["iana_timezone"] == "Asia/Kolkata"
        # The privacy guard agrees, and no actor identity is present.
        outbox_relay.assert_payload_safe(payload)
        blob = repr(payload)
        assert "Meera" not in blob and "@" not in blob
        for actor in (world.student_id, world.tutor_user_id, world.admin_id):
            assert str(actor) not in blob
