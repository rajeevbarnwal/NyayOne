"""Security contract for student OTP login and cookie-backed sessions."""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import auth_student, student_settings
from app.core.auth import ActorContext, Role, get_actor_context
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
    OtpFlow,
    OtpOutbox,
    OtpPurposeAuthority,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)
from app.models.wave1 import DataSubjectRequest, DeletionJob
from app.services import login_service, otp_authority, otp_flow_service
from tests import dbtemplate


class CapturingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._receipts: dict[str, tuple[str, str, str]] = {}

    def send_idempotent(
        self, destination: str, code: str, *, idempotency_token: str
    ) -> str:
        existing = self._receipts.get(idempotency_token)
        if existing is not None:
            assert existing[:2] == (destination, code)
            return existing[2]
        receipt = f"test-{len(self._receipts) + 1}"
        self._receipts[idempotency_token] = (destination, code, receipt)
        self.sent.append((destination, code))
        return receipt


class CommitFailSession(Session):
    armed = False

    def commit(self):  # type: ignore[override]
        if CommitFailSession.armed:
            CommitFailSession.armed = False
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
            headers={"Origin": settings.cors_origins[0]},
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


def _registration_body(**overrides) -> dict[str, object]:
    body: dict[str, object] = {
        "first_name": "Aditi",
        "last_name": "Nair",
        "mobile": "9876543210",
        "dob": "2004-03-14",
        "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    }
    body.update(overrides)
    return body


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
        json=_registration_body(mobile=mobile, dob=dob),
    )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    signup_code = sender.sent[-1][1]
    factory = client.app.dependency_overrides[
        auth_student.get_outbox_session_factory
    ]()
    with factory() as session:
        registration_id = session.scalar(
            select(StudentRegistration.id).where(
                StudentRegistration.mobile_hash == keyed_hash(mobile)
            )
        )
    assert registration_id is not None
    verified = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"code": signup_code},
    )
    assert verified.status_code == 200
    _assert_initial_onboarding(verified, purpose="signup", dob=dob)
    assert "HttpOnly" in verified.headers["set-cookie"]
    if not keep_session:
        client.cookies.clear()
    return str(registration_id), signup_code


def _assert_initial_onboarding(
    response, *, purpose: str, dob: str = "2004-03-14"
) -> None:
    is_minor = dob == "2012-01-01"
    assert response.json() == {
        "status": "authenticated",
        "purpose": purpose,
        "destination_masked": None,
        "attempts_left": None,
        "expires_in_seconds": None,
        "resend_in_seconds": None,
        "locked_for_seconds": None,
        "resend_allowed": False,
        "onboarding": {
            "profile_version": 1,
            "completion_version": "v1",
            "completion_percent": 0,
            "completed_sections": [],
            "next_incomplete_section": "personal",
            "is_complete": False,
            "institutional_email_status": "not_provided",
            "guardian": (
                {"required": True, "status": "required_pending"}
                if is_minor
                else {"required": False, "status": "not_required"}
            ),
            "access_mode": "limited" if is_minor else "full",
            "disabled_capabilities": (
                ["community", "sharing"] if is_minor else []
            ),
            "profile_prompt": {
                "should_show": True,
                "dismissed_for_session": False,
            },
            "profile": {
                "personal": {
                    "first_name": "Aditi",
                    "middle_name": None,
                    "last_name": "Nair",
                    "date_of_birth": dob,
                    "preferred_language": None,
                    "city": None,
                    "pronouns": None,
                },
                "academic": {
                    "college": None,
                    "year_of_study": None,
                    "enrolment_number": None,
                    "institutional_email": None,
                    "bar_enrolment_number": None,
                },
                "interests": {"interests": [], "goals": []},
            },
        },
    }


def _start_login(client: TestClient, sender: CapturingSender, mobile="9876543210"):
    before = len(sender.sent)
    response = client.post(
        "/api/v1/auth/student/login/otp/start", json={"mobile": mobile}
    )
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    flow_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert flow_token
    code = sender.sent[-1][1] if len(sender.sent) > before else None
    return flow_token, code


def _use_session_cookie(client: TestClient, token: str) -> None:
    """Replace the browser cookie without leaving a second scoped value."""

    client.cookies.clear()
    client.cookies.set(settings.auth_session_cookie_name, token)


def _use_flow_cookie(client: TestClient, token: str) -> None:
    """Replace the browser OTP-flow cookie for private test interleavings."""

    client.cookies.clear()
    client.cookies.set(
        settings.otp_flow_cookie_name,
        token,
        domain="testserver.local",
        path="/api/v1",
    )


def _flow_for_token(session: Session, token: str) -> OtpFlow | None:
    return session.scalar(
        select(OtpFlow).where(
            OtpFlow.token_hash == otp_flow_service.flow_token_hash(token)
        )
    )


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
        "expected_profile_version": 2,
        "college": "National Law School of India University",
        "year_of_study": "3rd year",
        "enrolment_number": "KA/1234/2023",
        "institutional_email": "aditi@nls.ac.in",
    }


def _personal_payload() -> dict[str, object]:
    return {
        "expected_profile_version": 1,
        "first_name": "Aditi",
        "middle_name": None,
        "last_name": "Nair",
        "date_of_birth": "2004-03-14",
        "preferred_language": "en",
        "city": "Bengaluru",
        "pronouns": None,
    }


def test_verification_transition_policy_exactly_exposes_reviewer_lifecycle_edges():
    assert auth_student._VERIFICATION_TRANSITIONS == {
        "pending": {"in_review", "verified", "rejected"},
        "in_review": {"verified", "rejected"},
        "verified": {"expired", "revoked"},
        "rejected": {"in_review"},
        "expired": {"in_review"},
        "revoked": {"in_review"},
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
    # The retired UUID is no longer an accepted public selector at all.
    assert resend.status_code == reverify.status_code == 422
    assert resend.json()["detail"]["code"] == "validation_error"
    assert reverify.json()["detail"]["code"] == "validation_error"
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
    assert len(known) == len(unknown) >= 32
    assert known_code is not None and unknown_code is None
    with factory() as session:
        known_row = _flow_for_token(session, known)
        unknown_row = _flow_for_token(session, unknown)
        assert known_row is not None and unknown_row is not None
        assert known_row.registration_id is not None
        assert unknown_row.registration_id is None
        assert len(known_row.subject_hash) == len(unknown_row.subject_hash) == 64


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
            row
            for row in (
                _flow_for_token(session, known_login),
                _flow_for_token(session, unknown_login),
            )
            if row is not None
        )
        assert len(attempts) == 2
        assert all(attempt.registration_id is None for attempt in attempts)

    known_recovery = client.post(
        "/api/v1/auth/student/recovery/start", json={"mobile": "9876543210"}
    )
    unknown_recovery = client.post(
        "/api/v1/auth/student/recovery/start", json={"mobile": "9999993210"}
    )
    assert known_recovery.status_code == unknown_recovery.status_code == 202
    assert known_recovery.json() == unknown_recovery.json()
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
    assert recovery_start.status_code == 202
    recovery_id = client.cookies.get(settings.otp_flow_cookie_name)
    assert recovery_id
    recovery_code = sender.sent[-1][1]
    with factory() as session:
        registration = session.scalar(select(StudentRegistration))
        registration.dob_hash = "f" * 64
        registration.dob_hash_state = "quarantined"
        session.commit()

    _use_flow_cookie(client, login_id)
    login_result = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": login_code},
    )
    _use_flow_cookie(client, recovery_id)
    recovery_result = client.post(
        "/api/v1/auth/student/recovery/verify",
        json={"code": recovery_code},
    )
    _use_flow_cookie(client, uuid.uuid4().hex)
    unknown_login = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": login_code},
    )
    _use_flow_cookie(client, uuid.uuid4().hex)
    unknown_recovery = client.post(
        "/api/v1/auth/student/recovery/verify",
        json={"code": recovery_code},
    )
    assert login_result.status_code == unknown_login.status_code == 401
    assert recovery_result.status_code == unknown_recovery.status_code == 401
    assert login_result.json() == unknown_login.json()
    assert recovery_result.json() == unknown_recovery.json()

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
    assert quarantined_resend.status_code == missing_resend.status_code == 422
    assert quarantined_resend.json() == missing_resend.json()
    assert quarantined_resend.json()["detail"]["code"] == "validation_error"

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
        json={},
    )
    missing_email_request = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={},
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
        json={
            "registration_id": registration_id,
            "status": "in_review",
            "expected_profile_version": 1,
        },
        headers={
            "X-Actor-Claims": json.dumps(
                {"sub": str(uuid.uuid4()), "roles": ["legal_reviewer"]}
            )
        },
    )
    missing_transition = client.post(
        "/api/v1/auth/student/verification/status",
        json={
            "registration_id": missing_id,
            "status": "in_review",
            "expected_profile_version": 1,
        },
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
        json=_registration_body(),
    )
    assert response.status_code == 202
    code = sender.sent[-1][1]
    with factory() as session:
        registration = session.scalar(
            select(StudentRegistration).where(
                StudentRegistration.mobile_hash == keyed_hash("9876543210")
            )
        )
        assert registration is not None
        registration_id = str(registration.id)
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
        json={"code": code},
    )
    _use_flow_cookie(client, uuid.uuid4().hex)
    missing = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"code": code},
    )
    assert blocked.status_code == missing.status_code == 401
    assert blocked.json() == missing.json()
    assert blocked.json()["detail"]["code"] == "otp_failed"
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
        json=_registration_body(),
    )
    assert registered.status_code == 202
    code = sender.sent[-1][1]
    flow_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert flow_token
    with factory() as session:
        registration = session.scalar(
            select(StudentRegistration).where(
                StudentRegistration.mobile_hash == keyed_hash("9876543210")
            )
        )
        assert registration is not None
        registration_id = str(registration.id)
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

    deleted_resend = client.post(
        "/api/v1/auth/student/otp/resend",
        json={},
    )
    _use_flow_cookie(client, uuid.uuid4().hex)
    missing_resend = client.post(
        "/api/v1/auth/student/otp/resend",
        json={},
    )
    assert deleted_resend.status_code == missing_resend.status_code == 401
    assert deleted_resend.json() == missing_resend.json()
    _use_flow_cookie(client, flow_token)
    deleted_verify = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"code": code},
    )
    _use_flow_cookie(client, uuid.uuid4().hex)
    missing_verify = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"code": code},
    )
    assert deleted_verify.status_code == missing_verify.status_code == 401
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
    assert recovery_start.status_code == 202
    recovery_id = client.cookies.get(settings.otp_flow_cookie_name)
    assert recovery_id
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

    _use_flow_cookie(client, login_id)
    denied_login = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": login_code},
    )
    _use_flow_cookie(client, recovery_id)
    denied_recovery = client.post(
        "/api/v1/auth/student/recovery/verify",
        json={"code": recovery_code},
    )
    assert denied_login.status_code == denied_recovery.status_code == 401
    assert denied_login.json()["detail"]["code"] == "login_failed"
    assert denied_recovery.json()["detail"]["code"] == "recovery_failed"

    sender.sent.clear()
    known_login, known_code = _start_login(client, sender, "9876543210")
    unknown_login, unknown_code = _start_login(client, sender, "9999999999")
    known_recovery = client.post(
        "/api/v1/auth/student/recovery/start",
        json={"mobile": "9876543210"},
    )
    known_recovery_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert known_recovery_token
    unknown_recovery = client.post(
        "/api/v1/auth/student/recovery/start",
        json={"mobile": "9999993210"},
    )
    unknown_recovery_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert unknown_recovery_token
    assert known_code is unknown_code is None
    assert known_recovery.status_code == unknown_recovery.status_code == 202
    assert known_recovery.json() == unknown_recovery.json()
    assert sender.sent == []

    with factory() as session:
        login_attempts = [
            _flow_for_token(session, token)
            for token in (known_login, unknown_login)
        ]
        recovery_attempts = [
            _flow_for_token(session, token)
            for token in (known_recovery_token, unknown_recovery_token)
        ]
        assert all(row is not None for row in login_attempts + recovery_attempts)
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


# ---------------------------------------------------------------------------
# NYAY-2: server-derived onboarding ownership and exact cookie Origin.
# ---------------------------------------------------------------------------
def test_protected_onboarding_uses_actor_not_registration_uuid(ctx):
    client, _, factory, sender = ctx
    first_id, first_token = _signup_session(
        client, sender, mobile="9876543210"
    )
    _set_trusted_origin(client)
    assert client.patch(
        "/api/v1/student/profile/personal", json=_personal_payload()
    ).status_code == 200
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
        audit = next(
            event
            for event in session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "student.profile.section_updated"
                )
            )
            if event.after_state["section"] == "academic"
        )
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
            .where(AuditEvent.action == "student.profile.section_updated")
        ) == 2

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
            json={},
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
            json={},
        ),
        client.post(
            "/api/v1/auth/student/verification/status",
            json={
                "registration_id": registration_id,
                "status": "in_review",
                "expected_profile_version": 1,
            },
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
            .where(AuditEvent.action == "student.profile.section_updated")
        ) == 0

    # A safe cookie-backed read does not require Origin.
    status_probe = client.get("/api/v1/auth/student/verification/status")
    assert status_probe.status_code == 200
    assert status_probe.json()["status"] == "pending"

    exact_personal = client.patch(
        "/api/v1/student/profile/personal",
        json={**_personal_payload(), "date_of_birth": "2012-01-01"},
        headers={"Origin": trusted},
    )
    assert exact_personal.status_code == 200

    exact_profile = client.patch(
        "/api/v1/auth/student/profile",
        json=_academic_payload(),
        headers={"Origin": trusted},
    )
    assert exact_profile.status_code == 200
    exact_email = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={},
        headers={"Origin": trusted},
    )
    assert exact_email.status_code == 202
    assert exact_email.json()["institutional_email_status"] == "pending"
    self_guardian = client.post(
        "/api/v1/auth/student/guardian-consent/complete",
        json={},
        headers={"Origin": trusted},
    )
    assert self_guardian.status_code == 403
    assert self_guardian.json()["detail"]["code"] == "guardian_self_approval_forbidden"
    self_review = client.post(
        "/api/v1/auth/student/verification/status",
        json={
            "registration_id": registration_id,
            "status": "verified",
            "expected_profile_version": 3,
        },
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
        json={
            "registration_id": registration_id,
            "status": "in_review",
            "expected_profile_version": 1,
        },
        headers={"Origin": trusted},
    )
    assert blocked.status_code == 403

    personal = client.patch(
        "/api/v1/student/profile/personal",
        json=_personal_payload(),
        headers={"Origin": trusted},
    )
    assert personal.status_code == 200
    academic = client.patch(
        "/api/v1/auth/student/profile",
        json=_academic_payload(),
        headers={"Origin": trusted},
    )
    assert academic.status_code == 200
    reviewed_version = academic.json()["profile_version"]
    assert reviewed_version == 3

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
            json={
                "registration_id": registration_id,
                "status": target,
                "expected_profile_version": reviewed_version,
            },
            headers={"Origin": trusted},
        )
        assert changed.status_code == 200
        assert changed.json() == {
            "status": target,
            "profile_version": reviewed_version,
            "owner_projection_invalidated": True,
        }

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
            {"status": "in_review", "profile_version": 3},
            {"status": "verified", "profile_version": 3},
        ]
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id
                == uuid.UUID(registration_id)
            )
        )
        profile = session.scalar(
            select(StudentProfile).where(
                StudentProfile.registration_id == uuid.UUID(registration_id)
            )
        )
        assert verification.verified_email_hash == profile.institutional_email_hash


@pytest.mark.parametrize("mutated_section", ["personal", "academic"])
def test_stale_reviewer_cannot_verify_after_identity_or_email_mutation(
    ctx, mutated_section
):
    client, _, factory, sender = ctx
    registration_id, student_token = _signup_session(
        client, sender, mobile="9876543210"
    )
    trusted = settings.cors_origins[0]
    _use_session_cookie(client, student_token)

    if mutated_section == "personal":
        stale_version = 1
        mutation = client.patch(
            "/api/v1/student/profile/personal",
            json={**_personal_payload(), "date_of_birth": "2003-03-14"},
            headers={"Origin": trusted},
        )
    else:
        personal = client.patch(
            "/api/v1/student/profile/personal",
            json=_personal_payload(),
            headers={"Origin": trusted},
        )
        assert personal.status_code == 200
        stale_version = 2
        mutation = client.patch(
            "/api/v1/student/profile/academic",
            json=_academic_payload(),
            headers={"Origin": trusted},
        )
    assert mutation.status_code == 200
    assert mutation.json()["profile_version"] == stale_version + 1

    now = datetime.now(timezone.utc)
    with factory() as session:
        reviewer = User(role="legal_reviewer", status="active")
        session.add(reviewer)
        session.flush()
        reviewer_token = f"stale-reviewer-{mutated_section}"
        session.add(
            AuthSession(
                user_id=reviewer.id,
                token_hash=keyed_hash(reviewer_token),
                status="active",
                expires_at=now + timedelta(minutes=5),
                last_seen_at=now,
            )
        )
        session.commit()

    _use_session_cookie(client, reviewer_token)
    stale = client.post(
        "/api/v1/auth/student/verification/status",
        json={
            "registration_id": registration_id,
            "status": "verified",
            "expected_profile_version": stale_version,
        },
        headers={"Origin": trusted},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "profile_version_conflict",
        "current_profile_version": stale_version + 1,
        "message": "Request failed",
    }
    with factory() as session:
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id
                == uuid.UUID(registration_id)
            )
        )
        assert verification is not None and verification.status == "pending"
        assert session.scalar(
            select(func.count()).select_from(AuditEvent).where(
                AuditEvent.action == "student.verification.status_changed"
            )
        ) == 0


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
            json={
                "registration_id": registration_id,
                "status": "in_review",
                "expected_profile_version": 1,
            },
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


def test_revoked_reviewer_cookie_cannot_mutate_from_stale_dependency_actor(ctx):
    client, _, factory, _ = ctx
    now = datetime.now(timezone.utc)
    raw_token = "revoked-reviewer-session"
    with factory() as session:
        student = User(role="student", status="active")
        reviewer = User(role="legal_reviewer", status="active")
        session.add_all([student, reviewer])
        session.flush()
        registration = StudentRegistration(
            user_id=student.id,
            first_name="Aditi",
            middle_name=None,
            last_name="Nair",
            mobile_hash=keyed_hash("9876543210"),
            mobile_ct="ciphertext",
            dob_hash=keyed_hash("2004-03-14"),
            dob_ct="ciphertext",
            dob_hash_state="verified",
            key_version="v1",
            status="active",
            is_minor=False,
        )
        session.add(registration)
        session.flush()
        session.add_all(
            [
                StudentProfile(
                    registration_id=registration.id,
                    profile_version=1,
                ),
                StudentVerification(
                    registration_id=registration.id,
                    method="institutional_email",
                    status="pending",
                ),
                AuthSession(
                    user_id=reviewer.id,
                    token_hash=keyed_hash(raw_token),
                    status="revoked",
                    expires_at=now + timedelta(hours=1),
                    last_seen_at=now,
                    revoked_at=now,
                ),
            ]
        )
        session.commit()
        reviewer_id = reviewer.id
        registration_id = registration.id

    _use_session_cookie(client, raw_token)
    client.app.dependency_overrides[get_actor_context] = lambda: ActorContext(
        user_id=reviewer_id,
        roles=frozenset({Role.LEGAL_REVIEWER}),
    )
    try:
        denied = client.post(
            "/api/v1/auth/student/verification/status",
            json={
                "registration_id": str(registration_id),
                "status": "in_review",
                "expected_profile_version": 1,
            },
            headers={"Origin": settings.cors_origins[0]},
        )
    finally:
        client.app.dependency_overrides.pop(get_actor_context, None)

    assert denied.status_code == 401
    assert denied.json()["detail"]["code"] == "authentication_required"
    with factory() as session:
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id == registration_id
            )
        )
        assert verification.status == "pending"
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "student.verification.status_changed")
        ) == 0


def test_signup_or_recovery_code_cannot_authenticate_login(ctx):
    client, _, _, sender = ctx
    _, signup_code = _create_account(client, sender)
    login_id, login_code = _start_login(client, sender)
    assert login_code and login_code != signup_code
    rejected = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": signup_code},
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"]["code"] == "login_failed"
    accepted = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": login_code},
    )
    assert accepted.status_code == 200


def test_success_sets_hardened_cookie_stores_only_hash_and_authenticates(ctx):
    client, _, factory, sender = ctx
    registration_id, _ = _create_account(client, sender)
    login_id, code = _start_login(client, sender)
    response = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": code},
    )
    assert response.status_code == 200
    _assert_initial_onboarding(response, purpose="login")
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=strict" in cookie_header
    assert "Path=/api/v1" in cookie_header
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


@pytest.mark.parametrize("purpose", ["signup", "login"])
def test_onboarding_projection_failure_rolls_back_otp_and_session_atomically(
    purpose, monkeypatch
):
    client, engine, factory, sender = _context()
    try:
        if purpose == "signup":
            created = client.post(
                "/api/v1/auth/student/register",
                json=_registration_body(),
            )
            assert created.status_code == 202
            flow_token = client.cookies.get(settings.otp_flow_cookie_name)
            code = sender.sent[-1][1]
            endpoint = "/api/v1/auth/student/otp/verify"
        else:
            _create_account(client, sender)
            flow_token, code = _start_login(client, sender)
            endpoint = "/api/v1/auth/student/login/otp/verify"
        assert flow_token and code

        def projection_failure(*_args, **_kwargs):
            raise RuntimeError("forced onboarding projection failure")

        monkeypatch.setattr(
            "app.services.profile_service.projection_for_actor",
            projection_failure,
        )
        failed = client.post(endpoint, json={"code": code})
        assert failed.status_code == 500

        with factory() as session:
            flow = _flow_for_token(session, flow_token)
            assert flow is not None and flow.state in {"pending", "code_sent"}
            assert flow.consumed_at is None
            challenge = session.get(OtpChallenge, flow.challenge_id)
            assert challenge is not None and challenge.consumed_at is None
            if purpose == "signup":
                registration = session.get(
                    StudentRegistration, flow.registration_id
                )
                assert registration is not None
                assert registration.status == "otp_pending"
                assert session.scalar(
                    select(func.count()).select_from(AuthSession)
                ) == 0
            else:
                assert session.scalar(
                    select(func.count()).select_from(AuthSession).where(
                        AuthSession.status == "active"
                    )
                ) == 1
    finally:
        client.close()
        engine.dispose()


def test_non_local_cookie_is_secure_and_authenticates_over_https(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    client, engine, _, sender = _context(base_url="https://testserver")
    try:
        _create_account(client, sender)
        login_id, code = _start_login(client, sender)
        response = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"code": code},
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
        json={"code": code},
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
    assert response.json()["profile"]["personal"]["first_name"] == "Aditi"
    assert client.get("/api/v1/auth/student/session").json()["actor"]["sub"] != str(other.user_id)


@pytest.mark.parametrize("case", ["wrong", "expired", "unknown"])
def test_wrong_expired_and_unknown_attempts_share_uniform_failure(ctx, case):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    login_id, code = _start_login(client, sender)
    submitted = ("111111" if code == "000000" else "000000") if case == "wrong" else code
    if case == "expired":
        with factory() as session:
            row = _flow_for_token(session, login_id)
            assert row is not None
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            session.commit()
    elif case == "unknown":
        login_id = uuid.uuid4().hex
        _use_flow_cookie(client, login_id)
        submitted = "000000"
    response = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": submitted},
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
        second = _flow_for_token(session, second_id)
        assert second is not None


def test_three_wrong_codes_lock_the_login_challenge_and_correct_code_stays_rejected(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    login_id, code = _start_login(client, sender)
    wrong = "111111" if code == "000000" else "000000"
    for _ in range(3):
        response = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"code": wrong},
        )
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "login_failed"
    still_locked = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": code},
    )
    assert still_locked.status_code == 401
    with factory() as session:
        flow = _flow_for_token(session, login_id)
        assert flow is not None
        challenge = session.get(OtpChallenge, flow.challenge_id)
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
        json={"code": code},
    ).status_code == 200
    first_token = client.cookies.get(settings.auth_session_cookie_name)
    replay = client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": code},
    )
    assert replay.status_code == 401

    with factory() as session:
        authority = session.scalar(
            select(OtpPurposeAuthority).where(
                OtpPurposeAuthority.purpose == "login"
            )
        )
        assert authority is not None
        authority.cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    second_id, second_code = _start_login(client, sender)
    assert second_code
    assert client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": second_code},
    ).status_code == 200
    second_token = client.cookies.get(settings.auth_session_cookie_name)
    assert second_token != first_token
    _use_session_cookie(client, first_token)
    expired_probe = client.get("/api/v1/auth/student/session")
    assert expired_probe.status_code == 200
    assert expired_probe.json() == {"authenticated": False, "actor": None}


def test_effect_session_locks_user_before_exact_cookie_and_reloads_both() -> None:
    """Effect/logout ordering is User -> AuthSession after domain discovery."""

    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    raw_token = "effect-lock-order-cookie"
    locked_user = User(id=user_id, role="admin", status="active")
    locked_auth_session = AuthSession(
        id=session_id,
        user_id=user_id,
        token_hash=keyed_hash(raw_token),
        status="active",
        expires_at=now + timedelta(hours=1),
        last_seen_at=now,
    )
    lock_order: list[str] = []

    class RecordingSession:
        def execute(self, statement):
            lock_order.append("cookie_discovery")
            return SimpleNamespace(
                one_or_none=lambda: SimpleNamespace(
                    id=session_id,
                    user_id=user_id,
                )
            )

        def scalar(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            assert statement._for_update_arg is not None
            assert statement.get_execution_options()["populate_existing"] is True
            if entity is User:
                lock_order.append("user")
                return locked_user
            assert entity is AuthSession
            lock_order.append("auth_session")
            return locked_auth_session

    result = login_service.lock_presented_session_for_effect(
        RecordingSession(),  # type: ignore[arg-type]
        raw_token,
        expected_user_id=user_id,
        now=now,
        allowed_roles=frozenset({"admin"}),
    )

    assert result is locked_auth_session
    assert lock_order == ["cookie_discovery", "user", "auth_session"]


def test_expired_session_and_logout_revoke_authority(ctx):
    client, _, factory, sender = ctx
    _create_account(client, sender)
    login_id, code = _start_login(client, sender)
    client.post(
        "/api/v1/auth/student/login/otp/verify",
        json={"code": code},
    )
    with factory() as session:
        row = session.scalar(select(AuthSession).where(AuthSession.status == "active"))
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    logged_out_probe = client.get("/api/v1/auth/student/session")
    assert logged_out_probe.status_code == 200
    assert logged_out_probe.json() == {"authenticated": False, "actor": None}
    invalidation = logged_out_probe.headers.get_list("set-cookie")
    assert len(invalidation) == 1
    assert invalidation[0].startswith(f"{settings.auth_session_cookie_name}=")
    assert "Max-Age=0" in invalidation[0]
    assert "Path=/api/v1" in invalidation[0]
    assert "HttpOnly" in invalidation[0]
    assert "SameSite=strict" in invalidation[0]

    # Logout is idempotent even after expiry and always clears the cookie.
    client.cookies.set(
        settings.otp_flow_cookie_name,
        "stale-flow-cookie",
        domain="testserver.local",
        path="/api/v1",
    )
    logout = client.post(
        "/api/v1/auth/student/logout",
        json={},
        headers={"Origin": settings.cors_origins[0]},
    )
    assert logout.status_code == 200
    logout_cookies = logout.headers.get_list("set-cookie")
    assert {
        header.split("=", 1)[0] for header in logout_cookies
    } == {
        settings.auth_session_cookie_name,
        settings.otp_flow_cookie_name,
    }
    assert all(
        "Max-Age=0" in header
        and "Path=/api/v1" in header
        and "HttpOnly" in header
        and "SameSite=strict" in header
        for header in logout_cookies
    )


def test_privacy_delete_freezes_account_revokes_session_and_clears_both_cookies(
    ctx,
):
    client, _, factory, sender = ctx
    registration_id, auth_token = _signup_session(
        client, sender, mobile="9876543210"
    )
    recovery = client.post(
        "/api/v1/auth/student/recovery/start",
        json={"mobile": "9876543210"},
    )
    assert recovery.status_code == 202
    recovery_code = sender.sent[-1][1]
    verified = client.post(
        "/api/v1/auth/student/recovery/verify",
        json={"code": recovery_code},
    )
    assert verified.status_code == 200
    proof_token = client.cookies.get(settings.otp_flow_cookie_name)
    assert proof_token

    deleted = client.post(
        "/api/v1/student/privacy/delete",
        json={"confirmation": "DELETE"},
        headers={
            "Origin": settings.cors_origins[0],
            "Idempotency-Key": "nyay19-delete-1",
        },
    )
    assert deleted.status_code == 202
    cookie_headers = deleted.headers.get_list("set-cookie")
    for name in (
        settings.auth_session_cookie_name,
        settings.otp_flow_cookie_name,
    ):
        matching = [header for header in cookie_headers if header.startswith(f"{name}=")]
        assert len(matching) == 1
        assert "Max-Age=0" in matching[0]
        assert "Path=/api/v1" in matching[0]
        assert "HttpOnly" in matching[0]
        assert "SameSite=strict" in matching[0]

    with factory() as session:
        registration = session.get(
            StudentRegistration, uuid.UUID(registration_id)
        )
        user = session.get(User, registration.user_id)
        auth_session = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == keyed_hash(auth_token)
            )
        )
        dsr = session.scalar(
            select(DataSubjectRequest).where(
                DataSubjectRequest.idempotency_key == "nyay19-delete-1"
            )
        )
        job = session.scalar(
            select(DeletionJob).where(DeletionJob.request_id == dsr.id)
        )
        assert registration.status == "suspended"
        assert user.status == "suspended"
        assert auth_session.status == "revoked"
        assert auth_session.revoked_at is not None
        assert job.mode == settings.retention_mode
        snapshot = (
            registration.status,
            user.status,
            auth_session.status,
            auth_session.revoked_at,
            dsr.status,
            job.status,
            session.scalar(select(func.count()).select_from(AuditEvent)),
        )

    client.cookies.set(
        settings.auth_session_cookie_name,
        auth_token,
        domain="testserver.local",
        path="/api/v1",
    )
    client.cookies.set(
        settings.otp_flow_cookie_name,
        proof_token,
        domain="testserver.local",
        path="/api/v1",
    )
    replay = client.post(
        "/api/v1/student/privacy/delete",
        json={"confirmation": "DELETE"},
        headers={
            "Origin": settings.cors_origins[0],
            "Idempotency-Key": "nyay19-delete-1",
        },
    )
    assert replay.status_code == 401
    with factory() as session:
        registration = session.get(
            StudentRegistration, uuid.UUID(registration_id)
        )
        user = session.get(User, registration.user_id)
        auth_session = session.scalar(
            select(AuthSession).where(
                AuthSession.token_hash == keyed_hash(auth_token)
            )
        )
        dsr = session.scalar(
            select(DataSubjectRequest).where(
                DataSubjectRequest.idempotency_key == "nyay19-delete-1"
            )
        )
        job = session.scalar(
            select(DeletionJob).where(DeletionJob.request_id == dsr.id)
        )
        assert (
            registration.status,
            user.status,
            auth_session.status,
            auth_session.revoked_at,
            dsr.status,
            job.status,
            session.scalar(select(func.count()).select_from(AuditEvent)),
        ) == snapshot

    client.cookies.clear()
    delivered = len(sender.sent)
    assert client.post(
        "/api/v1/auth/student/login/otp/start",
        json={"mobile": "9876543210"},
    ).status_code == 202
    assert client.post(
        "/api/v1/auth/student/recovery/start",
        json={"mobile": "9876543210"},
    ).status_code == 202
    assert len(sender.sent) == delivered


def test_privacy_delete_commit_failure_rolls_back_proof_job_and_account_freeze():
    client, engine, factory, sender = _context(CommitFailSession)
    try:
        registration_id, auth_token = _signup_session(
            client, sender, mobile="9876543210"
        )
        assert client.post(
            "/api/v1/auth/student/recovery/start",
            json={"mobile": "9876543210"},
        ).status_code == 202
        recovery_code = sender.sent[-1][1]
        assert client.post(
            "/api/v1/auth/student/recovery/verify",
            json={"code": recovery_code},
        ).status_code == 200
        proof_token = client.cookies.get(settings.otp_flow_cookie_name)
        assert proof_token

        with factory() as session:
            registration = session.get(
                StudentRegistration, uuid.UUID(registration_id)
            )
            flow = _flow_for_token(session, proof_token)
            before = (
                registration.status,
                session.get(User, registration.user_id).status,
                session.scalar(
                    select(AuthSession.status).where(
                        AuthSession.token_hash == keyed_hash(auth_token)
                    )
                ),
                flow.state,
                flow.consumed_at,
                session.scalar(select(func.count()).select_from(DataSubjectRequest)),
                session.scalar(select(func.count()).select_from(DeletionJob)),
                session.scalar(select(func.count()).select_from(AuditEvent)),
            )

        CommitFailSession.armed = True
        failed = client.post(
            "/api/v1/student/privacy/delete",
            json={"confirmation": "DELETE"},
            headers={
                "Origin": settings.cors_origins[0],
                "Idempotency-Key": "nyay19-delete-rollback",
            },
        )
        assert failed.status_code == 500
        assert not failed.headers.get_list("set-cookie")

        with factory() as session:
            registration = session.get(
                StudentRegistration, uuid.UUID(registration_id)
            )
            flow = _flow_for_token(session, proof_token)
            assert (
                registration.status,
                session.get(User, registration.user_id).status,
                session.scalar(
                    select(AuthSession.status).where(
                        AuthSession.token_hash == keyed_hash(auth_token)
                    )
                ),
                flow.state,
                flow.consumed_at,
                session.scalar(select(func.count()).select_from(DataSubjectRequest)),
                session.scalar(select(func.count()).select_from(DeletionJob)),
                session.scalar(select(func.count()).select_from(AuditEvent)),
            ) == before

        retry = client.post(
            "/api/v1/student/privacy/delete",
            json={"confirmation": "DELETE"},
            headers={
                "Origin": settings.cors_origins[0],
                "Idempotency-Key": "nyay19-delete-rollback",
            },
        )
        assert retry.status_code == 202
    finally:
        client.close()
        engine.dispose()


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
            json={"code": code},
        )
        assert failed.status_code == 500
        with factory() as session:
            active = session.scalar(
                select(AuthSession).where(AuthSession.status == "active")
            )
            assert active is not None and active.id == initial_id
            flow = _flow_for_token(session, login_id)
            assert flow is not None and flow.state in {"pending", "code_sent"}
            assert flow.consumed_at is None
            challenge = session.get(OtpChallenge, flow.challenge_id)
            assert challenge.consumed_at is None
        retry = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"code": code},
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
        json={"code": login_code},
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
    from app.core.crypto import encrypt, keyed_hash, otp_verifier
    from app.models.registration import Consent
    now = datetime.now(timezone.utc)
    with factory() as session:
        user = User(role="student", status="pending")
        session.add(user)
        session.flush()
        reg = StudentRegistration(
            user_id=user.id, first_name="Aditi", last_name="Nair",
            mobile_hash=keyed_hash("9876543210"), mobile_ct=encrypt("9876543210"),
            dob_hash=keyed_hash("2004-03-14"), dob_ct=encrypt("2004-03-14"),
            status="otp_verified", is_minor=False,
        )
        session.add(reg)
        session.flush()
        session.add(Consent(registration_id=reg.id, accepted=True, policy_version="v1"))
        authority = otp_authority.lock_or_create_authority(
            session,
            subject_hash=otp_authority.authority_subject_from_mobile_hash(
                reg.mobile_hash
            ),
            purpose="login",
            registration_id=reg.id,
            now=now,
        )
        salt = uuid.uuid4().hex
        code = "654321"
        challenge = OtpChallenge(
            registration_id=reg.id, authority_id=authority.id, purpose="login",
            verifier_hash=otp_verifier(code, salt=salt), attempts=0, max_attempts=3,
            expires_at=now + timedelta(minutes=5), delivery_state="active",
            metadata_json={"salt": salt},
        )
        authority.active_expires_at = challenge.expires_at
        session.add(challenge)
        session.flush()
        attempt = LoginAttempt(
            opaque_id=uuid.uuid4().hex, lookup_hash=reg.mobile_hash,
            registration_id=reg.id, challenge_id=challenge.id, status="pending",
            expires_at=now + timedelta(minutes=10),
        )
        session.add(attempt)
        session.commit()
        opaque_id = attempt.opaque_id

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
