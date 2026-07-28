"""PostgreSQL 16 target-runtime gate for Wave 3 credential trust.

This module is deliberately opt-in. SQLite remains the fast unit-test oracle;
CI and Independent QA set ``WAVE3_POSTGRES_TEST=1`` and ``DATABASE_URL`` to
exercise row locks, unique conflicts, physical indexes, constraints and
privacy against the approved target database.
"""
from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401
from app.api.v1.router import api_router
from app.core.exceptions import register_exception_handlers
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.integrations.storage import FilesystemStorageAdapter
from app.models.credentials import (
    Credential,
    CredentialEvidence,
    CredentialIssuer,
    CredentialOutbox,
    CredentialReminderJob,
    CredentialRevocation,
    CredentialShareProjection,
    CredentialStatusHistory,
    CredentialVerificationEvent,
    IssuerAuthorisation,
    VerificationAccessLog,
    VerificationToken,
)
from app.services.credential_storage import get_credential_storage
from scripts.seed_wave3_e2e import (
    ISSUER_ACTOR_ID,
    ISSUER_ID,
    STUDENT_ID,
    provision,
)

pytestmark = pytest.mark.skipif(
    os.getenv("WAVE3_POSTGRES_TEST") != "1",
    reason="requires explicit isolated PostgreSQL 16 runtime",
)

WAVE3_TABLES = {
    "credential_issuers",
    "credentials",
    "credential_evidence",
    "credential_status_history",
    "credential_share_projections",
    "credential_outbox",
    "credential_reminder_jobs",
    "credential_evidence_scan_events",
    "issuer_authorisations",
    "credential_verification_events",
    "verification_tokens",
    "credential_revocations",
    "verification_access_logs",
}
WAVE3_DELETE_ORDER = (
    "verification_access_logs",
    "credential_revocations",
    "verification_tokens",
    "credential_verification_events",
    "issuer_authorisations",
    "credential_evidence_scan_events",
    "credential_outbox",
    "credential_reminder_jobs",
    "credential_share_projections",
    "credential_status_history",
    "credential_evidence",
    "credentials",
    "credential_issuers",
)


def _claims(user_id: uuid.UUID, *roles: str) -> dict[str, str]:
    return {
        "X-Actor-Claims": json.dumps(
            {"sub": str(user_id), "roles": list(roles)}
        )
    }


def _clear_wave3(engine) -> None:
    with engine.begin() as connection:
        for table in WAVE3_DELETE_ORDER:
            connection.execute(text(f"DELETE FROM {table}"))


@pytest.fixture(scope="module")
def pg_ctx(tmp_path_factory):
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url, pool_size=12, max_overflow=12, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        pytest.fail("Wave 3 target-runtime gate must use PostgreSQL")
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    # The gate owns an isolated database. Clear only Wave 3 state so reruns are
    # deterministic while earlier-wave rows remain available for seed reuse.
    _clear_wave3(engine)
    with factory() as session:
        provision(session)
        session.commit()

    def prod_session():
        session = factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    storage = FilesystemStorageAdapter(
        tmp_path_factory.mktemp("wave3-pg-evidence")
    )
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_session] = prod_session
    app.dependency_overrides[get_credential_storage] = lambda: storage
    client = TestClient(app, raise_server_exceptions=False)
    yield client, factory, engine, storage
    client.close()
    _clear_wave3(engine)
    engine.dispose()


def test_postgres_16_pgvector_schema_constraints_and_fk_indexes(pg_ctx):
    _, _, engine, _ = pg_ctx
    inspector = inspect(engine)
    assert int(engine.connect().scalar(text("SHOW server_version_num"))) >= 160000
    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        )
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "0007_wave3_credentials"
        )
    tables = set(inspector.get_table_names())
    assert WAVE3_TABLES <= tables

    missing_fk_indexes: list[str] = []
    for table in sorted(tables):
        candidates = [
            tuple(index["column_names"])
            for index in inspector.get_indexes(table)
            if index.get("column_names")
        ]
        candidates.extend(
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(table)
            if item.get("column_names")
        )
        primary = tuple(inspector.get_pk_constraint(table).get("constrained_columns") or ())
        if primary:
            candidates.append(primary)
        for fk in inspector.get_foreign_keys(table):
            columns = tuple(fk.get("constrained_columns") or ())
            if columns and not any(candidate[: len(columns)] == columns for candidate in candidates):
                missing_fk_indexes.append(f"{table}({','.join(columns)})")
    assert missing_fk_indexes == []

    with engine.connect() as connection:
        constraints = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE connamespace = 'public'::regnamespace"
                )
            )
        }
    assert {
        "ck_credentials_credential_type",
        "ck_credentials_status",
        "ck_credentials_expiry_after_issue",
        "ck_credential_evidence_scan_state",
        "ck_credential_outbox_kind",
        "ck_credential_outbox_status",
        "ck_verification_access_logs_outcome",
    } <= constraints


def test_postgres_concurrent_idempotency_and_privacy(pg_ctx):
    client, factory, engine, storage = pg_ctx
    create_headers = {
        **_claims(STUDENT_ID, "student"),
        "Idempotency-Key": "wave3-pg-create-concurrent",
    }
    create_payload = {
        "title": "PostgreSQL Concurrency Credential",
        "credential_type": "certificate",
        "issue_date": "2026-01-15",
        "expiry_date": "2028-01-15",
        "issuer_id": str(ISSUER_ID),
        "identifier": "PG-CONCURRENCY-PRIVATE-0007",
    }

    def create_once():
        # A fresh HTTP client per worker avoids sharing Starlette's in-process
        # portal across threads; the concurrency under test is the real
        # PostgreSQL/API transaction boundary.
        with TestClient(client.app, raise_server_exceptions=False) as worker:
            return worker.post(
                "/api/v1/credentials",
                headers=create_headers,
                json=create_payload,
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        created = list(pool.map(lambda _: create_once(), range(8)))
    assert [response.status_code for response in created] == [201] * 8
    credential_ids = {response.json()["id"] for response in created}
    assert len(credential_ids) == 1
    credential_id = credential_ids.pop()

    evidence_marker = b"PRIVATE-WAVE3-EVIDENCE-MARKER"

    def upload_same_evidence():
        with TestClient(client.app, raise_server_exceptions=False) as worker:
            return worker.post(
                f"/api/v1/credentials/{credential_id}/evidence",
                headers=_claims(STUDENT_ID, "student"),
                files={
                    "file": (
                        "credential.pdf",
                        b"%PDF-1.7\n" + evidence_marker,
                        "application/pdf",
                    )
                },
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        uploads = list(pool.map(lambda _: upload_same_evidence(), range(8)))
    assert sorted(response.status_code for response in uploads) == [200] + [409] * 7
    assert all(
        response.status_code == 200
        or response.json()["detail"]["code"] == "duplicate_evidence"
        for response in uploads
    )

    verify_headers = {
        **_claims(ISSUER_ACTOR_ID, "lawyer"),
        "Idempotency-Key": "wave3-pg-verify-concurrent",
    }

    def verify_once():
        with TestClient(client.app, raise_server_exceptions=False) as worker:
            return worker.post(
                f"/api/v1/issuer/credentials/{credential_id}/verify",
                headers=verify_headers,
                json={"expected_version": 2},
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        verified = list(pool.map(lambda _: verify_once(), range(8)))
    assert [response.status_code for response in verified] == [200] * 8
    assert {response.json()["status"] for response in verified} == {"verified"}

    # A real verify-vs-revoke race on the same pending row cannot produce
    # contradictory terminal states: verify succeeds, while revoke receives a
    # typed conflict whether it acquires the row lock before or after verify.
    race_create = client.post(
        "/api/v1/credentials",
        headers={
            **_claims(STUDENT_ID, "student"),
            "Idempotency-Key": "wave3-pg-verify-revoke-race-create",
        },
        json={
            "title": "Verify revoke race",
            "credential_type": "certificate",
            "issue_date": "2026-01-15",
            "expiry_date": "2028-01-15",
            "issuer_id": str(ISSUER_ID),
        },
    )
    assert race_create.status_code == 201, race_create.text
    race_id = race_create.json()["id"]
    race_evidence = client.post(
        f"/api/v1/credentials/{race_id}/evidence",
        headers=_claims(STUDENT_ID, "student"),
        files={
            "file": (
                "race.pdf",
                b"%PDF-1.7\nrace-evidence",
                "application/pdf",
            )
        },
    )
    assert race_evidence.status_code == 200, race_evidence.text

    def race_verify():
        with TestClient(client.app, raise_server_exceptions=False) as worker:
            return worker.post(
                f"/api/v1/issuer/credentials/{race_id}/verify",
                headers={
                    **_claims(ISSUER_ACTOR_ID, "lawyer"),
                    "Idempotency-Key": "wave3-pg-race-verify",
                },
                json={"expected_version": 2},
            )

    def race_revoke():
        with TestClient(client.app, raise_server_exceptions=False) as worker:
            return worker.post(
                f"/api/v1/issuer/credentials/{race_id}/revoke",
                headers={
                    **_claims(ISSUER_ACTOR_ID, "lawyer"),
                    "Idempotency-Key": "wave3-pg-race-revoke",
                },
                json={
                    "expected_version": 2,
                    "reason": "Issuer race test revocation reason",
                },
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        race_responses = list(pool.map(lambda call: call(), [race_verify, race_revoke]))
    assert sorted(response.status_code for response in race_responses) == [200, 409]
    conflict = next(response for response in race_responses if response.status_code == 409)
    assert conflict.json()["detail"]["code"] in {
        "credential_not_revocable",
        "stale_credential_version",
    }
    with factory() as session:
        race_row = session.get(Credential, uuid.UUID(race_id))
        assert race_row.status == "verified"
        race_events = session.scalars(
            select(CredentialVerificationEvent).where(
                CredentialVerificationEvent.credential_id == uuid.UUID(race_id)
            )
        ).all()
        assert [(event.action, event.resulting_status) for event in race_events] == [
            ("verified", "verified")
        ]

    projection_headers = {
        **_claims(STUDENT_ID, "student"),
        "Idempotency-Key": "wave3-pg-projection-concurrent",
    }

    def projection_once():
        with TestClient(client.app, raise_server_exceptions=False) as worker:
            return worker.post(
                f"/api/v1/credentials/{credential_id}/share-projections",
                headers=projection_headers,
                json={
                    "fields": [
                        "title",
                        "credential_type",
                        "status",
                        "issuer_display_name",
                        "student_name",
                    ]
                },
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        projections = list(pool.map(lambda _: projection_once(), range(8)))
    assert [response.status_code for response in projections] == [200] * 8
    projection_ids = {response.json()["id"] for response in projections}
    assert len(projection_ids) == 1

    token_headers = {
        **_claims(STUDENT_ID, "student"),
        "Idempotency-Key": "wave3-pg-token-concurrent",
    }

    # Keep the projection id immutable across threads.
    projection_id = projections[0].json()["id"]

    def stable_token_once():
        with TestClient(client.app, raise_server_exceptions=False) as worker:
            return worker.post(
                f"/api/v1/credentials/{credential_id}/verification-tokens",
                headers=token_headers,
                json={"projection_id": projection_id, "lifetime_days": 90},
            )

    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: stable_token_once(), range(8)))
    assert [response.status_code for response in tokens] == [200] * 8
    assert len({response.json()["id"] for response in tokens}) == 1
    assert len({response.json()["token"] for response in tokens}) == 1
    raw_token = tokens[0].json()["token"]
    public = client.get(f"/api/v1/public/credential-verifications/{raw_token}")
    assert public.status_code == 200
    assert set(public.json()["verification"]) == {
        "title",
        "credential_type",
        "status",
        "issuer_display_name",
        "student_name",
    }

    with factory() as session:
        credential_uuid = uuid.UUID(credential_id)
        assert (
            len(
                session.scalars(
                    select(Credential).where(Credential.id == credential_uuid)
                ).all()
            )
            == 1
        )
        assert (
            len(
                session.scalars(
                    select(CredentialVerificationEvent).where(
                        CredentialVerificationEvent.credential_id
                        == credential_uuid
                    )
                ).all()
            )
            == 1
        )
        assert (
            len(
                session.scalars(
                    select(CredentialShareProjection).where(
                        CredentialShareProjection.credential_id
                        == credential_uuid
                    )
                ).all()
            )
            == 1
        )
        stored_tokens = session.scalars(
            select(VerificationToken).where(
                VerificationToken.credential_id == credential_uuid
            )
        ).all()
        assert len(stored_tokens) == 1
        assert stored_tokens[0].token_hash != raw_token
        evidence_row = session.scalar(
            select(CredentialEvidence).where(
                CredentialEvidence.credential_id == credential_uuid
            )
        )
        assert evidence_row and storage.exists(evidence_row.object_ref)

    sensitive_values = (
        "PG-CONCURRENCY-PRIVATE-0007",
        raw_token,
        evidence_marker.decode(),
        "9000000097",
        "2001-01-02",
    )
    with engine.connect() as connection:
        for table in sorted(set(inspect(engine).get_table_names())):
            columns = [
                column["name"] for column in inspect(engine).get_columns(table)
            ]
            if not columns:
                continue
            expression = " || ' ' || ".join(
                f"coalesce(\"{column}\"::text, '')" for column in columns
            )
            for value in sensitive_values:
                count = connection.scalar(
                    text(
                        f'SELECT count(*) FROM "{table}" '
                        f"WHERE ({expression}) LIKE :needle"
                    ),
                    {"needle": f"%{value}%"},
                )
                assert count == 0, f"plaintext fixture leaked in {table}"

        audit_rows = connection.execute(
            text("SELECT before_state, after_state FROM audit_events")
        ).all()
        forbidden_audit_keys = {
            "identifier",
            "token",
            "mobile",
            "dob",
            "evidence",
            "object_ref",
            "reason",
        }
        assert all(
            not forbidden_audit_keys.intersection((state or {}).keys())
            for row in audit_rows
            for state in row
            if isinstance(state, dict)
        )
