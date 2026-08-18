"""Sanitized operator-CLI contract for NYAY-16 migration preflight."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import scripts.nyay16_migration_preflight as preflight_cli

BACKEND = Path(__file__).resolve().parents[1]


def test_local_migration_ledger_verifier_is_part_of_preflight_contract():
    assert preflight_cli._migration_ledger_is_valid() is True


def test_ledger_failure_is_sanitized_and_prevents_database_open(monkeypatch, capsys):
    monkeypatch.setattr(preflight_cli, "_migration_ledger_is_valid", lambda: False)

    def forbidden_database_open(*_args, **_kwargs):
        raise AssertionError("database must not open after ledger rejection")

    monkeypatch.setattr(preflight_cli, "create_engine", forbidden_database_open)
    assert preflight_cli.main() == 1
    assert json.loads(capsys.readouterr().out) == {
        "code": "migration_ledger_rejected",
        "revision": "0016_dob_hash_reconcile",
        "verdict": "FAIL",
    }


def test_non_postgres_is_exit_78_and_never_echoes_url_or_secrets(tmp_path):
    database = tmp_path / "non-authoritative.db"
    database_url = f"sqlite+pysqlite:///{database}"
    encryption_secret = "sensitive-encryption-sentinel"
    lookup_secret = "sensitive-lookup-sentinel"
    result = subprocess.run(
        [sys.executable, "scripts/nyay16_migration_preflight.py"],
        cwd=BACKEND,
        env={
            **os.environ,
            "DATABASE_URL": database_url,
            "REGISTRATION_SECRET": encryption_secret,
            "REGISTRATION_LOOKUP_SECRET": lookup_secret,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 78
    assert json.loads(result.stdout) == {
        "code": "postgresql_required",
        "revision": "0016_dob_hash_reconcile",
        "verdict": "NOT_AUTHORITATIVE",
    }
    combined = result.stdout + result.stderr
    for forbidden in (database_url, str(database), encryption_secret, lookup_secret):
        assert forbidden not in combined
