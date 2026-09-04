#!/usr/bin/env python3
"""Fail-closed CI reachability contracts for the NYAY-22 release gates."""

from __future__ import annotations

import importlib.util
import json
import sys
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
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Nyay22CiPolicyTests(unittest.TestCase):
    def test_browser_sources_package_and_required_workflow_are_sealed(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(policy.check_nyay22_browser_gate_contract(), [])

    def test_nyay22_adversarial_policy_contracts_are_required_in_ci(self) -> None:
        policy = load("verify_nyayone_ci")
        key = ("nyayone-policy-gate.yml", "policy-contracts")
        self.assertIn(policy.EXPECTED_NYAY22_POLICY_COMMAND, policy.REQUIRED_JOB_RUNS[key])
        workflow = policy.WORKFLOWS / key[0]
        self.assertEqual(policy.check_workflow(workflow), [])

    def test_staging_db_gate_jobs_bind_the_retention_policy_explicitly(self) -> None:
        policy = load("verify_nyayone_ci")
        expected = {
            "MENTOR_TERMINAL_RETENTION_SECONDS": "2592000",
            "MENTOR_AUDIT_LINK_RETENTION_SECONDS": "2592000",
            "MENTOR_RETENTION_MODE": "bounded_crypto_erasure",
        }
        jobs = {
            "wave1-foundation-gate.yml": "backend-postgres16-gate",
            "wave3-credential-trust-gate.yml": "credential-trust-postgres-browser",
        }
        for workflow_name, job_name in jobs.items():
            with self.subTest(workflow=workflow_name):
                document = policy.yaml.load(
                    (policy.WORKFLOWS / workflow_name).read_text(encoding="utf-8"),
                    Loader=policy._NoDuplicateBaseLoader,
                )
                job = document["jobs"][job_name]
                self.assertEqual(
                    {name: str(job["env"].get(name)) for name in expected},
                    expected,
                )

    def test_staging_authority_and_local_browser_cors_are_separate_contracts(self) -> None:
        """Seal HTTPS for staging while preserving loopback only in APP_ENV=test."""

        policy = load("verify_nyayone_ci")
        canonical = '["https://ci.nyayone.example"]'
        for workflow_name, job_name in (
            ("wave1-foundation-gate.yml", "backend-postgres16-gate"),
            ("wave3-credential-trust-gate.yml", "credential-trust-postgres-browser"),
        ):
            with self.subTest(workflow=workflow_name):
                document = policy.yaml.load(
                    (policy.WORKFLOWS / workflow_name).read_text(encoding="utf-8"),
                    Loader=policy._NoDuplicateBaseLoader,
                )
                self.assertEqual(document["jobs"][job_name]["env"]["CORS_ORIGINS"], canonical)
                self.assertEqual(
                    policy.EXPECTED_JOB_ENVS[(workflow_name, job_name)]["CORS_ORIGINS"],
                    canonical,
                )

        document = policy.yaml.load(
            (policy.WORKFLOWS / "wave3-credential-trust-gate.yml").read_text(
                encoding="utf-8"
            ),
            Loader=policy._NoDuplicateBaseLoader,
        )
        start = next(
            step
            for step in document["jobs"]["credential-trust-postgres-browser"]["steps"]
            if step.get("name") == "Start OTP, backend and frontend"
        )
        self.assertEqual(start["env"]["APP_ENV"], "test")
        self.assertEqual(
            start["env"]["CORS_ORIGINS"],
            '["http://127.0.0.1:1170","http://localhost:1170",'
            '"http://127.0.0.1:1190"]',
        )

    def test_browser_producer_cannot_be_removed_masked_or_detached_from_live_backend(self) -> None:
        policy = load("verify_nyayone_ci")
        workflow = policy.NYAY22_REQUIRED_WORKFLOW
        original = workflow.read_text(encoding="utf-8")
        producer = policy.EXPECTED_NYAY22_BROWSER_STEP
        mutations = {
            "producer removed": original.replace(producer, "", 1),
            "failure masked": original.replace(
                "        run: npm run qa:nyay22:mentor-ceremony\n",
                "        run: npm run qa:nyay22:mentor-ceremony || true\n",
                1,
            ),
            "live backend detached": original.replace(
                "NYAY22_LIVE_API_BASE_URL: http://127.0.0.1:1171",
                "NYAY22_LIVE_API_BASE_URL: http://127.0.0.1:9999",
                1,
            ),
            "production build disabled": original.replace(
                'NYAY22_BROWSER_PRODUCTION_BUILD: "true"',
                'NYAY22_BROWSER_PRODUCTION_BUILD: "false"',
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / workflow.name
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(
                        any("NYAY-22" in failure or "canonical semantic contract" in failure
                            for failure in failures),
                        failures,
                    )

    def test_browser_failure_diagnostic_is_immediate_exact_and_privacy_safe(self) -> None:
        policy = load("verify_nyayone_ci")
        workflow = policy.NYAY22_REQUIRED_WORKFLOW
        original = workflow.read_text(encoding="utf-8")
        diagnostic = policy.EXPECTED_NYAY22_FAILURE_UPLOAD_STEP
        mutations = {
            "diagnostic removed": original.replace(diagnostic, "", 1),
            "diagnostic moved": original.replace(
                policy.EXPECTED_NYAY22_BROWSER_STEP + diagnostic,
                diagnostic + policy.EXPECTED_NYAY22_BROWSER_STEP,
                1,
            ),
            "broad evidence path": original.replace(
                "test-results/nyay22-browser/failure.json",
                "test-results",
                1,
            ),
            "missing-file accepted": original.replace(
                "if-no-files-found: error",
                "if-no-files-found: ignore",
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / workflow.name
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_workflow(candidate)
                    self.assertTrue(failures, failures)

    def test_wave3_attestation_requires_exact_fourteen_row_nyay22_inventory(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        self.assertIn(
            ("nyay22-browser", "nyay22-browser/results.json", "nyay22-browser"),
            exporter.PROFILE_SPECS["wave3"],
        )
        self.assertEqual(
            exporter.INVENTORY_CONTRACTS.get("nyay22-browser"),
            (
                "rows",
                "name",
                14,
                "d9febbb9662d7f6e436e214936fc5111e4202e0c8d463b31275be13353315257",
            ),
        )

    def test_browser_runner_is_production_build_and_live_backend_bound(self) -> None:
        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_BROWSER_GATE.read_text(encoding="utf-8")
        for required in (
            "NYAY22_BROWSER_PRODUCTION_BUILD",
            "NYAY22_LIVE_API_BASE_URL",
            "NYAY22_BROWSER_FAILURE_PATH",
            "buildVite",
            "previewVite",
            "live-backend-positive-lifecycle",
            "NYAY22_LIVE_FIXTURE_PATH",
        ):
            self.assertIn(required, source)
        self.assertNotIn("createViteServer", source)
        self.assertIn(
            "verifyMentorIdentity",
            policy.NYAY22_BROWSER_HARNESS_ENTRY.read_text(encoding="utf-8"),
        )

    def test_live_fixture_seed_and_positive_lifecycle_are_required_in_wave3(self) -> None:
        policy = load("verify_nyayone_ci")
        workflow = policy.NYAY22_REQUIRED_WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(workflow.count(policy.EXPECTED_NYAY22_LIVE_SEED_STEP), 1)
        self.assertIn(
            policy.EXPECTED_NYAY22_LIVE_SEED_STEP
            + policy.EXPECTED_NYAY22_BROWSER_STEP,
            workflow,
        )
        self.assertEqual(policy.check_nyay22_browser_gate_contract(), [])

    def test_live_fixture_capability_is_runner_temp_only_and_source_sealed(self) -> None:
        policy = load("verify_nyayone_ci")
        seed = policy.NYAY22_BROWSER_SEED.read_text(encoding="utf-8")
        test = policy.NYAY22_BROWSER_SEED_TEST.read_text(encoding="utf-8")
        runner = policy.NYAY22_BROWSER_GATE.read_text(encoding="utf-8")
        self.assertIn("RUNNER_TEMP", seed)
        self.assertIn("O_EXCL", seed)
        self.assertIn("S_IRUSR | stat.S_IWUSR", seed)
        self.assertNotIn("print(fixture", seed)
        self.assertIn("NYAY22_LIVE_FIXTURE_PATH", runner)
        self.assertIn("await rm(target, { force: true })", runner)
        self.assertIn(
            "liveLifecycle.required === true && liveLifecycle.bound === true",
            runner,
        )
        self.assertIn("test_private_fixture_writer_is_exclusive_mode_0600", test)
        self.assertEqual(policy.check_nyay22_browser_gate_contract(), [])

    def test_browser_transitive_harness_and_fixture_are_sealed(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(policy.check_nyay22_browser_gate_contract(), [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source_path, argument, diagnostic in (
                (
                    policy.NYAY22_BROWSER_HARNESS_ENTRY,
                    "harness_entry_path",
                    "browser harness entry SHA-256",
                ),
                (
                    policy.NYAY22_BROWSER_FIXTURE,
                    "fixture_path",
                    "browser fixture SHA-256",
                ),
                (
                    policy.NYAY22_BROWSER_SEED,
                    "seed_path",
                    "private live-fixture seed SHA-256",
                ),
                (
                    policy.NYAY22_BROWSER_SEED_TEST,
                    "seed_test_path",
                    "private live-fixture seed tests SHA-256",
                ),
            ):
                candidate = root / source_path.name
                candidate.write_bytes(source_path.read_bytes() + b"\n")
                failures = policy.check_nyay22_browser_gate_contract(
                    **{argument: candidate}
                )
                self.assertTrue(
                    any(diagnostic in row for row in failures),
                    failures,
                )

    def test_native_postgres_producer_is_exactly_once_and_final_in_db_gate(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(policy.check_db_gate_contract(), [])
        source = policy.DB_GATE.read_text(encoding="utf-8")
        self.assertEqual(source.count("scripts/nyay22_postgres_mentor_gate.py"), 1)
        self.assertIn(policy.EXPECTED_NYAY22_DB_GATE_STAGE, source)
        self.assertLess(
            source.index("scripts/nyay19_postgres_auth_retention_gate.py"),
            source.index("scripts/nyay22_postgres_mentor_gate.py"),
        )

    def test_native_postgres_summary_is_promoted_into_closed_wave3_evidence(self) -> None:
        policy = load("verify_nyayone_ci")
        exporter = load("prepare_uploadable_evidence")
        source = policy.DB_GATE.read_text(encoding="utf-8")
        self.assertIn(policy.EXPECTED_NYAY22_DB_GATE_EVIDENCE_PROMOTION, source)
        self.assertIn(
            (
                "nyay22-postgres",
                "nyay22-postgres/summary.json",
                "nyay22-postgres",
            ),
            exporter.PROFILE_SPECS["wave3"],
        )
        self.assertEqual(
            exporter.INVENTORY_CONTRACTS.get("nyay22-postgres"),
            (
                "oracles",
                "id",
                len(policy.EXPECTED_NYAY22_POSTGRES_ORACLES),
                policy.EXPECTED_NYAY22_POSTGRES_ORACLE_INVENTORY_SHA256,
            ),
        )

    def test_native_postgres_upload_projection_is_closed_world_and_fail_closed(self) -> None:
        policy = load("verify_nyayone_ci")
        exporter = load("prepare_uploadable_evidence")
        rows = [
            {"id": oracle_id, "status": "PASS", "assertions": 1}
            for oracle_id in policy.EXPECTED_NYAY22_POSTGRES_ORACLES
        ]
        report = {
            "schema_version": policy.EXPECTED_NYAY22_POSTGRES_SCHEMA,
            "status": "PASS",
            "classification": "EXECUTED",
            "postgres_major": 16,
            "pgvector_present": True,
            "oracles": rows,
            "summary": {"passed": len(rows), "total": len(rows)},
        }
        projected, failure = exporter._safe_result(
            "nyay22-postgres", report, "nyay22-postgres"
        )
        self.assertIsNone(failure)
        self.assertEqual(projected["producerState"], "pass")
        self.assertTrue(projected["inventoryComplete"])

        mutations = {
            "empty assertions": {**report, "oracles": [], "summary": {"passed": 0, "total": 0}},
            "stale inventory": {
                **report,
                "oracles": rows[:-1],
                "summary": {"passed": len(rows) - 1, "total": len(rows) - 1},
            },
            "summary mismatch": {**report, "summary": {"passed": 0, "total": len(rows)}},
            "PII field": {**report, "actor": "forbidden"},
            "nonexecuted classification": {**report, "classification": "CONTRACT_CHECK_ONLY"},
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                projected, failure = exporter._safe_result(
                    "nyay22-postgres", mutation, "nyay22-postgres"
                )
                self.assertIsNone(projected)
                self.assertIsNotNone(failure)

    def test_native_postgres_source_and_contract_are_exactly_sealed(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(policy.check_nyay22_postgres_gate_contract(), [])

    def test_nyay19_subject_erasure_integration_is_exactly_sealed(self) -> None:
        policy = load("verify_nyayone_ci")
        self.assertEqual(
            policy.check_nyay22_nyay19_erasure_integration_contract(), []
        )

    def test_nyay19_subject_erasure_integration_absence_or_drift_fails_closed(
        self,
    ) -> None:
        policy = load("verify_nyayone_ci")
        original = policy.NYAY22_NYAY19_ERASURE_TEST.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test_nyay22_nyay19_erasure_integration.py"
            missing = policy.check_nyay22_nyay19_erasure_integration_contract(path)
            self.assertTrue(any("missing or unsafe" in row for row in missing))

            path.write_text(original.replace(
                'counts["materialized_expirations"] == 0',
                'counts["materialized_expirations"] >= 0',
                1,
            ), encoding="utf-8")
            failures = policy.check_nyay22_nyay19_erasure_integration_contract(path)
            self.assertTrue(any("semantic contract" in row for row in failures))

    def test_native_postgres_source_or_contract_drift_fails_closed(self) -> None:
        policy = load("verify_nyayone_ci")
        producer_source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        contract = json.loads(
            policy.NYAY22_POSTGRES_CONTRACT.read_text(encoding="utf-8")
        )
        contract_mutations = {
            "inventory item removed": (
                {**contract, "oracleInventory": contract["oracleInventory"][:-1]},
                "oracle inventory",
            ),
            "declared count drift": (
                {**contract, "oracleCount": contract["oracleCount"] - 1},
                "oracle count",
            ),
            "application head drift": (
                {**contract, "applicationHead": "0022_nyay9_owner_profile_api"},
                "application head",
            ),
            "previous revision drift": (
                {**contract, "previousRevision": "0021_nyay5_profile_boundary"},
                "previous revision",
            ),
            "closed-world field added": (
                {**contract, "unsealedEscape": True},
                "closed-world",
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            producer_path = root / "nyay22_postgres_mentor_gate.py"
            contract_path = root / "nyay22-mentor-postgres-contract.json"
            producer_path.write_text(producer_source, encoding="utf-8")
            contract_path.write_text(
                policy.NYAY22_POSTGRES_CONTRACT.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            self.assertEqual(
                policy.check_nyay22_postgres_gate_contract(
                    producer_path=producer_path,
                    contract_path=contract_path,
                ),
                [],
            )

            producer_path.write_text(producer_source + "\n", encoding="utf-8")
            failures = policy.check_nyay22_postgres_gate_contract(
                producer_path=producer_path,
                contract_path=contract_path,
            )
            self.assertTrue(any("producer SHA-256" in row for row in failures), failures)
            producer_path.write_text(producer_source, encoding="utf-8")

            for label, (mutation, diagnostic) in contract_mutations.items():
                with self.subTest(label=label):
                    contract_path.write_text(
                        json.dumps(mutation, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    failures = policy.check_nyay22_postgres_gate_contract(
                        producer_path=producer_path,
                        contract_path=contract_path,
                    )
                    self.assertTrue(
                        any(diagnostic in row.lower() for row in failures),
                        failures,
                    )

    def test_native_postgres_producer_constants_cannot_drift_from_contract(self) -> None:
        policy = load("verify_nyayone_ci")
        original = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        mutations = {
            "producer head drift": (
                original.replace(
                    'APPLICATION_HEAD = "0023_nyay22_mentor_ceremony"',
                    'APPLICATION_HEAD = "0022_nyay9_owner_profile_api"',
                    1,
                ),
                "application head",
            ),
            "producer previous drift": (
                original.replace(
                    'PREVIOUS_REVISION = "0022_nyay9_owner_profile_api"',
                    'PREVIOUS_REVISION = "0021_nyay5_profile_boundary"',
                    1,
                ),
                "previous revision",
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            producer_path = root / "nyay22_postgres_mentor_gate.py"
            contract_path = root / "nyay22-mentor-postgres-contract.json"
            contract_path.write_text(
                policy.NYAY22_POSTGRES_CONTRACT.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            for label, (source, diagnostic) in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(source, original)
                    producer_path.write_text(source, encoding="utf-8")
                    failures = policy.check_nyay22_postgres_gate_contract(
                        producer_path=producer_path,
                        contract_path=contract_path,
                    )
                    self.assertTrue(
                        any(diagnostic in row.lower() for row in failures),
                        failures,
                    )

    def test_native_postgres_semantic_oracles_cannot_be_weakened_behind_the_seal(self) -> None:
        policy = load("verify_nyayone_ci")
        original = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        mutations = {
            "downgrade TOCTOU proof detached": original.replace(
                "toctou_assertions = _migration_downgrade_toctou_oracle(database_url)",
                "toctou_assertions = 7",
                1,
            ),
            "downgrade ACCESS EXCLUSIVE proof weakened": original.replace(
                'wait_row[0] == "Lock"',
                'wait_row[0] == "Client"',
                1,
            ),
            "retention rollback injection weakened": original.replace(
                "if calls == 7:", "if calls == 8:", 1
            ),
            "oversize hard cap weakened": original.replace(
                "oversize_sessions=256", "oversize_sessions=255", 1
            ),
            "reverse deletion order removed": original.replace(
                'for order in ("action_first", "revoke_first"):',
                'for order in ("action_first",):',
                1,
            ),
            "cross-actor deletion proof detached": original.replace(
                "_deletion_historical_subject_actor_isolation_oracle(app, factory)",
                "8",
                1,
            ),
            "cross-actor deletion snapshot weakened": original.replace(
                "if snapshot_b() != before_b:",
                "if False:",
                1,
            ),
            "session read-only proof detached": original.replace(
                "_session_read_only_idle_boundary_oracle(app, factory)",
                "6",
                1,
            ),
            "session read-only timestamp check weakened": original.replace(
                "after_read.last_seen_at != original_last_seen",
                "False",
                1,
            ),
            "recovery active-set proof detached": original.replace(
                "_recovery_active_set_snapshot_oracle(app, factory)",
                "8",
                1,
            ),
            "recovery active-set equality weakened": original.replace(
                "after != before",
                "False",
                1,
            ),
            "expired-cookie owner-login race detached": original.replace(
                "_expired_mentor_owner_login_race_oracle(app, factory)",
                "24",
                1,
            ),
            "expired-cookie reverse order removed": original.replace(
                'for order in ("owner_first", "mentor_first"):',
                'for order in ("owner_first",):',
                1,
            ),
            "expired-owner-cookie race detached": original.replace(
                "_expired_owner_cookie_mentor_race_oracle(app, factory)",
                "24",
                1,
            ),
            "expired-owner-cookie reverse order removed": original.replace(
                'for order in ("owner_first", "mentor_first"):',
                'for order in ("owner_first",):',
                2,
            ),
            "retention catalog omitted": original.replace(
                '            "mentor_retention_blocked_graphs",\n', "", 1
            ),
            "required retention oracle detached": original.replace(
                "            _retention_oversize_oracle(app, factory),",
                "            _retention_atomic_oracle(app, factory),",
                1,
            ),
            "held-node contention proof detached": original.replace(
                "held_node_assertions = _retention_held_node_atomicity_proof(app, factory)",
                "held_node_assertions = 8",
                1,
            ),
            "same-run live-expiry proof detached": original.replace(
                "live_expiry_assertions = _retention_live_expiry_same_run_proof(app, factory)",
                "live_expiry_assertions = 7",
                1,
            ),
            "same-run materialization count weakened": original.replace(
                'counts.get("materialized_expirations", 0) < 1',
                'counts.get("materialized_expirations", 0) < 0',
                1,
            ),
            "held-node settlement observer weakened": original.replace(
                'wait_event_type == "Lock"',
                'wait_event_type == "Client"',
                1,
            ),
            "orphan erasure proof detached": original.replace(
                "orphan_assertions = _retention_orphan_erasure_proof(app, factory)",
                "orphan_assertions = 14",
                1,
            ),
            "orphan closed inventory weakened": original.replace(
                'counts.get("severed_graphs") != 2',
                'counts.get("severed_graphs") != 1',
                1,
            ),
            "NYAY-19 subject erasure proof detached": original.replace(
                "_nyay19_subject_erasure_authority_oracle(app, factory)",
                "24",
                1,
            ),
            "NYAY-19 erasure mode coverage weakened": original.replace(
                'for mode in ("anonymise", "delete"):',
                'for mode in ("anonymise",):',
                1,
            ),
            "report accepts zero assertions": original.replace(
                'row.get("assertions", 0) <= 0',
                'row.get("assertions", 0) < 0',
                1,
            ),
            "report accepts extra fields": original.replace(
                "set(report) != expected_report_fields",
                "False",
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            producer_path = root / "nyay22_postgres_mentor_gate.py"
            contract_path = root / "nyay22-mentor-postgres-contract.json"
            contract_path.write_bytes(policy.NYAY22_POSTGRES_CONTRACT.read_bytes())
            for label, source in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(source, original)
                    producer_path.write_text(source, encoding="utf-8")
                    failures = policy.check_nyay22_postgres_gate_contract(
                        producer_path=producer_path,
                        contract_path=contract_path,
                    )
                    self.assertTrue(
                        any("semantic" in row.lower() for row in failures),
                        failures,
                    )

    def test_native_retention_gate_requires_held_node_and_orphan_proofs(self) -> None:
        """The retention row may not hide partial or orphan graph erasure gaps."""

        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        self.assertIn("def _retention_held_node_atomicity_proof(", source)
        self.assertEqual(
            source.count("_retention_held_node_atomicity_proof(app, factory)"),
            1,
        )
        self.assertIn("def _retention_orphan_erasure_proof(", source)
        self.assertEqual(
            source.count("_retention_orphan_erasure_proof(app, factory)"),
            1,
        )
        for marker in (
            "pg_stat_activity",
            'wait_event_type == "Lock"',
            '"40P01"',
            "bit-identical",
            "orphan",
        ):
            self.assertIn(marker, source)

    def test_native_migration_gate_requires_downgrade_toctou_proof(self) -> None:
        """A concurrent insert must make downgrade refuse without dropping tables."""

        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        self.assertIn("def _migration_downgrade_toctou_oracle(", source)
        self.assertEqual(
            source.count("_migration_downgrade_toctou_oracle(database_url)"),
            1,
        )
        for marker in (
            "ACCESS EXCLUSIVE",
            "pg_stat_activity",
            'wait_event_type == "Lock"',
            "all mentor tables were not preserved",
            "downgrade accepted a concurrent durable row",
        ):
            self.assertIn(marker, source)

    def test_native_deletion_gate_rejects_historical_subject_cross_actor_reuse(
        self,
    ) -> None:
        """Deletion authority may not traverse another actor's historical proof."""

        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        self.assertIn(
            "def _deletion_historical_subject_actor_isolation_oracle(",
            source,
        )
        self.assertEqual(
            source.count(
                "_deletion_historical_subject_actor_isolation_oracle(app, factory)"
            ),
            1,
        )
        for marker in (
            "historical provider-subject actor-isolation",
            "unrelated actor graph changed during authority deletion",
            "deleted actor retained live authority",
        ):
            self.assertIn(marker, source)

    def test_native_session_read_gate_preserves_the_original_idle_boundary(
        self,
    ) -> None:
        """A read probe is non-authoritative and cannot extend idle lifetime."""

        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        self.assertIn("def _session_read_only_idle_boundary_oracle(", source)
        self.assertEqual(
            source.count("_session_read_only_idle_boundary_oracle(app, factory)"),
            1,
        )
        for marker in (
            "session GET changed last_seen_at",
            "original idle boundary did not expire authority",
            'expired_result != (410, "SESSION_EXPIRED")',
        ):
            self.assertIn(marker, source)

    def test_native_recovery_exchange_requires_the_exact_verified_active_set(
        self,
    ) -> None:
        """A post-verify session generation must invalidate recovery atomically."""

        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        self.assertIn("def _recovery_active_set_snapshot_oracle(", source)
        self.assertEqual(
            source.count("_recovery_active_set_snapshot_oracle(app, factory)"),
            1,
        )
        for marker in (
            '"mandatoryRevocationSessionIds"',
            'denied != (409, "CONCURRENT_STATE_CHANGED")',
            "after != before",
            "recovery active-set mismatch mutated authority",
        ):
            self.assertIn(marker, source)

    def test_native_owner_login_races_an_expired_mentor_cookie_both_orders(
        self,
    ) -> None:
        """Owner login and every mentor terminal path share bounded locking."""

        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        self.assertIn("def _expired_mentor_owner_login_race_oracle(", source)
        self.assertEqual(
            source.count("_expired_mentor_owner_login_race_oracle(app, factory)"),
            1,
        )
        for marker in (
            'for operation in ("rotate", "revoke", "logout"):',
            'for order in ("owner_first", "mentor_first"):',
            'text("SHOW lock_timeout")',
            '"40P01"',
            "owner/mentor race retained incompatible session classes",
        ):
            self.assertIn(marker, source)

    def test_native_mentor_request_races_an_expired_owner_cookie_both_orders(
        self,
    ) -> None:
        """An elapsed owner cookie may not invert User/AuthSession lock order."""

        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        self.assertIn("def _expired_owner_cookie_mentor_race_oracle(", source)
        self.assertEqual(
            source.count("_expired_owner_cookie_mentor_race_oracle(app, factory)"),
            1,
        )
        for marker in (
            'for operation in ("read", "rotate"):',
            'for order in ("owner_first", "mentor_first"):',
            'text("SHOW lock_timeout")',
            'text("SHOW statement_timeout")',
            '"40P01"',
            "expired owner boundary was not materialized exactly",
            "owner-cookie race retained incompatible session classes",
            "owner-cookie race changed unrelated authority",
        ):
            self.assertIn(marker, source)

    def test_native_retention_gate_covers_same_run_expiry_and_owner_ledger(
        self,
    ) -> None:
        """Materialization and owner prerequisite evidence stay in one graph."""

        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        self.assertIn("def _retention_live_expiry_same_run_proof(", source)
        self.assertEqual(
            source.count("_retention_live_expiry_same_run_proof(app, factory)"),
            1,
        )
        for marker in (
            'operation="owner-create-mentor-prerequisites"',
            "owner prerequisite idempotency ledger was not graph-bound",
            'counts.get("materialized_expirations", 0) < 1',
            "live expiry was not severed in the same retention run",
        ):
            self.assertIn(marker, source)

    def test_native_subject_erasure_retires_mentor_authority_atomically(
        self,
    ) -> None:
        """NYAY-19 anonymise/delete cannot leave a mentor bearer or cross actor."""

        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        self.assertIn("def _nyay19_subject_erasure_authority_oracle(", source)
        self.assertEqual(
            source.count("_nyay19_subject_erasure_authority_oracle(app, factory)"),
            1,
        )
        for marker in (
            'for mode in ("anonymise", "delete"):',
            'for operation in ("rotate", "read", "exchange"):',
            "threading.Barrier(2)",
            "NYAY-19 subject erasure left mentor authority",
            "unrelated subject changed during NYAY-19 erasure",
        ):
            self.assertIn(marker, source)

    def test_native_report_validator_is_closed_world_and_nonvacuous(self) -> None:
        policy = load("verify_nyayone_ci")
        source = policy.NYAY22_POSTGRES_GATE.read_text(encoding="utf-8")
        for marker in (
            "set(report) != expected_report_fields",
            'set(row) != {"id", "status", "assertions"}',
            'type(row.get("assertions")) is not int',
            'row.get("assertions", 0) <= 0',
        ):
            self.assertIn(marker, source)

    def test_native_postgres_stage_removal_masking_or_reordering_fails_closed(self) -> None:
        policy = load("verify_nyayone_ci")
        original = policy.DB_GATE.read_text(encoding="utf-8")
        stage = policy.EXPECTED_NYAY22_DB_GATE_STAGE
        mutations = {
            "stage removed": original.replace(stage, "", 1),
            "failure masked": original.replace(
                "  --output test-results/nyay22-postgres/summary.json\n",
                "  --output test-results/nyay22-postgres/summary.json || true\n",
                1,
            ),
            "stage before inherited lifecycle": original.replace(stage, "", 1).replace(
                'echo "== NYAY-19 authentication-retention lifecycle gate',
                stage + 'echo "== NYAY-19 authentication-retention lifecycle gate',
                1,
            ),
            "evidence promotion removed": original.replace(
                policy.EXPECTED_NYAY22_DB_GATE_EVIDENCE_PROMOTION,
                "",
                1,
            ),
            "evidence promotion failure masked": original.replace(
                '  "$REPO_ROOT/test-results/nyay22-postgres/summary.json"\n',
                '  "$REPO_ROOT/test-results/nyay22-postgres/summary.json" || true\n',
                1,
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "db_gate.sh"
            for label, mutated in mutations.items():
                with self.subTest(label=label):
                    self.assertNotEqual(mutated, original)
                    candidate.write_text(mutated, encoding="utf-8")
                    failures = policy.check_db_gate_contract(candidate)
                    self.assertTrue(
                        any("NYAY-22" in failure for failure in failures),
                        failures,
                    )

    def test_top_level_policy_cannot_omit_either_nyay22_release_gate(self) -> None:
        policy_source = (HERE / "verify_nyayone_ci.py").read_text(encoding="utf-8")
        main_source = policy_source[policy_source.index("def main()") :]
        self.assertIn("check_nyay22_browser_gate_contract()", main_source)
        self.assertIn("check_nyay22_postgres_gate_contract()", main_source)
        self.assertIn(
            "check_nyay22_nyay19_erasure_integration_contract()", main_source
        )
        self.assertIn("check_db_gate_contract()", main_source)


if __name__ == "__main__":
    unittest.main()
