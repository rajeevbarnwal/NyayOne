"""Wave 2 tutoring marketplace schema (SAATHI-123 / SAATHI-127).

17 tables: tutor discovery (tutor_profiles, tutor_subjects,
tutor_availability_slots), booking + money (booking_holds, payment_orders,
payment_events, payment_refunds), session lifecycle (tutoring_sessions,
booking_events, session_status_history, session_attendance,
session_cancellations), reviews (tutor_reviews, review_moderation) and delivery
(tutoring_outbox, session_reminder_jobs, video_session_grants).

Forward-only, explicit DDL — no metadata.create_all. Constraint names match the
ORM (``app/models/wave2.py``) exactly so ``alembic check`` reports no drift.

Data-protection invariants encoded in the DDL, not just in service code:
* ``payment_orders`` has NO pan/cvv/otp column; only brand, ``masked_last4``
  (CHECK length = 4) and expiry month/year are representable.
* ``payment_events`` keeps ``payload_digest`` (a hash) and a UNIQUE
  ``provider_event_id`` for webhook replay protection — never a raw payload.
* ``video_session_grants`` stores ``token_hash`` only, never a join token.
* ``tutoring_outbox.last_error`` is VARCHAR(200), reserved for codes, never PII.

"At most one row in state X per parent" — enforced twice, portably:

1. Portable fallback, present on EVERY dialect (this is what SQLite, and any
   engine without partial indexes, relies on): a maintained marker column that
   equals the parent id while the row is in the guarded state and is NULL
   otherwise, plus a plain UNIQUE constraint on that column (NULLs are distinct
   in both PostgreSQL and SQLite). A CHECK constraint keeps the marker honest so
   it cannot be set to a wrong/stale value:
     - booking_holds.active_slot_id + uq_booking_holds_active_slot_id
       + ck_booking_holds_active_marker  => ONE 'active' hold per slot.
     - payment_refunds.succeeded_order_id + uq_payment_refunds_succeeded_order_id
       + ck_payment_refunds_succeeded_marker => ONE 'succeeded' refund per order
       (blocks duplicate full refunds).
2. Native partial unique indexes with the same semantics:
   uq_booking_holds_one_active_per_slot and
   uq_payment_refunds_one_succeeded_per_order. Created behind a dialect guard —
   the PostgreSQL branch uses ``postgresql_where``; SQLite gets the equivalent
   ``sqlite_where`` branch so test-suite parity and ``alembic check`` agree with
   the ORM declaration. Any other dialect silently falls back to (1).
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_wave2_tutoring"
down_revision: Union[str, None] = "0007_wave3_credentials"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)

# Partial unique indexes: (index name, table, column, predicate)
_PARTIAL_UNIQUE = (
    ("uq_booking_holds_one_active_per_slot", "booking_holds", "slot_id",
     "status = 'active'"),
    ("uq_payment_refunds_one_succeeded_per_order", "payment_refunds", "order_id",
     "status = 'succeeded'"),
)

SESSION_STATUSES = (
    "confirmed", "pending_provider", "rescheduled", "cancelled", "completed",
    "disputed",
)
ACTOR_ROLES = ("student", "tutor", "admin", "system")


def _ts() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    ]


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _in_or_null(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IS NULL OR {_in(column, values)}"


def upgrade() -> None:
    # ------------------------- tutor discovery ---------------------------------
    op.create_table(
        "tutor_profiles",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("headline", sa.String(200), nullable=True),
        sa.Column(
            "experience_years", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("rating_avg", sa.Numeric(3, 2), nullable=True),
        sa.Column("rating_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "verified_identity",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "verified_credentials",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "source", sa.String(40), server_default="self_declared", nullable=False
        ),
        sa.Column("source_url", sa.String(400), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(24), server_default="draft", nullable=False),
        *_ts(),
        sa.UniqueConstraint("user_id", name="uq_tutor_profiles_user_id"),
        sa.CheckConstraint(
            _in(
                "status",
                ("draft", "pending_review", "active", "suspended", "retired"),
            ),
            name="status",
        ),
        sa.CheckConstraint(
            "experience_years >= 0", name="experience_nonnegative"
        ),
        sa.CheckConstraint("rating_count >= 0", name="rating_count_nonnegative"),
        sa.CheckConstraint(
            "rating_avg IS NULL OR (rating_avg >= 0 AND rating_avg <= 5)",
            name="rating_avg_range",
        ),
    )
    op.create_index("ix_tutor_profiles_user_id", "tutor_profiles", ["user_id"])

    op.create_table(
        "tutor_subjects",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tutor_id",
            _UUID,
            sa.ForeignKey("tutor_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(80), nullable=False),
        sa.Column("level", sa.String(40), nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "tutor_id",
            "subject",
            "level",
            name="uq_tutor_subjects_tutor_subject_level",
        ),
    )
    op.create_index("ix_tutor_subjects_tutor_id", "tutor_subjects", ["tutor_id"])

    op.create_table(
        "tutor_availability_slots",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "tutor_id",
            _UUID,
            sa.ForeignKey("tutor_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "iana_timezone",
            sa.String(64),
            server_default="Asia/Kolkata",
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(16), server_default="available", nullable=False
        ),
        *_ts(),
        sa.UniqueConstraint(
            "tutor_id", "start_utc", name="uq_tutor_availability_slots_start"
        ),
        sa.CheckConstraint(
            _in(
                "status",
                ("available", "held", "booked", "expired", "cancelled"),
            ),
            name="status",
        ),
        sa.CheckConstraint("end_utc > start_utc", name="slot_end_after_start"),
    )
    op.create_index(
        "ix_tutor_availability_slots_tutor_id",
        "tutor_availability_slots",
        ["tutor_id"],
    )
    op.create_index(
        "ix_tutor_availability_slots_start_utc",
        "tutor_availability_slots",
        ["start_utc"],
    )

    # ------------------------- holds and payments ------------------------------
    op.create_table(
        "booking_holds",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "slot_id",
            _UUID,
            sa.ForeignKey("tutor_availability_slots.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        # Portable one-active-hold-per-slot marker (see module docstring).
        sa.Column("active_slot_id", _UUID, nullable=True),
        *_ts(),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_booking_holds_idempotency_key"
        ),
        sa.UniqueConstraint(
            "active_slot_id", name="uq_booking_holds_active_slot_id"
        ),
        sa.CheckConstraint(
            _in("status", ("active", "consumed", "expired", "released")),
            name="status",
        ),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_created"),
        sa.CheckConstraint(
            "(status = 'active' AND active_slot_id = slot_id) "
            "OR (status <> 'active' AND active_slot_id IS NULL)",
            name="active_marker",
        ),
    )
    op.create_index("ix_booking_holds_slot_id", "booking_holds", ["slot_id"])
    op.create_index(
        "ix_booking_holds_student_user_id", "booking_holds", ["student_user_id"]
    )
    op.create_index("ix_booking_holds_expires_at", "booking_holds", ["expires_at"])

    op.create_table(
        "payment_orders",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "hold_id",
            _UUID,
            # RESTRICT: the money trail must not vanish with the hold.
            sa.ForeignKey("booking_holds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "provider", sa.String(24), server_default="deterministic", nullable=False
        ),
        sa.Column("provider_order_ref", sa.String(120), nullable=True),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        sa.Column("status", sa.String(16), server_default="created", nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        # Issuer display crumbs ONLY. No pan/cvv/otp column exists by design.
        sa.Column("brand", sa.String(24), nullable=True),
        sa.Column("masked_last4", sa.String(4), nullable=True),
        sa.Column("expiry_month", sa.Integer(), nullable=True),
        sa.Column("expiry_year", sa.Integer(), nullable=True),
        *_ts(),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_payment_orders_idempotency_key"
        ),
        sa.UniqueConstraint(
            "provider", "provider_order_ref", name="uq_payment_orders_provider_ref"
        ),
        sa.CheckConstraint(
            _in("provider", ("deterministic", "razorpay")), name="provider"
        ),
        sa.CheckConstraint(_in("currency", ("INR",)), name="currency"),
        sa.CheckConstraint(
            _in(
                "status",
                (
                    "created",
                    "pending",
                    "paid",
                    "failed",
                    "expired",
                    "cancelled",
                ),
            ),
            name="status",
        ),
        sa.CheckConstraint("amount_paise >= 0", name="amount_nonnegative"),
        sa.CheckConstraint(
            "masked_last4 IS NULL OR length(masked_last4) = 4",
            name="masked_last4_len",
        ),
        sa.CheckConstraint(
            "expiry_month IS NULL OR (expiry_month >= 1 AND expiry_month <= 12)",
            name="expiry_month_range",
        ),
        sa.CheckConstraint(
            "expiry_year IS NULL OR (expiry_year >= 2000 AND expiry_year <= 2100)",
            name="expiry_year_range",
        ),
    )
    op.create_index("ix_payment_orders_hold_id", "payment_orders", ["hold_id"])
    op.create_index(
        "ix_payment_orders_student_user_id", "payment_orders", ["student_user_id"]
    )

    op.create_table(
        "payment_events",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "order_id",
            _UUID,
            sa.ForeignKey("payment_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_event_id", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column(
            "signature_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        # Hash of the payload. Raw provider payloads/secrets are never stored.
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        *_ts(),
        # Replay protection: one row per provider event, ever.
        sa.UniqueConstraint(
            "provider_event_id", name="uq_payment_events_provider_event_id"
        ),
    )
    op.create_index("ix_payment_events_order_id", "payment_events", ["order_id"])

    op.create_table(
        "payment_refunds",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "order_id",
            _UUID,
            sa.ForeignKey("payment_orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("provider_refund_ref", sa.String(120), nullable=True),
        # Portable one-succeeded-refund-per-order marker (see module docstring).
        sa.Column("succeeded_order_id", _UUID, nullable=True),
        *_ts(),
        sa.UniqueConstraint(
            "order_id", "provider_refund_ref", name="uq_payment_refunds_order_ref"
        ),
        sa.UniqueConstraint(
            "succeeded_order_id", name="uq_payment_refunds_succeeded_order_id"
        ),
        sa.CheckConstraint(
            _in(
                "reason",
                ("cancel_ge_24h", "tutor_cancelled", "admin_exception"),
            ),
            name="reason",
        ),
        sa.CheckConstraint(
            _in("status", ("pending", "processing", "succeeded", "failed")),
            name="status",
        ),
        sa.CheckConstraint("amount_paise >= 0", name="amount_nonnegative"),
        sa.CheckConstraint(
            "(status = 'succeeded' AND succeeded_order_id = order_id) "
            "OR (status <> 'succeeded' AND succeeded_order_id IS NULL)",
            name="succeeded_marker",
        ),
    )
    op.create_index("ix_payment_refunds_order_id", "payment_refunds", ["order_id"])

    # ------------------------- session lifecycle -------------------------------
    op.create_table(
        "tutoring_sessions",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "slot_id",
            _UUID,
            sa.ForeignKey("tutor_availability_slots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "tutor_id",
            _UUID,
            sa.ForeignKey("tutor_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "student_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            _UUID,
            sa.ForeignKey("payment_orders.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "iana_timezone",
            sa.String(64),
            server_default="Asia/Kolkata",
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(24), server_default="confirmed", nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        # One session per slot: double-booking is structurally impossible.
        sa.UniqueConstraint("slot_id", name="uq_tutoring_sessions_slot_id"),
        sa.CheckConstraint(_in("status", SESSION_STATUSES), name="status"),
        sa.CheckConstraint("end_utc > start_utc", name="session_end_after_start"),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index("ix_tutoring_sessions_slot_id", "tutoring_sessions", ["slot_id"])
    op.create_index(
        "ix_tutoring_sessions_tutor_id", "tutoring_sessions", ["tutor_id"]
    )
    op.create_index(
        "ix_tutoring_sessions_student_user_id",
        "tutoring_sessions",
        ["student_user_id"],
    )
    op.create_index(
        "ix_tutoring_sessions_order_id", "tutoring_sessions", ["order_id"]
    )
    op.create_index(
        "ix_tutoring_sessions_start_utc", "tutoring_sessions", ["start_utc"]
    )

    op.create_table(
        "booking_events",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "session_id",
            _UUID,
            sa.ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "hold_id",
            _UUID,
            sa.ForeignKey("booking_holds.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("actor_role", sa.String(16), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        # Non-PII payload: ids, codes and amounts only.
        sa.Column("payload_json", sa.JSON(), nullable=True),
        *_ts(),
        sa.CheckConstraint(
            _in(
                "kind",
                (
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
                ),
            ),
            name="kind",
        ),
        sa.CheckConstraint(_in("actor_role", ACTOR_ROLES), name="actor_role"),
        sa.CheckConstraint(
            "session_id IS NOT NULL OR hold_id IS NOT NULL",
            name="subject_present",
        ),
    )
    op.create_index("ix_booking_events_session_id", "booking_events", ["session_id"])
    op.create_index("ix_booking_events_hold_id", "booking_events", ["hold_id"])

    op.create_table(
        "session_status_history",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "session_id",
            _UUID,
            sa.ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_role", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(200), nullable=True),
        *_ts(),
        sa.CheckConstraint(
            _in_or_null("from_status", SESSION_STATUSES), name="from_status"
        ),
        sa.CheckConstraint(_in("to_status", SESSION_STATUSES), name="to_status"),
        sa.CheckConstraint(_in("actor_role", ACTOR_ROLES), name="actor_role"),
    )
    op.create_index(
        "ix_session_status_history_session_id",
        "session_status_history",
        ["session_id"],
    )

    op.create_table(
        "session_attendance",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "session_id",
            _UUID,
            sa.ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(16), server_default="pending", nullable=False),
        sa.Column("recorded_by_role", sa.String(16), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disputed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution", sa.String(24), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *_ts(),
        # Exactly one attendance lifecycle per session.
        sa.UniqueConstraint("session_id", name="uq_session_attendance_session_id"),
        sa.CheckConstraint(
            _in(
                "state",
                ("pending", "recorded", "confirmed", "disputed", "resolved"),
            ),
            name="state",
        ),
        sa.CheckConstraint(
            _in_or_null("recorded_by_role", ("tutor", "admin")),
            name="recorded_by_role",
        ),
        sa.CheckConstraint(
            _in_or_null(
                "resolution",
                ("attended", "no_show_student", "no_show_tutor", "waived"),
            ),
            name="resolution",
        ),
        sa.CheckConstraint(
            "state = 'pending' OR (recorded_at IS NOT NULL "
            "AND recorded_by_role IS NOT NULL)",
            name="recorded_provenance",
        ),
        sa.CheckConstraint(
            "state <> 'resolved' OR (resolved_at IS NOT NULL "
            "AND resolution IS NOT NULL)",
            name="resolution_provenance",
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
    )
    op.create_index(
        "ix_session_attendance_session_id", "session_attendance", ["session_id"]
    )

    op.create_table(
        "session_cancellations",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "session_id",
            _UUID,
            sa.ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cancelled_by_role", sa.String(16), nullable=False),
        sa.Column("hours_before_start", sa.Numeric(8, 2), nullable=False),
        sa.Column("refund_decision", sa.String(24), nullable=False),
        sa.Column(
            "admin_actor_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "audited", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        *_ts(),
        sa.CheckConstraint(
            _in("cancelled_by_role", ("student", "tutor", "admin")),
            name="cancelled_by_role",
        ),
        sa.CheckConstraint(
            _in(
                "refund_decision",
                ("full_refund", "no_auto_refund", "admin_exception"),
            ),
            name="refund_decision",
        ),
        sa.CheckConstraint("hours_before_start >= 0", name="hours_nonnegative"),
        sa.CheckConstraint(
            "refund_decision <> 'admin_exception' OR admin_actor_id IS NOT NULL",
            name="admin_exception_actor",
        ),
    )
    op.create_index(
        "ix_session_cancellations_session_id",
        "session_cancellations",
        ["session_id"],
    )
    op.create_index(
        "ix_session_cancellations_admin_actor_id",
        "session_cancellations",
        ["admin_actor_id"],
    )

    # ------------------------- reviews -----------------------------------------
    op.create_table(
        "tutor_reviews",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "session_id",
            _UUID,
            sa.ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tutor_id",
            _UUID,
            sa.ForeignKey("tutor_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column(
            "published", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("edit_deadline_at", sa.DateTime(timezone=True), nullable=False),
        *_ts(),
        # Exactly one review per session.
        sa.UniqueConstraint("session_id", name="uq_tutor_reviews_session_id"),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="rating_range"),
        sa.CheckConstraint(
            "body IS NULL OR (length(body) >= 10 AND length(body) <= 1000)",
            name="body_length",
        ),
    )
    op.create_index("ix_tutor_reviews_session_id", "tutor_reviews", ["session_id"])
    op.create_index("ix_tutor_reviews_tutor_id", "tutor_reviews", ["tutor_id"])
    op.create_index(
        "ix_tutor_reviews_author_user_id", "tutor_reviews", ["author_user_id"]
    )

    op.create_table(
        "review_moderation",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "review_id",
            _UUID,
            sa.ForeignKey("tutor_reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("state", sa.String(16), server_default="pending", nullable=False),
        sa.Column(
            "moderator_user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(200), nullable=True),
        *_ts(),
        sa.UniqueConstraint("review_id", name="uq_review_moderation_review_id"),
        sa.CheckConstraint(
            _in("state", ("pending", "approved", "rejected")), name="state"
        ),
        sa.CheckConstraint(
            "state = 'pending' OR decided_at IS NOT NULL",
            name="decided_timestamped",
        ),
    )
    op.create_index(
        "ix_review_moderation_review_id", "review_moderation", ["review_id"]
    )
    op.create_index(
        "ix_review_moderation_moderator_user_id",
        "review_moderation",
        ["moderator_user_id"],
    )

    # ------------------------- delivery / notifications ------------------------
    op.create_table(
        "tutoring_outbox",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        # Polymorphic aggregate reference; intentionally not a FK so the audit
        # row survives aggregate deletion.
        sa.Column("aggregate_id", _UUID, nullable=False),
        # Privacy-safe payload only.
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        # Bounded error slot — codes only, never PII.
        sa.Column("last_error", sa.String(200), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.CheckConstraint(
            _in(
                "kind",
                (
                    "booking_confirmed",
                    "booking_cancelled",
                    "payment_captured",
                    "refund_issued",
                    "session_reminder",
                    "review_published",
                    "attendance_recorded",
                ),
            ),
            name="kind",
        ),
        sa.CheckConstraint(
            _in("status", ("pending", "sent", "failed", "void")), name="status"
        ),
        sa.CheckConstraint("attempts >= 0", name="attempts_nonnegative"),
    )
    op.create_index(
        "ix_tutoring_outbox_aggregate_id", "tutoring_outbox", ["aggregate_id"]
    )

    op.create_table(
        "session_reminder_jobs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "session_id",
            _UUID,
            sa.ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("offset_kind", sa.String(8), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(16), server_default="scheduled", nullable=False
        ),
        *_ts(),
        sa.UniqueConstraint(
            "session_id",
            "offset_kind",
            "scheduled_for",
            name="uq_session_reminder_jobs_session_offset",
        ),
        sa.CheckConstraint(
            _in("offset_kind", ("7d", "1d", "3h")), name="offset_kind"
        ),
        sa.CheckConstraint(
            _in("status", ("scheduled", "sent", "revoked", "failed")),
            name="status",
        ),
    )
    op.create_index(
        "ix_session_reminder_jobs_session_id",
        "session_reminder_jobs",
        ["session_id"],
    )
    op.create_index(
        "ix_session_reminder_jobs_scheduled_for",
        "session_reminder_jobs",
        ["scheduled_for"],
    )

    op.create_table(
        "video_session_grants",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "session_id",
            _UUID,
            sa.ForeignKey("tutoring_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Opaque participant reference — never an email/phone/name.
        sa.Column("participant_ref", sa.String(64), nullable=False),
        # Provider-neutral room reference.
        sa.Column("room_ref", sa.String(120), nullable=False),
        sa.Column("permissions", sa.String(64), nullable=False),
        # HASH ONLY. The raw join token is never persisted.
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_ts(),
        sa.UniqueConstraint(
            "session_id",
            "participant_ref",
            "issued_at",
            name="uq_video_session_grants_session_participant",
        ),
        sa.CheckConstraint("expires_at > issued_at", name="expiry_after_issued"),
    )
    op.create_index(
        "ix_video_session_grants_session_id",
        "video_session_grants",
        ["session_id"],
    )

    # ------------------------- dialect-guarded partial unique indexes ----------
    # PostgreSQL gets the native partial unique indexes. SQLite (test/dev) gets
    # the equivalent sqlite_where form so behaviour and `alembic check` match.
    # Any other dialect relies on the portable marker-column UNIQUEs above.
    dialect = op.get_bind().dialect.name
    for index_name, table_name, column_name, predicate in _PARTIAL_UNIQUE:
        if dialect == "postgresql":
            op.create_index(
                index_name,
                table_name,
                [column_name],
                unique=True,
                postgresql_where=sa.text(predicate),
            )
        elif dialect == "sqlite":
            op.create_index(
                index_name,
                table_name,
                [column_name],
                unique=True,
                sqlite_where=sa.text(predicate),
            )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "sqlite"):
        for index_name, table_name, _column, _predicate in _PARTIAL_UNIQUE:
            op.drop_index(index_name, table_name=table_name)

    for table_name in (
        "video_session_grants",
        "session_reminder_jobs",
        "tutoring_outbox",
        "review_moderation",
        "tutor_reviews",
        "session_cancellations",
        "session_attendance",
        "session_status_history",
        "booking_events",
        "tutoring_sessions",
        "payment_refunds",
        "payment_events",
        "payment_orders",
        "booking_holds",
        "tutor_availability_slots",
        "tutor_subjects",
        "tutor_profiles",
    ):
        op.drop_table(table_name)
