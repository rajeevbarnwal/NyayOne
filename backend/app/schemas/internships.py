"""Typed HTTP contracts for SAATHI-60 internship discovery and saves."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
import uuid

from pydantic import BaseModel, Field


class InternshipSourceOut(BaseModel):
    name: str
    url: str | None
    retrieved_at: datetime | None
    verified_at: datetime | None


class InternshipListingOut(BaseModel):
    id: str
    organisation_id: uuid.UUID
    role: str
    organisation: str
    location: str
    stipend_monthly_paise: int | None = Field(ge=0)
    verification_status: Literal["verified", "unverified"]
    application_deadline: date
    eligibility: str
    tags: list[str]
    description: str
    source: InternshipSourceOut


class InternshipListingListOut(BaseModel):
    items: list[InternshipListingOut]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class SavedInternshipListOut(BaseModel):
    items: list[InternshipListingOut]


class SavedInternshipStateOut(BaseModel):
    saved: bool
    listing_id: str
