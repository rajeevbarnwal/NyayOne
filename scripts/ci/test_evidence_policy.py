#!/usr/bin/env python3
"""Seeded negative tests for uploadable evidence privacy and integrity gates."""

from __future__ import annotations

import base64
import binascii
import importlib.util
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from types import ModuleType
from unittest import mock


HERE = Path(__file__).resolve().parent


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def visually_clean_png_with_email_like_idat() -> bytes:
    """Return a valid three-pixel PNG whose compressed bytes resemble an email."""

    # One RGB scanline: the bytes are colours, not rendered text. Level-zero
    # DEFLATE deliberately preserves the planted sequence inside IDAT.
    scanline = b"\x00A@9V.yp\x00\x00"
    compressed = zlib.compress(scanline, level=0)
    if b"A@9V.yp" not in compressed:
        raise AssertionError("test setup did not preserve the planted IDAT bytes")
    header = struct.pack(">IIBBBBB", 3, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", compressed)
        + png_chunk(b"IEND", b"")
    )


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class EvidenceScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scanner = load("scan_evidence")

    def test_missing_wrong_type_empty_and_symlink_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing"
            self.assertTrue(self.scanner.scan(missing))

            regular_file = root / "evidence.txt"
            regular_file.write_text("clean\n", encoding="utf-8")
            self.assertTrue(self.scanner.scan(regular_file))

            empty = root / "empty"
            empty.mkdir()
            self.assertTrue(self.scanner.scan(empty))

            evidence = root / "evidence"
            evidence.mkdir()
            (evidence / "clean.txt").write_text("sanitized evidence\n", encoding="utf-8")
            (evidence / "linked.txt").symlink_to(evidence / "clean.txt")
            self.assertTrue(
                any("symlink" in failure for failure in self.scanner.scan(evidence))
            )

    def test_unreadable_and_opaque_payloads_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "evidence"
            evidence.mkdir()
            payload = evidence / "results.json"
            payload.write_text('{"status":"sanitized"}\n', encoding="utf-8")
            with mock.patch.object(Path, "read_bytes", side_effect=PermissionError):
                self.assertTrue(
                    any("cannot be read" in failure for failure in self.scanner.scan(evidence))
                )

            payload.rename(evidence / "hidden.zip")
            self.assertTrue(
                any("ZIP evidence is malformed" in failure for failure in self.scanner.scan(evidence))
            )

    def test_zip_members_are_scanned_and_nested_archives_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "trace.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("trace.network", '{"otp":"429016"}\n')
            self.assertTrue(
                any("raw otp field" in failure for failure in self.scanner.scan(root))
            )

            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("nested.zip", b"not independently scanned")
            self.assertTrue(
                any("nested archive" in failure for failure in self.scanner.scan(root))
            )

    def test_empty_unsafe_and_magic_disguised_zip_archives_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "evidence.bin"

            with zipfile.ZipFile(archive, "w"):
                pass
            failures = self.scanner.scan(root)
            self.assertTrue(any("zero regular members" in failure for failure in failures))

            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("../person@nls.ac.in.txt", "sanitized\n")
            failures = self.scanner.scan(root)
            self.assertTrue(any("unsafe ZIP member path" in failure for failure in failures))
            self.assertTrue(any("path: raw email address" in failure for failure in failures))
            self.assertNotIn("person@nls.ac.in", "\n".join(failures))

            nested = root / "nested-source.zip"
            with zipfile.ZipFile(nested, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("safe.txt", "sanitized\n")
            nested_bytes = nested.read_bytes()
            nested.unlink()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("renamed.txt", nested_bytes)
            self.assertTrue(
                any("nested archive" in failure for failure in self.scanner.scan(root))
            )

            prefixed = root / "prefixed.zip"
            with zipfile.ZipFile(prefixed, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("safe.txt", "sanitized\n")
            prefixed.write_bytes(b'{"otp":"429016"}\n' + prefixed.read_bytes())
            self.assertTrue(
                any(
                    "ZIP signature must begin at byte zero" in failure
                    for failure in self.scanner.scan(root)
                )
            )

    def test_zip_comments_member_paths_and_member_contents_are_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "evidence.zip"
            info = zipfile.ZipInfo("person%2540nls.ac.in.txt")
            info.comment = b'{"otp":"429016"}'
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.comment = b'{"mobile":"9876543210"}'
                bundle.writestr(info, '{"session_token":"opaque-value-123456"}')

            report = self.scanner.scan_report(root)
            joined = "\n".join(report.failures)
            self.assertIn("raw mobile field", joined)
            self.assertIn("raw otp field", joined)
            self.assertIn("raw auth field", joined)
            self.assertIn("path: raw email address", joined)
            self.assertNotIn("person@nls.ac.in", joined)
            self.assertNotIn("opaque-value-123456", joined)

    def test_visual_pdf_and_unknown_binary_payloads_are_rejected_by_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            png = root / "clean.png"
            png.write_bytes(visually_clean_png_with_email_like_idat())
            report = self.scanner.scan_report(root)
            self.assertTrue(any("pixel privacy inspection" in item for item in report.errors))
            self.assertFalse(any("raw email address" in item for item in report.findings))

            png.rename(root / "renamed.txt")
            report = self.scanner.scan_report(root)
            self.assertTrue(any("PNG evidence" in item for item in report.errors))
            self.assertFalse(any("raw email address" in item for item in report.findings))

            (root / "renamed.txt").unlink()
            (root / "capture.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x02\xff\xd9")
            self.assertTrue(any("JPEG evidence" in item for item in self.scanner.scan(root)))

            (root / "capture.jpg").unlink()
            (root / "report.bin").write_bytes(b"%PDF-1.7\nplanted\n%%EOF")
            self.assertTrue(any("PDF evidence" in item for item in self.scanner.scan(root)))

            (root / "report.bin").write_bytes(b"\x00\xff\x10\x80")
            self.assertTrue(
                any("unknown binary evidence" in item for item in self.scanner.scan(root))
            )

    def test_fake_image_extension_still_scans_text_canaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "not-an-image.png").write_text(
                '{"otp":"429016"}\n',
                encoding="utf-8",
            )
            report = self.scanner.scan_report(root)
            self.assertTrue(any("visual extension" in item for item in report.errors))
            self.assertTrue(any("raw otp field" in item for item in report.findings))

    def test_redacted_sentinels_are_accepted_in_all_text_forms(self) -> None:
        payload = b"\n".join(
            (
                b'{"session_token":"<redacted>","otp":"[MASKED]",'
                b'"mobile":"***3210","institutional_email":"reviewer@example.test",'
                b'"date_of_birth":"omitted","first_name":"synthetic"}',
                b"GET /callback?auth_token=%3Credacted%3E&otp=masked&mobile=***3210",
                b'Content-Disposition: form-data; name="session_token"\r\n'
                b"\r\n[REDACTED]\r\n--boundary--",
                b"Authorization: Bearer redacted",
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sanitized.log").write_bytes(payload)
            self.assertEqual(self.scanner.scan_report(root).failures, [])

    def test_query_form_and_multipart_sensitive_values_are_rejected(self) -> None:
        payload = b"\n".join(
            (
                b"POST /submit?otp=429016&mobile=9876543210"
                b"&email=person%40nls.ac.in&date_of_birth=2004-03-14"
                b"&first_name=Aditi&session_token=opaque-query-token-123456",
                b'Content-Disposition: form-data; name="password"\r\n'
                b"\r\nsecret-form-value\r\n--boundary--",
                b'{"value":"opaque-form-token-123456","name":"auth_token"}',
                b'{"name":"nyayone_session","value":"opaque-cookie-value-123456"}',
                b"GET /complete#session_token=opaque-fragment-token-123456",
                b"GET /complete#session%2554oken=opaque-double-encoded-123456",
                b"otp: 429016\nmobile: 9876543210\n"
                b"date_of_birth: 2004-03-14\nfirst_name: Aditi",
                b"verificationCode = 429016\nphoneNumber = 9876543210\n"
                b"dateOfBirth = 2004-03-14\nfirstName = Aditi",
                b"{otp: 429016, mobile: 9876543210}",
                b'{"urlsVisited":["https://example.test/s-35#token='
                b'join_0123456789abcdefghijklmnopqrstuv"]}',
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "request.log").write_bytes(payload)
            joined = "\n".join(self.scanner.scan(root))
            for expected in (
                "raw auth field",
                "raw otp field",
                "raw mobile field",
                "raw email address",
                "raw date of birth field",
                "raw personal name field",
            ):
                with self.subTest(expected=expected):
                    self.assertIn(expected, joined)
            self.assertNotIn("person@nls.ac.in", joined)
            self.assertNotIn("opaque-query-token-123456", joined)

    def test_each_alternate_structured_field_shape_is_rejected_in_isolation(self) -> None:
        payloads = {
            "camel session": ('{"sessionToken":"opaque-session-123456"}', "raw auth field"),
            "camel join": ('{"joinToken":"opaque-join-123456"}', "raw auth field"),
            "camel otp": ('{"verificationCode":"429016"}', "raw otp field"),
            "camel mobile": ('{"phoneNumber":"9876543210"}', "raw mobile field"),
            "camel dob": ('{"dateOfBirth":"2004-03-14"}', "raw date of birth field"),
            "camel name": ('{"firstName":"Aditi"}', "raw personal name field"),
            "cookie array": (
                '{"cookies":[{"name":"nyayone_session","value":"opaque-cookie-123456"}]}',
                "raw auth field",
            ),
            "inline yaml": ("{otp: 429016}", "raw otp field"),
            "toml": ("phoneNumber = 9876543210", "raw mobile field"),
            "python repr": ("{'sessionToken': 'opaque-python-123456'}", "raw auth field"),
            "encoded fragment key": (
                "GET /done#session%2554oken=opaque-fragment-123456",
                "raw auth field",
            ),
            "repeatedly encoded query key": (
                "GET /done?session%25252554oken=opaque-query-123456",
                "raw auth field",
            ),
            "repeatedly encoded fragment key": (
                "GET /done#session%25252554oken=opaque-fragment-123456",
                "raw auth field",
            ),
            "repeatedly encoded URL path": (
                "https://example.test/person%25252540nls.ac.in/profile",
                "raw email address",
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "result.txt"
            for label, (payload, expected) in payloads.items():
                with self.subTest(label=label):
                    evidence.write_text(payload + "\n", encoding="utf-8")
                    self.assertIn(expected, "\n".join(self.scanner.scan(root)))

    def test_declared_bounded_base64_bodies_are_decoded_and_dispatched(self) -> None:
        otp_body = base64.b64encode(b'{"otp":"429016"}')
        image_body = base64.b64encode(visually_clean_png_with_email_like_idat())
        payload = json.dumps(
            {
                "requests": [
                    {"encoding": "base64", "body": otp_body.decode("ascii")},
                    {"body": image_body.decode("ascii"), "content_encoding": "base64"},
                ]
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "encoded.json"
            evidence.write_text(payload, encoding="utf-8")
            joined = "\n".join(self.scanner.scan(root))
            self.assertIn("raw otp field", joined)
            self.assertIn("PNG evidence", joined)

            evidence.write_text(
                '{"encoding":"base64","body":"!!!not-base64!!!"}',
                encoding="utf-8",
            )
            self.assertTrue(
                any("base64 body is malformed" in item for item in self.scanner.scan(root))
            )

            with mock.patch.object(self.scanner, "MAX_BASE64_ENCODED_BYTES", 8):
                evidence.write_text(
                    '{"encoding":"base64","body":"QUFBQUFBQUFB"}',
                    encoding="utf-8",
                )
                self.assertTrue(
                    any(
                        "base64 body exceeds the scan limit" in item
                        for item in self.scanner.scan(root)
                    )
                )

    def test_data_url_and_transfer_encoded_base64_are_scanned(self) -> None:
        encoded = base64.b64encode(b'{"otp":"429016"}')
        payload = (
            b"data:text/plain;base64,"
            + encoded
            + b"\nContent-Transfer-Encoding: base64\r\n\r\n"
            + encoded
            + b"\r\n--boundary--"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "encoded.log").write_bytes(payload)
            self.assertTrue(
                any("raw otp field" in item for item in self.scanner.scan(root))
            )

    def test_top_level_sensitive_path_is_detected_without_echoing_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sensitive_name = "person@nls.ac.in.log"
            (root / sensitive_name).write_text("sanitized\n", encoding="utf-8")
            failures = self.scanner.scan(root)
            self.assertTrue(any("path: raw email address" in item for item in failures))
            self.assertNotIn(sensitive_name, "\n".join(failures))

            (root / sensitive_name).unlink()
            double_encoded = root / "person%2540nls.ac.in.log"
            double_encoded.write_text("sanitized\n", encoding="utf-8")
            failures = self.scanner.scan(root)
            self.assertTrue(any("path: raw email address" in item for item in failures))
            self.assertNotIn("person%2540nls.ac.in", "\n".join(failures))

            double_encoded.unlink()
            repeatedly_encoded = root / "person%25252540nls.ac.in.log"
            repeatedly_encoded.write_text("sanitized\n", encoding="utf-8")
            failures = self.scanner.scan(root)
            self.assertTrue(any("path: raw email address" in item for item in failures))
            self.assertNotIn("person%25252540nls.ac.in", "\n".join(failures))

    def test_each_secret_and_pii_canary_is_rejected(self) -> None:
        payloads = {
            "bearer": b"Authorization: Bearer nyayone-ci-planted-canary-0123456789\n",
            "json bearer": b'{"Authorization":"Bearer nyayone-json-canary-0123456789"}\n',
            "cookie": b'{"cookie":"nyayone_session=nyayone-cookie-canary-0123456789"}\n',
            "jwt": b"eyJueWF5b25lIjoiY2FuYXJ5In0.eyJzY29wZSI6InRlc3QifQ.c2lnbmF0dXJlLWNhbmFyeQ\n",
            "otp": b'{"otp":"429016"}\n',
            "mobile": b'{"mobile":"9876543210"}\n',
            "email": b'{"institutional_email":"person@nls.ac.in"}\n',
            "dob": b'{"date_of_birth":"2004-03-14"}\n',
            "name": b'{"first_name":"Aditi"}\n',
            "storage": b'{"localStorage":{"session_token":"opaque-value-123456"}}\n',
            "env token": b"WAVE4_E2E_SESSION_TOKEN=opaque-env-value-123456\n",
            "query token": b"GET /callback?auth_token=opaque-query-value-123456\n",
            "form token": b'{"name":"session_token","value":"opaque-form-value-123456"}\n',
            "join token": b'{"join_token":"join_planted_secret_123456789"}\n',
            "escaped join token": b'{"body":"{\\\"join_token\\\":\\\"join_planted_secret_123456789\\\"}"}\n',
            "private key": b"-----BEGIN PRIVATE KEY-----\nplanted\n",
            "GitHub token": b"ghp_0123456789abcdefghijklmnopqrstuv\n",
            "AWS key": b"AKIA0123456789ABCDEF\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            leak = root / "evidence.txt"
            for label, payload in payloads.items():
                with self.subTest(label=label):
                    leak.write_bytes(payload)
                    report = self.scanner.scan_report(root)
                    self.assertEqual(report.files_discovered, 1)
                    self.assertGreaterEqual(len(report.findings), 1, report)

    def test_clean_sanitized_evidence_reports_nonzero_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "summary.json").write_text(
                '{"status":"pass","email":"reviewer@example.test",'
                '"destination_masked":"******3210","first_name":"redacted"}\n',
                encoding="utf-8",
            )
            report = self.scanner.scan_report(root)
            self.assertEqual(report.failures, [])
            self.assertEqual(report.files_discovered, 1)
            self.assertGreater(report.bytes_scanned, 0)

    def test_directory_traversal_error_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def denied_walk(*_args, **kwargs):
                kwargs["onerror"](PermissionError("planted unreadable directory"))
                return iter(())

            with mock.patch.object(
                self.scanner.os,
                "walk",
                side_effect=denied_walk,
            ):
                report = self.scanner.scan_report(root)
            self.assertTrue(
                any("cannot be traversed" in error for error in report.errors),
                report.errors,
            )


class EvidenceManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load("evidence_manifest")

    def test_seal_and_verify_require_complete_nonempty_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "summary.json").write_text('{"status":"pass"}\n', encoding="utf-8")
            screenshots = root / "screenshots"
            screenshots.mkdir()
            (screenshots / "screen.png").write_bytes(b"synthetic-png-fixture")

            count, failures = self.manifest.seal(root)
            self.assertEqual((count, failures), (2, []))
            verified, failures = self.manifest.verify(root)
            self.assertEqual((verified, failures), (2, []))

            (root / "unlisted.txt").write_text("late payload\n", encoding="utf-8")
            _, failures = self.manifest.verify(root)
            self.assertTrue(any("not listed" in failure for failure in failures), failures)

    def test_tamper_duplicate_traversal_and_symlink_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "summary.txt"
            payload.write_text("pass\n", encoding="utf-8")
            self.assertEqual(self.manifest.seal(root)[1], [])
            payload.write_text("tampered\n", encoding="utf-8")
            _, failures = self.manifest.verify(root)
            self.assertTrue(any("checksum mismatch" in failure for failure in failures))

            manifest = root / self.manifest.MANIFEST_NAME
            row = manifest.read_text(encoding="utf-8").strip()
            manifest.write_text(f"{row}\n{row}\n{'0' * 64}  ../escape\n", encoding="utf-8")
            _, failures = self.manifest.verify(root)
            self.assertTrue(any("duplicate" in failure for failure in failures))
            self.assertTrue(any("unsafe path" in failure for failure in failures))

            linked = root / "linked.txt"
            linked.symlink_to(payload)
            _, failures = self.manifest.verify(root)
            self.assertTrue(any("symlink" in failure for failure in failures))

    def test_missing_and_empty_evidence_cannot_be_sealed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(self.manifest.seal(root)[1])
            self.assertTrue(self.manifest.verify(root / "missing")[1])

            (root / "empty.json").write_bytes(b"")
            _, failures = self.manifest.seal(root)
            self.assertTrue(any("zero-byte" in failure for failure in failures), failures)

    def test_frozen_qa_evidence_rejects_namespace_and_byte_drift(self) -> None:
        verifier = load("verify_sha256_manifests")
        allowed = {
            Path("QA/evidence/NYAY-20/run/report.json"): b"sealed report\n",
            Path("QA/evidence/SAATHI-60/README.md"): b"legacy evidence\n",
        }

        def frozen_digest(root: Path, tracked: set[Path]) -> str:
            digest = hashlib.sha256()
            for relative in sorted(tracked):
                if not relative.is_relative_to(verifier.QA_EVIDENCE_ROOT):
                    continue
                path_bytes = relative.as_posix().encode("utf-8", "surrogatepass")
                digest.update(len(path_bytes).to_bytes(8, "big"))
                digest.update(path_bytes)
                digest.update(bytes.fromhex(verifier._sha256_file(root / relative)))
            return digest.hexdigest()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, data in allowed.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            exact = set(allowed) | {Path("README.md")}
            expected_digest = frozen_digest(root, exact)
            with (
                mock.patch.object(verifier, "ROOT", root),
                mock.patch.object(
                    verifier, "FROZEN_QA_EVIDENCE_FILE_COUNT", len(allowed)
                ),
                mock.patch.object(
                    verifier, "FROZEN_QA_EVIDENCE_SHA256", expected_digest
                ),
            ):
                self.assertEqual(verifier.frozen_qa_evidence_failures(exact), [])

                added_path = Path("QA/evidence/NYAY-20/run/extra.json")
                added_target = root / added_path
                added_target.write_text("added\n", encoding="utf-8")
                self.assertTrue(
                    verifier.frozen_qa_evidence_failures(exact | {added_path})
                )

                deleted = exact - {Path("QA/evidence/SAATHI-60/README.md")}
                self.assertTrue(verifier.frozen_qa_evidence_failures(deleted))

                report = root / "QA/evidence/NYAY-20/run/report.json"
                report.write_text("modified report\n", encoding="utf-8")
                failures = verifier.frozen_qa_evidence_failures(exact)
                self.assertTrue(any("bytes differ" in item for item in failures), failures)
                report.write_bytes(allowed[Path("QA/evidence/NYAY-20/run/report.json")])

                for label, alias in {
                    "case drift": Path("QA/evidence/NYAY-20/RUN/report.json"),
                    "underscore drift": Path("QA/evidence/NYAY_20/run/report.json"),
                }.items():
                    with self.subTest(label=label):
                        target = root / alias
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(
                            allowed[Path("QA/evidence/NYAY-20/run/report.json")]
                        )
                        drifted = (
                            exact - {Path("QA/evidence/NYAY-20/run/report.json")}
                        ) | {alias}
                        failures = verifier.frozen_qa_evidence_failures(drifted)
                        self.assertTrue(
                            any("bytes differ" in item for item in failures), failures
                        )
                        self.assertNotIn(alias.as_posix(), "\n".join(failures))

                control_path = Path("QA/evidence/NYAY-20/run/raw\nreview.txt")
                control_target = root / control_path
                control_target.write_text("sanitized\n", encoding="utf-8")
                failures = verifier.frozen_qa_evidence_failures(
                    exact | {control_path}
                )
                self.assertTrue(
                    any("control characters" in item for item in failures), failures
                )

                root_case_alias = Path("qa/evidence/NYAY-20/run/report.json")
                root_case_target = root / root_case_alias
                root_case_target.parent.mkdir(parents=True, exist_ok=True)
                root_case_target.write_text("sealed report\n", encoding="utf-8")
                failures = verifier.frozen_qa_evidence_failures(
                    exact | {root_case_alias}
                )
                self.assertTrue(
                    any("canonical casing" in item for item in failures), failures
                )

    def test_tracked_file_inventory_is_nul_delimited(self) -> None:
        verifier = load("verify_sha256_manifests")
        unusual = Path("QA/evidence/NYAY-20/run/raw\nreview.txt")
        payload = unusual.as_posix().encode("utf-8") + b"\0README.md\0"
        with mock.patch.object(
            verifier.subprocess, "check_output", return_value=payload
        ):
            self.assertEqual(verifier.tracked_files(), {unusual, Path("README.md")})

    def test_repository_manifest_verifier_rejects_tracked_symlink(self) -> None:
        verifier = load("verify_sha256_manifests")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "QA" / "evidence" / "NYAY-15" / "run"
            package.mkdir(parents=True)
            target = package / "target.txt"
            target.write_text("sanitized\n", encoding="utf-8")
            linked = package / "linked.txt"
            linked.symlink_to(target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            manifest = package / "SHA256SUMS.txt"
            manifest.write_text(
                f"{digest}  target.txt\n{digest}  linked.txt\n",
                encoding="utf-8",
            )
            tracked = ("\0".join(
                [
                    "QA/evidence/NYAY-15/run/SHA256SUMS.txt",
                    "QA/evidence/NYAY-15/run/linked.txt",
                    "QA/evidence/NYAY-15/run/target.txt",
                ]
            ) + "\0").encode("utf-8")
            verifier.ROOT = root
            with mock.patch.object(verifier.subprocess, "check_output", return_value=tracked):
                _, failures = verifier.verify(manifest)
            self.assertTrue(any("symlink" in failure for failure in failures), failures)

            external_manifest = root / "external-manifest.txt"
            external_manifest.write_text(
                f"{digest}  target.txt\n",
                encoding="utf-8",
            )
            manifest.unlink()
            manifest.symlink_to(external_manifest)
            with mock.patch.object(verifier.subprocess, "check_output", return_value=tracked):
                _, failures = verifier.verify(manifest)
            self.assertTrue(
                any("manifest symlink" in failure for failure in failures), failures
            )


class UploadableEvidenceTests(unittest.TestCase):
    @staticmethod
    def _contract(
        exporter: ModuleType,
        rows_key: str,
        identity_key: str,
        identities: list[str],
    ) -> tuple[str, str, int, str]:
        return (
            rows_key,
            identity_key,
            len(identities),
            exporter._identity_digest(identities),
        )

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def test_attestation_quarantines_raw_structured_visual_and_archive_payloads(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        manifest = load("evidence_manifest")
        scanner = load("scan_evidence")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            destination = root / "uploadable"
            source.mkdir()
            (source / "results.json").write_text(
                json.dumps(
                    {
                        "total": 1,
                        "passed": 1,
                        "failed": 0,
                        "rows": [
                            {
                                "pass": True,
                                "area": "wave1-planted-area",
                                "actual": (
                                    "student 9876543210 described a private narrative; "
                                    "novel sk_live_planted_credential"
                                ),
                            }
                        ],
                    }
                ) + "\n",
                encoding="utf-8",
            )
            (source / "screen.png").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
            screenshots = source / "screenshots"
            screenshots.mkdir()
            (screenshots / "private.png").write_bytes(
                b"\x89PNG\r\n\x1a\nsynthetic-private"
            )
            (source / "service.log").write_text(
                "private narrative that must remain local\n", encoding="utf-8"
            )
            with zipfile.ZipFile(source / "trace.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("trace.txt", "not uploadable in phase 1")
            work = source / "work"
            work.mkdir()
            (work / "state.json").write_text(
                '{"join_token":"join_planted_secret_123456789"}\n',
                encoding="utf-8",
            )

            contract = self._contract(
                exporter, "rows", "area", ["wave1-planted-area"]
            )
            with mock.patch.dict(
                exporter.INVENTORY_CONTRACTS,
                {"wave1-browser": contract},
            ):
                included, quarantined, failures = exporter.prepare(
                    source, destination, "wave1"
                )
            self.assertEqual((included, quarantined, failures), (1, 5, []))
            self.assertFalse((destination / "results.json").exists())
            self.assertFalse((destination / "screen.png").exists())
            self.assertFalse((destination / "screenshots" / "private.png").exists())
            self.assertFalse((destination / "trace.zip").exists())
            self.assertFalse((destination / "service.log").exists())
            self.assertFalse((destination / "work" / "state.json").exists())
            export = (destination / exporter.EXPORT_NAME).read_text(encoding="utf-8")
            self.assertNotIn("screen.png", export)
            self.assertNotIn("trace.zip", export)
            self.assertNotIn("private narrative", export)
            self.assertNotIn("9876543210", export)
            self.assertNotIn("sk_live", export)
            self.assertNotIn("join_planted_secret", export)
            export_payload = json.loads(export)
            self.assertEqual(export_payload["producerProfile"], "wave1")
            self.assertEqual(
                export_payload["structuredCandidates"],
                [
                    {
                        "artifactId": "wave1-browser",
                        "assertionCount": 1,
                        "executed": True,
                        "failedAssertionCount": 0,
                        "inventoryComplete": True,
                        "producerState": "pass",
                        "sizeClass": "up-to-1KiB",
                    }
                ],
            )
            self.assertTrue(export_payload["quarantined"])
            self.assertTrue(any(
                row.get("mediaClass") == "sensitive-capture"
                and row.get("count") == 2
                for row in export_payload["quarantined"]
            ))
            self.assertTrue(
                all(
                    "contentSha256" not in row and "pathSha256" not in row
                    for row in export_payload["quarantined"]
                )
            )
            self.assertEqual(manifest.seal(destination)[1], [])
            self.assertEqual(scanner.scan(destination), [])

    def test_quarantine_media_classes_are_closed_and_do_not_echo_suffixes(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            self._write_json(
                source / "results.json",
                {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "rows": [{"area": "known-area", "pass": True}],
                },
            )
            planted_suffix = ".student-secret-9876543210"
            (source / f"capture{planted_suffix}").write_text(
                "runner-local diagnostic\n", encoding="utf-8"
            )
            contract = self._contract(exporter, "rows", "area", ["known-area"])
            with mock.patch.dict(
                exporter.INVENTORY_CONTRACTS,
                {"wave1-browser": contract},
            ):
                included, quarantined, failures = exporter.prepare(
                    source, root / "uploadable", "wave1"
                )
            self.assertEqual((included, quarantined, failures), (1, 1, []))
            raw_export = (root / "uploadable" / exporter.EXPORT_NAME).read_text(
                encoding="utf-8"
            )
            payload = json.loads(raw_export)
            self.assertNotIn(planted_suffix, raw_export)
            self.assertNotIn("9876543210", raw_export)
            self.assertEqual(payload["quarantined"][0]["mediaClass"], "other")
            self.assertTrue(
                all(
                    row["mediaClass"] in exporter.QUARANTINE_MEDIA_CLASSES
                    for row in payload["quarantined"]
                )
            )

    def test_required_json_rejects_duplicate_keys_and_nonfinite_numbers(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        payloads = {
            "duplicate top-level rows": (
                '{"total":1,"passed":1,"failed":0,'
                '"rows":[{"area":"first","pass":false}],'
                '"rows":[{"area":"second","pass":true}]}\n'
            ),
            "duplicate nested pass": (
                '{"total":1,"passed":1,"failed":0,'
                '"rows":[{"area":"first","pass":false,"pass":true}]}\n'
            ),
            "NaN": (
                '{"total":1,"passed":1,"failed":0,'
                '"rows":[{"area":"first","pass":true,"metric":NaN}]}\n'
            ),
            "Infinity": (
                '{"total":1,"passed":1,"failed":0,'
                '"rows":[{"area":"first","pass":true,"metric":Infinity}]}\n'
            ),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (label, raw) in enumerate(payloads.items()):
                with self.subTest(label=label):
                    source = root / f"source-{index}"
                    source.mkdir()
                    (source / "results.json").write_text(raw, encoding="utf-8")
                    failures = exporter.prepare(
                        source, root / f"out-{index}", "wave1"
                    )[2]
                    self.assertTrue(
                        any("not valid UTF-8 JSON" in item for item in failures),
                        failures,
                    )

    def test_exact_inventory_rejects_shrink_substitute_and_duplicate(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        identities = ["area-a", "area-b", "area-c"]
        contract = self._contract(exporter, "rows", "area", identities)

        def payload(areas: list[str]) -> dict[str, object]:
            return {
                "total": len(areas),
                "passed": len(areas),
                "failed": 0,
                "rows": [{"area": area, "pass": True} for area in areas],
            }

        variants = {
            "shrink": identities[:-1],
            "substitute": ["area-a", "area-b", "area-x"],
            "duplicate": ["area-a", "area-b", "area-b"],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            exporter.INVENTORY_CONTRACTS,
            {"wave1-browser": contract},
        ):
            root = Path(directory)
            positive = root / "positive"
            self._write_json(positive / "results.json", payload(identities))
            self.assertEqual(
                exporter.prepare(positive, root / "positive-out", "wave1")[2],
                [],
            )

            for index, (label, areas) in enumerate(variants.items()):
                with self.subTest(label=label):
                    source = root / f"source-{index}"
                    self._write_json(source / "results.json", payload(areas))
                    failures = exporter.prepare(
                        source, root / f"out-{index}", "wave1"
                    )[2]
                    if label == "duplicate":
                        expected = "invalid or duplicated"
                    else:
                        expected = "incomplete or substituted"
                    self.assertTrue(
                        any(expected in item for item in failures), failures
                    )

    def test_snapshot_rejects_missing_empty_and_zero_byte_sources(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertTrue(exporter.prepare(root / "missing", root / "out", "wave1")[2])
            source = root / "source"
            source.mkdir()
            self.assertTrue(exporter.prepare(source, root / "empty-out", "wave1")[2])
            (source / "empty.json").write_bytes(b"")
            self.assertTrue(exporter.prepare(source, root / "zero-out", "wave1")[2])

    def test_profile_inventory_and_semantics_fail_closed(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        contract = self._contract(exporter, "rows", "area", ["failed-area"])
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            exporter.INVENTORY_CONTRACTS,
            {"wave1-browser": contract},
        ):
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "safe.json").write_text('{"status":"pass"}\n', encoding="utf-8")
            failures = exporter.prepare(source, root / "unrelated", "wave1")[2]
            self.assertTrue(any("missing required producer" in item for item in failures))

            (source / "results.json").write_text(
                '{"total":2,"passed":2,"failed":0,"rows":[{"pass":true}]}\n',
                encoding="utf-8",
            )
            failures = exporter.prepare(source, root / "inconsistent", "wave1")[2]
            self.assertTrue(any("declared browser counts" in item for item in failures))

            (source / "results.json").write_text(
                '{"total":1,"passed":0,"failed":1,'
                '"rows":[{"area":"failed-area","pass":false}]}\n',
                encoding="utf-8",
            )
            included, _, failures = exporter.prepare(source, root / "failed", "wave1")
            self.assertEqual((included, failures), (1, []))
            payload = json.loads(
                (root / "failed" / exporter.EXPORT_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(payload["structuredCandidates"][0]["producerState"], "fail")

    def test_wave1_production_inventory_contract_is_exactly_pinned(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        self.assertEqual(
            exporter.INVENTORY_CONTRACTS.get("wave1-browser"),
            (
                "rows", "area", 1467,
                "250d3429ae3056dc2b117e013196ee896c8d73b3e99dfc61d3ebd27ef66f8f65",
            ),
        )

    def test_nyay5_production_inventory_contracts_are_exactly_pinned(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        self.assertEqual(exporter.NYAY5_POSTGRES_MUTANT_COUNT, 29)
        self.assertEqual(
            exporter.INVENTORY_CONTRACTS.get("nyay5-postgres"),
            (
                "assertions", "id", 21,
                "ced6011b74db2f2b1c890f8ac1d7b3a212ff2aac8f7259e4ef6085e5d4dfd372",
            ),
        )
        self.assertEqual(
            exporter.INVENTORY_CONTRACTS.get("nyay5-browser"),
            (
                "rows", "name", 22,
                "b9e7aa70519d7d16f044b2ac928fb039cce8d2e073bd1b0303f9f58787d28071",
            ),
        )
        self.assertEqual(
            exporter.INVENTORY_CONTRACTS.get("nyay5-acceptance-attestations"),
            (
                "executions", "id", 12,
                "3f22abbff483c686efaabc3d86ab33bd2b8758aa95d4df77b8f306edddb9b328",
            ),
        )
        self.assertEqual(
            exporter.INVENTORY_CONTRACTS.get("nyay5-acceptance-matrix"),
            (
                "assertions", "id", 61,
                "3808f4a08805ec0cc8f904996c9fda428904ae48d8f34e261e3e07791e6d597e",
            ),
        )

    def test_every_profile_accepts_only_its_complete_consistent_inventory(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        inventory_contracts = {
            "wave1-browser": self._contract(
                exporter, "rows", "area", ["wave1-area"]
            ),
            "wave2-postgres": self._contract(
                exporter, "assertions", "id", ["W2-01"]
            ),
            "registration-browser": self._contract(
                exporter, "results", "name", ["registration-01"]
            ),
            "auth-browser": self._contract(
                exporter, "rows", "area", ["auth-area"]
            ),
            "nyay22-browser": self._contract(
                exporter, "rows", "name", ["runtime-chromium"]
            ),
            "nyay22-postgres": self._contract(
                exporter, "oracles", "id", ["NYAY22-PG-01"]
            ),
            "wave4-postgres": self._contract(
                exporter, "results", "id", ["W4-PG-01"]
            ),
            "reporting-browser": self._contract(
                exporter, "rows", "name", ["reporting-01"]
            ),
            "moderation-browser": self._contract(
                exporter, "rows", "name", ["moderation-01"]
            ),
            "risk-label-browser": self._contract(
                exporter, "rows", "name", ["risk-01"]
            ),
            "wave5-postgres": self._contract(
                exporter, "rows", "id", ["W5-PG-01"]
            ),
            "wave5-real-browser": self._contract(
                exporter, "rows", "name", ["wave5-real-01"]
            ),
            "nyay5-postgres": self._contract(
                exporter, "assertions", "id", ["N5-PG-01"]
            ),
            "nyay5-browser": self._contract(
                exporter, "rows", "name", ["nyay5-browser-01"]
            ),
            "nyay5-acceptance-attestations": self._contract(
                exporter, "executions", "id", ["native:frontend-unit"]
            ),
            "nyay5-acceptance-matrix": self._contract(
                exporter, "assertions", "id", ["QA-01"]
            ),
        }
        credential_contracts = {
            group: (
                1,
                exporter._identity_digest([f"{group}:{group}-01"]),
            )
            for group in ("functional", "negative", "geometry")
        }
        profile_payloads = {
            "wave1": {
                "results.json": {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "rows": [{"area": "wave1-area", "pass": True}],
                },
            },
            "wave2": {
                "wave2-db-gate/summary.json": {
                    "gate": "wave2_postgres",
                    "status": "PASS",
                    "exit_code": 0,
                    "executed": True,
                    "assertions": [{"id": "W2-01", "status": "PASS"}],
                    "failed_assertions": [],
                },
            },
            "wave3": {
                "credentials/credential-e2e-report.json": {
                    "functional": [{"name": "functional-01", "pass": True}],
                    "negative": [{"name": "negative-01", "pass": True}],
                    "geometry": [{"name": "geometry-01", "pass": True}],
                    "failures": [],
                    "summary": {
                        "functionalPassed": 1,
                        "functionalFailed": 0,
                        "negativePassed": 1,
                        "negativeFailed": 0,
                        "geometryPassed": 1,
                        "geometryFailed": 0,
                    },
                },
                "registration/registration_e2e_report.json": {
                    "passed": 1,
                    "failed": 0,
                    "results": [{"name": "registration-01", "pass": True}],
                },
                "v34-s01-s10/results.json": {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "rows": [{"area": "auth-area", "pass": True}],
                },
                "nyay22-browser/results.json": {
                    "schemaVersion": "nyay22-browser-evidence.v1",
                    "rows": [{"name": "runtime-chromium", "pass": True}],
                    "summary": {"total": 1, "passed": 1, "failed": 0},
                    "authorityModel": "withServerProvenMentorSession",
                },
                "nyay22-postgres/summary.json": {
                    "schema_version": "nyay22-mentor-postgres/v1",
                    "status": "PASS",
                    "classification": "EXECUTED",
                    "postgres_major": 16,
                    "pgvector_present": True,
                    "oracles": [
                        {"id": "NYAY22-PG-01", "status": "PASS", "assertions": 1}
                    ],
                    "summary": {"passed": 1, "total": 1},
                },
            },
            "wave4": {
                "wave4-postgres/summary.json": {
                    "gate": "wave4_postgres",
                    "status": "PASS",
                    "executed": True,
                    "results": [{"id": "W4-PG-01", "status": "PASS"}],
                    "failed_assertions": [],
                },
                "wave4-browser/results.json": {
                    "rows": [{"name": "reporting-01", "pass": True}],
                    "failures": [],
                },
                "wave4-moderation-browser/results.json": {
                    "rows": [{"name": "moderation-01", "pass": True}],
                    "failures": [],
                },
                "wave4-risk-label-browser/results.json": {
                    "target": "isolated-loopback-real-api-postgresql-chromium",
                    "databaseDialect": "postgresql",
                    "rows": [{"name": "risk-01", "pass": True}],
                    "failures": [],
                },
                "wave4-risk-label-fixture.json": {
                    "organisation_id": "00000000-0000-4000-8000-000000000001",
                    "candidate_cluster_id": "00000000-0000-4000-8000-000000000002",
                    "candidate_version": "1",
                    "prepublished_label_id": "00000000-0000-4000-8000-000000000003",
                    "valid_request_id": "00000000-0000-4000-8000-000000000004",
                    "expired_request_id": "00000000-0000-4000-8000-000000000005",
                    "boundary_request_id": "00000000-0000-4000-8000-000000000006",
                    "database_dialect": "postgresql",
                },
            },
            "wave5-postgres": {
                "wave5-postgres/summary.json": {
                    "gate": "wave5_postgres",
                    "status": "PASS",
                    "executed": True,
                    "rows": [{"id": "W5-PG-01", "status": "PASS"}],
                },
            },
            "wave5-real": {
                "wave5-real-browser/wave5-calendar-real-e2e.json": {
                    "evidenceClass": "real-target-runtime-api-postgresql-browser",
                    "releaseGate": True,
                    "legacyTimezoneNavigationInjected": False,
                    "rows": [{"name": "wave5-real-01", "pass": True}],
                    "failures": [],
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "fatalError": None,
                },
            },
            "nyay5": {
                "nyay5-postgres/summary.json": {
                    "gate": "nyay5_postgres",
                    "status": "PASS",
                    "executed": True,
                    "exit_code": 0,
                    "head": "0021_nyay5_profile_boundary",
                    "assertions": [{"id": "N5-PG-01", "status": "PASS"}],
                    "failed_assertions": [],
                    "assertion_summary": {
                        "exact_inventory": True,
                        "failed": [],
                        "overall_pass": True,
                        "passed": 1,
                        "required": 1,
                    },
                    "scratch_cleanup": {
                        "all_created_removed": True,
                        "cleanup_failed": 0,
                        "created": 4,
                        "inventory_match": True,
                        "removed": 4,
                    },
                    "mutant_inventory": {"named": 29, "killed": 29},
                    "privacy_scan": {"scanned": True, "findings": 0, "passed": True},
                },
                "nyay5-browser/results.json": {
                    "gate": "nyay5_profile_browser",
                    "target": "isolated-loopback-real-api-postgresql-chromium",
                    "executed": True,
                    "status": "PASS",
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "inventoryExact": True,
                    "rows": [{
                        "name": "nyay5-browser-01",
                        "pass": True,
                        "metrics": {"executed": True},
                    }],
                    "failureClass": None,
                    "failureStage": None,
                    "failureCode": None,
                },
                "nyay5-browser/orchestrator-summary.json": {
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
                },
                "nyay5-acceptance/attestations.json": {
                    "gate": "nyay5_acceptance_attestations_v1",
                    "status": "PASS",
                    "executed": True,
                    "executions": [{
                        "id": "native:frontend-unit",
                        "executed": True,
                        "skipped": False,
                        "pass": True,
                        "evidenceCount": 1,
                        "selectorCount": None,
                    }],
                },
                "nyay5-acceptance/summary.json": {
                    "gate": "nyay5_acceptance_matrix",
                    "status": "PASS",
                    "executed": True,
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "inventoryExact": True,
                    "assertions": [{
                        "id": "QA-01",
                        "passed": True,
                        "evidenceCount": 1,
                    }],
                    "executionCoverage": {
                        "pass": True,
                        "mapped": 1,
                        "missing": 0,
                        "skipped": 0,
                        "unknown": 0,
                        "unique": True,
                    },
                    "executionInventory": {
                        "count": 1,
                        "sha256": "a" * 64,
                    },
                    "producerStatus": {
                        "browser": True,
                        "postgres": True,
                        "otpPostgres": True,
                        "attestations": True,
                    },
                    "privacyScan": {"passed": True, "findings": 0},
                },
            },
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                exporter, "INVENTORY_CONTRACTS", inventory_contracts
            ),
            mock.patch.object(
                exporter,
                "CREDENTIAL_INVENTORY_CONTRACTS",
                credential_contracts,
            ),
            mock.patch.object(
                exporter,
                "NYAY5_ACCEPTANCE_EXECUTION_INVENTORY",
                (1, "a" * 64),
            ),
        ):
            root = Path(directory)
            for profile, payloads in profile_payloads.items():
                with self.subTest(profile=profile):
                    source = root / f"source-{profile}"
                    destination = root / f"out-{profile}"
                    for relative, payload in payloads.items():
                        target = source / relative
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                    included, _, failures = exporter.prepare(
                        source, destination, profile
                    )
                    self.assertEqual(failures, [])
                    self.assertEqual(included, len(payloads))
                    exported = json.loads(
                        (destination / exporter.EXPORT_NAME).read_text(encoding="utf-8")
                    )
                    self.assertEqual(exported["producerProfile"], profile)
                    self.assertTrue(
                        all(
                            row["producerState"]
                            == ("valid" if row.get("candidateType") == "fixture" else "pass")
                            for row in exported["structuredCandidates"]
                        )
                    )

            blocked = root / "source-blocked"
            blocked_payload = blocked / "wave2-db-gate" / "summary.json"
            blocked_payload.parent.mkdir(parents=True)
            blocked_payload.write_text(
                json.dumps(
                    {
                        "gate": "wave2_postgres",
                        "status": "BLOCKED",
                        "exit_code": 78,
                        "executed": False,
                        "assertions": [],
                        "failed_assertions": [],
                    }
                ) + "\n",
                encoding="utf-8",
            )
            included, _, failures = exporter.prepare(
                blocked, root / "out-blocked", "wave2"
            )
            self.assertEqual((included, failures), (1, []))
            exported = json.loads(
                (root / "out-blocked" / exporter.EXPORT_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(
                exported["structuredCandidates"][0]["producerState"], "blocked"
            )

    def test_nyay5_evidence_rejects_false_green_producer_summaries(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        contracts = {
            "nyay5-postgres": self._contract(
                exporter, "assertions", "id", ["N5-PG-01"]
            ),
            "nyay5-browser": self._contract(
                exporter, "rows", "name", ["N5-BROWSER-01"]
            ),
        }
        postgres = {
            "gate": "nyay5_postgres",
            "status": "PASS",
            "executed": True,
            "exit_code": 0,
            "head": "0021_nyay5_profile_boundary",
            "assertions": [{"id": "N5-PG-01", "status": "PASS"}],
            "failed_assertions": [],
            "assertion_summary": {
                "exact_inventory": True,
                "failed": [],
                "overall_pass": True,
                "passed": 1,
                "required": 1,
            },
            "scratch_cleanup": {
                "all_created_removed": True,
                "cleanup_failed": 0,
                "created": 4,
                "inventory_match": True,
                "removed": 4,
            },
            "mutant_inventory": {"named": 29, "killed": 29},
            "privacy_scan": {"scanned": True, "findings": 0, "passed": True},
        }
        browser = {
            "gate": "nyay5_profile_browser",
            "target": "isolated-loopback-real-api-postgresql-chromium",
            "executed": True,
            "status": "PASS",
            "total": 1,
            "passed": 1,
            "failed": 0,
            "inventoryExact": True,
            "rows": [{
                "name": "N5-BROWSER-01",
                "pass": True,
                "metrics": {"executed": True},
            }],
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
        mutants = {
            "PostgreSQL mutant survived": (
                "nyay5-postgres",
                {**postgres, "mutant_inventory": {"named": 29, "killed": 28}},
            ),
            "PostgreSQL mutant inventory shrank": (
                "nyay5-postgres",
                {**postgres, "mutant_inventory": {"named": 28, "killed": 28}},
            ),
            "PostgreSQL mutant inventory has an extra field": (
                "nyay5-postgres",
                {**postgres, "mutant_inventory": {
                    "named": 29,
                    "killed": 29,
                    "survived": 0,
                }},
            ),
            "PostgreSQL cleanup incomplete": (
                "nyay5-postgres",
                {**postgres, "scratch_cleanup": {
                    **postgres["scratch_cleanup"], "removed": 3,
                }},
            ),
            "browser assertion not executed": (
                "nyay5-browser",
                {**browser, "rows": [{
                    "name": "N5-BROWSER-01",
                    "pass": True,
                    "metrics": {"executed": False},
                }]},
            ),
            "browser failure hidden by PASS": (
                "nyay5-browser",
                {**browser, "failureCode": "RUNTIME_ASSERTION_FAILED"},
            ),
            "orchestrator service absent": (
                "nyay5-orchestrator",
                {**orchestrator, "services": {
                    **orchestrator["services"], "serviceWorkerActive": False,
                }},
            ),
            "orchestrator cleanup mismatch": (
                "nyay5-orchestrator",
                {**orchestrator, "scratchCleanup": {
                    "created": 1, "removed": 0, "inventoryMatch": False,
                }},
            ),
            "orchestrator browser failed": (
                "nyay5-orchestrator",
                {**orchestrator, "browserExitCode": 1},
            ),
            "orchestrator service logs absent": (
                "nyay5-orchestrator",
                {**orchestrator, "serviceLogsCaptured": False},
            ),
            "orchestrator extra field": (
                "nyay5-orchestrator",
                {**orchestrator, "diagnostic": "not uploadable"},
            ),
        }
        with mock.patch.object(exporter, "INVENTORY_CONTRACTS", contracts):
            for label, (kind, payload) in mutants.items():
                with self.subTest(label=label):
                    result, error = exporter._safe_result(kind, payload, {
                        "nyay5-postgres": "nyay5-postgres",
                        "nyay5-browser": "nyay5-browser",
                        "nyay5-orchestrator": "nyay5-orchestrator",
                    }[kind])
                    self.assertIsNone(result)
                    self.assertIsNotNone(error)

    def test_nyay5_acceptance_reports_reject_forged_passes(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        contracts = {
            "nyay5-acceptance-attestations": self._contract(
                exporter, "executions", "id", ["native:frontend-unit"]
            ),
            "nyay5-acceptance-matrix": self._contract(
                exporter, "assertions", "id", ["QA-01"]
            ),
        }
        attestation = {
            "gate": "nyay5_acceptance_attestations_v1",
            "status": "PASS",
            "executed": True,
            "executions": [{
                "id": "native:frontend-unit",
                "executed": True,
                "skipped": False,
                "pass": True,
                "evidenceCount": 1,
                "selectorCount": None,
            }],
        }
        aggregate = {
            "gate": "nyay5_acceptance_matrix",
            "status": "PASS",
            "executed": True,
            "total": 1,
            "passed": 1,
            "failed": 0,
            "inventoryExact": True,
            "assertions": [{"id": "QA-01", "passed": True, "evidenceCount": 1}],
            "executionCoverage": {
                "pass": True,
                "mapped": 1,
                "missing": 0,
                "skipped": 0,
                "unknown": 0,
                "unique": True,
            },
            "executionInventory": {"count": 1, "sha256": "a" * 64},
            "producerStatus": {
                "browser": True,
                "postgres": True,
                "otpPostgres": True,
                "attestations": True,
            },
            "privacyScan": {"passed": True, "findings": 0},
        }
        with (
            mock.patch.object(exporter, "INVENTORY_CONTRACTS", contracts),
            mock.patch.object(
                exporter,
                "NYAY5_ACCEPTANCE_EXECUTION_INVENTORY",
                (1, "a" * 64),
            ),
        ):
            for kind, artifact_id, payload in (
                (
                    "nyay5-acceptance-attestations",
                    "nyay5-acceptance-attestations",
                    attestation,
                ),
                (
                    "nyay5-acceptance-matrix",
                    "nyay5-acceptance-matrix",
                    aggregate,
                ),
            ):
                result, error = exporter._safe_result(kind, payload, artifact_id)
                self.assertIsNone(error)
                self.assertEqual(result["producerState"], "pass")

            mutants = {
                "skipped attestation": (
                    "nyay5-acceptance-attestations",
                    "nyay5-acceptance-attestations",
                    {**attestation, "executions": [{
                        **attestation["executions"][0], "skipped": True,
                    }]},
                ),
                "zero-evidence attestation": (
                    "nyay5-acceptance-attestations",
                    "nyay5-acceptance-attestations",
                    {**attestation, "executions": [{
                        **attestation["executions"][0], "evidenceCount": 0,
                    }]},
                ),
                "hidden aggregate assertion failure": (
                    "nyay5-acceptance-matrix",
                    "nyay5-acceptance-matrix",
                    {**aggregate, "assertions": [{
                        "id": "QA-01", "passed": False, "evidenceCount": 1,
                    }]},
                ),
                "failed producer hidden by aggregate": (
                    "nyay5-acceptance-matrix",
                    "nyay5-acceptance-matrix",
                    {**aggregate, "producerStatus": {
                        **aggregate["producerStatus"], "attestations": False,
                    }},
                ),
                "missing execution coverage hidden by aggregate": (
                    "nyay5-acceptance-matrix",
                    "nyay5-acceptance-matrix",
                    {**aggregate, "executionCoverage": {
                        **aggregate["executionCoverage"],
                        "pass": False,
                        "missing": 1,
                    }},
                ),
                "privacy finding hidden by aggregate": (
                    "nyay5-acceptance-matrix",
                    "nyay5-acceptance-matrix",
                    {**aggregate, "privacyScan": {"passed": False, "findings": 1}},
                ),
            }
            for label, (kind, artifact_id, payload) in mutants.items():
                with self.subTest(label=label):
                    result, error = exporter._safe_result(kind, payload, artifact_id)
                    self.assertIsNone(result)
                    self.assertIsNotNone(error)

    def test_require_pass_needs_sealed_full_schema_and_rejects_non_pass_states(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        manifest = load("evidence_manifest")
        contract = self._contract(exporter, "rows", "area", ["sealed-area"])
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            exporter.INVENTORY_CONTRACTS,
            {"wave1-browser": contract},
        ):
            root = Path(directory)
            source = root / "source"
            self._write_json(
                source / "results.json",
                {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "rows": [{"area": "sealed-area", "pass": True}],
                },
            )
            valid = root / "valid"
            self.assertEqual(exporter.prepare(source, valid, "wave1")[2], [])
            self.assertEqual(manifest.seal(valid)[1], [])
            self.assertEqual(exporter.validate_attestation(valid), [])
            self.assertEqual(exporter.require_pass(valid), [])
            valid_payload = json.loads(
                (valid / exporter.EXPORT_NAME).read_text(encoding="utf-8")
            )

            failed_payload = json.loads(json.dumps(valid_payload))
            failed_payload["structuredCandidates"][0].update(
                {"producerState": "fail", "failedAssertionCount": 1}
            )
            failed = root / "valid-failed-producer"
            failed.mkdir()
            self._write_json(failed / exporter.EXPORT_NAME, failed_payload)
            self.assertEqual(manifest.seal(failed)[1], [])
            self.assertEqual(exporter.validate_attestation(failed), [])
            self.assertTrue(exporter.require_pass(failed))

            encoded_private_value = base64.b64encode(
                b"person@nls.ac.in OTP 429016"
            ).decode("ascii")
            unsafe_payload = json.loads(json.dumps(valid_payload))
            unsafe_payload["diagnostic"] = encoded_private_value
            unsafe = root / "unsafe-extra-field"
            unsafe.mkdir()
            self._write_json(unsafe / exporter.EXPORT_NAME, unsafe_payload)
            self.assertEqual(manifest.seal(unsafe)[1], [])
            scanner = load("scan_evidence")
            self.assertEqual(scanner.scan(unsafe), [])
            self.assertTrue(exporter.validate_attestation(unsafe))

            unsealed = root / "unsealed"
            unsealed.mkdir()
            self._write_json(unsealed / exporter.EXPORT_NAME, valid_payload)
            self.assertTrue(exporter.require_pass(unsealed))

            tampered = root / "tampered-after-seal"
            tampered.mkdir()
            self._write_json(tampered / exporter.EXPORT_NAME, valid_payload)
            self.assertEqual(manifest.seal(tampered)[1], [])
            (tampered / exporter.EXPORT_NAME).write_text(
                json.dumps(valid_payload, indent=4) + "\n", encoding="utf-8"
            )
            self.assertTrue(exporter.require_pass(tampered))

            mutations = {
                "missing privacy marker": lambda payload: payload.pop(
                    "rawEvidenceUploaded"
                ),
                "forged privacy marker": lambda payload: payload.__setitem__(
                    "rawEvidenceUploaded", True
                ),
                "candidate count mismatch": lambda payload: payload.__setitem__(
                    "structuredCandidateCount", 2
                ),
                "boolean candidate count": lambda payload: payload.__setitem__(
                    "structuredCandidateCount", True
                ),
                "unknown profile": lambda payload: payload.__setitem__(
                    "producerProfile", "forged-profile"
                ),
                "substituted artifact id": lambda payload: payload[
                    "structuredCandidates"
                ][0].__setitem__("artifactId", "forged-artifact"),
                "substituted assertion count": lambda payload: payload[
                    "structuredCandidates"
                ][0].__setitem__("assertionCount", 2),
                "boolean failure count": lambda payload: payload[
                    "structuredCandidates"
                ][0].__setitem__("failedAssertionCount", False),
                "executable substituted as fixture": lambda payload: payload[
                    "structuredCandidates"
                ][0].update(
                    {
                        "candidateType": "fixture",
                        "producerState": "valid",
                        "executed": False,
                        "assertionCount": 0,
                    }
                ),
                "duplicate quarantine bucket": lambda payload: (
                    payload.__setitem__("quarantinedCount", 2),
                    payload.__setitem__(
                        "quarantined",
                        [
                            {
                                "mediaClass": "service-log",
                                "sizeClass": "up-to-1KiB",
                                "count": 1,
                            },
                            {
                                "mediaClass": "service-log",
                                "sizeClass": "up-to-1KiB",
                                "count": 1,
                            },
                        ],
                    ),
                ),
                "quarantine count exceeds exporter bound": lambda payload: (
                    payload.__setitem__("quarantinedCount", 5_001),
                    payload.__setitem__(
                        "quarantined",
                        [
                            {
                                "mediaClass": "service-log",
                                "sizeClass": "up-to-1KiB",
                                "count": 5_001,
                            }
                        ],
                    ),
                ),
                "extra candidate field": lambda payload: payload[
                    "structuredCandidates"
                ][0].__setitem__("rawAssertion", "forged"),
                "failed producer": lambda payload: (
                    payload["structuredCandidates"][0].__setitem__(
                        "producerState", "fail"
                    ),
                    payload["structuredCandidates"][0].__setitem__(
                        "failedAssertionCount", 1
                    ),
                ),
                "blocked producer": lambda payload: (
                    payload["structuredCandidates"][0].__setitem__(
                        "producerState", "blocked"
                    ),
                    payload["structuredCandidates"][0].__setitem__("executed", False),
                    payload["structuredCandidates"][0].__setitem__(
                        "assertionCount", 0
                    ),
                    payload["structuredCandidates"][0].__setitem__(
                        "inventoryComplete", False
                    ),
                ),
            }
            for index, (label, mutate) in enumerate(mutations.items()):
                with self.subTest(label=label):
                    payload = json.loads(json.dumps(valid_payload))
                    mutate(payload)
                    candidate = root / f"mutated-{index}"
                    candidate.mkdir()
                    self._write_json(candidate / exporter.EXPORT_NAME, payload)
                    self.assertEqual(manifest.seal(candidate)[1], [])
                    self.assertTrue(exporter.require_pass(candidate), label)

            malformed = {
                "duplicate": (
                    '{"contract":"nyayone-evidence-attestation-v1",'
                    '"structuredCandidates":[],"structuredCandidates":['
                    '{"producerState":"pass","executed":true,'
                    '"assertionCount":1,"failedAssertionCount":0,'
                    '"inventoryComplete":true}]}\n'
                ),
                "nonfinite": (
                    '{"contract":"nyayone-evidence-attestation-v1",'
                    '"metric":NaN,"structuredCandidates":['
                    '{"producerState":"pass","executed":true,'
                    '"assertionCount":1,"failedAssertionCount":0,'
                    '"inventoryComplete":true}]}\n'
                ),
            }
            for index, (label, raw) in enumerate(malformed.items()):
                with self.subTest(label=label):
                    candidate = root / f"malformed-{index}"
                    candidate.mkdir()
                    (candidate / exporter.EXPORT_NAME).write_text(
                        raw, encoding="utf-8"
                    )
                    self.assertTrue(exporter.require_pass(candidate), label)

    def test_snapshot_rejects_reserved_output_and_nested_destination(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "results.json").write_text(
                '{"status":"pass"}\n', encoding="utf-8"
            )
            self.assertTrue(exporter.prepare(source, source / "uploadable", "wave1")[2])
            (source / exporter.EXPORT_NAME).write_text(
                '{"contract":"planted"}\n', encoding="utf-8"
            )
            failures = exporter.prepare(source, root / "outside", "wave1")[2]
            self.assertTrue(any("reserved" in failure for failure in failures), failures)

    def test_snapshot_detects_same_size_atomic_replacement(self) -> None:
        exporter = load("prepare_uploadable_evidence")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "results.json"
            candidate.write_bytes(b'{"safe":true}\n')
            before = candidate.lstat()
            replacement = root / "replacement.json"
            replacement.write_bytes(b'{"safe":null}\n')
            os.utime(
                replacement,
                ns=(before.st_atime_ns, before.st_mtime_ns),
            )
            replacement.replace(candidate)
            data, error = exporter._read_stable_regular_file(
                candidate,
                before,
                limit=1024,
            )
            self.assertIsNone(data)
            self.assertIn("changed before", error or "")


if __name__ == "__main__":
    unittest.main()
