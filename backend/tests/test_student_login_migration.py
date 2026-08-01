"""Executable Alembic proof for the student login security boundary."""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[1]
REVISION = "0010_student_login_session"
PARENT = "0009_wave2_session_pricing"


def _alembic(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{database}"},
        capture_output=True,
        text=True,
    )


def test_upgrade_from_parent_creates_login_tables_constraints_and_indexes(tmp_path):
    database = tmp_path / "login-upgrade.db"
    parent = _alembic(database, "upgrade", PARENT)
    assert parent.returncode == 0, parent.stderr
    upgraded = _alembic(database, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    engine = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(engine)
    assert {"login_attempts", "auth_sessions"} <= set(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("login_attempts")} >= {
        "opaque_id", "lookup_hash", "registration_id", "challenge_id",
        "status", "expires_at", "consumed_at",
    }
    assert {column["name"] for column in inspector.get_columns("auth_sessions")} >= {
        "user_id", "token_hash", "status", "expires_at", "last_seen_at", "revoked_at",
    }
    assert {index["name"] for index in inspector.get_indexes("login_attempts")} >= {
        "ix_login_attempts_lookup_hash",
        "ix_login_attempts_registration_id",
        "ix_login_attempts_challenge_id",
    }
    assert {index["name"] for index in inspector.get_indexes("auth_sessions")} >= {
        "ix_auth_sessions_user_id",
        "ix_auth_sessions_token_hash",
        "ix_auth_sessions_expires_at",
    }
    assert {row["name"] for row in inspector.get_unique_constraints("login_attempts")} >= {
        "uq_login_attempts_opaque_id",
    }
    assert {row["name"] for row in inspector.get_unique_constraints("auth_sessions")} >= {
        "uq_auth_sessions_token_hash",
    }
    login_foreign_keys = {row["constrained_columns"][0]: row for row in inspector.get_foreign_keys("login_attempts")}
    assert login_foreign_keys["registration_id"]["options"]["ondelete"] == "CASCADE"
    assert login_foreign_keys["challenge_id"]["options"]["ondelete"] == "SET NULL"
    assert inspector.get_foreign_keys("auth_sessions")[0]["options"]["ondelete"] == "CASCADE"
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
        otp_sql = connection.scalar(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='otp_challenges'")
        )
    assert "'login'" in otp_sql
    engine.dispose()


def test_downgrade_removes_only_login_boundary_and_reupgrade_is_clean(tmp_path):
    database = tmp_path / "login-roundtrip.db"
    assert _alembic(database, "upgrade", "head").returncode == 0
    down = _alembic(database, "downgrade", PARENT)
    assert down.returncode == 0, down.stderr
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        otp_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='otp_challenges'"
        ).fetchone()[0]
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert "login_attempts" not in tables and "auth_sessions" not in tables
    assert "'login'" not in otp_sql and revision == PARENT
    assert _alembic(database, "upgrade", "head").returncode == 0
    assert _alembic(database, "check").returncode == 0
