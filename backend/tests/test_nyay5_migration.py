from __future__ import annotations

import importlib
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql

from app.models.registration import GUARDIAN_STATUSES, VERIFICATION_STATUSES

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env={
            **os.environ,
            "APP_ENV": "testing",
            "DATABASE_URL": f"sqlite+pysqlite:///{database}",
            "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


def test_nyay5_is_one_forward_revision_from_the_sealed_head():
    migration = importlib.import_module(
        "app.db.migrations.versions.0021_nyay5_profile_boundary"
    )
    assert migration.revision == "0021_nyay5_profile_boundary"
    assert migration.down_revision == "0020_auth_retention_lifecycle"
    assert callable(migration.upgrade)
    assert callable(migration.downgrade)
    assert callable(migration._validate_postflight)


def test_profile_metadata_matches_the_normalized_forward_shape(db_session):
    inspector = inspect(db_session.get_bind())
    profile_columns = {row["name"]: row for row in inspector.get_columns("student_profiles")}
    assert {
        "city": (True, 120),
        "preferred_language": (True, 16),
        "pronouns": (True, 60),
        "profile_version": (False, None),
    } == {
        name: (bool(profile_columns[name]["nullable"]), getattr(profile_columns[name]["type"], "length", None))
        for name in ("city", "preferred_language", "pronouns", "profile_version")
    }
    assert set(VERIFICATION_STATUSES) == {
        "pending", "in_review", "verified", "rejected", "expired", "revoked"
    }
    assert set(GUARDIAN_STATUSES) == {
        "pending", "sent", "verified", "rejected", "revoked"
    }
    verification_columns = {
        row["name"]: row
        for row in inspector.get_columns("student_verifications")
    }
    assert verification_columns["verified_email_hash"]["nullable"] is True
    assert verification_columns["verified_email_hash"]["type"].length == 64


def test_0021_installs_exact_verification_proof_and_v2_ledger_constraints(
    tmp_path: Path,
):
    database = tmp_path / "nyay5_exact_authority.sqlite"
    upgraded = _alembic(database, "upgrade", "0021_nyay5_profile_boundary")
    assert upgraded.returncode == 0, upgraded.stderr
    inspector = inspect(create_engine(f"sqlite+pysqlite:///{database}"))
    verification_checks = {
        row["name"]: " ".join(row["sqltext"].split())
        for row in inspector.get_check_constraints("student_verifications")
    }
    assert verification_checks[
        "ck_student_verifications_verified_email_proof"
    ] == (
        "(status = 'verified' AND verified_email_hash IS NOT NULL) OR "
        "(status <> 'verified' AND verified_email_hash IS NULL)"
    )
    ledger_checks = {
        row["name"]: row["sqltext"]
        for row in inspector.get_check_constraints(
            "registration_idempotency_records"
        )
    }
    assert "request_fingerprint_version IN ('v1', 'v2')" in ledger_checks[
        "ck_registration_idempotency_records_request_fingerprint_shape"
    ]


def test_0021_quarantines_unproven_legacy_guardian_positive(tmp_path: Path):
    database = tmp_path / "nyay5_guardian_quarantine.sqlite"
    upgraded_parent = _alembic(database, "upgrade", "0020_auth_retention_lifecycle")
    assert upgraded_parent.returncode == 0, upgraded_parent.stderr
    user_id = uuid.uuid4().hex
    registration_id = uuid.uuid4().hex
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (id, role, status) VALUES (?, 'student', 'active')",
            (user_id,),
        )
        connection.execute(
            "INSERT INTO student_registrations "
            "(id, user_id, first_name, last_name, mobile_hash, mobile_ct, "
            "dob_hash, dob_ct, dob_hash_state, key_version, status, is_minor) "
            "VALUES (?, ?, 'Legacy', 'Minor', ?, 'v1:mobile', ?, 'v1:dob', "
            "'verified', 'v1', 'active', true)",
            (registration_id, user_id, "a" * 64, "b" * 64),
        )
        connection.execute(
            "INSERT INTO student_profiles (id, registration_id) VALUES (?, ?)",
            (uuid.uuid4().hex, registration_id),
        )
        connection.execute(
            "INSERT INTO guardian_consents "
            "(id, registration_id, status, verified) "
            "VALUES (?, ?, 'verified', true)",
            (uuid.uuid4().hex, registration_id),
        )
        connection.execute(
            "INSERT INTO student_verifications "
            "(id, registration_id, method, status) "
            "VALUES (?, ?, 'institutional_email', 'verified')",
            (uuid.uuid4().hex, registration_id),
        )
        connection.commit()

    upgraded = _alembic(database, "upgrade", "0021_nyay5_profile_boundary")
    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status, verified FROM guardian_consents "
            "WHERE registration_id = ?",
            (registration_id,),
        ).fetchone() == ("revoked", 0)
        assert connection.execute(
            "SELECT status FROM student_verifications "
            "WHERE registration_id = ?",
            (registration_id,),
        ).fetchone() == ("revoked",)


class _CatalogResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _CatalogConnection:
    def __init__(self, rows, drift_counts=(0, 0, 0)):
        self.dialect = SimpleNamespace(name="postgresql")
        self._rows = rows
        self._drift = iter(drift_counts)

    def execute(self, *_args, **_kwargs):
        return _CatalogResult(self._rows)

    def scalar(self, *_args, **_kwargs):
        return next(self._drift)


class _PostgresCheckConnection:
    def __init__(self, definitions):
        self.dialect = postgresql.dialect()
        self._definitions = iter(definitions)
        self.executed = []

    def execute(self, statement, *_args, **_kwargs):
        self.executed.append(str(statement))
        return _CatalogResult([])

    def scalar(self, statement, *_args, **_kwargs):
        self.executed.append(str(statement))
        return next(self._definitions)


class _PostgresCheckInspector:
    def __init__(self, sqltext, definitions):
        self.bind = _PostgresCheckConnection(definitions)
        self._sqltext = sqltext

    def get_check_constraints(self, _table):
        return [
            {
                "name": "ck_student_verifications_status",
                "sqltext": self._sqltext,
            }
        ]


class _ExactNewTableInspector:
    def __init__(self, table: str, *, mutation: str | None = None):
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
        prompt = table == "auth_session_profile_prompts"
        parent_column = "auth_session_id" if prompt else "profile_id"
        parent_table = "auth_sessions" if prompt else "student_profiles"
        self.columns = [
            {
                "name": parent_column,
                "type": sa.CHAR(32),
                "nullable": False,
            },
        ]
        if prompt:
            self.columns.append(
                {
                    "name": "dismissed_at",
                    "type": sa.DateTime(timezone=True),
                    "nullable": False,
                }
            )
        else:
            self.columns.append(
                {"name": "value", "type": sa.String(80), "nullable": False}
            )
        self.columns.extend(
            [
                {"name": "id", "type": sa.CHAR(32), "nullable": False},
                {
                    "name": "created_at",
                    "type": sa.DateTime(timezone=True),
                    "nullable": False,
                },
                {
                    "name": "updated_at",
                    "type": sa.DateTime(timezone=True),
                    "nullable": False,
                },
                {
                    "name": "deleted_at",
                    "type": sa.DateTime(timezone=True),
                    "nullable": True,
                },
                {"name": "metadata_json", "type": sa.JSON(), "nullable": True},
            ]
        )
        self.pk = {"name": f"pk_{table}", "constrained_columns": ["id"]}
        self.fks = [
            {
                "name": f"fk_{table}_{parent_column}_{parent_table}",
                "constrained_columns": [parent_column],
                "referred_schema": None,
                "referred_table": parent_table,
                "referred_columns": ["id"],
                "options": {"ondelete": "CASCADE"},
            }
        ]
        self.uniques = [
            {
                "name": (
                    f"uq_{table}_{parent_column}"
                    if prompt
                    else f"uq_{table}_profile_id_value"
                ),
                "column_names": (
                    [parent_column]
                    if prompt
                    else ["profile_id", "value"]
                ),
            }
        ]
        self.indexes = [
            {
                "name": f"ix_{table}_{parent_column}",
                "column_names": [parent_column],
                "unique": False,
            }
        ]
        self.checks = (
            []
            if prompt
            else [
                {
                    "name": f"ck_{table}_value_length",
                    "sqltext": "length(value) >= 1 AND length(value) <= 80",
                }
            ]
        )

        if mutation == "extra_column":
            self.columns.append(
                {"name": "ambient", "type": sa.String(1), "nullable": True}
            )
        elif mutation == "primary_key":
            self.pk["name"] = "pk_ambient"
        elif mutation == "foreign_key":
            self.fks[0]["options"] = {"ondelete": "SET NULL"}
        elif mutation == "unique":
            self.uniques = []
        elif mutation == "index":
            self.indexes[0]["unique"] = True
        elif mutation == "check":
            self.checks = []
        elif mutation == "extra_check":
            self.checks.append(
                {"name": "ck_ambient", "sqltext": "1 = 1"}
            )

    def get_columns(self, _table):
        return self.columns

    def get_pk_constraint(self, _table):
        return self.pk

    def get_foreign_keys(self, _table):
        return self.fks

    def get_unique_constraints(self, _table):
        return self.uniques

    def get_indexes(self, _table):
        return self.indexes

    def get_check_constraints(self, _table):
        return self.checks


@pytest.mark.parametrize(
    "table",
    (
        "student_profile_interests",
        "student_profile_goals",
        "auth_session_profile_prompts",
    ),
)
def test_new_profile_table_catalog_oracle_accepts_only_the_exact_shape(table):
    migration = importlib.import_module(
        "app.db.migrations.versions.0021_nyay5_profile_boundary"
    )
    migration._validate_new_table_catalog(_ExactNewTableInspector(table), table)


@pytest.mark.parametrize(
    ("table", "mutation"),
    (
        ("student_profile_interests", "extra_column"),
        ("student_profile_interests", "primary_key"),
        ("student_profile_interests", "foreign_key"),
        ("student_profile_interests", "unique"),
        ("student_profile_interests", "index"),
        ("student_profile_interests", "check"),
        ("auth_session_profile_prompts", "extra_check"),
    ),
)
def test_new_profile_table_catalog_oracle_rejects_independent_drift(
    table,
    mutation,
):
    migration = importlib.import_module(
        "app.db.migrations.versions.0021_nyay5_profile_boundary"
    )
    with pytest.raises(migration.Nyay5ProfileMigrationError):
        migration._validate_new_table_catalog(
            _ExactNewTableInspector(table, mutation=mutation),
            table,
        )


def test_postgres_check_validation_compares_database_normalized_definitions():
    migration = importlib.import_module(
        "app.db.migrations.versions.0021_nyay5_profile_boundary"
    )
    postgres_definition = (
        "CHECK (status::text = ANY (ARRAY['pending'::character varying, "
        "'in_review'::character varying, 'verified'::character varying, "
        "'rejected'::character varying, 'expired'::character varying, "
        "'revoked'::character varying]::text[]))"
    )
    inspector = _PostgresCheckInspector(
        postgres_definition.removeprefix("CHECK (").removesuffix(")"),
        [postgres_definition, postgres_definition],
    )

    migration._check_constraint(
        inspector,
        "student_verifications",
        "ck_student_verifications_status",
        migration._NEW_VERIFICATION_STATUS,
    )

    assert any("CREATE TEMP TABLE" in sql for sql in inspector.bind.executed)
    assert any("ADD CONSTRAINT" in sql for sql in inspector.bind.executed)


@pytest.mark.parametrize(
    "definitions",
    [
        [None],
        [
            "CHECK (status::text = ANY (ARRAY['pending'::character varying]::text[]))",
            "CHECK (status::text = ANY (ARRAY['pending'::character varying, "
            "'verified'::character varying]::text[]))",
        ],
    ],
    ids=("missing", "semantic-drift"),
)
def test_postgres_check_validation_rejects_missing_or_drifted_definition(
    definitions,
):
    migration = importlib.import_module(
        "app.db.migrations.versions.0021_nyay5_profile_boundary"
    )
    inspector = _PostgresCheckInspector("irrelevant reflection", definitions)

    with pytest.raises(migration.Nyay5ProfileMigrationError):
        migration._check_constraint(
            inspector,
            "student_verifications",
            "ck_student_verifications_status",
            migration._NEW_VERIFICATION_STATUS,
        )


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [
            ("student_profiles", "r", "p", False, False),
            ("unexpected_profile_table", "r", "p", False, False),
        ],
        [("student_profiles", "v", "p", False, False)],
        [("student_profiles", "r", "t", False, False)],
        [("student_profiles", "r", "p", True, False)],
        [("student_profiles", "r", "p", False, True)],
    ],
    ids=("missing", "extra", "nonordinary", "temporary", "rls", "forced_rls"),
)
def test_postgres_profile_authority_rejects_noncanonical_catalog(rows):
    migration = importlib.import_module(
        "app.db.migrations.versions.0021_nyay5_profile_boundary"
    )
    connection = _CatalogConnection(rows)
    with pytest.raises(migration.Nyay5ProfileMigrationError):
        migration._validate_postgres_table_authority(
            connection, ("student_profiles",)
        )


@pytest.mark.parametrize(
    "drift_counts",
    [(1, 0, 0), (0, 1, 0), (0, 0, 1)],
    ids=("policy", "rule", "trigger"),
)
def test_postgres_profile_authority_rejects_policy_rule_and_trigger(
    drift_counts,
):
    migration = importlib.import_module(
        "app.db.migrations.versions.0021_nyay5_profile_boundary"
    )
    connection = _CatalogConnection(
        [("student_profiles", "r", "p", False, False)],
        drift_counts=drift_counts,
    )
    with pytest.raises(migration.Nyay5ProfileMigrationError):
        migration._validate_postgres_table_authority(
            connection, ("student_profiles",)
        )


@pytest.mark.parametrize(
    "drift_table",
    (
        "student_profiles",
        "student_registrations",
        "auth_sessions",
        "student_verifications",
        "guardian_consents",
        "consents",
        "registration_idempotency_records",
        "student_profile_interests",
        "student_profile_goals",
        "auth_session_profile_prompts",
    ),
)
def test_every_touched_table_is_independently_rejected_for_ambient_rls(
    drift_table,
):
    migration = importlib.import_module(
        "app.db.migrations.versions.0021_nyay5_profile_boundary"
    )
    names = migration._EXISTING_AUTHORITY_TABLES + migration._NEW_AUTHORITY_TABLES
    rows = [
        (name, "r", "p", name == drift_table, False)
        for name in names
    ]
    with pytest.raises(migration.Nyay5ProfileMigrationError):
        migration._validate_postgres_table_authority(
            _CatalogConnection(rows), names
        )
