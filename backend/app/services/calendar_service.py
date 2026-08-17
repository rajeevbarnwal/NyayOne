"""Server-authoritative Wave 5 unified-calendar domain service.

All reads are owner-scoped and cross-user identifiers are deliberately
non-enumerating.  Public iCalendar bearer tokens are hashed before persistence;
the raw token exists only in the immediate creation response.
"""
from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from itertools import combinations
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, Role
from app.core.config import settings
from app.core.crypto import active_key_version, keyed_hash
from app.models.calendar import (
    CALENDAR_SOURCE_TYPES,
    CalendarConflict,
    CalendarEvent,
    CalendarEventSource,
    CalendarExportRevocation,
    CalendarExportSubscription,
    CalendarExportToken,
    CalendarReminderPreference,
    CalendarViewPreference,
)
from app.models.registration import User
from app.models.credentials import Credential, CredentialReminderJob
from app.models.wave2 import TutoringSession
from app.schemas.calendar import (
    CalendarExportOut,
    ConflictUpdate,
    ConflictListOut,
    ConflictOut,
    EventCreate,
    EventListOut,
    EventOut,
    EventPreview,
    EventUpdate,
    ReminderPreferenceListOut,
    ReminderPreferenceOut,
    ReminderPreviewOut,
    ReminderPreferenceUpdate,
    ViewPreferenceOut,
    ViewPreferenceUpdate,
)
from app.services.audit_service import record_audit_event

_IDEMPOTENCY_UNSAFE = re.compile(r"[\x00-\x20<>]")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43,160}$")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[- ]?)?[6-9]\d{9}(?!\d)")
_URL_RE = re.compile(r"(?i)\bhttps?://\S+")


@dataclass(frozen=True)
class CalendarError(Exception):
    status_code: int
    code: str
    message: str
    field: str | None = None
    current_version: int | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _safe_idempotency(value: str | None) -> str:
    cleaned = (value or "").strip()
    if not 8 <= len(cleaned) <= 200 or _IDEMPOTENCY_UNSAFE.search(cleaned):
        raise CalendarError(
            422,
            "invalid_idempotency_key",
            "A safe Idempotency-Key is required",
            "Idempotency-Key",
        )
    return cleaned


def require_student(actor: ActorContext) -> uuid.UUID:
    if not actor.is_authenticated or actor.user_id is None:
        raise CalendarError(401, "authentication_required", "Authentication required")
    if not actor.has_role(Role.STUDENT):
        raise CalendarError(403, "forbidden", "Student role required")
    return actor.user_id


def _clean_title(value: str) -> str:
    """Strip common direct identifiers from public-feed text defensively."""
    value = _EMAIL_RE.sub("[private]", value)
    value = _PHONE_RE.sub("[private]", value)
    value = _URL_RE.sub("[private]", value)
    return " ".join(value.split())[:160] or "NyayOne event"


def _safe_deep_link(value: str) -> str:
    if (
        not value.startswith("/s-")
        or any(marker in value for marker in ("?", "#", "\\", "//"))
        or len(value) > 80
    ):
        raise CalendarError(500, "calendar_source_contract_error", "Calendar source link is invalid")
    return value


def _event_stmt(owner_id: uuid.UUID, event_id: uuid.UUID | None = None):
    stmt = (
        select(CalendarEvent, CalendarEventSource)
        .join(
            CalendarEventSource,
            (CalendarEventSource.id == CalendarEvent.event_source_id)
            & (CalendarEventSource.owner_user_id == CalendarEvent.owner_user_id),
        )
        .where(
            CalendarEvent.owner_user_id == owner_id,
            CalendarEventSource.owner_user_id == owner_id,
            CalendarEvent.deleted_at.is_(None),
            CalendarEventSource.deleted_at.is_(None),
        )
    )
    return stmt.where(CalendarEvent.id == event_id) if event_id is not None else stmt


def _event_pair(session: Session, owner_id: uuid.UUID, event_id: uuid.UUID) -> tuple[CalendarEvent, CalendarEventSource]:
    row = session.execute(_event_stmt(owner_id, event_id)).one_or_none()
    if row is None:
        raise CalendarError(404, "calendar_event_not_found", "Calendar event not found")
    return row[0], row[1]


def _event_out(event: CalendarEvent, source: CalendarEventSource) -> EventOut:
    return EventOut(
        id=event.id,
        source_type=source.source_type,
        title=event.title,
        starts_at=_utc(event.starts_at),
        ends_at=_utc(event.ends_at),
        timezone=event.timezone,
        status=event.status,
        privacy_classification=event.privacy_classification,
        event_kind=event.personal_event_kind,
        source_url=_safe_deep_link(source.source_url),
        version=event.version,
        created_at=_utc(event.created_at),
        updated_at=_utc(event.updated_at),
    )


def _event_preview(event: CalendarEvent, source: CalendarEventSource) -> EventPreview:
    return EventPreview(
        id=event.id,
        source_type=source.source_type,
        title=event.title,
        starts_at=_utc(event.starts_at),
        ends_at=_utc(event.ends_at),
        timezone=event.timezone,
        status=event.status,
        event_kind=event.personal_event_kind,
        source_url=_safe_deep_link(source.source_url),
    )


def _payload_signature(payload: EventCreate) -> tuple[object, ...]:
    return (
        payload.title,
        _utc(payload.starts_at),
        _utc(payload.ends_at),
        payload.timezone,
        payload.status,
        payload.privacy_classification,
        payload.event_kind,
    )


def _upsert_imported_event(
    session: Session,
    *,
    owner_id: uuid.UUID,
    source_type: str,
    source_id: str,
    source_url: str,
    title: str,
    starts_at: datetime,
    ends_at: datetime,
    timezone_name: str,
    status: str,
) -> None:
    now = _now()
    source_url = _safe_deep_link(source_url)
    source = session.scalar(select(CalendarEventSource).where(
        CalendarEventSource.owner_user_id == owner_id,
        CalendarEventSource.source_type == source_type,
        CalendarEventSource.source_id == source_id,
    ))
    if source is None:
        source = CalendarEventSource(
            owner_user_id=owner_id,
            source_type=source_type,
            source_id=source_id,
            source_url=source_url,
            last_synced_at=now,
        )
        session.add(source)
        session.flush()
    else:
        source.source_url = source_url
        source.last_synced_at = now
        source.deleted_at = None
    event = session.scalar(select(CalendarEvent).where(
        CalendarEvent.event_source_id == source.id,
    ))
    start_utc, end_utc = _utc(starts_at), _utc(ends_at)
    zone = ZoneInfo(timezone_name)
    offset = int((start_utc.astimezone(zone).utcoffset() or timedelta()).total_seconds() // 60)
    if event is None:
        session.add(CalendarEvent(
            owner_user_id=owner_id,
            event_source_id=source.id,
            title=title,
            starts_at=start_utc,
            ends_at=end_utc,
            timezone=timezone_name,
            source_offset_minutes=offset,
            status=status,
            privacy_classification="personal",
            personal_event_kind=None,
            idempotency_key=f"aggregate:{source_type}:{source_id}",
        ))
        return
    changed = (
        event.title != title
        or _utc(event.starts_at) != start_utc
        or _utc(event.ends_at) != end_utc
        or event.timezone != timezone_name
        or event.status != status
    )
    event.title = title
    event.starts_at = start_utc
    event.ends_at = end_utc
    event.timezone = timezone_name
    event.source_offset_minutes = offset
    event.status = status
    event.privacy_classification = "personal"
    event.personal_event_kind = None
    event.deleted_at = None
    if changed:
        event.version += 1


def _reconcile_imported_sources(
    session: Session,
    *,
    owner_id: uuid.UUID,
    source_type: str,
    active_source_ids: set[str],
    source_id_prefix: str | None = None,
) -> None:
    """Soft-delete materialised rows whose authoritative upstream row vanished."""
    stmt = (
        select(CalendarEventSource, CalendarEvent)
        .outerjoin(CalendarEvent, CalendarEvent.event_source_id == CalendarEventSource.id)
        .where(
            CalendarEventSource.owner_user_id == owner_id,
            CalendarEventSource.source_type == source_type,
        )
    )
    if source_id_prefix is not None:
        stmt = stmt.where(CalendarEventSource.source_id.startswith(source_id_prefix))
    now = _now()
    for source, event in session.execute(stmt).all():
        if source.source_id in active_source_ids:
            continue
        if source.deleted_at is not None and (event is None or event.deleted_at is not None):
            continue
        source.deleted_at = now
        if event is not None:
            event.deleted_at = now
            event.version += 1


def _sync_tutoring_source(session: Session, owner_id: uuid.UUID) -> None:
    sessions = list(session.scalars(select(TutoringSession).where(
        TutoringSession.student_user_id == owner_id,
        TutoringSession.deleted_at.is_(None),
    )))
    status_map = {
        "pending_provider": "tentative",
        "completed": "done",
        "cancelled": "cancelled",
    }
    for item in sessions:
        _upsert_imported_event(
            session,
            owner_id=owner_id,
            source_type="tutoring",
            source_id=str(item.id),
            source_url="/s-35",
            title="Tutoring session",
            starts_at=item.start_utc,
            ends_at=item.end_utc,
            timezone_name=item.iana_timezone,
            status=status_map.get(item.status, "scheduled"),
        )
    _reconcile_imported_sources(
        session,
        owner_id=owner_id,
        source_type="tutoring",
        active_source_ids={str(item.id) for item in sessions},
    )


def _sync_credential_reminder_source(session: Session, owner_id: uuid.UUID) -> None:
    rows = session.execute(
        select(CredentialReminderJob, Credential)
        .join(Credential, Credential.id == CredentialReminderJob.credential_id)
        .where(
            Credential.owner_user_id == owner_id,
            Credential.deleted_at.is_(None),
            CredentialReminderJob.deleted_at.is_(None),
        )
    ).all()
    status_map = {"sent": "done", "cancelled": "cancelled", "failed": "tentative"}
    for reminder, _credential in rows:
        _upsert_imported_event(
            session,
            owner_id=owner_id,
            source_type="reminder",
            source_id=f"credential-reminder:{reminder.id}",
            source_url="/s-82",
            title="Credential renewal reminder",
            starts_at=reminder.remind_at,
            ends_at=_utc(reminder.remind_at) + timedelta(minutes=30),
            timezone_name="Asia/Kolkata",
            status=status_map.get(reminder.status, "scheduled"),
        )
    _reconcile_imported_sources(
        session,
        owner_id=owner_id,
        source_type="reminder",
        active_source_ids={f"credential-reminder:{reminder.id}" for reminder, _credential in rows},
        source_id_prefix="credential-reminder:",
    )


def sync_domain_sources(
    session: Session,
    owner_id: uuid.UUID,
    requested_source_types: set[str] | None = None,
) -> list[str]:
    """Flush real module rows without taking ownership of the caller's commit."""
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        # Python's sqlite3 legacy transaction mode does not BEGIN for a
        # SAVEPOINT. Releasing that outermost SAVEPOINT would otherwise make
        # adapter writes durable before the caller can accept the projection.
        driver_connection = connection.connection.driver_connection
        if not driver_connection.in_transaction:
            connection.exec_driver_sql("BEGIN")
    failed: list[str] = []
    for source_type, adapter in (
        ("tutoring", _sync_tutoring_source),
        ("reminder", _sync_credential_reminder_source),
    ):
        if requested_source_types is not None and source_type not in requested_source_types:
            continue
        try:
            with session.begin_nested():
                adapter(session, owner_id)
                session.flush()
        except Exception:
            failed.append(source_type)
    session.flush()
    return failed


def create_event(
    session: Session,
    actor: ActorContext,
    payload: EventCreate,
    idempotency_key: str | None,
) -> EventOut:
    owner_id = require_student(actor)
    idem = _safe_idempotency(idempotency_key)
    existing = session.execute(
        _event_stmt(owner_id).where(CalendarEvent.idempotency_key == idem)
    ).one_or_none()
    if existing is not None:
        event, source = existing[0], existing[1]
        if _payload_signature(payload) != (
            event.title,
            _utc(event.starts_at),
            _utc(event.ends_at),
            event.timezone,
            event.status,
            event.privacy_classification,
            event.personal_event_kind,
        ):
            raise CalendarError(409, "idempotency_conflict", "Idempotency-Key was reused with different data")
        return _event_out(event, source)

    try:
        now = _now()
        source = CalendarEventSource(
            owner_user_id=owner_id,
            source_type="reminder",
            source_id=uuid.uuid4().hex,
            source_url="/s-91",
            last_synced_at=now,
        )
        session.add(source)
        session.flush()
        local = payload.starts_at.astimezone(ZoneInfo(payload.timezone))
        event = CalendarEvent(
            owner_user_id=owner_id,
            event_source_id=source.id,
            title=payload.title,
            starts_at=_utc(payload.starts_at),
            ends_at=_utc(payload.ends_at),
            timezone=payload.timezone,
            source_offset_minutes=int((local.utcoffset() or timedelta()).total_seconds() // 60),
            status=payload.status,
            privacy_classification=payload.privacy_classification,
            personal_event_kind=payload.event_kind,
            idempotency_key=idem,
        )
        session.add(event)
        session.flush()
        record_audit_event(
            session,
            action="calendar_event_created",
            resource_type="calendar_event",
            resource_id=event.id,
            actor_user_id=owner_id,
            actor_role="student",
            after_state={"source_type": "reminder", "status": event.status, "privacy": event.privacy_classification},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = session.execute(
            _event_stmt(owner_id).where(CalendarEvent.idempotency_key == idem)
        ).one_or_none()
        if replay is None:
            raise
        replay_event, replay_source = replay[0], replay[1]
        if _payload_signature(payload) != (
            replay_event.title,
            _utc(replay_event.starts_at),
            _utc(replay_event.ends_at),
            replay_event.timezone,
            replay_event.status,
            replay_event.privacy_classification,
            replay_event.personal_event_kind,
        ):
            raise CalendarError(409, "idempotency_conflict", "Idempotency-Key was reused with different data")
        return _event_out(replay_event, replay_source)
    return _event_out(event, source)


def list_events(
    session: Session,
    actor: ActorContext,
    source_types: list[str] | None,
    from_date: date | None,
    to_date: date | None,
    timezone_name: str,
) -> EventListOut:
    owner_id = require_student(actor)
    if from_date and to_date and to_date < from_date:
        raise CalendarError(422, "calendar_invalid_date_range", "Invalid calendar date range", "to_date")
    zone = ZoneInfo(timezone_name)
    if source_types:
        unknown = set(source_types) - set(CALENDAR_SOURCE_TYPES)
        if unknown:
            raise CalendarError(422, "calendar_invalid_source", "Unsupported calendar source", "source_type")
    failed_sources = sync_domain_sources(
        session,
        owner_id,
        set(source_types) if source_types else None,
    )
    stmt = _event_stmt(owner_id)
    if source_types:
        stmt = stmt.where(CalendarEventSource.source_type.in_(source_types))
    if from_date:
        start = datetime.combine(from_date, time.min, zone).astimezone(timezone.utc)
        stmt = stmt.where(CalendarEvent.ends_at > start)
    if to_date:
        end = datetime.combine(to_date + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        stmt = stmt.where(CalendarEvent.starts_at < end)
    rows = session.execute(stmt.order_by(CalendarEvent.starts_at, CalendarEvent.id)).all()
    result = EventListOut(
        items=[_event_out(row[0], row[1]) for row in rows],
        total=len(rows),
        failed_sources=failed_sources,
    )
    session.commit()
    return result


def get_event(session: Session, actor: ActorContext, event_id: uuid.UUID) -> EventOut:
    owner_id = require_student(actor)
    sync_domain_sources(session, owner_id)
    event, source = _event_pair(session, owner_id, event_id)
    result = _event_out(event, source)
    session.commit()
    return result


def update_event(
    session: Session,
    actor: ActorContext,
    event_id: uuid.UUID,
    payload: EventUpdate,
) -> EventOut:
    owner_id = require_student(actor)
    row = session.execute(_event_stmt(owner_id, event_id).with_for_update()).one_or_none()
    if row is None:
        raise CalendarError(404, "calendar_event_not_found", "Calendar event not found")
    event, source = row[0], row[1]
    if event.personal_event_kind is None:
        raise CalendarError(409, "calendar_event_read_only", "Imported calendar events are read-only")
    if event.version != payload.expected_version:
        raise CalendarError(409, "calendar_stale_version", "Calendar event changed", current_version=event.version)
    before = {"status": event.status, "privacy": event.privacy_classification, "version": event.version}
    local = payload.starts_at.astimezone(ZoneInfo(payload.timezone))
    event.title = payload.title
    event.starts_at = _utc(payload.starts_at)
    event.ends_at = _utc(payload.ends_at)
    event.timezone = payload.timezone
    event.source_offset_minutes = int((local.utcoffset() or timedelta()).total_seconds() // 60)
    event.status = payload.status
    event.privacy_classification = payload.privacy_classification
    event.personal_event_kind = payload.event_kind
    event.version += 1
    source.last_synced_at = _now()
    record_audit_event(
        session,
        action="calendar_event_updated",
        resource_type="calendar_event",
        resource_id=event.id,
        actor_user_id=owner_id,
        actor_role="student",
        before_state=before,
        after_state={"status": event.status, "privacy": event.privacy_classification, "version": event.version},
    )
    session.commit()
    return _event_out(event, source)


def delete_event(session: Session, actor: ActorContext, event_id: uuid.UUID) -> None:
    """Delete an owner-created reminder; repeat/cross-user requests both return 404."""
    owner_id = require_student(actor)
    row = session.execute(_event_stmt(owner_id, event_id).with_for_update()).one_or_none()
    if row is None:
        raise CalendarError(404, "calendar_event_not_found", "Calendar event not found")
    event, source = row[0], row[1]
    if event.personal_event_kind is None:
        raise CalendarError(409, "calendar_event_read_only", "Imported calendar events are read-only")
    record_audit_event(
        session,
        action="calendar_event_deleted",
        resource_type="calendar_event",
        resource_id=event.id,
        actor_user_id=owner_id,
        actor_role="student",
        after_state={"source_type": "reminder", "version": event.version},
    )
    # Delete dependants explicitly so the local SQLite demo does not rely on
    # PRAGMA foreign_keys; PostgreSQL's CASCADE remains the final backstop.
    session.execute(delete(CalendarConflict).where(
        CalendarConflict.owner_user_id == owner_id,
        (CalendarConflict.left_event_id == event.id) | (CalendarConflict.right_event_id == event.id),
    ))
    session.delete(event)
    session.flush()
    session.delete(source)
    session.commit()


def _default_view() -> ViewPreferenceOut:
    return ViewPreferenceOut(
        view_mode="month",
        source_types=list(CALENDAR_SOURCE_TYPES),
        from_date=None,
        to_date=None,
        timezone="Asia/Kolkata",
        version=0,
        updated_at=_now(),
    )


def get_view_preferences(session: Session, actor: ActorContext) -> ViewPreferenceOut:
    owner_id = require_student(actor)
    row = session.scalar(select(CalendarViewPreference).where(CalendarViewPreference.owner_user_id == owner_id))
    if row is None:
        return _default_view()
    return ViewPreferenceOut(
        view_mode=row.view_mode,
        source_types=row.source_types_json,
        from_date=row.from_date,
        to_date=row.to_date,
        timezone=row.timezone,
        version=row.version,
        updated_at=_utc(row.updated_at),
    )


def update_view_preferences(
    session: Session, actor: ActorContext, payload: ViewPreferenceUpdate
) -> ViewPreferenceOut:
    owner_id = require_student(actor)
    # Lock the durable owner row so two first writes cannot both observe an
    # absent preference row on PostgreSQL.
    session.scalar(select(User.id).where(User.id == owner_id).with_for_update())
    row = session.scalar(
        select(CalendarViewPreference)
        .where(CalendarViewPreference.owner_user_id == owner_id)
        .with_for_update()
    )
    current = row.version if row else 0
    if payload.expected_version != current:
        raise CalendarError(409, "calendar_stale_version", "Calendar preferences changed", current_version=current)
    if row is not None and (
        row.view_mode == payload.view_mode
        and row.source_types_json == list(payload.source_types)
        and row.from_date == payload.from_date
        and row.to_date == payload.to_date
        and row.timezone == payload.timezone
    ):
        return get_view_preferences(session, actor)
    if row is None:
        row = CalendarViewPreference(owner_user_id=owner_id)
        session.add(row)
    else:
        row.version += 1
    row.view_mode = payload.view_mode
    row.source_types_json = list(payload.source_types)
    row.from_date = payload.from_date
    row.to_date = payload.to_date
    row.timezone = payload.timezone
    try:
        session.flush()
        record_audit_event(
            session,
            action="calendar_view_preferences_updated",
            resource_type="calendar_view_preference",
            resource_id=row.id,
            actor_user_id=owner_id,
            actor_role="student",
            after_state={"view_mode": row.view_mode, "source_count": len(row.source_types_json), "version": row.version},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        winner = session.scalar(select(CalendarViewPreference).where(
            CalendarViewPreference.owner_user_id == owner_id
        ))
        raise CalendarError(
            409,
            "calendar_stale_version",
            "Calendar preferences changed",
            current_version=winner.version if winner else 0,
        ) from None
    return get_view_preferences(session, actor)


def list_reminder_preferences(session: Session, actor: ActorContext) -> ReminderPreferenceListOut:
    owner_id = require_student(actor)
    rows = list(session.scalars(select(CalendarReminderPreference).where(
        CalendarReminderPreference.owner_user_id == owner_id
    ).order_by(CalendarReminderPreference.source_type, CalendarReminderPreference.channel)))
    stored = {(row.source_type, row.channel): _reminder_out(row) for row in rows}
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    items: list[ReminderPreferenceOut] = []
    for source_type in CALENDAR_SOURCE_TYPES:
        key = (source_type, "in_app")
        items.append(stored.get(key) or ReminderPreferenceOut(
            id=uuid.uuid5(uuid.NAMESPACE_URL, f"nyayone:calendar-reminder:{owner_id}:{source_type}:in_app"),
            source_type=source_type,
            channel="in_app",
            enabled=True,
            lead_minutes=30,
            quiet_start_min=22 * 60,
            quiet_end_min=7 * 60,
            timezone="Asia/Kolkata",
            version=0,
            updated_at=epoch,
        ))
    # Explicitly persisted additional channels follow the seven safe defaults.
    items.extend(
        output for key, output in sorted(stored.items()) if key[1] != "in_app"
    )
    return ReminderPreferenceListOut(items=items)


def _reminder_out(row: CalendarReminderPreference) -> ReminderPreferenceOut:
    return ReminderPreferenceOut(
        id=row.id,
        source_type=row.source_type,
        channel=row.channel,
        enabled=row.enabled,
        lead_minutes=row.lead_minutes,
        quiet_start_min=row.quiet_start_min,
        quiet_end_min=row.quiet_end_min,
        timezone=row.timezone,
        version=row.version,
        updated_at=_utc(row.updated_at),
    )


def update_reminder_preference(
    session: Session, actor: ActorContext, payload: ReminderPreferenceUpdate
) -> ReminderPreferenceOut:
    owner_id = require_student(actor)
    session.scalar(select(User.id).where(User.id == owner_id).with_for_update())
    row = session.scalar(select(CalendarReminderPreference).where(
        CalendarReminderPreference.owner_user_id == owner_id,
        CalendarReminderPreference.source_type == payload.source_type,
        CalendarReminderPreference.channel == payload.channel,
    ).with_for_update())
    current = row.version if row else 0
    if payload.expected_version != current:
        raise CalendarError(409, "calendar_stale_version", "Reminder preference changed", current_version=current)
    if row is not None and (
        row.enabled == payload.enabled
        and row.lead_minutes == payload.lead_minutes
        and row.quiet_start_min == payload.quiet_start_min
        and row.quiet_end_min == payload.quiet_end_min
        and row.timezone == payload.timezone
    ):
        # A version-matched retry of the already-persisted representation is a
        # true no-op: do not create another audit row or advance the version.
        return _reminder_out(row)
    if row is None:
        row = CalendarReminderPreference(
            owner_user_id=owner_id,
            source_type=payload.source_type,
            channel=payload.channel,
            lead_minutes=payload.lead_minutes,
            quiet_start_min=payload.quiet_start_min,
            quiet_end_min=payload.quiet_end_min,
            timezone=payload.timezone,
        )
        session.add(row)
    else:
        row.version += 1
        row.lead_minutes = payload.lead_minutes
        row.quiet_start_min = payload.quiet_start_min
        row.quiet_end_min = payload.quiet_end_min
        row.timezone = payload.timezone
    row.enabled = payload.enabled
    try:
        session.flush()
        record_audit_event(
            session,
            action="calendar_reminder_preference_updated",
            resource_type="calendar_reminder_preference",
            resource_id=row.id,
            actor_user_id=owner_id,
            actor_role="student",
            after_state={"source_type": row.source_type, "channel": row.channel, "enabled": row.enabled, "version": row.version},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        winner = session.scalar(select(CalendarReminderPreference).where(
            CalendarReminderPreference.owner_user_id == owner_id,
            CalendarReminderPreference.source_type == payload.source_type,
            CalendarReminderPreference.channel == payload.channel,
        ))
        raise CalendarError(
            409,
            "calendar_stale_version",
            "Reminder preference changed",
            current_version=winner.version if winner else 0,
        ) from None
    return _reminder_out(row)


def reminder_preview(
    session: Session,
    actor: ActorContext,
    source_type: str,
    channel: str,
) -> ReminderPreviewOut:
    """Return a generic preview only when server-side scheduling is eligible."""
    owner_id = require_student(actor)
    row = session.scalar(select(CalendarReminderPreference).where(
        CalendarReminderPreference.owner_user_id == owner_id,
        CalendarReminderPreference.source_type == source_type,
        CalendarReminderPreference.channel == channel,
    ))
    if row is None and channel != "in_app":
        return ReminderPreviewOut(
            source_type=source_type,
            channel=channel,
            scheduling_eligible=False,
            reason_code="not_configured",
            preview=None,
            lead_minutes=None,
            timezone=None,
        )
    enabled = row.enabled if row is not None else True
    if not enabled:
        return ReminderPreviewOut(
            source_type=source_type,
            channel=channel,
            scheduling_eligible=False,
            reason_code="disabled",
            preview=None,
            lead_minutes=row.lead_minutes if row else None,
            timezone=row.timezone if row else None,
        )
    return ReminderPreviewOut(
        source_type=source_type,
        channel=channel,
        scheduling_eligible=True,
        reason_code="eligible",
        preview="An upcoming NyayOne event has a reminder.",
        lead_minutes=row.lead_minutes if row else 30,
        timezone=row.timezone if row else "Asia/Kolkata",
    )


def check_conflicts(
    session: Session,
    actor: ActorContext,
    event_ids: list[uuid.UUID] | None,
    persist: bool,
) -> ConflictListOut:
    owner_id = require_student(actor)
    sync_domain_sources(session, owner_id)
    if persist:
        # PostgreSQL serialises conflict materialisation for this owner. SQLite
        # ignores FOR UPDATE but remains protected by the unique pair CHECK.
        session.scalar(select(User.id).where(User.id == owner_id).with_for_update())
    stmt = _event_stmt(owner_id)
    if event_ids is not None:
        stmt = stmt.where(CalendarEvent.id.in_(event_ids))
    rows = session.execute(stmt.order_by(CalendarEvent.starts_at, CalendarEvent.id)).all()
    if event_ids is not None and len(rows) != len(event_ids):
        raise CalendarError(404, "calendar_event_not_found", "Calendar event not found")
    pairs: list[ConflictOut] = []
    now = _now()
    for left_row, right_row in combinations(rows, 2):
        left, left_source = left_row[0], left_row[1]
        right, right_source = right_row[0], right_row[1]
        if not (_utc(left.starts_at) < _utc(right.ends_at) and _utc(right.starts_at) < _utc(left.ends_at)):
            continue
        if str(left.id) > str(right.id):
            left, right, left_source, right_source = right, left, right_source, left_source
        conflict = session.scalar(select(CalendarConflict).where(
            CalendarConflict.owner_user_id == owner_id,
            CalendarConflict.left_event_id == left.id,
            CalendarConflict.right_event_id == right.id,
        )) if persist else None
        if persist and conflict is None:
            conflict = CalendarConflict(
                owner_user_id=owner_id,
                left_event_id=left.id,
                right_event_id=right.id,
                status="active",
                detected_at=now,
            )
            session.add(conflict)
            session.flush()
        ephemeral_id = uuid.uuid5(uuid.NAMESPACE_URL, f"nyayone:{owner_id}:{left.id}:{right.id}")
        pairs.append(ConflictOut(
            id=conflict.id if conflict else ephemeral_id,
            left_event_id=left.id,
            right_event_id=right.id,
            left=_event_preview(left, left_source),
            right=_event_preview(right, right_source),
            status=conflict.status if conflict else "active",
            detected_at=_utc(conflict.detected_at) if conflict else now,
            version=conflict.version if conflict else 1,
        ))
    if persist:
        record_audit_event(
            session,
            action="calendar_conflicts_checked",
            resource_type="calendar_conflict",
            actor_user_id=owner_id,
            actor_role="student",
            after_state={"conflict_count": len(pairs)},
        )
    result = ConflictListOut(items=pairs, total=len(pairs))
    # The authenticated conflict read also refreshes the aggregate. It owns one
    # deliberate commit whether or not conflict rows were requested.
    session.commit()
    return result


def update_conflict(
    session: Session,
    actor: ActorContext,
    conflict_id: uuid.UUID,
    payload: ConflictUpdate,
) -> ConflictOut:
    owner_id = require_student(actor)
    conflict = session.scalar(select(CalendarConflict).where(
        CalendarConflict.id == conflict_id,
        CalendarConflict.owner_user_id == owner_id,
        CalendarConflict.deleted_at.is_(None),
    ).with_for_update())
    if conflict is None:
        raise CalendarError(404, "calendar_conflict_not_found", "Calendar conflict not found")
    if conflict.version != payload.expected_version:
        raise CalendarError(409, "calendar_stale_version", "Calendar conflict changed", current_version=conflict.version)
    left, left_source = _event_pair(session, owner_id, conflict.left_event_id)
    right, right_source = _event_pair(session, owner_id, conflict.right_event_id)
    previous = conflict.status
    if conflict.status != payload.status:
        conflict.status = payload.status
        conflict.version += 1
    record_audit_event(
        session,
        action="calendar_conflict_status_updated",
        resource_type="calendar_conflict",
        resource_id=conflict.id,
        actor_user_id=owner_id,
        actor_role="student",
        before_state={"status": previous, "version": payload.expected_version},
        after_state={"status": conflict.status, "version": conflict.version},
    )
    session.commit()
    return ConflictOut(
        id=conflict.id,
        left_event_id=left.id,
        right_event_id=right.id,
        left=_event_preview(left, left_source),
        right=_event_preview(right, right_source),
        status=conflict.status,
        detected_at=_utc(conflict.detected_at),
        version=conflict.version,
    )


def _export_out(row: CalendarExportSubscription, *, feed_url: str | None = None) -> CalendarExportOut:
    status = "expired" if row.status == "active" and _utc(row.expires_at) <= _now() else row.status
    return CalendarExportOut(
        id=row.id,
        status=status,
        timezone=row.timezone,
        expires_at=_utc(row.expires_at),
        revoked_at=_utc(row.revoked_at) if row.revoked_at else None,
        feed_url=feed_url,
        token_returned_once=feed_url is not None,
        version=row.version,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def list_exports(session: Session, actor: ActorContext) -> list[CalendarExportOut]:
    owner_id = require_student(actor)
    rows = list(session.scalars(select(CalendarExportSubscription).where(
        CalendarExportSubscription.owner_user_id == owner_id,
        CalendarExportSubscription.deleted_at.is_(None),
    ).order_by(CalendarExportSubscription.created_at.desc(), CalendarExportSubscription.id)))
    return [_export_out(row) for row in rows]


def get_export(session: Session, actor: ActorContext, export_id: uuid.UUID) -> CalendarExportOut:
    owner_id = require_student(actor)
    row = session.scalar(select(CalendarExportSubscription).where(
        CalendarExportSubscription.id == export_id,
        CalendarExportSubscription.owner_user_id == owner_id,
        CalendarExportSubscription.deleted_at.is_(None),
    ))
    if row is None:
        raise CalendarError(404, "calendar_export_not_found", "Calendar export not found")
    return _export_out(row)


def create_export(
    session: Session,
    actor: ActorContext,
    timezone_name: str,
    idempotency_key: str | None,
) -> CalendarExportOut:
    owner_id = require_student(actor)
    idem = _safe_idempotency(idempotency_key)
    sync_domain_sources(session, owner_id)
    # The user row is the cross-dialect mutex. PostgreSQL holds this lock until
    # commit; the partial unique index remains the final invariant backstop.
    session.scalar(select(User.id).where(User.id == owner_id).with_for_update())
    existing = session.scalar(select(CalendarExportSubscription).where(
        CalendarExportSubscription.owner_user_id == owner_id,
        CalendarExportSubscription.idempotency_key == idem,
    ))
    if existing is not None:
        if existing.timezone != timezone_name:
            raise CalendarError(409, "idempotency_conflict", "Idempotency-Key was reused with different data")
        result = _export_out(existing)
        session.commit()
        return result
    raw = secrets.token_urlsafe(32)
    now = _now()
    expiry = now + timedelta(days=settings.calendar_export_token_ttl_days)
    try:
        previous = list(session.scalars(select(CalendarExportSubscription).where(
            CalendarExportSubscription.owner_user_id == owner_id,
            CalendarExportSubscription.status == "active",
            CalendarExportSubscription.deleted_at.is_(None),
        ).with_for_update()))
        for old in previous:
            reason = "expired" if _utc(old.expires_at) <= now else "rotated"
            _revoke_subscription(session, old, owner_id, reason, now)
        row = CalendarExportSubscription(
            owner_user_id=owner_id,
            status="active",
            active_marker=True,
            timezone=timezone_name,
            idempotency_key=idem,
            expires_at=expiry,
        )
        session.add(row)
        session.flush()
        token = CalendarExportToken(
            subscription_id=row.id,
            token_hash=keyed_hash(raw),
            key_version=active_key_version(),
            expires_at=expiry,
        )
        session.add(token)
        session.flush()
        record_audit_event(
            session,
            action="calendar_export_created",
            resource_type="calendar_export_subscription",
            resource_id=row.id,
            actor_user_id=owner_id,
            actor_role="student",
            after_state={"status": "active", "expires_at": expiry.isoformat(), "rotated_count": len(previous)},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = session.scalar(select(CalendarExportSubscription).where(
            CalendarExportSubscription.owner_user_id == owner_id,
            CalendarExportSubscription.idempotency_key == idem,
        ))
        if replay is None:
            raise
        if replay.timezone != timezone_name:
            raise CalendarError(409, "idempotency_conflict", "Idempotency-Key was reused with different data")
        return _export_out(replay)
    return _export_out(
        row,
        feed_url=f"{settings.calendar_public_base_url}/api/v1/public/calendar-feeds/{raw}.ics",
    )


def _revoke_subscription(
    session: Session,
    row: CalendarExportSubscription,
    actor_user_id: uuid.UUID,
    reason: str,
    now: datetime,
) -> None:
    token = session.scalar(select(CalendarExportToken).where(
        CalendarExportToken.subscription_id == row.id
    ).with_for_update())
    if token is None:
        raise CalendarError(409, "calendar_export_integrity_error", "Calendar export cannot be rotated")
    row.status = "expired" if reason == "expired" else "revoked"
    row.active_marker = None
    row.revoked_at = now if row.status == "revoked" else None
    row.version += 1
    token.revoked_at = now
    session.add(CalendarExportRevocation(
        subscription_id=row.id,
        token_id=token.id,
        revoked_by_user_id=actor_user_id,
        reason_code=reason,
        revoked_at=now,
    ))


def revoke_export(session: Session, actor: ActorContext, export_id: uuid.UUID) -> CalendarExportOut:
    owner_id = require_student(actor)
    row = session.scalar(select(CalendarExportSubscription).where(
        CalendarExportSubscription.id == export_id,
        CalendarExportSubscription.owner_user_id == owner_id,
        CalendarExportSubscription.deleted_at.is_(None),
    ).with_for_update())
    if row is None:
        raise CalendarError(404, "calendar_export_not_found", "Calendar export not found")
    if row.status == "revoked":
        return _export_out(row)
    token = session.scalar(select(CalendarExportToken).where(
        CalendarExportToken.subscription_id == row.id
    ).with_for_update())
    if token is None:
        raise CalendarError(404, "calendar_export_not_found", "Calendar export not found")
    now = _now()
    _revoke_subscription(session, row, owner_id, "user_requested", now)
    record_audit_event(
        session,
        action="calendar_export_revoked",
        resource_type="calendar_export_subscription",
        resource_id=row.id,
        actor_user_id=owner_id,
        actor_role="student",
        after_state={"status": "revoked", "version": row.version},
    )
    session.commit()
    return _export_out(row)


def _ics_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _safe_ics_summary(event: CalendarEvent, source: CalendarEventSource) -> str:
    """Return only an approved category label, never user-entered title text."""
    if event.privacy_classification == "restricted":
        return "Private NyayOne event"
    if event.personal_event_kind:
        return {
            "study": "Study block",
            "deadline": "Personal deadline",
            "meeting": "Personal meeting",
            "reminder": "Personal reminder",
            "other": "Personal calendar event",
        }[event.personal_event_kind]
    return {
        "tutoring": "Tutoring session",
        "reminder": "Credential renewal reminder",
        "internship": "Internship event",
        "exam": "Exam preparation event",
        "clinical": "Clinical hours event",
        "community": "Community event",
        "moot": "Moot court event",
    }[source.source_type]


def _fold_ics(line: str) -> list[str]:
    """Fold an iCalendar content line at 75 UTF-8 octets (RFC 5545)."""
    chunks: list[str] = []
    current = ""
    limit = 75
    for char in line:
        if len((current + char).encode("utf-8")) > limit:
            chunks.append(current)
            current = " " + char
            limit = 75
        else:
            current += char
    chunks.append(current)
    return chunks


def public_ics(session: Session, raw_token: str) -> str:
    if not _TOKEN_RE.fullmatch(raw_token):
        raise CalendarError(404, "calendar_export_not_found", "Calendar export not found")
    token = session.scalar(select(CalendarExportToken).where(
        CalendarExportToken.token_hash == keyed_hash(raw_token),
        CalendarExportToken.deleted_at.is_(None),
    ))
    if token is None or token.revoked_at is not None or _utc(token.expires_at) <= _now():
        raise CalendarError(404, "calendar_export_not_found", "Calendar export not found")
    subscription = session.scalar(select(CalendarExportSubscription).where(
        CalendarExportSubscription.id == token.subscription_id,
        CalendarExportSubscription.status == "active",
        CalendarExportSubscription.deleted_at.is_(None),
    ))
    if subscription is None or _utc(subscription.expires_at) <= _now():
        raise CalendarError(404, "calendar_export_not_found", "Calendar export not found")
    rows = session.execute(_event_stmt(subscription.owner_user_id).order_by(
        CalendarEvent.starts_at, CalendarEvent.id
    )).all()
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//NyayOne//Private Calendar Feed//EN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    generated = _now().strftime("%Y%m%dT%H%M%SZ")
    for row in rows:
        event, source = row[0], row[1]
        title = _safe_ics_summary(event, source)
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{keyed_hash(str(event.id))}@calendar.nyayone.local",
            f"DTSTAMP:{generated}",
            f"DTSTART:{_utc(event.starts_at).strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{_utc(event.ends_at).strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{_ics_escape(title)}",
            f"STATUS:{'CANCELLED' if event.status == 'cancelled' else 'CONFIRMED'}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return "\r\n".join(part for line in lines for part in _fold_ics(line)) + "\r\n"
