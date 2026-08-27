#!/usr/bin/env python3
"""Fail-closed planning and evidence validators for NYAY-21.

This module deliberately does not execute ``git filter-repo``, write a backup,
push a ref, alter a ruleset, or change repository visibility.  It validates
sealed observations and renders narrowly scoped command plans for a separately
authorized operator to inspect and execute in a disposable private mirror.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "nyay21-history-purge/v1"
REPOSITORY = "rajeevbarnwal/NyayOne"
BASE_SHA = "422b3dbbeddb25c6735cd093003ccaef335cb60a"
SOURCE_COMMIT = "9d6d56cc84b4f3fe9e2b223631f8a5e96c815374"
DELETION_COMMIT = "d58d1fbac48db5a29158ca5b3b168b8951d526d1"
FILTER_REPO_VERSION = "a40bce548d2c"
APPROVAL_REGISTRY_SCHEMA = "nyay21-approval-consumption/v1"
OWNER_APPROVER = "Rajeev Barnwal"
STRICT_REQUIRED_CHECKS = (
    "nyayone-registration-required",
    "nyayone-wave1-required",
    "nyayone-wave2-required",
    "nyayone-wave3-required",
    "nyayone-wave4-required",
    "nyayone-wave5-required",
    "nyayone-policy-required",
)
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

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_APPROVAL_ID = {
    "rewrite": re.compile(
        r"^NYAY21-REWRITE-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
    "force": re.compile(
        r"^NYAY21-FORCE-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
        r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    ),
}
_PUBLISHABLE_KINDS = frozenset({"branch", "protected-branch", "annotated-tag"})
_KNOWN_REF_KINDS = _PUBLISHABLE_KINDS | frozenset(
    {"symbolic-head", "server-managed-pull"}
)


def _result(
    codes: Iterable[str] = (),
    *,
    verdict: str | None = None,
    **values: Any,
) -> dict[str, Any]:
    unique_codes = list(dict.fromkeys(code for code in codes if code))
    if verdict is None:
        verdict = "PASS" if not unique_codes else "FAIL"
    return {"verdict": verdict, "codes": unique_codes, **values}


def _is_hex(value: object, width: int) -> bool:
    if not isinstance(value, str):
        return False
    matcher = _HEX40 if width == 40 else _HEX64
    return matcher.fullmatch(value) is not None


def _target_rows(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    rows: list[dict[str, object]] = []
    for row in value:
        if not isinstance(row, Mapping):
            return ()
        rows.append(dict(row))
    return tuple(rows)


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


def _inventory_content_seal_is_valid(inventory: object) -> bool:
    if not isinstance(inventory, Mapping):
        return False
    refs = inventory.get("refs")
    targets = inventory.get("targetManifest")
    if not isinstance(refs, list) or not refs or _target_rows(targets) != TARGETS:
        return False
    try:
        ref_digest = _canonical_json_sha256(refs)
        target_digest = _canonical_json_sha256(targets)
    except (TypeError, ValueError):
        return False
    return (
        inventory.get("refInventorySha256") == ref_digest
        and inventory.get("targetManifestSha256") == target_digest
    )


def _inventory_seal_is_valid(inventory: object) -> bool:
    return (
        isinstance(inventory, Mapping)
        and inventory.get("repository") == REPOSITORY
        and inventory.get("visibility") == "PRIVATE"
        and inventory.get("defaultBranch") == "main"
        and inventory.get("sourceHead") == BASE_SHA
        and _inventory_content_seal_is_valid(inventory)
    )


def _approval_uuid_body(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if not any(pattern.fullmatch(value) for pattern in _APPROVAL_ID.values()):
        return None
    return value[-36:]


def _validate_approval_records(
    gate: Mapping[str, object], *, expected_id_kind: str
) -> tuple[list[str], str | None]:
    codes: list[str] = []
    approval_id = gate.get("approvalId")
    if (
        not isinstance(approval_id, str)
        or _APPROVAL_ID[expected_id_kind].fullmatch(approval_id) is None
    ):
        codes.append("APPROVAL_ID_INVALID")

    owner = gate.get("ownerApproval")
    security = gate.get("securityPrivacyApproval")
    if not (
        isinstance(owner, Mapping)
        and owner.get("name") == OWNER_APPROVER
        and owner.get("role") == "repository-owner"
        and owner.get("decision") == "APPROVE"
        and isinstance(security, Mapping)
        and isinstance(security.get("name"), str)
        and bool(security.get("name", "").strip())
        and security.get("role") == "security-privacy"
        and security.get("decision") == "APPROVE"
    ):
        codes.append("NAMED_APPROVERS_REQUIRED")
    if not (
        isinstance(owner, Mapping)
        and _is_hex(owner.get("approvalRecordSha256"), 64)
        and isinstance(security, Mapping)
        and _is_hex(security.get("approvalRecordSha256"), 64)
    ):
        codes.append("APPROVAL_RECORD_REQUIRED")
    security_name = (
        security.get("name")
        if isinstance(security, Mapping) and isinstance(security.get("name"), str)
        else None
    )
    return codes, security_name


def _validate_approval_registry(
    registry: object,
    *,
    authoritative_sha256: str | None,
) -> tuple[list[str], set[str]]:
    codes: list[str] = []
    row = registry if isinstance(registry, Mapping) else {}
    consumed = row.get("consumedApprovalIds")
    consumed_uuids = (
        [_approval_uuid_body(value) for value in consumed]
        if isinstance(consumed, list)
        else []
    )
    consumed_is_valid_list = (
        isinstance(consumed, list)
        and all(value is not None for value in consumed_uuids)
    )
    if (
        row.get("schemaVersion") != APPROVAL_REGISTRY_SCHEMA
        or not consumed_is_valid_list
        or (
            consumed_is_valid_list
            and len(consumed_uuids) != len(set(consumed_uuids))
        )
    ):
        codes.append("APPROVAL_REGISTRY_INVALID")
        consumed_ids: set[str] = set()
    else:
        consumed_ids = set(consumed_uuids)
    payload = {
        "schemaVersion": row.get("schemaVersion"),
        "consumedApprovalIds": consumed if isinstance(consumed, list) else [],
    }
    observed_digest = row.get("registrySha256")
    if (
        not _is_hex(observed_digest, 64)
        or observed_digest != _canonical_json_sha256(payload)
        or not _is_hex(authoritative_sha256, 64)
        or observed_digest != authoritative_sha256
    ):
        codes.append("APPROVAL_REGISTRY_MISMATCH")
    return codes, consumed_ids


def validate_target_manifest(targets: object) -> dict[str, Any]:
    """Require the exact two content-addressed objects approved for removal."""

    rows = _target_rows(targets)
    codes: list[str] = []
    if rows != TARGETS:
        codes.append("TARGET_MANIFEST_MISMATCH")
    for row in rows:
        path = row.get("path")
        if (
            not isinstance(path, str)
            or PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or any(character in path for character in "*?[]")
        ):
            codes.append("UNSAFE_TARGET_PATH")
        if not _is_hex(row.get("blob"), 40) or not isinstance(row.get("size"), int):
            codes.append("INVALID_TARGET_IDENTITY")
    return _result(codes, targets=copy.deepcopy(rows))


def validate_authorizations(
    authorizations: object,
    *,
    authoritative_commit_map_sha256: str | None = None,
    authoritative_ref_map_sha256: str | None = None,
    authoritative_inventory: object = None,
    authoritative_approval_registry_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate the two independent approvals without granting visibility."""

    rewrite_codes: list[str] = []
    force_codes: list[str] = []
    document = authorizations if isinstance(authorizations, Mapping) else {}
    rewrite = document.get("rewrite")
    force = document.get("forceUpdate")
    visibility = document.get("visibility")

    rewrite_is_mapping = isinstance(rewrite, Mapping)
    rewrite_approved = rewrite.get("approved") if rewrite_is_mapping else None
    if rewrite_is_mapping and rewrite_approved is not True and rewrite_approved is not False:
        rewrite_codes.append("APPROVAL_BOOLEAN_REQUIRED")
    if not rewrite_is_mapping or rewrite_approved is not True:
        rewrite_codes.append("REWRITE_APPROVAL_REQUIRED")
        if not rewrite_is_mapping:
            rewrite = {}
    force_is_mapping = isinstance(force, Mapping)
    force_approved = force.get("approved") if force_is_mapping else None
    if force_is_mapping and force_approved is not True and force_approved is not False:
        force_codes.append("APPROVAL_BOOLEAN_REQUIRED")
    force_present = force_is_mapping and force_approved is True
    if not force_present:
        if not force_is_mapping:
            force = {}
    rewrite_id = rewrite.get("approvalId")
    force_id = force.get("approvalId")
    record_codes, rewrite_security_name = _validate_approval_records(
        rewrite,
        expected_id_kind="rewrite",
    )
    rewrite_codes.extend(record_codes)
    force_security_name: str | None = None
    if force_present:
        record_codes, force_security_name = _validate_approval_records(
            force,
            expected_id_kind="force",
        )
        force_codes.extend(record_codes)
    if force_present:
        rewrite_uuid = _approval_uuid_body(rewrite_id)
        force_uuid = _approval_uuid_body(force_id)
        rewrite_records = {
            row.get("approvalRecordSha256")
            for row in (
                rewrite.get("ownerApproval"),
                rewrite.get("securityPrivacyApproval"),
            )
            if isinstance(row, Mapping)
        }
        force_records = {
            row.get("approvalRecordSha256")
            for row in (
                force.get("ownerApproval"),
                force.get("securityPrivacyApproval"),
            )
            if isinstance(row, Mapping)
        }
        if (
            rewrite_id == force_id
            or rewrite_uuid == force_uuid
            or bool(rewrite_records.intersection(force_records))
        ):
            force_codes.append("DISTINCT_FORCE_APPROVAL_REQUIRED")
    if force_present and rewrite_security_name != force_security_name:
        force_codes.append("SECURITY_APPROVER_MISMATCH")
    if rewrite.get("action") != "rewrite-local-mirror":
        rewrite_codes.append("REWRITE_APPROVAL_SCOPE_MISMATCH")
    if rewrite.get("sourceHead") != BASE_SHA:
        rewrite_codes.append("APPROVAL_HEAD_MISMATCH")
    if not _is_hex(rewrite.get("refInventorySha256"), 64) or not _is_hex(
        rewrite.get("targetManifestSha256"), 64
    ):
        rewrite_codes.append("APPROVAL_SEAL_MISSING")
    inventory = authoritative_inventory if isinstance(authoritative_inventory, Mapping) else {}
    if not inventory:
        rewrite_codes.append("APPROVAL_INVENTORY_AUTHORITY_REQUIRED")
    else:
        if not _inventory_seal_is_valid(inventory):
            rewrite_codes.append("APPROVAL_INPUT_SEAL_MISMATCH")
        if (
            rewrite.get("refInventorySha256")
            != inventory.get("refInventorySha256")
            or rewrite.get("targetManifestSha256")
            != inventory.get("targetManifestSha256")
        ):
            rewrite_codes.append("APPROVAL_INPUT_SEAL_MISMATCH")
        rewrite_ref_result = validate_rewrite_refs(
            rewrite.get("approvedRefs"), inventory
        )
        if rewrite_ref_result["verdict"] != "PASS":
            rewrite_codes.append("UNSAFE_REF_SCOPE")
    if force_present:
        if force.get("action") != "atomic-force-with-lease":
            force_codes.append("FORCE_APPROVAL_SCOPE_MISMATCH")
        if force.get("sourceHead") != BASE_SHA:
            force_codes.append("APPROVAL_HEAD_MISMATCH")
        if rewrite.get("approvedRefs") != force.get("approvedRefs"):
            force_codes.append("APPROVED_REF_SCOPE_MISMATCH")
        if not inventory or validate_rewrite_refs(
            force.get("approvedRefs"), inventory
        )["verdict"] != "PASS":
            force_codes.append("UNSAFE_REF_SCOPE")
        if (
            not _is_hex(force.get("commitMapSha256"), 64)
            or not _is_hex(force.get("refMapSha256"), 64)
            or force.get("commitMapSha256") != authoritative_commit_map_sha256
            or force.get("refMapSha256") != authoritative_ref_map_sha256
        ):
            force_codes.append("FORCE_MAP_AUTHORITY_MISMATCH")
    registry_codes, consumed_ids = _validate_approval_registry(
        document.get("approvalRegistry"),
        authoritative_sha256=authoritative_approval_registry_sha256,
    )
    rewrite_codes.extend(registry_codes)
    rewrite_uuid = _approval_uuid_body(rewrite_id)
    force_uuid = _approval_uuid_body(force_id)
    if rewrite_uuid in consumed_ids or (
        force_present and force_uuid in consumed_ids
    ):
        rewrite_codes.append("APPROVAL_ALREADY_CONSUMED")
    if isinstance(visibility, Mapping) and (
        visibility.get("approved") is not False
        or visibility.get("action") != "remain-private"
    ):
        rewrite_codes.append("VISIBILITY_CHANGE_NOT_IN_SCOPE")
    rewrite_authorized = not rewrite_codes
    push_authorized = rewrite_authorized and force_present and not force_codes
    codes = rewrite_codes + force_codes
    if rewrite_authorized and not force_present and not force_codes:
        codes.append("FORCE_UPDATE_APPROVAL_PENDING")
        verdict = "PASS_FOR_LOCAL_MIRROR"
    elif push_authorized:
        verdict = "PASS"
    else:
        verdict = "BLOCKED"
    return _result(
        codes,
        verdict=verdict,
        rewriteAuthorized=rewrite_authorized,
        pushAuthorized=push_authorized,
        visibilityChangeAuthorized=False,
    )


def validate_operations(
    operations: object,
    *,
    authorizations: object,
    authoritative_commit_map_sha256: str | None = None,
    authoritative_ref_map_sha256: str | None = None,
    planned_inventory: object = None,
    authoritative_inventory: object = None,
    authoritative_ref_inventory_sha256: str | None = None,
    authoritative_target_manifest_sha256: str | None = None,
    authoritative_approval_registry_sha256: str | None = None,
) -> dict[str, Any]:
    """Classify an invocation; the unauthorised/default path never mutates."""

    allowed_non_mutating = {"inventory", "render-local-plan", "validate", "audit"}
    allowed_mutating = {"rewrite-local-mirror"}
    rows = operations if isinstance(operations, Sequence) else []
    requested = [
        row.get("kind")
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("kind"), str)
    ]
    unknown = [
        kind for kind in requested if kind not in allowed_non_mutating | allowed_mutating
    ]
    mutation_operations = [kind for kind in requested if kind in allowed_mutating]
    codes: list[str] = []
    if unknown:
        codes.append("UNKNOWN_OR_FORBIDDEN_OPERATION")
        mutation_operations = []
    if mutation_operations:
        if not isinstance(planned_inventory, Mapping) or not isinstance(
            authoritative_inventory, Mapping
        ):
            auth = _result(
                ["APPROVAL_INPUT_SEAL_MISMATCH"],
                verdict="BLOCKED",
                rewriteAuthorized=False,
                pushAuthorized=False,
            )
        elif (
            not _is_hex(authoritative_ref_inventory_sha256, 64)
            or not _is_hex(authoritative_target_manifest_sha256, 64)
            or not _inventory_content_seal_is_valid(authoritative_inventory)
            or authoritative_inventory.get("refInventorySha256")
            != authoritative_ref_inventory_sha256
            or authoritative_inventory.get("targetManifestSha256")
            != authoritative_target_manifest_sha256
        ):
            auth = _result(
                ["AUTHORITATIVE_SEAL_MISMATCH"],
                verdict="BLOCKED",
                rewriteAuthorized=False,
                pushAuthorized=False,
            )
        elif (
            planned_inventory.get("repository")
            == authoritative_inventory.get("repository")
            and planned_inventory.get("sourceHead")
            == authoritative_inventory.get("sourceHead")
            and planned_inventory.get("refInventorySha256")
            == authoritative_inventory.get("refInventorySha256")
            and planned_inventory.get("targetManifestSha256")
            == authoritative_inventory.get("targetManifestSha256")
            and planned_inventory.get("refs") == authoritative_inventory.get("refs")
            and not _inventory_seal_is_valid(authoritative_inventory)
        ):
            auth = _result(
                ["AUTHORITATIVE_SEAL_MISMATCH"],
                verdict="BLOCKED",
                rewriteAuthorized=False,
                pushAuthorized=False,
            )
        else:
            auth = validate_preflight(
                authorizations,
                planned_inventory=planned_inventory,
                authoritative_inventory=authoritative_inventory,
                authoritative_approval_registry_sha256=(
                    authoritative_approval_registry_sha256
                ),
            )
    else:
        auth = validate_authorizations(
            authorizations,
            authoritative_commit_map_sha256=authoritative_commit_map_sha256,
            authoritative_ref_map_sha256=authoritative_ref_map_sha256,
            authoritative_inventory=authoritative_inventory,
            authoritative_approval_registry_sha256=(
                authoritative_approval_registry_sha256
            ),
        )
    rewrite_authorized = auth["rewriteAuthorized"] is True
    if not rewrite_authorized or auth["verdict"] in {"BLOCKED", "HEAD_CHANGED", "FAIL"}:
        codes.extend(auth.get("codes", []))
        codes.append("SEPARATE_APPROVALS_REQUIRED")
        # Unauthorised operations are discarded, not returned as runnable work.
        mutation_operations = []
    verdict = auth["verdict"] if rewrite_authorized and not codes else "BLOCKED"
    if auth["verdict"] == "HEAD_CHANGED":
        verdict = "HEAD_CHANGED"
    return _result(
        codes,
        verdict=verdict,
        rewriteAuthorized=rewrite_authorized,
        pushAuthorized=False,
        mutationOperations=mutation_operations,
        planOnly=not rewrite_authorized,
    )


def validate_execution_environment(
    *,
    protected_root: str,
    execution_root: str,
    backup_root: str,
    before: object,
    after: object,
    fresh_bare_mirror: bool,
) -> dict[str, Any]:
    codes: list[str] = []
    protected = Path(protected_root).resolve()
    execution = Path(execution_root).resolve()
    backup = Path(backup_root).resolve()
    if (
        execution == protected
        or protected in execution.parents
        or backup == protected
        or protected in backup.parents
        or execution == backup
        or not fresh_bare_mirror
    ):
        codes.append("UNSAFE_EXECUTION_ROOT")
    if before != after:
        codes.append("PROTECTED_CHECKOUT_CHANGED")
    return _result(codes, protectedCheckoutPreserved=before == after)


def validate_ref_inventory(
    inventory: object, authoritative_refs: object
) -> dict[str, Any]:
    document = inventory if isinstance(inventory, Mapping) else {}
    refs = document.get("refs") if isinstance(document.get("refs"), list) else []
    expected = authoritative_refs if isinstance(authoritative_refs, list) else []
    codes: list[str] = []
    if not refs or not expected:
        codes.append("REF_INVENTORY_EMPTY")
    names: set[str] = set()
    for row in refs:
        if not isinstance(row, Mapping):
            codes.append("MALFORMED_REF")
            continue
        name = row.get("name")
        kind = row.get("kind")
        if kind not in _KNOWN_REF_KINDS:
            codes.append("UNCLASSIFIED_RELEVANT_REF")
        if not isinstance(name, str) or name in names:
            codes.append("DUPLICATE_OR_INVALID_REF")
        else:
            names.add(name)
        if not _is_hex(row.get("target"), 40):
            codes.append("INVALID_REF_TARGET")
    expected_names = {
        row.get("name") for row in expected if isinstance(row, Mapping)
    }
    if names != expected_names:
        codes.append("REF_INVENTORY_NOT_CLOSED")
    counts = {
        "heads": sum(row.get("kind") in {"branch", "protected-branch"} for row in refs if isinstance(row, Mapping)),
        "annotatedTags": sum(row.get("kind") == "annotated-tag" for row in refs if isinstance(row, Mapping)),
        "serverManagedPulls": sum(row.get("kind") == "server-managed-pull" for row in refs if isinstance(row, Mapping)),
    }
    return _result(codes, counts=counts)


def validate_rewrite_refs(approved_refs: object, inventory: object) -> dict[str, Any]:
    document = inventory if isinstance(inventory, Mapping) else {}
    rows = document.get("refs") if isinstance(document.get("refs"), list) else []
    publishable = {
        row.get("name")
        for row in rows
        if isinstance(row, Mapping) and row.get("kind") in _PUBLISHABLE_KINDS
    }
    refs = list(approved_refs) if isinstance(approved_refs, Sequence) and not isinstance(approved_refs, (str, bytes)) else []
    codes: list[str] = []
    refs_are_strings = all(isinstance(name, str) for name in refs)
    ref_set = set(refs) if refs_are_strings else set()
    if not refs or not refs_are_strings or ref_set != publishable or len(refs) != len(ref_set):
        codes.append("UNSAFE_REF_SCOPE")
    for name in refs:
        if (
            not isinstance(name, str)
            or any(symbol in name for symbol in ("*", "?", "[", "]"))
            or name in {"--all", "HEAD"}
            or name.startswith("refs/pull/")
            or name not in publishable
        ):
            codes.append("UNSAFE_REF_SCOPE")
    return _result(codes, approvedRefs=refs)


def validate_pre_rewrite_reachability(
    inventory: object, observations: object
) -> dict[str, Any]:
    document = inventory if isinstance(inventory, Mapping) else {}
    expected_refs = {
        row.get("name")
        for row in document.get("refs", [])
        if isinstance(row, Mapping)
    }
    rows = observations if isinstance(observations, list) else []
    codes: list[str] = []
    if not expected_refs or not rows:
        codes.append("TARGET_REACHABILITY_EMPTY")
    if {
        row.get("ref") for row in rows if isinstance(row, Mapping)
    } != expected_refs:
        codes.append("TARGET_REACHABILITY_INCOMPLETE")
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or row.get("sourceCommit") != SOURCE_COMMIT
            or _target_rows(row.get("targets")) != TARGETS
        ):
            codes.append("TARGET_BASELINE_MISMATCH")
    return _result(codes)


def validate_preflight(
    authorizations: object,
    *,
    planned_inventory: object,
    authoritative_inventory: object,
    authoritative_approval_registry_sha256: str | None = None,
) -> dict[str, Any]:
    planned = planned_inventory if isinstance(planned_inventory, Mapping) else {}
    current = (
        authoritative_inventory if isinstance(authoritative_inventory, Mapping) else {}
    )
    drift = (
        planned.get("repository") != current.get("repository")
        or planned.get("sourceHead") != current.get("sourceHead")
        or planned.get("refInventorySha256") != current.get("refInventorySha256")
        or planned.get("targetManifestSha256")
        != current.get("targetManifestSha256")
        or planned.get("refs") != current.get("refs")
    )
    if drift:
        return _result(
            ["HEAD_CHANGED"],
            verdict="HEAD_CHANGED",
            rewriteAuthorized=False,
            pushAuthorized=False,
        )
    rewrite = (
        authorizations.get("rewrite")
        if isinstance(authorizations, Mapping)
        else None
    )
    if not isinstance(rewrite, Mapping) or (
        rewrite.get("refInventorySha256") != current.get("refInventorySha256")
        or rewrite.get("targetManifestSha256")
        != current.get("targetManifestSha256")
    ):
        return _result(
            ["APPROVAL_INPUT_SEAL_MISMATCH"],
            verdict="BLOCKED",
            rewriteAuthorized=False,
            pushAuthorized=False,
        )
    gate_r = {
        "rewrite": dict(rewrite),
        "approvalRegistry": (
            authorizations.get("approvalRegistry")
            if isinstance(authorizations, Mapping)
            else None
        ),
        "visibility": (
            authorizations.get("visibility")
            if isinstance(authorizations, Mapping)
            else None
        ),
    }
    auth = validate_authorizations(
        gate_r,
        authoritative_inventory=current,
        authoritative_approval_registry_sha256=(
            authoritative_approval_registry_sha256
        ),
    )
    return _result(
        auth.get("codes", []),
        verdict=auth["verdict"],
        rewriteAuthorized=auth["rewriteAuthorized"],
        pushAuthorized=auth["pushAuthorized"],
    )


def validate_backup(backup: object, inventory: object) -> dict[str, Any]:
    row = backup if isinstance(backup, Mapping) else {}
    document = inventory if isinstance(inventory, Mapping) else {}
    expected_refs = {
        ref.get("name")
        for ref in document.get("refs", [])
        if isinstance(ref, Mapping)
    }
    actual_refs = set(row.get("containedRefs", [])) if isinstance(row.get("containedRefs"), list) else set()
    codes: list[str] = []
    path = row.get("path")
    if not isinstance(path, str) or not Path(path).is_absolute():
        codes.append("BACKUP_PATH_INVALID")
    if row.get("locationOutsideRepositories") is not True:
        codes.append("UNSAFE_BACKUP_LOCATION")
    if actual_refs != expected_refs:
        codes.append("BACKUP_INCOMPLETE")
    if (
        row.get("nodeType") != "regular-file"
        or not _is_hex(row.get("sha256"), 64)
        or row.get("bundleVerifyExitCode") != 0
        or row.get("restoredFsckExitCode") != 0
        or row.get("classification") != "restricted-private-pre-rewrite"
        or row.get("publiclyPublishable") is not False
        or row.get("createdBeforeRewrite") is not True
    ):
        codes.append("BACKUP_NOT_RECOVERABLE_OR_PRIVATE")
    custodians = row.get("custodians")
    if (
        row.get("directoryMode") != "0700"
        or row.get("fileMode") != "0600"
        or row.get("encrypted") is not True
        or row.get("accessLogEnabled") is not True
        or not isinstance(custodians, list)
        or len(custodians) < 2
        or len(set(custodians)) != len(custodians)
        or not all(isinstance(value, str) and value.strip() for value in custodians)
        or not isinstance(row.get("destructionAt"), str)
    ):
        codes.append("BACKUP_GOVERNANCE_INCOMPLETE")
    return _result(codes)


def render_local_rewrite_argv(plan: object) -> list[str]:
    """Render but never execute the exact local-mirror rewrite command."""

    row = plan if isinstance(plan, Mapping) else {}
    if (
        row.get("tool") != "git-filter-repo"
        or row.get("toolVersion") != FILTER_REPO_VERSION
        or row.get("freshMirror") is not True
        or row.get("sensitiveDataRemoval") is not True
        or row.get("invertPaths") is not True
        or list(row.get("targetPaths", [])) != [target["path"] for target in TARGETS]
    ):
        raise ValueError("rewrite plan is not exact, pinned, and mirror-scoped")
    argv = [
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
    ]
    for path in row["targetPaths"]:
        argv.extend(("--path", path))
    return argv


def validate_rewrite_mirror(mirror: object) -> dict[str, Any]:
    row = mirror if isinstance(mirror, Mapping) else {}
    codes: list[str] = []
    if row.get("fresh") is not True:
        codes.append("FRESH_MIRROR_REQUIRED")
    if (
        row.get("bare") is not True
        or row.get("repository") != REPOSITORY
        or row.get("visibility") != "PRIVATE"
        or row.get("sourceHead") != BASE_SHA
        or row.get("hasLocalWork") is not False
    ):
        codes.append("PRIVATE_MIRROR_CONTRACT_MISMATCH")
    if (
        row.get("cloneProof") != "fresh-network-mirror"
        or row.get("origin") != "git@github.com:rajeevbarnwal/NyayOne.git"
        or row.get("remoteOriginMirror") is not True
    ):
        codes.append("MIRROR_ORIGIN_IDENTITY_MISMATCH")
    if (
        not _is_hex(row.get("refInventorySha256"), 64)
        or row.get("refInventorySha256")
        != row.get("authoritativeRefInventorySha256")
    ):
        codes.append("MIRROR_REF_INVENTORY_MISMATCH")
    if (
        row.get("writableProductionRemote") is not False
        or row.get("pushDisabled") is not True
        or row.get("pushUrl") != "disabled://nyay21-local-mirror"
    ):
        codes.append("WRITABLE_PRODUCTION_REMOTE_FORBIDDEN")
    return _result(codes)


def validate_retention_boundary(
    before: object, after: object, *, allowedPruned: object
) -> dict[str, Any]:
    prior = before if isinstance(before, Mapping) else {}
    current = after if isinstance(after, Mapping) else {}
    codes: list[str] = []
    if current.get("targetBlobs") not in ([], ()):
        codes.append("TARGET_RETENTION_REMAINS")
    for key in (
        "nonTargetObjects",
        "unrelatedFiles",
        "topologyDigest",
        "nonSignatureMetadataDigest",
        "signatureManifestSha256",
    ):
        if prior.get(key) != current.get(key):
            codes.append("REWRITE_SCOPE_DRIFT")
    if (
        prior.get("signedCommitCount") != 31
        or current.get("signedCommitCount") != 0
        or current.get("signatureDisposition")
        != "git-filter-repo-stripped-31-gpg-signatures-with-sealed-old-object-map"
        or current.get("unexpectedMetadataChanges") != []
    ):
        codes.append("SIGNATURE_DISPOSITION_MISMATCH")
    if list(allowedPruned) != [DELETION_COMMIT]:
        codes.append("UNAPPROVED_PRUNED_COMMIT")
    return _result(codes)


def validate_commit_map(
    rows: object,
    *,
    expectedReachableCount: int,
    expectedAffectedCount: int,
    requiredOldShas: object,
) -> dict[str, Any]:
    mappings = rows if isinstance(rows, list) else []
    codes: list[str] = []
    if not mappings:
        codes.append("COMMIT_MAP_EMPTY")
    if len(mappings) != expectedReachableCount:
        codes.append("COMMIT_MAP_INCOMPLETE")
    by_old: dict[str, str] = {}
    affected = 0
    for row in mappings:
        if not isinstance(row, Mapping):
            codes.append("COMMIT_MAP_MALFORMED")
            continue
        old, new, disposition = row.get("old"), row.get("new"), row.get("disposition")
        if not _is_hex(old, 40) or not _is_hex(new, 40) or old in by_old:
            codes.append("COMMIT_MAP_MALFORMED")
            continue
        by_old[old] = new
        if disposition in {"rewritten", "pruned-empty"}:
            affected += 1
        if disposition == "pruned-empty" and new != "0" * 40:
            codes.append("PRUNED_COMMIT_NOT_NULL")
        elif disposition == "unchanged" and old != new:
            codes.append("UNCHANGED_COMMIT_DRIFT")
        elif disposition not in {"rewritten", "pruned-empty", "unchanged"}:
            codes.append("COMMIT_DISPOSITION_INVALID")
    if affected != expectedAffectedCount:
        codes.append("AFFECTED_COMMIT_COUNT_MISMATCH")
    if not set(requiredOldShas).issubset(by_old):
        codes.append("REQUIRED_SHA_MAPPING_MISSING")
    return _result(codes, mapping=by_old)


def validate_ref_map(
    rows: object, inventory: object, approved_refs: object
) -> dict[str, Any]:
    mappings = rows if isinstance(rows, list) else []
    document = inventory if isinstance(inventory, Mapping) else {}
    approved = list(approved_refs) if isinstance(approved_refs, Sequence) else []
    inventory_by_name = {
        row.get("name"): row
        for row in document.get("refs", [])
        if isinstance(row, Mapping)
    }
    codes: list[str] = []
    if not mappings or not approved or not inventory_by_name:
        codes.append("REF_MAP_EMPTY")
    by_name = {
        row.get("ref"): row for row in mappings if isinstance(row, Mapping)
    }
    if set(by_name) != set(approved) or len(mappings) != len(approved):
        codes.append("REF_MAP_INCOMPLETE")
    for name, row in by_name.items():
        source = inventory_by_name.get(name)
        if (
            source is None
            or row.get("old") != source.get("target")
            or row.get("kind") != source.get("kind")
            or not _is_hex(row.get("new"), 40)
        ):
            codes.append("REF_MAP_IDENTITY_MISMATCH")
    return _result(codes)


def verify_purge_reachability(audit: object, inventory: object) -> dict[str, Any]:
    row = audit if isinstance(audit, Mapping) else {}
    expected_refs = {
        ref.get("name")
        for ref in (
            inventory.get("refs", []) if isinstance(inventory, Mapping) else []
        )
        if isinstance(ref, Mapping) and ref.get("kind") != "symbolic-head"
    }
    codes: list[str] = []
    if set(row.get("scannedRefs", [])) != expected_refs:
        codes.append("POST_REWRITE_REF_SCAN_INCOMPLETE")
    target_blobs = {target["blob"] for target in TARGETS}
    target_paths = {target["path"] for target in TARGETS}
    if target_blobs.intersection(row.get("reachableObjects", [])):
        codes.append("TARGET_BLOB_STILL_REACHABLE")
    reachable_by_ref = row.get("reachableByRef")
    if not isinstance(reachable_by_ref, Mapping) or set(reachable_by_ref) != expected_refs:
        codes.append("POST_REWRITE_REF_SCAN_INCOMPLETE")
    elif any(
        target_blobs.intersection(objects)
        for objects in reachable_by_ref.values()
        if isinstance(objects, Sequence) and not isinstance(objects, (str, bytes))
    ):
        codes.append("TARGET_BLOB_STILL_REACHABLE")
    if target_paths.intersection(row.get("historicalPaths", [])):
        codes.append("TARGET_PATH_STILL_REACHABLE")
    if target_blobs.intersection(row.get("reflogTargetObjects", [])):
        codes.append("TARGET_BLOB_STILL_REACHABLE")
    if row.get("internalRetentionRefs"):
        codes.append("INTERNAL_RETENTION_REF_REMAINS")
    return _result(codes)


def validate_seeded_history_canary(observations: object) -> dict[str, Any]:
    expected = {"side-branch", "annotated-tag", "second-parent"}
    rows = observations if isinstance(observations, list) else []
    seen = {
        row.get("location")
        for row in rows
        if isinstance(row, Mapping)
        and row.get("detected") is True
        and row.get("blob") in {target["blob"] for target in TARGETS}
    }
    codes = [] if seen == expected else ["SEEDED_HISTORY_CANARY_MISSED"]
    return _result(codes, detectedLocations=sorted(seen))


def validate_residual_retention(retention: object) -> dict[str, Any]:
    row = retention if isinstance(retention, Mapping) else {}
    codes: list[str] = []
    pulls = row.get("serverManagedPullRefs")
    if (
        isinstance(pulls, Mapping)
        and pulls.get("count", 0) > 0
        and pulls.get("targetReachable") is True
        and pulls.get("remediated") is not True
    ):
        codes.append("SERVER_MANAGED_REF_STILL_REACHABLE")
    caches = row.get("githubCaches")
    if isinstance(caches, Mapping) and caches.get("confirmation") != "expired-or-purged":
        codes.append("HOST_CACHE_RETENTION_UNRESOLVED")
    backup = row.get("backup")
    if not (
        isinstance(backup, Mapping)
        and backup.get("restricted") is True
        and backup.get("outsidePublishableRefs") is True
    ):
        codes.append("BACKUP_GOVERNANCE_UNRESOLVED")
    return _result(
        codes,
        verdict="BLOCKED" if codes else "PASS",
        publicVisibilityEligible=False,
    )


def render_force_update_commands(
    mapping: object, approved_refs: object
) -> list[str]:
    """Render exact lease-bound commands; never call a subprocess or remote."""

    rows = mapping if isinstance(mapping, Mapping) else {}
    refs = list(approved_refs) if isinstance(approved_refs, Sequence) else []
    if not rows or not refs:
        raise ValueError("force-update plan requires a non-empty exact ref mapping")
    if set(rows) != set(refs) or len(refs) != len(set(refs)):
        raise ValueError("force-update map must exactly equal the approved ref set")
    leases: list[str] = []
    refspecs: list[str] = []
    for name in refs:
        entry = rows.get(name)
        if (
            not isinstance(name, str)
            or name in {"HEAD", "--all"}
            or name.startswith("refs/pull/")
            or any(symbol in name for symbol in "*?[]")
            or not isinstance(entry, Mapping)
            or not _is_hex(entry.get("old"), 40)
            or not _is_hex(entry.get("new"), 40)
        ):
            raise ValueError("unsafe force-update ref mapping")
        leases.append(f"--force-with-lease={name}:{entry['old']}")
        refspecs.append(f"{entry['new']}:{name}")
    return [" ".join(("git", "push", "--atomic", *leases, "origin", *refspecs))]


def validate_ruleset_restoration(before: object, after: object) -> dict[str, Any]:
    prior = before if isinstance(before, Mapping) else {}
    current = after if isinstance(after, Mapping) else {}
    codes: list[str] = []
    if prior != current:
        codes.append("PROTECTION_NOT_RESTORED")
    prior_checks = set(prior.get("requiredChecks", []))
    current_checks = set(current.get("requiredChecks", []))
    if (
        current.get("requiredChecksStrict") is not True
        or current_checks != prior_checks
        or current.get("enforcement") != "active"
    ):
        codes.append("ORACLE_WEAKENED")
    return _result(codes)


def validate_collaborator_recovery(plan: object) -> dict[str, Any]:
    row = plan if isinstance(plan, Mapping) else {}
    methods = set(row.get("methods", []))
    forbidden = set(row.get("forbidden", []))
    dangerous = {"merge-old-history", "rebase-old-history", "cherry-pick-old-history"}
    codes: list[str] = []
    if not {"reclone", "fetch-and-reset-to-exact-new-tip"}.issubset(methods):
        codes.append("COLLABORATOR_RECOVERY_INCOMPLETE")
    if methods.intersection(dangerous) or not dangerous.issubset(forbidden):
        codes.append("OLD_HISTORY_REINTRODUCTION_RISK")
    if row.get("acknowledgementsRequired") is not True:
        codes.append("COLLABORATOR_ACKNOWLEDGEMENT_MISSING")
    return _result(codes)


def validate_exact_head_inventory(
    bindings: object, invalidated_shas: object
) -> dict[str, Any]:
    rows = bindings if isinstance(bindings, list) else []
    known = set(invalidated_shas) if isinstance(invalidated_shas, Sequence) else set()
    codes: list[str] = []
    systems = set()
    for row in rows:
        if not isinstance(row, Mapping):
            codes.append("EXACT_HEAD_BINDING_MALFORMED")
            continue
        sha = row.get("sha")
        systems.add(row.get("system"))
        if row.get("kind") != "git-commit" or not _is_hex(sha, 40):
            codes.append("DIGEST_IS_NOT_COMMIT_IDENTITY")
        elif sha not in known:
            codes.append("DIGEST_IS_NOT_COMMIT_IDENTITY")
    if not {"qa", "docs", "code", "jira", "github", "manifest"}.issubset(systems):
        codes.append("EXACT_HEAD_BINDING_INVENTORY_INCOMPLETE")
    return _result(codes)


def validate_evidence_rebinding(old: object, rebound: object) -> dict[str, Any]:
    prior = old if isinstance(old, Mapping) else {}
    current = rebound if isinstance(rebound, Mapping) else {}
    codes: list[str] = []
    if (
        prior.get("status") != "historical-invalidated-by-history-rewrite"
        or current.get("oldSha") != prior.get("testedHead")
        or current.get("sourceArtifactSha256") != prior.get("artifactSha256")
        or not _is_hex(current.get("testedHead"), 40)
        or not _is_hex(current.get("commitMapSha256"), 64)
    ):
        codes.append("EVIDENCE_REBINDING_IDENTITY_MISMATCH")
    if current.get("evidenceId") == prior.get("evidenceId"):
        codes.append("SILENT_EVIDENCE_RELABEL")
    if (
        current.get("executedAssertions", 0) <= 0
        or current.get("rawArtifacts", 0) <= 0
        or current.get("rerunAfterRewrite") is not True
    ):
        codes.append("EVIDENCE_RERUN_MISSING")
    return _result(codes)


def validate_gate_readbacks(gates: object, expected_head: str) -> dict[str, Any]:
    rows = gates if isinstance(gates, list) else []
    codes: list[str] = []
    gate_ids = [
        row.get("id") for row in rows if isinstance(row, Mapping)
    ]
    ids_are_strings = all(isinstance(gate_id, str) for gate_id in gate_ids)
    gate_id_set = set(gate_ids) if ids_are_strings else set()
    if not _is_hex(expected_head, 40):
        codes.append("GATE_READBACK_INVALID_HEAD")
    if (
        len(rows) != len(STRICT_REQUIRED_CHECKS)
        or len(gate_ids) != len(rows)
        or not ids_are_strings
        or len(gate_id_set) != len(gate_ids)
        or gate_id_set != set(STRICT_REQUIRED_CHECKS)
    ):
        codes.append("GATE_READBACK_INCOMPLETE")
    for row in rows:
        if not isinstance(row, Mapping):
            codes.append("GATE_READBACK_MALFORMED")
            continue
        executed = row.get("executed")
        passed = row.get("passed")
        failed = row.get("failed")
        if type(executed) is not int or executed <= 0:
            codes.append("ZERO_ASSERTIONS")
        if row.get("testedHead") != expected_head:
            codes.append("STALE_EXACT_HEAD_EVIDENCE")
        if (
            type(passed) is not int
            or type(failed) is not int
            or passed != executed
            or failed != 0
            or not _is_hex(row.get("oracleDigest"), 64)
        ):
            codes.append("GATE_READBACK_FAILED")
    return _result(codes)


def validate_pre_public_audit(audit: object) -> dict[str, Any]:
    row = audit if isinstance(audit, Mapping) else {}
    codes: list[str] = []
    if (
        row.get("repositoryVisibilityBefore") != "PRIVATE"
        or row.get("repositoryVisibilityAfter") != "PRIVATE"
    ):
        codes.append("VISIBILITY_CHANGED_WITHOUT_APPROVAL")
    if (
        row.get("independent") is not True
        or row.get("historyTargetFindings") != 0
        or row.get("privacyFindings") != 0
        or row.get("unaccountedForks") != 0
        or row.get("unaccountedRetention") != 0
        or row.get("localAndRemoteGatesPassed") is not True
    ):
        codes.append("PRE_PUBLIC_AUDIT_INCOMPLETE")
    if codes:
        verdict = "FAIL"
    else:
        verdict = "READY_FOR_SEPARATE_VISIBILITY_DECISION"
    return _result(
        codes,
        verdict=verdict,
        visibilityChangeAuthorized=False,
        publicVisibilityEligible=False,
    )


__all__ = [
    "SCHEMA_VERSION",
    "REPOSITORY",
    "BASE_SHA",
    "SOURCE_COMMIT",
    "DELETION_COMMIT",
    "FILTER_REPO_VERSION",
    "APPROVAL_REGISTRY_SCHEMA",
    "OWNER_APPROVER",
    "STRICT_REQUIRED_CHECKS",
    "TARGETS",
    "render_force_update_commands",
    "render_local_rewrite_argv",
    "validate_authorizations",
    "validate_backup",
    "validate_collaborator_recovery",
    "validate_commit_map",
    "validate_evidence_rebinding",
    "validate_exact_head_inventory",
    "validate_execution_environment",
    "validate_gate_readbacks",
    "validate_operations",
    "validate_pre_public_audit",
    "validate_pre_rewrite_reachability",
    "validate_preflight",
    "validate_ref_inventory",
    "validate_ref_map",
    "validate_residual_retention",
    "validate_retention_boundary",
    "validate_rewrite_mirror",
    "validate_rewrite_refs",
    "validate_ruleset_restoration",
    "validate_seeded_history_canary",
    "validate_target_manifest",
    "verify_purge_reachability",
]
