"""Wave 3 credential trust: API, security, storage and negative contracts."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import credentials as credential_api
from app.api.v1.router import api_router
from app.core.auth import ActorContext, Role, get_actor_context
from app.core.config import settings
from app.core.crypto import encrypt, keyed_hash
from app.core.exceptions import register_exception_handlers
from app.core.middleware import redact_sensitive_path
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.integrations.storage import FilesystemStorageAdapter
from app.models.credentials import (
    Credential,
    CredentialEvidence,
    CredentialEvidenceScanEvent,
    CredentialIssuer,
    CredentialOutbox,
    CredentialRevocation,
    CredentialShareProjection,
    CredentialVerificationEvent,
    IssuerAuthorisation,
    VerificationAccessLog,
    VerificationToken,
)
from app.models.registration import AuthSession, StudentRegistration, User
from app.services.credential_storage import (
    EvidenceScanner,
    ScanResult,
    get_credential_storage,
)
from app.workers.credential_outbox_relay import relay_credential_outbox

# Test-suite plumbing: create_all-equivalent schema copies + a module-scoped
# route-materialised app (see tests/dbtemplate.py, tests/apptemplate.py).
from tests import apptemplate, dbtemplate


def _claims(user_id: uuid.UUID, *roles: str) -> dict[str, str]:
    return {
        "X-Actor-Claims": json.dumps(
            {"sub": str(user_id), "roles": list(roles)}
        )
    }


def _cookie_request(raw_token: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/credentials",
            "query_string": b"",
            "headers": [
                (
                    b"cookie",
                    (
                        f"{settings.auth_session_cookie_name}={raw_token}"
                    ).encode("ascii"),
                )
            ],
            "scheme": "https",
            "server": ("testserver", 443),
            "client": ("127.0.0.1", 1),
        }
    )


@pytest.fixture(scope="module")
def _mounted():
    """The mounted app + client, built and route-materialised once per module.

    Nothing test-specific lives on it: ``ctx`` re-points every dependency
    override per test. See ``tests/apptemplate.py``.
    """
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

    def prod_session():
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    storage = FilesystemStorageAdapter(tmp_path / "objects")
    app, client = _mounted
    apptemplate.fresh(app, client)
    app.dependency_overrides[get_session] = prod_session
    app.dependency_overrides[get_credential_storage] = lambda: storage

    with SessionLocal() as session:
        student = User(role="student", status="active")
        other = User(role="student", status="active")
        issuer_actor = User(role="lawyer", status="active")
        admin = User(role="admin", status="active")
        issuer = CredentialIssuer(
            display_name="National Law Skills Council",
            issuer_type="institution",
            active=True,
        )
        session.add_all([student, other, issuer_actor, admin, issuer])
        session.flush()
        session.add(
            StudentRegistration(
                user_id=student.id,
                first_name="Aditi",
                middle_name=None,
                last_name="Nair",
                mobile_hash=keyed_hash("9000000007"),
                mobile_ct=encrypt("9000000007"),
                dob_hash=keyed_hash("2001-01-02"),
                dob_ct=encrypt("2001-01-02"),
                key_version="v1",
                status="active",
                is_minor=False,
                idempotency_key="wave3-student-registration",
                idempotency_key_legacy=True,
            )
        )
        session.add(
            IssuerAuthorisation(
                issuer_id=issuer.id,
                user_id=issuer_actor.id,
                can_verify=True,
                can_revoke=True,
                active=True,
                granted_by_user_id=admin.id,
            )
        )
        session.commit()
        ids = {
            "student": student.id,
            "other": other.id,
            "issuer_actor": issuer_actor.id,
            "admin": admin.id,
            "issuer": issuer.id,
        }
    yield client, SessionLocal, storage, ids
    # Per-test engine: dispose() below is the cleanup that matters; the old
    # drop_all re-walked all 53 tables (~10 ms) to demolish a discarded database.
    engine.dispose()


def _create(
    client: TestClient,
    ids: dict[str, uuid.UUID],
    *,
    key: str = "credential-create-0001",
    payload: dict | None = None,
):
    return client.post(
        "/api/v1/credentials",
        headers={
            **_claims(ids["student"], "student"),
            "Idempotency-Key": key,
        },
        json=payload
        or {
            "title": "Advanced Moot Court Certificate",
            "credential_type": "certificate",
            "issue_date": "2026-01-15",
            "expiry_date": "2028-01-15",
            "issuer_id": str(ids["issuer"]),
            "identifier": "CERT-2026-0007",
        },
    )


def _add_pdf(client, ids, credential_id, body=b"%PDF-1.7\nclean evidence"):
    return client.post(
        f"/api/v1/credentials/{credential_id}/evidence",
        headers=_claims(ids["student"], "student"),
        files={"file": ("certificate.pdf", body, "application/pdf")},
    )


def _verify(client, ids, credential_id, version=2, key="issuer-verify-0001"):
    return client.post(
        f"/api/v1/issuer/credentials/{credential_id}/verify",
        headers={
            **_claims(ids["issuer_actor"], "lawyer"),
            "Idempotency-Key": key,
        },
        json={"expected_version": version},
    )


def _projection(client, ids, credential_id, fields=None):
    return client.post(
        f"/api/v1/credentials/{credential_id}/share-projections",
        headers={
            **_claims(ids["student"], "student"),
            "Idempotency-Key": "projection-create-0001",
        },
        json={
            "fields": fields
            or [
                "title",
                "credential_type",
                "status",
                "issue_date",
                "expiry_date",
                "issuer_display_name",
                "verification_timestamp",
                "student_name",
            ]
        },
    )


def _token(client, ids, credential_id, projection_id, key="share-token-0001"):
    return client.post(
        f"/api/v1/credentials/{credential_id}/verification-tokens",
        headers={
            **_claims(ids["student"], "student"),
            "Idempotency-Key": key,
        },
        json={"projection_id": projection_id, "lifetime_days": 90},
    )


def test_complete_wallet_verify_share_revoke_journey(ctx):
    client, SessionLocal, storage, ids = ctx
    created = _create(client, ids)
    assert created.status_code == 201, created.text
    credential_id = created.json()["id"]
    assert created.json()["status"] == "self_declared"
    assert created.json()["identifier"] == "CERT-2026-0007"

    evidence = _add_pdf(client, ids, credential_id)
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["scan_state"] == "clean"
    assert evidence.json()["status"] == "pending_verification"

    verified = _verify(client, ids, credential_id)
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "verified"
    replay = _verify(client, ids, credential_id, key="issuer-verify-0001")
    assert replay.status_code == 200 and replay.json()["idempotent_replay"] is True

    projection = _projection(client, ids, credential_id)
    assert projection.status_code == 200, projection.text
    token = _token(client, ids, credential_id, projection.json()["id"])
    assert token.status_code == 200, token.text
    raw = token.json()["token"]
    assert len(raw) == 43 and raw not in token.json()["verification_url"][:-43]

    public = client.get(f"/api/v1/public/credential-verifications/{raw}")
    assert public.status_code == 200, public.text
    verification = public.json()["verification"]
    assert verification["verification_timestamp"]
    assert {
        key: value
        for key, value in verification.items()
        if key != "verification_timestamp"
    } == {
        "title": "Advanced Moot Court Certificate",
        "credential_type": "certificate",
        "status": "verified",
        "issue_date": "2026-01-15",
        "expiry_date": "2028-01-15",
        "issuer_display_name": "National Law Skills Council",
        "student_name": "Aditi Nair",
    }
    token_id = token.json()["id"]
    revoked = client.delete(
        f"/api/v1/credentials/{credential_id}/verification-tokens/{token_id}",
        headers=_claims(ids["student"], "student"),
    )
    assert revoked.status_code == 200
    unavailable = client.get(f"/api/v1/public/credential-verifications/{raw}")
    assert unavailable.status_code == 410
    assert unavailable.json()["detail"]["code"] == "verification_revoked"

    with SessionLocal() as session:
        stored = session.scalar(
            select(VerificationToken).where(
                VerificationToken.id == uuid.UUID(token_id)
            )
        )
        assert stored and stored.token_hash != raw
        assert not any(
            raw in json.dumps(
                {
                    "before": audit.before_state,
                    "after": audit.after_state,
                }
            )
            for audit in session.scalars(select(AuditEvent)).all()
        )
        evidence_row = session.scalar(
            select(CredentialEvidence).where(
                CredentialEvidence.credential_id == uuid.UUID(credential_id)
            )
        )
        assert evidence_row and storage.exists(evidence_row.object_ref)


def test_revoked_cookie_cannot_create_sharing_authority_from_stale_actor(
    ctx,
):
    client, SessionLocal, _, ids = ctx
    raw_token = "revoked-sharing-session"
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        credential = Credential(
            owner_user_id=ids["student"],
            issuer_id=None,
            title="Privacy certificate",
            credential_type="certificate",
            status="verified",
            issue_date=date(2026, 1, 1),
            expiry_date=None,
            key_version="v1",
            version=1,
            idempotency_key="revoked-session-credential",
        )
        session.add(credential)
        session.flush()
        fixture_projection = CredentialShareProjection(
            credential_id=credential.id,
            owner_user_id=ids["student"],
            fields_json=["title"],
            version=1,
            active=True,
            idempotency_key="revoked-session-fixture-projection",
        )
        session.add_all(
            [
                fixture_projection,
                AuthSession(
                    user_id=ids["student"],
                    token_hash=keyed_hash(raw_token),
                    status="revoked",
                    expires_at=now + timedelta(hours=1),
                    last_seen_at=now,
                    revoked_at=now,
                ),
            ]
        )
        session.commit()
        credential_id = credential.id
        projection_id = fixture_projection.id

    client.cookies.clear()
    client.cookies.set(settings.auth_session_cookie_name, raw_token)
    client.app.dependency_overrides[get_actor_context] = lambda: ActorContext(
        user_id=ids["student"],
        roles=frozenset({Role.STUDENT}),
    )
    try:
        projection_response = client.post(
            f"/api/v1/credentials/{credential_id}/share-projections",
            headers={
                "Origin": settings.cors_origins[0],
                "Idempotency-Key": "revoked-session-projection",
            },
            json={"fields": ["title"]},
        )
        token_response = client.post(
            f"/api/v1/credentials/{credential_id}/verification-tokens",
            headers={
                "Origin": settings.cors_origins[0],
                "Idempotency-Key": "revoked-session-token",
            },
            json={"projection_id": str(projection_id), "lifetime_days": 1},
        )
    finally:
        client.app.dependency_overrides.pop(get_actor_context, None)

    for response in (projection_response, token_response):
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "authentication_required"
    with SessionLocal() as session:
        assert session.query(CredentialShareProjection).count() == 1
        assert session.query(VerificationToken).count() == 0


@pytest.mark.parametrize(
    "operation",
    (
        "create",
        "update",
        "delete",
        "evidence",
        "share",
        "token_create",
        "token_delete",
    ),
)
def test_every_student_credential_effect_revalidates_the_presented_cookie(
    ctx,
    operation,
):
    client, SessionLocal, _, ids = ctx
    raw_token = f"revoked-{operation}-session"
    now = datetime.now(timezone.utc)
    credential_id = None
    projection_id = None
    token_id = None
    with SessionLocal() as session:
        credential = None
        if operation != "create":
            credential = Credential(
                owner_user_id=ids["student"],
                issuer_id=None,
                title="Effect boundary credential",
                credential_type="certificate",
                status=(
                    "verified"
                    if operation in {"share", "token_create", "token_delete"}
                    else "self_declared"
                ),
                issue_date=date(2026, 1, 1),
                expiry_date=None,
                key_version="v1",
                version=1,
                idempotency_key=f"effect-{operation}-credential",
            )
            session.add(credential)
            session.flush()
            credential_id = credential.id
        if operation in {"token_create", "token_delete"}:
            projection = CredentialShareProjection(
                credential_id=credential.id,
                owner_user_id=ids["student"],
                fields_json=["title"],
                version=1,
                active=True,
                idempotency_key=f"effect-{operation}-projection",
            )
            session.add(projection)
            session.flush()
            projection_id = projection.id
            if operation == "token_delete":
                token = VerificationToken(
                    projection_id=projection.id,
                    credential_id=credential.id,
                    owner_user_id=ids["student"],
                    token_hash=keyed_hash("effect-token-delete"),
                    key_version="v1",
                    expires_at=now + timedelta(days=1),
                    idempotency_key="effect-token-delete",
                )
                session.add(token)
                session.flush()
                token_id = token.id
        session.add(
            AuthSession(
                user_id=ids["student"],
                token_hash=keyed_hash(raw_token),
                status="revoked",
                expires_at=now + timedelta(hours=1),
                last_seen_at=now,
                revoked_at=now,
            )
        )
        session.commit()
        before_counts = tuple(
            session.query(model).count()
            for model in (
                Credential,
                CredentialEvidence,
                CredentialShareProjection,
                VerificationToken,
                AuditEvent,
            )
        )
        before_credential = (
            None
            if credential is None
            else (
                credential.status,
                credential.version,
                credential.deleted_at,
                credential.title,
            )
        )

    client.cookies.clear()
    client.cookies.set(settings.auth_session_cookie_name, raw_token)
    client.app.dependency_overrides[get_actor_context] = lambda: ActorContext(
        user_id=ids["student"], roles=frozenset({Role.STUDENT})
    )
    headers = {"Origin": settings.cors_origins[0]}
    try:
        if operation == "create":
            response = client.post(
                "/api/v1/credentials",
                headers={**headers, "Idempotency-Key": "effect-create-request"},
                json={
                    "title": "New credential",
                    "credential_type": "certificate",
                    "issue_date": "2026-01-15",
                    "expiry_date": None,
                    "issuer_id": None,
                    "identifier": None,
                },
            )
        elif operation == "update":
            response = client.patch(
                f"/api/v1/credentials/{credential_id}",
                headers=headers,
                json={
                    "title": "Changed title",
                    "expiry_date": None,
                    "identifier": None,
                    "expected_version": 1,
                },
            )
        elif operation == "delete":
            response = client.delete(
                f"/api/v1/credentials/{credential_id}", headers=headers
            )
        elif operation == "evidence":
            response = client.post(
                f"/api/v1/credentials/{credential_id}/evidence",
                headers=headers,
                files={
                    "file": (
                        "evidence.pdf",
                        b"%PDF-1.7\nrevoked session evidence",
                        "application/pdf",
                    )
                },
            )
        elif operation == "share":
            response = client.post(
                f"/api/v1/credentials/{credential_id}/share-projections",
                headers={**headers, "Idempotency-Key": "effect-share-request"},
                json={"fields": ["title"]},
            )
        elif operation == "token_create":
            response = client.post(
                f"/api/v1/credentials/{credential_id}/verification-tokens",
                headers={
                    **headers,
                    "Idempotency-Key": "effect-token-create-request",
                },
                json={"projection_id": str(projection_id), "lifetime_days": 1},
            )
        else:
            response = client.delete(
                f"/api/v1/credentials/{credential_id}/verification-tokens/{token_id}",
                headers=headers,
            )
    finally:
        client.app.dependency_overrides.pop(get_actor_context, None)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"
    with SessionLocal() as session:
        assert tuple(
            session.query(model).count()
            for model in (
                Credential,
                CredentialEvidence,
                CredentialShareProjection,
                VerificationToken,
                AuditEvent,
            )
        ) == before_counts
        if credential_id is not None:
            credential = session.get(Credential, credential_id)
            assert (
                credential.status,
                credential.version,
                credential.deleted_at,
                credential.title,
            ) == before_credential
        if token_id is not None:
            assert session.get(VerificationToken, token_id).revoked_at is None


@pytest.mark.parametrize("operation", ("verify", "revoke"))
def test_every_issuer_credential_effect_revalidates_the_presented_cookie(
    ctx,
    operation,
):
    client, SessionLocal, _, ids = ctx
    raw_token = f"revoked-issuer-{operation}-session"
    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        credential = Credential(
            owner_user_id=ids["student"],
            issuer_id=ids["issuer"],
            title="Issuer effect boundary",
            credential_type="certificate",
            status="pending_verification" if operation == "verify" else "verified",
            issue_date=date(2026, 1, 1),
            expiry_date=None,
            key_version="v1",
            version=1,
            idempotency_key=f"issuer-{operation}-credential",
        )
        session.add(credential)
        session.flush()
        if operation == "verify":
            session.add(
                CredentialEvidence(
                    credential_id=credential.id,
                    object_ref="evidence/issuer-effect.pdf",
                    sha256_digest="a" * 64,
                    declared_mime="application/pdf",
                    detected_mime="application/pdf",
                    size_bytes=10,
                    scan_state="clean",
                )
            )
        session.add(
            AuthSession(
                user_id=ids["issuer_actor"],
                token_hash=keyed_hash(raw_token),
                status="revoked",
                expires_at=now + timedelta(hours=1),
                last_seen_at=now,
                revoked_at=now,
            )
        )
        session.commit()
        credential_id = credential.id

    client.cookies.clear()
    client.cookies.set(settings.auth_session_cookie_name, raw_token)
    client.app.dependency_overrides[get_actor_context] = lambda: ActorContext(
        user_id=ids["issuer_actor"], roles=frozenset({Role.LAWYER})
    )
    try:
        if operation == "verify":
            response = client.post(
                f"/api/v1/issuer/credentials/{credential_id}/verify",
                headers={
                    "Origin": settings.cors_origins[0],
                    "Idempotency-Key": "revoked-issuer-verify",
                },
                json={"expected_version": 1},
            )
        else:
            response = client.post(
                f"/api/v1/issuer/credentials/{credential_id}/revoke",
                headers={
                    "Origin": settings.cors_origins[0],
                    "Idempotency-Key": "revoked-issuer-revoke",
                },
                json={
                    "reason": "Authoritative issuer revocation reason",
                    "expected_version": 1,
                },
            )
    finally:
        client.app.dependency_overrides.pop(get_actor_context, None)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"
    with SessionLocal() as session:
        stored = session.get(Credential, credential_id)
        assert stored.status == (
            "pending_verification" if operation == "verify" else "verified"
        )
        assert stored.version == 1
        assert session.query(CredentialVerificationEvent).count() == 0
        assert session.query(CredentialRevocation).count() == 0


@pytest.mark.parametrize(
    ("operation", "recognized_constraint"),
    (
        ("credential", True),
        ("credential", False),
        ("share_projection", True),
        ("share_projection", False),
        ("verification_token", True),
        ("verification_token", "token_hash"),
        ("verification_token", False),
    ),
)
def test_integrity_loser_revalidates_cookie_and_never_replays_unrelated_error(
    ctx, monkeypatch, operation, recognized_constraint
):
    """A duplicate loser cannot reuse the session lock lost by rollback."""

    _, SessionLocal, _, ids = ctx
    raw_token = f"integrity-loser-{operation}-session"
    idem = f"integrity-loser-{operation}"
    now = datetime.now(timezone.utc)
    credential_id = None
    projection_id = None
    with SessionLocal() as setup:
        setup.add(
            AuthSession(
                user_id=ids["student"],
                token_hash=keyed_hash(raw_token),
                status="active",
                expires_at=now + timedelta(hours=1),
                last_seen_at=now,
            )
        )
        if operation == "credential":
            setup.add(
                Credential(
                    owner_user_id=ids["student"],
                    issuer_id=None,
                    title="Winning credential",
                    credential_type="certificate",
                    status="self_declared",
                    issue_date=date(2026, 1, 1),
                    expiry_date=None,
                    key_version="v1",
                    version=1,
                    idempotency_key=idem,
                )
            )
        else:
            credential = Credential(
                owner_user_id=ids["student"],
                issuer_id=None,
                title="Winning sharing credential",
                credential_type="certificate",
                status="verified",
                issue_date=date(2026, 1, 1),
                expiry_date=None,
                key_version="v1",
                version=1,
                idempotency_key=f"{idem}-credential",
            )
            setup.add(credential)
            setup.flush()
            credential_id = credential.id
            projection = CredentialShareProjection(
                credential_id=credential.id,
                owner_user_id=ids["student"],
                fields_json=["title"],
                version=1,
                active=True,
                idempotency_key=(
                    idem if operation == "share_projection" else f"{idem}-projection"
                ),
            )
            setup.add(projection)
            setup.flush()
            projection_id = projection.id
            if operation == "verification_token":
                raw = credential_api._raw_token(
                    projection.id, ids["student"], idem
                )
                setup.add(
                    VerificationToken(
                        projection_id=projection.id,
                        credential_id=credential.id,
                        owner_user_id=ids["student"],
                        token_hash=keyed_hash(raw),
                        key_version="v1",
                        expires_at=now + timedelta(days=1),
                        idempotency_key=idem,
                    )
                )
        setup.commit()

    actor = ActorContext(
        user_id=ids["student"], roles=frozenset({Role.STUDENT})
    )
    request = _cookie_request(raw_token)
    session = SessionLocal()
    original_scalar = session.scalar
    initial_lookup_hidden = False
    rollback_interleaved = False
    recovery_lock_order: list[str] = []

    def scalar_with_losing_insert(statement, *args, **kwargs):
        nonlocal initial_lookup_hidden
        sql = str(statement)
        target = {
            "credential": "credentials.idempotency_key",
            "share_projection": "credential_share_projections.idempotency_key",
            "verification_token": "verification_tokens.idempotency_key",
        }[operation]
        if not initial_lookup_hidden and target in sql:
            initial_lookup_hidden = True
            return None
        if (
            rollback_interleaved
            and operation == "credential"
            and target in sql
            and getattr(statement, "_for_update_arg", None) is not None
        ):
            recovery_lock_order.append("credential")
        return original_scalar(statement, *args, **kwargs)

    original_rollback = session.rollback

    def rollback_then_revoke_presented_cookie():
        nonlocal rollback_interleaved
        original_rollback()
        if rollback_interleaved:
            return
        rollback_interleaved = True
        with SessionLocal() as lifecycle:
            auth_session = lifecycle.scalar(
                select(AuthSession)
                .where(AuthSession.token_hash == keyed_hash(raw_token))
                .with_for_update()
            )
            assert auth_session is not None
            auth_session.status = "revoked"
            auth_session.revoked_at = now
            lifecycle.commit()

    monkeypatch.setattr(session, "scalar", scalar_with_losing_insert)
    monkeypatch.setattr(session, "rollback", rollback_then_revoke_presented_cookie)
    original_session_revalidation = (
        credential_api._require_presented_effect_session
    )

    def record_session_revalidation(*args, **kwargs):
        if rollback_interleaved and operation == "credential":
            recovery_lock_order.append("session")
        return original_session_revalidation(*args, **kwargs)

    monkeypatch.setattr(
        credential_api,
        "_require_presented_effect_session",
        record_session_revalidation,
    )
    expected_constraint = {
        "credential": "uq_credentials_owner_idempotency",
        "share_projection": (
            "uq_credential_share_projections_owner_idempotency"
        ),
        "verification_token": "uq_verification_tokens_owner_idempotency",
    }[operation]
    monkeypatch.setattr(
        credential_api,
        "constraint_name",
        lambda _exc: (
            "uq_verification_tokens_token_hash"
            if recognized_constraint == "token_hash"
            else (
                expected_constraint
                if recognized_constraint
                else "uq_unrelated_integrity_failure"
            )
        ),
    )
    try:
        with pytest.raises(
            HTTPException if recognized_constraint else IntegrityError
        ) as caught:
            if operation == "credential":
                credential_api.create_credential(
                    credential_api.CredentialCreate(
                        title="Losing credential",
                        credential_type="certificate",
                        issue_date=date(2026, 1, 1),
                        expiry_date=None,
                        issuer_id=None,
                        identifier=None,
                    ),
                    request,
                    idempotency_key=idem,
                    actor=actor,
                    session=session,
                )
            elif operation == "share_projection":
                credential_api.create_share_projection(
                    credential_id,
                    credential_api.ShareProjectionCreate(fields=["title"]),
                    request,
                    idempotency_key=idem,
                    actor=actor,
                    session=session,
                )
            else:
                credential_api.create_verification_token(
                    credential_id,
                    credential_api.VerificationTokenCreate(
                        projection_id=projection_id, lifetime_days=1
                    ),
                    request,
                    idempotency_key=idem,
                    actor=actor,
                    session=session,
                )
    finally:
        session.close()

    assert initial_lookup_hidden is True
    assert rollback_interleaved is True
    if recognized_constraint:
        assert caught.value.status_code == 401
        assert caught.value.detail["code"] == "authentication_required"
        if operation == "credential":
            assert recovery_lock_order == ["credential", "session"]
    with SessionLocal() as verify:
        assert verify.scalar(
            select(AuthSession.status).where(
                AuthSession.token_hash == keyed_hash(raw_token)
            )
        ) == "revoked"
        expected = {
            "credential": verify.query(Credential).count(),
            "share_projection": verify.query(CredentialShareProjection).count(),
            "verification_token": verify.query(VerificationToken).count(),
        }[operation]
        assert expected == 1


@pytest.mark.parametrize(
    ("payload_update", "expected_field"),
    [
        ({"issue_date": "2030-01-01"}, "body"),
        ({"title": ""}, "body"),
        ({"title": "x" * 161}, "body"),
        ({"title": "<script>alert(1)</script>"}, "body"),
        ({"credential_type": "diploma-from-hogwarts"}, "body"),
        ({"expiry_date": "2025-01-01"}, "body"),
    ],
)
def test_create_negative_boundaries_are_422_and_do_not_echo_input(
    ctx, payload_update, expected_field
):
    client, SessionLocal, _, ids = ctx
    payload = {
        "title": "Certificate",
        "credential_type": "certificate",
        "issue_date": "2026-01-15",
        "expiry_date": "2028-01-15",
        "issuer_id": str(ids["issuer"]),
    }
    payload.update(payload_update)
    response = _create(
        client, ids, key=f"negative-{uuid.uuid4()}", payload=payload
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "validation_error"
    body = response.json()
    assert "input" not in json.dumps(body)
    assert not isinstance(expected_field, type(None))
    with SessionLocal() as session:
        assert session.scalar(select(Credential.id)) is None


def test_auth_ownership_and_unknown_are_non_enumerating(ctx):
    client, _, _, ids = ctx
    created = _create(client, ids)
    credential_id = created.json()["id"]
    assert client.get(f"/api/v1/credentials/{credential_id}").status_code == 401
    other = client.get(
        f"/api/v1/credentials/{credential_id}",
        headers=_claims(ids["other"], "student"),
    )
    missing = client.get(
        f"/api/v1/credentials/{uuid.uuid4()}",
        headers=_claims(ids["other"], "student"),
    )
    assert other.status_code == missing.status_code == 404
    assert other.json()["detail"]["code"] == missing.json()["detail"]["code"]


def test_active_issuer_catalog_is_server_backed_and_student_scoped(ctx):
    client, _, _, ids = ctx
    unauthenticated = client.get("/api/v1/credential-issuers")
    response = client.get(
        "/api/v1/credential-issuers",
        headers=_claims(ids["student"], "student"),
    )
    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(ids["issuer"]),
                "display_name": "National Law Skills Council",
                "issuer_type": "institution",
            }
        ]
    }


@pytest.mark.parametrize(
    ("filename", "body", "mime", "code"),
    [
        ("empty.pdf", b"", "application/pdf", "empty_evidence"),
        ("spoof.png", b"%PDF-1.7\nx", "image/png", "mime_mismatch"),
        ("wrong.jpg", b"%PDF-1.7\nx", "application/pdf", "extension_mismatch"),
        ("../escape.pdf", b"%PDF-1.7\nx", "application/pdf", "unsafe_filename"),
        ("payload.exe", b"MZ-not-allowed", "application/octet-stream", "unsupported_evidence_type"),
        (
            "infected.pdf",
            b"%PDF-1.7\nEICAR-STANDARD-ANTIVIRUS-TEST-FILE",
            "application/pdf",
            "infected_evidence",
        ),
    ],
)
def test_evidence_negative_matrix_has_no_partial_rows(
    ctx, filename, body, mime, code
):
    client, SessionLocal, storage, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    response = client.post(
        f"/api/v1/credentials/{credential_id}/evidence",
        headers=_claims(ids["student"], "student"),
        files={"file": (filename, body, mime)},
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == code
    with SessionLocal() as session:
        assert session.scalar(select(CredentialEvidence.id)) is None
    assert list(storage.root.rglob("*")) == []


def test_scanner_failure_is_quarantined_retryable_and_not_pending(ctx):
    client, SessionLocal, storage, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    response = _add_pdf(
        client,
        ids,
        credential_id,
        b"%PDF-1.7\nSCAN_PROVIDER_FAILURE",
    )
    assert response.status_code == 200
    assert response.json()["scan_state"] == "retryable_failure"
    assert response.json()["retryable"] is True
    with SessionLocal() as session:
        credential = session.get(Credential, uuid.UUID(credential_id))
        assert credential.status == "self_declared"
        outbox = session.scalar(
            select(CredentialOutbox).where(
                CredentialOutbox.credential_id == credential.id,
                CredentialOutbox.kind == "scan_evidence",
            )
        )
        assert outbox and outbox.kind == "scan_evidence"
        assert outbox.payload_json is None
        evidence = session.scalar(select(CredentialEvidence))
        assert evidence and storage.exists(evidence.object_ref)


class _CleanRetryScanner(EvidenceScanner):
    def scan(self, data: bytes, *, detected_mime: str) -> ScanResult:
        return ScanResult("clean", "clean_after_retry", "test-retry-scanner")


def test_retry_outbox_clean_scan_updates_evidence_and_credential(ctx):
    client, SessionLocal, storage, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    response = _add_pdf(
        client,
        ids,
        credential_id,
        b"%PDF-1.7\nSCAN_PROVIDER_FAILURE",
    )
    assert response.json()["scan_state"] == "retryable_failure"

    processed = relay_credential_outbox(
        storage=storage,
        scanner=_CleanRetryScanner(),
        session_factory=SessionLocal,
    )
    assert processed == 1
    with SessionLocal() as session:
        evidence = session.scalar(select(CredentialEvidence))
        outbox = session.scalar(
            select(CredentialOutbox).where(
                CredentialOutbox.kind == "scan_evidence"
            )
        )
        credential = session.get(Credential, uuid.UUID(credential_id))
        events = session.scalars(
            select(CredentialEvidenceScanEvent).where(
                CredentialEvidenceScanEvent.evidence_id == evidence.id
            )
        ).all()
        assert evidence.scan_state == "clean"
        assert credential.status == "pending_verification"
        assert outbox.status == "complete" and outbox.delivered_at is not None
        assert [event.scan_state for event in events] == [
            "retryable_failure",
            "clean",
        ]


def test_duplicate_evidence_and_file_limit(ctx, monkeypatch):
    client, SessionLocal, _, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    assert _add_pdf(client, ids, credential_id).status_code == 200
    duplicate = _add_pdf(client, ids, credential_id)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "duplicate_evidence"

    from app.core.config import settings

    monkeypatch.setattr(settings, "credential_max_evidence_files", 1)
    second = _add_pdf(client, ids, credential_id, b"%PDF-1.7\nsecond")
    assert second.status_code == 422
    assert second.json()["detail"]["code"] == "evidence_file_limit"
    with SessionLocal() as session:
        assert len(session.scalars(select(CredentialEvidence)).all()) == 1


def test_oversize_rejected(ctx, monkeypatch):
    client, SessionLocal, _, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    from app.core.config import settings

    monkeypatch.setattr(settings, "credential_max_file_bytes", 12)
    response = _add_pdf(client, ids, credential_id, b"%PDF-1.7\n123456789")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "evidence_too_large"
    with SessionLocal() as session:
        assert session.scalar(select(CredentialEvidence.id)) is None


@pytest.mark.parametrize(
    ("size_bytes", "expected_status", "expected_code"),
    [
        (11, 200, None),
        (12, 200, None),
        (13, 422, "evidence_too_large"),
    ],
)
def test_evidence_size_one_below_at_and_one_above_limit(
    ctx, monkeypatch, size_bytes, expected_status, expected_code
):
    client, SessionLocal, _, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    from app.core.config import settings

    monkeypatch.setattr(settings, "credential_max_file_bytes", 12)
    body = b"%PDF-" + (b"x" * (size_bytes - 5))
    response = _add_pdf(client, ids, credential_id, body)
    assert response.status_code == expected_status, response.text
    if expected_code:
        assert response.json()["detail"]["code"] == expected_code
    with SessionLocal() as session:
        assert len(session.scalars(select(CredentialEvidence)).all()) == (
            1 if expected_status == 200 else 0
        )


def test_projection_rejects_private_and_duplicate_fields(ctx):
    client, _, _, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    private = _projection(client, ids, credential_id, ["title", "identifier"])
    duplicate = _projection(client, ids, credential_id, ["title", "title"])
    assert private.status_code == duplicate.status_code == 422
    assert "input" not in json.dumps(private.json())


def test_issuer_requires_active_grant_and_clean_evidence(ctx):
    client, SessionLocal, _, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    no_evidence = _verify(client, ids, credential_id, version=1)
    assert no_evidence.status_code == 409
    assert no_evidence.json()["detail"]["code"] == "credential_not_pending"
    _add_pdf(client, ids, credential_id)
    unauthorised = client.post(
        f"/api/v1/issuer/credentials/{credential_id}/verify",
        headers={
            **_claims(ids["other"], "student"),
            "Idempotency-Key": "unauthorised-verify",
        },
        json={"expected_version": 2},
    )
    assert unauthorised.status_code == 403
    with SessionLocal() as session:
        grant = session.scalar(select(IssuerAuthorisation))
        grant.active = False
        session.commit()
    inactive = _verify(
        client, ids, credential_id, version=2, key="inactive-grant-verify"
    )
    assert inactive.status_code == 403


def test_tampered_unknown_malformed_expired_are_minimal(ctx):
    client, SessionLocal, _, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    _add_pdf(client, ids, credential_id)
    assert _verify(client, ids, credential_id).status_code == 200
    projection_id = _projection(client, ids, credential_id).json()["id"]
    token = _token(client, ids, credential_id, projection_id).json()

    malformed = client.get("/api/v1/public/credential-verifications/not-valid")
    unknown = client.get(
        "/api/v1/public/credential-verifications/"
        + ("A" * 43)
    )
    # A REAL single-character mutation of the issued token. Appending a fixed "A"
    # was a no-op whenever the token already ended in "A", and it ends in "A"
    # about 1 token in 16: the token is `urlsafe_b64encode(32-byte digest)` with
    # padding stripped, so its final character carries only 4 significant bits and
    # comes from a 16-character alphabet. When that happened the "tampered" token
    # WAS the valid token and this assertion saw 200 — the intermittent failure of
    # this exact test recorded in docs/product/wave2/FULL_SUITE_FLAKE_DIAGNOSIS.md.
    # Lookup is `keyed_hash(token)` over the raw ASCII string, so changing any one
    # character is a genuine tamper; the case is unchanged, it is now guaranteed to
    # actually happen.
    tampered_token = token["token"][:-1] + ("B" if token["token"][-1] == "A" else "A")
    assert tampered_token != token["token"]  # a no-op mutation would prove nothing
    tampered = client.get(
        f"/api/v1/public/credential-verifications/{tampered_token}"
    )
    for response in (malformed, unknown, tampered):
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "verification_not_found"
        assert "credential" not in json.dumps(response.json()).lower()

    with SessionLocal() as session:
        stored = session.scalar(select(VerificationToken))
        stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    expired = client.get(
        f"/api/v1/public/credential-verifications/{token['token']}"
    )
    assert expired.status_code == 410
    assert expired.json()["detail"]["code"] == "verification_expired"


def test_issuer_revocation_is_encrypted_and_public_tokens_revoked(ctx):
    client, SessionLocal, _, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    _add_pdf(client, ids, credential_id)
    verified = _verify(client, ids, credential_id).json()
    projection_id = _projection(client, ids, credential_id).json()["id"]
    token = _token(client, ids, credential_id, projection_id).json()["token"]
    reason = "Issuer record was invalidated after an internal compliance review."
    revoked = client.post(
        f"/api/v1/issuer/credentials/{credential_id}/revoke",
        headers={
            **_claims(ids["issuer_actor"], "lawyer"),
            "Idempotency-Key": "issuer-revoke-0001",
        },
        json={"reason": reason, "expected_version": verified["version"]},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"
    public = client.get(f"/api/v1/public/credential-verifications/{token}")
    assert public.status_code == 410
    with SessionLocal() as session:
        record = session.scalar(select(CredentialRevocation))
        assert record and record.reason_ct != reason and reason not in record.reason_ct
        assert record.reason_hash == keyed_hash(reason, lower=True)
        assert not any(
            reason in json.dumps(
                {"before": row.before_state, "after": row.after_state}
            )
            for row in session.scalars(select(AuditEvent))
        )


@pytest.mark.parametrize(
    ("reason_length", "expected_status"),
    [(9, 422), (10, 200), (500, 200), (501, 422)],
)
def test_revocation_reason_boundaries(ctx, reason_length, expected_status):
    client, _, _, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    _add_pdf(client, ids, credential_id)
    verified = _verify(client, ids, credential_id).json()
    response = client.post(
        f"/api/v1/issuer/credentials/{credential_id}/revoke",
        headers={
            **_claims(ids["issuer_actor"], "lawyer"),
            "Idempotency-Key": f"reason-boundary-{reason_length}",
        },
        json={
            "reason": "R" * reason_length,
            "expected_version": verified["version"],
        },
    )
    assert response.status_code == expected_status, response.text
    if expected_status == 422:
        assert response.json()["detail"]["code"] == "validation_error"
        assert "input" not in json.dumps(response.json())


def test_already_expired_credential_is_truthful_and_not_shareable(ctx):
    client, _, _, ids = ctx
    created = _create(
        client,
        ids,
        payload={
            "title": "Expired certificate",
            "credential_type": "certificate",
            "issue_date": "2020-01-15",
            "expiry_date": "2021-01-15",
            "issuer_id": str(ids["issuer"]),
        },
    )
    credential_id = created.json()["id"]
    _add_pdf(client, ids, credential_id)
    verified = _verify(client, ids, credential_id)
    assert verified.status_code == 200
    assert verified.json()["status"] == "expired"
    projection = _projection(client, ids, credential_id)
    token = _token(client, ids, credential_id, projection.json()["id"])
    assert token.status_code == 409
    assert token.json()["detail"]["code"] == "verified_credential_required"


def test_evidence_commit_failure_rolls_back_database_audit_and_object(ctx):
    _, SessionLocal, storage, ids = ctx
    normal_client = TestClient(
        _commit_failure_app(SessionLocal, storage, fail_commits=False),
        raise_server_exceptions=False,
    )
    credential_id = _create(normal_client, ids).json()["id"]
    normal_client.close()

    failing_client = TestClient(
        _commit_failure_app(SessionLocal, storage, fail_commits=True),
        raise_server_exceptions=False,
    )
    response = _add_pdf(failing_client, ids, credential_id)
    failing_client.close()
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "internal_error"
    assert "clean evidence" not in response.text
    with SessionLocal() as session:
        assert session.scalar(select(CredentialEvidence.id)) is None
        evidence_audits = session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "credential.evidence_added"
            )
        ).all()
        assert evidence_audits == []
    assert [path for path in storage.root.rglob("*") if path.is_file()] == []


def _commit_failure_app(SessionLocal, storage, *, fail_commits: bool) -> FastAPI:
    bind = SessionLocal.kw["bind"]

    class CommitControlledSession(Session):
        def commit(self) -> None:
            if fail_commits:
                raise RuntimeError("injected_commit_failure")
            super().commit()

    factory = sessionmaker(
        bind=bind, expire_on_commit=False, class_=CommitControlledSession
    )

    def dependency():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_session] = dependency
    app.dependency_overrides[get_credential_storage] = lambda: storage
    return app


def test_delete_soft_deletes_revokes_and_schedules_object_deletion(ctx):
    client, SessionLocal, _, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    _add_pdf(client, ids, credential_id)
    response = client.delete(
        f"/api/v1/credentials/{credential_id}",
        headers=_claims(ids["student"], "student"),
    )
    assert response.status_code == 200
    with SessionLocal() as session:
        credential = session.get(Credential, uuid.UUID(credential_id))
        evidence = session.scalar(select(CredentialEvidence))
        outbox = session.scalar(
            select(CredentialOutbox).where(
                CredentialOutbox.kind == "delete_evidence"
            )
        )
        assert credential.deleted_at and credential.status == "revoked"
        assert credential.identifier_hash is None
        assert credential.identifier_ct is None
        assert credential.key_version is None
        assert evidence.deleted_at and evidence.scan_state == "deleted"
        assert outbox and outbox.payload_json is None


def test_delete_outbox_erases_object_and_tombstones_reference(ctx):
    client, SessionLocal, storage, ids = ctx
    credential_id = _create(client, ids).json()["id"]
    _add_pdf(client, ids, credential_id)
    with SessionLocal() as session:
        evidence = session.scalar(select(CredentialEvidence))
        object_ref = evidence.object_ref
    assert storage.exists(object_ref)
    assert (
        client.delete(
            f"/api/v1/credentials/{credential_id}",
            headers=_claims(ids["student"], "student"),
        ).status_code
        == 200
    )

    processed = relay_credential_outbox(
        storage=storage,
        scanner=_CleanRetryScanner(),
        session_factory=SessionLocal,
    )
    assert processed == 1
    assert not storage.exists(object_ref)
    with SessionLocal() as session:
        evidence = session.scalar(select(CredentialEvidence))
        outbox = session.scalar(
            select(CredentialOutbox).where(
                CredentialOutbox.kind == "delete_evidence"
            )
        )
        assert evidence.object_ref == f"deleted:{evidence.id}"
        assert outbox.status == "complete"


def test_request_log_redacts_public_bearer_token():
    raw = "A" * 43
    assert (
        redact_sensitive_path(f"/api/v1/public/credential-verifications/{raw}")
        == "/api/v1/public/credential-verifications/:token"
    )
    assert redact_sensitive_path(f"/verify/{raw}") == "/verify/:token"
    assert redact_sensitive_path("/api/v1/credentials") == "/api/v1/credentials"


def test_public_rate_limit_uses_hash_only_bucket(ctx, monkeypatch):
    client, SessionLocal, _, _ = ctx
    from app.core.config import settings

    monkeypatch.setattr(settings, "credential_public_rate_per_minute", 2)
    path = "/api/v1/public/credential-verifications/" + ("A" * 43)
    assert client.get(path).status_code == 404
    assert client.get(path).status_code == 404
    third = client.get(path)
    assert third.status_code == 429
    with SessionLocal() as session:
        rows = session.scalars(select(VerificationAccessLog)).all()
        assert len(rows) == 3
        assert all(len(row.bucket_hash) == 64 for row in rows)
        assert all("127.0.0.1" not in row.bucket_hash for row in rows)
