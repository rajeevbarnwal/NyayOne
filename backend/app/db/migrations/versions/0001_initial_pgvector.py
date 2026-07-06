"""initial baseline: enable pgvector extension

Revision ID: 0001_initial_pgvector
Revises:
Create Date: 2026-07-06

Baseline migration. Enables the pgvector extension on PostgreSQL so downstream
Student Module tables can add vector columns for RAG. No domain tables are
created in the foundation stage. On non-Postgres backends (e.g. SQLite used by
tests) the extension step is skipped safely.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001_initial_pgvector"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS vector")
