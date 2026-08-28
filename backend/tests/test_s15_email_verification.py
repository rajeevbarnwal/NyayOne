"""S-15 institutional-email request boundary (SAATHI-109/449)."""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 -- register every mapped table
from app.api.v1 import auth_student as ep
from app.api.v1 import student_settings as profile_ep
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.base import Base
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import StudentRegistration, StudentVerification
from tests.profile_idempotency_fixture import install_profile_mutation_idempotency


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


def _assert_private_profile_projection(response) -> None:
    assert response.headers["cache-control"] == "private, no-store"
    assert "cookie" in {
        token.strip().casefold()
        for token in response.headers["vary"].split(",")
    }


@pytest.fixture()
def ctx():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    sender = CapturingSender()

    def prod_session():
        with factory() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise
            else:
                # Mirror app.db.session.get_session: endpoint/service owns any
                # write commit, and successful uncommitted work is discarded.
                session.rollback()

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(ep.router, prefix="/api/v1")
    app.include_router(profile_ep.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = prod_session
    app.dependency_overrides[ep.get_otp_sender] = lambda: sender
    app.dependency_overrides[ep.get_outbox_session_factory] = lambda: factory

    client = TestClient(app, headers={"Origin": settings.cors_origins[0]})
    install_profile_mutation_idempotency(client, prefix="s15-profile-mutation")
    yield (client, factory, sender)
    Base.metadata.drop_all(engine)


def _registration(
    client: TestClient, factory, sender: CapturingSender
) -> str:
    registered = client.post(
        "/api/v1/auth/student/register",
        json={
            "first_name": "Aditi",
            "last_name": "Nair",
            "mobile": "9876543210",
            "dob": "2004-03-14",
            "terms_accepted": True,
            "terms_version": "terms-2026-08.v1",
            "privacy_notice_acknowledged": True,
            "privacy_notice_version": "privacy-2026-08.v1",
        },
    )
    assert registered.status_code == 202
    with factory() as session:
        registration = session.scalar(select(StudentRegistration))
        assert registration is not None
        registration_id = str(registration.id)
    verified = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"code": sender.sent[-1][1]},
    )
    assert verified.status_code == 200
    client.headers["Origin"] = settings.cors_origins[0]
    personal = client.patch(
        "/api/v1/student/profile/personal",
        json={
            "expected_profile_version": 1,
            "first_name": "Aditi",
            "middle_name": None,
            "last_name": "Nair",
            "date_of_birth": "2004-03-14",
            "preferred_language": "en",
            "city": "Bengaluru",
            "pronouns": None,
        },
    )
    assert personal.status_code == 200
    saved = client.patch(
        "/api/v1/auth/student/profile",
        json={
            "expected_profile_version": 2,
            "college": "National Law School of India University",
            "year_of_study": "3rd year",
            "enrolment_number": "KA/1234/2023",
            "institutional_email": "aditi@nls.ac.in",
        },
    )
    assert saved.status_code == 200
    return registration_id


@pytest.mark.parametrize(
    "invalid_email",
    ["", "not-an-email", f"{'a' * 250}@nls.ac.in", "student@gmail.com"],
    ids=["empty", "malformed", "overlength", "consumer-domain"],
)
def test_invalid_email_is_typed_422_with_zero_mutation(ctx, invalid_email: str):
    client, factory, sender = ctx
    registration_id = _registration(client, factory, sender)
    with factory() as session:
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id == uuid.UUID(registration_id)
            )
        )
        before = (verification.method, verification.status, verification.updated_at)
        audit_before = session.scalar(select(func.count()).select_from(AuditEvent))

    response = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={"institutional_email": invalid_email},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert response.json()["detail"]["field"] == "institutional_email"
    if invalid_email:
        assert invalid_email not in response.text
    with factory() as session:
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id == uuid.UUID(registration_id)
            )
        )
        assert (verification.method, verification.status, verification.updated_at) == before
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == audit_before


def test_saved_email_verification_request_is_pending_projection_and_bounded_audit(ctx):
    client, factory, sender = ctx
    registration_id = _registration(client, factory, sender)
    with factory() as session:
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id == uuid.UUID(registration_id)
            )
        )
        assert verification.status == "pending"

    response = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={},
    )

    assert response.status_code == 202
    _assert_private_profile_projection(response)
    projection = response.json()
    assert projection["institutional_email_status"] == "pending"
    assert projection["profile"]["academic"]["institutional_email"] == "aditi@nls.ac.in"
    with factory() as session:
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id == uuid.UUID(registration_id)
            )
        )
        assert verification.status == "in_review"
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "student.verification.email_requested"
            )
        ).all()
        assert len(events) == 1
        event = events[0]
        assert event.resource_id is None
        assert event.after_state == {
            "outcome": "accepted",
            "status": "pending",
            "profile_version": 3,
        }
        serialized = str(event.after_state)
        assert "aditi@nls.ac.in" not in serialized
        assert registration_id not in serialized

    replay = client.post(
        "/api/v1/auth/student/verification/email/request", json={}
    )
    assert replay.status_code == 202
    _assert_private_profile_projection(replay)
    assert replay.json() == projection
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "student.verification.email_requested")
        ) == 1


def test_client_selected_email_is_typed_422_and_not_audited(ctx):
    client, factory, sender = ctx
    _registration(client, factory, sender)

    response = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={"institutional_email": "other@nls.ac.in"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "validation_error"
    assert response.json()["detail"]["field"] == "institutional_email"
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "student.verification.email_requested")
        ) == 0


def test_verification_request_rejects_query_selector_and_untrusted_origins(ctx):
    client, factory, sender = ctx
    registration_id = _registration(client, factory, sender)
    with factory() as session:
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id == uuid.UUID(registration_id)
            )
        )
        before = (verification.method, verification.status, verification.updated_at)

    query = client.post(
        f"/api/v1/auth/student/verification/email/request?registration_id={registration_id}",
        json={},
    )
    assert query.status_code == 422
    assert query.json()["detail"]["code"] == "validation_error"

    for origin in (
        None,
        "https://attacker.example",
        f"{settings.cors_origins[0]}.attacker.example",
    ):
        if origin is None:
            client.headers.pop("Origin", None)
        else:
            client.headers["Origin"] = origin
        denied = client.post(
            "/api/v1/auth/student/verification/email/request", json={}
        )
        assert denied.status_code == 403

    with factory() as session:
        verification = session.scalar(
            select(StudentVerification).where(
                StudentVerification.registration_id == uuid.UUID(registration_id)
            )
        )
        assert (verification.method, verification.status, verification.updated_at) == before
