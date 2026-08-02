"""Add interests and career_goal columns to student_profiles table.

Revision ID: 0012_student_profile_preferences
Revises: 0011_wave4_private_reporting
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_student_profile_preferences"
down_revision: Union[str, None] = "0012_wave4_moderation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("student_profiles") as batch:
        batch.add_column(sa.Column("interests", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("career_goal", sa.String(length=160), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("student_profiles") as batch:
        batch.drop_column("career_goal")
        batch.drop_column("interests")
