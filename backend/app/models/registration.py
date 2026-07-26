"""Student registration / auth physical model (SAATHI-366/448).

Implements the Product-approved (2026-07-26) schema: UUID PKs, timestamptz,
indexed FKs, explicit delete behavior. Sensitive values are stored as keyed
lookup hash + Fernet ciphertext (see app.core.crypto); raw mobile/email/
enrolment/DOB/OTP are never persisted in plaintext.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.db.base import TimestampedBase


class User(TimestampedBase):
    __tablename__ = "users"
    role: Mapped[str] = mapped_column(String(32), default="student", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)


class StudentRegistration(TimestampedBase):
    __tablename__ = "student_registrations"
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    # Split legal name (First/Last required, Middle optional).
    first_name: Mapped[str] = mapped_column(String(60), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(60), nullable=True)
    last_name: Mapped[str] = mapped_column(String(60), nullable=False)
    # Mobile + DOB: keyed hash (unique lookup) + ciphertext (authorized display).
    mobile_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mobile_ct: Mapped[str] = mapped_column(String(512), nullable=False)
    dob_ct: Mapped[str] = mapped_column(String(512), nullable=False)
    institution_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="otp_pending", nullable=False)
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    __table_args__ = (
        UniqueConstraint("mobile_hash", name="uq_student_registrations_mobile_hash"),
        UniqueConstraint("idempotency_key", name="uq_student_registrations_idempotency_key"),
    )
    profile: Mapped["StudentProfile | None"] = relationship(back_populates="registration", uselist=False)


class StudentProfile(TimestampedBase):
    __tablename__ = "student_profiles"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    college: Mapped[str | None] = mapped_column(String(160), nullable=True)
    year_of_study: Mapped[str | None] = mapped_column(String(40), nullable=True)
    enrolment_ct: Mapped[str | None] = mapped_column(String(512), nullable=True)
    enrolment_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    institutional_email_ct: Mapped[str | None] = mapped_column(String(512), nullable=True)
    institutional_email_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    bar_enrolment_ct: Mapped[str | None] = mapped_column(String(512), nullable=True)
    registration: Mapped[StudentRegistration] = relationship(back_populates="profile")


class OtpChallenge(TimestampedBase):
    __tablename__ = "otp_challenges"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    verifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # NEVER the raw OTP
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Consent(TimestampedBase):
    __tablename__ = "consents"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), default="registration", nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StudentVerification(TimestampedBase):
    __tablename__ = "student_verifications"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    method: Mapped[str] = mapped_column(String(32), default="institutional_email", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)


class GuardianConsent(TimestampedBase):
    __tablename__ = "guardian_consents"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class StudentAuditEvent(TimestampedBase):
    __tablename__ = "student_audit_events"
    actor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    # Redacted, non-PII snapshot only.
    redacted_meta: Mapped[dict | None] = mapped_column(JSON, default=None, nullable=True)
