"""P0.2 student registration API (SAATHI-421/448).

`POST /api/v1/auth/student/register` — validates via the shared contract,
persists transactionally, returns an opaque registration id + typed field errors,
supports idempotent replay (Idempotency-Key) and mobile-conflict handling.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.registration import StudentRegisterRequest, StudentRegisterResponse
from app.services import otp_service
from app.services.registration_service import RegistrationError, register_student

router = APIRouter(prefix="/auth/student", tags=["auth"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/register", response_model=StudentRegisterResponse, status_code=201)
def register(
    payload: StudentRegisterRequest,
    session: Session = Depends(get_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StudentRegisterResponse:
    try:
        reg = register_student(session, payload, idempotency_key)
    except RegistrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "field": exc.field}) from exc
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
def otp_resend(payload: RegistrationRef, session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        otp_service.resend(session, payload.registration_id, _now())
    except otp_service.OtpError as exc:
        raise _otp_error(exc) from exc
    return {"status": "sent"}  # never returns the code


@router.post("/recovery/start", status_code=202)
def recovery_start(payload: RecoveryStartRequest, session: Session = Depends(get_session)) -> dict[str, str]:
    # Always 202 + opaque recovery id — no account-existence leak.
    recovery_id = otp_service.start_recovery(session, payload.mobile, _now())
    return {"recovery_id": recovery_id}
