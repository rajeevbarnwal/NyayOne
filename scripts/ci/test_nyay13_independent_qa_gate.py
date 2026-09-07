"""NYAY-13 executable RED specification; implementation is separately authorized.

All identities are synthetic. Trust/read-back inputs model privileged adapters,
never fields accepted from the submitted evidence package. No network mutation.
"""
import copy
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUBJECT = HERE / "nyay13_independent_qa_gate.py"
HEAD, BASE, MERGE = "1" * 40, "2" * 40, "3" * 40
DIGEST = "4" * 64


def fixture():
    """A complete synthetic envelope plus independently acquired trusted facts."""
    evidence = {
        "repository": "rajeevbarnwal/NyayOne", "base": BASE,
        "reviewedHead": HEAD, "prospectiveMerge": MERGE,
        "reviewer": "independent-qa", "implementer": "implementation-agent",
        "runId": "synthetic-independent-run", "verdict": "PASS",
        "manifestSha256": DIGEST, "contactSheetSha256": DIGEST,
        "limitations": [], "rawCategories": ["backend", "postgresql-migration",
            "postgresql-concurrency", "frontend-native", "chromium"],
        "assertions": {"expected": 1467, "executed": 1467, "passed": 1467,
            "failed": 0, "missing": 0, "skipped": 0, "selectors": 1},
        "inventory": ["raw.log", "contact.png", "contact.txt"],
        "failureDigestCoverage": {"contract": "nyay40", "seededFailureExecuted": True,
            "privacyScanned": True, "manifested": True, "uploadedReadBack": True},
    }
    facts = {
        "repository": evidence["repository"], "base": BASE, "remoteHead": HEAD,
        "prospectiveMerge": MERGE, "visibility": "PRIVATE", "acquisitionTrusted": True,
        "trust": {"reviewer": "independent-qa", "implementer": "implementation-agent",
            "issuer": "trusted-independent-publisher", "signatureVerified": True,
            "signedPayloadMatches": True, "revoked": False, "expired": False,
            "separateExecutionIdentity": True, "implementationCanWriteTrust": False},
        "artifactReadBack": {"manifestSha256": DIGEST, "sheetSha256": DIGEST,
            "inventory": evidence["inventory"][:], "hashesVerified": True,
            "privacyPassed": True, "archiveClean": True, "rawMetricsVerified": True,
            "contactSidecarVerified": True, "nonzeroAttachments": True},
        "checkReadBack": {"exactHead": HEAD, "allRequiredSuccess": True,
            "urlsVerified": True, "publisherTrusted": True, "uniqueContext": True},
        "reviewState": {"unresolved": 0, "requests": 0, "changesRequested": 0,
            "paginationComplete": True},
    }
    return evidence, facts


class IndependentQARedContracts(unittest.TestCase):
    def subject(self):
        self.assertTrue(SUBJECT.is_file(), "NYAY13_GATE_ABSENT: independent trust gate is not implemented")
        spec = importlib.util.spec_from_file_location("nyay13_independent_qa_gate", SUBJECT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_valid_independently_authenticated_exact_head(self):
        result = self.subject().validate_review(*fixture())
        self.assertEqual(result["classification"], "PASS")
        self.assertIs(result["mergeAuthorized"], True)

    def test_pr_template_has_exact_head_evidence_and_risks(self):
        result = self.subject().render_pr_comment(*fixture())
        for value in (HEAD, BASE, DIGEST, "Limitations", "PASS"):
            self.assertIn(value, result)

    def test_guarded_rail_binds_fresh_head_and_closed_review_state(self):
        gate = self.subject()
        evidence, facts = fixture()
        command = gate.render_merge_command(evidence, facts)
        self.assertIn("--merge", command)
        self.assertIn("--match-head-commit " + HEAD, command)
        self.assertNotIn("--admin", command)
        self.assertNotIn("--auto", command)
        facts["remoteHead"] = "9" * 40
        self.assertIsNone(gate.render_merge_command(evidence, facts))

    def test_sole_owner_never_enabled_as_own_independent_approver(self):
        result = self.subject().approval_policy({"trustedSeparateReviewerAvailable": False})
        self.assertEqual(result["requiredApprovals"], 0)
        self.assertIs(result["requireLastPushApproval"], False)
        self.assertIs(result["independentEvidenceRequired"], True)
        self.assertIs(result["bypassAllowed"], False)

    def test_post_merge_closure_requires_exact_merge_and_main_push_readbacks(self):
        gate = self.subject()
        readback = {"merge": MERGE, "reviewedHead": HEAD, "headIsAncestor": True,
            "mergeIsAncestor": True, "mainPushHead": MERGE, "allMainGatesSuccess": True,
            "runUrlsVerified": True, "checkUrlsVerified": True}
        self.assertEqual(gate.validate_closure(HEAD, MERGE, readback)["classification"], "PASS")
        for field in ("headIsAncestor", "mergeIsAncestor", "allMainGatesSuccess", "runUrlsVerified", "checkUrlsVerified"):
            with self.subTest(field=field):
                mutated = dict(readback, **{field: False})
                self.assertIs(gate.validate_closure(HEAD, MERGE, mutated)["closureAuthorized"], False)
        readback["mainPushHead"] = BASE
        self.assertIs(gate.validate_closure(HEAD, MERGE, readback)["closureAuthorized"], False)


NEGATIVES = {
    "self_certification": ("e", "reviewer", "implementation-agent"),
    "shared_execution_identity": ("f", "trust.separateExecutionIdentity", False),
    "implementer_can_edit_trust": ("f", "trust.implementationCanWriteTrust", True),
    "unsigned_attestation": ("f", "trust.signatureVerified", False),
    "substituted_signed_payload": ("f", "trust.signedPayloadMatches", False),
    "untrusted_issuer": ("f", "trust.issuer", "untrusted"),
    "revoked_reviewer": ("f", "trust.revoked", True),
    "expired_trust": ("f", "trust.expired", True),
    "self_reported_readbacks": ("f", "acquisitionTrusted", False),
    "head_changed": ("f", "remoteHead", "9" * 40),
    "base_changed": ("f", "base", "9" * 40),
    "foreign_repository": ("e", "repository", "foreign/repository"),
    "prospective_merge_changed": ("f", "prospectiveMerge", "9" * 40),
    "missing_raw_logs": ("e", "rawCategories", []),
    "zero_assertions": ("e", "assertions.executed", 0),
    "boolean_counts": ("e", "assertions.executed", True),
    "skipped_assertions": ("e", "assertions.skipped", 1),
    "missing_assertions": ("e", "assertions.missing", 1),
    "failed_assertions": ("e", "assertions.failed", 1),
    "zero_selectors": ("e", "assertions.selectors", 0),
    "metric_not_raw_bound": ("f", "artifactReadBack.rawMetricsVerified", False),
    "missing_inventory_item": ("f", "artifactReadBack.inventory", ["raw.log"]),
    "bad_manifest_hash": ("f", "artifactReadBack.manifestSha256", "9" * 64),
    "artifact_hash_mismatch": ("f", "artifactReadBack.hashesVerified", False),
    "privacy_failure": ("f", "artifactReadBack.privacyPassed", False),
    "dirty_archive": ("f", "artifactReadBack.archiveClean", False),
    "missing_contact_sheet": ("e", "contactSheetSha256", ""),
    "invalid_contact_sidecar": ("f", "artifactReadBack.contactSidecarVerified", False),
    "empty_attachment": ("f", "artifactReadBack.nonzeroAttachments", False),
    "stale_check_head": ("f", "checkReadBack.exactHead", BASE),
    "failed_required_check": ("f", "checkReadBack.allRequiredSuccess", False),
    "forged_check_url": ("f", "checkReadBack.urlsVerified", False),
    "untrusted_check_publisher": ("f", "checkReadBack.publisherTrusted", False),
    "duplicate_qa_context": ("f", "checkReadBack.uniqueContext", False),
    "unresolved_thread": ("f", "reviewState.unresolved", 1),
    "pending_review_request": ("f", "reviewState.requests", 1),
    "changes_requested": ("f", "reviewState.changesRequested", 1),
    "incomplete_review_pagination": ("f", "reviewState.paginationComplete", False),
    "missing_failure_digest_exercise": ("e", "failureDigestCoverage.seededFailureExecuted", False),
    "unscanned_failure_digest": ("e", "failureDigestCoverage.privacyScanned", False),
    "unsealed_failure_digest": ("e", "failureDigestCoverage.manifested", False),
    "unpublished_failure_digest": ("e", "failureDigestCoverage.uploadedReadBack", False),
}


def negative_contract(name, mutation):
    def test(self):
        gate = self.subject()
        evidence, facts = fixture()
        side, path, value = mutation
        node = evidence if side == "e" else facts
        segments = path.split(".")
        for segment in segments[:-1]:
            node = node[segment]
        node[segments[-1]] = copy.deepcopy(value)
        result = gate.validate_review(evidence, facts)
        self.assertIn(result["classification"], ("FAIL", "BLOCKED", "HEAD_CHANGED"))
        self.assertIs(result["mergeAuthorized"], False)
        self.assertTrue(result["codes"], "failure must identify a canonical reason")
        if name == "head_changed":
            self.assertEqual(result["classification"], "HEAD_CHANGED")
    return test


for _name, _mutation in NEGATIVES.items():
    setattr(IndependentQARedContracts, "test_reject_" + _name, negative_contract(_name, _mutation))


if __name__ == "__main__":
    unittest.main()
