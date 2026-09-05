"""NYAY-11 authority records. Proof material is hashed; audit has no owner link."""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

GUARDIAN_STATES = ("NOT_REQUIRED", "REQUIRED_PENDING", "VERIFIED", "REJECTED", "REVOKED")
INSTITUTIONAL_STATES = ("UNVERIFIED", "PENDING", "VERIFIED", "REJECTED", "EXPIRED", "REVOKED")
AUTHORITY_CLASSES = ("student", "guardian", "owner", "platform_owner", "assigned_institutional_reviewer", "admin", "server", "server_attested_guardian", "server_age_policy", "server_clock", "server_profile_policy")
AUDIT_TRANSITIONS = tuple(sorted({
    *(f"{source}_TO_{target}" for states in (GUARDIAN_STATES, INSTITUTIONAL_STATES) for source in states for target in states if source != target),
    *(f"GUARDIAN_{state}" for state in GUARDIAN_STATES),
    *(f"INSTITUTIONAL_{state}" for state in INSTITUTIONAL_STATES),
    "REVIEW_RETURNED_TO_QUEUE", "DEPENDENT_PROOF_INVALIDATED", "REVIEWER_ASSIGNED",
    "EMAIL_PROOF_VERIFIED", "EMAIL_PROOF_DENIED", "PROOF_REVOKED",
}))


def enum_check(column, values, name):
    return sa.CheckConstraint(f"{column} IN ({', '.join(repr(v) for v in values)})", name=name)


class AuthorityState(Base):
    __tablename__ = "student_authority_states"
    registration_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), sa.ForeignKey("student_registrations.id", ondelete="CASCADE"), primary_key=True)
    guardian_state: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    institutional_state: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer(), default=1, nullable=False)
    guardian_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    guardian_verified_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    guardian_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    guardian_dob_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    guardian_identity_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    relationship: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    consent_version: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    institutional_email_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    institutional_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    review_due_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    reproof_guardian: Mapped[bool] = mapped_column(sa.Boolean(), default=False, nullable=False)
    reproof_institutional: Mapped[bool] = mapped_column(sa.Boolean(), default=False, nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.String(24), default="NYAY-11-v1", nullable=False)
    __table_args__ = (
        enum_check("guardian_state", GUARDIAN_STATES, "guardian_state"),
        enum_check("institutional_state", INSTITUTIONAL_STATES, "institutional_state"),
        sa.CheckConstraint("version >= 1", name="version"),
        sa.CheckConstraint("policy_version = 'NYAY-11-v1'", name="policy_version"),
        sa.CheckConstraint("relationship IS NULL OR relationship IN ('parent', 'legal_guardian')", name="relationship"),
        sa.CheckConstraint("guardian_state <> 'VERIFIED' OR (guardian_verified_at IS NOT NULL AND guardian_expires_at IS NOT NULL AND guardian_expires_at > guardian_verified_at AND guardian_dob_hash IS NOT NULL AND guardian_identity_hash IS NOT NULL AND length(guardian_identity_hash) = 64 AND relationship IS NOT NULL AND consent_version = 'guardian-consent.v1')", name="guardian_proof"),
        sa.CheckConstraint("institutional_state <> 'VERIFIED' OR (institutional_email_hash IS NOT NULL AND institutional_expires_at IS NOT NULL)", name="institutional_proof"),
    )


class GuardianInvitation(Base):
    __tablename__ = "guardian_authority_invitations"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    registration_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), sa.ForeignKey("student_registrations.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)
    generation: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    state: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    __table_args__ = (enum_check("state", ("pending", "consumed", "revoked"), "state"), sa.CheckConstraint("generation >= 1 AND length(token_hash) = 64", name="shape"))


class InstitutionalEmailProof(Base):
    __tablename__ = "institutional_authority_email_proofs"
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    email_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    institution: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    code_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    provider_receipt_hash: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    state: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(sa.Integer(), default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    __table_args__ = (
        enum_check("state", ("pending_delivery", "active", "verified", "failed", "revoked"), "state"),
        sa.CheckConstraint("attempts BETWEEN 0 AND 5 AND length(email_hash) = 64", name="shape"),
        sa.CheckConstraint("state NOT IN ('active','verified') OR provider_receipt_hash IS NOT NULL", name="delivery"),
        sa.CheckConstraint("state <> 'verified' OR code_hash IS NULL", name="consumed"),
    )


class InstitutionalReviewerAssignment(Base):
    __tablename__ = "institutional_reviewer_assignments"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    institution: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    operation: Mapped[str] = mapped_column(sa.String(24), nullable=False, default="review")
    active: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, default=True)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    __table_args__ = (sa.UniqueConstraint("user_id", "institution", "operation"), sa.CheckConstraint("operation = 'review'", name="operation"))


class AuthorityMutationRecord(Base):
    __tablename__ = "student_authority_mutations"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    registration_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid(), sa.ForeignKey("student_registrations.id", ondelete="CASCADE"), nullable=True, index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    operation: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    key_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    outcome_ct: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    __table_args__ = (sa.UniqueConstraint("actor_id", "operation", "key_hash"), sa.CheckConstraint("length(key_hash) = 64 AND length(fingerprint) = 64", name="shape"))


class AuthorityAuditEvent(Base):
    """Append-only closed aggregate projection: no IDs or unconstrained text."""
    __tablename__ = "student_authority_audit_events"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    actor_class: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    authority_class: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    purpose_code: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    transition_code: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    policy_version: Mapped[str] = mapped_column(sa.String(24), nullable=False, default="NYAY-11-v1")
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    __table_args__ = (
        enum_check("purpose_code", ("guardian", "institutional", "legacy_mapping", "identity"), "purpose"),
        enum_check("actor_class", ("student", "guardian", "owner", "reviewer", "admin", "server"), "actor"),
        enum_check("authority_class", AUTHORITY_CLASSES, "authority"),
        enum_check("transition_code", AUDIT_TRANSITIONS, "transition"),
        sa.CheckConstraint("policy_version = 'NYAY-11-v1'", name="policy"),
    )


class AuthorityNotification(Base):
    __tablename__ = "student_authority_notifications"
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), primary_key=True, default=uuid.uuid4)
    registration_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid(), sa.ForeignKey("student_registrations.id", ondelete="CASCADE"), nullable=False)
    state_version: Mapped[int] = mapped_column(sa.Integer(), nullable=False)
    code: Mapped[str] = mapped_column(sa.String(32), default="review_returned_to_queue", nullable=False)
    __table_args__ = (sa.UniqueConstraint("registration_id", "state_version", "code"), sa.CheckConstraint("code = 'review_returned_to_queue'", name="code"))


@sa.event.listens_for(AuthorityAuditEvent, "before_update")
@sa.event.listens_for(AuthorityAuditEvent, "before_delete")
def deny_audit_mutation(*_):
    raise ValueError("authority_audit_append_only")
