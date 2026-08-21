"""Fail-closed lifecycle contract for NYAY-3 migration 0017.

SQLite is used here only to prove deterministic Alembic lifecycle, schema
inventory, and row preservation.  PostgreSQL 16 remains the authority for the
concurrency claims exercised by the opt-in NYAY-3 characterization gate.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


BACKEND = Path(__file__).resolve().parents[1]
PARENT = "0016_dob_hash_reconcile"
HEAD = "0017_registration_invariants"
GENERIC_REJECTION = (
    "NYAY-3 registration invariant preflight rejected ambiguous schema or data"
)
TARGET_OBJECTS = frozenset(
    {
        "uq_otp_challenges_one_active_per_registration_purpose",
        "uq_auth_sessions_one_active_per_user",
        "uq_guardian_consents_registration_id",
        "uq_student_verifications_registration_id",
        "ck_guardian_consents_verified_matches_status",
    }
)
TABLES = (
    "users",
    "student_registrations",
    "otp_challenges",
    "auth_sessions",
    "guardian_consents",
    "student_verifications",
)
TEST_ENV = {
    "APP_ENV": "testing",
    "REGISTRATION_SECRET": "nyay3-test-encryption-authority-not-default",
    "REGISTRATION_LOOKUP_SECRET": "nyay3-test-lookup-authority-not-default",
    "REGISTRATION_KEY_VERSION": "v1",
}


def _module():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "app/db/migrations"))
    return ScriptDirectory.from_config(config).get_revision(HEAD).module


def test_postgresql_reflected_partial_predicate_casts_are_canonicalized():
    module = _module()
    expected = module._normalise_sql("status = 'active'")
    assert module._normalise_sql("((status)::text = 'active'::text)") == expected
    assert (
        module._normalise_sql("status::varchar(32) = 'active'::character varying")
        == expected
    )
    assert module._normalise_sql("status = 'active' OR revoked_at IS NULL") != expected
    assert module._normalise_sql("status = 'active::text'") != expected
    assert module._normalise_sql("status = 'active '") != expected
    assert module._normalise_sql("status = 'ACTIVE'") != expected
    assert module._normalise_sql("status = 'active()'") != expected
    assert module._normalise_sql("status = 'act''ive'") != expected


def test_guardian_check_reflection_requires_exact_semantics():
    module = _module()
    expected = module._normalise_check_sql(module._GUARDIAN_STATE_SQL)
    reflected = (
        "CHECK (status::text = 'verified'::text AND verified = true OR "
        "status::text = ANY (ARRAY['pending'::character varying, "
        "'sent'::character varying, 'rejected'::character varying]::text[]) "
        "AND verified = false)"
    )
    assert module._normalise_check_sql(reflected) == expected
    assert (
        module._normalise_check_sql(reflected + " OR verified = true")
        != expected
    )


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
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def _seed_clean(database: Path) -> dict[str, str]:
    ids = {
        "user": uuid.uuid4().hex,
        "registration": uuid.uuid4().hex,
        "otp": uuid.uuid4().hex,
        "session": uuid.uuid4().hex,
        "guardian": uuid.uuid4().hex,
        "verification": uuid.uuid4().hex,
    }
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users (id, role, status) VALUES (:id, 'student', 'active')"),
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
                        :id, :user_id, 'NYAY3', 'Lifecycle', :mobile_hash,
                        'v1:mobile-ciphertext', :dob_hash, 'v1:dob-ciphertext',
                        'verified', 'v1', 'active', false, :idempotency_key
                    )
                    """
                ),
                {
                    "id": ids["registration"],
                    "user_id": ids["user"],
                    "mobile_hash": "a" * 64,
                    "dob_hash": "b" * 64,
                    "idempotency_key": f"nyay3-{ids['registration']}",
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO otp_challenges (
                        id, registration_id, purpose, verifier_hash, attempts,
                        max_attempts, expires_at
                    ) VALUES (
                        :id, :registration_id, 'login', :verifier_hash, 0, 3,
                        '2030-01-01 00:00:00+00:00'
                    )
                    """
                ),
                {
                    "id": ids["otp"],
                    "registration_id": ids["registration"],
                    "verifier_hash": "c" * 64,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO auth_sessions (
                        id, user_id, token_hash, status, expires_at, last_seen_at
                    ) VALUES (
                        :id, :user_id, :token_hash, 'active',
                        '2030-01-01 00:00:00+00:00',
                        '2026-08-20 00:00:00+00:00'
                    )
                    """
                ),
                {
                    "id": ids["session"],
                    "user_id": ids["user"],
                    "token_hash": "d" * 64,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO guardian_consents (
                        id, registration_id, status, verified
                    ) VALUES (:id, :registration_id, 'pending', false)
                    """
                ),
                {"id": ids["guardian"], "registration_id": ids["registration"]},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO student_verifications (
                        id, registration_id, method, status
                    ) VALUES (
                        :id, :registration_id, 'institutional_email', 'pending'
                    )
                    """
                ),
                {
                    "id": ids["verification"],
                    "registration_id": ids["registration"],
                },
            )
    finally:
        engine.dispose()
    return ids


def _snapshot(database: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    with sqlite3.connect(database) as connection:
        return {
            table: tuple(connection.execute(f'SELECT * FROM "{table}" ORDER BY id'))
            for table in TABLES
        }


def _inventory(database: Path) -> dict[str, dict[str, object]]:
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        inspector = inspect(engine)
        indexes = {
            item["name"]: {
                "table": table,
                "columns": tuple(item["column_names"]),
                "unique": bool(item["unique"]),
            }
            for table in ("otp_challenges", "auth_sessions")
            for item in inspector.get_indexes(table)
            if item["name"] in TARGET_OBJECTS
        }
        uniques = {
            item["name"]: {
                "table": table,
                "columns": tuple(item["column_names"]),
            }
            for table in ("guardian_consents", "student_verifications")
            for item in inspector.get_unique_constraints(table)
            if item["name"] in TARGET_OBJECTS
        }
        checks = {
            item["name"]: {
                "table": "guardian_consents",
                "sqltext": " ".join(str(item["sqltext"]).split()).casefold(),
            }
            for item in inspector.get_check_constraints("guardian_consents")
            if item["name"] in TARGET_OBJECTS
        }
        with engine.connect() as connection:
            index_sql = {
                row.name: " ".join(str(row.sql).split()).casefold()
                for row in connection.execute(
                    text(
                        "SELECT name, sql FROM sqlite_master "
                        "WHERE type='index' AND name IN "
                        "('uq_otp_challenges_one_active_per_registration_purpose', "
                        "'uq_auth_sessions_one_active_per_user')"
                    )
                )
            }
        for name, sql in index_sql.items():
            indexes[name]["sql"] = sql
        return {"indexes": indexes, "uniques": uniques, "checks": checks}
    finally:
        engine.dispose()


def _target_names(inventory: dict[str, dict[str, object]]) -> set[str]:
    return set().union(*(set(section) for section in inventory.values()))


def _assert_exact_inventory(database: Path) -> dict[str, dict[str, object]]:
    inventory = _inventory(database)
    assert _target_names(inventory) == TARGET_OBJECTS
    assert inventory["indexes"][
        "uq_otp_challenges_one_active_per_registration_purpose"
    ]["columns"] == ("registration_id", "purpose")
    assert inventory["indexes"][
        "uq_otp_challenges_one_active_per_registration_purpose"
    ]["unique"] is True
    assert "where consumed_at is null" in inventory["indexes"][
        "uq_otp_challenges_one_active_per_registration_purpose"
    ]["sql"]
    assert inventory["indexes"]["uq_auth_sessions_one_active_per_user"][
        "columns"
    ] == ("user_id",)
    assert inventory["indexes"]["uq_auth_sessions_one_active_per_user"][
        "unique"
    ] is True
    assert "where status = 'active'" in inventory["indexes"][
        "uq_auth_sessions_one_active_per_user"
    ]["sql"]
    assert inventory["uniques"]["uq_guardian_consents_registration_id"][
        "columns"
    ] == ("registration_id",)
    assert inventory["uniques"]["uq_student_verifications_registration_id"][
        "columns"
    ] == ("registration_id",)
    check_sql = inventory["checks"][
        "ck_guardian_consents_verified_matches_status"
    ]["sqltext"]
    assert "status = 'verified'" in check_sql
    assert all(value in check_sql for value in ("'pending'", "'sent'", "'rejected'"))
    return inventory


def _plant_conflict(database: Path, ids: dict[str, str], conflict: str) -> None:
    extra_id = uuid.uuid4().hex
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.begin() as connection:
            if conflict == "otp":
                connection.execute(
                    text(
                        """
                        INSERT INTO otp_challenges (
                            id, registration_id, purpose, verifier_hash,
                            attempts, max_attempts, expires_at
                        ) VALUES (
                            :id, :registration_id, 'login', :verifier_hash,
                            0, 3, '2030-01-01 00:00:00+00:00'
                        )
                        """
                    ),
                    {
                        "id": extra_id,
                        "registration_id": ids["registration"],
                        "verifier_hash": "e" * 64,
                    },
                )
            elif conflict == "session":
                connection.execute(
                    text(
                        """
                        INSERT INTO auth_sessions (
                            id, user_id, token_hash, status,
                            expires_at, last_seen_at
                        ) VALUES (
                            :id, :user_id, :token_hash, 'active',
                            '2030-01-01 00:00:00+00:00',
                            '2026-08-20 00:00:00+00:00'
                        )
                        """
                    ),
                    {
                        "id": extra_id,
                        "user_id": ids["user"],
                        "token_hash": "f" * 64,
                    },
                )
            elif conflict == "guardian":
                connection.execute(
                    text(
                        "INSERT INTO guardian_consents "
                        "(id, registration_id, status, verified) "
                        "VALUES (:id, :registration_id, 'sent', false)"
                    ),
                    {"id": extra_id, "registration_id": ids["registration"]},
                )
            elif conflict == "verification":
                connection.execute(
                    text(
                        "INSERT INTO student_verifications "
                        "(id, registration_id, method, status) "
                        "VALUES (:id, :registration_id, 'manual', 'in_review')"
                    ),
                    {"id": extra_id, "registration_id": ids["registration"]},
                )
            elif conflict == "guardian_verified_false":
                connection.execute(
                    text(
                        "UPDATE guardian_consents "
                        "SET status='verified', verified=false WHERE id=:id"
                    ),
                    {"id": ids["guardian"]},
                )
            elif conflict == "guardian_pending_true":
                connection.execute(
                    text(
                        "UPDATE guardian_consents "
                        "SET status='pending', verified=true WHERE id=:id"
                    ),
                    {"id": ids["guardian"]},
                )
            else:  # pragma: no cover - test programming error
                raise AssertionError(conflict)
    finally:
        engine.dispose()


def _assert_sanitized_rejection(
    result: subprocess.CompletedProcess[str], ids: dict[str, str]
) -> None:
    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert GENERIC_REJECTION in output
    assert all(value not in output for value in ids.values())
    assert "v1:mobile-ciphertext" not in output
    assert "v1:dob-ciphertext" not in output


def test_revision_metadata_and_public_error_contract():
    module = _module()
    assert module.revision == HEAD
    assert module.down_revision == PARENT
    assert issubclass(module.RegistrationInvariantPreflightError, RuntimeError)
    assert str(module.RegistrationInvariantPreflightError(GENERIC_REJECTION)) == (
        GENERIC_REJECTION
    )


def test_clean_populated_upgrade_downgrade_reupgrade_is_lossless(tmp_path):
    database = tmp_path / "nyay3-clean-lifecycle.db"
    parent = _alembic(database, "upgrade", PARENT)
    assert parent.returncode == 0, parent.stderr[-3000:]
    ids = _seed_clean(database)
    before = _snapshot(database)

    upgraded = _alembic(database, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stderr[-3000:]
    assert _revision(database) == HEAD
    first_inventory = _assert_exact_inventory(database)
    assert _snapshot(database) == before

    downgraded = _alembic(database, "downgrade", PARENT)
    assert downgraded.returncode == 0, downgraded.stderr[-3000:]
    assert _revision(database) == PARENT
    assert _target_names(_inventory(database)) == set()
    assert _snapshot(database) == before

    reupgraded = _alembic(database, "upgrade", HEAD)
    assert reupgraded.returncode == 0, reupgraded.stderr[-3000:]
    assert _revision(database) == HEAD
    assert _assert_exact_inventory(database) == first_inventory
    assert _snapshot(database) == before
    assert all(value for value in ids.values())  # preserve fixture authority


def test_historical_revision_is_not_repository_head():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option(
        "script_location", str(BACKEND / "app/db/migrations")
    )
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0019_otp_security_authority"
    assert HEAD != script.get_current_head()
    assert script.get_revision(HEAD).down_revision == PARENT


@pytest.mark.parametrize(
    "conflict",
    (
        "otp",
        "session",
        "guardian",
        "verification",
        "guardian_verified_false",
        "guardian_pending_true",
    ),
)
def test_dirty_upgrade_rejects_before_any_target_ddl_and_preserves_rows(
    tmp_path, conflict
):
    database = tmp_path / f"nyay3-dirty-{conflict}.db"
    parent = _alembic(database, "upgrade", PARENT)
    assert parent.returncode == 0, parent.stderr[-3000:]
    ids = _seed_clean(database)
    _plant_conflict(database, ids, conflict)
    before = _snapshot(database)

    rejected = _alembic(database, "upgrade", HEAD)
    _assert_sanitized_rejection(rejected, ids)
    assert _revision(database) == PARENT
    assert _snapshot(database) == before
    assert _target_names(_inventory(database)) == set()


def test_constraints_reject_all_five_hostile_writes_at_head(tmp_path):
    database = tmp_path / "nyay3-hostile-writes.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    ids = _seed_clean(database)
    upgraded = _alembic(database, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stderr[-3000:]
    _assert_exact_inventory(database)

    statements = (
        (
            "INSERT INTO otp_challenges "
            "(id,registration_id,purpose,verifier_hash,attempts,max_attempts,expires_at) "
            "VALUES (:id,:registration_id,'login',:digest,0,3,'2030-01-02')",
            {"id": uuid.uuid4().hex, "registration_id": ids["registration"], "digest": "1" * 64},
        ),
        (
            "INSERT INTO auth_sessions "
            "(id,user_id,token_hash,status,expires_at,last_seen_at) "
            "VALUES (:id,:user_id,:digest,'active','2030-01-02','2026-08-20')",
            {"id": uuid.uuid4().hex, "user_id": ids["user"], "digest": "2" * 64},
        ),
        (
            "INSERT INTO guardian_consents (id,registration_id,status,verified) "
            "VALUES (:id,:registration_id,'pending',false)",
            {"id": uuid.uuid4().hex, "registration_id": ids["registration"]},
        ),
        (
            "INSERT INTO student_verifications (id,registration_id,method,status) "
            "VALUES (:id,:registration_id,'manual','pending')",
            {"id": uuid.uuid4().hex, "registration_id": ids["registration"]},
        ),
        (
            "UPDATE guardian_consents SET status='verified', verified=false "
            "WHERE id=:id",
            {"id": ids["guardian"]},
        ),
    )
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        for statement, parameters in statements:
            with pytest.raises(Exception) as caught:
                with engine.begin() as connection:
                    connection.execute(text(statement), parameters)
            assert "IntegrityError" in type(caught.value).__name__
    finally:
        engine.dispose()


@pytest.mark.parametrize("mutation", ("missing", "wrong_predicate"))
def test_downgrade_rejects_hostile_index_inventory_without_partial_drop(
    tmp_path, mutation
):
    database = tmp_path / f"nyay3-hostile-downgrade-{mutation}.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    ids = _seed_clean(database)
    assert _alembic(database, "upgrade", HEAD).returncode == 0
    before = _snapshot(database)

    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX uq_auth_sessions_one_active_per_user")
        if mutation == "wrong_predicate":
            connection.execute(
                "CREATE UNIQUE INDEX uq_auth_sessions_one_active_per_user "
                "ON auth_sessions (user_id) WHERE status = 'revoked'"
            )

    planted = _inventory(database)
    rejected = _alembic(database, "downgrade", PARENT)
    _assert_sanitized_rejection(rejected, ids)
    assert _revision(database) == HEAD
    assert _snapshot(database) == before
    assert _inventory(database) == planted
    # Proves validation happened before the first reverse-order target drop.
    remaining = _target_names(_inventory(database))
    assert "uq_otp_challenges_one_active_per_registration_purpose" in remaining
    assert "uq_guardian_consents_registration_id" in remaining
    assert "uq_student_verifications_registration_id" in remaining
    assert "ck_guardian_consents_verified_matches_status" in remaining
