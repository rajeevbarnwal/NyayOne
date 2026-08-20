"""Fail-closed PostgreSQL 16 lifecycle gate for NYAY-16.

The gate never mutates the database named by ``DATABASE_URL``.  That URL is
used only as a loopback PostgreSQL control connection from which uniquely named
scratch databases are created and, in a ``finally`` block, removed.  A pass
proves the real 0015 -> 0016 migration on PostgreSQL; SQLite is not accepted as
substitute evidence.

Exit codes:

* 0  - every assertion passed and every scratch database was removed;
* 1  - an assertion failed (including privacy or cleanup);
* 78 - the explicitly opted-in PostgreSQL 16 prerequisite was unavailable.

The JSON report intentionally contains only assertion outcomes, aggregate
counts and SHA-256 fingerprints of canonical schema/count inventories.  It
never contains a database URL, credential, row identifier, ciphertext, DOB or
lookup hash.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
BLOCKED = 78
PARENT = "0015_wave4_public_risk_labels"
HEAD = "0016_dob_hash_reconcile"
LEDGER_VERIFY = ROOT / "scripts" / "ci" / "verify_migration_ledger.py"
OPERATOR_PREFLIGHT = BACKEND / "scripts" / "nyay16_migration_preflight.py"
_SCRATCH_PREFIX = "nyay16_gate_"
_SAFE_DB_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_MIGRATION_ADVISORY_LOCK = int.from_bytes(
    hashlib.sha256(b"nyayone:migration:0016:dob-hash-reconcile").digest()[:8],
    byteorder="big",
    signed=True,
)


ASSERTION_CONTRACT = (
    ("N16-PG-01", "target is PostgreSQL 16 with pgvector migration support"),
    ("N16-PG-02", "inherited migration SHA-256 ledger verifies before DB work"),
    ("N16-PG-03", "empty 0015 -> 0016 -> check -> 0015 -> 0016 is stable"),
    ("N16-PG-04", "populated safe, isolated-invalid and erased rows reconcile"),
    (
        "N16-PG-05",
        "downgrade rejects live quarantine and a safe populated subset round-trips",
    ),
    ("N16-PG-06", "ambiguous data fails before any 0016 DDL"),
    ("N16-PG-07", "partial/drifted schema fails before additional DDL"),
    ("N16-PG-08", "concurrent upgrade attempts converge without partial state"),
    ("N16-PG-09", "report is privacy-safe and contains no runtime secrets"),
    ("N16-PG-10", "every disposable database is removed"),
)


@dataclass(frozen=True)
class CommandResult:
    returncode: int


class Results:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(self, ident: str, title: str, ok: bool, detail: Any = None) -> None:
        row: dict[str, Any] = {
            "id": ident,
            "title": title,
            "status": "PASS" if ok else "FAIL",
        }
        if detail is not None:
            row["detail"] = detail
        self.rows.append(row)
        print(f"[{'PASS' if ok else 'FAIL'}] {ident} {title}")

    @property
    def ok(self) -> bool:
        return bool(self.rows) and all(row["status"] == "PASS" for row in self.rows)


def is_isolated_control_target(database_url: str, allow_databases: bool) -> bool:
    """Accept only an explicit loopback QA database plus mutation opt-in.

    Isolation markers are read from the database name only.  A password or
    query parameter containing ``test`` must never authorize CREATE DATABASE.
    """

    if not database_url or not allow_databases:
        return False
    try:
        parsed = make_url(database_url)
    except Exception:
        return False
    # psycopg accepts connection-routing query arguments (host, hostaddr,
    # service, options) that can override an apparently loopback authority.
    # Gate URLs have no need for query parameters, percent-encoded authority
    # components, or multiple @ delimiters, so reject the entire ambiguous
    # surface rather than attempting an incomplete allowlist.
    authority = database_url.split("://", 1)[-1].split("/", 1)[0]
    if parsed.query or "%" in authority or authority.count("@") > 1:
        return False
    if not parsed.drivername.casefold().startswith("postgres"):
        return False
    if (parsed.host or "").casefold() not in {"127.0.0.1", "localhost", "::1"}:
        return False
    tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", (parsed.database or "").casefold())
        if token
    }
    return bool(tokens & {"ci", "test", "testing", "qa", "nyay16"}) and not bool(
        tokens & {"prod", "production", "stage", "staging"}
    )


def _canonical_fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_postgresql_16(server_version_num: int) -> bool:
    """The approved runtime is major 16, not an open-ended minimum."""

    return 160000 <= server_version_num < 170000


def privacy_canary_hits(payload: Any, canaries: Iterable[str]) -> list[str]:
    """Return canary labels only; never echo the matched secret value."""

    serialised = json.dumps(payload, sort_keys=True, default=str)
    return [f"canary-{index}" for index, value in enumerate(canaries) if value and value in serialised]


def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt(value: str, secret: str, version: str = "v1") -> str:
    token = _fernet(secret).encrypt(value.encode("utf-8")).decode("ascii")
    return f"{version}:{token}"


def _lookup_hash(value: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), value.strip().encode("utf-8"), hashlib.sha256).hexdigest()


def _scratch_url(control_url: str, database: str) -> str:
    return make_url(control_url).set(database=database).render_as_string(hide_password=False)


def _migration_env(database_url: str, encryption_secret: str, lookup_secret: str) -> dict[str, str]:
    return {
        **os.environ,
        "APP_ENV": "testing",
        "DATABASE_URL": database_url,
        "REGISTRATION_SECRET": encryption_secret,
        "REGISTRATION_LOOKUP_SECRET": lookup_secret,
        "REGISTRATION_KEY_VERSION": "v1",
        "REGISTRATION_PRIOR_KEYS": "[]",
    }


def _run_alembic(database_url: str, env: dict[str, str], *args: str) -> CommandResult:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**env, "DATABASE_URL": database_url},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=180,
        check=False,
    )
    return CommandResult(completed.returncode)


def _run_ledger() -> CommandResult:
    if not LEDGER_VERIFY.is_file():
        return CommandResult(1)
    completed = subprocess.run(
        [sys.executable, str(LEDGER_VERIFY)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )
    return CommandResult(completed.returncode)


def _operator_preflight_matches(
    database_url: str,
    env: dict[str, str],
    *,
    returncode: int,
    payload: dict[str, Any],
) -> bool:
    """Require one exact sanitized operator result without exporting output."""

    if not OPERATOR_PREFLIGHT.is_file() or OPERATOR_PREFLIGHT.is_symlink():
        return False
    try:
        completed = subprocess.run(
            [sys.executable, str(OPERATOR_PREFLIGHT)],
            cwd=BACKEND,
            env={**env, "DATABASE_URL": database_url},
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=60,
            check=False,
        )
        observed = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False
    return completed.returncode == returncode and observed == payload


def _create_database(control: Engine, database: str) -> None:
    if not _SAFE_DB_NAME.fullmatch(database):
        raise ValueError("unsafe scratch database identifier")
    with control.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database}"')


def _drop_database(control: Engine, database: str) -> bool:
    if not _SAFE_DB_NAME.fullmatch(database):
        return False
    try:
        with control.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:database AND pid <> pg_backend_pid()"
                ),
                {"database": database},
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}"')
        return True
    except Exception:
        return False


def _schema_inventory(connection: Connection) -> dict[str, Any]:
    """Canonical public-schema structure with no application row data."""

    tables = connection.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "ORDER BY table_name"
        )
    ).scalars().all()
    columns = connection.execute(
        text(
            "SELECT table_name,column_name,data_type,udt_name,is_nullable,"
            "COALESCE(column_default,'') FROM information_schema.columns "
            "WHERE table_schema='public' ORDER BY table_name,ordinal_position"
        )
    ).all()
    constraints = connection.execute(
        text(
            "SELECT c.conrelid::regclass::text,c.conname,pg_get_constraintdef(c.oid,true) "
            "FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
            "WHERE n.nspname='public' ORDER BY 1,2"
        )
    ).all()
    indexes = connection.execute(
        text(
            "SELECT tablename,indexname,indexdef FROM pg_indexes "
            "WHERE schemaname='public' ORDER BY tablename,indexname"
        )
    ).all()
    triggers = connection.execute(
        text(
            "SELECT event_object_table,trigger_name,event_manipulation,action_timing "
            "FROM information_schema.triggers WHERE trigger_schema='public' "
            "ORDER BY event_object_table,trigger_name,event_manipulation"
        )
    ).all()
    return {
        "tables": list(tables),
        "columns": [list(row) for row in columns],
        "constraints": [list(row) for row in constraints],
        "indexes": [list(row) for row in indexes],
        "triggers": [list(row) for row in triggers],
    }


def _schema_fingerprint(engine: Engine) -> str:
    with engine.connect() as connection:
        return _canonical_fingerprint(_schema_inventory(connection))


def _registration_data_fingerprint(engine: Engine) -> str:
    """One-way exact fingerprint of registration rows for no-mutation proofs.

    The canonical row bytes are held only in process memory.  Evidence receives
    the SHA-256 digest, never an identifier, ciphertext, DOB or stored hash.
    """

    with engine.connect() as connection:
        payload = connection.scalar(
            text(
                "SELECT COALESCE(jsonb_agg(to_jsonb(sr) ORDER BY sr.id)::text,'[]') "
                "FROM student_registrations sr"
            )
        )
    return hashlib.sha256(str(payload).encode("utf-8")).hexdigest()


def _head(engine: Engine) -> str | None:
    with engine.connect() as connection:
        exists = connection.scalar(
            text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
        )
        if not exists:
            return None
        return connection.scalar(text("SELECT version_num FROM alembic_version"))


def _clear_seed_rows(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users"))


def _nyay16_shape(engine: Engine) -> dict[str, bool]:
    with engine.connect() as connection:
        return {
            "state_column": bool(
                connection.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema='public' AND table_name='student_registrations' "
                        "AND column_name='dob_hash_state')"
                    )
                )
            ),
            "reconciliation_table": bool(
                connection.scalar(
                    text("SELECT to_regclass('public.registration_dob_reconciliations') IS NOT NULL")
                )
            ),
        }


def _seed_rows(
    engine: Engine,
    encryption_secret: str,
    lookup_secret: str,
    *,
    include_mismatch: bool = False,
) -> dict[str, Any]:
    """Seed synthetic cases and return only in-memory expectations/canaries."""

    canonical = "2001-02-03"
    alternate = "1999-08-07"
    noncanonical = "03/02/2001"
    # Keep the native subprocess proof stable even if a run crosses midnight.
    future = (date.today() + timedelta(days=366)).isoformat()
    cases = [
        ("safe", _encrypt(canonical, encryption_secret), "[rehash-required]", "v1", "active"),
        ("unreadable", "v1:not-a-fernet-token", "[rehash-required]", "v1", "active"),
        ("noncanonical", _encrypt(noncanonical, encryption_secret), "[rehash-required]", "v1", "active"),
        ("future", _encrypt(future, encryption_secret), "[rehash-required]", "v1", "active"),
        # Retention already marks a deleted DOB with an irreversible marker.
        # 0016 must classify, not reconstruct or quarantine, that state.
        ("erased", "[erased]", "__ERASED_MARKER__", "v1", "deleted"),
        ("verified", _encrypt(alternate, encryption_secret), _lookup_hash(alternate, lookup_secret), "v1", "active"),
    ]
    if include_mismatch:
        cases = [
            ("mismatch", _encrypt(canonical, encryption_secret), "0" * 64, "v1", "active")
        ]

    ids: dict[str, uuid.UUID] = {}
    mobile_canaries: list[str] = []
    with engine.begin() as connection:
        for index, (case, dob_ct, dob_hash, key_version, status) in enumerate(cases):
            user_id = uuid.uuid4()
            registration_id = uuid.uuid4()
            ids[case] = registration_id
            if dob_hash == "__ERASED_MARKER__":
                dob_hash = f"[erased]:{registration_id}"
            if case == "erased":
                mobile_value = ""
                mobile_hash = f"[erased]:{registration_id}"
                mobile_ct = "[erased]"
            else:
                mobile_value = f"900000{index:04d}"
                mobile_canaries.append(mobile_value)
                mobile_hash = _lookup_hash(mobile_value, lookup_secret)
                mobile_ct = _encrypt(mobile_value, encryption_secret)
            connection.execute(
                text("INSERT INTO users (id,role,status) VALUES (:id,'student','active')"),
                {"id": user_id},
            )
            connection.execute(
                text(
                    "INSERT INTO student_registrations "
                    "(id,user_id,first_name,last_name,mobile_hash,mobile_ct,dob_ct,dob_hash,"
                    "key_version,status,is_minor,idempotency_key) VALUES "
                    "(:id,:user_id,'Gate','Fixture',:mobile_hash,:mobile_ct,:dob_ct,:dob_hash,"
                    ":key_version,:status,false,:idempotency_key)"
                ),
                {
                    "id": registration_id,
                    "user_id": user_id,
                    "mobile_hash": mobile_hash,
                    "mobile_ct": mobile_ct,
                    "dob_ct": dob_ct,
                    "dob_hash": dob_hash,
                    "key_version": key_version,
                    "status": status,
                    "idempotency_key": f"nyay16-gate-{case}",
                },
            )
    return {
        "ids": ids,
        "safe_expected": _lookup_hash(canonical, lookup_secret),
        "verified_expected": _lookup_hash(alternate, lookup_secret),
        "canaries": [
            canonical,
            alternate,
            noncanonical,
            future,
            encryption_secret,
            lookup_secret,
            *mobile_canaries,
        ],
    }


def _aggregate_data(engine: Engine) -> dict[str, Any]:
    """Return only bounded category counts; no IDs, DOBs, hashes or ciphertext."""

    with engine.connect() as connection:
        states = {
            str(state): int(count)
            for state, count in connection.execute(
                text(
                    "SELECT dob_hash_state,count(*) FROM student_registrations "
                    "GROUP BY dob_hash_state ORDER BY dob_hash_state"
                )
            )
        }
        outcomes = {
            f"{outcome}:{reason}": int(count)
            for outcome, reason, count in connection.execute(
                text(
                    "SELECT outcome,reason_code,count(*) FROM registration_dob_reconciliations "
                    "GROUP BY outcome,reason_code ORDER BY outcome,reason_code"
                )
            )
        }
        placeholders = int(
            connection.scalar(
                text("SELECT count(*) FROM student_registrations WHERE dob_hash='[rehash-required]'")
            )
            or 0
        )
        invalid_hashes = int(
            connection.scalar(
                    text(
                        "SELECT count(*) FROM student_registrations "
                        "WHERE dob_hash_state <> 'erased' "
                        "AND dob_hash !~ '^[0-9a-f]{64}$'"
                    )
            )
            or 0
        )
    aggregate = {
        "states": states,
        "reconciliations": outcomes,
        "placeholder_count": placeholders,
        "invalid_hash_count": invalid_hashes,
    }
    return {"counts": aggregate, "fingerprint": _canonical_fingerprint(aggregate)}


def _expected_populated_counts() -> dict[str, Any]:
    return {
        "states": {"erased": 1, "quarantined": 3, "verified": 2},
        "reconciliations": {
            "quarantined:ciphertext_unreadable": 1,
            "quarantined:source_not_canonical_date": 1,
            "quarantined:source_future_date": 1,
            "reconciled:verified_source": 1,
        },
        "placeholder_count": 0,
        "invalid_hash_count": 0,
    }


def _expected_concurrent_counts() -> dict[str, Any]:
    """Writer converts the safe placeholder into an already-valid digest."""

    expected = _expected_populated_counts()
    expected["reconciliations"] = {
        key: value
        for key, value in expected["reconciliations"].items()
        if key != "reconciled:verified_source"
    }
    return expected


def _expected_safe_roundtrip_counts() -> dict[str, Any]:
    """Subset left after synthetic live quarantines are safely retired."""

    return {
        "states": {"erased": 1, "verified": 2},
        "reconciliations": {"reconciled:verified_source": 1},
        "placeholder_count": 0,
        "invalid_hash_count": 0,
    }


def _values_match_without_export(engine: Engine, seed: dict[str, Any]) -> bool:
    """Compare protected values inside SQL/Python without returning them."""

    with engine.connect() as connection:
        safe_ok = connection.scalar(
            text("SELECT dob_hash=:expected FROM student_registrations WHERE id=:id"),
            {"expected": seed["safe_expected"], "id": seed["ids"]["safe"]},
        )
        existing_ok = connection.scalar(
            text("SELECT dob_hash=:expected FROM student_registrations WHERE id=:id"),
            {"expected": seed["verified_expected"], "id": seed["ids"]["verified"]},
        )
    return bool(safe_ok and existing_ok)


def _run_empty_lifecycle(url: str, env: dict[str, str]) -> dict[str, Any]:
    if _run_alembic(url, env, "upgrade", PARENT).returncode != 0:
        return {"ok": False, "stage": "upgrade_parent"}
    engine = create_engine(url, pool_pre_ping=True)
    try:
        parent_before = _schema_fingerprint(engine)
        up = _run_alembic(url, env, "upgrade", HEAD).returncode
        check = _run_alembic(url, env, "check").returncode
        head_up = _head(engine)
        with engine.connect() as connection:
            pgvector_version = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            )
        schema_up = _schema_fingerprint(engine)
        down = _run_alembic(url, env, "downgrade", PARENT).returncode
        head_down = _head(engine)
        parent_after = _schema_fingerprint(engine)
        reup = _run_alembic(url, env, "upgrade", HEAD).returncode
        recheck = _run_alembic(url, env, "check").returncode
        head_reup = _head(engine)
        schema_reup = _schema_fingerprint(engine)
        return {
            "ok": (
                up == check == down == reup == recheck == 0
                and head_up == head_reup == HEAD
                and head_down == PARENT
                and bool(pgvector_version)
                and parent_before == parent_after
                and schema_up == schema_reup
            ),
            "return_codes": [up, check, down, reup, recheck],
            "parent_schema_stable": parent_before == parent_after,
            "head_schema_stable": schema_up == schema_reup,
            "pgvector_version": pgvector_version,
            "parent_schema_fingerprint": parent_before,
            "head_schema_fingerprint": schema_up,
        }
    finally:
        engine.dispose()


def _run_populated_lifecycle(url: str, env: dict[str, str]) -> dict[str, Any]:
    if _run_alembic(url, env, "upgrade", PARENT).returncode != 0:
        return {"upgrade_ok": False, "roundtrip_ok": False, "stage": "upgrade_parent", "canaries": []}
    engine = create_engine(url, pool_pre_ping=True)
    try:
        seed = _seed_rows(engine, env["REGISTRATION_SECRET"], env["REGISTRATION_LOOKUP_SECRET"])
        operator_preflight_passed = _operator_preflight_matches(
            url,
            env,
            returncode=0,
            payload={
                "code": "migration_ready",
                "erased": 1,
                "quarantined": 3,
                "reconciled": 1,
                "revision": HEAD,
                "rows": 6,
                "verdict": "PASS",
                "verified": 2,
            },
        )
        up = _run_alembic(url, env, "upgrade", HEAD).returncode
        check = _run_alembic(url, env, "check").returncode
        if up != 0:
            return {"upgrade_ok": False, "roundtrip_ok": False, "return_codes": [up, check], "canaries": seed["canaries"]}
        first = _aggregate_data(engine)
        protected_values_ok = _values_match_without_export(engine, seed)
        head_schema_before_rejected_down = _schema_fingerprint(engine)
        head_data_before_rejected_down = _registration_data_fingerprint(engine)
        rejected_down = _run_alembic(url, env, "downgrade", PARENT).returncode
        rejected_down_unchanged = (
            rejected_down != 0
            and _head(engine) == HEAD
            and _schema_fingerprint(engine) == head_schema_before_rejected_down
            and _registration_data_fingerprint(engine) == head_data_before_rejected_down
            and _aggregate_data(engine) == first
        )
        # The synthetic invalid rows are terminal quarantines. Retire them in
        # this disposable database before proving that the remaining populated,
        # safe reconciliation can still downgrade and deterministically re-run.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM student_registrations "
                    "WHERE dob_hash_state='quarantined'"
                )
            )
        safe_first = _aggregate_data(engine)
        down = _run_alembic(url, env, "downgrade", PARENT).returncode
        with engine.connect() as connection:
            placeholder_after_down = int(
                connection.scalar(
                    text("SELECT count(*) FROM student_registrations WHERE dob_hash='[rehash-required]'")
                )
                or 0
            )
        reup = _run_alembic(url, env, "upgrade", HEAD).returncode
        recheck = _run_alembic(url, env, "check").returncode
        second = _aggregate_data(engine) if reup == 0 else {"counts": {}, "fingerprint": ""}
        expected = _expected_populated_counts()
        safe_expected = _expected_safe_roundtrip_counts()
        return {
            "upgrade_ok": (
                operator_preflight_passed
                and up == check == 0
                and first["counts"] == expected
                and protected_values_ok
            ),
            "roundtrip_ok": (
                rejected_down_unchanged
                and down == reup == recheck == 0
                and placeholder_after_down == 1
                and safe_first["counts"] == safe_expected
                and safe_first == second
                and _head(engine) == HEAD
            ),
            "return_codes": [up, check, rejected_down, down, reup, recheck],
            "operator_preflight_passed": operator_preflight_passed,
            "counts": first["counts"],
            "data_fingerprint": first["fingerprint"],
            "protected_values_match": protected_values_ok,
            "live_quarantine_downgrade_rejected": rejected_down != 0,
            "rejected_downgrade_unchanged": rejected_down_unchanged,
            "downgrade_placeholder_count": placeholder_after_down,
            "safe_subset_data_fingerprint": safe_first["fingerprint"],
            "reupgrade_stable": safe_first == second,
            "canaries": seed["canaries"],
        }
    finally:
        engine.dispose()


def _run_ambiguous(url: str, env: dict[str, str]) -> dict[str, Any]:
    if _run_alembic(url, env, "upgrade", PARENT).returncode != 0:
        return {"ok": False, "stage": "upgrade_parent", "canaries": []}
    engine = create_engine(url, pool_pre_ping=True)
    try:
        cases: list[dict[str, Any]] = []
        canaries: list[str] = []

        def prove_failed_unchanged(label: str, attempt_env: dict[str, str]) -> bool:
            operator_preflight_rejected = _operator_preflight_matches(
                url,
                attempt_env,
                returncode=1,
                payload={
                    "code": "preflight_rejected",
                    "revision": HEAD,
                    "verdict": "FAIL",
                },
            )
            before_schema = _schema_fingerprint(engine)
            before_data = _registration_data_fingerprint(engine)
            attempt = _run_alembic(url, attempt_env, "upgrade", HEAD).returncode
            after_schema = _schema_fingerprint(engine)
            after_data = _registration_data_fingerprint(engine)
            shape = _nyay16_shape(engine)
            ok = (
                operator_preflight_rejected
                and attempt != 0
                and _head(engine) == PARENT
                and before_schema == after_schema
                and before_data == after_data
                and not any(shape.values())
            )
            cases.append(
                {
                    "case": label,
                    "status": "PASS" if ok else "FAIL",
                    "operator_preflight_rejected": operator_preflight_rejected,
                    "upgrade_return_code_nonzero": attempt != 0,
                    "schema_unchanged": before_schema == after_schema,
                    "data_unchanged": before_data == after_data,
                    "schema_fingerprint": before_schema,
                    "data_fingerprint": before_data,
                    "nyay16_shape": shape,
                }
            )
            return ok

        # Invalid digest shape is neither a historical placeholder nor a
        # trustworthy digest.  It is ambiguity, not a quarantine candidate.
        seed = _seed_rows(
            engine,
            env["REGISTRATION_SECRET"],
            env["REGISTRATION_LOOKUP_SECRET"],
            include_mismatch=True,
        )
        canaries.extend(seed["canaries"])
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE student_registrations SET dob_hash='unexpected-shape'")
            )
        if prove_failed_unchanged("unexpected_hash_shape", env):
            _clear_seed_rows(engine)

        # A syntactically valid digest that contradicts decryptable source data
        # must fail rather than overwrite deployed data.
        if (
            all(row["status"] == "PASS" for row in cases)
            and not any(_nyay16_shape(engine).values())
            and _head(engine) == PARENT
        ):
            seed = _seed_rows(
                engine,
                env["REGISTRATION_SECRET"],
                env["REGISTRATION_LOOKUP_SECRET"],
                include_mismatch=True,
            )
            canaries.extend(seed["canaries"])
            if prove_failed_unchanged("hash_cipher_mismatch", env):
                _clear_seed_rows(engine)

        # Missing declared provenance is schema/data drift.  A genuinely named
        # but unavailable old key is also a runtime-configuration failure; an
        # empty declaration is independently rejected here.
        if (
            all(row["status"] == "PASS" for row in cases)
            and not any(_nyay16_shape(engine).values())
            and _head(engine) == PARENT
        ):
            seed = _seed_rows(
                engine, env["REGISTRATION_SECRET"], env["REGISTRATION_LOOKUP_SECRET"]
            )
            canaries.extend(seed["canaries"])
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE student_registrations SET key_version='' WHERE id=:id"),
                    {"id": seed["ids"]["safe"]},
                )
            if prove_failed_unchanged("missing_declared_key_version", env):
                _clear_seed_rows(engine)

        # Configuration version names are identifiers, not display text.  A
        # padded active version must fail before DDL rather than silently bind
        # the same key bytes to a normalized version.
        if (
            all(row["status"] == "PASS" for row in cases)
            and not any(_nyay16_shape(engine).values())
            and _head(engine) == PARENT
        ):
            seed = _seed_rows(
                engine, env["REGISTRATION_SECRET"], env["REGISTRATION_LOOKUP_SECRET"]
            )
            canaries.extend(seed["canaries"])
            padded_version_env = {**env, "REGISTRATION_KEY_VERSION": " v1 "}
            if prove_failed_unchanged("padded_active_key_version", padded_version_env):
                _clear_seed_rows(engine)

        # Deleted rows are authoritative only as the exact retention-erased
        # tuple.  A partially deleted registration must never be rewritten or
        # reclassified by this migration.
        if (
            all(row["status"] == "PASS" for row in cases)
            and not any(_nyay16_shape(engine).values())
            and _head(engine) == PARENT
        ):
            seed = _seed_rows(
                engine, env["REGISTRATION_SECRET"], env["REGISTRATION_LOOKUP_SECRET"]
            )
            canaries.extend(seed["canaries"])
            with engine.begin() as connection:
                connection.execute(
                    text("UPDATE student_registrations SET status='deleted' WHERE id=:id"),
                    {"id": seed["ids"]["safe"]},
                )
            if prove_failed_unchanged("partial_deleted_tuple", env):
                _clear_seed_rows(engine)

        if (
            all(row["status"] == "PASS" for row in cases)
            and not any(_nyay16_shape(engine).values())
            and _head(engine) == PARENT
        ):
            seed = _seed_rows(
                engine, env["REGISTRATION_SECRET"], env["REGISTRATION_LOOKUP_SECRET"]
            )
            canaries.extend(seed["canaries"])
            unavailable_ciphertext = _encrypt("2001-02-03", "unavailable-key", "v0")
            canaries.append(unavailable_ciphertext)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE student_registrations SET dob_ct=:ciphertext,key_version='v0' "
                        "WHERE id=:id"
                    ),
                    {"ciphertext": unavailable_ciphertext, "id": seed["ids"]["safe"]},
                )
            if prove_failed_unchanged("unavailable_declared_key", env):
                _clear_seed_rows(engine)

        # With every active DOB hash still a placeholder, the independently
        # authoritative mobile ciphertext/hash pair detects a lookup-secret
        # mismatch.  The absence of a valid DOB digest anchor must not turn a
        # wrong lookup key into a bulk rewrite.
        if (
            all(row["status"] == "PASS" for row in cases)
            and not any(_nyay16_shape(engine).values())
            and _head(engine) == PARENT
        ):
            seed = _seed_rows(
                engine, env["REGISTRATION_SECRET"], env["REGISTRATION_LOOKUP_SECRET"]
            )
            canaries.extend(seed["canaries"])
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE student_registrations SET dob_hash='[rehash-required]' "
                        "WHERE status <> 'deleted'"
                    )
                )
            wrong_lookup = secrets.token_urlsafe(32)
            canaries.append(wrong_lookup)
            wrong_lookup_env = {**env, "REGISTRATION_LOOKUP_SECRET": wrong_lookup}
            if prove_failed_unchanged("wrong_lookup_all_placeholders", wrong_lookup_env):
                _clear_seed_rows(engine)

        # Known development defaults are never migration authority.  Seed with
        # those same bytes so this case would otherwise succeed; a pre-DDL
        # failure therefore proves the denylist rather than decryption failure.
        if (
            all(row["status"] == "PASS" for row in cases)
            and not any(_nyay16_shape(engine).values())
            and _head(engine) == PARENT
        ):
            default_encryption = "dev-registration-secret-change-me"
            default_lookup = "dev-registration-lookup-change-me"
            seed = _seed_rows(engine, default_encryption, default_lookup)
            canaries.extend(seed["canaries"])
            default_env = {
                **env,
                "REGISTRATION_SECRET": default_encryption,
                "REGISTRATION_LOOKUP_SECRET": default_lookup,
            }
            if prove_failed_unchanged("development_default_keys", default_env):
                _clear_seed_rows(engine)

        # A wrong deployment-wide keyring is proven with an existing verified
        # row, which can never be reclassified as a corrupt legacy placeholder.
        if (
            all(row["status"] == "PASS" for row in cases)
            and not any(_nyay16_shape(engine).values())
            and _head(engine) == PARENT
        ):
            seed = _seed_rows(
                engine, env["REGISTRATION_SECRET"], env["REGISTRATION_LOOKUP_SECRET"]
            )
            canaries.extend(seed["canaries"])
            wrong_env = {
                **env,
                "REGISTRATION_SECRET": secrets.token_urlsafe(32),
                "REGISTRATION_LOOKUP_SECRET": secrets.token_urlsafe(32),
            }
            canaries.extend(
                [wrong_env["REGISTRATION_SECRET"], wrong_env["REGISTRATION_LOOKUP_SECRET"]]
            )
            prove_failed_unchanged("wrong_keyring", wrong_env)

        expected_labels = {
            "unexpected_hash_shape",
            "hash_cipher_mismatch",
            "missing_declared_key_version",
            "padded_active_key_version",
            "partial_deleted_tuple",
            "unavailable_declared_key",
            "wrong_lookup_all_placeholders",
            "development_default_keys",
            "wrong_keyring",
        }
        return {
            "ok": (
                {row["case"] for row in cases} == expected_labels
                and all(row["status"] == "PASS" for row in cases)
            ),
            "cases": cases,
            "canaries": canaries,
        }
    finally:
        engine.dispose()


def _run_partial_schema(url: str, env: dict[str, str]) -> dict[str, Any]:
    if _run_alembic(url, env, "upgrade", PARENT).returncode != 0:
        return {"ok": False, "stage": "upgrade_parent", "canaries": []}
    engine = create_engine(url, pool_pre_ping=True)
    try:
        seed = _seed_rows(engine, env["REGISTRATION_SECRET"], env["REGISTRATION_LOOKUP_SECRET"])
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE student_registrations ADD COLUMN dob_hash_state varchar(32)")
            )
        before = _schema_fingerprint(engine)
        data_before = _registration_data_fingerprint(engine)
        attempt = _run_alembic(url, env, "upgrade", HEAD).returncode
        after = _schema_fingerprint(engine)
        data_after = _registration_data_fingerprint(engine)
        shape = _nyay16_shape(engine)
        return {
            "ok": (
                attempt != 0
                and _head(engine) == PARENT
                and before == after
                and data_before == data_after
                and shape == {"state_column": True, "reconciliation_table": False}
            ),
            "upgrade_return_code_nonzero": attempt != 0,
            "schema_unchanged": before == after,
            "data_unchanged": data_before == data_after,
            "schema_fingerprint": before,
            "data_fingerprint": data_before,
            "nyay16_shape": shape,
            "canaries": seed["canaries"],
        }
    finally:
        engine.dispose()


def _run_concurrent(url: str, env: dict[str, str]) -> dict[str, Any]:
    if _run_alembic(url, env, "upgrade", PARENT).returncode != 0:
        return {"ok": False, "stage": "upgrade_parent", "canaries": []}
    engine = create_engine(url, pool_pre_ping=True)
    try:
        seed = _seed_rows(engine, env["REGISTRATION_SECRET"], env["REGISTRATION_LOOKUP_SECRET"])
        barrier = engine.connect()
        barrier_tx = barrier.begin()
        outcomes: list[int] = []
        wait_observed = False
        max_waiters = 0
        protected_writer_preserved = False
        try:
            barrier.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _MIGRATION_ADVISORY_LOCK},
            )
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(_run_alembic, url, env, "upgrade", HEAD)
                    for _ in range(2)
                ]
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    with engine.connect() as monitor:
                        waiting = int(
                            monitor.scalar(
                                text(
                                    "SELECT count(*) FROM pg_stat_activity "
                                    "WHERE datname=current_database() "
                                    "AND pid <> pg_backend_pid() "
                                    "AND wait_event_type='Lock'"
                                )
                            )
                            or 0
                        )
                    max_waiters = max(max_waiters, waiting)
                    if waiting >= 1:
                        wait_observed = True
                        break
                    time.sleep(0.05)

                # A real writer changes the protected source and its matching
                # lookup hash while both migrators are observably held behind
                # the migration advisory barrier.  On release, preflight must
                # see the committed pair and neither lose nor rewrite it.
                writer_date = "2002-04-05"
                writer_ciphertext = _encrypt(writer_date, env["REGISTRATION_SECRET"])
                writer_hash = _lookup_hash(writer_date, env["REGISTRATION_LOOKUP_SECRET"])
                seed["canaries"].extend([writer_date, writer_ciphertext, writer_hash])
                with engine.begin() as writer:
                    writer.execute(
                        text(
                            "UPDATE student_registrations SET dob_ct=:ciphertext,"
                            "dob_hash=:digest,key_version='v1' WHERE id=:id"
                        ),
                        {
                            "ciphertext": writer_ciphertext,
                            "digest": writer_hash,
                            "id": seed["ids"]["safe"],
                        },
                    )
                seed["safe_expected"] = writer_hash
                barrier_tx.commit()
                outcomes = [future.result().returncode for future in futures]
        finally:
            if barrier_tx.is_active:
                barrier_tx.rollback()
            barrier.close()
        aggregate = _aggregate_data(engine) if _head(engine) == HEAD else {"counts": {}, "fingerprint": ""}
        expected = _expected_concurrent_counts()
        if _head(engine) == HEAD:
            protected_writer_preserved = _values_match_without_export(engine, seed)
        # A loser may fail closed on a held advisory lock, or may begin after the
        # winner and observe an already-current head.  Both are safe.  What is
        # forbidden is two failures or any partial/forked final state.
        ok = (
            0 in outcomes
            and len(outcomes) == 2
            and wait_observed
            and _head(engine) == HEAD
            and _nyay16_shape(engine) == {"state_column": True, "reconciliation_table": True}
            and aggregate["counts"] == expected
            and protected_writer_preserved
            and _run_alembic(url, env, "check").returncode == 0
        )
        return {
            "ok": ok,
            "outcome_classes": sorted("success" if code == 0 else "fail_closed" for code in outcomes),
            "advisory_lock_wait_observed": wait_observed,
            "maximum_observed_lock_waiters": max_waiters,
            "protected_source_and_hash_commit_preserved": protected_writer_preserved,
            "final_data_fingerprint": aggregate["fingerprint"],
            "canaries": seed["canaries"],
        }
    finally:
        engine.dispose()


def _write_summary(output: Path, payload: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    started_at = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=BACKEND / "test-results" / "nyay16-postgres" / "summary.json",
    )
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        for ident, title in ASSERTION_CONTRACT:
            print(f"{ident} {title}")
        return 0

    database_url = os.getenv("DATABASE_URL", "")
    allowed = is_isolated_control_target(
        database_url, os.getenv("NYAY16_GATE_ALLOW_DATABASES") == "true"
    )
    if not allowed:
        payload = {
            "gate": "nyay16_postgres",
            "status": "BLOCKED",
            "exit_code": BLOCKED,
            "executed": False,
            "reason": "isolated loopback PostgreSQL QA control target or mutation opt-in absent",
        }
        _write_summary(args.output, payload)
        print("BLOCKED: NYAY-16 requires an opted-in loopback PostgreSQL QA control target")
        return BLOCKED

    control = create_engine(database_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with control.connect() as connection:
            server_version_num = int(connection.scalar(text("SHOW server_version_num")))
    except Exception:
        payload = {
            "gate": "nyay16_postgres",
            "status": "BLOCKED",
            "exit_code": BLOCKED,
            "executed": False,
            "reason": "PostgreSQL control connection unavailable",
        }
        _write_summary(args.output, payload)
        print("BLOCKED: PostgreSQL control connection unavailable")
        control.dispose()
        return BLOCKED
    if not is_postgresql_16(server_version_num):
        payload = {
            "gate": "nyay16_postgres",
            "status": "BLOCKED",
            "exit_code": BLOCKED,
            "executed": False,
            "reason": "exact PostgreSQL major 16 prerequisite unavailable",
            "server_version_num": server_version_num,
        }
        _write_summary(args.output, payload)
        print("BLOCKED: exact PostgreSQL major 16 prerequisite unavailable")
        control.dispose()
        return BLOCKED

    run_token = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
    names = {
        kind: f"{_SCRATCH_PREFIX}{run_token}_{kind}"
        for kind in ("empty", "pop", "amb", "drift", "race")
    }
    created: list[str] = []
    cleanup: dict[str, bool] = {}
    results = Results()
    # Whitespace is valid secret material, not cosmetic configuration.  The
    # native success path proves migration key loading preserves exact bytes.
    encryption_secret = f" {secrets.token_urlsafe(32)} "
    lookup_secret = f"\t{secrets.token_urlsafe(32)}\n"
    canaries = [encryption_secret, lookup_secret]
    scenario_reports: dict[str, dict[str, Any]] = {}
    fatal: str | None = None

    try:
        ledger = _run_ledger()
        results.add(
            "N16-PG-02",
            "inherited migration SHA-256 ledger verifies before DB work",
            ledger.returncode == 0,
            {"return_code": ledger.returncode},
        )
        if ledger.returncode != 0:
            fatal = "migration ledger verification failed"
        else:
            for name in names.values():
                _create_database(control, name)
                created.append(name)

            env = _migration_env(database_url, encryption_secret, lookup_secret)
            urls = {kind: _scratch_url(database_url, name) for kind, name in names.items()}
            scenario_reports["empty"] = _run_empty_lifecycle(urls["empty"], env)
            scenario_reports["populated"] = _run_populated_lifecycle(urls["pop"], env)
            scenario_reports["ambiguous"] = _run_ambiguous(urls["amb"], env)
            scenario_reports["drift"] = _run_partial_schema(urls["drift"], env)
            scenario_reports["concurrency"] = _run_concurrent(urls["race"], env)
            for report in scenario_reports.values():
                canaries.extend(report.pop("canaries", []))

            empty = scenario_reports["empty"]
            populated = scenario_reports["populated"]
            ambiguous = scenario_reports["ambiguous"]
            drift = scenario_reports["drift"]
            concurrency = scenario_reports["concurrency"]
            results.add("N16-PG-03", ASSERTION_CONTRACT[2][1], bool(empty.get("ok")), empty)
            results.add("N16-PG-04", ASSERTION_CONTRACT[3][1], bool(populated.get("upgrade_ok")), {
                key: value for key, value in populated.items() if key != "roundtrip_ok"
            })
            results.add("N16-PG-05", ASSERTION_CONTRACT[4][1], bool(populated.get("roundtrip_ok")), {
                "return_codes": populated.get("return_codes"),
                "live_quarantine_downgrade_rejected": populated.get(
                    "live_quarantine_downgrade_rejected"
                ),
                "rejected_downgrade_unchanged": populated.get(
                    "rejected_downgrade_unchanged"
                ),
                "downgrade_placeholder_count": populated.get("downgrade_placeholder_count"),
                "reupgrade_stable": populated.get("reupgrade_stable"),
                "safe_subset_data_fingerprint": populated.get(
                    "safe_subset_data_fingerprint"
                ),
            })
            results.add("N16-PG-06", ASSERTION_CONTRACT[5][1], bool(ambiguous.get("ok")), ambiguous)
            results.add("N16-PG-07", ASSERTION_CONTRACT[6][1], bool(drift.get("ok")), drift)
            results.add("N16-PG-08", ASSERTION_CONTRACT[7][1], bool(concurrency.get("ok")), concurrency)
    except subprocess.TimeoutExpired:
        fatal = "bounded subprocess timeout"
    except Exception as exc:
        # Exception type is diagnostic enough and cannot contain operator data.
        fatal = f"gate exception class: {type(exc).__name__}"
    finally:
        control.dispose()
        # Re-open a short-lived control engine after scenario engines have been
        # disposed.  Termination before DROP also handles a crashed subprocess.
        cleanup_control = create_engine(
            database_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True
        )
        try:
            for name in reversed(created):
                cleanup[name] = _drop_database(cleanup_control, name)
        finally:
            cleanup_control.dispose()

    # Runtime/extension proof is earned by the empty migration: 0001 must create
    # pgvector successfully for that scenario to pass.  Record only the numeric
    # server version and whether the real migration path completed.
    empty_report = scenario_reports.get("empty", {})
    results.add(
        "N16-PG-01",
        ASSERTION_CONTRACT[0][1],
        is_postgresql_16(server_version_num)
        and bool(empty_report.get("ok"))
        and bool(empty_report.get("pgvector_version")),
        {
            "server_version_num": server_version_num,
            "pgvector_version": empty_report.get("pgvector_version"),
        },
    )

    cleanup_ok = len(cleanup) == len(created) and all(cleanup.values())
    results.add(
        "N16-PG-10",
        ASSERTION_CONTRACT[9][1],
        cleanup_ok,
        {"created_count": len(created), "removed_count": sum(cleanup.values())},
    )
    # A report that executed against PostgreSQL always has the complete unique
    # contract, including explicit NOT_EXECUTED failures after an early stop.
    # Absence can therefore never be mistaken for a pass by downstream policy.
    present = {row["id"] for row in results.rows}
    for ident, title in ASSERTION_CONTRACT:
        if ident not in present and ident != "N16-PG-09":
            results.add(
                ident,
                title,
                False,
                {"not_executed_reason": fatal or "an earlier gate prerequisite failed"},
            )
    provisional = {
        "gate": "nyay16_postgres",
        "head": HEAD,
        "parent": PARENT,
        "executed": True,
        "assertions": results.rows,
        "fatal": fatal,
    }
    hits = privacy_canary_hits(provisional, canaries)
    results.add(
        "N16-PG-09",
        ASSERTION_CONTRACT[8][1],
        not hits,
        {"canary_hit_labels": hits},
    )
    by_id = {row["id"]: row for row in results.rows}
    results.rows = [by_id[ident] for ident, _ in ASSERTION_CONTRACT]
    passed = results.ok and fatal is None
    payload = {
        "gate": "nyay16_postgres",
        "head": HEAD,
        "parent": PARENT,
        "status": "PASS" if passed else "FAIL",
        "exit_code": 0 if passed else 1,
        "executed": True,
        "duration_seconds": round(time.monotonic() - started_at, 3),
        "fatal": fatal,
        "assertions": results.rows,
    }
    _write_summary(args.output, payload)
    print(f"nyay16_postgres_gate: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
