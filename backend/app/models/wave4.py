"""Wave 4 private reporting, moderation, and disabled-by-default projection.

Reporter identity is physically separated from report content.  The report row
contains no user id, email, mobile or reversible identity.  Ownership is resolved
through ``reporter_identity_vault`` using a keyed lookup hash; the authorised
identity value is encrypted and key-versioned.

Internal aggregate candidates are persisted for SAATHI-274.  SAATHI-279 adds
the separately moderated projection schema, while runtime configuration keeps
its HTTP publication boundary closed until the external approvals are real.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import TimestampedBase

REPORT_PRIVACY_MODES = ("anonymous", "private_to_platform")
REPORT_STATUSES = (
    "draft",
    "moderation_pending",
    "needs_information",
    "approved",
    "rejected",
    "withdrawn",
)
REPORT_CATEGORIES = (
    "unpaid_mismatch",
    "excessive_hours",
    "unsafe_environment",
    "harassment",
    "discrimination",
    "misleading_work",
    "non_response",
    "certificate_withheld",
    "stipend_delay_exploitative",
    "positive_experience",
)
EVIDENCE_SCAN_STATES = (
    "quarantined",
    "clean",
    "infected",
    "retryable_failure",
    "deleted",
)
IDENTITY_ACCESS_STATES = ("pending", "approved", "rejected", "executed", "expired")
IDENTITY_APPROVAL_DECISIONS = ("approve", "reject")
MODERATION_HANDOFF_STATES = (
    "pending",
    "assigned",
    "needs_information",
    "approved",
    "rejected",
    "withdrawn",
)
REPORTING_OUTBOX_KINDS = (
    "report_submitted",
    "evidence_scan_requested",
    "moderation_handoff_created",
)
REPORTING_OUTBOX_STATES = ("pending", "sent", "failed", "void")
MODERATION_CASE_STATES = (
    "pending",
    "under_review",
    "approved_aggregate_only",
    "rejected",
    "needs_information",
)
MODERATION_ACTIONS = (
    "claim",
    "needs_information",
    "approve_aggregate_only",
    "reject",
)
MODERATION_REASON_CODES = (
    "review_started",
    "more_information_required",
    "aggregate_criteria_met",
    "insufficient_or_unverifiable",
)
DUPLICATE_CLUSTER_STATES = ("candidate", "suppressed", "eligible")
RISK_APPROVAL_ROLES = ("moderator", "safety_officer", "legal_reviewer")
RISK_APPROVAL_REASON_CODES = (
    "moderator_policy_check", "safety_policy_check", "qa_target_gate_approval",
    "qa_publication_veto", "risk_signal_veto",
)
MODERATION_OUTBOX_STATES = ("pending", "sent", "failed", "void")
PUBLIC_RISK_LABEL_STATUSES = ("published", "withdrawn", "corrected")
PUBLICATION_DECISION_TYPES = ("publish", "withhold", "withdraw")
PUBLICATION_REASON_CODES = (
    "qa_policy", "qa_governed_publication", "policy_approved",
    "risk_signal_veto", "administrative_withdrawal",
)
ORGANISATION_RESPONSE_REQUEST_STATES = (
    "pending",
    "responded",
    "expired",
    "revoked",
)
ORGANISATION_RESPONSE_REQUEST_KINDS = ("initial", "correction", "appeal")
ORGANISATION_RESPONSE_STATES = (
    "moderation_pending",
    "approved",
    "rejected",
    "withdrawn",
    "superseded",
)
RESPONSE_MODERATION_DECISIONS = ("approve", "reject")
RESPONSE_MODERATION_REASON_CODES = (
    "qa_review", "verified_initial_response", "verified_factual_correction",
    "response_verified", "response_policy_violation",
)
NOTIFICATION_OUTBOX_KINDS = (
    "risk_label_published",
    "risk_label_withdrawn",
    "organisation_response_requested",
    "organisation_response_submitted",
    "organisation_response_decided",
)
NOTIFICATION_OUTBOX_STATES = ("pending", "processing", "sent", "failed", "void")


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IN ({', '.join(repr(value) for value in values)})",
        name=name,
    )


class InternshipReport(TimestampedBase):
    __tablename__ = "internship_reports"

    organisation_name: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    listing_application_ref: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    experience_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    experience_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    narrative: Mapped[str] = mapped_column(Text, default="", nullable=False)
    privacy_mode: Mapped[str] = mapped_column(
        String(32), default="anonymous", server_default="anonymous", nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="draft", server_default="draft", nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    support_guidance_required: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _in("privacy_mode", REPORT_PRIVACY_MODES, "privacy_mode"),
        _in("status", REPORT_STATUSES, "status"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "experience_end_date IS NULL OR experience_start_date IS NULL "
            "OR experience_end_date >= experience_start_date",
            name="experience_date_order",
        ),
        CheckConstraint(
            "status = 'draft' OR submitted_at IS NOT NULL",
            name="submitted_timestamp_required",
        ),
    )


class InternshipReportCategory(TimestampedBase):
    __tablename__ = "internship_report_categories"

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("internship_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(48), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("report_id", "category", name="uq_report_category"),
        _in("category", REPORT_CATEGORIES, "category"),
    )


class InternshipReportConsent(TimestampedBase):
    __tablename__ = "internship_report_consents"

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("internship_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    consent_version: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("report_id", name="uq_internship_report_consents_report_id"),
        CheckConstraint(
            "(accepted = false AND accepted_at IS NULL) OR "
            "(accepted = true AND accepted_at IS NOT NULL)",
            name="accepted_timestamp_matches",
        ),
    )


class InternshipReportEvidence(TimestampedBase):
    __tablename__ = "internship_report_evidence"

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("internship_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_ref: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scan_state: Mapped[str] = mapped_column(
        String(32), default="quarantined", server_default="quarantined", nullable=False
    )
    scanner_result_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    retention_policy: Mapped[str] = mapped_column(
        String(80), default="configured", server_default="configured", nullable=False
    )

    __table_args__ = (
        UniqueConstraint("report_id", "checksum_sha256", name="uq_report_evidence_digest"),
        _in("scan_state", EVIDENCE_SCAN_STATES, "scan_state"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("length(checksum_sha256) = 64", name="checksum_length"),
    )


class ReporterIdentityVault(TimestampedBase):
    __tablename__ = "reporter_identity_vault"

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("internship_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reporter_lookup_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reporter_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint("report_id", name="uq_reporter_identity_vault_report_id"),
        CheckConstraint("length(reporter_lookup_hash) = 64", name="lookup_hash_length"),
        CheckConstraint("length(reporter_ciphertext) > 20", name="ciphertext_nontrivial"),
    )


class ReporterIdentityAccessRequest(TimestampedBase):
    __tablename__ = "reporter_identity_access_requests"

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("internship_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    safety_officer_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reason_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    reason_key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(
        String(24), default="pending", server_default="pending", nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(200), nullable=False, unique=True
    )
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _in("state", IDENTITY_ACCESS_STATES, "state"),
        CheckConstraint(
            "state != 'executed' OR executed_at IS NOT NULL",
            name="executed_timestamp_required",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "length(request_fingerprint) = 64",
            name="request_fingerprint_length",
        ),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )


class ReporterIdentityAccessApproval(TimestampedBase):
    __tablename__ = "reporter_identity_access_approvals"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("reporter_identity_access_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    approver_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)

    __table_args__ = (
        UniqueConstraint("request_id", "approver_user_id", name="uq_identity_access_approver"),
        _in("decision", IDENTITY_APPROVAL_DECISIONS, "decision"),
        _in("approver_role", ("safety_officer", "legal_reviewer"), "approver_role"),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )


class ModerationHandoff(TimestampedBase):
    __tablename__ = "moderation_handoffs"

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("internship_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    state: Mapped[str] = mapped_column(
        String(32), default="pending", server_default="pending", nullable=False, index=True
    )
    assigned_moderator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        UniqueConstraint("report_id", name="uq_moderation_handoffs_report_id"),
        _in("state", MODERATION_HANDOFF_STATES, "state"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class InternshipReportingOutbox(TimestampedBase):
    __tablename__ = "internship_reporting_outbox"

    event_kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(48), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _in("event_kind", REPORTING_OUTBOX_KINDS, "event_kind"),
        _in("state", REPORTING_OUTBOX_STATES, "state"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )


class ModerationCase(TimestampedBase):
    __tablename__ = "moderation_cases"

    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("internship_reports.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    state: Mapped[str] = mapped_column(
        String(40), default="pending", server_default="pending", nullable=False, index=True
    )
    assigned_moderator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("report_id", name="uq_moderation_cases_report_id"),
        _in("state", MODERATION_CASE_STATES, "state"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "(state = 'pending' AND assigned_moderator_user_id IS NULL AND claimed_at IS NULL) "
            "OR (state != 'pending' AND assigned_moderator_user_id IS NOT NULL AND claimed_at IS NOT NULL)",
            name="claim_state_consistent",
        ),
    )


class ModerationAssignment(TimestampedBase):
    __tablename__ = "moderation_assignments"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("moderation_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    moderator_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("case_id", "moderator_user_id", name="uq_moderation_assignment_actor"),
        CheckConstraint(
            "(active = true AND released_at IS NULL) OR (active = false AND released_at IS NOT NULL)",
            name="active_release_consistent",
        ),
    )


class ModerationAction(TimestampedBase):
    __tablename__ = "moderation_actions"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("moderation_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    reason_key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    case_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        _in("action", MODERATION_ACTIONS, "action"),
        _in("reason_code", MODERATION_REASON_CODES, "reason_code"),
        CheckConstraint("length(reason_ciphertext) > 20", name="reason_ciphertext_nontrivial"),
        CheckConstraint("case_version >= 2", name="case_version_minimum"),
        CheckConstraint(
            "request_fingerprint IS NULL OR length(request_fingerprint) = 64",
            name="request_fingerprint_length",
        ),
    )


class DuplicateCluster(TimestampedBase):
    __tablename__ = "duplicate_clusters"

    organisation_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    organisation_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    explanation_code: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(
        String(24), default="candidate", server_default="candidate", nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        _in("category", REPORT_CATEGORIES, "category"),
        _in("state", DUPLICATE_CLUSTER_STATES, "state"),
        CheckConstraint("length(organisation_hash) = 64", name="organisation_hash_length"),
        CheckConstraint("length(organisation_ciphertext) > 20", name="organisation_ciphertext_nontrivial"),
        CheckConstraint("window_end >= window_start", name="window_order"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "request_fingerprint IS NULL OR length(request_fingerprint) = 64",
            name="request_fingerprint_length",
        ),
    )


class DuplicateClusterMember(TimestampedBase):
    __tablename__ = "duplicate_cluster_members"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("duplicate_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("internship_reports.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(48), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("cluster_id", "report_id", name="uq_duplicate_cluster_member"),
        Index(
            "uq_report_risk_cluster_category_active",
            "report_id",
            "category",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        _in("category", REPORT_CATEGORIES, "category"),
    )


class RiskSignal(TimestampedBase):
    __tablename__ = "risk_signals"

    cluster_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("duplicate_clusters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    neutral_label: Mapped[str] = mapped_column(String(160), nullable=False)
    report_count: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_reporter_count: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold_met: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    small_count_suppressed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    moderator_approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    safety_legal_approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    approval_vetoed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    publication_ready: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        UniqueConstraint("cluster_id", name="uq_risk_signals_cluster_id"),
        CheckConstraint("report_count >= distinct_reporter_count", name="reporter_count_bounded"),
        CheckConstraint("distinct_reporter_count >= 1", name="distinct_reporters_positive"),
        CheckConstraint("version >= 1", name="version_positive"),
        # Governance boundary: external counsel/security/target-runtime
        # approvals have not yet been recorded, so no application code or
        # configuration value can make a candidate publishable in this build.
        CheckConstraint("publication_ready = false", name="publication_disabled"),
    )


class RiskSignalApproval(TimestampedBase):
    __tablename__ = "risk_signal_approvals"

    risk_signal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("risk_signals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("risk_signal_id", "actor_user_id", name="uq_risk_signal_approval_actor"),
        _in("actor_role", RISK_APPROVAL_ROLES, "actor_role"),
        _in("decision", ("approve", "reject"), "decision"),
        _in("reason_code", RISK_APPROVAL_REASON_CODES, "reason_code"),
    )


class ModerationNotificationOutbox(TimestampedBase):
    __tablename__ = "moderation_notification_outbox"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("moderation_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("internship_reports.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_kind: Mapped[str] = mapped_column(String(48), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    __table_args__ = (
        _in("event_kind", ("report_information_requested", "moderation_decision_recorded"), "event_kind"),
        _in("state", MODERATION_OUTBOX_STATES, "state"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )


class PublishedRiskLabel(TimestampedBase):
    __tablename__ = "published_risk_labels"

    risk_signal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("risk_signals.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    # Opaque, stable identifier derived from a versioned UUIDv5 namespace over
    # a canonical public organisation name. It deliberately is not an FK to
    # internship_listings: reports may
    # concern an organisation that is no longer, or never was, in the catalogue.
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True,
    )
    neutral_label: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    public_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(
        String(32), default="moderated_aggregate", server_default="moderated_aggregate",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(24), default="published", server_default="published", nullable=False, index=True
    )
    last_reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        UniqueConstraint("risk_signal_id", name="uq_published_risk_labels_risk_signal_id"),
        _in("category", REPORT_CATEGORIES, "category"),
        _in("status", PUBLIC_RISK_LABEL_STATUSES, "status"),
        CheckConstraint("source_type = 'moderated_aggregate'", name="source_type"),
        CheckConstraint("public_count IS NULL OR public_count >= 5", name="public_count_suppressed"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )


class PublicationDecision(TimestampedBase):
    __tablename__ = "publication_decisions"

    risk_signal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("risk_signals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    published_label_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("published_risk_labels.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        _in("decision", PUBLICATION_DECISION_TYPES, "decision"),
        _in("reason_code", PUBLICATION_REASON_CODES, "reason_code"),
        CheckConstraint("expected_version >= 1", name="expected_version_positive"),
        CheckConstraint("length(request_fingerprint) = 64", name="request_fingerprint_length"),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )


class OrganisationResponseRequest(TimestampedBase):
    __tablename__ = "organisation_response_requests"

    published_label_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("published_risk_labels.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    target_response_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "organisation_responses.id",
            ondelete="RESTRICT",
            name="fk_org_response_requests_target_response",
            use_alter=True,
        ),
        nullable=True,
        index=True,
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    representative_ref_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    representative_verification_method: Mapped[str] = mapped_column(String(48), nullable=False)
    representative_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    representative_verified_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    request_kind: Mapped[str] = mapped_column(
        String(24), default="initial", server_default="initial", nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    state: Mapped[str] = mapped_column(
        String(24), default="pending", server_default="pending", nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    __table_args__ = (
        Index(
            "uq_response_requests_pending_initial_label",
            "published_label_id",
            unique=True,
            postgresql_where=text("state = 'pending' AND request_kind = 'initial' AND deleted_at IS NULL"),
            sqlite_where=text("state = 'pending' AND request_kind = 'initial' AND deleted_at IS NULL"),
        ),
        _in("state", ORGANISATION_RESPONSE_REQUEST_STATES, "state"),
        _in("request_kind", ORGANISATION_RESPONSE_REQUEST_KINDS, "request_kind"),
        _in(
            "representative_verification_method",
            ("manual_legal_review", "verified_domain_challenge", "qa_fixture"),
            "representative_verification_method",
        ),
        CheckConstraint("length(representative_ref_hash) = 64", name="representative_ref_hash_length"),
        CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        CheckConstraint("length(request_fingerprint) = 64", name="request_fingerprint_length"),
        CheckConstraint(
            "(state = 'responded' AND used_at IS NOT NULL) OR "
            "(state != 'responded' AND used_at IS NULL)",
            name="used_timestamp_matches",
        ),
        CheckConstraint(
            "(request_kind = 'initial' AND target_response_id IS NULL) OR "
            "(request_kind != 'initial' AND target_response_id IS NOT NULL)",
            name="target_response_matches_kind",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )


class OrganisationResponse(TimestampedBase):
    __tablename__ = "organisation_responses"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organisation_response_requests.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    published_label_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("published_risk_labels.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    supersedes_response_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organisation_responses.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    response_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    response_key_version: Mapped[str] = mapped_column(String(32), nullable=False)
    response_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(32), default="moderation_pending", server_default="moderation_pending",
        nullable=False, index=True,
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("request_id", name="uq_organisation_responses_request_id"),
        Index(
            "uq_organisation_responses_current_label",
            "published_label_id",
            unique=True,
            postgresql_where=text("is_current = true"),
            sqlite_where=text("is_current = 1"),
        ),
        _in("state", ORGANISATION_RESPONSE_STATES, "state"),
        CheckConstraint("length(response_ciphertext) > 20", name="response_ciphertext_nontrivial"),
        CheckConstraint("length(response_digest) = 64", name="response_digest_length"),
        CheckConstraint("length(request_fingerprint) = 64", name="request_fingerprint_length"),
        CheckConstraint(
            "(state = 'moderation_pending' AND moderated_at IS NULL) OR "
            "(state != 'moderation_pending' AND moderated_at IS NOT NULL)",
            name="moderated_timestamp_matches",
        ),
        CheckConstraint(
            "(state = 'approved' AND is_current = true) OR "
            "(state != 'approved' AND is_current = false)",
            name="current_matches_approved",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )


class ResponseModeration(TimestampedBase):
    __tablename__ = "response_moderation"

    response_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organisation_responses.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_version: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("response_id", name="uq_response_moderation_response_id"),
        _in("decision", RESPONSE_MODERATION_DECISIONS, "decision"),
        _in("reason_code", RESPONSE_MODERATION_REASON_CODES, "reason_code"),
        CheckConstraint("response_version >= 2", name="response_version_minimum"),
        CheckConstraint("length(request_fingerprint) = 64", name="request_fingerprint_length"),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )


class NotificationOutbox(TimestampedBase):
    __tablename__ = "notification_outbox"

    aggregate_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    event_kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Only response invitations need a delivery secret.  It is encrypted and
    # key-versioned, never put in payload_json/logs/audit, and a relay must erase
    # it after delivery.
    secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    secret_key_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending", nullable=False, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _in("event_kind", NOTIFICATION_OUTBOX_KINDS, "event_kind"),
        _in("state", NOTIFICATION_OUTBOX_STATES, "state"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        CheckConstraint(
            "(event_kind = 'organisation_response_requested' AND state IN ('pending', 'processing', 'failed') AND "
            "secret_ciphertext IS NOT NULL AND secret_key_version IS NOT NULL) OR "
            "(event_kind = 'organisation_response_requested' AND state IN ('sent', 'void') AND "
            "secret_ciphertext IS NULL AND secret_key_version IS NULL) OR "
            "(event_kind != 'organisation_response_requested' AND "
            "secret_ciphertext IS NULL AND secret_key_version IS NULL)",
            name="delivery_secret_scope",
        ),
        CheckConstraint(
            "(state = 'sent' AND sent_at IS NOT NULL) OR state != 'sent'",
            name="sent_timestamp_required",
        ),
        CheckConstraint(
            "(state = 'processing' AND claimed_at IS NOT NULL AND claim_token IS NOT NULL) OR "
            "(state != 'processing' AND claimed_at IS NULL AND claim_token IS NULL)",
            name="claim_timestamp_matches",
        ),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
