"""Real-signature and malformed-input adversarial coverage for observe-only QA."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import nyay13_independent_qa_gate as gate
from test_nyay13_independent_qa_gate import fixture, HEAD


class TrustBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="nyay13-synthetic-signer-")
        cls.root = Path(cls.tmp.name)
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                        "-out", str(cls.root / "private.pem")], capture_output=True, check=True)
        cls.key = subprocess.run(["openssl", "pkey", "-in", str(cls.root / "private.pem"), "-pubout"],
                                 capture_output=True, check=True).stdout

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def inputs(self):
        evidence, facts = fixture()
        envelope = dict(evidence=evidence, facts=facts, issuedAt=100, expiresAt=200)
        policy = dict(publicKeySha256=hashlib.sha256(self.key).hexdigest(), revoked=False,
                      issuer=gate.ISSUER, reviewer="independent-qa", implementer="implementation-agent")
        return envelope, policy

    def sign(self, envelope):
        return subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(self.root / "private.pem")],
                              input=gate.canonical(envelope), capture_output=True, check=True).stdout

    def test_real_signature_valid_but_never_merge_authority(self):
        e, p = self.inputs()
        result = gate.observe_signed_review(e, self.sign(e), self.key, p, HEAD, now=150)
        self.assertEqual(result["policyVerdict"], "PASS")
        self.assertIs(result["mergeAuthorized"], False)
        self.assertEqual(result["mode"], "observe-only")

    def test_forged_signature_rejected(self):
        e, p = self.inputs()
        result = gate.observe_signed_review(e, b"not-a-signature", self.key, p, HEAD, now=150)
        self.assertEqual(result["classification"], "BLOCKED")
        self.assertIs(result["mergeAuthorized"], False)

    def test_payload_substitution_rejected(self):
        e, p = self.inputs()
        signature = self.sign(e)
        e["evidence"]["limitations"] = ["altered"]
        self.assertEqual(gate.observe_signed_review(e, signature, self.key, p, HEAD, now=150)["classification"], "BLOCKED")

    def test_unpinned_key_and_revoked_policy_rejected(self):
        e, p = self.inputs()
        for key, value in (("publicKeySha256", "0" * 64), ("revoked", True),
                           ("reviewer", "implementation-agent"), ("issuer", "foreign")):
            with self.subTest(key=key):
                mutated = dict(p, **{key: value})
                self.assertEqual(gate.observe_signed_review(e, self.sign(e), self.key, mutated, HEAD, now=150)["classification"], "BLOCKED")

    def test_receipt_expiry_future_and_boolean_time_rejected(self):
        e, p = self.inputs()
        for now in (99, 200, 201):
            self.assertEqual(gate.observe_signed_review(e, self.sign(e), self.key, p, HEAD, now=now)["classification"], "BLOCKED")
        e["issuedAt"] = True
        self.assertEqual(gate.observe_signed_review(e, self.sign(e), self.key, p, HEAD, now=150)["classification"], "BLOCKED")

    def test_live_head_invalidates_genuine_receipt(self):
        e, p = self.inputs()
        result = gate.observe_signed_review(e, self.sign(e), self.key, p, "9" * 40, now=150)
        self.assertEqual(result["classification"], "HEAD_CHANGED")
        self.assertIs(result["mergeAuthorized"], False)

    def test_signed_failure_cannot_be_pass(self):
        e, p = self.inputs()
        e["evidence"]["assertions"]["failed"] = 1
        result = gate.observe_signed_review(e, self.sign(e), self.key, p, HEAD, now=150)
        self.assertEqual(result["classification"], "FAIL")
        self.assertIs(result["mergeAuthorized"], False)

    def test_signed_malformed_fact_container_is_canonical_refusal(self):
        for invalid in ([], None, "private@example.test", 7):
            with self.subTest(kind=type(invalid).__name__):
                e, p = self.inputs()
                e["facts"] = invalid
                result = gate.observe_signed_review(e, self.sign(e), self.key, p, HEAD, now=150)
                self.assertEqual(result["classification"], "BLOCKED")
                self.assertIs(result["mergeAuthorized"], False)
                self.assertNotIn("private@", json.dumps(result))

    def test_malformed_core_inputs_are_privacy_safe(self):
        e, f = fixture()
        for invalid in (None, [], "private@example.test", True, 7):
            for result in (gate.validate_review(invalid, f), gate.validate_review(e, invalid)):
                self.assertIs(result["mergeAuthorized"], False)
                self.assertNotIn("private@", json.dumps(result))
        for field in ("trust", "artifactReadBack", "checkReadBack", "reviewState"):
            mutated = copy.deepcopy(f)
            mutated[field] = None
            self.assertIs(gate.validate_review(e, mutated)["mergeAuthorized"], False)

    def test_boolean_review_counts_and_duplicate_inventory_rejected(self):
        e, f = fixture()
        f["reviewState"]["unresolved"] = False
        self.assertIs(gate.validate_review(e, f)["mergeAuthorized"], False)
        e, f = fixture()
        e["inventory"].append("raw.log")
        self.assertIs(gate.validate_review(e, f)["mergeAuthorized"], False)

    def test_json_duplicate_keys_rejected(self):
        path = self.root / "duplicate.json"
        path.write_text('{"verdict":"FAIL","verdict":"PASS"}')
        with self.assertRaisesRegex(ValueError, "DUPLICATE_FIELD"):
            gate._read_json(path)

    def test_observer_workflow_step_cannot_become_a_new_required_context(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / ".github/workflows/nyay13-independent-qa-observe.yml").read_text()
        self.assertNotIn("continue-on-error", text)
        self.assertNotIn("  required:", text)
        self.assertIn("test_nyay13_independent_qa_gate.py", text)
        self.assertIn("test_nyay13_trust_boundary.py", text)
        policy = (root / ".github/workflows/nyayone-policy-gate.yml").read_text()
        self.assertIn("needs: [policy-contracts]", policy)
        self.assertNotIn("independent-qa-observe", policy)

    def test_pr_template_requires_exact_head_evidence_and_known_risks(self):
        template = (Path(__file__).resolve().parents[2] / ".github/pull_request_template.md").read_text()
        for field in ("Reviewed head", "Base SHA", "Prospective merge", "Manifest SHA-256",
                      "Contact sheet", "Required check URLs", "Known risks", "Independent reviewer"):
            self.assertIn(field, template)

    def test_observation_workflow_mutations_are_rejected_not_allowlisted(self):
        import verify_nyayone_ci as verifier
        path = Path(__file__).resolve().parents[2] / ".github/workflows/nyay13-independent-qa-observe.yml"
        source = path.read_text()
        self.assertEqual(verifier.check_workflow(path), [])
        candidate = self.root / path.name
        for old, new in (("contents: read", "contents: write"),
                         ("timeout-minutes: 5", "timeout-minutes: 5\n    continue-on-error: true"),
                         ("test_nyay13_independent_qa_gate.py", "missing.py"),
                         ("branches: [main]", "branches: [foreign]")):
            candidate.write_text(source.replace(old, new))
            self.assertTrue(verifier.check_workflow(candidate))


if __name__ == "__main__":
    unittest.main()
