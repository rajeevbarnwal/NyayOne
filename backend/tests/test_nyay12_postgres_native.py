"""Execute the NYAY-12 native PostgreSQL gate when explicitly opted in (E-30).

Mirrors the WAVE3/SAATHI-60 pattern: without ``NYAY12_POSTGRES_GATE=1`` and a
loopback ``NYAY12_POSTGRES_CONTROL_URL`` the test is skipped, never a PASS.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests import nyay12_native_gate as gate


def test_native_gate_executes_all_oracles_when_opted_in(tmp_path: Path):
    if os.getenv(gate.OPT_IN_ENV) != "1" or not os.getenv("NYAY12_POSTGRES_CONTROL_URL"):
        pytest.skip("NYAY12_POSTGRES_GATE=1 and NYAY12_POSTGRES_CONTROL_URL are not configured")
    output = tmp_path / "summary.json"
    report = gate.run(os.environ["NYAY12_POSTGRES_CONTROL_URL"], output)
    gate.validate_report(report)
    assert json.loads(output.read_text())["status"] == "PASS"
    assert tuple(row["id"] for row in report["rows"]) == gate.ORACLE_IDS
