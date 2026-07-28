"""Wave 3 deterministic setup is idempotent and privacy-safe."""
from __future__ import annotations

from sqlalchemy import func, select

from app.core.crypto import decrypt
from app.models.credentials import CredentialIssuer, IssuerAuthorisation
from app.models.registration import StudentRegistration
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
    assert first["created_authorisation"] == 1
    assert second["created_issuer"] == 0
    assert second["created_registration"] == 0
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

    assert issuer is not None and issuer.active
    assert grant is not None and grant.active and grant.can_verify and grant.can_revoke
    assert registration is not None and registration.status == "active"
    assert registration.mobile_hash != "9000000097"
    assert registration.dob_hash != "2001-01-02"
    assert decrypt(registration.mobile_ct) == "9000000097"
    assert decrypt(registration.dob_ct) == "2001-01-02"
