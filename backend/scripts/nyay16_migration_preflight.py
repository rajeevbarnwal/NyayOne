#!/usr/bin/env python3
"""Read-only operator preflight for the authoritative NYAY-16 PG migration.

Exit codes:
  0  PostgreSQL parent schema/data/key authority is migration-ready.
  1  Preflight rejected or the database could not be safely inspected.
  78 The configured database is not PostgreSQL 16 and is non-authoritative.

Output is one bounded JSON object containing aggregate disposition counts only.
Database URLs, row identifiers, source values, ciphertext, hashes, key versions,
and exception strings are deliberately never emitted.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

_BACKEND = Path(__file__).resolve().parents[1]
_ROOT = _BACKEND.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _revision_module():
    config = Config(str(_BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND / "app/db/migrations"))
    return ScriptDirectory.from_config(config).get_revision(
        "0016_dob_hash_reconcile"
    ).module


def _migration_ledger_is_valid() -> bool:
    """Verify frozen local migration bytes before opening the database."""

    verifier = _ROOT / "scripts/ci/verify_migration_ledger.py"
    if not verifier.is_file() or verifier.is_symlink():
        return False
    try:
        result = subprocess.run(
            [sys.executable, str(verifier)],
            cwd=_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _emit(verdict: str, code: str, **aggregates: int) -> None:
    payload: dict[str, object] = {
        "verdict": verdict,
        "code": code,
        "revision": "0016_dob_hash_reconcile",
    }
    payload.update({key: int(value) for key, value in sorted(aggregates.items())})
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def main() -> int:
    engine = None
    try:
        # Local source authority is a prerequisite for interpreting any DB
        # result. This runs before settings are loaded or a connection opens.
        if not _migration_ledger_is_valid():
            _emit("FAIL", "migration_ledger_rejected")
            return 1
        from app.core.config import settings

        engine = create_engine(settings.database_url, pool_pre_ping=True)
        if engine.dialect.name != "postgresql":
            _emit("NOT_AUTHORITATIVE", "postgresql_required")
            return 78
        module = _revision_module()
        # The helper performs SELECT/lock-based inspection only.  Rolling the
        # transaction back makes that read-only intent explicit and releases
        # both the advisory and table locks without changing database state.
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                server_version_num = int(
                    connection.scalar(
                        text("SELECT current_setting('server_version_num')::integer")
                    )
                )
                if not 160000 <= server_version_num < 170000:
                    _emit("NOT_AUTHORITATIVE", "postgresql_16_required")
                    return 78
                plan = module.preflight_dob_hash_reconciliation(connection)
            finally:
                transaction.rollback()
        states = Counter(row.state for row in plan)
        outcomes = Counter(row.outcome for row in plan if row.outcome is not None)
        _emit(
            "PASS",
            "migration_ready",
            rows=len(plan),
            verified=states["verified"],
            quarantined=states["quarantined"],
            erased=states["erased"],
            reconciled=outcomes["reconciled"],
        )
        return 0
    except Exception:
        # Fail closed and sanitized: operator logs must not receive driver error
        # strings because those can contain hosts, user names or source values.
        _emit("FAIL", "preflight_rejected")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
