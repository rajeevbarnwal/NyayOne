"""Idempotent Wave 3 credential-trust actors and issuer setup.

Run after ``alembic upgrade head``:

    python -m scripts.seed_wave3_e2e

The script reuses the repository-owned E2E users and adds only the minimum
server-side state needed for S-82 through S-85 browser journeys. It never
calls production endpoints, never stores plaintext lookup values, and is safe
to execute repeatedly.
"""
from __future__ import annotations

import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

STUDENT_ID = uuid.UUID("00000000-0000-4000-8000-0000000000de")
ISSUER_ACTOR_ID = uuid.UUID("00000000-0000-4000-8000-0000000000c3")
ISSUER_ID = uuid.UUID("00000000-0000-4000-8000-000000000253")
REGISTRATION_ID = uuid.UUID("00000000-0000-4000-8000-000000000254")
AUTHORISATION_ID = uuid.UUID("00000000-0000-4000-8000-000000000255")


def provision(session: Session) -> dict[str, int]:
    from app.core.crypto import active_key_version, encrypt, keyed_hash
    from app.models.credentials import CredentialIssuer, IssuerAuthorisation
    from app.models.registration import StudentRegistration
    from scripts.seed_e2e_actors import provision as provision_common

    common = provision_common(session)

    issuer = session.get(CredentialIssuer, ISSUER_ID)
    created_issuer = 0
    if issuer is None:
        issuer = CredentialIssuer(
            id=ISSUER_ID,
            display_name="National Law Skills Council",
            issuer_type="institution",
            active=True,
        )
        session.add(issuer)
        created_issuer = 1
    else:
        issuer.display_name = "National Law Skills Council"
        issuer.issuer_type = "institution"
        issuer.active = True
        issuer.deleted_at = None

    registration = session.scalar(
        select(StudentRegistration).where(
            StudentRegistration.user_id == STUDENT_ID,
            StudentRegistration.deleted_at.is_(None),
        )
    )
    created_registration = 0
    # Reserved outside the registration E2E suite's 9000000001..0007 range.
    mobile = "9000000097"
    dob = "2001-01-02"
    if registration is None:
        registration = StudentRegistration(
            id=REGISTRATION_ID,
            user_id=STUDENT_ID,
            first_name="Aditi",
            middle_name=None,
            last_name="Nair",
            mobile_hash=keyed_hash(mobile),
            mobile_ct=encrypt(mobile),
            dob_hash=keyed_hash(dob),
            dob_ct=encrypt(dob),
            key_version=active_key_version(),
            institution_ref="National Law School of India University",
            status="active",
            is_minor=False,
            idempotency_key="wave3-e2e-registration-v1",
            idempotency_key_legacy=True,
        )
        session.add(registration)
        created_registration = 1
    else:
        # Natural-key reconciliation keeps an already-provisioned QA database
        # aligned with the current, non-conflicting fixture contract.
        registration.mobile_hash = keyed_hash(mobile)
        registration.mobile_ct = encrypt(mobile)
        registration.dob_hash = keyed_hash(dob)
        registration.dob_ct = encrypt(dob)
        registration.key_version = active_key_version()

    grant = session.get(IssuerAuthorisation, AUTHORISATION_ID)
    if grant is None:
        grant = session.scalar(
            select(IssuerAuthorisation).where(
                IssuerAuthorisation.issuer_id == ISSUER_ID,
                IssuerAuthorisation.user_id == ISSUER_ACTOR_ID,
            )
        )
    created_authorisation = 0
    if grant is None:
        session.add(
            IssuerAuthorisation(
                id=AUTHORISATION_ID,
                issuer_id=ISSUER_ID,
                user_id=ISSUER_ACTOR_ID,
                can_verify=True,
                can_revoke=True,
                active=True,
                granted_by_user_id=None,
            )
        )
        created_authorisation = 1
    else:
        grant.can_verify = True
        grant.can_revoke = True
        grant.active = True
        grant.deleted_at = None

    session.flush()
    return {
        "common_users": common["created_users"],
        "common_schools": common["created_schools"],
        "created_issuer": created_issuer,
        "created_registration": created_registration,
        "created_authorisation": created_authorisation,
    }


def main() -> int:
    import pathlib

    backend_root = str(pathlib.Path(__file__).resolve().parent.parent)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        summary = provision(session)
        session.commit()
    print(f"seed_wave3_e2e: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
