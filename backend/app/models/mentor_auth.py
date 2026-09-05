"""Server-owned tutor/lawyer ceremony and mentor-session authority (NYAY-22).

The browser receives only opaque HttpOnly cookies.  Every lookup value below is
the keyed digest of an opaque token; raw cookie values, identity-provider proof,
idempotency keys and profile values are deliberately unrepresentable.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import Base, TimestampedBase


MENTOR_CEREMONY_STATES = (
    "pending_invitation",
    "challenge_issued",
    "proof_verified",
    "exchanged",
    "expired",
    "revoked",
    "deleted",
)
MENTOR_CEREMONY_TERMINAL_STATES = frozenset({"exchanged", "expired", "revoked", "deleted"})
MENTOR_SESSION_STATES = (
    "active",
    "rotated_out",
    "expired",
    "revoked",
    "logged_out",
    "deleted",
)
MENTOR_SESSION_TERMINAL_STATES = frozenset(
    {"rotated_out", "expired", "revoked", "logged_out", "deleted"}
)
MENTOR_SESSION_TRANSITIONS = {
    "active": frozenset(MENTOR_SESSION_TERMINAL_STATES),
    "rotated_out": frozenset(),
    "expired": frozenset(),
    "revoked": frozenset(),
    "logged_out": frozenset(),
    "deleted": frozenset(),
}
MENTOR_ROLES = ("tutor", "lawyer_tutor")
MENTOR_PURPOSES = (
    "student_guidance",
    "legal_education",
    "document_review",
    "case_discussion",
)
MENTOR_INTENTS = ("mentor_session", "authority_deletion_step_up")
MENTOR_IDEMPOTENCY_STATES = ("pending", "succeeded", "failed", "erased")
MENTOR_INVITATION_STATES = ("pending", "accepted", "expired", "revoked", "deleted")
MENTOR_ENGAGEMENT_STATES = ("pending", "active", "expired", "revoked", "deleted")
MENTOR_PROOF_STATES = ("current", "expired", "revoked", "deleted")
MENTOR_STEP_UP_STATES = ("active", "consumed", "expired", "revoked", "deleted")
MENTOR_PROVIDER_RESULT_STATES = (
    "pending",
    "verified",
    "consumed",
    "rejected",
    "expired",
)
MENTOR_SUBJECT_CONSENT_STATES = ("granted", "revoked", "expired", "deleted")
MENTOR_RETENTION_BLOCK_REASONS = (
    "GRAPH_EXCEEDS_BATCH",
    "GRAPH_EXCEEDS_HARD_CAP",
)


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    rendered = ", ".join(repr(value) for value in values)
    return CheckConstraint(f"{column} IN ({rendered})", name=name)


def _hex64(column: str, name: str) -> CheckConstraint:
    expression = column
    for character in "0123456789abcdef":
        expression = f"replace({expression}, '{character}', '')"
    return CheckConstraint(
        f"length({column}) = 64 AND length({expression}) = 0",
        name=name,
    )


class MentorBootstrapAttempt(TimestampedBase):
    """Non-authoritative, pre-identity browser binding."""

    __tablename__ = "mentor_bootstrap_attempts"

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_role: Mapped[str] = mapped_column(String(24), nullable=False)
    purpose_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_mentor_bootstrap_attempts_token_hash"),
        _hex64("token_hash", "token_hash_shape"),
        _in("requested_role", MENTOR_ROLES, "requested_role"),
        _in("purpose_code", MENTOR_PURPOSES, "purpose_code"),
        _in("state", ("active", "consumed", "expired"), "state"),
        CheckConstraint(
            "(state = 'active' AND consumed_at IS NULL AND deleted_at IS NULL) OR "
            "(state IN ('consumed', 'expired') AND consumed_at IS NOT NULL)",
            name="lifecycle_shape",
        ),
    )


class MentorInvitation(TimestampedBase):
    """Purpose-bound owner prerequisite; never selected by a browser identifier."""

    __tablename__ = "mentor_invitations"

    subject_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    initiator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    initiator_session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    creation_idempotency_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    purpose_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    mentor_match_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    authority_domain_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mentor_role: Mapped[str] = mapped_column(String(24), nullable=False)
    purpose_code: Mapped[str] = mapped_column(String(32), nullable=False)
    consent_version: Mapped[str] = mapped_column(String(64), nullable=False)
    acceptance_text_version: Mapped[str] = mapped_column(String(64), nullable=False)
    disclosure_classes: Mapped[list] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        _hex64("mentor_match_hash", "mentor_match_hash_shape"),
        _hex64("authority_domain_hash", "authority_domain_hash_shape"),
        _hex64("initiator_session_hash", "initiator_session_hash_shape"),
        _hex64(
            "creation_idempotency_hash", "creation_idempotency_hash_shape"
        ),
        _in("mentor_role", MENTOR_ROLES, "mentor_role"),
        _in("purpose_code", MENTOR_PURPOSES, "purpose_code"),
        _in("state", MENTOR_INVITATION_STATES, "state"),
        CheckConstraint(
            "(deleted_at IS NULL AND subject_registration_id IS NOT NULL AND "
            "initiator_user_id IS NOT NULL) OR (deleted_at IS NOT NULL AND "
            "subject_registration_id IS NULL AND initiator_user_id IS NULL)",
            name="retention_linkage_shape",
        ),
        sa.Index(
            "uq_mentor_invitations_one_pending_match_purpose",
            "mentor_match_hash",
            "purpose_code",
            unique=True,
            postgresql_where=sa.text("state = 'pending'"),
            sqlite_where=sa.text("state = 'pending'"),
        ),
    )


class TutorProfileOwnershipProof(TimestampedBase):
    """Protected, current proof that one actor owns one active TutorProfile."""

    __tablename__ = "tutor_profile_ownership_proofs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tutor_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tutor_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_class: Mapped[str] = mapped_column(String(48), nullable=False)
    assurance_class: Mapped[str] = mapped_column(String(48), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    key_version: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="current", nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_class: Mapped[str] = mapped_column(
        String(48), default="mentor_proof_security", nullable=False
    )
    __table_args__ = (
        _hex64("provider_subject_hash", "provider_subject_hash_shape"),
        _hex64("evidence_digest", "evidence_digest_shape"),
        _in("state", MENTOR_PROOF_STATES, "state"),
        CheckConstraint(
            "(deleted_at IS NULL AND user_id IS NOT NULL AND tutor_profile_id IS NOT NULL) "
            "OR (deleted_at IS NOT NULL AND user_id IS NULL AND tutor_profile_id IS NULL)",
            name="retention_linkage_shape",
        ),
        sa.Index(
            "uq_tutor_profile_ownership_proofs_one_current",
            "tutor_profile_id",
            unique=True,
            postgresql_where=sa.text("state = 'current'"),
            sqlite_where=sa.text("state = 'current'"),
        ),
        sa.Index(
            "uq_tutor_profile_ownership_proofs_one_current_provider_subject",
            "provider_class",
            "provider_subject_hash",
            unique=True,
            postgresql_where=sa.text("state = 'current' AND deleted_at IS NULL"),
            sqlite_where=sa.text("state = 'current' AND deleted_at IS NULL"),
        ),
    )


class MentorCeremony(TimestampedBase):
    """Server-owned finite-state ceremony selected only by a cookie digest."""

    __tablename__ = "mentor_ceremonies"

    bootstrap_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("mentor_bootstrap_attempts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_seed_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_seed_key_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    predecessor_token_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    challenge_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intent: Mapped[str] = mapped_column(String(40), nullable=False)
    requested_role: Mapped[str | None] = mapped_column(String(24), nullable=True)
    purpose_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    privacy_notice_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state: Mapped[str] = mapped_column(String(24), default="challenge_issued", nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tutor_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tutor_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ownership_proof_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutor_profile_ownership_proofs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentor_invitations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recovery: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    verification_policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_class: Mapped[str] = mapped_column(
        String(48), default="mentor_ceremony_security", nullable=False
    )
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_mentor_ceremonies_token_hash"),
        UniqueConstraint(
            "predecessor_token_hash",
            name="uq_mentor_ceremonies_predecessor_token_hash",
        ),
        _hex64("token_hash", "token_hash_shape"),
        CheckConstraint(
            "(token_seed_ct IS NULL AND token_seed_key_version IS NULL) OR "
            "(token_seed_ct IS NOT NULL AND token_seed_key_version IS NOT NULL "
            "AND token_seed_ct LIKE token_seed_key_version || ':%')",
            name="token_seed_ciphertext_shape",
        ),
        CheckConstraint(
            "state NOT IN ('pending_invitation', 'challenge_issued', "
            "'proof_verified') OR token_seed_ct IS NOT NULL",
            name="live_state_requires_token_seed",
        ),
        CheckConstraint(
            "predecessor_token_hash IS NULL OR "
            "(length(predecessor_token_hash) = 64 AND "
            "length(replace(replace(replace(replace(replace(replace(replace("
            "replace(replace(replace(replace(replace(replace(replace(replace("
            "replace(predecessor_token_hash, '0', ''), '1', ''), '2', ''), "
            "'3', ''), '4', ''), '5', ''), '6', ''), '7', ''), '8', ''), "
            "'9', ''), 'a', ''), 'b', ''), 'c', ''), 'd', ''), 'e', ''), "
            "'f', '')) = 0)",
            name="predecessor_token_hash_shape",
        ),
        _hex64("challenge_hash", "challenge_hash_shape"),
        _in("intent", MENTOR_INTENTS, "intent"),
        _in("requested_role", MENTOR_ROLES, "requested_role"),
        _in("purpose_code", MENTOR_PURPOSES, "purpose_code"),
        _in("state", MENTOR_CEREMONY_STATES, "state"),
        CheckConstraint("generation >= 1", name="generation_positive"),
        CheckConstraint(
            "deleted_at IS NULL OR (bootstrap_attempt_id IS NULL AND actor_user_id IS NULL "
            "AND tutor_profile_id IS NULL AND ownership_proof_id IS NULL AND invitation_id IS NULL)",
            name="severed_state_has_no_authority_links",
        ),
        CheckConstraint(
            "deleted_at IS NOT NULL OR state NOT IN ('pending_invitation', "
            "'challenge_issued', 'proof_verified') OR "
            "((intent = 'mentor_session' AND bootstrap_attempt_id IS NOT NULL AND "
            "(state <> 'proof_verified' OR (actor_user_id IS NOT NULL AND "
            "tutor_profile_id IS NOT NULL AND ownership_proof_id IS NOT NULL AND "
            "invitation_id IS NOT NULL))) OR (intent = 'authority_deletion_step_up' "
            "AND actor_user_id IS NOT NULL AND tutor_profile_id IS NOT NULL AND "
            "ownership_proof_id IS NOT NULL))",
            name="live_state_requires_authority_links",
        ),
    )


class MentorProviderResult(TimestampedBase):
    """Server-to-server identity result bound to exactly one ceremony.

    The provider transaction exists before the browser leaves NyayOne.  A
    trusted backchannel adapter changes ``pending`` to ``verified`` and stores
    only protected digests plus bounded provenance.  No browser endpoint
    accepts any of these fields.
    """

    __tablename__ = "mentor_provider_results"

    ceremony_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentor_ceremonies.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    provider_class: Mapped[str] = mapped_column(String(48), nullable=False)
    assurance_class: Mapped[str] = mapped_column(String(48), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    issuer_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    audience_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(16), nullable=False)
    nonce_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    nonce_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_key_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    start_dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_subject_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    key_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retention_class: Mapped[str] = mapped_column(
        String(48), default="mentor_identity_evidence", nullable=False
    )
    __table_args__ = (
        _in("state", MENTOR_PROVIDER_RESULT_STATES, "state"),
        _hex64("issuer_hash", "issuer_hash_shape"),
        _hex64("audience_hash", "audience_hash_shape"),
        _hex64("nonce_hash", "nonce_hash_shape"),
        _hex64("correlation_hash", "correlation_hash_shape"),
        _in("algorithm", ("EdDSA",), "algorithm"),
        CheckConstraint("failure_count >= 0", name="failure_count_nonnegative"),
        CheckConstraint(
            "issued_at IS NULL OR expires_at > issued_at",
            name="positive_signed_interval",
        ),
        CheckConstraint(
            "(nonce_ct IS NULL AND correlation_ct IS NULL AND transaction_key_version IS NULL) OR "
            "(nonce_ct LIKE transaction_key_version || ':%' AND "
            "correlation_ct LIKE transaction_key_version || ':%')",
            name="transaction_ciphertext_shape",
        ),
        CheckConstraint(
            "state IN ('rejected', 'expired') OR ceremony_id IS NOT NULL",
            name="live_state_requires_ceremony",
        ),
        CheckConstraint(
            "(deleted_at IS NULL AND ceremony_id IS NOT NULL) OR "
            "(deleted_at IS NOT NULL AND ceremony_id IS NULL)",
            name="retention_linkage_shape",
        ),
        CheckConstraint(
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
            name="lifecycle_shape",
        ),
    )


class MentorSubjectConsent(TimestampedBase):
    """Owner/student consent created before, never by, mentor exchange."""

    __tablename__ = "mentor_subject_consents"

    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentor_invitations.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    subject_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("student_registrations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # This grant is an independent owner/student act.  The mentor acceptance
    # endpoint can consume it, but can never manufacture or widen it.
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    granting_session_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    grant_idempotency_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    guardian_consent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("guardian_consents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    purpose_code: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    disclosure_classes: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_class: Mapped[str] = mapped_column(
        String(48), default="mentor_subject_consent", nullable=False
    )
    __table_args__ = (
        _hex64("granting_session_hash", "granting_session_hash_shape"),
        _hex64("grant_idempotency_hash", "grant_idempotency_hash_shape"),
        _in("purpose_code", MENTOR_PURPOSES, "purpose_code"),
        _in("status", MENTOR_SUBJECT_CONSENT_STATES, "status"),
        CheckConstraint(
            "(deleted_at IS NULL AND invitation_id IS NOT NULL AND "
            "subject_registration_id IS NOT NULL AND granted_by_user_id IS NOT NULL) "
            "OR (deleted_at IS NOT NULL AND invitation_id IS NULL AND "
            "subject_registration_id IS NULL AND granted_by_user_id IS NULL AND "
            "guardian_consent_id IS NULL)",
            name="retention_linkage_shape",
        ),
    )


class MentorEngagement(TimestampedBase):
    __tablename__ = "mentor_engagements"

    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("mentor_invitations.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    subject_registration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mentor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tutor_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tutor_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    authority_domain_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose_code: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        _hex64("authority_domain_hash", "authority_domain_hash_shape"),
        _in("purpose_code", MENTOR_PURPOSES, "purpose_code"),
        _in("state", MENTOR_ENGAGEMENT_STATES, "state"),
        CheckConstraint(
            "(deleted_at IS NULL AND invitation_id IS NOT NULL AND "
            "subject_registration_id IS NOT NULL AND mentor_user_id IS NOT NULL AND "
            "tutor_profile_id IS NOT NULL) OR (deleted_at IS NOT NULL AND "
            "invitation_id IS NULL AND subject_registration_id IS NULL AND "
            "mentor_user_id IS NULL AND tutor_profile_id IS NULL)",
            name="retention_linkage_shape",
        ),
    )


class MentorConsent(TimestampedBase):
    __tablename__ = "mentor_consents"

    engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("mentor_engagements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    purpose_code: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    disclosure_classes: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="granted", nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("engagement_id", "purpose_code", "version", name="uq_mentor_consents_scope"),
        _in("purpose_code", MENTOR_PURPOSES, "purpose_code"),
        _in("status", ("granted", "revoked", "expired", "deleted"), "status"),
        CheckConstraint(
            "(deleted_at IS NULL AND engagement_id IS NOT NULL) OR "
            "(deleted_at IS NOT NULL AND engagement_id IS NULL)",
            name="retention_linkage_shape",
        ),
    )


class MentorSession(TimestampedBase):
    """A distinct, narrow mentor authority; never an owner-session role bit."""

    __tablename__ = "mentor_sessions"

    ceremony_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentor_ceremonies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    engagement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("mentor_engagements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tutor_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("tutor_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ownership_proof_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutor_profile_ownership_proofs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    consent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentor_consents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject_consent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentor_subject_consents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    authority_domain_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_seed_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_seed_key_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    mentor_role: Mapped[str] = mapped_column(String(24), nullable=False)
    purpose_code: Mapped[str] = mapped_column(String(32), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    permitted_profile_slices: Mapped[list] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(24), default="active", nullable=False)
    generation: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    successor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentor_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    retention_class: Mapped[str] = mapped_column(
        String(48), default="mentor_session_security", nullable=False
    )
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_mentor_sessions_token_hash"),
        _hex64("token_hash", "token_hash_shape"),
        CheckConstraint(
            "(token_seed_ct IS NULL AND token_seed_key_version IS NULL) OR "
            "(token_seed_ct IS NOT NULL AND token_seed_key_version IS NOT NULL "
            "AND token_seed_ct LIKE token_seed_key_version || ':%')",
            name="token_seed_ciphertext_shape",
        ),
        CheckConstraint(
            "(deleted_at IS NULL AND ceremony_id IS NOT NULL AND engagement_id IS NOT NULL "
            "AND actor_user_id IS NOT NULL AND tutor_profile_id IS NOT NULL "
            "AND ownership_proof_id IS NOT NULL AND consent_id IS NOT NULL AND "
            "subject_consent_id IS NOT NULL) OR (deleted_at IS NOT NULL AND "
            "ceremony_id IS NULL AND engagement_id IS NULL AND actor_user_id IS NULL "
            "AND tutor_profile_id IS NULL AND ownership_proof_id IS NULL AND "
            "consent_id IS NULL AND subject_consent_id IS NULL AND successor_id IS NULL)",
            name="retention_linkage_shape",
        ),
        CheckConstraint(
            "state <> 'active' OR token_seed_ct IS NOT NULL",
            name="active_state_requires_token_seed",
        ),
        _hex64("authority_domain_hash", "authority_domain_hash_shape"),
        _in("mentor_role", MENTOR_ROLES, "mentor_role"),
        _in("purpose_code", MENTOR_PURPOSES, "purpose_code"),
        _in("state", MENTOR_SESSION_STATES, "state"),
        CheckConstraint("generation >= 1", name="generation_positive"),
        CheckConstraint("expires_at > issued_at", name="positive_lifetime"),
        CheckConstraint(
            "(state = 'active' AND terminal_at IS NULL AND successor_id IS NULL) OR "
            "(state = 'rotated_out' AND terminal_at IS NOT NULL) OR "
            "(state IN ('expired', 'revoked', 'logged_out', 'deleted') AND terminal_at IS NOT NULL)",
            name="lifecycle_shape",
        ),
        sa.Index(
            "uq_mentor_sessions_one_active_per_actor_purpose",
            "actor_user_id",
            "purpose_code",
            unique=True,
            postgresql_where=sa.text("state = 'active'"),
            sqlite_where=sa.text("state = 'active'"),
        ),
    )


class MentorAuthorityStepUp(TimestampedBase):
    __tablename__ = "mentor_authority_step_ups"

    ceremony_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("mentor_ceremonies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mentor_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("mentor_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_seed_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_seed_key_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    intent: Mapped[str] = mapped_column(String(40), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_class: Mapped[str] = mapped_column(
        String(48), default="mentor_step_up_security", nullable=False
    )
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_mentor_authority_step_ups_token_hash"),
        _hex64("token_hash", "token_hash_shape"),
        CheckConstraint(
            "(token_seed_ct IS NULL AND token_seed_key_version IS NULL) OR "
            "(token_seed_ct IS NOT NULL AND token_seed_key_version IS NOT NULL "
            "AND token_seed_ct LIKE token_seed_key_version || ':%')",
            name="token_seed_ciphertext_shape",
        ),
        CheckConstraint(
            "(deleted_at IS NULL AND ceremony_id IS NOT NULL AND actor_user_id IS NOT NULL "
            "AND mentor_session_id IS NOT NULL) OR (deleted_at IS NOT NULL AND "
            "ceremony_id IS NULL AND actor_user_id IS NULL AND mentor_session_id IS NULL)",
            name="retention_linkage_shape",
        ),
        CheckConstraint(
            "state <> 'active' OR token_seed_ct IS NOT NULL",
            name="active_state_requires_token_seed",
        ),
        _hex64("fingerprint", "fingerprint_shape"),
        _in("intent", ("authority_deletion_step_up",), "intent"),
        _in("state", MENTOR_STEP_UP_STATES, "state"),
        sa.Index(
            "uq_mentor_authority_step_ups_one_active_per_actor",
            "actor_user_id",
            unique=True,
            postgresql_where=sa.text("state = 'active'"),
            sqlite_where=sa.text("state = 'active'"),
        ),
    )


class MentorIdempotencyRecord(Base):
    """Durable NYAY-9-style digest-bound replay ledger for every mutation."""

    __tablename__ = "mentor_idempotency_records"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    retention_class: Mapped[str] = mapped_column(
        String(48), default="mentor_idempotency_security", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa.func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("scope_hash", "operation", "idempotency_key_hash", name="uq_mentor_idempotency_records_scope"),
        _hex64("scope_hash", "scope_hash_shape"),
        _hex64("idempotency_key_hash", "idempotency_key_hash_shape"),
        _hex64("request_fingerprint", "request_fingerprint_shape"),
        _in("state", MENTOR_IDEMPOTENCY_STATES, "state"),
        CheckConstraint(
            "(state = 'pending' AND outcome_status IS NULL AND outcome_ct IS NULL AND key_version IS NULL) OR "
            "(state IN ('succeeded', 'failed') AND outcome_status IS NOT NULL AND outcome_ct IS NOT NULL "
            "AND key_version IS NOT NULL AND outcome_ct LIKE key_version || ':%') OR "
            "(state = 'erased' AND outcome_status IS NULL AND outcome_ct IS NULL AND key_version IS NULL)",
            name="outcome_shape",
        ),
    )


class MentorRateBucket(Base):
    """Bounded, digest-only abuse budget; no actor/IP value is retained."""

    __tablename__ = "mentor_rate_buckets"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "scope_hash", "operation", "window_started_at",
            name="uq_mentor_rate_buckets_scope_window",
        ),
        _hex64("scope_hash", "scope_hash_shape"),
        CheckConstraint("count >= 1", name="positive_count"),
        CheckConstraint("expires_at > window_started_at", name="positive_window"),
    )


class MentorAuditLink(Base):
    """Separately erasable reversible link for one immutable PII-free event.

    ``link_key_ct`` is an envelope-wrapped per-subject key and ``actor_link_ct``
    is encrypted with that key.  Erasure destroys both ciphertexts while the
    aggregate ``AuditEvent`` remains append-only and non-linkable.
    """

    __tablename__ = "mentor_audit_links"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    audit_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("audit_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    correlation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    link_key_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_link_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    retention_class: Mapped[str] = mapped_column(
        String(48), default="mentor_audit_reversible_link", nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    erased_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    __table_args__ = (
        _hex64("correlation_hash", "correlation_hash_shape"),
        CheckConstraint(
            "(erased_at IS NULL AND link_key_ct IS NOT NULL AND actor_link_ct IS NOT NULL "
            "AND key_version IS NOT NULL) OR "
            "(erased_at IS NOT NULL AND link_key_ct IS NULL AND actor_link_ct IS NULL "
            "AND key_version IS NULL)",
            name="crypto_erasure_shape",
        ),
    )


class MentorRetentionBlockedGraph(Base):
    """PII-free durable alert for a graph that cannot be severed atomically.

    The keyed graph fingerprint is used only while the still-linked terminal
    graph remains present.  It contains no row identifier or authority-domain
    value and lets the NYAY-19 retention review deduplicate repeated alerts.
    """

    __tablename__ = "mentor_retention_blocked_graphs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    graph_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    observed_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    review_queue: Mapped[str] = mapped_column(
        String(32), default="nyay19_retention_review", nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "graph_key_hash", name="uq_mentor_retention_blocked_graphs_key"
        ),
        _hex64("graph_key_hash", "graph_key_hash_shape"),
        _in("reason_code", MENTOR_RETENTION_BLOCK_REASONS, "reason_code"),
        _in("state", ("open", "resolved"), "state"),
        CheckConstraint(
            "observed_row_count > 0", name="observed_row_count_positive"
        ),
        CheckConstraint("occurrence_count > 0", name="occurrence_count_positive"),
        CheckConstraint(
            "review_queue = 'nyay19_retention_review'",
            name="review_queue_closed",
        ),
    )
