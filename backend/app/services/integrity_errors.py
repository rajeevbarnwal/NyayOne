"""Small, PostgreSQL-aware helpers for translating named invariant failures."""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError


def constraint_name(exc: IntegrityError) -> str | None:
    """Return the database-reported constraint/index name when available.

    PostgreSQL exposes this through the DBAPI diagnostic object.  Deliberately
    do not classify arbitrary uniqueness text: only an exact named invariant is
    safe to translate into a product conflict.
    """

    diagnostic = getattr(exc.orig, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None
