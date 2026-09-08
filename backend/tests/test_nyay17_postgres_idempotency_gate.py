"""Pure oracles for the opt-in NYAY-17 PostgreSQL idempotency gate.

These tests prove fail-closed routing, exact assertion inventory, evaluator
strictness, aggregate-evidence privacy, and scratch cleanup.  They make no
PostgreSQL or application-behaviour claim; authoritative product evidence is
emitted only by executing the gate against PostgreSQL 16 + pgvector.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
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
    _behavior_rate_limit_scope,
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
    assert gate.NYAY5_CHECKPOINT == "0021_nyay5_profile_boundary"
    assert gate.NYAY9_CHECKPOINT == "0022_nyay9_owner_profile_api"
    assert gate.APPLICATION_HEAD == "0025_nyay12_email_identity"
    config = Config(str(gate.BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(gate.BACKEND / "app/db/migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [gate.APPLICATION_HEAD]
    otp_security_head = scripts.get_revision("0019_otp_security_authority")
    retention_head = scripts.get_revision("0020_auth_retention_lifecycle")
    nyay9_checkpoint = scripts.get_revision(gate.NYAY9_CHECKPOINT)
    nyay22_checkpoint = scripts.get_revision(gate.NYAY22_CHECKPOINT)
    nyay5_checkpoint = scripts.get_revision(gate.NYAY5_CHECKPOINT)
    nyay11_checkpoint = scripts.get_revision(gate.NYAY11_CHECKPOINT)
    assert scripts.get_revision(gate.APPLICATION_HEAD).down_revision == (
        nyay11_checkpoint.revision
    )
    assert nyay11_checkpoint.down_revision == nyay22_checkpoint.revision
    assert nyay22_checkpoint.down_revision == nyay9_checkpoint.revision
    assert nyay9_checkpoint.down_revision == nyay5_checkpoint.revision
    assert nyay5_checkpoint.down_revision == retention_head.revision
    assert retention_head.down_revision == otp_security_head.revision
    assert otp_security_head.down_revision == gate.PINNED_HEAD
    behavior_source = pyinspect.getsource(gate._execute_behavior)
    assert '"upgrade", APPLICATION_HEAD' in behavior_source
    assert '"upgrade", PINNED_HEAD' not in behavior_source
    assert (
        "_migration_inventory_passes(\n"
        "            engine, expected_revision=APPLICATION_HEAD\n"
        "        )"
    ) in behavior_source
    integrity_source = pyinspect.getsource(gate._run_integrity_translation_probe)
    assert "uuid.UUID(str(_response_handle(created)))" not in integrity_source
    assert "_public_response_handle(created) is None" in integrity_source
    assert "_ledger_for_key(session, wire_key)" in integrity_source
    assert "app.state.nyay17_session_factory = factory" in pyinspect.getsource(
        gate._build_app_context
    )
    assert "_attach_private_response_handle" in pyinspect.getsource(
        gate._post_registration
    )
    inventory_source = pyinspect.getsource(gate._migration_inventory_passes)
    assert "app.db.migrations.versions.0021_nyay5_profile_boundary" in inventory_source
    assert "profile_migration._NEW_REGISTRATION_FINGERPRINT" in inventory_source


def test_registration_probe_helpers_supply_trusted_origin_without_collapsing_headers(
    monkeypatch,
):
    from app.core.config import settings

    calls = []
    response = object()

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, path, *, json, headers):
            calls.append((path, json, headers))
            return response

    monkeypatch.setattr(gate, "TestClient", Client)
    payload = {"field": "value"}

    assert gate._post_registration(object(), payload, "one-key") is response
    assert (
        gate._post_registration_headers(
            object(), payload, [("Idempotency-Key", "a"), ("Idempotency-Key", "b")]
        )
        is response
    )
    origin = settings.cors_origins[0]
    assert calls == [
        (
            gate.REGISTER_PATH,
            payload,
            {"Origin": origin, "Idempotency-Key": "one-key"},
        ),
        (
            gate.REGISTER_PATH,
            payload,
            [
                ("Origin", origin),
                ("Idempotency-Key", "a"),
                ("Idempotency-Key", "b"),
            ],
        ),
    ]


def test_private_probe_handle_cannot_masquerade_as_public_response_uuid():
    handle = "c9dc4df2-1641-4d5d-a3c8-8d05691102c2"
    private = SimpleNamespace(
        _nyay17_private_registration_id=handle,
        json=lambda: {"status": "pending"},
    )
    leaked = SimpleNamespace(json=lambda: {"registration_id": handle})

    assert gate._response_handle(private) == handle
    assert gate._public_response_handle(private) is None
    assert gate._response_handle(leaked) is None
    assert gate._public_response_handle(leaked) == handle


def test_identifier_free_accepted_projection_rejects_uuid_in_any_public_field():
    handle = "c9dc4df2-1641-4d5d-a3c8-8d05691102c2"
    body = {
        "status": "accepted",
        "next": "otp",
        "expires_in_seconds": 300,
        "resend_after_seconds": 30,
    }
    response = SimpleNamespace(
        status_code=202,
        json=lambda: body,
        _nyay17_private_registration_id=handle,
    )
    assert gate._response_is_identifier_free(response, private_handle=handle)
    assert gate._registration_accepted_projection_is_exact(
        response, private_handle=handle
    )
    assert gate._post_response_crash_projection_is_exact(
        response, private_handle=handle
    )

    for field, value in (
        ("registration_id", handle),
        ("next", handle),
        ("next", handle.replace("-", "")),
    ):
        mutated = dict(body)
        mutated[field] = value
        leaked = SimpleNamespace(status_code=202, json=lambda value=mutated: value)
        assert not gate._response_is_identifier_free(leaked, private_handle=handle)
        assert not gate._registration_accepted_projection_is_exact(
            leaked, private_handle=handle
        )

    wrong_private = SimpleNamespace(
        status_code=202,
        json=lambda: body,
        _nyay17_private_registration_id="c7b31f6e-9b98-492e-abee-d951498dc279",
    )
    assert not gate._post_response_crash_projection_is_exact(
        wrong_private, private_handle=handle
    )


def test_signup_otp_helpers_use_private_cookie_capability_and_current_payloads(
    monkeypatch,
):
    from app.core.config import settings
    from app.services import otp_flow_service

    calls = []

    class Cookies:
        def set(self, name, value, *, path):
            calls.append(("cookie", name, value, path))

    class Client:
        def __init__(self, *_args, **_kwargs):
            self.cookies = Cookies()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, path, *, json, headers):
            calls.append(("post", path, json, headers))
            return object()

    monkeypatch.setattr(gate, "TestClient", Client)
    monkeypatch.setattr(
        otp_flow_service,
        "deterministic_signup_token",
        lambda key: f"private-{key}",
    )

    crashed = SimpleNamespace(status_code=500)
    gate._post_signup_resend(object(), crashed, "opaque-key")
    gate._post_signup_verify(object(), crashed, "opaque-key", "123456")
    origin = settings.cors_origins[0]
    assert calls == [
        (
            "cookie",
            settings.otp_flow_cookie_name,
            "private-opaque-key",
            "/api/v1",
        ),
        (
            "post",
            "/api/v1/auth/student/otp/resend",
            {},
            {"Origin": origin},
        ),
        (
            "cookie",
            settings.otp_flow_cookie_name,
            "private-opaque-key",
            "/api/v1",
        ),
        (
            "post",
            "/api/v1/auth/student/otp/verify",
            {"code": "123456"},
            {"Origin": origin},
        ),
    ]

    successful_without_cookie = SimpleNamespace(status_code=202)
    captured = SimpleNamespace(
        status_code=202,
        _nyay17_private_flow_token="captured-token",
    )
    assert gate._private_flow_token(captured, "opaque-key") == "captured-token"
    assert gate._private_flow_token(successful_without_cookie, "opaque-key") is None
    assert gate._private_flow_token(crashed, None) is None
    assert gate._private_flow_token(crashed, "opaque-key") == "private-opaque-key"


def test_behavior_rate_limit_scope_is_exact_and_restores_on_every_exit():
    from app.core.config import settings

    fields = (
        "otp_issue_identity_limit",
        "otp_issue_ip_limit",
        "otp_issue_global_limit",
    )
    original = tuple(getattr(settings, field) for field in fields)
    seeded = (3, 4, 5)
    try:
        for field, value in zip(fields, seeded, strict=True):
            setattr(settings, field, value)
        with _behavior_rate_limit_scope():
            assert tuple(getattr(settings, field) for field in fields) == (
                100,
                1000,
                10000,
            )
        assert tuple(getattr(settings, field) for field in fields) == seeded

        with pytest.raises(RuntimeError, match="forced probe failure"):
            with _behavior_rate_limit_scope():
                raise RuntimeError("forced probe failure")
        assert tuple(getattr(settings, field) for field in fields) == seeded
    finally:
        for field, value in zip(fields, original, strict=True):
            setattr(settings, field, value)

    behavior_source = pyinspect.getsource(gate._execute_behavior)
    assert "with _behavior_rate_limit_scope():" in behavior_source


def test_behavior_process_scope_restores_keyring_and_environment_on_every_exit():
    from app.core import crypto
    from app.core.config import settings
    from app.core.crypto import KeyRing

    original_env = settings.app_env
    original_ring = crypto._override
    seeded_ring = KeyRing(
        active_version="seeded",
        secrets={"seeded": b"seeded-process-key"},
        lookup_secret=b"seeded-process-lookup",
    )
    try:
        settings.app_env = "seeded-environment"
        crypto.override_keyring(seeded_ring)
        with gate._behavior_process_scope():
            assert settings.app_env == "testing"
            assert crypto._override is not seeded_ring
            assert crypto._override is not None
            assert crypto._override.active_version == "v1"
        assert settings.app_env == "seeded-environment"
        assert crypto._override is seeded_ring

        with pytest.raises(RuntimeError, match="forced process-scope failure"):
            with gate._behavior_process_scope():
                raise RuntimeError("forced process-scope failure")
        assert settings.app_env == "seeded-environment"
        assert crypto._override is seeded_ring
    finally:
        settings.app_env = original_env
        crypto.override_keyring(original_ring)


def test_gate_provider_doubles_implement_exact_idempotent_contract():
    from app.services.otp_sender import OtpSendError

    sender = gate._CapturingSender()
    first = sender.send_idempotent(
        "private-destination",
        "private-code",
        idempotency_token="opaque-token",
    )
    second = sender.send_idempotent(
        "private-destination",
        "private-code",
        idempotency_token="opaque-token",
    )
    assert first == second
    assert sender.count == 1
    with pytest.raises(OtpSendError, match="idempotency conflict"):
        sender.send_idempotent(
            "different-destination",
            "private-code",
            idempotency_token="opaque-token",
        )

    crash = gate._CrashSender()
    with pytest.raises(RuntimeError, match="post-commit crash"):
        crash.send_idempotent(
            "private-destination",
            "private-code",
            idempotency_token="opaque-crash",
        )
    assert crash.attempts == 1
    assert crash.count == 0

    accepted = gate._AcceptedCrashSender()
    with pytest.raises(RuntimeError, match="accepted-before-finalization"):
        accepted.send_idempotent(
            "private-destination",
            "private-code",
            idempotency_token="opaque-accepted",
        )
    assert accepted.attempts == 1
    assert accepted.count == 1
    assert accepted.send_idempotent(
        "private-destination",
        "private-code",
        idempotency_token="opaque-accepted",
    )
    assert accepted.attempts == 2
    assert accepted.count == 1

    failing = gate._FailingSender()
    with pytest.raises(OtpSendError, match="synthetic provider failure"):
        failing.send_idempotent(
            "private-destination",
            "private-code",
            idempotency_token="opaque-failure",
        )
    assert failing.count == 1

    blocking = gate._BlockingSender()
    blocking.release.set()
    assert blocking.send_idempotent(
        "private-destination",
        "private-code",
        idempotency_token="opaque-blocking",
    )
    assert blocking.entered.is_set()
    assert blocking.count == 1


def test_current_head_neutralized_ledger_shape_is_exact():
    record = SimpleNamespace(
        state="neutralized",
        idempotency_key_hash="a" * 64,
        request_fingerprint_version="v2",
        request_fingerprint="b" * 64,
        registration_id=None,
        outbox_id=None,
        outcome_code="registration_neutralized",
    )
    assert gate._ledger_state_exact(record, "neutralized")
    for field, unsafe in (
        ("request_fingerprint_version", None),
        ("request_fingerprint", None),
        ("registration_id", gate.uuid.uuid4()),
        ("outbox_id", gate.uuid.uuid4()),
        ("outcome_code", "registration_replay_expired"),
    ):
        mutant = SimpleNamespace(**vars(record))
        setattr(mutant, field, unsafe)
        assert not gate._ledger_state_exact(mutant, "neutralized")


def _neutralized_observation() -> dict:
    return {
        "response_status": 202,
        "projection_exact": True,
        "projection_matches_real": True,
        "public_identifier_absent": True,
        "private_registration_absent": True,
        "distinct_deterministic_cookie": True,
        "neutralized_state_exact": True,
        "neutral_flow_exact": True,
        "neutral_authority_exact": True,
        "real_graph_unchanged": True,
        "real_provider_delta": 0,
        "ledger_delta": 1,
        "authority_delta": 1,
        "flow_delta": 1,
        "replay_status": 202,
        "replay_projection_stable": True,
        "replay_cookie_stable": True,
        "replay_state_unchanged": True,
        "replay_provider_delta": 0,
        "mutation_conflict_exact": True,
        "mutation_state_unchanged": True,
        "mutation_provider_delta": 0,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    tuple(
        (field, 409 if field in {"response_status", "replay_status"} else False)
        for field in _neutralized_observation()
        if not field.endswith("_delta")
    )
    + (
        ("real_provider_delta", 1),
        ("ledger_delta", 0),
        ("authority_delta", 0),
        ("flow_delta", 0),
        ("replay_provider_delta", 1),
        ("mutation_provider_delta", 1),
    ),
)
def test_neutralized_evaluator_rejects_every_false_green(field, unsafe):
    observation = _neutralized_observation()
    assert gate._neutralized_observation_passes(observation)
    observation[field] = unsafe
    assert not gate._neutralized_observation_passes(observation)


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


def test_schema_inventory_accepts_exact_0021_evolution_at_application_head(
    monkeypatch,
):
    fixture = _SchemaInspectorFixture()
    otp_migration = gate.importlib.import_module(
        "app.db.migrations.versions.0019_otp_security_authority"
    )
    profile_migration = gate.importlib.import_module(
        "app.db.migrations.versions.0021_nyay5_profile_boundary"
    )
    evolved = {
        "ck_registration_idempotency_records_state": (otp_migration._LEDGER_STATE_0019),
        "ck_registration_idempotency_records_request_fingerprint_shape": (
            profile_migration._NEW_REGISTRATION_FINGERPRINT
        ),
        "ck_registration_idempotency_records_state_links": (
            otp_migration._LEDGER_LINKS_0019
        ),
    }
    for item in fixture.checks["registration_idempotency_records"]:
        if item["name"] in evolved:
            item["sqltext"] = evolved[item["name"]]
    monkeypatch.setattr(gate, "inspect", lambda _engine: fixture)

    assert not _migration_inventory_passes(object())
    assert _migration_inventory_passes(
        object(), expected_revision=gate.APPLICATION_HEAD
    )
    assert not _migration_inventory_passes(
        object(), expected_revision="unknown_revision"
    )


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
        "consents": 2 * int(one),
        "otp_challenges": int(one),
        "otp_outbox": int(one),
        "audit_events": int(one),
    }


def _replay() -> dict:
    return {
        "first_status": 202,
        "first_literal_pending": True,
        "replay_status": 202,
        "public_handles_absent": True,
        "private_subject_stable": True,
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
        ("public_handles_absent", False),
        ("private_subject_stable", False),
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
        "statuses": [202] * 8,
        "conflict_codes": [],
        "conflict_fields": [],
        "public_handles_absent": True,
        "private_winner_exact": True,
        "graph_delta": _graph(),
        "ledger_delta": 1,
        "delivery_delta": 1,
        "backend_count": 8,
        "stable_followups": True,
    }


def _mismatch_race() -> dict:
    return {
        "statuses": [409, 202],
        "conflict_codes": ["idempotency_conflict"],
        "conflict_fields": ["Idempotency-Key"],
        "public_handles_absent": True,
        "private_winner_exact": True,
        "graph_delta": _graph(),
        "ledger_delta": 1,
        "delivery_delta": 1,
        "backend_count": 2,
        "provider_overlap_completed_before_release": True,
        "winner_blocked_before_release": True,
        "ledger_lock_wait_observed": True,
        "ledger_wait_backend_count": 1,
        "deadlock_free": True,
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
            ("public_handles_absent", False),
            ("private_winner_exact", False),
            ("ledger_delta", 2),
            ("delivery_delta", 2),
            ("backend_count", 1),
            ("stable_followups", False),
        ):
            mutant = deepcopy(observation)
            mutant[field] = unsafe
            assert not _race_observation_passes(mutant, mismatched=mismatched)
    for field, unsafe in (
        ("provider_overlap_completed_before_release", False),
        ("winner_blocked_before_release", False),
        ("ledger_lock_wait_observed", False),
        ("ledger_wait_backend_count", 2),
        ("deadlock_free", False),
    ):
        mutant = deepcopy(_mismatch_race())
        mutant[field] = unsafe
        assert not _race_observation_passes(mutant, mismatched=True)


def _failure() -> dict:
    return {
        "first_status": 202,
        "first_projection_exact": True,
        "replay_status": 202,
        "replay_projection_exact": True,
        "public_handles_absent": True,
        "private_subject_stable": True,
        "pending_state_exact": True,
        "failed_delivery_exact": True,
        "ledger_delta": 1,
        "graph_delta": _graph(),
        "replay_ledger_delta": 0,
        "replay_delivery_delta": 0,
        "replay_graph_delta_zero": True,
        "replay_state_unchanged": True,
        "mismatch_conflict_exact": True,
        "mismatch_state_unchanged": True,
        "recovery_status": 202,
        "stable_provider_key": True,
        "succeeded_state_exact": True,
        "sent_delivery_exact": True,
        "recovery_provider_acceptances": 1,
        "recovery_graph_delta_zero": True,
        "final_replay_stable": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("first_status", 502),
        ("first_projection_exact", False),
        ("replay_status", 502),
        ("replay_projection_exact", False),
        ("public_handles_absent", False),
        ("private_subject_stable", False),
        ("pending_state_exact", False),
        ("failed_delivery_exact", False),
        ("ledger_delta", 0),
        ("graph_delta", _graph(False)),
        ("replay_ledger_delta", 1),
        ("replay_delivery_delta", 1),
        ("replay_graph_delta_zero", False),
        ("replay_state_unchanged", False),
        ("mismatch_conflict_exact", False),
        ("mismatch_state_unchanged", False),
        ("recovery_status", 503),
        ("stable_provider_key", False),
        ("succeeded_state_exact", False),
        ("sent_delivery_exact", False),
        ("recovery_provider_acceptances", 2),
        ("recovery_graph_delta_zero", False),
        ("final_replay_stable", False),
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
        "crash_status": 202,
        "crash_projection_exact": True,
        "pending_state_exact": True,
        "claimed_delivery_exact": True,
        "pending_mismatch_status": 409,
        "pending_mismatch_code": "idempotency_conflict",
        "pending_mismatch_field": "Idempotency-Key",
        "pending_mismatch_state_unchanged": True,
        "immediate_replay_status": 202,
        "immediate_projection_exact": True,
        "immediate_delivery_delta": 0,
        "immediate_state_unchanged": True,
        "resume_status": 202,
        "public_handles_absent": True,
        "private_subject_stable": True,
        "succeeded_state_exact": True,
        "sent_delivery_exact": True,
        "stable_provider_key": True,
        "ledger_delta": 1,
        "graph_delta": _graph(),
        "resume_graph_delta_zero": True,
        "crash_provider_invocations": 1,
        "crash_provider_acceptances": 0,
        "resume_provider_invocations": 1,
        "resume_provider_acceptances": 1,
        "provider_acceptances_total": 1,
        "followup_stable": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("crash_status", 500),
        ("crash_projection_exact", False),
        ("pending_state_exact", False),
        ("claimed_delivery_exact", False),
        ("pending_mismatch_status", 201),
        ("pending_mismatch_code", "mobile_already_registered"),
        ("pending_mismatch_field", "mobile"),
        ("pending_mismatch_state_unchanged", False),
        ("immediate_replay_status", 500),
        ("immediate_projection_exact", False),
        ("immediate_delivery_delta", 1),
        ("immediate_state_unchanged", False),
        ("resume_status", 500),
        ("public_handles_absent", False),
        ("private_subject_stable", False),
        ("succeeded_state_exact", False),
        ("sent_delivery_exact", False),
        ("stable_provider_key", False),
        ("ledger_delta", 2),
        ("graph_delta", _graph(False)),
        ("resume_graph_delta_zero", False),
        ("crash_provider_invocations", 2),
        ("crash_provider_acceptances", 1),
        ("resume_provider_invocations", 2),
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
        "statuses": [202, 202],
        "projections_exact": True,
        "public_handles_absent": True,
        "private_subject_stable": True,
        "peer_completed_before_release": True,
        "winner_blocked_before_release": True,
        "pending_state_during_overlap": True,
        "claimed_delivery_during_overlap": True,
        "pending_state_exact": True,
        "failed_delivery_exact": True,
        "ledger_delta": 1,
        "graph_delta": _graph(),
        "provider_attempt_delta": 1,
        "backend_count": 2,
        "stable_failure_replay": True,
        "mismatch_conflict": True,
        "recovery_status": 202,
        "stable_provider_key": True,
        "succeeded_state_exact": True,
        "sent_delivery_exact": True,
        "recovery_provider_acceptances": 1,
        "recovery_graph_delta_zero": True,
        "final_replay_stable": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("statuses", [201, 502]),
        ("projections_exact", False),
        ("public_handles_absent", False),
        ("private_subject_stable", False),
        ("peer_completed_before_release", False),
        ("winner_blocked_before_release", False),
        ("pending_state_during_overlap", False),
        ("claimed_delivery_during_overlap", False),
        ("pending_state_exact", False),
        ("failed_delivery_exact", False),
        ("ledger_delta", 2),
        ("graph_delta", _graph(False)),
        ("provider_attempt_delta", 2),
        ("backend_count", 1),
        ("stable_failure_replay", False),
        ("mismatch_conflict", False),
        ("recovery_status", 503),
        ("stable_provider_key", False),
        ("succeeded_state_exact", False),
        ("sent_delivery_exact", False),
        ("recovery_provider_acceptances", 2),
        ("recovery_graph_delta_zero", False),
        ("final_replay_stable", False),
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
        "replay_status": 202,
        "public_handles_absent": True,
        "private_subject_stable": True,
        "ledger_reused_original_during_send": True,
        "ledger_repointed_to_replacement_during_send": False,
        "claimed_delivery_exact": True,
        "provider_key_authority_exact": True,
        "claim_fence_exact": True,
        "original_sent_erased_before_replacement": False,
        "succeeded_state_exact": True,
        "registration_graph_exact": True,
        "active_signup_challenges": 1,
        "relayable_signup_payloads": 0,
        "provider_acceptances": 1,
        "backend_count": 2,
        "peer_completed_before_release": True,
        "winner_blocked_before_release": True,
    }


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("resend_status", 500),
        ("replay_status", 409),
        ("public_handles_absent", False),
        ("private_subject_stable", False),
        ("ledger_reused_original_during_send", False),
        ("claimed_delivery_exact", False),
        ("provider_key_authority_exact", False),
        ("claim_fence_exact", False),
        ("succeeded_state_exact", False),
        ("registration_graph_exact", False),
        ("active_signup_challenges", 2),
        ("relayable_signup_payloads", 1),
        ("provider_acceptances", 2),
        ("backend_count", 1),
        ("peer_completed_before_release", False),
        ("winner_blocked_before_release", False),
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
            "ledger_reused_original_during_send": False,
            "ledger_repointed_to_replacement_during_send": True,
            "original_sent_erased_before_replacement": True,
            "provider_acceptances": 2,
            "backend_count": 0,
            "peer_completed_before_release": False,
            "winner_blocked_before_release": False,
        }
    )
    assert gate._pending_resend_observation_passes(
        observation, concurrent=False, pre_relay=True
    )
    observation["ledger_repointed_to_replacement_during_send"] = False
    assert not gate._pending_resend_observation_passes(
        observation, concurrent=False, pre_relay=True
    )


def test_pending_resend_threads_one_clock_through_background_delivery():
    source = pyinspect.getsource(gate._run_pending_resend_case)
    assert "_registration_resend_clock_scope(clock)" in source
    assert 'clock["now"] = window["operation_now"]' in source


def test_pending_sent_retention_relay_opens_the_crash_lease_first():
    source = pyinspect.getsource(gate._run_pending_sent_retention_purge_probe)
    open_window = source.index("_open_pending_resend_window(")
    delivery = source.index("otp_outbox.run_delivery(")
    assert open_window < delivery
    assert 'now=window["operation_now"]' in source


def _finalizer_retention_race(*, finalizer_first: bool) -> dict:
    observation = {
        "setup_projection_exact": True,
        "initial_pending_exact": True,
        "initial_failed_delivery_exact": True,
        "setup_provider_attempts": 1,
        "bound_flow_boundary_exact": True,
        "first_waited": True,
        "both_waited": True,
        "backend_count": 2,
        "final_state_exact": True,
        "terminal_projection_exact": True,
        "expired_flows": 0 if finalizer_first else 1,
        "provider_acceptances": 1 if finalizer_first else 0,
        "followup_delivery_delta": 0,
        "followup_state_unchanged": True,
    }
    if finalizer_first:
        observation.update(
            {
                "provider_entered": True,
                "claimed_delivery_during_overlap": True,
                "provider_io_ledger_unlocked": True,
                "finalizer_succeeded": True,
                "finalizer_error_exact": False,
                "purged_challenges": 1,
                "registration_transitions": 0,
                "succeeded_state_exact": True,
                "erased_state_exact": False,
                "exact_replay_status": 202,
                "private_subject_stable": True,
                "mutation_conflict_exact": True,
                "uniform_terminal_signature": False,
            }
        )
    else:
        observation.update(
            {
                "provider_entered": False,
                "claimed_delivery_during_overlap": False,
                "provider_io_ledger_unlocked": False,
                "finalizer_succeeded": False,
                "finalizer_error_exact": True,
                "purged_challenges": 0,
                "registration_transitions": 1,
                "succeeded_state_exact": False,
                "erased_state_exact": True,
                "exact_replay_status": 409,
                "private_subject_stable": False,
                "mutation_conflict_exact": False,
                "uniform_terminal_signature": True,
            }
        )
    return observation


@pytest.mark.parametrize(
    "finalizer_first",
    (True, False),
)
def test_finalizer_retention_race_evaluator_accepts_only_exact_ordered_outcome(
    finalizer_first,
):
    observation = _finalizer_retention_race(finalizer_first=finalizer_first)
    assert gate._finalizer_retention_race_observation_passes(
        observation, finalizer_first=finalizer_first
    )


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("setup_projection_exact", False),
        ("initial_pending_exact", False),
        ("initial_failed_delivery_exact", False),
        ("setup_provider_attempts", 2),
        ("bound_flow_boundary_exact", False),
        ("first_waited", False),
        ("both_waited", False),
        ("backend_count", 1),
        ("final_state_exact", False),
        ("terminal_projection_exact", False),
        ("provider_entered", False),
        ("claimed_delivery_during_overlap", False),
        ("provider_io_ledger_unlocked", False),
        ("finalizer_succeeded", False),
        ("expired_flows", 1),
        ("purged_challenges", 0),
        ("registration_transitions", 1),
        ("succeeded_state_exact", False),
        ("exact_replay_status", 409),
        ("private_subject_stable", False),
        ("mutation_conflict_exact", False),
        ("provider_acceptances", 0),
        ("followup_delivery_delta", 1),
        ("followup_state_unchanged", False),
    ),
)
def test_finalizer_first_retention_evaluator_closes_each_seam(field, unsafe):
    observation = _finalizer_retention_race(finalizer_first=True)
    observation[field] = unsafe
    assert not gate._finalizer_retention_race_observation_passes(
        observation, finalizer_first=True
    )


@pytest.mark.parametrize(
    "field, unsafe",
    (
        ("setup_projection_exact", False),
        ("initial_pending_exact", False),
        ("initial_failed_delivery_exact", False),
        ("setup_provider_attempts", 2),
        ("bound_flow_boundary_exact", False),
        ("first_waited", False),
        ("both_waited", False),
        ("backend_count", 1),
        ("final_state_exact", False),
        ("terminal_projection_exact", False),
        ("finalizer_error_exact", False),
        ("expired_flows", 0),
        ("purged_challenges", 1),
        ("registration_transitions", 0),
        ("erased_state_exact", False),
        ("exact_replay_status", 201),
        ("uniform_terminal_signature", False),
        ("provider_acceptances", 1),
        ("followup_delivery_delta", 1),
        ("followup_state_unchanged", False),
    ),
)
def test_retention_first_finalizer_evaluator_closes_each_seam(field, unsafe):
    observation = _finalizer_retention_race(finalizer_first=False)
    observation[field] = unsafe
    assert not gate._finalizer_retention_race_observation_passes(
        observation, finalizer_first=False
    )


def test_finalizer_retention_race_uses_failed_boundary_and_one_clock():
    source = pyinspect.getsource(gate._run_finalizer_retention_race_case)
    open_window = source.index("_open_pending_resend_window(")
    race = source.index("ThreadPoolExecutor")
    assert open_window < race
    assert "_FailingSender()" in source
    assert "registration_service.finalize_pending_registration(" in source
    assert 'clock = {"now": window["operation_now"]}' in source
    assert 'now=clock["now"]' in source
    assert 'now=clock["now"],' in source
    assert "sender.entered.wait(" in source
    assert "claimed_delivery_during_overlap" in source
    assert "provider_io_ledger_unlocked" in source
    assert 'flow.expires_at = clock["now"] - timedelta(microseconds=1)' in source
    assert "bound_flow_boundary_exact" in source
    aggregate_source = pyinspect.getsource(gate._run_retention_purge_probes)
    assembly_source = pyinspect.getsource(gate._assemble_assertions)
    assert '"race_finalizer_first_diagnostics"' in aggregate_source
    assert '"race_retention_first_diagnostics"' in aggregate_source
    assert "retention_finalizer_first_checks" in assembly_source
    assert "retention_retention_first_checks" in assembly_source


def test_failed_retry_claim_preserves_the_prior_failure_marker_exactly():
    now = datetime.now(timezone.utc)
    row = SimpleNamespace(
        status="claimed",
        attempts=2,
        max_attempts=5,
        provider_idempotency_key="a" * 64,
        claim_token_hash="b" * 64,
        claimed_at=now,
        lease_expires_at=now + timedelta(seconds=30),
        next_attempt_at=None,
        code_ct="ciphertext",
        destination_ct="ciphertext",
        key_version="v1",
        last_error="provider_send_failed",
        delivered_at=None,
        provider_receipt_hash=None,
        provider_receipt_key_version=None,
        legacy_destination_retained=False,
    )
    assert not gate._claimed_delivery_state_exact(row, attempts=2)
    assert gate._claimed_delivery_state_exact(
        row,
        attempts=2,
        expected_last_error="provider_send_failed",
    )


def test_backend_tracker_replaces_a_logical_requests_post_commit_pid():
    tracker = gate._PgBackendTracker()
    first_owner = object()
    second_owner = object()
    tracker.record(101, owner=first_owner)
    tracker.record(202, owner=first_owner)
    assert tracker.count == 1
    assert tracker.private_snapshot() == {202}
    tracker.record(303, owner=second_owner)
    assert tracker.count == 2
    assert tracker.private_snapshot() == {202, 303}


def test_lock_wait_poll_refreshes_replaced_request_pids():
    source = pyinspect.getsource(gate._wait_for_request_lock)
    loop = source.index("while time.monotonic() < deadline:")
    snapshot = source.rindex("tracker.private_snapshot()")
    assert snapshot > loop
    assert 'isolation_level="AUTOCOMMIT"' in source


def _pending_purge() -> dict:
    return {
        "expired_flows": 1,
        # Expiring the bound flow performs the registration transition and
        # removes its OTP graph before the generic challenge sweep runs.
        "purged_challenges": 0,
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
        ("expired_flows", 0),
        ("purged_challenges", 1),
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


def test_pending_retention_expires_the_bound_flow_before_purge():
    source = pyinspect.getsource(gate._run_pending_retention_purge_case)
    assert "OtpFlow" in source
    assert "flow.expires_at = now - timedelta(seconds=1)" in source


def test_succeeded_retention_resend_uses_persisted_cooldown_clock():
    source = pyinspect.getsource(gate._run_succeeded_retention_purge_probe)
    assert "cooldown_until" in source
    assert "_registration_request_clock_scope(" in source
    assert "_registration_resend_clock_scope(resend_clock)" in source
    assert "authority.cooldown_until =" not in source


def test_canonical_inventory_is_exact_and_has_no_derived_fields():
    assert CANONICAL_FIELD_PATHS == (
        "first_name",
        "middle_name",
        "last_name",
        "mobile",
        "dob",
        "terms_accepted",
        "terms_version",
        "privacy_notice_acknowledged",
        "privacy_notice_version",
        "consent",
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
    assert len(mutations) == len(CANONICAL_FIELD_PATHS) == 15
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


def test_current_registration_fixture_has_separate_legal_authority_and_no_profile_write():
    payload = _base_registration_payload(904)

    assert payload == {
        "first_name": "Āsha Rao",
        "middle_name": None,
        "last_name": "Sen",
        "mobile": "8000000904",
        "dob": "2000-01-02",
        "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    }


def test_sealed_v1_fixture_is_used_only_by_the_bound_replay_probe():
    from app.schemas.registration import StudentRegisterRequest
    from app.services import registration_service

    payload = gate._legacy_v1_registration_payload(905)
    request = StudentRegisterRequest.model_validate(payload)

    assert (
        registration_service.registration_request_fingerprint_version(request) == "v1"
    )
    assert set(payload) == registration_service.REGISTRATION_REQUEST_V1_FIELDS
    assert "_run_legacy_v1_replay_probe(" in pyinspect.getsource(
        gate._run_sequential_probes
    )
    source = pyinspect.getsource(gate._run_legacy_v1_replay_probe)
    assert 'fingerprint_version="v1"' in source
    assert "_legacy_v1_registration_payload" in source


def test_current_registration_projection_and_v2_ledger_shape_are_exact():
    accepted = _Response(
        202,
        {
            "status": "accepted",
            "next": "otp",
            "expires_in_seconds": 300,
            "resend_after_seconds": 30,
        },
    )
    accepted._nyay17_private_registration_id = "c9dc4df2-1641-4d5d-a3c8-8d05691102c2"
    assert gate._registration_accepted_projection_is_exact(
        accepted,
        private_handle="c9dc4df2-1641-4d5d-a3c8-8d05691102c2",
    )

    record = SimpleNamespace(
        idempotency_key_hash="a" * 64,
        request_fingerprint="b" * 64,
        request_fingerprint_version="v2",
        state="succeeded",
        registration_id="registration",
        outbox_id=None,
        outcome_code=None,
    )
    assert gate._ledger_state_exact(record, "succeeded")
    record.request_fingerprint_version = "v1"
    assert not gate._ledger_state_exact(record, "succeeded")
    assert gate._ledger_state_exact(record, "succeeded", fingerprint_version="v1")


def _expected_signup_onboarding(payload):
    return {
        "status": "authenticated",
        "purpose": "signup",
        "destination_masked": None,
        "attempts_left": None,
        "expires_in_seconds": None,
        "resend_in_seconds": None,
        "locked_for_seconds": None,
        "resend_allowed": False,
        "onboarding": {
            "profile_version": 1,
            "completion_version": "v1",
            "completion_percent": 0,
            "completed_sections": [],
            "missing_requirements": [
                "personal.preferred_language",
                "personal.city",
                "academic.college",
                "academic.year_of_study",
                "academic.enrolment_number",
                "interests.interests",
                "interests.goals",
            ],
            "next_incomplete_section": "personal",
            "is_complete": False,
            "institutional_email_status": "not_provided",
            "guardian": {"required": False, "status": "not_required"},
            "access_mode": "full",
            "disabled_capabilities": [],
            "profile_prompt": {
                "should_show": True,
                "dismissed_for_session": False,
            },
            "profile": {
                "personal": {
                    "first_name": payload["first_name"],
                    "middle_name": payload["middle_name"],
                    "last_name": payload["last_name"],
                    "date_of_birth": payload["dob"],
                    "preferred_language": None,
                    "city": None,
                    "pronouns": None,
                },
                "academic": {
                    "college": None,
                    "year_of_study": None,
                    "enrolment_number": None,
                    "institutional_email": None,
                    "bar_enrolment_number": None,
                },
                "interests": {"interests": [], "goals": []},
            },
        },
    }


def test_signup_activation_requires_exact_server_owned_onboarding_projection():
    payload = _base_registration_payload(906)
    expected = _expected_signup_onboarding(payload)

    assert gate._signup_authenticated_projection_is_exact(
        _Response(200, expected), registration_payload=payload
    )
    mutants = []
    for mutation in (
        lambda body: body.pop("onboarding"),
        lambda body: body.update({"extra": False}),
        lambda body: body["onboarding"].update({"profile_version": 2}),
        lambda body: body["onboarding"]["profile_prompt"].update(
            {"should_show": False}
        ),
        lambda body: body["onboarding"]["guardian"].update(
            {"status": "required_pending"}
        ),
        lambda body: body["onboarding"]["profile"]["personal"].update(
            {"first_name": "Changed"}
        ),
        lambda body: body["onboarding"]["profile"]["academic"].update(
            {"college": "Client supplied"}
        ),
        lambda body: body["onboarding"]["profile"]["interests"].update(
            {"goals": ["Changed"]}
        ),
    ):
        body = deepcopy(expected)
        mutation(body)
        mutants.append(body)
    assert all(
        not gate._signup_authenticated_projection_is_exact(
            _Response(200, body), registration_payload=payload
        )
        for body in mutants
    )
    assert not gate._signup_authenticated_projection_is_exact(
        _Response(201, expected), registration_payload=payload
    )

    activation_source = pyinspect.getsource(gate._run_activation_probe)
    race_source = pyinspect.getsource(gate._run_activation_retention_race)
    assembly_source = pyinspect.getsource(gate._assemble_assertions)
    assert "_signup_authenticated_projection_is_exact(" in activation_source
    assert "_signup_authenticated_projection_is_exact(" in race_source
    assert 'activation["verification_body_exact"]' in assembly_source


def test_activation_retention_race_retries_only_the_canonical_mentor_boundary_conflict():
    """A newly fenced erasure retries once after activation changes its prelock."""

    from app.services.mentor_ceremony import MentorCeremonyError

    calls = 0

    def retryable_operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MentorCeremonyError(
                409, "CONCURRENT_STATE_CHANGED", retryable=True
            )
        return True

    assert gate._retry_subject_erasure_boundary_once(retryable_operation) == (
        True,
        1,
    )
    assert calls == 2

    for rejected in (
        MentorCeremonyError(409, "CONCURRENT_STATE_CHANGED", retryable=False),
        MentorCeremonyError(400, "CONCURRENT_STATE_CHANGED", retryable=True),
        MentorCeremonyError(409, "OTHER_FAILURE", retryable=True),
        RuntimeError("CONCURRENT_STATE_CHANGED"),
    ):
        rejected_calls = 0

        def rejected_operation():
            nonlocal rejected_calls
            rejected_calls += 1
            raise rejected

        with pytest.raises(type(rejected)) as caught:
            gate._retry_subject_erasure_boundary_once(rejected_operation)
        assert caught.value is rejected
        assert rejected_calls == 1

    exhausted_calls = 0
    exhausted = MentorCeremonyError(
        409, "CONCURRENT_STATE_CHANGED", retryable=True
    )

    def exhausted_operation():
        nonlocal exhausted_calls
        exhausted_calls += 1
        raise exhausted

    with pytest.raises(MentorCeremonyError) as exhausted_caught:
        gate._retry_subject_erasure_boundary_once(exhausted_operation)
    assert exhausted_caught.value is exhausted
    assert exhausted_calls == 2

    race_source = pyinspect.getsource(gate._run_activation_retention_race)
    assert race_source.count("_retry_subject_erasure_boundary_once(") == 2


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
        _Response(202, {"registration_id": raw_identifier, "status": "accepted"})
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
    assert success == {"status_code": 202, "shape": "object"}
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
