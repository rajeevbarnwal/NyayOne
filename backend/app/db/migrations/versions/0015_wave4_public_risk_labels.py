"""Governed, disabled-by-default Wave 4 risk-label projection schema.

Revision ID: 0015_wave4_public_risk_labels
Revises: 0014_saathi60_internships

The existing ``publication_ready = false`` database safeguard is deliberately
retained.  These tables make the approved workflow structurally testable but
cannot activate public labels before the separately recorded approvals.
"""
from __future__ import annotations

import hashlib
import unicodedata
import uuid

import sqlalchemy as sa
from alembic import op

revision: str = "0015_wave4_public_risk_labels"
down_revision: str | None = "0014_saathi60_internships"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)
_PUBLIC_ORGANISATION_NAMESPACE_V1 = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://legalsaathi.in/namespaces/public-organisation/v1",
)


def _public_organisation_id(value: str) -> uuid.UUID:
    canonical = unicodedata.normalize("NFC", " ".join(value.casefold().split()))
    return uuid.uuid5(_PUBLIC_ORGANISATION_NAMESPACE_V1, canonical)


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
    bind = op.get_bind()
    with op.batch_alter_table("internship_listings") as batch:
        batch.add_column(sa.Column("organisation_public_id", _UUID, nullable=True))
    for listing_id, organisation in bind.execute(sa.text(
        "SELECT id, organisation FROM internship_listings"
    )):
        bind.execute(
            sa.text(
                "UPDATE internship_listings SET organisation_public_id = :public_id "
                "WHERE id = :listing_id"
            ),
            {
                # Raw text statements do not apply SQLAlchemy's Uuid bind
                # processor on SQLite.  The canonical 32-hex representation
                # is accepted by both SQLite's CHAR storage and PostgreSQL's
                # native UUID input parser.
                "public_id": _public_organisation_id(organisation).hex,
                "listing_id": listing_id,
            },
        )
    with op.batch_alter_table("internship_listings") as batch:
        batch.alter_column("organisation_public_id", existing_type=_UUID, nullable=False)
    op.create_index(
        "ix_internship_listings_organisation_public_id",
        "internship_listings",
        ["organisation_public_id"],
    )
    invalid_legacy_roles = list(bind.execute(sa.text(
        "SELECT DISTINCT u.role FROM reporter_identity_access_approvals a "
        "JOIN users u ON u.id = a.approver_user_id "
        "WHERE u.role NOT IN ('safety_officer', 'legal_reviewer')"
    )).scalars())
    if invalid_legacy_roles:
        # Do not include role values or row identifiers in the error: operators
        # must reconcile the preserved governance records explicitly before
        # retrying this migration.
        raise RuntimeError(
            "legacy identity-access approvals require manual role reconciliation"
        )
    if bind.execute(sa.text(
        "SELECT 1 FROM reporter_identity_access_approvals "
        "WHERE metadata_json IS NOT NULL LIMIT 1"
    )).first() is not None:
        raise RuntimeError(
            "legacy identity-access approvals require metadata reconciliation"
        )
    if bind.execute(sa.text(
        "SELECT 1 FROM reporter_identity_access_requests "
        "WHERE metadata_json IS NOT NULL LIMIT 1"
    )).first() is not None:
        # Fail without echoing the legacy JSON or any row identifier.
        raise RuntimeError(
            "legacy identity-access requests require metadata reconciliation"
        )
    overlapping_cluster_sources = bind.execute(sa.text(
        "SELECT 1 FROM duplicate_cluster_members m "
        "JOIN duplicate_clusters c ON c.id = m.cluster_id "
        "WHERE m.deleted_at IS NULL "
        "GROUP BY m.report_id, c.category HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if overlapping_cluster_sources is not None:
        raise RuntimeError(
            "legacy risk-cluster memberships require manual category reconciliation"
        )
    with op.batch_alter_table("duplicate_cluster_members") as batch:
        batch.add_column(sa.Column("category", sa.String(48), nullable=True))
    bind.execute(sa.text(
        "UPDATE duplicate_cluster_members SET category = ("
        "SELECT category FROM duplicate_clusters "
        "WHERE duplicate_clusters.id = duplicate_cluster_members.cluster_id)"
    ))
    with op.batch_alter_table("duplicate_cluster_members") as batch:
        batch.alter_column("category", existing_type=sa.String(48), nullable=False)
        batch.drop_constraint("uq_report_duplicate_cluster", type_="unique")
        batch.create_check_constraint(
            "category",
            _in("category", (
                "unpaid_mismatch", "excessive_hours", "unsafe_environment", "harassment",
                "discrimination", "misleading_work", "non_response", "certificate_withheld",
                "stipend_delay_exploitative", "positive_experience",
            )),
        )
    op.create_index(
        "ix_duplicate_cluster_members_category",
        "duplicate_cluster_members",
        ["category"],
    )
    op.create_index(
        "uq_report_risk_cluster_category_active",
        "duplicate_cluster_members",
        ["report_id", "category"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )
    with op.batch_alter_table("moderation_actions") as batch:
        batch.add_column(sa.Column("request_fingerprint", sa.String(64), nullable=True))
        batch.create_check_constraint(
            "request_fingerprint_length",
            "request_fingerprint IS NULL OR length(request_fingerprint) = 64",
        )

    with op.batch_alter_table("duplicate_clusters") as batch:
        batch.add_column(sa.Column("actor_user_id", _UUID, nullable=True))
        batch.add_column(sa.Column("request_fingerprint", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_duplicate_clusters_actor_user_id_users",
            "users", ["actor_user_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "request_fingerprint_length",
            "request_fingerprint IS NULL OR length(request_fingerprint) = 64",
        )
    op.create_index("ix_duplicate_clusters_actor_user_id", "duplicate_clusters", ["actor_user_id"])

    with op.batch_alter_table("reporter_identity_access_requests") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(200), nullable=True))
        batch.add_column(sa.Column("request_fingerprint", sa.String(64), nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        batch.add_column(sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("version_positive", "version >= 1")
    request_rows = bind.execute(
        sa.text("SELECT id FROM reporter_identity_access_requests WHERE idempotency_key IS NULL")
    ).mappings()
    for row in request_rows:
        bind.execute(
            sa.text(
                "UPDATE reporter_identity_access_requests "
                "SET idempotency_key = :key, request_fingerprint = :fingerprint, "
                "expires_at = created_at, "
                "state = CASE WHEN state IN ('pending', 'approved') THEN 'expired' ELSE state END "
                "WHERE id = :id"
            ),
            {
                "key": f"legacy-identity-request:{row['id']}",
                "fingerprint": hashlib.sha256(
                    f"legacy-identity-request:{row['id']}".encode("utf-8")
                ).hexdigest(),
                "id": row["id"],
            },
        )
    with op.batch_alter_table("reporter_identity_access_requests") as batch:
        batch.alter_column("idempotency_key", existing_type=sa.String(200), nullable=False)
        batch.alter_column("request_fingerprint", existing_type=sa.String(64), nullable=False)
        batch.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.create_unique_constraint(
            "uq_reporter_identity_access_requests_idempotency_key", ["idempotency_key"]
        )
        batch.create_check_constraint(
            "request_fingerprint_length", "length(request_fingerprint) = 64"
        )
        batch.create_check_constraint("metadata_must_be_null", "metadata_json IS NULL")
    op.create_index(
        "ix_reporter_identity_access_requests_expires_at",
        "reporter_identity_access_requests",
        ["expires_at"],
    )

    with op.batch_alter_table("reporter_identity_access_approvals") as batch:
        batch.add_column(sa.Column("approver_role", sa.String(32), nullable=True))
        batch.add_column(sa.Column("idempotency_key", sa.String(200), nullable=True))
    approval_rows = bind.execute(sa.text(
        "SELECT a.id, u.role FROM reporter_identity_access_approvals a "
        "JOIN users u ON u.id = a.approver_user_id"
    )).mappings()
    for row in approval_rows:
        role = row["role"]
        bind.execute(
            sa.text(
                "UPDATE reporter_identity_access_approvals "
                "SET approver_role = :role, idempotency_key = :key WHERE id = :id"
            ),
            {
                "role": role,
                "key": f"legacy-identity-approval:{row['id']}",
                "id": row["id"],
            },
        )
    with op.batch_alter_table("reporter_identity_access_approvals") as batch:
        batch.alter_column("approver_role", existing_type=sa.String(32), nullable=False)
        batch.alter_column("idempotency_key", existing_type=sa.String(200), nullable=False)
        batch.create_unique_constraint(
            "uq_reporter_identity_access_approvals_idempotency_key", ["idempotency_key"]
        )
        batch.create_check_constraint(
            "approver_role", "approver_role IN ('safety_officer', 'legal_reviewer')"
        )
        batch.create_check_constraint("metadata_must_be_null", "metadata_json IS NULL")

    with op.batch_alter_table("risk_signals") as batch:
        batch.add_column(
            sa.Column("approval_vetoed", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    with op.batch_alter_table("risk_signal_approvals") as batch:
        batch.create_check_constraint(
            "reason_code",
            _in("reason_code", (
                "moderator_policy_check", "safety_policy_check",
                "qa_target_gate_approval", "qa_publication_veto",
                "risk_signal_veto",
            )),
        )

    op.create_table(
        "published_risk_labels",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("risk_signal_id", _UUID, sa.ForeignKey("risk_signals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("organisation_id", _UUID, nullable=False),
        sa.Column("neutral_label", sa.String(160), nullable=False),
        sa.Column("category", sa.String(48), nullable=False),
        sa.Column("public_count", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(32), server_default="moderated_aggregate", nullable=False),
        sa.Column("status", sa.String(24), server_default="published", nullable=False),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.UniqueConstraint("risk_signal_id", name="uq_published_risk_labels_risk_signal_id"),
        sa.CheckConstraint(_in("category", (
            "unpaid_mismatch", "excessive_hours", "unsafe_environment", "harassment",
            "discrimination", "misleading_work", "non_response", "certificate_withheld",
            "stipend_delay_exploitative", "positive_experience",
        )), name="category"),
        sa.CheckConstraint(_in("status", ("published", "withdrawn", "corrected")), name="status"),
        sa.CheckConstraint("source_type = 'moderated_aggregate'", name="source_type"),
        sa.CheckConstraint("public_count IS NULL OR public_count >= 5", name="public_count_suppressed"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
    for column in ("risk_signal_id", "organisation_id", "category", "status"):
        op.create_index(f"ix_published_risk_labels_{column}", "published_risk_labels", [column])

    op.create_table(
        "publication_decisions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("risk_signal_id", _UUID, sa.ForeignKey("risk_signals.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("published_label_id", _UUID, sa.ForeignKey("published_risk_labels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        *_ts(),
        sa.UniqueConstraint("idempotency_key", name="uq_publication_decisions_idempotency_key"),
        sa.CheckConstraint(_in("decision", ("publish", "withhold", "withdraw")), name="decision"),
        sa.CheckConstraint(_in("reason_code", (
            "qa_policy", "qa_governed_publication", "policy_approved",
            "risk_signal_veto", "administrative_withdrawal",
        )), name="reason_code"),
        sa.CheckConstraint("expected_version >= 1", name="expected_version_positive"),
        sa.CheckConstraint("length(request_fingerprint) = 64", name="request_fingerprint_length"),
        sa.CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
    for column in ("risk_signal_id", "published_label_id", "actor_user_id"):
        op.create_index(f"ix_publication_decisions_{column}", "publication_decisions", [column])

    op.create_table(
        "organisation_response_requests",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("published_label_id", _UUID, sa.ForeignKey("published_risk_labels.id", ondelete="RESTRICT"), nullable=False),
        # FK is added after organisation_responses exists (the response table
        # itself references this request table).
        sa.Column("target_response_id", _UUID, nullable=True),
        sa.Column("requested_by_user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("representative_ref_hash", sa.String(64), nullable=False),
        sa.Column("representative_verification_method", sa.String(48), nullable=False),
        sa.Column("representative_verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("representative_verified_by_user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("request_kind", sa.String(24), server_default="initial", nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.UniqueConstraint("token_hash", name="uq_organisation_response_requests_token_hash"),
        sa.UniqueConstraint("idempotency_key", name="uq_organisation_response_requests_idempotency_key"),
        sa.CheckConstraint(_in("state", ("pending", "responded", "expired", "revoked")), name="state"),
        sa.CheckConstraint(_in("request_kind", ("initial", "correction", "appeal")), name="request_kind"),
        sa.CheckConstraint(_in("representative_verification_method", (
            "manual_legal_review", "verified_domain_challenge", "qa_fixture",
        )), name="representative_verification_method"),
        sa.CheckConstraint("length(representative_ref_hash) = 64", name="representative_ref_hash_length"),
        sa.CheckConstraint("length(token_hash) = 64", name="token_hash_length"),
        sa.CheckConstraint("length(request_fingerprint) = 64", name="request_fingerprint_length"),
        sa.CheckConstraint("(state = 'responded' AND used_at IS NOT NULL) OR (state != 'responded' AND used_at IS NULL)", name="used_timestamp_matches"),
        sa.CheckConstraint("(request_kind = 'initial' AND target_response_id IS NULL) OR (request_kind != 'initial' AND target_response_id IS NOT NULL)", name="target_response_matches_kind"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
    for column in (
        "published_label_id", "requested_by_user_id", "representative_ref_hash",
        "representative_verified_by_user_id", "state", "expires_at",
    ):
        # ``representative_verified_by_user_id`` makes the conventional index
        # name longer than PostgreSQL's 63-byte identifier limit.  Mark the
        # generated name as convention-derived so SQLAlchemy applies its
        # deterministic truncation instead of rejecting the migration.
        op.create_index(
            op.f(f"ix_organisation_response_requests_{column}"),
            "organisation_response_requests",
            [column],
        )
    op.create_index(
        "uq_response_requests_pending_initial_label",
        "organisation_response_requests",
        ["published_label_id"],
        unique=True,
        postgresql_where=sa.text("state = 'pending' AND request_kind = 'initial' AND deleted_at IS NULL"),
        sqlite_where=sa.text("state = 'pending' AND request_kind = 'initial' AND deleted_at IS NULL"),
    )

    op.create_table(
        "organisation_responses",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("request_id", _UUID, sa.ForeignKey("organisation_response_requests.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("published_label_id", _UUID, sa.ForeignKey("published_risk_labels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("supersedes_response_id", _UUID, sa.ForeignKey("organisation_responses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("response_ciphertext", sa.Text(), nullable=False),
        sa.Column("response_key_version", sa.String(32), nullable=False),
        sa.Column("response_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), server_default="moderation_pending", nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("moderated_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint("request_id", name="uq_organisation_responses_request_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_organisation_responses_idempotency_key"),
        sa.CheckConstraint(_in("state", ("moderation_pending", "approved", "rejected", "withdrawn", "superseded")), name="state"),
        sa.CheckConstraint("length(response_ciphertext) > 20", name="response_ciphertext_nontrivial"),
        sa.CheckConstraint("length(response_digest) = 64", name="response_digest_length"),
        sa.CheckConstraint("length(request_fingerprint) = 64", name="request_fingerprint_length"),
        sa.CheckConstraint("(state = 'moderation_pending' AND moderated_at IS NULL) OR (state != 'moderation_pending' AND moderated_at IS NOT NULL)", name="moderated_timestamp_matches"),
        sa.CheckConstraint("(state = 'approved' AND is_current = true) OR (state != 'approved' AND is_current = false)", name="current_matches_approved"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
    for column in ("request_id", "published_label_id", "supersedes_response_id", "state"):
        op.create_index(f"ix_organisation_responses_{column}", "organisation_responses", [column])
    op.create_index(
        "uq_organisation_responses_current_label",
        "organisation_responses",
        ["published_label_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
        sqlite_where=sa.text("is_current = 1"),
    )
    with op.batch_alter_table("organisation_response_requests") as batch:
        batch.create_foreign_key(
            "fk_org_response_requests_target_response",
            "organisation_responses",
            ["target_response_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_organisation_response_requests_target_response_id",
        "organisation_response_requests",
        ["target_response_id"],
    )

    op.create_table(
        "response_moderation",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("response_id", _UUID, sa.ForeignKey("organisation_responses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("response_version", sa.Integer(), nullable=False),
        *_ts(),
        sa.UniqueConstraint("response_id", name="uq_response_moderation_response_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_response_moderation_idempotency_key"),
        sa.CheckConstraint(_in("decision", ("approve", "reject")), name="decision"),
        sa.CheckConstraint(_in("reason_code", (
            "qa_review", "verified_initial_response", "verified_factual_correction",
            "response_verified", "response_policy_violation",
        )), name="reason_code"),
        sa.CheckConstraint("response_version >= 2", name="response_version_minimum"),
        sa.CheckConstraint("length(request_fingerprint) = 64", name="request_fingerprint_length"),
        sa.CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
    for column in ("response_id", "actor_user_id"):
        op.create_index(f"ix_response_moderation_{column}", "response_moderation", [column])

    op.create_table(
        "notification_outbox",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("aggregate_type", sa.String(48), nullable=False),
        sa.Column("aggregate_id", _UUID, nullable=False),
        sa.Column("event_kind", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=True),
        sa.Column("secret_key_version", sa.String(32), nullable=True),
        sa.Column("state", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(36), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint("idempotency_key", name="uq_notification_outbox_idempotency_key"),
        sa.CheckConstraint(_in("event_kind", (
            "risk_label_published", "risk_label_withdrawn", "organisation_response_requested",
            "organisation_response_submitted", "organisation_response_decided",
        )), name="event_kind"),
        sa.CheckConstraint(_in("state", ("pending", "processing", "sent", "failed", "void")), name="state"),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
        sa.CheckConstraint(
            "(event_kind = 'organisation_response_requested' AND state IN ('pending', 'processing', 'failed') AND secret_ciphertext IS NOT NULL AND secret_key_version IS NOT NULL) OR "
            "(event_kind = 'organisation_response_requested' AND state IN ('sent', 'void') AND secret_ciphertext IS NULL AND secret_key_version IS NULL) OR "
            "(event_kind != 'organisation_response_requested' AND secret_ciphertext IS NULL AND secret_key_version IS NULL)",
            name="delivery_secret_scope",
        ),
        sa.CheckConstraint("(state = 'sent' AND sent_at IS NOT NULL) OR state != 'sent'", name="sent_timestamp_required"),
        sa.CheckConstraint("(state = 'processing' AND claimed_at IS NOT NULL AND claim_token IS NOT NULL) OR (state != 'processing' AND claimed_at IS NULL AND claim_token IS NULL)", name="claim_timestamp_matches"),
        sa.CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
    for column in ("aggregate_type", "aggregate_id", "event_kind", "state"):
        op.create_index(f"ix_notification_outbox_{column}", "notification_outbox", [column])


def downgrade() -> None:
    op.drop_index(
        "uq_response_requests_pending_initial_label",
        table_name="organisation_response_requests",
    )
    op.drop_index(
        "ix_organisation_response_requests_target_response_id",
        table_name="organisation_response_requests",
    )
    with op.batch_alter_table("organisation_response_requests") as batch:
        batch.drop_constraint(
            "fk_org_response_requests_target_response",
            type_="foreignkey",
        )
    tables = (
        ("notification_outbox", ("state", "event_kind", "aggregate_id", "aggregate_type")),
        ("response_moderation", ("actor_user_id", "response_id")),
        ("organisation_responses", ("state", "supersedes_response_id", "published_label_id", "request_id")),
        ("organisation_response_requests", (
            "expires_at", "state", "representative_verified_by_user_id",
            "representative_ref_hash", "requested_by_user_id", "published_label_id",
        )),
        ("publication_decisions", ("actor_user_id", "published_label_id", "risk_signal_id")),
        ("published_risk_labels", ("status", "category", "organisation_id", "risk_signal_id")),
    )
    for table, columns in tables:
        if table == "organisation_responses":
            op.drop_index("uq_organisation_responses_current_label", table_name=table)
        for column in columns:
            op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)
        op.drop_table(table)

    with op.batch_alter_table("risk_signals") as batch:
        batch.drop_column("approval_vetoed")

    with op.batch_alter_table("risk_signal_approvals") as batch:
        batch.drop_constraint(
            op.f("ck_risk_signal_approvals_reason_code"), type_="check"
        )

    op.drop_index(
        "uq_report_risk_cluster_category_active",
        table_name="duplicate_cluster_members",
    )
    op.drop_index(
        "ix_duplicate_cluster_members_category",
        table_name="duplicate_cluster_members",
    )
    with op.batch_alter_table("duplicate_cluster_members") as batch:
        batch.drop_constraint(op.f("ck_duplicate_cluster_members_category"), type_="check")
        batch.create_unique_constraint(
            "uq_report_duplicate_cluster", ["report_id", "cluster_id"]
        )
        batch.drop_column("category")

    op.drop_index("ix_duplicate_clusters_actor_user_id", table_name="duplicate_clusters")
    with op.batch_alter_table("duplicate_clusters") as batch:
        batch.drop_constraint(op.f("ck_duplicate_clusters_request_fingerprint_length"), type_="check")
        batch.drop_constraint("fk_duplicate_clusters_actor_user_id_users", type_="foreignkey")
        batch.drop_column("request_fingerprint")
        batch.drop_column("actor_user_id")

    with op.batch_alter_table("moderation_actions") as batch:
        batch.drop_constraint(op.f("ck_moderation_actions_request_fingerprint_length"), type_="check")
        batch.drop_column("request_fingerprint")

    with op.batch_alter_table("reporter_identity_access_approvals") as batch:
        batch.drop_constraint(op.f("ck_reporter_identity_access_approvals_metadata_must_be_null"), type_="check")
        batch.drop_constraint(op.f("ck_reporter_identity_access_approvals_approver_role"), type_="check")
        batch.drop_constraint("uq_reporter_identity_access_approvals_idempotency_key", type_="unique")
        batch.drop_column("idempotency_key")
        batch.drop_column("approver_role")

    op.drop_index(
        "ix_reporter_identity_access_requests_expires_at",
        table_name="reporter_identity_access_requests",
    )
    with op.batch_alter_table("reporter_identity_access_requests") as batch:
        batch.drop_constraint(
            op.f("ck_reporter_identity_access_requests_request_fingerprint_length"),
            type_="check",
        )
        batch.drop_constraint(
            op.f("ck_reporter_identity_access_requests_metadata_must_be_null"),
            type_="check",
        )
        batch.drop_constraint(op.f("ck_reporter_identity_access_requests_version_positive"), type_="check")
        batch.drop_constraint("uq_reporter_identity_access_requests_idempotency_key", type_="unique")
        batch.drop_column("version")
        batch.drop_column("expires_at")
        batch.drop_column("request_fingerprint")
        batch.drop_column("idempotency_key")

    op.drop_index(
        "ix_internship_listings_organisation_public_id",
        table_name="internship_listings",
    )
    with op.batch_alter_table("internship_listings") as batch:
        batch.drop_column("organisation_public_id")
