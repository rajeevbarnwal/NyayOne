"""Authenticated calendar interoperability and privacy-minimised ICS routes."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, get_actor_context
from app.db.session import get_session
from app.schemas.calendar import (
    CalendarExportListOut,
    CalendarExportOut,
    CalendarSourceType,
    ConflictCheckIn,
    ConflictListOut,
    ConflictOut,
    ConflictUpdate,
    EventCreate,
    EventListOut,
    EventOut,
    EventUpdate,
    ExportCreate,
    ReminderPreferenceListOut,
    ReminderPreferenceOut,
    ReminderPreferenceUpdate,
    ReminderPreviewIn,
    ReminderPreviewOut,
    ViewPreferenceOut,
    ViewPreferenceUpdate,
    validate_timezone,
)
from app.services import calendar_service

router = APIRouter(tags=["calendar"])


def _raise(error: calendar_service.CalendarError) -> None:
    detail: dict[str, object] = {"code": error.code, "message": error.message}
    if error.field is not None:
        detail["field"] = error.field
    if error.current_version is not None:
        detail["current_version"] = error.current_version
    raise HTTPException(status_code=error.status_code, detail=detail)


@router.get("/calendar/events", response_model=EventListOut)
def calendar_events(
    source_type: Annotated[list[CalendarSourceType] | None, Query()] = None,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    timezone: str = Query(default="Asia/Kolkata", min_length=1, max_length=64),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> EventListOut:
    try:
        timezone = validate_timezone(timezone)
        return calendar_service.list_events(
            session, actor, list(source_type) if source_type else None, from_date, to_date, timezone
        )
    except ValueError:
        session.rollback()
        _raise(calendar_service.CalendarError(422, "calendar_invalid_timezone", "Invalid timezone", "timezone"))
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.post("/calendar/events", response_model=EventOut, status_code=201)
def calendar_event_create(
    payload: EventCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> EventOut:
    try:
        return calendar_service.create_event(session, actor, payload, idempotency_key)
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.get("/calendar/events/{event_id}", response_model=EventOut)
def calendar_event_get(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> EventOut:
    try:
        return calendar_service.get_event(session, actor, event_id)
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.put("/calendar/events/{event_id}", response_model=EventOut)
def calendar_event_update(
    event_id: uuid.UUID,
    payload: EventUpdate,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> EventOut:
    try:
        return calendar_service.update_event(session, actor, event_id, payload)
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.delete("/calendar/events/{event_id}", status_code=204)
def calendar_event_delete(
    event_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> Response:
    try:
        calendar_service.delete_event(session, actor, event_id)
        return Response(status_code=204)
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.get("/calendar/view-preferences", response_model=ViewPreferenceOut)
def calendar_view_preferences_get(
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ViewPreferenceOut:
    try:
        return calendar_service.get_view_preferences(session, actor)
    except calendar_service.CalendarError as error:
        _raise(error)


@router.put("/calendar/view-preferences", response_model=ViewPreferenceOut)
def calendar_view_preferences_put(
    payload: ViewPreferenceUpdate,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ViewPreferenceOut:
    try:
        return calendar_service.update_view_preferences(session, actor, payload)
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.get("/calendar/reminder-preferences", response_model=ReminderPreferenceListOut)
def calendar_reminder_preferences_get(
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ReminderPreferenceListOut:
    try:
        return calendar_service.list_reminder_preferences(session, actor)
    except calendar_service.CalendarError as error:
        _raise(error)


@router.put("/calendar/reminder-preferences", response_model=ReminderPreferenceOut)
def calendar_reminder_preferences_put(
    payload: ReminderPreferenceUpdate,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ReminderPreferenceOut:
    try:
        return calendar_service.update_reminder_preference(session, actor, payload)
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.post("/calendar/reminder-preferences/preview", response_model=ReminderPreviewOut)
def calendar_reminder_preview(
    payload: ReminderPreviewIn,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ReminderPreviewOut:
    try:
        return calendar_service.reminder_preview(
            session, actor, payload.source_type, payload.channel
        )
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.post("/calendar/conflicts/check", response_model=ConflictListOut)
def calendar_conflicts_check(
    payload: ConflictCheckIn,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ConflictListOut:
    try:
        return calendar_service.check_conflicts(session, actor, payload.event_ids, payload.persist)
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.patch("/calendar/conflicts/{conflict_id}", response_model=ConflictOut)
def calendar_conflict_update(
    conflict_id: uuid.UUID,
    payload: ConflictUpdate,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> ConflictOut:
    try:
        return calendar_service.update_conflict(session, actor, conflict_id, payload)
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.get("/calendar/exports", response_model=CalendarExportListOut)
def calendar_exports_list(
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> CalendarExportListOut:
    try:
        items = calendar_service.list_exports(session, actor)
        return CalendarExportListOut(items=items, total=len(items))
    except calendar_service.CalendarError as error:
        _raise(error)


@router.post("/calendar/exports", response_model=CalendarExportOut, status_code=201)
def calendar_export_create(
    payload: ExportCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> CalendarExportOut:
    try:
        return calendar_service.create_export(session, actor, payload.timezone, idempotency_key)
    except calendar_service.CalendarError as error:
        session.rollback()
        _raise(error)


@router.get("/calendar/exports/{export_id}", response_model=CalendarExportOut)
def calendar_export_get(
    export_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> CalendarExportOut:
    try:
        return calendar_service.get_export(session, actor, export_id)
    except calendar_service.CalendarError as error:
        _raise(error)


@router.delete("/calendar/exports/{export_id}", response_model=CalendarExportOut)
def calendar_export_delete(
    export_id: uuid.UUID,
    session: Session = Depends(get_session),
    actor: ActorContext = Depends(get_actor_context),
) -> CalendarExportOut:
    try:
        return calendar_service.revoke_export(session, actor, export_id)
    except (calendar_service.CalendarError, IntegrityError) as error:
        session.rollback()
        if isinstance(error, calendar_service.CalendarError):
            _raise(error)
        _raise(calendar_service.CalendarError(409, "calendar_export_already_revoked", "Calendar export is already revoked"))


@router.get("/public/calendar-feeds/{raw_token}.ics")
def calendar_public_feed(
    raw_token: str,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    try:
        if request.url.query:
            raise calendar_service.CalendarError(
                404, "calendar_export_not_found", "Calendar export not found"
            )
        content = calendar_service.public_ics(session, raw_token)
    except calendar_service.CalendarError as error:
        _raise(error)
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'inline; filename="legalsaathi-private-calendar.ics"',
        },
    )
