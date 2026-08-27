#!/usr/bin/env python3
"""NYAY-21 contracts for the SQLite WAL/SHM history purge.

The first 24 tests preserve the original RED baseline; the remaining tests
encode the Independent Senior Tester's fail-open bypass matrix.  Every test
loads the subject lazily and the suite must never rewrite this checkout, update
a remote, or change repository visibility.  All rewrite integration work is
confined to disposable synthetic repositories and requires separately sealed
authorizations.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType


HERE = Path(__file__).resolve().parent
SUBJECT = HERE / "nyay21_history_purge.py"
CONTRACT = HERE / "nyay21_history_purge_contract.json"

SCHEMA_VERSION = "nyay21-history-purge/v1"
REPOSITORY = "rajeevbarnwal/NyayOne"
BASE_SHA = "422b3dbbeddb25c6735cd093003ccaef335cb60a"
SOURCE_COMMIT = "9d6d56cc84b4f3fe9e2b223631f8a5e96c815374"
DELETION_COMMIT = "d58d1fbac48db5a29158ca5b3b168b8951d526d1"
NULL_SHA = "0" * 40
TARGETS = (
    {
        "path": "backend/legalsaathi_dev.db-shm",
        "blob": "c3d899c19aa30ca15b2d3c952c0f98f96c6e5337",
        "size": 32768,
    },
    {
        "path": "backend/legalsaathi_dev.db-wal",
        "blob": "9b2634ba5293ee2ceb0a28c19a448e9714c0799e",
        "size": 457352,
    },
)
KNOWN_INVALIDATED_SHAS = (
    SOURCE_COMMIT,
    "928a2f5f7d51341b3c01c24c423e5f1742d50e5f",
    "140906ba986a1567d9fee34e4aacb2776dff79e9",
    "3678eba9cb54df09005dcd2d7453954336cb1305",
    BASE_SHA,
)
STRICT_REQUIRED_CHECKS = (
    "nyayone-registration-required",
    "nyayone-wave1-required",
    "nyayone-wave2-required",
    "nyayone-wave3-required",
    "nyayone-wave4-required",
    "nyayone-wave5-required",
    "nyayone-policy-required",
)
APPROVAL_REGISTRY_SCHEMA = "nyay21-approval-consumption/v1"
OWNER_APPROVER = "Rajeev Barnwal"
SECURITY_PRIVACY_APPROVER = "Named Security/Privacy Approver"
REWRITE_APPROVAL_ID = (
    "NYAY21-REWRITE-11111111-1111-4111-8111-111111111111"
)
FORCE_APPROVAL_ID = "NYAY21-FORCE-22222222-2222-4222-8222-222222222222"


def load_subject(test_case: unittest.TestCase, contract_id: str) -> ModuleType:
    test_case.assertTrue(
        SUBJECT.is_file(),
        f"{contract_id}: RED — scripts/ci/nyay21_history_purge.py is not implemented",
    )
    spec = importlib.util.spec_from_file_location("nyay21_history_purge", SUBJECT)
    test_case.assertIsNotNone(spec, f"{contract_id}: subject import spec unavailable")
    test_case.assertIsNotNone(spec.loader, f"{contract_id}: subject loader unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    test_case.assertEqual(
        getattr(module, "SCHEMA_VERSION", None),
        SCHEMA_VERSION,
        f"{contract_id}: the exact versioned contract must be published",
    )
    return module


def finding_codes(result: object) -> set[str]:
    if isinstance(result, dict):
        findings = result.get("codes", result.get("findings", []))
    else:
        findings = result
    return {
        value if isinstance(value, str) else value.get("code")
        for value in findings
        if isinstance(value, (str, dict))
    }


def full_sha(seed: int) -> str:
    return f"{seed:040x}"


def canonical_json_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_approval_registry(
    consumed: tuple[str, ...] = (),
) -> dict[str, object]:
    payload = {
        "schemaVersion": APPROVAL_REGISTRY_SCHEMA,
        "consumedApprovalIds": list(consumed),
    }
    return {**payload, "registrySha256": canonical_json_sha256(payload)}


def canonical_remote_refs() -> list[dict[str, object]]:
    """Representative sealed authority: 12 heads, 11 pull refs, one tag + HEAD."""
    rows: list[dict[str, object]] = [
        {
            "name": "HEAD",
            "kind": "symbolic-head",
            "target": BASE_SHA,
            "symbolicTarget": "refs/heads/main",
            "targetReachable": True,
        }
    ]
    for index in range(12):
        rows.append(
            {
                "name": "refs/heads/main" if index == 0 else f"refs/heads/sealed-{index}",
                "kind": "protected-branch" if index == 0 else "branch",
                "target": BASE_SHA if index == 0 else full_sha(100 + index),
                "targetReachable": True,
            }
        )
    rows.append(
        {
            "name": "refs/tags/nyayone-bootstrap-20260815",
            "kind": "annotated-tag",
            "target": full_sha(300),
            "peeledTarget": full_sha(301),
            "targetReachable": True,
        }
    )
    for index in range(1, 12):
        rows.append(
            {
                "name": f"refs/pull/{index}/head",
                "kind": "server-managed-pull",
                "target": full_sha(400 + index),
                "targetReachable": True,
            }
        )
    return rows


def authoritative_inventory() -> dict[str, object]:
    refs = canonical_remote_refs()
    ref_digest = canonical_json_sha256(refs)
    target_digest = canonical_json_sha256(TARGETS)
    return {
        "repository": REPOSITORY,
        "visibility": "PRIVATE",
        "defaultBranch": "main",
        "capturedAt": "2026-08-26T15:30:00Z",
        "sourceHead": BASE_SHA,
        "refs": refs,
        "refInventorySha256": ref_digest,
        "protectedCheckout": {
            "root": "/Users/rajeevbarnwal/Desktop/Codes/NyayOne",
            "head": BASE_SHA,
            "entries": 299,
            "statusSha256": "2bddf5cb49dd5c49919226c21be65fa32df2b1d7328f7e3d105a0dac42080a27",
            "nulStatusSha256": "fe9eb22421cfbb0087501431255a790a6d36e97c7165b0e05a985f66dcc638c0",
        },
        "targetManifest": list(copy.deepcopy(TARGETS)),
        "targetManifestSha256": target_digest,
        "sourceCommit": SOURCE_COMMIT,
        "deletionCommit": DELETION_COMMIT,
        "reachableCommitCount": 297,
        "affectedCommitCount": 243,
        "signedCommitCount": 31,
    }


def canonical_authorizations() -> dict[str, object]:
    inventory = authoritative_inventory()
    publishable_refs = [
        row["name"]
        for row in inventory["refs"]
        if row["kind"] in {"branch", "protected-branch", "annotated-tag"}
    ]
    owner_rewrite = {
        "name": OWNER_APPROVER,
        "role": "repository-owner",
        "decision": "APPROVE",
        "approvalRecordSha256": "4" * 64,
    }
    security_rewrite = {
        "name": SECURITY_PRIVACY_APPROVER,
        "role": "security-privacy",
        "decision": "APPROVE",
        "approvalRecordSha256": "5" * 64,
    }
    return {
        "approvalRegistry": canonical_approval_registry(),
        "rewrite": {
            "approvalId": REWRITE_APPROVAL_ID,
            "approved": True,
            "action": "rewrite-local-mirror",
            "sourceHead": BASE_SHA,
            "refInventorySha256": inventory["refInventorySha256"],
            "targetManifestSha256": inventory["targetManifestSha256"],
            "approvedRefs": publishable_refs,
            "ownerApproval": owner_rewrite,
            "securityPrivacyApproval": security_rewrite,
        },
        "forceUpdate": {
            "approvalId": FORCE_APPROVAL_ID,
            "approved": True,
            "action": "atomic-force-with-lease",
            "sourceHead": BASE_SHA,
            "approvedRefs": publishable_refs,
            "commitMapSha256": "c" * 64,
            "refMapSha256": "d" * 64,
            "ownerApproval": {
                **owner_rewrite,
                "approvalRecordSha256": "6" * 64,
            },
            "securityPrivacyApproval": {
                **security_rewrite,
                "approvalRecordSha256": "7" * 64,
            },
        },
        "visibility": {
            "approved": False,
            "action": "remain-private",
        },
    }


def authorization_context(
    authorizations: dict[str, object],
) -> dict[str, object]:
    registry = authorizations["approvalRegistry"]
    return {
        "authoritative_inventory": authoritative_inventory(),
        "authoritative_approval_registry_sha256": registry["registrySha256"],
    }


def operation_context(
    authorizations: dict[str, object],
    *,
    planned: dict[str, object] | None = None,
    current: dict[str, object] | None = None,
) -> dict[str, object]:
    planned_inventory = planned or authoritative_inventory()
    current_inventory = current or copy.deepcopy(planned_inventory)
    return {
        "planned_inventory": planned_inventory,
        "authoritative_inventory": current_inventory,
        "authoritative_ref_inventory_sha256": current_inventory[
            "refInventorySha256"
        ],
        "authoritative_target_manifest_sha256": current_inventory[
            "targetManifestSha256"
        ],
        "authoritative_approval_registry_sha256": authorizations[
            "approvalRegistry"
        ]["registrySha256"],
    }


def canonical_ruleset() -> dict[str, object]:
    return {
        "id": 20888530,
        "name": "NyayOne main baseline protection",
        "enforcement": "active",
        "target": "refs/heads/main",
        "bypassActors": [],
        "deletion": False,
        "nonFastForward": False,
        "requiredChecksStrict": True,
        "requiredChecks": list(STRICT_REQUIRED_CHECKS),
        "pullRequest": {
            "requiredApprovals": 0,
            "dismissStaleReviews": True,
            "requireConversationResolution": True,
        },
    }


class Nyay21HistoryPurgeRedTests(unittest.TestCase):
    maxDiff = None

    def test_01_target_manifest_is_exact_and_content_addressed(self) -> None:
        gate = load_subject(self, "NYAY21-TARGET-MANIFEST")
        self.assertTrue(CONTRACT.is_file(), "the versioned NYAY-21 contract is required")
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.assertEqual(contract["schemaVersion"], SCHEMA_VERSION)
        self.assertEqual(tuple(contract["targets"]), TARGETS)
        self.assertEqual(contract["reachableCommitCount"], 297)
        self.assertEqual(contract["expectedAffectedCommitCount"], 243)
        self.assertEqual(contract["signedCommitCount"], 31)
        self.assertEqual(
            contract["approvalPolicy"],
            {
                "registrySchemaVersion": APPROVAL_REGISTRY_SCHEMA,
                "ownerApprover": OWNER_APPROVER,
                "requiredRoles": ["repository-owner", "security-privacy"],
                "sameSecurityPrivacyApproverAcrossGates": True,
                "approvalIdFormat": "NYAY21-(REWRITE|FORCE)-UUIDv4",
                "approvalUuidDistinctAcrossGates": True,
                "approvalRecordSha256Required": True,
                "approvalRecordsDistinctAcrossGates": True,
                "authoritativeSealRecomputation": True,
                "singleUse": True,
            },
        )
        self.assertEqual(contract["requiredGateIds"], list(STRICT_REQUIRED_CHECKS))
        self.assertEqual(
            contract["signatureDisposition"],
            "git-filter-repo-strips-31-gpg-signatures; preserve old signed objects only in the restricted backup and re-sign release attestations on rewritten heads",
        )
        self.assertEqual(gate.REPOSITORY, REPOSITORY)
        self.assertEqual(gate.BASE_SHA, BASE_SHA)
        self.assertEqual(gate.SOURCE_COMMIT, SOURCE_COMMIT)
        self.assertEqual(tuple(gate.TARGETS), TARGETS)
        invalid = [dict(TARGETS[0]), {**TARGETS[1], "size": 1}]
        self.assertIn(
            "TARGET_MANIFEST_MISMATCH",
            finding_codes(gate.validate_target_manifest(invalid)),
        )

    def test_02_rewrite_and_force_update_require_distinct_bound_approvals(self) -> None:
        gate = load_subject(self, "NYAY21-SEPARATE-AUTHORIZATIONS")
        approvals = canonical_authorizations()
        self.assertEqual(
            gate.validate_authorizations(
                approvals,
                authoritative_commit_map_sha256="c" * 64,
                authoritative_ref_map_sha256="d" * 64,
                **authorization_context(approvals),
            )["verdict"],
            "PASS",
        )
        approvals["forceUpdate"]["approvalId"] = approvals["rewrite"]["approvalId"]
        result = gate.validate_authorizations(
            approvals,
            authoritative_commit_map_sha256="c" * 64,
            authoritative_ref_map_sha256="d" * 64,
            **authorization_context(approvals),
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("DISTINCT_FORCE_APPROVAL_REQUIRED", finding_codes(result))
        self.assertFalse(result["visibilityChangeAuthorized"])

        rewrite_only = canonical_authorizations()
        rewrite_only.pop("forceUpdate")
        result = gate.validate_authorizations(
            rewrite_only,
            **authorization_context(rewrite_only),
        )
        self.assertEqual(result["verdict"], "PASS_FOR_LOCAL_MIRROR")
        self.assertTrue(result["rewriteAuthorized"])
        self.assertFalse(result["pushAuthorized"])
        self.assertIn("FORCE_UPDATE_APPROVAL_PENDING", finding_codes(result))

    def test_03_unauthorized_or_default_invocation_is_plan_only_and_non_mutating(self) -> None:
        gate = load_subject(self, "NYAY21-PLAN-ONLY-DEFAULT")
        result = gate.validate_operations(
            [{"kind": "inventory"}, {"kind": "render-local-plan"}],
            authorizations={},
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertFalse(result["rewriteAuthorized"])
        self.assertFalse(result["pushAuthorized"])
        self.assertEqual(result["mutationOperations"], [])

        rewrite_only = canonical_authorizations()
        rewrite_only.pop("forceUpdate")
        result = gate.validate_operations(
            [{"kind": "rewrite-local-mirror"}],
            authorizations=rewrite_only,
            **operation_context(rewrite_only),
        )
        self.assertEqual(result["verdict"], "PASS_FOR_LOCAL_MIRROR")
        self.assertTrue(result["rewriteAuthorized"])
        self.assertFalse(result["pushAuthorized"])
        self.assertEqual(result["mutationOperations"], ["rewrite-local-mirror"])

        result = gate.validate_operations(
            [{"kind": "change-visibility"}],
            authorizations=rewrite_only,
            **operation_context(rewrite_only),
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("UNKNOWN_OR_FORBIDDEN_OPERATION", finding_codes(result))
        self.assertEqual(result["mutationOperations"], [])

    def test_04_protected_checkout_seal_and_isolated_roots_are_mandatory(self) -> None:
        gate = load_subject(self, "NYAY21-PROTECTED-CHECKOUT-ISOLATION")
        seal = authoritative_inventory()["protectedCheckout"]
        valid = gate.validate_execution_environment(
            protected_root=seal["root"],
            execution_root="/private/tmp/nyay21-rewrite.git",
            backup_root="/private/tmp/nyay21-recovery",
            before=seal,
            after=copy.deepcopy(seal),
            fresh_bare_mirror=True,
        )
        self.assertEqual(valid["verdict"], "PASS")
        changed = copy.deepcopy(seal)
        changed["entries"] = 300
        invalid = gate.validate_execution_environment(
            protected_root=seal["root"],
            execution_root=seal["root"],
            backup_root=f"{seal['root']}/backup",
            before=seal,
            after=changed,
            fresh_bare_mirror=False,
        )
        self.assertIn("UNSAFE_EXECUTION_ROOT", finding_codes(invalid))
        self.assertIn("PROTECTED_CHECKOUT_CHANGED", finding_codes(invalid))

    def test_05_ref_inventory_is_closed_world_typed_and_complete(self) -> None:
        gate = load_subject(self, "NYAY21-CLOSED-WORLD-REF-INVENTORY")
        inventory = authoritative_inventory()
        result = gate.validate_ref_inventory(inventory, inventory["refs"])
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["counts"]["heads"], 12)
        self.assertEqual(result["counts"]["annotatedTags"], 1)
        self.assertEqual(result["counts"]["serverManagedPulls"], 11)
        candidate = copy.deepcopy(inventory)
        candidate["refs"].append(
            {"name": "refs/unknown/retained", "kind": "unknown", "target": full_sha(999)}
        )
        self.assertIn(
            "UNCLASSIFIED_RELEVANT_REF",
            finding_codes(gate.validate_ref_inventory(candidate, inventory["refs"])),
        )

    def test_06_publishable_allowlist_rejects_wildcards_and_host_managed_refs(self) -> None:
        gate = load_subject(self, "NYAY21-REF-ALLOWLIST")
        inventory = authoritative_inventory()
        approved = canonical_authorizations()["rewrite"]["approvedRefs"]
        self.assertEqual(gate.validate_rewrite_refs(approved, inventory)["verdict"], "PASS")
        for invalid in (["refs/heads/*"], ["--all"], ["refs/pull/1/head"], ["HEAD"]):
            with self.subTest(invalid=invalid):
                result = gate.validate_rewrite_refs(invalid, inventory)
                self.assertIn("UNSAFE_REF_SCOPE", finding_codes(result))

    def test_07_preflight_proves_exact_target_origin_and_reachability(self) -> None:
        gate = load_subject(self, "NYAY21-PREFLIGHT-TARGET-REACHABILITY")
        inventory = authoritative_inventory()
        observations = [
            {
                "ref": row["name"],
                "targets": list(copy.deepcopy(TARGETS)),
                "sourceCommit": SOURCE_COMMIT,
            }
            for row in inventory["refs"]
        ]
        self.assertEqual(
            gate.validate_pre_rewrite_reachability(inventory, observations)["verdict"],
            "PASS",
        )
        observations[0]["targets"][0]["blob"] = full_sha(700)
        self.assertIn(
            "TARGET_BASELINE_MISMATCH",
            finding_codes(gate.validate_pre_rewrite_reachability(inventory, observations)),
        )

    def test_08_authoritative_remote_or_inventory_drift_invalidates_the_plan(self) -> None:
        gate = load_subject(self, "NYAY21-HEAD-CHANGED")
        inventory = authoritative_inventory()
        drifted = copy.deepcopy(inventory)
        drifted["sourceHead"] = full_sha(800)
        drifted["refInventorySha256"] = "8" * 64
        result = gate.validate_preflight(
            canonical_authorizations(),
            planned_inventory=inventory,
            authoritative_inventory=drifted,
        )
        self.assertEqual(result["verdict"], "HEAD_CHANGED")
        self.assertFalse(result["rewriteAuthorized"])
        self.assertFalse(result["pushAuthorized"])

    def test_09_backup_is_external_checksummed_restore_tested_and_private(self) -> None:
        gate = load_subject(self, "NYAY21-RECOVERABLE-BACKUP")
        inventory = authoritative_inventory()
        backup = {
            "path": "/private/tmp/nyay21-recovery/pre-rewrite.bundle",
            "nodeType": "regular-file",
            "locationOutsideRepositories": True,
            "directoryMode": "0700",
            "fileMode": "0600",
            "encrypted": True,
            "custodians": ["Rajeev Barnwal", "Named Security Reviewer"],
            "accessLogEnabled": True,
            "destructionAt": "2026-09-30T18:29:59Z",
            "sha256": "9" * 64,
            "bundleVerifyExitCode": 0,
            "restoredFsckExitCode": 0,
            "containedRefs": [row["name"] for row in inventory["refs"]],
            "classification": "restricted-private-pre-rewrite",
            "publiclyPublishable": False,
            "createdBeforeRewrite": True,
        }
        self.assertEqual(gate.validate_backup(backup, inventory)["verdict"], "PASS")
        backup["containedRefs"].pop()
        backup["encrypted"] = False
        backup["locationOutsideRepositories"] = False
        self.assertIn("BACKUP_INCOMPLETE", finding_codes(gate.validate_backup(backup, inventory)))
        self.assertIn("UNSAFE_BACKUP_LOCATION", finding_codes(gate.validate_backup(backup, inventory)))
        self.assertIn("BACKUP_GOVERNANCE_INCOMPLETE", finding_codes(gate.validate_backup(backup, inventory)))

    def test_10_filter_repo_command_is_pinned_exact_and_narrow(self) -> None:
        gate = load_subject(self, "NYAY21-FILTER-REPO-COMMAND")
        plan = {
            "tool": "git-filter-repo",
            "toolVersion": "a40bce548d2c",
            "freshMirror": True,
            "targetPaths": [row["path"] for row in TARGETS],
            "sensitiveDataRemoval": True,
            "invertPaths": True,
        }
        argv = tuple(gate.render_local_rewrite_argv(plan))
        self.assertEqual(
            argv,
            (
                "git",
                "filter-repo",
                "--sensitive-data-removal",
                "--invert-paths",
                "--preserve-commit-hashes",
                "--replace-refs",
                "delete-no-add",
                "--prune-empty",
                "auto",
                "--prune-degenerate",
                "auto",
                "--path",
                TARGETS[0]["path"],
                "--path",
                TARGETS[1]["path"],
            ),
        )
        for forbidden in (
            "--force",
            "--partial",
            "--refs",
            "--no-fetch",
            "--no-gc",
            "--mirror",
            "--all",
            "*",
        ):
            self.assertNotIn(forbidden, argv)

    def test_11_fresh_private_origin_mirror_is_required_for_local_rewrite(self) -> None:
        gate = load_subject(self, "NYAY21-FRESH-PRIVATE-MIRROR")
        mirror = {
            "fresh": True,
            "bare": True,
            "origin": "git@github.com:rajeevbarnwal/NyayOne.git",
            "remoteOriginMirror": True,
            "repository": REPOSITORY,
            "visibility": "PRIVATE",
            "sourceHead": BASE_SHA,
            "refInventorySha256": authoritative_inventory()["refInventorySha256"],
            "authoritativeRefInventorySha256": authoritative_inventory()["refInventorySha256"],
            "cloneProof": "fresh-network-mirror",
            "writableProductionRemote": False,
            "pushDisabled": True,
            "pushUrl": "disabled://nyay21-local-mirror",
            "hasLocalWork": False,
        }
        self.assertEqual(gate.validate_rewrite_mirror(mirror)["verdict"], "PASS")
        mirror["fresh"] = False
        mirror["remoteOriginMirror"] = False
        mirror["authoritativeRefInventorySha256"] = "b" * 64
        mirror["writableProductionRemote"] = True
        mirror["pushDisabled"] = False
        mirror["pushUrl"] = "git@github.com:rajeevbarnwal/NyayOne.git"
        codes = finding_codes(gate.validate_rewrite_mirror(mirror))
        self.assertIn("FRESH_MIRROR_REQUIRED", codes)
        self.assertIn("MIRROR_ORIGIN_IDENTITY_MISMATCH", codes)
        self.assertIn("MIRROR_REF_INVENTORY_MISMATCH", codes)
        self.assertIn("WRITABLE_PRODUCTION_REMOTE_FORBIDDEN", codes)

    def test_12_rewrite_preserves_non_target_content_topology_and_metadata(self) -> None:
        gate = load_subject(self, "NYAY21-RETENTION-BOUNDARY")
        before = {
            "targetBlobs": [row["blob"] for row in TARGETS],
            "nonTargetObjects": [full_sha(1200), full_sha(1201)],
            "unrelatedFiles": {
                "backend/legalsaathi_dev.db": "c" * 64,
                "docs/evidence.json": "d" * 64,
            },
            "topologyDigest": "e" * 64,
            "nonSignatureMetadataDigest": "f" * 64,
            "signedCommitCount": 31,
            "signatureManifestSha256": "4" * 64,
        }
        after = copy.deepcopy(before)
        after["targetBlobs"] = []
        after["signedCommitCount"] = 0
        after["signatureDisposition"] = (
            "git-filter-repo-stripped-31-gpg-signatures-with-sealed-old-object-map"
        )
        after["unexpectedMetadataChanges"] = []
        result = gate.validate_retention_boundary(before, after, allowedPruned=[DELETION_COMMIT])
        self.assertEqual(result["verdict"], "PASS")
        after["unrelatedFiles"].pop("docs/evidence.json")
        self.assertIn("REWRITE_SCOPE_DRIFT", finding_codes(gate.validate_retention_boundary(before, after, allowedPruned=[DELETION_COMMIT])))
        after = copy.deepcopy(before)
        after["targetBlobs"] = []
        after["signedCommitCount"] = 30
        after["signatureDisposition"] = "undocumented"
        after["unexpectedMetadataChanges"] = []
        self.assertIn(
            "SIGNATURE_DISPOSITION_MISMATCH",
            finding_codes(
                gate.validate_retention_boundary(
                    before,
                    after,
                    allowedPruned=[DELETION_COMMIT],
                )
            ),
        )

    def test_13_commit_map_is_complete_and_records_pruned_deletion_commit(self) -> None:
        gate = load_subject(self, "NYAY21-COMMIT-MAP")
        affected = list(KNOWN_INVALIDATED_SHAS) + [full_sha(index) for index in range(1, 238)]
        rows = [
            {"old": old, "new": full_sha(2000 + index), "disposition": "rewritten"}
            for index, old in enumerate(affected)
        ]
        rows.append({"old": DELETION_COMMIT, "new": NULL_SHA, "disposition": "pruned-empty"})
        rows.extend(
            {
                "old": full_sha(1000 + index),
                "new": full_sha(1000 + index),
                "disposition": "unchanged",
            }
            for index in range(54)
        )
        self.assertEqual(len(rows), 297)
        result = gate.validate_commit_map(
            rows,
            expectedReachableCount=297,
            expectedAffectedCount=243,
            requiredOldShas=KNOWN_INVALIDATED_SHAS + (DELETION_COMMIT,),
        )
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(result["mapping"][DELETION_COMMIT], NULL_SHA)

    def test_14_ref_map_covers_each_approved_ref_without_rename_or_drop(self) -> None:
        gate = load_subject(self, "NYAY21-REF-MAP")
        inventory = authoritative_inventory()
        approved = canonical_authorizations()["rewrite"]["approvedRefs"]
        rows = [
            {
                "ref": name,
                "old": next(row["target"] for row in inventory["refs"] if row["name"] == name),
                "new": full_sha(1400 + index),
                "kind": next(row["kind"] for row in inventory["refs"] if row["name"] == name),
            }
            for index, name in enumerate(approved)
        ]
        self.assertEqual(gate.validate_ref_map(rows, inventory, approved)["verdict"], "PASS")
        rows.pop()
        self.assertIn("REF_MAP_INCOMPLETE", finding_codes(gate.validate_ref_map(rows, inventory, approved)))

    def test_15_target_paths_and_blobs_are_unreachable_from_every_clean_ref(self) -> None:
        gate = load_subject(self, "NYAY21-POST-REWRITE-REACHABILITY")
        inventory = authoritative_inventory()
        audit = {
            "scannedRefs": [
                row["name"]
                for row in inventory["refs"]
                if row["kind"] != "symbolic-head"
            ],
            "reachableObjects": [full_sha(1500)],
            "reachableByRef": {
                row["name"]: [full_sha(1500)]
                for row in inventory["refs"]
                if row["kind"] != "symbolic-head"
            },
            "historicalPaths": ["backend/legalsaathi_dev.db", "docs/evidence.json"],
            "internalRetentionRefs": [],
            "reflogTargetObjects": [],
        }
        self.assertEqual(gate.verify_purge_reachability(audit, inventory)["verdict"], "PASS")
        audit["reachableByRef"]["refs/pull/1/head"].append(TARGETS[0]["blob"])
        self.assertIn("TARGET_BLOB_STILL_REACHABLE", finding_codes(gate.verify_purge_reachability(audit, inventory)))

    def test_16_side_branch_tag_and_merge_contamination_is_detected(self) -> None:
        gate = load_subject(self, "NYAY21-PLANTED-HISTORY-CANARY")
        observations = [
            {"location": "side-branch", "blob": TARGETS[0]["blob"], "detected": True},
            {"location": "annotated-tag", "blob": TARGETS[1]["blob"], "detected": True},
            {"location": "second-parent", "blob": TARGETS[0]["blob"], "detected": True},
        ]
        self.assertEqual(gate.validate_seeded_history_canary(observations)["verdict"], "PASS")
        observations[2]["detected"] = False
        self.assertIn("SEEDED_HISTORY_CANARY_MISSED", finding_codes(gate.validate_seeded_history_canary(observations)))

    def test_17_host_managed_and_backup_retention_blocks_public_readiness(self) -> None:
        gate = load_subject(self, "NYAY21-UNRESOLVED-RETENTION")
        retention = {
            "backup": {"restricted": True, "outsidePublishableRefs": True},
            "serverManagedPullRefs": {"count": 11, "targetReachable": True, "remediated": False},
            "githubCaches": {"confirmation": "pending"},
        }
        result = gate.validate_residual_retention(retention)
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertFalse(result["publicVisibilityEligible"])
        self.assertIn("SERVER_MANAGED_REF_STILL_REACHABLE", finding_codes(result))

    def test_18_push_plan_is_atomic_exact_lease_bound_and_closed_scope(self) -> None:
        gate = load_subject(self, "NYAY21-GUARDED-FORCE-UPDATE")
        inventory = authoritative_inventory()
        approved = canonical_authorizations()["forceUpdate"]["approvedRefs"]
        mapping = {
            name: {
                "old": next(row["target"] for row in inventory["refs"] if row["name"] == name),
                "new": full_sha(1800 + index),
            }
            for index, name in enumerate(approved)
        }
        commands = gate.render_force_update_commands(mapping, approved)
        self.assertEqual(len(commands), 1, "all approved refs must share one atomic transaction")
        command = commands[0]
        for name in approved:
            self.assertEqual(command.count(f"--force-with-lease={name}:{mapping[name]['old']}"), 1)
            self.assertEqual(command.count(f"{mapping[name]['new']}:{name}"), 1)
        rendered = command
        for forbidden in (" --force ", "--mirror", "--all", " origin :refs/", "--delete"):
            self.assertNotIn(forbidden, rendered)

    def test_19_ruleset_and_all_strict_required_checks_restore_exactly(self) -> None:
        gate = load_subject(self, "NYAY21-PROTECTION-RESTORATION")
        before = canonical_ruleset()
        after = copy.deepcopy(before)
        self.assertEqual(gate.validate_ruleset_restoration(before, after)["verdict"], "PASS")
        after["requiredChecks"].pop()
        after["requiredChecksStrict"] = False
        result = gate.validate_ruleset_restoration(before, after)
        self.assertIn("PROTECTION_NOT_RESTORED", finding_codes(result))
        self.assertIn("ORACLE_WEAKENED", finding_codes(result))

    def test_20_collaborators_must_reclone_and_cannot_merge_old_history(self) -> None:
        gate = load_subject(self, "NYAY21-COLLABORATOR-REALIGNMENT")
        plan = {
            "methods": ["reclone", "fetch-and-reset-to-exact-new-tip"],
            "forbidden": ["merge-old-history", "rebase-old-history", "cherry-pick-old-history"],
            "acknowledgementsRequired": True,
        }
        self.assertEqual(gate.validate_collaborator_recovery(plan)["verdict"], "PASS")
        plan["methods"].append("merge-old-history")
        self.assertIn("OLD_HISTORY_REINTRODUCTION_RISK", finding_codes(gate.validate_collaborator_recovery(plan)))

    def test_21_all_exact_commit_bindings_are_inventoried_without_digest_confusion(self) -> None:
        gate = load_subject(self, "NYAY21-EXACT-HEAD-BINDING-INVENTORY")
        bindings = [
            {"system": system, "kind": "git-commit", "sha": KNOWN_INVALIDATED_SHAS[index % len(KNOWN_INVALIDATED_SHAS)]}
            for index, system in enumerate(("qa", "docs", "code", "jira", "github", "manifest"))
        ]
        self.assertEqual(gate.validate_exact_head_inventory(bindings, KNOWN_INVALIDATED_SHAS)["verdict"], "PASS")
        bindings.append({"system": "manifest", "kind": "git-commit", "sha": "f" * 64})
        result = gate.validate_exact_head_inventory(bindings, KNOWN_INVALIDATED_SHAS)
        self.assertIn("DIGEST_IS_NOT_COMMIT_IDENTITY", finding_codes(result))

    def test_22_old_evidence_is_immutable_invalidated_and_never_silently_relabelled(self) -> None:
        gate = load_subject(self, "NYAY21-EVIDENCE-INVALIDATION")
        old = {
            "evidenceId": "sealed-old-evidence",
            "testedHead": KNOWN_INVALIDATED_SHAS[0],
            "artifactSha256": "1" * 64,
            "status": "historical-invalidated-by-history-rewrite",
        }
        rebound = {
            "evidenceId": "new-exact-head-rerun",
            "oldSha": KNOWN_INVALIDATED_SHAS[0],
            "testedHead": full_sha(2200),
            "sourceArtifactSha256": old["artifactSha256"],
            "commitMapSha256": "2" * 64,
            "executedAssertions": 1,
            "rawArtifacts": 1,
            "rerunAfterRewrite": True,
        }
        self.assertEqual(gate.validate_evidence_rebinding(old, rebound)["verdict"], "PASS")
        rebound["evidenceId"] = old["evidenceId"]
        rebound["executedAssertions"] = 0
        result = gate.validate_evidence_rebinding(old, rebound)
        self.assertIn("SILENT_EVIDENCE_RELABEL", finding_codes(result))
        self.assertIn("EVIDENCE_RERUN_MISSING", finding_codes(result))

    def test_23_fresh_exact_head_gates_are_nonzero_and_oracles_cannot_weaken(self) -> None:
        gate = load_subject(self, "NYAY21-FRESH-GATE-READBACKS")
        gates = [
            {"id": name, "testedHead": full_sha(2300), "executed": 1, "passed": 1, "failed": 0, "oracleDigest": "3" * 64}
            for name in STRICT_REQUIRED_CHECKS
        ]
        self.assertEqual(gate.validate_gate_readbacks(gates, full_sha(2300))["verdict"], "PASS")
        gates[0]["executed"] = 0
        gates[1]["testedHead"] = BASE_SHA
        result = gate.validate_gate_readbacks(gates, full_sha(2300))
        self.assertIn("ZERO_ASSERTIONS", finding_codes(result))
        self.assertIn("STALE_EXACT_HEAD_EVIDENCE", finding_codes(result))

    def test_24_pre_public_audit_keeps_repo_private_and_only_hands_off_decision(self) -> None:
        gate = load_subject(self, "NYAY21-PRE-PUBLIC-HOLD")
        request = (
            HERE.parent.parent
            / "docs"
            / "operations"
            / "nyay21-history-purge"
            / "REWRITE_EXECUTION_REQUEST.md"
        ).read_text(encoding="utf-8")
        self.assertIn("| Approved action | `rewrite-local-mirror` |", request)
        self.assertIn("| Approved action | `atomic-force-with-lease` |", request)
        self.assertNotIn("`rewrite-local-production-mirror`", request)
        self.assertNotIn("`atomic-exact-force-with-lease`", request)
        audit = {
            "independent": True,
            "historyTargetFindings": 0,
            "privacyFindings": 0,
            "unaccountedForks": 0,
            "unaccountedRetention": 0,
            "repositoryVisibilityBefore": "PRIVATE",
            "repositoryVisibilityAfter": "PRIVATE",
            "localAndRemoteGatesPassed": True,
            "separateVisibilityDecisionRecorded": False,
        }
        result = gate.validate_pre_public_audit(audit)
        self.assertEqual(result["verdict"], "READY_FOR_SEPARATE_VISIBILITY_DECISION")
        self.assertFalse(result["visibilityChangeAuthorized"])
        self.assertFalse(result["publicVisibilityEligible"])
        audit["repositoryVisibilityAfter"] = "PUBLIC"
        invalid = gate.validate_pre_public_audit(audit)
        self.assertEqual(invalid["verdict"], "FAIL")
        self.assertIn("VISIBILITY_CHANGED_WITHOUT_APPROVAL", finding_codes(invalid))

    def test_25_empty_ref_scope_cannot_authorize_or_render_force_plan(self) -> None:
        gate = load_subject(self, "NYAY21-EMPTY-FORCE-PLAN")
        for remove_key in (False, True):
            with self.subTest(remove_key=remove_key):
                approvals = canonical_authorizations()
                for gate_name in ("rewrite", "forceUpdate"):
                    if remove_key:
                        approvals[gate_name].pop("approvedRefs")
                    else:
                        approvals[gate_name]["approvedRefs"] = []
                result = gate.validate_authorizations(
                    approvals,
                    authoritative_commit_map_sha256="c" * 64,
                    authoritative_ref_map_sha256="d" * 64,
                    **authorization_context(approvals),
                )
                self.assertEqual(result["verdict"], "BLOCKED")
                self.assertFalse(result["rewriteAuthorized"])
                self.assertFalse(result["pushAuthorized"])
                self.assertIn("UNSAFE_REF_SCOPE", finding_codes(result))
        with self.assertRaisesRegex(ValueError, "non-empty"):
            gate.render_force_update_commands({}, [])

    def test_26_gate_readbacks_require_the_exact_closed_required_set(self) -> None:
        gate = load_subject(self, "NYAY21-CLOSED-GATE-READBACKS")
        expected_head = full_sha(2600)
        complete = [
            {
                "id": name,
                "testedHead": expected_head,
                "executed": 1,
                "passed": 1,
                "failed": 0,
                "oracleDigest": "8" * 64,
            }
            for name in STRICT_REQUIRED_CHECKS
        ]
        self.assertEqual(
            gate.validate_gate_readbacks(complete, expected_head)["verdict"],
            "PASS",
        )
        for rows in (
            [],
            complete[:-1],
            complete + [copy.deepcopy(complete[0])],
            [{**row, "id": "unknown-required-check"} for row in complete],
        ):
            with self.subTest(rows=len(rows)):
                result = gate.validate_gate_readbacks(rows, expected_head)
                self.assertEqual(result["verdict"], "FAIL")
                self.assertIn("GATE_READBACK_INCOMPLETE", finding_codes(result))

    def test_27_mutation_operations_are_bound_to_authoritative_preflight(self) -> None:
        gate = load_subject(self, "NYAY21-OPERATIONS-SEAL-BINDING")
        approvals = canonical_authorizations()
        approvals.pop("forceUpdate")
        planned = authoritative_inventory()
        valid = gate.validate_operations(
            [{"kind": "rewrite-local-mirror"}],
            authorizations=approvals,
            **operation_context(approvals, planned=planned),
        )
        self.assertEqual(valid["verdict"], "PASS_FOR_LOCAL_MIRROR")
        self.assertEqual(valid["mutationOperations"], ["rewrite-local-mirror"])

        approvals["rewrite"]["refInventorySha256"] = "a" * 64
        direct = gate.validate_authorizations(
            approvals,
            **authorization_context(approvals),
        )
        self.assertEqual(direct["verdict"], "BLOCKED")
        self.assertFalse(direct["rewriteAuthorized"])
        self.assertFalse(direct["pushAuthorized"])
        self.assertIn("APPROVAL_INPUT_SEAL_MISMATCH", finding_codes(direct))
        mismatch = gate.validate_operations(
            [{"kind": "rewrite-local-mirror"}],
            authorizations=approvals,
            **operation_context(approvals, planned=planned),
        )
        self.assertEqual(mismatch["verdict"], "BLOCKED")
        self.assertEqual(mismatch["mutationOperations"], [])
        self.assertIn("APPROVAL_INPUT_SEAL_MISMATCH", finding_codes(mismatch))

        approvals = canonical_authorizations()
        approvals.pop("forceUpdate")
        wrong_authority = operation_context(approvals, planned=planned)
        wrong_authority["authoritative_ref_inventory_sha256"] = "b" * 64
        mismatch = gate.validate_operations(
            [{"kind": "rewrite-local-mirror"}],
            authorizations=approvals,
            **wrong_authority,
        )
        self.assertEqual(mismatch["verdict"], "BLOCKED")
        self.assertEqual(mismatch["mutationOperations"], [])
        self.assertIn("AUTHORITATIVE_SEAL_MISMATCH", finding_codes(mismatch))

        approvals = canonical_authorizations()
        approvals.pop("forceUpdate")
        drifted = copy.deepcopy(planned)
        drifted["sourceHead"] = full_sha(2700)
        changed = gate.validate_operations(
            [{"kind": "rewrite-local-mirror"}],
            authorizations=approvals,
            **operation_context(approvals, planned=planned, current=drifted),
        )
        self.assertEqual(changed["verdict"], "HEAD_CHANGED")
        self.assertEqual(changed["mutationOperations"], [])
        self.assertIn("HEAD_CHANGED", finding_codes(changed))

    def test_28_approvals_are_named_recorded_typed_and_single_use(self) -> None:
        gate = load_subject(self, "NYAY21-STATEFUL-APPROVALS")
        valid = canonical_authorizations()
        self.assertEqual(
            gate.validate_authorizations(
                valid,
                authoritative_commit_map_sha256="c" * 64,
                authoritative_ref_map_sha256="d" * 64,
                **authorization_context(valid),
            )["verdict"],
            "PASS",
        )

        consumed = canonical_authorizations()
        registry = canonical_approval_registry((REWRITE_APPROVAL_ID,))
        consumed["approvalRegistry"] = registry
        result = gate.validate_authorizations(
            consumed,
            authoritative_commit_map_sha256="c" * 64,
            authoritative_ref_map_sha256="d" * 64,
            authoritative_inventory=authoritative_inventory(),
            authoritative_approval_registry_sha256=registry["registrySha256"],
        )
        self.assertIn("APPROVAL_ALREADY_CONSUMED", finding_codes(result))
        self.assertFalse(result["rewriteAuthorized"])
        self.assertFalse(result["pushAuthorized"])

        cross_namespace = canonical_authorizations()
        force_uuid = cross_namespace["forceUpdate"]["approvalId"].removeprefix(
            "NYAY21-FORCE-"
        )
        registry = canonical_approval_registry(
            (f"NYAY21-REWRITE-{force_uuid}",)
        )
        cross_namespace["approvalRegistry"] = registry
        result = gate.validate_authorizations(
            cross_namespace,
            authoritative_commit_map_sha256="c" * 64,
            authoritative_ref_map_sha256="d" * 64,
            authoritative_inventory=authoritative_inventory(),
            authoritative_approval_registry_sha256=registry["registrySha256"],
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertFalse(result["pushAuthorized"])
        self.assertIn("APPROVAL_ALREADY_CONSUMED", finding_codes(result))

        adversaries = []
        unnamed = canonical_authorizations()
        unnamed["rewrite"]["securityPrivacyApproval"]["name"] = ""
        adversaries.append((unnamed, "NAMED_APPROVERS_REQUIRED"))
        different = canonical_authorizations()
        different["forceUpdate"]["securityPrivacyApproval"]["name"] = "Other Reviewer"
        adversaries.append((different, "SECURITY_APPROVER_MISMATCH"))
        unsigned = canonical_authorizations()
        unsigned["rewrite"]["ownerApproval"].pop("approvalRecordSha256")
        adversaries.append((unsigned, "APPROVAL_RECORD_REQUIRED"))
        malformed_id = canonical_authorizations()
        malformed_id["rewrite"]["approvalId"] = "free-form"
        adversaries.append((malformed_id, "APPROVAL_ID_INVALID"))
        for approvals, expected_code in adversaries:
            with self.subTest(expected_code=expected_code):
                result = gate.validate_authorizations(
                    approvals,
                    authoritative_commit_map_sha256="c" * 64,
                    authoritative_ref_map_sha256="d" * 64,
                    **authorization_context(approvals),
                )
                self.assertEqual(result["verdict"], "BLOCKED")
                self.assertIn(expected_code, finding_codes(result))

        mismatch = canonical_authorizations()
        result = gate.validate_authorizations(
            mismatch,
            authoritative_commit_map_sha256="c" * 64,
            authoritative_ref_map_sha256="d" * 64,
            authoritative_inventory=authoritative_inventory(),
            authoritative_approval_registry_sha256="f" * 64,
        )
        self.assertIn("APPROVAL_REGISTRY_MISMATCH", finding_codes(result))

        malformed_registry = canonical_authorizations()
        registry_payload = {
            "schemaVersion": APPROVAL_REGISTRY_SCHEMA,
            "consumedApprovalIds": [{}],
        }
        malformed_registry["approvalRegistry"] = {
            **registry_payload,
            "registrySha256": canonical_json_sha256(registry_payload),
        }
        result = gate.validate_authorizations(
            malformed_registry,
            authoritative_commit_map_sha256="c" * 64,
            authoritative_ref_map_sha256="d" * 64,
            authoritative_inventory=authoritative_inventory(),
            authoritative_approval_registry_sha256=malformed_registry[
                "approvalRegistry"
            ]["registrySha256"],
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("APPROVAL_REGISTRY_INVALID", finding_codes(result))

    def test_29_strict_booleans_and_empty_validators_fail_closed(self) -> None:
        gate = load_subject(self, "NYAY21-STRICT-NONEMPTY-INPUTS")
        for gate_name in ("rewrite", "forceUpdate"):
            for invalid_boolean in ("false", {}):
                with self.subTest(
                    gate_name=gate_name,
                    invalid_boolean=type(invalid_boolean).__name__,
                ):
                    approvals = canonical_authorizations()
                    approvals[gate_name]["approved"] = invalid_boolean
                    result = gate.validate_authorizations(
                        approvals,
                        authoritative_commit_map_sha256="c" * 64,
                        authoritative_ref_map_sha256="d" * 64,
                        **authorization_context(approvals),
                    )
                    self.assertEqual(result["verdict"], "BLOCKED")
                    self.assertIn(
                        "APPROVAL_BOOLEAN_REQUIRED", finding_codes(result)
                    )

        empty_results = (
            (
                gate.validate_ref_inventory({}, []),
                "REF_INVENTORY_EMPTY",
            ),
            (
                gate.validate_ref_map([], {}, []),
                "REF_MAP_EMPTY",
            ),
            (
                gate.validate_pre_rewrite_reachability({}, []),
                "TARGET_REACHABILITY_EMPTY",
            ),
            (
                gate.validate_commit_map(
                    [],
                    expectedReachableCount=0,
                    expectedAffectedCount=0,
                    requiredOldShas=(),
                ),
                "COMMIT_MAP_EMPTY",
            ),
        )
        for result, expected_code in empty_results:
            with self.subTest(expected_code=expected_code):
                self.assertEqual(result["verdict"], "FAIL")
                self.assertIn(expected_code, finding_codes(result))

    def test_30_authoritative_seals_are_recomputed_and_gate_ids_are_distinct(self) -> None:
        gate = load_subject(self, "NYAY21-INTERNAL-SEALS-AND-DISTINCT-GATES")
        approvals = canonical_authorizations()
        approvals.pop("forceUpdate")
        stale_inventory = authoritative_inventory()
        stale_inventory["refs"][0]["target"] = full_sha(3000)
        stale_context = operation_context(
            approvals,
            planned=copy.deepcopy(stale_inventory),
            current=stale_inventory,
        )
        result = gate.validate_operations(
            [{"kind": "rewrite-local-mirror"}],
            authorizations=approvals,
            **stale_context,
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["mutationOperations"], [])
        self.assertIn("AUTHORITATIVE_SEAL_MISMATCH", finding_codes(result))

        stale_targets = authoritative_inventory()
        stale_targets["targetManifest"][0]["size"] = 1
        stale_context = operation_context(
            approvals,
            planned=copy.deepcopy(stale_targets),
            current=stale_targets,
        )
        result = gate.validate_operations(
            [{"kind": "rewrite-local-mirror"}],
            authorizations=approvals,
            **stale_context,
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["mutationOperations"], [])
        self.assertIn("AUTHORITATIVE_SEAL_MISMATCH", finding_codes(result))

        stale_head = authoritative_inventory()
        stale_head["sourceHead"] = full_sha(3001)
        stale_context = operation_context(
            approvals,
            planned=copy.deepcopy(stale_head),
            current=stale_head,
        )
        result = gate.validate_operations(
            [{"kind": "rewrite-local-mirror"}],
            authorizations=approvals,
            **stale_context,
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertEqual(result["mutationOperations"], [])
        self.assertIn("AUTHORITATIVE_SEAL_MISMATCH", finding_codes(result))

        approvals = canonical_authorizations()
        shared_uuid = "33333333-3333-4333-8333-333333333333"
        approvals["rewrite"]["approvalId"] = f"NYAY21-REWRITE-{shared_uuid}"
        approvals["forceUpdate"]["approvalId"] = f"NYAY21-FORCE-{shared_uuid}"
        approvals["forceUpdate"]["ownerApproval"]["approvalRecordSha256"] = (
            approvals["rewrite"]["ownerApproval"]["approvalRecordSha256"]
        )
        result = gate.validate_authorizations(
            approvals,
            authoritative_commit_map_sha256="c" * 64,
            authoritative_ref_map_sha256="d" * 64,
            **authorization_context(approvals),
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertFalse(result["pushAuthorized"])
        self.assertIn("DISTINCT_FORCE_APPROVAL_REQUIRED", finding_codes(result))

    def test_31_malformed_collections_and_expected_head_fail_structurally(self) -> None:
        gate = load_subject(self, "NYAY21-MALFORMED-COLLECTIONS")
        inventory = authoritative_inventory()
        approvals = canonical_authorizations()
        approvals["rewrite"]["approvedRefs"] = [{}]
        result = gate.validate_authorizations(
            approvals,
            authoritative_commit_map_sha256="c" * 64,
            authoritative_ref_map_sha256="d" * 64,
            **authorization_context(approvals),
        )
        self.assertEqual(result["verdict"], "BLOCKED")
        self.assertIn("UNSAFE_REF_SCOPE", finding_codes(result))

        malformed_gates = [
            {
                "id": {},
                "testedHead": full_sha(3100),
                "executed": 1,
                "passed": 1,
                "failed": 0,
                "oracleDigest": "9" * 64,
            }
            for _ in STRICT_REQUIRED_CHECKS
        ]
        result = gate.validate_gate_readbacks(malformed_gates, full_sha(3100))
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("GATE_READBACK_INCOMPLETE", finding_codes(result))

        empty_head_gates = [
            {
                "id": name,
                "testedHead": "",
                "executed": 1,
                "passed": 1,
                "failed": 0,
                "oracleDigest": "9" * 64,
            }
            for name in STRICT_REQUIRED_CHECKS
        ]
        result = gate.validate_gate_readbacks(empty_head_gates, "")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertIn("GATE_READBACK_INVALID_HEAD", finding_codes(result))


if __name__ == "__main__":
    unittest.main()
