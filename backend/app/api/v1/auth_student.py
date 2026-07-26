"""P0.2 student registration API (SAATHI-421/448).

`POST /api/v1/auth/student/register` — validates via the shared contract,
persists transactionally, returns an opaque registration id + typed field errors,
supports idempotent replay (Idempotency-Key) and mobile-conflict handling.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt
from app.db.session import get_session
from app.models.registration import StudentRegistration
from app.schemas.registration import StudentRegisterRequest, StudentRegisterResponse
from app.services import otp_service
from app.services.otp_sender import OtpSendError, OtpSender, build_otp_sender
from app.services.registration_service import RegistrationError, register_student

router = APIRouter(prefix="/auth/student", tags=["auth"])
_MOBILE_RE = re.compile(r"^\d{10}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_otp_sender() -> OtpSender | None:
    """Resolve the configured OTP provider. FastAPI dependency (override in tests)."""
    return build_otp_sender()


def _require_sender(sender: OtpSender | None) -> OtpSender:
    if sender is None:
        # Fail closed — never claim an OTP was sent when delivery isn't configured.
        raise HTTPException(status_code=503, detail={"code": "otp_delivery_unavailable"})
    return sender


@router.post("/register", response_model=StudentRegisterResponse, status_code=201)
def register(
    payload: StudentRegisterRequest,
    session: Session = Depends(get_session),
    sender: OtpSender | None = Depends(get_otp_sender),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StudentRegisterResponse:
    provider = _require_sender(sender)
    try:
        reg = register_student(session, payload, idempotency_key, sender=provider)
    except RegistrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "field": exc.field}) from exc
    except OtpSendError as exc:
        raise HTTPException(status_code=502, detail={"code": "otp_delivery_failed"}) from exc
    return StudentRegisterResponse(registration_id=reg.id, status=reg.status)


class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration_id: uuid.UUID
    code: str


class RegistrationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration_id: uuid.UUID


class RecoveryStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobile: str

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str) -> str:
        if not _MOBILE_RE.match(v or ""):
            raise ValueError("Mobile number must be exactly 10 digits.")
        return v


def _otp_error(exc: otp_service.OtpError) -> HTTPException:
    detail = {"code": exc.code}
    if exc.attempts_left is not None:
        detail["attempts_left"] = exc.attempts_left
    return HTTPException(status_code=exc.status_code, detail=detail)


@router.post("/otp/verify")
def otp_verify(payload: OtpVerifyRequest, session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        otp_service.verify(session, payload.registration_id, payload.code, _now())
    except otp_service.OtpError as exc:
        raise _otp_error(exc) from exc
    return {"status": "verified"}


@router.post("/otp/resend", status_code=202)
def otp_resend(
    payload: RegistrationRef,
    session: Session = Depends(get_session),
    sender: OtpSender | None = Depends(get_otp_sender),
) -> dict[str, str]:
    provider = _require_sender(sender)
    reg = session.get(StudentRegistration, payload.registration_id)
    if reg is None:
        raise HTTPException(status_code=404, detail={"code": "registration_not_found"})
    destination = decrypt(reg.mobile_ct)
    try:
        otp_service.resend(session, payload.registration_id, _now(), send=lambda code: provider.send(destination, code))
        session.commit()
    except otp_service.OtpError as exc:
        raise _otp_error(exc) from exc
    except OtpSendError as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail={"code": "otp_delivery_failed"}) from exc
    return {"status": "sent"}  # never returns the code


@router.post("/recovery/start", status_code=202)
def recovery_start(
    payload: RecoveryStartRequest,
    session: Session = Depends(get_session),
    sender: OtpSender | None = Depends(get_otp_sender),
) -> dict[str, str]:
    provider = _require_sender(sender)
    # Always 202 + fresh opaque recovery id — indistinguishable for known/unknown.
    try:
        recovery_id = otp_service.start_recovery(
            session, payload.mobile, _now(), send=lambda code: provider.send(payload.mobile, code)
        )
        session.commit()
    except OtpSendError as exc:
        session.rollback()
        raise HTTPException(status_code=502, detail={"code": "otp_delivery_failed"}) from exc
    return {"recovery_id": recovery_id}
