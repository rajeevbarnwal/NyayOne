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
import hmac
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
from contextlib import contextmanager
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
    event,
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
# the OTP-authority, auth-retention, NYAY-5 profile-boundary and NYAY-9
# owner-scoped profile contracts added after 0018.  Keep 0021 named as a
# checkpoint so advancing the repository head cannot erase its chain oracle.
NYAY5_CHECKPOINT = "0021_nyay5_profile_boundary"
NYAY9_CHECKPOINT = "0022_nyay9_owner_profile_api"
APPLICATION_HEAD = "0023_nyay22_mentor_ceremony"
REGISTER_PATH = "/api/v1/auth/student/register"
REGISTRATION_ACCEPTED_STATUS = 202
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
    "terms_accepted",
    "terms_version",
    "privacy_notice_acknowledged",
    "privacy_notice_version",
    "consent",
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
        env={
            **os.environ,
            "APP_ENV": "testing",
            "DATABASE_URL": scratch_url,
            "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
        },
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


def _migration_inventory_passes(
    engine: Engine, *, expected_revision: str = PINNED_HEAD
) -> bool:
    """Validate 0018 ownership and its exact application-head evolution."""

    if expected_revision == PINNED_HEAD:
        expected_state_sql = _LEDGER_STATE_SQL
        expected_request_hash_sql = _LEDGER_REQUEST_HASH_SQL
        expected_state_links_sql = _LEDGER_STATE_LINKS_SQL
    elif expected_revision == APPLICATION_HEAD:
        otp_migration = importlib.import_module(
            "app.db.migrations.versions.0019_otp_security_authority"
        )
        profile_migration = importlib.import_module(
            "app.db.migrations.versions.0021_nyay5_profile_boundary"
        )
        expected_state_sql = otp_migration._LEDGER_STATE_0019
        expected_request_hash_sql = profile_migration._NEW_REGISTRATION_FINGERPRINT
        expected_state_links_sql = otp_migration._LEDGER_LINKS_0019
    else:
        return False

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
                _canonical_schema_check(expected_state_sql)
            ),
            "ck_registration_idempotency_records_key_hash_shape": (
                _canonical_schema_check(_LEDGER_KEY_HASH_SQL)
            ),
            "ck_registration_idempotency_records_request_fingerprint_shape": (
                _canonical_schema_check(expected_request_hash_sql)
            ),
            "ck_registration_idempotency_records_state_links": (
                _canonical_schema_check(expected_state_links_sql)
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
        "consents": 2,
        "otp_challenges": 1,
        "otp_outbox": 1,
        "audit_events": 1,
    }
    return dict(deltas) == expected


def _replay_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("first_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("first_literal_pending") is True
        and observation.get("replay_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("public_handles_absent") is True
        and observation.get("private_subject_stable") is True
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
    expected_statuses = (
        [REGISTRATION_ACCEPTED_STATUS, 409]
        if mismatched
        else [REGISTRATION_ACCEPTED_STATUS] * 8
    )
    codes = list(observation.get("conflict_codes", ()))
    fields = list(observation.get("conflict_fields", ()))
    return bool(
        sorted(statuses) == expected_statuses
        and (codes == ["idempotency_conflict"] if mismatched else not codes)
        and (fields == ["Idempotency-Key"] if mismatched else not fields)
        and observation.get("public_handles_absent") is True
        and observation.get("private_winner_exact") is True
        and _single_graph_delta(observation.get("graph_delta", {}))
        and observation.get("ledger_delta") == 1
        and observation.get("delivery_delta") == 1
        and observation.get("backend_count") == (2 if mismatched else 8)
        and (
            observation.get("provider_overlap_completed_before_release") is True
            and observation.get("winner_blocked_before_release") is True
            and observation.get("ledger_lock_wait_observed") is True
            and observation.get("ledger_wait_backend_count") == 1
            and observation.get("deadlock_free") is True
            if mismatched
            else True
        )
        and observation.get("stable_followups") is True
    )


def _failure_replay_observation_passes(observation: Mapping[str, Any]) -> bool:
    """A failed provider attempt stays retryable, replay-stable, and bounded."""

    return bool(
        observation.get("first_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("first_projection_exact") is True
        and observation.get("replay_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("replay_projection_exact") is True
        and observation.get("public_handles_absent") is True
        and observation.get("private_subject_stable") is True
        and observation.get("pending_state_exact") is True
        and observation.get("failed_delivery_exact") is True
        and observation.get("ledger_delta") == 1
        and _single_graph_delta(observation.get("graph_delta", {}))
        and observation.get("replay_ledger_delta") == 0
        and observation.get("replay_delivery_delta") == 0
        and observation.get("replay_graph_delta_zero") is True
        and observation.get("replay_state_unchanged") is True
        and observation.get("mismatch_conflict_exact") is True
        and observation.get("mismatch_state_unchanged") is True
        and observation.get("recovery_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("stable_provider_key") is True
        and observation.get("succeeded_state_exact") is True
        and observation.get("sent_delivery_exact") is True
        and observation.get("recovery_provider_acceptances") == 1
        and observation.get("recovery_graph_delta_zero") is True
        and observation.get("final_replay_stable") is True
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


def _neutralized_observation_passes(observation: Mapping[str, Any]) -> bool:
    """Require one real, identifier-free neutral reservation and stable replay."""

    return bool(
        observation.get("response_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("projection_exact") is True
        and observation.get("projection_matches_real") is True
        and observation.get("public_identifier_absent") is True
        and observation.get("private_registration_absent") is True
        and observation.get("distinct_deterministic_cookie") is True
        and observation.get("neutralized_state_exact") is True
        and observation.get("neutral_flow_exact") is True
        and observation.get("neutral_authority_exact") is True
        and observation.get("real_graph_unchanged") is True
        and observation.get("real_provider_delta") == 0
        and observation.get("ledger_delta") == 1
        and observation.get("authority_delta") == 1
        and observation.get("flow_delta") == 1
        and observation.get("replay_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("replay_projection_stable") is True
        and observation.get("replay_cookie_stable") is True
        and observation.get("replay_state_unchanged") is True
        and observation.get("replay_provider_delta") == 0
        and observation.get("mutation_conflict_exact") is True
        and observation.get("mutation_state_unchanged") is True
        and observation.get("mutation_provider_delta") == 0
    )


def _pending_resume_observation_passes(observation: Mapping[str, Any]) -> bool:
    """A crash-pending request must resume once without duplicating its graph."""

    return bool(
        observation.get("crash_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("crash_projection_exact") is True
        and observation.get("pending_state_exact") is True
        and observation.get("claimed_delivery_exact") is True
        and observation.get("pending_mismatch_status") == 409
        and observation.get("pending_mismatch_code") == "idempotency_conflict"
        and observation.get("pending_mismatch_field") == "Idempotency-Key"
        and observation.get("pending_mismatch_state_unchanged") is True
        and observation.get("immediate_replay_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("immediate_projection_exact") is True
        and observation.get("immediate_delivery_delta") == 0
        and observation.get("immediate_state_unchanged") is True
        and observation.get("resume_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("public_handles_absent") is True
        and observation.get("private_subject_stable") is True
        and observation.get("succeeded_state_exact") is True
        and observation.get("sent_delivery_exact") is True
        and observation.get("stable_provider_key") is True
        and observation.get("ledger_delta") == 1
        and _single_graph_delta(observation.get("graph_delta", {}))
        and observation.get("resume_graph_delta_zero") is True
        and observation.get("crash_provider_invocations") == 1
        and observation.get("crash_provider_acceptances") == 0
        and observation.get("resume_provider_invocations") == 1
        and observation.get("resume_provider_acceptances") == 1
        and observation.get("provider_acceptances_total") == 1
        and observation.get("followup_stable") is True
    )


def _failed_waiters_observation_passes(observation: Mapping[str, Any]) -> bool:
    """A peer request must finish while provider I/O remains off-lock."""

    return bool(
        sorted(observation.get("statuses", ()))
        == [REGISTRATION_ACCEPTED_STATUS, REGISTRATION_ACCEPTED_STATUS]
        and observation.get("projections_exact") is True
        and observation.get("public_handles_absent") is True
        and observation.get("private_subject_stable") is True
        and observation.get("peer_completed_before_release") is True
        and observation.get("winner_blocked_before_release") is True
        and observation.get("pending_state_during_overlap") is True
        and observation.get("claimed_delivery_during_overlap") is True
        and observation.get("pending_state_exact") is True
        and observation.get("failed_delivery_exact") is True
        and observation.get("ledger_delta") == 1
        and _single_graph_delta(observation.get("graph_delta", {}))
        and observation.get("provider_attempt_delta") == 1
        and observation.get("backend_count") == 2
        and observation.get("stable_failure_replay") is True
        and observation.get("mismatch_conflict") is True
        and observation.get("recovery_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("stable_provider_key") is True
        and observation.get("succeeded_state_exact") is True
        and observation.get("sent_delivery_exact") is True
        and observation.get("recovery_provider_acceptances") == 1
        and observation.get("recovery_graph_delta_zero") is True
        and observation.get("final_replay_stable") is True
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
        observation.get("ledger_reused_original_during_send") is False
        and observation.get("ledger_repointed_to_replacement_during_send") is True
        and observation.get("original_sent_erased_before_replacement") is True
        and observation.get("provider_acceptances") == 2
        if pre_relay
        else observation.get("ledger_reused_original_during_send") is True
        and observation.get("ledger_repointed_to_replacement_during_send") is False
        and observation.get("original_sent_erased_before_replacement") is False
        and observation.get("provider_acceptances") == 1
    )
    return bool(
        observation.get("resend_status") == 202
        and observation.get("replay_status") == REGISTRATION_ACCEPTED_STATUS
        and observation.get("public_handles_absent") is True
        and observation.get("private_subject_stable") is True
        and authority_shape_exact
        and observation.get("claimed_delivery_exact") is True
        and observation.get("provider_key_authority_exact") is True
        and observation.get("claim_fence_exact") is True
        and observation.get("succeeded_state_exact") is True
        and observation.get("registration_graph_exact") is True
        and observation.get("active_signup_challenges") == 1
        and observation.get("relayable_signup_payloads") == 0
        and (
            observation.get("backend_count") == 2
            and observation.get("peer_completed_before_release") is True
            and observation.get("winner_blocked_before_release") is True
            if concurrent
            else True
        )
    )


def _finalizer_retention_race_observation_passes(
    observation: Mapping[str, Any], *, finalizer_first: bool
) -> bool:
    """Require one exact terminal winner under both PostgreSQL lock orders."""

    common = bool(
        observation.get("setup_projection_exact") is True
        and observation.get("initial_pending_exact") is True
        and observation.get("initial_failed_delivery_exact") is True
        and observation.get("setup_provider_attempts") == 1
        and observation.get("bound_flow_boundary_exact") is True
        and observation.get("first_waited") is True
        and observation.get("both_waited") is True
        and observation.get("backend_count") == 2
        and observation.get("final_state_exact") is True
        and observation.get("terminal_projection_exact") is True
        and observation.get("followup_delivery_delta") == 0
        and observation.get("followup_state_unchanged") is True
    )
    if finalizer_first:
        ordered = bool(
            observation.get("provider_entered") is True
            and observation.get("claimed_delivery_during_overlap") is True
            and observation.get("provider_io_ledger_unlocked") is True
            and observation.get("finalizer_succeeded") is True
            and observation.get("expired_flows") == 0
            and observation.get("purged_challenges") == 1
            and observation.get("registration_transitions") == 0
            and observation.get("succeeded_state_exact") is True
            and observation.get("exact_replay_status") == REGISTRATION_ACCEPTED_STATUS
            and observation.get("private_subject_stable") is True
            and observation.get("mutation_conflict_exact") is True
            and observation.get("provider_acceptances") == 1
        )
    else:
        ordered = bool(
            observation.get("finalizer_error_exact") is True
            and observation.get("expired_flows") == 1
            and observation.get("purged_challenges") == 0
            and observation.get("registration_transitions") == 1
            and observation.get("erased_state_exact") is True
            and observation.get("exact_replay_status") == 409
            and observation.get("uniform_terminal_signature") is True
            and observation.get("provider_acceptances") == 0
        )
    return common and ordered


def _pending_purge_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        observation.get("expired_flows") == 1
        # Expiring the bound flow removes its OTP graph before the generic
        # challenge sweep. A second challenge count would mean unrelated
        # history was swept by this single-subject probe.
        and observation.get("purged_challenges") == 0
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
        "consents": 2,
        "otp_challenges": 1,
        "otp_outbox": 1,
        "audit_events": 1,
    }
    zero_graph = {name: 0 for name in graph}
    replay = {
        "first_status": REGISTRATION_ACCEPTED_STATUS,
        "first_literal_pending": True,
        "replay_status": REGISTRATION_ACCEPTED_STATUS,
        "public_handles_absent": True,
        "private_subject_stable": True,
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
        "statuses": [REGISTRATION_ACCEPTED_STATUS] * 8,
        "conflict_codes": [],
        "conflict_fields": [],
        "public_handles_absent": True,
        "private_winner_exact": True,
        "graph_delta": graph,
        "ledger_delta": 1,
        "delivery_delta": 1,
        "backend_count": 8,
        "stable_followups": True,
    }
    mismatch_race = {
        "statuses": [REGISTRATION_ACCEPTED_STATUS, 409],
        "conflict_codes": ["idempotency_conflict"],
        "conflict_fields": ["Idempotency-Key"],
        "public_handles_absent": True,
        "private_winner_exact": True,
        "graph_delta": graph,
        "ledger_delta": 1,
        "delivery_delta": 1,
        "backend_count": 2,
        "provider_overlap_completed_before_release": True,
        "winner_blocked_before_release": True,
        "ledger_lock_wait_observed": True,
        "ledger_wait_backend_count": 1,
        "deadlock_free": True,
        "stable_followups": True,
    }
    failure = {
        "first_status": REGISTRATION_ACCEPTED_STATUS,
        "first_projection_exact": True,
        "replay_status": REGISTRATION_ACCEPTED_STATUS,
        "replay_projection_exact": True,
        "public_handles_absent": True,
        "private_subject_stable": True,
        "pending_state_exact": True,
        "failed_delivery_exact": True,
        "ledger_delta": 1,
        "graph_delta": graph,
        "replay_ledger_delta": 0,
        "replay_delivery_delta": 0,
        "replay_graph_delta_zero": True,
        "replay_state_unchanged": True,
        "mismatch_conflict_exact": True,
        "mismatch_state_unchanged": True,
        "recovery_status": REGISTRATION_ACCEPTED_STATUS,
        "stable_provider_key": True,
        "succeeded_state_exact": True,
        "sent_delivery_exact": True,
        "recovery_provider_acceptances": 1,
        "recovery_graph_delta_zero": True,
        "final_replay_stable": True,
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
    neutralized = {
        "response_status": REGISTRATION_ACCEPTED_STATUS,
        "projection_exact": True,
        "projection_matches_real": True,
        "public_identifier_absent": True,
        "private_registration_absent": True,
        "distinct_deterministic_cookie": True,
        "neutralized_state_exact": True,
        "neutral_flow_exact": True,
        "neutral_authority_exact": True,
        "real_graph_unchanged": True,
        "real_provider_delta": 0,
        "ledger_delta": 1,
        "authority_delta": 1,
        "flow_delta": 1,
        "replay_status": REGISTRATION_ACCEPTED_STATUS,
        "replay_projection_stable": True,
        "replay_cookie_stable": True,
        "replay_state_unchanged": True,
        "replay_provider_delta": 0,
        "mutation_conflict_exact": True,
        "mutation_state_unchanged": True,
        "mutation_provider_delta": 0,
    }
    pending = {
        "crash_status": REGISTRATION_ACCEPTED_STATUS,
        "crash_projection_exact": True,
        "pending_state_exact": True,
        "claimed_delivery_exact": True,
        "pending_mismatch_status": 409,
        "pending_mismatch_code": "idempotency_conflict",
        "pending_mismatch_field": "Idempotency-Key",
        "pending_mismatch_state_unchanged": True,
        "immediate_replay_status": REGISTRATION_ACCEPTED_STATUS,
        "immediate_projection_exact": True,
        "immediate_delivery_delta": 0,
        "immediate_state_unchanged": True,
        "resume_status": REGISTRATION_ACCEPTED_STATUS,
        "public_handles_absent": True,
        "private_subject_stable": True,
        "succeeded_state_exact": True,
        "sent_delivery_exact": True,
        "stable_provider_key": True,
        "ledger_delta": 1,
        "graph_delta": graph,
        "resume_graph_delta_zero": True,
        "crash_provider_invocations": 1,
        "crash_provider_acceptances": 0,
        "resume_provider_invocations": 1,
        "resume_provider_acceptances": 1,
        "provider_acceptances_total": 1,
        "followup_stable": True,
    }
    failed_waiter = {
        "statuses": [REGISTRATION_ACCEPTED_STATUS] * 2,
        "projections_exact": True,
        "public_handles_absent": True,
        "private_subject_stable": True,
        "peer_completed_before_release": True,
        "winner_blocked_before_release": True,
        "pending_state_during_overlap": True,
        "claimed_delivery_during_overlap": True,
        "pending_state_exact": True,
        "failed_delivery_exact": True,
        "ledger_delta": 1,
        "graph_delta": graph,
        "provider_attempt_delta": 1,
        "backend_count": 2,
        "stable_failure_replay": True,
        "mismatch_conflict": True,
        "recovery_status": REGISTRATION_ACCEPTED_STATUS,
        "stable_provider_key": True,
        "succeeded_state_exact": True,
        "sent_delivery_exact": True,
        "recovery_provider_acceptances": 1,
        "recovery_graph_delta_zero": True,
        "final_replay_stable": True,
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
        "replay_status": REGISTRATION_ACCEPTED_STATUS,
        "public_handles_absent": True,
        "private_subject_stable": True,
        "ledger_reused_original_during_send": True,
        "ledger_repointed_to_replacement_during_send": False,
        "claimed_delivery_exact": True,
        "provider_key_authority_exact": True,
        "claim_fence_exact": True,
        "original_sent_erased_before_replacement": False,
        "succeeded_state_exact": True,
        "registration_graph_exact": True,
        "active_signup_challenges": 1,
        "relayable_signup_payloads": 0,
        "provider_acceptances": 1,
        "backend_count": 2,
        "peer_completed_before_release": True,
        "winner_blocked_before_release": True,
    }
    pre_relay_resend = deepcopy(pending_resend)
    pre_relay_resend.update(
        {
            "ledger_reused_original_during_send": False,
            "ledger_repointed_to_replacement_during_send": True,
            "original_sent_erased_before_replacement": True,
            "provider_acceptances": 2,
            "backend_count": 0,
            "peer_completed_before_release": False,
            "winner_blocked_before_release": False,
        }
    )
    pending_purge = {
        "expired_flows": 1,
        "purged_challenges": 0,
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
            ("public_handles_absent", False),
            ("private_subject_stable", False),
            ("replay_delivery_delta", 1),
            ("replay_state_unchanged", False),
        )
    ]
    # One deterministic bypass mutant per canonical request field: replaying a
    # A changed field false-replayed as accepted must turn the oracle red.
    results.extend(
        killed(
            _conflict_observation_passes,
            conflict,
            "status",
            REGISTRATION_ACCEPTED_STATUS,
        )
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
            ("failed_delivery_exact", False),
            ("replay_delivery_delta", 1),
            ("stable_provider_key", False),
            ("final_replay_stable", False),
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
            ("statuses", [REGISTRATION_ACCEPTED_STATUS] * 7 + [409]),
            ("public_handles_absent", False),
            ("private_winner_exact", False),
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
            ("public_handles_absent", False),
            ("private_winner_exact", False),
            ("backend_count", 1),
            ("provider_overlap_completed_before_release", False),
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
        killed(_neutralized_observation_passes, neutralized, field, unsafe)
        for field, unsafe in (
            ("projection_matches_real", False),
            ("private_registration_absent", False),
            ("neutralized_state_exact", False),
            ("neutral_flow_exact", False),
            ("neutral_authority_exact", False),
            ("ledger_delta", 0),
            ("replay_cookie_stable", False),
            ("mutation_conflict_exact", False),
        )
    )
    results.extend(
        killed(_pending_resume_observation_passes, pending, field, unsafe)
        for field, unsafe in (
            ("claimed_delivery_exact", False),
            ("immediate_delivery_delta", 1),
            ("pending_mismatch_field", "mobile"),
            ("public_handles_absent", False),
            ("stable_provider_key", False),
            ("resume_graph_delta_zero", False),
        )
    )
    results.extend(
        killed(_failed_waiters_observation_passes, failed_waiter, field, unsafe)
        for field, unsafe in (
            ("statuses", [REGISTRATION_ACCEPTED_STATUS, 502]),
            ("backend_count", 1),
            ("peer_completed_before_release", False),
            ("provider_attempt_delta", 2),
        )
    )
    results.extend(
        killed(_invalid_key_observation_passes, invalid_key, field, unsafe)
        for field, unsafe in (
            ("status", REGISTRATION_ACCEPTED_STATUS),
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
            ("ledger_reused_original_during_send", False),
            ("public_handles_absent", False),
            ("private_subject_stable", False),
            ("provider_key_authority_exact", False),
            ("registration_graph_exact", False),
            ("relayable_signup_payloads", 1),
            ("backend_count", 1),
            ("peer_completed_before_release", False),
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
            ("ledger_repointed_to_replacement_during_send", False),
            ("original_sent_erased_before_replacement", False),
            ("succeeded_state_exact", False),
            ("provider_acceptances", 1),
        )
    )
    results.extend(
        killed(_pending_purge_observation_passes, pending_purge, field, unsafe)
        for field, unsafe in (
            ("expired_flows", 0),
            ("purged_challenges", 1),
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
    """Return one current NYAY-5 registration kept in memory only.

    Academic data is intentionally absent: the current contract creates an
    empty profile and accepts those fields only through the authenticated CAS
    profile boundary.  Terms and Privacy Notice authority are independent.
    """

    mobile = f"8{sequence:09d}"[-10:]
    return {
        "first_name": "Āsha Rao",
        "middle_name": None,
        "last_name": "Sen",
        "mobile": mobile,
        "dob": "2000-01-02",
        "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    }


def _legacy_v1_registration_payload(sequence: int) -> dict[str, Any]:
    """Return the sealed v1 shape solely for an already-bound replay probe."""

    payload = _base_registration_payload(sequence)
    for field in (
        "terms_accepted",
        "terms_version",
        "privacy_notice_acknowledged",
        "privacy_notice_version",
    ):
        payload.pop(field)
    payload.update(
        {
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
    )
    return payload


def _canonical_field_mutations(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Change exactly one of the fifteen current v2 canonical fields."""

    mutations: list[dict[str, Any]] = []
    replacements: tuple[tuple[str, Any], ...] = (
        ("first_name", "Maya"),
        ("middle_name", "Devi"),
        ("last_name", "Rao"),
        ("mobile", "7999999999"),
        ("dob", "2000-01-03"),
        ("terms_accepted", False),
        ("terms_version", "terms-2026-08.v2"),
        ("privacy_notice_acknowledged", False),
        ("privacy_notice_version", "privacy-2026-08.v2"),
        (
            "consent",
            {"accepted": True, "policy_version": "dpdp-2023.v1"},
        ),
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
    """Different JSON spellings that validate to the same current v2 value."""

    variants: list[dict[str, Any]] = []
    names = deepcopy(dict(payload))
    names["first_name"] = (
        "  "
        + unicodedata.normalize("NFD", str(payload["first_name"])).replace(" ", "   ")
        + "  "
    )
    names["middle_name"] = "   "
    variants.append(names)

    terms = deepcopy(dict(payload))
    terms["terms_version"] = f"  {payload['terms_version']}  "
    variants.append(terms)

    privacy = deepcopy(dict(payload))
    privacy["privacy_notice_version"] = f"  {payload['privacy_notice_version']}  "
    variants.append(privacy)

    explicit_nulls = deepcopy(dict(payload))
    for field in (
        "consent",
        "college",
        "year_of_study",
        "enrolment_number",
        "institutional_email",
        "bar_enrolment_number",
    ):
        explicit_nulls[field] = None
    variants.append(explicit_nulls)

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
        self._receipts: dict[str, tuple[str, str, str]] = {}

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> str:
        from app.services.otp_sender import OtpSendError

        with self._lock:
            existing = self._receipts.get(idempotency_token)
            if existing is not None:
                if existing[:2] != (destination, code):
                    raise OtpSendError("otp provider idempotency conflict")
                return existing[2]
            receipt = f"nyay17-gate-{len(self._receipts) + 1}"
            self._receipts[idempotency_token] = (destination, code, receipt)
            self.sent.append((destination, code))
            return receipt

    @property
    def count(self) -> int:
        with self._lock:
            return len(self.sent)


class _FailingSender(_CapturingSender):
    """Provider-level failure used to exercise durable retry/backoff replay."""

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> None:
        from app.services.otp_sender import OtpSendError

        del idempotency_token
        with self._lock:
            self.sent.append((destination, code))
        raise OtpSendError("synthetic provider failure")


class _CrashSender(_CapturingSender):
    """Crash before provider acceptance, leaving resumable durable pending."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> None:
        del destination, code, idempotency_token
        with self._lock:
            self.attempts += 1
        raise RuntimeError("synthetic post-commit crash")


class _AcceptedCrashSender(_CapturingSender):
    """Project a provider acceptance followed by local finalization crash."""

    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> str:
        from app.services.otp_sender import OtpSendError

        with self._lock:
            self.attempts += 1
            existing = self._receipts.get(idempotency_token)
            if existing is not None:
                if existing[:2] != (destination, code):
                    raise OtpSendError("otp provider idempotency conflict")
                return existing[2]
            receipt = f"nyay17-gate-{len(self._receipts) + 1}"
            self._receipts[idempotency_token] = (destination, code, receipt)
            self.sent.append((destination, code))
        raise RuntimeError("synthetic accepted-before-finalization crash")


class _BlockingSender(_CapturingSender):
    """Hold one provider attempt so an exact concurrent waiter overlaps it."""

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail = fail

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> str:
        from app.services.otp_sender import OtpSendError

        with self._lock:
            existing = self._receipts.get(idempotency_token)
            if existing is not None:
                if existing[:2] != (destination, code):
                    raise OtpSendError("otp provider idempotency conflict")
                return existing[2]
            self.sent.append((destination, code))
        self.entered.set()
        if not self.release.wait(timeout=10):
            raise RuntimeError("synthetic gate release timeout")
        if self.fail:
            raise OtpSendError("synthetic provider failure")
        with self._lock:
            receipt = f"nyay17-gate-{len(self._receipts) + 1}"
            self._receipts[idempotency_token] = (destination, code, receipt)
            return receipt


@contextmanager
def _registration_finalizer_clock_scope(
    clock: Mapping[str, datetime],
) -> Iterator[None]:
    """Thread only the background delivery clock through the certified probe."""

    from app.api.v1 import auth_student as endpoint
    from app.services import registration_service

    original = endpoint.finalize_registration_after_response

    def deterministic_finalizer(key_hash: str, sender: Any, factory: Any) -> None:
        with factory() as session:
            try:
                registration_service.finalize_pending_registration(
                    session,
                    key_hash,
                    sender,
                    now=clock["now"],
                )
            except registration_service.RegistrationError:
                session.rollback()

    endpoint.finalize_registration_after_response = deterministic_finalizer
    try:
        yield
    finally:
        endpoint.finalize_registration_after_response = original


@contextmanager
def _registration_resend_clock_scope(clock: Mapping[str, datetime]) -> Iterator[None]:
    """Thread one certified clock through the resend background adapter."""

    from app.api.v1 import auth_student as endpoint
    from app.workers import otp_outbox_relay

    original = endpoint.deliver_resend_after_response

    def deterministic_resend(
        registration_id: Any,
        outbox_id: Any,
        sender: Any,
        factory: Any,
    ) -> None:
        otp_outbox_relay.deliver_resend_after_response(
            registration_id,
            outbox_id,
            sender,
            factory,
            now=clock["now"],
        )

    endpoint.deliver_resend_after_response = deterministic_resend
    try:
        yield
    finally:
        endpoint.deliver_resend_after_response = original


@contextmanager
def _registration_request_clock_scope(now: datetime) -> Iterator[None]:
    """Hold one request clock fixed without changing production clock ownership."""

    from app.api.v1 import auth_student as endpoint

    original = endpoint._now
    endpoint._now = lambda: now
    try:
        yield
    finally:
        endpoint._now = original


class _PgBackendTracker:
    """Track request backend cardinality privately; never emit PID values."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pids_by_owner: dict[object, int] = {}

    def record(self, pid: int, *, owner: object | None = None) -> None:
        owner_key: object = ("pid", pid) if owner is None else owner
        with self._condition:
            self._pids_by_owner[owner_key] = pid
            self._condition.notify_all()

    def wait_for_count(self, expected: int, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self._pids_by_owner) < expected:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return len(self._pids_by_owner) == expected

    def private_snapshot(self) -> set[int]:
        with self._condition:
            return set(self._pids_by_owner.values())

    @property
    def count(self) -> int:
        with self._condition:
            return len(self._pids_by_owner)


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
    deadline = time.monotonic() + timeout
    # PostgreSQL activity snapshots can stay transaction-bound while a request
    # moves to a new backend after an internal commit. AUTOCOMMIT makes each
    # poll observe current lock state while the owner/PID set is refreshed.
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        while time.monotonic() < deadline:
            pids = tracker.private_snapshot()
            if tracker.count != expected_backends or len(pids) != expected_backends:
                time.sleep(0.02)
                continue
            placeholders = ", ".join(f":pid_{index}" for index in range(len(pids)))
            parameters = {f"pid_{index}": pid for index, pid in enumerate(sorted(pids))}
            statement = text(
                "SELECT count(*) FROM pg_stat_activity "
                f"WHERE pid IN ({placeholders}) AND wait_event_type = 'Lock'"
            )
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
        request_owner = object()

        def track_backend(
            _session: Session,
            _transaction: Any,
            connection: Any,
        ) -> None:
            if backend_tracker is not None:
                backend_tracker.record(
                    int(connection.scalar(text("SELECT pg_backend_pid()"))),
                    owner=request_owner,
                )

        if backend_tracker is not None:
            event.listen(session, "after_begin", track_backend)
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        else:
            session.rollback()
        finally:
            if backend_tracker is not None:
                event.remove(session, "after_begin", track_backend)
            session.close()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(endpoint.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[endpoint.get_otp_sender] = lambda: sender
    app.dependency_overrides[endpoint.get_outbox_session_factory] = lambda: factory
    app.state.nyay17_session_factory = factory
    return app, factory


def _post_registration(
    app: FastAPI,
    payload: Mapping[str, Any],
    key: str | None,
) -> Any:
    from app.core.config import settings

    headers = {"Origin": settings.cors_origins[0]}
    if key is not None:
        headers["Idempotency-Key"] = key
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(REGISTER_PATH, json=dict(payload), headers=headers)
    return _attach_private_response_handle(app, response, key)


def _post_registration_headers(
    app: FastAPI,
    payload: Mapping[str, Any],
    headers: list[tuple[str, str]],
) -> Any:
    """Send an exact raw header list so duplicate occurrences remain visible."""

    from app.core.config import settings

    with TestClient(app, raise_server_exceptions=False) as client:
        return client.post(
            REGISTER_PATH,
            json=dict(payload),
            headers=[("Origin", settings.cors_origins[0]), *headers],
        )


def _private_flow_token(response: Any, key: str | None) -> str | None:
    """Resolve a QA-only bearer without reading it from public response data."""

    token = getattr(response, "_nyay17_private_flow_token", None)
    if isinstance(token, str) and token:
        return token
    if key is not None and getattr(response, "status_code", 0) >= 500:
        from app.services import otp_flow_service

        return otp_flow_service.deterministic_signup_token(key)
    return None


def _post_signup_resend(
    app: FastAPI,
    registration_response: Any,
    key: str | None,
) -> Any:
    from app.core.config import settings

    token = _private_flow_token(registration_response, key)
    with TestClient(app, raise_server_exceptions=False) as client:
        if token is not None:
            client.cookies.set(
                settings.otp_flow_cookie_name,
                token,
                path="/api/v1",
            )
        return client.post(
            "/api/v1/auth/student/otp/resend",
            json={},
            headers={"Origin": settings.cors_origins[0]},
        )


def _post_signup_verify(
    app: FastAPI,
    registration_response: Any,
    key: str | None,
    code: str,
) -> Any:
    from app.core.config import settings

    token = _private_flow_token(registration_response, key)
    with TestClient(app, raise_server_exceptions=False) as client:
        if token is not None:
            client.cookies.set(
                settings.otp_flow_cookie_name,
                token,
                path="/api/v1",
            )
        return client.post(
            "/api/v1/auth/student/otp/verify",
            json={"code": code},
            headers={"Origin": settings.cors_origins[0]},
        )


def _public_response_handle(response: Any) -> str | None:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - only an in-memory comparison handle
        return None
    value = body.get("registration_id") if isinstance(body, dict) else None
    return str(value) if value is not None else None


def _response_handle(response: Any) -> str | None:
    """Return the gate-private subject without treating it as public output."""

    value = getattr(response, "_nyay17_private_registration_id", None)
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _response_is_identifier_free(
    response: Any,
    *,
    private_handle: str | None = None,
) -> bool:
    """Reject a registration UUID anywhere in a public HTTP response body."""

    try:
        body = response.json()
        serialized = json.dumps(body, sort_keys=True, separators=(",", ":"))
    except Exception:  # noqa: BLE001 - fail closed on an unreadable response
        return False
    if _UUID_TEXT.search(serialized) or _public_response_handle(response) is not None:
        return False
    if private_handle is None:
        return True
    try:
        private_id = uuid.UUID(str(private_handle))
    except (TypeError, ValueError):
        return False
    lowered = serialized.casefold()
    return str(private_id) not in lowered and private_id.hex not in lowered


def _registration_accepted_projection_is_exact(
    response: Any,
    *,
    private_handle: str | None,
) -> bool:
    """Require the exact current identifier-free registration projection."""

    from app.core.config import settings

    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - fail closed on malformed output
        return False
    return bool(
        response.status_code == 202
        and private_handle is not None
        and body
        == {
            "status": "accepted",
            "next": "otp",
            "expires_in_seconds": settings.otp_challenge_ttl_seconds,
            "resend_after_seconds": settings.otp_resend_cooldown_seconds,
        }
        and all(
            isinstance(body.get(field), int) and not isinstance(body.get(field), bool)
            for field in (
                "expires_in_seconds",
                "resend_after_seconds",
            )
        )
        and _response_is_identifier_free(response, private_handle=private_handle)
    )


def _signup_pending_projection_is_exact(
    response: Any,
    *,
    private_handle: str | None,
) -> bool:
    """Compatibility name for the now-accepted registration wire oracle."""

    return _registration_accepted_projection_is_exact(
        response, private_handle=private_handle
    )


def _signup_authenticated_projection_is_exact(
    response: Any,
    *,
    registration_payload: Mapping[str, Any],
) -> bool:
    """Validate the complete NYAY-5 signup activation wire in memory only.

    This oracle deliberately compares the identity values because activation
    is an authenticated response.  It returns only one boolean; neither the
    payload nor the response body can enter aggregate evidence.
    """

    from app.services import otp_flow_service

    profile_fields = (
        "college",
        "year_of_study",
        "enrolment_number",
        "institutional_email",
        "bar_enrolment_number",
    )
    current_v2_shape = bool(
        registration_payload.get("terms_accepted") is True
        and isinstance(registration_payload.get("terms_version"), str)
        and registration_payload.get("privacy_notice_acknowledged") is True
        and isinstance(registration_payload.get("privacy_notice_version"), str)
        and registration_payload.get("consent") is None
        and all(registration_payload.get(field) is None for field in profile_fields)
    )
    if not current_v2_shape:
        return False
    expected = {
        **otp_flow_service.authenticated_state("signup"),
        "onboarding": {
            "profile_version": 1,
            "completion_version": "v1",
            "completion_percent": 0,
            "completed_sections": [],
            "missing_requirements": [
                "personal.preferred_language",
                "personal.city",
                "academic.college",
                "academic.year_of_study",
                "academic.enrolment_number",
                "interests.interests",
                "interests.goals",
            ],
            "next_incomplete_section": "personal",
            "is_complete": False,
            "institutional_email_status": "not_provided",
            "guardian": {"required": False, "status": "not_required"},
            "access_mode": "full",
            "disabled_capabilities": [],
            "profile_prompt": {
                "should_show": True,
                "dismissed_for_session": False,
            },
            "profile": {
                "personal": {
                    "first_name": registration_payload.get("first_name"),
                    "middle_name": registration_payload.get("middle_name"),
                    "last_name": registration_payload.get("last_name"),
                    "date_of_birth": registration_payload.get("dob"),
                    "preferred_language": None,
                    "city": None,
                    "pronouns": None,
                },
                "academic": {
                    "college": None,
                    "year_of_study": None,
                    "enrolment_number": None,
                    "institutional_email": None,
                    "bar_enrolment_number": None,
                },
                "interests": {"interests": [], "goals": []},
            },
        },
    }
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - fail closed on malformed output
        return False
    return bool(response.status_code == 200 and body == expected)


def _neutralized_pending_projection_is_exact(response: Any) -> bool:
    """Require the exact accepted shape without a real registration."""

    from app.core.config import settings

    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - fail closed on malformed output
        return False
    return bool(
        response.status_code == 202
        and _response_handle(response) is None
        and body
        == {
            "status": "accepted",
            "next": "otp",
            "expires_in_seconds": settings.otp_challenge_ttl_seconds,
            "resend_after_seconds": settings.otp_resend_cooldown_seconds,
        }
        and all(
            isinstance(body.get(field), int) and not isinstance(body.get(field), bool)
            for field in (
                "expires_in_seconds",
                "resend_after_seconds",
            )
        )
        and _response_is_identifier_free(response)
    )


def _post_response_crash_projection_is_exact(
    response: Any, *, private_handle: str | None
) -> bool:
    """Certify the response committed before a background finalizer crashed."""

    return bool(
        private_handle is not None
        and _response_handle(response) == private_handle
        and _signup_pending_projection_is_exact(response, private_handle=private_handle)
    )


def _opaque_internal_error_is_exact(
    response: Any, *, private_handle: str | None
) -> bool:
    """Require the exact privacy-safe crash envelope and prove it has no UUID."""

    try:
        private_id = uuid.UUID(str(private_handle))
        body = response.json()
        serialized = json.dumps(body, sort_keys=True, separators=(",", ":"))
    except (AttributeError, TypeError, ValueError):
        return False
    lowered = serialized.casefold()
    return bool(
        response.status_code == 500
        and body
        == {
            "detail": {
                "code": "internal_error",
                "message": "An unexpected error occurred",
            },
            "request_id": None,
        }
        and _UUID_TEXT.search(serialized) is None
        and str(private_id) not in lowered
        and private_id.hex not in lowered
    )


def _lower_hex_64(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _as_gate_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _claimed_delivery_state_exact(
    row: Any,
    *,
    attempts: int = 1,
    expected_last_error: str | None = None,
) -> bool:
    """Validate the exact durable post-crash lease without exposing payload."""

    claimed_at = _as_gate_utc(getattr(row, "claimed_at", None))
    lease_expires_at = _as_gate_utc(getattr(row, "lease_expires_at", None))
    return bool(
        row is not None
        and row.status == "claimed"
        and row.attempts == attempts
        and 0 < row.max_attempts <= 10
        and _lower_hex_64(row.provider_idempotency_key)
        and _lower_hex_64(row.claim_token_hash)
        and claimed_at is not None
        and lease_expires_at is not None
        and lease_expires_at > claimed_at
        and row.next_attempt_at is None
        and isinstance(row.code_ct, str)
        and bool(row.code_ct)
        and isinstance(row.destination_ct, str)
        and bool(row.destination_ct)
        and row.key_version == "v1"
        and row.last_error == expected_last_error
        and row.delivered_at is None
        and row.provider_receipt_hash is None
        and row.provider_receipt_key_version is None
        and row.legacy_destination_retained is False
    )


def _failed_delivery_state_exact(row: Any, *, attempts: int = 1) -> bool:
    """Validate one fenced retryable provider failure and retained payload."""

    return bool(
        row is not None
        and row.status == "failed"
        and row.attempts == attempts
        and 0 < row.max_attempts <= 10
        and _lower_hex_64(row.provider_idempotency_key)
        and row.claim_token_hash is None
        and row.claimed_at is None
        and row.lease_expires_at is None
        and _as_gate_utc(row.next_attempt_at) is not None
        and isinstance(row.code_ct, str)
        and bool(row.code_ct)
        and isinstance(row.destination_ct, str)
        and bool(row.destination_ct)
        and row.key_version == "v1"
        and row.last_error == "provider_send_failed"
        and row.delivered_at is None
        and row.provider_receipt_hash is None
        and row.provider_receipt_key_version is None
        and row.legacy_destination_retained is False
    )


def _sent_delivery_state_exact(row: Any, *, attempts: int = 2) -> bool:
    """Validate one successful retry, hashed receipt, and payload erasure."""

    return bool(
        row is not None
        and row.status == "sent"
        and row.attempts == attempts
        and 0 < row.max_attempts <= 10
        and _lower_hex_64(row.provider_idempotency_key)
        and row.claim_token_hash is None
        and row.claimed_at is None
        and row.lease_expires_at is None
        and row.next_attempt_at is None
        and row.code_ct is None
        and row.destination_ct is None
        and row.key_version == "v1"
        and row.last_error is None
        and _as_gate_utc(row.delivered_at) is not None
        and _lower_hex_64(row.provider_receipt_hash)
        and row.provider_receipt_key_version == "v1"
        and row.legacy_destination_retained is False
    )


def _attach_private_response_handle(
    app: FastAPI,
    response: Any,
    key: str | None,
) -> Any:
    """Attach a private DB handle/cookie solely to the in-memory QA response."""

    from app.core.config import settings
    from app.models.registration import OtpFlow
    from app.services import otp_flow_service

    state = getattr(app, "state", None)
    factory = getattr(state, "nyay17_session_factory", None)
    if factory is None:
        return response

    cookies = getattr(response, "cookies", None)
    raw_token = (
        cookies.get(settings.otp_flow_cookie_name) if cookies is not None else None
    )
    registration_id = None
    with factory() as session:
        if key is not None:
            record = _ledger_for_key(session, key)
            registration_id = getattr(record, "registration_id", None)
        if registration_id is None and isinstance(raw_token, str) and raw_token:
            registration_id = session.scalar(
                select(OtpFlow.registration_id).where(
                    OtpFlow.token_hash == otp_flow_service.flow_token_hash(raw_token)
                )
            )

    try:
        private_id = str(uuid.UUID(str(registration_id)))
    except (TypeError, ValueError):
        private_id = None
    if private_id is not None and getattr(response, "status_code", 0) == 202:
        setattr(response, "_nyay17_private_registration_id", private_id)
    if isinstance(raw_token, str) and raw_token:
        setattr(response, "_nyay17_private_flow_token", raw_token)
    return response


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


def _ledger_state_exact(
    record: Any,
    state: str,
    *,
    fingerprint_version: str = "v2",
) -> bool:
    """Validate one exact state/link/fingerprint inventory in memory."""

    if (
        record is None
        or record.state != state
        or fingerprint_version not in {"v1", "v2"}
    ):
        return False
    hash_value = record.idempotency_key_hash
    key_shape = bool(
        isinstance(hash_value, str) and re.fullmatch(r"[0-9a-f]{64}", hash_value)
    )
    if state == "pending":
        state_shape = bool(
            record.request_fingerprint_version == fingerprint_version
            and isinstance(record.request_fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", record.request_fingerprint)
            and record.registration_id is not None
            and record.outbox_id is not None
            and record.outcome_code is None
        )
    elif state == "succeeded":
        state_shape = bool(
            record.request_fingerprint_version == fingerprint_version
            and isinstance(record.request_fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", record.request_fingerprint)
            and record.registration_id is not None
            and record.outbox_id is None
            and record.outcome_code is None
        )
    elif state == "failed":
        state_shape = bool(
            record.request_fingerprint_version == fingerprint_version
            and isinstance(record.request_fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", record.request_fingerprint)
            and record.registration_id is None
            and record.outbox_id is None
            and record.outcome_code == "otp_delivery_failed"
        )
    elif state == "neutralized":
        state_shape = bool(
            record.request_fingerprint_version == fingerprint_version
            and isinstance(record.request_fingerprint, str)
            and re.fullmatch(r"[0-9a-f]{64}", record.request_fingerprint)
            and record.registration_id is None
            and record.outbox_id is None
            and record.outcome_code == "registration_neutralized"
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
        short_response.status_code == REGISTRATION_ACCEPTED_STATUS
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
        absent_response.status_code == REGISTRATION_ACCEPTED_STATUS
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


def _run_legacy_v1_replay_probe(
    engine: Engine,
    app: FastAPI,
    factory: sessionmaker[Session],
    sender: _CapturingSender,
) -> bool:
    """Prove a sealed v1 ledger replays before current fresh-write policy.

    The gate first creates a normal current graph, then turns only its private
    QA ledger fingerprint into an exact historical v1 binding.  The route must
    replay that already-bound request despite its legacy profile fields, while
    a changed v1 request remains a typed conflict.  No v1-shaped fresh write is
    attempted or accepted.
    """

    from app.schemas.registration import StudentRegisterRequest
    from app.services import registration_service

    current_payload = _base_registration_payload(107)
    legacy_payload = _legacy_v1_registration_payload(107)
    wire_key = "nyay17-sealed-v1-bound-replay"
    created = _post_registration(app, current_payload, wire_key)
    private_handle = _response_handle(created)
    legacy_request = StudentRegisterRequest.model_validate(legacy_payload)
    legacy_fingerprint = registration_service.registration_request_fingerprint(
        legacy_request,
        version=registration_service.REGISTRATION_REQUEST_FINGERPRINT_VERSION,
    )
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        if record is None or private_handle is None:
            return False
        record.request_fingerprint = legacy_fingerprint
        record.request_fingerprint_version = "v1"
        session.commit()

    tables = REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",)
    stable_before = _database_state_digest(engine, tables)
    delivery_before = sender.count
    exact = _post_registration(app, legacy_payload, wire_key)
    stable_after_exact = _database_state_digest(engine, tables)
    changed = deepcopy(legacy_payload)
    changed["first_name"] = "Maya"
    conflict = _post_registration(app, changed, wire_key)
    stable_after_conflict = _database_state_digest(engine, tables)
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        legacy_state_exact = _ledger_state_exact(
            record,
            "succeeded",
            fingerprint_version="v1",
        )
    return bool(
        created.status_code == REGISTRATION_ACCEPTED_STATUS
        and _registration_accepted_projection_is_exact(
            exact, private_handle=private_handle
        )
        and _response_handle(exact) == private_handle
        and _conflict_observation_passes(
            {
                "status": conflict.status_code,
                "error_code": _response_error_code(conflict),
                "error_field": _response_error_field(conflict),
                "graph_delta": {table: 0 for table in REGISTRATION_GRAPH_TABLES},
                "ledger_delta": 0,
                "delivery_delta": sender.count - delivery_before,
                "state_unchanged": stable_after_conflict == stable_after_exact,
            }
        )
        and stable_after_exact == stable_before
        and stable_after_conflict == stable_before
        and sender.count == delivery_before
        and legacy_state_exact
    )


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
            _signup_pending_projection_is_exact(
                first, private_handle=_response_handle(first)
            )
            and _signup_pending_projection_is_exact(
                replay, private_handle=_response_handle(replay)
            )
        ),
        "replay_status": replay.status_code,
        "public_handles_absent": bool(
            _response_is_identifier_free(first, private_handle=_response_handle(first))
            and _response_is_identifier_free(
                replay, private_handle=_response_handle(replay)
            )
        ),
        "private_subject_stable": bool(
            _response_handle(first) is not None
            and _response_handle(first) == _response_handle(replay)
        ),
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
        all(
            response.status_code == REGISTRATION_ACCEPTED_STATUS
            for response in equivalent_responses
        )
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
    # share one v2 fingerprint after model validation.
    explicit_null_payload = _base_registration_payload(105)
    optional_fields = (
        "middle_name",
        "consent",
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
        null_first.status_code == REGISTRATION_ACCEPTED_STATUS
        and omitted_replay.status_code == REGISTRATION_ACCEPTED_STATUS
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
    legacy_v1_replay_passed = _run_legacy_v1_replay_probe(engine, app, factory, sender)

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
        "legacy_passed": bool(
            _conflict_observation_passes(legacy_observation) and legacy_v1_replay_passed
        ),
        "legacy_cases": 2,
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


def _run_neutralized_ledger_probe(engine: Engine) -> dict[str, Any]:
    """Exercise the sixth ledger state through the real duplicate HTTP path."""

    from app.models.registration import OtpFlow, OtpPurposeAuthority
    from app.services import otp_flow_service

    sender = _CapturingSender()
    app, factory = _build_app_context(engine, sender)
    payload = _base_registration_payload(106)
    real_key = "nyay17-neutralized-real"
    neutral_key = "nyay17-neutralized-decoy"
    fixed_now = datetime.now(timezone.utc)
    delivery_clock = {"now": fixed_now}
    with (
        _registration_request_clock_scope(fixed_now),
        _registration_finalizer_clock_scope(delivery_clock),
    ):
        real = _post_registration(app, payload, real_key)
    real_token = _private_flow_token(real, real_key)
    before_graph = _database_state_digest(engine, REGISTRATION_GRAPH_TABLES)
    before_counts = _table_counts(
        factory,
        (
            "registration_idempotency_records",
            "otp_purpose_authorities",
            "otp_flows",
        ),
    )
    delivery_before = sender.count
    with _registration_request_clock_scope(fixed_now):
        neutral = _post_registration(app, payload, neutral_key)
    delivery_after = sender.count
    after_counts = _table_counts(
        factory,
        (
            "registration_idempotency_records",
            "otp_purpose_authorities",
            "otp_flows",
        ),
    )
    neutral_token = _private_flow_token(neutral, neutral_key)

    record = None
    flow = None
    authority = None
    with factory() as session:
        record = _ledger_for_key(session, neutral_key)
        if record is not None:
            flow = session.scalar(
                select(OtpFlow).where(
                    OtpFlow.registration_idempotency_record_id == record.id
                )
            )
        if flow is not None:
            authority = session.get(OtpPurposeAuthority, flow.authority_id)
        neutralized_state_exact = _ledger_state_exact(record, "neutralized")
        neutral_flow_exact = bool(
            flow is not None
            and record is not None
            and authority is not None
            and isinstance(neutral_token, str)
            and neutral_token
            == otp_flow_service.deterministic_signup_token(neutral_key)
            and flow.token_hash == otp_flow_service.flow_token_hash(neutral_token)
            and flow.registration_idempotency_record_id == record.id
            and flow.authority_id == authority.id
            and flow.registration_id is None
            and flow.challenge_id is None
            and flow.purpose == "signup"
            and flow.state == "pending"
            and flow.consumed_at is None
            and _as_gate_utc(flow.expires_at) is not None
            and _as_gate_utc(flow.expires_at) > fixed_now
            and _lower_hex_64(flow.subject_hash)
            and isinstance(flow.destination_masked_ct, str)
            and bool(flow.destination_masked_ct)
            and flow.key_version == "v1"
        )
        neutral_authority_exact = bool(
            authority is not None
            and flow is not None
            and authority.registration_id is None
            and authority.purpose == "signup"
            and _lower_hex_64(authority.subject_hash)
            and authority.subject_hash == flow.subject_hash
            and _as_gate_utc(authority.last_issued_at) == fixed_now
            and _as_gate_utc(authority.cooldown_until) is not None
            and _as_gate_utc(authority.cooldown_until) > fixed_now
        )

    observed_tables = REGISTRATION_GRAPH_TABLES + (
        "registration_idempotency_records",
        "otp_purpose_authorities",
        "otp_flows",
    )
    stable_before_replay = _database_state_digest(engine, observed_tables)
    replay_delivery_before = sender.count
    with _registration_request_clock_scope(fixed_now):
        replay = _post_registration(app, payload, neutral_key)
    stable_after_replay = _database_state_digest(engine, observed_tables)
    replay_delivery_after = sender.count
    replay_token = _private_flow_token(replay, neutral_key)

    mutation_before = stable_after_replay
    mutation_delivery_before = sender.count
    with _registration_request_clock_scope(fixed_now):
        mutation = _post_registration(
            app,
            _canonical_field_mutations(payload)[0],
            neutral_key,
        )
    mutation_after = _database_state_digest(engine, observed_tables)

    try:
        projection_matches_real = neutral.json() == real.json()
        replay_projection_stable = replay.json() == neutral.json()
    except Exception:  # noqa: BLE001 - fail-closed public projection oracle
        projection_matches_real = False
        replay_projection_stable = False
    observation = {
        "response_status": neutral.status_code,
        "projection_exact": _neutralized_pending_projection_is_exact(neutral),
        "projection_matches_real": projection_matches_real,
        "public_identifier_absent": bool(
            _response_is_identifier_free(neutral)
            and _response_is_identifier_free(replay)
            and _response_is_identifier_free(mutation)
        ),
        "private_registration_absent": bool(
            _response_handle(neutral) is None
            and _response_handle(replay) is None
            and _response_handle(mutation) is None
        ),
        "distinct_deterministic_cookie": bool(
            isinstance(real_token, str)
            and isinstance(neutral_token, str)
            and real_token != neutral_token
            and neutral_token
            == otp_flow_service.deterministic_signup_token(neutral_key)
        ),
        "neutralized_state_exact": neutralized_state_exact,
        "neutral_flow_exact": neutral_flow_exact,
        "neutral_authority_exact": neutral_authority_exact,
        "real_graph_unchanged": (
            _database_state_digest(engine, REGISTRATION_GRAPH_TABLES) == before_graph
        ),
        "real_provider_delta": delivery_after - delivery_before,
        "ledger_delta": (
            after_counts["registration_idempotency_records"]
            - before_counts["registration_idempotency_records"]
        ),
        "authority_delta": (
            after_counts["otp_purpose_authorities"]
            - before_counts["otp_purpose_authorities"]
        ),
        "flow_delta": after_counts["otp_flows"] - before_counts["otp_flows"],
        "replay_status": replay.status_code,
        "replay_projection_stable": bool(
            replay_projection_stable
            and _neutralized_pending_projection_is_exact(replay)
        ),
        "replay_cookie_stable": bool(
            isinstance(neutral_token, str) and replay_token == neutral_token
        ),
        "replay_state_unchanged": stable_after_replay == stable_before_replay,
        "replay_provider_delta": replay_delivery_after - replay_delivery_before,
        "mutation_conflict_exact": bool(
            mutation.status_code == 409
            and _response_error_code(mutation) == "idempotency_conflict"
            and _response_error_field(mutation) == "Idempotency-Key"
        ),
        "mutation_state_unchanged": mutation_after == mutation_before,
        "mutation_provider_delta": sender.count - mutation_delivery_before,
    }
    return {"passed": _neutralized_observation_passes(observation)}


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
    verified = (
        _post_signup_verify(app, registered, wire_key, delivered_code)
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
        "verification_body_exact": bool(
            verified is not None
            and _signup_authenticated_projection_is_exact(
                verified, registration_payload=payload
            )
        ),
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
        OtpPurposeAuthority,
        StudentRegistration,
    )
    from app.services import otp_flow_service

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
        return _post_signup_verify(app, registered, wire_key, delivered_code)

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
        authority_id = control.scalar(
            select(OtpPurposeAuthority.id).where(
                OtpPurposeAuthority.registration_id == registration_id,
                OtpPurposeAuthority.purpose == "signup",
            )
        )
        if authority_id is None:
            return {"passed": False, "cases": 1}
        control.scalar(
            select(OtpPurposeAuthority)
            .where(OtpPurposeAuthority.id == authority_id)
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
            return _post_signup_verify(
                app_two,
                registered_two,
                wire_key_two,
                delivered_code_two,
            )

        control_two = factory_two()
        try:
            authority_id_two = control_two.scalar(
                select(OtpPurposeAuthority.id).where(
                    OtpPurposeAuthority.registration_id == registration_id_two,
                    OtpPurposeAuthority.purpose == "signup",
                )
            )
            if authority_id_two is not None:
                control_two.scalar(
                    select(OtpPurposeAuthority)
                    .where(OtpPurposeAuthority.id == authority_id_two)
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
                try:
                    activation_detail_two = activation_response_two.json().get(
                        "detail", {}
                    )
                except Exception:  # noqa: BLE001 - fail-closed response oracle
                    activation_detail_two = {}
                activation_denied_exact = bool(
                    activation_response_two.status_code == 401
                    and isinstance(activation_detail_two, dict)
                    and activation_detail_two.get("code") == "otp_failed"
                    and activation_detail_two.get("otp_state")
                    == otp_flow_service.unavailable_state()
                    and activation_response_two.headers.get("cache-control")
                    == "private, no-store"
                    and activation_response_two.headers.get("vary") == "Cookie"
                    and _response_is_identifier_free(
                        activation_response_two, private_handle=handle_two
                    )
                )
                retention_wins = bool(
                    retention_waited_two
                    and both_waited_two
                    and _backend_cardinality_is_exact(race_backend_count_two, 2)
                    and retention_completed_two
                    and activation_denied_exact
                    and erased_two
                    and row_erased_two
                    and _retired_observation_passes(terminal_two)
                    and sender_two.count == 1
                )
        finally:
            control_two.rollback()
            control_two.close()
    activation_body_exact = _signup_authenticated_projection_is_exact(
        activation_response,
        registration_payload=payload,
    )
    backend_exact = _backend_cardinality_is_exact(race_backend_count, 2)
    activation_private = _response_is_identifier_free(
        activation_response, private_handle=handle
    )
    terminal_passed = _retired_observation_passes(terminal)
    sender_exact = sender.count == 1
    passed = bool(
        registered.status_code == REGISTRATION_ACCEPTED_STATUS
        and activation_waited
        and both_waited
        and backend_exact
        and activation_response.status_code == 200
        and activation_body_exact
        and activation_private
        and retention_completed
        and retired_preserved
        and row_erased
        and terminal_passed
        and sender_exact
        and retention_wins
    )
    return {
        "passed": passed,
        "cases": 2,
        "registration_created": (
            registered.status_code == REGISTRATION_ACCEPTED_STATUS
        ),
        "activation_waited": activation_waited,
        "both_waited": both_waited,
        "backend_exact": backend_exact,
        "activation_status_exact": activation_response.status_code == 200,
        "activation_body_exact": activation_body_exact,
        "activation_private": activation_private,
        "retention_completed": retention_completed,
        "retired_preserved": retired_preserved,
        "row_erased": row_erased,
        "terminal_passed": terminal_passed,
        "sender_exact": sender_exact,
        "retention_wins": retention_wins,
    }


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
    from app.models.registration import OtpOutbox

    ledger_table = ("registration_idempotency_records",)
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    crash_sender = _CrashSender()
    crash_app, factory = _build_app_context(engine, crash_sender)
    payload = _base_registration_payload(221)
    wire_key = "nyay17-pending-crash"
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    clock = {"now": datetime.now(timezone.utc)}
    with _registration_finalizer_clock_scope(clock):
        crashed = _post_registration(crash_app, payload, wire_key)
    after_crash_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_crash_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        pending_exact = _ledger_state_exact(record, "pending")
        pending_handle = (
            str(record.registration_id)
            if record is not None and record.registration_id is not None
            else None
        )
        outbox_id = record.outbox_id if record is not None else None
        claimed = session.get(OtpOutbox, outbox_id) if outbox_id is not None else None
        claimed_exact = _claimed_delivery_state_exact(claimed)
        lease_expires_at = _as_gate_utc(getattr(claimed, "lease_expires_at", None))
        provider_key = getattr(claimed, "provider_idempotency_key", None)

    mismatch_before = _database_state_digest(engine, all_tables)
    mismatch_invocations_before = crash_sender.attempts
    with _registration_finalizer_clock_scope(clock):
        mismatch = _post_registration(
            crash_app, _canonical_field_mutations(payload)[0], wire_key
        )
    mismatch_unchanged = bool(
        _database_state_digest(engine, all_tables) == mismatch_before
        and crash_sender.attempts == mismatch_invocations_before
    )

    resume_sender = _CapturingSender()
    resume_app, _ = _build_app_context(engine, resume_sender)
    immediate_state = _database_state_digest(engine, all_tables)
    immediate_delivery_before = resume_sender.count
    if lease_expires_at is not None:
        clock["now"] = lease_expires_at - timedelta(microseconds=1)
    with _registration_finalizer_clock_scope(clock):
        immediate = _post_registration(resume_app, payload, wire_key)
    immediate_stable = bool(
        _database_state_digest(engine, all_tables) == immediate_state
        and resume_sender.count == 0
    )
    immediate_delivery_delta = resume_sender.count - immediate_delivery_before

    resume_graph_before = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    if lease_expires_at is not None:
        clock["now"] = lease_expires_at + timedelta(seconds=1)
    with _registration_finalizer_clock_scope(clock):
        resumed = _post_registration(resume_app, payload, wire_key)
    resume_graph_after = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    with factory() as session:
        succeeded_exact = _ledger_state_exact(
            _ledger_for_key(session, wire_key), "succeeded"
        )
        sent = session.get(OtpOutbox, outbox_id) if outbox_id is not None else None
        sent_exact = _sent_delivery_state_exact(sent)
        stable_provider_key = bool(
            _lower_hex_64(provider_key)
            and getattr(sent, "provider_idempotency_key", None) == provider_key
        )
    followup_before = _database_state_digest(engine, all_tables)
    delivery_before = resume_sender.count
    with _registration_finalizer_clock_scope(clock):
        followup = _post_registration(resume_app, payload, wire_key)
    followup_stable = bool(
        followup.status_code == REGISTRATION_ACCEPTED_STATUS
        and _response_handle(followup) == _response_handle(resumed)
        and resume_sender.count == delivery_before
        and _database_state_digest(engine, all_tables) == followup_before
    )
    observation = {
        "crash_status": crashed.status_code,
        "crash_projection_exact": _post_response_crash_projection_is_exact(
            crashed, private_handle=pending_handle
        ),
        "pending_state_exact": pending_exact,
        "claimed_delivery_exact": claimed_exact,
        "pending_mismatch_status": mismatch.status_code,
        "pending_mismatch_code": _response_error_code(mismatch),
        "pending_mismatch_field": _response_error_field(mismatch),
        "pending_mismatch_state_unchanged": mismatch_unchanged,
        "immediate_replay_status": immediate.status_code,
        "immediate_projection_exact": _signup_pending_projection_is_exact(
            immediate, private_handle=_response_handle(immediate)
        ),
        "immediate_delivery_delta": immediate_delivery_delta,
        "immediate_state_unchanged": immediate_stable,
        "resume_status": resumed.status_code,
        "public_handles_absent": bool(
            _response_is_identifier_free(mismatch, private_handle=pending_handle)
            and _response_is_identifier_free(immediate, private_handle=pending_handle)
            and _response_is_identifier_free(resumed, private_handle=pending_handle)
            and _response_is_identifier_free(followup, private_handle=pending_handle)
        ),
        "private_subject_stable": bool(
            pending_handle is not None
            and _response_handle(immediate) == pending_handle
            and _response_handle(resumed) == pending_handle
            and _response_handle(followup) == pending_handle
        ),
        "succeeded_state_exact": succeeded_exact,
        "sent_delivery_exact": sent_exact,
        "stable_provider_key": stable_provider_key,
        "ledger_delta": after_crash_ledger - before_ledger,
        "graph_delta": _count_delta(before_graph, after_crash_graph),
        "resume_graph_delta_zero": _zero_deltas(
            _count_delta(resume_graph_before, resume_graph_after)
        ),
        "crash_provider_invocations": crash_sender.attempts,
        "crash_provider_acceptances": crash_sender.count,
        "resume_provider_invocations": resume_sender.count,
        "resume_provider_acceptances": resume_sender.count,
        "provider_acceptances_total": crash_sender.count + resume_sender.count,
        "followup_stable": followup_stable,
    }
    return {
        "passed": _pending_resume_observation_passes(observation),
        "crash_provider_invocations": crash_sender.attempts,
        "crash_provider_acceptances": crash_sender.count,
        "resume_provider_acceptances": resume_sender.count,
        "crash_setup_exact": bool(
            observation["crash_status"] == REGISTRATION_ACCEPTED_STATUS
            and observation["crash_projection_exact"]
            and observation["pending_state_exact"]
            and observation["claimed_delivery_exact"]
        ),
        "mismatch_exact": bool(
            observation["pending_mismatch_status"] == 409
            and observation["pending_mismatch_code"] == "idempotency_conflict"
            and observation["pending_mismatch_field"] == "Idempotency-Key"
            and observation["pending_mismatch_state_unchanged"]
        ),
        "immediate_replay_exact": bool(
            observation["immediate_replay_status"] == REGISTRATION_ACCEPTED_STATUS
            and observation["immediate_projection_exact"]
            and observation["immediate_delivery_delta"] == 0
            and observation["immediate_state_unchanged"]
        ),
        "recovery_exact": bool(
            observation["resume_status"] == REGISTRATION_ACCEPTED_STATUS
            and observation["public_handles_absent"]
            and observation["private_subject_stable"]
            and observation["succeeded_state_exact"]
            and observation["sent_delivery_exact"]
            and observation["stable_provider_key"]
            and observation["resume_graph_delta_zero"]
            and observation["resume_provider_invocations"] == 1
            and observation["provider_acceptances_total"] == 1
            and observation["followup_stable"]
        ),
    }


def _run_accepted_crash_projection(engine: Engine) -> dict[str, Any]:
    """Prove an accepted crash retries one stable provider operation."""

    from app.models.registration import OtpOutbox

    ledger_table = ("registration_idempotency_records",)
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    sender = _AcceptedCrashSender()
    app, factory = _build_app_context(engine, sender)
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    payload = _base_registration_payload(222)
    wire_key = "nyay17-accepted-crash-projection"
    clock = {"now": datetime.now(timezone.utc)}
    with _registration_finalizer_clock_scope(clock):
        response = _post_registration(app, payload, wire_key)
    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        pending_exact = _ledger_state_exact(record, "pending")
        private_handle = (
            str(record.registration_id)
            if record is not None and record.registration_id is not None
            else None
        )
        outbox_id = record.outbox_id if record is not None else None
        claimed = session.get(OtpOutbox, outbox_id) if outbox_id is not None else None
        claimed_exact = _claimed_delivery_state_exact(claimed)
        lease_expires_at = _as_gate_utc(getattr(claimed, "lease_expires_at", None))
        provider_key = getattr(claimed, "provider_idempotency_key", None)

    before_replay = _database_state_digest(engine, all_tables)
    if lease_expires_at is not None:
        clock["now"] = lease_expires_at - timedelta(microseconds=1)
    with _registration_finalizer_clock_scope(clock):
        immediate = _post_registration(app, payload, wire_key)
    immediate_stable = bool(
        sender.attempts == 1
        and sender.count == 1
        and _database_state_digest(engine, all_tables) == before_replay
    )

    if lease_expires_at is not None:
        clock["now"] = lease_expires_at + timedelta(seconds=1)
    with _registration_finalizer_clock_scope(clock):
        recovered = _post_registration(app, payload, wire_key)
    with factory() as session:
        succeeded_exact = _ledger_state_exact(
            _ledger_for_key(session, wire_key), "succeeded"
        )
        sent = session.get(OtpOutbox, outbox_id) if outbox_id is not None else None
        sent_exact = _sent_delivery_state_exact(sent)
        stable_provider_key = bool(
            _lower_hex_64(provider_key)
            and getattr(sent, "provider_idempotency_key", None) == provider_key
        )
    final_state = _database_state_digest(engine, all_tables)
    attempts_before = sender.attempts
    with _registration_finalizer_clock_scope(clock):
        final_replay = _post_registration(app, payload, wire_key)
    final_stable = bool(
        sender.attempts == attempts_before
        and _database_state_digest(engine, all_tables) == final_state
    )
    observed = bool(
        _post_response_crash_projection_is_exact(
            response, private_handle=private_handle
        )
        and immediate.status_code == REGISTRATION_ACCEPTED_STATUS
        and _signup_pending_projection_is_exact(
            immediate, private_handle=_response_handle(immediate)
        )
        and immediate_stable
        and recovered.status_code == REGISTRATION_ACCEPTED_STATUS
        and final_replay.status_code == REGISTRATION_ACCEPTED_STATUS
        and _response_is_identifier_free(immediate, private_handle=private_handle)
        and _response_is_identifier_free(recovered, private_handle=private_handle)
        and _response_is_identifier_free(final_replay, private_handle=private_handle)
        and _response_handle(immediate)
        == _response_handle(recovered)
        == _response_handle(final_replay)
        == private_handle
        and sender.attempts == 2
        and sender.count == 1
        and pending_exact
        and claimed_exact
        and succeeded_exact
        and sent_exact
        and stable_provider_key
        and final_stable
        and _single_graph_delta(_count_delta(before_graph, after_graph))
        and after_ledger - before_ledger == 1
    )
    return {
        "observed": observed,
        "provider_acceptances": sender.count,
        "provider_invocations": sender.attempts,
        "pending_state_exact": pending_exact,
    }


def _age_signup_challenge(
    factory: sessionmaker[Session],
    registration_handle: str | None,
    *,
    age_days: int = RECENT_PROBE_HISTORY_AGE_DAYS,
    now: datetime | None = None,
) -> None:
    from app.models.registration import OtpChallenge

    registration_id = uuid.UUID(str(registration_handle))
    reference_now = _as_gate_utc(now) or datetime.now(timezone.utc)
    aged_at = reference_now - timedelta(days=age_days)
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
            challenge.expires_at = reference_now + timedelta(minutes=5)
        session.commit()


def _open_pending_resend_window(
    factory: sessionmaker[Session],
    registration_handle: str | None,
    *,
    wire_key: str,
) -> dict[str, Any] | None:
    """Expire only the crash lease/backoff and resend cooldown, never history."""

    from app.models.registration import OtpChallenge, OtpOutbox, OtpPurposeAuthority

    try:
        registration_id = uuid.UUID(str(registration_handle))
    except (TypeError, ValueError):
        return None
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        if not _ledger_state_exact(record, "pending"):
            return None
        row = session.get(OtpOutbox, record.outbox_id)
        challenge = (
            session.get(OtpChallenge, row.challenge_id) if row is not None else None
        )
        authority = (
            session.get(OtpPurposeAuthority, challenge.authority_id)
            if challenge is not None
            else None
        )
        claimed_at = _as_gate_utc(getattr(row, "claimed_at", None))
        if (
            row is None
            or challenge is None
            or authority is None
            or record.registration_id != registration_id
            or challenge.registration_id != registration_id
            or challenge.authority_id != authority.id
            or challenge.purpose != "signup"
            or row.purpose != "signup"
            or row.status not in {"claimed", "failed"}
            or not _lower_hex_64(row.provider_idempotency_key)
            or (row.status == "claimed" and not _lower_hex_64(row.claim_token_hash))
        ):
            return None
        operation_now = datetime.now(timezone.utc)
        if claimed_at is not None:
            operation_now = max(
                operation_now,
                claimed_at + timedelta(seconds=1),
            )
        opened_at = operation_now - timedelta(microseconds=1)
        authority.cooldown_until = opened_at
        authority.updated_at = operation_now
        if row.status == "claimed":
            if claimed_at is None or opened_at <= claimed_at:
                return None
            row.lease_expires_at = opened_at
        else:
            row.next_attempt_at = opened_at
        initial = {
            "operation_now": operation_now,
            "original_outbox_id": row.id,
            "initial_provider_key": row.provider_idempotency_key,
            "initial_claim_hash": row.claim_token_hash,
        }
        session.commit()
        return initial


def _pending_resend_shape(
    factory: sessionmaker[Session],
    *,
    registration_handle: str | None,
    wire_key: str,
    window: Mapping[str, Any],
    pre_relay: bool,
) -> dict[str, Any]:
    from app.models.registration import OtpChallenge, OtpOutbox

    registration_id = uuid.UUID(str(registration_handle))
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        linked_id = record.outbox_id if record is not None else None
        linked = session.get(OtpOutbox, linked_id) if linked_id is not None else None
        original_outbox_id = window.get("original_outbox_id")
        original = (
            session.get(OtpOutbox, original_outbox_id)
            if original_outbox_id is not None
            else None
        )
        linked_challenge = (
            session.get(OtpChallenge, linked.challenge_id)
            if linked is not None
            else None
        )
        provider_key = getattr(linked, "provider_idempotency_key", None)
        claim_hash = getattr(linked, "claim_token_hash", None)
        initial_provider_key = window.get("initial_provider_key")
        initial_claim_hash = window.get("initial_claim_hash")
        return {
            "target_outbox_id": linked_id,
            "ledger_reused_original_during_send": bool(
                record is not None
                and record.state == "pending"
                and linked_id == original_outbox_id
            ),
            "ledger_repointed_to_replacement_during_send": bool(
                record is not None
                and record.state == "pending"
                and linked_id is not None
                and original_outbox_id is not None
                and linked_id != original_outbox_id
            ),
            "claimed_delivery_exact": _claimed_delivery_state_exact(
                linked, attempts=1 if pre_relay else 2
            ),
            "provider_key_authority_exact": bool(
                _lower_hex_64(provider_key)
                and _lower_hex_64(initial_provider_key)
                and (
                    provider_key != initial_provider_key
                    if pre_relay
                    else provider_key == initial_provider_key
                )
            ),
            "claim_fence_exact": bool(
                linked_challenge is not None
                and linked_challenge.registration_id == registration_id
                and _lower_hex_64(claim_hash)
                and (
                    pre_relay
                    or not hmac.compare_digest(str(claim_hash), str(initial_claim_hash))
                )
            ),
            "original_sent_erased_before_replacement": bool(
                pre_relay and _sent_delivery_state_exact(original, attempts=2)
            ),
        }


def _pending_resend_final_shape(
    factory: sessionmaker[Session],
    *,
    registration_handle: str | None,
    wire_key: str,
    target_outbox_id: uuid.UUID | None,
    pre_relay: bool,
) -> dict[str, Any]:
    from app.models.registration import OtpChallenge, OtpOutbox

    registration_id = uuid.UUID(str(registration_handle))
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        target = (
            session.get(OtpOutbox, target_outbox_id)
            if target_outbox_id is not None
            else None
        )
        challenges = list(
            session.scalars(
                select(OtpChallenge).where(
                    OtpChallenge.registration_id == registration_id,
                    OtpChallenge.purpose == "signup",
                )
            )
        )
        challenge_ids = [challenge.id for challenge in challenges]
        relayable = (
            list(
                session.scalars(
                    select(OtpOutbox.id).where(
                        OtpOutbox.challenge_id.in_(challenge_ids),
                        OtpOutbox.status.in_(("pending", "claimed", "failed")),
                        OtpOutbox.code_ct.is_not(None),
                    )
                )
            )
            if challenge_ids
            else []
        )
        return {
            "succeeded_state_exact": _ledger_state_exact(record, "succeeded"),
            "sent_delivery_exact": _sent_delivery_state_exact(
                target, attempts=1 if pre_relay else 2
            ),
            "active_signup_challenges": sum(
                challenge.delivery_state == "active" and challenge.consumed_at is None
                for challenge in challenges
            ),
            "relayable_signup_payloads": len(relayable),
        }


def _resend_graph_is_exact(
    before: Mapping[str, int],
    after: Mapping[str, int],
    *,
    pre_relay: bool,
) -> bool:
    expected = {
        "users": 1,
        "student_registrations": 1,
        "student_profiles": 1,
        "student_verifications": 1,
        "guardian_consents": 0,
        "consents": 2,
        "otp_challenges": 2 if pre_relay else 1,
        "otp_outbox": 2 if pre_relay else 1,
        "audit_events": 1,
    }
    return _count_delta(before, after) == expected


def _run_pending_resend_case(
    engine: Engine,
    *,
    sequence: int,
    concurrent: bool,
    pre_relay: bool = False,
    diagnostics: dict[str, bool] | None = None,
) -> bool:
    before_graph: dict[str, int]
    crash_sender = _CrashSender()
    crash_app, factory = _build_app_context(engine, crash_sender)
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    payload = _base_registration_payload(sequence)
    wire_key = f"nyay17-pending-resend-{sequence}"
    clock = {"now": datetime.now(timezone.utc)}
    with _registration_finalizer_clock_scope(clock):
        crashed = _post_registration(crash_app, payload, wire_key)
    with factory() as session:
        handle = _durable_registration_handle_for_key(session, wire_key)
        initial_record = _ledger_for_key(session, wire_key)
        pending_exact = _ledger_state_exact(initial_record, "pending")
    if (
        not _post_response_crash_projection_is_exact(crashed, private_handle=handle)
        or not pending_exact
        or handle is None
    ):
        return False
    window = _open_pending_resend_window(
        factory,
        handle,
        wire_key=wire_key,
    )
    if window is None:
        return False
    clock["now"] = window["operation_now"]
    relay_passed = True
    relay_sender = _CapturingSender()
    if pre_relay:
        from app.services import otp_outbox

        with factory() as session:
            relay_passed = bool(
                window["original_outbox_id"] is not None
                and otp_outbox.run_delivery(
                    session,
                    otp_outbox.DeliveryIntent(outbox_id=window["original_outbox_id"]),
                    relay_sender,
                    raise_on_failure=True,
                    now=window["operation_now"],
                )
                and relay_sender.count == 1
                and _ledger_state_exact(_ledger_for_key(session, wire_key), "pending")
            )

    sender: _CapturingSender = _BlockingSender()
    peer_completed = False
    winner_blocked = False
    if concurrent:
        tracker = _PgBackendTracker()
        app, _ = _build_app_context(engine, sender, backend_tracker=tracker)
        with (
            _registration_request_clock_scope(window["operation_now"]),
            _registration_resend_clock_scope(clock),
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                resend_future = executor.submit(
                    _post_signup_resend, app, crashed, wire_key
                )
                if not sender.entered.wait(timeout=15):
                    sender.release.set()
                    return False
                shape = _pending_resend_shape(
                    factory,
                    registration_handle=handle,
                    wire_key=wire_key,
                    window=window,
                    pre_relay=pre_relay,
                )
                replay_future = executor.submit(
                    _post_registration, app, payload, wire_key
                )
                try:
                    replay = replay_future.result(timeout=5)
                    peer_completed = True
                except TimeoutError:
                    peer_completed = False
                    replay = None
                winner_blocked = not resend_future.done()
                backend_count = tracker.count
                sender.release.set()
                resend = resend_future.result(timeout=30)
                if replay is None:
                    replay = replay_future.result(timeout=30)
    else:
        app, _ = _build_app_context(engine, sender)
        with (
            _registration_request_clock_scope(window["operation_now"]),
            _registration_resend_clock_scope(clock),
        ):
            with ThreadPoolExecutor(max_workers=1) as executor:
                resend_future = executor.submit(
                    _post_signup_resend, app, crashed, wire_key
                )
                if not sender.entered.wait(timeout=15):
                    sender.release.set()
                    return False
                shape = _pending_resend_shape(
                    factory,
                    registration_handle=handle,
                    wire_key=wire_key,
                    window=window,
                    pre_relay=pre_relay,
                )
                winner_blocked = not resend_future.done()
                sender.release.set()
                resend = resend_future.result(timeout=30)
            replay = _post_registration(app, payload, wire_key)
        backend_count = 0

    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    final_shape = _pending_resend_final_shape(
        factory,
        registration_handle=handle,
        wire_key=wire_key,
        target_outbox_id=shape["target_outbox_id"],
        pre_relay=pre_relay,
    )
    observation = {
        "resend_status": resend.status_code,
        "replay_status": replay.status_code,
        "public_handles_absent": bool(
            _response_is_identifier_free(crashed, private_handle=handle)
            and _response_is_identifier_free(resend, private_handle=handle)
            and _response_is_identifier_free(replay, private_handle=handle)
        ),
        "private_subject_stable": bool(
            handle is not None and _response_handle(replay) == handle
        ),
        "ledger_reused_original_during_send": shape[
            "ledger_reused_original_during_send"
        ],
        "ledger_repointed_to_replacement_during_send": shape[
            "ledger_repointed_to_replacement_during_send"
        ],
        "claimed_delivery_exact": shape["claimed_delivery_exact"],
        "provider_key_authority_exact": shape["provider_key_authority_exact"],
        "claim_fence_exact": shape["claim_fence_exact"],
        "original_sent_erased_before_replacement": shape[
            "original_sent_erased_before_replacement"
        ],
        "succeeded_state_exact": bool(
            final_shape["succeeded_state_exact"] and final_shape["sent_delivery_exact"]
        ),
        "registration_graph_exact": _resend_graph_is_exact(
            before_graph, after_graph, pre_relay=pre_relay
        ),
        "active_signup_challenges": final_shape["active_signup_challenges"],
        "relayable_signup_payloads": final_shape["relayable_signup_payloads"],
        "provider_acceptances": relay_sender.count + sender.count,
        "backend_count": backend_count,
        "peer_completed_before_release": peer_completed,
        "winner_blocked_before_release": winner_blocked,
    }
    passed = bool(
        relay_passed
        and _pending_resend_observation_passes(
            observation,
            concurrent=concurrent,
            pre_relay=pre_relay,
        )
    )
    if diagnostics is not None:
        diagnostics.update(
            {
                "relay": relay_passed,
                "resend_status": observation["resend_status"] == 202,
                "replay_status": (
                    observation["replay_status"] == REGISTRATION_ACCEPTED_STATUS
                ),
                "public_identifiers_absent": observation["public_handles_absent"],
                "subject_stable": observation["private_subject_stable"],
                "original_link": observation["ledger_reused_original_during_send"]
                is (not pre_relay),
                "replacement_link": observation[
                    "ledger_repointed_to_replacement_during_send"
                ]
                is pre_relay,
                "claimed_delivery": observation["claimed_delivery_exact"],
                "provider_authority": observation["provider_key_authority_exact"],
                "claim_fence": observation["claim_fence_exact"],
                "original_sent": observation["original_sent_erased_before_replacement"]
                is pre_relay,
                "succeeded": observation["succeeded_state_exact"],
                "graph": observation["registration_graph_exact"],
                "one_active": observation["active_signup_challenges"] == 1,
                "no_relayable": observation["relayable_signup_payloads"] == 0,
                "acceptances": observation["provider_acceptances"]
                == (2 if pre_relay else 1),
                "backend": (observation["backend_count"] == 2 if concurrent else True),
                "peer_completed": (
                    observation["peer_completed_before_release"] if concurrent else True
                ),
                "winner_blocked": (
                    observation["winner_blocked_before_release"] if concurrent else True
                ),
            }
        )
    return passed


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
        not _post_response_crash_projection_is_exact(crashed, private_handle=handle)
        or handle is None
    ):
        return False
    registration_id = uuid.UUID(handle)
    window = _open_pending_resend_window(
        factory,
        handle,
        wire_key=wire_key,
    )
    if window is None:
        return False
    with factory() as session:
        _, intent = otp_service.resend(
            session,
            registration_id,
            window["operation_now"],
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
                now=window["operation_now"],
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
        if (
            unrelated.status_code != REGISTRATION_ACCEPTED_STATUS
            or unrelated_handle is None
        ):
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
        expected_delivery_available = False
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
    crosslink_response = _post_signup_resend(crosslink_app, pending, wire_key)
    crosslink_rejected = bool(
        _post_response_crash_projection_is_exact(pending, private_handle=handle)
        and crosslink_installed
        and crosslink_response.status_code == 500
        and _opaque_internal_error_is_exact(crosslink_response, private_handle=handle)
        and crosslink_sender.count == 0
        and _database_state_digest(
            engine,
            REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",),
        )
        == state_before
    )
    if crosslink_installed and original_pending_outbox_id is not None:
        with factory() as session:
            record = _ledger_for_key(session, wire_key)
            if record is not None:
                record.outbox_id = original_pending_outbox_id
                session.commit()
    ordinary_diagnostics: dict[str, bool] = {}
    concurrent_diagnostics: dict[str, bool] = {}
    pre_relay_diagnostics: dict[str, bool] = {}
    ordinary = _run_pending_resend_case(
        engine,
        sequence=223,
        concurrent=False,
        diagnostics=ordinary_diagnostics,
    )
    concurrent = _run_pending_resend_case(
        engine,
        sequence=224,
        concurrent=True,
        diagnostics=concurrent_diagnostics,
    )
    pre_relay = _run_pending_resend_case(
        engine,
        sequence=228,
        concurrent=False,
        pre_relay=True,
        diagnostics=pre_relay_diagnostics,
    )
    cases = (ordinary, concurrent, pre_relay, crosslink_rejected)
    helper_waits = _run_resend_helper_terminal_wait_probes(engine)
    return {
        "passed": all(cases) and helper_waits["passed"],
        "cases": len(cases) + helper_waits["cases"],
        "ordinary_passed": ordinary,
        "concurrent_passed": concurrent,
        "pre_relay_passed": pre_relay,
        "crosslink_passed": crosslink_rejected,
        "helper_waits_passed": helper_waits["passed"],
        "ordinary_diagnostics": ordinary_diagnostics,
        "concurrent_diagnostics": concurrent_diagnostics,
        "pre_relay_diagnostics": pre_relay_diagnostics,
        "product_seam_mutants_killed": int(crosslink_rejected)
        + helper_waits["product_seam_mutants_killed"],
    }


def _run_pending_retention_purge_case(
    engine: Engine, *, sequence: int, mode: str
) -> dict[str, Any]:
    from app.core import retention
    from app.db.models.audit import AuditEvent
    from app.models.registration import (
        OtpChallenge,
        OtpFlow,
        OtpOutbox,
        StudentProfile,
    )

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
        not _post_response_crash_projection_is_exact(crashed, private_handle=handle)
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
            flow = session.scalar(
                select(OtpFlow).where(
                    OtpFlow.registration_id == uuid.UUID(handle),
                    OtpFlow.purpose == "signup",
                )
            )
            record = _ledger_for_key(session, wire_key)
            if challenge is None or flow is None or record is None:
                return {"passed": False, "cases": 0}
            # Expire the browser capability first. The product then fences the
            # crash-left provider claim before erasing registration authority.
            flow.expires_at = now - timedelta(seconds=1)
            # Use a uniquely far-old window so this exact subject is the only
            # eligible challenge even after earlier probes age resend history.
            challenge.created_at = now - timedelta(
                days=PENDING_RETENTION_TARGET_AGE_DAYS
            )
            challenge.expires_at = now - timedelta(minutes=1)
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
        "consents": 2,
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
        "expired_flows": counts.get("otp_flows", 0),
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
        "diagnostics": {
            "expired_one": observation["expired_flows"] == 1,
            "generic_challenge_sweep_zero": observation["purged_challenges"] == 0,
            "transitioned_one": observation["registration_transitions"] == 1,
            "erased_state": observation["erased_state_exact"],
            "policy_shape": observation["policy_mode_shape_exact"],
            "audit_action": observation["audit_action_exact"],
            "payload_absent": observation["relayable_payload_absent"],
            "case_count": observation["terminal_cases"]
            == len(CANONICAL_FIELD_PATHS) + 1,
            "statuses": observation["all_terminal_statuses_409"],
            "codes": observation["all_terminal_codes_expired"],
            "fields": observation["all_terminal_fields_idempotency_key"],
            "uniform": observation["uniform_response_bytes"],
            "provider_zero": observation["provider_acceptances"] == 0,
            "replays_stable": observation["state_unchanged_on_replays"],
        },
    }


def _run_succeeded_retention_purge_probe(
    engine: Engine, *, diagnostics: dict[str, bool] | None = None
) -> bool:
    from app.core import retention
    from app.models.registration import (
        OtpChallenge,
        OtpFlow,
        OtpOutbox,
        OtpPurposeAuthority,
    )

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
        replay.status_code == REGISTRATION_ACCEPTED_STATUS
        and _response_handle(replay) == handle
        and sender.count == delivery_before_replay
    )
    with factory() as session:
        authority = session.scalar(
            select(OtpPurposeAuthority).where(
                OtpPurposeAuthority.registration_id == registration_id,
                OtpPurposeAuthority.purpose == "signup",
            )
        )
        flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.registration_id == registration_id,
                OtpFlow.purpose == "signup",
            )
        )
        cooldown_until = _as_gate_utc(getattr(authority, "cooldown_until", None))
        flow_expires_at = _as_gate_utc(getattr(flow, "expires_at", None))
    if cooldown_until is None or flow_expires_at is None:
        return False
    resend_now = cooldown_until + timedelta(microseconds=1)
    if resend_now >= flow_expires_at:
        return False
    resend_clock = {"now": resend_now}
    with (
        _registration_request_clock_scope(resend_now),
        _registration_resend_clock_scope(resend_clock),
    ):
        resend = _post_signup_resend(app, registered, wire_key)
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
    checks = {
        "registered": registered.status_code == REGISTRATION_ACCEPTED_STATUS,
        "purged_one": counts.get("otp_challenges") == 1,
        "succeeded_after_purge": succeeded_after_purge,
        "registration_preserved": registration_preserved,
        "history_removed": history_removed,
        "replay_stable": replay_stable,
        "resend_status": resend.status_code == 202,
        "succeeded_after_resend": succeeded_after_resend,
        "one_active": len(active) == 1,
        "no_relayable": not relayable,
        "two_acceptances": sender.count == 2,
    }
    if diagnostics is not None:
        diagnostics.update(checks)
    return all(checks.values())


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
        not _post_response_crash_projection_is_exact(crashed, private_handle=handle)
        or handle is None
        or outbox_id is None
    ):
        return False
    window = _open_pending_resend_window(
        factory,
        handle,
        wire_key=wire_key,
    )
    if window is None:
        return False

    relay_sender = _CapturingSender()
    with factory() as session:
        delivered = otp_outbox.run_delivery(
            session,
            otp_outbox.DeliveryIntent(outbox_id=outbox_id),
            relay_sender,
            raise_on_failure=True,
            now=window["operation_now"],
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
        and exact.status_code == REGISTRATION_ACCEPTED_STATUS
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
    diagnostics: dict[str, Any] | None = None,
) -> bool:
    """Prove both terminal orders at the post-provider ledger boundary."""

    from app.core import retention
    from app.models.registration import (
        OtpFlow,
        OtpOutbox,
        RegistrationIdempotencyRecord,
    )
    from app.services import registration_service

    setup_sender = _FailingSender()
    setup_app, factory = _build_app_context(engine, setup_sender)
    payload = _base_registration_payload(sequence)
    wire_key = f"nyay17-finalizer-retention-race-{sequence}"
    setup_response = _post_registration(setup_app, payload, wire_key)
    with factory() as session:
        handle = _durable_registration_handle_for_key(session, wire_key)
        initial_record = _ledger_for_key(session, wire_key)
        initial_outbox = (
            session.get(OtpOutbox, initial_record.outbox_id)
            if initial_record is not None and initial_record.outbox_id is not None
            else None
        )
        record_id = getattr(initial_record, "id", None)
        initial_pending_exact = _ledger_state_exact(initial_record, "pending")
        initial_failed_delivery_exact = _failed_delivery_state_exact(
            initial_outbox, attempts=1
        )
    setup_projection_exact = bool(
        handle is not None
        and _response_handle(setup_response) == handle
        and _signup_pending_projection_is_exact(setup_response, private_handle=handle)
    )
    if (
        not setup_projection_exact
        or handle is None
        or record_id is None
        or not initial_pending_exact
        or not initial_failed_delivery_exact
        or setup_sender.count != 1
    ):
        return False
    window = _open_pending_resend_window(
        factory,
        handle,
        wire_key=wire_key,
    )
    if window is None:
        return False
    clock = {"now": window["operation_now"]}
    bound_flow_boundary_exact = False
    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(
                OtpFlow.registration_id == uuid.UUID(handle),
                OtpFlow.registration_idempotency_record_id == record_id,
                OtpFlow.purpose == "signup",
            )
        )
        flow_expires_at = _as_gate_utc(getattr(flow, "expires_at", None))
        if (
            flow is None
            or flow.state not in {"pending", "code_sent"}
            or flow_expires_at is None
            or flow_expires_at <= clock["now"]
        ):
            return False
        if not finalizer_first:
            # The current NYAY-4 candidate is pending_delivery with a consumed
            # staging marker, so generic challenge retention must preserve it.
            # Expire the bound browser capability to exercise the canonical
            # flow-first fencing and erased-tombstone path instead.
            flow.expires_at = clock["now"] - timedelta(microseconds=1)
            session.commit()
        bound_flow_boundary_exact = True
    _age_signup_challenge(
        factory,
        handle,
        age_days=PENDING_RETENTION_TARGET_AGE_DAYS,
        now=clock["now"],
    )

    sender = _BlockingSender()
    tracker = _PgBackendTracker()
    finalizer_owner = object()
    purge_owner = object()
    key_hash = registration_service.registration_idempotency_key_hash(wire_key)

    def track_backend(owner: object) -> Callable[[Session, Any, Any], None]:
        def track(
            _session: Session,
            _transaction: Any,
            connection: Any,
        ) -> None:
            tracker.record(
                int(connection.scalar(text("SELECT pg_backend_pid()"))),
                owner=owner,
            )

        return track

    def finalize() -> dict[str, Any]:
        with factory() as session:
            listener = track_backend(finalizer_owner)
            event.listen(session, "after_begin", listener)
            try:
                try:
                    registration_service.finalize_pending_registration(
                        session,
                        key_hash,
                        sender,
                        now=clock["now"],
                    )
                except registration_service.RegistrationError as exc:
                    session.rollback()
                    return {
                        "succeeded": False,
                        "status_code": exc.status_code,
                        "error_code": exc.code,
                        "error_field": exc.field,
                    }
                return {
                    "succeeded": True,
                    "status_code": None,
                    "error_code": None,
                    "error_field": None,
                }
            finally:
                event.remove(session, "after_begin", listener)

    def purge() -> dict[str, int]:
        with factory() as session:
            listener = track_backend(purge_owner)
            event.listen(session, "after_begin", listener)
            try:
                counts = retention.purge_expired(
                    session,
                    now=clock["now"],
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
            finally:
                event.remove(session, "after_begin", listener)

    control = factory()
    first_waited = False
    both_waited = False
    provider_entered = False
    claimed_delivery_during_overlap = False
    provider_io_ledger_unlocked = False
    race_backend_count = 0
    finalizer_result: dict[str, Any] = {
        "succeeded": False,
        "status_code": None,
        "error_code": None,
        "error_field": None,
    }
    purge_counts: dict[str, int] = {}
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            if finalizer_first:
                finalizer_future = executor.submit(finalize)
                provider_entered = sender.entered.wait(timeout=15)
                if not provider_entered:
                    sender.release.set()
                    finalizer_future.result(timeout=30)
                    return False
                locked = control.scalar(
                    select(RegistrationIdempotencyRecord)
                    .where(RegistrationIdempotencyRecord.id == record_id)
                    .with_for_update()
                )
                provider_io_ledger_unlocked = locked is not None
                with factory() as session:
                    overlap_record = _ledger_for_key(session, wire_key)
                    overlap_outbox = (
                        session.get(OtpOutbox, overlap_record.outbox_id)
                        if overlap_record is not None
                        and overlap_record.outbox_id is not None
                        else None
                    )
                    claimed_delivery_during_overlap = bool(
                        _ledger_state_exact(overlap_record, "pending")
                        and _claimed_delivery_state_exact(
                            overlap_outbox,
                            attempts=2,
                            expected_last_error="provider_send_failed",
                        )
                    )
                sender.release.set()
                first_waited = _wait_for_request_lock(
                    engine,
                    tracker,
                    expected_backends=1,
                    minimum_waiters=1,
                )
                purge_future = executor.submit(purge)
                both_waited = _wait_for_request_lock(
                    engine,
                    tracker,
                    expected_backends=2,
                    minimum_waiters=2,
                )
            else:
                locked = control.scalar(
                    select(RegistrationIdempotencyRecord)
                    .where(RegistrationIdempotencyRecord.id == record_id)
                    .with_for_update()
                )
                if locked is None:
                    return False
                purge_future = executor.submit(purge)
                first_waited = _wait_for_request_lock(
                    engine,
                    tracker,
                    expected_backends=1,
                    minimum_waiters=1,
                )
                finalizer_future = executor.submit(finalize)
                both_waited = _wait_for_request_lock(
                    engine,
                    tracker,
                    expected_backends=2,
                    minimum_waiters=2,
                )
            race_backend_count = tracker.count
            control.commit()
            if not finalizer_first:
                # A regression that reaches provider I/O must still terminate
                # and turn this exact zero-acceptance oracle red, not hang.
                sender.release.set()
            finalizer_result = finalizer_future.result(timeout=30)
            purge_counts = purge_future.result(timeout=30)
    finally:
        sender.release.set()
        control.rollback()
        control.close()

    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        succeeded_state_exact = _ledger_state_exact(record, "succeeded")
        erased_state_exact = _ledger_state_exact(record, "erased")
        final_state_exact = (
            succeeded_state_exact if finalizer_first else erased_state_exact
        )

    tables = REGISTRATION_GRAPH_TABLES + ("registration_idempotency_records",)
    stable_before = _database_state_digest(engine, tables)
    followup_sender = _CapturingSender()
    followup_app, _ = _build_app_context(engine, followup_sender)
    delivery_before = followup_sender.count
    exact = _post_registration(followup_app, payload, wire_key)
    mismatch = _post_registration(
        followup_app, _canonical_field_mutations(payload)[0], wire_key
    )
    mutation_conflict_exact = bool(
        mismatch.status_code == 409
        and _response_error_code(mismatch) == "idempotency_conflict"
        and _response_error_field(mismatch) == "Idempotency-Key"
    )
    uniform_terminal_signature = bool(
        bytes(exact.content) == bytes(mismatch.content)
        and _safe_response_signature(exact) == _safe_response_signature(mismatch)
    )
    if finalizer_first:
        terminal_projection_exact = bool(
            _signup_pending_projection_is_exact(exact, private_handle=handle)
            and purge_counts.get("otp_challenges") == 1
            and purge_counts.get("registrations") == 0
            and _response_handle(exact) == handle
            and mutation_conflict_exact
        )
    else:
        terminal_projection_exact = bool(
            purge_counts.get("otp_flows") == 1
            and purge_counts.get("otp_challenges") == 0
            and purge_counts.get("registrations") == 1
            and exact.status_code == 409
            and mismatch.status_code == 409
            and _response_error_code(exact)
            == _response_error_code(mismatch)
            == "registration_replay_expired"
            and _response_error_field(exact)
            == _response_error_field(mismatch)
            == "Idempotency-Key"
            and uniform_terminal_signature
            and _response_is_identifier_free(exact, private_handle=handle)
            and _response_is_identifier_free(mismatch, private_handle=handle)
        )
    finalizer_error_exact = bool(
        finalizer_result["succeeded"] is False
        and finalizer_result["status_code"] == 409
        and finalizer_result["error_code"] == "registration_replay_expired"
        and finalizer_result["error_field"] == "Idempotency-Key"
    )
    observation = {
        "setup_projection_exact": setup_projection_exact,
        "initial_pending_exact": initial_pending_exact,
        "initial_failed_delivery_exact": initial_failed_delivery_exact,
        "setup_provider_attempts": setup_sender.count,
        "bound_flow_boundary_exact": bound_flow_boundary_exact,
        "first_waited": first_waited,
        "both_waited": both_waited,
        "backend_count": race_backend_count,
        "provider_entered": provider_entered,
        "claimed_delivery_during_overlap": claimed_delivery_during_overlap,
        "provider_io_ledger_unlocked": provider_io_ledger_unlocked,
        "finalizer_succeeded": finalizer_result["succeeded"],
        "finalizer_error_exact": finalizer_error_exact,
        "expired_flows": purge_counts.get("otp_flows", 0),
        "purged_challenges": purge_counts.get("otp_challenges", 0),
        "registration_transitions": purge_counts.get("registrations", 0),
        "succeeded_state_exact": succeeded_state_exact,
        "erased_state_exact": erased_state_exact,
        "final_state_exact": final_state_exact,
        "exact_replay_status": exact.status_code,
        "private_subject_stable": _response_handle(exact) == handle,
        "mutation_conflict_exact": mutation_conflict_exact,
        "uniform_terminal_signature": uniform_terminal_signature,
        "terminal_projection_exact": terminal_projection_exact,
        "provider_acceptances": sender.count,
        "followup_delivery_delta": followup_sender.count - delivery_before,
        "followup_state_unchanged": (
            _database_state_digest(engine, tables) == stable_before
        ),
    }
    if diagnostics is not None:
        diagnostics.update(observation)
    return _finalizer_retention_race_observation_passes(
        observation, finalizer_first=finalizer_first
    )


def _run_finalizer_retention_races(engine: Engine) -> dict[str, Any]:
    finalizer_first_diagnostics: dict[str, Any] = {}
    retention_first_diagnostics: dict[str, Any] = {}
    finalizer_first = _run_finalizer_retention_race_case(
        engine,
        sequence=232,
        finalizer_first=True,
        diagnostics=finalizer_first_diagnostics,
    )
    retention_first = _run_finalizer_retention_race_case(
        engine,
        sequence=233,
        finalizer_first=False,
        diagnostics=retention_first_diagnostics,
    )
    cases = (finalizer_first, retention_first)
    return {
        "passed": all(cases),
        "cases": len(cases),
        "finalizer_first": finalizer_first,
        "retention_first": retention_first,
        "finalizer_first_diagnostics": finalizer_first_diagnostics,
        "retention_first_diagnostics": retention_first_diagnostics,
    }


def _run_retention_purge_probes(engine: Engine) -> dict[str, Any]:
    pending_anonymise = _run_pending_retention_purge_case(
        engine, sequence=227, mode="anonymise"
    )
    pending_delete = _run_pending_retention_purge_case(
        engine, sequence=230, mode="delete"
    )
    succeeded_diagnostics: dict[str, bool] = {}
    succeeded = _run_succeeded_retention_purge_probe(
        engine, diagnostics=succeeded_diagnostics
    )
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
        "pending_anonymise_passed": pending_anonymise["passed"],
        "pending_delete_passed": pending_delete["passed"],
        "succeeded_passed": succeeded,
        "pending_sent_passed": pending_sent,
        "races_passed": races["passed"],
        "pending_anonymise_diagnostics": pending_anonymise.get("diagnostics", {}),
        "pending_delete_diagnostics": pending_delete.get("diagnostics", {}),
        "succeeded_diagnostics": succeeded_diagnostics,
        "race_finalizer_first": races["finalizer_first"],
        "race_retention_first": races["retention_first"],
        "race_finalizer_first_diagnostics": races["finalizer_first_diagnostics"],
        "race_retention_first_diagnostics": races["retention_first_diagnostics"],
    }


def _run_failed_delivery_probe(engine: Engine) -> dict[str, Any]:
    from app.models.registration import OtpOutbox

    ledger_table = ("registration_idempotency_records",)
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    sender = _FailingSender()
    app, factory = _build_app_context(engine, sender)
    payload = _base_registration_payload(231)
    wire_key = "nyay17-failed-delivery"
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    clock = {"now": datetime.now(timezone.utc)}
    with _registration_finalizer_clock_scope(clock):
        first = _post_registration(app, payload, wire_key)
    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        pending_exact = _ledger_state_exact(record, "pending")
        private_handle = (
            str(record.registration_id)
            if record is not None and record.registration_id is not None
            else None
        )
        outbox_id = record.outbox_id if record is not None else None
        failed_row = (
            session.get(OtpOutbox, outbox_id) if outbox_id is not None else None
        )
        failed_exact = _failed_delivery_state_exact(failed_row)
        retry_at = _as_gate_utc(getattr(failed_row, "next_attempt_at", None))
        provider_key = getattr(failed_row, "provider_idempotency_key", None)
    first_state = _database_state_digest(engine, all_tables)
    first_delivery = sender.count
    if retry_at is not None:
        clock["now"] = retry_at - timedelta(microseconds=1)
    with _registration_finalizer_clock_scope(clock):
        replay = _post_registration(app, payload, wire_key)
    replay_state = _database_state_digest(engine, all_tables)
    replay_delivery = sender.count
    replay_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    replay_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with _registration_finalizer_clock_scope(clock):
        mismatch = _post_registration(
            app, _canonical_field_mutations(payload)[0], wire_key
        )
    mismatch_state = _database_state_digest(engine, all_tables)

    recovery_sender = _CapturingSender()
    recovery_app, _ = _build_app_context(engine, recovery_sender)
    recovery_graph_before = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    if retry_at is not None:
        clock["now"] = retry_at + timedelta(seconds=1)
    with _registration_finalizer_clock_scope(clock):
        recovery = _post_registration(recovery_app, payload, wire_key)
    recovery_graph_after = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    with factory() as session:
        succeeded_exact = _ledger_state_exact(
            _ledger_for_key(session, wire_key), "succeeded"
        )
        sent_row = session.get(OtpOutbox, outbox_id) if outbox_id is not None else None
        sent_exact = _sent_delivery_state_exact(sent_row)
        stable_provider_key = bool(
            _lower_hex_64(provider_key)
            and getattr(sent_row, "provider_idempotency_key", None) == provider_key
        )
    final_state = _database_state_digest(engine, all_tables)
    final_delivery = recovery_sender.count
    with _registration_finalizer_clock_scope(clock):
        final_replay = _post_registration(recovery_app, payload, wire_key)
    final_replay_stable = bool(
        final_replay.status_code == REGISTRATION_ACCEPTED_STATUS
        and _response_handle(final_replay) == private_handle
        and recovery_sender.count == final_delivery
        and _database_state_digest(engine, all_tables) == final_state
    )
    observation = {
        "first_status": first.status_code,
        "first_projection_exact": _signup_pending_projection_is_exact(
            first, private_handle=_response_handle(first)
        ),
        "replay_status": replay.status_code,
        "replay_projection_exact": _signup_pending_projection_is_exact(
            replay, private_handle=_response_handle(replay)
        ),
        "public_handles_absent": bool(
            _response_is_identifier_free(first, private_handle=private_handle)
            and _response_is_identifier_free(replay, private_handle=private_handle)
            and _response_is_identifier_free(mismatch, private_handle=private_handle)
            and _response_is_identifier_free(recovery, private_handle=private_handle)
            and _response_is_identifier_free(
                final_replay, private_handle=private_handle
            )
        ),
        "private_subject_stable": bool(
            private_handle is not None
            and _response_handle(first)
            == _response_handle(replay)
            == _response_handle(recovery)
            == _response_handle(final_replay)
            == private_handle
        ),
        "pending_state_exact": pending_exact,
        "failed_delivery_exact": failed_exact,
        "ledger_delta": after_ledger - before_ledger,
        "graph_delta": _count_delta(before_graph, after_graph),
        "replay_ledger_delta": replay_ledger - after_ledger,
        "replay_delivery_delta": replay_delivery - first_delivery,
        "replay_graph_delta_zero": _zero_deltas(
            _count_delta(after_graph, replay_graph)
        ),
        "replay_state_unchanged": replay_state == first_state,
        "mismatch_conflict_exact": bool(
            mismatch.status_code == 409
            and _response_error_code(mismatch) == "idempotency_conflict"
            and _response_error_field(mismatch) == "Idempotency-Key"
        ),
        "mismatch_state_unchanged": mismatch_state == replay_state,
        "recovery_status": recovery.status_code,
        "stable_provider_key": stable_provider_key,
        "succeeded_state_exact": succeeded_exact,
        "sent_delivery_exact": sent_exact,
        "recovery_provider_acceptances": recovery_sender.count,
        "recovery_graph_delta_zero": _zero_deltas(
            _count_delta(recovery_graph_before, recovery_graph_after)
        ),
        "final_replay_stable": final_replay_stable,
    }
    return {
        "passed": _failure_replay_observation_passes(observation),
        "initial_failure_exact": bool(
            observation["first_status"] == REGISTRATION_ACCEPTED_STATUS
            and observation["first_projection_exact"]
            and observation["pending_state_exact"]
            and observation["failed_delivery_exact"]
        ),
        "stable_replay_exact": bool(
            observation["replay_status"] == REGISTRATION_ACCEPTED_STATUS
            and observation["replay_projection_exact"]
            and observation["replay_ledger_delta"] == 0
            and observation["replay_delivery_delta"] == 0
            and observation["replay_graph_delta_zero"]
            and observation["replay_state_unchanged"]
        ),
        "mismatch_exact": bool(
            observation["mismatch_conflict_exact"]
            and observation["mismatch_state_unchanged"]
        ),
        "recovery_exact": bool(
            observation["recovery_status"] == REGISTRATION_ACCEPTED_STATUS
            and observation["public_handles_absent"]
            and observation["private_subject_stable"]
            and observation["stable_provider_key"]
            and observation["succeeded_state_exact"]
            and observation["sent_delivery_exact"]
            and observation["recovery_provider_acceptances"] == 1
            and observation["recovery_graph_delta_zero"]
            and observation["final_replay_stable"]
        ),
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
        record = _ledger_for_key(session, wire_key)
        succeeded = _ledger_state_exact(record, "succeeded")
        private_winner = (
            str(record.registration_id)
            if record is not None and record.registration_id is not None
            else None
        )
    stable_before = _database_state_digest(engine, all_tables)
    delivery_before = sender.count
    exact_followup = _post_registration(app, payload, wire_key)
    conflict_followup = _post_registration(
        app, _canonical_field_mutations(payload)[0], wire_key
    )
    stable_followups = bool(
        exact_followup.status_code == REGISTRATION_ACCEPTED_STATUS
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
        "public_handles_absent": bool(
            all(
                _response_is_identifier_free(response, private_handle=private_winner)
                for response in [*responses, exact_followup, conflict_followup]
            )
        ),
        "private_winner_exact": bool(
            private_winner is not None and handles == {private_winner}
        ),
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
    from app.models.registration import RegistrationIdempotencyRecord
    from app.services.registration_service import registration_idempotency_key_hash

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
    loser = None
    provider_overlap_completed = False
    winner_blocked = False
    with ThreadPoolExecutor(max_workers=2) as executor:
        winner_future = executor.submit(
            _post_registration, app, winner_payload, wire_key
        )
        if not sender.entered.wait(timeout=15):
            sender.release.set()
            return False
        loser_future = executor.submit(_post_registration, app, loser_payload, wire_key)
        try:
            loser = loser_future.result(timeout=5)
            provider_overlap_completed = True
        except TimeoutError:
            provider_overlap_completed = False
        winner_blocked = not winner_future.done()
        sender.release.set()
        winner = winner_future.result(timeout=30)
        if loser is None:
            loser = loser_future.result(timeout=30)
    backend_count = tracker.count
    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        succeeded = _ledger_state_exact(record, "succeeded")
        private_winner = (
            str(record.registration_id)
            if record is not None and record.registration_id is not None
            else None
        )

    # Provider I/O and ledger serialization are distinct contracts. Prove the
    # latter directly after the winner is terminal, without forming a
    # provider/ledger/authority lock cycle.
    ledger_tracker = _PgBackendTracker()
    ledger_app, _ = _build_app_context(engine, sender, backend_tracker=ledger_tracker)
    control = factory()
    ledger_waited = False
    ledger_wait_response = None
    ledger_phase_before = _database_state_digest(engine, all_tables)
    ledger_phase_delivery = sender.count
    try:
        locked = control.scalar(
            select(RegistrationIdempotencyRecord)
            .where(
                RegistrationIdempotencyRecord.idempotency_key_hash
                == registration_idempotency_key_hash(wire_key)
            )
            .with_for_update()
        )
        if locked is None:
            return False
        with ThreadPoolExecutor(max_workers=1) as executor:
            ledger_future = executor.submit(
                _post_registration, ledger_app, loser_payload, wire_key
            )
            ledger_waited = _wait_for_request_lock(
                engine,
                ledger_tracker,
                expected_backends=1,
                minimum_waiters=1,
            )
            control.commit()
            ledger_wait_response = ledger_future.result(timeout=30)
    finally:
        control.rollback()
        control.close()
    ledger_phase_stable = bool(
        ledger_wait_response is not None
        and ledger_wait_response.status_code == 409
        and _response_error_code(ledger_wait_response) == "idempotency_conflict"
        and _response_error_field(ledger_wait_response) == "Idempotency-Key"
        and sender.count == ledger_phase_delivery
        and _database_state_digest(engine, all_tables) == ledger_phase_before
    )

    stable_before = _database_state_digest(engine, all_tables)
    delivery_before = sender.count
    winner_replay = _post_registration(app, winner_payload, wire_key)
    loser_replay = _post_registration(app, loser_payload, wire_key)
    stable = bool(
        winner_replay.status_code == REGISTRATION_ACCEPTED_STATUS
        and _response_handle(winner_replay) == _response_handle(winner)
        and loser_replay.status_code == 409
        and _response_error_code(loser_replay) == "idempotency_conflict"
        and _response_error_field(loser_replay) == "Idempotency-Key"
        and sender.count == delivery_before
        and _database_state_digest(engine, all_tables) == stable_before
        and ledger_phase_stable
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
        "public_handles_absent": bool(
            all(
                _response_is_identifier_free(response, private_handle=private_winner)
                for response in (
                    winner,
                    loser,
                    ledger_wait_response,
                    winner_replay,
                    loser_replay,
                )
            )
        ),
        "private_winner_exact": bool(
            private_winner is not None
            and _response_handle(winner) == private_winner
            and _response_handle(loser) is None
            and _response_handle(ledger_wait_response) is None
            and _response_handle(winner_replay) == private_winner
            and _response_handle(loser_replay) is None
        ),
        "graph_delta": _count_delta(before_graph, after_graph),
        "ledger_delta": after_ledger - before_ledger,
        "delivery_delta": sender.count,
        "backend_count": backend_count,
        "provider_overlap_completed_before_release": provider_overlap_completed,
        "winner_blocked_before_release": winner_blocked,
        "ledger_lock_wait_observed": ledger_waited,
        "ledger_wait_backend_count": ledger_tracker.count,
        "deadlock_free": bool(
            winner.status_code == REGISTRATION_ACCEPTED_STATUS
            and loser.status_code == 409
            and ledger_phase_stable
        ),
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
    from app.models.registration import OtpOutbox

    ledger_table = ("registration_idempotency_records",)
    all_tables = REGISTRATION_GRAPH_TABLES + ledger_table
    sender = _BlockingSender(fail=True)
    tracker = _PgBackendTracker()
    app, factory = _build_app_context(engine, sender, backend_tracker=tracker)
    payload = _base_registration_payload(321)
    wire_key = "nyay17-failed-waiter"
    before_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    before_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    clock = {"now": datetime.now(timezone.utc)}
    waiter = None
    winner = None
    peer_completed_before_release = False
    winner_blocked_before_release = False
    pending_during_overlap = False
    claimed_during_overlap = False
    with _registration_finalizer_clock_scope(clock):
        with ThreadPoolExecutor(max_workers=2) as executor:
            winner_future = executor.submit(_post_registration, app, payload, wire_key)
            if not sender.entered.wait(timeout=15):
                sender.release.set()
                return {"passed": False}
            with factory() as session:
                overlap_record = _ledger_for_key(session, wire_key)
                overlap_outbox_id = (
                    overlap_record.outbox_id if overlap_record is not None else None
                )
                overlap_row = (
                    session.get(OtpOutbox, overlap_outbox_id)
                    if overlap_outbox_id is not None
                    else None
                )
                pending_during_overlap = _ledger_state_exact(overlap_record, "pending")
                claimed_during_overlap = _claimed_delivery_state_exact(overlap_row)
            waiter_future = executor.submit(_post_registration, app, payload, wire_key)
            try:
                waiter = waiter_future.result(timeout=5)
                peer_completed_before_release = True
            except TimeoutError:
                peer_completed_before_release = False
            winner_blocked_before_release = not winner_future.done()
            sender.release.set()
            winner = winner_future.result(timeout=30)
            if waiter is None:
                waiter = waiter_future.result(timeout=30)
    backend_count = tracker.count
    after_graph = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    after_ledger = _table_counts(factory, ledger_table)[ledger_table[0]]
    with factory() as session:
        record = _ledger_for_key(session, wire_key)
        pending_exact = _ledger_state_exact(record, "pending")
        private_handle = (
            str(record.registration_id)
            if record is not None and record.registration_id is not None
            else None
        )
        outbox_id = record.outbox_id if record is not None else None
        failed_row = (
            session.get(OtpOutbox, outbox_id) if outbox_id is not None else None
        )
        failed_exact = _failed_delivery_state_exact(failed_row)
        retry_at = _as_gate_utc(getattr(failed_row, "next_attempt_at", None))
        provider_key = getattr(failed_row, "provider_idempotency_key", None)
    stable_before = _database_state_digest(engine, all_tables)
    delivery_before = sender.count
    with _registration_finalizer_clock_scope(clock):
        exact_replay = _post_registration(app, payload, wire_key)
    stable = bool(
        exact_replay.status_code == REGISTRATION_ACCEPTED_STATUS
        and _signup_pending_projection_is_exact(
            exact_replay, private_handle=_response_handle(exact_replay)
        )
        and sender.count == delivery_before
        and _database_state_digest(engine, all_tables) == stable_before
    )
    with _registration_finalizer_clock_scope(clock):
        mismatch = _post_registration(
            app, _canonical_field_mutations(payload)[0], wire_key
        )
    mismatch_conflict = bool(
        mismatch.status_code == 409
        and _response_error_code(mismatch) == "idempotency_conflict"
        and _response_error_field(mismatch) == "Idempotency-Key"
    )

    recovery_sender = _CapturingSender()
    recovery_app, _ = _build_app_context(engine, recovery_sender)
    recovery_graph_before = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    if retry_at is not None:
        clock["now"] = retry_at + timedelta(seconds=1)
    with _registration_finalizer_clock_scope(clock):
        recovery = _post_registration(recovery_app, payload, wire_key)
    recovery_graph_after = _table_counts(factory, REGISTRATION_GRAPH_TABLES)
    with factory() as session:
        succeeded_exact = _ledger_state_exact(
            _ledger_for_key(session, wire_key), "succeeded"
        )
        sent_row = session.get(OtpOutbox, outbox_id) if outbox_id is not None else None
        sent_exact = _sent_delivery_state_exact(sent_row)
        stable_provider_key = bool(
            _lower_hex_64(provider_key)
            and getattr(sent_row, "provider_idempotency_key", None) == provider_key
        )
    final_state = _database_state_digest(engine, all_tables)
    final_delivery = recovery_sender.count
    with _registration_finalizer_clock_scope(clock):
        final_replay = _post_registration(recovery_app, payload, wire_key)
    final_replay_stable = bool(
        final_replay.status_code == REGISTRATION_ACCEPTED_STATUS
        and _response_handle(final_replay) == private_handle
        and recovery_sender.count == final_delivery
        and _database_state_digest(engine, all_tables) == final_state
    )
    observation = {
        "statuses": [winner.status_code, waiter.status_code],
        "projections_exact": bool(
            _signup_pending_projection_is_exact(
                winner, private_handle=_response_handle(winner)
            )
            and _signup_pending_projection_is_exact(
                waiter, private_handle=_response_handle(waiter)
            )
        ),
        "public_handles_absent": bool(
            all(
                _response_is_identifier_free(response, private_handle=private_handle)
                for response in (
                    winner,
                    waiter,
                    exact_replay,
                    mismatch,
                    recovery,
                    final_replay,
                )
            )
        ),
        "private_subject_stable": bool(
            private_handle is not None
            and all(
                _response_handle(response) == private_handle
                for response in (
                    winner,
                    waiter,
                    exact_replay,
                    recovery,
                    final_replay,
                )
            )
            and _response_handle(mismatch) is None
        ),
        "peer_completed_before_release": peer_completed_before_release,
        "winner_blocked_before_release": winner_blocked_before_release,
        "pending_state_during_overlap": pending_during_overlap,
        "claimed_delivery_during_overlap": claimed_during_overlap,
        "pending_state_exact": pending_exact,
        "failed_delivery_exact": failed_exact,
        "ledger_delta": after_ledger - before_ledger,
        "graph_delta": _count_delta(before_graph, after_graph),
        "provider_attempt_delta": sender.count,
        "backend_count": backend_count,
        "stable_failure_replay": stable,
        "mismatch_conflict": mismatch_conflict,
        "recovery_status": recovery.status_code,
        "stable_provider_key": stable_provider_key,
        "succeeded_state_exact": succeeded_exact,
        "sent_delivery_exact": sent_exact,
        "recovery_provider_acceptances": recovery_sender.count,
        "recovery_graph_delta_zero": _zero_deltas(
            _count_delta(recovery_graph_before, recovery_graph_after)
        ),
        "final_replay_stable": final_replay_stable,
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
    probe_now = datetime.now(timezone.utc)
    with factory() as session:
        setup_record = _ledger_for_key(session, wire_key)
        private_winner_id = (
            setup_record.registration_id if setup_record is not None else None
        )
    identifier_free_setup_exact = bool(
        created.status_code == REGISTRATION_ACCEPTED_STATUS
        and _public_response_handle(created) is None
        and private_winner_id is not None
    )
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
                now=probe_now,
            )
            exact_results.append(
                recovered.registration.id == private_winner_id
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
                now=probe_now,
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
                now=probe_now,
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
                    session, payload, wire_key, expected, now=probe_now
                )
            except IntegrityError as caught:
                unknown_rethrown = unknown_rethrown and caught is expected
            else:
                unknown_rethrown = False

    # Deterministically mutate the product fingerprint comparison seam. A
    # changed request then false-replays as accepted, which the typed-conflict
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
        bypassed.status_code == REGISTRATION_ACCEPTED_STATUS
        and not _conflict_observation_passes(bypass_observation)
    )
    return {
        "passed": bool(
            identifier_free_setup_exact
            and all(exact_results)
            and mobile_typed
            and mismatch_typed
            and unknown_rethrown
            and fingerprint_bypass_killed
        ),
        "cases": len(exact_results) + 1 + 1 + 3 + 1,
        "product_seam_mutants_killed": int(fingerprint_bypass_killed),
    }


@contextmanager
def _behavior_rate_limit_scope() -> Iterator[None]:
    """Prevent later-ticket abuse budgets from coupling independent probes."""

    from app.core.config import settings

    fields = (
        "otp_issue_identity_limit",
        "otp_issue_ip_limit",
        "otp_issue_global_limit",
    )
    original = tuple(getattr(settings, field) for field in fields)
    try:
        for field, value in zip(fields, (100, 1000, 10000), strict=True):
            setattr(settings, field, value)
        yield
    finally:
        for field, value in zip(fields, original, strict=True):
            setattr(settings, field, value)


@contextmanager
def _behavior_process_scope() -> Iterator[None]:
    """Install and exactly restore the gate's process-global authorities."""

    from app.core import crypto
    from app.core.config import settings
    from app.core.crypto import KeyRing, override_keyring

    previous_env = settings.app_env
    previous_keyring = crypto._override
    try:
        settings.app_env = "testing"
        override_keyring(
            KeyRing(
                active_version="v1",
                secrets={"v1": b"nyay17-postgres-gate-encryption-v1"},
                lookup_secret=b"nyay17-postgres-gate-stable-lookup-v1",
            )
        )
        yield
    finally:
        override_keyring(previous_keyring)
        settings.app_env = previous_env


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
        schema_exact = _migration_inventory_passes(
            engine, expected_revision=APPLICATION_HEAD
        )
        if not schema_exact:
            raise ProductGateFailure("0018 ledger schema inventory drifted")

        with _behavior_process_scope():
            with _behavior_rate_limit_scope():
                sequential = _run_sequential_probes(engine)
                neutralized = _run_neutralized_ledger_probe(engine)
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
            "neutralized": neutralized,
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
    neutralized = behavior["neutralized"]
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
            and neutralized["passed"]
            and activation["retired_exact"]
            and retention["passed"]
            and pending["passed"]
            and pending_resend["passed"]
            and retention_purge["passed"]
            and failed["passed"]
        ),
        "state_links_exact": bool(
            neutralized["passed"]
            and activation["retired_exact"]
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
            states_checked=6,
            schema_checked=True,
            neutralized_probe=neutralized["passed"],
            activation_probe=activation["retired_exact"],
            pending_probe=pending["passed"],
            pending_resend_probe=pending_resend["passed"],
            retention_purge_probe=retention_purge["passed"],
            failed_probe=failed["passed"],
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
            cases_checked=sequential["legacy_cases"],
        ),
        _assertion(
            "CONTRACT-ACTIVATION-RETIRES-REPLAY-UNIFORM",
            activation["verification_status"] == 200
            and activation["verification_body_exact"]
            and activation["retired_exact"]
            and activation["lifecycle_advanced"]
            and activation["activation_then_retention_preserves_retired"]
            and activation_retention_race["passed"]
            and _retired_observation_passes(activation["terminal"]),
            cases_checked=3 + activation_retention_race["cases"],
            verification_exact=activation["verification_status"] == 200,
            verification_body_exact=activation["verification_body_exact"],
            retired_exact=activation["retired_exact"],
            lifecycle_exact=activation["lifecycle_advanced"],
            post_retention_exact=activation[
                "activation_then_retention_preserves_retired"
            ],
            race_exact=activation_retention_race["passed"],
            race_wait_one=activation_retention_race.get("activation_waited", False),
            race_wait_two=activation_retention_race.get("both_waited", False),
            race_backend_exact=activation_retention_race.get("backend_exact", False),
            race_activation_status=activation_retention_race.get(
                "activation_status_exact", False
            ),
            race_activation_body=activation_retention_race.get(
                "activation_body_exact", False
            ),
            race_retention_completed=activation_retention_race.get(
                "retention_completed", False
            ),
            race_retired_preserved=activation_retention_race.get(
                "retired_preserved", False
            ),
            race_row_erased=activation_retention_race.get("row_erased", False),
            race_terminal=activation_retention_race.get("terminal_passed", False),
            race_sender_exact=activation_retention_race.get("sender_exact", False),
            race_retention_wins=activation_retention_race.get("retention_wins", False),
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
            pending_probe=pending["passed"],
            crash_setup_exact=pending.get("crash_setup_exact", False),
            mismatch_exact=pending.get("mismatch_exact", False),
            immediate_replay_exact=pending.get("immediate_replay_exact", False),
            recovery_exact=pending.get("recovery_exact", False),
            resend_probe=pending_resend["passed"],
            resend_ordinary=pending_resend.get("ordinary_passed", False),
            resend_concurrent=pending_resend.get("concurrent_passed", False),
            resend_pre_relay=pending_resend.get("pre_relay_passed", False),
            resend_crosslink=pending_resend.get("crosslink_passed", False),
            resend_helper_waits=pending_resend.get("helper_waits_passed", False),
            resend_ordinary_checks=pending_resend.get("ordinary_diagnostics", {}),
            resend_concurrent_checks=pending_resend.get("concurrent_diagnostics", {}),
            resend_pre_relay_checks=pending_resend.get("pre_relay_diagnostics", {}),
        ),
        _assertion(
            "CONTRACT-FAILED-DELIVERY-REPLAY-STABLE",
            failed["passed"] and retention_purge["passed"],
            cases_checked=1 + retention_purge["cases"],
            failed_probe=failed["passed"],
            failure_initial=failed.get("initial_failure_exact", False),
            failure_replay=failed.get("stable_replay_exact", False),
            failure_mismatch=failed.get("mismatch_exact", False),
            failure_recovery=failed.get("recovery_exact", False),
            retention_probe=retention_purge["passed"],
            retention_anonymise=retention_purge.get("pending_anonymise_passed", False),
            retention_delete=retention_purge.get("pending_delete_passed", False),
            retention_succeeded=retention_purge.get("succeeded_passed", False),
            retention_pending_sent=retention_purge.get("pending_sent_passed", False),
            retention_races=retention_purge.get("races_passed", False),
            retention_anonymise_checks=retention_purge.get(
                "pending_anonymise_diagnostics", {}
            ),
            retention_delete_checks=retention_purge.get(
                "pending_delete_diagnostics", {}
            ),
            retention_succeeded_checks=retention_purge.get("succeeded_diagnostics", {}),
            retention_finalizer_first=retention_purge.get(
                "race_finalizer_first", False
            ),
            retention_retention_first=retention_purge.get(
                "race_retention_first", False
            ),
            retention_finalizer_first_checks=retention_purge.get(
                "race_finalizer_first_diagnostics", {}
            ),
            retention_retention_first_checks=retention_purge.get(
                "race_retention_first_diagnostics", {}
            ),
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
