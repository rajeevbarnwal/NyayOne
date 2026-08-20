"""Install the durable registration idempotency ledger.

Revision ID: 0018_registration_idempotency
Revises: 0017_registration_invariants

The ledger stores only domain-separated keyed HMACs. Existing raw keys remain
on their historical registration rows and are marked ``legacy`` under the same
write lock that installs a CHECK rejecting post-0018 writes from old binaries.
No request content or legacy fingerprint is reconstructed by this migration.
Deploy during a quiescent writer window: PostgreSQL target-table locks use
``NOWAIT`` and reject sanitized on contention rather than waiting into a runtime
lock-order cycle. This is a version-locked cutover, not rolling old-binary
support: the CHECK rejects an old keyed insert after 0018, but a pre-0018 binary
could still hard-delete an existing legacy raw-key row without creating the
runtime HMAC tombstone.
"""
from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

revision: str = "0018_registration_idempotency"
down_revision: str | None = "0017_registration_invariants"
branch_labels = None
depends_on = None

_REGISTRATIONS = "student_registrations"
_LEDGER = "registration_idempotency_records"
_LEGACY_CHECK = "ck_student_registrations_idempotency_key_legacy"
_IDEMPOTENCY_UNIQUE = "uq_student_registrations_idempotency_key"
_PG_ADVISORY_LOCK_KEY = 4353333856519384234

_KEY_HASH_HEX_SQL = "idempotency_key_hash"
_REQUEST_HASH_HEX_SQL = "request_fingerprint"
for _hex_character in "0123456789abcdef":
    _KEY_HASH_HEX_SQL = (
        f"replace({_KEY_HASH_HEX_SQL}, '{_hex_character}', '')"
    )
    _REQUEST_HASH_HEX_SQL = (
        f"replace({_REQUEST_HASH_HEX_SQL}, '{_hex_character}', '')"
    )

_LEGACY_SQL = (
    "(idempotency_key IS NULL AND idempotency_key_legacy = false) OR "
    "(idempotency_key IS NOT NULL AND idempotency_key_legacy = true)"
)
_KEY_HASH_SQL = (
    "length(idempotency_key_hash) = 64 AND "
    f"length({_KEY_HASH_HEX_SQL}) = 0"
)
_STATE_SQL = "state IN ('pending', 'succeeded', 'failed', 'retired', 'erased')"
_REQUEST_HASH_SQL = (
    "((state IN ('pending', 'succeeded', 'failed') AND "
    "request_fingerprint_version = 'v1' AND "
    "request_fingerprint IS NOT NULL AND "
    "length(request_fingerprint) = 64 AND "
    f"length({_REQUEST_HASH_HEX_SQL}) = 0) OR "
    "(state IN ('retired', 'erased') AND request_fingerprint IS NULL AND "
    "request_fingerprint_version IS NULL))"
)
_STATE_LINKS_SQL = (
    "(state = 'pending' AND registration_id IS NOT NULL AND "
    "outbox_id IS NOT NULL AND outcome_code IS NULL) OR "
    "(state = 'succeeded' AND registration_id IS NOT NULL AND "
    "outbox_id IS NULL AND outcome_code IS NULL) OR "
    "(state = 'failed' AND registration_id IS NULL AND outbox_id IS NULL "
    "AND outcome_code = 'otp_delivery_failed') OR "
    "(state IN ('retired', 'erased') AND registration_id IS NULL AND "
    "outbox_id IS NULL AND outcome_code = 'registration_replay_expired')"
)


class RegistrationIdempotencyMigrationError(RuntimeError):
    """A deliberately non-identifying migration rejection."""


def _reject() -> RegistrationIdempotencyMigrationError:
    return RegistrationIdempotencyMigrationError(
        "NYAY-17 registration idempotency migration rejected unsafe schema or data"
    )


def _acquire_lock(bind: Connection, *, ledger_exists: bool) -> None:
    if bind.dialect.name == "postgresql":
        try:
            bind.execute(sa.text("SET LOCAL lock_timeout = '100ms'"))
            bind.execute(sa.text("SET LOCAL statement_timeout = '30000ms'"))
            bind.execute(
                sa.text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _PG_ADVISORY_LOCK_KEY},
            )
            tables = (
                "registration_idempotency_records, student_registrations"
                if ledger_exists
                else "student_registrations"
            )
            bind.execute(
                sa.text(
                    f"LOCK TABLE {tables} "
                    "IN SHARE ROW EXCLUSIVE MODE NOWAIT"
                )
            )
        except SQLAlchemyError:
            raise _reject() from None
    elif bind.dialect.name == "sqlite":
        # Alembic's SQLite implementation historically treats DDL as
        # non-transactional even though the sqlite3 driver can roll it back
        # once a real DBAPI transaction has begun. Force the transaction before
        # validation or the first batch/DDL statement so any later failure
        # restores every 0018-owned object atomically.
        try:
            driver = bind.connection.driver_connection
            if not driver.in_transaction:
                bind.exec_driver_sql("BEGIN IMMEDIATE")
        except (AttributeError, SQLAlchemyError):
            raise _reject() from None
    else:
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


def _normalise_default(value: object) -> str:
    text, literals = _protect_sql_literals(value)
    text = text.casefold()
    text = re.sub(
        r"::(?:text|character varying|varchar)(?:\([0-9]+\))?",
        "",
        text,
    )
    text = re.sub(r"[\s\"]+", "", text)
    for token, literal in literals.items():
        text = text.replace(token, literal)
    return text


_TOKEN = re.compile(
    r"__literal[0-9]+__|[a-z_][a-z0-9_]*|[0-9]+|<=|>=|<>|!=|=|\(|\)|,|\[|\]"
)


class _CheckParser:
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
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", token):
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
    text = protected.casefold().replace('"', "")
    text = re.sub(
        r"::(?:text|character varying|varchar)(?:\([0-9]+\))?(?:\[\])?",
        "",
        text,
    )
    text = text.replace("[", "(").replace("]", ")")
    # NUL placeholders are inconvenient tokenizer characters; substitute
    # ordinary identifiers while retaining an exact literal-value map.
    literals: dict[str, str] = {}
    for index, (placeholder, literal) in enumerate(literals_by_token.items()):
        token = f"__literal{index}__"
        text = text.replace(placeholder, token)
        literals[token] = literal
    tokens = _TOKEN.findall(text)
    compact_source = re.sub(r"\s+", "", text)
    if "".join(tokens) != compact_source:
        raise ValueError("unsupported CHECK syntax")
    return _CheckParser(tokens, literals).parse()


def _unique_is_exact(inspector: sa.Inspector) -> bool:
    matches = [
        item
        for item in inspector.get_unique_constraints(_REGISTRATIONS)
        if item.get("name") == _IDEMPOTENCY_UNIQUE
    ]
    return len(matches) == 1 and matches[0].get("column_names") == [
        "idempotency_key"
    ]


def _validate_parent_schema(bind: Connection) -> None:
    try:
        inspector = sa.inspect(bind)
        if _REGISTRATIONS not in inspector.get_table_names():
            raise _reject()
        columns = {
            item["name"]: item
            for item in inspector.get_columns(_REGISTRATIONS)
        }
        key = columns.get("idempotency_key")
        if (
            key is None
            or not bool(key.get("nullable"))
            or not _varchar_column_is_exact(key, 200)
            or key.get("default") is not None
            or "idempotency_key_legacy" in columns
            or _LEDGER in inspector.get_table_names()
            or not _unique_is_exact(inspector)
            or any(
                item.get("name") == _LEGACY_CHECK
                for item in inspector.get_check_constraints(_REGISTRATIONS)
            )
        ):
            raise _reject()
    except RegistrationIdempotencyMigrationError:
        raise
    except (SQLAlchemyError, KeyError, TypeError, ValueError):
        raise _reject() from None


def _named_check_ast(inspector: sa.Inspector, table: str, name: str) -> object | None:
    matches = [
        item
        for item in inspector.get_check_constraints(table)
        if item.get("name") == name
    ]
    if len(matches) != 1:
        return None
    return _canonical_check(matches[0].get("sqltext"))


def _named_columns(
    items: list[dict[str, object]],
) -> dict[str, tuple[str, ...]]:
    return {
        str(item["name"]): tuple(str(value) for value in item["column_names"])
        for item in items
        if item.get("name")
    }


def _uuid_column_is_exact(
    bind: Connection, column: dict[str, object]
) -> bool:
    column_type = column.get("type")
    rendered = str(column_type).casefold().replace(" ", "")
    if bind.dialect.name == "postgresql":
        return rendered == "uuid"
    return isinstance(column_type, sa.Uuid) or rendered in {"uuid", "char(32)"}


def _length(column: dict[str, object]) -> int | None:
    return getattr(column.get("type"), "length", None)


def _varchar_column_is_exact(
    column: dict[str, object], length: int
) -> bool:
    """Reject CHAR/TEXT/custom lookalikes even when they expose a length."""

    column_type = column.get("type")
    return isinstance(column_type, sa.VARCHAR) and column_type.length == length


def _default_is_false(column: dict[str, object]) -> bool:
    return _normalise_default(column.get("default")) in {"false", "0"}


def _timestamp_default_is_exact(column: dict[str, object]) -> bool:
    return _normalise_default(column.get("default")) in {
        "current_timestamp",
        "now()",
    }


def _timestamp_type_is_exact(
    bind: Connection, column: dict[str, object]
) -> bool:
    column_type = column.get("type")
    if not isinstance(column_type, sa.DateTime):
        return False
    # SQLite discards timezone metadata during reflection. PostgreSQL retains
    # it and must report TIMESTAMP WITH TIME ZONE exactly.
    return bind.dialect.name != "postgresql" or bool(column_type.timezone)


def _validate_head_schema(bind: Connection) -> None:
    try:
        inspector = sa.inspect(bind)
        if _LEDGER not in inspector.get_table_names():
            raise _reject()
        registration_columns = {
            item["name"]: item
            for item in inspector.get_columns(_REGISTRATIONS)
        }
        legacy = registration_columns.get("idempotency_key_legacy")
        historical_key = registration_columns.get("idempotency_key")
        ledger_columns = {
            item["name"]: item for item in inspector.get_columns(_LEDGER)
        }
        expected_ledger = {
            "id",
            "idempotency_key_hash",
            "request_fingerprint",
            "request_fingerprint_version",
            "state",
            "outcome_code",
            "registration_id",
            "outbox_id",
            "created_at",
            "updated_at",
        }
        primary_key = inspector.get_pk_constraint(_LEDGER)
        raw_uniques = inspector.get_unique_constraints(_LEDGER)
        uniques = _named_columns(raw_uniques)
        expected_uniques = {
            "uq_registration_idempotency_records_idempotency_key_hash": (
                "idempotency_key_hash",
            ),
            "uq_registration_idempotency_records_registration_id": (
                "registration_id",
            ),
            "uq_registration_idempotency_records_outbox_id": ("outbox_id",),
        }
        raw_foreign_keys = inspector.get_foreign_keys(_LEDGER)
        foreign_keys = {
            str(item["name"]): (
                tuple(str(value) for value in item["constrained_columns"]),
                str(item["referred_table"]),
                tuple(str(value) for value in item["referred_columns"]),
                tuple(
                    sorted(
                        (
                            str(key),
                            str(value).upper(),
                        )
                        for key, value in (item.get("options") or {}).items()
                    )
                ),
            )
            for item in raw_foreign_keys
            if item.get("name")
        }
        expected_foreign_keys = {
            "fk_reg_idem_registration": (
                ("registration_id",),
                "student_registrations",
                ("id",),
                (("ondelete", "SET NULL"),),
            ),
            "fk_reg_idem_outbox": (
                ("outbox_id",),
                "otp_outbox",
                ("id",),
                (("ondelete", "SET NULL"),),
            ),
        }
        raw_checks = inspector.get_check_constraints(_LEDGER)
        owned_checks = {
            str(item["name"]): _canonical_check(item.get("sqltext"))
            for item in raw_checks
            if item.get("name")
        }
        expected_checks = {
            "ck_registration_idempotency_records_state": _canonical_check(
                _STATE_SQL
            ),
            "ck_registration_idempotency_records_key_hash_shape": _canonical_check(
                _KEY_HASH_SQL
            ),
            "ck_registration_idempotency_records_request_fingerprint_shape": _canonical_check(
                _REQUEST_HASH_SQL
            ),
            "ck_registration_idempotency_records_state_links": _canonical_check(
                _STATE_LINKS_SQL
            ),
        }
        if (
            legacy is None
            or historical_key is None
            or not bool(historical_key.get("nullable"))
            or not _varchar_column_is_exact(historical_key, 200)
            or historical_key.get("default") is not None
            or not _unique_is_exact(inspector)
            or bool(legacy.get("nullable"))
            or not isinstance(legacy.get("type"), sa.Boolean)
            or not _default_is_false(legacy)
            or set(ledger_columns) != expected_ledger
            or not _uuid_column_is_exact(bind, ledger_columns["id"])
            or bool(ledger_columns["id"].get("nullable"))
            or not _varchar_column_is_exact(
                ledger_columns["idempotency_key_hash"], 64
            )
            or not _varchar_column_is_exact(
                ledger_columns["request_fingerprint"], 64
            )
            or not _varchar_column_is_exact(
                ledger_columns["request_fingerprint_version"], 16
            )
            or not _varchar_column_is_exact(ledger_columns["state"], 24)
            or not _varchar_column_is_exact(
                ledger_columns["outcome_code"], 40
            )
            or bool(ledger_columns["idempotency_key_hash"].get("nullable"))
            or bool(ledger_columns["state"].get("nullable"))
            or not bool(ledger_columns["request_fingerprint"].get("nullable"))
            or not bool(
                ledger_columns["request_fingerprint_version"].get("nullable")
            )
            or not bool(ledger_columns["outcome_code"].get("nullable"))
            or not _uuid_column_is_exact(
                bind, ledger_columns["registration_id"]
            )
            or not _uuid_column_is_exact(bind, ledger_columns["outbox_id"])
            or not bool(ledger_columns["registration_id"].get("nullable"))
            or not bool(ledger_columns["outbox_id"].get("nullable"))
            or any(
                ledger_columns[name].get("default") is not None
                for name in (
                    "id",
                    "idempotency_key_hash",
                    "request_fingerprint",
                    "request_fingerprint_version",
                    "state",
                    "outcome_code",
                    "registration_id",
                    "outbox_id",
                )
            )
            or not _timestamp_type_is_exact(bind, ledger_columns["created_at"])
            or not _timestamp_type_is_exact(bind, ledger_columns["updated_at"])
            or bool(ledger_columns["created_at"].get("nullable"))
            or bool(ledger_columns["updated_at"].get("nullable"))
            or not _timestamp_default_is_exact(ledger_columns["created_at"])
            or not _timestamp_default_is_exact(ledger_columns["updated_at"])
            or str(primary_key.get("name"))
            != "pk_registration_idempotency_records"
            or tuple(primary_key.get("constrained_columns") or ()) != ("id",)
            or len(raw_uniques) != 3
            or any(not item.get("name") for item in raw_uniques)
            or uniques != expected_uniques
            or len(raw_foreign_keys) != 2
            or any(not item.get("name") for item in raw_foreign_keys)
            or foreign_keys != expected_foreign_keys
            or len(raw_checks) != 4
            or any(not item.get("name") for item in raw_checks)
            or owned_checks != expected_checks
            or _named_check_ast(
                inspector, _REGISTRATIONS, _LEGACY_CHECK
            )
            != _canonical_check(_LEGACY_SQL)
        ):
            raise _reject()
    except RegistrationIdempotencyMigrationError:
        raise
    except (SQLAlchemyError, KeyError, TypeError, ValueError):
        raise _reject() from None


def upgrade() -> None:
    bind = op.get_bind()
    _acquire_lock(bind, ledger_exists=False)
    _validate_parent_schema(bind)

    op.add_column(
        _REGISTRATIONS,
        sa.Column(
            "idempotency_key_legacy",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    bind.execute(
        sa.text(
            "UPDATE student_registrations SET idempotency_key_legacy = true "
            "WHERE idempotency_key IS NOT NULL"
        )
    )
    with op.batch_alter_table(_REGISTRATIONS) as batch:
        batch.create_check_constraint("idempotency_key_legacy", _LEGACY_SQL)

    op.create_table(
        _LEDGER,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=True),
        sa.Column("request_fingerprint_version", sa.String(16), nullable=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("outcome_code", sa.String(40), nullable=True),
        sa.Column("registration_id", sa.Uuid(), nullable=True),
        sa.Column("outbox_id", sa.Uuid(), nullable=True),
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
        sa.CheckConstraint(
            _STATE_SQL,
            name="state",
        ),
        sa.CheckConstraint(_KEY_HASH_SQL, name="key_hash_shape"),
        sa.CheckConstraint(
            _REQUEST_HASH_SQL, name="request_fingerprint_shape"
        ),
        sa.CheckConstraint(_STATE_LINKS_SQL, name="state_links"),
        sa.ForeignKeyConstraint(
            ["registration_id"],
            ["student_registrations.id"],
            name="fk_reg_idem_registration",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["outbox_id"],
            ["otp_outbox.id"],
            name="fk_reg_idem_outbox",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id", name="pk_registration_idempotency_records"
        ),
        sa.UniqueConstraint(
            "idempotency_key_hash",
            name="uq_registration_idempotency_records_idempotency_key_hash",
        ),
        sa.UniqueConstraint(
            "registration_id",
            name="uq_registration_idempotency_records_registration_id",
        ),
        sa.UniqueConstraint(
            "outbox_id",
            name="uq_registration_idempotency_records_outbox_id",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    _acquire_lock(bind, ledger_exists=True)
    _validate_head_schema(bind)
    try:
        has_ledger = bind.scalar(
            sa.text("SELECT 1 FROM registration_idempotency_records LIMIT 1")
        )
        has_legacy_key = bind.scalar(
            sa.text(
                "SELECT 1 FROM student_registrations "
                "WHERE idempotency_key IS NOT NULL LIMIT 1"
            )
        )
    except SQLAlchemyError:
        raise _reject() from None
    if has_ledger is not None or has_legacy_key is not None:
        # 0017 replayed keys without comparing request content. Never remove the
        # ledger protection while any historical or v1 reservation survives.
        raise _reject()

    op.drop_table(_LEDGER)
    with op.batch_alter_table(_REGISTRATIONS) as batch:
        batch.drop_constraint(op.f(_LEGACY_CHECK), type_="check")
        batch.drop_column("idempotency_key_legacy")
