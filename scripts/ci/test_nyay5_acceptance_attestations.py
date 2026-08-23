#!/usr/bin/env python3
"""Fail-closed tests for the NYAY-5 acceptance-attestation producer."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Nyay5AcceptanceAttestationTests(unittest.TestCase):
    def _fixture(self, root: Path):
        producer = load("nyay5_acceptance_attestations")
        manifest = load("evidence_manifest")
        browser_root = root / "nyay5-browser"
        screenshots = browser_root / "screenshots"
        screenshots.mkdir(parents=True)
        (screenshots / "mobile.png").write_bytes(b"synthetic-mobile-screenshot")
        (screenshots / "desktop.png").write_bytes(b"synthetic-desktop-screenshot")

        browser = {
            "gate": "nyay5_profile_browser",
            "target": "isolated-loopback-real-api-postgresql-chromium",
            "status": "PASS",
            "executed": True,
            "total": 2,
            "passed": 2,
            "failed": 0,
            "inventoryExact": True,
            "rows": [
                {
                    "name": "runtime_chromium",
                    "pass": True,
                    "metrics": {"executed": True},
                },
                {
                    "name": "evidence_privacy_and_mutants",
                    "pass": True,
                    "metrics": {"executed": True},
                },
            ],
            "artifacts": {"screenshots": 2},
            "failureClass": None,
            "failureStage": None,
            "failureCode": None,
        }
        orchestrator = {
            "gate": "nyay5-profile-browser-orchestrator-v1",
            "executed": True,
            "status": "PASS",
            "services": {
                "postgresReady": True,
                "apiReady": True,
                "otpCaptureReady": True,
                "productionPreviewReady": True,
                "serviceWorkerActive": True,
            },
            "scratchCleanup": {
                "created": 1,
                "removed": 1,
                "inventoryMatch": True,
            },
            "browserExitCode": 0,
            "serviceLogsCaptured": True,
        }
        postgres = {
            "gate": "nyay5_postgres",
            "status": "PASS",
            "executed": True,
            "privacy_scan": {"scanned": True, "findings": 0, "passed": True},
        }
        otp_postgres = {
            "gate": "nyay4_postgres_otp",
            "status": "PASS",
            "executed": True,
            "privacy_findings": 0,
        }
        paths = {
            "browser": browser_root / "results.json",
            "orchestrator": browser_root / "orchestrator-summary.json",
            "postgres": root / "nyay5-postgres.json",
            "otp_postgres": root / "nyay4-postgres.json",
            "manifest_root": browser_root,
        }
        for key, payload in (
            ("browser", browser),
            ("orchestrator", orchestrator),
            ("postgres", postgres),
            ("otp_postgres", otp_postgres),
        ):
            paths[key].write_text(json.dumps(payload), encoding="utf-8")
        count, failures = manifest.seal(browser_root)
        self.assertEqual(failures, [])
        self.assertEqual(count, 4)
        return producer, paths, browser, orchestrator, postgres, otp_postgres

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
            "GITHUB_EVENT_NAME": "pull_request",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_REF": "refs/pull/7/merge",
            "GITHUB_BASE_REF": "main",
        }

    def test_real_inputs_and_executed_commands_produce_exact_pass_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            producer, paths, *_ = self._fixture(Path(directory))
            commands: list[tuple[tuple[str, ...], Path]] = []

            def run(command, cwd):
                commands.append((tuple(command), cwd))
                return True

            report = producer.build_attestation(
                **paths,
                root=Path(directory),
                environment=self._environment(),
                command_runner=run,
                head_reader=lambda _root: "a" * 40,
            )
            self.assertEqual(report["gate"], "nyay5_acceptance_attestations_v1")
            self.assertEqual(report["status"], "PASS")
            self.assertIs(report["executed"], True)
            self.assertEqual(
                [row["id"] for row in report["executions"]],
                list(producer.EXECUTION_IDS),
            )
            self.assertTrue(all(row["pass"] is True for row in report["executions"]))
            self.assertTrue(all(row["executed"] is True for row in report["executions"]))
            self.assertTrue(all(row["skipped"] is False for row in report["executions"]))
            self.assertEqual(
                [command for command, _ in commands],
                list(producer.EXPECTED_COMMANDS.values()),
            )

    def test_artifact_and_ci_mutants_fail_their_exact_execution_rows(self) -> None:
        mutations = {
            "missing screenshot": "evidence:screenshots",
            "service logs not captured": "evidence:service-logs",
            "privacy finding": "evidence:privacy-scan",
            "tampered manifest": "evidence:sha256-manifest",
            "failed native command": "native:frontend-lint",
            "non-merge pull request ref": "ci:prospective-merge",
            "failed required-job oracle": "ci:required-job-fail-closed",
        }
        for label, expected_id in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                producer, paths, _, orchestrator, postgres, _ = self._fixture(root)
                environment = self._environment()
                failed_command = None
                if label == "missing screenshot":
                    (paths["manifest_root"] / "screenshots" / "mobile.png").unlink()
                elif label == "service logs not captured":
                    changed = copy.deepcopy(orchestrator)
                    changed["serviceLogsCaptured"] = False
                    paths["orchestrator"].write_text(json.dumps(changed), encoding="utf-8")
                elif label == "privacy finding":
                    changed = copy.deepcopy(postgres)
                    changed["privacy_scan"]["findings"] = 1
                    changed["privacy_scan"]["passed"] = False
                    paths["postgres"].write_text(json.dumps(changed), encoding="utf-8")
                elif label == "tampered manifest":
                    paths["browser"].write_text("{}", encoding="utf-8")
                elif label == "failed native command":
                    failed_command = producer.EXPECTED_COMMANDS["native:frontend-lint"]
                elif label == "non-merge pull request ref":
                    environment["GITHUB_REF"] = "refs/heads/feature"
                elif label == "failed required-job oracle":
                    failed_command = producer.EXPECTED_COMMANDS[
                        "ci:required-job-fail-closed"
                    ]

                def run(command, _cwd):
                    return tuple(command) != failed_command

                report = producer.build_attestation(
                    **paths,
                    root=root,
                    environment=environment,
                    command_runner=run,
                    head_reader=lambda _root: "a" * 40,
                )
                rows = {row["id"]: row for row in report["executions"]}
                self.assertEqual(report["status"], "FAIL")
                self.assertIs(rows[expected_id]["pass"], False)

    def test_strict_json_and_symlink_evidence_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            producer, paths, browser, *_ = self._fixture(root)
            paths["browser"].write_text(
                '{"gate":"nyay5_profile_browser","gate":"forged"}',
                encoding="utf-8",
            )
            report = producer.build_attestation(
                **paths,
                root=root,
                environment=self._environment(),
                command_runner=lambda _command, _cwd: True,
                head_reader=lambda _root: "a" * 40,
            )
            browser_row = next(
                row for row in report["executions"]
                if row["id"] == "evidence:browser-report"
            )
            self.assertIs(browser_row["pass"], False)

            paths["browser"].unlink()
            external = root / "forged-browser.json"
            external.write_text(json.dumps(browser), encoding="utf-8")
            paths["browser"].symlink_to(external)
            symlink_report = producer.build_attestation(
                **paths,
                root=root,
                environment=self._environment(),
                command_runner=lambda _command, _cwd: True,
                head_reader=lambda _root: "a" * 40,
            )
            symlink_browser_row = next(
                row for row in symlink_report["executions"]
                if row["id"] == "evidence:browser-report"
            )
            self.assertIs(symlink_browser_row["executed"], False)
            self.assertIs(symlink_browser_row["pass"], False)


if __name__ == "__main__":
    unittest.main()
