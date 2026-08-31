"""NYAY-9 owner-scoped profile API native PostgreSQL release producer.

The ordinary unit suite cannot prove PostgreSQL row-lock ordering, unique-key
winner/loser behaviour, or an Alembic up/down/up lifecycle.  This opt-in
producer therefore accepts only an explicit query-free loopback PostgreSQL
control URL, creates marker-named disposable databases, and emits an
aggregate-only report consumed by ``scripts/ci/nyay9-profile-api-postgres.mjs``.

No URL, database name, UUID, cookie, idempotency key, request payload, profile
value, ciphertext, hash, or other identity data is written to evidence.

Exit codes: 0 PASS, 1 FAIL, 78 BLOCKED prerequisite.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, func, inspect, make_url, select, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CONTRACT_PATH = REPOSITORY / "scripts/ci/nyay9-profile-api-contract.json"
BLOCKED_EXIT = 78
OPT_IN_ENV = "NYAY9_POSTGRES_GATE"
PREVIOUS_REVISION = "0021_nyay5_profile_boundary"
PINNED_HEAD = "0022_nyay9_owner_profile_api"
PINNED_MIGRATION = (
    BACKEND
    / "app/db/migrations/versions/0022_nyay9_owner_profile_api.py"
)
MIGRATION_AUTHORITY = BACKEND / "app/db/migration_release_guard.py"
MIGRATION_AUTHORITY_REFERENCE = (
    "backend/app/db/migration_release_guard.py#APPLICATION_HEAD_SOURCE_SHA256"
)
SCRATCH_PREFIX = "nyay9_profile_"
FIXED_NOW = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)
TRUSTED_ORIGIN = "https://nyay9-gate.invalid"

REQUIRED_ORACLE_IDS = (
    "OWNER_ONLY_SESSION_AUTHORITY",
    "CROSS_OWNER_ISOLATION",
    "IDEMPOTENT_SAME_KEY_CONCURRENCY",
    "VERSION_CONFLICT_DIFFERENT_KEYS",
    "DOB_GUARDIAN_ATOMIC_TRANSITION",
    "PII_CLEAN_DIAGNOSTICS",
    "MIGRATION_UP_DOWN_UP",
)

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

_UUID_TEXT = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_EMAIL_TEXT = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_MOBILE_TEXT = re.compile(r"(?<!\d)[6-9]\d{9}(?!\d)")
_DATE_TEXT = re.compile(r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b")
_URL_TEXT = re.compile(r"(?i)\b(?:postgres(?:ql)?|https?)\+?[^\s:]*://")
_TOKEN_TEXT = re.compile(r"(?i)\b(?:bearer\s+|eyJ)[A-Za-z0-9._~+/-]{12,}")
_HEX64_TEXT = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "actor_id",
        "actor_user_id",
        "canonical_payload",
        "ciphertext",
        "cookie",
        "database_name",
        "database_url",
        "date_of_birth",
        "dob",
        "email",
        "first_name",
        "idempotency_key",
        "idempotency_key_hash",
        "last_name",
        "middle_name",
        "mobile",
        "outcome_ct",
        "payload",
        "profile_id",
        "registration_id",
        "request_body",
        "request_fingerprint",
        "scratch_database",
        "session_token",
        "token",
        "user_id",
    }
)


class Blocked(RuntimeError):
    """A target-runtime prerequisite is absent; never a pass."""


class ProductGateFailure(RuntimeError):
    """The target runtime existed but a product or oracle failed."""


class ScratchCleanupFailure(RuntimeError):
    """A disposable database could not be removed."""


def _canonical_json_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _contract() -> dict[str, object]:
    try:
        document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Blocked("the NYAY-9 versioned contract is unavailable") from exc
    if not isinstance(document, dict):
        raise Blocked("the NYAY-9 versioned contract is malformed")
    if (
        document.get("schemaVersion") != "nyay9-profile-api-postgres/v1"
        or document.get("producer")
        != "backend/scripts/nyay9_postgres_profile_gate.py"
        or document.get("orchestrator")
        != "scripts/ci/nyay9-profile-api-postgres.mjs"
        or tuple(document.get("oracleInventory", [])) != REQUIRED_ORACLE_IDS
        or document.get("oracleCount") != len(REQUIRED_ORACLE_IDS)
    ):
        raise Blocked("the NYAY-9 versioned contract does not match the producer")
    migration = document.get("migration")
    if not isinstance(migration, dict) or migration != {
        "downRevision": PREVIOUS_REVISION,
        "path": PINNED_MIGRATION.relative_to(REPOSITORY).as_posix(),
        "revision": PINNED_HEAD,
        "sha256Authority": MIGRATION_AUTHORITY_REFERENCE,
    }:
        raise Blocked("the NYAY-9 migration contract is not exact")
    return document


def _contract_check() -> dict[str, object]:
    contract = _contract()
    source = Path(__file__).read_text(encoding="utf-8")
    return {
        "gate": "nyay9_profile_api_postgres_producer",
        "status": "PASS",
        "classification": "CONTRACT_CHECK_ONLY",
        "executed": False,
        "oracle_count": len(REQUIRED_ORACLE_IDS),
        "oracle_inventory_exact": all(
            source.count(identifier) >= 1 for identifier in REQUIRED_ORACLE_IDS
        ),
        "contract_digest": _canonical_json_digest(contract),
        "exit_code": 0,
    }


def _reject_ambient_libpq_environment() -> None:
    if any(key in LIBPQ_AMBIENT_KEYS or key.startswith("PGSSL") for key in os.environ):
        raise Blocked("ambient libpq routing or credential environment is not allowed")


def _safe_local_postgres_url(raw: str) -> URL:
    _reject_ambient_libpq_environment()
    if "://" not in raw:
        raise Blocked("an explicit PostgreSQL URL is required")
    authority = re.split(r"[/?#]", raw.split("://", 1)[1], maxsplit=1)[0]
    if "%" in authority or authority.count("@") > 1:
        raise Blocked("the PostgreSQL URL authority is ambiguous")
    try:
        url = make_url(raw)
    except Exception as exc:
        raise Blocked("an explicit PostgreSQL URL is required") from exc
    if url.get_backend_name() != "postgresql" or url.query:
        raise Blocked("a query-free PostgreSQL URL is required")
    try:
        if ipaddress.ip_address((url.host or "").casefold()).is_loopback:
            return url
    except ValueError:
        pass
    raise Blocked("the NYAY-9 gate accepts a literal loopback PostgreSQL host only")


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
        raise Blocked("could not create a disposable NYAY-9 database") from exc
    return _database_url(base, name)


def _scratch_inventory(base: URL) -> set[str]:
    engine = create_engine(_database_url(base, "postgres"), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return {
                str(value)
                for value in connection.scalars(
                    text(
                        "SELECT datname FROM pg_database "
                        "WHERE datname LIKE 'nyay9_profile_%'"
                    )
                )
            }
    finally:
        engine.dispose()


class _ScratchDatabaseManager:
    def __init__(self, base: URL) -> None:
        self.base = base
        self.records: list[dict[str, object]] = []
        self._owned: set[str] = set()
        try:
            self._baseline = _scratch_inventory(base)
        except Exception as exc:
            raise Blocked("could not inventory disposable NYAY-9 databases") from exc

    def run(self, purpose: str, probe: Callable[[str], Any]) -> Any:
        name = f"{SCRATCH_PREFIX}{uuid.uuid4().hex}"
        row: dict[str, object] = {
            "purpose": purpose,
            "created": False,
            "cleanup": "PENDING",
        }
        self.records.append(row)
        self._owned.add(name)
        try:
            url = _create_scratch(self.base, name)
            row["created"] = True
            return probe(url)
        finally:
            if row["created"] is True:
                try:
                    _drop_scratch(self.base, name)
                    if name in _scratch_inventory(self.base):
                        raise ScratchCleanupFailure(
                            "a disposable NYAY-9 database remained after cleanup"
                        )
                    row["cleanup"] = "PASS"
                except ScratchCleanupFailure:
                    row["cleanup"] = "FAIL"
                    raise
                except Exception as exc:
                    row["cleanup"] = "FAIL"
                    raise ScratchCleanupFailure(
                        "a disposable NYAY-9 database could not be removed"
                    ) from exc
            else:
                row["cleanup"] = "NOT_CREATED"

    def summary(self) -> dict[str, object]:
        created = sum(row["created"] is True for row in self.records)
        removed = sum(row["cleanup"] == "PASS" for row in self.records)
        failed = sum(row["cleanup"] == "FAIL" for row in self.records)
        try:
            current = _scratch_inventory(self.base)
            inventory_match = current == self._baseline and not self._owned & current
            current_count = len(current)
        except Exception:
            inventory_match = False
            current_count = -1
        return {
            "created": created,
            "removed": removed,
            "cleanup_failed": failed,
            "all_created_removed": (
                created == removed and failed == 0 and inventory_match
            ),
            "inventory_match": inventory_match,
            "baseline_count": len(self._baseline),
            "final_count": current_count,
            "purposes": [str(row["purpose"]) for row in self.records],
        }


def _run_alembic(scratch_url: str, *arguments: str) -> int:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env={
            **os.environ,
            "APP_ENV": "testing",
            "DATABASE_URL": scratch_url,
            "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=300,
        check=False,
    )
    return result.returncode


def _runtime_probe(scratch_url: str) -> dict[str, object]:
    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            version = int(connection.scalar(text("SHOW server_version_num")))
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            vector = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
    except Exception as exc:
        raise Blocked("PostgreSQL runtime could not be inspected") from exc
    finally:
        engine.dispose()
    return {
        "postgres16": 160000 <= version < 170000,
        "pgvector": isinstance(vector, str) and bool(vector.strip()),
    }


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def _schema_digest(engine: Engine, excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    catalog = inspect(engine)
    rows: list[dict[str, object]] = []
    for table in sorted(set(catalog.get_table_names()) - excluded):
        rows.append(
            {
                "table": table,
                "columns": [
                    {
                        "name": column["name"],
                        "type": str(column["type"]),
                        "nullable": bool(column["nullable"]),
                    }
                    for column in catalog.get_columns(table)
                ],
                "pk": catalog.get_pk_constraint(table),
                "fks": catalog.get_foreign_keys(table),
                "unique": catalog.get_unique_constraints(table),
                "checks": catalog.get_check_constraints(table),
                "indexes": catalog.get_indexes(table),
            }
        )
    return _canonical_json_digest(rows)


def _migration_source_authority_matches() -> bool:
    if not PINNED_MIGRATION.is_file() or not MIGRATION_AUTHORITY.is_file():
        return False
    try:
        from app.db import migration_release_guard
    except Exception:
        return False
    migration_digest = hashlib.sha256(PINNED_MIGRATION.read_bytes()).hexdigest()
    return bool(
        migration_release_guard.APPLICATION_HEAD_REVISION == PINNED_HEAD
        and migration_release_guard.APPLICATION_HEAD_SOURCE_PATH.resolve()
        == PINNED_MIGRATION.resolve()
        and migration_release_guard.APPLICATION_HEAD_SOURCE_SHA256
        == migration_digest
        and migration_release_guard.source_authority_is_valid()
    )


def _idempotency_schema_exact(engine: Engine) -> bool:
    catalog = inspect(engine)
    table = "profile_mutation_idempotency_records"
    if table not in catalog.get_table_names():
        return False
    columns = {item["name"]: item for item in catalog.get_columns(table)}
    expected = {
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
    if set(columns) != expected or "idempotency_key" in columns:
        return False
    pk = catalog.get_pk_constraint(table)
    uniques = catalog.get_unique_constraints(table)
    foreign_keys = catalog.get_foreign_keys(table)
    checks = catalog.get_check_constraints(table)
    return bool(
        pk.get("name") == "pk_profile_mutation_idempotency_records"
        and pk.get("constrained_columns") == ["id"]
        and len(uniques) == 1
        and uniques[0].get("name")
        == "uq_profile_mutation_idempotency_records_scope"
        and uniques[0].get("column_names")
        == ["actor_user_id", "section", "idempotency_key_hash"]
        and len(foreign_keys) == 1
        and foreign_keys[0].get("constrained_columns") == ["actor_user_id"]
        and foreign_keys[0].get("referred_table") == "users"
        and str(foreign_keys[0].get("options", {}).get("ondelete", "")).upper()
        == "CASCADE"
        and len(checks) >= 5
        and all(item.get("name") for item in checks)
    )


def _migration_probe(scratch_url: str) -> dict[str, bool]:
    if _run_alembic(scratch_url, "upgrade", PREVIOUS_REVISION) != 0:
        raise ProductGateFailure("migration parent setup failed")
    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        parent_tables = set(inspect(engine).get_table_names())
        parent_digest = _schema_digest(engine)
        absent_at_parent = "profile_mutation_idempotency_records" not in parent_tables
        if _run_alembic(scratch_url, "upgrade", PINNED_HEAD) != 0:
            raise ProductGateFailure("migration upgrade failed")
        first_head = _current_revision(engine)
        first_digest = _schema_digest(engine)
        schema_exact = _idempotency_schema_exact(engine)
        if _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION) != 0:
            raise ProductGateFailure("migration downgrade failed")
        down_revision = _current_revision(engine)
        down_tables = set(inspect(engine).get_table_names())
        down_digest = _schema_digest(engine)
        if _run_alembic(scratch_url, "upgrade", PINNED_HEAD) != 0:
            raise ProductGateFailure("migration re-upgrade failed")
        second_head = _current_revision(engine)
        second_digest = _schema_digest(engine)
        schema_exact_after = _idempotency_schema_exact(engine)
        check_passed = _run_alembic(scratch_url, "check") == 0
    finally:
        engine.dispose()
    return {
        "parent_exact": absent_at_parent,
        "first_upgrade_exact": first_head == PINNED_HEAD and schema_exact,
        "downgrade_exact": (
            down_revision == PREVIOUS_REVISION
            and "profile_mutation_idempotency_records" not in down_tables
            and down_digest == parent_digest
        ),
        "reupgrade_exact": (
            second_head == PINNED_HEAD
            and schema_exact_after
            and second_digest == first_digest
        ),
        "alembic_check": check_passed,
        "source_authority_exact": _migration_source_authority_matches(),
    }


def _body_code(response: Any) -> str | None:
    try:
        body = response.json()
    except Exception:
        return None
    detail = body.get("detail") if isinstance(body, Mapping) else None
    return detail.get("code") if isinstance(detail, Mapping) else None


def _behavior_probe(scratch_url: str) -> dict[str, bool]:
    if _run_alembic(scratch_url, "upgrade", PINNED_HEAD) != 0:
        raise ProductGateFailure("behavior migration failed")
    engine = create_engine(scratch_url, poolclass=NullPool)
    prior: dict[str, object] = {}
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api.v1 import student_settings
        from app.core.config import settings
        from app.core.crypto import KeyRing, encrypt, keyed_hash, override_keyring
        from app.core.exceptions import register_exception_handlers
        from app.core.middleware import RequestIDMiddleware
        from app.db.models.audit import AuditEvent
        from app.db.session import get_session
        from app.models.registration import (
            AuthSession,
            GuardianConsent,
            ProfileMutationIdempotencyRecord,
            StudentProfile,
            StudentRegistration,
            User,
        )

        factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

        def request_session():
            session = factory()
            try:
                yield session
            finally:
                session.close()

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
        register_exception_handlers(app)
        app.include_router(student_settings.router, prefix="/api/v1")
        app.dependency_overrides[get_session] = request_session

        prior = {
            "app_env": settings.app_env,
            "cors_origins": list(settings.cors_origins),
            "now": student_settings._now,
        }
        session_anchor = datetime.now(timezone.utc)
        settings.app_env = "testing"
        settings.cors_origins = [TRUSTED_ORIGIN]
        student_settings._now = lambda: FIXED_NOW
        override_keyring(
            KeyRing(
                active_version="v1",
                secrets={"v1": b"nyay9-postgres-gate-synthetic-key-v1"},
                lookup_secret=b"nyay9-postgres-gate-synthetic-lookup-v1",
            )
        )

        def seed(label: str, *, role: str = "student") -> dict[str, object]:
            token = f"nyay9-{label}-" + uuid.uuid4().hex
            with factory.begin() as session:
                user = User(role=role, status="active")
                session.add(user)
                session.flush()
                registration = StudentRegistration(
                    user_id=user.id,
                    first_name="Synthetic",
                    middle_name=None,
                    last_name="Student",
                    mobile_hash=keyed_hash(f"mobile-{label}"),
                    mobile_ct=encrypt(f"mobile-{label}"),
                    dob_hash=keyed_hash("2000-01-01"),
                    dob_ct=encrypt("2000-01-01"),
                    dob_hash_state="verified",
                    key_version="v1",
                    status="active",
                    is_minor=False,
                )
                session.add(registration)
                session.flush()
                profile = StudentProfile(registration_id=registration.id)
                session.add(profile)
                auth_session = AuthSession(
                    user_id=user.id,
                    token_hash=keyed_hash(token),
                    status="active",
                    expires_at=session_anchor
                    + timedelta(seconds=settings.auth_session_ttl_seconds),
                    last_seen_at=session_anchor,
                )
                session.add(auth_session)
                session.flush()
                return {
                    "user": user.id,
                    "registration": registration.id,
                    "profile": profile.id,
                    "token": token,
                }

        def client_for(actor: Mapping[str, object] | None) -> TestClient:
            client = TestClient(app, base_url=TRUSTED_ORIGIN, raise_server_exceptions=False)
            client.headers["Origin"] = TRUSTED_ORIGIN
            if actor is not None:
                client.cookies.set(
                    settings.auth_session_cookie_name,
                    str(actor["token"]),
                )
            return client

        def personal(
            *, version: int, label: str, city: str, dob: str = "2000-01-01"
        ) -> dict[str, object]:
            return {
                "expected_profile_version": version,
                "first_name": "Synthetic",
                "middle_name": None,
                "last_name": label,
                "date_of_birth": dob,
                "preferred_language": "en",
                "city": city,
                "pronouns": None,
            }

        observations = {
            "owner_only": False,
            "cross_owner": False,
            "same_key_concurrency": False,
            "different_key_conflict": False,
            "dob_guardian_atomic": False,
        }

        owner = seed("owner")
        other = seed("other")
        owner_client = client_for(owner)
        read = owner_client.get("/api/v1/student/profile")
        forged = owner_client.get(
            "/api/v1/student/profile",
            headers={
                "Origin": TRUSTED_ORIGIN,
                "X-Actor-Claims": json.dumps(
                    {"sub": str(other["user"]), "roles": ["student"]}
                ),
            },
        )
        query_selected = owner_client.get(
            "/api/v1/student/profile",
            params={"registration_id": str(other["registration"])},
        )
        body_selected = owner_client.patch(
            "/api/v1/student/profile/personal",
            headers={"Idempotency-Key": "owner-boundary-key-0001"},
            json={
                **personal(version=1, label="Owner", city="OwnerCity"),
                "registration_id": str(other["registration"]),
            },
        )
        anonymous = client_for(None).get("/api/v1/student/profile")
        invalid_client = TestClient(app, base_url=TRUSTED_ORIGIN, raise_server_exceptions=False)
        invalid_client.headers["Origin"] = TRUSTED_ORIGIN
        invalid_client.cookies.set(settings.auth_session_cookie_name, "invalid-cookie")
        invalid = invalid_client.get("/api/v1/student/profile")
        observations["owner_only"] = bool(
            read.status_code == 200
            and forged.status_code == 200
            and forged.json() == read.json()
            and query_selected.status_code == 422
            and body_selected.status_code == 422
            and anonymous.status_code == 401
            and invalid.status_code == 401
        )

        cross_a = seed("cross-a")
        cross_b = seed("cross-b")
        shared_key = "cross-owner-shared-key-0001"
        cross_a_response = client_for(cross_a).patch(
            "/api/v1/student/profile/personal",
            headers={"Idempotency-Key": shared_key},
            json=personal(version=1, label="Alpha", city="AlphaCity"),
        )
        cross_b_response = client_for(cross_b).patch(
            "/api/v1/student/profile/personal",
            headers={"Idempotency-Key": shared_key},
            json=personal(version=1, label="Beta", city="BetaCity"),
        )
        with factory() as session:
            cross_profiles = {
                cross_a["profile"]: session.get(StudentProfile, cross_a["profile"]),
                cross_b["profile"]: session.get(StudentProfile, cross_b["profile"]),
            }
            scoped_records = int(
                session.scalar(
                    select(func.count(ProfileMutationIdempotencyRecord.id)).where(
                        ProfileMutationIdempotencyRecord.actor_user_id.in_(
                            [cross_a["user"], cross_b["user"]]
                        ),
                        ProfileMutationIdempotencyRecord.section == "personal",
                    )
                )
                or 0
            )
        observations["cross_owner"] = bool(
            cross_a_response.status_code == 200
            and cross_b_response.status_code == 200
            and scoped_records == 2
            and cross_profiles[cross_a["profile"]] is not None
            and cross_profiles[cross_b["profile"]] is not None
            and cross_profiles[cross_a["profile"]].profile_version == 2
            and cross_profiles[cross_b["profile"]].profile_version == 2
        )

        replay_actor = seed("same-key")
        replay_key = "same-key-concurrency-00000001"
        replay_payload = personal(version=1, label="Replay", city="ReplayCity")

        def same_key_request(_index: int):
            return client_for(replay_actor).patch(
                "/api/v1/student/profile/personal",
                headers={"Idempotency-Key": replay_key},
                json=replay_payload,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            replay_responses = list(executor.map(same_key_request, range(2)))
        with factory() as session:
            replay_profile = session.get(StudentProfile, replay_actor["profile"])
            replay_records = int(
                session.scalar(
                    select(func.count(ProfileMutationIdempotencyRecord.id)).where(
                        ProfileMutationIdempotencyRecord.actor_user_id
                        == replay_actor["user"],
                        ProfileMutationIdempotencyRecord.section == "personal",
                    )
                )
                or 0
            )
            replay_audits = int(
                session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.actor_user_id == replay_actor["user"],
                        AuditEvent.action == "student.profile.section_updated",
                    )
                )
                or 0
            )
            replay_row = session.scalar(
                select(ProfileMutationIdempotencyRecord).where(
                    ProfileMutationIdempotencyRecord.actor_user_id
                    == replay_actor["user"],
                    ProfileMutationIdempotencyRecord.section == "personal",
                )
            )
        replay_bodies = [response.json() for response in replay_responses]
        replay_conflict = client_for(replay_actor).patch(
            "/api/v1/student/profile/personal",
            headers={"Idempotency-Key": replay_key},
            json=personal(
                version=1,
                label="Replay",
                city="DifferentReplayCity",
            ),
        )
        replay_conflict_detail = (
            replay_conflict.json().get("detail", {})
            if replay_conflict.status_code == 409
            else {}
        )
        observations["same_key_concurrency"] = bool(
            [response.status_code for response in replay_responses] == [200, 200]
            and replay_bodies[0] == replay_bodies[1]
            and sum(
                response.headers.get("Idempotency-Replayed") == "true"
                for response in replay_responses
            )
            >= 1
            and replay_profile is not None
            and replay_profile.profile_version == 2
            and replay_records == 1
            and replay_audits == 1
            and replay_row is not None
            and replay_row.state == "succeeded"
            and replay_row.outcome_status == 200
            and replay_row.profile_version == 2
            and replay_conflict.status_code == 409
            and replay_conflict_detail
            == {
                "code": "profile_idempotency_conflict",
                "message": "Request failed",
                "section": "personal",
            }
        )
        observations["same_key_statuses_exact"] = sorted(
            response.status_code for response in replay_responses
        ) == [200, 200]
        observations["same_key_bodies_equal"] = replay_bodies[0] == replay_bodies[1]
        observations["same_key_replay_headers"] = sum(
            response.headers.get("Idempotency-Replayed") == "true"
            for response in replay_responses
        )
        observations["same_key_profile_exact"] = bool(
            replay_profile is not None and replay_profile.profile_version == 2
        )
        observations["same_key_ledger_rows"] = replay_records
        observations["same_key_audit_rows"] = replay_audits
        observations["same_key_ledger_succeeded"] = bool(
            replay_row is not None
            and replay_row.state == "succeeded"
            and replay_row.outcome_status == 200
            and replay_row.profile_version == 2
        )
        observations["same_key_conflict_typed"] = bool(
            replay_conflict.status_code == 409
            and replay_conflict_detail
            == {
                "code": "profile_idempotency_conflict",
                "message": "Request failed",
                "section": "personal",
            }
        )
        observations["same_key_conflict_status"] = replay_conflict.status_code
        observations["same_key_conflict_code_exact"] = (
            _body_code(replay_conflict) == "profile_idempotency_conflict"
        )

        conflict_actor = seed("different-keys")

        def conflicting_request(arguments: tuple[str, str]):
            key, city = arguments
            return client_for(conflict_actor).patch(
                "/api/v1/student/profile/personal",
                headers={"Idempotency-Key": key},
                json=personal(version=1, label="Conflict", city=city),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            conflict_responses = list(
                executor.map(
                    conflicting_request,
                    [
                        ("different-key-a-000000000001", "FirstCity"),
                        ("different-key-b-000000000001", "SecondCity"),
                    ],
                )
            )
        with factory() as session:
            conflict_profile = session.get(StudentProfile, conflict_actor["profile"])
            conflict_audits = int(
                session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.actor_user_id == conflict_actor["user"],
                        AuditEvent.action == "student.profile.section_updated",
                    )
                )
                or 0
            )
        observations["different_key_conflict"] = bool(
            sorted(response.status_code for response in conflict_responses) == [200, 409]
            and sum(
                _body_code(response) == "profile_version_conflict"
                for response in conflict_responses
            )
            == 1
            and conflict_profile is not None
            and conflict_profile.profile_version == 2
            and conflict_audits == 1
        )

        dob_actor = seed("dob-transition")
        dob_client = client_for(dob_actor)
        minor = dob_client.patch(
            "/api/v1/student/profile/personal",
            headers={"Idempotency-Key": "dob-minor-transition-000000001"},
            json=personal(
                version=1,
                label="Minor",
                city="MinorCity",
                dob="2012-01-01",
            ),
        )
        rejected = dob_client.patch(
            "/api/v1/student/profile/personal",
            headers={"Idempotency-Key": "dob-stale-transition-000000001"},
            json=personal(
                version=1,
                label="Adult",
                city="AdultCity",
                dob="2000-01-01",
            ),
        )
        with factory() as session:
            registration = session.get(StudentRegistration, dob_actor["registration"])
            profile = session.get(StudentProfile, dob_actor["profile"])
            guardians = list(
                session.scalars(
                    select(GuardianConsent).where(
                        GuardianConsent.registration_id == dob_actor["registration"]
                    )
                )
            )
            dob_records = int(
                session.scalar(
                    select(func.count(ProfileMutationIdempotencyRecord.id)).where(
                        ProfileMutationIdempotencyRecord.actor_user_id
                        == dob_actor["user"],
                        ProfileMutationIdempotencyRecord.state == "succeeded",
                    )
                )
                or 0
            )
        observations["dob_guardian_atomic"] = bool(
            minor.status_code == 200
            and minor.json().get("guardian")
            == {"required": True, "status": "required_pending"}
            and rejected.status_code == 409
            and _body_code(rejected) == "profile_version_conflict"
            and registration is not None
            and registration.is_minor is True
            and profile is not None
            and profile.profile_version == 2
            and len(guardians) == 1
            and guardians[0].status == "pending"
            and guardians[0].verified is False
            and dob_records == 1
        )
        return observations
    except Exception as exc:
        raise ProductGateFailure("NYAY-9 native behavior probe failed") from exc
    finally:
        try:
            from app.api.v1 import student_settings
            from app.core.config import settings
            from app.core.crypto import override_keyring

            settings.app_env = str(prior["app_env"])
            settings.cors_origins = list(prior["cors_origins"])
            student_settings._now = prior["now"]  # type: ignore[assignment]
            override_keyring(None)
            app.dependency_overrides.clear()
        except (KeyError, NameError):
            pass
        engine.dispose()


def _assertion(identifier: str, passed: bool, **metrics: object) -> dict[str, object]:
    return {
        "id": identifier,
        "status": "PASS" if passed is True else "FAIL",
        "passed": passed is True,
        "metrics": metrics,
    }


def _privacy_findings(value: object) -> list[str]:
    findings: set[str] = set()

    def visit(candidate: object, path: str) -> None:
        if isinstance(candidate, Mapping):
            for key, item in candidate.items():
                normalized = re.sub(
                    r"[^a-z0-9]+", "_", str(key).casefold()
                ).strip("_")
                if normalized in _FORBIDDEN_REPORT_KEYS:
                    findings.add(f"{path}.{normalized}:forbidden_key")
                visit(item, f"{path}.{normalized}")
        elif isinstance(candidate, Sequence) and not isinstance(
            candidate, (str, bytes)
        ):
            for index, item in enumerate(candidate):
                visit(item, f"{path}[{index}]")
        elif isinstance(candidate, str):
            for label, pattern in (
                ("uuid", _UUID_TEXT),
                ("email", _EMAIL_TEXT),
                ("mobile", _MOBILE_TEXT),
                ("date", _DATE_TEXT),
                ("url", _URL_TEXT),
                ("token", _TOKEN_TEXT),
                ("digest", _HEX64_TEXT),
            ):
                if pattern.search(candidate):
                    findings.add(f"{path}:{label}")

    visit(value, "report")
    return sorted(findings)


def _privacy_scanner_self_test() -> bool:
    """Kill a planted diagnostic leak without retaining it in evidence."""

    safe = {
        "status": "PASS",
        "concurrent_requests": 2,
        "aggregate_only": True,
    }
    planted = {
        "status": "PASS",
        "mobile": "9876543210",
        "request_body": "planted@example.invalid",
    }
    return not _privacy_findings(safe) and len(_privacy_findings(planted)) >= 2


def _assemble_assertions(
    runtime: Mapping[str, object],
    migration: Mapping[str, object],
    behavior: Mapping[str, object],
    cleanup: Mapping[str, object],
) -> list[dict[str, object]]:
    cleanup_exact = bool(
        cleanup.get("created") == 3
        and cleanup.get("removed") == 3
        and cleanup.get("cleanup_failed") == 0
        and cleanup.get("all_created_removed") is True
        and cleanup.get("inventory_match") is True
        and cleanup.get("baseline_count") == cleanup.get("final_count")
        and cleanup.get("purposes") == ["runtime", "migration", "behavior"]
    )
    migration_exact = all(value is True for value in migration.values())
    privacy_mutant_killed = _privacy_scanner_self_test()
    assertions = [
        _assertion(
            "OWNER_ONLY_SESSION_AUTHORITY",
            behavior.get("owner_only") is True,
            anonymous_denied=True,
            forged_selector_denied=True,
        ),
        _assertion(
            "CROSS_OWNER_ISOLATION",
            behavior.get("cross_owner") is True,
            independent_actor_scopes=2,
        ),
        _assertion(
            "IDEMPOTENT_SAME_KEY_CONCURRENCY",
            behavior.get("same_key_concurrency") is True,
            concurrent_requests=2,
            committed_mutations=1,
        ),
        _assertion(
            "VERSION_CONFLICT_DIFFERENT_KEYS",
            behavior.get("different_key_conflict") is True,
            concurrent_requests=2,
            winners=1,
            typed_conflicts=1,
        ),
        _assertion(
            "DOB_GUARDIAN_ATOMIC_TRANSITION",
            behavior.get("dob_guardian_atomic") is True,
            committed_transitions=1,
            rejected_partial_transitions=1,
        ),
        _assertion(
            "PII_CLEAN_DIAGNOSTICS",
            cleanup_exact and privacy_mutant_killed,
            aggregate_only=True,
            planted_privacy_mutant_killed=privacy_mutant_killed,
            scratch_cleanup_exact=cleanup_exact,
        ),
        _assertion(
            "MIGRATION_UP_DOWN_UP",
            runtime.get("postgres16") is True
            and runtime.get("pgvector") is True
            and migration_exact,
            postgres_major=16,
            pgvector_present=True,
            lifecycle_stages=3,
        ),
    ]
    return assertions


def _evaluate(assertions: list[Mapping[str, object]]) -> dict[str, object]:
    identifiers = [str(row.get("id", "")) for row in assertions]
    failed = [
        str(row.get("id", ""))
        for row in assertions
        if row.get("passed") is not True
    ]
    exact = identifiers == list(REQUIRED_ORACLE_IDS)
    return {
        "required": len(REQUIRED_ORACLE_IDS),
        "executed": len(assertions),
        "passed": sum(row.get("passed") is True for row in assertions),
        "failed": len(failed),
        "failed_ids": failed,
        "exact_inventory": exact,
        "overall_pass": exact and not failed,
    }


def _blocked_report(reason_code: str) -> dict[str, object]:
    return {
        "gate": "nyay9_profile_api_postgres_producer",
        "status": "BLOCKED",
        "executed": False,
        "reason_code": reason_code,
        "assertions": [],
        "assertion_summary": {
            "required": len(REQUIRED_ORACLE_IDS),
            "executed": 0,
            "passed": 0,
            "failed": len(REQUIRED_ORACLE_IDS),
            "failed_ids": list(REQUIRED_ORACLE_IDS),
            "exact_inventory": False,
            "overall_pass": False,
        },
        "exit_code": BLOCKED_EXIT,
    }


def _write(path: str | None, report: Mapping[str, object]) -> None:
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
    parser.add_argument("--check-contract", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    if args.check_contract:
        try:
            report = _contract_check()
            exit_code = 0
        except Exception:
            report = {
                "gate": "nyay9_profile_api_postgres_producer",
                "status": "FAIL",
                "classification": "CONTRACT_CHECK_ONLY",
                "executed": False,
                "reason_code": "CONTRACT_INVALID",
                "exit_code": 1,
            }
            exit_code = 1
        _write(args.output, report)
        print(json.dumps(report, sort_keys=True))
        return exit_code

    if not args.execute or os.environ.get(OPT_IN_ENV) != "1":
        report = _blocked_report("EXPLICIT_EXECUTION_OPT_IN_REQUIRED")
        _write(args.output, report)
        print(json.dumps(report, sort_keys=True))
        return BLOCKED_EXIT
    if not args.database_url:
        report = _blocked_report("LOOPBACK_POSTGRES_CONTROL_REQUIRED")
        _write(args.output, report)
        print(json.dumps(report, sort_keys=True))
        return BLOCKED_EXIT

    manager: _ScratchDatabaseManager | None = None
    phase = "preflight"
    try:
        _contract()
        base = _safe_local_postgres_url(args.database_url)
        manager = _ScratchDatabaseManager(base)
        phase = "runtime"
        runtime = manager.run("runtime", _runtime_probe)
        if not all(value is True for value in runtime.values()):
            raise Blocked("PostgreSQL 16 plus pgvector is required")
        phase = "migration"
        migration = manager.run("migration", _migration_probe)
        phase = "behavior"
        behavior = manager.run("behavior", _behavior_probe)
        phase = "assembly"
        cleanup = manager.summary()
        assertions = _assemble_assertions(runtime, migration, behavior, cleanup)
        evaluation = _evaluate(assertions)
        report: dict[str, object] = {
            "gate": "nyay9_profile_api_postgres_producer",
            "status": "PASS" if evaluation["overall_pass"] else "FAIL",
            "executed": True,
            "head": PINNED_HEAD,
            "assertions": assertions,
            "assertion_summary": evaluation,
            "scratch_cleanup": cleanup,
            "privacy_scan": {"scanned": True, "findings": 0, "passed": True},
            "exit_code": 0 if evaluation["overall_pass"] else 1,
        }
        findings = _privacy_findings(report)
        if findings:
            report["status"] = "FAIL"
            report["privacy_scan"] = {
                "scanned": True,
                "findings": len(findings),
                "passed": False,
            }
            report["exit_code"] = 1
        exit_code = int(report["exit_code"])
    except Blocked:
        report = _blocked_report("TARGET_RUNTIME_PREREQUISITE_BLOCKED")
        if manager is not None:
            report["scratch_cleanup"] = manager.summary()
        exit_code = BLOCKED_EXIT
    except Exception as exc:
        report = {
            "gate": "nyay9_profile_api_postgres_producer",
            "status": "FAIL",
            "executed": bool(manager and manager.records),
            "failure_class": type(exc).__name__,
            "failure_phase": phase,
            "assertions": [],
            "assertion_summary": {
                "required": len(REQUIRED_ORACLE_IDS),
                "executed": 0,
                "passed": 0,
                "failed": len(REQUIRED_ORACLE_IDS),
                "failed_ids": list(REQUIRED_ORACLE_IDS),
                "exact_inventory": False,
                "overall_pass": False,
            },
            "scratch_cleanup": manager.summary() if manager is not None else {},
            "privacy_scan": {"scanned": True, "findings": 0, "passed": True},
            "exit_code": 1,
        }
        exit_code = 1

    final_findings = _privacy_findings(report)
    if final_findings:
        report["status"] = "FAIL"
        report["privacy_scan"] = {
            "scanned": True,
            "findings": len(final_findings),
            "passed": False,
        }
        report["exit_code"] = 1
        exit_code = 1
    _write(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
