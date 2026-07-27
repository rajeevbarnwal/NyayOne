"""SAATHI-63 — law-school search/detail/compare/save/follow API (frozen contract)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import asc, func, select
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, Role, get_actor_context
from app.core.config import settings
from app.db.models.audit import AuditEvent
from app.db.session import get_session
from app.models.wave1 import (
    INSTITUTION_TYPES,
    LawSchool, LawSchoolFact, LawSchoolFollow, LawSchoolProgramme, LawSchoolSource, SavedLawSchool,
)
from app.services.law_school_service import CompareError, create_comparison

router = APIRouter(tags=["law-schools"])
_SORTS = {"name": LawSchool.name, "fees": LawSchool.fees_min, "nirf_rank": LawSchool.nirf_rank}


def _require_student(actor: ActorContext = Depends(get_actor_context)) -> ActorContext:
    if not actor.is_authenticated:
        raise HTTPException(status_code=401, detail={"code": "authentication_required"})
    if not actor.has_role(Role.STUDENT):
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    return actor


def _summary(s: LawSchool) -> dict:
    return {"id": str(s.id), "name": s.name, "slug": s.slug, "state": s.state,
            "institution_type": s.institution_type, "accreditation": s.accreditation,
            "entrance_exam": s.entrance_exam, "fees_min": s.fees_min, "fees_max": s.fees_max,
            "nirf_rank": s.nirf_rank}


def _detail(session: Session, s: LawSchool, actor: ActorContext) -> dict:
    progs = session.scalars(select(LawSchoolProgramme).where(LawSchoolProgramme.school_id == s.id)).all()
    facts = session.execute(
        select(LawSchoolFact, LawSchoolSource)
        .join(LawSchoolSource, LawSchoolFact.source_id == LawSchoolSource.id, isouter=True)
        .where(LawSchoolFact.school_id == s.id)
    ).all()
    saved = followed = False
    if actor.is_authenticated:
        saved = session.scalar(select(SavedLawSchool).where(
            SavedLawSchool.user_id == actor.user_id, SavedLawSchool.school_id == s.id)) is not None
        followed = session.scalar(select(LawSchoolFollow).where(
            LawSchoolFollow.user_id == actor.user_id, LawSchoolFollow.school_id == s.id)) is not None
    return {**_summary(s),
            "programmes": [{"degree": p.degree, "duration_years": p.duration_years} for p in progs],
            "facts": [{"key": f.key, "value": f.value,
                       "source_name": src.name if src else None,
                       "source_url": src.url if src else None,
                       "retrieved_at": src.retrieved_at.isoformat() if src else None} for f, src in facts],
            "saved": saved, "followed": followed}


@router.get("/law-schools")
def list_schools(
    q: str | None = None, state: str | None = None, institution_type: str | None = None,
    degree: str | None = None, accreditation: str | None = None, entrance_exam: str | None = None,
    fees_max: int | None = Query(default=None, ge=0), sort: str = "name",
    page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=50),
    session: Session = Depends(get_session),
) -> dict:
    if sort not in _SORTS:
        raise HTTPException(status_code=422, detail={"code": "unsupported_sort", "allowed": sorted(_SORTS)})
    if institution_type is not None and institution_type not in INSTITUTION_TYPES:
        raise HTTPException(status_code=422, detail={"code": "unsupported_institution_type", "allowed": list(INSTITUTION_TYPES)})
    stmt = select(LawSchool).where(LawSchool.deleted_at.is_(None))
    if q and q.strip():
        stmt = stmt.where(LawSchool.name.ilike(f"%{q.strip()}%"))
    if state:
        stmt = stmt.where(LawSchool.state == state)
    if institution_type:
        stmt = stmt.where(LawSchool.institution_type == institution_type)
    if accreditation:
        stmt = stmt.where(LawSchool.accreditation == accreditation)
    if entrance_exam:
        stmt = stmt.where(LawSchool.entrance_exam == entrance_exam)
    if fees_max is not None:
        stmt = stmt.where(LawSchool.fees_min <= fees_max)
    if degree:
        stmt = stmt.where(LawSchool.id.in_(
            select(LawSchoolProgramme.school_id).where(LawSchoolProgramme.degree.ilike(f"%{degree}%"))))
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.order_by(asc(_SORTS[sort])).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_summary(s) for s in rows], "total": total, "page": page,
            "page_size": page_size, "compare_max": settings.compare_max_schools}


@router.get("/law-schools/{school_id}")
def get_school(school_id: uuid.UUID, session: Session = Depends(get_session),
               actor: ActorContext = Depends(get_actor_context)) -> dict:
    s = session.get(LawSchool, school_id)
    if s is None or s.deleted_at is not None:
        raise HTTPException(status_code=404, detail={"code": "school_not_found"})
    return _detail(session, s, actor)


class CompareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    school_ids: list[uuid.UUID]


@router.post("/law-schools/compare")
def compare(payload: CompareIn, session: Session = Depends(get_session),
            actor: ActorContext = Depends(get_actor_context)) -> dict:
    try:
        cs = create_comparison(session, payload.school_ids, actor.user_id)
    except CompareError as exc:
        session.rollback()  # no partial mutation
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, **exc.extra}) from exc
    session.commit()
    schools = [session.get(LawSchool, sid) for sid in payload.school_ids]
    return {"comparison_id": str(cs.id), "compare_max": settings.compare_max_schools,
            "items": [_detail(session, s, actor) for s in schools]}


# ------------------- user-scoped saved / follow (idempotent) --------------------
student = APIRouter(prefix="/student/law-schools", tags=["law-schools"])


def _school_or_404(session: Session, school_id: uuid.UUID) -> LawSchool:
    s = session.get(LawSchool, school_id)
    if s is None or s.deleted_at is not None:
        raise HTTPException(status_code=404, detail={"code": "school_not_found"})
    return s


@student.get("/saved")
def list_saved(actor: ActorContext = Depends(_require_student), session: Session = Depends(get_session)) -> dict:
    rows = session.execute(
        select(LawSchool).join(SavedLawSchool, SavedLawSchool.school_id == LawSchool.id)
        .where(SavedLawSchool.user_id == actor.user_id)
    ).scalars().all()
    return {"items": [_summary(s) for s in rows]}


@student.get("/followed")
def list_followed(actor: ActorContext = Depends(_require_student), session: Session = Depends(get_session)) -> dict:
    rows = session.execute(
        select(LawSchool, LawSchoolFollow).join(LawSchoolFollow, LawSchoolFollow.school_id == LawSchool.id)
        .where(LawSchoolFollow.user_id == actor.user_id)
    ).all()
    return {"items": [{**_summary(s), "notify_opt_in": f.notify_opt_in} for s, f in rows]}


@student.put("/{school_id}/saved")
def save_school(school_id: uuid.UUID, actor: ActorContext = Depends(_require_student),
                session: Session = Depends(get_session)) -> dict:
    _school_or_404(session, school_id)
    if session.scalar(select(SavedLawSchool).where(
            SavedLawSchool.user_id == actor.user_id, SavedLawSchool.school_id == school_id)) is None:
        session.add(SavedLawSchool(user_id=actor.user_id, school_id=school_id))
        session.add(AuditEvent(actor_user_id=actor.user_id, actor_role="student", action="law_school.saved",
                               resource_type="law_school", resource_id=school_id, after_state={"saved": True}))
    session.commit()  # idempotent: replay is a no-op, single row
    return {"saved": True}


@student.delete("/{school_id}/saved")
def unsave_school(school_id: uuid.UUID, actor: ActorContext = Depends(_require_student),
                  session: Session = Depends(get_session)) -> dict:
    row = session.scalar(select(SavedLawSchool).where(
        SavedLawSchool.user_id == actor.user_id, SavedLawSchool.school_id == school_id))
    if row is not None:
        session.delete(row)
    session.commit()
    return {"saved": False}


class FollowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notify_opt_in: bool = False


@student.put("/{school_id}/follow")
def follow_school(school_id: uuid.UUID, payload: FollowIn | None = None,
                  actor: ActorContext = Depends(_require_student),
                  session: Session = Depends(get_session)) -> dict:
    _school_or_404(session, school_id)
    opt_in = payload.notify_opt_in if payload else False
    row = session.scalar(select(LawSchoolFollow).where(
        LawSchoolFollow.user_id == actor.user_id, LawSchoolFollow.school_id == school_id))
    if row is None:
        row = LawSchoolFollow(user_id=actor.user_id, school_id=school_id, notify_opt_in=opt_in)
        session.add(row)
        session.add(AuditEvent(actor_user_id=actor.user_id, actor_role="student", action="law_school.followed",
                               resource_type="law_school", resource_id=school_id,
                               after_state={"followed": True, "notify_opt_in": opt_in}))
    else:
        row.notify_opt_in = opt_in
    session.commit()
    return {"followed": True, "notify_opt_in": row.notify_opt_in}


@student.delete("/{school_id}/follow")
def unfollow_school(school_id: uuid.UUID, actor: ActorContext = Depends(_require_student),
                    session: Session = Depends(get_session)) -> dict:
    row = session.scalar(select(LawSchoolFollow).where(
        LawSchoolFollow.user_id == actor.user_id, LawSchoolFollow.school_id == school_id))
    if row is not None:
        session.delete(row)
    session.commit()
    return {"followed": False, "notify_opt_in": False}
