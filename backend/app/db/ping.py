"""Lightweight DB reachability check for developer/health use (no domain logic)."""
from __future__ import annotations

from sqlalchemy import text

from app.db.session import get_engine


def check_database() -> dict[str, object]:
    """Attempt a trivial query. Returns a status dict; never raises so a
    health endpoint can report 'unavailable' cleanly when the DB is down."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"database": "ok", "dialect": engine.dialect.name}
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        return {"database": "unavailable", "detail": str(exc)[:200]}
