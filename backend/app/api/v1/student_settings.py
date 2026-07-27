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

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, Role, get_actor_context
from app.core.crypto import decrypt, keyed_hash
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.registration import RecoverySession, StudentProfile, StudentRegistration
from app.models.wave1 import (
    PRIVACY_KINDS, THEMES,
    DataSubjectRequest, DeletionJob, ExportJob, PrivacyPreference, UserSettings,
)

router = APIRouter(prefix="/student", tags=["student"])

# --- Canonical wire values (SAATHI-58 D1/D2). Labels live in the UI only. ---
LANGUAGES = ("en", "hi")
CANONICAL_COLLEGES = (
    "National Law School of India University",
    "NALSAR University of Law",
    "The West Bengal National University of Juridical Sciences",
    "Other",
)
CANONICAL_YEARS = ("1st", "2nd", "3rd", "4th", "5th", "llm")
_LEGACY_COLLEGE = {
    "NLSIU": "National Law School of India University",
    "National Law School of India University (NLSIU)": "National Law School of India University",
    "NALSAR": "NALSAR University of Law",
    "The West Bengal NUJS": "The West Bengal National University of Juridical Sciences",
    "WBNUJS": "The West Bengal National University of Juridical Sciences",
}
_LEGACY_YEAR = {
    "1st year": "1st", "2nd year": "2nd", "3rd year": "3rd",
    "4th year \u00b7 B.A. LL.B. (Hons.)": "4th", "4th year": "4th", "5th year": "5th",
    "LL.M.": "llm", "LLM": "llm",
}


def canonical_college(v):
    if v is None:
        return None
    return v if v in CANONICAL_COLLEGES else _LEGACY_COLLEGE.get(v, v)


def canonical_year(v):
    if v is None:
        return None
    return v if v in CANONICAL_YEARS else _LEGACY_YEAR.get(v, v)


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
class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    college: str | None = None
    year_of_study: str | None = None

    @field_validator("college")
    @classmethod
    def _college(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = canonical_college(v.strip())
        if not v:
            raise ValueError("must not be empty or whitespace")
        if v not in CANONICAL_COLLEGES:
            raise ValueError(f"college must be one of {CANONICAL_COLLEGES}")
        return v

    @field_validator("year_of_study")
    @classmethod
    def _year(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = canonical_year(v.strip())
        if not v:
            raise ValueError("must not be empty or whitespace")
        if v not in CANONICAL_YEARS:
            raise ValueError(f"year_of_study must be one of {CANONICAL_YEARS}")
        return v


def _profile_payload(session: Session, reg: StudentRegistration) -> dict:
    prof = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == reg.id))
    mobile = decrypt(reg.mobile_ct)
    return {
        "first_name": reg.first_name, "middle_name": reg.middle_name, "last_name": reg.last_name,
        "college": canonical_college(prof.college) if prof else None,
        "year_of_study": canonical_year(prof.year_of_study) if prof else None,
        "masked_mobile": f"******{mobile[-4:]}",
    }


@router.get("/profile")
def get_profile(actor: ActorContext = Depends(_require_student), session: Session = Depends(get_session)) -> dict:
    return _profile_payload(session, _registration_for(session, actor))


@router.patch("/profile")
def patch_profile(payload: ProfilePatch, actor: ActorContext = Depends(_require_student),
                  session: Session = Depends(get_session)) -> dict:
    reg = _registration_for(session, actor)
    prof = session.scalar(select(StudentProfile).where(StudentProfile.registration_id == reg.id))
    if prof is None:
        prof = StudentProfile(registration_id=reg.id)
        session.add(prof)
    if payload.college is not None:
        prof.college = payload.college
        reg.institution_ref = payload.college
    if payload.year_of_study is not None:
        prof.year_of_study = payload.year_of_study
    _audit(session, actor, "student.profile.update", "student_profile", reg.id,
           {"fields": [k for k, v in payload.model_dump().items() if v is not None]})
    session.commit()
    return _profile_payload(session, reg)


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
    reauth_recovery_id: str


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
def privacy_delete(payload: DeleteRequestIn, actor: ActorContext = Depends(_require_student),
                   session: Session = Depends(get_session),
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict:
    if payload.confirmation != "DELETE":
        raise HTTPException(status_code=422, detail={"code": "invalid_confirmation", "field": "confirmation"})
    # REAL server-authoritative reauthentication: a verified, unconsumed recovery
    # session owned by this user's registration (issued via OTP re-verification).
    reg = _registration_for(session, actor)
    rs = session.scalar(select(RecoverySession).where(
        RecoverySession.opaque_id == payload.reauth_recovery_id,
        RecoverySession.registration_id == reg.id,
        RecoverySession.status == "verified",
    ))
    if rs is None:
        raise HTTPException(status_code=401, detail={"code": "reauth_required"})
    rs.status = "consumed"
    rs.consumed_at = _now()
    dsr = _create_dsr(session, actor, "delete", idempotency_key)
    if session.scalar(select(DeletionJob).where(DeletionJob.request_id == dsr.id)) is None:
        dsr.reauth_verified = True
        dsr.confirmation_hash = keyed_hash(payload.confirmation)
        session.add(DeletionJob(request_id=dsr.id, status="pending", mode="anonymise"))
        _audit(session, actor, "student.privacy.delete_requested", "data_subject_request", dsr.id,
               {"status": dsr.status, "reauth_verified": True})
    session.commit()
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
