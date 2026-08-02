"""Wave 4 private internship reporting models (SAATHI-269 / SAATHI-450).

Reporter identity is physically separated from report content.  The report row
contains no user id, email, mobile or reversible identity.  Ownership is resolved
through ``reporter_identity_vault`` using a keyed lookup hash; the authorised
identity value is encrypted and key-versioned.

Public risk labels are deliberately absent from this module.  They remain behind
the Product/Safety gate owned by SAATHI-452/279 and are disabled by default.
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
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        _in("state", IDENTITY_ACCESS_STATES, "state"),
        CheckConstraint(
            "state != 'executed' OR executed_at IS NOT NULL",
            name="executed_timestamp_required",
        ),
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

    __table_args__ = (
        UniqueConstraint("request_id", "approver_user_id", name="uq_identity_access_approver"),
        _in("decision", IDENTITY_APPROVAL_DECISIONS, "decision"),
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
