"""Install durable OTP authority, abuse budgets and leased delivery state.

Revision ID: 0019_otp_security_authority
Revises: 0018_registration_idempotency

The migration is forward-only in security semantics: it preserves every byte of
0001..0018 and leaves the NYAY-3 partial unique index unchanged.  Existing
challenge-local attempt/lock data is copied into one stable
registration+purpose authority.  Existing outbox rows receive opaque, stable
provider idempotency tokens before the column becomes required.

No legacy browser flow is synthesized: a migration cannot safely mint and
deliver the raw HttpOnly bearer that such a row would require. Existing active
challenges retain authority, while upgraded clients restart once to obtain a
post-0019 reload-safe flow cookie.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import SQLAlchemyError

revision: str = "0019_otp_security_authority"
down_revision: str | None = "0018_registration_idempotency"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)
_AUTHORITY_NAMESPACE = uuid.UUID("d4bd542f-dd07-4512-ac24-c7d789287708")
_PG_ADVISORY_LOCK_KEY = 4353333856519384235


class OtpSecurityDowngradeError(RuntimeError):
    """Raised when downgrade would discard live security authority."""


class OtpSecurityMigrationError(RuntimeError):
    """Sanitized fail-closed migration rejection."""


def _reject() -> OtpSecurityMigrationError:
    return OtpSecurityMigrationError(
        "NYAY-4 OTP security migration rejected unsafe schema or data"
    )


def _downgrade_reject() -> OtpSecurityDowngradeError:
    return OtpSecurityDowngradeError(
        "NYAY-4 downgrade rejected unsafe schema or live OTP security state"
    )


def _authority_subject(mobile_hash: object) -> str:
    return hashlib.sha256(
        f"nyayone:otp-authority:v1:{mobile_hash}".encode("ascii")
    ).hexdigest()


def _provider_key(outbox_id: object) -> str:
    # The input is already a random opaque UUID. A fixed domain key makes the
    # result a deterministic, stable 64-hex provider token without importing
    # deployment secrets into migration history.
    return hmac.new(
        b"nyayone:otp-provider-idempotency:v1",
        str(outbox_id).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _acquire_lock_and_preflight(bind: sa.Connection) -> None:
    try:
        if bind.dialect.name == "postgresql":
            bind.execute(sa.text("SET LOCAL lock_timeout = '5000ms'"))
            bind.execute(sa.text("SET LOCAL statement_timeout = '30000ms'"))
            bind.execute(
                sa.text("SELECT pg_advisory_xact_lock(:value)"),
                {"value": _PG_ADVISORY_LOCK_KEY},
            )
            bind.execute(
                sa.text(
                    "LOCK TABLE registration_idempotency_records, "
                    "student_registrations, otp_challenges, otp_outbox "
                    "IN SHARE ROW EXCLUSIVE MODE NOWAIT"
                )
            )
        elif bind.dialect.name == "sqlite":
            driver = bind.connection.driver_connection
            if not driver.in_transaction:
                bind.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            raise _reject()

        inspector = sa.inspect(bind)
        tables = set(inspector.get_table_names())
        required = {
            "registration_idempotency_records",
            "student_registrations",
            "otp_challenges",
            "otp_outbox",
        }
        forbidden = {
            "otp_purpose_authorities",
            "otp_rate_limit_buckets",
            "otp_flows",
        }
        if not required <= tables or forbidden & tables:
            raise _reject()
        challenge_columns = {item["name"] for item in inspector.get_columns("otp_challenges")}
        outbox_columns = {item["name"] for item in inspector.get_columns("otp_outbox")}
        if {"delivery_state", "authority_id"} & challenge_columns:
            raise _reject()
        if {
            "provider_idempotency_key",
            "claim_token_hash",
            "lease_expires_at",
        } & outbox_columns:
            raise _reject()
        invalid_challenge = bind.scalar(
            sa.text(
                "SELECT 1 FROM otp_challenges WHERE attempts < 0 OR "
                "max_attempts <= 0 OR max_attempts > 10 OR "
                "attempts > max_attempts LIMIT 1"
            )
        )
        invalid_outbox = bind.scalar(
            sa.text(
                "SELECT 1 FROM otp_outbox WHERE status NOT IN "
                "('pending','sent','failed','void') OR attempts < 0 OR "
                "attempts > 10 OR "
                "(status IN ('pending','failed') AND "
                "(code_ct IS NULL OR destination_ct IS NULL)) OR "
                "(status IN ('sent','void') AND code_ct IS NOT NULL) LIMIT 1"
            )
        )
        if invalid_challenge is not None or invalid_outbox is not None:
            raise _reject()
    except OtpSecurityMigrationError:
        raise
    except (AttributeError, SQLAlchemyError, ValueError):
        raise _reject() from None


def _ts_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )


def _hex_residue_is_empty(column: str) -> str:
    expression = column
    for character in "0123456789abcdef":
        expression = f"replace({expression}, '{character}', '')"
    return f"length({expression}) = 0"


def _hex_shape(column: str) -> str:
    return f"length({column}) = 64 AND {_hex_residue_is_empty(column)}"


_LEDGER_STATE_0019 = (
    "state IN ('pending', 'succeeded', 'failed', 'retired', 'erased', "
    "'neutralized')"
)
_LEDGER_FINGERPRINT_0019 = (
    "((state IN ('pending', 'succeeded', 'failed', 'neutralized') AND "
    "request_fingerprint_version = 'v1' AND request_fingerprint IS NOT NULL "
    "AND length(request_fingerprint) = 64 AND "
    + _hex_shape("request_fingerprint")
    + ") OR (state IN ('retired', 'erased') AND request_fingerprint IS NULL "
    "AND request_fingerprint_version IS NULL))"
)
_LEDGER_LINKS_0019 = (
    "(state = 'pending' AND registration_id IS NOT NULL AND outbox_id IS NOT NULL "
    "AND outcome_code IS NULL) OR "
    "(state = 'succeeded' AND registration_id IS NOT NULL AND outbox_id IS NULL "
    "AND outcome_code IS NULL) OR "
    "(state = 'failed' AND registration_id IS NULL AND outbox_id IS NULL AND "
    "outcome_code = 'otp_delivery_failed') OR "
    "(state = 'neutralized' AND registration_id IS NULL AND outbox_id IS NULL "
    "AND outcome_code = 'registration_neutralized') OR "
    "(state IN ('retired', 'erased') AND registration_id IS NULL AND "
    "outbox_id IS NULL AND outcome_code = 'registration_replay_expired')"
)
_LEDGER_STATE_0018 = (
    "state IN ('pending', 'succeeded', 'failed', 'retired', 'erased')"
)
_LEDGER_FINGERPRINT_0018 = (
    "((state IN ('pending', 'succeeded', 'failed') AND "
    "request_fingerprint_version = 'v1' AND request_fingerprint IS NOT NULL "
    "AND length(request_fingerprint) = 64 AND "
    + _hex_residue_is_empty("request_fingerprint")
    + ") OR (state IN ('retired', 'erased') AND request_fingerprint IS NULL "
    "AND request_fingerprint_version IS NULL))"
)
_LEDGER_LINKS_0018 = (
    "(state = 'pending' AND registration_id IS NOT NULL AND outbox_id IS NOT NULL "
    "AND outcome_code IS NULL) OR "
    "(state = 'succeeded' AND registration_id IS NOT NULL AND outbox_id IS NULL "
    "AND outcome_code IS NULL) OR "
    "(state = 'failed' AND registration_id IS NULL AND outbox_id IS NULL AND "
    "outcome_code = 'otp_delivery_failed') OR "
    "(state IN ('retired', 'erased') AND registration_id IS NULL AND "
    "outbox_id IS NULL AND outcome_code = 'registration_replay_expired')"
)


def _as_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed


def _issued_at(row: sa.RowMapping) -> datetime:
    """Use the historical server-issued timestamp, never browser metadata."""

    metadata = row.get("metadata_json")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = None
    if isinstance(metadata, dict):
        candidate = metadata.get("issued_at")
        if isinstance(candidate, str):
            try:
                return _as_datetime(candidate)
            except ValueError:
                pass
    return _as_datetime(row["created_at"])


def _install_legacy_destination_guard(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                CREATE FUNCTION nyay4_reject_new_legacy_otp_destination()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.legacy_destination_retained = true AND
                       (TG_OP = 'INSERT' OR OLD.legacy_destination_retained = false)
                    THEN
                        RAISE EXCEPTION 'new legacy OTP destinations are forbidden'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END;
                $$
                """
            )
        )
        bind.execute(
            sa.text(
                """
                CREATE TRIGGER trg_otp_outbox_no_new_legacy_destination
                BEFORE INSERT OR UPDATE OF legacy_destination_retained
                ON otp_outbox FOR EACH ROW
                EXECUTE FUNCTION nyay4_reject_new_legacy_otp_destination()
                """
            )
        )
    else:
        bind.execute(
            sa.text(
                """
                CREATE TRIGGER trg_otp_outbox_no_new_legacy_destination_insert
                BEFORE INSERT ON otp_outbox
                WHEN NEW.legacy_destination_retained = 1
                BEGIN
                    SELECT RAISE(ABORT, 'new legacy OTP destinations are forbidden');
                END
                """
            )
        )
        bind.execute(
            sa.text(
                """
                CREATE TRIGGER trg_otp_outbox_no_new_legacy_destination_update
                BEFORE UPDATE OF legacy_destination_retained ON otp_outbox
                WHEN OLD.legacy_destination_retained = 0
                 AND NEW.legacy_destination_retained = 1
                BEGIN
                    SELECT RAISE(ABORT, 'new legacy OTP destinations are forbidden');
                END
                """
            )
        )


def _drop_legacy_destination_guard(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                "DROP TRIGGER trg_otp_outbox_no_new_legacy_destination ON otp_outbox"
            )
        )
        bind.execute(
            sa.text("DROP FUNCTION nyay4_reject_new_legacy_otp_destination()")
        )
    else:
        bind.execute(
            sa.text("DROP TRIGGER trg_otp_outbox_no_new_legacy_destination_insert")
        )
        bind.execute(
            sa.text("DROP TRIGGER trg_otp_outbox_no_new_legacy_destination_update")
        )


def _acquire_downgrade_lock_and_preflight(bind: sa.Connection) -> None:
    """Validate the exact 0019-owned surface before the first read or DDL."""

    try:
        if bind.dialect.name == "postgresql":
            bind.execute(sa.text("SET LOCAL lock_timeout = '5000ms'"))
            bind.execute(sa.text("SET LOCAL statement_timeout = '30000ms'"))
            bind.execute(
                sa.text("SELECT pg_advisory_xact_lock(:value)"),
                {"value": _PG_ADVISORY_LOCK_KEY},
            )
            bind.execute(
                sa.text(
                    "LOCK TABLE registration_idempotency_records, "
                    "student_registrations, otp_purpose_authorities, "
                    "otp_rate_limit_buckets, otp_challenges, otp_flows, "
                    "otp_outbox IN SHARE ROW EXCLUSIVE MODE NOWAIT"
                )
            )
        elif bind.dialect.name == "sqlite":
            driver = bind.connection.driver_connection
            if not driver.in_transaction:
                bind.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            raise _downgrade_reject()

        inspector = sa.inspect(bind)
        required_tables = {
            "registration_idempotency_records",
            "student_registrations",
            "otp_purpose_authorities",
            "otp_rate_limit_buckets",
            "otp_challenges",
            "otp_flows",
            "otp_outbox",
        }
        if not required_tables <= set(inspector.get_table_names()):
            raise _downgrade_reject()
        challenge_columns = {
            item["name"]: item for item in inspector.get_columns("otp_challenges")
        }
        outbox_columns = {
            item["name"]: item for item in inspector.get_columns("otp_outbox")
        }
        expected_outbox_owned = {
            "provider_idempotency_key",
            "claim_token_hash",
            "claimed_at",
            "lease_expires_at",
            "next_attempt_at",
            "provider_receipt_hash",
            "provider_receipt_key_version",
            "legacy_destination_retained",
            "max_attempts",
        }
        if (
            {"authority_id", "delivery_state"} - set(challenge_columns)
            or bool(challenge_columns["authority_id"].get("nullable"))
            or expected_outbox_owned - set(outbox_columns)
            or bool(outbox_columns["provider_idempotency_key"].get("nullable"))
            or not bool(outbox_columns["destination_ct"].get("nullable"))
        ):
            raise _downgrade_reject()
        challenge_indexes = {
            item.get("name") for item in inspector.get_indexes("otp_challenges")
        }
        flow_indexes = {
            item.get("name") for item in inspector.get_indexes("otp_flows")
        }
        if not {
            "ix_otp_challenges_authority_id",
            "uq_otp_challenges_one_active_per_authority",
            "uq_otp_challenges_one_pending_delivery_per_authority",
        } <= challenge_indexes or not {
            "ix_otp_flows_registration_id",
            "ix_otp_flows_registration_idempotency_record_id",
            "ix_otp_flows_challenge_id",
            "ix_otp_flows_authority_id",
            "uq_otp_flows_one_nonterminal_per_authority",
        } <= flow_indexes:
            raise _downgrade_reject()
        if bind.dialect.name == "postgresql":
            trigger_names = set(
                bind.scalars(
                    sa.text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE tgrelid='otp_outbox'::regclass AND NOT tgisinternal "
                        "AND tgname LIKE "
                        "'trg_otp_outbox_no_new_legacy_destination%'"
                    )
                )
            )
            expected_triggers = {"trg_otp_outbox_no_new_legacy_destination"}
        else:
            trigger_names = set(
                bind.scalars(
                    sa.text(
                        "SELECT name FROM sqlite_master WHERE type='trigger' "
                        "AND tbl_name='otp_outbox' AND name LIKE "
                        "'trg_otp_outbox_no_new_legacy_destination%'"
                    )
                )
            )
            expected_triggers = {
                "trg_otp_outbox_no_new_legacy_destination_insert",
                "trg_otp_outbox_no_new_legacy_destination_update",
            }
        if trigger_names != expected_triggers:
            raise _downgrade_reject()
    except OtpSecurityDowngradeError:
        raise
    except (AttributeError, KeyError, SQLAlchemyError, TypeError, ValueError):
        raise _downgrade_reject() from None


def upgrade() -> None:
    bind = op.get_bind()
    _acquire_lock_and_preflight(bind)
    with op.batch_alter_table("registration_idempotency_records") as batch:
        batch.drop_constraint(
            op.f("ck_registration_idempotency_records_state_links"),
            type_="check",
        )
        batch.drop_constraint(
            op.f("ck_registration_idempotency_records_request_fingerprint_shape"),
            type_="check",
        )
        batch.drop_constraint(
            op.f("ck_registration_idempotency_records_state"), type_="check"
        )
        batch.create_check_constraint(
            op.f("ck_registration_idempotency_records_state"),
            _LEDGER_STATE_0019,
        )
        batch.create_check_constraint(
            op.f("ck_registration_idempotency_records_request_fingerprint_shape"),
            _LEDGER_FINGERPRINT_0019,
        )
        batch.create_check_constraint(
            op.f("ck_registration_idempotency_records_state_links"),
            _LEDGER_LINKS_0019,
        )
    op.create_table(
        "otp_purpose_authorities",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column(
            "registration_id",
            _UUID,
            sa.ForeignKey(
                "student_registrations.id",
                name="fk_otp_authority_registration",
                ondelete="CASCADE",
            ),
            nullable=True,
        ),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resend_window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resend_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_resends", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("active_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        *_ts_columns(),
        sa.UniqueConstraint(
            "subject_hash",
            "purpose",
            name="uq_otp_purpose_authorities_subject_purpose",
        ),
        sa.UniqueConstraint(
            "registration_id",
            "purpose",
            name="uq_otp_purpose_authorities_registration_purpose",
        ),
        sa.CheckConstraint(
            _hex_shape("subject_hash"),
            name=op.f("ck_otp_purpose_authorities_subject_hash_shape"),
        ),
        sa.CheckConstraint(
            "purpose IN ('signup', 'recovery', 'login')",
            name=op.f("ck_otp_purpose_authorities_purpose"),
        ),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name=op.f("ck_otp_purpose_authorities_failed_attempts_nonneg"),
        ),
        sa.CheckConstraint(
            "max_attempts > 0",
            name=op.f("ck_otp_purpose_authorities_max_attempts_positive"),
        ),
        sa.CheckConstraint(
            "max_attempts <= 10",
            name=op.f("ck_otp_purpose_authorities_max_attempts_bounded"),
        ),
        sa.CheckConstraint(
            "failed_attempts <= max_attempts",
            name=op.f("ck_otp_purpose_authorities_failed_attempts_le_max"),
        ),
        sa.CheckConstraint(
            "resend_count >= 0",
            name=op.f("ck_otp_purpose_authorities_resend_count_nonneg"),
        ),
        sa.CheckConstraint(
            "max_resends > 0",
            name=op.f("ck_otp_purpose_authorities_max_resends_positive"),
        ),
        sa.CheckConstraint(
            "max_resends <= 10",
            name=op.f("ck_otp_purpose_authorities_max_resends_bounded"),
        ),
        sa.CheckConstraint(
            "resend_count <= max_resends",
            name=op.f("ck_otp_purpose_authorities_resend_count_within_limit"),
        ),
        sa.CheckConstraint(
            "generation >= 0",
            name=op.f("ck_otp_purpose_authorities_generation_nonneg"),
        ),
    )
    op.create_index(
        "ix_otp_purpose_authorities_registration_id",
        "otp_purpose_authorities",
        ["registration_id"],
    )

    op.create_table(
        "otp_rate_limit_buckets",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("max_requests", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "scope",
            "subject_hash",
            "action",
            name="uq_otp_rate_limit_buckets_scope_subject_action",
        ),
        sa.CheckConstraint(
            "scope IN ('identity', 'ip', 'global')",
            name=op.f("ck_otp_rate_limit_buckets_scope"),
        ),
        sa.CheckConstraint(
            "action IN ('issue', 'resend', 'verify')",
            name=op.f("ck_otp_rate_limit_buckets_action"),
        ),
        sa.CheckConstraint(
            _hex_shape("subject_hash"),
            name=op.f("ck_otp_rate_limit_buckets_subject_hash_shape"),
        ),
        sa.CheckConstraint(
            "window_seconds > 0",
            name=op.f("ck_otp_rate_limit_buckets_window_seconds_positive"),
        ),
        sa.CheckConstraint(
            "window_seconds <= 86400",
            name=op.f("ck_otp_rate_limit_buckets_window_seconds_bounded"),
        ),
        sa.CheckConstraint(
            "request_count >= 0",
            name=op.f("ck_otp_rate_limit_buckets_request_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "max_requests > 0",
            name=op.f("ck_otp_rate_limit_buckets_max_requests_positive"),
        ),
        sa.CheckConstraint(
            "max_requests <= 100000",
            name=op.f("ck_otp_rate_limit_buckets_max_requests_bounded"),
        ),
        sa.CheckConstraint(
            "request_count <= max_requests",
            name=op.f("ck_otp_rate_limit_buckets_request_count_within_limit"),
        ),
    )

    # Additive columns first; backfill before enforcing new CHECKs/indexes.
    with op.batch_alter_table("otp_challenges") as batch:
        batch.add_column(sa.Column("authority_id", _UUID, nullable=True))
        batch.add_column(
            sa.Column(
                "delivery_state",
                sa.String(24),
                nullable=False,
                server_default="active",
            )
        )
    bind.execute(
        sa.text(
            "UPDATE otp_challenges SET delivery_state = "
            "CASE WHEN consumed_at IS NULL THEN 'active' ELSE 'consumed' END"
        )
    )
    with op.batch_alter_table("otp_challenges") as batch:
        batch.create_foreign_key(
            "fk_otp_challenges_authority",
            "otp_purpose_authorities",
            ["authority_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            op.f("ck_otp_challenges_delivery_state"),
            "delivery_state IN ('pending_delivery', 'active', 'consumed', "
            "'superseded', 'void')",
        )
        batch.create_check_constraint(
            op.f("ck_otp_challenges_delivery_state_consumed_at"),
            "(delivery_state = 'active' AND consumed_at IS NULL) OR "
            "(delivery_state <> 'active' AND consumed_at IS NOT NULL)",
        )

    challenge_rows = list(
        bind.execute(
            sa.text(
                "SELECT c.id, c.registration_id, c.purpose, c.attempts, "
                "c.max_attempts, c.locked_until, c.expires_at, c.consumed_at, "
                "c.created_at, c.metadata_json, r.mobile_hash "
                "FROM otp_challenges c "
                "JOIN student_registrations r ON r.id = c.registration_id "
                "ORDER BY c.registration_id, c.purpose, c.created_at, c.id"
            )
        ).mappings()
    )
    grouped: dict[tuple[str, str], list[sa.RowMapping]] = defaultdict(list)
    for row in challenge_rows:
        grouped[(str(row["registration_id"]), str(row["purpose"]))].append(row)
    authority_table = sa.table(
        "otp_purpose_authorities",
        sa.column("id", _UUID),
        sa.column("subject_hash", sa.String()),
        sa.column("registration_id", _UUID),
        sa.column("purpose", sa.String()),
        sa.column("failed_attempts", sa.Integer()),
        sa.column("max_attempts", sa.Integer()),
        sa.column("locked_until", sa.DateTime(timezone=True)),
        sa.column("attempt_window_started_at", sa.DateTime(timezone=True)),
        sa.column("last_issued_at", sa.DateTime(timezone=True)),
        sa.column("cooldown_until", sa.DateTime(timezone=True)),
        sa.column("resend_window_started_at", sa.DateTime(timezone=True)),
        sa.column("resend_count", sa.Integer()),
        sa.column("max_resends", sa.Integer()),
        sa.column("active_expires_at", sa.DateTime(timezone=True)),
        sa.column("generation", sa.Integer()),
    )
    challenge_table = sa.table(
        "otp_challenges",
        sa.column("authority_id", _UUID),
        sa.column("registration_id", _UUID),
        sa.column("purpose", sa.String()),
    )
    for (registration_id, purpose), rows in grouped.items():
        active = next((item for item in reversed(rows) if item["consumed_at"] is None), None)
        latest = rows[-1]
        source = active or latest
        attempts = min(int(source["attempts"]), int(source["max_attempts"]))
        last_issued = _issued_at(latest)
        bind.execute(
            authority_table.insert().values(
                id=uuid.uuid5(_AUTHORITY_NAMESPACE, f"{registration_id}:{purpose}"),
                subject_hash=_authority_subject(source["mobile_hash"]),
                registration_id=_as_uuid(registration_id),
                purpose=purpose,
                failed_attempts=attempts if active is not None else 0,
                max_attempts=int(source["max_attempts"]),
                locked_until=(
                    _as_datetime(source["locked_until"])
                    if active is not None and source["locked_until"] is not None
                    else None
                ),
                attempt_window_started_at=(
                    _as_datetime(active["created_at"])
                    if active is not None and attempts
                    else None
                ),
                last_issued_at=last_issued,
                cooldown_until=last_issued + timedelta(seconds=30),
                resend_window_started_at=None,
                resend_count=0,
                max_resends=3,
                active_expires_at=(
                    _as_datetime(active["expires_at"])
                    if active is not None
                    else None
                ),
                generation=len(rows),
            )
        )
        authority_id = uuid.uuid5(
            _AUTHORITY_NAMESPACE, f"{registration_id}:{purpose}"
        )
        bind.execute(
            challenge_table.update()
            .where(challenge_table.c.registration_id == _as_uuid(registration_id))
            .where(challenge_table.c.purpose == purpose)
            .values(authority_id=authority_id)
        )

    with op.batch_alter_table("otp_challenges") as batch:
        batch.alter_column(
            "authority_id",
            existing_type=_UUID,
            nullable=False,
        )
        batch.alter_column(
            "delivery_state",
            existing_type=sa.String(24),
            server_default="pending_delivery",
            nullable=False,
        )

    op.create_index(
        "ix_otp_challenges_authority_id",
        "otp_challenges",
        ["authority_id"],
    )
    op.create_index(
        "uq_otp_challenges_one_active_per_authority",
        "otp_challenges",
        ["authority_id"],
        unique=True,
        postgresql_where=sa.text(
            "authority_id IS NOT NULL AND delivery_state = 'active'"
        ),
        sqlite_where=sa.text(
            "authority_id IS NOT NULL AND delivery_state = 'active'"
        ),
    )
    op.create_index(
        "uq_otp_challenges_one_pending_delivery_per_authority",
        "otp_challenges",
        ["authority_id"],
        unique=True,
        postgresql_where=sa.text(
            "authority_id IS NOT NULL AND delivery_state = 'pending_delivery'"
        ),
        sqlite_where=sa.text(
            "authority_id IS NOT NULL AND delivery_state = 'pending_delivery'"
        ),
    )

    op.create_table(
        "otp_flows",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "authority_id",
            _UUID,
            sa.ForeignKey("otp_purpose_authorities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column(
            "registration_id",
            _UUID,
            sa.ForeignKey("student_registrations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "challenge_id",
            _UUID,
            sa.ForeignKey("otp_challenges.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "registration_idempotency_record_id",
            _UUID,
            sa.ForeignKey(
                "registration_idempotency_records.id",
                name="fk_otp_flow_registration_idempotency",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column("destination_masked_ct", sa.String(600), nullable=True),
        sa.Column("key_version", sa.String(8), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        *_ts_columns(),
        sa.UniqueConstraint("token_hash", name="uq_otp_flows_token_hash"),
        sa.UniqueConstraint(
            "registration_idempotency_record_id",
            name="uq_otp_flows_registration_idempotency_record_id",
        ),
        sa.CheckConstraint(
            "purpose IN ('signup','recovery','login')",
            name=op.f("ck_otp_flows_purpose"),
        ),
        sa.CheckConstraint(
            "state IN ('pending','code_sent','verified','locked','expired',"
            "'consumed','failed')",
            name=op.f("ck_otp_flows_state"),
        ),
        sa.CheckConstraint(
            _hex_shape("token_hash"),
            name=op.f("ck_otp_flows_token_hash_shape"),
        ),
        sa.CheckConstraint(
            _hex_shape("subject_hash"),
            name=op.f("ck_otp_flows_subject_hash_shape"),
        ),
        sa.CheckConstraint(
            "registration_id IS NOT NULL OR challenge_id IS NULL",
            name=op.f("ck_otp_flows_challenge_requires_registration"),
        ),
        sa.CheckConstraint(
            "(state IN ('expired', 'consumed', 'failed') AND "
            "consumed_at IS NOT NULL) OR "
            "(state IN ('pending', 'code_sent', 'verified', 'locked') AND "
            "consumed_at IS NULL)",
            name=op.f("ck_otp_flows_consumption_shape"),
        ),
        sa.CheckConstraint(
            "state <> 'verified' OR "
            "(registration_id IS NOT NULL AND challenge_id IS NOT NULL)",
            name=op.f("ck_otp_flows_verified_links"),
        ),
        sa.CheckConstraint(
            "(state IN ('pending', 'code_sent', 'locked') AND "
            "destination_masked_ct IS NOT NULL AND key_version IS NOT NULL) OR "
            "(state IN ('verified', 'expired', 'consumed', 'failed') AND "
            "destination_masked_ct IS NULL AND key_version IS NULL)",
            name=op.f("ck_otp_flows_destination_shape"),
        ),
    )
    op.create_index("ix_otp_flows_registration_id", "otp_flows", ["registration_id"])
    op.create_index(
        "ix_otp_flows_registration_idempotency_record_id",
        "otp_flows",
        ["registration_idempotency_record_id"],
    )
    op.create_index("ix_otp_flows_challenge_id", "otp_flows", ["challenge_id"])
    op.create_index("ix_otp_flows_authority_id", "otp_flows", ["authority_id"])
    op.create_index(
        "uq_otp_flows_one_nonterminal_per_authority",
        "otp_flows",
        ["authority_id"],
        unique=True,
        postgresql_where=sa.text(
            "state IN ('pending', 'code_sent', 'verified', 'locked')"
        ),
        sqlite_where=sa.text(
            "state IN ('pending', 'code_sent', 'verified', 'locked')"
        ),
    )

    with op.batch_alter_table("otp_outbox") as batch:
        batch.alter_column(
            "destination_ct",
            existing_type=sa.String(600),
            nullable=True,
        )
        batch.add_column(sa.Column("provider_idempotency_key", sa.String(64), nullable=True))
        batch.add_column(sa.Column("claim_token_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("provider_receipt_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("provider_receipt_key_version", sa.String(8), nullable=True))
        batch.add_column(
            sa.Column(
                "legacy_destination_retained",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5")
        )
    outbox_ids = list(bind.execute(sa.text("SELECT id, attempts FROM otp_outbox")).mappings())
    for row in outbox_ids:
        token = _provider_key(row["id"])
        bind.execute(
            sa.text(
                "UPDATE otp_outbox SET provider_idempotency_key=:token, "
                "max_attempts=:maximum WHERE id=:id"
            ),
            {
                "token": token,
                "maximum": max(5, int(row["attempts"])),
                "id": row["id"],
            },
        )
    bind.execute(
        sa.text(
            "UPDATE otp_outbox SET legacy_destination_retained=true "
            "WHERE status IN ('sent','void') AND destination_ct IS NOT NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE otp_outbox SET next_attempt_at=updated_at WHERE status='failed'"
        )
    )
    with op.batch_alter_table("otp_outbox") as batch:
        batch.alter_column(
            "provider_idempotency_key",
            existing_type=sa.String(64),
            nullable=False,
        )
        batch.create_unique_constraint(
            "uq_otp_outbox_provider_idempotency_key",
            ["provider_idempotency_key"],
        )
        batch.drop_constraint("ck_otp_outbox_status", type_="check")
        batch.create_check_constraint(
            op.f("ck_otp_outbox_status"),
            "status IN ('pending', 'claimed', 'sent', 'failed', 'void')",
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_max_attempts_positive"), "max_attempts > 0"
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_max_attempts_bounded"), "max_attempts <= 10"
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_attempts_le_max"), "attempts <= max_attempts"
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_provider_idempotency_key_shape"),
            _hex_shape("provider_idempotency_key"),
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_claim_shape"),
            "(status = 'claimed' AND claim_token_hash IS NOT NULL AND "
            "claimed_at IS NOT NULL AND lease_expires_at IS NOT NULL AND "
            "lease_expires_at > claimed_at) OR "
            "(status <> 'claimed' AND claim_token_hash IS NULL AND "
            "claimed_at IS NULL AND lease_expires_at IS NULL)",
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_claim_token_hash_shape"),
            "claim_token_hash IS NULL OR (" + _hex_shape("claim_token_hash") + ")",
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_payload_shape"),
            "(status IN ('pending', 'claimed', 'failed') AND code_ct IS NOT NULL "
            "AND destination_ct IS NOT NULL AND "
            "legacy_destination_retained = false) OR "
            "(status IN ('sent', 'void') AND code_ct IS NULL AND "
            "((destination_ct IS NULL AND legacy_destination_retained = false) "
            "OR (destination_ct IS NOT NULL AND "
            "legacy_destination_retained = true)))",
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_legacy_destination_terminal"),
            "legacy_destination_retained = false OR "
            "status IN ('sent', 'void')",
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_retry_shape"),
            "(status = 'failed' AND next_attempt_at IS NOT NULL) OR "
            "(status <> 'failed' AND next_attempt_at IS NULL)",
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_provider_receipt_shape"),
            "(provider_receipt_hash IS NULL AND provider_receipt_key_version IS NULL) "
            "OR (status = 'sent' AND provider_receipt_hash IS NOT NULL AND "
            "provider_receipt_key_version = 'v1')",
        )
        batch.create_check_constraint(
            op.f("ck_otp_outbox_provider_receipt_hash_shape"),
            "provider_receipt_hash IS NULL OR ("
            + _hex_shape("provider_receipt_hash")
            + ")",
        )
    _install_legacy_destination_guard(bind)


def downgrade() -> None:
    bind = op.get_bind()
    _acquire_downgrade_lock_and_preflight(bind)
    try:
        unsafe = any(
            bind.scalar(sa.text(statement)) is not None
            for statement in (
                "SELECT 1 FROM otp_purpose_authorities LIMIT 1",
                "SELECT 1 FROM otp_flows LIMIT 1",
                "SELECT 1 FROM otp_rate_limit_buckets LIMIT 1",
                "SELECT 1 FROM otp_challenges LIMIT 1",
                "SELECT 1 FROM otp_outbox LIMIT 1",
                "SELECT 1 FROM registration_idempotency_records "
                "WHERE state = 'neutralized' LIMIT 1",
            )
        )
    except SQLAlchemyError:
        raise _downgrade_reject() from None
    if unsafe:
        raise _downgrade_reject()

    _drop_legacy_destination_guard(bind)

    with op.batch_alter_table("otp_outbox") as batch:
        batch.drop_constraint(
            op.f("ck_otp_outbox_provider_receipt_hash_shape"), type_="check"
        )
        batch.drop_constraint(op.f("ck_otp_outbox_provider_receipt_shape"), type_="check")
        batch.drop_constraint(op.f("ck_otp_outbox_retry_shape"), type_="check")
        batch.drop_constraint(op.f("ck_otp_outbox_legacy_destination_terminal"), type_="check")
        batch.drop_constraint(op.f("ck_otp_outbox_payload_shape"), type_="check")
        batch.drop_constraint(op.f("ck_otp_outbox_claim_shape"), type_="check")
        batch.drop_constraint(
            op.f("ck_otp_outbox_claim_token_hash_shape"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_otp_outbox_provider_idempotency_key_shape"), type_="check"
        )
        batch.drop_constraint(op.f("ck_otp_outbox_attempts_le_max"), type_="check")
        batch.drop_constraint(op.f("ck_otp_outbox_max_attempts_bounded"), type_="check")
        batch.drop_constraint(op.f("ck_otp_outbox_max_attempts_positive"), type_="check")
        batch.drop_constraint(
            "uq_otp_outbox_provider_idempotency_key", type_="unique"
        )
        batch.drop_constraint(op.f("ck_otp_outbox_status"), type_="check")
        batch.create_check_constraint(
            "ck_otp_outbox_status",
            "status IN ('pending', 'sent', 'failed', 'void')",
        )
        batch.drop_column("max_attempts")
        batch.drop_column("legacy_destination_retained")
        batch.drop_column("provider_receipt_key_version")
        batch.drop_column("provider_receipt_hash")
        batch.drop_column("next_attempt_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("claimed_at")
        batch.drop_column("claim_token_hash")
        batch.drop_column("provider_idempotency_key")
        batch.alter_column(
            "destination_ct",
            existing_type=sa.String(600),
            nullable=False,
        )

    op.drop_index(
        "uq_otp_flows_one_nonterminal_per_authority", table_name="otp_flows"
    )
    op.drop_index("ix_otp_flows_authority_id", table_name="otp_flows")
    op.drop_index("ix_otp_flows_challenge_id", table_name="otp_flows")
    op.drop_index("ix_otp_flows_registration_id", table_name="otp_flows")
    op.drop_index(
        "ix_otp_flows_registration_idempotency_record_id",
        table_name="otp_flows",
    )
    op.drop_table("otp_flows")

    op.drop_index(
        "uq_otp_challenges_one_pending_delivery_per_authority",
        table_name="otp_challenges",
    )
    op.drop_index(
        "uq_otp_challenges_one_active_per_authority",
        table_name="otp_challenges",
    )
    op.drop_index("ix_otp_challenges_authority_id", table_name="otp_challenges")
    with op.batch_alter_table("otp_challenges") as batch:
        batch.drop_constraint(
            op.f("ck_otp_challenges_delivery_state_consumed_at"), type_="check"
        )
        batch.drop_constraint(op.f("ck_otp_challenges_delivery_state"), type_="check")
        batch.drop_constraint("fk_otp_challenges_authority", type_="foreignkey")
        batch.drop_column("authority_id")
        batch.drop_column("delivery_state")

    op.drop_table("otp_rate_limit_buckets")
    op.drop_index(
        "ix_otp_purpose_authorities_registration_id",
        table_name="otp_purpose_authorities",
    )
    op.drop_table("otp_purpose_authorities")

    with op.batch_alter_table("registration_idempotency_records") as batch:
        batch.drop_constraint(
            op.f("ck_registration_idempotency_records_state_links"),
            type_="check",
        )
        batch.drop_constraint(
            op.f("ck_registration_idempotency_records_request_fingerprint_shape"),
            type_="check",
        )
        batch.drop_constraint(
            op.f("ck_registration_idempotency_records_state"), type_="check"
        )
        batch.create_check_constraint(
            op.f("ck_registration_idempotency_records_state"),
            _LEDGER_STATE_0018,
        )
        batch.create_check_constraint(
            op.f("ck_registration_idempotency_records_request_fingerprint_shape"),
            _LEDGER_FINGERPRINT_0018,
        )
        batch.create_check_constraint(
            op.f("ck_registration_idempotency_records_state_links"),
            _LEDGER_LINKS_0018,
        )
