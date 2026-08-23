"""Pure fail-closed oracles for the opt-in NYAY-4 PostgreSQL gate.

These tests never connect to PostgreSQL and make no product-behaviour claim.
They prove that the gate's routing, exact ordered assertion inventory, strict
observation evaluators, seeded-mutant inventory, evidence privacy, and scratch
cleanup cannot turn incomplete or vulnerable evidence green.  PostgreSQL 16 +
pgvector behaviour is authoritative only when the separate opt-in gate runs.
"""

from __future__ import annotations

import importlib
import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from inspect import getsource
from types import SimpleNamespace
from typing import Callable

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import scripts.nyay4_postgres_otp_gate as gate
from scripts.nyay4_postgres_otp_gate import (
    BEHAVIOR_FIXTURE_MOBILES,
    COOKIE_TIMING_SAMPLE_ORDER,
    LIBPQ_AMBIENT_KEYS,
    EXPECTED_0019_CHECKS,
    EXPECTED_0019_CHECK_SQL,
    EXPECTED_0019_COLUMNS,
    REQUIRED_ASSERTION_IDS,
    REQUIRED_CONFIG_REJECTION_CASES,
    REQUIRED_MUTANT_IDS,
    Blocked,
    ScratchCleanupFailure,
    _CertifiedGateProvider,
    _ScratchDatabaseManager,
    _claim_observation_passes,
    _behavior_fixture_mobile_inventory_is_unique,
    _canonical_check_sql,
    _config_observation_passes,
    _concurrent_verify_observation_passes,
    _compose_retry_observation,
    _compose_rate_observation,
    _cookie_observation_passes,
    _db_gate_wiring_is_exact,
    _evaluate_assertions,
    _exact_schema_observation,
    _failed_resend_observation_passes,
    _harness_observation_passes,
    _historical_migration_bytes_unchanged,
    _lockout_observation_passes,
    _metadata_observation_passes,
    _migration_observation_passes,
    _populated_migration_observation_passes,
    _preauth_enumeration_observation_passes,
    _privacy_findings,
    _privacy_observation_projection,
    _provider_observation_passes,
    _rate_observation_passes,
    _reject_ambient_libpq_environment,
    _resend_observation_passes,
    _retry_observation_passes,
    _runtime_observation_passes,
    _run_configuration_probe,
    _run_concurrent_resend_probe,
    _run_concurrent_verify_probe,
    _run_cookie_projection_probe,
    _run_claim_concurrency_probe,
    _run_exact_schema_probe,
    _run_expired_active_resend_probe,
    _run_failed_resend_probe,
    _run_initial_exhaustion_probe,
    _run_lockout_probe,
    _run_maintenance_entrypoint_probe,
    _run_metadata_probe,
    _run_neutralized_concurrency_probe,
    _run_migration_lifecycle_probe,
    _run_neutralized_registration_probe,
    _run_populated_migration_probe,
    _run_pending_registration_lifecycle_probe,
    _run_preauth_enumeration_probe,
    _run_provider_idempotency_probe,
    _run_rate_budget_probe,
    _run_retry_lease_probe,
    _run_signup_verify_symmetry_probe,
    _run_start_resend_alternation_probe,
    _safe_local_postgres_url,
    _safe_response_signature,
    _schema_observation_passes,
    _seeded_mutants_are_killed,
    _seeded_mutant_results,
    _timing_ratio_observation,
)


_SQLITE_LEDGER_KEY_UNIQUE_FAILURE = (
    "UNIQUE constraint failed: "
    "registration_idempotency_records.idempotency_key_hash"
)


def _sqlite_exact_ledger_constraint_adapter(
    exc: IntegrityError,
    delegate: Callable[[IntegrityError], str | None],
) -> str | None:
    """Give the pure SQLite race PostgreSQL-equivalent exact attribution.

    Production deliberately translates only database-reported constraint
    names. SQLite does not expose one, so the exact-migration pure test maps
    only its byte-exact ledger-key UNIQUE diagnostic; every near miss remains
    unclassified and therefore fail closed.
    """

    reported = delegate(exc)
    if reported is not None:
        return reported
    if (
        type(exc.orig) is sqlite3.IntegrityError
        and getattr(exc.orig, "sqlite_errorcode", None)
        == sqlite3.SQLITE_CONSTRAINT_UNIQUE
        and getattr(exc.orig, "sqlite_errorname", None)
        == "SQLITE_CONSTRAINT_UNIQUE"
        and str(exc.orig) == _SQLITE_LEDGER_KEY_UNIQUE_FAILURE
    ):
        return "uq_registration_idempotency_records_idempotency_key_hash"
    return None


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
def test_ambient_libpq_routing_and_credentials_are_rejected_without_echo(key):
    with pytest.raises(Blocked) as caught:
        _reject_ambient_libpq_environment({key: "secret-value-must-not-echo"})
    assert "secret-value-must-not-echo" not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    (
        "postgresql+psycopg://qa:secret@localhost:5432/postgres",
        "postgresql+psycopg://qa:secret@127.0.0.1:5432/postgres",
        "postgresql+psycopg://qa:secret@[::1]:5432/postgres",
    ),
)
def test_safe_url_accepts_only_query_free_loopback_postgresql(url):
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
            "postgresql+psycopg://qa:secret@localhost@evil.invalid/postgres",
            "authority is ambiguous",
        ),
        (
            "postgresql+psycopg://qa:secret@localhost/postgres?host=evil.invalid",
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


def _assertions() -> list[dict[str, object]]:
    return [{"id": identifier, "passed": True} for identifier in REQUIRED_ASSERTION_IDS]


def test_assertion_inventory_is_exact_ordered_and_fully_green():
    evaluated = _evaluate_assertions(_assertions())
    assert len(REQUIRED_ASSERTION_IDS) == 17
    assert "CONTRACT-PREAUTH-ENUMERATION-NEUTRAL" in REQUIRED_ASSERTION_IDS
    assert evaluated == {
        "exact_inventory": True,
        "required": 17,
        "passed": 17,
        "failed": [],
        "inventory_failures": {
            "missing": 0,
            "extra": 0,
            "duplicate": 0,
            "reordered": False,
        },
        "overall_pass": True,
    }


def test_immutable_migration_oracle_pins_every_0001_through_0018_byte(
    monkeypatch,
):
    assert _historical_migration_bytes_unchanged()
    mutated = dict(gate.POST_LEDGER_HISTORICAL_SHA256)
    mutated["0018_registration_idempotency.py"] = "0" * 64
    monkeypatch.setattr(gate, "POST_LEDGER_HISTORICAL_SHA256", mutated)
    assert not _historical_migration_bytes_unchanged()


def test_historical_lifecycle_and_current_application_heads_are_separate():
    assert gate.PREVIOUS_REVISION == "0018_registration_idempotency"
    assert gate.PINNED_HEAD == "0019_otp_security_authority"
    assert gate.APPLICATION_HEAD == "0021_nyay5_profile_boundary"

    config = Config(str(gate.BACKEND / "alembic.ini"))
    config.set_main_option(
        "script_location", str(gate.BACKEND / "app" / "db" / "migrations")
    )
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [gate.APPLICATION_HEAD]
    retention = scripts.get_revision("0020_auth_retention_lifecycle")
    assert scripts.get_revision(gate.APPLICATION_HEAD).down_revision == retention.revision
    assert retention.down_revision == gate.PINNED_HEAD

    lifecycle_source = getsource(gate._run_migration_lifecycle_probe)
    behavior_source = getsource(gate._run_behavior_probe)
    assert '"upgrade", PINNED_HEAD' in lifecycle_source
    assert '"upgrade", PINNED_HEAD' in behavior_source
    assert '"upgrade", APPLICATION_HEAD' in behavior_source
    assert behavior_source.index('"upgrade", PINNED_HEAD') < behavior_source.index(
        '"upgrade", APPLICATION_HEAD'
    )


def test_populated_restart_probe_uses_https_for_the_secure_staging_cookie():
    source = getsource(gate._run_populated_restart_probe)

    assert 'base_url="https://testserver"' in source
    assert "settings.app_env" not in source


def test_0019_sqlite_lifecycle_proves_induced_ddl_failures_are_atomic(tmp_path):
    database = tmp_path / "nyay4-lifecycle.db"
    observation = _run_migration_lifecycle_probe(f"sqlite+pysqlite:///{database}")
    assert _migration_observation_passes(observation)


@pytest.mark.parametrize("attempt", range(3))
def test_0019_populated_upgrade_backfills_authority_and_runtime_restarts_signup(
    tmp_path, attempt
):
    database = tmp_path / f"nyay4-populated-{attempt}.db"
    observation = _run_populated_migration_probe(f"sqlite+pysqlite:///{database}")
    assert _populated_migration_observation_passes(observation)
    assert observation["legacy_rows"] == 2
    assert observation["authority_rows"] == 2
    assert observation["flow_rows"] == 0
    assert observation["post_upgrade_restart_status"] == 202
    assert observation["post_upgrade_resend_status"] == 202
    assert observation["post_upgrade_verify_status"] == 200


def test_populated_evaluator_rejects_unsafe_migration_minted_flow():
    observation = _populated_migration()
    observation["flow_rows"] = observation["legacy_rows"]
    assert not _populated_migration_observation_passes(observation)


@pytest.mark.parametrize(
    "field,value",
    (
        ("post_upgrade_restart_status", 409),
        ("post_upgrade_restart_cookie_issued", False),
        ("post_upgrade_restart_uuid_exposed", True),
        ("post_upgrade_resend_status", 500),
        ("post_upgrade_provider_acceptances", 0),
        ("post_upgrade_verify_status", 401),
        ("post_upgrade_registration_active", False),
        ("post_upgrade_ledger_retired", False),
        ("post_upgrade_terminal_replays_uniform", False),
        ("post_upgrade_terminal_replays_zero_delta", False),
    ),
)
def test_populated_evaluator_rejects_unrecoverable_post_upgrade_signup(
    field, value
):
    observation = _populated_migration()
    observation[field] = value
    assert not _populated_migration_observation_passes(observation)


def test_0019_exact_schema_oracle_pins_every_owned_surface(tmp_path):
    database = tmp_path / "nyay4-exact-schema.db"
    url = f"sqlite+pysqlite:///{database}"
    observation = _run_exact_schema_probe(url)
    assert _schema_observation_passes(observation)

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_otp_flows_authority_id"))
        assert not _exact_schema_observation(engine)["exact_indexes"]
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE INDEX ix_otp_flows_authority_id ON otp_flows (authority_id)"
                )
            )
            connection.execute(text("CREATE TABLE otp_unreviewed_mutant (id INTEGER)"))
        assert not _exact_schema_observation(engine)["exact_tables"]
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE otp_unreviewed_mutant"))
            connection.execute(text("ALTER TABLE otp_flows ADD COLUMN raw_ip TEXT"))
        mutated = _exact_schema_observation(engine)
        assert not mutated["exact_columns"]
        assert mutated["raw_sensitive_columns"] == 1
        assert not _schema_observation_passes(mutated)
    finally:
        engine.dispose()


def test_exact_check_contract_is_exhaustive_and_reparenthesization_sensitive():
    expected_names = set().union(*EXPECTED_0019_CHECKS.values())
    assert set(EXPECTED_0019_CHECK_SQL) == expected_names
    original = EXPECTED_0019_CHECK_SQL["ck_otp_flows_verified_links"]
    mutant = (
        "(state <> 'verified' OR registration_id IS NOT NULL) "
        "AND challenge_id IS NOT NULL"
    )
    assert _canonical_check_sql(original) != _canonical_check_sql(mutant)
    literal_mutant = EXPECTED_0019_CHECK_SQL["ck_otp_flows_state"].replace(
        "'failed'", "'failure'"
    )
    assert _canonical_check_sql(EXPECTED_0019_CHECK_SQL["ck_otp_flows_state"]) != (
        _canonical_check_sql(literal_mutant)
    )


def _expected_check_inspector_rows():
    return {
        table: [
            {"name": name, "sqltext": EXPECTED_0019_CHECK_SQL[name]}
            for name in sorted(names)
        ]
        for table, names in EXPECTED_0019_CHECKS.items()
    }


def _expected_check_catalog_sql():
    return {
        (table, name): EXPECTED_0019_CHECK_SQL[name]
        for table, names in EXPECTED_0019_CHECKS.items()
        for name in names
    }


class _CheckInspector:
    def __init__(self, rows):
        self.rows = rows

    def get_check_constraints(self, table):
        return self.rows[table]


class _CatalogConnection:
    def __init__(self, rows=(), error=None, captured=None):
        self.rows = rows
        self.error = error
        self.captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, statement, parameters):
        if self.captured is not None:
            self.captured["statement"] = str(statement)
            self.captured["parameters"] = parameters
        if self.error is not None:
            raise self.error
        return self.rows


class _CatalogEngine:
    def __init__(self, rows=(), error=None, captured=None):
        self.rows = rows
        self.error = error
        self.captured = captured

    def connect(self):
        return _CatalogConnection(self.rows, self.error, self.captured)


_REFLECTED_PENDING_STATUS = (
    "(status)::text = ANY ((ARRAY['pending'::character varying, "
    "'claimed'::character varying, 'failed'::character varying])::text[])"
)
_REFLECTED_TERMINAL_STATUS = (
    "(status)::text = ANY ((ARRAY['sent'::character varying, "
    "'void'::character varying])::text[])"
)
_REFLECTED_PENDING_ARM = (
    f"(({_REFLECTED_PENDING_STATUS}) AND (code_ct IS NOT NULL) AND "
    "(destination_ct IS NOT NULL) AND "
    "(legacy_destination_retained = false))"
)
_REFLECTED_TERMINAL_ARM = (
    f"(({_REFLECTED_TERMINAL_STATUS}) AND (code_ct IS NULL) AND "
    "(((destination_ct IS NULL) AND "
    "(legacy_destination_retained = false)) OR "
    "((destination_ct IS NOT NULL) AND "
    "(legacy_destination_retained = true))))"
)
_REFLECTED_PAYLOAD_CHECK = (
    f"{_REFLECTED_PENDING_ARM} OR {_REFLECTED_TERMINAL_ARM}"
)


def test_postgresql_reflected_any_array_payload_is_exactly_canonicalized():
    expected = EXPECTED_0019_CHECK_SQL["ck_otp_outbox_payload_shape"]
    assert _canonical_check_sql(_REFLECTED_PAYLOAD_CHECK) == _canonical_check_sql(
        expected
    )


def test_catalog_expression_avoids_inspector_cross_branch_parenthesis_damage():
    expected = EXPECTED_0019_CHECK_SQL["ck_otp_outbox_payload_shape"]
    assert _canonical_check_sql(_REFLECTED_PAYLOAD_CHECK) == _canonical_check_sql(
        expected
    )
    inspector_damaged = _REFLECTED_PAYLOAD_CHECK[1:-1]
    with pytest.raises(ValueError):
        _canonical_check_sql(inspector_damaged)


def test_postgresql_check_catalog_query_is_schema_and_table_scoped():
    captured: dict[str, object] = {}
    observed = gate._postgresql_check_constraint_sql(
        _CatalogEngine(
            rows=[
                (
                    "otp_outbox",
                    "ck_otp_outbox_payload_shape",
                    _REFLECTED_PAYLOAD_CHECK,
                )
            ],
            captured=captured,
        )
    )
    assert observed == {
        (
            "otp_outbox",
            "ck_otp_outbox_payload_shape",
        ): _REFLECTED_PAYLOAD_CHECK
    }
    statement = str(captured["statement"])
    assert "pg_get_expr(con.conbin, con.conrelid, false)" in statement
    assert "con.contype = 'c'" in statement
    assert "ns.nspname = current_schema()" in statement
    assert "cls.relname IN" in statement
    assert captured["parameters"] == {
        "table_names": tuple(EXPECTED_0019_CHECKS)
    }
    oracle_source = getsource(gate._check_constraints_are_exact)
    assert "inspector.get_check_constraints(table)" in oracle_source
    assert "_postgresql_check_constraint_sql(engine)" in oracle_source


def test_postgresql_check_catalog_query_failures_return_no_authority():
    assert gate._postgresql_check_constraint_sql(
        _CatalogEngine(error=SQLAlchemyError("sanitized"))
    ) is None
    row = (
        "otp_outbox",
        "ck_otp_outbox_payload_shape",
        _REFLECTED_PAYLOAD_CHECK,
    )
    assert gate._postgresql_check_constraint_sql(
        _CatalogEngine(rows=[row, row])
    ) is None
    assert gate._postgresql_check_constraint_sql(
        _CatalogEngine(rows=[(row[0], row[1], None)])
    ) is None


def test_postgresql_check_oracle_uses_balanced_catalog_but_keeps_inspector_inventory(
    monkeypatch,
):
    rows = _expected_check_inspector_rows()
    for item in rows["otp_outbox"]:
        if item["name"] == "ck_otp_outbox_payload_shape":
            item["sqltext"] = _REFLECTED_PAYLOAD_CHECK[1:-1]
    catalog = _expected_check_catalog_sql()
    catalog[("otp_outbox", "ck_otp_outbox_payload_shape")] = (
        _REFLECTED_PAYLOAD_CHECK
    )
    monkeypatch.setattr(
        gate, "_postgresql_check_constraint_sql", lambda _engine: catalog
    )
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    exact, by_name = gate._check_constraints_are_exact(
        _CheckInspector(rows), engine
    )
    assert exact
    assert all(by_name.values())

    missing = deepcopy(rows)
    missing["otp_outbox"] = missing["otp_outbox"][1:]
    assert not gate._check_constraints_are_exact(
        _CheckInspector(missing), engine
    )[0]
    duplicate = deepcopy(rows)
    duplicate["otp_outbox"].append(deepcopy(duplicate["otp_outbox"][0]))
    assert not gate._check_constraints_are_exact(
        _CheckInspector(duplicate), engine
    )[0]


@pytest.mark.parametrize("dialect_option", ("not_valid", "no_inherit"))
def test_postgresql_check_oracle_rejects_nonempty_dialect_options(
    monkeypatch, dialect_option
):
    rows = _expected_check_inspector_rows()
    rows["otp_outbox"][0]["dialect_options"] = {dialect_option: True}
    catalog = _expected_check_catalog_sql()
    monkeypatch.setattr(
        gate, "_postgresql_check_constraint_sql", lambda _engine: catalog
    )
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    assert not gate._check_constraints_are_exact(
        _CheckInspector(rows), engine
    )[0]


def test_postgresql_check_oracle_rejects_catalog_key_and_expression_mutants(
    monkeypatch,
):
    rows = _expected_check_inspector_rows()
    expected_catalog = _expected_check_catalog_sql()
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    expected_key = next(iter(expected_catalog))

    missing = dict(expected_catalog)
    missing.pop(expected_key)
    extra = dict(expected_catalog)
    extra[("otp_outbox", "ck_unreviewed_extra")] = "1 = 1"
    wrong_table = dict(expected_catalog)
    value = wrong_table.pop(expected_key)
    wrong_table[("otp_unreviewed", expected_key[1])] = value
    for mutant in (missing, extra, wrong_table):
        monkeypatch.setattr(
            gate,
            "_postgresql_check_constraint_sql",
            lambda _engine, mutant=mutant: mutant,
        )
        assert not gate._check_constraints_are_exact(
            _CheckInspector(rows), engine
        )[0]

    mutated_expression = dict(expected_catalog)
    payload_key = ("otp_outbox", "ck_otp_outbox_payload_shape")
    mutated_expression[payload_key] = EXPECTED_0019_CHECK_SQL[
        payload_key[1]
    ].replace("'failed'", "'failure'", 1)
    monkeypatch.setattr(
        gate,
        "_postgresql_check_constraint_sql",
        lambda _engine: mutated_expression,
    )
    assert not gate._check_constraints_are_exact(
        _CheckInspector(rows), engine
    )[0]


def test_sqlite_check_oracle_never_queries_postgresql_catalog(monkeypatch):
    def forbidden(_engine):
        raise AssertionError("PostgreSQL catalog must not be queried")

    monkeypatch.setattr(gate, "_postgresql_check_constraint_sql", forbidden)
    engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    exact, by_name = gate._check_constraints_are_exact(
        _CheckInspector(_expected_check_inspector_rows()), engine
    )
    assert exact
    assert all(by_name.values())


@pytest.mark.parametrize(
    "mutant",
    (
        _REFLECTED_PAYLOAD_CHECK.replace("'failed'", "'failure'", 1),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "'failed'::character varying",
            "'failed'::character varying, 'queued'::character varying",
            1,
        ),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "'claimed'::character varying, ", "", 1
        ),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "'pending'::character varying, 'claimed'::character varying",
            "'claimed'::character varying, 'pending'::character varying",
            1,
        ),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "'failed'::character varying",
            "'failed'::character varying, 'failed'::character varying",
            1,
        ),
        (
            f"((({_REFLECTED_PENDING_STATUS}) OR "
            f"({_REFLECTED_TERMINAL_STATUS})) AND (code_ct IS NULL) AND "
            "(((destination_ct IS NULL) AND "
            "(legacy_destination_retained = false)) OR "
            "((destination_ct IS NOT NULL) AND "
            "(legacy_destination_retained = true))))"
        ),
    ),
)
def test_reflected_any_array_semantic_mutants_never_match_payload(mutant):
    expected = EXPECTED_0019_CHECK_SQL["ck_otp_outbox_payload_shape"]
    assert _canonical_check_sql(mutant) != _canonical_check_sql(expected)


@pytest.mark.parametrize(
    "mutant",
    (
        _REFLECTED_PAYLOAD_CHECK.replace(
            "])::text[])", "]::text[])", 1
        ),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "'pending'::character varying", "pending", 1
        ),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "'pending'::character varying", "7", 1
        ),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "ARRAY['pending'::character varying, "
            "'claimed'::character varying, 'failed'::character varying]",
            "ARRAY[]",
            1,
        ),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "])::text[])", "], 'extra'::character varying)::text[])", 1
        ),
        _REFLECTED_PAYLOAD_CHECK.replace("= ANY", "<> ANY", 1),
        _REFLECTED_PAYLOAD_CHECK.replace("= ANY", "= ALL", 1),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "'pending'::character varying",
            "ANY (ARRAY['nested'::text])",
            1,
        ),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "'pending'::character varying",
            "'pending'::character varying(7)",
            1,
        ),
        _REFLECTED_PAYLOAD_CHECK.replace(
            "])::text[])", "])::character varying(16)[])", 1
        ),
    ),
)
def test_reflected_any_array_malformed_or_nonliteral_shapes_fail_closed(mutant):
    with pytest.raises(ValueError):
        _canonical_check_sql(mutant)


def test_any_array_normalizer_is_inactive_for_declared_checks_and_indexes():
    historical = importlib.import_module(
        "app.db.migrations.versions.0018_registration_idempotency"
    )
    declared = list(EXPECTED_0019_CHECK_SQL.values())
    declared.extend(
        predicate
        for indexes in gate.EXPECTED_0019_INDEXES.values()
        for _name, _columns, _unique, predicate in indexes
        if predicate is not None
    )
    assert declared
    for source in declared:
        assert gate._normalise_reflected_any_array_sql(source, historical) == source
    non_any_unrelated = (
        "status::varchar(16) = ALL "
        "(ARRAY['pending'::varchar(16)]::varchar(16)[])"
    )
    assert (
        gate._normalise_reflected_any_array_sql(non_any_unrelated, historical)
        == non_any_unrelated
    )


def test_every_0019_metadata_identifier_fits_postgresql_limit():
    import app.models  # noqa: F401
    from app.db.base import Base

    for table_name in EXPECTED_0019_COLUMNS:
        table = Base.metadata.tables[table_name]
        for item in (*table.constraints, *table.indexes):
            if item.name is not None:
                assert len(item.name.encode("utf-8")) <= 63, item.name


@pytest.mark.parametrize("index", range(len(REQUIRED_ASSERTION_IDS)))
def test_each_required_assertion_independently_blocks_release(index):
    assertions = _assertions()
    assertions[index]["passed"] = False
    evaluated = _evaluate_assertions(assertions)
    assert not evaluated["overall_pass"]
    assert evaluated["failed"] == [REQUIRED_ASSERTION_IDS[index]]


def test_missing_extra_duplicate_and_reordered_assertions_never_pass():
    variants = []
    missing = _assertions()
    missing.pop()
    variants.append(missing)
    extra = _assertions() + [{"id": "UNREVIEWED", "passed": True}]
    variants.append(extra)
    duplicate = _assertions() + [_assertions()[0]]
    variants.append(duplicate)
    reordered = _assertions()
    reordered[0], reordered[1] = reordered[1], reordered[0]
    variants.append(reordered)
    assert all(not _evaluate_assertions(item)["overall_pass"] for item in variants)


def _runtime() -> dict[str, object]:
    return {
        "postgres_major": 16,
        "pgvector_present": True,
        "loopback": True,
        "query_free": True,
        "ambient_rejected": True,
    }


def test_runtime_probe_checks_pgvector_in_supplied_gate_database(monkeypatch):
    captured: dict[str, object] = {}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalar(self, statement):
            sql = str(statement)
            return "160015" if "server_version_num" in sql else "0.8.6"

    class Engine:
        def connect(self):
            return Connection()

        def dispose(self):
            captured["disposed"] = True

    def create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return Engine()

    monkeypatch.setattr(gate, "create_engine", create_engine)
    base = make_url(
        "postgresql+psycopg://gate:secret@127.0.0.1:55489/"
        "nyay19_corrective_qa"
    )

    assert gate._runtime_probe(base) == _runtime()
    assert make_url(str(captured["url"])).database == "nyay19_corrective_qa"
    assert captured["disposed"] is True


def _migration() -> dict[str, object]:
    return {
        "start_revision": gate.PREVIOUS_REVISION,
        "head_revision": gate.PINNED_HEAD,
        "single_head": True,
        "upgrade": True,
        "downgrade": True,
        "reupgrade": True,
        "alembic_check": True,
        "historical_digest_unchanged": True,
        "row_projection_unchanged": True,
        "parent_validator_exact": True,
        "multi_step_downgrade_reupgrade": True,
        "upgrade_failure_atomic": True,
        "downgrade_failure_atomic": True,
        "retry_after_induced_failure": True,
    }


def _populated_migration() -> dict[str, object]:
    return {
        "legacy_rows": 2,
        "authority_rows": 2,
        "flow_rows": 0,
        "challenge_authority_nonnull": True,
        "flow_authority_nonnull": True,
        "raw_subject_columns": 0,
        "raw_ip_columns": 0,
        "old_writer_challenge_rejected": True,
        "legacy_destination_writer_rejected": True,
        "post_upgrade_restart_status": 202,
        "post_upgrade_restart_cookie_issued": True,
        "post_upgrade_restart_uuid_exposed": False,
        "post_upgrade_resend_status": 202,
        "post_upgrade_provider_acceptances": 1,
        "post_upgrade_verify_status": 200,
        "post_upgrade_registration_active": True,
        "post_upgrade_ledger_retired": True,
        "post_upgrade_terminal_replays_uniform": True,
        "post_upgrade_terminal_replays_zero_delta": True,
        "downgrade_rejected": True,
        "revision_unchanged": True,
        "schema_unchanged": True,
        "rows_unchanged": True,
    }


def _schema() -> dict[str, object]:
    return {
        "exact_tables": True,
        "exact_columns": True,
        "exact_primary_keys": True,
        "exact_unique_constraints": True,
        "exact_foreign_keys": True,
        "exact_check_constraints": True,
        "exact_indexes": True,
        "challenge_authority_nonnull": True,
        "flow_authority_nonnull": True,
        "provider_key_shape": True,
        "claim_state_shape": True,
        "neutralized_ledger_shape": True,
        "raw_sensitive_columns": 0,
    }


def _lockout() -> dict[str, object]:
    return {
        "configured_max_attempts": 3,
        "configured_lock_seconds": 900,
        "wrong_statuses": [401, 401, 423],
        "wrong_codes": ["invalid_otp", "invalid_otp", "locked"],
        "attempts_after_wrong": 3,
        "locked": True,
        "resend_status": 423,
        "resend_code": "locked",
        "attempts_after_resend": 3,
        "lock_deadline_unchanged": True,
        "new_delivery_delta": 0,
    }


def _concurrent_verify() -> dict[str, object]:
    return {
        "workers": 8,
        "completed": 8,
        "deadlocks": 0,
        "successes": 0,
        "typed_failures": 8,
        "stored_attempts": 3,
        "configured_max_attempts": 3,
        "locked": True,
        "active_challenges": 1,
        "deliverable_outboxes": 0,
    }


def _resend() -> dict[str, object]:
    return {
        "workers": 8,
        "completed": 8,
        "deadlocks": 0,
        "accepted_resends": 1,
        "typed_rejections": 7,
        "authority_rows": 1,
        "staged_challenges": 1,
        "active_challenges": 1,
        "deliverable_outboxes": 1,
        "attempts_unchanged": True,
        "lock_unchanged": True,
        "resend_budget_delta": 1,
        "expired_active_status_before_resend": "pending",
        "expired_active_resend_allowed": True,
        "expired_active_resend_status": 202,
        "expired_active_replacement_active": True,
        "expired_active_attempts_unchanged": True,
        "expired_active_delivery_delta": 1,
        "alternation_purposes": ["login", "recovery"],
        "fractional_retry_after_ceil": True,
        "exhausted_start_status": 429,
        "exhausted_start_zero_delivery": True,
        "alternation_real_decoy_equal": True,
    }


def _failed_resend() -> dict[str, object]:
    return {
        "status": 502,
        "code": "otp_delivery_failed",
        "prior_active_unchanged": True,
        "prior_verification_succeeds": True,
        "replacement_active": False,
        "replacement_deliverable": False,
        "provider_acceptances": 0,
        "authority_unchanged": True,
    }


_RATE_DIMENSIONS = {
    "identity_issue",
    "identity_resend",
    "identity_verify",
    "ip_issue",
    "ip_resend",
    "ip_verify",
    "global_issue",
    "global_resend",
    "global_verify",
}


def _maintenance() -> dict[str, object]:
    return {
        "entrypoint_executed": True,
        "counts_aggregate_only": True,
        "aged_bucket_purged": True,
        "recent_bucket_preserved": True,
        "aged_legacy_destination_purged": True,
        "recent_legacy_destination_preserved": True,
        "expired_flow_terminalized": True,
        "recent_flow_preserved": True,
        "expired_key_reuse_blocked": True,
    }


def _rate() -> dict[str, object]:
    return {
        "dimensions": sorted(_RATE_DIMENSIONS),
        "limits_positive": True,
        "accepted_equal_limits": True,
        "next_rejected": True,
        "retry_after_exact": True,
        "real_decoy_symmetric": True,
        "untrusted_forwarded_for_ignored": True,
        "raw_identity_rows": 0,
        "raw_ip_rows": 0,
        "retention_preserves_active_budgets": True,
        "maintenance_entrypoint_executed": True,
        "aged_buckets_purged": True,
        "active_recent_buckets_preserved": True,
    }


def _cookie() -> dict[str, object]:
    return {
        "start_statuses": [202, 202],
        "start_signatures_equal": True,
        "timing_ratio_within_bound": True,
        "timing_samples_per_class": 40,
        "timing_p95_ratio_milli": 1100,
        "timing_bound_milli": 2000,
        "cookie_httponly": True,
        "cookie_secure_nonlocal": True,
        "cookie_samesite": "strict",
        "raw_flow_token_rows": 0,
        "uuid_in_response": False,
        "reload_status": 200,
        "reload_metadata_equal": True,
        "origin_missing_status": 403,
        "origin_bad_status": 403,
        "origin_good_status": 200,
        "invalid_expired_consumed_signatures_equal": True,
        "invalid_expired_consumed_values_equal": True,
        "terminal_verify_zero_delta": True,
        "initial_exhaustion_purposes": ["login", "recovery"],
        "initial_exhaustion_known_decoy_shapes_equal": True,
        "initial_exhaustion_known_decoy_values_equal": True,
        "initial_exhaustion_symmetry_through_flow_ttl": True,
        "fully_expired_status": "unavailable",
        "fully_expired_known_decoy_values_equal": True,
        "neutralized_key_request_bound": True,
        "neutralized_exact_replay_stable": True,
        "neutralized_live_mutations_conflict": True,
        "neutralized_concurrent_mismatch_linearized": True,
        "neutralized_expired_mutations_uniform": True,
        "neutralized_removed_mutations_uniform": True,
        "pending_expired_mutations_uniform": True,
        "pending_missing_mutations_uniform": True,
        "lifecycle_replay_zero_provider": True,
        "lifecycle_replay_zero_delta": True,
    }


def _preauth_enumeration() -> dict[str, object]:
    return {
        "classes": ["known", "unknown", "suspended", "ineligible"],
        "operations": ["login_start", "resend"],
        "start_statuses": [202, 202, 202, 202],
        "resend_statuses": [202, 202, 202, 202],
        "start_bodies_equal": True,
        "resend_bodies_equal": True,
        "start_headers_equal": True,
        "resend_headers_equal": True,
        "flow_cookies_exact": True,
        "start_delivery_deltas": [1, 0, 0, 0],
        "resend_delivery_deltas": [1, 0, 0, 0],
        "registration_bound_flows": 1,
        "decoy_flows": 3,
        "raw_identifier_exposed": False,
    }


def _metadata() -> dict[str, object]:
    return {
        "fields_exact": True,
        "attempts_from_authority": True,
        "cooldown_from_database": True,
        "expiry_from_database": True,
        "lock_from_database": True,
        "retry_after_matches": True,
        "bounded_clock_skew": True,
        "typed_outcomes_exact": True,
        "no_local_clock_authority": True,
    }


def _claim() -> dict[str, object]:
    return {
        "workers": 2,
        "completed": 2,
        "deadlocks": 0,
        "claims_won": 1,
        "provider_callbacks": 1,
        "provider_acceptances": 1,
        "newly_delivered_sum": 1,
        "active_claims": 0,
        "row_locks_during_callback": 0,
        "canary_lock_succeeded": True,
        "resend_while_claimed_rejected": True,
        "registration_finalizer_interleaving_passed": True,
    }


def _provider() -> dict[str, object]:
    return {
        "provider_contract_name": "nyay4_gate_idempotent_provider_v1",
        "provider_contract_certified": True,
        "real_provider_exactly_once_claimed": False,
        "provider_calls": 2,
        "provider_acceptances": 1,
        "ack_loss_injected": True,
        "retry_succeeded": True,
        "stable_key": True,
        "key_is_hmac64": True,
        "same_payload": True,
        "payload_conflict_rejected": True,
        "database_sent_once": True,
        "otp_ciphertext_erased": True,
    }


def _retry() -> dict[str, object]:
    return {
        "lease_expired_reclaimed": True,
        "new_claim_token": True,
        "stale_finalize_rejected": True,
        "stale_finalize_state_unchanged": True,
        "backoff_positive": True,
        "immediate_retry_claims": 0,
        "attempts_at_terminal": 3,
        "configured_max_attempts": 3,
        "terminal_status": "failed",
        "otp_ciphertext_erased": True,
        "destination_ciphertext_erased": True,
        "initial_exhaustion_recovery_same_authority": True,
        "initial_exhaustion_recovery_succeeded": True,
        "initial_exhaustion_stale_payload_rows": 0,
        "initial_exhaustion_exactly_one_acceptance_each": True,
        "initial_exhaustion_exactly_one_delivered_each": True,
        "aged_legacy_destinations_purged": True,
        "active_recent_outboxes_preserved": True,
        "expired_flows_terminalized": True,
        "expired_flow_key_reuse_blocked": True,
        "maintenance_counts_aggregate_only": True,
    }


_CONFIG_CASES = set(REQUIRED_CONFIG_REJECTION_CASES)


def _config() -> dict[str, object]:
    return {
        "cases": sorted(_CONFIG_CASES),
        "all_rejected": True,
        "production_booted": False,
        "valid_real_provider_booted": True,
        "provider_contract_certified": True,
        "errors_sanitized": True,
    }


def _harness() -> dict[str, object]:
    return {
        "mutants": {identifier: True for identifier in REQUIRED_MUTANT_IDS},
        "privacy_findings": 0,
        "privacy_scanned": True,
        "scratch_created": 3,
        "scratch_removed": 3,
        "scratch_failed": 0,
        "scratch_purposes": [
            "migration_lifecycle",
            "migration_populated",
            "behavior",
        ],
        "scratch_inventory_match": True,
        "all_created_removed": True,
        "frontend_server_authority": True,
        "gate_command_present": True,
    }


def test_db_gate_wiring_requires_exact_nyay4_then_nyay19_terminal_sequence():
    nyay17 = (
        '"$PY" scripts/nyay17_postgres_idempotency_gate.py '
        '--report test-results/nyay17-postgres/summary.json'
    )
    nyay4 = (
        'NYAY4_POSTGRES_GATE=1 "$PY" scripts/nyay4_postgres_otp_gate.py '
        '--execute --database-url "$DATABASE_URL" '
        '--output test-results/nyay4-postgres/summary.json'
    )
    nyay19 = (
        'NYAY19_POSTGRES_GATE_EXECUTE=1 "$PY" '
        'scripts/nyay19_postgres_auth_retention_gate.py '
        '--execute --database-url "$DATABASE_URL" '
        '--output test-results/nyay19-postgres/summary.json'
    )
    exact = "\n".join(("set -euo pipefail", nyay17, nyay4, nyay19))

    assert _db_gate_wiring_is_exact(exact)
    assert not _db_gate_wiring_is_exact(
        "\n".join(("set -euo pipefail", nyay17, nyay19, nyay4))
    )
    assert not _db_gate_wiring_is_exact("\n".join(("set -euo pipefail", nyay17, nyay4)))
    assert not _db_gate_wiring_is_exact(f"{exact}\necho stale-trailing-stage")
    assert not _db_gate_wiring_is_exact(
        exact.replace(nyay17, 'echo scripts/nyay17_postgres_idempotency_gate.py')
    )
    assert not _db_gate_wiring_is_exact(
        "\n".join((nyay17, "set -euo pipefail", nyay4, nyay19))
    )


_EVALUATOR_CASES = (
    (_runtime_observation_passes, _runtime),
    (_migration_observation_passes, _migration),
    (_populated_migration_observation_passes, _populated_migration),
    (_schema_observation_passes, _schema),
    (_lockout_observation_passes, _lockout),
    (_concurrent_verify_observation_passes, _concurrent_verify),
    (_resend_observation_passes, _resend),
    (_failed_resend_observation_passes, _failed_resend),
    (_rate_observation_passes, _rate),
    (_cookie_observation_passes, _cookie),
    (_preauth_enumeration_observation_passes, _preauth_enumeration),
    (_metadata_observation_passes, _metadata),
    (_claim_observation_passes, _claim),
    (_provider_observation_passes, _provider),
    (_retry_observation_passes, _retry),
    (_config_observation_passes, _config),
    (_harness_observation_passes, _harness),
)


@pytest.mark.parametrize("evaluator,factory", _EVALUATOR_CASES)
def test_each_exact_observation_accepts_only_its_complete_positive_shape(
    evaluator, factory
):
    observation = factory()
    assert evaluator(observation)
    missing = deepcopy(observation)
    missing.pop(next(iter(missing)))
    assert not evaluator(missing)
    extra = deepcopy(observation)
    extra["unreviewed"] = True
    assert not evaluator(extra)


@pytest.mark.parametrize(
    "evaluator,factory,mutations",
    (
        (
            _runtime_observation_passes,
            _runtime,
            {"postgres_major": 17, "pgvector_present": False},
        ),
        (
            _migration_observation_passes,
            _migration,
            {
                "single_head": False,
                "historical_digest_unchanged": False,
                "parent_validator_exact": False,
                "multi_step_downgrade_reupgrade": False,
                "upgrade_failure_atomic": False,
                "downgrade_failure_atomic": False,
                "retry_after_induced_failure": False,
            },
        ),
        (
            _populated_migration_observation_passes,
            _populated_migration,
            {
                "downgrade_rejected": False,
                "raw_ip_columns": 1,
                "old_writer_challenge_rejected": False,
                "legacy_destination_writer_rejected": False,
            },
        ),
        (
            _schema_observation_passes,
            _schema,
            {
                "exact_foreign_keys": False,
                "flow_authority_nonnull": False,
                "neutralized_ledger_shape": False,
            },
        ),
        (
            _lockout_observation_passes,
            _lockout,
            {"attempts_after_resend": 0, "new_delivery_delta": 1},
        ),
        (
            _concurrent_verify_observation_passes,
            _concurrent_verify,
            {"stored_attempts": 8, "deadlocks": 1},
        ),
        (
            _resend_observation_passes,
            _resend,
            {
                "accepted_resends": 2,
                "staged_challenges": 2,
                "expired_active_resend_allowed": False,
                "expired_active_delivery_delta": 2,
            },
        ),
        (
            _failed_resend_observation_passes,
            _failed_resend,
            {"prior_active_unchanged": False, "replacement_active": True},
        ),
        (
            _rate_observation_passes,
            _rate,
            {
                "untrusted_forwarded_for_ignored": False,
                "raw_ip_rows": 1,
                "maintenance_entrypoint_executed": False,
                "active_recent_buckets_preserved": False,
            },
        ),
        (
            _cookie_observation_passes,
            _cookie,
            {
                "timing_ratio_within_bound": False,
                "timing_samples_per_class": 41,
                "timing_p95_ratio_milli": 2001,
                "timing_bound_milli": 2500,
                "uuid_in_response": True,
                "origin_missing_status": 200,
                "initial_exhaustion_known_decoy_values_equal": False,
                "initial_exhaustion_symmetry_through_flow_ttl": False,
                "fully_expired_status": "pending",
                "invalid_expired_consumed_values_equal": False,
                "terminal_verify_zero_delta": False,
                "neutralized_live_mutations_conflict": False,
                "neutralized_expired_mutations_uniform": False,
                "pending_missing_mutations_uniform": False,
                "lifecycle_replay_zero_provider": False,
            },
        ),
        (
            _preauth_enumeration_observation_passes,
            _preauth_enumeration,
            {
                "start_statuses": [202, 202, 403, 202],
                "resend_bodies_equal": False,
                "start_headers_equal": False,
                "flow_cookies_exact": False,
                "start_delivery_deltas": [1, 0, 1, 0],
                "resend_delivery_deltas": [1, 0, 0, 1],
                "registration_bound_flows": 2,
                "raw_identifier_exposed": True,
            },
        ),
        (
            _metadata_observation_passes,
            _metadata,
            {"cooldown_from_database": False, "no_local_clock_authority": False},
        ),
        (
            _claim_observation_passes,
            _claim,
            {"claims_won": 2, "newly_delivered_sum": 2},
        ),
        (
            _provider_observation_passes,
            _provider,
            {"stable_key": False, "provider_acceptances": 2},
        ),
        (
            _retry_observation_passes,
            _retry,
            {
                "immediate_retry_claims": 1,
                "otp_ciphertext_erased": False,
                "initial_exhaustion_recovery_same_authority": False,
                "initial_exhaustion_stale_payload_rows": 1,
                "initial_exhaustion_exactly_one_acceptance_each": False,
                "aged_legacy_destinations_purged": False,
                "expired_flow_key_reuse_blocked": False,
                "maintenance_counts_aggregate_only": False,
            },
        ),
        (
            _config_observation_passes,
            _config,
            {"all_rejected": False, "provider_contract_certified": False},
        ),
        (
            _harness_observation_passes,
            _harness,
            {"privacy_findings": 1, "gate_command_present": False},
        ),
    ),
)
def test_each_observation_rejects_seeded_false_green_mutations(
    evaluator, factory, mutations
):
    for field, value in mutations.items():
        observation = factory()
        observation[field] = value
        assert not evaluator(observation), field


@pytest.mark.parametrize("dimension", sorted(_RATE_DIMENSIONS))
def test_rate_evaluator_requires_every_identity_ip_global_action_dimension(dimension):
    observation = _rate()
    observation["dimensions"].remove(dimension)
    assert not _rate_observation_passes(observation)


def test_config_evaluator_requires_every_invalid_production_case():
    assert _config_observation_passes(_config())
    for case in _CONFIG_CASES:
        observation = _config()
        observation["cases"].remove(case)
        assert not _config_observation_passes(observation), case


def test_real_configuration_validator_rejects_every_unsafe_boot_case():
    observation = _run_configuration_probe()
    assert _config_observation_passes(observation)


def test_named_provider_contract_deduplicates_same_token_and_exact_payload():
    provider = _CertifiedGateProvider()
    first = provider.send_idempotent(
        "private-destination", "private-code", idempotency_token="opaque-token"
    )
    second = provider.send_idempotent(
        "private-destination", "private-code", idempotency_token="opaque-token"
    )
    assert first == second
    assert provider.calls == 2
    assert provider.acceptance_count == 1


def test_provider_idempotency_key_is_stable_64hex_across_migration_and_runtime():
    import importlib
    import uuid

    from app.services.otp_outbox import provider_idempotency_key

    migration = importlib.import_module(
        "app.db.migrations.versions.0019_otp_security_authority"
    )
    outbox_id = uuid.UUID("e88009db-cc02-45b8-9136-fdfba74e428a")
    other_id = uuid.UUID("12263042-1013-4b1c-9f31-354a30a6ec44")
    first = provider_idempotency_key(outbox_id)
    assert first == migration._provider_key(outbox_id)
    assert first == provider_idempotency_key(outbox_id)
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")
    assert first != provider_idempotency_key(other_id)


def test_named_provider_contract_recovers_ack_loss_without_second_acceptance():
    from app.services.otp_sender import OtpSendError

    provider = _CertifiedGateProvider(lose_ack_after_accept_once=True)
    with pytest.raises(OtpSendError):
        provider.send_idempotent(
            "private-destination", "private-code", idempotency_token="opaque-token"
        )
    assert provider.send_idempotent(
        "private-destination", "private-code", idempotency_token="opaque-token"
    )
    assert provider.calls == 2
    assert provider.acceptance_count == 1


def test_initial_exhaustion_oracle_covers_login_recovery_and_decoy_recovery(
    tmp_path,
):
    """SQLite exercises the probe seam; PostgreSQL remains authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'exhaustion.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-exhaustion-encryption-v1"},
            lookup_secret=b"nyay4-pure-exhaustion-lookup-v1",
        )
    )
    try:
        observation = _run_initial_exhaustion_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert observation == {
        "purposes": ["login", "recovery"],
        "known_decoy_shapes_equal": True,
        "known_decoy_values_equal": True,
        "symmetry_through_flow_ttl": True,
        "fully_expired_status": "unavailable",
        "fully_expired_known_decoy_values_equal": True,
        "recovery_same_authority": True,
        "recovery_succeeded": True,
        "stale_payload_rows": 0,
        "exactly_one_acceptance_each": True,
        "exactly_one_delivered_each": True,
    }


def test_expired_active_challenge_can_resend_through_still_live_cookie(tmp_path):
    """SQLite exercises the probe seam; PostgreSQL remains authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'active-expiry.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-expiry-encryption-v1"},
            lookup_secret=b"nyay4-pure-expiry-lookup-v1",
        )
    )
    try:
        observation = _run_expired_active_resend_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert observation == {
        "status_before_resend": "pending",
        "expires_zero": True,
        "resend_allowed": True,
        "resend_status": 202,
        "same_authority": True,
        "replacement_active": True,
        "attempts_unchanged": True,
        "delivery_delta": 1,
        "provider_acceptance_delta": 1,
        "stale_payload_rows": 0,
    }


def test_signup_lockout_authority_survives_resend(tmp_path):
    """SQLite binds the service seam; PostgreSQL concurrency is separate."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'lockout.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-lockout-encryption-v1"},
            lookup_secret=b"nyay4-pure-lockout-lookup-v1",
        )
    )
    try:
        observation = _run_lockout_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert _lockout_observation_passes(observation)
    assert observation["wrong_statuses"] == [401, 401, 423]
    assert observation["wrong_codes"] == ["incorrect_otp", "incorrect_otp", "locked"]


def test_direct_registration_relay_fixtures_attach_signup_flow_before_commit():
    """Direct gate relays must stage the browser capability the product requires."""

    from scripts import postgres_runtime_gate

    sources = (
        getsource(gate._run_registration_finalizer_interleaving_probe),
        getsource(postgres_runtime_gate.main),
    )
    for source in sources:
        flow_creation = source.index("otp_flow_service.create_flow(")
        first_commit = source.index("session.commit()")
        assert flow_creation < first_commit
        assert "otp_flow_service.deterministic_signup_token(" in source
        assert "challenge=challenge" in source
        assert "registration_id=" in source
        assert "registration_idempotency_record_id=" in source


def test_postgres_runtime_gate_uses_separate_current_legal_acknowledgements():
    """The live PostgreSQL producer must not revive the legacy combined consent."""

    from scripts import postgres_runtime_gate

    source = getsource(postgres_runtime_gate.main)
    request_source = source[
        source.index("request = StudentRegisterRequest(") : source.index(
            "with factory() as session:"
        )
    ]
    assert "consent=" not in request_source
    assert "terms_accepted=True" in request_source
    assert 'terms_version="terms-2026-08.v1"' in request_source
    assert "privacy_notice_acknowledged=True" in request_source
    assert 'privacy_notice_version="privacy-2026-08.v1"' in request_source


def test_failed_resend_never_displaces_prior_delivered_verifier(tmp_path):
    """SQLite binds the lifecycle seam; PostgreSQL fencing is separate."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'failed-resend.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-failed-resend-encryption-v1"},
            lookup_secret=b"nyay4-pure-failed-resend-lookup-v1",
        )
    )
    try:
        observation = _run_failed_resend_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert _failed_resend_observation_passes(observation)


def test_relay_claim_commits_before_provider_and_fences_second_worker(tmp_path):
    """SQLite proves the seam; PostgreSQL row-lock behavior is authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'claim.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-claim-encryption-v1"},
            lookup_secret=b"nyay4-pure-claim-lookup-v1",
        )
    )
    try:
        observation = _run_claim_concurrency_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert _claim_observation_passes(observation)


def test_provider_ack_loss_reuses_exact_key_and_payload_once(tmp_path):
    """SQLite binds the provider contract; PostgreSQL relay remains authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'provider.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-provider-encryption-v1"},
            lookup_secret=b"nyay4-pure-provider-lookup-v1",
        )
    )
    try:
        observation = _run_provider_idempotency_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert _provider_observation_passes(observation)


def test_retry_lease_fencing_backoff_exhaustion_and_erasure(tmp_path):
    """SQLite binds state machines; PostgreSQL lease races are authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'retry.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-retry-encryption-v1"},
            lookup_secret=b"nyay4-pure-retry-lookup-v1",
        )
    )
    try:
        lease = _run_retry_lease_probe(engine)
        initial = _run_initial_exhaustion_probe(engine)
        observation = _compose_retry_observation(lease, initial, _maintenance())
    finally:
        override_keyring(None)
        engine.dispose()
    assert _retry_observation_passes(observation)


def test_all_nine_rate_dimensions_and_untrusted_forwarded_header(tmp_path):
    """SQLite binds fixed windows; PostgreSQL row serialization is authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'rate.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-rate-encryption-v1"},
            lookup_secret=b"nyay4-pure-rate-lookup-v1",
        )
    )
    try:
        rate = _run_rate_budget_probe(engine)
        observation = _compose_rate_observation(rate, _maintenance())
    finally:
        override_keyring(None)
        engine.dispose()
    assert _rate_observation_passes(observation)


def test_repeated_known_decoy_starts_cookie_reload_and_origin_are_uniform(tmp_path):
    """SQLite binds HTTP projection; PostgreSQL timing is authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'cookie.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-cookie-encryption-v1"},
            lookup_secret=b"nyay4-pure-cookie-lookup-v1",
        )
    )
    try:
        observation = _run_cookie_projection_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert observation["start_statuses"] == [202, 202]
    assert observation["start_signatures_equal"] is True
    assert observation["timing_samples_per_class"] == 40
    # SQLite binds the HTTP projection, not wall-clock scheduling.  The same
    # live measurement remains mandatory in the authoritative PostgreSQL gate;
    # deterministic boundary coverage below proves its estimator and limit.
    assert observation["timing_ratio_within_bound"] is (
        observation["timing_p95_ratio_milli"]
        <= observation["timing_bound_milli"]
    )
    assert observation["cookie_httponly"] is True
    assert observation["cookie_secure_nonlocal"] is True
    assert observation["cookie_samesite"] == "strict"
    assert observation["raw_flow_token_rows"] == 0
    assert observation["uuid_in_response"] is False
    assert observation["reload_status"] == 200
    assert observation["reload_metadata_equal"] is True
    assert observation["origin_missing_status"] == 403
    assert observation["origin_bad_status"] == 403
    assert observation["origin_good_status"] == 202


def test_known_unknown_suspended_ineligible_start_and_resend_are_conjunctive(
    tmp_path,
):
    """SQLite binds the HTTP contract; PostgreSQL remains authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'enumeration.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-enumeration-encryption-v1"},
            lookup_secret=b"nyay4-pure-enumeration-lookup-v1",
        )
    )
    try:
        observation = _run_preauth_enumeration_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()

    assert observation == _preauth_enumeration()
    assert _preauth_enumeration_observation_passes(observation)


def test_cookie_timing_ratio_oracle_enforces_the_exact_two_x_boundary():
    at_bound = _timing_ratio_observation([100] * 40, [200] * 40)
    above_bound = _timing_ratio_observation([100] * 40, [201] * 40)

    assert at_bound == {
        "timing_ratio_within_bound": True,
        "timing_samples_per_class": 40,
        "timing_p95_ratio_milli": 2000,
        "timing_bound_milli": 2000,
    }
    assert above_bound == {
        "timing_ratio_within_bound": False,
        "timing_samples_per_class": 40,
        "timing_p95_ratio_milli": 2010,
        "timing_bound_milli": 2000,
    }


def test_cookie_timing_p95_ignores_exactly_five_percent_not_persistent_skew():
    two_outliers = _timing_ratio_observation(
        [100] * 40, [100] * 38 + [1000] * 2
    )
    three_outliers = _timing_ratio_observation(
        [100] * 40, [100] * 37 + [1000] * 3
    )

    assert two_outliers["timing_p95_ratio_milli"] == 1000
    assert two_outliers["timing_ratio_within_bound"] is True
    assert three_outliers["timing_p95_ratio_milli"] == 10000
    assert three_outliers["timing_ratio_within_bound"] is False


def test_cookie_timing_samples_alternate_known_and_decoy_first():
    assert COOKIE_TIMING_SAMPLE_ORDER == tuple(
        ("known", "decoy") if index % 2 == 0 else ("decoy", "known")
        for index in range(40)
    )


@pytest.mark.parametrize(
    "known,decoy",
    (
        ([], []),
        ([100] * 39, [100] * 39),
        ([100] * 41, [100] * 41),
        ([100] * 40, [100] * 39),
        ([100] * 39 + [0], [100] * 40),
        ([100] * 39 + [-1], [100] * 40),
        ([100] * 39 + [True], [100] * 40),
    ),
)
def test_cookie_timing_ratio_oracle_rejects_incomplete_or_invalid_samples(
    known, decoy
):
    with pytest.raises(ValueError, match="timing samples"):
        _timing_ratio_observation(known, decoy)


def test_server_metadata_is_exactly_derived_from_persisted_authority(tmp_path):
    """SQLite binds the projection; PostgreSQL timing remains authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'metadata.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-metadata-encryption-v1"},
            lookup_secret=b"nyay4-pure-metadata-lookup-v1",
        )
    )
    try:
        observation = _run_metadata_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert _metadata_observation_passes(observation)


def test_postgresql_race_probes_remain_bound_to_real_service_entrypoints():
    """Pure source tripwire; execution belongs to the opt-in PG gate."""

    import inspect as pyinspect

    verify_source = pyinspect.getsource(_run_concurrent_verify_probe)
    resend_source = pyinspect.getsource(_run_concurrent_resend_probe)
    assert "otp_service.verify(" in verify_source
    assert "ThreadPoolExecutor" in verify_source
    assert "otp_service.resend(" in resend_source
    assert "ThreadPoolExecutor" in resend_source
    assert "statement_timeout" in verify_source
    assert "statement_timeout" in resend_source
    neutralized_source = pyinspect.getsource(_run_neutralized_concurrency_probe)
    assert "ThreadPoolExecutor" in neutralized_source
    assert "idempotency_conflict" in neutralized_source
    assert "sender.calls == 0" in neutralized_source


def test_shared_behavior_fixture_mobile_inventory_is_exactly_unique():
    assert _behavior_fixture_mobile_inventory_is_unique()
    assert len(BEHAVIOR_FIXTURE_MOBILES) == len(
        set(BEHAVIOR_FIXTURE_MOBILES.values())
    )
    duplicate = dict(BEHAVIOR_FIXTURE_MOBILES)
    duplicate["retry"] = duplicate["registration_finalizer"]
    assert not _behavior_fixture_mobile_inventory_is_unique(duplicate)


def test_claim_provider_retry_production_order_shares_one_database(tmp_path):
    """Catch cross-subprobe fixture collisions before PostgreSQL execution."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'shared-order.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-shared-order-encryption-v1"},
            lookup_secret=b"nyay4-pure-shared-order-lookup-v1",
        )
    )
    try:
        claim = _run_claim_concurrency_probe(engine)
        provider = _run_provider_idempotency_probe(engine)
        retry = _run_retry_lease_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert _claim_observation_passes(claim)
    assert _provider_observation_passes(provider)
    assert retry["lease_expired_reclaimed"] is True
    assert retry["stale_finalize_rejected"] is True
    assert retry["attempts_at_terminal"] == retry["configured_max_attempts"]
    assert retry["otp_ciphertext_erased"] is True
    assert retry["destination_ciphertext_erased"] is True


def test_full_behavior_phase_runs_in_production_order_on_exact_migrations(
    tmp_path, monkeypatch
):
    """Bind every behavior probe to one real 0018 -> 0019 SQLite graph.

    The authoritative verdict still belongs to PostgreSQL.  This regression
    catches cross-probe fixture collisions and replay-state interactions that
    isolated ``create_all`` tests cannot expose before the single native run.
    """

    from app.api.v1 import auth_student as endpoint

    original_constraint_name = endpoint.constraint_name
    monkeypatch.setattr(
        endpoint,
        "constraint_name",
        lambda exc: _sqlite_exact_ledger_constraint_adapter(
            exc, original_constraint_name
        ),
    )
    # This shared SQLite probe binds fixture order and HTTP projections.  Its
    # wall-clock timing verdict belongs to the separately required PostgreSQL
    # gate, so use a deterministic monotonic clock here instead of inheriting
    # host scheduler contention from the native aggregate suite.
    import time

    ticks = iter(range(10_000))
    monkeypatch.setattr(time, "perf_counter_ns", lambda: next(ticks))
    database_url = f"sqlite+pysqlite:///{tmp_path / 'full-behavior.db'}"
    observation = gate._run_behavior_probe(database_url)

    assert list(observation) == [
        "schema",
        "lockout",
        "verify",
        "resend",
        "failed_resend",
        "rate",
        "cookie",
        "enumeration",
        "metadata",
        "claim",
        "provider",
        "retry",
    ]
    evaluators = {
        "schema": _schema_observation_passes,
        "lockout": _lockout_observation_passes,
        "verify": _concurrent_verify_observation_passes,
        "resend": _resend_observation_passes,
        "failed_resend": _failed_resend_observation_passes,
        "rate": _rate_observation_passes,
        "cookie": _cookie_observation_passes,
        "enumeration": _preauth_enumeration_observation_passes,
        "metadata": _metadata_observation_passes,
        "claim": _claim_observation_passes,
        "provider": _provider_observation_passes,
        "retry": _retry_observation_passes,
    }
    assert {
        name: evaluator(observation[name])
        for name, evaluator in evaluators.items()
    } == {name: True for name in evaluators}
    assert observation["cookie"]["timing_p95_ratio_milli"] == 1000


@pytest.mark.parametrize(
    "message",
    (
        _SQLITE_LEDGER_KEY_UNIQUE_FAILURE + " ",
        "UNIQUE constraint failed: "
        "registration_idempotency_records.idempotency_key_hash,state",
        "UNIQUE constraint failed: student_registrations.mobile_hash",
        "CHECK constraint failed: ck_registration_idempotency_state",
        "database is locked",
    ),
)
def test_sqlite_constraint_adapter_rejects_every_nonexact_diagnostic(message):
    original = sqlite3.IntegrityError(message)
    original.sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT_UNIQUE
    original.sqlite_errorname = "SQLITE_CONSTRAINT_UNIQUE"
    exc = IntegrityError("INSERT", {}, original)
    assert _sqlite_exact_ledger_constraint_adapter(exc, lambda _exc: None) is None


def test_sqlite_constraint_adapter_maps_real_exact_ledger_unique_diagnostic():
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE registration_idempotency_records "
            "(idempotency_key_hash TEXT UNIQUE)"
        )
        connection.execute(
            "INSERT INTO registration_idempotency_records VALUES (?)",
            ("opaque-key-hash",),
        )
        with pytest.raises(sqlite3.IntegrityError) as caught:
            connection.execute(
                "INSERT INTO registration_idempotency_records VALUES (?)",
                ("opaque-key-hash",),
            )
    finally:
        connection.close()
    original = caught.value
    assert original.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE
    assert original.sqlite_errorname == "SQLITE_CONSTRAINT_UNIQUE"
    assert str(original) == _SQLITE_LEDGER_KEY_UNIQUE_FAILURE
    exc = IntegrityError("INSERT", {}, original)
    assert _sqlite_exact_ledger_constraint_adapter(exc, lambda _exc: None) == (
        "uq_registration_idempotency_records_idempotency_key_hash"
    )


@pytest.mark.parametrize(
    "errorcode,errorname",
    (
        (None, None),
        (sqlite3.SQLITE_CONSTRAINT, "SQLITE_CONSTRAINT"),
        (sqlite3.SQLITE_CONSTRAINT_UNIQUE, None),
        (None, "SQLITE_CONSTRAINT_UNIQUE"),
        (sqlite3.SQLITE_CONSTRAINT_UNIQUE, "SQLITE_CONSTRAINT_PRIMARYKEY"),
    ),
)
def test_sqlite_constraint_adapter_rejects_missing_or_wrong_error_metadata(
    errorcode, errorname
):
    original = sqlite3.IntegrityError(_SQLITE_LEDGER_KEY_UNIQUE_FAILURE)
    original.sqlite_errorcode = errorcode
    original.sqlite_errorname = errorname
    exc = IntegrityError("INSERT", {}, original)
    assert _sqlite_exact_ledger_constraint_adapter(exc, lambda _exc: None) is None


def test_sqlite_constraint_adapter_rejects_non_sqlite_exact_text():
    exc = IntegrityError(
        "INSERT", {}, RuntimeError(_SQLITE_LEDGER_KEY_UNIQUE_FAILURE)
    )
    assert _sqlite_exact_ledger_constraint_adapter(exc, lambda _exc: None) is None


def test_sqlite_constraint_adapter_preserves_database_reported_name():
    exc = IntegrityError(
        "INSERT", {}, sqlite3.IntegrityError(_SQLITE_LEDGER_KEY_UNIQUE_FAILURE)
    )
    assert _sqlite_exact_ledger_constraint_adapter(
        exc, lambda _exc: "database_reported_constraint"
    ) == "database_reported_constraint"


def test_start_and_resend_share_fractional_cooldown_and_window(tmp_path):
    """SQLite binds public alternation; PostgreSQL locking is authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'alternation.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-alternation-encryption-v1"},
            lookup_secret=b"nyay4-pure-alternation-lookup-v1",
        )
    )
    try:
        observation = _run_start_resend_alternation_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert observation == {
        "purposes": ["login", "recovery"],
        "fractional_retry_after_ceil": True,
        "exhausted_start_status": 429,
        "exhausted_start_zero_delivery": True,
        "real_decoy_equal": True,
    }


def test_neutralized_registration_key_is_bound_across_flow_expiry_and_removal(
    tmp_path,
):
    """SQLite exercises lifecycle precedence; PG races stay authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'neutralized.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-neutralized-encryption-v1"},
            lookup_secret=b"nyay4-pure-neutralized-lookup-v1",
        )
    )
    try:
        observation = _run_neutralized_registration_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert observation == {
        "key_request_bound": True,
        "exact_replay_stable": True,
        "live_mutations_conflict": True,
        "expired_mutations_uniform": True,
        "removed_mutations_uniform": True,
        "zero_provider": True,
        "zero_delta_after_terminal": True,
        "mutation_count": 9,
    }


def test_pending_registration_expiry_or_missing_flow_closes_relay_graph(tmp_path):
    """SQLite exercises lifecycle closure; PG finalizer races stay authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'pending-flow.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-pending-encryption-v1"},
            lookup_secret=b"nyay4-pure-pending-lookup-v1",
        )
    )
    try:
        observation = _run_pending_registration_lifecycle_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert observation == {
        "expired_mutations_uniform": True,
        "missing_mutations_uniform": True,
        "expired_graph_terminal": True,
        "missing_graph_terminal": True,
        "zero_provider": True,
        "zero_delta_after_terminal": True,
        "mutation_count_each": 9,
    }


def test_signup_verify_expired_and_consumed_states_are_non_enumerating(tmp_path):
    """SQLite exercises response symmetry; PG locking stays authoritative."""

    from app.core.crypto import KeyRing, override_keyring
    from tests import dbtemplate

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'verify-symmetry.db'}")
    dbtemplate.create_all(engine)
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-verify-encryption-v1"},
            lookup_secret=b"nyay4-pure-verify-lookup-v1",
        )
    )
    try:
        observation = _run_signup_verify_symmetry_probe(engine)
    finally:
        override_keyring(None)
        engine.dispose()
    assert observation == {
        "expired_status": 401,
        "expired_code": "otp_failed",
        "expired_values_equal": True,
        "expired_real_zero_delta": True,
        "expired_decoy_zero_delta": True,
        "consumed_status": 401,
        "consumed_code": "otp_failed",
        "consumed_values_equal": True,
        "consumed_real_zero_delta": True,
        "consumed_decoy_zero_delta": True,
        "provider_delta": 0,
    }


def test_scheduled_maintenance_entrypoint_purges_only_aged_security_state(
    tmp_path,
):
    """SQLite binds authentic 0018 grandfathering to the real worker seam."""

    from app.core.crypto import KeyRing, override_keyring
    from app.core.config import settings

    database_url = f"sqlite+pysqlite:///{tmp_path / 'maintenance.db'}"
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay4-pure-maintenance-encryption-v1"},
            lookup_secret=b"nyay4-pure-maintenance-lookup-v1",
        )
    )
    engine = None
    try:
        assert gate._run_alembic(
            database_url, "upgrade", gate.PREVIOUS_REVISION
        )["returncode"] == 0
        parent = create_engine(database_url)
        now = datetime.now(timezone.utc)
        old = now - timedelta(
            seconds=max(
                settings.otp_rate_bucket_retention_seconds,
                settings.otp_outbox_legacy_destination_retention_seconds,
            )
            + 60
        )
        try:
            legacy_outbox_ids = gate._seed_behavior_legacy_destinations(
                parent,
                aged_at=old,
                recent_at=now,
            )
        finally:
            parent.dispose()
        assert gate._run_alembic(database_url, "upgrade", gate.APPLICATION_HEAD)[
            "returncode"
        ] == 0
        engine = create_engine(database_url)
        observation = _run_maintenance_entrypoint_probe(
            engine,
            legacy_outbox_ids=legacy_outbox_ids,
        )
    finally:
        override_keyring(None)
        if engine is not None:
            engine.dispose()
    assert observation == _maintenance()


def test_named_provider_contract_rejects_token_reuse_with_changed_payload():
    from app.services.otp_sender import OtpSendError

    provider = _CertifiedGateProvider()
    provider.send_idempotent(
        "private-destination", "private-code", idempotency_token="opaque-token"
    )
    with pytest.raises(OtpSendError, match="idempotency conflict"):
        provider.send_idempotent(
            "different-destination",
            "private-code",
            idempotency_token="opaque-token",
        )
    assert provider.acceptance_count == 1


def test_provider_evaluator_never_overclaims_an_uncertified_real_provider():
    observation = _provider()
    observation["real_provider_exactly_once_claimed"] = True
    assert not _provider_observation_passes(observation)
    observation = _provider()
    observation["provider_contract_name"] = "unnamed"
    assert not _provider_observation_passes(observation)


def test_mutant_inventory_is_exact_and_every_seeded_mutant_must_be_killed():
    killed = {identifier: True for identifier in REQUIRED_MUTANT_IDS}
    assert len(REQUIRED_MUTANT_IDS) == len(set(REQUIRED_MUTANT_IDS))
    assert _seeded_mutants_are_killed(killed)
    for identifier in REQUIRED_MUTANT_IDS:
        survivor = dict(killed)
        survivor[identifier] = False
        assert not _seeded_mutants_are_killed(survivor), identifier
        missing = dict(killed)
        missing.pop(identifier)
        assert not _seeded_mutants_are_killed(missing), identifier
    extra = dict(killed)
    extra["UNREVIEWED-MUTANT"] = True
    assert not _seeded_mutants_are_killed(extra)


def test_every_seeded_vulnerable_outcome_is_killed_by_a_strict_oracle():
    observations = {
        "schema": _schema(),
        "lockout": _lockout(),
        "verify": _concurrent_verify(),
        "resend": _resend(),
        "failed_resend": _failed_resend(),
        "rate": _rate(),
        "cookie": _cookie(),
        "enumeration": _preauth_enumeration(),
        "claim": _claim(),
        "provider": _provider(),
        "retry": _retry(),
        "config": _config(),
        "harness": _harness(),
    }
    results = _seeded_mutant_results(observations)
    assert tuple(results) == REQUIRED_MUTANT_IDS
    assert _seeded_mutants_are_killed(results)
    incomplete = dict(observations)
    incomplete.pop("claim")
    assert not _seeded_mutants_are_killed(_seeded_mutant_results(incomplete))


def _privacy_projection_inputs() -> dict[str, object]:
    behavior = {
        "schema": _schema(),
        "lockout": _lockout(),
        "verify": _concurrent_verify(),
        "resend": _resend(),
        "failed_resend": _failed_resend(),
        "rate": _rate(),
        "cookie": _cookie(),
        "enumeration": _preauth_enumeration(),
        "metadata": _metadata(),
        "claim": _claim(),
        "provider": _provider(),
        "retry": _retry(),
    }
    return {
        "runtime": _runtime(),
        "migration": _migration(),
        "populated": _populated_migration(),
        "behavior": behavior,
        "config": _config(),
        "harness": _harness(),
    }


def _positive_privacy_projection() -> dict[str, object]:
    return _privacy_observation_projection(**_privacy_projection_inputs())


def test_private_observation_projection_renames_only_safe_aggregate_labels():
    projected = _positive_privacy_projection()
    assert _privacy_findings(projected) == []
    assert "cookie" not in projected
    assert projected["cookie_contract"] == _cookie()
    assert projected["failed_resend"] == {
        **{key: value for key, value in _failed_resend().items() if key != "code"},
        "typed_outcome": "otp_delivery_failed",
    }


@pytest.mark.parametrize(
    "value",
    (
        "opaque_browser_capability_123456789012345678901234567890",
        "193746",
        "9876543210",
        "198.51.100.23",
        "https://provider.invalid/secret",
        "a" * 64,
        "v1:VGhpcy1pcy1ub3QtcmVhbC1jaXBoZXJ0ZXh0",
    ),
)
def test_private_projection_rejects_secret_in_allowlisted_cookie_section(value):
    inputs = _privacy_projection_inputs()
    behavior = deepcopy(inputs["behavior"])
    behavior["cookie"]["raw_cookie_mutant"] = value
    inputs["behavior"] = behavior
    with pytest.raises(gate.ProductGateFailure):
        _privacy_observation_projection(**inputs)


def test_private_projection_rejects_direct_raw_cookie_section_value():
    inputs = _privacy_projection_inputs()
    behavior = deepcopy(inputs["behavior"])
    behavior["cookie"] = "opaque_browser_capability_123456789012345678901234567890"
    inputs["behavior"] = behavior
    with pytest.raises(gate.ProductGateFailure):
        _privacy_observation_projection(**inputs)


@pytest.mark.parametrize("field", ("cookie", "flow_token", "code"))
def test_private_projection_rejects_nested_secret_in_cookie_safe_field(field):
    inputs = _privacy_projection_inputs()
    behavior = deepcopy(inputs["behavior"])
    behavior["cookie"]["reload_metadata_equal"] = {
        field: "opaque_browser_capability_123456789012345678901234567890"
    }
    inputs["behavior"] = behavior
    with pytest.raises(gate.ProductGateFailure):
        _privacy_observation_projection(**inputs)


def test_private_projection_rejects_secret_replacing_cookie_safe_scalar():
    inputs = _privacy_projection_inputs()
    behavior = deepcopy(inputs["behavior"])
    behavior["cookie"]["origin_missing_code"] = (
        "https://provider.invalid/private-capability"
    )
    inputs["behavior"] = behavior
    with pytest.raises(gate.ProductGateFailure):
        _privacy_observation_projection(**inputs)


@pytest.mark.parametrize(
    "value",
    (
        "opaque_flow_capability_123456789012345678901234567890",
        "193746",
        "9876543210",
        "198.51.100.23",
        "https://provider.invalid/secret",
        "a" * 64,
        "v1:VGhpcy1pcy1ub3QtcmVhbC1jaXBoZXJ0ZXh0",
    ),
)
def test_private_projection_rejects_secret_in_allowlisted_outcome_section(value):
    inputs = _privacy_projection_inputs()
    behavior = deepcopy(inputs["behavior"])
    behavior["failed_resend"]["code"] = value
    inputs["behavior"] = behavior
    with pytest.raises(gate.ProductGateFailure):
        _privacy_observation_projection(**inputs)


@pytest.mark.parametrize(
    "field,value",
    (
        ("cookie", "opaque-browser-capability"),
        ("flow_token", "opaque-flow-capability"),
        ("code", "bounded-looking-value"),
        ("mobile", "must-not-be-copied"),
    ),
)
def test_private_observation_projection_still_rejects_secret_keys(field, value):
    projected = _positive_privacy_projection()
    projected["seeded_secret_mutant"] = {field: value}
    findings = _privacy_findings(projected)
    assert findings
    assert all(value not in finding for finding in findings)


@pytest.mark.parametrize(
    "value,label",
    (
        ("193746", "otp"),
        ("9876543210", "mobile"),
        ("198.51.100.23", "ip"),
        ("a" * 64, "hash64"),
    ),
)
def test_private_observation_projection_still_rejects_secret_shapes(value, label):
    projected = _positive_privacy_projection()
    projected["seeded_shape_mutant"] = value
    assert f"pattern:{label}" in _privacy_findings(projected)


@pytest.mark.parametrize(
    "field",
    (
        "database_url",
        "scratch_database",
        "mobile",
        "ip_hash",
        "otp",
        "flow_token",
        "provider_idempotency_key",
        "claim_token",
        "ciphertext",
        "registration_id",
        "payload",
        "response_body",
        "exception",
    ),
)
def test_privacy_scan_rejects_forbidden_evidence_keys_without_value_echo(field):
    findings = _privacy_findings({"safe": {field: "must-not-be-copied"}})
    assert findings
    assert all("must-not-be-copied" not in finding for finding in findings)


@pytest.mark.parametrize(
    "value,label",
    (
        ("d4d680e7-0218-4ee2-8717-bf46cfa915f3", "uuid"),
        ("person@example.invalid", "email"),
        ("9876543210", "mobile"),
        ("193746", "otp"),
        ("198.51.100.23", "ip"),
        ("postgresql://qa:secret@localhost/db", "url"),
        ("a" * 64, "hash64"),
        ("v1:VGhpcy1pcy1ub3QtcmVhbC1jaXBoZXJ0ZXh0", "ciphertext"),
    ),
)
def test_privacy_scan_rejects_secret_shapes_without_echo(value, label):
    findings = _privacy_findings({"aggregate_note": value})
    assert f"pattern:{label}" in findings
    assert all(value not in finding for finding in findings)


def test_aggregate_pass_report_is_privacy_clean():
    report = {
        "gate": "nyay4_postgres_otp",
        "status": "PASS",
        "executed": True,
        "assertions": 17,
        "mutants_killed": len(REQUIRED_MUTANT_IDS),
        "scratch": {"created": 3, "removed": 3, "failed": 0},
        "postgres_major": 16,
        "pgvector_present": True,
    }
    assert _privacy_findings(report) == []


def test_safe_response_signature_retains_shape_not_sensitive_values():
    body = {
        "detail": {
            "code": "locked",
            "field": "otp",
            "secret": "must-not-survive",
        },
        "retry_after": 30,
    }
    signature = _safe_response_signature(423, body)
    assert signature == {
        "status": 423,
        "top_level_keys": ["detail", "retry_after"],
        "detail_keys": ["code", "field", "secret"],
        "code_present": True,
    }
    assert "must-not-survive" not in repr(signature)
    assert "locked" not in repr(signature)


def test_scratch_manager_removes_every_created_database_and_matches_inventory(
    monkeypatch,
):
    existing: set[str] = set()

    def inventory(_base):
        return set(existing)

    def create(_base, name):
        existing.add(name)
        return "postgresql+psycopg://qa:secret@localhost/scratch"

    def drop(_base, name):
        existing.discard(name)

    monkeypatch.setattr(gate, "_scratch_database_inventory", inventory)
    monkeypatch.setattr(gate, "_create_scratch", create)
    monkeypatch.setattr(gate, "_drop_scratch", drop)
    manager = _ScratchDatabaseManager(make_url("postgresql://localhost/postgres"))
    for purpose in ("migration_lifecycle", "migration_populated", "behavior"):
        assert manager.run(purpose, lambda _url: True) is True
    assert manager.summary() == {
        "created": 3,
        "removed": 3,
        "failed": 0,
        "purposes": ["migration_lifecycle", "migration_populated", "behavior"],
        "inventory_match": True,
        "all_created_removed": True,
    }


def test_scratch_manager_cleanup_failure_is_part_of_verdict(monkeypatch):
    existing: set[str] = set()

    def inventory(_base):
        return set(existing)

    def create(_base, name):
        existing.add(name)
        return "postgresql+psycopg://qa:secret@localhost/scratch"

    monkeypatch.setattr(gate, "_scratch_database_inventory", inventory)
    monkeypatch.setattr(gate, "_create_scratch", create)
    monkeypatch.setattr(gate, "_drop_scratch", lambda _base, _name: None)
    manager = _ScratchDatabaseManager(make_url("postgresql://localhost/postgres"))
    with pytest.raises(ScratchCleanupFailure):
        manager.run("behavior", lambda _url: True)
    summary = manager.summary()
    assert summary["failed"] == 1
    assert summary["all_created_removed"] is False


def test_main_without_both_opt_ins_exits_78_before_database_or_gate(
    monkeypatch, capsys
):
    monkeypatch.delenv(gate.OPT_IN_ENV, raising=False)
    monkeypatch.setattr(
        gate,
        "run_gate",
        lambda _base: pytest.fail("database gate must not run without opt-in"),
    )
    assert gate.main([]) == gate.BLOCKED_EXIT
    report = gate.json.loads(capsys.readouterr().out)
    assert report == {
        "executed": False,
        "gate": "nyay4_postgres_otp",
        "reason": "explicit execution opt-in is required",
        "status": "BLOCKED",
    }


def test_execute_flag_without_environment_opt_in_still_exits_78(monkeypatch):
    monkeypatch.delenv(gate.OPT_IN_ENV, raising=False)
    monkeypatch.setattr(
        gate,
        "run_gate",
        lambda _base: pytest.fail("database gate must not run without opt-in"),
    )
    assert gate.main(["--execute"]) == gate.BLOCKED_EXIT


def test_environment_opt_in_without_execute_flag_still_exits_78(monkeypatch):
    monkeypatch.setenv(gate.OPT_IN_ENV, "1")
    monkeypatch.setattr(
        gate,
        "run_gate",
        lambda _base: pytest.fail("database gate must not run without opt-in"),
    )
    assert gate.main([]) == gate.BLOCKED_EXIT


def test_both_opt_ins_without_explicit_database_url_exit_78(monkeypatch):
    monkeypatch.setenv(gate.OPT_IN_ENV, "1")
    monkeypatch.delenv("NYAY4_POSTGRES_ADMIN_URL", raising=False)
    monkeypatch.setattr(
        gate,
        "run_gate",
        lambda _base: pytest.fail("database gate must not run without a URL"),
    )
    assert gate.main(["--execute"]) == gate.BLOCKED_EXIT


def test_both_opt_ins_with_remote_database_url_exit_78_before_gate(monkeypatch):
    monkeypatch.setenv(gate.OPT_IN_ENV, "1")
    monkeypatch.setattr(
        gate,
        "run_gate",
        lambda _base: pytest.fail("database gate must not run against remote DB"),
    )
    assert (
        gate.main(
            [
                "--execute",
                "--database-url",
                "postgresql+psycopg://qa:secret@example.invalid/postgres",
            ]
        )
        == gate.BLOCKED_EXIT
    )
