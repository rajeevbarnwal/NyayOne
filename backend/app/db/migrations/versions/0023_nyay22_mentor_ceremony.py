"""Install the server-owned tutor/lawyer ceremony and mentor session graph.

Revision ID: 0023_nyay22_mentor_ceremony
Revises: 0022_nyay9_owner_profile_api

Raw cookies, identity proof, idempotency keys and profile values are deliberately
absent.  Only keyed digests, closed lifecycle state, purpose/consent versions,
and server-derived relational authority are representable.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision: str = "0023_nyay22_mentor_ceremony"
down_revision: str | None = "0022_nyay9_owner_profile_api"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)
_PURPOSES = "'student_guidance', 'legal_education', 'document_review', 'case_discussion'"
_ROLES = "'tutor', 'lawyer_tutor'"
_OWNED_TABLES = (
    "mentor_retention_blocked_graphs",
    "mentor_audit_links",
    "mentor_rate_buckets",
    "mentor_idempotency_records",
    "mentor_authority_step_ups",
    "mentor_sessions",
    "mentor_consents",
    "mentor_engagements",
    "mentor_subject_consents",
    "mentor_provider_results",
    "mentor_ceremonies",
    "tutor_profile_ownership_proofs",
    "mentor_invitations",
    "mentor_bootstrap_attempts",
)


class Nyay22MentorCeremonyDowngradeError(RuntimeError):
    """Downgrade would discard live or retained mentor authority."""


def _hex64(column: str) -> str:
    expression = column
    for character in "0123456789abcdef":
        expression = f"replace({expression}, '{character}', '')"
    return f"length({column}) = 64 AND length({expression}) = 0"


def _timestamped() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", _UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )


def _primary(table: str) -> sa.PrimaryKeyConstraint:
    return sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{table}"))


def _lock_owned_tables_for_downgrade(connection, tables: tuple[str, ...]) -> None:
    """Close PostgreSQL's count-then-drop race in deterministic order."""

    if connection.dialect.name != "postgresql":
        return
    for table in sorted(tables):
        # Names come only from the closed, source-controlled tuple above.
        connection.execute(
            sa.text(f'LOCK TABLE "{table}" IN ACCESS EXCLUSIVE MODE')
        )


def upgrade() -> None:
    op.create_table(
        "mentor_bootstrap_attempts",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("requested_role", sa.String(24), nullable=False),
        sa.Column("purpose_code", sa.String(32), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamped(),
        _primary("mentor_bootstrap_attempts"),
        sa.UniqueConstraint("token_hash", name="uq_mentor_bootstrap_attempts_token_hash"),
        sa.CheckConstraint(_hex64("token_hash"), name=op.f("ck_mentor_bootstrap_attempts_token_hash_shape")),
        sa.CheckConstraint(f"requested_role IN ({_ROLES})", name=op.f("ck_mentor_bootstrap_attempts_requested_role")),
        sa.CheckConstraint(f"purpose_code IN ({_PURPOSES})", name=op.f("ck_mentor_bootstrap_attempts_purpose_code")),
        sa.CheckConstraint("state IN ('active', 'consumed', 'expired')", name=op.f("ck_mentor_bootstrap_attempts_state")),
        sa.CheckConstraint(
            "(state = 'active' AND consumed_at IS NULL AND deleted_at IS NULL) OR "
            "(state IN ('consumed', 'expired') AND consumed_at IS NOT NULL)",
            name=op.f("ck_mentor_bootstrap_attempts_lifecycle_shape"),
        ),
    )

    op.create_table(
        "mentor_invitations",
        sa.Column("subject_registration_id", _UUID, nullable=True),
        sa.Column("initiator_user_id", _UUID, nullable=True),
        sa.Column("initiator_session_hash", sa.String(64), nullable=False),
        sa.Column("creation_idempotency_hash", sa.String(64), nullable=False),
        sa.Column("purpose_policy_version", sa.String(64), nullable=False),
        sa.Column("mentor_match_hash", sa.String(64), nullable=False),
        sa.Column("authority_domain_hash", sa.String(64), nullable=False),
        sa.Column("mentor_role", sa.String(24), nullable=False),
        sa.Column("purpose_code", sa.String(32), nullable=False),
        sa.Column("consent_version", sa.String(64), nullable=False),
        sa.Column("acceptance_text_version", sa.String(64), nullable=False),
        sa.Column("disclosure_classes", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamped(),
        _primary("mentor_invitations"),
        sa.ForeignKeyConstraint(
            ["subject_registration_id"], ["student_registrations.id"],
            name=op.f("fk_mentor_invitations_subject_registration_id_student_registrations"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["initiator_user_id"], ["users.id"],
            name=op.f("fk_mentor_invitations_initiator_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(_hex64("initiator_session_hash"), name=op.f("ck_mentor_invitations_initiator_session_hash_shape")),
        sa.CheckConstraint(_hex64("creation_idempotency_hash"), name=op.f("ck_mentor_invitations_creation_idempotency_hash_shape")),
        sa.CheckConstraint(_hex64("mentor_match_hash"), name=op.f("ck_mentor_invitations_mentor_match_hash_shape")),
        sa.CheckConstraint(_hex64("authority_domain_hash"), name=op.f("ck_mentor_invitations_authority_domain_hash_shape")),
        sa.CheckConstraint(f"mentor_role IN ({_ROLES})", name=op.f("ck_mentor_invitations_mentor_role")),
        sa.CheckConstraint(f"purpose_code IN ({_PURPOSES})", name=op.f("ck_mentor_invitations_purpose_code")),
        sa.CheckConstraint("state IN ('pending', 'accepted', 'expired', 'revoked', 'deleted')", name=op.f("ck_mentor_invitations_state")),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND subject_registration_id IS NOT NULL AND "
            "initiator_user_id IS NOT NULL) OR (deleted_at IS NOT NULL AND "
            "subject_registration_id IS NULL AND initiator_user_id IS NULL)",
            name=op.f("ck_mentor_invitations_retention_linkage_shape"),
        ),
    )
    op.create_index(op.f("ix_mentor_invitations_subject_registration_id"), "mentor_invitations", ["subject_registration_id"])
    op.create_index(op.f("ix_mentor_invitations_initiator_user_id"), "mentor_invitations", ["initiator_user_id"])
    op.create_index(op.f("ix_mentor_invitations_mentor_match_hash"), "mentor_invitations", ["mentor_match_hash"])
    op.create_index(
        "uq_mentor_invitations_one_pending_match_purpose", "mentor_invitations",
        ["mentor_match_hash", "purpose_code"], unique=True,
        postgresql_where=sa.text("state = 'pending'"), sqlite_where=sa.text("state = 'pending'"),
    )

    op.create_table(
        "tutor_profile_ownership_proofs",
        sa.Column("user_id", _UUID, nullable=True),
        sa.Column("tutor_profile_id", _UUID, nullable=True),
        sa.Column("provider_class", sa.String(48), nullable=False),
        sa.Column("assurance_class", sa.String(48), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("provider_subject_hash", sa.String(64), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("key_version", sa.String(8), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_class", sa.String(48), nullable=False),
        *_timestamped(),
        _primary("tutor_profile_ownership_proofs"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_tutor_profile_ownership_proofs_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tutor_profile_id"], ["tutor_profiles.id"], name=op.f("fk_tutor_profile_ownership_proofs_tutor_profile_id_tutor_profiles"), ondelete="SET NULL"),
        sa.CheckConstraint(_hex64("provider_subject_hash"), name=op.f("ck_tutor_profile_ownership_proofs_provider_subject_hash_shape")),
        sa.CheckConstraint(_hex64("evidence_digest"), name=op.f("ck_tutor_profile_ownership_proofs_evidence_digest_shape")),
        sa.CheckConstraint("state IN ('current', 'expired', 'revoked', 'deleted')", name=op.f("ck_tutor_profile_ownership_proofs_state")),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND user_id IS NOT NULL AND tutor_profile_id IS NOT NULL) "
            "OR (deleted_at IS NOT NULL AND user_id IS NULL AND tutor_profile_id IS NULL)",
            name=op.f("ck_tutor_profile_ownership_proofs_retention_linkage_shape"),
        ),
    )
    op.create_index(op.f("ix_tutor_profile_ownership_proofs_user_id"), "tutor_profile_ownership_proofs", ["user_id"])
    op.create_index(op.f("ix_tutor_profile_ownership_proofs_tutor_profile_id"), "tutor_profile_ownership_proofs", ["tutor_profile_id"])
    op.create_index(
        "uq_tutor_profile_ownership_proofs_one_current",
        "tutor_profile_ownership_proofs",
        ["tutor_profile_id"],
        unique=True,
        postgresql_where=sa.text("state = 'current'"),
        sqlite_where=sa.text("state = 'current'"),
    )
    op.create_index(
        "uq_tutor_profile_ownership_proofs_one_current_provider_subject",
        "tutor_profile_ownership_proofs",
        ["provider_class", "provider_subject_hash"],
        unique=True,
        postgresql_where=sa.text("state = 'current' AND deleted_at IS NULL"),
        sqlite_where=sa.text("state = 'current' AND deleted_at IS NULL"),
    )

    op.create_table(
        "mentor_ceremonies",
        sa.Column("bootstrap_attempt_id", _UUID, nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_seed_ct", sa.Text(), nullable=True),
        sa.Column("token_seed_key_version", sa.String(8), nullable=True),
        sa.Column("predecessor_token_hash", sa.String(64), nullable=True),
        sa.Column("challenge_hash", sa.String(64), nullable=False),
        sa.Column("intent", sa.String(40), nullable=False),
        sa.Column("requested_role", sa.String(24), nullable=True),
        sa.Column("purpose_code", sa.String(32), nullable=True),
        sa.Column("privacy_notice_version", sa.String(64), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", _UUID, nullable=True),
        sa.Column("tutor_profile_id", _UUID, nullable=True),
        sa.Column("ownership_proof_id", _UUID, nullable=True),
        sa.Column("invitation_id", _UUID, nullable=True),
        sa.Column("recovery", sa.Boolean(), nullable=False),
        sa.Column("verification_policy_version", sa.String(64), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_class", sa.String(48), nullable=False),
        *_timestamped(),
        _primary("mentor_ceremonies"),
        sa.ForeignKeyConstraint(["bootstrap_attempt_id"], ["mentor_bootstrap_attempts.id"], name=op.f("fk_mentor_ceremonies_bootstrap_attempt_id_mentor_bootstrap_attempts"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_mentor_ceremonies_actor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tutor_profile_id"], ["tutor_profiles.id"], name=op.f("fk_mentor_ceremonies_tutor_profile_id_tutor_profiles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ownership_proof_id"], ["tutor_profile_ownership_proofs.id"], name=op.f("fk_mentor_ceremonies_ownership_proof_id_tutor_profile_ownership_proofs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invitation_id"], ["mentor_invitations.id"], name=op.f("fk_mentor_ceremonies_invitation_id_mentor_invitations"), ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash", name="uq_mentor_ceremonies_token_hash"),
        sa.UniqueConstraint(
            "predecessor_token_hash",
            name="uq_mentor_ceremonies_predecessor_token_hash",
        ),
        sa.CheckConstraint(_hex64("token_hash"), name=op.f("ck_mentor_ceremonies_token_hash_shape")),
        sa.CheckConstraint("(token_seed_ct IS NULL AND token_seed_key_version IS NULL) OR (token_seed_ct IS NOT NULL AND token_seed_key_version IS NOT NULL AND token_seed_ct LIKE token_seed_key_version || ':%')", name=op.f("ck_mentor_ceremonies_token_seed_ciphertext_shape")),
        sa.CheckConstraint(
            "state NOT IN ('pending_invitation', 'challenge_issued', "
            "'proof_verified') OR token_seed_ct IS NOT NULL",
            name=op.f("ck_mentor_ceremonies_live_state_requires_token_seed"),
        ),
        sa.CheckConstraint(
            "predecessor_token_hash IS NULL OR (" + _hex64("predecessor_token_hash") + ")",
            name=op.f("ck_mentor_ceremonies_predecessor_token_hash_shape"),
        ),
        sa.CheckConstraint(_hex64("challenge_hash"), name=op.f("ck_mentor_ceremonies_challenge_hash_shape")),
        sa.CheckConstraint("intent IN ('mentor_session', 'authority_deletion_step_up')", name=op.f("ck_mentor_ceremonies_intent")),
        sa.CheckConstraint(f"requested_role IN ({_ROLES})", name=op.f("ck_mentor_ceremonies_requested_role")),
        sa.CheckConstraint(f"purpose_code IN ({_PURPOSES})", name=op.f("ck_mentor_ceremonies_purpose_code")),
        sa.CheckConstraint("state IN ('pending_invitation', 'challenge_issued', 'proof_verified', 'exchanged', 'expired', 'revoked', 'deleted')", name=op.f("ck_mentor_ceremonies_state")),
        sa.CheckConstraint("generation >= 1", name=op.f("ck_mentor_ceremonies_generation_positive")),
        sa.CheckConstraint(
            "deleted_at IS NULL OR (bootstrap_attempt_id IS NULL AND actor_user_id IS NULL "
            "AND tutor_profile_id IS NULL AND ownership_proof_id IS NULL AND invitation_id IS NULL)",
            name=op.f("ck_mentor_ceremonies_severed_state_has_no_authority_links"),
        ),
        sa.CheckConstraint(
            "deleted_at IS NOT NULL OR state NOT IN ('pending_invitation', "
            "'challenge_issued', 'proof_verified') OR "
            "((intent = 'mentor_session' AND bootstrap_attempt_id IS NOT NULL AND "
            "(state <> 'proof_verified' OR (actor_user_id IS NOT NULL AND "
            "tutor_profile_id IS NOT NULL AND ownership_proof_id IS NOT NULL AND "
            "invitation_id IS NOT NULL))) OR (intent = 'authority_deletion_step_up' "
            "AND actor_user_id IS NOT NULL AND tutor_profile_id IS NOT NULL AND "
            "ownership_proof_id IS NOT NULL))",
            name=op.f("ck_mentor_ceremonies_live_state_requires_authority_links"),
        ),
    )
    op.create_index(op.f("ix_mentor_ceremonies_bootstrap_attempt_id"), "mentor_ceremonies", ["bootstrap_attempt_id"])
    op.create_index(op.f("ix_mentor_ceremonies_actor_user_id"), "mentor_ceremonies", ["actor_user_id"])
    op.create_index(op.f("ix_mentor_ceremonies_tutor_profile_id"), "mentor_ceremonies", ["tutor_profile_id"])

    op.create_table(
        "mentor_provider_results",
        sa.Column("ceremony_id", _UUID, nullable=True),
        sa.Column("provider_class", sa.String(48), nullable=False),
        sa.Column("assurance_class", sa.String(48), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("issuer_hash", sa.String(64), nullable=False),
        sa.Column("audience_hash", sa.String(64), nullable=False),
        sa.Column("algorithm", sa.String(16), nullable=False),
        sa.Column("nonce_hash", sa.String(64), nullable=False),
        sa.Column("correlation_hash", sa.String(64), nullable=False),
        sa.Column("nonce_ct", sa.Text(), nullable=True),
        sa.Column("correlation_ct", sa.Text(), nullable=True),
        sa.Column("transaction_key_version", sa.String(8), nullable=True),
        sa.Column("start_dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("provider_subject_hash", sa.String(64), nullable=True),
        sa.Column("evidence_digest", sa.String(64), nullable=True),
        sa.Column("key_version", sa.String(8), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_class", sa.String(48), nullable=False),
        *_timestamped(),
        _primary("mentor_provider_results"),
        sa.ForeignKeyConstraint(
            ["ceremony_id"],
            ["mentor_ceremonies.id"],
            name=op.f("fk_mentor_provider_results_ceremony_id_mentor_ceremonies"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'verified', 'consumed', 'rejected', 'expired')",
            name=op.f("ck_mentor_provider_results_state"),
        ),
        sa.CheckConstraint(_hex64("issuer_hash"), name=op.f("ck_mentor_provider_results_issuer_hash_shape")),
        sa.CheckConstraint(_hex64("audience_hash"), name=op.f("ck_mentor_provider_results_audience_hash_shape")),
        sa.CheckConstraint(_hex64("nonce_hash"), name=op.f("ck_mentor_provider_results_nonce_hash_shape")),
        sa.CheckConstraint(_hex64("correlation_hash"), name=op.f("ck_mentor_provider_results_correlation_hash_shape")),
        sa.CheckConstraint("algorithm IN ('EdDSA')", name=op.f("ck_mentor_provider_results_algorithm")),
        sa.CheckConstraint(
            "failure_count >= 0",
            name=op.f("ck_mentor_provider_results_failure_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "issued_at IS NULL OR expires_at > issued_at",
            name=op.f("ck_mentor_provider_results_positive_signed_interval"),
        ),
        sa.CheckConstraint(
            "(nonce_ct IS NULL AND correlation_ct IS NULL AND transaction_key_version IS NULL) OR "
            "(nonce_ct LIKE transaction_key_version || ':%' AND "
            "correlation_ct LIKE transaction_key_version || ':%')",
            name=op.f("ck_mentor_provider_results_transaction_ciphertext_shape"),
        ),
        sa.CheckConstraint(
            "state IN ('rejected', 'expired') OR ceremony_id IS NOT NULL",
            name=op.f("ck_mentor_provider_results_live_state_requires_ceremony"),
        ),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND ceremony_id IS NOT NULL) OR "
            "(deleted_at IS NOT NULL AND ceremony_id IS NULL)",
            name=op.f("ck_mentor_provider_results_retention_linkage_shape"),
        ),
        sa.CheckConstraint(
            "(state = 'pending' AND provider_subject_hash IS NULL AND "
            "evidence_digest IS NULL AND key_version IS NULL AND issued_at IS NULL "
            "AND consumed_at IS NULL) OR "
            "(state = 'verified' AND provider_subject_hash IS NOT NULL AND "
            "evidence_digest IS NOT NULL AND key_version IS NOT NULL AND "
            "issued_at IS NOT NULL AND consumed_at IS NULL) OR "
            "(state = 'consumed' AND provider_subject_hash IS NOT NULL AND "
            "evidence_digest IS NOT NULL AND key_version IS NOT NULL AND "
            "issued_at IS NOT NULL AND consumed_at IS NOT NULL) OR "
            "(state IN ('rejected', 'expired') AND consumed_at IS NOT NULL)",
            name=op.f("ck_mentor_provider_results_lifecycle_shape"),
        ),
    )
    op.create_index(
        op.f("ix_mentor_provider_results_ceremony_id"),
        "mentor_provider_results",
        ["ceremony_id"],
        unique=True,
    )

    op.create_table(
        "mentor_subject_consents",
        sa.Column("invitation_id", _UUID, nullable=True),
        sa.Column("subject_registration_id", _UUID, nullable=True),
        sa.Column("granted_by_user_id", _UUID, nullable=True),
        sa.Column("granting_session_hash", sa.String(64), nullable=False),
        sa.Column("grant_idempotency_hash", sa.String(64), nullable=False),
        sa.Column("purpose_policy_version", sa.String(64), nullable=False),
        sa.Column("guardian_consent_id", _UUID, nullable=True),
        sa.Column("purpose_code", sa.String(32), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("disclosure_classes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_class", sa.String(48), nullable=False),
        *_timestamped(),
        _primary("mentor_subject_consents"),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["mentor_invitations.id"],
            name=op.f("fk_mentor_subject_consents_invitation_id_mentor_invitations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["subject_registration_id"],
            ["student_registrations.id"],
            name=op.f("fk_mentor_subject_consents_subject_registration_id_student_registrations"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name=op.f("fk_mentor_subject_consents_granted_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["guardian_consent_id"],
            ["guardian_consents.id"],
            name=op.f("fk_mentor_subject_consents_guardian_consent_id_guardian_consents"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            _hex64("granting_session_hash"),
            name=op.f("ck_mentor_subject_consents_granting_session_hash_shape"),
        ),
        sa.CheckConstraint(
            _hex64("grant_idempotency_hash"),
            name=op.f("ck_mentor_subject_consents_grant_idempotency_hash_shape"),
        ),
        sa.CheckConstraint(f"purpose_code IN ({_PURPOSES})", name=op.f("ck_mentor_subject_consents_purpose_code")),
        sa.CheckConstraint(
            "status IN ('granted', 'revoked', 'expired', 'deleted')",
            name=op.f("ck_mentor_subject_consents_status"),
        ),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND invitation_id IS NOT NULL AND "
            "subject_registration_id IS NOT NULL AND granted_by_user_id IS NOT NULL) "
            "OR (deleted_at IS NOT NULL AND invitation_id IS NULL AND "
            "subject_registration_id IS NULL AND granted_by_user_id IS NULL AND "
            "guardian_consent_id IS NULL)",
            name=op.f("ck_mentor_subject_consents_retention_linkage_shape"),
        ),
    )
    op.create_index(
        op.f("ix_mentor_subject_consents_invitation_id"),
        "mentor_subject_consents",
        ["invitation_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_mentor_subject_consents_subject_registration_id"),
        "mentor_subject_consents",
        ["subject_registration_id"],
    )
    op.create_index(
        op.f("ix_mentor_subject_consents_granted_by_user_id"),
        "mentor_subject_consents",
        ["granted_by_user_id"],
    )

    op.create_table(
        "mentor_engagements",
        sa.Column("invitation_id", _UUID, nullable=True),
        sa.Column("subject_registration_id", _UUID, nullable=True),
        sa.Column("mentor_user_id", _UUID, nullable=True),
        sa.Column("tutor_profile_id", _UUID, nullable=True),
        sa.Column("authority_domain_hash", sa.String(64), nullable=False),
        sa.Column("purpose_code", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamped(),
        _primary("mentor_engagements"),
        sa.ForeignKeyConstraint(["invitation_id"], ["mentor_invitations.id"], name=op.f("fk_mentor_engagements_invitation_id_mentor_invitations"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_registration_id"], ["student_registrations.id"], name=op.f("fk_mentor_engagements_subject_registration_id_student_registrations"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mentor_user_id"], ["users.id"], name=op.f("fk_mentor_engagements_mentor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tutor_profile_id"], ["tutor_profiles.id"], name=op.f("fk_mentor_engagements_tutor_profile_id_tutor_profiles"), ondelete="SET NULL"),
        sa.UniqueConstraint("invitation_id", name=op.f("uq_mentor_engagements_invitation_id")),
        sa.CheckConstraint(_hex64("authority_domain_hash"), name=op.f("ck_mentor_engagements_authority_domain_hash_shape")),
        sa.CheckConstraint(f"purpose_code IN ({_PURPOSES})", name=op.f("ck_mentor_engagements_purpose_code")),
        sa.CheckConstraint("state IN ('pending', 'active', 'expired', 'revoked', 'deleted')", name=op.f("ck_mentor_engagements_state")),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND invitation_id IS NOT NULL AND "
            "subject_registration_id IS NOT NULL AND mentor_user_id IS NOT NULL AND "
            "tutor_profile_id IS NOT NULL) OR (deleted_at IS NOT NULL AND "
            "invitation_id IS NULL AND subject_registration_id IS NULL AND "
            "mentor_user_id IS NULL AND tutor_profile_id IS NULL)",
            name=op.f("ck_mentor_engagements_retention_linkage_shape"),
        ),
    )
    op.create_index(op.f("ix_mentor_engagements_subject_registration_id"), "mentor_engagements", ["subject_registration_id"])
    op.create_index(op.f("ix_mentor_engagements_mentor_user_id"), "mentor_engagements", ["mentor_user_id"])
    op.create_index(op.f("ix_mentor_engagements_tutor_profile_id"), "mentor_engagements", ["tutor_profile_id"])

    op.create_table(
        "mentor_consents",
        sa.Column("engagement_id", _UUID, nullable=True),
        sa.Column("purpose_code", sa.String(32), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("disclosure_classes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamped(),
        _primary("mentor_consents"),
        sa.ForeignKeyConstraint(["engagement_id"], ["mentor_engagements.id"], name=op.f("fk_mentor_consents_engagement_id_mentor_engagements"), ondelete="SET NULL"),
        sa.UniqueConstraint("engagement_id", "purpose_code", "version", name="uq_mentor_consents_scope"),
        sa.CheckConstraint(f"purpose_code IN ({_PURPOSES})", name=op.f("ck_mentor_consents_purpose_code")),
        sa.CheckConstraint("status IN ('granted', 'revoked', 'expired', 'deleted')", name=op.f("ck_mentor_consents_status")),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND engagement_id IS NOT NULL) OR "
            "(deleted_at IS NOT NULL AND engagement_id IS NULL)",
            name=op.f("ck_mentor_consents_retention_linkage_shape"),
        ),
    )
    op.create_index(op.f("ix_mentor_consents_engagement_id"), "mentor_consents", ["engagement_id"])

    op.create_table(
        "mentor_sessions",
        sa.Column("ceremony_id", _UUID, nullable=True),
        sa.Column("engagement_id", _UUID, nullable=True),
        sa.Column("actor_user_id", _UUID, nullable=True),
        sa.Column("tutor_profile_id", _UUID, nullable=True),
        sa.Column("ownership_proof_id", _UUID, nullable=True),
        sa.Column("consent_id", _UUID, nullable=True),
        sa.Column("subject_consent_id", _UUID, nullable=True),
        sa.Column("authority_domain_hash", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_seed_ct", sa.Text(), nullable=True),
        sa.Column("token_seed_key_version", sa.String(8), nullable=True),
        sa.Column("mentor_role", sa.String(24), nullable=False),
        sa.Column("purpose_code", sa.String(32), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("permitted_profile_slices", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("successor_id", _UUID, nullable=True),
        sa.Column("retention_class", sa.String(48), nullable=False),
        *_timestamped(),
        _primary("mentor_sessions"),
        sa.ForeignKeyConstraint(["ceremony_id"], ["mentor_ceremonies.id"], name=op.f("fk_mentor_sessions_ceremony_id_mentor_ceremonies"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["engagement_id"], ["mentor_engagements.id"], name=op.f("fk_mentor_sessions_engagement_id_mentor_engagements"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_mentor_sessions_actor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tutor_profile_id"], ["tutor_profiles.id"], name=op.f("fk_mentor_sessions_tutor_profile_id_tutor_profiles"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ownership_proof_id"], ["tutor_profile_ownership_proofs.id"], name=op.f("fk_mentor_sessions_ownership_proof_id_tutor_profile_ownership_proofs"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["consent_id"], ["mentor_consents.id"], name=op.f("fk_mentor_sessions_consent_id_mentor_consents"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["subject_consent_id"], ["mentor_subject_consents.id"], name=op.f("fk_mentor_sessions_subject_consent_id_mentor_subject_consents"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["successor_id"], ["mentor_sessions.id"], name=op.f("fk_mentor_sessions_successor_id_mentor_sessions"), ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash", name="uq_mentor_sessions_token_hash"),
        sa.CheckConstraint(_hex64("authority_domain_hash"), name=op.f("ck_mentor_sessions_authority_domain_hash_shape")),
        sa.CheckConstraint(_hex64("token_hash"), name=op.f("ck_mentor_sessions_token_hash_shape")),
        sa.CheckConstraint("(token_seed_ct IS NULL AND token_seed_key_version IS NULL) OR (token_seed_ct IS NOT NULL AND token_seed_key_version IS NOT NULL AND token_seed_ct LIKE token_seed_key_version || ':%')", name=op.f("ck_mentor_sessions_token_seed_ciphertext_shape")),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND ceremony_id IS NOT NULL AND engagement_id IS NOT NULL "
            "AND actor_user_id IS NOT NULL AND tutor_profile_id IS NOT NULL "
            "AND ownership_proof_id IS NOT NULL AND consent_id IS NOT NULL AND "
            "subject_consent_id IS NOT NULL) OR (deleted_at IS NOT NULL AND "
            "ceremony_id IS NULL AND engagement_id IS NULL AND actor_user_id IS NULL "
            "AND tutor_profile_id IS NULL AND ownership_proof_id IS NULL AND "
            "consent_id IS NULL AND subject_consent_id IS NULL AND successor_id IS NULL)",
            name=op.f("ck_mentor_sessions_retention_linkage_shape"),
        ),
        sa.CheckConstraint(
            "state <> 'active' OR token_seed_ct IS NOT NULL",
            name=op.f("ck_mentor_sessions_active_state_requires_token_seed"),
        ),
        sa.CheckConstraint(f"mentor_role IN ({_ROLES})", name=op.f("ck_mentor_sessions_mentor_role")),
        sa.CheckConstraint(f"purpose_code IN ({_PURPOSES})", name=op.f("ck_mentor_sessions_purpose_code")),
        sa.CheckConstraint("state IN ('active', 'rotated_out', 'expired', 'revoked', 'logged_out', 'deleted')", name=op.f("ck_mentor_sessions_state")),
        sa.CheckConstraint("generation >= 1", name=op.f("ck_mentor_sessions_generation_positive")),
        sa.CheckConstraint("expires_at > issued_at", name=op.f("ck_mentor_sessions_positive_lifetime")),
        sa.CheckConstraint(
            "(state = 'active' AND terminal_at IS NULL AND successor_id IS NULL) OR "
            "(state = 'rotated_out' AND terminal_at IS NOT NULL) OR "
            "(state IN ('expired', 'revoked', 'logged_out', 'deleted') AND terminal_at IS NOT NULL)",
            name=op.f("ck_mentor_sessions_lifecycle_shape"),
        ),
    )
    op.create_index(op.f("ix_mentor_sessions_ceremony_id"), "mentor_sessions", ["ceremony_id"])
    op.create_index(op.f("ix_mentor_sessions_engagement_id"), "mentor_sessions", ["engagement_id"])
    op.create_index(op.f("ix_mentor_sessions_actor_user_id"), "mentor_sessions", ["actor_user_id"])
    op.create_index(op.f("ix_mentor_sessions_tutor_profile_id"), "mentor_sessions", ["tutor_profile_id"])
    op.create_index(
        "uq_mentor_sessions_one_active_per_actor_purpose", "mentor_sessions",
        ["actor_user_id", "purpose_code"], unique=True,
        postgresql_where=sa.text("state = 'active'"), sqlite_where=sa.text("state = 'active'"),
    )

    op.create_table(
        "mentor_authority_step_ups",
        sa.Column("ceremony_id", _UUID, nullable=True),
        sa.Column("actor_user_id", _UUID, nullable=True),
        sa.Column("mentor_session_id", _UUID, nullable=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("token_seed_ct", sa.Text(), nullable=True),
        sa.Column("token_seed_key_version", sa.String(8), nullable=True),
        sa.Column("intent", sa.String(40), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_class", sa.String(48), nullable=False),
        *_timestamped(),
        _primary("mentor_authority_step_ups"),
        sa.ForeignKeyConstraint(["ceremony_id"], ["mentor_ceremonies.id"], name=op.f("fk_mentor_authority_step_ups_ceremony_id_mentor_ceremonies"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_mentor_authority_step_ups_actor_user_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mentor_session_id"], ["mentor_sessions.id"], name=op.f("fk_mentor_authority_step_ups_mentor_session_id_mentor_sessions"), ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash", name="uq_mentor_authority_step_ups_token_hash"),
        sa.CheckConstraint(_hex64("token_hash"), name=op.f("ck_mentor_authority_step_ups_token_hash_shape")),
        sa.CheckConstraint("(token_seed_ct IS NULL AND token_seed_key_version IS NULL) OR (token_seed_ct IS NOT NULL AND token_seed_key_version IS NOT NULL AND token_seed_ct LIKE token_seed_key_version || ':%')", name=op.f("ck_mentor_authority_step_ups_token_seed_ciphertext_shape")),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND ceremony_id IS NOT NULL AND actor_user_id IS NOT NULL "
            "AND mentor_session_id IS NOT NULL) OR (deleted_at IS NOT NULL AND "
            "ceremony_id IS NULL AND actor_user_id IS NULL AND mentor_session_id IS NULL)",
            name=op.f("ck_mentor_authority_step_ups_retention_linkage_shape"),
        ),
        sa.CheckConstraint(
            "state <> 'active' OR token_seed_ct IS NOT NULL",
            name=op.f("ck_mentor_authority_step_ups_active_state_requires_token_seed"),
        ),
        sa.CheckConstraint(_hex64("fingerprint"), name=op.f("ck_mentor_authority_step_ups_fingerprint_shape")),
        sa.CheckConstraint("intent IN ('authority_deletion_step_up')", name=op.f("ck_mentor_authority_step_ups_intent")),
        sa.CheckConstraint("state IN ('active', 'consumed', 'expired', 'revoked', 'deleted')", name=op.f("ck_mentor_authority_step_ups_state")),
    )
    op.create_index(op.f("ix_mentor_authority_step_ups_ceremony_id"), "mentor_authority_step_ups", ["ceremony_id"])
    op.create_index(
        "uq_mentor_authority_step_ups_one_active_per_actor",
        "mentor_authority_step_ups",
        ["actor_user_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
        sqlite_where=sa.text("state = 'active'"),
    )
    op.create_index(op.f("ix_mentor_authority_step_ups_actor_user_id"), "mentor_authority_step_ups", ["actor_user_id"])
    op.create_index(op.f("ix_mentor_authority_step_ups_mentor_session_id"), "mentor_authority_step_ups", ["mentor_session_id"])

    op.create_table(
        "mentor_idempotency_records",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("outcome_status", sa.Integer(), nullable=True),
        sa.Column("outcome_ct", sa.Text(), nullable=True),
        sa.Column("key_version", sa.String(8), nullable=True),
        sa.Column("retention_class", sa.String(48), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mentor_idempotency_records")),
        sa.UniqueConstraint("scope_hash", "operation", "idempotency_key_hash", name="uq_mentor_idempotency_records_scope"),
        sa.CheckConstraint(_hex64("scope_hash"), name=op.f("ck_mentor_idempotency_records_scope_hash_shape")),
        sa.CheckConstraint(_hex64("idempotency_key_hash"), name=op.f("ck_mentor_idempotency_records_idempotency_key_hash_shape")),
        sa.CheckConstraint(_hex64("request_fingerprint"), name=op.f("ck_mentor_idempotency_records_request_fingerprint_shape")),
        sa.CheckConstraint("state IN ('pending', 'succeeded', 'failed', 'erased')", name=op.f("ck_mentor_idempotency_records_state")),
        sa.CheckConstraint(
            "(state = 'pending' AND outcome_status IS NULL AND outcome_ct IS NULL AND key_version IS NULL) OR "
            "(state IN ('succeeded', 'failed') AND outcome_status IS NOT NULL AND outcome_ct IS NOT NULL "
            "AND key_version IS NOT NULL AND outcome_ct LIKE key_version || ':%') OR "
            "(state = 'erased' AND outcome_status IS NULL AND outcome_ct IS NULL AND key_version IS NULL)",
            name=op.f("ck_mentor_idempotency_records_outcome_shape"),
        ),
    )

    op.create_table(
        "mentor_rate_buckets",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mentor_rate_buckets")),
        sa.UniqueConstraint(
            "scope_hash",
            "operation",
            "window_started_at",
            name="uq_mentor_rate_buckets_scope_window",
        ),
        sa.CheckConstraint(
            _hex64("scope_hash"),
            name=op.f("ck_mentor_rate_buckets_scope_hash_shape"),
        ),
        sa.CheckConstraint(
            "count >= 1", name=op.f("ck_mentor_rate_buckets_positive_count")
        ),
        sa.CheckConstraint(
            "expires_at > window_started_at",
            name=op.f("ck_mentor_rate_buckets_positive_window"),
        ),
    )

    op.create_table(
        "mentor_audit_links",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("audit_event_id", _UUID, nullable=False),
        sa.Column("correlation_hash", sa.String(64), nullable=False),
        sa.Column("link_key_ct", sa.Text(), nullable=True),
        sa.Column("actor_link_ct", sa.Text(), nullable=True),
        sa.Column("key_version", sa.String(8), nullable=True),
        sa.Column("retention_class", sa.String(48), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mentor_audit_links")),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["audit_events.id"],
            name=op.f("fk_mentor_audit_links_audit_event_id_audit_events"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "audit_event_id", name=op.f("uq_mentor_audit_links_audit_event_id")
        ),
        sa.CheckConstraint(
            _hex64("correlation_hash"),
            name=op.f("ck_mentor_audit_links_correlation_hash_shape"),
        ),
        sa.CheckConstraint(
            "(erased_at IS NULL AND link_key_ct IS NOT NULL AND actor_link_ct IS NOT NULL "
            "AND key_version IS NOT NULL) OR "
            "(erased_at IS NOT NULL AND link_key_ct IS NULL AND actor_link_ct IS NULL "
            "AND key_version IS NULL)",
            name=op.f("ck_mentor_audit_links_crypto_erasure_shape"),
        ),
    )

    op.create_table(
        "mentor_retention_blocked_graphs",
        sa.Column("id", _UUID, nullable=False),
        sa.Column("graph_key_hash", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(40), nullable=False),
        sa.Column("observed_row_count", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False),
        sa.Column("review_queue", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_mentor_retention_blocked_graphs")
        ),
        sa.UniqueConstraint(
            "graph_key_hash", name="uq_mentor_retention_blocked_graphs_key"
        ),
        sa.CheckConstraint(
            _hex64("graph_key_hash"),
            name=op.f("ck_mentor_retention_blocked_graphs_graph_key_hash_shape"),
        ),
        sa.CheckConstraint(
            "reason_code IN ('GRAPH_EXCEEDS_BATCH', 'GRAPH_EXCEEDS_HARD_CAP')",
            name=op.f("ck_mentor_retention_blocked_graphs_reason_code"),
        ),
        sa.CheckConstraint(
            "state IN ('open', 'resolved')",
            name=op.f("ck_mentor_retention_blocked_graphs_state"),
        ),
        sa.CheckConstraint(
            "observed_row_count > 0",
            name=op.f(
                "ck_mentor_retention_blocked_graphs_observed_row_count_positive"
            ),
        ),
        sa.CheckConstraint(
            "occurrence_count > 0",
            name=op.f(
                "ck_mentor_retention_blocked_graphs_occurrence_count_positive"
            ),
        ),
        sa.CheckConstraint(
            "review_queue = 'nyay19_retention_review'",
            name=op.f("ck_mentor_retention_blocked_graphs_review_queue_closed"),
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    _lock_owned_tables_for_downgrade(connection, _OWNED_TABLES)
    for table in _OWNED_TABLES:
        count = connection.scalar(sa.text(f"SELECT count(*) FROM {table}"))
        if type(count) is not int or count != 0:
            raise Nyay22MentorCeremonyDowngradeError(
                "NYAY-22 mentor authority downgrade rejected durable data"
            )
    for table in _OWNED_TABLES:
        op.drop_table(table)
