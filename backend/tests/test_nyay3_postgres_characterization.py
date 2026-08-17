"""Pure evaluator tests for the opt-in NYAY-3 PostgreSQL gate.

These tests do not claim PostgreSQL behavior.  They ensure a vulnerable result
can never be mislabeled as hardened (or vice versa); the real database evidence
comes only from ``scripts/nyay3_postgres_characterization.py``.
"""
from __future__ import annotations

from scripts.nyay3_postgres_characterization import WORKERS, _expectation_results


def _report(*, vulnerable: bool) -> dict:
    def race(workers: int) -> dict:
        inserted = workers if vulnerable else 1
        rejected = 0 if vulnerable else workers - 1
        return {
            "workers": workers,
            "distinct_backend_pids": list(range(100, 100 + workers)),
            "inserted": inserted,
            "constraint_rejected": rejected,
            "unexpected_error": 0,
            "persisted_rows": inserted,
            "constraint_names": [],
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
        },
        "probes": {
            "otp": race(WORKERS),
            "session": race(WORKERS),
            "guardian": race(2),
            "verification": race(2),
            "guardian_state": {
                "contradiction_inserted": vulnerable,
                "constraint": (
                    None
                    if vulnerable
                    else "ck_guardian_consents_verified_matches_status"
                ),
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
