"""Canonical versioned student-profile request contracts (NYAY-5)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.student_academic_profile import normalize_college, normalize_year
from app.core.institutional_email import (
    CONSUMER_EMAIL_DOMAINS,
    INSTITUTIONAL_EMAIL_MAX_LENGTH,
    INSTITUTIONAL_EMAIL_RE,
)
from app.services.profile_service import normalize_legal_name


def _optional_text(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFC", value.strip())
    normalized = re.sub(r"\s+", " ", normalized)
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ValueError(f"must be {maximum} characters or fewer")
    return normalized


class PersonalProfileMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_profile_version: int = Field(ge=1)
    first_name: str
    middle_name: str | None = None
    last_name: str
    date_of_birth: date
    preferred_language: Literal["en", "hi"] | None
    city: str | None
    pronouns: str | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def _required_name(cls, value: str) -> str:
        try:
            return normalize_legal_name(value)
        except ValueError as exc:
            raise ValueError("invalid legal name") from exc

    @field_validator("middle_name")
    @classmethod
    def _middle_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_legal_name(value)
        except ValueError as exc:
            raise ValueError("invalid legal name") from exc

    @field_validator("city")
    @classmethod
    def _city(cls, value: str | None) -> str | None:
        return _optional_text(value, 120)

    @field_validator("pronouns")
    @classmethod
    def _pronouns(cls, value: str | None) -> str | None:
        return _optional_text(value, 60)


class AcademicProfileMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_profile_version: int = Field(ge=1)
    college: str | None
    year_of_study: str | None
    enrolment_number: str | None
    institutional_email: str | None
    bar_enrolment_number: str | None = None

    @field_validator("college")
    @classmethod
    def _college(cls, value: str | None) -> str | None:
        normalized = _optional_text(value, 160)
        try:
            return normalize_college(normalized)
        except ValueError as exc:
            raise ValueError("Select a supported college.") from exc

    @field_validator("year_of_study")
    @classmethod
    def _year(cls, value: str | None) -> str | None:
        normalized = _optional_text(value, 40)
        try:
            return normalize_year(normalized)
        except ValueError as exc:
            raise ValueError("Select a supported year of study.") from exc

    @field_validator("enrolment_number")
    @classmethod
    def _enrolment(cls, value: str | None) -> str | None:
        normalized = _optional_text(value, 120)
        if normalized is not None and not re.fullmatch(
            r"[A-Za-z]{2}/\d+/\d{4}", normalized
        ):
            raise ValueError("College enrolment number must use STATE/ROLL/YEAR.")
        return normalized

    @field_validator("institutional_email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        normalized = _optional_text(value, INSTITUTIONAL_EMAIL_MAX_LENGTH)
        if normalized is None:
            return None
        normalized = normalized.casefold()
        if (
            not INSTITUTIONAL_EMAIL_RE.fullmatch(normalized)
            or normalized.rpartition("@")[2] in CONSUMER_EMAIL_DOMAINS
        ):
            raise ValueError("Enter a valid institutional email.")
        return normalized

    @field_validator("bar_enrolment_number")
    @classmethod
    def _bar(cls, value: str | None) -> str | None:
        return _optional_text(value, 120)


class InterestsProfileMutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_profile_version: int = Field(ge=1)
    interests: list[str] = Field(max_length=20)
    goals: list[str] = Field(max_length=20)

    @field_validator("interests", "goals")
    @classmethod
    def _values(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in values:
            normalized = _optional_text(item, 80)
            if normalized is not None and normalized not in seen:
                seen.add(normalized)
                result.append(normalized)
        return result


class PromptDismissRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
