"""Install explicit erased login/session retention lifecycle.

Revision ID: 0020_auth_retention_lifecycle
Revises: 0019_otp_security_authority

This forward migration preserves 0001..0019 byte-for-byte.  It adds the
database state needed to retain non-linkable tombstones without retaining a
mobile lookup, bearer hash, user FK, metadata, or activity timestamps.
"""
from __future__ import annotations

import re
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import SQLAlchemyError

revision: str = "0020_auth_retention_lifecycle"
down_revision: str | None = "0019_otp_security_authority"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)
_PG_ADVISORY_LOCK_KEY = 4353333856519384236


class AuthRetentionMigrationError(RuntimeError):
    """Sanitized fail-closed upgrade rejection."""


class AuthRetentionDowngradeError(RuntimeError):
    """Raised when downgrade would discard an erased tombstone lifecycle."""


def _reject() -> AuthRetentionMigrationError:
    return AuthRetentionMigrationError(
        "NYAY-19 auth retention migration rejected unsafe schema or data"
    )


def _downgrade_reject() -> AuthRetentionDowngradeError:
    return AuthRetentionDowngradeError(
        "NYAY-19 downgrade rejected unsafe schema or erased auth state"
    )


def _hex_residue_is_empty(column: str) -> str:
    expression = column
    for character in "0123456789abcdef":
        expression = f"replace({expression}, '{character}', '')"
    return f"length({expression}) = 0"


def _protect_sql_literals(value: object) -> tuple[str, dict[str, str]]:
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
    source, literals = _protect_sql_literals(value)
    source = source.lower()
    source = re.sub(
        r"::(?:text|character varying|varchar)(?:\([0-9]+\))?",
        "",
        source,
    )
    source = re.sub(r"[\s()\"\[\]]+", "", source)
    # PostgreSQL reflects ``IN (...)`` as ``= ANY (ARRAY[...]::text[])``.
    # Canonicalize only the structural spelling outside protected literals.
    source = source.replace("=anyarray", "in")
    for token, literal in literals.items():
        source = source.replace(token, literal)
    return source


_CHECK_TOKEN = re.compile(
    r"__literal[0-9]+__|[a-z_][a-z0-9_]*|[0-9]+|<=|>=|<>|!=|=|\(|\)|,|\[|\]"
)


class _CheckParser:
    """Parse the deliberately small CHECK grammar without losing grouping."""

    def __init__(self, tokens: list[str], literals: dict[str, str]) -> None:
        self.tokens = tokens
        self.literals = literals
        self.index = 0

    def _peek(self) -> str | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def _take(self, expected: str | None = None) -> str:
        token = self._peek()
        if token is None or (expected is not None and token != expected):
            raise ValueError("invalid CHECK expression")
        self.index += 1
        return token

    @staticmethod
    def _combine(operator: str, left: object, right: object) -> tuple[object, ...]:
        children: list[object] = []
        for value in (left, right):
            if isinstance(value, tuple) and value and value[0] == operator:
                children.extend(value[1:])
            else:
                children.append(value)
        return (operator, *children)

    def parse(self) -> object:
        if self._peek() == "check":
            self._take("check")
        result = self._or()
        if self._peek() is not None:
            raise ValueError("unexpected CHECK token")
        return result

    def _or(self) -> object:
        result = self._and()
        while self._peek() == "or":
            self._take("or")
            result = self._combine("or", result, self._and())
        return result

    def _and(self) -> object:
        result = self._factor()
        while self._peek() == "and":
            self._take("and")
            result = self._combine("and", result, self._factor())
        return result

    def _factor(self) -> object:
        if self._peek() == "(":
            self._take("(")
            result = self._or()
            self._take(")")
        else:
            result = self._value()
        return self._suffix(result)

    def _value(self) -> object:
        token = self._take()
        if token.startswith("__literal"):
            return ("literal", self.literals[token])
        if token.isdigit():
            return ("number", token)
        if re.fullmatch(r"[a-z_][a-z0-9_]*", token) is None:
            raise ValueError("invalid CHECK value")
        if self._peek() != "(":
            return ("identifier", token)
        self._take("(")
        arguments: list[object] = []
        if self._peek() != ")":
            while True:
                arguments.append(self._or())
                if self._peek() != ",":
                    break
                self._take(",")
        self._take(")")
        return ("function", token, tuple(arguments))

    def _list(self) -> tuple[object, ...]:
        self._take("(")
        values: list[object] = []
        if self._peek() != ")":
            while True:
                values.append(self._or())
                if self._peek() != ",":
                    break
                self._take(",")
        self._take(")")
        return tuple(values)

    def _suffix(self, left: object) -> object:
        token = self._peek()
        if token == "is":
            self._take("is")
            negate = self._peek() == "not"
            if negate:
                self._take("not")
            self._take("null")
            return ("is_not_null" if negate else "is_null", left)
        if token == "in":
            self._take("in")
            return ("in", left, self._list())
        if token in {"=", "!=", "<>", "<=", ">="}:
            operator = self._take()
            right = self._factor()
            if (
                operator == "="
                and isinstance(right, tuple)
                and len(right) == 3
                and right[:2] == ("function", "any")
            ):
                argument = right[2]
                if (
                    isinstance(argument, tuple)
                    and len(argument) == 1
                    and isinstance(argument[0], tuple)
                    and argument[0][:2] == ("function", "array")
                ):
                    return ("in", left, argument[0][2])
            return (operator, left, right)
        return left


def _canonical_check(value: object) -> object:
    protected, literals_by_token = _protect_sql_literals(value)
    source = protected.casefold().replace('"', "")
    source = re.sub(
        r"::(?:text|character varying|varchar)(?:\([0-9]+\))?(?:\[\])?",
        "",
        source,
    )
    source = source.replace("[", "(").replace("]", ")")
    literals: dict[str, str] = {}
    for index, (placeholder, literal) in enumerate(literals_by_token.items()):
        token = f"__literal{index}__"
        source = source.replace(placeholder, token)
        literals[token] = literal
    tokens = _CHECK_TOKEN.findall(source)
    if "".join(tokens) != re.sub(r"\s+", "", source):
        raise ValueError("unsupported CHECK syntax")
    return _CheckParser(tokens, literals).parse()


def _column_type_matches(
    column: dict[str, object],
    expected: str,
    *,
    dialect: str,
    length: int | None = None,
) -> bool:
    value = column.get("type")
    if expected == "uuid":
        return (
            isinstance(value, sa.Uuid)
            if dialect == "postgresql"
            else isinstance(value, sa.CHAR) and value.length == 32
        )
    if expected == "string":
        return isinstance(value, sa.String) and value.length == length
    if expected == "datetime":
        return isinstance(value, sa.DateTime) and (
            dialect != "postgresql" or bool(value.timezone)
        )
    if expected == "json":
        return isinstance(value, sa.JSON)
    return False


def _default_matches(value: object, expected: str | None) -> bool:
    if expected is None:
        return value is None
    normalized = _normalise_sql(value)
    if expected in {"pending", "active"}:
        return normalized == f"'{expected}'"
    if expected == "now":
        return normalized in {"current_timestamp", "now"}
    return False


def _validate_columns(
    inspector: sa.Inspector,
    *,
    table: str,
    expected: tuple[tuple[str, str, int | None, bool, str | None], ...],
    dialect: str,
) -> None:
    columns = inspector.get_columns(table)
    if [item.get("name") for item in columns] != [item[0] for item in expected]:
        raise ValueError("column inventory mismatch")
    for column, (name, kind, length, nullable, default) in zip(
        columns, expected, strict=True
    ):
        if (
            column.get("name") != name
            or bool(column.get("nullable")) is not nullable
            or not _column_type_matches(
                column, kind, dialect=dialect, length=length
            )
            or not _default_matches(column.get("default"), default)
            or column.get("computed") is not None
            or column.get("identity") is not None
            or column.get("comment") is not None
            or getattr(column.get("type"), "collation", None) is not None
        ):
            raise ValueError("column definition mismatch")


def _validate_fk_inventory(
    inspector: sa.Inspector,
    *,
    table: str,
    expected: dict[str, tuple[list[str], str, list[str], str]],
) -> None:
    reflected = inspector.get_foreign_keys(table)
    foreign_keys = {item.get("name"): item for item in reflected}
    if (
        len(reflected) != len(foreign_keys)
        or len(foreign_keys) != len(expected)
        or set(foreign_keys) != set(expected)
    ):
        raise ValueError("foreign key inventory mismatch")
    for name, (columns, referred_table, referred_columns, ondelete) in expected.items():
        item = foreign_keys[name]
        options = item.get("options") or {}
        normalized_options = {
            str(key): value.upper() if isinstance(value, str) else value
            for key, value in options.items()
            if value is not None
        }
        if (
            item.get("constrained_columns") != columns
            or item.get("referred_schema")
            not in {None, inspector.default_schema_name}
            or item.get("referred_table") != referred_table
            or item.get("referred_columns") != referred_columns
            or normalized_options != {"ondelete": ondelete}
        ):
            raise ValueError("foreign key definition mismatch")


def _check_inventory(
    inspector: sa.Inspector,
    *,
    table: str,
    dialect: str,
) -> dict[str, object]:
    if dialect != "postgresql":
        rows = inspector.get_check_constraints(table)
        result = {
            str(row.get("name")): _canonical_check(row.get("sqltext"))
            for row in rows
        }
        if len(rows) != len(result):
            raise ValueError("duplicate check name")
        return result
    rows = inspector.bind.execute(
        sa.text(
            "SELECT constraint_row.conname, "
            "pg_get_expr(constraint_row.conbin, constraint_row.conrelid, false) "
            "AS expression, constraint_row.convalidated, constraint_row.connoinherit "
            "FROM pg_catalog.pg_constraint AS constraint_row "
            "JOIN pg_catalog.pg_class AS table_row "
            "ON table_row.oid = constraint_row.conrelid "
            "JOIN pg_catalog.pg_namespace AS namespace_row "
            "ON namespace_row.oid = table_row.relnamespace "
            "WHERE namespace_row.nspname = current_schema() "
            "AND table_row.relname = :table_name "
            "AND constraint_row.contype = 'c'"
        ),
        {"table_name": table},
    ).mappings().all()
    if any(
        not bool(row["convalidated"]) or bool(row["connoinherit"])
        for row in rows
    ):
        raise ValueError("unsafe check state")
    result = {
        str(row["conname"]): _canonical_check(row["expression"])
        for row in rows
    }
    if len(result) != len(rows):
        raise ValueError("duplicate check name")
    return result


def _validate_exact_auth_schema(
    inspector: sa.Inspector,
    *,
    dialect: str,
    head: bool,
) -> None:
    _validate_columns(
        inspector,
        table="login_attempts",
        dialect=dialect,
        expected=(
            ("id", "uuid", None, False, None),
            ("opaque_id", "string", 64, False, None),
            ("lookup_hash", "string", 64, False, None),
            ("registration_id", "uuid", None, True, None),
            ("challenge_id", "uuid", None, True, None),
            ("status", "string", 24, False, "pending"),
            ("expires_at", "datetime", None, False, None),
            ("consumed_at", "datetime", None, True, None),
            ("created_at", "datetime", None, False, "now"),
            ("updated_at", "datetime", None, False, "now"),
            ("deleted_at", "datetime", None, True, None),
            ("metadata_json", "json", None, True, None),
        ),
    )
    _validate_columns(
        inspector,
        table="auth_sessions",
        dialect=dialect,
        expected=(
            ("id", "uuid", None, False, None),
            ("user_id", "uuid", None, head, None),
            ("token_hash", "string", 64, False, None),
            ("status", "string", 24, False, "active"),
            ("expires_at", "datetime", None, False, None),
            ("last_seen_at", "datetime", None, False, None),
            ("revoked_at", "datetime", None, True, None),
            ("created_at", "datetime", None, False, "now"),
            ("updated_at", "datetime", None, False, "now"),
            ("deleted_at", "datetime", None, True, None),
            ("metadata_json", "json", None, True, None),
        ),
    )
    login_pk = inspector.get_pk_constraint("login_attempts")
    session_pk = inspector.get_pk_constraint("auth_sessions")
    if (
        login_pk.get("name") != "pk_login_attempts"
        or login_pk.get("constrained_columns") != ["id"]
        or session_pk.get("name") != "pk_auth_sessions"
        or session_pk.get("constrained_columns") != ["id"]
    ):
        raise ValueError("primary key inventory mismatch")
    _validate_fk_inventory(
        inspector,
        table="login_attempts",
        expected={
            "fk_login_attempts_registration_id_student_registrations": (
                ["registration_id"], "student_registrations", ["id"], "CASCADE"
            ),
            "fk_login_attempts_challenge_id_otp_challenges": (
                ["challenge_id"], "otp_challenges", ["id"], "SET NULL"
            ),
        },
    )
    _validate_fk_inventory(
        inspector,
        table="auth_sessions",
        expected={
            "fk_auth_sessions_user_id_users": (
                ["user_id"], "users", ["id"], "CASCADE"
            )
        },
    )
    expected_checks = (
        {
            "ck_login_attempts_status": _LOGIN_STATUS,
            "ck_login_attempts_lookup_hash_shape": _LOGIN_LOOKUP_SHAPE,
            "ck_login_attempts_opaque_id_shape": _LOGIN_OPAQUE_SHAPE,
            "ck_login_attempts_lifecycle_shape": _LOGIN_LIFECYCLE,
        }
        if head
        else {
            "ck_login_attempts_ck_login_attempts_status": (
                "status IN ('pending', 'consumed', 'expired')"
            )
        }
    )
    actual_checks = _check_inventory(
        inspector, table="login_attempts", dialect=dialect
    )
    if actual_checks != {
        name: _canonical_check(sql) for name, sql in expected_checks.items()
    }:
        raise ValueError("login check inventory mismatch")
    expected_checks = (
        {
            "ck_auth_sessions_status": _SESSION_STATUS,
            "ck_auth_sessions_token_hash_shape": _SESSION_TOKEN_SHAPE,
            "ck_auth_sessions_lifecycle_shape": _SESSION_LIFECYCLE,
        }
        if head
        else {
            "ck_auth_sessions_ck_auth_sessions_status": (
                "status IN ('active', 'revoked', 'expired')"
            )
        }
    )
    actual_checks = _check_inventory(
        inspector, table="auth_sessions", dialect=dialect
    )
    if actual_checks != {
        name: _canonical_check(sql) for name, sql in expected_checks.items()
    }:
        raise ValueError("session check inventory mismatch")


def _index_where(index: dict[str, object], *, dialect: str) -> object:
    options = index.get("dialect_options") or {}
    return options.get(
        "postgresql_where" if dialect == "postgresql" else "sqlite_where"
    )


def _index_options_are_safe(
    index: dict[str, object],
    *,
    dialect: str,
    predicate: str | None,
) -> bool:
    if index.get("column_sorting") not in (None, {}) or index.get(
        "include_columns"
    ) not in (None, [], ()):
        return False
    expressions = index.get("expressions")
    if expressions is not None and expressions != index.get("column_names"):
        return False
    options = index.get("dialect_options") or {}
    where_key = "postgresql_where" if dialect == "postgresql" else "sqlite_where"
    for key, value in options.items():
        if key == where_key:
            if _normalise_sql(value) != _normalise_sql(predicate):
                return False
        elif value not in (None, False, "", (), [], {}):
            return False
    return _normalise_sql(_index_where(index, dialect=dialect)) == _normalise_sql(
        predicate
    )


def _validate_exact_auth_indexes(
    inspector: sa.Inspector,
    *,
    dialect: str,
    head: bool,
) -> None:
    login_expected = {
        "ix_login_attempts_lookup_hash": (["lookup_hash"], False, None),
        "ix_login_attempts_registration_id": (["registration_id"], False, None),
        "ix_login_attempts_challenge_id": (["challenge_id"], False, None),
    }
    session_expected = {
        "ix_auth_sessions_user_id": (["user_id"], False, None),
        "ix_auth_sessions_token_hash": (["token_hash"], False, None),
        "ix_auth_sessions_expires_at": (["expires_at"], False, None),
        "uq_auth_sessions_one_active_per_user": (
            ["user_id"],
            True,
            "status = 'active'",
        ),
    }
    if head:
        login_expected.update(
            {
                "ix_login_attempts_expires_at": (["expires_at"], False, None),
                "ix_login_attempts_consumed_at": (["consumed_at"], False, None),
            }
        )
        session_expected["ix_auth_sessions_revoked_at"] = (
            ["revoked_at"],
            False,
            None,
        )

    for table, expected in (
        ("login_attempts", login_expected),
        ("auth_sessions", session_expected),
    ):
        reflected = inspector.get_indexes(table)
        duplicate_expected = (
            {"uq_login_attempts_opaque_id": ["opaque_id"]}
            if table == "login_attempts"
            else {"uq_auth_sessions_token_hash": ["token_hash"]}
        )
        duplicate_rows = {
            row.get("name"): row
            for row in reflected
            if row.get("duplicates_constraint") is not None
        }
        if dialect == "postgresql":
            if set(duplicate_rows) != set(duplicate_expected):
                raise ValueError("constraint index inventory mismatch")
            for name, columns in duplicate_expected.items():
                row = duplicate_rows[name]
                if (
                    row.get("duplicates_constraint") != name
                    or row.get("column_names") != columns
                    or not bool(row.get("unique"))
                    or not _index_options_are_safe(
                        row, dialect=dialect, predicate=None
                    )
                ):
                    raise ValueError("constraint index definition mismatch")
        elif duplicate_rows:
            raise ValueError("unexpected constraint index reflection")
        actual = {
            row.get("name"): row
            for row in reflected
            if row.get("duplicates_constraint") is None
        }
        if set(actual) != set(expected):
            raise ValueError("index inventory mismatch")
        for name, (columns, unique, predicate) in expected.items():
            row = actual[name]
            if (
                row.get("column_names") != columns
                or bool(row.get("unique")) is not unique
                or not _index_options_are_safe(
                    row, dialect=dialect, predicate=predicate
                )
            ):
                raise ValueError("index definition mismatch")

    login_unique_rows = inspector.get_unique_constraints("login_attempts")
    session_unique_rows = inspector.get_unique_constraints("auth_sessions")
    login_uniques = {
        row.get("name"): row.get("column_names")
        for row in login_unique_rows
    }
    session_uniques = {
        row.get("name"): row.get("column_names")
        for row in session_unique_rows
    }
    if (
        len(login_unique_rows) != len(login_uniques)
        or len(session_unique_rows) != len(session_uniques)
        or login_uniques != {"uq_login_attempts_opaque_id": ["opaque_id"]}
        or session_uniques != {"uq_auth_sessions_token_hash": ["token_hash"]}
    ):
        raise ValueError("unique constraint inventory mismatch")


def _validate_postgresql_catalog_authority(
    bind: sa.Connection,
    *,
    head: bool,
) -> None:
    """Pin PG-only constraint/index safety state omitted by Inspector."""

    constraint_rows = bind.execute(
        sa.text(
            "SELECT table_row.relname AS table_name, constraint_row.conname, "
            "constraint_row.contype, constraint_row.convalidated, "
            "constraint_row.condeferrable, constraint_row.condeferred, "
            "constraint_row.connoinherit, constraint_row.confupdtype, "
            "constraint_row.confdeltype, constraint_row.confmatchtype, "
            "index_row.relname AS backing_index "
            "FROM pg_catalog.pg_constraint AS constraint_row "
            "JOIN pg_catalog.pg_class AS table_row "
            "ON table_row.oid = constraint_row.conrelid "
            "JOIN pg_catalog.pg_namespace AS namespace_row "
            "ON namespace_row.oid = table_row.relnamespace "
            "LEFT JOIN pg_catalog.pg_class AS index_row "
            "ON index_row.oid = constraint_row.conindid "
            "WHERE namespace_row.nspname = current_schema() "
            "AND table_row.relname IN ('login_attempts','auth_sessions') "
            "AND constraint_row.contype IN ('p','u','f')"
        )
    ).mappings().all()
    expected_constraints = {
        ("login_attempts", "pk_login_attempts"): ("p", "pk_login_attempts", None),
        ("login_attempts", "uq_login_attempts_opaque_id"): (
            "u",
            "uq_login_attempts_opaque_id",
            None,
        ),
        (
            "login_attempts",
            "fk_login_attempts_registration_id_student_registrations",
        ): ("f", "pk_student_registrations", "c"),
        (
            "login_attempts",
            "fk_login_attempts_challenge_id_otp_challenges",
        ): ("f", "pk_otp_challenges", "n"),
        ("auth_sessions", "pk_auth_sessions"): ("p", "pk_auth_sessions", None),
        ("auth_sessions", "uq_auth_sessions_token_hash"): (
            "u",
            "uq_auth_sessions_token_hash",
            None,
        ),
        ("auth_sessions", "fk_auth_sessions_user_id_users"): (
            "f",
            "pk_users",
            "c",
        ),
    }
    actual_constraints = {
        (str(row["table_name"]), str(row["conname"])): row
        for row in constraint_rows
    }
    if (
        len(actual_constraints) != len(constraint_rows)
        or set(actual_constraints) != set(expected_constraints)
    ):
        raise ValueError("PostgreSQL constraint catalog inventory mismatch")
    for key, (kind, backing_index, delete_action) in expected_constraints.items():
        row = actual_constraints[key]
        if (
            row["contype"] != kind
            or not bool(row["convalidated"])
            or bool(row["condeferrable"])
            or bool(row["condeferred"])
            # PostgreSQL marks top-level PK/UQ/FK constraints on these
            # ordinary tables non-inheritable. CHECK constraints are audited
            # separately and retain the opposite flag.
            or not bool(row["connoinherit"])
            or row["backing_index"] != backing_index
        ):
            raise ValueError("unsafe PostgreSQL constraint state")
        if kind == "f" and (
            row["confupdtype"] != "a"
            or row["confdeltype"] != delete_action
            or row["confmatchtype"] != "s"
        ):
            raise ValueError("unsafe PostgreSQL foreign key action")

    index_rows = bind.execute(
        sa.text(
            "SELECT table_row.relname AS table_name, index_row.relname AS index_name, "
            "index_state.indisunique, index_state.indisprimary, "
            "index_state.indisexclusion, index_state.indisvalid, "
            "index_state.indisready, index_state.indislive, "
            "index_state.indnullsnotdistinct, "
            "index_state.indnkeyatts, index_state.indnatts, "
            "index_state.indexprs IS NULL AS has_no_expressions, "
            "access_method.amname AS access_method, "
            "ARRAY(SELECT pg_get_indexdef(index_state.indexrelid, position, true) "
            "FROM generate_series(1, index_state.indnkeyatts) AS position "
            "ORDER BY position) AS key_columns, "
            "ARRAY(SELECT pg_get_indexdef(index_state.indexrelid, position, true) "
            "FROM generate_series(index_state.indnkeyatts + 1, "
            "index_state.indnatts) AS position ORDER BY position) AS include_columns, "
            "pg_get_expr(index_state.indpred, index_state.indrelid, false) "
            "AS predicate "
            "FROM pg_catalog.pg_index AS index_state "
            "JOIN pg_catalog.pg_class AS table_row "
            "ON table_row.oid = index_state.indrelid "
            "JOIN pg_catalog.pg_namespace AS namespace_row "
            "ON namespace_row.oid = table_row.relnamespace "
            "JOIN pg_catalog.pg_class AS index_row "
            "ON index_row.oid = index_state.indexrelid "
            "JOIN pg_catalog.pg_am AS access_method "
            "ON access_method.oid = index_row.relam "
            "WHERE namespace_row.nspname = current_schema() "
            "AND table_row.relname IN ('login_attempts','auth_sessions')"
        )
    ).mappings().all()
    expected_indexes: dict[
        tuple[str, str], tuple[list[str], bool, bool, str | None]
    ] = {
        ("login_attempts", "pk_login_attempts"): (["id"], True, True, None),
        ("login_attempts", "uq_login_attempts_opaque_id"): (
            ["opaque_id"],
            True,
            False,
            None,
        ),
        ("login_attempts", "ix_login_attempts_lookup_hash"): (
            ["lookup_hash"],
            False,
            False,
            None,
        ),
        ("login_attempts", "ix_login_attempts_registration_id"): (
            ["registration_id"],
            False,
            False,
            None,
        ),
        ("login_attempts", "ix_login_attempts_challenge_id"): (
            ["challenge_id"],
            False,
            False,
            None,
        ),
        ("auth_sessions", "pk_auth_sessions"): (["id"], True, True, None),
        ("auth_sessions", "uq_auth_sessions_token_hash"): (
            ["token_hash"],
            True,
            False,
            None,
        ),
        ("auth_sessions", "ix_auth_sessions_user_id"): (
            ["user_id"],
            False,
            False,
            None,
        ),
        ("auth_sessions", "ix_auth_sessions_token_hash"): (
            ["token_hash"],
            False,
            False,
            None,
        ),
        ("auth_sessions", "ix_auth_sessions_expires_at"): (
            ["expires_at"],
            False,
            False,
            None,
        ),
        ("auth_sessions", "uq_auth_sessions_one_active_per_user"): (
            ["user_id"],
            True,
            False,
            "status = 'active'",
        ),
    }
    if head:
        expected_indexes.update(
            {
                ("login_attempts", "ix_login_attempts_expires_at"): (
                    ["expires_at"],
                    False,
                    False,
                    None,
                ),
                ("login_attempts", "ix_login_attempts_consumed_at"): (
                    ["consumed_at"],
                    False,
                    False,
                    None,
                ),
                ("auth_sessions", "ix_auth_sessions_revoked_at"): (
                    ["revoked_at"],
                    False,
                    False,
                    None,
                ),
            }
        )
    actual_indexes = {
        (str(row["table_name"]), str(row["index_name"])): row
        for row in index_rows
    }
    if (
        len(actual_indexes) != len(index_rows)
        or set(actual_indexes) != set(expected_indexes)
    ):
        raise ValueError("PostgreSQL index catalog inventory mismatch")
    for key, (columns, unique, primary, predicate) in expected_indexes.items():
        row = actual_indexes[key]
        if (
            list(row["key_columns"] or []) != columns
            or list(row["include_columns"] or [])
            or int(row["indnkeyatts"]) != len(columns)
            or int(row["indnatts"]) != len(columns)
            or bool(row["indisunique"]) is not unique
            or bool(row["indisprimary"]) is not primary
            or bool(row["indisexclusion"])
            or not bool(row["indisvalid"])
            or not bool(row["indisready"])
            or not bool(row["indislive"])
            or bool(row["indnullsnotdistinct"])
            or not bool(row["has_no_expressions"])
            or row["access_method"] != "btree"
            or _normalise_sql(row["predicate"]) != _normalise_sql(predicate)
        ):
            raise ValueError("unsafe PostgreSQL index state")


def _validate_postflight(bind: sa.Connection, *, head: bool) -> None:
    error = _reject if head else _downgrade_reject
    try:
        inspector = sa.inspect(bind)
        _validate_exact_auth_schema(
            inspector,
            dialect=bind.dialect.name,
            head=head,
        )
        _validate_exact_auth_indexes(
            inspector,
            dialect=bind.dialect.name,
            head=head,
        )
        if bind.dialect.name == "postgresql":
            _validate_postgresql_catalog_authority(bind, head=head)
    except (AuthRetentionMigrationError, AuthRetentionDowngradeError):
        raise
    except (AttributeError, KeyError, SQLAlchemyError, TypeError, ValueError):
        raise error() from None


_LOGIN_STATUS = "status IN ('pending', 'consumed', 'expired', 'erased')"
_LOGIN_LOOKUP_SHAPE = (
    "length(lookup_hash) = 64 AND " + _hex_residue_is_empty("lookup_hash")
)
_LOGIN_OPAQUE_SHAPE = (
    "((status <> 'erased' AND length(opaque_id) = 32) OR "
    "(status = 'erased' AND length(opaque_id) = 64)) AND "
    + _hex_residue_is_empty("opaque_id")
)
_LOGIN_LIFECYCLE = (
    "(status = 'pending' AND consumed_at IS NULL AND deleted_at IS NULL) OR "
    "(status IN ('consumed', 'expired') AND consumed_at IS NOT NULL "
    "AND deleted_at IS NULL) OR "
    "(status = 'erased' AND registration_id IS NULL AND challenge_id IS NULL "
    "AND consumed_at IS NOT NULL AND deleted_at IS NOT NULL "
    "AND metadata_json IS NULL AND created_at = updated_at "
    "AND updated_at = expires_at AND expires_at = consumed_at "
    "AND consumed_at = deleted_at)"
)
_SESSION_STATUS = "status IN ('active', 'revoked', 'expired', 'erased')"
_SESSION_TOKEN_SHAPE = (
    "length(token_hash) = 64 AND " + _hex_residue_is_empty("token_hash")
)
_SESSION_LIFECYCLE = (
    "(status = 'active' AND user_id IS NOT NULL AND revoked_at IS NULL "
    "AND deleted_at IS NULL) OR "
    "(status IN ('revoked', 'expired') AND user_id IS NOT NULL "
    "AND revoked_at IS NOT NULL AND deleted_at IS NULL) OR "
    "(status = 'erased' AND user_id IS NULL AND revoked_at IS NOT NULL "
    "AND deleted_at IS NOT NULL AND metadata_json IS NULL "
    "AND created_at = updated_at AND updated_at = expires_at "
    "AND expires_at = last_seen_at AND last_seen_at = revoked_at "
    "AND revoked_at = deleted_at)"
)


def _begin_and_lock(bind: sa.Connection, *, downgrade: bool) -> None:
    error = _downgrade_reject if downgrade else _reject
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
                    "LOCK TABLE data_subject_requests, deletion_jobs, users, "
                    "student_registrations, login_attempts, auth_sessions, "
                    "audit_events IN SHARE ROW EXCLUSIVE MODE NOWAIT"
                )
            )
        elif bind.dialect.name == "sqlite":
            driver = bind.connection.driver_connection
            if not driver.in_transaction:
                bind.exec_driver_sql("BEGIN IMMEDIATE")
        else:
            raise error()

        inspector = sa.inspect(bind)
        if not {
            "data_subject_requests",
            "deletion_jobs",
            "users",
            "student_registrations",
            "login_attempts",
            "auth_sessions",
            "audit_events",
        } <= set(inspector.get_table_names()):
            raise error()
        _validate_exact_auth_schema(
            inspector,
            dialect=bind.dialect.name,
            head=downgrade,
        )
        _validate_exact_auth_indexes(
            inspector,
            dialect=bind.dialect.name,
            head=downgrade,
        )
        if bind.dialect.name == "postgresql":
            _validate_postgresql_catalog_authority(bind, head=downgrade)
    except (AuthRetentionMigrationError, AuthRetentionDowngradeError):
        raise
    except (AttributeError, KeyError, SQLAlchemyError, TypeError, ValueError):
        raise error() from None


def _upgrade_data_preflight(bind: sa.Connection) -> None:
    try:
        invalid_login = bind.scalar(
            sa.text(
                "SELECT 1 FROM login_attempts WHERE "
                "status IS NULL OR status NOT IN ('pending','consumed','expired') OR "
                "opaque_id IS NULL OR length(opaque_id) <> 32 OR NOT ("
                + _hex_residue_is_empty("opaque_id") + ") OR "
                "lookup_hash IS NULL OR length(lookup_hash) <> 64 OR NOT ("
                + _hex_residue_is_empty("lookup_hash") + ") OR "
                "expires_at IS NULL OR created_at IS NULL OR updated_at IS NULL OR "
                "(status = 'pending' AND consumed_at IS NOT NULL) OR "
                "(status = 'consumed' AND consumed_at IS NULL) OR deleted_at IS NOT NULL OR "
                "(registration_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM student_registrations AS registration_row "
                "WHERE registration_row.id = login_attempts.registration_id)) OR "
                "(challenge_id IS NOT NULL AND NOT EXISTS ("
                "SELECT 1 FROM otp_challenges AS challenge_row "
                "WHERE challenge_row.id = login_attempts.challenge_id)) "
                "LIMIT 1"
            )
        )
        invalid_session = bind.scalar(
            sa.text(
                "SELECT 1 FROM auth_sessions WHERE "
                "status IS NULL OR status NOT IN ('active','revoked','expired') OR "
                "user_id IS NULL OR token_hash IS NULL OR length(token_hash) <> 64 OR NOT ("
                + _hex_residue_is_empty("token_hash") + ") OR "
                "expires_at IS NULL OR last_seen_at IS NULL OR "
                "created_at IS NULL OR updated_at IS NULL OR "
                "(status = 'active' AND revoked_at IS NOT NULL) OR deleted_at IS NOT NULL OR "
                "NOT EXISTS (SELECT 1 FROM users AS user_row "
                "WHERE user_row.id = auth_sessions.user_id) "
                "LIMIT 1"
            )
        )
    except SQLAlchemyError:
        raise _reject() from None
    if invalid_login is not None or invalid_session is not None:
        raise _reject()


def _freeze_accepted_legacy_deletions(bind: sa.Connection) -> None:
    """Close the pre-0020 accepted-delete/session revocation gap atomically."""

    subjects = (
        "SELECT DISTINCT dsr.user_id FROM data_subject_requests AS dsr "
        "JOIN deletion_jobs AS job ON job.request_id = dsr.id "
        "WHERE dsr.kind = 'delete' AND dsr.reauth_verified = true "
        "AND dsr.status IN ('pending','processing','complete','failed')"
    )
    try:
        invalid_evidence = bind.scalar(
            sa.text(
                "SELECT 1 FROM data_subject_requests AS dsr "
                "JOIN deletion_jobs AS job ON job.request_id = dsr.id "
                "WHERE dsr.kind = 'delete' AND dsr.reauth_verified = true "
                "AND (dsr.status IS NULL OR (dsr.status <> 'cancelled' AND ("
                "dsr.status NOT IN ('pending','processing','complete','failed') OR "
                "dsr.confirmation_hash IS NULL OR length(dsr.confirmation_hash) <> 64 OR NOT ("
                + _hex_residue_is_empty("dsr.confirmation_hash") + ") OR "
                "job.status IS NULL OR "
                "job.status NOT IN ('pending','processing','complete','failed') OR "
                "job.mode IS NULL OR job.mode NOT IN ('anonymise','delete')))) LIMIT 1"
            )
        )
        ambiguous_job = bind.scalar(
            sa.text(
                "SELECT 1 FROM data_subject_requests AS dsr "
                "LEFT JOIN deletion_jobs AS job ON job.request_id = dsr.id "
                "WHERE dsr.kind = 'delete' AND dsr.reauth_verified = true "
                "AND dsr.status IN ('pending','processing','complete','failed') "
                "GROUP BY dsr.id HAVING count(job.id) <> 1 LIMIT 1"
            )
        )
        if invalid_evidence is not None or ambiguous_job is not None:
            raise _reject()
        invalid_target = bind.scalar(
            sa.text(
                "WITH targets AS (" + subjects + ") "
                "SELECT 1 FROM targets AS target "
                "LEFT JOIN users AS user_row ON user_row.id = target.user_id "
                "LEFT JOIN student_registrations AS registration_row "
                "ON registration_row.user_id = target.user_id "
                "GROUP BY target.user_id, user_row.id, user_row.role, user_row.status "
                "HAVING user_row.id IS NULL OR user_row.role IS NULL "
                "OR user_row.role <> 'student' OR user_row.status IS NULL "
                "OR user_row.status NOT IN ('pending','active','suspended','deleted') "
                "OR count(registration_row.id) <> 1 OR "
                "min(CASE WHEN registration_row.status IN "
                "('otp_pending','otp_verified','active','suspended','deleted') "
                "THEN 1 ELSE 0 END) <> 1 LIMIT 1"
            )
        )
        if invalid_target is not None:
            raise _reject()
        frozen_users = bind.execute(
            sa.text(
                "UPDATE users SET status = 'suspended', updated_at = CURRENT_TIMESTAMP "
                f"WHERE id IN ({subjects}) AND status NOT IN ('suspended', 'deleted')"
            )
        ).rowcount
        frozen_registrations = bind.execute(
            sa.text(
                "UPDATE student_registrations SET status = 'suspended', "
                "updated_at = CURRENT_TIMESTAMP "
                f"WHERE user_id IN ({subjects}) "
                "AND status NOT IN ('suspended', 'deleted')"
            )
        ).rowcount
        revoked_sessions = bind.execute(
            sa.text(
                "UPDATE auth_sessions SET "
                "status = CASE WHEN expires_at <= CURRENT_TIMESTAMP "
                "THEN 'expired' ELSE 'revoked' END, "
                "revoked_at = CASE WHEN expires_at <= CURRENT_TIMESTAMP "
                "THEN expires_at ELSE CURRENT_TIMESTAMP END, "
                "updated_at = CURRENT_TIMESTAMP "
                f"WHERE user_id IN ({subjects}) AND status = 'active'"
            )
        ).rowcount
        if frozen_users or frozen_registrations or revoked_sessions:
            audit = sa.table(
                "audit_events",
                sa.column("id", _UUID),
                sa.column("actor_user_id", _UUID),
                sa.column("actor_role", sa.String(40)),
                sa.column("action", sa.String(120)),
                sa.column("resource_type", sa.String(80)),
                sa.column("resource_id", _UUID),
                sa.column("before_state", sa.JSON()),
                sa.column("after_state", sa.JSON()),
                sa.column("ip_hash", sa.String(64)),
                sa.column("user_agent_hash", sa.String(64)),
                sa.column("created_at", sa.DateTime(timezone=True)),
            )
            bind.execute(
                audit.insert().values(
                    id=uuid.uuid4(),
                    actor_user_id=None,
                    actor_role="system",
                    action="student.auth.deletion_backfill_frozen",
                    resource_type="auth_security_history",
                    resource_id=None,
                    before_state=None,
                    after_state={
                        "accounts": max(0, frozen_users or 0),
                        "registrations": max(0, frozen_registrations or 0),
                        "sessions": max(0, revoked_sessions or 0),
                    },
                    ip_hash=None,
                    user_agent_hash=None,
                    created_at=sa.func.now(),
                )
            )
    except AuthRetentionMigrationError:
        raise
    except SQLAlchemyError:
        raise _reject() from None


def upgrade() -> None:
    bind = op.get_bind()
    _begin_and_lock(bind, downgrade=False)
    _upgrade_data_preflight(bind)
    _freeze_accepted_legacy_deletions(bind)

    # Historical code marked expiry without a terminal timestamp.  Populate a
    # non-PII lifecycle instant before the stricter state checks become active.
    bind.execute(
        sa.text(
            "UPDATE login_attempts SET consumed_at = expires_at "
            "WHERE status = 'expired' AND consumed_at IS NULL"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE auth_sessions SET revoked_at = expires_at "
            "WHERE status = 'expired'"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, updated_at) "
            "WHERE status = 'revoked' AND revoked_at IS NULL"
        )
    )

    with op.batch_alter_table("login_attempts") as batch:
        batch.drop_constraint(
            op.f("ck_login_attempts_ck_login_attempts_status"), type_="check"
        )
        batch.create_check_constraint(op.f("ck_login_attempts_status"), _LOGIN_STATUS)
        batch.create_check_constraint(
            op.f("ck_login_attempts_lookup_hash_shape"), _LOGIN_LOOKUP_SHAPE
        )
        batch.create_check_constraint(
            op.f("ck_login_attempts_opaque_id_shape"), _LOGIN_OPAQUE_SHAPE
        )
        batch.create_check_constraint(
            op.f("ck_login_attempts_lifecycle_shape"), _LOGIN_LIFECYCLE
        )
    op.create_index(
        "ix_login_attempts_expires_at", "login_attempts", ["expires_at"]
    )
    op.create_index(
        "ix_login_attempts_consumed_at", "login_attempts", ["consumed_at"]
    )

    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_constraint(
            op.f("ck_auth_sessions_ck_auth_sessions_status"), type_="check"
        )
        batch.alter_column(
            "user_id", existing_type=_UUID, existing_nullable=False, nullable=True
        )
        batch.create_check_constraint(op.f("ck_auth_sessions_status"), _SESSION_STATUS)
        batch.create_check_constraint(
            op.f("ck_auth_sessions_token_hash_shape"), _SESSION_TOKEN_SHAPE
        )
        batch.create_check_constraint(
            op.f("ck_auth_sessions_lifecycle_shape"), _SESSION_LIFECYCLE
        )
    op.create_index(
        "ix_auth_sessions_revoked_at", "auth_sessions", ["revoked_at"]
    )
    _validate_postflight(bind, head=True)


def downgrade() -> None:
    bind = op.get_bind()
    _begin_and_lock(bind, downgrade=True)
    try:
        unsafe = bind.scalar(
            sa.text(
                "SELECT 1 FROM login_attempts WHERE status = 'erased' LIMIT 1"
            )
        ) is not None or bind.scalar(
            sa.text(
                "SELECT 1 FROM auth_sessions WHERE status = 'erased' OR user_id IS NULL LIMIT 1"
            )
        ) is not None or bind.scalar(
            sa.text(
                "SELECT 1 FROM audit_events "
                "WHERE action = 'student.auth.deletion_backfill_frozen' LIMIT 1"
            )
        ) is not None
    except SQLAlchemyError:
        raise _downgrade_reject() from None
    if unsafe:
        raise _downgrade_reject()

    op.drop_index("ix_auth_sessions_revoked_at", table_name="auth_sessions")
    op.drop_index("ix_login_attempts_consumed_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_expires_at", table_name="login_attempts")
    with op.batch_alter_table("auth_sessions") as batch:
        batch.drop_constraint(op.f("ck_auth_sessions_lifecycle_shape"), type_="check")
        batch.drop_constraint(op.f("ck_auth_sessions_token_hash_shape"), type_="check")
        batch.drop_constraint(op.f("ck_auth_sessions_status"), type_="check")
        batch.alter_column(
            "user_id", existing_type=_UUID, existing_nullable=True, nullable=False
        )
        # Reproduce the historical 0010 physical name under the naming
        # convention rather than silently rewriting immutable history.
        batch.create_check_constraint(
            op.f("ck_auth_sessions_ck_auth_sessions_status"),
            "status IN ('active', 'revoked', 'expired')",
        )

    with op.batch_alter_table("login_attempts") as batch:
        batch.drop_constraint(op.f("ck_login_attempts_lifecycle_shape"), type_="check")
        batch.drop_constraint(op.f("ck_login_attempts_opaque_id_shape"), type_="check")
        batch.drop_constraint(op.f("ck_login_attempts_lookup_hash_shape"), type_="check")
        batch.drop_constraint(op.f("ck_login_attempts_status"), type_="check")
        batch.create_check_constraint(
            op.f("ck_login_attempts_ck_login_attempts_status"),
            "status IN ('pending', 'consumed', 'expired')",
        )
    _validate_postflight(bind, head=False)
