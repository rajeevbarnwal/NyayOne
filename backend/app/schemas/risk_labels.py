"""Privacy-safe contracts for governed internship risk labels (SAATHI-279)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_UNSAFE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f<>]")
_OPAQUE_REPRESENTATIVE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$")


class RiskLabelCandidateOut(BaseModel):
    cluster_id: uuid.UUID
    risk_signal_id: uuid.UUID
    organisation_id: uuid.UUID
    organisation_name: str
    category: str
    neutral_label: str
    report_count: int
    distinct_reporter_count: int
    public_count: int | None
    threshold_met: bool
    small_count_suppressed: bool
    moderator_approved: bool
    safety_legal_approved: bool
    approval_vetoed: bool
    publication_ready: bool
    published_label_id: uuid.UUID | None
    status: str
    version: int


class RiskLabelCandidateListOut(BaseModel):
    items: list[RiskLabelCandidateOut]
    total: int = Field(ge=0)
    publication_gate_open: bool


class RiskLabelPublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    reason_code: str
    action: str = "publish"

    @field_validator("action")
    @classmethod
    def valid_action(cls, value: str) -> str:
        if value not in {"publish", "withdraw"}:
            raise ValueError("unsupported_publication_action")
        return value

    @field_validator("reason_code")
    @classmethod
    def safe_reason(cls, value: str) -> str:
        value = value.strip()
        if value not in {
            "qa_policy",
            "qa_governed_publication",
            "policy_approved",
            "risk_signal_veto",
            "administrative_withdrawal",
        }:
            raise ValueError("unsupported_publication_reason")
        return value


class PublishedRiskLabelOut(BaseModel):
    id: uuid.UUID
    organisation_id: uuid.UUID
    category: str
    neutral_label: str
    public_count: int | None
    status: str
    last_reviewed_at: datetime
    published_at: datetime
    version: int


class OrganisationResponseRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    published_label_id: uuid.UUID
    representative_verification_ref: str
    verification_method: str
    request_kind: str = "initial"

    @field_validator("representative_verification_ref", "verification_method")
    @classmethod
    def safe_text(cls, value: str) -> str:
        value = value.strip()
        if not 3 <= len(value) <= 500:
            raise ValueError("representative_verification_length")
        if _UNSAFE.search(value):
            raise ValueError("unsafe_representative_verification")
        return value

    @field_validator("representative_verification_ref")
    @classmethod
    def verification_ref_length(cls, value: str) -> str:
        if not _OPAQUE_REPRESENTATIVE_REF.fullmatch(value):
            raise ValueError("representative_verification_ref_must_be_opaque")
        return value

    @field_validator("verification_method")
    @classmethod
    def verification_method_allowed(cls, value: str) -> str:
        if value not in {
            "manual_legal_review",
            "verified_domain_challenge",
            "qa_fixture",
        }:
            raise ValueError("unsupported_representative_verification_method")
        return value

    @field_validator("request_kind")
    @classmethod
    def valid_kind(cls, value: str) -> str:
        if value not in {"initial", "correction", "appeal"}:
            raise ValueError("unsupported_response_request_kind")
        return value


class OrganisationResponseRequestOut(BaseModel):
    id: uuid.UUID
    published_label_id: uuid.UUID
    state: str
    expires_at: datetime
    version: int


class OrganisationResponseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Length is enforced after normalisation below.  Field-level length checks
    # run before validators in Pydantic and would otherwise allow an all-space
    # response to become an empty string after validation.
    response_text: str

    @field_validator("response_text")
    @classmethod
    def safe_response(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 2000:
            raise ValueError("organisation_response_length")
        if _UNSAFE.search(value):
            raise ValueError("unsafe_organisation_response")
        return value


class OrganisationResponseOut(BaseModel):
    id: uuid.UUID
    published_label_id: uuid.UUID
    state: str
    version: int
    submitted_at: datetime


class OrganisationResponseDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: str
    reason_code: str
    expected_version: int = Field(ge=1)

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, value: str) -> str:
        if value not in {"approve", "reject"}:
            raise ValueError("unsupported_response_decision")
        return value

    @field_validator("reason_code")
    @classmethod
    def safe_reason(cls, value: str) -> str:
        value = value.strip()
        if value not in {
            "qa_review",
            "verified_initial_response",
            "verified_factual_correction",
            "response_verified",
            "response_policy_violation",
        }:
            raise ValueError("unsupported_response_reason")
        return value


class PublicOrganisationResponseOut(BaseModel):
    text: str
    last_reviewed_at: datetime
    kind: str


class PublicRiskLabelOut(BaseModel):
    id: uuid.UUID
    category: str
    neutral_label: str
    public_count: int | None
    last_reviewed_at: datetime
    source_type: str
    status: str
    organisation_response: PublicOrganisationResponseOut | None


class PublicRiskLabelsOut(BaseModel):
    organisation_id: uuid.UUID
    labels: list[PublicRiskLabelOut]
    available: bool
