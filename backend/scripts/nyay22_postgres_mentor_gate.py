"""Native PostgreSQL 16/pgvector release gate for NYAY-22 mentor authority.

The ordinary HTTP suite uses SQLite and cannot prove PostgreSQL row locks,
partial indexes, advisory-lock exclusion, or migration lifecycle symmetry.
This opt-in producer accepts only a query-free literal-loopback control URL,
creates one marker-named disposable database, runs the 0022 -> 0023 -> 0022 ->
0023 lifecycle plus ``alembic check``, then executes privacy-safe aggregate
concurrency oracles.  It never prints or records a URL, cookie, UUID, digest,
profile value, proof value, request payload, or idempotency key.

Exit codes: 0 PASS, 1 FAIL, 78 BLOCKED prerequisite.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, make_url, select, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

CONTRACT_PATH = REPOSITORY / "scripts/ci/nyay22-mentor-postgres-contract.json"
OPT_IN_ENV = "NYAY22_POSTGRES_GATE"
BLOCKED_EXIT = 78
PREVIOUS_REVISION = "0022_nyay9_owner_profile_api"
APPLICATION_HEAD = "0023_nyay22_mentor_ceremony"
SCRATCH_PREFIX = "nyay22_mentor_"
TRUSTED_ORIGIN = "http://127.0.0.1:1130"
SCHEMA_VERSION = "nyay22-mentor-postgres/v1"
ORACLE_IDS = (
    "MIGRATION_0023_UP_DOWN_UP_CHECK",
    "POSTGRES_BOUNDED_LOCKS_NO_DEADLOCK",
    "INITIATE_SAME_KEY_EXACT_REPLAY",
    "INITIATE_CHANGED_PAYLOAD_CONFLICT",
    "PROVIDER_SUBJECT_UNIQUE_INSERT",
    "EXCHANGE_K1_K2_ONE_AUTHORITY",
    "OWNER_LOGIN_EXCHANGE_CLASS_EXCLUSION",
    "ROTATE_REVOKE_LINEARIZED",
    "ROTATE_LOGOUT_LINEARIZED",
    "DELETION_VERIFY_REVOKE_BOTH_ORDERS",
    "DELETION_EXCHANGE_REVOKE_BOTH_ORDERS",
    "PROOF_REVOCATION_AUTHORITY_RACE",
    "SUBJECT_CONSENT_REVOCATION_AUTHORITY_RACE",
    "RETENTION_ADVISORY_NONOVERLAP",
    "RETENTION_ATOMIC_GRAPH_SEVERANCE",
    "RETENTION_OVERSIZE_FAIL_CLOSED",
    "AUDIT_APPEND_ONLY_AND_CREDENTIAL_PRIVACY",
)
FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "actor",
        "cookie",
        "database",
        "digest",
        "email",
        "idempotency_key",
        "mobile",
        "payload",
        "profile",
        "registration",
        "subject",
        "token",
        "url",
        "uuid",
    }
)

# Raw values are held only in process so the native privacy oracle can prove
# that server-owned credentials never reached a text/JSON database column.
# They are never serialized, logged, or copied into the privacy-safe report.
_RUNTIME_SECRET_VALUES: set[str] = set()


class Blocked(RuntimeError):
    """A required native prerequisite is unavailable."""


class GateFailure(RuntimeError):
    """The native runtime exists but a required oracle failed."""


def _safe_control_url(raw: str) -> URL:
    if any(
        key in os.environ or any(name.startswith("PGSSL") for name in os.environ)
        for key in (
            "PGHOST",
            "PGHOSTADDR",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGPASSWORD",
            "PGPASSFILE",
            "PGSERVICE",
            "PGSERVICEFILE",
            "PGOPTIONS",
        )
    ):
        raise Blocked("ambient PostgreSQL routing is not allowed")
    if "://" not in raw:
        raise Blocked("an explicit PostgreSQL control URL is required")
    authority = re.split(r"[/?#]", raw.split("://", 1)[1], maxsplit=1)[0]
    if "%" in authority or authority.count("@") > 1:
        raise Blocked("the PostgreSQL authority is ambiguous")
    try:
        parsed = make_url(raw)
        address = ipaddress.ip_address(parsed.host or "")
    except Exception as exc:
        raise Blocked("a literal-loopback PostgreSQL URL is required") from exc
    if (
        parsed.get_backend_name() != "postgresql"
        or parsed.query
        or not address.is_loopback
    ):
        raise Blocked("a query-free literal-loopback PostgreSQL URL is required")
    return parsed


def _database_url(control: URL, name: str) -> str:
    return control.set(database=name).render_as_string(hide_password=False)


def _admin(control: URL, statement: str) -> None:
    engine = create_engine(
        _database_url(control, "postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text(statement))
    finally:
        engine.dispose()


def _drop(control: URL, name: str) -> None:
    try:
        _admin(control, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:
        _admin(control, f'DROP DATABASE IF EXISTS "{name}"')


def _run_alembic(database_url: str, *arguments: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env={
            **os.environ,
            "APP_ENV": "testing",
            "DATABASE_URL": database_url,
            "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise GateFailure("migration lifecycle failed")


def _migration_downgrade_toctou_oracle(database_url: str) -> int:
    """Prove a concurrent durable row can never race through downgrade.

    The fixture transaction takes PostgreSQL's normal ``RowExclusiveLock`` by
    inserting one valid bootstrap row.  Downgrade must then wait for its
    deterministic ACCESS EXCLUSIVE table lock, re-read the inventory after it
    acquires that lock, and refuse the destructive operation.  The subprocess
    output and application marker are process-only diagnostics and are never
    copied into the privacy-safe gate report.
    """

    mentor_tables = {
        "mentor_bootstrap_attempts",
        "mentor_invitations",
        "tutor_profile_ownership_proofs",
        "mentor_ceremonies",
        "mentor_provider_results",
        "mentor_subject_consents",
        "mentor_engagements",
        "mentor_consents",
        "mentor_sessions",
        "mentor_authority_step_ups",
        "mentor_idempotency_records",
        "mentor_rate_buckets",
        "mentor_audit_links",
        "mentor_retention_blocked_graphs",
    }
    engine = create_engine(database_url, poolclass=NullPool)
    holder = engine.connect()
    transaction = holder.begin()
    marker = f"nyay22_downgrade_probe_{uuid.uuid4().hex}"
    fixture_id = uuid.uuid4()
    process: subprocess.Popen[str] | None = None
    observed_access_exclusive_wait = False
    try:
        holder.execute(
            text(
                "INSERT INTO mentor_bootstrap_attempts "
                "(id, token_hash, requested_role, purpose_code, state, expires_at) "
                "VALUES (:id, :token_hash, 'tutor', 'student_guidance', "
                "'active', :expires_at)"
            ),
            {
                "id": fixture_id,
                "token_hash": hashlib.sha256(marker.encode("utf-8")).hexdigest(),
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=5),
            },
        )
        process = subprocess.Popen(
            [sys.executable, "-m", "alembic", "downgrade", PREVIOUS_REVISION],
            cwd=BACKEND,
            env={
                **os.environ,
                "APP_ENV": "testing",
                "DATABASE_URL": database_url,
                "PGAPPNAME": marker,
                "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and process.poll() is None:
            with engine.connect() as observer:
                wait_row = observer.execute(
                    text(
                        "SELECT a.wait_event_type, "
                        "bool_or(l.mode = 'AccessExclusiveLock' AND NOT l.granted) "
                        "FROM pg_stat_activity AS a "
                        "JOIN pg_locks AS l ON l.pid = a.pid "
                        "WHERE a.application_name = :marker "
                        "GROUP BY a.wait_event_type"
                    ),
                    {"marker": marker},
                ).first()
            if (
                wait_row is not None
                and wait_row[0] == "Lock"
                and wait_row[1] is True
            ):
                observed_access_exclusive_wait = True
                break
            time.sleep(0.02)
        if not observed_access_exclusive_wait:
            raise GateFailure("downgrade ACCESS EXCLUSIVE wait was not observed")

        transaction.commit()
        _output, _ = process.communicate(timeout=30)
        if process.returncode == 0:
            raise GateFailure("downgrade accepted a concurrent durable row")

        with engine.begin() as verifier:
            revision = verifier.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            tables = set(inspect(verifier).get_table_names())
            fixture_count = int(
                verifier.scalar(
                    text(
                        "SELECT count(*) FROM mentor_bootstrap_attempts "
                        "WHERE id = :id"
                    ),
                    {"id": fixture_id},
                )
                or 0
            )
            if revision != APPLICATION_HEAD or not mentor_tables <= tables:
                raise GateFailure("all mentor tables were not preserved")
            if fixture_count != 1:
                raise GateFailure("concurrent durable row was not preserved")
            verifier.execute(
                text("DELETE FROM mentor_bootstrap_attempts WHERE id = :id"),
                {"id": fixture_id},
            )
    finally:
        if transaction.is_active:
            transaction.rollback()
        holder.close()
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
        engine.dispose()
    return 7


def _migration_oracle(database_url: str) -> dict[str, Any]:
    _run_alembic(database_url, "upgrade", PREVIOUS_REVISION)
    _run_alembic(database_url, "upgrade", APPLICATION_HEAD)
    _run_alembic(database_url, "check")
    _run_alembic(database_url, "downgrade", PREVIOUS_REVISION)
    _run_alembic(database_url, "upgrade", APPLICATION_HEAD)
    _run_alembic(database_url, "check")
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            major = int(connection.scalar(text("SHOW server_version_num"))) // 10000
            vector = connection.scalar(
                text("SELECT 1 FROM pg_extension WHERE extname='vector'")
            )
        expected_tables = {
            "mentor_bootstrap_attempts",
            "mentor_invitations",
            "tutor_profile_ownership_proofs",
            "mentor_ceremonies",
            "mentor_provider_results",
            "mentor_subject_consents",
            "mentor_engagements",
            "mentor_consents",
            "mentor_sessions",
            "mentor_authority_step_ups",
            "mentor_idempotency_records",
            "mentor_rate_buckets",
            "mentor_audit_links",
            "mentor_retention_blocked_graphs",
        }
        tables = set(inspect(engine).get_table_names())
        passed = revision == APPLICATION_HEAD and major == 16 and vector == 1 and expected_tables <= tables
    finally:
        engine.dispose()
    if not passed:
        raise GateFailure("migration catalog oracle failed")
    toctou_assertions = _migration_downgrade_toctou_oracle(database_url)
    return {
        "id": ORACLE_IDS[0],
        "status": "PASS",
        "assertions": 6 + toctou_assertions,
    }


def _app(factory: sessionmaker[Session]) -> FastAPI:
    from app.api.v1.auth_mentor import router
    from app.db.session import get_session

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def provide():
        session = factory()
        try:
            yield session
        finally:
            session.rollback()
            session.close()

    app.dependency_overrides[get_session] = provide
    return app


def _seed(factory: sessionmaker[Session], marker: str) -> dict[str, Any]:
    from app.core.crypto import encrypt, keyed_hash
    from app.models.mentor_auth import (
        MentorBootstrapAttempt,
        MentorInvitation,
        MentorSubjectConsent,
        TutorProfileOwnershipProof,
    )
    from app.models.registration import StudentProfile, StudentRegistration, User
    from app.models.wave2 import TutorProfile
    from app.services.mentor_ceremony import _token_hash

    now = datetime.now(timezone.utc)
    bootstrap = f"bootstrap-{marker}-authority-value"
    with factory() as db:
        student = User(role="student", status="active")
        mentor = User(role="lawyer", status="active")
        db.add_all([student, mentor])
        db.flush()
        registration = StudentRegistration(
            user_id=student.id,
            first_name="Synthetic",
            last_name="Subject",
            mobile_hash=keyed_hash(f"mobile-{marker}"),
            mobile_ct=encrypt("9000000001"),
            dob_hash=keyed_hash(f"dob-{marker}"),
            dob_ct=encrypt("2000-01-01"),
            dob_hash_state="verified",
            key_version="v1",
            status="active",
            is_minor=False,
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
        provider_subject = f"provider-subject-{marker}"
        _RUNTIME_SECRET_VALUES.update({bootstrap, provider_subject})
        match = keyed_hash(provider_subject)
        proof = TutorProfileOwnershipProof(
            user_id=mentor.id,
            tutor_profile_id=tutor.id,
            provider_class="nyayone_reviewed_identity",
            assurance_class="high",
            policy_version="mentor-proof.v1",
            provider_subject_hash=match,
            evidence_digest=hashlib.sha256(f"evidence-{marker}".encode()).hexdigest(),
            key_version="v1",
            state="current",
            issued_at=now,
            expires_at=now + timedelta(hours=2),
        )
        invitation = MentorInvitation(
            subject_registration_id=registration.id,
            initiator_user_id=student.id,
            initiator_session_hash=keyed_hash(f"owner-session-{marker}"),
            creation_idempotency_hash=keyed_hash(f"invite-key-{marker}"),
            purpose_policy_version="mentor-purpose-policy.v1",
            mentor_match_hash=match,
            authority_domain_hash=keyed_hash(f"domain-{marker}"),
            mentor_role="tutor",
            purpose_code="student_guidance",
            consent_version="mentor-consent.v1",
            acceptance_text_version="mentor-acceptance.v1",
            disclosure_classes=["display_identity", "preferred_language"],
            state="pending",
            expires_at=now + timedelta(hours=1),
        )
        attempt = MentorBootstrapAttempt(
            token_hash=_token_hash(bootstrap),
            requested_role="tutor",
            purpose_code="student_guidance",
            state="active",
            expires_at=now + timedelta(minutes=10),
        )
        db.add_all([proof, invitation, attempt])
        db.flush()
        consent = MentorSubjectConsent(
            invitation_id=invitation.id,
            subject_registration_id=registration.id,
            granted_by_user_id=student.id,
            granting_session_hash=invitation.initiator_session_hash,
            grant_idempotency_hash=keyed_hash(f"consent-key-{marker}"),
            purpose_policy_version="mentor-purpose-policy.v1",
            guardian_consent_id=None,
            purpose_code="student_guidance",
            version="mentor-consent.v1",
            disclosure_classes=list(invitation.disclosure_classes),
            status="granted",
            recorded_at=now,
            expires_at=now + timedelta(hours=1),
        )
        db.add(consent)
        db.commit()
        return {
            "bootstrap": bootstrap,
            "bootstrap_id": attempt.id,
            "student": student.id,
            "mentor": mentor.id,
            "registration": registration.id,
            "tutor": tutor.id,
            "proof": proof.id,
            "invitation": invitation.id,
            "subject_consent": consent.id,
            "provider_subject": provider_subject,
        }


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, headers={"Origin": TRUSTED_ORIGIN})


def _copy_cookie(
    client: TestClient, *, name: str, value: str, path: str
) -> None:
    client.cookies.set(name, value, domain="testserver.local", path=path)


def _public_result(response: Any) -> tuple[int, str]:
    """Return only the status and sealed public code from a response."""

    try:
        body = response.json()
    except Exception:
        body = {}
    detail = body.get("detail", {}) if isinstance(body, dict) else {}
    code = detail.get("code") if isinstance(detail, dict) else None
    if not isinstance(code, str):
        code = "SUCCESS" if response.status_code < 400 else "FAILURE"
    return int(response.status_code), code


def _assert_bounded_results(
    results: list[tuple[int, str]], *, allowed: set[tuple[int, str]]
) -> None:
    if len(results) != 2 or any(result not in allowed for result in results):
        raise GateFailure("concurrent operation escaped the sealed outcome set")
    if any(status >= 500 for status, _code in results):
        raise GateFailure("concurrent operation reached a server failure")


def _sqlstate(exc: BaseException) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def _initiate(
    client: TestClient,
    bootstrap: str,
    key: str,
    *,
    requested_role: str = "tutor",
    purpose_code: str = "student_guidance",
):
    from app.services.mentor_ceremony import BOOTSTRAP_COOKIE, MENTOR_COOKIE_PATH

    client.cookies.set(BOOTSTRAP_COOKIE, bootstrap, path=MENTOR_COOKIE_PATH)
    return client.post(
        "/api/v1/auth/mentor/ceremony/initiate",
        headers={"Idempotency-Key": key},
        json={
            "intent": "mentor_session",
            "requestedMentorRole": requested_role,
            "purposeCode": purpose_code,
            "privacyNoticeVersion": "mentor-privacy.v1",
        },
    )


def _settle(
    factory: sessionmaker[Session], seeded: dict[str, Any], marker: str
) -> uuid.UUID:
    from app.models.mentor_auth import MentorCeremony

    with factory() as db:
        ceremony = db.scalar(
            select(MentorCeremony)
            .where(
                MentorCeremony.bootstrap_attempt_id == seeded["bootstrap_id"],
                MentorCeremony.state == "challenge_issued",
            )
            .order_by(MentorCeremony.id)
        )
        if ceremony is None:
            raise GateFailure("provider setup failed")
        ceremony_id = ceremony.id
    _settle_exact(
        factory,
        ceremony_id=ceremony_id,
        provider_subject=seeded["provider_subject"],
        evidence_marker=marker,
    )
    return ceremony_id


def _settle_exact(
    factory: sessionmaker[Session],
    *,
    ceremony_id: uuid.UUID,
    provider_subject: str,
    evidence_marker: str,
) -> None:
    from app.models.mentor_auth import MentorProviderResult
    from app.services import mentor_ceremony

    with factory() as db:
        transaction = mentor_ceremony.claim_provider_start(db, ceremony_id=ceremony_id)
        issued = datetime.now(timezone.utc)
        provider = db.scalar(
            select(MentorProviderResult).where(MentorProviderResult.ceremony_id == ceremony_id)
        )
        if provider is None:
            raise GateFailure("provider setup failed")
        expires = min(
            issued + timedelta(seconds=10),
            provider.expires_at.replace(tzinfo=timezone.utc)
            if provider.expires_at.tzinfo is None
            else provider.expires_at,
        )
        payload = {
            **transaction,
            "providerSubject": provider_subject,
            "accountBindingClass": "provider_account",
            "userPresenceApproved": True,
            "evidenceDigest": hashlib.sha256(
                f"evidence-{evidence_marker}".encode()
            ).hexdigest(),
            "issuedAt": issued.isoformat(),
            "expiresAt": expires.isoformat(),
        }
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("22" * 32))
        signature = base64.b64encode(
            private.sign(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        ).decode()
        mentor_ceremony.settle_provider_result(
            db,
            ceremony_id=ceremony_id,
            payload=payload,
            signature_b64=signature,
        )


def _verify(client: TestClient, key: str):
    return client.post(
        "/api/v1/auth/mentor/ceremony/verify",
        headers={"Idempotency-Key": key},
        json={"expectedCeremonyState": "challenge_issued"},
    )


def _exchange(client: TestClient, key: str):
    return client.post(
        "/api/v1/auth/mentor/ceremony/exchange",
        headers={"Idempotency-Key": key},
        json={
            "intent": "mentor_session",
            "expectedCeremonyState": "proof_verified",
            "acceptPurpose": True,
            "purposeCode": "student_guidance",
            "consentReceiptVersion": "mentor-consent.v1",
            "acceptanceTextVersion": "mentor-acceptance.v1",
        },
    )


def _ready_session(app: FastAPI, factory: sessionmaker[Session], marker: str) -> tuple[TestClient, dict[str, Any]]:
    seeded = _seed(factory, marker)
    client = _client(app)
    if _initiate(client, seeded["bootstrap"], f"initiate-{marker}-0000000001").status_code != 202:
        raise GateFailure("ceremony initiation failed")
    seeded["ceremony"] = _settle(factory, seeded, marker)
    if _verify(client, f"verify-{marker}-000000000001").status_code != 200:
        raise GateFailure("identity verification failed")
    from app.services.mentor_ceremony import CEREMONY_COOKIE

    ceremony_token = client.cookies.get(CEREMONY_COOKIE)
    if not ceremony_token:
        raise GateFailure("identity verification did not retain ceremony authority")
    _RUNTIME_SECRET_VALUES.add(ceremony_token)
    seeded["ceremony_token"] = ceremony_token
    if _exchange(client, f"exchange-{marker}-0000000001").status_code != 201:
        raise GateFailure("ceremony exchange failed")
    from app.services.mentor_ceremony import CEREMONY_COOKIE, SESSION_COOKIE

    session_token = client.cookies.get(SESSION_COOKIE)
    if not session_token:
        raise GateFailure("ceremony exchange did not issue mentor authority")
    _RUNTIME_SECRET_VALUES.add(session_token)
    return client, seeded


def _postgres_bounds_oracle(factory: sessionmaker[Session]) -> dict[str, Any]:
    from app.services import mentor_ceremony

    marker = uuid.uuid4().hex
    with factory() as db:
        mentor_ceremony._lock_authority_scope(
            db, fallback=f"native-bounds-success-{marker}"
        )
        lock_timeout = db.scalar(text("SHOW lock_timeout"))
        statement_timeout = db.scalar(text("SHOW statement_timeout"))
        if lock_timeout != "5s" or statement_timeout != "15s":
            raise GateFailure("PostgreSQL authority timeouts were not bounded")
        db.rollback()

    holder = factory()
    contender = factory()
    try:
        label = f"native-bounds-contended-{marker}"
        holder.execute(
            select(func.pg_advisory_xact_lock(mentor_ceremony._advisory_key(label)))
        )
        rejected = False
        try:
            mentor_ceremony._lock_authority_scope(contender, fallback=label)
        except mentor_ceremony.MentorCeremonyError as exc:
            rejected = (
                exc.status_code == 409
                and exc.code == "CONCURRENT_STATE_CHANGED"
                and exc.retryable is True
            )
        if not rejected:
            raise GateFailure("contended authority lock did not fail closed")
    finally:
        contender.rollback()
        contender.close()
        holder.rollback()
        holder.close()
    return {"id": ORACLE_IDS[1], "status": "PASS", "assertions": 5}


def _idempotency_oracles(
    app: FastAPI, factory: sessionmaker[Session]
) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.models.mentor_auth import MentorCeremony, MentorIdempotencyRecord
    from app.services import mentor_ceremony

    marker = uuid.uuid4().hex
    seeded = _seed(factory, marker)
    key = f"same-key-{marker}"
    barrier = threading.Barrier(2)

    def invoke() -> tuple[int, dict[str, Any]]:
        with _client(app) as client:
            barrier.wait(timeout=10)
            response = _initiate(client, seeded["bootstrap"], key)
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(timeout=30) for future in (pool.submit(invoke), pool.submit(invoke))]
    payload = {
        "intent": "mentor_session",
        "requestedMentorRole": "tutor",
        "purposeCode": "student_guidance",
        "privacyNoticeVersion": "mentor-privacy.v1",
    }
    expected_scope = mentor_ceremony._scope_hash(
        "initiate", f"bootstrap:{seeded['bootstrap_id']}", payload
    )
    expected_key = mentor_ceremony.keyed_hash(
        f"mentor-idempotency-key:v1:{key}"
    )
    with factory() as db:
        ceremonies = db.scalar(
            select(func.count()).select_from(MentorCeremony).where(
                MentorCeremony.bootstrap_attempt_id == seeded["bootstrap_id"]
            )
        )
        ledgers = db.scalar(
            select(func.count()).select_from(MentorIdempotencyRecord).where(
                MentorIdempotencyRecord.operation == "initiate",
                MentorIdempotencyRecord.scope_hash == expected_scope,
                MentorIdempotencyRecord.idempotency_key_hash == expected_key,
            )
        )
    if sorted(item[0] for item in results) != [202, 202] or results[0][1] != results[1][1] or ceremonies != 1 or ledgers != 1:
        raise GateFailure("same-key initiation did not linearize")

    with _client(app) as changed_client:
        changed = _initiate(
            changed_client,
            seeded["bootstrap"],
            key,
            requested_role="lawyer_tutor",
        )
    changed_result = _public_result(changed)
    with factory() as db:
        after_ceremonies = db.scalar(
            select(func.count()).select_from(MentorCeremony).where(
                MentorCeremony.bootstrap_attempt_id == seeded["bootstrap_id"]
            )
        )
        after_ledgers = db.scalar(
            select(func.count()).select_from(MentorIdempotencyRecord).where(
                MentorIdempotencyRecord.operation == "initiate",
                MentorIdempotencyRecord.scope_hash == expected_scope,
                MentorIdempotencyRecord.idempotency_key_hash == expected_key,
            )
        )
    if changed_result != (409, "IDEMPOTENCY_CONFLICT") or after_ceremonies != 1 or after_ledgers != 1:
        raise GateFailure("changed-payload same-key request did not fail closed")
    return (
        {"id": ORACLE_IDS[2], "status": "PASS", "assertions": 5},
        {"id": ORACLE_IDS[3], "status": "PASS", "assertions": 3},
    )


def _provider_subject_unique_race(
    factory: sessionmaker[Session],
) -> dict[str, Any]:
    from app.core.crypto import keyed_hash
    from app.models.mentor_auth import TutorProfileOwnershipProof
    from app.models.registration import User
    from app.models.wave2 import TutorProfile

    marker = uuid.uuid4().hex
    subject_hash = keyed_hash(f"native-provider-unique-{marker}")
    now = datetime.now(timezone.utc)
    with factory() as db:
        users = [User(role="lawyer", status="active") for _ in range(2)]
        db.add_all(users)
        db.flush()
        profiles = [
            TutorProfile(
                user_id=user.id,
                display_name="Native Gate Mentor",
                status="active",
                verified_identity=True,
                verified_credentials=True,
            )
            for user in users
        ]
        db.add_all(profiles)
        db.flush()
        bindings = [(user.id, profile.id) for user, profile in zip(users, profiles)]
        db.commit()
    barrier = threading.Barrier(2)

    def insert(binding: tuple[uuid.UUID, uuid.UUID], suffix: str) -> str:
        with factory() as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            db.add(
                TutorProfileOwnershipProof(
                    user_id=binding[0],
                    tutor_profile_id=binding[1],
                    provider_class="nyayone_reviewed_identity",
                    assurance_class="high",
                    policy_version="mentor-proof.v1",
                    provider_subject_hash=subject_hash,
                    evidence_digest=hashlib.sha256(
                        f"native-evidence-{marker}-{suffix}".encode()
                    ).hexdigest(),
                    key_version="v1",
                    state="current",
                    issued_at=now,
                    expires_at=now + timedelta(hours=1),
                )
            )
            barrier.wait(timeout=10)
            try:
                db.commit()
                return "COMMITTED"
            except IntegrityError as exc:
                state = _sqlstate(exc)
                db.rollback()
                if state != "23505":
                    raise GateFailure("provider uniqueness failed unexpectedly") from None
                return "UNIQUE_REJECTED"
            except DBAPIError as exc:
                state = _sqlstate(exc)
                db.rollback()
                if state in {"40P01", "57014", "55P03"}:
                    raise GateFailure("provider uniqueness deadlocked or timed out") from None
                raise GateFailure("provider uniqueness database failure") from None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=30)
            for future in (
                pool.submit(insert, bindings[0], "a"),
                pool.submit(insert, bindings[1], "b"),
            )
        ]
    with factory() as db:
        scoped = db.scalar(
            select(func.count()).select_from(TutorProfileOwnershipProof).where(
                TutorProfileOwnershipProof.provider_class
                == "nyayone_reviewed_identity",
                TutorProfileOwnershipProof.provider_subject_hash == subject_hash,
                TutorProfileOwnershipProof.state == "current",
                TutorProfileOwnershipProof.deleted_at.is_(None),
            )
        )
    if sorted(results) != ["COMMITTED", "UNIQUE_REJECTED"] or scoped != 1:
        raise GateFailure("provider subject uniqueness did not linearize")
    return {"id": ORACLE_IDS[4], "status": "PASS", "assertions": 4}


def _exchange_race(
    app: FastAPI, factory: sessionmaker[Session]
) -> dict[str, Any]:
    from app.models.mentor_auth import MentorSession
    from app.services.mentor_ceremony import CEREMONY_COOKIE, MENTOR_COOKIE_PATH

    marker = uuid.uuid4().hex
    seeded = _seed(factory, marker)
    setup = _client(app)
    if _initiate(setup, seeded["bootstrap"], f"setup-{marker}-000000000001").status_code != 202:
        raise GateFailure("exchange setup failed")
    seeded["ceremony"] = _settle(factory, seeded, marker)
    if _verify(setup, f"proof-{marker}-0000000000001").status_code != 200:
        raise GateFailure("exchange setup failed")
    ceremony_cookie = setup.cookies.get(CEREMONY_COOKIE)
    if not ceremony_cookie:
        raise GateFailure("exchange setup failed")
    barrier = threading.Barrier(2)

    def invoke(suffix: str) -> int:
        with _client(app) as client:
            client.cookies.set(CEREMONY_COOKIE, ceremony_cookie, path=MENTOR_COOKIE_PATH)
            barrier.wait(timeout=10)
            return _exchange(client, f"exchange-race-{suffix}-{marker}").status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = [future.result(timeout=30) for future in (pool.submit(invoke, "a"), pool.submit(invoke, "b"))]
    with factory() as db:
        session_count = db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"],
                MentorSession.ceremony_id == seeded["ceremony"],
            )
        )
        active = db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"],
                MentorSession.ceremony_id == seeded["ceremony"],
                MentorSession.state == "active",
            )
        )
    if sorted(statuses) != [201, 409] or session_count != 1 or active != 1:
        raise GateFailure("exchange did not produce one authority")
    setup.close()
    return {"id": ORACLE_IDS[5], "status": "PASS", "assertions": 5}


def _recovery_active_set_snapshot_oracle(
    app: FastAPI,
    factory: sessionmaker[Session],
) -> int:
    """Reject recovery when any active generation appeared after verify.

    Recovery is actor/profile-global rather than purpose-local.  Verification
    therefore records the complete active mentor-session set and exchange may
    revoke exactly that set only.  This native proof commits a different-purpose
    generation after the verification snapshot, then requires the exchange to
    fail without mutating either authority or its engagement graph.
    """

    from app.core.crypto import keyed_hash
    from app.models.mentor_auth import (
        MentorBootstrapAttempt,
        MentorCeremony,
        MentorEngagement,
        MentorInvitation,
        MentorSession,
        MentorSubjectConsent,
        TutorProfileOwnershipProof,
    )
    from app.models.registration import StudentRegistration
    from app.services import mentor_ceremony
    from app.services.mentor_ceremony import (
        BOOTSTRAP_COOKIE,
        MENTOR_COOKIE_PATH,
    )

    marker = uuid.uuid4().hex
    client, seeded = _ready_session(app, factory, marker)
    recovery_bootstrap = f"recovery-bootstrap-{marker}-authority-value"
    _RUNTIME_SECRET_VALUES.add(recovery_bootstrap)
    now = datetime.now(timezone.utc)

    with factory() as db:
        proof = db.get(TutorProfileOwnershipProof, seeded["proof"])
        registration = db.get(StudentRegistration, seeded["registration"])
        if proof is None or registration is None:
            raise GateFailure("recovery active-set setup failed")
        pending = MentorInvitation(
            subject_registration_id=registration.id,
            initiator_user_id=seeded["student"],
            initiator_session_hash=keyed_hash(
                f"recovery-owner-session-{marker}"
            ),
            creation_idempotency_hash=keyed_hash(
                f"recovery-invitation-request-{marker}"
            ),
            purpose_policy_version="mentor-purpose-policy.v1",
            mentor_match_hash=proof.provider_subject_hash,
            authority_domain_hash=keyed_hash(
                f"recovery-authority-domain-{marker}"
            ),
            mentor_role="tutor",
            purpose_code="student_guidance",
            consent_version="mentor-consent.v1",
            acceptance_text_version="mentor-acceptance.v1",
            disclosure_classes=["display_identity"],
            state="pending",
            expires_at=now + timedelta(hours=1),
        )
        bootstrap = MentorBootstrapAttempt(
            token_hash=mentor_ceremony._token_hash(recovery_bootstrap),
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
                subject_registration_id=registration.id,
                granted_by_user_id=seeded["student"],
                granting_session_hash=pending.initiator_session_hash,
                grant_idempotency_hash=keyed_hash(
                    f"recovery-subject-consent-{marker}"
                ),
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
        bootstrap_id = bootstrap.id
        db.commit()

    _copy_cookie(
        client,
        name=BOOTSTRAP_COOKIE,
        value=recovery_bootstrap,
        path=MENTOR_COOKIE_PATH,
    )
    recovered = client.post(
        "/api/v1/auth/mentor/ceremony/recover",
        headers={"Idempotency-Key": f"recovery-start-{marker}"},
        json={
            "intent": "mentor_session",
            "requestedMentorRole": "tutor",
            "purposeCode": "student_guidance",
            "recoveryMethod": "fresh_external_identity",
            "privacyNoticeVersion": "mentor-privacy.v1",
        },
    )
    if recovered.status_code != 202:
        raise GateFailure("recovery active-set setup failed")
    with factory() as db:
        recovery = db.scalar(
            select(MentorCeremony).where(
                MentorCeremony.bootstrap_attempt_id == bootstrap_id,
                MentorCeremony.recovery.is_(True),
                MentorCeremony.state == "challenge_issued",
            )
        )
        if recovery is None:
            raise GateFailure("recovery active-set setup failed")
        recovery_id = recovery.id
    _settle_exact(
        factory,
        ceremony_id=recovery_id,
        provider_subject=seeded["provider_subject"],
        # Recovery must independently prove the exact currently-bound
        # provider evidence, not manufacture a different evidence digest.
        evidence_marker=marker,
    )
    verified = _verify(client, f"recovery-verify-{marker}")
    if verified.status_code != 200:
        status, code = _public_result(verified)
        raise GateFailure(
            f"recovery active-set verification failed: {status}:{code}"
        )

    with factory() as db:
        recovery = db.get(MentorCeremony, recovery_id)
        predecessor = db.scalar(
            select(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"],
                MentorSession.state == "active",
            )
        )
        if recovery is None or predecessor is None:
            raise GateFailure("recovery active-set setup failed")
        marked = set(
            (recovery.metadata_json or {}).get(
                "mandatoryRevocationSessionIds", []
            )
        )
        if marked != {str(predecessor.id)}:
            raise GateFailure("recovery verification did not seal the active set")

        late_id = uuid.uuid4()
        late_raw, late_seed, late_seed_version = mentor_ceremony._new_seeded_token(
            "session", late_id
        )
        _RUNTIME_SECRET_VALUES.add(late_raw)
        db.add(
            MentorSession(
                id=late_id,
                ceremony_id=predecessor.ceremony_id,
                engagement_id=predecessor.engagement_id,
                actor_user_id=predecessor.actor_user_id,
                tutor_profile_id=predecessor.tutor_profile_id,
                ownership_proof_id=predecessor.ownership_proof_id,
                consent_id=predecessor.consent_id,
                subject_consent_id=predecessor.subject_consent_id,
                authority_domain_hash=predecessor.authority_domain_hash,
                token_hash=mentor_ceremony._token_hash(late_raw),
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
        )
        db.commit()
        before = {
            row.id: (row.state, row.terminal_at)
            for row in db.scalars(
                select(MentorSession).where(
                    MentorSession.actor_user_id == seeded["mentor"]
                )
            )
        }
        engagement_count = int(
            db.scalar(select(func.count()).select_from(MentorEngagement)) or 0
        )

    denied = _public_result(_exchange(client, f"recovery-exchange-{marker}"))
    with factory() as db:
        after = {
            row.id: (row.state, row.terminal_at)
            for row in db.scalars(
                select(MentorSession).where(
                    MentorSession.actor_user_id == seeded["mentor"]
                )
            )
        }
        after_engagements = int(
            db.scalar(select(func.count()).select_from(MentorEngagement)) or 0
        )
    client.close()
    if denied != (409, "CONCURRENT_STATE_CHANGED"):
        raise GateFailure("recovery accepted an unmarked active session")
    if after != before or after_engagements != engagement_count:
        raise GateFailure("recovery active-set mismatch mutated authority")
    return 8


def _expired_mentor_owner_login_race_oracle(
    app: FastAPI,
    factory: sessionmaker[Session],
) -> int:
    """Prove elapsed mentor authority cannot survive a concurrent owner login.

    Each schedule uses two independent PostgreSQL sessions.  A test-only hook
    pauses the transaction that must commit first only after it owns the stable
    actor/session locks; the losing transaction is then started against those
    same locks.  This proves both serialization orders without sleeps, retries,
    or a client-side authority bypass.
    """

    from app.models.mentor_auth import MentorIdempotencyRecord, MentorSession
    from app.models.registration import AuthSession, StudentRegistration
    from app.services import login_service, mentor_ceremony
    from app.services.mentor_ceremony import SESSION_COOKIE

    final_shapes: list[tuple[int, int, int, int]] = []
    assertions = 0
    for operation in ("rotate", "revoke", "logout"):
        for order in ("owner_first", "mentor_first"):
            marker = uuid.uuid4().hex
            mentor_client, seeded = _ready_session(app, factory, marker)
            mentor_raw = mentor_client.cookies.get(SESSION_COOKIE)
            unrelated_client, unrelated = _ready_session(
                app, factory, f"unrelated-{marker}"
            )
            if not mentor_raw:
                raise GateFailure("expired-cookie race setup failed")
            _RUNTIME_SECRET_VALUES.add(mentor_raw)
            boundary_now = datetime.now(timezone.utc)
            with factory() as db:
                elapsed = db.scalar(
                    select(MentorSession).where(
                        MentorSession.actor_user_id == seeded["mentor"],
                        MentorSession.state == "active",
                    )
                )
                unrelated_row = db.scalar(
                    select(MentorSession).where(
                        MentorSession.actor_user_id == unrelated["mentor"],
                        MentorSession.state == "active",
                    )
                )
                if elapsed is None or unrelated_row is None:
                    raise GateFailure("expired-cookie race setup failed")
                # Preserve the database's positive-lifetime invariant while
                # making only the immutable idle boundary elapsed.
                elapsed.expires_at = boundary_now + timedelta(minutes=1)
                elapsed.last_seen_at = boundary_now - timedelta(
                    seconds=(
                        mentor_ceremony.settings.mentor_session_idle_ttl_seconds
                        + 2
                    )
                )
                expected_terminal = elapsed.last_seen_at + timedelta(
                    seconds=mentor_ceremony.settings.mentor_session_idle_ttl_seconds
                )
                unrelated_before = {
                    column.name: getattr(unrelated_row, column.name)
                    for column in MentorSession.__table__.columns
                }
                db.commit()

            owner_locked = threading.Event()
            mentor_locked = threading.Event()
            contender_started = threading.Event()
            release_winner = threading.Event()
            original_owner_lock = login_service.active_sessions_for_rotation
            original_mentor_lock = mentor_ceremony._lock_actor_session_classes

            def owner_lock_hook(db: Session, user_id: uuid.UUID):
                if order == "mentor_first":
                    contender_started.set()
                    return original_owner_lock(db, user_id)
                rows = original_owner_lock(db, user_id)
                owner_locked.set()
                if not release_winner.wait(timeout=10):
                    raise GateFailure("owner-first schedule did not settle")
                return rows

            def mentor_lock_hook(db: Session, actor_id: uuid.UUID):
                if actor_id != seeded["mentor"]:
                    return original_mentor_lock(db, actor_id)
                if order == "owner_first":
                    contender_started.set()
                    return original_mentor_lock(db, actor_id)
                rows = original_mentor_lock(db, actor_id)
                mentor_locked.set()
                if not release_winner.wait(timeout=10):
                    raise GateFailure("mentor-first schedule did not settle")
                return rows

            def owner_login() -> tuple[int, str]:
                if order == "mentor_first":
                    contender_started.set()
                with factory() as db:
                    db.execute(text("SET LOCAL lock_timeout = '5s'"))
                    db.execute(text("SET LOCAL statement_timeout = '15s'"))
                    if (
                        db.scalar(text("SHOW lock_timeout")) != "5s"
                        or db.scalar(text("SHOW statement_timeout")) != "15s"
                    ):
                        raise GateFailure("owner-login race timeouts were not bounded")
                    registration = db.get(
                        StudentRegistration, seeded["registration"]
                    )
                    if registration is None:
                        raise GateFailure("expired-cookie race setup failed")
                    try:
                        raw_owner, _row = login_service.rotate_authenticated_session(
                            db,
                            registration,
                            boundary_now,
                            presented_mentor_session_token=mentor_raw,
                        )
                    except DBAPIError as exc:
                        if _sqlstate(exc) == "40P01":
                            raise GateFailure("owner/mentor race deadlocked") from None
                        raise
                    _RUNTIME_SECRET_VALUES.add(raw_owner)
                    return (200, "SUCCESS")

            def mentor_operation() -> tuple[int, str]:
                # Owner-first now serializes at the canonical actor advisory
                # lock before the mentor row-lock hook can run.  Record that
                # the contender has entered the request before it blocks on
                # that lock; settlement is still proven by the durable result
                # and bounded SQL lock/statement timeouts below.
                if order == "owner_first":
                    contender_started.set()
                with _client(app) as peer:
                    _copy_cookie(
                        peer,
                        name=SESSION_COOKIE,
                        value=mentor_raw,
                        path="/",
                    )
                    if operation == "rotate":
                        response = peer.post(
                            "/api/v1/auth/mentor/session/rotate",
                            headers={
                                "Idempotency-Key": f"expired-rotate-{marker}"
                            },
                            json={
                                "expectedSessionState": "active",
                                "purposeCode": "student_guidance",
                                "reasonCode": "routine_rotation",
                            },
                        )
                    else:
                        response = peer.post(
                            f"/api/v1/auth/mentor/session/{operation}",
                            headers={
                                "Idempotency-Key": (
                                    f"expired-{operation}-{marker}"
                                )
                            },
                            json={
                                "expectedSessionState": "active",
                                "purposeCode": "student_guidance",
                                "reasonCode": (
                                    "mentor_requested"
                                    if operation == "revoke"
                                    else "purpose_complete"
                                ),
                            },
                        )
                    return _public_result(response)

            login_service.active_sessions_for_rotation = owner_lock_hook
            mentor_ceremony._lock_actor_session_classes = mentor_lock_hook
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    if order == "owner_first":
                        first = pool.submit(owner_login)
                        if not owner_locked.wait(timeout=10):
                            raise GateFailure("owner-first lock was not acquired")
                        second = pool.submit(mentor_operation)
                    else:
                        first = pool.submit(mentor_operation)
                        if not mentor_locked.wait(timeout=10):
                            raise GateFailure("mentor-first lock was not acquired")
                        second = pool.submit(owner_login)
                    if not contender_started.wait(timeout=10):
                        raise GateFailure("expired-cookie contender did not start")
                    release_winner.set()
                    first_result = first.result(timeout=30)
                    second_result = second.result(timeout=30)
            finally:
                release_winner.set()
                login_service.active_sessions_for_rotation = original_owner_lock
                mentor_ceremony._lock_actor_session_classes = original_mentor_lock

            owner_result, mentor_result = (
                (first_result, second_result)
                if order == "owner_first"
                else (second_result, first_result)
            )
            expected_mentor = (
                (410, "AUTHORITY_TERMINAL")
                if order == "owner_first"
                else (410, "SESSION_EXPIRED")
            )
            if owner_result != (200, "SUCCESS") or mentor_result != expected_mentor:
                raise GateFailure("expired-cookie race escaped its sealed outcomes")
            if any(status >= 500 for status, _code in (owner_result, mentor_result)):
                raise GateFailure("expired-cookie race reached a server failure")

            with factory() as db:
                elapsed = db.scalar(
                    select(MentorSession).where(
                        MentorSession.actor_user_id == seeded["mentor"]
                    )
                )
                unrelated_after_row = db.scalar(
                    select(MentorSession).where(
                        MentorSession.actor_user_id == unrelated["mentor"]
                    )
                )
                mentor_active = int(
                    db.scalar(
                        select(func.count()).select_from(MentorSession).where(
                            MentorSession.actor_user_id == seeded["mentor"],
                            MentorSession.state == "active",
                        )
                    )
                    or 0
                )
                mentor_rows = int(
                    db.scalar(
                        select(func.count()).select_from(MentorSession).where(
                            MentorSession.actor_user_id == seeded["mentor"]
                        )
                    )
                    or 0
                )
                owner_active = int(
                    db.scalar(
                        select(func.count()).select_from(AuthSession).where(
                            AuthSession.user_id == seeded["student"],
                            AuthSession.status == "active",
                        )
                    )
                    or 0
                )
                wrong_owner_active = int(
                    db.scalar(
                        select(func.count()).select_from(AuthSession).where(
                            AuthSession.user_id == seeded["mentor"],
                            AuthSession.status == "active",
                        )
                    )
                    or 0
                )
                durable_lifecycle_records = int(
                    db.scalar(
                        select(func.count())
                        .select_from(MentorIdempotencyRecord)
                        .where(
                            MentorIdempotencyRecord.operation == operation,
                            MentorIdempotencyRecord.state == "completed",
                        )
                    )
                    or 0
                )
                unrelated_after = (
                    {
                        column.name: getattr(unrelated_after_row, column.name)
                        for column in MentorSession.__table__.columns
                    }
                    if unrelated_after_row is not None
                    else None
                )
            if (
                elapsed is None
                or elapsed.state != "expired"
                or elapsed.terminal_at != expected_terminal
                or elapsed.successor_id is not None
                or mentor_active != 0
                or mentor_rows != 1
                or owner_active != 1
                or wrong_owner_active != 0
                or durable_lifecycle_records != 0
            ):
                raise GateFailure(
                    "owner/mentor race retained incompatible session classes"
                )
            if unrelated_after != unrelated_before:
                raise GateFailure("expired-cookie race changed unrelated authority")
            final_shapes.append(
                (mentor_active, mentor_rows, owner_active, wrong_owner_active)
            )
            mentor_client.close()
            unrelated_client.close()
            assertions += 12

    if len(set(final_shapes)) != 1 or final_shapes[0] != (0, 1, 1, 0):
        raise GateFailure("expired-cookie schedules had different durable results")
    return assertions + 1


def _expired_owner_cookie_mentor_race_oracle(
    app: FastAPI,
    factory: sessionmaker[Session],
) -> int:
    """Prove an elapsed owner cookie cannot invert the shared class lock order."""

    from app.core.config import settings
    from app.core.crypto import keyed_hash
    from app.models.mentor_auth import MentorSession
    from app.models.registration import AuthSession, StudentRegistration
    from app.services import login_service, mentor_ceremony
    from app.services.mentor_ceremony import SESSION_COOKIE

    assertions = 0
    durable_shapes: dict[str, list[tuple[int, int, int, int, int]]] = {
        "read": [],
        "rotate": [],
    }
    for operation in ("read", "rotate"):
        for order in ("owner_first", "mentor_first"):
            marker = uuid.uuid4().hex
            mentor_client, seeded = _ready_session(app, factory, marker)
            mentor_raw = mentor_client.cookies.get(SESSION_COOKIE)
            unrelated_client, unrelated = _ready_session(
                app, factory, f"unrelated-owner-cookie-{marker}"
            )
            if not mentor_raw:
                raise GateFailure("expired owner-cookie race setup failed")
            owner_raw = f"elapsed-owner-authority-{marker}"
            _RUNTIME_SECRET_VALUES.update({mentor_raw, owner_raw})
            boundary_now = datetime.now(timezone.utc)
            owner_expiry = boundary_now - timedelta(seconds=2)
            with factory() as db:
                expired_owner = AuthSession(
                    user_id=seeded["mentor"],
                    token_hash=keyed_hash(owner_raw),
                    status="active",
                    expires_at=owner_expiry,
                    last_seen_at=boundary_now - timedelta(minutes=1),
                )
                db.add(expired_owner)
                unrelated_row = db.scalar(
                    select(MentorSession).where(
                        MentorSession.actor_user_id == unrelated["mentor"],
                        MentorSession.state == "active",
                    )
                )
                if unrelated_row is None:
                    raise GateFailure("expired owner-cookie race setup failed")
                unrelated_before = {
                    column.name: getattr(unrelated_row, column.name)
                    for column in MentorSession.__table__.columns
                }
                db.commit()
                expired_owner_id = expired_owner.id

            peer = _client(app)
            _copy_cookie(peer, name=SESSION_COOKIE, value=mentor_raw, path="/")
            _copy_cookie(
                peer,
                name=settings.auth_session_cookie_name,
                value=owner_raw,
                path="/",
            )
            owner_locked = threading.Event()
            mentor_locked = threading.Event()
            contender_started = threading.Event()
            release_winner = threading.Event()
            hook_guard = threading.Lock()
            mentor_hook_seen = False
            original_owner_lock = login_service.active_sessions_for_rotation
            original_active_student = mentor_ceremony._active_student_session
            original_now = mentor_ceremony._now

            def owner_lock_hook(db: Session, user_id: uuid.UUID):
                rows = original_owner_lock(db, user_id)
                if order == "owner_first" and user_id == seeded["student"]:
                    owner_locked.set()
                    if not release_winner.wait(timeout=10):
                        raise GateFailure("owner-first schedule did not settle")
                return rows

            def active_student_hook(db: Session, request: Any):
                nonlocal mentor_hook_seen
                target = (
                    request.cookies.get(settings.auth_session_cookie_name)
                    == owner_raw
                )
                if target and order == "owner_first":
                    contender_started.set()
                result = original_active_student(db, request)
                should_pause = False
                if target and order == "mentor_first":
                    with hook_guard:
                        if not mentor_hook_seen:
                            mentor_hook_seen = True
                            should_pause = True
                if should_pause:
                    mentor_locked.set()
                    if not release_winner.wait(timeout=10):
                        raise GateFailure("mentor-first schedule did not settle")
                return result

            def owner_login() -> tuple[int, str]:
                if order == "mentor_first":
                    contender_started.set()
                with factory() as db:
                    db.execute(text("SET LOCAL lock_timeout = '5s'"))
                    db.execute(text("SET LOCAL statement_timeout = '15s'"))
                    if (
                        db.scalar(text("SHOW lock_timeout")) != "5s"
                        or db.scalar(text("SHOW statement_timeout")) != "15s"
                    ):
                        raise GateFailure(
                            "expired owner-cookie race timeouts were not bounded"
                        )
                    registration = db.get(
                        StudentRegistration, seeded["registration"]
                    )
                    if registration is None:
                        raise GateFailure("expired owner-cookie race setup failed")
                    try:
                        login_service.rotate_authenticated_session(
                            db,
                            registration,
                            boundary_now,
                            presented_mentor_session_token=mentor_raw,
                        )
                    except login_service.LoginError as exc:
                        return (exc.status_code, exc.code)
                    except DBAPIError as exc:
                        if _sqlstate(exc) == "40P01":
                            raise
                        raise
                return (200, "SUCCESS")

            def mentor_operation() -> tuple[int, str]:
                if order == "owner_first":
                    contender_started.set()
                if operation == "read":
                    response = peer.get("/api/v1/auth/mentor/session")
                else:
                    response = peer.post(
                        "/api/v1/auth/mentor/session/rotate",
                        headers={
                            "Idempotency-Key": f"owner-cookie-rotate-{marker}"
                        },
                        json={
                            "expectedSessionState": "active",
                            "purposeCode": "student_guidance",
                            "reasonCode": "routine_rotation",
                        },
                    )
                return _public_result(response)

            login_service.active_sessions_for_rotation = owner_lock_hook
            mentor_ceremony._active_student_session = active_student_hook
            mentor_ceremony._now = lambda: boundary_now
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    if order == "owner_first":
                        first = pool.submit(owner_login)
                        if not owner_locked.wait(timeout=10):
                            raise GateFailure("owner-first lock was not acquired")
                        second = pool.submit(mentor_operation)
                    else:
                        first = pool.submit(mentor_operation)
                        if not mentor_locked.wait(timeout=10):
                            raise GateFailure("mentor-first lock was not acquired")
                        second = pool.submit(owner_login)
                    if not contender_started.wait(timeout=10):
                        raise GateFailure("owner-cookie contender did not start")
                    release_winner.set()
                    first_result = first.result(timeout=30)
                    second_result = second.result(timeout=30)
            finally:
                release_winner.set()
                login_service.active_sessions_for_rotation = original_owner_lock
                mentor_ceremony._active_student_session = original_active_student
                mentor_ceremony._now = original_now

            owner_result, mentor_result = (
                (first_result, second_result)
                if order == "owner_first"
                else (second_result, first_result)
            )
            if owner_result != (409, "login_conflict"):
                raise GateFailure(
                    "live mentor authority did not exclude owner login: "
                    f"{operation}/{order}={owner_result!r}"
                )
            if mentor_result != (200, "SUCCESS"):
                raise GateFailure("elapsed owner cookie blocked live mentor authority")
            if any(status >= 500 for status, _code in (owner_result, mentor_result)):
                raise GateFailure("owner-cookie race reached a server failure")

            with factory() as db:
                expired_owner = db.get(AuthSession, expired_owner_id)
                mentor_rows = list(
                    db.scalars(
                        select(MentorSession)
                        .where(MentorSession.actor_user_id == seeded["mentor"])
                        .order_by(MentorSession.generation)
                    )
                )
                unrelated_after_row = db.scalar(
                    select(MentorSession).where(
                        MentorSession.actor_user_id == unrelated["mentor"]
                    )
                )
                unrelated_after = (
                    {
                        column.name: getattr(unrelated_after_row, column.name)
                        for column in MentorSession.__table__.columns
                    }
                    if unrelated_after_row is not None
                    else None
                )
                active_mentor = sum(row.state == "active" for row in mentor_rows)
                active_owner_a = int(
                    db.scalar(
                        select(func.count()).select_from(AuthSession).where(
                            AuthSession.user_id == seeded["mentor"],
                            AuthSession.status == "active",
                        )
                    )
                    or 0
                )
                active_owner_b = int(
                    db.scalar(
                        select(func.count()).select_from(AuthSession).where(
                            AuthSession.user_id == seeded["student"],
                            AuthSession.status == "active",
                        )
                    )
                    or 0
                )
            if (
                expired_owner is None
                or expired_owner.status != "expired"
                or expired_owner.expires_at != owner_expiry
                or expired_owner.revoked_at != owner_expiry
            ):
                raise GateFailure(
                    "expired owner boundary was not materialized exactly"
                )
            expected_rows = 1 if operation == "read" else 2
            if (
                active_mentor != 1
                or len(mentor_rows) != expected_rows
                or active_owner_a != 0
                or active_owner_b != 0
            ):
                raise GateFailure(
                    "owner-cookie race retained incompatible session classes"
                )
            if unrelated_after != unrelated_before:
                raise GateFailure("owner-cookie race changed unrelated authority")
            durable_shapes[operation].append(
                (
                    active_mentor,
                    len(mentor_rows),
                    active_owner_a,
                    active_owner_b,
                    int(expired_owner.status == "expired"),
                )
            )
            mentor_client.close()
            unrelated_client.close()
            peer.close()
            assertions += 12

    if any(len(set(rows)) != 1 for rows in durable_shapes.values()):
        raise GateFailure("owner-cookie schedules had different durable results")
    return assertions + 2


def _owner_exclusion(
    app: FastAPI, factory: sessionmaker[Session]
) -> dict[str, Any]:
    from app.core.config import settings
    from app.models.mentor_auth import MentorSession
    from app.models.registration import AuthSession, StudentRegistration
    from app.services import login_service
    from app.services.mentor_ceremony import SESSION_COOKIE

    recovery_assertions = _recovery_active_set_snapshot_oracle(app, factory)
    expired_cookie_assertions = _expired_mentor_owner_login_race_oracle(app, factory)
    expired_owner_assertions = _expired_owner_cookie_mentor_race_oracle(app, factory)
    now = datetime.now(timezone.utc)
    mentor_first_client, mentor_first = _ready_session(
        app, factory, uuid.uuid4().hex
    )
    mentor_token = mentor_first_client.cookies.get(SESSION_COOKIE)
    if not mentor_token:
        raise GateFailure("mentor-first class exclusion setup failed")
    mentor_first_rejected = False
    with factory() as db:
        registration = db.get(StudentRegistration, mentor_first["registration"])
        if registration is None:
            raise GateFailure("mentor-first class exclusion setup failed")
        try:
            login_service.rotate_authenticated_session(
                db,
                registration,
                now,
                presented_mentor_session_token=mentor_token,
            )
        except login_service.LoginError as exc:
            mentor_first_rejected = (
                exc.status_code == 409 and exc.code == "login_conflict"
            )
    mentor_first_client.close()

    owner_first_marker = uuid.uuid4().hex
    owner_first = _seed(factory, owner_first_marker)
    ceremony_client = _client(app)
    if _initiate(
        ceremony_client,
        owner_first["bootstrap"],
        f"owner-first-init-{owner_first_marker}",
    ).status_code != 202:
        raise GateFailure("owner-first class exclusion setup failed")
    owner_first["ceremony"] = _settle(
        factory, owner_first, owner_first_marker
    )
    if _verify(
        ceremony_client, f"owner-first-verify-{owner_first_marker}"
    ).status_code != 200:
        raise GateFailure("owner-first class exclusion setup failed")
    with factory() as db:
        registration = db.get(StudentRegistration, owner_first["registration"])
        if registration is None:
            raise GateFailure("owner-first class exclusion setup failed")
        owner_token, _row = login_service.rotate_authenticated_session(
            db, registration, now
        )
    _copy_cookie(
        ceremony_client,
        name=settings.auth_session_cookie_name,
        value=owner_token,
        path="/",
    )
    denied_exchange = _public_result(
        _exchange(ceremony_client, f"owner-first-exchange-{owner_first_marker}")
    )
    ceremony_client.close()

    with factory() as db:
        mentor_first_active = db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id == mentor_first["mentor"],
                MentorSession.state == "active",
            )
        )
        owner_first_mentor = db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id == owner_first["mentor"]
            )
        )
        owner_first_owner = db.scalar(
            select(func.count()).select_from(AuthSession).where(
                AuthSession.user_id == owner_first["student"],
                AuthSession.status == "active",
            )
        )
    if (
        not mentor_first_rejected
        or denied_exchange != (409, "SESSION_CONFLICT")
        or mentor_first_active != 1
        or owner_first_mentor != 0
        or owner_first_owner != 1
    ):
        raise GateFailure("owner/mentor session classes coexisted")
    return {
        "id": ORACLE_IDS[6],
        "status": "PASS",
        "assertions": (
            7
            + recovery_assertions
            + expired_cookie_assertions
            + expired_owner_assertions
        ),
    }


def _session_read_only_idle_boundary_oracle(
    app: FastAPI,
    factory: sessionmaker[Session],
) -> int:
    """Prove session GET neither extends nor races the original idle bound."""

    from app.models.mentor_auth import MentorSession
    from app.services import mentor_ceremony

    client, seeded = _ready_session(app, factory, uuid.uuid4().hex)
    with factory() as db:
        session = db.scalar(
            select(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"],
                MentorSession.state == "active",
            )
        )
        if session is None:
            raise GateFailure("session read-only setup failed")
        session_id = session.id
        original_last_seen = session.last_seen_at
    read = client.get("/api/v1/auth/mentor/session")
    if read.status_code != 200:
        raise GateFailure("canonical mentor session read failed")
    with factory() as db:
        after_read = db.get(MentorSession, session_id)
        if after_read is None or after_read.last_seen_at != original_last_seen:
            raise GateFailure("session GET changed last_seen_at")
        idle_boundary = datetime.now(timezone.utc) - timedelta(
            seconds=mentor_ceremony.settings.mentor_session_idle_ttl_seconds
        )
        after_read.last_seen_at = idle_boundary
        db.commit()

    expired_result = _public_result(client.get("/api/v1/auth/mentor/session"))
    with factory() as db:
        expired = db.get(MentorSession, session_id)
        expired_state = expired.state if expired is not None else None
        expired_last_seen = expired.last_seen_at if expired is not None else None
        terminal_at = expired.terminal_at if expired is not None else None
    client.close()
    if expired_result != (410, "SESSION_EXPIRED"):
        raise GateFailure("original idle boundary did not expire authority")
    if (
        expired_state != "expired"
        or expired_last_seen != idle_boundary
        or terminal_at is None
    ):
        raise GateFailure("idle expiration mutated the original activity boundary")
    return 6


def _rotate_end_race(
    app: FastAPI,
    factory: sessionmaker[Session],
    *,
    operation: str,
    oracle_id: str,
) -> dict[str, Any]:
    from app.models.mentor_auth import MentorSession
    from app.services.mentor_ceremony import SESSION_COOKIE

    read_only_assertions = (
        _session_read_only_idle_boundary_oracle(app, factory)
        if operation == "revoke"
        else 0
    )
    client, seeded = _ready_session(app, factory, uuid.uuid4().hex)
    raw = client.cookies.get(SESSION_COOKIE)
    if not raw:
        raise GateFailure("rotation setup failed")
    barrier = threading.Barrier(2)

    def invoke(candidate: str) -> tuple[int, str]:
        with _client(app) as peer:
            _copy_cookie(peer, name=SESSION_COOKIE, value=raw, path="/")
            barrier.wait(timeout=10)
            body = {
                "expectedSessionState": "active",
                "purposeCode": "student_guidance",
                "reasonCode": (
                    "routine_rotation"
                    if candidate == "rotate"
                    else (
                        "mentor_requested"
                        if candidate == "revoke"
                        else "purpose_complete"
                    )
                ),
            }
            return _public_result(peer.post(
                f"/api/v1/auth/mentor/session/{candidate}",
                headers={"Idempotency-Key": f"{candidate}-{uuid.uuid4().hex}"},
                json=body,
            ))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=30)
            for future in (
                pool.submit(invoke, "rotate"),
                pool.submit(invoke, operation),
            )
        ]
    _assert_bounded_results(
        results,
        allowed={
            (200, "SUCCESS"),
            (410, "AUTHORITY_TERMINAL"),
            (409, "CONCURRENT_STATE_CHANGED"),
        },
    )
    with factory() as db:
        active = db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"],
                MentorSession.state == "active",
            )
        )
        scoped_states = list(
            db.scalars(
                select(MentorSession.state).where(
                    MentorSession.actor_user_id == seeded["mentor"]
                )
            )
        )
    client.close()
    if not any(result == (200, "SUCCESS") for result in results):
        raise GateFailure("rotate/end race had no committed operation")
    if active != 0 or any(state == "active" for state in scoped_states):
        raise GateFailure("rotate/end race retained active authority")
    if len(scoped_states) not in {1, 2}:
        raise GateFailure("rotate/end race cardinality escaped its bound")
    return {
        "id": oracle_id,
        "status": "PASS",
        "assertions": 6 + read_only_assertions,
    }


def _prepare_deletion_operation(
    app: FastAPI,
    factory: sessionmaker[Session],
    *,
    phase: str,
) -> tuple[dict[str, Any], str, str]:
    from app.models.mentor_auth import MentorCeremony
    from app.services.mentor_ceremony import CEREMONY_COOKIE, SESSION_COOKIE

    marker = uuid.uuid4().hex
    client, seeded = _ready_session(app, factory, marker)
    session_token = client.cookies.get(SESSION_COOKIE)
    recovered = client.post(
        "/api/v1/auth/mentor/ceremony/recover",
        headers={"Idempotency-Key": f"delete-recover-{marker}"},
        json={
            "intent": "authority_deletion_step_up",
            "recoveryMethod": "fresh_external_identity",
            "stepUpNoticeVersion": "mentor-authority-deletion.v1",
        },
    )
    # Recovery replaces the original, already-exchanged ceremony capability.
    # The race must exercise the newly issued deletion ceremony, never the
    # stale mentor-session ceremony retained only in the setup dictionary.
    ceremony_token = client.cookies.get(CEREMONY_COOKIE)
    if recovered.status_code != 202 or not session_token or not ceremony_token:
        raise GateFailure("deletion race setup failed")
    with factory() as db:
        deletion = db.scalar(
            select(MentorCeremony)
            .where(
                MentorCeremony.actor_user_id == seeded["mentor"],
                MentorCeremony.intent == "authority_deletion_step_up",
                MentorCeremony.state == "challenge_issued",
            )
            .order_by(MentorCeremony.id)
        )
        if deletion is None:
            raise GateFailure("deletion race setup failed")
        seeded["deletion_ceremony"] = deletion.id
    _settle_exact(
        factory,
        ceremony_id=seeded["deletion_ceremony"],
        provider_subject=seeded["provider_subject"],
        evidence_marker=marker,
    )
    if phase == "exchange":
        verified = _verify(client, f"delete-prepare-verify-{marker}")
        ceremony_token = client.cookies.get(CEREMONY_COOKIE)
        if verified.status_code != 200 or not ceremony_token:
            raise GateFailure("deletion exchange race setup failed")
    client.close()
    return seeded, session_token, ceremony_token


def _deletion_action(
    app: FastAPI,
    *,
    phase: str,
    ceremony_token: str,
    session_token: str,
    marker: str,
) -> tuple[int, str]:
    from app.services.mentor_ceremony import (
        CEREMONY_COOKIE,
        MENTOR_COOKIE_PATH,
        SESSION_COOKIE,
    )

    with _client(app) as client:
        _copy_cookie(
            client,
            name=CEREMONY_COOKIE,
            value=ceremony_token,
            path=MENTOR_COOKIE_PATH,
        )
        if phase == "exchange":
            # Exchange derives the step-up from the still-live mentor session,
            # so this independent contender must carry both server-issued
            # authorities held by the real browser.
            _copy_cookie(
                client,
                name=SESSION_COOKIE,
                value=session_token,
                path="/",
            )
        if phase == "verify":
            response = _verify(client, f"delete-race-verify-{marker}")
        else:
            response = client.post(
                "/api/v1/auth/mentor/ceremony/exchange",
                headers={"Idempotency-Key": f"delete-race-exchange-{marker}"},
                json={
                    "intent": "authority_deletion_step_up",
                    "expectedCeremonyState": "proof_verified",
                    "acceptAuthorityDeletionStepUp": True,
                    "acceptanceTextVersion": "mentor-authority-deletion.v1",
                },
            )
        return _public_result(response)


def _revoke_session(
    app: FastAPI, *, session_token: str, marker: str
) -> tuple[int, str]:
    from app.services.mentor_ceremony import SESSION_COOKIE

    with _client(app) as client:
        _copy_cookie(client, name=SESSION_COOKIE, value=session_token, path="/")
        return _public_result(client.post(
            "/api/v1/auth/mentor/session/revoke",
            headers={"Idempotency-Key": f"delete-race-revoke-{marker}"},
            json={
                "expectedSessionState": "active",
                "purposeCode": "student_guidance",
                "reasonCode": "mentor_requested",
            },
        ))


def _assert_deleted_race_terminal(
    factory: sessionmaker[Session], seeded: dict[str, Any]
) -> None:
    from app.models.mentor_auth import (
        MentorAuthorityStepUp,
        MentorCeremony,
        MentorSession,
    )

    with factory() as db:
        active_sessions = db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"],
                MentorSession.state == "active",
            )
        )
        active_step_ups = db.scalar(
            select(func.count()).select_from(MentorAuthorityStepUp).where(
                MentorAuthorityStepUp.actor_user_id == seeded["mentor"],
                MentorAuthorityStepUp.state == "active",
            )
        )
        deletion_state = db.scalar(
            select(MentorCeremony.state).where(
                MentorCeremony.id == seeded["deletion_ceremony"]
            )
        )
    if (
        active_sessions != 0
        or active_step_ups != 0
        or deletion_state not in {"exchanged", "revoked"}
    ):
        raise GateFailure("deletion race left residual authority")


def _deletion_historical_subject_actor_isolation_oracle(
    app: FastAPI,
    factory: sessionmaker[Session],
) -> int:
    """Reject historical provider-subject actor-isolation traversal.

    Actor A's presented live session is rebound to current subject Y while a
    revoked historical proof retains subject X.  Actor B then owns current X.
    A's authenticated authority deletion must leave every column in B's
    pre-proof graph bit-identical, and B must still be able to verify the
    original ceremony bearer.  No raw bearer or subject reaches evidence.
    """

    from app.core.crypto import keyed_hash
    from app.models.mentor_auth import (
        MentorAuthorityStepUp,
        MentorBootstrapAttempt,
        MentorCeremony,
        MentorInvitation,
        MentorProviderResult,
        MentorSession,
        MentorSubjectConsent,
        TutorProfileOwnershipProof,
    )
    from app.models.registration import User
    from app.models.wave2 import TutorProfile
    from app.services import mentor_ceremony
    from app.services.mentor_ceremony import (
        CEREMONY_COOKIE,
        MENTOR_COOKIE_PATH,
        SESSION_COOKIE,
        STEP_UP_COOKIE,
        STEP_UP_COOKIE_PATH,
        _token_hash,
    )

    marker = uuid.uuid4().hex
    client, seeded = _ready_session(app, factory, marker)
    live_cookie = client.cookies.get(SESSION_COOKIE)
    if not live_cookie:
        raise GateFailure("historical provider-subject actor-isolation setup failed")
    now = datetime.now(timezone.utc)
    subject_x = keyed_hash(seeded["provider_subject"])
    subject_y = keyed_hash(f"native-actor-current-{marker}")
    evidence_y = hashlib.sha256(f"native-actor-evidence-{marker}".encode()).hexdigest()

    with factory() as db:
        current_a = db.get(TutorProfileOwnershipProof, seeded["proof"])
        profile_a = db.get(TutorProfile, seeded["tutor"])
        session_a = db.scalar(
            select(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"],
                MentorSession.state == "active",
            )
        )
        provider_a = db.scalar(
            select(MentorProviderResult).where(
                MentorProviderResult.ceremony_id == seeded["ceremony"],
                MentorProviderResult.state == "consumed",
            )
        )
        invitation_a = db.get(MentorInvitation, seeded["invitation"])
        if any(
            row is None
            for row in (current_a, profile_a, session_a, provider_a, invitation_a)
        ):
            raise GateFailure(
                "historical provider-subject actor-isolation setup failed"
            )

        current_a.provider_subject_hash = subject_y
        current_a.evidence_digest = evidence_y
        provider_a.provider_subject_hash = subject_y
        provider_a.evidence_digest = evidence_y
        invitation_a.mentor_match_hash = subject_y
        db.add(
            TutorProfileOwnershipProof(
                user_id=seeded["mentor"],
                tutor_profile_id=seeded["tutor"],
                provider_class="nyayone_reviewed_identity",
                assurance_class="high",
                policy_version="mentor-proof.v1",
                provider_subject_hash=subject_x,
                evidence_digest=hashlib.sha256(
                    f"native-actor-historical-{marker}".encode()
                ).hexdigest(),
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
            display_name="Native Isolated Mentor",
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
            evidence_digest=hashlib.sha256(
                f"native-actor-b-evidence-{marker}".encode()
            ).hexdigest(),
            key_version="v1",
            state="current",
            issued_at=now,
            expires_at=now + timedelta(days=1),
        )
        invitation_b = MentorInvitation(
            subject_registration_id=seeded["registration"],
            initiator_user_id=seeded["student"],
            initiator_session_hash=keyed_hash(f"native-actor-b-owner-{marker}"),
            creation_idempotency_hash=keyed_hash(
                f"native-actor-b-invitation-{marker}"
            ),
            purpose_policy_version="mentor-purpose-policy.v1",
            mentor_match_hash=subject_x,
            authority_domain_hash=keyed_hash(f"native-actor-b-domain-{marker}"),
            mentor_role="tutor",
            purpose_code="student_guidance",
            consent_version="mentor-consent.v1",
            acceptance_text_version="mentor-acceptance.v1",
            disclosure_classes=["display_identity"],
            state="pending",
            expires_at=now + timedelta(hours=1),
        )
        bootstrap_b = MentorBootstrapAttempt(
            token_hash=keyed_hash(f"native-actor-b-bootstrap-{marker}"),
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
            subject_registration_id=seeded["registration"],
            granted_by_user_id=seeded["student"],
            granting_session_hash=invitation_b.initiator_session_hash,
            grant_idempotency_hash=keyed_hash(
                f"native-actor-b-consent-{marker}"
            ),
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
        raw_b, seed_b, seed_version_b = mentor_ceremony._new_seeded_token(
            "ceremony", ceremony_b_id
        )
        _RUNTIME_SECRET_VALUES.add(raw_b)
        ceremony_b = MentorCeremony(
            id=ceremony_b_id,
            bootstrap_attempt_id=bootstrap_b.id,
            token_hash=_token_hash(raw_b),
            token_seed_ct=seed_b,
            token_seed_key_version=seed_version_b,
            challenge_hash=keyed_hash(f"native-actor-b-challenge-{marker}"),
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
        raw_nonce_b = f"native-actor-b-nonce-{marker}"
        raw_correlation_b = f"native-actor-b-correlation-{marker}"
        _RUNTIME_SECRET_VALUES.update({raw_nonce_b, raw_correlation_b})
        mentor_ceremony._add_provider_transaction(
            db,
            ceremony=ceremony_b,
            requested_role="tutor",
            raw_nonce=raw_nonce_b,
            raw_correlation=raw_correlation_b,
        )
        db.flush()
        provider_b = db.scalar(
            select(MentorProviderResult).where(
                MentorProviderResult.ceremony_id == ceremony_b.id
            )
        )
        if provider_b is None:
            raise GateFailure(
                "historical provider-subject actor-isolation setup failed"
            )
        provider_b.state = "verified"
        provider_b.start_dispatched_at = now
        provider_b.provider_subject_hash = subject_x
        provider_b.evidence_digest = proof_b.evidence_digest
        provider_b.key_version = "v1"
        provider_b.issued_at = now

        step_id = uuid.uuid4()
        raw_step, step_seed, step_seed_version = mentor_ceremony._new_seeded_token(
            "step-up", step_id
        )
        _RUNTIME_SECRET_VALUES.add(raw_step)
        step_up = MentorAuthorityStepUp(
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
                        mentor_ceremony.settings.mentor_retention_notice_version
                    ),
                },
            ),
            state="active",
            issued_at=now,
            expires_at=now + timedelta(minutes=5),
        )
        db.add(step_up)
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

    def snapshot_b() -> dict[str, dict[str, Any]]:
        with factory() as db:
            return {
                name: {
                    column.name: getattr(row, column.name)
                    for column in model.__table__.columns
                }
                for name, model in b_models.items()
                if (row := db.get(model, b_ids[name])) is not None
            }

    before_b = snapshot_b()
    if set(before_b) != set(b_models):
        raise GateFailure("historical provider-subject actor-isolation setup failed")
    client.cookies.clear()
    _copy_cookie(client, name=SESSION_COOKIE, value=live_cookie, path="/")
    _copy_cookie(
        client,
        name=STEP_UP_COOKIE,
        value=raw_step,
        path=STEP_UP_COOKIE_PATH,
    )
    deleted = client.request(
        "DELETE",
        "/api/v1/auth/mentor/authority",
        headers={"Idempotency-Key": f"native-cross-actor-delete-{marker}"},
        json={
            "expectedSessionState": "active",
            "expectedStepUpIntent": "authority_deletion_step_up",
            "confirmation": "delete_mentor_authority",
            "retentionNoticeVersion": "mentor-retention.v1",
        },
    )
    if deleted.status_code != 202:
        raise GateFailure("historical provider-subject actor-isolation failed")
    if snapshot_b() != before_b:
        raise GateFailure("unrelated actor graph changed during authority deletion")

    with factory() as db:
        active_a = int(
            db.scalar(
                select(func.count()).select_from(MentorSession).where(
                    MentorSession.actor_user_id == seeded["mentor"],
                    MentorSession.state == "active",
                )
            )
            or 0
        )
    if active_a != 0:
        raise GateFailure("deleted actor retained live authority")

    client.cookies.clear()
    _copy_cookie(
        client,
        name=CEREMONY_COOKIE,
        value=raw_b,
        path=MENTOR_COOKIE_PATH,
    )
    b_verified = _verify(client, f"native-actor-b-verify-{marker}")
    client.close()
    if (
        b_verified.status_code != 200
        or b_verified.json().get("ceremonyState") != "proof_verified"
    ):
        raise GateFailure("unrelated actor authority was not usable after deletion")
    return 8


def _deletion_race(
    app: FastAPI,
    factory: sessionmaker[Session],
    *,
    phase: str,
    oracle_id: str,
) -> dict[str, Any]:
    expected_action_success = (200, "SUCCESS")
    terminal_action_results = {
        (403, "AUTHORIZATION_DENIED"),
        (409, "CONCURRENT_STATE_CHANGED"),
        # Revoking the source session also retires its pending deletion
        # ceremony.  Presenting that now-terminal ceremony is the sealed,
        # public replay outcome—not a successful continuation.
        (409, "CEREMONY_REPLAYED"),
        (410, "AUTHORITY_TERMINAL"),
    }
    assertions = (
        _deletion_historical_subject_actor_isolation_oracle(app, factory)
        if phase == "exchange"
        else 0
    )

    # Deterministically exercise both committed lock orders, then exercise a
    # real two-connection race.  This makes branch coverage independent of the
    # runner scheduler while retaining a true PostgreSQL concurrency oracle.
    for order in ("action_first", "revoke_first"):
        seeded, session_token, ceremony_token = _prepare_deletion_operation(
            app, factory, phase=phase
        )
        marker = uuid.uuid4().hex
        if order == "action_first":
            action = _deletion_action(
                app,
                phase=phase,
                ceremony_token=ceremony_token,
                session_token=session_token,
                marker=marker,
            )
            ended = _revoke_session(
                app, session_token=session_token, marker=marker
            )
            if action != expected_action_success or ended != (200, "SUCCESS"):
                raise GateFailure("action-first deletion ordering failed")
        else:
            ended = _revoke_session(
                app, session_token=session_token, marker=marker
            )
            action = _deletion_action(
                app,
                phase=phase,
                ceremony_token=ceremony_token,
                session_token=session_token,
                marker=marker,
            )
            if ended != (200, "SUCCESS"):
                raise GateFailure("revocation-first deletion end did not commit")
            if action not in terminal_action_results:
                raise GateFailure(
                    "revocation-first deletion action escaped the sealed outcome: "
                    f"{action[0]}:{action[1]}"
                )
        _assert_deleted_race_terminal(factory, seeded)
        assertions += 4

    seeded, session_token, ceremony_token = _prepare_deletion_operation(
        app, factory, phase=phase
    )
    barrier = threading.Barrier(2)
    marker = uuid.uuid4().hex

    def action_worker() -> tuple[int, str]:
        barrier.wait(timeout=10)
        return _deletion_action(
            app,
            phase=phase,
            ceremony_token=ceremony_token,
            session_token=session_token,
            marker=f"action-{marker}",
        )

    def revoke_worker() -> tuple[int, str]:
        barrier.wait(timeout=10)
        return _revoke_session(
            app,
            session_token=session_token,
            marker=f"revoke-{marker}",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        action_future = pool.submit(action_worker)
        revoke_future = pool.submit(revoke_worker)
        action_result = action_future.result(timeout=30)
        revoke_result = revoke_future.result(timeout=30)
    _assert_bounded_results(
        [action_result, revoke_result],
        allowed={expected_action_success, (200, "SUCCESS")} | terminal_action_results,
    )
    if revoke_result != (200, "SUCCESS") or action_result not in (
        {expected_action_success} | terminal_action_results
    ):
        raise GateFailure("concurrent deletion ordering failed")
    _assert_deleted_race_terminal(factory, seeded)
    return {"id": oracle_id, "status": "PASS", "assertions": assertions + 6}


def _restriction_race(
    app: FastAPI,
    factory: sessionmaker[Session],
    *,
    restriction: str,
    oracle_id: str,
) -> dict[str, Any]:
    from app.models.mentor_auth import (
        MentorSession,
        MentorSubjectConsent,
        TutorProfileOwnershipProof,
    )

    client, seeded = _ready_session(app, factory, uuid.uuid4().hex)
    locked = threading.Event()
    release = threading.Event()

    def revoke_authority() -> None:
        with factory() as db:
            model = (
                TutorProfileOwnershipProof
                if restriction == "proof"
                else MentorSubjectConsent
            )
            identifier = (
                seeded["proof"]
                if restriction == "proof"
                else seeded["subject_consent"]
            )
            row = db.scalar(
                select(model)
                .where(model.id == identifier)
                .with_for_update()
            )
            if row is None:
                raise GateFailure("restriction setup failed")
            locked.set()
            release.wait(timeout=10)
            if restriction == "proof":
                row.state = "revoked"
            else:
                row.status = "revoked"
            row.revoked_at = datetime.now(timezone.utc)
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(revoke_authority)
        if not locked.wait(timeout=10):
            raise GateFailure("restriction lock was unavailable")
        if restriction == "proof":
            reader = pool.submit(
                lambda: _public_result(client.post(
                    "/api/v1/auth/mentor/session/rotate",
                    headers={
                        "Idempotency-Key": f"proof-restriction-{uuid.uuid4().hex}"
                    },
                    json={
                        "expectedSessionState": "active",
                        "purposeCode": "student_guidance",
                        "reasonCode": "routine_rotation",
                    },
                ))
            )
        else:
            reader = pool.submit(
                lambda: _public_result(
                    client.get("/api/v1/auth/mentor/session")
                )
            )
        release.set()
        writer.result(timeout=20)
        result = reader.result(timeout=20)
    with factory() as db:
        active = db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"],
                MentorSession.state == "active",
            )
        )
        rows = db.scalar(
            select(func.count()).select_from(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"]
            )
        )
    client.close()
    if result != (403, "AUTHORIZATION_DENIED") or active != 1 or rows != 1:
        raise GateFailure("restriction did not win the authority race")
    return {"id": oracle_id, "status": "PASS", "assertions": 4}


def _retention_models() -> dict[str, Any]:
    from app.models.mentor_auth import (
        MentorAuditLink,
        MentorAuthorityStepUp,
        MentorBootstrapAttempt,
        MentorCeremony,
        MentorConsent,
        MentorEngagement,
        MentorIdempotencyRecord,
        MentorInvitation,
        MentorProviderResult,
        MentorSession,
        MentorSubjectConsent,
        TutorProfileOwnershipProof,
    )

    return {
        "bootstraps": MentorBootstrapAttempt,
        "invitations": MentorInvitation,
        "proofs": TutorProfileOwnershipProof,
        "ceremonies": MentorCeremony,
        "provider_results": MentorProviderResult,
        "subject_consents": MentorSubjectConsent,
        "engagements": MentorEngagement,
        "mentor_consents": MentorConsent,
        "sessions": MentorSession,
        "step_ups": MentorAuthorityStepUp,
        "idempotency": MentorIdempotencyRecord,
        "audit_links": MentorAuditLink,
    }


def _retention_sensitive_fields() -> dict[str, tuple[str, ...]]:
    return {
        "bootstraps": ("token_hash",),
        "invitations": (
            "initiator_session_hash",
            "creation_idempotency_hash",
            "mentor_match_hash",
            "authority_domain_hash",
        ),
        "proofs": ("provider_subject_hash", "evidence_digest"),
        "ceremonies": ("token_hash", "challenge_hash"),
        "provider_results": (
            "issuer_hash",
            "audience_hash",
            "nonce_hash",
            "correlation_hash",
            "provider_subject_hash",
            "evidence_digest",
        ),
        "subject_consents": (
            "granting_session_hash",
            "grant_idempotency_hash",
        ),
        "engagements": ("authority_domain_hash",),
        "sessions": ("authority_domain_hash", "token_hash"),
        "step_ups": ("token_hash", "fingerprint"),
        "idempotency": (
            "scope_hash",
            "idempotency_key_hash",
            "request_fingerprint",
        ),
        "audit_links": ("correlation_hash",),
    }


def _retention_link_fields() -> dict[str, tuple[str, ...]]:
    return {
        "invitations": ("subject_registration_id", "initiator_user_id"),
        "proofs": ("user_id", "tutor_profile_id"),
        "ceremonies": (
            "bootstrap_attempt_id",
            "actor_user_id",
            "tutor_profile_id",
            "ownership_proof_id",
            "invitation_id",
        ),
        "provider_results": ("ceremony_id",),
        "subject_consents": (
            "invitation_id",
            "subject_registration_id",
            "granted_by_user_id",
            "guardian_consent_id",
        ),
        "engagements": (
            "invitation_id",
            "subject_registration_id",
            "mentor_user_id",
            "tutor_profile_id",
        ),
        "mentor_consents": ("engagement_id",),
        "sessions": (
            "ceremony_id",
            "engagement_id",
            "actor_user_id",
            "tutor_profile_id",
            "ownership_proof_id",
            "consent_id",
            "subject_consent_id",
            "successor_id",
        ),
        "step_ups": ("ceremony_id", "actor_user_id", "mentor_session_id"),
    }


def _terminal_authority_graph(
    app: FastAPI,
    factory: sessionmaker[Session],
    *,
    oversize_sessions: int = 0,
    live_expired_session: bool = False,
) -> dict[str, Any]:
    """Create one closed, old, still-linked authority graph for retention."""

    from app.core.crypto import active_key_version, encrypt, keyed_hash
    from app.db.models.audit import AuditEvent
    from app.models.mentor_auth import (
        MentorAuthorityStepUp,
        MentorIdempotencyRecord,
        MentorSession,
    )
    from app.services import mentor_ceremony

    marker = uuid.uuid4().hex
    from app.services.mentor_ceremony import SESSION_COOKIE

    client, seeded = _ready_session(app, factory, marker)
    session_token = client.cookies.get(SESSION_COOKIE)
    ceremony_token = seeded.get("ceremony_token")
    if not session_token or not ceremony_token:
        raise GateFailure("retention graph bearer setup failed")
    _RUNTIME_SECRET_VALUES.update({session_token, ceremony_token})
    client.close()
    current = datetime.now(timezone.utc)
    old = current - timedelta(days=400)
    with factory() as db:
        session = db.scalar(
            select(MentorSession).where(
                MentorSession.actor_user_id == seeded["mentor"],
                MentorSession.ceremony_id == seeded["ceremony"],
            )
        )
        if session is None:
            raise GateFailure("retention graph setup failed")
        domain = session.authority_domain_hash
        owner_scope = mentor_ceremony._scope_hash(
            "owner-create-mentor-prerequisites",
            f"owner-invitation:{seeded['invitation']}",
            {},
        )
        owner_record = MentorIdempotencyRecord(
            scope_hash=owner_scope,
            operation="owner-create-mentor-prerequisites",
            idempotency_key_hash=keyed_hash(
                f"native-retention-owner-key-{marker}"
            ),
            request_fingerprint=keyed_hash(
                f"native-retention-owner-request-{marker}"
            ),
            state="succeeded",
            outcome_status=201,
            outcome_ct=encrypt(
                json.dumps(
                    {
                        "invitationBinding": str(seeded["invitation"]),
                        "consentBinding": str(seeded["subject_consent"]),
                    },
                    sort_keys=True,
                )
            ),
            key_version=active_key_version(),
            created_at=old,
            updated_at=old,
        )
        db.add(owner_record)
        db.add(
            MentorAuthorityStepUp(
                ceremony_id=session.ceremony_id,
                actor_user_id=session.actor_user_id,
                mentor_session_id=session.id,
                token_hash=keyed_hash(f"native-retention-step-up-{marker}"),
                token_seed_ct=None,
                token_seed_key_version=None,
                intent="authority_deletion_step_up",
                fingerprint=keyed_hash(
                    f"native-retention-fingerprint-{marker}"
                ),
                state="expired",
                issued_at=old - timedelta(minutes=10),
                expires_at=old - timedelta(minutes=5),
                consumed_at=old,
                retention_class="mentor_step_up_security",
                updated_at=old,
            )
        )
        for index in range(oversize_sessions):
            db.add(
                MentorSession(
                    ceremony_id=session.ceremony_id,
                    engagement_id=session.engagement_id,
                    actor_user_id=session.actor_user_id,
                    tutor_profile_id=session.tutor_profile_id,
                    ownership_proof_id=session.ownership_proof_id,
                    consent_id=session.consent_id,
                    subject_consent_id=session.subject_consent_id,
                    authority_domain_hash=domain,
                    token_hash=keyed_hash(
                        f"native-retention-oversize-{marker}-{index}"
                    ),
                    token_seed_ct=None,
                    token_seed_key_version=None,
                    mentor_role=session.mentor_role,
                    purpose_code=session.purpose_code,
                    scopes=list(session.scopes),
                    permitted_profile_slices=list(
                        session.permitted_profile_slices
                    ),
                    state="deleted",
                    generation=index + 2,
                    issued_at=old - timedelta(hours=2),
                    last_seen_at=old - timedelta(hours=2),
                    expires_at=old - timedelta(hours=1),
                    terminal_at=old,
                    retention_class="mentor_session_security",
                    updated_at=old,
                )
            )
        db.commit()

    with factory() as db:
        graph = mentor_ceremony._load_authority_domain_graph(db, domain)
        required = set(_retention_models())
        if set(graph) != required or any(not graph[name] for name in required):
            raise GateFailure("retention graph inventory was incomplete")
        if not any(
            row.operation == "owner-create-mentor-prerequisites"
            for row in graph["idempotency"]
        ):
            raise GateFailure(
                "owner prerequisite idempotency ledger was not graph-bound"
            )
        for row in graph["bootstraps"]:
            row.state = "expired"
            row.consumed_at = old
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["invitations"]:
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["proofs"]:
            row.state = "deleted"
            row.revoked_at = old
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["ceremonies"]:
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["provider_results"]:
            row.state = "expired"
            row.consumed_at = old
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["subject_consents"]:
            row.status = "deleted"
            row.revoked_at = old
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["engagements"]:
            row.state = "deleted"
            row.terminal_at = old
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["mentor_consents"]:
            row.status = "deleted"
            row.revoked_at = old
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["sessions"]:
            if live_expired_session and row.id == session.id:
                row.state = "active"
                row.issued_at = old - timedelta(hours=2)
                row.last_seen_at = old - timedelta(hours=1)
                row.expires_at = old
                row.terminal_at = None
            else:
                row.state = "deleted"
                row.terminal_at = old
            row.successor_id = None
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["step_ups"]:
            row.state = "expired"
            row.consumed_at = old
            row.updated_at = old
            row.metadata_json = {"classification": "native-retention-fixture"}
        for row in graph["idempotency"]:
            row.updated_at = old
        for row in graph["audit_links"]:
            row.expires_at = old
        db.commit()

        graph = mentor_ceremony._load_authority_domain_graph(db, domain)
        ids = {name: [row.id for row in rows] for name, rows in graph.items()}
        old_digests = {
            str(getattr(row, field))
            for name, fields in _retention_sensitive_fields().items()
            for row in graph[name]
            for field in fields
            if getattr(row, field, None) is not None
        }
        audit_count = int(
            db.scalar(select(func.count()).select_from(AuditEvent)) or 0
        )
    return {
        "current": current,
        "domain": domain,
        "ids": ids,
        "old_digests": old_digests,
        "audit_count": audit_count,
        # Process-only inputs used by the native subject-erasure race proof.
        # They are included in the runtime-secret scan set above and are never
        # serialized into the privacy-safe producer report.
        "session_token": session_token,
        "ceremony_token": ceremony_token,
        "external_ids": (
            seeded["student"],
            seeded["registration"],
            seeded["mentor"],
            seeded["tutor"],
        ),
    }


def _retention_snapshot(
    factory: sessionmaker[Session], context: dict[str, Any]
) -> dict[str, tuple[tuple[tuple[str, str], ...], ...]]:
    snapshot: dict[str, tuple[tuple[tuple[str, str], ...], ...]] = {}
    with factory() as db:
        for name, model in _retention_models().items():
            rows = list(
                db.scalars(
                    select(model)
                    .where(model.id.in_(context["ids"][name]))
                    .order_by(model.id)
                )
            )
            snapshot[name] = tuple(
                tuple(
                    (column.name, repr(getattr(row, column.name)))
                    for column in model.__table__.columns
                )
                for row in rows
            )
    return snapshot


def _retention_advisory_oracle(
    factory: sessionmaker[Session],
) -> dict[str, Any]:
    from app.services import mentor_ceremony

    holder = factory()
    contender = factory()
    blocked = False
    try:
        holder.execute(select(func.pg_advisory_xact_lock(0x4E59415922)))
        try:
            mentor_ceremony.run_mentor_retention(contender)
        except mentor_ceremony.MentorCeremonyError as exc:
            blocked = (
                exc.status_code == 409
                and exc.code == "CONCURRENT_STATE_CHANGED"
                and exc.retryable is True
            )
    finally:
        contender.rollback()
        contender.close()
        holder.rollback()
        holder.close()
    if not blocked:
        raise GateFailure("retention overlap was not refused")
    return {"id": ORACLE_IDS[13], "status": "PASS", "assertions": 3}


def _retention_graph_is_fully_severed(
    factory: sessionmaker[Session], context: dict[str, Any]
) -> bool:
    """Read back one exact graph without authorizing through its old links."""

    with factory() as db:
        for name, model in _retention_models().items():
            rows = list(
                db.scalars(
                    select(model)
                    .where(model.id.in_(context["ids"][name]))
                    .order_by(model.id)
                )
            )
            if len(rows) != len(context["ids"][name]):
                return False
            for row in rows:
                if any(
                    getattr(row, field) is not None
                    for field in _retention_link_fields().get(name, ())
                ):
                    return False
                if name == "idempotency":
                    if (
                        row.state != "erased"
                        or row.outcome_status is not None
                        or row.outcome_ct is not None
                        or row.key_version is not None
                    ):
                        return False
                elif name == "audit_links":
                    if (
                        row.erased_at is None
                        or row.link_key_ct is not None
                        or row.actor_link_ct is not None
                        or row.key_version is not None
                    ):
                        return False
                elif row.deleted_at is None:
                    return False
    return True


def _retention_live_expiry_same_run_proof(
    app: FastAPI,
    factory: sessionmaker[Session],
) -> int:
    """Materialize an elapsed live session and sever its graph in one run."""

    from app.models.mentor_auth import MentorIdempotencyRecord
    from app.services import mentor_ceremony

    context = _terminal_authority_graph(
        app,
        factory,
        live_expired_session=True,
    )
    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=context["current"],
            batch_size=min(
                256, mentor_ceremony.settings.mentor_retention_batch_size
            ),
        )
    if (
        counts.get("materialized_expirations", 0) < 1
        or counts.get("severed_graphs") != 1
        or counts.get("blocked_graphs") != 0
        or not _retention_graph_is_fully_severed(factory, context)
    ):
        raise GateFailure("live expiry was not severed in the same retention run")
    with factory() as db:
        owner_records = list(
            db.scalars(
                select(MentorIdempotencyRecord).where(
                    MentorIdempotencyRecord.id.in_(
                        context["ids"]["idempotency"]
                    ),
                    MentorIdempotencyRecord.operation
                    == "owner-create-mentor-prerequisites",
                )
            )
        )
    if (
        len(owner_records) != 1
        or owner_records[0].state != "erased"
        or owner_records[0].outcome_status is not None
        or owner_records[0].outcome_ct is not None
        or owner_records[0].key_version is not None
    ):
        raise GateFailure("owner prerequisite idempotency erasure was incomplete")
    return 7


def _retention_held_node_atomicity_proof(
    app: FastAPI, factory: sessionmaker[Session]
) -> int:
    """Prove a contended node cannot be omitted from a severed graph.

    The worker must first acquire the shared authority-domain serialization,
    then PostgreSQL may wait on the independently held graph row.  Readiness is
    observed from ``pg_stat_activity`` rather than inferred from a sleep.  Once
    released, the result must be full severance or a bit-identical rollback;
    a subset is never an accepted state.
    """

    from app.models.mentor_auth import MentorInvitation
    from app.services import mentor_ceremony

    context = _terminal_authority_graph(app, factory)
    before = _retention_snapshot(factory, context)
    invitation_id = context["ids"]["invitations"][0]
    holder = factory()
    worker_started = threading.Event()
    worker_pid: list[int] = []
    outcome: dict[str, Any] = {}

    def worker() -> None:
        with factory() as db:
            worker_pid.append(int(db.scalar(text("SELECT pg_backend_pid()"))))
            worker_started.set()
            try:
                outcome["counts"] = mentor_ceremony.run_mentor_retention(
                    db,
                    now=context["current"],
                    batch_size=min(
                        256, mentor_ceremony.settings.mentor_retention_batch_size
                    ),
                )
            except Exception as exc:  # kept in memory; never emitted as evidence
                outcome["exception"] = exc

    try:
        held = holder.scalar(
            select(MentorInvitation)
            .where(MentorInvitation.id == invitation_id)
            .with_for_update()
        )
        if held is None:
            raise GateFailure("retention contention fixture was unavailable")
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        if not worker_started.wait(timeout=5):
            raise GateFailure("retention contention worker did not start")

        observed_lock_wait = False
        deadline = time.monotonic() + 5
        with factory() as observer:
            while time.monotonic() < deadline:
                wait_event_type = observer.scalar(
                    text(
                        "SELECT wait_event_type FROM pg_stat_activity "
                        "WHERE pid = :pid"
                    ),
                    {"pid": worker_pid[0]},
                )
                if wait_event_type == "Lock":
                    observed_lock_wait = True
                    break
                threading.Event().wait(0.01)
        if not observed_lock_wait:
            raise GateFailure("retention row-lock settlement was not observed")
        holder.rollback()
        thread.join(timeout=20)
        if thread.is_alive():
            raise GateFailure("retention contention worker did not settle")
    finally:
        holder.rollback()
        holder.close()

    after = _retention_snapshot(factory, context)
    exception = outcome.get("exception")
    if isinstance(exception, DBAPIError):
        if _sqlstate(exception) in {"40P01", "57014", "55P03"}:
            raise GateFailure("retention contention reached a forbidden SQL state")
    if exception is None:
        counts = outcome.get("counts", {})
        if (
            counts.get("severed_graphs") != 1
            or counts.get("blocked_graphs") != 0
            or not _retention_graph_is_fully_severed(factory, context)
        ):
            raise GateFailure("retention contention did not sever the full graph")
    elif not (
        isinstance(exception, mentor_ceremony.MentorCeremonyError)
        and exception.status_code == 409
        and exception.code == "CONCURRENT_STATE_CHANGED"
        and exception.retryable is True
        and after == before
    ):
        raise GateFailure("retention contention was neither full nor bit-identical")
    if after != before and not _retention_graph_is_fully_severed(factory, context):
        raise GateFailure("retention contention partially severed an authority graph")
    return 8


def _retention_orphan_erasure_proof(
    app: FastAPI, factory: sessionmaker[Session]
) -> int:
    """Prove bounded post-window erasure of both pre-authority orphan shapes."""

    from app.core.crypto import keyed_hash
    from app.models.mentor_auth import (
        MentorBootstrapAttempt,
        MentorCeremony,
        MentorIdempotencyRecord,
        MentorProviderResult,
        MentorSubjectConsent,
        TutorProfileOwnershipProof,
    )
    from app.models.mentor_auth import MentorInvitation
    from app.services import mentor_ceremony

    marker = uuid.uuid4().hex
    seeded = _seed(factory, marker)
    client = _client(app)
    try:
        if _initiate(
            client,
            seeded["bootstrap"],
            f"orphan-initiate-{marker}-0001",
        ).status_code != 202:
            raise GateFailure("orphan retention fixture initiation failed")
    finally:
        client.close()

    current = datetime.now(timezone.utc)
    old = current - timedelta(days=400)
    unused_raw = f"orphan-unused-bootstrap-{marker}"
    _RUNTIME_SECRET_VALUES.add(unused_raw)
    with factory() as db:
        bootstrap = db.get(MentorBootstrapAttempt, seeded["bootstrap_id"])
        ceremony = db.scalar(
            select(MentorCeremony).where(
                MentorCeremony.bootstrap_attempt_id == seeded["bootstrap_id"]
            )
        )
        if bootstrap is None or ceremony is None:
            raise GateFailure("orphan retention fixture graph was unavailable")
        provider = db.scalar(
            select(MentorProviderResult).where(
                MentorProviderResult.ceremony_id == ceremony.id
            )
        )
        scope_hash = mentor_ceremony._scope_hash(
            "initiate", f"bootstrap:{bootstrap.id}", {}
        )
        record = db.scalar(
            select(MentorIdempotencyRecord).where(
                MentorIdempotencyRecord.scope_hash == scope_hash
            )
        )
        if provider is None or record is None:
            raise GateFailure("orphan retention fixture evidence was unavailable")
        unused = MentorBootstrapAttempt(
            token_hash=keyed_hash(unused_raw),
            requested_role="tutor",
            purpose_code="student_guidance",
            state="expired",
            expires_at=old - timedelta(minutes=1),
            consumed_at=old,
        )
        db.add(unused)
        bootstrap.consumed_at = old
        bootstrap.expires_at = old - timedelta(minutes=1)
        bootstrap.updated_at = old
        ceremony.state = "expired"
        ceremony.expires_at = old - timedelta(minutes=1)
        ceremony.terminal_at = old
        ceremony.updated_at = old
        provider.state = "expired"
        provider.expires_at = old - timedelta(minutes=1)
        provider.consumed_at = old
        provider.updated_at = old
        record.updated_at = old
        db.commit()
        linked_bootstrap_id = bootstrap.id
        unused_bootstrap_id = unused.id
        ceremony_id = ceremony.id
        provider_id = provider.id
        record_id = record.id
        old_digests = {
            bootstrap.token_hash,
            unused.token_hash,
            ceremony.token_hash,
            ceremony.challenge_hash,
            provider.issuer_hash,
            provider.audience_hash,
            provider.nonce_hash,
            provider.correlation_hash,
            record.scope_hash,
            record.idempotency_key_hash,
            record.request_fingerprint,
        }

    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=current,
            batch_size=min(
                256, mentor_ceremony.settings.mentor_retention_batch_size
            ),
        )
    if (
        counts.get("severed_graphs") != 2
        or counts.get("blocked_graphs") != 0
        or counts.get("bootstraps") != 2
        or counts.get("ceremonies") != 1
        or counts.get("provider_results") != 1
        or counts.get("idempotency") != 1
    ):
        raise GateFailure("orphan retention did not consume its bounded inventory")

    with factory() as db:
        bootstraps = [
            db.get(MentorBootstrapAttempt, linked_bootstrap_id),
            db.get(MentorBootstrapAttempt, unused_bootstrap_id),
        ]
        ceremony = db.get(MentorCeremony, ceremony_id)
        provider = db.get(MentorProviderResult, provider_id)
        record = db.get(MentorIdempotencyRecord, record_id)
        invitation = db.get(MentorInvitation, seeded["invitation"])
        proof = db.get(TutorProfileOwnershipProof, seeded["proof"])
        subject_consent = db.get(
            MentorSubjectConsent, seeded["subject_consent"]
        )
        if (
            any(row is None for row in bootstraps)
            or ceremony is None
            or provider is None
            or record is None
            or invitation is None
            or proof is None
            or subject_consent is None
        ):
            raise GateFailure("orphan retention deleted a durable record")
        new_digests = {
            *(row.token_hash for row in bootstraps if row is not None),
            ceremony.token_hash,
            ceremony.challenge_hash,
            provider.issuer_hash,
            provider.audience_hash,
            provider.nonce_hash,
            provider.correlation_hash,
            record.scope_hash,
            record.idempotency_key_hash,
            record.request_fingerprint,
        }
        fully_erased = (
            all(row is not None and row.deleted_at is not None for row in bootstraps)
            and ceremony.deleted_at is not None
            and ceremony.bootstrap_attempt_id is None
            and ceremony.token_seed_ct is None
            and ceremony.token_seed_key_version is None
            and provider.deleted_at is not None
            and provider.ceremony_id is None
            and provider.nonce_ct is None
            and provider.correlation_ct is None
            and provider.transaction_key_version is None
            and record.state == "erased"
            and record.outcome_status is None
            and record.outcome_ct is None
            and record.key_version is None
        )
        unrelated_preserved = (
            invitation.deleted_at is None
            and invitation.subject_registration_id is not None
            and proof.deleted_at is None
            and proof.user_id is not None
            and proof.tutor_profile_id is not None
            and subject_consent.deleted_at is None
            and subject_consent.invitation_id == invitation.id
        )
        residual_joins = int(
            db.scalar(
                select(func.count()).select_from(MentorCeremony).where(
                    MentorCeremony.bootstrap_attempt_id.in_(
                        (linked_bootstrap_id, unused_bootstrap_id)
                    )
                )
            )
            or 0
        ) + int(
            db.scalar(
                select(func.count()).select_from(MentorProviderResult).where(
                    MentorProviderResult.ceremony_id == ceremony_id
                )
            )
            or 0
        )
    if (
        not fully_erased
        or not unrelated_preserved
        or residual_joins != 0
        or old_digests & new_digests
        or len(new_digests) != 11
        or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in new_digests)
    ):
        raise GateFailure("orphan retention erasure boundary was incomplete")
    return 14


def _nyay19_subject_erasure_authority_oracle(
    app: FastAPI, factory: sessionmaker[Session]
) -> int:
    """Prove NYAY-19 subject erasure cannot leave mentor authority.

    Both registration dispositions are raced, on independent database
    connections, against each externally reachable terminal-authority path.
    The subject graph must be wholly severed before the registration mutation
    commits, while a second subject graph remains byte-for-byte unchanged.
    A stale bearer may observe either the already-terminal record or the
    post-severance absence, but it may never recover authority or reach a 5xx.
    """

    from app.core import retention
    from app.models.mentor_auth import MentorSession
    from app.models.registration import StudentRegistration
    from app.services.mentor_ceremony import (
        CEREMONY_COOKIE,
        MENTOR_COOKIE_PATH,
        SESSION_COOKIE,
    )

    assertions = 0
    allowed_terminal = {
        (401, "AUTHENTICATION_REQUIRED"),
        (409, "CONCURRENT_STATE_CHANGED"),
        (410, "AUTHORITY_TERMINAL"),
    }

    for mode in ("anonymise", "delete"):
        for operation in ("rotate", "read", "exchange"):
            subject = _terminal_authority_graph(app, factory)
            unrelated = _terminal_authority_graph(app, factory)
            unrelated_before = _retention_snapshot(factory, unrelated)
            registration_id = subject["external_ids"][1]
            barrier = threading.Barrier(2)

            def erase_subject() -> str:
                with factory() as db:
                    db.execute(text("SET LOCAL lock_timeout = '5s'"))
                    db.execute(text("SET LOCAL statement_timeout = '15s'"))
                    registration = db.get(StudentRegistration, registration_id)
                    if registration is None:
                        raise GateFailure("NYAY-19 subject erasure setup failed")
                    barrier.wait(timeout=10)
                    if mode == "anonymise":
                        retention.anonymise_registration(db, registration)
                    else:
                        retention.delete_registration(db, registration)
                    db.commit()
                return "COMMITTED"

            def exercise_bearer() -> tuple[int, str]:
                with _client(app) as client:
                    if operation == "exchange":
                        _copy_cookie(
                            client,
                            name=CEREMONY_COOKIE,
                            value=subject["ceremony_token"],
                            path=MENTOR_COOKIE_PATH,
                        )
                    else:
                        _copy_cookie(
                            client,
                            name=SESSION_COOKIE,
                            value=subject["session_token"],
                            path="/",
                        )
                    barrier.wait(timeout=10)
                    if operation == "read":
                        response = client.get("/api/v1/auth/mentor/session")
                    elif operation == "rotate":
                        response = client.post(
                            "/api/v1/auth/mentor/session/rotate",
                            headers={
                                "Idempotency-Key": (
                                    f"nyay19-erasure-rotate-{uuid.uuid4().hex}"
                                )
                            },
                            json={
                                "expectedSessionState": "active",
                                "purposeCode": "student_guidance",
                                "reasonCode": "routine_rotation",
                            },
                        )
                    else:
                        response = _exchange(
                            client,
                            f"nyay19-erasure-exchange-{uuid.uuid4().hex}",
                        )
                    return _public_result(response)

            with ThreadPoolExecutor(max_workers=2) as pool:
                erasure_future = pool.submit(erase_subject)
                bearer_future = pool.submit(exercise_bearer)
                try:
                    erasure_result = erasure_future.result(timeout=30)
                    bearer_result = bearer_future.result(timeout=30)
                except DBAPIError as exc:
                    if _sqlstate(exc) in {"40P01", "57014", "55P03"}:
                        raise GateFailure(
                            "NYAY-19 subject erasure deadlocked or timed out"
                        ) from None
                    raise

            if erasure_result != "COMMITTED" or bearer_result not in allowed_terminal:
                raise GateFailure(
                    "NYAY-19 subject erasure escaped sealed outcomes: "
                    f"{mode}:{operation}:{bearer_result[0]}:{bearer_result[1]}"
                )
            if bearer_result[0] >= 500:
                raise GateFailure("NYAY-19 subject erasure reached server failure")
            if not _retention_graph_is_fully_severed(factory, subject):
                raise GateFailure("NYAY-19 subject erasure left mentor authority")
            if _retention_snapshot(factory, unrelated) != unrelated_before:
                raise GateFailure("unrelated subject changed during NYAY-19 erasure")

            # Retire the untouched control graph only after the byte-equality
            # assertion.  This keeps later global-retention oracle cardinality
            # exact without weakening the cross-subject isolation proof.
            with factory() as db:
                control_registration = db.get(
                    StudentRegistration, unrelated["external_ids"][1]
                )
                if control_registration is None:
                    raise GateFailure("unrelated subject control disappeared")
                retention.anonymise_registration(db, control_registration)
                db.commit()
            if not _retention_graph_is_fully_severed(factory, unrelated):
                raise GateFailure("unrelated subject control cleanup failed")

            with factory() as db:
                registration = db.get(StudentRegistration, registration_id)
                active = int(
                    db.scalar(
                        select(func.count()).select_from(MentorSession).where(
                            MentorSession.id.in_(subject["ids"]["sessions"]),
                            MentorSession.state == "active",
                        )
                    )
                    or 0
                )
            if active != 0:
                raise GateFailure("NYAY-19 subject erasure left mentor authority")
            if mode == "anonymise":
                if registration is None or registration.status != "deleted":
                    raise GateFailure("NYAY-19 anonymise did not commit")
            elif registration is not None:
                raise GateFailure("NYAY-19 delete did not commit")
            assertions += 8

    return assertions


def _retention_atomic_oracle(
    app: FastAPI, factory: sessionmaker[Session]
) -> dict[str, Any]:
    from app.db.models.audit import AuditEvent
    from app.models.mentor_auth import MentorAuditLink, MentorIdempotencyRecord
    from app.models.registration import StudentRegistration, User
    from app.models.wave2 import TutorProfile
    from app.services import mentor_ceremony

    live_expiry_assertions = _retention_live_expiry_same_run_proof(app, factory)
    held_node_assertions = _retention_held_node_atomicity_proof(app, factory)
    orphan_assertions = _retention_orphan_erasure_proof(app, factory)
    subject_erasure_assertions = _nyay19_subject_erasure_authority_oracle(app, factory)
    context = _terminal_authority_graph(app, factory)
    before = _retention_snapshot(factory, context)
    real_tombstone = mentor_ceremony._retention_tombstone
    calls = 0

    def injected_failure(label: str) -> str:
        nonlocal calls
        calls += 1
        if calls == 7:
            raise RuntimeError("privacy-safe injected retention failure")
        return real_tombstone(label)

    mentor_ceremony._retention_tombstone = injected_failure
    rolled_back = False
    try:
        with factory() as db:
            try:
                mentor_ceremony.run_mentor_retention(
                    db,
                    now=context["current"],
                    batch_size=min(
                        256, mentor_ceremony.settings.mentor_retention_batch_size
                    ),
                )
            except RuntimeError:
                rolled_back = True
    finally:
        mentor_ceremony._retention_tombstone = real_tombstone
    if not rolled_back or _retention_snapshot(factory, context) != before:
        raise GateFailure("retention mid-severance rollback was not atomic")

    with factory() as db:
        counts = mentor_ceremony.run_mentor_retention(
            db,
            now=context["current"],
            batch_size=min(
                256, mentor_ceremony.settings.mentor_retention_batch_size
            ),
        )
    if counts.get("severed_graphs") != 1 or counts.get("blocked_graphs") != 0:
        raise GateFailure("eligible retention graph was not severed exactly once")

    new_digests: list[str] = []
    with factory() as db:
        for name, model in _retention_models().items():
            rows = list(
                db.scalars(
                    select(model)
                    .where(model.id.in_(context["ids"][name]))
                    .order_by(model.id)
                )
            )
            if len(rows) != len(context["ids"][name]):
                raise GateFailure("retention deleted an authority record")
            for row in rows:
                for field in _retention_link_fields().get(name, ()):
                    if getattr(row, field) is not None:
                        raise GateFailure("retention left a joinable authority link")
                if hasattr(row, "metadata_json") and row.metadata_json is not None:
                    raise GateFailure("retention preserved identifying metadata")
                for field in _retention_sensitive_fields().get(name, ()):
                    value = getattr(row, field)
                    if not isinstance(value, str) or re.fullmatch(
                        r"[0-9a-f]{64}", value
                    ) is None:
                        raise GateFailure("retention tombstone shape was invalid")
                    new_digests.append(value)
                if name not in {"idempotency", "audit_links"} and row.deleted_at is None:
                    raise GateFailure("retention row was not marked severed")

        idempotency = list(
            db.scalars(
                select(MentorIdempotencyRecord).where(
                    MentorIdempotencyRecord.id.in_(context["ids"]["idempotency"])
                )
            )
        )
        audit_links = list(
            db.scalars(
                select(MentorAuditLink).where(
                    MentorAuditLink.id.in_(context["ids"]["audit_links"])
                )
            )
        )
        if any(
            row.state != "erased"
            or row.outcome_status is not None
            or row.outcome_ct is not None
            or row.key_version is not None
            for row in idempotency
        ):
            raise GateFailure("retention preserved idempotency authority")
        if any(
            row.link_key_ct is not None
            or row.actor_link_ct is not None
            or row.key_version is not None
            or row.erased_at is None
            for row in audit_links
        ):
            raise GateFailure("retention did not crypto-erase reversible audit links")
        audit_count = int(
            db.scalar(select(func.count()).select_from(AuditEvent)) or 0
        )
        student, registration, mentor, tutor = context["external_ids"]
        external_present = all(
            row is not None
            for row in (
                db.get(User, student),
                db.get(StudentRegistration, registration),
                db.get(User, mentor),
                db.get(TutorProfile, tutor),
            )
        )
    if (
        context["old_digests"] & set(new_digests)
        or len(new_digests) != len(set(new_digests))
        or audit_count != context["audit_count"]
        or not external_present
    ):
        raise GateFailure("retention erasure boundary was incomplete")
    return {
        "id": ORACLE_IDS[14],
        "status": "PASS",
        "assertions": (
            12
            + live_expiry_assertions
            + held_node_assertions
            + orphan_assertions
            + subject_erasure_assertions
        ),
    }


def _retention_oversize_oracle(
    app: FastAPI, factory: sessionmaker[Session]
) -> dict[str, Any]:
    from app.models.mentor_auth import MentorRetentionBlockedGraph, MentorSession
    from app.services import mentor_ceremony

    # One elapsed-but-not-yet-materialized live row proves the hard cap is
    # checked against the whole graph before *any* state transition.  The
    # blocked register is the only durable mutation allowed for this graph.
    context = _terminal_authority_graph(
        app,
        factory,
        oversize_sessions=256,
        live_expired_session=True,
    )
    before = _retention_snapshot(factory, context)
    limit = min(256, mentor_ceremony.settings.mentor_retention_batch_size)
    with factory() as db:
        first = mentor_ceremony.run_mentor_retention(
            db, now=context["current"], batch_size=limit
        )
    after_first = _retention_snapshot(factory, context)
    with factory() as db:
        alert = db.scalar(
            select(MentorRetentionBlockedGraph).where(
                MentorRetentionBlockedGraph.state == "open"
            )
        )
        alerts = int(
            db.scalar(
                select(func.count()).select_from(MentorRetentionBlockedGraph)
            )
            or 0
        )
        linked = int(
            db.scalar(
                select(func.count()).select_from(MentorSession).where(
                    MentorSession.id.in_(context["ids"]["sessions"]),
                    MentorSession.actor_user_id.is_not(None),
                    MentorSession.deleted_at.is_(None),
                )
            )
            or 0
        )
    if (
        first.get("materialized_expirations", 0) != 0
        or
        first.get("severed_graphs") != 0
        or first.get("blocked_graphs") != 1
        or after_first != before
        or alert is None
        or alerts != 1
        or alert.reason_code != "GRAPH_EXCEEDS_HARD_CAP"
        or alert.observed_row_count <= 256
        or alert.review_queue != "nyay19_retention_review"
        or alert.occurrence_count != 1
        or re.fullmatch(r"[0-9a-f]{64}", alert.graph_key_hash) is None
        or alert.graph_key_hash == context["domain"]
        or linked != len(context["ids"]["sessions"])
    ):
        raise GateFailure("oversize retention graph did not fail closed")
    with factory() as db:
        second = mentor_ceremony.run_mentor_retention(
            db, now=context["current"], batch_size=limit
        )
    with factory() as db:
        occurrence = db.scalar(
            select(MentorRetentionBlockedGraph.occurrence_count)
        )
        alerts_after = int(
            db.scalar(
                select(func.count()).select_from(MentorRetentionBlockedGraph)
            )
            or 0
        )
    if (
        second.get("severed_graphs") != 0
        or second.get("blocked_graphs") != 1
        or occurrence != 2
        or alerts_after != 1
        or _retention_snapshot(factory, context) != before
    ):
        raise GateFailure("oversize retention alert was not durable and idempotent")
    return {"id": ORACLE_IDS[15], "status": "PASS", "assertions": 12}


def _privacy_oracle(
    engine: Engine,
    factory: sessionmaker[Session],
    known_secrets: set[str],
) -> dict[str, Any]:
    from app.db.models.audit import AuditEvent
    from app.models.mentor_auth import MentorAuditLink

    with factory() as db:
        audit_count = db.scalar(select(func.count()).select_from(AuditEvent))
        link_count = db.scalar(select(func.count()).select_from(MentorAuditLink))
    leaked = False
    inspector = inspect(engine)
    with engine.connect() as connection:
        for table in inspector.get_table_names():
            text_columns = [
                column["name"]
                for column in inspector.get_columns(table)
                if any(part in str(column["type"]).upper() for part in ("CHAR", "TEXT", "JSON"))
            ]
            for column in text_columns:
                values = connection.execute(
                    text(f'SELECT "{column}"::text FROM "{table}" WHERE "{column}" IS NOT NULL')
                )
                if any(secret and secret in str(value[0]) for value in values for secret in known_secrets):
                    leaked = True
                    break
            if leaked:
                break
    if leaked or not audit_count or not link_count:
        raise GateFailure("credential or audit privacy oracle failed")
    return {"id": ORACLE_IDS[16], "status": "PASS", "assertions": 3}


def _validate_report(report: dict[str, Any]) -> None:
    expected_report_fields = {
        "schema_version",
        "status",
        "classification",
        "postgres_major",
        "pgvector_present",
        "oracles",
        "summary",
    }
    rows = report.get("oracles", [])
    if (
        set(report) != expected_report_fields
        or report.get("schema_version") != SCHEMA_VERSION
        or report.get("status") != "PASS"
        or report.get("classification") != "EXECUTED"
        or report.get("postgres_major") != 16
        or report.get("pgvector_present") is not True
        or not isinstance(rows, list)
        or any(
            not isinstance(row, dict)
            or set(row) != {"id", "status", "assertions"}
            or row.get("status") != "PASS"
            or type(row.get("assertions")) is not int
            or row.get("assertions", 0) <= 0
            for row in rows
        )
        or [row.get("id") for row in rows] != list(ORACLE_IDS)
        or report.get("summary") != {"passed": len(ORACLE_IDS), "total": len(ORACLE_IDS)}
    ):
        raise GateFailure("report contract failed")
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":"))
    for key in FORBIDDEN_REPORT_KEYS:
        if re.search(rf'"{re.escape(key)}"\s*:', encoded, re.IGNORECASE):
            raise GateFailure("report privacy contract failed")


def _contract_check() -> dict[str, Any]:
    document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if document != {
        "schemaVersion": SCHEMA_VERSION,
        "producer": "backend/scripts/nyay22_postgres_mentor_gate.py",
        "optInEnvironment": OPT_IN_ENV,
        "oracleInventory": list(ORACLE_IDS),
        "oracleCount": len(ORACLE_IDS),
        "applicationHead": APPLICATION_HEAD,
        "previousRevision": PREVIOUS_REVISION,
    }:
        raise Blocked("the NYAY-22 PostgreSQL contract is unavailable")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "classification": "CONTRACT_CHECK_ONLY",
        "oracle_count": len(ORACLE_IDS),
        "executed": False,
    }


def run(control_raw: str, output: Path) -> dict[str, Any]:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise Blocked("the NYAY-22 PostgreSQL gate is not explicitly enabled")
    control = _safe_control_url(control_raw)
    scratch = f"{SCRATCH_PREFIX}{uuid.uuid4().hex[:12]}"
    _drop(control, scratch)
    try:
        _admin(control, f'CREATE DATABASE "{scratch}"')
        database_url = _database_url(control, scratch)
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        finally:
            engine.dispose()
        oracle_by_id = {
            ORACLE_IDS[0]: _migration_oracle(database_url),
        }
        engine = create_engine(database_url, poolclass=NullPool)
        factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
        app = _app(factory)
        _RUNTIME_SECRET_VALUES.clear()

        # Retention runs first on a clean migrated database so its exact graph
        # cardinality and rollback proofs cannot be diluted by another oracle.
        for row in (
            _retention_advisory_oracle(factory),
            _retention_atomic_oracle(app, factory),
            _retention_oversize_oracle(app, factory),
        ):
            oracle_by_id[row["id"]] = row

        bounds = _postgres_bounds_oracle(factory)
        oracle_by_id[bounds["id"]] = bounds
        for row in _idempotency_oracles(app, factory):
            oracle_by_id[row["id"]] = row
        for row in (
            _provider_subject_unique_race(factory),
            _exchange_race(app, factory),
            _owner_exclusion(app, factory),
            _rotate_end_race(
                app,
                factory,
                operation="revoke",
                oracle_id=ORACLE_IDS[7],
            ),
            _rotate_end_race(
                app,
                factory,
                operation="logout",
                oracle_id=ORACLE_IDS[8],
            ),
            _deletion_race(
                app,
                factory,
                phase="verify",
                oracle_id=ORACLE_IDS[9],
            ),
            _deletion_race(
                app,
                factory,
                phase="exchange",
                oracle_id=ORACLE_IDS[10],
            ),
            _restriction_race(
                app,
                factory,
                restriction="proof",
                oracle_id=ORACLE_IDS[11],
            ),
            _restriction_race(
                app,
                factory,
                restriction="subject_consent",
                oracle_id=ORACLE_IDS[12],
            ),
        ):
            oracle_by_id[row["id"]] = row
        privacy = _privacy_oracle(
            engine, factory, set(_RUNTIME_SECRET_VALUES)
        )
        oracle_by_id[privacy["id"]] = privacy
        if set(oracle_by_id) != set(ORACLE_IDS):
            raise GateFailure("native oracle inventory was incomplete")
        oracles = [oracle_by_id[oracle_id] for oracle_id in ORACLE_IDS]
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "PASS",
            "classification": "EXECUTED",
            "postgres_major": 16,
            "pgvector_present": True,
            "oracles": oracles,
            "summary": {"passed": len(oracles), "total": len(ORACLE_IDS)},
        }
        _validate_report(report)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        engine.dispose()
        return report
    finally:
        try:
            _drop(control, scratch)
        except Exception as exc:
            raise GateFailure("disposable database cleanup failed") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--contract-check", action="store_true")
    args = parser.parse_args()
    try:
        if args.contract_check:
            print(json.dumps(_contract_check(), sort_keys=True))
            return 0
        if not args.database_url or args.output is None:
            raise Blocked("database URL and output path are required")
        report = run(args.database_url, args.output)
        print(json.dumps({"status": report["status"], "oracle_count": len(ORACLE_IDS)}, sort_keys=True))
        return 0
    except Blocked:
        print(json.dumps({"status": "BLOCKED", "code": "NYAY22_POSTGRES_PREREQUISITE"}, sort_keys=True))
        return BLOCKED_EXIT
    except Exception:
        print(json.dumps({"status": "FAIL", "code": "NYAY22_POSTGRES_GATE_FAILED"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
