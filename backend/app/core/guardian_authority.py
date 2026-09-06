"""Guardian authority derives from the NYAY-11 server-attested ceremony."""
from __future__ import annotations

from typing import Protocol


class GuardianState(Protocol):
    status: str
    verified: bool


def has_authoritative_guardian_proof(_row: GuardianState | None, *, now=None) -> bool:
    """Legacy flags alone never grant; resolve the current DB proof and clock."""
    from datetime import datetime, timezone
    from sqlalchemy.orm import object_session
    from sqlalchemy import inspect
    from app.services.student_authority import guardian_is_current
    if _row is None or getattr(_row, "registration_id", None) is None:
        return False
    if inspect(_row, raiseerr=False) is None:
        return False
    session = object_session(_row)
    if session is None:
        return False
    return guardian_is_current(session, _row.registration_id, now=now or datetime.now(timezone.utc))
