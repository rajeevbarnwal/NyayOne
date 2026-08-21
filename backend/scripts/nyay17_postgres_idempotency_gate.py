"""NYAY-17 PostgreSQL 16 registration-idempotency release gate.

The ordinary unit suite cannot establish PostgreSQL unique-conflict ordering,
transaction visibility, or concurrent delivery cardinality.  This opt-in gate
therefore accepts only an explicit query-free loopback PostgreSQL control URL,
creates disposable databases, migrates them through the pinned 0017/0018
lifecycle, exercises the real registration HTTP route, and removes every
scratch database in ``finally`` blocks.

The emitted JSON is aggregate evidence only.  It contains assertion names,
status codes, counts, and booleans; it never contains database URLs/names,
request fields or values, idempotency keys, canonical bytes, fingerprints,
UUIDs, OTPs, ciphertext, email addresses, mobile numbers, or DOB values.

Exit codes:

* 0: every exact oracle, negative control, privacy scan, and cleanup passed;
* 1: a product, harness, privacy, or cleanup assertion failed;
* 78: the pinned PostgreSQL 16 + pgvector runtime was unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from collections import Counter
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import (
    Boolean,
    DateTime,
    Uuid,
    VARCHAR,
    create_engine,
    inspect,
    make_url,
    select,
    text,
)
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

BLOCKED_EXIT = 78
PREVIOUS_REVISION = "0017_registration_invariants"
PINNED_HEAD = "0018_registration_idempotency"
# Historical NYAY-17 migration lifecycle remains sealed at 0018. Current ORM,
# routes and services must instead execute on the repository head, including
# the OTP-authority and auth-retention lifecycle contracts added after 0018.
APPLICATION_HEAD = "0020_auth_retention_lifecycle"
REGISTER_PATH = "/api/v1/auth/student/register"
RECENT_PROBE_HISTORY_AGE_DAYS = 2
PENDING_RETENTION_TARGET_AGE_DAYS = 400
PENDING_RETENTION_CUTOFF_DAYS = 365

LIBPQ_AMBIENT_KEYS = frozenset(
    {
        "PGHOST",
        "PGHOSTADDR",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
        "PGPASSFILE",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGOPTIONS",
        "PGCONNECT_TIMEOUT",
        "PGTARGETSESSIONATTRS",
    }
)

CANONICAL_FIELD_PATHS = (
    "first_name",
    "middle_name",
    "last_name",
    "mobile",
    "dob",
    "consent.accepted",
    "consent.policy_version",
    "college",
    "year_of_study",
    "enrolment_number",
    "institutional_email",
    "bar_enrolment_number",
)

REQUIRED_ASSERTION_IDS = (
    "RUNTIME-POSTGRES-16-PGVECTOR",
    "RUNTIME-ALEMBIC-PINNED-HEAD",
    "MIGRATION-0017-0018-ROUNDTRIP-PRESERVES-NOKEY-ROW",
    "MIGRATION-0018-DOWNGRADE-KEYED-REFUSAL-IMMUTABLE",
    "SCHEMA-LEDGER-EXACT-STATE-INVENTORY",
    "CONTRACT-IDEMPOTENCY-KEY-BOUNDARY",
    "CONTRACT-EXACT-REPLAY-STABLE",
    "CONTRACT-CANONICAL-EQUIVALENTS-REPLAY",
    "CONTRACT-EVERY-CANONICAL-FIELD-CONFLICTS",
    "CONTRACT-LEGACY-UNVERIFIABLE-CONFLICT",
    "CONTRACT-ACTIVATION-RETIRES-REPLAY-UNIFORM",
    "CONTRACT-RETENTION-ERASED-TOMBSTONE-UNIFORM",
    "CONTRACT-PENDING-CRASH-RESUMES-ONCE",
    "CONTRACT-FAILED-DELIVERY-REPLAY-STABLE",
    "CONCURRENCY-EIGHT-SAME-CONTENT-ONE-GRAPH",
    "CONCURRENCY-MISMATCHED-ONE-WINNER-TYPED-CONFLICT",
    "CONCURRENCY-FAILED-LOSER-WAITS-FOR-FINAL-OUTCOME",
    "CONTRACT-EXACT-INTEGRITY-CONSTRAINT-TRANSLATION",
    "MUTANTS-IDEMPOTENCY-ORACLE",
    "HARNESS-AGGREGATE-PRIVACY",
)

# Transactional business graph.  The independent idempotency ledger table is
# discovered by its pinned schema name in the product probes once 0018 is live.
REGISTRATION_GRAPH_TABLES = (
    "users",
    "student_registrations",
    "student_profiles",
    "student_verifications",
    "guardian_consents",
    "consents",
    "otp_challenges",
    "otp_outbox",
    "audit_events",
)

_UUID_TEXT = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_EMAIL_TEXT = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_MOBILE_TEXT = re.compile(r"(?<!\d)\d{10}(?!\d)")
_DATE_TEXT = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_URL_TEXT = re.compile(r"(?i)\b(?:postgres(?:ql)?|https?)\+?[^\s:]*://")
_HEX64_TEXT = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "database_url",
        "scratch_database",
        "idempotency_key",
        "canonical_request",
        "canonical_payload",
        "request_fingerprint",
        "fingerprint_key",
        "payload",
        "first_name",
        "middle_name",
        "last_name",
        "mobile",
        "dob",
        "policy_version",
        "college",
        "year_of_study",
        "enrolment_number",
        "institutional_email",
        "bar_enrolment_number",
        "registration_id",
        "user_id",
        "otp",
        "code",
        "ciphertext",
    }
)

_LEDGER_STATE_SQL = "state IN ('pending', 'succeeded', 'failed', 'retired', 'erased')"
_LEDGER_KEY_HASH_HEX_SQL = "idempotency_key_hash"
_LEDGER_REQUEST_HASH_HEX_SQL = "request_fingerprint"
for _hex_character in "0123456789abcdef":
    _LEDGER_KEY_HASH_HEX_SQL = (
        f"replace({_LEDGER_KEY_HASH_HEX_SQL}, '{_hex_character}', '')"
    )
    _LEDGER_REQUEST_HASH_HEX_SQL = (
        f"replace({_LEDGER_REQUEST_HASH_HEX_SQL}, '{_hex_character}', '')"
    )
_LEDGER_KEY_HASH_SQL = (
    f"length(idempotency_key_hash) = 64 AND length({_LEDGER_KEY_HASH_HEX_SQL}) = 0"
)
_LEDGER_REQUEST_HASH_SQL = (
    "((state IN ('pending', 'succeeded', 'failed') AND "
    "request_fingerprint_version = 'v1' AND "
    "request_fingerprint IS NOT NULL AND "
    "length(request_fingerprint) = 64 AND "
    f"length({_LEDGER_REQUEST_HASH_HEX_SQL}) = 0) OR "
    "(state IN ('retired', 'erased') AND request_fingerprint IS NULL AND "
    "request_fingerprint_version IS NULL))"
)
_LEDGER_STATE_LINKS_SQL = (
    "(state = 'pending' AND registration_id IS NOT NULL AND "
    "outbox_id IS NOT NULL AND outcome_code IS NULL) OR "
    "(state = 'succeeded' AND registration_id IS NOT NULL AND "
    "outbox_id IS NULL AND outcome_code IS NULL) OR "
    "(state = 'failed' AND registration_id IS NULL AND outbox_id IS NULL "
    "AND outcome_code = 'otp_delivery_failed') OR "
    "(state IN ('retired', 'erased') AND registration_id IS NULL AND "
    "outbox_id IS NULL AND outcome_code = 'registration_replay_expired')"
)
_REGISTRATION_LEGACY_SQL = (
    "(idempotency_key IS NULL AND idempotency_key_legacy = false) OR "
    "(idempotency_key IS NOT NULL AND idempotency_key_legacy = true)"
)


class Blocked(RuntimeError):
    """A required target-runtime prerequisite is absent; never a pass."""


class ScratchCleanupFailure(RuntimeError):
    """A disposable database could not be removed; always fatal."""


class ProductGateFailure(RuntimeError):
    """A product or migration assertion failed on the target runtime."""


def _reject_ambient_libpq_environment(
    environment: Mapping[str, str] | None = None,
) -> None:
    """Reject ambient libpq authority without copying any value."""

    source = os.environ if environment is None else environment
    if any(key in LIBPQ_AMBIENT_KEYS or key.startswith("PGSSL") for key in source):
        raise Blocked("ambient libpq routing or credential environment is not allowed")


def _safe_local_postgres_url(raw: str) -> URL:
    """Accept only an unambiguous query-free loopback PostgreSQL URL."""

    _reject_ambient_libpq_environment()
    if "://" not in raw:
        raise Blocked("a valid PostgreSQL URL is required")
    authority = re.split(r"[/?#]", raw.split("://", 1)[1], maxsplit=1)[0]
    if "%" in authority or authority.count("@") > 1:
        raise Blocked("the PostgreSQL URL authority is ambiguous")
    try:
        url = make_url(raw)
    except Exception as exc:  # noqa: BLE001 - supplied URL stays private
        raise Blocked("a valid PostgreSQL URL is required") from exc
    if url.get_backend_name() != "postgresql":
        raise Blocked("a PostgreSQL URL is required")
    if url.query:
        raise Blocked("the scratch-database gate rejects PostgreSQL URL queries")
    host = (url.host or "").casefold()
    if host == "localhost":
        return url
    try:
        if ipaddress.ip_address(host).is_loopback:
            return url
    except ValueError:
        pass
    raise Blocked("the scratch-database gate accepts loopback PostgreSQL only")


def _database_url(base: URL, database: str) -> str:
    return base.set(database=database).render_as_string(hide_password=False)


def _admin_execute(base: URL, statement: str) -> None:
    engine = create_engine(
        _database_url(base, "postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text(statement))
    finally:
        engine.dispose()


def _drop_scratch(base: URL, name: str) -> None:
    try:
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:  # pragma: no cover - fallback for old compatible servers
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}"')


def _create_scratch(base: URL, name: str) -> str:
    try:
        _drop_scratch(base, name)
        _admin_execute(base, f'CREATE DATABASE "{name}"')
    except Exception as exc:  # noqa: BLE001 - sanitized prerequisite failure
        raise Blocked("could not create the disposable scratch database") from exc
    return _database_url(base, name)


def _scratch_database_inventory(base: URL) -> set[str]:
    """Keep the private NYAY-17 scratch-name set in memory only."""

    engine = create_engine(_database_url(base, "postgres"), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return {
                str(value)
                for value in connection.scalars(
                    text(
                        "SELECT datname FROM pg_database "
                        "WHERE datname LIKE 'nyay17_idem_%'"
                    )
                )
            }
    finally:
        engine.dispose()


class _ScratchDatabaseManager:
    """Own disposable databases and make cleanup part of the verdict."""

    def __init__(self, base: URL) -> None:
        self.base = base
        self.records: list[dict[str, Any]] = []
        self._owned_names: set[str] = set()
        try:
            self._baseline_inventory = _scratch_database_inventory(base)
        except Exception as exc:  # noqa: BLE001 - sanitized authority failure
            raise Blocked("could not inventory disposable scratch databases") from exc

    def run(self, purpose: str, operation: Callable[[str], Any]) -> Any:
        name = f"nyay17_idem_{uuid.uuid4().hex[:12]}"
        record: dict[str, Any] = {
            "purpose": purpose,
            "created": False,
            "cleanup": "NOT_CREATED",
        }
        self.records.append(record)
        self._owned_names.add(name)
        scratch_url = _create_scratch(self.base, name)
        record["created"] = True
        try:
            return operation(scratch_url)
        finally:
            try:
                _drop_scratch(self.base, name)
            except Exception as exc:  # noqa: BLE001 - fatal, sanitized cleanup
                record["cleanup"] = "FAIL"
                raise ScratchCleanupFailure(
                    "a disposable NYAY-17 database could not be removed"
                ) from exc
            try:
                if name in _scratch_database_inventory(self.base):
                    raise ScratchCleanupFailure(
                        "a disposable NYAY-17 database remained after cleanup"
                    )
            except ScratchCleanupFailure:
                record["cleanup"] = "FAIL"
                raise
            except Exception as exc:  # noqa: BLE001 - sanitized cleanup oracle
                record["cleanup"] = "FAIL"
                raise ScratchCleanupFailure(
                    "NYAY-17 scratch cleanup inventory could not be verified"
                ) from exc
            record["cleanup"] = "PASS"

    @property
    def scratch_created(self) -> bool:
        return any(record["created"] for record in self.records)

    def summary(self) -> dict[str, Any]:
        created = sum(record["created"] is True for record in self.records)
        removed = sum(record["cleanup"] == "PASS" for record in self.records)
        failed = sum(record["cleanup"] == "FAIL" for record in self.records)
        try:
            final_inventory = _scratch_database_inventory(self.base)
            inventory_match = bool(
                final_inventory == self._baseline_inventory
                and not self._owned_names.intersection(final_inventory)
            )
            final_count = len(final_inventory)
        except Exception:  # noqa: BLE001 - summary must fail closed
            inventory_match = False
            final_count = -1
        return {
            "created": created,
            "removed": removed,
            "cleanup_failed": failed,
            "all_created_removed": (
                created == removed and failed == 0 and inventory_match
            ),
            "inventory_match": inventory_match,
            "baseline_count": len(self._baseline_inventory),
            "final_count": final_count,
            "purposes": [record["purpose"] for record in self.records],
        }


def _run_alembic(scratch_url: str, *arguments: str) -> dict[str, Any]:
    """Run Alembic while retaining no stdout, stderr, URL, or database name."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env={**os.environ, "APP_ENV": "testing", "DATABASE_URL": scratch_url},
        capture_output=True,
        text=True,
        timeout=240,
    )
    return {"arguments": list(arguments), "returncode": result.returncode}


def _schema_digest(engine: Engine, tables: tuple[str, ...]) -> str:
    """Internal exact schema oracle; its digest never enters evidence."""

    inspector = inspect(engine)
    snapshot: list[Any] = []
    available = set(inspector.get_table_names())
    for table in tables:
        if table not in available:
            snapshot.append((table, "absent"))
            continue
        snapshot.append(
            (
                table,
                tuple(
                    (
                        column["name"],
                        str(column["type"]),
                        bool(column["nullable"]),
                        str(column.get("default")),
                    )
                    for column in inspector.get_columns(table)
                ),
                tuple(
                    sorted(
                        (
                            item.get("name"),
                            tuple(item.get("column_names") or ()),
                        )
                        for item in inspector.get_unique_constraints(table)
                    )
                ),
                tuple(
                    sorted(
                        (item.get("name"), item.get("sqltext"))
                        for item in inspector.get_check_constraints(table)
                    )
                ),
                tuple(
                    sorted(
                        (
                            item.get("name"),
                            bool(item.get("unique")),
                            tuple(item.get("column_names") or ()),
                        )
                        for item in inspector.get_indexes(table)
                    )
                ),
                (
                    inspector.get_pk_constraint(table).get("name"),
                    tuple(
                        inspector.get_pk_constraint(table).get("constrained_columns")
                        or ()
                    ),
                ),
                tuple(
                    sorted(
                        (
                            item.get("name"),
                            tuple(item.get("constrained_columns") or ()),
                            item.get("referred_schema"),
                            item.get("referred_table"),
                            tuple(item.get("referred_columns") or ()),
                            tuple(
                                sorted(
                                    (str(key), str(value).upper())
                                    for key, value in (
                                        item.get("options") or {}
                                    ).items()
                                )
                            ),
                        )
                        for item in inspector.get_foreign_keys(table)
                    )
                ),
            )
        )
    return hashlib.sha256(repr(snapshot).encode("utf-8")).hexdigest()


def _row_projection_digest(
    engine: Engine,
    table: str,
    columns: tuple[str, ...],
) -> str:
    """Internal equality oracle over a stable historical column projection."""

    quoted = ", ".join(f'"{column}"' for column in columns)
    with engine.connect() as connection:
        rows = [
            tuple(row)
            for row in connection.execute(
                text(f'SELECT {quoted} FROM "{table}" ORDER BY 1')
            )
        ]
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        value = connection.scalar(text("SELECT version_num FROM alembic_version"))
    return str(value) if value is not None else None


def _seed_0017_registration(
    engine: Engine, *, raw_idempotency_key: str | None
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert one constraint-valid synthetic 0017 row without ORM drift."""

    user_id = uuid.uuid4()
    registration_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, role, status) "
                "VALUES (:id, 'student', 'pending')"
            ),
            {"id": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO student_registrations "
                "(id, user_id, first_name, middle_name, last_name, "
                "mobile_hash, mobile_ct, dob_hash, dob_ct, dob_hash_state, "
                "key_version, institution_ref, status, is_minor, "
                "idempotency_key) VALUES "
                "(:id, :user_id, 'Synthetic', NULL, 'Lifecycle', :mobile_hash, "
                "'[sealed]', :dob_hash, '[sealed]', 'verified', 'v1', NULL, "
                "'otp_pending', false, :idempotency_key)"
            ),
            {
                "id": registration_id,
                "user_id": user_id,
                "mobile_hash": hashlib.sha256(
                    registration_id.bytes + b"mobile"
                ).hexdigest(),
                "dob_hash": hashlib.sha256(registration_id.bytes + b"dob").hexdigest(),
                "idempotency_key": raw_idempotency_key,
            },
        )
    return user_id, registration_id


def _canonical_schema_check(value: object) -> object:
    """Parse reflected IN/ANY CHECKs while preserving literal boundaries."""

    migration = importlib.import_module(
        "app.db.migrations.versions.0018_registration_idempotency"
    )
    return migration._canonical_check(value)


def _canonical_schema_default(value: object) -> str:
    """Canonicalize only casts/spacing, retaining exact default semantics."""

    migration = importlib.import_module(
        "app.db.migrations.versions.0018_registration_idempotency"
    )
    return migration._normalise_default(value)


def _named_column_constraints(
    items: list[dict[str, Any]],
) -> dict[str, tuple[str, ...]]:
    return {
        str(item["name"]): tuple(str(value) for value in item["column_names"])
        for item in items
        if item.get("name")
    }


def _migration_inventory_passes(engine: Engine) -> bool:
    """Independently validate every owned 0018 definition, not just names."""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    ledger_table = "registration_idempotency_records"
    registration_table = "student_registrations"
    if ledger_table not in tables or registration_table not in tables:
        return False
    registration_columns = {
        item["name"]: item for item in inspector.get_columns(registration_table)
    }
    ledger_columns = {
        item["name"]: item for item in inspector.get_columns(ledger_table)
    }
    expected_columns = {
        "id": (Uuid, None, False),
        "idempotency_key_hash": (VARCHAR, 64, False),
        "request_fingerprint": (VARCHAR, 64, True),
        "request_fingerprint_version": (VARCHAR, 16, True),
        "state": (VARCHAR, 24, False),
        "outcome_code": (VARCHAR, 40, True),
        "registration_id": (Uuid, None, True),
        "outbox_id": (Uuid, None, True),
        "created_at": (DateTime, None, False),
        "updated_at": (DateTime, None, False),
    }
    if set(ledger_columns) != set(expected_columns):
        return False
    for name, (expected_type, expected_length, nullable) in expected_columns.items():
        column = ledger_columns[name]
        column_type = column.get("type")
        if not isinstance(column_type, expected_type):
            return False
        if (
            expected_length is not None
            and getattr(column_type, "length", None) != expected_length
        ):
            return False
        if bool(column.get("nullable")) is not nullable:
            return False
        if isinstance(column_type, DateTime):
            if not bool(column_type.timezone) or _canonical_schema_default(
                column.get("default")
            ) not in {"now()", "current_timestamp"}:
                return False
        elif column.get("default") is not None:
            return False

    legacy = registration_columns.get("idempotency_key_legacy")
    raw_key = registration_columns.get("idempotency_key")
    if (
        legacy is None
        or not isinstance(legacy.get("type"), Boolean)
        or bool(legacy.get("nullable"))
        or _canonical_schema_default(legacy.get("default")) not in {"false", "0"}
        or raw_key is None
        or not isinstance(raw_key.get("type"), VARCHAR)
        or getattr(raw_key.get("type"), "length", None) != 200
        or not bool(raw_key.get("nullable"))
        or raw_key.get("default") is not None
    ):
        return False

    pk = inspector.get_pk_constraint(ledger_table)
    if pk.get("name") != "pk_registration_idempotency_records" or tuple(
        pk.get("constrained_columns") or ()
    ) != ("id",):
        return False
    raw_uniques = inspector.get_unique_constraints(ledger_table)
    uniques = _named_column_constraints(raw_uniques)
    if (
        len(raw_uniques) != 3
        or any(not item.get("name") for item in raw_uniques)
        or uniques
        != {
            "uq_registration_idempotency_records_idempotency_key_hash": (
                "idempotency_key_hash",
            ),
            "uq_registration_idempotency_records_registration_id": ("registration_id",),
            "uq_registration_idempotency_records_outbox_id": ("outbox_id",),
        }
    ):
        return False
    registration_unique_matches = [
        item
        for item in inspector.get_unique_constraints(registration_table)
        if item.get("name") == "uq_student_registrations_idempotency_key"
    ]
    if not (
        len(registration_unique_matches) == 1
        and tuple(registration_unique_matches[0].get("column_names") or ())
        == ("idempotency_key",)
    ):
        return False

    raw_foreign_keys = inspector.get_foreign_keys(ledger_table)
    foreign_keys = {
        str(item["name"]): (
            tuple(str(value) for value in item["constrained_columns"]),
            item.get("referred_schema"),
            str(item["referred_table"]),
            tuple(str(value) for value in item["referred_columns"]),
            tuple(
                sorted(
                    (str(key), str(value).upper())
                    for key, value in (item.get("options") or {}).items()
                )
            ),
        )
        for item in raw_foreign_keys
        if item.get("name")
    }
    if (
        len(raw_foreign_keys) != 2
        or any(not item.get("name") for item in raw_foreign_keys)
        or foreign_keys
        != {
            "fk_reg_idem_registration": (
                ("registration_id",),
                None,
                "student_registrations",
                ("id",),
                (("ondelete", "SET NULL"),),
            ),
            "fk_reg_idem_outbox": (
                ("outbox_id",),
                None,
                "otp_outbox",
                ("id",),
                (("ondelete", "SET NULL"),),
            ),
        }
    ):
        return False

    ledger_check_items = inspector.get_check_constraints(ledger_table)
    registration_check_items = inspector.get_check_constraints(registration_table)
    try:
        checks = {
            str(item["name"]): _canonical_schema_check(item.get("sqltext"))
            for item in ledger_check_items
            if item.get("name")
        }
        expected_checks = {
            "ck_registration_idempotency_records_state": (
                _canonical_schema_check(_LEDGER_STATE_SQL)
            ),
            "ck_registration_idempotency_records_key_hash_shape": (
                _canonical_schema_check(_LEDGER_KEY_HASH_SQL)
            ),
            "ck_registration_idempotency_records_request_fingerprint_shape": (
                _canonical_schema_check(_LEDGER_REQUEST_HASH_SQL)
            ),
            "ck_registration_idempotency_records_state_links": (
                _canonical_schema_check(_LEDGER_STATE_LINKS_SQL)
            ),
        }
        legacy_matches = [
            item
            for item in registration_check_items
            if item.get("name") == "ck_student_registrations_idempotency_key_legacy"
        ]
        legacy_check_exact = bool(
            len(legacy_matches) == 1
            and _canonical_schema_check(legacy_matches[0].get("sqltext"))
            == _canonical_schema_check(_REGISTRATION_LEGACY_SQL)
        )
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        len(ledger_check_items) == 4
        and all(item.get("name") for item in ledger_check_items)
        and len(checks) == 4
        and checks == expected_checks
        and legacy_check_exact
        and "idempotency_key" not in ledger_columns
    )


def _run_migration_lifecycle(scratch_url: str) -> dict[str, Any]:
    """Exercise populated 0017↔0018 safety plus mixed-writer rejection."""

    first_upgrade = _run_alembic(scratch_url, "upgrade", PREVIOUS_REVISION)
    if first_upgrade["returncode"] != 0:
        raise ProductGateFailure("migration to the pinned parent failed")
    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        inspector = inspect(engine)
        historical_columns = tuple(
            item["name"] for item in inspector.get_columns("student_registrations")
        )
        _, registration_id = _seed_0017_registration(engine, raw_idempotency_key=None)
        schema_17 = _schema_digest(
            engine, ("student_registrations", "registration_idempotency_records")
        )
        row_17 = _row_projection_digest(
            engine, "student_registrations", historical_columns
        )

        upgrade_head = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        if upgrade_head["returncode"] != 0:
            raise ProductGateFailure("migration to the pinned head failed")
        schema_inventory = bool(
            _current_revision(engine) == PINNED_HEAD
            and _migration_inventory_passes(engine)
        )
        schema_18 = _schema_digest(
            engine, ("student_registrations", "registration_idempotency_records")
        )
        first_projection_preserved = (
            _row_projection_digest(engine, "student_registrations", historical_columns)
            == row_17
        )
        with engine.connect() as connection:
            no_key_marker = connection.execute(
                text(
                    "SELECT idempotency_key, idempotency_key_legacy "
                    "FROM student_registrations WHERE id = :id"
                ),
                {"id": registration_id},
            ).one()
            ledger_empty = (
                int(
                    connection.scalar(
                        text("SELECT count(*) FROM registration_idempotency_records")
                    )
                    or 0
                )
                == 0
            )

        downgrade = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        roundtrip_17 = bool(
            downgrade["returncode"] == 0
            and _current_revision(engine) == PREVIOUS_REVISION
            and _schema_digest(
                engine,
                ("student_registrations", "registration_idempotency_records"),
            )
            == schema_17
            and _row_projection_digest(
                engine, "student_registrations", historical_columns
            )
            == row_17
        )
        reupgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        roundtrip_18 = bool(
            reupgrade["returncode"] == 0
            and _current_revision(engine) == PINNED_HEAD
            and _schema_digest(
                engine,
                ("student_registrations", "registration_idempotency_records"),
            )
            == schema_18
            and _row_projection_digest(
                engine, "student_registrations", historical_columns
            )
            == row_17
        )

        # A hash-only terminal tombstone is independently sufficient to block
        # downgrade.  Snapshot both complete owned tables and their definition
        # so a rejected downgrade cannot false-green after partial DDL/DML.
        tombstone_id = uuid.uuid4()
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO registration_idempotency_records "
                    "(id, idempotency_key_hash, request_fingerprint, "
                    "request_fingerprint_version, state, outcome_code, "
                    "registration_id, outbox_id) VALUES "
                    "(:id, :key_hash, NULL, NULL, 'erased', "
                    "'registration_replay_expired', NULL, NULL)"
                ),
                {"id": tombstone_id, "key_hash": "3" * 64},
            )
        tombstone_schema = _schema_digest(
            engine, ("student_registrations", "registration_idempotency_records")
        )
        tombstone_state = _database_state_digest(
            engine, ("student_registrations", "registration_idempotency_records")
        )
        tombstone_rejection = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        ledger_downgrade_refused_unchanged = bool(
            tombstone_rejection["returncode"] != 0
            and _current_revision(engine) == PINNED_HEAD
            and _schema_digest(
                engine,
                ("student_registrations", "registration_idempotency_records"),
            )
            == tombstone_schema
            and _database_state_digest(
                engine,
                ("student_registrations", "registration_idempotency_records"),
            )
            == tombstone_state
        )
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM registration_idempotency_records WHERE id = :id"),
                {"id": tombstone_id},
            )

        # Return to 0017, simulate a historical raw key, then prove 0018 marks
        # it explicitly.  The raw value stays in memory and never enters evidence.
        back_again = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        if back_again["returncode"] != 0:
            raise ProductGateFailure("clean second downgrade failed")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE student_registrations SET idempotency_key = :value "
                    "WHERE id = :id"
                ),
                {"value": "synthetic-legacy-wire-token", "id": registration_id},
            )
        legacy_upgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        with engine.connect() as connection:
            legacy_marked = bool(
                connection.scalar(
                    text(
                        "SELECT idempotency_key_legacy "
                        "FROM student_registrations WHERE id = :id"
                    ),
                    {"id": registration_id},
                )
            )
        guarded_schema = _schema_digest(
            engine, ("student_registrations", "registration_idempotency_records")
        )
        guarded_state = _database_state_digest(
            engine, ("student_registrations", "registration_idempotency_records")
        )
        rejected_downgrade = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        legacy_downgrade_refused_unchanged = bool(
            rejected_downgrade["returncode"] != 0
            and _current_revision(engine) == PINNED_HEAD
            and _schema_digest(
                engine,
                ("student_registrations", "registration_idempotency_records"),
            )
            == guarded_schema
            and _database_state_digest(
                engine,
                ("student_registrations", "registration_idempotency_records"),
            )
            == guarded_state
        )

        # At 0018 an old writer omitting the marker must fail the named CHECK.
        mixed_writer_rejected = False
        mixed_constraint_exact = False
        try:
            _seed_0017_registration(
                engine, raw_idempotency_key="synthetic-old-writer-token"
            )
        except IntegrityError as exc:
            mixed_writer_rejected = True
            mixed_constraint_exact = (
                getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                == "ck_student_registrations_idempotency_key_legacy"
            )

        return {
            "schema_inventory": schema_inventory,
            "first_projection_preserved": first_projection_preserved,
            "no_key_marker_false": no_key_marker[0] is None
            and no_key_marker[1] is False,
            "ledger_empty": ledger_empty,
            "roundtrip_17": roundtrip_17,
            "roundtrip_18": roundtrip_18,
            "legacy_upgrade": legacy_upgrade["returncode"] == 0,
            "legacy_marked": legacy_marked,
            "ledger_downgrade_refused_unchanged": (ledger_downgrade_refused_unchanged),
            "legacy_downgrade_refused_unchanged": (legacy_downgrade_refused_unchanged),
            "mixed_writer_rejected": mixed_writer_rejected,
            "mixed_constraint_exact": mixed_constraint_exact,
        }
    finally:
        engine.dispose()


def _safe_response_signature(response: Any) -> dict[str, Any]:
    """Retain only status and a typed error code, never response values."""

    signature: dict[str, Any] = {"status_code": int(response.status_code)}
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - non-JSON is represented by shape only
        signature["shape"] = "non_json"
        return signature
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        error_code = detail.get("code")
        error_field = detail.get("field")
        signature["shape"] = "typed_detail"
        signature["error_code"] = (
            error_code if isinstance(error_code, str) else "absent"
        )
        signature["error_field"] = (
            error_field if isinstance(error_field, str) else "absent"
        )
    elif isinstance(detail, list):
        signature["shape"] = "validation"
        signature["error_count"] = len(detail)
    elif isinstance(body, dict):
        signature["shape"] = "object"
    else:
        signature["shape"] = "other_json"
    return signature


def _privacy_findings(value: Any) -> list[str]:
    """Return aggregate finding classes without retaining offending material."""

    findings: list[str] = []

    def scan(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).casefold() in _FORBIDDEN_REPORT_KEYS:
                    findings.append("forbidden_key")
                scan(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                scan(child)
        elif isinstance(item, str):
            for label, pattern in (
                ("uuid", _UUID_TEXT),
                ("email", _EMAIL_TEXT),
                ("mobile", _MOBILE_TEXT),
                ("date", _DATE_TEXT),
                ("url", _URL_TEXT),
                ("hex64", _HEX64_TEXT),
            ):
                if pattern.search(item):
                    findings.append(label)

    scan(value)
    return sorted(findings)


def _assertion(identifier: str, passed: bool, **metrics: Any) -> dict[str, Any]:
    return {"id": identifier, "passed": bool(passed), "metrics": metrics}


def _is_postgresql_16_with_pgvector(
    server_version_num: int, vector_version: object
) -> bool:
    return 160000 <= server_version_num < 170000 and bool(vector_version)


def _activation_route_state_is_exact(status: object) -> bool:
    """The real verify route finishes NYAY-2 session rotation at ``active``."""

    return status == "active"


def _backend_cardinality_is_exact(observed: int, expected: int) -> bool:
    """Pin the worker snapshot taken before diagnostic follow-up requests."""

    return observed == expected


def _invalid_key_error_is_exact(exc: Any, candidate: str) -> bool:
    """Require typed rejection without echoing any non-empty wire value."""

    return bool(
        exc.status_code == 422
        and exc.code == "invalid_idempotency_key"
        and exc.field == "Idempotency-Key"
        and (candidate == "" or candidate not in str(exc))
    )


def _evaluate_assertions(assertions: list[dict[str, Any]]) -> dict[str, Any]:
    """Fail closed on omissions, substitutions, duplicates, order, or false."""

    identifiers = [
        item.get("id") if isinstance(item.get("id"), str) else "<invalid>"
        for item in assertions
    ]
    counts = Counter(identifiers)
    missing = sum(item not in identifiers for item in REQUIRED_ASSERTION_IDS)
    extra = sum(item not in REQUIRED_ASSERTION_IDS for item in identifiers)
    duplicate = sum(max(0, count - 1) for count in counts.values())
    reordered = bool(
        missing == 0
        and extra == 0
        and duplicate == 0
        and tuple(identifiers) != REQUIRED_ASSERTION_IDS
    )
    exact_inventory = tuple(identifiers) == REQUIRED_ASSERTION_IDS
    passed = sum(
        item.get("id") in REQUIRED_ASSERTION_IDS and item.get("passed") is True
        for item in assertions
    )
    failed = sorted(
        str(item.get("id"))
        for item in assertions
        if item.get("id") in REQUIRED_ASSERTION_IDS and item.get("passed") is not True
    )
    return {
        "exact_inventory": exact_inventory,
        "required": len(REQUIRED_ASSERTION_IDS),
        "passed": passed,
        "failed": failed,
        "inventory_failures": {
            "missing": missing,
            "extra": extra,
            "duplicate": duplicate,
            "reordered": reordered,
        },
        "overall_pass": exact_inventory and passed == len(REQUIRED_ASSERTION_IDS),
    }


def _zero_deltas(deltas: Mapping[str, int]) -> bool:
    return bool(deltas) and all(value == 0 for value in deltas.values())


def _single_graph_delta(deltas: Mapping[str, int]) -> bool:
    expected = {
        "users": 1,
        "student_registrations": 1,
        "student_profiles": 1,
        "student_verifications": 1,
        "guardian_consents": 0,
        "consents": 1,
        "otp_challenges": 1,
        "otp_outbox": 1,
        "audit_events": 1,
    }
    return dict(deltas) == expected


def _replay_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("first_status") == 201
        and observation.get("first_literal_pending") is True
        and observation.get("replay_status") == 201
        and observation.get("same_public_handle") is True
        and _single_graph_delta(observation.get("initial_graph_delta", {}))
        and _zero_deltas(observation.get("replay_graph_delta", {}))
        and observation.get("replay_ledger_delta") == 0
        and observation.get("replay_delivery_delta") == 0
        and observation.get("replay_state_unchanged") is True
    )


def _conflict_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("status") == 409
        and observation.get("error_code") == "idempotency_conflict"
        and observation.get("error_field") == "Idempotency-Key"
        and _zero_deltas(observation.get("graph_delta", {}))
        and observation.get("ledger_delta") == 0
        and observation.get("delivery_delta") == 0
        and observation.get("state_unchanged") is True
    )


def _retired_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("matching_status") == 409
        and observation.get("mismatched_status") == 409
        and observation.get("matching_code") == "registration_replay_expired"
        and observation.get("mismatched_code") == "registration_replay_expired"
        and observation.get("matching_field") == "Idempotency-Key"
        and observation.get("mismatched_field") == "Idempotency-Key"
        and observation.get("uniform_signature") is True
        and _zero_deltas(observation.get("graph_delta", {}))
        and observation.get("ledger_delta") == 0
        and observation.get("delivery_delta") == 0
        and observation.get("state_unchanged") is True
    )


def _race_observation_passes(
    observation: Mapping[str, Any], *, mismatched: bool
) -> bool:
    statuses = list(observation.get("statuses", ()))
    expected_statuses = [201, 409] if mismatched else [201] * 8
    codes = list(observation.get("conflict_codes", ()))
    fields = list(observation.get("conflict_fields", ()))
    return bool(
        sorted(statuses) == expected_statuses
        and (codes == ["idempotency_conflict"] if mismatched else not codes)
        and (fields == ["Idempotency-Key"] if mismatched else not fields)
        and observation.get("same_public_handle") is (not mismatched)
        and _single_graph_delta(observation.get("graph_delta", {}))
        and observation.get("ledger_delta") == 1
        and observation.get("delivery_delta") == 1
        and observation.get("backend_count") == (2 if mismatched else 8)
        and (observation.get("db_lock_wait_observed") is True if mismatched else True)
        and observation.get("stable_followups") is True
    )


def _failure_replay_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("first_status") == 502
        and observation.get("replay_status") == 502
        and observation.get("same_error_code") is True
        and observation.get("error_fields_absent") is True
        and observation.get("ledger_delta") == 1
        and observation.get("replay_ledger_delta") == 0
        and observation.get("replay_delivery_delta") == 0
        and observation.get("replay_graph_delta_zero") is True
        and observation.get("replay_state_unchanged") is True
    )


def _ledger_inventory_observation_passes(
    observation: Mapping[str, Any],
) -> bool:
    """Require the exact non-PII ledger authority and state/link shapes."""

    return bool(
        observation.get("schema_exact") is True
        and observation.get("ledger_has_raw_key_column") is False
        and observation.get("new_registration_raw_key_is_null") is True
        and observation.get("new_registration_legacy_marker_false") is True
        and observation.get("key_hash_lower_hex_64") is True
        and observation.get("key_hash_differs_from_wire_key") is True
        and observation.get("key_hash_unique_authority") is True
        and observation.get("state_inventory_exact") is True
        and observation.get("state_links_exact") is True
    )


def _pending_resume_observation_passes(observation: Mapping[str, Any]) -> bool:
    """A crash-pending request must resume once without duplicating its graph."""

    return bool(
        observation.get("crash_status") == 500
        and observation.get("pending_state_exact") is True
        and observation.get("pending_mismatch_status") == 409
        and observation.get("pending_mismatch_code") == "idempotency_conflict"
        and observation.get("pending_mismatch_field") == "Idempotency-Key"
        and observation.get("resume_status") == 201
        and observation.get("resume_same_public_handle") is True
        and observation.get("succeeded_state_exact") is True
        and observation.get("ledger_delta") == 1
        and _single_graph_delta(observation.get("graph_delta", {}))
        and observation.get("resume_graph_delta_zero") is True
        and observation.get("crash_provider_invocations") == 1
        and observation.get("crash_provider_acceptances") == 0
        and observation.get("resume_provider_acceptances") == 1
        and observation.get("provider_acceptances_total") == 1
        and observation.get("followup_stable") is True
    )


def _failed_waiters_observation_passes(observation: Mapping[str, Any]) -> bool:
    """Concurrent exact waiters must observe one finalized 502 outcome."""

    return bool(
        sorted(observation.get("statuses", ())) == [502, 502]
        and observation.get("same_error_code") is True
        and observation.get("error_fields_absent") is True
        and observation.get("failed_state_exact") is True
        and observation.get("ledger_delta") == 1
        and observation.get("registration_graph_absent") is True
        and observation.get("provider_attempt_delta") == 1
        and observation.get("backend_count") == 2
        and observation.get("db_lock_wait_observed") is True
        and observation.get("stable_failure_replay") is True
        and observation.get("mismatch_conflict") is True
    )


def _invalid_key_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("status") == 422
        and observation.get("error_code") == "invalid_idempotency_key"
        and observation.get("error_field") == "Idempotency-Key"
        and observation.get("state_unchanged") is True
        and observation.get("delivery_delta") == 0
    )


def _downgrade_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("legacy_upgrade") is True
        and observation.get("legacy_marked") is True
        and observation.get("ledger_downgrade_refused_unchanged") is True
        and observation.get("legacy_downgrade_refused_unchanged") is True
        and observation.get("mixed_writer_rejected") is True
        and observation.get("mixed_constraint_exact") is True
    )


def _scratch_cleanup_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("created") == observation.get("removed")
        and observation.get("cleanup_failed") == 0
        and observation.get("inventory_match") is True
        and observation.get("all_created_removed") is True
        and observation.get("baseline_count", -1) >= 0
        and observation.get("final_count") == observation.get("baseline_count")
    )


def _pending_resend_observation_passes(
    observation: Mapping[str, Any], *, concurrent: bool, pre_relay: bool = False
) -> bool:
    authority_shape_exact = bool(
        observation.get("ledger_succeeded_unlinked_before_replacement") is True
        if pre_relay
        else observation.get("ledger_repointed_to_replacement") is True
    )
    return bool(
        observation.get("resend_status") == 202
        and observation.get("replay_status") == 201
        and observation.get("same_public_handle") is True
        and authority_shape_exact
        and observation.get("superseded_payload_nonrelayable") is True
        and observation.get("succeeded_state_exact") is True
        and observation.get("registration_graph_single") is True
        and observation.get("active_signup_challenges") == 1
        and observation.get("relayable_signup_payloads") == 0
        and observation.get("provider_acceptances") == 1
        and (
            observation.get("backend_count") == 2
            and observation.get("db_lock_wait_observed") is True
            if concurrent
            else True
        )
    )


def _pending_purge_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("purged_challenges") == 1
        and observation.get("registration_transitions") == 1
        and observation.get("erased_state_exact") is True
        and observation.get("policy_mode_shape_exact") is True
        and observation.get("audit_action_exact") is True
        and observation.get("relayable_payload_absent") is True
        and observation.get("terminal_cases") == len(CANONICAL_FIELD_PATHS) + 1
        and observation.get("all_terminal_statuses_409") is True
        and observation.get("all_terminal_codes_expired") is True
        and observation.get("all_terminal_fields_idempotency_key") is True
        and observation.get("uniform_response_bytes") is True
        and observation.get("provider_acceptances") == 0
        and observation.get("state_unchanged_on_replays") is True
    )


def _seeded_mutant_results() -> list[bool]:
    """Return privacy-safe deterministic oracle-closure results."""

    graph = {
        "users": 1,
        "student_registrations": 1,
        "student_profiles": 1,
        "student_verifications": 1,
        "guardian_consents": 0,
        "consents": 1,
        "otp_challenges": 1,
        "otp_outbox": 1,
        "audit_events": 1,
    }
    zero_graph = {name: 0 for name in graph}
    replay = {
        "first_status": 201,
        "first_literal_pending": True,
        "replay_status": 201,
        "same_public_handle": True,
        "initial_graph_delta": graph,
        "replay_graph_delta": zero_graph,
        "replay_ledger_delta": 0,
        "replay_delivery_delta": 0,
        "replay_state_unchanged": True,
    }
    conflict = {
        "status": 409,
        "error_code": "idempotency_conflict",
        "error_field": "Idempotency-Key",
        "graph_delta": zero_graph,
        "ledger_delta": 0,
        "delivery_delta": 0,
        "state_unchanged": True,
    }
    retired = {
        "matching_status": 409,
        "mismatched_status": 409,
        "matching_code": "registration_replay_expired",
        "mismatched_code": "registration_replay_expired",
        "matching_field": "Idempotency-Key",
        "mismatched_field": "Idempotency-Key",
        "uniform_signature": True,
        "graph_delta": zero_graph,
        "ledger_delta": 0,
        "delivery_delta": 0,
        "state_unchanged": True,
    }
    same_race = {
        "statuses": [201] * 8,
        "conflict_codes": [],
        "conflict_fields": [],
        "same_public_handle": True,
        "graph_delta": graph,
        "ledger_delta": 1,
        "delivery_delta": 1,
        "backend_count": 8,
        "stable_followups": True,
    }
    mismatch_race = {
        "statuses": [201, 409],
        "conflict_codes": ["idempotency_conflict"],
        "conflict_fields": ["Idempotency-Key"],
        "same_public_handle": False,
        "graph_delta": graph,
        "ledger_delta": 1,
        "delivery_delta": 1,
        "backend_count": 2,
        "db_lock_wait_observed": True,
        "stable_followups": True,
    }
    failure = {
        "first_status": 502,
        "replay_status": 502,
        "same_error_code": True,
        "error_fields_absent": True,
        "ledger_delta": 1,
        "replay_ledger_delta": 0,
        "replay_delivery_delta": 0,
        "replay_graph_delta_zero": True,
        "replay_state_unchanged": True,
    }
    ledger = {
        "schema_exact": True,
        "ledger_has_raw_key_column": False,
        "new_registration_raw_key_is_null": True,
        "new_registration_legacy_marker_false": True,
        "key_hash_lower_hex_64": True,
        "key_hash_differs_from_wire_key": True,
        "key_hash_unique_authority": True,
        "state_inventory_exact": True,
        "state_links_exact": True,
    }
    pending = {
        "crash_status": 500,
        "pending_state_exact": True,
        "pending_mismatch_status": 409,
        "pending_mismatch_code": "idempotency_conflict",
        "pending_mismatch_field": "Idempotency-Key",
        "resume_status": 201,
        "resume_same_public_handle": True,
        "succeeded_state_exact": True,
        "ledger_delta": 1,
        "graph_delta": graph,
        "resume_graph_delta_zero": True,
        "crash_provider_invocations": 1,
        "crash_provider_acceptances": 0,
        "resume_provider_acceptances": 1,
        "provider_acceptances_total": 1,
        "followup_stable": True,
    }
    failed_waiter = {
        "statuses": [502, 502],
        "same_error_code": True,
        "error_fields_absent": True,
        "failed_state_exact": True,
        "ledger_delta": 1,
        "registration_graph_absent": True,
        "provider_attempt_delta": 1,
        "backend_count": 2,
        "db_lock_wait_observed": True,
        "stable_failure_replay": True,
        "mismatch_conflict": True,
    }
    invalid_key = {
        "status": 422,
        "error_code": "invalid_idempotency_key",
        "error_field": "Idempotency-Key",
        "state_unchanged": True,
        "delivery_delta": 0,
    }
    downgrade = {
        "legacy_upgrade": True,
        "legacy_marked": True,
        "ledger_downgrade_refused_unchanged": True,
        "legacy_downgrade_refused_unchanged": True,
        "mixed_writer_rejected": True,
        "mixed_constraint_exact": True,
    }
    cleanup = {
        "created": 2,
        "removed": 2,
        "cleanup_failed": 0,
        "inventory_match": True,
        "all_created_removed": True,
        "baseline_count": 0,
        "final_count": 0,
    }
    pending_resend = {
        "resend_status": 202,
        "replay_status": 201,
        "same_public_handle": True,
        "ledger_repointed_to_replacement": True,
        "ledger_succeeded_unlinked_before_replacement": False,
        "superseded_payload_nonrelayable": True,
        "succeeded_state_exact": True,
        "registration_graph_single": True,
        "active_signup_challenges": 1,
        "relayable_signup_payloads": 0,
        "provider_acceptances": 1,
        "backend_count": 2,
        "db_lock_wait_observed": True,
    }
    pre_relay_resend = deepcopy(pending_resend)
    pre_relay_resend.update(
        {
            "ledger_repointed_to_replacement": False,
            "ledger_succeeded_unlinked_before_replacement": True,
            "backend_count": 0,
            "db_lock_wait_observed": False,
        }
    )
    pending_purge = {
        "purged_challenges": 1,
        "registration_transitions": 1,
        "erased_state_exact": True,
        "policy_mode_shape_exact": True,
        "audit_action_exact": True,
        "relayable_payload_absent": True,
        "terminal_cases": len(CANONICAL_FIELD_PATHS) + 1,
        "all_terminal_statuses_409": True,
        "all_terminal_codes_expired": True,
        "all_terminal_fields_idempotency_key": True,
        "uniform_response_bytes": True,
        "provider_acceptances": 0,
        "state_unchanged_on_replays": True,
    }

    def killed(
        evaluator: Callable[[Mapping[str, Any]], bool],
        baseline: dict[str, Any],
        field: str,
        unsafe: Any,
    ) -> bool:
        mutant = deepcopy(baseline)
        mutant[field] = unsafe
        return evaluator(baseline) and not evaluator(mutant)

    results = [
        killed(_replay_observation_passes, replay, field, unsafe)
        for field, unsafe in (
            ("replay_status", 409),
            ("same_public_handle", False),
            ("replay_delivery_delta", 1),
            ("replay_state_unchanged", False),
        )
    ]
    # One deterministic bypass mutant per canonical request field: replaying a
    # changed field as 201 must turn the typed-conflict oracle red.
    results.extend(
        killed(_conflict_observation_passes, conflict, "status", 201)
        for _ in CANONICAL_FIELD_PATHS
    )
    results.extend(
        killed(_retired_observation_passes, retired, field, unsafe)
        for field, unsafe in (
            ("matching_code", "idempotency_conflict"),
            ("mismatched_field", "mobile"),
            ("uniform_signature", False),
            ("delivery_delta", 1),
        )
    )
    results.extend(
        killed(_failure_replay_observation_passes, failure, field, unsafe)
        for field, unsafe in (
            ("replay_status", 201),
            ("error_fields_absent", False),
            ("replay_delivery_delta", 1),
            ("replay_state_unchanged", False),
        )
    )
    results.extend(
        killed(
            lambda value: _race_observation_passes(value, mismatched=False),
            same_race,
            field,
            unsafe,
        )
        for field, unsafe in (
            ("statuses", [201] * 7 + [409]),
            ("backend_count", 7),
            ("delivery_delta", 2),
            ("stable_followups", False),
        )
    )
    results.extend(
        killed(
            lambda value: _race_observation_passes(value, mismatched=True),
            mismatch_race,
            field,
            unsafe,
        )
        for field, unsafe in (
            ("conflict_codes", ["mobile_already_registered"]),
            ("conflict_fields", ["mobile"]),
            ("backend_count", 1),
            ("db_lock_wait_observed", False),
        )
    )
    results.extend(
        killed(_ledger_inventory_observation_passes, ledger, field, unsafe)
        for field, unsafe in (
            ("schema_exact", False),
            ("key_hash_unique_authority", False),
            ("state_links_exact", False),
        )
    )
    results.extend(
        killed(_pending_resume_observation_passes, pending, field, unsafe)
        for field, unsafe in (
            ("crash_provider_acceptances", 1),
            ("resume_provider_acceptances", 2),
            ("pending_mismatch_field", "mobile"),
            ("resume_graph_delta_zero", False),
        )
    )
    results.extend(
        killed(_failed_waiters_observation_passes, failed_waiter, field, unsafe)
        for field, unsafe in (
            ("statuses", [201, 502]),
            ("backend_count", 1),
            ("db_lock_wait_observed", False),
            ("provider_attempt_delta", 2),
        )
    )
    results.extend(
        killed(_invalid_key_observation_passes, invalid_key, field, unsafe)
        for field, unsafe in (
            ("status", 201),
            ("error_code", "idempotency_conflict"),
            ("error_field", "mobile"),
            ("state_unchanged", False),
            ("delivery_delta", 1),
        )
    )
    results.extend(
        killed(_downgrade_observation_passes, downgrade, field, False)
        for field in (
            "ledger_downgrade_refused_unchanged",
            "legacy_downgrade_refused_unchanged",
            "mixed_constraint_exact",
        )
    )
    results.extend(
        killed(_scratch_cleanup_observation_passes, cleanup, field, unsafe)
        for field, unsafe in (
            ("removed", 1),
            ("cleanup_failed", 1),
            ("inventory_match", False),
            ("all_created_removed", False),
            ("final_count", 1),
        )
    )
    results.extend(
        killed(
            lambda value: _pending_resend_observation_passes(value, concurrent=True),
            pending_resend,
            field,
            unsafe,
        )
        for field, unsafe in (
            ("ledger_repointed_to_replacement", False),
            ("superseded_payload_nonrelayable", False),
            ("registration_graph_single", False),
            ("relayable_signup_payloads", 1),
            ("backend_count", 1),
            ("db_lock_wait_observed", False),
        )
    )
    results.extend(
        killed(
            lambda value: _pending_resend_observation_passes(
                value, concurrent=False, pre_relay=True
            ),
            pre_relay_resend,
            field,
            unsafe,
        )
        for field, unsafe in (
            ("ledger_succeeded_unlinked_before_replacement", False),
            ("superseded_payload_nonrelayable", False),
            ("succeeded_state_exact", False),
            ("provider_acceptances", 2),
        )
    )
    results.extend(
        killed(_pending_purge_observation_passes, pending_purge, field, unsafe)
        for field, unsafe in (
            ("erased_state_exact", False),
            ("registration_transitions", 0),
            ("policy_mode_shape_exact", False),
            ("audit_action_exact", False),
            ("relayable_payload_absent", False),
            ("all_terminal_statuses_409", False),
            ("all_terminal_codes_expired", False),
            ("all_terminal_fields_idempotency_key", False),
            ("uniform_response_bytes", False),
            ("state_unchanged_on_replays", False),
        )
    )
    passing_assertions = [
        _assertion(identifier, True) for identifier in REQUIRED_ASSERTION_IDS
    ]
    missing = passing_assertions[:-1]
    reordered = list(reversed(passing_assertions))
    results.extend(
        (
            _evaluate_assertions(passing_assertions)["overall_pass"]
            and not _evaluate_assertions(missing)["overall_pass"],
            _evaluate_assertions(passing_assertions)["overall_pass"]
            and not _evaluate_assertions(reordered)["overall_pass"],
            bool(_privacy_findings({"idempotency_key": "opaque"})),
            bool(_privacy_findings({"value": "a" * 64})),
        )
    )
    return results


def _seeded_mutants_are_killed() -> bool:
    """Every deterministic seeded mutant must turn its exact oracle red."""

    results = _seeded_mutant_results()
    return bool(results) and all(results)


def _base_registration_payload(sequence: int) -> dict[str, Any]:
    """Return synthetic valid content that is kept in memory only."""

    mobile = f"8{sequence:09d}"[-10:]
    return {
        "first_name": "Āsha Rao",
        "middle_name": None,
        "last_name": "Sen",
        "mobile": mobile,
        "dob": "2000-01-02",
        "consent": {
            "accepted": True,
            "policy_version": "dpdp-2023.v1",
        },
        "college": "Synthetic Law University",
        "year_of_study": "Year 2",
        "enrolment_number": f"QA/{1000 + sequence}/2026",
        "institutional_email": (f"synthetic-{sequence}" + chr(64) + "law.invalid"),
        "bar_enrolment_number": f"QA-BAR-{sequence}",
    }


def _canonical_field_mutations(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Change exactly one of the twelve v1 canonical fields per request."""

    mutations: list[dict[str, Any]] = []
    replacements: tuple[tuple[str, Any], ...] = (
        ("first_name", "Maya"),
        ("middle_name", "Devi"),
        ("last_name", "Rao"),
        ("mobile", "7999999999"),
        ("dob", "2000-01-03"),
        ("consent.accepted", False),
        ("consent.policy_version", "dpdp-2023.v2"),
        ("college", "Other Law University"),
        ("year_of_study", "Year 3"),
        ("enrolment_number", "QA/9999/2026"),
        (
            "institutional_email",
            "changed" + chr(64) + "law.invalid",
        ),
        ("bar_enrolment_number", "QA-BAR-CHANGED"),
    )
    for path, replacement in replacements:
        candidate = deepcopy(dict(payload))
        if "." in path:
            parent, child = path.split(".", 1)
            candidate[parent] = dict(candidate[parent])
            candidate[parent][child] = replacement
        else:
            candidate[path] = replacement
        mutations.append(candidate)
    return mutations


def _canonical_equivalent_payloads(
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Different JSON spellings that validate to the same canonical v1 value."""

    variants: list[dict[str, Any]] = []
    names = deepcopy(dict(payload))
    names["first_name"] = (
        "  "
        + unicodedata.normalize("NFD", str(payload["first_name"])).replace(" ", "   ")
        + "  "
    )
    names["middle_name"] = "   "
    variants.append(names)

    academic = deepcopy(dict(payload))
    academic["college"] = "  Synthetic   Law University  "
    academic["year_of_study"] = " Year   2 "
    academic["enrolment_number"] = f" {payload['enrolment_number']} "
    academic["bar_enrolment_number"] = f" {payload['bar_enrolment_number']} "
    variants.append(academic)

    email = deepcopy(dict(payload))
    email["institutional_email"] = (
        "  " + str(payload["institutional_email"]).upper() + "  "
    )
    variants.append(email)

    defaulted = deepcopy(dict(payload))
    defaulted["consent"] = {"accepted": True}
    variants.append(defaulted)

    omitted_middle = deepcopy(dict(payload))
    omitted_middle.pop("middle_name")
    variants.append(omitted_middle)
    return variants


def _table_counts(
    session_factory: sessionmaker[Session], tables: tuple[str, ...]
) -> dict[str, int]:
    with session_factory() as session:
        return {
            table: int(session.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)
            for table in tables
        }


def _count_delta(before: Mapping[str, int], after: Mapping[str, int]) -> dict[str, int]:
    return {name: int(after[name] - before[name]) for name in before}


def _database_state_digest(engine: Engine, tables: tuple[str, ...]) -> str:
    """Internal all-column equality oracle; digest never enters evidence."""

    available = set(inspect(engine).get_table_names())
    snapshot: list[Any] = []
    with engine.connect() as connection:
        for table in tables:
            if table not in available:
                snapshot.append((table, "absent"))
                continue
            rows = [
                tuple(row)
                for row in connection.execute(
                    text(f'SELECT * FROM "{table}" ORDER BY 1')
                )
            ]
            snapshot.append((table, rows))
    return hashlib.sha256(repr(snapshot).encode("utf-8")).hexdigest()


class _CapturingSender:
    """Thread-safe synthetic OTP provider; values never enter evidence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.sent: list[tuple[str, str]] = []

    def send(self, destination: str, code: str) -> None:
        with self._lock:
            self.sent.append((destination, code))

    @property
    def count(self) -> int:
        with self._lock:
            return len(self.sent)


class _FailingSender(_CapturingSender):
    """Provider-level failure used to exercise durable terminal 502 replay."""

    def send(self, destination: str, code: str) -> None:
        from app.services.otp_sender import OtpSendError

        with self._lock:
            self.sent.append((destination, code))
        raise OtpSendError("synthetic provider failure")


class _CrashSender(_CapturingSender):
    """Crash before provider acceptance, leaving resumable durable pending."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def send(self, destination: str, code: str) -> None:
        with self._lock:
            self.attempts += 1
        raise RuntimeError("synthetic post-commit crash")


class _AcceptedCrashSender(_CapturingSender):
    """Project a provider acceptance followed by local finalization crash."""

    def send(self, destination: str, code: str) -> None:
        with self._lock:
            self.sent.append((destination, code))
        raise RuntimeError("synthetic accepted-before-finalization crash")


class _BlockingSender(_CapturingSender):
    """Hold one provider attempt so an exact concurrent waiter overlaps it."""

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail = fail

    def send(self, destination: str, code: str) -> None:
        from app.services.otp_sender import OtpSendError

        with self._lock:
            self.sent.append((destination, code))
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise RuntimeError("synthetic gate release timeout")
        if self.fail:
            raise OtpSendError("synthetic provider failure")


class _PgBackendTracker:
    """Track request backend cardinality privately; never emit PID values."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pids: set[int] = set()

    def record(self, pid: int) -> None:
        with self._condition:
            self._pids.add(pid)
            self._condition.notify_all()

    def wait_for_count(self, expected: int, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self._pids) < expected:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return len(self._pids) == expected

    def private_snapshot(self) -> set[int]:
        with self._condition:
            return set(self._pids)

    @property
    def count(self) -> int:
        with self._condition:
            return len(self._pids)


def _wait_for_request_lock(
    engine: Engine,
    tracker: _PgBackendTracker,
    *,
    expected_backends: int,
    minimum_waiters: int = 1,
    timeout: float = 5.0,
) -> bool:
    """Prove a tracked request reached a PostgreSQL lock wait."""

    if not tracker.wait_for_count(expected_backends, timeout=timeout):
        return False
    pids = tracker.private_snapshot()
    if len(pids) != expected_backends:
        return False
    deadline = time.monotonic() + timeout
    placeholders = ", ".join(f":pid_{index}" for index in range(len(pids)))
    parameters = {f"pid_{index}": pid for index, pid in enumerate(sorted(pids))}
    statement = text(
        "SELECT count(*) FROM pg_stat_activity "
        f"WHERE pid IN ({placeholders}) AND wait_event_type = 'Lock'"
    )
    with engine.connect() as connection:
        while time.monotonic() < deadline:
            waiting = int(connection.scalar(statement, parameters) or 0)
            if waiting >= minimum_waiters:
                return True
            time.sleep(0.02)
    return False


def _build_app_context(
    engine: Engine,
    sender: Any,
    *,
    backend_tracker: _PgBackendTracker | None = None,
) -> tuple[FastAPI, sessionmaker[Session]]:
    """Bind the real registration router to the isolated PostgreSQL engine."""

    from app.api.v1 import auth_student as endpoint
    from app.core.exceptions import register_exception_handlers
    from app.db.session import get_session

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    def request_session() -> Iterator[Session]:
        session = factory()
        try:
            if backend_tracker is not None:
                backend_tracker.record(
                    int(session.scalar(text("SELECT pg_backend_pid()")))
                )
            yield session
        except Exception:
            session.rollback()
            raise
        else:
            session.rollback()
        finally:
            session.close()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(endpoint.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[endpoint.get_otp_sender] = lambda: sender
    app.dependency_overrides[endpoint.get_outbox_session_factory] = lambda: factory
    return app, factory


def _post_registration(
    app: FastAPI,
    payload: Mapping[str, Any],
    key: str | None,
) -> Any:
    headers = {"Idempotency-Key": key} if key is not None else None
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(REGISTER_PATH, json=dict(payload), headers=headers)


def _post_registration_headers(
    app: FastAPI,
    payload: Mapping[str, Any],
    headers: list[tuple[str, str]],
) -> Any:
    """Send an exact raw header list so duplicate occurrences remain visible."""

    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(REGISTER_PATH, json=dict(payload), headers=headers)


def _post_signup_resend(app: FastAPI, registration_handle: str | None) -> Any:
    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(
            "/api/v1/auth/student/otp/resend",
            json={"registration_id": registration_handle},
        )


def _response_handle(response: Any) -> str | None:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - only an in-memory comparison handle
        return None
    value = body.get("registration_id") if isinstance(body, dict) else None
    return str(value) if value is not None else None


def _response_error_code(response: Any) -> str | None:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - aggregate error class only
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    value = detail.get("code") if isinstance(detail, dict) else None
    return value if isinstance(value, str) else None


def _response_error_field(response: Any) -> str | None:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - aggregate error shape only
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    value = detail.get("field") if isinstance(detail, dict) else None
    return value if isinstance(value, str) else None


def _ledger_state_exact(record: Any, state: str) -> bool:
    """Validate one exact state/link/fingerprint inventory in memory."""

    if record is None or record.state != state:
        return False
    hash_value = record.idempotency_key_hash
    key_shape = bool(
        isinstance(hash_value, str) and re.fullmatch(r"[0-9a-f]{64}", hash_value)
    )
    if state == "pending":
        state_shape = bool(
            record.request_fingerprint_version == "v1"
            and isinstance(record.request_fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", record.request_fingerprint)
            and record.registration_id is not None
            and record.outbox_id is not None
            and record.outcome_code is None
        )
    elif state == "succeeded":
        state_shape = bool(
            record.request_fingerprint_version == "v1"
            and isinstance(record.request_fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", record.request_fingerprint)
            and record.registration_id is not None
            and record.outbox_id is None
            and record.outcome_code is None
        )
    elif state == "failed":
        state_shape = bool(
            record.request_fingerprint_version == "v1"
            and isinstance(record.request_fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", record.request_fingerprint)
            and record.registration_id is None
            and record.outbox_id is None
            and record.outcome_code == "otp_delivery_failed"
        )
    elif state in {"retired", "erased"}:
        state_shape = bool(
            record.request_fingerprint is None
            and record.request_fingerprint_version is None
            and record.registration_id is None
            and record.outbox_id is None
            and record.outcome_code == "registration_replay_expired"
        )
    else:
        return False
    return key_shape and state_shape


def _ledger_for_key(session: Session, key: str) -> Any:
    from app.models.registration import RegistrationIdempotencyRecord
    from app.services.registration_service import registration_idempotency_key_hash

    return session.scalar(
        select(RegistrationIdempotencyRecord).where(
            RegistrationIdempotencyRecord.idempotency_key_hash
            == registration_idempotency_key_hash(key)
        )
    )


def _durable_registration_handle_for_key(session: Session, key: str) -> str | None:
    """Resolve a crash-pending subject only through its unique durable ledger.

    A post-commit process failure correctly returns an opaque HTTP 500 with no
    public registration handle. Runtime probes must therefore recover the
    already-committed subject from the HMAC-keyed ledger, never from the error
    body. The ledger key hash is UNIQUE in the independently checked schema,
    so ``scalar`` represents exactly one authority or none.
    """

    record = _ledger_for_key(session, key)
    registration_id = getattr(record, "registration_id", None)
    try:
        return str(uuid.UUID(str(registration_id)))
    except (TypeError, ValueError):
        return None


def _registration_rows_for_handle(session: Session, handle: str | None) -> Any:
    from app.models.registration import StudentRegistration

    try:
        identifier = uuid.UUID(str(handle))
    except (TypeError, ValueError):
        return None
    return session.get(StudentRegistration, identifier)


def _key_boundary_passes() -> tuple[bool, int]:
    from app.services.registration_service import (
        RegistrationError,
        validate_idempotency_key,
    )

    rejected = ["", " leading", "trailing ", "x" * 201]
    rejected.extend(chr(value) for value in range(32))
    rejected.append(chr(127))
    invalid_passed = True
    for candidate in rejected:
        try:
            validate_idempotency_key(candidate)
        except RegistrationError as exc:
            invalid_passed = invalid_passed and _invalid_key_error_is_exact(
                exc, candidate
            )
        else:
            invalid_passed = False
    allowed = ("x", "x" * 200, "opaque internal space", "opaque<>token")
    allowed_passed = all(validate_idempotency_key(value) == value for value in allowed)
    return invalid_passed and allowed_passed, len(rejected) + len(allowed)


def _run_http_key_boundary(
    engine: Engine,
    app: FastAPI,
    factory: sessionmaker[Session],
    sender: _CapturingSender,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove real HTTP rejection, duplicate detection, and legacy omission."""

    tables = REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",)
    mandatory_headers = (
        [("Idempotency-Key", "duplicate"), ("Idempotency-Key", "duplicate")],
        [("Idempotency-Key", "left"), ("Idempotency-Key", "right")],
        [("Idempotency-Key", "")],
        [("Idempotency-Key", " leading")],
        [("Idempotency-Key", "trailing ")],
        [("Idempotency-Key", "x" * 201)],
    )
    optional_transport_headers = (
        [("Idempotency-Key", chr(1))],
        [("Idempotency-Key", chr(127))],
    )
    mandatory_passed = True
    optional_executed = 0
    optional_passed = True
    for headers in mandatory_headers + optional_transport_headers:
        before_state = _database_state_digest(engine, tables)
        before_delivery = sender.count
        response = None
        try:
            response = _post_registration_headers(app, payload, headers)
        except Exception:  # noqa: BLE001 - transport can reject control bytes
            if headers in mandatory_headers:
                mandatory_passed = False
        unchanged = bool(
            _database_state_digest(engine, tables) == before_state
            and sender.count == before_delivery
        )
        if headers in mandatory_headers:
            mandatory_passed = mandatory_passed and bool(
                response is not None
                and _invalid_key_observation_passes(
                    {
                        "status": response.status_code,
                        "error_code": _response_error_code(response),
                        "error_field": _response_error_field(response),
                        "state_unchanged": unchanged,
                        "delivery_delta": sender.count - before_delivery,
                    }
                )
            )
        elif response is not None:
            optional_executed += 1
            optional_passed = optional_passed and _invalid_key_observation_passes(
                {
                    "status": response.status_code,
                    "error_code": _response_error_code(response),
                    "error_field": _response_error_field(response),
                    "state_unchanged": unchanged,
                    "delivery_delta": sender.count - before_delivery,
                }
            )
        else:
            optional_passed = optional_passed and unchanged

    short_before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    short_before_ledger = _table_counts(factory, ("registration_idempotency_records",))[
        "registration_idempotency_records"
    ]
    short_before_delivery = sender.count
    short_response = _post_registration(app, _base_registration_payload(103), "x")
    short_after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    short_after_ledger = _table_counts(factory, ("registration_idempotency_records",))[
        "registration_idempotency_records"
    ]
    short_passed = bool(
        short_response.status_code == 201
        and _single_graph_delta(_count_delta(short_before_graph, short_after_graph))
        and short_after_ledger - short_before_ledger == 1
        and sender.count - short_before_delivery == 1
    )

    absent_before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    absent_before_ledger = _table_counts(
        factory, ("registration_idempotency_records",)
    )["registration_idempotency_records"]
    absent_before_delivery = sender.count
    absent_response = _post_registration(app, _base_registration_payload(104), None)
    absent_after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    absent_after_ledger = _table_counts(factory, ("registration_idempotency_records",))[
        "registration_idempotency_records"
    ]
    absent_passed = bool(
        absent_response.status_code == 201
        and _single_graph_delta(_count_delta(absent_before_graph, absent_after_graph))
        and absent_after_ledger - absent_before_ledger == 0
        and sender.count - absent_before_delivery == 1
    )
    return {
        "passed": mandatory_passed
        and optional_passed
        and short_passed
        and absent_passed,
        "mandatory_invalid_cases": len(mandatory_headers),
        "optional_control_cases_executed": optional_executed,
        "short_key_succeeded": short_passed,
        "absent_header_legacy_succeeded": absent_passed,
    }


def _run_sequential_probes(
    engine: Engine,
) -> dict[str, Any]:
    """Sequential replay, canonicalization, conflict, legacy, and key probes."""

    from app.schemas.registration import StudentRegisterRequest

    ledger_table = ("registration_idempotency_records",)
    all_state_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    sender = _CapturingSender()
    app, factory = _build_app_context(engine, sender)
    base = _base_registration_payload(101)
    wire_key = "nyay17-sequential-synthetic"

    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ledger_table)
    first = _post_registration(app, base, wire_key)
    after_first_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_first_ledger = _table_counts(factory, ledger_table)
    first_state = _database_state_digest(engine, all_state_tables)
    first_delivery_count = sender.count

    replay = _post_registration(app, base, wire_key)
    after_replay_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_replay_ledger = _table_counts(factory, ledger_table)
    replay_state = _database_state_digest(engine, all_state_tables)
    replay_observation = {
        "first_status": first.status_code,
        "first_literal_pending": bool(
            first.status_code == 201
            and isinstance(first.json(), dict)
            and first.json().get("status") == "otp_pending"
        ),
        "replay_status": replay.status_code,
        "same_public_handle": _response_handle(first) == _response_handle(replay),
        "initial_graph_delta": _count_delta(before_graph, after_first_graph),
        "replay_graph_delta": _count_delta(after_first_graph, after_replay_graph),
        "replay_ledger_delta": (
            after_replay_ledger[ledger_table[0]] - after_first_ledger[ledger_table[0]]
        ),
        "replay_delivery_delta": sender.count - first_delivery_count,
        "replay_state_unchanged": replay_state == first_state,
    }

    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        registration = _registration_rows_for_handle(session, _response_handle(first))
        ledger_shape = _ledger_state_exact(record, "succeeded")
        raw_key_absent = bool(
            registration is not None
            and registration.idempotency_key is None
            and registration.idempotency_key_legacy is False
        )
        hash_private = bool(
            record is not None
            and record.idempotency_key_hash != wire_key
            and wire_key not in record.idempotency_key_hash
        )

    equivalent_before = _database_state_digest(engine, all_state_tables)
    equivalent_delivery_before = sender.count
    equivalent_responses = [
        _post_registration(app, candidate, wire_key)
        for candidate in _canonical_equivalent_payloads(base)
    ]
    equivalent_passed = bool(
        all(response.status_code == 201 for response in equivalent_responses)
        and all(
            _response_handle(response) == _response_handle(first)
            for response in equivalent_responses
        )
        and sender.count == equivalent_delivery_before
        and _database_state_digest(engine, all_state_tables) == equivalent_before
    )

    mutations = _canonical_field_mutations(base)
    mutations_schema_valid = True
    for candidate in mutations:
        try:
            StudentRegisterRequest.model_validate(candidate)
        except Exception:  # noqa: BLE001 - exact aggregate schema oracle
            mutations_schema_valid = False
    conflict_observations: list[dict[str, Any]] = []
    for candidate in mutations:
        counts_before = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
        ledger_before = _table_counts(factory, ledger_table)[ledger_table[0]]
        state_before = _database_state_digest(engine, all_state_tables)
        delivery_before = sender.count
        response = _post_registration(app, candidate, wire_key)
        counts_after = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
        ledger_after = _table_counts(factory, ledger_table)[ledger_table[0]]
        conflict_observations.append(
            {
                "status": response.status_code,
                "error_code": _response_error_code(response),
                "error_field": _response_error_field(response),
                "graph_delta": _count_delta(counts_before, counts_after),
                "ledger_delta": ledger_after - ledger_before,
                "delivery_delta": sender.count - delivery_before,
                "state_unchanged": (
                    _database_state_digest(engine, all_state_tables) == state_before
                ),
            }
        )

    # Explicit null and omitted spellings of every optional request field must
    # share one v1 fingerprint after model validation.
    explicit_null_payload = _base_registration_payload(105)
    optional_fields = (
        "middle_name",
        "college",
        "year_of_study",
        "enrolment_number",
        "institutional_email",
        "bar_enrolment_number",
    )
    for field in optional_fields:
        explicit_null_payload[field] = None
    omitted_payload = deepcopy(explicit_null_payload)
    for field in optional_fields:
        omitted_payload.pop(field)
    null_key = "nyay17-null-omitted-equivalence"
    null_first = _post_registration(app, explicit_null_payload, null_key)
    null_before = _database_state_digest(engine, all_state_tables)
    null_delivery_before = sender.count
    omitted_replay = _post_registration(app, omitted_payload, null_key)
    null_omitted_passed = bool(
        null_first.status_code == 201
        and omitted_replay.status_code == 201
        and _response_handle(null_first) == _response_handle(omitted_replay)
        and sender.count == null_delivery_before
        and _database_state_digest(engine, all_state_tables) == null_before
    )

    # Create an unkeyed graph, then mark its raw key as a pre-0018 reservation.
    legacy_payload = _base_registration_payload(102)
    legacy_created = _post_registration(app, legacy_payload, None)
    legacy_key = "nyay17-legacy-synthetic"
    with factory() as session:
        legacy_registration = _registration_rows_for_handle(
            session, _response_handle(legacy_created)
        )
        if legacy_registration is not None:
            legacy_registration.idempotency_key = legacy_key
            legacy_registration.idempotency_key_legacy = True
            session.commit()
    legacy_before_counts = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    legacy_before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    legacy_before_state = _database_state_digest(engine, all_state_tables)
    legacy_delivery_before = sender.count
    legacy_response = _post_registration(app, legacy_payload, legacy_key)
    legacy_after_counts = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    legacy_after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    legacy_observation = {
        "status": legacy_response.status_code,
        "error_code": _response_error_code(legacy_response),
        "error_field": _response_error_field(legacy_response),
        "graph_delta": _count_delta(legacy_before_counts, legacy_after_counts),
        "ledger_delta": legacy_after_ledger - legacy_before_ledger,
        "delivery_delta": sender.count - legacy_delivery_before,
        "state_unchanged": (
            _database_state_digest(engine, all_state_tables) == legacy_before_state
        ),
    }

    service_boundary_passed, service_boundary_cases = _key_boundary_passes()
    http_boundary = _run_http_key_boundary(engine, app, factory, sender, base)
    return {
        "replay": replay_observation,
        "ledger_shape": ledger_shape,
        "raw_key_absent": raw_key_absent,
        "hash_private": hash_private,
        "equivalents_passed": equivalent_passed and null_omitted_passed,
        "equivalent_cases": len(equivalent_responses) + 1,
        "conflicts_passed": mutations_schema_valid
        and all(_conflict_observation_passes(item) for item in conflict_observations),
        "conflict_cases": len(conflict_observations),
        "legacy_passed": _conflict_observation_passes(legacy_observation),
        "boundary_passed": service_boundary_passed and http_boundary["passed"],
        "boundary_cases": (
            service_boundary_cases
            + http_boundary["mandatory_invalid_cases"]
            + http_boundary["optional_control_cases_executed"]
            + 2
        ),
        "boundary_http": http_boundary,
        "head_ledger_delta": (
            after_first_ledger[ledger_table[0]] - before_ledger[ledger_table[0]]
        ),
    }


def _terminal_replay_observation(
    engine: Engine,
    app: FastAPI,
    factory: sessionmaker[Session],
    sender: _CapturingSender,
    payload: Mapping[str, Any],
    key: str,
) -> dict[str, Any]:
    tables = REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",)
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ("registration_idempotency_records",))[
        "registration_idempotency_records"
    ]
    before_delivery = sender.count
    before_state = _database_state_digest(engine, tables)
    matching = _post_registration(app, payload, key)
    mismatched = _post_registration(app, _canonical_field_mutations(payload)[0], key)
    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_ledger = _table_counts(factory, ("registration_idempotency_records",))[
        "registration_idempotency_records"
    ]
    matching_signature = _safe_response_signature(matching)
    mismatched_signature = _safe_response_signature(mismatched)
    return {
        "matching_status": matching.status_code,
        "mismatched_status": mismatched.status_code,
        "matching_code": _response_error_code(matching),
        "mismatched_code": _response_error_code(mismatched),
        "matching_field": _response_error_field(matching),
        "mismatched_field": _response_error_field(mismatched),
        "uniform_signature": matching_signature == mismatched_signature,
        "graph_delta": _count_delta(before_graph, after_graph),
        "ledger_delta": after_ledger - before_ledger,
        "delivery_delta": sender.count - before_delivery,
        "state_unchanged": _database_state_digest(engine, tables) == before_state,
    }


def _run_activation_probe(engine: Engine) -> dict[str, Any]:
    from app.core import retention

    sender = _CapturingSender()
    app, factory = _build_app_context(engine, sender)
    payload = _base_registration_payload(201)
    wire_key = "nyay17-activation-synthetic"
    registered = _post_registration(app, payload, wire_key)
    handle = _response_handle(registered)
    delivered_code = sender.sent[-1][1] if sender.sent else None
    with TestClient(app, raise_server_exceptions=False) as client:
        verified = (
            client.post(
                "/api/v1/auth/student/otp/verify",
                json={"registration_id": handle, "code": delivered_code},
            )
            if handle is not None and delivered_code is not None
            else None
        )
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        retired_exact = _ledger_state_exact(record, "retired")
        registration = _registration_rows_for_handle(session, handle)
        lifecycle_advanced = bool(
            registration is not None
            and _activation_route_state_is_exact(registration.status)
        )
    terminal = _terminal_replay_observation(
        engine, app, factory, sender, payload, wire_key
    )
    with factory() as session:
        registration = _registration_rows_for_handle(session, handle)
        if registration is not None:
            retention.anonymise_registration(session, registration)
            session.commit()
        record = _ledger_for_key(session, wire_key)
        first_terminal_cause_preserved = _ledger_state_exact(record, "retired")
        registration = _registration_rows_for_handle(session, handle)
        retained_row_erased = bool(
            registration is not None and registration.status == "deleted"
        )
    post_retention_terminal = _terminal_replay_observation(
        engine, app, factory, sender, payload, wire_key
    )
    return {
        "verification_status": verified.status_code if verified is not None else 0,
        "retired_exact": retired_exact,
        "lifecycle_advanced": lifecycle_advanced,
        "terminal": terminal,
        "activation_then_retention_preserves_retired": bool(
            first_terminal_cause_preserved
            and retained_row_erased
            and _retired_observation_passes(post_retention_terminal)
        ),
    }


def _run_activation_retention_race(engine: Engine) -> dict[str, Any]:
    from app.core import retention
    from app.models.registration import (
        RegistrationIdempotencyRecord,
        StudentRegistration,
    )
    from app.services.registration_service import (
        registration_idempotency_key_hash,
    )

    sender = _CapturingSender()
    initial_app, factory = _build_app_context(engine, sender)
    payload = _base_registration_payload(202)
    wire_key = "nyay17-activation-retention-race"
    registered = _post_registration(initial_app, payload, wire_key)
    handle = _response_handle(registered)
    delivered_code = sender.sent[-1][1] if sender.sent else None
    if handle is None or delivered_code is None:
        return {"passed": False, "cases": 1}
    registration_id = uuid.UUID(handle)
    tracker = _PgBackendTracker()
    app, _ = _build_app_context(engine, sender, backend_tracker=tracker)

    def activate() -> Any:
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.post(
                "/api/v1/auth/student/otp/verify",
                json={"registration_id": handle, "code": delivered_code},
            )

    def retain() -> bool:
        with factory() as session:
            tracker.record(int(session.scalar(text("SELECT pg_backend_pid()"))))
            registration = session.get(StudentRegistration, registration_id)
            if registration is None:
                return False
            retention.anonymise_registration(session, registration)
            session.commit()
            return True

    control = factory()
    activation_waited = False
    both_waited = False
    try:
        record_id = control.scalar(
            select(RegistrationIdempotencyRecord.id).where(
                RegistrationIdempotencyRecord.idempotency_key_hash
                == registration_idempotency_key_hash(wire_key)
            )
        )
        if record_id is None:
            return {"passed": False, "cases": 1}
        control.scalar(
            select(RegistrationIdempotencyRecord)
            .where(RegistrationIdempotencyRecord.id == record_id)
            .with_for_update()
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            activation_future = executor.submit(activate)
            activation_waited = _wait_for_request_lock(
                engine,
                tracker,
                expected_backends=1,
                minimum_waiters=1,
            )
            retention_future = executor.submit(retain)
            both_waited = _wait_for_request_lock(
                engine,
                tracker,
                expected_backends=2,
                minimum_waiters=2,
            )
            control.commit()
            activation_response = activation_future.result(timeout=30)
            retention_completed = retention_future.result(timeout=30)
            race_backend_count = tracker.count
    finally:
        control.rollback()
        control.close()
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        retired_preserved = _ledger_state_exact(record, "retired")
        registration = _registration_rows_for_handle(session, handle)
        row_erased = bool(registration is not None and registration.status == "deleted")
    terminal = _terminal_replay_observation(
        engine, app, factory, sender, payload, wire_key
    )

    # Reverse the queue: retention wins and activation must observe only the
    # permanent erased outcome after its stale association wait.
    sender_two = _CapturingSender()
    initial_app_two, factory_two = _build_app_context(engine, sender_two)
    payload_two = _base_registration_payload(203)
    wire_key_two = "nyay17-retention-activation-race"
    registered_two = _post_registration(initial_app_two, payload_two, wire_key_two)
    handle_two = _response_handle(registered_two)
    delivered_code_two = sender_two.sent[-1][1] if sender_two.sent else None
    retention_wins = False
    if handle_two is not None and delivered_code_two is not None:
        registration_id_two = uuid.UUID(handle_two)
        tracker_two = _PgBackendTracker()
        app_two, _ = _build_app_context(engine, sender_two, backend_tracker=tracker_two)

        def retain_two() -> bool:
            with factory_two() as session:
                tracker_two.record(int(session.scalar(text("SELECT pg_backend_pid()"))))
                registration = session.get(StudentRegistration, registration_id_two)
                if registration is None:
                    return False
                retention.anonymise_registration(session, registration)
                session.commit()
                return True

        def activate_two() -> Any:
            with TestClient(app_two, raise_server_exceptions=False) as client:
                return client.post(
                    "/api/v1/auth/student/otp/verify",
                    json={
                        "registration_id": handle_two,
                        "code": delivered_code_two,
                    },
                )

        control_two = factory_two()
        try:
            record_id_two = control_two.scalar(
                select(RegistrationIdempotencyRecord.id).where(
                    RegistrationIdempotencyRecord.idempotency_key_hash
                    == registration_idempotency_key_hash(wire_key_two)
                )
            )
            if record_id_two is not None:
                control_two.scalar(
                    select(RegistrationIdempotencyRecord)
                    .where(RegistrationIdempotencyRecord.id == record_id_two)
                    .with_for_update()
                )
                with ThreadPoolExecutor(max_workers=2) as executor:
                    retention_future_two = executor.submit(retain_two)
                    retention_waited_two = _wait_for_request_lock(
                        engine,
                        tracker_two,
                        expected_backends=1,
                        minimum_waiters=1,
                    )
                    activation_future_two = executor.submit(activate_two)
                    both_waited_two = _wait_for_request_lock(
                        engine,
                        tracker_two,
                        expected_backends=2,
                        minimum_waiters=2,
                    )
                    control_two.commit()
                    retention_completed_two = retention_future_two.result(timeout=30)
                    activation_response_two = activation_future_two.result(timeout=30)
                    race_backend_count_two = tracker_two.count
                with factory_two() as session:
                    erased_two = _ledger_state_exact(
                        _ledger_for_key(session, wire_key_two), "erased"
                    )
                    row_erased_two = bool(
                        (
                            registration := _registration_rows_for_handle(
                                session, handle_two
                            )
                        )
                        is not None
                        and registration.status == "deleted"
                    )
                terminal_two = _terminal_replay_observation(
                    engine,
                    app_two,
                    factory_two,
                    sender_two,
                    payload_two,
                    wire_key_two,
                )
                retention_wins = bool(
                    retention_waited_two
                    and both_waited_two
                    and _backend_cardinality_is_exact(race_backend_count_two, 2)
                    and retention_completed_two
                    and activation_response_two.status_code in {404, 409}
                    and erased_two
                    and row_erased_two
                    and _retired_observation_passes(terminal_two)
                    and sender_two.count == 1
                )
        finally:
            control_two.rollback()
            control_two.close()
    passed = bool(
        registered.status_code == 201
        and activation_waited
        and both_waited
        and _backend_cardinality_is_exact(race_backend_count, 2)
        and activation_response.status_code == 200
        and retention_completed
        and retired_preserved
        and row_erased
        and _retired_observation_passes(terminal)
        and sender.count == 1
        and retention_wins
    )
    return {"passed": passed, "cases": 2}


def _run_retention_probe(engine: Engine) -> dict[str, Any]:
    from app.core import retention

    sender = _CapturingSender()
    app, factory = _build_app_context(engine, sender)
    cases: list[bool] = []

    # New-ledger anonymisation retains only an erased key-hash tombstone.
    anonymise_payload = _base_registration_payload(211)
    anonymise_key = "nyay17-retention-anonymise"
    anonymise_response = _post_registration(app, anonymise_payload, anonymise_key)
    with factory() as session:
        registration = _registration_rows_for_handle(
            session, _response_handle(anonymise_response)
        )
        if registration is not None:
            retention.anonymise_registration(session, registration)
            session.commit()
        record = _ledger_for_key(session, anonymise_key)
        erased = _ledger_state_exact(record, "erased")
        registration = _registration_rows_for_handle(
            session, _response_handle(anonymise_response)
        )
        row_erased = bool(
            registration is not None
            and registration.status == "deleted"
            and registration.idempotency_key is None
            and registration.idempotency_key_legacy is False
        )
    cases.append(
        erased
        and row_erased
        and _retired_observation_passes(
            _terminal_replay_observation(
                engine,
                app,
                factory,
                sender,
                anonymise_payload,
                anonymise_key,
            )
        )
    )

    # Hard deletion must leave the same non-PII erased tombstone.
    delete_payload = _base_registration_payload(212)
    delete_key = "nyay17-retention-delete"
    delete_response = _post_registration(app, delete_payload, delete_key)
    delete_handle = _response_handle(delete_response)
    with factory() as session:
        registration = _registration_rows_for_handle(session, delete_handle)
        if registration is not None:
            retention.delete_registration(session, registration)
            session.commit()
        record = _ledger_for_key(session, delete_key)
        erased = _ledger_state_exact(record, "erased")
        row_absent = _registration_rows_for_handle(session, delete_handle) is None
    cases.append(
        erased
        and row_absent
        and _retired_observation_passes(
            _terminal_replay_observation(
                engine, app, factory, sender, delete_payload, delete_key
            )
        )
    )

    # A historical raw-key row is converted to a hash-only tombstone before
    # its raw reservation is cleared.
    legacy_payload = _base_registration_payload(213)
    legacy_key = "nyay17-retention-legacy"
    legacy_response = _post_registration(app, legacy_payload, None)
    legacy_handle = _response_handle(legacy_response)
    with factory() as session:
        registration = _registration_rows_for_handle(session, legacy_handle)
        if registration is not None:
            registration.idempotency_key = legacy_key
            registration.idempotency_key_legacy = True
            session.commit()
            retention.anonymise_registration(session, registration)
            session.commit()
        record = _ledger_for_key(session, legacy_key)
        erased = _ledger_state_exact(record, "erased")
        registration = _registration_rows_for_handle(session, legacy_handle)
        raw_cleared = bool(
            registration is not None
            and registration.idempotency_key is None
            and registration.idempotency_key_legacy is False
        )
    cases.append(
        erased
        and raw_cleared
        and _retired_observation_passes(
            _terminal_replay_observation(
                engine, app, factory, sender, legacy_payload, legacy_key
            )
        )
    )
    return {"passed": all(cases), "cases": len(cases)}


def _run_pending_crash_probe(engine: Engine) -> dict[str, Any]:
    ledger_table = ("registration_idempotency_records",)
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    crash_sender = _CrashSender()
    crash_app, factory = _build_app_context(engine, crash_sender)
    payload = _base_registration_payload(221)
    wire_key = "nyay17-pending-crash"
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    crashed = _post_registration(crash_app, payload, wire_key)
    after_crash_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_crash_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        pending_exact = _ledger_state_exact(record, "pending")
        pending_handle = str(record.registration_id) if record is not None else None

    mismatch_before = _database_state_digest(engine, all_tables)
    mismatch_delivery_before = crash_sender.count
    mismatch = _post_registration(
        crash_app, _canonical_field_mutations(payload)[0], wire_key
    )
    mismatch_unchanged = bool(
        _database_state_digest(engine, all_tables) == mismatch_before
        and crash_sender.count == mismatch_delivery_before
    )

    resume_sender = _CapturingSender()
    resume_app, _ = _build_app_context(engine, resume_sender)
    resume_graph_before = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    resumed = _post_registration(resume_app, payload, wire_key)
    resume_graph_after = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    with factory() as session:
        succeeded_exact = _ledger_state_exact(
            _ledger_for_key(session, wire_key), "succeeded"
        )
    followup_before = _database_state_digest(engine, all_tables)
    delivery_before = resume_sender.count
    followup = _post_registration(resume_app, payload, wire_key)
    followup_stable = bool(
        followup.status_code == 201
        and _response_handle(followup) == _response_handle(resumed)
        and resume_sender.count == delivery_before
        and _database_state_digest(engine, all_tables) == followup_before
    )
    observation = {
        "crash_status": crashed.status_code,
        "pending_state_exact": pending_exact,
        "pending_mismatch_status": mismatch.status_code,
        "pending_mismatch_code": _response_error_code(mismatch),
        "pending_mismatch_field": _response_error_field(mismatch),
        "resume_status": resumed.status_code,
        "resume_same_public_handle": _response_handle(resumed) == pending_handle,
        "succeeded_state_exact": succeeded_exact,
        "ledger_delta": after_crash_ledger - before_ledger,
        "graph_delta": _count_delta(before_graph, after_crash_graph),
        "resume_graph_delta_zero": _zero_deltas(
            _count_delta(resume_graph_before, resume_graph_after)
        ),
        "crash_provider_invocations": crash_sender.attempts,
        "crash_provider_acceptances": crash_sender.count,
        "resume_provider_acceptances": resume_sender.count,
        "provider_acceptances_total": crash_sender.count + resume_sender.count,
        "followup_stable": followup_stable and mismatch_unchanged,
    }
    return {
        "passed": _pending_resume_observation_passes(observation),
        "crash_provider_invocations": crash_sender.attempts,
        "crash_provider_acceptances": crash_sender.count,
        "resume_provider_acceptances": resume_sender.count,
    }


def _run_accepted_crash_projection(engine: Engine) -> dict[str, Any]:
    """Observe—not close—the accepted-before-finalization redelivery gap."""

    ledger_table = ("registration_idempotency_records",)
    sender = _AcceptedCrashSender()
    app, factory = _build_app_context(engine, sender)
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    response = _post_registration(
        app,
        _base_registration_payload(222),
        "nyay17-accepted-crash-projection",
    )
    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        record = _ledger_for_key(session, "nyay17-accepted-crash-projection")
        pending_exact = _ledger_state_exact(record, "pending")
    observed = bool(
        response.status_code == 500
        and sender.count == 1
        and pending_exact
        and _single_graph_delta(_count_delta(before_graph, after_graph))
        and after_ledger - before_ledger == 1
    )
    return {
        "observed": observed,
        "provider_acceptances": sender.count,
        "pending_state_exact": pending_exact,
    }


def _age_signup_challenge(
    factory: sessionmaker[Session],
    registration_handle: str | None,
    *,
    age_days: int = RECENT_PROBE_HISTORY_AGE_DAYS,
) -> None:
    from app.models.registration import OtpChallenge

    registration_id = uuid.UUID(str(registration_handle))
    aged_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    with factory() as session:
        challenges = list(
            session.scalars(
                select(OtpChallenge).where(
                    OtpChallenge.registration_id == registration_id,
                    OtpChallenge.purpose == "signup",
                )
            )
        )
        for challenge in challenges:
            metadata = dict(challenge.metadata_json or {})
            metadata["issued_at"] = aged_at.isoformat()
            challenge.metadata_json = metadata
            challenge.created_at = aged_at
            challenge.expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        session.commit()


def _pending_resend_shape(
    factory: sessionmaker[Session],
    *,
    registration_handle: str | None,
    wire_key: str,
    original_outbox_id: uuid.UUID | None,
) -> dict[str, Any]:
    from app.models.registration import OtpChallenge, OtpOutbox

    registration_id = uuid.UUID(str(registration_handle))
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        replacement_id = record.outbox_id if record is not None else None
        original = (
            session.get(OtpOutbox, original_outbox_id)
            if original_outbox_id is not None
            else None
        )
        active = list(
            session.scalars(
                select(OtpChallenge).where(
                    OtpChallenge.registration_id == registration_id,
                    OtpChallenge.purpose == "signup",
                    OtpChallenge.consumed_at.is_(None),
                )
            )
        )
        challenge_ids = list(
            session.scalars(
                select(OtpChallenge.id).where(
                    OtpChallenge.registration_id == registration_id,
                    OtpChallenge.purpose == "signup",
                )
            )
        )
        relayable = (
            list(
                session.scalars(
                    select(OtpOutbox.id).where(
                        OtpOutbox.challenge_id.in_(challenge_ids),
                        OtpOutbox.status.in_(("pending", "failed")),
                        OtpOutbox.code_ct.is_not(None),
                    )
                )
            )
            if challenge_ids
            else []
        )
        return {
            "ledger_repointed_to_replacement": bool(
                replacement_id is not None
                and original_outbox_id is not None
                and replacement_id != original_outbox_id
            ),
            "ledger_succeeded_unlinked_before_replacement": bool(
                record is not None
                and record.state == "succeeded"
                and record.outbox_id is None
            ),
            "superseded_payload_nonrelayable": bool(
                original is not None
                and original.status in {"void", "sent"}
                and original.code_ct is None
            ),
            "active_signup_challenges": len(active),
            "relayable_signup_payloads": len(relayable),
        }


def _resend_graph_is_single(
    before: Mapping[str, int], after: Mapping[str, int]
) -> bool:
    expected = {
        "users": 1,
        "student_registrations": 1,
        "student_profiles": 1,
        "student_verifications": 1,
        "guardian_consents": 0,
        "consents": 1,
        "otp_challenges": 2,
        "otp_outbox": 2,
        "audit_events": 1,
    }
    return _count_delta(before, after) == expected


def _run_pending_resend_case(
    engine: Engine,
    *,
    sequence: int,
    concurrent: bool,
    pre_relay: bool = False,
) -> bool:
    before_graph: dict[str, int]
    crash_sender = _CrashSender()
    crash_app, factory = _build_app_context(engine, crash_sender)
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    payload = _base_registration_payload(sequence)
    wire_key = f"nyay17-pending-resend-{sequence}"
    crashed = _post_registration(crash_app, payload, wire_key)
    with factory() as session:
        handle = _durable_registration_handle_for_key(session, wire_key)
        initial_record = _ledger_for_key(session, wire_key)
        original_outbox_id = (
            initial_record.outbox_id if initial_record is not None else None
        )
        pending_exact = _ledger_state_exact(initial_record, "pending")
    if (
        crashed.status_code != 500
        or _response_handle(crashed) is not None
        or not pending_exact
        or handle is None
    ):
        return False
    relay_passed = True
    if pre_relay:
        from app.services import otp_outbox

        relay_sender = _CapturingSender()
        with factory() as session:
            relay_passed = bool(
                original_outbox_id is not None
                and otp_outbox.run_delivery(
                    session,
                    otp_outbox.DeliveryIntent(outbox_id=original_outbox_id),
                    relay_sender,
                    raise_on_failure=True,
                )
                and relay_sender.count == 1
                and _ledger_state_exact(_ledger_for_key(session, wire_key), "pending")
            )
    _age_signup_challenge(factory, handle)

    sender: _CapturingSender = _BlockingSender()
    if concurrent:
        tracker = _PgBackendTracker()
        app, _ = _build_app_context(engine, sender, backend_tracker=tracker)
        with ThreadPoolExecutor(max_workers=2) as executor:
            resend_future = executor.submit(_post_signup_resend, app, handle)
            if not sender.entered.wait(timeout=15):
                sender.release.set()
                return False
            shape = _pending_resend_shape(
                factory,
                registration_handle=handle,
                wire_key=wire_key,
                original_outbox_id=original_outbox_id,
            )
            replay_future = executor.submit(_post_registration, app, payload, wire_key)
            waited = _wait_for_request_lock(engine, tracker, expected_backends=2)
            backend_count = tracker.count
            sender.release.set()
            resend = resend_future.result(timeout=30)
            replay = replay_future.result(timeout=30)
    else:
        app, _ = _build_app_context(engine, sender)
        with ThreadPoolExecutor(max_workers=1) as executor:
            resend_future = executor.submit(_post_signup_resend, app, handle)
            if not sender.entered.wait(timeout=15):
                sender.release.set()
                return False
            shape = _pending_resend_shape(
                factory,
                registration_handle=handle,
                wire_key=wire_key,
                original_outbox_id=original_outbox_id,
            )
            sender.release.set()
            resend = resend_future.result(timeout=30)
        replay = _post_registration(app, payload, wire_key)
        waited = False
        backend_count = 0

    with factory() as session:
        succeeded = _ledger_state_exact(_ledger_for_key(session, wire_key), "succeeded")
    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    final_shape = _pending_resend_shape(
        factory,
        registration_handle=handle,
        wire_key=wire_key,
        original_outbox_id=original_outbox_id,
    )
    observation = {
        "resend_status": resend.status_code,
        "replay_status": replay.status_code,
        "same_public_handle": _response_handle(replay) == handle,
        "ledger_repointed_to_replacement": shape["ledger_repointed_to_replacement"],
        "ledger_succeeded_unlinked_before_replacement": shape[
            "ledger_succeeded_unlinked_before_replacement"
        ],
        "superseded_payload_nonrelayable": shape["superseded_payload_nonrelayable"],
        "succeeded_state_exact": succeeded,
        "registration_graph_single": _resend_graph_is_single(before_graph, after_graph),
        "active_signup_challenges": final_shape["active_signup_challenges"],
        "relayable_signup_payloads": final_shape["relayable_signup_payloads"],
        "provider_acceptances": sender.count,
        "backend_count": backend_count,
        "db_lock_wait_observed": waited,
    }
    return bool(
        relay_passed
        and _pending_resend_observation_passes(
            observation,
            concurrent=concurrent,
            pre_relay=pre_relay,
        )
    )


def _run_resend_helper_terminal_wait_case(
    engine: Engine,
    *,
    sequence: int,
    winner: str,
) -> bool:
    """Force the resend helper to wait after discovering ledger authority."""

    from app.core import retention
    from app.models.registration import RegistrationIdempotencyRecord
    from app.services import otp_outbox, otp_service, registration_service
    from app.services.otp_sender import OtpSendError

    crash_sender = _CrashSender()
    crash_app, factory = _build_app_context(engine, crash_sender)
    payload = _base_registration_payload(sequence)
    wire_key = f"nyay17-resend-helper-terminal-{sequence}"
    crashed = _post_registration(crash_app, payload, wire_key)
    with factory() as session:
        handle = _durable_registration_handle_for_key(session, wire_key)
    if (
        crashed.status_code != 500
        or _response_handle(crashed) is not None
        or handle is None
    ):
        return False
    registration_id = uuid.UUID(handle)
    _age_signup_challenge(factory, handle)
    with factory() as session:
        _, intent = otp_service.resend(
            session,
            registration_id,
            datetime.now(timezone.utc),
            purpose="signup",
            destination=str(payload["mobile"]),
        )
        session.commit()
        record = _ledger_for_key(session, wire_key)
        replacement_linked = bool(
            _ledger_state_exact(record, "pending")
            and record.outbox_id == intent.outbox_id
        )
    if not replacement_linked:
        return False

    winner_sender = _CapturingSender()
    activation_code = None
    if winner == "retired":
        with factory() as session:
            delivered = otp_outbox.run_delivery(
                session,
                intent,
                winner_sender,
                raise_on_failure=True,
            )
        if not delivered or winner_sender.count != 1:
            return False
        activation_code = winner_sender.sent[-1][1]

    unrelated_handle = None
    if winner == "corrupt":
        unrelated_sender = _CapturingSender()
        unrelated_app, _ = _build_app_context(engine, unrelated_sender)
        unrelated = _post_registration(
            unrelated_app, _base_registration_payload(sequence + 100), None
        )
        unrelated_handle = _response_handle(unrelated)
        if unrelated.status_code != 201 or unrelated_handle is None:
            return False

    helper_sender = _CapturingSender()
    tracker = _PgBackendTracker()

    def helper() -> dict[str, Any]:
        with factory() as session:
            tracker.record(int(session.scalar(text("SELECT pg_backend_pid()"))))
            try:
                claimed = registration_service.finalize_pending_resend_if_claimed(
                    session, registration_id, intent, helper_sender
                )
                delivery_available = None
                if not claimed:
                    try:
                        delivery_available = otp_outbox.run_delivery(
                            session,
                            intent,
                            helper_sender,
                            raise_on_failure=True,
                        )
                    except OtpSendError:
                        delivery_available = False
                return {
                    "runtime_error": False,
                    "claimed": claimed,
                    "delivery_available": delivery_available,
                }
            except RuntimeError:
                session.rollback()
                return {
                    "runtime_error": True,
                    "claimed": None,
                    "delivery_available": None,
                }

    winner_session = factory()
    helper_waited = False
    winner_pid_distinct = False
    try:
        record = winner_session.scalar(
            select(RegistrationIdempotencyRecord)
            .where(RegistrationIdempotencyRecord.registration_id == registration_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        registration = _registration_rows_for_handle(winner_session, handle)
        if record is None or registration is None:
            return False
        winner_pid = int(winner_session.scalar(text("SELECT pg_backend_pid()")))
        with ThreadPoolExecutor(max_workers=1) as executor:
            helper_future = executor.submit(helper)
            helper_waited = _wait_for_request_lock(
                engine,
                tracker,
                expected_backends=1,
                minimum_waiters=1,
            )
            winner_pid_distinct = winner_pid not in tracker.private_snapshot()
            if winner == "failed":
                registration_service.compensate_delete(
                    winner_session,
                    registration_id,
                    idempotency_record=record,
                )
            elif winner == "retired":
                if activation_code is None:
                    return False
                otp_service.verify(
                    winner_session,
                    registration_id,
                    activation_code,
                    datetime.now(timezone.utc),
                )
            elif winner == "erased":
                retention.anonymise_registration(winner_session, registration)
                winner_session.commit()
            elif winner == "corrupt" and unrelated_handle is not None:
                record.registration_id = uuid.UUID(unrelated_handle)
                winner_session.commit()
            else:
                return False
            winner_state = _database_state_digest(
                engine,
                REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",),
            )
            helper_result = helper_future.result(timeout=30)
    finally:
        winner_session.rollback()
        winner_session.close()

    stable_after_helper = bool(
        _database_state_digest(
            engine,
            REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",),
        )
        == winner_state
    )
    if winner == "corrupt":
        passed = bool(
            helper_waited
            and winner_pid_distinct
            and tracker.count == 1
            and helper_result["runtime_error"] is True
            and helper_sender.count == 0
            and stable_after_helper
        )
        if passed:
            with factory() as session:
                record = _ledger_for_key(session, wire_key)
                if record is not None:
                    record.registration_id = registration_id
                    session.commit()
        return passed

    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        terminal_state_exact = _ledger_state_exact(record, winner)
    replay_app, _ = _build_app_context(engine, helper_sender)
    replay_state = _database_state_digest(
        engine,
        REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",),
    )
    exact = _post_registration(replay_app, payload, wire_key)
    mismatch = _post_registration(
        replay_app, _canonical_field_mutations(payload)[0], wire_key
    )
    if winner == "failed":
        terminal_http_exact = bool(
            exact.status_code == 502
            and _response_error_code(exact) == "otp_delivery_failed"
            and _response_error_field(exact) is None
            and mismatch.status_code == 409
            and _response_error_code(mismatch) == "idempotency_conflict"
            and _response_error_field(mismatch) == "Idempotency-Key"
        )
        expected_delivery_available = False
    else:
        terminal_http_exact = bool(
            exact.status_code == 409
            and mismatch.status_code == 409
            and _response_error_code(exact)
            == _response_error_code(mismatch)
            == "registration_replay_expired"
            and _safe_response_signature(exact) == _safe_response_signature(mismatch)
        )
        expected_delivery_available = winner == "retired"
    return bool(
        helper_waited
        and winner_pid_distinct
        and tracker.count == 1
        and helper_result["runtime_error"] is False
        and helper_result["claimed"] is False
        and helper_result["delivery_available"] is expected_delivery_available
        and helper_sender.count == 0
        and winner_sender.count == (1 if winner == "retired" else 0)
        and terminal_state_exact
        and terminal_http_exact
        and stable_after_helper
        and _database_state_digest(
            engine,
            REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",),
        )
        == replay_state
    )


def _run_resend_helper_terminal_wait_probes(
    engine: Engine,
) -> dict[str, Any]:
    winners = ("failed", "retired", "erased", "corrupt")
    cases = tuple(
        _run_resend_helper_terminal_wait_case(
            engine,
            sequence=240 + index,
            winner=winner,
        )
        for index, winner in enumerate(winners)
    )
    return {
        "passed": all(cases),
        "cases": len(cases),
        "product_seam_mutants_killed": int(cases[-1]),
    }


def _run_pending_resend_probes(engine: Engine) -> dict[str, Any]:
    from app.models.registration import OtpChallenge, OtpOutbox

    crash_sender = _CrashSender()
    crash_app, factory = _build_app_context(engine, crash_sender)
    payload = _base_registration_payload(225)
    wire_key = "nyay17-pending-resend-crosslink"
    pending = _post_registration(crash_app, payload, wire_key)
    with factory() as session:
        handle = _durable_registration_handle_for_key(session, wire_key)
    unrelated_sender = _CapturingSender()
    unrelated_app, _ = _build_app_context(engine, unrelated_sender)
    unrelated = _post_registration(unrelated_app, _base_registration_payload(226), None)
    unrelated_handle = _response_handle(unrelated)
    crosslink_installed = False
    original_pending_outbox_id = None
    if handle is not None and unrelated_handle is not None:
        with factory() as session:
            unrelated_registration_id = uuid.UUID(unrelated_handle)
            unrelated_outbox_id = session.scalar(
                select(OtpOutbox.id)
                .join(
                    OtpChallenge,
                    OtpChallenge.id == OtpOutbox.challenge_id,
                )
                .where(
                    OtpChallenge.registration_id == unrelated_registration_id,
                    OtpChallenge.purpose == "signup",
                )
            )
            record = _ledger_for_key(session, wire_key)
            if record is not None and unrelated_outbox_id is not None:
                original_pending_outbox_id = record.outbox_id
                record.outbox_id = unrelated_outbox_id
                session.commit()
                crosslink_installed = True
        _age_signup_challenge(factory, handle)
    state_before = _database_state_digest(
        engine,
        REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",),
    )
    crosslink_sender = _CapturingSender()
    crosslink_app, _ = _build_app_context(engine, crosslink_sender)
    crosslink_response = _post_signup_resend(crosslink_app, handle)
    crosslink_rejected = bool(
        pending.status_code == 500
        and _response_handle(pending) is None
        and crosslink_installed
        and crosslink_response.status_code == 500
        and crosslink_sender.count == 0
        and _database_state_digest(
            engine,
            REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",),
        )
        == state_before
    )
    if crosslink_rejected and original_pending_outbox_id is not None:
        with factory() as session:
            record = _ledger_for_key(session, wire_key)
            if record is not None:
                record.outbox_id = original_pending_outbox_id
                session.commit()
    cases = (
        _run_pending_resend_case(engine, sequence=223, concurrent=False),
        _run_pending_resend_case(engine, sequence=224, concurrent=True),
        _run_pending_resend_case(
            engine,
            sequence=228,
            concurrent=False,
            pre_relay=True,
        ),
        crosslink_rejected,
    )
    helper_waits = _run_resend_helper_terminal_wait_probes(engine)
    return {
        "passed": all(cases) and helper_waits["passed"],
        "cases": len(cases) + helper_waits["cases"],
        "product_seam_mutants_killed": int(crosslink_rejected)
        + helper_waits["product_seam_mutants_killed"],
    }


def _run_pending_retention_purge_case(
    engine: Engine, *, sequence: int, mode: str
) -> dict[str, Any]:
    from app.core import retention
    from app.db.models.audit import AuditEvent
    from app.models.registration import OtpChallenge, OtpOutbox, StudentProfile

    ledger_table = ("registration_idempotency_records",)
    entity_tables = tuple(
        table for table in REGISTRATION_GRAPH_TABLES if table != "audit_events"
    )
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    sender = _CrashSender()
    app, factory = _build_app_context(engine, sender)
    payload = _base_registration_payload(sequence)
    wire_key = f"nyay17-pending-retention-purge-{mode}"
    before_entities = _table_counts(factory, entity_tables)
    crashed = _post_registration(app, payload, wire_key)
    with factory() as session:
        handle = _durable_registration_handle_for_key(session, wire_key)
    if (
        crashed.status_code != 500
        or _response_handle(crashed) is not None
        or handle is None
    ):
        return {"passed": False, "cases": 0}
    now = datetime.now(timezone.utc)
    outbox_id = None
    if handle is not None:
        with factory() as session:
            challenge = session.scalar(
                select(OtpChallenge).where(
                    OtpChallenge.registration_id == uuid.UUID(handle),
                    OtpChallenge.purpose == "signup",
                )
            )
            record = _ledger_for_key(session, wire_key)
            if challenge is not None:
                # Use a uniquely far-old window so this exact subject is the
                # only eligible candidate even after prior probes deliberately
                # leave recently aged resend history in the shared scratch DB.
                challenge.created_at = now - timedelta(
                    days=PENDING_RETENTION_TARGET_AGE_DAYS
                )
                challenge.expires_at = now - timedelta(minutes=1)
            if record is not None:
                outbox_id = record.outbox_id
            session.commit()
    with factory() as session:
        counts = retention.purge_expired(
            session,
            now=now,
            policy=retention.RetentionPolicy(
                registration_pending_days=None,
                registration_inactive_days=None,
                otp_challenge_days=PENDING_RETENTION_CUTOFF_DAYS,
                recovery_session_days=None,
                audit_events_days=None,
                mode=mode,
            ),
        )
        session.commit()
    after_entities = _table_counts(factory, entity_tables)
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        erased_exact = _ledger_state_exact(record, "erased")
        outbox = session.get(OtpOutbox, outbox_id) if outbox_id else None
        relayable_absent = bool(
            outbox is None or outbox.status == "void" and outbox.code_ct is None
        )
        registration = _registration_rows_for_handle(session, handle)
        profile = (
            session.scalar(
                select(StudentProfile).where(
                    StudentProfile.registration_id == uuid.UUID(str(handle))
                )
            )
            if handle is not None
            else None
        )
        expected_action = (
            "student.registration.deleted"
            if mode == "delete"
            else "student.registration.anonymised"
        )
        transition_audits = (
            list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_id == uuid.UUID(str(handle)),
                        AuditEvent.action == expected_action,
                    )
                )
            )
            if handle is not None
            else []
        )
        reason_audits = (
            list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_id == uuid.UUID(str(handle)),
                        AuditEvent.action
                        == "student.registration.otp_retention_expired",
                    )
                )
            )
            if handle is not None
            else []
        )
        erased_registration_shape = bool(
            registration is not None
            and registration.status == "deleted"
            and registration.deleted_at is not None
            and registration.mobile_ct == retention.ANONYMISED
            and registration.dob_ct == retention.ANONYMISED
            and registration.dob_hash_state == "erased"
            and registration.first_name == retention.ANONYMISED
            and registration.middle_name is None
            and registration.last_name == retention.ANONYMISED
            and registration.idempotency_key is None
            and registration.idempotency_key_legacy is False
            and profile is not None
            and profile.college is None
            and profile.year_of_study is None
            and profile.enrolment_ct == retention.ANONYMISED
            and profile.institutional_email_ct == retention.ANONYMISED
            and profile.bar_enrolment_ct == retention.ANONYMISED
            and profile.enrolment_hash is None
            and profile.institutional_email_hash is None
            and profile.bar_enrolment_hash is None
        )
    entity_delta = _count_delta(before_entities, after_entities)
    expected_anonymised_delta = {
        "users": 1,
        "student_registrations": 1,
        "student_profiles": 1,
        "student_verifications": 1,
        "guardian_consents": 0,
        "consents": 1,
        "otp_challenges": 0,
        "otp_outbox": 0,
    }
    policy_shape_exact = bool(
        _zero_deltas(entity_delta)
        if mode == "delete"
        else erased_registration_shape and entity_delta == expected_anonymised_delta
    )
    replay_state = _database_state_digest(engine, all_tables)
    replay_delivery = sender.count
    responses = [_post_registration(app, payload, wire_key)]
    responses.extend(
        _post_registration(app, mutation, wire_key)
        for mutation in _canonical_field_mutations(payload)
    )
    observation = {
        "purged_challenges": counts.get("otp_challenges", 0),
        "registration_transitions": counts.get("registrations", 0),
        "erased_state_exact": erased_exact,
        "policy_mode_shape_exact": policy_shape_exact,
        "audit_action_exact": bool(
            len(transition_audits) == 1
            and transition_audits[0].after_state == {"status": "deleted"}
            and len(reason_audits) == 1
            and reason_audits[0].after_state == {"mode": mode}
        ),
        "relayable_payload_absent": relayable_absent,
        "terminal_cases": len(responses),
        "all_terminal_statuses_409": all(
            response.status_code == 409 for response in responses
        ),
        "all_terminal_codes_expired": all(
            _response_error_code(response) == "registration_replay_expired"
            for response in responses
        ),
        "all_terminal_fields_idempotency_key": all(
            _response_error_field(response) == "Idempotency-Key"
            for response in responses
        ),
        "uniform_response_bytes": len(
            {bytes(response.content) for response in responses}
        )
        == 1,
        "provider_acceptances": sender.count,
        "state_unchanged_on_replays": bool(
            sender.count == replay_delivery
            and _database_state_digest(engine, all_tables) == replay_state
        ),
    }
    return {
        "passed": _pending_purge_observation_passes(observation),
        "cases": len(responses),
    }


def _run_succeeded_retention_purge_probe(engine: Engine) -> bool:
    from app.core import retention
    from app.models.registration import OtpChallenge, OtpOutbox

    sender = _CapturingSender()
    app, factory = _build_app_context(engine, sender)
    payload = _base_registration_payload(229)
    wire_key = "nyay17-succeeded-retention-purge"
    registered = _post_registration(app, payload, wire_key)
    handle = _response_handle(registered)
    now = datetime.now(timezone.utc)
    if handle is None:
        return False
    registration_id = uuid.UUID(handle)
    with factory() as session:
        challenge = session.scalar(
            select(OtpChallenge).where(
                OtpChallenge.registration_id == registration_id,
                OtpChallenge.purpose == "signup",
            )
        )
        if challenge is None:
            return False
        challenge.created_at = now - timedelta(days=PENDING_RETENTION_TARGET_AGE_DAYS)
        session.commit()
    with factory() as session:
        counts = retention.purge_expired(
            session,
            now=now,
            policy=retention.RetentionPolicy(
                registration_pending_days=None,
                registration_inactive_days=None,
                otp_challenge_days=PENDING_RETENTION_CUTOFF_DAYS,
                recovery_session_days=None,
                audit_events_days=None,
                mode="anonymise",
            ),
        )
        session.commit()
    with factory() as session:
        succeeded_after_purge = _ledger_state_exact(
            _ledger_for_key(session, wire_key), "succeeded"
        )
        registration_preserved = (
            _registration_rows_for_handle(session, handle) is not None
        )
        history_removed = not list(
            session.scalars(
                select(OtpChallenge.id).where(
                    OtpChallenge.registration_id == registration_id,
                    OtpChallenge.purpose == "signup",
                )
            )
        )
    delivery_before_replay = sender.count
    replay = _post_registration(app, payload, wire_key)
    replay_stable = bool(
        replay.status_code == 201
        and _response_handle(replay) == handle
        and sender.count == delivery_before_replay
    )
    resend = _post_signup_resend(app, handle)
    with factory() as session:
        succeeded_after_resend = _ledger_state_exact(
            _ledger_for_key(session, wire_key), "succeeded"
        )
        active = list(
            session.scalars(
                select(OtpChallenge).where(
                    OtpChallenge.registration_id == registration_id,
                    OtpChallenge.purpose == "signup",
                    OtpChallenge.consumed_at.is_(None),
                )
            )
        )
        challenge_ids = [item.id for item in active]
        relayable = (
            list(
                session.scalars(
                    select(OtpOutbox.id).where(
                        OtpOutbox.challenge_id.in_(challenge_ids),
                        OtpOutbox.status.in_(("pending", "failed")),
                        OtpOutbox.code_ct.is_not(None),
                    )
                )
            )
            if challenge_ids
            else []
        )
    return bool(
        registered.status_code == 201
        and counts.get("otp_challenges") == 1
        and succeeded_after_purge
        and registration_preserved
        and history_removed
        and replay_stable
        and resend.status_code == 202
        and succeeded_after_resend
        and len(active) == 1
        and not relayable
        and sender.count == 2
    )


def _run_pending_sent_retention_purge_probe(engine: Engine) -> bool:
    """Reconcile a generic-relay success before removing expired OTP history."""

    from app.core import retention
    from app.models.registration import OtpChallenge
    from app.services import otp_outbox

    crash_sender = _CrashSender()
    crash_app, factory = _build_app_context(engine, crash_sender)
    payload = _base_registration_payload(234)
    wire_key = "nyay17-pending-sent-retention-purge"
    crashed = _post_registration(crash_app, payload, wire_key)
    with factory() as session:
        handle = _durable_registration_handle_for_key(session, wire_key)
        record = _ledger_for_key(session, wire_key)
        outbox_id = record.outbox_id if record is not None else None
    if (
        crashed.status_code != 500
        or _response_handle(crashed) is not None
        or handle is None
        or outbox_id is None
    ):
        return False

    relay_sender = _CapturingSender()
    with factory() as session:
        delivered = otp_outbox.run_delivery(
            session,
            otp_outbox.DeliveryIntent(outbox_id=outbox_id),
            relay_sender,
            raise_on_failure=True,
        )
    with factory() as session:
        pending_sent_exact = bool(
            _ledger_state_exact(_ledger_for_key(session, wire_key), "pending")
        )
    _age_signup_challenge(
        factory,
        handle,
        age_days=PENDING_RETENTION_TARGET_AGE_DAYS,
    )
    now = datetime.now(timezone.utc)
    with factory() as session:
        counts = retention.purge_expired(
            session,
            now=now,
            policy=retention.RetentionPolicy(
                registration_pending_days=None,
                registration_inactive_days=None,
                otp_challenge_days=PENDING_RETENTION_CUTOFF_DAYS,
                recovery_session_days=None,
                audit_events_days=None,
                mode="anonymise",
            ),
        )
        session.commit()
    registration_id = uuid.UUID(handle)
    with factory() as session:
        succeeded = _ledger_state_exact(_ledger_for_key(session, wire_key), "succeeded")
        registration_preserved = (
            _registration_rows_for_handle(session, handle) is not None
        )
        history_removed = not list(
            session.scalars(
                select(OtpChallenge.id).where(
                    OtpChallenge.registration_id == registration_id,
                    OtpChallenge.purpose == "signup",
                )
            )
        )
    replay_app, _ = _build_app_context(engine, relay_sender)
    tables = REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",)
    stable_before = _database_state_digest(engine, tables)
    delivery_before = relay_sender.count
    exact = _post_registration(replay_app, payload, wire_key)
    mismatch = _post_registration(
        replay_app, _canonical_field_mutations(payload)[0], wire_key
    )
    return bool(
        delivered
        and pending_sent_exact
        and counts.get("otp_challenges") == 1
        and counts.get("registrations") == 0
        and succeeded
        and registration_preserved
        and history_removed
        and exact.status_code == 201
        and _response_handle(exact) == handle
        and mismatch.status_code == 409
        and _response_error_code(mismatch) == "idempotency_conflict"
        and _response_error_field(mismatch) == "Idempotency-Key"
        and relay_sender.count == delivery_before == 1
        and _database_state_digest(engine, tables) == stable_before
    )


def _run_finalizer_retention_race_case(
    engine: Engine,
    *,
    sequence: int,
    finalizer_first: bool,
) -> bool:
    """Force both terminal contenders to queue after ledger discovery."""

    from app.core import retention
    from app.models.registration import RegistrationIdempotencyRecord
    from app.services.registration_service import (
        registration_idempotency_key_hash,
    )

    crash_sender = _CrashSender()
    crash_app, factory = _build_app_context(engine, crash_sender)
    payload = _base_registration_payload(sequence)
    wire_key = f"nyay17-finalizer-retention-race-{sequence}"
    crashed = _post_registration(crash_app, payload, wire_key)
    with factory() as session:
        handle = _durable_registration_handle_for_key(session, wire_key)
    if (
        crashed.status_code != 500
        or _response_handle(crashed) is not None
        or handle is None
    ):
        return False
    _age_signup_challenge(
        factory,
        handle,
        age_days=PENDING_RETENTION_TARGET_AGE_DAYS,
    )

    sender = _BlockingSender()
    tracker = _PgBackendTracker()
    app, _ = _build_app_context(engine, sender, backend_tracker=tracker)

    def finalize() -> Any:
        return _post_registration(app, payload, wire_key)

    def purge() -> dict[str, int]:
        with factory() as session:
            tracker.record(int(session.scalar(text("SELECT pg_backend_pid()"))))
            counts = retention.purge_expired(
                session,
                now=datetime.now(timezone.utc),
                policy=retention.RetentionPolicy(
                    registration_pending_days=None,
                    registration_inactive_days=None,
                    otp_challenge_days=PENDING_RETENTION_CUTOFF_DAYS,
                    recovery_session_days=None,
                    audit_events_days=None,
                    mode="anonymise",
                ),
            )
            session.commit()
            return counts

    control = factory()
    first_waited = False
    both_waited = False
    try:
        record_id = control.scalar(
            select(RegistrationIdempotencyRecord.id).where(
                RegistrationIdempotencyRecord.idempotency_key_hash
                == registration_idempotency_key_hash(wire_key)
            )
        )
        if record_id is None:
            return False
        control.scalar(
            select(RegistrationIdempotencyRecord)
            .where(RegistrationIdempotencyRecord.id == record_id)
            .with_for_update()
        )
        first, second = (finalize, purge) if finalizer_first else (purge, finalize)
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(first)
            first_waited = _wait_for_request_lock(
                engine,
                tracker,
                expected_backends=1,
                minimum_waiters=1,
            )
            second_future = executor.submit(second)
            both_waited = _wait_for_request_lock(
                engine,
                tracker,
                expected_backends=2,
                minimum_waiters=2,
            )
            control.commit()
            sender.release.set()
            first_result = first_future.result(timeout=30)
            second_result = second_future.result(timeout=30)
            race_backend_count = tracker.count
    finally:
        sender.release.set()
        control.rollback()
        control.close()

    finalizer_response, purge_counts = (
        (first_result, second_result)
        if finalizer_first
        else (second_result, first_result)
    )
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        final_state_exact = _ledger_state_exact(
            record, "succeeded" if finalizer_first else "erased"
        )
        never_failed = bool(record is not None and record.state != "failed")

    tables = REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",)
    stable_before = _database_state_digest(engine, tables)
    delivery_before = sender.count
    exact = _post_registration(app, payload, wire_key)
    mismatch = _post_registration(app, _canonical_field_mutations(payload)[0], wire_key)
    if finalizer_first:
        terminal_exact = bool(
            finalizer_response.status_code == 201
            and purge_counts.get("otp_challenges") == 1
            and purge_counts.get("registrations") == 0
            and sender.count == 1
            and exact.status_code == 201
            and _response_handle(exact) == handle
            and mismatch.status_code == 409
            and _response_error_code(mismatch) == "idempotency_conflict"
            and _response_error_field(mismatch) == "Idempotency-Key"
        )
    else:
        terminal_exact = bool(
            purge_counts.get("otp_challenges") == 1
            and purge_counts.get("registrations") == 1
            and sender.count == 0
            and finalizer_response.status_code == 409
            and _response_error_code(finalizer_response)
            == "registration_replay_expired"
            and _safe_response_signature(exact)
            == _safe_response_signature(mismatch)
            == _safe_response_signature(finalizer_response)
        )
    return bool(
        first_waited
        and both_waited
        and _backend_cardinality_is_exact(race_backend_count, 2)
        and final_state_exact
        and never_failed
        and terminal_exact
        and sender.count == delivery_before
        and _database_state_digest(engine, tables) == stable_before
    )


def _run_finalizer_retention_races(engine: Engine) -> dict[str, Any]:
    cases = (
        _run_finalizer_retention_race_case(engine, sequence=232, finalizer_first=True),
        _run_finalizer_retention_race_case(engine, sequence=233, finalizer_first=False),
    )
    return {"passed": all(cases), "cases": len(cases)}


def _run_retention_purge_probes(engine: Engine) -> dict[str, Any]:
    pending_anonymise = _run_pending_retention_purge_case(
        engine, sequence=227, mode="anonymise"
    )
    pending_delete = _run_pending_retention_purge_case(
        engine, sequence=230, mode="delete"
    )
    succeeded = _run_succeeded_retention_purge_probe(engine)
    pending_sent = _run_pending_sent_retention_purge_probe(engine)
    races = _run_finalizer_retention_races(engine)
    return {
        "passed": bool(
            pending_anonymise["passed"]
            and pending_delete["passed"]
            and succeeded
            and pending_sent
            and races["passed"]
        ),
        "cases": (
            pending_anonymise["cases"] + pending_delete["cases"] + 2 + races["cases"]
        ),
    }


def _run_failed_delivery_probe(engine: Engine) -> dict[str, Any]:
    ledger_table = ("registration_idempotency_records",)
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    entity_tables = tuple(
        table for table in REGISTRATION_GRAPH_TABLES if table != "audit_events"
    )
    sender = _FailingSender()
    app, factory = _build_app_context(engine, sender)
    payload = _base_registration_payload(231)
    wire_key = "nyay17-failed-delivery"
    before_entities = _table_counts(factory, entity_tables)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    first = _post_registration(app, payload, wire_key)
    after_entities = _table_counts(factory, entity_tables)
    after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        failed_exact = _ledger_state_exact(_ledger_for_key(session, wire_key), "failed")
    first_state = _database_state_digest(engine, all_tables)
    first_delivery = sender.count
    replay = _post_registration(app, payload, wire_key)
    replay_state = _database_state_digest(engine, all_tables)
    replay_delivery = sender.count
    mismatch = _post_registration(app, _canonical_field_mutations(payload)[0], wire_key)
    final_state = _database_state_digest(engine, all_tables)
    observation = {
        "first_status": first.status_code,
        "replay_status": replay.status_code,
        "same_error_code": (
            _response_error_code(first)
            == _response_error_code(replay)
            == "otp_delivery_failed"
        ),
        "error_fields_absent": (
            _response_error_field(first) is None
            and _response_error_field(replay) is None
        ),
        "ledger_delta": after_ledger - before_ledger,
        "replay_ledger_delta": 0,
        "replay_delivery_delta": replay_delivery - first_delivery,
        "replay_graph_delta_zero": _zero_deltas(
            _count_delta(after_entities, _table_counts(factory, entity_tables))
        ),
        "replay_state_unchanged": replay_state == first_state,
    }
    return {
        "passed": bool(
            _failure_replay_observation_passes(observation)
            and failed_exact
            and _zero_deltas(_count_delta(before_entities, after_entities))
            and sender.count == 1
            and mismatch.status_code == 409
            and _response_error_code(mismatch) == "idempotency_conflict"
            and _response_error_field(mismatch) == "Idempotency-Key"
            and final_state == replay_state
        )
    }


def _run_same_content_race(engine: Engine) -> dict[str, Any]:
    ledger_table = ("registration_idempotency_records",)
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    sender = _CapturingSender()
    tracker = _PgBackendTracker()
    app, factory = _build_app_context(engine, sender, backend_tracker=tracker)
    payload = _base_registration_payload(301)
    wire_key = "nyay17-eight-worker-same"
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    barrier = threading.Barrier(8)

    def worker() -> Any:
        barrier.wait(timeout=10)
        return _post_registration(app, payload, wire_key)

    with ThreadPoolExecutor(max_workers=8) as executor:
        responses = [
            future.result(timeout=30)
            for future in [executor.submit(worker) for _ in range(8)]
        ]
    backend_count = tracker.count
    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    handles = {_response_handle(response) for response in responses}
    with factory() as session:
        succeeded = _ledger_state_exact(_ledger_for_key(session, wire_key), "succeeded")
    stable_before = _database_state_digest(engine, all_tables)
    delivery_before = sender.count
    exact_followup = _post_registration(app, payload, wire_key)
    conflict_followup = _post_registration(
        app, _canonical_field_mutations(payload)[0], wire_key
    )
    stable_followups = bool(
        exact_followup.status_code == 201
        and _response_handle(exact_followup) in handles
        and conflict_followup.status_code == 409
        and _response_error_code(conflict_followup) == "idempotency_conflict"
        and _response_error_field(conflict_followup) == "Idempotency-Key"
        and sender.count == delivery_before
        and _database_state_digest(engine, all_tables) == stable_before
    )
    observation = {
        "statuses": [response.status_code for response in responses],
        "conflict_codes": [],
        "conflict_fields": [],
        "same_public_handle": len(handles) == 1 and None not in handles,
        "graph_delta": _count_delta(before_graph, after_graph),
        "ledger_delta": after_ledger - before_ledger,
        "delivery_delta": sender.count,
        "backend_count": backend_count,
        "stable_followups": stable_followups and succeeded,
    }
    return {"passed": _race_observation_passes(observation, mismatched=False)}


def _run_mismatch_race_case(
    engine: Engine,
    *,
    sequence: int,
    second_variant_wins: bool,
) -> bool:
    ledger_table = ("registration_idempotency_records",)
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    sender = _BlockingSender()
    tracker = _PgBackendTracker()
    app, factory = _build_app_context(engine, sender, backend_tracker=tracker)
    original = _base_registration_payload(sequence)
    changed = _canonical_field_mutations(original)[0]
    winner_payload, loser_payload = (
        (changed, original) if second_variant_wins else (original, changed)
    )
    wire_key = f"nyay17-mismatch-race-{sequence}"
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with ThreadPoolExecutor(max_workers=2) as executor:
        winner_future = executor.submit(
            _post_registration, app, winner_payload, wire_key
        )
        if not sender.entered.wait(timeout=15):
            sender.release.set()
            return False
        loser_future = executor.submit(_post_registration, app, loser_payload, wire_key)
        loser_waited = _wait_for_request_lock(engine, tracker, expected_backends=2)
        backend_count = tracker.count
        sender.release.set()
        winner = winner_future.result(timeout=30)
        loser = loser_future.result(timeout=30)
    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        succeeded = _ledger_state_exact(_ledger_for_key(session, wire_key), "succeeded")
    stable_before = _database_state_digest(engine, all_tables)
    delivery_before = sender.count
    winner_replay = _post_registration(app, winner_payload, wire_key)
    loser_replay = _post_registration(app, loser_payload, wire_key)
    stable = bool(
        winner_replay.status_code == 201
        and _response_handle(winner_replay) == _response_handle(winner)
        and loser_replay.status_code == 409
        and _response_error_code(loser_replay) == "idempotency_conflict"
        and _response_error_field(loser_replay) == "Idempotency-Key"
        and sender.count == delivery_before
        and _database_state_digest(engine, all_tables) == stable_before
        and loser_waited
        and succeeded
    )
    observation = {
        "statuses": [winner.status_code, loser.status_code],
        "conflict_codes": [
            code
            for code in (_response_error_code(winner), _response_error_code(loser))
            if code == "idempotency_conflict"
        ],
        "conflict_fields": [
            field
            for field in (
                _response_error_field(winner),
                _response_error_field(loser),
            )
            if field is not None
        ],
        "same_public_handle": False,
        "graph_delta": _count_delta(before_graph, after_graph),
        "ledger_delta": after_ledger - before_ledger,
        "delivery_delta": sender.count,
        "backend_count": backend_count,
        "db_lock_wait_observed": loser_waited,
        "stable_followups": stable,
    }
    return _race_observation_passes(observation, mismatched=True)


def _run_mismatch_races(engine: Engine) -> dict[str, Any]:
    cases = (
        _run_mismatch_race_case(engine, sequence=311, second_variant_wins=False),
        _run_mismatch_race_case(engine, sequence=312, second_variant_wins=True),
    )
    return {"passed": all(cases), "cases": len(cases)}


def _run_failed_waiter_race(engine: Engine) -> dict[str, Any]:
    ledger_table = ("registration_idempotency_records",)
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    entity_tables = tuple(
        table for table in REGISTRATION_GRAPH_TABLES if table != "audit_events"
    )
    sender = _BlockingSender(fail=True)
    tracker = _PgBackendTracker()
    app, factory = _build_app_context(engine, sender, backend_tracker=tracker)
    payload = _base_registration_payload(321)
    wire_key = "nyay17-failed-waiter"
    before_entities = _table_counts(factory, entity_tables)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with ThreadPoolExecutor(max_workers=2) as executor:
        winner_future = executor.submit(_post_registration, app, payload, wire_key)
        if not sender.entered.wait(timeout=15):
            sender.release.set()
            return {"passed": False}
        waiter_future = executor.submit(_post_registration, app, payload, wire_key)
        waiter_waited = _wait_for_request_lock(engine, tracker, expected_backends=2)
        backend_count = tracker.count
        sender.release.set()
        winner = winner_future.result(timeout=30)
        waiter = waiter_future.result(timeout=30)
    after_entities = _table_counts(factory, entity_tables)
    after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        failed_exact = _ledger_state_exact(_ledger_for_key(session, wire_key), "failed")
    stable_before = _database_state_digest(engine, all_tables)
    delivery_before = sender.count
    exact_replay = _post_registration(app, payload, wire_key)
    mismatch = _post_registration(app, _canonical_field_mutations(payload)[0], wire_key)
    stable = bool(
        exact_replay.status_code == 502
        and _response_error_code(exact_replay) == "otp_delivery_failed"
        and _response_error_field(exact_replay) is None
        and sender.count == delivery_before
        and _database_state_digest(engine, all_tables) == stable_before
    )
    observation = {
        "statuses": [winner.status_code, waiter.status_code],
        "same_error_code": (
            _response_error_code(winner)
            == _response_error_code(waiter)
            == "otp_delivery_failed"
        ),
        "error_fields_absent": (
            _response_error_field(winner) is None
            and _response_error_field(waiter) is None
        ),
        "failed_state_exact": failed_exact,
        "ledger_delta": after_ledger - before_ledger,
        "registration_graph_absent": _zero_deltas(
            _count_delta(before_entities, after_entities)
        ),
        "provider_attempt_delta": sender.count,
        "backend_count": backend_count,
        "db_lock_wait_observed": waiter_waited,
        "stable_failure_replay": stable and waiter_waited,
        "mismatch_conflict": bool(
            mismatch.status_code == 409
            and _response_error_code(mismatch) == "idempotency_conflict"
            and _response_error_field(mismatch) == "Idempotency-Key"
        ),
    }
    return {"passed": _failed_waiters_observation_passes(observation)}


class _SyntheticDiag:
    def __init__(self, name: str) -> None:
        self.constraint_name = name


class _SyntheticIntegrityOriginal(Exception):
    def __init__(self, name: str) -> None:
        super().__init__("synthetic integrity failure")
        self.diag = _SyntheticDiag(name)


def _synthetic_integrity_error(name: str) -> IntegrityError:
    return IntegrityError(
        "sanitized statement",
        {},
        _SyntheticIntegrityOriginal(name),
    )


def _run_integrity_translation_probe(engine: Engine) -> dict[str, Any]:
    from app.api.v1 import auth_student as endpoint
    from app.schemas.registration import StudentRegisterRequest
    from app.services import registration_service

    sender = _CapturingSender()
    app, factory = _build_app_context(engine, sender)
    payload_dict = _base_registration_payload(331)
    payload = StudentRegisterRequest.model_validate(payload_dict)
    wire_key = "nyay17-integrity-translation"
    created = _post_registration(app, payload_dict, wire_key)
    exact_results: list[bool] = []
    for constraint in (
        endpoint._REGISTRATION_IDEMPOTENCY_CONSTRAINT,
        endpoint._REGISTRATION_MOBILE_CONSTRAINT,
    ):
        with factory() as session:
            recovered = endpoint._recover_registration_integrity_conflict(
                session,
                payload,
                wire_key,
                _synthetic_integrity_error(constraint),
            )
            exact_results.append(
                recovered.registration.id == uuid.UUID(str(_response_handle(created)))
                and recovered.replayed is True
            )
            session.rollback()

    mobile_typed = False
    with factory() as session:
        try:
            endpoint._recover_registration_integrity_conflict(
                session,
                payload,
                None,
                _synthetic_integrity_error(endpoint._REGISTRATION_MOBILE_CONSTRAINT),
            )
        except HTTPException as exc:
            mobile_typed = bool(
                exc.status_code == 409
                and isinstance(exc.detail, dict)
                and exc.detail.get("code") == "mobile_already_registered"
                and exc.detail.get("field") == "mobile"
            )

    mismatch_typed = False
    changed = StudentRegisterRequest.model_validate(
        _canonical_field_mutations(payload_dict)[0]
    )
    with factory() as session:
        try:
            endpoint._recover_registration_integrity_conflict(
                session,
                changed,
                wire_key,
                _synthetic_integrity_error(endpoint._REGISTRATION_MOBILE_CONSTRAINT),
            )
        except HTTPException as exc:
            mismatch_typed = bool(
                exc.status_code == 409
                and isinstance(exc.detail, dict)
                and exc.detail.get("code") == "idempotency_conflict"
                and exc.detail.get("field") == "Idempotency-Key"
            )

    unknown_rethrown = True
    for name in (
        "unknown_registration_constraint",
        endpoint._REGISTRATION_IDEMPOTENCY_CONSTRAINT + "_near_miss",
        endpoint._REGISTRATION_MOBILE_CONSTRAINT + "_near_miss",
    ):
        expected = _synthetic_integrity_error(name)
        with factory() as session:
            try:
                endpoint._recover_registration_integrity_conflict(
                    session, payload, wire_key, expected
                )
            except IntegrityError as caught:
                unknown_rethrown = unknown_rethrown and caught is expected
            else:
                unknown_rethrown = False

    # Deterministically mutate the product fingerprint comparison seam. A
    # changed request then false-replays as 201, which the real typed-conflict
    # oracle must reject. Restore the seam before leaving this single thread.
    mutation_tables = REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",)
    mutation_state = _database_state_digest(engine, mutation_tables)
    mutation_delivery = sender.count
    original_compare = registration_service.hmac.compare_digest
    try:
        registration_service.hmac.compare_digest = lambda *_: True
        bypassed = _post_registration(
            app, _canonical_field_mutations(payload_dict)[0], wire_key
        )
    finally:
        registration_service.hmac.compare_digest = original_compare
    bypass_observation = {
        "status": bypassed.status_code,
        "error_code": _response_error_code(bypassed),
        "error_field": _response_error_field(bypassed),
        "graph_delta": {table: 0 for table in REGISTRATION_GRAPH_TABLES},
        "ledger_delta": 0,
        "delivery_delta": sender.count - mutation_delivery,
        "state_unchanged": (
            _database_state_digest(engine, mutation_tables) == mutation_state
        ),
    }
    fingerprint_bypass_killed = bool(
        bypassed.status_code == 201
        and not _conflict_observation_passes(bypass_observation)
    )
    return {
        "passed": bool(
            created.status_code == 201
            and all(exact_results)
            and mobile_typed
            and mismatch_typed
            and unknown_rethrown
            and fingerprint_bypass_killed
        ),
        "cases": len(exact_results) + 1 + 1 + 3 + 1,
        "product_seam_mutants_killed": int(fingerprint_bypass_killed),
    }


def _execute_behavior(scratch_url: str) -> dict[str, Any]:
    migration = {
        "upgrade": _run_alembic(scratch_url, "upgrade", APPLICATION_HEAD),
        "check": None,
    }
    if migration["upgrade"]["returncode"] != 0:
        raise ProductGateFailure("behavior scratch migration failed")
    migration["check"] = _run_alembic(scratch_url, "check")
    if migration["check"]["returncode"] != 0:
        raise ProductGateFailure("behavior scratch is not at one Alembic head")

    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            server_version_num = int(connection.scalar(text("SHOW server_version_num")))
            vector_version = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            revision_rows = int(
                connection.scalar(text("SELECT count(*) FROM alembic_version")) or 0
            )
        runtime_passed = _is_postgresql_16_with_pgvector(
            server_version_num, vector_version
        )
        if not runtime_passed:
            raise Blocked("PostgreSQL 16 with pgvector is required")
        schema_exact = _migration_inventory_passes(engine)
        if not schema_exact:
            raise ProductGateFailure("0018 ledger schema inventory drifted")

        from app.core.config import settings
        from app.core.crypto import KeyRing, override_keyring

        previous_env = settings.app_env
        settings.app_env = "testing"
        override_keyring(
            KeyRing(
                active_version="v1",
                secrets={"v1": b"nyay17-postgres-gate-encryption-v1"},
                lookup_secret=b"nyay17-postgres-gate-stable-lookup-v1",
            )
        )
        try:
            sequential = _run_sequential_probes(engine)
            activation = _run_activation_probe(engine)
            activation_retention_race = _run_activation_retention_race(engine)
            retention = _run_retention_probe(engine)
            pending = _run_pending_crash_probe(engine)
            accepted_crash = _run_accepted_crash_projection(engine)
            pending_resend = _run_pending_resend_probes(engine)
            retention_purge = _run_retention_purge_probes(engine)
            failed = _run_failed_delivery_probe(engine)
            same_race = _run_same_content_race(engine)
            mismatch_races = _run_mismatch_races(engine)
            failed_waiter = _run_failed_waiter_race(engine)
            integrity = _run_integrity_translation_probe(engine)
        finally:
            override_keyring(None)
            settings.app_env = previous_env
        return {
            "runtime": {
                "passed": runtime_passed,
                "server_version_num": server_version_num,
                "pgvector_present": bool(vector_version),
            },
            "migration": {
                "upgrade_returncode": migration["upgrade"]["returncode"],
                "check_returncode": migration["check"]["returncode"],
                "current_revision_exact": _current_revision(engine) == APPLICATION_HEAD,
                "revision_rows": revision_rows,
            },
            "schema_exact": schema_exact,
            "sequential": sequential,
            "activation": activation,
            "activation_retention_race": activation_retention_race,
            "retention": retention,
            "pending": pending,
            "accepted_crash": accepted_crash,
            "pending_resend": pending_resend,
            "retention_purge": retention_purge,
            "failed": failed,
            "same_race": same_race,
            "mismatch_races": mismatch_races,
            "failed_waiter": failed_waiter,
            "integrity": integrity,
        }
    finally:
        engine.dispose()


def _assemble_assertions(
    lifecycle: Mapping[str, Any],
    behavior: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    runtime = behavior["runtime"]
    migration = behavior["migration"]
    sequential = behavior["sequential"]
    activation = behavior["activation"]
    activation_retention_race = behavior["activation_retention_race"]
    retention = behavior["retention"]
    pending = behavior["pending"]
    accepted_crash = behavior["accepted_crash"]
    pending_resend = behavior["pending_resend"]
    retention_purge = behavior["retention_purge"]
    failed = behavior["failed"]
    same_race = behavior["same_race"]
    mismatch_races = behavior["mismatch_races"]
    failed_waiter = behavior["failed_waiter"]
    integrity = behavior["integrity"]
    roundtrip_passed = bool(
        lifecycle["schema_inventory"]
        and lifecycle["first_projection_preserved"]
        and lifecycle["no_key_marker_false"]
        and lifecycle["ledger_empty"]
        and lifecycle["roundtrip_17"]
        and lifecycle["roundtrip_18"]
    )
    downgrade_passed = _downgrade_observation_passes(lifecycle)
    ledger_inventory = {
        "schema_exact": behavior["schema_exact"],
        "ledger_has_raw_key_column": False,
        "new_registration_raw_key_is_null": sequential["raw_key_absent"],
        "new_registration_legacy_marker_false": sequential["raw_key_absent"],
        "key_hash_lower_hex_64": sequential["ledger_shape"],
        "key_hash_differs_from_wire_key": sequential["hash_private"],
        "key_hash_unique_authority": behavior["schema_exact"],
        "state_inventory_exact": bool(
            sequential["ledger_shape"]
            and activation["retired_exact"]
            and retention["passed"]
            and pending["passed"]
            and pending_resend["passed"]
            and retention_purge["passed"]
            and failed["passed"]
        ),
        "state_links_exact": bool(
            activation["retired_exact"]
            and retention["passed"]
            and pending_resend["passed"]
            and retention_purge["passed"]
            and failed["passed"]
        ),
    }
    assertions = [
        _assertion(
            "RUNTIME-POSTGRES-16-PGVECTOR",
            runtime["passed"],
            server_version_num=runtime["server_version_num"],
            pgvector_present=runtime["pgvector_present"],
        ),
        _assertion(
            "RUNTIME-ALEMBIC-PINNED-HEAD",
            migration["upgrade_returncode"] == 0
            and migration["check_returncode"] == 0
            and migration["current_revision_exact"]
            and migration["revision_rows"] == 1,
            upgrade_returncode=migration["upgrade_returncode"],
            check_returncode=migration["check_returncode"],
            current_revision_exact=migration["current_revision_exact"],
            revision_rows=migration["revision_rows"],
        ),
        _assertion(
            "MIGRATION-0017-0018-ROUNDTRIP-PRESERVES-NOKEY-ROW",
            roundtrip_passed,
            lifecycle_steps=4,
            populated_rows=1,
        ),
        _assertion(
            "MIGRATION-0018-DOWNGRADE-KEYED-REFUSAL-IMMUTABLE",
            downgrade_passed,
            ledger_cases=1,
            legacy_cases=1,
            mixed_writer_cases=1,
        ),
        _assertion(
            "SCHEMA-LEDGER-EXACT-STATE-INVENTORY",
            _ledger_inventory_observation_passes(ledger_inventory),
            states_checked=5,
            schema_checked=True,
        ),
        _assertion(
            "CONTRACT-IDEMPOTENCY-KEY-BOUNDARY",
            sequential["boundary_passed"],
            cases_checked=sequential["boundary_cases"],
        ),
        _assertion(
            "CONTRACT-EXACT-REPLAY-STABLE",
            _replay_observation_passes(sequential["replay"]),
            delivery_count=1,
            graph_count=1,
        ),
        _assertion(
            "CONTRACT-CANONICAL-EQUIVALENTS-REPLAY",
            sequential["equivalents_passed"],
            cases_checked=sequential["equivalent_cases"],
        ),
        _assertion(
            "CONTRACT-EVERY-CANONICAL-FIELD-CONFLICTS",
            sequential["conflicts_passed"]
            and sequential["conflict_cases"] == len(CANONICAL_FIELD_PATHS),
            cases_checked=sequential["conflict_cases"],
        ),
        _assertion(
            "CONTRACT-LEGACY-UNVERIFIABLE-CONFLICT",
            sequential["legacy_passed"],
            cases_checked=1,
        ),
        _assertion(
            "CONTRACT-ACTIVATION-RETIRES-REPLAY-UNIFORM",
            activation["verification_status"] == 200
            and activation["retired_exact"]
            and activation["lifecycle_advanced"]
            and activation["activation_then_retention_preserves_retired"]
            and activation_retention_race["passed"]
            and _retired_observation_passes(activation["terminal"]),
            cases_checked=3 + activation_retention_race["cases"],
        ),
        _assertion(
            "CONTRACT-RETENTION-ERASED-TOMBSTONE-UNIFORM",
            retention["passed"],
            cases_checked=retention["cases"],
        ),
        _assertion(
            "CONTRACT-PENDING-CRASH-RESUMES-ONCE",
            pending["passed"]
            and accepted_crash["observed"]
            and pending_resend["passed"],
            cases_checked=2 + pending_resend["cases"],
            crash_provider_invocations=pending["crash_provider_invocations"],
            crash_provider_acceptances=pending["crash_provider_acceptances"],
            resume_provider_acceptances=pending["resume_provider_acceptances"],
            accepted_crash_projection_observed=accepted_crash["observed"],
        ),
        _assertion(
            "CONTRACT-FAILED-DELIVERY-REPLAY-STABLE",
            failed["passed"] and retention_purge["passed"],
            cases_checked=1 + retention_purge["cases"],
        ),
        _assertion(
            "CONCURRENCY-EIGHT-SAME-CONTENT-ONE-GRAPH",
            same_race["passed"],
            workers=8,
        ),
        _assertion(
            "CONCURRENCY-MISMATCHED-ONE-WINNER-TYPED-CONFLICT",
            mismatch_races["passed"],
            cases_checked=mismatch_races["cases"],
        ),
        _assertion(
            "CONCURRENCY-FAILED-LOSER-WAITS-FOR-FINAL-OUTCOME",
            failed_waiter["passed"],
            workers=2,
        ),
        _assertion(
            "CONTRACT-EXACT-INTEGRITY-CONSTRAINT-TRANSLATION",
            integrity["passed"],
            cases_checked=integrity["cases"],
        ),
        _assertion(
            "MUTANTS-IDEMPOTENCY-ORACLE",
            _seeded_mutants_are_killed()
            and integrity["product_seam_mutants_killed"] == 1
            and pending_resend["product_seam_mutants_killed"] == 2,
            mutants=(
                len(_seeded_mutant_results())
                + integrity["product_seam_mutants_killed"]
                + pending_resend["product_seam_mutants_killed"]
            ),
            product_seam_mutants=(
                integrity["product_seam_mutants_killed"]
                + pending_resend["product_seam_mutants_killed"]
            ),
        ),
    ]
    preprivacy = {"assertions": assertions}
    privacy_findings = _privacy_findings(preprivacy)
    assertions.append(
        _assertion(
            "HARNESS-AGGREGATE-PRIVACY",
            not privacy_findings,
            scanned=True,
            findings=len(privacy_findings),
        )
    )
    metrics = {
        "authoritative_databases": 2,
        "assertions_required": len(REQUIRED_ASSERTION_IDS),
        "canonical_cases": len(CANONICAL_FIELD_PATHS),
        "concurrency_workers_max": 8,
        "real_http_executed": True,
        "provider_accepted_before_finalization_commit_crash_may_redeliver": (
            accepted_crash["observed"]
        ),
        "provider_acceptance_or_acknowledgement_ambiguity_not_exactly_once": True,
        "ambiguous_acceptance_may_leave_unusable_delivered_otp": True,
        "database_graph_remains_bounded_under_delivery_ambiguity": True,
        "provider_idempotency_follow_up": "NYAY-4",
        "migration_0018_requires_quiescent_version_locked_cutover": True,
        "pre_0018_legacy_hard_delete_can_erase_raw_key_authority": True,
        "universal_mixed_version_lifecycle_fail_close_claimed": False,
    }
    return assertions, metrics


def _blocked_report(reason: str) -> dict[str, Any]:
    return {
        "gate": "nyay17_postgres_idempotency",
        "status": "BLOCKED",
        "executed": False,
        "reason": reason,
        "assertions": [],
        "evaluation": {
            "exact_inventory": False,
            "required": len(REQUIRED_ASSERTION_IDS),
            "passed": 0,
            "failed": [],
            "inventory_failures": {
                "missing": len(REQUIRED_ASSERTION_IDS),
                "extra": 0,
                "duplicate": 0,
                "reordered": False,
            },
            "overall_pass": False,
        },
        "scratch_cleanup": {
            "created": 0,
            "removed": 0,
            "cleanup_failed": 0,
            "all_created_removed": True,
            "inventory_match": True,
            "baseline_count": 0,
            "final_count": 0,
            "purposes": [],
        },
    }


def _write_report(path: str | None, report: dict[str, Any]) -> None:
    if path:
        Path(path).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="loopback PostgreSQL control URL used only for scratch databases",
    )
    parser.add_argument("--report", help="optional aggregate JSON report path")
    args = parser.parse_args(argv)

    if not args.database_url:
        report = _blocked_report("explicit loopback PostgreSQL control URL absent")
        _write_report(args.report, report)
        print(json.dumps(report, sort_keys=True))
        return BLOCKED_EXIT

    manager: _ScratchDatabaseManager | None = None
    try:
        base = _safe_local_postgres_url(args.database_url)
        manager = _ScratchDatabaseManager(base)
        lifecycle = manager.run("migration_lifecycle", _run_migration_lifecycle)
        behavior = manager.run("behavior", _execute_behavior)
        assertions, metrics = _assemble_assertions(lifecycle, behavior)
        evaluation = _evaluate_assertions(assertions)
        report = {
            "gate": "nyay17_postgres_idempotency",
            "status": "PASS" if evaluation["overall_pass"] else "FAIL",
            "executed": True,
            "assertions": assertions,
            "evaluation": evaluation,
            "metrics": metrics,
            "limitations": {
                "provider_accepted_before_finalization_commit_crash_may_redeliver": True,
                "provider_acceptance_or_acknowledgement_ambiguity_not_exactly_once": True,
                "ambiguous_acceptance_may_leave_unusable_delivered_otp": True,
                "database_graph_remains_bounded_under_delivery_ambiguity": True,
                "closure_ticket": "NYAY-4",
                "migration_0018_requires_quiescent_version_locked_cutover": True,
                "pre_0018_legacy_hard_delete_can_erase_raw_key_authority": True,
                "universal_mixed_version_lifecycle_fail_close_claimed": False,
            },
            "scratch_cleanup": manager.summary(),
        }
        if not _scratch_cleanup_observation_passes(report["scratch_cleanup"]):
            report["status"] = "FAIL"
            report["evaluation"]["overall_pass"] = False
        final_findings = _privacy_findings(report)
        report["privacy_scan"] = {
            "scanned": True,
            "findings": len(final_findings),
            "passed": not final_findings,
        }
        if final_findings:
            report["status"] = "FAIL"
            report["evaluation"]["overall_pass"] = False
        exit_code = 0 if report["status"] == "PASS" else 1
    except Blocked as exc:
        report = _blocked_report(str(exc))
        report["executed"] = bool(manager and manager.scratch_created)
        if manager is not None:
            report["scratch_cleanup"] = manager.summary()
            if not _scratch_cleanup_observation_passes(report["scratch_cleanup"]):
                report["status"] = "FAIL"
                exit_code = 1
            else:
                exit_code = BLOCKED_EXIT
        else:
            exit_code = BLOCKED_EXIT
    except Exception as exc:  # noqa: BLE001 - fail closed; class only
        cleanup = (
            manager.summary()
            if manager is not None
            else {
                "created": 0,
                "removed": 0,
                "cleanup_failed": 0,
                "all_created_removed": True,
                "inventory_match": True,
                "baseline_count": 0,
                "final_count": 0,
                "purposes": [],
            }
        )
        report = {
            "gate": "nyay17_postgres_idempotency",
            "status": "FAIL",
            "executed": bool(manager and manager.scratch_created),
            "failure_class": type(exc).__name__,
            "assertions": [],
            "evaluation": {
                "exact_inventory": False,
                "required": len(REQUIRED_ASSERTION_IDS),
                "passed": 0,
                "failed": [],
                "inventory_failures": {
                    "missing": len(REQUIRED_ASSERTION_IDS),
                    "extra": 0,
                    "duplicate": 0,
                    "reordered": False,
                },
                "overall_pass": False,
            },
            "scratch_cleanup": cleanup,
        }
        exit_code = 1

    _write_report(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
