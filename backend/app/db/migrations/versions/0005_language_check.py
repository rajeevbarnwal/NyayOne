"""F2 (SAATHI-58/107): canonical language CHECK on user_settings.

Forward migration only — 0004 stays immutable. Maps known legacy display
labels onto canonical codes, FAILS LOUDLY on any unknown legacy value (no
silent coercion), then adds the named CHECK constraint. Downgrade removes only
the constraint; settings data is preserved in both directions.
"""
from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_language_check"
down_revision: Union[str, None] = "0004_wave1_foundation"
branch_labels = None
depends_on = None

_LEGACY = {
    "English": "en",
    "English (en-IN)": "en",
    "हिन्दी (Hindi)": "hi",
    "हिन्दी (hi-IN)": "hi",
    "Hindi": "hi",
}
_CANONICAL = ("en", "hi")


def upgrade() -> None:
    bind = op.get_bind()
    # 1) Map known legacy labels to canonical codes.
    for legacy, code in _LEGACY.items():
        bind.execute(
            sa.text("UPDATE user_settings SET language = :code WHERE language = :legacy"),
            {"code": code, "legacy": legacy},
        )
    # 2) Refuse to proceed if unknown values remain (explicit report, no coercion).
    rows = bind.execute(
        sa.text("SELECT DISTINCT language FROM user_settings WHERE language NOT IN ('en','hi')")
    ).fetchall()
    if rows:
        raise RuntimeError(
            "0005_language_check: unmapped legacy language values present: "
            + ", ".join(repr(r[0]) for r in rows)
            + " — map them explicitly before applying the constraint."
        )
    # 3) Named CHECK constraint (batch mode: ALTER on PostgreSQL, rebuild on SQLite).
    with op.batch_alter_table("user_settings") as batch:
        batch.create_check_constraint("ck_user_settings_language", "language IN ('en','hi')")


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_constraint("ck_user_settings_language", type_="check")
