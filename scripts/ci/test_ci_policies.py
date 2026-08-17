#!/usr/bin/env python3
"""Seeded negative tests proving NyayOne CI policy oracles fail closed."""

from __future__ import annotations

import importlib.util
import json
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

    def test_runtime_identity_policy_accepts_the_current_tree(self) -> None:
        policy = load("check_nyayone_runtime_identity")
        self.assertEqual(policy.check(policy.ROOT), [])

    def test_runtime_identity_policy_rejects_planted_legacy_canaries(self) -> None:
        policy = load("check_nyayone_runtime_identity")
        env_text = (policy.ROOT / ".env.example").read_text(encoding="utf-8")
        bad_env = env_text.replace("VITE_APP_NAME=NyayOne", "VITE_APP_NAME=LegalSaathi")
        self.assertTrue(policy.check_env_text(bad_env, label="planted.env"))

        bad_workflow = """env:
  POSTGRES_USER: legalsaathi
  POSTGRES_PASSWORD: legalsaathi
  POSTGRES_DB: legalsaathi
"""
        self.assertTrue(policy.check_workflow_text(bad_workflow, label="planted.yml"))

        drifted_workflow = """env:
  POSTGRES_USER: unrelated_ci
  POSTGRES_PASSWORD: unrelated_ephemeral
  POSTGRES_DB: unrelated_ci
"""
        drift_failures = policy.check_workflow_text(
            drifted_workflow, label="drifted.yml"
        )
        for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
            self.assertTrue(any(key in item for item in drift_failures), drift_failures)

        removed_postgres = policy.check_workflow_text(
            "name: registration switched to sqlite\njobs: {}\n",
            label="registration-db-gate.yml",
        )
        self.assertTrue(
            any("PostgreSQL service" in item for item in removed_postgres),
            removed_postgres,
        )
        self.assertTrue(
            any("DATABASE_URL contract" in item for item in removed_postgres),
            removed_postgres,
        )

        bad_compose = {
            "name": "legalsaathi",
            "services": {
                "postgres": {
                    "environment": {
                        "POSTGRES_USER": "legalsaathi",
                        "POSTGRES_PASSWORD": "legalsaathi",
                        "POSTGRES_DB": "legalsaathi",
                    },
                    "ports": [{"published": 1032, "target": 5432}],
                },
                "backend": {
                    "environment": {
                        "DATABASE_URL": "postgresql://legacy:redacted@postgres:5432/legacy"
                    },
                    "ports": [{"published": 1031, "target": 1031}],
                },
                "frontend": {
                    "environment": {
                        "VITE_API_BASE_URL": "http://localhost:1031",
                        "VITE_APP_NAME": "LegalSaathi",
                    },
                    "ports": [{"published": 1030, "target": 1030}],
                },
                "logstash": {"ports": [{"published": 1038, "target": 9600}]},
            },
            "volumes": {"pgdata": {"name": "legalsaathi_pgdata"}},
        }
        failures = policy.check_compose_payload(bad_compose, label="planted compose")
        self.assertGreaterEqual(len(failures), 6, json.dumps(failures))

        correct_identity_bad_password = {
            "name": "nyayone",
            "services": {
                "postgres": {
                    "environment": {
                        "POSTGRES_USER": "nyayone",
                        "POSTGRES_PASSWORD": "legalsaathi",
                        "POSTGRES_DB": "nyayone",
                    },
                    "ports": [{"published": 1132, "target": 5432}],
                },
                "backend": {
                    "environment": {
                        "DATABASE_URL": (
                            "postgresql+psycopg://nyayone:nyayone_dev_only"
                            "@postgres:5432/nyayone_evil"
                        )
                    },
                    "ports": [{"published": 1131, "target": 1031}],
                },
                "frontend": {
                    "environment": {
                        "VITE_API_BASE_URL": "http://localhost:1131",
                        "VITE_APP_NAME": "NyayOne",
                    },
                    "ports": [{"published": 1130, "target": 1030}],
                },
                "logstash": {"ports": [{"published": 1138, "target": 9600}]},
            },
            "volumes": {"pgdata": {"name": "nyayone_pgdata"}},
        }
        failures = policy.check_compose_payload(
            correct_identity_bad_password,
            label="password and database path canary",
        )
        self.assertTrue(any("POSTGRES_PASSWORD" in item for item in failures), failures)
        self.assertTrue(any("isolated Compose database" in item for item in failures), failures)

        extra_legacy_service = json.loads(json.dumps(correct_identity_bad_password))
        extra_legacy_service["services"]["postgres"]["environment"][
            "POSTGRES_PASSWORD"
        ] = "nyayone_dev_only"
        extra_legacy_service["services"]["backend"]["environment"][
            "DATABASE_URL"
        ] = (
            "postgresql+psycopg://nyayone:nyayone_dev_only"
            "@postgres:5432/nyayone"
        )
        extra_legacy_service["services"]["legalsaathi-helper"] = {
            "ports": [{"published": 1032, "target": 9999}]
        }
        extra_legacy_service["networks"] = {
            "default": {"name": "legalsaathi_default"}
        }
        failures = policy.check_compose_payload(
            extra_legacy_service,
            label="extra legacy service canary",
        )
        for fragment in ("service identity", "1030-1049", "network identity"):
            self.assertTrue(any(fragment in item for item in failures), failures)

        bad_cookie = (
            policy.ROOT / "frontend/scripts/wave4-moderation-e2e.mjs"
        ).read_text(encoding="utf-8").replace("'nyayone_session'", "'legalsaathi_session'")
        self.assertTrue(
            policy.check_required_operational_text(
                "frontend/scripts/wave4-moderation-e2e.mjs", bad_cookie
            )
        )

    def test_runtime_identity_policy_allows_shared_tenant_and_historical_migrations(self) -> None:
        policy = load("check_nyayone_runtime_identity")
        shared_tenant = "JIRA_BASE_URL=https://legalsaathi.atlassian.net\n"
        values = policy.parse_env(shared_tenant)
        self.assertEqual(values["JIRA_BASE_URL"], "https://legalsaathi.atlassian.net")
        migration_canary = policy.check_active_source_text(
            Path("backend/app/db/migrations/versions/0001_historical.py"),
            'MESSAGE = "Your LegalSaathi verification code"\n',
        )
        active_canary = policy.check_active_source_text(
            Path("backend/app/services/planted.py"),
            'MESSAGE = "Your LegalSaathi verification code"\n',
        )
        self.assertEqual(migration_canary, [])
        self.assertTrue(active_canary)


if __name__ == "__main__":
    unittest.main()
