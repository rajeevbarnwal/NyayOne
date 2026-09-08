"""NYAY-11 native authority gate with an exact, nonzero assertion inventory.

The producer creates a uniquely named disposable database on a literal
loopback PostgreSQL 16/pgvector control server. The caller's database is never
migrated. Every one of the 61 guardian/institutional state pairs is exercised
through the production transition service, committed, and independently read
back. Evidence contains only closed-world identifiers and aggregate counts.
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
import time
import uuid
from typing import Any

from sqlalchemy import create_engine, event, func, inspect, make_url, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import IntegrityError, DBAPIError
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SCHEMA_VERSION = "nyay11-authority-postgres/v1"
OPT_IN_ENV = "NYAY11_POSTGRES_GATE"
BLOCKED_EXIT = 78
PREVIOUS_REVISION = "0023_nyay22_mentor_ceremony"
APPLICATION_HEAD = "0025_nyay12_email_identity"
GUARDIAN_STATES = (
    "NOT_REQUIRED", "REQUIRED_PENDING", "VERIFIED", "REJECTED", "REVOKED",
)
INSTITUTIONAL_STATES = (
    "UNVERIFIED", "PENDING", "VERIFIED", "REJECTED", "EXPIRED", "REVOKED",
)
STATE_ORACLE_IDS = tuple(
    f"STATE:{machine}:{source}:{target}"
    for machine, states in (
        ("guardian", GUARDIAN_STATES), ("institutional", INSTITUTIONAL_STATES)
    )
    for source in states for target in states
)
SUPPORT_ORACLE_IDS = (
    "MIGRATION_UP_DOWN_UP_CHECK",
    "MIGRATION_POPULATED_LEGACY_MAPPING",
    "DB_CARDINALITY_AND_CONSISTENCY",
    "GUARDIAN_SERVER_PROOF_AND_CROSS_OWNER_DENIAL",
    "REVIEWER_PROOF_ASSIGNMENT_AND_CROSS_INSTITUTION_DENIAL",
    "CONCURRENT_REVOCATION_COMPLETION_SERIALIZED",
    "EXACT_DUPLICATE_IDEMPOTENCY",
    "DOB_BIRTHDAY_LEAP_AND_ATOMIC_REPROOF",
    "AUDIT_APPEND_ONLY_AGGREGATE_PRIVACY",
    "REVIEWER_ERASURE_REVIEW_FIRST_ATOMIC",
    "REVIEWER_ERASURE_ERASE_FIRST_ATOMIC",
)
ORACLE_IDS = (*STATE_ORACLE_IDS, *SUPPORT_ORACLE_IDS)


class Blocked(RuntimeError):
    """A prerequisite is unavailable; no executed PASS may be emitted."""


class GateFailure(RuntimeError):
    """A privacy-safe native execution or assertion failure."""


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
        "rows", "total", "passed", "failed", "state_outcomes", "scratch_cleanup",
    }
    _require(isinstance(report, dict) and set(report) == expected_keys, "REPORT_SHAPE_INVALID")
    _require(report["schema_version"] == SCHEMA_VERSION and report["status"] == "PASS", "REPORT_VERDICT_INVALID")
    _require(report["executed"] is True and report["scratch_cleanup"] is True, "REPORT_UNEXECUTED")
    _require(type(report["postgres_major"]) is int and report["postgres_major"] == 16, "REPORT_RUNTIME_INVALID")
    _require(report["pgvector_present"] is True, "REPORT_RUNTIME_INVALID")
    expected_counts = {"total": len(ORACLE_IDS), "passed": len(ORACLE_IDS), "failed": 0, "state_outcomes": 61}
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


def _alembic(database_url: str, *arguments: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments], cwd=BACKEND,
        env={**os.environ, "APP_ENV": "testing", "DATABASE_URL": database_url,
             "PYTHONDONTWRITEBYTECODE": "1", "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180,
        check=False,
    )
    _require(result.returncode == 0, "MIGRATION_LIFECYCLE_FAILED")


def _migration_roundtrip(database_url: str) -> dict[str, Any]:
    _alembic(database_url, "upgrade", APPLICATION_HEAD)
    _alembic(database_url, "check")
    _alembic(database_url, "downgrade", PREVIOUS_REVISION)
    _alembic(database_url, "upgrade", APPLICATION_HEAD)
    _alembic(database_url, "check")
    return _row("MIGRATION_UP_DOWN_UP_CHECK", 5)


def _state_matrix(factory: sessionmaker[Session]) -> list[dict[str, Any]]:
    """Implemented below against the production service and committed rows."""
    from app.services import student_authority

    # The expected operations are read from the accepted independent contract;
    # the product implementation neither generates nor replaces this inventory.
    contract = json.loads((REPOSITORY / "docs/architecture/nyay11-guardian-institution-authority/STATE_MACHINE_CONTRACT.json").read_text())
    expected_rows = contract["stateOutcomeMatrix"]
    _require(len(expected_rows) == 61, "STATE_CONTRACT_INVENTORY_INVALID")
    rows = []
    for expected in expected_rows:
        machine, source, target = expected["machine"], expected["from"], expected["to"]
        identifier = f"STATE:{machine}:{source}:{target}"
        with factory() as session:
            registration, state, now = _seed_state(session, machine=machine, source=source)
            session.commit()
            version = state.version
            field = "guardian_state" if machine == "guardian" else "institutional_state"
            trigger = (expected["triggers"] or ["undeclared_transition"])[0]
            authority = (expected["authorities"] or ["student"])[0]
            try:
                result = student_authority.apply_transition(
                    session, state, machine=machine, target=target, trigger=trigger,
                    authority=authority, now=now,
                )
                denied = False
            except student_authority.AuthorityError:
                denied, result = True, "DENIED"
            session.commit()
            session.expire_all()
            persisted = session.get(type(state), registration.id)
            _require(persisted is not None, "STATE_PERSISTENCE_MISSING")
            if expected["disposition"] == "DENIED":
                _require(denied or result == "DENIED", "FORBIDDEN_EDGE_ACCEPTED")
                _require(getattr(persisted, field) == source and persisted.version == version, "DENIED_EDGE_WROTE_STATE")
            elif expected["disposition"] == "STATE_STABLE":
                _require(not denied and getattr(persisted, field) == source and persisted.version == version, "STABLE_EDGE_CHANGED_STATE")
            else:
                _require(not denied and getattr(persisted, field) == target and persisted.version == version + 1, "ALLOWED_EDGE_NOT_COMMITTED")
            rows.append(_row(identifier, 3))
    _require(set(row["id"] for row in rows) == set(STATE_ORACLE_IDS), "STATE_EXECUTION_INVENTORY_INVALID")
    return rows


def _seed_state(session: Session, *, machine: str, source: str):
    from app.models.student_authority import AuthorityState

    actor = _seed_actor(session, minor=True)
    now, registration = actor["now"], actor["registration"]
    row = AuthorityState(
        registration_id=registration.id,
        guardian_state=source if machine == "guardian" else "REQUIRED_PENDING",
        institutional_state=source if machine == "institutional" else "UNVERIFIED",
        version=1,
    )
    # This seed establishes the service primitive's already-attested context.
    # Separate entrypoint oracles below prove clients cannot author these proofs.
    _prime_proof_fields(row, registration, now)
    session.add(row)
    session.flush()
    return registration, row, now


def _prime_proof_fields(row, registration, now):
    from app.core.crypto import keyed_hash
    from app.services import student_authority

    row.guardian_user_id = registration.user_id
    row.guardian_verified_at = now
    row.guardian_expires_at = student_authority.guardian_deadline(now)
    row.guardian_dob_hash = registration.dob_hash
    row.guardian_identity_hash = keyed_hash("nyay11:guardian-identity:" + registration.dob_hash)
    row.relationship, row.consent_version = "parent", "guardian-consent.v1"
    row.institutional_email_hash = keyed_hash("synthetic-institutional-proof")
    row.institutional_expires_at = now + timedelta(days=30)


def _seed_actor(session, *, minor=False, role="student", born=None, now=None):
    from app.core.crypto import encrypt, keyed_hash
    from app.models.registration import AuthSession, StudentProfile, StudentRegistration, User

    now = now or datetime.now(timezone.utc)
    born = born or date(now.year - (16 if minor else 25), 1, 1)
    marker = uuid.uuid4().hex
    token = f"native-authority-session-{marker}"
    user = User(role=role, status="active")
    session.add(user)
    session.flush()
    registration = StudentRegistration(
        user_id=user.id, first_name="Synthetic", last_name="Authority",
        mobile_hash=keyed_hash(f"native-mobile-{marker}"),
        mobile_ct=encrypt(f"native-mobile-{marker}"),
        dob_hash=keyed_hash(born.isoformat()), dob_ct=encrypt(born.isoformat()),
        dob_hash_state="verified", key_version="v1", status="active", is_minor=minor,
    )
    session.add(registration)
    session.flush()
    profile = StudentProfile(registration_id=registration.id, profile_version=1)
    session.add(profile)
    session.add(AuthSession(
        user_id=user.id, token_hash=keyed_hash(token), status="active",
        expires_at=now + timedelta(hours=1), last_seen_at=now,
    ))
    session.flush()
    return {"actor_id": user.id, "registration": registration, "registration_id": registration.id,
            "token": token, "now": now, "profile": profile}


def _assert_denied(factory, call, *, code="authority_denied"):
    from app.services import student_authority
    from app.models.student_authority import AuthorityState, AuthorityMutationRecord

    with factory() as observer:
        before_states = [(row.registration_id, row.guardian_state, row.institutional_state, row.version)
                         for row in observer.scalars(select(AuthorityState).order_by(AuthorityState.registration_id))]
        before_mutations = observer.scalar(select(func.count()).select_from(AuthorityMutationRecord))
    with factory() as session:
        try:
            call(session)
        except student_authority.AuthorityError as exc:
            _require(exc.code == code, "AUTHORITY_ERROR_NOT_CANONICAL")
            session.rollback()
        else:
            raise GateFailure("UNAUTHORIZED_ENTRYPOINT_ACCEPTED")
    with factory() as observer:
        after_states = [(row.registration_id, row.guardian_state, row.institutional_state, row.version)
                        for row in observer.scalars(select(AuthorityState).order_by(AuthorityState.registration_id))]
        after_mutations = observer.scalar(select(func.count()).select_from(AuthorityMutationRecord))
    _require(before_states == after_states and before_mutations == after_mutations, "DENIED_AUTHORITY_MUTATED_STATE")


def _guardian_proof_oracle(factory):
    from app.models.student_authority import AuthorityState
    from app.services import student_authority as service

    with factory.begin() as session:
        child, guardian, unrelated = _seed_actor(session, minor=True), _seed_actor(session), _seed_actor(session)
    now = child["now"]
    with factory.begin() as session:
        invitation = service.guardian_request(session, child["actor_id"], child["token"], key="native-guardian-request-0001", now=now)["invitation"]
    _assert_denied(factory, lambda session: service.guardian_consent(session, child["actor_id"], child["token"], invitation=invitation, relationship="parent", accepted=True, key="native-self-approval-0001", now=now))
    _assert_denied(factory, lambda session: service.guardian_consent(session, guardian["actor_id"], None, invitation=invitation, relationship="parent", accepted=True, key="native-no-session-00001", now=now), code="authentication_required")
    with factory.begin() as session:
        result = service.guardian_consent(session, guardian["actor_id"], guardian["token"], invitation=invitation, relationship="parent", accepted=True, key="native-consent-valid-0001", now=now)
        _require(result["guardian_state"] == "VERIFIED", "GUARDIAN_PROOF_NOT_ACCEPTED")
    with factory() as session:
        row = session.get(AuthorityState, child["registration_id"])
        _require(row.guardian_user_id == guardian["actor_id"] and row.guardian_expires_at == service.guardian_deadline(now), "GUARDIAN_PROOF_BINDING_INVALID")
    _assert_denied(factory, lambda session: service.guardian_revoke(session, unrelated["actor_id"], unrelated["token"], registration_id=child["registration_id"], key="native-cross-owner-0001", now=now))
    with factory.begin() as session:
        ended = service.guardian_revoke(session, guardian["actor_id"], guardian["token"], registration_id=child["registration_id"], key="native-own-guardian-revoke-0001", now=now)
        _require(ended["guardian_state"] == "REVOKED", "GUARDIAN_REVOCATION_FAILED")
    with factory.begin() as session:
        replay = service.guardian_consent(session, guardian["actor_id"], guardian["token"], invitation=invitation, relationship="parent", accepted=True, key="native-consent-valid-0001", now=now)
        _require(replay == result, "CONSENT_REPLAY_CHANGED_OUTCOME")
    with factory() as session:
        _require(session.get(AuthorityState, child["registration_id"]).guardian_state == "REVOKED", "REPLAY_RESURRECTED_REVOKED_AUTHORITY")
    with factory.begin() as session:
        reg, state, _ = _seed_state(session, machine="guardian", source="VERIFIED")
        state.guardian_expires_at = now - timedelta(seconds=1)
        state.guardian_verified_at = now - timedelta(days=366)
        service.settle_state(session, reg, state, now)
        _require(state.guardian_state == "REQUIRED_PENDING" and state.reproof_guardian is True, "EXPIRED_GUARDIAN_AUTHORITY_SURVIVED")
    return _row("GUARDIAN_SERVER_PROOF_AND_CROSS_OWNER_DENIAL", 11)


def _email_proof(session, actor, institution, *, expired=False):
    from app.core.crypto import keyed_hash
    from app.models.student_authority import InstitutionalEmailProof

    email_hash = keyed_hash("native-mail-" + str(actor["actor_id"]))
    actor["registration"].institution_ref = institution
    actor["profile"].institutional_email_hash = email_hash
    proof = InstitutionalEmailProof(user_id=actor["actor_id"], email_hash=email_hash,
        institution=institution, code_hash=None, provider_receipt_hash=keyed_hash("native-attested-delivery"),
        state="verified", attempts=1, issued_at=actor["now"] - timedelta(minutes=1),
        expires_at=actor["now"] + timedelta(days=-1 if expired else 60))
    session.add(proof)


def _reviewer_proof_oracle(factory):
    from app.services import student_authority as service
    from app.models.student_authority import AuthorityState, InstitutionalReviewerAssignment, AuthorityNotification

    with factory.begin() as session:
        owner, reviewer, foreign, admin = _seed_actor(session), _seed_actor(session), _seed_actor(session), _seed_actor(session, role="admin")
        institution = "native-institution-" + uuid.uuid4().hex
        _email_proof(session, owner, institution)
        _email_proof(session, reviewer, institution)
        _email_proof(session, foreign, institution + "-other")
    now = owner["now"]
    with factory.begin() as session:
        service.request_review(session, owner["actor_id"], owner["token"], key="native-review-request-0001", now=now)
    _assert_denied(factory, lambda session: service.review(session, owner["actor_id"], owner["token"], registration_id=owner["registration_id"], approve=True, key="native-review-self-0001", now=now))
    _assert_denied(factory, lambda session: service.review(session, reviewer["actor_id"], reviewer["token"], registration_id=owner["registration_id"], approve=True, key="native-review-unassigned-0001", now=now))
    with factory.begin() as session:
        service.assign_reviewer(session, admin["actor_id"], admin["token"], reviewer_id=reviewer["actor_id"], institution=institution, expires_at=now+timedelta(days=30), key="native-assign-own-00001", now=now)
        service.assign_reviewer(session, admin["actor_id"], admin["token"], reviewer_id=foreign["actor_id"], institution=institution+"-other", expires_at=now+timedelta(days=30), key="native-assign-foreign-0001", now=now)
    _assert_denied(factory, lambda session: service.review(session, foreign["actor_id"], foreign["token"], registration_id=owner["registration_id"], approve=True, key="native-review-foreign-0001", now=now))
    with factory.begin() as session:
        result = service.review(session, reviewer["actor_id"], reviewer["token"], registration_id=owner["registration_id"], approve=True, key="native-review-approved-0001", now=now)
        _require(result["institutional_state"] == "VERIFIED", "REVIEWER_PROOF_NOT_ACCEPTED")
    with factory() as session:
        row = session.get(AuthorityState, owner["registration_id"])
        assignment = session.scalar(select(InstitutionalReviewerAssignment).where(InstitutionalReviewerAssignment.user_id == reviewer["actor_id"]))
        _require(row.institutional_expires_at <= assignment.expires_at, "REVIEW_AUTHORITY_TTL_WIDENED")
    statements = []
    engine = factory.kw["bind"]
    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.upper())
    event.listen(engine, "before_cursor_execute", observe)
    try:
        with factory() as session:
            _require(service.institutional_is_current(session, owner["registration_id"], now=now) is True, "CURRENT_INSTITUTIONAL_PROOF_NOT_OBSERVED")
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    _require(bool(statements) and not any("FOR UPDATE" in statement for statement in statements), "PROJECTION_TAKES_NO_PROOF_LOCK")
    with factory.begin() as session:
        reg = session.get(type(owner["registration"]), owner["registration_id"])
        row = session.get(AuthorityState, owner["registration_id"])
        service.settle_state(session, reg, row, now + timedelta(days=31))
        _require(row.institutional_state == "EXPIRED", "EXPIRED_INSTITUTION_AUTHORITY_SURVIVED")
    with factory.begin() as session:
        queued = _seed_actor(session)
        service.request_review(session, queued["actor_id"], queued["token"], key="native-review-timeout-0001", now=queued["now"])
        row = session.get(AuthorityState, queued["registration_id"])
        row.review_due_at = queued["now"] - timedelta(seconds=1)
    with factory.begin() as session:
        _require(service.reviewer_timeout(session, queued["registration_id"], now=queued["now"]) is True, "REVIEW_TIMEOUT_NOT_RETURNED")
    with factory.begin() as session:
        _require(service.reviewer_timeout(session, queued["registration_id"], now=queued["now"]) is False, "REVIEW_TIMEOUT_REPEATED_EVENT")
        row = session.get(AuthorityState, queued["registration_id"])
        notifications = session.scalar(select(func.count()).select_from(AuthorityNotification).where(AuthorityNotification.registration_id == queued["registration_id"]))
        _require(row.institutional_state == "PENDING" and notifications == 1, "REVIEW_TIMEOUT_REJECTED_OR_SILENT")
    return _row("REVIEWER_PROOF_ASSIGNMENT_AND_CROSS_INSTITUTION_DENIAL", 14)


def _migration_legacy(factory, database_url):
    from app.core.crypto import keyed_hash
    from app.models.registration import GuardianConsent, StudentVerification
    from app.models.student_authority import AuthorityState, AuthorityAuditEvent

    _alembic(database_url, "downgrade", PREVIOUS_REVISION)
    guardian_map = {"pending": "REQUIRED_PENDING", "sent": "REQUIRED_PENDING", "verified": "VERIFIED", "rejected": "REJECTED", "revoked": "REVOKED"}
    institution_map = {"pending": "UNVERIFIED", "in_review": "PENDING", "verified": "VERIFIED", "rejected": "REJECTED", "expired": "EXPIRED", "revoked": "REVOKED"}
    expected = []
    with factory.begin() as session:
        for source, target in guardian_map.items():
            actor = _seed_actor(session, minor=True)
            session.add(GuardianConsent(registration_id=actor["registration_id"], status=source, verified=source == "verified"))
            expected.append((actor["registration_id"], "guardian", target))
        for source, target in institution_map.items():
            actor = _seed_actor(session)
            session.add(StudentVerification(registration_id=actor["registration_id"], method="institutional_email", status=source, verified_email_hash=keyed_hash("native-legacy-proof") if source == "verified" else None))
            expected.append((actor["registration_id"], "institutional", target))
    _alembic(database_url, "upgrade", APPLICATION_HEAD)
    _alembic(database_url, "check")
    with factory() as session:
        audit_codes = list(session.scalars(select(AuthorityAuditEvent.transition_code).where(AuthorityAuditEvent.purpose_code == "legacy_mapping")))
        _require(len(audit_codes) == 22, "LEGACY_MAPPING_AUDIT_INCOMPLETE")
        for registration_id, machine, target in expected:
            row = session.get(AuthorityState, registration_id)
            _require(row is not None, "LEGACY_MAPPING_ROW_LOST")
            desired = ("REQUIRED_PENDING" if machine == "guardian" else "PENDING") if target == "VERIFIED" else target
            _require(getattr(row, f"{machine}_state") == desired, "LEGACY_MAPPING_WRONG_STATE")
            _require(f"{'GUARDIAN' if machine == 'guardian' else 'INSTITUTIONAL'}_{target}" in audit_codes, "LEGACY_MAPPING_SILENT_REWRITE")
            if target == "VERIFIED":
                _require(getattr(row, f"reproof_{machine}") is True, "LEGACY_MUTABLE_FLAG_BECAME_AUTHORITY")
    def preserved_graph():
        with factory() as session:
            states = session.execute(select(*AuthorityState.__table__.columns).order_by(AuthorityState.registration_id)).all()
            audit = session.execute(select(*AuthorityAuditEvent.__table__.columns).order_by(AuthorityAuditEvent.id)).all()
            return states, audit, tuple(sorted(inspect(factory.kw["bind"]).get_table_names()))
    before = preserved_graph()
    try:
        _alembic(database_url, "downgrade", PREVIOUS_REVISION)
    except GateFailure as exc:
        _require(str(exc) == "MIGRATION_LIFECYCLE_FAILED", "POPULATED_DOWNGRADE_REFUSED")
    else:
        raise GateFailure("POPULATED_DOWNGRADE_REFUSED")
    _require(preserved_graph() == before, "POPULATED_DOWNGRADE_GRAPH_UNCHANGED")
    with factory() as session:
        _require(session.scalar(text("SELECT version_num FROM alembic_version")) == APPLICATION_HEAD, "POPULATED_DOWNGRADE_REVISION_UNCHANGED")
    return _row("MIGRATION_POPULATED_LEGACY_MAPPING", 39)


def _constraint_oracle(factory):
    from app.models.student_authority import AuthorityState

    with factory.begin() as session:
        reg, row, _now = _seed_state(session, machine="guardian", source="REQUIRED_PENDING")
        registration_id = reg.id
    rejected = 0
    for clause in (
        "INSERT INTO student_authority_states (registration_id, guardian_state, institutional_state, version, reproof_guardian, reproof_institutional, policy_version) VALUES (:id, 'REQUIRED_PENDING', 'UNVERIFIED', 1, false, false, 'NYAY-11-v1')",
        "UPDATE student_authority_states SET guardian_state='FORGED' WHERE registration_id=:id",
        "UPDATE student_authority_states SET guardian_state='VERIFIED', guardian_verified_at=NULL WHERE registration_id=:id",
        "UPDATE student_authority_states SET institutional_state='VERIFIED', institutional_email_hash=NULL WHERE registration_id=:id",
        "UPDATE student_authority_states SET version=0 WHERE registration_id=:id",
    ):
        with factory() as session:
            try:
                session.execute(text(clause), {"id": registration_id})
                session.commit()
            except IntegrityError:
                session.rollback()
                rejected += 1
            else:
                raise GateFailure("NATIVE_CONSTRAINT_ACCEPTED_INVALID_ROW")
    with factory() as session:
        _require(session.scalar(select(func.count()).select_from(AuthorityState).where(AuthorityState.registration_id == registration_id)) == 1, "CARDINALITY_NOT_PRESERVED")
    return _row("DB_CARDINALITY_AND_CONSISTENCY", rejected + 1)


def _duplicate_oracle(factory):
    from app.services import student_authority as service
    from app.models.student_authority import AuthorityMutationRecord, GuardianInvitation

    with factory.begin() as session:
        child = _seed_actor(session, minor=True)
    barrier = threading.Barrier(2)
    def request():
        with factory() as session:
            barrier.wait(timeout=10)
            result = service.guardian_request(session, child["actor_id"], child["token"], key="native-concurrent-exact-key-0001", now=child["now"])
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(request) for _ in range(2)]
        results = [future.result(timeout=20) for future in futures]
    _require(results[0] == results[1], "DUPLICATE_REPLAY_NOT_EXACT")
    with factory() as session:
        records = session.scalar(select(func.count()).select_from(AuthorityMutationRecord).where(AuthorityMutationRecord.registration_id == child["registration_id"]))
        invitations = session.scalar(select(func.count()).select_from(GuardianInvitation).where(GuardianInvitation.registration_id == child["registration_id"]))
        _require(records == 1 and invitations == 1, "DUPLICATE_AUTHORITY_GRAPH_CREATED")
    return _row("EXACT_DUPLICATE_IDEMPOTENCY", 3)


def _revocation_race_oracle(factory):
    from app.models.registration import StudentRegistration
    from app.models.student_authority import AuthorityState
    from app.services import student_authority as service

    assertions = 0
    for first in ("revoke", "consent"):
        with factory.begin() as session:
            child, guardian = _seed_actor(session, minor=True), _seed_actor(session)
        now = child["now"]
        with factory.begin() as session:
            invitation = service.guardian_request(session, child["actor_id"], child["token"], key=f"native-race-request-{first}-0001", now=now)["invitation"]
        def operation(session, which):
            if which == "revoke":
                return service.guardian_revoke(session, child["actor_id"], child["token"], key=f"native-race-revoke-{first}-0001", now=now)
            return service.guardian_consent(session, guardian["actor_id"], guardian["token"], invitation=invitation, relationship="parent", accepted=True, key=f"native-race-consent-{first}-0001", now=now)
        second = "consent" if first == "revoke" else "revoke"
        observed_pid = []
        started = threading.Event()
        def loser():
            with factory() as session:
                observed_pid.append(session.scalar(text("SELECT pg_backend_pid()")))
                started.set()
                try:
                    result = operation(session, second)
                    session.commit()
                    return result["guardian_state"]
                except service.AuthorityError as exc:
                    session.rollback()
                    _require(exc.code == "authority_denied", "RACE_ERROR_NOT_CANONICAL")
                    return "DENIED"
        with factory() as holder, ThreadPoolExecutor(max_workers=1) as executor:
            holder.scalar(select(StudentRegistration).where(StudentRegistration.id == child["registration_id"]).with_for_update())
            operation(holder, first)
            holder.flush()
            future = executor.submit(loser)
            _require(started.wait(10), "RACE_WORKER_NOT_STARTED")
            deadline = time.monotonic() + 10
            lock_observed = False
            while time.monotonic() < deadline:
                with factory() as observer:
                    lock_observed = observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": observed_pid[0]}) is True
                if lock_observed:
                    break
                time.sleep(0.01)
            if not lock_observed:
                holder.rollback()
                raise GateFailure("NATIVE_REGISTRATION_LOCK_NOT_OBSERVED")
            holder.commit()
            result = future.result(timeout=20)
            _require(result == ("DENIED" if first == "revoke" else "REVOKED"), "REVOCATION_DID_NOT_WIN_AUTHORITY_RACE")
        with factory() as session:
            _require(session.get(AuthorityState, child["registration_id"]).guardian_state == "REVOKED", "CONCURRENT_COMPLETION_RESURRECTED_AUTHORITY")
        assertions += 3
    assertions += _cross_review_oracle(factory)
    assertions += _erasure_completion_oracle(factory)
    return _row("CONCURRENT_REVOCATION_COMPLETION_SERIALIZED", assertions)


def _cross_review_oracle(factory):
    from app.services import student_authority as service
    from app.models.student_authority import AuthorityState

    with factory.begin() as session:
        actors = [_seed_actor(session), _seed_actor(session)]
        admin = _seed_actor(session, role="admin")
        institution = "native-cross-review-" + uuid.uuid4().hex
        for actor in actors:
            _email_proof(session, actor, institution)
    now = actors[0]["now"]
    for index, actor in enumerate(actors):
        with factory.begin() as session:
            service.assign_reviewer(session, admin["actor_id"], admin["token"], reviewer_id=actor["actor_id"], institution=institution, expires_at=now+timedelta(days=20), key=f"native-cross-assignment-{index}", now=now)
            service.request_review(session, actor["actor_id"], actor["token"], key=f"native-cross-request-{index}", now=now)
    barrier = threading.Barrier(2)
    def review(index):
        actor, target = actors[index], actors[1-index]
        with factory() as session:
            session.execute(text("SET LOCAL statement_timeout = '15000ms'"))
            barrier.wait(timeout=10)
            result = service.review(session, actor["actor_id"], actor["token"], registration_id=target["registration_id"], approve=True, key=f"native-cross-review-{index}", now=now)
            session.commit()
            return result["institutional_state"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(review, index) for index in range(2)]
        results = [future.result(timeout=20) for future in futures]
    _require(results == ["VERIFIED", "VERIFIED"], "CROSS_REVIEW_COMPLETES_WITHOUT_DEADLOCK")
    with factory() as session:
        _require(all(session.get(AuthorityState, actor["registration_id"]).institutional_state == "VERIFIED" for actor in actors), "CROSS_REVIEW_COMMIT_NOT_DURABLE")
    return 2


def _erasure_completion_oracle(factory):
    from app.core.retention import delete_registration
    from app.models.registration import StudentRegistration
    from app.models.student_authority import AuthorityState, AuthorityAuditEvent
    from app.services import student_authority as service

    assertions = 0
    for first in ("erase", "consent"):
        with factory.begin() as session:
            child, guardian = _seed_actor(session, minor=True), _seed_actor(session)
        now = child["now"]
        with factory.begin() as session:
            invitation = service.guardian_request(session, child["actor_id"], child["token"], key="native-erasure-request-0001", now=now)["invitation"]
        causal_query = select(func.count()).select_from(AuthorityAuditEvent).where(
            AuthorityAuditEvent.actor_class == "server",
            AuthorityAuditEvent.authority_class == "server_profile_policy",
            AuthorityAuditEvent.purpose_code == "guardian",
            AuthorityAuditEvent.transition_code == "PROOF_REVOKED",
        )
        with factory() as session:
            causal_before = session.scalar(causal_query)
        def operation(session, which):
            if which == "erase":
                reg = session.get(StudentRegistration, guardian["registration_id"])
                _require(delete_registration(session, reg) is True, "GUARDIAN_ERASURE_DEFERRED")
                return "ERASED"
            result = service.guardian_consent(session, guardian["actor_id"], guardian["token"], invitation=invitation, relationship="parent", accepted=True, key="native-erasure-consent-0001", now=now)
            return result["guardian_state"]
        second = "consent" if first == "erase" else "erase"
        pid, started = [], threading.Event()
        def competing():
            with factory() as session:
                session.execute(text("SET LOCAL statement_timeout = '15000ms'"))
                pid.append(session.scalar(text("SELECT pg_backend_pid()")))
                started.set()
                try:
                    result = operation(session, second)
                    session.commit()
                    return result
                except service.AuthorityError:
                    session.rollback()
                    return "DENIED"
        with factory() as holder, ThreadPoolExecutor(max_workers=1) as executor:
            operation(holder, first)
            holder.flush()
            future = executor.submit(competing)
            _require(started.wait(10), "ERASURE_WORKER_NOT_STARTED")
            deadline, lock_observed = time.monotonic() + 10, False
            while time.monotonic() < deadline:
                with factory() as observer:
                    lock_observed = observer.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid[0]}) is True
                if lock_observed:
                    break
                if future.done():
                    break
                time.sleep(0.01)
            if not lock_observed:
                holder.rollback()
                raise GateFailure("ERASURE_LOCK_NOT_OBSERVED")
            holder.commit()
            result = future.result(timeout=20)
            _require(result == ("DENIED" if first == "erase" else "ERASED"), "ERASURE_COMPLETION_ORDER_INVALID")
        with factory() as session:
            _require(not service.guardian_is_current(session, child["registration_id"], now=now), "ERASURE_PREVENTS_AUTHORITY_RESURRECTION")
            state = session.get(AuthorityState, child["registration_id"])
            _require(state.guardian_user_id is None and state.guardian_state != "VERIFIED", "ERASURE_LEFT_DEPENDENT_AUTHORITY_LINK")
            _require(session.scalar(causal_query) == causal_before + (1 if first == "consent" else 0), "ERASURE_AUDIT_CAUSE_NOT_SERVER")
        assertions += 5
    return assertions


def _dob_oracle(factory):
    from app.core.crypto import encrypt, keyed_hash
    from app.models.student_authority import AuthorityState
    from app.services import student_authority as service

    cases = (
        (date(2008, 9, 5), date(2026, 9, 4), "REQUIRED_PENDING"),
        (date(2008, 9, 5), date(2026, 9, 5), "NOT_REQUIRED"),
        (date(2008, 2, 29), date(2026, 2, 28), "REQUIRED_PENDING"),
        (date(2008, 2, 29), date(2026, 3, 1), "NOT_REQUIRED"),
    )
    for born, today, expected in cases:
        now = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        with factory.begin() as session:
            actor = _seed_actor(session, minor=True, born=born, now=now)
            row = service.get_or_create_state(session, actor["registration"], now)
            service.settle_state(session, actor["registration"], row, now)
        with factory() as session:
            _require(session.get(AuthorityState, actor["registration_id"]).guardian_state == expected, "DOB_CIVIL_DATE_BOUNDARY_FAILED")
    # An identity edit and its invalidation share the caller transaction. An
    # injected abort cannot leave a new DOB paired with a trusted old proof.
    with factory.begin() as session:
        reg, row, now = _seed_state(session, machine="guardian", source="VERIFIED")
        registration_id, original_hash, original_ct = reg.id, reg.dob_hash, reg.dob_ct
    with factory() as session:
        from app.models.registration import StudentRegistration
        reg = session.get(StudentRegistration, registration_id)
        service.identity_changed(session, reg, "date_of_birth", now)
        reg.dob_hash, reg.dob_ct = keyed_hash("2011-02-03"), encrypt("2011-02-03")
        session.flush()
        session.rollback()
    with factory() as session:
        reg = session.get(StudentRegistration, registration_id)
        row = session.get(AuthorityState, registration_id)
        _require(reg.dob_hash == original_hash and reg.dob_ct == original_ct and row.guardian_state == "VERIFIED", "IDENTITY_ABORT_PARTIALLY_CHANGED_AUTHORITY")
        service.identity_changed(session, reg, "date_of_birth", now)
        reg.dob_hash, reg.dob_ct = keyed_hash("2011-02-03"), encrypt("2011-02-03")
        session.commit()
    with factory() as session:
        row = session.get(AuthorityState, registration_id)
        _require(row.guardian_state == "REQUIRED_PENDING" and row.reproof_guardian is True, "IDENTITY_CHANGE_DID_NOT_REQUIRE_REPROOF")
    _require(service.guardian_deadline(datetime(2024, 2, 29, tzinfo=timezone.utc)) == datetime(2025, 2, 28, tzinfo=timezone.utc), "CALENDAR_TTL_LEAP_BOUNDARY_FAILED")
    return _row("DOB_BIRTHDAY_LEAP_AND_ATOMIC_REPROOF", 7)


def _reviewer_erasure_oracle(factory, first):
    """Two real operations, both observed schedules; no retries or sleeps as proof.

    The reproof state deliberately retains the earlier reviewer edge through
    the production identity-change service. That reachable edge is needed to
    exercise erasure's dependent-authority lock, not merely reviewer self-state.
    """
    from app.core.crypto import keyed_hash
    from app.core.retention import delete_registration
    from app.models.registration import StudentProfile, StudentRegistration, StudentVerification
    from app.models.student_authority import AuthorityState, AuthorityAuditEvent, InstitutionalEmailProof, InstitutionalReviewerAssignment
    from app.services import student_authority as service

    _require(first in {"review", "erase"}, "REVIEWER_ERASURE_SCHEDULE_INVALID")
    with factory.begin() as session:
        owner, reviewer, admin = _seed_actor(session), _seed_actor(session), _seed_actor(session, role="admin")
        institution = "native-reviewer-erasure-" + uuid.uuid4().hex
        for actor in (owner, reviewer, admin):
            session.add(StudentVerification(registration_id=actor["registration_id"], method="institutional_email", status="pending"))
        for actor in (owner, reviewer):
            _email_proof(session, actor, institution)
    now = owner["now"]
    with factory.begin() as session:
        service.request_review(session, owner["actor_id"], owner["token"], key="native-erasure-review-request-0001", now=now)
        service.assign_reviewer(session, admin["actor_id"], admin["token"], reviewer_id=reviewer["actor_id"], institution=institution, expires_at=now + timedelta(days=30), key="native-erasure-review-assign-0001", now=now)
    with factory.begin() as session:
        result = service.review(session, reviewer["actor_id"], reviewer["token"], registration_id=owner["registration_id"], approve=True, key="native-erasure-first-review-0001", now=now)
        _require(result["institutional_state"] == "VERIFIED", "REVIEWER_ERASURE_INITIAL_REVIEW_FAILED")
    with factory.begin() as session:
        reg = session.scalar(select(StudentRegistration).where(StudentRegistration.id == owner["registration_id"]).with_for_update())
        service.identity_changed(session, reg, "institutional_email", now)
        profile = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == reg.id))
        proof = session.get(InstitutionalEmailProof, owner["actor_id"])
        profile.institutional_email_hash = keyed_hash("native-erasure-new-email-" + str(reg.id))
        proof.email_hash = profile.institutional_email_hash
        proof.provider_receipt_hash = keyed_hash("native-erasure-new-receipt-" + str(reg.id))
        state = session.get(AuthorityState, reg.id)
        _require(state.institutional_state == "PENDING" and state.reviewer_user_id == reviewer["actor_id"], "REVIEWER_ERASURE_REPROOF_EDGE_NOT_REACHABLE")

    audit_query = select(func.count()).select_from(AuthorityAuditEvent).where(
        AuthorityAuditEvent.actor_class == "server",
        AuthorityAuditEvent.authority_class == "server_profile_policy",
        AuthorityAuditEvent.purpose_code == "institutional",
        AuthorityAuditEvent.transition_code == "PROOF_REVOKED",
    )
    with factory() as session:
        audit_before = session.scalar(audit_query)

    held, release, started = threading.Event(), threading.Event(), threading.Event()
    engine = factory.kw["bind"]
    pids = {}
    second = "erase" if first == "review" else "review"

    def observe(connection, _cursor, statement, _parameters, _context, _many):
        if connection.info.get("reviewer_erasure_role") != first or held.is_set():
            return
        sql = statement.lower()
        table = "institutional_authority_email_proofs" if first == "review" else "student_authority_states"
        if "from " + table in sql and "for update" in sql:
            held.set()
            _require(release.wait(15), "REVIEWER_ERASURE_RELEASE_NOT_OBSERVED")

    def operation(which):
        with factory() as session:
            connection = session.connection()
            connection.info["reviewer_erasure_role"] = which
            session.execute(text("SET LOCAL statement_timeout='12000ms'"))
            pids[which] = session.scalar(text("SELECT pg_backend_pid()"))
            if which == second:
                started.set()
            try:
                if which == "erase":
                    reg = session.get(StudentRegistration, reviewer["registration_id"])
                    result = "ERASED" if delete_registration(session, reg) is True else "DEFERRED"
                else:
                    result = service.review(session, reviewer["actor_id"], reviewer["token"], registration_id=owner["registration_id"], approve=True, key="native-erasure-racing-review-0001", now=now)["institutional_state"]
                session.commit()
                return {"result": result, "sqlstate": None}
            except service.AuthorityError as exc:
                session.rollback()
                _require(which == "review" and first == "erase" and exc.code == "authentication_required" and exc.status_code == 401, "REVIEWER_ERASURE_DENIAL_NOT_CANONICAL")
                return {"result": "DENIED", "sqlstate": None}
            except DBAPIError as exc:
                session.rollback()
                return {"result": "DB_ERROR", "sqlstate": getattr(exc.orig, "sqlstate", None)}

    event.listen(engine, "after_cursor_execute", observe)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            leader = executor.submit(operation, first)
            try:
                _require(held.wait(10), "REVIEWER_ERASURE_HELD_LOCK_NOT_OBSERVED")
                follower = executor.submit(operation, second)
                _require(started.wait(10), "REVIEWER_ERASURE_WORKER_NOT_STARTED")
                deadline, lock_observed = time.monotonic() + 10, False
                while time.monotonic() < deadline:
                    with factory() as observer:
                        blockers = observer.scalar(text("SELECT pg_blocking_pids(:pid)"), {"pid": pids[second]})
                    if pids[first] in blockers:
                        lock_observed = True
                        break
                    if follower.done():
                        break
                _require(lock_observed, "REVIEWER_ERASURE_BLOCKING_EDGE_NOT_OBSERVED")
            finally:
                release.set()
            results = {first: leader.result(timeout=20), second: follower.result(timeout=20)}
    finally:
        release.set()
        event.remove(engine, "after_cursor_execute", observe)
    _require(all(value["sqlstate"] != "40P01" for value in results.values()), "REVIEWER_ERASURE_DEADLOCK")
    _require(all(value["sqlstate"] is None for value in results.values()), "REVIEWER_ERASURE_DATABASE_FAILURE")
    _require(results["erase"]["result"] == "ERASED", "REVIEWER_ERASURE_NOT_COMMITTED")
    _require(results["review"]["result"] == ("VERIFIED" if first == "review" else "DENIED"), "REVIEWER_ERASURE_SERIAL_RESULT_INVALID")
    with factory() as session:
        state = session.get(AuthorityState, owner["registration_id"])
        expected_state = "REVOKED" if first == "review" else "PENDING"
        _require(state.reviewer_user_id is None and state.institutional_state == expected_state and state.reproof_institutional is True, "REVIEWER_ERASURE_RETAINED_AUTHORITY")
        _require(session.get(StudentRegistration, reviewer["registration_id"]) is None, "REVIEWER_ERASURE_PARTIAL_REGISTRATION")
        _require(session.get(InstitutionalEmailProof, reviewer["actor_id"]) is None, "REVIEWER_ERASURE_PARTIAL_PROOF")
        _require(session.scalar(select(func.count()).select_from(InstitutionalReviewerAssignment).where(InstitutionalReviewerAssignment.user_id == reviewer["actor_id"])) == 0, "REVIEWER_ERASURE_PARTIAL_ASSIGNMENT")
        _require(not service.institutional_is_current(session, owner["registration_id"], now=now), "REVIEWER_ERASURE_LEGACY_AUTHORITY_SURVIVED")
        _require(session.scalar(audit_query) == audit_before + (1 if first == "review" else 0), "REVIEWER_ERASURE_AUDIT_NOT_AGGREGATE_SERVER_CAUSE")
    identifier = "REVIEWER_ERASURE_REVIEW_FIRST_ATOMIC" if first == "review" else "REVIEWER_ERASURE_ERASE_FIRST_ATOMIC"
    return _row(identifier, 14)


def _audit_oracle(factory):
    from app.models.student_authority import AuthorityAuditEvent

    engine = factory.kw["bind"]
    columns = {column["name"] for column in inspect(engine).get_columns("student_authority_audit_events")}
    _require(columns == {"id", "actor_class", "authority_class", "purpose_code", "transition_code", "policy_version", "occurred_at"}, "AUDIT_COLUMN_ALLOWLIST_NOT_EXACT")
    _require(inspect(engine).get_foreign_keys("student_authority_audit_events") == [], "AUDIT_CONTAINS_LINKABLE_OWNER_FK")
    with factory() as session:
        audit_id = session.scalar(select(AuthorityAuditEvent.id).limit(1))
        _require(audit_id is not None, "AUDIT_ZERO_EXECUTED")
    rejected = 0
    for operation in ("UPDATE student_authority_audit_events SET actor_class='server' WHERE id=:id", "DELETE FROM student_authority_audit_events WHERE id=:id"):
        with factory() as session:
            try:
                session.execute(text(operation), {"id": audit_id})
                session.commit()
            except DBAPIError:
                session.rollback()
                rejected += 1
            else:
                raise GateFailure("AUDIT_MUTATION_ACCEPTED")
    return _row("AUDIT_APPEND_ONLY_AGGREGATE_PRIVACY", rejected + 3)


def _support_oracles(factory: sessionmaker[Session]) -> list[dict[str, Any]]:
    return [
        _constraint_oracle(factory), _guardian_proof_oracle(factory),
        _reviewer_proof_oracle(factory), _revocation_race_oracle(factory),
        _duplicate_oracle(factory), _dob_oracle(factory), _audit_oracle(factory),
        _reviewer_erasure_oracle(factory, "review"),
        _reviewer_erasure_oracle(factory, "erase"),
    ]


def run(control_raw: str, output: Path) -> dict[str, Any]:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise Blocked("NATIVE_EXPLICIT_OPT_IN_REQUIRED")
    control = safe_control_url(control_raw)
    scratch = f"nyay11_gate_{uuid.uuid4().hex[:12]}"
    engine = None
    created = False
    rows = []
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
        migration = _migration_roundtrip(database_url)
        factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
        legacy = _migration_legacy(factory, database_url)
        rows.extend(_state_matrix(factory))
        rows.append(migration)
        rows.append(legacy)
        rows.extend(_support_oracles(factory))
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
        "failed": sum(row["passed"] is not True for row in rows), "state_outcomes": 61,
        "scratch_cleanup": True,
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
    except Blocked:
        print(json.dumps({"status": "BLOCKED", "code": "NATIVE_PREREQUISITE_UNAVAILABLE", "executed": False}))
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
