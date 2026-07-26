"""P0.2 student registration API (SAATHI-421/448).

`POST /api/v1/auth/student/register` — validates via the shared contract,
persists transactionally, returns an opaque registration id + typed field errors,
supports idempotent replay (Idempotency-Key) and mobile-conflict handling.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.schemas.registration import StudentRegisterRequest, StudentRegisterResponse
from app.services.registration_service import RegistrationError, register_student

router = APIRouter(prefix="/auth/student", tags=["auth"])


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
