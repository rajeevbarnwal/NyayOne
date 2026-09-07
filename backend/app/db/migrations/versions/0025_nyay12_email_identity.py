"""NYAY-12 verified-email login identities with fail-closed legacy reconciliation.

No historical address is marked verified: the revision only creates the identity,
idempotency and reconciliation tables and records (hash-only) reconciliation rows
for institutional-email hashes that are duplicated across live student profiles.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
import sqlalchemy as sa
from alembic import op
revision = "0025_nyay12_email_identity"
down_revision = "0024_nyay11_authority_state"
branch_labels = None
depends_on = None



def _hex_only_sql(column: str) -> str:
    expression = column
    for character in "0123456789abcdef":
        expression = f"replace({expression}, '{character}', '')"
    return expression

_TABLES = ("user_email_identities", "email_identity_mutations", "email_identity_reconciliations")


def upgrade():
    op.create_table(
        "user_email_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("email_ct", sa.String(600), nullable=False),
        sa.Column("key_version", sa.String(8), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_state", sa.String(20), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=True),
        sa.Column("provider_receipt_hash", sa.String(64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("challenge_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("challenge_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.CheckConstraint("state IN ('pending', 'verified', 'removed')", name=op.f("ck_user_email_identities_state")),
        sa.CheckConstraint("verification_state IN ('none', 'pending_delivery', 'active', 'failed')", name=op.f("ck_user_email_identities_verification_state")),
        sa.CheckConstraint(f"length(email_hash) = 64 AND length({_hex_only_sql('email_hash')}) = 0", name=op.f("ck_user_email_identities_email_hash_shape")),
        sa.CheckConstraint("code_hash IS NULL OR length(code_hash) = 64", name=op.f("ck_user_email_identities_code_hash_shape")),
        sa.CheckConstraint("attempts >= 0 AND attempts <= 10", name=op.f("ck_user_email_identities_attempts_bounded")),
        sa.CheckConstraint("NOT is_primary OR state = 'verified'", name=op.f("ck_user_email_identities_primary_requires_verified")),
        sa.CheckConstraint("state <> 'verified' OR (verified_at IS NOT NULL AND code_hash IS NULL AND verification_state = 'none')", name=op.f("ck_user_email_identities_verified_shape")),
        sa.CheckConstraint("state <> 'removed' OR (removed_at IS NOT NULL AND NOT is_primary)", name=op.f("ck_user_email_identities_removed_shape")),
        sa.CheckConstraint("(verification_state = 'none' AND code_hash IS NULL) OR (verification_state <> 'none' AND challenge_issued_at IS NOT NULL AND challenge_expires_at IS NOT NULL)", name=op.f("ck_user_email_identities_challenge_shape")),
        sa.CheckConstraint("verification_state <> 'active' OR provider_receipt_hash IS NOT NULL", name=op.f("ck_user_email_identities_delivery_receipt")),
        sa.PrimaryKeyConstraint("id", name="pk_user_email_identities"),
    )
    op.create_index("ix_user_email_identities_user_id", "user_email_identities", ["user_id"], unique=False)
    op.create_index("ix_user_email_identities_email_hash", "user_email_identities", ["email_hash"], unique=False)
    op.create_index(
        "uq_user_email_identities_one_primary_per_user", "user_email_identities", ["user_id"], unique=True,
        postgresql_where=sa.text("is_primary = true"), sqlite_where=sa.text("is_primary = 1"),
    )
    op.create_index(
        "uq_user_email_identities_verified_email", "user_email_identities", ["email_hash"], unique=True,
        postgresql_where=sa.text("state = 'verified'"), sqlite_where=sa.text("state = 'verified'"),
    )
    op.create_index(
        "uq_user_email_identities_live_owner_email", "user_email_identities", ["user_id", "email_hash"], unique=True,
        postgresql_where=sa.text("state <> 'removed'"), sqlite_where=sa.text("state <> 'removed'"),
    )
    op.create_table(
        "email_identity_mutations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("outcome_ct", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("operation IN ('add', 'verify', 'resend', 'remove', 'primary')", name=op.f("ck_email_identity_mutations_operation")),
        sa.CheckConstraint("length(key_hash) = 64 AND length(fingerprint) = 64", name=op.f("ck_email_identity_mutations_shape")),
        sa.CheckConstraint("status_code >= 200 AND status_code <= 599", name=op.f("ck_email_identity_mutations_status_code")),
        sa.PrimaryKeyConstraint("id", name="pk_email_identity_mutations"),
        sa.UniqueConstraint("user_id", "operation", "key_hash", name="uq_email_identity_mutations_scope"),
    )
    op.create_index("ix_email_identity_mutations_user_id", "email_identity_mutations", ["user_id"], unique=False)
    op.create_table(
        "email_identity_reconciliations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email_hash", sa.String(64), nullable=False),
        sa.Column("holder_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("claimant_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.CheckConstraint("reason IN ('verified_collision', 'legacy_duplicate')", name=op.f("ck_email_identity_reconciliations_reason")),
        sa.CheckConstraint("state IN ('open', 'resolved')", name=op.f("ck_email_identity_reconciliations_state")),
        sa.CheckConstraint("length(email_hash) = 64", name=op.f("ck_email_identity_reconciliations_email_hash_shape")),
        sa.CheckConstraint("(state = 'open' AND resolved_at IS NULL) OR (state = 'resolved' AND resolved_at IS NOT NULL)", name=op.f("ck_email_identity_reconciliations_resolution_shape")),
        sa.PrimaryKeyConstraint("id", name="pk_email_identity_reconciliations"),
    )
    op.create_index("ix_email_identity_reconciliations_email_hash", "email_identity_reconciliations", ["email_hash"], unique=False)
    _reconcile_legacy_duplicates()


def _reconcile_legacy_duplicates():
    """Record duplicated live institutional-email hashes; never verify anything."""
    bind = op.get_bind()
    duplicates = bind.execute(
        sa.text(
            "SELECT institutional_email_hash AS email_hash, COUNT(*) AS occurrences "
            "FROM student_profiles WHERE institutional_email_hash IS NOT NULL AND deleted_at IS NULL "
            "GROUP BY institutional_email_hash HAVING COUNT(*) > 1 ORDER BY institutional_email_hash"
        )
    ).mappings().all()
    if not duplicates:
        return
    reconciliation = sa.table(
        "email_identity_reconciliations",
        sa.column("id", sa.Uuid()), sa.column("email_hash"), sa.column("holder_user_id", sa.Uuid()),
        sa.column("claimant_user_id", sa.Uuid()), sa.column("reason"), sa.column("state"),
        sa.column("resolved_at", sa.DateTime(timezone=True)), sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)), sa.column("metadata_json", sa.JSON()),
    )
    now = datetime.now(timezone.utc)
    bind.execute(
        reconciliation.insert(),
        [
            {
                "id": uuid.uuid4(), "email_hash": row["email_hash"], "holder_user_id": None,
                "claimant_user_id": None, "reason": "legacy_duplicate", "state": "open", "resolved_at": None,
                "created_at": now, "updated_at": now,
                "metadata_json": {"source": "student_profiles.institutional_email_hash", "occurrences": int(row["occurrences"])},
            }
            for row in duplicates
        ],
    )


def downgrade():
    bind = op.get_bind()
    for table in _TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise RuntimeError("email_identity_downgrade_requires_empty_graph")
    op.drop_index("ix_email_identity_reconciliations_email_hash", table_name="email_identity_reconciliations")
    op.drop_table("email_identity_reconciliations")
    op.drop_index("ix_email_identity_mutations_user_id", table_name="email_identity_mutations")
    op.drop_table("email_identity_mutations")
    for index in (
        "uq_user_email_identities_live_owner_email", "uq_user_email_identities_verified_email",
        "uq_user_email_identities_one_primary_per_user", "ix_user_email_identities_email_hash",
        "ix_user_email_identities_user_id",
    ):
        op.drop_index(index, table_name="user_email_identities")
    op.drop_table("user_email_identities")
