"""Focused fail-closed regressions for migration 0016."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import subprocess
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, inspect, text


BACKEND = Path(__file__).resolve().parents[1]
PARENT = "0015_wave4_public_risk_labels"
HEAD = "0016_dob_hash_reconcile"


def _module():
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "app/db/migrations"))
    return ScriptDirectory.from_config(config).get_revision(HEAD).module


def _alembic(database: Path, *args: str, **environment: str):
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={
            **os.environ,
            "DATABASE_URL": f"sqlite+pysqlite:///{database}",
            **environment,
        },
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _encrypt(value: str, secret: str) -> str:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return "v1:" + Fernet(key).encrypt(value.encode()).decode()


def _lookup_hash(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def test_downgrade_rejects_unknown_reconciliation_column_before_mutation(tmp_path):
    database = tmp_path / "planted-head-column.db"
    assert _alembic(database, "upgrade", HEAD).returncode == 0
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE registration_dob_reconciliations "
                "ADD COLUMN planted_unknown varchar(40)"
            )
        )
    before_columns = {
        row["name"]
        for row in inspect(engine).get_columns("registration_dob_reconciliations")
    }
    engine.dispose()

    result = _alembic(database, "downgrade", PARENT)
    assert result.returncode != 0
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(engine)
    assert "registration_dob_reconciliations" in inspector.get_table_names()
    assert {
        row["name"]
        for row in inspector.get_columns("registration_dob_reconciliations")
    } == before_columns
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
    engine.dispose()


def test_upgrade_rejects_unexpected_registration_trigger_before_ddl(tmp_path):
    database = tmp_path / "planted-parent-trigger.db"
    assert _alembic(database, "upgrade", PARENT).returncode == 0
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER planted_registration_observer "
                "BEFORE UPDATE ON student_registrations "
                "BEGIN SELECT 1; END"
            )
        )
    engine.dispose()

    result = _alembic(database, "upgrade", HEAD)
    assert result.returncode != 0
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(engine)
    assert "registration_dob_reconciliations" not in inspector.get_table_names()
    assert "dob_hash_state" not in {
        row["name"] for row in inspector.get_columns("student_registrations")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PARENT
        assert connection.scalar(
            text(
                "SELECT count(*) FROM sqlite_master WHERE type='trigger' "
                "AND name='planted_registration_observer'"
            )
        ) == 1
    engine.dispose()

def test_populated_sqlite_upgrade_canonicalizes_reflected_uuid_before_ddl(tmp_path):
    database = tmp_path / "populated-parent.db"
    encryption_secret = "test-encryption-authority-not-default"
    lookup_secret = "test-lookup-authority-not-default"
    env = {
        "APP_ENV": "testing",
        "REGISTRATION_SECRET": encryption_secret,
        "REGISTRATION_LOOKUP_SECRET": lookup_secret,
        "REGISTRATION_KEY_VERSION": "v1",
    }
    assert _alembic(database, "upgrade", PARENT, **env).returncode == 0
    user_id = uuid.uuid4()
    registration_id = uuid.uuid4()
    mobile = "9000000001"
    dob = "2001-02-03"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,role,status) VALUES (:id,'student','active')"),
            {"id": user_id.hex},
        )
        connection.execute(
            text(
                "INSERT INTO student_registrations "
                "(id,user_id,first_name,last_name,mobile_hash,mobile_ct,dob_ct,"
                "dob_hash,key_version,status,is_minor,idempotency_key) VALUES "
                "(:id,:user_id,'Gate','Fixture',:mobile_hash,:mobile_ct,:dob_ct,"
                "'[rehash-required]','v1','active',false,'sqlite-populated')"
            ),
            {
                "id": registration_id.hex,
                "user_id": user_id.hex,
                "mobile_hash": _lookup_hash(mobile, lookup_secret),
                "mobile_ct": _encrypt(mobile, encryption_secret),
                "dob_ct": _encrypt(dob, encryption_secret),
            },
        )
    engine.dispose()

    result = _alembic(database, "upgrade", HEAD, **env)
    assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT dob_hash,dob_hash_state FROM student_registrations "
                "WHERE id=:id"
            ),
            {"id": registration_id.hex},
        ).one()
        assert row == (_lookup_hash(dob, lookup_secret), "verified")
        assert connection.scalar(
            text("SELECT count(*) FROM registration_dob_reconciliations")
        ) == 1
    engine.dispose()

    down = _alembic(database, "downgrade", PARENT, **env)
    assert down.returncode == 0, down.stderr
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT dob_hash FROM student_registrations WHERE id=:id"),
            {"id": registration_id.hex},
        ) == "[rehash-required]"
    engine.dispose()
    reupgrade = _alembic(database, "upgrade", HEAD, **env)
    assert reupgrade.returncode == 0, reupgrade.stderr


def test_live_quarantine_rejects_downgrade_without_mutation(tmp_path):
    database = tmp_path / "quarantine-blocks-downgrade.db"
    encryption_secret = "test-encryption-authority-not-default"
    lookup_secret = "test-lookup-authority-not-default"
    env = {
        "APP_ENV": "testing",
        "REGISTRATION_SECRET": encryption_secret,
        "REGISTRATION_LOOKUP_SECRET": lookup_secret,
        "REGISTRATION_KEY_VERSION": "v1",
    }
    assert _alembic(database, "upgrade", PARENT, **env).returncode == 0
    user_id = uuid.uuid4()
    registration_id = uuid.uuid4()
    mobile = "9000000002"
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO users (id,role,status) VALUES (:id,'student','active')"),
            {"id": user_id.hex},
        )
        connection.execute(
            text(
                "INSERT INTO student_registrations "
                "(id,user_id,first_name,last_name,mobile_hash,mobile_ct,dob_ct,"
                "dob_hash,key_version,status,is_minor,idempotency_key) VALUES "
                "(:id,:user_id,'Gate','Quarantine',:mobile_hash,:mobile_ct,"
                "'v1:not-a-fernet-token','[rehash-required]','v1','active',"
                "false,'sqlite-quarantine')"
            ),
            {
                "id": registration_id.hex,
                "user_id": user_id.hex,
                "mobile_hash": _lookup_hash(mobile, lookup_secret),
                "mobile_ct": _encrypt(mobile, encryption_secret),
            },
        )
    engine.dispose()

    upgraded = _alembic(database, "upgrade", HEAD, **env)
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    with engine.connect() as connection:
        before = connection.execute(
            text(
                "SELECT dob_hash,dob_hash_state,status FROM student_registrations "
                "WHERE id=:id"
            ),
            {"id": registration_id.hex},
        ).one()
        assert before[1:] == ("quarantined", "active")
    engine.dispose()

    rejected = _alembic(database, "downgrade", PARENT, **env)
    assert rejected.returncode != 0
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(engine)
    assert "registration_dob_reconciliations" in inspector.get_table_names()
    assert "dob_hash_state" in {
        row["name"] for row in inspector.get_columns("student_registrations")
    }
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        after = connection.execute(
            text(
                "SELECT dob_hash,dob_hash_state,status FROM student_registrations "
                "WHERE id=:id"
            ),
            {"id": registration_id.hex},
        ).one()
        assert after == before
        assert connection.scalar(
            text("SELECT count(*) FROM registration_dob_reconciliations")
        ) == 1
    # Even cross-table drift cannot erase the authoritative parent-state guard.
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM registration_dob_reconciliations"))
    engine.dispose()

    orphan_rejected = _alembic(database, "downgrade", PARENT, **env)
    assert orphan_rejected.returncode != 0
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(engine)
    assert "registration_dob_reconciliations" in inspector.get_table_names()
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        assert connection.execute(
            text(
                "SELECT dob_hash,dob_hash_state,status FROM student_registrations "
                "WHERE id=:id"
            ),
            {"id": registration_id.hex},
        ).one() == before
        assert connection.scalar(
            text("SELECT count(*) FROM registration_dob_reconciliations")
        ) == 0
    engine.dispose()


def test_canonical_date_accepts_today_and_quarantines_future_date():
    module = _module()
    today = date.today()
    tomorrow = today + timedelta(days=1)
    assert module._canonical_date(today.isoformat().encode("ascii")) == (
        today.isoformat(),
        "verified_source",
    )
    assert module._canonical_date(tomorrow.isoformat().encode("ascii")) == (
        None,
        "source_future_date",
    )


@pytest.mark.parametrize(
    ("field", "mutant"),
    [
        ("status", "'evil-otp_pending'"),
        ("status", "'OTP_PENDING'"),
        ("dob_hash", "'[rehash-required]-evil'"),
        ("dob_hash", "'[REHASH-REQUIRED]'"),
        ("key_version", "'evil-v1'"),
        ("key_version", "'V1'"),
        ("created_at", "evil_now()"),
    ],
)
def test_parent_default_fingerprint_rejects_semantic_mutants(field, mutant):
    module = _module()
    columns = {
        name: {"default": None}
        for name in module._PARENT_COLUMNS
    }
    columns.update({
        "status": {"default": "'otp_pending'"},
        "is_minor": {"default": "0"},
        "dob_hash": {"default": "'[rehash-required]'"},
        "key_version": {"default": "'v1'"},
        "created_at": {"default": "CURRENT_TIMESTAMP"},
        "updated_at": {"default": "CURRENT_TIMESTAMP"},
    })
    module._validate_registration_defaults(columns)
    columns[field]["default"] = mutant
    with pytest.raises(module.DobHashPreflightError):
        module._validate_registration_defaults(columns)


def test_status_check_fingerprint_rejects_negative_any_operator():
    module = _module()
    expected = (
        "status IN ('otp_pending', 'otp_verified', 'active', 'suspended', 'deleted')"
    )
    reflected_positive = (
        "(status)::text = ANY ((ARRAY['otp_pending'::character varying, "
        "'otp_verified'::character varying, 'active'::character varying, "
        "'suspended'::character varying, 'deleted'::character varying])::text[])"
    )
    module._validate_check_sql(reflected_positive, expected)
    with pytest.raises(module.DobHashPreflightError):
        module._validate_check_sql(
            reflected_positive.replace("= ANY", "<> ANY"), expected
        )
    with pytest.raises(module.DobHashPreflightError):
        module._validate_check_sql(
            reflected_positive.replace("'otp_pending'", "'OTP_PENDING'"),
            expected,
        )


def test_check_fingerprint_rejects_column_literal_association_swap():
    module = _module()
    expected = module._RECONCILIATION_OUTCOME_REASON_SQL
    swapped = expected.replace(
        "outcome = 'reconciled' AND reason_code = 'verified_source'",
        "reason_code = 'reconciled' AND outcome = 'verified_source'",
    )
    with pytest.raises(module.DobHashPreflightError):
        module._validate_check_sql(swapped, expected)


def test_check_fingerprint_rejects_boolean_regrouping():
    module = _module()
    expected = module._RECONCILIATION_OUTCOME_REASON_SQL
    regrouped = (
        "outcome = 'reconciled' AND "
        "(reason_code = 'verified_source' OR outcome = 'quarantined') AND "
        "reason_code != 'verified_source'"
    )
    with pytest.raises(module.DobHashPreflightError):
        module._validate_check_sql(regrouped, expected)


@pytest.mark.parametrize(
    "expected",
    [
        "length(dob_hash) = 64",
        "length(source_ciphertext_sha256) = 64",
    ],
)
def test_check_fingerprint_rejects_numeric_threshold_drift(expected):
    module = _module()
    for replacement in ("6", "-64", "+64", "~64", "@64", "`64", "?64"):
        with pytest.raises(module.DobHashPreflightError):
            module._validate_check_sql(expected.replace("64", replacement), expected)


def test_uuid_parent_type_is_dialect_exact():
    module = _module()
    assert module._type_matches(sa.Uuid(), "uuid", None, "postgresql")
    assert module._type_matches(sa.CHAR(32), "uuid", None, "sqlite")
    assert not module._type_matches(sa.CHAR(32), "uuid", None, "postgresql")


def test_schema_introspection_accepts_one_to_one_reconciliation_primary_key():
    from scripts import introspect_schema
    from sqlalchemy.dialects import postgresql

    failures = introspect_schema._table_key_failures(
        table="registration_dob_reconciliations",
        dialect="postgresql",
        columns=[{"name": "registration_id", "type": postgresql.UUID()}],
        primary_key={"constrained_columns": ["registration_id"]},
        indexes=[],
        unique_constraints=[],
        foreign_keys=[
            {
                "constrained_columns": ["registration_id"],
                "options": {"ondelete": "CASCADE"},
            }
        ],
    )
    assert failures == []

    wrong_primary_key = introspect_schema._table_key_failures(
        table="registration_dob_reconciliations",
        dialect="postgresql",
        columns=[{"name": "registration_id", "type": postgresql.UUID()}],
        primary_key={"constrained_columns": []},
        indexes=[],
        unique_constraints=[],
        foreign_keys=[
            {
                "constrained_columns": ["registration_id"],
                "options": {"ondelete": "CASCADE"},
            }
        ],
    )
    assert wrong_primary_key == [
        "registration_dob_reconciliations primary key is not exactly registration_id",
        "registration_dob_reconciliations.registration_id foreign key is not indexed",
    ]

    assert introspect_schema._table_key_failures(
        table="users",
        dialect="postgresql",
        columns=[{"name": "id", "type": postgresql.UUID()}],
        primary_key={"constrained_columns": ["id"]},
        indexes=[],
        unique_constraints=[],
        foreign_keys=[],
    ) == []


def test_reconciliation_fk_name_is_dialect_exact_after_pg_truncation():
    module = _module()
    assert module._expected_reconciliation_fk_name("sqlite") == (
        "fk_registration_dob_reconciliations_registration_id_student_registrations"
    )
    assert module._expected_reconciliation_fk_name("postgresql") == (
        "fk_registration_dob_reconciliations_registration_id_stu_1b42"
    )
    with pytest.raises(module.DobHashPreflightError):
        module._expected_reconciliation_fk_name("mysql")


@pytest.mark.parametrize(
    ("active", "lookup"),
    [
        (" dev-registration-secret-change-me ", "safe-lookup-secret"),
        ("safe-encryption-secret", " dev-registration-lookup-change-me "),
        ("same-safe-secret", "same-safe-secret"),
    ],
)
def test_keyring_rejects_padded_defaults_and_equal_lookup_key(
    monkeypatch, active, lookup
):
    module = _module()
    secret_type = type(module.settings.registration_secret)
    monkeypatch.setattr(module.settings, "registration_key_version", "v1")
    monkeypatch.setattr(module.settings, "registration_secret", secret_type(active))
    monkeypatch.setattr(
        module.settings, "registration_lookup_secret", secret_type(lookup)
    )
    monkeypatch.setattr(module.settings, "registration_prior_keys", [])
    with pytest.raises(module.DobHashPreflightError):
        module._load_migration_keyring()
