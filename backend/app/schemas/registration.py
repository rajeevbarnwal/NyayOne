"""Registration API contracts (SAATHI-421/448). Mirrors the frontend shared
contract: exact-10 mobile, First/Last required + optional Middle (Unicode, ≤60),
real non-future DOB, affirmative consent."""
from __future__ import annotations

import re
import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, field_validator

MOBILE_RE = re.compile(r"^\d{10}$")
_ALLOWED_NAME_EXTRA = set(" .'-‘’")


def _validate_name(value: str | None, *, required: bool, field: str) -> str | None:
    v = (value or "").strip()
    if not v:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if len(v) > 60:
        raise ValueError(f"{field} must be 60 characters or fewer")
    if any(ch.isdigit() for ch in v) or not any(ch.isalpha() for ch in v):
        raise ValueError(f"{field} contains characters that aren't allowed")
    if not all(ch.isalpha() or ch.isspace() or ch in _ALLOWED_NAME_EXTRA for ch in v):
        raise ValueError(f"{field} contains characters that aren't allowed")
    return re.sub(r"\s+", " ", v)


class ConsentIn(BaseModel):
    accepted: bool
    policy_version: str = "dpdp-2023.v1"


class StudentRegisterRequest(BaseModel):
    # Reject unknown fields so submitted data is never silently discarded.
    model_config = ConfigDict(extra="forbid")

    first_name: str
    middle_name: str | None = None
    last_name: str
    mobile: str
    dob: date
    consent: ConsentIn
    # Academic profile (SAATHI-421). Optional at registration; persisted to
    # student_profiles when supplied.
    college: str | None = None
    year_of_study: str | None = None
    enrolment_number: str | None = None
    institutional_email: str | None = None
    bar_enrolment_number: str | None = None

    @field_validator("first_name")
    @classmethod
    def _first(cls, v: str) -> str:
        return _validate_name(v, required=True, field="First name")  # type: ignore[return-value]

    @field_validator("last_name")
    @classmethod
    def _last(cls, v: str) -> str:
        return _validate_name(v, required=True, field="Last name")  # type: ignore[return-value]

    @field_validator("middle_name")
    @classmethod
    def _middle(cls, v: str | None) -> str | None:
        return _validate_name(v, required=False, field="Middle name")

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str) -> str:
        if not MOBILE_RE.match(v or ""):
            raise ValueError("Mobile number must be exactly 10 digits.")
        return v

    @field_validator("dob")
    @classmethod
    def _dob(cls, v: date) -> date:
        # Pydantic already rejects impossible calendar dates (e.g. 2026-02-31).
        if v > date.today():
            raise ValueError("Enter a valid date of birth that is not in the future.")
        return v


class StudentRegisterResponse(BaseModel):
    registration_id: uuid.UUID
    status: str


class StudentAcademicProfileRequest(BaseModel):
    """S-10 academic profile payload."""

    model_config = ConfigDict(extra="ignore")

    registration_id: uuid.UUID
    college: str
    year_of_study: str
    enrolment_number: str
    institutional_email: str
    bar_enrolment_number: str | None = None
    interests: str | None = None
    career_goal: str | None = None

    @field_validator("college")
    @classmethod
    def _college(cls, v: str) -> str:
        value = v.strip()
        if not value or len(value) > 160:
            raise ValueError("College / institution is required and must be 160 characters or fewer.")
        return value

    @field_validator("year_of_study")
    @classmethod
    def _year(cls, v: str) -> str:
        value = v.strip()
        if not value or len(value) > 40:
            raise ValueError("Year of study is required.")
        return value

    @field_validator("enrolment_number")
    @classmethod
    def _enrolment(cls, v: str) -> str:
        value = v.strip()
        if not re.fullmatch(r"[A-Za-z]{2}/\d+/\d{4}", value):
            raise ValueError("College enrolment number must use STATE/ROLL/YEAR.")
        return value

    @field_validator("institutional_email")
    @classmethod
    def _email(cls, v: str) -> str:
        value = v.strip().lower()
        if len(value) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]{2,}", value):
            raise ValueError("Enter a valid institutional email.")
        return value

    @field_validator("bar_enrolment_number")
    @classmethod
    def _bar(cls, v: str | None) -> str | None:
        value = (v or "").strip()
        if not value:
            return None
        if len(value) > 120:
            raise ValueError("Bar enrolment number must be 120 characters or fewer.")
        return value
