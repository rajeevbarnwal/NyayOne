"""Pure evaluator tests for the opt-in NYAY-3 PostgreSQL gate.

These tests do not claim PostgreSQL behavior.  They ensure a vulnerable result
can never be mislabeled as hardened (or vice versa); the real database evidence
comes only from ``scripts/nyay3_postgres_characterization.py``.
"""
from __future__ import annotations

import pytest
import scripts.nyay3_postgres_characterization as gate
from sqlalchemy import create_engine, text

from scripts.nyay3_postgres_characterization import (
    Blocked,
    DIRTY_CONFLICT_CASES,
    GUARDIAN_STATE_CASES,
    HARDENED_ASSERTION_IDS,
    RACE_CONSTRAINTS,
    TARGET_CONSTRAINTS,
    TARGET_INDEXES,
    WORKERS,
    LIBPQ_AMBIENT_KEYS,
    ScratchCleanupFailure,
    _ScratchDatabaseManager,
    _clean_lifecycle_case_passes,
    _dirty_lifecycle_case_passes,
    _exact_revision_check,
    _expectation_results,
    _finalize_cleanup,
    _normalize_predicate,
    _normalize_constraint_definition,
    _reject_ambient_libpq_environment,
    _safe_local_postgres_url,
)


def test_historical_lifecycle_revision_check_rejects_future_head():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32))")
            )
            connection.execute(
                text("INSERT INTO alembic_version VALUES (:revision)"),
                {"revision": "0017_registration_invariants"},
            )
        assert _exact_revision_check(
            engine, "0017_registration_invariants"
        )["returncode"] == 0
        assert _exact_revision_check(
            engine, "0018_registration_idempotency"
        )["returncode"] == 1
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def _without_ambient_libpq_authority(monkeypatch):
    for key in tuple(gate.os.environ):
        if key in LIBPQ_AMBIENT_KEYS or key.startswith("PGSSL"):
            monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    "key",
    tuple(sorted(LIBPQ_AMBIENT_KEYS))
    + ("PGSSLMODE", "PGSSLCERT", "PGSSLKEY", "PGSSLROOTCERT"),
)
def test_ambient_libpq_routing_and_credentials_are_rejected(monkeypatch, key):
    monkeypatch.setenv(key, "sensitive-value-must-not-be-reported")
    with pytest.raises(
        Blocked,
        match="ambient libpq routing or credential environment is not allowed",
    ) as caught:
        _reject_ambient_libpq_environment()
    assert "sensitive-value" not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    (
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?host=evil.example",
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?hostaddr=203.0.113.7",
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?port=6543",
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?host=%2Ftmp",
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?options=-cstatement_timeout%3D0",
        "postgresql+psycopg:///postgres?host=%2Fvar%2Frun%2Fpostgresql",
    ),
)
def test_safe_postgres_url_rejects_every_query_routing_surface(url):
    with pytest.raises(Blocked, match="rejects PostgreSQL URL queries"):
        _safe_local_postgres_url(url)


@pytest.mark.parametrize(
    "url",
    (
        "postgresql+psycopg://qa:secret@localhost:5432/postgres",
        "postgresql+psycopg://qa:secret@127.0.0.1:5432/postgres",
        "postgresql+psycopg://qa:secret@[::1]:5432/postgres",
    ),
)
def test_safe_postgres_url_accepts_only_authority_loopback_without_query(url):
    parsed = _safe_local_postgres_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert not parsed.query


@pytest.mark.parametrize(
    "url",
    (
        "postgresql+psycopg://qa:p%40ss@localhost:5432/postgres",
        "postgresql+psycopg://qa:secret@localhost@evil.example:5432/postgres",
        "postgresql+psycopg://qa:secret@local%68ost:5432/postgres",
    ),
)
def test_safe_postgres_url_rejects_ambiguous_authority_bytes(url):
    with pytest.raises(Blocked, match="authority is ambiguous"):
        _safe_local_postgres_url(url)


def test_dirty_conflict_inventory_covers_every_preflight_class_and_polarity():
    assert DIRTY_CONFLICT_CASES == (
        "otp",
        "session",
        "guardian",
        "verification",
        "guardian_verified_false",
        "guardian_pending_true",
    )


def _command(returncode: int = 0, *, rejected: bool = False) -> dict:
    return {
        "arguments": [],
        "returncode": returncode,
        "generic_preflight_rejection": rejected,
    }


def _migration_lifecycle() -> dict:
    clean = {}
    for fixture in ("empty", "populated"):
        case = {
            "fixture": fixture,
            "commands": {
                "setup_parent": _command(),
                "upgrade_head": _command(),
                "check_head": _command(),
                "downgrade_parent": _command(),
                "reupgrade_head": _command(),
                "recheck_head": _command(),
            },
            "observations": {
                "parent": {
                    "revision": "0016_dob_hash_reconcile",
                    "target_objects_absent": True,
                },
                "first_head": {
                    "revision": "0017_registration_invariants",
                    "target_objects_exact": True,
                },
                "downgraded_parent": {
                    "revision": "0016_dob_hash_reconcile",
                    "target_objects_absent": True,
                },
                "final_head": {
                    "revision": "0017_registration_invariants",
                    "target_objects_exact": True,
                },
            },
            "fixture_shape_verified": True,
            "row_preservation": {
                "upgrade": True,
                "downgrade": True,
                "reupgrade": True,
                "parent_inventory_restored": True,
                "inventory_reproduced": True,
            },
        }
        case["passed"] = _clean_lifecycle_case_passes(case)
        clean[fixture] = case

    dirty = {}
    for conflict in DIRTY_CONFLICT_CASES:
        case = {
            "conflict": conflict,
            "commands": {
                "setup_parent": _command(),
                "rejected_upgrade": _command(1, rejected=True),
            },
            "observations": {
                "before": {
                    "revision": "0016_dob_hash_reconcile",
                    "target_objects_absent": True,
                },
                "after": {
                    "revision": "0016_dob_hash_reconcile",
                    "target_objects_absent": True,
                },
            },
            "fixture_shape_verified": True,
            "rows_unchanged": True,
            "schema_inventory_unchanged": True,
        }
        case["passed"] = _dirty_lifecycle_case_passes(case)
        dirty[conflict] = case
    return {
        "clean": clean,
        "dirty": dirty,
        "clean_passed": True,
        "dirty_passed": True,
    }


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
        "migration_lifecycle": _migration_lifecycle(),
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
            "typed_conflict_translation": {
                "otp_issue": {
                    "workers": 2,
                    "distinct_backend_pids": [560, 561],
                    "outcomes": {
                        "success": 1,
                        "otp_error:otp_issue_conflict:409:savepoint_usable": 1,
                    },
                    "active": 1,
                    "deliverable": 1,
                    "index_semantics_retained": True,
                },
                "session_rotation": {
                    "workers": 2,
                    "distinct_backend_pids": [570, 571],
                    "outcomes": {
                        "success": 1,
                        "login_error:login_conflict:409": 1,
                    },
                    "active_sessions": 1,
                    "audit_events": 1,
                    "index_semantics_retained": True,
                },
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


def test_harness_error_evidence_uses_scanner_safe_count_keys():
    results = _expectation_results(_report(vulnerable=False), "hardened")
    harness = next(item for item in results if item["id"] == "HARNESS-ERRORS")

    assert harness["observed"] == {
        "otp_unexpected_errors": 0,
        "session_unexpected_errors": 0,
        "guardian_unexpected_errors": 0,
        "verification_unexpected_errors": 0,
    }


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


@pytest.mark.parametrize(
    "fixture,field",
    (
        ("empty", "upgrade"),
        ("empty", "downgrade"),
        ("populated", "reupgrade"),
        ("populated", "parent_inventory_restored"),
        ("populated", "inventory_reproduced"),
    ),
)
def test_hardened_requires_both_clean_postgresql_lifecycles(fixture, field):
    report = _report(vulnerable=False)
    report["migration_lifecycle"]["clean"][fixture]["row_preservation"][field] = (
        False
    )
    statuses = {
        item["id"]: item["status"]
        for item in _expectation_results(report, "hardened")
    }
    assert statuses["HARD-MIGRATION-LIFECYCLE"] == "FAIL"


@pytest.mark.parametrize("conflict", DIRTY_CONFLICT_CASES)
def test_hardened_requires_every_dirty_preflight_to_fail_before_ddl(conflict):
    report = _report(vulnerable=False)
    case = report["migration_lifecycle"]["dirty"][conflict]
    case["observations"]["after"]["target_objects_absent"] = False
    statuses = {
        item["id"]: item["status"]
        for item in _expectation_results(report, "hardened")
    }
    assert statuses["HARD-DIRTY-PREFLIGHT"] == "FAIL"


def test_dirty_preflight_evaluator_requires_full_schema_inventory_identity():
    report = _report(vulnerable=False)
    report["migration_lifecycle"]["dirty"][DIRTY_CONFLICT_CASES[0]][
        "schema_inventory_unchanged"
    ] = False
    statuses = {
        item["id"]: item["status"]
        for item in _expectation_results(report, "hardened")
    }
    assert statuses["HARD-DIRTY-PREFLIGHT"] == "FAIL"


def test_hardened_requires_exact_dirty_case_inventory():
    report = _report(vulnerable=False)
    report["migration_lifecycle"]["dirty"].pop(DIRTY_CONFLICT_CASES[-1])
    statuses = {
        item["id"]: item["status"]
        for item in _expectation_results(report, "hardened")
    }
    assert statuses["HARD-DIRTY-PREFLIGHT"] == "FAIL"


def test_hardened_now_has_eighteen_assertions():
    assertions = _expectation_results(_report(vulnerable=False), "hardened")
    assert tuple(item["id"] for item in assertions) == HARDENED_ASSERTION_IDS


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


@pytest.mark.parametrize(
    "probe,path,value,assertion_id",
    (
        ("otp_issue", ("workers",), 3, "HARD-SERVICE-OTP-CONFLICT-TYPED"),
        (
            "otp_issue",
            ("distinct_backend_pids",),
            [560],
            "HARD-SERVICE-OTP-CONFLICT-TYPED",
        ),
        (
            "otp_issue",
            ("outcomes",),
            {"success": 1, "otp_error:wrong_code:409:savepoint_usable": 1},
            "HARD-SERVICE-OTP-CONFLICT-TYPED",
        ),
        (
            "otp_issue",
            ("outcomes",),
            {
                "success": 1,
                "otp_error:otp_issue_conflict:500:savepoint_usable": 1,
            },
            "HARD-SERVICE-OTP-CONFLICT-TYPED",
        ),
        (
            "otp_issue",
            ("outcomes",),
            {
                "success": 2,
                "otp_error:otp_issue_conflict:409:savepoint_usable": 0,
            },
            "HARD-SERVICE-OTP-CONFLICT-TYPED",
        ),
        (
            "otp_issue",
            ("outcomes",),
            {
                "success": 1,
                "otp_error:otp_issue_conflict:409:savepoint_unusable": 1,
            },
            "HARD-SERVICE-OTP-CONFLICT-TYPED",
        ),
        ("otp_issue", ("active",), 2, "HARD-SERVICE-OTP-CONFLICT-TYPED"),
        ("otp_issue", ("deliverable",), 0, "HARD-SERVICE-OTP-CONFLICT-TYPED"),
        (
            "otp_issue",
            ("index_semantics_retained",),
            False,
            "HARD-SERVICE-OTP-CONFLICT-TYPED",
        ),
        (
            "session_rotation",
            ("workers",),
            3,
            "HARD-SERVICE-SESSION-CONFLICT-TYPED",
        ),
        (
            "session_rotation",
            ("distinct_backend_pids",),
            [570],
            "HARD-SERVICE-SESSION-CONFLICT-TYPED",
        ),
        (
            "session_rotation",
            ("outcomes",),
            {"success": 1, "login_error:wrong_code:409": 1},
            "HARD-SERVICE-SESSION-CONFLICT-TYPED",
        ),
        (
            "session_rotation",
            ("outcomes",),
            {"success": 1, "login_error:login_conflict:500": 1},
            "HARD-SERVICE-SESSION-CONFLICT-TYPED",
        ),
        (
            "session_rotation",
            ("outcomes",),
            {"success": 2, "login_error:login_conflict:409": 0},
            "HARD-SERVICE-SESSION-CONFLICT-TYPED",
        ),
        (
            "session_rotation",
            ("active_sessions",),
            2,
            "HARD-SERVICE-SESSION-CONFLICT-TYPED",
        ),
        (
            "session_rotation",
            ("audit_events",),
            2,
            "HARD-SERVICE-SESSION-CONFLICT-TYPED",
        ),
        (
            "session_rotation",
            ("index_semantics_retained",),
            False,
            "HARD-SERVICE-SESSION-CONFLICT-TYPED",
        ),
    ),
)
def test_hardened_requires_every_typed_conflict_field(
    probe,
    path,
    value,
    assertion_id,
):
    report = _report(vulnerable=False)
    target = report["service_probes"]["typed_conflict_translation"][probe]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    statuses = {
        item["id"]: item["status"]
        for item in _expectation_results(report, "hardened")
    }
    assert statuses[assertion_id] == "FAIL"


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


def test_scratch_manager_fatally_cleans_each_successful_operation(monkeypatch):
    created = []
    dropped = []
    monkeypatch.setattr(
        gate,
        "_create_scratch",
        lambda _base, name: created.append(name) or "postgresql://scratch",
    )
    monkeypatch.setattr(
        gate,
        "_drop_scratch",
        lambda _base, name: dropped.append(name),
    )
    manager = _ScratchDatabaseManager(
        _safe_local_postgres_url(
            "postgresql+psycopg://qa:secret@localhost:5432/postgres"
        )
    )

    assert manager.run("first", lambda _url: "first-result") == "first-result"
    assert manager.run("second", lambda _url: "second-result") == "second-result"
    assert dropped == created
    assert manager.summary()["all_created_removed"] is True
    assert manager.summary()["created"] == 2
    assert manager.summary()["removed"] == 2


def test_scratch_manager_cleans_when_the_operation_raises(monkeypatch):
    created = []
    dropped = []
    monkeypatch.setattr(
        gate,
        "_create_scratch",
        lambda _base, name: created.append(name) or "postgresql://scratch",
    )
    monkeypatch.setattr(
        gate,
        "_drop_scratch",
        lambda _base, name: dropped.append(name),
    )
    manager = _ScratchDatabaseManager(
        _safe_local_postgres_url(
            "postgresql+psycopg://qa:secret@localhost:5432/postgres"
        )
    )

    def fail_operation(_url):
        raise ValueError("bounded operation failure")

    with pytest.raises(ValueError, match="bounded operation failure"):
        manager.run("operation-failure", fail_operation)
    assert dropped == created
    assert manager.summary()["all_created_removed"] is True


def test_scratch_manager_cleanup_failure_is_fatal_and_bounded(monkeypatch):
    monkeypatch.setattr(
        gate,
        "_create_scratch",
        lambda _base, _name: "postgresql://scratch",
    )

    def fail_drop(_base, _name):
        raise RuntimeError("sensitive driver output must not escape")

    monkeypatch.setattr(gate, "_drop_scratch", fail_drop)
    manager = _ScratchDatabaseManager(
        _safe_local_postgres_url(
            "postgresql+psycopg://qa:secret@localhost:5432/postgres"
        )
    )

    with pytest.raises(
        ScratchCleanupFailure,
        match="a disposable NYAY-3 database could not be removed",
    ):
        manager.run("failing-cleanup", lambda _url: "product-pass")
    summary = manager.summary()
    assert summary["all_created_removed"] is False
    assert summary["created"] == 1
    assert summary["removed"] == 0
    assert summary["cleanup_failed"] == 1


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
