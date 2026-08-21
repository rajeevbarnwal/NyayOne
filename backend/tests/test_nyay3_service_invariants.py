"""Focused service tests for NYAY-3 parent locks and typed race handling."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import encrypt, keyed_hash, otp_verifier
from app.models.registration import (
    AuthSession,
    Consent,
    LoginAttempt,
    OtpChallenge,
    OtpOutbox,
    StudentRegistration,
    User,
)
from app.schemas.registration import StudentRegisterRequest
from app.services import login_service, otp_outbox, otp_service, recovery_service
from app.services.otp_sender import CapturingSender
from app.services.registration_service import register_student

NOW = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
MOBILE = "9876543210"


class _Diagnostic:
    def __init__(self, constraint_name: str) -> None:
        self.constraint_name = constraint_name


class _DriverFailure(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.diag = _Diagnostic(constraint_name)


def _integrity_error(constraint_name: str) -> IntegrityError:
    return IntegrityError(
        "statement redacted",
        {},
        _DriverFailure(constraint_name),
    )


def _registered(session: Session, *, login_eligible: bool = False) -> StudentRegistration:
    request = StudentRegisterRequest(
        first_name="Aditi",
        last_name="Nair",
        mobile=MOBILE,
        dob="2004-03-14",
        consent={"accepted": True},
    )
    result = register_student(session, request, now=NOW)
    registration = result.registration
    if login_eligible:
        registration.status = "otp_verified"
        user = session.get(User, registration.user_id)
        assert user is not None
        user.status = "active"
    session.commit()
    assert result.delivery is not None
    assert otp_outbox.run_delivery(
        session,
        result.delivery,
        CapturingSender(),
        raise_on_failure=True,
        now=NOW,
    )
    return registration


def _login_attempt(session: Session) -> tuple[str, str]:
    user = User(role="student", status="active")
    session.add(user)
    session.flush()
    registration = StudentRegistration(
        user_id=user.id,
        first_name="Aditi",
        last_name="Nair",
        mobile_hash=keyed_hash(MOBILE),
        mobile_ct=encrypt(MOBILE),
        dob_hash=keyed_hash("2004-03-14"),
        dob_ct=encrypt("2004-03-14"),
        dob_hash_state="verified",
        status="otp_verified",
        is_minor=False,
    )
    session.add(registration)
    session.flush()
    session.add(
        Consent(
            registration_id=registration.id,
            accepted=True,
            policy_version="v1",
        )
    )
    salt = uuid.uuid4().hex
    code = "654321"
    authority = otp_service.authority_for_registration(
        session, registration, "login", NOW
    )
    authority.last_issued_at = NOW
    authority.active_expires_at = NOW + timedelta(minutes=5)
    authority.generation = 1
    challenge = OtpChallenge(
        registration_id=registration.id,
        authority_id=authority.id,
        purpose="login",
        verifier_hash=otp_verifier(code, salt=salt),
        attempts=0,
        max_attempts=3,
        expires_at=NOW + timedelta(minutes=5),
        delivery_state="active",
        metadata_json={"salt": salt},
    )
    session.add(challenge)
    session.flush()
    attempt = LoginAttempt(
        opaque_id=uuid.uuid4().hex,
        lookup_hash=registration.mobile_hash,
        registration_id=registration.id,
        challenge_id=challenge.id,
        status="pending",
        expires_at=NOW + timedelta(minutes=10),
    )
    session.add(attempt)
    session.commit()
    return attempt.opaque_id, code


def test_otp_named_unique_race_is_typed_and_savepoint_preserves_prior(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration = _registered(db_session)
    prior = db_session.scalar(
        select(OtpChallenge).where(
            OtpChallenge.registration_id == registration.id,
            OtpChallenge.purpose == "signup",
            OtpChallenge.consumed_at.is_(None),
        )
    )
    assert prior is not None

    def reject_enqueue(*args, **kwargs):
        raise _integrity_error(otp_service.ACTIVE_OTP_CONSTRAINT)

    monkeypatch.setattr(otp_outbox, "enqueue", reject_enqueue)
    with pytest.raises(otp_service.OtpError) as caught:
        otp_service.issue_challenge(
            db_session,
            registration.id,
            NOW + timedelta(seconds=31),
            purpose="signup",
            destination=MOBILE,
        )
    assert (caught.value.status_code, caught.value.code) == (
        409,
        "otp_issue_conflict",
    )

    active = db_session.scalars(
        select(OtpChallenge).where(
            OtpChallenge.registration_id == registration.id,
            OtpChallenge.purpose == "signup",
            OtpChallenge.consumed_at.is_(None),
        )
    ).all()
    assert [row.id for row in active] == [prior.id]


def test_login_rotation_named_unique_race_is_typed_and_retryable(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opaque_id, code = _login_attempt(db_session)
    original_flush = db_session.flush
    armed = True

    def fail_auth_session_flush(objects=None):
        nonlocal armed
        if armed and any(isinstance(row, AuthSession) for row in db_session.new):
            armed = False
            raise _integrity_error(login_service.ACTIVE_SESSION_CONSTRAINT)
        return original_flush(objects)

    monkeypatch.setattr(db_session, "flush", fail_auth_session_flush)
    with pytest.raises(login_service.LoginError) as caught:
        login_service.verify(db_session, opaque_id, code, NOW)
    assert (caught.value.status_code, caught.value.code) == (409, "login_conflict")

    attempt = db_session.scalar(
        select(LoginAttempt).where(LoginAttempt.opaque_id == opaque_id)
    )
    assert attempt is not None
    challenge = db_session.get(OtpChallenge, attempt.challenge_id)
    assert attempt.status == "pending" and attempt.consumed_at is None
    assert challenge is not None and challenge.consumed_at is None
    assert db_session.scalar(select(AuthSession)) is None

    _, auth_session = login_service.verify(db_session, opaque_id, code, NOW)
    assert auth_session.status == "active"


def test_login_start_locks_before_cooldown_and_contains_otp_conflict(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registered(db_session, login_eligible=True)
    events: list[str] = []
    original_lock = otp_service.lock_registration_for_update

    def recording_lock(session: Session, registration_id: uuid.UUID):
        events.append("lock")
        return original_lock(session, registration_id)

    def no_recent(*args, **kwargs) -> bool:
        events.append("cooldown")
        return False

    def race(*args, **kwargs):
        raise otp_service.OtpError(409, "otp_issue_conflict")

    monkeypatch.setattr(otp_service, "lock_registration_for_update", recording_lock)
    monkeypatch.setattr(login_service, "_recent_attempt", no_recent)
    monkeypatch.setattr(otp_service, "issue_challenge", race)

    opaque_id, intent = login_service.start(db_session, MOBILE, NOW)
    assert events == ["lock", "cooldown"]
    assert intent is None
    attempt = db_session.scalar(
        select(LoginAttempt).where(LoginAttempt.opaque_id == opaque_id)
    )
    assert attempt is not None and attempt.challenge_id is None


def test_recovery_start_locks_before_cooldown_and_contains_otp_conflict(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registered(db_session)
    events: list[str] = []
    original_lock = otp_service.lock_registration_for_update

    def recording_lock(session: Session, registration_id: uuid.UUID):
        events.append("lock")
        return original_lock(session, registration_id)

    def no_recent(*args, **kwargs) -> bool:
        events.append("cooldown")
        return False

    def race(*args, **kwargs):
        raise otp_service.OtpError(409, "otp_issue_conflict")

    monkeypatch.setattr(otp_service, "lock_registration_for_update", recording_lock)
    monkeypatch.setattr(recovery_service, "_recent_recovery_excluding", no_recent)
    monkeypatch.setattr(otp_service, "issue_challenge", race)

    opaque_id, intent = recovery_service.start(db_session, MOBILE, NOW)
    assert events == ["lock", "cooldown"]
    assert intent is None
    recovery = db_session.scalar(
        select(recovery_service.RecoverySession).where(
            recovery_service.RecoverySession.opaque_id == opaque_id
        )
    )
    assert recovery is not None and recovery.challenge_id is None


def test_superseded_challenge_erases_and_voids_prior_delivery(
    db_session: Session,
) -> None:
    registration = _registered(db_session)
    prior = db_session.scalar(
        select(OtpChallenge).where(
            OtpChallenge.registration_id == registration.id,
            OtpChallenge.purpose == "signup",
            OtpChallenge.consumed_at.is_(None),
        )
    )
    assert prior is not None
    prior_outbox = db_session.scalar(
        select(OtpOutbox).where(OtpOutbox.challenge_id == prior.id)
    )
    assert prior_outbox is not None
    assert prior_outbox.status == "sent" and prior_outbox.code_ct is None
    stale_intent = otp_outbox.DeliveryIntent(outbox_id=prior_outbox.id)

    candidate, replacement_intent = otp_service.issue_challenge(
        db_session,
        registration.id,
        NOW + timedelta(seconds=31),
        purpose="signup",
        destination=MOBILE,
    )
    db_session.commit()

    # A resend candidate cannot displace the usable code until its provider
    # delivery succeeds under the fenced outbox claim.
    db_session.refresh(prior)
    assert prior.delivery_state == "active" and prior.consumed_at is None
    assert candidate.delivery_state == "pending_delivery"
    assert candidate.consumed_at is not None
    sender = CapturingSender()
    assert otp_outbox.run_delivery(
        db_session,
        replacement_intent,
        sender,
        raise_on_failure=True,
        now=NOW + timedelta(seconds=31),
    )

    db_session.refresh(prior)
    db_session.refresh(candidate)
    db_session.refresh(prior_outbox)
    assert prior.delivery_state == "superseded"
    assert prior.consumed_at is not None
    assert candidate.delivery_state == "active"
    assert candidate.consumed_at is None
    assert prior_outbox.status == "sent"
    assert prior_outbox.code_ct is None
    assert len(sender.sent) == 1
    assert (
        otp_outbox.run_delivery(
            db_session,
            stale_intent,
            sender,
            raise_on_failure=False,
        )
        is False
    )
    assert len(sender.sent) == 1
