"""Executable 0019 -> 0020 NYAY-19 migration lifecycle proof."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import uuid
from copy import deepcopy
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[1]
PARENT = "0019_otp_security_authority"
HEAD = "0020_auth_retention_lifecycle"
CURRENT_HEAD = "0022_nyay9_owner_profile_api"


def _alembic(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{database}"},
        capture_output=True,
        text=True,
    )


def _seed_0019(database: Path) -> tuple[str, str, str]:
    user_id = uuid.uuid4().hex
    attempt_id = uuid.uuid4().hex
    session_id = uuid.uuid4().hex
    instant = "2026-01-01 00:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users "
            "(id, role, status, created_at, updated_at, deleted_at, metadata_json) "
            "VALUES (?, 'student', 'active', ?, ?, NULL, NULL)",
            (user_id, instant, instant),
        )
        connection.execute(
            "INSERT INTO login_attempts "
            "(id, opaque_id, lookup_hash, registration_id, challenge_id, status, "
            "expires_at, consumed_at, created_at, updated_at, deleted_at, metadata_json) "
            "VALUES (?, ?, ?, NULL, NULL, 'expired', ?, NULL, ?, ?, NULL, NULL)",
            (attempt_id, uuid.uuid4().hex, "a" * 64, instant, instant, instant),
        )
        connection.execute(
            "INSERT INTO auth_sessions "
            "(id, user_id, token_hash, status, expires_at, last_seen_at, revoked_at, "
            "created_at, updated_at, deleted_at, metadata_json) "
            "VALUES (?, ?, ?, 'revoked', ?, ?, NULL, ?, ?, NULL, NULL)",
            (session_id, user_id, "b" * 64, instant, instant, instant, instant),
        )
        connection.commit()
    return user_id, attempt_id, session_id


def _seed_legacy_delete_graph(
    database: Path,
    *,
    role: str = "student",
    registrations: int = 1,
    confirmation_hash: str | None = "c" * 64,
    deletion_jobs: int = 1,
) -> tuple[str, tuple[str, ...]]:
    user_id = uuid.uuid4().hex
    request_id = uuid.uuid4().hex
    session_ids = (uuid.uuid4().hex, uuid.uuid4().hex)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (id, role, status) VALUES (?, ?, 'active')",
            (user_id, role),
        )
        for index in range(registrations):
            connection.execute(
                "INSERT INTO student_registrations "
                "(id, user_id, first_name, last_name, mobile_hash, mobile_ct, "
                "dob_hash, dob_ct, dob_hash_state, key_version, status, is_minor, "
                "idempotency_key) VALUES (?, ?, 'Legacy', 'Delete', ?, ?, ?, ?, "
                "'verified', 'v1', 'active', false, ?)",
                (
                    uuid.uuid4().hex,
                    user_id,
                    f"{index + 1:064x}",
                    f"v1:mobile-{index}",
                    f"{index + 101:064x}",
                    f"v1:dob-{index}",
                    None,
                ),
            )
        connection.execute(
            "INSERT INTO data_subject_requests "
            "(id, user_id, kind, opaque_id, status, idempotency_key, "
            "reauth_verified, confirmation_hash) "
            "VALUES (?, ?, 'delete', ?, 'pending', ?, true, ?)",
            (
                request_id,
                user_id,
                uuid.uuid4().hex,
                f"legacy-dsr-{request_id}",
                confirmation_hash,
            ),
        )
        for _ in range(deletion_jobs):
            connection.execute(
                "INSERT INTO deletion_jobs (id, request_id, status, mode) "
                "VALUES (?, ?, 'pending', 'anonymise')",
                (uuid.uuid4().hex, request_id),
            )
        connection.execute(
            "INSERT INTO auth_sessions "
            "(id, user_id, token_hash, status, expires_at, last_seen_at, revoked_at) "
            "VALUES (?, ?, ?, 'active', ?, ?, NULL)",
            (
                session_ids[0],
                user_id,
                "d" * 64,
                "2030-01-01 00:00:00+00:00",
                "2026-01-01 00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO auth_sessions "
            "(id, user_id, token_hash, status, expires_at, last_seen_at, revoked_at) "
            "VALUES (?, ?, ?, 'expired', ?, ?, NULL)",
            (
                session_ids[1],
                user_id,
                "e" * 64,
                "2025-01-01 00:00:00+00:00",
                "2025-01-01 00:00:00+00:00",
            ),
        )
        connection.commit()
    return user_id, session_ids


def _schema(database: Path) -> tuple[tuple[str, str | None], ...]:
    with sqlite3.connect(database) as connection:
        return tuple(
            connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type IN ('table','index','trigger') AND name NOT LIKE 'sqlite_%' "
                "ORDER BY type, name"
            )
        )


def _legacy_delete_state(database: Path, user_id: str) -> tuple[object, ...]:
    """Return a deterministic, privacy-safe before/after migration digest."""

    with sqlite3.connect(database) as connection:
        return (
            connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone(),
            connection.execute(
                "SELECT role, status, updated_at FROM users WHERE id=?", (user_id,)
            ).fetchone(),
            connection.execute(
                "SELECT status, updated_at FROM student_registrations "
                "WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall(),
            connection.execute(
                "SELECT status, confirmation_hash FROM data_subject_requests "
                "WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall(),
            connection.execute(
                "SELECT job.status, job.mode FROM deletion_jobs AS job "
                "JOIN data_subject_requests AS request ON request.id=job.request_id "
                "WHERE request.user_id=? ORDER BY job.id",
                (user_id,),
            ).fetchall(),
            connection.execute(
                "SELECT status, revoked_at, updated_at FROM auth_sessions "
                "WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall(),
            connection.execute(
                "SELECT count(*) FROM audit_events WHERE "
                "action='student.auth.deletion_backfill_frozen'"
            ).fetchone(),
        )


def _rewrite_table_sql(
    database: Path,
    *,
    table: str,
    old: str,
    new: str,
) -> None:
    with sqlite3.connect(database) as connection:
        original = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
        assert old in original
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute(
            "UPDATE sqlite_master SET sql=? WHERE type='table' AND name=?",
            (original.replace(old, new, 1), table),
        )
        schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
        connection.execute(f"PRAGMA schema_version={schema_version + 1}")
        connection.execute("PRAGMA writable_schema=OFF")
        connection.commit()


def _append_table_constraint(
    database: Path,
    *,
    table: str,
    constraint: str,
) -> None:
    with sqlite3.connect(database) as connection:
        original = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()[0]
        prefix, closing, suffix = original.rpartition(")")
        assert closing == ")" and not suffix.strip()
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute(
            "UPDATE sqlite_master SET sql=? WHERE type='table' AND name=?",
            (f"{prefix}, {constraint})", table),
        )
        schema_version = connection.execute("PRAGMA schema_version").fetchone()[0]
        connection.execute(f"PRAGMA schema_version={schema_version + 1}")
        connection.execute("PRAGMA writable_schema=OFF")
        connection.commit()


def _pg_catalog_fixture() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    def constraint(
        table: str,
        name: str,
        kind: str,
        *,
        backing_index: str | None = None,
        delete_action: str | None = None,
    ) -> dict[str, object]:
        return {
            "table_name": table,
            "conname": name,
            "contype": kind,
            "convalidated": True,
            "condeferrable": False,
            "condeferred": False,
            "connoinherit": True,
            "confupdtype": "a" if kind == "f" else None,
            "confdeltype": delete_action,
            "confmatchtype": "s" if kind == "f" else None,
            "backing_index": backing_index,
        }

    def index(
        table: str,
        name: str,
        columns: list[str],
        *,
        unique: bool = False,
        primary: bool = False,
        predicate: str | None = None,
    ) -> dict[str, object]:
        return {
            "table_name": table,
            "index_name": name,
            "indisunique": unique,
            "indisprimary": primary,
            "indisexclusion": False,
            "indisvalid": True,
            "indisready": True,
            "indislive": True,
            "indnullsnotdistinct": False,
            "indnkeyatts": len(columns),
            "indnatts": len(columns),
            "has_no_expressions": True,
            "access_method": "btree",
            "key_columns": columns,
            "include_columns": [],
            "predicate": predicate,
        }

    constraints = [
        constraint(
            "login_attempts", "pk_login_attempts", "p",
            backing_index="pk_login_attempts",
        ),
        constraint(
            "login_attempts", "uq_login_attempts_opaque_id", "u",
            backing_index="uq_login_attempts_opaque_id",
        ),
        constraint(
            "login_attempts",
            "fk_login_attempts_registration_id_student_registrations",
            "f",
            backing_index="pk_student_registrations",
            delete_action="c",
        ),
        constraint(
            "login_attempts",
            "fk_login_attempts_challenge_id_otp_challenges",
            "f",
            backing_index="pk_otp_challenges",
            delete_action="n",
        ),
        constraint(
            "auth_sessions", "pk_auth_sessions", "p",
            backing_index="pk_auth_sessions",
        ),
        constraint(
            "auth_sessions", "uq_auth_sessions_token_hash", "u",
            backing_index="uq_auth_sessions_token_hash",
        ),
        constraint(
            "auth_sessions", "fk_auth_sessions_user_id_users", "f",
            backing_index="pk_users",
            delete_action="c",
        ),
    ]
    indexes = [
        index("login_attempts", "pk_login_attempts", ["id"], unique=True, primary=True),
        index(
            "login_attempts", "uq_login_attempts_opaque_id", ["opaque_id"],
            unique=True,
        ),
        index("login_attempts", "ix_login_attempts_lookup_hash", ["lookup_hash"]),
        index(
            "login_attempts", "ix_login_attempts_registration_id", ["registration_id"]
        ),
        index("login_attempts", "ix_login_attempts_challenge_id", ["challenge_id"]),
        index("login_attempts", "ix_login_attempts_expires_at", ["expires_at"]),
        index("login_attempts", "ix_login_attempts_consumed_at", ["consumed_at"]),
        index("auth_sessions", "pk_auth_sessions", ["id"], unique=True, primary=True),
        index(
            "auth_sessions", "uq_auth_sessions_token_hash", ["token_hash"],
            unique=True,
        ),
        index("auth_sessions", "ix_auth_sessions_user_id", ["user_id"]),
        index("auth_sessions", "ix_auth_sessions_token_hash", ["token_hash"]),
        index("auth_sessions", "ix_auth_sessions_expires_at", ["expires_at"]),
        index(
            "auth_sessions", "uq_auth_sessions_one_active_per_user", ["user_id"],
            unique=True, predicate="status = 'active'",
        ),
        index("auth_sessions", "ix_auth_sessions_revoked_at", ["revoked_at"]),
    ]
    return constraints, indexes


class _CatalogRows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def mappings(self) -> _CatalogRows:
        return self

    def all(self) -> list[dict[str, object]]:
        return self.rows


class _CatalogBind:
    def __init__(
        self,
        constraints: list[dict[str, object]],
        indexes: list[dict[str, object]],
    ) -> None:
        self.constraints = constraints
        self.indexes = indexes

    def execute(self, statement: object) -> _CatalogRows:
        source = str(statement)
        if "FROM pg_catalog.pg_constraint" in source:
            return _CatalogRows(self.constraints)
        if "FROM pg_catalog.pg_index" in source:
            return _CatalogRows(self.indexes)
        raise AssertionError("unexpected catalog statement")


def test_0020_postgresql_catalog_authority_accepts_exact_safe_head() -> None:
    migration = import_module(
        "app.db.migrations.versions.0020_auth_retention_lifecycle"
    )
    constraints, indexes = _pg_catalog_fixture()

    migration._validate_postgresql_catalog_authority(
        _CatalogBind(constraints, indexes), head=True
    )


@pytest.mark.parametrize(
    ("surface", "table", "name", "field", "value"),
    (
        ("constraint", "login_attempts", "pk_login_attempts", "condeferrable", True),
        ("constraint", "login_attempts", "pk_login_attempts", "convalidated", False),
        ("constraint", "login_attempts", "pk_login_attempts", "connoinherit", False),
        (
            "constraint", "auth_sessions", "uq_auth_sessions_token_hash",
            "condeferrable", True,
        ),
        (
            "constraint", "auth_sessions", "uq_auth_sessions_token_hash",
            "condeferred", True,
        ),
        (
            "constraint", "auth_sessions", "uq_auth_sessions_token_hash",
            "convalidated", False,
        ),
        (
            "constraint", "auth_sessions", "fk_auth_sessions_user_id_users",
            "convalidated", False,
        ),
        (
            "constraint", "auth_sessions", "fk_auth_sessions_user_id_users",
            "backing_index", None,
        ),
        (
            "constraint", "auth_sessions", "fk_auth_sessions_user_id_users",
            "connoinherit", False,
        ),
        ("index", "login_attempts", "pk_login_attempts", "include_columns", ["opaque_id"]),
        ("index", "auth_sessions", "ix_auth_sessions_expires_at", "indisvalid", False),
        ("index", "auth_sessions", "ix_auth_sessions_expires_at", "indisready", False),
        ("index", "auth_sessions", "ix_auth_sessions_expires_at", "indislive", False),
    ),
)
def test_0020_postgresql_catalog_authority_rejects_safety_state_mutants(
    surface: str,
    table: str,
    name: str,
    field: str,
    value: object,
) -> None:
    migration = import_module(
        "app.db.migrations.versions.0020_auth_retention_lifecycle"
    )
    constraints, indexes = deepcopy(_pg_catalog_fixture())
    rows = constraints if surface == "constraint" else indexes
    target = next(
        row
        for row in rows
        if row["table_name"] == table
        and row["conname" if surface == "constraint" else "index_name"] == name
    )
    target[field] = value

    with pytest.raises(ValueError):
        migration._validate_postgresql_catalog_authority(
            _CatalogBind(constraints, indexes), head=True
        )


def test_0020_populated_upgrade_backfills_and_roundtrips_to_exact_parent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "nyay19-populated.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    _, attempt_id, session_id = _seed_0019(database)
    upgraded = _alembic(database, "upgrade", HEAD)
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(engine)
    assert "ix_login_attempts_expires_at" in {
        row["name"] for row in inspector.get_indexes("login_attempts")
    }
    assert {
        row["name"] for row in inspector.get_check_constraints("login_attempts")
    } == {
        "ck_login_attempts_status",
        "ck_login_attempts_lookup_hash_shape",
        "ck_login_attempts_opaque_id_shape",
        "ck_login_attempts_lifecycle_shape",
    }
    assert {
        row["name"] for row in inspector.get_check_constraints("auth_sessions")
    } == {
        "ck_auth_sessions_status",
        "ck_auth_sessions_token_hash_shape",
        "ck_auth_sessions_lifecycle_shape",
    }
    assert next(
        row for row in inspector.get_columns("auth_sessions") if row["name"] == "user_id"
    )["nullable"] is True
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT consumed_at FROM login_attempts WHERE id=:id"),
            {"id": attempt_id},
        ) is not None
        assert connection.scalar(
            text("SELECT revoked_at FROM auth_sessions WHERE id=:id"),
            {"id": session_id},
        ) is not None
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
    engine.dispose()

    downgraded = _alembic(database, "downgrade", PARENT)
    assert downgraded.returncode == 0, downgraded.stderr
    parent_inspector = inspect(create_engine(f"sqlite+pysqlite:///{database}"))
    assert {
        row["name"] for row in parent_inspector.get_check_constraints("login_attempts")
    } == {"ck_login_attempts_ck_login_attempts_status"}
    assert {
        row["name"] for row in parent_inspector.get_check_constraints("auth_sessions")
    } == {"ck_auth_sessions_ck_auth_sessions_status"}
    assert next(
        row
        for row in parent_inspector.get_columns("auth_sessions")
        if row["name"] == "user_id"
    )["nullable"] is False
    assert "ix_login_attempts_expires_at" not in {
        row["name"] for row in parent_inspector.get_indexes("login_attempts")
    }
    assert _alembic(database, "upgrade", HEAD).returncode == 0
    # Alembic ``check`` compares against the repository head.  First prove the
    # exact 0019<->0020 lifecycle above, then advance through the sealed 0021
    # checkpoint to the authenticated repository head before asking Alembic for
    # model/migration drift.
    assert _alembic(database, "upgrade", CURRENT_HEAD).returncode == 0
    assert _alembic(database, "check").returncode == 0


def test_0020_populated_downgrade_refuses_erased_state_without_partial_ddl(
    tmp_path: Path,
) -> None:
    database = tmp_path / "nyay19-refusal.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    _seed_0019(database)
    assert _alembic(database, "upgrade", HEAD).returncode == 0
    epoch = "1970-01-01 00:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE login_attempts SET opaque_id=?, lookup_hash=?, registration_id=NULL, "
            "challenge_id=NULL, status='erased', expires_at=?, consumed_at=?, "
            "created_at=?, updated_at=?, deleted_at=?, metadata_json=NULL",
            ("c" * 64, "d" * 64, epoch, epoch, epoch, epoch, epoch),
        )
        connection.commit()
    before = _schema(database)
    with sqlite3.connect(database) as connection:
        row_before = connection.execute(
            "SELECT opaque_id, lookup_hash, status, expires_at, consumed_at, "
            "created_at, updated_at, deleted_at FROM login_attempts"
        ).fetchone()

    refused = _alembic(database, "downgrade", PARENT)
    assert refused.returncode != 0
    assert "NYAY-19 downgrade rejected unsafe schema or erased auth state" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0] == HEAD
        assert connection.execute(
            "SELECT opaque_id, lookup_hash, status, expires_at, consumed_at, "
            "created_at, updated_at, deleted_at FROM login_attempts"
        ).fetchone() == row_before


def test_0020_upgrade_rejects_same_name_wrong_active_session_index(
    tmp_path: Path,
) -> None:
    database = tmp_path / "nyay19-index-mutant.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX uq_auth_sessions_one_active_per_user")
        connection.execute(
            "CREATE INDEX uq_auth_sessions_one_active_per_user "
            "ON auth_sessions(token_hash)"
        )
        connection.commit()
    before = _schema(database)

    refused = _alembic(database, "upgrade", HEAD)

    assert refused.returncode != 0
    assert "NYAY-19 auth retention migration rejected unsafe schema or data" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0] == PARENT


def test_0020_upgrade_rejects_nullable_token_hash_without_partial_ddl(
    tmp_path: Path,
) -> None:
    database = tmp_path / "nyay19-nullable-token-upgrade.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    _rewrite_table_sql(
        database,
        table="auth_sessions",
        old="token_hash VARCHAR(64) NOT NULL",
        new="token_hash VARCHAR(64)",
    )
    before = _schema(database)

    refused = _alembic(database, "upgrade", HEAD)

    assert refused.returncode != 0
    assert "NYAY-19 auth retention migration rejected unsafe schema or data" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0] == PARENT


@pytest.mark.parametrize(
    ("table", "old", "new"),
    (
        (
            "login_attempts",
            "opaque_id VARCHAR(64) NOT NULL",
            "opaque_id VARCHAR(64)",
        ),
        (
            "login_attempts",
            "lookup_hash VARCHAR(64) NOT NULL",
            "lookup_hash VARCHAR(64)",
        ),
        (
            "auth_sessions",
            "token_hash VARCHAR(64) NOT NULL",
            "token_hash VARCHAR(63) NOT NULL",
        ),
        (
            "auth_sessions",
            "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE",
            "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL",
        ),
        (
            "auth_sessions",
            "status IN ('active', 'revoked', 'expired')",
            "status IN ('active', 'revoked', 'expired') OR token_hash IS NULL",
        ),
    ),
)
def test_0020_upgrade_rejects_same_name_parent_schema_mutants_without_ddl(
    tmp_path: Path,
    table: str,
    old: str,
    new: str,
) -> None:
    database = tmp_path / f"nyay19-parent-mutant-{table}-{uuid.uuid4().hex}.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    _rewrite_table_sql(database, table=table, old=old, new=new)
    before = _schema(database)

    refused = _alembic(database, "upgrade", HEAD)

    assert refused.returncode != 0
    assert "NYAY-19 auth retention migration rejected unsafe schema or data" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0] == PARENT


@pytest.mark.parametrize(
    "constraint",
    (
        "CONSTRAINT fk_auth_sessions_user_id_users FOREIGN KEY(user_id) "
        "REFERENCES student_registrations (id) ON DELETE SET NULL",
        "CONSTRAINT ck_auth_sessions_ck_auth_sessions_status CHECK (1 = 1)",
        "CONSTRAINT uq_auth_sessions_token_hash UNIQUE (status)",
    ),
)
def test_0020_upgrade_rejects_duplicate_same_name_constraints_without_ddl(
    tmp_path: Path,
    constraint: str,
) -> None:
    database = tmp_path / f"nyay19-duplicate-{uuid.uuid4().hex}.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    _append_table_constraint(
        database,
        table="auth_sessions",
        constraint=constraint,
    )
    before = _schema(database)

    refused = _alembic(database, "upgrade", HEAD)

    assert refused.returncode != 0
    assert "NYAY-19 auth retention migration rejected unsafe schema or data" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0] == PARENT


def test_0020_downgrade_rejects_nullable_null_token_without_partial_ddl(
    tmp_path: Path,
) -> None:
    database = tmp_path / "nyay19-nullable-token-downgrade.db"
    assert _alembic(database, "upgrade", HEAD).returncode == 0
    _rewrite_table_sql(
        database,
        table="auth_sessions",
        old="token_hash VARCHAR(64) NOT NULL",
        new="token_hash VARCHAR(64)",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (id, role, status) VALUES (?, 'student', 'active')",
            (uuid.uuid4().hex,),
        )
        connection.execute(
            "INSERT INTO auth_sessions "
            "(id, user_id, token_hash, status, expires_at, last_seen_at) "
            "SELECT ?, id, NULL, 'active', ?, ? FROM users LIMIT 1",
            (
                uuid.uuid4().hex,
                "2030-01-01 00:00:00+00:00",
                "2026-01-01 00:00:00+00:00",
            ),
        )
        connection.commit()
    before = _schema(database)

    refused = _alembic(database, "downgrade", PARENT)

    assert refused.returncode != 0
    assert "NYAY-19 downgrade rejected unsafe schema or erased auth state" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0] == HEAD
        assert connection.execute(
            "SELECT token_hash FROM auth_sessions"
        ).fetchone()[0] is None


def test_0020_downgrade_rejects_lifecycle_grouping_mutant_without_partial_ddl(
    tmp_path: Path,
) -> None:
    database = tmp_path / "nyay19-lifecycle-grouping-mutant.db"
    assert _alembic(database, "upgrade", HEAD).returncode == 0
    _rewrite_table_sql(
        database,
        table="auth_sessions",
        old=(
            "(status = 'active' AND user_id IS NOT NULL AND revoked_at IS NULL "
            "AND deleted_at IS NULL)"
        ),
        new=(
            "(status = 'active' AND (user_id IS NOT NULL AND revoked_at IS NULL "
            "OR deleted_at IS NULL))"
        ),
    )
    before = _schema(database)

    refused = _alembic(database, "downgrade", PARENT)

    assert refused.returncode != 0
    assert "NYAY-19 downgrade rejected unsafe schema or erased auth state" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0] == HEAD


def test_0020_freezes_legacy_delete_once_and_refuses_lossy_downgrade(
    tmp_path: Path,
) -> None:
    database = tmp_path / "nyay19-legacy-delete.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    user_id, session_ids = _seed_legacy_delete_graph(database)

    upgraded = _alembic(database, "upgrade", HEAD)

    assert upgraded.returncode == 0, upgraded.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT status FROM users WHERE id=?", (user_id,)
        ).fetchone()[0] == "suspended"
        assert connection.execute(
            "SELECT status FROM student_registrations WHERE user_id=?", (user_id,)
        ).fetchone()[0] == "suspended"
        sessions = connection.execute(
            "SELECT id, status, expires_at, revoked_at FROM auth_sessions "
            "WHERE user_id=? ORDER BY id",
            (user_id,),
        ).fetchall()
        by_id = {row[0]: row[1:] for row in sessions}
        assert by_id[session_ids[0]][0] == "revoked"
        assert by_id[session_ids[0]][2] is not None
        assert by_id[session_ids[1]][0] == "expired"
        assert by_id[session_ids[1]][2] == by_id[session_ids[1]][1]
        assert connection.execute(
            "SELECT count(*) FROM audit_events "
            "WHERE action='student.auth.deletion_backfill_frozen'"
        ).fetchone()[0] == 1
        frozen_timestamps = (
            connection.execute(
                "SELECT updated_at FROM users WHERE id=?", (user_id,)
            ).fetchone()[0],
            connection.execute(
                "SELECT updated_at FROM student_registrations WHERE user_id=?",
                (user_id,),
            ).fetchone()[0],
        )

    migration = import_module(
        "app.db.migrations.versions.0020_auth_retention_lifecycle"
    )
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        migration._freeze_accepted_legacy_deletions(connection)
    engine.dispose()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT count(*) FROM audit_events "
            "WHERE action='student.auth.deletion_backfill_frozen'"
        ).fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT updated_at FROM users WHERE id=?", (user_id,)
            ).fetchone()[0],
            connection.execute(
                "SELECT updated_at FROM student_registrations WHERE user_id=?",
                (user_id,),
            ).fetchone()[0],
        ) == frozen_timestamps

    before = _schema(database)
    refused = _alembic(database, "downgrade", PARENT)
    assert refused.returncode != 0
    assert "NYAY-19 downgrade rejected unsafe schema or erased auth state" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == before


def test_0020_rejects_unsafe_legacy_delete_targets_before_writes(
    tmp_path: Path,
) -> None:
    for label, role, registrations, confirmation_hash, jobs in (
        ("non-student", "admin", 1, "c" * 64, 1),
        ("missing-registration", "student", 0, "c" * 64, 1),
        ("ambiguous-registration", "student", 2, "c" * 64, 1),
        ("missing-confirmation", "student", 1, None, 1),
        ("missing-job", "student", 1, "c" * 64, 0),
        ("ambiguous-job", "student", 1, "c" * 64, 2),
    ):
        database = tmp_path / f"nyay19-{label}.db"
        assert _alembic(database, "upgrade", PARENT).returncode == 0
        user_id, _ = _seed_legacy_delete_graph(
            database,
            role=role,
            registrations=registrations,
            confirmation_hash=confirmation_hash,
            deletion_jobs=jobs,
        )
        before = _schema(database)
        state_before = _legacy_delete_state(database, user_id)

        refused = _alembic(database, "upgrade", HEAD)

        assert refused.returncode != 0
        assert "NYAY-19 auth retention migration rejected unsafe schema or data" in (
            refused.stdout + refused.stderr
        )
        assert _schema(database) == before
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone()[0] == PARENT
            assert connection.execute(
                "SELECT count(*) FROM audit_events "
                "WHERE action='student.auth.deletion_backfill_frozen'"
            ).fetchone()[0] == 0
        assert _legacy_delete_state(database, user_id) == state_before


@pytest.mark.parametrize(
    ("label", "table", "old", "new", "mutation"),
    (
        (
            "null-dsr-status",
            "data_subject_requests",
            "status VARCHAR(16) DEFAULT 'pending' NOT NULL",
            "status VARCHAR(16) DEFAULT 'pending'",
            "UPDATE data_subject_requests SET status=NULL",
        ),
        (
            "null-job-status",
            "deletion_jobs",
            "status VARCHAR(16) DEFAULT 'pending' NOT NULL",
            "status VARCHAR(16) DEFAULT 'pending'",
            "UPDATE deletion_jobs SET status=NULL",
        ),
        (
            "null-job-mode",
            "deletion_jobs",
            "mode VARCHAR(16) DEFAULT 'anonymise' NOT NULL",
            "mode VARCHAR(16) DEFAULT 'anonymise'",
            "UPDATE deletion_jobs SET mode=NULL",
        ),
        (
            "null-user-role",
            "users",
            "role VARCHAR(32) DEFAULT 'student' NOT NULL",
            "role VARCHAR(32) DEFAULT 'student'",
            "UPDATE users SET role=NULL",
        ),
        (
            "null-user-status",
            "users",
            "status VARCHAR(32) DEFAULT 'pending' NOT NULL",
            "status VARCHAR(32) DEFAULT 'pending'",
            "UPDATE users SET status=NULL",
        ),
        (
            "null-registration-status",
            "student_registrations",
            "status VARCHAR(32) DEFAULT 'otp_pending' NOT NULL",
            "status VARCHAR(32) DEFAULT 'otp_pending'",
            "UPDATE student_registrations SET status=NULL",
        ),
    ),
)
def test_0020_rejects_null_legacy_delete_evidence_and_targets_without_writes(
    tmp_path: Path,
    label: str,
    table: str,
    old: str,
    new: str,
    mutation: str,
) -> None:
    database = tmp_path / f"nyay19-{label}.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    user_id, _ = _seed_legacy_delete_graph(database)
    _rewrite_table_sql(database, table=table, old=old, new=new)
    with sqlite3.connect(database) as connection:
        connection.execute(mutation)
        connection.commit()
    schema_before = _schema(database)
    state_before = _legacy_delete_state(database, user_id)

    refused = _alembic(database, "upgrade", HEAD)

    assert refused.returncode != 0
    assert "NYAY-19 auth retention migration rejected unsafe schema or data" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == schema_before
    assert _legacy_delete_state(database, user_id) == state_before


@pytest.mark.parametrize(
    ("label", "table", "old", "new", "mutation"),
    (
        (
            "unknown-user-status",
            "users",
            "status IN ('pending', 'active', 'suspended', 'deleted')",
            "status IN ('pending', 'active', 'suspended', 'deleted', 'unknown')",
            "UPDATE users SET status='unknown'",
        ),
        (
            "unknown-registration-status",
            "student_registrations",
            "status IN ('otp_pending', 'otp_verified', 'active', 'suspended', 'deleted')",
            "status IN "
            "('otp_pending', 'otp_verified', 'active', 'suspended', 'deleted', 'unknown')",
            "UPDATE student_registrations SET status='unknown'",
        ),
    ),
)
def test_0020_rejects_unknown_legacy_target_status_without_writes(
    tmp_path: Path,
    label: str,
    table: str,
    old: str,
    new: str,
    mutation: str,
) -> None:
    database = tmp_path / f"nyay19-{label}.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    user_id, _ = _seed_legacy_delete_graph(database)
    _rewrite_table_sql(database, table=table, old=old, new=new)
    with sqlite3.connect(database) as connection:
        connection.execute(mutation)
        connection.commit()
    schema_before = _schema(database)
    state_before = _legacy_delete_state(database, user_id)

    refused = _alembic(database, "upgrade", HEAD)

    assert refused.returncode != 0
    assert "NYAY-19 auth retention migration rejected unsafe schema or data" in (
        refused.stdout + refused.stderr
    )
    assert _schema(database) == schema_before
    assert _legacy_delete_state(database, user_id) == state_before
