"""Fail-closed, privacy-safe diagnostic export contracts for NYAY-40."""
import hashlib
import json
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from test_evidence_policy import load


class FailureDigestContracts(unittest.TestCase):
    def test_document_departure_waits_for_font_settlement_and_fails_closed(self):
        root = Path(__file__).resolve().parents[2]
        script = r"""
import assert from 'node:assert/strict';
import {leaveSettledDocument} from './frontend/scripts/lib/wave1-document-settlement.mjs';
let release;
const font = new Promise(r=>{release=r;});
const events=[];
const page={evaluate:async callback=>{
  globalThis.document={body:{getBoundingClientRect:()=>events.push('layout')},fonts:{ready:font}};
  globalThis.requestAnimationFrame=callback=>queueMicrotask(callback);
  return callback();
}};
const leaving=leaveSettledDocument(page,async()=>events.push('depart'));
await new Promise(r=>setImmediate(r));
assert.equal(events.includes('depart'),false);
release(); await leaving;
assert.equal(events.at(-1),'depart');
let departed=false;
await assert.rejects(leaveSettledDocument({evaluate:async()=>{throw Error('private-url');}},()=>{departed=true;}),
  e=>e.message==='WAVE1_DOCUMENT_SETTLEMENT_FAILED' && !JSON.stringify(e).includes('private-url'));
assert.equal(departed,false);
console.log('settlement-order-and-fail-closed PASS');
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_functional_departures_are_guarded_without_ignoring_runtime_errors(self):
        root = Path(__file__).resolve().parents[2]
        source = (root / "frontend/scripts/v34-s11-s26-e2e.mjs").read_text()
        functional = source[source.index("  const functionalRuntime = createRuntimeEvidence();"):]
        departures = [line.strip() for line in functional.splitlines()
                      if "page.goto(" in line or "page.close()" in line]
        self.assertEqual(len(departures), 11)
        self.assertTrue(all(line.startswith("await leaveSettledDocument(page,") for line in departures))
        self.assertIn("functionalRuntime.failedRequests.length === 0", functional)

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

    def runtime_fixture(self):
        root = Path(__file__).resolve().parents[2]
        script = r"""
import {createRuntimeEvidence, attachRuntimeEvidence, runtimeEvent} from './frontend/scripts/lib/wave1-runtime-diagnostics.mjs';
const handlers = {};
const page = {on:(event, handler)=>{handlers[event]=handler;}, url:()=> 'http://localhost:4177/s-18?person=private@example.test'};
const runtime = createRuntimeEvidence();
attachRuntimeEvidence(page, runtime);
const request = {url:()=> 'http://localhost:1131/api/v1/student/privacy/requests/private-identifier?secret=private', method:()=> 'GET', failure:()=>({errorText:'net::ERR_ABORTED'})};
handlers.console({type:()=> 'error', location:()=>({url:'http://localhost:4177/assets/private-build.js?token=private'}), text:()=>{throw Error('must not read message');}});
handlers.pageerror(new Error('private message body'));
handlers.requestfailed(request);
handlers.response({status:()=>404, request:()=>request, url:request.url});
runtime.unmatchedApi.push(runtimeEvent('unmatched-api', request.url(), request.method()));
console.log(JSON.stringify(runtime));
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script], cwd=root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_seeded_runtime_categories_are_collected_without_private_content(self):
        runtime = self.runtime_fixture()
        self.assertEqual(set(runtime), {"consoleErrors", "pageErrors", "failedRequests", "httpErrors", "unmatchedApi"})
        self.assertTrue(all(len(items) == 1 for items in runtime.values()))
        self.assertEqual(runtime["httpErrors"][0]["routeTemplate"], "/api/v1/student/privacy/requests/{request_id}")
        self.assertEqual(runtime["consoleErrors"][0]["routeTemplate"], "/assets/{asset}")
        self.assertEqual(runtime["failedRequests"][0]["reason"], "net::ERR_ABORTED")
        self.assertNotIn("private", json.dumps(runtime))
        self.assertNotIn("?", json.dumps(runtime))

    def test_failed_runtime_export_contains_strict_counted_hmac_bound_categories(self):
        self.ids = ["functional_runtime"]
        rows = [{"area": "functional_runtime", "expected": "zero runtime errors", "actual": self.runtime_fixture(), "pass": False}]
        result, target = self.export(rows)
        self.assertEqual(result[2], [])
        item = json.loads((target / self.exporter.EXPORT_NAME).read_text())["failureDigests"]["rows"][0]
        self.assertEqual({r["category"] for r in item["runtimeCategories"]}, {"console", "page", "request-failed", "HTTP", "unmatched-API"})
        self.assertTrue(all(r["count"] == 1 for r in item["runtimeCategories"]))
        self.assertRegex(item["runtimeHash"], r"^[0-9a-f]{64}$")
        self.assertEqual(load("scan_evidence").scan(target), [])
        self.assertTrue(self.exporter._runtime_categories_valid(item["runtimeCategories"]))
        for invalid in (True, -1, "1"):
            with self.subTest(count=invalid):
                mutated = json.loads(json.dumps(item["runtimeCategories"]))
                mutated[0]["count"] = invalid
                self.assertFalse(self.exporter._runtime_categories_valid(mutated))
        mutated = json.loads(json.dumps(item["runtimeCategories"]))
        mutated[0]["routes"][0]["routeTemplate"] = "/assets/private.js?credential=private"
        self.assertFalse(self.exporter._runtime_categories_valid(mutated))
        _, second = self.export(rows)
        other = json.loads((second / self.exporter.EXPORT_NAME).read_text())["failureDigests"]["rows"][0]
        self.assertNotEqual(item["runtimeHash"], other["runtimeHash"])

    def test_untrusted_runtime_metadata_cannot_enter_diagnostic_export(self):
        self.ids = ["functional_runtime"]
        for invalid in ({"routeTemplate": "/s-18?private@example.test"}, {"count": True}, {"body": "private"}):
            with self.subTest(invalid=invalid):
                runtime = self.runtime_fixture()
                runtime["httpErrors"][0].update(invalid)
                result, target = self.export([{"area": "functional_runtime", "expected": 0, "actual": runtime, "pass": False}])
                self.assertTrue(result[2])
                self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
