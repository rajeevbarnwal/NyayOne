"""NYAY-5 PostgreSQL 16 server-authoritative profile release gate.

The executable accepts only an explicit query-free loopback PostgreSQL control
URL, creates disposable marker-named scratch databases, exercises the exact
0020 -> 0021 migration and product boundary, and removes every scratch database
in ``finally``. Evidence is aggregate-only and never includes URLs, database
names, UUIDs, cookies, identity PII, profile values, or request payloads.

Exit codes: 0 PASS, 1 FAIL, 78 BLOCKED prerequisite.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import inspect as pyinspect
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import Any

from sqlalchemy import create_engine, func, inspect, make_url, select, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.migration_release_guard import APPLICATION_HEAD_REVISION

BLOCKED_EXIT = 78
PREVIOUS_REVISION = "0020_auth_retention_lifecycle"
PINNED_HEAD = "0021_nyay5_profile_boundary"
PINNED_HEAD_PATH = (
    BACKEND / "app/db/migrations/versions/0021_nyay5_profile_boundary.py"
)
PINNED_HEAD_SHA256 = (
    "439de03dc431a73264db706f77ffb703541619db1f490760d6d685aa173c7c50"
)
BEHAVIOR_HEAD = APPLICATION_HEAD_REVISION
OPT_IN_ENV = "NYAY5_POSTGRES_GATE"
SCRATCH_PREFIX = "nyay5_profile_"

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

REQUIRED_ASSERTION_IDS = (
    "RUNTIME-POSTGRES-16-PGVECTOR",
    "MIGRATION-0020-0021-FORWARD-IMMUTABLE",
    "MIGRATION-POPULATED-ROUNDTRIP-ATOMIC",
    "SCHEMA-PROFILE-BOUNDARY-EXACT",
    "CONTRACT-OWNER-PROJECTION-EXACT",
    "CONTRACT-ANONYMOUS-EXPIRED-REVOKED-DELETED-WRONG-ROLE",
    "CONTRACT-REGISTRATION-CONSENT-ZERO-MUTATION",
    "CONTRACT-REGISTRATION-ENUMERATION-NEUTRAL",
    "CONTRACT-CROSS-USER-CLIENT-SELECTOR-DENIED",
    "CONTRACT-NONTEST-ACTOR-HEADER-REJECTED",
    "CONTRACT-COMPLETION-V1-DETERMINISTIC",
    "CONTRACT-PERSISTENCE-FRESH-SESSION",
    "CONTRACT-NORMALIZED-IDENTITY-NO-DUPLICATION",
    "CONTRACT-OPTIMISTIC-CONCURRENCY",
    "CONTRACT-DOB-GUARDIAN-ATOMIC",
    "CONTRACT-DOB-AGE-BOUNDARIES",
    "CONTRACT-VERIFICATION-SELF-AUTHORITY-DENIED",
    "CONTRACT-AUTHORIZED-TRANSITIONS-EXACT",
    "CONTRACT-PROMPT-SESSION-SCOPE",
    "CONTRACT-AUDIT-AGGREGATE-PRIVACY",
    "HARNESS-MUTANTS-PRIVACY-SCRATCH-CLEANUP",
)

REQUIRED_MUTANT_IDS = (
    "ACCEPT-POSTGRES-15",
    "ACCEPT-MISSING-PGVECTOR",
    "ACCEPT-NONLOOPBACK-CONTROL",
    "ACCEPT-QUERY-ROUTED-CONTROL",
    "SKIP-0020-PARENT",
    "REWRITE-HISTORICAL-MIGRATION",
    "REWRITE-APPLICATION-HEAD",
    "ALLOW-MULTIPLE-ALEMBIC-HEADS",
    "DROP-PROFILE-VERSION-CAS",
    "DUPLICATE-IDENTITY-COLUMNS",
    "TRUST-CLIENT-OWNER-SELECTOR",
    "ALLOW-CROSS-USER-MUTATION",
    "FABRICATE-67-PERCENT-NEW-USER",
    "COMPLETE-SKIPPED-SECTION",
    "COUPLE-COMPLETION-TO-VERIFICATION",
    "ALLOW-STALE-WRITE",
    "OVERWRITE-AFTER-CONFLICT",
    "USE-PROCESS-DATE-FOR-AGE",
    "NONATOMIC-GUARDIAN-RECOMPUTE",
    "ALLOW-SHARE-AFTER-MINOR-COMMIT",
    "ALLOW-TOKEN-AFTER-MINOR-COMMIT",
    "ALLOW-STUDENT-SELF-VERIFICATION",
    "BYPASS-M01-EXACT-EFFECT-SESSION-LOCK",
    "PERSIST-PROMPT-DISMISSAL-ACROSS-SESSIONS",
    "AUDIT-CONTAINS-PROFILE-PII",
    "SCRATCH-CLEANUP-NOT-FINAL",
    "ASSERTION-INVENTORY-MISSING",
    "ASSERTION-INVENTORY-REORDERED",
    "ASSERTION-INVENTORY-DUPLICATED",
)

_UUID_TEXT = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_EMAIL_TEXT = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_MOBILE_TEXT = re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)")
_DOB_TEXT = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_URL_TEXT = re.compile(r"(?i)\b(?:postgres(?:ql)?|https?)\+?[^\s:]*://")
_TOKEN_TEXT = re.compile(r"(?i)\b(?:bearer\s+|eyJ)[A-Za-z0-9._~+/-]{12,}")
_FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "actor_id",
        "cookie",
        "database_url",
        "date_of_birth",
        "dob",
        "email",
        "first_name",
        "last_name",
        "middle_name",
        "mobile",
        "password",
        "payload",
        "profile_id",
        "registration_id",
        "request_body",
        "scratch_database",
        "session_token",
        "token",
        "user_id",
    }
)

_PROFILE_MUTATION_PATHS = frozenset(
    {
        "/api/v1/auth/student/profile",
        "/api/v1/student/profile/personal",
        "/api/v1/student/profile/academic",
        "/api/v1/student/profile/interests",
    }
)


def _profile_mutation_headers(
    path: str,
    headers: object,
    idempotency_key: str,
) -> object:
    """Add one fixture key without rewriting caller-supplied header structure."""

    if path not in _PROFILE_MUTATION_PATHS:
        return headers
    if headers is None:
        return {"Idempotency-Key": idempotency_key}
    if isinstance(headers, Mapping):
        if any(str(name).casefold() == "idempotency-key" for name in headers):
            return headers
        augmented = dict(headers)
        augmented["Idempotency-Key"] = idempotency_key
        return augmented
    pairs = list(headers)  # type: ignore[arg-type]
    if any(str(name).casefold() == "idempotency-key" for name, _value in pairs):
        return pairs
    return [*pairs, ("Idempotency-Key", idempotency_key)]


class Blocked(RuntimeError):
    """A target-runtime prerequisite was absent; never a pass."""


class ProductGateFailure(RuntimeError):
    """The target runtime existed but a product or harness assertion failed."""


class ScratchCleanupFailure(RuntimeError):
    """A disposable scratch database could not be removed."""


def _reject_ambient_libpq_environment() -> None:
    if any(key in LIBPQ_AMBIENT_KEYS or key.startswith("PGSSL") for key in os.environ):
        raise Blocked("ambient libpq routing or credential environment is not allowed")


def _safe_local_postgres_url(raw: str) -> URL:
    _reject_ambient_libpq_environment()
    if "://" not in raw:
        raise Blocked("a valid PostgreSQL URL is required")
    authority = re.split(r"[/?#]", raw.split("://", 1)[1], maxsplit=1)[0]
    if "%" in authority or authority.count("@") > 1:
        raise Blocked("the PostgreSQL URL authority is ambiguous")
    try:
        url = make_url(raw)
    except Exception as exc:
        raise Blocked("a valid PostgreSQL URL is required") from exc
    if url.get_backend_name() != "postgresql" or url.query:
        raise Blocked("a query-free PostgreSQL URL is required")
    host = (url.host or "").casefold()
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
    except Exception:
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}"')


def _create_scratch(base: URL, name: str) -> str:
    try:
        _drop_scratch(base, name)
        _admin_execute(base, f'CREATE DATABASE "{name}"')
    except Exception as exc:
        try:
            _drop_scratch(base, name)
        except Exception:
            pass
        raise Blocked("could not create a disposable NYAY-5 database") from exc
    return _database_url(base, name)


def _scratch_database_inventory(base: URL) -> set[str]:
    """Return owned-prefix names in memory; names never enter evidence."""

    engine = create_engine(_database_url(base, "postgres"), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return {
                str(value)
                for value in connection.scalars(
                    text(
                        "SELECT datname FROM pg_database "
                        "WHERE datname LIKE 'nyay5_profile_%'"
                    )
                )
            }
    finally:
        engine.dispose()


class _ScratchDatabaseManager:
    def __init__(self, base: URL) -> None:
        self.base = base
        self.records: list[dict[str, object]] = []
        self._owned_names: set[str] = set()
        try:
            self._baseline_inventory = _scratch_database_inventory(base)
        except Exception as exc:
            raise Blocked("could not inventory disposable NYAY-5 databases") from exc

    def run(self, purpose: str, probe: Callable[[str], Any]) -> Any:
        name = f"{SCRATCH_PREFIX}{uuid.uuid4().hex}"
        row: dict[str, object] = {"purpose": purpose, "created": False, "cleanup": "PENDING"}
        self.records.append(row)
        self._owned_names.add(name)
        try:
            scratch_url = _create_scratch(self.base, name)
            row["created"] = True
            return probe(scratch_url)
        except Blocked:
            raise
        except ProductGateFailure:
            raise
        except Exception as exc:
            raise ProductGateFailure("scratch database probe failed") from exc
        finally:
            if row["created"] is True:
                try:
                    _drop_scratch(self.base, name)
                    if name in _scratch_database_inventory(self.base):
                        raise ScratchCleanupFailure(
                            "a disposable NYAY-5 database remained after cleanup"
                        )
                    row["cleanup"] = "PASS"
                except ScratchCleanupFailure:
                    row["cleanup"] = "FAIL"
                    raise
                except Exception as exc:
                    row["cleanup"] = "FAIL"
                    raise ScratchCleanupFailure(
                        "a disposable NYAY-5 database could not be removed"
                    ) from exc
            else:
                row["cleanup"] = "NOT_CREATED"

    def summary(self) -> dict[str, object]:
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
        except Exception:
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
            "purposes": [str(row["purpose"]) for row in self.records],
        }


def _run_alembic(scratch_url: str, *arguments: str) -> dict[str, object]:
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
        timeout=300,
        check=False,
    )
    return {"returncode": result.returncode, "arguments": list(arguments)}


def _is_postgresql_16_with_pgvector(
    server_version_num: object, vector_version: object
) -> bool:
    return (
        type(server_version_num) is int
        and 160000 <= server_version_num < 170000
        and isinstance(vector_version, str)
        and bool(vector_version.strip())
    )


def _assertion(identifier: str, passed: bool, **metrics: object) -> dict[str, object]:
    return {
        "id": identifier,
        "status": "PASS" if passed is True else "FAIL",
        "passed": passed is True,
        "metrics": metrics,
    }


def _evaluate_assertions(assertions: list[Mapping[str, object]]) -> dict[str, object]:
    identifiers = [str(item.get("id", "")) for item in assertions]
    exact_inventory = identifiers == list(REQUIRED_ASSERTION_IDS)
    failed = [
        str(item.get("id", ""))
        for item in assertions
        if item.get("passed") is not True
    ]
    return {
        "exact_inventory": exact_inventory,
        "required": len(REQUIRED_ASSERTION_IDS),
        "passed": sum(item.get("passed") is True for item in assertions),
        "failed": failed,
        "overall_pass": exact_inventory and not failed,
    }


def _exact_keys(value: Mapping[str, object], expected: set[str]) -> bool:
    return set(value) == expected


_SCHEMA_OBSERVATION_KEYS = {
    "tables_delta_exact",
    "profile_columns_delta_exact",
    "profile_column_catalog_exact",
    "verification_column_catalog_exact",
    "new_table_column_catalog_exact",
    "primary_keys_exact",
    "foreign_keys_exact",
    "unique_constraints_exact",
    "checks_exact",
    "indexes_exact",
    "status_constraints_exact",
    "touched_constraint_catalog_exact",
    "catalog_authority_exact",
    "model_shape_exact",
    "identity_columns_absent",
}
_POPULATED_OBSERVATION_KEYS = {
    "parent_fixture_seeded",
    "authority_drift_refused",
    "upgrade_preserved",
    "new_defaults_exact",
    "legacy_authority_quarantined",
    "lossless_downgrade",
    "downgrade_preserved",
    "reupgrade_preserved",
    "retained_state_refused",
    "refusal_atomic",
}
_MIGRATION_OBSERVATION_KEYS = {
    "parent_exact",
    "head_exact",
    "single_head",
    "alembic_check",
    "clean_roundtrip",
    "historical_bytes_immutable",
    "application_head_bytes_immutable",
}
_BEHAVIOR_OBSERVATION_KEYS = {
    "owner_projection",
    "denial_matrix",
    "registration_consent_zero_mutation",
    "registration_enumeration_neutral",
    "client_selector_denial",
    "cross_user_denied",
    "non_test_actor_header_rejected",
    "completion",
    "section_order",
    "verification_independent",
    "fresh_session",
    "normalization",
    "cas_sql_exact",
    "concurrency",
    "stale_conflict_rejected",
    "conflict_atomic",
    "clock_injected",
    "dob_guardian",
    "dob_boundaries",
    "self_authority_denied",
    "authorized_transitions_exact",
    "reviewer_serialization",
    "prompt_scope",
    "prompt_lifecycle_races",
    "audit_privacy",
    "legacy_delegates_canonical",
    "ceremony_selector_absent",
    "share_projection_dob_serialized",
    "verification_token_dob_serialized",
    "profile_session_lifecycle_serialized",
    "reviewer_session_lifecycle_serialized",
    "share_session_lifecycle_serialized",
    "token_session_lifecycle_serialized",
    "m01_completion_session_lifecycle_serialized",
    "login_rotation_no_deadlock",
    "credential_unique_loser_reauthenticated",
    "share_unique_fault_reauthenticated",
    "token_unique_fault_reauthenticated",
}


def _all_exact_true(value: Mapping[str, object], keys: set[str]) -> bool:
    return _exact_keys(value, keys) and all(value.get(key) is True for key in keys)


def _schema_observation_passes(value: Mapping[str, object]) -> bool:
    return _all_exact_true(value, _SCHEMA_OBSERVATION_KEYS)


def _populated_observation_passes(value: Mapping[str, object]) -> bool:
    return _all_exact_true(value, _POPULATED_OBSERVATION_KEYS)


def _migration_observation_passes(value: Mapping[str, object]) -> bool:
    return _all_exact_true(value, _MIGRATION_OBSERVATION_KEYS)


def _behavior_observation_passes(value: Mapping[str, object]) -> bool:
    return _all_exact_true(value, _BEHAVIOR_OBSERVATION_KEYS)


def _scratch_observation_passes(value: Mapping[str, object]) -> bool:
    return bool(
        _exact_keys(
            value,
            {
                "created",
                "removed",
                "cleanup_failed",
                "all_created_removed",
                "inventory_match",
                "baseline_count",
                "final_count",
                "purposes",
            },
        )
        and type(value.get("created")) is int
        and value.get("created") == value.get("removed")
        and value.get("cleanup_failed") == 0
        and value.get("all_created_removed") is True
        and value.get("inventory_match") is True
        and value.get("baseline_count") == value.get("final_count")
        and value.get("purposes")
        == ["runtime", "migration", "populated", "behavior"]
    )


def _url_policy_observation_passes(value: Mapping[str, object]) -> bool:
    return bool(
        _exact_keys(value, {"literal_loopback", "query_free"})
        and value.get("literal_loopback") is True
        and value.get("query_free") is True
    )


def _oracle_baselines() -> dict[str, dict[str, object]]:
    return {
        "runtime": {"postgres16": True, "pgvector": True},
        "url": {"literal_loopback": True, "query_free": True},
        "migration": {key: True for key in _MIGRATION_OBSERVATION_KEYS},
        "schema": {key: True for key in _SCHEMA_OBSERVATION_KEYS},
        "populated": {key: True for key in _POPULATED_OBSERVATION_KEYS},
        "behavior": {key: True for key in _BEHAVIOR_OBSERVATION_KEYS},
        "scratch": {
            "created": 4,
            "removed": 4,
            "cleanup_failed": 0,
            "all_created_removed": True,
            "inventory_match": True,
            "baseline_count": 0,
            "final_count": 0,
            "purposes": ["runtime", "migration", "populated", "behavior"],
        },
    }


def _privacy_findings(value: object) -> list[str]:
    findings: set[str] = set()

    def visit(candidate: object, path: str) -> None:
        if isinstance(candidate, Mapping):
            for key, item in candidate.items():
                normalized = re.sub(r"[^a-z0-9]+", "_", str(key).casefold()).strip("_")
                if normalized in _FORBIDDEN_REPORT_KEYS and item not in {
                    None,
                    False,
                    "redacted",
                    "omitted",
                    "not_stored",
                }:
                    findings.add(f"{path}.{normalized}:forbidden_key")
                visit(item, f"{path}.{normalized}")
        elif isinstance(candidate, (list, tuple)):
            for index, item in enumerate(candidate):
                visit(item, f"{path}[{index}]")
        elif isinstance(candidate, str):
            for label, pattern in (
                ("uuid", _UUID_TEXT),
                ("email", _EMAIL_TEXT),
                ("mobile", _MOBILE_TEXT),
                ("dob", _DOB_TEXT),
                ("url", _URL_TEXT),
                ("token", _TOKEN_TEXT),
            ):
                if pattern.search(candidate):
                    findings.add(f"{path}:{label}")

    visit(value, "report")
    return sorted(findings)


def _historical_migration_bytes_unchanged() -> bool:
    """Pin immutable 0001..0020 without freezing the new 0021 bytes here."""

    versions = BACKEND / "app/db/migrations/versions"
    try:
        base = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=BACKEND.parent, text=True
        ).strip()
        for ordinal in range(1, 21):
            pattern = f"{ordinal:04d}_*.py"
            matches = sorted(versions.glob(pattern))
            if len(matches) != 1:
                return False
            relative = matches[0].relative_to(BACKEND.parent).as_posix()
            committed = subprocess.check_output(
                ["git", "show", f"{base}:{relative}"], cwd=BACKEND.parent
            )
            if hashlib.sha256(committed).digest() != hashlib.sha256(
                matches[0].read_bytes()
            ).digest():
                return False
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _application_head_bytes_unchanged(path: Path = PINNED_HEAD_PATH) -> bool:
    """Pin the complete 0021 body, not only its revision identifiers."""

    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == PINNED_HEAD_SHA256
    except OSError:
        return False


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        rows = list(connection.scalars(text("SELECT version_num FROM alembic_version")))
    return str(rows[0]) if len(rows) == 1 else None


def _type_text(column: Mapping[str, object]) -> str:
    return re.sub(r"\s+", " ", str(column.get("type", "")).upper()).strip()


def _column_shape(
    column: Mapping[str, object],
    *,
    type_text: str,
    nullable: bool,
    default_one: bool = False,
) -> bool:
    reflected_type = _type_text(column)
    type_exact = reflected_type == type_text
    if type_text == "TIMESTAMP WITH TIME ZONE":
        type_exact = bool(
            reflected_type == "TIMESTAMP"
            and getattr(column.get("type"), "timezone", None) is True
        )
    if type_text == "JSON":
        type_exact = reflected_type in {"JSON", "JSONB"}
    default = str(column.get("default") or "")
    default_exact = (not default_one) or bool(
        re.fullmatch(r"\(?'?1'?(?:::[a-z ]+)?\)?", default.casefold())
    )
    return bool(
        type_exact
        and bool(column.get("nullable")) is nullable
        and default_exact
    )


def _new_table_catalog_exact(inspector: Any, table: str, *, prompt: bool) -> bool:
    expected_columns = {
        "id": ("UUID", False),
        "created_at": ("TIMESTAMP WITH TIME ZONE", False),
        "updated_at": ("TIMESTAMP WITH TIME ZONE", False),
        "deleted_at": ("TIMESTAMP WITH TIME ZONE", True),
        "metadata_json": ("JSON", True),
        **(
            {
                "auth_session_id": ("UUID", False),
                "dismissed_at": ("TIMESTAMP WITH TIME ZONE", False),
            }
            if prompt
            else {"profile_id": ("UUID", False), "value": ("VARCHAR(80)", False)}
        ),
    }
    columns = {row["name"]: row for row in inspector.get_columns(table)}
    if set(columns) != set(expected_columns):
        return False
    if not all(
        _column_shape(columns[name], type_text=kind, nullable=nullable)
        for name, (kind, nullable) in expected_columns.items()
    ):
        return False
    parent_column = "auth_session_id" if prompt else "profile_id"
    parent_table = "auth_sessions" if prompt else "student_profiles"
    expected_fk = f"fk_{table}_{parent_column}_{parent_table}"
    expected_uq = f"uq_{table}_{parent_column}" if prompt else f"uq_{table}_profile_id_value"
    expected_uq_columns = [parent_column] if prompt else ["profile_id", "value"]
    pk = inspector.get_pk_constraint(table)
    foreign_keys = inspector.get_foreign_keys(table)
    uniques = inspector.get_unique_constraints(table)
    checks = inspector.get_check_constraints(table)
    explicit_indexes = [
        row for row in inspector.get_indexes(table) if not row.get("duplicates_constraint")
    ]
    catalog_exact = bool(
        pk.get("name") == f"pk_{table}"
        and pk.get("constrained_columns") == ["id"]
        and len(foreign_keys) == 1
        and foreign_keys[0].get("name") == expected_fk
        and foreign_keys[0].get("constrained_columns") == [parent_column]
        and foreign_keys[0].get("referred_table") == parent_table
        and foreign_keys[0].get("referred_columns") == ["id"]
        and str(foreign_keys[0].get("options", {}).get("ondelete", "")).upper()
        == "CASCADE"
        and len(uniques) == 1
        and uniques[0].get("name") == expected_uq
        and uniques[0].get("column_names") == expected_uq_columns
        and len(explicit_indexes) == 1
        and explicit_indexes[0].get("name") == f"ix_{table}_{parent_column}"
        and explicit_indexes[0].get("column_names") == [parent_column]
        and explicit_indexes[0].get("unique") is False
    )
    if prompt:
        return catalog_exact and checks == []
    checks_by_name = {row.get("name"): str(row.get("sqltext", "")) for row in checks}
    expected_check = f"ck_{table}_value_length"
    check_sql = re.sub(r"\s", "", checks_by_name.get(expected_check, "")).casefold()
    check_sql = check_sql.replace("::text", "")
    return bool(
        catalog_exact
        and set(checks_by_name) == {expected_check}
        and "length(value)>=1" in check_sql
        and "length(value)<=80" in check_sql
    )


def _catalog_authority_exact(engine: Engine) -> bool:
    """Pin every 0021-touched authority table to ordinary unmediated storage."""

    names = (
        "auth_session_profile_prompts",
        "auth_sessions",
        "consents",
        "guardian_consents",
        "registration_idempotency_records",
        "student_profile_goals",
        "student_profile_interests",
        "student_profiles",
        "student_registrations",
        "student_verifications",
    )
    relation_list = ", ".join(f"'{name}'" for name in names)
    with engine.connect() as connection:
        catalog = list(
            connection.execute(
                text(
                    "SELECT c.relname, c.relkind, c.relpersistence, "
                    "c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_catalog.pg_class AS c "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' "
                    f"AND c.relname IN ({relation_list}) ORDER BY c.relname"
                )
            )
        )
        if [row[0] for row in catalog] != list(names) or any(
            row[1] != "r" or row[2] != "p" or bool(row[3]) or bool(row[4])
            for row in catalog
        ):
            return False
        drift_queries = (
            "SELECT count(*) FROM pg_catalog.pg_policy AS p "
            "JOIN pg_catalog.pg_class AS c ON c.oid = p.polrelid "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace ",
            "SELECT count(*) FROM pg_catalog.pg_rewrite AS r "
            "JOIN pg_catalog.pg_class AS c ON c.oid = r.ev_class "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE r.rulename <> '_RETURN' AND ",
            "SELECT count(*) FROM pg_catalog.pg_trigger AS t "
            "JOIN pg_catalog.pg_class AS c ON c.oid = t.tgrelid "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE NOT t.tgisinternal AND ",
        )
        for prefix in drift_queries:
            where = "WHERE " if "WHERE" not in prefix else ""
            count = connection.scalar(
                text(
                    f"{prefix}{where}n.nspname = 'public' "
                    f"AND c.relname IN ({relation_list})"
                )
            )
            if type(count) is not int or count != 0:
                return False
    return True


def _model_shape_exact() -> bool:
    try:
        from app.models.registration import (
            AuthSessionProfilePrompt,
            StudentProfile,
            StudentProfileGoal,
            StudentProfileInterest,
            StudentVerification,
        )

        profile = StudentProfile.__table__.columns
        profile_columns = {
            "registration_id", "college", "year_of_study", "enrolment_ct",
            "enrolment_hash", "institutional_email_ct",
            "institutional_email_hash", "bar_enrolment_ct",
            "bar_enrolment_hash", "key_version", "city",
            "preferred_language", "pronouns", "profile_version", "id",
            "created_at", "updated_at", "deleted_at", "metadata_json",
        }
        profile_exact = bool(
            set(profile.keys()) == profile_columns
            and isinstance(profile["city"].type.length, int)
            and profile["city"].type.length == 120
            and profile["preferred_language"].type.length == 16
            and profile["pronouns"].type.length == 60
            and profile["profile_version"].nullable is False
        )
        value_columns = {
            "profile_id", "value", "id", "created_at", "updated_at", "deleted_at", "metadata_json"
        }
        prompt_columns = {
            "auth_session_id", "dismissed_at", "id", "created_at", "updated_at", "deleted_at", "metadata_json"
        }
        verification_columns = {
            "registration_id", "method", "status", "verified_email_hash",
            "id", "created_at", "updated_at", "deleted_at", "metadata_json",
        }
        return bool(
            profile_exact
            and set(StudentVerification.__table__.columns.keys())
            == verification_columns
            and StudentVerification.__table__.columns["verified_email_hash"].nullable
            is True
            and StudentVerification.__table__.columns[
                "verified_email_hash"
            ].type.length
            == 64
            and set(StudentProfileInterest.__table__.columns.keys()) == value_columns
            and set(StudentProfileGoal.__table__.columns.keys()) == value_columns
            and set(AuthSessionProfilePrompt.__table__.columns.keys()) == prompt_columns
        )
    except (AttributeError, ImportError, TypeError):
        return False


def _constraint_sql(inspector: Any, table: str, name: str) -> str:
    checks = {
        row.get("name"): " ".join(
            str(row.get("sqltext", "")).casefold().split()
        )
        for row in inspector.get_check_constraints(table)
    }
    return checks.get(name, "")


def _server_normalized_constraint_exact(
    inspector: Any,
    table: str,
    name: str,
    expression: str,
) -> bool:
    """Compare exact PG16 parse trees by compiling the expected source."""

    if inspector.bind.dialect.name != "postgresql":
        return _constraint_sql(inspector, table, name) == " ".join(
            expression.casefold().split()
        )
    try:
        with inspector.bind.begin() as connection:
            actual = connection.scalar(
                text(
                    "SELECT pg_catalog.pg_get_constraintdef(c.oid, true) "
                    "FROM pg_catalog.pg_constraint AS c "
                    "JOIN pg_catalog.pg_class AS r ON r.oid = c.conrelid "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid = r.relnamespace "
                    "WHERE n.nspname = 'public' AND r.relname = :table_name "
                    "AND c.conname = :constraint_name AND c.contype = 'c'"
                ),
                {"table_name": table, "constraint_name": name},
            )
            connection.execute(text("DROP TABLE IF EXISTS pg_temp._nyay5_gate_check"))
            try:
                connection.execute(
                    text(
                        'CREATE TEMP TABLE pg_temp."_nyay5_gate_check" '
                        f'(LIKE public."{table}") ON COMMIT DROP'
                    )
                )
                connection.execute(
                    text(
                        'ALTER TABLE pg_temp."_nyay5_gate_check" '
                        'ADD CONSTRAINT "_nyay5_gate_check_constraint" '
                        f"CHECK ({expression})"
                    )
                )
                expected = connection.scalar(
                    text(
                        "SELECT pg_catalog.pg_get_constraintdef(c.oid, true) "
                        "FROM pg_catalog.pg_constraint AS c "
                        "JOIN pg_catalog.pg_class AS r ON r.oid = c.conrelid "
                        "JOIN pg_catalog.pg_namespace AS n ON n.oid = r.relnamespace "
                        "WHERE n.oid = pg_catalog.pg_my_temp_schema() "
                        "AND r.relname = '_nyay5_gate_check' "
                        "AND c.conname = '_nyay5_gate_check_constraint' "
                        "AND c.contype = 'c'"
                    )
                )
            finally:
                connection.execute(
                    text("DROP TABLE IF EXISTS pg_temp._nyay5_gate_check")
                )
        return bool(
            isinstance(actual, str)
            and isinstance(expected, str)
            and " ".join(actual.casefold().split())
            == " ".join(expected.casefold().split())
        )
    except Exception:
        return False


def _status_constraints_exact(inspector: Any) -> bool:
    verification = {
        row.get("name"): str(row.get("sqltext", "")).casefold()
        for row in inspector.get_check_constraints("student_verifications")
    }
    guardian = {
        row.get("name"): str(row.get("sqltext", "")).casefold()
        for row in inspector.get_check_constraints("guardian_consents")
    }
    return bool(
        "ck_student_verifications_status" in verification
        and "expired" in verification["ck_student_verifications_status"]
        and "revoked" in verification["ck_student_verifications_status"]
        and "ck_student_verifications_ck_student_verifications_status" not in verification
        and "ck_guardian_consents_status" in guardian
        and "revoked" in guardian["ck_guardian_consents_status"]
        and "ck_guardian_consents_verified_matches_status" in guardian
        and "revoked" in guardian["ck_guardian_consents_verified_matches_status"]
        and "ck_guardian_consents_ck_guardian_consents_status" not in guardian
    )


def _touched_constraint_catalog_exact(inspector: Any) -> bool:
    verification_status_expected = "status IN ('pending', 'in_review', 'verified', 'rejected', 'expired', 'revoked')"
    verification_proof_expected = (
        "(status = 'verified' AND verified_email_hash IS NOT NULL) OR "
        "(status <> 'verified' AND verified_email_hash IS NULL)"
    )
    guardian_status_expected = (
        "status IN ('pending', 'sent', 'verified', 'rejected', 'revoked')"
    )
    guardian_proof_expected = (
        "(status = 'verified' AND verified = true) OR "
        "(status IN ('pending', 'sent', 'rejected', 'revoked') "
        "AND verified = false)"
    )
    registration_v1 = (
        "((state IN ('pending', 'succeeded', 'failed', 'neutralized') AND "
        "request_fingerprint_version = 'v1' AND request_fingerprint IS NOT NULL "
        "AND length(request_fingerprint) = 64 AND "
        "length(replace(replace(replace(replace(replace(replace(replace(replace("
        "replace(replace(replace(replace(replace(replace(replace(replace("
        "request_fingerprint, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), "
        "'5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), "
        "'c', ''), 'd', ''), 'e', ''), 'f', '')) = 0) OR "
        "(state IN ('retired', 'erased') AND request_fingerprint IS NULL AND "
        "request_fingerprint_version IS NULL))"
    )
    fingerprint_expected = registration_v1.replace(
        "request_fingerprint_version = 'v1'",
        "request_fingerprint_version IN ('v1', 'v2')",
    )
    return bool(
        _server_normalized_constraint_exact(
            inspector,
            "student_verifications",
            "ck_student_verifications_status",
            verification_status_expected,
        )
        and _server_normalized_constraint_exact(
            inspector,
            "student_verifications",
            "ck_student_verifications_verified_email_proof",
            verification_proof_expected,
        )
        and _server_normalized_constraint_exact(
            inspector,
            "guardian_consents",
            "ck_guardian_consents_status",
            guardian_status_expected,
        )
        and _server_normalized_constraint_exact(
            inspector,
            "guardian_consents",
            "ck_guardian_consents_verified_matches_status",
            guardian_proof_expected,
        )
        and _server_normalized_constraint_exact(
            inspector,
            "registration_idempotency_records",
            "ck_registration_idempotency_records_request_fingerprint_shape",
            fingerprint_expected,
        )
    )


def _runtime_probe(scratch_url: str) -> dict[str, object]:
    """Install and verify pgvector inside an owned disposable database."""

    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            server_version_num = int(connection.scalar(text("SHOW server_version_num")))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            vector_version = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
    except Exception as exc:
        raise Blocked("PostgreSQL runtime could not be inspected") from exc
    finally:
        engine.dispose()
    return {
        "server_version_num": server_version_num,
        "pgvector_present": bool(vector_version),
        "pass": _is_postgresql_16_with_pgvector(server_version_num, vector_version),
    }


def _migration_and_schema_probe(scratch_url: str) -> dict[str, object]:
    parent = _run_alembic(scratch_url, "upgrade", PREVIOUS_REVISION)
    if parent["returncode"] != 0:
        raise ProductGateFailure("0020 migration setup failed")
    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        before = _current_revision(engine)
        before_inspector = inspect(engine)
        before_tables = set(before_inspector.get_table_names())
        before_profile_columns = {
            row["name"] for row in before_inspector.get_columns("student_profiles")
        }
        before_verification_columns = {
            row["name"]
            for row in before_inspector.get_columns("student_verifications")
        }
        before_profile_checks = {
            row.get("name")
            for row in before_inspector.get_check_constraints("student_profiles")
        }
        upgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        after = _current_revision(engine)
        inspector = inspect(engine)
        after_tables = set(inspector.get_table_names())
        after_profile_columns = {
            row["name"]: row for row in inspector.get_columns("student_profiles")
        }
        after_verification_columns = {
            row["name"]: row
            for row in inspector.get_columns("student_verifications")
        }
        after_profile_checks = {
            row.get("name")
            for row in inspector.get_check_constraints("student_profiles")
        }
        additions = {
            "student_profile_interests",
            "student_profile_goals",
            "auth_session_profile_prompts",
        }
        profile_additions = {"city", "preferred_language", "pronouns", "profile_version"}
        profile_column_catalog_exact = bool(
            set(after_profile_columns) - before_profile_columns == profile_additions
            and _column_shape(
                after_profile_columns["city"], type_text="VARCHAR(120)", nullable=True
            )
            and _column_shape(
                after_profile_columns["preferred_language"],
                type_text="VARCHAR(16)",
                nullable=True,
            )
            and _column_shape(
                after_profile_columns["pronouns"],
                type_text="VARCHAR(60)",
                nullable=True,
            )
            and _column_shape(
                after_profile_columns["profile_version"],
                type_text="INTEGER",
                nullable=False,
                default_one=True,
            )
        )
        verification_column_catalog_exact = bool(
            set(after_verification_columns) - before_verification_columns
            == {"verified_email_hash"}
            and _column_shape(
                after_verification_columns["verified_email_hash"],
                type_text="VARCHAR(64)",
                nullable=True,
            )
        )
        expected_new_checks = {
            "ck_student_profiles_preferred_language",
            "ck_student_profiles_profile_version_positive",
        }
        new_catalog = {
            table: _new_table_catalog_exact(
                inspector, table, prompt=table == "auth_session_profile_prompts"
            )
            for table in additions
        }
        boundary_columns = profile_additions | {
            str(row["name"])
            for table in additions
            for row in inspector.get_columns(table)
        }
        schema_observation = {
            "tables_delta_exact": after_tables - before_tables == additions,
            "profile_columns_delta_exact": (
                set(after_profile_columns) - before_profile_columns == profile_additions
            ),
            "profile_column_catalog_exact": profile_column_catalog_exact,
            "verification_column_catalog_exact": verification_column_catalog_exact,
            "new_table_column_catalog_exact": all(new_catalog.values()),
            "primary_keys_exact": all(new_catalog.values()),
            "foreign_keys_exact": all(new_catalog.values()),
            "unique_constraints_exact": all(new_catalog.values()),
            "checks_exact": bool(
                after_profile_checks - before_profile_checks == expected_new_checks
                and all(new_catalog.values())
            ),
            "indexes_exact": all(new_catalog.values()),
            "status_constraints_exact": _status_constraints_exact(inspector),
            "touched_constraint_catalog_exact": _touched_constraint_catalog_exact(
                inspector
            ),
            "catalog_authority_exact": _catalog_authority_exact(engine),
            "model_shape_exact": _model_shape_exact(),
            "identity_columns_absent": not {
                "first_name", "middle_name", "last_name", "date_of_birth", "mobile", "mobile_hash"
            }.intersection(boundary_columns),
        }
        current_upgrade = _run_alembic(scratch_url, "upgrade", BEHAVIOR_HEAD)
        current = _current_revision(engine)
        check = _run_alembic(scratch_url, "check")
        downgrade = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        down = _current_revision(engine)
        reupgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        final = _current_revision(engine)
        migration_observation = {
            "parent_exact": before == PREVIOUS_REVISION,
            "head_exact": upgrade["returncode"] == 0 and after == PINNED_HEAD,
            "single_head": bool(
                current_upgrade["returncode"] == 0 and current == BEHAVIOR_HEAD
            ),
            "alembic_check": bool(
                current_upgrade["returncode"] == 0
                and current == BEHAVIOR_HEAD
                and check["returncode"] == 0
            ),
            "clean_roundtrip": bool(
                downgrade["returncode"] == 0
                and down == PREVIOUS_REVISION
                and reupgrade["returncode"] == 0
                and final == PINNED_HEAD
            ),
            "historical_bytes_immutable": _historical_migration_bytes_unchanged(),
            "application_head_bytes_immutable": _application_head_bytes_unchanged(),
        }
        return {
            "migration": migration_observation,
            "schema": schema_observation,
            "required_tables": len(additions),
            "profile_columns": len(profile_additions),
            "required_constraints": 14,
            "required_indexes": 3,
        }
    finally:
        engine.dispose()


def _seed_populated_parent(engine: Engine) -> dict[str, str]:
    identifiers = {
        "user": str(uuid.uuid4()),
        "registration": str(uuid.uuid4()),
        "profile": str(uuid.uuid4()),
        "verification": str(uuid.uuid4()),
        "guardian": str(uuid.uuid4()),
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, role, status) "
                "VALUES (CAST(:user AS uuid), 'student', 'active')"
            ),
            identifiers,
        )
        connection.execute(
            text(
                "INSERT INTO student_registrations "
                "(id, user_id, first_name, middle_name, last_name, mobile_hash, "
                "mobile_ct, dob_hash, dob_ct, dob_hash_state, key_version, status, "
                "is_minor, idempotency_key, idempotency_key_legacy) VALUES "
                "(CAST(:registration AS uuid), CAST(:user AS uuid), 'Synthetic', "
                "NULL, 'Fixture', :mobile_hash, 'synthetic-ciphertext', :dob_hash, "
                "'synthetic-ciphertext', 'verified', 'v1', 'active', false, NULL, false)"
            ),
            {
                **identifiers,
                "mobile_hash": "a" * 64,
                "dob_hash": "b" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO student_profiles (id, registration_id, key_version) "
                "VALUES (CAST(:profile AS uuid), CAST(:registration AS uuid), 'v1')"
            ),
            identifiers,
        )
        connection.execute(
            text(
                "INSERT INTO student_verifications "
                "(id, registration_id, method, status) VALUES "
                "(CAST(:verification AS uuid), CAST(:registration AS uuid), "
                "'institutional_email', 'verified')"
            ),
            identifiers,
        )
        connection.execute(
            text(
                "INSERT INTO guardian_consents "
                "(id, registration_id, status, verified) VALUES "
                "(CAST(:guardian AS uuid), CAST(:registration AS uuid), "
                "'verified', true)"
            ),
            identifiers,
        )
    return identifiers


def _fixture_base_preserved(engine: Engine, identifiers: Mapping[str, str]) -> bool:
    with engine.connect() as connection:
        count = connection.scalar(
            text(
                "SELECT count(*) FROM users AS u "
                "JOIN student_registrations AS r ON r.user_id = u.id "
                "JOIN student_profiles AS p ON p.registration_id = r.id "
                "WHERE u.id = CAST(:user AS uuid) "
                "AND r.id = CAST(:registration AS uuid) "
                "AND p.id = CAST(:profile AS uuid)"
            ),
            identifiers,
        )
    return count == 1


def _populated_migration_probe(scratch_url: str) -> dict[str, object]:
    parent = _run_alembic(scratch_url, "upgrade", PREVIOUS_REVISION)
    if parent["returncode"] != 0:
        raise ProductGateFailure("populated 0020 migration setup failed")
    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        identifiers = _seed_populated_parent(engine)
        parent_seeded = _fixture_base_preserved(engine, identifiers)
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE student_profiles ENABLE ROW LEVEL SECURITY")
            )
        drift_upgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        drift_inspector = inspect(engine)
        authority_drift_refused = bool(
            drift_upgrade["returncode"] != 0
            and _current_revision(engine) == PREVIOUS_REVISION
            and not {
                "student_profile_interests",
                "student_profile_goals",
                "auth_session_profile_prompts",
            }.intersection(drift_inspector.get_table_names())
            and not {
                "city", "preferred_language", "pronouns", "profile_version"
            }.intersection(
                row["name"]
                for row in drift_inspector.get_columns("student_profiles")
            )
            and _fixture_base_preserved(engine, identifiers)
        )
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE student_profiles DISABLE ROW LEVEL SECURITY")
            )
        upgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        upgrade_preserved = bool(
            upgrade["returncode"] == 0
            and _current_revision(engine) == PINNED_HEAD
            and _fixture_base_preserved(engine, identifiers)
        )
        with engine.connect() as connection:
            defaults = connection.execute(
                text(
                    "SELECT city, preferred_language, pronouns, profile_version "
                    "FROM student_profiles WHERE id = CAST(:profile AS uuid)"
                ),
                identifiers,
            ).one_or_none()
        new_defaults_exact = bool(
            defaults is not None
            and defaults[0] is None
            and defaults[1] is None
            and defaults[2] is None
            and defaults[3] == 1
        )
        with engine.connect() as connection:
            quarantined = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM student_verifications "
                    " WHERE id = CAST(:verification AS uuid) "
                    " AND status = 'revoked' AND verified_email_hash IS NULL), "
                    "(SELECT count(*) FROM guardian_consents "
                    " WHERE id = CAST(:guardian AS uuid) "
                    " AND status = 'revoked' AND verified = false), "
                    "(SELECT count(*) FROM student_verifications "
                    " WHERE status = 'verified' AND verified_email_hash IS NULL), "
                    "(SELECT count(*) FROM guardian_consents "
                    " WHERE status = 'verified' OR verified = true)"
                ),
                identifiers,
            ).one()
        legacy_authority_quarantined = quarantined == (1, 1, 0, 0)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM guardian_consents "
                    "WHERE id = CAST(:guardian AS uuid)"
                ),
                identifiers,
            )
            connection.execute(
                text(
                    "DELETE FROM student_verifications "
                    "WHERE id = CAST(:verification AS uuid)"
                ),
                identifiers,
            )
        downgrade = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        lossless_downgrade = bool(
            downgrade["returncode"] == 0
            and _current_revision(engine) == PREVIOUS_REVISION
        )
        downgrade_preserved = _fixture_base_preserved(engine, identifiers)
        reupgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        reupgrade_preserved = bool(
            reupgrade["returncode"] == 0
            and _current_revision(engine) == PINNED_HEAD
            and _fixture_base_preserved(engine, identifiers)
        )
        retained_id = str(uuid.uuid4())
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE student_profiles SET city = 'Synthetic City' "
                    "WHERE id = CAST(:profile AS uuid)"
                ),
                identifiers,
            )
            connection.execute(
                text(
                    "INSERT INTO student_profile_interests (id, profile_id, value) "
                    "VALUES (CAST(:retained AS uuid), CAST(:profile AS uuid), 'synthetic-topic')"
                ),
                {**identifiers, "retained": retained_id},
            )
        refused = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        retained_state_refused = bool(
            refused["returncode"] != 0 and _current_revision(engine) == PINNED_HEAD
        )
        with engine.connect() as connection:
            retained_counts = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM student_profiles "
                    " WHERE id = CAST(:profile AS uuid) AND city IS NOT NULL), "
                    "(SELECT count(*) FROM student_profile_interests "
                    " WHERE id = CAST(:retained AS uuid))"
                ),
                {**identifiers, "retained": retained_id},
            ).one()
        refusal_atomic = retained_counts[0] == 1 and retained_counts[1] == 1
        observation = {
            "parent_fixture_seeded": parent_seeded,
            "authority_drift_refused": authority_drift_refused,
            "upgrade_preserved": upgrade_preserved,
            "new_defaults_exact": new_defaults_exact,
            "legacy_authority_quarantined": legacy_authority_quarantined,
            "lossless_downgrade": lossless_downgrade,
            "downgrade_preserved": downgrade_preserved,
            "reupgrade_preserved": reupgrade_preserved,
            "retained_state_refused": retained_state_refused,
            "refusal_atomic": refusal_atomic,
        }
        return {"observation": observation, "fixture_rows": 5, "retained_rows": 2}
    finally:
        engine.dispose()


def _behavior_probe(scratch_url: str) -> dict[str, bool]:
    """Exercise the real NYAY-5 HTTP/service boundary on migrated PostgreSQL."""

    upgrade = _run_alembic(scratch_url, "upgrade", BEHAVIOR_HEAD)
    if upgrade["returncode"] != 0:
        raise ProductGateFailure("behavior database migration failed")
    observations = {name: False for name in _BEHAVIOR_OBSERVATION_KEYS}
    engine = create_engine(scratch_url, poolclass=NullPool)
    fixed_now = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
    origin = "https://nyay5-gate.invalid"
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy.orm import Session, sessionmaker

        from app.api.v1 import (
            auth_student,
            credentials as credential_api,
            student_settings,
            tutoring as tutoring_api,
        )
        from app.core.config import settings
        from app.core.crypto import KeyRing, decrypt, encrypt, keyed_hash, override_keyring
        from app.core.exceptions import register_exception_handlers
        from app.core.middleware import RequestIDMiddleware
        from app.db.models.audit import AuditEvent
        from app.db.session import get_session
        from app.models.registration import (
            AuthSession,
            AuthSessionProfilePrompt,
            GuardianConsent,
            StudentProfile,
            StudentRegistration,
            StudentVerification,
            User,
        )
        from app.models.credentials import (
            Credential,
            CredentialOutbox,
            CredentialReminderJob,
            CredentialShareProjection,
            CredentialStatusHistory,
            VerificationToken,
        )
        from app.models.wave2 import (
            BookingEvent,
            SessionAttendance,
            SessionStatusHistory,
            TutorAvailabilitySlot,
            TutoringOutbox,
            TutoringSession,
            TutorProfile,
        )
        from app.services import login_service, profile_service
        from app.services.tutoring import attendance as attendance_service
        from app.services.otp_sender import CapturingSender

        factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )
        unique_loser_controller: dict[str, object] | None = None

        def request_session():
            session = factory()
            if unique_loser_controller is not None:
                session.info["nyay5_unique_loser"] = unique_loser_controller
            try:
                yield session
            finally:
                session.close()

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
        register_exception_handlers(app)
        app.include_router(auth_student.router, prefix="/api/v1")
        app.include_router(student_settings.router, prefix="/api/v1")
        app.include_router(credential_api.router, prefix="/api/v1")
        app.include_router(tutoring_api.router, prefix="/api/v1")
        app.dependency_overrides[get_session] = request_session
        registration_sender = CapturingSender()
        app.dependency_overrides[auth_student.get_otp_sender] = (
            lambda: registration_sender
        )
        app.dependency_overrides[auth_student.get_outbox_session_factory] = (
            lambda: factory
        )

        previous_env = settings.app_env
        previous_origins = list(settings.cors_origins)
        previous_student_now = student_settings._now
        previous_auth_now = auth_student._now
        previous_attendance_now = attendance_service.utcnow
        settings.app_env = "testing"
        settings.cors_origins = [origin]
        request_clock = {"now": fixed_now}
        student_settings._now = lambda: request_clock["now"]
        auth_student._now = lambda: request_clock["now"]
        attendance_service.utcnow = lambda: request_clock["now"]
        override_keyring(
            KeyRing(
                active_version="v1",
                secrets={"v1": b"nyay5-postgres-gate-synthetic-key-v1"},
                lookup_secret=b"nyay5-postgres-gate-synthetic-lookup-v1",
            )
        )

        def seed_actor(
            label: str,
            *,
            dob: date = date(2000, 1, 1),
            user_role: str = "student",
            user_status: str = "active",
            session_status: str = "active",
            session_expired: bool = False,
            registration_deleted: bool = False,
        ) -> dict[str, object]:
            raw_token = f"nyay5-{label}-" + uuid.uuid4().hex
            with factory.begin() as session:
                user = User(role=user_role, status=user_status)
                session.add(user)
                session.flush()
                registration = StudentRegistration(
                    user_id=user.id,
                    first_name="Synthetic",
                    middle_name=None,
                    last_name="Student",
                    mobile_hash=keyed_hash(f"synthetic-mobile-{label}"),
                    mobile_ct=encrypt(f"synthetic-mobile-{label}"),
                    dob_hash=keyed_hash(dob.isoformat()),
                    dob_ct=encrypt(dob.isoformat()),
                    dob_hash_state="verified",
                    key_version="v1",
                    status="active",
                    is_minor=False,
                    deleted_at=fixed_now if registration_deleted else None,
                )
                session.add(registration)
                session.flush()
                profile = StudentProfile(registration_id=registration.id)
                session.add(profile)
                session.flush()
                revoked = fixed_now if session_status != "active" else None
                auth_session = AuthSession(
                    user_id=user.id,
                    token_hash=keyed_hash(raw_token),
                    status=session_status,
                    expires_at=(
                        fixed_now - timedelta(minutes=1)
                        if session_expired
                        else fixed_now + timedelta(days=30)
                    ),
                    last_seen_at=fixed_now,
                    revoked_at=revoked,
                )
                session.add(auth_session)
                session.flush()
                return {
                    "user_id": user.id,
                    "registration_id": registration.id,
                    "profile_id": profile.id,
                    "session_id": auth_session.id,
                    "token": raw_token,
                }

        def client_for(actor: Mapping[str, object] | None) -> TestClient:
            client = TestClient(
                app,
                base_url=origin,
                raise_server_exceptions=False,
            )
            client.headers["Origin"] = origin
            if actor is not None:
                client.cookies.set(
                    settings.auth_session_cookie_name,
                    str(actor["token"]),
                )
            original_patch = client.patch

            def profile_patch(url: object, *args: object, **kwargs: object):
                path = str(url)
                kwargs["headers"] = _profile_mutation_headers(
                    path,
                    kwargs.get("headers"),
                    f"nyay5-gate-profile-{uuid.uuid4().hex}",
                )
                return original_patch(url, *args, **kwargs)

            client.patch = profile_patch  # type: ignore[method-assign]
            return client

        def personal(version: int, dob: str = "2000-01-01", city: str = "Pune") -> dict:
            return {
                "expected_profile_version": version,
                "first_name": "Synthetic",
                "middle_name": None,
                "last_name": "Student",
                "date_of_birth": dob,
                "preferred_language": "en",
                "city": city,
                "pronouns": None,
            }

        def projection_exact(body: object) -> bool:
            if not isinstance(body, Mapping):
                return False
            exact_top = {
                "profile_version", "completion_version", "completion_percent",
                "completed_sections", "next_incomplete_section", "is_complete",
                "institutional_email_status", "guardian", "access_mode",
                "disabled_capabilities", "profile_prompt", "missing_requirements",
                "profile",
            }
            nested = body.get("profile")
            return bool(
                set(body) == exact_top
                and isinstance(body.get("profile_version"), int)
                and body.get("completion_version") == "v1"
                and body.get("completion_percent") in {0, 34, 67, 100}
                and isinstance(nested, Mapping)
                and set(nested) == {"personal", "academic", "interests"}
                and set(nested["personal"]) == {
                    "first_name", "middle_name", "last_name", "date_of_birth",
                    "preferred_language", "city", "pronouns",
                }
                and set(nested["academic"]) == {
                    "college", "year_of_study", "enrolment_number",
                    "institutional_email", "bar_enrolment_number",
                }
                and set(nested["interests"]) == {"interests", "goals"}
                and not {
                    "mobile", "mobile_hash", "registration_id", "profile_id", "user_id"
                }.intersection(body)
            )

        registration_graph_tables = (
            "users",
            "student_registrations",
            "student_profiles",
            "student_verifications",
            "guardian_consents",
            "consents",
            "registration_idempotency_records",
            "otp_purpose_authorities",
            "otp_flows",
            "otp_challenges",
            "otp_outbox",
            "otp_rate_limit_buckets",
            "audit_events",
        )

        def registration_graph_counts() -> tuple[int, ...]:
            with engine.connect() as connection:
                return tuple(
                    int(
                        connection.scalar(
                            text(f'SELECT count(*) FROM "{table_name}"')
                        )
                        or 0
                    )
                    for table_name in registration_graph_tables
                )

        def registration_body(mobile: str, **overrides: object) -> dict[str, object]:
            body: dict[str, object] = {
                "first_name": "Aditi",
                "middle_name": None,
                "last_name": "Nair",
                "mobile": mobile,
                "dob": "2004-03-14",
                "terms_accepted": True,
                "terms_version": "terms-2026-08.v1",
                "privacy_notice_acknowledged": True,
                "privacy_notice_version": "privacy-2026-08.v1",
            }
            body.update(overrides)
            return body

        def registration_safe_projection(response: object) -> bool:
            if not hasattr(response, "status_code") or response.status_code != 202:
                return False
            body = response.json()
            return bool(
                isinstance(body, Mapping)
                and set(body)
                == {
                    "status",
                    "next",
                    "expires_in_seconds",
                    "resend_after_seconds",
                }
                and body.get("status") == "accepted"
                and body.get("next") == "otp"
                and isinstance(body.get("expires_in_seconds"), int)
                and body.get("expires_in_seconds", 0) > 0
                and isinstance(body.get("resend_after_seconds"), int)
                and body.get("resend_after_seconds", -1) >= 0
            )

        registration_client = client_for(None)
        original_rate_budgets = auth_student.otp_authority.consume_rate_budgets
        hostile_registration_preconditions: list[bool] = []
        invalid_legal_cases = (
            ("terms_accepted", True, "terms_acceptance_required"),
            ("terms_accepted", False, "terms_acceptance_required"),
            (
                "privacy_notice_acknowledged",
                True,
                "privacy_notice_acknowledgement_required",
            ),
            (
                "privacy_notice_acknowledged",
                False,
                "privacy_notice_acknowledgement_required",
            ),
        )
        try:
            for hostile in ("sender-unavailable", "rate-exhausted"):
                if hostile == "sender-unavailable":
                    app.dependency_overrides[auth_student.get_otp_sender] = (
                        lambda: None
                    )
                    auth_student.otp_authority.consume_rate_budgets = (
                        original_rate_budgets
                    )
                else:
                    app.dependency_overrides[auth_student.get_otp_sender] = (
                        lambda: registration_sender
                    )

                    def forbidden_rate_budget(*_args: object, **_kwargs: object) -> None:
                        raise ProductGateFailure(
                            "invalid legal request reached rate authority"
                        )

                    auth_student.otp_authority.consume_rate_budgets = (
                        forbidden_rate_budget
                    )

                for field, omit, expected_code in invalid_legal_cases:
                    invalid_body = registration_body("7987654300")
                    if omit:
                        invalid_body.pop(field)
                    else:
                        invalid_body[field] = False
                    before_counts = registration_graph_counts()
                    before_deliveries = len(registration_sender.sent)
                    invalid_response = registration_client.post(
                        "/api/v1/auth/student/register",
                        json=invalid_body,
                    )
                    detail = invalid_response.json().get("detail", {})
                    hostile_registration_preconditions.append(
                        invalid_response.status_code == 422
                        and detail
                        == {
                            "code": expected_code,
                            "field": field,
                            "message": "Request failed",
                        }
                        and registration_graph_counts() == before_counts
                        and len(registration_sender.sent) == before_deliveries
                    )
        finally:
            auth_student.otp_authority.consume_rate_budgets = original_rate_budgets
            app.dependency_overrides[auth_student.get_otp_sender] = (
                lambda: registration_sender
            )
        observations["registration_consent_zero_mutation"] = bool(
            len(hostile_registration_preconditions) == 8
            and all(hostile_registration_preconditions)
        )

        suspended_mobile = "7987654302"
        ineligible_mobile = "7987654303"
        suspended_actor = seed_actor(
            "registration-suspended", user_status="suspended"
        )
        ineligible_actor = seed_actor(
            "registration-ineligible", user_status="deleted"
        )
        with factory.begin() as session:
            suspended_registration = session.get(
                StudentRegistration, suspended_actor["registration_id"]
            )
            ineligible_registration = session.get(
                StudentRegistration, ineligible_actor["registration_id"]
            )
            assert suspended_registration is not None
            assert ineligible_registration is not None
            suspended_registration.mobile_hash = keyed_hash(suspended_mobile)
            suspended_registration.mobile_ct = encrypt(suspended_mobile)
            suspended_registration.status = "suspended"
            ineligible_registration.mobile_hash = keyed_hash(ineligible_mobile)
            ineligible_registration.mobile_ct = encrypt(ineligible_mobile)

        registration_count_before = registration_graph_counts()[1]
        new_mobile = "7987654301"
        new_registration = registration_client.post(
            "/api/v1/auth/student/register",
            json=registration_body(new_mobile),
        )
        known_registration = registration_client.post(
            "/api/v1/auth/student/register",
            json=registration_body(new_mobile),
        )
        duplicate_registration = registration_client.post(
            "/api/v1/auth/student/register",
            json=registration_body(
                new_mobile,
                first_name="Other",
                last_name="Person",
                dob="2001-01-01",
            ),
        )
        suspended_registration_response = registration_client.post(
            "/api/v1/auth/student/register",
            json=registration_body(suspended_mobile),
        )
        ineligible_registration_response = registration_client.post(
            "/api/v1/auth/student/register",
            json=registration_body(ineligible_mobile),
        )
        registration_responses = (
            new_registration,
            known_registration,
            duplicate_registration,
            suspended_registration_response,
            ineligible_registration_response,
        )
        registration_response_bodies = [
            response.json() for response in registration_responses
        ]
        with factory() as session:
            new_registration_row = session.scalar(
                select(StudentRegistration).where(
                    StudentRegistration.mobile_hash == keyed_hash(new_mobile)
                )
            )
            suspended_registration_row = session.scalar(
                select(StudentRegistration).where(
                    StudentRegistration.mobile_hash
                    == keyed_hash(suspended_mobile)
                )
            )
            ineligible_registration_row = session.scalar(
                select(StudentRegistration).where(
                    StudentRegistration.mobile_hash
                    == keyed_hash(ineligible_mobile)
                )
            )
            ineligible_user = (
                session.get(User, ineligible_registration_row.user_id)
                if ineligible_registration_row is not None
                else None
            )
        observations["registration_enumeration_neutral"] = bool(
            all(registration_safe_projection(response) for response in registration_responses)
            and len(registration_response_bodies) == 5
            and all(
                body == registration_response_bodies[0]
                for body in registration_response_bodies[1:]
            )
            and registration_graph_counts()[1] == registration_count_before + 1
            and new_registration_row is not None
            and new_registration_row.first_name == "Aditi"
            and new_registration_row.last_name == "Nair"
            and decrypt(new_registration_row.dob_ct) == "2004-03-14"
            and suspended_registration_row is not None
            and suspended_registration_row.first_name == "Synthetic"
            and suspended_registration_row.status == "suspended"
            and ineligible_registration_row is not None
            and ineligible_registration_row.first_name == "Synthetic"
            and ineligible_user is not None
            and ineligible_user.status == "deleted"
        )
        registration_client.close()

        settings.app_env = "production"
        non_test_header_client = client_for(None)
        non_test_actor_response = non_test_header_client.get(
            "/api/v1/student/profile",
            headers={
                "X-Actor-Claims": json.dumps(
                    {"sub": str(uuid.uuid4()), "roles": ["student"]}
                )
            },
        )
        non_test_header_client.close()
        settings.app_env = "testing"
        observations["non_test_actor_header_rejected"] = bool(
            non_test_actor_response.status_code == 401
            and set(non_test_actor_response.json()) == {"detail", "request_id"}
            and non_test_actor_response.json().get("detail")
            == {
                "code": "authentication_required",
                "message": "Request failed",
            }
            and isinstance(non_test_actor_response.json().get("request_id"), str)
            and bool(non_test_actor_response.headers.get("X-Request-ID"))
        )

        owner = seed_actor("owner")
        owner_client = client_for(owner)
        initial = owner_client.get("/api/v1/student/profile")
        initial_body = initial.json() if initial.status_code == 200 else {}
        observations["owner_projection"] = bool(
            initial.status_code == 200
            and projection_exact(initial_body)
            and initial_body.get("profile_version") == 1
            and initial_body.get("completion_percent") == 0
        )

        skip_academic = owner_client.patch(
            "/api/v1/student/profile/academic",
            json={
                "expected_profile_version": 1,
                "college": "National Law School of India University",
                "year_of_study": "4th",
                "enrolment_number": "QA/42/2026",
                "institutional_email": "student@synthetic.edu",
                "bar_enrolment_number": None,
            },
        )
        personal_response = owner_client.patch(
            "/api/v1/student/profile/personal", json=personal(1)
        )
        academic_response = owner_client.patch(
            "/api/v1/student/profile/academic",
            json={
                "expected_profile_version": 2,
                "college": "National Law School of India University",
                "year_of_study": "4th",
                "enrolment_number": "QA/42/2026",
                "institutional_email": "student@synthetic.edu",
                "bar_enrolment_number": None,
            },
        )
        interests_response = owner_client.patch(
            "/api/v1/student/profile/interests",
            json={
                "expected_profile_version": 3,
                "interests": ["Constitutional law", "Constitutional law"],
                "goals": ["Moot court", "Moot court"],
            },
        )
        personal_body = personal_response.json() if personal_response.status_code == 200 else {}
        academic_body = academic_response.json() if academic_response.status_code == 200 else {}
        interests_body = interests_response.json() if interests_response.status_code == 200 else {}
        observations["section_order"] = bool(
            skip_academic.status_code == 409
            and skip_academic.json().get("detail", {}).get("code")
            == "profile_section_prerequisite_incomplete"
        )
        observations["completion"] = bool(
            personal_body.get("completion_percent") == 34
            and personal_body.get("completed_sections") == ["personal"]
            and academic_body.get("completion_percent") == 67
            and academic_body.get("completed_sections") == ["personal", "academic"]
            and interests_body.get("completion_percent") == 100
            and interests_body.get("completed_sections")
            == ["personal", "academic", "interests"]
            and interests_body.get("profile", {}).get("interests")
            == {"interests": ["Constitutional law"], "goals": ["Moot court"]}
        )
        observations["verification_independent"] = bool(
            interests_body.get("completion_percent") == 100
            and interests_body.get("institutional_email_status") == "pending"
        )
        observations["normalization"] = bool(
            interests_body.get("profile", {}).get("interests")
            == {"interests": ["Constitutional law"], "goals": ["Moot court"]}
            and callable(profile_service.normalize_legal_name)
        )
        fresh_client = client_for(owner)
        fresh_projection = fresh_client.get("/api/v1/student/profile")
        observations["fresh_session"] = bool(
            fresh_projection.status_code == 200
            and fresh_projection.json().get("profile_version") == 4
            and fresh_projection.json().get("completion_percent") == 100
        )

        forged_payload = {**personal(4), "registration_id": str(uuid.uuid4())}
        forged_body = owner_client.patch(
            "/api/v1/student/profile/personal", json=forged_payload
        )
        other = seed_actor("other")
        forged_header = owner_client.get(
            "/api/v1/student/profile",
            headers={
                "Origin": origin,
                "X-Actor-Claims": json.dumps(
                    {"sub": str(other["user_id"]), "roles": ["student"]}
                ),
            },
        )
        forged_query = owner_client.get(
            "/api/v1/student/profile",
            params={"registration_id": str(other["registration_id"])},
        )
        observations["client_selector_denial"] = bool(
            forged_body.status_code == 422
            and forged_header.status_code == 200
            and forged_header.json().get("profile_version") == 4
            and forged_query.status_code == 422
        )
        observations["cross_user_denied"] = bool(
            forged_header.status_code == 200
            and forged_header.json().get("profile_version") == 4
            and forged_body.status_code == 422
        )

        anonymous = client_for(None).get("/api/v1/student/profile")
        expired = client_for(seed_actor("expired", session_expired=True)).get(
            "/api/v1/student/profile"
        )
        revoked = client_for(seed_actor("revoked", session_status="revoked")).get(
            "/api/v1/student/profile"
        )
        deleted = client_for(seed_actor("deleted", registration_deleted=True)).get(
            "/api/v1/student/profile"
        )
        wrong_role = client_for(seed_actor("wrong-role", user_role="moderator")).get(
            "/api/v1/student/profile"
        )
        observations["denial_matrix"] = [
            anonymous.status_code,
            expired.status_code,
            revoked.status_code,
            deleted.status_code,
            wrong_role.status_code,
        ] == [401, 401, 401, 401, 403]

        conflict_actor = seed_actor("conflict")
        before_conflict_audits: int
        with factory() as session:
            before_conflict_audits = int(
                session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.actor_user_id == conflict_actor["user_id"],
                        AuditEvent.action == "student.profile.section_updated",
                    )
                )
                or 0
            )

        def concurrent_personal(city: str):
            return client_for(conflict_actor).patch(
                "/api/v1/student/profile/personal", json=personal(1, city=city)
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            conflict_responses = list(
                executor.map(concurrent_personal, ["Pune", "Chennai"])
            )
        conflict_statuses = sorted(response.status_code for response in conflict_responses)
        with factory() as session:
            conflict_profile = session.get(StudentProfile, conflict_actor["profile_id"])
            after_conflict_audits = int(
                session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.actor_user_id == conflict_actor["user_id"],
                        AuditEvent.action == "student.profile.section_updated",
                    )
                )
                or 0
            )
            conflict_city = conflict_profile.city if conflict_profile else None
            conflict_version = conflict_profile.profile_version if conflict_profile else None
        cas_source = pyinspect.getsource(profile_service._cas)
        observations["cas_sql_exact"] = all(
            fragment in cas_source
            for fragment in (
                "StudentProfile.profile_version == expected_profile_version",
                ".returning(StudentProfile.profile_version)",
                "session.rollback()",
            )
        )
        observations["concurrency"] = conflict_statuses == [200, 409]
        observations["stale_conflict_rejected"] = any(
            response.status_code == 409
            and response.json().get("detail", {}).get("code")
            == "profile_version_conflict"
            for response in conflict_responses
        )
        observations["conflict_atomic"] = bool(
            conflict_version == 2
            and conflict_city in {"Pune", "Chennai"}
            and after_conflict_audits == before_conflict_audits + 1
        )

        prompt_actor = seed_actor("prompt")
        prompt_client = client_for(prompt_actor)
        prompt_before = prompt_client.get("/api/v1/student/profile")
        with ThreadPoolExecutor(max_workers=2) as executor:
            prompt_dismissals = list(
                executor.map(
                    lambda _index: client_for(prompt_actor).post(
                        "/api/v1/student/profile/prompt-dismiss", json={}
                    ),
                    range(2),
                )
            )
        prompt_dismissed = prompt_dismissals[0]
        with factory() as session:
            prompt_row_count = int(
                session.scalar(
                    select(func.count(AuthSessionProfilePrompt.id)).where(
                        AuthSessionProfilePrompt.auth_session_id
                        == prompt_actor["session_id"]
                    )
                )
                or 0
            )
        with factory() as session:
            prior_registration = session.get(
                StudentRegistration, prompt_actor["registration_id"]
            )
            if prior_registration is None:
                raise ProductGateFailure("prompt session rotation setup failed")
            rotated_token, rotated_session = login_service.rotate_authenticated_session(
                session, prior_registration, fixed_now + timedelta(minutes=1)
            )
            rotated_session_id = rotated_session.id
        with factory() as session:
            old_prompt_count = int(
                session.scalar(
                    select(func.count(AuthSessionProfilePrompt.id)).where(
                        AuthSessionProfilePrompt.auth_session_id
                        == prompt_actor["session_id"]
                    )
                )
                or 0
            )
            old_session = session.get(AuthSession, prompt_actor["session_id"])
        rotated_actor = {
            **prompt_actor,
            "token": rotated_token,
            "session_id": rotated_session_id,
        }
        prompt_rotated = client_for(rotated_actor).get("/api/v1/student/profile")
        observations["prompt_scope"] = bool(
            prompt_before.status_code == 200
            and prompt_before.json().get("profile_prompt", {}).get("should_show") is True
            and sorted(response.status_code for response in prompt_dismissals)
            == [200, 200]
            and prompt_row_count == 1
            and prompt_dismissed.json().get("profile_prompt")
            == {"should_show": False, "dismissed_for_session": True}
            and prompt_rotated.status_code == 200
            and prompt_rotated.json().get("profile_prompt")
            == {"should_show": True, "dismissed_for_session": False}
            and old_prompt_count == 0
            and old_session is not None
            and old_session.status == "revoked"
        )

        def prompt_count(session_id: object) -> int:
            with factory() as session:
                return int(
                    session.scalar(
                        select(func.count(AuthSessionProfilePrompt.id)).where(
                            AuthSessionProfilePrompt.auth_session_id == session_id
                        )
                    )
                    or 0
                )

        rotation_race_actor = seed_actor("prompt-rotation-race")
        rotation_race_client = client_for(rotation_race_actor)
        rotation_seed = rotation_race_client.post(
            "/api/v1/student/profile/prompt-dismiss", json={}
        )

        def rotate_race_session(_index: int):
            with factory() as session:
                registration = session.get(
                    StudentRegistration,
                    rotation_race_actor["registration_id"],
                )
                if registration is None:
                    raise ProductGateFailure("prompt rotation race setup failed")
                token, auth_session = login_service.rotate_authenticated_session(
                    session,
                    registration,
                    fixed_now + timedelta(minutes=2),
                )
                return token, auth_session.id

        with ThreadPoolExecutor(max_workers=2) as executor:
            rotation_future = executor.submit(rotate_race_session, 0)
            rotation_dismiss_future = executor.submit(
                lambda: client_for(rotation_race_actor).post(
                    "/api/v1/student/profile/prompt-dismiss", json={}
                )
            )
            rotation_token, rotation_session_id = rotation_future.result()
            rotation_dismiss_status = rotation_dismiss_future.result().status_code
        with factory() as session:
            rotation_old_session = session.get(
                AuthSession, rotation_race_actor["session_id"]
            )
        rotation_projection = client_for(
            {
                **rotation_race_actor,
                "token": rotation_token,
                "session_id": rotation_session_id,
            }
        ).get("/api/v1/student/profile")

        logout_race_actor = seed_actor("prompt-logout-race")
        logout_race_client = client_for(logout_race_actor)
        logout_seed = logout_race_client.post(
            "/api/v1/student/profile/prompt-dismiss", json={}
        )
        with ThreadPoolExecutor(max_workers=2) as executor:
            logout_future = executor.submit(
                lambda: client_for(logout_race_actor).post(
                    "/api/v1/auth/student/logout", json={}
                )
            )
            logout_dismiss_future = executor.submit(
                lambda: client_for(logout_race_actor).post(
                    "/api/v1/student/profile/prompt-dismiss", json={}
                )
            )
            logout_status = logout_future.result().status_code
            logout_dismiss_status = logout_dismiss_future.result().status_code
        with factory() as session:
            logout_old_session = session.get(
                AuthSession, logout_race_actor["session_id"]
            )

        expiry_race_actor = seed_actor("prompt-expiry-race")
        expiry_race_client = client_for(expiry_race_actor)
        expiry_seed = expiry_race_client.post(
            "/api/v1/student/profile/prompt-dismiss", json={}
        )

        def expire_race_session() -> bool:
            with factory.begin() as session:
                auth_session = session.scalar(
                    select(AuthSession)
                    .where(AuthSession.id == expiry_race_actor["session_id"])
                    .with_for_update()
                )
                if auth_session is None:
                    return False
                auth_session.expires_at = fixed_now - timedelta(seconds=1)
                return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            expiry_future = executor.submit(expire_race_session)
            expiry_dismiss_future = executor.submit(
                lambda: client_for(expiry_race_actor).post(
                    "/api/v1/student/profile/prompt-dismiss", json={}
                )
            )
            expiry_mutated = expiry_future.result()
            expiry_dismiss_status = expiry_dismiss_future.result().status_code
        expiry_discovery = expiry_race_client.get(
            "/api/v1/auth/student/session"
        )
        with factory() as session:
            expiry_old_session = session.get(
                AuthSession, expiry_race_actor["session_id"]
            )

        observations["prompt_lifecycle_races"] = bool(
            rotation_seed.status_code == 200
            and rotation_dismiss_status in {200, 401}
            and prompt_count(rotation_race_actor["session_id"]) == 0
            and rotation_old_session is not None
            and rotation_old_session.status == "revoked"
            and rotation_projection.status_code == 200
            and rotation_projection.json().get("profile_prompt")
            == {"should_show": True, "dismissed_for_session": False}
            and logout_seed.status_code == 200
            and logout_status == 200
            and logout_dismiss_status in {200, 401}
            and prompt_count(logout_race_actor["session_id"]) == 0
            and logout_old_session is not None
            and logout_old_session.status == "revoked"
            and expiry_seed.status_code == 200
            and expiry_mutated
            and expiry_dismiss_status in {200, 401}
            and expiry_discovery.status_code == 200
            and expiry_discovery.json()
            == {"authenticated": False, "actor": None}
            and prompt_count(expiry_race_actor["session_id"]) == 0
            and expiry_old_session is not None
            and expiry_old_session.status == "expired"
        )

        reviewer = seed_actor(
            "verification-reviewer", user_role="legal_reviewer"
        )

        def review_registration(registration_id: object, version: int):
            return client_for(reviewer).post(
                "/api/v1/auth/student/verification/status",
                json={
                    "registration_id": str(registration_id),
                    "status": "verified",
                    "expected_profile_version": version,
                },
            )

        def reviewer_wire_exact(response, version: int) -> bool:
            return response.status_code != 200 or response.json() == {
                "status": "verified",
                "profile_version": version,
                "owner_projection_invalidated": True,
            }

        dob_actor = seed_actor("dob", dob=date(2000, 1, 1))
        dob_client = client_for(dob_actor)
        exact_adult = dob_client.patch(
            "/api/v1/student/profile/personal",
            json=personal(1, dob="2008-08-22"),
        )
        one_day_minor = dob_client.patch(
            "/api/v1/student/profile/personal",
            json=personal(2, dob="2008-08-23"),
        )
        self_guardian = dob_client.post(
            "/api/v1/auth/student/guardian-consent/complete", json={}
        )
        student_verification_denied = dob_client.post(
            "/api/v1/auth/student/verification/status",
            json={
                "registration_id": str(dob_actor["registration_id"]),
                "status": "verified",
                "expected_profile_version": 3,
            },
        )
        back_to_adult = dob_client.patch(
            "/api/v1/student/profile/personal",
            json=personal(3, dob="2008-08-22"),
        )
        dob_academic = dob_client.patch(
            "/api/v1/student/profile/academic",
            json={
                "expected_profile_version": 4,
                "college": "National Law School of India University",
                "year_of_study": "4th",
                "enrolment_number": "QA/45/2026",
                "institutional_email": "dob-authority@synthetic.edu",
                "bar_enrolment_number": None,
            },
        )
        dob_review_request = dob_client.post(
            "/api/v1/auth/student/verification/email/request", json={}
        )
        dob_reviewed = review_registration(dob_actor["registration_id"], 5)
        before_verified_change = dob_client.get("/api/v1/student/profile").json()
        verified_change = dob_client.patch(
            "/api/v1/student/profile/personal",
            json=personal(5, dob="2007-08-22"),
        )
        with factory() as session:
            dob_registration = session.get(
                StudentRegistration, dob_actor["registration_id"]
            )
            guardian_count = int(
                session.scalar(
                    select(func.count(GuardianConsent.id)).where(
                        GuardianConsent.registration_id == dob_actor["registration_id"]
                    )
                )
                or 0
            )
            stored_dob = decrypt(dob_registration.dob_ct) if dob_registration else None
        observations["dob_boundaries"] = bool(
            exact_adult.status_code == 200
            and exact_adult.json().get("guardian")
            == {"required": False, "status": "not_required"}
            and one_day_minor.status_code == 200
            and one_day_minor.json().get("guardian")
            == {"required": True, "status": "required_pending"}
        )
        observations["dob_guardian"] = bool(
            one_day_minor.json().get("access_mode") == "limited"
            and one_day_minor.json().get("disabled_capabilities")
            == ["community", "sharing"]
            and guardian_count == 1
            and back_to_adult.status_code == 200
            and back_to_adult.json().get("guardian")
            == {"required": False, "status": "not_required"}
            and dob_academic.status_code == 200
            and dob_review_request.status_code == 202
            and dob_reviewed.status_code == 200
            and reviewer_wire_exact(dob_reviewed, 5)
            and verified_change.status_code == 403
            and verified_change.json().get("detail", {}).get("code")
            == "dob_step_up_required"
            and stored_dob == "2008-08-22"
            and before_verified_change.get("profile_version") == 5
        )
        observations["clock_injected"] = bool(
            observations["dob_boundaries"]
            and "request_date = now.date()" in pyinspect.getsource(
                profile_service.update_personal
            )
        )
        observations["self_authority_denied"] = bool(
            self_guardian.status_code == 403
            and self_guardian.json().get("detail", {}).get("code")
            == "guardian_self_approval_forbidden"
            and student_verification_denied.status_code == 403
            and student_verification_denied.json().get("detail", {}).get("code")
            == "verification_reviewer_required"
        )

        leap_actor = seed_actor("leap-day", dob=date(2000, 1, 1))
        leap_client = client_for(leap_actor)
        request_clock["now"] = datetime(2026, 2, 28, 12, 0, tzinfo=timezone.utc)
        leap_minor = leap_client.patch(
            "/api/v1/student/profile/personal",
            json=personal(1, dob="2008-02-29"),
        )
        request_clock["now"] = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
        leap_adult = leap_client.patch(
            "/api/v1/student/profile/personal",
            json=personal(2, dob="2008-02-29"),
        )
        offset_actor = seed_actor("civil-day", dob=date(2000, 1, 1))
        offset_client = client_for(offset_actor)
        request_clock["now"] = datetime(
            2026, 3, 1, 0, 15, tzinfo=timezone(timedelta(hours=5, minutes=30))
        )
        civil_day_adult = offset_client.patch(
            "/api/v1/student/profile/personal",
            json=personal(1, dob="2008-03-01"),
        )
        request_clock["now"] = fixed_now
        leap_and_timezone_exact = bool(
            leap_minor.status_code == 200
            and leap_minor.json().get("guardian")
            == {"required": True, "status": "required_pending"}
            and leap_adult.status_code == 200
            and leap_adult.json().get("guardian")
            == {"required": False, "status": "not_required"}
            and civil_day_adult.status_code == 200
            and civil_day_adult.json().get("guardian")
            == {"required": False, "status": "not_required"}
        )
        observations["dob_boundaries"] = bool(
            observations["dob_boundaries"] and leap_and_timezone_exact
        )
        observations["clock_injected"] = bool(
            observations["clock_injected"] and leap_and_timezone_exact
        )

        sharing_actor = seed_actor("limited-sharing", dob=date(2000, 1, 1))
        sharing_client = client_for(sharing_actor)
        limited_profile = sharing_client.patch(
            "/api/v1/student/profile/personal",
            json=personal(1, dob="2010-01-01"),
        )
        with factory.begin() as session:
            guardian = session.scalar(
                select(GuardianConsent).where(
                    GuardianConsent.registration_id
                    == sharing_actor["registration_id"]
                )
            )
            assert guardian is not None
            # A bare mutable positive has no ceremony/reviewer provenance and
            # must remain non-authorizing in every consumer.
            guardian.status = "verified"
            guardian.verified = True
            credential = Credential(
                owner_user_id=sharing_actor["user_id"],
                issuer_id=None,
                title="Synthetic credential",
                credential_type="certificate",
                status="verified",
                issue_date=date(2026, 1, 1),
                expiry_date=None,
                key_version="v1",
                version=1,
                idempotency_key="nyay5-gate-credential",
            )
            session.add(credential)
            session.flush()
            credential_id = credential.id
        with factory() as session:
            before_sharing_rows = (
                int(session.scalar(select(func.count(CredentialShareProjection.id))) or 0),
                int(session.scalar(select(func.count(VerificationToken.id))) or 0),
                int(
                    session.scalar(
                        select(func.count(AuditEvent.id)).where(
                            AuditEvent.action.in_(
                                (
                                    "credential.share_projection_created",
                                    "credential.verification_token_created",
                                )
                            )
                        )
                    )
                    or 0
                ),
            )
        denied_projection = sharing_client.post(
            f"/api/v1/credentials/{credential_id}/share-projections",
            headers={"Idempotency-Key": "nyay5-share-denied"},
            json={"fields": ["title"]},
        )
        denied_token = sharing_client.post(
            f"/api/v1/credentials/{credential_id}/verification-tokens",
            headers={"Idempotency-Key": "nyay5-token-denied"},
            json={"projection_id": str(uuid.uuid4()), "lifetime_days": 1},
        )
        forged_guardian_projection = sharing_client.get(
            "/api/v1/student/profile"
        )
        with factory() as session:
            after_sharing_rows = (
                int(session.scalar(select(func.count(CredentialShareProjection.id))) or 0),
                int(session.scalar(select(func.count(VerificationToken.id))) or 0),
                int(
                    session.scalar(
                        select(func.count(AuditEvent.id)).where(
                            AuditEvent.action.in_(
                                (
                                    "credential.share_projection_created",
                                    "credential.verification_token_created",
                                )
                            )
                        )
                    )
                    or 0
                ),
            )
        limited_sharing_denied = bool(
            limited_profile.status_code == 200
            and limited_profile.json().get("access_mode") == "limited"
            and forged_guardian_projection.status_code == 200
            and forged_guardian_projection.json().get("access_mode") == "limited"
            and forged_guardian_projection.json().get("guardian")
            == {"required": True, "status": "revoked"}
            and denied_projection.status_code == 403
            and denied_projection.json().get("detail", {}).get("code")
            == "guardian_verification_required"
            and denied_token.status_code == 403
            and denied_token.json().get("detail", {}).get("code")
            == "guardian_verification_required"
            and after_sharing_rows == before_sharing_rows
        )
        observations["self_authority_denied"] = bool(
            observations["self_authority_denied"] and limited_sharing_denied
        )

        def seed_credential_race(
            label: str, *, with_projection: bool
        ) -> tuple[dict[str, object], TestClient, object, object | None]:
            actor = seed_actor(label, dob=date(2000, 1, 1))
            client = client_for(actor)
            adult = client.patch(
                "/api/v1/student/profile/personal", json=personal(1)
            )
            if adult.status_code != 200:
                raise ProductGateFailure("credential race actor setup failed")
            with factory.begin() as session:
                credential = Credential(
                    owner_user_id=actor["user_id"],
                    issuer_id=None,
                    title="Synthetic race credential",
                    credential_type="certificate",
                    status="verified",
                    issue_date=date(2026, 1, 1),
                    expiry_date=None,
                    key_version="v1",
                    version=1,
                    idempotency_key=f"nyay5-race-{label}",
                )
                session.add(credential)
                session.flush()
                race_credential_id = credential.id
            projection_id = None
            if with_projection:
                projection_response = client.post(
                    f"/api/v1/credentials/{race_credential_id}/share-projections",
                    headers={"Idempotency-Key": f"nyay5-race-projection-{label}"},
                    json={"fields": ["title"]},
                )
                if projection_response.status_code != 200:
                    raise ProductGateFailure("credential race projection setup failed")
                projection_id = projection_response.json().get("id")
            return actor, client, race_credential_id, projection_id

        def credential_row_counts() -> tuple[int, int, int]:
            with factory() as session:
                return (
                    int(
                        session.scalar(select(func.count(CredentialShareProjection.id)))
                        or 0
                    ),
                    int(session.scalar(select(func.count(VerificationToken.id))) or 0),
                    int(
                        session.scalar(
                            select(func.count(AuditEvent.id)).where(
                                AuditEvent.action.in_(
                                    (
                                        "credential.share_projection_created",
                                        "credential.verification_token_created",
                                    )
                                )
                            )
                        )
                        or 0
                    ),
                )

        original_commit_projection = profile_service._commit_projection
        original_sharing_guard = credential_api._require_current_sharing_access

        share_actor, share_client, share_credential_id, _ = seed_credential_race(
            "share-dob", with_projection=False
        )
        share_commit_entered = Event()
        share_commit_release = Event()
        sharing_entered = Event()
        share_hold = {"active": True}

        def hold_share_dob_commit(*args, **kwargs):
            if share_hold["active"] and kwargs.get("section") == "personal":
                share_commit_entered.set()
                if not share_commit_release.wait(timeout=10):
                    raise ProductGateFailure("DOB/share race synchronization failed")
            return original_commit_projection(*args, **kwargs)

        def observe_share_guard(*args, **kwargs):
            sharing_entered.set()
            return original_sharing_guard(*args, **kwargs)

        profile_service._commit_projection = hold_share_dob_commit
        credential_api._require_current_sharing_access = observe_share_guard
        share_before = credential_row_counts()
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                dob_future = executor.submit(
                    lambda: client_for(share_actor).patch(
                        "/api/v1/student/profile/personal",
                        json=personal(2, dob="2010-01-01"),
                    )
                )
                share_commit_ready = share_commit_entered.wait(timeout=10)
                share_future = executor.submit(
                    lambda: share_client.post(
                        f"/api/v1/credentials/{share_credential_id}/share-projections",
                        headers={"Idempotency-Key": "nyay5-share-dob-race"},
                        json={"fields": ["title"]},
                    )
                )
                share_guard_ready = sharing_entered.wait(timeout=10)
                share_blocked_on_authority = not share_future.done()
                share_commit_release.set()
                share_dob_response = dob_future.result(timeout=10)
                share_race_response = share_future.result(timeout=10)
        finally:
            share_hold["active"] = False
            share_commit_release.set()
            profile_service._commit_projection = original_commit_projection
            credential_api._require_current_sharing_access = original_sharing_guard
        share_after = credential_row_counts()
        share_final = share_client.get("/api/v1/student/profile")
        observations["share_projection_dob_serialized"] = bool(
            share_commit_ready
            and share_guard_ready
            and share_blocked_on_authority
            and share_dob_response.status_code == 200
            and share_dob_response.json().get("access_mode") == "limited"
            and share_race_response.status_code == 403
            and share_race_response.json().get("detail", {}).get("code")
            == "guardian_verification_required"
            and share_after == share_before
            and share_final.status_code == 200
            and share_final.json().get("access_mode") == "limited"
        )

        token_actor, token_client, token_credential_id, token_projection_id = (
            seed_credential_race("token-dob", with_projection=True)
        )
        token_commit_entered = Event()
        token_commit_release = Event()
        token_entered = Event()
        token_hold = {"active": True}

        def hold_token_dob_commit(*args, **kwargs):
            if token_hold["active"] and kwargs.get("section") == "personal":
                token_commit_entered.set()
                if not token_commit_release.wait(timeout=10):
                    raise ProductGateFailure("DOB/token race synchronization failed")
            return original_commit_projection(*args, **kwargs)

        def observe_token_guard(*args, **kwargs):
            token_entered.set()
            return original_sharing_guard(*args, **kwargs)

        profile_service._commit_projection = hold_token_dob_commit
        credential_api._require_current_sharing_access = observe_token_guard
        token_before = credential_row_counts()
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                token_dob_future = executor.submit(
                    lambda: client_for(token_actor).patch(
                        "/api/v1/student/profile/personal",
                        json=personal(2, dob="2010-01-01"),
                    )
                )
                token_commit_ready = token_commit_entered.wait(timeout=10)
                token_future = executor.submit(
                    lambda: token_client.post(
                        f"/api/v1/credentials/{token_credential_id}/verification-tokens",
                        headers={"Idempotency-Key": "nyay5-token-dob-race"},
                        json={
                            "projection_id": token_projection_id,
                            "lifetime_days": 1,
                        },
                    )
                )
                token_guard_ready = token_entered.wait(timeout=10)
                token_blocked_on_authority = not token_future.done()
                token_commit_release.set()
                token_dob_response = token_dob_future.result(timeout=10)
                token_race_response = token_future.result(timeout=10)
        finally:
            token_hold["active"] = False
            token_commit_release.set()
            profile_service._commit_projection = original_commit_projection
            credential_api._require_current_sharing_access = original_sharing_guard
        token_after = credential_row_counts()
        token_final = token_client.get("/api/v1/student/profile")
        observations["verification_token_dob_serialized"] = bool(
            token_commit_ready
            and token_guard_ready
            and token_blocked_on_authority
            and token_dob_response.status_code == 200
            and token_dob_response.json().get("access_mode") == "limited"
            and token_race_response.status_code == 403
            and token_race_response.json().get("detail", {}).get("code")
            == "guardian_verification_required"
            and token_after == token_before
            and token_final.status_code == 200
            and token_final.json().get("access_mode") == "limited"
        )

        with factory() as session:
            verification_audits_before = int(
                session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.action
                        == "student.verification.email_requested",
                        AuditEvent.actor_user_id == owner["user_id"],
                    )
                )
                or 0
            )

        def request_saved_email_review(_index: int):
            return client_for(owner).post(
                "/api/v1/auth/student/verification/email/request", json={}
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            verification_requests = list(
                executor.map(request_saved_email_review, range(2))
            )
        verification_selector = owner_client.post(
            "/api/v1/auth/student/verification/email/request",
            json={"institutional_email": "forged@synthetic.edu"},
        )
        with factory() as session:
            verification_rows = list(
                session.scalars(
                    select(StudentVerification).where(
                        StudentVerification.registration_id
                        == owner["registration_id"]
                    )
                )
            )
            verification_audits = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action
                        == "student.verification.email_requested",
                        AuditEvent.actor_user_id == owner["user_id"],
                    )
                )
            )
        verification_projection_bodies = [
            response.json()
            for response in verification_requests
            if response.status_code == 202
        ]
        verification_selector_detail = verification_selector.json().get("detail")
        verification_selector_denied_exact = bool(
            verification_selector.status_code == 422
            and set(verification_selector.json()) == {"detail", "request_id"}
            and isinstance(verification_selector_detail, Mapping)
            and set(verification_selector_detail)
            == {"code", "message", "errors", "field"}
            and verification_selector_detail.get("code") == "validation_error"
            and verification_selector_detail.get("message")
            == "Request validation failed"
            and verification_selector_detail.get("field")
            == "institutional_email"
            and verification_selector_detail.get("errors")
            == [
                {
                    "type": "extra_forbidden",
                    "loc": ["body", "institutional_email"],
                    "msg": "Extra inputs are not permitted",
                }
            ]
            and isinstance(verification_selector.json().get("request_id"), str)
            and "forged@synthetic.edu"
            not in json.dumps(verification_selector.json(), sort_keys=True)
        )
        observations["ceremony_selector_absent"] = bool(
            sorted(response.status_code for response in verification_requests)
            == [202, 202]
            and len(verification_projection_bodies) == 2
            and all(
                projection_exact(body)
                and body.get("institutional_email_status") == "pending"
                and body.get("profile_version") == 4
                for body in verification_projection_bodies
            )
            and verification_projection_bodies[0]
            == verification_projection_bodies[1]
            and len(verification_rows) == 1
            and verification_rows[0].status == "in_review"
            and verification_rows[0].verified_email_hash is None
            and len(verification_audits) == verification_audits_before + 1
            and verification_audits[-1].resource_id is None
            and verification_audits[-1].after_state
            == {
                "outcome": "accepted",
                "status": "pending",
                "profile_version": 4,
            }
            and verification_selector_denied_exact
        )

        def change_owner_email():
            return client_for(owner).patch(
                "/api/v1/student/profile/academic",
                json={
                    "expected_profile_version": 4,
                    "college": "National Law School of India University",
                    "year_of_study": "4th",
                    "enrolment_number": "QA/42/2026",
                    "institutional_email": "updated@synthetic.edu",
                    "bar_enrolment_number": None,
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            email_change_future = executor.submit(change_owner_email)
            email_review_future = executor.submit(
                review_registration, owner["registration_id"], 4
            )
            email_change_response = email_change_future.result()
            email_review_response = email_review_future.result()
        email_race_projection = owner_client.get("/api/v1/student/profile")
        with factory() as session:
            email_race_verification = session.scalar(
                select(StudentVerification).where(
                    StudentVerification.registration_id
                    == owner["registration_id"]
                )
            )

        dob_review_actor = seed_actor(
            "dob-review-race", dob=date(2000, 1, 1)
        )
        dob_review_client = client_for(dob_review_actor)
        dob_review_personal = dob_review_client.patch(
            "/api/v1/student/profile/personal", json=personal(1)
        )
        dob_review_academic = dob_review_client.patch(
            "/api/v1/student/profile/academic",
            json={
                "expected_profile_version": 2,
                "college": "National Law School of India University",
                "year_of_study": "4th",
                "enrolment_number": "QA/44/2026",
                "institutional_email": "dob-review@synthetic.edu",
                "bar_enrolment_number": None,
            },
        )
        dob_review_interests = dob_review_client.patch(
            "/api/v1/student/profile/interests",
            json={
                "expected_profile_version": 3,
                "interests": ["Constitutional law"],
                "goals": ["Moot court"],
            },
        )
        dob_review_request = dob_review_client.post(
            "/api/v1/auth/student/verification/email/request", json={}
        )

        def change_reviewed_dob():
            return client_for(dob_review_actor).patch(
                "/api/v1/student/profile/personal",
                json=personal(4, dob="2001-01-01"),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            dob_change_future = executor.submit(change_reviewed_dob)
            dob_review_future = executor.submit(
                review_registration, dob_review_actor["registration_id"], 4
            )
            dob_change_response = dob_change_future.result()
            dob_review_response = dob_review_future.result()
        with factory() as session:
            dob_race_registration = session.get(
                StudentRegistration, dob_review_actor["registration_id"]
            )
            dob_race_profile = session.get(
                StudentProfile, dob_review_actor["profile_id"]
            )
            dob_race_verification = session.scalar(
                select(StudentVerification).where(
                    StudentVerification.registration_id
                    == dob_review_actor["registration_id"]
                )
            )
            dob_race_value = (
                decrypt(dob_race_registration.dob_ct)
                if dob_race_registration is not None
                else None
            )
        dob_race_serialized = bool(
            (
                dob_change_response.status_code == 200
                and dob_review_response.status_code == 409
                and dob_race_profile is not None
                and dob_race_profile.profile_version == 5
                and dob_race_value == "2001-01-01"
                and dob_race_verification is not None
                and dob_race_verification.status != "verified"
                and dob_race_verification.verified_email_hash is None
            )
            or (
                dob_change_response.status_code == 403
                and dob_change_response.json().get("detail", {}).get("code")
                == "dob_step_up_required"
                and dob_review_response.status_code == 200
                and dob_race_profile is not None
                and dob_race_profile.profile_version == 4
                and dob_race_value == "2000-01-01"
                and dob_race_verification is not None
                and dob_race_verification.status == "verified"
                and dob_race_verification.verified_email_hash is not None
            )
        )
        observations["reviewer_serialization"] = bool(
            email_change_response.status_code == 200
            and email_review_response.status_code in {200, 409}
            and reviewer_wire_exact(email_review_response, 4)
            and email_race_projection.status_code == 200
            and email_race_projection.json().get("profile_version") == 5
            and email_race_projection.json().get("institutional_email_status")
            == "pending"
            and email_race_projection.json().get("profile", {})
            .get("academic", {})
            .get("institutional_email")
            == "updated@synthetic.edu"
            and email_race_verification is not None
            and email_race_verification.status == "pending"
            and email_race_verification.verified_email_hash is None
            and dob_review_personal.status_code == 200
            and dob_review_academic.status_code == 200
            and dob_review_interests.status_code == 200
            and dob_review_request.status_code == 202
            and reviewer_wire_exact(dob_review_response, 4)
            and dob_race_serialized
        )
        observations["authorized_transitions_exact"] = bool(
            observations["self_authority_denied"]
            and dob_reviewed.status_code == 200
            and dob_reviewed.json()
            == {
                "status": "verified",
                "profile_version": 5,
                "owner_projection_invalidated": True,
            }
            and observations["reviewer_serialization"]
        )

        def effect_error_code(response: object) -> str | None:
            body = response.json() if hasattr(response, "json") else None
            detail = body.get("detail") if isinstance(body, Mapping) else None
            return detail.get("code") if isinstance(detail, Mapping) else None

        def session_status(actor: Mapping[str, object]) -> str | None:
            with factory() as session:
                row = session.get(AuthSession, actor["session_id"])
                return row.status if row is not None else None

        def identify_postgres_backend(session: object, label: str) -> int:
            pid, applied_label = session.execute(
                text(
                    "SELECT pg_backend_pid(), "
                    "set_config('application_name', :label, true)"
                ),
                {"label": label},
            ).one()
            if not isinstance(pid, int) or applied_label != label:
                raise ProductGateFailure("PostgreSQL backend identity failed")
            return pid

        def postgres_lock_wait_observed(
            *,
            waiting_pid: int,
            waiting_label: str,
            blocker_pid: int,
            blocker_label: str,
            timeout_seconds: float = 5.0,
        ) -> bool:
            """Observe an exact backend blocked on another exact backend lock."""

            deadline = monotonic() + timeout_seconds
            while monotonic() < deadline:
                with engine.connect() as observer:
                    row = observer.execute(
                        text(
                            "SELECT waiting.application_name, "
                            "waiting.wait_event_type, waiting.wait_event, "
                            "pg_blocking_pids(waiting.pid), "
                            "blocker.application_name "
                            "FROM pg_stat_activity AS waiting "
                            "JOIN pg_stat_activity AS blocker "
                            "ON blocker.pid = :blocker_pid "
                            "WHERE waiting.pid = :waiting_pid"
                        ),
                        {
                            "waiting_pid": waiting_pid,
                            "blocker_pid": blocker_pid,
                        },
                    ).one_or_none()
                if row is not None:
                    (
                        observed_waiting_label,
                        wait_event_type,
                        wait_event,
                        blocking_pids,
                        observed_blocker_label,
                    ) = row
                    if (
                        observed_waiting_label == waiting_label
                        and observed_blocker_label == blocker_label
                        and wait_event_type == "Lock"
                        and wait_event in {"tuple", "transactionid"}
                        and blocker_pid in set(blocking_pids or ())
                    ):
                        return True
                sleep(0.01)
            return False

        def run_effect_lifecycle_race(
            label: str,
            *,
            lifecycle_first_actor: Mapping[str, object],
            lifecycle_first_effect: Callable[[], object],
            lifecycle_first_snapshot: Callable[[], object],
            lifecycle_first_error: str,
            mutation_first_actor: Mapping[str, object],
            mutation_first_effect: Callable[[], object],
            mutation_first_snapshot: Callable[[], object],
            mutation_first_changed: Callable[[object, object, object], bool],
            lock_wait_timeout_seconds: float = 5.0,
        ) -> bool:
            """Prove both serial orders around the cookie lifecycle lock pair.

            The first phase holds a real PostgreSQL ``FOR UPDATE`` lock on the
            presented session while the HTTP effect has already resolved its
            actor, locked its domain graph, and locked/reloaded the exact User.
            Revocation commits first; the blocked effect must then reject with
            no domain change.  The second phase pauses only after the product
            helper owns both User and exact AuthSession locks.  Real logout,
            which uses the same User -> AuthSession order, must block; the
            effect commits first and logout then revokes the authority.
            """

            original_effect_lock = login_service.lock_presented_session_for_effect

            lifecycle_lock_entered = Event()
            lifecycle_backend: dict[str, object] = {}
            lifecycle_waiting_label = f"nyay5:{label}:effect-wait"
            lifecycle_blocker_label = f"nyay5:{label}:lifecycle-first"

            def observe_lifecycle_first(*args, **kwargs):
                if kwargs.get("expected_user_id") == lifecycle_first_actor["user_id"]:
                    lifecycle_backend["waiting_pid"] = identify_postgres_backend(
                        args[0], lifecycle_waiting_label
                    )
                    lifecycle_lock_entered.set()
                return original_effect_lock(*args, **kwargs)

            lifecycle_before = lifecycle_first_snapshot()
            lifecycle_response = None
            lifecycle_entered = False
            lifecycle_blocked = False
            lifecycle_session = factory()
            login_service.lock_presented_session_for_effect = observe_lifecycle_first
            try:
                lifecycle_blocker_pid = identify_postgres_backend(
                    lifecycle_session, lifecycle_blocker_label
                )
                locked_session = lifecycle_session.scalar(
                    select(AuthSession)
                    .where(
                        AuthSession.id == lifecycle_first_actor["session_id"],
                        AuthSession.token_hash
                        == keyed_hash(str(lifecycle_first_actor["token"])),
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if locked_session is None:
                    raise ProductGateFailure(
                        f"{label} lifecycle-first session setup failed"
                    )
                with ThreadPoolExecutor(max_workers=1) as executor:
                    lifecycle_first_future = executor.submit(
                        lifecycle_first_effect
                    )
                    lifecycle_entered = lifecycle_lock_entered.wait(timeout=10)
                    lifecycle_native_wait = bool(
                        lifecycle_entered
                        and isinstance(
                            lifecycle_backend.get("waiting_pid"), int
                        )
                        and postgres_lock_wait_observed(
                            waiting_pid=lifecycle_backend["waiting_pid"],
                            waiting_label=lifecycle_waiting_label,
                            blocker_pid=lifecycle_blocker_pid,
                            blocker_label=lifecycle_blocker_label,
                            timeout_seconds=lock_wait_timeout_seconds,
                        )
                    )
                    lifecycle_blocked = bool(
                        lifecycle_native_wait
                        and not lifecycle_first_future.done()
                    )
                    locked_session.status = "revoked"
                    locked_session.revoked_at = fixed_now + timedelta(minutes=10)
                    lifecycle_session.commit()
                    lifecycle_response = lifecycle_first_future.result(timeout=10)
            finally:
                lifecycle_session.rollback()
                lifecycle_session.close()
                login_service.lock_presented_session_for_effect = original_effect_lock

            lifecycle_after = lifecycle_first_snapshot()
            lifecycle_first_passed = bool(
                lifecycle_entered
                and lifecycle_native_wait
                and lifecycle_blocked
                and lifecycle_response is not None
                and getattr(lifecycle_response, "status_code", None) == 401
                and effect_error_code(lifecycle_response) == lifecycle_first_error
                and lifecycle_after == lifecycle_before
                and session_status(lifecycle_first_actor) == "revoked"
            )

            mutation_lock_acquired = Event()
            mutation_lock_release = Event()
            logout_entered = Event()
            original_logout = login_service.logout
            mutation_backend: dict[str, object] = {}
            mutation_blocker_label = f"nyay5:{label}:effect-first"
            mutation_waiting_label = f"nyay5:{label}:logout-wait"

            def hold_mutation_first(*args, **kwargs):
                if kwargs.get("expected_user_id") == mutation_first_actor["user_id"]:
                    mutation_backend["blocker_pid"] = identify_postgres_backend(
                        args[0], mutation_blocker_label
                    )
                row = original_effect_lock(*args, **kwargs)
                if kwargs.get("expected_user_id") == mutation_first_actor["user_id"]:
                    mutation_lock_acquired.set()
                    if not mutation_lock_release.wait(timeout=10):
                        raise ProductGateFailure(
                            f"{label} mutation-first synchronization failed"
                        )
                return row

            def observe_logout(*args, **kwargs):
                mutation_backend["waiting_pid"] = identify_postgres_backend(
                    args[0], mutation_waiting_label
                )
                logout_entered.set()
                return original_logout(*args, **kwargs)

            mutation_before = mutation_first_snapshot()
            mutation_response = None
            mutation_logout_response = None
            mutation_entered = False
            mutation_logout_entered = False
            mutation_logout_blocked = False
            login_service.lock_presented_session_for_effect = hold_mutation_first
            login_service.logout = observe_logout
            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    mutation_first_future = executor.submit(
                        mutation_first_effect
                    )
                    mutation_entered = mutation_lock_acquired.wait(timeout=10)
                    mutation_first_logout = executor.submit(
                        lambda: client_for(mutation_first_actor).post(
                            "/api/v1/auth/student/logout", json={}
                        )
                    )
                    mutation_logout_entered = logout_entered.wait(timeout=10)
                    mutation_native_wait = bool(
                        mutation_entered
                        and mutation_logout_entered
                        and isinstance(
                            mutation_backend.get("waiting_pid"), int
                        )
                        and isinstance(
                            mutation_backend.get("blocker_pid"), int
                        )
                        and postgres_lock_wait_observed(
                            waiting_pid=mutation_backend["waiting_pid"],
                            waiting_label=mutation_waiting_label,
                            blocker_pid=mutation_backend["blocker_pid"],
                            blocker_label=mutation_blocker_label,
                            timeout_seconds=lock_wait_timeout_seconds,
                        )
                    )
                    mutation_logout_blocked = bool(
                        mutation_native_wait
                        and not mutation_first_logout.done()
                    )
                    mutation_lock_release.set()
                    mutation_response = mutation_first_future.result(timeout=10)
                    mutation_logout_response = mutation_first_logout.result(timeout=10)
            finally:
                mutation_lock_release.set()
                login_service.lock_presented_session_for_effect = original_effect_lock
                login_service.logout = original_logout

            mutation_after = mutation_first_snapshot()
            return bool(
                lifecycle_first_passed
                and mutation_entered
                and mutation_logout_entered
                and mutation_native_wait
                and mutation_logout_blocked
                and mutation_response is not None
                and mutation_logout_response is not None
                and getattr(mutation_response, "status_code", None) == 200
                and mutation_first_changed(
                    mutation_before, mutation_after, mutation_response
                )
                and mutation_logout_response.status_code == 200
                and mutation_logout_response.json() == {"status": "logged_out"}
                and session_status(mutation_first_actor) == "revoked"
            )

        m01_complete_path = "/api/v1/tutoring/sessions/{}/complete"

        def seed_m01_target(label: str) -> uuid.UUID:
            """Create a real, ended tutoring session with no completion effects."""

            with factory.begin() as session:
                student_user = User(role="student", status="active")
                tutor_user = User(role="lawyer", status="active")
                session.add_all([student_user, tutor_user])
                session.flush()
                tutor = TutorProfile(
                    user_id=tutor_user.id,
                    display_name=f"Synthetic M01 {label}",
                    headline="Synthetic gate target",
                    experience_years=1,
                    verified_identity=True,
                    verified_credentials=True,
                    status="active",
                )
                session.add(tutor)
                session.flush()
                slot = TutorAvailabilitySlot(
                    tutor_id=tutor.id,
                    start_utc=fixed_now - timedelta(hours=2),
                    end_utc=fixed_now - timedelta(hours=1),
                    iana_timezone="Asia/Kolkata",
                    status="booked",
                )
                session.add(slot)
                session.flush()
                tutoring_session = TutoringSession(
                    slot_id=slot.id,
                    tutor_id=tutor.id,
                    student_user_id=student_user.id,
                    order_id=None,
                    start_utc=slot.start_utc,
                    end_utc=slot.end_utc,
                    iana_timezone=slot.iana_timezone,
                    status="confirmed",
                    version=1,
                )
                session.add(tutoring_session)
                session.flush()
                return tutoring_session.id

        def m01_effect_snapshot(
            tutoring_session_id: uuid.UUID,
            admin_actor: Mapping[str, object],
        ) -> dict[str, object]:
            """Exact M-01 domain/effect graph, excluding the raced auth row."""

            with factory() as session:
                tutoring_session = session.get(
                    TutoringSession, tutoring_session_id
                )
                attendance_rows = list(
                    session.scalars(
                        select(SessionAttendance)
                        .where(
                            SessionAttendance.session_id == tutoring_session_id
                        )
                        .order_by(SessionAttendance.id)
                    )
                )
                history_rows = list(
                    session.scalars(
                        select(SessionStatusHistory)
                        .where(
                            SessionStatusHistory.session_id
                            == tutoring_session_id
                        )
                        .order_by(SessionStatusHistory.id)
                    )
                )
                booking_rows = list(
                    session.scalars(
                        select(BookingEvent)
                        .where(BookingEvent.session_id == tutoring_session_id)
                        .order_by(BookingEvent.id)
                    )
                )
                audit_rows = list(
                    session.scalars(
                        select(AuditEvent)
                        .where(
                            AuditEvent.actor_user_id == admin_actor["user_id"],
                            AuditEvent.action
                            == "tutoring.attendance.recorded",
                        )
                        .order_by(AuditEvent.id)
                    )
                )
                outbox_rows = list(
                    session.scalars(
                        select(TutoringOutbox)
                        .where(
                            TutoringOutbox.aggregate_id == tutoring_session_id,
                            TutoringOutbox.kind == "attendance_recorded",
                        )
                        .order_by(TutoringOutbox.id)
                    )
                )
                return {
                    "session": (
                        None
                        if tutoring_session is None
                        else {
                            "status": tutoring_session.status,
                            "version": tutoring_session.version,
                        }
                    ),
                    "attendance": [
                        {
                            "state": row.state,
                            "version": row.version,
                            "recorded_by_role": row.recorded_by_role,
                            "recorded_at_exact": row.recorded_at == fixed_now,
                            "confirmed_at": row.confirmed_at,
                            "disputed_at": row.disputed_at,
                            "resolved_at": row.resolved_at,
                            "resolution": row.resolution,
                        }
                        for row in attendance_rows
                    ],
                    "history": [
                        {
                            "from_status": row.from_status,
                            "to_status": row.to_status,
                            "actor_role": row.actor_role,
                            "reason": row.reason,
                            "at_exact": row.at == fixed_now,
                        }
                        for row in history_rows
                    ],
                    "booking_events": [
                        {
                            "kind": row.kind,
                            "actor_role": row.actor_role,
                            "payload": row.payload_json,
                            "at_exact": row.at == fixed_now,
                        }
                        for row in booking_rows
                    ],
                    "audit": [
                        {
                            "actor_role": row.actor_role,
                            "action": row.action,
                            "resource_type": row.resource_type,
                            "resource_id_present": row.resource_id is not None,
                            "before_state": row.before_state,
                            "after_state": row.after_state,
                        }
                        for row in audit_rows
                    ],
                    "outbox": [
                        {
                            "kind": row.kind,
                            "aggregate_id": str(row.aggregate_id),
                            "payload": row.payload_json,
                            "status": row.status,
                            "attempts": row.attempts,
                            "last_error": row.last_error,
                            "delivered": row.delivered_at is not None,
                        }
                        for row in outbox_rows
                    ],
                }

        def m01_empty_snapshot() -> dict[str, object]:
            return {
                "session": {"status": "confirmed", "version": 1},
                "attendance": [],
                "history": [],
                "booking_events": [],
                "audit": [],
                "outbox": [],
            }

        def m01_completion_changed(
            before: object,
            after: object,
            response: object,
            *,
            tutoring_session_id: uuid.UUID,
        ) -> bool:
            expected_after = {
                "session": {"status": "completed", "version": 2},
                "attendance": [
                    {
                        "state": "recorded",
                        "version": 1,
                        "recorded_by_role": "admin",
                        "recorded_at_exact": True,
                        "confirmed_at": None,
                        "disputed_at": None,
                        "resolved_at": None,
                        "resolution": None,
                    }
                ],
                "history": [
                    {
                        "from_status": "confirmed",
                        "to_status": "completed",
                        "actor_role": "admin",
                        "reason": "attendance_recorded",
                        "at_exact": True,
                    }
                ],
                "booking_events": [
                    {
                        "kind": "session_completed",
                        "actor_role": "admin",
                        "payload": {"recorded_by_role": "admin"},
                        "at_exact": True,
                    }
                ],
                "audit": [
                    {
                        "actor_role": "admin",
                        "action": "tutoring.attendance.recorded",
                        "resource_type": "session_attendance",
                        "resource_id_present": True,
                        "before_state": None,
                        "after_state": {
                            "session_id": str(tutoring_session_id),
                            "state": "recorded",
                            "recorded_by_role": "admin",
                        },
                    }
                ],
                "outbox": [
                    {
                        "kind": "attendance_recorded",
                        "aggregate_id": str(tutoring_session_id),
                        "payload": {
                            "session_id": str(tutoring_session_id),
                            "state": "recorded",
                            "recorded_by_role": "admin",
                        },
                        "status": "sent",
                        "attempts": 1,
                        "last_error": None,
                        "delivered": True,
                    }
                ],
            }
            expected_response = {
                "session_id": str(tutoring_session_id),
                "state": "recorded",
                "version": 1,
                "recorded_by_role": "admin",
                "recorded_at": fixed_now.isoformat(),
                "confirmed_at": None,
                "disputed_at": None,
                "resolved_at": None,
                "resolution": None,
                "session_status": "completed",
            }
            return bool(
                before == m01_empty_snapshot()
                and after == expected_after
                and hasattr(response, "json")
                and response.json() == expected_response
            )

        m01_lifecycle_actor = seed_actor(
            "m01-completion-lifecycle-first", user_role="admin"
        )
        m01_lifecycle_target = seed_m01_target(
            "m01-completion-lifecycle-first"
        )
        m01_mutation_actor = seed_actor(
            "m01-completion-mutation-first", user_role="admin"
        )
        m01_mutation_target = seed_m01_target(
            "m01-completion-mutation-first"
        )
        m01_targets_start_empty = bool(
            m01_effect_snapshot(
                m01_lifecycle_target, m01_lifecycle_actor
            )
            == m01_empty_snapshot()
            and m01_effect_snapshot(
                m01_mutation_target, m01_mutation_actor
            )
            == m01_empty_snapshot()
        )
        m01_real_race_passed = bool(
            m01_targets_start_empty
            and run_effect_lifecycle_race(
                "m01-completion",
                lifecycle_first_actor=m01_lifecycle_actor,
                lifecycle_first_effect=lambda: client_for(
                    m01_lifecycle_actor
                ).post(m01_complete_path.format(m01_lifecycle_target)),
                lifecycle_first_snapshot=lambda: m01_effect_snapshot(
                    m01_lifecycle_target, m01_lifecycle_actor
                ),
                lifecycle_first_error="session_authority_required",
                mutation_first_actor=m01_mutation_actor,
                mutation_first_effect=lambda: client_for(
                    m01_mutation_actor
                ).post(m01_complete_path.format(m01_mutation_target)),
                mutation_first_snapshot=lambda: m01_effect_snapshot(
                    m01_mutation_target, m01_mutation_actor
                ),
                mutation_first_changed=lambda before, after, response: (
                    m01_completion_changed(
                        before,
                        after,
                        response,
                        tutoring_session_id=m01_mutation_target,
                    )
                ),
            )
        )

        def bypass_m01_effect_lock(
            session: object,
            raw_token: str | None,
            *,
            expected_user_id: uuid.UUID,
            now: datetime,
            allowed_roles: frozenset[str],
        ) -> object | None:
            """Named mutant: repeat authority checks without the row lock."""

            if not raw_token:
                return None
            token_hash = keyed_hash(raw_token)
            auth_session = session.scalar(
                select(AuthSession)
                .where(
                    AuthSession.user_id == expected_user_id,
                    AuthSession.token_hash == token_hash,
                )
                .execution_options(populate_existing=True)
            )
            expires_at = (
                auth_session.expires_at
                if auth_session is not None
                else None
            )
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if (
                auth_session is None
                or auth_session.status != "active"
                or auth_session.deleted_at is not None
                or expires_at is None
                or expires_at <= now
            ):
                return None
            user = session.get(User, expected_user_id)
            if (
                user is None
                or user.status != "active"
                or user.role not in allowed_roles
            ):
                return None
            return auth_session

        m01_mutant_lifecycle_actor = seed_actor(
            "m01-mutant-lifecycle-first", user_role="admin"
        )
        m01_mutant_lifecycle_target = seed_m01_target(
            "m01-mutant-lifecycle-first"
        )
        m01_mutant_effect_actor = seed_actor(
            "m01-mutant-effect-first", user_role="admin"
        )
        m01_mutant_effect_target = seed_m01_target(
            "m01-mutant-effect-first"
        )
        original_m01_effect_lock = (
            login_service.lock_presented_session_for_effect
        )
        try:
            login_service.lock_presented_session_for_effect = (
                bypass_m01_effect_lock
            )
            m01_bypass_mutant_survived = run_effect_lifecycle_race(
                "m01-bypass-mutant",
                lifecycle_first_actor=m01_mutant_lifecycle_actor,
                lifecycle_first_effect=lambda: client_for(
                    m01_mutant_lifecycle_actor
                ).post(
                    m01_complete_path.format(m01_mutant_lifecycle_target)
                ),
                lifecycle_first_snapshot=lambda: m01_effect_snapshot(
                    m01_mutant_lifecycle_target,
                    m01_mutant_lifecycle_actor,
                ),
                lifecycle_first_error="session_authority_required",
                mutation_first_actor=m01_mutant_effect_actor,
                mutation_first_effect=lambda: client_for(
                    m01_mutant_effect_actor
                ).post(m01_complete_path.format(m01_mutant_effect_target)),
                mutation_first_snapshot=lambda: m01_effect_snapshot(
                    m01_mutant_effect_target, m01_mutant_effect_actor
                ),
                mutation_first_changed=lambda before, after, response: (
                    m01_completion_changed(
                        before,
                        after,
                        response,
                        tutoring_session_id=m01_mutant_effect_target,
                    )
                ),
                lock_wait_timeout_seconds=0.25,
            )
        finally:
            login_service.lock_presented_session_for_effect = (
                original_m01_effect_lock
            )
        m01_bypass_mutant_killed = not m01_bypass_mutant_survived
        observations["m01_completion_session_lifecycle_serialized"] = bool(
            m01_real_race_passed and m01_bypass_mutant_killed
        )

        def profile_effect_snapshot(actor: Mapping[str, object]) -> tuple[object, ...]:
            with factory() as session:
                profile = session.get(StudentProfile, actor["profile_id"])
                audit_count = int(
                    session.scalar(
                        select(func.count(AuditEvent.id)).where(
                            AuditEvent.actor_user_id == actor["user_id"],
                            AuditEvent.action == "student.profile.section_updated",
                        )
                    )
                    or 0
                )
                return (
                    profile.profile_version if profile is not None else None,
                    profile.city if profile is not None else None,
                    audit_count,
                )

        profile_lifecycle_actor = seed_actor("profile-session-lifecycle-first")
        profile_mutation_actor = seed_actor("profile-session-mutation-first")
        observations["profile_session_lifecycle_serialized"] = (
            run_effect_lifecycle_race(
                "profile-personal",
                lifecycle_first_actor=profile_lifecycle_actor,
                lifecycle_first_effect=lambda: client_for(
                    profile_lifecycle_actor
                ).patch(
                    "/api/v1/student/profile/personal",
                    json=personal(1, city="Kolkata"),
                ),
                lifecycle_first_snapshot=lambda: profile_effect_snapshot(
                    profile_lifecycle_actor
                ),
                lifecycle_first_error="session_authority_required",
                mutation_first_actor=profile_mutation_actor,
                mutation_first_effect=lambda: client_for(
                    profile_mutation_actor
                ).patch(
                    "/api/v1/student/profile/personal",
                    json=personal(1, city="Kolkata"),
                ),
                mutation_first_snapshot=lambda: profile_effect_snapshot(
                    profile_mutation_actor
                ),
                mutation_first_changed=lambda before, after, response: bool(
                    before[0] == 1
                    and after[0] == 2
                    and after[1] == "Kolkata"
                    and after[2] == before[2] + 1
                    and response.json().get("profile_version") == 2
                ),
            )
        )

        def seed_reviewer_target(label: str) -> dict[str, object]:
            actor = seed_actor(label)
            client = client_for(actor)
            responses = (
                client.patch(
                    "/api/v1/student/profile/personal", json=personal(1)
                ),
                client.patch(
                    "/api/v1/student/profile/academic",
                    json={
                        "expected_profile_version": 2,
                        "college": "National Law School of India University",
                        "year_of_study": "4th",
                        "enrolment_number": "QA/51/2026",
                        "institutional_email": f"{label}@synthetic.edu",
                        "bar_enrolment_number": None,
                    },
                ),
            )
            request_response = client.post(
                "/api/v1/auth/student/verification/email/request", json={}
            )
            if [response.status_code for response in responses] != [200, 200] or (
                request_response.status_code != 202
            ):
                raise ProductGateFailure("reviewer session race target setup failed")
            return actor

        def reviewer_effect_snapshot(
            target: Mapping[str, object], reviewer_actor: Mapping[str, object]
        ) -> tuple[object, ...]:
            with factory() as session:
                verification = session.scalar(
                    select(StudentVerification).where(
                        StudentVerification.registration_id
                        == target["registration_id"]
                    )
                )
                audit_count = int(
                    session.scalar(
                        select(func.count(AuditEvent.id)).where(
                            AuditEvent.actor_user_id == reviewer_actor["user_id"],
                            AuditEvent.action
                            == "student.verification.status_changed",
                        )
                    )
                    or 0
                )
                return (
                    verification.status if verification is not None else None,
                    bool(
                        verification is not None
                        and verification.verified_email_hash is not None
                    ),
                    audit_count,
                )

        reviewer_lifecycle_actor = seed_actor(
            "reviewer-session-lifecycle-first", user_role="legal_reviewer"
        )
        reviewer_lifecycle_target = seed_reviewer_target(
            "reviewer-lifecycle-target"
        )
        reviewer_mutation_actor = seed_actor(
            "reviewer-session-mutation-first", user_role="legal_reviewer"
        )
        reviewer_mutation_target = seed_reviewer_target(
            "reviewer-mutation-target"
        )

        def reviewer_effect(
            reviewer_actor: Mapping[str, object], target: Mapping[str, object]
        ):
            return client_for(reviewer_actor).post(
                "/api/v1/auth/student/verification/status",
                json={
                    "registration_id": str(target["registration_id"]),
                    "status": "verified",
                    "expected_profile_version": 3,
                },
            )

        observations["reviewer_session_lifecycle_serialized"] = (
            run_effect_lifecycle_race(
                "reviewer-verification",
                lifecycle_first_actor=reviewer_lifecycle_actor,
                lifecycle_first_effect=lambda: reviewer_effect(
                    reviewer_lifecycle_actor, reviewer_lifecycle_target
                ),
                lifecycle_first_snapshot=lambda: reviewer_effect_snapshot(
                    reviewer_lifecycle_target, reviewer_lifecycle_actor
                ),
                lifecycle_first_error="authentication_required",
                mutation_first_actor=reviewer_mutation_actor,
                mutation_first_effect=lambda: reviewer_effect(
                    reviewer_mutation_actor, reviewer_mutation_target
                ),
                mutation_first_snapshot=lambda: reviewer_effect_snapshot(
                    reviewer_mutation_target, reviewer_mutation_actor
                ),
                mutation_first_changed=lambda before, after, response: bool(
                    before[0] == "in_review"
                    and before[1] is False
                    and after[0] == "verified"
                    and after[1] is True
                    and after[2] == before[2] + 1
                    and response.json()
                    == {
                        "status": "verified",
                        "profile_version": 3,
                        "owner_projection_invalidated": True,
                    }
                ),
            )
        )

        def share_effect_snapshot(actor: Mapping[str, object]) -> tuple[int, int]:
            with factory() as session:
                return (
                    int(
                        session.scalar(
                            select(func.count(CredentialShareProjection.id)).where(
                                CredentialShareProjection.owner_user_id
                                == actor["user_id"]
                            )
                        )
                        or 0
                    ),
                    int(
                        session.scalar(
                            select(func.count(AuditEvent.id)).where(
                                AuditEvent.actor_user_id == actor["user_id"],
                                AuditEvent.action
                                == "credential.share_projection_created",
                            )
                        )
                        or 0
                    ),
                )

        share_lifecycle_actor, _, share_lifecycle_credential, _ = (
            seed_credential_race(
                "share-session-lifecycle-first", with_projection=False
            )
        )
        share_mutation_actor, _, share_mutation_credential, _ = (
            seed_credential_race(
                "share-session-mutation-first", with_projection=False
            )
        )

        def create_race_projection(
            actor: Mapping[str, object], credential_id: object, idempotency: str
        ):
            return client_for(actor).post(
                f"/api/v1/credentials/{credential_id}/share-projections",
                headers={"Idempotency-Key": idempotency},
                json={"fields": ["title"]},
            )

        observations["share_session_lifecycle_serialized"] = (
            run_effect_lifecycle_race(
                "share-projection",
                lifecycle_first_actor=share_lifecycle_actor,
                lifecycle_first_effect=lambda: create_race_projection(
                    share_lifecycle_actor,
                    share_lifecycle_credential,
                    "nyay5-share-session-lifecycle-first",
                ),
                lifecycle_first_snapshot=lambda: share_effect_snapshot(
                    share_lifecycle_actor
                ),
                lifecycle_first_error="authentication_required",
                mutation_first_actor=share_mutation_actor,
                mutation_first_effect=lambda: create_race_projection(
                    share_mutation_actor,
                    share_mutation_credential,
                    "nyay5-share-session-mutation-first",
                ),
                mutation_first_snapshot=lambda: share_effect_snapshot(
                    share_mutation_actor
                ),
                mutation_first_changed=lambda before, after, response: bool(
                    after == (before[0] + 1, before[1] + 1)
                    and response.json().get("credential_id")
                    == str(share_mutation_credential)
                    and response.json().get("fields") == ["title"]
                    and response.json().get("active") is True
                ),
            )
        )

        def token_effect_snapshot(actor: Mapping[str, object]) -> tuple[int, int]:
            with factory() as session:
                return (
                    int(
                        session.scalar(
                            select(func.count(VerificationToken.id)).where(
                                VerificationToken.owner_user_id == actor["user_id"]
                            )
                        )
                        or 0
                    ),
                    int(
                        session.scalar(
                            select(func.count(AuditEvent.id)).where(
                                AuditEvent.actor_user_id == actor["user_id"],
                                AuditEvent.action
                                == "credential.verification_token_created",
                            )
                        )
                        or 0
                    ),
                )

        (
            token_lifecycle_actor,
            _,
            token_lifecycle_credential,
            token_lifecycle_projection,
        ) = seed_credential_race(
            "token-session-lifecycle-first", with_projection=True
        )
        (
            token_mutation_actor,
            _,
            token_mutation_credential,
            token_mutation_projection,
        ) = seed_credential_race(
            "token-session-mutation-first", with_projection=True
        )

        def create_race_token(
            actor: Mapping[str, object],
            credential_id: object,
            projection_id: object,
            idempotency: str,
        ):
            return client_for(actor).post(
                f"/api/v1/credentials/{credential_id}/verification-tokens",
                headers={"Idempotency-Key": idempotency},
                json={"projection_id": projection_id, "lifetime_days": 1},
            )

        observations["token_session_lifecycle_serialized"] = (
            run_effect_lifecycle_race(
                "verification-token",
                lifecycle_first_actor=token_lifecycle_actor,
                lifecycle_first_effect=lambda: create_race_token(
                    token_lifecycle_actor,
                    token_lifecycle_credential,
                    token_lifecycle_projection,
                    "nyay5-token-session-lifecycle-first",
                ),
                lifecycle_first_snapshot=lambda: token_effect_snapshot(
                    token_lifecycle_actor
                ),
                lifecycle_first_error="authentication_required",
                mutation_first_actor=token_mutation_actor,
                mutation_first_effect=lambda: create_race_token(
                    token_mutation_actor,
                    token_mutation_credential,
                    token_mutation_projection,
                    "nyay5-token-session-mutation-first",
                ),
                mutation_first_snapshot=lambda: token_effect_snapshot(
                    token_mutation_actor
                ),
                mutation_first_changed=lambda before, after, response: bool(
                    after == (before[0] + 1, before[1] + 1)
                    and response.json().get("idempotent_replay") is False
                    and isinstance(response.json().get("token"), str)
                    and isinstance(response.json().get("verification_url"), str)
                ),
            )
        )

        rotation_actor = seed_actor("login-rotation-overlap")
        original_rotation_effect_lock = (
            login_service.lock_presented_session_for_effect
        )
        rotation_mutation_entered = Event()
        rotation_mutation_release = Event()
        rotation_attempt_entered = Event()

        def hold_rotation_overlap(*args, **kwargs):
            row = original_rotation_effect_lock(*args, **kwargs)
            if kwargs.get("expected_user_id") == rotation_actor["user_id"]:
                rotation_mutation_entered.set()
                if not rotation_mutation_release.wait(timeout=10):
                    raise ProductGateFailure("login rotation synchronization failed")
            return row

        def rotate_during_mutation() -> tuple[str, object]:
            rotation_attempt_entered.set()
            with factory() as session:
                registration = session.scalar(
                    select(StudentRegistration)
                    .where(
                        StudentRegistration.id == rotation_actor["registration_id"]
                    )
                    .with_for_update()
                )
                if registration is None:
                    raise ProductGateFailure("login rotation actor missing")
                token, auth_session = login_service.rotate_authenticated_session(
                    session,
                    registration,
                    fixed_now + timedelta(minutes=20),
                )
                return token, auth_session.id

        rotation_response = None
        rotated_token = None
        rotated_session_id = None
        rotation_entered = False
        rotation_attempted = False
        rotation_blocked = False
        login_service.lock_presented_session_for_effect = hold_rotation_overlap
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                rotation_mutation_future = executor.submit(
                    lambda: client_for(rotation_actor).patch(
                        "/api/v1/student/profile/personal",
                        json=personal(1, city="Jaipur"),
                    )
                )
                rotation_entered = rotation_mutation_entered.wait(timeout=10)
                rotation_future = executor.submit(rotate_during_mutation)
                rotation_attempted = rotation_attempt_entered.wait(timeout=10)
                rotation_blocked = bool(
                    rotation_entered
                    and rotation_attempted
                    and not rotation_future.done()
                )
                rotation_mutation_release.set()
                rotation_response = rotation_mutation_future.result(timeout=10)
                rotated_token, rotated_session_id = rotation_future.result(timeout=10)
        finally:
            rotation_mutation_release.set()
            login_service.lock_presented_session_for_effect = (
                original_rotation_effect_lock
            )
        with factory() as session:
            old_rotation_session = session.get(
                AuthSession, rotation_actor["session_id"]
            )
            new_rotation_session = session.get(AuthSession, rotated_session_id)
            active_rotation_sessions = int(
                session.scalar(
                    select(func.count(AuthSession.id)).where(
                        AuthSession.user_id == rotation_actor["user_id"],
                        AuthSession.status == "active",
                    )
                )
                or 0
            )
        rotated_projection = (
            client_for(
                {
                    **rotation_actor,
                    "token": rotated_token,
                    "session_id": rotated_session_id,
                }
            ).get("/api/v1/student/profile")
            if rotated_token is not None and rotated_session_id is not None
            else None
        )
        observations["login_rotation_no_deadlock"] = bool(
            rotation_entered
            and rotation_attempted
            and rotation_blocked
            and rotation_response is not None
            and rotation_response.status_code == 200
            and rotation_response.json().get("profile_version") == 2
            and old_rotation_session is not None
            and old_rotation_session.status == "revoked"
            and new_rotation_session is not None
            and new_rotation_session.status == "active"
            and active_rotation_sessions == 1
            and rotated_projection is not None
            and rotated_projection.status_code == 200
            and rotated_projection.json().get("profile_version") == 2
        )

        def run_unique_loser_reauthentication(
            *,
            kind: str,
            actor: Mapping[str, object],
            invoke_loser: Callable[[], object],
            expected_constraint: str,
            table_marker: str,
            stale_discovery_fault: bool,
        ) -> bool:
            """Exercise the post-IntegrityError rollback reauthentication gap.

            Cookie effects now hold the exact User parent before AuthSession,
            and share/token additionally hold their registration/credential
            domain locks, so a same-owner database writer cannot overtake a
            live request without blocking.  The gate therefore precommits each
            real winner and hides exactly one initial idempotency discovery,
            then lets PostgreSQL raise the real named unique violation.  Every
            path performs a real rollback, revokes the exact session in that
            gap, and must reject recovery.
            """

            nonlocal unique_loser_controller
            original_session_scalar = Session.scalar
            original_session_rollback = Session.rollback
            original_constraint_name = credential_api.constraint_name
            unique_gap_entered = Event()
            unique_gap_release = Event()
            control: dict[str, object] = {
                "kind": kind,
                "table_marker": table_marker,
                "expected_constraint": expected_constraint,
                "stale_discovery_fault": stale_discovery_fault,
                "stale_discovery_hidden": False,
                "observed_constraint": None,
                "gap_recorded": False,
            }

            def fault_scalar(session, statement, *args, **kwargs):
                active = session.info.get("nyay5_unique_loser")
                statement_text = str(statement).casefold()
                if (
                    active is control
                    and stale_discovery_fault
                    and control["stale_discovery_hidden"] is False
                    and table_marker in statement_text
                    and "idempotency_key" in statement_text
                ):
                    control["stale_discovery_hidden"] = True
                    return None
                return original_session_scalar(session, statement, *args, **kwargs)

            def observe_constraint(exc):
                name = original_constraint_name(exc)
                if unique_loser_controller is control:
                    control["observed_constraint"] = name
                return name

            def hold_after_real_rollback(session):
                result = original_session_rollback(session)
                active = session.info.get("nyay5_unique_loser")
                if (
                    active is control
                    and control["gap_recorded"] is False
                    and control["observed_constraint"] == expected_constraint
                ):
                    control["gap_recorded"] = True
                    unique_gap_entered.set()
                    if not unique_gap_release.wait(timeout=10):
                        raise ProductGateFailure(
                            f"{kind} unique rollback-gap synchronization failed"
                        )
                return result

            unique_loser_controller = control
            Session.scalar = fault_scalar
            Session.rollback = hold_after_real_rollback
            credential_api.constraint_name = observe_constraint
            loser_response = None
            loser_gap_reached = False
            loser_blocked_in_gap = False
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    loser_future = executor.submit(invoke_loser)
                    loser_gap_reached = unique_gap_entered.wait(timeout=10)
                    loser_blocked_in_gap = bool(
                        loser_gap_reached and not loser_future.done()
                    )
                    if loser_gap_reached:
                        with factory.begin() as lifecycle_session:
                            presented = lifecycle_session.scalar(
                                select(AuthSession)
                                .where(
                                    AuthSession.id == actor["session_id"],
                                    AuthSession.token_hash
                                    == keyed_hash(str(actor["token"])),
                                )
                                .with_for_update()
                                .execution_options(populate_existing=True)
                            )
                            if presented is None:
                                raise ProductGateFailure(
                                    f"{kind} rollback-gap session missing"
                                )
                            presented.status = "revoked"
                            presented.revoked_at = fixed_now + timedelta(minutes=30)
                    unique_gap_release.set()
                    loser_response = loser_future.result(timeout=10)
            finally:
                unique_gap_release.set()
                credential_api.constraint_name = original_constraint_name
                Session.scalar = original_session_scalar
                Session.rollback = original_session_rollback
                unique_loser_controller = None

            stale_discovery_exact = bool(
                control["stale_discovery_hidden"] is stale_discovery_fault
            )
            return bool(
                loser_gap_reached
                and loser_blocked_in_gap
                and control["gap_recorded"] is True
                and control["observed_constraint"] == expected_constraint
                and stale_discovery_exact
                and loser_response is not None
                and getattr(loser_response, "status_code", None) == 401
                and effect_error_code(loser_response) == "authentication_required"
                and session_status(actor) == "revoked"
            )

        def credential_unique_snapshot(
            actor: Mapping[str, object], idempotency: str
        ) -> tuple[int, int, int, int, int]:
            with factory() as session:
                credential_ids = list(
                    session.scalars(
                        select(Credential.id).where(
                            Credential.owner_user_id == actor["user_id"],
                            Credential.idempotency_key == idempotency,
                        )
                    )
                )
                return (
                    len(credential_ids),
                    int(
                        session.scalar(
                            select(func.count(AuditEvent.id)).where(
                                AuditEvent.actor_user_id == actor["user_id"],
                                AuditEvent.action == "credential.created",
                            )
                        )
                        or 0
                    ),
                    int(
                        session.scalar(
                            select(func.count(CredentialStatusHistory.id)).where(
                                CredentialStatusHistory.actor_user_id
                                == actor["user_id"]
                            )
                        )
                        or 0
                    ),
                    int(
                        session.scalar(
                            select(func.count(CredentialReminderJob.id)).where(
                                CredentialReminderJob.credential_id.in_(credential_ids)
                            )
                        )
                        or 0
                    )
                    if credential_ids
                    else 0,
                    int(
                        session.scalar(
                            select(func.count(CredentialOutbox.id)).where(
                                CredentialOutbox.credential_id.in_(credential_ids)
                            )
                        )
                        or 0
                    )
                    if credential_ids
                    else 0,
                )

        credential_loser_actor = seed_actor("credential-unique-loser")
        credential_loser_key = "nyay5-credential-unique-loser"

        def insert_precommitted_credential_winner() -> None:
            with factory.begin() as session:
                session.add(
                    Credential(
                        owner_user_id=credential_loser_actor["user_id"],
                        issuer_id=None,
                        title="Synthetic concurrent winner",
                        credential_type="certificate",
                        status="self_declared",
                        issue_date=date(2026, 1, 1),
                        expiry_date=None,
                        identifier_hash=None,
                        identifier_ct=None,
                        key_version=None,
                        version=1,
                        idempotency_key=credential_loser_key,
                    )
                )

        insert_precommitted_credential_winner()
        credential_loser_gate = run_unique_loser_reauthentication(
            kind="credential-create",
            actor=credential_loser_actor,
            invoke_loser=lambda: client_for(credential_loser_actor).post(
                "/api/v1/credentials",
                headers={"Idempotency-Key": credential_loser_key},
                json={
                    "title": "Synthetic losing request",
                    "credential_type": "certificate",
                    "issue_date": "2026-01-01",
                    "expiry_date": None,
                    "issuer_id": None,
                    "identifier": None,
                },
            ),
            expected_constraint=credential_api._CREDENTIAL_IDEMPOTENCY_CONSTRAINT,
            table_marker="credentials",
            stale_discovery_fault=True,
        )
        observations["credential_unique_loser_reauthenticated"] = bool(
            credential_loser_gate
            and credential_unique_snapshot(
                credential_loser_actor, credential_loser_key
            )
            == (1, 0, 0, 0, 0)
        )

        def share_unique_snapshot(
            actor: Mapping[str, object], idempotency: str
        ) -> tuple[int, int]:
            with factory() as session:
                return (
                    int(
                        session.scalar(
                            select(func.count(CredentialShareProjection.id)).where(
                                CredentialShareProjection.owner_user_id
                                == actor["user_id"],
                                CredentialShareProjection.idempotency_key
                                == idempotency,
                            )
                        )
                        or 0
                    ),
                    int(
                        session.scalar(
                            select(func.count(AuditEvent.id)).where(
                                AuditEvent.actor_user_id == actor["user_id"],
                                AuditEvent.action
                                == "credential.share_projection_created",
                            )
                        )
                        or 0
                    ),
                )

        share_fault_actor, share_fault_client, share_fault_credential, _ = (
            seed_credential_race("share-unique-fault", with_projection=False)
        )
        share_fault_key = "nyay5-share-unique-fault"
        share_fault_winner = share_fault_client.post(
            f"/api/v1/credentials/{share_fault_credential}/share-projections",
            headers={"Idempotency-Key": share_fault_key},
            json={"fields": ["title"]},
        )
        share_fault_before = share_unique_snapshot(
            share_fault_actor, share_fault_key
        )
        share_fault_gate = run_unique_loser_reauthentication(
            kind="share-projection",
            actor=share_fault_actor,
            invoke_loser=lambda: client_for(share_fault_actor).post(
                f"/api/v1/credentials/{share_fault_credential}/share-projections",
                headers={"Idempotency-Key": share_fault_key},
                json={"fields": ["title"]},
            ),
            expected_constraint=credential_api._SHARE_IDEMPOTENCY_CONSTRAINT,
            table_marker="credential_share_projections",
            stale_discovery_fault=True,
        )
        observations["share_unique_fault_reauthenticated"] = bool(
            share_fault_winner.status_code == 200
            and share_fault_before == (1, 1)
            and share_fault_gate
            and share_unique_snapshot(share_fault_actor, share_fault_key)
            == share_fault_before
        )

        def token_unique_snapshot(
            actor: Mapping[str, object], idempotency: str
        ) -> tuple[int, int, bool]:
            with factory() as session:
                tokens = list(
                    session.scalars(
                        select(VerificationToken).where(
                            VerificationToken.owner_user_id == actor["user_id"],
                            VerificationToken.idempotency_key == idempotency,
                        )
                    )
                )
                audit_count = int(
                    session.scalar(
                        select(func.count(AuditEvent.id)).where(
                            AuditEvent.actor_user_id == actor["user_id"],
                            AuditEvent.action
                            == "credential.verification_token_created",
                        )
                    )
                    or 0
                )
                return (
                    len(tokens),
                    audit_count,
                    len(tokens) == 1 and tokens[0].revoked_at is None,
                )

        (
            token_fault_actor,
            token_fault_client,
            token_fault_credential,
            token_fault_projection,
        ) = seed_credential_race("token-unique-fault", with_projection=True)
        token_fault_key = "nyay5-token-unique-fault"
        token_fault_winner = token_fault_client.post(
            f"/api/v1/credentials/{token_fault_credential}/verification-tokens",
            headers={"Idempotency-Key": token_fault_key},
            json={
                "projection_id": token_fault_projection,
                "lifetime_days": 1,
            },
        )
        token_fault_before = token_unique_snapshot(
            token_fault_actor, token_fault_key
        )
        token_fault_gate = run_unique_loser_reauthentication(
            kind="verification-token",
            actor=token_fault_actor,
            invoke_loser=lambda: client_for(token_fault_actor).post(
                f"/api/v1/credentials/{token_fault_credential}/verification-tokens",
                headers={"Idempotency-Key": token_fault_key},
                json={
                    "projection_id": token_fault_projection,
                    "lifetime_days": 1,
                },
            ),
            expected_constraint=credential_api._TOKEN_HASH_CONSTRAINT,
            table_marker="verification_tokens",
            stale_discovery_fault=True,
        )
        token_recovery_source = pyinspect.getsource(
            credential_api.create_verification_token
        )
        token_recovery_constraints_exact = bool(
            "_TOKEN_IDEMPOTENCY_CONSTRAINT" in token_recovery_source
            and "_TOKEN_HASH_CONSTRAINT" in token_recovery_source
            and "if failed_constraint not in" in token_recovery_source
            and "keyed_hash(replay_raw) != replay.token_hash"
            in token_recovery_source
        )
        observations["token_unique_fault_reauthenticated"] = bool(
            token_fault_winner.status_code == 200
            and token_fault_before == (1, 1, True)
            and token_fault_gate
            and token_recovery_constraints_exact
            and token_unique_snapshot(token_fault_actor, token_fault_key)
            == token_fault_before
        )

        legacy_actor = seed_actor("legacy")
        legacy_client = client_for(legacy_actor)
        legacy_payload = {
            "expected_profile_version": 1,
            "college": "National Law School of India University",
            "year_of_study": "4th",
            "enrolment_number": "QA/43/2026",
            "institutional_email": "legacy@synthetic.edu",
            "bar_enrolment_number": None,
        }
        legacy_before = legacy_client.patch(
            "/api/v1/auth/student/profile", json=legacy_payload
        )
        legacy_personal = legacy_client.patch(
            "/api/v1/student/profile/personal", json=personal(1)
        )
        legacy_payload["expected_profile_version"] = 2
        legacy_after = legacy_client.patch(
            "/api/v1/auth/student/profile", json=legacy_payload
        )
        legacy_source = pyinspect.getsource(auth_student.update_academic_profile)
        observations["legacy_delegates_canonical"] = bool(
            legacy_before.status_code == 409
            and legacy_personal.status_code == 200
            and legacy_after.status_code == 200
            and legacy_after.json().get("profile_version") == 3
            and legacy_after.json().get("completed_sections")
            == ["personal", "academic"]
            and "profile_service.update_academic" in legacy_source
            and "expected_profile_version=payload.expected_profile_version" in legacy_source
        )

        with factory() as session:
            audit_events = list(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.action.in_(
                            [
                                "student.profile.section_updated",
                                "student.profile.prompt_dismissed",
                            ]
                        )
                    )
                )
            )
        private_markers = {
            str(owner["user_id"]),
            str(owner["registration_id"]),
            str(owner["profile_id"]),
            "National Law School of India University",
            "student@synthetic.edu",
            "Constitutional law",
            "Moot court",
            "2008-08-22",
        }
        audit_blob = json.dumps(
            [event.after_state for event in audit_events], sort_keys=True
        )
        observations["audit_privacy"] = bool(
            audit_events
            and all(event.resource_id is None for event in audit_events)
            and not any(marker in audit_blob for marker in private_markers)
            and all(
                set(event.after_state or {})
                <= {
                    "outcome", "section", "profile_version",
                    "guardian_required", "scope",
                }
                for event in audit_events
            )
        )
        return observations
    except Exception as exc:
        raise ProductGateFailure("NYAY-5 real behavior probe failed") from exc
    finally:
        try:
            settings.app_env = previous_env
            settings.cors_origins = previous_origins
            student_settings._now = previous_student_now
            auth_student._now = previous_auth_now
            attendance_service.utcnow = previous_attendance_now
            override_keyring(None)
            app.dependency_overrides.clear()
        except (AttributeError, NameError):
            pass
        engine.dispose()


def _seeded_mutant_results() -> dict[str, bool]:
    """Kill each named mutant through an actual input, fixture, or source seam.

    These mutations deliberately avoid flipping already-computed pass booleans.
    Each case changes the concrete datum consumed by the same kind of oracle as
    the native probe: a runtime version, URL, migration/model/function source,
    HTTP/state observation fixture, audit payload, or exact inventory.
    """

    from app.api.v1 import auth_student, student_settings
    from app.models.registration import StudentProfile, StudentRegistration
    from app.services import login_service, profile_service

    def actual_fixture_mutation(
        evaluator: Callable[[object], bool], baseline: object, mutant: object
    ) -> bool:
        return bool(
            baseline != mutant
            and evaluator(baseline)
            and not evaluator(mutant)
        )

    def source_mutant(source: str, exact: str, replacement: str) -> str:
        if source.count(exact) != 1:
            return source
        return source.replace(exact, replacement, 1)

    results: dict[str, bool] = {}

    runtime_fixture = {
        "server_version_num": 160015,
        "pgvector_version": "0.8.1",
    }

    def runtime_exact(value: object) -> bool:
        return bool(
            isinstance(value, Mapping)
            and _is_postgresql_16_with_pgvector(
                value.get("server_version_num"),
                value.get("pgvector_version"),
            )
        )

    results["ACCEPT-POSTGRES-15"] = actual_fixture_mutation(
        runtime_exact,
        runtime_fixture,
        {**runtime_fixture, "server_version_num": 150015},
    )
    results["ACCEPT-MISSING-PGVECTOR"] = actual_fixture_mutation(
        runtime_exact,
        runtime_fixture,
        {**runtime_fixture, "pgvector_version": None},
    )

    loopback_control = (
        "postgresql://postgres:synthetic@127.0.0.1:5432/postgres"
    )

    def control_url_accepted(value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            _safe_local_postgres_url(value)
        except Blocked:
            return False
        return True

    results["ACCEPT-NONLOOPBACK-CONTROL"] = actual_fixture_mutation(
        control_url_accepted,
        loopback_control,
        "postgresql://postgres:synthetic@database.internal:5432/postgres",
    )
    results["ACCEPT-QUERY-ROUTED-CONTROL"] = actual_fixture_mutation(
        control_url_accepted,
        loopback_control,
        f"{loopback_control}?host=database.internal",
    )

    head_source = PINNED_HEAD_PATH.read_text(encoding="utf-8")

    def revision_chain_exact(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and re.search(
                rf'^revision:\s*str\s*=\s*"{re.escape(PINNED_HEAD)}"$',
                value,
                re.MULTILINE,
            )
            and re.search(
                rf'^down_revision:\s*str\s*\|\s*None\s*=\s*"'
                rf'{re.escape(PREVIOUS_REVISION)}"$',
                value,
                re.MULTILINE,
            )
        )

    results["SKIP-0020-PARENT"] = actual_fixture_mutation(
        revision_chain_exact,
        head_source,
        source_mutant(
            head_source,
            f'down_revision: str | None = "{PREVIOUS_REVISION}"',
            'down_revision: str | None = "0019_registration_hardening"',
        ),
    )

    historical_path = sorted(
        (BACKEND / "app/db/migrations/versions").glob("0001_*.py")
    )[0]
    historical_bytes = historical_path.read_bytes()

    def historical_bytes_exact(value: object) -> bool:
        return bool(
            isinstance(value, bytes)
            and hashlib.sha256(value).digest()
            == hashlib.sha256(historical_bytes).digest()
        )

    results["REWRITE-HISTORICAL-MIGRATION"] = actual_fixture_mutation(
        historical_bytes_exact,
        historical_bytes,
        historical_bytes + b"\n# mutant historical rewrite\n",
    )

    application_head_bytes = PINNED_HEAD_PATH.read_bytes()

    def application_head_exact(value: object) -> bool:
        return bool(
            isinstance(value, bytes)
            and hashlib.sha256(value).hexdigest() == PINNED_HEAD_SHA256
        )

    results["REWRITE-APPLICATION-HEAD"] = actual_fixture_mutation(
        application_head_exact,
        application_head_bytes,
        application_head_bytes + b"\n# mutant application rewrite\n",
    )

    def single_head_exact(value: object) -> bool:
        return value == [PINNED_HEAD]

    results["ALLOW-MULTIPLE-ALEMBIC-HEADS"] = actual_fixture_mutation(
        single_head_exact,
        [PINNED_HEAD],
        [PINNED_HEAD, "0021_mutant_parallel_head"],
    )

    cas_source = pyinspect.getsource(profile_service._cas)
    cas_predicate = (
        "StudentProfile.profile_version == expected_profile_version"
    )

    def cas_source_exact(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and cas_predicate in value
            and ".returning(StudentProfile.profile_version)" in value
            and "session.rollback()" in value
        )

    results["DROP-PROFILE-VERSION-CAS"] = actual_fixture_mutation(
        cas_source_exact,
        cas_source,
        source_mutant(cas_source, cas_predicate, "StudentProfile.id.is_not(None)"),
    )

    registration_columns = set(StudentRegistration.__table__.columns.keys())
    profile_columns = set(StudentProfile.__table__.columns.keys())
    identity_columns = {
        "first_name",
        "middle_name",
        "last_name",
        "dob_hash",
        "dob_ct",
    }
    model_fixture = {
        "registration": registration_columns,
        "profile": profile_columns,
    }

    def identity_model_exact(value: object) -> bool:
        return bool(
            isinstance(value, Mapping)
            and identity_columns <= set(value.get("registration", set()))
            and not identity_columns.intersection(
                set(value.get("profile", set()))
            )
        )

    results["DUPLICATE-IDENTITY-COLUMNS"] = actual_fixture_mutation(
        identity_model_exact,
        model_fixture,
        {
            "registration": registration_columns,
            "profile": profile_columns | {"first_name"},
        },
    )

    owner_route_source = pyinspect.getsource(student_settings.get_profile)

    def owner_route_exact(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and "_require_empty_profile_query(request)" in value
            and "actor.user_id" in value
            and "registration_id" not in value
            and "profile_id" not in value
        )

    results["TRUST-CLIENT-OWNER-SELECTOR"] = actual_fixture_mutation(
        owner_route_exact,
        owner_route_source,
        source_mutant(
            owner_route_source,
            "_require_empty_profile_query(request)",
            "registration_id = request.query_params.get('registration_id')",
        ),
    )

    authority_source = pyinspect.getsource(profile_service.resolve_authority)
    owner_predicate = "StudentRegistration.user_id == actor_user_id"

    def authority_source_exact(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and owner_predicate in value
            and "limit(2)" in value
            and "len(registrations) != 1" in value
        )

    results["ALLOW-CROSS-USER-MUTATION"] = actual_fixture_mutation(
        authority_source_exact,
        authority_source,
        source_mutant(
            authority_source,
            owner_predicate,
            "StudentRegistration.user_id.is_not(None)",
        ),
    )

    def completion_fixture_exact(value: object) -> bool:
        if not isinstance(value, Mapping):
            return False
        completed = value.get("completed_sections")
        prefixes = {
            (): (0, "personal", False),
            ("personal",): (34, "academic", False),
            ("personal", "academic"): (67, "interests", False),
            ("personal", "academic", "interests"): (100, None, True),
        }
        expected = prefixes.get(tuple(completed) if isinstance(completed, list) else None)
        return bool(
            expected is not None
            and (
                value.get("completion_percent"),
                value.get("next_incomplete_section"),
                value.get("is_complete"),
            )
            == expected
        )

    empty_projection_fixture = {
        "completed_sections": [],
        "completion_percent": 0,
        "next_incomplete_section": "personal",
        "is_complete": False,
    }
    results["FABRICATE-67-PERCENT-NEW-USER"] = actual_fixture_mutation(
        completion_fixture_exact,
        empty_projection_fixture,
        {**empty_projection_fixture, "completion_percent": 67},
    )

    ordered_projection_fixture = {
        "completed_sections": ["personal"],
        "completion_percent": 34,
        "next_incomplete_section": "academic",
        "is_complete": False,
    }
    results["COMPLETE-SKIPPED-SECTION"] = actual_fixture_mutation(
        completion_fixture_exact,
        ordered_projection_fixture,
        {
            **ordered_projection_fixture,
            "completed_sections": ["personal", "interests"],
        },
    )

    verification_fixture = {
        "completed_sections": ["personal", "academic", "interests"],
        "completion_percent": 100,
        "next_incomplete_section": None,
        "is_complete": True,
        "institutional_email_status": "pending",
    }
    results["COUPLE-COMPLETION-TO-VERIFICATION"] = actual_fixture_mutation(
        completion_fixture_exact,
        verification_fixture,
        {**verification_fixture, "completion_percent": 67},
    )

    def concurrency_fixture_exact(value: object) -> bool:
        return bool(
            isinstance(value, Mapping)
            and sorted(value.get("response_statuses", [])) == [200, 409]
            and value.get("profile_version") == 2
            and value.get("audit_delta") == 1
        )

    concurrency_fixture = {
        "response_statuses": [200, 409],
        "profile_version": 2,
        "audit_delta": 1,
    }
    results["ALLOW-STALE-WRITE"] = actual_fixture_mutation(
        concurrency_fixture_exact,
        concurrency_fixture,
        {**concurrency_fixture, "response_statuses": [200, 200]},
    )

    def conflict_winner_exact(value: object) -> bool:
        return bool(
            isinstance(value, Mapping)
            and value.get("winner_city") == value.get("persisted_city")
            and value.get("profile_version") == 2
            and value.get("audit_delta") == 1
        )

    conflict_fixture = {
        "winner_city": "Pune",
        "persisted_city": "Pune",
        "profile_version": 2,
        "audit_delta": 1,
    }
    results["OVERWRITE-AFTER-CONFLICT"] = actual_fixture_mutation(
        conflict_winner_exact,
        conflict_fixture,
        {**conflict_fixture, "persisted_city": "Chennai"},
    )

    personal_source = pyinspect.getsource(profile_service.update_personal)

    def injected_clock_source_exact(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and "request_date = now.date()" in value
            and "date.today(" not in value
            and "datetime.now(" not in value
        )

    results["USE-PROCESS-DATE-FOR-AGE"] = actual_fixture_mutation(
        injected_clock_source_exact,
        personal_source,
        source_mutant(personal_source, "request_date = now.date()", "request_date = date.today()"),
    )

    def guardian_source_exact(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and 'guardian.status = "pending"' in value
            and "guardian.verified = False" in value
            and "registration.is_minor = new_minor" in value
        )

    results["NONATOMIC-GUARDIAN-RECOMPUTE"] = actual_fixture_mutation(
        guardian_source_exact,
        personal_source,
        source_mutant(
            personal_source,
            'guardian.status = "pending"',
            'guardian.status = "verified"',
        ),
    )

    def limited_sharing_fixture_exact(value: object) -> bool:
        return bool(
            isinstance(value, Mapping)
            and value.get("dob_status") == 200
            and value.get("access_mode") == "limited"
            and value.get("effect_status") == 403
            and value.get("detail_code") == "guardian_verification_required"
            and value.get("rows_before") == value.get("rows_after")
        )

    share_fixture = {
        "kind": "share_projection",
        "dob_status": 200,
        "access_mode": "limited",
        "effect_status": 403,
        "detail_code": "guardian_verification_required",
        "rows_before": 0,
        "rows_after": 0,
    }
    results["ALLOW-SHARE-AFTER-MINOR-COMMIT"] = actual_fixture_mutation(
        limited_sharing_fixture_exact,
        share_fixture,
        {
            **share_fixture,
            "effect_status": 200,
            "detail_code": None,
            "rows_after": 1,
        },
    )
    token_fixture = {**share_fixture, "kind": "verification_token"}
    results["ALLOW-TOKEN-AFTER-MINOR-COMMIT"] = actual_fixture_mutation(
        limited_sharing_fixture_exact,
        token_fixture,
        {
            **token_fixture,
            "effect_status": 200,
            "detail_code": None,
            "rows_after": 1,
        },
    )

    reviewer_source = pyinspect.getsource(auth_student.verification_transition)

    def reviewer_authority_exact(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and "Depends(_require_verification_reviewer)" in value
            and "lock_authority_for_review" in value
            and "owner_projection_invalidated" in value
        )

    results["ALLOW-STUDENT-SELF-VERIFICATION"] = actual_fixture_mutation(
        reviewer_authority_exact,
        reviewer_source,
        source_mutant(
            reviewer_source,
            "Depends(_require_verification_reviewer)",
            "Depends(_require_student)",
        ),
    )

    effect_lock_source = pyinspect.getsource(
        login_service.lock_presented_session_for_effect
    )
    user_parent_lock_source = pyinspect.getsource(
        login_service.lock_user_for_session_rotation
    )

    def exact_effect_session_lock_source(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and "user = lock_user_for_session_rotation(" in value
            and value.index("user = lock_user_for_session_rotation(")
            < value.index("auth_session = session.scalar(")
            and "AuthSession.token_hash == token_hash" in value
            and ".with_for_update()" in value
            and ".execution_options(populate_existing=True)" in value
            and 'auth_session.status != "active"' in value
            and "user.role not in allowed_roles" in value
            and "select(User)" in user_parent_lock_source
            and ".with_for_update()" in user_parent_lock_source
            and ".execution_options(populate_existing=True)"
            in user_parent_lock_source
        )

    results["BYPASS-M01-EXACT-EFFECT-SESSION-LOCK"] = (
        actual_fixture_mutation(
            exact_effect_session_lock_source,
            effect_lock_source,
            source_mutant(
                effect_lock_source,
                ".with_for_update()",
                "",
            ),
        )
    )

    rotation_source = pyinspect.getsource(login_service.rotate_authenticated_session)

    def rotation_prompt_scope_exact(value: object) -> bool:
        return bool(
            isinstance(value, str)
            and "clear_profile_prompts(session, [prior.id for prior in prior_sessions])"
            in value
            and 'prior.status = "revoked"' in value
        )

    results["PERSIST-PROMPT-DISMISSAL-ACROSS-SESSIONS"] = (
        actual_fixture_mutation(
            rotation_prompt_scope_exact,
            rotation_source,
            source_mutant(
                rotation_source,
                "clear_profile_prompts(session, [prior.id for prior in prior_sessions])",
                "pass  # mutant keeps old-session prompt rows",
            ),
        )
    )

    allowed_audit_keys = {
        "outcome",
        "section",
        "profile_version",
        "guardian_required",
        "scope",
    }
    audit_fixture = {
        "outcome": "succeeded",
        "section": "personal",
        "profile_version": 2,
        "guardian_required": False,
    }

    def aggregate_audit_exact(value: object) -> bool:
        return bool(
            isinstance(value, Mapping)
            and set(value) <= allowed_audit_keys
            and not _privacy_findings({"after_state": value})
        )

    results["AUDIT-CONTAINS-PROFILE-PII"] = actual_fixture_mutation(
        aggregate_audit_exact,
        audit_fixture,
        {**audit_fixture, "email": "student@synthetic.edu"},
    )

    scratch_fixture = _oracle_baselines()["scratch"]
    results["SCRATCH-CLEANUP-NOT-FINAL"] = actual_fixture_mutation(
        lambda value: bool(
            isinstance(value, Mapping) and _scratch_observation_passes(value)
        ),
        scratch_fixture,
        {**scratch_fixture, "removed": 3, "all_created_removed": False},
    )

    passing = [_assertion(identifier, True) for identifier in REQUIRED_ASSERTION_IDS]
    results["ASSERTION-INVENTORY-MISSING"] = bool(
        _evaluate_assertions(passing)["overall_pass"]
        and not _evaluate_assertions(passing[:-1])["overall_pass"]
    )
    results["ASSERTION-INVENTORY-REORDERED"] = bool(
        _evaluate_assertions(passing)["overall_pass"]
        and not _evaluate_assertions(list(reversed(passing)))["overall_pass"]
    )
    results["ASSERTION-INVENTORY-DUPLICATED"] = bool(
        _evaluate_assertions(passing)["overall_pass"]
        and not _evaluate_assertions([*passing, passing[-1]])["overall_pass"]
    )
    return results


def _seeded_mutants_are_killed() -> bool:
    results = _seeded_mutant_results()
    return tuple(results) == REQUIRED_MUTANT_IDS and all(results.values())


def _assemble_assertions(
    runtime: Mapping[str, object],
    migration: Mapping[str, object],
    populated: Mapping[str, object],
    behavior: Mapping[str, bool],
    cleanup: Mapping[str, object],
) -> list[dict[str, object]]:
    migration_observation = migration.get("migration", {})
    schema_observation = migration.get("schema", {})
    populated_observation = populated.get("observation", {})
    return [
        _assertion(
            "RUNTIME-POSTGRES-16-PGVECTOR",
            runtime.get("pass") is True,
            server_version_num=runtime.get("server_version_num"),
            pgvector_present=runtime.get("pgvector_present"),
        ),
        _assertion(
            "MIGRATION-0020-0021-FORWARD-IMMUTABLE",
            isinstance(migration_observation, Mapping)
            and _migration_observation_passes(migration_observation),
            cases=1,
        ),
        _assertion(
            "MIGRATION-POPULATED-ROUNDTRIP-ATOMIC",
            isinstance(populated_observation, Mapping)
            and _populated_observation_passes(populated_observation),
            fixture_rows=populated.get("fixture_rows"),
            retained_rows=populated.get("retained_rows"),
        ),
        _assertion(
            "SCHEMA-PROFILE-BOUNDARY-EXACT",
            isinstance(schema_observation, Mapping)
            and _schema_observation_passes(schema_observation),
            tables=migration.get("required_tables"),
            columns=migration.get("profile_columns"),
            constraints=migration.get("required_constraints"),
            indexes=migration.get("required_indexes"),
        ),
        _assertion(
            "CONTRACT-OWNER-PROJECTION-EXACT",
            behavior.get("owner_projection") is True
            and behavior.get("legacy_delegates_canonical") is True
            and behavior.get("ceremony_selector_absent") is True,
        ),
        _assertion(
            "CONTRACT-ANONYMOUS-EXPIRED-REVOKED-DELETED-WRONG-ROLE",
            behavior.get("denial_matrix") is True,
        ),
        _assertion(
            "CONTRACT-REGISTRATION-CONSENT-ZERO-MUTATION",
            behavior.get("registration_consent_zero_mutation") is True,
        ),
        _assertion(
            "CONTRACT-REGISTRATION-ENUMERATION-NEUTRAL",
            behavior.get("registration_enumeration_neutral") is True,
        ),
        _assertion(
            "CONTRACT-CROSS-USER-CLIENT-SELECTOR-DENIED",
            behavior.get("client_selector_denial") is True
            and behavior.get("cross_user_denied") is True,
        ),
        _assertion(
            "CONTRACT-NONTEST-ACTOR-HEADER-REJECTED",
            behavior.get("non_test_actor_header_rejected") is True,
        ),
        _assertion(
            "CONTRACT-COMPLETION-V1-DETERMINISTIC",
            behavior.get("completion") is True
            and behavior.get("section_order") is True
            and behavior.get("verification_independent") is True,
        ),
        _assertion(
            "CONTRACT-PERSISTENCE-FRESH-SESSION",
            behavior.get("fresh_session") is True
            and behavior.get("credential_unique_loser_reauthenticated") is True,
        ),
        _assertion(
            "CONTRACT-NORMALIZED-IDENTITY-NO-DUPLICATION",
            behavior.get("normalization") is True,
        ),
        _assertion(
            "CONTRACT-OPTIMISTIC-CONCURRENCY",
            behavior.get("cas_sql_exact") is True
            and behavior.get("concurrency") is True
            and behavior.get("stale_conflict_rejected") is True
            and behavior.get("conflict_atomic") is True
            and behavior.get("profile_session_lifecycle_serialized") is True,
        ),
        _assertion(
            "CONTRACT-DOB-GUARDIAN-ATOMIC",
            behavior.get("dob_guardian") is True
            and behavior.get("clock_injected") is True
            and behavior.get("share_projection_dob_serialized") is True
            and behavior.get("verification_token_dob_serialized") is True
            and behavior.get("share_session_lifecycle_serialized") is True
            and behavior.get("token_session_lifecycle_serialized") is True
            and behavior.get("share_unique_fault_reauthenticated") is True
            and behavior.get("token_unique_fault_reauthenticated") is True,
        ),
        _assertion("CONTRACT-DOB-AGE-BOUNDARIES", behavior.get("dob_boundaries") is True),
        _assertion(
            "CONTRACT-VERIFICATION-SELF-AUTHORITY-DENIED",
            behavior.get("self_authority_denied") is True
            and behavior.get("reviewer_serialization") is True
            and behavior.get("reviewer_session_lifecycle_serialized") is True,
        ),
        _assertion(
            "CONTRACT-AUTHORIZED-TRANSITIONS-EXACT",
            behavior.get("authorized_transitions_exact") is True
            and behavior.get("m01_completion_session_lifecycle_serialized") is True,
        ),
        _assertion(
            "CONTRACT-PROMPT-SESSION-SCOPE",
            behavior.get("prompt_scope") is True
            and behavior.get("prompt_lifecycle_races") is True
            and behavior.get("login_rotation_no_deadlock") is True,
        ),
        _assertion("CONTRACT-AUDIT-AGGREGATE-PRIVACY", behavior.get("audit_privacy") is True),
        _assertion(
            "HARNESS-MUTANTS-PRIVACY-SCRATCH-CLEANUP",
            _seeded_mutants_are_killed() and _scratch_observation_passes(cleanup),
            named_mutants=len(REQUIRED_MUTANT_IDS),
            cleanup_exact=cleanup.get("all_created_removed"),
        ),
    ]


def _blocked_report(reason: str) -> dict[str, object]:
    return {
        "gate": "nyay5_postgres",
        "status": "BLOCKED",
        "executed": False,
        "reason": reason,
        "assertions": [],
        "failed_assertions": [],
        "exit_code": BLOCKED_EXIT,
    }


def _write_report(path: str | None, report: Mapping[str, object]) -> None:
    if not path:
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    if not args.execute or os.environ.get(OPT_IN_ENV) != "1":
        report = _blocked_report("explicit execution opt-in is required")
        _write_report(args.output, report)
        print(json.dumps(report, sort_keys=True))
        return BLOCKED_EXIT
    if not args.database_url:
        report = _blocked_report("an explicit loopback PostgreSQL control URL is required")
        _write_report(args.output, report)
        print(json.dumps(report, sort_keys=True))
        return BLOCKED_EXIT

    manager: _ScratchDatabaseManager | None = None
    phase = "preflight"
    try:
        base = _safe_local_postgres_url(args.database_url)
        manager = _ScratchDatabaseManager(base)
        phase = "runtime"
        runtime = manager.run("runtime", _runtime_probe)
        if runtime["pass"] is not True:
            raise Blocked("PostgreSQL 16 plus pgvector is required")
        phase = "migration"
        migration = manager.run("migration", _migration_and_schema_probe)
        phase = "populated_migration"
        populated = manager.run("populated", _populated_migration_probe)
        phase = "behavior"
        behavior = manager.run("behavior", _behavior_probe)
        phase = "assembly"
        cleanup = manager.summary()
        assertions = _assemble_assertions(
            runtime, migration, populated, behavior, cleanup
        )
        evaluation = _evaluate_assertions(assertions)
        report: dict[str, object] = {
            "gate": "nyay5_postgres",
            "status": "PASS" if evaluation["overall_pass"] else "FAIL",
            "executed": True,
            "head": PINNED_HEAD,
            "assertions": assertions,
            "failed_assertions": evaluation["failed"],
            "assertion_summary": evaluation,
            "scratch_cleanup": cleanup,
            "mutant_inventory": {
                "named": len(REQUIRED_MUTANT_IDS),
                "killed": sum(_seeded_mutant_results().values()),
            },
            "exit_code": 0 if evaluation["overall_pass"] else 1,
        }
        findings = _privacy_findings(report)
        report["privacy_scan"] = {
            "scanned": True,
            "findings": len(findings),
            "passed": not findings,
        }
        if findings:
            report["status"] = "FAIL"
            report["exit_code"] = 1
        exit_code = int(report["exit_code"])
    except Blocked as exc:
        report = _blocked_report(str(exc))
        if manager is not None:
            report["scratch_cleanup"] = manager.summary()
        exit_code = BLOCKED_EXIT
    except Exception as exc:
        cleanup = manager.summary() if manager is not None else {
            "created": 0,
            "removed": 0,
            "cleanup_failed": 0,
            "all_created_removed": True,
            "purposes": [],
        }
        report = {
            "gate": "nyay5_postgres",
            "status": "FAIL",
            "executed": bool(manager and manager.records),
            "failure_class": type(exc).__name__,
            "failure_phase": phase,
            "assertions": [],
            "failed_assertions": list(REQUIRED_ASSERTION_IDS),
            "scratch_cleanup": cleanup,
            "exit_code": 1,
        }
        exit_code = 1

    final_findings = _privacy_findings(report)
    if final_findings:
        report["status"] = "FAIL"
        report["exit_code"] = 1
        exit_code = 1
    _write_report(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
