"""Fail-closed lifecycle and exact-schema tests for NYAY-17 revision 0018."""
from __future__ import annotations

from copy import deepcopy
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError


BACKEND = Path(__file__).resolve().parents[1]
PARENT = "0017_registration_invariants"
HEAD = "0018_registration_idempotency"
OTP_HEAD = "0019_otp_security_authority"
NYAY5_CHECKPOINT = "0021_nyay5_profile_boundary"
NYAY9_CHECKPOINT = "0022_nyay9_owner_profile_api"
CURRENT_HEAD = "0024_nyay11_authority_state"
LEDGER = "registration_idempotency_records"
TEST_ENV = {
    "APP_ENV": "testing",
    "REGISTRATION_SECRET": "nyay17-test-encryption-authority-not-default",
    "REGISTRATION_LOOKUP_SECRET": "nyay17-test-lookup-authority-not-default",
    "REGISTRATION_KEY_VERSION": "v1",
}


def _module():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "app/db/migrations"))
    return ScriptDirectory.from_config(config).get_revision(HEAD).module


def _alembic(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env={
            **os.environ,
            **TEST_ENV,
            "DATABASE_URL": f"sqlite+pysqlite:///{database}",
        },
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _revision(database: Path) -> str:
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.connect() as connection:
            return str(
                connection.scalar(text("SELECT version_num FROM alembic_version"))
            )
    finally:
        engine.dispose()


def _seed_registration(database: Path, *, raw_key: str | None = None) -> dict[str, str]:
    ids = {
        "user": uuid.uuid4().hex,
        "registration": uuid.uuid4().hex,
        "profile": uuid.uuid4().hex,
    }
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, role, status) "
                    "VALUES (:id, 'student', 'pending')"
                ),
                {"id": ids["user"]},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO student_registrations (
                        id, user_id, first_name, last_name, mobile_hash,
                        mobile_ct, dob_hash, dob_ct, dob_hash_state,
                        key_version, status, is_minor, idempotency_key
                    ) VALUES (
                        :id, :user_id, 'NYAY17', 'Lifecycle', :mobile_hash,
                        'v1:mobile', :dob_hash, 'v1:dob', 'verified',
                        'v1', 'otp_pending', false, :raw_key
                    )
                    """
                ),
                {
                    "id": ids["registration"],
                    "user_id": ids["user"],
                    "mobile_hash": uuid.uuid4().hex * 2,
                    "dob_hash": uuid.uuid4().hex * 2,
                    "raw_key": raw_key,
                },
            )
            # Every pre-NYAY-5 live registration already owned exactly one
            # normalized profile.  Seed that valid historical invariant so
            # the later 0021 safety check is exercised by a representative
            # populated graph rather than an impossible orphan fixture.
            connection.execute(
                text(
                    "INSERT INTO student_profiles (id, registration_id) "
                    "VALUES (:id, :registration_id)"
                ),
                {
                    "id": ids["profile"],
                    "registration_id": ids["registration"],
                },
            )
    finally:
        engine.dispose()
    return ids


def _owned_inventory(database: Path) -> dict[str, object]:
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        inspector = inspect(engine)
        return {
            "tables": tuple(sorted(inspector.get_table_names())),
            "registration_columns": tuple(
                item["name"] for item in inspector.get_columns("student_registrations")
            ),
            "ledger_columns": tuple(
                item["name"] for item in inspector.get_columns(LEDGER)
            )
            if LEDGER in inspector.get_table_names()
            else (),
            "ledger_pk": inspector.get_pk_constraint(LEDGER)
            if LEDGER in inspector.get_table_names()
            else None,
            "ledger_uniques": tuple(
                sorted(
                    (item.get("name"), tuple(item.get("column_names") or ()))
                    for item in inspector.get_unique_constraints(LEDGER)
                )
            )
            if LEDGER in inspector.get_table_names()
            else (),
            "ledger_fks": tuple(
                sorted(
                    (
                        item.get("name"),
                        tuple(item.get("constrained_columns") or ()),
                        item.get("referred_table"),
                        tuple(item.get("referred_columns") or ()),
                        tuple(sorted((item.get("options") or {}).items())),
                    )
                    for item in inspector.get_foreign_keys(LEDGER)
                )
            )
            if LEDGER in inspector.get_table_names()
            else (),
            "ledger_checks": tuple(
                sorted(item.get("name") for item in inspector.get_check_constraints(LEDGER))
            )
            if LEDGER in inspector.get_table_names()
            else (),
        }
    finally:
        engine.dispose()


def _subject_projection(database: Path, ids: dict[str, str]) -> dict[str, tuple]:
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        inspector = inspect(engine)
        registration_columns = [
            item["name"]
            for item in inspector.get_columns("student_registrations")
            if item["name"] != "idempotency_key_legacy"
        ]
        user_columns = [item["name"] for item in inspector.get_columns("users")]
        with engine.connect() as connection:
            registration = tuple(
                connection.execute(
                    text(
                        "SELECT "
                        + ", ".join(f'"{name}"' for name in registration_columns)
                        + " FROM student_registrations WHERE id = :id"
                    ),
                    {"id": ids["registration"]},
                ).one()
            )
            user = tuple(
                connection.execute(
                    text(
                        "SELECT "
                        + ", ".join(f'"{name}"' for name in user_columns)
                        + " FROM users WHERE id = :id"
                    ),
                    {"id": ids["user"]},
                ).one()
            )
        return {"registration": registration, "user": user}
    finally:
        engine.dispose()


def _rows(database: Path, statement: str) -> tuple[tuple, ...]:
    with sqlite3.connect(database) as connection:
        return tuple(connection.execute(statement))


def test_revision_chain_is_single_forward_head():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "app/db/migrations"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(HEAD)
    assert revision is not None
    assert revision.down_revision == PARENT
    otp_head = scripts.get_revision(OTP_HEAD)
    assert otp_head is not None
    assert otp_head.down_revision == HEAD
    retention_head = scripts.get_revision("0020_auth_retention_lifecycle")
    assert retention_head is not None
    assert retention_head.down_revision == OTP_HEAD
    nyay5_checkpoint = scripts.get_revision(NYAY5_CHECKPOINT)
    assert nyay5_checkpoint is not None
    assert nyay5_checkpoint.down_revision == retention_head.revision
    nyay9_checkpoint = scripts.get_revision(NYAY9_CHECKPOINT)
    assert nyay9_checkpoint is not None
    assert nyay9_checkpoint.down_revision == nyay5_checkpoint.revision
    nyay22_checkpoint = scripts.get_revision("0023_nyay22_mentor_ceremony")
    assert nyay22_checkpoint is not None
    assert nyay22_checkpoint.down_revision == nyay9_checkpoint.revision
    current = scripts.get_revision(CURRENT_HEAD)
    assert current is not None
    assert current.down_revision == nyay22_checkpoint.revision
    assert scripts.get_heads() == [CURRENT_HEAD]


def test_clean_populated_no_key_roundtrip_and_alembic_check(tmp_path: Path):
    database = tmp_path / "roundtrip.sqlite"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    ids = _seed_registration(database)
    original_subject = _subject_projection(database, ids)

    assert _alembic(database, "upgrade", HEAD).returncode == 0
    assert _subject_projection(database, ids) == original_subject
    first_inventory = _owned_inventory(database)
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT idempotency_key_legacy FROM student_registrations "
                "WHERE id = :id"
            ),
            {"id": ids["registration"]},
        ) in (False, 0)
        assert connection.scalar(text(f"SELECT count(*) FROM {LEDGER}")) == 0
        _module()._validate_head_schema(connection)
    engine.dispose()

    assert _alembic(database, "downgrade", PARENT).returncode == 0
    assert _revision(database) == PARENT
    assert _subject_projection(database, ids) == original_subject
    assert _alembic(database, "upgrade", HEAD).returncode == 0
    assert _subject_projection(database, ids) == original_subject
    assert _owned_inventory(database) == first_inventory
    # Alembic ``check`` is defined at the repository's current forward head;
    # the assertions above still isolate 0018's own round-trip bytes.
    assert _alembic(database, "upgrade", CURRENT_HEAD).returncode == 0
    check = _alembic(database, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    assert "No new upgrade operations detected" in check.stdout + check.stderr


def test_legacy_marker_rejects_old_writer_and_blocks_downgrade_without_ddl(
    tmp_path: Path,
):
    database = tmp_path / "legacy.sqlite"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    ids = _seed_registration(database, raw_key="legacy-exact-key")
    assert _alembic(database, "upgrade", HEAD).returncode == 0
    before = _owned_inventory(database)

    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT idempotency_key, idempotency_key_legacy "
                "FROM student_registrations WHERE id = :id"
            ),
            {"id": ids["registration"]},
        ).one()
        assert tuple(row) == ("legacy-exact-key", 1)
    with pytest.raises(DBAPIError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO student_registrations (
                        id, user_id, first_name, last_name, mobile_hash,
                        mobile_ct, dob_hash, dob_ct, dob_hash_state,
                        key_version, status, is_minor, idempotency_key
                    ) VALUES (
                        :id, :user_id, 'Old', 'Writer', :mobile_hash,
                        'v1:mobile', :dob_hash, 'v1:dob', 'verified',
                        'v1', 'otp_pending', false, 'post-0018-raw-key'
                    )
                    """
                ),
                {
                    "id": uuid.uuid4().hex,
                    "user_id": ids["user"],
                    "mobile_hash": uuid.uuid4().hex * 2,
                    "dob_hash": uuid.uuid4().hex * 2,
                },
            )
    engine.dispose()
    legacy_row_before = _rows(
        database,
        "SELECT * FROM student_registrations WHERE idempotency_key = "
        "'legacy-exact-key'",
    )

    rejected = _alembic(database, "downgrade", PARENT)
    assert rejected.returncode != 0
    assert _revision(database) == HEAD
    assert _owned_inventory(database) == before
    assert _rows(
        database,
        "SELECT * FROM student_registrations WHERE idempotency_key = "
        "'legacy-exact-key'",
    ) == legacy_row_before


def test_ledger_tombstone_blocks_downgrade_without_partial_ddl(tmp_path: Path):
    database = tmp_path / "ledger.sqlite"
    assert _alembic(database, "upgrade", HEAD).returncode == 0
    before = _owned_inventory(database)
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                f"""
                INSERT INTO {LEDGER} (
                    id, idempotency_key_hash, state, outcome_code
                ) VALUES (
                    :id, :key_hash, 'erased', 'registration_replay_expired'
                )
                """
            ),
            {"id": uuid.uuid4().hex, "key_hash": "a" * 64},
        )
    engine.dispose()
    tombstone_before = _rows(database, f"SELECT * FROM {LEDGER}")

    rejected = _alembic(database, "downgrade", PARENT)
    assert rejected.returncode != 0
    assert _revision(database) == HEAD
    assert _owned_inventory(database) == before
    assert _rows(database, f"SELECT * FROM {LEDGER}") == tombstone_before


@pytest.mark.parametrize("direction", ("upgrade", "downgrade"))
def test_sqlite_mid_batch_failure_is_atomic_and_retryable(
    tmp_path: Path, direction: str
):
    database = tmp_path / f"atomic-{direction}.sqlite"
    target = PARENT if direction == "upgrade" else HEAD
    assert _alembic(database, "upgrade", target).returncode == 0
    column = "idempotency_key" if direction == "upgrade" else "idempotency_key_legacy"
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"CREATE VIEW nyay17_probe_view AS SELECT {column} "
            "FROM student_registrations"
        )
        before = tuple(connection.iterdump())

    command = ("upgrade", HEAD) if direction == "upgrade" else ("downgrade", PARENT)
    failed = _alembic(database, *command)
    assert failed.returncode != 0
    with sqlite3.connect(database) as connection:
        assert tuple(connection.iterdump()) == before
    assert _revision(database) == target

    with sqlite3.connect(database) as connection:
        connection.execute("DROP VIEW nyay17_probe_view")
    retried = _alembic(database, *command)
    assert retried.returncode == 0, retried.stdout + retried.stderr


def test_check_parser_preserves_literals_and_boolean_grouping():
    module = _module()
    reflected = (
        "CHECK (((state)::text = ANY ((ARRAY['pending'::character varying, "
        "'succeeded'::character varying, 'failed'::character varying, "
        "'retired'::character varying, 'erased'::character varying])::text[])))"
    )
    assert module._canonical_check(reflected) == module._canonical_check(
        module._STATE_SQL
    )
    assert module._canonical_check("state IN ('PENDING')") != module._canonical_check(
        "state IN ('pending')"
    )
    expected = "a AND (b OR c) AND d"
    hostile = "(a AND b) OR (c AND d)"
    assert module._canonical_check(expected) != module._canonical_check(hostile)


def test_uuid_type_oracle_is_dialect_exact():
    module = _module()

    class _PostgresBind:
        class _Dialect:
            name = "postgresql"

        dialect = _Dialect()

    assert module._uuid_column_is_exact(
        _PostgresBind(), {"type": postgresql.UUID()}
    )
    assert not module._uuid_column_is_exact(
        _PostgresBind(), {"type": sa.CHAR(32)}
    )
    assert module._uuid_column_is_exact(_FakeBind(), {"type": sa.CHAR(32)})


class _FakeInspector:
    def __init__(self, inventory: dict[str, object]) -> None:
        self.inventory = inventory

    def get_table_names(self):
        return ["student_registrations", LEDGER]

    def get_columns(self, table):
        return deepcopy(self.inventory["columns"][table])

    def get_pk_constraint(self, table):
        return deepcopy(self.inventory["pk"])

    def get_unique_constraints(self, table):
        return deepcopy(self.inventory["uniques"][table])

    def get_foreign_keys(self, table):
        return deepcopy(self.inventory["foreign_keys"])

    def get_check_constraints(self, table):
        return deepcopy(self.inventory["checks"][table])


class _FakeBind:
    class _Dialect:
        name = "sqlite"

    dialect = _Dialect()

    def scalar(self, *_args, **_kwargs):
        raise AssertionError("unsafe schema reached downgrade data/DDL phase")


def _good_fake_inventory(module) -> dict[str, object]:
    columns = [
        {"name": "id", "type": sa.Uuid(), "nullable": False, "default": None},
        {"name": "idempotency_key_hash", "type": sa.VARCHAR(64), "nullable": False, "default": None},
        {"name": "request_fingerprint", "type": sa.VARCHAR(64), "nullable": True, "default": None},
        {"name": "request_fingerprint_version", "type": sa.VARCHAR(16), "nullable": True, "default": None},
        {"name": "state", "type": sa.VARCHAR(24), "nullable": False, "default": None},
        {"name": "outcome_code", "type": sa.VARCHAR(40), "nullable": True, "default": None},
        {"name": "registration_id", "type": sa.Uuid(), "nullable": True, "default": None},
        {"name": "outbox_id", "type": sa.Uuid(), "nullable": True, "default": None},
        {"name": "created_at", "type": sa.DateTime(timezone=True), "nullable": False, "default": "CURRENT_TIMESTAMP"},
        {"name": "updated_at", "type": sa.DateTime(timezone=True), "nullable": False, "default": "CURRENT_TIMESTAMP"},
    ]
    return {
        "columns": {
            "student_registrations": [
                {"name": "idempotency_key", "type": sa.VARCHAR(200), "nullable": True, "default": None},
                {"name": "idempotency_key_legacy", "type": sa.Boolean(), "nullable": False, "default": "0"},
            ],
            LEDGER: columns,
        },
        "pk": {"name": "pk_registration_idempotency_records", "constrained_columns": ["id"]},
        "uniques": {
            "student_registrations": [
                {"name": module._IDEMPOTENCY_UNIQUE, "column_names": ["idempotency_key"]}
            ],
            LEDGER: [
                {"name": "uq_registration_idempotency_records_idempotency_key_hash", "column_names": ["idempotency_key_hash"]},
                {"name": "uq_registration_idempotency_records_registration_id", "column_names": ["registration_id"]},
                {"name": "uq_registration_idempotency_records_outbox_id", "column_names": ["outbox_id"]},
            ],
        },
        "foreign_keys": [
            {"name": "fk_reg_idem_registration", "constrained_columns": ["registration_id"], "referred_table": "student_registrations", "referred_columns": ["id"], "options": {"ondelete": "SET NULL"}},
            {"name": "fk_reg_idem_outbox", "constrained_columns": ["outbox_id"], "referred_table": "otp_outbox", "referred_columns": ["id"], "options": {"ondelete": "SET NULL"}},
        ],
        "checks": {
            "student_registrations": [
                {"name": module._LEGACY_CHECK, "sqltext": module._LEGACY_SQL}
            ],
            LEDGER: [
                {"name": "ck_registration_idempotency_records_state", "sqltext": module._STATE_SQL},
                {"name": "ck_registration_idempotency_records_key_hash_shape", "sqltext": module._KEY_HASH_SQL},
                {"name": "ck_registration_idempotency_records_request_fingerprint_shape", "sqltext": module._REQUEST_HASH_SQL},
                {"name": "ck_registration_idempotency_records_state_links", "sqltext": module._STATE_LINKS_SQL},
            ],
        },
    }


def _column(inventory, name):
    return next(
        item for item in inventory["columns"][LEDGER] if item["name"] == name
    )


def _mutate(inventory: dict[str, object], mutation: str) -> None:
    if mutation == "pk":
        inventory["pk"]["constrained_columns"] = ["idempotency_key_hash"]
    elif mutation == "unique":
        inventory["uniques"][LEDGER][0]["column_names"] = ["request_fingerprint"]
    elif mutation == "unnamed_unique":
        inventory["uniques"][LEDGER].append(
            {"name": None, "column_names": ["state"]}
        )
    elif mutation == "fk":
        inventory["foreign_keys"][0]["referred_table"] = "users"
    elif mutation == "ondelete":
        inventory["foreign_keys"][0]["options"] = {"ondelete": "CASCADE"}
    elif mutation == "unnamed_fk":
        inventory["foreign_keys"].append(
            {"name": None, "constrained_columns": ["registration_id"], "referred_table": "student_registrations", "referred_columns": ["id"], "options": {"ondelete": "SET NULL"}}
        )
    elif mutation == "check_literal":
        inventory["checks"][LEDGER][0]["sqltext"] = module_for_mutants._STATE_SQL.replace("'pending'", "'PENDING'")
    elif mutation == "check_parentheses":
        inventory["checks"][LEDGER][3]["sqltext"] = "state = 'pending' AND (registration_id IS NOT NULL OR outbox_id IS NOT NULL) AND outcome_code IS NULL"
    elif mutation == "unnamed_check":
        inventory["checks"][LEDGER].append({"name": None, "sqltext": "state IS NOT NULL"})
    elif mutation == "default":
        _column(inventory, "idempotency_key_hash")["default"] = "'unsafe'"
    elif mutation == "timestamp_default":
        _column(inventory, "created_at")["default"] = "clock_timestamp()"
    elif mutation == "nullable":
        _column(inventory, "state")["nullable"] = True
    elif mutation == "type":
        _column(inventory, "idempotency_key_hash")["type"] = sa.CHAR(64)
    elif mutation == "historical_default":
        inventory["columns"]["student_registrations"][0]["default"] = "'raw'"
    else:  # pragma: no cover - test table is exhaustive
        raise AssertionError(mutation)


module_for_mutants = _module()


@pytest.mark.parametrize(
    "mutation",
    (
        "pk",
        "unique",
        "unnamed_unique",
        "fk",
        "ondelete",
        "unnamed_fk",
        "check_literal",
        "check_parentheses",
        "unnamed_check",
        "default",
        "timestamp_default",
        "nullable",
        "type",
        "historical_default",
    ),
)
def test_hostile_head_schema_rejects_before_data_or_ddl(monkeypatch, mutation):
    module = _module()
    inventory = _good_fake_inventory(module)
    fake = _FakeInspector(inventory)
    bind = _FakeBind()
    monkeypatch.setattr(module.sa, "inspect", lambda _bind: fake)
    # Positive control: the same fake reaches and passes the exact validator.
    module._validate_head_schema(bind)

    _mutate(inventory, mutation)

    with pytest.raises(module.RegistrationIdempotencyMigrationError):
        module._validate_head_schema(bind)
