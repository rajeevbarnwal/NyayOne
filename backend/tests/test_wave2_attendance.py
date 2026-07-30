"""Wave 2 attendance / completion proofs (SAATHI-127 P2, matrix D4 + D5).

Every test drives the REAL services against a real (SQLite) database through
``tests.wave2_helpers``: the session under test is always produced by
hold -> order -> VERIFIED paid webhook, never inserted by hand.

Frozen decisions proved here
----------------------------
* attendance/completion may be recorded ONLY AFTER the scheduled end — the
  boundary is asserted from BOTH sides (one second early is refused, exactly at
  ``end_utc`` is allowed);
* a TUTOR or an ADMIN records it; a STUDENT may not, and only an ADMIN may
  resolve a dispute;
* the student then CONFIRMS or DISPUTES, and an admin RESOLVES a dispute;
* exactly ONE attendance row per session (service refusal AND the database
  UNIQUE constraint);
* the optimistic ``version`` rejects a stale write;
* illegal state transitions are refused by the service, not just by the DB
  domain CHECK;
* reads/writes are cross-user isolated and non-enumerating (a foreign session is
  reported exactly like an unknown one).
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.wave2 import (
    ATTENDANCE_RESOLUTIONS,
    BookingEvent,
    SessionAttendance,
    TutoringSession,
)
from app.services.tutoring import attendance as attendance_service
from app.services.tutoring import errors
from app.services.tutoring import sessions as sessions_service
from tests.wave2_helpers import (
    T0,
    audit_actions,
    audit_rows,
    book_session,
    build_world,
    outbox_rows,
)

pytestmark = pytest.mark.usefixtures("db_session")


@pytest.fixture()
def world(db_session: Session):
    return build_world(db_session, now=T0)


def _end(sess) -> object:
    return sessions_service._aware(sess.end_utc)


def _after_end(sess, minutes: int = 5):
    return _end(sess) + timedelta(minutes=minutes)


# --------------------------------------------------------------------------- #
# D4 — record after the scheduled end
# --------------------------------------------------------------------------- #


def test_tutor_records_after_end_then_student_confirms(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = _after_end(sess)

    recorded = attendance_service.record(
        db_session,
        sess.id,
        actor_user_id=world.tutor_user_id,
        actor_role="tutor",
        now=after_end,
    )
    db_session.commit()

    row = recorded.attendance
    assert row.state == "recorded"
    assert row.recorded_by_role == "tutor"
    assert sessions_service._aware(row.recorded_at) == after_end
    assert row.version == 1
    assert (row.confirmed_at, row.disputed_at, row.resolved_at, row.resolution) == (
        None, None, None, None,
    )
    # Recording COMPLETES the session and writes the history + booking event.
    assert db_session.get(TutoringSession, sess.id).status == "completed"
    assert ("confirmed", "completed") in {
        (h.from_status, h.to_status)
        for h in sessions_service.status_history(db_session, sess.id)
    }
    assert "session_completed" in {
        row_.kind for row_ in db_session.scalars(select(BookingEvent)).all()
    }
    # The outbox row is written in the same transaction and is still PENDING.
    assert ("attendance_recorded", "pending") in {
        (r.kind, r.status) for r in outbox_rows(db_session)
    }
    assert [i.kind for i in recorded.intents] == ["attendance_recorded"]

    confirmed = attendance_service.confirm(
        db_session, sess.id, actor_user_id=world.student_id, now=after_end
    )
    db_session.commit()
    assert confirmed.attendance.state == "confirmed"
    assert confirmed.attendance.version == 2
    assert sessions_service._aware(confirmed.attendance.confirmed_at) == after_end
    assert confirmed.intents == []  # a confirmation notifies nobody
    assert "confirmed" in attendance_service.REVIEWABLE_STATES

    actions = set(audit_actions(db_session))
    assert {"tutoring.attendance.recorded", "tutoring.attendance.confirmed"} <= actions
    audited = audit_rows(db_session, "tutoring.attendance.recorded")[0]
    assert audited.actor_role == "tutor"
    assert audited.after_state["recorded_by_role"] == "tutor"


def test_admin_may_also_record_attendance(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    result = attendance_service.record(
        db_session,
        sess.id,
        actor_user_id=world.admin_id,
        actor_role="admin",
        now=_after_end(sess),
    )
    db_session.commit()
    assert result.attendance.recorded_by_role == "admin"
    assert attendance_service.RECORDER_ROLES == ("tutor", "admin")


def test_recording_before_the_scheduled_end_is_rejected(db_session, world):
    """FROZEN: no early completion. One second before ``end_utc`` is too early."""
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    early = _end(sess) - timedelta(seconds=1)

    with pytest.raises(errors.AttendanceTooEarly) as too_early:
        attendance_service.record(
            db_session,
            sess.id,
            actor_user_id=world.tutor_user_id,
            actor_role="tutor",
            now=early,
        )
    assert too_early.value.code == "ATTENDANCE_TOO_EARLY"
    assert too_early.value.extra["session_id"] == str(sess.id)
    db_session.rollback()

    assert db_session.scalars(select(SessionAttendance)).all() == []
    assert db_session.get(TutoringSession, sess.id).status == "confirmed"
    assert sessions_service.has_ended(sess, now=early) is False


def test_recording_exactly_at_the_scheduled_end_is_allowed(db_session, world):
    """The boundary is INCLUSIVE: ``now == end_utc`` completes the session."""
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    boundary = _end(sess)

    assert sessions_service.has_ended(sess, now=boundary) is True
    result = attendance_service.record(
        db_session,
        sess.id,
        actor_user_id=world.tutor_user_id,
        actor_role="tutor",
        now=boundary,
    )
    db_session.commit()
    assert result.attendance.state == "recorded"
    assert sessions_service._aware(result.attendance.recorded_at) == boundary


def test_only_a_tutor_or_an_admin_may_record(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = _after_end(sess)

    for role in ("student", "system", "root"):
        with pytest.raises(errors.Forbidden) as refused:
            attendance_service.record(
                db_session,
                sess.id,
                actor_user_id=world.student_id,
                actor_role=role,
                now=after_end,
            )
        assert refused.value.code == "FORBIDDEN"
        assert refused.value.extra["actor_role"] == role
        db_session.rollback()

    # An anonymous recorder is refused even with a permitted role.
    with pytest.raises(errors.Forbidden):
        attendance_service.record(
            db_session, sess.id, actor_user_id=None, actor_role="tutor", now=after_end
        )
    db_session.rollback()
    assert db_session.scalars(select(SessionAttendance)).all() == []


def test_recording_a_non_live_session_is_rejected(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    sessions_service.cancel(
        db_session,
        sess.id,
        actor_user_id=world.student_id,
        actor_role="student",
        now=T0,
    )
    db_session.commit()
    with pytest.raises(errors.AttendanceStateInvalid) as invalid:
        attendance_service.record(
            db_session,
            sess.id,
            actor_user_id=world.tutor_user_id,
            actor_role="tutor",
            now=_after_end(sess),
        )
    assert invalid.value.extra["status"] == "cancelled"
    db_session.rollback()
    assert db_session.scalars(select(SessionAttendance)).all() == []


# --------------------------------------------------------------------------- #
# D5 — confirm / dispute / admin resolution
# --------------------------------------------------------------------------- #


def test_student_dispute_is_resolved_by_an_admin(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = _after_end(sess)
    attendance_service.record(
        db_session,
        sess.id,
        actor_user_id=world.tutor_user_id,
        actor_role="tutor",
        now=after_end,
    )
    db_session.commit()

    disputed = attendance_service.dispute(
        db_session,
        sess.id,
        actor_user_id=world.student_id,
        reason_code="tutor_absent",
        now=after_end,
    )
    db_session.commit()
    assert disputed.attendance.state == "disputed"
    assert disputed.attendance.version == 2
    assert sessions_service._aware(disputed.attendance.disputed_at) == after_end
    assert db_session.get(TutoringSession, sess.id).status == "disputed"
    assert "disputed" not in attendance_service.REVIEWABLE_STATES

    resolved = attendance_service.resolve(
        db_session,
        sess.id,
        admin_user_id=world.admin_id,
        resolution="attended",
        now=after_end,
    )
    db_session.commit()
    assert resolved.attendance.state == "resolved"
    assert resolved.attendance.resolution == "attended"
    assert resolved.attendance.version == 3
    assert sessions_service._aware(resolved.attendance.resolved_at) == after_end
    # An admin resolution returns the session to 'completed'.
    assert db_session.get(TutoringSession, sess.id).status == "completed"
    assert "resolved" in attendance_service.REVIEWABLE_STATES

    assert {
        "tutoring.attendance.recorded",
        "tutoring.attendance.disputed",
        "tutoring.attendance.resolved",
    } <= set(audit_actions(db_session))
    history = {
        (h.from_status, h.to_status)
        for h in sessions_service.status_history(db_session, sess.id)
    }
    assert {("confirmed", "completed"), ("completed", "disputed"),
            ("disputed", "completed")} <= history
    # The dispute trail carries a CODE, never the student's narrative.
    reasons = {
        h.reason
        for h in sessions_service.status_history(db_session, sess.id)
        if h.to_status == "disputed"
    }
    assert reasons == {"tutor_absent"}


def test_a_confirmed_attendance_may_still_be_disputed_then_resolved(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = _after_end(sess)
    attendance_service.record(
        db_session, sess.id, actor_user_id=world.tutor_user_id,
        actor_role="tutor", now=after_end,
    )
    attendance_service.confirm(
        db_session, sess.id, actor_user_id=world.student_id, now=after_end
    )
    db_session.commit()

    attendance_service.dispute(
        db_session, sess.id, actor_user_id=world.student_id, now=after_end
    )
    db_session.commit()
    row = attendance_service.get_attendance(db_session, sess.id)
    assert (row.state, row.version) == ("disputed", 3)
    assert row.confirmed_at is not None  # the earlier confirmation is not erased

    attendance_service.resolve(
        db_session, sess.id, admin_user_id=world.admin_id,
        resolution="no_show_tutor", now=after_end,
    )
    db_session.commit()
    row = attendance_service.get_attendance(db_session, sess.id)
    assert (row.state, row.resolution, row.version) == ("resolved", "no_show_tutor", 4)


def test_only_an_admin_may_resolve_a_dispute(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = _after_end(sess)
    attendance_service.record(
        db_session, sess.id, actor_user_id=world.tutor_user_id,
        actor_role="tutor", now=after_end,
    )
    attendance_service.dispute(
        db_session, sess.id, actor_user_id=world.student_id, now=after_end
    )
    db_session.commit()

    for role, actor in (
        ("tutor", world.tutor_user_id),
        ("student", world.student_id),
        ("system", world.admin_id),
    ):
        with pytest.raises(errors.Forbidden) as refused:
            attendance_service.resolve(
                db_session,
                sess.id,
                admin_user_id=actor,
                resolution="attended",
                actor_role=role,
                now=after_end,
            )
        assert refused.value.extra["actor_role"] == role
        db_session.rollback()

    # A resolution must name the acting admin...
    with pytest.raises(errors.Forbidden):
        attendance_service.resolve(
            db_session, sess.id, admin_user_id=None,
            resolution="attended", now=after_end,
        )
    db_session.rollback()
    # ...and use one of the four frozen resolutions.
    with pytest.raises(errors.ValidationError) as bad:
        attendance_service.resolve(
            db_session, sess.id, admin_user_id=world.admin_id,
            resolution="whatever", now=after_end,
        )
    assert bad.value.extra["allowed"] == list(ATTENDANCE_RESOLUTIONS)
    db_session.rollback()

    row = attendance_service.get_attendance(db_session, sess.id)
    assert (row.state, row.resolution) == ("disputed", None)
    assert db_session.get(TutoringSession, sess.id).status == "disputed"


# --------------------------------------------------------------------------- #
# Isolation, uniqueness, optimistic concurrency, state machine
# --------------------------------------------------------------------------- #


def test_attendance_is_cross_user_isolated_and_non_enumerating(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = _after_end(sess)

    # Another tutor cannot record on someone else's session.
    with pytest.raises(errors.NotFound) as absent:
        attendance_service.record(
            db_session, uuid.uuid4(), actor_user_id=world.tutor_user_id,
            actor_role="tutor", now=after_end,
        )
    with pytest.raises(errors.NotFound) as foreign:
        attendance_service.record(
            db_session, sess.id, actor_user_id=world.other_tutor_user_id,
            actor_role="tutor", now=after_end,
        )
    assert foreign.value.to_dict() == absent.value.to_dict()
    db_session.rollback()

    attendance_service.record(
        db_session, sess.id, actor_user_id=world.tutor_user_id,
        actor_role="tutor", now=after_end,
    )
    db_session.commit()

    # Another student can neither confirm nor dispute it, and cannot tell the
    # difference between "not yours" and "does not exist".
    for call in (attendance_service.confirm, attendance_service.dispute):
        with pytest.raises(errors.NotFound) as unknown:
            call(db_session, uuid.uuid4(), actor_user_id=world.student_id, now=after_end)
        with pytest.raises(errors.NotFound) as other:
            call(
                db_session, sess.id,
                actor_user_id=world.other_student_id, now=after_end,
            )
        assert other.value.to_dict() == unknown.value.to_dict()
        assert other.value.message == "session not found"
        db_session.rollback()

    row = attendance_service.get_attendance(db_session, sess.id)
    assert (row.state, row.version) == ("recorded", 1)


def test_exactly_one_attendance_row_per_session(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = _after_end(sess)
    attendance_service.record(
        db_session, sess.id, actor_user_id=world.tutor_user_id,
        actor_role="tutor", now=after_end,
    )
    db_session.commit()

    # (a) the service refuses a second recording...
    with pytest.raises(errors.AttendanceStateInvalid):
        attendance_service.record(
            db_session, sess.id, actor_user_id=world.tutor_user_id,
            actor_role="tutor", now=after_end,
        )
    db_session.rollback()

    # (b) ...and the database refuses a second ROW even if a service is bypassed
    #     (uq_session_attendance_session_id).
    db_session.add(
        SessionAttendance(
            session_id=sess.id,
            state="recorded",
            recorded_by_role="admin",
            recorded_at=after_end,
            version=1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    assert len(db_session.scalars(select(SessionAttendance)).all()) == 1


def test_stale_version_is_rejected(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = _after_end(sess)
    recorded = attendance_service.record(
        db_session, sess.id, actor_user_id=world.tutor_user_id,
        actor_role="tutor", now=after_end,
    )
    db_session.commit()
    stale_version = recorded.attendance.version + 7

    with pytest.raises(errors.AttendanceStaleVersion) as stale:
        attendance_service.confirm(
            db_session, sess.id, actor_user_id=world.student_id,
            expected_version=stale_version, now=after_end,
        )
    assert stale.value.code == "ATTENDANCE_STALE_VERSION"
    assert stale.value.extra["expected_version"] == stale_version
    db_session.rollback()

    with pytest.raises(errors.AttendanceStaleVersion):
        attendance_service.dispute(
            db_session, sess.id, actor_user_id=world.student_id,
            expected_version=stale_version, now=after_end,
        )
    db_session.rollback()

    row = attendance_service.get_attendance(db_session, sess.id)
    assert (row.state, row.version) == ("recorded", 1)
    # The correct version still wins.
    attendance_service.confirm(
        db_session, sess.id, actor_user_id=world.student_id,
        expected_version=1, now=after_end,
    )
    db_session.commit()
    row = attendance_service.get_attendance(db_session, sess.id)
    assert (row.state, row.version) == ("confirmed", 2)


def test_attendance_state_machine_is_enforced_in_the_service():
    graph = attendance_service.LEGAL_STATES
    assert graph["resolved"] == ()
    for from_state, allowed in graph.items():
        row = SessionAttendance(state=from_state, version=1)
        for to_state in allowed:
            attendance_service._assert_state(row, to_state)
        for to_state in set(graph) - set(allowed):
            with pytest.raises(errors.AttendanceStateInvalid) as bad:
                attendance_service._assert_state(row, to_state)
            assert bad.value.extra["from_state"] == from_state
            assert bad.value.extra["to_state"] == to_state


def test_illegal_transitions_are_rejected_end_to_end(db_session, world):
    booked = book_session(db_session, world, now=T0)
    sess = booked.tutoring_session
    after_end = _after_end(sess)

    # Nothing recorded yet: neither confirm nor dispute nor resolve is legal.
    for call in (
        lambda: attendance_service.confirm(
            db_session, sess.id, actor_user_id=world.student_id, now=after_end),
        lambda: attendance_service.dispute(
            db_session, sess.id, actor_user_id=world.student_id, now=after_end),
    ):
        with pytest.raises(errors.AttendanceStateInvalid) as missing:
            call()
        assert missing.value.code == "ATTENDANCE_STATE_INVALID"
        assert "not been recorded" in missing.value.message
        db_session.rollback()

    attendance_service.record(
        db_session, sess.id, actor_user_id=world.tutor_user_id,
        actor_role="tutor", now=after_end,
    )
    db_session.commit()

    # recorded -> resolved is not a legal move (a dispute must come first).
    with pytest.raises(errors.AttendanceStateInvalid) as skipped:
        attendance_service.resolve(
            db_session, sess.id, admin_user_id=world.admin_id,
            resolution="attended", now=after_end,
        )
    assert skipped.value.extra["from_state"] == "recorded"
    db_session.rollback()

    attendance_service.confirm(
        db_session, sess.id, actor_user_id=world.student_id, now=after_end
    )
    db_session.commit()
    # confirmed -> confirmed is not legal either.
    with pytest.raises(errors.AttendanceStateInvalid):
        attendance_service.confirm(
            db_session, sess.id, actor_user_id=world.student_id, now=after_end
        )
    db_session.rollback()
    row = attendance_service.get_attendance(db_session, sess.id)
    assert (row.state, row.version) == ("confirmed", 2)
