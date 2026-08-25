"""NYAY-19 PostgreSQL 16 authentication-retention release gate.

The ordinary unit suite cannot prove PostgreSQL row-lock ordering, concurrent
session revocation, cutoff semantics, or transactional rollback.  This opt-in
gate owns disposable loopback databases and emits aggregate evidence only.

The product-facing behavior adapter is bound to the frozen 0020 service/API
seams.  Migration, schema, HTTP, retention and concurrency evidence is kept
private; only fixed aggregate verdicts leave the gate.

Exit codes:

* 0: every exact oracle, seeded mutant, privacy scan and cleanup passed;
* 1: product, migration, harness, privacy or cleanup evidence failed;
* 78: the explicit PostgreSQL 16 + pgvector prerequisite was unavailable.
"""

from __future__ import annotations

import argparse
import ast
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
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import (
    DateTime,
    JSON,
    String,
    Uuid,
    bindparam,
    create_engine,
    func,
    inspect,
    make_url,
    select,
    text,
)
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

BLOCKED_EXIT = 78
PREVIOUS_REVISION = "0019_otp_security_authority"
PINNED_HEAD = "0020_auth_retention_lifecycle"
PINNED_HEAD_FILENAME = "0020_auth_retention_lifecycle.py"
PINNED_HEAD_SHA256 = "8b462f0d35839a0edd7166f4e5881fafaeb368f8816cba673144d3c745270dbe"
APPLICATION_HEAD = "0021_nyay5_profile_boundary"
APPLICATION_HEAD_FILENAME = "0021_nyay5_profile_boundary.py"
APPLICATION_HEAD_SHA256 = (
    "439de03dc431a73264db706f77ffb703541619db1f490760d6d685aa173c7c50"
)
OPT_IN_ENV = "NYAY19_POSTGRES_GATE_EXECUTE"

POST_LEDGER_HISTORICAL_SHA256 = {
    "0016_dob_hash_reconcile.py": (
        "b483bad2e23abbd0087856b06cc53fb54021baa2a397c295f3021caf1da0cef6"
    ),
    "0017_registration_invariants.py": (
        "f7b0420779699ceb555ad9ce35016cc8ce7fed9042fe23c44234d6b5eefd03a5"
    ),
    "0018_registration_idempotency.py": (
        "5678a9b2117c5e0397a40052731563e4b5b09664f73f9874b3239c235bb7a862"
    ),
    "0019_otp_security_authority.py": (
        "3513d5400295fb424a6b84e3325286a45c8c57192d5ef91f98ce884d691062d4"
    ),
}

# Static filename+digest authority for every historical revision.  The JSON
# ledger is itself cross-checked against the first fifteen entries, but is not
# trusted as the only filename inventory: an added/missing alternate revision
# at or below 0019 must fail even when every listed file still hashes correctly.
HISTORICAL_MIGRATION_SHA256 = {
    "0001_initial_pgvector.py": (
        "0fcdb6c94a2f31023b262aa7aa1720c9503ad6cf587fadb7c34c74dbda8ed3b6"
    ),
    "0002_registration_schema.py": (
        "7af72ddf1f2fb0b62c6cdee96118f0611ad7651747a1345838182d5e4b3bbaec"
    ),
    "0003_registration_security_lifecycle.py": (
        "78b9c4b615e22ab16ea117f276b1c6650d824ddf79a93e152ef61fdfd4b43546"
    ),
    "0004_wave1_foundation.py": (
        "385bb1379543a6218642c6ef6f7edf61721a16ce5472a218008d562a39a908e5"
    ),
    "0005_language_check.py": (
        "40aade919fbe7ea2e9d03901be6969e8ef2799203408f27e6ede1473811fb85f"
    ),
    "0006_lawschool_fact_backfill.py": (
        "a2df7ac37926b10f24a7c621715de2cf4e10a2c1a3deb7af34a95ccd5698764a"
    ),
    "0007_wave3_credentials.py": (
        "da63e6166fb0c1d5598c94e22477cb76903b939c7997996827643c2725c267a8"
    ),
    "0008_wave2_tutoring.py": (
        "fff836ccc283f267568def3c2e5f6962bdda1b4f3e016a1aad77933dfa2c50a8"
    ),
    "0009_wave2_session_pricing.py": (
        "6c6bf34dfe78bc45b82eb3a2418450c0e61e48acf09fb21c42503cd2b308ceb0"
    ),
    "0010_student_login_session.py": (
        "cbc4cc7e41106eebc79f5cc0cf81a0c4a2b4901a9da55e33fba1e158916cbed6"
    ),
    "0011_wave4_private_reporting.py": (
        "4feee798862880a5c49d2d188706c7724a7f0f367e26a6e5ed203731a2ea5774"
    ),
    "0012_wave4_moderation.py": (
        "aea2c15c9858c6ea5f2823a9092b3f586f5f8974cdfa603d8e72338433423dbc"
    ),
    "0013_wave5_calendar_interop.py": (
        "8a9f60b367eeeed423dd37eeb9e91b6602c07ccca3259354a2ba54b6542e9b30"
    ),
    "0014_saathi60_internships.py": (
        "3fe141f2b45e16d21377d25e7ca99f0015580110c4f2c6fb04d252167718bc14"
    ),
    "0015_wave4_public_risk_labels.py": (
        "5b8c01093d062c7281029514ba27c075f0a4f898fb0d078f9dab02243d4f4c6f"
    ),
    **POST_LEDGER_HISTORICAL_SHA256,
}

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

# Exact order is part of the release contract.  No additional green row may
# substitute for a missing control, and a reordering is a failing inventory.
REQUIRED_ASSERTION_IDS = (
    "RUNTIME-POSTGRES-16-PGVECTOR",
    "MIGRATION-0019-0020-LIFECYCLE-IMMUTABLE",
    "MIGRATION-POPULATED-BACKFILL-DOWNGRADE-REFUSAL",
    "SCHEMA-AUTH-RETENTION-EXACT",
    "CONFIG-COUNSEL-WINDOWS-FAIL-CLOSED",
    "CONTRACT-LOGOUT-EXPIRY-REVOKE-COOKIE",
    "CONTRACT-ROTATION-OLD-COOKIE-REPLAY-DENIED",
    "CONTRACT-LOGIN-ATTEMPT-REAL-DECOY-RETENTION",
    "CONTRACT-AUTH-SESSION-ANONYMISE-CUTOFF-NOOP-ROLLBACK",
    "CONTRACT-AUTH-SESSION-DELETE-CUTOFF-NOOP-ROLLBACK",
    "CONTRACT-REGISTRATION-ANONYMISE-REVOKES-TOMBSTONES",
    "CONTRACT-REGISTRATION-DELETE-REVOKES-REMOVES",
    "CONTRACT-PRIVACY-DELETE-FREEZES-LEGACY-BACKFILL",
    "CONCURRENCY-AUTH-LIFECYCLE-SERIALIZED",
    "CONTRACT-AUDIT-AGGREGATE-PRIVACY",
    "HARNESS-MUTANTS-PRIVACY-SCRATCH-CLEANUP",
)

REQUIRED_RACE_CASES = (
    "rotation_vs_logout",
    "rotation_vs_anonymise",
    "rotation_vs_delete",
    "privacy_delete_vs_verify_session_mint",
    "expiry_vs_session_resolve",
    "attempt_retention_vs_verify",
    "logout_vs_verify",
    "registration_anonymise_vs_retention_worker",
    "registration_delete_vs_retention_worker",
)
REGISTRATION_RETENTION_RACE_CASES = frozenset(REQUIRED_RACE_CASES[-2:])

REQUIRED_MUTANT_IDS = (
    "ACCEPT-POSTGRES-15",
    "ACCEPT-MISSING-PGVECTOR",
    "REWRITE-HISTORICAL-MIGRATION",
    "HISTORICAL-INVENTORY-MISSING",
    "HISTORICAL-INVENTORY-EXTRA",
    "SKIP-POST-DDL-EXACT-HEAD-VALIDATION",
    "POST-DDL-VALIDATION-FAILURE-PERSISTS",
    "SKIP-POPULATED-BACKFILL",
    "ALLOW-ERASED-DOWNGRADE",
    "COUPLE-ERASED-REFUSAL-TO-LEGACY-MARKER",
    "ACCEPT-CORRUPT-LEGACY-DELETION-TARGET",
    "ACCEPT-MISSING-LEGACY-DELETION-JOB",
    "OMIT-LEGACY-DOWNGRADE-MARKER",
    "MUTATE-APPEND-ONLY-AUDIT-EVENTS",
    "RELAX-SESSION-USER-NULLABILITY",
    "NULLABLE-LOGIN-LOOKUP",
    "NULLABLE-SESSION-TOKEN",
    "AUTH-COLUMN-WRONG-TYPE",
    "AUTH-COLUMN-WRONG-LENGTH",
    "AUTH-COLUMN-WRONG-DEFAULT",
    "AUTH-COLUMN-WRONG-TIMEZONE",
    "AUTH-PK-DRIFT",
    "AUTH-PK-CATALOG-DEFERRABLE",
    "AUTH-PK-CATALOG-NO-INHERIT-FALSE",
    "AUTH-UQ-CATALOG-NO-INHERIT-FALSE",
    "AUTH-PK-INCLUDE-DRIFT",
    "AUTH-FK-DRIFT",
    "AUTH-FK-OPTIONS-DRIFT",
    "AUTH-FK-CATALOG-NOT-VALID",
    "AUTH-FK-CATALOG-NO-INHERIT-FALSE",
    "DUPLICATE-NAMED-FK-PRECEDES-EXPECTED",
    "AUTH-CHECK-SQL-DRIFT",
    "AUTH-CHECK-NOT-VALID",
    "AUTH-CHECK-NO-INHERIT",
    "DUPLICATE-NAMED-CHECK-PRECEDES-EXPECTED",
    "AUTH-UQ-DRIFT",
    "AUTH-UQ-BACKING-INDEX-MISSING",
    "AUTH-UQ-BACKING-INDEX-EXTRA",
    "AUTH-UQ-BACKING-INDEX-NAME-DRIFT",
    "AUTH-UQ-BACKING-INDEX-DUPLICATE-LINK-DRIFT",
    "AUTH-UQ-BACKING-INDEX-COLUMNS-DRIFT",
    "AUTH-UQ-BACKING-INDEX-UNIQUENESS-DRIFT",
    "AUTH-UQ-BACKING-INDEX-PREDICATE-DRIFT",
    "AUTH-UQ-BACKING-INDEX-INCLUDE-DRIFT",
    "AUTH-UQ-BACKING-INDEX-OPTIONS-DRIFT",
    "AUTH-UQ-CATALOG-DEFERRABLE",
    "DUPLICATE-NAMED-UQ-PRECEDES-EXPECTED",
    "AUTH-INDEX-PREDICATE-DRIFT",
    "AUTH-INDEX-UNIQUENESS-DRIFT",
    "AUTH-INDEX-OPTIONS-DRIFT",
    "AUTH-INDEX-CATALOG-INVALID",
    "AUTH-INDEX-CATALOG-UNREADY",
    "AUTH-INDEX-CATALOG-DEAD",
    "ALLOW-ZERO-RETENTION-WINDOW",
    "REJECT-DOCUMENTED-BLANK-RETENTION",
    "ACCEPT-WHITESPACE-RETENTION",
    "ALLOW-UNKNOWN-RETENTION-MODE",
    "LOGOUT-LEAVES-ACTIVE-SESSION",
    "LOGOUT-COOKIE-PATH-DRIFT",
    "COOKIE-ATTRIBUTE-VALUE-CASING-DRIFT",
    "COOKIE-ATTRIBUTE-SUBSTRING-ACCEPTED",
    "COOKIE-DUPLICATE-HEADER-ACCEPTED",
    "COOKIE-DUPLICATE-ATTRIBUTE-ACCEPTED",
    "COOKIE-MISSING-HEADER-ACCEPTED",
    "COOKIE-DOMAIN-ACCEPTED",
    "COOKIE-SECURE-PARITY-DRIFT",
    "COOKIE-VALUED-SECURE-FALSE-ACCEPTED",
    "COOKIE-VALUED-SECURE-ZERO-ACCEPTED",
    "COOKIE-VALUED-SECURE-EMPTY-ACCEPTED",
    "COOKIE-CONTRACT-TYPE-COERCION",
    "EXPIRY-USES-SWEEP-TIME",
    "ROTATION-ACCEPTS-OLD-COOKIE",
    "ROTATION-CREATES-TWO-ACTIVE",
    "SKIP-DECOY-ATTEMPT-PURGE",
    "CUT-OFF-INCLUSIVE",
    "UNSET-WINDOW-MUTATES",
    "ANONYMISE-RETAINS-BEARER-HASH",
    "DELETE-LEAVES-SESSION",
    "REGISTRATION-ERASURE-LEAVES-LINK",
    "PRIVACY-DELETE-NONATOMIC-FREEZE",
    "SKIP-LEGACY-ACCEPTED-DELETION",
    "SKIP-LEGACY-REGISTRATION-FREEZE",
    "OMIT-ONE-RACE",
    "OMIT-REGISTRATION-ANONYMISE-RETENTION-RACE",
    "OMIT-REGISTRATION-DELETE-RETENTION-RACE",
    "RETENTION-SWEEP-BEFORE-RECOVERY-FLUSH",
    "RACE-ALLOWS-SESSION-RESURRECTION",
    "RACE-COHERENT-DOUBLE-COMMIT",
    "RACE-SPLIT-COMMIT-TAUTOLOGY",
    "AUDIT-CONTAINS-IDENTIFIER",
    "SCRATCH-CLEANUP-NOT-FINAL",
    "SCRATCH-CREATE-ORPHAN-NOT-COMPENSATED",
    "SCRATCH-CREATE-CLEANUP-UNCERTAINTY-IGNORED",
    "ASSERTION-INVENTORY-REORDERED",
)

# These are named assurance probes, not 94 distinct product/source mutations.
# Some names document separate threat labels that currently exercise the same
# aggregate observation perturbation.  Keep that relationship explicit so the
# release report cannot overstate the amount of independent mutation coverage.
MUTANT_ALIAS_OF = {
    "ACCEPT-MISSING-LEGACY-DELETION-JOB": (
        "ACCEPT-CORRUPT-LEGACY-DELETION-TARGET"
    ),
    "NULLABLE-LOGIN-LOOKUP": "RELAX-SESSION-USER-NULLABILITY",
    "NULLABLE-SESSION-TOKEN": "RELAX-SESSION-USER-NULLABILITY",
    "AUTH-COLUMN-WRONG-TYPE": "RELAX-SESSION-USER-NULLABILITY",
    "AUTH-COLUMN-WRONG-LENGTH": "RELAX-SESSION-USER-NULLABILITY",
    "AUTH-COLUMN-WRONG-DEFAULT": "RELAX-SESSION-USER-NULLABILITY",
    "AUTH-COLUMN-WRONG-TIMEZONE": "RELAX-SESSION-USER-NULLABILITY",
    "AUTH-PK-CATALOG-NO-INHERIT-FALSE": "AUTH-PK-CATALOG-DEFERRABLE",
    "AUTH-UQ-CATALOG-NO-INHERIT-FALSE": "AUTH-PK-CATALOG-DEFERRABLE",
    "AUTH-FK-CATALOG-NOT-VALID": "AUTH-PK-CATALOG-DEFERRABLE",
    "AUTH-FK-CATALOG-NO-INHERIT-FALSE": "AUTH-PK-CATALOG-DEFERRABLE",
    "AUTH-UQ-CATALOG-DEFERRABLE": "AUTH-PK-CATALOG-DEFERRABLE",
    "AUTH-INDEX-CATALOG-INVALID": "AUTH-PK-INCLUDE-DRIFT",
    "AUTH-INDEX-CATALOG-UNREADY": "AUTH-PK-INCLUDE-DRIFT",
    "AUTH-INDEX-CATALOG-DEAD": "AUTH-PK-INCLUDE-DRIFT",
    "AUTH-FK-OPTIONS-DRIFT": "AUTH-FK-DRIFT",
    "DUPLICATE-NAMED-FK-PRECEDES-EXPECTED": "AUTH-FK-DRIFT",
    "AUTH-CHECK-NOT-VALID": "AUTH-CHECK-SQL-DRIFT",
    "AUTH-CHECK-NO-INHERIT": "AUTH-CHECK-SQL-DRIFT",
    "DUPLICATE-NAMED-UQ-PRECEDES-EXPECTED": "AUTH-UQ-DRIFT",
    "AUTH-UQ-BACKING-INDEX-EXTRA": "AUTH-UQ-BACKING-INDEX-MISSING",
    "AUTH-UQ-BACKING-INDEX-NAME-DRIFT": (
        "AUTH-UQ-BACKING-INDEX-MISSING"
    ),
    "AUTH-UQ-BACKING-INDEX-DUPLICATE-LINK-DRIFT": (
        "AUTH-UQ-BACKING-INDEX-MISSING"
    ),
    "AUTH-UQ-BACKING-INDEX-COLUMNS-DRIFT": (
        "AUTH-UQ-BACKING-INDEX-MISSING"
    ),
    "AUTH-UQ-BACKING-INDEX-UNIQUENESS-DRIFT": (
        "AUTH-UQ-BACKING-INDEX-MISSING"
    ),
    "AUTH-UQ-BACKING-INDEX-PREDICATE-DRIFT": (
        "AUTH-UQ-BACKING-INDEX-MISSING"
    ),
    "AUTH-UQ-BACKING-INDEX-INCLUDE-DRIFT": (
        "AUTH-UQ-BACKING-INDEX-MISSING"
    ),
    "AUTH-UQ-BACKING-INDEX-OPTIONS-DRIFT": (
        "AUTH-UQ-BACKING-INDEX-MISSING"
    ),
    "AUTH-INDEX-UNIQUENESS-DRIFT": "AUTH-UQ-BACKING-INDEX-MISSING",
    "AUTH-INDEX-OPTIONS-DRIFT": "AUTH-UQ-BACKING-INDEX-MISSING",
}

DISTINCT_MUTANT_IDS = tuple(
    identifier
    for identifier in REQUIRED_MUTANT_IDS
    if identifier not in MUTANT_ALIAS_OF
)
EXPECTED_MUTANT_INVENTORY = {
    "named_probe_ids": 94,
    "distinct_probe_variants": 64,
    "duplicate_aliases": 30,
    "killed_named_probe_ids": 94,
    "killed_distinct_probe_variants": 64,
}

EXPECTED_COOKIE_CONTRACT = {
    "auth_path": "/",
    "auth_same_site": "lax",
    "flow_path": "/api/v1",
    "flow_same_site": "strict",
    "http_only": True,
    "secure_parity": True,
    "host_only": True,
}

_LOGIN_COLUMNS = (
    ("id", Uuid, None, False, None),
    ("opaque_id", String, 64, False, None),
    ("lookup_hash", String, 64, False, None),
    ("registration_id", Uuid, None, True, None),
    ("challenge_id", Uuid, None, True, None),
    ("status", String, 24, False, "pending"),
    ("expires_at", DateTime, None, False, None),
    ("consumed_at", DateTime, None, True, None),
    ("created_at", DateTime, None, False, "now"),
    ("updated_at", DateTime, None, False, "now"),
    ("deleted_at", DateTime, None, True, None),
    ("metadata_json", JSON, None, True, None),
)
_SESSION_COLUMNS = (
    ("id", Uuid, None, False, None),
    ("user_id", Uuid, None, True, None),
    ("token_hash", String, 64, False, None),
    ("status", String, 24, False, "active"),
    ("expires_at", DateTime, None, False, None),
    ("last_seen_at", DateTime, None, False, None),
    ("revoked_at", DateTime, None, True, None),
    ("created_at", DateTime, None, False, "now"),
    ("updated_at", DateTime, None, False, "now"),
    ("deleted_at", DateTime, None, True, None),
    ("metadata_json", JSON, None, True, None),
)


def _hex_check_contract(column: str) -> str:
    expression = column
    for character in "0123456789abcdef":
        expression = f"replace({expression}, '{character}', '')"
    return f"length({expression}) = 0"


_LOGIN_CHECKS = {
    "ck_login_attempts_status": (
        "status IN ('pending', 'consumed', 'expired', 'erased')"
    ),
    "ck_login_attempts_lookup_hash_shape": (
        "length(lookup_hash) = 64 AND " + _hex_check_contract("lookup_hash")
    ),
    "ck_login_attempts_opaque_id_shape": (
        "((status <> 'erased' AND length(opaque_id) = 32) OR "
        "(status = 'erased' AND length(opaque_id) = 64)) AND "
        + _hex_check_contract("opaque_id")
    ),
    "ck_login_attempts_lifecycle_shape": (
        "(status = 'pending' AND consumed_at IS NULL AND deleted_at IS NULL) OR "
        "(status IN ('consumed', 'expired') AND consumed_at IS NOT NULL "
        "AND deleted_at IS NULL) OR "
        "(status = 'erased' AND registration_id IS NULL AND challenge_id IS NULL "
        "AND consumed_at IS NOT NULL AND deleted_at IS NOT NULL "
        "AND metadata_json IS NULL AND created_at = updated_at "
        "AND updated_at = expires_at AND expires_at = consumed_at "
        "AND consumed_at = deleted_at)"
    ),
}
_SESSION_CHECKS = {
    "ck_auth_sessions_status": (
        "status IN ('active', 'revoked', 'expired', 'erased')"
    ),
    "ck_auth_sessions_token_hash_shape": (
        "length(token_hash) = 64 AND " + _hex_check_contract("token_hash")
    ),
    "ck_auth_sessions_lifecycle_shape": (
        "(status = 'active' AND user_id IS NOT NULL AND revoked_at IS NULL "
        "AND deleted_at IS NULL) OR "
        "(status IN ('revoked', 'expired') AND user_id IS NOT NULL "
        "AND revoked_at IS NOT NULL AND deleted_at IS NULL) OR "
        "(status = 'erased' AND user_id IS NULL AND revoked_at IS NOT NULL "
        "AND deleted_at IS NOT NULL AND metadata_json IS NULL "
        "AND created_at = updated_at AND updated_at = expires_at "
        "AND expires_at = last_seen_at AND last_seen_at = revoked_at "
        "AND revoked_at = deleted_at)"
    ),
}
_LOGIN_INDEXES = {
    "ix_login_attempts_lookup_hash": (("lookup_hash",), False, None),
    "ix_login_attempts_registration_id": (("registration_id",), False, None),
    "ix_login_attempts_challenge_id": (("challenge_id",), False, None),
    "ix_login_attempts_expires_at": (("expires_at",), False, None),
    "ix_login_attempts_consumed_at": (("consumed_at",), False, None),
}
_SESSION_INDEXES = {
    "ix_auth_sessions_user_id": (("user_id",), False, None),
    "ix_auth_sessions_token_hash": (("token_hash",), False, None),
    "ix_auth_sessions_expires_at": (("expires_at",), False, None),
    "ix_auth_sessions_revoked_at": (("revoked_at",), False, None),
    "uq_auth_sessions_one_active_per_user": (
        ("user_id",),
        True,
        "status = 'active'",
    ),
}
_POSTGRESQL_UQ_BACKING_INDEXES = {
    "login_attempts": {
        "uq_login_attempts_opaque_id": ("opaque_id",),
    },
    "auth_sessions": {
        "uq_auth_sessions_token_hash": ("token_hash",),
    },
}

_UUID_TEXT = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_EMAIL_TEXT = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_MOBILE_TEXT = re.compile(r"(?<!\d)\d{10}(?!\d)")
_DATE_TEXT = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_URL_TEXT = re.compile(r"(?i)\b(?:postgres(?:ql)?|https?)\+?[^\s:]*://")
_HEX64_TEXT = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_COOKIE_VALUE_TEXT = re.compile(r"(?i)(?:set-cookie|cookie)\s*[:=]")
_FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "database_url",
        "scratch_database",
        "scratch_name",
        "user_id",
        "registration_id",
        "attempt_id",
        "session_id",
        "request_id",
        "opaque_id",
        "lookup_hash",
        "token_hash",
        "cookie",
        "cookie_value",
        "mobile",
        "email",
        "dob",
        "otp",
        "code",
        "payload",
        "metadata_json",
        "before_state",
        "after_state",
    }
)


class Blocked(RuntimeError):
    """A required target-runtime prerequisite is absent; never a pass."""


class ProductGateFailure(RuntimeError):
    """A product, migration, evaluator, or privacy assertion failed."""


class ScratchCleanupFailure(RuntimeError):
    """A disposable database could not be removed; always fatal."""


def _exact_keys(observation: Mapping[str, Any], expected: set[str]) -> bool:
    return set(observation) == expected


def _is_exact_bool(value: object) -> bool:
    return type(value) is bool


def _is_exact_int(value: object) -> bool:
    return type(value) is int


def _reject_ambient_libpq_environment(
    environment: Mapping[str, str] | None = None,
) -> None:
    """Reject libpq routing authority without copying any supplied value."""

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
    except Exception as exc:  # noqa: BLE001 - URL remains private
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
    except Exception:  # pragma: no cover - compatible-server fallback
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}"')


def _create_scratch(base: URL, name: str) -> str:
    try:
        _drop_scratch(base, name)
        _admin_execute(base, f'CREATE DATABASE "{name}"')
    except Exception as exc:  # noqa: BLE001 - sanitized prerequisite failure
        raise Blocked("could not create a disposable scratch database") from exc
    return _database_url(base, name)


def _scratch_database_inventory(base: URL) -> set[str]:
    """Keep private NYAY-19 scratch names in memory only."""

    engine = create_engine(_database_url(base, "postgres"), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return {
                str(value)
                for value in connection.scalars(
                    text(
                        "SELECT datname FROM pg_database "
                        "WHERE datname LIKE 'nyay19_auth_%'"
                    )
                )
            }
    finally:
        engine.dispose()


class _ScratchDatabaseManager:
    """Own disposable databases and include cleanup in the verdict."""

    def __init__(self, base: URL) -> None:
        self.base = base
        self.records: list[dict[str, Any]] = []
        self._owned_names: set[str] = set()
        try:
            self._baseline_inventory = _scratch_database_inventory(base)
        except Exception as exc:  # noqa: BLE001 - sanitized authority failure
            raise Blocked("could not inventory disposable scratch databases") from exc

    def run(self, purpose: str, operation: Callable[[str], Any]) -> Any:
        name = f"nyay19_auth_{uuid.uuid4().hex[:12]}"
        record: dict[str, Any] = {
            "purpose": purpose,
            "created": False,
            "cleanup": "NOT_CREATED",
        }
        self.records.append(record)
        self._owned_names.add(name)
        try:
            scratch_url = _create_scratch(self.base, name)
            record["created"] = True
            return operation(scratch_url)
        finally:
            try:
                _drop_scratch(self.base, name)
                if name in _scratch_database_inventory(self.base):
                    raise ScratchCleanupFailure(
                        "a disposable NYAY-19 database remained after cleanup"
                    )
            except ScratchCleanupFailure:
                record["cleanup"] = "FAIL"
                raise
            except Exception as exc:  # noqa: BLE001 - sanitized cleanup failure
                record["cleanup"] = "FAIL"
                raise ScratchCleanupFailure(
                    "a disposable NYAY-19 database could not be removed"
                ) from exc
            record["cleanup"] = "PASS"

    def summary(self) -> dict[str, Any]:
        created = sum(row["created"] is True for row in self.records)
        removed = sum(row["cleanup"] == "PASS" for row in self.records)
        failed = sum(row["cleanup"] == "FAIL" for row in self.records)
        try:
            final_inventory = _scratch_database_inventory(self.base)
            inventory_match = bool(
                final_inventory == self._baseline_inventory
                and not self._owned_names.intersection(final_inventory)
            )
            final_count = len(final_inventory)
        except Exception:  # noqa: BLE001 - summary fails closed
            inventory_match = False
            final_count = -1
        return {
            "created": created,
            "removed": removed,
            "cleanup_failed": failed,
            "all_created_removed": bool(
                created == removed and failed == 0 and inventory_match
            ),
            "inventory_match": inventory_match,
            "baseline_count": len(self._baseline_inventory),
            "final_count": final_count,
            "purposes": [row["purpose"] for row in self.records],
        }


def _is_postgresql_16_with_pgvector(
    server_version_num: object, vector_version: object
) -> bool:
    return bool(
        type(server_version_num) is int
        and 160000 <= server_version_num < 170000
        and isinstance(vector_version, str)
        and bool(vector_version.strip())
    )


def _runtime_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {"server_version_num", "postgres_major", "pgvector_present"},
        )
        and _is_postgresql_16_with_pgvector(
            observation.get("server_version_num"),
            "present" if observation.get("pgvector_present") is True else None,
        )
        and _is_exact_int(observation.get("postgres_major"))
        and observation.get("postgres_major") == 16
    )


def _migration_observation_passes(observation: Mapping[str, Any]) -> bool:
    expected = {
        "historical_bytes_immutable",
        "historical_file_inventory_exact",
        "historical_hash_inventory_exact",
        "post_ddl_exact_head_validation",
        "post_ddl_validation_failure_rolled_back",
        "pinned_release_exact",
        "parent_upgrade_returncode",
        "head_upgrade_returncode",
        "head_revision_exact",
        "revision_rows",
        "parent_schema_roundtrip_exact",
        "parent_rows_roundtrip_exact",
        "invalid_upgrade_refused_unchanged",
    }
    return bool(
        _exact_keys(observation, expected)
        and observation.get("historical_bytes_immutable") is True
        and observation.get("historical_file_inventory_exact") is True
        and observation.get("historical_hash_inventory_exact") is True
        and observation.get("post_ddl_exact_head_validation") is True
        and observation.get("post_ddl_validation_failure_rolled_back") is True
        and observation.get("pinned_release_exact") is True
        and all(
            _is_exact_int(observation.get(key))
            for key in (
                "parent_upgrade_returncode",
                "head_upgrade_returncode",
                "revision_rows",
            )
        )
        and observation.get("parent_upgrade_returncode") == 0
        and observation.get("head_upgrade_returncode") == 0
        and observation.get("head_revision_exact") is True
        and observation.get("revision_rows") == 1
        and observation.get("parent_schema_roundtrip_exact") is True
        and observation.get("parent_rows_roundtrip_exact") is True
        and observation.get("invalid_upgrade_refused_unchanged") is True
    )


def _populated_migration_observation_passes(
    observation: Mapping[str, Any],
) -> bool:
    expected = {
        "login_rows",
        "session_rows",
        "login_expiry_backfilled",
        "session_revocation_backfilled",
        "live_rows_preserved",
        "erased_login_shape_exact",
        "erased_session_shape_exact",
        "erased_downgrade_refused",
        "legacy_delete_corrupt_cases",
        "legacy_delete_preflight_rejects_corrupt_target",
        "legacy_delete_downgrade_marker_refuses",
        "legacy_delete_backfill_aggregate_audit_exact",
        "refusal_schema_unchanged",
        "refusal_rows_unchanged",
    }
    return bool(
        _exact_keys(observation, expected)
        and _is_exact_int(observation.get("login_rows"))
        and _is_exact_int(observation.get("session_rows"))
        and observation.get("login_rows") == 3
        and observation.get("session_rows") == 3
        and _is_exact_int(observation.get("legacy_delete_corrupt_cases"))
        and observation.get("legacy_delete_corrupt_cases") == 5
        and all(
            observation.get(key) is True
            for key in expected
            - {"login_rows", "session_rows", "legacy_delete_corrupt_cases"}
        )
    )


def _canonical_schema_check(value: object) -> object:
    """Use the pinned 0018 parser to compare CHECK semantics, not substrings."""

    migration = importlib.import_module(
        "app.db.migrations.versions.0018_registration_idempotency"
    )
    return migration._canonical_check(value)


def _canonical_schema_default(value: object) -> str:
    migration = importlib.import_module(
        "app.db.migrations.versions.0018_registration_idempotency"
    )
    return migration._normalise_default(value)


def _column_inventory_exact(inspector: Any) -> bool:
    return bool(
        [row.get("name") for row in inspector.get_columns("login_attempts")]
        == [row[0] for row in _LOGIN_COLUMNS]
        and [row.get("name") for row in inspector.get_columns("auth_sessions")]
        == [row[0] for row in _SESSION_COLUMNS]
    )


def _column_definitions_exact(inspector: Any, *, dialect_name: str) -> bool:
    for table, expected in (
        ("login_attempts", _LOGIN_COLUMNS),
        ("auth_sessions", _SESSION_COLUMNS),
    ):
        columns = inspector.get_columns(table)
        if len(columns) != len(expected):
            return False
        for column, (name, kind, length, nullable, default) in zip(
            columns, expected, strict=True
        ):
            column_type = column.get("type")
            if (
                column.get("name") != name
                or not isinstance(column_type, kind)
                or bool(column.get("nullable")) is not nullable
            ):
                return False
            if kind is String and getattr(column_type, "length", None) != length:
                return False
            if (
                kind is DateTime
                and dialect_name == "postgresql"
                and not bool(getattr(column_type, "timezone", False))
            ):
                return False
            reflected_default = column.get("default")
            if default is None and reflected_default is not None:
                return False
            if default in {"pending", "active"} and _canonical_schema_default(
                reflected_default
            ) != f"'{default}'":
                return False
            if default == "now" and _canonical_schema_default(
                reflected_default
            ) not in {"now()", "current_timestamp"}:
                return False
    return True


def _primary_keys_exact(inspector: Any) -> bool:
    expected = {
        "login_attempts": ("pk_login_attempts", ["id"]),
        "auth_sessions": ("pk_auth_sessions", ["id"]),
    }
    for table, (name, columns) in expected.items():
        row = inspector.get_pk_constraint(table)
        if (
            row.get("name") != name
            or row.get("constrained_columns") != columns
            or any((row.get("dialect_options") or {}).values())
            or row.get("deferrable") not in (None, False)
            or row.get("initially") is not None
        ):
            return False
    return True


def _foreign_keys_exact(inspector: Any) -> bool:
    expected = {
        "login_attempts": {
            "fk_login_attempts_registration_id_student_registrations": (
                ("registration_id",),
                None,
                "student_registrations",
                ("id",),
                (("ondelete", "CASCADE"),),
            ),
            "fk_login_attempts_challenge_id_otp_challenges": (
                ("challenge_id",),
                None,
                "otp_challenges",
                ("id",),
                (("ondelete", "SET NULL"),),
            ),
        },
        "auth_sessions": {
            "fk_auth_sessions_user_id_users": (
                ("user_id",),
                None,
                "users",
                ("id",),
                (("ondelete", "CASCADE"),),
            )
        },
    }
    for table, expected_rows in expected.items():
        reflected = inspector.get_foreign_keys(table)
        actual = {
            str(row.get("name")): (
                tuple(row.get("constrained_columns") or ()),
                row.get("referred_schema"),
                str(row.get("referred_table")),
                tuple(row.get("referred_columns") or ()),
                tuple(
                    sorted(
                        (str(key), str(value).upper())
                        for key, value in (row.get("options") or {}).items()
                    )
                ),
            )
            for row in reflected
            if row.get("name")
        }
        if (
            len(reflected) != len(expected_rows)
            or actual != expected_rows
            or any(any((row.get("dialect_options") or {}).values()) for row in reflected)
        ):
            return False
    return True


def _unique_constraints_exact(inspector: Any) -> bool:
    expected = {
        "login_attempts": {"uq_login_attempts_opaque_id": ("opaque_id",)},
        "auth_sessions": {"uq_auth_sessions_token_hash": ("token_hash",)},
    }
    for table, expected_rows in expected.items():
        reflected = inspector.get_unique_constraints(table)
        actual = {
            str(row.get("name")): tuple(row.get("column_names") or ())
            for row in reflected
            if row.get("name")
        }
        if (
            len(reflected) != 1
            or actual != expected_rows
            or any(any((row.get("dialect_options") or {}).values()) for row in reflected)
            or any(row.get("deferrable") not in (None, False) for row in reflected)
            or any(row.get("initially") is not None for row in reflected)
        ):
            return False
    return True


def _index_predicate(row: Mapping[str, Any], *, dialect_name: str) -> object:
    options = row.get("dialect_options") or {}
    return options.get(
        "postgresql_where" if dialect_name == "postgresql" else "sqlite_where"
    )


def _indexes_exact(inspector: Any, *, dialect_name: str) -> bool:
    for table, expected in (
        ("login_attempts", _LOGIN_INDEXES),
        ("auth_sessions", _SESSION_INDEXES),
    ):
        reflected = inspector.get_indexes(table)
        duplicate_rows = [
            row
            for row in reflected
            if row.get("duplicates_constraint") is not None
        ]
        expected_duplicates = (
            _POSTGRESQL_UQ_BACKING_INDEXES[table]
            if dialect_name == "postgresql"
            else {}
        )
        duplicate_shape: dict[str, tuple[tuple[str, ...], str]] = {}
        for row in duplicate_rows:
            name = str(row.get("name"))
            options = row.get("dialect_options") or {}
            if (
                name in duplicate_shape
                or row.get("unique") is not True
                or row.get("duplicates_constraint") != name
                or row.get("include_columns") not in (None, (), [])
                or row.get("column_sorting") not in (None, {})
                or set(options)
                - {"postgresql_include", "postgresql_nulls_not_distinct"}
                or options.get("postgresql_include") not in (None, (), [])
                or options.get("postgresql_nulls_not_distinct")
                not in (None, False)
                or _index_predicate(row, dialect_name=dialect_name) is not None
            ):
                return False
            duplicate_shape[name] = (
                tuple(row.get("column_names") or ()),
                str(row.get("duplicates_constraint")),
            )
        expected_duplicate_shape = {
            name: (columns, name)
            for name, columns in expected_duplicates.items()
        }
        if (
            len(duplicate_rows) != len(expected_duplicates)
            or duplicate_shape != expected_duplicate_shape
        ):
            return False

        explicit_rows = [
            row for row in reflected if row.get("duplicates_constraint") is None
        ]
        actual = {
            str(row.get("name")): (
                tuple(row.get("column_names") or ()),
                row.get("unique"),
            )
            for row in explicit_rows
            if row.get("name")
        }
        expected_shape = {
            name: (columns, unique)
            for name, (columns, unique, _predicate) in expected.items()
        }
        if (
            len(explicit_rows) != len(expected)
            or actual != expected_shape
            or any(type(row.get("unique")) is not bool for row in explicit_rows)
        ):
            return False
        for row in explicit_rows:
            name = str(row.get("name"))
            options = row.get("dialect_options") or {}
            if row.get("include_columns") not in (None, (), []):
                return False
            where_key = (
                "postgresql_where"
                if dialect_name == "postgresql"
                else "sqlite_where"
            )
            for key, value in options.items():
                if key == where_key:
                    continue
                if value not in (None, False, "", (), [], {}):
                    return False
            predicate = _index_predicate(row, dialect_name=dialect_name)
            if name == "uq_auth_sessions_one_active_per_user":
                if _canonical_schema_check(predicate) != _canonical_schema_check(
                    "status = 'active'"
                ):
                    return False
            elif predicate is not None:
                return False
    return True


def _partial_active_index_exact(inspector: Any, *, dialect_name: str) -> bool:
    matches = [
        row
        for row in inspector.get_indexes("auth_sessions")
        if row.get("name") == "uq_auth_sessions_one_active_per_user"
    ]
    return bool(
        len(matches) == 1
        and matches[0].get("column_names") == ["user_id"]
        and matches[0].get("unique") is True
        and _canonical_schema_check(
            _index_predicate(matches[0], dialect_name=dialect_name)
        )
        == _canonical_schema_check("status = 'active'")
    )


def _check_inventory(
    inspector: Any,
) -> tuple[dict[str, object], dict[str, object]]:
    login = {
        str(row.get("name")): _canonical_schema_check(row.get("sqltext"))
        for row in inspector.get_check_constraints("login_attempts")
        if row.get("name")
    }
    sessions = {
        str(row.get("name")): _canonical_schema_check(row.get("sqltext"))
        for row in inspector.get_check_constraints("auth_sessions")
        if row.get("name")
    }
    return login, sessions


def _check_names_exact(inspector: Any) -> bool:
    login, sessions = _check_inventory(inspector)
    return bool(
        set(login) == set(_LOGIN_CHECKS)
        and set(sessions) == set(_SESSION_CHECKS)
        and len(inspector.get_check_constraints("login_attempts"))
        == len(_LOGIN_CHECKS)
        and len(inspector.get_check_constraints("auth_sessions"))
        == len(_SESSION_CHECKS)
    )


def _expected_auth_check_catalog() -> dict[tuple[str, str], str]:
    return {
        **{("login_attempts", name): sql for name, sql in _LOGIN_CHECKS.items()},
        **{("auth_sessions", name): sql for name, sql in _SESSION_CHECKS.items()},
    }


def _expected_auth_constraint_catalog() -> dict[
    tuple[str, str],
    tuple[
        str,
        tuple[str, ...],
        str | None,
        str | None,
        str | None,
        tuple[str, ...],
    ],
]:
    """Exact PostgreSQL constraint inventory whose safety bits Inspector omits."""

    return {
        ("login_attempts", "pk_login_attempts"): (
            "p", ("id",), "pk_login_attempts", None, None, ()
        ),
        ("login_attempts", "uq_login_attempts_opaque_id"): (
            "u", ("opaque_id",), "uq_login_attempts_opaque_id", None, None, ()
        ),
        (
            "login_attempts",
            "fk_login_attempts_registration_id_student_registrations",
        ): (
            "f",
            ("registration_id",),
            "pk_student_registrations",
            "c",
            "student_registrations",
            ("id",),
        ),
        (
            "login_attempts",
            "fk_login_attempts_challenge_id_otp_challenges",
        ): (
            "f",
            ("challenge_id",),
            "pk_otp_challenges",
            "n",
            "otp_challenges",
            ("id",),
        ),
        ("auth_sessions", "pk_auth_sessions"): (
            "p", ("id",), "pk_auth_sessions", None, None, ()
        ),
        ("auth_sessions", "uq_auth_sessions_token_hash"): (
            "u", ("token_hash",), "uq_auth_sessions_token_hash", None, None, ()
        ),
        ("auth_sessions", "fk_auth_sessions_user_id_users"): (
            "f", ("user_id",), "pk_users", "c", "users", ("id",)
        ),
    }


def _expected_auth_index_catalog() -> dict[
    tuple[str, str], tuple[tuple[str, ...], tuple[str, ...], bool, bool, str | None]
]:
    """Exact key/include inventory for constraint-owned and explicit indexes."""

    expected: dict[
        tuple[str, str], tuple[
            tuple[str, ...], tuple[str, ...], bool, bool, str | None
        ]
    ] = {
        ("login_attempts", "pk_login_attempts"): (
            ("id",), (), True, True, None
        ),
        ("login_attempts", "uq_login_attempts_opaque_id"): (
            ("opaque_id",), (), True, False, None
        ),
        ("auth_sessions", "pk_auth_sessions"): (
            ("id",), (), True, True, None
        ),
        ("auth_sessions", "uq_auth_sessions_token_hash"): (
            ("token_hash",), (), True, False, None
        ),
    }
    for table, indexes in (
        ("login_attempts", _LOGIN_INDEXES),
        ("auth_sessions", _SESSION_INDEXES),
    ):
        expected.update(
            {
                (table, name): (columns, (), unique, False, predicate)
                for name, (columns, unique, predicate) in indexes.items()
            }
        )
    return expected


def _postgresql_auth_constraint_catalog_sql(
    engine: Engine,
) -> dict[tuple[str, str], dict[str, Any]] | None:
    """Read p/u/f validation and deferrability from scoped pg_catalog rows."""

    statement = text(
        "SELECT cls.relname, con.conname, con.contype, con.convalidated, "
        "con.condeferrable, con.condeferred, con.connoinherit, "
        "con.confupdtype, con.confdeltype, con.confmatchtype, "
        "idx_cls.relname, ref_cls.relname, "
        "ARRAY(SELECT att.attname FROM unnest(con.conkey) WITH ORDINALITY "
        "AS key(attnum, position) JOIN pg_catalog.pg_attribute AS att "
        "ON att.attrelid = con.conrelid AND att.attnum = key.attnum "
        "ORDER BY key.position), "
        "ARRAY(SELECT att.attname FROM unnest(con.confkey) WITH ORDINALITY "
        "AS key(attnum, position) JOIN pg_catalog.pg_attribute AS att "
        "ON att.attrelid = con.confrelid AND att.attnum = key.attnum "
        "ORDER BY key.position) "
        "FROM pg_catalog.pg_constraint AS con "
        "JOIN pg_catalog.pg_class AS cls ON cls.oid = con.conrelid "
        "JOIN pg_catalog.pg_namespace AS ns ON ns.oid = cls.relnamespace "
        "LEFT JOIN pg_catalog.pg_class AS idx_cls ON idx_cls.oid = con.conindid "
        "LEFT JOIN pg_catalog.pg_class AS ref_cls ON ref_cls.oid = con.confrelid "
        "WHERE con.contype IN ('p', 'u', 'f') "
        "AND ns.nspname = current_schema() AND cls.relname IN :table_names "
        "ORDER BY cls.relname, con.conname"
    ).bindparams(bindparam("table_names", expanding=True))
    try:
        with engine.connect() as connection:
            rows = list(
                connection.execute(
                    statement,
                    {"table_names": ("auth_sessions", "login_attempts")},
                )
            )
    except SQLAlchemyError:
        return None
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for (
        table,
        name,
        kind,
        validated,
        deferrable,
        deferred,
        no_inherit,
        update_action,
        delete_action,
        match_type,
        backing_index,
        referred_table,
        columns,
        referred_columns,
    ) in rows:
        key = (str(table), str(name))
        if key in output or columns is None:
            return None
        output[key] = {
            "kind": str(kind),
            "columns": tuple(str(column) for column in columns),
            "validated": validated,
            "deferrable": deferrable,
            "deferred": deferred,
            "no_inherit": no_inherit,
            "update_action": update_action,
            "delete_action": delete_action,
            "match_type": match_type,
            "backing_index": None if backing_index is None else str(backing_index),
            "referred_table": (
                None if referred_table is None else str(referred_table)
            ),
            "referred_columns": tuple(
                str(column) for column in (referred_columns or ())
            ),
        }
    return output


def _auth_constraint_catalog_observation_passes(
    observation: Mapping[tuple[str, str], Mapping[str, Any]] | None,
) -> bool:
    expected = _expected_auth_constraint_catalog()
    if observation is None or set(observation) != set(expected):
        return False
    for key, (
        kind,
        columns,
        backing_index,
        delete_action,
        referred_table,
        referred_columns,
    ) in expected.items():
        row = observation.get(key)
        if (
            not isinstance(row, Mapping)
            or set(row)
            != {
                "kind",
                "columns",
                "validated",
                "deferrable",
                "deferred",
                "no_inherit",
                "update_action",
                "delete_action",
                "match_type",
                "backing_index",
                "referred_table",
                "referred_columns",
            }
            or row.get("kind") != kind
            or row.get("columns") != columns
            or row.get("validated") is not True
            or row.get("deferrable") is not False
            or row.get("deferred") is not False
            # PostgreSQL 16 records ordinary-table PK/UQ/FK constraints as
            # connoinherit=true.  This is a catalog state separate from the
            # CHECK-constraint NO INHERIT syntax contract (which remains false).
            or row.get("no_inherit") is not True
            or row.get("backing_index") != backing_index
            or row.get("referred_table") != referred_table
            or row.get("referred_columns") != referred_columns
        ):
            return False
        if kind == "f" and (
            row.get("update_action") != "a"
            or row.get("delete_action") != delete_action
            or row.get("match_type") != "s"
        ):
            return False
    return True


def _postgresql_auth_index_catalog_sql(
    engine: Engine,
) -> dict[tuple[str, str], dict[str, Any]] | None:
    """Read PostgreSQL index health plus exact key/include and predicate state."""

    statement = text(
        "SELECT tbl.relname, idx_cls.relname, idx.indisunique, idx.indisprimary, "
        "idx.indisexclusion, idx.indisvalid, idx.indisready, idx.indislive, "
        "idx.indnullsnotdistinct, idx.indnkeyatts, idx.indnatts, "
        "idx.indexprs IS NULL, access_method.amname, "
        "ARRAY(SELECT pg_catalog.pg_get_indexdef(idx.indexrelid, position, true) "
        "FROM generate_series(1, idx.indnatts) AS position ORDER BY position), "
        "pg_catalog.pg_get_expr(idx.indpred, idx.indrelid, false) "
        "FROM pg_catalog.pg_index AS idx "
        "JOIN pg_catalog.pg_class AS tbl ON tbl.oid = idx.indrelid "
        "JOIN pg_catalog.pg_class AS idx_cls ON idx_cls.oid = idx.indexrelid "
        "JOIN pg_catalog.pg_am AS access_method ON access_method.oid = idx_cls.relam "
        "JOIN pg_catalog.pg_namespace AS ns ON ns.oid = tbl.relnamespace "
        "WHERE ns.nspname = current_schema() AND tbl.relname IN :table_names "
        "ORDER BY tbl.relname, idx_cls.relname"
    ).bindparams(bindparam("table_names", expanding=True))
    try:
        with engine.connect() as connection:
            rows = list(
                connection.execute(
                    statement,
                    {"table_names": ("auth_sessions", "login_attempts")},
                )
            )
    except SQLAlchemyError:
        return None
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for (
        table,
        name,
        unique,
        primary,
        exclusion,
        valid,
        ready,
        live,
        nulls_not_distinct,
        key_count,
        attribute_count,
        has_no_expressions,
        access_method,
        columns,
        predicate,
    ) in rows:
        key = (str(table), str(name))
        if (
            key in output
            or columns is None
            or not isinstance(key_count, int)
            or not isinstance(attribute_count, int)
            or key_count < 0
            or attribute_count < key_count
            or len(columns) != attribute_count
        ):
            return None
        names = tuple(str(column) for column in columns)
        output[key] = {
            "key_columns": names[:key_count],
            "include_columns": names[key_count:],
            "unique": unique,
            "primary": primary,
            "exclusion": exclusion,
            "valid": valid,
            "ready": ready,
            "live": live,
            "nulls_not_distinct": nulls_not_distinct,
            "has_no_expressions": has_no_expressions,
            "access_method": str(access_method),
            "predicate": predicate,
        }
    return output


def _auth_index_catalog_observation_passes(
    observation: Mapping[tuple[str, str], Mapping[str, Any]] | None,
) -> bool:
    expected = _expected_auth_index_catalog()
    if observation is None or set(observation) != set(expected):
        return False
    for key, (keys, includes, unique, primary, predicate) in expected.items():
        row = observation.get(key)
        if (
            not isinstance(row, Mapping)
            or set(row)
            != {
                "key_columns",
                "include_columns",
                "unique",
                "primary",
                "exclusion",
                "valid",
                "ready",
                "live",
                "nulls_not_distinct",
                "has_no_expressions",
                "access_method",
                "predicate",
            }
            or row.get("key_columns") != keys
            or row.get("include_columns") != includes
            or row.get("unique") is not unique
            or row.get("primary") is not primary
            or row.get("exclusion") is not False
            or row.get("valid") is not True
            or row.get("ready") is not True
            or row.get("live") is not True
            or row.get("nulls_not_distinct") is not False
            or row.get("has_no_expressions") is not True
            or row.get("access_method") != "btree"
        ):
            return False
        actual_predicate = row.get("predicate")
        if actual_predicate is None or predicate is None:
            if actual_predicate is not None or predicate is not None:
                return False
        else:
            try:
                if _canonical_schema_check(
                    actual_predicate
                ) != _canonical_schema_check(predicate):
                    return False
            except (TypeError, ValueError):
                return False
    return True


def _postgresql_auth_check_catalog_sql(
    engine: Engine,
) -> dict[tuple[str, str], dict[str, Any]] | None:
    """Read balanced CHECK SQL and validation/inheritance bits from PostgreSQL."""

    statement = text(
        "SELECT cls.relname, con.conname, "
        "pg_get_expr(con.conbin, con.conrelid, false), "
        "con.convalidated, con.connoinherit "
        "FROM pg_constraint AS con "
        "JOIN pg_class AS cls ON cls.oid = con.conrelid "
        "JOIN pg_namespace AS ns ON ns.oid = cls.relnamespace "
        "WHERE con.contype = 'c' AND ns.nspname = current_schema() "
        "AND cls.relname IN :table_names "
        "ORDER BY cls.relname, con.conname"
    ).bindparams(bindparam("table_names", expanding=True))
    try:
        with engine.connect() as connection:
            rows = list(
                connection.execute(
                    statement,
                    {"table_names": ("auth_sessions", "login_attempts")},
                )
            )
    except SQLAlchemyError:
        return None
    output: dict[tuple[str, str], dict[str, Any]] = {}
    for table, name, sqltext, validated, no_inherit in rows:
        key = (str(table), str(name))
        if key in output or sqltext is None:
            return None
        output[key] = {
            "sqltext": sqltext,
            "validated": validated,
            "no_inherit": no_inherit,
        }
    return output


def _auth_check_catalog_observation_passes(
    observation: Mapping[tuple[str, str], Mapping[str, Any]] | None,
) -> bool:
    expected = _expected_auth_check_catalog()
    if observation is None or set(observation) != set(expected):
        return False
    for key, expected_sql in expected.items():
        row = observation.get(key)
        if (
            not isinstance(row, Mapping)
            or set(row) != {"sqltext", "validated", "no_inherit"}
            or row.get("validated") is not True
            or row.get("no_inherit") is not False
        ):
            return False
        try:
            if _canonical_schema_check(row.get("sqltext")) != _canonical_schema_check(
                expected_sql
            ):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _check_semantics_exact(
    inspector: Any, *, dialect_name: str, engine: Engine | None
) -> bool:
    for table in ("login_attempts", "auth_sessions"):
        if any(
            row.get("dialect_options")
            for row in inspector.get_check_constraints(table)
        ):
            return False
    if dialect_name == "postgresql":
        if engine is None:
            return False
        return _auth_check_catalog_observation_passes(
            _postgresql_auth_check_catalog_sql(engine)
        )
    login, sessions = _check_inventory(inspector)
    return bool(
        login
        == {
            name: _canonical_schema_check(value)
            for name, value in _LOGIN_CHECKS.items()
        }
        and sessions
        == {
            name: _canonical_schema_check(value)
            for name, value in _SESSION_CHECKS.items()
        }
    )


def _model_auth_schema_matches() -> bool:
    """Require current ORM ownership to describe every 0020 DB invariant."""

    from app.models.registration import AuthSession, LoginAttempt

    for table, expected_columns, expected_indexes, expected_checks in (
        (
            LoginAttempt.__table__,
            _LOGIN_COLUMNS,
            _LOGIN_INDEXES,
            _LOGIN_CHECKS,
        ),
        (
            AuthSession.__table__,
            _SESSION_COLUMNS,
            _SESSION_INDEXES,
            _SESSION_CHECKS,
        ),
    ):
        columns = {column.name: column for column in table.columns}
        if set(columns) != {row[0] for row in expected_columns}:
            return False
        for name, kind, length, nullable, _default in expected_columns:
            column = columns[name]
            if not isinstance(column.type, kind) or column.nullable is not nullable:
                return False
            if kind is String and getattr(column.type, "length", None) != length:
                return False
            if kind is DateTime and not bool(column.type.timezone):
                return False
            if name == "id":
                if column.default is None or not column.default.is_callable:
                    return False
            elif _default is None:
                if column.default is not None:
                    return False
            elif _default in {"pending", "active"}:
                if column.default is None or column.default.arg != _default:
                    return False
            elif _default == "now":
                if column.default is None or not column.default.is_callable:
                    return False
            if name == "updated_at":
                if column.onupdate is None or not column.onupdate.is_callable:
                    return False
            elif column.onupdate is not None:
                return False
            server_default = column.server_default
            if _default is None:
                if server_default is not None:
                    return False
            elif server_default is None:
                return False
            else:
                normalized = _canonical_schema_default(server_default.arg)
                if _default in {"pending", "active"}:
                    if normalized not in {_default, f"'{_default}'"}:
                        return False
                elif _default == "now":
                    if normalized not in {"now()", "current_timestamp"}:
                        return False
        indexes = {
            index.name: (
                tuple(column.name for column in index.columns),
                bool(index.unique),
                index.dialect_options["postgresql"].get("where"),
            )
            for index in table.indexes
        }
        if set(indexes) != set(expected_indexes):
            return False
        for name, (expected_columns_tuple, unique, predicate) in expected_indexes.items():
            columns_tuple, actual_unique, actual_predicate = indexes[name]
            if columns_tuple != expected_columns_tuple or actual_unique is not unique:
                return False
            if _canonical_schema_default(actual_predicate) != _canonical_schema_default(
                predicate
            ):
                return False
        checks = {
            constraint.name: _canonical_schema_check(constraint.sqltext)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "CheckConstraint"
        }
        if checks != {
            name: _canonical_schema_check(value)
            for name, value in expected_checks.items()
        }:
            return False
        if table.primary_key.name != f"pk_{table.name}" or tuple(
            column.name for column in table.primary_key.columns
        ) != ("id",):
            return False
        uniques = {
            constraint.name: tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        expected_uniques = (
            {"uq_login_attempts_opaque_id": ("opaque_id",)}
            if table.name == "login_attempts"
            else {"uq_auth_sessions_token_hash": ("token_hash",)}
        )
        if uniques != expected_uniques:
            return False
        foreign_keys = {
            constraint.name: (
                tuple(column.name for column in constraint.columns),
                tuple(element.target_fullname for element in constraint.elements),
                tuple(element.ondelete for element in constraint.elements),
            )
            for constraint in table.constraints
            if constraint.__class__.__name__ == "ForeignKeyConstraint"
        }
        expected_foreign_keys = (
            {
                "fk_login_attempts_registration_id_student_registrations": (
                    ("registration_id",),
                    ("student_registrations.id",),
                    ("CASCADE",),
                ),
                "fk_login_attempts_challenge_id_otp_challenges": (
                    ("challenge_id",),
                    ("otp_challenges.id",),
                    ("SET NULL",),
                ),
            }
            if table.name == "login_attempts"
            else {
                "fk_auth_sessions_user_id_users": (
                    ("user_id",),
                    ("users.id",),
                    ("CASCADE",),
                )
            }
        )
        if foreign_keys != expected_foreign_keys:
            return False
    return True


def _exact_auth_schema_observation(
    inspector: Any, *, dialect_name: str, engine: Engine | None = None
) -> dict[str, bool]:
    """Independently reflect all two-table 0020 invariants, fail closed."""

    def probe(operation: Callable[[], bool]) -> bool:
        try:
            return operation() is True
        except (AttributeError, KeyError, TypeError, ValueError):
            return False

    tables = probe(
        lambda: {"login_attempts", "auth_sessions"}
        <= set(inspector.get_table_names())
    )
    constraint_catalog_exact = False
    index_catalog_exact = False
    if dialect_name == "postgresql" and engine is not None:
        constraint_catalog_exact = probe(
            lambda: _auth_constraint_catalog_observation_passes(
                _postgresql_auth_constraint_catalog_sql(engine)
            )
        )
        index_catalog_exact = probe(
            lambda: _auth_index_catalog_observation_passes(
                _postgresql_auth_index_catalog_sql(engine)
            )
        )
    return {
        "table_inventory_exact": tables,
        "column_inventory_exact": probe(lambda: _column_inventory_exact(inspector)),
        "types_nullability_defaults_exact": probe(
            lambda: _column_definitions_exact(
                inspector, dialect_name=dialect_name
            )
        ),
        "primary_keys_exact": probe(lambda: _primary_keys_exact(inspector)),
        "foreign_keys_exact": probe(lambda: _foreign_keys_exact(inspector)),
        "unique_constraints_exact": probe(
            lambda: _unique_constraints_exact(inspector)
        ),
        "constraint_catalog_safety_exact": constraint_catalog_exact,
        "indexes_exact": probe(
            lambda: _indexes_exact(inspector, dialect_name=dialect_name)
        ),
        "index_catalog_safety_exact": index_catalog_exact,
        "partial_active_index_exact": probe(
            lambda: _partial_active_index_exact(
                inspector, dialect_name=dialect_name
            )
        ),
        "check_names_exact": probe(lambda: _check_names_exact(inspector)),
        "check_semantics_exact": probe(
            lambda: _check_semantics_exact(
                inspector, dialect_name=dialect_name, engine=engine
            )
        ),
        "model_metadata_matches": probe(_model_auth_schema_matches),
    }


def _schema_observation_passes(observation: Mapping[str, Any]) -> bool:
    expected = {
        "table_inventory_exact",
        "column_inventory_exact",
        "types_nullability_defaults_exact",
        "primary_keys_exact",
        "foreign_keys_exact",
        "unique_constraints_exact",
        "constraint_catalog_safety_exact",
        "indexes_exact",
        "index_catalog_safety_exact",
        "partial_active_index_exact",
        "check_names_exact",
        "check_semantics_exact",
        "model_metadata_matches",
    }
    return bool(
        _exact_keys(observation, expected)
        and all(observation.get(key) is True for key in expected)
    )


def _config_observation_passes(observation: Mapping[str, Any]) -> bool:
    expected = {
        "unset_login_window_is_none",
        "unset_session_window_is_none",
        "empty_login_env_is_none",
        "empty_session_env_is_none",
        "all_documented_empty_env_is_none",
        "noncanonical_text_rejected",
        "unset_windows_noop",
        "minimum_window_days",
        "maximum_window_days",
        "accepted_modes",
        "invalid_values_rejected_before_mutation",
        "statutory_duration_absent",
    }
    return bool(
        _exact_keys(observation, expected)
        and observation.get("unset_login_window_is_none") is True
        and observation.get("unset_session_window_is_none") is True
        and observation.get("empty_login_env_is_none") is True
        and observation.get("empty_session_env_is_none") is True
        and observation.get("all_documented_empty_env_is_none") is True
        and observation.get("noncanonical_text_rejected") is True
        and observation.get("unset_windows_noop") is True
        and _is_exact_int(observation.get("minimum_window_days"))
        and _is_exact_int(observation.get("maximum_window_days"))
        and observation.get("minimum_window_days") == 1
        and observation.get("maximum_window_days") == 36500
        and observation.get("accepted_modes") == ["anonymise", "delete"]
        and observation.get("invalid_values_rejected_before_mutation") is True
        and observation.get("statutory_duration_absent") is True
    )


def _logout_expiry_observation_passes(observation: Mapping[str, Any]) -> bool:
    expected = {
        "logout_status",
        "logout_active_sessions",
        "logout_replay_authenticated",
        "logout_audit_count",
        "expired_discovery_authenticated",
        "expired_status_exact",
        "expired_terminal_uses_expires_at",
        "auth_cookie_clear",
        "flow_cookie_clear",
        "cookie_contract",
        "untrusted_origin_status",
        "untrusted_origin_state_unchanged",
    }
    cookie = observation.get("cookie_contract")
    return bool(
        _exact_keys(observation, expected)
        and _is_exact_int(observation.get("logout_status"))
        and _is_exact_int(observation.get("logout_active_sessions"))
        and _is_exact_int(observation.get("logout_audit_count"))
        and _is_exact_int(observation.get("untrusted_origin_status"))
        and observation.get("logout_status") == 200
        and observation.get("logout_active_sessions") == 0
        and observation.get("logout_replay_authenticated") is False
        and observation.get("logout_audit_count") == 1
        and observation.get("expired_discovery_authenticated") is False
        and observation.get("expired_status_exact") is True
        and observation.get("expired_terminal_uses_expires_at") is True
        and observation.get("auth_cookie_clear") is True
        and observation.get("flow_cookie_clear") is True
        and _cookie_contract_observation_passes(cookie)
        and observation.get("untrusted_origin_status") == 403
        and observation.get("untrusted_origin_state_unchanged") is True
    )


def _rotation_observation_passes(observation: Mapping[str, Any]) -> bool:
    expected = {
        "first_verify_status",
        "second_verify_status",
        "active_sessions",
        "revoked_sessions",
        "old_cookie_authenticated",
        "new_cookie_authenticated",
        "old_cookie_cleared",
        "database_tokens_are_hashes",
        "wire_tokens_absent_from_database",
    }
    return bool(
        _exact_keys(observation, expected)
        and all(
            _is_exact_int(observation.get(key))
            for key in (
                "first_verify_status",
                "second_verify_status",
                "active_sessions",
                "revoked_sessions",
            )
        )
        and observation.get("first_verify_status") == 200
        and observation.get("second_verify_status") == 200
        and observation.get("active_sessions") == 1
        and observation.get("revoked_sessions") == 1
        and observation.get("old_cookie_authenticated") is False
        and observation.get("new_cookie_authenticated") is True
        and observation.get("old_cookie_cleared") is True
        and observation.get("database_tokens_are_hashes") is True
        and observation.get("wire_tokens_absent_from_database") is True
    )


def _attempt_retention_observation_passes(
    observation: Mapping[str, Any],
) -> bool:
    expected = {
        "real_expired_terminalized",
        "decoy_expired_terminalized",
        "terminal_time_uses_expires_at",
        "strictly_older_real_affected",
        "strictly_older_decoy_affected",
        "at_cutoff_real_unchanged",
        "at_cutoff_decoy_unchanged",
        "recent_real_unchanged",
        "recent_decoy_unchanged",
        "unset_window_unchanged",
        "anonymise_shape_exact",
        "delete_rows_absent",
        "rollback_restores_all_rows",
    }
    return bool(
        _exact_keys(observation, expected)
        and all(observation.get(key) is True for key in expected)
    )


def _session_retention_observation_passes(
    observation: Mapping[str, Any], *, mode: str
) -> bool:
    expected = {
        "mode",
        "expired_active_terminalized",
        "expiry_terminal_uses_expires_at",
        "strictly_older_affected",
        "at_cutoff_unchanged",
        "recent_unchanged",
        "active_unchanged",
        "unset_window_unchanged",
        "result_shape_exact",
        "bearer_replay_denied",
        "rollback_restores_all_rows",
    }
    return bool(
        mode in {"anonymise", "delete"}
        and _exact_keys(observation, expected)
        and observation.get("mode") == mode
        and all(
            observation.get(key) is True
            for key in expected - {"mode"}
        )
    )


def _registration_erasure_observation_passes(
    observation: Mapping[str, Any], *, mode: str
) -> bool:
    expected = {
        "mode",
        "active_sessions_before",
        "active_sessions_after",
        "attempts_before",
        "sessions_before",
        "attempts_after",
        "sessions_after",
        "bearer_replay_denied",
        "attempt_shape_exact",
        "session_shape_exact",
        "orphan_links",
        "rollback_restores_graph",
    }
    expected_after = 2 if mode == "anonymise" else 0
    return bool(
        mode in {"anonymise", "delete"}
        and _exact_keys(observation, expected)
        and observation.get("mode") == mode
        and all(
            _is_exact_int(observation.get(key))
            for key in (
                "active_sessions_before",
                "active_sessions_after",
                "attempts_before",
                "sessions_before",
                "attempts_after",
                "sessions_after",
                "orphan_links",
            )
        )
        and observation.get("active_sessions_before") == 1
        and observation.get("active_sessions_after") == 0
        and observation.get("attempts_before") == 2
        and observation.get("sessions_before") == 2
        and observation.get("attempts_after") == expected_after
        and observation.get("sessions_after") == expected_after
        and observation.get("bearer_replay_denied") is True
        and observation.get("attempt_shape_exact") is True
        and observation.get("session_shape_exact") is True
        and observation.get("orphan_links") == 0
        and observation.get("rollback_restores_graph") is True
    )


def _privacy_delete_observation_passes(
    observation: Mapping[str, Any],
) -> bool:
    expected = {
        "accepted_status",
        "request_rows",
        "job_rows",
        "proof_consumed",
        "user_suspended",
        "registration_suspended",
        "active_sessions",
        "bearer_replay_denied",
        "auth_cookie_clear",
        "flow_cookie_clear",
        "cookie_contract",
        "atomic_rollback_restores_all",
        "legacy_accepted_cases",
        "legacy_accounts_frozen",
        "legacy_registrations_frozen",
        "legacy_active_sessions",
        "legacy_idempotent_second_pass",
    }
    return bool(
        _exact_keys(observation, expected)
        and all(
            _is_exact_int(observation.get(key))
            for key in (
                "accepted_status",
                "request_rows",
                "job_rows",
                "active_sessions",
                "legacy_accepted_cases",
                "legacy_accounts_frozen",
                "legacy_registrations_frozen",
                "legacy_active_sessions",
            )
        )
        and observation.get("accepted_status") == 202
        and observation.get("request_rows") == 1
        and observation.get("job_rows") == 1
        and observation.get("proof_consumed") is True
        and observation.get("user_suspended") is True
        and observation.get("registration_suspended") is True
        and observation.get("active_sessions") == 0
        and observation.get("bearer_replay_denied") is True
        and observation.get("auth_cookie_clear") is True
        and observation.get("flow_cookie_clear") is True
        and _cookie_contract_observation_passes(
            observation.get("cookie_contract")
        )
        and observation.get("atomic_rollback_restores_all") is True
        and observation.get("legacy_accepted_cases") == 2
        and observation.get("legacy_accounts_frozen") == 2
        and observation.get("legacy_registrations_frozen") == 2
        and observation.get("legacy_active_sessions") == 0
        and observation.get("legacy_idempotent_second_pass") is True
    )


_RACE_OBSERVATION_KEYS = {
    "workers",
    "backend_count",
    "pg_lock_wait_observed",
    "transactions_terminal",
    "active_sessions",
    "linearizable_outcome_exact",
    "session_resurrections",
    "reusable_old_bearers",
    "orphan_links",
    "split_commits",
    "timeouts",
    "state_constraints_valid",
}
_REGISTRATION_RETENTION_RACE_KEYS = _RACE_OBSERVATION_KEYS | {
    "shared_recovery_sessions",
    "shared_login_attempts",
    "shared_auth_sessions",
    "recovery_rows_flushed_before_auth_sweep",
    "canonical_lock_order_observed",
}


def _race_case_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(observation, _RACE_OBSERVATION_KEYS)
        and all(
            _is_exact_int(observation.get(key))
            for key in (
                "workers",
                "backend_count",
                "transactions_terminal",
                "active_sessions",
                "session_resurrections",
                "reusable_old_bearers",
                "orphan_links",
                "split_commits",
                "timeouts",
            )
        )
        and observation.get("workers") == 2
        and observation.get("backend_count") == 2
        and observation.get("pg_lock_wait_observed") is True
        and observation.get("transactions_terminal") == 2
        and observation.get("active_sessions") in {0, 1}
        and observation.get("linearizable_outcome_exact") is True
        and observation.get("session_resurrections") == 0
        and observation.get("reusable_old_bearers") == 0
        and observation.get("orphan_links") == 0
        and observation.get("split_commits") == 0
        and observation.get("timeouts") == 0
        and observation.get("state_constraints_valid") is True
    )


def _registration_retention_race_case_passes(
    observation: Mapping[str, Any],
) -> bool:
    common = {
        key: observation.get(key)
        for key in _RACE_OBSERVATION_KEYS
    }
    return bool(
        _exact_keys(observation, _REGISTRATION_RETENTION_RACE_KEYS)
        and _race_case_passes(common)
        and _is_exact_int(observation.get("shared_recovery_sessions"))
        and _is_exact_int(observation.get("shared_login_attempts"))
        and _is_exact_int(observation.get("shared_auth_sessions"))
        and observation.get("shared_recovery_sessions") == 1
        and observation.get("shared_login_attempts") == 1
        and observation.get("shared_auth_sessions") == 1
        and observation.get("recovery_rows_flushed_before_auth_sweep") is True
        and observation.get("canonical_lock_order_observed") is True
    )


def _concurrency_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        tuple(observation) == REQUIRED_RACE_CASES
        and all(
            (
                _registration_retention_race_case_passes(observation[name])
                if name in REGISTRATION_RETENTION_RACE_CASES
                else _race_case_passes(observation[name])
            )
            for name in REQUIRED_RACE_CASES
        )
    )


def _audit_observation_passes(observation: Mapping[str, Any]) -> bool:
    expected = {
        "action_exact",
        "resource_type_exact",
        "aggregate_keys_exact",
        "aggregate_integer_counts",
        "zero_count_run_has_no_event",
        "identifiers_absent",
        "contact_data_absent",
        "bearers_absent",
        "row_hashes_absent",
    }
    return bool(
        _exact_keys(observation, expected)
        and all(observation.get(key) is True for key in expected)
    )


def _scratch_cleanup_observation_passes(
    observation: Mapping[str, Any],
) -> bool:
    expected = {
        "created",
        "removed",
        "cleanup_failed",
        "all_created_removed",
        "inventory_match",
        "baseline_count",
        "final_count",
        "purposes",
    }
    return bool(
        _exact_keys(observation, expected)
        and all(
            _is_exact_int(observation.get(key))
            for key in (
                "created",
                "removed",
                "cleanup_failed",
                "baseline_count",
                "final_count",
            )
        )
        and observation.get("created") == 3
        and observation.get("removed") == 3
        and observation.get("cleanup_failed") == 0
        and observation.get("all_created_removed") is True
        and observation.get("inventory_match") is True
        and observation.get("baseline_count", -1) >= 0
        and observation.get("final_count") == observation.get("baseline_count")
        and observation.get("purposes")
        == ["migration_lifecycle", "migration_populated", "behavior"]
    )


def _harness_observation_passes(observation: Mapping[str, Any]) -> bool:
    expected = {
        "mutants",
        "mutant_inventory",
        "privacy_scanned",
        "privacy_findings",
        "scratch",
        "behavior_adapter_frozen",
        "native_postgres_executed",
    }
    mutants = observation.get("mutants")
    mutant_inventory = observation.get("mutant_inventory")
    scratch = observation.get("scratch")
    return bool(
        _exact_keys(observation, expected)
        and isinstance(mutants, Mapping)
        and tuple(mutants) == REQUIRED_MUTANT_IDS
        and all(value is True for value in mutants.values())
        and isinstance(mutant_inventory, Mapping)
        and _mutant_inventory_observation_passes(mutant_inventory)
        and dict(mutant_inventory) == _mutant_inventory(mutants)
        and observation.get("privacy_scanned") is True
        and _is_exact_int(observation.get("privacy_findings"))
        and observation.get("privacy_findings") == 0
        and isinstance(scratch, Mapping)
        and _scratch_cleanup_observation_passes(scratch)
        and observation.get("behavior_adapter_frozen") is True
        and observation.get("native_postgres_executed") is True
    )


def _mutant_inventory(results: Mapping[str, Any]) -> dict[str, int]:
    """Return honest named-versus-distinct seeded-probe accounting."""

    named_killed = sum(value is True for value in results.values())
    distinct_killed = sum(
        results.get(identifier) is True for identifier in DISTINCT_MUTANT_IDS
    )
    return {
        "named_probe_ids": len(REQUIRED_MUTANT_IDS),
        "distinct_probe_variants": len(DISTINCT_MUTANT_IDS),
        "duplicate_aliases": len(MUTANT_ALIAS_OF),
        "killed_named_probe_ids": named_killed,
        "killed_distinct_probe_variants": distinct_killed,
    }


def _mutant_inventory_observation_passes(
    observation: Mapping[str, Any],
) -> bool:
    expected_keys = set(EXPECTED_MUTANT_INVENTORY)
    return bool(
        _exact_keys(observation, expected_keys)
        and all(_is_exact_int(observation.get(key)) for key in expected_keys)
        and dict(observation) == EXPECTED_MUTANT_INVENTORY
        and observation["named_probe_ids"]
        == observation["distinct_probe_variants"]
        + observation["duplicate_aliases"]
        and set(MUTANT_ALIAS_OF).issubset(REQUIRED_MUTANT_IDS)
        and set(MUTANT_ALIAS_OF.values()).issubset(DISTINCT_MUTANT_IDS)
        and not set(MUTANT_ALIAS_OF.values()).intersection(MUTANT_ALIAS_OF)
    )


def _assertion(identifier: str, passed: bool, **metrics: Any) -> dict[str, Any]:
    return {
        "id": identifier,
        "passed": passed if _is_exact_bool(passed) else False,
        "metrics": metrics,
    }


def _evaluate_assertions(assertions: list[Mapping[str, Any]]) -> dict[str, Any]:
    identifiers = [str(item.get("id", "")) for item in assertions]
    expected = list(REQUIRED_ASSERTION_IDS)
    missing = [identifier for identifier in expected if identifier not in identifiers]
    extra = [identifier for identifier in identifiers if identifier not in expected]
    duplicate = len(identifiers) - len(set(identifiers))
    exact_inventory = identifiers == expected and duplicate == 0
    failed = [
        str(item.get("id", ""))
        for item in assertions
        if item.get("passed") is not True
    ]
    return {
        "exact_inventory": exact_inventory,
        "required": len(expected),
        "passed": sum(item.get("passed") is True for item in assertions),
        "failed": failed,
        "inventory_failures": {
            "missing": len(missing),
            "extra": len(extra),
            "duplicate": duplicate,
            "reordered": bool(
                not missing
                and not extra
                and duplicate == 0
                and identifiers != expected
            ),
        },
        "overall_pass": bool(exact_inventory and not failed),
    }


def _privacy_findings(value: Any) -> list[str]:
    """Find identifying or secret-shaped material in aggregate evidence."""

    findings: list[str] = []

    def visit(item: Any, path: str = "") -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key).casefold()
                child_path = f"{path}.{key_text}" if path else key_text
                if key_text in _FORBIDDEN_REPORT_KEYS:
                    findings.append(f"forbidden_key:{child_path}")
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")

    visit(value)
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"))
    for label, pattern in (
        ("uuid", _UUID_TEXT),
        ("email", _EMAIL_TEXT),
        ("mobile", _MOBILE_TEXT),
        ("date", _DATE_TEXT),
        ("url", _URL_TEXT),
        ("hash64", _HEX64_TEXT),
        ("cookie_value", _COOKIE_VALUE_TEXT),
    ):
        if pattern.search(serialized):
            findings.append(f"pattern:{label}")
    return findings


def _historical_migration_inventory(
    repo_root: Path | None = None,
) -> dict[str, bool]:
    """Return independent filename, digest and ledger-cross-check verdicts."""

    root = BACKEND.parent if repo_root is None else repo_root
    versions = root / "backend/app/db/migrations/versions"
    ledger_path = root / "backend/app/db/migrations/MIGRATION_SHA256_LEDGER.json"
    result = {
        "file_inventory_exact": False,
        "hash_inventory_exact": False,
        "ledger_crosscheck_exact": False,
        "pinned_head_hash_exact": False,
        "application_head_hash_exact": False,
        "forward_application_head_exact": False,
    }
    try:
        version_files = {
            path.name
            for path in versions.glob("*.py")
            if path.name != "__init__.py"
        }
        result["file_inventory_exact"] = (
            version_files
            == set(HISTORICAL_MIGRATION_SHA256)
            | {PINNED_HEAD_FILENAME, APPLICATION_HEAD_FILENAME}
        )
        result["hash_inventory_exact"] = bool(
            result["file_inventory_exact"]
            and all(
                hashlib.sha256((versions / filename).read_bytes()).hexdigest()
                == expected
                for filename, expected in HISTORICAL_MIGRATION_SHA256.items()
            )
        )
        result["pinned_head_hash_exact"] = bool(
            result["file_inventory_exact"]
            and hashlib.sha256((versions / PINNED_HEAD_FILENAME).read_bytes()).hexdigest()
            == PINNED_HEAD_SHA256
        )
        result["application_head_hash_exact"] = bool(
            result["file_inventory_exact"]
            and hashlib.sha256(
                (versions / APPLICATION_HEAD_FILENAME).read_bytes()
            ).hexdigest()
            == APPLICATION_HEAD_SHA256
        )
        forward_tree = ast.parse(
            (versions / APPLICATION_HEAD_FILENAME).read_text(encoding="utf-8")
        )
        assignments: dict[str, object] = {}
        for node in forward_tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        assignments[target.id] = ast.literal_eval(node.value)
        result["forward_application_head_exact"] = bool(
            result["file_inventory_exact"]
            and result["application_head_hash_exact"]
            and assignments
            == {"revision": APPLICATION_HEAD, "down_revision": PINNED_HEAD}
        )
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        migrations = ledger["migrations"]
        ledger_manifest = {
            Path(str(item["path"])).name: str(item["sha256"])
            for item in migrations
        }
        result["ledger_crosscheck_exact"] = bool(
            ledger.get("schemaVersion") == 1
            and ledger.get("baseline", {}).get("migrationCount") == 15
            and len(migrations) == 15
            and [item.get("ordinal") for item in migrations] == list(range(1, 16))
            and ledger_manifest
            == dict(tuple(HISTORICAL_MIGRATION_SHA256.items())[:15])
        )
    except (KeyError, OSError, TypeError, ValueError):
        return result
    return result


def _historical_migration_bytes_unchanged(repo_root: Path | None = None) -> bool:
    """Verify exact immutable 0001..0019 filename and byte inventory."""

    inventory = _historical_migration_inventory(repo_root)
    return bool(inventory and all(inventory.values()))


_AUDIT_EVENTS_MUTATION_SQL = re.compile(
    r"\b(?:update\s+audit_events|delete\s+from\s+audit_events)\b",
    re.IGNORECASE,
)


def _static_string_expression(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string_expression(node.left)
        right = _static_string_expression(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _gate_preserves_append_only_audit_events(source: str | None = None) -> bool:
    """Reject any gate SQL that UPDATEs or DELETEs append-only audit evidence."""

    if source is None:
        try:
            source = Path(__file__).read_text(encoding="utf-8")
        except OSError:
            return False
    if _AUDIT_EVENTS_MUTATION_SQL.search(source) is not None:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function_name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if function_name != "text":
            continue
        argument = _static_string_expression(node.args[0])
        if (
            argument is not None
            and _AUDIT_EVENTS_MUTATION_SQL.search(argument) is not None
        ):
            return False
    return True


def _run_alembic(scratch_url: str, *arguments: str) -> dict[str, Any]:
    """Run Alembic without retaining stdout, stderr, URL, or database name."""

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
        check=False,
    )
    return {"arguments": list(arguments), "returncode": result.returncode}


_AUTH_TABLES = ("login_attempts", "auth_sessions")
_LIFECYCLE_TABLES = (
    "users",
    "student_registrations",
    "otp_challenges",
    "login_attempts",
    "auth_sessions",
    "data_subject_requests",
    "deletion_jobs",
    "audit_events",
)


def _stable_catalog_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(
            sorted((str(key), _stable_catalog_value(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_stable_catalog_value(item) for item in value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return " ".join(str(value).split())


def _schema_digest(engine: Engine, tables: tuple[str, ...] = _AUTH_TABLES) -> str:
    """Private exact reflected schema fingerprint; never emitted as evidence."""

    inspector = inspect(engine)
    available = set(inspector.get_table_names())
    snapshot: list[Any] = []
    for table in tables:
        if table not in available:
            snapshot.append((table, "absent"))
            continue
        snapshot.append(
            (
                table,
                tuple(
                    (
                        column.get("name"),
                        str(column.get("type")),
                        bool(column.get("nullable")),
                        str(column.get("default")),
                    )
                    for column in inspector.get_columns(table)
                ),
                _stable_catalog_value(inspector.get_pk_constraint(table)),
                tuple(
                    sorted(
                        (
                            _stable_catalog_value(item)
                            for item in inspector.get_unique_constraints(table)
                        ),
                        key=repr,
                    )
                ),
                tuple(
                    sorted(
                        (
                            _stable_catalog_value(item)
                            for item in inspector.get_foreign_keys(table)
                        ),
                        key=repr,
                    )
                ),
                tuple(
                    sorted(
                        (
                            _stable_catalog_value(item)
                            for item in inspector.get_check_constraints(table)
                        ),
                        key=repr,
                    )
                ),
                tuple(
                    sorted(
                        (
                            _stable_catalog_value(item)
                            for item in inspector.get_indexes(table)
                        ),
                        key=repr,
                    )
                ),
            )
        )
    return hashlib.sha256(repr(snapshot).encode("utf-8")).hexdigest()


def _rows_digest(engine: Engine, tables: tuple[str, ...] = _LIFECYCLE_TABLES) -> str:
    """Private equality fingerprint over every column of the selected tables."""

    inspector = inspect(engine)
    available = set(inspector.get_table_names())
    snapshot: list[Any] = []
    with engine.connect() as connection:
        for table in tables:
            if table not in available:
                snapshot.append((table, "absent"))
                continue
            columns = tuple(
                str(column["name"]) for column in inspector.get_columns(table)
            )
            selected = ", ".join(f'"{column}"' for column in columns)
            rows = tuple(
                tuple(_stable_catalog_value(value) for value in row)
                for row in connection.execute(
                    text(f'SELECT {selected} FROM "{table}" ORDER BY 1')
                )
            )
            snapshot.append((table, columns, rows))
    return hashlib.sha256(repr(snapshot).encode("utf-8")).hexdigest()


def _current_revision(engine: Engine) -> str | None:
    try:
        with engine.connect() as connection:
            value = connection.scalar(text("SELECT version_num FROM alembic_version"))
    except SQLAlchemyError:
        return None
    return None if value is None else str(value)


def _revision_row_count(engine: Engine) -> int:
    try:
        with engine.connect() as connection:
            return int(
                connection.scalar(text("SELECT count(*) FROM alembic_version")) or 0
            )
    except SQLAlchemyError:
        return -1


def _postflight_failure_rolls_back(engine: Engine) -> bool:
    """Inject a failure at 0020 postflight and prove all prior DDL/data rolls back."""

    migration = importlib.import_module(
        "app.db.migrations.versions.0020_auth_retention_lifecycle"
    )
    before_schema = _schema_digest(engine, _LIFECYCLE_TABLES)
    before_rows = _rows_digest(engine)
    before_revision = _current_revision(engine)
    original_op = migration.op
    original_validator = migration._validate_postflight
    called = False

    def reject_after_ddl(_bind: Any, *, head: bool) -> None:
        nonlocal called
        called = head is True
        raise migration.AuthRetentionMigrationError(
            "NYAY-19 injected postflight failure"
        )

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                context = MigrationContext.configure(connection)
                migration.op = Operations(context)
                migration._validate_postflight = reject_after_ddl
                try:
                    migration.upgrade()
                except migration.AuthRetentionMigrationError:
                    pass
                else:
                    return False
            finally:
                transaction.rollback()
    except (SQLAlchemyError, TypeError, ValueError):
        return False
    finally:
        migration.op = original_op
        migration._validate_postflight = original_validator
    return bool(
        called
        and _current_revision(engine) == before_revision == PREVIOUS_REVISION
        and _schema_digest(engine, _LIFECYCLE_TABLES) == before_schema
        and _rows_digest(engine) == before_rows
    )


def _seed_invalid_parent_attempt(engine: Engine) -> uuid.UUID:
    now = datetime.now(timezone.utc)
    attempt_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO login_attempts "
                "(id, opaque_id, lookup_hash, status, expires_at, consumed_at, "
                "created_at, updated_at, deleted_at, metadata_json) VALUES "
                "(:id, :opaque_id, :lookup_hash, 'pending', :expires_at, NULL, "
                ":created_at, :updated_at, NULL, NULL)"
            ),
            {
                "id": attempt_id,
                "opaque_id": "z" * 32,
                "lookup_hash": "a" * 64,
                "expires_at": now + timedelta(minutes=5),
                "created_at": now,
                "updated_at": now,
            },
        )
    return attempt_id


def _remove_invalid_parent_attempt(
    engine: Engine, attempt_id: uuid.UUID
) -> bool:
    """Remove only the hostile row owned by the lifecycle probe."""

    with engine.begin() as connection:
        removed = connection.execute(
            text("DELETE FROM login_attempts WHERE id = :id"),
            {"id": attempt_id},
        )
    return removed.rowcount == 1


_ERASED_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_ERASED_LOGIN_ID = uuid.UUID("00000000-0000-4000-8000-000000000019")
_ERASED_SESSION_ID = uuid.UUID("00000000-0000-4000-8000-000000000020")


def _seed_erased_auth_tombstones(engine: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert exact link-free 0020 tombstones for marker-free downgrade refusal."""

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO login_attempts "
                "(id, opaque_id, lookup_hash, registration_id, challenge_id, "
                "status, expires_at, consumed_at, created_at, updated_at, "
                "deleted_at, metadata_json) VALUES "
                "(:id, :opaque_id, :lookup_hash, NULL, NULL, 'erased', :epoch, "
                ":epoch, :epoch, :epoch, :epoch, NULL)"
            ),
            {
                "id": _ERASED_LOGIN_ID,
                "opaque_id": "c" * 64,
                "lookup_hash": "d" * 64,
                "epoch": _ERASED_EPOCH,
            },
        )
        connection.execute(
            text(
                "INSERT INTO auth_sessions "
                "(id, user_id, token_hash, status, expires_at, last_seen_at, "
                "revoked_at, created_at, updated_at, deleted_at, metadata_json) "
                "VALUES (:id, NULL, :token_hash, 'erased', :epoch, :epoch, "
                ":epoch, :epoch, :epoch, :epoch, NULL)"
            ),
            {
                "id": _ERASED_SESSION_ID,
                "token_hash": "e" * 64,
                "epoch": _ERASED_EPOCH,
            },
        )
    return _ERASED_LOGIN_ID, _ERASED_SESSION_ID


def _erased_auth_shapes_exact(
    engine: Engine,
    *,
    attempt_id: uuid.UUID,
    session_id: uuid.UUID,
) -> tuple[bool, bool]:
    with engine.connect() as connection:
        erased_login = connection.execute(
            text(
                "SELECT opaque_id, lookup_hash, registration_id, challenge_id, "
                "status, expires_at, consumed_at, created_at, updated_at, "
                "deleted_at, metadata_json FROM login_attempts WHERE id = :id"
            ),
            {"id": attempt_id},
        ).one()
        erased_session = connection.execute(
            text(
                "SELECT user_id, token_hash, status, expires_at, last_seen_at, "
                "revoked_at, created_at, updated_at, deleted_at, metadata_json "
                "FROM auth_sessions WHERE id = :id"
            ),
            {"id": session_id},
        ).one()
    login_exact = bool(
        erased_login[0] == "c" * 64
        and erased_login[1] == "d" * 64
        and erased_login[2] is None
        and erased_login[3] is None
        and erased_login[4] == "erased"
        and all(
            _timestamp_equal(value, _ERASED_EPOCH)
            for value in erased_login[5:10]
        )
        and erased_login[10] is None
    )
    session_exact = bool(
        erased_session[0] is None
        and erased_session[1] == "e" * 64
        and erased_session[2] == "erased"
        and all(
            _timestamp_equal(value, _ERASED_EPOCH)
            for value in erased_session[3:9]
        )
        and erased_session[9] is None
    )
    return login_exact, session_exact


def _run_migration_lifecycle_probe(scratch_url: str) -> dict[str, Any]:
    """Exercise exact 0019↔0020 lifecycle and transactional refusal paths."""

    inventory = _historical_migration_inventory()
    parent = _run_alembic(scratch_url, "upgrade", PREVIOUS_REVISION)
    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        if (
            parent["returncode"] != 0
            or _current_revision(engine) != PREVIOUS_REVISION
            or _revision_row_count(engine) != 1
        ):
            raise ProductGateFailure("0019 migration lifecycle setup failed")
        parent_schema = _schema_digest(engine, _LIFECYCLE_TABLES)
        parent_rows = _rows_digest(engine)
        injected_rollback = _postflight_failure_rolls_back(engine)

        head = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        head_revision = _current_revision(engine)
        head_rows = _revision_row_count(engine)
        schema_observation = _exact_auth_schema_observation(
            inspect(engine), dialect_name="postgresql", engine=engine
        )
        downgrade = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        roundtrip_schema = _schema_digest(engine, _LIFECYCLE_TABLES) == parent_schema
        roundtrip_rows = _rows_digest(engine) == parent_rows

        invalid_attempt_id = _seed_invalid_parent_attempt(engine)
        invalid_schema = _schema_digest(engine, _LIFECYCLE_TABLES)
        invalid_rows = _rows_digest(engine)
        invalid = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        invalid_unchanged = bool(
            invalid["returncode"] != 0
            and _current_revision(engine) == PREVIOUS_REVISION
            and _revision_row_count(engine) == 1
            and _schema_digest(engine, _LIFECYCLE_TABLES) == invalid_schema
            and _rows_digest(engine) == invalid_rows
        )
        if not invalid_unchanged:
            raise ProductGateFailure("invalid parent upgrade refusal was not atomic")
        if not _remove_invalid_parent_attempt(engine, invalid_attempt_id):
            raise ProductGateFailure("hostile lifecycle row cleanup was not exact")
        if (
            _current_revision(engine) != PREVIOUS_REVISION
            or _schema_digest(engine, _LIFECYCLE_TABLES) != parent_schema
            or _rows_digest(engine) != parent_rows
        ):
            raise ProductGateFailure("marker-free parent state was not restored")

        erased_head = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        if (
            erased_head["returncode"] != 0
            or _current_revision(engine) != PINNED_HEAD
            or _revision_row_count(engine) != 1
        ):
            raise ProductGateFailure("erased downgrade setup upgrade failed")
        erased_attempt_id, erased_session_id = _seed_erased_auth_tombstones(engine)
        erased_login_shape, erased_session_shape = _erased_auth_shapes_exact(
            engine,
            attempt_id=erased_attempt_id,
            session_id=erased_session_id,
        )
        if not (erased_login_shape and erased_session_shape):
            raise ProductGateFailure("erased downgrade tombstones were not exact")
        erased_schema = _schema_digest(engine, _LIFECYCLE_TABLES)
        erased_rows = _rows_digest(engine)
        erased_revision = _current_revision(engine)
        erased_refusal = _run_alembic(
            scratch_url, "downgrade", PREVIOUS_REVISION
        )
        erased_revision_unchanged = bool(
            erased_refusal["returncode"] != 0
            and erased_revision == PINNED_HEAD
            and _current_revision(engine) == erased_revision
            and _revision_row_count(engine) == 1
        )
        erased_schema_unchanged = (
            _schema_digest(engine, _LIFECYCLE_TABLES) == erased_schema
        )
        erased_rows_unchanged = _rows_digest(engine) == erased_rows
        return {
            "observation": {
                "historical_bytes_immutable": bool(
                    inventory.get("ledger_crosscheck_exact")
                    and inventory.get("hash_inventory_exact")
                ),
                "historical_file_inventory_exact": bool(
                    inventory.get("file_inventory_exact")
                ),
                "historical_hash_inventory_exact": bool(
                    inventory.get("hash_inventory_exact")
                ),
                "post_ddl_exact_head_validation": bool(
                    _schema_observation_passes(schema_observation)
                ),
                "post_ddl_validation_failure_rolled_back": injected_rollback,
                "pinned_release_exact": bool(
                    inventory.get("pinned_head_hash_exact")
                    and inventory.get("forward_application_head_exact")
                    and head_revision == PINNED_HEAD
                    and head_rows == 1
                    and _schema_observation_passes(schema_observation)
                ),
                "parent_upgrade_returncode": int(parent["returncode"]),
                "head_upgrade_returncode": int(head["returncode"]),
                "head_revision_exact": head_revision == PINNED_HEAD,
                "revision_rows": head_rows,
                "parent_schema_roundtrip_exact": bool(
                    downgrade["returncode"] == 0 and roundtrip_schema
                ),
                "parent_rows_roundtrip_exact": bool(
                    downgrade["returncode"] == 0 and roundtrip_rows
                ),
                "invalid_upgrade_refused_unchanged": invalid_unchanged,
            },
            "schema": schema_observation,
            "erased_refusal": {
                "downgrade_refused": erased_revision_unchanged,
                "schema_unchanged": erased_schema_unchanged,
                "rows_unchanged": erased_rows_unchanged,
            },
        }
    finally:
        engine.dispose()


def _seed_parent_account(
    engine: Engine,
    *,
    role: str = "student",
    registrations: int = 1,
    accepted_delete_mode: str | None = None,
    delete_job_count: int = 1,
) -> tuple[uuid.UUID, tuple[uuid.UUID, ...]]:
    """Seed a coherent 0019 account, optionally with accepted delete evidence."""

    user_id = uuid.uuid4()
    registration_ids = tuple(uuid.uuid4() for _ in range(registrations))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, role, status) "
                "VALUES (:id, :role, 'active')"
            ),
            {"id": user_id, "role": role},
        )
        for index, registration_id in enumerate(registration_ids):
            mobile_hash = hashlib.sha256(
                registration_id.bytes + b"mobile"
            ).hexdigest()
            dob_hash = hashlib.sha256(registration_id.bytes + b"dob").hexdigest()
            connection.execute(
                text(
                    "INSERT INTO student_registrations "
                    "(id, user_id, first_name, last_name, mobile_hash, mobile_ct, "
                    "dob_hash, dob_ct, dob_hash_state, key_version, status, is_minor, "
                    "idempotency_key, idempotency_key_legacy) VALUES "
                    "(:id, :user_id, 'Gate', 'Subject', :mobile_hash, :mobile_ct, "
                    ":dob_hash, :dob_ct, 'verified', 'v1', 'active', false, NULL, false)"
                ),
                {
                    "id": registration_id,
                    "user_id": user_id,
                    "mobile_hash": mobile_hash,
                    "mobile_ct": f"v1:gate-mobile-{index}",
                    "dob_hash": dob_hash,
                    "dob_ct": f"v1:gate-dob-{index}",
                },
            )
        if accepted_delete_mode is not None:
            request_id = uuid.uuid4()
            connection.execute(
                text(
                    "INSERT INTO data_subject_requests "
                    "(id, user_id, kind, opaque_id, status, idempotency_key, "
                    "reauth_verified, confirmation_hash) VALUES "
                    "(:id, :user_id, 'delete', :opaque_id, 'pending', "
                    ":idempotency_key, true, :confirmation_hash)"
                ),
                {
                    "id": request_id,
                    "user_id": user_id,
                    "opaque_id": uuid.uuid4().hex,
                    "idempotency_key": f"nyay19-legacy-{request_id.hex}",
                    "confirmation_hash": hashlib.sha256(
                        request_id.bytes + b"confirmation"
                    ).hexdigest(),
                },
            )
            for index in range(delete_job_count):
                connection.execute(
                    text(
                        "INSERT INTO deletion_jobs (id, request_id, status, mode) "
                        "VALUES (:id, :request_id, 'pending', :mode)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "request_id": request_id,
                        "mode": (
                            accepted_delete_mode
                            if index == 0
                            else (
                                "delete"
                                if accepted_delete_mode == "anonymise"
                                else "anonymise"
                            )
                        ),
                    },
                )
    return user_id, registration_ids


def _delete_parent_account_graph(engine: Engine, user_id: uuid.UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM deletion_jobs WHERE request_id IN "
                "(SELECT id FROM data_subject_requests WHERE user_id = :user_id)"
            ),
            {"user_id": user_id},
        )
        connection.execute(
            text("DELETE FROM data_subject_requests WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        connection.execute(
            text("DELETE FROM users WHERE id = :user_id"),
            {"user_id": user_id},
        )


def _legacy_corrupt_targets_are_refused(engine: Engine, scratch_url: str) -> bool:
    cases = (
        {"role": "admin", "registrations": 1, "delete_job_count": 1},
        {"role": "student", "registrations": 0, "delete_job_count": 1},
        {"role": "student", "registrations": 2, "delete_job_count": 1},
        {"role": "student", "registrations": 1, "delete_job_count": 0},
        {"role": "student", "registrations": 1, "delete_job_count": 2},
    )
    outcomes: list[bool] = []
    for case in cases:
        user_id, _ = _seed_parent_account(
            engine,
            role=case["role"],
            registrations=case["registrations"],
            accepted_delete_mode="anonymise",
            delete_job_count=case["delete_job_count"],
        )
        before_schema = _schema_digest(engine, _LIFECYCLE_TABLES)
        before_rows = _rows_digest(engine)
        attempt = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        outcomes.append(
            bool(
                attempt["returncode"] != 0
                and _current_revision(engine) == PREVIOUS_REVISION
                and _schema_digest(engine, _LIFECYCLE_TABLES) == before_schema
                and _rows_digest(engine) == before_rows
            )
        )
        _delete_parent_account_graph(engine, user_id)
    return len(outcomes) == 5 and all(outcomes)


def _insert_parent_auth_history(
    engine: Engine,
    *,
    legacy_one: tuple[uuid.UUID, uuid.UUID],
    legacy_two: tuple[uuid.UUID, uuid.UUID],
    ordinary: tuple[uuid.UUID, uuid.UUID],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    attempt_ids = tuple(uuid.uuid4() for _ in range(3))
    session_ids = tuple(uuid.uuid4() for _ in range(3))
    attempt_tokens = tuple(
        hashlib.sha256(value.bytes + b"attempt").hexdigest()
        for value in attempt_ids
    )
    session_tokens = tuple(
        hashlib.sha256(value.bytes + b"session").hexdigest()
        for value in session_ids
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO login_attempts "
                "(id, opaque_id, lookup_hash, registration_id, challenge_id, "
                "status, expires_at, consumed_at, created_at, updated_at, "
                "deleted_at, metadata_json) VALUES "
                "(:id, :opaque_id, :lookup_hash, :registration_id, NULL, "
                "'expired', :expires_at, NULL, :created_at, :updated_at, NULL, NULL)"
            ),
            {
                "id": attempt_ids[0],
                "opaque_id": uuid.uuid4().hex,
                "lookup_hash": attempt_tokens[0],
                "registration_id": legacy_one[1],
                "expires_at": now - timedelta(days=2),
                "created_at": now - timedelta(days=3),
                "updated_at": now - timedelta(days=2),
            },
        )
        connection.execute(
            text(
                "INSERT INTO login_attempts "
                "(id, opaque_id, lookup_hash, registration_id, challenge_id, "
                "status, expires_at, consumed_at, created_at, updated_at, "
                "deleted_at, metadata_json) VALUES "
                "(:id, :opaque_id, :lookup_hash, :registration_id, NULL, "
                "'consumed', :expires_at, :consumed_at, :created_at, :updated_at, "
                "NULL, NULL)"
            ),
            {
                "id": attempt_ids[1],
                "opaque_id": uuid.uuid4().hex,
                "lookup_hash": attempt_tokens[1],
                "registration_id": legacy_two[1],
                "expires_at": now + timedelta(minutes=5),
                "consumed_at": now,
                "created_at": now - timedelta(minutes=2),
                "updated_at": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO login_attempts "
                "(id, opaque_id, lookup_hash, registration_id, challenge_id, "
                "status, expires_at, consumed_at, created_at, updated_at, "
                "deleted_at, metadata_json) VALUES "
                "(:id, :opaque_id, :lookup_hash, NULL, NULL, 'pending', "
                ":expires_at, NULL, :created_at, :updated_at, NULL, NULL)"
            ),
            {
                "id": attempt_ids[2],
                "opaque_id": uuid.uuid4().hex,
                "lookup_hash": attempt_tokens[2],
                "expires_at": now + timedelta(minutes=5),
                "created_at": now,
                "updated_at": now,
            },
        )
        for index, (user_id, status, expires_at, revoked_at) in enumerate(
            (
                (legacy_one[0], "active", now + timedelta(days=1), None),
                (legacy_two[0], "expired", now - timedelta(days=1), None),
                (ordinary[0], "active", now + timedelta(days=1), None),
            )
        ):
            connection.execute(
                text(
                    "INSERT INTO auth_sessions "
                    "(id, user_id, token_hash, status, expires_at, last_seen_at, "
                    "revoked_at, created_at, updated_at, deleted_at, metadata_json) "
                    "VALUES (:id, :user_id, :token_hash, :status, :expires_at, "
                    ":last_seen_at, :revoked_at, :created_at, :updated_at, NULL, NULL)"
                ),
                {
                    "id": session_ids[index],
                    "user_id": user_id,
                    "token_hash": session_tokens[index],
                    "status": status,
                    "expires_at": expires_at,
                    "last_seen_at": now - timedelta(minutes=1),
                    "revoked_at": revoked_at,
                    "created_at": now - timedelta(days=2),
                    "updated_at": now - timedelta(minutes=1),
                },
            )
    return {
        "attempt_ids": attempt_ids,
        "session_ids": session_ids,
        "attempt_tokens": attempt_tokens,
        "session_tokens": session_tokens,
    }


def _timestamp_equal(left: Any, right: Any) -> bool:
    if not isinstance(left, datetime) or not isinstance(right, datetime):
        return False
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def _run_populated_migration_probe(scratch_url: str) -> dict[str, Any]:
    """Prove populated backfills, legacy freeze/idempotence, and downgrade refusal."""

    parent = _run_alembic(scratch_url, "upgrade", PREVIOUS_REVISION)
    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        if parent["returncode"] != 0:
            raise ProductGateFailure("populated migration setup failed")
        corrupt_refused = _legacy_corrupt_targets_are_refused(engine, scratch_url)
        legacy_one_user, legacy_one_regs = _seed_parent_account(
            engine, accepted_delete_mode="anonymise"
        )
        legacy_two_user, legacy_two_regs = _seed_parent_account(
            engine, accepted_delete_mode="delete"
        )
        ordinary_user, ordinary_regs = _seed_parent_account(engine)
        seeded = _insert_parent_auth_history(
            engine,
            legacy_one=(legacy_one_user, legacy_one_regs[0]),
            legacy_two=(legacy_two_user, legacy_two_regs[0]),
            ordinary=(ordinary_user, ordinary_regs[0]),
        )
        upgraded = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        if upgraded["returncode"] != 0 or _current_revision(engine) != PINNED_HEAD:
            raise ProductGateFailure("populated 0020 migration failed")

        with engine.connect() as connection:
            login_rows = int(
                connection.scalar(text("SELECT count(*) FROM login_attempts")) or 0
            )
            session_rows = int(
                connection.scalar(text("SELECT count(*) FROM auth_sessions")) or 0
            )
            expired_attempt = connection.execute(
                text(
                    "SELECT status, expires_at, consumed_at FROM login_attempts "
                    "WHERE id = :id"
                ),
                {"id": seeded["attempt_ids"][0]},
            ).one()
            expired_session = connection.execute(
                text(
                    "SELECT status, expires_at, revoked_at FROM auth_sessions "
                    "WHERE id = :id"
                ),
                {"id": seeded["session_ids"][1]},
            ).one()
            ordinary_attempt = connection.execute(
                text(
                    "SELECT status, lookup_hash FROM login_attempts WHERE id = :id"
                ),
                {"id": seeded["attempt_ids"][2]},
            ).one()
            ordinary_session = connection.execute(
                text(
                    "SELECT status, user_id, token_hash FROM auth_sessions WHERE id = :id"
                ),
                {"id": seeded["session_ids"][2]},
            ).one()
            frozen_accounts = int(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM users WHERE id IN (:one, :two) "
                        "AND status = 'suspended'"
                    ),
                    {"one": legacy_one_user, "two": legacy_two_user},
                )
                or 0
            )
            frozen_registrations = int(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM student_registrations "
                        "WHERE user_id IN (:one, :two) AND status = 'suspended'"
                    ),
                    {"one": legacy_one_user, "two": legacy_two_user},
                )
                or 0
            )
            legacy_active = int(
                connection.scalar(
                    text(
                        "SELECT count(*) FROM auth_sessions "
                        "WHERE user_id IN (:one, :two) AND status = 'active'"
                    ),
                    {"one": legacy_one_user, "two": legacy_two_user},
                )
                or 0
            )
            audit_rows = list(
                connection.execute(
                    text(
                        "SELECT actor_user_id, action, resource_type, resource_id, "
                        "before_state, after_state FROM audit_events WHERE "
                        "action = 'student.auth.deletion_backfill_frozen'"
                    )
                ).mappings()
            )

        audit_exact = False
        if len(audit_rows) == 1:
            audit_row = audit_rows[0]
            after_state = audit_row["after_state"]
            audit_exact = bool(
                audit_row["actor_user_id"] is None
                and audit_row["resource_id"] is None
                and audit_row["action"]
                == "student.auth.deletion_backfill_frozen"
                and audit_row["resource_type"] == "auth_security_history"
                and audit_row["before_state"] is None
                and isinstance(after_state, Mapping)
                and set(after_state) == {"accounts", "registrations", "sessions"}
                and all(type(value) is int for value in after_state.values())
                and after_state
                == {"accounts": 2, "registrations": 2, "sessions": 1}
            )

        before_second_pass = _rows_digest(engine)
        migration = importlib.import_module(
            "app.db.migrations.versions.0020_auth_retention_lifecycle"
        )
        with engine.begin() as connection:
            migration._freeze_accepted_legacy_deletions(connection)
        idempotent_second_pass = _rows_digest(engine) == before_second_pass

        marker_schema = _schema_digest(engine, _LIFECYCLE_TABLES)
        marker_rows = _rows_digest(engine)
        marker_refusal = _run_alembic(
            scratch_url, "downgrade", PREVIOUS_REVISION
        )
        marker_schema_unchanged = bool(
            marker_refusal["returncode"] != 0
            and _current_revision(engine) == PINNED_HEAD
            and _schema_digest(engine, _LIFECYCLE_TABLES) == marker_schema
        )
        marker_rows_unchanged = _rows_digest(engine) == marker_rows

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE login_attempts SET opaque_id = :opaque_id, "
                    "lookup_hash = :lookup_hash, registration_id = NULL, "
                    "challenge_id = NULL, status = 'erased', expires_at = :epoch, "
                    "consumed_at = :epoch, created_at = :epoch, updated_at = :epoch, "
                    "deleted_at = :epoch, metadata_json = NULL WHERE id = :id"
                ),
                {
                    "id": seeded["attempt_ids"][0],
                    "opaque_id": "c" * 64,
                    "lookup_hash": "d" * 64,
                    "epoch": _ERASED_EPOCH,
                },
            )
            connection.execute(
                text(
                    "UPDATE auth_sessions SET user_id = NULL, token_hash = :token_hash, "
                    "status = 'erased', expires_at = :epoch, last_seen_at = :epoch, "
                    "revoked_at = :epoch, created_at = :epoch, updated_at = :epoch, "
                    "deleted_at = :epoch, metadata_json = NULL WHERE id = :id"
                ),
                {
                    "id": seeded["session_ids"][0],
                    "token_hash": "e" * 64,
                    "epoch": _ERASED_EPOCH,
                },
            )
        erased_login_shape, erased_session_shape = _erased_auth_shapes_exact(
            engine,
            attempt_id=seeded["attempt_ids"][0],
            session_id=seeded["session_ids"][0],
        )

        return {
            "observation": {
                "login_rows": login_rows,
                "session_rows": session_rows,
                "login_expiry_backfilled": bool(
                    expired_attempt[0] == "expired"
                    and _timestamp_equal(expired_attempt[1], expired_attempt[2])
                ),
                "session_revocation_backfilled": bool(
                    expired_session[0] == "expired"
                    and _timestamp_equal(expired_session[1], expired_session[2])
                ),
                "live_rows_preserved": bool(
                    ordinary_attempt
                    == ("pending", seeded["attempt_tokens"][2])
                    and ordinary_session
                    == (
                        "active",
                        ordinary_user,
                        seeded["session_tokens"][2],
                    )
                ),
                "erased_login_shape_exact": erased_login_shape,
                "erased_session_shape_exact": erased_session_shape,
                # These private placeholders are replaced only by the
                # marker-free lifecycle scratch in run_gate.
                "erased_downgrade_refused": False,
                "legacy_delete_corrupt_cases": 5,
                "legacy_delete_preflight_rejects_corrupt_target": corrupt_refused,
                "legacy_delete_downgrade_marker_refuses": bool(
                    marker_schema_unchanged and marker_rows_unchanged
                ),
                "legacy_delete_backfill_aggregate_audit_exact": audit_exact,
                "refusal_schema_unchanged": False,
                "refusal_rows_unchanged": False,
            },
            "legacy": {
                "accepted_cases": 2,
                "accounts_frozen": frozen_accounts,
                "registrations_frozen": frozen_registrations,
                "active_sessions": legacy_active,
                "idempotent_second_pass": idempotent_second_pass,
            },
        }
    finally:
        engine.dispose()


def _runtime_probe(base: URL) -> dict[str, Any]:
    engine = create_engine(base, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            version = connection.scalar(text("SHOW server_version_num"))
            vector_version = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
    except Exception as exc:  # noqa: BLE001 - sanitized runtime failure
        raise Blocked("PostgreSQL runtime could not be inspected") from exc
    finally:
        engine.dispose()
    version_num = int(version)
    return {
        "server_version_num": version_num,
        "postgres_major": version_num // 10000,
        "pgvector_present": bool(vector_version),
    }


_RETENTION_CONFIG_FIELDS = (
    "retention_days_registration_pending",
    "retention_days_registration_inactive",
    "retention_days_otp_challenge",
    "retention_days_recovery_session",
    "retention_days_login_attempt",
    "retention_days_auth_session",
    "retention_days_audit_events",
)


def _run_config_probe() -> dict[str, Any]:
    """Exercise real Settings parsing while retaining only aggregate verdicts."""

    from pydantic import ValidationError

    from app.core.config import Settings
    from app.core.retention import RetentionPolicy

    unset_values = {field: None for field in _RETENTION_CONFIG_FIELDS}
    unset = Settings(_env_file=None, **unset_values)
    empty = Settings(
        _env_file=None,
        **{field: "" for field in _RETENTION_CONFIG_FIELDS},
    )
    documented = Settings(_env_file=BACKEND.parent / ".env.example")

    rejected: list[bool] = []
    for field in ("retention_days_login_attempt", "retention_days_auth_session"):
        for unsafe in (" ", "00", "+1", "1.0", True, 0, 36_501):
            try:
                Settings(_env_file=None, **{**unset_values, field: unsafe})
            except (ValidationError, ValueError):
                rejected.append(True)
            else:
                rejected.append(False)
    try:
        minimum = Settings(
            _env_file=None,
            **{**unset_values, "retention_days_login_attempt": "1"},
        ).retention_days_login_attempt
        maximum = Settings(
            _env_file=None,
            **{**unset_values, "retention_days_auth_session": "36500"},
        ).retention_days_auth_session
    except (ValidationError, ValueError):
        minimum = None
        maximum = None
    accepted_modes = []
    for mode in ("anonymise", "delete"):
        try:
            candidate = Settings(
                _env_file=None,
                **unset_values,
                retention_mode=mode,
            )
        except (ValidationError, ValueError):
            continue
        if candidate.retention_mode == mode:
            accepted_modes.append(mode)
    try:
        Settings(
            _env_file=None,
            **unset_values,
            retention_mode="archive",
        )
    except (ValidationError, ValueError):
        unknown_mode_rejected = True
    else:
        unknown_mode_rejected = False

    policy = RetentionPolicy(
        None,
        None,
        None,
        None,
        None,
        "anonymise",
        login_attempt_days=unset.retention_days_login_attempt,
        auth_session_days=unset.retention_days_auth_session,
    )
    return {
        "unset_login_window_is_none": unset.retention_days_login_attempt is None,
        "unset_session_window_is_none": unset.retention_days_auth_session is None,
        "empty_login_env_is_none": empty.retention_days_login_attempt is None,
        "empty_session_env_is_none": empty.retention_days_auth_session is None,
        "all_documented_empty_env_is_none": all(
            getattr(documented, field) is None for field in _RETENTION_CONFIG_FIELDS
        ),
        "noncanonical_text_rejected": bool(len(rejected) == 14 and all(rejected)),
        "unset_windows_noop": bool(
            policy.login_attempt_days is None and policy.auth_session_days is None
        ),
        "minimum_window_days": minimum,
        "maximum_window_days": maximum,
        "accepted_modes": accepted_modes if unknown_mode_rejected else [],
        "invalid_values_rejected_before_mutation": bool(
            len(rejected) == 14 and all(rejected) and unknown_mode_rejected
        ),
        "statutory_duration_absent": all(
            getattr(unset, field) is None for field in _RETENTION_CONFIG_FIELDS
        ),
    }


class _CommitFailSession(Session):
    """One-shot transaction failure used only by the privacy rollback probe."""

    armed = False

    def commit(self) -> None:
        if type(self).armed:
            type(self).armed = False
            raise RuntimeError("NYAY-19 injected commit failure")
        super().commit()


def _build_behavior_app(
    engine: Engine,
    sender: Any,
    *,
    session_class: type[Session] = Session,
) -> tuple[FastAPI, sessionmaker[Session]]:
    from app.api.v1 import auth_student, student_settings
    from app.core.exceptions import register_exception_handlers
    from app.db.session import get_session

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=session_class,
    )

    def request_session():
        session = factory()
        try:
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
    app.include_router(auth_student.router, prefix="/api/v1")
    app.include_router(student_settings.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[auth_student.get_otp_sender] = lambda: sender
    app.dependency_overrides[auth_student.get_outbox_session_factory] = lambda: factory
    return app, factory


def _seed_active_registration(
    factory: sessionmaker[Session], mobile: str
) -> tuple[uuid.UUID, uuid.UUID]:
    from app.core.crypto import active_key_version, encrypt, keyed_hash
    from app.models.registration import StudentProfile, StudentRegistration, User

    with factory() as session:
        user = User(role="student", status="active")
        session.add(user)
        session.flush()
        registration = StudentRegistration(
            user_id=user.id,
            first_name="Gate",
            middle_name=None,
            last_name="Subject",
            mobile_hash=keyed_hash(mobile),
            mobile_ct=encrypt(mobile),
            dob_hash=keyed_hash(f"nyay19-gate-dob:{mobile}"),
            dob_ct=encrypt("2000-01-01"),
            dob_hash_state="verified",
            key_version=active_key_version(),
            institution_ref=None,
            status="active",
            is_minor=False,
            idempotency_key=None,
            idempotency_key_legacy=False,
        )
        session.add(registration)
        session.flush()
        session.add(
            StudentProfile(
                registration_id=registration.id,
                key_version=active_key_version(),
            )
        )
        session.commit()
        return user.id, registration.id


def _seed_auth_session(
    factory: sessionmaker[Session],
    user_id: uuid.UUID,
    *,
    expires_at: datetime,
    status: str = "active",
    revoked_at: datetime | None = None,
) -> tuple[uuid.UUID, str]:
    from app.core.crypto import keyed_hash
    from app.models.registration import AuthSession

    raw_token = f"nyay19-{uuid.uuid4().hex}-{uuid.uuid4().hex}"
    with factory() as session:
        row = AuthSession(
            user_id=user_id,
            token_hash=keyed_hash(raw_token),
            status=status,
            expires_at=expires_at,
            last_seen_at=expires_at - timedelta(minutes=1),
            revoked_at=revoked_at,
        )
        session.add(row)
        session.commit()
        return row.id, raw_token


def _response_cookie_headers(response: Any) -> list[str]:
    try:
        return list(response.headers.get_list("set-cookie"))
    except AttributeError:
        value = response.headers.get("set-cookie")
        return [] if value is None else [str(value)]


def _cookie_headers_for_name(headers: list[str], name: str) -> list[str]:
    matched: list[str] = []
    for header in headers:
        if not isinstance(header, str) or "\r" in header or "\n" in header:
            continue
        cookie_pair = header.split(";", 1)[0].strip()
        cookie_name, separator, _cookie_value = cookie_pair.partition("=")
        if separator and cookie_name == name:
            matched.append(header)
    return matched


_COOKIE_ATTRIBUTE_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


def _parse_set_cookie_attributes(
    header: str, *, name: str
) -> dict[str, str | None] | None:
    """Parse one target Set-Cookie header with exact, duplicate-free tokens."""

    if not isinstance(header, str) or "\r" in header or "\n" in header:
        return None
    parts = header.split(";")
    cookie_name, separator, _cookie_value = parts[0].strip().partition("=")
    if not separator or cookie_name != name:
        return None
    attributes: dict[str, str | None] = {}
    for raw_attribute in parts[1:]:
        attribute = raw_attribute.strip()
        if not attribute:
            return None
        raw_name, has_value, raw_value = attribute.partition("=")
        attribute_name = raw_name.strip().casefold()
        if (
            not _COOKIE_ATTRIBUTE_NAME.fullmatch(attribute_name)
            or attribute_name in attributes
        ):
            return None
        attributes[attribute_name] = raw_value.strip() if has_value else None
    return attributes


def _cookie_flag_exact(
    attributes: Mapping[str, str | None], name: str
) -> bool:
    return name in attributes and attributes[name] is None


def _cookie_secure_parity_exact(
    attributes: Mapping[str, str | None], *, secure: bool
) -> bool:
    if type(secure) is not bool:
        return False
    if secure:
        return _cookie_flag_exact(attributes, "secure")
    return "secure" not in attributes


def _cookie_contract_observation_passes(value: object) -> bool:
    return bool(
        isinstance(value, Mapping)
        and _exact_keys(value, set(EXPECTED_COOKIE_CONTRACT))
        and type(value.get("auth_path")) is str
        and value.get("auth_path") == "/"
        and type(value.get("auth_same_site")) is str
        and value.get("auth_same_site") == "lax"
        and type(value.get("flow_path")) is str
        and value.get("flow_path") == "/api/v1"
        and type(value.get("flow_same_site")) is str
        and value.get("flow_same_site") == "strict"
        and value.get("http_only") is True
        and value.get("secure_parity") is True
        and value.get("host_only") is True
    )


def _combine_cookie_contracts(
    *contracts: Mapping[str, object]
) -> dict[str, str | bool | None]:
    """Require one full logout observation plus exact auth-only expiries."""

    primary_exact = bool(
        contracts
        and dict(contracts[0]) == EXPECTED_COOKIE_CONTRACT
    )
    expiry_exact = bool(
        all(
            _exact_keys(contract, set(EXPECTED_COOKIE_CONTRACT))
            and contract.get("auth_path") == "/"
            and contract.get("auth_same_site") == "lax"
            and contract.get("flow_path") is None
            and contract.get("flow_same_site") is None
            and contract.get("http_only") is True
            and contract.get("secure_parity") is True
            and contract.get("host_only") is True
            for contract in contracts[1:]
        )
    )
    if primary_exact and expiry_exact:
        return dict(EXPECTED_COOKIE_CONTRACT)
    return {
        "auth_path": None,
        "auth_same_site": None,
        "flow_path": None,
        "flow_same_site": None,
        "http_only": False,
        "secure_parity": False,
        "host_only": False,
    }


def _cookie_clear_contract(
    headers: list[str], *, names: tuple[str, ...], secure: bool
) -> tuple[dict[str, str | bool | None], dict[str, bool]]:
    by_name = {name: _cookie_headers_for_name(headers, name) for name in names}
    auth_names = [name for name in names if name.endswith("session")]
    flow_names = [name for name in names if name.endswith("flow")]
    parsed: dict[str, dict[str, str | None] | None] = {}
    legacy_auth: dict[str, dict[str, str | None] | None] = {}
    for name, items in by_name.items():
        parsed_items = [
            _parse_set_cookie_attributes(item, name=name) for item in items
        ]
        if name in auth_names:
            current = [
                attributes
                for attributes in parsed_items
                if attributes is not None
                and attributes.get("path") == "/"
                and attributes.get("samesite") == "lax"
            ]
            legacy = [
                attributes
                for attributes in parsed_items
                if attributes is not None
                and attributes.get("path") == "/api/v1"
                and attributes.get("samesite") == "strict"
            ]
            parsed[name] = current[0] if len(items) == 2 and len(current) == 1 else None
            legacy_auth[name] = (
                legacy[0] if len(items) == 2 and len(legacy) == 1 else None
            )
        else:
            parsed[name] = (
                parsed_items[0]
                if len(items) == 1 and parsed_items[0] is not None
                else None
            )
    selected = [
        attributes
        for attributes in (
            *parsed.values(),
            *legacy_auth.values(),
        )
        if attributes is not None
    ]
    exact_inventory = bool(
        names
        and len(auth_names) <= 1
        and len(flow_names) <= 1
        and len(auth_names) + len(flow_names) == len(names)
        and all(parsed.get(name) is not None for name in names)
        and all(legacy_auth.get(name) is not None for name in auth_names)
        and len(selected) == len(names) + len(auth_names)
    )

    def named_attribute(
        role_names: list[str], attribute: str, expected: str
    ) -> str | None:
        if not exact_inventory or len(role_names) == 0:
            return None
        if len(role_names) != 1:
            return None
        attributes = parsed[role_names[0]]
        return (
            expected
            if attributes is not None and attributes.get(attribute) == expected
            else None
        )

    contract = {
        "auth_path": named_attribute(auth_names, "path", "/"),
        "auth_same_site": named_attribute(auth_names, "samesite", "lax"),
        "flow_path": named_attribute(flow_names, "path", "/api/v1"),
        "flow_same_site": named_attribute(flow_names, "samesite", "strict"),
        "http_only": bool(
            exact_inventory
            and all(
                _cookie_flag_exact(attributes, "httponly")
                for attributes in selected
            )
        ),
        "secure_parity": bool(
            exact_inventory
            and all(
                _cookie_secure_parity_exact(attributes, secure=secure)
                for attributes in selected
            )
        ),
        "host_only": bool(
            exact_inventory
            and all("domain" not in attributes for attributes in selected)
        ),
    }
    cleared = {
        name: bool(parsed[name] is not None and parsed[name].get("max-age") == "0")
        for name in names
    }
    for name in auth_names:
        cleared[name] = bool(
            cleared[name]
            and legacy_auth[name] is not None
            and legacy_auth[name].get("max-age") == "0"
        )
    return contract, cleared


def _set_client_cookie(
    client: TestClient, name: str, value: str, *, path: str
) -> None:
    if path not in {"/", "/api/v1"}:
        raise ProductGateFailure("client cookie fixture path is invalid")
    client.cookies.set(name, value, path=path)


def _run_logout_expiry_probe(
    engine: Engine,
    app: FastAPI,
    factory: sessionmaker[Session],
) -> dict[str, Any]:
    from app.core.auth_cookies import cookie_secure
    from app.core.config import settings
    from app.db.models.audit import AuditEvent
    from app.models.registration import AuthSession

    now = datetime.now(timezone.utc)
    logout_user, _ = _seed_active_registration(factory, "9100000001")
    logout_session_id, logout_token = _seed_auth_session(
        factory, logout_user, expires_at=now + timedelta(days=1)
    )
    with TestClient(
        app,
        base_url="http://testserver",
        raise_server_exceptions=False,
        headers={"Origin": settings.cors_origins[0]},
    ) as client:
        _set_client_cookie(
            client, settings.auth_session_cookie_name, logout_token, path="/"
        )
        _set_client_cookie(
            client, settings.otp_flow_cookie_name, "stale-flow", path="/api/v1"
        )
        logout = client.post("/api/v1/auth/student/logout", json={})
        logout_headers = _response_cookie_headers(logout)
        _set_client_cookie(
            client, settings.auth_session_cookie_name, logout_token, path="/"
        )
        replay = client.get("/api/v1/auth/student/session")

    with factory() as session:
        active_after_logout = int(
            session.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.user_id == logout_user,
                    AuthSession.status == "active",
                )
            )
            or 0
        )
        logout_audits = int(
            session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "student.auth.logout",
                    AuditEvent.resource_id == logout_session_id,
                )
            )
            or 0
        )

    untrusted_user, _ = _seed_active_registration(factory, "9100000002")
    untrusted_session_id, untrusted_token = _seed_auth_session(
        factory, untrusted_user, expires_at=now + timedelta(days=1)
    )
    with TestClient(
        app, base_url="http://testserver", raise_server_exceptions=False
    ) as client:
        _set_client_cookie(
            client, settings.auth_session_cookie_name, untrusted_token, path="/"
        )
        untrusted = client.post(
            "/api/v1/auth/student/logout",
            json={},
            headers={"Origin": "https://untrusted.example.invalid"},
        )
    with factory() as session:
        untrusted_row = session.get(AuthSession, untrusted_session_id)
        untrusted_unchanged = bool(
            untrusted_row is not None
            and untrusted_row.status == "active"
            and untrusted_row.revoked_at is None
        )

    expired_user, _ = _seed_active_registration(factory, "9100000003")
    expired_session_id, expired_token = _seed_auth_session(
        factory, expired_user, expires_at=now - timedelta(seconds=1)
    )
    with TestClient(
        app, base_url="http://testserver", raise_server_exceptions=False
    ) as client:
        _set_client_cookie(
            client, settings.auth_session_cookie_name, expired_token, path="/"
        )
        expired = client.get("/api/v1/auth/student/session")
        expired_headers = _response_cookie_headers(expired)
    with factory() as session:
        expired_row = session.get(AuthSession, expired_session_id)
        expired_status_exact = bool(
            expired_row is not None
            and expired_row.status == "expired"
            and expired_row.revoked_at is not None
        )
        terminal_uses_expiry = bool(
            expired_row is not None
            and _timestamp_equal(expired_row.revoked_at, expired_row.expires_at)
        )

    cookie_contract, cleared = _cookie_clear_contract(
        logout_headers,
        names=(settings.auth_session_cookie_name, settings.otp_flow_cookie_name),
        secure=cookie_secure(),
    )
    expiry_contract, expiry_cleared = _cookie_clear_contract(
        expired_headers,
        names=(settings.auth_session_cookie_name,),
        secure=cookie_secure(),
    )
    cookie_contract = _combine_cookie_contracts(
        cookie_contract, expiry_contract
    )
    return {
        "logout_status": int(logout.status_code),
        "logout_active_sessions": active_after_logout,
        "logout_replay_authenticated": bool(
            replay.json().get("authenticated") is True
        ),
        "logout_audit_count": logout_audits,
        "expired_discovery_authenticated": bool(
            expired.json().get("authenticated") is True
        ),
        "expired_status_exact": expired_status_exact,
        "expired_terminal_uses_expires_at": terminal_uses_expiry,
        "auth_cookie_clear": bool(
            cleared[settings.auth_session_cookie_name]
            and expiry_cleared[settings.auth_session_cookie_name]
        ),
        "flow_cookie_clear": cleared[settings.otp_flow_cookie_name],
        "cookie_contract": cookie_contract,
        "untrusted_origin_status": int(untrusted.status_code),
        "untrusted_origin_state_unchanged": untrusted_unchanged,
    }


def _run_rotation_probe(
    app: FastAPI,
    factory: sessionmaker[Session],
    sender: Any,
) -> dict[str, Any]:
    from app.core.auth_cookies import cookie_secure
    from app.core.config import settings
    from app.models.registration import AuthSession, OtpPurposeAuthority

    user_id, registration_id = _seed_active_registration(factory, "9100000010")
    with TestClient(
        app,
        base_url="http://testserver",
        raise_server_exceptions=False,
        headers={"Origin": settings.cors_origins[0]},
    ) as client:
        before = len(sender.sent)
        first_start = client.post(
            "/api/v1/auth/student/login/otp/start",
            json={"mobile": "9100000010"},
        )
        first_code = sender.sent[-1][1] if len(sender.sent) == before + 1 else ""
        first_verify = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"code": first_code},
        )
        first_token = client.cookies.get(settings.auth_session_cookie_name) or ""

        with factory() as session:
            authority = session.scalar(
                select(OtpPurposeAuthority).where(
                    OtpPurposeAuthority.registration_id == registration_id,
                    OtpPurposeAuthority.purpose == "login",
                )
            )
            if authority is not None:
                authority.cooldown_until = datetime.now(timezone.utc) - timedelta(
                    seconds=1
                )
                session.commit()

        before = len(sender.sent)
        second_start = client.post(
            "/api/v1/auth/student/login/otp/start",
            json={"mobile": "9100000010"},
        )
        second_code = sender.sent[-1][1] if len(sender.sent) == before + 1 else ""
        second_verify = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"code": second_code},
        )
        second_token = client.cookies.get(settings.auth_session_cookie_name) or ""

    with TestClient(
        app, base_url="http://testserver", raise_server_exceptions=False
    ) as replay_client:
        _set_client_cookie(
            replay_client, settings.auth_session_cookie_name, first_token, path="/"
        )
        old_replay = replay_client.get("/api/v1/auth/student/session")
        old_headers = _response_cookie_headers(old_replay)
    with TestClient(
        app, base_url="http://testserver", raise_server_exceptions=False
    ) as current_client:
        _set_client_cookie(
            current_client, settings.auth_session_cookie_name, second_token, path="/"
        )
        current = current_client.get("/api/v1/auth/student/session")

    with factory() as session:
        rows = list(
            session.scalars(
                select(AuthSession)
                .where(AuthSession.user_id == user_id)
                .order_by(AuthSession.created_at, AuthSession.id)
            )
        )
        active = sum(row.status == "active" for row in rows)
        revoked = sum(row.status == "revoked" for row in rows)
        hashes_exact = bool(
            len(rows) == 2
            and all(
                len(row.token_hash) == 64
                and re.fullmatch(r"[0-9a-f]{64}", row.token_hash) is not None
                for row in rows
            )
        )
        raw_absent = bool(
            first_token
            and second_token
            and first_token != second_token
            and all(
                row.token_hash not in {first_token, second_token} for row in rows
            )
        )
    _, old_clear_inventory = _cookie_clear_contract(
        old_headers,
        names=(settings.auth_session_cookie_name,),
        secure=cookie_secure(),
    )
    old_cleared = old_clear_inventory[settings.auth_session_cookie_name]
    return {
        "first_verify_status": int(
            first_verify.status_code if first_start.status_code == 202 else 0
        ),
        "second_verify_status": int(
            second_verify.status_code if second_start.status_code == 202 else 0
        ),
        "active_sessions": int(active),
        "revoked_sessions": int(revoked),
        "old_cookie_authenticated": bool(
            old_replay.json().get("authenticated") is True
        ),
        "new_cookie_authenticated": bool(
            current.json().get("authenticated") is True
        ),
        "old_cookie_cleared": old_cleared,
        "database_tokens_are_hashes": hashes_exact,
        "wire_tokens_absent_from_database": raw_absent,
    }


def _login_attempt_shape(row: Any, *, original: tuple[str, str] | None = None) -> bool:
    from app.services.login_service import ERASED_LIFECYCLE_AT

    return bool(
        row is not None
        and row.status == "erased"
        and row.registration_id is None
        and row.challenge_id is None
        and row.metadata_json is None
        and len(row.opaque_id) == 64
        and len(row.lookup_hash) == 64
        and re.fullmatch(r"[0-9a-f]{64}", row.opaque_id) is not None
        and re.fullmatch(r"[0-9a-f]{64}", row.lookup_hash) is not None
        and (
            original is None
            or (row.opaque_id, row.lookup_hash) != original
        )
        and all(
            _timestamp_equal(value, ERASED_LIFECYCLE_AT)
            for value in (
                row.expires_at,
                row.consumed_at,
                row.created_at,
                row.updated_at,
                row.deleted_at,
            )
        )
    )


def _auth_session_shape(row: Any, *, original_hash: str | None = None) -> bool:
    from app.services.login_service import ERASED_LIFECYCLE_AT

    return bool(
        row is not None
        and row.status == "erased"
        and row.user_id is None
        and row.metadata_json is None
        and len(row.token_hash) == 64
        and re.fullmatch(r"[0-9a-f]{64}", row.token_hash) is not None
        and (original_hash is None or row.token_hash != original_hash)
        and all(
            _timestamp_equal(value, ERASED_LIFECYCLE_AT)
            for value in (
                row.expires_at,
                row.last_seen_at,
                row.revoked_at,
                row.created_at,
                row.updated_at,
                row.deleted_at,
            )
        )
    )


def _new_login_attempt(
    session: Session,
    *,
    registration_id: uuid.UUID | None,
    lookup_hash: str,
    status: str,
    expires_at: datetime,
    consumed_at: datetime | None,
) -> Any:
    from app.models.registration import LoginAttempt

    row = LoginAttempt(
        opaque_id=uuid.uuid4().hex,
        lookup_hash=lookup_hash,
        registration_id=registration_id,
        status=status,
        expires_at=expires_at,
        consumed_at=consumed_at,
    )
    session.add(row)
    session.flush()
    return row


def _run_attempt_retention_probe(
    factory: sessionmaker[Session],
) -> dict[str, Any]:
    from app.core.crypto import keyed_hash
    from app.core.retention import RetentionPolicy, purge_expired
    from app.models.registration import LoginAttempt, StudentRegistration

    now = datetime.now(timezone.utc)
    _, registration_id = _seed_active_registration(factory, "9100000020")
    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        real_lookup = registration.mobile_hash
        real_pending = _new_login_attempt(
            session,
            registration_id=registration_id,
            lookup_hash=real_lookup,
            status="pending",
            expires_at=now - timedelta(seconds=2),
            consumed_at=None,
        )
        decoy_pending = _new_login_attempt(
            session,
            registration_id=None,
            lookup_hash=keyed_hash("nyay19-decoy-expiry"),
            status="pending",
            expires_at=now - timedelta(seconds=2),
            consumed_at=None,
        )
        pending_ids = (real_pending.id, decoy_pending.id)
        session.commit()
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(None, None, None, None, None, "anonymise"),
        )
        session.commit()
    with factory() as session:
        real_expired = session.get(LoginAttempt, pending_ids[0])
        decoy_expired = session.get(LoginAttempt, pending_ids[1])
        real_expired_exact = bool(
            real_expired is not None
            and real_expired.status == "expired"
            and _timestamp_equal(real_expired.consumed_at, real_expired.expires_at)
        )
        decoy_expired_exact = bool(
            decoy_expired is not None
            and decoy_expired.status == "expired"
            and _timestamp_equal(decoy_expired.consumed_at, decoy_expired.expires_at)
        )

    old = now - timedelta(days=6)
    boundary = now - timedelta(days=5)
    recent = now - timedelta(days=1)
    with factory() as session:
        rows = {
            "old_real": _new_login_attempt(
                session,
                registration_id=registration_id,
                lookup_hash=real_lookup,
                status="consumed",
                expires_at=old,
                consumed_at=old,
            ),
            "old_decoy": _new_login_attempt(
                session,
                registration_id=None,
                lookup_hash=keyed_hash("nyay19-old-decoy"),
                status="expired",
                expires_at=old,
                consumed_at=old,
            ),
            "boundary_real": _new_login_attempt(
                session,
                registration_id=registration_id,
                lookup_hash=real_lookup,
                status="consumed",
                expires_at=boundary,
                consumed_at=boundary,
            ),
            "boundary_decoy": _new_login_attempt(
                session,
                registration_id=None,
                lookup_hash=keyed_hash("nyay19-boundary-decoy"),
                status="expired",
                expires_at=boundary,
                consumed_at=boundary,
            ),
            "recent_real": _new_login_attempt(
                session,
                registration_id=registration_id,
                lookup_hash=real_lookup,
                status="consumed",
                expires_at=recent,
                consumed_at=recent,
            ),
            "recent_decoy": _new_login_attempt(
                session,
                registration_id=None,
                lookup_hash=keyed_hash("nyay19-recent-decoy"),
                status="expired",
                expires_at=recent,
                consumed_at=recent,
            ),
        }
        ids = {name: row.id for name, row in rows.items()}
        originals = {
            name: (row.opaque_id, row.lookup_hash) for name, row in rows.items()
        }
        session.commit()
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(
                None,
                None,
                None,
                None,
                None,
                "anonymise",
                login_attempt_days=5,
            ),
        )
        session.commit()
    with factory() as session:
        observed = {name: session.get(LoginAttempt, row_id) for name, row_id in ids.items()}
        old_real_affected = _login_attempt_shape(
            observed["old_real"], original=originals["old_real"]
        )
        old_decoy_affected = _login_attempt_shape(
            observed["old_decoy"], original=originals["old_decoy"]
        )
        boundary_real_unchanged = bool(
            observed["boundary_real"] is not None
            and observed["boundary_real"].status == "consumed"
            and observed["boundary_real"].lookup_hash
            == originals["boundary_real"][1]
        )
        boundary_decoy_unchanged = bool(
            observed["boundary_decoy"] is not None
            and observed["boundary_decoy"].status == "expired"
            and observed["boundary_decoy"].lookup_hash
            == originals["boundary_decoy"][1]
        )
        recent_real_unchanged = bool(
            observed["recent_real"] is not None
            and observed["recent_real"].status == "consumed"
            and observed["recent_real"].lookup_hash == originals["recent_real"][1]
        )
        recent_decoy_unchanged = bool(
            observed["recent_decoy"] is not None
            and observed["recent_decoy"].status == "expired"
            and observed["recent_decoy"].lookup_hash
            == originals["recent_decoy"][1]
        )

    with factory() as session:
        delete_real = _new_login_attempt(
            session,
            registration_id=registration_id,
            lookup_hash=real_lookup,
            status="consumed",
            expires_at=old,
            consumed_at=old,
        )
        delete_decoy = _new_login_attempt(
            session,
            registration_id=None,
            lookup_hash=keyed_hash("nyay19-delete-decoy"),
            status="expired",
            expires_at=old,
            consumed_at=old,
        )
        delete_ids = (delete_real.id, delete_decoy.id)
        session.commit()
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(
                None, None, None, None, None, "delete", login_attempt_days=5
            ),
        )
        session.commit()
    with factory() as session:
        deleted_absent = all(session.get(LoginAttempt, row_id) is None for row_id in delete_ids)

    with factory() as session:
        unset = _new_login_attempt(
            session,
            registration_id=None,
            lookup_hash=keyed_hash("nyay19-unset-attempt"),
            status="expired",
            expires_at=old,
            consumed_at=old,
        )
        unset_id = unset.id
        unset_before = (unset.status, unset.lookup_hash, unset.consumed_at)
        session.commit()
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(None, None, None, None, None, "anonymise"),
        )
        session.commit()
    with factory() as session:
        unset = session.get(LoginAttempt, unset_id)
        unset_unchanged = bool(
            unset is not None
            and (unset.status, unset.lookup_hash, unset.consumed_at) == unset_before
        )
        session.delete(unset)
        session.commit()

    with factory() as session:
        rollback = _new_login_attempt(
            session,
            registration_id=None,
            lookup_hash=keyed_hash("nyay19-rollback-attempt"),
            status="expired",
            expires_at=old,
            consumed_at=old,
        )
        rollback_id = rollback.id
        rollback_before = (rollback.status, rollback.opaque_id, rollback.lookup_hash)
        session.commit()
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(
                None,
                None,
                None,
                None,
                None,
                "anonymise",
                login_attempt_days=5,
            ),
        )
        session.flush()
        session.rollback()
    with factory() as session:
        rollback = session.get(LoginAttempt, rollback_id)
        rollback_restored = bool(
            rollback is not None
            and (rollback.status, rollback.opaque_id, rollback.lookup_hash)
            == rollback_before
        )
    return {
        "real_expired_terminalized": real_expired_exact,
        "decoy_expired_terminalized": decoy_expired_exact,
        "terminal_time_uses_expires_at": bool(
            real_expired_exact and decoy_expired_exact
        ),
        "strictly_older_real_affected": old_real_affected,
        "strictly_older_decoy_affected": old_decoy_affected,
        "at_cutoff_real_unchanged": boundary_real_unchanged,
        "at_cutoff_decoy_unchanged": boundary_decoy_unchanged,
        "recent_real_unchanged": recent_real_unchanged,
        "recent_decoy_unchanged": recent_decoy_unchanged,
        "unset_window_unchanged": unset_unchanged,
        "anonymise_shape_exact": bool(old_real_affected and old_decoy_affected),
        "delete_rows_absent": deleted_absent,
        "rollback_restores_all_rows": rollback_restored,
    }


def _new_auth_session_row(
    session: Session,
    *,
    user_id: uuid.UUID,
    status: str,
    expires_at: datetime,
    revoked_at: datetime | None,
) -> tuple[Any, str]:
    from app.core.crypto import keyed_hash
    from app.models.registration import AuthSession

    raw = f"nyay19-retention-{uuid.uuid4().hex}-{uuid.uuid4().hex}"
    row = AuthSession(
        user_id=user_id,
        token_hash=keyed_hash(raw),
        status=status,
        expires_at=expires_at,
        last_seen_at=expires_at - timedelta(minutes=1),
        revoked_at=revoked_at,
    )
    session.add(row)
    session.flush()
    return row, raw


def _run_session_retention_probe(
    factory: sessionmaker[Session], *, mode: str, mobile_offset: int
) -> dict[str, Any]:
    from app.core.retention import RetentionPolicy, purge_expired
    from app.models.registration import AuthSession
    from app.services import login_service

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=6)
    boundary = now - timedelta(days=5)
    recent = now - timedelta(days=1)
    users: list[uuid.UUID] = []
    for index in range(5):
        user_id, _ = _seed_active_registration(
            factory, f"91{mobile_offset + index:08d}"
        )
        users.append(user_id)
    with factory() as session:
        expired_active, _ = _new_auth_session_row(
            session,
            user_id=users[0],
            status="active",
            expires_at=recent,
            revoked_at=None,
        )
        old_terminal, old_bearer = _new_auth_session_row(
            session,
            user_id=users[1],
            status="revoked",
            expires_at=old,
            revoked_at=old,
        )
        boundary_terminal, _ = _new_auth_session_row(
            session,
            user_id=users[2],
            status="revoked",
            expires_at=boundary,
            revoked_at=boundary,
        )
        recent_terminal, _ = _new_auth_session_row(
            session,
            user_id=users[3],
            status="revoked",
            expires_at=recent,
            revoked_at=recent,
        )
        active_future, _ = _new_auth_session_row(
            session,
            user_id=users[4],
            status="active",
            expires_at=now + timedelta(days=1),
            revoked_at=None,
        )
        ids = {
            "expired": expired_active.id,
            "old": old_terminal.id,
            "boundary": boundary_terminal.id,
            "recent": recent_terminal.id,
            "active": active_future.id,
        }
        old_hash = old_terminal.token_hash
        boundary_hash = boundary_terminal.token_hash
        recent_hash = recent_terminal.token_hash
        active_hash = active_future.token_hash
        session.commit()
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(
                None,
                None,
                None,
                None,
                None,
                mode,
                auth_session_days=5,
            ),
        )
        session.commit()
    with factory() as session:
        expired = session.get(AuthSession, ids["expired"])
        old_row = session.get(AuthSession, ids["old"])
        boundary_row = session.get(AuthSession, ids["boundary"])
        recent_row = session.get(AuthSession, ids["recent"])
        active_row = session.get(AuthSession, ids["active"])
        expired_exact = bool(
            expired is not None
            and expired.status == "expired"
            and _timestamp_equal(expired.revoked_at, expired.expires_at)
        )
        affected_exact = bool(
            old_row is None
            if mode == "delete"
            else _auth_session_shape(old_row, original_hash=old_hash)
        )
        boundary_unchanged = bool(
            boundary_row is not None
            and boundary_row.status == "revoked"
            and boundary_row.token_hash == boundary_hash
        )
        recent_unchanged = bool(
            recent_row is not None
            and recent_row.status == "revoked"
            and recent_row.token_hash == recent_hash
        )
        active_unchanged = bool(
            active_row is not None
            and active_row.status == "active"
            and active_row.token_hash == active_hash
        )
        bearer_replay = login_service.session_claims(
            session, old_bearer, now, touch=False
        )

    unset_user, _ = _seed_active_registration(
        factory, f"91{mobile_offset + 10:08d}"
    )
    with factory() as session:
        unset, _ = _new_auth_session_row(
            session,
            user_id=unset_user,
            status="revoked",
            expires_at=old,
            revoked_at=old,
        )
        unset_id = unset.id
        unset_before = (unset.status, unset.user_id, unset.token_hash, unset.revoked_at)
        session.commit()
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(None, None, None, None, None, mode),
        )
        session.commit()
    with factory() as session:
        unset = session.get(AuthSession, unset_id)
        unset_unchanged = bool(
            unset is not None
            and (unset.status, unset.user_id, unset.token_hash, unset.revoked_at)
            == unset_before
        )
        session.delete(unset)
        session.commit()

    rollback_user, _ = _seed_active_registration(
        factory, f"91{mobile_offset + 11:08d}"
    )
    with factory() as session:
        rollback, _ = _new_auth_session_row(
            session,
            user_id=rollback_user,
            status="revoked",
            expires_at=old,
            revoked_at=old,
        )
        rollback_id = rollback.id
        rollback_before = (
            rollback.status,
            rollback.user_id,
            rollback.token_hash,
            rollback.revoked_at,
        )
        session.commit()
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(
                None,
                None,
                None,
                None,
                None,
                mode,
                auth_session_days=5,
            ),
        )
        session.flush()
        session.rollback()
    with factory() as session:
        rollback = session.get(AuthSession, rollback_id)
        rollback_restored = bool(
            rollback is not None
            and (
                rollback.status,
                rollback.user_id,
                rollback.token_hash,
                rollback.revoked_at,
            )
            == rollback_before
        )
    return {
        "mode": mode,
        "expired_active_terminalized": expired_exact,
        "expiry_terminal_uses_expires_at": expired_exact,
        "strictly_older_affected": affected_exact,
        "at_cutoff_unchanged": boundary_unchanged,
        "recent_unchanged": recent_unchanged,
        "active_unchanged": active_unchanged,
        "unset_window_unchanged": unset_unchanged,
        "result_shape_exact": affected_exact,
        "bearer_replay_denied": bearer_replay is None,
        "rollback_restores_all_rows": rollback_restored,
    }


def _run_registration_erasure_probe(
    engine: Engine,
    factory: sessionmaker[Session],
    *,
    mode: str,
    mobile: str,
) -> dict[str, Any]:
    from app.core.retention import anonymise_registration, delete_registration
    from app.models.registration import (
        AuthSession,
        LoginAttempt,
        StudentRegistration,
    )
    from app.services import login_service

    now = datetime.now(timezone.utc)
    user_id, registration_id = _seed_active_registration(factory, mobile)
    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        attempt_one = _new_login_attempt(
            session,
            registration_id=registration_id,
            lookup_hash=registration.mobile_hash,
            status="pending",
            expires_at=now + timedelta(minutes=5),
            consumed_at=None,
        )
        attempt_two = _new_login_attempt(
            session,
            registration_id=registration_id,
            lookup_hash=registration.mobile_hash,
            status="expired",
            expires_at=now - timedelta(days=1),
            consumed_at=now - timedelta(days=1),
        )
        active_session, active_bearer = _new_auth_session_row(
            session,
            user_id=user_id,
            status="active",
            expires_at=now + timedelta(days=1),
            revoked_at=None,
        )
        revoked_session, _ = _new_auth_session_row(
            session,
            user_id=user_id,
            status="revoked",
            expires_at=now - timedelta(days=1),
            revoked_at=now - timedelta(days=1),
        )
        attempt_ids = (attempt_one.id, attempt_two.id)
        session_ids = (active_session.id, revoked_session.id)
        attempt_originals = {
            attempt_one.id: (attempt_one.opaque_id, attempt_one.lookup_hash),
            attempt_two.id: (attempt_two.opaque_id, attempt_two.lookup_hash),
        }
        session_originals = {
            active_session.id: active_session.token_hash,
            revoked_session.id: revoked_session.token_hash,
        }
        session.commit()

    before_graph = _rows_digest(engine)
    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        operation = anonymise_registration if mode == "anonymise" else delete_registration
        operation(session, registration)
        session.flush()
        session.rollback()
    rollback_restored = _rows_digest(engine) == before_graph

    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        operation = anonymise_registration if mode == "anonymise" else delete_registration
        operation(session, registration)
        session.commit()
    with factory() as session:
        attempts = [session.get(LoginAttempt, row_id) for row_id in attempt_ids]
        sessions = [session.get(AuthSession, row_id) for row_id in session_ids]
        attempts_after = sum(row is not None for row in attempts)
        sessions_after = sum(row is not None for row in sessions)
        active_after = int(
            session.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.user_id == user_id,
                    AuthSession.status == "active",
                )
            )
            or 0
        )
        attempt_shapes = bool(
            all(row is None for row in attempts)
            if mode == "delete"
            else all(
                _login_attempt_shape(
                    row, original=attempt_originals[row_id]
                )
                for row_id, row in zip(attempt_ids, attempts, strict=True)
            )
        )
        session_shapes = bool(
            all(row is None for row in sessions)
            if mode == "delete"
            else all(
                _auth_session_shape(
                    row, original_hash=session_originals[row_id]
                )
                for row_id, row in zip(session_ids, sessions, strict=True)
            )
        )
        orphan_links = int(
            session.scalar(
                select(func.count(LoginAttempt.id)).where(
                    LoginAttempt.registration_id == registration_id
                )
            )
            or 0
        ) + int(
            session.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.user_id == user_id
                )
            )
            or 0
        )
        replay = login_service.session_claims(
            session, active_bearer, now, touch=False
        )
    return {
        "mode": mode,
        "active_sessions_before": 1,
        "active_sessions_after": active_after,
        "attempts_before": 2,
        "sessions_before": 2,
        "attempts_after": int(attempts_after),
        "sessions_after": int(sessions_after),
        "bearer_replay_denied": replay is None,
        "attempt_shape_exact": attempt_shapes,
        "session_shape_exact": session_shapes,
        "orphan_links": int(orphan_links),
        "rollback_restores_graph": rollback_restored,
    }


def _run_privacy_delete_probe(
    engine: Engine,
    app: FastAPI,
    factory: sessionmaker[Session],
    sender: Any,
) -> dict[str, Any]:
    from app.core.auth_cookies import cookie_secure
    from app.core.config import settings
    from app.core.crypto import keyed_hash
    from app.models.registration import AuthSession, OtpFlow, StudentRegistration, User
    from app.models.wave1 import DataSubjectRequest, DeletionJob
    from app.services.otp_flow_service import flow_token_hash

    now = datetime.now(timezone.utc)
    user_id, registration_id = _seed_active_registration(factory, "9100000050")
    auth_session_id, auth_token = _seed_auth_session(
        factory, user_id, expires_at=now + timedelta(days=1)
    )
    idempotency_key = f"nyay19-delete-{uuid.uuid4().hex}"
    with TestClient(
        app,
        base_url="http://testserver",
        raise_server_exceptions=False,
        headers={"Origin": settings.cors_origins[0]},
    ) as client:
        _set_client_cookie(
            client, settings.auth_session_cookie_name, auth_token, path="/"
        )
        delivered_before = len(sender.sent)
        recovery = client.post(
            "/api/v1/auth/student/recovery/start",
            json={"mobile": "9100000050"},
        )
        recovery_code = (
            sender.sent[-1][1]
            if recovery.status_code == 202 and len(sender.sent) == delivered_before + 1
            else ""
        )
        verified = client.post(
            "/api/v1/auth/student/recovery/verify",
            json={"code": recovery_code},
        )
        proof_token = client.cookies.get(settings.otp_flow_cookie_name) or ""
        deleted = client.post(
            "/api/v1/student/privacy/delete",
            json={"confirmation": "DELETE"},
            headers={"Idempotency-Key": idempotency_key},
        )
        delete_headers = _response_cookie_headers(deleted)
    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        user = session.get(User, user_id)
        auth_session = session.get(AuthSession, auth_session_id)
        dsr_rows = list(
            session.scalars(
                select(DataSubjectRequest).where(
                    DataSubjectRequest.idempotency_key == idempotency_key
                )
            )
        )
        job_rows = (
            list(
                session.scalars(
                    select(DeletionJob).where(
                        DeletionJob.request_id == dsr_rows[0].id
                    )
                )
            )
            if len(dsr_rows) == 1
            else []
        )
        proof = session.scalar(
            select(OtpFlow).where(OtpFlow.token_hash == flow_token_hash(proof_token))
        ) if proof_token else None
        active_sessions = int(
            session.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.user_id == user_id,
                    AuthSession.status == "active",
                )
            )
            or 0
        )
        proof_consumed = bool(
            proof is not None
            and proof.state == "consumed"
            and proof.consumed_at is not None
        )
        frozen_user = bool(user is not None and user.status == "suspended")
        frozen_registration = bool(
            registration is not None and registration.status == "suspended"
        )
        revoked = bool(
            auth_session is not None
            and auth_session.status in {"revoked", "expired"}
            and auth_session.revoked_at is not None
            and auth_session.token_hash == keyed_hash(auth_token)
        )
    with TestClient(
        app, base_url="http://testserver", raise_server_exceptions=False
    ) as replay_client:
        _set_client_cookie(
            replay_client, settings.auth_session_cookie_name, auth_token, path="/"
        )
        replay = replay_client.get("/api/v1/auth/student/session")

    fail_app, fail_factory = _build_behavior_app(
        engine, sender, session_class=_CommitFailSession
    )
    rollback_user, _ = _seed_active_registration(fail_factory, "9100000051")
    _, rollback_auth_token = _seed_auth_session(
        fail_factory, rollback_user, expires_at=now + timedelta(days=1)
    )
    rollback_key = f"nyay19-delete-rollback-{uuid.uuid4().hex}"
    with TestClient(
        fail_app,
        base_url="http://testserver",
        raise_server_exceptions=False,
        headers={"Origin": settings.cors_origins[0]},
    ) as client:
        _set_client_cookie(
            client,
            settings.auth_session_cookie_name,
            rollback_auth_token,
            path="/",
        )
        delivered_before = len(sender.sent)
        recovery = client.post(
            "/api/v1/auth/student/recovery/start",
            json={"mobile": "9100000051"},
        )
        recovery_code = (
            sender.sent[-1][1]
            if recovery.status_code == 202 and len(sender.sent) == delivered_before + 1
            else ""
        )
        verified_rollback = client.post(
            "/api/v1/auth/student/recovery/verify",
            json={"code": recovery_code},
        )
        before_failure = _rows_digest(engine)
        _CommitFailSession.armed = True
        failed = client.post(
            "/api/v1/student/privacy/delete",
            json={"confirmation": "DELETE"},
            headers={"Idempotency-Key": rollback_key},
        )
        after_failure = _rows_digest(engine)
        retry = client.post(
            "/api/v1/student/privacy/delete",
            json={"confirmation": "DELETE"},
            headers={"Idempotency-Key": rollback_key},
        )
    cookie_contract, cleared = _cookie_clear_contract(
        delete_headers,
        names=(settings.auth_session_cookie_name, settings.otp_flow_cookie_name),
        secure=cookie_secure(),
    )
    atomic_rollback = bool(
        verified_rollback.status_code == 200
        and failed.status_code == 500
        and not _response_cookie_headers(failed)
        and before_failure == after_failure
        and retry.status_code == 202
    )
    return {
        "accepted_status": int(deleted.status_code),
        "request_rows": len(dsr_rows),
        "job_rows": len(job_rows),
        "proof_consumed": bool(verified.status_code == 200 and proof_consumed),
        "user_suspended": frozen_user,
        "registration_suspended": frozen_registration,
        "active_sessions": active_sessions,
        "bearer_replay_denied": bool(
            revoked and replay.json().get("authenticated") is False
        ),
        "auth_cookie_clear": cleared[settings.auth_session_cookie_name],
        "flow_cookie_clear": cleared[settings.otp_flow_cookie_name],
        "cookie_contract": cookie_contract,
        "atomic_rollback_restores_all": atomic_rollback,
        "legacy_accepted_cases": 0,
        "legacy_accounts_frozen": 0,
        "legacy_registrations_frozen": 0,
        "legacy_active_sessions": -1,
        "legacy_idempotent_second_pass": False,
    }


def _run_audit_probe(factory: sessionmaker[Session]) -> dict[str, Any]:
    from app.core.crypto import keyed_hash
    from app.core.retention import RetentionPolicy, purge_expired
    from app.db.models.audit import AuditEvent

    now = datetime.now(timezone.utc)
    with factory() as session:
        pending = _new_login_attempt(
            session,
            registration_id=None,
            lookup_hash=keyed_hash("nyay19-audit-decoy"),
            status="pending",
            expires_at=now - timedelta(seconds=1),
            consumed_at=None,
        )
        pending_id = pending.id
        before = int(
            session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "student.auth.retention_applied"
                )
            )
            or 0
        )
        session.commit()
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(None, None, None, None, None, "anonymise"),
        )
        session.commit()
    with factory() as session:
        after = int(
            session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "student.auth.retention_applied"
                )
            )
            or 0
        )
        event = session.scalar(
            select(AuditEvent)
            .where(AuditEvent.action == "student.auth.retention_applied")
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        )
    with factory() as session:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(None, None, None, None, None, "anonymise"),
        )
        session.commit()
    with factory() as session:
        final = int(
            session.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "student.auth.retention_applied"
                )
            )
            or 0
        )
    state = event.after_state if event is not None else None
    serialized = json.dumps(state, sort_keys=True, separators=(",", ":"))
    expected_keys = {
        "mode",
        "expired_sessions",
        "expired_attempts",
        "login_attempts",
        "auth_sessions",
    }
    integer_keys = expected_keys - {"mode"}
    return {
        "action_exact": bool(
            event is not None
            and event.action == "student.auth.retention_applied"
            and after == before + 1
        ),
        "resource_type_exact": bool(
            event is not None and event.resource_type == "auth_security_history"
        ),
        "aggregate_keys_exact": bool(
            isinstance(state, Mapping)
            and set(state) == expected_keys
            and state.get("mode") == "anonymise"
            and state.get("expired_attempts") == 1
        ),
        "aggregate_integer_counts": bool(
            isinstance(state, Mapping)
            and all(type(state.get(key)) is int for key in integer_keys)
        ),
        "zero_count_run_has_no_event": final == after,
        "identifiers_absent": bool(
            event is not None
            and event.actor_user_id is None
            and event.resource_id is None
            and str(pending_id) not in serialized
        ),
        "contact_data_absent": bool(
            _EMAIL_TEXT.search(serialized) is None
            and _MOBILE_TEXT.search(serialized) is None
        ),
        "bearers_absent": _COOKIE_VALUE_TEXT.search(serialized) is None,
        "row_hashes_absent": _HEX64_TEXT.search(serialized) is None,
    }


class _PgBackendTracker:
    """Keep backend identities private while proving two physical workers."""

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


def _wait_for_tracked_pg_locks(
    engine: Engine,
    tracker: _PgBackendTracker,
    *,
    expected_backends: int,
    minimum_waiters: int,
    timeout: float = 8.0,
) -> bool:
    """Observe real PostgreSQL lock waits without retaining backend PIDs."""

    if not tracker.wait_for_count(expected_backends, timeout=timeout):
        return False
    pids = tracker.private_snapshot()
    if len(pids) != expected_backends:
        return False
    placeholders = ", ".join(f":pid_{index}" for index in range(len(pids)))
    parameters = {
        f"pid_{index}": pid for index, pid in enumerate(sorted(pids))
    }
    statement = text(
        "SELECT count(*) FROM pg_stat_activity "
        f"WHERE pid IN ({placeholders}) AND wait_event_type = 'Lock'"
    )
    deadline = time.monotonic() + timeout
    with engine.connect() as connection:
        while time.monotonic() < deadline:
            if int(connection.scalar(statement, parameters) or 0) >= minimum_waiters:
                return True
            time.sleep(0.02)
    return False


class _TransactionBoundaryCounter:
    """Count observed worker transaction boundaries without exposing row data."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def after_commit(self, _session: Session) -> None:
        self.commits += 1

    def after_rollback(self, _session: Session) -> None:
        self.rollbacks += 1


def _observed_split_commits(outcomes: list[Mapping[str, Any]]) -> int:
    """Return observed commits beyond the single allowed commit per worker."""

    if len(outcomes) != 2:
        return 1
    split_commits = 0
    for outcome in outcomes:
        commits = outcome.get("commits")
        rollbacks = outcome.get("rollbacks")
        if (
            not _is_exact_int(commits)
            or commits < 0
            or not _is_exact_int(rollbacks)
            or rollbacks < 0
        ):
            return 1
        split_commits += max(0, commits - 1)
    return split_commits


def _run_controlled_pair(
    engine: Engine,
    factory: sessionmaker[Session],
    *,
    control_lock: Callable[[Session], bool],
    first: tuple[str, Callable[[Session], Mapping[str, Any]]],
    second: tuple[str, Callable[[Session], Mapping[str, Any]]],
) -> dict[str, Any]:
    """Queue two real transactions behind one control lock, then release."""

    from sqlalchemy import event

    tracker = _PgBackendTracker()
    traces: dict[str, list[str]] = {first[0]: [], second[0]: []}

    def worker(
        label: str, operation: Callable[[Session], Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        with factory() as session:
            boundaries = _TransactionBoundaryCounter()
            after_commit = boundaries.after_commit
            after_rollback = boundaries.after_rollback
            event.listen(session, "after_commit", after_commit)
            event.listen(session, "after_rollback", after_rollback)
            connection = session.connection()
            tracker.record(int(connection.scalar(text("SELECT pg_backend_pid()"))))
            connection_info = connection.info
            connection_info["nyay19_race_trace"] = traces[label]
            try:
                session.execute(text("SET LOCAL statement_timeout = '15000ms'"))
                result = dict(operation(session))
                return {
                    "terminal": result.get("terminal") is True,
                    "kind": str(result.get("kind", "unknown")),
                    "wire": result.get("wire"),
                    "commits": boundaries.commits,
                    "rollbacks": boundaries.rollbacks,
                }
            except Exception:  # noqa: BLE001 - private hostile-race result
                session.rollback()
                return {
                    "terminal": False,
                    "kind": "error",
                    "wire": None,
                    "commits": boundaries.commits,
                    "rollbacks": boundaries.rollbacks,
                }
            finally:
                # Product operations may commit and return this Connection to
                # the NullPool before the worker exits.  Retain the info dict,
                # not a possibly closed Connection wrapper, for trace cleanup.
                connection_info.pop("nyay19_race_trace", None)
                event.remove(session, "after_commit", after_commit)
                event.remove(session, "after_rollback", after_rollback)

    control = factory()
    outcomes: list[Mapping[str, Any]] = []
    timeouts = 0
    first_waited = False
    both_waited = False
    try:
        if control_lock(control) is not True:
            return {
                "outcomes": outcomes,
                "backend_count": 0,
                "lock_wait_observed": False,
                "timeouts": 0,
                "traces": traces,
                "split_commits": _observed_split_commits(outcomes),
            }
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(worker, *first)
            first_waited = _wait_for_tracked_pg_locks(
                engine,
                tracker,
                expected_backends=1,
                minimum_waiters=1,
            )
            second_future = executor.submit(worker, *second)
            both_waited = _wait_for_tracked_pg_locks(
                engine,
                tracker,
                expected_backends=2,
                minimum_waiters=2,
            )
            control.commit()
            for future in (first_future, second_future):
                try:
                    outcomes.append(future.result(timeout=30))
                except FuturesTimeout:
                    timeouts += 1
                    future.cancel()
    finally:
        control.rollback()
        control.close()
    return {
        "outcomes": outcomes,
        "backend_count": tracker.count,
        "lock_wait_observed": bool(first_waited and both_waited),
        "timeouts": timeouts,
        "traces": traces,
        "split_commits": _observed_split_commits(outcomes),
    }


def _auth_state_invariants(
    factory: sessionmaker[Session],
) -> tuple[bool, int]:
    """Independently re-check lifecycle coherence and dangling auth links."""

    invalid_sql = text(
        """
        SELECT
          (SELECT count(*) FROM login_attempts la
           WHERE NOT (
             (la.status = 'pending' AND la.consumed_at IS NULL
              AND la.deleted_at IS NULL) OR
             (la.status IN ('consumed', 'expired')
              AND la.consumed_at IS NOT NULL AND la.deleted_at IS NULL) OR
             (la.status = 'erased' AND la.registration_id IS NULL
              AND la.challenge_id IS NULL AND la.consumed_at IS NOT NULL
              AND la.deleted_at IS NOT NULL AND la.metadata_json IS NULL
              AND la.created_at = la.updated_at
              AND la.updated_at = la.expires_at
              AND la.expires_at = la.consumed_at
              AND la.consumed_at = la.deleted_at)))
          +
          (SELECT count(*) FROM auth_sessions auth
           WHERE NOT (
             (auth.status = 'active' AND auth.user_id IS NOT NULL
              AND auth.revoked_at IS NULL AND auth.deleted_at IS NULL) OR
             (auth.status IN ('revoked', 'expired')
              AND auth.user_id IS NOT NULL AND auth.revoked_at IS NOT NULL
              AND auth.deleted_at IS NULL) OR
             (auth.status = 'erased' AND auth.user_id IS NULL
              AND auth.revoked_at IS NOT NULL AND auth.deleted_at IS NOT NULL
              AND auth.metadata_json IS NULL
              AND auth.created_at = auth.updated_at
              AND auth.updated_at = auth.expires_at
              AND auth.expires_at = auth.last_seen_at
              AND auth.last_seen_at = auth.revoked_at
              AND auth.revoked_at = auth.deleted_at)))
          +
          (SELECT count(*) FROM (
             SELECT user_id FROM auth_sessions
             WHERE status = 'active' GROUP BY user_id HAVING count(*) > 1
           ) duplicate_active)
        """
    )
    orphan_sql = text(
        """
        SELECT
          (SELECT count(*) FROM login_attempts la
           LEFT JOIN student_registrations reg ON reg.id = la.registration_id
           WHERE la.registration_id IS NOT NULL AND reg.id IS NULL)
          +
          (SELECT count(*) FROM auth_sessions auth
           LEFT JOIN users account ON account.id = auth.user_id
           WHERE auth.user_id IS NOT NULL AND account.id IS NULL)
        """
    )
    with factory() as session:
        invalid = int(session.scalar(invalid_sql) or 0)
        orphans = int(session.scalar(orphan_sql) or 0)
    return invalid == 0 and orphans == 0, orphans


def _scoped_auth_race_state(
    factory: sessionmaker[Session],
    *,
    user_id: uuid.UUID,
    prior_session_ids: tuple[uuid.UUID, ...],
    obsolete_bearers: tuple[str, ...],
    now: datetime,
) -> dict[str, Any]:
    from app.models.registration import AuthSession
    from app.services import login_service

    with factory() as session:
        scoped = list(
            session.scalars(
                select(AuthSession).where(
                    (AuthSession.user_id == user_id)
                    | (AuthSession.id.in_(prior_session_ids))
                )
            )
        )
        active = sum(
            row.user_id == user_id and row.status == "active" for row in scoped
        )
        resurrections = sum(
            row.id in prior_session_ids and row.status == "active"
            for row in scoped
            if row.id in prior_session_ids
        )
        reusable = sum(
            login_service.session_claims(session, token, now, touch=False)
            is not None
            for token in obsolete_bearers
        )
    constraints_valid, orphan_links = _auth_state_invariants(factory)
    return {
        "active_sessions": int(active),
        "session_resurrections": int(resurrections),
        "reusable_old_bearers": int(reusable),
        "orphan_links": int(orphan_links),
        "state_constraints_valid": constraints_valid,
    }


def _run_user_lifecycle_race(
    engine: Engine,
    factory: sessionmaker[Session],
    *,
    case_name: str,
    mobile: str,
) -> dict[str, Any]:
    from app.core.retention import (
        RetentionPolicy,
        anonymise_registration,
        delete_registration,
        purge_expired,
    )
    from app.models.registration import AuthSession, StudentRegistration, User
    from app.services import login_service, registration_service

    now = datetime.now(timezone.utc)
    expires_at = (
        now - timedelta(seconds=2)
        if case_name == "expiry_vs_session_resolve"
        else now + timedelta(days=1)
    )
    user_id, registration_id = _seed_active_registration(factory, mobile)
    prior_id, old_bearer = _seed_auth_session(
        factory, user_id, expires_at=expires_at
    )

    def lock_user(session: Session) -> bool:
        return session.scalar(
            select(User).where(User.id == user_id).with_for_update()
        ) is not None

    def rotate(session: Session) -> Mapping[str, Any]:
        registration = session.get(StudentRegistration, registration_id)
        try:
            raw, _ = login_service.rotate_authenticated_session(
                session, registration, now
            )
        except login_service.LoginError:
            session.rollback()
            return {"terminal": True, "kind": "rejected"}
        return {"terminal": True, "kind": "rotated", "wire": raw}

    def logout(session: Session) -> Mapping[str, Any]:
        login_service.logout(session, old_bearer, now)
        return {"terminal": True, "kind": "logout"}

    def anonymise(session: Session) -> Mapping[str, Any]:
        registration = session.get(StudentRegistration, registration_id)
        if registration is not None:
            anonymise_registration(session, registration)
        session.commit()
        return {"terminal": True, "kind": "anonymised"}

    def delete(session: Session) -> Mapping[str, Any]:
        registration = session.get(StudentRegistration, registration_id)
        if registration is not None:
            delete_registration(session, registration)
        session.commit()
        return {"terminal": True, "kind": "deleted"}

    def freeze_for_privacy_delete(session: Session) -> Mapping[str, Any]:
        registration, _ = registration_service.lock_registration_with_idempotency(
            session, registration_id
        )
        if registration is None:
            session.rollback()
            return {"terminal": False, "kind": "missing"}
        login_service.suspend_user_and_revoke_sessions(session, user_id, now)
        registration.status = "suspended"
        session.commit()
        return {"terminal": True, "kind": "frozen"}

    def expire(session: Session) -> Mapping[str, Any]:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(None, None, None, None, None, "anonymise"),
        )
        session.commit()
        return {"terminal": True, "kind": "expired"}

    def resolve(session: Session) -> Mapping[str, Any]:
        claims = login_service.session_claims(session, old_bearer, now)
        return {
            "terminal": True,
            "kind": "resolved" if claims is not None else "denied",
        }

    operations = {
        "rotation_vs_logout": (("rotate", rotate), ("logout", logout)),
        "rotation_vs_anonymise": (
            ("rotate", rotate),
            ("anonymise", anonymise),
        ),
        "rotation_vs_delete": (("rotate", rotate), ("delete", delete)),
        "privacy_delete_vs_verify_session_mint": (
            ("privacy", freeze_for_privacy_delete),
            ("verify", rotate),
        ),
        "expiry_vs_session_resolve": (
            ("expiry", expire),
            ("resolve", resolve),
        ),
        "logout_vs_verify": (("logout", logout), ("verify", rotate)),
    }
    first, second = operations[case_name]
    race = _run_controlled_pair(
        engine,
        factory,
        control_lock=lock_user,
        first=first,
        second=second,
    )
    outcomes = list(race["outcomes"])
    minted = tuple(
        str(row["wire"])
        for row in outcomes
        if row.get("kind") == "rotated" and isinstance(row.get("wire"), str)
    )
    destructive = case_name in {
        "rotation_vs_anonymise",
        "rotation_vs_delete",
        "privacy_delete_vs_verify_session_mint",
    }
    obsolete = (old_bearer, *minted) if destructive else (old_bearer,)
    state = _scoped_auth_race_state(
        factory,
        user_id=user_id,
        prior_session_ids=(prior_id,),
        obsolete_bearers=obsolete,
        now=now,
    )
    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        user = session.get(User, user_id)
        prior = session.get(AuthSession, prior_id)
    if case_name in {"rotation_vs_logout", "logout_vs_verify"}:
        coherent = bool(
            state["active_sessions"] == 1
            and state["reusable_old_bearers"] == 0
        )
    elif case_name == "rotation_vs_anonymise":
        coherent = bool(
            registration is not None
            and registration.status == "deleted"
            and state["active_sessions"] == 0
            and state["reusable_old_bearers"] == 0
        )
    elif case_name == "rotation_vs_delete":
        coherent = bool(
            registration is None
            and user is None
            and state["active_sessions"] == 0
            and state["reusable_old_bearers"] == 0
        )
    elif case_name == "privacy_delete_vs_verify_session_mint":
        coherent = bool(
            registration is not None
            and registration.status == "suspended"
            and user is not None
            and user.status == "suspended"
            and state["active_sessions"] == 0
            and state["reusable_old_bearers"] == 0
        )
    else:
        coherent = bool(
            prior is not None
            and prior.status == "expired"
            and _timestamp_equal(prior.revoked_at, prior.expires_at)
            and state["active_sessions"] == 0
            and state["reusable_old_bearers"] == 0
        )
    terminal = sum(row.get("terminal") is True for row in outcomes)
    return {
        "workers": 2,
        "backend_count": int(race["backend_count"]),
        "pg_lock_wait_observed": race["lock_wait_observed"] is True,
        "transactions_terminal": int(terminal),
        "active_sessions": int(state["active_sessions"]),
        "linearizable_outcome_exact": coherent,
        "session_resurrections": int(state["session_resurrections"]),
        "reusable_old_bearers": int(state["reusable_old_bearers"]),
        "orphan_links": int(state["orphan_links"]),
        "split_commits": int(race["split_commits"]),
        "timeouts": int(race["timeouts"]),
        "state_constraints_valid": state["state_constraints_valid"] is True,
    }


def _run_attempt_retention_verify_race(
    engine: Engine, factory: sessionmaker[Session], *, mobile: str
) -> dict[str, Any]:
    from app.core.crypto import otp_verifier
    from app.core.retention import RetentionPolicy, purge_expired
    from app.models.registration import (
        AuthSession,
        LoginAttempt,
        OtpChallenge,
        StudentRegistration,
    )
    from app.services import login_service, otp_authority

    now = datetime.now(timezone.utc)
    verify_now = now + timedelta(seconds=5)
    retention_now = now + timedelta(seconds=11)
    expires_at = now + timedelta(seconds=10)
    user_id, registration_id = _seed_active_registration(factory, mobile)
    code = "654321"
    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        authority = otp_authority.lock_or_create_authority(
            session,
            subject_hash=otp_authority.authority_subject_from_mobile_hash(
                registration.mobile_hash
            ),
            purpose="login",
            registration_id=registration_id,
            now=now,
        )
        salt = uuid.uuid4().hex
        challenge = OtpChallenge(
            registration_id=registration_id,
            authority_id=authority.id,
            purpose="login",
            verifier_hash=otp_verifier(code, salt=salt),
            attempts=0,
            max_attempts=3,
            expires_at=expires_at,
            delivery_state="active",
            metadata_json={"salt": salt},
        )
        authority.active_expires_at = expires_at
        session.add(challenge)
        session.flush()
        attempt = LoginAttempt(
            opaque_id=uuid.uuid4().hex,
            lookup_hash=registration.mobile_hash,
            registration_id=registration_id,
            challenge_id=challenge.id,
            status="pending",
            expires_at=expires_at,
        )
        session.add(attempt)
        session.commit()
        attempt_id = attempt.id
        challenge_id = challenge.id
        opaque_id = attempt.opaque_id

    def lock_attempt(session: Session) -> bool:
        return session.scalar(
            select(LoginAttempt)
            .where(LoginAttempt.id == attempt_id)
            .with_for_update()
        ) is not None

    def retain(session: Session) -> Mapping[str, Any]:
        purge_expired(
            session,
            now=retention_now,
            policy=RetentionPolicy(None, None, None, None, None, "anonymise"),
        )
        session.commit()
        return {"terminal": True, "kind": "retained"}

    def verify(session: Session) -> Mapping[str, Any]:
        try:
            raw, _ = login_service.verify(session, opaque_id, code, verify_now)
        except login_service.LoginError:
            session.rollback()
            return {"terminal": True, "kind": "rejected"}
        return {"terminal": True, "kind": "verified", "wire": raw}

    race = _run_controlled_pair(
        engine,
        factory,
        control_lock=lock_attempt,
        first=("retention", retain),
        second=("verify", verify),
    )
    outcomes = list(race["outcomes"])
    with factory() as session:
        attempt = session.get(LoginAttempt, attempt_id)
        challenge = session.get(OtpChallenge, challenge_id)
        active = int(
            session.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.user_id == user_id,
                    AuthSession.status == "active",
                )
            )
            or 0
        )
    retained_won = bool(
        attempt is not None
        and attempt.status == "expired"
        and _timestamp_equal(attempt.consumed_at, attempt.expires_at)
        and challenge is not None
        and challenge.consumed_at is None
        and active == 0
    )
    verified_won = bool(
        attempt is not None
        and attempt.status == "consumed"
        and challenge is not None
        and challenge.consumed_at is not None
        and active == 1
    )
    constraints_valid, orphan_links = _auth_state_invariants(factory)
    terminal = sum(row.get("terminal") is True for row in outcomes)
    coherent = bool(retained_won ^ verified_won)
    return {
        "workers": 2,
        "backend_count": int(race["backend_count"]),
        "pg_lock_wait_observed": race["lock_wait_observed"] is True,
        "transactions_terminal": int(terminal),
        "active_sessions": active,
        "linearizable_outcome_exact": coherent,
        "session_resurrections": 0,
        "reusable_old_bearers": 0,
        "orphan_links": int(orphan_links),
        "split_commits": int(race["split_commits"]),
        "timeouts": int(race["timeouts"]),
        "state_constraints_valid": constraints_valid,
    }


def _trace_position(
    trace: list[str], table: str, *, operation: str | None = None
) -> int | None:
    for index, statement in enumerate(trace):
        if table not in statement:
            continue
        if operation is not None and operation not in statement:
            continue
        return index
    return None


def _run_registration_retention_race(
    engine: Engine,
    factory: sessionmaker[Session],
    *,
    mode: str,
    mobile: str,
) -> dict[str, Any]:
    from sqlalchemy import event

    from app.core.retention import (
        RetentionPolicy,
        anonymise_registration,
        delete_registration,
        purge_expired,
    )
    from app.models.registration import (
        AuthSession,
        LoginAttempt,
        RecoverySession,
        StudentRegistration,
    )

    now = datetime.now(timezone.utc)
    old = now - timedelta(days=6)
    user_id, registration_id = _seed_active_registration(factory, mobile)
    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        recovery = RecoverySession(
            opaque_id=uuid.uuid4().hex,
            lookup_hash=registration.mobile_hash,
            registration_id=registration_id,
            challenge_id=None,
            status="pending",
            expires_at=old,
            consumed_at=None,
            created_at=old,
            updated_at=old,
        )
        attempt = _new_login_attempt(
            session,
            registration_id=registration_id,
            lookup_hash=registration.mobile_hash,
            status="pending",
            expires_at=old,
            consumed_at=None,
        )
        attempt.created_at = old
        attempt.updated_at = old
        auth_session, old_bearer = _new_auth_session_row(
            session,
            user_id=user_id,
            status="active",
            expires_at=old,
            revoked_at=None,
        )
        auth_session.created_at = old
        auth_session.updated_at = old
        session.add(recovery)
        session.commit()
        recovery_id = recovery.id
        attempt_id = attempt.id
        auth_session_id = auth_session.id
    with factory() as session:
        shared_recovery = int(
            session.scalar(
                select(func.count(RecoverySession.id)).where(
                    RecoverySession.id == recovery_id
                )
            )
            or 0
        )
        shared_attempts = int(
            session.scalar(
                select(func.count(LoginAttempt.id)).where(
                    LoginAttempt.id == attempt_id
                )
            )
            or 0
        )
        shared_sessions = int(
            session.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.id == auth_session_id
                )
            )
            or 0
        )

    def trace_statement(
        connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        trace = connection.info.get("nyay19_race_trace")
        if isinstance(trace, list):
            trace.append(" ".join(statement.casefold().split()))

    def lock_recovery(session: Session) -> bool:
        return session.scalar(
            select(RecoverySession)
            .where(RecoverySession.id == recovery_id)
            .with_for_update()
        ) is not None

    def retain(session: Session) -> Mapping[str, Any]:
        purge_expired(
            session,
            now=now,
            policy=RetentionPolicy(
                None,
                None,
                None,
                5,
                None,
                mode,
                login_attempt_days=5,
                auth_session_days=5,
            ),
        )
        session.commit()
        return {"terminal": True, "kind": "retained"}

    def erase(session: Session) -> Mapping[str, Any]:
        registration = session.get(StudentRegistration, registration_id)
        if registration is not None:
            operation = (
                anonymise_registration if mode == "anonymise" else delete_registration
            )
            operation(session, registration)
        session.commit()
        return {"terminal": True, "kind": "erased"}

    event.listen(engine, "before_cursor_execute", trace_statement)
    try:
        race = _run_controlled_pair(
            engine,
            factory,
            control_lock=lock_recovery,
            first=("retention", retain),
            second=("registration", erase),
        )
    finally:
        event.remove(engine, "before_cursor_execute", trace_statement)
    traces = race["traces"]
    retention_trace = traces["retention"]
    registration_trace = traces["registration"]
    recovery_delete = _trace_position(
        retention_trace, "delete from recovery_sessions"
    )
    auth_sweep = _trace_position(retention_trace, "from login_attempts")
    recovery_flushed_first = bool(
        recovery_delete is not None
        and auth_sweep is not None
        and recovery_delete < auth_sweep
    )
    lock_positions = [
        _trace_position(registration_trace, f"from {table}", operation="for update")
        for table in (
            "recovery_sessions",
            "login_attempts",
            "users",
            "auth_sessions",
        )
    ]
    canonical_order = bool(
        all(position is not None for position in lock_positions)
        and lock_positions == sorted(lock_positions)
        and len(set(lock_positions)) == len(lock_positions)
    )
    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        linked_recovery = int(
            session.scalar(
                select(func.count(RecoverySession.id)).where(
                    RecoverySession.registration_id == registration_id
                )
            )
            or 0
        )
        linked_attempts = int(
            session.scalar(
                select(func.count(LoginAttempt.id)).where(
                    LoginAttempt.registration_id == registration_id
                )
            )
            or 0
        )
        linked_sessions = int(
            session.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.user_id == user_id
                )
            )
            or 0
        )
    state = _scoped_auth_race_state(
        factory,
        user_id=user_id,
        prior_session_ids=(auth_session_id,),
        obsolete_bearers=(old_bearer,),
        now=now,
    )
    erased = bool(
        (registration is not None and registration.status == "deleted")
        if mode == "anonymise"
        else registration is None
    )
    coherent = bool(
        erased
        and linked_recovery == 0
        and linked_attempts == 0
        and linked_sessions == 0
        and state["active_sessions"] == 0
        and state["reusable_old_bearers"] == 0
    )
    outcomes = list(race["outcomes"])
    terminal = sum(row.get("terminal") is True for row in outcomes)
    return {
        "workers": 2,
        "backend_count": int(race["backend_count"]),
        "pg_lock_wait_observed": race["lock_wait_observed"] is True,
        "transactions_terminal": int(terminal),
        "active_sessions": int(state["active_sessions"]),
        "linearizable_outcome_exact": coherent,
        "session_resurrections": int(state["session_resurrections"]),
        "reusable_old_bearers": int(state["reusable_old_bearers"]),
        "orphan_links": int(state["orphan_links"]),
        "split_commits": int(race["split_commits"]),
        "timeouts": int(race["timeouts"]),
        "state_constraints_valid": state["state_constraints_valid"] is True,
        "shared_recovery_sessions": shared_recovery,
        "shared_login_attempts": shared_attempts,
        "shared_auth_sessions": shared_sessions,
        "recovery_rows_flushed_before_auth_sweep": recovery_flushed_first,
        "canonical_lock_order_observed": canonical_order,
    }


def _run_concurrency_probe(
    engine: Engine, factory: sessionmaker[Session]
) -> dict[str, Any]:
    """Run the exact ordered nine-case PostgreSQL serialization inventory."""

    observations: dict[str, Any] = {}
    user_cases = (
        "rotation_vs_logout",
        "rotation_vs_anonymise",
        "rotation_vs_delete",
        "privacy_delete_vs_verify_session_mint",
        "expiry_vs_session_resolve",
    )
    for index, case_name in enumerate(user_cases, start=1):
        observations[case_name] = _run_user_lifecycle_race(
            engine,
            factory,
            case_name=case_name,
            mobile=f"91910000{index:02d}",
        )
    observations["attempt_retention_vs_verify"] = (
        _run_attempt_retention_verify_race(
            engine, factory, mobile="9191000006"
        )
    )
    observations["logout_vs_verify"] = _run_user_lifecycle_race(
        engine,
        factory,
        case_name="logout_vs_verify",
        mobile="9191000007",
    )
    observations["registration_anonymise_vs_retention_worker"] = (
        _run_registration_retention_race(
            engine,
            factory,
            mode="anonymise",
            mobile="9191000008",
        )
    )
    observations["registration_delete_vs_retention_worker"] = (
        _run_registration_retention_race(
            engine,
            factory,
            mode="delete",
            mobile="9191000009",
        )
    )
    return {name: observations[name] for name in REQUIRED_RACE_CASES}


def _run_behavior_probe(scratch_url: str) -> dict[str, Any]:
    """Bind frozen retention seams through the current application schema."""

    from app.core.config import settings
    from app.core.crypto import KeyRing, override_keyring
    from app.services.otp_sender import CapturingSender

    original_environment = settings.app_env
    engine: Engine | None = None
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": os.urandom(32)},
            lookup_secret=os.urandom(32),
        )
    )
    settings.app_env = "testing"
    try:
        upgrade = _run_alembic(scratch_url, "upgrade", APPLICATION_HEAD)
        if upgrade["returncode"] != 0:
            raise ProductGateFailure(
                "behavior probe could not install current application head"
            )
        engine = create_engine(scratch_url, poolclass=NullPool)
        if (
            _current_revision(engine) != APPLICATION_HEAD
            or _revision_row_count(engine) != 1
        ):
            raise ProductGateFailure(
                "behavior probe did not reach current application head"
            )
        sender = CapturingSender()
        app, factory = _build_behavior_app(engine, sender)
        return {
            "config": _run_config_probe(),
            "logout_expiry": _run_logout_expiry_probe(engine, app, factory),
            "rotation": _run_rotation_probe(app, factory, sender),
            "attempt_retention": _run_attempt_retention_probe(factory),
            "session_anonymise": _run_session_retention_probe(
                factory, mode="anonymise", mobile_offset=300
            ),
            "session_delete": _run_session_retention_probe(
                factory, mode="delete", mobile_offset=400
            ),
            "registration_anonymise": _run_registration_erasure_probe(
                engine,
                factory,
                mode="anonymise",
                mobile="9100000040",
            ),
            "registration_delete": _run_registration_erasure_probe(
                engine,
                factory,
                mode="delete",
                mobile="9100000041",
            ),
            "privacy_delete": _run_privacy_delete_probe(
                engine, app, factory, sender
            ),
            "concurrency": _run_concurrency_probe(engine, factory),
            "audit": _run_audit_probe(factory),
        }
    finally:
        settings.app_env = original_environment
        override_keyring(None)
        if engine is not None:
            engine.dispose()


def _assemble_assertions(
    observations: Mapping[str, Any], harness: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Map private exact observations into the fixed aggregate inventory."""

    return [
        _assertion(
            REQUIRED_ASSERTION_IDS[0],
            _runtime_observation_passes(observations["runtime"]),
            cases=1,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[1],
            _migration_observation_passes(observations["migration"]),
            lifecycle_steps=5,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[2],
            _populated_migration_observation_passes(observations["populated"]),
            populated_rows=6,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[3],
            _schema_observation_passes(observations["schema"]),
            tables=2,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[4],
            _config_observation_passes(observations["config"]),
            invalid_cases=15,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[5],
            _logout_expiry_observation_passes(observations["logout_expiry"]),
            cases=4,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[6],
            _rotation_observation_passes(observations["rotation"]),
            cases=2,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[7],
            _attempt_retention_observation_passes(observations["attempt_retention"]),
            cases=12,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[8],
            _session_retention_observation_passes(
                observations["session_anonymise"], mode="anonymise"
            ),
            cases=7,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[9],
            _session_retention_observation_passes(
                observations["session_delete"], mode="delete"
            ),
            cases=7,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[10],
            _registration_erasure_observation_passes(
                observations["registration_anonymise"], mode="anonymise"
            ),
            cases=2,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[11],
            _registration_erasure_observation_passes(
                observations["registration_delete"], mode="delete"
            ),
            cases=2,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[12],
            _privacy_delete_observation_passes(observations["privacy_delete"]),
            cases=4,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[13],
            _concurrency_observation_passes(observations["concurrency"]),
            cases=len(REQUIRED_RACE_CASES),
            workers=2,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[14],
            _audit_observation_passes(observations["audit"]),
            cases=2,
        ),
        _assertion(
            REQUIRED_ASSERTION_IDS[15],
            _harness_observation_passes(harness),
            named_probe_ids=len(REQUIRED_MUTANT_IDS),
            distinct_probe_variants=len(DISTINCT_MUTANT_IDS),
            duplicate_aliases=len(MUTANT_ALIAS_OF),
            scratch_databases=3,
        ),
    ]


def _oracle_baselines() -> dict[str, Any]:
    """Return synthetic aggregate observations used only for mutant closure."""

    migration = {
        "historical_bytes_immutable": True,
        "historical_file_inventory_exact": True,
        "historical_hash_inventory_exact": True,
        "post_ddl_exact_head_validation": True,
        "post_ddl_validation_failure_rolled_back": True,
        "pinned_release_exact": True,
        "parent_upgrade_returncode": 0,
        "head_upgrade_returncode": 0,
        "head_revision_exact": True,
        "revision_rows": 1,
        "parent_schema_roundtrip_exact": True,
        "parent_rows_roundtrip_exact": True,
        "invalid_upgrade_refused_unchanged": True,
    }
    populated = {
        "login_rows": 3,
        "session_rows": 3,
        "login_expiry_backfilled": True,
        "session_revocation_backfilled": True,
        "live_rows_preserved": True,
        "erased_login_shape_exact": True,
        "erased_session_shape_exact": True,
        "erased_downgrade_refused": True,
        "legacy_delete_corrupt_cases": 5,
        "legacy_delete_preflight_rejects_corrupt_target": True,
        "legacy_delete_downgrade_marker_refuses": True,
        "legacy_delete_backfill_aggregate_audit_exact": True,
        "refusal_schema_unchanged": True,
        "refusal_rows_unchanged": True,
    }
    schema = {
        "table_inventory_exact": True,
        "column_inventory_exact": True,
        "types_nullability_defaults_exact": True,
        "primary_keys_exact": True,
        "foreign_keys_exact": True,
        "unique_constraints_exact": True,
        "constraint_catalog_safety_exact": True,
        "indexes_exact": True,
        "index_catalog_safety_exact": True,
        "partial_active_index_exact": True,
        "check_names_exact": True,
        "check_semantics_exact": True,
        "model_metadata_matches": True,
    }
    config = {
        "unset_login_window_is_none": True,
        "unset_session_window_is_none": True,
        "empty_login_env_is_none": True,
        "empty_session_env_is_none": True,
        "all_documented_empty_env_is_none": True,
        "noncanonical_text_rejected": True,
        "unset_windows_noop": True,
        "minimum_window_days": 1,
        "maximum_window_days": 36500,
        "accepted_modes": ["anonymise", "delete"],
        "invalid_values_rejected_before_mutation": True,
        "statutory_duration_absent": True,
    }
    logout = {
        "logout_status": 200,
        "logout_active_sessions": 0,
        "logout_replay_authenticated": False,
        "logout_audit_count": 1,
        "expired_discovery_authenticated": False,
        "expired_status_exact": True,
        "expired_terminal_uses_expires_at": True,
        "auth_cookie_clear": True,
        "flow_cookie_clear": True,
        "cookie_contract": dict(EXPECTED_COOKIE_CONTRACT),
        "untrusted_origin_status": 403,
        "untrusted_origin_state_unchanged": True,
    }
    rotation = {
        "first_verify_status": 200,
        "second_verify_status": 200,
        "active_sessions": 1,
        "revoked_sessions": 1,
        "old_cookie_authenticated": False,
        "new_cookie_authenticated": True,
        "old_cookie_cleared": True,
        "database_tokens_are_hashes": True,
        "wire_tokens_absent_from_database": True,
    }
    attempts = {
        "real_expired_terminalized": True,
        "decoy_expired_terminalized": True,
        "terminal_time_uses_expires_at": True,
        "strictly_older_real_affected": True,
        "strictly_older_decoy_affected": True,
        "at_cutoff_real_unchanged": True,
        "at_cutoff_decoy_unchanged": True,
        "recent_real_unchanged": True,
        "recent_decoy_unchanged": True,
        "unset_window_unchanged": True,
        "anonymise_shape_exact": True,
        "delete_rows_absent": True,
        "rollback_restores_all_rows": True,
    }

    def session(mode: str) -> dict[str, Any]:
        return {
            "mode": mode,
            "expired_active_terminalized": True,
            "expiry_terminal_uses_expires_at": True,
            "strictly_older_affected": True,
            "at_cutoff_unchanged": True,
            "recent_unchanged": True,
            "active_unchanged": True,
            "unset_window_unchanged": True,
            "result_shape_exact": True,
            "bearer_replay_denied": True,
            "rollback_restores_all_rows": True,
        }

    def registration(mode: str) -> dict[str, Any]:
        expected_after = 2 if mode == "anonymise" else 0
        return {
            "mode": mode,
            "active_sessions_before": 1,
            "active_sessions_after": 0,
            "attempts_before": 2,
            "sessions_before": 2,
            "attempts_after": expected_after,
            "sessions_after": expected_after,
            "bearer_replay_denied": True,
            "attempt_shape_exact": True,
            "session_shape_exact": True,
            "orphan_links": 0,
            "rollback_restores_graph": True,
        }

    privacy_delete = {
        "accepted_status": 202,
        "request_rows": 1,
        "job_rows": 1,
        "proof_consumed": True,
        "user_suspended": True,
        "registration_suspended": True,
        "active_sessions": 0,
        "bearer_replay_denied": True,
        "auth_cookie_clear": True,
        "flow_cookie_clear": True,
        "cookie_contract": dict(EXPECTED_COOKIE_CONTRACT),
        "atomic_rollback_restores_all": True,
        "legacy_accepted_cases": 2,
        "legacy_accounts_frozen": 2,
        "legacy_registrations_frozen": 2,
        "legacy_active_sessions": 0,
        "legacy_idempotent_second_pass": True,
    }
    race = {
        "workers": 2,
        "backend_count": 2,
        "pg_lock_wait_observed": True,
        "transactions_terminal": 2,
        "active_sessions": 0,
        "linearizable_outcome_exact": True,
        "session_resurrections": 0,
        "reusable_old_bearers": 0,
        "orphan_links": 0,
        "split_commits": 0,
        "timeouts": 0,
        "state_constraints_valid": True,
    }
    concurrency = {name: deepcopy(race) for name in REQUIRED_RACE_CASES}
    for name in REGISTRATION_RETENTION_RACE_CASES:
        concurrency[name].update(
            {
                "shared_recovery_sessions": 1,
                "shared_login_attempts": 1,
                "shared_auth_sessions": 1,
                "recovery_rows_flushed_before_auth_sweep": True,
                "canonical_lock_order_observed": True,
            }
        )
    audit = {
        "action_exact": True,
        "resource_type_exact": True,
        "aggregate_keys_exact": True,
        "aggregate_integer_counts": True,
        "zero_count_run_has_no_event": True,
        "identifiers_absent": True,
        "contact_data_absent": True,
        "bearers_absent": True,
        "row_hashes_absent": True,
    }
    scratch = {
        "created": 3,
        "removed": 3,
        "cleanup_failed": 0,
        "all_created_removed": True,
        "inventory_match": True,
        "baseline_count": 0,
        "final_count": 0,
        "purposes": ["migration_lifecycle", "migration_populated", "behavior"],
    }
    return {
        "runtime": {
            "server_version_num": 160000,
            "postgres_major": 16,
            "pgvector_present": True,
        },
        "migration": migration,
        "populated": populated,
        "schema": schema,
        "config": config,
        "logout_expiry": logout,
        "rotation": rotation,
        "attempt_retention": attempts,
        "session_anonymise": session("anonymise"),
        "session_delete": session("delete"),
        "registration_anonymise": registration("anonymise"),
        "registration_delete": registration("delete"),
        "privacy_delete": privacy_delete,
        "concurrency": concurrency,
        "audit": audit,
        "scratch": scratch,
    }


def _seeded_mutant_results() -> dict[str, bool]:
    """Prove each named unsafe variant turns its exact oracle red."""

    baseline = _oracle_baselines()

    def killed(
        evaluator: Callable[[Mapping[str, Any]], bool],
        observation: Mapping[str, Any],
        field: str,
        unsafe: Any,
    ) -> bool:
        mutant = deepcopy(dict(observation))
        mutant[field] = unsafe
        return bool(evaluator(observation) and not evaluator(mutant))

    results: dict[str, bool] = {}
    results["ACCEPT-POSTGRES-15"] = killed(
        _runtime_observation_passes,
        baseline["runtime"],
        "server_version_num",
        159999,
    )
    results["ACCEPT-MISSING-PGVECTOR"] = killed(
        _runtime_observation_passes,
        baseline["runtime"],
        "pgvector_present",
        False,
    )
    results["REWRITE-HISTORICAL-MIGRATION"] = killed(
        _migration_observation_passes,
        baseline["migration"],
        "historical_bytes_immutable",
        False,
    )
    results["HISTORICAL-INVENTORY-MISSING"] = killed(
        _migration_observation_passes,
        baseline["migration"],
        "historical_file_inventory_exact",
        False,
    )
    results["HISTORICAL-INVENTORY-EXTRA"] = killed(
        _migration_observation_passes,
        baseline["migration"],
        "historical_hash_inventory_exact",
        False,
    )
    results["SKIP-POST-DDL-EXACT-HEAD-VALIDATION"] = killed(
        _migration_observation_passes,
        baseline["migration"],
        "post_ddl_exact_head_validation",
        False,
    )
    results["POST-DDL-VALIDATION-FAILURE-PERSISTS"] = killed(
        _migration_observation_passes,
        baseline["migration"],
        "post_ddl_validation_failure_rolled_back",
        False,
    )
    results["SKIP-POPULATED-BACKFILL"] = killed(
        _populated_migration_observation_passes,
        baseline["populated"],
        "login_expiry_backfilled",
        False,
    )
    results["ALLOW-ERASED-DOWNGRADE"] = killed(
        _populated_migration_observation_passes,
        baseline["populated"],
        "erased_downgrade_refused",
        False,
    )
    erased_missing = deepcopy(baseline["populated"])
    erased_missing["erased_downgrade_refused"] = False
    marker_missing = deepcopy(baseline["populated"])
    marker_missing["legacy_delete_downgrade_marker_refuses"] = False
    results["COUPLE-ERASED-REFUSAL-TO-LEGACY-MARKER"] = bool(
        erased_missing["legacy_delete_downgrade_marker_refuses"] is True
        and marker_missing["erased_downgrade_refused"] is True
        and not _populated_migration_observation_passes(erased_missing)
        and not _populated_migration_observation_passes(marker_missing)
    )
    results["ACCEPT-CORRUPT-LEGACY-DELETION-TARGET"] = killed(
        _populated_migration_observation_passes,
        baseline["populated"],
        "legacy_delete_preflight_rejects_corrupt_target",
        False,
    )
    results["ACCEPT-MISSING-LEGACY-DELETION-JOB"] = killed(
        _populated_migration_observation_passes,
        baseline["populated"],
        "legacy_delete_preflight_rejects_corrupt_target",
        False,
    )
    results["OMIT-LEGACY-DOWNGRADE-MARKER"] = killed(
        _populated_migration_observation_passes,
        baseline["populated"],
        "legacy_delete_downgrade_marker_refuses",
        False,
    )
    results["MUTATE-APPEND-ONLY-AUDIT-EVENTS"] = bool(
        _gate_preserves_append_only_audit_events()
        and not _gate_preserves_append_only_audit_events(
            "DELETE FROM " + "audit_events WHERE action = 'hostile'"
        )
        and not _gate_preserves_append_only_audit_events(
            "UPDATE " + "audit_events SET action = 'hostile'"
        )
        and not _gate_preserves_append_only_audit_events(
            'statement = text("DELETE FROM " + "audit_events")'
        )
    )
    results["RELAX-SESSION-USER-NULLABILITY"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "types_nullability_defaults_exact",
        False,
    )
    for identifier in (
        "NULLABLE-LOGIN-LOOKUP",
        "NULLABLE-SESSION-TOKEN",
        "AUTH-COLUMN-WRONG-TYPE",
        "AUTH-COLUMN-WRONG-LENGTH",
        "AUTH-COLUMN-WRONG-DEFAULT",
        "AUTH-COLUMN-WRONG-TIMEZONE",
    ):
        results[identifier] = killed(
            _schema_observation_passes,
            baseline["schema"],
            "types_nullability_defaults_exact",
            False,
        )
    results["AUTH-PK-DRIFT"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "primary_keys_exact",
        False,
    )
    results["AUTH-PK-CATALOG-DEFERRABLE"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "constraint_catalog_safety_exact",
        False,
    )
    results["AUTH-PK-CATALOG-NO-INHERIT-FALSE"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "constraint_catalog_safety_exact",
        False,
    )
    results["AUTH-UQ-CATALOG-NO-INHERIT-FALSE"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "constraint_catalog_safety_exact",
        False,
    )
    results["AUTH-PK-INCLUDE-DRIFT"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "index_catalog_safety_exact",
        False,
    )
    for identifier in ("AUTH-FK-DRIFT", "AUTH-FK-OPTIONS-DRIFT"):
        results[identifier] = killed(
            _schema_observation_passes,
            baseline["schema"],
            "foreign_keys_exact",
            False,
        )
    results["AUTH-FK-CATALOG-NOT-VALID"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "constraint_catalog_safety_exact",
        False,
    )
    results["AUTH-FK-CATALOG-NO-INHERIT-FALSE"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "constraint_catalog_safety_exact",
        False,
    )
    results["DUPLICATE-NAMED-FK-PRECEDES-EXPECTED"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "foreign_keys_exact",
        False,
    )
    for identifier in (
        "AUTH-CHECK-SQL-DRIFT",
        "AUTH-CHECK-NOT-VALID",
        "AUTH-CHECK-NO-INHERIT",
    ):
        results[identifier] = killed(
            _schema_observation_passes,
            baseline["schema"],
            "check_semantics_exact",
            False,
        )
    results["DUPLICATE-NAMED-CHECK-PRECEDES-EXPECTED"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "check_names_exact",
        False,
    )
    results["AUTH-UQ-DRIFT"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "unique_constraints_exact",
        False,
    )
    for identifier in (
        "AUTH-UQ-BACKING-INDEX-MISSING",
        "AUTH-UQ-BACKING-INDEX-EXTRA",
        "AUTH-UQ-BACKING-INDEX-NAME-DRIFT",
        "AUTH-UQ-BACKING-INDEX-DUPLICATE-LINK-DRIFT",
        "AUTH-UQ-BACKING-INDEX-COLUMNS-DRIFT",
        "AUTH-UQ-BACKING-INDEX-UNIQUENESS-DRIFT",
        "AUTH-UQ-BACKING-INDEX-PREDICATE-DRIFT",
        "AUTH-UQ-BACKING-INDEX-INCLUDE-DRIFT",
        "AUTH-UQ-BACKING-INDEX-OPTIONS-DRIFT",
    ):
        results[identifier] = killed(
            _schema_observation_passes,
            baseline["schema"],
            "indexes_exact",
            False,
        )
    results["AUTH-UQ-CATALOG-DEFERRABLE"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "constraint_catalog_safety_exact",
        False,
    )
    results["DUPLICATE-NAMED-UQ-PRECEDES-EXPECTED"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "unique_constraints_exact",
        False,
    )
    results["AUTH-INDEX-PREDICATE-DRIFT"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "partial_active_index_exact",
        False,
    )
    for identifier in (
        "AUTH-INDEX-UNIQUENESS-DRIFT",
        "AUTH-INDEX-OPTIONS-DRIFT",
    ):
        results[identifier] = killed(
            _schema_observation_passes,
            baseline["schema"],
            "indexes_exact",
            False,
        )
    results["AUTH-INDEX-CATALOG-INVALID"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "index_catalog_safety_exact",
        False,
    )
    results["AUTH-INDEX-CATALOG-UNREADY"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "index_catalog_safety_exact",
        False,
    )
    results["AUTH-INDEX-CATALOG-DEAD"] = killed(
        _schema_observation_passes,
        baseline["schema"],
        "index_catalog_safety_exact",
        False,
    )
    results["ALLOW-ZERO-RETENTION-WINDOW"] = killed(
        _config_observation_passes,
        baseline["config"],
        "minimum_window_days",
        0,
    )
    results["REJECT-DOCUMENTED-BLANK-RETENTION"] = killed(
        _config_observation_passes,
        baseline["config"],
        "all_documented_empty_env_is_none",
        False,
    )
    results["ACCEPT-WHITESPACE-RETENTION"] = killed(
        _config_observation_passes,
        baseline["config"],
        "noncanonical_text_rejected",
        False,
    )
    results["ALLOW-UNKNOWN-RETENTION-MODE"] = killed(
        _config_observation_passes,
        baseline["config"],
        "accepted_modes",
        ["anonymise", "delete", "archive"],
    )
    results["LOGOUT-LEAVES-ACTIVE-SESSION"] = killed(
        _logout_expiry_observation_passes,
        baseline["logout_expiry"],
        "logout_active_sessions",
        1,
    )
    cookie_drift = deepcopy(baseline["logout_expiry"])
    cookie_drift["cookie_contract"]["auth_path"] = "/api/v1"
    results["LOGOUT-COOKIE-PATH-DRIFT"] = bool(
        _logout_expiry_observation_passes(baseline["logout_expiry"])
        and not _logout_expiry_observation_passes(cookie_drift)
    )
    cookie_names = ("auth_session", "otp_flow")

    def cookie_header(
        name: str,
        *,
        secure: bool = False,
        path: str | None = None,
    ) -> str:
        path = path or ("/" if name.endswith("session") else "/api/v1")
        same_site = (
            "lax" if name.endswith("session") and path == "/" else "strict"
        )
        return (
            f'{name}=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; '
            f"Max-Age=0; Path={path}; SameSite={same_site}"
            + ("; Secure" if secure else "")
        )

    def parser_rejects(headers: list[str], *, secure: bool = False) -> bool:
        contract, cleared = _cookie_clear_contract(
            headers,
            names=cookie_names,
            secure=secure,
        )
        return bool(
            not _cookie_contract_observation_passes(contract)
            or not all(cleared.values())
        )

    cookie_headers = [
        cookie_header("auth_session", path="/"),
        cookie_header("auth_session", path="/api/v1"),
        cookie_header("otp_flow"),
    ]
    results["COOKIE-ATTRIBUTE-VALUE-CASING-DRIFT"] = parser_rejects(
        [
            cookie_headers[0].replace("SameSite=lax", "SameSite=Lax"),
            *cookie_headers[1:],
        ]
    )
    secure_headers = [
        cookie_header("auth_session", secure=True, path="/"),
        cookie_header("auth_session", secure=True, path="/api/v1"),
        cookie_header("otp_flow", secure=True),
    ]
    results["COOKIE-ATTRIBUTE-SUBSTRING-ACCEPTED"] = parser_rejects(
        [
            secure_headers[0].replace("; Secure", "; VerySecure"),
            *secure_headers[1:],
        ],
        secure=True,
    )
    results["COOKIE-DUPLICATE-HEADER-ACCEPTED"] = parser_rejects(
        [*cookie_headers, cookie_headers[0]]
    )
    results["COOKIE-DUPLICATE-ATTRIBUTE-ACCEPTED"] = parser_rejects(
        [f"{cookie_headers[0]}; Path=/", *cookie_headers[1:]]
    )
    results["COOKIE-MISSING-HEADER-ACCEPTED"] = parser_rejects(
        cookie_headers[:1]
    )
    results["COOKIE-DOMAIN-ACCEPTED"] = parser_rejects(
        [f"{cookie_headers[0]}; Domain=example.invalid", *cookie_headers[1:]]
    )
    results["COOKIE-SECURE-PARITY-DRIFT"] = parser_rejects(
        [f"{cookie_headers[0]}; Secure", *cookie_headers[1:]]
    )
    for identifier, value in (
        ("COOKIE-VALUED-SECURE-FALSE-ACCEPTED", "false"),
        ("COOKIE-VALUED-SECURE-ZERO-ACCEPTED", "0"),
        ("COOKIE-VALUED-SECURE-EMPTY-ACCEPTED", ""),
    ):
        results[identifier] = parser_rejects(
            [f"{cookie_headers[0]}; Secure={value}", *cookie_headers[1:]]
        )
    cookie_type_drift = deepcopy(baseline["logout_expiry"])
    cookie_type_drift["cookie_contract"]["http_only"] = 1
    results["COOKIE-CONTRACT-TYPE-COERCION"] = bool(
        _logout_expiry_observation_passes(baseline["logout_expiry"])
        and not _logout_expiry_observation_passes(cookie_type_drift)
    )
    results["EXPIRY-USES-SWEEP-TIME"] = killed(
        _logout_expiry_observation_passes,
        baseline["logout_expiry"],
        "expired_terminal_uses_expires_at",
        False,
    )
    results["ROTATION-ACCEPTS-OLD-COOKIE"] = killed(
        _rotation_observation_passes,
        baseline["rotation"],
        "old_cookie_authenticated",
        True,
    )
    results["ROTATION-CREATES-TWO-ACTIVE"] = killed(
        _rotation_observation_passes,
        baseline["rotation"],
        "active_sessions",
        2,
    )
    results["SKIP-DECOY-ATTEMPT-PURGE"] = killed(
        _attempt_retention_observation_passes,
        baseline["attempt_retention"],
        "strictly_older_decoy_affected",
        False,
    )
    results["CUT-OFF-INCLUSIVE"] = killed(
        _attempt_retention_observation_passes,
        baseline["attempt_retention"],
        "at_cutoff_real_unchanged",
        False,
    )
    results["UNSET-WINDOW-MUTATES"] = killed(
        _attempt_retention_observation_passes,
        baseline["attempt_retention"],
        "unset_window_unchanged",
        False,
    )
    results["ANONYMISE-RETAINS-BEARER-HASH"] = killed(
        lambda value: _session_retention_observation_passes(
            value, mode="anonymise"
        ),
        baseline["session_anonymise"],
        "result_shape_exact",
        False,
    )
    results["DELETE-LEAVES-SESSION"] = killed(
        lambda value: _session_retention_observation_passes(value, mode="delete"),
        baseline["session_delete"],
        "result_shape_exact",
        False,
    )
    results["REGISTRATION-ERASURE-LEAVES-LINK"] = killed(
        lambda value: _registration_erasure_observation_passes(
            value, mode="anonymise"
        ),
        baseline["registration_anonymise"],
        "orphan_links",
        1,
    )
    results["PRIVACY-DELETE-NONATOMIC-FREEZE"] = killed(
        _privacy_delete_observation_passes,
        baseline["privacy_delete"],
        "atomic_rollback_restores_all",
        False,
    )
    results["SKIP-LEGACY-ACCEPTED-DELETION"] = killed(
        _privacy_delete_observation_passes,
        baseline["privacy_delete"],
        "legacy_accounts_frozen",
        1,
    )
    results["SKIP-LEGACY-REGISTRATION-FREEZE"] = killed(
        _privacy_delete_observation_passes,
        baseline["privacy_delete"],
        "legacy_registrations_frozen",
        0,
    )
    omitted_race = deepcopy(baseline["concurrency"])
    omitted_race.pop(REQUIRED_RACE_CASES[-1])
    results["OMIT-ONE-RACE"] = bool(
        _concurrency_observation_passes(baseline["concurrency"])
        and not _concurrency_observation_passes(omitted_race)
    )
    for identifier, case_name in (
        (
            "OMIT-REGISTRATION-ANONYMISE-RETENTION-RACE",
            "registration_anonymise_vs_retention_worker",
        ),
        (
            "OMIT-REGISTRATION-DELETE-RETENTION-RACE",
            "registration_delete_vs_retention_worker",
        ),
    ):
        mutant = deepcopy(baseline["concurrency"])
        mutant.pop(case_name)
        results[identifier] = bool(
            _concurrency_observation_passes(baseline["concurrency"])
            and not _concurrency_observation_passes(mutant)
        )
    inverted = deepcopy(baseline["concurrency"])
    inverted["registration_anonymise_vs_retention_worker"][
        "recovery_rows_flushed_before_auth_sweep"
    ] = False
    results["RETENTION-SWEEP-BEFORE-RECOVERY-FLUSH"] = bool(
        _concurrency_observation_passes(baseline["concurrency"])
        and not _concurrency_observation_passes(inverted)
    )
    resurrected = deepcopy(baseline["concurrency"])
    resurrected[REQUIRED_RACE_CASES[0]]["session_resurrections"] = 1
    results["RACE-ALLOWS-SESSION-RESURRECTION"] = bool(
        _concurrency_observation_passes(baseline["concurrency"])
        and not _concurrency_observation_passes(resurrected)
    )
    observed_double_commit = _observed_split_commits(
        [
            {"commits": 2, "rollbacks": 0},
            {"commits": 0, "rollbacks": 1},
        ]
    )
    coherent_double_commit = deepcopy(
        baseline["concurrency"][REQUIRED_RACE_CASES[0]]
    )
    coherent_double_commit["split_commits"] = observed_double_commit
    results["RACE-COHERENT-DOUBLE-COMMIT"] = bool(
        observed_double_commit == 1
        and coherent_double_commit["linearizable_outcome_exact"] is True
        and not _race_case_passes(coherent_double_commit)
    )
    results["RACE-SPLIT-COMMIT-TAUTOLOGY"] = bool(
        _observed_split_commits(
            [
                {"commits": 1, "rollbacks": 0},
                {"commits": 0, "rollbacks": 1},
            ]
        )
        == 0
        and observed_double_commit != (
            0
            if coherent_double_commit["linearizable_outcome_exact"] is True
            else 1
        )
    )
    results["AUDIT-CONTAINS-IDENTIFIER"] = killed(
        _audit_observation_passes,
        baseline["audit"],
        "identifiers_absent",
        False,
    )
    results["SCRATCH-CLEANUP-NOT-FINAL"] = killed(
        _scratch_cleanup_observation_passes,
        baseline["scratch"],
        "removed",
        2,
    )
    results["SCRATCH-CREATE-ORPHAN-NOT-COMPENSATED"] = killed(
        _scratch_cleanup_observation_passes,
        baseline["scratch"],
        "inventory_match",
        False,
    )
    results["SCRATCH-CREATE-CLEANUP-UNCERTAINTY-IGNORED"] = killed(
        _scratch_cleanup_observation_passes,
        baseline["scratch"],
        "cleanup_failed",
        1,
    )
    passing = [_assertion(identifier, True) for identifier in REQUIRED_ASSERTION_IDS]
    results["ASSERTION-INVENTORY-REORDERED"] = bool(
        _evaluate_assertions(passing)["overall_pass"]
        and not _evaluate_assertions(list(reversed(passing)))["overall_pass"]
    )
    return results


def _seeded_mutants_are_killed() -> bool:
    results = _seeded_mutant_results()
    inventory = _mutant_inventory(results)
    return bool(
        tuple(results) == REQUIRED_MUTANT_IDS
        and all(value is True for value in results.values())
        and _mutant_inventory_observation_passes(inventory)
    )


def _blocked_report(reason: str) -> dict[str, Any]:
    return {
        "gate": "nyay19_postgres_auth_retention",
        "status": "BLOCKED",
        "executed": False,
        "reason": reason,
        "assertion_ids": list(REQUIRED_ASSERTION_IDS),
    }


def run_gate(base: URL) -> dict[str, Any]:
    """Run the authoritative three-scratch gate and emit aggregate evidence."""

    runtime = _runtime_probe(base)
    if not _runtime_observation_passes(runtime):
        raise Blocked("PostgreSQL 16 plus pgvector is required")
    if not _historical_migration_bytes_unchanged():
        raise ProductGateFailure("immutable migration history changed")

    manager = _ScratchDatabaseManager(base)
    lifecycle = manager.run(
        "migration_lifecycle", _run_migration_lifecycle_probe
    )
    populated = manager.run(
        "migration_populated", _run_populated_migration_probe
    )
    behavior = manager.run("behavior", _run_behavior_probe)
    scratch = manager.summary()

    erased_refusal = lifecycle["erased_refusal"]
    if not isinstance(erased_refusal, Mapping) or not _exact_keys(
        erased_refusal,
        {"downgrade_refused", "schema_unchanged", "rows_unchanged"},
    ):
        raise ProductGateFailure("erased downgrade evidence was not exact")
    populated_observation = dict(populated["observation"])
    populated_observation.update(
        {
            "erased_downgrade_refused": (
                erased_refusal["downgrade_refused"] is True
            ),
            "refusal_schema_unchanged": (
                erased_refusal["schema_unchanged"] is True
            ),
            "refusal_rows_unchanged": erased_refusal["rows_unchanged"] is True,
        }
    )
    privacy_delete = dict(behavior["privacy_delete"])
    legacy = populated["legacy"]
    privacy_delete.update(
        {
            "legacy_accepted_cases": int(legacy["accepted_cases"]),
            "legacy_accounts_frozen": int(legacy["accounts_frozen"]),
            "legacy_registrations_frozen": int(
                legacy["registrations_frozen"]
            ),
            "legacy_active_sessions": int(legacy["active_sessions"]),
            "legacy_idempotent_second_pass": (
                legacy["idempotent_second_pass"] is True
            ),
        }
    )
    observations = {
        "runtime": runtime,
        "migration": lifecycle["observation"],
        "populated": populated_observation,
        "schema": lifecycle["schema"],
        **{
            key: value
            for key, value in behavior.items()
            if key != "privacy_delete"
        },
        "privacy_delete": privacy_delete,
        "scratch": scratch,
    }
    mutants = _seeded_mutant_results()
    mutant_inventory = _mutant_inventory(mutants)
    private_evidence = {
        "observations": observations,
        "named_probe_results": mutants,
        "mutant_inventory": mutant_inventory,
    }
    privacy_findings = len(_privacy_findings(private_evidence))
    harness = {
        "mutants": mutants,
        "mutant_inventory": mutant_inventory,
        "privacy_scanned": True,
        "privacy_findings": privacy_findings,
        "scratch": scratch,
        "behavior_adapter_frozen": True,
        "native_postgres_executed": True,
    }
    assertions = _assemble_assertions(observations, harness)
    evaluation = _evaluate_assertions(assertions)
    return {
        "gate": "nyay19_postgres_auth_retention",
        "status": "PASS" if evaluation["overall_pass"] else "FAIL",
        "executed": True,
        "assertions": assertions,
        "assertion_summary": evaluation,
        "mutant_inventory": mutant_inventory,
        "race_cases": len(REQUIRED_RACE_CASES),
        "scratch": {
            "created": scratch["created"],
            "removed": scratch["removed"],
            "cleanup_failed": scratch["cleanup_failed"],
            "all_created_removed": scratch["all_created_removed"],
        },
        "privacy_findings": privacy_findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--database-url", default=os.getenv("NYAY19_POSTGRES_ADMIN_URL")
    )
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)

    if not arguments.execute or os.getenv(OPT_IN_ENV) != "1":
        report = _blocked_report("explicit execution opt-in is required")
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return BLOCKED_EXIT
    try:
        if not arguments.database_url:
            raise Blocked("an explicit loopback PostgreSQL control URL is required")
        report = run_gate(_safe_local_postgres_url(arguments.database_url))
        exit_code = 0 if report.get("status") == "PASS" else 1
    except Blocked as exc:
        report = _blocked_report(str(exc))
        exit_code = BLOCKED_EXIT
    except Exception:  # never copy exception or database details into evidence
        report = {
            "gate": "nyay19_postgres_auth_retention",
            "status": "FAIL",
            "executed": True,
            "reason": "authoritative gate rejected product or harness state",
        }
        exit_code = 1

    findings = _privacy_findings(report)
    if findings:
        report = {
            "gate": "nyay19_postgres_auth_retention",
            "status": "FAIL",
            "executed": report.get("executed") is True,
            "reason": "aggregate evidence privacy validation failed",
            "privacy_findings": len(findings),
        }
        exit_code = 1
    serialized = json.dumps(report, sort_keys=True, separators=(",", ":"))
    if arguments.output:
        Path(arguments.output).write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
