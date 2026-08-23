"""Registration API contracts (SAATHI-421/448, NYAY-5).

Names share the tracked Unicode contract; DOB future policy is evaluated by
the service's request clock. Legacy academic fields remain parseable only to
replay sealed v1 idempotency ledgers and new-key creation rejects them.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.legal_name import normalize_legal_name
from app.core.institutional_email import (
    normalize_institutional_email,
)

MOBILE_RE = re.compile(r"[0-9]{10}")
_ALLOWED_NAME_EXTRA = set(" .'-‘’")


def _validate_name(value: str | None, *, required: bool, field: str) -> str | None:
    if value is None or not value.strip(" "):
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        return normalize_legal_name(value)
    except ValueError:
        raise ValueError(f"{field} contains characters that aren't allowed")


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    policy_version: str = "dpdp-2023.v1"

    @field_validator("policy_version")
    @classmethod
    def _policy_version(cls, value: str) -> str:
        normalized = unicodedata.normalize("NFC", value.strip())
        if not normalized or len(normalized) > 40:
            raise ValueError("Consent policy version is required and must be 40 characters or fewer.")
        return normalized


class StudentRegisterRequest(BaseModel):
    # Reject unknown fields so submitted data is never silently discarded.
    model_config = ConfigDict(extra="forbid")

    first_name: str
    middle_name: str | None = None
    last_name: str
    mobile: str
    dob: date
    # NYAY-5 legal authority.  The two legal artefacts are deliberately
    # independent: accepting Terms is not consent to, or acknowledgement of,
    # the Privacy Notice.  They remain optional at schema construction only so
    # an exact pre-NYAY-5 v1 idempotency replay can be parsed and resolved
    # before the service rejects legacy-shaped new writes.
    terms_accepted: bool | None = None
    terms_version: str | None = None
    privacy_notice_acknowledged: bool | None = None
    privacy_notice_version: str | None = None
    consent: ConsentIn | None = None
    # Replay-only compatibility leaves for pre-NYAY-5 v1 fingerprints. New
    # registration writes reject any non-null value before creating a graph.
    college: str | None = None
    year_of_study: str | None = None
    enrolment_number: str | None = None
    institutional_email: str | None = None
    bar_enrolment_number: str | None = None

    @field_validator("terms_version", "privacy_notice_version")
    @classmethod
    def _legal_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = unicodedata.normalize("NFC", value.strip())
        if not normalized or len(normalized) > 40:
            raise ValueError(
                "Legal policy version is required and must be 40 characters or fewer."
            )
        return normalized

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
        if not MOBILE_RE.fullmatch(v or ""):
            raise ValueError("Mobile number must be exactly 10 digits.")
        return v

    @field_validator("dob")
    @classmethod
    def _dob(cls, v: date) -> date:
        # Pydantic rejects impossible calendar dates. Whether this date is in
        # the future is request-clock policy and is enforced in the service,
        # never against process wall time during schema construction.
        return v

    @field_validator("college")
    @classmethod
    def _registration_college(cls, value: str | None) -> str | None:
        normalized = unicodedata.normalize("NFC", (value or "").strip())
        if not normalized:
            return None
        normalized = re.sub(r"\s+", " ", normalized)
        # ``institution_ref`` is the narrower of the two destination columns.
        if len(normalized) > 120:
            raise ValueError("College / institution must be 120 characters or fewer.")
        return normalized

    @field_validator("year_of_study")
    @classmethod
    def _registration_year(cls, value: str | None) -> str | None:
        normalized = unicodedata.normalize("NFC", (value or "").strip())
        if not normalized:
            return None
        normalized = re.sub(r"\s+", " ", normalized)
        if len(normalized) > 40:
            raise ValueError("Year of study must be 40 characters or fewer.")
        return normalized

    @field_validator("enrolment_number")
    @classmethod
    def _registration_enrolment(cls, value: str | None) -> str | None:
        normalized = unicodedata.normalize("NFC", (value or "").strip())
        if not normalized:
            return None
        if not re.fullmatch(r"[A-Za-z]{2}/\d+/\d{4}", normalized):
            raise ValueError("College enrolment number must use STATE/ROLL/YEAR.")
        return normalized

    @field_validator("bar_enrolment_number")
    @classmethod
    def _registration_bar_enrolment(cls, value: str | None) -> str | None:
        normalized = unicodedata.normalize("NFC", (value or "").strip())
        if not normalized:
            return None
        if len(normalized) > 120:
            raise ValueError("Bar enrolment number must be 120 characters or fewer.")
        return normalized

    @field_validator("institutional_email")
    @classmethod
    def _registration_email(cls, value: str | None) -> str | None:
        try:
            return normalize_institutional_email(value)
        except ValueError:
            raise ValueError("Enter a valid institutional email.")


class StudentRegisterResponse(BaseModel):
    registration_id: uuid.UUID
    status: str


class StudentAcademicProfileRequest(BaseModel):
    """S-10 owner-scoped academic profile payload.

    The authenticated server session resolves the registration.  A client
    registration UUID is deliberately not part of this protected contract.
    """

    model_config = ConfigDict(extra="forbid")

    expected_profile_version: int = Field(ge=1)
    college: str
    year_of_study: str
    enrolment_number: str
    institutional_email: str
    bar_enrolment_number: str | None = None

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
        try:
            value = normalize_institutional_email(v)
        except ValueError:
            raise ValueError("Enter a valid institutional email.")
        if value is None:
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
