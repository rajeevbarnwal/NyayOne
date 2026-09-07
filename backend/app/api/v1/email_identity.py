"""NYAY-12 owner-scoped verified-email identity API (add/verify/resend/remove/primary).

All errors are typed and PII-free; every response is ``private, no-store``.
Mutations require the exact allowlisted Origin, the presented student session and
one ``Idempotency-Key`` (16–200 chars of ``A-Z a-z 0-9 . _ ~ -``). Request bodies
are validated by closed strict models inside the handler so framework 422s never
bypass the private cache headers.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
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


class _StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmailBody(_StrictBody):
    email: str = Field(min_length=3, max_length=254)


class CodeBody(_StrictBody):
    code: str = Field(pattern=r"^[0-9]{6}$")


class EmptyBody(_StrictBody):
    pass


class VerificationProjection(_StrictBody):
    status: str
    expires_in_seconds: int | None
    resend_in_seconds: int | None
    attempts_left: int | None


class IdentityProjection(_StrictBody):
    id: str
    email_masked: str
    state: str
    is_primary: bool
    verification: VerificationProjection


class IdentityListResponse(_StrictBody):
    login_channel_enabled: bool
    max_identities: int
    identities: list[IdentityProjection]


class IdentityMutationResponse(_StrictBody):
    status: str
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


def _parse(model: type[_StrictBody], payload: object, field: str) -> _StrictBody:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise _error(422, "validation_error", field=field) from exc


def _run(session: Session, response: Response, function, *args, **kwargs) -> dict[str, Any]:
    try:
        status_code, body, replayed = function(session, *args, **kwargs)
    except service.EmailIdentityError as exc:
        session.rollback()
        raise _error(exc.status_code, exc.code, field=exc.field, retry_after_seconds=exc.retry_after_seconds) from exc
    response.status_code = status_code
    response.headers["Idempotency-Replayed"] = "true" if replayed else "false"
    return body


MUTATION = [Depends(require_trusted_cookie_origin)]


@router.get("", response_model=IdentityListResponse)
def list_email_identities(context=Depends(_context), session: Session = Depends(get_session)) -> dict[str, Any]:
    actor_user_id, _ = context
    return service.list_identities(session, actor_user_id, now=_now())


@router.post("", response_model=IdentityMutationResponse, status_code=202, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
def add_email_identity(
    request: Request,
    response: Response,
    payload: Any = Body(default=None),
    context=Depends(_context),
    session: Session = Depends(get_session),
    sender: IdempotentOtpSender | None = Depends(get_email_otp_sender),
) -> dict[str, Any]:
    actor_user_id, raw_token = context
    key = _idempotency_key(request)
    body = _parse(EmailBody, payload, "email")
    return _run(
        session, response, service.add_identity, actor_user_id, raw_token,
        email=body.email, sender=sender, key=key, client_ip=_client_ip(request), now=_now(),
    )


@router.post("/{identity_id}/verify", response_model=IdentityMutationResponse, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
def verify_email_identity(
    identity_id: str,
    request: Request,
    response: Response,
    payload: Any = Body(default=None),
    context=Depends(_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    actor_user_id, raw_token = context
    key = _idempotency_key(request)
    body = _parse(CodeBody, payload, "code")
    return _run(
        session, response, service.verify_identity, actor_user_id, raw_token,
        identity_id=identity_id, code=body.code, key=key, now=_now(),
    )


@router.post("/{identity_id}/resend", response_model=IdentityMutationResponse, status_code=202, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
def resend_email_identity(
    identity_id: str,
    request: Request,
    response: Response,
    payload: Any = Body(default=None),
    context=Depends(_context),
    session: Session = Depends(get_session),
    sender: IdempotentOtpSender | None = Depends(get_email_otp_sender),
) -> dict[str, Any]:
    actor_user_id, raw_token = context
    key = _idempotency_key(request)
    _parse(EmptyBody, payload if payload is not None else {}, "request")
    return _run(
        session, response, service.resend_identity, actor_user_id, raw_token,
        identity_id=identity_id, sender=sender, key=key, client_ip=_client_ip(request), now=_now(),
    )


@router.delete("/{identity_id}", response_model=IdentityMutationResponse, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
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


@router.post("/{identity_id}/primary", response_model=IdentityMutationResponse, openapi_extra=required_idempotency_header(), dependencies=MUTATION)
def set_primary_email_identity(
    identity_id: str,
    request: Request,
    response: Response,
    payload: Any = Body(default=None),
    context=Depends(_context),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    actor_user_id, raw_token = context
    key = _idempotency_key(request)
    _parse(EmptyBody, payload if payload is not None else {}, "request")
    return _run(
        session, response, service.set_primary, actor_user_id, raw_token,
        identity_id=identity_id, key=key, now=_now(),
    )
