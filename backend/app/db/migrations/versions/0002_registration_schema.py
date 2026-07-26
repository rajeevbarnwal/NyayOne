"""Registration/auth/profile schema (SAATHI-366/448).

Creates the Product-approved (2026-07-26) tables: users, student_registrations,
student_profiles, otp_challenges, consents, student_verifications,
guardian_consents, audit_events. Built from the ORM metadata so the models,
migration and data-dictionary stay in sync by construction.
"""
from __future__ import annotations

from typing import Union

from alembic import op

# Register all model tables on Base.metadata.
import app.db.models.audit  # noqa: F401
import app.models  # noqa: F401
from app.db.base import Base

revision: str = "0002_registration_schema"
down_revision: Union[str, None] = "0001_initial_pgvector"
branch_labels = None
depends_on = None

TABLES = [
    "users",
    "student_registrations",
    "student_profiles",
    "otp_challenges",
    "consents",
    "student_verifications",
    "guardian_consents",
    "audit_events",
]


def _tables():
    return [Base.metadata.tables[name] for name in TABLES]


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, tables=_tables())


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind, tables=list(reversed(_tables())))
