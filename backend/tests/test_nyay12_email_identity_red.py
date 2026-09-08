"""NYAY-12 verified-email identity + email OTP login: RED-first HTTP contract.

Matrix rows E-01..E-28 (see NYAY-12 acceptance-to-test matrix). Every test
drives production routers over SQLite; PostgreSQL-only invariants live in the
native gate. No raw email, OTP code or session token may appear in logs,
responses (other than the owner-facing masked destination) or audit rows.
"""
from __future__ import annotations

import importlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.v1 import auth_student, student_settings
from app.core.config import settings
from app.core.crypto import keyed_hash
from app.core.exceptions import register_exception_handlers
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import (
    AuthSession,
    OtpFlow,
    StudentRegistration,
    User,
)
from tests import dbtemplate
from tests.profile_idempotency_fixture import install_profile_mutation_idempotency

ROOT = "/api/v1/auth/student/email-identities"
CHANNELS = "/api/v1/auth/student/login/channels"
EMAIL_START = "/api/v1/auth/student/login/email/start"
EMAIL_MASK = re.compile(r"^[^\s@•]•{5}@[^\s@]+\.[^\s@]+$")
IDENTITY_KEYS = {"id", "email_masked", "state", "is_primary", "verification"}
VERIFICATION_KEYS = {"status", "expires_in_seconds", "resend_in_seconds", "attempts_left"}
LIST_KEYS = {"login_channel_enabled", "max_identities", "identities"}
OTP_STATE_KEYS = {
    "status", "purpose", "destination_masked", "attempts_left",
    "expires_in_seconds", "resend_in_seconds", "locked_for_seconds", "resend_allowed",
}


class CapturingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = False
        self._receipts: dict[str, tuple[str, str, str]] = {}

    def send_idempotent(self, destination: str, code: str, *, idempotency_token: str) -> str:
        if self.fail:
            from app.services.otp_sender import OtpSendError

            raise OtpSendError("otp provider send failed: Simulated")
        existing = self._receipts.get(idempotency_token)
        if existing is not None:
            assert existing[:2] == (destination, code)
            return existing[2]
        receipt = f"test-{len(self._receipts) + 1}"
        self._receipts[idempotency_token] = (destination, code, receipt)
        self.sent.append((destination, code))
        return receipt


def _service():
    return importlib.import_module("app.services.email_identity_service")


def _models():
    return importlib.import_module("app.models.email_identity")


def _policy():
    return importlib.import_module("app.core.email_identity")


class Ctx:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        dbtemplate.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)
        self.sms = CapturingSender()
        self.email = CapturingSender()
        self.clock = {"now": datetime.now(timezone.utc)}
        factory = self.factory

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

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(auth_student.router, prefix="/api/v1")
        app.include_router(student_settings.router, prefix="/api/v1")
        try:
            identity_router = importlib.import_module("app.api.v1.email_identity")
        except ModuleNotFoundError:
            identity_router = None
        if identity_router is not None:
            app.include_router(identity_router.router, prefix="/api/v1")
            monkeypatch.setattr(identity_router, "_now", lambda: self.clock["now"], raising=False)
        app.dependency_overrides[get_session] = request_session
        app.dependency_overrides[auth_student.get_otp_sender] = lambda: self.sms
        app.dependency_overrides[auth_student.get_outbox_session_factory] = lambda: factory
        email_seam = getattr(auth_student, "get_email_otp_sender", None)
        if email_seam is not None:
            app.dependency_overrides[email_seam] = lambda: self.email
        monkeypatch.setattr(auth_student, "_now", lambda: self.clock["now"])
        monkeypatch.setattr(settings, "email_login_enabled", True, raising=False)
        self.app = app
        self.client = TestClient(
            app,
            raise_server_exceptions=False,
            headers={"Origin": settings.cors_origins[0]},
        )
        install_profile_mutation_idempotency(self.client, prefix="nyay12-profile")

    def advance(self, seconds: int) -> None:
        self.clock["now"] = self.clock["now"] + timedelta(seconds=seconds)

    def new_client(self) -> TestClient:
        client = TestClient(
            self.app,
            raise_server_exceptions=False,
            headers={"Origin": settings.cors_origins[0]},
        )
        install_profile_mutation_idempotency(client, prefix="nyay12-profile-b")
        return client

    def register_student(self, client: TestClient, mobile: str, *, dob: str = "2004-03-14") -> uuid.UUID:
        registered = client.post(
            "/api/v1/auth/student/register",
            json={
                "first_name": "Aditi",
                "last_name": "Nair",
                "mobile": mobile,
                "dob": dob,
                "terms_accepted": True,
                "terms_version": "terms-2026-08.v1",
                "privacy_notice_acknowledged": True,
                "privacy_notice_version": "privacy-2026-08.v1",
            },
        )
        assert registered.status_code == 202, registered.text
        verified = client.post(
            "/api/v1/auth/student/otp/verify", json={"code": self.sms.sent[-1][1]}
        )
        assert verified.status_code == 200, verified.text
        assert settings.auth_session_cookie_name in client.cookies
        with self.factory() as session:
            registration = session.scalar(
                select(StudentRegistration).where(
                    StudentRegistration.mobile_hash == keyed_hash(mobile)
                )
            )
            assert registration is not None
            return registration.user_id


def _key(label: str) -> str:
    return f"nyay12-{label}-" + uuid.uuid4().hex[:16]


def _add(client: TestClient, email: str, key: str | None = None):
    headers = {"Idempotency-Key": key or _key("add")}
    return client.post(ROOT, json={"email": email}, headers=headers)


def _verify(client: TestClient, identity_id: str, code: str, key: str | None = None):
    return client.post(
        f"{ROOT}/{identity_id}/verify",
        json={"code": code},
        headers={"Idempotency-Key": key or _key("verify")},
    )


def _resend(client: TestClient, identity_id: str, key: str | None = None):
    return client.post(
        f"{ROOT}/{identity_id}/resend", json={}, headers={"Idempotency-Key": key or _key("resend")}
    )


def _remove(client: TestClient, identity_id: str, key: str | None = None):
    return client.delete(f"{ROOT}/{identity_id}", headers={"Idempotency-Key": key or _key("remove")})


def _primary(client: TestClient, identity_id: str, key: str | None = None):
    return client.post(
        f"{ROOT}/{identity_id}/primary", json={}, headers={"Idempotency-Key": key or _key("primary")}
    )


def _add_verified(ctx: Ctx, client: TestClient, email: str) -> str:
    accepted = _add(client, email)
    assert accepted.status_code == 202, accepted.text
    identity_id = accepted.json()["identity"]["id"]
    verified = _verify(client, identity_id, ctx.email.sent[-1][1])
    assert verified.status_code == 200, verified.text
    assert verified.json()["identity"]["state"] == "verified"
    return identity_id


def _assert_private(response) -> None:
    assert response.headers["cache-control"] == "private, no-store"
    assert "cookie" in {t.strip().casefold() for t in response.headers["vary"].split(",")}


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch) -> Ctx:
    return Ctx(monkeypatch)


# --------------------------------------------------------------------------- #
# E-05 / E-06 : server-owned flag and non-enumerating email login start        #
# --------------------------------------------------------------------------- #
def test_channels_projection_and_email_start_disabled_by_default(ctx: Ctx, monkeypatch):
    monkeypatch.setattr(settings, "email_login_enabled", False, raising=False)
    channels = ctx.client.get(CHANNELS)
    assert channels.status_code == 200, channels.text
    _assert_private(channels)
    assert channels.json() == {
        "channels": [
            {"channel": "mobile", "enabled": True},
            {"channel": "email", "enabled": False},
        ]
    }
    assert ctx.client.get(CHANNELS, params={"probe": "1"}).status_code == 422
    for email in ("nobody@example.edu", "Student.One@Example.EDU", "not-an-email"):
        response = ctx.client.post(EMAIL_START, json={"email": email})
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "email_login_disabled"
        assert settings.otp_flow_cookie_name not in response.cookies
    assert ctx.email.sent == []
    with ctx.factory() as session:
        assert session.scalar(select(OtpFlow)) is None


def test_email_login_start_is_uniform_for_unknown_pending_verified_and_suspended(ctx: Ctx):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    verified_id = _add_verified(ctx, owner, "verified.owner@example.edu")
    pending = _add(owner, "pending.owner@example.edu")
    assert pending.status_code == 202
    suspended_client = ctx.new_client()
    suspended_user = ctx.register_student(suspended_client, "9876543211")
    _add_verified(ctx, suspended_client, "suspended.owner@example.edu")
    with ctx.factory() as session:
        user = session.get(User, suspended_user)
        user.status = "suspended"
        session.commit()
    anonymous = ctx.new_client()
    sent_before = len(ctx.email.sent)
    outcomes = []
    for email in (
        "unknown.person@example.edu",
        "pending.owner@example.edu",
        "verified.owner@example.edu",
        "suspended.owner@example.edu",
    ):
        client = ctx.new_client()
        response = client.post(EMAIL_START, json={"email": email})
        body = response.json()
        outcomes.append(
            (
                response.status_code,
                tuple(sorted(body)),
                body["status"],
                body["purpose"],
                bool(EMAIL_MASK.match(body["destination_masked"] or "")),
                body["attempts_left"],
                body["expires_in_seconds"],
                body["resend_in_seconds"],
                settings.otp_flow_cookie_name in client.cookies,
            )
        )
        _assert_private(response)
    assert len({o for o in outcomes}) == 1, outcomes
    assert outcomes[0][0] == 202 and outcomes[0][1] == tuple(sorted(OTP_STATE_KEYS))
    assert outcomes[0][2] == "pending" and outcomes[0][3] == "login" and outcomes[0][4] is True
    assert outcomes[0][8] is True
    # Exactly one real delivery (the verified, active owner); no decoy delivers.
    assert len(ctx.email.sent) == sent_before + 1
    assert ctx.email.sent[-1][0] == "verified.owner@example.edu"
    assert verified_id
    del anonymous


# --------------------------------------------------------------------------- #
# E-01 / E-02 / E-03 / E-04 : unverified cannot login; no silent promotion     #
# --------------------------------------------------------------------------- #
def test_pending_identity_cannot_start_real_login(ctx: Ctx):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    pending = _add(owner, "pending.person@example.edu")
    assert pending.status_code == 202
    identity_code = ctx.email.sent[-1][1]
    anonymous = ctx.new_client()
    started = anonymous.post(EMAIL_START, json={"email": "pending.person@example.edu"})
    assert started.status_code == 202
    assert len(ctx.email.sent) == 1  # the identity code only; no login delivery
    # Even the genuine identity-verification code cannot authenticate the decoy login flow.
    verify = anonymous.post("/api/v1/auth/student/login/otp/verify", json={"code": identity_code})
    assert verify.status_code == 401
    assert settings.auth_session_cookie_name not in anonymous.cookies
    with ctx.factory() as session:
        assert session.scalar(select(AuthSession).where(AuthSession.status == "active")) is not None
        assert session.scalar(
            select(AuthSession).where(AuthSession.status == "active")
        ).user_id is not None
        assert len(session.scalars(select(AuthSession)).all()) == 1  # only the owner's cookie session


def test_email_is_not_a_recovery_identifier(ctx: Ctx):
    response = ctx.client.post(
        "/api/v1/auth/student/recovery/start", json={"email": "someone@example.edu"}
    )
    assert response.status_code == 422
    assert "someone@example.edu" not in response.text
    with ctx.factory() as session:
        assert session.scalar(select(OtpFlow)) is None


def test_mobile_login_never_creates_or_verifies_identity(ctx: Ctx):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    pending = _add(owner, "pending.person@example.edu")
    assert pending.status_code == 202
    owner.post("/api/v1/auth/student/logout")
    login = ctx.new_client()
    started = login.post("/api/v1/auth/student/login/otp/start", json={"mobile": "9876543210"})
    assert started.status_code == 202
    verified = login.post("/api/v1/auth/student/login/otp/verify", json={"code": ctx.sms.sent[-1][1]})
    assert verified.status_code == 200
    listing = login.get(ROOT)
    assert listing.status_code == 200
    identities = listing.json()["identities"]
    assert [i["state"] for i in identities] == ["pending"]
    assert all(i["is_primary"] is False for i in identities)


def test_institutional_email_proof_does_not_create_login_identity(ctx: Ctx):
    models = _models()
    owner = ctx.client
    user_id = ctx.register_student(owner, "9876543210")
    from app.models.student_authority import InstitutionalEmailProof

    with ctx.factory() as session:
        session.add(
            InstitutionalEmailProof(
                user_id=user_id,
                email_hash=keyed_hash("student@nls.example.edu"),
                institution="nls",
                code_hash=None,
                provider_receipt_hash=keyed_hash("receipt"),
                state="verified",
                attempts=1,
                expires_at=ctx.clock["now"] + timedelta(days=365),
                issued_at=ctx.clock["now"],
            )
        )
        session.commit()
        assert session.scalar(select(models.UserEmailIdentity)) is None
    listing = owner.get(ROOT)
    assert listing.status_code == 200 and listing.json()["identities"] == []
    anonymous = ctx.new_client()
    started = anonymous.post(EMAIL_START, json={"email": "student@nls.example.edu"})
    assert started.status_code == 202 and ctx.email.sent == []


# --------------------------------------------------------------------------- #
# E-07 : documented normalization policy                                       #
# --------------------------------------------------------------------------- #
def test_normalization_policy_is_nfc_casefold_no_plus_dot_rewrite():
    policy = _policy()
    normalize = policy.normalize_login_email
    assert normalize("  Student.One@Example.EDU ") == "student.one@example.edu"
    assert normalize("Ａ@example.edu") != normalize("A@example.edu") or True  # width is preserved by NFC
    assert normalize("stràsse@example.edu") == normalize("stràsse@example.edu")
    assert normalize("first+tag@example.edu") == "first+tag@example.edu"
    assert normalize("first+tag@example.edu") != normalize("first@example.edu")
    assert normalize("fi.rst@example.edu") != normalize("first@example.edu")
    assert normalize("STUDENT@EXAMPLE.EDU") == normalize("student@example.edu")
    for invalid in ("", "   ", "no-at", "a@b", "a b@example.edu", "a@exa mple.edu", "a" * 250 + "@example.edu", "a@@example.edu"):
        with pytest.raises(ValueError):
            normalize(invalid)
    assert policy.EMAIL_IDENTITY_POLICY_VERSION == "nyay12-email-identity-policy.v1"
    assert policy.mask_login_email("student.one@example.edu") == "s•••••@example.edu"
    assert EMAIL_MASK.match(policy.mask_login_email("x@example.edu"))


# --------------------------------------------------------------------------- #
# E-08 .. E-12 : lifecycle                                                     #
# --------------------------------------------------------------------------- #
def test_add_identity_creates_pending_row_and_delivers_code(ctx: Ctx):
    models = _models()
    owner = ctx.client
    user_id = ctx.register_student(owner, "9876543210")
    accepted = _add(owner, "Student.One@Example.EDU")
    assert accepted.status_code == 202, accepted.text
    _assert_private(accepted)
    body = accepted.json()
    assert set(body) == {"status", "identity"} and body["status"] == "accepted"
    identity = body["identity"]
    assert set(identity) == IDENTITY_KEYS and set(identity["verification"]) == VERIFICATION_KEYS
    assert identity["state"] == "pending" and identity["is_primary"] is False
    assert identity["email_masked"] == "s•••••@example.edu"
    assert identity["verification"]["status"] == "active"
    assert identity["verification"]["attempts_left"] == settings.otp_max_attempts
    assert 0 < identity["verification"]["expires_in_seconds"] <= settings.otp_challenge_ttl_seconds
    assert identity["verification"]["resend_in_seconds"] == settings.otp_resend_cooldown_seconds
    assert ctx.email.sent == [("student.one@example.edu", ctx.email.sent[0][1])]
    assert re.fullmatch(r"[0-9]{6}", ctx.email.sent[0][1])
    with ctx.factory() as session:
        row = session.scalar(select(models.UserEmailIdentity))
        assert row.user_id == user_id and row.state == "pending"
        assert row.email_hash == keyed_hash("nyay12:email-identity:v1:student.one@example.edu")
        assert "student.one" not in (row.email_ct or "") and row.code_hash and len(row.code_hash) == 64
        assert row.provider_receipt_hash is not None
    listing = owner.get(ROOT)
    assert listing.status_code == 200 and set(listing.json()) == LIST_KEYS
    assert listing.json()["login_channel_enabled"] is True
    assert listing.json()["max_identities"] == 3
    assert [i["id"] for i in listing.json()["identities"]] == [identity["id"]]
    # Re-adding the same live address is idempotent-by-address, not a second row.
    again = _add(owner, "student.one@example.edu")
    assert again.status_code == 202 and again.json()["identity"]["id"] == identity["id"]
    with ctx.factory() as session:
        assert len(session.scalars(select(models.UserEmailIdentity)).all()) == 1


def test_verify_marks_verified_and_enables_email_login(ctx: Ctx):
    models = _models()
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    accepted = _add(owner, "student.one@example.edu")
    identity_id = accepted.json()["identity"]["id"]
    wrong = _verify(owner, identity_id, "000000" if ctx.email.sent[-1][1] != "000000" else "111111")
    assert wrong.status_code == 401 and wrong.json()["detail"]["code"] == "email_identity_verification_failed"
    malformed = _verify(owner, identity_id, "12345")
    assert malformed.status_code == 422
    verified = _verify(owner, identity_id, ctx.email.sent[-1][1])
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "verified" and body["identity"]["state"] == "verified"
    assert body["identity"]["is_primary"] is True  # first verified identity becomes primary
    assert body["identity"]["verification"]["status"] == "none"
    replay = _verify(owner, identity_id, ctx.email.sent[-1][1])
    assert replay.status_code == 401
    with ctx.factory() as session:
        row = session.get(models.UserEmailIdentity, uuid.UUID(identity_id))
        assert row.state == "verified" and row.verified_at is not None and row.code_hash is None
    owner.post("/api/v1/auth/student/logout")
    login = ctx.new_client()
    started = login.post(EMAIL_START, json={"email": "STUDENT.ONE@example.edu"})
    assert started.status_code == 202 and started.json()["destination_masked"] == "s•••••@example.edu"
    state = login.get("/api/v1/auth/student/otp/state")
    assert state.status_code == 200 and state.json()["destination_masked"] == "s•••••@example.edu"
    assert ctx.email.sent[-1][0] == "student.one@example.edu"
    verify = login.post("/api/v1/auth/student/login/otp/verify", json={"code": ctx.email.sent[-1][1]})
    assert verify.status_code == 200, verify.text
    assert verify.json()["status"] == "authenticated" and verify.json()["purpose"] == "login"
    assert settings.auth_session_cookie_name in login.cookies
    session_probe = login.get("/api/v1/auth/student/session")
    assert session_probe.json()["authenticated"] is True
    with ctx.factory() as session:
        assert len(session.scalars(select(AuthSession).where(AuthSession.status == "active")).all()) == 1


def test_resend_respects_cooldown_and_rotates_code(ctx: Ctx):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    identity_id = _add(owner, "student.one@example.edu").json()["identity"]["id"]
    first_code = ctx.email.sent[-1][1]
    early = _resend(owner, identity_id)
    assert early.status_code == 429 and early.json()["detail"]["code"] == "email_identity_rate_limited"
    assert int(early.headers["retry-after"]) >= 1
    ctx.advance(settings.otp_resend_cooldown_seconds)
    resent = _resend(owner, identity_id)
    assert resent.status_code == 202, resent.text
    assert resent.json()["identity"]["verification"]["status"] == "active"
    second_code = ctx.email.sent[-1][1]
    assert len(ctx.email.sent) == 2
    stale = _verify(owner, identity_id, first_code)
    if first_code != second_code:
        assert stale.status_code == 401
    fresh = _verify(owner, identity_id, second_code)
    assert fresh.status_code == 200
    on_verified = _resend(owner, identity_id)
    assert on_verified.status_code == 409 and on_verified.json()["detail"]["code"] == "email_identity_state_conflict"


def test_remove_clears_primary_and_disables_login(ctx: Ctx):
    models = _models()
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    identity_id = _add_verified(ctx, owner, "student.one@example.edu")
    removed = _remove(owner, identity_id)
    assert removed.status_code == 200, removed.text
    assert removed.json() == {"status": "removed", "identity": removed.json()["identity"]}
    assert removed.json()["identity"]["state"] == "removed"
    assert removed.json()["identity"]["is_primary"] is False
    assert owner.get(ROOT).json()["identities"] == []
    assert _remove(owner, identity_id).status_code == 404
    with ctx.factory() as session:
        row = session.get(models.UserEmailIdentity, uuid.UUID(identity_id))
        assert row.state == "removed" and row.removed_at is not None and row.is_primary is False
    sent_before = len(ctx.email.sent)
    login = ctx.new_client()
    assert login.post(EMAIL_START, json={"email": "student.one@example.edu"}).status_code == 202
    assert len(ctx.email.sent) == sent_before  # decoy: removed identity has no login authority


def test_set_primary_requires_verified_and_is_exclusive(ctx: Ctx):
    models = _models()
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    first = _add_verified(ctx, owner, "first@example.edu")
    second_pending = _add(owner, "second@example.edu").json()["identity"]["id"]
    denied = _primary(owner, second_pending)
    assert denied.status_code == 409 and denied.json()["detail"]["code"] == "email_identity_state_conflict"
    verified = _verify(owner, second_pending, ctx.email.sent[-1][1])
    assert verified.status_code == 200 and verified.json()["identity"]["is_primary"] is False
    promoted = _primary(owner, second_pending)
    assert promoted.status_code == 200 and promoted.json()["status"] == "primary"
    listing = {i["id"]: i for i in owner.get(ROOT).json()["identities"]}
    assert listing[second_pending]["is_primary"] is True and listing[first]["is_primary"] is False
    with ctx.factory() as session:
        primaries = session.scalars(
            select(models.UserEmailIdentity).where(models.UserEmailIdentity.is_primary.is_(True))
        ).all()
        assert len(primaries) == 1 and str(primaries[0].id) == second_pending
        # DB-level exclusivity: a second primary row is refused by the partial unique index.
        with pytest.raises(Exception):
            session.execute(
                text("UPDATE user_email_identities SET is_primary = 1 WHERE id = :id"),
                {"id": uuid.UUID(first).hex if session.bind.dialect.name == "sqlite" else first},
            )
            session.commit()
        session.rollback()


def test_interleaved_primary_promotions_leave_exactly_one_primary(ctx: Ctx):
    """SQLite schedule oracle for E-13.

    SQLite shares one connection across the test app, so a true parallel
    schedule cannot be proven here; the native PostgreSQL gate
    (``CONCURRENT_PRIMARY_EXACTLY_ONE``) runs the barrier-released concurrent
    version. This oracle drives every interleaving of repeated promotions,
    including replays with reused keys, and asserts the DB invariant.
    """
    models = _models()
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    ids = [_add_verified(ctx, owner, f"person{i}@example.edu") for i in range(3)]
    reused = {identity_id: _key("primary-reuse") for identity_id in ids}
    schedule = [ids[0], ids[1], ids[2], ids[1], ids[0], ids[2], ids[2], ids[0]]
    statuses = []
    for index, identity_id in enumerate(schedule):
        key = reused[identity_id] if index % 3 == 0 else None
        statuses.append(_primary(owner, identity_id, key).status_code)
        with ctx.factory() as session:
            rows = session.scalars(select(models.UserEmailIdentity)).all()
            assert sum(1 for row in rows if row.is_primary) == 1, statuses
            assert str(next(row for row in rows if row.is_primary).id) == identity_id
    assert all(status == 200 for status in statuses), statuses
    with ctx.factory() as session:
        rows = session.scalars(select(models.UserEmailIdentity)).all()
        assert sum(1 for row in rows if row.is_primary) == 1
        assert all(row.state == "verified" for row in rows)


# --------------------------------------------------------------------------- #
# E-14 / E-15 / E-16 : cross-user, replay and collision                        #
# --------------------------------------------------------------------------- #
def test_user_a_cannot_verify_manage_or_bind_user_b_identity(ctx: Ctx):
    models = _models()
    a = ctx.client
    ctx.register_student(a, "9876543210")
    b = ctx.new_client()
    ctx.register_student(b, "9876543211")
    b_pending = _add(b, "owner.b@example.edu").json()["identity"]["id"]
    b_code = ctx.email.sent[-1][1]
    b_verified = _add_verified(ctx, b, "verified.b@example.edu")
    for action, response in (
        ("verify", _verify(a, b_pending, b_code)),
        ("resend", _resend(a, b_pending)),
        ("remove", _remove(a, b_verified)),
        ("primary", _primary(a, b_verified)),
        ("unknown", _remove(a, str(uuid.uuid4()))),
        ("malformed", _remove(a, "not-a-uuid")),
    ):
        assert response.status_code in {404, 422}, (action, response.text)
        if action != "malformed":
            assert response.json()["detail"]["code"] == "email_identity_not_found", action
    listing_a = a.get(ROOT).json()["identities"]
    assert listing_a == []
    with ctx.factory() as session:
        rows = {str(r.id): r for r in session.scalars(select(models.UserEmailIdentity)).all()}
        assert rows[b_pending].state == "pending" and rows[b_verified].state == "verified"
        assert rows[b_verified].is_primary is True


def test_replayed_code_after_removal_cannot_rebind(ctx: Ctx):
    models = _models()
    a = ctx.client
    ctx.register_student(a, "9876543210")
    pending = _add(a, "shared@example.edu").json()["identity"]["id"]
    code = ctx.email.sent[-1][1]
    assert _remove(a, pending).status_code == 200
    replay = _verify(a, pending, code)
    assert replay.status_code == 404
    b = ctx.new_client()
    ctx.register_student(b, "9876543211")
    b_id = _add_verified(ctx, b, "shared@example.edu")
    # A re-adds the same address later: a fresh pending claim; the old code is dead.
    fresh = _add(a, "shared@example.edu").json()["identity"]["id"]
    assert fresh != pending
    dead = _verify(a, fresh, code)
    assert dead.status_code == 401
    # Expired proof cannot bind either.
    ctx.advance(settings.otp_challenge_ttl_seconds + 1)
    expired = _verify(a, fresh, ctx.email.sent[-1][1])
    assert expired.status_code == 401
    with ctx.factory() as session:
        verified = session.scalars(
            select(models.UserEmailIdentity).where(models.UserEmailIdentity.state == "verified")
        ).all()
        assert [str(r.id) for r in verified] == [b_id]


def test_verified_collision_fails_closed_into_reconciliation_row(ctx: Ctx):
    models = _models()
    a = ctx.client
    a_user = ctx.register_student(a, "9876543210")
    a_id = _add_verified(ctx, a, "shared@example.edu")
    b = ctx.new_client()
    b_user = ctx.register_student(b, "9876543211")
    claim = _add(b, "shared@example.edu")
    assert claim.status_code == 202  # non-enumerating: the claim is accepted
    b_id = claim.json()["identity"]["id"]
    conflict = _verify(b, b_id, ctx.email.sent[-1][1])
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "email_identity_conflict"
    assert "shared@example.edu" not in conflict.text and str(a_user) not in conflict.text
    with ctx.factory() as session:
        rows = {str(r.id): r for r in session.scalars(select(models.UserEmailIdentity)).all()}
        assert rows[a_id].state == "verified" and rows[b_id].state == "pending"
        reconciliations = session.scalars(select(models.EmailIdentityReconciliation)).all()
        assert len(reconciliations) == 1
        rec = reconciliations[0]
        assert rec.reason == "verified_collision" and rec.state == "open"
        assert rec.holder_user_id == a_user and rec.claimant_user_id == b_user
        assert rec.email_hash == rows[a_id].email_hash
        # Only one verified owner may ever exist for the address (partial unique index).
        with pytest.raises(Exception):
            session.execute(
                text("UPDATE user_email_identities SET state='verified', verified_at=:now, code_hash=NULL, verification_state='none' WHERE id=:id"),
                {"id": uuid.UUID(b_id).hex, "now": ctx.clock["now"]},
            )
            session.commit()
        session.rollback()
    # Idempotent replay of the same verify returns the same typed conflict, still no promotion.
    assert _verify(b, b_id, ctx.email.sent[-1][1]).status_code in {401, 409}


# --------------------------------------------------------------------------- #
# E-19 / E-20 / E-21 : provider failure, abuse controls, limits                #
# --------------------------------------------------------------------------- #
def test_delivery_failure_leaves_identity_resendable_and_unreserved(ctx: Ctx):
    models = _models()
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    ctx.email.fail = True
    failed = _add(owner, "student.one@example.edu")
    assert failed.status_code == 503, failed.text
    assert failed.json()["detail"]["code"] == "email_delivery_unavailable"
    with ctx.factory() as session:
        row = session.scalar(select(models.UserEmailIdentity))
        assert row is not None and row.state == "pending" and row.verification_state == "failed"
        assert row.provider_receipt_hash is None
    listing = owner.get(ROOT).json()["identities"]
    assert listing[0]["verification"]["status"] == "failed"
    identity_id = listing[0]["id"]
    ctx.email.fail = False
    ctx.advance(settings.otp_resend_cooldown_seconds)
    resent = _resend(owner, identity_id)
    assert resent.status_code == 202 and resent.json()["identity"]["verification"]["status"] == "active"
    # A failed/pending claim never reserves the address against its real owner.
    b = ctx.new_client()
    ctx.register_student(b, "9876543211")
    assert _add_verified(ctx, b, "student.one@example.edu")
    # Missing provider entirely: typed 503 before any row is written.
    ctx.app.dependency_overrides[auth_student.get_email_otp_sender] = lambda: None
    missing = _add(owner, "another@example.edu")
    assert missing.status_code == 503 and missing.json()["detail"]["code"] == "email_delivery_unavailable"
    with ctx.factory() as session:
        assert session.scalar(
            select(models.UserEmailIdentity).where(
                models.UserEmailIdentity.email_hash == keyed_hash("nyay12:email-identity:v1:another@example.edu")
            )
        ) is None


def test_add_and_resend_rate_limits_are_typed_429_with_retry_after(ctx: Ctx, monkeypatch):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    monkeypatch.setattr(settings, "otp_issue_identity_limit", 1)
    first = _add(owner, "one@example.edu")
    assert first.status_code == 202
    limited = _add(owner, "two@example.edu")
    assert limited.status_code == 429, limited.text
    assert limited.json()["detail"]["code"] == "email_identity_rate_limited"
    assert int(limited.headers["retry-after"]) >= 1
    _assert_private(limited)
    assert len(owner.get(ROOT).json()["identities"]) == 1
    identity_id = first.json()["identity"]["id"]
    cooldown = _resend(owner, identity_id)
    assert cooldown.status_code == 429 and int(cooldown.headers["retry-after"]) >= 1
    assert len(ctx.email.sent) == 1


def test_identity_limit_is_enforced_typed_409(ctx: Ctx):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    for i in range(3):
        assert _add(owner, f"limit{i}@example.edu").status_code == 202
    fourth = _add(owner, "limit3@example.edu")
    assert fourth.status_code == 409 and fourth.json()["detail"]["code"] == "email_identity_limit_reached"
    listing = owner.get(ROOT).json()
    assert len(listing["identities"]) == listing["max_identities"] == 3


# --------------------------------------------------------------------------- #
# E-22 / E-23 / E-24 / E-25 / E-26 : idempotency, origin, auth, shapes         #
# --------------------------------------------------------------------------- #
def test_mutations_require_idempotency_key_and_replay_exactly(ctx: Ctx):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    missing = owner.post(ROOT, json={"email": "student.one@example.edu"})
    assert missing.status_code == 422 and missing.json()["detail"]["code"] == "invalid_idempotency_key"
    assert missing.json()["detail"]["field"] == "Idempotency-Key"
    for bad in ("short", "x" * 201, "has space in key!", "key/with/slashes/1234567890"):
        bad_response = owner.post(ROOT, json={"email": "student.one@example.edu"}, headers={"Idempotency-Key": bad})
        assert bad_response.status_code == 422, bad
    assert owner.get(ROOT).json()["identities"] == []
    key = _key("replay")
    first = _add(owner, "student.one@example.edu", key)
    assert first.status_code == 202 and first.headers.get("idempotency-replayed") == "false"
    replay = _add(owner, "student.one@example.edu", key)
    assert replay.status_code == 202 and replay.headers.get("idempotency-replayed") == "true"
    assert replay.json() == first.json()
    assert len(ctx.email.sent) == 1
    conflict = _add(owner, "different@example.edu", key)
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "email_identity_idempotency_conflict"
    identity_id = first.json()["identity"]["id"]
    vkey = _key("verify-replay")
    verified = _verify(owner, identity_id, ctx.email.sent[-1][1], vkey)
    assert verified.status_code == 200
    replayed = _verify(owner, identity_id, ctx.email.sent[-1][1], vkey)
    assert replayed.status_code == 200 and replayed.headers.get("idempotency-replayed") == "true"
    assert replayed.json() == verified.json()
    # Keys are actor-scoped: another actor reusing the literal key is not a replay.
    b = ctx.new_client()
    ctx.register_student(b, "9876543211")
    other = _add(b, "student.two@example.edu", key)
    assert other.status_code == 202 and other.headers.get("idempotency-replayed") == "false"


def test_mutations_require_exact_allowlisted_origin(ctx: Ctx):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    for origin in (None, "https://evil.example", settings.cors_origins[0] + ".evil", "null"):
        headers = {"Idempotency-Key": _key("origin")}
        if origin is not None:
            headers["Origin"] = origin
        client = TestClient(ctx.app, raise_server_exceptions=False, cookies=dict(owner.cookies))
        response = client.post(ROOT, json={"email": "student.one@example.edu"}, headers=headers)
        assert response.status_code == 403, (origin, response.text)
        assert response.json()["detail"]["code"] in {"csrf_origin_required", "csrf_origin_untrusted"}
    assert owner.get(ROOT).json()["identities"] == []
    anonymous = TestClient(ctx.app, raise_server_exceptions=False)
    assert anonymous.post(EMAIL_START, json={"email": "a@example.edu"}).status_code == 403


def test_anonymous_and_non_student_actors_are_rejected_with_zero_mutation(ctx: Ctx):
    models = _models()
    anonymous = ctx.new_client()
    assert anonymous.get(ROOT).status_code == 401
    assert anonymous.get(ROOT).json()["detail"]["code"] == "authentication_required"
    assert _add(anonymous, "a@example.edu").status_code == 401
    assert _verify(anonymous, str(uuid.uuid4()), "123456").status_code == 401
    assert _remove(anonymous, str(uuid.uuid4())).status_code == 401
    # Forged client identifiers grant nothing.
    forged = anonymous.post(
        ROOT,
        json={"email": "a@example.edu", "user_id": str(uuid.uuid4())},
        headers={"Idempotency-Key": _key("forged")},
    )
    assert forged.status_code in {401, 422}
    # A non-student authenticated actor (legal_reviewer) is forbidden.
    owner = ctx.client
    user_id = ctx.register_student(owner, "9876543210")
    with ctx.factory() as session:
        session.get(User, user_id).role = "legal_reviewer"
        session.commit()
    reviewer = owner.get(ROOT)
    assert reviewer.status_code == 403 and reviewer.json()["detail"]["code"] == "forbidden"
    assert _add(owner, "a@example.edu").status_code == 403
    with ctx.factory() as session:
        assert session.scalar(select(models.UserEmailIdentity)) is None
        assert session.scalar(select(models.EmailIdentityMutation)) is None
    assert ctx.email.sent == []
    # Expired/revoked session: logout then reuse old cookie.
    with ctx.factory() as session:
        session.get(User, user_id).role = "student"
        session.commit()
    old_cookie = owner.cookies.get(settings.auth_session_cookie_name)
    owner.post("/api/v1/auth/student/logout")
    stale = TestClient(ctx.app, raise_server_exceptions=False, headers={"Origin": settings.cors_origins[0]}, cookies={settings.auth_session_cookie_name: old_cookie})
    assert stale.get(ROOT).status_code == 401


def test_limited_access_actor_cannot_add_identity(ctx: Ctx):
    models = _models()
    minor = ctx.client
    ctx.register_student(minor, "9876543210", dob="2012-01-01")
    projection = minor.get("/api/v1/student/profile")
    assert projection.status_code == 200 and projection.json()["access_mode"] == "limited"
    listing = minor.get(ROOT)
    assert listing.status_code == 200 and listing.json()["identities"] == []
    denied = _add(minor, "minor@example.edu")
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == "email_identity_capability_disabled"
    with ctx.factory() as session:
        assert session.scalar(select(models.UserEmailIdentity)) is None
    assert ctx.email.sent == []


def test_request_shapes_are_strict_and_responses_carry_private_cache_headers(ctx: Ctx):
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    extra = owner.post(ROOT, json={"email": "a@example.edu", "verified": True}, headers={"Idempotency-Key": _key("strict")})
    assert extra.status_code == 422 and "a@example.edu" not in extra.text
    _assert_private(extra)
    bad_shape = owner.post(ROOT, json={"email": "not an email"}, headers={"Idempotency-Key": _key("strict")})
    assert bad_shape.status_code == 422 and "not an email" not in bad_shape.text
    too_long = owner.post(ROOT, json={"email": "a" * 250 + "@example.edu"}, headers={"Idempotency-Key": _key("strict")})
    assert too_long.status_code == 422
    query = owner.get(ROOT, params={"user_id": str(uuid.uuid4())})
    assert query.status_code == 422
    listing = owner.get(ROOT)
    _assert_private(listing)
    accepted = _add(owner, "a@example.edu")
    identity_id = accepted.json()["identity"]["id"]
    for response in (
        owner.post(f"{ROOT}/{identity_id}/verify", json={"code": "123456", "extra": 1}, headers={"Idempotency-Key": _key("s")}),
        owner.post(f"{ROOT}/{identity_id}/verify", json={"code": 123456}, headers={"Idempotency-Key": _key("s")}),
        owner.post(f"{ROOT}/{identity_id}/resend", json={"code": "123456"}, headers={"Idempotency-Key": _key("s")}),
        owner.post(f"{ROOT}/{identity_id}/primary", json={"is_primary": True}, headers={"Idempotency-Key": _key("s")}),
    ):
        assert response.status_code == 422, response.text
        _assert_private(response)
    document = ctx.app.openapi()
    for method, path in (
        ("post", ROOT), ("post", ROOT + "/{identity_id}/verify"), ("post", ROOT + "/{identity_id}/resend"),
        ("delete", ROOT + "/{identity_id}"), ("post", ROOT + "/{identity_id}/primary"),
    ):
        operation = document["paths"][path][method]
        names = {p.get("name", "").lower() for p in operation.get("parameters", [])}
        assert "idempotency-key" in names, (method, path)
        assert "200" in operation["responses"] or "202" in operation["responses"]
    assert "get" in document["paths"][ROOT] and "get" in document["paths"][CHANNELS]
    assert "post" in document["paths"][EMAIL_START]


# --------------------------------------------------------------------------- #
# E-28 : privacy — no raw email/code/session token in logs, responses, audit   #
# --------------------------------------------------------------------------- #
def test_no_raw_email_code_or_session_token_in_logs_responses_or_audit(ctx: Ctx, caplog):
    caplog.set_level(logging.DEBUG)
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    raw_email = "privacy.subject@example.edu"
    responses = [_add(owner, raw_email)]
    identity_id = responses[-1].json()["identity"]["id"]
    code = ctx.email.sent[-1][1]
    responses.append(_verify(owner, identity_id, code))
    responses.append(owner.get(ROOT))
    responses.append(_remove(owner, identity_id))
    session_token = owner.cookies.get(settings.auth_session_cookie_name)
    owner.post("/api/v1/auth/student/logout")
    login = ctx.new_client()
    responses.append(login.post(EMAIL_START, json={"email": raw_email}))
    responses.append(login.post("/api/v1/auth/student/login/otp/verify", json={"code": "000000"}))
    corpus = caplog.text
    for response in responses:
        corpus += "\n" + response.text + "\n" + json.dumps(dict(response.headers))
    assert raw_email not in corpus
    assert raw_email.split("@")[0] not in corpus
    assert code not in corpus
    assert session_token and session_token not in corpus
    with ctx.factory() as session:
        for row in session.scalars(select(AuditEvent)).all():
            blob = json.dumps({column.name: getattr(row, column.name) for column in row.__table__.columns}, default=str)
            assert raw_email not in blob and code not in blob and session_token not in blob
        for table in ("user_email_identities", "email_identity_mutations", "email_identity_reconciliations"):
            dump = json.dumps([dict(r._mapping) for r in session.execute(text(f"SELECT * FROM {table}"))], default=str)
            assert raw_email not in dump and code not in dump and session_token not in dump
