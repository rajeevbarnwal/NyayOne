"""SAATHI-58 — student profile, settings and DPDP privacy API (frozen contract).

Reuses ActorContext (no second identity system), the registration tables for
profile data, config-driven retention, the shared audit table, and the
recovery-session verifier as REAL server-authoritative reauthentication
evidence for deletion. Opaque request ids only; cross-user lookups 404
uniformly; no PII/echo in errors, logs or audit snapshots.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import (
    ActorContext,
    Role,
    get_actor_context,
    require_trusted_cookie_origin,
)
from app.core.auth_cookies import clear_auth_session_cookie, clear_otp_flow_cookie
from app.core.config import settings
from app.core.crypto import keyed_hash
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import StudentRegistration
from app.schemas.student_profile import (
    AcademicProfileMutation,
    InterestsProfileMutation,
    PersonalProfileMutation,
    PromptDismissRequest,
    StudentProfileProjectionResponse,
)
from app.services import (
    login_service,
    mentor_ceremony,
    otp_flow_service,
    registration_service,
)
from app.services import profile_service
from app.models.wave1 import (
    PRIVACY_KINDS, THEMES,
    DataSubjectRequest, DeletionJob, ExportJob, PrivacyPreference, UserSettings,
)

router = APIRouter(prefix="/student", tags=["student"])

# --- Canonical wire values (SAATHI-58 D1/D2). Labels live in the UI only. ---
LANGUAGES = ("en", "hi")


def _require_student(actor: ActorContext = Depends(get_actor_context)) -> ActorContext:
    if not actor.is_authenticated:
        raise HTTPException(status_code=401, detail={"code": "authentication_required"})
    if not actor.has_role(Role.STUDENT):
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    return actor


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _registration_for(session: Session, actor: ActorContext) -> StudentRegistration:
    reg = session.scalar(
        select(StudentRegistration).where(
            StudentRegistration.user_id == actor.user_id,
            StudentRegistration.deleted_at.is_(None),
        )
    )
    if reg is None:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
    return reg


def _audit(session: Session, actor: ActorContext, action: str, resource: str, rid, state: dict) -> None:
    session.add(AuditEvent(actor_user_id=actor.user_id, actor_role="student", action=action,
                           resource_type=resource, resource_id=rid, after_state=state))


# ------------------------------- profile ---------------------------------------
_PROFILE_PROJECTION_HEADERS = {
    "Cache-Control": "private, no-store",
    "Vary": "Cookie",
}


def _mark_profile_projection_private(response: Response) -> None:
    for name, value in _PROFILE_PROJECTION_HEADERS.items():
        response.headers[name] = value


def _raise_profile_error(error: profile_service.ProfileBoundaryError) -> None:
    detail: dict[str, object] = {"code": error.code}
    if error.field is not None:
        detail["field"] = error.field
    if isinstance(error, profile_service.ProfileVersionConflict):
        detail.update(
            {
                "current_profile_version": error.projection["profile_version"],
                "current_projection": error.projection,
            }
        )
    if isinstance(error, profile_service.ProfileIdempotencyConflict):
        detail["section"] = error.section
    raise HTTPException(
        status_code=error.status_code,
        detail=detail,
        headers=dict(_PROFILE_PROJECTION_HEADERS),
    ) from error


def _raw_session_token(request: Request) -> str | None:
    return request.cookies.get(settings.auth_session_cookie_name)


def _require_empty_profile_query(request: Request) -> None:
    if request.query_params:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_error", "field": "query"},
        )


def _profile_idempotency_key(request: Request) -> str:
    """Preserve one raw value; an invalid sentinel remains fail-closed.

    Validation occurs inside the service only after canonical session authority
    is re-proven.  This preserves the NYAY-5 rule that a revoked cookie returns
    the authoritative session denial before any request-shape observation.
    Missing and duplicate headers become the empty invalid sentinel and are
    still rejected as ``invalid_idempotency_key`` before any profile write.
    """

    values = request.headers.getlist("Idempotency-Key")
    return values[0] if len(values) == 1 else ""


def _mark_profile_replay(response: Response, projection: dict) -> None:
    response.headers["Idempotency-Replayed"] = (
        "true" if getattr(projection, "replayed", False) else "false"
    )


@router.get("/profile", response_model=StudentProfileProjectionResponse)
def get_profile(
    request: Request,
    response: Response,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> dict:
    _mark_profile_projection_private(response)
    _require_empty_profile_query(request)
    try:
        return profile_service.projection_for_actor(
            session,
            actor.user_id,
            now=_now(),
            raw_session_token=_raw_session_token(request),
        )
    except profile_service.ProfileBoundaryError as error:
        _raise_profile_error(error)


@router.patch("/profile/personal", response_model=StudentProfileProjectionResponse)
def patch_personal_profile(
    payload: PersonalProfileMutation,
    request: Request,
    response: Response,
    actor: ActorContext = Depends(_require_student),
    _: None = Depends(require_trusted_cookie_origin),
    session: Session = Depends(get_session),
) -> dict:
    _mark_profile_projection_private(response)
    _require_empty_profile_query(request)
    try:
        projection = profile_service.update_personal(
            session,
            actor.user_id,
            **payload.model_dump(),
            now=_now(),
            raw_session_token=_raw_session_token(request),
            idempotency_key=_profile_idempotency_key(request),
        )
        _mark_profile_replay(response, projection)
        return projection
    except profile_service.ProfileBoundaryError as error:
        session.rollback()
        _raise_profile_error(error)


@router.patch("/profile/academic", response_model=StudentProfileProjectionResponse)
def patch_academic_profile(
    payload: AcademicProfileMutation,
    request: Request,
    response: Response,
    actor: ActorContext = Depends(_require_student),
    _: None = Depends(require_trusted_cookie_origin),
    session: Session = Depends(get_session),
) -> dict:
    _mark_profile_projection_private(response)
    _require_empty_profile_query(request)
    try:
        projection = profile_service.update_academic(
            session,
            actor.user_id,
            **payload.model_dump(),
            now=_now(),
            raw_session_token=_raw_session_token(request),
            idempotency_key=_profile_idempotency_key(request),
        )
        _mark_profile_replay(response, projection)
        return projection
    except profile_service.ProfileBoundaryError as error:
        session.rollback()
        _raise_profile_error(error)


@router.patch("/profile/interests", response_model=StudentProfileProjectionResponse)
def patch_interests_profile(
    payload: InterestsProfileMutation,
    request: Request,
    response: Response,
    actor: ActorContext = Depends(_require_student),
    _: None = Depends(require_trusted_cookie_origin),
    session: Session = Depends(get_session),
) -> dict:
    _mark_profile_projection_private(response)
    _require_empty_profile_query(request)
    try:
        projection = profile_service.update_interests(
            session,
            actor.user_id,
            **payload.model_dump(),
            now=_now(),
            raw_session_token=_raw_session_token(request),
            idempotency_key=_profile_idempotency_key(request),
        )
        _mark_profile_replay(response, projection)
        return projection
    except profile_service.ProfileBoundaryError as error:
        session.rollback()
        _raise_profile_error(error)


@router.post("/profile/prompt-dismiss")
def dismiss_profile_prompt(
    payload: PromptDismissRequest,
    request: Request,
    response: Response,
    actor: ActorContext = Depends(_require_student),
    _: None = Depends(require_trusted_cookie_origin),
    session: Session = Depends(get_session),
) -> dict:
    del payload
    _mark_profile_projection_private(response)
    _require_empty_profile_query(request)
    try:
        return profile_service.dismiss_prompt(
            session,
            actor.user_id,
            now=_now(),
            raw_session_token=_raw_session_token(request),
        )
    except profile_service.ProfileBoundaryError as error:
        session.rollback()
        _raise_profile_error(error)


# ------------------------------- settings --------------------------------------
class PrivacyPrefIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    enabled: bool

    @field_validator("kind")
    @classmethod
    def _kind(cls, v: str) -> str:
        if v not in PRIVACY_KINDS:
            raise ValueError(f"kind must be one of {PRIVACY_KINDS}")
        return v


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    theme: str | None = None
    language: str | None = None
    notif_email: bool | None = None
    notif_sms: bool | None = None
    notif_updates: bool | None = None
    privacy: list[PrivacyPrefIn] | None = None
    expected_version: int

    @field_validator("theme")
    @classmethod
    def _theme(cls, v: str | None) -> str | None:
        if v is not None and v not in THEMES:
            raise ValueError(f"theme must be one of {THEMES}")
        return v

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if v not in LANGUAGES:
            raise ValueError(f"language must be one of {LANGUAGES}")
        return v


def _settings_row(session: Session, actor: ActorContext) -> UserSettings:
    row = session.scalar(select(UserSettings).where(UserSettings.user_id == actor.user_id))
    if row is None:
        row = UserSettings(user_id=actor.user_id)
        session.add(row)
        session.flush()
    return row


def _settings_payload(session: Session, row: UserSettings, actor: ActorContext) -> dict:
    stored = {
        p.kind: p.enabled
        for p in session.scalars(
            select(PrivacyPreference).where(PrivacyPreference.user_id == actor.user_id)
        )
    }
    return {
        "theme": row.theme, "language": row.language,
        "notif_email": row.notif_email, "notif_sms": row.notif_sms, "notif_updates": row.notif_updates,
        "version": row.version,
        # D3: ALWAYS synthesize the complete canonical set (safe defaults false);
        # PATCH upserts rows (unique (user_id, kind) enforced by the schema).
        "privacy": [{"kind": k, "enabled": stored.get(k, False)} for k in PRIVACY_KINDS],
    }


@router.get("/settings")
def get_settings(actor: ActorContext = Depends(_require_student), session: Session = Depends(get_session)) -> dict:
    row = _settings_row(session, actor)
    payload = _settings_payload(session, row, actor)
    session.commit()  # persist lazily-created defaults
    return payload


@router.patch("/settings")
def patch_settings(payload: SettingsPatch, actor: ActorContext = Depends(_require_student),
                   session: Session = Depends(get_session)) -> dict:
    row = _settings_row(session, actor)
    if payload.expected_version != row.version:
        # Optimistic concurrency: stale client must refetch (no partial write).
        raise HTTPException(status_code=409, detail={"code": "settings_version_conflict", "current_version": row.version})
    for f in ("theme", "language", "notif_email", "notif_sms", "notif_updates"):
        v = getattr(payload, f)
        if v is not None:
            setattr(row, f, v)
    if payload.privacy:
        for pref in payload.privacy:
            existing = session.scalar(select(PrivacyPreference).where(
                PrivacyPreference.user_id == actor.user_id, PrivacyPreference.kind == pref.kind))
            if existing is None:
                session.add(PrivacyPreference(user_id=actor.user_id, kind=pref.kind, enabled=pref.enabled))
            else:
                existing.enabled = pref.enabled
    row.version += 1
    _audit(session, actor, "student.settings.update", "user_settings", row.id, {"version": row.version})
    session.commit()
    return _settings_payload(session, row, actor)


# ------------------------------- privacy / DPDP --------------------------------
class DeleteRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation: str


def _create_dsr(session: Session, actor: ActorContext, kind: str, idem: str | None) -> DataSubjectRequest:
    if idem:
        existing = session.scalar(select(DataSubjectRequest).where(DataSubjectRequest.idempotency_key == idem))
        if existing is not None:
            if existing.user_id != actor.user_id:
                raise HTTPException(status_code=404, detail={"code": "request_not_found"})
            return existing
    dsr = DataSubjectRequest(user_id=actor.user_id, kind=kind, opaque_id=uuid.uuid4().hex,
                             status="pending", idempotency_key=idem)
    session.add(dsr)
    session.flush()
    return dsr


@router.post("/privacy/export", status_code=202)
def privacy_export(actor: ActorContext = Depends(_require_student), session: Session = Depends(get_session),
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    dsr = _create_dsr(session, actor, "export", idempotency_key)
    if session.scalar(select(ExportJob).where(ExportJob.request_id == dsr.id)) is None:
        session.add(ExportJob(request_id=dsr.id, status="pending"))
        _audit(session, actor, "student.privacy.export_requested", "data_subject_request", dsr.id,
               {"status": dsr.status})
    session.commit()  # request + job + audit are one transaction
    return {"request_id": dsr.opaque_id, "status": dsr.status}


@router.post("/privacy/delete", status_code=202)
def privacy_delete(payload: DeleteRequestIn, request: Request, response: Response,
                   actor: ActorContext = Depends(_require_student),
                   _: None = Depends(require_trusted_cookie_origin),
                   session: Session = Depends(get_session),
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    if payload.confirmation != "DELETE":
        raise HTTPException(status_code=422, detail={"code": "invalid_confirmation", "field": "confirmation"})
    # REAL server-authoritative reauthentication: the browser supplies only its
    # HttpOnly OTP-flow cookie. The server proves that the short-lived verified
    # recovery flow belongs to this authenticated registration and consumes it
    # in the same transaction as the deletion request.
    discovered = _registration_for(session, actor)
    try:
        mentor_boundary = mentor_ceremony.lock_subject_mentor_erasure_boundary(
            session, discovered.id
        )
    except mentor_ceremony.MentorCeremonyError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "concurrent_state_changed"}
        ) from None
    reg, _ = registration_service.lock_registration_with_idempotency(
        session, discovered.id
    )
    if reg is None:
        raise HTTPException(status_code=404, detail={"code": "profile_not_found"})
    now = _now()
    try:
        mentor_graph_within_cap = (
            mentor_ceremony.preflight_subject_mentor_authority_for_privacy_request(
                session,
                mentor_boundary,
                reg,
                now=now,
            )
        )
    except mentor_ceremony.MentorCeremonyError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "concurrent_state_changed"}
        ) from None
    if not mentor_graph_within_cap:
        # Commit only the digest-bound NYAY-19 blocked-graph alert.  The
        # one-shot recovery proof and every authority/subject row are intact.
        session.commit()
        raise HTTPException(
            status_code=409, detail={"code": "concurrent_state_changed"}
        )
    try:
        otp_flow_service.consume_recovery_proof(
            session,
            request.cookies.get(settings.otp_flow_cookie_name),
            registration_id=reg.id,
            now=now,
        )
    except ValueError:
        raise HTTPException(status_code=401, detail={"code": "reauth_required"})
    try:
        retired_mentor_graphs = (
            mentor_ceremony.retire_subject_mentor_authority_for_privacy_request(
                session,
                mentor_boundary,
                now=now,
            )
        )
    except mentor_ceremony.MentorCeremonyError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "concurrent_state_changed"}
        ) from None
    if retired_mentor_graphs < 0:
        # Persist only the digest-bound NYAY-19 blocked-graph alert.  No DSR,
        # account, registration or mentor-graph state is changed in this path.
        session.commit()
        raise HTTPException(
            status_code=409, detail={"code": "concurrent_state_changed"}
        )
    dsr = _create_dsr(session, actor, "delete", idempotency_key)
    created_job = (
        session.scalar(
            select(DeletionJob).where(DeletionJob.request_id == dsr.id)
        )
        is None
    )
    if created_job:
        dsr.reauth_verified = True
        dsr.confirmation_hash = keyed_hash(payload.confirmation)
        session.add(
            DeletionJob(
                request_id=dsr.id,
                status="pending",
                mode=settings.retention_mode,
            )
        )
    revoked = login_service.suspend_user_and_revoke_sessions(
        session, reg.user_id, now
    )
    reg.status = "suspended"
    if created_job:
        _audit(session, actor, "student.privacy.delete_requested", "data_subject_request", dsr.id,
               {
                   "status": dsr.status,
                   "reauth_verified": True,
                   "account_frozen": True,
                   "sessions_revoked": revoked,
               })
    elif revoked:
        _audit(
            session,
            actor,
            "student.privacy.delete_frozen",
            "data_subject_request",
            dsr.id,
            {"account_frozen": True, "sessions_revoked": revoked},
        )
    session.commit()
    clear_auth_session_cookie(response)
    clear_otp_flow_cookie(response)
    return {"request_id": dsr.opaque_id, "status": dsr.status}


@router.get("/privacy/requests/{request_id}")
def privacy_request_status(request_id: str, actor: ActorContext = Depends(_require_student),
                           session: Session = Depends(get_session)) -> dict:
    dsr = session.scalar(select(DataSubjectRequest).where(
        DataSubjectRequest.opaque_id == request_id,
        DataSubjectRequest.user_id == actor.user_id,  # cross-user lookup: uniform 404
    ))
    if dsr is None:
        raise HTTPException(status_code=404, detail={"code": "request_not_found"})
    return {"request_id": dsr.opaque_id, "kind": dsr.kind, "status": dsr.status,
            "created_at": dsr.created_at.isoformat() if dsr.created_at else None}
