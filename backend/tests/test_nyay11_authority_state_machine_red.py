"""NYAY-11 complete tests-first RED contract.

Jira acceptance criteria and Owner Policy Decisions comment 14714 are the sole
policy authority.  The future contract must enumerate all 5x5 guardian and
6x6 institutional source/target outcomes: exactly 61 closed-world rows.

The artifact is deliberately absent, so this specification is RED.  This file
adds no product, migration, route, database, or browser implementation.
"""
from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from typing import Any

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
CONTRACT_PATH = (
    REPOSITORY
    / "docs"
    / "architecture"
    / "nyay11-guardian-institution-authority"
    / "STATE_MACHINE_CONTRACT.json"
)

POLICY_COMMENT_ID = "14714"
POLICY_COMMENT_SHA256 = (
    "6b0aafc07ed2897c88efd455428136c6dbd67465b13fd2fd9b8ee01d5bd85ca0"
)
GUARDIAN_STATES = (
    "NOT_REQUIRED",
    "REQUIRED_PENDING",
    "VERIFIED",
    "REJECTED",
    "REVOKED",
)
INSTITUTIONAL_STATES = (
    "UNVERIFIED",
    "PENDING",
    "VERIFIED",
    "REJECTED",
    "EXPIRED",
    "REVOKED",
)

# (ordered triggers, ordered authorities); every omitted non-self edge denies.
GUARDIAN_ALLOWED_EDGES: dict[tuple[str, str], tuple[list[str], list[str]]] = {
    ("NOT_REQUIRED", "REQUIRED_PENDING"): (
        ["adult_to_minor"], ["server_age_policy"]),
    ("REQUIRED_PENDING", "NOT_REQUIRED"): (
        ["minor_to_adult"], ["server_age_policy"]),
    ("REQUIRED_PENDING", "VERIFIED"): (
        ["guardian_proof_completed"], ["server_attested_guardian"]),
    ("REQUIRED_PENDING", "REJECTED"): (
        ["guardian_declined"], ["server_attested_guardian"]),
    ("REQUIRED_PENDING", "REVOKED"): (
        ["guardian_or_owner_revocation"], ["guardian", "owner"]),
    ("VERIFIED", "NOT_REQUIRED"): (
        ["minor_to_adult"], ["server_age_policy"]),
    ("VERIFIED", "REQUIRED_PENDING"): (
        ["proof_expired", "dependent_identity_changed"],
        ["server_clock", "server_profile_policy"]),
    ("VERIFIED", "REVOKED"): (
        ["guardian_or_owner_revocation"], ["guardian", "owner"]),
    ("REJECTED", "NOT_REQUIRED"): (
        ["minor_to_adult"], ["server_age_policy"]),
    ("REJECTED", "REQUIRED_PENDING"): (
        ["new_guardian_request"], ["student"]),
    ("REVOKED", "NOT_REQUIRED"): (
        ["minor_to_adult"], ["server_age_policy"]),
    ("REVOKED", "REQUIRED_PENDING"): (
        ["new_guardian_request"], ["student"]),
}
INSTITUTIONAL_ALLOWED_EDGES: dict[
    tuple[str, str], tuple[list[str], list[str]]
] = {
    ("UNVERIFIED", "PENDING"): (
        ["student_review_request"], ["student"]),
    ("PENDING", "VERIFIED"): (
        ["assigned_review_approved"], ["assigned_institutional_reviewer"]),
    ("PENDING", "REJECTED"): (
        ["assigned_review_rejected"], ["assigned_institutional_reviewer"]),
    ("VERIFIED", "PENDING"): (
        ["dependent_identity_changed"], ["server_profile_policy"]),
    ("VERIFIED", "EXPIRED"): (
        ["verification_expired"], ["server_clock"]),
    ("VERIFIED", "REVOKED"): (
        ["owner_break_glass"], ["platform_owner"]),
    ("REJECTED", "PENDING"): (
        ["student_review_request"], ["student"]),
    ("EXPIRED", "PENDING"): (
        ["student_review_request"], ["student"]),
    ("REVOKED", "PENDING"): (
        ["student_review_request"], ["student"]),
}

LEGACY_GUARDIAN_MAP = {
    "pending": "REQUIRED_PENDING",
    "sent": "REQUIRED_PENDING",
    "verified": "VERIFIED",
    "rejected": "REJECTED",
    "revoked": "REVOKED",
}
LEGACY_INSTITUTIONAL_MAP = {
    "pending": "UNVERIFIED",
    "in_review": "PENDING",
    "verified": "VERIFIED",
    "rejected": "REJECTED",
    "expired": "EXPIRED",
    "revoked": "REVOKED",
}


def _red(contract_id: str, detail: str) -> None:
    pytest.fail(f"{contract_id}: {detail}", pytrace=False)


def _load_contract(contract_id: str) -> dict[str, Any]:
    if not CONTRACT_PATH.is_file():
        _red(contract_id, "authority/state-machine contract is not implemented")
    try:
        document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _red(contract_id, f"contract is not valid UTF-8 JSON: {exc}")
    if not isinstance(document, dict):
        _red(contract_id, "contract root must be an object")
    if document.get("ticket") != "NYAY-11":
        _red(contract_id, "contract is not bound to ticket NYAY-11")
    return document


def _object(parent: dict[str, Any], key: str, contract_id: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        _red(contract_id, f"{key} must be an object")
    return value


def _expected_row(machine: str, source: str, target: str) -> dict[str, Any]:
    allowed = (GUARDIAN_ALLOWED_EDGES if machine == "guardian"
               else INSTITUTIONAL_ALLOWED_EDGES)
    if source == target:
        triggers = ["exact_idempotent_replay"]
        if machine == "institutional" and source == "PENDING":
            triggers.append("reviewer_timeout_return_to_queue")
        return {
            "machine": machine, "from": source, "to": target,
            "disposition": "STATE_STABLE", "triggers": triggers,
            "authorities": ["server"],
            "effect": "no_state_change",
            "auditSemantics": (
                "aggregate_timeout_event_or_no_duplicate_exact_replay"
                if machine == "institutional" and source == "PENDING"
                else "no_duplicate_event_for_exact_replay"
            ),
            "policySource": "jira-comment-14714",
        }
    edge = allowed.get((source, target))
    if edge is None:
        return {
            "machine": machine, "from": source, "to": target,
            "disposition": "DENIED", "triggers": [], "authorities": [],
            "effect": "zero_state_write",
            "auditSemantics": "aggregate_denial_event_without_pii",
            "policySource": "jira-comment-14714",
        }
    triggers, authorities = edge
    return {
        "machine": machine, "from": source, "to": target,
        "disposition": "ALLOWED", "triggers": triggers,
        "authorities": authorities,
        "effect": "atomic_state_transition",
        "auditSemantics": "append_aggregate_transition_event",
        "policySource": "jira-comment-14714",
    }


STATE_PAIR_CASES = tuple(
    ("guardian", source, target)
    for source, target in product(GUARDIAN_STATES, repeat=2)
) + tuple(
    ("institutional", source, target)
    for source, target in product(INSTITUTIONAL_STATES, repeat=2)
)
assert len(STATE_PAIR_CASES) == 61


def test_red_policy_provenance_is_bound_to_owner_comment_14714() -> None:
    cid = "NYAY11-RED-POLICY-PROVENANCE"
    provenance = _object(_load_contract(cid), "policyProvenance", cid)
    assert provenance == {
        "policyVersion": "NYAY-11-v1",
        "jiraCommentId": POLICY_COMMENT_ID,
        "commentSha256": POLICY_COMMENT_SHA256,
        "owner": "Rajeev Barnwal",
    }


def test_red_state_vocabularies_are_closed_and_exact() -> None:
    cid = "NYAY11-RED-STATE-VOCABULARIES"
    vocabularies = _object(_load_contract(cid), "stateVocabularies", cid)
    assert vocabularies == {
        "guardian": list(GUARDIAN_STATES),
        "institutionalVerification": list(INSTITUTIONAL_STATES),
    }


@pytest.mark.parametrize(
    ("machine", "source", "target"),
    STATE_PAIR_CASES,
    ids=lambda value: value,
)
def test_red_each_of_61_state_pair_outcomes_is_exact(
    machine: str, source: str, target: str,
) -> None:
    cid = f"NYAY11-RED-STATE-{machine}-{source}-TO-{target}"
    matrix = _load_contract(cid).get("stateOutcomeMatrix")
    assert isinstance(matrix, list), f"{cid}: matrix must be a list"
    matches = [
        row for row in matrix
        if isinstance(row, dict)
        and row.get("machine") == machine
        and row.get("from") == source
        and row.get("to") == target
    ]
    assert len(matches) == 1, f"{cid}: pair must occur exactly once"
    assert matches[0] == _expected_row(machine, source, target)


def test_red_61_row_matrix_is_closed_world_without_duplicates_or_extras() -> None:
    cid = "NYAY11-RED-STATE-CLOSED-WORLD"
    matrix = _load_contract(cid).get("stateOutcomeMatrix")
    assert isinstance(matrix, list)
    assert len(matrix) == 61, f"{cid}: expected exactly 61 rows"
    expected = set(STATE_PAIR_CASES)
    actual = {
        (row.get("machine"), row.get("from"), row.get("to"))
        for row in matrix if isinstance(row, dict)
    }
    assert actual == expected
    assert len(actual) == len(matrix), f"{cid}: duplicate pair detected"


def test_red_p1_guardian_proof_is_server_attested_and_fail_closed() -> None:
    cid = "NYAY11-RED-P1-GUARDIAN-PROOF"
    proof = _object(_load_contract(cid), "guardianProof", cid)
    assert proof == {
        "sources": ["server_attested_otp_consent", "relationship_declaration"],
        "externalIdentityProvider": False,
        "purposeBound": True,
        "singleUse": True,
        "serverClocked": True,
        "binds": ["relationship", "policy_version", "consent_version", "timestamp"],
        "untilProven": {"accessMode": "limited", "failClosed": True},
    }


def test_red_p2_uses_12_month_ttl_and_immediate_revocation() -> None:
    cid = "NYAY11-RED-P2-TTL-REVOCATION"
    lifecycle = _object(_load_contract(cid), "guardianAuthorityLifecycle", cid)
    assert lifecycle == {
        "ttl": "P12M",
        "clockAuthority": "server",
        "revocationActors": ["guardian", "owner"],
        "revocationEffect": "immediate",
        "revocationWinsRaces": True,
        "expiredState": "REQUIRED_PENDING",
    }


def test_red_p3_institutional_reviewer_authority_is_exactly_scoped() -> None:
    cid = "NYAY11-RED-P3-INSTITUTIONAL-AUTHORITY"
    authority = _object(_load_contract(cid), "institutionalReviewerAuthority", cid)
    assert authority == {
        "requiredProofs": ["verified_institutional_email", "admin_assignment"],
        "scopeKeys": ["institution", "operation"],
        "crossInstitutionAllowed": False,
        "studentCanSelfVerify": False,
        "breakGlass": {
            "actor": "platform_owner", "audited": True,
            "studentAccessible": False,
        },
    }


def test_red_p4_timeout_returns_to_queue_and_never_auto_rejects() -> None:
    cid = "NYAY11-RED-P4-REVIEWER-TIMEOUT"
    timeout = _object(_load_contract(cid), "reviewerTimeout", cid)
    assert timeout == {
        "fromState": "PENDING", "toState": "PENDING",
        "action": "return_to_queue", "notificationRequired": True,
        "autoReject": False, "auditRequired": True,
    }


def test_red_p5_legacy_mapping_is_explicit_complete_and_audited() -> None:
    cid = "NYAY11-RED-P5-LEGACY-MAPPING"
    legacy = _object(_load_contract(cid), "legacyStateMapping", cid)
    assert legacy.get("guardian") == LEGACY_GUARDIAN_MAP
    assert legacy.get("institutionalVerification") == LEGACY_INSTITUTIONAL_MAP
    assert legacy.get("mappingCardinality") == {
        "guardianLegacyInputs": 5,
        "institutionalLegacyInputs": 6,
        "mappedInputs": 11,
    }
    assert legacy.get("auditEveryMapping") is True
    assert legacy.get("silentDropsAllowed") is False
    assert legacy.get("unknownLegacyState") == "BLOCK_MIGRATION"
    assert legacy.get("missingGuardianRow") == {
        "adult": "NOT_REQUIRED", "minor": "REQUIRED_PENDING",
    }


def test_red_p6_identity_changes_block_until_dependency_reproof() -> None:
    cid = "NYAY11-RED-P6-IDENTITY-REVERIFICATION"
    identity = _object(_load_contract(cid), "identityReverification", cid)
    assert identity.get("knownDependencyMap") == {
        "date_of_birth": ["guardian_authority"],
        "institutional_email": ["institutional_verification"],
    }
    assert identity.get("dependencyDirected") is True
    assert identity.get("unknownDependencyDisposition") == "BLOCK_MUTATION"
    assert identity.get("mutationWhileReproofPending") == "BLOCKED"
    assert identity.get("dependentProofDisposition") == "REVERIFICATION_REQUIRED"
    assert identity.get("auditProjection") == "aggregate_only_per_NYAY_19"
    assert identity.get("rawIdentityValuesInAudit") is False


def test_red_negative_authority_matrix_fails_closed_with_zero_writes() -> None:
    cid = "NYAY11-RED-AUTHORITY-NEGATIVE-MATRIX"
    authority = _object(_load_contract(cid), "authorityBoundary", cid)
    assert set(authority.get("deniedCases", [])) == {
        "anonymous", "student_self_approval", "cross_student_guardian",
        "cross_institution_reviewer",
    }
    assert authority.get("failClosed") is True
    assert authority.get("clientClaimsConferAuthority") is False
    assert authority.get("zeroWriteOnDenial") is True


def test_red_student_requests_and_reads_but_never_authors_approval() -> None:
    cid = "NYAY11-RED-STUDENT-CAPABILITIES"
    student = _object(_load_contract(cid), "studentCapabilities", cid)
    assert set(student.get("allowed", [])) == {
        "request_own_guardian_status", "request_own_institutional_status",
        "read_own_guardian_status", "read_own_institutional_status",
        "revoke_own_guardian_link",
    }
    assert set(student.get("forbiddenStateAuthorship", [])) == {
        "guardian:VERIFIED", "guardian:REJECTED",
        "institutional:VERIFIED", "institutional:REJECTED",
    }


def test_red_server_database_cardinality_and_consistency_are_mandatory() -> None:
    cid = "NYAY11-RED-SERVER-DB-INVARIANTS"
    inv = _object(_load_contract(cid), "serverInvariants", cid)
    assert inv.get("serverOwnedAuthority") is True
    assert inv.get("databaseCardinalityEnforced") is True
    assert inv.get("databaseConsistencyEnforced") is True
    assert inv.get("clientAuthorityAccepted") is False
    assert inv.get("oneCurrentGuardianAuthorityPerOwner") is True
    assert inv.get("oneCurrentInstitutionalReviewPerOwner") is True


def test_red_duplicates_revocation_expiry_and_concurrency_fail_closed() -> None:
    cid = "NYAY11-RED-CONCURRENCY-IDEMPOTENCY"
    inv = _object(_load_contract(cid), "serverInvariants", cid)
    assert inv.get("idempotentDuplicateHandling") is True
    assert inv.get("revocationFailClosed") is True
    assert inv.get("expiryFailClosed") is True
    assert inv.get("concurrencyProtected") is True
    assert inv.get("contradictoryRecordsPossible") is False
    assert inv.get("authorityLossWinsConcurrentCompletion") is True


def test_red_dob_boundaries_are_atomic_server_clocked_and_complete() -> None:
    cid = "NYAY11-RED-DOB-BOUNDARIES"
    transitions = _object(_load_contract(cid), "ageTransitions", cid)
    assert transitions.get("clock") == "single_injected_request_clock"
    assert transitions.get("dateBasis") == "request_civil_date"
    assert transitions.get("exactBirthdayCovered") is True
    assert transitions.get("leapDayCovered") is True
    assert transitions.get("concurrentDobEditCovered") is True
    assert transitions.get("adultToMinor") == {
        "atomic": True, "guardianState": "REQUIRED_PENDING",
        "accessMode": "limited", "restrictedImmediately": True,
    }
    assert transitions.get("minorToAdult") == {
        "atomic": True, "guardianState": "NOT_REQUIRED",
        "preserveHistory": True, "fabricateVerified": False,
    }


def test_red_postgresql_oracle_covers_all_61_valid_and_invalid_edges() -> None:
    cid = "NYAY11-RED-POSTGRES-61-EDGE-COVERAGE"
    coverage = _object(_load_contract(cid), "postgresqlCoverage", cid)
    assert coverage == {
        "guardianRows": 25, "institutionalRows": 36, "totalRows": 61,
        "validAndInvalidEdges": True, "committedNativePostgresTests": True,
        "zeroExecutedCannotPass": True, "exactInventoryRequired": True,
    }


def test_red_ui_consumes_server_projection_and_cannot_bypass_routes() -> None:
    cid = "NYAY11-RED-UI-SERVER-PROJECTION"
    ui = _object(_load_contract(cid), "uiBoundary", cid)
    assert ui == {
        "authoritySource": "canonical_server_projection",
        "localStorageAuthority": False, "sessionStorageAuthority": False,
        "clientClaimAuthority": False,
        "limitedModePrivateRouteMount": "DENIED",
        "canonical401Disposition": "UNMOUNT_PRIVATE_CONTENT",
    }


def test_red_audit_is_append_only_complete_and_aggregate_only() -> None:
    cid = "NYAY11-RED-AUDIT-PRIVACY"
    audit = _object(_load_contract(cid), "auditEvidence", cid)
    assert set(audit.get("required", [])) == {
        "actor_class", "authority_class", "purpose_code", "transition_code",
        "policy_version", "occurred_at",
    }
    assert audit.get("appendOnly") is True
    assert audit.get("aggregateOnly") is True
    assert audit.get("containsSecrets") is False
    assert audit.get("containsRawPii") is False
    assert audit.get("containsFreeText") is False


def test_red_public_errors_are_typed_collapsed_and_pii_safe() -> None:
    cid = "NYAY11-RED-PII-SAFE-DIAGNOSTICS"
    errors = _object(_load_contract(cid), "publicErrors", cid)
    assert errors.get("typed") is True
    assert errors.get("crossAuthorityReasonsCollapsed") is True
    assert errors.get("revealsRelationship") is False
    assert errors.get("revealsInstitution") is False
    assert errors.get("revealsActorIdentifier") is False
    assert errors.get("revealsProofMaterial") is False


def test_red_completion_is_disabled_without_current_authority() -> None:
    cid = "NYAY11-RED-NO-AUTHORITY-NO-COMPLETION"
    completion = _object(_load_contract(cid), "completionBoundary", cid)
    assert completion == {
        "missingGuardianCeremony": "DENIED_FAIL_CLOSED",
        "expiredGuardianProof": "DENIED_FAIL_CLOSED",
        "missingReviewerAssignment": "DENIED_FAIL_CLOSED",
        "staleInstitutionalEmailProof": "DENIED_FAIL_CLOSED",
        "authorityDerivedServerSide": True, "zeroWriteOnDenial": True,
    }
