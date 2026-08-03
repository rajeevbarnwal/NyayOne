"""Fail-closed SAATHI-279 publication, response and fixture boundaries."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core import rate_limit
from app.core.config import ConfigurationError, Settings, settings
from app.core.crypto import decrypt, encrypt, key_version, keyed_hash
from app.db.models.audit import AuditEvent
from app.db.session import get_session
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
    PublishedRiskLabel,
    ReporterIdentityVault,
    RiskSignal,
    RiskSignalApproval,
)
from app.schemas.moderation import RiskSignalApprovalIn
from app.schemas.risk_labels import (
    OrganisationResponseDecisionIn,
    OrganisationResponseIn,
    RiskLabelPublishIn,
)
from app.services.organisation_identity import public_organisation_id
from scripts.seed_wave4_risk_labels_e2e import (
    RISK_REPORT_IDS,
    RESPONSE_REQUEST_ID,
    _write_fixture_output,
    provision,
)
from scripts.seed_wave4_moderation_e2e import (
    MODERATOR_ID,
    REPORT_IDS as MODERATION_REPORT_IDS,
    provision as provision_moderation,
)
from scripts.relay_wave4_response_invitations_e2e import _write_private
from scripts.invalidate_wave4_risk_label_source_e2e import invalidate_source
from app.services.risk_notification_relay import (
    DeterministicResponseInvitationProvider,
    NotificationRelayError,
    _claim,
    _finish,
    relay_response_invitations,
)
from app.workers.risk_notification_outbox_relay import relay_once
from tests import apptemplate, dbtemplate


def test_ci_runs_moderation_before_seeding_risk_label_cluster() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github"
        / "workflows"
        / "wave4-private-reporting-gate.yml"
    ).read_text(encoding="utf-8")
    moderation_seed = workflow.index("python -m scripts.seed_wave4_moderation_e2e")
    moderation_gate = workflow.index("run: npm run qa:wave4-moderation")
    risk_seed = workflow.index("python -m scripts.seed_wave4_risk_labels_e2e")
    risk_gate = workflow.index("run: npm run qa:wave4-risk-labels")
    assert moderation_seed < moderation_gate < risk_seed < risk_gate


def _claims(user_id: uuid.UUID, *roles: str) -> dict[str, str]:
    return {"X-Actor-Claims": json.dumps({"sub": str(user_id), "roles": list(roles)})}


def _open_qa_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = "sqlite+pysqlite:////tmp/legalsaathi_wave4_qa.db"
    monkeypatch.setattr(settings, "app_env", "testing")
    monkeypatch.setattr(settings, "database_url", database_url)
    monkeypatch.setattr(settings, "test_database_url", database_url)
    monkeypatch.setattr(settings, "internship_risk_labels_enabled", False)
    monkeypatch.setattr(settings, "wave4_gate_allow_publication_test", True)
    monkeypatch.setattr(settings, "wave4_security_approval_ref", "QA-SECURITY")
    monkeypatch.setattr(settings, "wave4_policy_approval_ref", "QA-POLICY")
    monkeypatch.setattr(settings, "wave4_target_runtime_gate_ref", "QA-RUNTIME")


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
        moderator = User(role="moderator", status="active")
        admin = User(role="admin", status="active")
        safety = User(role="safety_officer", status="active")
        session.add_all([moderator, admin, safety])
        session.commit()
        ids = {"moderator": moderator.id, "admin": admin.id, "safety": safety.id}
    rate_limit.reset()
    yield client, SessionLocal, ids
    rate_limit.reset()
    engine.dispose()


def test_publication_gate_requires_every_qa_condition_and_exact_database_match():
    base = {
        "_env_file": None,
        "app_env": "testing",
        "database_url": "sqlite+pysqlite:////tmp/legalsaathi_wave4_qa.db",
        "test_database_url": "sqlite+pysqlite:////tmp/legalsaathi_wave4_qa.db",
        "wave4_gate_allow_publication_test": True,
        "wave4_security_approval_ref": "QA-SECURITY",
        "wave4_policy_approval_ref": "QA-POLICY",
        "wave4_target_runtime_gate_ref": "QA-RUNTIME",
    }
    assert Settings(**base).wave4_gate_allow_publication_test is True
    for key in (
        "wave4_security_approval_ref",
        "wave4_policy_approval_ref",
        "wave4_target_runtime_gate_ref",
    ):
        with pytest.raises(ConfigurationError, match=key):
            Settings(**{**base, key: None})
    with pytest.raises(ConfigurationError, match="only in testing"):
        Settings(**{**base, "app_env": "development"})
    with pytest.raises(ConfigurationError, match="isolated test/qa"):
        Settings(**{
            **base,
            "database_url": "postgresql://qa-user:secret@db/production",
            "test_database_url": "postgresql://qa-user:secret@db/production",
        })
    with pytest.raises(ConfigurationError, match="equal DATABASE_URL"):
        Settings(**{**base, "test_database_url": "sqlite+pysqlite:////tmp/other_qa.db"})
    with pytest.raises(ConfigurationError, match="internship_risk_labels_enabled"):
        Settings(**{**base, "internship_risk_labels_enabled": True})


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://qa:secret@db.example/legalsaathi_wave4_qa",
        "postgresql://wave4:qa@production.example/production",
        "postgresql://user:secret@production.example/production?target=wave4_qa",
        "postgresql://qa:test@127.0.0.1/production_wave4",
        "postgresql://qa:test@127.0.0.1/saathi279",
        "postgresql://test:secret@127.0.0.1/production",
        "postgresql://user:secret@127.0.0.1/production?environment=e2e",
        "sqlite+pysqlite:////Users/example/production/wave4_qa.db",
        "postgresql://qa:test@127.0.0.1/production_qa",
        "postgresql://qa:test@127.0.0.1/legalsaathi_prod_test",
        "sqlite+pysqlite:////tmp/legalsaathi_production_qa.db",
        "sqlite+pysqlite:////tmp/legalsaathi_staging_e2e.db",
        "postgresql://qa:test@127.0.0.1/%70roduction_qa",
        "sqlite+pysqlite:////tmp/legalsaathi_%70roduction_qa.db",
    ],
)
def test_publication_gate_rejects_remote_or_non_temp_qa_looking_database(database_url):
    with pytest.raises(ConfigurationError, match="isolated test/qa DATABASE_URL"):
        Settings(
            _env_file=None,
            app_env="testing",
            database_url=database_url,
            test_database_url=database_url,
            wave4_gate_allow_publication_test=True,
            wave4_security_approval_ref="QA-SECURITY",
            wave4_policy_approval_ref="QA-POLICY",
            wave4_target_runtime_gate_ref="QA-RUNTIME",
        )


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://qa:secret@localhost/legalsaathi_wave4_qa",
        "postgresql://qa:secret@127.0.0.1/legalsaathi_saathi279_e2e",
        "postgresql://qa:secret@[::1]/legalsaathi_wave4_test",
        "sqlite+pysqlite:////tmp/legalsaathi_wave4_qa.db",
    ],
)
def test_publication_gate_accepts_only_explicit_loopback_or_temp_qa_targets(database_url):
    configured = Settings(
        _env_file=None,
        app_env="testing",
        database_url=database_url,
        test_database_url=database_url,
        wave4_gate_allow_publication_test=True,
        wave4_security_approval_ref="QA-SECURITY",
        wave4_policy_approval_ref="QA-POLICY",
        wave4_target_runtime_gate_ref="QA-RUNTIME",
    )
    assert configured.wave4_gate_allow_publication_test is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"internship_risk_min_distinct_reporters": 1},
        {"internship_risk_min_distinct_reporters": 2},
        {"internship_risk_window_months": 0},
        {"internship_risk_window_months": 25},
        {"internship_risk_public_count_suppression": 1},
        {"internship_risk_public_count_suppression": 4},
        {
            "internship_risk_min_distinct_reporters": 6,
            "internship_risk_public_count_suppression": 5,
        },
    ],
)
def test_risk_policy_configuration_cannot_weaken_approved_bounds(overrides):
    with pytest.raises(ConfigurationError, match="internship_risk"):
        Settings(_env_file=None, **overrides)


def test_risk_policy_configuration_allows_safe_stricter_values():
    configured = Settings(
        _env_file=None,
        internship_risk_min_distinct_reporters=6,
        internship_risk_window_months=12,
        internship_risk_public_count_suppression=7,
    )
    assert configured.internship_risk_min_distinct_reporters == 6


@pytest.mark.parametrize(
    ("factory", "payload"),
    [
        (RiskSignalApprovalIn, {"decision": "approve", "reason_code": "person@example.test"}),
        (RiskLabelPublishIn, {"expected_version": 1, "reason_code": "Named person narrative"}),
        (OrganisationResponseDecisionIn, {
            "decision": "approve", "expected_version": 1,
            "reason_code": "private@example.test",
        }),
    ],
)
def test_governance_reason_codes_are_machine_allowlists(factory, payload):
    with pytest.raises(ValueError, match="unsupported_.*reason"):
        factory(**payload)


def test_public_organisation_id_is_canonical_and_independent_of_rotating_secrets(
    monkeypatch,
):
    first = public_organisation_id("  Example   Legal  LLP ")
    monkeypatch.setattr(
        settings,
        "registration_lookup_secret",
        SecretStr("rotated-unrelated-secret"),
    )
    assert public_organisation_id("example legal llp") == first
    assert public_organisation_id("EXAMPLE LEGAL LLP") == first


def test_public_organisation_id_normalises_canonically_equivalent_unicode_only():
    composed = public_organisation_id("Société Legal")
    decomposed = public_organisation_id("Socie\u0301te\u0301 Legal")
    assert composed == decomposed
    # A visually similar but different Greek omicron remains distinct.  The
    # canonicalizer must not act as an unsafe confusable-character mapper.
    assert public_organisation_id("Acme Legal") != public_organisation_id("Acme Legaο")


@pytest.mark.parametrize("environment", ["staging", "stage", "production", "prod"])
def test_deterministic_response_notification_provider_is_local_test_only(environment):
    common = {
        "_env_file": None,
        "app_env": environment,
        "internship_report_scanner_provider": "clamav",
        "calendar_public_base_url": "https://calendar.legalsaathi.example",
    }
    with pytest.raises(ConfigurationError, match="notification_provider must be none"):
        Settings(
            **common,
            internship_response_notification_provider="deterministic",
        )
    assert Settings(
        **common,
        internship_response_notification_provider="none",
    )


def test_disabled_public_and_mutation_routes_fail_before_any_database_mutation(ctx):
    client, SessionLocal, ids = ctx
    headers = {**_claims(ids["safety"], "safety_officer"), "Idempotency-Key": "disabled-gate-0001"}
    calls = (
        client.post(
            f"/api/v1/moderation/risk-labels/{uuid.uuid4()}/publish",
            headers=headers,
            json={"expected_version": 1, "reason_code": "qa_policy", "action": "publish"},
        ),
        client.post(
            "/api/v1/organisation-response-requests",
            headers=headers,
            json={
                "published_label_id": str(uuid.uuid4()),
                "representative_verification_ref": "verified-reference",
                "verification_method": "qa_fixture",
                "request_kind": "initial",
            },
        ),
        client.post(
            "/api/v1/organisation-responses",
            headers={"X-Organisation-Response-Token": "x" * 40, "Idempotency-Key": "disabled-gate-0002"},
            json={"response_text": "A valid but unavailable response."},
        ),
        client.post(
            f"/api/v1/moderation/organisation-responses/{uuid.uuid4()}/decide",
            headers=headers,
            json={"decision": "approve", "reason_code": "qa_review", "expected_version": 1},
        ),
        client.get(f"/api/v1/public/internship-risk-labels/{uuid.uuid4()}"),
    )
    for response in calls:
        assert response.status_code == 503, response.text
        assert response.json()["detail"] == {
            "code": "risk_labels_unavailable",
            "message": "Public internship risk labels are not available",
            "retryable": False,
        }
    with SessionLocal() as session:
        for model in (
            PublishedRiskLabel,
            OrganisationResponseRequest,
            OrganisationResponse,
            NotificationOutbox,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("value", ["", "   ", "visible\x7fhidden", "x" * 2001, "😀" * 2001])
def test_response_negative_boundaries_are_rejected_at_http(ctx, monkeypatch, value):
    client, _SessionLocal, _ids = ctx
    _open_qa_gate(monkeypatch)
    response = client.post(
        "/api/v1/organisation-responses",
        headers={"X-Organisation-Response-Token": "boundary-token-" + "x" * 32,
                 "Idempotency-Key": f"negative-{uuid.uuid4()}"},
        json={"response_text": value},
    )
    assert response.status_code == 422, response.text


def test_response_uses_unicode_code_points_and_accepts_exactly_2000_emoji():
    parsed = OrganisationResponseIn(response_text="😀" * 2000)
    assert len(parsed.response_text) == 2000
    with pytest.raises(ValueError, match="organisation_response_length"):
        OrganisationResponseIn(response_text="😀" * 2001)


def test_rate_limit_is_partitioned_by_ip_and_token_and_retains_no_raw_token(
    ctx, monkeypatch
):
    client, _SessionLocal, _ids = ctx
    _open_qa_gate(monkeypatch)
    monkeypatch.setattr(settings, "internship_response_token_rate_per_minute", 1)
    rate_limit.reset()
    token_a = "representative-A-" + "a" * 40
    token_b = "representative-B-" + "b" * 40

    def attempt(token: str, suffix: str):
        return client.post(
            "/api/v1/organisation-responses",
            headers={
                "X-Organisation-Response-Token": token,
                "Idempotency-Key": f"rate-test-{suffix}",
            },
            json={"response_text": "A structurally valid representative response."},
        )

    first = attempt(token_a, "a1")
    exhausted = attempt(token_a, "a2")
    independent = attempt(token_b, "b1")
    assert first.status_code == independent.status_code == 404
    assert exhausted.status_code == 429
    combined = json.dumps([first.json(), exhausted.json(), independent.json()]) + repr(rate_limit._buckets)
    assert token_a not in combined and token_b not in combined
    # One coarse IP bucket plus one independent bucket for each invitation.
    assert len(rate_limit._buckets) == 3


def test_candidate_queue_reports_real_gate_state_and_admin_audit_role(ctx, monkeypatch):
    client, SessionLocal, ids = ctx
    _open_qa_gate(monkeypatch)
    response = client.get(
        "/api/v1/moderation/risk-labels",
        headers=_claims(ids["admin"], "admin"),
    )
    assert response.status_code == 200
    assert response.json()["publication_gate_open"] is True
    with SessionLocal() as session:
        audit = session.scalar(select(AuditEvent).where(
            AuditEvent.action == "risk_label_candidate_queue_viewed"
        ))
        assert audit.actor_role == "admin"
        assert audit.after_state["publication_gate_open"] is True


def test_risk_label_seed_is_idempotent_private_and_writes_mode_0600_fixture(
    ctx, tmp_path
):
    _client, SessionLocal, _ids = ctx
    values = {
        "moderator_token": "moderator-" + "m" * 40,
        "safety_token": "safety-" + "s" * 40,
        "legal_token": "legal-" + "l" * 40,
        "response_token": "response-" + "r" * 40,
        "expired_response_token": "expired-" + "e" * 40,
        "boundary_response_token": "boundary-" + "b" * 40,
    }
    with SessionLocal() as session:
        first = provision(session, **values)
        session.commit()
    with SessionLocal() as session:
        counts_before = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (PublishedRiskLabel, OrganisationResponseRequest, OrganisationResponse, NotificationOutbox)
        }
        second = provision(session, **values)
        session.commit()
        counts_after = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (PublishedRiskLabel, OrganisationResponseRequest, OrganisationResponse, NotificationOutbox)
        }
    assert first == second
    assert counts_before == counts_after
    output = tmp_path / "fixture.json"
    _write_fixture_output(
        str(output), first, database_url="sqlite+pysqlite:////tmp/wave4_fixture_qa.db"
    )
    assert os.stat(output).st_mode & 0o777 == 0o600
    serialized = output.read_text()
    for token in values.values():
        assert token not in serialized
    payload = json.loads(serialized)
    assert payload["database_dialect"] == "sqlite"
    assert payload["candidate_cluster_id"].endswith("2791")
    assert payload["valid_request_id"].endswith("2796")
    assert payload["expired_request_id"].endswith("2800")
    assert payload["boundary_request_id"].endswith("2801")


def test_risk_seed_composes_with_existing_moderation_cluster(ctx):
    _client, SessionLocal, _ids = ctx
    moderator_token = "moderator-" + "m" * 40
    values = {
        "moderator_token": moderator_token,
        "safety_token": "safety-" + "s" * 40,
        "legal_token": "legal-" + "l" * 40,
        "response_token": "response-" + "r" * 40,
        "expired_response_token": "expired-" + "e" * 40,
        "boundary_response_token": "boundary-" + "b" * 40,
    }
    with SessionLocal() as session:
        provision_moderation(session, moderator_token)
        reports = [session.get(InternshipReport, ident) for ident in MODERATION_REPORT_IDS[:3]]
        organisation_ct = encrypt("Nyaya Legal Foundation")
        existing = DuplicateCluster(
            organisation_hash=keyed_hash("Nyaya Legal Foundation", lower=True),
            organisation_ciphertext=organisation_ct,
            key_version=key_version(organisation_ct),
            category="unsafe_environment",
            window_start=min(report.experience_end_date for report in reports),
            window_end=max(report.experience_end_date for report in reports),
            explanation_code="organisation_category_time_window_clean_evidence",
            state="eligible",
            idempotency_key="wave4-moderation-composition-cluster",
            actor_user_id=MODERATOR_ID,
            request_fingerprint=keyed_hash("wave4-moderation-composition-cluster"),
            version=1,
        )
        session.add(existing)
        session.flush()
        for report_id in MODERATION_REPORT_IDS[:3]:
            session.add(DuplicateClusterMember(
                cluster_id=existing.id,
                report_id=report_id,
                category="unsafe_environment",
            ))
        session.commit()

    with SessionLocal() as session:
        provision(session, **values)
        session.commit()
        risk_members = session.scalars(select(DuplicateClusterMember).where(
            DuplicateClusterMember.report_id.in_(RISK_REPORT_IDS)
        )).all()
    assert len(risk_members) == 9
    assert not ({item.report_id for item in risk_members} & set(MODERATION_REPORT_IDS))


def test_source_invalidator_targets_an_actual_published_risk_source(ctx):
    _client, SessionLocal, _ids = ctx
    values = {
        "moderator_token": "moderator-" + "m" * 40,
        "safety_token": "safety-" + "s" * 40,
        "legal_token": "legal-" + "l" * 40,
        "response_token": "response-" + "r" * 40,
        "expired_response_token": "expired-" + "e" * 40,
        "boundary_response_token": "boundary-" + "b" * 40,
    }
    with SessionLocal() as session:
        provision(session, **values)
        session.commit()
        result = invalidate_source(session)
        infected = session.scalars(select(InternshipReportEvidence).where(
            InternshipReportEvidence.report_id == RISK_REPORT_IDS[0],
            InternshipReportEvidence.scan_state == "infected",
        )).all()
        published_source = session.scalar(
            select(DuplicateClusterMember)
            .join(RiskSignal, RiskSignal.cluster_id == DuplicateClusterMember.cluster_id)
            .join(PublishedRiskLabel, PublishedRiskLabel.risk_signal_id == RiskSignal.id)
            .where(DuplicateClusterMember.report_id == RISK_REPORT_IDS[0])
        )
    assert result == {"updated_evidence": 1}
    assert len(infected) == 1
    assert published_source is not None


def _provision_response_invitation(SessionLocal):
    values = {
        "moderator_token": "moderator-" + "m" * 40,
        "safety_token": "safety-" + "s" * 40,
        "legal_token": "legal-" + "l" * 40,
        "response_token": "response-" + "r" * 40,
        "expired_response_token": "expired-" + "e" * 40,
        "boundary_response_token": "boundary-" + "b" * 40,
    }
    with SessionLocal() as session:
        fixture = provision(session, **values)
        session.commit()
    return {**values, **fixture}


def test_invitation_relay_uses_fragment_only_and_erases_delivered_secret(ctx, monkeypatch):
    _client, SessionLocal, _ids = ctx
    values = _provision_response_invitation(SessionLocal)
    monkeypatch.setattr(settings, "internship_response_public_base_url", "https://app.example/s-89")
    provider = DeterministicResponseInvitationProvider()
    with SessionLocal() as session:
        result = relay_response_invitations(session, provider, limit=1)
        row = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        assert (result.claimed, result.sent, result.failed, result.dead_lettered) == (1, 1, 0, 0)
        assert row.state == "sent"
        assert row.secret_ciphertext is None and row.secret_key_version is None
        assert row.claimed_at is None and row.sent_at is not None
        stored = json.dumps(row.payload_json) + repr(row.last_error_code)
    assert len(provider.deliveries) == 1
    delivery = provider.deliveries[0]
    parsed = urlsplit(delivery["invitation_url"])
    assert parsed.scheme == "https" and parsed.query == ""
    assert parsed.fragment == f"token={values['response_token']}"
    assert values["response_token"] not in stored
    # Provider idempotency is contractual: crash-after-send retry is a no-op.
    provider.send_invitation(**delivery)
    assert len(provider.deliveries) == 1


def test_worker_fails_closed_without_provider_and_does_not_claim(ctx, monkeypatch):
    _client, SessionLocal, _ids = ctx
    _provision_response_invitation(SessionLocal)
    monkeypatch.setattr(settings, "internship_response_notification_provider", "none")
    with pytest.raises(NotificationRelayError, match="notification_provider_unconfigured"):
        relay_once(session_factory=SessionLocal)
    with SessionLocal() as session:
        row = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        assert row.state == "pending" and row.attempts == 0
        assert row.secret_ciphertext is not None


def test_delivery_capture_is_mode_0600_confined_and_refuses_existing_target(
    tmp_path, monkeypatch
):
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    output = runner_temp / "private" / "delivery.json"
    _write_private(str(output), {"invitation_url": "https://app.example/s-89#token=opaque"})
    assert os.stat(output).st_mode & 0o777 == 0o600
    with pytest.raises(RuntimeError, match="must not already exist"):
        _write_private(str(output), {"invitation_url": "replacement"})
    with pytest.raises(RuntimeError, match="inside RUNNER_TEMP"):
        _write_private(str(tmp_path / "outside.json"), {"invitation_url": "outside"})


def test_worker_invokes_real_relay_contract_and_erases_secret(ctx, monkeypatch):
    _client, SessionLocal, _ids = ctx
    values = _provision_response_invitation(SessionLocal)
    monkeypatch.setattr(settings, "internship_response_public_base_url", "https://app.example/s-89")
    provider = DeterministicResponseInvitationProvider()
    result = relay_once(session_factory=SessionLocal, provider=provider, limit=1)
    assert (result.claimed, result.sent, result.failed, result.dead_lettered) == (1, 1, 0, 0)
    assert len(provider.deliveries) == 1
    with SessionLocal() as session:
        row = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        assert row.state == "sent" and row.secret_ciphertext is None
    delivery = provider.deliveries[0]
    parsed = urlsplit(delivery["invitation_url"])
    assert parsed.scheme == "https" and parsed.query == ""
    assert parsed.fragment == f"token={values['response_token']}"


def test_invitation_relay_retries_then_sends_and_retains_secret_only_for_retry(ctx, monkeypatch):
    _client, SessionLocal, _ids = ctx
    _provision_response_invitation(SessionLocal)
    monkeypatch.setattr(settings, "internship_response_public_base_url", "https://app.example/s-89")
    provider = DeterministicResponseInvitationProvider(fail_times=1)
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        first = relay_response_invitations(session, provider, limit=1, now=now)
        row = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        assert (first.claimed, first.failed) == (1, 1)
        assert row.state == "failed" and row.secret_ciphertext and row.secret_key_version
        assert row.claimed_at is None and row.last_error_code == "provider_unavailable"
        second = relay_response_invitations(
            session, provider, limit=1, now=now + timedelta(seconds=31)
        )
        session.refresh(row)
        assert (second.claimed, second.sent) == (1, 1)
        assert row.state == "sent" and row.secret_ciphertext is None


def test_invitation_relay_rejects_cross_organisation_envelope_and_erases_token(ctx, monkeypatch):
    _client, SessionLocal, _ids = ctx
    values = _provision_response_invitation(SessionLocal)
    monkeypatch.setattr(settings, "internship_response_public_base_url", "https://app.example/s-89")
    provider = DeterministicResponseInvitationProvider()
    with SessionLocal() as session:
        row = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        envelope = json.loads(decrypt(row.secret_ciphertext))
        envelope["organisation_id"] = str(uuid.uuid4())
        row.secret_ciphertext = encrypt(json.dumps(envelope, sort_keys=True, separators=(",", ":")))
        row.secret_key_version = key_version(row.secret_ciphertext)
        session.commit()
        result = relay_response_invitations(session, provider, limit=1)
        session.refresh(row)
        assert (result.claimed, result.dead_lettered) == (1, 1)
        assert row.state == "void" and row.secret_ciphertext is None
        assert row.last_error_code == "invitation_organisation_mismatch"
        assert provider.deliveries == []
        assert values["response_token"] not in json.dumps(row.payload_json)
        request = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
        assert request.state == "revoked"


def test_invitation_at_exact_expiry_is_void_and_secret_erased(ctx, monkeypatch):
    _client, SessionLocal, _ids = ctx
    _provision_response_invitation(SessionLocal)
    monkeypatch.setattr(settings, "internship_response_public_base_url", "https://app.example/s-89")
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        request = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
        request.expires_at = now
        session.commit()
        result = relay_response_invitations(
            session, DeterministicResponseInvitationProvider(), now=now, limit=1
        )
        row = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        session.refresh(request)
        assert (result.claimed, result.dead_lettered) == (1, 1)
        assert request.state == "expired"
        assert row.state == "void" and row.secret_ciphertext is None
        assert row.claimed_at is None and row.claim_token is None


def test_response_submission_at_exact_expiry_is_terminal_and_erases_secret(
    ctx, monkeypatch
):
    client, SessionLocal, _ids = ctx
    values = _provision_response_invitation(SessionLocal)
    _open_qa_gate(monkeypatch)
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        request = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
        request.expires_at = now
        session.commit()
    rejected = client.post(
        "/api/v1/organisation-responses",
        headers={
            "X-Organisation-Response-Token": values["response_token"],
            "Idempotency-Key": "expired-response-submit-0001",
        },
        json={"response_text": "This exact-expiry token must never be accepted."},
    )
    assert rejected.status_code == 404, rejected.text
    assert rejected.json()["detail"]["code"] == "response_token_unavailable"
    with SessionLocal() as session:
        request = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
        outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID,
            NotificationOutbox.event_kind == "organisation_response_requested",
        ))
        assert request.state == "expired" and request.version == 2
        assert outbox.state == "void"
        assert outbox.secret_ciphertext is None and outbox.secret_key_version is None
        assert outbox.claimed_at is None and outbox.claim_token is None
        assert outbox.last_error_code == "invitation_expired"


def test_invitation_just_before_expiry_is_delivered(ctx, monkeypatch):
    _client, SessionLocal, _ids = ctx
    _provision_response_invitation(SessionLocal)
    monkeypatch.setattr(settings, "internship_response_public_base_url", "https://app.example/s-89")
    now = datetime.now(timezone.utc)
    provider = DeterministicResponseInvitationProvider()
    with SessionLocal() as session:
        request = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
        request.expires_at = now + timedelta(microseconds=1)
        session.commit()
        result = relay_response_invitations(session, provider, now=now, limit=1)
        assert (result.claimed, result.sent) == (1, 1)
        assert len(provider.deliveries) == 1


def test_retry_exhaustion_revokes_request_and_erases_secret(ctx, monkeypatch):
    _client, SessionLocal, _ids = ctx
    _provision_response_invitation(SessionLocal)
    monkeypatch.setattr(settings, "internship_response_public_base_url", "https://app.example/s-89")
    with SessionLocal() as session:
        result = relay_response_invitations(
            session,
            DeterministicResponseInvitationProvider(fail_times=1),
            max_attempts=1,
            limit=1,
        )
        request = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
        row = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        assert (result.claimed, result.dead_lettered) == (1, 1)
        assert request.state == "revoked"
        assert row.state == "void" and row.secret_ciphertext is None


def test_expired_initial_is_voided_before_exactly_one_replacement(ctx, monkeypatch):
    client, SessionLocal, ids = ctx
    fixture = _provision_response_invitation(SessionLocal)
    _open_qa_gate(monkeypatch)
    with SessionLocal() as session:
        old = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
        old.expires_at = datetime.now(timezone.utc)
        session.commit()
    headers = {
        **_claims(ids["safety"], "safety_officer"),
        "Idempotency-Key": "renew-expired-initial-0001",
    }
    payload = {
        "published_label_id": fixture["prepublished_label_id"],
        "representative_verification_ref": "qa-renewed-representative",
        "verification_method": "qa_fixture",
        "request_kind": "initial",
    }
    replacement = client.post(
        "/api/v1/organisation-response-requests", headers=headers, json=payload
    )
    assert replacement.status_code == 201, replacement.text
    with SessionLocal() as session:
        old = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
        old_outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        assert old.state == "expired"
        assert old_outbox.state == "void"
        assert old_outbox.secret_ciphertext is None
        assert old_outbox.secret_key_version is None
        assert old_outbox.claimed_at is None and old_outbox.claim_token is None
    conflict = client.post(
        "/api/v1/organisation-response-requests",
        headers={**headers, "Idempotency-Key": "renew-active-initial-0002"},
        json=payload,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "initial_response_invitation_exists"


def test_consumed_token_voids_processing_invitation_and_blocks_second_initial(
    ctx, monkeypatch
):
    client, SessionLocal, ids = ctx
    fixture = _provision_response_invitation(SessionLocal)
    _open_qa_gate(monkeypatch)
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        envelope = json.loads(decrypt(outbox.secret_ciphertext))
        raw_token = envelope["invitation_token"]
        assert _claim(session, outbox, now=now) is True
        session.refresh(outbox)
        attempts, claim_token = outbox.attempts, outbox.claim_token
    submitted = client.post(
        "/api/v1/organisation-responses",
        headers={
            "X-Organisation-Response-Token": raw_token,
            "Idempotency-Key": "consume-processing-invitation-0001",
        },
        json={"response_text": "A pending initial response awaiting moderation."},
    )
    assert submitted.status_code == 201, submitted.text
    with SessionLocal() as session:
        outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        assert outbox.state == "void"
        assert outbox.secret_ciphertext is None and outbox.secret_key_version is None
        assert outbox.claimed_at is None and outbox.claim_token is None
        assert outbox.last_error_code == "invitation_consumed"
        assert _finish(
            session, outbox.id, state="sent", now=now,
            error_code=None, expected_attempts=attempts,
            expected_claim_token=claim_token,
        ) is False
    duplicate = client.post(
        "/api/v1/organisation-response-requests",
        headers={
            **_claims(ids["safety"], "safety_officer"),
            "Idempotency-Key": "duplicate-initial-during-moderation-0001",
        },
        json={
            "published_label_id": fixture["prepublished_label_id"],
            "representative_verification_ref": "qa-second-initial-blocked",
            "verification_method": "qa_fixture",
            "request_kind": "initial",
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"]["code"] == "initial_response_already_exists"


def test_public_projection_revalidates_evidence_and_live_approver(ctx, monkeypatch):
    client, SessionLocal, _ids = ctx
    fixture = _provision_response_invitation(SessionLocal)
    _open_qa_gate(monkeypatch)
    endpoint = f"/api/v1/public/internship-risk-labels/{fixture['organisation_id']}"
    baseline = client.get(endpoint)
    assert baseline.status_code == 200, baseline.text
    assert any(
        item["id"] == fixture["prepublished_label_id"]
        for item in baseline.json()["labels"]
    )
    with SessionLocal() as session:
        label = session.get(PublishedRiskLabel, uuid.UUID(fixture["prepublished_label_id"]))
        signal = session.get(RiskSignal, label.risk_signal_id)
        member = session.scalar(select(DuplicateClusterMember).where(
            DuplicateClusterMember.cluster_id == signal.cluster_id
        ).order_by(DuplicateClusterMember.id))
        evidence = session.scalar(select(InternshipReportEvidence).where(
            InternshipReportEvidence.report_id == member.report_id
        ).order_by(InternshipReportEvidence.id))
        evidence.scan_state = "infected"
        session.commit()
    hidden = client.get(endpoint)
    assert hidden.status_code == 200
    assert all(
        item["id"] != fixture["prepublished_label_id"]
        for item in hidden.json()["labels"]
    )


def test_representative_verification_authority_and_adapters_fail_closed(
    ctx, monkeypatch
):
    client, SessionLocal, ids = ctx
    fixture = _provision_response_invitation(SessionLocal)
    label_id = fixture["prepublished_label_id"]
    legal_id = uuid.uuid4()
    with SessionLocal() as session:
        # Retire the seed invitation so this test isolates verification
        # authority rather than the one-active-initial invariant.
        pending = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
        pending.state = "revoked"
        pending.version += 1
        outbox = session.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        outbox.state = "void"
        outbox.secret_ciphertext = None
        outbox.secret_key_version = None
        session.add(User(id=legal_id, role="legal_reviewer", status="active"))
        session.commit()
    _open_qa_gate(monkeypatch)

    def request(
        actor_id: uuid.UUID,
        claimed_role: str,
        method: str,
        key: str,
        ref: str = "opaque-verified-representative",
    ):
        return client.post(
            "/api/v1/organisation-response-requests",
            headers={
                **_claims(actor_id, claimed_role),
                "Idempotency-Key": key,
            },
            json={
                "published_label_id": label_id,
                "representative_verification_ref": ref,
                "verification_method": method,
                "request_kind": "initial",
            },
        )

    for actor_id, role in (
        (ids["safety"], "safety_officer"),
        (ids["admin"], "admin"),
    ):
        rejected = request(
            actor_id, role, "manual_legal_review", f"manual-nonlegal-{role}"
        )
        assert rejected.status_code == 403, rejected.text
        assert rejected.json()["detail"]["code"] == (
            "representative_verification_authority_required"
        )

    with SessionLocal() as session:
        legal = session.get(User, legal_id)
        legal.status = "suspended"
        session.commit()
    suspended = request(
        legal_id, "legal_reviewer", "manual_legal_review", "manual-suspended"
    )
    assert suspended.status_code == 403, suspended.text
    assert suspended.json()["detail"]["code"] == "risk_publication_actor_not_active"

    with SessionLocal() as session:
        legal = session.get(User, legal_id)
        legal.status = "active"
        legal.role = "safety_officer"
        session.commit()
    changed_role = request(
        legal_id, "legal_reviewer", "manual_legal_review", "manual-role-changed"
    )
    assert changed_role.status_code == 403, changed_role.text
    assert changed_role.json()["detail"]["code"] == "risk_publication_actor_not_active"

    domain = request(
        ids["safety"],
        "safety_officer",
        "verified_domain_challenge",
        "domain-adapter-unavailable",
    )
    assert domain.status_code == 422, domain.text
    assert domain.json()["detail"]["code"] == (
        "representative_verification_method_unavailable"
    )

    with SessionLocal() as session:
        legal = session.get(User, legal_id)
        legal.role = "legal_reviewer"
        session.commit()
    allowed = request(
        legal_id, "legal_reviewer", "manual_legal_review", "manual-legal-allowed"
    )
    assert allowed.status_code == 201, allowed.text

    monkeypatch.setattr(settings, "wave4_gate_allow_publication_test", False)
    qa_outside_seam = request(
        ids["safety"],
        "safety_officer",
        "qa_fixture",
        "qa-fixture-outside-seam",
        ref="qa-fixture-reference",
    )
    assert qa_outside_seam.status_code == 503, qa_outside_seam.text
    assert qa_outside_seam.json()["detail"]["code"] == "risk_labels_unavailable"


def test_dynamic_same_label_correction_targets_and_supersedes_exact_current_response(
    ctx, monkeypatch
):
    client, SessionLocal, ids = ctx
    fixture = _provision_response_invitation(SessionLocal)
    _open_qa_gate(monkeypatch)
    monkeypatch.setattr(settings, "internship_response_public_base_url", "https://app.example/s-89")

    initial = client.post(
        "/api/v1/organisation-responses",
        headers={
            "X-Organisation-Response-Token": fixture["response_token"],
            "Idempotency-Key": "dynamic-initial-response-0001",
        },
        json={"response_text": "Initial organisation response A."},
    )
    assert initial.status_code == 201, initial.text
    initial_body = initial.json()
    approved_initial = client.post(
        f"/api/v1/moderation/organisation-responses/{initial_body['id']}/decide",
        headers={
            **_claims(ids["moderator"], "moderator"),
            "Idempotency-Key": "dynamic-initial-approval-0001",
        },
        json={
            "decision": "approve",
            "reason_code": "verified_initial_response",
            "expected_version": initial_body["version"],
        },
    )
    assert approved_initial.status_code == 200, approved_initial.text

    correction_key = "dynamic-correction-request-0001"
    request = client.post(
        "/api/v1/organisation-response-requests",
        headers={
            **_claims(ids["safety"], "safety_officer"),
            "Idempotency-Key": correction_key,
        },
        json={
            "published_label_id": fixture["prepublished_label_id"],
            "representative_verification_ref": "qa-dynamic-correction",
            "verification_method": "qa_fixture",
            "request_kind": "correction",
        },
    )
    assert request.status_code == 201, request.text
    request_id = uuid.UUID(request.json()["id"])
    with SessionLocal() as session:
        request_row = session.get(OrganisationResponseRequest, request_id)
        assert request_row.target_response_id == uuid.UUID(initial_body["id"])

    provider = DeterministicResponseInvitationProvider()
    with SessionLocal() as session:
        relay_result = relay_response_invitations(session, provider, limit=100)
    assert relay_result.sent >= 1
    delivery = next(
        item for item in provider.deliveries
        if item["idempotency_key"] == f"notification:{correction_key}"
    )
    correction_token = urlsplit(delivery["invitation_url"]).fragment.removeprefix("token=")
    correction = client.post(
        "/api/v1/organisation-responses",
        headers={
            "X-Organisation-Response-Token": correction_token,
            "Idempotency-Key": "dynamic-correction-response-0001",
        },
        json={"response_text": "Approved organisation correction B."},
    )
    assert correction.status_code == 201, correction.text
    correction_body = correction.json()
    approved_correction = client.post(
        f"/api/v1/moderation/organisation-responses/{correction_body['id']}/decide",
        headers={
            **_claims(ids["moderator"], "moderator"),
            "Idempotency-Key": "dynamic-correction-approval-0001",
        },
        json={
            "decision": "approve",
            "reason_code": "verified_factual_correction",
            "expected_version": correction_body["version"],
        },
    )
    assert approved_correction.status_code == 200, approved_correction.text
    with SessionLocal() as session:
        predecessor = session.get(OrganisationResponse, uuid.UUID(initial_body["id"]))
        successor = session.get(OrganisationResponse, uuid.UUID(correction_body["id"]))
        currents = list(session.scalars(select(OrganisationResponse).where(
            OrganisationResponse.published_label_id == uuid.UUID(fixture["prepublished_label_id"]),
            OrganisationResponse.is_current.is_(True),
            OrganisationResponse.deleted_at.is_(None),
        )))
        assert predecessor.state == "superseded" and predecessor.is_current is False
        assert successor.state == "approved" and successor.is_current is True
        assert successor.supersedes_response_id == predecessor.id
        assert [row.id for row in currents] == [successor.id]
    public = client.get(
        f"/api/v1/public/internship-risk-labels/{fixture['organisation_id']}"
    )
    assert public.status_code == 200, public.text
    item = next(
        row for row in public.json()["labels"]
        if row["id"] == fixture["prepublished_label_id"]
    )
    assert item["status"] == "corrected"
    assert item["organisation_response"]["text"] == "Approved organisation correction B."

    label_id = uuid.UUID(fixture["prepublished_label_id"])
    successor_id = uuid.UUID(correction_body["id"])

    def projection():
        response = client.get(
            f"/api/v1/public/internship-risk-labels/{fixture['organisation_id']}"
        )
        assert response.status_code == 200, response.text
        return next(
            (row for row in response.json()["labels"] if row["id"] == str(label_id)),
            None,
        )

    # A ciphertext swap must not turn encrypted storage into unauthenticated
    # public copy. The label remains, but the response is suppressed.
    with SessionLocal() as session:
        successor = session.get(OrganisationResponse, successor_id)
        original_ciphertext = successor.response_ciphertext
        successor.response_ciphertext = encrypt("Attacker-swapped response text.")
        session.commit()
    assert projection()["organisation_response"] is None
    with SessionLocal() as session:
        successor = session.get(OrganisationResponse, successor_id)
        successor.response_ciphertext = original_ciphertext
        session.commit()
    assert projection()["organisation_response"]["text"] == (
        "Approved organisation correction B."
    )

    # The origin request is part of the public response chain. Removing it
    # suppresses the response instead of inventing an "initial" fallback.
    with SessionLocal() as session:
        successor = session.get(OrganisationResponse, successor_id)
        request_row = session.get(OrganisationResponseRequest, successor.request_id)
        request_row.deleted_at = datetime.now(timezone.utc)
        session.commit()
    assert projection()["organisation_response"] is None

    # Public labels are also a live governed projection: neither display copy
    # nor count may drift from the approved signal snapshot.
    with SessionLocal() as session:
        label = session.get(PublishedRiskLabel, label_id)
        label.neutral_label = "Unapproved public narrative"
        session.commit()
    assert projection() is None
    with SessionLocal() as session:
        label = session.get(PublishedRiskLabel, label_id)
        label.neutral_label = "Moderated excessive-hours pattern"
        label.public_count = 5
        session.commit()
    assert projection() is None

    # The approval quorum is live. A suspended approver no longer authorises
    # public visibility even though the historical decision row remains.
    with SessionLocal() as session:
        label = session.get(PublishedRiskLabel, label_id)
        label.public_count = None
        signal = session.get(RiskSignal, label.risk_signal_id)
        approval = session.scalar(select(RiskSignalApproval).where(
            RiskSignalApproval.risk_signal_id == signal.id,
            RiskSignalApproval.actor_role == "safety_officer",
            RiskSignalApproval.decision == "approve",
        ))
        approver = session.get(User, approval.actor_user_id)
        approver.status = "suspended"
        session.commit()
    assert projection() is None


def _publish_candidate(client, ids, fixture, *, expected_version=1, key="publish-candidate-0001"):
    return client.post(
        f"/api/v1/moderation/risk-labels/{fixture['candidate_cluster_id']}/publish",
        headers={
            **_claims(ids["safety"], "safety_officer"),
            "Idempotency-Key": key,
        },
        json={
            "expected_version": expected_version,
            "reason_code": "qa_governed_publication",
            "action": "publish",
        },
    )


def test_publication_accepts_exact_calendar_month_cutoff(ctx, monkeypatch):
    client, SessionLocal, ids = ctx
    fixture = _provision_response_invitation(SessionLocal)
    _open_qa_gate(monkeypatch)
    from app.services.moderation_service import _months_ago

    cutoff = _months_ago(
        datetime.now(timezone.utc).date(), settings.internship_risk_window_months
    )
    with SessionLocal() as session:
        cluster = session.get(DuplicateCluster, uuid.UUID(fixture["candidate_cluster_id"]))
        members = list(session.scalars(select(DuplicateClusterMember).where(
            DuplicateClusterMember.cluster_id == cluster.id,
            DuplicateClusterMember.deleted_at.is_(None),
        )))
        for member in members:
            report = session.get(InternshipReport, member.report_id)
            report.experience_start_date = cutoff
            report.experience_end_date = cutoff
        cluster.window_start = cutoff
        cluster.window_end = cutoff
        session.commit()
    response = _publish_candidate(client, ids, fixture)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "published"


@pytest.mark.parametrize(
    "failure_mode",
    [
        "infected_evidence",
        "case_not_approved",
        "report_not_approved",
        "category_deleted",
        "vault_deleted",
        "outside_window",
        "organisation_changed",
        "signal_count_changed",
        "approver_inactive",
        "approval_veto",
    ],
)
def test_publication_revalidates_every_live_source_and_active_approval(
    ctx, monkeypatch, failure_mode
):
    client, SessionLocal, ids = ctx
    fixture = _provision_response_invitation(SessionLocal)
    _open_qa_gate(monkeypatch)
    cluster_id = uuid.UUID(fixture["candidate_cluster_id"])
    with SessionLocal() as session:
        cluster = session.get(DuplicateCluster, cluster_id)
        signal = session.scalar(select(RiskSignal).where(RiskSignal.cluster_id == cluster.id))
        members = list(session.scalars(select(DuplicateClusterMember).where(
            DuplicateClusterMember.cluster_id == cluster.id,
            DuplicateClusterMember.deleted_at.is_(None),
        )))
        report_id = members[0].report_id
        now = datetime.now(timezone.utc)
        if failure_mode == "infected_evidence":
            evidence = session.scalar(select(InternshipReportEvidence).where(
                InternshipReportEvidence.report_id == report_id,
                InternshipReportEvidence.deleted_at.is_(None),
            ))
            evidence.scan_state = "infected"
        elif failure_mode == "case_not_approved":
            case = session.scalar(select(ModerationCase).where(
                ModerationCase.report_id == report_id,
                ModerationCase.deleted_at.is_(None),
            ))
            case.state = "pending"
            case.assigned_moderator_user_id = None
            case.claimed_at = None
        elif failure_mode == "report_not_approved":
            session.get(InternshipReport, report_id).status = "moderation_pending"
        elif failure_mode == "category_deleted":
            category = session.scalar(select(InternshipReportCategory).where(
                InternshipReportCategory.report_id == report_id,
                InternshipReportCategory.category == cluster.category,
            ))
            category.deleted_at = now
        elif failure_mode == "vault_deleted":
            vault = session.scalar(select(ReporterIdentityVault).where(
                ReporterIdentityVault.report_id == report_id
            ))
            vault.deleted_at = now
        elif failure_mode == "outside_window":
            from app.services.moderation_service import _months_ago
            cutoff = _months_ago(now.date(), settings.internship_risk_window_months)
            report = session.get(InternshipReport, report_id)
            report.experience_start_date = cutoff - timedelta(days=2)
            report.experience_end_date = cutoff - timedelta(days=1)
            cluster.window_start = min(
                session.get(InternshipReport, item.report_id).experience_end_date
                for item in members
            )
        elif failure_mode == "organisation_changed":
            session.get(InternshipReport, report_id).organisation_name = "Changed Organisation"
        elif failure_mode == "signal_count_changed":
            signal.report_count += 1
        elif failure_mode == "approver_inactive":
            moderator_approval = session.scalar(select(RiskSignalApproval).where(
                RiskSignalApproval.risk_signal_id == signal.id,
                RiskSignalApproval.actor_role == "moderator",
            ))
            session.get(User, moderator_approval.actor_user_id).status = "suspended"
        elif failure_mode == "approval_veto":
            veto_actor = User(role="legal_reviewer", status="active")
            session.add(veto_actor)
            session.flush()
            session.add(RiskSignalApproval(
                risk_signal_id=signal.id,
                actor_user_id=veto_actor.id,
                actor_role="legal_reviewer",
                decision="reject",
                reason_code="qa_publication_veto",
            ))
        session.commit()
    response = _publish_candidate(
        client,
        ids,
        fixture,
        key=f"publish-invalid-{failure_mode}",
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "risk_publication_prerequisites_missing"
    with SessionLocal() as session:
        signal = session.scalar(select(RiskSignal).where(RiskSignal.cluster_id == cluster_id))
        assert session.scalar(select(PublishedRiskLabel).where(
            PublishedRiskLabel.risk_signal_id == signal.id,
            PublishedRiskLabel.deleted_at.is_(None),
        )) is None


def test_publication_rejects_stale_signal_version_without_projection(ctx, monkeypatch):
    client, SessionLocal, ids = ctx
    fixture = _provision_response_invitation(SessionLocal)
    _open_qa_gate(monkeypatch)
    response = _publish_candidate(
        client, ids, fixture, expected_version=999, key="publish-stale-version-0001"
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_risk_signal"


def test_stale_claimant_cannot_finish_after_another_worker_reclaims(ctx):
    _client, SessionLocal, _ids = ctx
    _provision_response_invitation(SessionLocal)
    first_now = datetime.now(timezone.utc)
    first = SessionLocal()
    second = SessionLocal()
    try:
        row_one = first.scalar(select(NotificationOutbox).where(
            NotificationOutbox.aggregate_id == RESPONSE_REQUEST_ID
        ))
        assert _claim(first, row_one, now=first_now) is True
        first.refresh(row_one)
        first_claim = row_one
        assert first_claim.attempts == 1 and first_claim.claim_token is not None
        first_attempt = first_claim.attempts
        first_claim_token = first_claim.claim_token

        row_two = second.get(NotificationOutbox, row_one.id)
        second_now = first_now + timedelta(minutes=6)
        assert _claim(second, row_two, now=second_now) is True
        second.refresh(row_two)
        second_claim = row_two
        assert second_claim.attempts == first_attempt + 1
        assert _finish(
            first,
            row_one.id,
            state="sent",
            now=second_now,
            error_code=None,
            expected_attempts=first_attempt,
            expected_claim_token=first_claim_token,
        ) is False
        second.refresh(second_claim)
        assert second_claim.state == "processing"
        assert second_claim.secret_ciphertext is not None
        assert _finish(
            second,
            row_one.id,
            state="sent",
            now=second_now,
            error_code=None,
            expected_attempts=second_claim.attempts,
            expected_claim_token=second_claim.claim_token,
        ) is True
    finally:
        first.close()
        second.close()


def test_deterministic_provider_rejects_idempotency_key_payload_conflict():
    provider = DeterministicResponseInvitationProvider()
    organisation_id = uuid.uuid4()
    payload = {
        "organisation_id": organisation_id,
        "delivery_ref": "opaque-ref-0001",
        "invitation_url": "https://app.example/s-89#token=one",
        "idempotency_key": "delivery-0001",
    }
    provider.send_invitation(**payload)
    with pytest.raises(NotificationRelayError, match="provider_idempotency_conflict"):
        provider.send_invitation(**{**payload, "invitation_url": "https://app.example/s-89#token=two"})
