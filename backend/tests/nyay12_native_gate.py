"""NYAY-12 native verified-email identity gate (PostgreSQL 16 + pgvector).

Lives under ``backend/tests`` like the other env-gated native PostgreSQL checks
(``WAVE3_POSTGRES_TEST``, ``SAATHI60_POSTGRES_TEST_URL``); wiring a producer copy
into ``backend/scripts/db_gate.sh`` requires the sealed Alembic-caller inventory
in ``scripts/ci/verify_nyayone_ci.py`` and is an owner/governance change.

The producer creates a uniquely named disposable database on a literal loopback
control server, migrates it through the real Alembic CLI, and exercises the
production ``email_identity_service`` under real concurrent schedules. Evidence
contains only closed-world oracle identifiers and aggregate counts; no address,
code or token is ever written. Exit 0 = PASS, 1 = FAIL, 78 = BLOCKED.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid
from typing import Any

from sqlalchemy import create_engine, func, make_url, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SCHEMA_VERSION = "nyay12-email-identity-postgres/v1"
OPT_IN_ENV = "NYAY12_POSTGRES_GATE"
BLOCKED_EXIT = 78
PREVIOUS_REVISION = "0024_nyay11_authority_state"
APPLICATION_HEAD = "0025_nyay12_email_identity"
ORACLE_IDS = (
    "MIGRATION_UP_DOWN_UP_CHECK",
    "MIGRATION_LEGACY_DUPLICATE_RECONCILIATION",
    "PARTIAL_UNIQUE_INDEXES_ENFORCED",
    "CONCURRENT_PRIMARY_EXACTLY_ONE",
    "VERIFY_RACE_SINGLE_OWNER",
    "REMOVE_REPLAY_NO_REBIND",
    "CROSS_OWNER_DENIAL",
    "EMAIL_LOGIN_NON_ENUMERATING_AND_UNVERIFIED_DENIED",
    "POPULATED_DOWNGRADE_REFUSED",
)


class Blocked(RuntimeError):
    """A prerequisite is unavailable; no executed PASS may be emitted."""


class GateFailure(RuntimeError):
    """A privacy-safe native execution or assertion failure."""


class CapturingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._receipts: dict[str, tuple[str, str, str]] = {}
        self._lock = threading.Lock()

    def send_idempotent(self, destination: str, code: str, *, idempotency_token: str) -> str:
        with self._lock:
            existing = self._receipts.get(idempotency_token)
            if existing is not None:
                return existing[2]
            receipt = f"native-{len(self._receipts) + 1}"
            self._receipts[idempotency_token] = (destination, code, receipt)
            self.sent.append((destination, code))
            return receipt

    def code_for(self, destination: str) -> str:
        with self._lock:
            for sent_to, code in reversed(self.sent):
                if sent_to == destination:
                    return code
        raise GateFailure("DELIVERY_NOT_CAPTURED")


def opt_in_enabled(environment: dict[str, str]) -> bool:
    return environment.get(OPT_IN_ENV) == "1"


def blocked_report(code: str) -> dict[str, Any]:
    return {"status": "BLOCKED", "code": code, "executed": False}


def safe_control_url(raw: str) -> URL:
    if any(
        name in os.environ for name in (
            "PGHOST", "PGHOSTADDR", "PGPORT", "PGDATABASE", "PGUSER",
            "PGPASSWORD", "PGPASSFILE", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS",
        )
    ) or any(name.startswith("PGSSL") for name in os.environ):
        raise Blocked("NATIVE_AMBIENT_ROUTING_DENIED")
    try:
        if "://" not in raw:
            raise ValueError("no scheme")
        authority = re.split(r"[/?#]", raw.split("://", 1)[1], maxsplit=1)[0]
        if "%" in authority or authority.count("@") > 1:
            raise ValueError("ambiguous authority")
        parsed = make_url(raw)
        address = ipaddress.ip_address(parsed.host or "")
        if parsed.get_backend_name() != "postgresql" or parsed.query or not address.is_loopback:
            raise ValueError("nonlocal or nonnative")
    except Exception as exc:
        raise Blocked("NATIVE_LOOPBACK_POSTGRES_REQUIRED") from exc
    return parsed


def _require(condition: bool, code: str) -> None:
    if condition is not True:
        raise GateFailure(code)


def validate_report(report: dict[str, Any]) -> None:
    expected_keys = {
        "schema_version", "status", "executed", "postgres_major", "pgvector_present",
        "rows", "total", "passed", "failed", "scratch_cleanup",
    }
    _require(isinstance(report, dict) and set(report) == expected_keys, "REPORT_SHAPE_INVALID")
    _require(report["schema_version"] == SCHEMA_VERSION and report["status"] == "PASS", "REPORT_VERDICT_INVALID")
    _require(report["executed"] is True and report["scratch_cleanup"] is True, "REPORT_UNEXECUTED")
    _require(type(report["postgres_major"]) is int and report["postgres_major"] == 16, "REPORT_RUNTIME_INVALID")
    _require(report["pgvector_present"] is True, "REPORT_RUNTIME_INVALID")
    expected_counts = {"total": len(ORACLE_IDS), "passed": len(ORACLE_IDS), "failed": 0}
    _require(all(type(report[key]) is int and report[key] == value for key, value in expected_counts.items()), "REPORT_COUNT_INVALID")
    rows = report["rows"]
    _require(isinstance(rows, list) and len(rows) == len(ORACLE_IDS), "REPORT_INVENTORY_INVALID")
    _require(all(isinstance(row, dict) and set(row) == {"id", "passed", "assertions"} for row in rows), "REPORT_ROW_SHAPE_INVALID")
    _require(tuple(row["id"] for row in rows) == ORACLE_IDS, "REPORT_INVENTORY_INVALID")
    _require(all(row["passed"] is True and type(row["assertions"]) is int and row["assertions"] > 0 for row in rows), "REPORT_ASSERTION_INVALID")


def _row(identifier: str, assertions: int) -> dict[str, Any]:
    _require(identifier in ORACLE_IDS and type(assertions) is int and assertions > 0, "ORACLE_ROW_INVALID")
    return {"id": identifier, "passed": True, "assertions": assertions}


def _database_url(control: URL, name: str) -> str:
    return control.set(database=name).render_as_string(hide_password=False)


def _admin(control: URL, statement: str) -> None:
    engine = create_engine(_database_url(control, "postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with engine.connect() as connection:
            connection.execute(text(statement))
    finally:
        engine.dispose()


def _alembic(database_url: str, *arguments: str, expect_failure: str | None = None) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments], cwd=BACKEND,
        env={**os.environ, "APP_ENV": "testing", "DATABASE_URL": database_url,
             "PYTHONDONTWRITEBYTECODE": "1", "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=240, check=False,
    )
    if expect_failure is not None:
        _require(result.returncode != 0 and expect_failure in result.stdout, "MIGRATION_REFUSAL_MISSING")
        return
    _require(result.returncode == 0, "MIGRATION_LIFECYCLE_FAILED")


def _migration_roundtrip(database_url: str) -> dict[str, Any]:
    _alembic(database_url, "upgrade", APPLICATION_HEAD)
    _alembic(database_url, "check")
    _alembic(database_url, "downgrade", PREVIOUS_REVISION)
    _alembic(database_url, "upgrade", APPLICATION_HEAD)
    _alembic(database_url, "check")
    return _row("MIGRATION_UP_DOWN_UP_CHECK", 5)


def _legacy_duplicate_oracle(control: URL) -> dict[str, Any]:
    """A second scratch database: seed duplicated legacy hashes at 0024, upgrade."""

    from app.core.crypto import encrypt, keyed_hash

    scratch = f"nyay12_legacy_{uuid.uuid4().hex[:12]}"
    _admin(control, f'CREATE DATABASE "{scratch}"')
    try:
        database_url = _database_url(control, scratch)
        engine = create_engine(database_url, poolclass=NullPool)
        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            _alembic(database_url, "upgrade", PREVIOUS_REVISION)
            shared = keyed_hash(f"legacy-shared-{uuid.uuid4().hex}")
            unique = keyed_hash(f"legacy-unique-{uuid.uuid4().hex}")
            with engine.begin() as connection:
                for email_hash, deleted in ((shared, False), (shared, False), (shared, True), (unique, False), (None, False)):
                    user_id, registration_id, profile_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
                    marker = uuid.uuid4().hex
                    connection.execute(text("INSERT INTO users (id, role, status, created_at, updated_at) VALUES (:id, 'student', 'active', now(), now())"), {"id": user_id})
                    connection.execute(
                        text(
                            "INSERT INTO student_registrations (id, user_id, first_name, last_name, mobile_hash, mobile_ct, dob_hash, dob_ct, dob_hash_state, key_version, status, is_minor, created_at, updated_at) "
                            "VALUES (:id, :user_id, 'Legacy', 'Duplicate', :mobile_hash, :mobile_ct, :dob_hash, :dob_ct, 'verified', 'v1', 'active', false, now(), now())"
                        ),
                        {"id": registration_id, "user_id": user_id, "mobile_hash": keyed_hash(marker), "mobile_ct": encrypt(marker), "dob_hash": keyed_hash("2000-01-01"), "dob_ct": encrypt("2000-01-01")},
                    )
                    connection.execute(
                        text("INSERT INTO student_profiles (id, registration_id, institutional_email_hash, deleted_at, created_at, updated_at) VALUES (:id, :registration_id, :email_hash, :deleted_at, now(), now())"),
                        {"id": profile_id, "registration_id": registration_id, "email_hash": email_hash, "deleted_at": datetime.now(timezone.utc) if deleted else None},
                    )
            _alembic(database_url, "upgrade", APPLICATION_HEAD)
            with engine.connect() as connection:
                rows = connection.execute(text("SELECT email_hash, reason, state, holder_user_id, claimant_user_id FROM email_identity_reconciliations")).all()
                _require(len(rows) == 1 and rows[0][0] == shared and rows[0][1] == "legacy_duplicate" and rows[0][2] == "open", "LEGACY_RECONCILIATION_INVALID")
                _require(rows[0][3] is None and rows[0][4] is None, "LEGACY_RECONCILIATION_LEAKS_ACTOR")
                _require(connection.scalar(text("SELECT count(*) FROM user_email_identities")) == 0, "LEGACY_MIGRATION_VERIFIED_SOMETHING")
            _alembic(database_url, "downgrade", PREVIOUS_REVISION, expect_failure="email_identity_downgrade_requires_empty_graph")
            with engine.connect() as connection:
                _require(connection.scalar(text("SELECT version_num FROM alembic_version")) == APPLICATION_HEAD, "POPULATED_DOWNGRADE_MUTATED_HEAD")
                _require(connection.scalar(text("SELECT count(*) FROM email_identity_reconciliations")) == 1, "POPULATED_DOWNGRADE_LOST_LEDGER")
        finally:
            engine.dispose()
    finally:
        _admin(control, f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
    return _row("MIGRATION_LEGACY_DUPLICATE_RECONCILIATION", 6)


def _seed_actor(session: Session, *, minor: bool = False) -> dict[str, Any]:
    from app.core.crypto import encrypt, keyed_hash
    from app.models.registration import AuthSession, StudentProfile, StudentRegistration, User

    now = datetime.now(timezone.utc)
    born = date(now.year - (16 if minor else 25), 1, 1)
    marker = uuid.uuid4().hex
    token = f"native-email-identity-session-{marker}"
    user = User(role="student", status="active")
    session.add(user)
    session.flush()
    registration = StudentRegistration(
        user_id=user.id, first_name="Synthetic", last_name="Identity",
        mobile_hash=keyed_hash(f"native-mobile-{marker}"), mobile_ct=encrypt(f"native-mobile-{marker}"),
        dob_hash=keyed_hash(born.isoformat()), dob_ct=encrypt(born.isoformat()),
        dob_hash_state="verified", key_version="v1", status="active", is_minor=minor,
    )
    session.add(registration)
    session.flush()
    session.add(StudentProfile(registration_id=registration.id, profile_version=1))
    session.add(AuthSession(user_id=user.id, token_hash=keyed_hash(token), status="active", expires_at=now + timedelta(hours=1), last_seen_at=now))
    session.flush()
    return {"actor_id": user.id, "registration_id": registration.id, "token": token, "now": now}


def _add_verified(factory, sender: CapturingSender, actor: dict[str, Any], email: str) -> uuid.UUID:
    from app.services import email_identity_service as service

    with factory() as session:
        _, body, _ = service.add_identity(session, actor["actor_id"], actor["token"], email=email, sender=sender, key=f"native-add-{uuid.uuid4().hex[:20]}", client_ip="127.0.0.1", now=actor["now"])
    identity_id = uuid.UUID(body["identity"]["id"])
    with factory() as session:
        _, body, _ = service.verify_identity(session, actor["actor_id"], actor["token"], identity_id=identity_id, code=sender.code_for(email), key=f"native-verify-{uuid.uuid4().hex[:20]}", now=actor["now"])
    _require(body["identity"]["state"] == "verified", "VERIFY_DID_NOT_PERSIST")
    return identity_id


def _partial_unique_oracle(factory) -> dict[str, Any]:
    from sqlalchemy.exc import IntegrityError
    from app.core.crypto import encrypt, keyed_hash
    from app.models.email_identity import UserEmailIdentity

    with factory.begin() as session:
        a, b = _seed_actor(session), _seed_actor(session)
    email_hash = keyed_hash(f"native-shared-{uuid.uuid4().hex}")
    now = datetime.now(timezone.utc)

    def row(user_id, *, state, primary, hash_value=email_hash):
        return UserEmailIdentity(user_id=user_id, email_hash=hash_value, email_ct=encrypt("x@example.test"), key_version="v1", state=state, is_primary=primary, verified_at=now if state == "verified" else None, verification_state="none", attempts=0)

    with factory.begin() as session:
        session.add(row(a["actor_id"], state="verified", primary=True))
    violations = 0
    for candidate in (
        row(b["actor_id"], state="verified", primary=False),                                  # second verified owner
        row(a["actor_id"], state="verified", primary=True, hash_value=keyed_hash("other-1")),  # second primary
        row(b["actor_id"], state="pending", primary=True, hash_value=keyed_hash("other-2")),   # primary without verified
    ):
        with factory() as session:
            session.add(candidate)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                violations += 1
    _require(violations == 3, "PARTIAL_UNIQUE_INDEX_NOT_ENFORCED")
    with factory.begin() as session:
        session.add(row(b["actor_id"], state="pending", primary=False))  # a pending claim by another user is allowed
    with factory() as session:
        session.add(row(b["actor_id"], state="pending", primary=False))
        try:
            session.commit()
            raise GateFailure("DUPLICATE_LIVE_CLAIM_ACCEPTED")
        except IntegrityError:
            session.rollback()
    return _row("PARTIAL_UNIQUE_INDEXES_ENFORCED", 5)


def _concurrent_primary_oracle(factory, sender: CapturingSender) -> dict[str, Any]:
    from app.models.email_identity import UserEmailIdentity
    from app.services import email_identity_service as service

    with factory.begin() as session:
        actor = _seed_actor(session)
    ids = [_add_verified(factory, sender, actor, f"native-primary-{index}-{uuid.uuid4().hex[:8]}@example.test") for index in range(3)]
    barrier = threading.Barrier(6, timeout=30)

    def promote(identity_id: uuid.UUID) -> str:
        with factory() as session:
            barrier.wait()
            try:
                service.set_primary(session, actor["actor_id"], actor["token"], identity_id=identity_id, key=f"native-primary-{uuid.uuid4().hex[:20]}", now=actor["now"])
                return "primary"
            except service.EmailIdentityError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(promote, ids * 2))
    _require(all(outcome in {"primary", "email_identity_state_conflict"} for outcome in outcomes), "CONCURRENT_PRIMARY_UNTYPED_OUTCOME")
    _require(outcomes.count("primary") >= 1, "CONCURRENT_PRIMARY_NO_WINNER")
    with factory() as session:
        primaries = session.scalar(select(func.count()).select_from(UserEmailIdentity).where(UserEmailIdentity.user_id == actor["actor_id"], UserEmailIdentity.is_primary.is_(True)))
        _require(primaries == 1, "CONCURRENT_PRIMARY_NOT_EXACTLY_ONE")
    return _row("CONCURRENT_PRIMARY_EXACTLY_ONE", 3)


def _verify_race_oracle(factory, sender: CapturingSender) -> dict[str, Any]:
    from app.models.email_identity import EmailIdentityReconciliation, UserEmailIdentity
    from app.services import email_identity_service as service

    with factory.begin() as session:
        a, b = _seed_actor(session), _seed_actor(session)
    email = f"native-race-{uuid.uuid4().hex[:8]}@example.test"
    claims = {}
    for actor in (a, b):
        with factory() as session:
            _, body, _ = service.add_identity(session, actor["actor_id"], actor["token"], email=email, sender=sender, key=f"native-add-{uuid.uuid4().hex[:20]}", client_ip="127.0.0.1", now=actor["now"])
        claims[actor["actor_id"]] = (uuid.UUID(body["identity"]["id"]), sender.sent[-1][1])
    barrier = threading.Barrier(2, timeout=30)

    def verify(actor: dict[str, Any]) -> str:
        identity_id, code = claims[actor["actor_id"]]
        with factory() as session:
            barrier.wait()
            try:
                service.verify_identity(session, actor["actor_id"], actor["token"], identity_id=identity_id, code=code, key=f"native-verify-{uuid.uuid4().hex[:20]}", now=actor["now"])
                return "verified"
            except service.EmailIdentityError as exc:
                session.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(verify, (a, b)))
    _require(outcomes == ["email_identity_conflict", "verified"], "VERIFY_RACE_OUTCOMES_INVALID")
    with factory() as session:
        verified = session.scalar(select(func.count()).select_from(UserEmailIdentity).where(UserEmailIdentity.state == "verified", UserEmailIdentity.email_hash == session.scalar(select(UserEmailIdentity.email_hash).where(UserEmailIdentity.id == claims[a["actor_id"]][0]))))
        _require(verified == 1, "VERIFY_RACE_TWO_OWNERS")
        reconciliations = session.scalar(select(func.count()).select_from(EmailIdentityReconciliation).where(EmailIdentityReconciliation.reason == "verified_collision"))
        _require(reconciliations == 1, "VERIFY_RACE_RECONCILIATION_MISSING")
    return _row("VERIFY_RACE_SINGLE_OWNER", 3)


def _remove_replay_oracle(factory, sender: CapturingSender) -> dict[str, Any]:
    from app.models.email_identity import UserEmailIdentity
    from app.services import email_identity_service as service

    with factory.begin() as session:
        a, b = _seed_actor(session), _seed_actor(session)
    email = f"native-replay-{uuid.uuid4().hex[:8]}@example.test"
    with factory() as session:
        _, body, _ = service.add_identity(session, a["actor_id"], a["token"], email=email, sender=sender, key=f"native-add-{uuid.uuid4().hex[:20]}", client_ip="127.0.0.1", now=a["now"])
    a_identity, a_code = uuid.UUID(body["identity"]["id"]), sender.sent[-1][1]
    with factory() as session:
        service.remove_identity(session, a["actor_id"], a["token"], identity_id=a_identity, key=f"native-remove-{uuid.uuid4().hex[:20]}", now=a["now"])
    b_identity = _add_verified(factory, sender, b, email)
    denied = 0
    for actor, identity_id, code in ((a, a_identity, a_code), (a, b_identity, a_code), (a, b_identity, sender.code_for(email))):
        with factory() as session:
            try:
                service.verify_identity(session, actor["actor_id"], actor["token"], identity_id=identity_id, code=code, key=f"native-verify-{uuid.uuid4().hex[:20]}", now=actor["now"])
            except service.EmailIdentityError as exc:
                session.rollback()
                _require(exc.code == "email_identity_not_found", "REPLAY_ERROR_NOT_CANONICAL")
                denied += 1
    _require(denied == 3, "REPLAY_AFTER_REMOVAL_ACCEPTED")
    with factory() as session:
        rows = session.scalars(select(UserEmailIdentity).where(UserEmailIdentity.state == "verified")).all()
        _require([row.id for row in rows if row.user_id == b["actor_id"]] == [b_identity], "REPLAY_REBOUND_ANOTHER_OWNER")
        _require(session.get(UserEmailIdentity, a_identity).state == "removed", "REMOVED_IDENTITY_RESURRECTED")
    return _row("REMOVE_REPLAY_NO_REBIND", 5)


def _cross_owner_oracle(factory, sender: CapturingSender) -> dict[str, Any]:
    from app.models.email_identity import EmailIdentityMutation, UserEmailIdentity
    from app.services import email_identity_service as service

    with factory.begin() as session:
        a, b = _seed_actor(session), _seed_actor(session)
    b_identity = _add_verified(factory, sender, b, f"native-cross-{uuid.uuid4().hex[:8]}@example.test")
    with factory() as session:
        before = (session.scalar(select(func.count()).select_from(UserEmailIdentity)), session.scalar(select(func.count()).select_from(EmailIdentityMutation)))
    attempts = (
        lambda s: service.verify_identity(s, a["actor_id"], a["token"], identity_id=b_identity, code="000000", key=f"native-x-{uuid.uuid4().hex[:20]}", now=a["now"]),
        lambda s: service.resend_identity(s, a["actor_id"], a["token"], identity_id=b_identity, sender=sender, key=f"native-x-{uuid.uuid4().hex[:20]}", client_ip="127.0.0.1", now=a["now"]),
        lambda s: service.remove_identity(s, a["actor_id"], a["token"], identity_id=b_identity, key=f"native-x-{uuid.uuid4().hex[:20]}", now=a["now"]),
        lambda s: service.set_primary(s, a["actor_id"], a["token"], identity_id=b_identity, key=f"native-x-{uuid.uuid4().hex[:20]}", now=a["now"]),
        lambda s: service.set_primary(s, a["actor_id"], None, identity_id=b_identity, key=f"native-x-{uuid.uuid4().hex[:20]}", now=a["now"]),
    )
    codes = []
    for attempt in attempts:
        with factory() as session:
            try:
                attempt(session)
                raise GateFailure("CROSS_OWNER_MUTATION_ACCEPTED")
            except service.EmailIdentityError as exc:
                session.rollback()
                codes.append(exc.code)
    _require(codes == ["email_identity_not_found"] * 4 + ["authentication_required"], "CROSS_OWNER_ERROR_NOT_CANONICAL")
    with factory() as session:
        after = (session.scalar(select(func.count()).select_from(UserEmailIdentity)), session.scalar(select(func.count()).select_from(EmailIdentityMutation)))
        _require(before == after, "CROSS_OWNER_DENIAL_MUTATED_STATE")
        _require(session.get(UserEmailIdentity, b_identity).is_primary is True, "CROSS_OWNER_DENIAL_CHANGED_PRIMARY")
    return _row("CROSS_OWNER_DENIAL", 7)


def _email_login_oracle(factory, sender: CapturingSender) -> dict[str, Any]:
    from app.core.config import settings
    from app.models.registration import OtpFlow
    from app.services import login_service

    original = settings.email_login_enabled
    settings.email_login_enabled = True
    try:
        with factory.begin() as session:
            verified_actor, pending_actor = _seed_actor(session), _seed_actor(session)
        verified_email = f"native-login-verified-{uuid.uuid4().hex[:8]}@example.test"
        pending_email = f"native-login-pending-{uuid.uuid4().hex[:8]}@example.test"
        _add_verified(factory, sender, verified_actor, verified_email)
        from app.services import email_identity_service as service
        with factory() as session:
            service.add_identity(session, pending_actor["actor_id"], pending_actor["token"], email=pending_email, sender=sender, key=f"native-add-{uuid.uuid4().hex[:20]}", client_ip="127.0.0.1", now=pending_actor["now"])
        shapes = []
        real_deliveries = 0
        for email in (verified_email, pending_email, f"native-unknown-{uuid.uuid4().hex[:8]}@example.test"):
            with factory() as session:
                raw_token, flow, intent = login_service.start_email_flow(session, email, datetime.now(timezone.utc))
                session.commit()
                shapes.append((flow.state, flow.purpose, bool(flow.destination_masked_ct), (flow.metadata_json or {}).get("channel")))
                real_deliveries += int(intent is not None)
                _require(len(raw_token) >= 32, "FLOW_TOKEN_TOO_SHORT")
        _require(len(set(shapes)) == 1 and shapes[0] == ("pending", "login", True, "email"), "EMAIL_LOGIN_SHAPE_NOT_UNIFORM")
        _require(real_deliveries == 1, "EMAIL_LOGIN_UNVERIFIED_DELIVERED")
        with factory() as session:
            _require(session.scalar(select(func.count()).select_from(OtpFlow).where(OtpFlow.purpose == "login")) == 3, "EMAIL_LOGIN_FLOWS_MISSING")
    finally:
        settings.email_login_enabled = original
    return _row("EMAIL_LOGIN_NON_ENUMERATING_AND_UNVERIFIED_DENIED", 4)


def _populated_downgrade_oracle(database_url: str, factory) -> dict[str, Any]:
    from app.models.email_identity import UserEmailIdentity

    with factory() as session:
        _require(session.scalar(select(func.count()).select_from(UserEmailIdentity)) > 0, "POPULATED_DOWNGRADE_PRECONDITION")
    _alembic(database_url, "downgrade", PREVIOUS_REVISION, expect_failure="email_identity_downgrade_requires_empty_graph")
    with factory() as session:
        _require(session.scalar(text("SELECT version_num FROM alembic_version")) == APPLICATION_HEAD, "POPULATED_DOWNGRADE_MUTATED_HEAD")
    return _row("POPULATED_DOWNGRADE_REFUSED", 2)


def run(control_raw: str, output: Path) -> dict[str, Any]:
    if not opt_in_enabled(dict(os.environ)):
        raise Blocked("NATIVE_EXPLICIT_OPT_IN_REQUIRED")
    control = safe_control_url(control_raw)
    scratch = f"nyay12_gate_{uuid.uuid4().hex[:12]}"
    engine = None
    created = False
    rows: list[dict[str, Any]] = []
    try:
        _admin(control, f'CREATE DATABASE "{scratch}"')
        created = True
        database_url = _database_url(control, scratch)
        engine = create_engine(database_url, poolclass=NullPool)
        with engine.begin() as connection:
            version = int(connection.scalar(text("SHOW server_version_num"))) // 10000
            _require(version == 16, "POSTGRES_16_REQUIRED")
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            _require(connection.scalar(text("SELECT count(*) FROM pg_extension WHERE extname='vector'")) == 1, "PGVECTOR_REQUIRED")
        rows.append(_migration_roundtrip(database_url))
        rows.append(_legacy_duplicate_oracle(control))
        factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
        sender = CapturingSender()
        rows.append(_partial_unique_oracle(factory))
        rows.append(_concurrent_primary_oracle(factory, sender))
        rows.append(_verify_race_oracle(factory, sender))
        rows.append(_remove_replay_oracle(factory, sender))
        rows.append(_cross_owner_oracle(factory, sender))
        rows.append(_email_login_oracle(factory, sender))
        rows.append(_populated_downgrade_oracle(database_url, factory))
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            try:
                _admin(control, f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
            except Exception as exc:
                raise GateFailure("NATIVE_SCRATCH_CLEANUP_FAILED") from exc
    report = {
        "schema_version": SCHEMA_VERSION, "status": "PASS", "executed": True,
        "postgres_major": 16, "pgvector_present": True, "rows": rows,
        "total": len(rows), "passed": sum(row["passed"] is True for row in rows),
        "failed": sum(row["passed"] is not True for row in rows), "scratch_cleanup": True,
    }
    validate_report(report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args.database_url, args.output)
    except Blocked as exc:
        print(json.dumps(blocked_report(str(exc))))
        return BLOCKED_EXIT
    except GateFailure as exc:
        code = str(exc) if re.fullmatch(r"[A-Z0-9_]+", str(exc)) else "NATIVE_REQUIRED_ORACLE_FAILED"
        print(json.dumps({"status": "FAIL", "code": code, "executed": False}))
        return 1
    except Exception:
        print(json.dumps({"status": "FAIL", "code": "NATIVE_REQUIRED_ORACLE_FAILED", "executed": False}))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
