"""Pure harness tests for the opt-in NYAY-2 PostgreSQL authorization gate.

These tests prove fail-closed routing, exact assertion inventory, cleanup, and
aggregate evidence privacy.  They do not claim PostgreSQL/API behavior; that
evidence comes only from executing ``scripts/nyay2_postgres_authorization_gate``
against the disposable PostgreSQL 16 + pgvector runtime.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import scripts.nyay2_postgres_authorization_gate as gate
from scripts.nyay2_postgres_authorization_gate import (
    BLOCKED_EXIT,
    LIBPQ_AMBIENT_KEYS,
    ORIGIN_MATRIX_CASES,
    REQUIRED_ASSERTION_IDS,
    Blocked,
    ProductGateFailure,
    ScratchCleanupFailure,
    _ScratchDatabaseManager,
    _business_state_digest,
    _bootstrap_expiry_passes,
    _evaluate_assertions,
    _is_postgresql_16_with_pgvector,
    _privacy_findings,
    _reject_ambient_libpq_environment,
    _safe_local_postgres_url,
    _safe_response_signature,
    _seed_actor,
)


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
def test_ambient_libpq_authority_is_rejected_without_value_disclosure(monkeypatch, key):
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
def test_safe_url_rejects_every_query_routing_surface(url):
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
def test_safe_url_accepts_only_query_free_loopback_authority(url):
    parsed = _safe_local_postgres_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert not parsed.query


@pytest.mark.parametrize(
    "url, message",
    (
        ("sqlite:///tmp/qa.db", "PostgreSQL URL is required"),
        (
            "postgresql+psycopg://qa:secret@example.invalid:5432/postgres",
            "accepts loopback PostgreSQL only",
        ),
        (
            "postgresql+psycopg://qa:p%40ss@localhost:5432/postgres",
            "authority is ambiguous",
        ),
        (
            "postgresql+psycopg://qa:secret@localhost@evil.invalid:5432/postgres",
            "authority is ambiguous",
        ),
        (
            "postgresql+psycopg://qa:secret@local%68ost:5432/postgres",
            "authority is ambiguous",
        ),
    ),
)
def test_safe_url_rejects_dialect_remote_and_ambiguous_authority(url, message):
    with pytest.raises(Blocked, match=message):
        _safe_local_postgres_url(url)


def _passing_assertions() -> list[dict]:
    return [
        {"id": identifier, "passed": True, "metrics": {}}
        for identifier in REQUIRED_ASSERTION_IDS
    ]


def test_evaluator_requires_exact_inventory_and_every_true():
    evaluation = _evaluate_assertions(_passing_assertions())
    assert evaluation == {
        "exact_inventory": True,
        "required": len(REQUIRED_ASSERTION_IDS),
        "passed": len(REQUIRED_ASSERTION_IDS),
        "failed": [],
        "inventory_failures": {
            "missing": 0,
            "extra": 0,
            "duplicate": 0,
            "reordered": False,
        },
        "overall_pass": True,
    }


@pytest.mark.parametrize(
    "version_num, vector_version, expected",
    (
        (159999, "0.8.6", False),
        (160000, "0.8.6", True),
        (169999, "0.8.6", True),
        (170000, "0.8.6", False),
        (180000, "0.8.6", False),
        (160000, None, False),
        (160000, "", False),
    ),
)
def test_runtime_is_pinned_to_postgresql_major_16_with_pgvector(
    version_num, vector_version, expected
):
    assert _is_postgresql_16_with_pgvector(version_num, vector_version) is expected


@pytest.mark.parametrize("identifier", REQUIRED_ASSERTION_IDS)
def test_each_required_assertion_independently_fails_the_gate(identifier):
    assertions = _passing_assertions()
    next(item for item in assertions if item["id"] == identifier)["passed"] = False
    evaluation = _evaluate_assertions(assertions)
    assert evaluation["exact_inventory"] is True
    assert evaluation["overall_pass"] is False
    assert evaluation["failed"] == [identifier]


def test_evaluator_rejects_missing_duplicate_and_substituted_assertions():
    missing = _passing_assertions()[:-1]
    duplicate = _passing_assertions() + [_passing_assertions()[0]]
    substituted = _passing_assertions()
    substituted[-1] = {
        "id": "OPTIONAL-SUBSTITUTE",
        "passed": True,
        "metrics": {},
    }
    for assertions in (missing, duplicate, substituted):
        evaluation = _evaluate_assertions(assertions)
        assert evaluation["exact_inventory"] is False
        assert evaluation["overall_pass"] is False


def test_evaluator_rejects_reordered_exact_assertion_set():
    assertions = _passing_assertions()
    assertions[0], assertions[1] = assertions[1], assertions[0]
    evaluation = _evaluate_assertions(assertions)
    assert evaluation["exact_inventory"] is False
    assert evaluation["inventory_failures"] == {
        "missing": 0,
        "extra": 0,
        "duplicate": 0,
        "reordered": True,
    }
    assert evaluation["overall_pass"] is False


def _passing_bootstrap_expiry_observation() -> dict:
    return {
        "resend_status": 404,
        "resend_code": "registration_not_found",
        "verify_status": 404,
        "verify_code": "no_active_challenge",
        "challenge_delta": 0,
        "outbox_delta": 0,
        "delivery_delta": 0,
        "session_delta": 0,
        "audit_delta": 0,
        "all_security_row_deltas_zero": True,
        "business_state_unchanged": True,
        "cookie_issued": False,
    }


def test_bootstrap_expiry_evaluator_accepts_only_exact_bounded_no_delta_case():
    assert _bootstrap_expiry_passes(_passing_bootstrap_expiry_observation())


@pytest.mark.parametrize(
    "field, unsafe_value",
    (
        ("resend_status", 202),
        ("resend_code", "resend_cooldown"),
        ("verify_status", 200),
        ("verify_code", "incorrect_otp"),
        ("challenge_delta", 1),
        ("outbox_delta", 1),
        ("delivery_delta", 1),
        ("session_delta", 1),
        ("audit_delta", 1),
        ("all_security_row_deltas_zero", False),
        ("business_state_unchanged", False),
        ("cookie_issued", True),
    ),
)
def test_each_bootstrap_expiry_false_green_mutation_is_rejected(field, unsafe_value):
    observation = _passing_bootstrap_expiry_observation()
    observation[field] = unsafe_value
    assert _bootstrap_expiry_passes(observation) is False


def test_business_digest_kills_session_telemetry_mutant(db_session, engine):
    """A denied request cannot false-green after touching session telemetry."""

    from app.models.registration import AuthSession

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    _seed_actor(factory, label="digest-mutant")
    before = _business_state_digest(factory)
    with factory() as session:
        row = session.scalar(select(AuthSession))
        assert row is not None
        row.last_seen_at = row.last_seen_at + timedelta(seconds=1)
        session.commit()
    assert _business_state_digest(factory) != before


def test_business_digest_kills_registration_deleted_at_mutant(db_session, engine):
    """The registration authority bit must participate in the no-delta oracle."""

    from datetime import datetime, timezone

    from app.models.registration import StudentRegistration

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    _seed_actor(factory, label="deleted-at-digest-mutant")
    before = _business_state_digest(factory)
    with factory() as session:
        row = session.scalar(select(StudentRegistration))
        assert row is not None
        row.deleted_at = datetime.now(timezone.utc)
        session.commit()
    assert _business_state_digest(factory) != before


def test_business_digest_kills_challenge_authority_mutant(db_session, engine):
    """A challenge/outbox regression cannot hide behind unchanged row owners."""

    from datetime import datetime, timezone

    from app.core.crypto import otp_verifier
    from app.models.registration import OtpChallenge, StudentRegistration
    from app.services.otp_authority import lock_or_create_registration_authority

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    actor = _seed_actor(factory, label="challenge-mutant")
    before = _business_state_digest(factory)
    now = datetime.now(timezone.utc)
    with factory() as session:
        registration = session.get(StudentRegistration, actor["registration_id"])
        assert registration is not None
        authority = lock_or_create_registration_authority(
            session, registration, "signup", now
        )
        expires_at = now + timedelta(minutes=5)
        session.add(
            OtpChallenge(
                registration_id=actor["registration_id"],
                authority_id=authority.id,
                purpose="signup",
                delivery_state="active",
                verifier_hash=otp_verifier("1" * 6, salt="synthetic-salt"),
                attempts=0,
                max_attempts=3,
                expires_at=expires_at,
                metadata_json={"salt": "synthetic-salt"},
            )
        )
        authority.active_expires_at = expires_at
        session.commit()
    assert _business_state_digest(factory) != before


class _Response:
    def __init__(self, status_code: int, payload, *, json_failure: bool = False):
        self.status_code = status_code
        self.payload = payload
        self.json_failure = json_failure

    def json(self):
        if self.json_failure:
            raise ValueError("not json")
        return self.payload


def test_response_signature_keeps_typed_code_but_not_payload_values():
    secret = "private-value"
    signature = _safe_response_signature(
        _Response(
            403,
            {
                "detail": {
                    "code": "forbidden",
                    "message": secret,
                    "target": "ignored",
                }
            },
        )
    )
    assert signature == {
        "status_code": 403,
        "shape": "typed_detail",
        "code": "forbidden",
    }
    assert secret not in json.dumps(signature)


def test_response_signature_removes_validation_input_and_messages():
    secret = "attacker-controlled-value"
    signature = _safe_response_signature(
        _Response(
            422,
            {
                "detail": [
                    {
                        "type": "extra_forbidden",
                        "loc": ["body", "registration_id"],
                        "msg": secret,
                        "input": secret,
                    }
                ]
            },
        )
    )
    assert signature == {
        "status_code": 422,
        "shape": "validation",
        "errors": [("extra_forbidden", "body.registration_id")],
    }
    assert secret not in json.dumps(signature)


def test_response_signature_classifies_non_json_without_copying_body():
    assert _safe_response_signature(_Response(500, None, json_failure=True)) == {
        "status_code": 500,
        "shape": "non_json",
    }


@pytest.mark.parametrize(
    "value, finding",
    (
        ({"value": "a2ef7107-0f9b-4b8d-b4a1-22e6c4375e9c"}, "uuid"),
        ({"value": "person@example.invalid"}, "email"),
        ({"value": "9876543210"}, "mobile"),
        ({"value": "postgresql://user:secret@localhost/db"}, "database_or_http_url"),
        ({"value": "https://example.invalid/path"}, "database_or_http_url"),
    ),
)
def test_privacy_scan_reports_only_path_and_class(value, finding):
    results = _privacy_findings(value)
    assert results == [f"report.value:{finding}"]
    assert value["value"] not in json.dumps(results)


def test_expected_aggregate_report_shape_is_privacy_safe():
    report = {
        "gate": "nyay2_postgres_authorization",
        "status": "PASS",
        "executed": True,
        "assertions": _passing_assertions(),
        "evaluation": _evaluate_assertions(_passing_assertions()),
        "api_metrics": {
            "real_http_requests_executed": True,
            "negative_controls_executed": 3,
            "protected_routes_checked": 5,
            "protected_uuid_contract_routes_checked": 4,
        },
        "scratch_cleanup": {
            "created": 1,
            "removed": 1,
            "cleanup_failed": 0,
            "all_created_removed": True,
            "purposes": ["authorization"],
        },
    }
    assert _privacy_findings(report) == []


def test_scratch_manager_cleans_after_success(monkeypatch):
    created: list[str] = []
    removed: list[str] = []
    monkeypatch.setattr(
        gate,
        "_create_scratch",
        lambda _base, name: created.append(name) or "postgresql://scratch",
    )
    monkeypatch.setattr(
        gate,
        "_drop_scratch",
        lambda _base, name: removed.append(name),
    )
    manager = _ScratchDatabaseManager(object())
    assert manager.run("authorization", lambda url: url) == "postgresql://scratch"
    assert removed == created
    assert manager.summary() == {
        "created": 1,
        "removed": 1,
        "cleanup_failed": 0,
        "all_created_removed": True,
        "purposes": ["authorization"],
    }


def test_scratch_manager_cleans_when_operation_fails(monkeypatch):
    created: list[str] = []
    removed: list[str] = []
    monkeypatch.setattr(
        gate,
        "_create_scratch",
        lambda _base, name: created.append(name) or "postgresql://scratch",
    )
    monkeypatch.setattr(
        gate,
        "_drop_scratch",
        lambda _base, name: removed.append(name),
    )
    manager = _ScratchDatabaseManager(object())

    def fail(_url):
        raise RuntimeError("forced")

    with pytest.raises(RuntimeError, match="forced"):
        manager.run("authorization", fail)
    assert removed == created
    assert manager.summary()["all_created_removed"] is True


def test_scratch_cleanup_failure_is_fatal_and_sanitized(monkeypatch):
    monkeypatch.setattr(
        gate, "_create_scratch", lambda _base, _name: "postgresql://scratch"
    )

    def fail_drop(_base, _name):
        raise RuntimeError("credential-bearing-driver-error")

    monkeypatch.setattr(gate, "_drop_scratch", fail_drop)
    manager = _ScratchDatabaseManager(object())
    with pytest.raises(
        ScratchCleanupFailure,
        match="disposable NYAY-2 database could not be removed",
    ) as caught:
        manager.run("authorization", lambda _url: True)
    assert "credential-bearing" not in str(caught.value)
    assert manager.summary()["cleanup_failed"] == 1
    assert manager.summary()["all_created_removed"] is False


def test_unsafe_url_is_rejected_before_any_scratch_creation(monkeypatch, capsys):
    calls: list[str] = []
    monkeypatch.setattr(
        gate,
        "_create_scratch",
        lambda *_args: calls.append("created") or "unexpected",
    )
    result = gate.main(
        [
            "--database-url",
            "postgresql+psycopg://qa:secret@example.invalid:5432/postgres",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert result == BLOCKED_EXIT
    assert calls == []
    assert report["status"] == "BLOCKED"
    assert report["executed"] is False
    assert "secret" not in json.dumps(report)


def test_missing_url_is_blocked_without_execution(capsys):
    result = gate.main([])
    report = json.loads(capsys.readouterr().out)
    assert result == BLOCKED_EXIT
    assert report["status"] == "BLOCKED"
    assert report["executed"] is False
    assert report["scratch_cleanup"]["created"] == 0


def test_blocked_after_scratch_creation_reports_executed(monkeypatch, capsys):
    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", _FakeManager)

    def blocked_after_execution(_url):
        raise Blocked("target runtime unavailable")

    monkeypatch.setattr(gate, "_execute", blocked_after_execution)
    result = gate.main(["--database-url", "opaque-test-authority"])
    report = json.loads(capsys.readouterr().out)
    assert result == BLOCKED_EXIT
    assert report["status"] == "BLOCKED"
    assert report["executed"] is True
    assert report["scratch_cleanup"]["created"] == 1
    assert report["scratch_cleanup"]["removed"] == 1


@pytest.mark.parametrize("returncodes", ((1,), (0, 1)))
def test_migration_or_head_failure_is_product_failure_not_blocked(
    monkeypatch, returncodes
):
    outcomes = iter(returncodes)
    monkeypatch.setattr(
        gate,
        "_run_alembic",
        lambda _url, *_arguments: {
            "arguments": [],
            "returncode": next(outcomes),
        },
    )
    with pytest.raises(ProductGateFailure):
        gate._execute("not-retained")


class _FakeManager:
    cleanup_ok = True

    def __init__(self, _base):
        self.scratch_created = True

    def run(self, _purpose, operation):
        return operation("not-retained")

    def summary(self):
        return {
            "created": 1,
            "removed": 1 if self.cleanup_ok else 0,
            "cleanup_failed": 0 if self.cleanup_ok else 1,
            "all_created_removed": self.cleanup_ok,
            "purposes": ["authorization"],
        }


def test_main_pass_requires_exact_assertions_privacy_and_cleanup(
    monkeypatch, capsys, tmp_path: Path
):
    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", _FakeManager)
    monkeypatch.setattr(
        gate,
        "_execute",
        lambda _url: {
            "assertions": _passing_assertions(),
            "api_metrics": {"real_http_requests_executed": True},
        },
    )
    report_path = tmp_path / "aggregate.json"
    result = gate.main(
        [
            "--database-url",
            "opaque-test-authority",
            "--report",
            str(report_path),
        ]
    )
    stdout_report = json.loads(capsys.readouterr().out)
    disk_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 0
    assert stdout_report == disk_report
    assert disk_report["status"] == "PASS"
    assert disk_report["evaluation"]["overall_pass"] is True
    assert disk_report["privacy_scan"] == {
        "scanned": True,
        "findings": 0,
        "passed": True,
    }


def test_main_cannot_pass_when_cleanup_fails(monkeypatch, capsys):
    class CleanupFailManager(_FakeManager):
        cleanup_ok = False

    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", CleanupFailManager)
    monkeypatch.setattr(
        gate,
        "_execute",
        lambda _url: {
            "assertions": _passing_assertions(),
            "api_metrics": {"real_http_requests_executed": True},
        },
    )
    result = gate.main(["--database-url", "opaque-test-authority"])
    report = json.loads(capsys.readouterr().out)
    assert result == 1
    assert report["status"] == "FAIL"
    assert report["evaluation"]["overall_pass"] is False


def test_main_cannot_pass_when_assertion_is_missing(monkeypatch, capsys):
    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", _FakeManager)
    monkeypatch.setattr(
        gate,
        "_execute",
        lambda _url: {
            "assertions": _passing_assertions()[:-1],
            "api_metrics": {"real_http_requests_executed": True},
        },
    )
    result = gate.main(["--database-url", "opaque-test-authority"])
    report = json.loads(capsys.readouterr().out)
    assert result == 1
    assert report["status"] == "FAIL"
    assert report["evaluation"]["exact_inventory"] is False


def test_main_cannot_pass_privacy_leak(monkeypatch, capsys):
    assertions = _passing_assertions()
    assertions[0]["metrics"] = {"forbidden": "a2ef7107-0f9b-4b8d-b4a1-22e6c4375e9c"}
    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", _FakeManager)
    monkeypatch.setattr(
        gate,
        "_execute",
        lambda _url: {
            "assertions": assertions,
            "api_metrics": {"real_http_requests_executed": True},
        },
    )
    result = gate.main(["--database-url", "opaque-test-authority"])
    report = json.loads(capsys.readouterr().out)
    assert result == 1
    assert report["status"] == "FAIL"
    assert report["privacy_scan"]["findings"] == 1


def test_source_contains_real_routes_and_all_five_mutant_oracles():
    source = Path(gate.__file__).read_text(encoding="utf-8")
    for route in (
        gate.PROFILE_PATH,
        gate.EMAIL_PATH,
        gate.STATUS_PATH,
        gate.GUARDIAN_PATH,
        gate.REGISTER_PATH,
        gate.OTP_VERIFY_PATH,
        gate.OTP_RESEND_PATH,
        gate.LOGIN_START_PATH,
        gate.RECOVERY_START_PATH,
    ):
        assert route in source
    assert "unsafe_owned_registration" in source
    assert "original_reviewer_dependency" in source
    assert "original_origin_guard" in source
    assert "unsafe_signup_scope" in source
    assert "unsafe_authorizable" in source
    assert "TestClient" in source


def test_origin_matrix_inventory_is_exact_and_includes_duplicate_header_case():
    labels = tuple(item[0] for item in ORIGIN_MATRIX_CASES)
    assert labels == (
        "missing",
        "null",
        "wildcard",
        "malformed",
        "lookalike",
        "prefix",
        "slash",
        "path",
        "userinfo",
        "query",
        "fragment",
        "cross_scheme",
        "cross_host",
        "cross_port",
        "duplicate",
        "trusted",
    )
    assert ORIGIN_MATRIX_CASES[-2][1] == (gate.TRUSTED_ORIGIN,) * 2
    assert sum(bool(item[2]) for item in ORIGIN_MATRIX_CASES) == 1
