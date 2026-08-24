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

import sqlalchemy as sa
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

from app.db.base import Base, TimestampedBase

# --- Permitted finite-domain values (mirrored by DB CHECK constraints) -------
USER_ROLES = (
    "student",
    "lawyer",
    "admin",
    "moderator",
    "safety_officer",
    "legal_reviewer",
)
USER_STATUSES = ("pending", "active", "suspended", "deleted")
REGISTRATION_STATUSES = ("otp_pending", "otp_verified", "active", "suspended", "deleted")
OTP_PURPOSES = ("signup", "recovery", "login")
OTP_CHALLENGE_DELIVERY_STATES = (
    "pending_delivery",
    "active",
    "consumed",
    "superseded",
    "void",
)
OTP_RATE_LIMIT_SCOPES = ("identity", "ip", "global")
OTP_RATE_LIMIT_ACTIONS = ("issue", "resend", "verify")
OTP_FLOW_STATES = (
    "pending",
    "code_sent",
    "verified",
    "locked",
    "expired",
    "consumed",
    "failed",
)
VERIFICATION_METHODS = ("institutional_email", "college_id", "manual")
VERIFICATION_STATUSES = (
    "pending",
    "in_review",
    "verified",
    "rejected",
    "expired",
    "revoked",
)
GUARDIAN_STATUSES = ("pending", "sent", "verified", "rejected", "revoked")
RECOVERY_STATUSES = ("pending", "verified", "consumed", "expired")
LOGIN_ATTEMPT_STATUSES = ("pending", "consumed", "expired", "erased")
AUTH_SESSION_STATUSES = ("active", "revoked", "expired", "erased")
REGISTRATION_IDEMPOTENCY_STATES = (
    "pending",
    "succeeded",
    "failed",
    "neutralized",
    "retired",
    "erased",
)
DOB_HASH_STATES = ("verified", "quarantined", "erased")
DOB_RECONCILIATION_OUTCOMES = ("reconciled", "quarantined")
DOB_RECONCILIATION_REASONS = (
    "verified_source",
    "ciphertext_unreadable",
    "source_not_canonical_date",
    "source_future_date",
)
_DOB_HASH_HEX_ONLY_SQL = "dob_hash"
for _hex_character in "0123456789abcdef":
    _DOB_HASH_HEX_ONLY_SQL = (
        f"replace({_DOB_HASH_HEX_ONLY_SQL}, '{_hex_character}', '')"
    )
_DOB_SOURCE_DIGEST_HEX_ONLY_SQL = "source_ciphertext_sha256"
for _hex_character in "0123456789abcdef":
    _DOB_SOURCE_DIGEST_HEX_ONLY_SQL = (
        f"replace({_DOB_SOURCE_DIGEST_HEX_ONLY_SQL}, '{_hex_character}', '')"
    )
_IDEMPOTENCY_KEY_HASH_HEX_ONLY_SQL = "idempotency_key_hash"
_REQUEST_FINGERPRINT_HEX_ONLY_SQL = "request_fingerprint"
_OTP_RATE_SUBJECT_HEX_ONLY_SQL = "subject_hash"
_OTP_FLOW_TOKEN_HEX_ONLY_SQL = "token_hash"
_OTP_PROVIDER_KEY_HEX_ONLY_SQL = "provider_idempotency_key"
_OTP_CLAIM_TOKEN_HEX_ONLY_SQL = "claim_token_hash"
_OTP_PROVIDER_RECEIPT_HEX_ONLY_SQL = "provider_receipt_hash"
_LOGIN_ATTEMPT_LOOKUP_HEX_ONLY_SQL = "lookup_hash"
_LOGIN_ATTEMPT_OPAQUE_HEX_ONLY_SQL = "opaque_id"
_AUTH_SESSION_TOKEN_HEX_ONLY_SQL = "token_hash"
for _hex_character in "0123456789abcdef":
    _IDEMPOTENCY_KEY_HASH_HEX_ONLY_SQL = (
        f"replace({_IDEMPOTENCY_KEY_HASH_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )
    _REQUEST_FINGERPRINT_HEX_ONLY_SQL = (
        f"replace({_REQUEST_FINGERPRINT_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )
    _OTP_RATE_SUBJECT_HEX_ONLY_SQL = (
        f"replace({_OTP_RATE_SUBJECT_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )
    _OTP_FLOW_TOKEN_HEX_ONLY_SQL = (
        f"replace({_OTP_FLOW_TOKEN_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )
    _OTP_PROVIDER_KEY_HEX_ONLY_SQL = (
        f"replace({_OTP_PROVIDER_KEY_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )
    _OTP_CLAIM_TOKEN_HEX_ONLY_SQL = (
        f"replace({_OTP_CLAIM_TOKEN_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )
    _OTP_PROVIDER_RECEIPT_HEX_ONLY_SQL = (
        f"replace({_OTP_PROVIDER_RECEIPT_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )
    _LOGIN_ATTEMPT_LOOKUP_HEX_ONLY_SQL = (
        f"replace({_LOGIN_ATTEMPT_LOOKUP_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )
    _LOGIN_ATTEMPT_OPAQUE_HEX_ONLY_SQL = (
        f"replace({_LOGIN_ATTEMPT_OPAQUE_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )
    _AUTH_SESSION_TOKEN_HEX_ONLY_SQL = (
        f"replace({_AUTH_SESSION_TOKEN_HEX_ONLY_SQL}, "
        f"'{_hex_character}', '')"
    )


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
    # 0016 makes historical placeholder reconciliation explicit.  Quarantined
    # rows carry a deterministic non-PII digest in dob_hash and a reason-only
    # record in registration_dob_reconciliations; raw/ciphertext values are
    # never copied to that table. Quarantine is terminal in the application:
    # there is no API transition back to verified. Any future operator repair
    # must also revoke/rotate auth capability under NYAY-3 session invariants.
    dob_hash_state: Mapped[str] = mapped_column(
        String(16),
        default="verified",
        index=True,
        nullable=False,
    )
    # Encryption key version stamped on this row's ciphertext columns (rotation).
    key_version: Mapped[str] = mapped_column(String(8), default="v1", nullable=False)
    institution_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="otp_pending", nullable=False)
    is_minor: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 0018 marks only pre-migration raw idempotency keys as legacy. New code
    # stores a domain-separated keyed HMAC in registration_idempotency_records
    # and leaves this raw column NULL. The server default makes an old binary's
    # post-0018 keyed insert fail the CHECK instead of bypassing the ledger.
    idempotency_key_legacy: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False
    )
    __table_args__ = (
        UniqueConstraint("mobile_hash", name="uq_student_registrations_mobile_hash"),
        UniqueConstraint("idempotency_key", name="uq_student_registrations_idempotency_key"),
        _in("status", REGISTRATION_STATUSES, "status"),
        _in("dob_hash_state", DOB_HASH_STATES, "dob_hash_state"),
        CheckConstraint(
            "(idempotency_key IS NULL AND idempotency_key_legacy = false) OR "
            "(idempotency_key IS NOT NULL AND idempotency_key_legacy = true)",
            name="idempotency_key_legacy",
        ),
        CheckConstraint(
            "(dob_hash_state IN ('verified', 'quarantined') AND status <> 'deleted' "
            "AND length(dob_hash) = 64 "
            f"AND length({_DOB_HASH_HEX_ONLY_SQL}) = 0) OR "
            "(dob_hash_state = 'erased' AND status = 'deleted' "
            "AND mobile_ct = '[erased]' AND dob_ct = '[erased]' "
            "AND replace(mobile_hash, '-', '') = '[erased]:' || "
            "replace(CAST(id AS VARCHAR), '-', '') "
            "AND replace(dob_hash, '-', '') = '[erased]:' || "
            "replace(CAST(id AS VARCHAR), '-', ''))",
            name="dob_hash_state_consistency",
        ),
    )
    profile: Mapped["StudentProfile | None"] = relationship(back_populates="registration", uselist=False)


class RegistrationIdempotencyRecord(Base):
    """Durable, non-PII registration request/outcome ledger (NYAY-17)."""

    __tablename__ = "registration_idempotency_records"

    # Domain-separated keyed HMAC of the opaque wire key; raw keys never enter
    # this table. This is the sole new-registration uniqueness authority.
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    idempotency_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_fingerprint_version: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    outcome_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    registration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "student_registrations.id",
            name="fk_reg_idem_registration",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    outbox_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "otp_outbox.id",
            name="fk_reg_idem_outbox",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
        nullable=False,
    )
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key_hash",
            name="uq_registration_idempotency_records_idempotency_key_hash",
        ),
        UniqueConstraint(
            "registration_id",
            name="uq_registration_idempotency_records_registration_id",
        ),
        UniqueConstraint(
            "outbox_id",
            name="uq_registration_idempotency_records_outbox_id",
        ),
        _in("state", REGISTRATION_IDEMPOTENCY_STATES, "state"),
        CheckConstraint(
            "length(idempotency_key_hash) = 64 AND "
            f"length({_IDEMPOTENCY_KEY_HASH_HEX_ONLY_SQL}) = 0",
            name="key_hash_shape",
        ),
        CheckConstraint(
            "((state IN ('pending', 'succeeded', 'failed', 'neutralized') AND "
            "request_fingerprint_version IN ('v1', 'v2') AND "
            "request_fingerprint IS NOT NULL AND "
            "length(request_fingerprint) = 64 AND "
            f"length({_REQUEST_FINGERPRINT_HEX_ONLY_SQL}) = 0) OR "
            "(state IN ('retired', 'erased') AND "
            "request_fingerprint IS NULL AND "
            "request_fingerprint_version IS NULL))",
            name="request_fingerprint_shape",
        ),
        CheckConstraint(
            "(state = 'pending' AND registration_id IS NOT NULL AND "
            "outbox_id IS NOT NULL AND outcome_code IS NULL) OR "
            "(state = 'succeeded' AND registration_id IS NOT NULL AND "
            "outbox_id IS NULL AND outcome_code IS NULL) OR "
            "(state = 'failed' AND registration_id IS NULL AND "
            "outbox_id IS NULL AND outcome_code = 'otp_delivery_failed') OR "
            "(state = 'neutralized' AND registration_id IS NULL AND "
            "outbox_id IS NULL AND outcome_code = 'registration_neutralized') OR "
            "(state IN ('retired', 'erased') AND registration_id IS NULL AND "
            "outbox_id IS NULL AND "
            "outcome_code = 'registration_replay_expired')",
            name="state_links",
        ),
    )


class RegistrationDobReconciliation(Base):
    """Non-PII disposition for a legacy ``[rehash-required]`` DOB row."""

    __tablename__ = "registration_dob_reconciliations"
    registration_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "student_registrations.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key_version: Mapped[str] = mapped_column(String(8), nullable=False)
    source_ciphertext_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    __table_args__ = (
        _in("outcome", DOB_RECONCILIATION_OUTCOMES, "outcome"),
        _in("reason_code", DOB_RECONCILIATION_REASONS, "reason_code"),
        CheckConstraint(
            "(outcome = 'reconciled' AND reason_code = 'verified_source') OR "
            "(outcome = 'quarantined' AND reason_code != 'verified_source')",
            name="outcome_reason",
        ),
        CheckConstraint(
            "length(source_ciphertext_sha256) = 64 AND "
            f"length({_DOB_SOURCE_DIGEST_HEX_ONLY_SQL}) = 0",
            name="source_digest_length",
        ),
    )


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
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pronouns: Mapped[str | None] = mapped_column(String(60), nullable=True)
    profile_version: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", nullable=False
    )
    registration: Mapped[StudentRegistration] = relationship(back_populates="profile")
    __table_args__ = (
        # Exactly one profile per registration (one-profile-per-registration contract).
        UniqueConstraint("registration_id", name="uq_student_profiles_registration_id"),
        CheckConstraint(
            "preferred_language IS NULL OR preferred_language IN ('en', 'hi')",
            name="preferred_language",
        ),
        CheckConstraint("profile_version >= 1", name="profile_version_positive"),
    )


class StudentProfileInterest(TimestampedBase):
    """Normalized, owner-scoped profile interest (NYAY-5)."""

    __tablename__ = "student_profile_interests"
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(80), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "value", name="uq_student_profile_interests_profile_id_value"
        ),
        CheckConstraint(
            "length(value) >= 1 AND length(value) <= 80", name="value_length"
        ),
    )


class StudentProfileGoal(TimestampedBase):
    """Normalized, owner-scoped profile goal (NYAY-5)."""

    __tablename__ = "student_profile_goals"
    profile_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("student_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(80), nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "value", name="uq_student_profile_goals_profile_id_value"
        ),
        CheckConstraint(
            "length(value) >= 1 AND length(value) <= 80", name="value_length"
        ),
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
    authority_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "otp_purpose_authorities.id",
            name="fk_otp_challenges_authority",
            ondelete="CASCADE",
        ),
        index=True,
        nullable=False,
    )
    # 0019 separates provider delivery from verification authority.  A resend
    # candidate remains non-verifiable until its outbox delivery is accepted;
    # only then is it atomically swapped with the prior ``active`` challenge.
    # ``consumed_at`` remains the predicate of the sealed NYAY-3 partial unique
    # index.  Pending candidates therefore carry a non-NULL reservation value
    # until activation, while ``delivery_state`` supplies the unambiguous
    # lifecycle meaning.
    delivery_state: Mapped[str] = mapped_column(
        String(24),
        default="pending_delivery",
        server_default="pending_delivery",
        nullable=False,
    )
    __table_args__ = (
        _in("purpose", OTP_PURPOSES, "purpose"),
        _in(
            "delivery_state",
            OTP_CHALLENGE_DELIVERY_STATES,
            "delivery_state",
        ),
        CheckConstraint(
            "(delivery_state = 'active' AND consumed_at IS NULL) OR "
            "(delivery_state <> 'active' AND consumed_at IS NOT NULL)",
            name="delivery_state_consumed_at",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
        CheckConstraint("max_attempts > 0", name="max_positive"),
        CheckConstraint("attempts <= max_attempts", name="attempts_le_max"),
        sa.Index(
            "uq_otp_challenges_one_active_per_registration_purpose",
            "registration_id",
            "purpose",
            unique=True,
            postgresql_where=sa.text("consumed_at IS NULL"),
            sqlite_where=sa.text("consumed_at IS NULL"),
        ),
        sa.Index(
            "uq_otp_challenges_one_active_per_authority",
            "authority_id",
            unique=True,
            postgresql_where=sa.text(
                "authority_id IS NOT NULL AND delivery_state = 'active'"
            ),
            sqlite_where=sa.text(
                "authority_id IS NOT NULL AND delivery_state = 'active'"
            ),
        ),
        sa.Index(
            "uq_otp_challenges_one_pending_delivery_per_authority",
            "authority_id",
            unique=True,
            postgresql_where=sa.text(
                "authority_id IS NOT NULL AND delivery_state = 'pending_delivery'"
            ),
            sqlite_where=sa.text(
                "authority_id IS NOT NULL AND delivery_state = 'pending_delivery'"
            ),
        ),
    )


class OtpPurposeAuthority(TimestampedBase):
    """Stable registration+purpose security authority (NYAY-4).

    Challenge material may rotate, but failed-attempt and lockout authority
    lives here and therefore cannot be reset by resend.  One row is serialized
    before any challenge replacement or verification decision.
    """

    __tablename__ = "otp_purpose_authorities"
    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    registration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "student_registrations.id",
            name="fk_otp_authority_registration",
            ondelete="CASCADE",
        ),
        index=True,
        nullable=True,
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    failed_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, default=3, server_default="3", nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resend_window_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resend_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    max_resends: Mapped[int] = mapped_column(
        Integer, default=3, server_default="3", nullable=False
    )
    active_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generation: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "subject_hash",
            "purpose",
            name="uq_otp_purpose_authorities_subject_purpose",
        ),
        UniqueConstraint(
            "registration_id",
            "purpose",
            name="uq_otp_purpose_authorities_registration_purpose",
        ),
        CheckConstraint(
            "length(subject_hash) = 64 AND "
            f"length({_OTP_RATE_SUBJECT_HEX_ONLY_SQL}) = 0",
            name="subject_hash_shape",
        ),
        _in("purpose", OTP_PURPOSES, "purpose"),
        CheckConstraint("failed_attempts >= 0", name="failed_attempts_nonneg"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        CheckConstraint("max_attempts <= 10", name="max_attempts_bounded"),
        CheckConstraint(
            "failed_attempts <= max_attempts", name="failed_attempts_le_max"
        ),
        CheckConstraint("resend_count >= 0", name="resend_count_nonneg"),
        CheckConstraint("max_resends > 0", name="max_resends_positive"),
        CheckConstraint("max_resends <= 10", name="max_resends_bounded"),
        CheckConstraint(
            "resend_count <= max_resends", name="resend_count_within_limit"
        ),
        CheckConstraint("generation >= 0", name="generation_nonneg"),
    )


class OtpRateLimitBucket(Base):
    """Durable fixed-window OTP abuse budget containing HMAC subjects only."""

    __tablename__ = "otp_rate_limit_buckets"
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    max_requests: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "subject_hash",
            "action",
            name="uq_otp_rate_limit_buckets_scope_subject_action",
        ),
        _in("scope", OTP_RATE_LIMIT_SCOPES, "scope"),
        _in("action", OTP_RATE_LIMIT_ACTIONS, "action"),
        CheckConstraint(
            "length(subject_hash) = 64 AND "
            f"length({_OTP_RATE_SUBJECT_HEX_ONLY_SQL}) = 0",
            name="subject_hash_shape",
        ),
        CheckConstraint("window_seconds > 0", name="window_seconds_positive"),
        CheckConstraint("window_seconds <= 86400", name="window_seconds_bounded"),
        CheckConstraint("request_count >= 0", name="request_count_nonnegative"),
        CheckConstraint("max_requests > 0", name="max_requests_positive"),
        CheckConstraint("max_requests <= 100000", name="max_requests_bounded"),
        CheckConstraint(
            "request_count <= max_requests", name="request_count_within_limit"
        ),
    )


class OtpFlow(TimestampedBase):
    """Reload-safe pre-auth capability; only a keyed cookie-token hash lives here."""

    __tablename__ = "otp_flows"
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    authority_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("otp_purpose_authorities.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    registration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("student_registrations.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("otp_challenges.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    registration_idempotency_record_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "registration_idempotency_records.id",
            name="fk_otp_flow_registration_idempotency",
            ondelete="RESTRICT",
        ),
        index=True,
        nullable=True,
    )
    destination_masked_ct: Mapped[str | None] = mapped_column(
        String(600), nullable=True
    )
    key_version: Mapped[str | None] = mapped_column(String(8), nullable=True)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_otp_flows_token_hash"),
        UniqueConstraint(
            "registration_idempotency_record_id",
            name="uq_otp_flows_registration_idempotency_record_id",
        ),
        _in("purpose", OTP_PURPOSES, "purpose"),
        _in("state", OTP_FLOW_STATES, "state"),
        CheckConstraint(
            "length(token_hash) = 64 AND "
            f"length({_OTP_FLOW_TOKEN_HEX_ONLY_SQL}) = 0",
            name="token_hash_shape",
        ),
        CheckConstraint(
            "length(subject_hash) = 64 AND "
            f"length({_OTP_RATE_SUBJECT_HEX_ONLY_SQL}) = 0",
            name="subject_hash_shape",
        ),
        CheckConstraint(
            "registration_id IS NOT NULL OR challenge_id IS NULL",
            name="challenge_requires_registration",
        ),
        CheckConstraint(
            "(state IN ('expired', 'consumed', 'failed') AND "
            "consumed_at IS NOT NULL) OR "
            "(state IN ('pending', 'code_sent', 'verified', 'locked') AND "
            "consumed_at IS NULL)",
            name="consumption_shape",
        ),
        CheckConstraint(
            "state <> 'verified' OR "
            "(registration_id IS NOT NULL AND challenge_id IS NOT NULL)",
            name="verified_links",
        ),
        CheckConstraint(
            "(state IN ('pending', 'code_sent', 'locked') AND "
            "destination_masked_ct IS NOT NULL AND key_version IS NOT NULL) OR "
            "(state IN ('verified', 'expired', 'consumed', 'failed') AND "
            "destination_masked_ct IS NULL AND key_version IS NULL)",
            name="destination_shape",
        ),
        sa.Index(
            "uq_otp_flows_one_nonterminal_per_authority",
            "authority_id",
            unique=True,
            postgresql_where=sa.text(
                "state IN ('pending', 'code_sent', 'verified', 'locked')"
            ),
            sqlite_where=sa.text(
                "state IN ('pending', 'code_sent', 'verified', 'locked')"
            ),
        ),
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


class LoginAttempt(TimestampedBase):
    """Opaque, non-enumerating OTP-login attempt.

    Unknown mobiles receive an indistinguishable row with null registration and
    challenge references. Raw mobiles and OTPs are never stored here.
    """

    __tablename__ = "login_attempts"
    opaque_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lookup_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    registration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("student_registrations.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("otp_challenges.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(24), default="pending", server_default="pending", nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("opaque_id", name="uq_login_attempts_opaque_id"),
        _in("status", LOGIN_ATTEMPT_STATUSES, "status"),
        CheckConstraint(
            "length(lookup_hash) = 64 AND "
            f"length({_LOGIN_ATTEMPT_LOOKUP_HEX_ONLY_SQL}) = 0",
            name="lookup_hash_shape",
        ),
        CheckConstraint(
            "((status <> 'erased' AND length(opaque_id) = 32) OR "
            "(status = 'erased' AND length(opaque_id) = 64)) AND "
            f"length({_LOGIN_ATTEMPT_OPAQUE_HEX_ONLY_SQL}) = 0",
            name="opaque_id_shape",
        ),
        CheckConstraint(
            "(status = 'pending' AND consumed_at IS NULL AND deleted_at IS NULL) OR "
            "(status IN ('consumed', 'expired') AND consumed_at IS NOT NULL "
            "AND deleted_at IS NULL) OR "
            "(status = 'erased' AND registration_id IS NULL AND challenge_id IS NULL "
            "AND consumed_at IS NOT NULL AND deleted_at IS NOT NULL "
            "AND metadata_json IS NULL AND created_at = updated_at "
            "AND updated_at = expires_at AND expires_at = consumed_at "
            "AND consumed_at = deleted_at)",
            name="lifecycle_shape",
        ),
        sa.Index("ix_login_attempts_expires_at", "expires_at"),
        sa.Index("ix_login_attempts_consumed_at", "consumed_at"),
    )


class AuthSession(TimestampedBase):
    """Server-authoritative authenticated session.

    The browser receives a random opaque token only in an HttpOnly cookie. The
    database stores its keyed hash, never the bearer token itself.
    """

    __tablename__ = "auth_sessions"
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), default="active", server_default="active", nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        _in("status", AUTH_SESSION_STATUSES, "status"),
        CheckConstraint(
            "length(token_hash) = 64 AND "
            f"length({_AUTH_SESSION_TOKEN_HEX_ONLY_SQL}) = 0",
            name="token_hash_shape",
        ),
        CheckConstraint(
            "(status = 'active' AND user_id IS NOT NULL AND revoked_at IS NULL "
            "AND deleted_at IS NULL) OR "
            "(status IN ('revoked', 'expired') AND user_id IS NOT NULL "
            "AND revoked_at IS NOT NULL AND deleted_at IS NULL) OR "
            "(status = 'erased' AND user_id IS NULL AND revoked_at IS NOT NULL "
            "AND deleted_at IS NOT NULL AND metadata_json IS NULL "
            "AND created_at = updated_at AND updated_at = expires_at "
            "AND expires_at = last_seen_at AND last_seen_at = revoked_at "
            "AND revoked_at = deleted_at)",
            name="lifecycle_shape",
        ),
        sa.Index(
            "uq_auth_sessions_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=sa.text("status = 'active'"),
            sqlite_where=sa.text("status = 'active'"),
        ),
        sa.Index("ix_auth_sessions_revoked_at", "revoked_at"),
    )


class AuthSessionProfilePrompt(TimestampedBase):
    """A dismissal scoped to one server-owned authenticated session."""

    __tablename__ = "auth_session_profile_prompts"
    auth_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("auth_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "auth_session_id", name="uq_auth_session_profile_prompts_auth_session_id"
        ),
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
    destination_ct: Mapped[str | None] = mapped_column(String(600), nullable=True)  # encrypted mobile
    code_ct: Mapped[str | None] = mapped_column(String(600), nullable=True)
    key_version: Mapped[str] = mapped_column(String(8), default="v1", nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), default="signup", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)  # never PII/code
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Stable across every lease/retry.  A provider that accepts an attempt and
    # loses the local acknowledgement must deduplicate the retried request by
    # this opaque token.
    provider_idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_receipt_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    provider_receipt_key_version: Mapped[str | None] = mapped_column(
        String(8), nullable=True
    )
    # Migration 0019 does not destructively erase historical terminal
    # ciphertext. New rows are always false and terminalization clears both
    # payloads; an explicit retention purge may clear grandfathered rows.
    legacy_destination_retained: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, default=5, server_default="5", nullable=False
    )
    __table_args__ = (
        UniqueConstraint("challenge_id", name="uq_otp_outbox_challenge_id"),
        UniqueConstraint(
            "provider_idempotency_key",
            name="uq_otp_outbox_provider_idempotency_key",
        ),
        CheckConstraint(
            "status IN ('pending', 'claimed', 'sent', 'failed', 'void')",
            name="status",
        ),
        CheckConstraint("attempts >= 0", name="attempts_nonneg"),
        CheckConstraint("max_attempts > 0", name="max_attempts_positive"),
        CheckConstraint("max_attempts <= 10", name="max_attempts_bounded"),
        CheckConstraint("attempts <= max_attempts", name="attempts_le_max"),
        CheckConstraint(
            "length(provider_idempotency_key) = 64 AND "
            f"length({_OTP_PROVIDER_KEY_HEX_ONLY_SQL}) = 0",
            name="provider_idempotency_key_shape",
        ),
        CheckConstraint(
            "(status = 'claimed' AND claim_token_hash IS NOT NULL AND "
            "claimed_at IS NOT NULL AND lease_expires_at IS NOT NULL AND "
            "lease_expires_at > claimed_at) OR "
            "(status <> 'claimed' AND claim_token_hash IS NULL AND "
            "claimed_at IS NULL AND lease_expires_at IS NULL)",
            name="claim_shape",
        ),
        CheckConstraint(
            "claim_token_hash IS NULL OR (length(claim_token_hash) = 64 AND "
            f"length({_OTP_CLAIM_TOKEN_HEX_ONLY_SQL}) = 0)",
            name="claim_token_hash_shape",
        ),
        CheckConstraint(
            "(status IN ('pending', 'claimed', 'failed') AND code_ct IS NOT NULL "
            "AND destination_ct IS NOT NULL) OR "
            "(status IN ('sent', 'void') AND code_ct IS NULL AND "
            "((destination_ct IS NULL AND legacy_destination_retained = false) "
            "OR (destination_ct IS NOT NULL AND "
            "legacy_destination_retained = true)))",
            name="payload_shape",
        ),
        CheckConstraint(
            "legacy_destination_retained = false OR status IN ('sent', 'void')",
            name="legacy_destination_terminal",
        ),
        CheckConstraint(
            "(status = 'failed' AND next_attempt_at IS NOT NULL) OR "
            "(status <> 'failed' AND next_attempt_at IS NULL)",
            name="retry_shape",
        ),
        CheckConstraint(
            "(provider_receipt_hash IS NULL AND provider_receipt_key_version IS NULL) "
            "OR (status = 'sent' AND provider_receipt_hash IS NOT NULL AND "
            "provider_receipt_key_version = 'v1')",
            name="provider_receipt_shape",
        ),
        CheckConstraint(
            "provider_receipt_hash IS NULL OR "
            "(length(provider_receipt_hash) = 64 AND "
            f"length({_OTP_PROVIDER_RECEIPT_HEX_ONLY_SQL}) = 0)",
            name="provider_receipt_hash_shape",
        ),
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
    verified_email_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    __table_args__ = (
        UniqueConstraint(
            "registration_id", name="uq_student_verifications_registration_id"
        ),
        _in("method", VERIFICATION_METHODS, "method"),
        _in("status", VERIFICATION_STATUSES, "status"),
        CheckConstraint(
            "(status = 'verified' AND verified_email_hash IS NOT NULL) OR "
            "(status <> 'verified' AND verified_email_hash IS NULL)",
            name="verified_email_proof",
        ),
    )


class GuardianConsent(TimestampedBase):
    __tablename__ = "guardian_consents"
    registration_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("student_registrations.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (
        UniqueConstraint(
            "registration_id", name="uq_guardian_consents_registration_id"
        ),
        _in("status", GUARDIAN_STATUSES, "status"),
        CheckConstraint(
            "(status = 'verified' AND verified = true) OR "
            "(status IN ('pending', 'sent', 'rejected', 'revoked') AND verified = false)",
            name="verified_matches_status",
        ),
    )


# Audit rows are written to the shared `audit_events` table
# (app.db.models.audit.AuditEvent) — append-only, enforced by an ORM guard
# (see app.db.models.audit) and a Postgres trigger in the migration.
