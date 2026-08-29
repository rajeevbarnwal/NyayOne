#!/usr/bin/env python3
"""NYAY-27 RED contracts for forward-only combined contact-sheet enforcement.

The NYAY-14 v1 evidence gate remains the immutable verifier for already sealed
historical packages.  Every package produced under v2 must carry a manifest-
bound combined contact sheet and a privacy-clean rendered-text sidecar (or an
equivalent pixel-content scan record).  These tests intentionally precede the
GREEN implementation in ``nyay14_evidence_gate.py``.

The source archive digest is supplied independently.  A sheet inside an
archive cannot embed the digest of that same final archive without creating a
self-reference, so the contact sheet binds to the sealed *source* archive and
the final evidence envelope binds the source archive, sheet, and sidecar.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Callable


HERE = Path(__file__).resolve().parent
SUBJECT = HERE / "nyay14_evidence_gate.py"
CONTRACT_PATH = HERE / "nyay27_contact_sheet_contract.json"

LEGACY_SCHEMA = "nyay14-evidence/v1"
FUTURE_SCHEMA = "nyay14-evidence/v2"
POLICY_SCHEMA = "nyay27-contact-sheet-contract/v1"
HEAD_SHA = "1" * 40
OTHER_HEAD_SHA = "2" * 40
SOURCE_ARCHIVE_SHA = "a" * 64
OTHER_ARCHIVE_SHA = "b" * 64
GENERATED_AT = "2026-08-29T15:00:00Z"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_contract() -> dict[str, object]:
    value = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError("NYAY-27 contract must be a JSON object")
    return value


def _load_subject(test_case: unittest.TestCase) -> ModuleType:
    spec = importlib.util.spec_from_file_location("nyay14_evidence_gate_nyay27_red", SUBJECT)
    test_case.assertIsNotNone(spec, "NYAY27-SUBJECT: import spec is unavailable")
    test_case.assertIsNotNone(spec.loader, "NYAY27-SUBJECT: loader is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _finding_codes(value: object) -> set[str]:
    if isinstance(value, dict):
        rows = value.get("codes", [])
    else:
        rows = value
    if not isinstance(rows, list):
        return set()
    return {
        row if isinstance(row, str) else row.get("code")
        for row in rows
        if isinstance(row, (str, dict))
    }


def _write_artifacts(root: Path, *, ticket_type: str) -> dict[str, object]:
    visual = root / "visual"
    visual.mkdir(parents=True)
    sheet = visual / "NYAY_COMBINED_CONTACT_SHEET.png"
    # A deterministic, non-empty PNG-like test payload. Pixel rendering is not
    # under test here; binding and scan-record enforcement are.
    sheet.write_bytes(b"\x89PNG\r\n\x1a\nNYAY-27 synthetic contact sheet\n")
    sidecar = visual / "NYAY_COMBINED_CONTACT_SHEET.txt"
    sidecar.write_text(
        "ticket=NYAY-27\nreviewedHead=" + HEAD_SHA + "\nprivacy=clean\n",
        encoding="utf-8",
    )

    if ticket_type == "ui":
        sheet_format = "ui-design-parity"
        panels = [
            {
                "id": "approved",
                "role": "approved-baseline",
                "position": "left",
                "artifactId": "approved-baseline-artifact",
            },
            {
                "id": "live",
                "role": "live-implementation",
                "position": "right",
                "artifactId": "live-implementation-artifact",
            },
        ]
    else:
        sheet_format = "rendered-evidence"
        panels = [
            {
                "id": "matrix",
                "role": "classification-matrix",
                "artifactId": "classification-matrix-artifact",
            },
            {
                "id": "merge",
                "role": "guarded-merge-checklist",
                "artifactId": "guarded-merge-artifact",
            },
            {
                "id": "comment",
                "role": "pr-comment-template",
                "artifactId": "pr-comment-artifact",
            },
        ]

    sheet_path = sheet.relative_to(root).as_posix()
    sidecar_path = sidecar.relative_to(root).as_posix()
    sheet_sha = _digest(sheet)
    sidecar_sha = _digest(sidecar)
    return {
        "schemaVersion": FUTURE_SCHEMA,
        "publisher": "codex",
        "ticket": {"key": "NYAY-27", "type": ticket_type},
        "provenance": {"reviewedHead": HEAD_SHA, "capturedAt": GENERATED_AT},
        "evidenceArtifacts": [
            {
                "id": "combined-contact-sheet",
                "path": sheet_path,
                "sha256": sheet_sha,
                "bytes": sheet.stat().st_size,
            },
            {
                "id": "combined-contact-sheet-sidecar",
                "path": sidecar_path,
                "sha256": sidecar_sha,
                "bytes": sidecar.stat().st_size,
            },
        ],
        "combinedContactSheet": {
            "artifactId": "combined-contact-sheet",
            "format": sheet_format,
            "path": sheet_path,
            "sha256": sheet_sha,
            "panelCount": len(panels),
            "panels": panels,
            "provenance": {
                "sheetSha256": sheet_sha,
                "sourceArchiveSha256": SOURCE_ARCHIVE_SHA,
                "generatedAt": GENERATED_AT,
                "reviewedHead": HEAD_SHA,
            },
            "renderedTextSidecar": {
                "artifactId": "combined-contact-sheet-sidecar",
                "path": sidecar_path,
                "sha256": sidecar_sha,
                "privacyScan": {
                    "scanner": "scripts/ci/scan_evidence.py",
                    "executed": 1,
                    "findings": 0,
                    "passed": True,
                },
            },
        },
    }


def _validator(
    test_case: unittest.TestCase,
    gate: ModuleType,
) -> Callable[..., list[str]]:
    validator = getattr(gate, "validate_combined_contact_sheet", None)
    test_case.assertTrue(
        callable(validator),
        "NYAY27-CONTACT-SHEET-VALIDATOR: RED — validate_combined_contact_sheet is absent",
    )
    return validator


def _validate(
    test_case: unittest.TestCase,
    gate: ModuleType,
    package: dict[str, object],
    root: Path,
    *,
    ticket_type: str,
    panel_roles: tuple[str, ...],
    source_archive_sha: str = SOURCE_ARCHIVE_SHA,
) -> set[str]:
    validator = _validator(test_case, gate)
    result = validator(
        package,
        root,
        authoritative_reviewed_head=HEAD_SHA,
        authoritative_source_archive_sha256=source_archive_sha,
        authoritative_ticket_type=ticket_type,
        authoritative_panel_roles=panel_roles,
        contract=_load_contract(),
    )
    return _finding_codes(result)


class Nyay27CombinedContactSheetRedTests(unittest.TestCase):
    maxDiff = None

    def test_01_legacy_policy_is_forward_only_and_exact_seal_scoped(self) -> None:
        """Existing named records stay v1; a timestamp cannot forge exemption."""
        contract = _load_contract()
        self.assertEqual(contract["schemaVersion"], POLICY_SCHEMA)
        self.assertEqual(contract["legacyEvidenceSchemaVersion"], LEGACY_SCHEMA)
        self.assertEqual(contract["futureEvidenceSchemaVersion"], FUTURE_SCHEMA)
        self.assertEqual(
            contract["historicalPolicy"],
            {
                "mode": "exact-seal-only",
                "immutableTicketKeys": [
                    "NYAY-7",
                    "NYAY-9",
                    "NYAY-14",
                    "NYAY-21",
                    "NYAY-28",
                    "NYAY-29",
                ],
                "selfDeclaredTimestampIsAuthority": False,
            },
        )
        # The already merged NYAY-14 verifier remains byte-compatible at v1;
        # GREEN must add v2 rather than rewriting historical v1 records.
        gate = _load_subject(self)
        self.assertEqual(gate.SCHEMA_VERSION, LEGACY_SCHEMA)

    def test_02_future_gate_is_integrated_and_cannot_be_downgraded_to_v1(self) -> None:
        gate = _load_subject(self)
        self.assertEqual(
            getattr(gate, "CONTACT_SHEET_POLICY_VERSION", None),
            POLICY_SCHEMA,
            "NYAY27-POLICY-VERSION: RED — the future contact-sheet policy is absent",
        )
        self.assertTrue(callable(getattr(gate, "validate_combined_contact_sheet", None)))
        source_names = set(gate.validate_package.__code__.co_names)
        self.assertIn(
            "validate_combined_contact_sheet",
            source_names,
            "NYAY27-INTEGRATION: validate_package must enforce the future policy",
        )
        self.assertIn("codex", _load_contract()["publishers"])
        self.assertIn("claude-code", _load_contract()["publishers"])
        # A package created after enforcement cannot self-select v1 or forge an
        # old capturedAt timestamp to suppress the authoritative requirement.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            downgraded = _write_artifacts(root, ticket_type="ui")
            downgraded["schemaVersion"] = LEGACY_SCHEMA
            downgraded["provenance"]["capturedAt"] = "2020-01-01T00:00:00Z"
            downgraded.pop("combinedContactSheet")
            codes = _validate(
                self,
                gate,
                downgraded,
                root,
                ticket_type="ui",
                panel_roles=("approved-baseline", "live-implementation"),
            )
        self.assertTrue(
            {"CONTACT_SHEET_MISSING", "HISTORICAL_SEAL_MISMATCH"}.intersection(codes),
            "NYAY27-DOWNGRADE: a package-controlled schema/timestamp must not bypass v2",
        )

    def test_03_missing_empty_unmanifested_or_hash_mismatched_sheet_fails_closed(self) -> None:
        gate = _load_subject(self)
        expected = {
            "missing": "CONTACT_SHEET_MISSING",
            "empty": "CONTACT_SHEET_EMPTY",
            "unmanifested": "CONTACT_SHEET_UNMANIFESTED",
            "hash-mismatch": "CONTACT_SHEET_HASH_MISMATCH",
        }
        for mutation, code in expected.items():
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                package = _write_artifacts(root, ticket_type="ui")
                sheet = root / str(package["combinedContactSheet"]["path"])
                if mutation == "missing":
                    package.pop("combinedContactSheet")
                elif mutation == "empty":
                    sheet.write_bytes(b"")
                elif mutation == "unmanifested":
                    package["evidenceArtifacts"] = package["evidenceArtifacts"][1:]
                else:
                    package["combinedContactSheet"]["sha256"] = "f" * 64
                codes = _validate(
                    self,
                    gate,
                    package,
                    root,
                    ticket_type="ui",
                    panel_roles=("approved-baseline", "live-implementation"),
                )
                self.assertIn(code, codes)
                self.assertNotEqual(gate.classify({"failed": bool(codes)}), "PASS")

    def test_04_sheet_provenance_is_bound_to_file_archive_timestamp_and_head(self) -> None:
        gate = _load_subject(self)
        mutations = {
            "sheet-sha": lambda value: value.__setitem__("sheetSha256", "f" * 64),
            "archive-sha": lambda value: value.__setitem__("sourceArchiveSha256", OTHER_ARCHIVE_SHA),
            "timestamp": lambda value: value.__setitem__("generatedAt", "not-rfc3339"),
            "reviewed-head": lambda value: value.__setitem__("reviewedHead", OTHER_HEAD_SHA),
        }
        for mutation, mutate in mutations.items():
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                package = _write_artifacts(root, ticket_type="non-ui")
                mutate(package["combinedContactSheet"]["provenance"])
                codes = _validate(
                    self,
                    gate,
                    package,
                    root,
                    ticket_type="non-ui",
                    panel_roles=(
                        "classification-matrix",
                        "guarded-merge-checklist",
                        "pr-comment-template",
                    ),
                )
                self.assertIn("CONTACT_SHEET_PROVENANCE_MISMATCH", codes)

    def test_05_ui_and_non_ui_formats_require_authoritative_exact_panel_sets(self) -> None:
        gate = _load_subject(self)
        cases = (
            (
                "ui",
                "rendered-evidence",
                ("approved-baseline", "live-implementation"),
            ),
            (
                "non-ui",
                "ui-design-parity",
                (
                    "classification-matrix",
                    "guarded-merge-checklist",
                    "pr-comment-template",
                ),
            ),
        )
        for ticket_type, wrong_format, roles in cases:
            with self.subTest(ticket_type=ticket_type), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                package = _write_artifacts(root, ticket_type=ticket_type)
                package["combinedContactSheet"]["format"] = wrong_format
                package["combinedContactSheet"]["panels"] = []
                package["combinedContactSheet"]["panelCount"] = 0
                codes = _validate(
                    self,
                    gate,
                    package,
                    root,
                    ticket_type=ticket_type,
                    panel_roles=roles,
                )
                self.assertIn("CONTACT_SHEET_FORMAT_MISMATCH", codes)
                self.assertIn("CONTACT_SHEET_ZERO_PANELS", codes)
                self.assertIn("CONTACT_SHEET_PANEL_SET_INVALID", codes)

    def test_06_ui_left_right_pair_and_non_ui_external_inventory_are_not_package_chosen(self) -> None:
        gate = _load_subject(self)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ui = _write_artifacts(root, ticket_type="ui")
            ui["combinedContactSheet"]["panels"].reverse()
            codes = _validate(
                self,
                gate,
                ui,
                root,
                ticket_type="ui",
                panel_roles=("approved-baseline", "live-implementation"),
            )
            self.assertIn("CONTACT_SHEET_PANEL_SET_INVALID", codes)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            non_ui = _write_artifacts(root, ticket_type="non-ui")
            non_ui["combinedContactSheet"]["panels"] = [
                {"id": "self-selected", "role": "package-selected", "artifactId": "x"}
            ]
            non_ui["combinedContactSheet"]["panelCount"] = 1
            codes = _validate(
                self,
                gate,
                non_ui,
                root,
                ticket_type="non-ui",
                panel_roles=(
                    "classification-matrix",
                    "guarded-merge-checklist",
                    "pr-comment-template",
                ),
            )
            self.assertIn("CONTACT_SHEET_PANEL_SET_INVALID", codes)

    def test_07_sidecar_is_required_manifest_bound_and_hash_exact(self) -> None:
        gate = _load_subject(self)
        mutations = {
            "missing": "CONTACT_SHEET_SIDECAR_MISSING",
            "unmanifested": "CONTACT_SHEET_SIDECAR_MISSING",
            "hash-mismatch": "CONTACT_SHEET_SIDECAR_HASH_MISMATCH",
        }
        for mutation, expected in mutations.items():
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                package = _write_artifacts(root, ticket_type="non-ui")
                sidecar = package["combinedContactSheet"]["renderedTextSidecar"]
                if mutation == "missing":
                    package["combinedContactSheet"].pop("renderedTextSidecar")
                elif mutation == "unmanifested":
                    package["evidenceArtifacts"] = package["evidenceArtifacts"][:1]
                else:
                    sidecar["sha256"] = "f" * 64
                codes = _validate(
                    self,
                    gate,
                    package,
                    root,
                    ticket_type="non-ui",
                    panel_roles=(
                        "classification-matrix",
                        "guarded-merge-checklist",
                        "pr-comment-template",
                    ),
                )
                self.assertIn(expected, codes)

    def test_08_sidecar_privacy_scan_must_execute_cleanly_and_diagnostics_are_redacted(self) -> None:
        gate = _load_subject(self)
        canary = "9876543210"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = _write_artifacts(root, ticket_type="ui")
            sidecar = package["combinedContactSheet"]["renderedTextSidecar"]
            target = root / str(sidecar["path"])
            target.write_text("mobile=" + canary + "\n", encoding="utf-8")
            new_sha = _digest(target)
            sidecar["sha256"] = new_sha
            package["evidenceArtifacts"][1]["sha256"] = new_sha
            package["evidenceArtifacts"][1]["bytes"] = target.stat().st_size
            # A package-authored PASS marker is never authoritative; the gate
            # must execute the repository scanner over the bound sidecar.
            codes = _validate(
                self,
                gate,
                package,
                root,
                ticket_type="ui",
                panel_roles=("approved-baseline", "live-implementation"),
            )
            self.assertIn("CONTACT_SHEET_PRIVACY_SCAN_FAILED", codes)
            self.assertNotIn(canary, json.dumps(sorted(codes)))


if __name__ == "__main__":
    unittest.main()
