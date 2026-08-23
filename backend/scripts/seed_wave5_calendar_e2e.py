"""Isolated target-runtime fixture for the Wave 5 calendar release gate.

This script is QA plumbing only.  It creates one authenticated student, one
real tutoring session and one real credential-reminder job in the database the
backend will use.  Calendar aggregation must materialise the latter two through
the production adapters; this script never inserts calendar rows directly.

Safety contract:

* ``APP_ENV=testing`` and ``WAVE5_E2E_ALLOW_SEED=true`` are mandatory.
* the database name/path must visibly identify an isolated test target;
* the raw browser-session bearer is supplied only through the environment,
  hashed before persistence, and never printed or written to the manifest;
* repeated runs reconcile the same natural fixture ids instead of duplicating
  rows.

Example (from ``backend/``):

    APP_ENV=testing WAVE5_E2E_ALLOW_SEED=true \
      WAVE5_E2E_SESSION_TOKEN="$WAVE5_E2E_SESSION_TOKEN" \
      DATABASE_URL="$DATABASE_URL" \
      python scripts/seed_wave5_calendar_e2e.py \
        --manifest /tmp/wave5-calendar-seed.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.crypto import encrypt, key_version, keyed_hash  # noqa: E402
from app.db.session import get_sessionmaker  # noqa: E402
from app.models.credentials import Credential, CredentialReminderJob  # noqa: E402
from app.models.registration import (  # noqa: E402
    AuthSession,
    Consent,
    StudentProfile,
    StudentRegistration,
    User,
)
from app.models.wave2 import (  # noqa: E402
    TutorAvailabilitySlot,
    TutorProfile,
    TutoringSession,
)

NAMESPACE = uuid.UUID("00000000-0000-4000-8000-000000000295")
STUDENT_ID = uuid.uuid5(NAMESPACE, "student")
REGISTRATION_ID = uuid.uuid5(NAMESPACE, "student-registration")
TUTOR_USER_ID = uuid.uuid5(NAMESPACE, "tutor-user")
TUTOR_ID = uuid.uuid5(NAMESPACE, "tutor-profile")
SLOT_ID = uuid.uuid5(NAMESPACE, "tutoring-slot")
SESSION_ID = uuid.uuid5(NAMESPACE, "tutoring-session")
CREDENTIAL_ID = uuid.uuid5(NAMESPACE, "credential")
REMINDER_ID = uuid.uuid5(NAMESPACE, "credential-reminder")


def assert_isolated_target(database_url: str) -> None:
    if os.getenv("APP_ENV", "").strip().lower() not in {"test", "testing"}:
        raise RuntimeError("refusing Wave 5 seed outside APP_ENV=testing")
    if os.getenv("WAVE5_E2E_ALLOW_SEED", "").strip().lower() != "true":
        raise RuntimeError("WAVE5_E2E_ALLOW_SEED=true is required")
    parsed = make_url(database_url)
    target = (parsed.database or "").casefold()
    markers = ("test", "qa", "e2e", "wave5", "saathi295", "calendar")
    if not target or not any(marker in target for marker in markers):
        raise RuntimeError(
            "database path/name must visibly identify an isolated Wave 5 QA target"
        )
    backend = parsed.get_backend_name()
    if backend == "postgresql":
        # A QA-looking database name on a remote server is still a destructive
        # target.  This seed is intentionally restricted to a database on the
        # same machine as the runner.
        if (parsed.host or "").casefold() not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("PostgreSQL Wave 5 seed target must use a loopback host")
    elif backend == "sqlite":
        # SQLite is supplementary local development coverage only.  Require an
        # explicit absolute file so a typo cannot silently create a relative DB
        # inside a source checkout; in-memory URLs are deliberately refused.
        database = parsed.database or ""
        if database == ":memory:" or not Path(database).is_absolute():
            raise RuntimeError("SQLite Wave 5 seed target must be an absolute isolated file")
    else:
        raise RuntimeError("Wave 5 seed supports only loopback PostgreSQL or local-file SQLite")


def _upsert_user(session, user_id: uuid.UUID, role: str) -> User:
    user = session.get(User, user_id)
    if user is None:
        user = User(id=user_id, role=role, status="active")
        session.add(user)
    else:
        user.role = role
        user.status = "active"
        user.deleted_at = None
    return user


def provision(session, raw_session_token: str) -> dict[str, object]:
    if len(raw_session_token) < 32:
        raise RuntimeError("WAVE5_E2E_SESSION_TOKEN must contain at least 32 characters")

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    tutoring_start = now + timedelta(days=2, hours=2)
    tutoring_end = tutoring_start + timedelta(hours=1)
    reminder_start = now + timedelta(days=3, hours=1)

    _upsert_user(session, STUDENT_ID, "student")
    _upsert_user(session, TUTOR_USER_ID, "lawyer")
    session.flush()

    # Cookie-session resolution intentionally requires a genuine active student
    # registration.  Use encrypted deterministic QA values so the fixture does
    # not bypass the production login boundary and no direct identifier is
    # searchable in the database.
    mobile_ct = encrypt("9999999999")
    dob_ct = encrypt("2000-01-01")
    registration = session.get(StudentRegistration, REGISTRATION_ID)
    if registration is None:
        registration = StudentRegistration(
            id=REGISTRATION_ID,
            user_id=STUDENT_ID,
            first_name="Calendar",
            middle_name=None,
            last_name="Fixture",
            mobile_hash=keyed_hash("9999999999"),
            mobile_ct=mobile_ct,
            dob_hash=keyed_hash("2000-01-01"),
            dob_ct=dob_ct,
            key_version=key_version(mobile_ct),
            institution_ref="WAVE5-QA",
            status="active",
            is_minor=False,
            idempotency_key="wave5-calendar-e2e-registration",
            idempotency_key_legacy=True,
        )
        session.add(registration)
    else:
        registration.user_id = STUDENT_ID
        registration.status = "active"
        registration.is_minor = False
        registration.deleted_at = None

    # The CI sessionmaker disables autoflush.  Persist the registration parent
    # before adding its canonical profile and consent children so PostgreSQL's
    # immediate foreign-key checks see the complete graph in dependency order.
    session.flush()

    # This fixture writes after the real migrations have run, so it must create
    # the same minimum authority graph as production registration.  A student
    # session without both rows is intentionally rejected by the frontend's
    # fail-closed session parser before any private route can mount.
    profile = session.scalar(
        select(StudentProfile).where(
            StudentProfile.registration_id == registration.id
        )
    )
    if profile is None:
        session.add(
            StudentProfile(
                registration_id=registration.id,
                key_version=registration.key_version,
            )
        )
    else:
        profile.key_version = registration.key_version
        profile.deleted_at = None

    consent = session.scalar(
        select(Consent).where(
            Consent.registration_id == registration.id,
            Consent.purpose == "registration",
        )
    )
    if consent is None:
        session.add(
            Consent(
                registration_id=registration.id,
                purpose="registration",
                accepted=True,
                policy_version="wave5-browser-v1",
                accepted_at=now,
            )
        )
    else:
        consent.accepted = True
        consent.policy_version = "wave5-browser-v1"
        consent.accepted_at = now
        consent.deleted_at = None

    # Reconcile one active, cookie-backed authenticated session.  The raw token
    # never enters any model field or output artifact.
    token_hash = keyed_hash(raw_session_token)
    auth = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if auth is None:
        auth = AuthSession(
            user_id=STUDENT_ID,
            token_hash=token_hash,
            status="active",
            expires_at=now + timedelta(hours=4),
            last_seen_at=now,
        )
        session.add(auth)
    else:
        auth.user_id = STUDENT_ID
        auth.status = "active"
        auth.expires_at = now + timedelta(hours=4)
        auth.last_seen_at = now
        auth.revoked_at = None

    tutor = session.get(TutorProfile, TUTOR_ID)
    if tutor is None:
        tutor = TutorProfile(
            id=TUTOR_ID,
            user_id=TUTOR_USER_ID,
            display_name="Adv. Calendar Fixture",
            headline="Target-runtime calendar interoperability fixture",
            experience_years=8,
            verified_identity=True,
            verified_credentials=True,
            source="qa_fixture",
            retrieved_at=now,
            status="active",
            session_price_paise=250_000,
            session_currency="INR",
        )
        session.add(tutor)
    else:
        tutor.user_id = TUTOR_USER_ID
        tutor.status = "active"
        tutor.deleted_at = None
    # These fixture models deliberately do not declare ORM relationships, so
    # SQLAlchemy cannot infer FK insert order from object references alone.
    # Flush each parent before constructing its child; PostgreSQL enforces the
    # same ordering the production services rely on.
    session.flush()

    slot = session.get(TutorAvailabilitySlot, SLOT_ID)
    if slot is None:
        slot = TutorAvailabilitySlot(
            id=SLOT_ID,
            tutor_id=TUTOR_ID,
            start_utc=tutoring_start,
            end_utc=tutoring_end,
            iana_timezone="Asia/Kolkata",
            status="booked",
        )
        session.add(slot)
    else:
        slot.tutor_id = TUTOR_ID
        slot.start_utc = tutoring_start
        slot.end_utc = tutoring_end
        slot.iana_timezone = "Asia/Kolkata"
        slot.status = "booked"
        slot.deleted_at = None
    session.flush()

    tutoring = session.get(TutoringSession, SESSION_ID)
    if tutoring is None:
        tutoring = TutoringSession(
            id=SESSION_ID,
            slot_id=SLOT_ID,
            tutor_id=TUTOR_ID,
            student_user_id=STUDENT_ID,
            order_id=None,
            start_utc=tutoring_start,
            end_utc=tutoring_end,
            iana_timezone="Asia/Kolkata",
            status="confirmed",
            version=1,
        )
        session.add(tutoring)
    else:
        tutoring.slot_id = SLOT_ID
        tutoring.tutor_id = TUTOR_ID
        tutoring.student_user_id = STUDENT_ID
        tutoring.start_utc = tutoring_start
        tutoring.end_utc = tutoring_end
        tutoring.iana_timezone = "Asia/Kolkata"
        tutoring.status = "confirmed"
        tutoring.deleted_at = None

    credential = session.get(Credential, CREDENTIAL_ID)
    if credential is None:
        credential = Credential(
            id=CREDENTIAL_ID,
            owner_user_id=STUDENT_ID,
            issuer_id=None,
            title="Calendar interoperability credential",
            credential_type="course_completion",
            status="verified",
            issue_date=date.today() - timedelta(days=90),
            expiry_date=date.today() + timedelta(days=33),
            version=1,
            idempotency_key="wave5-calendar-e2e-credential",
        )
        session.add(credential)
    else:
        credential.owner_user_id = STUDENT_ID
        credential.status = "verified"
        credential.expiry_date = date.today() + timedelta(days=33)
        credential.deleted_at = None
    session.flush()

    reminder = session.get(CredentialReminderJob, REMINDER_ID)
    if reminder is None:
        reminder = CredentialReminderJob(
            id=REMINDER_ID,
            credential_id=CREDENTIAL_ID,
            days_before=30,
            remind_at=reminder_start,
            status="pending",
        )
        session.add(reminder)
    else:
        reminder.credential_id = CREDENTIAL_ID
        reminder.days_before = 30
        reminder.remind_at = reminder_start
        reminder.status = "pending"
        reminder.deleted_at = None

    session.flush()
    return {
        "actor_id": str(STUDENT_ID),
        "tutoring_session_id": str(SESSION_ID),
        "credential_reminder_id": str(REMINDER_ID),
        "tutoring_start_utc": tutoring_start.isoformat(),
        "tutoring_end_utc": tutoring_end.isoformat(),
        "credential_reminder_start_utc": reminder_start.isoformat(),
        "timezone": "Asia/Kolkata",
        "session_token": "NOT_LOGGED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL", "")
    raw_token = os.getenv("WAVE5_E2E_SESSION_TOKEN", "")
    try:
        assert_isolated_target(database_url)
        if not raw_token:
            raise RuntimeError("WAVE5_E2E_SESSION_TOKEN is required")
        if not args.manifest.is_absolute():
            raise RuntimeError("--manifest must be an absolute path")
        if args.manifest.exists():
            raise RuntimeError("refusing to overwrite an existing seed manifest")
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        with get_sessionmaker()() as session:
            manifest = provision(session, raw_token)
            session.commit()
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(
        "seed_wave5_calendar_e2e: target-runtime fixture ready; "
        "raw_session_token=NOT_LOGGED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
