"""SAATHI-60 internship discovery, detail, and owner-scoped saves API."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, Role, get_actor_context
from app.db.session import get_session
from app.schemas.internships import (
    InternshipListingListOut,
    InternshipListingOut,
    SavedInternshipListOut,
    SavedInternshipStateOut,
)
from app.services import internship_service

router = APIRouter(prefix="/internships", tags=["internships"])
student = APIRouter(prefix="/student/internships", tags=["internships"])
ListingSlug = Annotated[
    str,
    Path(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="Stable lower-case internship listing slug",
    ),
]


def _require_student(actor: ActorContext = Depends(get_actor_context)) -> ActorContext:
    if not actor.is_authenticated:
        raise HTTPException(
            status_code=401, detail={"code": "authentication_required"}
        )
    if not actor.has_role(Role.STUDENT):
        raise HTTPException(status_code=403, detail={"code": "forbidden"})
    return actor


def _listing_or_404(session: Session, slug: str):
    listing = internship_service.listing_or_none(session, slug)
    if listing is None:
        raise HTTPException(
            status_code=404, detail={"code": "internship_listing_not_found"}
        )
    return listing


@router.get("", response_model=InternshipListingListOut)
def list_internships(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    verified_only: bool = Query(default=False),
    session: Session = Depends(get_session),
) -> InternshipListingListOut:
    rows, total = internship_service.list_catalogue(
        session, page=page, page_size=page_size, verified_only=verified_only
    )
    return InternshipListingListOut(
        items=[internship_service.listing_out(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{listing_id}", response_model=InternshipListingOut)
def get_internship(
    listing_id: ListingSlug, session: Session = Depends(get_session)
) -> InternshipListingOut:
    return internship_service.listing_out(_listing_or_404(session, listing_id))


@student.get("/saved", response_model=SavedInternshipListOut)
def get_saved_internships(
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> SavedInternshipListOut:
    assert actor.user_id is not None
    return SavedInternshipListOut(
        items=[
            internship_service.listing_out(row)
            for row in internship_service.list_saved(session, actor.user_id)
        ]
    )


@student.put("/{listing_id}/saved", response_model=SavedInternshipStateOut)
def save_internship(
    listing_id: ListingSlug,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> SavedInternshipStateOut:
    assert actor.user_id is not None
    listing = _listing_or_404(session, listing_id)
    try:
        internship_service.save_listing(session, user_id=actor.user_id, listing=listing)
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=401, detail={"code": str(exc)}) from exc
    return SavedInternshipStateOut(saved=True, listing_id=listing.slug)


@student.delete("/{listing_id}/saved", response_model=SavedInternshipStateOut)
def unsave_internship(
    listing_id: ListingSlug,
    actor: ActorContext = Depends(_require_student),
    session: Session = Depends(get_session),
) -> SavedInternshipStateOut:
    assert actor.user_id is not None
    listing = _listing_or_404(session, listing_id)
    try:
        internship_service.unsave_listing(
            session, user_id=actor.user_id, listing=listing
        )
    except LookupError as exc:
        session.rollback()
        raise HTTPException(status_code=401, detail={"code": str(exc)}) from exc
    return SavedInternshipStateOut(saved=False, listing_id=listing.slug)
