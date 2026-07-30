"""Attendance / completion lifecycle (SAATHI-127 P2, matrix D4 + D5).

Frozen decisions implemented here
---------------------------------
* Attendance (i.e. completion) may be recorded **only AFTER the scheduled end**.
  An early completion is refused with ``ATTENDANCE_TOO_EARLY`` — the boundary is
  inclusive, so ``now == end_utc`` is allowed and one second earlier is not.
* Only a **tutor or an admin** may record it (``session_attendance``'s
  ``recorded_by_role`` CHECK lists exactly those two), and a tutor may only
  record on their OWN session. A student attempting to record gets ``FORBIDDEN``.
* The **student then confirms or disputes**; an **admin resolves** a dispute.
  Reviews are gated on this state machine (see ``reviews.assert_reviewable``).
* **One attendance row per session** (``uq_session_attendance_session_id``) with
  an integer ``version`` for optimistic concurrency: every mutation is a single
  conditional ``UPDATE ... WHERE id = :id AND version = :expected``, so a caller
  working from a stale read loses with ``ATTENDANCE_STALE_VERSION`` instead of
  overwriting someone else's decision.

State machine (enforced here; the DB only constrains the domain + provenance)::

    pending  -> recorded                (tutor/admin, after scheduled end)
    recorded -> confirmed | disputed    (student)
    confirmed-> disputed                (student, still unhappy)
    disputed -> resolved                (admin, with a resolution)

Session status follows along: ``recorded`` completes the session, a dispute moves
it to ``disputed``, and an admin resolution returns it to ``completed``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.wave2 import (
    ATTENDANCE_RESOLUTIONS,
    SessionAttendance,
    TutoringSession,
    TutorProfile,
)
from app.services.audit_service import record_audit_event
from app.services.tutoring import outbox_relay, sessions as sessions_service
from app.services.tutoring.errors import (
    AttendanceStaleVersion,
    AttendanceStateInvalid,
    AttendanceTooEarly,
    Forbidden,
    NotFound,
    ValidationError,
)
from app.services.tutoring.outbox_relay import OutboxIntent

#: Only these roles may RECORD attendance (mirrors the DB CHECK).
RECORDER_ROLES = ("tutor", "admin")
#: Attendance states from which a review may be written (see reviews.py).
REVIEWABLE_STATES = ("confirmed", "resolved")
#: Legal attendance state moves.
LEGAL_STATES: dict[str, tuple[str, ...]] = {
    "pending": ("recorded",),
    "recorded": ("confirmed", "disputed"),
    "confirmed": ("disputed",),
    "disputed": ("resolved",),
    "resolved": (),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AttendanceMutation:
    """Result of one attendance transition. ``intents`` dispatch after commit."""

    attendance: SessionAttendance
    tutoring_session: TutoringSession
    intents: list[OutboxIntent] = field(default_factory=list)


def get_attendance(
    session: Session, session_id: uuid.UUID
) -> SessionAttendance | None:
    return session.scalars(
        select(SessionAttendance).where(SessionAttendance.session_id == session_id)
    ).first()


def _require(session: Session, session_id: uuid.UUID) -> SessionAttendance:
    row = get_attendance(session, session_id)
    if row is None:
        raise AttendanceStateInvalid(
            "attendance has not been recorded yet", session_id=str(session_id)
        )
    return row


def _assert_state(row: SessionAttendance, to_state: str) -> None:
    allowed = LEGAL_STATES.get(row.state, ())
    if to_state not in allowed:
        raise AttendanceStateInvalid(
            "illegal attendance state transition",
            from_state=row.state,
            to_state=to_state,
            allowed=list(allowed),
        )


def _bump(
    session: Session,
    row: SessionAttendance,
    *,
    expected_version: int | None,
    values: dict,
) -> SessionAttendance:
    """Apply one optimistic-locked update to the attendance row."""
    expected = row.version if expected_version is None else int(expected_version)
    result = session.execute(
        sa.update(SessionAttendance)
        .where(
            SessionAttendance.id == row.id, SessionAttendance.version == expected
        )
        .values(version=expected + 1, **values)
    )
    if (result.rowcount or 0) != 1:
        raise AttendanceStaleVersion(
            "attendance was modified by someone else",
            attendance_id=str(row.id),
            expected_version=expected,
        )
    session.flush()
    session.refresh(row)
    return row


def _student(session: Session, session_id: uuid.UUID, actor_user_id: uuid.UUID):
    """Load a session the STUDENT owns, non-enumerating."""
    return sessions_service.get_session(
        session, session_id, user_id=actor_user_id, role="student"
    )


# --------------------------------------------------------------------------- #
# Record (matrix D4)
# --------------------------------------------------------------------------- #


def record(
    session: Session,
    session_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None,
    actor_role: str,
    now: datetime | None = None,
) -> AttendanceMutation:
    """Record attendance/completion. Tutor or admin only, AFTER the end. No commit."""
    now = now or utcnow()
    if actor_role not in RECORDER_ROLES:
        raise Forbidden(
            "only a tutor or an admin may record attendance", actor_role=actor_role
        )
    if actor_user_id is None:
        raise Forbidden("an actor id is required")
    sess = sessions_service.get_session(
        session, session_id, user_id=actor_user_id, role=actor_role
    )
    if actor_role == "tutor":
        tutor = session.get(TutorProfile, sess.tutor_id)
        if tutor is None or tutor.user_id != actor_user_id:  # pragma: no cover
            raise NotFound("session not found", resource="tutoring_session")
    if sess.status not in ("confirmed", "rescheduled"):
        raise AttendanceStateInvalid(
            "attendance can only be recorded for a live session", status=sess.status
        )
    if not sessions_service.has_ended(sess, now=now):
        # FROZEN: no early completion. The boundary is inclusive of end_utc.
        raise AttendanceTooEarly(
            "attendance may only be recorded after the scheduled end",
            session_id=str(sess.id),
            end_utc=sessions_service._aware(sess.end_utc).isoformat(),
        )
    existing = get_attendance(session, sess.id)
    if existing is not None:
        raise AttendanceStateInvalid(
            "attendance already exists for this session",
            attendance_id=str(existing.id),
            state=existing.state,
        )
    row = SessionAttendance(
        session_id=sess.id,
        state="recorded",
        recorded_by_role=actor_role,
        recorded_at=now,
        version=1,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:  # uq_session_attendance_session_id
        session.rollback()
        raise AttendanceStateInvalid(
            "attendance already exists for this session", session_id=str(session_id)
        ) from exc
    sessions_service.transition(
        session,
        sess,
        to_status="completed",
        actor_role=actor_role,
        now=now,
        reason="attendance_recorded",
        booking_event_kind="session_completed",
        booking_event_payload={"recorded_by_role": actor_role},
    )
    intents = [
        outbox_relay.enqueue(
            session,
            kind="attendance_recorded",
            aggregate_id=sess.id,
            payload={
                "session_id": str(sess.id),
                "state": "recorded",
                "recorded_by_role": actor_role,
            },
        )
    ]
    record_audit_event(
        session,
        action="tutoring.attendance.recorded",
        resource_type="session_attendance",
        resource_id=row.id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        after_state={
            "session_id": str(sess.id),
            "state": "recorded",
            "recorded_by_role": actor_role,
        },
    )
    session.flush()
    return AttendanceMutation(attendance=row, tutoring_session=sess, intents=intents)


# --------------------------------------------------------------------------- #
# Confirm / dispute / resolve (matrix D5)
# --------------------------------------------------------------------------- #


def confirm(
    session: Session,
    session_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    expected_version: int | None = None,
    now: datetime | None = None,
) -> AttendanceMutation:
    """The STUDENT confirms the recorded attendance. No commit."""
    now = now or utcnow()
    sess = _student(session, session_id, actor_user_id)
    row = _require(session, sess.id)
    _assert_state(row, "confirmed")
    _bump(
        session,
        row,
        expected_version=expected_version,
        values={"state": "confirmed", "confirmed_at": now, "updated_at": now},
    )
    record_audit_event(
        session,
        action="tutoring.attendance.confirmed",
        resource_type="session_attendance",
        resource_id=row.id,
        actor_user_id=actor_user_id,
        actor_role="student",
        before_state={"state": "recorded"},
        after_state={"state": "confirmed", "session_id": str(sess.id)},
    )
    session.flush()
    return AttendanceMutation(attendance=row, tutoring_session=sess)


def dispute(
    session: Session,
    session_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
    expected_version: int | None = None,
    reason_code: str | None = None,
    now: datetime | None = None,
) -> AttendanceMutation:
    """The STUDENT disputes the recorded attendance; the session becomes disputed."""
    now = now or utcnow()
    sess = _student(session, session_id, actor_user_id)
    row = _require(session, sess.id)
    _assert_state(row, "disputed")
    _bump(
        session,
        row,
        expected_version=expected_version,
        values={"state": "disputed", "disputed_at": now, "updated_at": now},
    )
    if sess.status != "disputed":
        sessions_service.transition(
            session,
            sess,
            to_status="disputed",
            actor_role="student",
            now=now,
            # Reason is a CODE, never the student's narrative.
            reason=(reason_code or "attendance_disputed")[:200],
        )
    record_audit_event(
        session,
        action="tutoring.attendance.disputed",
        resource_type="session_attendance",
        resource_id=row.id,
        actor_user_id=actor_user_id,
        actor_role="student",
        after_state={
            "state": "disputed",
            "session_id": str(sess.id),
            "reason_code": reason_code,
        },
    )
    session.flush()
    return AttendanceMutation(attendance=row, tutoring_session=sess)


def resolve(
    session: Session,
    session_id: uuid.UUID,
    *,
    admin_user_id: uuid.UUID,
    resolution: str,
    actor_role: str = "admin",
    expected_version: int | None = None,
    reason_code: str | None = None,
    now: datetime | None = None,
) -> AttendanceMutation:
    """An ADMIN resolves a dispute with one of the four allowed resolutions."""
    now = now or utcnow()
    if actor_role != "admin":
        raise Forbidden("only an admin may resolve a dispute", actor_role=actor_role)
    if admin_user_id is None:
        raise Forbidden("a resolution must name the acting admin")
    if resolution not in ATTENDANCE_RESOLUTIONS:
        raise ValidationError(
            f"unknown attendance resolution: {resolution}",
            field="resolution",
            allowed=list(ATTENDANCE_RESOLUTIONS),
        )
    sess = sessions_service.get_session(session, session_id, role="admin")
    row = _require(session, sess.id)
    _assert_state(row, "resolved")
    _bump(
        session,
        row,
        expected_version=expected_version,
        values={
            "state": "resolved",
            "resolution": resolution,
            "resolved_at": now,
            "updated_at": now,
        },
    )
    if sess.status == "disputed":
        sessions_service.transition(
            session,
            sess,
            to_status="completed",
            actor_role="admin",
            now=now,
            reason=f"resolved_{resolution}"[:200],
        )
    record_audit_event(
        session,
        action="tutoring.attendance.resolved",
        resource_type="session_attendance",
        resource_id=row.id,
        actor_user_id=admin_user_id,
        actor_role="admin",
        before_state={"state": "disputed"},
        after_state={
            "state": "resolved",
            "resolution": resolution,
            "session_id": str(sess.id),
            "reason_code": reason_code,
        },
    )
    session.flush()
    return AttendanceMutation(attendance=row, tutoring_session=sess)
