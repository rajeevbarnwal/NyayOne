"""Forward-only repair for historical DOB lookup-hash placeholders.

Revision ID: 0016_dob_hash_reconcile
Revises: 0015_wave4_public_risk_labels

The complete populated-database plan is validated while holding the
authoritative PostgreSQL transaction/table locks and before the first DDL
statement.  Reconciliation evidence contains only bounded disposition codes,
key-version metadata, and a SHA-256 digest of the already-encrypted source; it
never stores plaintext DOB, ciphertext, lookup hashes, exception text, or free
form metadata.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import uuid
from datetime import date
from typing import NamedTuple

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings

revision: str = "0016_dob_hash_reconcile"
down_revision: str | None = "0015_wave4_public_risk_labels"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)
_LEGACY_PLACEHOLDER = "[rehash-required]"
_ERASED = "[erased]"
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_DOB_HASH_STATES = ("verified", "quarantined", "erased")
_OUTCOMES = ("reconciled", "quarantined")
_REASON_CODES = (
    "verified_source",
    "ciphertext_unreadable",
    "source_not_canonical_date",
    "source_future_date",
)
_QUARANTINE_DOMAIN = b"nyayone:dob-hash-quarantine:v1:"
_HEX_ONLY_SQL = "dob_hash"
for _hex_character in "0123456789abcdef":
    _HEX_ONLY_SQL = f"replace({_HEX_ONLY_SQL}, '{_hex_character}', '')"
_SOURCE_DIGEST_HEX_ONLY_SQL = "source_ciphertext_sha256"
for _hex_character in "0123456789abcdef":
    _SOURCE_DIGEST_HEX_ONLY_SQL = (
        f"replace({_SOURCE_DIGEST_HEX_ONLY_SQL}, '{_hex_character}', '')"
    )
_DOB_HASH_STATE_CHECK_SQL = (
    "dob_hash_state IN ('verified', 'quarantined', 'erased')"
)
_DOB_HASH_STATE_CONSISTENCY_SQL = (
    "(dob_hash_state IN ('verified', 'quarantined') AND status <> 'deleted' "
    "AND length(dob_hash) = 64 "
    f"AND length({_HEX_ONLY_SQL}) = 0) OR "
    "(dob_hash_state = 'erased' AND status = 'deleted' "
    "AND mobile_ct = '[erased]' AND dob_ct = '[erased]' "
    "AND replace(mobile_hash, '-', '') = '[erased]:' || "
    "replace(CAST(id AS VARCHAR), '-', '') "
    "AND replace(dob_hash, '-', '') = '[erased]:' || "
    "replace(CAST(id AS VARCHAR), '-', ''))"
)
_RECONCILIATION_OUTCOME_CHECK_SQL = (
    "outcome IN ('reconciled', 'quarantined')"
)
_RECONCILIATION_REASON_CHECK_SQL = (
    "reason_code IN ('verified_source', 'ciphertext_unreadable', "
    "'source_not_canonical_date', 'source_future_date')"
)
_RECONCILIATION_OUTCOME_REASON_SQL = (
    "(outcome = 'reconciled' AND reason_code = 'verified_source') OR "
    "(outcome = 'quarantined' AND reason_code != 'verified_source')"
)
_RECONCILIATION_SOURCE_DIGEST_SQL = (
    "length(source_ciphertext_sha256) = 64 AND "
    f"length({_SOURCE_DIGEST_HEX_ONLY_SQL}) = 0"
)
_RECONCILIATION_FK_NAME = (
    "fk_registration_dob_reconciliations_registration_id_student_registrations"
)
# SQLAlchemy's naming convention truncates identifiers deterministically for
# PostgreSQL's 63-byte limit. Fingerprint the physical name as well as the FK
# semantics; accepting an arbitrary prefix would reopen structural drift.
_RECONCILIATION_FK_NAME_POSTGRESQL = (
    "fk_registration_dob_reconciliations_registration_id_stu_1b42"
)
_PG_ADVISORY_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"nyayone:migration:0016:dob-hash-reconcile").digest()[:8],
    byteorder="big",
    signed=True,
)
_DEV_DEFAULT_SECRETS = frozenset({
    "dev-registration-secret-change-me",
    "dev-registration-lookup-change-me",
    "",
    "changeme",
    "change-me",
})


def _is_development_default_secret(value: str) -> bool:
    """Detect padded defaults without changing the bytes used by crypto."""

    return value.strip() in _DEV_DEFAULT_SECRETS


class DobHashPreflightError(RuntimeError):
    """Deliberately non-identifying fail-closed rejection."""


class MigrationKeyRing(NamedTuple):
    active_version: str
    secrets: dict[str, bytes]
    lookup_secret: bytes


class DobHashPlanRow(NamedTuple):
    """A retained, non-PII operation produced after source verification."""

    registration_id: object
    state: str
    replacement_hash: str | None = None
    outcome: str | None = None
    reason_code: str | None = None
    source_key_version: str | None = None
    source_ciphertext_sha256: str | None = None


def _reject() -> DobHashPreflightError:
    return DobHashPreflightError(
        "NYAY-16 DOB reconciliation preflight rejected ambiguous schema, data, or key authority"
    )


def _canonical_uuid(value: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _reject() from exc


def _quarantine_hash(registration_id: object) -> str:
    canonical = _canonical_uuid(registration_id).hex.encode("ascii")
    return hashlib.sha256(_QUARANTINE_DOMAIN + canonical).hexdigest()


def _exact_erased_crypto_tuple(row: sa.RowMapping) -> bool:
    """Match only the retention-erased mobile/DOB cryptographic fields.

    NYAY-16 reconciles DOB lookup authority; it does not claim to audit the
    broader registration/profile retention policy.
    """

    expected_hash = f"{_ERASED}:{_canonical_uuid(row['id'])}"
    return (
        row["status"] == "deleted"
        and row["mobile_ct"] == _ERASED
        and row["mobile_hash"] == expected_hash
        and row["dob_ct"] == _ERASED
        and row["dob_hash"] == expected_hash
    )


def _acquire_preflight_locks(
    bind: Connection,
    *,
    include_reconciliation: bool = False,
) -> None:
    """Serialize NYAY-16 planning and close the writer gap on PostgreSQL."""

    dialect = bind.dialect.name
    if dialect == "postgresql":
        try:
            bind.execute(sa.text("SET LOCAL lock_timeout = '5000ms'"))
            bind.execute(sa.text("SET LOCAL statement_timeout = '30000ms'"))
            bind.execute(
                sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _PG_ADVISORY_LOCK_KEY},
            )
            tables = (
                "student_registrations, auth_sessions, login_attempts, "
                "recovery_sessions, otp_challenges"
            )
            if include_reconciliation:
                tables += ", registration_dob_reconciliations"
            bind.execute(
                sa.text(f"LOCK TABLE {tables} IN SHARE ROW EXCLUSIVE MODE")
            )
        except SQLAlchemyError:
            raise _reject() from None
    elif dialect != "sqlite":
        raise _reject()
    # SQLite is retained only for repository migration-lifecycle compatibility.
    # It is never reported as authoritative populated-database evidence.


_PARENT_COLUMNS: dict[str, tuple[str, bool, int | None]] = {
    "id": ("uuid", False, None),
    "user_id": ("uuid", False, None),
    "first_name": ("string", False, 60),
    "middle_name": ("string", True, 60),
    "last_name": ("string", False, 60),
    "mobile_hash": ("string", False, 64),
    "mobile_ct": ("string", False, 600),
    "dob_ct": ("string", False, 600),
    "institution_ref": ("string", True, 120),
    "status": ("string", False, 32),
    "is_minor": ("boolean", False, None),
    "idempotency_key": ("string", True, 200),
    "created_at": ("datetime", False, None),
    "updated_at": ("datetime", False, None),
    "deleted_at": ("datetime", True, None),
    "metadata_json": ("json", True, None),
    "dob_hash": ("string", False, 64),
    "key_version": ("string", False, 8),
}
_HEAD_REGISTRATION_COLUMNS = {
    **_PARENT_COLUMNS,
    "dob_hash_state": ("string", False, 16),
}
_RECONCILIATION_COLUMNS: dict[str, tuple[str, bool, int | None]] = {
    "registration_id": ("uuid", False, None),
    "outcome": ("string", False, 16),
    "reason_code": ("string", False, 40),
    "source_key_version": ("string", False, 8),
    "source_ciphertext_sha256": ("string", False, 64),
    "created_at": ("datetime", False, None),
}


def _type_matches(
    actual: sa.types.TypeEngine,
    kind: str,
    length: int | None,
    dialect: str,
) -> bool:
    if kind == "uuid":
        return isinstance(actual, sa.Uuid) or (
            dialect == "sqlite"
            and isinstance(actual, sa.CHAR)
            and getattr(actual, "length", None) == 32
        )
    if kind == "string":
        return isinstance(actual, sa.String) and getattr(actual, "length", None) == length
    if kind == "boolean":
        return isinstance(actual, sa.Boolean)
    if kind == "datetime":
        return isinstance(actual, sa.DateTime)
    if kind == "json":
        return isinstance(actual, sa.JSON)
    return False


def _lower_sql_outside_literals(value: str) -> str:
    """Canonicalize SQL keywords while preserving quoted payload bytes."""

    result: list[str] = []
    in_literal = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            result.append(character)
            if in_literal and index + 1 < len(value) and value[index + 1] == "'":
                result.append("'")
                index += 2
                continue
            in_literal = not in_literal
        else:
            result.append(character if in_literal else character.lower())
        index += 1
    # An unmatched quote is intentionally left noncanonical so exact callers
    # reject it instead of guessing at SQL semantics.
    return "".join(result)


def _normalized_default(value: object) -> str:
    """Remove inspector syntax without changing case-sensitive payload text."""

    normalized = _lower_sql_outside_literals(str(value).strip())
    for _attempt in range(4):
        previous = normalized
        # PostgreSQL reflects string defaults with a type cast; SQLite does not.
        normalized = re.sub(
            r"::(?:character varying|varchar|text|boolean|timestamp(?: with time zone)?)$",
            "",
            normalized,
            flags=re.IGNORECASE,
        ).strip()
        if normalized.startswith("(") and normalized.endswith(")"):
            depth = 0
            quote = False
            encloses_all = True
            for index, character in enumerate(normalized):
                if character == "'":
                    quote = not quote
                elif not quote and character == "(":
                    depth += 1
                elif not quote and character == ")":
                    depth -= 1
                    if depth < 0:
                        encloses_all = False
                        break
                if depth == 0 and index != len(normalized) - 1:
                    encloses_all = False
                    break
            if encloses_all and depth == 0 and not quote:
                normalized = normalized[1:-1].strip()
        if normalized == previous:
            break
    return normalized


def _validate_registration_defaults(actual_columns: dict[str, dict[str, object]]) -> None:
    no_default = (
        "id", "user_id", "first_name", "middle_name", "last_name", "mobile_hash",
        "mobile_ct", "dob_ct", "institution_ref", "idempotency_key", "deleted_at",
        "metadata_json",
    )
    if any(actual_columns[name].get("default") is not None for name in no_default):
        raise _reject()
    expected = {
        "status": {"'otp_pending'"},
        "is_minor": {"0", "false"},
        "dob_hash": {"'[rehash-required]'"},
        "key_version": {"'v1'"},
        "created_at": {"now()", "current_timestamp"},
        "updated_at": {"now()", "current_timestamp"},
    }
    for name, allowed in expected.items():
        if _normalized_default(actual_columns[name].get("default")) not in allowed:
            raise _reject()


def _validate_no_table_hooks(bind: Connection, table_name: str) -> None:
    """Reject code-bearing schema surfaces that can alter or observe repair DML."""

    if bind.dialect.name == "postgresql":
        trigger_count = bind.scalar(
            sa.text(
                "SELECT count(*) FROM pg_trigger t "
                "JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() AND c.relname=:table "
                "AND NOT t.tgisinternal"
            ),
            {"table": table_name},
        )
        rule_count = bind.scalar(
            sa.text(
                "SELECT count(*) FROM pg_rewrite r "
                "JOIN pg_class c ON c.oid=r.ev_class "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() AND c.relname=:table "
                "AND r.rulename <> '_RETURN'"
            ),
            {"table": table_name},
        )
        rls = bind.execute(
            sa.text(
                "SELECT c.relrowsecurity,c.relforcerowsecurity,"
                "(SELECT count(*) FROM pg_policy p WHERE p.polrelid=c.oid) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=current_schema() AND c.relname=:table"
            ),
            {"table": table_name},
        ).one_or_none()
        if trigger_count != 0 or rule_count != 0 or rls is None:
            raise _reject()
        if bool(rls[0]) or bool(rls[1]) or int(rls[2]) != 0:
            raise _reject()
    elif bind.dialect.name == "sqlite":
        trigger_count = bind.scalar(
            sa.text(
                "SELECT count(*) FROM sqlite_master "
                "WHERE type='trigger' AND tbl_name=:table"
            ),
            {"table": table_name},
        )
        if trigger_count != 0:
            raise _reject()
    else:
        raise _reject()


def _expected_reconciliation_fk_name(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return _RECONCILIATION_FK_NAME_POSTGRESQL
    if dialect_name == "sqlite":
        return _RECONCILIATION_FK_NAME
    raise _reject()


def _strip_boolean_outer_parentheses(value: str) -> str:
    """Remove only parentheses that enclose one complete boolean expression."""

    current = value.strip()
    while current.startswith("(") and current.endswith(")"):
        depth = 0
        in_literal = False
        encloses_all = True
        index = 0
        while index < len(current):
            character = current[index]
            if character == "'":
                if in_literal and index + 1 < len(current) and current[index + 1] == "'":
                    index += 2
                    continue
                in_literal = not in_literal
            elif not in_literal and character == "(":
                depth += 1
            elif not in_literal and character == ")":
                depth -= 1
                if depth == 0 and index != len(current) - 1:
                    encloses_all = False
                    break
                if depth < 0:
                    encloses_all = False
                    break
            index += 1
        if not encloses_all or in_literal or depth != 0:
            break
        current = current[1:-1].strip()
    return current


def _split_top_level_boolean(value: str, keyword: str) -> list[str]:
    """Split a canonical SQL expression on a top-level AND/OR token."""

    parts: list[str] = []
    start = 0
    depth = 0
    in_literal = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            if in_literal and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_literal = not in_literal
            index += 1
            continue
        if not in_literal:
            if character == "(":
                depth += 1
            elif character == ")":
                # SQLAlchemy's PostgreSQL CHECK reflection strips some leading
                # CHECK/group parentheses while retaining their closing mate.
                # Ignore only an unmatched top-level closer; real nested
                # function/list/group parentheses still affect depth.
                if depth > 0:
                    depth -= 1
            elif depth == 0 and value.startswith(keyword, index):
                before = value[index - 1] if index else " "
                after_index = index + len(keyword)
                after = value[after_index] if after_index < len(value) else " "
                if not (before.isalnum() or before == "_") and not (
                    after.isalnum() or after == "_"
                ):
                    parts.append(value[start:index].strip())
                    start = after_index
                    index = after_index
                    continue
        index += 1
    if not parts:
        return [value.strip()]
    parts.append(value[start:].strip())
    return parts


def _check_atom_signature(
    canonical: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return a dialect-neutral signature for one boolean predicate."""

    literals = tuple(re.findall(r"'([^']*)'", canonical))
    without_literals = re.sub(r"'[^']*'", "", canonical)
    # PostgreSQL rewrites positive IN lists as = ANY(ARRAY[...]); canonicalize
    # only that exact operator pair. A hostile <> ANY remains visible below.
    operator_source = re.sub(r"=\s*any\b", " in ", without_literals)
    operators = tuple(
        "<>" if operator == "!=" else operator
        for operator in re.findall(
            r"<>|!=|<=|>=|<<|>>|\|\||[=<>+\-*/%~^&|#!@`?]", operator_source
        )
    )
    words = []
    for word in re.findall(r"[a-z_][a-z0-9_]*", operator_source):
        if word in {
            "check", "character", "varying", "text", "uuid", "bpchar",
            "cast", "as", "varchar", "array", "any",
        }:
            continue
        words.append(word)
    numbers = tuple(
        re.findall(r"(?<![a-z0-9_])(?:0|[1-9][0-9]*)(?![a-z0-9_])", operator_source)
    )
    # Word order is part of the contract: a bag-of-words signature would let a
    # hostile CHECK swap the columns attached to otherwise identical literals.
    return literals, tuple(words), operators, numbers


def _check_signature(sql: str) -> tuple[object, ...]:
    """Build a grouping-sensitive, dialect-neutral CHECK expression tree."""

    canonical = _strip_boolean_outer_parentheses(
        _lower_sql_outside_literals(sql)
    )
    # SQL AND binds more tightly than OR. Split the lower-precedence operator
    # first so explicit hostile regrouping produces a different tree while
    # redundant parentheses and PostgreSQL's omitted precedence parentheses do
    # not. Flatten associative uses without reordering their operands.
    for keyword in ("or", "and"):
        parts = _split_top_level_boolean(canonical, keyword)
        if len(parts) > 1:
            children: list[tuple[object, ...]] = []
            for part in parts:
                child = _check_signature(part)
                if child and child[0] == keyword:
                    children.extend(child[1:])
                else:
                    children.append(child)
            return (keyword, *children)
    return ("predicate", *_check_atom_signature(canonical))


def _validate_check_sql(actual: object, expected: str) -> None:
    if _check_signature(str(actual)) != _check_signature(expected):
        raise _reject()


def _validate_exact_columns(
    bind: Connection,
    inspector: sa.Inspector,
    table_name: str,
    expected: dict[str, tuple[str, bool, int | None]],
) -> dict[str, dict[str, object]]:
    actual = {
        column["name"]: column for column in inspector.get_columns(table_name)
    }
    if set(actual) != set(expected):
        raise _reject()
    for name, (kind, nullable, length) in expected.items():
        column = actual[name]
        if bool(column["nullable"]) != nullable:
            raise _reject()
        if not _type_matches(column["type"], kind, length, bind.dialect.name):
            raise _reject()
        if kind == "datetime" and bind.dialect.name == "postgresql":
            if getattr(column["type"], "timezone", False) is not True:
                raise _reject()
    return actual


def _validate_registration_keys_and_indexes(
    inspector: sa.Inspector,
    *,
    include_state: bool,
) -> None:
    primary_key = inspector.get_pk_constraint("student_registrations")
    if (
        primary_key.get("name") != "pk_student_registrations"
        or primary_key.get("constrained_columns") != ["id"]
    ):
        raise _reject()

    indexes = {
        row["name"]: row
        for row in inspector.get_indexes("student_registrations")
        if not row.get("duplicates_constraint")
    }
    expected_index_columns = {
        "ix_student_registrations_user_id": ["user_id"],
        "ix_student_registrations_mobile_hash": ["mobile_hash"],
        "ix_student_registrations_dob_hash": ["dob_hash"],
    }
    if include_state:
        expected_index_columns["ix_student_registrations_dob_hash_state"] = [
            "dob_hash_state"
        ]
    if set(indexes) != set(expected_index_columns):
        raise _reject()
    if any(
        indexes[name].get("column_names") != columns
        or bool(indexes[name].get("unique"))
        for name, columns in expected_index_columns.items()
    ):
        raise _reject()

    uniques = {
        row["name"]: row
        for row in inspector.get_unique_constraints("student_registrations")
    }
    expected_unique_columns = {
        "uq_student_registrations_mobile_hash": ["mobile_hash"],
        "uq_student_registrations_idempotency_key": ["idempotency_key"],
    }
    if set(uniques) != set(expected_unique_columns):
        raise _reject()
    if any(
        uniques[name].get("column_names") != columns
        or bool(uniques[name].get("deferrable"))
        or bool(uniques[name].get("initially"))
        for name, columns in expected_unique_columns.items()
    ):
        raise _reject()

    foreign_keys = inspector.get_foreign_keys("student_registrations")
    if len(foreign_keys) != 1:
        raise _reject()
    foreign_key = foreign_keys[0]
    options = foreign_key.get("options", {})
    if (
        foreign_key.get("name") != "fk_student_registrations_user_id_users"
        or foreign_key.get("constrained_columns") != ["user_id"]
        or foreign_key.get("referred_table") != "users"
        or foreign_key.get("referred_columns") != ["id"]
        or str(options.get("ondelete", "")).upper() != "CASCADE"
        or bool(options.get("deferrable"))
        or bool(options.get("initially"))
        or options.get("onupdate") not in (None, "NO ACTION")
    ):
        raise _reject()


def _validate_registration_checks(
    inspector: sa.Inspector,
    *,
    include_state: bool,
) -> None:
    checks = {
        row["name"]: row
        for row in inspector.get_check_constraints("student_registrations")
    }
    expected = {
        "ck_student_registrations_ck_student_registrations_status": (
            "status IN ('otp_pending', 'otp_verified', 'active', 'suspended', 'deleted')"
        )
    }
    if include_state:
        expected.update({
            "ck_student_registrations_dob_hash_state": _DOB_HASH_STATE_CHECK_SQL,
            "ck_student_registrations_dob_hash_state_consistency": (
                _DOB_HASH_STATE_CONSISTENCY_SQL
            ),
        })
    if set(checks) != set(expected):
        raise _reject()
    for name, expression in expected.items():
        _validate_check_sql(checks[name].get("sqltext", ""), expression)


def _validate_parent_schema(bind: Connection) -> None:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "student_registrations" not in tables or "alembic_version" not in tables:
        raise _reject()
    if "registration_dob_reconciliations" in tables:
        raise _reject()

    actual_columns = {
        column["name"]: column
        for column in inspector.get_columns("student_registrations")
    }
    if set(actual_columns) != set(_PARENT_COLUMNS):
        raise _reject()
    for name, (kind, nullable, length) in _PARENT_COLUMNS.items():
        column = actual_columns[name]
        if bool(column["nullable"]) != nullable:
            raise _reject()
        if not _type_matches(column["type"], kind, length, bind.dialect.name):
            raise _reject()
        if kind == "datetime" and bind.dialect.name == "postgresql":
            if getattr(column["type"], "timezone", False) is not True:
                raise _reject()

    _validate_registration_defaults(actual_columns)

    # 0003 supplied an already-prefixed name inside batch mode while the shared
    # naming convention added its own prefix.  The resulting doubled physical
    # name is historical fact and is fingerprinted rather than "fixed".
    _validate_registration_keys_and_indexes(inspector, include_state=False)
    _validate_registration_checks(inspector, include_state=False)

    _validate_no_table_hooks(bind, "student_registrations")

    versions = tuple(bind.execute(sa.text("SELECT version_num FROM alembic_version")))
    if len(versions) != 1 or versions[0][0] != down_revision:
        raise _reject()


def _validate_head_schema_for_downgrade(bind: Connection) -> None:
    """Fingerprint every 0016-owned structure before destructive downgrade."""

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if not {
        "student_registrations",
        "registration_dob_reconciliations",
        "alembic_version",
    } <= tables:
        raise _reject()

    registration_columns = _validate_exact_columns(
        bind,
        inspector,
        "student_registrations",
        _HEAD_REGISTRATION_COLUMNS,
    )
    _validate_registration_defaults(registration_columns)
    if registration_columns["dob_hash_state"].get("default") is not None:
        raise _reject()
    _validate_registration_keys_and_indexes(inspector, include_state=True)
    _validate_registration_checks(inspector, include_state=True)
    _validate_no_table_hooks(bind, "student_registrations")

    reconciliation_columns = _validate_exact_columns(
        bind,
        inspector,
        "registration_dob_reconciliations",
        _RECONCILIATION_COLUMNS,
    )
    if any(
        reconciliation_columns[name].get("default") is not None
        for name in _RECONCILIATION_COLUMNS
        if name != "created_at"
    ):
        raise _reject()
    if _normalized_default(
        reconciliation_columns["created_at"].get("default")
    ) not in {"now()", "current_timestamp"}:
        raise _reject()

    primary_key = inspector.get_pk_constraint("registration_dob_reconciliations")
    if (
        primary_key.get("name") != "pk_registration_dob_reconciliations"
        or primary_key.get("constrained_columns") != ["registration_id"]
    ):
        raise _reject()
    indexes = [
        row
        for row in inspector.get_indexes("registration_dob_reconciliations")
        if not row.get("duplicates_constraint")
    ]
    if indexes or inspector.get_unique_constraints("registration_dob_reconciliations"):
        raise _reject()

    checks = {
        row["name"]: row
        for row in inspector.get_check_constraints(
            "registration_dob_reconciliations"
        )
    }
    expected_checks = {
        "ck_registration_dob_reconciliations_outcome": (
            _RECONCILIATION_OUTCOME_CHECK_SQL
        ),
        "ck_registration_dob_reconciliations_reason_code": (
            _RECONCILIATION_REASON_CHECK_SQL
        ),
        "ck_registration_dob_reconciliations_outcome_reason": (
            _RECONCILIATION_OUTCOME_REASON_SQL
        ),
        "ck_registration_dob_reconciliations_source_digest_length": (
            _RECONCILIATION_SOURCE_DIGEST_SQL
        ),
    }
    if set(checks) != set(expected_checks):
        raise _reject()
    for name, expression in expected_checks.items():
        _validate_check_sql(checks[name].get("sqltext", ""), expression)

    foreign_keys = inspector.get_foreign_keys(
        "registration_dob_reconciliations"
    )
    if len(foreign_keys) != 1:
        raise _reject()
    foreign_key = foreign_keys[0]
    options = foreign_key.get("options", {})
    if (
        foreign_key.get("name")
        != _expected_reconciliation_fk_name(bind.dialect.name)
        or foreign_key.get("constrained_columns") != ["registration_id"]
        or foreign_key.get("referred_table") != "student_registrations"
        or foreign_key.get("referred_columns") != ["id"]
        or str(options.get("ondelete", "")).upper() != "CASCADE"
        or bool(options.get("deferrable"))
        or bool(options.get("initially"))
        or options.get("onupdate") not in (None, "NO ACTION")
    ):
        raise _reject()
    _validate_no_table_hooks(bind, "registration_dob_reconciliations")

    versions = tuple(bind.execute(sa.text("SELECT version_num FROM alembic_version")))
    if len(versions) != 1 or versions[0][0] != revision:
        raise _reject()


def _load_migration_keyring() -> MigrationKeyRing:
    """Freeze 0016 key parsing instead of importing mutable app crypto logic."""

    try:
        raw_active_version = str(settings.registration_key_version or "")
        if raw_active_version != raw_active_version.strip():
            raise _reject()
        active_version = raw_active_version
        # Active and lookup secrets use their exact configured bytes, matching
        # application crypto. Whitespace is checked for emptiness, never removed.
        active_secret = settings.registration_secret.get_secret_value()
        lookup_secret = settings.registration_lookup_secret.get_secret_value()
        prior_entries = tuple(settings.registration_prior_keys or ())
    except Exception as exc:
        raise _reject() from exc
    if (
        not active_version
        or len(active_version) > 8
        or not active_secret.strip()
        or not lookup_secret.strip()
    ):
        raise _reject()
    # A populated historical migration is an irreversible identity repair, so
    # known development defaults are rejected in every environment (stronger
    # than the application's production/staging startup boundary).
    if (
        _is_development_default_secret(active_secret)
        or _is_development_default_secret(lookup_secret)
    ):
        raise _reject()
    secrets: dict[str, bytes] = {active_version: active_secret.encode("utf-8")}
    for entry in prior_entries:
        if not isinstance(entry, str) or ":" not in entry:
            raise _reject()
        version, secret = (part.strip() for part in entry.split(":", 1))
        if (
            not version
            or len(version) > 8
            or not secret
            or version in secrets
            or _is_development_default_secret(secret)
        ):
            raise _reject()
        secrets[version] = secret.encode("utf-8")
    lookup_secret_bytes = lookup_secret.encode("utf-8")
    if any(
        hmac.compare_digest(lookup_secret_bytes, encryption_secret)
        for encryption_secret in secrets.values()
    ):
        raise _reject()
    return MigrationKeyRing(
        active_version,
        secrets,
        lookup_secret_bytes,
    )


def _source_parts(ciphertext: str, declared_version: str) -> tuple[str, str]:
    if not declared_version or len(declared_version) > 8:
        raise _reject()
    if ":" not in ciphertext:
        # Unstamped 0002 ciphertext is authoritative only under 0003's declared
        # row key version; trying arbitrary fallback keys would accept drift.
        return declared_version, ciphertext
    stamped_version, token = ciphertext.split(":", 1)
    if stamped_version != declared_version or not token:
        raise _reject()
    return stamped_version, token


def _authenticated_plaintext(token: str, secret: bytes) -> bytes | None:
    # Import lazily so an empty SQLite lifecycle can still inspect/load the
    # revision in minimal tooling; populated authoritative runs require the
    # pinned runtime dependency.
    try:
        from cryptography.fernet import Fernet, InvalidToken

        fernet_key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
        return Fernet(fernet_key).decrypt(token.encode("ascii"))
    except (InvalidToken, UnicodeEncodeError, ValueError):
        return None
    except ImportError as exc:
        raise _reject() from exc


def _canonical_date(raw: bytes | None) -> tuple[str | None, str]:
    if raw is None:
        return None, "ciphertext_unreadable"
    try:
        plaintext = raw.decode("utf-8")
        parsed = date.fromisoformat(plaintext)
    except (UnicodeDecodeError, ValueError):
        return None, "source_not_canonical_date"
    if parsed.isoformat() != plaintext:
        return None, "source_not_canonical_date"
    if parsed > date.today():
        return None, "source_future_date"
    return plaintext, "verified_source"


def _lookup_hash(value: str, ring: MigrationKeyRing) -> str:
    # A distinct configured lookup secret is mandatory; encryption-key fallback
    # would make rotations silently change lookup identity.
    return hmac.new(
        ring.lookup_secret,
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def preflight_dob_hash_reconciliation(bind: Connection) -> tuple[DobHashPlanRow, ...]:
    """Build the complete repair plan before DDL, or reject without PII."""

    _acquire_preflight_locks(bind)
    _validate_parent_schema(bind)
    rows = tuple(
        bind.execute(
            sa.text(
                "SELECT id, mobile_hash, mobile_ct, dob_hash, dob_ct, key_version, status "
                "FROM student_registrations ORDER BY id"
            )
        ).mappings()
    )
    if not rows:
        return ()
    ring = _load_migration_keyring()

    authority: dict[str, list[int]] = {}
    # Prove at least one authentic ciphertext per configured source version.
    # Otherwise an all-failure population cannot distinguish a wrong key from
    # corrupt rows and must abort rather than bulk-quarantine.
    for row in rows:
        _canonical_uuid(row["id"])
        if _exact_erased_crypto_tuple(row):
            continue
        values = (
            row["mobile_hash"], row["mobile_ct"], row["dob_hash"], row["dob_ct"],
            row["key_version"], row["status"],
        )
        if not all(isinstance(value, str) for value in values):
            raise _reject()
        if row["status"] == "deleted":
            # Within NYAY-16's identity scope, deleted registrations must have
            # the exact mobile/DOB cryptographic tuple handled above. Broader
            # registration/profile retention is intentionally not audited here.
            raise _reject()
        current_hash = row["dob_hash"]
        if current_hash != _LEGACY_PLACEHOLDER and _HEX_DIGEST.fullmatch(current_hash) is None:
            raise _reject()
        source_version, token = _source_parts(row["dob_ct"], row["key_version"])
        mobile_version, mobile_token = _source_parts(row["mobile_ct"], row["key_version"])
        if mobile_version != source_version:
            raise _reject()
        secret = ring.secrets.get(source_version)
        if secret is None:
            raise _reject()
        counts = authority.setdefault(source_version, [0, 0])
        counts[0] += 1
        if _authenticated_plaintext(token, secret) is not None:
            counts[1] += 1
        counts[0] += 1
        if _authenticated_plaintext(mobile_token, secret) is not None:
            counts[1] += 1
    if any(total < 1 or authentic < 1 for total, authentic in authority.values()):
        raise _reject()

    plan: list[DobHashPlanRow] = []
    for row in rows:
        # SQLite reflects UUID columns as strings, while sa.Uuid DML processors
        # require UUID objects. Canonicalize during planning, before any DDL.
        registration_id = _canonical_uuid(row["id"])
        if _exact_erased_crypto_tuple(row):
            plan.append(DobHashPlanRow(registration_id, "erased"))
            continue
        current_hash = row["dob_hash"]
        is_placeholder = current_hash == _LEGACY_PLACEHOLDER
        source_version, token = _source_parts(row["dob_ct"], row["key_version"])
        mobile_version, mobile_token = _source_parts(row["mobile_ct"], row["key_version"])
        if mobile_version != source_version or _HEX_DIGEST.fullmatch(row["mobile_hash"]) is None:
            raise _reject()
        mobile_raw = _authenticated_plaintext(mobile_token, ring.secrets[mobile_version])
        try:
            mobile_plaintext = mobile_raw.decode("utf-8").strip() if mobile_raw is not None else ""
        except UnicodeDecodeError as exc:
            raise _reject() from exc
        if not mobile_plaintext:
            raise _reject()
        expected_mobile_hash = _lookup_hash(mobile_plaintext, ring)
        mobile_plaintext = None
        if not hmac.compare_digest(row["mobile_hash"], expected_mobile_hash):
            # Every non-erased row supplies an independently persisted lookup
            # verifier. This proves the configured lookup secret even when all
            # historical DOB hashes are placeholders.
            raise _reject()
        raw = _authenticated_plaintext(token, ring.secrets[source_version])
        plaintext, reason = _canonical_date(raw)
        source_digest = hashlib.sha256(row["dob_ct"].encode("utf-8")).hexdigest()
        if plaintext is None:
            if not is_placeholder:
                raise _reject()
            plan.append(
                DobHashPlanRow(
                    registration_id,
                    "quarantined",
                    _quarantine_hash(registration_id),
                    "quarantined",
                    reason,
                    source_version,
                    source_digest,
                )
            )
            continue
        computed_hash = _lookup_hash(plaintext, ring)
        plaintext = None
        if not is_placeholder:
            if not hmac.compare_digest(current_hash, computed_hash):
                raise _reject()
            plan.append(DobHashPlanRow(registration_id, "verified"))
            continue
        plan.append(
            DobHashPlanRow(
                registration_id,
                "verified",
                computed_hash,
                "reconciled",
                "verified_source",
                source_version,
                source_digest,
            )
        )
    return tuple(plan)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    bind = op.get_bind()
    plan = preflight_dob_hash_reconciliation(bind)

    with op.batch_alter_table("student_registrations") as batch:
        batch.add_column(sa.Column("dob_hash_state", sa.String(16), nullable=True))
    op.create_table(
        "registration_dob_reconciliations",
        sa.Column(
            "registration_id",
            _UUID,
            sa.ForeignKey("student_registrations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(40), nullable=False),
        sa.Column("source_key_version", sa.String(8), nullable=False),
        sa.Column("source_ciphertext_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(_RECONCILIATION_OUTCOME_CHECK_SQL, name="outcome"),
        sa.CheckConstraint(_RECONCILIATION_REASON_CHECK_SQL, name="reason_code"),
        sa.CheckConstraint(
            _RECONCILIATION_OUTCOME_REASON_SQL,
            name="outcome_reason",
        ),
        sa.CheckConstraint(
            _RECONCILIATION_SOURCE_DIGEST_SQL,
            name="source_digest_length",
        ),
    )

    registration = sa.table(
        "student_registrations",
        sa.column("id", _UUID),
        sa.column("dob_hash", sa.String(64)),
        sa.column("dob_hash_state", sa.String(16)),
    )
    reconciliation = sa.table(
        "registration_dob_reconciliations",
        sa.column("registration_id", _UUID),
        sa.column("outcome", sa.String(16)),
        sa.column("reason_code", sa.String(40)),
        sa.column("source_key_version", sa.String(8)),
        sa.column("source_ciphertext_sha256", sa.String(64)),
    )
    for row in plan:
        values: dict[str, object] = {"dob_hash_state": row.state}
        if row.replacement_hash is not None:
            values["dob_hash"] = row.replacement_hash
        result = bind.execute(
            registration.update()
            .where(registration.c.id == row.registration_id)
            .values(**values)
        )
        if result.rowcount != 1:
            raise _reject()
        if row.outcome is not None:
            bind.execute(
                reconciliation.insert().values(
                    registration_id=row.registration_id,
                    outcome=row.outcome,
                    reason_code=row.reason_code,
                    source_key_version=row.source_key_version,
                    source_ciphertext_sha256=row.source_ciphertext_sha256,
                )
            )

    with op.batch_alter_table("student_registrations") as batch:
        batch.alter_column(
            "dob_hash_state",
            existing_type=sa.String(16),
            nullable=False,
        )
        batch.create_check_constraint("dob_hash_state", _DOB_HASH_STATE_CHECK_SQL)
        batch.create_check_constraint(
            "dob_hash_state_consistency",
            _DOB_HASH_STATE_CONSISTENCY_SQL,
        )
    op.create_index(
        "ix_student_registrations_dob_hash_state",
        "student_registrations",
        ["dob_hash_state"],
    )


def _validate_downgrade_rows(bind: Connection) -> tuple[sa.RowMapping, ...]:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "registration_dob_reconciliations" not in tables:
        raise _reject()
    columns = {row["name"] for row in inspector.get_columns("student_registrations")}
    if "dob_hash_state" not in columns:
        raise _reject()
    # The pre-0016 application cannot enforce this marker. Block on the
    # authoritative parent table itself so a missing/tampered reconciliation
    # row cannot make a live quarantine disappear during downgrade.
    live_quarantines = bind.scalar(
        sa.text(
            "SELECT count(*) FROM student_registrations "
            "WHERE dob_hash_state='quarantined'"
        )
    )
    if live_quarantines:
        raise _reject()
    rows = tuple(
        bind.execute(
            sa.text(
                "SELECT r.registration_id, r.outcome, r.reason_code, "
                "r.source_key_version, r.source_ciphertext_sha256, "
                "s.id, s.mobile_hash, s.mobile_ct, s.dob_hash, s.dob_hash_state, "
                "s.dob_ct, s.key_version, s.status "
                "FROM registration_dob_reconciliations r "
                "JOIN student_registrations s ON s.id = r.registration_id "
                "ORDER BY r.registration_id"
            )
        ).mappings()
    )
    total = bind.scalar(sa.text("SELECT count(*) FROM registration_dob_reconciliations"))
    if total != len(rows):
        raise _reject()
    active_rows = [row for row in rows if not _exact_erased_crypto_tuple(row)]
    ring = _load_migration_keyring() if any(row["outcome"] == "reconciled" for row in active_rows) else None
    for row in rows:
        outcome = row["outcome"]
        reason = row["reason_code"]
        if outcome not in _OUTCOMES or reason not in _REASON_CODES:
            raise _reject()
        if (outcome == "reconciled") != (reason == "verified_source"):
            raise _reject()
        if _exact_erased_crypto_tuple(row):
            if row["dob_hash_state"] != "erased":
                raise _reject()
            continue
        if hashlib.sha256(row["dob_ct"].encode("utf-8")).hexdigest() != row["source_ciphertext_sha256"]:
            raise _reject()
        source_version, token = _source_parts(row["dob_ct"], row["key_version"])
        if source_version != row["source_key_version"]:
            raise _reject()
        if outcome == "quarantined":
            if (
                row["dob_hash_state"] != "quarantined"
                or row["dob_hash"] != _quarantine_hash(row["id"])
            ):
                raise _reject()
            # The aggregate guard above rejects this before row restoration;
            # retain the row-level validation as defense in depth.
            raise _reject()
        else:
            if ring is None or source_version not in ring.secrets:
                raise _reject()
            plaintext, verified_reason = _canonical_date(
                _authenticated_plaintext(token, ring.secrets[source_version])
            )
            if plaintext is None or verified_reason != "verified_source":
                raise _reject()
            expected_hash = _lookup_hash(plaintext, ring)
            plaintext = None
            if row["dob_hash_state"] != "verified" or not hmac.compare_digest(row["dob_hash"], expected_hash):
                raise _reject()
    return rows


def downgrade() -> None:
    bind = op.get_bind()
    _acquire_preflight_locks(bind, include_reconciliation=True)
    _validate_head_schema_for_downgrade(bind)
    rows = _validate_downgrade_rows(bind)

    # Validation above is complete before any downgrade schema/data mutation.
    # PostgreSQL rolls every subsequent operation back if a row-count invariant
    # fails. SQLite is compatibility-only and has no concurrent writer here.
    with op.batch_alter_table("student_registrations") as batch:
        batch.drop_constraint(
            op.f("ck_student_registrations_dob_hash_state_consistency"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_student_registrations_dob_hash_state"), type_="check"
        )

    registration = sa.table(
        "student_registrations",
        sa.column("id", _UUID),
        sa.column("dob_hash", sa.String(64)),
        sa.column("dob_hash_state", sa.String(16)),
    )
    for row in rows:
        if _exact_erased_crypto_tuple(row):
            continue
        registration_id = _canonical_uuid(row["id"])
        expected_hash = (
            _quarantine_hash(registration_id)
            if row["outcome"] == "quarantined"
            else row["dob_hash"]
        )
        result = bind.execute(
            registration.update()
            .where(
                registration.c.id == registration_id,
                registration.c.dob_hash_state == row["dob_hash_state"],
                registration.c.dob_hash == expected_hash,
            )
            .values(dob_hash=_LEGACY_PLACEHOLDER)
        )
        if result.rowcount != 1:
            raise _reject()

    op.drop_table("registration_dob_reconciliations")
    op.drop_index(
        "ix_student_registrations_dob_hash_state",
        table_name="student_registrations",
    )
    with op.batch_alter_table("student_registrations") as batch:
        batch.drop_column("dob_hash_state")
