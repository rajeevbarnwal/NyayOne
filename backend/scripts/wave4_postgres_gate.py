"""PostgreSQL 16 + pgvector release gate for SAATHI-269/274 reporting.

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
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

def _expected_alembic_head() -> str:
    versions_dir = BACKEND / "app" / "db" / "migrations" / "versions"
    files = [p.stem for p in versions_dir.glob("*.py")]
    numbered = [f for f in files if f.split("_", 1)[0].isdigit()]
    assert numbered, f"No alembic version files found in {versions_dir}"
    return max(numbered, key=lambda s: int(s.split("_", 1)[0]))


BLOCKED = 78
HEAD = _expected_alembic_head()
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
    "moderation_cases": {"uq_moderation_cases_report_id", "state", "version_positive", "claim_state_consistent"},
    "moderation_assignments": {"uq_moderation_assignment_actor", "active_release_consistent"},
    "moderation_actions": {"uq_moderation_actions_idempotency_key", "action", "reason_code", "reason_ciphertext_nontrivial", "case_version_minimum"},
    "duplicate_clusters": {"uq_duplicate_clusters_idempotency_key", "category", "state", "organisation_hash_length", "organisation_ciphertext_nontrivial", "window_order", "version_positive"},
    "duplicate_cluster_members": {"uq_duplicate_cluster_member"},
    "risk_signals": {"uq_risk_signals_cluster_id", "reporter_count_bounded", "distinct_reporters_positive", "version_positive", "publication_disabled"},
    "risk_signal_approvals": {"uq_risk_signal_approval_actor", "actor_role", "decision"},
    "moderation_notification_outbox": {"uq_moderation_notification_outbox_idempotency_key", "event_kind", "state", "attempts_nonnegative"},
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


def is_isolated_gate_target(
    database_url: str, app_env: str, mutation_allowed: bool
) -> bool:
    """Permit destructive release probes only on explicit loopback QA targets."""
    parsed = make_url(database_url)
    database_name = (parsed.database or "").casefold()
    database_host = (parsed.host or "").casefold()
    return (
        app_env.casefold() in {"test", "testing"}
        and database_host in {"127.0.0.1", "localhost", "::1"}
        and any(
            marker in database_name
            for marker in ("test", "qa", "e2e", "wave4", "saathi274")
        )
        and mutation_allowed
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
    parsed_database_url = make_url(database_url)
    database_name = (parsed_database_url.database or "").casefold()
    database_host = (parsed_database_url.host or "").casefold()
    app_env = os.getenv("APP_ENV", "").casefold()
    mutation_allowed = os.getenv("WAVE4_GATE_ALLOW_MUTATION") == "true"
    isolated = is_isolated_gate_target(database_url, app_env, mutation_allowed)
    if not isolated:
        summary = {
            "gate": "wave4_postgres",
            "status": "BLOCKED",
            "executed": False,
            "reason": "target is not an explicitly isolated test database",
            "database_name": database_name,
            "database_host": database_host,
            "app_env": app_env,
            "mutation_allowed": mutation_allowed,
        }
        output.write_text(json.dumps(summary, indent=2) + "\n")
        print(
            "BLOCKED: Wave 4 gate requires explicit mutation opt-in and a "
            "loopback isolated QA database"
        )
        return BLOCKED

    from app.api.v1.internship_reports import create_report, submit_report, update_report
    from app.core.auth import ActorContext, Role
    from app.core.config import settings
    from app.core.crypto import decrypt
    from app.db.session import get_engine, get_sessionmaker
    from app.models.registration import User
    from app.models.wave4 import InternshipReport, ReporterIdentityVault
    from app.schemas.moderation import (
        ModerationActionIn,
        RiskClusterCreate,
        RiskSignalApprovalIn,
    )
    from app.schemas.reporting import ReportDraftCreate, ReportDraftPatch, ReportSubmit
    from app.services.moderation_service import (
        ModerationError,
        act_on_case,
        approve_cluster,
        create_cluster,
    )

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
    results.add("W4PG-01", "fresh head, Wave 4 round-trip and no-drift", initial_up.returncode == down.returncode == up.returncode == drift.returncode == 0, {
        "initial_up_rc": initial_up.returncode, "down_rc": down.returncode, "up_rc": up.returncode, "check_rc": drift.returncode,
        "stderr": (initial_up.stderr + down.stderr + up.stderr + drift.stderr)[-1500:],
    })

    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())
    results.add("W4PG-02", "all seventeen Wave 4 tables exist", TABLES <= live_tables, sorted(TABLES - live_tables))
    with engine.connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    results.add("W4PG-03", "database is at 0012 head", head == HEAD, head)
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

    moderator_ids = (
        uuid.UUID("00000000-0000-4000-8000-0000000000c4"),
        uuid.UUID("00000000-0000-4000-8000-0000000000c5"),
    )
    safety_id = uuid.UUID("00000000-0000-4000-8000-0000000000c6")
    with SessionLocal() as session:
        for value in moderator_ids:
            if session.get(User, value) is None:
                session.add(User(id=value, role="moderator", status="active"))
        if session.get(User, safety_id) is None:
            session.add(User(id=safety_id, role="safety_officer", status="active"))
        session.commit()
    moderators = tuple(
        ActorContext(user_id=value, roles=frozenset({Role.MODERATOR}))
        for value in moderator_ids
    )
    safety_actor = ActorContext(
        user_id=safety_id, roles=frozenset({Role.SAFETY_OFFICER})
    )

    with SessionLocal() as session:
        target_version = session.get(InternshipReport, row.id).version
    with SessionLocal() as session:
        submit_report(
            row.id,
            ReportSubmit(expected_version=target_version),
            session,
            actor,
        )

    def concurrent_claim(index: int):
        with SessionLocal() as session:
            try:
                outcome = act_on_case(
                    session,
                    moderators[index],
                    row.id,
                    ModerationActionIn(
                        action="claim",
                        reason_code="review_started",
                        reason_detail="Starting target-runtime moderation review.",
                        expected_version=1,
                    ),
                    f"wave4-pg-claim-{uuid.uuid4()}",
                )
                return {"status": 200, "version": outcome.case_version}
            except ModerationError as error:
                return {"status": error.status_code, "code": error.code}

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(concurrent_claim, (0, 1)))
    results.add(
        "W4PG-13",
        "moderation claim lock admits one moderator and rejects the competitor",
        sorted(item["status"] for item in claims) == [200, 409]
        and any(
            item.get("code")
            in {"stale_moderation_case", "moderation_case_already_claimed"}
            for item in claims
        ),
        claims,
    )

    aggregate_report_ids: list[uuid.UUID] = []
    for index in range(3):
        reporter_id = uuid.UUID(
            f"00000000-0000-4000-8000-{index + 301:012d}"
        )
        with SessionLocal() as session:
            if session.get(User, reporter_id) is None:
                session.add(User(id=reporter_id, role="student", status="active"))
                session.commit()
        reporter = ActorContext(
            user_id=reporter_id, roles=frozenset({Role.STUDENT})
        )
        cluster_payload = ReportDraftCreate(
            organisation_name="PG16 Moderation Cluster Organisation",
            listing_application_ref=f"PG16-MOD-{index}",
            experience_start_date="2026-01-01",
            experience_end_date="2026-01-31",
            categories=["unsafe_environment"],
            narrative=(
                "Independent factual moderation evidence for the target-runtime "
                f"aggregate workflow, reporter {index}."
            ),
            privacy_mode="anonymous",
            consent_accepted=True,
            consent_version=settings.internship_report_consent_version,
        )
        with SessionLocal() as session:
            created = create_report(
                cluster_payload,
                f"wave4-pg-moderation-report-{uuid.uuid4()}",
                session,
                reporter,
            )
            report_id = created.id
        with SessionLocal() as session:
            submitted = submit_report(
                report_id,
                ReportSubmit(expected_version=created.version),
                session,
                reporter,
            )
        if submitted.status != "moderation_pending":
            raise RuntimeError("target-runtime report did not enter moderation")
        with SessionLocal() as session:
            claim = act_on_case(
                session,
                moderators[0],
                report_id,
                ModerationActionIn(
                    action="claim",
                    reason_code="review_started",
                    reason_detail="Starting target-runtime aggregate review.",
                    expected_version=1,
                ),
                f"wave4-pg-cluster-claim-{uuid.uuid4()}",
            )
        with SessionLocal() as session:
            approved = act_on_case(
                session,
                moderators[0],
                report_id,
                ModerationActionIn(
                    action="approve_aggregate_only",
                    reason_code="aggregate_criteria_met",
                    reason_detail=(
                        "Aggregate-only criteria verified on PostgreSQL."
                    ),
                    expected_version=claim.case_version,
                ),
                f"wave4-pg-cluster-approve-{uuid.uuid4()}",
            )
        if approved.case_state == "approved_aggregate_only":
            aggregate_report_ids.append(report_id)

    with SessionLocal() as session:
        cluster = create_cluster(
            session,
            moderators[0],
            RiskClusterCreate(
                report_ids=aggregate_report_ids,
                category="unsafe_environment",
            ),
            f"wave4-pg-risk-cluster-{uuid.uuid4()}",
        )
    results.add(
        "W4PG-14",
        "three distinct approved reporters meet the private threshold with small-count suppression",
        len(aggregate_report_ids) == 3
        and cluster.threshold_met
        and cluster.small_count_suppressed
        and cluster.public_count is None
        and cluster.publication_ready is False,
        cluster.model_dump(mode="json"),
    )

    with SessionLocal() as session:
        moderator_approval = approve_cluster(
            session,
            moderators[0],
            cluster.id,
            RiskSignalApprovalIn(
                decision="approve", reason_code="moderator_policy_check"
            ),
        )
    with SessionLocal() as session:
        dual_approval = approve_cluster(
            session,
            safety_actor,
            cluster.id,
            RiskSignalApprovalIn(
                decision="approve", reason_code="safety_policy_check"
            ),
        )
    results.add(
        "W4PG-15",
        "moderator plus safety approval is durable but cannot enable publication",
        moderator_approval.moderator_approved
        and dual_approval.moderator_approved
        and dual_approval.safety_legal_approved
        and dual_approval.publication_ready is False,
        dual_approval.model_dump(mode="json"),
    )

    moderation_reason = "Aggregate-only criteria verified on PostgreSQL."
    reason_findings = []
    with engine.connect() as connection:
        for table in TABLES:
            for column in inspector.get_columns(table):
                if str(column["type"]).upper().startswith(
                    ("VARCHAR", "TEXT", "JSON")
                ):
                    values = connection.execute(
                        text(
                            f'SELECT CAST("{column["name"]}" AS TEXT) '
                            f'FROM "{table}" '
                            f'WHERE "{column["name"]}" IS NOT NULL'
                        )
                    )
                    for value, in values:
                        if moderation_reason in value:
                            reason_findings.append(
                                {"table": table, "column": column["name"]}
                            )
    results.add(
        "W4PG-16",
        "moderator reason detail is absent from searchable plaintext",
        not reason_findings,
        reason_findings,
    )

    summary = {
        "gate": "wave4_postgres", "status": "PASS" if not results.failed else "FAIL", "executed": True,
        "server_version_num": version_num, "pgvector": vector, "head": head,
        "tables": sorted(TABLES), "results": results.rows, "failed_assertions": results.failed,
    }
    output.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    return 0 if not results.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
