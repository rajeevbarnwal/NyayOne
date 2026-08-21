"""Pure oracles for the opt-in NYAY-17 PostgreSQL idempotency gate.

These tests prove fail-closed routing, exact assertion inventory, evaluator
strictness, aggregate-evidence privacy, and scratch cleanup.  They make no
PostgreSQL or application-behaviour claim; authoritative product evidence is
emitted only by executing the gate against PostgreSQL 16 + pgvector.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import inspect as pyinspect

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, DateTime, Uuid, VARCHAR

import scripts.nyay17_postgres_idempotency_gate as gate
from scripts.nyay17_postgres_idempotency_gate import (
    CANONICAL_FIELD_PATHS,
    LIBPQ_AMBIENT_KEYS,
    REQUIRED_ASSERTION_IDS,
    Blocked,
    ScratchCleanupFailure,
    _ScratchDatabaseManager,
    _base_registration_payload,
    _canonical_equivalent_payloads,
    _canonical_field_mutations,
    _conflict_observation_passes,
    _canonical_schema_check,
    _canonical_schema_default,
    _evaluate_assertions,
    _failed_waiters_observation_passes,
    _failure_replay_observation_passes,
    _is_postgresql_16_with_pgvector,
    _ledger_inventory_observation_passes,
    _migration_inventory_passes,
    _pending_resume_observation_passes,
    _privacy_findings,
    _race_observation_passes,
    _reject_ambient_libpq_environment,
    _replay_observation_passes,
    _retired_observation_passes,
    _safe_local_postgres_url,
    _safe_response_signature,
    _seeded_mutants_are_killed,
)


@pytest.fixture(autouse=True)
def _without_ambient_libpq_authority(monkeypatch):
    for key in tuple(gate.os.environ):
        if key in LIBPQ_AMBIENT_KEYS or key.startswith("PGSSL"):
            monkeypatch.delenv(key, raising=False)


def test_historical_lifecycle_and_current_application_heads_are_separate():
    assert gate.PREVIOUS_REVISION == "0017_registration_invariants"
    assert gate.PINNED_HEAD == "0018_registration_idempotency"
    assert gate.APPLICATION_HEAD == "0020_auth_retention_lifecycle"
    config = Config(str(gate.BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(gate.BACKEND / "app/db/migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [gate.APPLICATION_HEAD]
    otp_security_head = scripts.get_revision("0019_otp_security_authority")
    assert scripts.get_revision(gate.APPLICATION_HEAD).down_revision == otp_security_head.revision
    assert otp_security_head.down_revision == gate.PINNED_HEAD
    behavior_source = pyinspect.getsource(gate._execute_behavior)
    assert '"upgrade", APPLICATION_HEAD' in behavior_source
    assert '"upgrade", PINNED_HEAD' not in behavior_source


@pytest.mark.parametrize(
    "key",
    tuple(sorted(LIBPQ_AMBIENT_KEYS))
    + ("PGSSLMODE", "PGSSLCERT", "PGSSLKEY", "PGSSLROOTCERT"),
)
def test_ambient_libpq_authority_is_rejected_without_value_disclosure(key):
    with pytest.raises(Blocked) as caught:
        _reject_ambient_libpq_environment({key: "sensitive-do-not-copy"})
    assert "sensitive-do-not-copy" not in str(caught.value)


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
        ("sqlite:///tmp/gate.db", "PostgreSQL URL is required"),
        (
            "postgresql+psycopg://qa:secret@example.invalid:5432/postgres",
            "accepts loopback PostgreSQL only",
        ),
        (
            "postgresql+psycopg://qa:p%40ss@localhost:5432/postgres",
            "authority is ambiguous",
        ),
        (
            "postgresql+psycopg://qa:secret@localhost:5432/postgres?host=evil.invalid",
            "rejects PostgreSQL URL queries",
        ),
        (
            "postgresql+psycopg:///postgres?host=%2Fvar%2Frun%2Fpostgresql",
            "rejects PostgreSQL URL queries",
        ),
    ),
)
def test_safe_url_rejects_remote_ambiguous_and_query_routing(url, message):
    with pytest.raises(Blocked, match=message):
        _safe_local_postgres_url(url)


@pytest.mark.parametrize(
    "version_num, vector_version, expected",
    (
        (159999, "0.8.6", False),
        (160000, "0.8.6", True),
        (169999, "0.8.6", True),
        (170000, "0.8.6", False),
        (160000, None, False),
        (160000, "", False),
    ),
)
def test_runtime_pin_is_exact_postgresql_major_16_with_pgvector(
    version_num, vector_version, expected
):
    assert _is_postgresql_16_with_pgvector(version_num, vector_version) is expected


def test_empty_invalid_key_does_not_make_no_echo_oracle_vacuously_false():
    class TypedInvalid(Exception):
        status_code = 422
        code = "invalid_idempotency_key"
        field = "Idempotency-Key"

    empty = TypedInvalid("safe typed rejection")
    opaque = TypedInvalid("safe typed rejection")
    echoed = TypedInvalid("unsafe opaque-token echo")
    assert gate._invalid_key_error_is_exact(empty, "")
    assert gate._invalid_key_error_is_exact(opaque, "opaque-token")
    assert not gate._invalid_key_error_is_exact(echoed, "opaque-token")


@pytest.mark.parametrize(
    "status, expected",
    (("active", True), ("otp_verified", False), ("otp_pending", False)),
)
def test_activation_oracle_pins_real_route_final_state(status, expected):
    assert gate._activation_route_state_is_exact(status) is expected


def test_race_backend_snapshot_excludes_later_terminal_followups():
    assert gate._backend_cardinality_is_exact(2, 2)
    assert not gate._backend_cardinality_is_exact(4, 2)


def test_pending_retention_target_window_excludes_recent_probe_history():
    assert (
        gate.PENDING_RETENTION_TARGET_AGE_DAYS
        > gate.PENDING_RETENTION_CUTOFF_DAYS
        > gate.RECENT_PROBE_HISTORY_AGE_DAYS
    )


def test_check_canonicalizer_accepts_postgresql_any_reflection_exactly():
    reflected = (
        "state = ANY (ARRAY['pending'::character varying, "
        "'succeeded'::character varying, 'failed'::character varying, "
        "'retired'::character varying, 'erased'::character varying]::text[])"
    )
    assert _canonical_schema_check(reflected) == _canonical_schema_check(
        gate._LEDGER_STATE_SQL
    )


def test_check_and_default_canonicalizers_reject_hostile_semantic_drift():
    wrong_literal = gate._LEDGER_STATE_SQL.replace("'failed'", "'failure'")
    wrong_grouping = (
        "idempotency_key IS NULL AND (idempotency_key_legacy = false OR "
        "idempotency_key IS NOT NULL) AND idempotency_key_legacy = true"
    )
    assert _canonical_schema_check(wrong_literal) != _canonical_schema_check(
        gate._LEDGER_STATE_SQL
    )
    assert _canonical_schema_check(wrong_grouping) != _canonical_schema_check(
        gate._REGISTRATION_LEGACY_SQL
    )
    assert _canonical_schema_default("now()") == "now()"
    assert _canonical_schema_default("CURRENT_TIMESTAMP") == "current_timestamp"
    assert _canonical_schema_default("now() + interval '1 second'") not in {
        "now()",
        "current_timestamp",
    }


class _SchemaInspectorFixture:
    def __init__(self):
        self.columns = {
            "registration_idempotency_records": [
                {"name": "id", "type": Uuid(), "nullable": False, "default": None},
                {
                    "name": "idempotency_key_hash",
                    "type": VARCHAR(64),
                    "nullable": False,
                    "default": None,
                },
                {
                    "name": "request_fingerprint",
                    "type": VARCHAR(64),
                    "nullable": True,
                    "default": None,
                },
                {
                    "name": "request_fingerprint_version",
                    "type": VARCHAR(16),
                    "nullable": True,
                    "default": None,
                },
                {
                    "name": "state",
                    "type": VARCHAR(24),
                    "nullable": False,
                    "default": None,
                },
                {
                    "name": "outcome_code",
                    "type": VARCHAR(40),
                    "nullable": True,
                    "default": None,
                },
                {
                    "name": "registration_id",
                    "type": Uuid(),
                    "nullable": True,
                    "default": None,
                },
                {
                    "name": "outbox_id",
                    "type": Uuid(),
                    "nullable": True,
                    "default": None,
                },
                {
                    "name": "created_at",
                    "type": DateTime(timezone=True),
                    "nullable": False,
                    "default": "now()",
                },
                {
                    "name": "updated_at",
                    "type": DateTime(timezone=True),
                    "nullable": False,
                    "default": "CURRENT_TIMESTAMP",
                },
            ],
            "student_registrations": [
                {
                    "name": "idempotency_key",
                    "type": VARCHAR(200),
                    "nullable": True,
                    "default": None,
                },
                {
                    "name": "idempotency_key_legacy",
                    "type": Boolean(),
                    "nullable": False,
                    "default": "false",
                },
            ],
        }
        self.uniques = {
            "registration_idempotency_records": [
                {
                    "name": "uq_registration_idempotency_records_idempotency_key_hash",
                    "column_names": ["idempotency_key_hash"],
                },
                {
                    "name": "uq_registration_idempotency_records_registration_id",
                    "column_names": ["registration_id"],
                },
                {
                    "name": "uq_registration_idempotency_records_outbox_id",
                    "column_names": ["outbox_id"],
                },
            ],
            "student_registrations": [
                {
                    "name": "uq_student_registrations_idempotency_key",
                    "column_names": ["idempotency_key"],
                }
            ],
        }
        self.pk = {
            "name": "pk_registration_idempotency_records",
            "constrained_columns": ["id"],
        }
        self.foreign_keys = [
            {
                "name": "fk_reg_idem_registration",
                "constrained_columns": ["registration_id"],
                "referred_schema": None,
                "referred_table": "student_registrations",
                "referred_columns": ["id"],
                "options": {"ondelete": "SET NULL"},
            },
            {
                "name": "fk_reg_idem_outbox",
                "constrained_columns": ["outbox_id"],
                "referred_schema": None,
                "referred_table": "otp_outbox",
                "referred_columns": ["id"],
                "options": {"ondelete": "SET NULL"},
            },
        ]
        self.checks = {
            "registration_idempotency_records": [
                {
                    "name": "ck_registration_idempotency_records_state",
                    "sqltext": gate._LEDGER_STATE_SQL,
                },
                {
                    "name": "ck_registration_idempotency_records_key_hash_shape",
                    "sqltext": gate._LEDGER_KEY_HASH_SQL,
                },
                {
                    "name": "ck_registration_idempotency_records_request_fingerprint_shape",
                    "sqltext": gate._LEDGER_REQUEST_HASH_SQL,
                },
                {
                    "name": "ck_registration_idempotency_records_state_links",
                    "sqltext": gate._LEDGER_STATE_LINKS_SQL,
                },
            ],
            "student_registrations": [
                {
                    "name": "ck_student_registrations_idempotency_key_legacy",
                    "sqltext": gate._REGISTRATION_LEGACY_SQL,
                }
            ],
        }

    def get_table_names(self):
        return list(self.columns)

    def get_columns(self, table):
        return self.columns[table]

    def get_pk_constraint(self, _table):
        return self.pk

    def get_unique_constraints(self, table):
        return self.uniques[table]

    def get_foreign_keys(self, table):
        return self.foreign_keys if table == "registration_idempotency_records" else []

    def get_check_constraints(self, table):
        return self.checks[table]


def _schema_column(fixture, name):
    return next(
        item
        for item in fixture.columns["registration_idempotency_records"]
        if item["name"] == name
    )


def test_schema_inventory_accepts_only_the_exact_reflected_definition(monkeypatch):
    fixture = _SchemaInspectorFixture()
    monkeypatch.setattr(gate, "inspect", lambda _engine: fixture)
    assert _migration_inventory_passes(object())


@pytest.mark.parametrize(
    "mutate",
    (
        lambda f: f.pk["constrained_columns"].append("state"),
        lambda f: f.uniques["registration_idempotency_records"].append(
            {"name": None, "column_names": ["state"]}
        ),
        lambda f: f.foreign_keys.append(
            {
                "name": None,
                "constrained_columns": ["id"],
                "referred_schema": None,
                "referred_table": "users",
                "referred_columns": ["id"],
                "options": {},
            }
        ),
        lambda f: f.foreign_keys[0]["options"].update(deferrable="true"),
        lambda f: f.foreign_keys[0].update(referred_table="users"),
        lambda f: f.checks["registration_idempotency_records"].append(
            {"name": None, "sqltext": "state IS NOT NULL"}
        ),
        lambda f: f.checks["registration_idempotency_records"][0].update(
            sqltext=gate._LEDGER_STATE_SQL.replace("'failed'", "'failure'")
        ),
        lambda f: _schema_column(f, "state").update(type=VARCHAR(25)),
        lambda f: _schema_column(f, "created_at").update(type=DateTime(timezone=False)),
        lambda f: _schema_column(f, "updated_at").update(
            default="now() + interval '1 second'"
        ),
        lambda f: f.columns["student_registrations"][0].update(default="'legacy'"),
        lambda f: f.columns["student_registrations"][0].update(type=Boolean()),
        lambda f: f.uniques["student_registrations"][0].update(
            name="uq_student_registrations_idempotency_key_near_miss"
        ),
        lambda f: f.checks["student_registrations"][0].update(
            sqltext="idempotency_key IS NULL"
        ),
    ),
)
def test_schema_inventory_kills_definition_mutants(monkeypatch, mutate):
    fixture = _SchemaInspectorFixture()
    mutate(fixture)
    monkeypatch.setattr(gate, "inspect", lambda _engine: fixture)
    assert not _migration_inventory_passes(object())


def _passing_assertions() -> list[dict]:
    return [
        {"id": identifier, "passed": True, "metrics": {}}
        for identifier in REQUIRED_ASSERTION_IDS
    ]


def test_evaluator_requires_exact_inventory_in_exact_order_and_every_true():
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


@pytest.mark.parametrize("identifier", REQUIRED_ASSERTION_IDS)
def test_each_required_assertion_independently_fails_the_gate(identifier):
    assertions = _passing_assertions()
    next(item for item in assertions if item["id"] == identifier)["passed"] = False
    evaluation = _evaluate_assertions(assertions)
    assert evaluation["exact_inventory"] is True
    assert evaluation["overall_pass"] is False
    assert evaluation["failed"] == [identifier]


def test_evaluator_rejects_missing_duplicate_substituted_and_reordered():
    variants = []
    variants.append(_passing_assertions()[:-1])
    variants.append(_passing_assertions() + [_passing_assertions()[0]])
    substituted = _passing_assertions()
    substituted[-1] = {"id": "OPTIONAL-SUBSTITUTE", "passed": True, "metrics": {}}
    variants.append(substituted)
    reordered = _passing_assertions()
    reordered[0], reordered[1] = reordered[1], reordered[0]
    variants.append(reordered)
    for assertions in variants:
        evaluation = _evaluate_assertions(assertions)
        assert evaluation["exact_inventory"] is False
        assert evaluation["overall_pass"] is False


def _graph(one: bool = True) -> dict[str, int]:
    return {
        "users": int(one),
        "student_registrations": int(one),
        "student_profiles": int(one),
        "student_verifications": int(one),
        "guardian_consents": 0,
        "consents": int(one),
        "otp_challenges": int(one),
        "otp_outbox": int(one),
        "audit_events": int(one),
    }


def _replay() -> dict:
    return {
        "first_status": 201,
        "first_literal_pending": True,
        "replay_status": 201,
        "same_public_handle": True,
        "initial_graph_delta": _graph(),
        "replay_graph_delta": _graph(False),
        "replay_ledger_delta": 0,
        "replay_delivery_delta": 0,
        "replay_state_unchanged": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("first_status", 200),
        ("first_literal_pending", False),
        ("replay_status", 409),
        ("same_public_handle", False),
        ("replay_ledger_delta", 1),
        ("replay_delivery_delta", 1),
        ("replay_state_unchanged", False),
    ),
)
def test_replay_evaluator_rejects_each_top_level_false_green(field, unsafe):
    observation = _replay()
    assert _replay_observation_passes(observation)
    observation[field] = unsafe
    assert not _replay_observation_passes(observation)


@pytest.mark.parametrize("table", tuple(_graph()))
def test_replay_evaluator_rejects_each_graph_delta_mutant(table):
    observation = _replay()
    observation["replay_graph_delta"][table] += 1
    assert not _replay_observation_passes(observation)


def _conflict() -> dict:
    return {
        "status": 409,
        "error_code": "idempotency_conflict",
        "error_field": "Idempotency-Key",
        "graph_delta": _graph(False),
        "ledger_delta": 0,
        "delivery_delta": 0,
        "state_unchanged": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("status", 201),
        ("error_code", "mobile_already_registered"),
        ("error_field", "mobile"),
        ("ledger_delta", 1),
        ("delivery_delta", 1),
        ("state_unchanged", False),
    ),
)
def test_conflict_evaluator_rejects_each_top_level_false_green(field, unsafe):
    observation = _conflict()
    assert _conflict_observation_passes(observation)
    observation[field] = unsafe
    assert not _conflict_observation_passes(observation)


@pytest.mark.parametrize("table", tuple(_graph()))
def test_conflict_evaluator_rejects_each_graph_side_effect(table):
    observation = _conflict()
    observation["graph_delta"][table] += 1
    assert not _conflict_observation_passes(observation)


def _retired() -> dict:
    return {
        "matching_status": 409,
        "mismatched_status": 409,
        "matching_code": "registration_replay_expired",
        "mismatched_code": "registration_replay_expired",
        "matching_field": "Idempotency-Key",
        "mismatched_field": "Idempotency-Key",
        "uniform_signature": True,
        "graph_delta": _graph(False),
        "ledger_delta": 0,
        "delivery_delta": 0,
        "state_unchanged": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("matching_status", 201),
        ("mismatched_status", 201),
        ("matching_code", "idempotency_conflict"),
        ("mismatched_code", "idempotency_conflict"),
        ("matching_field", "mobile"),
        ("mismatched_field", "mobile"),
        ("uniform_signature", False),
        ("ledger_delta", 1),
        ("delivery_delta", 1),
        ("state_unchanged", False),
    ),
)
def test_retired_evaluator_rejects_match_oracle_and_side_effects(field, unsafe):
    observation = _retired()
    assert _retired_observation_passes(observation)
    observation[field] = unsafe
    assert not _retired_observation_passes(observation)


def _same_race() -> dict:
    return {
        "statuses": [201] * 8,
        "conflict_codes": [],
        "conflict_fields": [],
        "same_public_handle": True,
        "graph_delta": _graph(),
        "ledger_delta": 1,
        "delivery_delta": 1,
        "backend_count": 8,
        "stable_followups": True,
    }


def _mismatch_race() -> dict:
    return {
        "statuses": [409, 201],
        "conflict_codes": ["idempotency_conflict"],
        "conflict_fields": ["Idempotency-Key"],
        "same_public_handle": False,
        "graph_delta": _graph(),
        "ledger_delta": 1,
        "delivery_delta": 1,
        "backend_count": 2,
        "db_lock_wait_observed": True,
        "stable_followups": True,
    }


def test_race_evaluator_requires_exact_same_and_mismatch_cardinality():
    assert _race_observation_passes(_same_race(), mismatched=False)
    assert _race_observation_passes(_mismatch_race(), mismatched=True)
    for observation, mismatched in (
        (_same_race(), False),
        (_mismatch_race(), True),
    ):
        for field, unsafe in (
            ("ledger_delta", 2),
            ("delivery_delta", 2),
            ("backend_count", 1),
            ("stable_followups", False),
        ):
            mutant = deepcopy(observation)
            mutant[field] = unsafe
            assert not _race_observation_passes(mutant, mismatched=mismatched)


def _failure() -> dict:
    return {
        "first_status": 502,
        "replay_status": 502,
        "same_error_code": True,
        "error_fields_absent": True,
        "ledger_delta": 1,
        "replay_ledger_delta": 0,
        "replay_delivery_delta": 0,
        "replay_graph_delta_zero": True,
        "replay_state_unchanged": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("first_status", 201),
        ("replay_status", 201),
        ("same_error_code", False),
        ("error_fields_absent", False),
        ("ledger_delta", 0),
        ("replay_ledger_delta", 1),
        ("replay_delivery_delta", 1),
        ("replay_graph_delta_zero", False),
        ("replay_state_unchanged", False),
    ),
)
def test_failure_replay_evaluator_rejects_each_false_green(field, unsafe):
    observation = _failure()
    assert _failure_replay_observation_passes(observation)
    observation[field] = unsafe
    assert not _failure_replay_observation_passes(observation)


def _ledger_inventory() -> dict:
    return {
        "schema_exact": True,
        "ledger_has_raw_key_column": False,
        "new_registration_raw_key_is_null": True,
        "new_registration_legacy_marker_false": True,
        "key_hash_lower_hex_64": True,
        "key_hash_differs_from_wire_key": True,
        "key_hash_unique_authority": True,
        "state_inventory_exact": True,
        "state_links_exact": True,
    }


@pytest.mark.parametrize("field", tuple(_ledger_inventory()))
def test_ledger_inventory_evaluator_rejects_every_missing_authority(field):
    observation = _ledger_inventory()
    assert _ledger_inventory_observation_passes(observation)
    observation[field] = not observation[field]
    assert not _ledger_inventory_observation_passes(observation)


def _pending_resume() -> dict:
    return {
        "crash_status": 500,
        "pending_state_exact": True,
        "pending_mismatch_status": 409,
        "pending_mismatch_code": "idempotency_conflict",
        "pending_mismatch_field": "Idempotency-Key",
        "resume_status": 201,
        "resume_same_public_handle": True,
        "succeeded_state_exact": True,
        "ledger_delta": 1,
        "graph_delta": _graph(),
        "resume_graph_delta_zero": True,
        "crash_provider_invocations": 1,
        "crash_provider_acceptances": 0,
        "resume_provider_acceptances": 1,
        "provider_acceptances_total": 1,
        "followup_stable": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("crash_status", 201),
        ("pending_state_exact", False),
        ("pending_mismatch_status", 201),
        ("pending_mismatch_code", "mobile_already_registered"),
        ("pending_mismatch_field", "mobile"),
        ("resume_status", 500),
        ("resume_same_public_handle", False),
        ("succeeded_state_exact", False),
        ("ledger_delta", 2),
        ("resume_graph_delta_zero", False),
        ("crash_provider_invocations", 2),
        ("crash_provider_acceptances", 1),
        ("resume_provider_acceptances", 2),
        ("provider_acceptances_total", 2),
        ("followup_stable", False),
    ),
)
def test_pending_resume_evaluator_rejects_every_false_green(field, unsafe):
    observation = _pending_resume()
    assert _pending_resume_observation_passes(observation)
    observation[field] = unsafe
    assert not _pending_resume_observation_passes(observation)


def _failed_waiters() -> dict:
    return {
        "statuses": [502, 502],
        "same_error_code": True,
        "error_fields_absent": True,
        "failed_state_exact": True,
        "ledger_delta": 1,
        "registration_graph_absent": True,
        "provider_attempt_delta": 1,
        "backend_count": 2,
        "db_lock_wait_observed": True,
        "stable_failure_replay": True,
        "mismatch_conflict": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("statuses", [502, 201]),
        ("same_error_code", False),
        ("error_fields_absent", False),
        ("failed_state_exact", False),
        ("ledger_delta", 2),
        ("registration_graph_absent", False),
        ("provider_attempt_delta", 2),
        ("backend_count", 1),
        ("db_lock_wait_observed", False),
        ("stable_failure_replay", False),
        ("mismatch_conflict", False),
    ),
)
def test_failed_waiter_evaluator_rejects_every_false_green(field, unsafe):
    observation = _failed_waiters()
    assert _failed_waiters_observation_passes(observation)
    observation[field] = unsafe
    assert not _failed_waiters_observation_passes(observation)


def _pending_resend() -> dict:
    return {
        "resend_status": 202,
        "replay_status": 201,
        "same_public_handle": True,
        "ledger_repointed_to_replacement": True,
        "ledger_succeeded_unlinked_before_replacement": False,
        "superseded_payload_nonrelayable": True,
        "succeeded_state_exact": True,
        "registration_graph_single": True,
        "active_signup_challenges": 1,
        "relayable_signup_payloads": 0,
        "provider_acceptances": 1,
        "backend_count": 2,
        "db_lock_wait_observed": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("resend_status", 500),
        ("replay_status", 409),
        ("same_public_handle", False),
        ("ledger_repointed_to_replacement", False),
        ("superseded_payload_nonrelayable", False),
        ("succeeded_state_exact", False),
        ("registration_graph_single", False),
        ("active_signup_challenges", 2),
        ("relayable_signup_payloads", 1),
        ("provider_acceptances", 2),
        ("backend_count", 1),
        ("db_lock_wait_observed", False),
    ),
)
def test_pending_resend_evaluator_closes_each_ordinary_seam(field, unsafe):
    observation = _pending_resend()
    assert gate._pending_resend_observation_passes(observation, concurrent=True)
    observation[field] = unsafe
    assert not gate._pending_resend_observation_passes(observation, concurrent=True)


def test_pending_sent_resend_requires_succeeded_unlinked_authority_shape():
    observation = _pending_resend()
    observation.update(
        {
            "ledger_repointed_to_replacement": False,
            "ledger_succeeded_unlinked_before_replacement": True,
            "backend_count": 0,
            "db_lock_wait_observed": False,
        }
    )
    assert gate._pending_resend_observation_passes(
        observation, concurrent=False, pre_relay=True
    )
    observation["ledger_succeeded_unlinked_before_replacement"] = False
    assert not gate._pending_resend_observation_passes(
        observation, concurrent=False, pre_relay=True
    )


def _pending_purge() -> dict:
    return {
        "purged_challenges": 1,
        "registration_transitions": 1,
        "erased_state_exact": True,
        "policy_mode_shape_exact": True,
        "audit_action_exact": True,
        "relayable_payload_absent": True,
        "terminal_cases": len(CANONICAL_FIELD_PATHS) + 1,
        "all_terminal_statuses_409": True,
        "all_terminal_codes_expired": True,
        "all_terminal_fields_idempotency_key": True,
        "uniform_response_bytes": True,
        "provider_acceptances": 0,
        "state_unchanged_on_replays": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("purged_challenges", 0),
        ("registration_transitions", 0),
        ("erased_state_exact", False),
        ("policy_mode_shape_exact", False),
        ("audit_action_exact", False),
        ("relayable_payload_absent", False),
        ("terminal_cases", len(CANONICAL_FIELD_PATHS)),
        ("all_terminal_statuses_409", False),
        ("all_terminal_codes_expired", False),
        ("all_terminal_fields_idempotency_key", False),
        ("uniform_response_bytes", False),
        ("provider_acceptances", 1),
        ("state_unchanged_on_replays", False),
    ),
)
def test_pending_retention_evaluator_rejects_every_false_green(field, unsafe):
    observation = _pending_purge()
    assert gate._pending_purge_observation_passes(observation)
    observation[field] = unsafe
    assert not gate._pending_purge_observation_passes(observation)


def test_canonical_inventory_is_exact_and_has_no_derived_fields():
    assert CANONICAL_FIELD_PATHS == (
        "first_name",
        "middle_name",
        "last_name",
        "mobile",
        "dob",
        "consent.accepted",
        "consent.policy_version",
        "college",
        "year_of_study",
        "enrolment_number",
        "institutional_email",
        "bar_enrolment_number",
    )
    assert not {"is_minor", "status", "key_version"}.intersection(CANONICAL_FIELD_PATHS)


def _path_value(payload, path):
    value = payload
    for part in path.split("."):
        value = value[part]
    return value


def test_every_canonical_mutation_is_schema_valid_and_changes_exactly_one_field():
    from app.schemas.registration import StudentRegisterRequest

    base = _base_registration_payload(901)
    normalized_base = StudentRegisterRequest.model_validate(base).model_dump(
        mode="json"
    )
    mutations = _canonical_field_mutations(base)
    assert len(mutations) == len(CANONICAL_FIELD_PATHS) == 12
    for expected_path, mutation in zip(CANONICAL_FIELD_PATHS, mutations, strict=True):
        normalized = StudentRegisterRequest.model_validate(mutation).model_dump(
            mode="json"
        )
        changed = [
            path
            for path in CANONICAL_FIELD_PATHS
            if _path_value(normalized, path) != _path_value(normalized_base, path)
        ]
        assert changed == [expected_path]


def test_unicode_whitespace_case_default_and_omission_equivalents_normalize_exactly():
    from app.schemas.registration import StudentRegisterRequest

    base = _base_registration_payload(902)
    normalized = StudentRegisterRequest.model_validate(base).model_dump(mode="json")
    variants = _canonical_equivalent_payloads(base)
    assert len(variants) >= 5
    assert all(
        StudentRegisterRequest.model_validate(variant).model_dump(mode="json")
        == normalized
        for variant in variants
    )


def test_all_optional_explicit_nulls_equal_omission_after_validation():
    from app.schemas.registration import StudentRegisterRequest

    explicit = _base_registration_payload(903)
    fields = (
        "middle_name",
        "college",
        "year_of_study",
        "enrolment_number",
        "institutional_email",
        "bar_enrolment_number",
    )
    for field in fields:
        explicit[field] = None
    omitted = deepcopy(explicit)
    for field in fields:
        omitted.pop(field)
    assert StudentRegisterRequest.model_validate(explicit).model_dump(
        mode="json"
    ) == StudentRegisterRequest.model_validate(omitted).model_dump(mode="json")


class _Response:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def test_crash_response_has_no_handle_but_unique_ledger_resolves_subject(
    monkeypatch,
):
    identifier = gate.uuid.uuid4()
    crashed = _Response(500, {"detail": {"code": "internal_error"}})
    monkeypatch.setattr(
        gate,
        "_ledger_for_key",
        lambda _session, _key: SimpleNamespace(registration_id=identifier),
    )
    assert gate._response_handle(crashed) is None
    assert gate._durable_registration_handle_for_key(object(), "opaque-key") == str(
        identifier
    )
    monkeypatch.setattr(
        gate,
        "_ledger_for_key",
        lambda _session, _key: SimpleNamespace(registration_id=None),
    )
    assert gate._durable_registration_handle_for_key(object(), "opaque-key") is None


def test_response_signature_never_retains_response_values():
    raw_identifier = "9dc64042-f7af-4a44-a14d-e48f810492fe"
    success = _safe_response_signature(
        _Response(201, {"registration_id": raw_identifier, "status": "otp_pending"})
    )
    conflict = _safe_response_signature(
        _Response(
            409,
            {
                "detail": {
                    "code": "idempotency_conflict",
                    "field": "Idempotency-Key",
                    "unsafe": raw_identifier,
                }
            },
        )
    )
    assert success == {"status_code": 201, "shape": "object"}
    assert conflict == {
        "status_code": 409,
        "shape": "typed_detail",
        "error_code": "idempotency_conflict",
        "error_field": "Idempotency-Key",
    }
    assert raw_identifier not in repr((success, conflict))


@pytest.mark.parametrize(
    "unsafe",
    (
        {"idempotency_key": "opaque"},
        {"canonical_payload": "redacted"},
        {"request_fingerprint": "a" * 64},
        {"note": "9dc64042-f7af-4a44-a14d-e48f810492fe"},
        {"note": "student@example.invalid"},
        {"note": "9876543210"},
        {"note": "2000-01-02"},
        {"note": "postgresql://localhost/db"},
        {"note": "a" * 64},
    ),
)
def test_privacy_scan_rejects_raw_key_canonical_fingerprint_and_pii(unsafe):
    assert _privacy_findings(unsafe)


def test_privacy_scan_accepts_aggregate_report_shape():
    report = {
        "gate": "nyay17_postgres_idempotency",
        "status": "PASS",
        "assertions": _passing_assertions(),
        "metrics": {
            "cases_checked": len(CANONICAL_FIELD_PATHS),
            "workers": 8,
            "deliveries": 1,
        },
    }
    assert _privacy_findings(report) == []


def test_seeded_mutants_are_deterministic_and_killed():
    assert _seeded_mutants_are_killed()
    assert _seeded_mutants_are_killed()


def test_scratch_manager_reports_created_and_removed_without_name(monkeypatch):
    events = []
    monkeypatch.setattr(gate, "_scratch_database_inventory", lambda _: set())

    def create(_base, name):
        events.append(("create", name))
        return "opaque-scratch-url"

    def drop(_base, name):
        events.append(("drop", name))

    monkeypatch.setattr(gate, "_create_scratch", create)
    monkeypatch.setattr(gate, "_drop_scratch", drop)
    manager = _ScratchDatabaseManager(object())
    assert manager.run("behavior", lambda value: value) == "opaque-scratch-url"
    summary = manager.summary()
    assert summary == {
        "created": 1,
        "removed": 1,
        "cleanup_failed": 0,
        "all_created_removed": True,
        "inventory_match": True,
        "baseline_count": 0,
        "final_count": 0,
        "purposes": ["behavior"],
    }
    assert all(name not in repr(summary) for _, name in events)


def test_scratch_cleanup_failure_is_fatal_and_sanitized(monkeypatch):
    monkeypatch.setattr(gate, "_scratch_database_inventory", lambda _: set())
    monkeypatch.setattr(gate, "_create_scratch", lambda *_: "opaque")

    def fail(*_):
        raise RuntimeError("credential-bearing detail")

    monkeypatch.setattr(gate, "_drop_scratch", fail)
    manager = _ScratchDatabaseManager(object())
    with pytest.raises(ScratchCleanupFailure) as caught:
        manager.run("behavior", lambda _: None)
    assert "credential-bearing detail" not in str(caught.value)
    assert manager.summary()["all_created_removed"] is False


def test_scratch_inventory_detects_drop_false_green_without_emitting_name(
    monkeypatch,
):
    names = {"nyay17_idem_preexisting"}
    created_name = None

    def inventory(_base):
        return set(names)

    def create(_base, name):
        nonlocal created_name
        created_name = name
        names.add(name)
        return "opaque"

    monkeypatch.setattr(gate, "_scratch_database_inventory", inventory)
    monkeypatch.setattr(gate, "_create_scratch", create)
    monkeypatch.setattr(gate, "_drop_scratch", lambda *_: None)
    manager = _ScratchDatabaseManager(object())
    with pytest.raises(ScratchCleanupFailure):
        manager.run("behavior", lambda _: None)
    summary = manager.summary()
    assert summary["inventory_match"] is False
    assert summary["all_created_removed"] is False
    assert created_name not in repr(summary)


def test_scratch_summary_rejects_unowned_inventory_delta(monkeypatch):
    names = {"nyay17_idem_preexisting"}

    def create(_base, name):
        names.add(name)
        return "opaque"

    def drop(_base, name):
        names.discard(name)

    monkeypatch.setattr(gate, "_scratch_database_inventory", lambda _base: set(names))
    monkeypatch.setattr(gate, "_create_scratch", create)
    monkeypatch.setattr(gate, "_drop_scratch", drop)
    manager = _ScratchDatabaseManager(object())
    manager.run("behavior", lambda _: None)
    names.add("nyay17_idem_external_delta")
    summary = manager.summary()
    assert summary["baseline_count"] == 1
    assert summary["final_count"] == 2
    assert summary["inventory_match"] is False
    assert summary["all_created_removed"] is False


def test_scratch_cleanup_inventory_exception_is_fatal_and_sanitized(
    monkeypatch,
):
    calls = 0

    def inventory(_base):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError("private inventory detail")
        return set()

    monkeypatch.setattr(gate, "_scratch_database_inventory", inventory)
    monkeypatch.setattr(gate, "_create_scratch", lambda *_: "opaque")
    monkeypatch.setattr(gate, "_drop_scratch", lambda *_: None)
    manager = _ScratchDatabaseManager(object())
    with pytest.raises(ScratchCleanupFailure) as caught:
        manager.run("behavior", lambda _: None)
    assert "private inventory detail" not in str(caught.value)
    assert manager.summary()["all_created_removed"] is False


def test_scratch_cleanup_still_runs_after_operation_exception(monkeypatch):
    names = set()

    def create(_base, name):
        names.add(name)
        return "opaque"

    def drop(_base, name):
        names.discard(name)

    monkeypatch.setattr(gate, "_scratch_database_inventory", lambda _base: set(names))
    monkeypatch.setattr(gate, "_create_scratch", create)
    monkeypatch.setattr(gate, "_drop_scratch", drop)
    manager = _ScratchDatabaseManager(object())
    with pytest.raises(ValueError, match="synthetic operation failure"):
        manager.run(
            "behavior",
            lambda _: (_ for _ in ()).throw(ValueError("synthetic operation failure")),
        )
    assert manager.summary()["all_created_removed"] is True
