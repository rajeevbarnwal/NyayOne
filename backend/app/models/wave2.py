"""Wave 2 tutoring marketplace models (SAATHI-123 / SAATHI-127).

Same conventions as the approved registration / Wave 1 / Wave 3 schemas:
UUID PKs via ``TimestampedBase``, ``timestamptz`` everywhere, every foreign key
indexed with explicit ``ON DELETE`` behaviour, named CHECK constraints on every
finite domain, unique constraints for idempotency and one-per-aggregate rules,
and integer ``version`` columns where optimistic concurrency is required.

Payment and video safety rules baked into the schema (not just service code):

* ``payment_orders`` stores NO cardholder data — there is deliberately no
  ``pan``, ``cvv`` or ``otp`` column. Only issuer-supplied display crumbs
  (brand, masked last four, expiry month/year) are representable, and
  ``masked_last4`` is length-checked to 4.
* ``payment_events`` stores a ``payload_digest`` (hash) only, never the raw
  webhook body or provider secret, and ``provider_event_id`` is UNIQUE so a
  replayed webhook cannot be applied twice.
* ``video_session_grants`` stores ``token_hash`` only — the raw join token is
  never persisted.
* ``tutoring_outbox.last_error`` is a bounded VARCHAR(200) reserved for error
  codes//messages that must never carry PII.

Two invariants need "at most one row in state X per parent". They are enforced
**portably**, twice over:

1. Portable fallback (works on every dialect, including SQLite used by the test
   suite): a maintained marker column that holds the parent id while the row is
   in the guarded state and NULL otherwise, plus a plain UNIQUE constraint on
   that column (NULLs are distinct in both PostgreSQL and SQLite, so any number
   of non-guarded rows may exist). A CHECK constraint keeps the marker honest,
   so the guard cannot be bypassed by writing the wrong marker value:
   - ``booking_holds.active_slot_id`` + ``uq_booking_holds_active_slot_id``
     + ``ck_booking_holds_active_marker`` => at most ONE 'active' hold per slot.
   - ``payment_refunds.succeeded_order_id``
     + ``uq_payment_refunds_succeeded_order_id``
     + ``ck_payment_refunds_succeeded_marker`` => at most ONE 'succeeded'
     refund per order (blocks duplicate full refunds).
2. Native partial unique indexes on the same semantics, created by migration
   0008 for PostgreSQL (and SQLite, which also supports partial indexes) and
   declared here so ``alembic check`` sees no drift:
   ``uq_booking_holds_one_active_per_slot`` and
   ``uq_payment_refunds_one_succeeded_per_order``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import TimestampedBase

# --------------------------- finite domains ------------------------------------
TUTOR_STATUSES = ("draft", "pending_review", "active", "suspended", "retired")
SLOT_STATUSES = ("available", "held", "booked", "expired", "cancelled")
HOLD_STATUSES = ("active", "consumed", "expired", "released")
PAYMENT_PROVIDERS = ("deterministic", "razorpay")
PAYMENT_CURRENCIES = ("INR",)
PAYMENT_ORDER_STATUSES = (
    "created",
    "pending",
    "paid",
    "failed",
    "expired",
    "cancelled",
)
REFUND_REASONS = ("cancel_ge_24h", "tutor_cancelled", "admin_exception")
REFUND_STATUSES = ("pending", "processing", "succeeded", "failed")
SESSION_STATUSES = (
    "confirmed",
    "pending_provider",
    "rescheduled",
    "cancelled",
    "completed",
    "disputed",
)
BOOKING_EVENT_KINDS = (
    "hold_created",
    "hold_consumed",
    "hold_expired",
    "hold_released",
    "payment_initiated",
    "payment_succeeded",
    "payment_failed",
    "session_confirmed",
    "session_rescheduled",
    "session_cancelled",
    "session_completed",
    "refund_requested",
    "refund_succeeded",
)
ACTOR_ROLES = ("student", "tutor", "admin", "system")
CANCEL_ROLES = ("student", "tutor", "admin")
ATTENDANCE_RECORDER_ROLES = ("tutor", "admin")
ATTENDANCE_STATES = ("pending", "recorded", "confirmed", "disputed", "resolved")
ATTENDANCE_RESOLUTIONS = (
    "attended",
    "no_show_student",
    "no_show_tutor",
    "waived",
)
REFUND_DECISIONS = ("full_refund", "no_auto_refund", "admin_exception")
MODERATION_STATES = ("pending", "approved", "rejected")
OUTBOX_KINDS = (
    "booking_confirmed",
    "booking_cancelled",
    "payment_captured",
    "refund_issued",
    "session_reminder",
    "review_published",
    "attendance_recorded",
)
OUTBOX_STATUSES = ("pending", "sent", "failed", "void")
REMINDER_OFFSETS = ("7d", "1d", "3h")
REMINDER_STATUSES = ("scheduled", "sent", "revoked", "failed")


def _in(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IN ({', '.join(repr(value) for value in values)})",
        name=name,
    )


def _in_or_null(column: str, values: tuple[str, ...], name: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} IS NULL OR {column} IN "
        f"({', '.join(repr(value) for value in values)})",
        name=name,
    )


# --------------------------- tutor discovery -----------------------------------
class TutorProfile(TimestampedBase):
    __tablename__ = "tutor_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    headline: Mapped[str | None] = mapped_column(String(200), nullable=True)
    experience_years: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rating_avg: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    verified_identity: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    verified_credentials: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Provenance: where the profile facts came from and when they were pulled.
    source: Mapped[str] = mapped_column(String(40), default="self_declared", nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)

    __table_args__ = (
        # One tutor profile per user account.
        UniqueConstraint("user_id", name="uq_tutor_profiles_user_id"),
        _in("status", TUTOR_STATUSES, "status"),
        CheckConstraint("experience_years >= 0", name="experience_nonnegative"),
        CheckConstraint("rating_count >= 0", name="rating_count_nonnegative"),
        CheckConstraint(
            "rating_avg IS NULL OR (rating_avg >= 0 AND rating_avg <= 5)",
            name="rating_avg_range",
        ),
    )


class TutorSubject(TimestampedBase):
    __tablename__ = "tutor_subjects"

    tutor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutor_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    subject: Mapped[str] = mapped_column(String(80), nullable=False)
    level: Mapped[str] = mapped_column(String(40), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tutor_id", "subject", "level", name="uq_tutor_subjects_tutor_subject_level"
        ),
    )


class TutorAvailabilitySlot(TimestampedBase):
    __tablename__ = "tutor_availability_slots"

    tutor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutor_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Display timezone for the tutor/student; instants themselves are stored UTC.
    iana_timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Kolkata", nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="available", nullable=False)

    __table_args__ = (
        UniqueConstraint("tutor_id", "start_utc", name="uq_tutor_availability_slots_start"),
        _in("status", SLOT_STATUSES, "status"),
        CheckConstraint("end_utc > start_utc", name="slot_end_after_start"),
    )


# --------------------------- hold / payment ------------------------------------
class BookingHold(TimestampedBase):
    __tablename__ = "booking_holds"

    slot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutor_availability_slots.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    student_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    # Portable "one active hold per slot" marker: equals slot_id while the hold
    # is active, NULL otherwise (NULLs are distinct, so expired/released/
    # consumed holds never collide). Kept honest by ck_booking_holds_active_marker.
    active_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_booking_holds_idempotency_key"),
        UniqueConstraint("active_slot_id", name="uq_booking_holds_active_slot_id"),
        _in("status", HOLD_STATUSES, "status"),
        CheckConstraint("expires_at > created_at", name="expiry_after_created"),
        CheckConstraint(
            "(status = 'active' AND active_slot_id = slot_id) "
            "OR (status <> 'active' AND active_slot_id IS NULL)",
            name="active_marker",
        ),
        # Native partial unique index (PostgreSQL and SQLite both support it);
        # migration 0008 creates it behind a dialect guard.
        Index(
            "uq_booking_holds_one_active_per_slot",
            "slot_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )


class PaymentOrder(TimestampedBase):
    """Payment intent. Contains NO cardholder data: no pan/cvv/otp columns."""

    __tablename__ = "payment_orders"

    hold_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        # RESTRICT: the money trail must not disappear with the hold.
        ForeignKey("booking_holds.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    student_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(24), default="deterministic", nullable=False
    )
    provider_order_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="created", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    # Issuer display crumbs only — never the PAN, never a CVV, never an OTP.
    brand: Mapped[str | None] = mapped_column(String(24), nullable=True)
    masked_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    expiry_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiry_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payment_orders_idempotency_key"),
        UniqueConstraint(
            "provider", "provider_order_ref", name="uq_payment_orders_provider_ref"
        ),
        _in("provider", PAYMENT_PROVIDERS, "provider"),
        _in("currency", PAYMENT_CURRENCIES, "currency"),
        _in("status", PAYMENT_ORDER_STATUSES, "status"),
        CheckConstraint("amount_paise >= 0", name="amount_nonnegative"),
        CheckConstraint(
            "masked_last4 IS NULL OR length(masked_last4) = 4", name="masked_last4_len"
        ),
        CheckConstraint(
            "expiry_month IS NULL OR (expiry_month >= 1 AND expiry_month <= 12)",
            name="expiry_month_range",
        ),
        CheckConstraint(
            "expiry_year IS NULL OR (expiry_year >= 2000 AND expiry_year <= 2100)",
            name="expiry_year_range",
        ),
    )


class PaymentEvent(TimestampedBase):
    """Provider webhook ledger. Digest only — never raw payloads or secrets."""

    __tablename__ = "payment_events"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payment_orders.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        # Replay protection: a provider event can only ever be recorded once.
        UniqueConstraint(
            "provider_event_id", name="uq_payment_events_provider_event_id"
        ),
    )


class PaymentRefund(TimestampedBase):
    __tablename__ = "payment_refunds"

    order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payment_orders.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    provider_refund_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Portable "one succeeded refund per order" marker (see module docstring).
    succeeded_order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "order_id", "provider_refund_ref", name="uq_payment_refunds_order_ref"
        ),
        UniqueConstraint(
            "succeeded_order_id", name="uq_payment_refunds_succeeded_order_id"
        ),
        _in("reason", REFUND_REASONS, "reason"),
        _in("status", REFUND_STATUSES, "status"),
        CheckConstraint("amount_paise >= 0", name="amount_nonnegative"),
        CheckConstraint(
            "(status = 'succeeded' AND succeeded_order_id = order_id) "
            "OR (status <> 'succeeded' AND succeeded_order_id IS NULL)",
            name="succeeded_marker",
        ),
        Index(
            "uq_payment_refunds_one_succeeded_per_order",
            "order_id",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
            sqlite_where=text("status = 'succeeded'"),
        ),
    )


# --------------------------- session lifecycle ---------------------------------
class TutoringSession(TimestampedBase):
    __tablename__ = "tutoring_sessions"

    slot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutor_availability_slots.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    tutor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutor_profiles.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    student_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    # Nullable so an admin-created / zero-fee session is representable; a paid
    # booking always carries its order.
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("payment_orders.id", ondelete="RESTRICT"),
        index=True,
        nullable=True,
    )
    start_utc: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    end_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    iana_timezone: Mapped[str] = mapped_column(
        String(64), default="Asia/Kolkata", nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="confirmed", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (
        # A slot can back at most one session (double-booking impossible).
        UniqueConstraint("slot_id", name="uq_tutoring_sessions_slot_id"),
        _in("status", SESSION_STATUSES, "status"),
        CheckConstraint("end_utc > start_utc", name="session_end_after_start"),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class BookingEvent(TimestampedBase):
    """Append-only, non-PII booking audit trail (ids and codes only)."""

    __tablename__ = "booking_events"

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    hold_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("booking_holds.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(16), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        _in("kind", BOOKING_EVENT_KINDS, "kind"),
        _in("actor_role", ACTOR_ROLES, "actor_role"),
        CheckConstraint(
            "session_id IS NOT NULL OR hold_id IS NOT NULL", name="subject_present"
        ),
    )


class SessionStatusHistory(TimestampedBase):
    __tablename__ = "session_status_history"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    from_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        _in_or_null("from_status", SESSION_STATUSES, "from_status"),
        _in("to_status", SESSION_STATUSES, "to_status"),
        _in("actor_role", ACTOR_ROLES, "actor_role"),
    )


class SessionAttendance(TimestampedBase):
    """One attendance lifecycle per session (UNIQUE session_id)."""

    __tablename__ = "session_attendance"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    recorded_by_role: Mapped[str | None] = mapped_column(String(16), nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disputed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolution: Mapped[str | None] = mapped_column(String(24), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (
        UniqueConstraint("session_id", name="uq_session_attendance_session_id"),
        _in("state", ATTENDANCE_STATES, "state"),
        _in_or_null(
            "recorded_by_role", ATTENDANCE_RECORDER_ROLES, "recorded_by_role"
        ),
        _in_or_null("resolution", ATTENDANCE_RESOLUTIONS, "resolution"),
        # Anything past 'pending' must name who recorded it and when.
        CheckConstraint(
            "state = 'pending' OR (recorded_at IS NOT NULL "
            "AND recorded_by_role IS NOT NULL)",
            name="recorded_provenance",
        ),
        CheckConstraint(
            "state <> 'resolved' OR (resolved_at IS NOT NULL "
            "AND resolution IS NOT NULL)",
            name="resolution_provenance",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )


class SessionCancellation(TimestampedBase):
    __tablename__ = "session_cancellations"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    cancelled_by_role: Mapped[str] = mapped_column(String(16), nullable=False)
    hours_before_start: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    refund_decision: Mapped[str] = mapped_column(String(24), nullable=False)
    admin_actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    audited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        _in("cancelled_by_role", CANCEL_ROLES, "cancelled_by_role"),
        _in("refund_decision", REFUND_DECISIONS, "refund_decision"),
        CheckConstraint("hours_before_start >= 0", name="hours_nonnegative"),
        # An admin exception must record which admin granted it.
        CheckConstraint(
            "refund_decision <> 'admin_exception' OR admin_actor_id IS NOT NULL",
            name="admin_exception_actor",
        ),
    )


# --------------------------- reviews -------------------------------------------
class TutorReview(TimestampedBase):
    __tablename__ = "tutor_reviews"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tutor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutor_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    author_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    edit_deadline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # `deleted_at` (soft delete) is inherited from TimestampedBase.

    __table_args__ = (
        # Exactly one review per session.
        UniqueConstraint("session_id", name="uq_tutor_reviews_session_id"),
        CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),
        CheckConstraint(
            "body IS NULL OR (length(body) >= 10 AND length(body) <= 1000)",
            name="body_length",
        ),
    )


class ReviewModeration(TimestampedBase):
    __tablename__ = "review_moderation"

    review_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutor_reviews.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    state: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    moderator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        UniqueConstraint("review_id", name="uq_review_moderation_review_id"),
        _in("state", MODERATION_STATES, "state"),
        # A decided moderation record must be timestamped.
        CheckConstraint(
            "state = 'pending' OR decided_at IS NOT NULL", name="decided_timestamped"
        ),
    )


# --------------------------- delivery / notifications --------------------------
class TutoringOutbox(TimestampedBase):
    """Transactional outbox. payload_json carries privacy-safe fields only."""

    __tablename__ = "tutoring_outbox"

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # Polymorphic aggregate reference (session/order/review id): intentionally
    # not a FK so the outbox row survives aggregate deletion for audit.
    aggregate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), index=True, nullable=False
    )
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Bounded error code/message slot — never PII.
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        _in("kind", OUTBOX_KINDS, "kind"),
        _in("status", OUTBOX_STATUSES, "status"),
        CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )


class SessionReminderJob(TimestampedBase):
    __tablename__ = "session_reminder_jobs"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    offset_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="scheduled", nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "offset_kind",
            "scheduled_for",
            name="uq_session_reminder_jobs_session_offset",
        ),
        _in("offset_kind", REMINDER_OFFSETS, "offset_kind"),
        _in("status", REMINDER_STATUSES, "status"),
    )


class VideoSessionGrant(TimestampedBase):
    """Join credential record. Stores a hash of the token, never the token."""

    __tablename__ = "video_session_grants"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # Opaque per-participant reference (never an email/phone/name).
    participant_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    # Provider-neutral room reference (LiveKit/deterministic/other).
    room_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    permissions: Mapped[str] = mapped_column(String(64), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "participant_ref",
            "issued_at",
            name="uq_video_session_grants_session_participant",
        ),
        CheckConstraint("expires_at > issued_at", name="expiry_after_issued"),
    )
