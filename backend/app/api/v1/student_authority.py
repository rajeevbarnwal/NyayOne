"""Strict NYAY-11 command API; authority labels are never wire parameters."""
from datetime import datetime, timezone
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, get_actor_context, require_trusted_mutation_origin
from app.core.config import settings
from app.db.session import get_session
from app.services import student_authority as service
from app.services.otp_sender import build_otp_sender

router = APIRouter(prefix="/auth/student/authority", tags=["student-authority"])
MUTATION = [Depends(require_trusted_mutation_origin)]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Projection(StrictBody):
    policy_version: Literal["NYAY-11-v1"]
    guardian_state: Literal["NOT_REQUIRED", "REQUIRED_PENDING", "VERIFIED", "REJECTED", "REVOKED"]
    institutional_state: Literal["UNVERIFIED", "PENDING", "VERIFIED", "REJECTED", "EXPIRED", "REVOKED"]
    version: int = Field(ge=1)
    access_mode: Literal["limited", "full"]
    reverification_required: bool


class InvitationProjection(Projection):
    invitation: str = Field(min_length=32, max_length=128)


class Notification(StrictBody):
    code: Literal["review_returned_to_queue"]
    state_version: int = Field(ge=1)


class Notifications(StrictBody):
    notifications: list[Notification]


class ConsentBody(StrictBody):
    invitation: str = Field(min_length=32, max_length=128)
    relationship: Literal["parent", "legal_guardian"]
    accepted: bool


class RevokeBody(StrictBody):
    registration_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")


class ReviewBody(StrictBody):
    registration_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    approve: bool


class EmailBody(StrictBody):
    email: str = Field(min_length=3, max_length=254)
    institution: str = Field(min_length=1, max_length=120)


class CodeBody(StrictBody):
    code: str = Field(pattern=r"^[0-9]{6}$")


class StatusResponse(StrictBody):
    status: Literal["code_sent", "verified", "assigned"]


class AssignmentBody(StrictBody):
    reviewer_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    institution: str = Field(min_length=1, max_length=120)
    expires_at: str = Field(max_length=40)


def _now():
    return datetime.now(timezone.utc)


def _context(request: Request, response: Response, actor: ActorContext = Depends(get_actor_context)):
    response.headers.update({"Cache-Control": "private, no-store", "Vary": "Cookie"})
    if request.query_params:
        raise HTTPException(422, detail={"code": "authority_request_invalid"})
    if not actor.is_authenticated:
        raise HTTPException(401, detail={"code": "authentication_required"})
    return actor.user_id, request.cookies.get(settings.auth_session_cookie_name)


def _key(key: str = Header(alias="Idempotency-Key", min_length=16, max_length=200, pattern=r"^[A-Za-z0-9._~-]+$")):
    return key


def _command(session, function, *args, **kwargs):
    try:
        for name in ("registration_id", "reviewer_id"):
            if kwargs.get(name) is not None:
                kwargs[name] = uuid.UUID(kwargs[name])
        result = function(session, *args, **kwargs)
        session.commit()
        return result
    except service.AuthorityError as exc:
        session.rollback()
        raise HTTPException(exc.status_code, detail={"code": exc.code}, headers={"Cache-Control": "private, no-store", "Vary": "Cookie"}) from exc
    except (ValueError, TypeError) as exc:
        session.rollback()
        raise HTTPException(422, detail={"code": "authority_request_invalid"}, headers={"Cache-Control": "private, no-store"}) from exc


@router.get("", response_model=Projection)
def read(context=Depends(_context), session: Session = Depends(get_session)):
    return _command(session, service.read_authority, *context, now=_now())


@router.get("/notifications", response_model=Notifications)
def notifications(context=Depends(_context), session: Session = Depends(get_session)):
    return _command(session, service.read_notifications, *context, now=_now())


@router.post("/guardian/request", response_model=InvitationProjection, dependencies=MUTATION)
def guardian_request(payload: StrictBody, context=Depends(_context), key=Depends(_key), session: Session = Depends(get_session)):
    return _command(session, service.guardian_request, *context, key=key, now=_now())


@router.post("/guardian/consent", response_model=Projection, dependencies=MUTATION)
def guardian_consent(payload: ConsentBody, context=Depends(_context), key=Depends(_key), session: Session = Depends(get_session)):
    return _command(session, service.guardian_consent, *context, **payload.model_dump(), key=key, now=_now())


@router.post("/guardian/revoke", response_model=Projection, dependencies=MUTATION)
def guardian_revoke(payload: RevokeBody, context=Depends(_context), key=Depends(_key), session: Session = Depends(get_session)):
    return _command(session, service.guardian_revoke, *context, registration_id=payload.registration_id, key=key, now=_now())


@router.post("/institutional/request", response_model=Projection, dependencies=MUTATION)
def request_review(payload: StrictBody, context=Depends(_context), key=Depends(_key), session: Session = Depends(get_session)):
    return _command(session, service.request_review, *context, key=key, now=_now())


@router.post("/institutional/review", response_model=Projection, dependencies=MUTATION)
def review(payload: ReviewBody, context=Depends(_context), key=Depends(_key), session: Session = Depends(get_session)):
    return _command(session, service.review, *context, **payload.model_dump(), key=key, now=_now())


@router.post("/institutional/email/request", response_model=StatusResponse, dependencies=MUTATION)
def email_request(payload: EmailBody, context=Depends(_context), key=Depends(_key), session: Session = Depends(get_session), sender=Depends(build_otp_sender)):
    return _command(session, service.request_email_proof, *context, **payload.model_dump(), sender=sender, key=key, now=_now())


@router.post("/institutional/email/verify", response_model=StatusResponse, dependencies=MUTATION)
def email_verify(payload: CodeBody, context=Depends(_context), key=Depends(_key), session: Session = Depends(get_session)):
    return _command(session, service.verify_email_proof, *context, code=payload.code, key=key, now=_now())


@router.post("/institutional/assignment", response_model=StatusResponse, dependencies=MUTATION)
def assignment(payload: AssignmentBody, context=Depends(_context), key=Depends(_key), session: Session = Depends(get_session)):
    try:
        deadline = datetime.fromisoformat(payload.expires_at)
        if deadline.tzinfo is None:
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "authority_request_invalid"}) from exc
    return _command(session, service.assign_reviewer, *context, reviewer_id=payload.reviewer_id, institution=payload.institution, expires_at=deadline, key=key, now=_now())


@router.post("/institutional/break-glass", response_model=Projection, dependencies=MUTATION)
def break_glass(payload: RevokeBody, context=Depends(_context), key=Depends(_key), session: Session = Depends(get_session)):
    return _command(session, service.owner_break_glass, *context, registration_id=payload.registration_id, key=key, now=_now())
