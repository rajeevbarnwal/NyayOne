"""Executable migration/schema proof for SAATHI-269/450."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import AddConstraint, CreateIndex

from app.models.wave4 import OrganisationResponseRequest

BACKEND = Path(__file__).resolve().parents[1]
WAVE4_REVISION = "0012_wave4_moderation"
HEAD_REVISION = "0025_nyay12_email_identity"
PARENT = "0010_student_login_session"
TABLES = {
    "internship_reports",
    "internship_report_categories",
    "internship_report_consents",
    "internship_report_evidence",
    "reporter_identity_vault",
    "reporter_identity_access_requests",
    "reporter_identity_access_approvals",
    "moderation_handoffs",
    "internship_reporting_outbox",
    "moderation_cases",
    "moderation_assignments",
    "moderation_actions",
    "duplicate_clusters",
    "duplicate_cluster_members",
    "risk_signals",
    "risk_signal_approvals",
    "moderation_notification_outbox",
    "published_risk_labels",
    "publication_decisions",
    "organisation_response_requests",
    "organisation_responses",
    "response_moderation",
    "notification_outbox",
}


def test_response_request_identifiers_compile_for_postgresql() -> None:
    """Catch explicit identifiers that exceed PostgreSQL's 63-byte limit."""
    table = OrganisationResponseRequest.__table__
    dialect = postgresql.dialect()
    for index in table.indexes:
        rendered = str(CreateIndex(index).compile(dialect=dialect))
        assert rendered.startswith("CREATE ")
    for constraint in table.constraints:
        if constraint.name:
            rendered = str(AddConstraint(constraint).compile(dialect=dialect))
            assert rendered.startswith("ALTER TABLE organisation_response_requests")


def _alembic(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{database}"},
        capture_output=True,
        text=True,
    )


def test_real_upgrade_has_all_tables_constraints_indexes_and_privacy_boundaries(
    alembic_snapshots, tmp_path
):
    database = tmp_path / "wave4-schema.db"
    shutil.copyfile(alembic_snapshots["head"], database)
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(engine)
    assert TABLES <= set(inspector.get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD_REVISION

    report_columns = {item["name"] for item in inspector.get_columns("internship_reports")}
    assert {
        "organisation_name",
        "listing_application_ref",
        "experience_start_date",
        "experience_end_date",
        "narrative",
        "privacy_mode",
        "status",
        "version",
    } <= report_columns
    assert not report_columns & {
        "user_id",
        "reporter_id",
        "author_id",
        "reporter_lookup_hash",
        "reporter_ciphertext",
        "mobile",
        "email",
    }
    vault_columns = {item["name"] for item in inspector.get_columns("reporter_identity_vault")}
    assert {"report_id", "reporter_lookup_hash", "reporter_ciphertext", "key_version"} <= vault_columns
    evidence_columns = {item["name"] for item in inspector.get_columns("internship_report_evidence")}
    assert {"object_ref", "mime_type", "size_bytes", "checksum_sha256", "scan_state"} <= evidence_columns
    assert not evidence_columns & {"filename", "file_bytes", "content", "raw_file"}

    response_request_checks = {
        item["name"] for item in inspector.get_check_constraints("organisation_response_requests")
    }
    assert any("representative_verification_method" in name for name in response_request_checks)
    assert any("target_response_matches_kind" in name for name in response_request_checks)
    response_request_indexes = {
        item["name"] for item in inspector.get_indexes("organisation_response_requests")
    }
    assert "ix_organisation_response_requests_target_response_id" in response_request_indexes
    assert "uq_response_requests_pending_initial_label" in response_request_indexes
    response_request_foreign_keys = {
        item["name"] for item in inspector.get_foreign_keys("organisation_response_requests")
    }
    assert (
        "fk_org_response_requests_target_response"
        in response_request_foreign_keys
    )
    response_indexes = {item["name"] for item in inspector.get_indexes("organisation_responses")}
    assert "uq_organisation_responses_current_label" in response_indexes
    member_indexes = {item["name"] for item in inspector.get_indexes("duplicate_cluster_members")}
    assert "uq_report_risk_cluster_category_active" in member_indexes
    outbox_columns = {item["name"] for item in inspector.get_columns("notification_outbox")}
    assert {"claimed_at", "claim_token", "secret_ciphertext", "secret_key_version"} <= outbox_columns
    listing_columns = {item["name"] for item in inspector.get_columns("internship_listings")}
    listing_indexes = {item["name"] for item in inspector.get_indexes("internship_listings")}
    assert "organisation_public_id" in listing_columns
    assert "ix_internship_listings_organisation_public_id" in listing_indexes

    for table in TABLES:
        index_columns = {
            column
            for index in inspector.get_indexes(table)
            for column in index.get("column_names") or []
        }
        unique_columns = {
            column
            for constraint in inspector.get_unique_constraints(table)
            for column in constraint.get("column_names") or []
        }
        for fk in inspector.get_foreign_keys(table):
            assert set(fk["constrained_columns"]) <= index_columns | unique_columns, (
                table,
                fk["constrained_columns"],
            )
            assert fk.get("options", {}).get("ondelete") in {"CASCADE", "RESTRICT", "SET NULL"}
    engine.dispose()


def test_upgrade_check_downgrade_reupgrade_is_clean(tmp_path):
    database = tmp_path / "wave4-lifecycle.db"
    up = _alembic(database, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    check = _alembic(database, "check")
    assert check.returncode == 0, check.stdout + check.stderr
    down = _alembic(database, "downgrade", PARENT)
    assert down.returncode == 0, down.stderr
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    assert not (TABLES & set(inspect(engine).get_table_names()))
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PARENT
    engine.dispose()
    reup = _alembic(database, "upgrade", "head")
    assert reup.returncode == 0, reup.stderr
    assert _alembic(database, "check").returncode == 0
