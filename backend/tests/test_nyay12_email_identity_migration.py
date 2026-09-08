"""NYAY-12 revision 0025: forward-only, evidence-free, reconciliation-first (E-17/E-18/E-29)."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

BACKEND = Path(__file__).resolve().parents[1]
PARENT = "0024_nyay11_authority_state"
HEAD = "0025_nyay12_email_identity"
TEST_ENV = {
    "APP_ENV": "testing",
    "REGISTRATION_SECRET": "nyay12-test-encryption-authority-not-default",
    "REGISTRATION_LOOKUP_SECRET": "nyay12-test-lookup-authority-not-default",
    "REGISTRATION_KEY_VERSION": "v1",
}
NEW_TABLES = ("user_email_identities", "email_identity_mutations", "email_identity_reconciliations")


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "app/db/migrations"))
    return ScriptDirectory.from_config(config)


def _alembic(database: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env={**os.environ, **TEST_ENV, "DATABASE_URL": f"sqlite+pysqlite:///{database}"},
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )


def _revision(database: Path) -> str:
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def _seed_profile(database: Path, *, email_hash: str | None, deleted: bool = False) -> None:
    ids = {"user": uuid.uuid4().hex, "registration": uuid.uuid4().hex, "profile": uuid.uuid4().hex}
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, role, status) VALUES (:id, 'student', 'active')"), {"id": ids["user"]})
            connection.execute(
                text(
                    """
                    INSERT INTO student_registrations (
                        id, user_id, first_name, last_name, mobile_hash, mobile_ct, dob_hash, dob_ct,
                        dob_hash_state, key_version, status, is_minor
                    ) VALUES (
                        :id, :user_id, 'NYAY12', 'Legacy', :mobile_hash, 'v1:mobile', :dob_hash, 'v1:dob',
                        'verified', 'v1', 'active', false
                    )
                    """
                ),
                {"id": ids["registration"], "user_id": ids["user"], "mobile_hash": uuid.uuid4().hex * 2, "dob_hash": uuid.uuid4().hex * 2},
            )
            connection.execute(
                text(
                    "INSERT INTO student_profiles (id, registration_id, institutional_email_hash, deleted_at) "
                    "VALUES (:id, :registration_id, :email_hash, :deleted_at)"
                ),
                {
                    "id": ids["profile"],
                    "registration_id": ids["registration"],
                    "email_hash": email_hash,
                    "deleted_at": "2026-01-01 00:00:00" if deleted else None,
                },
            )
    finally:
        engine.dispose()


def test_head_and_chain_are_forward_only_from_0024():
    script = _script_directory()
    assert script.get_current_head() == HEAD
    revision = script.get_revision(HEAD)
    assert revision.down_revision == PARENT
    from app.db import migration_release_guard as guard

    assert guard.APPLICATION_HEAD_REVISION == HEAD
    path = BACKEND / "app/db/migrations/versions" / f"{HEAD}.py"
    assert guard.APPLICATION_HEAD_SOURCE_PATH == path
    assert guard.APPLICATION_HEAD_SOURCE_SHA256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert path.name in guard.ALL_MIGRATION_SOURCE_SHA256
    assert "nyay12" in guard._ISOLATED_DATABASE_MARKERS
    source = path.read_text(encoding="utf-8")
    # The only data-writing section is the reconciliation ledger; it never touches identities.
    reconcile = source[source.index("def _reconcile_legacy_duplicates"):source.index("def downgrade")]
    assert "user_email_identities" not in reconcile
    assert "verified" not in reconcile.replace("never verify", "")
    for forbidden in ("state='verified'", 'state="verified"', '"verified"', "is_primary=True", "verified_at="):
        assert forbidden not in source, forbidden


def test_migration_creates_no_identity_rows_and_round_trips(tmp_path: Path):
    database = tmp_path / "nyay12-lifecycle.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    _seed_profile(database, email_hash="a" * 64)
    assert _alembic(database, "upgrade", "head").returncode == 0
    assert _revision(database) == HEAD
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        inspector = inspect(engine)
        for table in NEW_TABLES:
            assert table in inspector.get_table_names(), table
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM user_email_identities")) == 0
            assert connection.scalar(text("SELECT COUNT(*) FROM email_identity_reconciliations")) == 0
            # Historical institutional emails are never promoted to verified login identities.
            assert connection.scalar(text("SELECT COUNT(*) FROM student_profiles WHERE institutional_email_hash IS NOT NULL")) == 1
        index_names = {index["name"] for index in inspector.get_indexes("user_email_identities")}
        assert {
            "uq_user_email_identities_one_primary_per_user",
            "uq_user_email_identities_verified_email",
            "uq_user_email_identities_live_owner_email",
        } <= index_names
    finally:
        engine.dispose()
    assert _alembic(database, "downgrade", PARENT).returncode == 0
    assert _revision(database) == PARENT
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        assert not set(NEW_TABLES) & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert _alembic(database, "upgrade", "head").returncode == 0
    assert _revision(database) == HEAD


def test_legacy_duplicate_institutional_emails_enter_reconciliation_not_verified(tmp_path: Path):
    database = tmp_path / "nyay12-legacy.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    shared = "b" * 64
    _seed_profile(database, email_hash=shared)
    _seed_profile(database, email_hash=shared)
    _seed_profile(database, email_hash=shared, deleted=True)  # deleted rows are not live duplicates
    _seed_profile(database, email_hash="c" * 64)
    _seed_profile(database, email_hash=None)
    assert _alembic(database, "upgrade", "head").returncode == 0
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT email_hash, reason, state, holder_user_id, claimant_user_id FROM email_identity_reconciliations")
            ).all()
            assert len(rows) == 1
            assert rows[0][0] == shared and rows[0][1] == "legacy_duplicate" and rows[0][2] == "open"
            assert rows[0][3] is None and rows[0][4] is None
            assert connection.scalar(text("SELECT COUNT(*) FROM user_email_identities")) == 0
    finally:
        engine.dispose()
    # Populated reconciliation graph: downgrade refuses (fail closed) and leaves the row intact.
    refused = _alembic(database, "downgrade", PARENT)
    assert refused.returncode != 0
    assert "email_identity_downgrade_requires_empty_graph" in (refused.stdout + refused.stderr)
    assert _revision(database) == HEAD
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM email_identity_reconciliations")) == 1
    finally:
        engine.dispose()


def test_partial_unique_indexes_hold_on_sqlite(tmp_path: Path):
    database = tmp_path / "nyay12-indexes.db"
    assert _alembic(database, "upgrade", "head").returncode == 0
    _seed_profile(database, email_hash=None)
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    try:
        with engine.begin() as connection:
            user_a = connection.scalar(text("SELECT id FROM users"))
            connection.execute(text("INSERT INTO users (id, role, status) VALUES (:id, 'student', 'active')"), {"id": uuid.uuid4().hex})
            user_b = connection.scalar(text("SELECT id FROM users WHERE id <> :a"), {"a": user_a})
            insert = text(
                "INSERT INTO user_email_identities (id, user_id, email_hash, email_ct, key_version, state, is_primary, "
                "verified_at, removed_at, verification_state, code_hash, provider_receipt_hash, attempts, "
                "challenge_issued_at, challenge_expires_at, created_at, updated_at) VALUES "
                "(:id, :user, :hash, 'v1:ct', 'v1', :state, :primary, :verified_at, NULL, 'none', NULL, NULL, 0, NULL, NULL, "
                "'2026-09-10 09:00:00', '2026-09-10 09:00:00')"
            )
            connection.execute(insert, {"id": uuid.uuid4().hex, "user": user_a, "hash": "d" * 64, "state": "verified", "primary": 1, "verified_at": "2026-09-10 09:00:00"})
            with pytest.raises(Exception):
                connection.execute(insert, {"id": uuid.uuid4().hex, "user": user_b, "hash": "d" * 64, "state": "verified", "primary": 0, "verified_at": "2026-09-10 09:00:00"})
        with engine.begin() as connection:
            with pytest.raises(Exception):
                connection.execute(insert, {"id": uuid.uuid4().hex, "user": user_a, "hash": "e" * 64, "state": "verified", "primary": 1, "verified_at": "2026-09-10 09:00:00"})
        with engine.begin() as connection:
            with pytest.raises(Exception):  # primary requires verified
                connection.execute(insert, {"id": uuid.uuid4().hex, "user": user_b, "hash": "f" * 64, "state": "pending", "primary": 1, "verified_at": None})
        with engine.begin() as connection:
            # A second pending claim on the same address by another user is allowed (non-enumerating claims).
            connection.execute(insert, {"id": uuid.uuid4().hex, "user": user_b, "hash": "d" * 64, "state": "pending", "primary": 0, "verified_at": None})
            with pytest.raises(Exception):  # but not two live claims by the same user
                connection.execute(insert, {"id": uuid.uuid4().hex, "user": user_b, "hash": "d" * 64, "state": "pending", "primary": 0, "verified_at": None})
    finally:
        engine.dispose()
