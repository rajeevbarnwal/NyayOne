"""Wave 1 foundation schema (SAATHI-58 settings/DPDP + SAATHI-63 law schools).

Explicit forward operations only; revision id kept <= 32 chars. UUID PKs,
timestamptz, indexed FKs with explicit ON DELETE, CHECK constraints, uniqueness
for idempotency/user-scoping. Comparison bound is config-driven (Product
decision 2026-07-27, SAATHI-63 comment 12569) — no limit baked into DDL.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_wave1_foundation"
down_revision: Union[str, None] = "0003_registration_security"
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


def _in(col, vals):
    return f"{col} IN ({', '.join(repr(v) for v in vals)})"


def upgrade() -> None:
    op.create_table(
        "user_settings",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("theme", sa.String(16), nullable=False, server_default="system"),
        sa.Column("language", sa.String(16), nullable=False, server_default="en"),
        sa.Column("notif_email", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notif_sms", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notif_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        *_ts(),
        sa.UniqueConstraint("user_id", name="uq_user_settings_user_id"),
        sa.CheckConstraint(_in("theme", ("system", "light", "dark")), name="ck_user_settings_theme"),
        sa.CheckConstraint("version >= 1", name="ck_user_settings_version_positive"),
    )
    op.create_index("ix_user_settings_user_id", "user_settings", ["user_id"])

    op.create_table(
        "privacy_preferences",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("policy_version", sa.String(40), nullable=False, server_default="dpdp-2023.v1"),
        *_ts(),
        sa.UniqueConstraint("user_id", "kind", name="uq_privacy_preferences_user_id"),
        sa.CheckConstraint(_in("kind", ("analytics", "marketing", "share_partners")), name="ck_privacy_preferences_kind"),
    )
    op.create_index("ix_privacy_preferences_user_id", "privacy_preferences", ["user_id"])

    op.create_table(
        "data_subject_requests",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("opaque_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("reauth_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmation_hash", sa.String(64), nullable=True),
        *_ts(),
        sa.UniqueConstraint("opaque_id", name="uq_data_subject_requests_opaque_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_data_subject_requests_idempotency_key"),
        sa.CheckConstraint(_in("kind", ("export", "delete")), name="ck_data_subject_requests_kind"),
        sa.CheckConstraint(_in("status", ("pending", "processing", "complete", "failed", "cancelled")), name="ck_data_subject_requests_status"),
    )
    op.create_index("ix_data_subject_requests_user_id", "data_subject_requests", ["user_id"])

    for tbl, extra in (
        ("export_jobs", [sa.Column("artifact_ref", sa.String(200), nullable=True)]),
        ("deletion_jobs", [sa.Column("mode", sa.String(16), nullable=False, server_default="anonymise")]),
    ):
        op.create_table(
            tbl,
            sa.Column("id", _UUID, primary_key=True),
            sa.Column("request_id", _UUID, sa.ForeignKey("data_subject_requests.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            *extra,
            *_ts(),
            sa.CheckConstraint(_in("status", ("pending", "processing", "complete", "failed")), name=f"ck_{tbl}_status"),
            *([sa.CheckConstraint(_in("mode", ("anonymise", "delete")), name="ck_deletion_jobs_mode")] if tbl == "deletion_jobs" else []),
        )
        op.create_index(f"ix_{tbl}_request_id", tbl, ["request_id"])

    op.create_table(
        "law_schools",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("state", sa.String(80), nullable=False),
        sa.Column("institution_type", sa.String(40), nullable=False),
        sa.Column("accreditation", sa.String(80), nullable=True),
        sa.Column("entrance_exam", sa.String(40), nullable=True),
        sa.Column("fees_min", sa.Integer(), nullable=True),
        sa.Column("fees_max", sa.Integer(), nullable=True),
        sa.Column("nirf_rank", sa.Integer(), nullable=True),
        *_ts(),
        sa.UniqueConstraint("slug", name="uq_law_schools_slug"),
        sa.CheckConstraint(_in("institution_type", ("national_law_university", "government", "private", "deemed")), name="ck_law_schools_institution_type"),
        sa.CheckConstraint("fees_min IS NULL OR fees_min >= 0", name="ck_law_schools_fees_min_nonneg"),
    )
    op.create_index("ix_law_schools_state", "law_schools", ["state"])
    op.create_index("ix_law_schools_institution_type", "law_schools", ["institution_type"])
    op.create_index("ix_law_schools_entrance_exam", "law_schools", ["entrance_exam"])

    op.create_table(
        "law_school_sources",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("url", sa.String(400), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("freshness_days", sa.Integer(), nullable=False, server_default="180"),
        *_ts(),
    )

    op.create_table(
        "law_school_programmes",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("school_id", _UUID, sa.ForeignKey("law_schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("degree", sa.String(80), nullable=False),
        sa.Column("duration_years", sa.Integer(), nullable=False),
        *_ts(),
        sa.CheckConstraint("duration_years > 0", name="ck_law_school_programmes_duration_positive"),
    )
    op.create_index("ix_law_school_programmes_school_id", "law_school_programmes", ["school_id"])
    op.create_index("ix_law_school_programmes_degree", "law_school_programmes", ["degree"])

    op.create_table(
        "law_school_facts",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("school_id", _UUID, sa.ForeignKey("law_schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("value", sa.String(400), nullable=False),
        sa.Column("source_id", _UUID, sa.ForeignKey("law_school_sources.id", ondelete="SET NULL"), nullable=True),
        *_ts(),
        sa.UniqueConstraint("school_id", "key", name="uq_law_school_facts_school_id"),
    )
    op.create_index("ix_law_school_facts_school_id", "law_school_facts", ["school_id"])
    op.create_index("ix_law_school_facts_source_id", "law_school_facts", ["source_id"])

    for tbl, extra in (
        ("saved_law_schools", []),
        ("law_school_follows", [sa.Column("notify_opt_in", sa.Boolean(), nullable=False, server_default=sa.false())]),
    ):
        op.create_table(
            tbl,
            sa.Column("id", _UUID, primary_key=True),
            sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("school_id", _UUID, sa.ForeignKey("law_schools.id", ondelete="CASCADE"), nullable=False),
            *extra,
            *_ts(),
            sa.UniqueConstraint("user_id", "school_id", name=f"uq_{tbl}_user_id"),
        )
        op.create_index(f"ix_{tbl}_user_id", tbl, ["user_id"])
        op.create_index(f"ix_{tbl}_school_id", tbl, ["school_id"])

    op.create_table(
        "comparison_sets",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("user_id", _UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        *_ts(),
    )
    op.create_index("ix_comparison_sets_user_id", "comparison_sets", ["user_id"])

    op.create_table(
        "comparison_items",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("set_id", _UUID, sa.ForeignKey("comparison_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("school_id", _UUID, sa.ForeignKey("law_schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        *_ts(),
        sa.UniqueConstraint("set_id", "school_id", name="uq_comparison_items_set_id"),
    )
    op.create_index("ix_comparison_items_set_id", "comparison_items", ["set_id"])
    op.create_index("ix_comparison_items_school_id", "comparison_items", ["school_id"])


def downgrade() -> None:
    for name in [
        "comparison_items", "comparison_sets", "law_school_follows", "saved_law_schools",
        "law_school_facts", "law_school_programmes", "law_school_sources", "law_schools",
        "deletion_jobs", "export_jobs", "data_subject_requests", "privacy_preferences",
        "user_settings",
    ]:
        op.drop_table(name)
