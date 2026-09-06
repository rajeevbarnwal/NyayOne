"""Fail-closed, privacy-safe diagnostic export contracts for NYAY-40."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_evidence_policy import load


class FailureDigestContracts(unittest.TestCase):
    def setUp(self):
        self.exporter = load("prepare_uploadable_evidence")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.ids = ["S-11/desktop/layout", "S-12/mobile/heading"]
        self.rows = [dict(area=value, expected="approved", actual="approved", **{"pass": True}) for value in self.ids]
        self.rows[0].update(actual="private user@example.test narrative", **{"pass": False})

    def export(self, rows=None):
        rows = self.rows if rows is None else rows
        payload = dict(total=len(rows), passed=sum(r["pass"] for r in rows),
                       failed=sum(not r["pass"] for r in rows), rows=rows)
        (self.source / "results.json").write_text(json.dumps(payload))
        target = self.root / ("export-" + str(len(list(self.root.iterdir()))))
        contract = ("rows", "area", len(self.ids), self.exporter._identity_digest(self.ids))
        with mock.patch.dict(self.exporter.INVENTORY_CONTRACTS, {"wave1-browser": contract}):
            result = self.exporter.prepare(self.source, target, "wave1")
        return result, target

    def test_failed_row_is_uploaded_with_screen_and_comparison_digests(self):
        result, target = self.export()
        self.assertEqual(result[2], [])
        data = json.loads((target / self.exporter.EXPORT_NAME).read_text())
        self.assertIn("failureDigests", data)
        rows = data["failureDigests"]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["assertionId"], self.ids[0])
        self.assertEqual(rows[0]["screenId"], "S-11")
        for key in ("expectedHash", "actualHash"):
            self.assertRegex(rows[0][key], r"^[0-9a-f]{64}$")
        self.assertNotEqual(rows[0]["expectedHash"], rows[0]["actualHash"])

    def test_private_values_are_neither_uploaded_nor_dictionary_hashable(self):
        _, target = self.export()
        data = (target / self.exporter.EXPORT_NAME).read_text()
        self.assertIn("failureDigests", json.loads(data))
        self.assertNotIn(self.rows[0]["actual"], data)
        self.assertNotIn(hashlib.sha256(self.rows[0]["actual"].encode()).hexdigest(), data)
        self.assertEqual(load("scan_evidence").scan(target), [])

    def test_digest_key_is_discarded_and_not_reused_between_exports(self):
        _, first = self.export()
        _, second = self.export()
        a = json.loads((first / self.exporter.EXPORT_NAME).read_text())["failureDigests"]
        b = json.loads((second / self.exporter.EXPORT_NAME).read_text())["failureDigests"]
        self.assertNotEqual(a["rows"][0]["actualHash"], b["rows"][0]["actualHash"])
        self.assertEqual(set(a), {"contract", "hashScheme", "rows"})

    def test_substituted_failure_identity_fails_before_export(self):
        self.rows[0]["area"] = "S-11/user@example.test"
        result, target = self.export()
        self.assertTrue(result[2])
        self.assertFalse(target.exists())

    def test_missing_comparison_field_fails_before_export(self):
        del self.rows[0]["expected"]
        result, target = self.export()
        self.assertTrue(result[2])
        self.assertFalse(target.exists())

    def test_sealed_failure_export_is_valid_but_never_a_passing_producer(self):
        contract = ("rows", "area", len(self.ids), self.exporter._identity_digest(self.ids))
        patcher = mock.patch.dict(self.exporter.INVENTORY_CONTRACTS, {"wave1-browser": contract})
        patcher.start()
        self.addCleanup(patcher.stop)
        _, target = self.export()
        data = json.loads((target / self.exporter.EXPORT_NAME).read_text())
        self.assertIn("failureDigests", data)
        body = (target / self.exporter.EXPORT_NAME).read_bytes()
        (target / "SHA256SUMS.txt").write_text(hashlib.sha256(body).hexdigest() + "  EVIDENCE_EXPORT.json\n")
        self.assertEqual(self.exporter._validate_attestation(target, require_all_pass=False), [])
        self.assertTrue(self.exporter._validate_attestation(target, require_all_pass=True))
        data["failureDigests"]["rows"][0]["actualHash"] = "private content"
        body = json.dumps(data).encode()
        (target / self.exporter.EXPORT_NAME).write_bytes(body)
        (target / "SHA256SUMS.txt").write_text(hashlib.sha256(body).hexdigest() + "  EVIDENCE_EXPORT.json\n")
        self.assertTrue(self.exporter._validate_attestation(target, require_all_pass=False))

    def test_existing_wave1_failure_upload_is_privacy_and_seal_gated(self):
        import verify_nyayone_ci as verifier
        root = Path(__file__).resolve().parents[2]
        workflow = root / ".github/workflows/wave1-foundation-gate.yml"
        self.assertEqual(verifier.check_workflow(workflow), [])
        text = workflow.read_text()
        self.assertIn("--profile wave1", text)
        self.assertIn("evidence_privacy.outcome == 'success'", text)
        self.assertIn("evidence_integrity.outcome == 'success'", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
