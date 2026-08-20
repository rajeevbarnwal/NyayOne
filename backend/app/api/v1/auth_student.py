"""P0.2 student registration + OTP/recovery API (SAATHI-421/448).

Server-authoritative registration, OTP verify/resend, opaque account recovery
(start/verify/complete), guardian-consent completion and student-verification
status transitions. Delivery uses the transactional outbox: an OTP is never
handed to a provider before the transaction commits. No raw OTP/mobile is ever
returned, logged or placed in a URL.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
)
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import (
    ActorContext,
    Role,
    get_actor_context,
    require_trusted_cookie_origin,
)
from app.core.config import settings
from app.core.crypto import active_key_version, decrypt, encrypt, keyed_hash
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.db.session import get_sessionmaker
from app.models.registration import (
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    VERIFICATION_STATUSES,
)
from app.schemas.registration import (
    InstitutionalEmailVerificationRequest,
    StudentAcademicProfileRequest,
    StudentRegisterRequest,
    StudentRegisterResponse,
)
from app.services import (
    login_service,
    otp_outbox,
    otp_service,
    recovery_service,
    registration_service,
)
from app.services.otp_sender import OtpSender, OtpSendError, build_otp_sender
from app.services.registration_service import RegistrationError, register_student
from app.workers.otp_outbox_relay import deliver_after_response

router = APIRouter(prefix="/auth/student", tags=["auth"])
_MOBILE_RE = re.compile(r"^\d{10}$")
_OTP_RE = re.compile(r"^\d{6}$")

# Allowed student-verification status transitions (finite-state machine).
_VERIFICATION_TRANSITIONS = {
    "pending": {"in_review", "verified", "rejected"},
    "in_review": {"verified", "rejected"},
    "verified": set(),
    "rejected": {"in_review"},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_otp_sender() -> OtpSender | None:
    """Resolve the configured OTP provider. FastAPI dependency (override in tests)."""
    return build_otp_sender()


def get_outbox_session_factory() -> Callable[[], Session]:
    """Dependency seam for post-response outbox delivery."""
    return get_sessionmaker()


def _require_sender(sender: OtpSender | None) -> OtpSender:
    if sender is None:
        # Fail closed — never claim an OTP was sent when delivery isn't configured.
        raise HTTPException(status_code=503, detail={"code": "otp_delivery_unavailable"})
    return sender


def _require_student_actor(
    actor: ActorContext = Depends(get_actor_context),
) -> ActorContext:
    """Require the server-resolved student session for protected onboarding."""

    if not actor.is_authenticated:
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required"},
        )
    if not actor.has_role(Role.STUDENT):
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    return actor


def _require_verification_reviewer(
    actor: ActorContext = Depends(get_actor_context),
) -> ActorContext:
    """Require server-authenticated admin or legal-reviewer authority."""

    if not actor.is_authenticated:
        raise HTTPException(
            status_code=401,
            detail={"code": "authentication_required"},
        )
    if not (
        actor.has_role(Role.ADMIN) or actor.has_role(Role.LEGAL_REVIEWER)
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "verification_reviewer_required"},
        )
    return actor


def _owned_registration(
    session: Session,
    actor: ActorContext,
) -> StudentRegistration:
    """Resolve exactly one verified registration through its owner identity."""

    candidates = list(
        session.scalars(
            select(StudentRegistration)
            .where(
                StudentRegistration.user_id == actor.user_id,
                *otp_service.registration_authority_filters(),
            )
            .limit(2)
        )
    )
    if len(candidates) != 1:
        # Missing, deleted, quarantined, and structurally ambiguous ownership
        # deliberately share one response and cannot become enumeration oracles.
        raise HTTPException(
            status_code=404,
            detail={"code": "registration_not_found"},
        )
    return candidates[0]


# --------------------------------------------------------------------------- #
# Registration                                                                #
# --------------------------------------------------------------------------- #
@router.post("/register", response_model=StudentRegisterResponse, status_code=201)
def register(
    payload: StudentRegisterRequest,
    session: Session = Depends(get_session),
    sender: OtpSender | None = Depends(get_otp_sender),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> StudentRegisterResponse:
    # Idempotent replay is resolved BEFORE requiring a provider, so a replay
    # succeeds (201) even if delivery is currently unconfigured and never
    # re-delivers (SAATHI-448 A3).
    if idempotency_key:
        existing = registration_service.find_by_idempotency_key(session, idempotency_key)
        if existing is not None:
            return StudentRegisterResponse(registration_id=existing.id, status=existing.status)

    provider = _require_sender(sender)
    try:
        result = register_student(session, payload, idempotency_key, now=_now())
    except RegistrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "field": exc.field}) from exc

    # Commit the registration + challenge + pending-outbox row FIRST. Only after
    # a durable commit is the OTP handed to the provider.
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        if idempotency_key:
            existing = registration_service.find_by_idempotency_key(session, idempotency_key)
            if existing is not None:
                return StudentRegisterResponse(registration_id=existing.id, status=existing.status)
        raise HTTPException(status_code=409, detail={"code": "mobile_already_registered", "field": "mobile"}) from exc

    reg = result.registration
    if result.delivery is not None:
        try:
            otp_outbox.run_delivery(session, result.delivery, provider, raise_on_failure=True)
        except OtpSendError as exc:
            # Compensate: remove the registration so no unusable challenge remains
            # (observable end state = no rows), then surface a typed failure.
            registration_service.compensate_delete(session, reg.id)
            raise HTTPException(status_code=502, detail={"code": "otp_delivery_failed"}) from exc
    return StudentRegisterResponse(registration_id=reg.id, status=reg.status)


# --------------------------------------------------------------------------- #
# OTP verify / resend                                                         #
# --------------------------------------------------------------------------- #
class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration_id: uuid.UUID
    code: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        # Strict six-digit schema at the HTTP boundary. Malformed codes are
        # rejected as 422 WITHOUT consuming an OTP attempt (SAATHI-448 B1).
        if not _OTP_RE.match(v or ""):
            raise ValueError("OTP code must be exactly 6 digits.")
        return v


class RegistrationRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration_id: uuid.UUID


def _otp_error(exc: otp_service.OtpError) -> HTTPException:
    detail: dict = {"code": exc.code}
    if exc.attempts_left is not None:
        detail["attempts_left"] = exc.attempts_left
    return HTTPException(status_code=exc.status_code, detail=detail)


@router.post("/otp/verify")
def otp_verify(
    payload: OtpVerifyRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    now = _now()
    try:
        otp_service.verify(
            session,
            payload.registration_id,
            payload.code,
            now,
            purpose="signup",
            commit_on_success=False,
        )
    except otp_service.OtpError as exc:
        raise _otp_error(exc) from exc
    # Reuse the identity-map row locked and advanced to ``otp_verified`` by
    # otp_service.verify. Refreshing here would clobber that uncommitted state
    # with the database's prior ``otp_pending`` value.
    registration = session.get(StudentRegistration, payload.registration_id)
    if not otp_service.registration_is_authorizable(registration):
        session.rollback()
        raise HTTPException(
            status_code=404,
            detail={"code": "no_active_challenge"},
        )
    try:
        raw_token, _ = login_service.rotate_authenticated_session(
            session, registration, now
        )
    except login_service.LoginError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code},
        ) from exc
    _set_session_cookie(response, raw_token)
    return {"status": "verified"}


@router.post("/otp/resend", status_code=202)
def otp_resend(
    payload: RegistrationRef,
    session: Session = Depends(get_session),
    sender: OtpSender | None = Depends(get_otp_sender),
) -> dict[str, str]:
    provider = _require_sender(sender)
    reg = otp_service.lock_registration_for_update(
        session, payload.registration_id
    )
    if not otp_service.registration_accepts_otp_purpose(reg, "signup"):
        raise HTTPException(status_code=404, detail={"code": "registration_not_found"})
    destination = decrypt(reg.mobile_ct)
    try:
        _, intent = otp_service.resend(
            session, payload.registration_id, _now(), purpose="signup", destination=destination
        )
    except otp_service.OtpError as exc:
        raise _otp_error(exc) from exc
    session.commit()  # persist the new challenge + outbox row before delivering
    try:
        otp_outbox.run_delivery(session, intent, provider, raise_on_failure=True)
    except OtpSendError as exc:
        raise HTTPException(status_code=502, detail={"code": "otp_delivery_failed"}) from exc
    return {"status": "sent"}  # never returns the code


# --------------------------------------------------------------------------- #
# Academic profile (S-10)                                                     #
# --------------------------------------------------------------------------- #
@router.patch("/profile")
def update_academic_profile(
    payload: StudentAcademicProfileRequest,
    actor: ActorContext = Depends(_require_student_actor),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Persist academic fields for the authenticated registration owner."""

    reg = _owned_registration(session, actor)
    if reg.status not in {"otp_verified", "active"}:
        raise HTTPException(status_code=403, detail={"code": "otp_verification_required"})
    profile = session.scalar(
        select(StudentProfile).where(StudentProfile.registration_id == reg.id)
    )
    if profile is None:
        profile = StudentProfile(registration_id=reg.id)
        session.add(profile)
    profile.college = payload.college
    profile.year_of_study = payload.year_of_study
    profile.enrolment_ct = encrypt(payload.enrolment_number)
    profile.enrolment_hash = keyed_hash(payload.enrolment_number)
    profile.institutional_email_ct = encrypt(payload.institutional_email)
    profile.institutional_email_hash = keyed_hash(
        payload.institutional_email, lower=True
    )
    profile.bar_enrolment_ct = (
        encrypt(payload.bar_enrolment_number)
        if payload.bar_enrolment_number
        else None
    )
    profile.bar_enrolment_hash = (
        keyed_hash(payload.bar_enrolment_number)
        if payload.bar_enrolment_number
        else None
    )
    profile.key_version = active_key_version()
    reg.institution_ref = payload.college
    session.flush()
    session.add(
        AuditEvent(
            actor_user_id=actor.user_id,
            actor_role="student",
            action="student.profile.academic_updated",
            resource_type="student_profile",
            resource_id=profile.id,
            after_state={
                "registration_id": str(reg.id),
                "academic_fields": "complete",
                "key_version": profile.key_version,
            },
        )
    )
    session.commit()
    return {"status": "saved"}


# --------------------------------------------------------------------------- #
# Account recovery (opaque, anti-enumeration)                                 #
# --------------------------------------------------------------------------- #
class RecoveryStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobile: str

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str) -> str:
        if not _MOBILE_RE.match(v or ""):
            raise ValueError("Mobile number must be exactly 10 digits.")
        return v


class RecoveryVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recovery_id: str
    code: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _OTP_RE.match(v or ""):
            raise ValueError("OTP code must be exactly 6 digits.")
        return v


class RecoveryRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recovery_id: str


class LoginStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobile: str

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str) -> str:
        if not _MOBILE_RE.match(v or ""):
            raise ValueError("Mobile number must be exactly 10 digits.")
        return v


class LoginVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_id: str
    code: str

    @field_validator("login_id")
    @classmethod
    def _login_id(cls, v: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", v or ""):
            raise ValueError("Invalid login attempt.")
        return v

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _OTP_RE.match(v or ""):
            raise ValueError("OTP code must be exactly 6 digits.")
        return v


def _cookie_secure() -> bool:
    return (settings.app_env or "").strip().lower() not in {
        "local",
        "development",
        "dev",
        "test",
        "testing",
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=token,
        max_age=settings.auth_session_ttl_seconds,
        path="/",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_session_cookie_name,
        path="/",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


@router.post("/recovery/start", status_code=202)
def recovery_start(
    payload: RecoveryStartRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    sender: OtpSender | None = Depends(get_otp_sender),
    outbox_session_factory: Callable[[], Session] = Depends(get_outbox_session_factory),
) -> dict[str, str]:
    provider = _require_sender(sender)  # symmetric for known/unknown (both 503 if absent)
    opaque_id, intent = recovery_service.start(session, payload.mobile, _now())
    session.commit()
    # Provider I/O is scheduled after the response and uses a fresh session.
    # Known and unknown mobiles therefore share the same response path/timing;
    # a provider outage cannot become an account-enumeration oracle.
    if intent is not None:
        background_tasks.add_task(
            deliver_after_response,
            intent.outbox_id,
            provider,
            outbox_session_factory,
        )
    return {"recovery_id": opaque_id}


@router.post("/recovery/verify")
def recovery_verify(payload: RecoveryVerifyRequest, session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        recovery_service.verify(session, payload.recovery_id, payload.code, _now())
    except recovery_service.RecoveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
    return {"status": "verified"}


@router.post("/recovery/complete")
def recovery_complete(payload: RecoveryRef, session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        recovery_service.complete(session, payload.recovery_id, _now())
    except recovery_service.RecoveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code}) from exc
    return {"status": "recovered"}


# --------------------------------------------------------------------------- #
# OTP login + server-side authenticated session                               #
# --------------------------------------------------------------------------- #
@router.post("/login/otp/start", status_code=202)
def login_otp_start(
    payload: LoginStartRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    sender: OtpSender | None = Depends(get_otp_sender),
    outbox_session_factory: Callable[[], Session] = Depends(get_outbox_session_factory),
) -> dict[str, str]:
    provider = _require_sender(sender)
    opaque_id, intent = login_service.start(session, payload.mobile, _now())
    session.commit()
    if intent is not None:
        background_tasks.add_task(
            deliver_after_response,
            intent.outbox_id,
            provider,
            outbox_session_factory,
        )
    # Same 202 + shape for a known, unknown, suspended or cooldown account.
    return {"login_id": opaque_id}


@router.post("/login/otp/verify")
def login_otp_verify(
    payload: LoginVerifyRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, str]:
    try:
        raw_token, _ = login_service.verify(
            session, payload.login_id, payload.code, _now()
        )
    except login_service.LoginError as exc:
        raise HTTPException(
            status_code=exc.status_code, detail={"code": exc.code}
        ) from exc
    _set_session_cookie(response, raw_token)
    return {"status": "authenticated"}


@router.get("/session")
def student_session(
    request: Request,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    claims = login_service.session_claims(
        session,
        request.cookies.get(settings.auth_session_cookie_name),
        _now(),
    )
    if claims is None:
        # Session discovery is intentionally a non-error probe so an anonymous
        # app boot does not generate a console/network error. Protected APIs
        # still resolve the same missing/expired cookie to an anonymous actor
        # and return 401 through ``require_authenticated``.
        return {"authenticated": False, "actor": None}
    return {"authenticated": True, "actor": claims}


@router.post("/logout")
def student_logout(
    request: Request,
    response: Response,
    _: None = Depends(require_trusted_cookie_origin),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    login_service.logout(
        session,
        request.cookies.get(settings.auth_session_cookie_name),
        _now(),
    )
    _clear_session_cookie(response)
    return {"status": "logged_out"}


# --------------------------------------------------------------------------- #
# Guardian consent + verification status                                      #
# --------------------------------------------------------------------------- #
class EmptyProtectedRequest(BaseModel):
    """Explicitly reject legacy UUID capability bodies on selector-free APIs."""

    model_config = ConfigDict(extra="forbid")


@router.post("/guardian-consent/complete")
def guardian_consent_complete(
    _: EmptyProtectedRequest | None = Body(default=None),
    actor: ActorContext = Depends(_require_student_actor),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    reg = _owned_registration(session, actor)
    if not reg.is_minor:
        raise HTTPException(status_code=409, detail={"code": "guardian_consent_not_required"})
    # No guardian authentication/proof ceremony exists yet. Student authority
    # must never be promoted into guardian authority.
    raise HTTPException(
        status_code=403,
        detail={"code": "guardian_self_approval_forbidden"},
    )


class VerificationTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration_id: uuid.UUID
    status: str

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in VERIFICATION_STATUSES:
            raise ValueError(f"status must be one of {VERIFICATION_STATUSES}")
        return v


def _load_verification(session: Session, registration_id: uuid.UUID) -> StudentVerification:
    registration = session.get(
        StudentRegistration,
        registration_id,
        populate_existing=True,
    )
    ver = session.scalar(
        select(StudentVerification).where(
            StudentVerification.registration_id == registration_id
        )
    )
    if (
        not otp_service.registration_is_authorizable(registration)
        or ver is None
    ):
        raise HTTPException(status_code=404, detail={"code": "verification_not_found"})
    return ver


@router.post("/verification/email/request", status_code=202)
def request_institutional_email_verification(
    payload: InstitutionalEmailVerificationRequest,
    actor: ActorContext = Depends(_require_student_actor),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Accept an S-15 verification request only for the saved email.

    Invalid email syntax is rejected by the request schema before this function
    runs, and registration ownership is resolved from the server session.
    """
    reg = _owned_registration(session, actor)
    if reg.status not in {"otp_verified", "active"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "otp_verification_required", "message": "Verify the mobile number first"},
        )

    profile = session.scalar(
        select(StudentProfile).where(StudentProfile.registration_id == reg.id)
    )
    if (
        profile is None
        or profile.institutional_email_hash is None
        or profile.institutional_email_hash
        != keyed_hash(payload.institutional_email, lower=True)
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "institutional_email_mismatch",
                "field": "institutional_email",
                "message": "Use the institutional email saved in your academic profile",
            },
        )

    verification = _load_verification(session, reg.id)
    if verification.status == "verified":
        raise HTTPException(
            status_code=409,
            detail={"code": "institutional_email_already_verified", "message": "Email is already verified"},
        )
    verification.method = "institutional_email"
    verification.status = "pending"
    session.add(
        AuditEvent(
            actor_user_id=actor.user_id,
            actor_role="student",
            action="student.verification.email_requested",
            resource_type="student_verification",
            resource_id=verification.id,
            after_state={"registration_id": str(reg.id), "status": "pending"},
        )
    )
    session.commit()
    return {"status": "pending"}


@router.get("/verification/status")
def verification_status(
    request: Request,
    actor: ActorContext = Depends(_require_student_actor),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    if request.query_params:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "validation_error",
                "field": "query",
            },
        )
    registration = _owned_registration(session, actor)
    ver = _load_verification(session, registration.id)
    return {"status": ver.status, "method": ver.method}


@router.post("/verification/status")
def verification_transition(
    payload: VerificationTransitionRequest,
    actor: ActorContext = Depends(_require_verification_reviewer),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    ver = _load_verification(session, payload.registration_id)
    allowed = _VERIFICATION_TRANSITIONS.get(ver.status, set())
    if payload.status != ver.status and payload.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_transition", "from": ver.status, "to": payload.status},
        )
    before = ver.status
    ver.status = payload.status
    reviewer_role = (
        "legal_reviewer"
        if actor.has_role(Role.LEGAL_REVIEWER)
        else "admin"
    )
    session.add(
        AuditEvent(
            actor_user_id=actor.user_id,
            actor_role=reviewer_role,
            action="student.verification.status_changed",
            resource_type="student_verification",
            resource_id=ver.id,
            before_state={"status": before},
            after_state={"status": ver.status},
        )
    )
    session.commit()
    return {"status": ver.status}
