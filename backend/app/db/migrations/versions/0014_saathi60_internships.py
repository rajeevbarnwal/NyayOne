"""SAATHI-60 internship discovery catalogue and saved listings.

Revision ID: 0014_saathi60_internships
Revises: 0013_wave5_calendar_interop
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0014_saathi60_internships"
down_revision: str | None = "0013_wave5_calendar_interop"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)


def _ts() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "internship_listings",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("role", sa.String(160), nullable=False),
        sa.Column("organisation", sa.String(200), nullable=False),
        sa.Column("location", sa.String(120), nullable=False),
        sa.Column("stipend_monthly_paise", sa.Integer(), nullable=True),
        sa.Column("verification_status", sa.String(24), nullable=False),
        sa.Column("application_deadline", sa.Date(), nullable=False),
        sa.Column("eligibility", sa.String(400), nullable=False),
        sa.Column("tags_json", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("source_name", sa.String(160), nullable=False),
        sa.Column("source_url", sa.String(400), nullable=True),
        sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *_ts(),
        sa.UniqueConstraint("slug", name="uq_internship_listings_slug"),
        sa.CheckConstraint("length(slug) BETWEEN 1 AND 64", name="slug_length"),
        sa.CheckConstraint("length(role) BETWEEN 1 AND 160", name="role_length"),
        sa.CheckConstraint(
            "length(organisation) BETWEEN 1 AND 200", name="organisation_length"
        ),
        sa.CheckConstraint(
            "length(location) BETWEEN 1 AND 120", name="location_length"
        ),
        sa.CheckConstraint(
            "stipend_monthly_paise IS NULL OR stipend_monthly_paise >= 0",
            name="stipend_nonnegative",
        ),
        sa.CheckConstraint(
            "verification_status IN ('verified', 'unverified')",
            name="verification_status",
        ),
        sa.CheckConstraint(
            "(verification_status = 'verified' AND source_verified_at IS NOT NULL "
            "AND source_retrieved_at IS NOT NULL AND source_url IS NOT NULL) OR "
            "(verification_status = 'unverified' AND source_verified_at IS NULL)",
            name="verification_provenance_truthful",
        ),
        sa.CheckConstraint("sort_order >= 0", name="sort_order_nonnegative"),
        sa.CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
    op.create_index(
        "ix_internship_listings_verification_status",
        "internship_listings",
        ["verification_status"],
    )
    op.create_index(
        "ix_internship_listings_application_deadline",
        "internship_listings",
        ["application_deadline"],
    )

    op.create_table(
        "saved_internships",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "user_id",
            _UUID,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "listing_id",
            _UUID,
            sa.ForeignKey("internship_listings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_ts(),
        sa.UniqueConstraint(
            "user_id", "listing_id", name="uq_saved_internships_user_listing"
        ),
        sa.CheckConstraint("metadata_json IS NULL", name="metadata_must_be_null"),
    )
    op.create_index("ix_saved_internships_user_id", "saved_internships", ["user_id"])
    op.create_index(
        "ix_saved_internships_listing_id", "saved_internships", ["listing_id"]
    )

    now = datetime(2026, 6, 28, tzinfo=timezone.utc)
    listings = sa.table(
        "internship_listings",
        sa.column("id", _UUID),
        sa.column("slug", sa.String()),
        sa.column("role", sa.String()),
        sa.column("organisation", sa.String()),
        sa.column("location", sa.String()),
        sa.column("stipend_monthly_paise", sa.Integer()),
        sa.column("verification_status", sa.String()),
        sa.column("application_deadline", sa.Date()),
        sa.column("eligibility", sa.String()),
        sa.column("tags_json", sa.JSON()),
        sa.column("description", sa.String()),
        sa.column("source_name", sa.String()),
        sa.column("source_url", sa.String()),
        sa.column("source_retrieved_at", sa.DateTime(timezone=True)),
        sa.column("source_verified_at", sa.DateTime(timezone=True)),
        sa.column("sort_order", sa.Integer()),
        sa.column("active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        listings,
        [
            {
                "id": uuid.UUID("60000000-0000-4000-8000-000000000001"),
                "slug": "cam",
                "role": "Summer Associate, disputes",
                "organisation": "Cyril Amarchand Mangaldas",
                "location": "Mumbai",
                "stipend_monthly_paise": 4_000_000,
                "verification_status": "verified",
                "application_deadline": date(2027, 7, 9),
                "eligibility": "4th or 5th year · one 1,500-word writing sample",
                "tags_json": ["Disputes", "Mumbai", "6 weeks"],
                "description": (
                    "Research notes for live commercial disputes, first cuts of "
                    "applications and written submissions, and client conferences "
                    "with a supervising associate."
                ),
                "source_name": "Cyril Amarchand Mangaldas careers",
                "source_url": "https://www.cyrilshroff.com/careers/",
                "source_retrieved_at": now,
                "source_verified_at": now,
                "sort_order": 10,
                "active": True,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            },
            {
                "id": uuid.UUID("60000000-0000-4000-8000-000000000002"),
                "slug": "menon",
                "role": "Judicial research assistant",
                "organisation": "Chambers of Sr. Adv. R. Menon",
                "location": "Delhi High Court",
                "stipend_monthly_paise": 1_500_000,
                "verification_status": "unverified",
                "application_deadline": date(2027, 7, 8),
                "eligibility": "2nd year or above · rolling selection",
                "tags_json": ["Research", "Delhi"],
                "description": (
                    "Judicial research support with a senior advocate's chambers "
                    "at the Delhi High Court."
                ),
                "source_name": "Sample fixture",
                "source_url": None,
                "source_retrieved_at": None,
                "source_verified_at": None,
                "sort_order": 20,
                "active": True,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            },
            {
                "id": uuid.UUID("60000000-0000-4000-8000-000000000003"),
                "slug": "vidhi",
                "role": "Research fellowship, policy",
                "organisation": "Vidhi Centre for Legal Policy",
                "location": "New Delhi",
                "stipend_monthly_paise": None,
                "verification_status": "unverified",
                "application_deadline": date(2027, 7, 15),
                "eligibility": "All years · certificate on completion",
                "tags_json": ["Policy", "Research"],
                "description": (
                    "Legal-policy research internship; certificate on completion. "
                    "Unpaid."
                ),
                "source_name": "Sample fixture",
                "source_url": None,
                "source_retrieved_at": None,
                "source_verified_at": None,
                "sort_order": 30,
                "active": True,
                "created_at": now,
                "updated_at": now,
                "deleted_at": None,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_saved_internships_listing_id", table_name="saved_internships")
    op.drop_index("ix_saved_internships_user_id", table_name="saved_internships")
    op.drop_table("saved_internships")
    op.drop_index(
        "ix_internship_listings_application_deadline",
        table_name="internship_listings",
    )
    op.drop_index(
        "ix_internship_listings_verification_status",
        table_name="internship_listings",
    )
    op.drop_table("internship_listings")
