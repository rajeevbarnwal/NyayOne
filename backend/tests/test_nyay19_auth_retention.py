"""NYAY-19 auth/session erasure, retention, and lifecycle contract."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import keyed_hash
from app.core.retention import (
    RetentionPolicy,
    anonymise_registration,
    delete_registration,
    purge_expired,
)
from app.db.models.audit import AuditEvent
from app.models.registration import (
    AuthSession,
    LoginAttempt,
    StudentRegistration,
    User,
)
from app.schemas.registration import StudentRegisterRequest
from app.services.registration_service import register_student

NOW = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _user(session: Session) -> User:
    row = User(role="student", status="active")
    session.add(row)
    session.flush()
    return row


def _attempt(
    session: Session,
    *,
    status: str,
    terminal_at: datetime | None,
    expires_at: datetime,
) -> LoginAttempt:
    row = LoginAttempt(
        opaque_id=uuid.uuid4().hex,
        lookup_hash=keyed_hash(f"attempt-{uuid.uuid4()}"),
        status=status,
        expires_at=expires_at,
        consumed_at=terminal_at,
    )
    session.add(row)
    session.flush()
    return row


def _auth_session(
    session: Session,
    user: User,
    *,
    status: str,
    expires_at: datetime,
    revoked_at: datetime | None,
) -> AuthSession:
    row = AuthSession(
        user_id=user.id,
        token_hash=keyed_hash(f"session-{uuid.uuid4()}"),
        status=status,
        expires_at=expires_at,
        last_seen_at=expires_at - timedelta(minutes=1),
        revoked_at=revoked_at,
    )
    session.add(row)
    session.flush()
    return row


def _policy(*, mode: str = "anonymise") -> RetentionPolicy:
    return RetentionPolicy(
        None,
        None,
        None,
        None,
        None,
        mode,
        login_attempt_days=5,
        auth_session_days=5,
    )


def test_retention_expires_live_rows_and_erases_only_strictly_older_history(
    db_session: Session,
) -> None:
    user = _user(db_session)
    old = NOW - timedelta(days=6)
    boundary = NOW - timedelta(days=5)
    pending_old = _attempt(
        db_session,
        status="pending",
        terminal_at=None,
        expires_at=old,
    )
    consumed_old = _attempt(
        db_session,
        status="consumed",
        terminal_at=old,
        expires_at=old,
    )
    consumed_boundary = _attempt(
        db_session,
        status="consumed",
        terminal_at=boundary,
        expires_at=boundary,
    )
    expired_active = _auth_session(
        db_session,
        user,
        status="active",
        expires_at=old,
        revoked_at=None,
    )
    revoked_boundary = _auth_session(
        db_session,
        user,
        status="revoked",
        expires_at=boundary,
        revoked_at=boundary,
    )
    original_values = {
        pending_old.opaque_id,
        pending_old.lookup_hash,
        consumed_old.opaque_id,
        consumed_old.lookup_hash,
        expired_active.token_hash,
    }

    counts = purge_expired(db_session, now=NOW, policy=_policy())

    assert counts["login_attempts_expired"] == 1
    assert counts["auth_sessions_expired"] == 1
    assert counts["login_attempts"] == 2
    assert counts["auth_sessions"] == 1
    for row in (pending_old, consumed_old):
        assert row.status == "erased"
        assert row.registration_id is None and row.challenge_id is None
        assert len(row.opaque_id) == len(row.lookup_hash) == 64
        assert row.opaque_id not in original_values
        assert row.lookup_hash not in original_values
        assert row.metadata_json is None
        assert all(
            value.replace(tzinfo=timezone.utc) == EPOCH
            for value in (
                row.created_at,
                row.updated_at,
                row.deleted_at,
                row.expires_at,
                row.consumed_at,
            )
        )
    assert consumed_boundary.status == "consumed"
    assert expired_active.status == "erased"
    assert expired_active.user_id is None
    assert len(expired_active.token_hash) == 64
    assert expired_active.token_hash not in original_values
    assert revoked_boundary.status == "revoked"

    event = db_session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "student.auth.retention_applied")
        .order_by(AuditEvent.created_at.desc())
    )
    assert event is not None
    assert event.actor_user_id is None and event.resource_id is None
    assert event.after_state == {
        "mode": "anonymise",
        "expired_sessions": 1,
        "expired_attempts": 1,
        "login_attempts": 2,
        "auth_sessions": 1,
    }


def test_delete_mode_removes_terminal_attempts_and_sessions(db_session: Session) -> None:
    user = _user(db_session)
    old = NOW - timedelta(days=6)
    attempt = _attempt(
        db_session,
        status="expired",
        terminal_at=old,
        expires_at=old,
    )
    auth_session = _auth_session(
        db_session,
        user,
        status="revoked",
        expires_at=old,
        revoked_at=old,
    )

    counts = purge_expired(db_session, now=NOW, policy=_policy(mode="delete"))

    assert counts["login_attempts"] == counts["auth_sessions"] == 1
    assert db_session.get(LoginAttempt, attempt.id) is None
    assert db_session.get(AuthSession, auth_session.id) is None
    assert db_session.get(User, user.id) is not None


def test_invalid_policy_is_rejected_before_expiry_mutation(db_session: Session) -> None:
    user = _user(db_session)
    attempt = _attempt(
        db_session,
        status="pending",
        terminal_at=None,
        expires_at=NOW - timedelta(days=2),
    )
    auth_session = _auth_session(
        db_session,
        user,
        status="active",
        expires_at=NOW - timedelta(days=2),
        revoked_at=None,
    )
    db_session.flush()

    with pytest.raises(ValueError):
        purge_expired(
            db_session,
            now=NOW,
            policy=RetentionPolicy(
                None,
                None,
                None,
                None,
                None,
                "anonymise",
                login_attempt_days=0,
                auth_session_days=5,
            ),
        )

    assert attempt.status == "pending" and attempt.consumed_at is None
    assert auth_session.status == "active" and auth_session.revoked_at is None
    assert db_session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_pending_attempt_expiry_alone_emits_complete_non_pii_aggregate_audit(
    db_session: Session,
) -> None:
    attempt = _attempt(
        db_session,
        status="pending",
        terminal_at=None,
        expires_at=NOW - timedelta(seconds=1),
    )

    counts = purge_expired(
        db_session,
        now=NOW,
        policy=RetentionPolicy(None, None, None, None, None, "anonymise"),
    )

    assert counts["auth_sessions_expired"] == 0
    assert counts["login_attempts_expired"] == 1
    assert counts["login_attempts"] == 0
    assert counts["auth_sessions"] == 0
    assert attempt.status == "expired"
    assert attempt.consumed_at == attempt.expires_at
    events = list(
        db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "student.auth.retention_applied"
            )
        )
    )
    assert len(events) == 1
    event = events[0]
    assert event.actor_user_id is None and event.resource_id is None
    assert event.before_state is None
    assert event.after_state == {
        "mode": "anonymise",
        "expired_sessions": 0,
        "expired_attempts": 1,
        "login_attempts": 0,
        "auth_sessions": 0,
    }


def _registration(session: Session, mobile: str) -> StudentRegistration:
    result = register_student(
        session,
        StudentRegisterRequest(
            first_name="Aditi",
            last_name="Nair",
            mobile=mobile,
            dob="2004-03-14",
            consent={"accepted": True},
        ),
        now=NOW,
    )
    return result.registration


def test_explicit_anonymise_tombstones_auth_history_and_blocks_user(
    db_session: Session,
) -> None:
    registration = _registration(db_session, "9876543210")
    user = db_session.get(User, registration.user_id)
    attempt = LoginAttempt(
        opaque_id=uuid.uuid4().hex,
        lookup_hash=registration.mobile_hash,
        registration_id=registration.id,
        status="expired",
        expires_at=NOW - timedelta(days=1),
        consumed_at=NOW - timedelta(days=1),
    )
    auth_session = _auth_session(
        db_session,
        user,
        status="active",
        expires_at=NOW + timedelta(days=1),
        revoked_at=None,
    )
    db_session.add(attempt)
    db_session.flush()

    anonymise_registration(db_session, registration)
    db_session.flush()

    assert registration.status == "deleted"
    assert user.status == "deleted"
    assert attempt.status == "erased" and attempt.registration_id is None
    assert auth_session.status == "erased" and auth_session.user_id is None
    assert db_session.scalar(
        select(func.count())
        .select_from(AuthSession)
        .where(AuthSession.status == "active")
    ) == 0


def test_explicit_hard_delete_removes_auth_history_and_user(db_session: Session) -> None:
    registration = _registration(db_session, "9876543210")
    user = db_session.get(User, registration.user_id)
    attempt = LoginAttempt(
        opaque_id=uuid.uuid4().hex,
        lookup_hash=registration.mobile_hash,
        registration_id=registration.id,
        status="expired",
        expires_at=NOW - timedelta(days=1),
        consumed_at=NOW - timedelta(days=1),
    )
    auth_session = _auth_session(
        db_session,
        user,
        status="active",
        expires_at=NOW + timedelta(days=1),
        revoked_at=None,
    )
    db_session.add(attempt)
    db_session.flush()
    user_id = user.id

    delete_registration(db_session, registration)
    db_session.flush()

    assert db_session.get(LoginAttempt, attempt.id) is None
    assert db_session.get(AuthSession, auth_session.id) is None
    assert db_session.get(StudentRegistration, registration.id) is None
    assert db_session.get(User, user_id) is None


@pytest.mark.parametrize(
    "erase",
    (anonymise_registration, delete_registration),
    ids=("anonymise", "delete"),
)
def test_explicit_erasure_transaction_rollback_restores_auth_graph(
    db_session: Session,
    erase: Callable[[Session, StudentRegistration], None],
) -> None:
    registration = _registration(db_session, "9876543210")
    user = db_session.get(User, registration.user_id)
    attempt = LoginAttempt(
        opaque_id=uuid.uuid4().hex,
        lookup_hash=registration.mobile_hash,
        registration_id=registration.id,
        status="expired",
        expires_at=NOW - timedelta(days=1),
        consumed_at=NOW - timedelta(days=1),
    )
    auth_session = _auth_session(
        db_session,
        user,
        status="active",
        expires_at=NOW + timedelta(days=1),
        revoked_at=None,
    )
    db_session.add(attempt)
    db_session.commit()
    ids = (registration.id, user.id, attempt.id, auth_session.id)
    audit_count = db_session.scalar(select(func.count()).select_from(AuditEvent))
    before = (
        registration.status,
        registration.mobile_hash,
        user.status,
        attempt.opaque_id,
        attempt.lookup_hash,
        attempt.registration_id,
        attempt.status,
        auth_session.user_id,
        auth_session.token_hash,
        auth_session.status,
    )

    try:
        erase(db_session, registration)
        db_session.flush()
        raise RuntimeError("forced post-auth-erasure failure")
    except RuntimeError:
        db_session.rollback()

    registration = db_session.get(StudentRegistration, ids[0])
    user = db_session.get(User, ids[1])
    attempt = db_session.get(LoginAttempt, ids[2])
    auth_session = db_session.get(AuthSession, ids[3])
    assert registration is not None and user is not None
    assert attempt is not None and auth_session is not None
    assert (
        registration.status,
        registration.mobile_hash,
        user.status,
        attempt.opaque_id,
        attempt.lookup_hash,
        attempt.registration_id,
        attempt.status,
        auth_session.user_id,
        auth_session.token_hash,
        auth_session.status,
    ) == before
    assert (
        db_session.scalar(select(func.count()).select_from(AuditEvent))
        == audit_count
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("retention_days_login_attempt", 0),
        ("retention_days_auth_session", True),
        ("retention_days_login_attempt", "01"),
        ("retention_days_auth_session", 36_501),
    ],
)
def test_auth_retention_config_rejects_unsafe_values(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, **{field: value})


def test_auth_retention_config_accepts_null_and_canonical_days() -> None:
    configured = Settings(
        _env_file=None,
        retention_days_login_attempt="30",
        retention_days_auth_session=None,
    )
    assert configured.retention_days_login_attempt == 30
    assert configured.retention_days_auth_session is None
    blank = Settings(
        _env_file=None,
        retention_days_login_attempt="",
        retention_days_auth_session="",
    )
    assert blank.retention_days_login_attempt is None
    assert blank.retention_days_auth_session is None


def test_shipped_env_example_loads_all_blank_retention_windows_as_none() -> None:
    configured = Settings(
        _env_file=Path(__file__).resolve().parents[2] / ".env.example"
    )
    assert {
        configured.retention_days_registration_pending,
        configured.retention_days_registration_inactive,
        configured.retention_days_otp_challenge,
        configured.retention_days_recovery_session,
        configured.retention_days_login_attempt,
        configured.retention_days_auth_session,
        configured.retention_days_audit_events,
    } == {None}
