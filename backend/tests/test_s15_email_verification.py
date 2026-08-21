"""S-15 institutional-email request boundary (SAATHI-109/449)."""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 -- register every mapped table
from app.api.v1 import auth_student as ep
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.db.base import Base
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import StudentRegistration, StudentVerification
from app.schemas.registration import InstitutionalEmailVerificationRequest


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
                session.commit()
            except Exception:
                session.rollback()
                raise

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(ep.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = prod_session
    app.dependency_overrides[ep.get_otp_sender] = lambda: sender
    app.dependency_overrides[ep.get_outbox_session_factory] = lambda: factory

    yield (
        TestClient(app, headers={"Origin": settings.cors_origins[0]}),
        factory,
        sender,
    )
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
            "consent": {"accepted": True},
        },
    )
    assert registered.status_code == 201
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
    saved = client.patch(
        "/api/v1/auth/student/profile",
        json={
            "college": "National Law School of India University",
            "year_of_study": "3rd year",
            "enrolment_number": "KA/1234/2023",
            "institutional_email": "aditi@nls.ac.in",
        },
    )
    assert saved.status_code == 200
    return registration_id


def test_email_length_boundary_is_exactly_254():
    suffix = "@nls.ac.in"
    at_limit = f"{'a' * (254 - len(suffix))}{suffix}"
    request = InstitutionalEmailVerificationRequest(institutional_email=at_limit)
    assert len(request.institutional_email) == 254
    with pytest.raises(ValidationError):
        InstitutionalEmailVerificationRequest(institutional_email=f"a{at_limit}")


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


def test_valid_saved_email_is_accepted_and_audited_without_pii(ctx):
    client, factory, sender = ctx
    registration_id = _registration(client, factory, sender)

    response = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={"institutional_email": "  ADITI@NLS.AC.IN  "},
    )

    assert response.status_code == 202
    assert response.json() == {"status": "pending"}
    with factory() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "student.verification.email_requested"
            )
        )
        assert audit is not None
        registration = session.get(StudentRegistration, uuid.UUID(registration_id))
        assert audit.actor_user_id == registration.user_id
        assert audit.actor_role == "student"
        assert audit.after_state == {
            "registration_id": registration_id,
            "status": "pending",
        }
        assert "aditi@nls.ac.in" not in str(audit.after_state).lower()


def test_different_email_is_typed_422_and_not_audited(ctx):
    client, factory, sender = ctx
    _registration(client, factory, sender)

    response = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={"institutional_email": "other@nls.ac.in"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "institutional_email_mismatch",
        "field": "institutional_email",
        "message": "Use the institutional email saved in your academic profile",
    }
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "student.verification.email_requested")
        ) == 0
