"""PostgreSQL 16 + pgvector release gate for SAATHI-269 private reporting.

This gate intentionally exits 78 when the target runtime is absent. SQLite is
useful regression coverage, but cannot prove PostgreSQL row locks, target DDL,
typed JSON, timestamptz or concurrent idempotency.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import inspect, select, text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

BLOCKED = 78
HEAD = "0011_wave4_private_reporting"
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
}
EXPECTED_CONSTRAINTS = {
    "internship_reports": {
        "uq_internship_reports_idempotency_key", "privacy_mode", "status",
        "version_positive", "experience_date_order", "submitted_timestamp_required",
    },
    "internship_report_categories": {"uq_report_category", "category"},
    "internship_report_consents": {"uq_internship_report_consents_report_id", "accepted_timestamp_matches"},
    "internship_report_evidence": {
        "uq_internship_report_evidence_object_ref", "uq_report_evidence_digest",
        "scan_state", "size_positive", "checksum_length",
    },
    "reporter_identity_vault": {
        "uq_reporter_identity_vault_report_id", "lookup_hash_length", "ciphertext_nontrivial",
    },
    "reporter_identity_access_requests": {"state", "executed_timestamp_required"},
    "reporter_identity_access_approvals": {"uq_identity_access_approver", "decision"},
    "moderation_handoffs": {"uq_moderation_handoffs_report_id", "state", "version_positive"},
    "internship_reporting_outbox": {
        "uq_internship_reporting_outbox_idempotency_key", "event_kind", "state", "attempts_nonnegative",
    },
}


class Results:
    def __init__(self):
        self.rows: list[dict] = []

    def add(self, ident: str, title: str, ok: bool, detail=None):
        self.rows.append({"id": ident, "title": title, "status": "PASS" if ok else "FAIL", "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {ident} {title}")

    @property
    def failed(self):
        return [row["id"] for row in self.rows if row["status"] != "PASS"]


def run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND,
        env=os.environ.copy(), capture_output=True, text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(BACKEND / "test-results/wave4-postgres/summary.json"))
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url.startswith("postgresql"):
        summary = {"gate": "wave4_postgres", "status": "BLOCKED", "executed": False, "reason": "DATABASE_URL is not PostgreSQL"}
        output.write_text(json.dumps(summary, indent=2) + "\n")
        print("BLOCKED: prerequisite runtime absent: PostgreSQL DATABASE_URL")
        return BLOCKED

    from app.api.v1.internship_reports import create_report, update_report
    from app.core.auth import ActorContext, Role
    from app.core.config import settings
    from app.core.crypto import decrypt
    from app.db.session import get_engine, get_sessionmaker
    from app.models.registration import User
    from app.models.wave4 import InternshipReport, ReporterIdentityVault
    from app.schemas.reporting import ReportDraftCreate, ReportDraftPatch

    engine = get_engine()
    with engine.connect() as connection:
        version_num = int(connection.scalar(text("SHOW server_version_num")))
        vector = connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
    if version_num < 160000 or not vector:
        summary = {"gate": "wave4_postgres", "status": "BLOCKED", "executed": False, "server_version_num": version_num, "pgvector": vector}
        output.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"BLOCKED: prerequisite runtime absent: PostgreSQL 16 + pgvector (actual {version_num}, {vector})")
        return BLOCKED

    results = Results()
    initial_up = run_alembic("upgrade", HEAD)
    down = run_alembic("downgrade", PARENT)
    up = run_alembic("upgrade", HEAD)
    drift = run_alembic("check")
    results.add("W4PG-01", "fresh head, 0011 round-trip and no-drift", initial_up.returncode == down.returncode == up.returncode == drift.returncode == 0, {
        "initial_up_rc": initial_up.returncode, "down_rc": down.returncode, "up_rc": up.returncode, "check_rc": drift.returncode,
        "stderr": (initial_up.stderr + down.stderr + up.stderr + drift.stderr)[-1500:],
    })

    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())
    results.add("W4PG-02", "all nine Wave 4 tables exist", TABLES <= live_tables, sorted(TABLES - live_tables))
    with engine.connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    results.add("W4PG-03", "database is at 0011 head", head == HEAD, head)
    results.add("W4PG-04", "PostgreSQL 16 and pgvector active", version_num >= 160000 and bool(vector), {"server": version_num, "pgvector": vector})

    report_columns = {column["name"] for column in inspector.get_columns("internship_reports")}
    identity_columns = {"user_id", "reporter_id", "author_id", "mobile", "email", "reporter_lookup_hash", "reporter_ciphertext"}
    results.add("W4PG-05", "report content table has no reporter identity", not (report_columns & identity_columns), sorted(report_columns & identity_columns))

    missing_constraints = {}
    for table, expected in EXPECTED_CONSTRAINTS.items():
        actual = {item["name"] for item in inspector.get_check_constraints(table)}
        actual |= {item["name"] for item in inspector.get_unique_constraints(table)}
        # The project's SQLAlchemy naming convention prefixes CHECK names with
        # ``ck_<table>_`` on PostgreSQL. Compare the explicit semantic suffix,
        # not a dialect-rendered prefix.
        def rendered_matches(name: str, value: str) -> bool:
            if value == name or value.endswith(f"_{name}"):
                return True
            prefix = f"ck_{table}_"
            if value.startswith(prefix):
                semantic = value[len(prefix):]
                # PostgreSQL's 63-byte identifier limit makes SQLAlchemy
                # replace the tail of long convention names with ``_<hash>``.
                if len(semantic) > 5 and semantic[-5] == "_":
                    semantic = semantic[:-5]
                return name.startswith(semantic)
            return False

        present = {name for name in expected if any(rendered_matches(name, value) for value in actual)}
        if expected - present:
            missing_constraints[table] = {"missing": sorted(expected - present), "actual": sorted(actual)}
    results.add("W4PG-06", "named CHECK and UNIQUE constraints match contract", not missing_constraints, missing_constraints)

    unsupported_fks = []
    for table in TABLES:
        index_columns = {column for item in inspector.get_indexes(table) for column in item.get("column_names") or []}
        unique_columns = {column for item in inspector.get_unique_constraints(table) for column in item.get("column_names") or []}
        for fk in inspector.get_foreign_keys(table):
            constrained = set(fk.get("constrained_columns") or [])
            if not constrained <= index_columns | unique_columns:
                unsupported_fks.append({"table": table, "columns": sorted(constrained)})
    results.add("W4PG-07", "every Wave 4 foreign key has a supporting index", not unsupported_fks, unsupported_fks)

    actor_id = uuid.UUID("00000000-0000-4000-8000-0000000000de")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        if session.get(User, actor_id) is None:
            session.add(User(id=actor_id, role="student", status="active"))
            session.commit()
    actor = ActorContext(user_id=actor_id, roles=frozenset({Role.STUDENT}))
    key = f"wave4-pg-concurrent-{uuid.uuid4()}"
    payload = ReportDraftCreate(
        organisation_name="PG16 Private Canary Organisation",
        listing_application_ref="PG16-REF-269",
        experience_start_date="2026-01-01",
        experience_end_date="2026-01-31",
        categories=["positive_experience"],
        narrative="A target-runtime factual report used to prove concurrent idempotency and row locking.",
        privacy_mode="anonymous",
        consent_accepted=True,
        consent_version=settings.internship_report_consent_version,
    )

    def concurrent_create():
        with SessionLocal() as session:
            return str(create_report(payload, key, session, actor).id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        created_ids = list(pool.map(lambda _: concurrent_create(), range(2)))
    with SessionLocal() as session:
        count = session.scalar(select(text("count(*)")).select_from(InternshipReport).where(InternshipReport.idempotency_key == key))
        row = session.scalar(select(InternshipReport).where(InternshipReport.idempotency_key == key))
        vault = session.scalar(select(ReporterIdentityVault).where(ReporterIdentityVault.report_id == row.id))
    results.add("W4PG-08", "concurrent idempotent create has one durable row", len(set(created_ids)) == 1 and count == 1, {"ids": created_ids, "count": count})
    results.add("W4PG-09", "reporter identity is encrypted and separately decryptable", bool(vault) and str(actor_id) not in vault.reporter_ciphertext and decrypt(vault.reporter_ciphertext) == str(actor_id), {"ciphertext_prefix": vault.reporter_ciphertext[:8] if vault else None})

    def concurrent_update(suffix: str):
        with SessionLocal() as session:
            try:
                result = update_report(
                    row.id,
                    ReportDraftPatch(expected_version=1, narrative=("Concurrent factual update " + suffix + " ") * 4),
                    session,
                    actor,
                )
                return {"status": 200, "version": result.version}
            except HTTPException as exc:
                return {"status": exc.status_code, "code": exc.detail.get("code")}

    with ThreadPoolExecutor(max_workers=2) as pool:
        updated = list(pool.map(concurrent_update, ("A", "B")))
    results.add("W4PG-10", "FOR UPDATE permits one writer and rejects stale competitor", sorted(item["status"] for item in updated) == [200, 409] and any(item.get("code") == "stale_report_version" for item in updated), updated)

    forbidden = [str(actor_id), "private-proof.pdf"]
    findings = []
    with engine.connect() as connection:
        for table in TABLES:
            for column in inspector.get_columns(table):
                if str(column["type"]).upper().startswith(("VARCHAR", "TEXT", "JSON")):
                    values = connection.execute(text(f'SELECT CAST("{column["name"]}" AS TEXT) FROM "{table}" WHERE "{column["name"]}" IS NOT NULL'))
                    for value, in values:
                        for marker in forbidden:
                            if marker in value:
                                findings.append({"table": table, "column": column["name"], "marker": "reporter_uuid" if marker == str(actor_id) else marker})
    results.add("W4PG-11", "raw target storage contains no reporter UUID or filename", not findings, findings)
    results.add("W4PG-12", "public label feature is fail-closed", settings.internship_risk_labels_enabled is False, settings.internship_risk_labels_enabled)

    summary = {
        "gate": "wave4_postgres", "status": "PASS" if not results.failed else "FAIL", "executed": True,
        "server_version_num": version_num, "pgvector": vector, "head": head,
        "tables": sorted(TABLES), "results": results.rows, "failed_assertions": results.failed,
    }
    output.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    return 0 if not results.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
