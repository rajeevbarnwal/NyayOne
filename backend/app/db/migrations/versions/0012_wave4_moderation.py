"""Wave 4 internal moderation and aggregate-candidate schema (SAATHI-274).

This revision creates no public risk-label projection.  ``risk_signals`` is an
internal, privacy-safe candidate table and carries a database CHECK forcing
``publication_ready = false`` until the separately approved SAATHI-279 revision.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_wave4_moderation"
down_revision: Union[str, None] = "0011_wave4_private_reporting"
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
    # The ActorContext already supported moderators, but the physical users
    # constraint did not.  Add the two-person safety/legal roles required by
    # the approved policy so assignment/approval FKs point at real users.
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_role", type_="check")
        batch.create_check_constraint(
            "ck_users_role",
            _in("role", ("student", "lawyer", "admin", "moderator", "safety_officer", "legal_reviewer")),
        )

    op.create_table(
        "moderation_cases",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("report_id", _UUID, sa.ForeignKey("internship_reports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("state", sa.String(40), server_default="pending", nullable=False),
        sa.Column("assigned_moderator_user_id", _UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint("report_id", name="uq_moderation_cases_report_id"),
        sa.CheckConstraint(
            _in("state", ("pending", "under_review", "approved_aggregate_only", "rejected", "needs_information")),
            name="state",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint(
            "(state = 'pending' AND assigned_moderator_user_id IS NULL AND claimed_at IS NULL) "
            "OR (state != 'pending' AND assigned_moderator_user_id IS NOT NULL AND claimed_at IS NOT NULL)",
            name="claim_state_consistent",
        ),
    )
    op.create_index("ix_moderation_cases_report_id", "moderation_cases", ["report_id"])
    op.create_index("ix_moderation_cases_state", "moderation_cases", ["state"])
    op.create_index("ix_moderation_cases_assigned_moderator_user_id", "moderation_cases", ["assigned_moderator_user_id"])

    op.create_table(
        "moderation_assignments",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("case_id", _UUID, sa.ForeignKey("moderation_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("moderator_user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint("case_id", "moderator_user_id", name="uq_moderation_assignment_actor"),
        sa.CheckConstraint(
            "(active = true AND released_at IS NULL) OR (active = false AND released_at IS NOT NULL)",
            name="active_release_consistent",
        ),
    )
    op.create_index("ix_moderation_assignments_case_id", "moderation_assignments", ["case_id"])
    op.create_index("ix_moderation_assignments_moderator_user_id", "moderation_assignments", ["moderator_user_id"])

    op.create_table(
        "moderation_actions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("case_id", _UUID, sa.ForeignKey("moderation_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        sa.Column("reason_ciphertext", sa.Text(), nullable=False),
        sa.Column("reason_key_version", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        *_ts(),
        sa.UniqueConstraint("idempotency_key", name="uq_moderation_actions_idempotency_key"),
        sa.CheckConstraint(_in("action", ("claim", "needs_information", "approve_aggregate_only", "reject")), name="action"),
        sa.CheckConstraint(
            _in("reason_code", ("review_started", "more_information_required", "aggregate_criteria_met", "insufficient_or_unverifiable")),
            name="reason_code",
        ),
        sa.CheckConstraint("length(reason_ciphertext) > 20", name="reason_ciphertext_nontrivial"),
        sa.CheckConstraint("case_version >= 2", name="case_version_minimum"),
    )
    op.create_index("ix_moderation_actions_case_id", "moderation_actions", ["case_id"])
    op.create_index("ix_moderation_actions_actor_user_id", "moderation_actions", ["actor_user_id"])
    op.create_index("ix_moderation_actions_action", "moderation_actions", ["action"])

    op.create_table(
        "duplicate_clusters",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("organisation_hash", sa.String(64), nullable=False),
        sa.Column("organisation_ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.String(32), nullable=False),
        sa.Column("category", sa.String(48), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("explanation_code", sa.String(80), nullable=False),
        sa.Column("state", sa.String(24), server_default="candidate", nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.UniqueConstraint("idempotency_key", name="uq_duplicate_clusters_idempotency_key"),
        sa.CheckConstraint(_in("category", (
            "unpaid_mismatch", "excessive_hours", "unsafe_environment", "harassment", "discrimination",
            "misleading_work", "non_response", "certificate_withheld", "stipend_delay_exploitative",
            "positive_experience",
        )), name="category"),
        sa.CheckConstraint(_in("state", ("candidate", "suppressed", "eligible")), name="state"),
        sa.CheckConstraint("length(organisation_hash) = 64", name="organisation_hash_length"),
        sa.CheckConstraint("length(organisation_ciphertext) > 20", name="organisation_ciphertext_nontrivial"),
        sa.CheckConstraint("window_end >= window_start", name="window_order"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index("ix_duplicate_clusters_organisation_hash", "duplicate_clusters", ["organisation_hash"])
    op.create_index("ix_duplicate_clusters_category", "duplicate_clusters", ["category"])
    op.create_index("ix_duplicate_clusters_state", "duplicate_clusters", ["state"])

    op.create_table(
        "duplicate_cluster_members",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("cluster_id", _UUID, sa.ForeignKey("duplicate_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", _UUID, sa.ForeignKey("internship_reports.id", ondelete="RESTRICT"), nullable=False),
        *_ts(),
        sa.UniqueConstraint("cluster_id", "report_id", name="uq_duplicate_cluster_member"),
        sa.UniqueConstraint("report_id", "cluster_id", name="uq_report_duplicate_cluster"),
    )
    op.create_index("ix_duplicate_cluster_members_cluster_id", "duplicate_cluster_members", ["cluster_id"])
    op.create_index("ix_duplicate_cluster_members_report_id", "duplicate_cluster_members", ["report_id"])

    op.create_table(
        "risk_signals",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("cluster_id", _UUID, sa.ForeignKey("duplicate_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("neutral_label", sa.String(160), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("distinct_reporter_count", sa.Integer(), nullable=False),
        sa.Column("threshold_met", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("small_count_suppressed", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("moderator_approved", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("safety_legal_approved", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("publication_ready", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        sa.UniqueConstraint("cluster_id", name="uq_risk_signals_cluster_id"),
        sa.CheckConstraint("report_count >= distinct_reporter_count", name="reporter_count_bounded"),
        sa.CheckConstraint("distinct_reporter_count >= 1", name="distinct_reporters_positive"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("publication_ready = false", name="publication_disabled"),
    )
    op.create_index("ix_risk_signals_cluster_id", "risk_signals", ["cluster_id"])

    op.create_table(
        "risk_signal_approvals",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("risk_signal_id", _UUID, sa.ForeignKey("risk_signals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_user_id", _UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(64), nullable=False),
        *_ts(),
        sa.UniqueConstraint("risk_signal_id", "actor_user_id", name="uq_risk_signal_approval_actor"),
        sa.CheckConstraint(_in("actor_role", ("moderator", "safety_officer", "legal_reviewer")), name="actor_role"),
        sa.CheckConstraint(_in("decision", ("approve", "reject")), name="decision"),
    )
    op.create_index("ix_risk_signal_approvals_risk_signal_id", "risk_signal_approvals", ["risk_signal_id"])
    op.create_index("ix_risk_signal_approvals_actor_user_id", "risk_signal_approvals", ["actor_user_id"])

    op.create_table(
        "moderation_notification_outbox",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("case_id", _UUID, sa.ForeignKey("moderation_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", _UUID, sa.ForeignKey("internship_reports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_kind", sa.String(48), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        *_ts(),
        sa.UniqueConstraint("idempotency_key", name="uq_moderation_notification_outbox_idempotency_key"),
        sa.CheckConstraint(_in("event_kind", ("report_information_requested", "moderation_decision_recorded")), name="event_kind"),
        sa.CheckConstraint(_in("state", ("pending", "sent", "failed", "void")), name="state"),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )
    op.create_index("ix_moderation_notification_outbox_case_id", "moderation_notification_outbox", ["case_id"])
    op.create_index("ix_moderation_notification_outbox_report_id", "moderation_notification_outbox", ["report_id"])
    op.create_index("ix_moderation_notification_outbox_state", "moderation_notification_outbox", ["state"])

    # Upgrade safety: reports submitted before this revision already have a
    # moderation_handoff. Populate their cases so an upgrade cannot silently
    # strand valid reports outside the moderator queue. UUIDs are generated in
    # Python to keep this data migration portable across SQLite and PostgreSQL.
    bind = op.get_bind()
    existing = bind.execute(
        sa.text(
            """
            SELECT r.id AS report_id,
                   h.state AS handoff_state,
                   h.assigned_moderator_user_id AS assigned_id,
                   h.version AS handoff_version,
                   h.created_at AS handoff_created_at
              FROM internship_reports r
              JOIN moderation_handoffs h ON h.report_id = r.id
             WHERE r.deleted_at IS NULL AND h.deleted_at IS NULL
            """
        )
    ).mappings()
    now = datetime.now(timezone.utc)
    state_map = {
        "pending": "pending",
        "assigned": "under_review",
        "needs_information": "needs_information",
        "approved": "approved_aggregate_only",
        "rejected": "rejected",
    }
    cases = sa.table(
        "moderation_cases",
        sa.column("id", _UUID),
        sa.column("report_id", _UUID),
        sa.column("state", sa.String()),
        sa.column("assigned_moderator_user_id", _UUID),
        sa.column("version", sa.Integer()),
        sa.column("claimed_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
        sa.column("metadata_json", sa.JSON()),
    )
    for row in existing:
        report_id = row["report_id"]
        if not isinstance(report_id, uuid.UUID):
            report_id = uuid.UUID(str(report_id))
        assigned = row["assigned_id"]
        if assigned is not None and not isinstance(assigned, uuid.UUID):
            assigned = uuid.UUID(str(assigned))
        state = state_map.get(row["handoff_state"], "pending")
        # A legacy non-pending handoff without an assignee cannot satisfy the
        # new invariant. Leave it pending for a fresh, auditable claim.
        if state != "pending" and assigned is None:
            state = "pending"
        timestamp = row["handoff_created_at"] or now
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        bind.execute(
            cases.insert().values(
                id=uuid.uuid4(),
                report_id=report_id,
                state=state,
                assigned_moderator_user_id=(assigned if state != "pending" else None),
                version=max(1, int(row["handoff_version"] or 1)),
                claimed_at=(timestamp if state != "pending" else None),
                created_at=timestamp,
                updated_at=now,
                deleted_at=None,
                metadata_json=None,
            )
        )


def downgrade() -> None:
    for table, indexes in (
        ("moderation_notification_outbox", ("ix_moderation_notification_outbox_state", "ix_moderation_notification_outbox_report_id", "ix_moderation_notification_outbox_case_id")),
        ("risk_signal_approvals", ("ix_risk_signal_approvals_actor_user_id", "ix_risk_signal_approvals_risk_signal_id")),
        ("risk_signals", ("ix_risk_signals_cluster_id",)),
        ("duplicate_cluster_members", ("ix_duplicate_cluster_members_report_id", "ix_duplicate_cluster_members_cluster_id")),
        ("duplicate_clusters", ("ix_duplicate_clusters_state", "ix_duplicate_clusters_category", "ix_duplicate_clusters_organisation_hash")),
        ("moderation_actions", ("ix_moderation_actions_action", "ix_moderation_actions_actor_user_id", "ix_moderation_actions_case_id")),
        ("moderation_assignments", ("ix_moderation_assignments_moderator_user_id", "ix_moderation_assignments_case_id")),
        ("moderation_cases", ("ix_moderation_cases_assigned_moderator_user_id", "ix_moderation_cases_state", "ix_moderation_cases_report_id")),
    ):
        for index in indexes:
            op.drop_index(index, table_name=table)
        op.drop_table(table)

    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_role", type_="check")
        batch.create_check_constraint("ck_users_role", _in("role", ("student", "lawyer", "admin")))
