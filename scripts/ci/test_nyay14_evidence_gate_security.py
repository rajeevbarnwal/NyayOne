#!/usr/bin/env python3
"""Adversarial regressions for the NYAY-14 evidence gate."""

from __future__ import annotations

import hashlib
import gzip
import io
import importlib.util
import json
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from types import ModuleType
from unittest import mock


HERE = Path(__file__).resolve().parent
SUBJECT = HERE / "nyay14_evidence_gate.py"
CONTRACT_TEST = HERE / "test_nyay14_evidence_gate.py"


def load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


class Nyay14EvidenceGateSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = load(SUBJECT, "nyay14_evidence_gate_security_subject")
        cls.fixtures = load(CONTRACT_TEST, "nyay14_evidence_gate_security_fixtures")

    def package(self, root: Path, *, future_contact_sheet: bool = False) -> dict[str, object]:
        package = self.fixtures.canonical_package(root)
        package["approvedVisualComparisons"] = json.loads(
            json.dumps(package["visualComparisons"])
        )
        artifacts: list[dict[str, str]] = []
        for artifact_id in ("visual-baseline", "visual-live", "visual-comparison"):
            path = root / "visual" / f"{artifact_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"artifact": artifact_id, "classification": "synthetic"})
                + "\n",
                encoding="utf-8",
            )
            artifacts.append(
                {
                    "id": artifact_id,
                    "path": path.relative_to(root).as_posix(),
                    "sha256": sha256(path),
                }
            )
        package["evidenceArtifacts"] = artifacts
        approved_payload = (
            json.dumps(
                package["approvedVisualComparisons"],
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        package["approvedVisualMatrixSha256"] = hashlib.sha256(
            approved_payload
        ).hexdigest()
        protected_seal = {
            "head": self.fixtures.BASE_SHA,
            "entries": 299,
            "statusSha256": "a" * 64,
            "nulStatusSha256": "b" * 64,
        }
        package["protectedCheckout"] = {
            "before": protected_seal,
            "after": dict(protected_seal),
            "operations": ["git status --porcelain=v1 -z"],
        }
        if future_contact_sheet:
            panel_roles = (
                "classification-matrix",
                "guarded-merge-checklist",
                "pr-comment-template",
            )
            panel_ids = ("matrix", "merge", "comment")
            panel_artifact_ids: list[str] = []
            for panel_id, role in zip(panel_ids, panel_roles, strict=True):
                artifact_id = f"contact-panel-{panel_id}"
                path = root / "visual" / f"{artifact_id}.json"
                path.write_text(
                    json.dumps({"panel": panel_id, "role": role}, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                )
                artifacts.append(
                    {
                        "id": artifact_id,
                        "path": path.relative_to(root).as_posix(),
                        "sha256": sha256(path),
                    }
                )
                panel_artifact_ids.append(artifact_id)

            sheet = root / "visual" / "NYAY27_COMBINED_CONTACT_SHEET.png"
            sheet.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                + png_chunk(
                    b"IHDR",
                    struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0),
                )
                + png_chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
                + png_chunk(b"IEND", b"")
            )
            source_archive_sha = "a" * 64
            sidecar = (
                root / "visual" / "NYAY27_COMBINED_CONTACT_SHEET.rendered-text.txt"
            )
            sidecar.write_text(
                "classification matrix\n"
                "guarded merge checklist\n"
                "PR comment template\n"
                f"sheetSha256={sha256(sheet)}\n"
                f"sourceArchiveSha256={source_archive_sha}\n"
                f"reviewedHead={self.fixtures.HEAD_SHA}\n"
                f"panelCount={len(panel_roles)}\n"
                f"panelRoles={','.join(panel_roles)}\n",
                encoding="utf-8",
            )
            for artifact_id, path in (
                ("combined-contact-sheet", sheet),
                ("combined-contact-sheet-sidecar", sidecar),
            ):
                artifacts.append(
                    {
                        "id": artifact_id,
                        "path": path.relative_to(root).as_posix(),
                        "sha256": sha256(path),
                        "bytes": path.stat().st_size,
                    }
                )
            package["schemaVersion"] = self.gate.FUTURE_SCHEMA_VERSION
            package["publisher"] = "codex"
            package["ticket"] = {"key": "NYAY-27", "type": "non-ui"}
            package["combinedContactSheet"] = {
                "artifactId": "combined-contact-sheet",
                "format": "rendered-evidence",
                "path": sheet.relative_to(root).as_posix(),
                "sha256": sha256(sheet),
                "panelCount": len(panel_roles),
                "panels": [
                    {
                        "id": panel_id,
                        "role": role,
                        "artifactId": artifact_id,
                    }
                    for panel_id, role, artifact_id in zip(
                        panel_ids, panel_roles, panel_artifact_ids, strict=True
                    )
                ],
                "provenance": {
                    "sheetSha256": sha256(sheet),
                    "sourceArchiveSha256": source_archive_sha,
                    "generatedAt": "2026-08-29T15:00:00Z",
                    "reviewedHead": self.fixtures.HEAD_SHA,
                },
                "renderedTextSidecar": {
                    "artifactId": "combined-contact-sheet-sidecar",
                    "path": sidecar.relative_to(root).as_posix(),
                    "sha256": sha256(sidecar),
                    "contentBindings": {
                        "sheetSha256": sha256(sheet),
                        "sourceArchiveSha256": source_archive_sha,
                        "reviewedHead": self.fixtures.HEAD_SHA,
                        "panelCount": len(panel_roles),
                        "panelRoles": list(panel_roles),
                    },
                    "privacyScan": {
                        "scanner": "scripts/ci/scan_evidence.py",
                        "scannerVersion": f"sha256:{sha256(HERE / 'scan_evidence.py')}",
                        "executed": 1,
                        "findings": 0,
                        "passed": True,
                    },
                },
            }
        return package

    def validate(
        self,
        package: dict[str, object],
        root: Path,
        report: Path,
        archive: Path,
        **overrides: str,
    ) -> dict[str, object]:
        authority = {
            "authoritative_remote_head": self.fixtures.HEAD_SHA,
            "authoritative_repository": self.fixtures.REPOSITORY,
            "authoritative_base": self.fixtures.BASE_SHA,
            "authoritative_prospective_merge": self.fixtures.MERGE_SHA,
            "authoritative_visual_matrix": package.get(
                "approvedVisualComparisons"
            ),
            "authoritative_evidence_schema_version": package.get("schemaVersion"),
            "execution_root": root.parent / "execution",
            "protected_root": root.parent / "protected",
        }
        if package.get("schemaVersion") == self.gate.FUTURE_SCHEMA_VERSION:
            authority.update(
                {
                    "authoritative_source_archive_sha256": "a" * 64,
                    "authoritative_ticket_type": "non-ui",
                    "authoritative_contact_sheet_panel_roles": (
                        "classification-matrix",
                        "guarded-merge-checklist",
                        "pr-comment-template",
                    ),
                }
            )
        authority.update(overrides)
        return self.gate.validate_package(
            package,
            evidence_root=root,
            report_path=report,
            archive_path=archive,
            **authority,
        )

    def test_pass_archive_binds_the_exact_validated_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root, future_contact_sheet=True)
            sheet = root / str(package["combinedContactSheet"]["path"])
            self.assertTrue(self.gate._valid_contact_sheet_png(sheet))
            ancillary = run / "contact-sheet-with-unscanned-metadata.png"
            png_payload = sheet.read_bytes()
            ancillary.write_bytes(
                png_payload[:-12]
                + png_chunk(b"tEXt", b"unscanned-channel")
                + png_payload[-12:]
            )
            self.assertFalse(self.gate._valid_contact_sheet_png(ancillary))
            result = self.validate(package, root, run / "report.json", run / "evidence.tar.gz")
            archive_result = self.gate.verify_clean_archive(run / "evidence.tar.gz")
            package_record = root / self.gate.PACKAGE_RECORD_NAME
            recorded = json.loads(package_record.read_text(encoding="utf-8"))
            report = json.loads((run / "report.json").read_text(encoding="utf-8"))
            recorded_digest = sha256(package_record)
        self.assertEqual(result["verdict"], "PASS")
        self.assertTrue(result["mergeAuthorized"])
        self.assertEqual(recorded, package)
        self.assertIn(self.gate.PACKAGE_RECORD_NAME, archive_result["members"])
        self.assertEqual(result["packageSha256"], recorded_digest)
        self.assertEqual(
            archive_result["memberSha256"][self.gate.PACKAGE_RECORD_NAME],
            result["packageSha256"],
        )
        self.assertEqual(
            archive_result["manifestSha256"], result["manifestSha256"]
        )
        self.assertEqual(report["packageSha256"], result["packageSha256"])

        # The package-authored scanner version is sealed provenance, not a
        # free-form display claim.  A forged digest must fail even though the
        # gate also executes the repository scanner independently.
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root, future_contact_sheet=True)
            package["combinedContactSheet"]["renderedTextSidecar"][
                "privacyScan"
            ]["scannerVersion"] = "sha256:" + "f" * 64
            result = self.validate(
                package,
                root,
                run / "report.json",
                run / "evidence.tar.gz",
            )
            self.assertEqual(result["verdict"], "FAIL", result)
            self.assertFalse(result["mergeAuthorized"])
            self.assertIn("CONTACT_SHEET_PRIVACY_SCAN_FAILED", result["codes"])
            self.assertFalse((run / "report.json").exists())
            self.assertFalse((run / "evidence.tar.gz").exists())
            self.assertFalse((root / self.gate.MANIFEST_NAME).exists())
            self.assertFalse((root / self.gate.PACKAGE_RECORD_NAME).exists())

    def test_false_claimed_head_changed_is_a_failure_not_exit_zero_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            package["claimedVerdict"] = "HEAD_CHANGED"
            result = self.validate(package, root, run / "report.json", run / "evidence.tar.gz")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("CLAIMED_VERDICT_MISMATCH", result["codes"])
        self.assertFalse(result["mergeAuthorized"])

    def test_output_preflight_and_aliases_fail_before_any_seal_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            report = run / "report.json"
            report.mkdir()
            archive = run / "evidence.tar.gz"
            result = self.validate(package, root, report, archive)
            self.assertEqual(result["verdict"], "FAIL")
            self.assertIn("OUTPUT_ALREADY_EXISTS", result["codes"])
            self.assertFalse((root / self.gate.MANIFEST_NAME).exists())
            self.assertFalse((root / self.gate.PACKAGE_RECORD_NAME).exists())
            self.assertFalse(archive.exists())

        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            same = run / "same-output"
            result = self.validate(package, root, same, same)
            self.assertEqual(result["verdict"], "FAIL")
            self.assertIn("OUTPUT_PATH_ALIAS", result["codes"])
            self.assertFalse(same.exists())
            self.assertFalse((root / self.gate.MANIFEST_NAME).exists())

    def test_manifest_symlink_is_rejected_without_touching_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            (root / "payload.txt").write_text("safe\n", encoding="utf-8")
            outside = run / "outside.txt"
            outside.write_text("must remain unchanged\n", encoding="utf-8")
            (root / self.gate.MANIFEST_NAME).symlink_to(outside)
            result = self.gate.generate_manifest(root)
            self.assertIn("UNSAFE_MANIFEST_NODE", result["codes"])
            self.assertEqual(outside.read_text(encoding="utf-8"), "must remain unchanged\n")

    def test_json_shaped_secrets_and_package_metadata_are_scanned(self) -> None:
        planted = {
            "password": "unsafe-secret-value",
            "otp": 429016,
            "nyayone_session": "opaque-cookie-value",
            "Authorization": "Bearer opaque-token-value",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "planted.json").write_text(json.dumps(planted), encoding="utf-8")
            scan = self.gate.scan_before_seal(root)
        self.assertFalse(scan["sealAllowed"])
        self.assertIn("PII_OR_SECRET_DETECTED", scan["codes"])
        self.assertNotIn("unsafe-secret-value", json.dumps(scan))

        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            package["limitations"] = ["password=unsafe-secret-value"]
            result = self.validate(package, root, run / "report.json", run / "archive.tar.gz")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("PII_OR_SECRET_DETECTED", result["codes"])

    def test_raw_logs_must_be_executed_machine_readable_assertion_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = []
            for index, category in enumerate(self.gate.RAW_CATEGORIES):
                path = root / f"{category}.txt"
                path.write_text("no assertions were executed\n", encoding="utf-8")
                inventory.append(
                    {
                        "id": f"raw-{index}",
                        "category": category,
                        "path": path.name,
                        "sha256": sha256(path),
                    }
                )
            codes = self.gate.validate_raw_logs(inventory, root)
        self.assertIn("RAW_LOG_FORMAT_INVALID", codes)

    def test_visual_matrix_and_evidence_references_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            package.pop("approvedVisualComparisons")
            package["visualComparisons"][0]["metric"] = {
                "value": 2.0,
                "threshold": 1.0,
                "unit": "percent",
            }
            package["evidenceArtifacts"] = []
            result = self.validate(package, root, run / "report.json", run / "archive.tar.gz")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("APPROVED_VISUAL_MATRIX_MISSING", result["codes"])
        self.assertIn("VISUAL_THRESHOLD_EXCEEDED", result["codes"])
        self.assertIn("UNTRACEABLE_EVIDENCE_ARTIFACT", result["codes"])

    def test_authoritative_repository_base_and_merge_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            result = self.validate(
                package,
                root,
                run / "report.json",
                run / "archive.tar.gz",
                authoritative_repository="different/private-repository",
            )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("PROVENANCE_MISMATCH", result["codes"])

    def test_malformed_visual_types_return_findings_instead_of_throwing(self) -> None:
        malformed = {
            "screen": [],
            "state": "initial",
            "viewport": {"width": 390, "height": 844},
            "approvedReference": "design://approved/reference",
            "testedHead": self.fixtures.HEAD_SHA,
            "baselineArtifactId": "visual-baseline",
            "liveArtifactId": "visual-live",
            "comparisonArtifactId": "visual-comparison",
            "executed": 1,
            "metric": {"value": 0.0, "threshold": 1.0, "unit": "percent"},
        }
        codes = self.gate.validate_visual_matrix([malformed], [malformed], Path("."))
        self.assertIn("VISUAL_ROW_INVALID", codes)

    def test_post_merge_commands_bind_reviewed_head_to_the_merge_commit(self) -> None:
        commands = self.gate.render_post_merge_validation(
            self.fixtures.REPOSITORY,
            14,
            self.fixtures.HEAD_SHA,
        )
        self.assertIn(
            f'git merge-base --is-ancestor {self.fixtures.HEAD_SHA} "$NYAY14_MERGE_SHA"',
            commands,
        )

    def test_protected_checkout_detects_git_global_option_mutations(self) -> None:
        seal = {"head": self.fixtures.BASE_SHA, "entries": 299}
        codes = self.gate.validate_protected_checkout(
            before=seal,
            after=dict(seal),
            execution_root=Path("/private/tmp/nyay14-run"),
            protected_root=Path("/protected/NyayOne"),
            operations=("git -C /protected/NyayOne reset --hard",),
        )
        self.assertIn("PROTECTED_CHECKOUT_MUTATION", codes)

    def test_plain_tar_is_not_accepted_as_the_required_gzip_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            (root / "payload.txt").write_text("safe\n", encoding="utf-8")
            self.assertEqual(self.gate.generate_manifest(root)["codes"], [])
            archive = run / "plain.tar"
            with tarfile.open(archive, "w") as bundle:
                bundle.add(root / "payload.txt", arcname="payload.txt")
                bundle.add(root / self.gate.MANIFEST_NAME, arcname=self.gate.MANIFEST_NAME)
            result = self.gate.verify_clean_archive(archive)
        self.assertIn("ARCHIVE_FORMAT_INVALID", result["codes"])

    def test_archive_rejects_bytes_after_the_single_gzip_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            (root / "payload.txt").write_text("safe\n", encoding="utf-8")
            self.assertEqual(self.gate.generate_manifest(root)["codes"], [])
            archive = run / "evidence.tar.gz"
            self.assertEqual(self.gate.build_clean_archive(root, archive)["codes"], [])
            with archive.open("ab") as stream:
                stream.write(b"TRAILING-UNMANIFESTED-PAYLOAD")
            result = self.gate.verify_clean_archive(archive)
        self.assertIn("ARCHIVE_TRAILING_DATA", result["codes"])

    def test_archive_rejects_nonzero_bytes_after_logical_tar_eof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            payload = run / "payload.txt"
            payload.write_text("safe evidence\n", encoding="utf-8")
            manifest = run / self.gate.MANIFEST_NAME
            manifest.write_text(
                f"{sha256(payload)}  payload.txt\n", encoding="utf-8"
            )
            raw_tar = run / "raw.tar"
            with tarfile.open(raw_tar, "w", format=tarfile.PAX_FORMAT) as bundle:
                for path, name in (
                    (payload, "payload.txt"),
                    (manifest, self.gate.MANIFEST_NAME),
                ):
                    info = bundle.gettarinfo(str(path), arcname=name)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as stream:
                        bundle.addfile(info, stream)
            archive = run / "tar-eof-secret.tar.gz"
            archive.write_bytes(
                gzip.compress(
                    raw_tar.read_bytes() + b"password=hidden-after-tar-eof\n",
                    mtime=0,
                )
            )
            result = self.gate.verify_clean_archive(archive)
        self.assertIn("ARCHIVE_TRAILING_DATA", result["codes"])

    def test_archive_rejects_secret_bytes_in_tar_member_padding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            payload = run / "payload.txt"
            payload.write_text("safe evidence\n", encoding="utf-8")
            manifest = run / self.gate.MANIFEST_NAME
            manifest.write_text(
                f"{sha256(payload)}  payload.txt\n", encoding="utf-8"
            )
            raw_tar = run / "raw.tar"
            with tarfile.open(raw_tar, "w", format=tarfile.PAX_FORMAT) as bundle:
                for path, name in (
                    (payload, "payload.txt"),
                    (manifest, self.gate.MANIFEST_NAME),
                ):
                    info = bundle.gettarinfo(str(path), arcname=name)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as stream:
                        bundle.addfile(info, stream)
            raw = bytearray(raw_tar.read_bytes())
            padding_start = 512 + payload.stat().st_size
            planted = b"password=hidden-in-padding"
            raw[padding_start : padding_start + len(planted)] = planted
            archive = run / "padding-secret.tar.gz"
            archive.write_bytes(gzip.compress(bytes(raw), mtime=0))
            result = self.gate.verify_clean_archive(archive)
        self.assertTrue(
            {"ARCHIVE_TRAILING_DATA", "PII_OR_SECRET_DETECTED"}.intersection(
                result["codes"]
            ),
            result,
        )

    def test_archive_path_swap_between_framing_and_tar_parse_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            payload = root / "payload.txt"
            payload.write_text("safe evidence\n", encoding="utf-8")
            self.assertEqual(self.gate.generate_manifest(root)["codes"], [])
            archive = run / "evidence.tar.gz"
            self.assertEqual(
                self.gate.build_clean_archive(root, archive)["codes"], []
            )

            raw_tar = run / "replacement.tar"
            with tarfile.open(raw_tar, "w", format=tarfile.PAX_FORMAT) as bundle:
                for name in ("payload.txt", self.gate.MANIFEST_NAME):
                    path = root / name
                    info = bundle.gettarinfo(str(path), arcname=name)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as stream:
                        bundle.addfile(info, stream)
            replacement = gzip.compress(
                raw_tar.read_bytes() + b"password=hidden-after-tar-eof\n",
                mtime=0,
            )
            original_framing = self.gate._validate_single_gzip_stream

            def validate_then_swap(snapshot: object) -> list[str]:
                result = original_framing(snapshot)
                archive.write_bytes(replacement)
                return result

            with mock.patch.object(
                self.gate,
                "_validate_single_gzip_stream",
                side_effect=validate_then_swap,
            ):
                result = self.gate.verify_clean_archive(archive)
        self.assertIn("ARCHIVE_CHANGED_DURING_VERIFICATION", result["codes"])

    def test_archive_expansion_failure_stops_before_tar_member_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "payload.tar.gz"
            archive.write_bytes(b"\x1f\x8bsynthetic")
            with mock.patch.object(
                self.gate,
                "_validate_single_gzip_stream",
                return_value=["ARCHIVE_EXPANSION_LIMIT"],
            ), mock.patch.object(self.gate.tarfile, "open") as tar_open:
                result = self.gate.verify_clean_archive(archive)
            tar_open.assert_not_called()
        self.assertEqual(result["codes"], ["ARCHIVE_EXPANSION_LIMIT"])

    def test_archive_member_count_is_bounded_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            payload = run / "payload.txt"
            payload.write_text("safe\n", encoding="utf-8")
            manifest = run / self.gate.MANIFEST_NAME
            manifest.write_text(
                f"{sha256(payload)}  payload.txt\n", encoding="utf-8"
            )
            archive = run / "evidence.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(payload, arcname="payload.txt")
                bundle.add(manifest, arcname=self.gate.MANIFEST_NAME)
            with mock.patch.object(self.gate, "_MAX_ARCHIVE_MEMBERS", 1):
                result = self.gate.verify_clean_archive(archive)
        self.assertEqual(result["codes"], ["ARCHIVE_MEMBER_COUNT_LIMIT"])

    def test_renamed_nested_archive_is_rejected_by_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            payload = root / "payload.bin"
            payload.write_bytes(b"PK\x03\x04synthetic-zip-payload")
            manifest_result = self.gate.generate_manifest(root)
            self.assertIn("NESTED_ARCHIVE", manifest_result["codes"])
            self.assertFalse((root / self.gate.MANIFEST_NAME).exists())

            (root / self.gate.MANIFEST_NAME).write_text(
                f"{sha256(payload)}  payload.bin\n", encoding="utf-8"
            )
            archive = run / "built.tar.gz"
            build_result = self.gate.build_clean_archive(root, archive)
            self.assertIn("NESTED_ARCHIVE", build_result["codes"])
            self.assertFalse(archive.exists())

            manual_archive = run / "manual.tar.gz"
            with tarfile.open(manual_archive, "w:gz") as bundle:
                bundle.add(payload, arcname="payload.bin")
                bundle.add(
                    root / self.gate.MANIFEST_NAME,
                    arcname=self.gate.MANIFEST_NAME,
                )
            verify_result = self.gate.verify_clean_archive(manual_archive)
        self.assertIn("NESTED_ARCHIVE", verify_result["codes"])

    def test_prefixed_self_extracting_zip_is_rejected_by_structure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"
            root.mkdir()
            zipped = io.BytesIO()
            with zipfile.ZipFile(zipped, "w") as bundle:
                bundle.writestr("inside.txt", "nested evidence")
            payload = root / "payload.bin"
            payload.write_bytes(b"MZ" + b"\x00" * 126 + zipped.getvalue())
            self.assertTrue(zipfile.is_zipfile(payload))
            result = self.gate.generate_manifest(root)
        self.assertIn("NESTED_ARCHIVE", result["codes"])
        self.assertFalse((root / self.gate.MANIFEST_NAME).exists())

    def test_standalone_sealers_scan_privacy_before_writing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            payload = root / "payload.json"
            payload.write_text(
                json.dumps({"password": "unsafe-secret-value"}) + "\n",
                encoding="utf-8",
            )
            manifest_result = self.gate.generate_manifest(root)
            self.assertIn("PII_OR_SECRET_DETECTED", manifest_result["codes"])
            self.assertFalse((root / self.gate.MANIFEST_NAME).exists())

            (root / self.gate.MANIFEST_NAME).write_text(
                f"{sha256(payload)}  payload.json\n", encoding="utf-8"
            )
            archive = run / "evidence.tar.gz"
            archive_result = self.gate.build_clean_archive(root, archive)
            self.assertIn("PII_OR_SECRET_DETECTED", archive_result["codes"])
            self.assertFalse(archive.exists())

    def test_standalone_manifest_rejects_mid_scan_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "evidence"
            root.mkdir()
            payload = root / "payload.json"
            payload.write_text('{"classification":"safe"}\n', encoding="utf-8")
            original_scan = self.gate.scan_before_seal
            calls = 0

            def scan_then_mutate(evidence_root: Path) -> dict[str, object]:
                nonlocal calls
                result = original_scan(evidence_root)
                calls += 1
                if calls == 1:
                    payload.write_text(
                        '{"password":"unsafe-secret-value"}\n', encoding="utf-8"
                    )
                return result

            with mock.patch.object(
                self.gate, "scan_before_seal", side_effect=scan_then_mutate
            ):
                result = self.gate.generate_manifest(root)
            self.assertIn("EVIDENCE_CHANGED_DURING_SEAL", result["codes"])
            self.assertFalse((root / self.gate.MANIFEST_NAME).exists())

    def test_standalone_archive_rejects_post_manifest_verification_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            payload = root / "payload.json"
            payload.write_text('{"classification":"safe"}\n', encoding="utf-8")
            self.assertEqual(self.gate.generate_manifest(root)["codes"], [])
            original_verify = self.gate.verify_manifest
            calls = 0

            def verify_then_mutate(evidence_root: Path) -> dict[str, object]:
                nonlocal calls
                result = original_verify(evidence_root)
                calls += 1
                if calls == 1:
                    payload.write_text(
                        '{"password":"unsafe-secret-value"}\n', encoding="utf-8"
                    )
                return result

            archive = run / "evidence.tar.gz"
            with mock.patch.object(
                self.gate, "verify_manifest", side_effect=verify_then_mutate
            ):
                result = self.gate.build_clean_archive(root, archive)
            self.assertIn("EVIDENCE_CHANGED_DURING_SEAL", result["codes"])
            self.assertFalse(archive.exists())

    def test_archive_verifier_rejects_checksum_valid_secret_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            payload = run / "secret.json"
            payload.write_text(
                '{"password":"unsafe-secret-value"}\n', encoding="utf-8"
            )
            manifest = run / self.gate.MANIFEST_NAME
            manifest.write_text(
                f"{sha256(payload)}  secret.json\n", encoding="utf-8"
            )
            archive = run / "manual.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                bundle.add(payload, arcname="secret.json")
                bundle.add(manifest, arcname=self.gate.MANIFEST_NAME)
            result = self.gate.verify_clean_archive(archive)
        self.assertIn("PII_OR_SECRET_DETECTED", result["codes"])

    def test_archive_verifier_rejects_secret_bearing_pax_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            payload = run / "payload.txt"
            payload.write_text("safe evidence\n", encoding="utf-8")
            manifest = run / self.gate.MANIFEST_NAME
            manifest.write_text(
                f"{sha256(payload)}  payload.txt\n", encoding="utf-8"
            )
            archive = run / "pax-secret.tar.gz"
            with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
                payload_info = bundle.gettarinfo(str(payload), arcname="payload.txt")
                payload_info.uid = payload_info.gid = 0
                payload_info.uname = payload_info.gname = ""
                payload_info.mtime = 0
                payload_info.pax_headers = {
                    "comment": "password=unsafe-secret-value"
                }
                with payload.open("rb") as stream:
                    bundle.addfile(payload_info, stream)
                manifest_info = bundle.gettarinfo(
                    str(manifest), arcname=self.gate.MANIFEST_NAME
                )
                manifest_info.uid = manifest_info.gid = 0
                manifest_info.uname = manifest_info.gname = ""
                manifest_info.mtime = 0
                with manifest.open("rb") as stream:
                    bundle.addfile(manifest_info, stream)
            result = self.gate.verify_clean_archive(archive)
        self.assertIn("PII_OR_SECRET_DETECTED", result["codes"])
        self.assertIn("UNSAFE_ARCHIVE_METADATA", result["codes"])

    def test_evidence_mutation_between_validation_and_manifest_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            raw_path = root / str(package["rawLogs"][0]["path"])
            original_generate = self.gate.generate_manifest

            def mutate_then_generate(evidence_root: Path) -> dict[str, object]:
                raw_path.write_text(
                    json.dumps(
                        {
                            "schemaVersion": self.gate.SCHEMA_VERSION,
                            "password": "unsafe-secret-value",
                            "assertions": [
                                {"id": "poisoned", "pass": False, "executed": 1}
                            ],
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return original_generate(evidence_root)

            with mock.patch.object(
                self.gate, "generate_manifest", side_effect=mutate_then_generate
            ):
                result = self.validate(
                    package,
                    root,
                    run / "report.json",
                    run / "evidence.tar.gz",
                )
            self.assertEqual(result["verdict"], "FAIL")
            self.assertFalse(result["mergeAuthorized"])
            self.assertFalse((root / self.gate.MANIFEST_NAME).exists())
            self.assertFalse((root / self.gate.PACKAGE_RECORD_NAME).exists())
            self.assertFalse((run / "report.json").exists())
            self.assertFalse((run / "evidence.tar.gz").exists())

    def test_final_archive_substitution_cannot_detach_validated_package(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            replacement_root = run / "replacement"
            replacement_root.mkdir()
            (replacement_root / "unrelated.txt").write_text(
                "safe unrelated evidence\n", encoding="utf-8"
            )
            self.assertEqual(
                self.gate.generate_manifest(replacement_root)["codes"], []
            )
            replacement = run / "replacement.tar.gz"
            self.assertEqual(
                self.gate.build_clean_archive(replacement_root, replacement)["codes"],
                [],
            )

            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            archive = run / "evidence.tar.gz"
            original_verify = self.gate.verify_clean_archive
            calls = 0

            def verify_then_swap(path: Path) -> dict[str, object]:
                nonlocal calls
                result = original_verify(path)
                calls += 1
                if calls == 1:
                    Path(path).unlink()
                    shutil.copyfile(replacement, path)
                return result

            with mock.patch.object(
                self.gate, "verify_clean_archive", side_effect=verify_then_swap
            ):
                result = self.validate(package, root, run / "report.json", archive)
            self.assertEqual(result["verdict"], "FAIL")
            self.assertFalse(result["mergeAuthorized"])
            self.assertIn("ARCHIVE_PACKAGE_BINDING_MISMATCH", result["codes"])
            self.assertFalse((root / self.gate.MANIFEST_NAME).exists())
            self.assertFalse((root / self.gate.PACKAGE_RECORD_NAME).exists())
            self.assertFalse((run / "report.json").exists())
            self.assertFalse(archive.exists())

    def test_non_finite_visual_metrics_never_seal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            package["visualComparisons"][0]["metric"]["value"] = float("nan")
            result = self.validate(
                package,
                root,
                run / "report.json",
                run / "evidence.tar.gz",
            )
            self.assertEqual(result["verdict"], "FAIL")
            self.assertFalse(result["mergeAuthorized"])
            self.assertFalse((root / self.gate.MANIFEST_NAME).exists())
            self.assertFalse((run / "evidence.tar.gz").exists())

    def test_shell_wrapped_protected_checkout_mutation_is_rejected(self) -> None:
        seal = {
            "head": self.fixtures.BASE_SHA,
            "entries": 299,
            "statusSha256": "a" * 64,
            "nulStatusSha256": "b" * 64,
        }
        codes = self.gate.validate_protected_checkout(
            before=seal,
            after=dict(seal),
            execution_root=Path("/private/tmp/nyay14-run"),
            protected_root=Path("/protected/NyayOne"),
            operations=("sh -c 'git -C /protected/NyayOne reset --hard'",),
        )
        self.assertIn("PROTECTED_CHECKOUT_MUTATION", codes)

    def test_read_subcommand_with_output_side_effect_is_rejected(self) -> None:
        seal = {
            "head": self.fixtures.BASE_SHA,
            "entries": 299,
            "statusSha256": "a" * 64,
            "nulStatusSha256": "b" * 64,
        }
        codes = self.gate.validate_protected_checkout(
            before=seal,
            after=dict(seal),
            execution_root=Path("/private/tmp/nyay14-run"),
            protected_root=Path("/protected/NyayOne"),
            operations=(
                "git diff --output=/protected/NyayOne/overwritten.txt HEAD~1 HEAD",
            ),
        )
        self.assertIn("PROTECTED_CHECKOUT_MUTATION", codes)

    def test_cli_rejects_package_report_alias_before_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            root = run / "evidence"
            root.mkdir()
            package = self.package(root)
            package_path = run / "package.json"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            visual_path = run / "approved.json"
            visual_path.write_text(
                json.dumps(package["approvedVisualComparisons"]),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SUBJECT),
                    "validate",
                    "--package",
                    str(package_path),
                    "--evidence-root",
                    str(root),
                    "--authoritative-repository",
                    self.fixtures.REPOSITORY,
                    "--authoritative-base",
                    self.fixtures.BASE_SHA,
                    "--authoritative-remote-head",
                    self.fixtures.HEAD_SHA,
                    "--authoritative-prospective-merge",
                    self.fixtures.MERGE_SHA,
                    "--approved-visual-matrix",
                    str(visual_path),
                    "--protected-root",
                    str(run / "protected"),
                    "--execution-root",
                    str(run / "execution"),
                    "--report",
                    str(package_path),
                    "--archive",
                    str(run / "archive.tar.gz"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            result = json.loads(completed.stdout)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(completed.stderr, "")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("OUTPUT_PATH_ALIAS", result["codes"])

    def test_package_validator_emits_each_nonpass_classification_truthfully(self) -> None:
        cases = (
            (
                "HEAD_CHANGED",
                {"claimedVerdict": "HEAD_CHANGED"},
                {"authoritative_remote_head": self.fixtures.OTHER_SHA},
            ),
            (
                "FAIL",
                {
                    "claimedVerdict": "FAIL",
                    "assertionGroups": [
                        {
                            "id": "required-gates",
                            "executed": 0,
                            "passed": 0,
                            "failed": 0,
                            "artifactIds": [],
                        }
                    ],
                },
                {},
            ),
            (
                "BLOCKED",
                {
                    "claimedVerdict": "BLOCKED",
                    "blockedReasons": ["synthetic external prerequisite"],
                },
                {},
            ),
            (
                "handoff-only",
                {"claimedVerdict": "handoff-only", "handoffOnly": True},
                {},
            ),
        )
        for expected, mutations, authority in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                run = Path(directory)
                root = run / "evidence"
                root.mkdir()
                package = self.package(root)
                package.update(mutations)
                result = self.validate(
                    package,
                    root,
                    run / "report.json",
                    run / "archive.tar.gz",
                    **authority,
                )
                self.assertEqual(result["verdict"], expected, result)
                self.assertFalse(result["mergeAuthorized"])
                self.assertFalse((root / self.gate.MANIFEST_NAME).exists())
                self.assertFalse((run / "archive.tar.gz").exists())

        # A package declaration is diagnostic-only.  The result must identify
        # the independently supplied schema as authoritative while retaining
        # the hostile declaration in a separate, non-authoritative field.
        for declared in (self.gate.SCHEMA_VERSION, "nyay14-evidence/foreign"):
            with (
                self.subTest(declared_schema=declared),
                tempfile.TemporaryDirectory() as directory,
            ):
                run = Path(directory)
                root = run / "evidence"
                root.mkdir()
                package = self.package(root, future_contact_sheet=True)
                package["schemaVersion"] = declared
                result = self.validate(
                    package,
                    root,
                    run / "report.json",
                    run / "archive.tar.gz",
                    authoritative_evidence_schema_version=(
                        self.gate.FUTURE_SCHEMA_VERSION
                    ),
                    authoritative_source_archive_sha256="a" * 64,
                    authoritative_ticket_type="non-ui",
                    authoritative_contact_sheet_panel_roles=(
                        "classification-matrix",
                        "guarded-merge-checklist",
                        "pr-comment-template",
                    ),
                )
                self.assertEqual(
                    result["schemaVersion"], self.gate.FUTURE_SCHEMA_VERSION
                )
                self.assertEqual(result["declaredSchemaVersion"], declared)
                self.assertEqual(result["verdict"], "FAIL", result)
                self.assertFalse(result["mergeAuthorized"])
                self.assertIn("SCHEMA_DOWNGRADE", result["codes"])
                self.assertFalse((run / "report.json").exists())
                self.assertFalse((run / "evidence.tar.gz").exists())
                self.assertFalse((root / self.gate.MANIFEST_NAME).exists())
                self.assertFalse((root / self.gate.PACKAGE_RECORD_NAME).exists())


if __name__ == "__main__":
    unittest.main()
