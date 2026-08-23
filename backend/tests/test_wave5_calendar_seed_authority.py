"""Wave 5's real-browser seed must produce a canonical student session actor."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.registration import Consent, StudentProfile
from app.services import login_service
from scripts.seed_wave5_calendar_e2e import provision


SESSION_TOKEN = "wave5-seed-session-token-0000000000000001"


def _count(session: Session, model: type[Consent] | type[StudentProfile]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_wave5_seed_is_idempotent_and_resolves_a_canonical_student_actor(
    db_session: Session,
):
    first = provision(db_session, SESSION_TOKEN)
    db_session.commit()

    actor = login_service.session_claims(
        db_session,
        SESSION_TOKEN,
        datetime.now(timezone.utc),
        touch=False,
    )
    assert actor is not None
    assert actor["sub"] == first["actor_id"]
    assert actor["roles"] == ["student"]
    assert uuid.UUID(str(actor["student_profile_id"]))
    assert actor["consent_state"] == ["registration"]
    assert _count(db_session, StudentProfile) == 1
    assert _count(db_session, Consent) == 1
    profile = db_session.scalar(select(StudentProfile))
    consent = db_session.scalar(select(Consent))
    assert profile is not None
    assert consent is not None
    assert profile.registration_id == consent.registration_id
    assert consent.purpose == "registration"
    assert consent.accepted is True
    assert consent.policy_version == "wave5-browser-v1"
    assert consent.accepted_at is not None
    assert profile.deleted_at is None
    assert consent.deleted_at is None

    second = provision(db_session, SESSION_TOKEN)
    db_session.commit()

    assert second["actor_id"] == first["actor_id"]
    second_actor = login_service.session_claims(
        db_session,
        SESSION_TOKEN,
        datetime.now(timezone.utc),
        touch=False,
    )
    assert second_actor is not None
    assert second_actor["student_profile_id"] == actor["student_profile_id"]
    assert second_actor["consent_state"] == ["registration"]
    assert _count(db_session, StudentProfile) == 1
    assert _count(db_session, Consent) == 1
