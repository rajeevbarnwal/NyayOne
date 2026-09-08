"""NYAY-12 owner-scoped verified-email identity API (add/verify/resend/remove/primary).

The published OpenAPI document is the enforced contract: every request body is
a required closed model (``additionalProperties: false``) and every response
carries closed enums. Auth precedence is preserved because FastAPI resolves the
session/origin dependencies before body validation, and framework 422s on the
closed route set keep the ``private, no-store`` headers (see core.exceptions).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.openapi_headers import required_idempotency_header
from app.api.v1.auth_student import _client_ip, get_email_otp_sender
from app.core.auth import ActorContext, Role, get_actor_context, require_trusted_cookie_origin
from app.core.config import settings
from app.db.session import get_session
from app.services import email_identity_service as service
from app.services.otp_sender import IdempotentOtpSender

router = APIRouter(prefix="/auth/student/email-identities", tags=["auth"])
_PRIVATE = {"Cache-Control": "private, no-store", "Vary": "Cookie"}

IdentityState = Literal["pending", "verified", "removed"]
VerificationStatus = Literal["none", "pending_delivery", "active", "failed", "expired"]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmailBody(_Closed):
    email: str = Field(min_length=3, max_length=254)


class CodeBody(_Closed):
    code: str = Field(pattern=r"^[0-9]{6}$")


class EmptyBody(_Closed):
    pass


class VerificationProjection(_Closed):
    status: VerificationStatus
    expires_in_seconds: int | None = Field(ge=0)
    resend_in_seconds: int | None = Field(ge=0)
    attempts_left: int | None = Field(ge=0)


class IdentityProjection(_Closed):
    id: str
    email_masked: str
    state: IdentityState
    is_primary: bool
    verification: VerificationProjection


class IdentityListResponse(_Closed):
    login_channel_enabled: bool
    max_identities: int = Field(ge=1)
    identities: list[IdentityProjection]


class AcceptedIdentityResponse(_Closed):
    status: Literal["accepted"]
    identity: IdentityProjection


class VerifiedIdentityResponse(_Closed):
    status: Literal["verified"]
    identity: IdentityProjection


class RemovedIdentityResponse(_Closed):
    status: Literal["removed"]
    identity: IdentityProjection


class PrimaryIdentityResponse(_Closed):
    status: Literal["primary"]
    identity: IdentityProjection


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _error(status_code: int, code: str, *, field: str | None = None, retry_after_seconds: int | None = None) -> HTTPException:
    detail: dict[str, Any] = {"code": code}
    if field is not None:
        detail["field"] = field
    headers = dict(_PRIVATE)
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(max(1, int(retry_after_seconds)))
    return HTTPException(status_code=status_code, detail=detail, headers=headers)


def _context(request: Request, response: Response, actor: ActorContext = Depends(get_actor_context)):
    response.headers.update(_PRIVATE)
    if request.query_params:
        raise _error(422, "validation_error", field="query")
    if not actor.is_authenticated:
        raise _error(401, "authentication_required")
    if not actor.has_role(Role.STUDENT):
        raise _error(403, "forbidden")
    return actor.user_id, request.cookies.get(settings.auth_session_cookie_name)


def _idempotency_key(request: Request) -> str:
    values = request.headers.getlist("idempotency-key")
    key = values[0] if len(values) == 1 else ""
    try:
        return service.validate_idempotency_key(key)
    except service.EmailIdentityError as exc:
        raise _error(exc.status_code, exc.code, field=exc.field) from exc


def _run(session: Session, response: Response, function, *args, **kwargs) -> dict[str, Any]:
    try:
        status_code, body, replayed = function(session, *args, **kwargs)
    except service.EmailIdentityError as exc:
        session.rollback()
        raise _error(exc.status_code, exc.code, field=exc.field, retry_after_seconds=exc.retry_after_seconds) from exc
    response.status_code = status_code
    response.headers["Idempotency-Replayed"] = "true" if replayed else "false"
    return body


# Dependency order matters: the session/origin authority resolves before FastAPI
# validates the closed body, so an anonymous malformed request is 401, not 422.
MUTATION = [Depends(require_trusted_cookie_origin)]


@router.get("", response_model=IdentityListResponse)
def list_email_identities(context=Depends(_context), session: Session = Depends(get_session)) -> dict[str, Any]:
    actor_user_id, _ = context
    return service.list_identities(session, actor_user_id, now=_now())


@router.post("", response_model=AcceptedIdentityResponse, status_code=202, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
def add_email_identity(
    payload: EmailBody,
    request: Request,
    response: Response,
    context=Depends(_context),
    session: Session = Depends(get_session),
    sender: IdempotentOtpSender | None = Depends(get_email_otp_sender),
) -> dict[str, Any]:
    actor_user_id, raw_token = context
    key = _idempotency_key(request)
    return _run(
        session, response, service.add_identity, actor_user_id, raw_token,
        email=payload.email, sender=sender, key=key, client_ip=_client_ip(request), now=_now(),
    )


@router.post("/{identity_id}/verify", response_model=VerifiedIdentityResponse, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
def verify_email_identity(
    identity_id: str,
    payload: CodeBody,
    request: Request,
    response: Response,
    context=Depends(_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    actor_user_id, raw_token = context
    key = _idempotency_key(request)
    return _run(
        session, response, service.verify_identity, actor_user_id, raw_token,
        identity_id=identity_id, code=payload.code, key=key, now=_now(),
    )


@router.post("/{identity_id}/resend", response_model=AcceptedIdentityResponse, status_code=202, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
def resend_email_identity(
    identity_id: str,
    payload: EmptyBody,
    request: Request,
    response: Response,
    context=Depends(_context),
    session: Session = Depends(get_session),
    sender: IdempotentOtpSender | None = Depends(get_email_otp_sender),
) -> dict[str, Any]:
    del payload
    actor_user_id, raw_token = context
    key = _idempotency_key(request)
    return _run(
        session, response, service.resend_identity, actor_user_id, raw_token,
        identity_id=identity_id, sender=sender, key=key, client_ip=_client_ip(request), now=_now(),
    )


@router.delete("/{identity_id}", response_model=RemovedIdentityResponse, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
def remove_email_identity(
    identity_id: str,
    request: Request,
    response: Response,
    context=Depends(_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    actor_user_id, raw_token = context
    key = _idempotency_key(request)
    return _run(
        session, response, service.remove_identity, actor_user_id, raw_token,
        identity_id=identity_id, key=key, now=_now(),
    )


@router.post("/{identity_id}/primary", response_model=PrimaryIdentityResponse, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
def set_primary_email_identity(
    identity_id: str,
    payload: EmptyBody,
    request: Request,
    response: Response,
    context=Depends(_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    del payload
    actor_user_id, raw_token = context
    key = _idempotency_key(request)
    return _run(
        session, response, service.set_primary, actor_user_id, raw_token,
        identity_id=identity_id, key=key, now=_now(),
    )
