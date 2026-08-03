"""Typed HTTP contracts for Wave 5 calendar interoperability."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.calendar import CALENDAR_SOURCE_TYPES

_CONTROL_CHARS = {*(chr(value) for value in range(0x20)), *(chr(value) for value in range(0x7F, 0xA0))}

CalendarSourceType = Literal[
    "internship", "exam", "clinical", "community", "tutoring", "moot", "reminder"
]
CalendarEventStatus = Literal["scheduled", "deadline", "tentative", "done", "cancelled"]
CalendarPrivacy = Literal["public", "personal", "restricted"]
PersonalEventKind = Literal["study", "deadline", "meeting", "reminder", "other"]


def validate_timezone(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned or len(cleaned) > 64:
        raise ValueError("timezone must be a valid IANA timezone")
    try:
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return cleaned


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a UTC offset")
    return value


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    starts_at: datetime
    ends_at: datetime
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)
    status: CalendarEventStatus = "scheduled"
    privacy_classification: Literal["personal", "restricted"] = "personal"
    event_kind: PersonalEventKind = "reminder"

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("title cannot be empty")
        if any(char in _CONTROL_CHARS for char in cleaned):
            raise ValueError("title cannot contain control characters")
        return cleaned

    @field_validator("starts_at", "ends_at")
    @classmethod
    def aware_datetime(cls, value: datetime) -> datetime:
        return _aware(value)

    @field_validator("timezone")
    @classmethod
    def iana_timezone(cls, value: str) -> str:
        return validate_timezone(value)

    @model_validator(mode="after")
    def interval_is_ordered(self) -> "EventCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        zone = ZoneInfo(self.timezone)
        for field_name, value in (("starts_at", self.starts_at), ("ends_at", self.ends_at)):
            expected = value.astimezone(zone).utcoffset()
            # Canonical UTC (the production frontend wire format) is an instant
            # and is always valid with a separately retained display timezone.
            # A caller that supplies a local offset must make that offset agree
            # with the IANA zone at the represented instant.
            if value.utcoffset() != timedelta(0) and value.utcoffset() != expected:
                raise ValueError(
                    f"{field_name} UTC offset does not match timezone at that instant"
                )
        return self


class EventUpdate(EventCreate):
    expected_version: int = Field(ge=1)


class EventOut(BaseModel):
    id: uuid.UUID
    source_type: CalendarSourceType
    title: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    status: CalendarEventStatus
    privacy_classification: CalendarPrivacy
    event_kind: PersonalEventKind | None
    source_url: str
    version: int
    created_at: datetime
    updated_at: datetime


class EventPreview(BaseModel):
    id: uuid.UUID
    source_type: CalendarSourceType
    title: str
    starts_at: datetime
    ends_at: datetime
    timezone: str
    status: CalendarEventStatus
    event_kind: PersonalEventKind | None
    source_url: str


class EventListOut(BaseModel):
    items: list[EventOut]
    total: int
    failed_sources: list[CalendarSourceType] = Field(default_factory=list)


class ViewPreferenceUpdate(BaseModel):
    view_mode: Literal["month", "week", "day"] = "month"
    source_types: list[CalendarSourceType] = Field(default_factory=list, max_length=len(CALENDAR_SOURCE_TYPES))
    from_date: date | None = None
    to_date: date | None = None
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)
    expected_version: int = Field(ge=0)

    @field_validator("timezone")
    @classmethod
    def iana_timezone(cls, value: str) -> str:
        return validate_timezone(value)

    @field_validator("source_types")
    @classmethod
    def unique_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("source_types cannot contain duplicates")
        return value

    @model_validator(mode="after")
    def date_order(self) -> "ViewPreferenceUpdate":
        if self.from_date and self.to_date and self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        return self


class ViewPreferenceOut(BaseModel):
    view_mode: Literal["month", "week", "day"]
    source_types: list[CalendarSourceType]
    from_date: date | None
    to_date: date | None
    timezone: str
    version: int
    updated_at: datetime


class ReminderPreferenceUpdate(BaseModel):
    source_type: CalendarSourceType
    channel: Literal["in_app", "email_digest", "push"]
    enabled: bool = True
    lead_minutes: Literal[0, 10, 30, 60, 120, 1440]
    quiet_start_min: int = Field(ge=0, le=1439)
    quiet_end_min: int = Field(ge=0, le=1439)
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)
    expected_version: int = Field(ge=0)

    @field_validator("timezone")
    @classmethod
    def iana_timezone(cls, value: str) -> str:
        return validate_timezone(value)


class ReminderPreferenceOut(BaseModel):
    id: uuid.UUID
    source_type: CalendarSourceType
    channel: Literal["in_app", "email_digest", "push"]
    enabled: bool
    lead_minutes: int
    quiet_start_min: int
    quiet_end_min: int
    timezone: str
    version: int
    updated_at: datetime


class ReminderPreferenceListOut(BaseModel):
    items: list[ReminderPreferenceOut]


class ReminderPreviewIn(BaseModel):
    source_type: CalendarSourceType
    channel: Literal["in_app", "email_digest", "push"] = "in_app"


class ReminderPreviewOut(BaseModel):
    source_type: CalendarSourceType
    channel: Literal["in_app", "email_digest", "push"]
    scheduling_eligible: bool
    reason_code: Literal["eligible", "disabled", "not_configured"]
    preview: str | None
    lead_minutes: int | None
    timezone: str | None


class ConflictCheckIn(BaseModel):
    event_ids: list[uuid.UUID] | None = Field(default=None, min_length=2, max_length=100)
    persist: bool = True

    @field_validator("event_ids")
    @classmethod
    def unique_event_ids(cls, value: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("event_ids cannot contain duplicates")
        return value


class ConflictOut(BaseModel):
    id: uuid.UUID
    left_event_id: uuid.UUID
    right_event_id: uuid.UUID
    left: EventPreview
    right: EventPreview
    status: Literal["active", "dismissed", "resolved"]
    detected_at: datetime
    version: int


class ConflictListOut(BaseModel):
    items: list[ConflictOut]
    total: int


class ConflictUpdate(BaseModel):
    status: Literal["active", "dismissed", "resolved"]
    expected_version: int = Field(ge=1)


class ExportCreate(BaseModel):
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def iana_timezone(cls, value: str) -> str:
        return validate_timezone(value)


class CalendarExportOut(BaseModel):
    id: uuid.UUID
    status: Literal["active", "revoked", "expired"]
    timezone: str
    expires_at: datetime
    revoked_at: datetime | None
    feed_url: str | None = None
    token_returned_once: bool = False
    version: int
    created_at: datetime
    updated_at: datetime


class CalendarExportListOut(BaseModel):
    items: list[CalendarExportOut]
    total: int
