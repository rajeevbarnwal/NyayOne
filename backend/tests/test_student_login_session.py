"""Security contract for student OTP login and cookie-backed sessions."""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import auth_student, student_settings
from app.core.auth import ActorContext, Role
from app.core.config import settings
from app.core.crypto import keyed_hash
from app.core.exceptions import register_exception_handlers
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import (
    AuthSession,
    GuardianConsent,
    LoginAttempt,
    OtpChallenge,
    OtpOutbox,
    RecoverySession,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)
from tests import dbtemplate


class CapturingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, destination: str, code: str) -> None:
        self.sent.append((destination, code))


class CommitFailSession(Session):
    armed = False

    def commit(self):  # type: ignore[override]
        if type(self).armed:
            type(self).armed = False
            raise RuntimeError("forced commit failure")
        return super().commit()


def _context(
    session_class: type[Session] = Session,
    *,
    base_url: str = "http://testserver",
):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    dbtemplate.create_all(engine)
    factory = sessionmaker(
        bind=engine, expire_on_commit=False, class_=session_class
    )

    def request_session():
        session = factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        else:
            session.rollback()
        finally:
            session.close()

    sender = CapturingSender()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_student.router, prefix="/api/v1")
    app.include_router(student_settings.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[auth_student.get_otp_sender] = lambda: sender
    app.dependency_overrides[auth_student.get_outbox_session_factory] = lambda: factory
    return (
        TestClient(
            app,
            base_url=base_url,
            raise_server_exceptions=False,
        ),
        engine,
        factory,
        sender,
    )


@pytest.fixture()
def ctx():
    context = _context()
    yield context
    context[0].close()
    context[1].dispose()


def _create_account(
    client: TestClient,
    sender: CapturingSender,
    mobile="9876543210",
    *,
    dob: str = "2004-03-14",
    keep_session: bool = False,
):
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/student/register",
        json={
            "first_name": "Aditi",
            "last_name": "Nair",
            "mobile": mobile,
            "dob": dob,
            "consent": {"accepted": True},
        },
    )
    assert response.status_code == 201
    signup_code = sender.sent[-1][1]
    verified = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"registration_id": response.json()["registration_id"], "code": signup_code},
    )
    assert verified.status_code == 200
    assert "HttpOnly" in verified.headers["set-cookie"]
    if not keep_session:
        client.cookies.clear()
    return response.json()["registration_id"], signup_code


def _start_login(client: TestClient, sender: CapturingSender, mobile="9876543210"):
    before = len(sender.sent)
    response = client.post(
        "/api/v1/auth/student/login/otp/start", json={"mobile": mobile}
    )
    assert response.status_code == 202
    assert set(response.json()) == {"login_id"}
    code = sender.sent[-1][1] if len(sender.sent) > before else None
    return response.json()["login_id"], code


def _use_session_cookie(client: TestClient, token: str) -> None:
    """Replace the browser cookie without leaving a second scoped value."""

    client.cookies.clear()
    client.cookies.set(settings.auth_session_cookie_name, token)


def _set_trusted_origin(client: TestClient) -> None:
    client.headers["Origin"] = settings.cors_origins[0]


def _remove_default_origin(client: TestClient) -> None:
    if "Origin" in client.headers:
        del client.headers["Origin"]


def _signup_session(
    client: TestClient,
    sender: CapturingSender,
    *,
    mobile: str,
    dob: str = "2004-03-14",
) -> tuple[str, str]:
    registration_id, _ = _create_account(
        client,
        sender,
        mobile,
        dob=dob,
        keep_session=True,
    )
    token = client.cookies.get(settings.auth_session_cookie_name)
    assert token
    return registration_id, token


def _academic_payload() -> dict[str, str]:
    return {
        "college": "National Law School of India University",
        "year_of_study": "3rd year",
        "enrolment_number": "KA/1234/2023",
        "institutional_email": "aditi@nls.ac.in",
    }


def test_signup_otp_verification_mints_authenticated_http_only_session(ctx):
    client, _, factory, sender = ctx
    registration_id, token = _signup_session(
        client, sender, mobile="9876543210"
    )
    assert token not in client.get("/api/v1/auth/student/session").text
    discovered = client.get("/api/v1/auth/student/session")
    assert discovered.status_code == 200
    assert discovered.json()["authenticated"] is True
    with factory() as session:
        registration = session.get(
            StudentRegistration, uuid.UUID(registration_id)
        )
        assert discovered.json()["actor"]["sub"] == str(registration.user_id)
        assert session.scalar(
            select(func.count())
            .select_from(AuthSession)
            .where(AuthSession.status == "active")
        ) == 1


def test_three_registration_owner_resolution_cannot_hide_second_valid_row(ctx):
    client, _, factory, sender = ctx
    registration_id, token = _signup_session(
        client, sender, mobile="9876543210"
    )
    now = datetime.now(timezone.utc)
    with factory() as session:
        primary = session.get(
            StudentRegistration, uuid.UUID(registration_id)
        )
        user_id = primary.user_id
        # Insert an ineligible newer row between two eligible registrations.
        # A LIMIT applied before the authority predicate would see only the
        # invalid row plus one eligible row and incorrectly grant access.
        invalid = StudentRegistration(
            user_id=user_id,
            first_name="Invalid",
            last_name="Registration",
            mobile_hash=keyed_hash("9876543211"),
            mobile_ct=primary.mobile_ct,
            dob_hash=keyed_hash("2001-01-01"),
            dob_ct=primary.dob_ct,
            dob_hash_state="quarantined",
            key_version=primary.key_version,
            status="active",
            is_minor=False,
        )
        second_valid = StudentRegistration(
            user_id=user_id,
            first_name="Second",
            last_name="Registration",
            mobile_hash=keyed_hash("9876543212"),
            mobile_ct=primary.mobile_ct,
            dob_hash=keyed_hash("2002-02-02"),
            dob_ct=primary.dob_ct,
            dob_hash_state="verified",
            key_version=primary.key_version,
            status="active",
            is_minor=False,
        )
        session.add_all([invalid, second_valid])
        session.flush()
        primary.created_at = now - timedelta(minutes=1)
        invalid.created_at = now
        second_valid.created_at = now - timedelta(minutes=2)
        actor = ActorContext(
            user_id=user_id,
            roles=frozenset({Role.STUDENT}),
        )
        active_session = session.scalar(
            select(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.status == "active",
            )
        )
        last_seen_before = active_session.last_seen_at
        with pytest.raises(HTTPException) as exc:
            auth_student._owned_registration(session, actor)
        assert exc.value.status_code == 404
        session.commit()

    _use_session_cookie(client, token)
    before = client.get("/api/v1/auth/student/session")
    assert before.status_code == 200
    assert before.json() == {"authenticated": False, "actor": None}
    denied = client.patch(
        "/api/v1/auth/student/profile",
        json=_academic_payload(),
    )
    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "authentication_required"
    with factory() as session:
        active_session = session.scalar(
            select(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.status == "active",
            )
        )
        assert active_session.last_seen_at == last_seen_before


def test_activated_signup_uuid_cannot_resend_reverify_or_rotate_session(ctx):
    client, _, factory, sender = ctx
    registration_id, token = _signup_session(
        client, sender, mobile="9876543210"
    )
    signup_code = sender.sent[0][1]
    delivered_before = list(sender.sent)

    def snapshot(session: Session):
        registration = session.get(
            StudentRegistration, uuid.UUID(registration_id)
        )
        return {
            "registration": (
                registration.status,
                registration.updated_at,
                registration.deleted_at,
            ),
            "challenges": [
                (
                    row.id,
                    row.purpose,
                    row.attempts,
                    row.consumed_at,
                    row.locked_until,
                )
                for row in session.scalars(
                    select(OtpChallenge).order_by(OtpChallenge.id)
                )
            ],
            "outbox": [
                (row.id, row.status, row.code_ct, row.attempts)
                for row in session.scalars(
                    select(OtpOutbox).order_by(OtpOutbox.id)
                )
            ],
            "sessions": [
                (
                    row.id,
                    row.status,
                    row.token_hash,
                    row.last_seen_at,
                    row.revoked_at,
                )
                for row in session.scalars(
                    select(AuthSession).order_by(AuthSession.id)
                )
            ],
            "audits": [
                (
                    row.id,
                    row.actor_user_id,
                    row.action,
                    row.before_state,
                    row.after_state,
                )
                for row in session.scalars(
                    select(AuditEvent).order_by(AuditEvent.id)
                )
            ],
        }

    with factory() as session:
        before = snapshot(session)
        assert before["registration"][0] == "active"
        active_session = session.scalar(
            select(AuthSession).where(AuthSession.status == "active")
        )
        assert active_session.token_hash == keyed_hash(token)

    resend = client.post(
        "/api/v1/auth/student/otp/resend",
        json={"registration_id": registration_id},
    )
    reverify = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"registration_id": registration_id, "code": signup_code},
    )
    assert resend.status_code == reverify.status_code == 404
    assert resend.json()["detail"]["code"] == "registration_not_found"
    assert reverify.json()["detail"]["code"] == "no_active_challenge"
    assert sender.sent == delivered_before

    with factory() as session:
        assert snapshot(session) == before


@pytest.mark.parametrize("mobile", ["987654321", "98765432101"])
def test_login_mobile_requires_exactly_ten_digits_without_echo(ctx, mobile):
    client, *_ = ctx
    response = client.post(
        "/api/v1/auth/student/login/otp/start", json={"mobile": mobile}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "mobile"
    assert mobile not in response.text


def test_known_and_unknown_start_are_non_enumerating_and_persist_decoy(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    known, known_code = _start_login(client, sender, "9876543210")
    unknown, unknown_code = _start_login(client, sender, "9999999999")
    assert len(known) == len(unknown) == 32
    assert known_code is not None and unknown_code is None
    with factory() as session:
        known_row = session.scalar(
            select(LoginAttempt).where(LoginAttempt.opaque_id == known)
        )
        unknown_row = session.scalar(
            select(LoginAttempt).where(LoginAttempt.opaque_id == unknown)
        )
        assert known_row.registration_id is not None
        assert unknown_row.registration_id is None
        assert len(known_row.lookup_hash) == len(unknown_row.lookup_hash) == 64


def test_quarantined_dob_hash_is_symmetric_decoy_for_login_and_recovery(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    with factory() as session:
        registration = session.scalar(select(StudentRegistration))
        registration.dob_hash = "f" * 64
        registration.dob_hash_state = "quarantined"
        session.commit()

    sender.sent.clear()
    known_login, known_code = _start_login(client, sender, "9876543210")
    unknown_login, unknown_code = _start_login(client, sender, "9999999999")
    assert known_code is unknown_code is None
    with factory() as session:
        attempts = tuple(
            session.scalars(
                select(LoginAttempt).where(
                    LoginAttempt.opaque_id.in_((known_login, unknown_login))
                )
            )
        )
        assert len(attempts) == 2
        assert all(attempt.registration_id is None for attempt in attempts)

    known_recovery = client.post(
        "/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"}
    )
    unknown_recovery = client.post(
        "/api/v1/auth/student/recovery/start", json={"mobile": "9999999999"}
    )
    assert known_recovery.status_code == unknown_recovery.status_code == 202
    assert set(known_recovery.json()) == set(unknown_recovery.json()) == {"recovery_id"}
    assert sender.sent == []


def test_quarantine_change_invalidates_existing_student_session_claims(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender, keep_session=True)
    assert client.get("/api/v1/auth/student/session").json()["authenticated"] is True
    with factory() as session:
        registration = session.scalar(select(StudentRegistration))
        registration.dob_hash = "f" * 64
        registration.dob_hash_state = "quarantined"
        session.commit()
    assert client.get("/api/v1/auth/student/session").json() == {
        "authenticated": False,
        "actor": None,
    }


def test_quarantine_change_blocks_pending_login_and_recovery_proofs(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    login_id, login_code = _start_login(client, sender)
    recovery_start = client.post(
        "/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"}
    )
    recovery_id = recovery_start.json()["recovery_id"]
    recovery_code = sender.sent[-1][1]
    with factory() as session:
        registration = session.scalar(select(StudentRegistration))
        registration.dob_hash = "f" * 64
        registration.dob_hash_state = "quarantined"
        session.commit()

    login_result = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": login_code},
    )
    recovery_result = client.post(
        "/api/v1/auth/student/recovery/verify",
        json={"recovery_id": recovery_id, "code": recovery_code},
    )
    unknown_login = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": uuid.uuid4().hex, "code": login_code},
    )
    unknown_recovery = client.post(
        "/api/v1/auth/student/recovery/verify",
        json={"recovery_id": uuid.uuid4().hex, "code": recovery_code},
    )
    assert login_result.status_code == unknown_login.status_code == 401
    assert recovery_result.status_code == unknown_recovery.status_code == 401
    assert login_result.json() == unknown_login.json()
    assert recovery_result.json() == unknown_recovery.json()

    with factory() as session:
        recovery = session.scalar(
            select(RecoverySession).where(RecoverySession.opaque_id == recovery_id)
        )
        recovery.status = "verified"
        session.commit()
    completion = client.post(
        "/api/v1/auth/student/recovery/complete",
        json={"recovery_id": recovery_id},
    )
    unknown_completion = client.post(
        "/api/v1/auth/student/recovery/complete",
        json={"recovery_id": uuid.uuid4().hex},
    )
    assert completion.status_code == unknown_completion.status_code == 401
    assert completion.json() == unknown_completion.json()


def test_quarantined_onboarding_capabilities_match_missing_registration(ctx):
    client, _, factory, sender = ctx
    registration_id, _ = _create_account(client, sender)
    with factory() as session:
        registration = session.get(StudentRegistration, uuid.UUID(registration_id))
        registration.dob_hash = "f" * 64
        registration.dob_hash_state = "quarantined"
        session.commit()
    missing_id = str(uuid.uuid4())

    quarantined_resend = client.post(
        "/api/v1/auth/student/otp/resend",
        json={"registration_id": registration_id},
    )
    missing_resend = client.post(
        "/api/v1/auth/student/otp/resend",
        json={"registration_id": missing_id},
    )
    assert quarantined_resend.status_code == missing_resend.status_code == 404
    assert quarantined_resend.json() == missing_resend.json()
    assert quarantined_resend.json()["detail"]["code"] == "registration_not_found"

    profile = {
        "college": "National Law School of India University",
        "year_of_study": "3rd year",
        "enrolment_number": "KA/1234/2023",
        "institutional_email": "aditi@nls.ac.in",
    }
    quarantined_profile = client.patch(
        "/api/v1/auth/student/profile",
        json=profile,
    )
    missing_profile = client.patch(
        "/api/v1/auth/student/profile",
        json=profile,
    )
    assert quarantined_profile.status_code == missing_profile.status_code == 401
    assert quarantined_profile.json() == missing_profile.json()
    assert quarantined_profile.json()["detail"]["code"] == "authentication_required"

    guardian = client.post(
        "/api/v1/auth/student/guardian-consent/complete",
        json={},
    )
    missing_guardian = client.post(
        "/api/v1/auth/student/guardian-consent/complete",
        json={},
    )
    assert guardian.status_code == missing_guardian.status_code == 401
    assert guardian.json() == missing_guardian.json()

    email_request = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={"institutional_email": "aditi@nls.ac.in"},
    )
    missing_email_request = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={"institutional_email": "aditi@nls.ac.in"},
    )
    assert email_request.status_code == missing_email_request.status_code == 401
    assert email_request.json() == missing_email_request.json()

    verification = client.get(
        "/api/v1/auth/student/verification/status",
    )
    missing_verification = client.get(
        "/api/v1/auth/student/verification/status",
    )
    assert verification.status_code == missing_verification.status_code == 401
    assert verification.json() == missing_verification.json()

    transition = client.post(
        "/api/v1/auth/student/verification/status",
        json={"registration_id": registration_id, "status": "in_review"},
        headers={
            "X-Actor-Claims": json.dumps(
                {"sub": str(uuid.uuid4()), "roles": ["legal_reviewer"]}
            )
        },
    )
    missing_transition = client.post(
        "/api/v1/auth/student/verification/status",
        json={"registration_id": missing_id, "status": "in_review"},
        headers={
            "X-Actor-Claims": json.dumps(
                {"sub": str(uuid.uuid4()), "roles": ["legal_reviewer"]}
            )
        },
    )
    assert transition.status_code == missing_transition.status_code == 404
    assert transition.json() == missing_transition.json()
    with factory() as session:
        stored = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id == uuid.UUID(registration_id)
            )
        )
        assert stored is not None and stored.status == "pending"


def test_quarantined_registration_cannot_consume_active_signup_otp(ctx):
    client, _, factory, sender = ctx
    response = client.post(
        "/api/v1/auth/student/register",
        json={
            "first_name": "Aditi",
            "last_name": "Nair",
            "mobile": "9876543210",
            "dob": "2004-03-14",
            "consent": {"accepted": True},
        },
    )
    assert response.status_code == 201
    registration_id = response.json()["registration_id"]
    code = sender.sent[-1][1]
    with factory() as session:
        registration = session.get(StudentRegistration, uuid.UUID(registration_id))
        registration.dob_hash = "f" * 64
        registration.dob_hash_state = "quarantined"
        challenge = session.scalar(
            select(OtpChallenge).where(
                OtpChallenge.registration_id == registration.id,
                OtpChallenge.purpose == "signup",
            )
        )
        before = (challenge.attempts, challenge.consumed_at, challenge.locked_until)
        session.commit()

    blocked = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"registration_id": registration_id, "code": code},
    )
    missing = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"registration_id": str(uuid.uuid4()), "code": code},
    )
    assert blocked.status_code == missing.status_code == 404
    assert blocked.json() == missing.json()
    assert blocked.json()["detail"]["code"] == "no_active_challenge"
    with factory() as session:
        challenge = session.scalar(
            select(OtpChallenge).where(
                OtpChallenge.registration_id == uuid.UUID(registration_id),
                OtpChallenge.purpose == "signup",
            )
        )
        assert (challenge.attempts, challenge.consumed_at, challenge.locked_until) == before


def test_soft_deleted_registration_cannot_use_signup_otp_capability(ctx):
    client, _, factory, sender = ctx
    registered = client.post(
        "/api/v1/auth/student/register",
        json={
            "first_name": "Aditi",
            "last_name": "Nair",
            "mobile": "9876543210",
            "dob": "2004-03-14",
            "consent": {"accepted": True},
        },
    )
    assert registered.status_code == 201
    registration_id = registered.json()["registration_id"]
    code = sender.sent[-1][1]
    with factory() as session:
        registration = session.get(
            StudentRegistration, uuid.UUID(registration_id)
        )
        registration.deleted_at = datetime.now(timezone.utc)
        session.commit()
        challenge = session.scalar(
            select(OtpChallenge).where(
                OtpChallenge.registration_id == registration.id
            )
        )
        challenge_before = (
            challenge.attempts,
            challenge.consumed_at,
            challenge.locked_until,
        )
        challenge_count = session.scalar(
            select(func.count()).select_from(OtpChallenge)
        )
        outbox_count = session.scalar(
            select(func.count()).select_from(OtpOutbox)
        )
        audit_count = session.scalar(
            select(func.count()).select_from(AuditEvent)
        )
        auth_session_count = session.scalar(
            select(func.count()).select_from(AuthSession)
        )

    missing_id = str(uuid.uuid4())
    deleted_resend = client.post(
        "/api/v1/auth/student/otp/resend",
        json={"registration_id": registration_id},
    )
    missing_resend = client.post(
        "/api/v1/auth/student/otp/resend",
        json={"registration_id": missing_id},
    )
    assert deleted_resend.status_code == missing_resend.status_code == 404
    assert deleted_resend.json() == missing_resend.json()
    deleted_verify = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"registration_id": registration_id, "code": code},
    )
    missing_verify = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"registration_id": missing_id, "code": code},
    )
    assert deleted_verify.status_code == missing_verify.status_code == 404
    assert deleted_verify.json() == missing_verify.json()

    with factory() as session:
        challenge = session.scalar(
            select(OtpChallenge).where(
                OtpChallenge.registration_id == uuid.UUID(registration_id)
            )
        )
        assert (
            challenge.attempts,
            challenge.consumed_at,
            challenge.locked_until,
        ) == challenge_before
        assert session.scalar(
            select(func.count()).select_from(OtpChallenge)
        ) == challenge_count
        assert session.scalar(
            select(func.count()).select_from(OtpOutbox)
        ) == outbox_count
        assert session.scalar(
            select(func.count()).select_from(AuditEvent)
        ) == audit_count
        assert session.scalar(
            select(func.count()).select_from(AuthSession)
        ) == auth_session_count


def test_soft_deleted_registration_is_decoy_for_login_and_recovery(ctx):
    client, _, factory, sender = ctx
    registration_id, _ = _create_account(client, sender)
    login_id, login_code = _start_login(client, sender)
    recovery_start = client.post(
        "/api/v1/auth/student/recovery/start",
        json={"mobile": "9876543210"},
    )
    recovery_id = recovery_start.json()["recovery_id"]
    recovery_code = sender.sent[-1][1]
    with factory() as session:
        registration = session.get(
            StudentRegistration, uuid.UUID(registration_id)
        )
        registration.deleted_at = datetime.now(timezone.utc)
        session.commit()
        challenge_count = session.scalar(
            select(func.count()).select_from(OtpChallenge)
        )
        outbox_count = session.scalar(
            select(func.count()).select_from(OtpOutbox)
        )
        session_count = session.scalar(
            select(func.count()).select_from(AuthSession)
        )
        audit_count = session.scalar(
            select(func.count()).select_from(AuditEvent)
        )

    denied_login = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": login_code},
    )
    denied_recovery = client.post(
        "/api/v1/auth/student/recovery/verify",
        json={"recovery_id": recovery_id, "code": recovery_code},
    )
    assert denied_login.status_code == denied_recovery.status_code == 401
    assert denied_login.json()["detail"]["code"] == "login_failed"
    assert denied_recovery.json()["detail"]["code"] == "recovery_failed"

    with factory() as session:
        recovery = session.scalar(
            select(RecoverySession).where(
                RecoverySession.opaque_id == recovery_id
            )
        )
        recovery.status = "verified"
        session.commit()
    denied_complete = client.post(
        "/api/v1/auth/student/recovery/complete",
        json={"recovery_id": recovery_id},
    )
    assert denied_complete.status_code == 401
    assert denied_complete.json()["detail"]["code"] == "recovery_failed"

    sender.sent.clear()
    known_login, known_code = _start_login(client, sender, "9876543210")
    unknown_login, unknown_code = _start_login(client, sender, "9999999999")
    known_recovery = client.post(
        "/api/v1/auth/student/recovery/start",
        json={"mobile": "9876543210"},
    )
    unknown_recovery = client.post(
        "/api/v1/auth/student/recovery/start",
        json={"mobile": "9999999999"},
    )
    assert known_code is unknown_code is None
    assert known_recovery.status_code == unknown_recovery.status_code == 202
    assert set(known_recovery.json()) == set(unknown_recovery.json()) == {
        "recovery_id"
    }
    assert sender.sent == []

    with factory() as session:
        login_attempts = list(
            session.scalars(
                select(LoginAttempt).where(
                    LoginAttempt.opaque_id.in_((known_login, unknown_login))
                )
            )
        )
        recovery_attempts = list(
            session.scalars(
                select(RecoverySession).where(
                    RecoverySession.opaque_id.in_(
                        (
                            known_recovery.json()["recovery_id"],
                            unknown_recovery.json()["recovery_id"],
                        )
                    )
                )
            )
        )
        assert all(row.registration_id is None for row in login_attempts)
        assert all(row.challenge_id is None for row in login_attempts)
        assert all(row.registration_id is None for row in recovery_attempts)
        assert all(row.challenge_id is None for row in recovery_attempts)
        assert session.scalar(
            select(func.count()).select_from(OtpChallenge)
        ) == challenge_count
        assert session.scalar(
            select(func.count()).select_from(OtpOutbox)
        ) == outbox_count
        assert session.scalar(
            select(func.count()).select_from(AuthSession)
        ) == session_count
        assert session.scalar(
            select(func.count()).select_from(AuditEvent)
        ) == audit_count
        recovery = session.scalar(
            select(RecoverySession).where(
                RecoverySession.opaque_id == recovery_id
            )
        )
        assert recovery.status == "verified"


# ---------------------------------------------------------------------------
# NYAY-2: server-derived onboarding ownership and exact cookie Origin.
# ---------------------------------------------------------------------------
def test_protected_onboarding_uses_actor_not_registration_uuid(ctx):
    client, _, factory, sender = ctx
    first_id, first_token = _signup_session(
        client, sender, mobile="9876543210"
    )
    _set_trusted_origin(client)
    saved = client.patch(
        "/api/v1/auth/student/profile", json=_academic_payload()
    )
    assert saved.status_code == 200

    second_id, _ = _signup_session(client, sender, mobile="9123456780")
    _set_trusted_origin(client)
    _use_session_cookie(client, first_token)
    with factory() as session:
        first_session = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == keyed_hash(first_token)
            )
        )
        last_seen_before = first_session.last_seen_at
        audit_count_before = session.scalar(
            select(func.count()).select_from(AuditEvent)
        )
    legacy_cross_owner = client.patch(
        "/api/v1/auth/student/profile",
        json={"registration_id": second_id, **_academic_payload()},
    )
    assert legacy_cross_owner.status_code == 422
    assert legacy_cross_owner.json()["detail"]["code"] == "validation_error"
    legacy_status = client.get(
        "/api/v1/auth/student/verification/status",
        params={"registration_id": second_id},
    )
    assert legacy_status.status_code == 422
    assert legacy_status.json()["detail"]["code"] == "validation_error"
    assert legacy_status.json()["detail"]["field"] == "query"
    legacy_guardian = client.post(
        "/api/v1/auth/student/guardian-consent/complete",
        json={"registration_id": second_id},
    )
    assert legacy_guardian.status_code == 422
    assert legacy_guardian.json()["detail"]["code"] == "validation_error"

    with factory() as session:
        first = session.get(StudentRegistration, uuid.UUID(first_id))
        second_profile = session.scalar(
            select(StudentProfile).where(
                StudentProfile.registration_id == uuid.UUID(second_id)
            )
        )
        assert second_profile is not None
        assert second_profile.enrolment_hash is None
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "student.profile.academic_updated"
            )
        )
        assert audit is not None
        assert audit.actor_user_id == first.user_id
        assert audit.actor_role == "student"
        first_session = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == keyed_hash(first_token)
            )
        )
        assert first_session.last_seen_at == last_seen_before
        assert session.scalar(
            select(func.count()).select_from(AuditEvent)
        ) == audit_count_before
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "student.profile.academic_updated")
        ) == 1

    client.cookies.clear()
    anonymous = client.patch(
        "/api/v1/auth/student/profile",
        json={"registration_id": second_id, **_academic_payload()},
    )
    assert anonymous.status_code == 401
    assert anonymous.json()["detail"]["code"] == "authentication_required"
    wrong_role = client.patch(
        "/api/v1/auth/student/profile",
        json=_academic_payload(),
        headers={
            "X-Actor-Claims": json.dumps(
                {"sub": str(uuid.uuid4()), "roles": ["lawyer"]}
            )
        },
    )
    assert wrong_role.status_code == 403
    assert wrong_role.json()["detail"]["code"] == "forbidden"


def test_quarantined_actor_registration_is_hidden_from_every_owned_route(ctx):
    client, _, factory, sender = ctx
    registration_id, _ = _signup_session(
        client, sender, mobile="9876543210", dob="2012-01-01"
    )
    with factory() as session:
        registration = session.get(
            StudentRegistration, uuid.UUID(registration_id)
        )
        actor_id = registration.user_id
        registration.dob_hash = "f" * 64
        registration.dob_hash_state = "quarantined"
        session.commit()
    client.cookies.clear()
    actor_headers = {
        "X-Actor-Claims": json.dumps(
            {"sub": str(actor_id), "roles": ["student"]}
        )
    }
    probes = (
        client.patch(
            "/api/v1/auth/student/profile",
            json=_academic_payload(),
            headers=actor_headers,
        ),
        client.post(
            "/api/v1/auth/student/guardian-consent/complete",
            json={},
            headers=actor_headers,
        ),
        client.post(
            "/api/v1/auth/student/verification/email/request",
            json={"institutional_email": "aditi@nls.ac.in"},
            headers=actor_headers,
        ),
        client.get(
            "/api/v1/auth/student/verification/status",
            headers=actor_headers,
        ),
    )
    for response in probes:
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "registration_not_found"
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action.in_(
                    (
                        "student.profile.academic_updated",
                        "student.verification.email_requested",
                        "student.verification.status_changed",
                    )
                )
            )
        ) == 0


@pytest.mark.parametrize(
    "case", ["forged", "expired", "revoked", "soft-deleted-registration"]
)
def test_rejected_session_credentials_do_not_touch_database(ctx, case):
    client, _, factory, sender = ctx
    _, token = _signup_session(client, sender, mobile="9876543210")
    with factory() as session:
        auth_session = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == keyed_hash(token)
            )
        )
        if case == "expired":
            auth_session.expires_at = datetime.now(timezone.utc) - timedelta(
                seconds=1
            )
        elif case == "revoked":
            auth_session.status = "revoked"
            auth_session.revoked_at = datetime.now(timezone.utc)
        elif case == "soft-deleted-registration":
            registration = session.scalar(select(StudentRegistration))
            registration.deleted_at = datetime.now(timezone.utc)
        session.commit()

    submitted = "forged-session-token" if case == "forged" else token
    _use_session_cookie(client, submitted)
    _remove_default_origin(client)
    with factory() as session:
        sessions_before = [
            (
                row.id,
                row.status,
                row.expires_at,
                row.last_seen_at,
                row.revoked_at,
            )
            for row in session.scalars(
                select(AuthSession).order_by(AuthSession.id)
            )
        ]
        audits_before = session.scalar(
            select(func.count()).select_from(AuditEvent)
        )

    denied_without_origin = client.patch(
        "/api/v1/auth/student/profile",
        json=_academic_payload(),
    )
    assert denied_without_origin.status_code == 401
    assert (
        denied_without_origin.json()["detail"]["code"]
        == "authentication_required"
    )
    denied = client.patch(
        "/api/v1/auth/student/profile",
        json=_academic_payload(),
        headers={"Origin": settings.cors_origins[0]},
    )
    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "authentication_required"
    with factory() as session:
        sessions_after = [
            (
                row.id,
                row.status,
                row.expires_at,
                row.last_seen_at,
                row.revoked_at,
            )
            for row in session.scalars(
                select(AuthSession).order_by(AuthSession.id)
            )
        ]
        assert sessions_after == sessions_before
        assert session.scalar(
            select(func.count()).select_from(AuditEvent)
        ) == audits_before


def test_all_cookie_mutations_require_origin_and_safe_read_does_not(ctx):
    client, _, factory, sender = ctx
    registration_id, token = _signup_session(
        client, sender, mobile="9000000000", dob="2012-01-01"
    )
    _use_session_cookie(client, token)
    _remove_default_origin(client)

    missing_origin_probes = (
        client.patch(
            "/api/v1/auth/student/profile", json=_academic_payload()
        ),
        client.post(
            "/api/v1/auth/student/guardian-consent/complete", json={}
        ),
        client.post(
            "/api/v1/auth/student/verification/email/request",
            json={"institutional_email": "aditi@nls.ac.in"},
        ),
        client.post(
            "/api/v1/auth/student/verification/status",
            json={"registration_id": registration_id, "status": "in_review"},
        ),
        client.post("/api/v1/auth/student/logout", json={}),
    )
    for response in missing_origin_probes:
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "csrf_origin_required"

    trusted = settings.cors_origins[0]
    for hostile in (
        f"{trusted}.evil.test",
        "http://user@localhost:1130",
        f"{trusted}/",
        f"{trusted}/path",
        f"{trusted}?query=1",
        "null",
    ):
        rejected = client.patch(
            "/api/v1/auth/student/profile",
            json=_academic_payload(),
            headers={"Origin": hostile},
        )
        assert rejected.status_code == 403
        assert rejected.json()["detail"]["code"] == "csrf_origin_untrusted"
    duplicate = client.patch(
        "/api/v1/auth/student/profile",
        json=_academic_payload(),
        headers=[("Origin", trusted), ("Origin", trusted)],
    )
    assert duplicate.status_code == 403
    assert duplicate.json()["detail"]["code"] == "csrf_origin_untrusted"

    with factory() as session:
        profile = session.scalar(
            select(StudentProfile).where(
                StudentProfile.registration_id == uuid.UUID(registration_id)
            )
        )
        guardian = session.scalar(
            select(GuardianConsent).where(
                GuardianConsent.registration_id == uuid.UUID(registration_id)
            )
        )
        assert profile is not None and profile.enrolment_hash is None
        assert guardian is not None
        assert (guardian.status, guardian.verified) == ("pending", False)
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "student.profile.academic_updated")
        ) == 0

    # A safe cookie-backed read does not require Origin.
    status_probe = client.get("/api/v1/auth/student/verification/status")
    assert status_probe.status_code == 200
    assert status_probe.json()["status"] == "pending"

    exact_profile = client.patch(
        "/api/v1/auth/student/profile",
        json=_academic_payload(),
        headers={"Origin": trusted},
    )
    assert exact_profile.status_code == 200
    exact_email = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={"institutional_email": "aditi@nls.ac.in"},
        headers={"Origin": trusted},
    )
    assert exact_email.status_code == 202
    self_guardian = client.post(
        "/api/v1/auth/student/guardian-consent/complete",
        json={},
        headers={"Origin": trusted},
    )
    assert self_guardian.status_code == 403
    assert self_guardian.json()["detail"]["code"] == "guardian_self_approval_forbidden"
    self_review = client.post(
        "/api/v1/auth/student/verification/status",
        json={"registration_id": registration_id, "status": "verified"},
        headers={"Origin": trusted},
    )
    assert self_review.status_code == 403
    assert self_review.json()["detail"]["code"] == "verification_reviewer_required"
    logged_out = client.post(
        "/api/v1/auth/student/logout",
        json={},
        headers={"Origin": trusted},
    )
    assert logged_out.status_code == 200


def test_reviewer_authority_and_identity_are_recorded_in_append_only_audit(ctx):
    client, _, factory, sender = ctx
    registration_id, student_token = _signup_session(
        client, sender, mobile="9876543210"
    )
    trusted = settings.cors_origins[0]
    _use_session_cookie(client, student_token)
    blocked = client.post(
        "/api/v1/auth/student/verification/status",
        json={"registration_id": registration_id, "status": "in_review"},
        headers={"Origin": trusted},
    )
    assert blocked.status_code == 403

    now = datetime.now(timezone.utc)
    with factory() as session:
        reviewer = User(role="legal_reviewer", status="active")
        session.add(reviewer)
        session.flush()
        reviewer_id = reviewer.id
        reviewer_token = "server-issued-reviewer-session"
        session.add(
            AuthSession(
                user_id=reviewer_id,
                token_hash=keyed_hash(reviewer_token),
                status="active",
                expires_at=now + timedelta(minutes=5),
                last_seen_at=now,
            )
        )
        session.commit()

    _use_session_cookie(client, reviewer_token)
    for target in ("in_review", "verified"):
        changed = client.post(
            "/api/v1/auth/student/verification/status",
            json={"registration_id": registration_id, "status": target},
            headers={"Origin": trusted},
        )
        assert changed.status_code == 200
        assert changed.json() == {"status": target}

    with factory() as session:
        events = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.action
                    == "student.verification.status_changed"
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        )
        assert len(events) == 2
        assert all(event.actor_user_id == reviewer_id for event in events)
        assert all(event.actor_role == "legal_reviewer" for event in events)
        assert [event.before_state for event in events] == [
            {"status": "pending"},
            {"status": "in_review"},
        ]
        assert [event.after_state for event in events] == [
            {"status": "in_review"},
            {"status": "verified"},
        ]


def test_reviewer_cannot_transition_deleted_quarantined_or_missing_target(ctx):
    client, _, factory, sender = ctx
    deleted_id, _ = _signup_session(client, sender, mobile="9876543210")
    quarantined_id, _ = _signup_session(client, sender, mobile="9123456780")
    now = datetime.now(timezone.utc)
    with factory() as session:
        deleted = session.get(StudentRegistration, uuid.UUID(deleted_id))
        deleted.deleted_at = now
        quarantined = session.get(
            StudentRegistration, uuid.UUID(quarantined_id)
        )
        quarantined.dob_hash = "f" * 64
        quarantined.dob_hash_state = "quarantined"
        reviewer = User(role="legal_reviewer", status="active")
        session.add(reviewer)
        session.flush()
        reviewer_id = reviewer.id
        reviewer_token = "deleted-target-reviewer-session"
        reviewer_session = AuthSession(
            user_id=reviewer_id,
            token_hash=keyed_hash(reviewer_token),
            status="active",
            expires_at=now + timedelta(minutes=5),
            last_seen_at=now,
        )
        session.add(reviewer_session)
        session.commit()

    _use_session_cookie(client, reviewer_token)
    with factory() as session:
        verification_before = {
            str(row.registration_id): row.status
            for row in session.scalars(select(StudentVerification))
        }
        audits_before = session.scalar(
            select(func.count()).select_from(AuditEvent)
        )
        reviewer_last_seen = session.scalar(
            select(AuthSession.last_seen_at).where(
                AuthSession.token_hash == keyed_hash(reviewer_token)
            )
        )

    for registration_id in (deleted_id, quarantined_id, str(uuid.uuid4())):
        denied = client.post(
            "/api/v1/auth/student/verification/status",
            json={"registration_id": registration_id, "status": "in_review"},
            headers={"Origin": settings.cors_origins[0]},
        )
        assert denied.status_code == 404
        assert denied.json()["detail"]["code"] == "verification_not_found"

    with factory() as session:
        assert {
            str(row.registration_id): row.status
            for row in session.scalars(select(StudentVerification))
        } == verification_before
        assert session.scalar(
            select(func.count()).select_from(AuditEvent)
        ) == audits_before
        assert session.scalar(
            select(AuthSession.last_seen_at).where(
                AuthSession.token_hash == keyed_hash(reviewer_token)
            )
        ) == reviewer_last_seen


def test_signup_or_recovery_code_cannot_authenticate_login(ctx):
    client, _, _, sender = ctx
    _, signup_code = _create_account(client, sender)
    login_id, login_code = _start_login(client, sender)
    assert login_code and login_code != signup_code
    rejected = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": signup_code},
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"]["code"] == "login_failed"
    accepted = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": login_code},
    )
    assert accepted.status_code == 200


def test_success_sets_hardened_cookie_stores_only_hash_and_authenticates(ctx):
    client, _, factory, sender = ctx
    registration_id, _ = _create_account(client, sender)
    login_id, code = _start_login(client, sender)
    response = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": code},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "authenticated"}
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header
    assert "Path=/" in cookie_header
    raw_token = client.cookies.get(settings.auth_session_cookie_name)
    assert raw_token and raw_token not in response.text and raw_token not in cookie_header.split(";", 1)[1]

    session_response = client.get("/api/v1/auth/student/session")
    assert session_response.status_code == 200
    actor = session_response.json()["actor"]
    with factory() as session:
        registration = session.get(StudentRegistration, uuid.UUID(registration_id))
        row = session.scalar(
            select(AuthSession).where(AuthSession.status == "active")
        )
        assert actor["sub"] == str(registration.user_id)
        assert row.token_hash != raw_token and len(row.token_hash) == 64
        assert row.status == "active"


def test_non_local_cookie_is_secure_and_authenticates_over_https(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    client, engine, _, sender = _context(base_url="https://testserver")
    try:
        _create_account(client, sender)
        login_id, code = _start_login(client, sender)
        response = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"login_id": login_id, "code": code},
        )
        assert response.status_code == 200
        assert "Secure" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]

        session_response = client.get("/api/v1/auth/student/session")
        assert session_response.status_code == 200
        assert session_response.json()["authenticated"] is True
        assert session_response.json()["actor"]["roles"] == ["student"]
    finally:
        client.close()
        engine.dispose()


@pytest.mark.parametrize("non_local_environment", ["staging", "production"])
def test_non_local_environment_never_trusts_dev_claims_header(
    ctx,
    monkeypatch,
    non_local_environment,
):
    client, *_ = ctx
    monkeypatch.setattr(settings, "app_env", non_local_environment)
    response = client.get(
        "/api/v1/student/profile",
        headers={
            "X-Actor-Claims": json.dumps(
                {"sub": str(uuid.uuid4()), "roles": ["student"]}
            )
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"


def test_valid_cookie_overrides_forged_dev_header_and_blocks_cross_user(ctx):
    client, _, factory, sender = ctx
    _, _ = _create_account(client, sender, "9876543210")
    login_id, code = _start_login(client, sender, "9876543210")
    assert client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": code},
    ).status_code == 200
    first_token = client.cookies.get(settings.auth_session_cookie_name)
    _create_account(client, sender, "9123456780")
    with factory() as session:
        other = session.scalar(
            select(StudentRegistration).where(
                StudentRegistration.mobile_hash != session.scalar(
                    select(StudentRegistration.mobile_hash).limit(1)
                )
            )
        )
    _use_session_cookie(client, first_token)
    response = client.get(
        "/api/v1/student/profile",
        headers={
            "X-Actor-Claims": json.dumps(
                {"sub": str(other.user_id), "roles": ["student"]}
            )
        },
    )
    assert response.status_code == 200
    assert response.json()["masked_mobile"] == "******3210"
    assert client.get("/api/v1/auth/student/session").json()["actor"]["sub"] != str(other.user_id)


@pytest.mark.parametrize("case", ["wrong", "expired", "unknown"])
def test_wrong_expired_and_unknown_attempts_share_uniform_failure(ctx, case):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    login_id, code = _start_login(client, sender)
    submitted = ("111111" if code == "000000" else "000000") if case == "wrong" else code
    if case == "expired":
        with factory() as session:
            row = session.scalar(select(LoginAttempt).where(LoginAttempt.opaque_id == login_id))
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
    elif case == "unknown":
        login_id = uuid.uuid4().hex
        submitted = "000000"
    response = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": submitted},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "login_failed"


def test_login_resend_cooldown_does_not_issue_a_second_code(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    first_id, first_code = _start_login(client, sender)
    second_id, second_code = _start_login(client, sender)
    assert first_id != second_id
    assert first_code is not None
    assert second_code is None
    with factory() as session:
        second = session.scalar(
            select(LoginAttempt).where(LoginAttempt.opaque_id == second_id)
        )
        assert second is not None and second.challenge_id is None


def test_three_wrong_codes_lock_the_login_challenge_and_correct_code_stays_rejected(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    login_id, code = _start_login(client, sender)
    wrong = "111111" if code == "000000" else "000000"
    for _ in range(3):
        response = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"login_id": login_id, "code": wrong},
        )
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "login_failed"
    still_locked = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": code},
    )
    assert still_locked.status_code == 401
    with factory() as session:
        attempt = session.scalar(
            select(LoginAttempt).where(LoginAttempt.opaque_id == login_id)
        )
        challenge = session.get(OtpChallenge, attempt.challenge_id)
        assert challenge.attempts == challenge.max_attempts == 3
        assert challenge.locked_until is not None
        assert session.scalar(
            select(func.count())
            .select_from(AuthSession)
            .where(AuthSession.status == "active")
        ) == 1


def test_replay_is_rejected_and_fresh_login_rotates_prior_session(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    login_id, code = _start_login(client, sender)
    assert client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": code},
    ).status_code == 200
    first_token = client.cookies.get(settings.auth_session_cookie_name)
    replay = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": code},
    )
    assert replay.status_code == 401

    with factory() as session:
        prior = session.scalar(
            select(LoginAttempt).where(LoginAttempt.opaque_id == login_id)
        )
        prior.created_at = datetime.now(timezone.utc) - timedelta(seconds=31)
        session.commit()
    second_id, second_code = _start_login(client, sender)
    assert second_code
    assert client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": second_id, "code": second_code},
    ).status_code == 200
    second_token = client.cookies.get(settings.auth_session_cookie_name)
    assert second_token != first_token
    _use_session_cookie(client, first_token)
    expired_probe = client.get("/api/v1/auth/student/session")
    assert expired_probe.status_code == 200
    assert expired_probe.json() == {"authenticated": False, "actor": None}


def test_expired_session_and_logout_revoke_authority(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    login_id, code = _start_login(client, sender)
    client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": code},
    )
    with factory() as session:
        row = session.scalar(select(AuthSession).where(AuthSession.status == "active"))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    logged_out_probe = client.get("/api/v1/auth/student/session")
    assert logged_out_probe.status_code == 200
    assert logged_out_probe.json() == {"authenticated": False, "actor": None}

    # Logout is idempotent even after expiry and always clears the cookie.
    logout = client.post(
        "/api/v1/auth/student/logout",
        json={},
        headers={"Origin": settings.cors_origins[0]},
    )
    assert logout.status_code == 200
    assert "Max-Age=0" in logout.headers["set-cookie"]


def test_commit_failure_leaves_no_session_and_retry_succeeds():
    client, engine, factory, sender = _context(CommitFailSession)
    try:
        _create_account(client, sender)
        with factory() as session:
            initial = session.scalar(
                select(AuthSession).where(AuthSession.status == "active")
            )
            initial_id = initial.id
        login_id, code = _start_login(client, sender)
        CommitFailSession.armed = True
        failed = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"login_id": login_id, "code": code},
        )
        assert failed.status_code == 500
        with factory() as session:
            active = session.scalar(
                select(AuthSession).where(AuthSession.status == "active")
            )
            assert active is not None and active.id == initial_id
            attempt = session.scalar(
                select(LoginAttempt).where(LoginAttempt.opaque_id == login_id)
            )
            assert attempt.status == "pending" and attempt.consumed_at is None
            challenge = session.get(OtpChallenge, attempt.challenge_id)
            assert challenge.consumed_at is None
        retry = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"login_id": login_id, "code": code},
        )
        assert retry.status_code == 200
    finally:
        client.close()
        engine.dispose()


def test_no_plaintext_mobile_otp_or_session_token_in_persistent_rows(ctx):
    client, _, factory, sender = ctx
    mobile = "9876543210"
    _, signup_code = _create_account(client, sender, mobile)
    login_id, login_code = _start_login(client, sender, mobile)
    client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"login_id": login_id, "code": login_code},
    )
    token = client.cookies.get(settings.auth_session_cookie_name)
    with factory() as session:
        values: list[str] = []
        for model in (LoginAttempt, AuthSession, OtpChallenge, AuditEvent):
            for row in session.scalars(select(model)):
                values.extend(str(value) for value in vars(row).values())
    persisted = " ".join(values)
    for secret in (mobile, signup_code, login_code, token):
        assert secret not in persisted


def test_concurrent_correct_verification_mints_exactly_one_session(tmp_path):
    database = tmp_path / "login-concurrency.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{database}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    dbtemplate.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    sender = CapturingSender()

    from app.core.crypto import encrypt, keyed_hash, otp_verifier
    from app.models.registration import Consent
    now = datetime.now(timezone.utc)
    with factory() as session:
        user = User(role="student", status="pending")
        session.add(user); session.flush()
        reg = StudentRegistration(
            user_id=user.id, first_name="Aditi", last_name="Nair",
            mobile_hash=keyed_hash("9876543210"), mobile_ct=encrypt("9876543210"),
            dob_hash=keyed_hash("2004-03-14"), dob_ct=encrypt("2004-03-14"),
            status="otp_verified", is_minor=False,
        )
        session.add(reg); session.flush()
        session.add(Consent(registration_id=reg.id, accepted=True, policy_version="v1"))
        salt = uuid.uuid4().hex; code = "654321"
        challenge = OtpChallenge(
            registration_id=reg.id, purpose="login",
            verifier_hash=otp_verifier(code, salt=salt), attempts=0, max_attempts=3,
            expires_at=now + timedelta(minutes=5), metadata_json={"salt": salt},
        )
        session.add(challenge); session.flush()
        attempt = LoginAttempt(
            opaque_id=uuid.uuid4().hex, lookup_hash=reg.mobile_hash,
            registration_id=reg.id, challenge_id=challenge.id, status="pending",
            expires_at=now + timedelta(minutes=10),
        )
        session.add(attempt); session.commit(); opaque_id = attempt.opaque_id

    def verify_once() -> bool:
        with factory() as session:
            try:
                from app.services import login_service
                login_service.verify(session, opaque_id, code, datetime.now(timezone.utc))
                return True
            except Exception:
                session.rollback()
                return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: verify_once(), range(8)))
    assert results.count(True) == 1
    with factory() as session:
        assert len(session.scalars(select(AuthSession)).all()) == 1
    engine.dispose()
