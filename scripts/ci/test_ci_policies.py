#!/usr/bin/env python3
"""Seeded negative tests proving NyayOne CI policy oracles fail closed."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


HERE = Path(__file__).resolve().parent


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PolicyOracleTests(unittest.TestCase):
    def test_workflow_validator_rejects_partial_green_and_write_authority(self) -> None:
        policy = load("verify_nyayone_ci")
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / "bad.yml"
            workflow.write_text(
                """name: bad
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  id-token: write
concurrency: bad
jobs:
  good:
    runs-on: ubuntu-24.04
    timeout-minutes: 1
    steps:
      - uses: evil/example@0000000000000000000000000000000000000000
  bad:
    runs-on: ubuntu-24.04
    timeout-minutes: 1
    steps:
      - run: exit 1
  required:
    name: nyayone-bad-required
    runs-on: ubuntu-24.04
    timeout-minutes: 1
    needs: [good]
    steps:
      - run: true
""",
                encoding="utf-8",
            )
            failures = policy.check_workflow(workflow)
        for fragment in (
            "write permission",
            "owner",
            "if: always",
            "expected",
            "fail-closed needs result contract",
        ):
            self.assertTrue(any(fragment in failure for failure in failures), failures)

    def test_evidence_scanner_rejects_each_credential_shape(self) -> None:
        scanner = load("scan_evidence")
        payloads = (
            b"Authorization: Bearer nyayone-ci-planted-canary-0123456789\n",
            b'{"Authorization":"Bearer nyayone-json-canary-0123456789"}\n',
            b'{"cookie":"nyayone_session=nyayone-cookie-canary-0123456789"}\n',
            b"eyJueWF5b25lIjoiY2FuYXJ5In0.eyJzY29wZSI6InRlc3QifQ.c2lnbmF0dXJlLWNhbmFyeQ\n",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            leak = root / "evidence.txt"
            for payload in payloads:
                leak.write_bytes(payload)
                self.assertTrue(scanner.scan(root), payload)
            leak.write_text("sanitized evidence\n", encoding="utf-8")
            self.assertEqual(scanner.scan(root), [])


if __name__ == "__main__":
    unittest.main()
