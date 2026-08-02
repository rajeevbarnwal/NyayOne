"""Pydantic contracts for S-86/S-87 private internship reporting."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.wave4 import REPORT_CATEGORIES, REPORT_PRIVACY_MODES

_UNSAFE_TEXT = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f<>]")


def _draft_text(value: str, *, field: str, maximum: int) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) > maximum or _UNSAFE_TEXT.search(cleaned):
        raise ValueError(f"{field}_invalid")
    return cleaned


class ReportDraftFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organisation_name: str | None = None
    listing_application_ref: str | None = None
    experience_start_date: date | None = None
    experience_end_date: date | None = None
    categories: list[str] | None = Field(default=None, max_length=len(REPORT_CATEGORIES))
    narrative: str | None = None
    privacy_mode: str | None = None
    consent_accepted: bool | None = None
    consent_version: str | None = Field(default=None, max_length=40)

    @field_validator("organisation_name")
    @classmethod
    def _organisation(cls, value: str | None) -> str | None:
        return None if value is None else _draft_text(value, field="organisation_name", maximum=160)

    @field_validator("listing_application_ref")
    @classmethod
    def _reference(cls, value: str | None) -> str | None:
        return None if value is None else _draft_text(value, field="listing_application_ref", maximum=120)

    @field_validator("narrative")
    @classmethod
    def _narrative(cls, value: str | None) -> str | None:
        return None if value is None else _draft_text(value, field="narrative", maximum=5000)

    @field_validator("privacy_mode")
    @classmethod
    def _privacy(cls, value: str | None) -> str | None:
        if value is not None and value not in REPORT_PRIVACY_MODES:
            raise ValueError("unsupported_privacy_mode")
        return value

    @field_validator("categories")
    @classmethod
    def _categories(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        if len(values) != len(set(values)):
            raise ValueError("duplicate_category")
        if set(values) - set(REPORT_CATEGORIES):
            raise ValueError("unsupported_category")
        return values

    @field_validator("consent_version")
    @classmethod
    def _consent_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _draft_text(value, field="consent_version", maximum=40)
        return cleaned or None

    @model_validator(mode="after")
    def _dates(self):
        today = date.today()
        if self.experience_start_date and self.experience_start_date > today:
            raise ValueError("future_experience_start_date")
        if self.experience_end_date and self.experience_end_date > today:
            raise ValueError("future_experience_end_date")
        if (
            self.experience_start_date
            and self.experience_end_date
            and self.experience_end_date < self.experience_start_date
        ):
            raise ValueError("experience_end_before_start")
        return self


class ReportDraftCreate(ReportDraftFields):
    pass


class ReportDraftPatch(ReportDraftFields):
    expected_version: int = Field(ge=1)


class ReportSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class ReportEvidenceOut(BaseModel):
    id: uuid.UUID
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    scan_state: str
    retryable: bool = False


class InternshipReportOut(BaseModel):
    id: uuid.UUID
    organisation_name: str
    listing_application_ref: str
    experience_start_date: date | None
    experience_end_date: date | None
    categories: list[str]
    narrative: str
    privacy_mode: str
    consent_accepted: bool
    consent_version: str | None
    status: str
    support_guidance_required: bool
    evidence: list[ReportEvidenceOut]
    version: int
    submitted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InternshipReportStatusOut(BaseModel):
    id: uuid.UUID
    status: str
    privacy_mode: str
    support_guidance_required: bool
    evidence_total: int
    evidence_clean: int
    version: int
    submitted_at: datetime | None


class InternshipReportListOut(BaseModel):
    items: list[InternshipReportOut]
    total: int
