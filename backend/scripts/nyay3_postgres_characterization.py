"""NYAY-3 PostgreSQL 16 cardinality/concurrency characterization gate.

This is an explicitly opt-in, disposable-database gate.  It does not run in the
ordinary SQLite pytest suite and it never mutates the database named by
``--database-url``: that URL is used only to create a uniquely named scratch
database, migrate the scratch database, run the probes, and drop it.

Before the NYAY-3 migration exists, run with ``--expect current-vulnerable``.
That mode passes only when the inherited defects are actually reproduced and
labels the result ``PASS_RED_BASELINE``.  It is not fix-verification evidence.
After the migration and locking changes exist, the same gate must be run with
``--expect hardened``; that mode requires database rejections and the exact
target index/constraint inventory.

Exit codes:

* 0: the selected expectation was proved;
* 1: a product assertion or harness assertion failed;
* 78: PostgreSQL 16/pgvector or scratch-database authority was unavailable.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import create_engine, make_url, select, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
BLOCKED_EXIT = 78
WORKERS = 8

TARGET_INDEXES = (
    "uq_otp_challenges_one_active_per_registration_purpose",
    "uq_auth_sessions_one_active_per_user",
)
TARGET_CONSTRAINTS = (
    "uq_guardian_consents_registration_id",
    "uq_student_verifications_registration_id",
    "ck_guardian_consents_verified_matches_status",
)
TARGET_INDEX_DEFINITIONS = {
    "uq_otp_challenges_one_active_per_registration_purpose": {
        "columns": ("registration_id", "purpose"),
        "predicate": "consumed_at is null",
    },
    "uq_auth_sessions_one_active_per_user": {
        "columns": ("user_id",),
        "predicate": "status = 'active'",
    },
}
GUARDIAN_STATE_SQL = (
    "(status = 'verified' AND verified = true) OR "
    "(status IN ('pending', 'sent', 'rejected') AND verified = false)"
)
TARGET_CONSTRAINT_DEFINITIONS = {
    "uq_guardian_consents_registration_id": {
        "type": "u",
        "columns": ("registration_id",),
    },
    "uq_student_verifications_registration_id": {
        "type": "u",
        "columns": ("registration_id",),
    },
    "ck_guardian_consents_verified_matches_status": {
        "type": "c",
        "columns": ("status", "verified"),
        "definition": GUARDIAN_STATE_SQL,
    },
}
RACE_CONSTRAINTS = {
    "otp": "uq_otp_challenges_one_active_per_registration_purpose",
    "session": "uq_auth_sessions_one_active_per_user",
    "guardian": "uq_guardian_consents_registration_id",
    "verification": "uq_student_verifications_registration_id",
}
GUARDIAN_STATE_CASES = (
    ("verified_true", "verified", True, True),
    ("verified_false", "verified", False, False),
    ("pending_false", "pending", False, True),
    ("pending_true", "pending", True, False),
    ("sent_false", "sent", False, True),
    ("sent_true", "sent", True, False),
    ("rejected_false", "rejected", False, True),
    ("rejected_true", "rejected", True, False),
)


class Blocked(RuntimeError):
    """The target runtime could not be exercised; this is never a pass."""


def _safe_local_postgres_url(raw: str) -> URL:
    """Accept only a loopback PostgreSQL URL and never echo its credentials."""

    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        raise Blocked("a PostgreSQL URL is required")
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
    admin = create_engine(
        _database_url(base, "postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(statement))
    finally:
        admin.dispose()


def _drop_scratch(base: URL, name: str) -> None:
    # ``name`` is generated from a fixed prefix plus uuid.hex, not user input.
    try:
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:  # pragma: no cover - PostgreSQL <13 fallback
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}"')


def _create_scratch(base: URL, name: str) -> str:
    try:
        _drop_scratch(base, name)
        _admin_execute(base, f'CREATE DATABASE "{name}"')
    except Exception as exc:  # noqa: BLE001 - classified as a blocked runtime
        raise Blocked("could not create the disposable scratch database") from exc
    return _database_url(base, name)


def _run_alembic(scratch_url: str, *arguments: str) -> dict[str, Any]:
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env={
            **os.environ,
            "APP_ENV": "testing",
            "DATABASE_URL": scratch_url,
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    # Do not copy subprocess output into evidence: a driver error can include a
    # credential-bearing URL.  The command tokens and return code distinguish
    # migration failure from probe failure without retaining that risk.
    return {
        "arguments": list(arguments),
        "returncode": result.returncode,
    }


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


def _normalize_predicate(value: object) -> str:
    """Canonicalize the simple immutable predicates owned by NYAY-3.

    PostgreSQL may reflect varchar comparisons with explicit casts and may put
    parentheses around a column reference.  Remove only those representation
    details; do not simplify boolean expressions or reorder terms.
    """

    normalized, literals = _protect_sql_literals(value)
    normalized = normalized.strip().lower().replace('"', "")
    normalized = re.sub(
        r"::(?:text|character varying|varchar)(?:\([0-9]+\))?",
        "",
        normalized,
    )
    normalized = re.sub(r"\(([a-z_][a-z0-9_]*)\)", r"\1", normalized)
    for _attempt in range(4):
        if normalized.startswith("(") and normalized.endswith(")"):
            normalized = normalized[1:-1].strip()
        else:
            break
    normalized = " ".join(normalized.split())
    for token, literal in literals.items():
        normalized = normalized.replace(token, literal)
    return normalized


def _normalize_constraint_definition(value: object) -> str:
    """Canonicalize the exact guardian CHECK without changing literals."""

    normalized, literals = _protect_sql_literals(value)
    normalized = normalized.lower()
    normalized = re.sub(
        r"::(?:text|character varying|varchar)(?:\([0-9]+\))?",
        "",
        normalized,
    )
    normalized = re.sub(r"[\s()\"\[\]]+", "", normalized)
    normalized = normalized.replace("=anyarray", "in")
    if normalized.startswith("check"):
        normalized = normalized[5:]
    for token, literal in literals.items():
        normalized = normalized.replace(token, literal)
    return normalized


def _runtime_inventory(engine: Engine) -> dict[str, Any]:
    with engine.connect() as connection:
        server_version_num = int(connection.scalar(text("SHOW server_version_num")))
        vector_version = connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        indexes = {
            row.indexname: row.indexdef
            for row in connection.execute(
                text(
                    """
                    SELECT indexname, indexdef
                    FROM pg_indexes
                    WHERE schemaname = current_schema()
                      AND tablename IN ('otp_challenges', 'auth_sessions',
                                        'guardian_consents', 'student_verifications')
                    ORDER BY indexname
                    """
                )
            )
        }
        constraints = {
            row.conname: row.definition
            for row in connection.execute(
                text(
                    """
                    SELECT c.conname, pg_get_constraintdef(c.oid) AS definition
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    JOIN pg_namespace n ON n.oid = t.relnamespace
                    WHERE n.nspname = current_schema()
                      AND t.relname IN ('otp_challenges', 'auth_sessions',
                                        'guardian_consents', 'student_verifications')
                    ORDER BY c.conname
                    """
                )
            )
        }
        index_details = {
            row.index_name: {
                "unique": bool(row.is_unique),
                "columns": list(row.key_columns or []),
                "predicate": _normalize_predicate(row.predicate),
            }
            for row in connection.execute(
                text(
                    """
                    SELECT idx.relname AS index_name,
                           ix.indisunique AS is_unique,
                           ARRAY(
                               SELECT att.attname
                               FROM unnest(ix.indkey) WITH ORDINALITY
                                    AS key_column(attnum, position)
                               JOIN pg_attribute att
                                 ON att.attrelid = tbl.oid
                                AND att.attnum = key_column.attnum
                               WHERE key_column.position <= ix.indnkeyatts
                               ORDER BY key_column.position
                           ) AS key_columns,
                           pg_get_expr(ix.indpred, ix.indrelid, true) AS predicate
                    FROM pg_index ix
                    JOIN pg_class idx ON idx.oid = ix.indexrelid
                    JOIN pg_class tbl ON tbl.oid = ix.indrelid
                    JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
                    WHERE ns.nspname = current_schema()
                      AND idx.relname IN (
                          'uq_otp_challenges_one_active_per_registration_purpose',
                          'uq_auth_sessions_one_active_per_user'
                      )
                    ORDER BY idx.relname
                    """
                )
            )
        }
        constraint_details = {
            row.constraint_name: {
                "type": row.constraint_type,
                "columns": list(row.columns or []),
                "definition": row.definition,
            }
            for row in connection.execute(
                text(
                    """
                    SELECT c.conname AS constraint_name,
                           c.contype AS constraint_type,
                           ARRAY(
                               SELECT att.attname
                               FROM unnest(c.conkey) WITH ORDINALITY
                                    AS key_column(attnum, position)
                               JOIN pg_attribute att
                                 ON att.attrelid = tbl.oid
                                AND att.attnum = key_column.attnum
                               ORDER BY key_column.position
                           ) AS columns,
                           pg_get_constraintdef(c.oid, true) AS definition
                    FROM pg_constraint c
                    JOIN pg_class tbl ON tbl.oid = c.conrelid
                    JOIN pg_namespace ns ON ns.oid = tbl.relnamespace
                    WHERE ns.nspname = current_schema()
                      AND c.conname IN (
                          'uq_guardian_consents_registration_id',
                          'uq_student_verifications_registration_id',
                          'ck_guardian_consents_verified_matches_status'
                      )
                    ORDER BY c.conname
                    """
                )
            )
        }
    target_index_semantics = {
        name: bool(
            (detail := index_details.get(name))
            and detail["unique"] is True
            and tuple(detail["columns"]) == expected["columns"]
            and detail["predicate"] == expected["predicate"]
        )
        for name, expected in TARGET_INDEX_DEFINITIONS.items()
    }
    target_constraint_semantics = {}
    for name, expected in TARGET_CONSTRAINT_DEFINITIONS.items():
        detail = constraint_details.get(name)
        columns = tuple(detail["columns"]) if detail else ()
        columns_match = (
            set(columns) == set(expected["columns"])
            if expected["type"] == "c"
            else columns == expected["columns"]
        )
        definition_match = (
            _normalize_constraint_definition(detail["definition"])
            == _normalize_constraint_definition(expected["definition"])
            if detail and expected["type"] == "c"
            else True
        )
        target_constraint_semantics[name] = bool(
            detail
            and detail["type"] == expected["type"]
            and columns_match
            and definition_match
        )
    return {
        "server_version_num": server_version_num,
        "postgresql_16_or_newer": server_version_num >= 160000,
        "pgvector_version": vector_version,
        "alembic_revision": revision,
        "indexes": indexes,
        "constraints": constraints,
        "index_details": index_details,
        "constraint_details": constraint_details,
        "target_indexes_present": {
            name: name in indexes for name in TARGET_INDEXES
        },
        "target_constraints_present": {
            name: name in constraints for name in TARGET_CONSTRAINTS
        },
        "target_index_semantics": target_index_semantics,
        "target_constraint_semantics": target_constraint_semantics,
    }


def _seed_registration(
    engine: Engine,
    *,
    user_id: uuid.UUID,
    registration_id: uuid.UUID,
    discriminator: str,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO users (id, role, status)
                VALUES (:id, 'student', 'active')
                """
            ),
            {"id": user_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO student_registrations (
                    id, user_id, first_name, last_name, mobile_hash, mobile_ct,
                    dob_hash, dob_ct, dob_hash_state, key_version, status, is_minor
                ) VALUES (
                    :id, :user_id, 'NYAY3', 'Probe', :mobile_hash,
                    :mobile_ct, :dob_hash, :dob_ct, 'verified', 'v1', 'active', false
                )
                """
            ),
            {
                "id": registration_id,
                "user_id": user_id,
                "mobile_hash": (discriminator * 64)[:64],
                "mobile_ct": f"qa:{discriminator}:ciphertext",
                "dob_hash": ((discriminator[::-1] or "d") * 64)[:64],
                "dob_ct": f"qa:{discriminator}:dob-ciphertext",
            },
        )


def _constraint_name(exc: IntegrityError) -> str | None:
    diagnostic = getattr(exc.orig, "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def _insert_worker(
    scratch_url: str,
    kind: str,
    index: int,
    barrier: threading.Barrier,
    ids: dict[str, uuid.UUID],
) -> dict[str, Any]:
    """Run one transaction on one physical PostgreSQL connection."""

    engine = create_engine(scratch_url, poolclass=NullPool)
    result: dict[str, Any] = {"worker": index, "outcome": "unstarted"}
    now = datetime.now(timezone.utc)
    row_id = uuid.uuid4()
    try:
        with engine.begin() as connection:
            result["backend_pid"] = connection.scalar(text("SELECT pg_backend_pid()"))
            barrier.wait(timeout=30)
            if kind == "otp":
                connection.execute(
                    text(
                        """
                        INSERT INTO otp_challenges (
                            id, registration_id, purpose, verifier_hash,
                            attempts, max_attempts, expires_at
                        ) VALUES (
                            :id, :registration_id, 'login', :verifier_hash,
                            0, 3, :expires_at
                        )
                        """
                    ),
                    {
                        "id": row_id,
                        "registration_id": ids["otp_registration"],
                        "verifier_hash": f"{index:064x}",
                        "expires_at": now + timedelta(minutes=5),
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO otp_outbox (
                            id, challenge_id, destination_ct, code_ct,
                            key_version, purpose, status, attempts
                        ) VALUES (
                            :id, :challenge_id, :destination_ct, :code_ct,
                            'v1', 'login', 'pending', 0
                        )
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "challenge_id": row_id,
                        "destination_ct": f"qa:destination:{index}",
                        "code_ct": f"qa:code:{index}",
                    },
                )
            elif kind == "session":
                connection.execute(
                    text(
                        """
                        INSERT INTO auth_sessions (
                            id, user_id, token_hash, status, expires_at,
                            last_seen_at
                        ) VALUES (
                            :id, :user_id, :token_hash, 'active', :expires_at,
                            :last_seen_at
                        )
                        """
                    ),
                    {
                        "id": row_id,
                        "user_id": ids["session_user"],
                        "token_hash": f"{index + 100:064x}",
                        "expires_at": now + timedelta(hours=1),
                        "last_seen_at": now,
                    },
                )
            elif kind == "guardian":
                connection.execute(
                    text(
                        """
                        INSERT INTO guardian_consents (
                            id, registration_id, status, verified
                        ) VALUES (:id, :registration_id, 'pending', false)
                        """
                    ),
                    {"id": row_id, "registration_id": ids["guardian_registration"]},
                )
            elif kind == "verification":
                connection.execute(
                    text(
                        """
                        INSERT INTO student_verifications (
                            id, registration_id, method, status
                        ) VALUES (
                            :id, :registration_id, 'institutional_email', 'pending'
                        )
                        """
                    ),
                    {"id": row_id, "registration_id": ids["verification_registration"]},
                )
            else:  # pragma: no cover - programming error
                raise AssertionError(f"unknown race kind: {kind}")
        result["outcome"] = "inserted"
    except IntegrityError as exc:
        result["outcome"] = "constraint_rejected"
        result["constraint"] = _constraint_name(exc)
    except Exception as exc:  # noqa: BLE001 - reported as a harness failure
        result["outcome"] = "unexpected_error"
        result["error_type"] = type(exc).__name__
    finally:
        engine.dispose()
    return result


def _run_race(
    scratch_url: str,
    kind: str,
    workers: int,
    ids: dict[str, uuid.UUID],
) -> list[dict[str, Any]]:
    barrier = threading.Barrier(workers)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(
            pool.map(
                lambda index: _insert_worker(
                    scratch_url, kind, index, barrier, ids
                ),
                range(workers),
            )
        )
    return sorted(results, key=lambda item: item["worker"])


def _summarize_race(
    engine: Engine,
    *,
    kind: str,
    results: list[dict[str, Any]],
    ids: dict[str, uuid.UUID],
) -> dict[str, Any]:
    count_sql = {
        "otp": """
            SELECT count(*)
            FROM otp_challenges c
            JOIN otp_outbox o ON o.challenge_id = c.id
            WHERE c.registration_id = :owner_id
              AND c.purpose = 'login'
              AND c.consumed_at IS NULL
              AND o.status = 'pending'
              AND o.code_ct IS NOT NULL
        """,
        "session": """
            SELECT count(*) FROM auth_sessions
            WHERE user_id = :owner_id AND status = 'active'
        """,
        "guardian": """
            SELECT count(*) FROM guardian_consents
            WHERE registration_id = :owner_id
        """,
        "verification": """
            SELECT count(*) FROM student_verifications
            WHERE registration_id = :owner_id
        """,
    }[kind]
    owner_id = {
        "otp": ids["otp_registration"],
        "session": ids["session_user"],
        "guardian": ids["guardian_registration"],
        "verification": ids["verification_registration"],
    }[kind]
    with engine.connect() as connection:
        persisted = int(
            connection.scalar(text(count_sql), {"owner_id": owner_id}) or 0
        )
    outcomes = [item["outcome"] for item in results]
    pids = sorted(
        {item["backend_pid"] for item in results if item.get("backend_pid")}
    )
    return {
        "workers": len(results),
        "distinct_backend_pids": pids,
        "inserted": outcomes.count("inserted"),
        "constraint_rejected": outcomes.count("constraint_rejected"),
        "unexpected_error": outcomes.count("unexpected_error"),
        "persisted_rows": persisted,
        # This is intentionally a multiset, not a set.  Seven rejected workers
        # must identify the intended constraint seven times; one correctly
        # named rejection cannot mask six anonymous or unrelated failures.
        "constraint_names": sorted(
            str(item.get("constraint") or "<missing>")
            for item in results
            if item.get("outcome") == "constraint_rejected"
        ),
    }


def _run_service_race(
    scratch_url: str,
    workers: int,
    operation: Callable[[Session, int], str],
) -> list[dict[str, Any]]:
    """Run one real service transaction per independent PostgreSQL backend."""

    barrier = threading.Barrier(workers)

    def worker(index: int) -> dict[str, Any]:
        engine = create_engine(scratch_url, poolclass=NullPool)
        result: dict[str, Any] = {"worker": index, "outcome": "unstarted"}
        try:
            with Session(engine) as session:
                result["backend_pid"] = session.scalar(text("SELECT pg_backend_pid()"))
                session.execute(text("SET LOCAL lock_timeout = '20s'"))
                session.execute(text("SET LOCAL statement_timeout = '60s'"))
                barrier.wait(timeout=30)
                result["outcome"] = operation(session, index)
        except Exception as exc:  # noqa: BLE001 - classified without detail
            result["outcome"] = "unexpected_error"
            result["error_type"] = type(exc).__name__
        finally:
            engine.dispose()
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(worker, range(workers)))
    return sorted(results, key=lambda item: item["worker"])


def _service_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes: dict[str, int] = {}
    for item in results:
        outcome = str(item["outcome"])
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return {
        "workers": len(results),
        "distinct_backend_pids": sorted(
            {item["backend_pid"] for item in results if item.get("backend_pid")}
        ),
        "outcomes": outcomes,
    }


def _deliverable_inventory(
    engine: Engine,
    registration_id: uuid.UUID,
    purpose: str,
) -> dict[str, int]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT
                    count(*) FILTER (WHERE c.consumed_at IS NULL) AS active,
                    count(*) FILTER (
                        WHERE c.consumed_at IS NULL
                          AND o.status = 'pending'
                          AND o.code_ct IS NOT NULL
                    ) AS deliverable
                FROM otp_challenges c
                LEFT JOIN otp_outbox o ON o.challenge_id = c.id
                WHERE c.registration_id = :registration_id
                  AND c.purpose = :purpose
                """
            ),
            {"registration_id": registration_id, "purpose": purpose},
        ).one()
    return {"active": int(row.active or 0), "deliverable": int(row.deliverable or 0)}


def _seed_login_attempt(
    engine: Engine,
    registration_id: uuid.UUID,
    now: datetime,
) -> tuple[uuid.UUID, uuid.UUID, str, str]:
    from app.core.crypto import otp_verifier
    from app.models.registration import LoginAttempt, OtpChallenge

    code = "654321"
    salt = uuid.uuid4().hex
    with Session(engine) as session:
        challenge = OtpChallenge(
            registration_id=registration_id,
            purpose="login",
            verifier_hash=otp_verifier(code, salt=salt),
            attempts=0,
            max_attempts=3,
            expires_at=now + timedelta(minutes=5),
            metadata_json={"salt": salt, "issued_at": now.isoformat()},
        )
        session.add(challenge)
        session.flush()
        attempt = LoginAttempt(
            opaque_id=uuid.uuid4().hex,
            lookup_hash=f"{991:064x}",
            registration_id=registration_id,
            challenge_id=challenge.id,
            status="pending",
            expires_at=now + timedelta(minutes=10),
        )
        session.add(attempt)
        session.commit()
        return attempt.id, challenge.id, attempt.opaque_id, code


def _outbox_delivery_supersede_probe(
    scratch_url: str,
    engine: Engine,
    registration_id: uuid.UUID,
    now: datetime,
) -> dict[str, Any]:
    """Prove delivery/supersession share challenge -> outbox lock order."""

    from app.services import otp_outbox, otp_service

    with Session(engine) as session:
        _challenge, intent = otp_service.issue_challenge(
            session,
            registration_id,
            now,
            purpose="signup",
            destination="9000000000",
        )
        session.commit()

    sender_started = threading.Event()
    sender_release = threading.Event()
    supersede_started = threading.Event()
    pids: dict[str, int] = {}
    sender_attempts = 0

    class BlockingSender:
        def send(self, _destination: str, _code: str) -> None:
            nonlocal sender_attempts
            sender_started.set()
            if not sender_release.wait(timeout=30):
                raise RuntimeError("bounded sender release was not observed")
            sender_attempts += 1

    def delivery() -> str:
        local_engine = create_engine(scratch_url, poolclass=NullPool)
        try:
            with Session(local_engine) as session:
                pids["delivery"] = int(
                    session.scalar(text("SELECT pg_backend_pid()"))
                )
                session.execute(text("SET LOCAL lock_timeout = '20s'"))
                session.execute(text("SET LOCAL statement_timeout = '60s'"))
                delivered = otp_outbox.run_delivery(
                    session,
                    intent,
                    BlockingSender(),
                    raise_on_failure=True,
                )
                return "success" if delivered else "not_delivered"
        except Exception as exc:  # noqa: BLE001 - bounded type only
            return f"unexpected_error:{type(exc).__name__}"
        finally:
            local_engine.dispose()

    def supersede() -> str:
        local_engine = create_engine(scratch_url, poolclass=NullPool)
        try:
            with Session(local_engine) as session:
                pids["supersede"] = int(
                    session.scalar(text("SELECT pg_backend_pid()"))
                )
                session.execute(text("SET LOCAL lock_timeout = '20s'"))
                session.execute(text("SET LOCAL statement_timeout = '60s'"))
                supersede_started.set()
                otp_service.issue_challenge(
                    session,
                    registration_id,
                    now + timedelta(seconds=31),
                    purpose="signup",
                    destination="9000000000",
                )
                session.commit()
                return "success"
        except Exception as exc:  # noqa: BLE001 - bounded type only
            return f"unexpected_error:{type(exc).__name__}"
        finally:
            local_engine.dispose()

    lock_wait_observed = False
    with ThreadPoolExecutor(max_workers=2) as pool:
        delivery_future = pool.submit(delivery)
        if not sender_started.wait(timeout=30):
            sender_release.set()
            raise RuntimeError("delivery did not reach bounded sender seam")
        supersede_future = pool.submit(supersede)
        if not supersede_started.wait(timeout=30):
            sender_release.set()
            raise RuntimeError("supersession did not start")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            supersede_pid = pids.get("supersede")
            if supersede_pid is not None:
                with engine.connect() as connection:
                    wait_type = connection.scalar(
                        text(
                            "SELECT wait_event_type FROM pg_stat_activity "
                            "WHERE pid=:pid"
                        ),
                        {"pid": supersede_pid},
                    )
                if wait_type == "Lock":
                    lock_wait_observed = True
                    break
            time.sleep(0.05)
        sender_release.set()
        delivery_outcome = delivery_future.result(timeout=30)
        supersede_outcome = supersede_future.result(timeout=30)

    with engine.connect() as connection:
        prior = connection.execute(
            text("SELECT status, code_ct FROM otp_outbox WHERE id=:id"),
            {"id": intent.outbox_id},
        ).one()
    return {
        "distinct_backend_pids": sorted(set(pids.values())),
        "lock_wait_observed": lock_wait_observed,
        "delivery_outcome": delivery_outcome,
        "supersede_outcome": supersede_outcome,
        "sender_attempts": sender_attempts,
        "prior_outbox_status": prior.status,
        "prior_code_erased": prior.code_ct is None,
        **_deliverable_inventory(engine, registration_id, "signup"),
    }


def _service_probes(
    scratch_url: str,
    engine: Engine,
) -> dict[str, Any]:
    """Exercise the real OTP and session services plus unsafe mutants."""

    from app.models.registration import AuthSession, StudentRegistration, User
    from app.services import login_service, otp_service

    now = datetime.now(timezone.utc)
    owners: dict[str, tuple[uuid.UUID, uuid.UUID]] = {}
    for index, name in enumerate(
        (
            "otp_start",
            "resend",
            "verify",
            "rotation",
            "delivery_race",
            "otp_mutant",
            "session_mutant",
        )
    ):
        user_id, registration_id = uuid.uuid4(), uuid.uuid4()
        _seed_registration(
            engine,
            user_id=user_id,
            registration_id=registration_id,
            discriminator=f"{index + 32:x}",
        )
        owners[name] = (user_id, registration_id)

    def issue_operation(registration_id: uuid.UUID) -> Callable[[Session, int], str]:
        def operation(session: Session, _index: int) -> str:
            try:
                otp_service.issue_challenge(
                    session,
                    registration_id,
                    now,
                    purpose="signup",
                    destination="9000000000",
                )
                session.commit()
                return "success"
            except otp_service.OtpError as exc:
                session.rollback()
                return f"otp_error:{exc.code}"

        return operation

    otp_results = _run_service_race(
        scratch_url,
        WORKERS,
        issue_operation(owners["otp_start"][1]),
    )
    otp_start = {
        **_service_summary(otp_results),
        **_deliverable_inventory(engine, owners["otp_start"][1], "signup"),
    }

    resend_registration = owners["resend"][1]
    with Session(engine) as session:
        otp_service.issue_challenge(
            session,
            resend_registration,
            now,
            purpose="signup",
            destination="9000000000",
        )
        session.commit()

    def resend_or_start(session: Session, index: int) -> str:
        try:
            if index == 0:
                otp_service.resend(
                    session,
                    resend_registration,
                    now + timedelta(seconds=31),
                    purpose="signup",
                    destination="9000000000",
                )
            else:
                otp_service.issue_challenge(
                    session,
                    resend_registration,
                    now + timedelta(seconds=31),
                    purpose="signup",
                    destination="9000000000",
                )
            session.commit()
            return "success"
        except otp_service.OtpError as exc:
            session.rollback()
            return f"otp_error:{exc.code}"

    resend_results = _run_service_race(scratch_url, 2, resend_or_start)
    resend = {
        **_service_summary(resend_results),
        **_deliverable_inventory(engine, resend_registration, "signup"),
    }

    verify_user, verify_registration = owners["verify"]
    attempt_id, challenge_id, opaque_id, code = _seed_login_attempt(
        engine, verify_registration, now
    )

    def verify_operation(session: Session, _index: int) -> str:
        try:
            login_service.verify(session, opaque_id, code, now)
            return "success"
        except login_service.LoginError as exc:
            session.rollback()
            return f"login_error:{exc.code}"

    verify_results = _run_service_race(scratch_url, WORKERS, verify_operation)
    with engine.connect() as connection:
        verify_state = connection.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM login_attempts
                   WHERE id=:attempt_id AND status='consumed'
                     AND consumed_at IS NOT NULL) AS claimed_attempts,
                  (SELECT count(*) FROM otp_challenges
                   WHERE id=:challenge_id AND consumed_at IS NOT NULL) AS consumed_challenges,
                  (SELECT count(*) FROM auth_sessions
                   WHERE user_id=:user_id AND status='active') AS active_sessions
                """
            ),
            {
                "attempt_id": attempt_id,
                "challenge_id": challenge_id,
                "user_id": verify_user,
            },
        ).one()
    verify = {
        **_service_summary(verify_results),
        "claimed_attempts": int(verify_state.claimed_attempts),
        "consumed_challenges": int(verify_state.consumed_challenges),
        "active_sessions": int(verify_state.active_sessions),
    }

    rotation_user, rotation_registration = owners["rotation"]

    def rotation_operation(session: Session, _index: int) -> str:
        registration = session.get(StudentRegistration, rotation_registration)
        if registration is None:
            return "missing_registration"
        try:
            login_service.rotate_authenticated_session(session, registration, now)
            return "success"
        except login_service.LoginError as exc:
            session.rollback()
            return f"login_error:{exc.code}"

    rotation_results = _run_service_race(
        scratch_url, WORKERS, rotation_operation
    )
    with engine.connect() as connection:
        active_rotations = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM auth_sessions "
                    "WHERE user_id=:user_id AND status='active'"
                ),
                {"user_id": rotation_user},
            )
            or 0
        )
    rotation = {
        **_service_summary(rotation_results),
        "active_sessions": active_rotations,
    }

    delivery_race = _outbox_delivery_supersede_probe(
        scratch_url,
        engine,
        owners["delivery_race"][1],
        now,
    )

    # Deterministic negative controls: remove both protection layers. The
    # barrier-bearing unsafe seams make every worker read the zero-child state
    # before any insert, proving the positive oracle would turn red.
    with engine.begin() as connection:
        connection.execute(text(f'DROP INDEX "{TARGET_INDEXES[0]}"'))
    original_registration_lock = otp_service.lock_registration_for_update
    original_active_read = otp_service.active_challenges_for_replacement
    unsafe_otp_barrier = threading.Barrier(WORKERS)
    unsafe_otp_read_barrier = threading.Barrier(WORKERS)

    def unsafe_registration_load(session: Session, registration_id: uuid.UUID):
        row = session.get(StudentRegistration, registration_id)
        unsafe_otp_barrier.wait(timeout=30)
        return row

    def unsafe_active_read(
        session: Session,
        registration_id: uuid.UUID,
        purpose: str,
    ) -> list[Any]:
        rows = list(
            session.scalars(
                select(otp_service.OtpChallenge).where(
                    otp_service.OtpChallenge.registration_id == registration_id,
                    otp_service.OtpChallenge.purpose == purpose,
                    otp_service.OtpChallenge.consumed_at.is_(None),
                )
            )
        )
        unsafe_otp_read_barrier.wait(timeout=30)
        return rows

    otp_service.lock_registration_for_update = unsafe_registration_load
    otp_service.active_challenges_for_replacement = unsafe_active_read
    try:
        otp_mutant_results = _run_service_race(
            scratch_url,
            WORKERS,
            issue_operation(owners["otp_mutant"][1]),
        )
    finally:
        otp_service.lock_registration_for_update = original_registration_lock
        otp_service.active_challenges_for_replacement = original_active_read
    otp_mutant = {
        **_service_summary(otp_mutant_results),
        **_deliverable_inventory(engine, owners["otp_mutant"][1], "signup"),
    }

    with engine.begin() as connection:
        connection.execute(text(f'DROP INDEX "{TARGET_INDEXES[1]}"'))
    original_user_lock = login_service.lock_user_for_session_rotation
    original_active_read = login_service.active_sessions_for_rotation
    unsafe_user_barrier = threading.Barrier(WORKERS)
    unsafe_read_barrier = threading.Barrier(WORKERS)

    def unsafe_user_load(session: Session, user_id: uuid.UUID):
        row = session.get(User, user_id)
        unsafe_user_barrier.wait(timeout=30)
        return row

    def unsafe_active_read(session: Session, user_id: uuid.UUID):
        rows = list(
            session.scalars(
                select(AuthSession).where(
                    AuthSession.user_id == user_id,
                    AuthSession.status == "active",
                )
            )
        )
        unsafe_read_barrier.wait(timeout=30)
        return rows

    login_service.lock_user_for_session_rotation = unsafe_user_load
    login_service.active_sessions_for_rotation = unsafe_active_read
    try:
        session_mutant_results = _run_service_race(
            scratch_url,
            WORKERS,
            lambda session, index: rotation_operation_for(
                session,
                owners["session_mutant"][1],
                login_service,
                now,
            ),
        )
    finally:
        login_service.lock_user_for_session_rotation = original_user_lock
        login_service.active_sessions_for_rotation = original_active_read
    with engine.connect() as connection:
        mutant_active_sessions = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM auth_sessions "
                    "WHERE user_id=:user_id AND status='active'"
                ),
                {"user_id": owners["session_mutant"][0]},
            )
            or 0
        )
    session_mutant = {
        **_service_summary(session_mutant_results),
        "active_sessions": mutant_active_sessions,
    }

    return {
        "otp_start": otp_start,
        "resend_start": resend,
        "otp_verify": verify,
        "session_rotation": rotation,
        "outbox_delivery_supersede": delivery_race,
        "unsafe_without_lock_and_constraint": {
            "otp_start": otp_mutant,
            "session_rotation": session_mutant,
        },
    }


def rotation_operation_for(
    session: Session,
    registration_id: uuid.UUID,
    login_service: Any,
    now: datetime,
) -> str:
    """Shared service-rotation operation used by the deterministic mutant."""

    from app.models.registration import StudentRegistration

    registration = session.get(StudentRegistration, registration_id)
    if registration is None:
        return "missing_registration"
    try:
        login_service.rotate_authenticated_session(session, registration, now)
        return "success"
    except login_service.LoginError as exc:
        session.rollback()
        return f"login_error:{exc.code}"


def _guardian_state_matrix(
    engine: Engine, ids: dict[str, uuid.UUID]
) -> dict[str, Any]:
    """Exercise every allowed guardian status in valid and invalid polarity."""

    cases: dict[str, dict[str, Any]] = {}
    for name, status, verified, should_insert in GUARDIAN_STATE_CASES:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO guardian_consents (
                            id, registration_id, status, verified
                        ) VALUES (:id, :registration_id, :status, :verified)
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "registration_id": ids[f"guardian_state_{name}_registration"],
                        "status": status,
                        "verified": verified,
                    },
                )
            cases[name] = {
                "status": status,
                "verified": verified,
                "should_insert": should_insert,
                "outcome": "inserted",
                "constraint": None,
            }
        except IntegrityError as exc:
            cases[name] = {
                "status": status,
                "verified": verified,
                "should_insert": should_insert,
                "outcome": "constraint_rejected",
                "constraint": _constraint_name(exc),
            }
    return {"cases": cases}


def _expectation_results(report: dict[str, Any], expectation: str) -> list[dict[str, Any]]:
    probes = report["probes"]
    inventory = report["inventory"]
    results: list[dict[str, Any]] = []

    def add(ident: str, title: str, passed: bool, observed: Any) -> None:
        results.append(
            {
                "id": ident,
                "title": title,
                "status": "PASS" if passed else "FAIL",
                "observed": observed,
            }
        )

    if expectation == "current-vulnerable":
        add(
            "RED-OTP",
            "eight concurrent deliverable active OTP inserts are accepted",
            probes["otp"]["persisted_rows"] == WORKERS
            and probes["otp"]["inserted"] == WORKERS,
            probes["otp"],
        )
        add(
            "RED-SESSION",
            "eight concurrent active sessions for one user are accepted",
            probes["session"]["persisted_rows"] == WORKERS
            and probes["session"]["inserted"] == WORKERS,
            probes["session"],
        )
        for ident, key in (
            ("RED-GUARDIAN", "guardian"),
            ("RED-VERIFICATION", "verification"),
        ):
            add(
                ident,
                f"duplicate {key} rows are accepted",
                probes[key]["persisted_rows"] == 2
                and probes[key]["inserted"] == 2,
                probes[key],
            )
        add(
            "RED-GUARDIAN-STATE",
            "all valid and contradictory guardian status/boolean pairs are accepted",
            all(
                case["outcome"] == "inserted"
                for case in probes["guardian_state"]["cases"].values()
            ),
            probes["guardian_state"],
        )
    else:
        service = report.get("service_probes") or {}
        add(
            "HARD-OTP",
            "exactly one concurrent deliverable active OTP survives",
            probes["otp"]["persisted_rows"] == 1
            and probes["otp"]["inserted"] == 1
            and probes["otp"]["constraint_rejected"] == WORKERS - 1
            and probes["otp"]["constraint_names"]
            == [RACE_CONSTRAINTS["otp"]] * (WORKERS - 1),
            probes["otp"],
        )
        add(
            "HARD-SESSION",
            "at most one concurrent active session survives",
            probes["session"]["persisted_rows"] == 1
            and probes["session"]["inserted"] == 1
            and probes["session"]["constraint_rejected"] == WORKERS - 1
            and probes["session"]["constraint_names"]
            == [RACE_CONSTRAINTS["session"]] * (WORKERS - 1),
            probes["session"],
        )
        for ident, key in (
            ("HARD-GUARDIAN", "guardian"),
            ("HARD-VERIFICATION", "verification"),
        ):
            add(
                ident,
                f"duplicate {key} row is rejected",
                probes[key]["persisted_rows"] == 1
                and probes[key]["inserted"] == 1
                and probes[key]["constraint_rejected"] == 1
                and probes[key]["constraint_names"]
                == [RACE_CONSTRAINTS[key]],
                probes[key],
            )
        add(
            "HARD-GUARDIAN-STATE",
            "valid guardian states are accepted and every contradiction is rejected by the intended constraint",
            all(
                (
                    case["outcome"] == "inserted"
                    and case["constraint"] is None
                )
                if case["should_insert"]
                else (
                    case["outcome"] == "constraint_rejected"
                    and case["constraint"]
                    == "ck_guardian_consents_verified_matches_status"
                )
                for case in probes["guardian_state"]["cases"].values()
            ),
            probes["guardian_state"],
        )
        add(
            "HARD-INVENTORY",
            "all target indexes and constraints are present by exact name",
            all(inventory["target_indexes_present"].values())
            and all(inventory["target_constraints_present"].values())
            and all(inventory["target_index_semantics"].values())
            and all(inventory["target_constraint_semantics"].values()),
            {
                "indexes": inventory["target_indexes_present"],
                "constraints": inventory["target_constraints_present"],
                "index_semantics": inventory["target_index_semantics"],
                "constraint_semantics": inventory["target_constraint_semantics"],
            },
        )
        otp_start = service.get("otp_start", {})
        add(
            "HARD-SERVICE-OTP-START",
            "eight real OTP starts serialize to one deliverable active challenge",
            otp_start.get("outcomes") == {"success": WORKERS}
            and len(otp_start.get("distinct_backend_pids", [])) == WORKERS
            and otp_start.get("active") == 1
            and otp_start.get("deliverable") == 1,
            otp_start,
        )
        resend = service.get("resend_start", {})
        resend_outcomes = resend.get("outcomes", {})
        add(
            "HARD-SERVICE-RESEND-START",
            "concurrent resend and start retain one deliverable active challenge",
            len(resend.get("distinct_backend_pids", [])) == 2
            and resend.get("active") == 1
            and resend.get("deliverable") == 1
            and sum(resend_outcomes.values()) == 2
            and resend_outcomes.get("success", 0) >= 1
            and set(resend_outcomes).issubset(
                {"success", "otp_error:resend_cooldown"}
            ),
            resend,
        )
        verify = service.get("otp_verify", {})
        add(
            "HARD-SERVICE-OTP-VERIFY",
            "eight real OTP verifications yield one consumption and session",
            verify.get("outcomes")
            == {"login_error:login_failed": WORKERS - 1, "success": 1}
            and len(verify.get("distinct_backend_pids", [])) == WORKERS
            and verify.get("claimed_attempts") == 1
            and verify.get("consumed_challenges") == 1
            and verify.get("active_sessions") == 1,
            verify,
        )
        rotation = service.get("session_rotation", {})
        add(
            "HARD-SERVICE-SESSION-ROTATION",
            "eight real session rotations serialize to one active session",
            rotation.get("outcomes") == {"success": WORKERS}
            and len(rotation.get("distinct_backend_pids", [])) == WORKERS
            and rotation.get("active_sessions") == 1,
            rotation,
        )
        delivery_race = service.get("outbox_delivery_supersede", {})
        add(
            "HARD-SERVICE-OUTBOX-LOCK-ORDER",
            "delivery and supersession linearize without lock-order deadlock",
            delivery_race.get("delivery_outcome") == "success"
            and delivery_race.get("supersede_outcome") == "success"
            and len(delivery_race.get("distinct_backend_pids", [])) == 2
            and delivery_race.get("lock_wait_observed") is True
            and delivery_race.get("sender_attempts") == 1
            and delivery_race.get("prior_outbox_status") == "sent"
            and delivery_race.get("prior_code_erased") is True
            and delivery_race.get("active") == 1
            and delivery_race.get("deliverable") == 1,
            delivery_race,
        )
        mutants = service.get("unsafe_without_lock_and_constraint", {})
        otp_mutant = mutants.get("otp_start", {})
        session_mutant = mutants.get("session_rotation", {})
        add(
            "HARD-SERVICE-MUTANTS",
            "removing both lock and constraint makes both service oracles red",
            otp_mutant.get("outcomes") == {"success": WORKERS}
            and otp_mutant.get("active") == WORKERS
            and otp_mutant.get("deliverable") == WORKERS
            and session_mutant.get("outcomes") == {"success": WORKERS}
            and session_mutant.get("active_sessions", 0) > 1,
            {"otp": otp_mutant, "session": session_mutant},
        )

    add(
        "HARNESS-CONNECTIONS",
        "every race used one distinct PostgreSQL backend per worker",
        all(
            len(probes[key]["distinct_backend_pids"]) == probes[key]["workers"]
            for key in ("otp", "session", "guardian", "verification")
        ),
        {
            key: probes[key]["distinct_backend_pids"]
            for key in ("otp", "session", "guardian", "verification")
        },
    )
    add(
        "HARNESS-ERRORS",
        "no worker ended in an unexpected harness error",
        all(
            probes[key]["unexpected_error"] == 0
            for key in ("otp", "session", "guardian", "verification")
        ),
        {
            key: probes[key]["unexpected_error"]
            for key in ("otp", "session", "guardian", "verification")
        },
    )
    return results


def _execute(scratch_url: str, expectation: str) -> dict[str, Any]:
    migration = [
        _run_alembic(scratch_url, "upgrade", "head"),
        _run_alembic(scratch_url, "check"),
    ]
    if any(item["returncode"] != 0 for item in migration):
        raise Blocked("scratch database migration/drift prerequisite failed")

    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        inventory = _runtime_inventory(engine)
        if not inventory["postgresql_16_or_newer"] or not inventory["pgvector_version"]:
            raise Blocked("PostgreSQL 16 with pgvector is required")

        ids: dict[str, uuid.UUID] = {}
        seed_targets = [
            ("otp", "a"),
            ("session", "b"),
            ("guardian", "c"),
            ("verification", "d"),
        ]
        seed_targets.extend(
            # 0016 requires 64-character lowercase-hex lookup hashes. Keep the
            # discriminator synthetic, unique, and inside that exact domain.
            (f"guardian_state_{name}", f"{index + 14:x}")
            for index, (name, _status, _verified, _should_insert) in enumerate(
                GUARDIAN_STATE_CASES
            )
        )
        for name, discriminator in seed_targets:
            user_id, registration_id = uuid.uuid4(), uuid.uuid4()
            _seed_registration(
                engine,
                user_id=user_id,
                registration_id=registration_id,
                discriminator=discriminator,
            )
            ids[f"{name}_user"] = user_id
            ids[f"{name}_registration"] = registration_id

        probes: dict[str, Any] = {}
        for kind, workers in (
            ("otp", WORKERS),
            ("session", WORKERS),
            ("guardian", 2),
            ("verification", 2),
        ):
            worker_results = _run_race(scratch_url, kind, workers, ids)
            probes[kind] = _summarize_race(
                engine,
                kind=kind,
                results=worker_results,
                ids=ids,
            )
        probes["guardian_state"] = _guardian_state_matrix(engine, ids)
        service_probes = (
            _service_probes(scratch_url, engine)
            if expectation == "hardened"
            else None
        )

        report: dict[str, Any] = {
            "gate": "NYAY-3 PostgreSQL cardinality characterization",
            "expectation": expectation,
            "classification": (
                "RED_BASELINE_ONLY"
                if expectation == "current-vulnerable"
                else "FIX_VERIFICATION"
            ),
            "scratch_database_retained": False,
            "migration": migration,
            "inventory": inventory,
            "probes": probes,
        }
        if service_probes is not None:
            report["service_probes"] = service_probes
        report["assertions"] = _expectation_results(report, expectation)
        passed = all(item["status"] == "PASS" for item in report["assertions"])
        report["verdict"] = (
            "PASS_RED_BASELINE"
            if passed and expectation == "current-vulnerable"
            else "PASS_HARDENED"
            if passed
            else "FAIL_EXPECTATION"
        )
        return report
    finally:
        engine.dispose()


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    print(payload, end="")
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")


def _finalize_cleanup(
    report: dict[str, Any],
    *,
    scratch_created: bool,
    cleanup_failed: bool,
    primary_exit_code: int,
) -> int:
    """Attach a fail-closed cleanup verdict and return the final exit code."""

    if not scratch_created:
        report["scratch_database_retained"] = False
        report["cleanup"] = {"attempted": False, "status": "NOT_CREATED"}
        return primary_exit_code
    if cleanup_failed:
        report["pre_cleanup_verdict"] = report.get("verdict")
        report["scratch_database_retained"] = True
        report["cleanup"] = {"attempted": True, "status": "FAIL"}
        report["classification"] = "HARNESS_FAILURE_NO_PRODUCT_VERDICT"
        report["verdict"] = "FAIL_CLEANUP"
        return 1
    report["scratch_database_retained"] = False
    report["cleanup"] = {"attempted": True, "status": "PASS"}
    return primary_exit_code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="loopback PostgreSQL server used only to create a scratch database",
    )
    parser.add_argument(
        "--expect",
        choices=("current-vulnerable", "hardened"),
        default="current-vulnerable",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("BLOCKED: set --database-url or DATABASE_URL")

    scratch_name = f"nyay3_char_{uuid.uuid4().hex[:12]}"
    base: URL | None = None
    scratch_created = False
    cleanup_failed = False
    exit_code = 1
    try:
        base = _safe_local_postgres_url(args.database_url)
        scratch_url = _create_scratch(base, scratch_name)
        scratch_created = True
        report = _execute(scratch_url, args.expect)
        exit_code = 0 if report["verdict"].startswith("PASS_") else 1
    except Blocked as exc:
        report = {
            "gate": "NYAY-3 PostgreSQL cardinality characterization",
            "expectation": args.expect,
            "classification": "BLOCKED_NO_EVIDENCE",
            "verdict": "BLOCKED",
            "reason": str(exc),
        }
        exit_code = BLOCKED_EXIT
    except Exception as exc:  # noqa: BLE001 - fail closed without secret text
        report = {
            "gate": "NYAY-3 PostgreSQL cardinality characterization",
            "expectation": args.expect,
            "classification": "HARNESS_FAILURE_NO_PRODUCT_VERDICT",
            "verdict": "FAIL_HARNESS",
            "error_type": type(exc).__name__,
        }
        exit_code = 1
    finally:
        if base is not None and scratch_created:
            try:
                _drop_scratch(base, scratch_name)
            except Exception:
                cleanup_failed = True

    exit_code = _finalize_cleanup(
        report,
        scratch_created=scratch_created,
        cleanup_failed=cleanup_failed,
        primary_exit_code=exit_code,
    )
    _write_report(report, args.output)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
