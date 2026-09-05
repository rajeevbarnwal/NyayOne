"""Functional NYAY-22 session-ceremony and fail-closed lifecycle contracts."""
from __future__ import annotations

import base64
import hashlib
import inspect
import json
import uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.auth_mentor import _MAX_MENTOR_BODY_BYTES, router
from app.core.config import settings
from app.core.crypto import decrypt, encrypt, keyed_hash
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.mentor_auth import (
    MentorAuthorityStepUp,
    MentorAuditLink,
    MentorBootstrapAttempt,
    MentorCeremony,
    MentorConsent,
    MentorEngagement,
    MentorIdempotencyRecord,
    MentorInvitation,
    MentorProviderResult,
    MentorRateBucket,
    MentorSession,
    MentorSubjectConsent,
    TutorProfileOwnershipProof,
)
from app.models.registration import AuthSession, StudentProfile, StudentRegistration, User
from app.models.wave2 import TutorProfile
from app.services.mentor_ceremony import (
    BOOTSTRAP_COOKIE,
    CEREMONY_COOKIE,
    MENTOR_COOKIE_PATH,
    SESSION_COOKIE,
    _seeded_token,
    _token_hash,
)
from app.services import mentor_ceremony
from tests import dbtemplate


def test_runtime_openapi_exactly_matches_sealed_mentor_namespace():
    """Generated docs must not invent an authorization or failure shape."""

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    live = app.openapi()
    repository = Path(__file__).resolve().parents[2]
    design_path = (
        repository
        / "docs/architecture/nyay29-tutor-lawyer-ceremony"
        / "CEREMONY_API_CONTRACT.openapi.json"
    )
    runtime_path = (
        repository / "backend/app/schemas/nyay22_mentor_contract.openapi.json"
    )
    assert hashlib.sha256(runtime_path.read_bytes()).digest() == hashlib.sha256(
        design_path.read_bytes()
    ).digest()
    sealed = json.loads(design_path.read_text(encoding="utf-8"))
    assert {path: live["paths"][path] for path in sealed["paths"]} == sealed["paths"]
    for section in ("securitySchemes", "headers", "responses"):
        assert live["components"][section] == sealed["components"][section]
    assert {
        name: live["components"]["schemas"][name]
        for name in sealed["components"]["schemas"]
    } == sealed["components"]["schemas"]


def test_unexpected_service_failure_rolls_back_and_is_privacy_safe(
    ceremony_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = ceremony_ctx
    planted = "opaque-driver-detail-that-must-not-escape"

    def crash_after_flush(*, db, **_kwargs):
        db.add(User(role="student", status="active"))
        db.flush()
        raise RuntimeError(planted)

    monkeypatch.setattr(mentor_ceremony, "initiate", crash_after_flush)
    response = client.post(
        "/api/v1/auth/mentor/ceremony/initiate",
        headers={"Idempotency-Key": "unexpected-db-error-key-00000001"},
        json={
            "intent": "mentor_session",
            "requestedMentorRole": "tutor",
            "purposeCode": "student_guidance",
            "privacyNoticeVersion": "mentor-privacy.v1",
        },
    )
    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "CONCURRENT_STATE_CHANGED",
            "message": "Request failed",
            "retryable": True,
        }
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    assert planted not in response.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 0


def test_mentor_request_body_is_cumulatively_bounded_before_service(
    ceremony_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Declared and chunked oversized bodies fail with no service mutation."""

    client, _factory = ceremony_ctx
    calls = 0

    def must_not_run(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("bounded request reached service")

    monkeypatch.setattr(mentor_ceremony, "initiate", must_not_run)
    planted = b"opaque-mentor-body-secret"
    oversized = b"{" + planted + (b"x" * _MAX_MENTOR_BODY_BYTES) + b"}"
    response = client.post(
        "/api/v1/auth/mentor/ceremony/initiate",
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(oversized)),
            "Idempotency-Key": "oversized-body-contract-key-0001",
        },
        content=oversized,
    )
    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "code": "INVALID_REQUEST",
            "message": "Request failed",
            "retryable": False,
            "field": "request",
        }
    }
    assert planted.decode() not in response.text

    def chunks():
        yield b"{" + planted
        yield b"x" * _MAX_MENTOR_BODY_BYTES
        yield b"}"

    chunked = client.post(
        "/api/v1/auth/mentor/ceremony/initiate",
        headers={
            "Content-Type": "application/json",
            # An untrusted declared length cannot bypass the stream ceiling.
            "Content-Length": "1",
            "Idempotency-Key": "chunked-body-contract-key-00001",
        },
        content=chunks(),
    )
    assert chunked.status_code == 400
    assert chunked.json()["detail"]["code"] == "INVALID_REQUEST"
    assert planted.decode() not in chunked.text
    assert calls == 0


def test_exact_mentor_request_body_ceiling_reaches_normal_validation(
    ceremony_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact ceiling is accepted; the service receives parsed authority intent."""

    client, _factory = ceremony_ctx
    payload = {
        "intent": "mentor_session",
        "requestedMentorRole": "tutor",
        "purposeCode": "student_guidance",
        "privacyNoticeVersion": "mentor-privacy.v1",
    }
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    body = encoded + (b" " * (_MAX_MENTOR_BODY_BYTES - len(encoded)))
    observed: dict[str, object] = {}

    def accepted(*, body, **_kwargs):
        observed.update(body.model_dump(mode="json", by_alias=True))
        return {
            "schemaVersion": "mentor-ceremony.v1",
            "status": "accepted",
            "ceremonyState": "challenge_issued",
            "next": "external_identity",
            "intent": "mentor_session",
            "expiresInSeconds": 900,
        }

    monkeypatch.setattr(mentor_ceremony, "initiate", accepted)
    response = client.post(
        "/api/v1/auth/mentor/ceremony/initiate",
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": "exact-body-ceiling-contract-key-01",
        },
        content=body,
    )
    assert response.status_code == 202
    assert observed["purposeCode"] == "student_guidance"


@pytest.mark.parametrize(
    ("field", "value", "payload"),
    (
        (
            "acceptPurpose",
            1,
            {
                "intent": "mentor_session",
                "expectedCeremonyState": "proof_verified",
                "purposeCode": "student_guidance",
                "consentReceiptVersion": "mentor-consent.v1",
                "acceptanceTextVersion": "mentor-acceptance.v1",
            },
        ),
        (
            "acceptPurpose",
            1.0,
            {
                "intent": "mentor_session",
                "expectedCeremonyState": "proof_verified",
                "purposeCode": "student_guidance",
                "consentReceiptVersion": "mentor-consent.v1",
                "acceptanceTextVersion": "mentor-acceptance.v1",
            },
        ),
        (
            "acceptPurpose",
            "true",
            {
                "intent": "mentor_session",
                "expectedCeremonyState": "proof_verified",
                "purposeCode": "student_guidance",
                "consentReceiptVersion": "mentor-consent.v1",
                "acceptanceTextVersion": "mentor-acceptance.v1",
            },
        ),
        (
            "acceptPurpose",
            "1",
            {
                "intent": "mentor_session",
                "expectedCeremonyState": "proof_verified",
                "purposeCode": "student_guidance",
                "consentReceiptVersion": "mentor-consent.v1",
                "acceptanceTextVersion": "mentor-acceptance.v1",
            },
        ),
        (
            "acceptAuthorityDeletionStepUp",
            1,
            {
                "intent": "authority_deletion_step_up",
                "expectedCeremonyState": "proof_verified",
                "acceptanceTextVersion": "mentor-authority-deletion.v1",
            },
        ),
        (
            "acceptAuthorityDeletionStepUp",
            1.0,
            {
                "intent": "authority_deletion_step_up",
                "expectedCeremonyState": "proof_verified",
                "acceptanceTextVersion": "mentor-authority-deletion.v1",
            },
        ),
        (
            "acceptAuthorityDeletionStepUp",
            "true",
            {
                "intent": "authority_deletion_step_up",
                "expectedCeremonyState": "proof_verified",
                "acceptanceTextVersion": "mentor-authority-deletion.v1",
            },
        ),
        (
            "acceptAuthorityDeletionStepUp",
            "1",
            {
                "intent": "authority_deletion_step_up",
                "expectedCeremonyState": "proof_verified",
                "acceptanceTextVersion": "mentor-authority-deletion.v1",
            },
        ),
    ),
)
def test_explicit_acceptance_fields_require_the_exact_json_boolean_true(
    ceremony_ctx,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    payload: dict[str, object],
) -> None:
    """Numeric/string truthiness can never become legal or security assent."""

    client, _factory = ceremony_ctx
    calls = 0

    def must_not_run(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("non-Boolean acceptance reached the service")

    monkeypatch.setattr(mentor_ceremony, "exchange", must_not_run)
    response = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "strict-acceptance-contract-key-0001"},
        json={**payload, field: value},
    )
    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "code": "INVALID_REQUEST",
            "message": "Request failed",
            "retryable": False,
            "field": "request",
        }
    }
    assert calls == 0


@pytest.mark.parametrize(
    ("path", "service_name", "payload"),
    (
        (
            "/api/v1/auth/mentor/ceremony/initiate",
            "initiate",
            {
                "intent": "mentor_session",
                "requested_mentor_role": "tutor",
                "purposeCode": "student_guidance",
                "privacyNoticeVersion": "mentor-privacy.v1",
            },
        ),
        (
            "/api/v1/auth/mentor/ceremony/verify",
            "verify",
            {"expected_ceremony_state": "challenge_issued"},
        ),
        (
            "/api/v1/auth/mentor/ceremony/exchange",
            "exchange",
            {
                "intent": "mentor_session",
                "expected_ceremony_state": "proof_verified",
                "acceptPurpose": True,
                "purposeCode": "student_guidance",
                "consentReceiptVersion": "mentor-consent.v1",
                "acceptanceTextVersion": "mentor-acceptance.v1",
            },
        ),
        (
            "/api/v1/auth/mentor/session/rotate",
            "rotate",
            {
                "expected_session_state": "active",
                "purposeCode": "student_guidance",
                "reasonCode": "routine_rotation",
            },
        ),
    ),
)
def test_request_contracts_accept_aliases_only_not_python_field_names(
    ceremony_ctx,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    service_name: str,
    payload: dict[str, object],
) -> None:
    """Undocumented snake_case spellings fail before any authority service."""

    client, _factory = ceremony_ctx
    calls = 0

    def must_not_run(**_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("non-contract field name reached the service")

    monkeypatch.setattr(mentor_ceremony, service_name, must_not_run)
    response = client.post(
        path,
        headers={"Idempotency-Key": "alias-only-contract-key-00000001"},
        json=payload,
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_REQUEST"
    assert calls == 0


def test_production_app_preserves_exact_failure_body_and_vary_contract(
    ceremony_ctx,
) -> None:
    """Global request-id/CORS handling must not rewrite mentor failures."""

    _focused_client, factory = ceremony_ctx
    from app.main import create_app

    app = create_app()

    def provide_session():
        db = factory()
        try:
            yield db
        finally:
            db.rollback()
            db.close()

    app.dependency_overrides[get_session] = provide_session
    with TestClient(app) as client:
        denied = client.get(
            "/api/v1/auth/mentor/session",
            headers={"Origin": "http://127.0.0.1:1130"},
        )
        untrusted = client.get(
            "/api/v1/auth/mentor/session",
            headers={"Origin": "https://cross-tenant.invalid"},
        )
    assert denied.status_code == 401
    assert denied.json() == {
        "detail": {
            "code": "AUTHENTICATION_REQUIRED",
            "message": "Request failed",
            "retryable": False,
        }
    }
    assert denied.headers["vary"] == "Cookie"
    assert denied.headers["cache-control"] == "private, no-store"
    assert denied.headers["access-control-allow-origin"] == "http://127.0.0.1:1130"
    assert denied.headers["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in untrusted.headers
    assert untrusted.headers["vary"] == "Cookie"


def test_locked_ownership_proof_state_is_rechecked_after_candidate_discovery(
    ceremony_ctx, monkeypatch: pytest.MonkeyPatch
):
    """A concurrent proof transition cannot survive the authorizing reread."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    _bind_provider_result(factory, ids)

    original_locked_row = mentor_ceremony._locked_row

    def transition_before_authorization(db, model, identifier):
        row = original_locked_row(db, model, identifier)
        if model is TutorProfileOwnershipProof and row is not None:
            # Model the value observed after a concurrent transaction wins
            # the row lock.  The pre-lock candidate query saw ``current``;
            # authorization must use this refreshed terminal state.
            row.state = "expired"
        return row

    monkeypatch.setattr(
        mentor_ceremony,
        "_locked_row",
        transition_before_authorization,
    )
    denied = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "proof-race-state-key-00000001"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 0


def test_live_session_rejects_future_issued_proof_without_touching_authority(
    ceremony_ctx,
) -> None:
    """Every private request rechecks positive proof currentness."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    with factory() as db:
        session = db.scalar(select(MentorSession).where(MentorSession.state == "active"))
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        assert session is not None and proof is not None
        original_last_seen = session.last_seen_at
        original_generation = session.generation
        proof.issued_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.commit()

    denied = client.get("/api/v1/auth/mentor/session")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    denied_rotation = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "future-proof-rotate-0000000001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "routine_rotation",
        },
    )
    assert denied_rotation.status_code == 403
    assert denied_rotation.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    with factory() as db:
        rows = list(db.scalars(select(MentorSession)))
        assert len(rows) == 1
        assert rows[0].state == "active"
        assert rows[0].generation == original_generation
        assert rows[0].last_seen_at == original_last_seen


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("provider_subject_hash", "b" * 64),
        ("evidence_digest", "c" * 64),
        ("key_version", "v2"),
    ),
)
def test_live_session_rebinds_exact_consumed_provider_provenance(
    ceremony_ctx, field: str, replacement: str
) -> None:
    """Post-verification proof mutation cannot retain mentor authority."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    with factory() as db:
        session = db.scalar(select(MentorSession).where(MentorSession.state == "active"))
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        assert session is not None and proof is not None
        original_last_seen = session.last_seen_at
        setattr(proof, field, replacement)
        db.commit()

    denied = client.get("/api/v1/auth/mentor/session")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    with factory() as db:
        rows = list(db.scalars(select(MentorSession)))
        assert len(rows) == 1
        assert rows[0].state == "active"
        assert rows[0].generation == 1
        assert rows[0].last_seen_at == original_last_seen


@pytest.mark.parametrize(
    ("operation", "reason", "terminal_state"),
    (
        ("revoke", "mentor_requested", "revoked"),
        ("logout", "purpose_complete", "logged_out"),
    ),
)
def test_targeted_end_preserves_unrelated_purpose_authority(
    ceremony_ctx, operation: str, reason: str, terminal_state: str
) -> None:
    """Revoke/logout retire only the presented session and its auxiliaries."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201

    now = datetime.now(timezone.utc)
    with factory() as db:
        presented = db.scalar(
            select(MentorSession).where(MentorSession.state == "active")
        )
        assert presented is not None
        other_session_id = uuid.uuid4()
        other_raw, other_seed_ct, other_seed_version = (
            mentor_ceremony._new_seeded_token("session", other_session_id)
        )
        other_session = MentorSession(
            id=other_session_id,
            ceremony_id=presented.ceremony_id,
            engagement_id=presented.engagement_id,
            actor_user_id=presented.actor_user_id,
            tutor_profile_id=presented.tutor_profile_id,
            ownership_proof_id=presented.ownership_proof_id,
            consent_id=presented.consent_id,
            subject_consent_id=presented.subject_consent_id,
            authority_domain_hash=presented.authority_domain_hash,
            token_hash=_token_hash(other_raw),
            token_seed_ct=other_seed_ct,
            token_seed_key_version=other_seed_version,
            mentor_role=presented.mentor_role,
            purpose_code="legal_education",
            scopes=["profile:display_identity:read"],
            permitted_profile_slices=["display_identity"],
            state="active",
            generation=1,
            issued_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        db.add(other_session)
        db.flush()
        other_ceremony_id = uuid.uuid4()
        other_ceremony_raw, other_ceremony_seed_ct, other_ceremony_seed_version = (
            mentor_ceremony._new_seeded_token("ceremony", other_ceremony_id)
        )
        other_ceremony = MentorCeremony(
            id=other_ceremony_id,
            bootstrap_attempt_id=None,
            token_hash=_token_hash(other_ceremony_raw),
            token_seed_ct=other_ceremony_seed_ct,
            token_seed_key_version=other_ceremony_seed_version,
            challenge_hash=keyed_hash("other-purpose-challenge"),
            intent="authority_deletion_step_up",
            requested_role=presented.mentor_role,
            purpose_code=other_session.purpose_code,
            privacy_notice_version="mentor-authority-deletion.v1",
            state="challenge_issued",
            generation=1,
            actor_user_id=presented.actor_user_id,
            tutor_profile_id=presented.tutor_profile_id,
            ownership_proof_id=presented.ownership_proof_id,
            recovery=True,
            metadata_json={"mentorSessionId": str(other_session.id)},
            expires_at=now + timedelta(minutes=5),
        )
        db.add(other_ceremony)
        db.flush()
        mentor_ceremony._add_provider_transaction(
            db,
            ceremony=other_ceremony,
            requested_role=presented.mentor_role,
            raw_nonce="other-purpose-nonce",
            raw_correlation="other-purpose-correlation",
        )
        # The row id participates in the bearer derivation, so create it
        # explicitly rather than relying on the ORM default.
        other_step_id = uuid.uuid4()
        other_step_raw, other_step_seed_ct, other_step_seed_version = (
            mentor_ceremony._new_seeded_token("step-up", other_step_id)
        )
        other_step = MentorAuthorityStepUp(
            id=other_step_id,
            ceremony_id=other_ceremony.id,
            actor_user_id=presented.actor_user_id,
            mentor_session_id=other_session.id,
            token_hash=_token_hash(other_step_raw),
            token_seed_ct=other_step_seed_ct,
            token_seed_key_version=other_step_seed_version,
            intent="authority_deletion_step_up",
            fingerprint=keyed_hash("other-purpose-step-up"),
            state="active",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        db.add(other_step)
        db.commit()
        presented_id = presented.id
        other_provider_id = db.scalar(
            select(MentorProviderResult.id).where(
                MentorProviderResult.ceremony_id == other_ceremony.id
            )
        )

    ended = client.post(
        f"/api/v1/auth/mentor/session/{operation}",
        headers={"Idempotency-Key": f"targeted-{operation}-key-000000001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": reason,
        },
    )
    assert ended.status_code == 200, ended.text
    with factory() as db:
        assert db.get(MentorSession, presented_id).state == terminal_state
        assert db.get(MentorSession, other_session_id).state == "active"
        assert db.get(MentorCeremony, other_ceremony_id).state == "challenge_issued"
        assert db.get(MentorProviderResult, other_provider_id).state == "pending"
        assert db.get(MentorAuthorityStepUp, other_step_id).state == "active"


@pytest.mark.parametrize(
    "tamper",
    (
        "consent_version",
        "invitation_subject",
        "invitation_owner",
        "source_ceremony_state",
        "source_ceremony_purpose",
    ),
)
def test_live_session_rejects_cross_linked_or_stale_authority_graph(
    ceremony_ctx, tamper: str
) -> None:
    """Every read rechecks exact ceremony/invitation/consent relationships."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    with factory() as db:
        session = db.scalar(select(MentorSession).where(MentorSession.state == "active"))
        assert session is not None
        engagement = db.get(MentorEngagement, session.engagement_id)
        consent = db.get(MentorConsent, session.consent_id)
        invitation = db.get(MentorInvitation, engagement.invitation_id)
        ceremony = db.get(MentorCeremony, session.ceremony_id)
        assert all(row is not None for row in (engagement, consent, invitation, ceremony))
        previous_touch = session.last_seen_at
        if tamper == "consent_version":
            consent.version = "mentor-consent.stale"
        elif tamper == "invitation_subject":
            other_student = User(role="student", status="active")
            db.add(other_student)
            db.flush()
            other_registration = StudentRegistration(
                user_id=other_student.id,
                first_name="Other",
                middle_name=None,
                last_name="Student",
                mobile_hash=keyed_hash("9000000099"),
                mobile_ct=encrypt("9000000099"),
                dob_hash=keyed_hash("2001-01-01"),
                dob_ct=encrypt("2001-01-01"),
                dob_hash_state="verified",
                key_version="v1",
                status="active",
                is_minor=False,
            )
            db.add(other_registration)
            db.flush()
            invitation.subject_registration_id = other_registration.id
        elif tamper == "invitation_owner":
            invitation.initiator_user_id = ids["mentor"]
        elif tamper == "source_ceremony_state":
            ceremony.state = "revoked"
            ceremony.terminal_at = datetime.now(timezone.utc)
        else:
            ceremony.purpose_code = "case_discussion"
        db.commit()
        session_id = session.id

    denied = client.get("/api/v1/auth/mentor/session")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    with factory() as db:
        assert db.get(MentorSession, session_id).last_seen_at == previous_touch


def test_rotation_has_stable_budget_and_finite_generation_ceiling(
    ceremony_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    monkeypatch.setattr(settings, "mentor_rate_max_requests", 2)
    for index in range(2):
        rotated = client.post(
            "/api/v1/auth/mentor/session/rotate",
            headers={"Idempotency-Key": f"stable-rotate-budget-key-{index:08d}"},
            json={
                "expectedSessionState": "active",
                "purposeCode": "student_guidance",
                "reasonCode": "routine_rotation",
            },
        )
        assert rotated.status_code == 200, rotated.text
    blocked = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "stable-rotate-budget-key-99999999"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "routine_rotation",
        },
    )
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["code"] == "RATE_LIMITED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 3
        active = db.scalar(select(MentorSession).where(MentorSession.state == "active"))
        assert active is not None
        active.generation = settings.mentor_session_max_generation
        db.commit()
    monkeypatch.setattr(settings, "mentor_rate_max_requests", 20)
    ceiling = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "max-generation-ceiling-key-000001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "routine_rotation",
        },
    )
    assert ceiling.status_code == 429
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 3


@pytest.fixture()
def ceremony_ctx(engine):
    dbtemplate.reset_to_empty_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def request_session():
        session = factory()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    client = TestClient(app, headers={"Origin": settings.cors_origins[1]})
    try:
        yield client, factory
    finally:
        client.close()


def _seed_graph(factory, *, minor: bool = False):
    now = datetime.now(timezone.utc)
    bootstrap_token = "bootstrap-authority-token-00000000000001"
    with factory() as db:
        student = User(role="student", status="active")
        mentor = User(role="lawyer", status="active")
        db.add_all([student, mentor])
        db.flush()
        registration = StudentRegistration(
            user_id=student.id,
            first_name="Synthetic",
            middle_name=None,
            last_name="Student",
            mobile_hash=keyed_hash("9000000001"),
            mobile_ct=encrypt("9000000001"),
            dob_hash=keyed_hash("2000-01-01"),
            dob_ct=encrypt("2000-01-01"),
            dob_hash_state="verified",
            key_version="v1",
            status="active",
            is_minor=minor,
        )
        db.add(registration)
        db.flush()
        db.add(StudentProfile(registration_id=registration.id, profile_version=1))
        tutor = TutorProfile(
            user_id=mentor.id,
            display_name="Synthetic Mentor",
            status="active",
            verified_identity=True,
            verified_credentials=True,
        )
        db.add(tutor)
        db.flush()
        proof = TutorProfileOwnershipProof(
            user_id=mentor.id,
            tutor_profile_id=tutor.id,
            provider_class="nyayone_reviewed_identity",
            assurance_class="high",
            policy_version="mentor-proof.v1",
            provider_subject_hash=keyed_hash("synthetic-provider-subject"),
            evidence_digest="a" * 64,
            key_version="v1",
            state="current",
            issued_at=now,
            expires_at=now + timedelta(days=1),
        )
        invitation = MentorInvitation(
            subject_registration_id=registration.id,
            initiator_user_id=student.id,
            initiator_session_hash=keyed_hash("seed-owner-session"),
            creation_idempotency_hash=keyed_hash("seed-invitation-request"),
            purpose_policy_version="mentor-purpose-policy.v1",
            mentor_match_hash=keyed_hash("synthetic-provider-subject"),
            authority_domain_hash=keyed_hash("synthetic-authority-domain"),
            mentor_role="tutor",
            purpose_code="student_guidance",
            consent_version="mentor-consent.v1",
            acceptance_text_version="mentor-acceptance.v1",
            disclosure_classes=["display_identity", "preferred_language", "city"],
            state="pending",
            expires_at=now + timedelta(hours=1),
        )
        bootstrap = MentorBootstrapAttempt(
            token_hash=_token_hash(bootstrap_token),
            requested_role="tutor",
            purpose_code="student_guidance",
            state="active",
            expires_at=now + timedelta(minutes=10),
        )
        db.add_all([proof, invitation, bootstrap])
        db.flush()
        subject_consent = MentorSubjectConsent(
            invitation_id=invitation.id,
            subject_registration_id=registration.id,
            granted_by_user_id=student.id,
            granting_session_hash=keyed_hash("seed-owner-session"),
            grant_idempotency_hash=keyed_hash("seed-subject-consent-request"),
            purpose_policy_version="mentor-purpose-policy.v1",
            guardian_consent_id=None,
            purpose_code="student_guidance",
            version="mentor-consent.v1",
            disclosure_classes=["display_identity", "preferred_language", "city"],
            status="granted",
            recorded_at=now,
            expires_at=now + timedelta(hours=1),
        )
        db.add(subject_consent)
        db.commit()
        return {
            "bootstrap": bootstrap_token,
            "mentor": mentor.id,
            "tutor": tutor.id,
            "proof": proof.id,
            "invitation": invitation.id,
        }


def _initiate(
    client: TestClient,
    bootstrap_token: str,
    key: str = "mentor-initiate-idempotency-0001",
    *,
    requested_role: str = "tutor",
):
    client.cookies.set(BOOTSTRAP_COOKIE, bootstrap_token, path="/api/v1/auth/mentor")
    return client.post(
        "/api/v1/auth/mentor/ceremony/initiate",
        headers={"Idempotency-Key": key},
        json={
            "intent": "mentor_session",
            "requestedMentorRole": requested_role,
            "purposeCode": "student_guidance",
            "privacyNoticeVersion": "mentor-privacy.v1",
        },
    )


def _bind_provider_result(factory, ids):
    from app.services import mentor_ceremony

    with factory() as db:
        ceremony = db.scalar(select(MentorCeremony).where(MentorCeremony.state == "challenge_issued"))
        assert ceremony is not None
        transaction = mentor_ceremony.claim_provider_start(
            db,
            ceremony_id=ceremony.id,
        )
        assert set(transaction) == {
            "providerClass",
            "assuranceClass",
            "policyVersion",
            "issuer",
            "audience",
            "algorithm",
            "nonce",
            "correlation",
        }
        assert not (
            {"purpose", "purposeCode", "invitation", "subject", "profile"}
            & set(transaction)
        )
        # The provider assertion is minted only after the server-owned start
        # transaction has been claimed.  Capturing this before the claim would
        # model a callback that predates its challenge and must fail closed.
        now = datetime.now(timezone.utc)
        provider_result = db.scalar(
            select(MentorProviderResult).where(
                MentorProviderResult.ceremony_id == ceremony.id
            )
        )
        assert provider_result is not None
        provider_deadline = (
            provider_result.expires_at.replace(tzinfo=timezone.utc)
            if provider_result.expires_at.tzinfo is None
            else provider_result.expires_at
        )
        expires_at = min(now + timedelta(seconds=30), provider_deadline)
        payload = {
            **transaction,
            "providerSubject": "synthetic-provider-subject",
            "accountBindingClass": "provider_account",
            "userPresenceApproved": True,
            "evidenceDigest": "a" * 64,
            "issuedAt": now.isoformat(),
            "expiresAt": expires_at.isoformat(),
        }
        private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("22" * 32))
        signature = base64.b64encode(
            private_key.sign(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            )
        ).decode("ascii")
        mentor_ceremony.settle_provider_result(
            db,
            ceremony_id=ceremony.id,
            payload=payload,
            signature_b64=signature,
        )


def _claim_provider_payload(factory):
    with factory() as db:
        ceremony = db.scalar(
            select(MentorCeremony).where(
                MentorCeremony.state == "challenge_issued"
            )
        )
        assert ceremony is not None
        transaction = mentor_ceremony.claim_provider_start(
            db,
            ceremony_id=ceremony.id,
        )
        now = datetime.now(timezone.utc)
        provider = db.scalar(
            select(MentorProviderResult).where(
                MentorProviderResult.ceremony_id == ceremony.id
            )
        )
        assert provider is not None
        deadline = (
            provider.expires_at.replace(tzinfo=timezone.utc)
            if provider.expires_at.tzinfo is None
            else provider.expires_at
        )
        return ceremony.id, {
            **transaction,
            "providerSubject": "synthetic-provider-subject",
            "accountBindingClass": "provider_account",
            "userPresenceApproved": True,
            "evidenceDigest": "a" * 64,
            "issuedAt": now.isoformat(),
            "expiresAt": min(now + timedelta(seconds=10), deadline).isoformat(),
        }


def _sign_provider_payload(payload):
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("22" * 32))
    return base64.b64encode(
        private_key.sign(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        )
    ).decode("ascii")


def test_provider_callback_before_server_dispatch_consumes_bounded_failure(
    ceremony_ctx,
):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    with factory() as db:
        ceremony_id = db.scalar(select(MentorCeremony.id))
        assert ceremony_id is not None
        with pytest.raises(mentor_ceremony.MentorCeremonyError) as denied:
            mentor_ceremony.settle_provider_result(
                db,
                ceremony_id=ceremony_id,
                payload={},
                signature_b64="invalid",
            )
        assert denied.value.code == "AUTHORIZATION_DENIED"
    with factory() as db:
        row = db.scalar(select(MentorProviderResult))
        assert row is not None
        assert row.failure_count == 1
        assert row.start_dispatched_at is None


@pytest.mark.parametrize(
    "mutation",
    (
        "signature",
        "providerClass",
        "assuranceClass",
        "policyVersion",
        "issuer",
        "audience",
        "algorithm",
        "nonce",
        "correlation",
        "accountBindingClass",
        "userPresenceApproved",
        "issuedAt",
        "expiresAt",
        "interval",
        "evidenceDigest",
    ),
)
def test_provider_negative_matrix_is_signed_checked_and_durable(
    ceremony_ctx, mutation: str
):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    ceremony_id, payload = _claim_provider_payload(factory)
    candidate = dict(payload)
    if mutation == "signature":
        signature = base64.b64encode(b"not-an-ed25519-signature").decode()
    elif mutation == "issuedAt":
        candidate[mutation] = "not-a-time"
        signature = _sign_provider_payload(candidate)
    elif mutation == "expiresAt":
        candidate[mutation] = "not-a-time"
        signature = _sign_provider_payload(candidate)
    elif mutation == "interval":
        issued = datetime.now(timezone.utc) + timedelta(seconds=1)
        candidate["issuedAt"] = issued.isoformat()
        candidate["expiresAt"] = (issued - timedelta(milliseconds=1)).isoformat()
        signature = _sign_provider_payload(candidate)
    elif mutation == "evidenceDigest":
        candidate[mutation] = "not-a-digest"
        signature = _sign_provider_payload(candidate)
    elif mutation == "userPresenceApproved":
        candidate[mutation] = False
        signature = _sign_provider_payload(candidate)
    else:
        candidate[mutation] = "foreign-policy-value"
        signature = _sign_provider_payload(candidate)
    with factory() as db:
        with pytest.raises(mentor_ceremony.MentorCeremonyError) as denied:
            mentor_ceremony.settle_provider_result(
                db,
                ceremony_id=ceremony_id,
                payload=candidate,
                signature_b64=signature,
            )
        assert denied.value.code == "AUTHORIZATION_DENIED"
    with factory() as db:
        row = db.scalar(select(MentorProviderResult))
        assert row is not None
        assert row.failure_count == 1
        assert row.state == "pending"


def test_provider_circuit_counter_is_capped_and_duplicate_callback_denied(
    ceremony_ctx,
):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    ceremony_id, payload = _claim_provider_payload(factory)
    invalid = {**payload, "issuer": "foreign-policy-value"}
    signature = _sign_provider_payload(invalid)
    for _ in range(settings.mentor_provider_circuit_breaker_failures + 2):
        with factory() as db:
            with pytest.raises(mentor_ceremony.MentorCeremonyError):
                mentor_ceremony.settle_provider_result(
                    db,
                    ceremony_id=ceremony_id,
                    payload=invalid,
                    signature_b64=signature,
                )
    with factory() as db:
        row = db.scalar(select(MentorProviderResult))
        assert row is not None
        assert row.failure_count == settings.mentor_provider_circuit_breaker_failures
        assert row.state == "rejected"
        assert row.consumed_at is not None


def test_replayed_cookie_max_age_never_exceeds_authority_expiry(
    ceremony_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    real_now = mentor_ceremony._now

    def assert_bounded_replay(db, kind, row, cookie, path, same_site):
        expiry = (
            row.expires_at.replace(tzinfo=timezone.utc)
            if row.expires_at.tzinfo is None
            else row.expires_at
        )
        replay = (
            200,
            {
                "status": "synthetic-replay",
                "__nyayoneCookieEffects": [
                    {
                        "action": "set",
                        "key": cookie,
                        "kind": kind,
                        "binding": str(row.id),
                        "generation": getattr(row, "generation", 1),
                        "maxAge": 28_800,
                        "path": path,
                        "sameSite": same_site,
                    }
                ],
            },
        )
        monkeypatch.setattr(
            mentor_ceremony,
            "_now",
            lambda expiry=expiry: expiry - timedelta(seconds=7),
        )
        response = Response()
        mentor_ceremony._replay(db, response, replay)
        max_age = int(
            response.headers["set-cookie"].split("Max-Age=", 1)[1].split(";", 1)[0]
        )
        assert 1 <= max_age <= 7

        monkeypatch.setattr(
            mentor_ceremony,
            "_now",
            lambda expiry=expiry: expiry + timedelta(seconds=1),
        )
        with pytest.raises(mentor_ceremony.MentorCeremonyError) as expired:
            mentor_ceremony._replay(db, Response(), replay)
        assert expired.value.code == {
            "ceremony": "AUTHORITY_TERMINAL",
            "session": "SESSION_EXPIRED",
            "step-up": "STEP_UP_EXPIRED",
        }[kind]
        if kind == "session":
            row.state = "active"
            row.terminal_at = None
            db.commit()

        monkeypatch.setattr(
            mentor_ceremony,
            "_now",
            lambda expiry=expiry: expiry - timedelta(seconds=7),
        )
        original_state = row.state
        original_terminal = getattr(row, "terminal_at", None)
        row.state = {
            "ceremony": "revoked",
            "session": "revoked",
            "step-up": "expired",
        }[kind]
        if kind == "session":
            row.terminal_at = mentor_ceremony._now()
        with pytest.raises(mentor_ceremony.MentorCeremonyError) as terminal:
            mentor_ceremony._replay(db, Response(), replay)
        assert terminal.value.code == (
            "STEP_UP_EXPIRED" if kind == "step-up" else "AUTHORITY_TERMINAL"
        )
        row.state = original_state
        if kind == "session":
            row.terminal_at = original_terminal

    with factory() as db:
        ceremony = db.scalar(select(MentorCeremony))
        assert ceremony is not None
        assert_bounded_replay(
            db,
            "ceremony",
            ceremony,
            CEREMONY_COOKIE,
            MENTOR_COOKIE_PATH,
            "strict",
        )
    monkeypatch.setattr(mentor_ceremony, "_now", real_now)
    assert _verify_and_exchange(client, factory, ids).status_code == 201

    with factory() as db:
        session = db.scalar(
            select(MentorSession).where(MentorSession.state == "active")
        )
        assert session is not None
        # Keep the replay probe inside every consent/invitation currentness
        # bound.  Advancing to the default 8h session expiry would correctly
        # fail the full authoritative graph after the 1h subject grant ends.
        session.expires_at = min(
            (
                session.expires_at.replace(tzinfo=timezone.utc)
                if session.expires_at.tzinfo is None
                else session.expires_at
            ),
            real_now() + timedelta(minutes=30),
        )
        step_up_id = uuid.uuid4()
        step_raw, step_seed_ct, step_seed_key_version = (
            mentor_ceremony._new_seeded_token("step-up", step_up_id)
        )
        step_up = MentorAuthorityStepUp(
            id=step_up_id,
            ceremony_id=session.ceremony_id,
            actor_user_id=session.actor_user_id,
            mentor_session_id=session.id,
            token_hash=_token_hash(step_raw),
            token_seed_ct=step_seed_ct,
            token_seed_key_version=step_seed_key_version,
            intent="authority_deletion_step_up",
            fingerprint=mentor_ceremony._fingerprint(
                "delete-authority",
                {
                    "actor": str(session.actor_user_id),
                    "sessionGeneration": session.generation,
                    "retentionNoticeVersion": (
                        mentor_ceremony.settings.mentor_retention_notice_version
                    ),
                },
            ),
            state="active",
            issued_at=real_now(),
            expires_at=real_now() + timedelta(minutes=5),
        )
        db.add(step_up)
        db.commit()
        assert_bounded_replay(db, "session", session, SESSION_COOKIE, "/", "lax")
        assert_bounded_replay(
            db,
            "step-up",
            step_up,
            "nyayone_mentor_authority_step_up",
            "/api/v1/auth/mentor/authority",
            "strict",
        )


def test_duplicate_verified_provider_result_never_rebinds_authority(ceremony_ctx):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    ceremony_id, payload = _claim_provider_payload(factory)
    signature = _sign_provider_payload(payload)
    with factory() as db:
        mentor_ceremony.settle_provider_result(
            db,
            ceremony_id=ceremony_id,
            payload=payload,
            signature_b64=signature,
        )
    with factory() as db:
        with pytest.raises(mentor_ceremony.MentorCeremonyError) as denied:
            mentor_ceremony.settle_provider_result(
                db,
                ceremony_id=ceremony_id,
                payload=payload,
                signature_b64=signature,
            )
        assert denied.value.code == "AUTHORIZATION_DENIED"
    with factory() as db:
        row = db.scalar(select(MentorProviderResult))
        assert row is not None
        assert row.state == "verified"
        assert row.failure_count == 1


def _verify_and_exchange(client: TestClient, factory, ids):
    _bind_provider_result(factory, ids)
    verified = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "mentor-verify-idempotency-000001"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "acceptance_required"
    exchanged = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "mentor-exchange-idempotency-0001"},
        json={
            "intent": "mentor_session",
            "expectedCeremonyState": "proof_verified",
            "acceptPurpose": True,
            "purposeCode": "student_guidance",
            "consentReceiptVersion": "mentor-consent.v1",
            "acceptanceTextVersion": "mentor-acceptance.v1",
        },
    )
    assert exchanged.status_code == 201, exchanged.text
    return exchanged


def test_server_owned_ceremony_exchange_session_rotation_and_revocation(ceremony_ctx):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    started = _initiate(client, ids["bootstrap"])
    assert started.status_code == 202, started.text
    assert started.json()["ceremonyState"] == "challenge_issued"
    assert client.cookies.get(CEREMONY_COOKIE)

    exchanged = _verify_and_exchange(client, factory, ids)
    projection = exchanged.json()
    assert projection["sessionClass"] == "mentor"
    assert projection["sameActorVerified"] is True
    assert projection["absoluteLifetimeSeconds"] <= 28_800
    assert projection["idleTimeoutSeconds"] <= 1_800
    assert client.cookies.get(SESSION_COOKIE)

    read = client.get("/api/v1/auth/mentor/session")
    assert read.status_code == 200
    assert read.json()["purposeCode"] == "student_guidance"

    rotated = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "mentor-rotate-idempotency-00001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "routine_rotation",
        },
    )
    assert rotated.status_code == 200, rotated.text
    rotated_body = rotated.json()
    replayed = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "mentor-rotate-idempotency-00001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "routine_rotation",
        },
    )
    assert replayed.status_code == 200, replayed.text
    assert replayed.json() == rotated_body
    with factory() as db:
        states = list(db.scalars(select(MentorSession.state).order_by(MentorSession.generation)))
        assert states == ["rotated_out", "active"]

    revoked = client.post(
        "/api/v1/auth/mentor/session/revoke",
        headers={"Idempotency-Key": "mentor-revoke-idempotency-00001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "mentor_requested",
        },
    )
    assert revoked.status_code == 200
    assert revoked.json()["sessionAuthorityPresent"] is False
    assert client.get("/api/v1/auth/mentor/session").status_code == 401


def test_composed_subject_privacy_export_includes_only_safe_mentor_history(
    ceremony_ctx,
) -> None:
    """The server materializer includes ceremony/consent history, never internals."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    now = datetime.now(timezone.utc)
    with factory() as db:
        subject = db.scalar(
            select(StudentRegistration).where(
                StudentRegistration.user_id != ids["mentor"]
            )
        )
        assert subject is not None
        isolated_user = User(role="student", status="active")
        db.add(isolated_user)
        db.flush()
        isolated_registration = StudentRegistration(
            user_id=isolated_user.id,
            first_name="Other",
            last_name="Subject",
            mobile_hash=keyed_hash("9000000099"),
            mobile_ct=encrypt("9000000099"),
            dob_hash=keyed_hash("2001-01-01"),
            dob_ct=encrypt("2001-01-01"),
            dob_hash_state="verified",
            key_version="v1",
            status="active",
            is_minor=False,
        )
        db.add(isolated_registration)
        db.flush()
        db.add(
            MentorInvitation(
                subject_registration_id=isolated_registration.id,
                initiator_user_id=isolated_user.id,
                initiator_session_hash=keyed_hash("isolated-owner-session"),
                creation_idempotency_hash=keyed_hash("isolated-invitation"),
                purpose_policy_version="mentor-purpose-policy.v1",
                mentor_match_hash=keyed_hash("isolated-mentor-match"),
                authority_domain_hash=keyed_hash("isolated-export-domain"),
                mentor_role="lawyer_tutor",
                purpose_code="case_discussion",
                consent_version="mentor-consent.v1",
                acceptance_text_version="mentor-acceptance.v1",
                disclosure_classes=["display_identity"],
                state="pending",
                expires_at=now + timedelta(hours=1),
            )
        )
        db.commit()
        from app.services import profile_service

        exported = profile_service.materialize_student_privacy_export(
            db,
            subject.user_id,
            now=now,
        )
        all_ids = {
            str(row[0])
            for model in (
                MentorInvitation,
                MentorSubjectConsent,
                MentorCeremony,
                MentorProviderResult,
                MentorSession,
            )
            for row in db.execute(select(model.id))
        }

    assert set(exported) == {
        "schema_version",
        "profile_version",
        "profile",
        "mentor_history",
    }
    assert exported["schema_version"] == "student-data-export.v1"
    assert len(exported["mentor_history"]) == 1
    history = exported["mentor_history"][0]
    assert history["purpose_code"] == "student_guidance"
    assert history["invitation_state"] == "accepted"
    assert history["consent"] == {
        "status": "granted",
        "version": "mentor-consent.v1",
        "disclosure_classes": [
            "display_identity",
            "preferred_language",
            "city",
        ],
    }
    assert history["ceremonies"] == [
        {
            "intent": "mentor_session",
            "state": "exchanged",
            "recovery": False,
            "verification_policy_version": "mentor-proof.v1",
            "verified_at": history["ceremonies"][0]["verified_at"],
            "terminal_at": history["ceremonies"][0]["terminal_at"],
        }
    ]
    assert history["ceremonies"][0]["verified_at"] is not None
    assert history["ceremonies"][0]["terminal_at"] is not None
    serialized = json.dumps(exported, sort_keys=True)
    assert all(identifier not in serialized for identifier in all_ids)
    for forbidden in (
        '"user_id"',
        '"registration_id"',
        '"invitation_id"',
        '"ceremony_id"',
        '"session_id"',
        '"token',
        '_hash"',
        '_ct"',
        '"fingerprint',
        '"provider',
        '"nonce',
        '"correlation',
        '"evidence',
    ):
        assert forbidden not in serialized
    assert "case_discussion" not in serialized


def test_verify_rotates_proof_bound_ceremony_cookie_and_old_cookie_cannot_exchange(
    ceremony_ctx,
):
    """A pre-proof capability must not become exchange authority after verify."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    stolen_preproof = client.cookies.get(CEREMONY_COOKIE)
    assert stolen_preproof
    _bind_provider_result(factory, ids)
    verified = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "mentor-proof-cookie-rotation-0001"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert verified.status_code == 200, verified.text
    proof_bound = client.cookies.get(CEREMONY_COOKIE)
    assert proof_bound and proof_bound != stolen_preproof

    attacker = TestClient(client.app, headers={"Origin": settings.cors_origins[1]})
    attacker.cookies.set(CEREMONY_COOKIE, stolen_preproof, path=MENTOR_COOKIE_PATH)
    denied = attacker.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "mentor-stolen-cookie-exchange-0001"},
        json={
            "intent": "mentor_session",
            "expectedCeremonyState": "proof_verified",
            "acceptPurpose": True,
            "purposeCode": "student_guidance",
            "consentReceiptVersion": "mentor-consent.v1",
            "acceptanceTextVersion": "mentor-acceptance.v1",
        },
    )
    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "AUTHENTICATION_REQUIRED"
    attacker.close()


def test_verify_rejects_minor_without_authoritative_guardian_proof(ceremony_ctx):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory, minor=True)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    _bind_provider_result(factory, ids)
    denied = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "mentor-minor-verify-idempotency"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 0


def test_subject_owner_suspension_revokes_mentor_read_authority(ceremony_ctx):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    with factory() as db:
        subject = db.scalar(select(User).where(User.role == "student"))
        assert subject is not None
        subject.status = "suspended"
        db.commit()
    denied = client.get("/api/v1/auth/mentor/session")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"


def test_digest_bound_idempotency_exact_replay_and_conflict(ceremony_ctx):
    _client, factory = ceremony_ctx
    from app.services import mentor_ceremony

    with factory() as db:
        record, replay = mentor_ceremony._begin_idempotency(
            db,
            operation="unit-proof",
            binding="server-derived-actor",
            idempotency_key="opaque-idempotency-key-000001",
            payload={"intent": "mentor_session", "purposeCode": "student_guidance"},
        )
        assert replay is None
        mentor_ceremony._seal_idempotency(record, 200, {"status": "accepted"})
        db.commit()
    with factory() as db:
        _record, replay = mentor_ceremony._begin_idempotency(
            db,
            operation="unit-proof",
            binding="server-derived-actor",
            idempotency_key="opaque-idempotency-key-000001",
            payload={"intent": "mentor_session", "purposeCode": "student_guidance"},
        )
        assert replay == (200, {"status": "accepted"})
        with pytest.raises(mentor_ceremony.MentorCeremonyError) as caught:
            mentor_ceremony._begin_idempotency(
                db,
                operation="unit-proof",
                binding="server-derived-actor",
                idempotency_key="opaque-idempotency-key-000001",
                payload={
                    "intent": "mentor_session",
                    "purposeCode": "student_guidance",
                    "reasonCode": "changed",
                },
            )
        assert caught.value.code == "IDEMPOTENCY_CONFLICT"
        rows = db.scalar(select(func.count()).select_from(MentorIdempotencyRecord))
        assert rows == 1


def test_idempotency_namespace_is_server_bound_not_client_partitioned(ceremony_ctx):
    """Changed client purpose cannot escape the original key's fingerprint."""

    _client, factory = ceremony_ctx
    from app.services import mentor_ceremony

    with factory() as db:
        record, replay = mentor_ceremony._begin_idempotency(
            db,
            operation="unit-scope-proof",
            binding="server-derived-generation",
            idempotency_key="same-key-changed-purpose-00001",
            payload={"intent": "mentor_session", "purposeCode": "student_guidance"},
        )
        assert replay is None
        mentor_ceremony._seal_idempotency(record, 200, {"status": "accepted"})
        db.commit()

    with factory() as db:
        with pytest.raises(mentor_ceremony.MentorCeremonyError) as caught:
            mentor_ceremony._begin_idempotency(
                db,
                operation="unit-scope-proof",
                binding="server-derived-generation",
                idempotency_key="same-key-changed-purpose-00001",
                payload={"intent": "mentor_session", "purposeCode": "case_discussion"},
            )
        assert caught.value.code == "IDEMPOTENCY_CONFLICT"
        assert db.scalar(select(func.count()).select_from(MentorIdempotencyRecord)) == 1


def test_session_expiry_is_server_clock_authoritative(ceremony_ctx):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    _verify_and_exchange(client, factory, ids)
    with factory() as db:
        live = db.scalar(select(MentorSession).where(MentorSession.state == "active"))
        assert live is not None
        live.issued_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        live.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    expired = client.get("/api/v1/auth/mentor/session")
    assert expired.status_code == 410
    assert expired.json()["detail"]["code"] == "SESSION_EXPIRED"
    with factory() as db:
        assert db.scalar(select(MentorSession.state)) == "expired"
        assert db.scalar(select(func.count()).select_from(AuditEvent)) >= 3


def test_safe_session_probe_never_extends_idle_authority(
    ceremony_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    anchor = datetime.now(timezone.utc)
    original_last_seen = anchor - timedelta(
        seconds=settings.mentor_session_idle_ttl_seconds - 2
    )
    with factory() as db:
        live = db.scalar(select(MentorSession).where(MentorSession.state == "active"))
        assert live is not None
        live.last_seen_at = original_last_seen
        live.expires_at = anchor + timedelta(hours=1)
        db.commit()
    monkeypatch.setattr(mentor_ceremony, "_now", lambda: anchor)
    probed = client.get("/api/v1/auth/mentor/session")
    assert probed.status_code == 200
    with factory() as db:
        live = db.scalar(select(MentorSession))
        assert live is not None
        observed = (
            live.last_seen_at.replace(tzinfo=timezone.utc)
            if live.last_seen_at.tzinfo is None
            else live.last_seen_at
        )
        assert observed == original_last_seen

    monkeypatch.setattr(
        mentor_ceremony, "_now", lambda: anchor + timedelta(seconds=3)
    )
    expired = client.get("/api/v1/auth/mentor/session")
    assert expired.status_code == 410
    assert expired.json()["detail"]["code"] == "SESSION_EXPIRED"
    with factory() as db:
        row = db.scalar(select(MentorSession))
        assert row is not None and row.state == "expired"
        boundary = (
            row.terminal_at.replace(tzinfo=timezone.utc)
            if row.terminal_at.tzinfo is None
            else row.terminal_at
        )
        assert boundary == original_last_seen + timedelta(
            seconds=settings.mentor_session_idle_ttl_seconds
        )


def test_session_probe_persists_only_exact_elapsed_owner_cookie_boundary(
    ceremony_ctx,
) -> None:
    """GET keeps mentor authority read-only while durably expiring an owner cookie."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    raw_owner_session = "elapsed-owner-probe-authority-00000001"
    now = datetime.now(timezone.utc)
    expiry = now - timedelta(minutes=5)
    with factory() as db:
        subject = db.scalar(
            select(StudentRegistration).where(
                StudentRegistration.user_id != ids["mentor"]
            )
        )
        mentor_session = db.scalar(
            select(MentorSession).where(MentorSession.state == "active")
        )
        assert subject is not None and mentor_session is not None
        owner_session = AuthSession(
            user_id=subject.user_id,
            token_hash=keyed_hash(raw_owner_session),
            status="active",
            expires_at=expiry,
            last_seen_at=expiry - timedelta(minutes=1),
        )
        db.add(owner_session)
        db.commit()
        owner_session_id = owner_session.id
        mentor_session_id = mentor_session.id
        mentor_before = {
            column.name: getattr(mentor_session, column.name)
            for column in MentorSession.__table__.columns
        }
        rate_before = db.scalar(select(func.count()).select_from(MentorRateBucket))

    client.cookies.set(
        settings.auth_session_cookie_name,
        raw_owner_session,
        domain="testserver.local",
        path="/",
    )
    probed = client.get("/api/v1/auth/mentor/session")
    assert probed.status_code == 200, probed.text

    with factory() as db:
        owner_session = db.get(AuthSession, owner_session_id)
        mentor_session = db.get(MentorSession, mentor_session_id)
        assert owner_session is not None and mentor_session is not None
        assert owner_session.status == "expired"
        assert owner_session.revoked_at is not None
        observed = (
            owner_session.revoked_at.replace(tzinfo=timezone.utc)
            if owner_session.revoked_at.tzinfo is None
            else owner_session.revoked_at
        )
        assert observed == expiry
        mentor_after = {
            column.name: getattr(mentor_session, column.name)
            for column in MentorSession.__table__.columns
        }
        assert mentor_after == mentor_before
        assert (
            db.scalar(select(func.count()).select_from(MentorRateBucket))
            == rate_before
        )

    rotated = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "elapsed-owner-probe-rotate-key-0001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "routine_rotation",
        },
    )
    assert rotated.status_code == 200, rotated.text
    with factory() as db:
        owner_session = db.get(AuthSession, owner_session_id)
        assert owner_session is not None
        assert owner_session.status == "expired"
        assert owner_session.revoked_at is not None
        observed = (
            owner_session.revoked_at.replace(tzinfo=timezone.utc)
            if owner_session.revoked_at.tzinfo is None
            else owner_session.revoked_at
        )
        assert observed == expiry
        assert (
            db.scalar(
                select(func.count(MentorSession.id)).where(
                    MentorSession.state == "active"
                )
            )
            == 1
        )


def test_requested_role_is_non_authorizing_and_mismatch_is_denied(ceremony_ctx):
    """A browser role choice cannot promote a tutor invitation to lawyer authority."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert (
        _initiate(client, ids["bootstrap"], requested_role="lawyer_tutor").status_code
        == 202
    )
    _bind_provider_result(factory, ids)
    denied = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "mentor-role-mismatch-idempotency"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 0


def test_unapproved_proof_provenance_is_denied_without_session_write(ceremony_ctx):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    with factory() as db:
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        assert proof is not None
        proof.assurance_class = "untrusted_bare_positive"
        db.commit()
    _bind_provider_result(factory, ids)
    denied = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "mentor-proof-policy-idempotency"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 0


def test_provider_subject_must_derive_exact_invitation(ceremony_ctx):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    with factory() as db:
        invitation = db.get(MentorInvitation, ids["invitation"])
        assert invitation is not None
        invitation.mentor_match_hash = keyed_hash("different-provider-subject")
        db.commit()
    _bind_provider_result(factory, ids)
    denied = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "mentor-invitation-binding-idempotency"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 0


def test_conflicting_student_session_class_blocks_mentor_initiation(ceremony_ctx):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    raw_student_session = "student-session-authority-00000000000001"
    now = datetime.now(timezone.utc)
    with factory() as db:
        db.add(
            AuthSession(
                user_id=ids["mentor"],
                token_hash=keyed_hash(raw_student_session),
                status="active",
                expires_at=now + timedelta(hours=1),
                last_seen_at=now,
            )
        )
        db.commit()
    client.cookies.set(settings.auth_session_cookie_name, raw_student_session, path="/")
    denied = _initiate(client, ids["bootstrap"])
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "SESSION_CONFLICT"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorCeremony)) == 0


def test_owner_cookie_resolution_discovers_child_before_parent_first_locks() -> None:
    """Cookie lookup cannot lock/dirty AuthSession before its stable User row."""

    source = inspect.getsource(mentor_ceremony._active_student_session)
    discovery = "select(AuthSession.id, AuthSession.user_id)"
    assert discovery in source
    assert source.index(discovery) < source.index(".with_for_update()")
    assert source.index("select(User)") < source.index("select(AuthSession)")
    locked_auth = source[source.index("select(AuthSession)") :]
    assert ".order_by(AuthSession.id)" in locked_auth
    assert ".with_for_update()" in locked_auth


def test_elapsed_owner_cookie_uses_exact_expiry_boundary_before_mentor_mutation(
    ceremony_ctx,
) -> None:
    """An elapsed owner cookie is terminalized at expiry after parent-first locks."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    raw_owner_session = "elapsed-owner-session-authority-00000001"
    now = datetime.now(timezone.utc)
    expiry = now - timedelta(minutes=5)
    with factory() as db:
        subject = db.scalar(
            select(StudentRegistration).where(
                StudentRegistration.user_id != ids["mentor"]
            )
        )
        assert subject is not None
        db.add(
            AuthSession(
                user_id=subject.user_id,
                token_hash=keyed_hash(raw_owner_session),
                status="active",
                expires_at=expiry,
                last_seen_at=expiry - timedelta(minutes=1),
            )
        )
        db.commit()

    client.cookies.set(
        settings.auth_session_cookie_name,
        raw_owner_session,
        domain="testserver.local",
        path="/",
    )
    initiated = _initiate(client, ids["bootstrap"])
    assert initiated.status_code == 202, initiated.text

    with factory() as db:
        owner_session = db.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == keyed_hash(raw_owner_session)
            )
        )
        assert owner_session is not None
        assert owner_session.status == "expired"
        assert owner_session.revoked_at is not None
        observed = (
            owner_session.revoked_at.replace(tzinfo=timezone.utc)
            if owner_session.revoked_at.tzinfo is None
            else owner_session.revoked_at
        )
        assert observed == expiry


def test_student_issuance_materializes_presented_mentor_expiry_after_user_lock(
    ceremony_ctx,
) -> None:
    """An elapsed mentor cookie is terminalized and no longer blocks owner login."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    mentor_token = client.cookies.get(SESSION_COOKIE)
    assert mentor_token
    now = datetime.now(timezone.utc)
    with factory() as db:
        mentor_session = db.scalar(
            select(MentorSession).where(MentorSession.state == "active")
        )
        registration = db.scalar(
            select(StudentRegistration).where(
                StudentRegistration.user_id != ids["mentor"]
            )
        )
        assert mentor_session is not None and registration is not None
        expiry = now - timedelta(seconds=1)
        mentor_session.issued_at = now - timedelta(hours=1)
        mentor_session.expires_at = expiry
        mentor_session.last_seen_at = now - timedelta(seconds=10)
        db.commit()
        from app.services import login_service

        raw_owner, owner_session = login_service.rotate_authenticated_session(
            db,
            registration,
            now,
            presented_mentor_session_token=mentor_token,
        )
        assert raw_owner
        assert owner_session.status == "active"
        db.commit()

    with factory() as db:
        mentor_session = db.scalar(select(MentorSession))
        owner_session = db.scalar(select(AuthSession))
        assert mentor_session is not None and owner_session is not None
        assert mentor_session.state == "expired"
        observed_terminal = (
            mentor_session.terminal_at.replace(tzinfo=timezone.utc)
            if mentor_session.terminal_at.tzinfo is None
            else mentor_session.terminal_at
        )
        assert observed_terminal == expiry
        assert owner_session.status == "active"


def test_student_issuance_rejects_rotated_presented_mentor_lineage(
    ceremony_ctx,
) -> None:
    """A stale predecessor token cannot hide its browser's active successor."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    predecessor_token = client.cookies.get(SESSION_COOKIE)
    assert predecessor_token

    rotated = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "mentor-owner-lineage-rotate-0001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "routine_rotation",
        },
    )
    assert rotated.status_code == 200, rotated.text

    from app.services import login_service

    with factory() as db:
        registration = db.scalar(
            select(StudentRegistration).where(
                StudentRegistration.user_id != ids["mentor"]
            )
        )
        assert registration is not None
        with pytest.raises(login_service.LoginError) as captured:
            login_service.rotate_authenticated_session(
                db,
                registration,
                datetime.now(timezone.utc),
                presented_mentor_session_token=predecessor_token,
            )
        assert captured.value.status_code == 409
        assert captured.value.code == "login_conflict"

    with factory() as db:
        assert (
            db.scalar(
                select(func.count(AuthSession.id)).where(
                    AuthSession.status == "active"
                )
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count(MentorSession.id)).where(
                    MentorSession.state == "active"
                )
            )
            == 1
        )


def test_privacy_request_atomically_retires_subject_mentor_authority(
    ceremony_ctx,
) -> None:
    """A deletion request freezes bearers but does not prematurely sever history."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    with factory() as db:
        registration = db.scalar(
            select(StudentRegistration).where(
                StudentRegistration.user_id != ids["mentor"]
            )
        )
        assert registration is not None
        boundary = mentor_ceremony.lock_subject_mentor_erasure_boundary(
            db, registration.id
        )
        from app.services import registration_service

        locked, _ledger = registration_service.lock_registration_with_idempotency(
            db, registration.id
        )
        assert locked is not None
        retired = (
            mentor_ceremony.retire_subject_mentor_authority_for_privacy_request(
                db,
                boundary,
                now=datetime.now(timezone.utc),
            )
        )
        assert retired == 1
        locked.status = "suspended"
        db.commit()

    denied = client.get("/api/v1/auth/mentor/session")
    assert denied.status_code == 410
    assert denied.json()["detail"]["code"] == "AUTHORITY_TERMINAL"
    with factory() as db:
        session = db.scalar(select(MentorSession))
        invitation = db.get(MentorInvitation, ids["invitation"])
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        assert session is not None and invitation is not None and proof is not None
        assert session.state == "deleted"
        assert session.deleted_at is None
        assert session.actor_user_id == ids["mentor"]
        assert invitation.state == "deleted"
        assert invitation.subject_registration_id is not None
        assert proof.state == "current"
        assert proof.deleted_at is None


def test_lost_response_replays_reissue_only_the_committed_cookie_generation(
    ceremony_ctx,
):
    """Initiate, verify, exchange and rotate retries never mint a new graph."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)

    # Initiate: restore the consumed bootstrap as if the 202 never arrived.
    started = _initiate(client, ids["bootstrap"])
    assert started.status_code == 202
    ceremony_cookie = client.cookies.get(CEREMONY_COOKIE)
    assert ceremony_cookie
    client.cookies.clear()
    replayed_start = _initiate(client, ids["bootstrap"])
    assert replayed_start.status_code == 202
    assert replayed_start.json() == started.json()
    assert client.cookies.get(CEREMONY_COOKIE) == ceremony_cookie

    # Verify: restore the pre-proof cookie. Exact replay must return the one
    # proof-bound generation, not authorize the predecessor directly.
    _bind_provider_result(factory, ids)
    preproof = client.cookies.get(CEREMONY_COOKIE)
    verify_body = {"expectedCeremonyState": "challenge_issued"}
    verified = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "lost-verify-response-key-00001"},
        json=verify_body,
    )
    assert verified.status_code == 200
    proof_bound = client.cookies.get(CEREMONY_COOKIE)
    assert proof_bound and proof_bound != preproof
    client.cookies.clear()
    client.cookies.set(
        CEREMONY_COOKIE,
        preproof,
        domain="testserver.local",
        path=MENTOR_COOKIE_PATH,
    )
    replayed_verify = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "lost-verify-response-key-00001"},
        json=verify_body,
    )
    assert replayed_verify.status_code == 200
    assert replayed_verify.json() == verified.json()
    assert client.cookies.get(CEREMONY_COOKIE) == proof_bound

    exchange_body = {
        "intent": "mentor_session",
        "expectedCeremonyState": "proof_verified",
        "acceptPurpose": True,
        "purposeCode": "student_guidance",
        "consentReceiptVersion": "mentor-consent.v1",
        "acceptanceTextVersion": "mentor-acceptance.v1",
    }
    exchanged = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "lost-exchange-response-key-0001"},
        json=exchange_body,
    )
    assert exchanged.status_code == 201
    first_session = client.cookies.get(SESSION_COOKIE)
    assert first_session
    client.cookies.clear()
    client.cookies.set(
        CEREMONY_COOKIE,
        proof_bound,
        domain="testserver.local",
        path=MENTOR_COOKIE_PATH,
    )
    replayed_exchange = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "lost-exchange-response-key-0001"},
        json=exchange_body,
    )
    assert replayed_exchange.status_code == 201
    assert replayed_exchange.json() == exchanged.json()
    assert client.cookies.get(SESSION_COOKIE) == first_session

    rotate_body = {
        "expectedSessionState": "active",
        "purposeCode": "student_guidance",
        "reasonCode": "routine_rotation",
    }
    predecessor = first_session
    rotated = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "lost-rotate-response-key-00001"},
        json=rotate_body,
    )
    assert rotated.status_code == 200
    successor = client.cookies.get(SESSION_COOKIE)
    assert successor and successor != predecessor
    client.cookies.clear()
    client.cookies.set(
        SESSION_COOKIE, predecessor, domain="testserver.local", path="/"
    )
    replayed_rotate = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "lost-rotate-response-key-00001"},
        json=rotate_body,
    )
    assert replayed_rotate.status_code == 200
    assert replayed_rotate.json() == rotated.json()
    assert client.cookies.get(SESSION_COOKIE) == successor
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorCeremony)) == 1
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 2


def test_lost_exchange_replay_cannot_reissue_after_proof_restriction(
    ceremony_ctx,
) -> None:
    """A stored success is never current authority after restriction wins."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    _bind_provider_result(factory, ids)
    verified = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "restricted-replay-verify-000001"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert verified.status_code == 200
    proof_bound_cookie = client.cookies.get(CEREMONY_COOKIE)
    exchange_body = {
        "intent": "mentor_session",
        "expectedCeremonyState": "proof_verified",
        "acceptPurpose": True,
        "purposeCode": "student_guidance",
        "consentReceiptVersion": "mentor-consent.v1",
        "acceptanceTextVersion": "mentor-acceptance.v1",
    }
    first = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "restricted-replay-exchange-0001"},
        json=exchange_body,
    )
    assert first.status_code == 201
    with factory() as db:
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        assert proof is not None
        proof.state = "revoked"
        proof.revoked_at = datetime.now(timezone.utc)
        db.commit()

    client.cookies.clear()
    client.cookies.set(
        CEREMONY_COOKIE,
        proof_bound_cookie,
        domain="testserver.local",
        path=MENTOR_COOKIE_PATH,
    )
    denied = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "restricted-replay-exchange-0001"},
        json=exchange_body,
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "AUTHORIZATION_DENIED"
    assert SESSION_COOKIE not in denied.headers.get("set-cookie", "")
    assert client.cookies.get(SESSION_COOKIE) is None
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 1


def test_lost_exchange_replay_normalizes_expired_session_to_sealed_exchange_code(
    ceremony_ctx,
) -> None:
    """The exchange operation never emits a session-only 410 code."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    _bind_provider_result(factory, ids)
    verify = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "expired-exchange-verify-key-00001"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert verify.status_code == 200
    proof_bound_cookie = client.cookies.get(CEREMONY_COOKIE)
    body = {
        "intent": "mentor_session",
        "expectedCeremonyState": "proof_verified",
        "acceptPurpose": True,
        "purposeCode": "student_guidance",
        "consentReceiptVersion": "mentor-consent.v1",
        "acceptanceTextVersion": "mentor-acceptance.v1",
    }
    key = "expired-exchange-replay-key-000001"
    assert client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": key},
        json=body,
    ).status_code == 201
    with factory() as db:
        session = db.scalar(select(MentorSession).where(MentorSession.state == "active"))
        assert session is not None
        current = datetime.now(timezone.utc)
        session.issued_at = current - timedelta(hours=2)
        session.last_seen_at = current - timedelta(hours=1)
        session.expires_at = current - timedelta(seconds=1)
        db.commit()

    client.cookies.clear()
    client.cookies.set(
        CEREMONY_COOKIE,
        proof_bound_cookie,
        domain="testserver.local",
        path=MENTOR_COOKIE_PATH,
    )
    replay = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": key},
        json=body,
    )
    assert replay.status_code == 410
    assert replay.json()["detail"]["code"] == "AUTHORITY_TERMINAL"
    assert client.cookies.get(SESSION_COOKIE) is None


def test_lost_exchange_replay_normalizes_expired_step_up_to_sealed_exchange_code(
    ceremony_ctx,
) -> None:
    """The exchange operation never emits a step-up-only 410 code."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    recover = client.post(
        "/api/v1/auth/mentor/ceremony/recover",
        headers={"Idempotency-Key": "expired-step-up-recover-key-0001"},
        json={
            "intent": "authority_deletion_step_up",
            "recoveryMethod": "fresh_external_identity",
            "stepUpNoticeVersion": "mentor-authority-deletion.v1",
        },
    )
    assert recover.status_code == 202
    _bind_provider_result(factory, ids)
    verify = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "expired-step-up-verify-key-00001"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert verify.status_code == 200
    proof_bound_cookie = client.cookies.get(CEREMONY_COOKIE)
    body = {
        "intent": "authority_deletion_step_up",
        "expectedCeremonyState": "proof_verified",
        "acceptAuthorityDeletionStepUp": True,
        "acceptanceTextVersion": "mentor-authority-deletion.v1",
    }
    key = "expired-step-up-exchange-key-0001"
    assert client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": key},
        json=body,
    ).status_code == 200
    with factory() as db:
        step_up = db.scalar(
            select(MentorAuthorityStepUp).where(
                MentorAuthorityStepUp.state == "active"
            )
        )
        assert step_up is not None
        step_up.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    client.cookies.set(
        CEREMONY_COOKIE,
        proof_bound_cookie,
        domain="testserver.local",
        path=MENTOR_COOKIE_PATH,
    )
    client.cookies.delete(
        "nyayone_mentor_authority_step_up",
        domain="testserver.local",
        path="/api/v1/auth/mentor/authority",
    )
    replay = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": key},
        json=body,
    )
    assert replay.status_code == 410
    assert replay.json()["detail"]["code"] == "AUTHORITY_TERMINAL"
    assert client.cookies.get("nyayone_mentor_authority_step_up") is None


def test_deletion_recovery_normalizes_expired_session_to_sealed_recover_code(
    ceremony_ctx,
) -> None:
    """The recovery operation never emits a session-only 410 code."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    with factory() as db:
        session = db.scalar(select(MentorSession).where(MentorSession.state == "active"))
        assert session is not None
        current = datetime.now(timezone.utc)
        session.issued_at = current - timedelta(hours=2)
        session.last_seen_at = current - timedelta(hours=1)
        session.expires_at = current - timedelta(seconds=1)
        db.commit()

    response = client.post(
        "/api/v1/auth/mentor/ceremony/recover",
        headers={"Idempotency-Key": "expired-session-recover-key-00001"},
        json={
            "intent": "authority_deletion_step_up",
            "recoveryMethod": "fresh_external_identity",
            "stepUpNoticeVersion": "mentor-authority-deletion.v1",
        },
    )
    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "AUTHORITY_TERMINAL"


def test_lost_rotate_replay_after_idle_timeout_never_reissues_authority(
    ceremony_ctx,
) -> None:
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    predecessor = client.cookies.get(SESSION_COOKIE)
    body = {
        "expectedSessionState": "active",
        "purposeCode": "student_guidance",
        "reasonCode": "routine_rotation",
    }
    rotated = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "idle-lost-rotate-key-000000001"},
        json=body,
    )
    assert rotated.status_code == 200
    with factory() as db:
        successor = db.scalar(
            select(MentorSession).where(MentorSession.state == "active")
        )
        assert successor is not None
        successor.last_seen_at = datetime.now(timezone.utc) - timedelta(
            seconds=settings.mentor_session_idle_ttl_seconds + 1
        )
        db.commit()
    client.cookies.clear()
    client.cookies.set(
        SESSION_COOKIE, predecessor, domain="testserver.local", path="/"
    )
    replay = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": "idle-lost-rotate-key-000000001"},
        json=body,
    )
    assert replay.status_code == 410
    assert replay.json()["detail"]["code"] == "SESSION_EXPIRED"
    assert not any(
        header.startswith(f"{SESSION_COOKIE}=")
        and "Max-Age=0" not in header
        for header in replay.headers.get_list("set-cookie")
    )
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 2
        assert db.scalar(
            select(func.count())
            .select_from(MentorSession)
            .where(MentorSession.state == "active")
        ) == 0


@pytest.mark.parametrize(
    ("operation", "terminal_state"),
    (("logout", "logged_out"), ("revoke", "revoked")),
)
def test_terminal_end_follows_a_concurrently_committed_rotation_successor(
    ceremony_ctx,
    operation: str,
    terminal_state: str,
) -> None:
    """Restriction wins even when rotation commits immediately before it."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    predecessor = client.cookies.get(SESSION_COOKIE)
    assert predecessor
    rotated = client.post(
        "/api/v1/auth/mentor/session/rotate",
        headers={"Idempotency-Key": f"rotate-before-{operation}-key-00001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "routine_rotation",
        },
    )
    assert rotated.status_code == 200

    # Model the losing request having captured the predecessor cookie before
    # the rotate response advanced browser state.  The shared actor lock makes
    # this the exact post-rotation ordering of the native two-connection race.
    client.cookies.clear()
    client.cookies.set(
        SESSION_COOKIE, predecessor, domain="testserver.local", path="/"
    )
    ended = client.post(
        f"/api/v1/auth/mentor/session/{operation}",
        headers={"Idempotency-Key": f"post-rotate-{operation}-key-000001"},
        json={
            "expectedSessionState": "active",
            "purposeCode": "student_guidance",
            "reasonCode": "mentor_requested",
        },
    )
    assert ended.status_code == 200, ended.text
    assert ended.json()["state"] == terminal_state
    with factory() as db:
        states = list(
            db.scalars(
                select(MentorSession.state).order_by(MentorSession.generation)
            )
        )
        assert states == ["rotated_out", terminal_state]
        assert db.scalar(
            select(func.count())
            .select_from(MentorSession)
            .where(MentorSession.state == "active")
        ) == 0


def test_authority_bearers_are_bound_to_encrypted_fresh_csprng_seeds(
    ceremony_ctx,
):
    """New authority cannot be reconstructed from public row identifiers.

    Exact lost-response replay is permitted only by decrypting the seed sealed
    on the authoritative row and then verifying the derived bearer against the
    persisted lookup digest.  No raw seed or bearer is stored in idempotency.
    """

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    ceremony_bearer = client.cookies.get(CEREMONY_COOKIE)
    assert ceremony_bearer

    with factory() as db:
        ceremony = db.scalar(select(MentorCeremony))
        assert ceremony is not None
        assert ceremony.token_seed_ct
        assert ceremony.token_seed_key_version
        ceremony_seed = decrypt(ceremony.token_seed_ct)
        assert len(ceremony_seed) >= 32
        assert ceremony_bearer == _seeded_token(
            "ceremony", ceremony.id, ceremony.generation, ceremony_seed
        )
        legacy_deterministic_candidate = keyed_hash(
            "mentor-issued-token:v1:ceremony:"
            f"{ceremony.id}:g{ceremony.generation}"
        )
        assert ceremony_bearer != legacy_deterministic_candidate
        assert ceremony.token_hash == _token_hash(ceremony_bearer)
        initiated_record = db.scalar(
            select(MentorIdempotencyRecord).where(
                MentorIdempotencyRecord.operation == "initiate"
            )
        )
        assert initiated_record is not None and initiated_record.outcome_ct
        sealed_outcome = decrypt(initiated_record.outcome_ct)
        assert ceremony_seed not in sealed_outcome
        assert ceremony_bearer not in sealed_outcome

    exchanged = _verify_and_exchange(client, factory, ids)
    assert exchanged.status_code == 201
    session_bearer = client.cookies.get(SESSION_COOKIE)
    assert session_bearer
    with factory() as db:
        session = db.scalar(
            select(MentorSession).where(MentorSession.state == "active")
        )
        assert session is not None
        assert session.token_seed_ct
        assert session.token_seed_key_version
        session_seed = decrypt(session.token_seed_ct)
        assert len(session_seed) >= 32
        assert session_bearer == _seeded_token(
            "session", session.id, session.generation, session_seed
        )
        legacy_deterministic_candidate = keyed_hash(
            "mentor-issued-token:v1:session:"
            f"{session.id}:g{session.generation}"
        )
        assert session_bearer != legacy_deterministic_candidate
        assert session.token_hash == _token_hash(session_bearer)


@pytest.mark.parametrize("mutation", ("missing", "tampered", "digest-mismatch"))
def test_authority_seed_corruption_fails_closed_without_reissuing_cookie(
    ceremony_ctx, mutation: str
) -> None:
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    with factory() as db:
        ceremony = db.scalar(select(MentorCeremony))
        assert ceremony is not None
        if mutation == "missing":
            ceremony.token_seed_ct = None
            ceremony.token_seed_key_version = None
        elif mutation == "tampered":
            ceremony.token_seed_ct = (
                f"{ceremony.token_seed_key_version}:not-valid-ciphertext"
            )
        else:
            ceremony.token_hash = keyed_hash("foreign-token-digest")
        with pytest.raises(mentor_ceremony.MentorCeremonyError) as blocked:
            mentor_ceremony._reconstruct_seeded_token(
                db,
                kind="ceremony",
                binding=ceremony.id,
                generation=ceremony.generation,
            )
        assert blocked.value.code == "AUTHORITY_TERMINAL"


@pytest.mark.parametrize(
    ("operation", "reason"),
    (("revoke", "mentor_requested"), ("logout", "purpose_complete")),
)
def test_terminal_end_exact_retry_reclears_all_browser_authority(
    ceremony_ctx, operation, reason
):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    _verify_and_exchange(client, factory, ids)
    predecessor = client.cookies.get(SESSION_COOKIE)
    body = {
        "expectedSessionState": "active",
        "purposeCode": "student_guidance",
        "reasonCode": reason,
    }
    key = f"lost-{operation}-response-key-000001"
    first = client.post(
        f"/api/v1/auth/mentor/session/{operation}",
        headers={"Idempotency-Key": key},
        json=body,
    )
    assert first.status_code == 200
    client.cookies.clear()
    client.cookies.set(
        SESSION_COOKIE, predecessor, domain="testserver.local", path="/"
    )
    retry = client.post(
        f"/api/v1/auth/mentor/session/{operation}",
        headers={"Idempotency-Key": key},
        json=body,
    )
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert client.cookies.get(SESSION_COOKIE) is None
    assert client.cookies.get(CEREMONY_COOKIE) is None
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 1


def test_failed_authority_derivation_consumes_a_durable_privacy_safe_budget(
    ceremony_ctx,
):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    with factory() as db:
        invitation = db.get(MentorInvitation, ids["invitation"])
        assert invitation is not None
        invitation.mentor_match_hash = keyed_hash("no-current-invitation")
        db.commit()
    _bind_provider_result(factory, ids)

    for suffix in ("one", "two"):
        denied = client.post(
            "/api/v1/auth/mentor/ceremony/verify",
            headers={"Idempotency-Key": f"denial-budget-{suffix}-0000000001"},
            json={"expectedCeremonyState": "challenge_issued"},
        )
        assert denied.status_code == 403
        assert denied.json()["detail"] == {
            "code": "AUTHORIZATION_DENIED",
            "message": "Request failed",
            "retryable": False,
        }

    with factory() as db:
        rows = list(
            db.scalars(
                select(MentorRateBucket).where(
                    MentorRateBucket.operation == "verify"
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].count == 2
        assert len(rows[0].scope_hash) == 64
        assert db.scalar(select(func.count()).select_from(MentorSession)) == 0


def test_audit_links_are_created_and_retention_crypto_erases_identity_evidence(
    ceremony_ctx,
):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201

    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MentorAuditLink)) >= 3
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        provider = db.scalar(select(MentorProviderResult))
        assert proof is not None and provider is not None
        old = datetime.now(timezone.utc) - timedelta(days=40)
        for row in db.scalars(select(MentorBootstrapAttempt)):
            row.state = "expired"
            row.consumed_at = old
            row.updated_at = old
        for row in db.scalars(select(MentorInvitation)):
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
        proof.state = "deleted"
        proof.revoked_at = old
        proof.updated_at = old
        for row in db.scalars(select(MentorCeremony)):
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
        provider.state = "expired"
        provider.consumed_at = old
        provider.updated_at = old
        for row in db.scalars(select(MentorSubjectConsent)):
            row.status = "deleted"
            row.revoked_at = old
            row.updated_at = old
        for row in db.scalars(select(MentorEngagement)):
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
        for row in db.scalars(select(MentorConsent)):
            row.status = "deleted"
            row.revoked_at = old
            row.updated_at = old
        session = db.scalar(
            select(MentorSession).where(MentorSession.state == "active")
        )
        assert session is not None
        session.state = "revoked"
        session.terminal_at = old
        session.updated_at = old
        for row in db.scalars(select(MentorAuditLink)):
            row.expires_at = old
        original_proof_subject = proof.provider_subject_hash
        original_provider_subject = provider.provider_subject_hash
        db.commit()

    from app.services import mentor_ceremony

    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc) + timedelta(days=31),
            batch_size=settings.mentor_retention_batch_size,
        )
        assert counts["severed_graphs"] == 1
        assert counts["proofs"] == 1
        assert counts["provider_results"] == 1
        assert counts["audit_links"] >= 3

    with factory() as db:
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        provider = db.scalar(select(MentorProviderResult))
        assert proof is not None and provider is not None
        assert proof.provider_subject_hash != original_proof_subject
        assert provider.provider_subject_hash != original_provider_subject
        ceremony = db.scalar(select(MentorCeremony))
        session = db.scalar(select(MentorSession))
        assert ceremony is not None and session is not None
        assert ceremony.token_seed_ct is None
        assert ceremony.token_seed_key_version is None
        assert session.token_seed_ct is None
        assert session.token_seed_key_version is None
        assert all(
            row.link_key_ct is None
            and row.actor_link_ct is None
            and row.key_version is None
            and row.erased_at is not None
            and row.correlation_hash
            != keyed_hash(f"mentor-audit-link:v1:{session.authority_domain_hash}")
            for row in db.scalars(select(MentorAuditLink))
        )

    with factory() as db:
        repeated = mentor_ceremony.run_mentor_retention(
            db,
            now=datetime.now(timezone.utc) + timedelta(days=31),
            batch_size=settings.mentor_retention_batch_size,
        )
    assert set(repeated) == {
        "materialized_expirations",
        "severed_graphs",
        "blocked_graphs",
        "bootstraps",
        "invitations",
        "ceremonies",
        "provider_results",
        "subject_consents",
        "engagements",
        "mentor_consents",
        "sessions",
        "step_ups",
        "proofs",
        "idempotency",
        "audit_links",
        "rate_buckets",
    }
    assert sum(repeated.values()) == 0


def test_recovery_exchange_rejects_any_unmarked_active_actor_session(
    ceremony_ctx,
) -> None:
    """A different-purpose generation minted after verify invalidates recovery."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201

    recovery_bootstrap = "recovery-bootstrap-authority-token-000000001"
    now = datetime.now(timezone.utc)
    with factory() as db:
        accepted = db.scalar(
            select(MentorInvitation).where(MentorInvitation.state == "accepted")
        )
        subject = db.get(StudentRegistration, accepted.subject_registration_id)
        owner = db.get(User, accepted.initiator_user_id)
        proof = db.get(TutorProfileOwnershipProof, ids["proof"])
        assert accepted is not None and subject is not None and owner is not None
        assert proof is not None
        pending = MentorInvitation(
            subject_registration_id=subject.id,
            initiator_user_id=owner.id,
            initiator_session_hash=keyed_hash("recovery-owner-session"),
            creation_idempotency_hash=keyed_hash("recovery-invitation-request"),
            purpose_policy_version="mentor-purpose-policy.v1",
            mentor_match_hash=proof.provider_subject_hash,
            authority_domain_hash=keyed_hash("recovery-authority-domain"),
            mentor_role="tutor",
            purpose_code="student_guidance",
            consent_version="mentor-consent.v1",
            acceptance_text_version="mentor-acceptance.v1",
            disclosure_classes=["display_identity"],
            state="pending",
            expires_at=now + timedelta(hours=1),
        )
        bootstrap = MentorBootstrapAttempt(
            token_hash=_token_hash(recovery_bootstrap),
            requested_role="tutor",
            purpose_code="student_guidance",
            state="active",
            expires_at=now + timedelta(minutes=10),
        )
        db.add_all([pending, bootstrap])
        db.flush()
        db.add(
            MentorSubjectConsent(
                invitation_id=pending.id,
                subject_registration_id=subject.id,
                granted_by_user_id=owner.id,
                granting_session_hash=pending.initiator_session_hash,
                grant_idempotency_hash=keyed_hash("recovery-subject-consent"),
                purpose_policy_version="mentor-purpose-policy.v1",
                guardian_consent_id=None,
                purpose_code="student_guidance",
                version="mentor-consent.v1",
                disclosure_classes=["display_identity"],
                status="granted",
                recorded_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        db.commit()

    client.cookies.set(
        BOOTSTRAP_COOKIE,
        recovery_bootstrap,
        domain="testserver.local",
        path=MENTOR_COOKIE_PATH,
    )
    recovered = client.post(
        "/api/v1/auth/mentor/ceremony/recover",
        headers={"Idempotency-Key": "global-recovery-start-key-00000001"},
        json={
            "intent": "mentor_session",
            "requestedMentorRole": "tutor",
            "purposeCode": "student_guidance",
            "recoveryMethod": "fresh_external_identity",
            "privacyNoticeVersion": "mentor-privacy.v1",
        },
    )
    assert recovered.status_code == 202, recovered.text
    _bind_provider_result(factory, ids)
    verified = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "global-recovery-verify-key-0000001"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert verified.status_code == 200, verified.text

    # Model a legitimate different-purpose authority committed after the
    # verification snapshot but before recovery exchange.  It must not be
    # silently left live while the older snapshot is revoked.
    with factory() as db:
        predecessor = db.scalar(
            select(MentorSession).where(MentorSession.state == "active")
        )
        assert predecessor is not None
        late_id = uuid.uuid4()
        _late_raw, late_seed, late_seed_version = mentor_ceremony._new_seeded_token(
            "session", late_id
        )
        late = MentorSession(
            id=late_id,
            ceremony_id=predecessor.ceremony_id,
            engagement_id=predecessor.engagement_id,
            actor_user_id=predecessor.actor_user_id,
            tutor_profile_id=predecessor.tutor_profile_id,
            ownership_proof_id=predecessor.ownership_proof_id,
            consent_id=predecessor.consent_id,
            subject_consent_id=predecessor.subject_consent_id,
            authority_domain_hash=predecessor.authority_domain_hash,
            token_hash=_token_hash(_late_raw),
            token_seed_ct=late_seed,
            token_seed_key_version=late_seed_version,
            mentor_role="lawyer_tutor",
            purpose_code="legal_education",
            scopes=list(mentor_ceremony._PURPOSE_SCOPES["legal_education"]),
            permitted_profile_slices=["display_name"],
            state="active",
            generation=predecessor.generation + 1,
            issued_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=1),
        )
        db.add(late)
        db.commit()
        before = {
            row.id: (row.state, row.terminal_at)
            for row in db.scalars(select(MentorSession))
        }
        engagement_count = db.scalar(select(func.count()).select_from(MentorEngagement))

    denied = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "global-recovery-exchange-key-00001"},
        json={
            "intent": "mentor_session",
            "expectedCeremonyState": "proof_verified",
            "acceptPurpose": True,
            "purposeCode": "student_guidance",
            "consentReceiptVersion": "mentor-consent.v1",
            "acceptanceTextVersion": "mentor-acceptance.v1",
        },
    )
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["code"] == "CONCURRENT_STATE_CHANGED"
    with factory() as db:
        after = {
            row.id: (row.state, row.terminal_at)
            for row in db.scalars(select(MentorSession))
        }
        assert after == before
        assert (
            db.scalar(select(func.count()).select_from(MentorEngagement))
            == engagement_count
        )


def test_deletion_step_up_is_fresh_exactly_replayable_and_retires_full_graph(
    ceremony_ctx,
):
    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    live_cookie = client.cookies.get(SESSION_COOKIE)
    assert live_cookie

    recovery_body = {
        "intent": "authority_deletion_step_up",
        "recoveryMethod": "fresh_external_identity",
        "stepUpNoticeVersion": "mentor-authority-deletion.v1",
    }
    recovered = client.post(
        "/api/v1/auth/mentor/ceremony/recover",
        headers={"Idempotency-Key": "deletion-recovery-key-00000001"},
        json=recovery_body,
    )
    assert recovered.status_code == 202, recovered.text
    deletion_ceremony_cookie = client.cookies.get(CEREMONY_COOKIE)
    assert deletion_ceremony_cookie
    client.cookies.delete(
        CEREMONY_COOKIE,
        domain="testserver.local",
        path=MENTOR_COOKIE_PATH,
    )
    replayed_recover = client.post(
        "/api/v1/auth/mentor/ceremony/recover",
        headers={"Idempotency-Key": "deletion-recovery-key-00000001"},
        json=recovery_body,
    )
    assert replayed_recover.status_code == 202
    assert replayed_recover.json() == recovered.json()
    assert client.cookies.get(CEREMONY_COOKIE) == deletion_ceremony_cookie

    _bind_provider_result(factory, ids)
    verified = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "deletion-verify-key-000000001"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["intent"] == "authority_deletion_step_up"
    proof_bound_cookie = client.cookies.get(CEREMONY_COOKIE)

    exchange_body = {
        "intent": "authority_deletion_step_up",
        "expectedCeremonyState": "proof_verified",
        "acceptAuthorityDeletionStepUp": True,
        "acceptanceTextVersion": "mentor-authority-deletion.v1",
    }
    exchanged = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "deletion-exchange-key-00000001"},
        json=exchange_body,
    )
    assert exchanged.status_code == 200, exchanged.text
    step_up_cookie = client.cookies.get("nyayone_mentor_authority_step_up")
    assert step_up_cookie
    client.cookies.set(
        CEREMONY_COOKIE,
        proof_bound_cookie,
        domain="testserver.local",
        path=MENTOR_COOKIE_PATH,
    )
    client.cookies.delete(
        "nyayone_mentor_authority_step_up",
        domain="testserver.local",
        path="/api/v1/auth/mentor/authority",
    )
    replayed_exchange = client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": "deletion-exchange-key-00000001"},
        json=exchange_body,
    )
    assert replayed_exchange.status_code == 200
    assert replayed_exchange.json() == exchanged.json()
    assert (
        client.cookies.get("nyayone_mentor_authority_step_up") == step_up_cookie
    )

    delete_body = {
        "expectedSessionState": "active",
        "expectedStepUpIntent": "authority_deletion_step_up",
        "confirmation": "delete_mentor_authority",
        "retentionNoticeVersion": "mentor-retention.v1",
    }
    deleted = client.request(
        "DELETE",
        "/api/v1/auth/mentor/authority",
        headers={"Idempotency-Key": "delete-authority-key-000000001"},
        json=delete_body,
    )
    assert deleted.status_code == 202, deleted.text
    client.cookies.clear()
    client.cookies.set(
        SESSION_COOKIE, live_cookie, domain="testserver.local", path="/"
    )
    client.cookies.set(
        "nyayone_mentor_authority_step_up",
        step_up_cookie,
        domain="testserver.local",
        path="/api/v1/auth/mentor/authority",
    )
    replayed_delete = client.request(
        "DELETE",
        "/api/v1/auth/mentor/authority",
        headers={"Idempotency-Key": "delete-authority-key-000000001"},
        json=delete_body,
    )
    assert replayed_delete.status_code == 202
    assert replayed_delete.json() == deleted.json()

    with factory() as db:
        assert set(db.scalars(select(MentorSession.state))) == {"deleted"}
        assert set(db.scalars(select(MentorCeremony.state))) == {"deleted"}
        assert set(db.scalars(select(MentorInvitation.state))) == {"deleted"}
        assert set(db.scalars(select(MentorEngagement.state))) == {"deleted"}
        assert set(db.scalars(select(MentorConsent.status))) == {"deleted"}
        assert set(db.scalars(select(MentorSubjectConsent.status))) == {"deleted"}
        assert set(db.scalars(select(TutorProfileOwnershipProof.state))) == {
            "deleted"
        }
        assert set(db.scalars(select(MentorAuthorityStepUp.state))) <= {
            "consumed",
            "deleted",
        }
        assert set(db.scalars(select(MentorBootstrapAttempt.state))) == {
            "expired"
        }
        assert all(
            row.erased_at is not None
            and row.link_key_ct is None
            and row.actor_link_ct is None
            for row in db.scalars(select(MentorAuditLink))
        )
        assert not list(
            db.scalars(
                select(MentorProviderResult).where(
                    MentorProviderResult.state.in_(("pending", "verified"))
                )
            )
        )


def test_authority_deletion_never_selects_another_actor_by_historical_subject(
    ceremony_ctx,
) -> None:
    """A reused provider subject cannot make actor A delete actor B's graph."""

    client, factory = ceremony_ctx
    ids = _seed_graph(factory)
    assert _initiate(client, ids["bootstrap"]).status_code == 202
    assert _verify_and_exchange(client, factory, ids).status_code == 201
    live_cookie = client.cookies.get(SESSION_COOKIE)
    assert live_cookie
    now = datetime.now(timezone.utc)
    subject_x = keyed_hash("synthetic-provider-subject")
    subject_y = keyed_hash("actor-a-current-provider-subject")
    evidence_y = "d" * 64

    with factory() as db:
        actor_a = db.get(User, ids["mentor"])
        profile_a = db.get(TutorProfile, ids["tutor"])
        current_a = db.get(TutorProfileOwnershipProof, ids["proof"])
        session_a = db.scalar(
            select(MentorSession).where(MentorSession.state == "active")
        )
        provider_a = db.scalar(
            select(MentorProviderResult).where(
                MentorProviderResult.state == "consumed"
            )
        )
        invitation_a = db.scalar(
            select(MentorInvitation).where(MentorInvitation.state == "accepted")
        )
        registration = db.scalar(select(StudentRegistration))
        owner = db.scalar(select(User).where(User.role == "student"))
        assert all(
            row is not None
            for row in (
                actor_a,
                profile_a,
                current_a,
                session_a,
                provider_a,
                invitation_a,
                registration,
                owner,
            )
        )

        # Actor A used X historically but its only current, session-bound
        # authority is Y.  Every live-graph binding is updated together.
        current_a.provider_subject_hash = subject_y
        current_a.evidence_digest = evidence_y
        provider_a.provider_subject_hash = subject_y
        provider_a.evidence_digest = evidence_y
        invitation_a.mentor_match_hash = subject_y
        db.add(
            TutorProfileOwnershipProof(
                user_id=actor_a.id,
                tutor_profile_id=profile_a.id,
                provider_class="nyayone_reviewed_identity",
                assurance_class="high",
                policy_version="mentor-proof.v1",
                provider_subject_hash=subject_x,
                evidence_digest="e" * 64,
                key_version="v1",
                state="revoked",
                issued_at=now - timedelta(days=10),
                expires_at=now + timedelta(days=10),
                revoked_at=now - timedelta(days=1),
            )
        )

        actor_b = User(role="lawyer", status="active")
        db.add(actor_b)
        db.flush()
        profile_b = TutorProfile(
            user_id=actor_b.id,
            display_name="Isolated Mentor B",
            status="active",
            verified_identity=True,
            verified_credentials=True,
        )
        db.add(profile_b)
        db.flush()
        proof_b = TutorProfileOwnershipProof(
            user_id=actor_b.id,
            tutor_profile_id=profile_b.id,
            provider_class="nyayone_reviewed_identity",
            assurance_class="high",
            policy_version="mentor-proof.v1",
            provider_subject_hash=subject_x,
            evidence_digest="f" * 64,
            key_version="v1",
            state="current",
            issued_at=now,
            expires_at=now + timedelta(days=1),
        )
        invitation_b = MentorInvitation(
            subject_registration_id=registration.id,
            initiator_user_id=owner.id,
            initiator_session_hash=keyed_hash("actor-b-owner-session"),
            creation_idempotency_hash=keyed_hash("actor-b-invitation-request"),
            purpose_policy_version="mentor-purpose-policy.v1",
            mentor_match_hash=subject_x,
            authority_domain_hash=keyed_hash("actor-b-authority-domain"),
            mentor_role="tutor",
            purpose_code="student_guidance",
            consent_version="mentor-consent.v1",
            acceptance_text_version="mentor-acceptance.v1",
            disclosure_classes=["display_identity"],
            state="pending",
            expires_at=now + timedelta(hours=1),
        )
        bootstrap_b = MentorBootstrapAttempt(
            token_hash=keyed_hash("actor-b-bootstrap-token"),
            requested_role="tutor",
            purpose_code="student_guidance",
            state="consumed",
            expires_at=now + timedelta(minutes=10),
            consumed_at=now,
        )
        db.add_all([proof_b, invitation_b, bootstrap_b])
        db.flush()
        subject_consent_b = MentorSubjectConsent(
                invitation_id=invitation_b.id,
                subject_registration_id=registration.id,
                granted_by_user_id=owner.id,
                granting_session_hash=keyed_hash("actor-b-owner-session"),
                grant_idempotency_hash=keyed_hash("actor-b-subject-consent"),
                purpose_policy_version="mentor-purpose-policy.v1",
                purpose_code="student_guidance",
                version="mentor-consent.v1",
                disclosure_classes=["display_identity"],
                status="granted",
                recorded_at=now,
                expires_at=now + timedelta(hours=1),
            )
        db.add(subject_consent_b)
        ceremony_b_id = uuid.uuid4()
        _raw_b, seed_b, seed_version_b = mentor_ceremony._new_seeded_token(
            "ceremony", ceremony_b_id
        )
        ceremony_b = MentorCeremony(
            id=ceremony_b_id,
            bootstrap_attempt_id=bootstrap_b.id,
            token_hash=_token_hash(_raw_b),
            token_seed_ct=seed_b,
            token_seed_key_version=seed_version_b,
            challenge_hash=keyed_hash("actor-b-provider-challenge"),
            intent="mentor_session",
            requested_role="tutor",
            purpose_code="student_guidance",
            privacy_notice_version="mentor-privacy.v1",
            state="challenge_issued",
            generation=1,
            expires_at=now + timedelta(minutes=10),
        )
        db.add(ceremony_b)
        db.flush()
        mentor_ceremony._add_provider_transaction(
            db,
            ceremony=ceremony_b,
            requested_role="tutor",
            raw_nonce="actor-b-private-provider-nonce",
            raw_correlation="actor-b-private-provider-correlation",
        )
        db.flush()
        provider_b = db.scalar(
            select(MentorProviderResult).where(
                MentorProviderResult.ceremony_id == ceremony_b.id
            )
        )
        assert provider_b is not None
        provider_b.state = "verified"
        provider_b.start_dispatched_at = now
        provider_b.provider_subject_hash = subject_x
        provider_b.evidence_digest = "f" * 64
        provider_b.key_version = "v1"
        provider_b.issued_at = now

        step_id = uuid.uuid4()
        raw_step, step_seed, step_seed_version = (
            mentor_ceremony._new_seeded_token("step-up", step_id)
        )
        db.add(
            MentorAuthorityStepUp(
                id=step_id,
                ceremony_id=session_a.ceremony_id,
                actor_user_id=session_a.actor_user_id,
                mentor_session_id=session_a.id,
                token_hash=_token_hash(raw_step),
                token_seed_ct=step_seed,
                token_seed_key_version=step_seed_version,
                intent="authority_deletion_step_up",
                fingerprint=mentor_ceremony._fingerprint(
                    "delete-authority",
                    {
                        "actor": str(session_a.actor_user_id),
                        "sessionGeneration": session_a.generation,
                        "retentionNoticeVersion": (
                            settings.mentor_retention_notice_version
                        ),
                    },
                ),
                state="active",
                issued_at=now,
                expires_at=now + timedelta(minutes=5),
            )
        )
        db.commit()
        b_ids = {
            "proof": proof_b.id,
            "invitation": invitation_b.id,
            "bootstrap": bootstrap_b.id,
            "ceremony": ceremony_b.id,
            "provider": provider_b.id,
            "subject_consent": subject_consent_b.id,
        }

    b_models = {
        "proof": TutorProfileOwnershipProof,
        "invitation": MentorInvitation,
        "bootstrap": MentorBootstrapAttempt,
        "ceremony": MentorCeremony,
        "provider": MentorProviderResult,
        "subject_consent": MentorSubjectConsent,
    }
    with factory() as db:
        before_b = {
            name: {
                column.name: getattr(row, column.name)
                for column in model.__table__.columns
            }
            for name, model in b_models.items()
            if (row := db.get(model, b_ids[name])) is not None
        }
    assert set(before_b) == set(b_models)

    client.cookies.clear()
    client.cookies.set(
        SESSION_COOKIE, live_cookie, domain="testserver.local", path="/"
    )
    client.cookies.set(
        "nyayone_mentor_authority_step_up",
        raw_step,
        domain="testserver.local",
        path="/api/v1/auth/mentor/authority",
    )
    deleted = client.request(
        "DELETE",
        "/api/v1/auth/mentor/authority",
        headers={"Idempotency-Key": "cross-tenant-delete-key-00000001"},
        json={
            "expectedSessionState": "active",
            "expectedStepUpIntent": "authority_deletion_step_up",
            "confirmation": "delete_mentor_authority",
            "retentionNoticeVersion": "mentor-retention.v1",
        },
    )
    assert deleted.status_code == 202, deleted.text
    with factory() as db:
        after_b = {
            name: {
                column.name: getattr(row, column.name)
                for column in model.__table__.columns
            }
            for name, model in b_models.items()
            if (row := db.get(model, b_ids[name])) is not None
        }
    assert after_b == before_b

    # B's exact pre-proof cookie still resolves its untouched server graph.
    client.cookies.clear()
    client.cookies.set(
        CEREMONY_COOKIE,
        _raw_b,
        domain="testserver.local",
        path=MENTOR_COOKIE_PATH,
    )
    b_verified = client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": "isolated-actor-b-verify-key-00001"},
        json={"expectedCeremonyState": "challenge_issued"},
    )
    assert b_verified.status_code == 200, b_verified.text
    assert b_verified.json()["ceremonyState"] == "proof_verified"


def test_actor_cannot_have_a_second_tutor_profile_or_current_proof(
    ceremony_ctx,
) -> None:
    """Schema invariants make the reported two-profile deletion case unreachable."""

    _client, factory = ceremony_ctx
    ids = _seed_graph(factory)

    with factory() as db:
        actor = db.get(User, ids["mentor"])
        assert actor is not None
        duplicate_profile = TutorProfile(
            user_id=actor.id,
            display_name="Forbidden second profile",
            status="active",
            verified_identity=True,
            verified_credentials=True,
        )
        db.add(duplicate_profile)
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()

    with factory() as db:
        profile_ids = list(
            db.scalars(
                select(TutorProfile.id).where(TutorProfile.user_id == ids["mentor"])
            )
        )
        assert len(profile_ids) == 1
        assert (
            db.scalar(
                select(func.count(TutorProfileOwnershipProof.id)).where(
                    TutorProfileOwnershipProof.user_id == ids["mentor"],
                    TutorProfileOwnershipProof.tutor_profile_id.in_(profile_ids),
                    TutorProfileOwnershipProof.state == "current",
                    TutorProfileOwnershipProof.deleted_at.is_(None),
                )
            )
            == 1
        )
