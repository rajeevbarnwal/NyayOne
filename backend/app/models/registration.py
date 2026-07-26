"""Student registration / auth physical model (SAATHI-366/448).

Implements the Product-approved (2026-07-26) schema: UUID PKs, timestamptz,
indexed FKs, explicit delete behavior. Sensitive values are stored as keyed
lookup hash + Fernet ciphertext (see app.core.crypto); raw mobile/email/
enrolment/DOB/OTP are never persisted in plaintext. Ciphertext columns carry a
`key_version` for rotation, and finite-domain columns carry DB CHECK constraints.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import TimestampedBase

# --- Permitted finite-domain values (mirrored by DB CHECK constraints) -------
USER_ROLES = ("student", "lawyer", "admin")
USER_STATUSES = ("pending", "active", "suspended", "deleted")
REGISTRATION_STATUSES = ("otp_pending", "otp_verified", "active", "suspended", "deleted")
OTP_PURPOSES = ("signup", "recovery")
VERIFICATION_METHODS = ("institutional_email", "college_id", "manual")
VERIFICATION_STATUSES = ("pending", "in_review", "verified", "rejected")
GUARDIAN_STATUSES = ("pending", "sent", "verified", "rejected")
RECOVERY_STATUSES = ("pending", "verified", "consumed", "expired")


def _in(column: str, allowed: tuple[str, ...], name: str) -> CheckConstraint:
    # `name` is the bare constraint token; the metadata naming convention
    # ("ck_%(table_name)s_%(constraint_name)s") renders the final name so it
    # matches the migration's explicit ck_<table>_<token> names exactly.
    values = ", ".join(f"'{v}'" for v in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=name)


class User(TimestampedBase):
    __tablename__ = "users"
    role: Mapped[str] = mapped_column(String(32), default="student", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    __table_args__ = (
        _in("role", USER_ROLES, "role"),
        _in("status", USER_STATUSES, "status"),
    )


class StudentRegistration(TimestampedBase):
    __tablename__ = "student_registrations"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    # Split legal name (First/Last required, Middle optional).
    first_name: Mapped[str] = mapped_column(String(60), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    # Mobile + DOB: keyed hash (unique/indexed lookup) + ciphertext (display).
    mobile_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mobile_ct: Mapped[str] = mapped_column(String(600), nullable=False)
    dob_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    dob_ct: Mapped[str] = mapped_column(String(600), nullable=False)
    # Encryption key version stamped on this row's ciphertext columns (rotation).
    key_version: Mapped[str] = mapped_column(String(8), default="v1", nullable=False)
    institution_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="otp_pending", nullable=False)
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    __table_args__ = (
        UniqueConstraint("mobile_hash", name="uq_student_registrations_mobile_hash"),
        UniqueConstraint("idempotency_key", name="uq_student_registrations_idempotency_key"),
        _in("status", REGISTRATION_STATUSES, "status"),
    )
    profile: Mapped["StudentProfile | None"] = relationship(back_populates="registration", uselist=False)


class StudentProfile(TimestampedBase):
    __tablename__ = "student_profiles"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    college: Mapped[str | None] = mapped_column(String(160), nullable=True)
    year_of_study: Mapped[str | None] = mapped_column(String(40), nullable=True)
    enrolment_ct: Mapped[str | None] = mapped_column(String(600), nullable=True)
    enrolment_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    institutional_email_ct: Mapped[str | None] = mapped_column(String(600), nullable=True)
    institutional_email_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    bar_enrolment_ct: Mapped[str | None] = mapped_column(String(600), nullable=True)
    bar_enrolment_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    key_version: Mapped[str] = mapped_column(String(8), default="v1", nullable=False)
    registration: Mapped[StudentRegistration] = relationship(back_populates="profile")
    __table_args__ = (
        # Exactly one profile per registration (one-profile-per-registration contract).
        UniqueConstraint("registration_id", name="uq_student_profiles_registration_id"),
    )


class OtpChallenge(TimestampedBase):
    __tablename__ = "otp_challenges"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    # Distinguishes a signup OTP from a recovery OTP so recovery never supersedes
    # the active signup challenge (and vice versa).
    purpose: Mapped[str] = mapped_column(String(16), default="signup", nullable=False)
    verifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # NEVER the raw OTP
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        _in("purpose", OTP_PURPOSES, "purpose"),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
        CheckConstraint("max_attempts > 0", name="max_positive"),
        CheckConstraint("attempts <= max_attempts", name="attempts_le_max"),
    )


class RecoverySession(TimestampedBase):
    __tablename__ = "recovery_sessions"
    # Opaque, client-facing identifier — NEVER the registration UUID. Both known
    # and unknown mobiles get a persisted session so responses are symmetric.
    opaque_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Stable keyed lookup for cooldown/rate limiting of both real and decoy
    # sessions. The raw mobile is never stored.
    lookup_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    # NULL for decoy sessions (unknown mobile) so shape/behaviour is identical.
    registration_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=True)
    challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("otp_challenges.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("opaque_id", name="uq_recovery_sessions_opaque_id"),
        _in("status", RECOVERY_STATUSES, "status"),
    )


class OtpOutbox(TimestampedBase):
    """Transactional outbox for OTP delivery (SAATHI-448 A2).

    A delivery intent is written in the SAME transaction as the challenge, so an
    OTP is never handed to a provider before that transaction commits. The raw
    code is NEVER stored in plaintext. A short-lived encrypted delivery payload
    makes a committed row relayable after a process crash; it is erased as soon
    as delivery succeeds or the row is voided.
    """

    __tablename__ = "otp_outbox"
    challenge_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("otp_challenges.id", ondelete="CASCADE"), index=True, nullable=False)
    destination_ct: Mapped[str] = mapped_column(String(600), nullable=False)  # encrypted mobile
    code_ct: Mapped[str | None] = mapped_column(String(600), nullable=True)
    key_version: Mapped[str] = mapped_column(String(8), default="v1", nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), default="signup", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)  # never PII/code
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("challenge_id", name="uq_otp_outbox_challenge_id"),
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'void')", name="status"
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
    )


class Consent(TimestampedBase):
    __tablename__ = "consents"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), default="registration", nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        # A stored consent row must be affirmative (accepted = true).
        CheckConstraint("accepted = true", name="affirmative"),
    )


class StudentVerification(TimestampedBase):
    __tablename__ = "student_verifications"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    method: Mapped[str] = mapped_column(String(32), default="institutional_email", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    __table_args__ = (
        _in("method", VERIFICATION_METHODS, "method"),
        _in("status", VERIFICATION_STATUSES, "status"),
    )


class GuardianConsent(TimestampedBase):
    __tablename__ = "guardian_consents"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (
        _in("status", GUARDIAN_STATUSES, "status"),
    )


# Audit rows are written to the shared `audit_events` table
# (app.db.models.audit.AuditEvent) — append-only, enforced by an ORM guard
# (see app.db.models.audit) and a Postgres trigger in the migration.
