"""Security contract for student OTP login and cookie-backed sessions."""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import auth_student, student_settings
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import (
    AuthSession,
    LoginAttempt,
    OtpChallenge,
    StudentRegistration,
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


def _create_account(client: TestClient, sender: CapturingSender, mobile="9876543210"):
    response = client.post(
        "/api/v1/auth/student/register",
        json={
            "first_name": "Aditi",
            "last_name": "Nair",
            "mobile": mobile,
            "dob": "2004-03-14",
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
        row = session.scalar(select(AuthSession))
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
    _create_account(client, sender, "9123456780")
    with factory() as session:
        other = session.scalar(
            select(StudentRegistration).where(
                StudentRegistration.mobile_hash != session.scalar(
                    select(StudentRegistration.mobile_hash).limit(1)
                )
            )
        )
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
        assert session.scalar(select(AuthSession)) is None


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
    client.cookies.set(settings.auth_session_cookie_name, first_token)
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
    logout = client.post("/api/v1/auth/student/logout", json={})
    assert logout.status_code == 200
    assert "Max-Age=0" in logout.headers["set-cookie"]


def test_commit_failure_leaves_no_session_and_retry_succeeds():
    client, engine, factory, sender = _context(CommitFailSession)
    try:
        _create_account(client, sender)
        login_id, code = _start_login(client, sender)
        CommitFailSession.armed = True
        failed = client.post(
            "/api/v1/auth/student/login/otp/verify",
            json={"login_id": login_id, "code": code},
        )
        assert failed.status_code == 500
        with factory() as session:
            assert session.scalar(select(AuthSession)) is None
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
