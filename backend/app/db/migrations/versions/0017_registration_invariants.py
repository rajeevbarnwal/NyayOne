"""Fail-closed registration cardinality and concurrency invariants.

Revision ID: 0017_registration_invariants
Revises: 0016_dob_hash_reconcile

All populated-data checks run while holding the PostgreSQL migration lock and
table write locks, before the first target DDL statement.  Conflicting rows are
never repaired, deleted, or selected as winners by this migration.
"""
from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

revision: str = "0017_registration_invariants"
down_revision: str | None = "0016_dob_hash_reconcile"
branch_labels = None
depends_on = None

_OTP_INDEX = "uq_otp_challenges_one_active_per_registration_purpose"
_SESSION_INDEX = "uq_auth_sessions_one_active_per_user"
_GUARDIAN_UNIQUE = "uq_guardian_consents_registration_id"
_VERIFICATION_UNIQUE = "uq_student_verifications_registration_id"
_GUARDIAN_CHECK = "ck_guardian_consents_verified_matches_status"
_TARGET_OBJECTS = frozenset(
    {
        _OTP_INDEX,
        _SESSION_INDEX,
        _GUARDIAN_UNIQUE,
        _VERIFICATION_UNIQUE,
        _GUARDIAN_CHECK,
    }
)
_GUARDIAN_STATE_SQL = (
    "(status = 'verified' AND verified = true) OR "
    "(status IN ('pending', 'sent', 'rejected') AND verified = false)"
)
_PG_ADVISORY_LOCK_KEY = 4353333856519384233

_REQUIRED_COLUMNS: dict[str, dict[str, bool]] = {
    "auth_sessions": {"user_id": False, "status": False},
    "guardian_consents": {
        "registration_id": False,
        "status": False,
        "verified": False,
    },
    "otp_challenges": {
        "registration_id": False,
        "purpose": False,
        "consumed_at": True,
    },
    "student_verifications": {"registration_id": False},
}

_CONFLICT_QUERIES = (
    """
    SELECT 1 FROM otp_challenges
    WHERE consumed_at IS NULL
    GROUP BY registration_id, purpose HAVING count(*) > 1
    LIMIT 1
    """,
    """
    SELECT 1 FROM auth_sessions
    WHERE status = 'active'
    GROUP BY user_id HAVING count(*) > 1
    LIMIT 1
    """,
    """
    SELECT 1 FROM guardian_consents
    GROUP BY registration_id HAVING count(*) > 1
    LIMIT 1
    """,
    """
    SELECT 1 FROM student_verifications
    GROUP BY registration_id HAVING count(*) > 1
    LIMIT 1
    """,
    """
    SELECT 1 FROM guardian_consents
    WHERE NOT (
        (status = 'verified' AND verified = true)
        OR (status IN ('pending', 'sent', 'rejected') AND verified = false)
    )
    LIMIT 1
    """,
)


class RegistrationInvariantPreflightError(RuntimeError):
    """A deliberately non-identifying migration rejection."""


def _reject() -> RegistrationInvariantPreflightError:
    return RegistrationInvariantPreflightError(
        "NYAY-3 registration invariant preflight rejected ambiguous schema or data"
    )


def _acquire_locks(bind: Connection) -> None:
    dialect = bind.dialect.name
    if dialect == "postgresql":
        try:
            bind.execute(sa.text("SET LOCAL lock_timeout = '5000ms'"))
            bind.execute(sa.text("SET LOCAL statement_timeout = '30000ms'"))
            bind.execute(
                sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _PG_ADVISORY_LOCK_KEY},
            )
            bind.execute(
                sa.text(
                    "LOCK TABLE auth_sessions, guardian_consents, "
                    "otp_challenges, student_verifications "
                    "IN SHARE ROW EXCLUSIVE MODE"
                )
            )
        except SQLAlchemyError:
            raise _reject() from None
    elif dialect != "sqlite":
        raise _reject()


def _all_object_names(inspector: sa.Inspector) -> set[str]:
    names: set[str] = set()
    for table in _REQUIRED_COLUMNS:
        names.update(
            str(item["name"])
            for item in inspector.get_indexes(table)
            if item.get("name")
        )
        names.update(
            str(item["name"])
            for item in inspector.get_unique_constraints(table)
            if item.get("name")
        )
        names.update(
            str(item["name"])
            for item in inspector.get_check_constraints(table)
            if item.get("name")
        )
    return names


def _validate_parent_schema(bind: Connection) -> None:
    try:
        inspector = sa.inspect(bind)
        if not set(_REQUIRED_COLUMNS).issubset(inspector.get_table_names()):
            raise _reject()
        for table, expected in _REQUIRED_COLUMNS.items():
            actual = {
                column["name"]: bool(column["nullable"])
                for column in inspector.get_columns(table)
            }
            if any(
                actual.get(name) is not nullable
                for name, nullable in expected.items()
            ):
                raise _reject()
        if _TARGET_OBJECTS & _all_object_names(inspector):
            raise _reject()
    except RegistrationInvariantPreflightError:
        raise
    except SQLAlchemyError:
        raise _reject() from None


def preflight_registration_invariants(bind: Connection) -> None:
    """Reject every dirty or structurally ambiguous 0016 database before DDL."""

    _acquire_locks(bind)
    _validate_parent_schema(bind)
    try:
        conflicts = [
            bind.scalar(sa.text(statement)) is not None
            for statement in _CONFLICT_QUERIES
        ]
    except SQLAlchemyError:
        raise _reject() from None
    if any(conflicts):
        raise _reject()


def _protect_sql_literals(value: object) -> tuple[str, dict[str, str]]:
    """Replace SQL string literals while preserving every literal byte."""

    source = "" if value is None else str(value)
    output: list[str] = []
    literals: dict[str, str] = {}
    index = 0
    while index < len(source):
        if source[index] != "'":
            output.append(source[index])
            index += 1
            continue
        start = index
        index += 1
        while index < len(source):
            if source[index] != "'":
                index += 1
                continue
            index += 1
            if index < len(source) and source[index] == "'":
                index += 1
                continue
            break
        token = f"\x00literal{len(literals)}\x00"
        literals[token] = source[start:index]
        output.append(token)
    return "".join(output), literals


def _normalise_sql(value: object) -> str:
    text, literals = _protect_sql_literals(value)
    text = text.lower()
    text = re.sub(
        r"::(?:text|character varying|varchar)(?:\([0-9]+\))?",
        "",
        text,
    )
    text = re.sub(r"[\s()\"\[\]]+", "", text)
    # PostgreSQL reflects ``IN (...)`` as ``= ANY (ARRAY[...]::text[])``.
    # Canonicalize only that representation outside protected literals.
    text = text.replace("=anyarray", "in")
    for token, literal in literals.items():
        text = text.replace(token, literal)
    return text


def _normalise_check_sql(value: object) -> str:
    normalized = _normalise_sql(value)
    return normalized[5:] if normalized.startswith("check") else normalized


def _index_predicate(index: dict[str, object], dialect: str) -> str:
    options = index.get("dialect_options") or {}
    key = "postgresql_where" if dialect == "postgresql" else "sqlite_where"
    return _normalise_sql(options.get(key))


def _validate_index(
    inspector: sa.Inspector,
    *,
    table: str,
    name: str,
    columns: list[str],
    predicate: str,
    dialect: str,
) -> None:
    matches = [
        item for item in inspector.get_indexes(table) if item.get("name") == name
    ]
    if len(matches) != 1:
        raise _reject()
    item = matches[0]
    if not bool(item.get("unique")) or item.get("column_names") != columns:
        raise _reject()
    if _index_predicate(item, dialect) != _normalise_sql(predicate):
        raise _reject()


def _validate_unique(
    inspector: sa.Inspector, *, table: str, name: str, columns: list[str]
) -> None:
    matches = [
        item
        for item in inspector.get_unique_constraints(table)
        if item.get("name") == name
    ]
    if len(matches) != 1 or matches[0].get("column_names") != columns:
        raise _reject()


def _validate_head_schema(bind: Connection) -> None:
    try:
        inspector = sa.inspect(bind)
        dialect = bind.dialect.name
        _validate_index(
            inspector,
            table="otp_challenges",
            name=_OTP_INDEX,
            columns=["registration_id", "purpose"],
            predicate="consumed_at IS NULL",
            dialect=dialect,
        )
        _validate_index(
            inspector,
            table="auth_sessions",
            name=_SESSION_INDEX,
            columns=["user_id"],
            predicate="status = 'active'",
            dialect=dialect,
        )
        _validate_unique(
            inspector,
            table="guardian_consents",
            name=_GUARDIAN_UNIQUE,
            columns=["registration_id"],
        )
        _validate_unique(
            inspector,
            table="student_verifications",
            name=_VERIFICATION_UNIQUE,
            columns=["registration_id"],
        )
        checks = [
            item
            for item in inspector.get_check_constraints("guardian_consents")
            if item.get("name") == _GUARDIAN_CHECK
        ]
        if len(checks) != 1:
            raise _reject()
        actual = _normalise_check_sql(checks[0].get("sqltext"))
        if actual != _normalise_check_sql(_GUARDIAN_STATE_SQL):
            raise _reject()
    except RegistrationInvariantPreflightError:
        raise
    except SQLAlchemyError:
        raise _reject() from None


def upgrade() -> None:
    bind = op.get_bind()
    preflight_registration_invariants(bind)

    op.create_index(
        _OTP_INDEX,
        "otp_challenges",
        ["registration_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL"),
        sqlite_where=sa.text("consumed_at IS NULL"),
    )
    op.create_index(
        _SESSION_INDEX,
        "auth_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )
    with op.batch_alter_table("guardian_consents") as batch:
        batch.create_unique_constraint(_GUARDIAN_UNIQUE, ["registration_id"])
        # The metadata convention renders this bare token to the exact physical
        # name in _GUARDIAN_CHECK without double-prefixing ``ck_<table>``.
        batch.create_check_constraint("verified_matches_status", _GUARDIAN_STATE_SQL)
    with op.batch_alter_table("student_verifications") as batch:
        batch.create_unique_constraint(_VERIFICATION_UNIQUE, ["registration_id"])


def downgrade() -> None:
    bind = op.get_bind()
    _acquire_locks(bind)
    _validate_head_schema(bind)

    with op.batch_alter_table("student_verifications") as batch:
        batch.drop_constraint(_VERIFICATION_UNIQUE, type_="unique")
    with op.batch_alter_table("guardian_consents") as batch:
        batch.drop_constraint(op.f(_GUARDIAN_CHECK), type_="check")
        batch.drop_constraint(_GUARDIAN_UNIQUE, type_="unique")
    op.drop_index(_SESSION_INDEX, table_name="auth_sessions")
    op.drop_index(_OTP_INDEX, table_name="otp_challenges")
