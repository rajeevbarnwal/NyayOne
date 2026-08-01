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
from app.core.exceptions import register_exception_handlers
from app.db.base import Base
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import StudentVerification
from app.schemas.registration import InstitutionalEmailVerificationRequest


class CapturingSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, destination: str, code: str) -> None:
        self.sent.append((destination, code))


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

    yield TestClient(app), factory, sender
    Base.metadata.drop_all(engine)


def _registration(client: TestClient, sender: CapturingSender) -> str:
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
    verified = client.post(
        "/api/v1/auth/student/otp/verify",
        json={"registration_id": registration_id, "code": sender.sent[-1][1]},
    )
    assert verified.status_code == 200
    saved = client.patch(
        "/api/v1/auth/student/profile",
        json={
            "registration_id": registration_id,
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
    request = InstitutionalEmailVerificationRequest(
        registration_id=uuid.uuid4(), institutional_email=at_limit
    )
    assert len(request.institutional_email) == 254
    with pytest.raises(ValidationError):
        InstitutionalEmailVerificationRequest(
            registration_id=uuid.uuid4(), institutional_email=f"a{at_limit}"
        )


@pytest.mark.parametrize(
    "invalid_email",
    ["", "not-an-email", f"{'a' * 250}@nls.ac.in"],
    ids=["empty", "malformed", "overlength"],
)
def test_invalid_email_is_typed_422_with_zero_mutation(ctx, invalid_email: str):
    client, factory, sender = ctx
    registration_id = _registration(client, sender)
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
        json={
            "registration_id": registration_id,
            "institutional_email": invalid_email,
        },
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
    registration_id = _registration(client, sender)

    response = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={
            "registration_id": registration_id,
            "institutional_email": "  ADITI@NLS.AC.IN  ",
        },
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
        assert audit.after_state == {
            "registration_id": registration_id,
            "status": "pending",
        }
        assert "aditi@nls.ac.in" not in str(audit.after_state).lower()


def test_different_email_is_typed_422_and_not_audited(ctx):
    client, factory, sender = ctx
    registration_id = _registration(client, sender)

    response = client.post(
        "/api/v1/auth/student/verification/email/request",
        json={
            "registration_id": registration_id,
            "institutional_email": "other@nls.ac.in",
        },
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
