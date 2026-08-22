"""Fail-closed policy tests for the NYAY-19 Alembic release guard."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

from alembic import command as alembic_command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, text

import app.db.migration_release_guard as release_guard
from app.db.migration_release_guard import (
    AGGREGATE_KEYS,
    APPROVAL_WINDOW_END_ENV,
    AUTHORITY_TABLES,
    CHANGE_REFERENCE_ENV,
    FORCE_APPROVAL_ENV,
    FREEZE_ACK_ENV,
    IRREVERSIBLE_FREEZE_ACK,
    ISOLATED_EXECUTION_ENV,
    MigrationApprovalError,
    PARENT_REVISION,
    PREFLIGHT_PATH_ENV,
    PREFLIGHT_SHA_ENV,
    REPORT_KEYS,
    RuntimeMigrationIntent,
    TARGET_SOURCE_SHA256,
    TARGET_REVISION,
    enforce_nyay19_migration_release_guard,
)


def _config(command_name: str, *, revision: str | None = None):
    options = {
        "cmd": (getattr(alembic_command, command_name), [], []),
        "sql": False,
        "tag": None,
    }
    if revision is not None:
        options["revision"] = revision
    return SimpleNamespace(cmd_opts=SimpleNamespace(**options))


def _unknown_config():
    def unknown():
        return None

    return SimpleNamespace(
        cmd_opts=SimpleNamespace(
            cmd=(unknown, [], []),
            revision=TARGET_REVISION,
            sql=False,
            tag=None,
        )
    )


def _upgrade_intent(revision: str = TARGET_REVISION) -> RuntimeMigrationIntent:
    return RuntimeMigrationIntent(
        operation="upgrade",
        destination_revision=revision,
        as_sql=False,
        tag=None,
        dont_mutate=False,
    )


def _current_intent() -> RuntimeMigrationIntent:
    return RuntimeMigrationIntent(
        operation="current",
        destination_revision=None,
        as_sql=False,
        tag=None,
        dont_mutate=True,
    )


def _connection(url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(url)
    connection = engine.connect()
    connection.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
    connection.commit()
    return engine, connection


def _isolated_postgres_target(database_url: str):
    from sqlalchemy.engine import make_url

    url = make_url(database_url)

    class Result:
        @staticmethod
        def one():
            return url.database, "127.0.0.1", 5432

    return SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(url=url),
        execute=lambda _statement: Result(),
    )


def _set_revision(connection, revision: str) -> None:
    connection.execute(text("DELETE FROM alembic_version"))
    connection.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
        {"revision": revision},
    )
    connection.commit()


def _report() -> dict[str, object]:
    report: dict[str, object] = {
        "verdict": "PASS",
        "code": "migration_ready",
        "parent_revision": PARENT_REVISION,
        "target_revision": TARGET_REVISION,
        "postgres_major": 16,
        "pgvector_present": True,
        "change_reference": "NYAY-19-RELEASE-001",
        "approval_window_ends_at": "2026-08-22T12:00:00Z",
        "preflight_observed_at": "2026-08-22T11:00:00Z",
        "target_source_sha256": TARGET_SOURCE_SHA256,
        "target_fingerprint": "b" * 64,
        "authority_state_digest": "c" * 64,
        "aggregates": {name: 0 for name in AGGREGATE_KEYS},
    }
    report["state_fingerprint"] = release_guard.state_fingerprint(report)
    return report


def _write_report(path: Path, report: dict[str, object]) -> str:
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    payload += b"\n"
    path.write_bytes(payload)
    path.chmod(0o600)
    return hashlib.sha256(payload).hexdigest()


def _authority(path: Path, digest: str) -> dict[str, str]:
    return {
        PREFLIGHT_PATH_ENV: str(path),
        PREFLIGHT_SHA_ENV: digest,
        CHANGE_REFERENCE_ENV: "NYAY-19-RELEASE-001",
        APPROVAL_WINDOW_END_ENV: "2026-08-22T12:00:00Z",
        FREEZE_ACK_ENV: IRREVERSIBLE_FREEZE_ACK,
        FORCE_APPROVAL_ENV: "1",
    }


class _CatalogRows:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


def _canonical_authority_catalog():
    relations = [
        {
            "table_name": table,
            "relation_kind": "r",
            "persistence": "p",
            "is_partition": False,
            "row_security": False,
            "force_row_security": False,
        }
        for table in sorted(AUTHORITY_TABLES)
    ]
    triggers = [
        {
            "table_name": "audit_events",
            "trigger_name": "trg_audit_events_append_only",
            "trigger_enabled": "O",
            "trigger_type": 27,
            "argument_count": 0,
            "no_column_filter": True,
            "no_when_clause": True,
            "not_constraint": True,
            "not_deferrable": True,
            "not_initially_deferred": True,
            "not_child_trigger": True,
            "no_transition_tables": True,
            "arguments_hex": "",
            "function_schema": "public",
            "function_name": "legalsaathi_audit_append_only",
            "function_kind": "f",
            "language_name": "plpgsql",
            "returns_trigger": True,
            "function_arguments": "",
            "function_source": (
                "BEGIN RAISE EXCEPTION "
                "'audit_events rows are append-only (% blocked)', TG_OP; END;"
            ),
            "function_volatile": "v",
            "function_parallel": "u",
            "security_definer": False,
            "leakproof": False,
            "function_strict": False,
            "function_config": None,
            "same_owner": True,
        }
    ]
    return relations, [], [], triggers


class _AuthorityCatalogConnection:
    def __init__(self, *, relations=None, policies=None, rules=None, triggers=None):
        canonical = _canonical_authority_catalog()
        self.relations = canonical[0] if relations is None else relations
        self.policies = canonical[1] if policies is None else policies
        self.rules = canonical[2] if rules is None else rules
        self.triggers = canonical[3] if triggers is None else triggers

    def execute(self, statement):
        sql = str(statement)
        if "pg_catalog.pg_policy" in sql:
            return _CatalogRows(self.policies)
        if "pg_catalog.pg_rewrite" in sql:
            return _CatalogRows(self.rules)
        if "pg_catalog.pg_trigger" in sql:
            return _CatalogRows(self.triggers)
        if "pg_catalog.pg_class" in sql:
            return _CatalogRows(self.relations)
        raise AssertionError(sql)


def test_target_fingerprint_binds_cluster_database_schema_and_role_without_leaking():
    from sqlalchemy.engine import make_url

    class TargetConnection:
        engine = SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://migration-owner:secret@"
                "db-primary.example:5432/private-production-name"
            )
        )

        @staticmethod
        def scalar(_statement):
            return "cluster-system-identifier-01"

        @staticmethod
        def execute(_statement):
            return [
                (
                    4242,
                    "private-production-name",
                    "migration-owner",
                    "10.20.30.40",
                    5432,
                    datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
                )
            ]

    identity = {
        "cluster_system_identifier": "cluster-system-identifier-01",
        "database_oid": 4242,
        "database_name": "private-production-name",
        "database_schema": "public",
        "database_user": "migration-owner",
        "configured_host": "db-primary.example",
        "configured_port": 5432,
        "live_server_address": "10.20.30.40",
        "live_server_port": 5432,
        "postmaster_started_at": "2026-08-22T10:00:00.000000Z",
    }
    expected = hashlib.sha256(
        json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    fingerprint = release_guard._target_fingerprint(TargetConnection())
    assert fingerprint == expected
    assert "cluster" not in fingerprint
    assert "private-production-name" not in fingerprint
    assert "migration-owner" not in fingerprint
    assert "db-primary.example" not in fingerprint
    assert "10.20.30.40" not in fingerprint
    assert "2026-08-22" not in fingerprint
    assert len(AGGREGATE_KEYS) == 7


def test_target_fingerprint_distinguishes_cloned_state_at_another_endpoint():
    from sqlalchemy.engine import make_url

    class TargetConnection:
        def __init__(self, configured_host, live_address):
            self.engine = SimpleNamespace(
                url=make_url(
                    "postgresql+psycopg://migration-owner:secret@"
                    f"{configured_host}:5432/private-production-name"
                )
            )
            self.live_address = live_address

        @staticmethod
        def scalar(_statement):
            return "same-cloned-system-identifier"

        def execute(self, _statement):
            return [
                (
                    4242,
                    "private-production-name",
                    "migration-owner",
                    self.live_address,
                    5432,
                    datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
                )
            ]

    primary = release_guard._target_fingerprint(
        TargetConnection("db-primary.example", "10.20.30.40")
    )
    replica = release_guard._target_fingerprint(
        TargetConnection("db-replica.example", "10.20.30.41")
    )
    assert primary != replica


def test_target_fingerprint_distinguishes_restart_or_clone_at_same_endpoint():
    from sqlalchemy.engine import make_url

    class TargetConnection:
        engine = SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://migration-owner:secret@"
                "db-primary.example:5432/private-production-name"
            )
        )

        def __init__(self, postmaster_started_at):
            self.postmaster_started_at = postmaster_started_at

        @staticmethod
        def scalar(_statement):
            return "same-cloned-system-identifier"

        def execute(self, _statement):
            return [
                (
                    4242,
                    "private-production-name",
                    "migration-owner",
                    "10.20.30.40",
                    5432,
                    self.postmaster_started_at,
                )
            ]

    original = release_guard._target_fingerprint(
        TargetConnection(datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc))
    )
    restarted = release_guard._target_fingerprint(
        TargetConnection(datetime(2026, 8, 22, 10, 1, tzinfo=timezone.utc))
    )
    assert original != restarted


@pytest.mark.parametrize("configured_host", ("127.0.0.1", "[::1]"))
def test_target_fingerprint_accepts_loopback_nat_and_mapped_client_port(
    configured_host,
):
    from sqlalchemy.engine import make_url

    class TargetConnection:
        engine = SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://migration-owner:secret@"
                f"{configured_host}:55469/private-production-name"
            )
        )

        @staticmethod
        def scalar(_statement):
            return "cluster-system-identifier-01"

        @staticmethod
        def execute(_statement):
            return [
                (
                    4242,
                    "private-production-name",
                    "migration-owner",
                    "172.17.0.2",
                    5432,
                    datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
                )
            ]

    assert len(release_guard._target_fingerprint(TargetConnection())) == 64


def test_configured_endpoint_is_canonical_and_defaults_postgres_port():
    from sqlalchemy.engine import make_url

    connection = SimpleNamespace(
        engine=SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://user@DB-PRIMARY.Example./database"
                "?sslmode=require"
            )
        )
    )
    assert release_guard._normalized_configured_endpoint(connection) == (
        "db-primary.example",
        5432,
        "database",
    )


def test_server_address_queries_strip_cidr_before_ipaddress_parsing():
    sources = (
        inspect.getsource(release_guard._is_explicit_isolated_target),
        inspect.getsource(release_guard._target_fingerprint),
    )
    for source in sources:
        assert "pg_catalog.host(pg_catalog.inet_server_addr())::text" in source
        assert "pg_catalog.inet_server_addr()::text" not in source


@pytest.mark.parametrize(
    ("url", "live_address", "live_port"),
    [
        ("postgresql+psycopg:///database", "10.20.30.40", 5432),
        (
            "postgresql+psycopg://user@db.example:5432/database"
            "?host=elsewhere.example",
            "10.20.30.40",
            5432,
        ),
        (
            "postgresql+psycopg://user@db.example:5432/database",
            None,
            5432,
        ),
        (
            "postgresql+psycopg://user@db.example:5432/database",
            "10.20.30.40",
            "5432",
        ),
    ],
)
def test_target_fingerprint_rejects_missing_unsafe_or_mismatched_endpoint(
    url,
    live_address,
    live_port,
):
    from sqlalchemy.engine import make_url

    class TargetConnection:
        engine = SimpleNamespace(url=make_url(url))

        @staticmethod
        def scalar(_statement):
            return "cluster-system-identifier-01"

        @staticmethod
        def execute(_statement):
            return [
                (
                    4242,
                    "database",
                    "migration-owner",
                    live_address,
                    live_port,
                    datetime(2026, 8, 22, 10, 0, tzinfo=timezone.utc),
                )
            ]

    with pytest.raises(RuntimeError, match="target identity rejected"):
        release_guard._target_fingerprint(TargetConnection())


@pytest.mark.parametrize(
    "postmaster_started_at",
    (None, "2026-08-22T10:00:00Z", datetime(2026, 8, 22, 10, 0)),
)
def test_target_fingerprint_rejects_noncanonical_postmaster_identity(
    postmaster_started_at,
):
    from sqlalchemy.engine import make_url

    class TargetConnection:
        engine = SimpleNamespace(
            url=make_url("postgresql+psycopg://user@db.example:5432/database")
        )

        @staticmethod
        def scalar(_statement):
            return "cluster-system-identifier-01"

        @staticmethod
        def execute(_statement):
            return [
                (
                    4242,
                    "database",
                    "migration-owner",
                    "10.20.30.40",
                    5432,
                    postmaster_started_at,
                )
            ]

    with pytest.raises(RuntimeError, match="target identity rejected"):
        release_guard._target_fingerprint(TargetConnection())


def test_authority_digest_covers_every_locked_row_and_count_preserving_changes():
    special = (
        '{"bytes":"\\\\x00ff","json":{"a":null,"z":[2,1]},'
        '"seen":"2026-08-21T01:02:03+00:00"}'
    )
    rows = {
        table: [(f"00000000-0000-0000-0000-{index:012d}", special)]
        for index, table in enumerate(AUTHORITY_TABLES, start=1)
    }

    class RowConnection:
        def __init__(self, values):
            self.values = values
            self.queries = []
            self.statement_options = []

        def execution_options(self, **_options):
            raise AssertionError("digest must not mutate connection options")

        def execute(self, statement):
            sql = str(statement)
            self.queries.append(sql)
            self.statement_options.append(dict(statement.get_execution_options()))
            table = next(
                name for name in AUTHORITY_TABLES if f"public.{name}" in sql
            )
            return self.values[table]

    baseline_connection = RowConnection(rows)
    baseline = release_guard._authority_state_digest(baseline_connection)
    assert len(baseline) == 64
    assert special not in baseline
    assert len(baseline_connection.queries) == len(AUTHORITY_TABLES) == 7
    for table, query, options in zip(
        AUTHORITY_TABLES,
        baseline_connection.queries,
        baseline_connection.statement_options,
    ):
        assert f"public.{table}" in query
        assert "to_jsonb(row_value)::text" in query
        assert "ORDER BY row_value.id" in query
        assert options == {"stream_results": True, "max_row_buffer": 256}

    changed_rows = {name: list(value) for name, value in rows.items()}
    stable_id, _canonical = changed_rows[AUTHORITY_TABLES[-1]][0]
    changed_rows[AUTHORITY_TABLES[-1]][0] = (
        stable_id,
        '{"bytes":"\\\\x00fe","json":{"a":null,"z":[2,1]},'
        '"seen":"2026-08-21T01:02:03+00:00"}',
    )
    changed = release_guard._authority_state_digest(RowConnection(changed_rows))
    assert changed != baseline
    assert release_guard._authority_state_digest(RowConnection(rows)) == baseline


def test_authority_catalog_accepts_only_the_canonical_seven_table_surface():
    release_guard._validate_authority_catalog(_AuthorityCatalogConnection())


@pytest.mark.parametrize(
    "mutate",
    (
        lambda catalog: catalog[0][0].update(row_security=True),
        lambda catalog: catalog[0][1].update(force_row_security=True),
        lambda catalog: catalog[1].append(
            {
                "table_name": "users",
                "policy_name": "suppress_privacy_targets",
            }
        ),
        lambda catalog: catalog[2].append(
            {
                "table_name": "student_registrations",
                "rule_name": "suppress_privacy_updates",
            }
        ),
        lambda catalog: catalog[3].append(
            {
                **catalog[3][0],
                "table_name": "auth_sessions",
                "trigger_name": "suppress_privacy_revocation",
            }
        ),
        lambda catalog: catalog[3][0].update(trigger_enabled="D"),
        lambda catalog: catalog[3][0].update(no_when_clause=False),
        lambda catalog: catalog[3][0].update(function_source="BEGIN RETURN NULL; END;"),
    ),
    ids=(
        "rls",
        "forced-rls",
        "policy",
        "rewrite-rule",
        "suppression-trigger",
        "disabled-audit-trigger",
        "conditional-audit-trigger",
        "altered-audit-function",
    ),
)
def test_authority_catalog_rejects_rls_policy_rule_and_trigger_mutants(mutate):
    relations, policies, rules, triggers = _canonical_authority_catalog()
    catalog = [
        [dict(row) for row in relations],
        [dict(row) for row in policies],
        [dict(row) for row in rules],
        [dict(row) for row in triggers],
    ]
    mutate(catalog)
    with pytest.raises(RuntimeError, match="authority catalog rejected"):
        release_guard._validate_authority_catalog(
            _AuthorityCatalogConnection(
                relations=catalog[0],
                policies=catalog[1],
                rules=catalog[2],
                triggers=catalog[3],
            )
        )


def test_locked_parent_preflight_validates_catalog_before_data_or_digest():
    source = inspect.getsource(release_guard.locked_parent_report)
    catalog = source.index("_validate_authority_catalog(connection)")
    data = source.index("module._upgrade_data_preflight(connection)")
    digest = source.index('"authority_state_digest": _authority_state_digest')
    assert catalog < data < digest


def test_statement_streaming_options_leave_real_connection_state_unchanged():
    engine, connection = _connection()
    try:
        before = dict(connection.get_execution_options())
        statement = text("SELECT 1").execution_options(
            stream_results=True,
            max_row_buffer=256,
        )
        assert dict(statement.get_execution_options()) == {
            "stream_results": True,
            "max_row_buffer": 256,
        }
        assert connection.execute(statement).scalar_one() == 1
        assert dict(connection.get_execution_options()) == before
    finally:
        connection.close()
        engine.dispose()


def test_public_authority_sets_deterministic_session_and_rejects_shadow_schema():
    class PublicConnection:
        dialect = SimpleNamespace(
            name="postgresql",
            default_schema_name="public",
        )

        def __init__(self):
            self.settings = []

        def exec_driver_sql(self, sql):
            self.settings.append(sql)

        @staticmethod
        def scalar(statement):
            sql = str(statement)
            if "current_schemas" in sql:
                return ["pg_catalog", "public"]
            if "CURRENT_SCHEMA" in sql:
                return "public"
            if "to_regnamespace" in sql:
                return 2200
            raise AssertionError(sql)

    connection = PublicConnection()
    release_guard._establish_public_authority(connection)
    assert connection.settings[0] == (
        "SET LOCAL search_path = pg_catalog, public"
    )
    assert "SET LOCAL TIME ZONE 'UTC'" in connection.settings
    assert "SET LOCAL bytea_output = 'hex'" in connection.settings
    assert connection.settings[-1] == "SET LOCAL search_path = public"

    connection.dialect.default_schema_name = "attacker"
    with pytest.raises(RuntimeError, match="schema authority rejected"):
        release_guard._establish_public_authority(connection)


def test_authoritative_preparation_locks_public_version_table(monkeypatch):
    events = []
    monkeypatch.setattr(
        release_guard,
        "_establish_public_authority",
        lambda _connection: events.append("schema"),
    )
    monkeypatch.setattr(
        release_guard,
        "_validate_platform",
        lambda _connection: events.append("platform"),
    )
    connection = SimpleNamespace(
        exec_driver_sql=lambda sql: events.append(sql),
    )
    release_guard._prepare_authoritative_transaction(connection)
    assert events == [
        "schema",
        "platform",
        "LOCK TABLE public.alembic_version "
        "IN SHARE ROW EXCLUSIVE MODE NOWAIT",
    ]


@pytest.mark.parametrize(
    ("case", "failure_index"),
    [
        ("invalid_evidence", 0),
        ("missing_job", 1),
        ("duplicate_job", 2),
        ("wrong_role", 3),
        ("missing_registration", 4),
        ("duplicate_registration", 5),
        ("invalid_registration", 6),
    ],
)
def test_read_only_legacy_deletion_validator_rejects_every_ambiguous_target(
    case,
    failure_index,
):
    class ValidationConnection:
        def __init__(self):
            self.index = 0
            self.queries = []

        def scalar(self, statement):
            self.queries.append(str(statement))
            result = 1 if self.index == failure_index else None
            self.index += 1
            return result

    connection = ValidationConnection()
    with pytest.raises(RuntimeError, match="legacy deletion authority rejected"):
        release_guard._validate_legacy_deletion_authority(connection)
    assert connection.queries
    assert all("public." in query for query in connection.queries)
    if failure_index == 0:
        assert "dsr.status IS NULL" in connection.queries[0]
        assert "dsr.status <> 'cancelled'" in connection.queries[0]
    assert case


def test_authenticated_loader_executes_verified_source_not_cached_bytecode(
    tmp_path,
):
    source = tmp_path / "0020_example.py"
    source.write_bytes(b"VALUE = 'verified-source'\n")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    cache = Path(str(source) + "c")
    cache.write_bytes(b"malicious-cache-must-never-be-read")

    module = release_guard._load_authenticated_migration_module(
        "verified_migration",
        source,
        expected,
    )
    assert module.VALUE == "verified-source"

    source.write_bytes(b"VALUE = 'source-drifted'\n")
    with pytest.raises(MigrationApprovalError, match="source authority rejected"):
        release_guard._load_authenticated_migration_module(
            "rejected_migration",
            source,
            expected,
        )


def test_installed_alembic_loader_authenticates_real_frozen_source():
    from alembic.util import pyfiles

    original = pyfiles.load_module_py
    restore = release_guard.install_authenticated_migration_loader()
    try:
        module = pyfiles.load_python_file(
            release_guard.VERSIONS_PATH,
            release_guard.TARGET_SOURCE_PATH.name,
        )
        assert module.revision == TARGET_REVISION
        assert module.down_revision == PARENT_REVISION
        with pytest.raises(MigrationApprovalError, match="source authority rejected"):
            pyfiles.load_module_py(
                "cached_target",
                Path(str(release_guard.TARGET_SOURCE_PATH) + "c"),
            )
    finally:
        restore()
    assert pyfiles.load_module_py is original


def test_full_source_authority_rejects_any_historical_revision_drift(monkeypatch):
    original = release_guard._stable_file_sha256

    def drift_one(path):
        if path.name == "0019_otp_security_authority.py":
            return "0" * 64
        return original(path)

    monkeypatch.setattr(release_guard, "_stable_file_sha256", drift_one)
    assert release_guard.source_authority_is_valid() is False


def test_real_alembic_upgrade_context_yields_independent_exact_runtime_intent(
    monkeypatch,
):
    observed = []

    def inspect_context(_script):
        from alembic import context

        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            with engine.connect() as connection:
                context.configure(connection=connection)
                observed.append(release_guard.runtime_migration_intent(context))
        finally:
            engine.dispose()

    monkeypatch.setattr(ScriptDirectory, "run_env", inspect_context)
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[1] / "app/db/migrations"),
    )
    alembic_command.upgrade(config, TARGET_REVISION)
    assert observed == [_upgrade_intent()]


def test_known_read_only_cli_command_does_not_require_mutation_approval():
    engine, connection = _connection()
    try:
        enforce_nyay19_migration_release_guard(
            _config("current"),
            connection,
            environment="production",
            environ={},
            runtime_intent=_current_intent(),
        )
    finally:
        connection.close()
        engine.dispose()


def test_local_sqlite_upgrade_is_an_explicit_nonproduction_boundary():
    engine, connection = _connection()
    try:
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            connection,
            environment="testing",
            environ={},
        )
    finally:
        connection.close()
        engine.dispose()


@pytest.mark.parametrize("config", [None, SimpleNamespace(cmd_opts=None)])
def test_nonisolated_programmatic_or_missing_command_metadata_fails_closed(config):
    engine, connection = _connection()
    try:
        with pytest.raises(MigrationApprovalError, match="command is not authorized"):
            enforce_nyay19_migration_release_guard(
                config,
                connection,
                environment="production",
                environ={},
                runtime_intent=_upgrade_intent(),
            )
    finally:
        connection.close()
        engine.dispose()


@pytest.mark.parametrize(
    "config",
    [
        _config("stamp", revision=TARGET_REVISION),
        _config("downgrade", revision=PARENT_REVISION),
        _config("upgrade", revision="head"),
        _config("upgrade", revision="+1"),
        _unknown_config(),
    ],
)
def test_nonisolated_mutation_requires_exact_upgrade_target(config):
    engine, connection = _connection()
    try:
        with pytest.raises(MigrationApprovalError, match="command is not authorized"):
            enforce_nyay19_migration_release_guard(
                config,
                connection,
                environment="production",
                environ={},
                runtime_intent=_upgrade_intent(),
            )
    finally:
        connection.close()
        engine.dispose()


def test_sqlite_stamped_0020_is_not_an_authoritative_noop():
    engine, connection = _connection()
    _set_revision(connection, TARGET_REVISION)
    try:
        transaction = connection.begin()
        with pytest.raises(MigrationApprovalError, match="live target rejected"):
            enforce_nyay19_migration_release_guard(
                _config("upgrade", revision=TARGET_REVISION),
                connection,
                environment="production",
                environ={},
                runtime_intent=_upgrade_intent(),
            )
        transaction.rollback()
    finally:
        connection.close()
        engine.dispose()


def test_exact_authoritative_0020_noop_validates_frozen_postflight(
    monkeypatch,
):
    connection = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(url=None),
        in_transaction=lambda: True,
    )
    observed = []
    monkeypatch.setattr(
        release_guard,
        "_prepare_authoritative_transaction",
        lambda _connection: observed.append("prepared"),
    )
    def current_revision(_connection):
        observed.append("revision")
        return TARGET_REVISION

    monkeypatch.setattr(release_guard, "_current_revision", current_revision)
    monkeypatch.setattr(
        release_guard,
        "_validate_at_head",
        lambda _connection: observed.append("postflight"),
    )
    enforce_nyay19_migration_release_guard(
        _config("upgrade", revision=TARGET_REVISION),
        connection,
        environment="production",
        environ={},
        runtime_intent=_upgrade_intent(),
    )
    assert observed == ["prepared", "revision", "postflight"]


def test_stamped_partial_0020_rejects_instead_of_reporting_noop(monkeypatch):
    connection = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(url=None),
        in_transaction=lambda: True,
    )
    monkeypatch.setattr(
        release_guard,
        "_prepare_authoritative_transaction",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: TARGET_REVISION,
    )
    monkeypatch.setattr(
        release_guard,
        "_validate_at_head",
        lambda _connection: (_ for _ in ()).throw(RuntimeError()),
    )
    with pytest.raises(MigrationApprovalError, match="head validation rejected"):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision=TARGET_REVISION),
            connection,
            environment="production",
            environ={},
            runtime_intent=_upgrade_intent(),
        )


def test_execution_postflight_revalidates_exact_head_and_privacy_zero(monkeypatch):
    observed = []
    connection = SimpleNamespace(in_transaction=lambda: True)
    monkeypatch.setattr(
        release_guard,
        "_validate_at_head",
        lambda candidate: observed.append(candidate),
    )

    release_guard.enforce_nyay19_migration_postflight(connection)

    assert observed == [connection]


def test_execution_postflight_fails_closed_outside_transaction_or_on_drift(
    monkeypatch,
):
    with pytest.raises(MigrationApprovalError, match="postflight rejected"):
        release_guard.enforce_nyay19_migration_postflight(
            SimpleNamespace(in_transaction=lambda: False)
        )

    monkeypatch.setattr(
        release_guard,
        "_validate_at_head",
        lambda _connection: (_ for _ in ()).throw(RuntimeError("sensitive")),
    )
    with pytest.raises(MigrationApprovalError, match="postflight rejected") as caught:
        release_guard.enforce_nyay19_migration_postflight(
            SimpleNamespace(in_transaction=lambda: True)
        )
    assert "sensitive" not in str(caught.value)


def test_at_head_revalidates_catalog_before_schema_and_privacy_zero(monkeypatch):
    events = []
    module = SimpleNamespace(
        _begin_and_lock=lambda _connection, *, downgrade: events.append(
            ("locked", downgrade)
        ),
        _validate_postflight=lambda _connection, *, head: events.append(
            ("schema", head)
        ),
    )
    monkeypatch.setattr(release_guard, "_target_module", lambda: module)
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: events.append("revision") or TARGET_REVISION,
    )
    monkeypatch.setattr(
        release_guard,
        "_validate_authority_catalog",
        lambda _connection: events.append("catalog"),
    )
    monkeypatch.setattr(
        release_guard,
        "_target_fingerprint",
        lambda _connection: events.append("target") or "b" * 64,
    )
    monkeypatch.setattr(
        release_guard,
        "_validate_legacy_deletion_authority",
        lambda _connection: events.append("deletion-authority"),
    )
    monkeypatch.setattr(
        release_guard,
        "_count",
        lambda _connection, _sql: events.append("privacy-zero") or 0,
    )
    monkeypatch.setattr(
        release_guard,
        "source_authority_is_valid",
        lambda: events.append("source") or True,
    )

    release_guard._validate_at_head(SimpleNamespace())

    assert events == [
        ("locked", True),
        "revision",
        "catalog",
        ("schema", True),
        "target",
        "deletion-authority",
        "privacy-zero",
        "privacy-zero",
        "privacy-zero",
        "source",
    ]


@pytest.mark.parametrize("remaining_index", (0, 1, 2))
def test_at_head_noop_rejects_incomplete_locked_privacy_freeze(
    monkeypatch,
    remaining_index,
):
    module = SimpleNamespace(
        _begin_and_lock=lambda _connection, *, downgrade: None,
        _validate_postflight=lambda _connection, *, head: None,
    )
    monkeypatch.setattr(release_guard, "_target_module", lambda: module)
    monkeypatch.setattr(
        release_guard,
        "_validate_authority_catalog",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: TARGET_REVISION,
    )
    monkeypatch.setattr(
        release_guard,
        "_validate_legacy_deletion_authority",
        lambda _connection: None,
    )
    values = iter(1 if index == remaining_index else 0 for index in range(3))
    monkeypatch.setattr(
        release_guard,
        "_count",
        lambda _connection, _sql: next(values),
    )
    monkeypatch.setattr(
        release_guard,
        "source_authority_is_valid",
        lambda: True,
    )
    monkeypatch.setattr(
        release_guard,
        "_target_fingerprint",
        lambda _connection: "b" * 64,
    )
    with pytest.raises(RuntimeError, match="privacy freeze incomplete"):
        release_guard._validate_at_head(SimpleNamespace())


def test_at_head_noop_rejects_endpoint_routing_override(monkeypatch):
    from sqlalchemy.engine import make_url

    module = SimpleNamespace(
        _begin_and_lock=lambda _connection, *, downgrade: None,
        _validate_postflight=lambda _connection, *, head: None,
    )
    monkeypatch.setattr(release_guard, "_target_module", lambda: module)
    monkeypatch.setattr(
        release_guard,
        "_validate_authority_catalog",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: TARGET_REVISION,
    )
    monkeypatch.setattr(
        release_guard,
        "_validate_legacy_deletion_authority",
        lambda _connection: None,
    )
    monkeypatch.setattr(release_guard, "_count", lambda _connection, _sql: 0)
    monkeypatch.setattr(
        release_guard,
        "source_authority_is_valid",
        lambda: True,
    )
    connection = SimpleNamespace(
        engine=SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://user@db.example:5432/database"
                "?host=elsewhere.example"
            )
        )
    )
    with pytest.raises(RuntimeError, match="target identity rejected"):
        release_guard._validate_at_head(connection)


def test_approved_or_at_head_execution_rejects_frozen_source_drift(monkeypatch):
    connection = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(url=None),
        in_transaction=lambda: True,
    )
    monkeypatch.setattr(
        release_guard,
        "source_authority_is_valid",
        lambda: False,
    )
    with pytest.raises(MigrationApprovalError, match="source authority rejected"):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision=TARGET_REVISION),
            connection,
            environment="production",
            environ={},
            runtime_intent=_upgrade_intent(),
        )


@pytest.mark.parametrize("revision", ["0018_privacy", "0021_future", ""])
def test_only_exact_0019_can_enter_the_approved_mutation_path(
    revision,
    monkeypatch,
):
    engine, connection = _connection()
    monkeypatch.setattr(
        release_guard,
        "_prepare_authoritative_transaction",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: revision,
    )
    try:
        transaction = connection.begin()
        with pytest.raises(MigrationApprovalError, match="database revision rejected"):
            enforce_nyay19_migration_release_guard(
                _config("upgrade", revision=TARGET_REVISION),
                connection,
                environment="production",
                environ={},
                runtime_intent=_upgrade_intent(),
            )
        transaction.rollback()
    finally:
        connection.close()
        engine.dispose()


def test_exact_report_and_exact_locked_live_state_are_required(
    tmp_path,
    monkeypatch,
):
    approved = _report()
    path = tmp_path / "approved.json"
    digest = _write_report(path, approved)
    engine, connection = _connection()
    _set_revision(connection, PARENT_REVISION)
    observed = []

    def locked_state(candidate, **metadata):
        observed.append(candidate.in_transaction())
        assert metadata == {
            "change_reference": approved["change_reference"],
            "approval_window_ends_at": approved["approval_window_ends_at"],
            "preflight_observed_at": approved["preflight_observed_at"],
        }
        return approved

    monkeypatch.setattr(release_guard, "locked_parent_report", locked_state)
    monkeypatch.setattr(
        release_guard,
        "_prepare_authoritative_transaction",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: PARENT_REVISION,
    )
    monkeypatch.setattr(
        release_guard,
        "_database_clock",
        lambda _connection: datetime(2026, 8, 22, 11, 30, tzinfo=timezone.utc),
    )
    try:
        transaction = connection.begin()
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision=TARGET_REVISION),
            connection,
            environment="production",
            environ=_authority(path, digest),
            runtime_intent=_upgrade_intent(),
        )
        transaction.rollback()
        assert observed == [True]

        # All seven counts remain identical; only one canonical locked row
        # changed, represented by the authority digest.
        changed = {**approved, "authority_state_digest": "d" * 64}
        changed["state_fingerprint"] = release_guard.state_fingerprint(changed)
        monkeypatch.setattr(
            release_guard,
            "locked_parent_report",
            lambda _connection, **_metadata: changed,
        )
        transaction = connection.begin()
        with pytest.raises(MigrationApprovalError, match="live state changed"):
            enforce_nyay19_migration_release_guard(
                _config("upgrade", revision=TARGET_REVISION),
                connection,
                environment="production",
                environ=_authority(path, digest),
                runtime_intent=_upgrade_intent(),
            )
        transaction.rollback()
    finally:
        connection.close()
        engine.dispose()


def test_execution_rejects_window_expiring_after_live_reconciliation(
    tmp_path,
    monkeypatch,
):
    approved = _report()
    path = tmp_path / "approved.json"
    digest = _write_report(path, approved)
    engine, connection = _connection()
    _set_revision(connection, PARENT_REVISION)
    monkeypatch.setattr(
        release_guard,
        "locked_parent_report",
        lambda _connection, **_metadata: approved,
    )
    monkeypatch.setattr(
        release_guard,
        "_prepare_authoritative_transaction",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: PARENT_REVISION,
    )
    monkeypatch.setattr(
        release_guard,
        "_database_clock",
        lambda _connection: datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
    )
    try:
        transaction = connection.begin()
        with pytest.raises(MigrationApprovalError, match="approval window expired"):
            enforce_nyay19_migration_release_guard(
                _config("upgrade", revision=TARGET_REVISION),
                connection,
                environment="production",
                environ=_authority(path, digest),
                runtime_intent=_upgrade_intent(),
            )
        transaction.rollback()
    finally:
        connection.close()
        engine.dispose()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report.update(extra=0),
        lambda report: report.pop("target_fingerprint"),
        lambda report: report.pop("authority_state_digest"),
        lambda report: report.update(target_source_sha256="a" * 64),
        lambda report: report.pop("change_reference"),
        lambda report: report.update(change_reference="invalid reference"),
        lambda report: report.update(
            approval_window_ends_at="2026-08-23T12:00:01Z"
        ),
        lambda report: report.update(
            preflight_observed_at="2026-08-22T11:00:00+00:00"
        ),
        lambda report: report.update(authority_state_digest="not-a-digest"),
        lambda report: report.update(postgres_major=15),
        lambda report: report.update(pgvector_present=1),
        lambda report: report["aggregates"].pop(AGGREGATE_KEYS[-1]),
        lambda report: report["aggregates"].update(extra=0),
        lambda report: report["aggregates"].update(
            {AGGREGATE_KEYS[0]: True}
        ),
        lambda report: report.update(state_fingerprint="a" * 64),
    ],
)
def test_report_schema_platform_aggregates_and_fingerprint_are_exact(
    tmp_path,
    mutate,
    monkeypatch,
):
    report = _report()
    mutate(report)
    path = tmp_path / "invalid.json"
    digest = _write_report(path, report)
    engine, connection = _connection()
    _set_revision(connection, PARENT_REVISION)
    monkeypatch.setattr(
        release_guard,
        "_prepare_authoritative_transaction",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: PARENT_REVISION,
    )
    try:
        transaction = connection.begin()
        with pytest.raises(MigrationApprovalError, match="preflight is invalid"):
            enforce_nyay19_migration_release_guard(
                _config("upgrade", revision=TARGET_REVISION),
                connection,
                environment="production",
                environ=_authority(path, digest),
                runtime_intent=_upgrade_intent(),
            )
        transaction.rollback()
    finally:
        connection.close()
        engine.dispose()
    assert set(_report()) == set(REPORT_KEYS)


def test_report_open_rejects_symlinks_even_when_the_target_is_mode_0600(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "target.json"
    digest = _write_report(target, _report())
    link = tmp_path / "approved.json"
    link.symlink_to(target)
    engine, connection = _connection()
    _set_revision(connection, PARENT_REVISION)
    monkeypatch.setattr(
        release_guard,
        "_prepare_authoritative_transaction",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: PARENT_REVISION,
    )
    try:
        transaction = connection.begin()
        with pytest.raises(MigrationApprovalError, match="unavailable"):
            enforce_nyay19_migration_release_guard(
                _config("upgrade", revision=TARGET_REVISION),
                connection,
                environment="production",
                environ=_authority(link, digest),
                runtime_intent=_upgrade_intent(),
            )
        transaction.rollback()
    finally:
        connection.close()
        engine.dispose()


def test_exact_mode_digest_acknowledgement_and_change_reference_are_required(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "approved.json"
    digest = _write_report(path, _report())
    engine, connection = _connection()
    _set_revision(connection, PARENT_REVISION)
    monkeypatch.setattr(
        release_guard,
        "_prepare_authoritative_transaction",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: PARENT_REVISION,
    )
    cases = []
    wrong_digest = _authority(path, digest)
    wrong_digest[PREFLIGHT_SHA_ENV] = "b" * 64
    cases.append(wrong_digest)
    wrong_ack = _authority(path, digest)
    wrong_ack[FREEZE_ACK_ENV] = "yes"
    cases.append(wrong_ack)
    wrong_reference = _authority(path, digest)
    wrong_reference[CHANGE_REFERENCE_ENV] = "NYAY-19-OTHER-CHANGE"
    cases.append(wrong_reference)
    wrong_window = _authority(path, digest)
    wrong_window[APPROVAL_WINDOW_END_ENV] = "2026-08-22T11:59:59Z"
    cases.append(wrong_window)
    try:
        for authority in cases:
            transaction = connection.begin()
            with pytest.raises(MigrationApprovalError):
                enforce_nyay19_migration_release_guard(
                    _config("upgrade", revision=TARGET_REVISION),
                    connection,
                    environment="production",
                    environ=authority,
                    runtime_intent=_upgrade_intent(),
                )
            transaction.rollback()
        path.chmod(0o644)
        transaction = connection.begin()
        with pytest.raises(MigrationApprovalError):
            enforce_nyay19_migration_release_guard(
                _config("upgrade", revision=TARGET_REVISION),
                connection,
                environment="production",
                environ=_authority(path, digest),
                runtime_intent=_upgrade_intent(),
            )
        transaction.rollback()
    finally:
        connection.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("now", "current"),
    [
        (datetime(2026, 8, 22, 11, 0, tzinfo=timezone.utc), True),
        (datetime(2026, 8, 22, 11, 30, tzinfo=timezone.utc), True),
        (datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc), False),
        (datetime(2026, 8, 22, 10, 59, 59, tzinfo=timezone.utc), False),
    ],
)
def test_approval_window_uses_locked_database_clock(now, current):
    assert release_guard._approval_window_is_current(_report(), now) is current


def test_approval_window_rejects_more_than_twenty_four_hours():
    report = _report()
    report["approval_window_ends_at"] = "2026-08-23T11:00:01Z"
    report["state_fingerprint"] = release_guard.state_fingerprint(report)
    assert release_guard._report_is_exact(report) is False


@pytest.mark.parametrize(
    ("database_now", "observed_at", "expected_success"),
    [
        (datetime(2026, 8, 22, 11, 0, 0, 900000, timezone.utc), None, True),
        (
            datetime(2026, 8, 22, 11, 30, tzinfo=timezone.utc),
            "2026-08-22T11:00:00Z",
            True,
        ),
        (
            datetime(2026, 8, 22, 10, 59, 59, tzinfo=timezone.utc),
            "2026-08-22T11:00:00Z",
            False,
        ),
        (
            datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc),
            "2026-08-22T11:00:00Z",
            False,
        ),
    ],
)
def test_locked_report_uses_or_preserves_database_observed_at(
    monkeypatch,
    database_now,
    observed_at,
    expected_success,
):
    connection = SimpleNamespace(in_transaction=lambda: True)
    module = SimpleNamespace(
        _begin_and_lock=lambda _connection, *, downgrade: None,
        _upgrade_data_preflight=lambda _connection: None,
    )
    monkeypatch.setattr(release_guard, "source_authority_is_valid", lambda: True)
    monkeypatch.setattr(
        release_guard,
        "_prepare_authoritative_transaction",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_current_revision",
        lambda _connection: PARENT_REVISION,
    )
    monkeypatch.setattr(release_guard, "_target_module", lambda: module)
    monkeypatch.setattr(
        release_guard,
        "_validate_authority_catalog",
        lambda _connection: None,
    )
    monkeypatch.setattr(
        release_guard,
        "_validate_legacy_deletion_authority",
        lambda _connection: None,
    )
    monkeypatch.setattr(release_guard, "_database_clock", lambda _connection: database_now)
    monkeypatch.setattr(release_guard, "_count", lambda _connection, _sql: 0)
    monkeypatch.setattr(release_guard, "_target_fingerprint", lambda _connection: "b" * 64)
    monkeypatch.setattr(
        release_guard,
        "_authority_state_digest",
        lambda _connection: "c" * 64,
    )
    arguments = {
        "change_reference": "NYAY-19-RELEASE-001",
        "approval_window_ends_at": "2026-08-22T12:00:00Z",
        "preflight_observed_at": observed_at,
    }
    if not expected_success:
        with pytest.raises(RuntimeError, match="approval window rejected"):
            release_guard.locked_parent_report(connection, **arguments)
        return
    report = release_guard.locked_parent_report(connection, **arguments)
    assert report["preflight_observed_at"] == (
        observed_at or "2026-08-22T11:00:00Z"
    )
    assert report["change_reference"] == "NYAY-19-RELEASE-001"
    assert report["approval_window_ends_at"] == "2026-08-22T12:00:00Z"


def test_force_approval_disables_otherwise_valid_isolated_bypass():
    engine, connection = _connection()
    try:
        with pytest.raises(MigrationApprovalError, match="command is not authorized"):
            enforce_nyay19_migration_release_guard(
                _config("upgrade", revision="head"),
                connection,
                environment="testing",
                environ={FORCE_APPROVAL_ENV: "1"},
                runtime_intent=_upgrade_intent("head"),
            )
    finally:
        connection.close()
        engine.dispose()


def test_stale_read_only_cmd_metadata_cannot_mask_actual_upgrade_intent():
    engine, connection = _connection()
    try:
        with pytest.raises(MigrationApprovalError, match="command is not authorized"):
            enforce_nyay19_migration_release_guard(
                _config("current"),
                connection,
                environment="production",
                environ={},
                runtime_intent=_upgrade_intent(),
            )
    finally:
        connection.close()
        engine.dispose()


def test_isolated_opt_in_cannot_authorize_an_unmarked_database_name():
    from sqlalchemy.engine import make_url

    unsafe = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(
            url=make_url("postgresql+psycopg://user:secret@127.0.0.1/production")
        ),
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            unsafe,
            environment="staging",
            environ={ISOLATED_EXECUTION_ENV: "1"},
        )


def test_staging_isolated_opt_in_requires_loopback_and_marker_name():
    safe = _isolated_postgres_target(
        "postgresql+psycopg://user:secret@127.0.0.1/nyayone_ci"
    )
    enforce_nyay19_migration_release_guard(
        _config("upgrade", revision="head"),
        safe,
        environment="staging",
        environ={ISOLATED_EXECUTION_ENV: "1"},
    )


@pytest.mark.parametrize("environment", ("development", "testing", "staging"))
@pytest.mark.parametrize("isolated_opt_in", (None, "0", "true"))
def test_every_postgres_isolated_bypass_requires_exact_explicit_opt_in(
    environment,
    isolated_opt_in,
):
    safe = _isolated_postgres_target(
        "postgresql+psycopg://user:secret@127.0.0.1/nyay19_qa"
    )
    authority = (
        {}
        if isolated_opt_in is None
        else {ISOLATED_EXECUTION_ENV: isolated_opt_in}
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            safe,
            environment=environment,
            environ=authority,
        )


@pytest.mark.parametrize("environment", ("development", "testing", "staging"))
@pytest.mark.parametrize(
    "database_name",
    (
        "production_qa",
        "prod_test",
        "stage_nyay19",
        "staging_ci",
        "productionclone_qa",
        "prod1_test",
        "stagecopy_nyay19",
        "qa_productioncopy",
    ),
)
def test_mixed_production_or_staging_tokens_can_never_use_isolated_bypass(
    environment,
    database_name,
):
    from sqlalchemy.engine import make_url

    target = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://user:secret@127.0.0.1/"
                + database_name
            )
        ),
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            target,
            environment=environment,
            environ={ISOLATED_EXECUTION_ENV: "1"},
        )


def test_development_postgres_bypass_also_requires_a_database_marker():
    from sqlalchemy.engine import make_url

    unmarked = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(
            url=make_url("postgresql+psycopg://user:secret@127.0.0.1/nyayone")
        ),
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            unmarked,
            environment="development",
            environ={ISOLATED_EXECUTION_ENV: "1"},
        )


def test_production_environment_never_honours_isolated_marker_opt_in():
    from sqlalchemy.engine import make_url

    marked = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://user:secret@127.0.0.1/nyay19_qa"
            )
        ),
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            marked,
            environment="production",
            environ={ISOLATED_EXECUTION_ENV: "1"},
        )


@pytest.mark.parametrize(
    "database_name",
    (
        "ls_w2gate_a_deadbeef",
        "nyay2_auth_deadbeef",
        "nyay3_char_deadbeef",
        "nyay4_gate_deadbeef",
        "nyay16_gate_deadbeef",
        "nyay17_idem_deadbeef",
        "nyay19_auth_deadbeef",
    ),
)
def test_known_ticket_scratch_names_are_isolated_only_on_loopback(
    database_name,
):
    from sqlalchemy.engine import make_url

    safe = _isolated_postgres_target(
        "postgresql+psycopg://user:secret@127.0.0.1/" + database_name
    )
    enforce_nyay19_migration_release_guard(
        _config("upgrade", revision="head"),
        safe,
        environment="testing",
        environ={ISOLATED_EXECUTION_ENV: "1"},
    )

    remote = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://user:secret@db.example.invalid/"
                + database_name
            )
        ),
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            remote,
            environment="testing",
            environ={ISOLATED_EXECUTION_ENV: "1"},
        )


def test_isolated_bypass_rejects_libpq_query_target_overrides():
    from sqlalchemy.engine import make_url

    disguised = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://user:secret@127.0.0.1/nyay19_qa"
                "?host=db.example.invalid&dbname=production"
            )
        ),
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            disguised,
            environment="testing",
            environ={ISOLATED_EXECUTION_ENV: "1"},
        )


@pytest.mark.parametrize(
    "routing_variable",
    (
        "PGHOST",
        "PGHOSTADDR",
        "PGPORT",
        "PGDATABASE",
        "PGSERVICE",
        "PGSERVICEFILE",
    ),
)
def test_isolated_bypass_rejects_ambient_libpq_routing(routing_variable):
    target = _isolated_postgres_target(
        "postgresql+psycopg://user:secret@127.0.0.1/nyay19_qa"
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            target,
            environment="testing",
            environ={
                ISOLATED_EXECUTION_ENV: "1",
                routing_variable: "10.0.0.9",
            },
        )


@pytest.mark.parametrize(
    ("live_database", "live_address", "live_port"),
    (
        ("production", "127.0.0.1", 5432),
        ("nyay19_qa", "8.8.8.8", 5432),
        ("nyay19_qa", "0.0.0.0", 5432),
        ("nyay19_qa", "224.0.0.1", 5432),
        ("nyay19_qa", "169.254.1.1", 5432),
        ("nyay19_qa", "192.0.2.1", 5432),
        ("nyay19_qa", "255.255.255.255", 5432),
        ("nyay19_qa", "not-an-ip", 5432),
        ("nyay19_qa", "10.0.0.9", 0),
        ("nyay19_qa", "10.0.0.9", True),
    ),
)
def test_isolated_bypass_rejects_unsafe_live_target_identity(
    live_database,
    live_address,
    live_port,
):
    from sqlalchemy.engine import make_url

    class Result:
        @staticmethod
        def one():
            return live_database, live_address, live_port

    target = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://user:secret@127.0.0.1/nyay19_qa"
            )
        ),
        execute=lambda _statement: Result(),
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            target,
            environment="testing",
            environ={ISOLATED_EXECUTION_ENV: "1"},
        )


def test_isolated_bypass_accepts_private_docker_server_and_mapped_port():
    from sqlalchemy.engine import make_url

    class Result:
        @staticmethod
        def one():
            return "nyay19_qa", "172.18.0.2", 5432

    target = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(
            url=make_url(
                "postgresql+psycopg://user:secret@"
                "127.0.0.1:55469/nyay19_qa"
            )
        ),
        execute=lambda _statement: Result(),
    )
    enforce_nyay19_migration_release_guard(
        _config("upgrade", revision="head"),
        target,
        environment="testing",
        environ={ISOLATED_EXECUTION_ENV: "1"},
    )


def test_isolated_bypass_requires_configured_literal_loopback():
    target = _isolated_postgres_target(
        "postgresql+psycopg://user:secret@localhost/nyay19_qa"
    )
    with pytest.raises(MigrationApprovalError):
        enforce_nyay19_migration_release_guard(
            _config("upgrade", revision="head"),
            target,
            environment="testing",
            environ={ISOLATED_EXECUTION_ENV: "1"},
        )
