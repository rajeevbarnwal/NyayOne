"""Unit and opt-in target-runtime tests for the NYAY-16 PG16 gate."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

import scripts.nyay16_postgres_gate as nyay16_gate

from scripts.nyay16_postgres_gate import (
    ASSERTION_CONTRACT,
    BLOCKED,
    HEAD,
    PARENT,
    Results,
    _canonical_fingerprint,
    _expected_concurrent_counts,
    _expected_populated_counts,
    _expected_safe_roundtrip_counts,
    _is_exact_nyay16_revision,
    is_isolated_control_target,
    is_postgresql_16,
    privacy_canary_hits,
)

BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("postgresql+psycopg://u:p@127.0.0.1:5432/nyay16_qa", True),
        ("postgresql+psycopg://u:p@localhost:5432/migration_test", True),
        ("postgresql+psycopg://u:p@localhost:5432/nyayone_ci", True),
        ("postgresql+psycopg://u:p@[::1]:5432/nyay16_testing", True),
        ("postgresql+psycopg://u:test@127.0.0.1:5432/application", False),
        ("postgresql+psycopg://u:p@127.0.0.1:5432/nyay16_qa?host=db.internal", False),
        ("postgresql+psycopg://u:p@127.0.0.1:5432/nyay16_qa?service=remote", False),
        ("postgresql+psycopg://u:p%40remote@127.0.0.1:5432/nyay16_qa", False),
        ("postgresql+psycopg://u:p@remote@127.0.0.1:5432/nyay16_qa", False),
        ("postgresql+psycopg://u:p@127.0.0.1:5432/production_qa", False),
        ("postgresql+psycopg://u:p@db.internal:5432/nyay16_qa", False),
        ("sqlite+pysqlite:////tmp/nyay16_qa.db", False),
        ("not-a-url", False),
        ("", False),
    ],
)
def test_control_target_isolation_uses_host_and_database_only(url: str, allowed: bool) -> None:
    assert is_isolated_control_target(url, True) is allowed


def test_control_target_always_requires_explicit_database_mutation_opt_in() -> None:
    url = "postgresql+psycopg://u:p@127.0.0.1:5432/nyay16_qa"
    assert is_isolated_control_target(url, False) is False


@pytest.mark.parametrize(
    ("server_version_num", "accepted"),
    [
        (159999, False),
        (160000, True),
        (160014, True),
        (169999, True),
        (170000, False),
        (180001, False),
    ],
)
def test_target_runtime_is_exactly_postgresql_major_16(
    server_version_num: int, accepted: bool
) -> None:
    assert is_postgresql_16(server_version_num) is accepted


def test_fingerprint_is_canonical_for_mapping_order() -> None:
    left = {"states": {"verified": 2, "quarantined": 3}, "placeholder": 0}
    right = {"placeholder": 0, "states": {"quarantined": 3, "verified": 2}}
    assert _canonical_fingerprint(left) == _canonical_fingerprint(right)
    assert len(_canonical_fingerprint(left)) == 64


def test_privacy_detector_returns_labels_without_echoing_canaries() -> None:
    secret = "do-not-export-this-value"
    hits = privacy_canary_hits({"nested": ["prefix", secret]}, [secret, "absent"])
    assert hits == ["canary-0"]
    assert secret not in json.dumps(hits)


def test_expected_populated_inventory_is_bounded_category_counts_only() -> None:
    expected = _expected_populated_counts()
    assert expected == {
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
    serialised = json.dumps(expected, sort_keys=True)
    assert "registration_id" not in serialised
    assert "dob_ct" not in serialised
    assert "dob_hash\"" not in serialised


def test_concurrent_writer_removes_only_the_safe_reconciliation_record() -> None:
    expected = _expected_concurrent_counts()
    assert expected["states"] == {"erased": 1, "quarantined": 3, "verified": 2}
    assert expected["reconciliations"] == {
        "quarantined:ciphertext_unreadable": 1,
        "quarantined:source_not_canonical_date": 1,
        "quarantined:source_future_date": 1,
    }


def test_safe_populated_roundtrip_inventory_excludes_terminal_quarantines() -> None:
    assert _expected_safe_roundtrip_counts() == {
        "states": {"erased": 1, "verified": 2},
        "reconciliations": {"reconciled:verified_source": 1},
        "placeholder_count": 0,
        "invalid_hash_count": 0,
    }


def test_results_are_fail_closed() -> None:
    results = Results()
    assert results.ok is False
    results.add("pass", "first", True)
    assert results.ok is True
    results.add("fail", "second", False)
    assert results.ok is False


def test_assertion_contract_is_unique_and_tracks_exact_revision_pair() -> None:
    identifiers = [ident for ident, _ in ASSERTION_CONTRACT]
    assert len(identifiers) == len(set(identifiers)) == 10
    assert identifiers == [f"N16-PG-{index:02d}" for index in range(1, 11)]
    assert PARENT == "0015_wave4_public_risk_labels"
    assert HEAD == "0016_dob_hash_reconcile"


@pytest.mark.parametrize(
    ("revision", "accepted"),
    [
        (HEAD, True),
        (PARENT, False),
        ("0017_registration_invariants", False),
        ("0018_registration_idempotency", False),
        ("0019_otp_security_authority", False),
        ("0020_auth_retention_lifecycle", False),
        (None, False),
    ],
)
def test_historical_gate_accepts_only_its_pinned_revision(
    monkeypatch: pytest.MonkeyPatch,
    revision: str | None,
    accepted: bool,
) -> None:
    monkeypatch.setattr(nyay16_gate, "_head", lambda _engine: revision)
    assert _is_exact_nyay16_revision(object()) is accepted


def test_historical_gate_revision_is_not_repository_head() -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option(
        "script_location", str(BACKEND / "app" / "db" / "migrations")
    )
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0023_nyay22_mentor_ceremony"
    assert HEAD != script.get_current_head()
    assert script.get_revision(HEAD).down_revision == PARENT


def test_historical_gate_never_calls_repository_head_or_alembic_check() -> None:
    source = Path(nyay16_gate.__file__).read_text(encoding="utf-8")
    assert '_run_alembic(url, env, "check")' not in source
    assert '_run_alembic(url, env, "upgrade", "head")' not in source
    assert '_run_alembic(url, env, "downgrade", "head")' not in source


def test_cli_lists_contract_without_database_access() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/nyay16_postgres_gate.py", "--list"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0
    assert "N16-PG-01" in completed.stdout
    assert "N16-PG-10" in completed.stdout


def test_cli_reports_blocked_not_pass_when_target_is_absent(tmp_path: Path) -> None:
    output = tmp_path / "blocked.json"
    env = {
        **os.environ,
        "DATABASE_URL": "sqlite+pysqlite:////tmp/nyay16_qa.db",
        "NYAY16_GATE_ALLOW_DATABASES": "true",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/nyay16_postgres_gate.py",
            "--output",
            str(output),
        ],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == BLOCKED
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "executed": False,
        "exit_code": BLOCKED,
        "gate": "nyay16_postgres",
        "reason": "isolated loopback PostgreSQL QA control target or mutation opt-in absent",
        "status": "BLOCKED",
    }
    assert "PASS" not in completed.stdout


@pytest.mark.skipif(
    os.getenv("NYAY16_POSTGRES_TEST") != "1",
    reason="requires explicitly opted-in disposable PostgreSQL 16 databases",
)
def test_full_native_gate_passes_and_report_contains_no_database_url(tmp_path: Path) -> None:
    output = tmp_path / "summary.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/nyay16_postgres_gate.py",
            "--output",
            str(output),
        ],
        cwd=BACKEND,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout[-2000:]
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "PASS"
    assert all(row["status"] == "PASS" for row in payload["assertions"])
    serialised = json.dumps(payload, sort_keys=True)
    assert os.environ["DATABASE_URL"] not in serialised
    assert "password" not in serialised.casefold()
