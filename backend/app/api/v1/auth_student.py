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
    require_trusted_mutation_origin,
)
from app.core.config import settings
from app.core.crypto import active_key_version, decrypt, encrypt, keyed_hash
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.db.session import get_sessionmaker
from app.models.registration import (
    OtpChallenge,
    OtpOutbox,
    OtpPurposeAuthority,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    VERIFICATION_STATUSES,
)
from app.schemas.registration import (
    InstitutionalEmailVerificationRequest,
    StudentAcademicProfileRequest,
    StudentRegisterRequest,
)
from app.services import (
    login_service,
    otp_authority,
    otp_flow_service,
    otp_service,
    recovery_service,
    registration_service,
)
from app.services.integrity_errors import constraint_name
from app.services.otp_sender import IdempotentOtpSender, build_otp_sender
from app.services.registration_service import RegistrationError, register_student
from app.workers.otp_outbox_relay import (
    deliver_after_response,
    deliver_resend_after_response,
    finalize_registration_after_response,
)

router = APIRouter(prefix="/auth/student", tags=["auth"])
_MOBILE_RE = re.compile(r"[0-9]{10}")
_OTP_RE = re.compile(r"[0-9]{6}")
_REGISTRATION_IDEMPOTENCY_CONSTRAINT = (
    "uq_registration_idempotency_records_idempotency_key_hash"
)
_REGISTRATION_MOBILE_CONSTRAINT = "uq_student_registrations_mobile_hash"

# Allowed student-verification status transitions (finite-state machine).
_VERIFICATION_TRANSITIONS = {
    "pending": {"in_review", "verified", "rejected"},
    "in_review": {"verified", "rejected"},
    "verified": set(),
    "rejected": {"in_review"},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_otp_sender() -> IdempotentOtpSender | None:
    """Resolve the configured OTP provider. FastAPI dependency (override in tests)."""
    return build_otp_sender()


def get_outbox_session_factory() -> Callable[[], Session]:
    """Dependency seam for post-response outbox delivery."""
    return get_sessionmaker()


def _require_sender(
    sender: IdempotentOtpSender | None,
) -> IdempotentOtpSender:
    if sender is None:
        # Fail closed — never claim an OTP was sent when delivery isn't configured.
        raise HTTPException(
            status_code=503,
            detail={"code": "otp_delivery_unavailable"},
            headers={"Cache-Control": "private, no-store", "Vary": "Cookie"},
        )
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
# Cookie-owned OTP authority                                                  #
# --------------------------------------------------------------------------- #
def _flow_cookie_value(request: Request) -> str | None:
    return request.cookies.get(settings.otp_flow_cookie_name)


def _set_flow_cookie(
    response: Response, token: str, *, max_age: int | None = None
) -> None:
    response.set_cookie(
        key=settings.otp_flow_cookie_name,
        value=token,
        max_age=max_age or settings.otp_flow_ttl_seconds,
        path="/api/v1",
        secure=_cookie_secure(),
        httponly=True,
        samesite="strict",
    )


def _clear_flow_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.otp_flow_cookie_name,
        path="/api/v1",
        secure=_cookie_secure(),
        httponly=True,
        samesite="strict",
    )


def _client_ip(request: Request) -> str | None:
    # Deliberately ignore X-Forwarded-For. Trusted-proxy resolution is not
    # configured at this boundary, so only the immediate peer is authoritative.
    return request.client.host if request.client is not None else None


def _otp_projection_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Cookie"


def _otp_error_headers(
    retry_after_seconds: int | None = None,
) -> dict[str, str]:
    headers = {"Cache-Control": "private, no-store", "Vary": "Cookie"}
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(max(1, retry_after_seconds))
    return headers


def _rate_limit(
    session: Session,
    request: Request,
    *,
    subject_hash: str,
    action: str,
    purpose: str,
    now: datetime,
) -> None:
    try:
        otp_authority.consume_rate_budgets(
            session,
            subject_hash=subject_hash,
            client_ip=_client_ip(request),
            action=action,
            purpose=purpose,
            now=now,
            commit=True,
        )
    except otp_authority.RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "otp_rate_limited",
                "otp_state": otp_flow_service.unavailable_state(),
            },
            headers=_otp_error_headers(exc.retry_after_seconds),
        ) from exc


def _flow_http_error(
    session: Session,
    raw_token: str | None,
    *,
    status_code: int,
    code: str,
    now: datetime,
    retry_after_seconds: int | None = None,
    field: str | None = None,
) -> HTTPException:
    detail: dict[str, object] = {
        "code": code,
        "otp_state": otp_flow_service.state_for_token(
            session, raw_token, now=now
        ),
    }
    if field is not None:
        detail["field"] = field
    return HTTPException(
        status_code=status_code,
        detail=detail,
        headers=_otp_error_headers(retry_after_seconds),
    )


def _otp_http_error(
    session: Session,
    raw_token: str | None,
    exc: otp_service.OtpError,
    *,
    now: datetime,
) -> HTTPException:
    return _flow_http_error(
        session,
        raw_token,
        status_code=exc.status_code,
        code=exc.code,
        now=now,
        retry_after_seconds=exc.retry_after_seconds,
    )


def _flow_subject_for_rate(session: Session, raw_token: str | None) -> str:
    return otp_flow_service.subject_for_token(session, raw_token)


def _signup_flow(
    session: Session,
    result: registration_service.RegistrationResult,
    *,
    raw_token: str,
    destination: str,
    now: datetime,
) -> tuple[str, object]:
    if result.delivery is None:
        graph = otp_flow_service.resolve_flow(session, raw_token)
        if graph is None:
            raise RuntimeError("registration replay lost its OTP flow graph")
        return raw_token, graph[1]
    outbox = session.get(OtpOutbox, result.delivery.outbox_id)
    challenge = (
        session.get(OtpChallenge, outbox.challenge_id)
        if outbox is not None
        else None
    )
    if challenge is None:
        raise RuntimeError("registration OTP delivery graph is incomplete")
    authority = otp_service.authority_for_registration(
        session, result.registration, "signup", now
    )
    return otp_flow_service.create_flow(
        session,
        authority,
        now=now,
        destination=destination,
        challenge=challenge,
        registration_id=result.registration.id,
        registration_idempotency_record_id=(
            result.idempotency_record.id
            if result.idempotency_record is not None
            else None
        ),
        raw_token=raw_token,
    )


def _decoy_signup_flow(
    session: Session,
    *,
    payload: StudentRegisterRequest,
    idempotency_key: str | None,
    now: datetime,
) -> tuple[str, object] | registration_service.RegistrationReplayResolution:
    # A duplicate/ineligible registration must not consume or rotate the real
    # account's OTP flow. Bind the decoy authority to this logical request,
    # while the separate abuse budget remains keyed to the supplied mobile.
    discriminator = idempotency_key or uuid.uuid4().hex
    reservation = None
    if idempotency_key is not None:
        reservation = registration_service.reserve_neutralized_registration(
            session, idempotency_key, payload, now=now
        )
        if isinstance(
            reservation,
            (
                registration_service.RegistrationResult,
                registration_service.NeutralizedRegistrationReplay,
            ),
        ):
            return reservation
    decoy_mobile_hash = keyed_hash(
        "nyayone:otp-registration-decoy:v1:" + discriminator
    )
    subject = otp_authority.authority_subject_from_mobile_hash(decoy_mobile_hash)
    authority = otp_authority.lock_or_create_authority(
        session,
        subject_hash=subject,
        purpose="signup",
        registration_id=None,
        now=now,
    )
    if authority.last_issued_at is None:
        otp_service.note_decoy_issue(authority, now=now)
    raw_token = (
        otp_flow_service.deterministic_signup_token(idempotency_key)
        if idempotency_key is not None
        else otp_flow_service.random_flow_token()
    )
    return otp_flow_service.create_flow(
        session,
        authority,
        now=now,
        destination=payload.mobile,
        challenge=None,
        registration_id=None,
        registration_idempotency_record_id=(
            reservation.id if reservation is not None else None
        ),
        raw_token=raw_token,
    )


# --------------------------------------------------------------------------- #
# Registration                                                                #
# --------------------------------------------------------------------------- #
def _registration_http_error(exc: RegistrationError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "field": exc.field},
    )


def _neutralized_replay_projection(
    session: Session,
    idempotency_key: str,
    *,
    now: datetime,
) -> tuple[str, otp_flow_service.OtpFlowState]:
    """Project only the deterministic live flow bound to a neutral winner."""

    raw_token = otp_flow_service.deterministic_signup_token(idempotency_key)
    graph = otp_flow_service.resolve_flow(session, raw_token)
    if graph is None:
        raise RuntimeError("neutralized registration flow disappeared")
    return raw_token, otp_flow_service.project(*graph, now=now)


def _finish_registration_replay(
    session: Session,
    response: Response,
    background_tasks: BackgroundTasks,
    resolution: registration_service.RegistrationReplayResolution,
    *,
    idempotency_key: str,
    payload: StudentRegisterRequest,
    now: datetime,
    sender: IdempotentOtpSender | None,
    outbox_session_factory: Callable[[], Session],
) -> otp_flow_service.OtpFlowState:
    """Return one typed real/neutral winner without creating another graph."""

    if isinstance(
        resolution, registration_service.NeutralizedRegistrationReplay
    ):
        raw_token, state = _neutralized_replay_projection(
            session, idempotency_key, now=now
        )
        delivery = None
    else:
        raw_token = otp_flow_service.deterministic_signup_token(
            idempotency_key
        )
        graph = otp_flow_service.resolve_flow(session, raw_token)
        if graph is None and resolution.delivery is not None:
            raw_token, flow = _signup_flow(
                session,
                resolution,
                raw_token=raw_token,
                destination=payload.mobile,
                now=now,
            )
            authority = session.get(OtpPurposeAuthority, flow.authority_id)
            state = otp_flow_service.project(authority, flow, now=now)
        elif graph is not None:
            state = otp_flow_service.project(*graph, now=now)
        else:
            raise RuntimeError("registration replay lost its OTP flow")
        delivery = resolution.delivery

    _set_flow_cookie(response, raw_token)
    if delivery is not None:
        # Provider work is resumed only for a real, already-bound delivery.
        # A neutral marker can never enter this branch.
        provider = _require_sender(sender)
        session.commit()
        background_tasks.add_task(
            finalize_registration_after_response,
            registration_service.registration_idempotency_key_hash(
                idempotency_key
            ),
            provider,
            outbox_session_factory,
        )
    else:
        # Releases the locked winner.  This is normally mutation-free; the
        # populated-0019 compatibility path may have recreated its bearer.
        session.commit()
    return state


def _recover_registration_integrity_conflict(
    session: Session,
    payload: StudentRegisterRequest,
    idempotency_key: str | None,
    exc: IntegrityError,
) -> registration_service.RegistrationReplayResolution:
    """Translate only exact named registration invariants after rollback.

    PostgreSQL can surface the losing idempotency race during either ``flush``
    or ``commit``. In both cases, compare the request against the durable winner
    before replaying it. Every unrelated integrity failure is re-raised so a
    schema/programming defect can never masquerade as a product conflict.
    """

    failed_constraint = constraint_name(exc)
    session.rollback()
    if (
        failed_constraint
        in {
            _REGISTRATION_IDEMPOTENCY_CONSTRAINT,
            _REGISTRATION_MOBILE_CONSTRAINT,
        }
        and idempotency_key is not None
    ):
        try:
            winner = registration_service.resolve_idempotent_replay(
                session, idempotency_key, payload
            )
        except RegistrationError as conflict:
            raise _registration_http_error(conflict) from exc
        if winner is not None:
            return winner
        if failed_constraint == _REGISTRATION_IDEMPOTENCY_CONSTRAINT:
            raise exc
    if failed_constraint == _REGISTRATION_MOBILE_CONSTRAINT:
        raise HTTPException(
            status_code=409,
            detail={"code": "mobile_already_registered", "field": "mobile"},
        ) from exc
    raise exc


def _commit_decoy_or_resolve_winner(
    session: Session,
    payload: StudentRegisterRequest,
    idempotency_key: str | None,
    *,
    now: datetime,
) -> tuple[str, object] | registration_service.RegistrationReplayResolution:
    """Commit one decoy graph or resolve an exact named concurrent winner."""

    try:
        outcome = _decoy_signup_flow(
            session,
            payload=payload,
            idempotency_key=idempotency_key,
            now=now,
        )
        if isinstance(outcome, tuple):
            session.commit()
        return outcome
    except IntegrityError as exc:
        return _recover_registration_integrity_conflict(
            session, payload, idempotency_key, exc
        )


@router.post("/register", status_code=201)
def register(
    payload: StudentRegisterRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_trusted_mutation_origin),
    session: Session = Depends(get_session),
    sender: IdempotentOtpSender | None = Depends(get_otp_sender),
    outbox_session_factory: Callable[[], Session] = Depends(
        get_outbox_session_factory
    ),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> otp_flow_service.OtpFlowState:
    if len(request.headers.getlist("idempotency-key")) > 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_idempotency_key",
                "field": "Idempotency-Key",
            },
        )
    try:
        idempotency_key = registration_service.validate_idempotency_key(
            idempotency_key
        )
    except RegistrationError as exc:
        raise _registration_http_error(exc) from exc

    now = _now()
    _otp_projection_headers(response)

    # A live exact replay only reconstructs the same HttpOnly bearer and safe
    # projection. An expired bootstrap performs the same bounded ledger+flow
    # terminalization for real and neutralized graphs; neither calls provider.
    if idempotency_key:
        try:
            existing = registration_service.resolve_idempotent_replay(
                session, idempotency_key, payload, now=now
            )
        except RegistrationError as exc:
            raise _registration_http_error(exc) from exc
        if existing is not None:
            return _finish_registration_replay(
                session,
                response,
                background_tasks,
                existing,
                idempotency_key=idempotency_key,
                payload=payload,
                now=now,
                sender=sender,
                outbox_session_factory=outbox_session_factory,
            )

    # Fresh real and neutralized requests share this provider-availability
    # decision before any account lookup can affect the HTTP outcome.
    provider = _require_sender(sender)

    mobile_subject = otp_authority.authority_subject_for_mobile(payload.mobile)
    _rate_limit(
        session,
        request,
        subject_hash=mobile_subject,
        action="issue",
        purpose="signup",
        now=now,
    )

    duplicate = False
    try:
        result = register_student(session, payload, idempotency_key, now=now)
    except RegistrationError as exc:
        if exc.code == "mobile_already_registered":
            session.rollback()
            duplicate = True
        else:
            raise _registration_http_error(exc) from exc
    except IntegrityError as exc:
        try:
            result = _recover_registration_integrity_conflict(
                session, payload, idempotency_key, exc
            )
        except HTTPException as conflict:
            if (
                isinstance(conflict.detail, dict)
                and conflict.detail.get("code") == "mobile_already_registered"
            ):
                duplicate = True
            else:
                raise

    if not duplicate and (
        isinstance(
            result, registration_service.NeutralizedRegistrationReplay
        )
        or (
            isinstance(result, registration_service.RegistrationResult)
            and result.replayed
        )
    ):
        if idempotency_key is None:
            raise RuntimeError("neutralized replay is missing its key authority")
        return _finish_registration_replay(
            session,
            response,
            background_tasks,
            result,
            idempotency_key=idempotency_key,
            payload=payload,
            now=now,
            sender=sender,
            outbox_session_factory=outbox_session_factory,
        )

    if duplicate:
        try:
            decoy = _commit_decoy_or_resolve_winner(
                session,
                payload,
                idempotency_key,
                now=now,
            )
        except RegistrationError as exc:
            raise _registration_http_error(exc) from exc
        if not isinstance(decoy, tuple):
            if idempotency_key is None:
                raise RuntimeError(
                    "registration replay is missing its key authority"
                )
            return _finish_registration_replay(
                session,
                response,
                background_tasks,
                decoy,
                idempotency_key=idempotency_key,
                payload=payload,
                now=now,
                sender=sender,
                outbox_session_factory=outbox_session_factory,
            )
        raw_token, flow = decoy
        authority = session.get(OtpPurposeAuthority, flow.authority_id)
        state = otp_flow_service.project(authority, flow, now=now)
        _set_flow_cookie(response, raw_token)
        return state

    raw_token = (
        otp_flow_service.deterministic_signup_token(idempotency_key)
        if idempotency_key is not None
        else otp_flow_service.random_flow_token()
    )
    raw_token, flow = _signup_flow(
        session,
        result,
        raw_token=raw_token,
        destination=payload.mobile,
        now=now,
    )
    authority = session.get(OtpPurposeAuthority, flow.authority_id)
    try:
        session.commit()
    except IntegrityError as exc:
        # A concurrent exact-key winner is resolved through the same replay
        # contract. A distinct-key mobile loser becomes a decoy flow.
        try:
            winner = _recover_registration_integrity_conflict(
                session, payload, idempotency_key, exc
            )
        except HTTPException as conflict:
            if not (
                isinstance(conflict.detail, dict)
                and conflict.detail.get("code") == "mobile_already_registered"
            ):
                raise
            try:
                decoy = _commit_decoy_or_resolve_winner(
                    session,
                    payload,
                    idempotency_key,
                    now=now,
                )
            except RegistrationError as decoy_conflict:
                raise _registration_http_error(decoy_conflict) from exc
            if not isinstance(decoy, tuple):
                if idempotency_key is None:
                    raise RuntimeError(
                        "registration replay is missing its key authority"
                    )
                return _finish_registration_replay(
                    session,
                    response,
                    background_tasks,
                    decoy,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    now=now,
                    sender=sender,
                    outbox_session_factory=outbox_session_factory,
                )
            raw_token, flow = decoy
            authority = session.get(OtpPurposeAuthority, flow.authority_id)
        else:
            if idempotency_key is None:
                raise
            if isinstance(
                winner, registration_service.NeutralizedRegistrationReplay
            ):
                return _finish_registration_replay(
                    session,
                    response,
                    background_tasks,
                    winner,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    now=now,
                    sender=sender,
                    outbox_session_factory=outbox_session_factory,
                )
            raw_token = otp_flow_service.deterministic_signup_token(
                idempotency_key
            )
            graph = otp_flow_service.resolve_flow(session, raw_token)
            if graph is None:
                raise RuntimeError("registration replay lost its OTP flow")
            authority, flow = graph
            result = winner

    _set_flow_cookie(response, raw_token)
    state = otp_flow_service.project(authority, flow, now=now)
    if not duplicate and result.delivery is not None:
        if idempotency_key is not None:
            background_tasks.add_task(
                finalize_registration_after_response,
                registration_service.registration_idempotency_key_hash(
                    idempotency_key
                ),
                provider,
                outbox_session_factory,
            )
        else:
            background_tasks.add_task(
                deliver_after_response,
                result.delivery.outbox_id,
                provider,
                outbox_session_factory,
            )
    return state


# --------------------------------------------------------------------------- #
# OTP verify / resend                                                         #
# --------------------------------------------------------------------------- #
class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        # Strict six-digit schema at the HTTP boundary. Malformed codes are
        # rejected as 422 WITHOUT consuming an OTP attempt (SAATHI-448 B1).
        if not _OTP_RE.fullmatch(v or ""):
            raise ValueError("OTP code must be exactly 6 digits.")
        return v


class EmptyOtpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post("/otp/verify")
def otp_verify(
    payload: OtpVerifyRequest,
    request: Request,
    response: Response,
    _: None = Depends(require_trusted_mutation_origin),
    session: Session = Depends(get_session),
) -> otp_flow_service.OtpFlowState:
    now = _now()
    _otp_projection_headers(response)
    raw_token = _flow_cookie_value(request)
    subject = _flow_subject_for_rate(session, raw_token)
    _rate_limit(
        session,
        request,
        subject_hash=subject,
        action="verify",
        purpose="signup",
        now=now,
    )
    graph = otp_flow_service.resolve_flow(session, raw_token)
    if graph is None:
        raise _flow_http_error(
            session,
            raw_token,
            status_code=401,
            code="otp_failed",
            now=now,
        )
    authority, flow = graph
    if flow.purpose != "signup" or flow.state not in {
        "pending",
        "code_sent",
        "locked",
    }:
        raise _flow_http_error(
            session,
            raw_token,
            status_code=401,
            code="otp_failed",
            now=now,
        )
    projected = otp_flow_service.project(authority, flow, now=now)
    if projected["expires_in_seconds"] == 0:
        # The verifier may expire before the cookie flow. Keep resend available
        # through the state endpoint, but verification itself has one uniform
        # failure for real/neutralized/expired candidates.
        raise _flow_http_error(
            session,
            raw_token,
            status_code=401,
            code="otp_failed",
            now=now,
        )
    if flow.registration_id is None or flow.challenge_id is None:
        try:
            otp_service.record_failed_attempt(session, authority, now=now)
        except otp_service.OtpError as exc:
            raise _otp_http_error(
                session, raw_token, exc, now=now
            ) from exc
        raise _flow_http_error(
            session,
            raw_token,
            status_code=401,
            code="incorrect_otp",
            now=now,
        )
    try:
        otp_service.verify(
            session,
            flow.registration_id,
            payload.code,
            now,
            purpose="signup",
            challenge_id=flow.challenge_id,
            commit_on_success=False,
        )
    except otp_service.OtpError as exc:
        if exc.code not in {"incorrect_otp", "locked"}:
            # Missing, undelivered, stale and expired real challenges consume
            # the same stable authority attempt as a decoy.  Their internal
            # lifecycle remains distinct, but the public failure and metadata
            # cannot disclose whether provider delivery ever succeeded.
            try:
                otp_service.record_failed_attempt(
                    session, authority, now=now
                )
            except otp_service.OtpError as uniform_exc:
                raise _otp_http_error(
                    session, raw_token, uniform_exc, now=now
                ) from exc
        raise _otp_http_error(session, raw_token, exc, now=now) from exc
    registration = session.get(StudentRegistration, flow.registration_id)
    if not otp_service.registration_is_authorizable(registration):
        session.rollback()
        raise _flow_http_error(
            session,
            raw_token,
            status_code=401,
            code="otp_failed",
            now=now,
        )
    state = otp_flow_service.mark_authenticated(flow, now=now)
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
    _clear_flow_cookie(response)
    return state


@router.post("/otp/resend", status_code=202)
def otp_resend(
    _: EmptyOtpRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    origin: None = Depends(require_trusted_mutation_origin),
    session: Session = Depends(get_session),
    sender: IdempotentOtpSender | None = Depends(get_otp_sender),
    outbox_session_factory: Callable[[], Session] = Depends(
        get_outbox_session_factory
    ),
) -> otp_flow_service.OtpFlowState:
    del origin
    now = _now()
    _otp_projection_headers(response)
    raw_token = _flow_cookie_value(request)
    provider = _require_sender(sender)
    subject = _flow_subject_for_rate(session, raw_token)
    _rate_limit(
        session,
        request,
        subject_hash=subject,
        action="resend",
        purpose=otp_flow_service.purpose_for_token(session, raw_token),
        now=now,
    )
    graph = otp_flow_service.resolve_flow(session, raw_token)
    if graph is None:
        raise _flow_http_error(
            session,
            raw_token,
            status_code=401,
            code="otp_flow_unavailable",
            now=now,
        )
    authority, flow = graph
    if (
        flow.state not in {"pending", "code_sent", "locked"}
        or flow.purpose not in {"signup", "login", "recovery"}
        or otp_authority.as_utc(flow.expires_at) <= now
    ):
        raise _flow_http_error(
            session,
            raw_token,
            status_code=401,
            code="otp_flow_unavailable",
            now=now,
        )
    intent = None
    try:
        if flow.registration_id is None:
            otp_service.resend_decoy(authority, now=now)
        else:
            registration = session.get(StudentRegistration, flow.registration_id)
            if not otp_service.registration_is_authorizable(registration):
                raise otp_service.OtpError(404, "no_active_challenge")
            candidate, intent = otp_service.resend(
                session,
                flow.registration_id,
                now,
                purpose=flow.purpose,
                destination=decrypt(registration.mobile_ct),
            )
            if flow.challenge_id is None:
                flow.challenge_id = candidate.id
    except otp_service.OtpError as exc:
        raise _otp_http_error(session, raw_token, exc, now=now) from exc
    session.commit()
    state = otp_flow_service.project(authority, flow, now=now)
    if intent is not None:
        if flow.purpose == "signup" and flow.registration_id is not None:
            background_tasks.add_task(
                deliver_resend_after_response,
                flow.registration_id,
                intent.outbox_id,
                provider,
                outbox_session_factory,
            )
        else:
            background_tasks.add_task(
                deliver_after_response,
                intent.outbox_id,
                provider,
                outbox_session_factory,
            )
    return state


@router.get("/otp/state")
def otp_state(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> otp_flow_service.OtpFlowState:
    _otp_projection_headers(response)
    return otp_flow_service.state_for_token(
        session, _flow_cookie_value(request), now=_now()
    )


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
        if not _MOBILE_RE.fullmatch(v or ""):
            raise ValueError("Mobile number must be exactly 10 digits.")
        return v


class RecoveryVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _OTP_RE.fullmatch(v or ""):
            raise ValueError("OTP code must be exactly 6 digits.")
        return v


class LoginStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mobile: str

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v: str) -> str:
        if not _MOBILE_RE.fullmatch(v or ""):
            raise ValueError("Mobile number must be exactly 10 digits.")
        return v


class LoginVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not _OTP_RE.fullmatch(v or ""):
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
        path="/api/v1",
        secure=_cookie_secure(),
        httponly=True,
        samesite="strict",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_session_cookie_name,
        path="/api/v1",
        secure=_cookie_secure(),
        httponly=True,
        samesite="strict",
    )


@router.post("/recovery/start", status_code=202)
def recovery_start(
    payload: RecoveryStartRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_trusted_mutation_origin),
    session: Session = Depends(get_session),
    sender: IdempotentOtpSender | None = Depends(get_otp_sender),
    outbox_session_factory: Callable[[], Session] = Depends(get_outbox_session_factory),
) -> otp_flow_service.OtpFlowState:
    now = _now()
    _otp_projection_headers(response)
    provider = _require_sender(sender)  # symmetric for known/unknown (both 503 if absent)
    subject = otp_authority.authority_subject_for_mobile(payload.mobile)
    _rate_limit(
        session,
        request,
        subject_hash=subject,
        action="issue",
        purpose="recovery",
        now=now,
    )
    try:
        raw_token, flow, intent = recovery_service.start_flow(
            session, payload.mobile, now
        )
    except otp_service.OtpError as exc:
        raise _otp_http_error(
            session, _flow_cookie_value(request), exc, now=now
        ) from exc
    authority = session.get(OtpPurposeAuthority, flow.authority_id)
    session.commit()
    _set_flow_cookie(response, raw_token)
    state = otp_flow_service.project(authority, flow, now=now)
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
    return state


@router.post("/recovery/verify")
def recovery_verify(
    payload: RecoveryVerifyRequest,
    request: Request,
    response: Response,
    _: None = Depends(require_trusted_mutation_origin),
    session: Session = Depends(get_session),
) -> otp_flow_service.OtpFlowState:
    now = _now()
    _otp_projection_headers(response)
    raw_token = _flow_cookie_value(request)
    subject = _flow_subject_for_rate(session, raw_token)
    _rate_limit(
        session,
        request,
        subject_hash=subject,
        action="verify",
        purpose="recovery",
        now=now,
    )
    try:
        recovery_service.verify_flow(
            session, raw_token, payload.code, now
        )
    except recovery_service.RecoveryError as exc:
        raise _flow_http_error(
            session,
            raw_token,
            status_code=exc.status_code,
            code=exc.code,
            now=now,
        ) from exc
    _set_flow_cookie(
        response,
        raw_token,  # type: ignore[arg-type]
        max_age=settings.otp_recovery_proof_ttl_seconds,
    )
    return otp_flow_service.verified_state()


@router.post("/recovery/complete")
def recovery_complete(
    _: EmptyOtpRequest,
    request: Request,
    response: Response,
    origin: None = Depends(require_trusted_mutation_origin),
    session: Session = Depends(get_session),
) -> otp_flow_service.OtpFlowState:
    del origin
    now = _now()
    _otp_projection_headers(response)
    raw_token = _flow_cookie_value(request)
    try:
        recovery_service.complete_flow(session, raw_token, now)
    except recovery_service.RecoveryError as exc:
        raise _flow_http_error(
            session,
            raw_token,
            status_code=exc.status_code,
            code=exc.code,
            now=now,
        ) from exc
    _clear_flow_cookie(response)
    return otp_flow_service.unavailable_state()


# --------------------------------------------------------------------------- #
# OTP login + server-side authenticated session                               #
# --------------------------------------------------------------------------- #
@router.post("/login/otp/start", status_code=202)
def login_otp_start(
    payload: LoginStartRequest,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    _: None = Depends(require_trusted_mutation_origin),
    session: Session = Depends(get_session),
    sender: IdempotentOtpSender | None = Depends(get_otp_sender),
    outbox_session_factory: Callable[[], Session] = Depends(get_outbox_session_factory),
) -> otp_flow_service.OtpFlowState:
    now = _now()
    _otp_projection_headers(response)
    provider = _require_sender(sender)
    subject = otp_authority.authority_subject_for_mobile(payload.mobile)
    _rate_limit(
        session,
        request,
        subject_hash=subject,
        action="issue",
        purpose="login",
        now=now,
    )
    try:
        raw_token, flow, intent = login_service.start_flow(
            session, payload.mobile, now
        )
    except otp_service.OtpError as exc:
        raise _otp_http_error(
            session, _flow_cookie_value(request), exc, now=now
        ) from exc
    authority = session.get(OtpPurposeAuthority, flow.authority_id)
    session.commit()
    _set_flow_cookie(response, raw_token)
    state = otp_flow_service.project(authority, flow, now=now)
    if intent is not None:
        background_tasks.add_task(
            deliver_after_response,
            intent.outbox_id,
            provider,
            outbox_session_factory,
        )
    # Same 202 + shape for a known, unknown, suspended or cooldown account.
    return state


@router.post("/login/otp/verify")
def login_otp_verify(
    payload: LoginVerifyRequest,
    request: Request,
    response: Response,
    _: None = Depends(require_trusted_mutation_origin),
    session: Session = Depends(get_session),
) -> otp_flow_service.OtpFlowState:
    now = _now()
    _otp_projection_headers(response)
    raw_flow_token = _flow_cookie_value(request)
    subject = _flow_subject_for_rate(session, raw_flow_token)
    _rate_limit(
        session,
        request,
        subject_hash=subject,
        action="verify",
        purpose="login",
        now=now,
    )
    try:
        raw_session_token, _, _ = login_service.verify_flow(
            session, raw_flow_token, payload.code, now
        )
    except login_service.LoginError as exc:
        raise _flow_http_error(
            session,
            raw_flow_token,
            status_code=exc.status_code,
            code=exc.code,
            now=now,
        ) from exc
    _set_session_cookie(response, raw_session_token)
    _clear_flow_cookie(response)
    return otp_flow_service.authenticated_state("login")


@router.get("/session")
def student_session(
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    _otp_projection_headers(response)
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
