#!/usr/bin/env python3
"""NYAY-21 path-to-GO contracts for the 2026-09-04 authoritative seal.

These tests are intentionally execution-free.  They validate only immutable
planning artifacts, fail-closed validators, and rendered dry-run/trap plans.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SUBJECT = HERE / "nyay21_history_purge.py"
CONTRACT = HERE / "nyay21_history_purge_contract.json"
DOCS = ROOT / "docs" / "operations" / "nyay21-history-purge"
REF_SEAL = DOCS / "AUTHORITATIVE_REF_SEAL_20260904.json"
RULESET_PAIR = DOCS / "RULESET_PAYLOAD_PAIR_20260904.json"
REBINDING_R2 = DOCS / "EVIDENCE_REBINDING_MANIFEST_20260904.json"
BUDGET_MEMO = DOCS / "CI_BUDGET_MEMO_20260904.json"

HEAD = "454a40784ee2e084d9a756a713f287b627f1c4d4"
REF_DIGEST = "292a8bbaeba262de21c700546790e3c2b0e6c55f0174b4f5e9098b125be7edc7"
RULESET_DIGEST = "8419caa7e36d80182a46550c1af82eaf3ece2b117a4e86e93758328e426e0955"


def sha256_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_gate():
    spec = importlib.util.spec_from_file_location("nyay21_path_to_go_subject", SUBJECT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def codes(result: dict[str, object]) -> set[str]:
    return set(result.get("codes", []))


class Nyay21PathToGoContracts(unittest.TestCase):
    maxDiff = None

    def test_01_fresh_authoritative_seal_is_the_only_accepted_boundary(self) -> None:
        gate = load_gate()
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        seal = json.loads(REF_SEAL.read_text(encoding="utf-8"))

        self.assertEqual(gate.BASE_SHA, HEAD)
        self.assertEqual(contract["sourceHead"], HEAD)
        self.assertEqual(contract["reachableCommitCount"], 321)
        self.assertEqual(contract["expectedAffectedCommitCount"], 267)
        self.assertEqual(contract["expectedChangedCommitCount"], 266)
        self.assertEqual(contract["expectedPrunedCommitCount"], 1)
        self.assertEqual(contract["signedCommitCount"], 40)
        self.assertEqual(
            contract["authoritativeRefSeal"]["artifactCanonicalSha256"],
            sha256_json(seal),
        )
        self.assertEqual(contract["authoritativeRefSeal"]["refInventorySha256"], REF_DIGEST)
        self.assertEqual(seal["refCounts"]["concreteRefs"], 42)
        self.assertEqual(seal["refCounts"]["totalRowsIncludingSymbolicHead"], 43)
        self.assertEqual(
            gate.validate_authoritative_planning_seal(seal)["verdict"], "PASS"
        )

        for mutation in (
            lambda row: row.__setitem__("sourceHead", "0" * 40),
            lambda row: row.__setitem__("reachableCommitCount", 320),
            lambda row: row.__setitem__("signedCommitCount", 39),
            lambda row: row["refCounts"].__setitem__("concreteRefs", 41),
            lambda row: row.__setitem__("refInventorySha256", "0" * 64),
            lambda row: row.__setitem__("rawRemoteInventorySha256", "0" * 64),
            lambda row: row.__setitem__("mergeCommitCount", 47),
        ):
            candidate = copy.deepcopy(seal)
            mutation(candidate)
            result = gate.validate_authoritative_planning_seal(candidate)
            self.assertEqual(result["verdict"], "FAIL")
            self.assertIn("AUTHORITATIVE_PLANNING_SEAL_MISMATCH", codes(result))

    def test_02_full_ruleset_get_and_sealed_payload_pair_are_required(self) -> None:
        gate = load_gate()
        pair = json.loads(RULESET_PAIR.read_text(encoding="utf-8"))
        before = pair["canonicalGetBefore"]
        after = copy.deepcopy(before)
        result = gate.validate_ruleset_restoration(
            before,
            after,
            sealed_before_sha256=pair["canonicalGetBeforeSha256"],
            relaxation_payload=pair["relaxationPayload"],
            sealed_relaxation_sha256=pair["relaxationPayloadSha256"],
            restoration_payload=pair["restorationPayload"],
            sealed_restoration_sha256=pair["restorationPayloadSha256"],
            restoration_trap=pair["restorationTrap"],
        )
        self.assertEqual(pair["canonicalGetBeforeSha256"], RULESET_DIGEST)
        self.assertEqual(result["verdict"], "PASS")
        self.assertTrue(result["restorationTrapArmed"])

    def test_03_ruleset_tampering_and_abstracted_readbacks_fail_closed(self) -> None:
        gate = load_gate()
        pair = json.loads(RULESET_PAIR.read_text(encoding="utf-8"))

        scenarios = []
        after = copy.deepcopy(pair["canonicalGetBefore"])
        after["updated_at"] = "forged"
        scenarios.append((after, pair, "PROTECTION_NOT_RESTORED"))
        bad_pair = copy.deepcopy(pair)
        bad_pair["relaxationPayload"]["rules"] = []
        scenarios.append((pair["canonicalGetBefore"], bad_pair, "RULESET_PAYLOAD_SEAL_MISMATCH"))
        bad_trap = copy.deepcopy(pair)
        bad_trap["restorationTrap"]["exitPaths"].remove("operator-error")
        scenarios.append((pair["canonicalGetBefore"], bad_trap, "RESTORATION_TRAP_INCOMPLETE"))

        for after_value, candidate, expected in scenarios:
            result = gate.validate_ruleset_restoration(
                candidate["canonicalGetBefore"],
                after_value,
                sealed_before_sha256=candidate["canonicalGetBeforeSha256"],
                relaxation_payload=candidate["relaxationPayload"],
                sealed_relaxation_sha256=candidate["relaxationPayloadSha256"],
                restoration_payload=candidate["restorationPayload"],
                sealed_restoration_sha256=candidate["restorationPayloadSha256"],
                restoration_trap=candidate["restorationTrap"],
            )
            self.assertEqual(result["verdict"], "FAIL")
            self.assertIn(expected, codes(result))

        result = gate.validate_ruleset_restoration(
            {"requiredChecks": []}, {"requiredChecks": []}
        )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("FULL_RULESET_READBACK_REQUIRED", codes(result))

        forged = copy.deepcopy(pair)
        forged["canonicalGetBefore"]["updated_at"] = "2026-09-04T00:00:00Z"
        forged["canonicalGetBeforeSha256"] = sha256_json(
            forged["canonicalGetBefore"]
        )
        forged["restorationTrap"]["canonicalGetBeforeSha256"] = forged[
            "canonicalGetBeforeSha256"
        ]
        result = gate.validate_ruleset_restoration(
            forged["canonicalGetBefore"],
            copy.deepcopy(forged["canonicalGetBefore"]),
            sealed_before_sha256=forged["canonicalGetBeforeSha256"],
            relaxation_payload=forged["relaxationPayload"],
            sealed_relaxation_sha256=forged["relaxationPayloadSha256"],
            restoration_payload=forged["restorationPayload"],
            sealed_restoration_sha256=forged["restorationPayloadSha256"],
            restoration_trap=forged["restorationTrap"],
        )
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("RULESET_GET_AUTHORITY_MISMATCH", codes(result))

        forged_relaxation = copy.deepcopy(pair)
        forged_relaxation["relaxationPayload"]["rules"] = []
        with self.assertRaisesRegex(ValueError, "not sealed"):
            gate.render_ruleset_restoration_trap(forged_relaxation)

    def test_04_atomic_dry_run_requires_closed_42_ref_readback_and_exact_leases(self) -> None:
        gate = load_gate()
        seal = json.loads(REF_SEAL.read_text(encoding="utf-8"))
        concrete = [row for row in seal["refs"] if row["kind"] != "symbolic-head"]
        approved = [
            row["name"]
            for row in concrete
            if row["kind"] in {"branch", "protected-branch", "annotated-tag"}
        ]
        mapping = {
            name: {
                "old": next(row["target"] for row in concrete if row["name"] == name),
                "new": f"{index + 1:040x}",
            }
            for index, name in enumerate(approved)
        }
        command = gate.render_force_update_dry_run_commands(mapping, approved)[0]
        proof = {
            "command": command,
            "commandSha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
            "dryRunExitCode": 0,
            "atomicAdvertised": True,
            "remoteUpdated": False,
            "readBackRefs": concrete,
        }
        self.assertEqual(
            gate.validate_atomic_dry_run_lease_readback(
                proof, seal, mapping, approved
            )["verdict"],
            "PASS",
        )
        self.assertIn("--atomic --dry-run", command)
        self.assertEqual(command.count("--force-with-lease="), len(approved))

        request = (DOCS / "REWRITE_EXECUTION_REQUEST.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("git push --atomic production", request)
        self.assertIn("git push --atomic --dry-run production", request)

        for mutation, expected in (
            (lambda row: row["readBackRefs"].pop(), "REMOTE_REF_READBACK_NOT_CLOSED"),
            (lambda row: row.__setitem__("remoteUpdated", True), "DRY_RUN_MUTATED_REMOTE"),
            (lambda row: row.__setitem__("atomicAdvertised", False), "ATOMIC_PUSH_NOT_PROVEN"),
        ):
            candidate = copy.deepcopy(proof)
            mutation(candidate)
            result = gate.validate_atomic_dry_run_lease_readback(
                candidate, seal, mapping, approved
            )
            self.assertEqual(result["verdict"], "FAIL")
            self.assertIn(expected, codes(result))

        # Reading every remote ref is not enough: the atomic transaction itself
        # must cover the complete closed set of publishable refs.  A single-ref
        # dry run must never be accepted as proof for the 42-ref inventory.
        subset_approved = [approved[0]]
        subset_mapping = {subset_approved[0]: mapping[subset_approved[0]]}
        subset_command = gate.render_force_update_dry_run_commands(
            subset_mapping, subset_approved
        )[0]
        subset_proof = copy.deepcopy(proof)
        subset_proof["command"] = subset_command
        subset_proof["commandSha256"] = hashlib.sha256(
            subset_command.encode("utf-8")
        ).hexdigest()
        subset_result = gate.validate_atomic_dry_run_lease_readback(
            subset_proof, seal, subset_mapping, subset_approved
        )
        self.assertEqual(subset_result["verdict"], "FAIL")
        self.assertIn("DRY_RUN_REF_SCOPE_INCOMPLETE", codes(subset_result))

    def test_05_backup_and_request_encode_signed_owner_decisions(self) -> None:
        backup = (DOCS / "BACKUP_AND_ROLLBACK.md").read_text(encoding="utf-8")
        request = (DOCS / "REWRITE_EXECUTION_REQUEST.md").read_text(encoding="utf-8")
        for text in (backup, request):
            self.assertIn("force-push + 30 days", text)
            self.assertNotIn("2026-09-30T18:29:59Z", text)
            self.assertIn("legal-erasure override", text.lower())
            self.assertIn("human countersign", text.lower())
        self.assertIn("Claude Code", request)
        self.assertIn("Rajeev Barnwal", request)
        self.assertEqual(request.count("--preserve-commit-hashes"), 1)
        self.assertEqual(request.count("--replace-refs delete-no-add"), 1)

    def test_06_gpg_inventory_canary_and_attestation_template_are_complete(self) -> None:
        text = (DOCS / "GPG_SIGNATURE_DISPOSITION.md").read_text(encoding="utf-8")
        self.assertIn("40", text)
        self.assertIn("signer identity", text.lower())
        self.assertIn("verification status", text.lower())
        self.assertIn("canary", text.lower())
        self.assertIn("attestation template", text.lower())
        self.assertIn("signing forward", text.lower())

    def test_07_rebinding_revision_is_new_immutable_and_exact_head_bound(self) -> None:
        old_path = DOCS / "EVIDENCE_REBINDING_MANIFEST.json"
        old = json.loads(old_path.read_text(encoding="utf-8"))
        new = json.loads(REBINDING_R2.read_text(encoding="utf-8"))
        self.assertEqual(old["planningHead"], "422b3dbbeddb25c6735cd093003ccaef335cb60a")
        self.assertEqual(new["planningHead"], HEAD)
        self.assertEqual(new["supersedesImmutableTemplate"], old_path.name)
        self.assertFalse(new["originRewrite"]["executed"])
        self.assertEqual(new["rewriteIdentityBoundary"]["reachableCommitCountBefore"], 321)
        self.assertEqual(new["rewriteIdentityBoundary"]["expectedChangedOrPrunedCommitCount"], 267)
        self.assertEqual(new["rewriteIdentityBoundary"]["gpgSignedCommitCountBefore"], 40)

    def test_08_budget_and_residual_register_remain_no_go_until_read_back(self) -> None:
        memo = json.loads(BUDGET_MEMO.read_text(encoding="utf-8"))
        residual = (DOCS / "HOST_RESIDUAL_SURFACES.md").read_text(encoding="utf-8")
        self.assertEqual(memo["reservationMinutes"], 250)
        self.assertEqual(memo["headroom"]["status"], "PENDING_OWNER_D5_READ")
        self.assertEqual(memo["quarantinedNyay4"]["dispatch"], "manual")
        self.assertIn("per-surface execution disposition", residual.lower())
        for disposition in (
            "PURGED_AND_READ_BACK",
            "EXPIRED_AND_READ_BACK",
            "RETAINED_RESTRICTED_UNTIL_<DATE>",
            "NOT_APPLICABLE_WITH_EVIDENCE",
            "BLOCKED",
        ):
            self.assertIn(disposition, residual)

    def test_09_restoration_trap_is_rendered_and_proven_on_every_exit_path(self) -> None:
        gate = load_gate()
        pair = json.loads(RULESET_PAIR.read_text(encoding="utf-8"))
        rendered = gate.render_ruleset_restoration_trap(pair)
        self.assertIn(
            "trap restore_ruleset_from_sealed_payload EXIT HUP INT TERM", rendered
        )
        self.assertIn(pair["restorationPayloadSha256"], rendered)
        self.assertIn(pair["canonicalGetBeforeSha256"], rendered)
        self.assertNotIn("--admin", rendered)
        events = [
            {
                "path": path,
                "restoreAttempted": True,
                "independentGetPerformed": True,
                "canonicalGetSha256": pair["canonicalGetBeforeSha256"],
            }
            for path in ("success", "push-rejected", "signal", "operator-error")
        ]
        self.assertEqual(
            gate.validate_ruleset_restoration_trap_events(
                events, pair["canonicalGetBeforeSha256"]
            )["verdict"],
            "PASS",
        )
        for index in range(len(events)):
            result = gate.validate_ruleset_restoration_trap_events(
                events[:index] + events[index + 1 :],
                pair["canonicalGetBeforeSha256"],
            )
            self.assertEqual(result["verdict"], "FAIL")
            self.assertIn("RESTORATION_EXIT_PATH_UNPROVEN", codes(result))

        forged_digest = "0" * 64
        forged_events = [
            {
                **row,
                "canonicalGetSha256": forged_digest,
            }
            for row in events
        ]
        forged_result = gate.validate_ruleset_restoration_trap_events(
            forged_events, forged_digest
        )
        self.assertEqual(forged_result["verdict"], "FAIL")
        self.assertIn("RULESET_GET_AUTHORITY_MISMATCH", codes(forged_result))


if __name__ == "__main__":
    unittest.main()
