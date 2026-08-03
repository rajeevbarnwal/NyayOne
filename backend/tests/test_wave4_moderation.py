"""SAATHI-274 internal moderation, clustering, RBAC and privacy proof."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.crypto import decrypt, encrypt, key_version, keyed_hash
from app.core.config import settings
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import AuthSession, User
from app.models.wave4 import (
    DuplicateCluster,
    DuplicateClusterMember,
    InternshipReport,
    InternshipReportCategory,
    InternshipReportEvidence,
    ModerationAction,
    ModerationAssignment,
    ModerationCase,
    ModerationHandoff,
    ModerationNotificationOutbox,
    ReporterIdentityVault,
    RiskSignal,
    RiskSignalApproval,
)
from tests import apptemplate, dbtemplate
from app.services.moderation_service import _months_ago
from scripts.seed_wave4_moderation_e2e import assert_isolated_target, provision
from scripts.wave4_postgres_gate import is_isolated_gate_target

BACKEND = Path(__file__).resolve().parents[1]


def test_postgres_gate_requires_loopback_qa_name_test_env_and_opt_in():
    safe = "postgresql+psycopg://user:secret@127.0.0.1:5432/saathi274_qa"
    assert is_isolated_gate_target(safe, safe, "testing", True)
    assert not is_isolated_gate_target(safe, "", "testing", True)
    assert not is_isolated_gate_target(safe, safe + "_other", "testing", True)
    assert not is_isolated_gate_target(safe, safe, "production", True)
    assert not is_isolated_gate_target(safe, safe, "testing", False)
    assert not is_isolated_gate_target(
        "postgresql+psycopg://user:secret@db.internal:5432/saathi274_qa",
        "postgresql+psycopg://user:secret@db.internal:5432/saathi274_qa",
        "testing",
        True,
    )
    assert not is_isolated_gate_target(
        "postgresql+psycopg://user:secret@127.0.0.1:5432/production",
        "postgresql+psycopg://user:secret@127.0.0.1:5432/production",
        "testing",
        True,
    )
    for target in ("production_qa", "legalsaathi_prod_test", "staging_e2e"):
        unsafe = (
            "postgresql+psycopg://user:secret@127.0.0.1:5432/" + target
        )
        assert not is_isolated_gate_target(unsafe, unsafe, "testing", True)
    encoded = "postgresql+psycopg://user:secret@127.0.0.1:5432/%70roduction_qa"
    assert not is_isolated_gate_target(encoded, encoded, "testing", True)


def _claims(user_id: uuid.UUID, *roles: str) -> dict[str, str]:
    return {"X-Actor-Claims": json.dumps({"sub": str(user_id), "roles": list(roles)})}


@pytest.fixture(scope="module")
def _mounted():
    return apptemplate.mounted_app(exception_handlers=True, raise_server_exceptions=False)


@pytest.fixture()
def ctx(_mounted):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    dbtemplate.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def request_session():
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app, client = _mounted
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = request_session
    with SessionLocal() as session:
        users = {
            name: User(role=role, status="active")
            for name, role in {
                "student": "student",
                "moderator": "moderator",
                "moderator2": "moderator",
                "safety": "safety_officer",
                "legal": "legal_reviewer",
                "admin": "admin",
            }.items()
        }
        session.add_all(users.values())
        session.commit()
        ids = {name: user.id for name, user in users.items()}
    yield client, SessionLocal, ids
    engine.dispose()


def _seed_report(
    SessionLocal,
    moderator_id: uuid.UUID,
    *,
    organisation: str = "Nyaya Legal Foundation",
    category: str = "unsafe_environment",
    reporter: str | None = None,
    state: str = "pending",
    experience_date: date | None = None,
    evidence_state: str | None = "clean",
) -> uuid.UUID:
    reporter = reporter or str(uuid.uuid4())
    experience_date = experience_date or (date.today() - timedelta(days=30))
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        report = InternshipReport(
            organisation_name=organisation,
            listing_application_ref=f"APP-{uuid.uuid4().hex[:10]}",
            experience_start_date=experience_date - timedelta(days=20),
            experience_end_date=experience_date,
            narrative="Private first-person account with enough detail for a trained moderator to assess safely.",
            privacy_mode="anonymous",
            status=("approved" if state == "approved_aggregate_only" else "moderation_pending"),
            idempotency_key=f"seed-{uuid.uuid4()}",
            version=2,
            support_guidance_required=True,
            submitted_at=now,
        )
        session.add(report)
        session.flush()
        session.add(InternshipReportCategory(report_id=report.id, category=category))
        if evidence_state is not None:
            digest = uuid.uuid4().hex + uuid.uuid4().hex
            session.add(InternshipReportEvidence(
                report_id=report.id,
                object_ref=f"quarantine/{uuid.uuid4()}",
                mime_type="application/pdf",
                size_bytes=128,
                checksum_sha256=digest,
                scan_state=evidence_state,
                scanner_result_code="fixture",
                retention_policy="configured",
            ))
        reporter_ct = encrypt(reporter)
        session.add(
            ReporterIdentityVault(
                report_id=report.id,
                reporter_lookup_hash=keyed_hash(reporter, lower=True),
                reporter_ciphertext=reporter_ct,
                key_version=key_version(reporter_ct),
            )
        )
        assigned = moderator_id if state != "pending" else None
        handoff_state = {
            "pending": "pending",
            "under_review": "assigned",
            "approved_aggregate_only": "approved",
            "needs_information": "needs_information",
            "rejected": "rejected",
        }[state]
        session.add(
            ModerationHandoff(
                report_id=report.id,
                state=handoff_state,
                assigned_moderator_user_id=assigned,
                version=1,
            )
        )
        session.add(
            ModerationCase(
                report_id=report.id,
                state=state,
                assigned_moderator_user_id=assigned,
                claimed_at=(now if assigned else None),
                version=1,
            )
        )
        session.commit()
        return report.id


def _action(client: TestClient, ids, report_id, action, version, *, actor="moderator", key=None):
    reasons = {
        "claim": ("review_started", "Beginning independent internal review."),
        "needs_information": ("more_information_required", "Please provide a date-specific supporting record."),
        "approve_aggregate_only": ("aggregate_criteria_met", "Evidence meets the internal aggregate-only criteria."),
        "reject": ("insufficient_or_unverifiable", "Available evidence cannot be independently verified."),
    }
    reason_code, detail = reasons[action]
    role = "moderator" if actor.startswith("moderator") else actor
    return client.post(
        f"/api/v1/moderation/internship-reports/{report_id}/actions",
        headers={**_claims(ids[actor], role), "Idempotency-Key": key or f"{action}-{uuid.uuid4()}"},
        json={
            "action": action,
            "reason_code": reason_code,
            "reason_detail": detail,
            "expected_version": version,
        },
    )


def test_queue_and_detail_are_moderator_only_and_identity_safe(ctx):
    client, SessionLocal, ids = ctx
    report_id = _seed_report(SessionLocal, ids["moderator"])
    assert client.get("/api/v1/moderation/internship-reports").status_code == 401
    assert client.get(
        "/api/v1/moderation/internship-reports", headers=_claims(ids["student"], "student")
    ).status_code == 403
    queue = client.get(
        "/api/v1/moderation/internship-reports", headers=_claims(ids["moderator"], "moderator")
    )
    assert queue.status_code == 200, queue.text
    item = queue.json()["items"][0]
    assert item["report_id"] == str(report_id)
    assert "narrative" not in item and "reporter" not in json.dumps(item).lower()
    detail = client.get(
        f"/api/v1/moderation/internship-reports/{report_id}",
        headers=_claims(ids["moderator"], "moderator"),
    )
    assert detail.status_code == 200 and "Private first-person" in detail.json()["narrative"]
    body = json.dumps(detail.json())
    assert str(ids["student"]) not in body and "reporter_lookup_hash" not in body


def test_hashed_http_only_style_staff_session_authorises_and_header_cannot_override(ctx):
    client, SessionLocal, ids = ctx
    _seed_report(SessionLocal, ids["moderator"])
    raw_token = "opaque-moderator-session-token-not-stored-raw"
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        session.add(AuthSession(
            user_id=ids["moderator"], token_hash=keyed_hash(raw_token), status="active",
            expires_at=now + timedelta(hours=1), last_seen_at=now,
        ))
        session.commit()
        assert raw_token not in session.scalar(select(AuthSession.token_hash))
    client.cookies.set(settings.auth_session_cookie_name, raw_token)
    response = client.get(
        "/api/v1/moderation/internship-reports",
        # A forged lower-privilege header cannot override the server session.
        headers=_claims(ids["student"], "student"),
    )
    assert response.status_code == 200 and response.json()["total"] == 1


def test_claim_is_atomic_idempotent_and_hides_case_from_other_moderator(ctx):
    client, SessionLocal, ids = ctx
    report_id = _seed_report(SessionLocal, ids["moderator"])
    first = _action(client, ids, report_id, "claim", 1, key="claim-idempotent-0001")
    replay = _action(client, ids, report_id, "claim", 1, key="claim-idempotent-0001")
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    loser = _action(client, ids, report_id, "claim", 1, actor="moderator2")
    assert loser.status_code == 409 and loser.json()["detail"]["code"] == "stale_moderation_case"
    hidden = client.get(
        f"/api/v1/moderation/internship-reports/{report_id}",
        headers=_claims(ids["moderator2"], "moderator"),
    )
    missing = client.get(
        f"/api/v1/moderation/internship-reports/{uuid.uuid4()}",
        headers=_claims(ids["moderator2"], "moderator"),
    )
    assert hidden.status_code == missing.status_code == 404
    with SessionLocal() as session:
        assert len(session.scalars(select(ModerationAssignment)).all()) == 1
        assert len(session.scalars(select(ModerationAction)).all()) == 1


@pytest.mark.parametrize(
    ("payload", "expected_fragment"),
    [
        ({"action": "claim", "reason_code": "review_started", "reason_detail": "short", "expected_version": 1}, "reason_detail"),
        ({"action": "claim", "reason_code": "aggregate_criteria_met", "reason_detail": "Long enough reason text", "expected_version": 1}, "reason_does_not_match_action"),
        ({"action": "unknown", "reason_code": "review_started", "reason_detail": "Long enough reason text", "expected_version": 1}, "unsupported_moderation_action"),
        ({"action": "claim", "reason_code": "review_started", "reason_detail": "Unsafe <script> text", "expected_version": 1}, "unsafe_reason_detail"),
    ],
)
def test_action_negative_boundaries_fail_without_mutation(ctx, payload, expected_fragment):
    client, SessionLocal, ids = ctx
    report_id = _seed_report(SessionLocal, ids["moderator"])
    response = client.post(
        f"/api/v1/moderation/internship-reports/{report_id}/actions",
        headers={**_claims(ids["moderator"], "moderator"), "Idempotency-Key": "negative-action-0001"},
        json=payload,
    )
    assert response.status_code == 422 and expected_fragment in response.text
    with SessionLocal() as session:
        case = session.scalar(select(ModerationCase).where(ModerationCase.report_id == report_id))
        assert case.state == "pending" and case.version == 1


def test_needs_information_encrypts_reason_updates_state_and_uses_outbox(ctx):
    client, SessionLocal, ids = ctx
    report_id = _seed_report(SessionLocal, ids["moderator"])
    claim = _action(client, ids, report_id, "claim", 1)
    response = _action(client, ids, report_id, "needs_information", claim.json()["case_version"])
    assert response.status_code == 200 and response.json()["case_state"] == "needs_information"
    with SessionLocal() as session:
        action = session.scalar(select(ModerationAction).where(ModerationAction.action == "needs_information"))
        assert "date-specific" not in action.reason_ciphertext
        assert "date-specific" in decrypt(action.reason_ciphertext)
        outbox = session.scalar(select(ModerationNotificationOutbox))
        assert outbox.event_kind == "report_information_requested"
        assert "narrative" not in json.dumps(outbox.payload_json).lower()
        report = session.get(InternshipReport, report_id)
        assert report.status == "needs_information"
        audit = json.dumps([row.after_state for row in session.scalars(select(AuditEvent)).all()])
        assert "date-specific" not in audit and "Private first-person" not in audit


@pytest.mark.parametrize(
    ("action", "expected_case_state", "expected_report_status"),
    [
        ("approve_aggregate_only", "approved_aggregate_only", "approved"),
        ("reject", "rejected", "rejected"),
    ],
)
def test_terminal_action_names_map_to_valid_durable_states(
    ctx, action, expected_case_state, expected_report_status
):
    client, SessionLocal, ids = ctx
    report_id = _seed_report(SessionLocal, ids["moderator"])
    claim = _action(client, ids, report_id, "claim", 1)
    response = _action(
        client,
        ids,
        report_id,
        action,
        claim.json()["case_version"],
    )
    assert response.status_code == 200, response.text
    assert response.json()["case_state"] == expected_case_state
    with SessionLocal() as session:
        case = session.scalar(
            select(ModerationCase).where(ModerationCase.report_id == report_id)
        )
        report = session.get(InternshipReport, report_id)
        assert case.state == expected_case_state
        assert report.status == expected_report_status


def test_stale_version_and_idempotency_cross_case_conflict(ctx):
    client, SessionLocal, ids = ctx
    report_a = _seed_report(SessionLocal, ids["moderator"])
    report_b = _seed_report(SessionLocal, ids["moderator"])
    assert _action(client, ids, report_a, "claim", 1, key="shared-action-key-0001").status_code == 200
    stale = _action(client, ids, report_a, "reject", 1)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_moderation_case"
    conflict = _action(client, ids, report_b, "claim", 1, key="shared-action-key-0001")
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "idempotency_conflict"


def test_cluster_requires_org_category_time_and_aggregate_approval(ctx):
    client, SessionLocal, ids = ctx
    approved = [
        _seed_report(SessionLocal, ids["moderator"], reporter=f"reporter-{n}", state="approved_aggregate_only")
        for n in range(2)
    ]
    pending = _seed_report(SessionLocal, ids["moderator"], reporter="reporter-pending")
    headers = {**_claims(ids["moderator"], "moderator"), "Idempotency-Key": "cluster-negative-0001"}
    not_approved = client.post(
        "/api/v1/moderation/risk-clusters",
        headers=headers,
        json={"report_ids": [str(approved[0]), str(pending)], "category": "unsafe_environment"},
    )
    assert not_approved.status_code == 409
    mismatch = _seed_report(
        SessionLocal, ids["moderator"], organisation="Different Organisation", reporter="reporter-mismatch",
        state="approved_aggregate_only",
    )
    headers["Idempotency-Key"] = "cluster-negative-0002"
    response = client.post(
        "/api/v1/moderation/risk-clusters", headers=headers,
        json={"report_ids": [str(approved[0]), str(mismatch)], "category": "unsafe_environment"},
    )
    assert response.status_code == 422 and response.json()["detail"]["code"] == "cluster_signal_mismatch"
    old = _seed_report(
        SessionLocal, ids["moderator"], reporter="reporter-old", state="approved_aggregate_only",
        experience_date=date.today().replace(year=date.today().year - 3),
    )
    headers["Idempotency-Key"] = "cluster-negative-0003"
    response = client.post(
        "/api/v1/moderation/risk-clusters", headers=headers,
        json={"report_ids": [str(approved[0]), str(old)], "category": "unsafe_environment"},
    )
    assert response.status_code == 422 and response.json()["detail"]["code"] == "cluster_outside_time_window"


def test_calendar_month_cutoff_is_inclusive_and_one_day_before_is_rejected(ctx):
    client, SessionLocal, ids = ctx
    cutoff = _months_ago(date.today(), settings.internship_risk_window_months)
    exact = [
        _seed_report(
            SessionLocal,
            ids["moderator"],
            reporter=f"cutoff-exact-{index}",
            state="approved_aggregate_only",
            experience_date=cutoff,
        )
        for index in range(3)
    ]
    accepted = client.post(
        "/api/v1/moderation/risk-clusters",
        headers={
            **_claims(ids["moderator"], "moderator"),
            "Idempotency-Key": "cluster-exact-cutoff-0001",
        },
        json={"report_ids": [str(value) for value in exact], "category": "unsafe_environment"},
    )
    assert accepted.status_code == 201, accepted.text
    before = [
        _seed_report(
            SessionLocal,
            ids["moderator"],
            reporter=f"cutoff-before-{index}",
            state="approved_aggregate_only",
            experience_date=cutoff - timedelta(days=1),
        )
        for index in range(3)
    ]
    rejected = client.post(
        "/api/v1/moderation/risk-clusters",
        headers={
            **_claims(ids["moderator"], "moderator"),
            "Idempotency-Key": "cluster-before-cutoff-0001",
        },
        json={"report_ids": [str(value) for value in before], "category": "unsafe_environment"},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["detail"]["code"] == "cluster_outside_time_window"


@pytest.mark.parametrize(
    ("today", "months", "expected"),
    [
        (date(2024, 2, 29), 12, date(2023, 2, 28)),
        (date(2024, 3, 31), 1, date(2024, 2, 29)),
        (date(2023, 3, 31), 1, date(2023, 2, 28)),
        (date(2026, 8, 31), 24, date(2024, 8, 31)),
    ],
)
def test_month_cutoff_handles_leap_year_and_month_end(today, months, expected):
    assert _months_ago(today, months) == expected


def test_threshold_small_count_suppression_approvals_and_publication_kill_switch(ctx):
    client, SessionLocal, ids = ctx
    reports = [
        _seed_report(SessionLocal, ids["moderator"], reporter=f"distinct-{n}", state="approved_aggregate_only")
        for n in range(3)
    ]
    created = client.post(
        "/api/v1/moderation/risk-clusters",
        headers={**_claims(ids["moderator"], "moderator"), "Idempotency-Key": "cluster-threshold-0001"},
        json={"report_ids": [str(value) for value in reports], "category": "unsafe_environment"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["threshold_met"] is True
    assert body["small_count_suppressed"] is True and body["public_count"] is None
    assert body["publication_ready"] is False
    cluster_id = body["id"]
    moderator = client.post(
        f"/api/v1/moderation/risk-clusters/{cluster_id}/approvals",
        headers=_claims(ids["moderator"], "moderator"),
        json={"decision": "approve", "reason_code": "moderator_policy_check"},
    )
    safety = client.post(
        f"/api/v1/moderation/risk-clusters/{cluster_id}/approvals",
        headers=_claims(ids["safety"], "safety_officer"),
        json={"decision": "approve", "reason_code": "safety_policy_check"},
    )
    assert moderator.status_code == safety.status_code == 200
    assert safety.json()["moderator_approved"] is True
    assert safety.json()["safety_legal_approved"] is True
    assert safety.json()["publication_ready"] is False
    denied = client.post(
        f"/api/v1/moderation/risk-clusters/{cluster_id}/approvals",
        headers=_claims(ids["student"], "student"),
        json={"decision": "approve", "reason_code": "moderator_policy_check"},
    )
    assert denied.status_code == 403
    with SessionLocal() as session:
        signal = session.scalar(select(RiskSignal))
        assert signal.publication_ready is False
        assert len(session.scalars(select(RiskSignalApproval)).all()) == 2
        assert len(session.scalars(select(DuplicateClusterMember)).all()) == 3


def test_distinct_reporter_threshold_rejects_duplicate_people(ctx):
    client, SessionLocal, ids = ctx
    reports = [
        _seed_report(SessionLocal, ids["moderator"], reporter="same-reporter", state="approved_aggregate_only")
        for _ in range(3)
    ]
    response = client.post(
        "/api/v1/moderation/risk-clusters",
        headers={**_claims(ids["moderator"], "moderator"), "Idempotency-Key": "cluster-sybil-0001"},
        json={"report_ids": [str(value) for value in reports], "category": "unsafe_environment"},
    )
    assert response.status_code == 201
    assert response.json()["distinct_reporter_count"] == 1
    assert response.json()["threshold_met"] is False
    assert response.json()["state"] == "suppressed"


def test_cluster_replay_is_idempotent_and_never_stores_plain_organisation(ctx):
    client, SessionLocal, ids = ctx
    reports = [
        _seed_report(SessionLocal, ids["moderator"], reporter=f"idempotent-{n}", state="approved_aggregate_only")
        for n in range(3)
    ]
    headers = {**_claims(ids["moderator"], "moderator"), "Idempotency-Key": "cluster-idempotent-0001"}
    payload = {"report_ids": [str(value) for value in reports], "category": "unsafe_environment"}
    first = client.post("/api/v1/moderation/risk-clusters", headers=headers, json=payload)
    replay = client.post("/api/v1/moderation/risk-clusters", headers=headers, json=payload)
    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    with SessionLocal() as session:
        clusters = session.scalars(select(DuplicateCluster)).all()
        assert len(clusters) == 1
        assert not hasattr(clusters[0], "organisation_name")
        assert "Nyaya Legal Foundation" not in clusters[0].organisation_ciphertext
        assert decrypt(clusters[0].organisation_ciphertext) == "Nyaya Legal Foundation"


def test_upgrade_from_0011_backfills_existing_moderation_handoff(alembic_db):
    database = alembic_db("head", name="moderation-backfill")
    environment = {**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{database}"}
    downgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0011_wave4_private_reporting"],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert downgrade.returncode == 0, downgrade.stderr
    report_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    engine = create_engine(environment["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO internship_reports
                    (id, organisation_name, listing_application_ref, narrative,
                     privacy_mode, status, idempotency_key, version,
                     support_guidance_required, submitted_at, created_at,
                     updated_at, deleted_at, metadata_json)
                VALUES
                    (:id, 'Legacy Organisation', 'LEGACY-001', 'Legacy private narrative',
                     'anonymous', 'moderation_pending', 'legacy-report-0001', 2,
                     false, :now, :now, :now, NULL, NULL)
                """
            ),
            {"id": report_id.hex, "now": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO moderation_handoffs
                    (id, report_id, state, assigned_moderator_user_id, version,
                     created_at, updated_at, deleted_at, metadata_json)
                VALUES (:id, :report_id, 'pending', NULL, 3, :now, :now, NULL, NULL)
                """
            ),
            {"id": uuid.uuid4().hex, "report_id": report_id.hex, "now": now},
        )
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert upgrade.returncode == 0, upgrade.stderr
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT state, version FROM moderation_cases WHERE report_id = :id"),
            {"id": report_id.hex},
        ).one()
    assert row.state == "pending" and row.version == 3
    engine.dispose()


def test_e2e_seed_refuses_non_test_or_ambiguous_database(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WAVE4_E2E_ALLOW_SEED", "true")
    with pytest.raises(RuntimeError, match="APP_ENV"):
        assert_isolated_target("postgresql://user:secret@db/production")
    monkeypatch.setenv("APP_ENV", "testing")
    remote = "postgresql://user:secret@db.example/legalsaathi_saathi274_qa"
    monkeypatch.setenv("TEST_DATABASE_URL", remote)
    with pytest.raises(RuntimeError, match="isolated local"):
        assert_isolated_target(remote)
    local = "postgresql://user:secret@localhost/legalsaathi_saathi274_qa"
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://user:secret@localhost/other_qa")
    with pytest.raises(RuntimeError, match="exactly equal"):
        assert_isolated_target(local)
    monkeypatch.setenv("TEST_DATABASE_URL", local)
    assert_isolated_target(local)


def test_e2e_fixture_is_idempotent_and_stores_only_session_hash(ctx):
    _, SessionLocal, _ = ctx
    token = "opaque-e2e-token-value-with-at-least-32-characters"
    with SessionLocal() as session:
        first = provision(session, token)
        session.commit()
    with SessionLocal() as session:
        second = provision(session, token)
        session.commit()
        stored = session.scalar(select(AuthSession).where(AuthSession.user_id == uuid.UUID("00000000-0000-4000-8000-0000000000c4")))
        assert stored and stored.token_hash == keyed_hash(token)
        assert token != stored.token_hash
    assert first == {"users": 1, "sessions": 1, "reports": 4, "cases": 4}
    assert second == {"users": 0, "sessions": 0, "reports": 0, "cases": 0}
