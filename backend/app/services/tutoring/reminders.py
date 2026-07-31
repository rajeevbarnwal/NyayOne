"""Session reminders: 7d / 1d / 3h jobs + durable delivery (matrix G1).

Frozen decisions implemented here
---------------------------------
* Offsets are exactly ``7d``, ``1d`` and ``3h`` before ``start_utc``
  (``settings.reminder_offsets`` selects which of them a deployment schedules;
  an unknown offset is a configuration error, never a silent skip).
* A reschedule or a cancellation **REVOKES stale jobs**
  (:func:`revoke_for_session`) BEFORE new ones are scheduled, so a moved or
  cancelled session can never notify on its old schedule. Revocation is a
  status transition (``scheduled`` -> ``revoked``), not a delete, so the trail
  survives for audit.
* Delivery goes through the DURABLE OUTBOX: :func:`enqueue_due` marks a job
  ``sent`` and writes the ``tutoring_outbox`` row in the SAME transaction as the
  caller's, and the row is dispatched only AFTER that transaction commits (by
  ``outbox_relay.run_delivery`` / ``relay_pending``). Nothing here talks to a
  transport.
* An offset whose instant is already in the past at scheduling time is NOT
  scheduled (a session booked 2 days out has no 7-day reminder) — the job would
  otherwise be born due and fire immediately, which is not a reminder.

Privacy: a reminder payload carries the session id, the offset code and the UTC
instant. No name, no email, no mobile, no join token.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.wave2 import REMINDER_OFFSETS, SessionReminderJob, TutoringSession
from app.services.tutoring import outbox_relay
from app.services.tutoring.errors import ValidationError
from app.services.tutoring.outbox_relay import OutboxIntent

#: The only offsets the schema's CHECK constraint accepts, and their deltas.
OFFSET_DELTAS: dict[str, timedelta] = {
    "7d": timedelta(days=7),
    "1d": timedelta(days=1),
    "3h": timedelta(hours=3),
}
#: Statuses of a session for which reminders make sense at all.
REMINDABLE_SESSION_STATUSES = ("pending_provider", "confirmed", "rescheduled")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_offset(kind: str) -> timedelta:
    """Map an offset code to its delta, rejecting anything unknown."""
    delta = OFFSET_DELTAS.get(str(kind).strip())
    if delta is None:
        raise ValidationError(
            f"unknown reminder offset: {kind}",
            field="reminder_offsets",
            allowed=list(REMINDER_OFFSETS),
        )
    return delta


def configured_offsets() -> tuple[str, ...]:
    """Validated ``settings.reminder_offsets``, in canonical 7d/1d/3h order.

    Config is validated at startup too (``app.core.config``); re-validating here
    keeps the service honest when a test or a worker mutates settings directly.
    """
    raw = list(getattr(settings, "reminder_offsets", []) or [])
    if not raw:
        raise ValidationError(
            "reminder_offsets must not be empty", field="reminder_offsets"
        )
    for kind in raw:
        parse_offset(kind)
    return tuple(k for k in REMINDER_OFFSETS if k in {str(x).strip() for x in raw})


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #


def schedule_for_session(
    session: Session,
    sess: TutoringSession,
    *,
    now: datetime | None = None,
    offsets: tuple[str, ...] | None = None,
) -> list[SessionReminderJob]:
    """Create the reminder jobs for a session. Idempotent; does not commit.

    ``uq_session_reminder_jobs_session_offset`` makes a duplicate impossible; a
    replay simply returns the rows that already exist.
    """
    now = now or utcnow()
    start_utc = _aware(sess.start_utc)
    if start_utc is None:  # pragma: no cover - NOT NULL column
        raise ValidationError("session has no start instant", field="start_utc")
    if sess.status not in REMINDABLE_SESSION_STATUSES:
        return []
    created: list[SessionReminderJob] = []
    for kind in offsets or configured_offsets():
        scheduled_for = start_utc - parse_offset(kind)
        if scheduled_for <= now:
            continue  # a reminder that is already due is not a reminder
        existing = session.scalars(
            select(SessionReminderJob).where(
                SessionReminderJob.session_id == sess.id,
                SessionReminderJob.offset_kind == kind,
                SessionReminderJob.scheduled_for == scheduled_for,
            )
        ).first()
        if existing is not None:
            if existing.status == "revoked":
                # A reschedule can land back on an instant this session has
                # already abandoned (A -> B -> A). The row for that instant is
                # REVOKED, and returning it as-is would report "scheduled" while
                # the session silently never notifies, so REINSTATE it. A job
                # already 'sent' is deliberately left alone: the reminder for
                # that exact instant was delivered and must not be duplicated.
                session.execute(
                    sa.update(SessionReminderJob)
                    .where(
                        SessionReminderJob.id == existing.id,
                        SessionReminderJob.status == "revoked",
                    )
                    .values(status="scheduled", updated_at=now)
                )
                session.flush()
                session.refresh(existing)
            created.append(existing)
            continue
        row = SessionReminderJob(
            session_id=sess.id,
            offset_kind=kind,
            scheduled_for=scheduled_for,
            status="scheduled",
        )
        session.add(row)
        try:
            session.flush()
        except IntegrityError:  # pragma: no cover - concurrent identical insert
            session.rollback()
            raise
        created.append(row)
    return created


def revoke_for_session(
    session: Session,
    session_id: uuid.UUID,
    *,
    now: datetime | None = None,
    reason: str = "revoked",
    offset_kinds: tuple[str, ...] | None = None,
) -> int:
    """Revoke every still-``scheduled`` job for a session. Returns the count.

    One conditional statement, so it is safe under concurrency and idempotent:
    a second call revokes nothing because no ``scheduled`` rows remain.
    """
    now = now or utcnow()
    stmt = (
        sa.update(SessionReminderJob)
        .where(
            SessionReminderJob.session_id == session_id,
            SessionReminderJob.status == "scheduled",
        )
        .values(status="revoked", updated_at=now)
    )
    if offset_kinds:
        stmt = stmt.where(SessionReminderJob.offset_kind.in_(offset_kinds))
    result = session.execute(stmt)
    session.flush()
    return int(result.rowcount or 0)


def list_jobs(
    session: Session,
    session_id: uuid.UUID,
    *,
    statuses: tuple[str, ...] | None = None,
) -> tuple[SessionReminderJob, ...]:
    stmt = select(SessionReminderJob).where(
        SessionReminderJob.session_id == session_id
    )
    if statuses:
        stmt = stmt.where(SessionReminderJob.status.in_(statuses))
    return tuple(
        session.scalars(
            stmt.order_by(
                SessionReminderJob.scheduled_for.asc(), SessionReminderJob.id.asc()
            )
        ).all()
    )


# --------------------------------------------------------------------------- #
# Due-job dispatch through the outbox
# --------------------------------------------------------------------------- #


@dataclass
class ReminderBatch:
    """What one :func:`enqueue_due` pass did. ``intents`` dispatch after commit."""

    intents: list[OutboxIntent] = field(default_factory=list)
    enqueued: int = 0
    revoked: int = 0

    def as_dict(self) -> dict:
        return {"enqueued": self.enqueued, "revoked": self.revoked}


def due_jobs(
    session: Session, *, now: datetime | None = None, limit: int = 100
) -> tuple[SessionReminderJob, ...]:
    """Scheduled jobs whose instant has arrived, oldest first (total order)."""
    now = now or utcnow()
    if limit <= 0 or limit > 500:
        raise ValidationError("limit must be between 1 and 500", field="limit")
    return tuple(
        session.scalars(
            select(SessionReminderJob)
            .where(
                SessionReminderJob.status == "scheduled",
                SessionReminderJob.scheduled_for <= now,
            )
            .order_by(
                SessionReminderJob.scheduled_for.asc(), SessionReminderJob.id.asc()
            )
            .limit(limit)
        ).all()
    )


def enqueue_due(
    session: Session, *, now: datetime | None = None, limit: int = 100
) -> ReminderBatch:
    """Turn due jobs into outbox rows in the CALLER's transaction. No commit.

    Each job is claimed with a conditional ``UPDATE ... WHERE status='scheduled'``
    so a job can be enqueued at most once even with several workers ticking; the
    outbox row is written only for the claim winner, and the dispatch itself
    happens after the caller commits. A job whose session is no longer
    remindable (cancelled / completed) is REVOKED instead of enqueued.
    """
    now = now or utcnow()
    batch = ReminderBatch()
    for job in due_jobs(session, now=now, limit=limit):
        sess = session.get(TutoringSession, job.session_id)
        if (
            sess is None
            or sess.deleted_at is not None
            or sess.status not in REMINDABLE_SESSION_STATUSES
        ):
            revoked = session.execute(
                sa.update(SessionReminderJob)
                .where(
                    SessionReminderJob.id == job.id,
                    SessionReminderJob.status == "scheduled",
                )
                .values(status="revoked", updated_at=now)
            )
            batch.revoked += int(revoked.rowcount or 0)
            continue
        claimed = session.execute(
            sa.update(SessionReminderJob)
            .where(
                SessionReminderJob.id == job.id,
                SessionReminderJob.status == "scheduled",
            )
            .values(status="sent", updated_at=now)
        )
        if (claimed.rowcount or 0) != 1:  # pragma: no cover - lost the claim race
            continue
        batch.intents.append(
            outbox_relay.enqueue(
                session,
                kind="session_reminder",
                aggregate_id=sess.id,
                payload={
                    "session_id": str(sess.id),
                    "offset_kind": job.offset_kind,
                    "start_utc": _aware(sess.start_utc).isoformat(),
                    "iana_timezone": sess.iana_timezone,
                },
            )
        )
        batch.enqueued += 1
    session.flush()
    return batch
