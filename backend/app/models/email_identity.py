"""NYAY-12 verified-email login identities (independent of institutional proof).

A login identity is never created or verified by mobile OTP, by the NYAY-11
institutional email proof or by migration. Raw addresses are stored only as a
keyed hash plus Fernet ciphertext; verification codes are stored only as keyed
hashes. Database partial unique indexes enforce: one verified owner per
address, one primary per user, one live claim per (user, address).
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base, TimestampedBase

EMAIL_IDENTITY_STATES = ("pending", "verified", "removed")
EMAIL_IDENTITY_VERIFICATION_STATES = ("none", "pending_delivery", "active", "failed")
EMAIL_IDENTITY_MUTATIONS = ("add", "verify", "resend", "remove", "primary")
EMAIL_IDENTITY_RECONCILIATION_REASONS = ("verified_collision", "legacy_duplicate")
EMAIL_IDENTITY_RECONCILIATION_STATES = ("open", "resolved")
EMAIL_IDENTITY_MAX_ATTEMPTS_BOUND = 10


def _hex_only_sql(column: str) -> str:
    expression = column
    for character in "0123456789abcdef":
        expression = f"replace({expression}, '{character}', '')"
    return expression


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    joined = ", ".join(f"'{value}'" for value in values)
    return CheckConstraint(f"{column} IN ({joined})", name=name)


class UserEmailIdentity(TimestampedBase):
    __tablename__ = "user_email_identities"
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    email_ct: Mapped[str] = mapped_column(String(600), nullable=False)
    key_version: Mapped[str] = mapped_column(String(8), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_state: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_receipt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    challenge_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    challenge_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        _in("state", EMAIL_IDENTITY_STATES, "state"),
        _in("verification_state", EMAIL_IDENTITY_VERIFICATION_STATES, "verification_state"),
        CheckConstraint(
            f"length(email_hash) = 64 AND length({_hex_only_sql('email_hash')}) = 0",
            name="email_hash_shape",
        ),
        CheckConstraint(
            "code_hash IS NULL OR length(code_hash) = 64", name="code_hash_shape"
        ),
        CheckConstraint(
            f"attempts >= 0 AND attempts <= {EMAIL_IDENTITY_MAX_ATTEMPTS_BOUND}", name="attempts_bounded"
        ),
        CheckConstraint("NOT is_primary OR state = 'verified'", name="primary_requires_verified"),
        CheckConstraint(
            "state <> 'verified' OR (verified_at IS NOT NULL AND code_hash IS NULL "
            "AND verification_state = 'none')",
            name="verified_shape",
        ),
        CheckConstraint(
            "state <> 'removed' OR (removed_at IS NOT NULL AND NOT is_primary)",
            name="removed_shape",
        ),
        CheckConstraint(
            "(verification_state = 'none' AND code_hash IS NULL) OR "
            "(verification_state <> 'none' AND challenge_issued_at IS NOT NULL "
            "AND challenge_expires_at IS NOT NULL)",
            name="challenge_shape",
        ),
        CheckConstraint(
            "verification_state <> 'active' OR provider_receipt_hash IS NOT NULL",
            name="delivery_receipt",
        ),
        sa.Index(
            "uq_user_email_identities_one_primary_per_user",
            "user_id",
            unique=True,
            postgresql_where=sa.text("is_primary = true"),
            sqlite_where=sa.text("is_primary = 1"),
        ),
        sa.Index(
            "uq_user_email_identities_verified_email",
            "email_hash",
            unique=True,
            postgresql_where=sa.text("state = 'verified'"),
            sqlite_where=sa.text("state = 'verified'"),
        ),
        sa.Index(
            "uq_user_email_identities_live_owner_email",
            "user_id",
            "email_hash",
            unique=True,
            postgresql_where=sa.text("state <> 'removed'"),
            sqlite_where=sa.text("state <> 'removed'"),
        ),
    )


class EmailIdentityMutation(Base):
    """Actor-scoped idempotency ledger; outcomes are sealed ciphertext."""

    __tablename__ = "email_identity_mutations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome_ct: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    __table_args__ = (
        UniqueConstraint("user_id", "operation", "key_hash", name="uq_email_identity_mutations_scope"),
        _in("operation", EMAIL_IDENTITY_MUTATIONS, "operation"),
        CheckConstraint("length(key_hash) = 64 AND length(fingerprint) = 64", name="shape"),
        CheckConstraint("status_code >= 200 AND status_code <= 599", name="status_code"),
    )


class EmailIdentityReconciliation(TimestampedBase):
    """Auditable, fail-closed collision ledger (hash only, never an address)."""

    __tablename__ = "email_identity_reconciliations"
    email_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    holder_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    claimant_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True, nullable=True
    )
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        _in("reason", EMAIL_IDENTITY_RECONCILIATION_REASONS, "reason"),
        _in("state", EMAIL_IDENTITY_RECONCILIATION_STATES, "state"),
        CheckConstraint("length(email_hash) = 64", name="email_hash_shape"),
        CheckConstraint(
            "(state = 'open' AND resolved_at IS NULL) OR (state = 'resolved' AND resolved_at IS NOT NULL)",
            name="resolution_shape",
        ),
    )
