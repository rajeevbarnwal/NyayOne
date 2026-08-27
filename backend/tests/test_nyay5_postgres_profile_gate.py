"""Source and pure-oracle contract for the NYAY-5 PostgreSQL release gate."""

from __future__ import annotations

import importlib
import hashlib
import inspect
import re
from pathlib import Path

import pytest

from app.services import login_service
from app.db import migration_release_guard


BACKEND = Path(__file__).resolve().parents[1]
GATE = BACKEND / "scripts/nyay5_postgres_profile_gate.py"
DB_GATE = BACKEND / "scripts/db_gate.sh"

EXPECTED_COMMAND = (
    'NYAY5_POSTGRES_GATE=1 "$PY" scripts/nyay5_postgres_profile_gate.py '
    '--execute --database-url "$DATABASE_URL" '
    '--output test-results/nyay5-postgres/summary.json'
)


def _gate_module():
    return importlib.import_module("scripts.nyay5_postgres_profile_gate")


def test_nyay5_postgres_gate_source_exists_and_is_opt_in() -> None:
    assert GATE.is_file()
    source = GATE.read_text(encoding="utf-8")
    assert 'OPT_IN_ENV = "NYAY5_POSTGRES_GATE"' in source
    assert 'parser.add_argument("--execute", action="store_true")' in source
    assert "BLOCKED_EXIT = 78" in source


def test_db_gate_runs_nyay5_once_after_nyay2_before_nyay17() -> None:
    source = "\n".join(
        line
        for line in DB_GATE.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    source = re.sub(r"\\\s+", " ", source)
    source = re.sub(r"\s+", " ", source)
    assert source.count(EXPECTED_COMMAND) == 1
    assert source.index("scripts/nyay2_postgres_authorization_gate.py") < source.index(
        "scripts/nyay5_postgres_profile_gate.py"
    )
    assert source.index("scripts/nyay5_postgres_profile_gate.py") < source.index(
        "scripts/nyay17_postgres_idempotency_gate.py"
    )


def test_gate_pins_the_forward_migration_and_exact_assertion_inventory() -> None:
    gate = _gate_module()
    assert gate.PREVIOUS_REVISION == "0020_auth_retention_lifecycle"
    assert gate.PINNED_HEAD == "0021_nyay5_profile_boundary"
    assert gate.PINNED_HEAD_SHA256 == hashlib.sha256(
        gate.PINNED_HEAD_PATH.read_bytes()
    ).hexdigest()
    assert gate._application_head_bytes_unchanged() is True
    assert gate.REQUIRED_ASSERTION_IDS == (
        "RUNTIME-POSTGRES-16-PGVECTOR",
        "MIGRATION-0020-0021-FORWARD-IMMUTABLE",
        "MIGRATION-POPULATED-ROUNDTRIP-ATOMIC",
        "SCHEMA-PROFILE-BOUNDARY-EXACT",
        "CONTRACT-OWNER-PROJECTION-EXACT",
        "CONTRACT-ANONYMOUS-EXPIRED-REVOKED-DELETED-WRONG-ROLE",
        "CONTRACT-REGISTRATION-CONSENT-ZERO-MUTATION",
        "CONTRACT-REGISTRATION-ENUMERATION-NEUTRAL",
        "CONTRACT-CROSS-USER-CLIENT-SELECTOR-DENIED",
        "CONTRACT-NONTEST-ACTOR-HEADER-REJECTED",
        "CONTRACT-COMPLETION-V1-DETERMINISTIC",
        "CONTRACT-PERSISTENCE-FRESH-SESSION",
        "CONTRACT-NORMALIZED-IDENTITY-NO-DUPLICATION",
        "CONTRACT-OPTIMISTIC-CONCURRENCY",
        "CONTRACT-DOB-GUARDIAN-ATOMIC",
        "CONTRACT-DOB-AGE-BOUNDARIES",
        "CONTRACT-VERIFICATION-SELF-AUTHORITY-DENIED",
        "CONTRACT-AUTHORIZED-TRANSITIONS-EXACT",
        "CONTRACT-PROMPT-SESSION-SCOPE",
        "CONTRACT-AUDIT-AGGREGATE-PRIVACY",
        "HARNESS-MUTANTS-PRIVACY-SCRATCH-CLEANUP",
    )


def test_application_head_body_mutant_is_rejected(tmp_path) -> None:
    gate = _gate_module()
    mutated = tmp_path / gate.PINNED_HEAD_PATH.name
    mutated.write_bytes(gate.PINNED_HEAD_PATH.read_bytes() + b"\n# body mutant\n")
    assert gate._application_head_bytes_unchanged(mutated) is False


def test_behavior_gate_uses_reviewer_provenance_for_positive_verification() -> None:
    source = GATE.read_text(encoding="utf-8")
    assert re.search(
        r"StudentVerification\([^)]*status=\"verified\"", source, re.DOTALL
    ) is None
    assert '"/api/v1/auth/student/verification/status"' in source
    assert '"owner_projection_invalidated": True' in source


def test_behavior_gate_executes_registration_and_non_test_authority_contracts() -> None:
    gate = _gate_module()
    assert {
        "registration_consent_zero_mutation",
        "registration_enumeration_neutral",
        "non_test_actor_header_rejected",
        "authorized_transitions_exact",
    } <= gate._BEHAVIOR_OBSERVATION_KEYS
    source = GATE.read_text(encoding="utf-8")
    assert "registration_graph_counts" in source
    assert "hostile_registration_preconditions" in source
    assert "registration_safe_projection" in source
    assert "app.add_middleware(RequestIDMiddleware)" in source
    assert "register_exception_handlers(app)" in source
    assert 'settings.app_env = "production"' in source
    assert 'student_verification_denied' in source


def test_behavior_gate_runs_current_product_on_the_authoritative_application_head() -> None:
    gate = _gate_module()
    assert gate.BEHAVIOR_HEAD == migration_release_guard.APPLICATION_HEAD_REVISION
    source = inspect.getsource(gate._behavior_probe)
    assert '_run_alembic(scratch_url, "upgrade", BEHAVIOR_HEAD)' in source


def test_historical_migration_oracle_checks_drift_only_after_current_head() -> None:
    source = inspect.getsource(_gate_module()._migration_and_schema_probe)
    pinned_upgrade = source.index('_run_alembic(scratch_url, "upgrade", PINNED_HEAD)')
    current_upgrade = source.index(
        '_run_alembic(scratch_url, "upgrade", BEHAVIOR_HEAD)',
        pinned_upgrade,
    )
    drift_check = source.index('_run_alembic(scratch_url, "check")')
    assert pinned_upgrade < current_upgrade < drift_check


def test_behavior_profile_fixture_adds_one_key_without_collapsing_headers() -> None:
    gate = _gate_module()
    duplicate_origin = [
        ("Origin", "https://first.invalid"),
        ("Origin", "https://second.invalid"),
    ]
    augmented = gate._profile_mutation_headers(
        "/api/v1/student/profile/personal",
        duplicate_origin,
        "nyay5-fixture-idempotency-0001",
    )
    assert augmented == [
        *duplicate_origin,
        ("Idempotency-Key", "nyay5-fixture-idempotency-0001"),
    ]
    assert gate._profile_mutation_headers(
        "/api/v1/student/profile/personal",
        [("idempotency-key", "caller-owned")],
        "must-not-replace",
    ) == [("idempotency-key", "caller-owned")]
    assert gate._profile_mutation_headers(
        "/api/v1/student/profile/prompt-dismiss",
        duplicate_origin,
        "must-not-add",
    ) == duplicate_origin


def test_behavior_projection_oracle_includes_server_derived_requirements() -> None:
    source = inspect.getsource(_gate_module()._behavior_probe)
    exact_top = source[source.index("exact_top = {") : source.index("nested = body.get")]
    assert '"missing_requirements"' in exact_top


def test_behavior_gate_serializes_dob_with_both_credential_creation_paths() -> None:
    gate = _gate_module()
    assert {
        "share_projection_dob_serialized",
        "verification_token_dob_serialized",
    } <= gate._BEHAVIOR_OBSERVATION_KEYS
    source = GATE.read_text(encoding="utf-8")
    assert "sharing_entered.wait" in source
    assert "token_entered.wait" in source
    assert "not share_future.done()" in source
    assert "not token_future.done()" in source
    assert 'guardian.status = "verified"' in source
    assert "guardian.verified = True" in source


def test_behavior_gate_linearizes_cookie_lifecycle_against_effects() -> None:
    gate = _gate_module()
    assert {
        "profile_session_lifecycle_serialized",
        "reviewer_session_lifecycle_serialized",
        "share_session_lifecycle_serialized",
        "token_session_lifecycle_serialized",
        "login_rotation_no_deadlock",
    } <= gate._BEHAVIOR_OBSERVATION_KEYS
    source = GATE.read_text(encoding="utf-8")
    assert "run_effect_lifecycle_race" in source
    assert "profile-personal" in source
    assert "reviewer-verification" in source
    assert "share-projection" in source
    assert "verification-token" in source
    assert ".with_for_update()" in source
    assert "lifecycle_lock_entered.wait" in source
    assert "logout_entered.wait" in source
    assert "rotation_attempt_entered.wait" in source
    assert "postgres_lock_wait_observed" in source
    assert "pg_blocking_pids" in source
    assert "pg_stat_activity" in source
    assert 'wait_event_type == "Lock"' in source
    assert "lifecycle_native_wait" in source
    assert "mutation_native_wait" in source
    assert "not lifecycle_first_future.done()" in source
    assert "not mutation_first_logout.done()" in source
    assert '"session_authority_required"' in source
    assert '"authentication_required"' in source
    effect_lock_source = inspect.getsource(
        login_service.lock_presented_session_for_effect
    )
    user_lock_source = inspect.getsource(
        login_service.lock_user_for_session_rotation
    )
    assert effect_lock_source.index("user = lock_user_for_session_rotation(") < (
        effect_lock_source.index("auth_session = session.scalar(")
    )
    assert ".with_for_update()" in user_lock_source
    assert ".execution_options(populate_existing=True)" in user_lock_source


def test_behavior_gate_linearizes_m01_completion_against_exact_admin_logout() -> None:
    gate = _gate_module()
    assert "m01_completion_session_lifecycle_serialized" in gate._BEHAVIOR_OBSERVATION_KEYS
    assert "BYPASS-M01-EXACT-EFFECT-SESSION-LOCK" in gate.REQUIRED_MUTANT_IDS
    source = GATE.read_text(encoding="utf-8")
    assert "m01-completion-lifecycle-first" in source
    assert "m01-completion-mutation-first" in source
    assert '"/api/v1/tutoring/sessions/{}/complete"' in source
    assert "m01_effect_snapshot" in source
    assert "SessionAttendance" in source
    assert "SessionStatusHistory" in source
    assert "BookingEvent" in source
    assert "TutoringOutbox" in source
    assert "bypass_m01_effect_lock" in source
    assert "m01_bypass_mutant_killed" in source
    assert '"status": tutoring_session.status' in source
    assert '"version": tutoring_session.version' in source
    assert (
        'behavior.get("m01_completion_session_lifecycle_serialized") is True'
        in source
    )
    assert '"session_authority_required"' in source


def test_behavior_gate_reauthenticates_unique_losers_after_rollback() -> None:
    gate = _gate_module()
    assert {
        "credential_unique_loser_reauthenticated",
        "share_unique_fault_reauthenticated",
        "token_unique_fault_reauthenticated",
    } <= gate._BEHAVIOR_OBSERVATION_KEYS
    source = GATE.read_text(encoding="utf-8")
    assert "run_unique_loser_reauthentication" in source
    assert "unique_gap_entered.wait" in source
    assert "original_session_rollback" in source
    assert "stale_discovery_hidden" in source
    assert "_CREDENTIAL_IDEMPOTENCY_CONSTRAINT" in source
    assert "_SHARE_IDEMPOTENCY_CONSTRAINT" in source
    assert "_TOKEN_IDEMPOTENCY_CONSTRAINT" in source
    assert "_TOKEN_HASH_CONSTRAINT" in source
    assert '"authentication_required"' in source
    credential_case = source[
        source.index("credential_loser_gate = run_unique_loser_reauthentication(") :
        source.index(
            'observations["credential_unique_loser_reauthenticated"]'
        )
    ]
    assert "stale_discovery_fault=True" in credential_case
    assert "concurrent_winner=" not in credential_case
    assert "credential_flush_entered" not in source


def test_gate_oracles_fail_closed_on_runtime_inventory_and_privacy_mutants() -> None:
    gate = _gate_module()
    passing = [gate._assertion(identifier, True) for identifier in gate.REQUIRED_ASSERTION_IDS]
    assert gate._evaluate_assertions(passing)["overall_pass"] is True
    assert gate._evaluate_assertions(list(reversed(passing)))["overall_pass"] is False
    assert gate._evaluate_assertions(passing[:-1])["overall_pass"] is False
    assert gate._evaluate_assertions([*passing, passing[-1]])["overall_pass"] is False
    assert gate._is_postgresql_16_with_pgvector(160000, "0.8.1") is True
    assert gate._is_postgresql_16_with_pgvector(150000, "0.8.1") is False
    assert gate._is_postgresql_16_with_pgvector(160000, None) is False
    assert gate._privacy_findings({"status": "PASS", "mobile": "9876543210"})
    mutant_results = gate._seeded_mutant_results()
    assert tuple(mutant_results) == gate.REQUIRED_MUTANT_IDS
    assert all(value is True for value in mutant_results.values())
    assert gate._seeded_mutants_are_killed() is True
    mutant_source = inspect.getsource(gate._seeded_mutant_results)
    assert "mutant[field] = unsafe" not in mutant_source
    assert "actual_fixture_mutation" in mutant_source
    assert "_safe_local_postgres_url" in mutant_source
    assert "pyinspect.getsource(profile_service._cas)" in mutant_source
    assert "PINNED_HEAD_PATH.read_bytes()" in mutant_source


def test_control_url_requires_a_literal_loopback_ip(monkeypatch) -> None:
    gate = _gate_module()
    for key in gate.LIBPQ_AMBIENT_KEYS:
        monkeypatch.delenv(key, raising=False)
    accepted = gate._safe_local_postgres_url(
        "postgresql://postgres:synthetic@127.0.0.1:5432/postgres"
    )
    assert accepted.host == "127.0.0.1"
    for rejected in (
        "postgresql://postgres:synthetic@localhost:5432/postgres",
        "postgresql://postgres:synthetic@database.internal:5432/postgres",
    ):
        with pytest.raises(gate.Blocked):
            gate._safe_local_postgres_url(rejected)


def test_schema_and_populated_oracles_require_exact_observation_shape() -> None:
    gate = _gate_module()
    baseline = gate._oracle_baselines()
    assert gate._schema_observation_passes(baseline["schema"]) is True
    assert gate._populated_observation_passes(baseline["populated"]) is True
    schema_extra = {**baseline["schema"], "unverified": True}
    assert gate._schema_observation_passes(schema_extra) is False
    populated_weak = {**baseline["populated"], "refusal_atomic": False}
    assert gate._populated_observation_passes(populated_weak) is False


def test_scratch_manager_proves_global_prefix_inventory_restored(monkeypatch) -> None:
    gate = _gate_module()
    inventory: set[str] = set()

    monkeypatch.setattr(gate, "_scratch_database_inventory", lambda _base: set(inventory))

    def create(_base, name):
        inventory.add(name)
        return "postgresql://127.0.0.1/scratch"

    monkeypatch.setattr(gate, "_create_scratch", create)
    monkeypatch.setattr(gate, "_drop_scratch", lambda _base, name: inventory.discard(name))
    manager = gate._ScratchDatabaseManager(object())
    assert manager.run("migration", lambda url: url).endswith("/scratch")
    assert manager.summary() == {
        "created": 1,
        "removed": 1,
        "cleanup_failed": 0,
        "all_created_removed": True,
        "inventory_match": True,
        "baseline_count": 0,
        "final_count": 0,
        "purposes": ["migration"],
    }
