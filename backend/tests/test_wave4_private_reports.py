"""SAATHI-269/450 private-report API, validation and privacy proof."""
from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import ConfigurationError, Settings, settings
from app.core.crypto import decrypt, keyed_hash
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.integrations.storage import FilesystemStorageAdapter
from app.models.registration import User
from app.models.wave4 import (
    REPORT_CATEGORIES,
    InternshipReport,
    InternshipReportEvidence,
    InternshipReportingOutbox,
    ModerationHandoff,
    ReporterIdentityVault,
)
from app.services.report_storage import (
    ClamAVReportEvidenceScanner,
    DeterministicReportEvidenceScanner,
    ReportEvidenceInfected,
    ReportEvidenceScanUnavailable,
    get_report_evidence_scanner,
    get_report_storage,
)
from tests import apptemplate, dbtemplate


def _claims(user_id: uuid.UUID, *roles: str) -> dict[str, str]:
    return {"X-Actor-Claims": json.dumps({"sub": str(user_id), "roles": list(roles)})}


@pytest.fixture(scope="module")
def _mounted():
    return apptemplate.mounted_app(exception_handlers=True, raise_server_exceptions=False)


@pytest.fixture()
def ctx(tmp_path, _mounted):
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

    storage = FilesystemStorageAdapter(tmp_path / "report-objects")
    app, client = _mounted
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[get_report_storage] = lambda: storage
    app.dependency_overrides[get_report_evidence_scanner] = DeterministicReportEvidenceScanner

    with SessionLocal() as session:
        student = User(role="student", status="active")
        other = User(role="student", status="active")
        lawyer = User(role="lawyer", status="active")
        session.add_all([student, other, lawyer])
        session.commit()
        ids = {"student": student.id, "other": other.id, "lawyer": lawyer.id}
    yield client, SessionLocal, storage, ids, app
    engine.dispose()


def _create(client: TestClient, ids, payload=None, key="report-create-0001"):
    return client.post(
        "/api/v1/internship-reports",
        headers={**_claims(ids["student"], "student"), "Idempotency-Key": key},
        json=payload or {},
    )


def _valid_patch(version=1, **updates):
    payload = {
        "expected_version": version,
        "organisation_name": "Nyaya Legal Foundation",
        "listing_application_ref": "APP-2026-1042",
        "experience_start_date": "2026-05-01",
        "experience_end_date": "2026-06-30",
        "categories": ["unsafe_environment", "stipend_delay_exploitative"],
        "narrative": "During the placement, the agreed stipend was delayed and safety procedures were not explained clearly.",
        "privacy_mode": "anonymous",
        "consent_accepted": True,
        "consent_version": settings.internship_report_consent_version,
    }
    payload.update(updates)
    return payload


def _patch(client, ids, report_id, payload):
    return client.patch(
        f"/api/v1/internship-reports/{report_id}",
        headers=_claims(ids["student"], "student"),
        json=payload,
    )


def _pdf(body=b"clean private evidence") -> bytes:
    return b"%PDF-1.7\n" + body


def _upload(client, ids, report_id, version, *, name="evidence.pdf", body=None, mime="application/pdf"):
    return client.post(
        f"/api/v1/internship-reports/{report_id}/evidence",
        headers=_claims(ids["student"], "student"),
        data={"expected_version": str(version)},
        files={"file": (name, body if body is not None else _pdf(), mime)},
    )


def test_complete_private_report_journey_and_db_privacy(ctx):
    client, SessionLocal, storage, ids, _ = ctx
    created = _create(client, ids)
    assert created.status_code == 201, created.text
    report_id = created.json()["id"]
    assert created.json()["privacy_mode"] == "anonymous"
    assert created.json()["status"] == "draft"

    saved = _patch(client, ids, report_id, _valid_patch())
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2
    evidence = _upload(client, ids, report_id, 2)
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["scan_state"] == "clean"

    submitted = client.post(
        f"/api/v1/internship-reports/{report_id}/submit",
        headers=_claims(ids["student"], "student"),
        json={"expected_version": 3},
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "moderation_pending"
    assert submitted.json()["support_guidance_required"] is True
    replay = client.post(
        f"/api/v1/internship-reports/{report_id}/submit",
        headers=_claims(ids["student"], "student"),
        json={"expected_version": 3},
    )
    assert replay.status_code == 200
    # SQLite reloads timezone-aware timestamps without the UTC suffix. Compare
    # the same instant rather than a dialect-specific wire spelling.
    assert replay.json()["submitted_at"].rstrip("Z") == submitted.json()["submitted_at"].rstrip("Z")

    status = client.get(
        f"/api/v1/internship-reports/{report_id}/status",
        headers=_claims(ids["student"], "student"),
    )
    assert status.status_code == 200
    assert status.json()["evidence_total"] == status.json()["evidence_clean"] == 1

    with SessionLocal() as session:
        report = session.get(InternshipReport, uuid.UUID(report_id))
        vault = session.scalar(select(ReporterIdentityVault).where(ReporterIdentityVault.report_id == report.id))
        stored_evidence = session.scalar(select(InternshipReportEvidence).where(InternshipReportEvidence.report_id == report.id))
        assert vault and vault.reporter_lookup_hash == keyed_hash(str(ids["student"]), lower=True)
        assert str(ids["student"]) not in vault.reporter_ciphertext
        assert decrypt(vault.reporter_ciphertext) == str(ids["student"])
        assert stored_evidence and storage.exists(stored_evidence.object_ref)
        assert session.scalar(select(ModerationHandoff).where(ModerationHandoff.report_id == report.id))
        assert len(session.scalars(select(InternshipReportingOutbox).where(InternshipReportingOutbox.aggregate_id == report.id)).all()) == 2
        audit_json = json.dumps(
            [{"before": row.before_state, "after": row.after_state, "actor": str(row.actor_user_id)} for row in session.scalars(select(AuditEvent).where(AuditEvent.resource_id == report.id))]
        )
        for forbidden in (
            str(ids["student"]),
            "Nyaya Legal Foundation",
            "APP-2026-1042",
            "agreed stipend",
            "evidence.pdf",
        ):
            assert forbidden not in audit_json
        assert session.scalar(select(InternshipReport.id)) == report.id

    columns = {column["name"] for column in inspect(SessionLocal.kw["bind"]).get_columns("internship_reports")}
    assert not columns & {"user_id", "reporter_id", "author_id", "mobile", "email", "reporter_lookup_hash"}


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        ({"experience_start_date": "2030-01-01"}, "validation_error"),
        ({"experience_end_date": "2030-01-01"}, "validation_error"),
        ({"organisation_name": "<script>bad</script>"}, "validation_error"),
        ({"listing_application_ref": "x" * 121}, "validation_error"),
        ({"narrative": "x" * 5001}, "validation_error"),
        ({"categories": ["invented_category"]}, "validation_error"),
        ({"privacy_mode": "public"}, "validation_error"),
    ],
)
def test_draft_boundary_validation_rejects_without_echo_or_mutation(ctx, payload, expected_code):
    client, SessionLocal, _, ids, _ = ctx
    response = _create(client, ids, payload, key=f"negative-{uuid.uuid4()}")
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == expected_code
    body = json.dumps(response.json())
    assert "input" not in body and "<script>" not in body
    with SessionLocal() as session:
        assert session.scalar(select(InternshipReport.id)) is None


@pytest.mark.parametrize(
    ("update", "expected_code"),
    [
        ({"organisation_name": ""}, "organisation_required"),
        ({"listing_application_ref": ""}, "listing_application_reference_required"),
        ({"experience_start_date": None}, "experience_start_date_required"),
        ({"experience_end_date": None}, "experience_end_date_required"),
        ({"categories": []}, "category_required"),
        ({"narrative": "x" * 49}, "narrative_length_invalid"),
        ({"consent_accepted": False}, "consent_required"),
        ({"consent_version": "obsolete"}, "consent_version_stale"),
    ],
)
def test_submit_required_and_boundary_matrix_is_typed_and_non_mutating(ctx, update, expected_code):
    client, SessionLocal, _, ids, _ = ctx
    report_id = _create(client, ids, key=f"submit-negative-{uuid.uuid4()}").json()["id"]
    saved = _patch(client, ids, report_id, _valid_patch(**update))
    assert saved.status_code == 200, saved.text
    response = client.post(
        f"/api/v1/internship-reports/{report_id}/submit",
        headers=_claims(ids["student"], "student"),
        json={"expected_version": saved.json()["version"]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == expected_code
    with SessionLocal() as session:
        report = session.get(InternshipReport, uuid.UUID(report_id))
        assert report.status == "draft" and report.submitted_at is None
        assert session.scalar(select(ModerationHandoff.id)) is None


def test_exact_narrative_and_text_max_boundaries_pass(ctx):
    client, _, _, ids, _ = ctx
    report_id = _create(client, ids, key="exact-boundaries-0001").json()["id"]
    saved = _patch(
        client,
        ids,
        report_id,
        _valid_patch(
            organisation_name="O" * 160,
            listing_application_ref="R" * 120,
            narrative="N" * 5000,
            categories=list(REPORT_CATEGORIES),
        ),
    )
    assert saved.status_code == 200, saved.text
    assert len(saved.json()["narrative"]) == 5000
    submitted = client.post(
        f"/api/v1/internship-reports/{report_id}/submit",
        headers=_claims(ids["student"], "student"),
        json={"expected_version": saved.json()["version"]},
    )
    assert submitted.status_code == 200, submitted.text


def test_auth_role_and_cross_user_are_non_enumerating(ctx):
    client, _, _, ids, _ = ctx
    report_id = _create(client, ids).json()["id"]
    assert client.get(f"/api/v1/internship-reports/{report_id}").status_code == 401
    assert client.get(f"/api/v1/internship-reports/{report_id}", headers=_claims(ids["lawyer"], "lawyer")).status_code == 403
    other = client.get(f"/api/v1/internship-reports/{report_id}", headers=_claims(ids["other"], "student"))
    missing = client.get(f"/api/v1/internship-reports/{uuid.uuid4()}", headers=_claims(ids["other"], "student"))
    assert other.status_code == missing.status_code == 404
    assert other.json()["detail"]["code"] == missing.json()["detail"]["code"]


def test_idempotency_stale_version_and_submitted_mutations_fail_closed(ctx):
    client, SessionLocal, _, ids, _ = ctx
    first = _create(client, ids, key="idempotent-report-0001")
    again = _create(client, ids, key="idempotent-report-0001")
    assert first.status_code == 201 and again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    report_id = first.json()["id"]
    saved = _patch(client, ids, report_id, _valid_patch())
    stale = _patch(client, ids, report_id, {"expected_version": 1, "narrative": "x" * 60})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_report_version"
    submitted = client.post(
        f"/api/v1/internship-reports/{report_id}/submit",
        headers=_claims(ids["student"], "student"),
        json={"expected_version": saved.json()["version"]},
    )
    assert submitted.status_code == 200
    refused = _patch(client, ids, report_id, {"expected_version": submitted.json()["version"], "narrative": "changed " * 10})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "report_not_mutable"
    with SessionLocal() as session:
        assert session.scalar(select(func_count(InternshipReport))) == 1


def test_create_flush_integrity_error_is_caught_and_typed(ctx, monkeypatch):
    """PostgreSQL can raise the idempotency UNIQUE conflict at flush, not commit.

    The target-runtime gate proves the winning-row replay. This focused test
    locks the transaction boundary so a future refactor cannot move ``flush``
    outside the IntegrityError handler and leak a raw 500 again.
    """
    client, _, _, ids, _ = ctx
    original_flush = Session.flush
    calls = 0
    raised = False

    def conflicting_flush(session, *args, **kwargs):
        nonlocal calls, raised
        if not raised and any(isinstance(item, InternshipReport) for item in session.new):
            calls += 1
            raised = True
            raise IntegrityError("INSERT internship_reports", {}, Exception("unique race"))
        return original_flush(session, *args, **kwargs)

    monkeypatch.setattr(Session, "flush", conflicting_flush)
    response = _create(client, ids, key="flush-race-typed-0001")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "idempotency_conflict"


def func_count(model):
    from sqlalchemy import func
    return func.count(model.id)


def test_evidence_signature_mime_extension_size_count_and_scanner_fail_closed(ctx, monkeypatch):
    client, SessionLocal, storage, ids, app = ctx
    report_id = _create(client, ids, key="evidence-matrix-0001").json()["id"]
    version = 1
    bad_cases = [
        ("empty.pdf", b"", "application/pdf", "empty_evidence"),
        ("fake.pdf", b"plain text", "application/pdf", "unsupported_evidence_type"),
        ("spoof.png", _pdf(), "image/png", "mime_mismatch"),
        ("wrong.txt", _pdf(), "application/pdf", "extension_mismatch"),
    ]
    for name, body, mime, code in bad_cases:
        response = _upload(client, ids, report_id, version, name=name, body=body, mime=mime)
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == code
    monkeypatch.setattr(settings, "internship_report_max_file_bytes", 32)
    oversized = _upload(client, ids, report_id, version, body=_pdf(b"x" * 32))
    assert oversized.status_code == 422
    assert oversized.json()["detail"]["code"] == "evidence_too_large"
    monkeypatch.setattr(settings, "internship_report_max_file_bytes", 5 * 1024 * 1024)

    for index in range(5):
        response = _upload(client, ids, report_id, version, body=_pdf(f"clean-{index}".encode()))
        assert response.status_code == 200, response.text
        version += 1
    sixth = _upload(client, ids, report_id, version, body=_pdf(b"sixth"))
    assert sixth.status_code == 422 and sixth.json()["detail"]["code"] == "evidence_file_limit"

    other_id = _create(client, ids, key="scanner-outage-0001").json()["id"]
    unavailable = _upload(client, ids, other_id, 1, body=_pdf(b"SCANNER_UNAVAILABLE"))
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "evidence_scanner_unavailable"
    with SessionLocal() as session:
        row = session.scalar(select(InternshipReportEvidence).where(InternshipReportEvidence.report_id == uuid.UUID(other_id)))
        assert row and row.scan_state == "retryable_failure" and storage.exists(row.object_ref)

    infected_id = _create(client, ids, key="scanner-infected-0001").json()["id"]
    infected = _upload(
        client,
        ids,
        infected_id,
        1,
        body=_pdf(b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"),
    )
    assert infected.status_code == 422 and infected.json()["detail"]["code"] == "infected_evidence"
    with SessionLocal() as session:
        assert session.scalar(select(InternshipReportEvidence.id).where(InternshipReportEvidence.report_id == uuid.UUID(infected_id))) is None

    app.dependency_overrides[get_report_evidence_scanner] = DeterministicReportEvidenceScanner


def test_public_label_configuration_is_disabled_and_cannot_be_enabled():
    assert Settings(_env_file=None).internship_risk_labels_enabled is False
    with pytest.raises(ConfigurationError) as refused:
        Settings(_env_file=None, internship_risk_labels_enabled=True)
    assert "internship_risk_labels_enabled" in str(refused.value)


def test_production_requires_real_clamav_scanner():
    with pytest.raises(ConfigurationError) as refused:
        Settings(
            _env_file=None,
            app_env="production",
            registration_secret="production-registration-encryption-secret",
            registration_lookup_secret="production-registration-lookup-secret",
            internship_report_scanner_provider="deterministic",
        )
    assert "must be clamav" in str(refused.value)


class _FakeClamdSocket:
    def __init__(self, response: bytes):
        self.response = response
        self.sent = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, _timeout):
        return None

    def sendall(self, data: bytes):
        self.sent.extend(data)

    def recv(self, _size: int) -> bytes:
        response, self.response = self.response, b""
        return response


@pytest.mark.parametrize(
    ("response", "expected"),
    [(b"stream: OK\0", "clean"), (b"stream: Eicar-Signature FOUND\0", "infected"), (b"stream: ERROR\0", "unavailable")],
)
def test_clamav_instream_adapter_is_fail_closed(monkeypatch, response, expected):
    connection = _FakeClamdSocket(response)
    monkeypatch.setattr("socket.create_connection", lambda *_args, **_kwargs: connection)
    scanner = ClamAVReportEvidenceScanner("scanner.internal", 3310, 2.0)
    if expected == "infected":
        with pytest.raises(ReportEvidenceInfected):
            scanner.scan(_pdf())
    elif expected == "unavailable":
        with pytest.raises(ReportEvidenceScanUnavailable):
            scanner.scan(_pdf())
    else:
        assert scanner.scan(_pdf()) == "clean"
    assert connection.sent.startswith(b"zINSTREAM\0")
    assert connection.sent.endswith(b"\x00\x00\x00\x00")


def test_clamav_network_failure_remains_quarantined(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise OSError("scanner offline")

    monkeypatch.setattr("socket.create_connection", unavailable)
    with pytest.raises(ReportEvidenceScanUnavailable):
        ClamAVReportEvidenceScanner("scanner.internal", 3310).scan(_pdf())


def test_public_risk_label_route_is_present_but_fails_closed(ctx):
    client, _, _, _, _ = ctx
    response = client.get(f"/api/v1/public/internship-risk-labels/{uuid.uuid4()}")
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "risk_labels_unavailable",
        "message": "Public internship risk labels are not available",
        "retryable": False,
    }
