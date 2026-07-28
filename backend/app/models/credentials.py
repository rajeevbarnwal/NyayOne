"""Wave 3 credential-trust models (SAATHI-253 / SAATHI-258).

Evidence bytes are deliberately absent: PostgreSQL stores only opaque object
references and integrity/scan metadata. Verification tokens store a keyed hash,
never the bearer token. Every FK is indexed and carries explicit delete
behaviour; finite domains are protected by named CHECK constraints.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import TimestampedBase

CREDENTIAL_TYPES = (
    "certificate",
    "badge",
    "moot_achievement",
    "course_completion",
    "employment",
    "other",
)
CREDENTIAL_STATUSES = (
    "self_declared",
    "pending_verification",
    "verified",
    "expired",
    "revoked",
)
ISSUER_TYPES = ("institution", "platform", "tutor", "employer", "external")
SCAN_STATES = ("quarantined", "clean", "infected", "retryable_failure", "deleted")
OUTBOX_KINDS = ("scan_evidence", "delete_evidence", "expiry_reminder")
OUTBOX_STATUSES = ("pending", "processing", "complete", "failed")
REMINDER_STATUSES = ("pending", "sent", "cancelled", "failed")
VERIFY_ACTIONS = ("verified", "revoked")
ACCESS_OUTCOMES = ("valid", "invalid", "expired", "revoked", "rate_limited")


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IN ({', '.join(repr(value) for value in values)})",
        name=name,
    )


class CredentialIssuer(TimestampedBase):
    __tablename__ = "credential_issuers"

    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    issuer_type: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("display_name", name="uq_credential_issuers_display_name"),
        _in("issuer_type", ISSUER_TYPES, "issuer_type"),
    )


class Credential(TimestampedBase):
    __tablename__ = "credentials"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    issuer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credential_issuers.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    credential_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default="self_declared", nullable=False
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    identifier_hash: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    identifier_ct: Mapped[str | None] = mapped_column(String(600), nullable=True)
    key_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_credentials_owner_idempotency",
        ),
        UniqueConstraint(
            "owner_user_id",
            "identifier_hash",
            name="uq_credentials_owner_identifier_hash",
        ),
        _in("credential_type", CREDENTIAL_TYPES, "credential_type"),
        _in("status", CREDENTIAL_STATUSES, "status"),
        CheckConstraint(
            "expiry_date IS NULL OR expiry_date >= issue_date",
            name="expiry_after_issue",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class CredentialEvidence(TimestampedBase):
    __tablename__ = "credential_evidence"

    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    object_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    sha256_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_mime: Mapped[str] = mapped_column(String(80), nullable=False)
    detected_mime: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    scan_state: Mapped[str] = mapped_column(
        String(32), default="quarantined", nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "credential_id",
            "sha256_digest",
            name="uq_credential_evidence_digest",
        ),
        UniqueConstraint("object_ref", name="uq_credential_evidence_object_ref"),
        _in("scan_state", SCAN_STATES, "scan_state"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
    )


class CredentialStatusHistory(TimestampedBase):
    __tablename__ = "credential_status_history"

    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        _in("to_status", CREDENTIAL_STATUSES, "to_status"),
    )


class CredentialShareProjection(TimestampedBase):
    __tablename__ = "credential_share_projections"

    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    fields_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_credential_share_projections_owner_idempotency",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class CredentialOutbox(TimestampedBase):
    __tablename__ = "credential_outbox"

    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credential_evidence.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[str | None] = mapped_column(
        String(80), nullable=True
    )
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "kind", "idempotency_key", name="uq_credential_outbox_kind_idempotency"
        ),
        _in("kind", OUTBOX_KINDS, "kind"),
        _in("status", OUTBOX_STATUSES, "status"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )


class CredentialReminderJob(TimestampedBase):
    __tablename__ = "credential_reminder_jobs"

    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    days_before: Mapped[int] = mapped_column(Integer, nullable=False)
    remind_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "credential_id",
            "days_before",
            name="uq_credential_reminder_jobs_credential_day",
        ),
        _in("status", REMINDER_STATUSES, "status"),
        CheckConstraint("days_before IN (30, 7, 1)", name="days_before"),
    )


class CredentialEvidenceScanEvent(TimestampedBase):
    __tablename__ = "credential_evidence_scan_events"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credential_evidence.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    scan_state: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    result_code: Mapped[str] = mapped_column(String(80), nullable=False)

    __table_args__ = (_in("scan_state", SCAN_STATES, "scan_state"),)


class IssuerAuthorisation(TimestampedBase):
    __tablename__ = "issuer_authorisations"

    issuer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credential_issuers.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    can_verify: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_revoke: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "issuer_id", "user_id", name="uq_issuer_authorisations_issuer_user"
        ),
    )


class CredentialVerificationEvent(TimestampedBase):
    __tablename__ = "credential_verification_events"

    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    issuer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credential_issuers.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    resulting_status: Mapped[str] = mapped_column(String(32), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "actor_user_id",
            "idempotency_key",
            name="uq_credential_verification_events_actor_idempotency",
        ),
        _in("action", VERIFY_ACTIONS, "action"),
        _in("resulting_status", CREDENTIAL_STATUSES, "resulting_status"),
    )


class VerificationToken(TimestampedBase):
    __tablename__ = "verification_tokens"

    projection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credential_share_projections.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_version: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_verification_tokens_token_hash"),
        UniqueConstraint(
            "owner_user_id",
            "idempotency_key",
            name="uq_verification_tokens_owner_idempotency",
        ),
    )


class CredentialRevocation(TimestampedBase):
    __tablename__ = "credential_revocations"

    credential_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credentials.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    issuer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("credential_issuers.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    reason_ct: Mapped[str] = mapped_column(Text, nullable=False)
    reason_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    key_version: Mapped[str] = mapped_column(String(16), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "credential_id", name="uq_credential_revocations_credential_id"
        ),
    )


class VerificationAccessLog(TimestampedBase):
    __tablename__ = "verification_access_logs"

    token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("verification_tokens.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    bucket_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)

    __table_args__ = (_in("outcome", ACCESS_OUTCOMES, "outcome"),)
