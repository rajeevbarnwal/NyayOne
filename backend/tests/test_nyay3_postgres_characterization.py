"""Pure evaluator tests for the opt-in NYAY-3 PostgreSQL gate.

These tests do not claim PostgreSQL behavior.  They ensure a vulnerable result
can never be mislabeled as hardened (or vice versa); the real database evidence
comes only from ``scripts/nyay3_postgres_characterization.py``.
"""
from __future__ import annotations

from scripts.nyay3_postgres_characterization import (
    GUARDIAN_STATE_CASES,
    RACE_CONSTRAINTS,
    TARGET_CONSTRAINTS,
    TARGET_INDEXES,
    WORKERS,
    _expectation_results,
    _finalize_cleanup,
    _normalize_predicate,
    _normalize_constraint_definition,
)


def _report(*, vulnerable: bool) -> dict:
    def race(kind: str, workers: int) -> dict:
        inserted = workers if vulnerable else 1
        rejected = 0 if vulnerable else workers - 1
        return {
            "workers": workers,
            "distinct_backend_pids": list(range(100, 100 + workers)),
            "inserted": inserted,
            "constraint_rejected": rejected,
            "unexpected_error": 0,
            "persisted_rows": inserted,
            "constraint_names": (
                [] if vulnerable else [RACE_CONSTRAINTS[kind]] * rejected
            ),
        }

    guardian_cases = {}
    for name, status, verified, should_insert in GUARDIAN_STATE_CASES:
        inserted = vulnerable or should_insert
        guardian_cases[name] = {
            "status": status,
            "verified": verified,
            "should_insert": should_insert,
            "outcome": "inserted" if inserted else "constraint_rejected",
            "constraint": (
                None
                if inserted
                else "ck_guardian_consents_verified_matches_status"
            ),
        }

    return {
        "inventory": {
            "target_indexes_present": {
                "uq_otp_challenges_one_active_per_registration_purpose": not vulnerable,
                "uq_auth_sessions_one_active_per_user": not vulnerable,
            },
            "target_constraints_present": {
                "uq_guardian_consents_registration_id": not vulnerable,
                "uq_student_verifications_registration_id": not vulnerable,
                "ck_guardian_consents_verified_matches_status": not vulnerable,
            },
            "target_index_semantics": {
                name: not vulnerable for name in TARGET_INDEXES
            },
            "target_constraint_semantics": {
                name: not vulnerable for name in TARGET_CONSTRAINTS
            },
        },
        "probes": {
            "otp": race("otp", WORKERS),
            "session": race("session", WORKERS),
            "guardian": race("guardian", 2),
            "verification": race("verification", 2),
            "guardian_state": {"cases": guardian_cases},
        },
        "service_probes": {
            "otp_start": {
                "workers": WORKERS,
                "distinct_backend_pids": list(range(200, 200 + WORKERS)),
                "outcomes": {"success": WORKERS},
                "active": 1,
                "deliverable": 1,
            },
            "resend_start": {
                "workers": 2,
                "distinct_backend_pids": [300, 301],
                "outcomes": {"success": 1, "otp_error:resend_cooldown": 1},
                "active": 1,
                "deliverable": 1,
            },
            "otp_verify": {
                "workers": WORKERS,
                "distinct_backend_pids": list(range(400, 400 + WORKERS)),
                "outcomes": {
                    "success": 1,
                    "login_error:login_failed": WORKERS - 1,
                },
                "claimed_attempts": 1,
                "consumed_challenges": 1,
                "active_sessions": 1,
            },
            "session_rotation": {
                "workers": WORKERS,
                "distinct_backend_pids": list(range(500, 500 + WORKERS)),
                "outcomes": {"success": WORKERS},
                "active_sessions": 1,
            },
            "outbox_delivery_supersede": {
                "distinct_backend_pids": [550, 551],
                "lock_wait_observed": True,
                "delivery_outcome": "success",
                "supersede_outcome": "success",
                "sender_attempts": 1,
                "prior_outbox_status": "sent",
                "prior_code_erased": True,
                "active": 1,
                "deliverable": 1,
            },
            "unsafe_without_lock_and_constraint": {
                "otp_start": {
                    "workers": WORKERS,
                    "distinct_backend_pids": list(range(600, 600 + WORKERS)),
                    "outcomes": {"success": WORKERS},
                    "active": WORKERS,
                    "deliverable": WORKERS,
                },
                "session_rotation": {
                    "workers": WORKERS,
                    "distinct_backend_pids": list(range(700, 700 + WORKERS)),
                    "outcomes": {"success": WORKERS},
                    "active_sessions": WORKERS,
                },
            },
        },
    }


def test_red_baseline_and_hardened_expectations_are_mutually_exclusive():
    vulnerable = _report(vulnerable=True)
    hardened = _report(vulnerable=False)

    assert all(
        item["status"] == "PASS"
        for item in _expectation_results(vulnerable, "current-vulnerable")
    )
    assert any(
        item["status"] == "FAIL"
        for item in _expectation_results(vulnerable, "hardened")
    )
    assert all(
        item["status"] == "PASS"
        for item in _expectation_results(hardened, "hardened")
    )
    assert any(
        item["status"] == "FAIL"
        for item in _expectation_results(hardened, "current-vulnerable")
    )


def test_unexpected_worker_error_fails_both_modes():
    for expectation, vulnerable in (
        ("current-vulnerable", True),
        ("hardened", False),
    ):
        report = _report(vulnerable=vulnerable)
        report["probes"]["otp"]["unexpected_error"] = 1
        statuses = {
            item["id"]: item["status"]
            for item in _expectation_results(report, expectation)
        }
        assert statuses["HARNESS-ERRORS"] == "FAIL"


def test_hardened_requires_the_exact_rejection_constraint_multiset():
    for kind, assertion_id in (
        ("otp", "HARD-OTP"),
        ("session", "HARD-SESSION"),
        ("guardian", "HARD-GUARDIAN"),
        ("verification", "HARD-VERIFICATION"),
    ):
        report = _report(vulnerable=False)
        report["probes"][kind]["constraint_names"][0] = "unrelated_constraint"
        statuses = {
            item["id"]: item["status"]
            for item in _expectation_results(report, "hardened")
        }
        assert statuses[assertion_id] == "FAIL"


def test_hardened_requires_definition_level_inventory_semantics():
    for group, target in (
        ("target_index_semantics", TARGET_INDEXES[0]),
        ("target_constraint_semantics", TARGET_CONSTRAINTS[0]),
    ):
        report = _report(vulnerable=False)
        assert all(report["inventory"][group].values())
        report["inventory"][group][target] = False
        statuses = {
            item["id"]: item["status"]
            for item in _expectation_results(report, "hardened")
        }
        assert statuses["HARD-INVENTORY"] == "FAIL"


def test_hardened_requires_each_service_and_mutant_oracle():
    mutations = (
        ("otp_start", "active", 2, "HARD-SERVICE-OTP-START"),
        ("resend_start", "deliverable", 2, "HARD-SERVICE-RESEND-START"),
        ("otp_verify", "claimed_attempts", 0, "HARD-SERVICE-OTP-VERIFY"),
        (
            "session_rotation",
            "active_sessions",
            2,
            "HARD-SERVICE-SESSION-ROTATION",
        ),
        (
            "outbox_delivery_supersede",
            "lock_wait_observed",
            False,
            "HARD-SERVICE-OUTBOX-LOCK-ORDER",
        ),
    )
    for group, key, value, assertion_id in mutations:
        report = _report(vulnerable=False)
        report["service_probes"][group][key] = value
        statuses = {
            item["id"]: item["status"]
            for item in _expectation_results(report, "hardened")
        }
        assert statuses[assertion_id] == "FAIL"

    report = _report(vulnerable=False)
    report["service_probes"]["unsafe_without_lock_and_constraint"][
        "otp_start"
    ]["active"] = 1
    statuses = {
        item["id"]: item["status"]
        for item in _expectation_results(report, "hardened")
    }
    assert statuses["HARD-SERVICE-MUTANTS"] == "FAIL"


def test_guardian_state_matrix_requires_valid_controls_and_named_rejections():
    for name, _status, _verified, should_insert in GUARDIAN_STATE_CASES:
        report = _report(vulnerable=False)
        case = report["probes"]["guardian_state"]["cases"][name]
        if should_insert:
            case["outcome"] = "constraint_rejected"
            case["constraint"] = "ck_guardian_consents_verified_matches_status"
        else:
            case["constraint"] = "ck_guardian_consents_status"
        statuses = {
            item["id"]: item["status"]
            for item in _expectation_results(report, "hardened")
        }
        assert statuses["HARD-GUARDIAN-STATE"] == "FAIL"


def test_cleanup_failure_overrides_a_product_pass():
    report = {"classification": "FIX_VERIFICATION", "verdict": "PASS_HARDENED"}
    exit_code = _finalize_cleanup(
        report,
        scratch_created=True,
        cleanup_failed=True,
        primary_exit_code=0,
    )
    assert exit_code == 1
    assert report["pre_cleanup_verdict"] == "PASS_HARDENED"
    assert report["verdict"] == "FAIL_CLEANUP"
    assert report["classification"] == "HARNESS_FAILURE_NO_PRODUCT_VERDICT"
    assert report["scratch_database_retained"] is True
    assert report["cleanup"] == {"attempted": True, "status": "FAIL"}


def test_cleanup_success_preserves_primary_verdict_and_exit_code():
    report = {"classification": "BLOCKED_NO_EVIDENCE", "verdict": "BLOCKED"}
    exit_code = _finalize_cleanup(
        report,
        scratch_created=True,
        cleanup_failed=False,
        primary_exit_code=78,
    )
    assert exit_code == 78
    assert report["verdict"] == "BLOCKED"
    assert report["scratch_database_retained"] is False
    assert report["cleanup"] == {"attempted": True, "status": "PASS"}


def test_postgresql_predicate_reflection_is_canonicalized_without_rewriting_logic():
    assert _normalize_predicate("(consumed_at IS NULL)") == "consumed_at is null"
    assert (
        _normalize_predicate("((status)::text = 'active'::text)")
        == "status = 'active'"
    )
    assert _normalize_predicate("status = 'active' OR deleted_at IS NULL") != "status = 'active'"
    assert _normalize_predicate("status = 'active::text'") != "status = 'active'"
    assert _normalize_predicate("status = 'active '") != "status = 'active'"
    assert _normalize_predicate("status = 'ACTIVE'") != "status = 'active'"
    assert _normalize_predicate("status = 'active()'") != "status = 'active'"
    assert _normalize_predicate("status = 'act''ive'") != "status = 'active'"


def test_guardian_check_catalog_definition_requires_exact_semantics():
    expected = _normalize_constraint_definition(
        "(status = 'verified' AND verified = true) OR "
        "(status IN ('pending', 'sent', 'rejected') AND verified = false)"
    )
    reflected = (
        "CHECK (status::text = 'verified'::text AND verified = true OR "
        "status::text = ANY (ARRAY['pending'::character varying, "
        "'sent'::character varying, 'rejected'::character varying]::text[]) "
        "AND verified = false)"
    )
    assert _normalize_constraint_definition(reflected) == expected
    assert _normalize_constraint_definition(reflected + " OR verified = true") != expected
