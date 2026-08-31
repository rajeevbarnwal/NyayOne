#!/usr/bin/env python3
"""NYAY-14 RED contracts for exact-head QA evidence and guarded merge control.

This test module intentionally lands before ``nyay14_evidence_gate.py`` and the
operator-facing templates.  Every test loads the subject lazily and first
requires the implementation to exist.  That keeps the initial RED result
granular while preventing negative cases from passing merely because a missing
CLI happened to return a non-zero status.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUBJECT = HERE / "nyay14_evidence_gate.py"
CONTRACT = HERE / "nyay14_evidence_contract.json"
FIXTURE = HERE / "fixtures/nyay14/seeded_zero_assertions.json"
TEMPLATE_ROOT = ROOT / "docs/operations/nyay14-exact-head-evidence"
TEMPLATES = {
    "readme": TEMPLATE_ROOT / "README.md",
    "provenance": TEMPLATE_ROOT / "templates/PROVENANCE.json",
    "raw_logs": TEMPLATE_ROOT / "templates/RAW_LOG_INVENTORY.json",
    "visual": TEMPLATE_ROOT / "templates/VISUAL_COMPARISON_MATRIX.json",
    "quality": TEMPLATE_ROOT / "templates/QUALITY_RESULTS.json",
    "comment": TEMPLATE_ROOT / "templates/PR_COMMENT.md",
    "merge": TEMPLATE_ROOT / "templates/GUARDED_MERGE.md",
}

SCHEMA_VERSION = "nyay14-evidence/v1"
REPOSITORY = "rajeevbarnwal/NyayOne"
BASE_SHA = "71bd18534c9fcf3f93c7341bbdb69f4e60792442"
HEAD_SHA = "1111111111111111111111111111111111111111"
MERGE_SHA = "2222222222222222222222222222222222222222"
OTHER_SHA = "3333333333333333333333333333333333333333"
CLASSIFICATIONS = ("PASS", "FAIL", "BLOCKED", "HEAD_CHANGED", "handoff-only")
RAW_CATEGORIES = (
    "backend",
    "postgresql-migration",
    "postgresql-concurrency",
    "frontend-native",
    "chromium",
)


def load_subject(test_case: unittest.TestCase, contract: str) -> ModuleType:
    test_case.assertTrue(
        SUBJECT.is_file(),
        f"{contract}: RED — scripts/ci/nyay14_evidence_gate.py is not implemented",
    )
    spec = importlib.util.spec_from_file_location("nyay14_evidence_gate", SUBJECT)
    test_case.assertIsNotNone(spec, f"{contract}: subject import spec is unavailable")
    test_case.assertIsNotNone(spec.loader, f"{contract}: subject loader is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    test_case.assertEqual(
        getattr(module, "SCHEMA_VERSION", None),
        SCHEMA_VERSION,
        f"{contract}: subject must publish the exact schema version",
    )
    return module


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finding_codes(findings: object) -> set[str]:
    if isinstance(findings, dict):
        values = findings.get("codes", [])
    else:
        values = findings
    return {
        value if isinstance(value, str) else value.get("code")
        for value in values
        if isinstance(value, (str, dict))
    }


def canonical_provenance() -> dict[str, object]:
    return {
        "repository": REPOSITORY,
        "base": BASE_SHA,
        "reviewedHead": HEAD_SHA,
        "remoteHead": HEAD_SHA,
        "prospectiveMerge": MERGE_SHA,
        "capturedAt": "2026-08-25T18:00:00Z",
        "runtime": {
            "os": "synthetic-linux",
            "architecture": "synthetic-x64",
            "python": "3.12.0",
            "node": "22.0.0",
            "chromium": "synthetic-1",
        },
    }


def create_raw_logs(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, category in enumerate(RAW_CATEGORIES, 1):
        path = root / "raw" / f"{category}.json"
        write_json(
            path,
            {
                "schemaVersion": SCHEMA_VERSION,
                "assertions": [
                    {"id": f"{category}-assertion", "pass": True, "executed": 1}
                ],
            },
        )
        rows.append(
            {
                "id": f"raw-{index}",
                "category": category,
                "path": path.relative_to(root).as_posix(),
                "sha256": digest(path),
            }
        )
    return rows


def canonical_package(root: Path) -> dict[str, object]:
    raw_logs = create_raw_logs(root)
    artifact_ids = [row["id"] for row in raw_logs]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "claimedVerdict": "PASS",
        "provenance": canonical_provenance(),
        "rawLogs": raw_logs,
        "assertionGroups": [
            {
                "id": "required-gates",
                "executed": len(raw_logs),
                "passed": len(raw_logs),
                "failed": 0,
                "artifactIds": artifact_ids,
            }
        ],
        "metrics": [
            {
                "id": "required-gate-count",
                "value": len(raw_logs),
                "artifactId": raw_logs[0]["id"],
                "sha256": raw_logs[0]["sha256"],
                "jsonPointer": "/assertions",
            }
        ],
        "visualComparisons": [
            {
                "screen": "S-04",
                "state": "initial",
                "viewport": {"width": 390, "height": 844},
                "approvedReference": "design://nyayone/revision-l/S-04/390x844",
                "testedHead": HEAD_SHA,
                "baselineArtifactId": "visual-baseline",
                "liveArtifactId": "visual-live",
                "comparisonArtifactId": "visual-comparison",
                "executed": 1,
                "metric": {"value": 0.5, "threshold": 1.0, "unit": "percent"},
            }
        ],
        "qualityResults": {
            "accessibility": {
                "executed": 1,
                "tool": "axe-core",
                "toolVersion": "synthetic-1",
                "ruleInventoryDigest": "a" * 64,
                "serious": 0,
                "critical": 0,
                "artifactId": raw_logs[0]["id"],
            },
            "privacy": {
                "executed": 1,
                "scanner": "nyayone-privacy-scanner",
                "scannerVersion": "synthetic-1",
                "findings": 0,
                "artifactId": raw_logs[1]["id"],
            },
            "credentials": {
                "executed": 1,
                "findings": 0,
                "artifactId": raw_logs[2]["id"],
            },
            "seededOracle": {
                "executed": 2,
                "planted": 2,
                "detected": 2,
                "artifactId": raw_logs[3]["id"],
            },
        },
        "readbacks": {
            "exactHead": {
                "kind": "remote-head",
                "sha": HEAD_SHA,
                "capturedAt": "2026-08-25T18:01:00Z",
                "artifactId": raw_logs[0]["id"],
            },
            "exactMerge": {
                "kind": "merge-commit",
                "sha": MERGE_SHA,
                "capturedAt": "2026-08-25T18:02:00Z",
                "artifactId": raw_logs[1]["id"],
            },
        },
        "limitations": ["none"],
    }


class Nyay14EvidenceGateRedTests(unittest.TestCase):
    maxDiff = None

    def test_01_classification_vocabulary_is_closed_and_case_sensitive(self) -> None:
        gate = load_subject(self, "NYAY14-CLASSIFICATION-VOCABULARY")
        self.assertEqual(tuple(gate.CLASSIFICATIONS), CLASSIFICATIONS)
        for invalid in ("pass", "Fail", "HEAD-CHANGED", "HANDOFF-ONLY", "UNKNOWN", ""):
            with self.subTest(invalid=invalid):
                self.assertIn("INVALID_CLASSIFICATION", gate.validate_classification(invalid))

    def test_02_classification_precedence_is_deterministic(self) -> None:
        gate = load_subject(self, "NYAY14-CLASSIFICATION-PRECEDENCE")
        cases = (
            ({"headChanged": True, "failed": True, "blocked": True}, "HEAD_CHANGED"),
            ({"failed": True, "blocked": True}, "FAIL"),
            ({"blocked": True, "handoffOnly": True}, "BLOCKED"),
            ({"handoffOnly": True}, "handoff-only"),
            ({}, "PASS"),
        )
        for state, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(gate.classify(state), expected)

    def test_03_provenance_requires_repository_base_heads_and_merge(self) -> None:
        gate = load_subject(self, "NYAY14-PROVENANCE-REQUIRED")
        for field in ("repository", "base", "reviewedHead", "remoteHead", "prospectiveMerge"):
            candidate = canonical_provenance()
            candidate.pop(field)
            with self.subTest(field=field):
                self.assertIn("MISSING_PROVENANCE", gate.validate_provenance(candidate, HEAD_SHA))

    def test_04_provenance_requires_versioned_runtime_and_tools(self) -> None:
        gate = load_subject(self, "NYAY14-PROVENANCE-RUNTIME")
        candidate = canonical_provenance()
        candidate["runtime"] = {}
        codes = finding_codes(gate.validate_provenance(candidate, HEAD_SHA))
        self.assertIn("MISSING_RUNTIME_VERSION", codes)

    def test_05_provenance_requires_full_lowercase_git_shas(self) -> None:
        gate = load_subject(self, "NYAY14-PROVENANCE-SHA")
        for value in ("abc123", "A" * 40, "g" * 40, "1" * 39, "1" * 41):
            candidate = canonical_provenance()
            candidate["reviewedHead"] = value
            with self.subTest(value=value):
                self.assertIn(
                    "INVALID_GIT_SHA",
                    finding_codes(gate.validate_provenance(candidate, HEAD_SHA)),
                )

    def test_06_remote_head_change_invalidates_claimed_pass(self) -> None:
        gate = load_subject(self, "NYAY14-HEAD-CHANGED")
        result = gate.validate_provenance(canonical_provenance(), OTHER_SHA)
        self.assertIn("HEAD_CHANGED", finding_codes(result))
        self.assertEqual(gate.classify({"headChanged": True}), "HEAD_CHANGED")

    def test_07_exact_head_readback_is_independent_and_authoritative(self) -> None:
        gate = load_subject(self, "NYAY14-EXACT-HEAD-READBACK")
        with tempfile.TemporaryDirectory() as directory:
            package = canonical_package(Path(directory))
        package["readbacks"]["exactHead"] = package["readbacks"]["exactMerge"].copy()
        codes = finding_codes(gate.validate_readbacks(package))
        self.assertIn("EXACT_HEAD_READBACK_INVALID", codes)

    def test_08_exact_merge_readback_is_independent_and_authoritative(self) -> None:
        gate = load_subject(self, "NYAY14-EXACT-MERGE-READBACK")
        with tempfile.TemporaryDirectory() as directory:
            package = canonical_package(Path(directory))
        package["readbacks"]["exactMerge"] = package["readbacks"]["exactHead"].copy()
        codes = finding_codes(gate.validate_readbacks(package))
        self.assertIn("EXACT_MERGE_READBACK_INVALID", codes)

    def test_09_raw_log_inventory_requires_every_canonical_category(self) -> None:
        gate = load_subject(self, "NYAY14-RAW-LOG-INVENTORY")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = create_raw_logs(root)
            self.assertEqual(gate.validate_raw_logs(inventory, root), [])
            for category in RAW_CATEGORIES:
                candidate = [row for row in inventory if row["category"] != category]
                with self.subTest(category=category):
                    self.assertIn(
                        "MISSING_RAW_LOG",
                        finding_codes(gate.validate_raw_logs(candidate, root)),
                    )

    def test_10_raw_artifacts_are_nonempty_regular_contained_and_listed(self) -> None:
        gate = load_subject(self, "NYAY14-RAW-LOG-FILE-SAFETY")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = create_raw_logs(root)
            target = root / str(inventory[0]["path"])
            target.write_bytes(b"")
            self.assertIn(
                "UNSAFE_RAW_LOG",
                finding_codes(gate.validate_raw_logs(inventory, root)),
            )

    def test_11_every_metric_is_traceable_to_a_raw_artifact(self) -> None:
        gate = load_subject(self, "NYAY14-METRIC-TRACEABILITY")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = canonical_package(root)
            package["metrics"][0].pop("artifactId")
            package["metrics"][0].pop("jsonPointer")
            codes = finding_codes(gate.validate_metric_traceability(package, root))
        self.assertIn("UNTRACEABLE_METRIC", codes)

    def test_12_metric_counts_reconcile_with_the_referenced_raw_rows(self) -> None:
        gate = load_subject(self, "NYAY14-METRIC-RECONCILIATION")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = canonical_package(root)
            package["metrics"][0]["value"] = 999
            codes = finding_codes(gate.validate_metric_traceability(package, root))
        self.assertIn("METRIC_VALUE_MISMATCH", codes)

    def test_13_pass_is_impossible_with_missing_assertion_groups(self) -> None:
        gate = load_subject(self, "NYAY14-MISSING-ASSERTIONS")
        codes = finding_codes(gate.validate_assertion_groups([]))
        self.assertIn("MISSING_ASSERTIONS", codes)
        self.assertNotEqual(gate.classify({"failed": bool(codes)}), "PASS")

    def test_14_pass_is_impossible_with_zero_executed_assertions(self) -> None:
        gate = load_subject(self, "NYAY14-ZERO-EXECUTED")
        group = {"id": "frontend-native", "executed": 0, "passed": 0, "failed": 0}
        codes = finding_codes(gate.validate_assertion_groups([group]))
        self.assertIn("ZERO_EXECUTED", codes)
        self.assertNotEqual(gate.classify({"failed": bool(codes)}), "PASS")

    def test_15_visual_matrix_requires_screen_state_viewport_reference_and_head(self) -> None:
        gate = load_subject(self, "NYAY14-VISUAL-MATRIX-FIELDS")
        with tempfile.TemporaryDirectory() as directory:
            package = canonical_package(Path(directory))
        row = package["visualComparisons"][0]
        for field in ("screen", "state", "viewport", "approvedReference", "testedHead"):
            candidate = row.copy()
            candidate.pop(field)
            with self.subTest(field=field):
                self.assertIn(
                    "VISUAL_ROW_INVALID",
                    finding_codes(gate.validate_visual_matrix([candidate], [row], Path("."))),
                )

    def test_16_visual_rows_require_baseline_live_and_comparison_artifacts(self) -> None:
        gate = load_subject(self, "NYAY14-VISUAL-ARTIFACTS")
        with tempfile.TemporaryDirectory() as directory:
            package = canonical_package(Path(directory))
        row = package["visualComparisons"][0]
        for field in ("baselineArtifactId", "liveArtifactId", "comparisonArtifactId"):
            candidate = row.copy()
            candidate.pop(field)
            with self.subTest(field=field):
                self.assertIn(
                    "VISUAL_ARTIFACT_MISSING",
                    finding_codes(gate.validate_visual_matrix([candidate], [row], Path("."))),
                )

    def test_17_visual_matrix_rejects_duplicates_and_unapproved_references(self) -> None:
        gate = load_subject(self, "NYAY14-VISUAL-MATRIX-EXACT")
        with tempfile.TemporaryDirectory() as directory:
            package = canonical_package(Path(directory))
        row = package["visualComparisons"][0]
        duplicate_codes = finding_codes(gate.validate_visual_matrix([row, row], [row], Path(".")))
        self.assertIn("DUPLICATE_VISUAL_ROW", duplicate_codes)
        changed = {**row, "approvedReference": "unsealed://design"}
        changed_codes = finding_codes(gate.validate_visual_matrix([changed], [row], Path(".")))
        self.assertIn("UNAPPROVED_DESIGN_REFERENCE", changed_codes)

    def test_18_accessibility_result_requires_execution_inventory_and_evidence(self) -> None:
        gate = load_subject(self, "NYAY14-ACCESSIBILITY-RESULT")
        with tempfile.TemporaryDirectory() as directory:
            package = canonical_package(Path(directory))
        result = package["qualityResults"]["accessibility"].copy()
        result["executed"] = 0
        result.pop("ruleInventoryDigest")
        codes = finding_codes(gate.validate_quality_results({"accessibility": result}))
        self.assertIn("ACCESSIBILITY_RESULT_INVALID", codes)

    def test_19_privacy_pii_and_credential_results_require_scanner_proof(self) -> None:
        gate = load_subject(self, "NYAY14-PRIVACY-RESULT")
        with tempfile.TemporaryDirectory() as directory:
            package = canonical_package(Path(directory))
        results = package["qualityResults"].copy()
        results["privacy"] = {"executed": 0, "findings": 0}
        results["credentials"] = {"executed": 0, "findings": 0}
        codes = finding_codes(gate.validate_quality_results(results))
        self.assertIn("PRIVACY_RESULT_INVALID", codes)
        self.assertIn("CREDENTIAL_RESULT_INVALID", codes)

    def test_20_seeded_oracle_requires_nonzero_execution_and_every_mutant_killed(self) -> None:
        gate = load_subject(self, "NYAY14-SEEDED-ORACLE-RESULT")
        with tempfile.TemporaryDirectory() as directory:
            package = canonical_package(Path(directory))
        results = package["qualityResults"].copy()
        results["seededOracle"] = {"executed": 2, "planted": 2, "detected": 1}
        codes = finding_codes(gate.validate_quality_results(results))
        self.assertIn("SEEDED_ORACLE_SURVIVED", codes)

    def test_21_planted_secret_and_pii_values_are_rejected_before_sealing(self) -> None:
        gate = load_subject(self, "NYAY14-PRIVACY-BEFORE-SEAL")
        canaries = (
            "person@nls.ac.in",
            "+91 98765 43210",
            "otp=429016",
            "nyayone_session=opaque-cookie-value",
            "Authorization: Bearer opaque-token-value",
            "password=unsafe-secret-value",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "raw.log").write_text("\n".join(canaries), encoding="utf-8")
            result = gate.scan_before_seal(root)
        self.assertTrue(result["codes"])
        diagnostics = json.dumps(result, sort_keys=True)
        for canary in canaries:
            self.assertNotIn(canary, diagnostics)
        self.assertFalse(result["sealAllowed"])

    def test_22_redacted_and_explicitly_synthetic_values_are_accepted(self) -> None:
        gate = load_subject(self, "NYAY14-REDACTED-SYNTHETIC")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "safe.json").write_text(
                json.dumps(
                    {
                        "email": "reviewer@example.test",
                        "mobile": "***3210",
                        "otp": "[REDACTED]",
                        "cookie": "<redacted>",
                        "fixtureClassification": "synthetic",
                    }
                ),
                encoding="utf-8",
            )
            result = gate.scan_before_seal(root)
        self.assertEqual(result["codes"], [])
        self.assertTrue(result["sealAllowed"])

    def test_23_manifest_generation_is_sorted_complete_and_sha256_exact(self) -> None:
        gate = load_subject(self, "NYAY14-MANIFEST-GENERATION")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "b.txt").write_text("b\n", encoding="utf-8")
            (root / "a.txt").write_text("a\n", encoding="utf-8")
            result = gate.generate_manifest(root)
            lines = (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(result["codes"], [])
        self.assertEqual([line.split("  ", 1)[1] for line in lines], ["a.txt", "b.txt"])
        self.assertTrue(all(len(line.split("  ", 1)[0]) == 64 for line in lines))

    def test_24_manifest_rejects_missing_extra_tampered_and_unsafe_nodes(self) -> None:
        gate = load_subject(self, "NYAY14-MANIFEST-FAIL-CLOSED")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "payload.txt").write_text("sealed\n", encoding="utf-8")
            self.assertEqual(gate.generate_manifest(root)["codes"], [])
            (root / "payload.txt").write_text("mutated\n", encoding="utf-8")
            (root / "extra.txt").write_text("extra\n", encoding="utf-8")
            (root / "zero.txt").write_bytes(b"")
            (root / ".hidden").write_text("hidden\n", encoding="utf-8")
            (root / "linked.txt").symlink_to(root / "payload.txt")
            codes = finding_codes(gate.verify_manifest(root))
        for expected in (
            "CHECKSUM_MISMATCH",
            "INVENTORY_MISMATCH",
            "ZERO_BYTE_ARTIFACT",
            "HIDDEN_ARTIFACT",
            "UNSAFE_ARTIFACT_NODE",
        ):
            self.assertIn(expected, codes)

    def test_25_clean_archive_reopens_to_the_exact_manifest_inventory(self) -> None:
        gate = load_subject(self, "NYAY14-CLEAN-ARCHIVE")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"
            root.mkdir()
            (root / "payload.txt").write_text("sealed\n", encoding="utf-8")
            self.assertEqual(gate.generate_manifest(root)["codes"], [])
            archive = Path(directory) / "evidence.tar.gz"
            self.assertEqual(gate.build_clean_archive(root, archive)["codes"], [])
            verified = gate.verify_clean_archive(archive)
        self.assertEqual(verified["codes"], [])
        self.assertEqual(set(verified["members"]), {"payload.txt", "SHA256SUMS.txt"})

    def test_26_archive_rejects_nested_hidden_unsafe_and_unsupported_members(self) -> None:
        gate = load_subject(self, "NYAY14-ARCHIVE-FAIL-CLOSED")
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "mutant.tar.gz"
            source = Path(directory) / "source"
            source.mkdir()
            (source / "nested.zip").write_bytes(b"PK\x03\x04mutant")
            (source / ".hidden").write_text("hidden\n", encoding="utf-8")
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(source / "nested.zip", arcname="nested.zip")
                bundle.add(source / ".hidden", arcname=".hidden")
                info = tarfile.TarInfo("../escape.txt")
                payload = b"escape\n"
                info.size = len(payload)
                import io

                bundle.addfile(info, io.BytesIO(payload))
                link = tarfile.TarInfo("linked.txt")
                link.type = tarfile.SYMTYPE
                link.linkname = "nested.zip"
                bundle.addfile(link)
            codes = finding_codes(gate.verify_clean_archive(archive))
        for expected in (
            "NESTED_ARCHIVE",
            "HIDDEN_ARCHIVE_MEMBER",
            "UNSAFE_ARCHIVE_PATH",
            "UNSUPPORTED_ARCHIVE_NODE",
        ):
            self.assertIn(expected, codes)

    def test_27_pr_comment_requires_head_digests_limitations_and_verdict(self) -> None:
        gate = load_subject(self, "NYAY14-PR-COMMENT")
        with tempfile.TemporaryDirectory() as directory:
            package = canonical_package(Path(directory))
        result = {
            "verdict": "PASS",
            "archiveLocation": "jira://NYAY-14/attachment/1",
            "archiveSha256": "a" * 64,
            "manifestSha256": "b" * 64,
        }
        comment = gate.render_pr_comment(package, result)
        for expected in (
            HEAD_SHA,
            result["archiveLocation"],
            result["archiveSha256"],
            result["manifestSha256"],
            "Limitations",
            "PASS",
        ):
            self.assertIn(expected, comment)
        result.pop("manifestSha256")
        self.assertIn(
            "PR_COMMENT_INVALID",
            finding_codes(gate.validate_pr_comment(package, result, comment)),
        )

    def test_28_guarded_merge_commands_pin_repo_pr_mode_and_exact_head(self) -> None:
        gate = load_subject(self, "NYAY14-GUARDED-MERGE")
        commands = gate.render_guarded_merge_commands(REPOSITORY, 14, HEAD_SHA)
        self.assertIn(f"gh pr view 14 --repo {REPOSITORY}", commands)
        self.assertIn(f"gh pr merge 14 --repo {REPOSITORY}", commands)
        for required_review_guard in (
            "--json reviewRequests",
            "--json reviews",
            "CHANGES_REQUESTED",
            "reviewThreads(first:100)",
            "pageInfo{hasNextPage}",
            "hasNextPage",
            "isResolved",
        ):
            self.assertIn(required_review_guard, commands)
            self.assertLess(
                commands.index(required_review_guard),
                commands.index(f"gh pr merge 14 --repo {REPOSITORY}"),
            )
        self.assertIn("--merge", commands)
        self.assertIn(f"--match-head-commit {HEAD_SHA}", commands)
        for forbidden in ("--squash", "--rebase", "--admin", "--auto", "--force"):
            self.assertNotIn(forbidden, commands)

    def test_29_post_merge_validation_reads_exact_commit_and_both_ancestries(self) -> None:
        gate = load_subject(self, "NYAY14-POST-MERGE-READBACK")
        commands = gate.render_post_merge_validation(REPOSITORY, 14, HEAD_SHA)
        self.assertIn("--json mergeCommit", commands)
        self.assertIn("git fetch origin main", commands)
        self.assertGreaterEqual(commands.count("git merge-base --is-ancestor"), 2)
        self.assertIn(HEAD_SHA, commands)
        self.assertIn("NYAY14_MERGE_SHA", commands)

    def test_30_process_never_modifies_the_protected_desktop_checkout(self) -> None:
        gate = load_subject(self, "NYAY14-PROTECTED-CHECKOUT")
        before = {
            "head": BASE_SHA,
            "entries": 299,
            "statusSha256": "2bddf5cb49dd5c49919226c21be65fa32df2b1d7328f7e3d105a0dac42080a27",
            "nulStatusSha256": "fe9eb22421cfbb0087501431255a790a6d36e97c7165b0e05a985f66dcc638c0",
        }
        self.assertEqual(
            gate.validate_protected_checkout(
                before=before,
                after=before.copy(),
                execution_root=Path("/private/tmp/nyay14-run"),
                protected_root=Path("/Users/reviewer/Desktop/Codes/NyayOne"),
                operations=("git status --porcelain=v1 -z",),
            ),
            [],
        )
        changed = {**before, "entries": 300}
        codes = finding_codes(
            gate.validate_protected_checkout(
                before=before,
                after=changed,
                execution_root=Path("/Users/reviewer/Desktop/Codes/NyayOne/subdir"),
                protected_root=Path("/Users/reviewer/Desktop/Codes/NyayOne"),
                operations=("git reset --hard",),
            )
        )
        self.assertIn("PROTECTED_CHECKOUT_CHANGED", codes)
        self.assertIn("UNSAFE_EXECUTION_ROOT", codes)
        self.assertIn("PROTECTED_CHECKOUT_MUTATION", codes)

    def test_31_seeded_false_pass_example_fails_closed_without_outputs(self) -> None:
        gate = load_subject(self, "NYAY14-SEEDED-FALSE-PASS")
        self.assertTrue(FIXTURE.is_file(), "seeded zero-assertion fixture is missing")
        package = json.loads(FIXTURE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "report.json"
            archive = root / "evidence.tar.gz"
            manifest = root / "SHA256SUMS.txt"
            result = gate.validate_package(
                package,
                evidence_root=root,
                authoritative_remote_head=HEAD_SHA,
                authoritative_evidence_schema_version=SCHEMA_VERSION,
                report_path=report,
                archive_path=archive,
            )
            codes = finding_codes(result)
            self.assertEqual(result["verdict"], "FAIL")
            self.assertFalse(result["mergeAuthorized"])
            self.assertIn("MISSING_RAW_LOG", codes)
            self.assertIn("ZERO_EXECUTED", codes)
            self.assertFalse(manifest.exists())
            self.assertFalse(archive.exists())


if __name__ == "__main__":
    unittest.main()
