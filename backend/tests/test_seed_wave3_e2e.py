"""Wave 3 deterministic setup is idempotent and privacy-safe."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.crypto import decrypt, keyed_hash
from app.models.credentials import CredentialIssuer, IssuerAuthorisation
from app.models.registration import (
    AuthSession,
    Consent,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
)
from app.services import login_service, profile_service
from scripts.seed_wave3_e2e import (
    ISSUER_ACTOR_ID,
    ISSUER_ID,
    STUDENT_ID,
    provision,
)


def test_seed_wave3_twice_without_duplicates(db_session):
    first = provision(db_session)
    db_session.commit()
    second = provision(db_session)
    db_session.commit()

    assert first["created_issuer"] == 1
    assert first["created_registration"] == 1
    assert first["created_profile"] == 1
    assert first["created_verification"] == 1
    assert first["created_consent"] == 1
    assert first["created_authorisation"] == 1
    assert second["created_issuer"] == 0
    assert second["created_registration"] == 0
    assert second["created_profile"] == 0
    assert second["created_verification"] == 0
    assert second["created_consent"] == 0
    assert second["created_authorisation"] == 0
    assert db_session.scalar(select(func.count()).select_from(CredentialIssuer)) == 1
    assert (
        db_session.scalar(select(func.count()).select_from(IssuerAuthorisation))
        == 1
    )
    assert (
        db_session.scalar(select(func.count()).select_from(StudentRegistration))
        == 1
    )
    assert db_session.scalar(select(func.count()).select_from(StudentProfile)) == 1
    assert (
        db_session.scalar(select(func.count()).select_from(StudentVerification))
        == 1
    )
    assert db_session.scalar(select(func.count()).select_from(Consent)) == 1


def test_seed_wave3_actor_grant_and_registration_are_authoritative(db_session):
    provision(db_session)
    db_session.commit()

    issuer = db_session.get(CredentialIssuer, ISSUER_ID)
    grant = db_session.scalar(
        select(IssuerAuthorisation).where(
            IssuerAuthorisation.issuer_id == ISSUER_ID,
            IssuerAuthorisation.user_id == ISSUER_ACTOR_ID,
        )
    )
    registration = db_session.scalar(
        select(StudentRegistration).where(
            StudentRegistration.user_id == STUDENT_ID
        )
    )
    profile = db_session.scalar(
        select(StudentProfile).where(
            StudentProfile.registration_id == registration.id
        )
    )
    verification = db_session.scalar(
        select(StudentVerification).where(
            StudentVerification.registration_id == registration.id
        )
    )
    consent = db_session.scalar(
        select(Consent).where(
            Consent.registration_id == registration.id,
            Consent.purpose == "registration",
        )
    )
    authority = profile_service.resolve_authority(db_session, STUDENT_ID)

    assert issuer is not None and issuer.active
    assert grant is not None and grant.active and grant.can_verify and grant.can_revoke
    assert registration is not None and registration.status == "active"
    assert registration.mobile_hash != "9000000097"
    assert registration.dob_hash != "2001-01-02"
    assert decrypt(registration.mobile_ct) == "9000000097"
    assert decrypt(registration.dob_ct) == "2001-01-02"
    assert profile is not None and profile.deleted_at is None
    assert profile.key_version == registration.key_version
    assert verification is not None and verification.deleted_at is None
    assert verification.method == "institutional_email"
    assert verification.status == "pending"
    assert verification.verified_email_hash is None
    assert consent is not None and consent.deleted_at is None
    assert consent.accepted is True
    assert consent.accepted_at is not None
    assert authority.registration.id == registration.id
    assert authority.profile.id == profile.id

    raw_session_token = "wave3-seed-session-token-0000000000000001"
    now = datetime.now(timezone.utc)
    db_session.add(
        AuthSession(
            user_id=STUDENT_ID,
            token_hash=keyed_hash(raw_session_token),
            status="active",
            expires_at=now + timedelta(hours=1),
            last_seen_at=now,
        )
    )
    db_session.commit()
    actor = login_service.session_claims(
        db_session,
        raw_session_token,
        now,
        touch=False,
    )
    assert actor is not None
    assert actor["student_profile_id"] == str(profile.id)
    assert actor["consent_state"] == ["registration"]
