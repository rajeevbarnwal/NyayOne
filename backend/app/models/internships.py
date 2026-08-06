"""Internship discovery catalogue and student saves (SAATHI-60).

The catalogue owns the product-facing listing truth.  A stable slug is exposed
to clients while the internal UUID remains the relational key.  Provenance is
structured and constrained so a row cannot claim to be verified without a
verification timestamp.  Saves are owner-scoped and idempotent by database
constraint; no browser-local identifier is the persistence authority.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import TimestampedBase

INTERNSHIP_VERIFICATION_STATUSES = ("verified", "unverified")


class InternshipListing(TimestampedBase):
    __tablename__ = "internship_listings"

    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(160), nullable=False)
    organisation: Mapped[str] = mapped_column(String(200), nullable=False)
    # Immutable route identity: display-name corrections must not orphan
    # public risk-label URLs or saved catalogue references.
    organisation_public_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    location: Mapped[str] = mapped_column(String(120), nullable=False)
    stipend_monthly_paise: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(24), nullable=False, index=True
    )
    application_deadline: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    eligibility: Mapped[str] = mapped_column(String(400), nullable=False)
    tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    source_name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    source_retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint("slug", name="uq_internship_listings_slug"),
        CheckConstraint("length(slug) BETWEEN 1 AND 64", name="slug_length"),
        CheckConstraint("length(role) BETWEEN 1 AND 160", name="role_length"),
        CheckConstraint(
            "length(organisation) BETWEEN 1 AND 200", name="organisation_length"
        ),
        CheckConstraint("length(location) BETWEEN 1 AND 120", name="location_length"),
        CheckConstraint(
            "stipend_monthly_paise IS NULL OR stipend_monthly_paise >= 0",
            name="stipend_nonnegative",
        ),
        CheckConstraint(
            "verification_status IN ('verified', 'unverified')",
            name="verification_status",
        ),
        CheckConstraint(
            "(verification_status = 'verified' AND source_verified_at IS NOT NULL "
            "AND source_retrieved_at IS NOT NULL AND source_url IS NOT NULL) OR "
            "(verification_status = 'unverified' AND source_verified_at IS NULL)",
            name="verification_provenance_truthful",
        ),
        CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )


class SavedInternship(TimestampedBase):
    __tablename__ = "saved_internships"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("internship_listings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id", "listing_id", name="uq_saved_internships_user_listing"
        ),
        CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
