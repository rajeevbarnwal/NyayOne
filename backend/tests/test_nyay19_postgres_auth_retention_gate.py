"""Pure oracles for the opt-in NYAY-19 PostgreSQL retention gate.

These tests make no PostgreSQL behavior claim.  They prove fail-closed target
routing, immutable migration pins, exact assertion/race inventories, strict
aggregate evaluators, seeded mutant closure, privacy scanning and final cleanup.
Authoritative product evidence exists only when the opt-in gate is executed
against PostgreSQL 16 plus pgvector.
"""

from __future__ import annotations

from copy import deepcopy
import inspect as pyinspect
import json
from types import SimpleNamespace

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import DateTime, JSON, String, Uuid, make_url
from sqlalchemy.exc import SQLAlchemyError

import scripts.nyay19_postgres_auth_retention_gate as gate
from scripts.nyay19_postgres_auth_retention_gate import (
    DISTINCT_MUTANT_IDS,
    EXPECTED_COOKIE_CONTRACT,
    EXPECTED_MUTANT_INVENTORY,
    LIBPQ_AMBIENT_KEYS,
    MUTANT_ALIAS_OF,
    REQUIRED_ASSERTION_IDS,
    REQUIRED_MUTANT_IDS,
    REQUIRED_RACE_CASES,
    Blocked,
    ProductGateFailure,
    ScratchCleanupFailure,
    _ScratchDatabaseManager,
    _assemble_assertions,
    _attempt_retention_observation_passes,
    _auth_check_catalog_observation_passes,
    _auth_constraint_catalog_observation_passes,
    _auth_index_catalog_observation_passes,
    _audit_observation_passes,
    _config_observation_passes,
    _concurrency_observation_passes,
    _evaluate_assertions,
    _exact_auth_schema_observation,
    _historical_migration_bytes_unchanged,
    _historical_migration_inventory,
    _is_postgresql_16_with_pgvector,
    _logout_expiry_observation_passes,
    _migration_observation_passes,
    _mutant_inventory,
    _mutant_inventory_observation_passes,
    _oracle_baselines,
    _populated_migration_observation_passes,
    _postgresql_auth_check_catalog_sql,
    _postgresql_auth_constraint_catalog_sql,
    _postgresql_auth_index_catalog_sql,
    _privacy_delete_observation_passes,
    _privacy_findings,
    _race_case_passes,
    _registration_erasure_observation_passes,
    _reject_ambient_libpq_environment,
    _rotation_observation_passes,
    _runtime_observation_passes,
    _safe_local_postgres_url,
    _schema_observation_passes,
    _scratch_cleanup_observation_passes,
    _seeded_mutant_results,
    _seeded_mutants_are_killed,
    _session_retention_observation_passes,
)


@pytest.fixture(autouse=True)
def _without_ambient_libpq_authority(monkeypatch):
    for key in tuple(gate.os.environ):
        if key in LIBPQ_AMBIENT_KEYS or key.startswith("PGSSL"):
            monkeypatch.delenv(key, raising=False)


def test_historical_lifecycle_and_application_head_are_exact():
    assert gate.PREVIOUS_REVISION == "0019_otp_security_authority"
    assert gate.PINNED_HEAD == "0020_auth_retention_lifecycle"
    config = Config(str(gate.BACKEND / "alembic.ini"))
    config.set_main_option(
        "script_location", str(gate.BACKEND / "app/db/migrations")
    )
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == [gate.PINNED_HEAD]
    assert scripts.get_revision(gate.PINNED_HEAD).down_revision == gate.PREVIOUS_REVISION


def test_immutable_migration_inventory_is_pinned_through_0019():
    assert len(gate.HISTORICAL_MIGRATION_SHA256) == 19
    assert tuple(gate.HISTORICAL_MIGRATION_SHA256)[0] == "0001_initial_pgvector.py"
    assert tuple(gate.HISTORICAL_MIGRATION_SHA256)[-1] == (
        "0019_otp_security_authority.py"
    )
    assert tuple(gate.POST_LEDGER_HISTORICAL_SHA256) == (
        "0016_dob_hash_reconcile.py",
        "0017_registration_invariants.py",
        "0018_registration_idempotency.py",
        "0019_otp_security_authority.py",
    )
    assert _historical_migration_bytes_unchanged()
    assert _historical_migration_inventory() == {
        "file_inventory_exact": True,
        "hash_inventory_exact": True,
        "ledger_crosscheck_exact": True,
    }


def test_immutable_migration_oracle_rejects_changed_post_ledger_file(tmp_path):
    source_root = gate.BACKEND.parent
    ledger_source = (
        source_root / "backend/app/db/migrations/MIGRATION_SHA256_LEDGER.json"
    )
    ledger = json.loads(ledger_source.read_text(encoding="utf-8"))
    for item in ledger["migrations"]:
        source = source_root / item["path"]
        target = tmp_path / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    versions = tmp_path / "backend/app/db/migrations/versions"
    versions.mkdir(parents=True, exist_ok=True)
    for filename in gate.POST_LEDGER_HISTORICAL_SHA256:
        source = source_root / "backend/app/db/migrations/versions" / filename
        (versions / filename).write_bytes(source.read_bytes())
    ledger_target = tmp_path / "backend/app/db/migrations/MIGRATION_SHA256_LEDGER.json"
    ledger_target.write_text(json.dumps(ledger), encoding="utf-8")
    assert _historical_migration_bytes_unchanged(tmp_path)
    changed = versions / "0019_otp_security_authority.py"
    changed.write_bytes(changed.read_bytes() + b"\n# unsafe rewrite\n")
    assert not _historical_migration_bytes_unchanged(tmp_path)


def test_immutable_migration_oracle_rejects_missing_and_extra_historical_files(
    tmp_path,
):
    source_root = gate.BACKEND.parent
    versions = tmp_path / "backend/app/db/migrations/versions"
    versions.mkdir(parents=True)
    for filename in gate.HISTORICAL_MIGRATION_SHA256:
        source = source_root / "backend/app/db/migrations/versions" / filename
        (versions / filename).write_bytes(source.read_bytes())
    ledger_source = (
        source_root / "backend/app/db/migrations/MIGRATION_SHA256_LEDGER.json"
    )
    ledger_target = tmp_path / "backend/app/db/migrations/MIGRATION_SHA256_LEDGER.json"
    ledger_target.parent.mkdir(parents=True, exist_ok=True)
    ledger_target.write_bytes(ledger_source.read_bytes())
    assert _historical_migration_bytes_unchanged(tmp_path)

    missing = versions / "0007_wave3_credentials.py"
    saved = missing.read_bytes()
    missing.unlink()
    inventory = _historical_migration_inventory(tmp_path)
    assert inventory["file_inventory_exact"] is False
    assert inventory["hash_inventory_exact"] is False
    assert not _historical_migration_bytes_unchanged(tmp_path)
    missing.write_bytes(saved)

    alternate = versions / "0019_unsafe_alternate.py"
    alternate.write_text(
        "revision = 'unsafe'\n", encoding="utf-8"
    )
    inventory = _historical_migration_inventory(tmp_path)
    assert inventory["file_inventory_exact"] is False
    assert inventory["hash_inventory_exact"] is False
    assert not _historical_migration_bytes_unchanged(tmp_path)
    alternate.unlink()

    (versions / "unreviewed_revision.py").write_text(
        "revision = 'unreviewed'\n", encoding="utf-8"
    )
    assert _historical_migration_inventory(tmp_path)["file_inventory_exact"] is False


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
            "postgresql+psycopg://qa:secret@localhost:5432/postgres?host=evil",
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
        (True, "0.8.6", False),
    ),
)
def test_runtime_pin_is_exact_postgresql_major_16_with_pgvector(
    version_num, vector_version, expected
):
    assert _is_postgresql_16_with_pgvector(version_num, vector_version) is expected


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

    assert gate._runtime_probe(base) == {
        "server_version_num": 160015,
        "postgres_major": 16,
        "pgvector_present": True,
    }
    assert make_url(str(captured["url"])).database == "nyay19_corrective_qa"
    assert captured["disposed"] is True


def test_exact_ordered_release_inventory_has_sixteen_unique_rows():
    assert len(REQUIRED_ASSERTION_IDS) == 16
    assert len(set(REQUIRED_ASSERTION_IDS)) == 16
    assert REQUIRED_ASSERTION_IDS[0] == "RUNTIME-POSTGRES-16-PGVECTOR"
    assert REQUIRED_ASSERTION_IDS[-1] == (
        "HARNESS-MUTANTS-PRIVACY-SCRATCH-CLEANUP"
    )


def test_concurrency_inventory_pins_all_nine_required_interleavings():
    assert REQUIRED_RACE_CASES == (
        "rotation_vs_logout",
        "rotation_vs_anonymise",
        "rotation_vs_delete",
        "privacy_delete_vs_verify_session_mint",
        "expiry_vs_session_resolve",
        "attempt_retention_vs_verify",
        "logout_vs_verify",
        "registration_anonymise_vs_retention_worker",
        "registration_delete_vs_retention_worker",
    )


def test_all_synthetic_baselines_satisfy_their_exact_oracles():
    rows = _oracle_baselines()
    assert _runtime_observation_passes(rows["runtime"])
    assert _migration_observation_passes(rows["migration"])
    assert _populated_migration_observation_passes(rows["populated"])
    assert _schema_observation_passes(rows["schema"])
    assert _config_observation_passes(rows["config"])
    assert _logout_expiry_observation_passes(rows["logout_expiry"])
    assert _rotation_observation_passes(rows["rotation"])
    assert _attempt_retention_observation_passes(rows["attempt_retention"])
    assert _session_retention_observation_passes(
        rows["session_anonymise"], mode="anonymise"
    )
    assert _session_retention_observation_passes(
        rows["session_delete"], mode="delete"
    )
    assert _registration_erasure_observation_passes(
        rows["registration_anonymise"], mode="anonymise"
    )
    assert _registration_erasure_observation_passes(
        rows["registration_delete"], mode="delete"
    )
    assert _privacy_delete_observation_passes(rows["privacy_delete"])
    assert _concurrency_observation_passes(rows["concurrency"])
    assert _audit_observation_passes(rows["audit"])
    assert _scratch_cleanup_observation_passes(rows["scratch"])


def _reflected_columns(specification):
    rows = []
    for name, kind, length, nullable, default in specification:
        if kind is String:
            column_type = String(length)
        elif kind is DateTime:
            column_type = DateTime(timezone=True)
        elif kind is Uuid:
            column_type = Uuid(as_uuid=True)
        elif kind is JSON:
            column_type = JSON()
        else:  # pragma: no cover - specification is closed above
            raise AssertionError(kind)
        reflected_default = {
            None: None,
            "pending": "'pending'::character varying",
            "active": "'active'::character varying",
            "now": "now()",
        }[default]
        rows.append(
            {
                "name": name,
                "type": column_type,
                "nullable": nullable,
                "default": reflected_default,
            }
        )
    return rows


class _AuthSchemaInspector:
    def __init__(self):
        self.columns = {
            "login_attempts": _reflected_columns(gate._LOGIN_COLUMNS),
            "auth_sessions": _reflected_columns(gate._SESSION_COLUMNS),
        }
        self.primary_keys = {
            "login_attempts": {
                "name": "pk_login_attempts",
                "constrained_columns": ["id"],
            },
            "auth_sessions": {
                "name": "pk_auth_sessions",
                "constrained_columns": ["id"],
            },
        }
        self.foreign_keys = {
            "login_attempts": [
                {
                    "name": "fk_login_attempts_registration_id_student_registrations",
                    "constrained_columns": ["registration_id"],
                    "referred_schema": None,
                    "referred_table": "student_registrations",
                    "referred_columns": ["id"],
                    "options": {"ondelete": "CASCADE"},
                },
                {
                    "name": "fk_login_attempts_challenge_id_otp_challenges",
                    "constrained_columns": ["challenge_id"],
                    "referred_schema": None,
                    "referred_table": "otp_challenges",
                    "referred_columns": ["id"],
                    "options": {"ondelete": "SET NULL"},
                },
            ],
            "auth_sessions": [
                {
                    "name": "fk_auth_sessions_user_id_users",
                    "constrained_columns": ["user_id"],
                    "referred_schema": None,
                    "referred_table": "users",
                    "referred_columns": ["id"],
                    "options": {"ondelete": "CASCADE"},
                }
            ],
        }
        self.uniques = {
            "login_attempts": [
                {
                    "name": "uq_login_attempts_opaque_id",
                    "column_names": ["opaque_id"],
                }
            ],
            "auth_sessions": [
                {
                    "name": "uq_auth_sessions_token_hash",
                    "column_names": ["token_hash"],
                }
            ],
        }
        self.indexes = {
            "login_attempts": [
                {
                    "name": name,
                    "column_names": list(columns),
                    "unique": unique,
                    "dialect_options": {},
                }
                for name, (columns, unique, _predicate) in gate._LOGIN_INDEXES.items()
            ],
            "auth_sessions": [
                {
                    "name": name,
                    "column_names": list(columns),
                    "unique": unique,
                    "dialect_options": (
                        {"postgresql_where": predicate} if predicate else {}
                    ),
                }
                for name, (columns, unique, predicate) in gate._SESSION_INDEXES.items()
            ],
        }
        self.indexes["login_attempts"].append(
            {
                "name": "uq_login_attempts_opaque_id",
                "column_names": ["opaque_id"],
                "unique": True,
                "duplicates_constraint": "uq_login_attempts_opaque_id",
                "include_columns": [],
                "dialect_options": {"postgresql_include": []},
            }
        )
        self.indexes["auth_sessions"].append(
            {
                "name": "uq_auth_sessions_token_hash",
                "column_names": ["token_hash"],
                "unique": True,
                "duplicates_constraint": "uq_auth_sessions_token_hash",
                "include_columns": [],
                "dialect_options": {"postgresql_include": []},
            }
        )
        self.checks = {
            "login_attempts": [
                {"name": name, "sqltext": sql, "dialect_options": {}}
                for name, sql in gate._LOGIN_CHECKS.items()
            ],
            "auth_sessions": [
                {"name": name, "sqltext": sql, "dialect_options": {}}
                for name, sql in gate._SESSION_CHECKS.items()
            ],
        }

    def get_table_names(self):
        return ["users", "student_registrations", "login_attempts", "auth_sessions"]

    def get_columns(self, table):
        return self.columns[table]

    def get_pk_constraint(self, table):
        return self.primary_keys[table]

    def get_foreign_keys(self, table):
        return self.foreign_keys[table]

    def get_unique_constraints(self, table):
        return self.uniques[table]

    def get_indexes(self, table):
        return self.indexes[table]

    def get_check_constraints(self, table):
        return self.checks[table]


def _catalog_observation():
    return {
        key: {"sqltext": sql, "validated": True, "no_inherit": False}
        for key, sql in gate._expected_auth_check_catalog().items()
    }


def _constraint_catalog_observation():
    return {
        key: row
        for key, (
            kind,
            columns,
            backing_index,
            delete_action,
            referred_table,
            referred_columns,
        ) in (
            gate._expected_auth_constraint_catalog().items()
        )
        for row in (
            {
                "kind": kind,
                "columns": columns,
                "validated": True,
                "deferrable": False,
                "deferred": False,
                "no_inherit": True,
                "update_action": "a" if kind == "f" else " ",
                "delete_action": delete_action if kind == "f" else " ",
                "match_type": "s" if kind == "f" else " ",
                "backing_index": backing_index,
                "referred_table": referred_table,
                "referred_columns": referred_columns,
            },
        )
    }


def _index_catalog_observation():
    return {
        key: {
            "key_columns": keys,
            "include_columns": includes,
            "unique": unique,
            "primary": primary,
            "exclusion": False,
            "valid": True,
            "ready": True,
            "live": True,
            "nulls_not_distinct": False,
            "has_no_expressions": True,
            "access_method": "btree",
            "predicate": predicate,
        }
        for key, (keys, includes, unique, primary, predicate) in (
            gate._expected_auth_index_catalog().items()
        )
    }


class _CatalogConnection:
    def __init__(
        self,
        rows=None,
        constraint_rows=None,
        index_rows=None,
        error=None,
    ):
        self.rows = rows or []
        self.constraint_rows = constraint_rows or []
        self.index_rows = index_rows or []
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, _parameters):
        if self.error is not None:
            raise self.error
        sql = str(statement)
        if "pg_catalog.pg_index" in sql:
            return self.index_rows
        if "con.contype IN" in sql:
            return self.constraint_rows
        return self.rows


class _CatalogEngine:
    def __init__(self, rows=None, constraint_rows=None, index_rows=None, error=None):
        self.rows = rows
        self.constraint_rows = constraint_rows
        self.index_rows = index_rows
        self.error = error
        self.dialect = SimpleNamespace(name="postgresql")

    def connect(self):
        return _CatalogConnection(
            self.rows,
            self.constraint_rows,
            self.index_rows,
            self.error,
        )


def _catalog_engine(
    observation=None,
    constraint_observation=None,
    index_observation=None,
):
    source = _catalog_observation() if observation is None else observation
    rows = [
        (table, name, row["sqltext"], row["validated"], row["no_inherit"])
        for (table, name), row in source.items()
    ]
    constraint_source = (
        _constraint_catalog_observation()
        if constraint_observation is None
        else constraint_observation
    )
    constraint_rows = [
        (
            table,
            name,
            row["kind"],
            row["validated"],
            row["deferrable"],
            row["deferred"],
            row["no_inherit"],
            row["update_action"],
            row["delete_action"],
            row["match_type"],
            row["backing_index"],
            row["referred_table"],
            row["columns"],
            row["referred_columns"],
        )
        for (table, name), row in constraint_source.items()
    ]
    index_source = (
        _index_catalog_observation()
        if index_observation is None
        else index_observation
    )
    index_rows = [
        (
            table,
            name,
            row["unique"],
            row["primary"],
            row["exclusion"],
            row["valid"],
            row["ready"],
            row["live"],
            row["nulls_not_distinct"],
            len(row["key_columns"]),
            len(row["key_columns"]) + len(row["include_columns"]),
            row["has_no_expressions"],
            row["access_method"],
            row["key_columns"] + row["include_columns"],
            row["predicate"],
        )
        for (table, name), row in index_source.items()
    ]
    return _CatalogEngine(
        rows=rows,
        constraint_rows=constraint_rows,
        index_rows=index_rows,
    )


def test_exact_auth_schema_baseline_passes_every_independent_axis():
    observation = _exact_auth_schema_observation(
        _AuthSchemaInspector(),
        dialect_name="postgresql",
        engine=_catalog_engine(),
    )
    assert observation == {key: True for key in _oracle_baselines()["schema"]}
    assert _schema_observation_passes(observation)
    assert gate._model_auth_schema_matches()


@pytest.mark.parametrize(
    "model,column_name,attribute",
    (
        ("LoginAttempt", "status", "server_default"),
        ("AuthSession", "status", "default"),
        ("LoginAttempt", "created_at", "server_default"),
        ("AuthSession", "updated_at", "onupdate"),
    ),
)
def test_model_schema_oracle_pins_server_client_and_onupdate_defaults(
    monkeypatch, model, column_name, attribute
):
    from app import models as model_inventory

    assert gate._model_auth_schema_matches()
    column = getattr(model_inventory, model).__table__.c[column_name]
    monkeypatch.setattr(column, attribute, None)
    assert not gate._model_auth_schema_matches()


@pytest.mark.parametrize(
    "table,column",
    (("login_attempts", "lookup_hash"), ("auth_sessions", "token_hash")),
)
def test_schema_oracle_rejects_nullable_lookup_and_token_authority(table, column):
    inspector = _AuthSchemaInspector()
    next(row for row in inspector.columns[table] if row["name"] == column)[
        "nullable"
    ] = True
    observation = _exact_auth_schema_observation(
        inspector, dialect_name="postgresql", engine=_catalog_engine()
    )
    assert observation["types_nullability_defaults_exact"] is False
    assert not _schema_observation_passes(observation)


@pytest.mark.parametrize(
    "mutation",
    ("wrong_type", "wrong_length", "wrong_default", "wrong_timezone"),
)
def test_schema_oracle_rejects_hostile_column_type_length_default_and_timezone(
    mutation,
):
    inspector = _AuthSchemaInspector()
    if mutation == "wrong_type":
        inspector.columns["auth_sessions"][0]["type"] = String(36)
    elif mutation == "wrong_length":
        next(
            row
            for row in inspector.columns["auth_sessions"]
            if row["name"] == "token_hash"
        )["type"] = String(63)
    elif mutation == "wrong_default":
        next(
            row
            for row in inspector.columns["login_attempts"]
            if row["name"] == "status"
        )["default"] = "'consumed'::character varying"
    else:
        next(
            row
            for row in inspector.columns["auth_sessions"]
            if row["name"] == "expires_at"
        )["type"] = DateTime(timezone=False)
    observation = _exact_auth_schema_observation(
        inspector, dialect_name="postgresql", engine=_catalog_engine()
    )
    assert observation["types_nullability_defaults_exact"] is False


def test_schema_oracle_rejects_pk_and_fk_option_mutants():
    primary = _AuthSchemaInspector()
    primary.primary_keys["auth_sessions"]["constrained_columns"] = ["user_id"]
    assert not _exact_auth_schema_observation(
        primary, dialect_name="postgresql", engine=_catalog_engine()
    )["primary_keys_exact"]
    primary_options = _AuthSchemaInspector()
    primary_options.primary_keys["auth_sessions"]["dialect_options"] = {
        "postgresql_include": ["user_id"]
    }
    assert not _exact_auth_schema_observation(
        primary_options, dialect_name="postgresql", engine=_catalog_engine()
    )["primary_keys_exact"]

    for options in ({}, {"ondelete": "SET NULL"}, {"ondelete": "CASCADE", "deferrable": True}):
        foreign = _AuthSchemaInspector()
        foreign.foreign_keys["auth_sessions"][0]["options"] = options
        assert not _exact_auth_schema_observation(
            foreign, dialect_name="postgresql", engine=_catalog_engine()
        )["foreign_keys_exact"]
    foreign_dialect = _AuthSchemaInspector()
    foreign_dialect.foreign_keys["auth_sessions"][0]["dialect_options"] = {
        "postgresql_not_valid": True
    }
    assert not _exact_auth_schema_observation(
        foreign_dialect, dialect_name="postgresql", engine=_catalog_engine()
    )["foreign_keys_exact"]

    duplicate = _AuthSchemaInspector()
    wrong = deepcopy(duplicate.foreign_keys["auth_sessions"][0])
    wrong["constrained_columns"] = ["token_hash"]
    duplicate.foreign_keys["auth_sessions"].insert(0, wrong)
    assert not _exact_auth_schema_observation(
        duplicate, dialect_name="postgresql", engine=_catalog_engine()
    )["foreign_keys_exact"]


def test_schema_oracle_rejects_unique_and_index_definition_option_mutants():
    unique = _AuthSchemaInspector()
    unique.uniques["auth_sessions"][0]["column_names"] = ["user_id"]
    assert not _exact_auth_schema_observation(
        unique, dialect_name="postgresql", engine=_catalog_engine()
    )["unique_constraints_exact"]
    duplicate_unique = _AuthSchemaInspector()
    wrong_unique = deepcopy(duplicate_unique.uniques["auth_sessions"][0])
    wrong_unique["column_names"] = ["user_id"]
    duplicate_unique.uniques["auth_sessions"].insert(0, wrong_unique)
    assert not _exact_auth_schema_observation(
        duplicate_unique, dialect_name="postgresql", engine=_catalog_engine()
    )["unique_constraints_exact"]
    unique_options = _AuthSchemaInspector()
    unique_options.uniques["auth_sessions"][0]["dialect_options"] = {
        "postgresql_include": ["user_id"]
    }
    assert not _exact_auth_schema_observation(
        unique_options, dialect_name="postgresql", engine=_catalog_engine()
    )["unique_constraints_exact"]

    for field, unsafe in (
        ("column_names", ["token_hash"]),
        ("unique", False),
    ):
        inspector = _AuthSchemaInspector()
        active = next(
            row
            for row in inspector.indexes["auth_sessions"]
            if row["name"] == "uq_auth_sessions_one_active_per_user"
        )
        active[field] = unsafe
        observation = _exact_auth_schema_observation(
            inspector, dialect_name="postgresql", engine=_catalog_engine()
        )
        assert observation["indexes_exact"] is False
        assert observation["partial_active_index_exact"] is False

    predicate = _AuthSchemaInspector()
    active = next(
        row
        for row in predicate.indexes["auth_sessions"]
        if row["name"] == "uq_auth_sessions_one_active_per_user"
    )
    active["dialect_options"]["postgresql_where"] = "status = 'revoked'"
    observation = _exact_auth_schema_observation(
        predicate, dialect_name="postgresql", engine=_catalog_engine()
    )
    assert observation["indexes_exact"] is False
    assert observation["partial_active_index_exact"] is False

    options = _AuthSchemaInspector()
    options.indexes["login_attempts"][0]["dialect_options"] = {
        "postgresql_include": ["opaque_id"]
    }
    assert not _exact_auth_schema_observation(
        options, dialect_name="postgresql", engine=_catalog_engine()
    )["indexes_exact"]


def test_index_oracle_requires_exact_uq_backing_duplicate_rows():
    def backing(inspector):
        return next(
            row
            for row in inspector.indexes["auth_sessions"]
            if row.get("duplicates_constraint") is not None
        )

    baseline = _AuthSchemaInspector()
    assert _exact_auth_schema_observation(
        baseline, dialect_name="postgresql", engine=_catalog_engine()
    )["indexes_exact"]

    missing = _AuthSchemaInspector()
    missing.indexes["auth_sessions"].remove(backing(missing))

    extra = _AuthSchemaInspector()
    extra_row = deepcopy(backing(extra))
    extra_row["name"] = "uq_auth_sessions_unexpected"
    extra_row["duplicates_constraint"] = "uq_auth_sessions_unexpected"
    extra.indexes["auth_sessions"].append(extra_row)

    wrong_name = _AuthSchemaInspector()
    backing(wrong_name)["name"] = "uq_auth_sessions_name_drift"
    backing(wrong_name)["duplicates_constraint"] = "uq_auth_sessions_name_drift"

    wrong_link = _AuthSchemaInspector()
    backing(wrong_link)["duplicates_constraint"] = "uq_login_attempts_opaque_id"

    wrong_columns = _AuthSchemaInspector()
    backing(wrong_columns)["column_names"] = ["user_id"]

    not_unique = _AuthSchemaInspector()
    backing(not_unique)["unique"] = False

    predicate = _AuthSchemaInspector()
    backing(predicate)["dialect_options"]["postgresql_where"] = (
        "status = 'active'"
    )

    include = _AuthSchemaInspector()
    backing(include)["include_columns"] = ["user_id"]

    dialect_include = _AuthSchemaInspector()
    backing(dialect_include)["dialect_options"]["postgresql_include"] = [
        "user_id"
    ]

    options = _AuthSchemaInspector()
    backing(options)["dialect_options"]["postgresql_nulls_not_distinct"] = True

    unexpected_options = _AuthSchemaInspector()
    backing(unexpected_options)["dialect_options"]["postgresql_ops"] = {}

    for mutant in (
        missing,
        extra,
        wrong_name,
        wrong_link,
        wrong_columns,
        not_unique,
        predicate,
        include,
        dialect_include,
        options,
        unexpected_options,
    ):
        observation = _exact_auth_schema_observation(
            mutant, dialect_name="postgresql", engine=_catalog_engine()
        )
        assert observation["indexes_exact"] is False
        assert observation["index_catalog_safety_exact"] is True
        assert not _schema_observation_passes(observation)


def test_check_catalog_oracle_rejects_sql_not_valid_no_inherit_and_inventory():
    baseline = _catalog_observation()
    assert _auth_check_catalog_observation_passes(baseline)
    key = next(iter(baseline))

    wrong_sql = deepcopy(baseline)
    wrong_sql[key]["sqltext"] = str(wrong_sql[key]["sqltext"]).replace(
        "'pending'", "'queued'", 1
    )
    not_valid = deepcopy(baseline)
    not_valid[key]["validated"] = False
    no_inherit = deepcopy(baseline)
    no_inherit[key]["no_inherit"] = True
    missing = deepcopy(baseline)
    missing.pop(key)
    extra = deepcopy(baseline)
    extra[("auth_sessions", "ck_unreviewed")] = {
        "sqltext": "1 = 1",
        "validated": True,
        "no_inherit": False,
    }
    assert all(
        not _auth_check_catalog_observation_passes(mutant)
        for mutant in (wrong_sql, not_valid, no_inherit, missing, extra)
    )


def test_check_inspector_rejects_wrong_duplicate_preceding_expected_name():
    inspector = _AuthSchemaInspector()
    wrong = deepcopy(inspector.checks["login_attempts"][0])
    wrong["sqltext"] = "1 = 1"
    inspector.checks["login_attempts"].insert(0, wrong)
    observation = _exact_auth_schema_observation(
        inspector, dialect_name="postgresql", engine=_catalog_engine()
    )
    assert observation["check_names_exact"] is False
    assert not _schema_observation_passes(observation)


@pytest.mark.parametrize("option", ("not_valid", "no_inherit"))
def test_check_inspector_dialect_options_fail_even_with_clean_catalog(option):
    inspector = _AuthSchemaInspector()
    inspector.checks["login_attempts"][0]["dialect_options"] = {option: True}
    observation = _exact_auth_schema_observation(
        inspector, dialect_name="postgresql", engine=_catalog_engine()
    )
    assert observation["check_semantics_exact"] is False


def test_postgresql_check_catalog_query_is_balanced_exact_and_fail_closed():
    baseline = _catalog_observation()
    observed = _postgresql_auth_check_catalog_sql(_catalog_engine(baseline))
    assert observed == baseline
    assert _postgresql_auth_check_catalog_sql(
        _CatalogEngine(error=SQLAlchemyError("sanitized"))
    ) is None
    rows = list(_catalog_engine(baseline).rows)
    assert _postgresql_auth_check_catalog_sql(_CatalogEngine(rows=rows + [rows[0]])) is None


def test_postgresql_constraint_catalog_pins_validation_and_nondeferrability():
    baseline = _constraint_catalog_observation()
    assert _auth_constraint_catalog_observation_passes(baseline)
    observed = _postgresql_auth_constraint_catalog_sql(_catalog_engine())
    assert observed == baseline

    cases = (
        (("login_attempts", "pk_login_attempts"), "deferrable", True),
        (("login_attempts", "uq_login_attempts_opaque_id"), "deferrable", True),
        (
            (
                "login_attempts",
                "fk_login_attempts_registration_id_student_registrations",
            ),
            "validated",
            False,
        ),
        (("auth_sessions", "pk_auth_sessions"), "no_inherit", False),
        (
            ("login_attempts", "uq_login_attempts_opaque_id"),
            "no_inherit",
            False,
        ),
        (
            (
                "login_attempts",
                "fk_login_attempts_registration_id_student_registrations",
            ),
            "no_inherit",
            False,
        ),
        (
            ("auth_sessions", "fk_auth_sessions_user_id_users"),
            "delete_action",
            "n",
        ),
        (
            ("auth_sessions", "fk_auth_sessions_user_id_users"),
            "backing_index",
            None,
        ),
        (
            ("auth_sessions", "fk_auth_sessions_user_id_users"),
            "referred_table",
            "student_registrations",
        ),
        (
            ("auth_sessions", "fk_auth_sessions_user_id_users"),
            "referred_columns",
            ("status",),
        ),
    )
    for key, field, unsafe in cases:
        mutant = deepcopy(baseline)
        mutant[key][field] = unsafe
        assert not _auth_constraint_catalog_observation_passes(mutant)

    rows = list(_catalog_engine().constraint_rows)
    duplicate = _CatalogEngine(constraint_rows=rows + [rows[0]])
    assert _postgresql_auth_constraint_catalog_sql(duplicate) is None
    assert _postgresql_auth_constraint_catalog_sql(
        _CatalogEngine(error=SQLAlchemyError("sanitized"))
    ) is None


def test_postgresql_index_catalog_pins_health_keys_and_zero_include_columns():
    baseline = _index_catalog_observation()
    assert _auth_index_catalog_observation_passes(baseline)
    observed = _postgresql_auth_index_catalog_sql(_catalog_engine())
    assert observed == baseline

    pk = ("login_attempts", "pk_login_attempts")
    active = ("auth_sessions", "uq_auth_sessions_one_active_per_user")
    for key, field, unsafe in (
        (pk, "include_columns", ("opaque_id",)),
        (active, "valid", False),
        (active, "ready", False),
        (active, "live", False),
        (active, "exclusion", True),
        (active, "nulls_not_distinct", True),
        (active, "has_no_expressions", False),
        (active, "access_method", "hash"),
        (active, "key_columns", ("token_hash",)),
    ):
        mutant = deepcopy(baseline)
        mutant[key][field] = unsafe
        assert not _auth_index_catalog_observation_passes(mutant)

    rows = list(_catalog_engine().index_rows)
    malformed = list(rows[0])
    malformed[10] += 1
    assert _postgresql_auth_index_catalog_sql(
        _CatalogEngine(index_rows=[tuple(malformed), *rows[1:]])
    ) is None
    assert _postgresql_auth_index_catalog_sql(
        _CatalogEngine(error=SQLAlchemyError("sanitized"))
    ) is None


def test_postgresql_schema_check_semantics_fail_closed_without_catalog_engine():
    observation = _exact_auth_schema_observation(
        _AuthSchemaInspector(), dialect_name="postgresql", engine=None
    )
    assert observation["check_semantics_exact"] is False
    assert not _schema_observation_passes(observation)


@pytest.mark.parametrize(
    "section,evaluator",
    (
        ("runtime", _runtime_observation_passes),
        ("migration", _migration_observation_passes),
        ("populated", _populated_migration_observation_passes),
        ("schema", _schema_observation_passes),
        ("config", _config_observation_passes),
        ("logout_expiry", _logout_expiry_observation_passes),
        ("rotation", _rotation_observation_passes),
        ("attempt_retention", _attempt_retention_observation_passes),
        ("privacy_delete", _privacy_delete_observation_passes),
        ("audit", _audit_observation_passes),
        ("scratch", _scratch_cleanup_observation_passes),
    ),
)
def test_exact_observation_evaluators_reject_missing_and_extra_keys(
    section, evaluator
):
    baseline = _oracle_baselines()[section]
    missing = deepcopy(baseline)
    missing.pop(next(iter(missing)))
    extra = deepcopy(baseline)
    extra["unexpected"] = True
    assert evaluator(baseline)
    assert not evaluator(missing)
    assert not evaluator(extra)


@pytest.mark.parametrize(
    "section,evaluator,field",
    (
        ("runtime", _runtime_observation_passes, "postgres_major"),
        ("migration", _migration_observation_passes, "revision_rows"),
        ("populated", _populated_migration_observation_passes, "login_rows"),
        ("config", _config_observation_passes, "minimum_window_days"),
        ("logout_expiry", _logout_expiry_observation_passes, "logout_audit_count"),
        ("rotation", _rotation_observation_passes, "active_sessions"),
        ("privacy_delete", _privacy_delete_observation_passes, "request_rows"),
        ("scratch", _scratch_cleanup_observation_passes, "created"),
    ),
)
def test_integer_evidence_rejects_python_boolean_aliases(section, evaluator, field):
    baseline = _oracle_baselines()[section]
    mutant = deepcopy(baseline)
    mutant[field] = True
    assert evaluator(baseline)
    assert not evaluator(mutant)


def test_privacy_delete_requires_both_legacy_account_and_registration_freezes():
    baseline = _oracle_baselines()["privacy_delete"]
    assert _privacy_delete_observation_passes(baseline)
    for field, unsafe in (
        ("legacy_accounts_frozen", 0),
        ("legacy_registrations_frozen", 0),
    ):
        mutant = deepcopy(baseline)
        mutant[field] = unsafe
        assert not _privacy_delete_observation_passes(mutant)


@pytest.mark.parametrize(
    "field",
    (
        "post_ddl_exact_head_validation",
        "post_ddl_validation_failure_rolled_back",
    ),
)
def test_migration_oracle_requires_post_ddl_validation_and_rollback(field):
    baseline = _oracle_baselines()["migration"]
    mutant = deepcopy(baseline)
    mutant[field] = False
    assert _migration_observation_passes(baseline)
    assert not _migration_observation_passes(mutant)


def test_gate_never_mutates_append_only_audit_events():
    source = gate.Path(gate.__file__).read_text(encoding="utf-8")
    assert gate._gate_preserves_append_only_audit_events(source)
    assert not gate._gate_preserves_append_only_audit_events(
        "DELETE FROM audit_events WHERE action = 'hostile'"
    )
    assert not gate._gate_preserves_append_only_audit_events(
        "UPDATE audit_events SET action = 'hostile'"
    )
    assert not gate._gate_preserves_append_only_audit_events(
        'statement = text("DELETE FROM " + "audit_events")'
    )


def test_erased_refusal_is_marker_free_and_runs_after_invalid_parent_cleanup():
    lifecycle = pyinspect.getsource(gate._run_migration_lifecycle_probe)
    assert "deletion_backfill_frozen" not in lifecycle
    assert lifecycle.index("invalid_unchanged") < lifecycle.index(
        "_remove_invalid_parent_attempt"
    ) < lifecycle.index("_seed_erased_auth_tombstones") < lifecycle.index(
        "erased_refusal = _run_alembic"
    )
    populated = pyinspect.getsource(gate._run_populated_migration_probe)
    assert populated.count('"downgrade", PREVIOUS_REVISION') == 1


@pytest.mark.parametrize(
    "field",
    (
        "legacy_delete_preflight_rejects_corrupt_target",
        "legacy_delete_downgrade_marker_refuses",
        "legacy_delete_backfill_aggregate_audit_exact",
    ),
)
def test_populated_migration_requires_safe_legacy_delete_backfill(field):
    baseline = _oracle_baselines()["populated"]
    mutant = deepcopy(baseline)
    mutant[field] = False
    assert _populated_migration_observation_passes(baseline)
    assert not _populated_migration_observation_passes(mutant)


def test_marker_and_erased_downgrade_refusals_are_independently_required():
    baseline = _oracle_baselines()["populated"]
    erased_missing = deepcopy(baseline)
    erased_missing["erased_downgrade_refused"] = False
    marker_missing = deepcopy(baseline)
    marker_missing["legacy_delete_downgrade_marker_refuses"] = False

    assert erased_missing["legacy_delete_downgrade_marker_refuses"] is True
    assert marker_missing["erased_downgrade_refused"] is True
    assert not _populated_migration_observation_passes(erased_missing)
    assert not _populated_migration_observation_passes(marker_missing)


@pytest.mark.parametrize("mode", ("anonymise", "delete"))
def test_session_mode_oracle_rejects_cross_mode_and_unknown_mode(mode):
    rows = _oracle_baselines()[f"session_{mode}"]
    other = "delete" if mode == "anonymise" else "anonymise"
    assert _session_retention_observation_passes(rows, mode=mode)
    assert not _session_retention_observation_passes(rows, mode=other)
    assert not _session_retention_observation_passes(rows, mode="archive")


@pytest.mark.parametrize("mode", ("anonymise", "delete"))
def test_registration_erasure_oracle_rejects_wrong_cardinality(mode):
    rows = _oracle_baselines()[f"registration_{mode}"]
    assert _registration_erasure_observation_passes(rows, mode=mode)
    mutant = deepcopy(rows)
    mutant["sessions_after"] += 1
    assert not _registration_erasure_observation_passes(mutant, mode=mode)


def test_cookie_contract_pins_host_only_api_path_strict_http_only_and_secure_parity():
    assert EXPECTED_COOKIE_CONTRACT == {
        "path": "/api/v1",
        "same_site": "strict",
        "http_only": True,
        "secure_parity": True,
        "host_only": True,
    }
    baseline = _oracle_baselines()["logout_expiry"]
    for key, unsafe in (
        ("path", "/"),
        ("same_site", "lax"),
        ("http_only", False),
        ("secure_parity", False),
        ("host_only", False),
    ):
        mutant = deepcopy(baseline)
        mutant["cookie_contract"][key] = unsafe
        assert not _logout_expiry_observation_passes(mutant)


def _clear_cookie_header(name, *, secure=False):
    secure_attribute = "; Secure" if secure else ""
    return (
        f'{name}=""; expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; '
        "Max-Age=0; Path=/api/v1; SameSite=strict"
        f"{secure_attribute}"
    )


def _both_cookie_evaluators_reject(contract, cleared):
    logout = deepcopy(_oracle_baselines()["logout_expiry"])
    logout["cookie_contract"] = contract
    logout["auth_cookie_clear"] = cleared.get("auth_session") is True
    logout["flow_cookie_clear"] = cleared.get("otp_flow") is True
    privacy = deepcopy(_oracle_baselines()["privacy_delete"])
    privacy["cookie_contract"] = contract
    privacy["auth_cookie_clear"] = cleared.get("auth_session") is True
    privacy["flow_cookie_clear"] = cleared.get("otp_flow") is True
    return bool(
        not _logout_expiry_observation_passes(logout)
        and not _privacy_delete_observation_passes(privacy)
    )


def test_real_set_cookie_headers_produce_exact_contract_for_both_evaluators():
    from fastapi import Response

    from app.core.auth_cookies import (
        clear_auth_session_cookie,
        clear_otp_flow_cookie,
        cookie_secure,
    )
    from app.core.config import settings

    names = (
        settings.auth_session_cookie_name,
        settings.otp_flow_cookie_name,
    )
    response = Response()
    clear_auth_session_cookie(response)
    clear_otp_flow_cookie(response)
    headers = response.headers.getlist("set-cookie")
    contract, cleared = gate._cookie_clear_contract(
        headers, names=names, secure=cookie_secure()
    )
    assert contract == EXPECTED_COOKIE_CONTRACT
    assert type(contract["path"]) is str
    assert type(contract["same_site"]) is str
    assert all(
        type(contract[key]) is bool
        for key in ("http_only", "secure_parity", "host_only")
    )
    assert cleared == {name: True for name in names}

    expiry_response = Response()
    clear_auth_session_cookie(expiry_response)
    expiry_contract, expiry_cleared = gate._cookie_clear_contract(
        expiry_response.headers.getlist("set-cookie"),
        names=(settings.auth_session_cookie_name,),
        secure=cookie_secure(),
    )
    combined = gate._combine_cookie_contracts(contract, expiry_contract)
    logout = deepcopy(_oracle_baselines()["logout_expiry"])
    logout["cookie_contract"] = combined
    logout["auth_cookie_clear"] = bool(
        cleared[settings.auth_session_cookie_name]
        and expiry_cleared[settings.auth_session_cookie_name]
    )
    logout["flow_cookie_clear"] = cleared[settings.otp_flow_cookie_name]
    privacy = deepcopy(_oracle_baselines()["privacy_delete"])
    privacy["cookie_contract"] = contract
    privacy["auth_cookie_clear"] = cleared[settings.auth_session_cookie_name]
    privacy["flow_cookie_clear"] = cleared[settings.otp_flow_cookie_name]
    assert _logout_expiry_observation_passes(logout)
    assert _privacy_delete_observation_passes(privacy)


@pytest.mark.parametrize(
    "mutate,secure",
    (
        (lambda rows: [rows[0].replace("/api/v1", "/api/v10"), rows[1]], False),
        (
            lambda rows: [rows[0].replace("SameSite=strict", "SameSite=Strict"), rows[1]],
            False,
        ),
        (
            lambda rows: [rows[0].replace("Path=/api/v1", "XPath=/api/v1"), rows[1]],
            False,
        ),
        (
            lambda rows: [rows[0].replace("HttpOnly", "HttpOnlySuffix"), rows[1]],
            False,
        ),
        (
            lambda rows: [
                rows[0].replace("Max-Age=0", "X-Max-Age=0"),
                rows[1],
            ],
            False,
        ),
        (lambda rows: [*rows, rows[0]], False),
        (
            lambda rows: [f"{rows[0]}; Path=/api/v1", rows[1]],
            False,
        ),
        (lambda rows: rows[:1], False),
        (lambda rows: [f"{rows[0]}; Domain=example.invalid", rows[1]], False),
        (lambda rows: [f"{rows[0]}; Secure", rows[1]], False),
        (lambda rows: [f"{rows[0]}; Secure=false", rows[1]], False),
        (lambda rows: [f"{rows[0]}; Secure=0", rows[1]], False),
        (lambda rows: [f"{rows[0]}; Secure=", rows[1]], False),
        (
            lambda rows: [rows[0].replace("; Secure", "; VerySecure"), rows[1]],
            True,
        ),
    ),
)
def test_cookie_parser_rejects_attribute_and_singleton_mutants(mutate, secure):
    names = ("auth_session", "otp_flow")
    headers = [_clear_cookie_header(name, secure=secure) for name in names]
    contract, cleared = gate._cookie_clear_contract(
        mutate(headers), names=names, secure=secure
    )
    assert _both_cookie_evaluators_reject(contract, cleared)


def test_cookie_evaluators_require_exact_contract_keys_and_types():
    for section, evaluator in (
        ("logout_expiry", _logout_expiry_observation_passes),
        ("privacy_delete", _privacy_delete_observation_passes),
    ):
        baseline = _oracle_baselines()[section]
        for key, unsafe in (
            ("path", True),
            ("same_site", True),
            ("http_only", 1),
            ("secure_parity", 1),
            ("host_only", 1),
        ):
            mutant = deepcopy(baseline)
            mutant["cookie_contract"][key] = unsafe
            assert not evaluator(mutant)
        missing = deepcopy(baseline)
        missing["cookie_contract"].pop("path")
        extra = deepcopy(baseline)
        extra["cookie_contract"]["unexpected"] = True
        assert not evaluator(missing)
        assert not evaluator(extra)


def test_secure_parity_requires_exact_flag_or_total_absence():
    assert gate._cookie_secure_parity_exact({}, secure=False)
    assert gate._cookie_secure_parity_exact({"secure": None}, secure=True)
    for value in (None, "false", "0", ""):
        assert not gate._cookie_secure_parity_exact({"secure": value}, secure=False)
    for value in ("false", "0", ""):
        assert not gate._cookie_secure_parity_exact({"secure": value}, secure=True)
    assert not gate._cookie_secure_parity_exact({}, secure=True)


def test_cookie_producer_signature_and_call_sites_remain_compatible():
    signature = pyinspect.signature(gate._cookie_clear_contract)
    assert tuple(signature.parameters) == ("headers", "names", "secure")
    assert signature.parameters["names"].kind is pyinspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["secure"].kind is pyinspect.Parameter.KEYWORD_ONLY
    logout_source = pyinspect.getsource(gate._run_logout_expiry_probe)
    privacy_source = pyinspect.getsource(gate._run_privacy_delete_probe)
    assert logout_source.count("_cookie_clear_contract(") == 2
    assert "_combine_cookie_contracts(" in logout_source
    assert privacy_source.count("_cookie_clear_contract(") == 1


def test_auth_retention_config_distinguishes_documented_empty_from_unsafe_text():
    from pydantic import ValidationError

    from app.core.config import Settings

    empty = Settings(
        _env_file=None,
        retention_days_login_attempt="",
        retention_days_auth_session="",
    )
    assert empty.retention_days_login_attempt is None
    assert empty.retention_days_auth_session is None
    documented = Settings(_env_file=gate.BACKEND.parent / ".env.example")
    assert {
        documented.retention_days_registration_pending,
        documented.retention_days_registration_inactive,
        documented.retention_days_otp_challenge,
        documented.retention_days_recovery_session,
        documented.retention_days_login_attempt,
        documented.retention_days_auth_session,
        documented.retention_days_audit_events,
    } == {None}
    for field in ("retention_days_login_attempt", "retention_days_auth_session"):
        for unsafe in (" ", "00", "+1", "1.0", True):
            with pytest.raises(ValidationError):
                Settings(_env_file=None, **{field: unsafe})

    baseline = _oracle_baselines()["config"]
    assert _config_observation_passes(baseline)
    for field in (
        "empty_login_env_is_none",
        "empty_session_env_is_none",
        "all_documented_empty_env_is_none",
        "noncanonical_text_rejected",
    ):
        mutant = deepcopy(baseline)
        mutant[field] = False
        assert not _config_observation_passes(mutant)


def test_cutoff_noop_and_rollback_axes_are_independently_required():
    baseline = _oracle_baselines()["attempt_retention"]
    for field in (
        "at_cutoff_real_unchanged",
        "at_cutoff_decoy_unchanged",
        "recent_real_unchanged",
        "recent_decoy_unchanged",
        "unset_window_unchanged",
        "rollback_restores_all_rows",
    ):
        mutant = deepcopy(baseline)
        mutant[field] = False
        assert not _attempt_retention_observation_passes(mutant)


def test_race_oracle_requires_real_two_backend_lock_wait_and_no_resurrection():
    race = _oracle_baselines()["concurrency"][REQUIRED_RACE_CASES[0]]
    assert _race_case_passes(race)
    for field, unsafe in (
        ("workers", 1),
        ("backend_count", 1),
        ("pg_lock_wait_observed", False),
        ("transactions_terminal", 1),
        ("linearizable_outcome_exact", False),
        ("session_resurrections", 1),
        ("reusable_old_bearers", 1),
        ("orphan_links", 1),
        ("split_commits", 1),
        ("timeouts", 1),
        ("state_constraints_valid", False),
    ):
        mutant = deepcopy(race)
        mutant[field] = unsafe
        assert not _race_case_passes(mutant)


def test_transaction_boundary_counter_rejects_coherent_double_commit():
    from sqlalchemy import event

    engine = gate.create_engine("sqlite://")
    counter = gate._TransactionBoundaryCounter()
    after_commit = counter.after_commit
    after_rollback = counter.after_rollback
    try:
        with gate.Session(engine) as session:
            event.listen(session, "after_commit", after_commit)
            event.listen(session, "after_rollback", after_rollback)
            try:
                session.execute(gate.text("SELECT 1"))
                session.commit()
                session.execute(gate.text("SELECT 1"))
                session.commit()
            finally:
                event.remove(session, "after_commit", after_commit)
                event.remove(session, "after_rollback", after_rollback)
    finally:
        engine.dispose()

    assert counter.commits == 2
    assert counter.rollbacks == 0
    split_commits = gate._observed_split_commits(
        [
            {"commits": counter.commits, "rollbacks": counter.rollbacks},
            {"commits": 0, "rollbacks": 1},
        ]
    )
    assert split_commits == 1
    coherent = deepcopy(
        _oracle_baselines()["concurrency"][REQUIRED_RACE_CASES[0]]
    )
    assert coherent["linearizable_outcome_exact"] is True
    coherent["split_commits"] = split_commits
    assert not _race_case_passes(coherent)


def test_all_race_producers_use_observed_transaction_boundaries():
    controlled_source = pyinspect.getsource(gate._run_controlled_pair)
    assert 'event.listen(session, "after_commit"' in controlled_source
    assert 'event.listen(session, "after_rollback"' in controlled_source
    assert "_observed_split_commits(outcomes)" in controlled_source
    for producer in (
        gate._run_user_lifecycle_race,
        gate._run_attempt_retention_verify_race,
        gate._run_registration_retention_race,
    ):
        source = pyinspect.getsource(producer)
        assert 'int(race["split_commits"])' in source
        assert "0 if coherent else 1" not in source


@pytest.mark.parametrize("case_name", tuple(gate.REGISTRATION_RETENTION_RACE_CASES))
def test_registration_retention_race_requires_shared_graph_and_recovery_flush(
    case_name,
):
    race = _oracle_baselines()["concurrency"][case_name]
    assert gate._registration_retention_race_case_passes(race)
    for field, unsafe in (
        ("shared_recovery_sessions", 0),
        ("shared_login_attempts", 0),
        ("shared_auth_sessions", 0),
        ("recovery_rows_flushed_before_auth_sweep", False),
        ("canonical_lock_order_observed", False),
    ):
        mutant = deepcopy(race)
        mutant[field] = unsafe
        assert not gate._registration_retention_race_case_passes(mutant)


def test_concurrency_oracle_rejects_missing_extra_and_reordered_case():
    baseline = _oracle_baselines()["concurrency"]
    assert _concurrency_observation_passes(baseline)
    missing = deepcopy(baseline)
    missing.pop(REQUIRED_RACE_CASES[-1])
    extra = deepcopy(baseline)
    extra["extra_race"] = deepcopy(next(iter(baseline.values())))
    reordered = dict(reversed(tuple(baseline.items())))
    assert not _concurrency_observation_passes(missing)
    assert not _concurrency_observation_passes(extra)
    assert not _concurrency_observation_passes(reordered)


def test_assertion_evaluator_rejects_missing_extra_duplicate_and_reordering():
    passing = [gate._assertion(identifier, True) for identifier in REQUIRED_ASSERTION_IDS]
    assert _evaluate_assertions(passing) == {
        "exact_inventory": True,
        "required": 16,
        "passed": 16,
        "failed": [],
        "inventory_failures": {
            "missing": 0,
            "extra": 0,
            "duplicate": 0,
            "reordered": False,
        },
        "overall_pass": True,
    }
    variants = (
        passing[:-1],
        passing + [gate._assertion("EXTRA", True)],
        passing + [deepcopy(passing[-1])],
        list(reversed(passing)),
    )
    assert all(not _evaluate_assertions(rows)["overall_pass"] for rows in variants)


def test_assertion_evaluator_requires_literal_true_not_truthy_values():
    passing = [gate._assertion(identifier, True) for identifier in REQUIRED_ASSERTION_IDS]
    passing[4]["passed"] = 1
    evaluated = _evaluate_assertions(passing)
    assert not evaluated["overall_pass"]
    assert evaluated["passed"] == 15
    assert evaluated["failed"] == [REQUIRED_ASSERTION_IDS[4]]
    assert gate._assertion("synthetic", 1)["passed"] is False


def test_assembled_assertions_are_exact_and_aggregate_only():
    observations = _oracle_baselines()
    harness = {
        "mutants": {identifier: True for identifier in REQUIRED_MUTANT_IDS},
        "mutant_inventory": dict(EXPECTED_MUTANT_INVENTORY),
        "privacy_scanned": True,
        "privacy_findings": 0,
        "scratch": observations["scratch"],
        "behavior_adapter_frozen": True,
        "native_postgres_executed": True,
    }
    assertions = _assemble_assertions(observations, harness)
    assert [row["id"] for row in assertions] == list(REQUIRED_ASSERTION_IDS)
    assert _evaluate_assertions(assertions)["overall_pass"]
    assert not _privacy_findings({"assertions": assertions})


def test_seeded_mutant_inventory_distinguishes_names_from_variants():
    results = _seeded_mutant_results()
    assert tuple(results) == REQUIRED_MUTANT_IDS
    assert len(results) == 94
    assert len(DISTINCT_MUTANT_IDS) == 64
    assert len(MUTANT_ALIAS_OF) == 30
    assert len(results) == len(DISTINCT_MUTANT_IDS) + len(MUTANT_ALIAS_OF)
    assert set(MUTANT_ALIAS_OF).issubset(results)
    assert set(MUTANT_ALIAS_OF.values()).issubset(DISTINCT_MUTANT_IDS)
    assert not set(MUTANT_ALIAS_OF.values()).intersection(MUTANT_ALIAS_OF)
    assert all(
        results[alias] is results[canonical]
        for alias, canonical in MUTANT_ALIAS_OF.items()
    )
    assert _mutant_inventory(results) == EXPECTED_MUTANT_INVENTORY
    assert _mutant_inventory_observation_passes(_mutant_inventory(results))
    assert _seeded_mutants_are_killed()


@pytest.mark.parametrize(
    "field",
    tuple(EXPECTED_MUTANT_INVENTORY),
)
def test_mutant_inventory_rejects_missing_wrong_or_truthy_counts(field):
    inventory = dict(EXPECTED_MUTANT_INVENTORY)
    inventory.pop(field)
    assert not _mutant_inventory_observation_passes(inventory)

    inventory = dict(EXPECTED_MUTANT_INVENTORY)
    inventory[field] += 1
    assert not _mutant_inventory_observation_passes(inventory)

    inventory = dict(EXPECTED_MUTANT_INVENTORY)
    inventory[field] = True
    assert not _mutant_inventory_observation_passes(inventory)


@pytest.mark.parametrize(
    "unsafe",
    (
        {"user_id": "opaque"},
        {"nested": {"token_hash": "redacted"}},
        {"value": "00000000-0000-4000-8000-000000000000"},
        {"value": "person" + chr(64) + "example.invalid"},
        {"value": "9876543210"},
        {"value": "2000-01-02"},
        {"value": "postgresql://localhost/private"},
        {"value": "a" * 64},
        {"value": "Set-Cookie: bearer"},
    ),
)
def test_privacy_scanner_rejects_identifying_and_secret_shaped_evidence(unsafe):
    assert _privacy_findings(unsafe)


def test_privacy_scanner_accepts_only_aggregate_release_evidence():
    safe = {
        "gate": "nyay19_postgres_auth_retention",
        "status": "PASS",
        "executed": True,
        "assertions": 16,
        "mutant_inventory": dict(EXPECTED_MUTANT_INVENTORY),
        "scratch": {"created": 3, "removed": 3},
        "privacy_findings": 0,
    }
    assert _privacy_findings(safe) == []


def test_scratch_manager_cleans_up_after_operation_failure(monkeypatch):
    inventory: set[str] = set()

    monkeypatch.setattr(gate, "_scratch_database_inventory", lambda _base: set(inventory))

    def create(_base, name):
        inventory.add(name)
        return "postgresql+psycopg://qa:secret@localhost/scratch"

    def drop(_base, name):
        inventory.discard(name)

    monkeypatch.setattr(gate, "_create_scratch", create)
    monkeypatch.setattr(gate, "_drop_scratch", drop)
    manager = _ScratchDatabaseManager(object())

    def fail(_url):
        raise ProductGateFailure("sanitized")

    with pytest.raises(ProductGateFailure, match="sanitized"):
        manager.run("migration_lifecycle", fail)
    summary = manager.summary()
    assert summary["created"] == 1
    assert summary["removed"] == 1
    assert summary["all_created_removed"] is True


def test_scratch_manager_compensates_when_create_becomes_visible_then_raises(
    monkeypatch,
):
    inventory: set[str] = set()
    compensated: list[str] = []
    monkeypatch.setattr(gate, "_scratch_database_inventory", lambda _base: set(inventory))

    def create_then_raise(_base, name):
        inventory.add(name)
        raise Blocked("ambiguous create result")

    def compensate(_base, name):
        compensated.append(name)
        inventory.discard(name)

    monkeypatch.setattr(gate, "_create_scratch", create_then_raise)
    monkeypatch.setattr(gate, "_drop_scratch", compensate)
    manager = _ScratchDatabaseManager(object())

    with pytest.raises(Blocked, match="ambiguous create result"):
        manager.run("migration_lifecycle", lambda _url: None)

    assert len(compensated) == 1
    assert inventory == set()
    assert manager.records == [
        {
            "purpose": "migration_lifecycle",
            "created": False,
            "cleanup": "PASS",
        }
    ]


def test_scratch_manager_makes_ambiguous_create_cleanup_failure_fatal(monkeypatch):
    inventory: set[str] = set()
    monkeypatch.setattr(gate, "_scratch_database_inventory", lambda _base: set(inventory))

    def create_then_raise(_base, name):
        inventory.add(name)
        raise Blocked("ambiguous create result")

    def fail_compensation(_base, _name):
        raise RuntimeError("private cleanup detail")

    monkeypatch.setattr(gate, "_create_scratch", create_then_raise)
    monkeypatch.setattr(gate, "_drop_scratch", fail_compensation)
    manager = _ScratchDatabaseManager(object())

    with pytest.raises(ScratchCleanupFailure) as caught:
        manager.run("migration_lifecycle", lambda _url: None)
    assert "private cleanup detail" not in str(caught.value)
    assert manager.records[0]["cleanup"] == "FAIL"
    summary = manager.summary()
    assert summary["cleanup_failed"] == 1
    assert summary["inventory_match"] is False


def test_scratch_manager_promotes_cleanup_failure_to_fatal(monkeypatch):
    inventory: set[str] = set()
    monkeypatch.setattr(gate, "_scratch_database_inventory", lambda _base: set(inventory))

    def create(_base, name):
        inventory.add(name)
        return "postgresql+psycopg://qa:secret@localhost/scratch"

    def fail_drop(_base, _name):
        raise RuntimeError("private database detail")

    monkeypatch.setattr(gate, "_create_scratch", create)
    monkeypatch.setattr(gate, "_drop_scratch", fail_drop)
    manager = _ScratchDatabaseManager(object())
    with pytest.raises(ScratchCleanupFailure) as caught:
        manager.run("behavior", lambda _url: None)
    assert "private database detail" not in str(caught.value)
    assert manager.summary()["cleanup_failed"] == 1


def test_run_gate_binds_all_three_frozen_adapters_in_order():
    source = pyinspect.getsource(gate.run_gate)
    assert "_behavior_adapter_pending" not in source
    assert source.index("_run_migration_lifecycle_probe") < source.index(
        "_run_populated_migration_probe"
    ) < source.index("_run_behavior_probe")


def test_run_gate_composes_legacy_and_aggregate_evidence_only(monkeypatch):
    baseline = _oracle_baselines()
    calls = []

    class FakeScratchManager:
        def __init__(self, base):
            assert base is sentinel

        def run(self, purpose, operation):
            calls.append((purpose, operation.__name__))
            if purpose == "migration_lifecycle":
                return {
                    "observation": deepcopy(baseline["migration"]),
                    "schema": deepcopy(baseline["schema"]),
                    "erased_refusal": {
                        "downgrade_refused": True,
                        "schema_unchanged": True,
                        "rows_unchanged": True,
                    },
                }
            if purpose == "migration_populated":
                populated = deepcopy(baseline["populated"])
                populated["erased_downgrade_refused"] = False
                populated["refusal_schema_unchanged"] = False
                populated["refusal_rows_unchanged"] = False
                return {
                    "observation": populated,
                    "legacy": {
                        "accepted_cases": 2,
                        "accounts_frozen": 2,
                        "registrations_frozen": 2,
                        "active_sessions": 0,
                        "idempotent_second_pass": True,
                    },
                }
            behavior = {
                key: deepcopy(value)
                for key, value in baseline.items()
                if key
                not in {"runtime", "migration", "populated", "schema", "scratch"}
            }
            # The behavior scratch has no authority for populated legacy rows.
            # A passing report proves run_gate overwrites this sentinel from
            # the populated-migration observation.
            behavior["privacy_delete"]["legacy_registrations_frozen"] = 0
            return behavior

        def summary(self):
            return deepcopy(baseline["scratch"])

    sentinel = object()
    monkeypatch.setattr(gate, "_runtime_probe", lambda _base: baseline["runtime"])
    monkeypatch.setattr(
        gate, "_historical_migration_bytes_unchanged", lambda: True
    )
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", FakeScratchManager)
    monkeypatch.setattr(
        gate,
        "_seeded_mutant_results",
        lambda: {identifier: True for identifier in REQUIRED_MUTANT_IDS},
    )

    report = gate.run_gate(sentinel)

    assert calls == [
        ("migration_lifecycle", "_run_migration_lifecycle_probe"),
        ("migration_populated", "_run_populated_migration_probe"),
        ("behavior", "_run_behavior_probe"),
    ]
    assert report["status"] == "PASS"
    assert report["executed"] is True
    assert report["assertion_summary"]["overall_pass"] is True
    assert report["mutant_inventory"] == EXPECTED_MUTANT_INVENTORY
    assert [row["id"] for row in report["assertions"]] == list(
        REQUIRED_ASSERTION_IDS
    )
    assert report["scratch"] == {
        "created": 3,
        "removed": 3,
        "cleanup_failed": 0,
        "all_created_removed": True,
    }
    assert _privacy_findings(report) == []


def test_cli_without_double_opt_in_is_blocked_and_aggregate(capsys, monkeypatch):
    monkeypatch.delenv(gate.OPT_IN_ENV, raising=False)
    assert gate.main([]) == gate.BLOCKED_EXIT
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED"
    assert report["executed"] is False
    assert report["assertion_ids"] == list(REQUIRED_ASSERTION_IDS)
    assert not _privacy_findings(report)
