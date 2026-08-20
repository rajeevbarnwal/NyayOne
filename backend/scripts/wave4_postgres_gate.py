"""PostgreSQL 16 + pgvector release gate for SAATHI-269/274 reporting.

This gate intentionally exits 78 when the target runtime is absent. SQLite is
useful regression coverage, but cannot prove PostgreSQL row locks, target DDL,
typed JSON, timestamptz or concurrent idempotency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import is_isolated_wave4_database_url

BLOCKED = 78
HEAD = "0016_dob_hash_reconcile"
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
    "reporter_identity_access_requests": {
        "state", "executed_timestamp_required", "version_positive",
        "request_fingerprint_length", "metadata_must_be_null",
        "uq_reporter_identity_access_requests_idempotency_key",
    },
    "reporter_identity_access_approvals": {
        "uq_identity_access_approver", "decision", "approver_role",
        "metadata_must_be_null", "uq_reporter_identity_access_approvals_idempotency_key",
    },
    "moderation_handoffs": {"uq_moderation_handoffs_report_id", "state", "version_positive"},
    "internship_reporting_outbox": {
        "uq_internship_reporting_outbox_idempotency_key", "event_kind", "state", "attempts_nonnegative",
    },
    "moderation_cases": {"uq_moderation_cases_report_id", "state", "version_positive", "claim_state_consistent"},
    "moderation_assignments": {"uq_moderation_assignment_actor", "active_release_consistent"},
    "moderation_actions": {"uq_moderation_actions_idempotency_key", "action", "reason_code", "reason_ciphertext_nontrivial", "case_version_minimum"},
    "duplicate_clusters": {"uq_duplicate_clusters_idempotency_key", "category", "state", "organisation_hash_length", "organisation_ciphertext_nontrivial", "window_order", "version_positive"},
    "duplicate_cluster_members": {
        "uq_duplicate_cluster_member", "uq_report_risk_cluster_category_active", "category",
    },
    "risk_signals": {"uq_risk_signals_cluster_id", "reporter_count_bounded", "distinct_reporters_positive", "version_positive", "publication_disabled"},
    "risk_signal_approvals": {
        "uq_risk_signal_approval_actor", "actor_role", "decision", "reason_code",
    },
    "moderation_notification_outbox": {"uq_moderation_notification_outbox_idempotency_key", "event_kind", "state", "attempts_nonnegative"},
    "published_risk_labels": {
        "uq_published_risk_labels_risk_signal_id", "category", "status",
        "source_type", "public_count_suppressed", "version_positive", "metadata_must_be_null",
    },
    "publication_decisions": {
        "uq_publication_decisions_idempotency_key", "decision", "expected_version_positive",
        "reason_code", "request_fingerprint_length", "metadata_must_be_null",
    },
    "organisation_response_requests": {
        "uq_organisation_response_requests_token_hash",
        "uq_organisation_response_requests_idempotency_key", "state", "request_kind",
        "representative_verification_method", "representative_ref_hash_length",
        "token_hash_length", "request_fingerprint_length", "used_timestamp_matches",
        "target_response_matches_kind", "uq_response_requests_pending_initial_label",
        "version_positive", "metadata_must_be_null",
    },
    "organisation_responses": {
        "uq_organisation_responses_request_id", "uq_organisation_responses_idempotency_key",
        "uq_organisation_responses_current_label", "state", "response_ciphertext_nontrivial",
        "response_digest_length", "request_fingerprint_length", "moderated_timestamp_matches",
        "current_matches_approved", "version_positive", "metadata_must_be_null",
    },
    "response_moderation": {
        "uq_response_moderation_response_id", "uq_response_moderation_idempotency_key",
        "decision", "reason_code", "response_version_minimum", "request_fingerprint_length",
        "metadata_must_be_null",
    },
    "notification_outbox": {
        "uq_notification_outbox_idempotency_key", "event_kind", "state",
        "attempts_nonnegative", "delivery_secret_scope", "sent_timestamp_required",
        "claim_timestamp_matches", "metadata_must_be_null",
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


def is_isolated_gate_target(
    database_url: str,
    test_database_url: str,
    app_env: str,
    mutation_allowed: bool,
) -> bool:
    """Permit destructive release probes only on explicit loopback QA targets."""
    return (
        app_env.casefold() in {"test", "testing"}
        and bool(test_database_url)
        and test_database_url == database_url
        and is_isolated_wave4_database_url(database_url)
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
    test_database_url = os.getenv("TEST_DATABASE_URL", "").strip()
    mutation_allowed = os.getenv("WAVE4_GATE_ALLOW_MUTATION") == "true"
    isolated = is_isolated_gate_target(
        database_url, test_database_url, app_env, mutation_allowed
    )
    if not isolated:
        summary = {
            "gate": "wave4_postgres",
            "status": "BLOCKED",
            "executed": False,
            "reason": "target is not an explicitly isolated test database",
            "database_name": database_name,
            "database_host": database_host,
            "app_env": app_env,
            "test_database_matches": bool(test_database_url)
            and test_database_url == database_url,
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
    from app.core.crypto import decrypt, encrypt, key_version
    from app.db.session import get_engine, get_sessionmaker
    from app.models.registration import User
    from app.models.wave4 import (
        DuplicateCluster,
        DuplicateClusterMember,
        InternshipReport,
        InternshipReportCategory,
        InternshipReportEvidence,
        ModerationCase,
        NotificationOutbox,
        OrganisationResponse,
        OrganisationResponseRequest,
        PublicationDecision,
        PublishedRiskLabel,
        ReporterIdentityAccessRequest,
        ReporterIdentityVault,
        ResponseModeration,
        RiskSignal,
        RiskSignalApproval,
    )
    from app.schemas.moderation import (
        ModerationActionIn,
        IdentityAccessApprovalIn,
        IdentityAccessRequestIn,
        RiskClusterCreate,
        RiskSignalApprovalIn,
    )
    from app.schemas.reporting import ReportDraftCreate, ReportDraftPatch, ReportSubmit
    from app.schemas.risk_labels import (
        OrganisationResponseDecisionIn,
        OrganisationResponseIn,
        OrganisationResponseRequestIn,
        RiskLabelPublishIn,
    )
    from app.services.moderation_service import (
        ModerationError,
        act_on_case,
        approve_cluster,
        create_cluster,
        decide_identity_access,
        execute_identity_access,
        request_identity_access,
    )
    from app.services.risk_label_service import (
        RiskLabelError,
        create_response_request,
        decide_response,
        publication_gate_open,
        public_labels,
        publish_risk_label,
        submit_response,
    )
    from app.services.risk_notification_relay import (
        DeterministicResponseInvitationProvider,
        _claim,
        _finish,
        relay_response_invitations,
    )
    from app.services.moderation_service import _months_ago

    engine = get_engine()
    with engine.connect() as connection:
        version_num = int(connection.scalar(text("SHOW server_version_num")))
    if version_num < 160000:
        summary = {"gate": "wave4_postgres", "status": "BLOCKED", "executed": False, "server_version_num": version_num, "pgvector": None}
        output.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"BLOCKED: prerequisite runtime absent: PostgreSQL 16 (actual {version_num})")
        return BLOCKED

    results = Results()
    migration_steps: dict[str, subprocess.CompletedProcess[str]] = {}
    for stage, command in (
        ("initial_up", ("upgrade", HEAD)),
        ("down", ("downgrade", PARENT)),
        ("up", ("upgrade", HEAD)),
        ("check", ("check",)),
    ):
        process = run_alembic(*command)
        migration_steps[stage] = process
        if process.returncode != 0:
            results.add(
                "W4PG-01",
                "fresh head, Wave 4 round-trip and no-drift",
                False,
                {
                    "failed_stage": stage,
                    "return_code": process.returncode,
                    "stderr": process.stderr[-1500:],
                    "stdout": process.stdout[-1500:],
                },
            )
            output.write_text(json.dumps({
                "gate": "wave4_postgres",
                "status": "FAIL",
                "executed": True,
                "server_version_num": version_num,
                "pgvector": None,
                "head": None,
                "tables": [],
                "results": results.rows,
                "failed_assertions": results.failed,
            }, indent=2, default=str) + "\n")
            return 1
    results.add(
        "W4PG-01",
        "fresh head, Wave 4 round-trip and no-drift",
        True,
        {stage: process.returncode for stage, process in migration_steps.items()},
    )

    # Revision 0001 owns ``CREATE EXTENSION vector``.  A genuinely fresh QA
    # database therefore has no installed extension until the migration has
    # run; treating that pre-migration state as a missing prerequisite makes
    # the release gate impossible to execute from empty state.
    with engine.connect() as connection:
        vector = connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        )

    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())
    results.add("W4PG-02", "all twenty-three Wave 4 tables exist", TABLES <= live_tables, sorted(TABLES - live_tables))
    with engine.connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    results.add("W4PG-03", "database is at 0016 head", head == HEAD, head)
    results.add("W4PG-04", "PostgreSQL 16 and pgvector active", version_num >= 160000 and bool(vector), {"server": version_num, "pgvector": vector})

    report_columns = {column["name"] for column in inspector.get_columns("internship_reports")}
    identity_columns = {"user_id", "reporter_id", "author_id", "mobile", "email", "reporter_lookup_hash", "reporter_ciphertext"}
    results.add("W4PG-05", "report content table has no reporter identity", not (report_columns & identity_columns), sorted(report_columns & identity_columns))

    missing_constraints = {}
    for table, expected in EXPECTED_CONSTRAINTS.items():
        actual = {item["name"] for item in inspector.get_check_constraints(table)}
        actual |= {item["name"] for item in inspector.get_unique_constraints(table)}
        actual |= {item["name"] for item in inspector.get_indexes(table) if item.get("unique")}
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
            evidence_marker = f"wave4-pg-clean-evidence-{index}".encode()
            session.add(InternshipReportEvidence(
                report_id=report_id,
                object_ref=f"wave4-pg/{report_id}/evidence",
                mime_type="application/pdf",
                size_bytes=len(evidence_marker),
                checksum_sha256=hashlib.sha256(evidence_marker).hexdigest(),
                scan_state="clean",
                retention_policy="qa-gate",
            ))
            session.commit()
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

    identity_key = f"wave4-pg-identity-idem-{uuid.uuid4()}"
    identity_payload = IdentityAccessRequestIn(
        reason_detail=(
            "Two-person access is required to investigate an immediate "
            "safety escalation without exposing identity in routine views."
        )
    )

    def concurrent_identity_request():
        with SessionLocal() as session:
            try:
                value = request_identity_access(
                    session, safety_actor, row.id, identity_payload, identity_key
                )
                return {"status": 201, "id": str(value.id)}
            except ModerationError as error:
                return {"status": error.status_code, "code": error.code}

    with ThreadPoolExecutor(max_workers=2) as pool:
        identity_race = list(pool.map(lambda _: concurrent_identity_request(), range(2)))
    with SessionLocal() as session:
        identity_count = session.scalar(select(func.count()).select_from(
            ReporterIdentityAccessRequest
        ).where(ReporterIdentityAccessRequest.idempotency_key == identity_key))
    results.add(
        "W4PG-28",
        "concurrent identity-access same-key create returns one durable winner",
        all(item["status"] == 201 for item in identity_race)
        and len({item["id"] for item in identity_race}) == 1
        and identity_count == 1,
        {"race": identity_race, "count": identity_count},
    )
    identity_request_id = uuid.UUID(identity_race[0]["id"])
    second_safety_id = uuid.UUID("00000000-0000-4000-8000-0000000000c8")
    legal_identity_id = uuid.UUID("00000000-0000-4000-8000-0000000000c7")
    with SessionLocal() as session:
        for value, role in (
            (second_safety_id, "safety_officer"),
            (legal_identity_id, "legal_reviewer"),
        ):
            if session.get(User, value) is None:
                session.add(User(id=value, role=role, status="active"))
        session.commit()
    second_safety_actor = ActorContext(
        user_id=second_safety_id, roles=frozenset({Role.SAFETY_OFFICER})
    )
    legal_identity_actor = ActorContext(
        user_id=legal_identity_id, roles=frozenset({Role.LEGAL_REVIEWER})
    )
    with SessionLocal() as session:
        identity_request = session.get(
            ReporterIdentityAccessRequest, identity_request_id
        )
        first_identity_approval = decide_identity_access(
            session, second_safety_actor, identity_request_id,
            IdentityAccessApprovalIn(
                decision="approve", expected_version=identity_request.version
            ),
            f"wave4-pg-identity-approve-safety-{uuid.uuid4()}",
        )
    with SessionLocal() as session:
        second_identity_approval = decide_identity_access(
            session, legal_identity_actor, identity_request_id,
            IdentityAccessApprovalIn(
                decision="approve", expected_version=first_identity_approval.version
            ),
            f"wave4-pg-identity-approve-legal-{uuid.uuid4()}",
        )
    with SessionLocal() as session:
        target_vault = session.scalar(select(ReporterIdentityVault).where(
            ReporterIdentityVault.report_id == row.id
        ))
        other_vault = session.scalar(select(ReporterIdentityVault).where(
            ReporterIdentityVault.report_id != row.id
        ).order_by(ReporterIdentityVault.id))
        original_identity_ciphertext = target_vault.reporter_ciphertext
        original_identity_key_version = target_vault.key_version
        target_vault.reporter_ciphertext = other_vault.reporter_ciphertext
        target_vault.key_version = other_vault.key_version
        session.commit()
    try:
        with SessionLocal() as session:
            execute_identity_access(
                session, safety_actor, identity_request_id,
                second_identity_approval.version,
            )
        swapped_identity_code = "unexpected_success"
    except ModerationError as error:
        swapped_identity_code = error.code
    with SessionLocal() as session:
        target_vault = session.scalar(select(ReporterIdentityVault).where(
            ReporterIdentityVault.report_id == row.id
        ))
        target_vault.reporter_ciphertext = original_identity_ciphertext
        target_vault.key_version = original_identity_key_version
        session.commit()
    with SessionLocal() as session:
        identity_execution = execute_identity_access(
            session, safety_actor, identity_request_id,
            second_identity_approval.version,
        )
    results.add(
        "W4PG-32",
        "dual-control identity access rejects valid ciphertext swap before execution",
        swapped_identity_code == "reporter_identity_integrity_conflict"
        and identity_execution.state == "executed"
        and identity_execution.reporter_identity == str(actor_id),
        {"swap_code": swapped_identity_code, "state": identity_execution.state},
    )

    # Public projection target-runtime lifecycle. The production switch remains
    # false; only the isolated QA seam (validated above) may execute this leg.
    def approved_source(
        *, prefix: str, index: int, reporter_id: uuid.UUID,
        category: str, organisation: str,
    ) -> uuid.UUID:
        with SessionLocal() as session:
            if session.get(User, reporter_id) is None:
                session.add(User(id=reporter_id, role="student", status="active"))
                session.commit()
        reporter = ActorContext(
            user_id=reporter_id, roles=frozenset({Role.STUDENT})
        )
        payload = ReportDraftCreate(
            organisation_name=organisation,
            listing_application_ref=f"{prefix}-{index}",
            experience_start_date="2026-01-01",
            experience_end_date="2026-01-31",
            categories=[category],
            narrative=(
                "Independent target-runtime threshold source with factual "
                f"moderation context {prefix} {index}."
            ),
            privacy_mode="anonymous",
            consent_accepted=True,
            consent_version=settings.internship_report_consent_version,
        )
        with SessionLocal() as session:
            created = create_report(
                payload, f"{prefix}-create-{index}-{uuid.uuid4()}", session, reporter
            )
            report_id, version = created.id, created.version
            marker = f"{prefix}-evidence-{index}".encode()
            session.add(InternshipReportEvidence(
                report_id=report_id,
                object_ref=f"wave4-pg/{prefix}/{report_id}",
                mime_type="application/pdf", size_bytes=len(marker),
                checksum_sha256=hashlib.sha256(marker).hexdigest(),
                scan_state="clean", retention_policy="qa-gate",
            ))
            session.commit()
        with SessionLocal() as session:
            submit_report(
                report_id, ReportSubmit(expected_version=version), session, reporter
            )
        with SessionLocal() as session:
            claim = act_on_case(
                session, moderators[0], report_id,
                ModerationActionIn(
                    action="claim", reason_code="review_started",
                    reason_detail="Starting target-runtime threshold review.",
                    expected_version=1,
                ),
                f"{prefix}-claim-{index}-{uuid.uuid4()}",
            )
        with SessionLocal() as session:
            act_on_case(
                session, moderators[0], report_id,
                ModerationActionIn(
                    action="approve_aggregate_only",
                    reason_code="aggregate_criteria_met",
                    reason_detail="Aggregate-only target-runtime criteria verified.",
                    expected_version=claim.case_version,
                ),
                f"{prefix}-approve-{index}-{uuid.uuid4()}",
            )
        return report_id

    def threshold_cluster(
        *, prefix: str, category: str, reporter_ids: list[uuid.UUID]
    ):
        source_ids = [
            approved_source(
                prefix=prefix, index=index, reporter_id=reporter_id,
                category=category,
                organisation=f"{prefix.replace('-', ' ').title()} Organisation",
            )
            for index, reporter_id in enumerate(reporter_ids)
        ]
        with SessionLocal() as session:
            return create_cluster(
                session, moderators[0],
                RiskClusterCreate(report_ids=source_ids, category=category),
                f"{prefix}-cluster-{uuid.uuid4()}",
            )

    minimum = settings.internship_risk_min_distinct_reporters
    minus = threshold_cluster(
        prefix="pg16-minus", category="harassment",
        reporter_ids=[uuid.uuid4() for _ in range(minimum - 1)],
    )
    plus = threshold_cluster(
        prefix="pg16-plus", category="positive_experience",
        reporter_ids=[uuid.uuid4() for _ in range(minimum + 1)],
    )
    repeated_reporter = uuid.uuid4()
    repeated = threshold_cluster(
        prefix="pg16-repeated", category="excessive_hours",
        reporter_ids=[repeated_reporter for _ in range(minimum)],
    )

    concurrent_cluster_sources = [
        approved_source(
            prefix="pg16-cluster-race", index=index,
            reporter_id=uuid.uuid4(), category="discrimination",
            organisation="PG16 Cluster Race Organisation",
        )
        for index in range(minimum)
    ]
    concurrent_cluster_key = f"wave4-pg-cluster-idem-{uuid.uuid4()}"
    concurrent_cluster_payload = RiskClusterCreate(
        report_ids=concurrent_cluster_sources,
        category="discrimination",
    )

    def concurrent_cluster_create():
        with SessionLocal() as session:
            try:
                value = create_cluster(
                    session, moderators[0], concurrent_cluster_payload,
                    concurrent_cluster_key,
                )
                return {"status": 201, "id": str(value.id)}
            except ModerationError as error:
                return {"status": error.status_code, "code": error.code}

    with ThreadPoolExecutor(max_workers=2) as pool:
        cluster_race = list(pool.map(lambda _: concurrent_cluster_create(), range(2)))
    try:
        with SessionLocal() as session:
            create_cluster(
                session, moderators[0], concurrent_cluster_payload,
                f"wave4-pg-cluster-overlap-{uuid.uuid4()}",
            )
        overlap_code = "unexpected_success"
    except ModerationError as error:
        overlap_code = error.code
    results.add(
        "W4PG-29",
        "same-key cluster race converges and different-key overlap is rejected",
        all(item["status"] == 201 for item in cluster_race)
        and len({item["id"] for item in cluster_race}) == 1
        and overlap_code == "risk_cluster_source_overlap",
        {"race": cluster_race, "overlap_code": overlap_code},
    )
    results.add(
        "W4PG-17",
        "persisted service proves -/= /+ threshold and repeated-reporter exclusion",
        publication_gate_open()
        and minimum >= 3
        and 1 <= settings.internship_risk_window_months <= 24
        and settings.internship_risk_public_count_suppression >= max(5, minimum)
        and minus.distinct_reporter_count == minimum - 1
        and not minus.threshold_met
        and cluster.distinct_reporter_count == minimum
        and cluster.threshold_met
        and plus.distinct_reporter_count == minimum + 1
        and plus.threshold_met
        and repeated.report_count == minimum
        and repeated.distinct_reporter_count == 1
        and not repeated.threshold_met,
        {
            "minimum": minimum,
            "minus": minus.distinct_reporter_count,
            "exact": cluster.distinct_reporter_count,
            "plus": plus.distinct_reporter_count,
            "same_reporter": repeated.distinct_reporter_count,
        },
    )

    cutoff = _months_ago(
        datetime.now(timezone.utc).date(), settings.internship_risk_window_months
    )
    with SessionLocal() as session:
        source_rows = list(session.scalars(select(InternshipReport).where(
            InternshipReport.id.in_(aggregate_report_ids)
        ).order_by(InternshipReport.id)))
        for source in source_rows:
            source.experience_start_date = cutoff
            source.experience_end_date = cutoff
        cluster_row = session.get(DuplicateCluster, cluster.id)
        cluster_row.window_start = cutoff
        cluster_row.window_end = cutoff
        session.commit()
    with SessionLocal() as session:
        first_source = session.get(InternshipReport, aggregate_report_ids[0])
        first_source.experience_start_date = cutoff - timedelta(days=1)
        first_source.experience_end_date = cutoff - timedelta(days=1)
        cluster_row = session.get(DuplicateCluster, cluster.id)
        cluster_row.window_start = cutoff - timedelta(days=1)
        session.commit()
    try:
        with SessionLocal() as session:
            signal_row = session.scalar(select(RiskSignal).where(
                RiskSignal.cluster_id == cluster.id
            ))
            publish_risk_label(
                session,
                safety_actor,
                cluster.id,
                RiskLabelPublishIn(
                    expected_version=signal_row.version,
                    reason_code="qa_governed_publication",
                ),
                f"wave4-pg-before-cutoff-{uuid.uuid4()}",
            )
        before_cutoff_code = "unexpected_success"
    except RiskLabelError as error:
        before_cutoff_code = error.code
    with SessionLocal() as session:
        first_source = session.get(InternshipReport, aggregate_report_ids[0])
        first_source.experience_start_date = cutoff
        first_source.experience_end_date = cutoff
        cluster_row = session.get(DuplicateCluster, cluster.id)
        cluster_row.window_start = cutoff
        session.commit()
    results.add(
        "W4PG-18",
        "rolling 24-month cutoff is inclusive and one day before is rejected",
        before_cutoff_code == "risk_publication_prerequisites_missing",
        {"cutoff": str(cutoff), "before_code": before_cutoff_code},
    )

    with SessionLocal() as session:
        evidence = session.scalar(select(InternshipReportEvidence).where(
            InternshipReportEvidence.report_id == aggregate_report_ids[0]
        ).order_by(InternshipReportEvidence.id))
        evidence.scan_state = "retryable_failure"
        session.commit()
    try:
        with SessionLocal() as session:
            signal_row = session.scalar(select(RiskSignal).where(
                RiskSignal.cluster_id == cluster.id
            ))
            publish_risk_label(
                session, safety_actor, cluster.id,
                RiskLabelPublishIn(
                    expected_version=signal_row.version,
                    reason_code="qa_governed_publication",
                ),
                f"wave4-pg-invalid-source-{uuid.uuid4()}",
            )
        invalid_source_code = "unexpected_success"
    except RiskLabelError as error:
        invalid_source_code = error.code
    with SessionLocal() as session:
        evidence = session.scalar(select(InternshipReportEvidence).where(
            InternshipReportEvidence.report_id == aggregate_report_ids[0]
        ).order_by(InternshipReportEvidence.id))
        evidence.scan_state = "clean"
        cluster_row = session.get(DuplicateCluster, cluster.id)
        original_ciphertext = cluster_row.organisation_ciphertext
        cluster_row.organisation_ciphertext = encrypt("Different QA Organisation")
        cluster_row.key_version = key_version(cluster_row.organisation_ciphertext)
        session.commit()
    try:
        with SessionLocal() as session:
            signal_row = session.scalar(select(RiskSignal).where(
                RiskSignal.cluster_id == cluster.id
            ))
            publish_risk_label(
                session, safety_actor, cluster.id,
                RiskLabelPublishIn(
                    expected_version=signal_row.version,
                    reason_code="qa_governed_publication",
                ),
                f"wave4-pg-tampered-org-{uuid.uuid4()}",
            )
        tampered_org_code = "unexpected_success"
    except RiskLabelError as error:
        tampered_org_code = error.code
    with SessionLocal() as session:
        cluster_row = session.get(DuplicateCluster, cluster.id)
        cluster_row.organisation_ciphertext = original_ciphertext
        cluster_row.key_version = key_version(original_ciphertext)
        session.commit()
    results.add(
        "W4PG-19",
        "live evidence and organisation ciphertext/hash binding fail closed",
        invalid_source_code == tampered_org_code
        == "risk_publication_prerequisites_missing",
        {"evidence": invalid_source_code, "organisation": tampered_org_code},
    )

    concurrent_publish_key = f"wave4-pg-concurrent-publish-{uuid.uuid4()}"

    def concurrent_publish(index: int):
        with SessionLocal() as session:
            try:
                session.execute(text("SET LOCAL lock_timeout = '8s'"))
                signal_row = session.scalar(select(RiskSignal).where(
                    RiskSignal.cluster_id == cluster.id
                ))
                value = publish_risk_label(
                    session, safety_actor, cluster.id,
                    RiskLabelPublishIn(
                        expected_version=signal_row.version,
                        reason_code="qa_governed_publication",
                    ),
                    concurrent_publish_key,
                )
                return {"status": 200, "id": str(value.id)}
            except RiskLabelError as error:
                return {"status": error.status_code, "code": error.code}
            except Exception as error:
                return {"status": 500, "type": type(error).__name__}

    def concurrent_forbidden_source_mutation():
        with SessionLocal() as session:
            try:
                session.execute(text("SET LOCAL lock_timeout = '8s'"))
                case = session.scalar(select(ModerationCase).where(
                    ModerationCase.report_id == aggregate_report_ids[0]
                ))
                act_on_case(
                    session, moderators[0], aggregate_report_ids[0],
                    ModerationActionIn(
                        action="claim", reason_code="review_started",
                        reason_detail="Attempting an invalid post-approval mutation.",
                        expected_version=case.version,
                    ),
                    f"wave4-pg-post-approval-mutation-{uuid.uuid4()}",
                )
                return {"status": 200}
            except ModerationError as error:
                return {"status": error.status_code, "code": error.code}
            except Exception as error:
                return {"status": 500, "type": type(error).__name__}

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(concurrent_publish, index) for index in range(2)]
        futures.append(pool.submit(concurrent_forbidden_source_mutation))
        publication_race = [future.result(timeout=20) for future in futures]
    with SessionLocal() as session:
        labels = list(session.scalars(select(PublishedRiskLabel).join(
            RiskSignal, RiskSignal.id == PublishedRiskLabel.risk_signal_id
        ).where(RiskSignal.cluster_id == cluster.id)))
    publish_successes = [item for item in publication_race if item["status"] == 200]
    try:
        with SessionLocal() as session:
            signal_row = session.scalar(select(RiskSignal).where(
                RiskSignal.cluster_id == cluster.id
            ))
            publish_risk_label(
                session, safety_actor, cluster.id,
                RiskLabelPublishIn(
                    expected_version=signal_row.version,
                    reason_code="qa_governed_publication",
                ),
                f"wave4-pg-competing-publish-{uuid.uuid4()}",
            )
        competing_publish_code = "unexpected_success"
    except RiskLabelError as error:
        competing_publish_code = error.code
    results.add(
        "W4PG-20",
        "same-key publication converges once and source mutation cannot deadlock",
        len(publish_successes) == 2
        and len({item["id"] for item in publish_successes}) == 1
        and len(labels) == 1
        and publication_race[2]["status"] == 409
        and competing_publish_code == "risk_label_already_published",
        {"race": publication_race, "competing_code": competing_publish_code},
    )
    label = labels[0]

    def public_label_visible() -> bool:
        with SessionLocal() as session:
            return any(
                item.id == label.id
                for item in public_labels(session, label.organisation_id).labels
            )

    with SessionLocal() as session:
        signal_row = session.get(RiskSignal, label.risk_signal_id)
        source_member = session.scalar(select(DuplicateClusterMember).where(
            DuplicateClusterMember.cluster_id == signal_row.cluster_id
        ).order_by(DuplicateClusterMember.id))
        source_evidence = session.scalar(select(InternshipReportEvidence).where(
            InternshipReportEvidence.report_id == source_member.report_id
        ).order_by(InternshipReportEvidence.id))
        source_category = session.scalar(select(InternshipReportCategory).where(
            InternshipReportCategory.report_id == source_member.report_id,
            InternshipReportCategory.category == label.category,
        ).order_by(InternshipReportCategory.id))
        source_case = session.scalar(select(ModerationCase).where(
            ModerationCase.report_id == source_member.report_id
        ).order_by(ModerationCase.id))
        source_vault = session.scalar(select(ReporterIdentityVault).where(
            ReporterIdentityVault.report_id == source_member.report_id
        ).order_by(ReporterIdentityVault.id))
        source_report = session.get(InternshipReport, source_member.report_id)
        publish_decision = session.scalar(select(PublicationDecision).where(
            PublicationDecision.published_label_id == label.id,
            PublicationDecision.decision == "publish",
        ))
        mutation_ids = {
            "signal": signal_row.id,
            "evidence": source_evidence.id,
            "category": source_category.id,
            "case": source_case.id,
            "vault": source_vault.id,
            "report": source_report.id,
            "decision": publish_decision.id,
        }
        original_start_date = source_report.experience_start_date
        original_date = source_report.experience_end_date

    live_mutations: list[tuple[str, bool]] = []

    def mutation_probe(name: str, mutate, restore) -> None:
        with SessionLocal() as session:
            mutate(session)
            session.commit()
        hidden = not public_label_visible()
        with SessionLocal() as session:
            restore(session)
            session.commit()
        live_mutations.append((name, hidden and public_label_visible()))

    mutation_probe(
        "evidence",
        lambda session: setattr(
            session.get(InternshipReportEvidence, mutation_ids["evidence"]),
            "scan_state", "infected",
        ),
        lambda session: setattr(
            session.get(InternshipReportEvidence, mutation_ids["evidence"]),
            "scan_state", "clean",
        ),
    )
    for name, model, field, invalid, valid in (
        ("category_deleted", InternshipReportCategory, "deleted_at", datetime.now(timezone.utc), None),
        ("case_state", ModerationCase, "state", "rejected", "approved_aggregate_only"),
        ("report_status", InternshipReport, "status", "rejected", "approved"),
        ("vault_deleted", ReporterIdentityVault, "deleted_at", datetime.now(timezone.utc), None),
        ("publication_decision_deleted", PublicationDecision, "deleted_at", datetime.now(timezone.utc), None),
    ):
        ident = mutation_ids[
            "category" if model is InternshipReportCategory else
            "case" if model is ModerationCase else
            "report" if model is InternshipReport else
            "vault" if model is ReporterIdentityVault else "decision"
        ]
        mutation_probe(
            name,
            lambda session, m=model, i=ident, f=field, v=invalid: setattr(
                session.get(m, i), f, v
            ),
            lambda session, m=model, i=ident, f=field, v=valid: setattr(
                session.get(m, i), f, v
            ),
        )
    def move_report_outside_window(session) -> None:
        report = session.get(InternshipReport, mutation_ids["report"])
        report.experience_start_date = cutoff - timedelta(days=2)
        report.experience_end_date = cutoff - timedelta(days=1)

    def restore_report_window(session) -> None:
        report = session.get(InternshipReport, mutation_ids["report"])
        report.experience_start_date = original_start_date
        report.experience_end_date = original_date

    mutation_probe(
        "outside_window",
        move_report_outside_window,
        restore_report_window,
    )
    with SessionLocal() as session:
        live_signal = session.get(RiskSignal, mutation_ids["signal"])
        original_report_count = live_signal.report_count
        original_signal_label = live_signal.neutral_label
    mutation_probe(
        "signal_count",
        lambda session: setattr(
            session.get(RiskSignal, mutation_ids["signal"]),
            "report_count", original_report_count + 1,
        ),
        lambda session: setattr(
            session.get(RiskSignal, mutation_ids["signal"]),
            "report_count", original_report_count,
        ),
    )
    mutation_probe(
        "signal_label",
        lambda session: setattr(
            session.get(RiskSignal, mutation_ids["signal"]),
            "neutral_label", "Unapproved signal narrative",
        ),
        lambda session: setattr(
            session.get(RiskSignal, mutation_ids["signal"]),
            "neutral_label", original_signal_label,
        ),
    )
    mutation_probe(
        "public_count",
        lambda session: setattr(session.get(PublishedRiskLabel, label.id), "public_count", 5),
        lambda session: setattr(session.get(PublishedRiskLabel, label.id), "public_count", None),
    )
    mutation_probe(
        "public_label_copy",
        lambda session: setattr(
            session.get(PublishedRiskLabel, label.id),
            "neutral_label", "Unapproved public narrative",
        ),
        lambda session: setattr(
            session.get(PublishedRiskLabel, label.id),
            "neutral_label", "Moderated workplace-safety pattern",
        ),
    )
    mutation_probe(
        "suspended_approver",
        lambda session: setattr(session.get(User, safety_id), "status", "suspended"),
        lambda session: setattr(session.get(User, safety_id), "status", "active"),
    )
    mutation_probe(
        "role_changed_approver",
        lambda session: setattr(session.get(User, safety_id), "role", "student"),
        lambda session: setattr(session.get(User, safety_id), "role", "safety_officer"),
    )
    results.add(
        "W4PG-31",
        "public projection revalidates every governed source and authority",
        bool(live_mutations) and all(passed for _name, passed in live_mutations),
        dict(live_mutations),
    )

    def representative_request(actor_value, method: str, key_suffix: str):
        with SessionLocal() as session:
            return create_response_request(
                session, actor_value,
                OrganisationResponseRequestIn(
                    published_label_id=label.id,
                    representative_verification_ref=f"opaque-{key_suffix}",
                    verification_method=method,
                    request_kind="initial",
                ),
                f"wave4-pg-authority-{key_suffix}-{uuid.uuid4()}",
            )

    authority_codes: dict[str, str] = {}
    for name, actor_value, method in (
        ("safety_manual", safety_actor, "manual_legal_review"),
        ("domain_unavailable", safety_actor, "verified_domain_challenge"),
    ):
        try:
            representative_request(actor_value, method, name)
            authority_codes[name] = "unexpected_success"
        except RiskLabelError as error:
            authority_codes[name] = error.code
    with SessionLocal() as session:
        legal_user = session.get(User, legal_identity_id)
        legal_user.status = "suspended"
        session.commit()
    try:
        representative_request(
            legal_identity_actor, "manual_legal_review", "legal-suspended"
        )
        authority_codes["legal_suspended"] = "unexpected_success"
    except RiskLabelError as error:
        authority_codes["legal_suspended"] = error.code
    with SessionLocal() as session:
        legal_user = session.get(User, legal_identity_id)
        legal_user.status = "active"
        legal_user.role = "safety_officer"
        session.commit()
    try:
        representative_request(
            legal_identity_actor, "manual_legal_review", "legal-role-changed"
        )
        authority_codes["legal_role_changed"] = "unexpected_success"
    except RiskLabelError as error:
        authority_codes["legal_role_changed"] = error.code
    with SessionLocal() as session:
        legal_user = session.get(User, legal_identity_id)
        legal_user.role = "legal_reviewer"
        session.commit()
    old_qa_seam = settings.wave4_gate_allow_publication_test
    settings.wave4_gate_allow_publication_test = False
    try:
        representative_request(safety_actor, "qa_fixture", "qa-outside-seam")
        authority_codes["qa_outside_seam"] = "unexpected_success"
    except RiskLabelError as error:
        authority_codes["qa_outside_seam"] = error.code
    finally:
        settings.wave4_gate_allow_publication_test = old_qa_seam
    manual_request = representative_request(
        legal_identity_actor, "manual_legal_review", "legal-active"
    )
    with SessionLocal() as session:
        manual_row = session.get(OrganisationResponseRequest, manual_request.id)
        manual_row.state = "revoked"
        manual_row.version += 1
        manual_outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == manual_request.id,
            NotificationOutbox.event_kind == "organisation_response_requested",
        ))
        manual_outbox.state = "void"
        manual_outbox.secret_ciphertext = None
        manual_outbox.secret_key_version = None
        manual_outbox.available_at = None
        session.commit()
    results.add(
        "W4PG-34",
        "representative verification authority and adapters fail closed",
        authority_codes == {
            "safety_manual": "representative_verification_authority_required",
            "domain_unavailable": "representative_verification_method_unavailable",
            "legal_suspended": "risk_publication_actor_not_active",
            "legal_role_changed": "risk_publication_actor_not_active",
            "qa_outside_seam": "risk_labels_unavailable",
        }
        and manual_request.state == "pending",
        authority_codes,
    )

    representative_ref = "qa-representative-opaque-pg16"
    request_payload = OrganisationResponseRequestIn(
        published_label_id=label.id,
        representative_verification_ref=representative_ref,
        verification_method="qa_fixture",
        request_kind="initial",
    )

    concurrent_request_key = f"wave4-pg-initial-request-{uuid.uuid4()}"

    def concurrent_request(index: int):
        with SessionLocal() as session:
            try:
                session.execute(text("SET LOCAL lock_timeout = '8s'"))
                row = create_response_request(
                    session, safety_actor, request_payload,
                    concurrent_request_key,
                )
                return {"status": 201, "id": str(row.id)}
            except RiskLabelError as error:
                return {"status": error.status_code, "code": error.code}
            except Exception as error:
                return {"status": 500, "type": type(error).__name__}

    with ThreadPoolExecutor(max_workers=2) as pool:
        request_futures = [pool.submit(concurrent_request, index) for index in range(2)]
        request_race = [future.result(timeout=20) for future in request_futures]
    request_successes = [item for item in request_race if item["status"] == 201]
    with SessionLocal() as session:
        pending_initial_count = session.scalar(select(func.count()).select_from(
            OrganisationResponseRequest
        ).where(
            OrganisationResponseRequest.published_label_id == label.id,
            OrganisationResponseRequest.request_kind == "initial",
            OrganisationResponseRequest.state == "pending",
        ))
    results.add(
        "W4PG-21",
        "concurrent same-key initial invitation returns one pending request",
        len(request_successes) == 2
        and len({item["id"] for item in request_successes}) == 1
        and pending_initial_count == 1
        and all(item["status"] == 201 for item in request_race),
        request_race,
    )
    request_id = uuid.UUID(request_successes[0]["id"])

    provider = DeterministicResponseInvitationProvider()
    def relay_worker():
        with SessionLocal() as session:
            result = relay_response_invitations(session, provider, limit=100)
            return result.__dict__

    with ThreadPoolExecutor(max_workers=2) as pool:
        relay_futures = [pool.submit(relay_worker) for _ in range(2)]
        relay_race = [future.result(timeout=20) for future in relay_futures]
    with SessionLocal() as session:
        invitation_outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == request_id,
            NotificationOutbox.event_kind == "organisation_response_requested",
        ))
    results.add(
        "W4PG-22",
        "two relay workers deliver once and terminally erase the bearer secret",
        len(provider.deliveries) == 1
        and sum(item["sent"] for item in relay_race) == 1
        and invitation_outbox.state == "sent"
        and invitation_outbox.secret_ciphertext is None
        and invitation_outbox.claim_token is None,
        relay_race,
    )
    invitation_token = str(provider.deliveries[0]["invitation_url"]).partition("#token=")[2]
    exact_response = "😀" * 2000
    exact_boundary_ok = len(OrganisationResponseIn(
        response_text=exact_response
    ).response_text) == 2000
    try:
        OrganisationResponseIn(response_text="😀" * 2001)
        over_boundary_rejected = False
    except ValidationError:
        over_boundary_rejected = True
    initial_response_key = f"wave4-pg-initial-response-{uuid.uuid4()}"

    def concurrent_response_submit():
        with SessionLocal() as session:
            try:
                value = submit_response(
                    session, invitation_token,
                    OrganisationResponseIn(response_text=exact_response),
                    initial_response_key,
                )
                return {"status": 201, "id": str(value.id)}
            except RiskLabelError as error:
                return {"status": error.status_code, "code": error.code}

    with ThreadPoolExecutor(max_workers=2) as pool:
        submit_race = list(pool.map(lambda _: concurrent_response_submit(), range(2)))
    with SessionLocal() as session:
        initial_response = session.scalar(select(OrganisationResponse).where(
            OrganisationResponse.idempotency_key == initial_response_key
        ))
    try:
        with SessionLocal() as session:
            submit_response(
                session, invitation_token,
                OrganisationResponseIn(response_text="Replay must fail."),
                f"wave4-pg-replay-response-{uuid.uuid4()}",
            )
        replay_code = "unexpected_success"
    except RiskLabelError as error:
        replay_code = error.code
    with SessionLocal() as session:
        consumed_outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == request_id,
            NotificationOutbox.event_kind == "organisation_response_requested",
        ))
    results.add(
        "W4PG-23",
        "response boundary, replay rejection and consumed-token erasure",
        exact_boundary_ok and over_boundary_rejected
        and all(item["status"] == 201 for item in submit_race)
        and len({item["id"] for item in submit_race}) == 1
        and replay_code == "response_token_unavailable"
        and consumed_outbox.secret_ciphertext is None
        and consumed_outbox.claim_token is None,
        {
            "submit_race": submit_race,
            "replay_code": replay_code,
            "outbox_state": consumed_outbox.state,
        },
    )
    initial_decision_key = f"wave4-pg-approve-initial-{uuid.uuid4()}"

    def concurrent_initial_decision():
        with SessionLocal() as session:
            try:
                value = decide_response(
                    session, moderators[0], initial_response.id,
                    OrganisationResponseDecisionIn(
                        decision="approve", reason_code="verified_initial_response",
                        expected_version=initial_response.version,
                    ),
                    initial_decision_key,
                )
                return {"status": 200, "id": str(value.id), "state": value.state}
            except RiskLabelError as error:
                return {"status": error.status_code, "code": error.code}

    with ThreadPoolExecutor(max_workers=2) as pool:
        initial_decision_race = list(
            pool.map(lambda _: concurrent_initial_decision(), range(2))
        )
    with SessionLocal() as session:
        approved_initial = session.get(OrganisationResponse, initial_response.id)
        decision_count = session.scalar(select(func.count()).select_from(
            ResponseModeration
        ).where(ResponseModeration.idempotency_key == initial_decision_key))
    results.add(
        "W4PG-30",
        "concurrent same-key response decision returns one durable moderation",
        all(item["status"] == 200 for item in initial_decision_race)
        and len({item["id"] for item in initial_decision_race}) == 1
        and approved_initial.state == "approved" and decision_count == 1,
        {"race": initial_decision_race, "decision_count": decision_count},
    )

    correction_ref = "qa-correction-opaque-pg16"
    with SessionLocal() as session:
        correction_request = create_response_request(
            session, safety_actor,
            OrganisationResponseRequestIn(
                published_label_id=label.id,
                representative_verification_ref=correction_ref,
                verification_method="qa_fixture",
                request_kind="correction",
            ),
            f"wave4-pg-correction-request-{uuid.uuid4()}",
        )
    correction_provider = DeterministicResponseInvitationProvider()
    with SessionLocal() as session:
        relay_response_invitations(session, correction_provider, limit=100)
    correction_delivery = next(
        item for item in correction_provider.deliveries
        if item["idempotency_key"].startswith("notification:wave4-pg-correction-request")
    )
    correction_token = str(correction_delivery["invitation_url"]).partition("#token=")[2]
    with SessionLocal() as session:
        correction_response = submit_response(
            session, correction_token,
            OrganisationResponseIn(response_text="Corrected factual organisation response."),
            f"wave4-pg-correction-response-{uuid.uuid4()}",
        )

    moderator_authority_codes: list[str] = []
    for field, invalid, valid in (
        ("status", "suspended", "active"),
        ("role", "student", "moderator"),
    ):
        with SessionLocal() as session:
            user = session.get(User, moderator_ids[0])
            setattr(user, field, invalid)
            session.commit()
        try:
            with SessionLocal() as session:
                decide_response(
                    session, moderators[0], correction_response.id,
                    OrganisationResponseDecisionIn(
                        decision="approve",
                        reason_code="verified_factual_correction",
                        expected_version=correction_response.version,
                    ),
                    f"wave4-pg-inactive-moderator-{field}-{uuid.uuid4()}",
                )
            moderator_authority_codes.append("unexpected_success")
        except RiskLabelError as error:
            moderator_authority_codes.append(error.code)
        with SessionLocal() as session:
            user = session.get(User, moderator_ids[0])
            setattr(user, field, valid)
            session.commit()

    def concurrent_response_decision(index: int):
        with SessionLocal() as session:
            try:
                session.execute(text("SET LOCAL lock_timeout = '8s'"))
                row = decide_response(
                    session, moderators[index], correction_response.id,
                    OrganisationResponseDecisionIn(
                        decision="approve",
                        reason_code="verified_factual_correction",
                        expected_version=correction_response.version,
                    ),
                    f"wave4-pg-correction-decision-{index}-{uuid.uuid4()}",
                )
                return {"status": 200, "state": row.state}
            except RiskLabelError as error:
                return {"status": error.status_code, "code": error.code}
            except Exception as error:
                return {"status": 500, "type": type(error).__name__}

    with ThreadPoolExecutor(max_workers=2) as pool:
        decision_futures = [
            pool.submit(concurrent_response_decision, index) for index in range(2)
        ]
        decision_race = [future.result(timeout=20) for future in decision_futures]
    with SessionLocal() as session:
        predecessor = session.get(OrganisationResponse, approved_initial.id)
        successor = session.get(OrganisationResponse, correction_response.id)
        current_count = session.scalar(select(func.count()).select_from(
            OrganisationResponse
        ).where(
            OrganisationResponse.published_label_id == label.id,
            OrganisationResponse.is_current.is_(True),
        ))
    results.add(
        "W4PG-24",
        "concurrent correction approval leaves exactly one current response",
        sorted(item["status"] for item in decision_race) == [200, 409]
        and moderator_authority_codes
        == ["response_moderator_not_active", "response_moderator_not_active"]
        and predecessor.state == "superseded" and not predecessor.is_current
        and successor.state == "approved" and successor.is_current
        and current_count == 1,
        decision_race,
    )

    def public_response_text():
        with SessionLocal() as session:
            item = next(
                value for value in public_labels(
                    session, label.organisation_id
                ).labels if value.id == label.id
            )
            return item.organisation_response.text if item.organisation_response else None

    expected_public_response = "Corrected factual organisation response."
    baseline_response_ok = public_response_text() == expected_public_response
    with SessionLocal() as session:
        successor_row = session.get(OrganisationResponse, correction_response.id)
        original_response_ciphertext = successor_row.response_ciphertext
        successor_row.response_ciphertext = encrypt("Swapped public response ciphertext")
        session.commit()
    ciphertext_swap_hidden = public_response_text() is None
    with SessionLocal() as session:
        successor_row = session.get(OrganisationResponse, correction_response.id)
        successor_row.response_ciphertext = original_response_ciphertext
        moderation_row = session.scalar(select(ResponseModeration).where(
            ResponseModeration.response_id == successor_row.id
        ))
        moderation_row.deleted_at = datetime.now(timezone.utc)
        session.commit()
    missing_moderation_hidden = public_response_text() is None
    with SessionLocal() as session:
        moderation_row = session.scalar(select(ResponseModeration).where(
            ResponseModeration.response_id == correction_response.id
        ))
        moderation_row.deleted_at = None
        session.commit()
    withdrawal_probe_key = f"wave4-pg-withdraw-provenance-{uuid.uuid4()}"
    with SessionLocal() as session:
        signal_row = session.get(RiskSignal, label.risk_signal_id)
        withdrawal_probe = PublicationDecision(
            risk_signal_id=signal_row.id,
            published_label_id=label.id,
            actor_user_id=safety_id,
            decision="withdraw",
            reason_code="administrative_withdrawal",
            idempotency_key=withdrawal_probe_key,
            expected_version=signal_row.version,
            request_fingerprint=hashlib.sha256(
                withdrawal_probe_key.encode("utf-8")
            ).hexdigest(),
        )
        session.add(withdrawal_probe)
        session.commit()
        withdrawal_probe_id = withdrawal_probe.id
    historical_withdraw_hidden = not public_label_visible()
    with SessionLocal() as session:
        withdrawal_probe = session.get(PublicationDecision, withdrawal_probe_id)
        withdrawal_probe.deleted_at = datetime.now(timezone.utc)
        session.commit()
    results.add(
        "W4PG-33",
        "public response requires digest-bound ciphertext and matching approval row",
        baseline_response_ok and ciphertext_swap_hidden
        and missing_moderation_hidden
        and historical_withdraw_hidden
        and public_response_text() == expected_public_response,
        {
            "baseline": baseline_response_ok,
            "ciphertext_swap_hidden": ciphertext_swap_hidden,
            "missing_moderation_hidden": missing_moderation_hidden,
            "historical_withdraw_hidden": historical_withdraw_hidden,
        },
    )

    wrong_ref = "qa-wrong-organisation-pg16"
    with SessionLocal() as session:
        wrong_request = create_response_request(
            session, safety_actor,
            OrganisationResponseRequestIn(
                published_label_id=label.id,
                representative_verification_ref=wrong_ref,
                verification_method="qa_fixture",
                request_kind="appeal",
            ),
            f"wave4-pg-wrong-org-request-{uuid.uuid4()}",
        )
        wrong_outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == wrong_request.id,
            NotificationOutbox.event_kind == "organisation_response_requested",
        ))
        envelope = json.loads(decrypt(wrong_outbox.secret_ciphertext))
        envelope["organisation_id"] = str(uuid.uuid4())
        wrong_outbox.secret_ciphertext = encrypt(json.dumps(
            envelope, sort_keys=True, separators=(",", ":")
        ))
        wrong_outbox.secret_key_version = key_version(wrong_outbox.secret_ciphertext)
        session.commit()
    wrong_provider = DeterministicResponseInvitationProvider()
    with SessionLocal() as session:
        wrong_result = relay_response_invitations(session, wrong_provider, limit=100)
        wrong_row = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == wrong_request.id,
            NotificationOutbox.event_kind == "organisation_response_requested",
        ))
    results.add(
        "W4PG-25",
        "wrong-organisation invitation fails terminally without delivery",
        wrong_result.dead_lettered == 1 and not wrong_provider.deliveries
        and wrong_row.state == "void" and wrong_row.secret_ciphertext is None
        and wrong_row.last_error_code == "invitation_organisation_mismatch",
        {"state": wrong_row.state, "code": wrong_row.last_error_code},
    )

    legal_id = uuid.UUID("00000000-0000-4000-8000-0000000000c7")
    with SessionLocal() as session:
        if session.get(User, legal_id) is None:
            session.add(User(id=legal_id, role="legal_reviewer", status="active"))
            session.commit()
    legal_actor = ActorContext(
        user_id=legal_id, roles=frozenset({Role.LEGAL_REVIEWER})
    )
    with SessionLocal() as session:
        processing_request = create_response_request(
            session, safety_actor,
            OrganisationResponseRequestIn(
                published_label_id=label.id,
                representative_verification_ref="qa-processing-veto-pg16",
                verification_method="qa_fixture",
                request_kind="appeal",
            ),
            f"wave4-pg-processing-request-{uuid.uuid4()}",
        )
    with SessionLocal() as session:
        processing_outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == processing_request.id,
            NotificationOutbox.event_kind == "organisation_response_requested",
        ))
        processing_claimed = _claim(
            session, processing_outbox, now=datetime.now(timezone.utc)
        )
        processing_outbox_id = processing_outbox.id
        processing_attempts = processing_outbox.attempts
        processing_claim_token = processing_outbox.claim_token

    def veto_signal():
        with SessionLocal() as session:
            try:
                session.execute(text("SET LOCAL lock_timeout = '8s'"))
                row = approve_cluster(
                    session, legal_actor, cluster.id,
                    RiskSignalApprovalIn(
                        decision="reject", reason_code="qa_publication_veto"
                    ),
                )
                return {"status": 200, "vetoed": row.publication_ready is False}
            except Exception as error:
                return {"status": 500, "type": type(error).__name__}

    def invitation_during_veto():
        with SessionLocal() as session:
            try:
                session.execute(text("SET LOCAL lock_timeout = '8s'"))
                row = create_response_request(
                    session, safety_actor,
                    OrganisationResponseRequestIn(
                        published_label_id=label.id,
                        representative_verification_ref="qa-veto-race-pg16",
                        verification_method="qa_fixture",
                        request_kind="appeal",
                    ),
                    f"wave4-pg-veto-race-request-{uuid.uuid4()}",
                )
                return {"status": 201, "id": str(row.id)}
            except RiskLabelError as error:
                return {"status": error.status_code, "code": error.code}
            except Exception as error:
                return {"status": 500, "type": type(error).__name__}

    with ThreadPoolExecutor(max_workers=2) as pool:
        veto_futures = [pool.submit(veto_signal), pool.submit(invitation_during_veto)]
        veto_race = [future.result(timeout=20) for future in veto_futures]
    with SessionLocal() as session:
        final_label = session.get(PublishedRiskLabel, label.id)
        active_request_count = session.scalar(select(func.count()).select_from(
            OrganisationResponseRequest
        ).where(
            OrganisationResponseRequest.published_label_id == label.id,
            OrganisationResponseRequest.state == "pending",
        ))
        live_secret_count = session.scalar(select(func.count()).select_from(
            NotificationOutbox
        ).where(
            NotificationOutbox.event_kind == "organisation_response_requested",
            NotificationOutbox.state.in_(("pending", "processing", "failed")),
            NotificationOutbox.secret_ciphertext.is_not(None),
        ))
        stale_finish = _finish(
            session,
            processing_outbox_id,
            state="sent",
            now=datetime.now(timezone.utc),
            error_code=None,
            expected_attempts=processing_attempts,
            expected_claim_token=processing_claim_token,
        )
    with SessionLocal() as session:
        final_label = session.get(PublishedRiskLabel, label.id)
        final_label.status = "published"
        session.commit()
    historical_veto_hidden = not public_label_visible()
    with SessionLocal() as session:
        final_label = session.get(PublishedRiskLabel, label.id)
        final_label.status = "withdrawn"
        session.commit()
    results.add(
        "W4PG-26",
        "veto vs invitation has no deadlock and voids processing bearer material",
        processing_claimed and veto_race[0]["status"] == 200
        and veto_race[1]["status"] in {201, 404}
        and final_label.status == "withdrawn"
        and active_request_count == 0 and live_secret_count == 0
        and stale_finish is False and historical_veto_hidden,
        {
            "race": veto_race,
            "stale_finish": stale_finish,
            "historical_veto_hidden": historical_veto_hidden,
        },
    )

    def scan_markers(
        markers: list[str], connection=None
    ) -> list[dict[str, str]]:
        hits: list[dict[str, str]] = []
        def scan(active_connection):
            for table in live_tables:
                for column in inspector.get_columns(table):
                    if str(column["type"]).upper().startswith(("VARCHAR", "TEXT", "JSON")):
                        values = active_connection.execute(text(
                            f'SELECT CAST("{column["name"]}" AS TEXT) FROM "{table}" '
                            f'WHERE "{column["name"]}" IS NOT NULL'
                        ))
                        for value, in values:
                            for marker in markers:
                                if marker and marker in value:
                                    hits.append({
                                        "table": table,
                                        "column": column["name"],
                                        "marker": hashlib.sha256(marker.encode()).hexdigest()[:12],
                                    })
        if connection is not None:
            scan(connection)
        else:
            with engine.connect() as active_connection:
                scan(active_connection)
        return hits

    provider_canary = "wave4-pg-provider-error-canary"
    session_canary = hashlib.sha256(b"wave4-pg-session-canary").hexdigest()
    audit_canary = "wave4-pg-audit-canary"
    canaries = [provider_canary, session_canary, audit_canary]
    with engine.connect() as connection:
        transaction = connection.begin()
        provider_row_id = connection.scalar(text(
            "SELECT id FROM notification_outbox ORDER BY id LIMIT 1"
        ))
        connection.execute(text(
            "UPDATE notification_outbox SET last_error_code = :marker "
            "WHERE id = :row_id"
        ), {"marker": provider_canary, "row_id": provider_row_id})
        connection.execute(text(
            "INSERT INTO auth_sessions "
            "(id, user_id, token_hash, status, expires_at, last_seen_at, "
            "created_at, updated_at, deleted_at, metadata_json) VALUES "
            "(:id, :user_id, :token_hash, 'active', now() + interval '5 minutes', "
            "now(), now(), now(), NULL, NULL)"
        ), {
            "id": uuid.uuid4(), "user_id": actor_id,
            "token_hash": session_canary,
        })
        connection.execute(text(
            "INSERT INTO audit_events "
            "(id, actor_user_id, actor_role, action, resource_type, resource_id, "
            "before_state, after_state, ip_hash, user_agent_hash, created_at) "
            "VALUES (:id, NULL, NULL, 'qa_privacy_canary', 'qa_canary', NULL, "
            "NULL, CAST(:state AS JSON), NULL, NULL, now())"
        ), {
            "id": uuid.uuid4(),
            "state": json.dumps({"marker": audit_canary}),
        })
        canary_hits = scan_markers(canaries, connection)
        transaction.rollback()
    forbidden_markers = [
        invitation_token, correction_token, representative_ref, correction_ref,
        wrong_ref, exact_response,
    ]
    final_privacy_hits = scan_markers(forbidden_markers + canaries)
    detected_canary_hashes = {item["marker"] for item in canary_hits}
    expected_canary_hashes = {
        hashlib.sha256(value.encode()).hexdigest()[:12] for value in canaries
    }
    results.add(
        "W4PG-27",
        "privacy scanner detects a planted canary then finds no raw bearer or response data",
        detected_canary_hashes == expected_canary_hashes and not final_privacy_hits,
        {
            "canary_contexts": ["provider_error", "auth_session", "audit_snapshot"],
            "canary_hit_count": len(canary_hits),
            "final_hits": final_privacy_hits,
        },
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
