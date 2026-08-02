"""Wave 4 private internship reporting (SAATHI-269 / SAATHI-450).

Creates the real HTTP/PostgreSQL persistence boundary for S-86/S-87. Reporter
identity is stored only in a separate encrypted vault. Evidence stores opaque
object references and quarantine/scan metadata, never file bytes or filenames.
Public risk labels are intentionally not created by this revision.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_wave4_private_reporting"
down_revision: Union[str, None] = "0010_student_login_session"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    ]


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    op.create_table(
        "internship_reports",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("organisation_name", sa.String(160), server_default="", nullable=False),
        sa.Column("listing_application_ref", sa.String(120), server_default="", nullable=False),
        sa.Column("experience_start_date", sa.Date(), nullable=True),
        sa.Column("experience_end_date", sa.Date(), nullable=True),
        sa.Column("narrative", sa.Text(), server_default="", nullable=False),
        sa.Column("privacy_mode", sa.String(32), server_default="anonymous", nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("support_guidance_required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint("idempotency_key", name="uq_internship_reports_idempotency_key"),
        sa.CheckConstraint(
            _in("privacy_mode", ("anonymous", "private_to_platform")),
            name="privacy_mode",
        ),
        sa.CheckConstraint(
            _in(
                "status",
                ("draft", "moderation_pending", "needs_information", "approved", "rejected", "withdrawn"),
            ),
            name="status",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint(
            "experience_end_date IS NULL OR experience_start_date IS NULL "
            "OR experience_end_date >= experience_start_date",
            name="experience_date_order",
        ),
        sa.CheckConstraint(
            "status = 'draft' OR submitted_at IS NOT NULL",
            name="submitted_timestamp_required",
        ),
    )
    op.create_index("ix_internship_reports_status", "internship_reports", ["status"])

    op.create_table(
        "internship_report_categories",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("report_id", _UUID, sa.ForeignKey("internship_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(48), nullable=False),
        *_ts(),
        sa.UniqueConstraint("report_id", "category", name="uq_report_category"),
        sa.CheckConstraint(
            _in(
                "category",
                (
                    "unpaid_mismatch", "excessive_hours", "unsafe_environment", "harassment",
                    "discrimination", "misleading_work", "non_response", "certificate_withheld",
                    "stipend_delay_exploitative", "positive_experience",
                ),
            ),
            name="category",
        ),
    )
    op.create_index("ix_internship_report_categories_report_id", "internship_report_categories", ["report_id"])
    op.create_index("ix_internship_report_categories_category", "internship_report_categories", ["category"])

    op.create_table(
        "internship_report_consents",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("report_id", _UUID, sa.ForeignKey("internship_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("consent_version", sa.String(40), nullable=False),
        sa.Column("accepted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint("report_id", name="uq_internship_report_consents_report_id"),
        sa.CheckConstraint(
            "(accepted = false AND accepted_at IS NULL) OR "
            "(accepted = true AND accepted_at IS NOT NULL)",
            name="accepted_timestamp_matches",
        ),
    )
    op.create_index("ix_internship_report_consents_report_id", "internship_report_consents", ["report_id"])

    op.create_table(
        "internship_report_evidence",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("report_id", _UUID, sa.ForeignKey("internship_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_ref", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(80), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("checksum_sha256", sa.String(64), nullable=False),
        sa.Column("scan_state", sa.String(32), server_default="quarantined", nullable=False),
        sa.Column("scanner_result_code", sa.String(80), nullable=True),
        sa.Column("retention_policy", sa.String(80), server_default="configured", nullable=False),
        *_ts(),
        sa.UniqueConstraint("object_ref", name="uq_internship_report_evidence_object_ref"),
        sa.UniqueConstraint("report_id", "checksum_sha256", name="uq_report_evidence_digest"),
        sa.CheckConstraint(
            _in("scan_state", ("quarantined", "clean", "infected", "retryable_failure", "deleted")),
            name="scan_state",
        ),
        sa.CheckConstraint("size_bytes > 0", name="size_positive"),
        sa.CheckConstraint("length(checksum_sha256) = 64", name="checksum_length"),
    )
    op.create_index("ix_internship_report_evidence_report_id", "internship_report_evidence", ["report_id"])

    op.create_table(
        "reporter_identity_vault",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("report_id", _UUID, sa.ForeignKey("internship_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reporter_lookup_hash", sa.String(64), nullable=False),
        sa.Column("reporter_ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.String(32), nullable=False),
        *_ts(),
        sa.UniqueConstraint("report_id", name="uq_reporter_identity_vault_report_id"),
        sa.CheckConstraint("length(reporter_lookup_hash) = 64", name="lookup_hash_length"),
        sa.CheckConstraint("length(reporter_ciphertext) > 20", name="ciphertext_nontrivial"),
    )
    op.create_index("ix_reporter_identity_vault_report_id", "reporter_identity_vault", ["report_id"])
    op.create_index("ix_reporter_identity_vault_reporter_lookup_hash", "reporter_identity_vault", ["reporter_lookup_hash"])

    op.create_table(
        "reporter_identity_access_requests",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("report_id", _UUID, sa.ForeignKey("internship_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("safety_officer_user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason_ciphertext", sa.Text(), nullable=False),
        sa.Column("reason_key_version", sa.String(32), nullable=False),
        sa.Column("state", sa.String(24), server_default="pending", nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.CheckConstraint(
            _in("state", ("pending", "approved", "rejected", "executed", "expired")),
            name="state",
        ),
        sa.CheckConstraint("state != 'executed' OR executed_at IS NOT NULL", name="executed_timestamp_required"),
    )
    op.create_index("ix_reporter_identity_access_requests_report_id", "reporter_identity_access_requests", ["report_id"])
    op.create_index("ix_reporter_identity_access_requests_safety_officer_user_id", "reporter_identity_access_requests", ["safety_officer_user_id"])

    op.create_table(
        "reporter_identity_access_approvals",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("request_id", _UUID, sa.ForeignKey("reporter_identity_access_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approver_user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        *_ts(),
        sa.UniqueConstraint("request_id", "approver_user_id", name="uq_identity_access_approver"),
        sa.CheckConstraint(_in("decision", ("approve", "reject")), name="decision"),
    )
    op.create_index("ix_reporter_identity_access_approvals_request_id", "reporter_identity_access_approvals", ["request_id"])
    op.create_index("ix_reporter_identity_access_approvals_approver_user_id", "reporter_identity_access_approvals", ["approver_user_id"])

    op.create_table(
        "moderation_handoffs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("report_id", _UUID, sa.ForeignKey("internship_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(32), server_default="pending", nullable=False),
        sa.Column("assigned_moderator_user_id", _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.UniqueConstraint("report_id", name="uq_moderation_handoffs_report_id"),
        sa.CheckConstraint(
            _in("state", ("pending", "assigned", "needs_information", "approved", "rejected", "withdrawn")),
            name="state",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index("ix_moderation_handoffs_report_id", "moderation_handoffs", ["report_id"])
    op.create_index("ix_moderation_handoffs_state", "moderation_handoffs", ["state"])
    op.create_index("ix_moderation_handoffs_assigned_moderator_user_id", "moderation_handoffs", ["assigned_moderator_user_id"])

    op.create_table(
        "internship_reporting_outbox",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("event_kind", sa.String(48), nullable=False),
        sa.Column("aggregate_type", sa.String(48), nullable=False),
        sa.Column("aggregate_id", _UUID, nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint("idempotency_key", name="uq_internship_reporting_outbox_idempotency_key"),
        sa.CheckConstraint(
            _in("event_kind", ("report_submitted", "evidence_scan_requested", "moderation_handoff_created")),
            name="event_kind",
        ),
        sa.CheckConstraint(_in("state", ("pending", "sent", "failed", "void")), name="state"),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )
    op.create_index("ix_internship_reporting_outbox_event_kind", "internship_reporting_outbox", ["event_kind"])
    op.create_index("ix_internship_reporting_outbox_aggregate_id", "internship_reporting_outbox", ["aggregate_id"])
    op.create_index("ix_internship_reporting_outbox_state", "internship_reporting_outbox", ["state"])


def downgrade() -> None:
    op.drop_index("ix_internship_reporting_outbox_state", table_name="internship_reporting_outbox")
    op.drop_index("ix_internship_reporting_outbox_aggregate_id", table_name="internship_reporting_outbox")
    op.drop_index("ix_internship_reporting_outbox_event_kind", table_name="internship_reporting_outbox")
    op.drop_table("internship_reporting_outbox")
    op.drop_index("ix_moderation_handoffs_assigned_moderator_user_id", table_name="moderation_handoffs")
    op.drop_index("ix_moderation_handoffs_state", table_name="moderation_handoffs")
    op.drop_index("ix_moderation_handoffs_report_id", table_name="moderation_handoffs")
    op.drop_table("moderation_handoffs")
    op.drop_index("ix_reporter_identity_access_approvals_approver_user_id", table_name="reporter_identity_access_approvals")
    op.drop_index("ix_reporter_identity_access_approvals_request_id", table_name="reporter_identity_access_approvals")
    op.drop_table("reporter_identity_access_approvals")
    op.drop_index("ix_reporter_identity_access_requests_safety_officer_user_id", table_name="reporter_identity_access_requests")
    op.drop_index("ix_reporter_identity_access_requests_report_id", table_name="reporter_identity_access_requests")
    op.drop_table("reporter_identity_access_requests")
    op.drop_index("ix_reporter_identity_vault_reporter_lookup_hash", table_name="reporter_identity_vault")
    op.drop_index("ix_reporter_identity_vault_report_id", table_name="reporter_identity_vault")
    op.drop_table("reporter_identity_vault")
    op.drop_index("ix_internship_report_evidence_report_id", table_name="internship_report_evidence")
    op.drop_table("internship_report_evidence")
    op.drop_index("ix_internship_report_consents_report_id", table_name="internship_report_consents")
    op.drop_table("internship_report_consents")
    op.drop_index("ix_internship_report_categories_category", table_name="internship_report_categories")
    op.drop_index("ix_internship_report_categories_report_id", table_name="internship_report_categories")
    op.drop_table("internship_report_categories")
    op.drop_index("ix_internship_reports_status", table_name="internship_reports")
    op.drop_table("internship_reports")
