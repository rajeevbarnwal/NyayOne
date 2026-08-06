"""Production-owned internship catalogue projection and saved-list service."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.internships import InternshipListing, SavedInternship
from app.models.registration import User
from app.schemas.internships import InternshipListingOut, InternshipSourceOut
from app.services.audit_service import record_audit_event
from app.services.organisation_identity import public_organisation_id

CATALOGUE_IDS = {
    "cam": uuid.UUID("60000000-0000-4000-8000-000000000001"),
    "menon": uuid.UUID("60000000-0000-4000-8000-000000000002"),
    "vidhi": uuid.UUID("60000000-0000-4000-8000-000000000003"),
}

# This fixture is a product-owned deterministic catalogue, not a browser mock.
# The migration duplicates these immutable values so every migrated runtime has
# the same starting truth without importing live application code into Alembic.
CATALOGUE_SEED: tuple[dict, ...] = (
    {
        "id": CATALOGUE_IDS["cam"],
        "slug": "cam",
        "role": "Summer Associate, disputes",
        "organisation": "Cyril Amarchand Mangaldas",
        "organisation_public_id": public_organisation_id("Cyril Amarchand Mangaldas"),
        "location": "Mumbai",
        "stipend_monthly_paise": 4_000_000,
        "verification_status": "verified",
        "application_deadline": date(2027, 7, 9),
        "eligibility": "4th or 5th year · one 1,500-word writing sample",
        "tags_json": ["Disputes", "Mumbai", "6 weeks"],
        "description": (
            "Research notes for live commercial disputes, first cuts of applications "
            "and written submissions, and client conferences with a supervising associate."
        ),
        "source_name": "Cyril Amarchand Mangaldas careers",
        "source_url": "https://www.cyrilshroff.com/careers/",
        "source_retrieved_at": datetime(2026, 6, 28, tzinfo=timezone.utc),
        "source_verified_at": datetime(2026, 6, 28, tzinfo=timezone.utc),
        "sort_order": 10,
        "active": True,
    },
    {
        "id": CATALOGUE_IDS["menon"],
        "slug": "menon",
        "role": "Judicial research assistant",
        "organisation": "Chambers of Sr. Adv. R. Menon",
        "organisation_public_id": public_organisation_id("Chambers of Sr. Adv. R. Menon"),
        "location": "Delhi High Court",
        "stipend_monthly_paise": 1_500_000,
        "verification_status": "unverified",
        "application_deadline": date(2027, 7, 8),
        "eligibility": "2nd year or above · rolling selection",
        "tags_json": ["Research", "Delhi"],
        "description": (
            "Judicial research support with a senior advocate's chambers at the "
            "Delhi High Court."
        ),
        "source_name": "Sample fixture",
        "source_url": None,
        "source_retrieved_at": None,
        "source_verified_at": None,
        "sort_order": 20,
        "active": True,
    },
    {
        "id": CATALOGUE_IDS["vidhi"],
        "slug": "vidhi",
        "role": "Research fellowship, policy",
        "organisation": "Vidhi Centre for Legal Policy",
        "organisation_public_id": public_organisation_id("Vidhi Centre for Legal Policy"),
        "location": "New Delhi",
        "stipend_monthly_paise": None,
        "verification_status": "unverified",
        "application_deadline": date(2027, 7, 15),
        "eligibility": "All years · certificate on completion",
        "tags_json": ["Policy", "Research"],
        "description": "Legal-policy research internship; certificate on completion. Unpaid.",
        "source_name": "Sample fixture",
        "source_url": None,
        "source_retrieved_at": None,
        "source_verified_at": None,
        "sort_order": 30,
        "active": True,
    },
)


def seed_internship_catalogue(session: Session) -> None:
    """Idempotently seed the deterministic catalogue for create-all test rigs.

    Migrated databases are seeded by revision 0014.  This helper exists for
    metadata-created tests and local isolated fixtures; it never commits.
    """
    existing = set(session.scalars(select(InternshipListing.slug)).all())
    for values in CATALOGUE_SEED:
        if values["slug"] not in existing:
            session.add(InternshipListing(**values))
    session.flush()


def listing_out(listing: InternshipListing) -> InternshipListingOut:
    return InternshipListingOut(
        id=listing.slug,
        organisation_id=listing.organisation_public_id,
        role=listing.role,
        organisation=listing.organisation,
        location=listing.location,
        stipend_monthly_paise=listing.stipend_monthly_paise,
        verification_status=listing.verification_status,
        application_deadline=listing.application_deadline,
        eligibility=listing.eligibility,
        tags=list(listing.tags_json or []),
        description=listing.description,
        source=InternshipSourceOut(
            name=listing.source_name,
            url=listing.source_url,
            retrieved_at=listing.source_retrieved_at,
            verified_at=listing.source_verified_at,
        ),
    )


def listing_or_none(session: Session, slug: str) -> InternshipListing | None:
    return session.scalar(
        select(InternshipListing).where(
            InternshipListing.slug == slug,
            InternshipListing.active.is_(True),
            InternshipListing.deleted_at.is_(None),
        )
    )


def list_catalogue(
    session: Session, *, page: int, page_size: int, verified_only: bool = False
) -> tuple[list[InternshipListing], int]:
    where: tuple = (
        InternshipListing.active.is_(True),
        InternshipListing.deleted_at.is_(None),
    )
    if verified_only:
        where += (InternshipListing.verification_status == "verified",)
    total = session.scalar(
        select(func.count()).select_from(InternshipListing).where(*where)
    ) or 0
    rows = list(
        session.scalars(
            select(InternshipListing)
            .where(*where)
            .order_by(InternshipListing.sort_order, InternshipListing.slug)
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
    )
    return rows, total


def list_saved(session: Session, user_id: uuid.UUID) -> list[InternshipListing]:
    return list(
        session.scalars(
            select(InternshipListing)
            .join(SavedInternship, SavedInternship.listing_id == InternshipListing.id)
            .where(
                SavedInternship.user_id == user_id,
                InternshipListing.active.is_(True),
                InternshipListing.deleted_at.is_(None),
            )
            .order_by(InternshipListing.sort_order, InternshipListing.slug)
        ).all()
    )


def _lock_user(session: Session, user_id: uuid.UUID) -> None:
    """Serialize one user's save mutations on PostgreSQL and prove ownership."""
    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or user.deleted_at is not None:
        raise LookupError("student_user_not_found")


def _insert_saved(session: Session, *, user_id: uuid.UUID, listing_id: uuid.UUID) -> bool:
    values = {"user_id": user_id, "listing_id": listing_id}
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        statement = (
            pg_insert(SavedInternship.__table__)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["user_id", "listing_id"])
            .returning(SavedInternship.id)
        )
        # DBAPI ``rowcount`` is not a reliable inserted-vs-conflicted signal
        # for PostgreSQL executemany/result implementations.  RETURNING emits
        # one identifier only for the request that actually inserted the row.
        return session.scalar(statement) is not None
    try:
        session.execute(insert(SavedInternship).values(**values))
        return True
    except IntegrityError:
        session.rollback()
        return False


def save_listing(
    session: Session, *, user_id: uuid.UUID, listing: InternshipListing
) -> bool:
    _lock_user(session, user_id)
    created = _insert_saved(session, user_id=user_id, listing_id=listing.id)
    if created:
        record_audit_event(
            session,
            action="internship.saved",
            resource_type="internship_listing",
            resource_id=listing.id,
            actor_user_id=user_id,
            actor_role="student",
            after_state={"listing_id": listing.slug, "saved": True},
            flush=False,
        )
    session.commit()
    return created


def unsave_listing(
    session: Session, *, user_id: uuid.UUID, listing: InternshipListing
) -> bool:
    _lock_user(session, user_id)
    row = session.scalar(
        select(SavedInternship).where(
            SavedInternship.user_id == user_id,
            SavedInternship.listing_id == listing.id,
        )
    )
    removed = row is not None
    if row is not None:
        session.delete(row)
        record_audit_event(
            session,
            action="internship.unsaved",
            resource_type="internship_listing",
            resource_id=listing.id,
            actor_user_id=user_id,
            actor_role="student",
            after_state={"listing_id": listing.slug, "saved": False},
            flush=False,
        )
    session.commit()
    return removed
