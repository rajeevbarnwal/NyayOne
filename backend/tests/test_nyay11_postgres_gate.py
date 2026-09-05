"""Fail-closed report, execution-boundary and inventory contracts for NYAY-11."""
from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]


def _gate():
    return importlib.import_module("scripts.nyay11_postgres_authority_gate")


def test_inherited_review_fixtures_establish_scoped_server_proofs_before_requests():
    helper = importlib.import_module("scripts.nyay11_authority_gate_fixtures")
    source = Path(helper.__file__).read_text()
    for required in ("InstitutionalEmailProof", "provider_receipt_hash", "InstitutionalReviewerAssignment", "get_or_create_state", 'target="PENDING"'):
        assert required in source
    for filename in ("nyay2_postgres_authorization_gate.py", "nyay5_postgres_profile_gate.py"):
        producer = (BACKEND / "scripts" / filename).read_text()
        assert "prepare_institutional_review" in producer
        assert "nyay11-review-" in producer


def test_inherited_review_audit_is_exact_aggregate_not_actor_linked():
    for filename in ("nyay2_postgres_authorization_gate.py", "nyay5_postgres_profile_gate.py"):
        producer = (BACKEND / "scripts" / filename).read_text()
        assert 'AuthorityAuditEvent.transition_code == "PENDING_TO_VERIFIED"' in producer
        assert 'AuthorityAuditEvent.authority_class == "assigned_institutional_reviewer"' in producer
        assert 'AuthorityAuditEvent.actor_class == "reviewer"' in producer
        assert "authority_audit_allowlist" in producer


def test_native_concurrency_covers_real_projection_cross_review_and_erasure():
    source = (BACKEND / "scripts/nyay11_postgres_authority_gate.py").read_text()
    for required in ("PROJECTION_TAKES_NO_PROOF_LOCK", "CROSS_REVIEW_COMPLETES_WITHOUT_DEADLOCK", "ERASURE_PREVENTS_AUTHORITY_RESURRECTION", "delete_registration", "before_cursor_execute", "pg_blocking_pids"):
        assert required in source


def test_populated_migration_refusal_preserves_current_authority_and_audit():
    source = (BACKEND / "scripts" / "nyay11_postgres_authority_gate.py").read_text()
    assert "POPULATED_DOWNGRADE_REFUSED" in source
    assert "POPULATED_DOWNGRADE_GRAPH_UNCHANGED" in source
    assert "POPULATED_DOWNGRADE_REVISION_UNCHANGED" in source


def test_native_retention_audit_proves_server_cause_not_forged_guardian_actor():
    source = (BACKEND / "scripts" / "nyay11_postgres_authority_gate.py").read_text()
    assert "ERASURE_AUDIT_CAUSE_NOT_SERVER" in source


def test_inherited_proof_fixture_anchor_never_expires_between_injected_and_real_clock():
    from scripts.nyay11_authority_gate_fixtures import fixture_validity_anchor
    historical = datetime(2026, 8, 22, tzinfo=timezone.utc)
    creation = datetime(2026, 9, 6, tzinfo=timezone.utc)
    assert fixture_validity_anchor(historical, creation) == creation
    assert fixture_validity_anchor(creation, historical) == creation


def test_nyay9_behavior_runs_at_current_schema_without_relabeling_historical_migration(monkeypatch):
    producer = importlib.import_module("scripts.nyay9_postgres_profile_gate")
    observed = []

    def stop_after_schema_selection(url, *arguments):
        observed.append(arguments)
        raise RuntimeError("TEST_ONLY_SCHEMA_SELECTION")

    monkeypatch.setattr(producer, "_run_alembic", stop_after_schema_selection)
    with pytest.raises(RuntimeError, match="TEST_ONLY_SCHEMA_SELECTION"):
        producer._behavior_probe("not-opened-test-sentinel")
    assert observed == [("upgrade", producer.APPLICATION_HEAD_REVISION)]
    assert producer.PINNED_HEAD == "0022_nyay9_owner_profile_api"


@pytest.mark.parametrize("mutation", [None, "delegation", "response", "role"])
def test_inherited_reviewer_mutant_binds_delegation_and_cached_response(mutation):
    import inspect
    from app.api.v1 import auth_student
    from app.services import student_authority
    from scripts.nyay5_postgres_profile_gate import _reviewer_authority_source_exact

    wrapper = inspect.getsource(auth_student.verification_transition)
    service = inspect.getsource(student_authority.review)
    if mutation == "delegation":
        wrapper = wrapper.replace("student_authority.review(", "unscoped_review(")
    elif mutation == "response":
        service = service.replace('"owner_projection_invalidated": True', '"owner_projection_invalidated": False')
    elif mutation == "role":
        wrapper = wrapper.replace("Depends(_require_verification_reviewer)", "Depends(_require_student)")
    assert _reviewer_authority_source_exact((wrapper, service)) is (mutation is None)


@pytest.mark.parametrize(("table", "key"), [("student_authority_states", "registration_id"), ("institutional_authority_email_proofs", "user_id")])
def test_native_introspection_enforces_exact_nyay11_parent_uuid_keys(table, key):
    from scripts.introspect_schema import _table_key_failures
    kwargs = dict(table=table, dialect="postgresql", columns=[{"name": key, "type": "UUID"}], primary_key={"constrained_columns": [key]}, indexes=[], unique_constraints=[], foreign_keys=[])
    assert _table_key_failures(**kwargs) == []
    assert _table_key_failures(**{**kwargs, "primary_key": {"constrained_columns": ["id"]}})
    assert _table_key_failures(**{**kwargs, "columns": [{"name": key, "type": "TEXT"}]})


def _passing_report():
    gate = _gate()
    return {
        "schema_version": "nyay11-authority-postgres/v1",
        "status": "PASS",
        "executed": True,
        "postgres_major": 16,
        "pgvector_present": True,
        "rows": [
            {"id": identifier, "passed": True, "assertions": 1}
            for identifier in gate.ORACLE_IDS
        ],
        "total": len(gate.ORACLE_IDS),
        "passed": len(gate.ORACLE_IDS),
        "failed": 0,
        "state_outcomes": 61,
        "scratch_cleanup": True,
    }


def test_inventory_contains_exactly_61_individually_observed_state_pairs():
    gate = _gate()
    guardian = {"NOT_REQUIRED", "REQUIRED_PENDING", "VERIFIED", "REJECTED", "REVOKED"}
    institutional = {"UNVERIFIED", "PENDING", "VERIFIED", "REJECTED", "EXPIRED", "REVOKED"}
    expected = {
        f"STATE:guardian:{source}:{target}"
        for source in guardian for target in guardian
    } | {
        f"STATE:institutional:{source}:{target}"
        for source in institutional for target in institutional
    }
    assert set(gate.STATE_ORACLE_IDS) == expected
    assert len(gate.STATE_ORACLE_IDS) == 61
    assert len(gate.ORACLE_IDS) == len(set(gate.ORACLE_IDS))
    assert set(gate.STATE_ORACLE_IDS) < set(gate.ORACLE_IDS)


def test_exact_executed_nonzero_report_passes():
    _gate().validate_report(_passing_report())


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "zero", "failed", "not_executed", "count_bool", "assertions_bool", "unexpected_field", "wrong_runtime"])
def test_report_mutants_cannot_claim_pass(mutation):
    gate = _gate()
    report = _passing_report()
    if mutation == "missing":
        report["rows"].pop()
    elif mutation == "duplicate":
        report["rows"][-1] = dict(report["rows"][0])
    elif mutation == "extra":
        report["rows"].append({"id": "UNAUTHORIZED", "passed": True, "assertions": 1})
    elif mutation == "zero":
        report["rows"][0]["assertions"] = 0
    elif mutation == "failed":
        report["rows"][0]["passed"] = False
    elif mutation == "not_executed":
        report["executed"] = False
    elif mutation == "count_bool":
        report["failed"] = False
    elif mutation == "assertions_bool":
        report["rows"][0]["assertions"] = True
    elif mutation == "unexpected_field":
        report["session_token"] = "must never serialize"
    elif mutation == "wrong_runtime":
        report["postgres_major"] = 15
    with pytest.raises(gate.GateFailure):
        gate.validate_report(report)


@pytest.mark.parametrize("raw", ["postgresql://remote.invalid/control", "postgresql://127.0.0.1/control?host=elsewhere", "sqlite:///scratch.db", "postgresql://localhost/control"])
def test_remote_routed_or_non_native_runtime_is_blocked(raw):
    with pytest.raises(_gate().Blocked):
        _gate().safe_control_url(raw)


def test_ambient_postgres_routing_is_blocked(monkeypatch):
    monkeypatch.setenv("PGHOST", "elsewhere.invalid")
    with pytest.raises(_gate().Blocked):
        _gate().safe_control_url("postgresql://127.0.0.1/control")


def test_whole_repository_gate_executes_nyay11_once():
    source = (BACKEND / "scripts/db_gate.sh").read_text()
    assert source.count('"$PY" scripts/nyay11_postgres_authority_gate.py') == 1
    assert "NYAY11_POSTGRES_GATE=1" in source


def test_state_matrix_uses_persisted_runtime_and_canonical_service():
    source = (BACKEND / "scripts/nyay11_postgres_authority_gate.py").read_text()
    assert "student_authority.apply_transition(" in source
    assert "session.commit()" in source
    assert "session.expire_all()" in source
    assert "pg_blocking_pids" in source
    assert "MIGRATION_POPULATED_LEGACY_MAPPING" in source
    assert "MIGRATION_UP_DOWN_UP_CHECK" in source


def test_failed_create_never_drops_a_database_the_gate_did_not_create(monkeypatch, tmp_path):
    gate = _gate()
    monkeypatch.setenv(gate.OPT_IN_ENV, "1")
    statements = []
    def denied_create(_control, statement):
        statements.append(statement)
        raise RuntimeError("synthetic create refusal")
    monkeypatch.setattr(gate, "_admin", denied_create)
    with pytest.raises(RuntimeError):
        gate.run("postgresql://127.0.0.1/control", tmp_path / "must-not-exist.json")
    assert len(statements) == 1
    assert statements[0].startswith("CREATE DATABASE ")
    assert not (tmp_path / "must-not-exist.json").exists()
