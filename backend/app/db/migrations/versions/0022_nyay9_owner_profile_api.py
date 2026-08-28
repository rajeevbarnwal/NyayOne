"""Install the durable NYAY-9 owner-scoped profile mutation ledger.

Revision ID: 0022_nyay9_owner_profile_api
Revises: 0021_nyay5_profile_boundary

The ledger retains no raw idempotency key or plaintext profile projection.
Opaque keys and canonical requests are stored as keyed HMACs; an exact replay
outcome is retained only as version-stamped ciphertext.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection


revision: str = "0022_nyay9_owner_profile_api"
down_revision: str | None = "0021_nyay5_profile_boundary"
branch_labels = None
depends_on = None


_TABLE = "profile_mutation_idempotency_records"
_UUID = sa.Uuid(as_uuid=True)
_PG_ADVISORY_LOCK_KEY = 4353333856519384241

_SECTION = "section IN ('personal', 'academic', 'interests')"
_STATE = "state IN ('pending', 'succeeded', 'erased')"
_KEY_HASH_SHAPE = (
    "length(idempotency_key_hash) = 64 AND "
    "length(replace(replace(replace(replace(replace(replace(replace(replace("
    "replace(replace(replace(replace(replace(replace(replace(replace("
    "idempotency_key_hash, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), "
    "'5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), "
    "'c', ''), 'd', ''), 'e', ''), 'f', '')) = 0"
)
_REQUEST_FINGERPRINT_SHAPE = (
    "((state IN ('pending', 'succeeded') AND "
    "request_fingerprint_version = 'v1' AND "
    "request_fingerprint IS NOT NULL AND "
    "length(request_fingerprint) = 64 AND "
    "length(replace(replace(replace(replace(replace(replace(replace(replace("
    "replace(replace(replace(replace(replace(replace(replace(replace("
    "request_fingerprint, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), "
    "'5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), "
    "'c', ''), 'd', ''), 'e', ''), 'f', '')) = 0) OR "
    "(state = 'erased' AND request_fingerprint IS NULL AND "
    "request_fingerprint_version IS NULL))"
)
_STATE_OUTCOME = (
    "(state = 'pending' AND outcome_status IS NULL AND "
    "outcome_ct IS NULL AND key_version IS NULL AND "
    "profile_version IS NULL) OR "
    "(state = 'succeeded' AND outcome_status = 200 AND "
    "outcome_ct IS NOT NULL AND length(outcome_ct) BETWEEN 1 AND 32768 "
    "AND key_version IS NOT NULL AND length(key_version) BETWEEN 1 AND 8 "
    "AND outcome_ct LIKE key_version || ':%' "
    "AND length(outcome_ct) > length(key_version) + 1 "
    "AND profile_version IS NOT NULL AND profile_version >= 1) OR "
    "(state = 'erased' AND outcome_status IS NULL AND "
    "outcome_ct IS NULL AND key_version IS NULL AND "
    "profile_version IS NULL)"
)

_CHECKS = {
    "ck_profile_mutation_idempotency_records_section": _SECTION,
    "ck_profile_mutation_idempotency_records_state": _STATE,
    "ck_profile_mutation_idempotency_records_key_hash_shape": _KEY_HASH_SHAPE,
    "ck_profile_mutation_idempotency_records_fingerprint_shape": (
        _REQUEST_FINGERPRINT_SHAPE
    ),
    "ck_profile_mutation_idempotency_records_state_outcome": _STATE_OUTCOME,
}


class Nyay9ProfileIdempotencyMigrationError(RuntimeError):
    """Sanitized schema rejection with no actor, key, or profile data."""


class Nyay9ProfileIdempotencyDowngradeError(RuntimeError):
    """Downgrade would discard durable mutation replay authority."""


def _validate_postgres_table_authority(
    connection: Connection, table_names: tuple[str, ...]
) -> None:
    """Reject ambient PostgreSQL authority capable of rewriting ledger DML."""

    if connection.dialect.name != "postgresql":
        return
    names = tuple(dict.fromkeys(table_names))
    catalog = connection.execute(
        sa.text(
            "SELECT c.relname::text, c.relkind::text, c.relpersistence::text, "
            "c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname IN :table_names"
        ).bindparams(sa.bindparam("table_names", expanding=True)),
        {"table_names": names},
    ).all()
    if (
        {row[0] for row in catalog} != set(names)
        or len(catalog) != len(names)
        or any(
            row[1] != "r"
            or row[2] != "p"
            or bool(row[3])
            or bool(row[4])
            for row in catalog
        )
    ):
        raise Nyay9ProfileIdempotencyMigrationError(
            "NYAY-9 profile ledger authority validation rejected"
        )
    drift_queries = (
        "SELECT count(*) FROM pg_catalog.pg_policy AS p "
        "JOIN pg_catalog.pg_class AS c ON c.oid = p.polrelid "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname IN :table_names",
        "SELECT count(*) FROM pg_catalog.pg_rewrite AS r "
        "JOIN pg_catalog.pg_class AS c ON c.oid = r.ev_class "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname IN :table_names "
        "AND r.rulename <> '_RETURN'",
        "SELECT count(*) FROM pg_catalog.pg_trigger AS t "
        "JOIN pg_catalog.pg_class AS c ON c.oid = t.tgrelid "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname IN :table_names "
        "AND NOT t.tgisinternal",
    )
    for query in drift_queries:
        count = connection.scalar(
            sa.text(query).bindparams(
                sa.bindparam("table_names", expanding=True)
            ),
            {"table_names": names},
        )
        if type(count) is not int or count != 0:
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger authority validation rejected"
            )


def _lock(connection: Connection, *, include_ledger: bool = False) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        sa.text("SELECT pg_catalog.pg_advisory_xact_lock(:key)"),
        {"key": _PG_ADVISORY_LOCK_KEY},
    )
    tables = f"users, {_TABLE}" if include_ledger else "users"
    connection.execute(
        sa.text(f"LOCK TABLE {tables} IN ACCESS EXCLUSIVE MODE")
    )


def _validate_parent_schema(connection: Connection) -> None:
    try:
        inspector = sa.inspect(connection)
        tables = set(inspector.get_table_names())
        if _TABLE in tables or not {"users", "student_profiles"} <= tables:
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger migration rejected unsafe schema"
            )
        profile_columns = {
            column["name"] for column in inspector.get_columns("student_profiles")
        }
        if "profile_version" not in profile_columns:
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger migration rejected unsafe schema"
            )
    except Nyay9ProfileIdempotencyMigrationError:
        raise
    except (sa.exc.SQLAlchemyError, KeyError, TypeError, ValueError):
        raise Nyay9ProfileIdempotencyMigrationError(
            "NYAY-9 profile ledger migration rejected unsafe schema"
        ) from None


def _is_uuid(connection: Connection, column_type: object) -> bool:
    rendered = str(column_type).casefold().replace(" ", "")
    if connection.dialect.name == "postgresql":
        return rendered == "uuid"
    return isinstance(column_type, sa.Uuid) or rendered in {"uuid", "char(32)"}


def _normalise_default(value: object) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip().casefold()
    while rendered.startswith("(") and rendered.endswith(")"):
        rendered = rendered[1:-1].strip()
    return rendered.replace("::timestamp with time zone", "")


def _canonical_check(expression: object) -> str:
    return " ".join(str(expression or "").casefold().split())


def _check_constraint(
    inspector: sa.Inspector, name: str, expression: str
) -> None:
    if inspector.bind.dialect.name == "postgresql":
        connection = inspector.bind
        expected_table = "_nyay9_expected_profile_ledger_check"
        expected_name = "_nyay9_expected_check_constraint"
        preparer = connection.dialect.identifier_preparer
        quoted_table = preparer.quote_identifier(_TABLE)
        quoted_expected_table = preparer.quote_identifier(expected_table)
        quoted_expected_name = preparer.quote_identifier(expected_name)
        actual = connection.scalar(
            sa.text(
                "SELECT pg_catalog.pg_get_constraintdef(c.oid, true) "
                "FROM pg_catalog.pg_constraint AS c "
                "JOIN pg_catalog.pg_class AS r ON r.oid = c.conrelid "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = r.relnamespace "
                "WHERE n.nspname = 'public' AND r.relname = :table_name "
                "AND c.conname = :constraint_name AND c.contype = 'c'"
            ),
            {"table_name": _TABLE, "constraint_name": name},
        )
        if not isinstance(actual, str):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        connection.execute(
            sa.text(f"DROP TABLE IF EXISTS pg_temp.{quoted_expected_table}")
        )
        try:
            connection.execute(
                sa.text(
                    f"CREATE TEMP TABLE pg_temp.{quoted_expected_table} "
                    f"(LIKE public.{quoted_table}) ON COMMIT DROP"
                )
            )
            connection.execute(
                sa.text(
                    f"ALTER TABLE pg_temp.{quoted_expected_table} "
                    f"ADD CONSTRAINT {quoted_expected_name} CHECK ({expression})"
                )
            )
            expected = connection.scalar(
                sa.text(
                    "SELECT pg_catalog.pg_get_constraintdef(c.oid, true) "
                    "FROM pg_catalog.pg_constraint AS c "
                    "JOIN pg_catalog.pg_class AS r ON r.oid = c.conrelid "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid = r.relnamespace "
                    "WHERE n.oid = pg_catalog.pg_my_temp_schema() "
                    "AND r.relname = :table_name "
                    "AND c.conname = :constraint_name AND c.contype = 'c'"
                ),
                {
                    "table_name": expected_table,
                    "constraint_name": expected_name,
                },
            )
        finally:
            connection.execute(
                sa.text(f"DROP TABLE IF EXISTS pg_temp.{quoted_expected_table}")
            )
        if not isinstance(expected, str) or _canonical_check(
            actual
        ) != _canonical_check(expected):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        return
    checks = {
        str(item.get("name")): _canonical_check(item.get("sqltext"))
        for item in inspector.get_check_constraints(_TABLE)
    }
    if checks.get(name) != _canonical_check(expression):
        raise Nyay9ProfileIdempotencyMigrationError(
            "NYAY-9 profile ledger schema validation rejected"
        )


def _validate_table_catalog(connection: Connection) -> None:
    try:
        inspector = sa.inspect(connection)
        if _TABLE not in inspector.get_table_names():
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        columns = {column["name"]: column for column in inspector.get_columns(_TABLE)}
        expected_columns = {
            "id",
            "actor_user_id",
            "section",
            "idempotency_key_hash",
            "request_fingerprint",
            "request_fingerprint_version",
            "state",
            "outcome_status",
            "outcome_ct",
            "key_version",
            "profile_version",
            "created_at",
            "updated_at",
        }
        if set(columns) != expected_columns or "idempotency_key" in columns:
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        required = {
            "id",
            "actor_user_id",
            "section",
            "idempotency_key_hash",
            "state",
            "created_at",
            "updated_at",
        }
        if any(bool(columns[name]["nullable"]) for name in required) or any(
            not bool(columns[name]["nullable"])
            for name in expected_columns - required
        ):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        if not _is_uuid(connection, columns["id"]["type"]) or not _is_uuid(
            connection, columns["actor_user_id"]["type"]
        ):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        lengths = {
            "section": 16,
            "idempotency_key_hash": 64,
            "request_fingerprint": 64,
            "request_fingerprint_version": 16,
            "state": 16,
            "key_version": 8,
        }
        if any(
            not isinstance(columns[name]["type"], sa.String)
            or getattr(columns[name]["type"], "length", None) != length
            for name, length in lengths.items()
        ):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        if not isinstance(columns["outcome_ct"]["type"], sa.Text) or any(
            not isinstance(columns[name]["type"], sa.Integer)
            for name in ("outcome_status", "profile_version")
        ):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        timestamp_columns = ("created_at", "updated_at")
        if any(
            not isinstance(columns[name]["type"], sa.DateTime)
            or _normalise_default(columns[name].get("default"))
            not in {"current_timestamp", "now()"}
            for name in timestamp_columns
        ) or (
            connection.dialect.name == "postgresql"
            and any(
                getattr(columns[name]["type"], "timezone", None) is not True
                for name in timestamp_columns
            )
        ):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        if any(
            columns[name].get("default") is not None
            for name in expected_columns - set(timestamp_columns)
        ):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        primary_key = inspector.get_pk_constraint(_TABLE)
        if primary_key.get("name") != f"pk_{_TABLE}" or primary_key.get(
            "constrained_columns"
        ) != ["id"]:
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        unique_constraints = {
            item.get("name"): tuple(item.get("column_names") or ())
            for item in inspector.get_unique_constraints(_TABLE)
        }
        if unique_constraints != {
            "uq_profile_mutation_idempotency_records_scope": (
                "actor_user_id",
                "section",
                "idempotency_key_hash",
            )
        }:
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        explicit_indexes = [
            item
            for item in inspector.get_indexes(_TABLE)
            if not item.get("duplicates_constraint")
        ]
        if explicit_indexes:
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        foreign_keys = inspector.get_foreign_keys(_TABLE)
        if len(foreign_keys) != 1:
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        actor_fk = foreign_keys[0]
        if (
            actor_fk.get("name") != "fk_profile_mutation_idempotency_actor"
            or actor_fk.get("constrained_columns") != ["actor_user_id"]
            or actor_fk.get("referred_table") != "users"
            or actor_fk.get("referred_columns") != ["id"]
            or str((actor_fk.get("options") or {}).get("ondelete", "")).upper()
            != "CASCADE"
        ):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        check_names = {
            item.get("name") for item in inspector.get_check_constraints(_TABLE)
        }
        if check_names != set(_CHECKS):
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger schema validation rejected"
            )
        for name, expression in _CHECKS.items():
            _check_constraint(inspector, name, expression)
    except Nyay9ProfileIdempotencyMigrationError:
        raise
    except (sa.exc.SQLAlchemyError, KeyError, TypeError, ValueError):
        raise Nyay9ProfileIdempotencyMigrationError(
            "NYAY-9 profile ledger schema validation rejected"
        ) from None


def _validate_postflight(connection: Connection, *, head: bool) -> None:
    """Validate the exact ledger catalog and DML authority before commit."""

    _validate_table_catalog(connection)
    _validate_postgres_table_authority(connection, (_TABLE,))
    if head:
        revision_value = connection.scalar(
            sa.text("SELECT version_num FROM alembic_version")
        )
        if revision_value != revision:
            raise Nyay9ProfileIdempotencyMigrationError(
                "NYAY-9 profile ledger head validation rejected"
            )


def upgrade() -> None:
    connection = op.get_bind()
    _lock(connection)
    _validate_parent_schema(connection)
    op.create_table(
        _TABLE,
        sa.Column("id", _UUID, nullable=False),
        sa.Column("actor_user_id", _UUID, nullable=False),
        sa.Column("section", sa.String(16), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=True),
        sa.Column("request_fingerprint_version", sa.String(16), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("outcome_status", sa.Integer(), nullable=True),
        sa.Column("outcome_ct", sa.Text(), nullable=True),
        sa.Column("key_version", sa.String(8), nullable=True),
        sa.Column("profile_version", sa.Integer(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_profile_mutation_idempotency_actor",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "actor_user_id",
            "section",
            "idempotency_key_hash",
            name="uq_profile_mutation_idempotency_records_scope",
        ),
        *(
            sa.CheckConstraint(expression, name=op.f(name))
            for name, expression in _CHECKS.items()
        ),
    )
    _validate_postflight(connection, head=False)


def downgrade() -> None:
    connection = op.get_bind()
    _lock(connection, include_ledger=True)
    _validate_postflight(connection, head=False)
    rows = connection.scalar(sa.text(f"SELECT count(*) FROM {_TABLE}"))
    if type(rows) is not int or rows != 0:
        raise Nyay9ProfileIdempotencyDowngradeError(
            "NYAY-9 profile ledger downgrade rejected durable replay data"
        )
    op.drop_table(_TABLE)
    _validate_parent_schema(connection)
