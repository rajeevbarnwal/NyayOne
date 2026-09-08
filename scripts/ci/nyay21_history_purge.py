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
BASE_SHA = "454a40784ee2e084d9a756a713f287b627f1c4d4"
SOURCE_COMMIT = "9d6d56cc84b4f3fe9e2b223631f8a5e96c815374"
DELETION_COMMIT = "d58d1fbac48db5a29158ca5b3b168b8951d526d1"
FILTER_REPO_VERSION = "a40bce548d2c"
AUTHORITATIVE_REF_INVENTORY_SHA256 = (
    "292a8bbaeba262de21c700546790e3c2b0e6c55f0174b4f5e9098b125be7edc7"
)
AUTHORITATIVE_PLANNING_SEAL_SHA256 = (
    "2c7f3e20e2b53a7c7b866e6d8b5cd4b87902d3f9eeaede9d56e3dbf3a72b1e71"
)
AUTHORITATIVE_REACHABLE_COMMIT_COUNT = 321
AUTHORITATIVE_AFFECTED_COMMIT_COUNT = 267
AUTHORITATIVE_CHANGED_COMMIT_COUNT = 266
AUTHORITATIVE_PRUNED_COMMIT_COUNT = 1
AUTHORITATIVE_SIGNED_COMMIT_COUNT = 40
AUTHORITATIVE_CONCRETE_REF_COUNT = 42
AUTHORITATIVE_TOTAL_REF_ROWS = 43
RULESET_ID = 20888530
AUTHORITATIVE_RULESET_GET_SHA256 = (
    "8419caa7e36d80182a46550c1af82eaf3ece2b117a4e86e93758328e426e0955"
)
AUTHORITATIVE_RELAXATION_PAYLOAD_SHA256 = (
    "9230f337f15f57ddb28f17dc24076441a9649d0994e015584d80b514997bc3cc"
)
AUTHORITATIVE_RESTORATION_PAYLOAD_SHA256 = (
    "bf1f82decd5e5276475a84ef42b26f0be67c908186195b00669f21158a0c0711"
)
APPROVAL_REGISTRY_SCHEMA = "nyay21-approval-consumption/v1"
OWNER_APPROVER = "Rajeev Barnwal"
SECURITY_PRIVACY_APPROVER = "Claude Code"
EXECUTION_SCHEMA_VERSION = "nyay21-execution/v2"
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
_SAFE_PUBLISHABLE_REF = re.compile(r"^refs/(?:heads|tags)/[A-Za-z0-9][A-Za-z0-9._/-]*$")
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


def _is_nonzero_hex40(value: object) -> bool:
    return _is_hex(value, 40) and value != "0" * 40


def _is_safe_publishable_ref_name(value: object) -> bool:
    if not isinstance(value, str) or _SAFE_PUBLISHABLE_REF.fullmatch(value) is None:
        return False
    suffix = value.removeprefix("refs/heads/").removeprefix("refs/tags/")
    components = suffix.split("/")
    return not (
        ".." in value
        or "@{" in value
        or "//" in value
        or value.endswith(("/", "."))
        or any(
            not component
            or component.startswith(".")
            or component.endswith(".lock")
            for component in components
        )
    )


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


# Execution/v2 accepts fresh observations, never a replacement historical seal.
# All results remain planning-only; caller-supplied claims are not live approvals.
def _execution_result(codes=(), **values):
    result = _result(codes, **values)
    if 'HEAD_CHANGED' in result['codes']:
        result['verdict'] = 'HEAD_CHANGED'
    result['executionAuthorized'] = False
    return result


def _execution_int(value, minimum=0, maximum=2**63 - 1):
    return type(value) is int and minimum <= value <= maximum


def _execution_refs(rows):
    if not isinstance(rows, list) or not rows:
        return None
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'name', 'oid'}
                or not _is_safe_publishable_ref_name(row['name'])
                or not _is_nonzero_hex40(row['oid']) or row['name'] in seen):
            return None
        seen.add(row['name'])
    return sorted(copy.deepcopy(rows), key=lambda row: row['name'])


def capture_execution_seal(observe, *, policy, now):
    """Seal two equal readbacks from an injected read-only collector; never execute.

    A production collector must authenticate/verify raw Git observations. This
    pure boundary does not turn a caller's `complete` claim into remote evidence.
    """
    if not callable(observe) or not isinstance(policy, dict) or not _execution_int(now):
        return _execution_result(['OBSERVATION_INVALID'])
    if (policy.get('schemaVersion') != EXECUTION_SCHEMA_VERSION
            or policy.get('repository') != REPOSITORY or policy.get('visibility') != 'PRIVATE'
            or policy.get('defaultBranch') != 'main'
            or policy.get('targetManifest') != list(TARGETS)
            or policy.get('filterRepoVersion') != FILTER_REPO_VERSION
            or not _execution_int(policy.get('maxSnapshotAgeSeconds'), 1, 300)):
        return _execution_result(['EXECUTION_POLICY_INVALID'])
    try:
        snapshots = [copy.deepcopy(observe()), copy.deepcopy(observe())]
    except Exception:
        return _execution_result(['OBSERVATION_UNAVAILABLE'])
    normalized = []
    for raw in snapshots:
        if not isinstance(raw, dict):
            return _execution_result(['OBSERVATION_INVALID'])
        if (raw.get('repository') != REPOSITORY or raw.get('visibility') != 'PRIVATE'
                or raw.get('defaultBranch') != 'main'):
            return _execution_result(['REPOSITORY_SCOPE_MISMATCH'])
        targets = raw.get('targets')
        if (not _execution_int(raw.get('exitCode')) or not isinstance(targets, list)
                or any(not isinstance(t, dict) or not _execution_int(t.get('size'), 1) for t in targets)):
            return _execution_result(['STRICT_INTEGER_REQUIRED'])
        if targets != list(TARGETS):
            return _execution_result(['TARGET_MANIFEST_MISMATCH'])
        refs = _execution_refs(raw.get('refs'))
        if raw.get('complete') is not True or raw['exitCode'] != 0 or refs is None:
            return _execution_result(['REF_INVENTORY_INVALID'])
        commits = raw.get('commits')
        if (not isinstance(commits, list) or not commits
                or any(not isinstance(c, dict) or set(c) != {'oid', 'signed'}
                       or not _is_nonzero_hex40(c['oid']) or type(c['signed']) is not bool for c in commits)
                or len({c['oid'] for c in commits}) != len(commits)
                or not _is_hex(raw.get('rulesetGetSha256'), 64)
                or not _is_nonzero_hex40(raw.get('head'))
                or not any(r == {'name': 'refs/heads/main', 'oid': raw['head']} for r in refs)
                or raw['head'] not in {c['oid'] for c in commits}):
            return _execution_result(['OBSERVATION_INVALID'])
        normalized.append({**raw, 'refs': refs, 'commits': sorted(commits, key=lambda c: c['oid'])})
    if normalized[0] != normalized[1]:
        return _execution_result(['HEAD_CHANGED'])
    raw = normalized[0]
    seal = {'schemaVersion': EXECUTION_SCHEMA_VERSION, 'repository': REPOSITORY,
            'sourceHead': raw['head'], 'refs': raw['refs'],
            'refInventorySha256': _canonical_json_sha256(raw['refs']),
            'targetManifestSha256': _canonical_json_sha256(raw['targets']),
            'rulesetGetSha256': raw['rulesetGetSha256'],
            'observationSha256': _canonical_json_sha256(raw),
            'capturedAt': now, 'expiresAt': now + policy['maxSnapshotAgeSeconds'],
            'policySha256': _canonical_json_sha256(policy),
            'reachableCommitCount': len(raw['commits']),
            'signedCommitCount': sum(c['signed'] for c in raw['commits'])}
    return _execution_result(seal=seal, sealSha256=_canonical_json_sha256(seal))


def _execution_seal_valid(seal):
    if not isinstance(seal, dict):
        return False
    refs = _execution_refs(seal.get('refs'))
    return (seal.get('schemaVersion') == EXECUTION_SCHEMA_VERSION
            and seal.get('repository') == REPOSITORY
            and _is_nonzero_hex40(seal.get('sourceHead')) and refs is not None
            and any(r == {'name': 'refs/heads/main', 'oid': seal['sourceHead']} for r in refs)
            and seal.get('refInventorySha256') == _canonical_json_sha256(refs)
            and seal.get('targetManifestSha256') == _canonical_json_sha256(list(TARGETS))
            and all(_is_hex(seal.get(k), 64) for k in ('rulesetGetSha256','observationSha256','policySha256'))
            and _execution_int(seal.get('capturedAt')) and _execution_int(seal.get('expiresAt'))
            and all(_execution_int(seal[k]) for k in ('reachableCommitCount', 'signedCommitCount') if k in seal)
            and 0 < seal['expiresAt'] - seal['capturedAt'] <= 300)


def _execution_authority_unchanged(seal, current):
    if not _execution_seal_valid(current):
        return False
    # Re-observation time is not an authority change. The original signed seal
    # and its expiry remain binding; only compare independently observed truth.
    volatile = {'capturedAt', 'expiresAt'}
    return ({k: v for k, v in seal.items() if k not in volatile}
            == {k: v for k, v in current.items() if k not in volatile})


def validate_execution_approvals(records, *, seal, current, now):
    """Validate declared bindings only; execution still needs authenticated registry proof."""
    if not _execution_seal_valid(seal) or not _execution_int(now):
        return _execution_result(['EXECUTION_SEAL_INVALID'])
    if not _execution_authority_unchanged(seal, current):
        return _execution_result(['HEAD_CHANGED'])
    if not isinstance(records, dict) or set(records) != {'rewrite', 'forceUpdate'}:
        return _execution_result(['DISTINCT_FORCE_APPROVAL_REQUIRED'])
    codes = []
    ids = []
    for kind, action in (('rewrite', 'rewrite'), ('forceUpdate', 'force-update')):
        row = records[kind]
        if not isinstance(row, dict):
            return _execution_result(['APPROVAL_INVALID'])
        if row.get('action') != action:
            codes.append('DISTINCT_FORCE_APPROVAL_REQUIRED')
        if row.get('approved') is not True:
            codes.append('APPROVAL_BOOLEAN_REQUIRED')
        approval_id = row.get('id')
        if not isinstance(approval_id, str) or re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', approval_id) is None:
            codes.append('APPROVAL_INVALID')
        if isinstance(approval_id, str):
            ids.append(approval_id)
        if row.get('sealSha256') != _canonical_json_sha256(seal) or row.get('sourceHead') != seal['sourceHead']:
            codes.append('APPROVAL_SEAL_MISMATCH')
        if row.get('approvedRefs') != [r['name'] for r in seal['refs']]:
            codes.append('APPROVAL_REF_SCOPE_MISMATCH')
        if (row.get('consumed') is not False or not _execution_int(row.get('expiresAt'))
                or not seal['capturedAt'] <= now < min(row['expiresAt'], seal['expiresAt'])):
            codes.append('APPROVAL_NOT_CURRENT')
        for role, identity, label in (('owner', OWNER_APPROVER, 'owner'),
                                      ('security', SECURITY_PRIVACY_APPROVER, 'technical-approver')):
            proof = row.get(role)
            if (not isinstance(proof, dict) or proof.get('identity') != identity
                    or proof.get('role') != label or proof.get('verified') is not True):
                codes.append('APPROVAL_ROLE_MISMATCH')
    if len(set(ids)) != 2:
        codes.append('DISTINCT_FORCE_APPROVAL_REQUIRED')
    return _execution_result(codes, rewriteApproved=not codes, forceUpdateApproved=not codes)


def plan_execution_leases(rows, *, seal, current):
    """Render a dry-run only; no force-update command or push authority is emitted."""
    if not _execution_seal_valid(seal):
        return _execution_result(['EXECUTION_SEAL_INVALID'])
    if not _execution_authority_unchanged(seal, current):
        return _execution_result(['HEAD_CHANGED'])
    expected = {r['name']: r['oid'] for r in seal['refs']}
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or any(not isinstance(r, dict) or set(r) != {'ref','expectedOldOid','newOid'}
                   or not isinstance(r.get('ref'), str)
                   or r.get('ref') not in expected or r.get('expectedOldOid') != expected.get(r.get('ref'))
                   or not _is_nonzero_hex40(r.get('newOid')) for r in rows)
            or len({r['ref'] for r in rows}) != len(expected)):
        return _execution_result(['LEASE_INVENTORY_MISMATCH'])
    rows = sorted(rows, key=lambda r: r['ref'])
    argv = ['git', 'push', '--atomic', '--dry-run']
    argv += ['--force-with-lease=' + r['ref'] + ':' + r['expectedOldOid'] for r in rows]
    argv += ['origin'] + [r['newOid'] + ':' + r['ref'] for r in rows]
    return _execution_result(dryRunArgv=argv, sealSha256=_canonical_json_sha256(seal))


def validate_execution_watchdog(row, *, seal, restoration_payload_sha256, now):
    if not _execution_seal_valid(seal) or not isinstance(row, dict):
        return _execution_result(['EXECUTION_SEAL_INVALID'])
    if (row.get('sourceHead') != seal['sourceHead'] or row.get('sealSha256') != _canonical_json_sha256(seal)
            or row.get('rulesetGetSha256') != seal['rulesetGetSha256']
            or not _is_hex(restoration_payload_sha256, 64)
            or row.get('restorePayloadSha256') != restoration_payload_sha256):
        return _execution_result(['WATCHDOG_BINDING_MISMATCH'])
    if not all(_execution_int(v) for v in (now,row.get('getExitCode'),row.get('heartbeatAt'))):
        return _execution_result(['STRICT_INTEGER_REQUIRED'])
    if (row.get('armed') is not True or row.get('independentProcess') is not True
            or row['getExitCode'] != 0 or not 0 <= now - row['heartbeatAt'] <= 30
            or not _execution_int(row.get('boundedPutAttempts'), 1, 3)
            or row.get('persistentFailureEscalation') != 'owner-break-glass'):
        return _execution_result(['WATCHDOG_NOT_READY'])
    return _execution_result()


def validate_execution_operator(row, *, seal):
    if not _execution_seal_valid(seal) or not isinstance(row, dict):
        return _execution_result(['OPERATOR_ATTESTATION_REQUIRED'])
    if (row.get('mode') != 'single-operator' or row.get('owner') != OWNER_APPROVER
            or row.get('sealSha256') != _canonical_json_sha256(seal)
            or any(row.get(k) is not True for k in ('riskAccepted','independentTechnicalApproval',
                                                    'supportAndFreshClonePlan','powerNetworkChecked'))
            or row.get('pausePoints') != ['backup-drill','rewrite-push','ci-dispatch']):
        return _execution_result(['OPERATOR_ATTESTATION_REQUIRED'])
    return _execution_result()


def validate_execution_scope_decision(row, *, seal, now, rewritten_paths):
    """Day-granular expiry model; declared scope must later match authenticated read-back."""
    if not _execution_seal_valid(seal) or not isinstance(row, dict) or not _execution_int(now):
        return _execution_result(['TOKEN_SCOPE_INVALID'])
    if row.get('workflowsWriteDecision') is not True:
        return _execution_result(['WORKFLOWS_SCOPE_DECISION_REQUIRED'])
    permissions = row.get('permissions')
    if not isinstance(permissions, dict):
        return _execution_result(['TOKEN_SCOPE_INVALID'])
    if set(permissions) - {'contents','workflows','metadata','administration','actions'}:
        return _execution_result(['TOKEN_SCOPE_EXCESS'])
    restoration_scope = {'contents':'write', 'workflows':'write', 'metadata':'read',
                         'administration':'write', 'actions':'read'}
    if (('administration' in permissions and
         (permissions != restoration_scope or row.get('restorationWorkflow') != 'reviewed-ruleset-restoration/v1'))
            or ('actions' in permissions and permissions['actions'] != 'read')):
        return _execution_result(['RESTORATION_SCOPE_INVALID'])
    if permissions.get('workflows') != 'write':
        return _execution_result(['WORKFLOWS_WRITE_REQUIRED'])
    if (row.get('repository') != REPOSITORY or permissions.get('contents') != 'write'
            or ('metadata' in permissions and permissions['metadata'] != 'read')
            or not _execution_int(row.get('expiresAt')) or not 600 <= row['expiresAt'] - now <= 172800
            or not isinstance(rewritten_paths, list) or not rewritten_paths
            or any(not isinstance(p, str) or p.startswith('/') or '..' in PurePosixPath(p).parts for p in rewritten_paths)):
        return _execution_result(['TOKEN_SCOPE_INVALID'])
    return _execution_result(scopeReadbackRequiredBeforePush=True, expiryGranularity='day',
                             sealSha256=_canonical_json_sha256(seal))


def validate_execution_scope_readback(row, *, seal, now, expected_receipt_sha256):
    """Validate a separately authenticated receipt; never trust a decision flag.

    The caller obtains the expected receipt digest from the independent approval
    channel, not from the supplied row. This pure API neither provisions a token
    nor establishes authenticity of arbitrary JSON. No token bytes are accepted.
    """
    if (not _execution_seal_valid(seal) or not isinstance(row, dict)
            or not _execution_int(now) or not _is_hex(expected_receipt_sha256, 64)):
        return _execution_result(['TOKEN_SCOPE_READBACK_REQUIRED'])
    fields = {'repository', 'sealSha256', 'sourceHead', 'permissions', 'readAt',
              'expiresAt', 'exitCode', 'ownerDecisionCommentId', 'receiptKind'}
    if set(row) not in (fields, fields | {'restorationWorkflow'}):
        return _execution_result(['TOKEN_SCOPE_READBACK_REQUIRED'])
    permissions = row['permissions']
    push_scope = {'contents':'write', 'workflows':'write', 'metadata':'read'}
    restoration_scope = {**push_scope, 'administration':'write', 'actions':'read'}
    if (permissions != push_scope and
            (permissions != restoration_scope or row.get('restorationWorkflow') != 'reviewed-ruleset-restoration/v1')):
        return _execution_result(['TOKEN_SCOPE_READBACK_MISMATCH'])
    if not all(_execution_int(row[k]) for k in ('readAt', 'expiresAt', 'exitCode')):
        return _execution_result(['STRICT_INTEGER_REQUIRED'])
    if (row['repository'] != REPOSITORY or row['sourceHead'] != seal['sourceHead']
            or row['sealSha256'] != _canonical_json_sha256(seal)
            or row['receiptKind'] != 'independent-scope-readback/v1'
            or not isinstance(row['ownerDecisionCommentId'], str)
            or re.fullmatch(r'[1-9][0-9]*', row['ownerDecisionCommentId']) is None
            or row['exitCode'] != 0 or not 0 <= now - row['readAt'] <= 300
            or not seal['capturedAt'] <= now < seal['expiresAt']
            or not 600 <= row['expiresAt'] - now <= 172800
            or _canonical_json_sha256(row) != expected_receipt_sha256):
        return _execution_result(['TOKEN_SCOPE_READBACK_MISMATCH'])
    return _execution_result(scopeReadbackVerified=True)


def prepare_execution_push(rows, *, seal, current, now, approvals,
                           scope_readback, scope_receipt_sha256):
    """Bind the push planner to current exact-seal approval AND scope receipts.

    This is still a dry-run-only planning boundary. A production executor must
    independently authenticate approval provenance, atomically consume Gate F,
    and establish watchdog/restoration readiness before any remote mutation.
    Neither the receipt hash nor arbitrary JSON grants execution authority here.
    """
    scope = validate_execution_scope_readback(scope_readback, seal=seal, now=now,
                                             expected_receipt_sha256=scope_receipt_sha256)
    if scope['verdict'] != 'PASS':
        return scope
    authorization = validate_execution_approvals(approvals, seal=seal, current=current, now=now)
    if authorization['verdict'] != 'PASS':
        return authorization
    return plan_execution_leases(rows, seal=seal, current=current)


EXECUTION_CI_WORKFLOWS = (
    'ci-flaky-nyay4-cookie-reload-symmetry.yml',
    'nyay13-independent-qa-observe.yml',
    'nyay18-frontend-namespace-gate.yml',
    'nyay42-optimization-observe.yml',
    'nyay5-profile-boundary-gate.yml',
    'nyayone-policy-gate.yml',
    'registration-db-gate.yml',
    'wave1-foundation-gate.yml',
    'wave2-tutoring-db-gate.yml',
    'wave3-credential-trust-gate.yml',
    'wave4-private-reporting-gate.yml',
    'wave5-calendar-gate.yml',
)


def prepare_owner_ci_dispatch(*, seal, post_push_head, observed_main_head, permissions):
    """Step 12: print an owner-only dispatch plan; never invoke gh or credentials.

    Actions:read remains the executor limit. The owner uses their own GitHub UI
    session or separate CLI authentication. A mutable main ref is guarded before
    EACH dispatch and every returned run must independently read back at the
    exact post-push head. A dispatched campaign is not a passing campaign.
    """
    if not _execution_seal_valid(seal) or not _is_nonzero_hex40(post_push_head):
        return _execution_result(['EXECUTION_SEAL_INVALID'])
    if observed_main_head != post_push_head:
        return _execution_result(['HEAD_CHANGED'])
    if permissions != {'contents':'write', 'workflows':'write', 'metadata':'read',
                       'administration':'write', 'actions':'read'}:
        return _execution_result(['RESTORATION_SCOPE_INVALID'])
    guard = (f'test "$(gh api repos/{REPOSITORY}/git/ref/heads/main '
             f'--jq .object.sha)" = "{post_push_head}"')
    commands = [f'{guard} && gh workflow run {name} --repo {REPOSITORY} --ref main'
                for name in EXECUTION_CI_WORKFLOWS]
    return _execution_result(step=12, operator='owner', dispatchExecuted=False,
                             ownerCommands=commands, ownerHeadGuard=guard,
                             uiUrl=f'https://github.com/{REPOSITORY}/actions',
                             expectedHead=post_push_head,
                             expectedWorkflows=list(EXECUTION_CI_WORKFLOWS),
                             scopeReadbackRequiredBeforePush=True,
                             nextPause='ci-dispatch')


def validate_owner_ci_dispatch_readback(rows, *, expected_head, observed_main_head):
    """Validate independent Actions GET rows; no owner declaration grants PASS.

    This validates dispatch identity only. Completion, producer assertions and
    exact-head evidence gates remain required before closure, including the
    manually dispatched quarantine workflow without promoting it to blocking.
    """
    if not _is_nonzero_hex40(expected_head):
        return _execution_result(['DISPATCH_HEAD_INVALID'])
    if expected_head != observed_main_head:
        return _execution_result(['HEAD_CHANGED'])
    fields = {'workflow', 'runId', 'headSha', 'event', 'repository'}
    if (not isinstance(rows, list) or len(rows) != len(EXECUTION_CI_WORKFLOWS)
            or any(not isinstance(r, dict) or set(r) != fields
                   or not isinstance(r['workflow'], str)
                   or r['workflow'] not in EXECUTION_CI_WORKFLOWS
                   or not _execution_int(r['runId'], 1)
                   or r['headSha'] != expected_head or r['event'] != 'workflow_dispatch'
                   or r['repository'] != REPOSITORY for r in rows)
            or len({r['workflow'] for r in rows}) != len(EXECUTION_CI_WORKFLOWS)
            or len({r['runId'] for r in rows}) != len(rows)):
        return _execution_result(['DISPATCH_READBACK_MISMATCH'])
    return _execution_result(dispatchReadbackVerified=True, campaignPassed=False,
                             runIds=sorted(r['runId'] for r in rows), nextPause='ci-dispatch')


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
        and inventory.get("refInventorySha256")
        == AUTHORITATIVE_REF_INVENTORY_SHA256
        and inventory.get("reachableCommitCount")
        == AUTHORITATIVE_REACHABLE_COMMIT_COUNT
        and inventory.get("affectedCommitCount")
        == AUTHORITATIVE_AFFECTED_COMMIT_COUNT
        and inventory.get("signedCommitCount")
        == AUTHORITATIVE_SIGNED_COMMIT_COUNT
        and _inventory_content_seal_is_valid(inventory)
    )


def validate_authoritative_planning_seal(seal: object) -> dict[str, Any]:
    """Accept only the exact R1 inventory sealed at the reviewed source head."""

    row = seal if isinstance(seal, Mapping) else {}
    refs = row.get("refs") if isinstance(row.get("refs"), list) else []
    ref_counts = row.get("refCounts") if isinstance(row.get("refCounts"), Mapping) else {}
    target_rows = _target_rows(row.get("targetManifest"))
    codes: list[str] = []
    try:
        observed_seal_digest = _canonical_json_sha256(row)
        observed_ref_digest = _canonical_json_sha256(refs)
        observed_target_digest = _canonical_json_sha256(row.get("targetManifest"))
    except (TypeError, ValueError):
        observed_seal_digest = ""
        observed_ref_digest = ""
        observed_target_digest = ""

    concrete_refs = [
        ref
        for ref in refs
        if isinstance(ref, Mapping) and ref.get("kind") != "symbolic-head"
    ]
    symbolic_refs = [
        ref
        for ref in refs
        if isinstance(ref, Mapping) and ref.get("kind") == "symbolic-head"
    ]
    if (
        observed_seal_digest != AUTHORITATIVE_PLANNING_SEAL_SHA256
        or row.get("repository") != REPOSITORY
        or row.get("visibility") != "PRIVATE"
        or row.get("sourceHead") != BASE_SHA
        or row.get("reachableCommitCount") != AUTHORITATIVE_REACHABLE_COMMIT_COUNT
        or row.get("expectedAffectedCommitCount")
        != AUTHORITATIVE_AFFECTED_COMMIT_COUNT
        or row.get("expectedChangedCommitCount")
        != AUTHORITATIVE_CHANGED_COMMIT_COUNT
        or row.get("expectedPrunedCommitCount")
        != AUTHORITATIVE_PRUNED_COMMIT_COUNT
        or row.get("signedCommitCount") != AUTHORITATIVE_SIGNED_COMMIT_COUNT
        or ref_counts.get("concreteRefs") != AUTHORITATIVE_CONCRETE_REF_COUNT
        or ref_counts.get("totalRowsIncludingSymbolicHead")
        != AUTHORITATIVE_TOTAL_REF_ROWS
        or len(concrete_refs) != AUTHORITATIVE_CONCRETE_REF_COUNT
        or len(refs) != AUTHORITATIVE_TOTAL_REF_ROWS
        or len(symbolic_refs) != 1
        or target_rows != TARGETS
        or row.get("refInventorySha256")
        != AUTHORITATIVE_REF_INVENTORY_SHA256
        or observed_ref_digest != AUTHORITATIVE_REF_INVENTORY_SHA256
        or row.get("targetManifestSha256") != observed_target_digest
    ):
        codes.append("AUTHORITATIVE_PLANNING_SEAL_MISMATCH")
    return _result(
        codes,
        sourceHead=row.get("sourceHead"),
        refInventorySha256=row.get("refInventorySha256"),
        concreteRefCount=len(concrete_refs),
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
        and security.get("name") == SECURITY_PRIVACY_APPROVER
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
        prior.get("signedCommitCount") != AUTHORITATIVE_SIGNED_COMMIT_COUNT
        or current.get("signedCommitCount") != 0
        or current.get("signatureDisposition")
        != "git-filter-repo-stripped-40-gpg-signatures-with-sealed-old-object-map"
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
            or not _is_safe_publishable_ref_name(name)
            or row.get("old") != source.get("target")
            or row.get("kind") != source.get("kind")
            or not _is_nonzero_hex40(row.get("old"))
            or not _is_nonzero_hex40(row.get("new"))
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
            not _is_safe_publishable_ref_name(name)
            or name in {"HEAD", "--all"}
            or name.startswith("refs/pull/")
            or any(symbol in name for symbol in "*?[]")
            or not isinstance(entry, Mapping)
            or not _is_nonzero_hex40(entry.get("old"))
            or not _is_nonzero_hex40(entry.get("new"))
        ):
            raise ValueError("unsafe force-update ref mapping")
        leases.append(f"--force-with-lease={name}:{entry['old']}")
        refspecs.append(f"{entry['new']}:{name}")
    return [" ".join(("git", "push", "--atomic", *leases, "origin", *refspecs))]


def render_force_update_dry_run_commands(
    mapping: object, approved_refs: object
) -> list[str]:
    """Render the exact transaction with ``--dry-run`` and never execute it."""

    commands = render_force_update_commands(mapping, approved_refs)
    prefix = "git push --atomic "
    return [
        command.replace(prefix, "git push --atomic --dry-run ", 1)
        for command in commands
    ]


def validate_atomic_dry_run_lease_readback(
    proof: object,
    authoritative_seal: object,
    mapping: object,
    approved_refs: object,
) -> dict[str, Any]:
    """Bind an atomic dry-run to all 42 remote refs and exact old-SHA leases."""

    row = proof if isinstance(proof, Mapping) else {}
    seal = authoritative_seal if isinstance(authoritative_seal, Mapping) else {}
    codes: list[str] = []
    seal_result = validate_authoritative_planning_seal(seal)
    if seal_result["verdict"] != "PASS":
        codes.append("AUTHORITATIVE_PLANNING_SEAL_MISMATCH")

    expected_readback = [
        dict(ref)
        for ref in seal.get("refs", [])
        if isinstance(ref, Mapping) and ref.get("kind") != "symbolic-head"
    ]
    actual_readback = (
        row.get("readBackRefs") if isinstance(row.get("readBackRefs"), list) else []
    )
    if (
        len(expected_readback) != AUTHORITATIVE_CONCRETE_REF_COUNT
        or actual_readback != expected_readback
    ):
        codes.append("REMOTE_REF_READBACK_NOT_CLOSED")

    try:
        expected_command = render_force_update_dry_run_commands(
            mapping, approved_refs
        )[0]
    except (TypeError, ValueError, IndexError):
        expected_command = ""
        codes.append("DRY_RUN_PLAN_INVALID")
    if (
        not expected_command
        or row.get("command") != expected_command
        or row.get("commandSha256")
        != hashlib.sha256(expected_command.encode("utf-8")).hexdigest()
    ):
        codes.append("DRY_RUN_PLAN_SEAL_MISMATCH")

    mapping_rows = mapping if isinstance(mapping, Mapping) else {}
    inventory_by_name = {
        ref.get("name"): ref
        for ref in expected_readback
        if isinstance(ref, Mapping)
    }
    approved = (
        list(approved_refs)
        if isinstance(approved_refs, Sequence)
        and not isinstance(approved_refs, (str, bytes))
        else []
    )
    rewrite_ref_result = validate_rewrite_refs(approved, seal)
    if rewrite_ref_result["verdict"] != "PASS":
        codes.append("DRY_RUN_REF_SCOPE_INCOMPLETE")
    if not approved or set(mapping_rows) != set(approved):
        codes.append("DRY_RUN_PLAN_INVALID")
    else:
        for name in approved:
            mapping_row = mapping_rows.get(name)
            inventory_row = inventory_by_name.get(name)
            if (
                not isinstance(mapping_row, Mapping)
                or not isinstance(inventory_row, Mapping)
                or mapping_row.get("old") != inventory_row.get("target")
            ):
                codes.append("LEASE_READBACK_MISMATCH")
                break

    if row.get("dryRunExitCode") != 0:
        codes.append("DRY_RUN_FAILED")
    if row.get("atomicAdvertised") is not True:
        codes.append("ATOMIC_PUSH_NOT_PROVEN")
    if row.get("remoteUpdated") is not False:
        codes.append("DRY_RUN_MUTATED_REMOTE")
    return _result(codes, remoteRefRows=len(actual_readback), remoteUpdated=False)


def _ruleset_update_payload(readback: Mapping[str, object]) -> dict[str, object]:
    required = ("name", "target", "enforcement", "bypass_actors", "conditions", "rules")
    return {key: copy.deepcopy(readback.get(key)) for key in required}


def _ruleset_oracles_are_intact(readback: Mapping[str, object]) -> bool:
    rules = readback.get("rules")
    if not isinstance(rules, list):
        return False
    by_type = {
        rule.get("type"): rule
        for rule in rules
        if isinstance(rule, Mapping) and isinstance(rule.get("type"), str)
    }
    status_rule = by_type.get("required_status_checks")
    pull_rule = by_type.get("pull_request")
    status_parameters = (
        status_rule.get("parameters") if isinstance(status_rule, Mapping) else None
    )
    pull_parameters = (
        pull_rule.get("parameters") if isinstance(pull_rule, Mapping) else None
    )
    contexts = (
        [
            item.get("context")
            for item in status_parameters.get("required_status_checks", [])
            if isinstance(item, Mapping)
        ]
        if isinstance(status_parameters, Mapping)
        else []
    )
    return (
        readback.get("id") == RULESET_ID
        and readback.get("name") == "NyayOne main baseline protection"
        and readback.get("enforcement") == "active"
        and readback.get("target") == "branch"
        and readback.get("bypass_actors") == []
        and readback.get("conditions")
        == {"ref_name": {"exclude": [], "include": ["refs/heads/main"]}}
        and "deletion" in by_type
        and "non_fast_forward" in by_type
        and isinstance(pull_parameters, Mapping)
        and pull_parameters.get("required_review_thread_resolution") is True
        and isinstance(status_parameters, Mapping)
        and status_parameters.get("strict_required_status_checks_policy") is True
        and contexts == list(STRICT_REQUIRED_CHECKS)
    )


def render_ruleset_restoration_trap(payload_pair: object) -> str:
    """Render, but never execute, the sealed ruleset restoration trap."""

    pair = payload_pair if isinstance(payload_pair, Mapping) else {}
    before_digest = pair.get("canonicalGetBeforeSha256")
    relaxation_digest = pair.get("relaxationPayloadSha256")
    restoration_digest = pair.get("restorationPayloadSha256")
    try:
        observed_before_digest = _canonical_json_sha256(
            pair.get("canonicalGetBefore")
        )
        observed_relaxation_digest = _canonical_json_sha256(
            pair.get("relaxationPayload")
        )
        observed_restoration_digest = _canonical_json_sha256(
            pair.get("restorationPayload")
        )
    except (TypeError, ValueError):
        raise ValueError("ruleset restoration pair is not sealed") from None
    if (
        pair.get("rulesetId") != RULESET_ID
        or not _is_hex(before_digest, 64)
        or not _is_hex(relaxation_digest, 64)
        or not _is_hex(restoration_digest, 64)
        or before_digest != AUTHORITATIVE_RULESET_GET_SHA256
        or relaxation_digest != AUTHORITATIVE_RELAXATION_PAYLOAD_SHA256
        or restoration_digest != AUTHORITATIVE_RESTORATION_PAYLOAD_SHA256
        or observed_before_digest != before_digest
        or observed_relaxation_digest != relaxation_digest
        or observed_restoration_digest != restoration_digest
    ):
        raise ValueError("ruleset restoration pair is not sealed")
    return f"""#!/usr/bin/env bash
set -euo pipefail

: "${{NYAY21_RESTORATION_PAYLOAD:?sealed restoration payload path required}}"
: "${{NYAY21_RESTORED_GET:?independent GET output path required}}"

restore_ruleset_from_sealed_payload() {{
  local prior_status=$?
  local payload_digest
  local readback_digest
  payload_digest="$(jq -cS . "$NYAY21_RESTORATION_PAYLOAD" | tr -d '\\n' | shasum -a 256 | awk '{{print $1}}')"
  test "$payload_digest" = "{restoration_digest}"
  gh api --method PUT repos/rajeevbarnwal/NyayOne/rulesets/{RULESET_ID} \\
    --input "$NYAY21_RESTORATION_PAYLOAD"
  gh api repos/rajeevbarnwal/NyayOne/rulesets/{RULESET_ID} \\
    > "$NYAY21_RESTORED_GET"
  readback_digest="$(jq -cS . "$NYAY21_RESTORED_GET" | tr -d '\\n' | shasum -a 256 | awk '{{print $1}}')"
  test "$readback_digest" = "{before_digest}"
  return "$prior_status"
}}

trap restore_ruleset_from_sealed_payload EXIT HUP INT TERM
"""


def validate_ruleset_restoration_trap_events(
    events: object, sealed_before_sha256: object
) -> dict[str, Any]:
    """Require evidence that restoration ran on every defined exit path."""

    rows = events if isinstance(events, list) else []
    required_paths = {"success", "push-rejected", "signal", "operator-error"}
    observed_paths = {
        row.get("path") for row in rows if isinstance(row, Mapping)
    }
    codes: list[str] = []
    if sealed_before_sha256 != AUTHORITATIVE_RULESET_GET_SHA256:
        codes.append("RULESET_GET_AUTHORITY_MISMATCH")
    if (
        not _is_hex(sealed_before_sha256, 64)
        or observed_paths != required_paths
        or len(rows) != len(required_paths)
    ):
        codes.append("RESTORATION_EXIT_PATH_UNPROVEN")
    for row in rows:
        if not (
            isinstance(row, Mapping)
            and row.get("restoreAttempted") is True
            and row.get("independentGetPerformed") is True
            and row.get("canonicalGetSha256") == sealed_before_sha256
        ):
            codes.append("RESTORATION_EXIT_PATH_UNPROVEN")
    return _result(codes, provenExitPaths=sorted(observed_paths - {None}))


def validate_ruleset_restoration(
    before: object,
    after: object,
    *,
    sealed_before_sha256: str | None = None,
    relaxation_payload: object = None,
    sealed_relaxation_sha256: str | None = None,
    restoration_payload: object = None,
    sealed_restoration_sha256: str | None = None,
    restoration_trap: object = None,
) -> dict[str, Any]:
    """Require the complete GitHub GET and a pre-sealed restoration ceremony."""

    prior = before if isinstance(before, Mapping) else {}
    current = after if isinstance(after, Mapping) else {}
    codes: list[str] = []
    required_full_get_keys = {
        "_links",
        "bypass_actors",
        "conditions",
        "created_at",
        "current_user_can_bypass",
        "enforcement",
        "id",
        "name",
        "node_id",
        "rules",
        "source",
        "source_type",
        "target",
        "updated_at",
    }
    full_get = required_full_get_keys.issubset(prior) and required_full_get_keys.issubset(
        current
    )
    if not full_get:
        codes.append("FULL_RULESET_READBACK_REQUIRED")

    try:
        before_digest = _canonical_json_sha256(prior)
        after_digest = _canonical_json_sha256(current)
    except (TypeError, ValueError):
        before_digest = ""
        after_digest = ""
    if not _is_hex(sealed_before_sha256, 64) or before_digest != sealed_before_sha256:
        codes.append("RULESET_GET_SEAL_MISMATCH")
    if sealed_before_sha256 != AUTHORITATIVE_RULESET_GET_SHA256:
        codes.append("RULESET_GET_AUTHORITY_MISMATCH")
    if prior != current or before_digest != after_digest:
        codes.append("PROTECTION_NOT_RESTORED")
    if not _ruleset_oracles_are_intact(prior) or not _ruleset_oracles_are_intact(
        current
    ):
        codes.append("ORACLE_WEAKENED")

    relaxation = relaxation_payload if isinstance(relaxation_payload, Mapping) else {}
    restoration = (
        restoration_payload if isinstance(restoration_payload, Mapping) else {}
    )
    try:
        relaxation_digest = _canonical_json_sha256(relaxation)
        restoration_digest = _canonical_json_sha256(restoration)
    except (TypeError, ValueError):
        relaxation_digest = ""
        restoration_digest = ""
    if (
        not _is_hex(sealed_relaxation_sha256, 64)
        or relaxation_digest != sealed_relaxation_sha256
        or not _is_hex(sealed_restoration_sha256, 64)
        or restoration_digest != sealed_restoration_sha256
    ):
        codes.append("RULESET_PAYLOAD_SEAL_MISMATCH")
    if (
        sealed_relaxation_sha256 != AUTHORITATIVE_RELAXATION_PAYLOAD_SHA256
        or sealed_restoration_sha256 != AUTHORITATIVE_RESTORATION_PAYLOAD_SHA256
    ):
        codes.append("RULESET_PAYLOAD_AUTHORITY_MISMATCH")

    expected_restoration = _ruleset_update_payload(prior)
    expected_relaxation = copy.deepcopy(expected_restoration)
    expected_relaxation["rules"] = [
        rule
        for rule in (expected_relaxation.get("rules") or [])
        if isinstance(rule, Mapping) and rule.get("type") != "non_fast_forward"
    ]
    if restoration != expected_restoration or relaxation != expected_relaxation:
        codes.append("RULESET_PAYLOAD_SCOPE_MISMATCH")

    trap = restoration_trap if isinstance(restoration_trap, Mapping) else {}
    if not (
        trap.get("schemaVersion") == "nyay21-ruleset-restoration-trap/v1"
        and trap.get("mechanism") == "shell-trap"
        and trap.get("installedBeforeRelaxation") is True
        and trap.get("trapSource")
        == "trap restore_ruleset_from_sealed_payload EXIT HUP INT TERM"
        and trap.get("signals") == ["EXIT", "HUP", "INT", "TERM"]
        and set(trap.get("exitPaths", []))
        == {"success", "push-rejected", "signal", "operator-error"}
        and trap.get("canonicalGetBeforeSha256") == sealed_before_sha256
        and trap.get("restorationPayloadSha256") == sealed_restoration_sha256
        and trap.get("independentGetAfterRestore") is True
        and trap.get("digestEqualityRequired") is True
    ):
        codes.append("RESTORATION_TRAP_INCOMPLETE")
    return _result(
        codes,
        beforeSha256=before_digest,
        afterSha256=after_digest,
        restorationTrapArmed="RESTORATION_TRAP_INCOMPLETE" not in codes,
    )


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
        "AUTHORITATIVE_REF_INVENTORY_SHA256",
    "AUTHORITATIVE_PLANNING_SEAL_SHA256",
    "AUTHORITATIVE_REACHABLE_COMMIT_COUNT",
    "AUTHORITATIVE_AFFECTED_COMMIT_COUNT",
    "AUTHORITATIVE_CHANGED_COMMIT_COUNT",
    "AUTHORITATIVE_PRUNED_COMMIT_COUNT",
    "AUTHORITATIVE_SIGNED_COMMIT_COUNT",
    "AUTHORITATIVE_CONCRETE_REF_COUNT",
    "AUTHORITATIVE_TOTAL_REF_ROWS",
    "AUTHORITATIVE_RULESET_GET_SHA256",
    "AUTHORITATIVE_RELAXATION_PAYLOAD_SHA256",
    "AUTHORITATIVE_RESTORATION_PAYLOAD_SHA256",
    "APPROVAL_REGISTRY_SCHEMA",
    "OWNER_APPROVER",
    "SECURITY_PRIVACY_APPROVER",
    "STRICT_REQUIRED_CHECKS",
    "TARGETS",
    "render_force_update_commands",
    "render_force_update_dry_run_commands",
    "render_ruleset_restoration_trap",
    "render_local_rewrite_argv",
    "validate_authorizations",
    "validate_atomic_dry_run_lease_readback",
    "validate_authoritative_planning_seal",
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
    "validate_ruleset_restoration_trap_events",
    "validate_seeded_history_canary",
    "validate_target_manifest",
    "verify_purge_reachability",
]
