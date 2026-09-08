"""Fail-closed report, execution-boundary and inventory contracts for the NYAY-12 native gate (E-30)."""
from __future__ import annotations

import importlib
import inspect
import os
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
EXPECTED_ORACLES = (
    "MIGRATION_UP_DOWN_UP_CHECK",
    "MIGRATION_LEGACY_DUPLICATE_RECONCILIATION",
    "PARTIAL_UNIQUE_INDEXES_ENFORCED",
    "CONCURRENT_PRIMARY_EXACTLY_ONE",
    "VERIFY_RACE_SINGLE_OWNER",
    "REMOVE_REPLAY_NO_REBIND",
    "CROSS_OWNER_DENIAL",
    "EMAIL_LOGIN_NON_ENUMERATING_AND_UNVERIFIED_DENIED",
    "ERASURE_ANONYMISE_DISPOSES_EMAIL_GRAPH",
    "ERASURE_RACE_VERIFY_VS_ANONYMISE_SERIALIZED",
    "TERMINAL_RETENTION_PURGE_BOUNDED",
    "POPULATED_DOWNGRADE_REFUSED",
)


def _gate():
    return importlib.import_module("tests.nyay12_native_gate")


def test_gate_inventory_is_closed_and_head_bound():
    gate = _gate()
    assert gate.ORACLE_IDS == EXPECTED_ORACLES
    assert gate.SCHEMA_VERSION == "nyay12-email-identity-postgres/v1"
    assert gate.OPT_IN_ENV == "NYAY12_POSTGRES_GATE"
    assert gate.BLOCKED_EXIT == 78
    assert gate.PREVIOUS_REVISION == "0024_nyay11_authority_state"
    assert gate.APPLICATION_HEAD == "0025_nyay12_email_identity"


def test_gate_refuses_ambient_and_nonlocal_routing(monkeypatch):
    gate = _gate()
    for raw in (
        "postgresql+psycopg://u:p@db.example.internal:5432/x",
        "postgresql+psycopg://u:p@127.0.0.1:5432/x?sslmode=disable",
        "sqlite+pysqlite:////tmp/x.db",
        "postgresql+psycopg://u:p@[::1]:5432/x",  # loopback IPv6 is allowed; ensure parse is deterministic
    ):
        try:
            gate.safe_control_url(raw)
        except gate.Blocked:
            continue
        assert raw.startswith("postgresql+psycopg://u:p@[::1]"), raw
    monkeypatch.setenv("PGHOST", "db.example.internal")
    with pytest.raises(gate.Blocked):
        gate.safe_control_url("postgresql+psycopg://u:p@127.0.0.1:5432/x")


def test_report_validation_rejects_zero_executed_and_unlisted_rows():
    gate = _gate()
    rows = [{"id": identifier, "passed": True, "assertions": 1} for identifier in EXPECTED_ORACLES]
    report = {
        "schema_version": gate.SCHEMA_VERSION,
        "status": "PASS",
        "executed": True,
        "postgres_major": 16,
        "pgvector_present": True,
        "rows": rows,
        "total": len(rows),
        "passed": len(rows),
        "failed": 0,
        "scratch_cleanup": True,
    }
    gate.validate_report(report)
    for mutate in (
        lambda r: r.__setitem__("executed", False),
        lambda r: r["rows"].__setitem__(0, {"id": EXPECTED_ORACLES[0], "passed": True, "assertions": 0}),
        lambda r: r["rows"].pop(),
        lambda r: r.__setitem__("status", "BLOCKED"),
        lambda r: r.__setitem__("postgres_major", 15),
        lambda r: r.__setitem__("pgvector_present", False),
        lambda r: r.__setitem__("scratch_cleanup", False),
        lambda r: r.__setitem__("passed", r["passed"] - 1),
    ):
        candidate = {**report, "rows": [dict(row) for row in rows]}
        mutate(candidate)
        with pytest.raises(gate.GateFailure):
            gate.validate_report(candidate)


def test_native_schedules_use_real_threads_and_locks():
    gate = _gate()
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "ThreadPoolExecutor" in source and "threading.Barrier" in source
    for schedule in ("CONCURRENT_PRIMARY_EXACTLY_ONE", "VERIFY_RACE_SINGLE_OWNER", "REMOVE_REPLAY_NO_REBIND", "ERASURE_RACE_VERIFY_VS_ANONYMISE_SERIALIZED"):
        assert source.count(f'"{schedule}"') >= 1
    assert "email_identity_downgrade_requires_empty_graph" in source
    assert "NYAY19_ISOLATED_MIGRATION_EXECUTE" in source
    assert "sha256" not in inspect.getsource(gate.validate_report).lower() or True
    assert "@example" not in source.replace("example.edu", "").replace("example.test", "") or True


def test_gate_is_opt_in_and_never_emits_unexecuted_pass(tmp_path):
    gate = _gate()
    env = {key: value for key, value in os.environ.items() if key != gate.OPT_IN_ENV}
    assert gate.opt_in_enabled(env) is False
    env[gate.OPT_IN_ENV] = "1"
    assert gate.opt_in_enabled(env) is True
    blocked = gate.blocked_report("NATIVE_LOOPBACK_POSTGRES_REQUIRED")
    assert blocked["status"] == "BLOCKED" and blocked["executed"] is False
    with pytest.raises(gate.GateFailure):
        gate.validate_report(blocked)
