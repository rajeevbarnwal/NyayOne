"""Privacy-safe HTTP contracts for SAATHI-274 internal moderation."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.wave4 import (
    MODERATION_ACTIONS,
    MODERATION_REASON_CODES,
    REPORT_CATEGORIES,
)

_UNSAFE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f<>]")


class ModerationQueueItemOut(BaseModel):
    case_id: uuid.UUID
    report_id: uuid.UUID
    organisation_name: str
    categories: list[str]
    experience_start_date: date | None
    experience_end_date: date | None
    evidence_clean: int
    evidence_total: int
    state: str
    assigned_to_me: bool
    version: int
    submitted_at: datetime | None


class ModerationQueueOut(BaseModel):
    items: list[ModerationQueueItemOut]
    total: int


class ModerationCaseOut(ModerationQueueItemOut):
    listing_application_ref: str
    narrative: str
    privacy_mode: str
    support_guidance_required: bool
    scan_states: list[str]


class ModerationActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    reason_code: str
    reason_detail: str
    expected_version: int = Field(ge=1)

    @field_validator("action")
    @classmethod
    def action_allowed(cls, value: str) -> str:
        if value not in MODERATION_ACTIONS:
            raise ValueError("unsupported_moderation_action")
        return value

    @field_validator("reason_code")
    @classmethod
    def reason_allowed(cls, value: str) -> str:
        if value not in MODERATION_REASON_CODES:
            raise ValueError("unsupported_moderation_reason")
        return value

    @field_validator("reason_detail")
    @classmethod
    def safe_reason(cls, value: str) -> str:
        value = value.strip()
        if not 10 <= len(value) <= 1000:
            raise ValueError("moderation_reason_detail_length")
        if _UNSAFE.search(value):
            raise ValueError("unsafe_reason_detail")
        return value

    @model_validator(mode="after")
    def action_reason_pair(self):
        expected = {
            "claim": "review_started",
            "needs_information": "more_information_required",
            "approve_aggregate_only": "aggregate_criteria_met",
            "reject": "insufficient_or_unverifiable",
        }
        if expected.get(self.action) != self.reason_code:
            raise ValueError("reason_does_not_match_action")
        return self


class ModerationActionOut(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    action: str
    reason_code: str
    case_state: str
    case_version: int
    created_at: datetime


class RiskClusterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_ids: list[uuid.UUID] = Field(min_length=2, max_length=50)
    category: str

    @field_validator("report_ids")
    @classmethod
    def unique_reports(cls, values: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate_cluster_report")
        return values

    @field_validator("category")
    @classmethod
    def category_allowed(cls, value: str) -> str:
        if value not in REPORT_CATEGORIES:
            raise ValueError("unsupported_category")
        return value


class RiskSignalApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    reason_code: str

    @field_validator("decision")
    @classmethod
    def decision_allowed(cls, value: str) -> str:
        if value not in {"approve", "reject"}:
            raise ValueError("unsupported_approval_decision")
        return value

    @field_validator("reason_code")
    @classmethod
    def safe_reason(cls, value: str) -> str:
        value = value.strip()
        if value not in {
            "moderator_policy_check",
            "safety_policy_check",
            "qa_target_gate_approval",
            "qa_publication_veto",
            "risk_signal_veto",
        }:
            raise ValueError("unsupported_approval_reason")
        return value


class RiskClusterOut(BaseModel):
    id: uuid.UUID
    organisation_name: str
    category: str
    explanation_code: str
    state: str
    member_report_ids: list[uuid.UUID]
    report_count: int
    distinct_reporter_count: int
    threshold_met: bool
    small_count_suppressed: bool
    moderator_approved: bool
    safety_legal_approved: bool
    publication_ready: bool
    public_count: int | None
    neutral_label: str
    version: int


class IdentityAccessRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason_detail: str

    @field_validator("reason_detail")
    @classmethod
    def safe_reason(cls, value: str) -> str:
        value = value.strip()
        if not 20 <= len(value) <= 1000:
            raise ValueError("identity_access_reason_length")
        if _UNSAFE.search(value):
            raise ValueError("unsafe_identity_access_reason")
        return value


class IdentityAccessApprovalIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    expected_version: int = Field(ge=1)

    @field_validator("decision")
    @classmethod
    def valid_decision(cls, value: str) -> str:
        if value not in {"approve", "reject"}:
            raise ValueError("unsupported_identity_access_decision")
        return value


class IdentityAccessRequestOut(BaseModel):
    id: uuid.UUID
    report_id: uuid.UUID
    state: str
    approval_count: int = Field(ge=0)
    version: int = Field(ge=1)
    expires_at: datetime
    created_at: datetime


class IdentityAccessExecutionOut(BaseModel):
    request_id: uuid.UUID
    state: str
    reporter_identity: str
