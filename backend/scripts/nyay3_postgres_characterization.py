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
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
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
    return {
        "server_version_num": server_version_num,
        "postgresql_16_or_newer": server_version_num >= 160000,
        "pgvector_version": vector_version,
        "alembic_revision": revision,
        "indexes": indexes,
        "constraints": constraints,
        "target_indexes_present": {
            name: name in indexes for name in TARGET_INDEXES
        },
        "target_constraints_present": {
            name: name in constraints for name in TARGET_CONSTRAINTS
        },
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
                    dob_hash, dob_ct, key_version, status, is_minor
                ) VALUES (
                    :id, :user_id, 'NYAY3', 'Probe', :mobile_hash,
                    :mobile_ct, :dob_hash, :dob_ct, 'v1', 'active', false
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
        "constraint_names": sorted(
            {
                str(item["constraint"])
                for item in results
                if item.get("constraint") is not None
            }
        ),
    }


def _guardian_contradiction(
    engine: Engine, registration_id: uuid.UUID
) -> dict[str, Any]:
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO guardian_consents (
                        id, registration_id, status, verified
                    ) VALUES (:id, :registration_id, 'verified', false)
                    """
                ),
                {"id": uuid.uuid4(), "registration_id": registration_id},
            )
        return {"contradiction_inserted": True, "constraint": None}
    except IntegrityError as exc:
        return {
            "contradiction_inserted": False,
            "constraint": _constraint_name(exc),
        }


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
            "status=verified with verified=false is accepted",
            probes["guardian_state"]["contradiction_inserted"] is True,
            probes["guardian_state"],
        )
    else:
        add(
            "HARD-OTP",
            "exactly one concurrent deliverable active OTP survives",
            probes["otp"]["persisted_rows"] == 1
            and probes["otp"]["inserted"] == 1
            and probes["otp"]["constraint_rejected"] == WORKERS - 1,
            probes["otp"],
        )
        add(
            "HARD-SESSION",
            "at most one concurrent active session survives",
            probes["session"]["persisted_rows"] == 1
            and probes["session"]["inserted"] == 1
            and probes["session"]["constraint_rejected"] == WORKERS - 1,
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
                and probes[key]["constraint_rejected"] == 1,
                probes[key],
            )
        add(
            "HARD-GUARDIAN-STATE",
            "contradictory guardian state is rejected",
            probes["guardian_state"]["contradiction_inserted"] is False
            and probes["guardian_state"]["constraint"]
            == "ck_guardian_consents_verified_matches_status",
            probes["guardian_state"],
        )
        add(
            "HARD-INVENTORY",
            "all target indexes and constraints are present by exact name",
            all(inventory["target_indexes_present"].values())
            and all(inventory["target_constraints_present"].values()),
            {
                "indexes": inventory["target_indexes_present"],
                "constraints": inventory["target_constraints_present"],
            },
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
        for name, discriminator in (
            ("otp", "a"),
            ("session", "b"),
            ("guardian", "c"),
            ("verification", "d"),
            ("guardian_state", "e"),
        ):
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
        probes["guardian_state"] = _guardian_contradiction(
            engine, ids["guardian_state_registration"]
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
    try:
        base = _safe_local_postgres_url(args.database_url)
        scratch_url = _create_scratch(base, scratch_name)
        scratch_created = True
        report = _execute(scratch_url, args.expect)
    except Blocked as exc:
        report = {
            "gate": "NYAY-3 PostgreSQL cardinality characterization",
            "expectation": args.expect,
            "classification": "BLOCKED_NO_EVIDENCE",
            "verdict": "BLOCKED",
            "reason": str(exc),
        }
        _write_report(report, args.output)
        raise SystemExit(BLOCKED_EXIT) from exc
    except Exception as exc:  # noqa: BLE001 - fail closed without secret text
        report = {
            "gate": "NYAY-3 PostgreSQL cardinality characterization",
            "expectation": args.expect,
            "classification": "HARNESS_FAILURE_NO_PRODUCT_VERDICT",
            "verdict": "FAIL_HARNESS",
            "error_type": type(exc).__name__,
        }
        _write_report(report, args.output)
        raise SystemExit(1) from exc
    finally:
        if base is not None and scratch_created:
            try:
                _drop_scratch(base, scratch_name)
            except Exception:
                # A leaked scratch database is operationally important but must
                # not replace the primary assertion result. Its random name is
                # intentionally printed without a URL/credential.
                print(
                    json.dumps(
                        {
                            "cleanup_warning": "scratch database drop failed",
                            "scratch_database": scratch_name,
                        }
                    ),
                    file=sys.stderr,
                )

    _write_report(report, args.output)
    raise SystemExit(0 if report["verdict"].startswith("PASS_") else 1)


if __name__ == "__main__":
    main()
