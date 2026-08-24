"""Isolated-runtime-only SAATHI-274 browser fixture.

This script refuses to run unless APP_ENV is testing, an explicit seed flag is
present, and the database name/path visibly denotes an isolated QA database.
The raw opaque moderator and student session tokens come from the process
environment, are stored only as keyed hashes, and are never printed or written
to evidence.
"""
from __future__ import annotations

import os
import secrets
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import is_isolated_wave4_database_url

MODERATOR_ID = uuid.UUID("00000000-0000-4000-8000-0000000000c4")
REPORTER_ID = uuid.UUID("00000000-0000-4000-8000-0000000000de")
REPORTER_REGISTRATION_ID = uuid.UUID("00000000-0000-4000-8000-000000008601")
REPORT_IDS = tuple(uuid.UUID(f"00000000-0000-4000-8000-{2740 + index:012d}") for index in range(4))
REPORTER_IDS = tuple(uuid.UUID(f"00000000-0000-4000-8000-{8600 + index:012d}") for index in range(4))


def _assert_distinct_session_tokens(
    raw_session_token: str,
    raw_student_session_token: str | None,
) -> None:
    if (
        raw_student_session_token is not None
        and secrets.compare_digest(raw_session_token, raw_student_session_token)
    ):
        raise RuntimeError(
            "WAVE4_E2E_SESSION_TOKEN and "
            "WAVE4_E2E_STUDENT_SESSION_TOKEN must be distinct"
        )


def assert_isolated_target(
    database_url: str,
    *,
    opt_in_env: str = "WAVE4_E2E_ALLOW_SEED",
) -> None:
    if os.getenv("APP_ENV", "").strip().lower() not in {"test", "testing"}:
        raise RuntimeError("refusing E2E seed outside APP_ENV=testing")
    if os.getenv(opt_in_env, "").strip().lower() != "true":
        raise RuntimeError(f"{opt_in_env}=true is required")
    test_database_url = os.getenv("TEST_DATABASE_URL", "").strip()
    actual_database_url = (database_url or "").strip()
    if not test_database_url or test_database_url != actual_database_url:
        raise RuntimeError("TEST_DATABASE_URL must exactly equal DATABASE_URL")
    if not is_isolated_wave4_database_url(actual_database_url):
        raise RuntimeError(
            "database target must be an isolated local Wave 4 QA database"
        )


def _provision_student_browser_authority(
    session: Session,
    raw_student_session_token: str,
    now: datetime,
    created: dict[str, int],
) -> None:
    """Add the S-86/S-87 browser authority only when explicitly requested."""

    if len(raw_student_session_token) < 32:
        raise RuntimeError(
            "WAVE4_E2E_STUDENT_SESSION_TOKEN must contain at least 32 characters"
        )
    from app.core.crypto import encrypt, key_version, keyed_hash
    from app.models.registration import (
        AuthSession,
        Consent,
        StudentProfile,
        StudentRegistration,
        User,
    )

    # S-86/S-87 are private student routes.  Provision a distinct bearer and
    # the same minimum authority graph as production registration so the real
    # browser route guard can discover a canonical server session.  The
    # moderator bearer must never be reused or disguised with a claims header:
    # cookie authority intentionally outranks all fixture headers.
    reporter = session.get(User, REPORTER_ID)
    if reporter is None:
        reporter = User(id=REPORTER_ID, role="student", status="active")
        session.add(reporter)
        created["users"] += 1
    else:
        reporter.role = "student"
        reporter.status = "active"
        reporter.deleted_at = None
    session.flush()

    registration = session.scalar(
        select(StudentRegistration).where(
            StudentRegistration.user_id == REPORTER_ID,
            StudentRegistration.deleted_at.is_(None),
        )
    )
    if registration is None:
        mobile = "8888880086"
        dob = "2000-01-01"
        mobile_ct = encrypt(mobile)
        registration = StudentRegistration(
            id=REPORTER_REGISTRATION_ID,
            user_id=REPORTER_ID,
            first_name="Reporting",
            middle_name=None,
            last_name="Fixture",
            mobile_hash=keyed_hash(mobile),
            mobile_ct=mobile_ct,
            dob_hash=keyed_hash(dob),
            dob_ct=encrypt(dob),
            dob_hash_state="verified",
            key_version=key_version(mobile_ct),
            institution_ref="WAVE4-QA",
            status="active",
            is_minor=False,
            idempotency_key="wave4-reporting-e2e-registration",
            idempotency_key_legacy=True,
        )
        session.add(registration)
        created["student_registrations"] += 1
    else:
        registration.status = "active"
        registration.is_minor = False
        registration.deleted_at = None
    session.flush()

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
        created["student_profiles"] += 1
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
                policy_version="wave4-reporting-browser-v1",
                accepted_at=now,
            )
        )
        created["student_consents"] += 1
    else:
        consent.accepted = True
        consent.policy_version = "wave4-reporting-browser-v1"
        consent.accepted_at = now
        consent.deleted_at = None

    student_token_hash = keyed_hash(raw_student_session_token)
    for prior in session.scalars(
        select(AuthSession).where(
            AuthSession.user_id == REPORTER_ID,
            AuthSession.status == "active",
        )
    ).all():
        if prior.token_hash != student_token_hash:
            prior.status = "revoked"
            prior.revoked_at = now
    student_auth = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == student_token_hash)
    )
    if student_auth is None:
        session.add(
            AuthSession(
                user_id=REPORTER_ID,
                token_hash=student_token_hash,
                status="active",
                expires_at=now + timedelta(hours=4),
                last_seen_at=now,
            )
        )
        created["sessions"] += 1
    else:
        student_auth.user_id = REPORTER_ID
        student_auth.status = "active"
        student_auth.expires_at = now + timedelta(hours=4)
        student_auth.last_seen_at = now
        student_auth.revoked_at = None
        student_auth.deleted_at = None


def provision(
    session: Session,
    raw_session_token: str,
    raw_student_session_token: str | None = None,
) -> dict[str, int]:
    if len(raw_session_token) < 32:
        raise RuntimeError("WAVE4_E2E_SESSION_TOKEN must contain at least 32 characters")
    _assert_distinct_session_tokens(raw_session_token, raw_student_session_token)
    from app.core.crypto import encrypt, key_version, keyed_hash
    from app.models.registration import AuthSession, User
    from app.models.wave4 import (
        InternshipReport,
        InternshipReportCategory,
        InternshipReportEvidence,
        ModerationCase,
        ModerationHandoff,
        ReporterIdentityVault,
    )

    created = {
        "users": 0,
        "sessions": 0,
        "student_registrations": 0,
        "student_profiles": 0,
        "student_consents": 0,
        "reports": 0,
        "cases": 0,
    }
    moderator = session.get(User, MODERATOR_ID)
    if moderator is None:
        moderator = User(id=MODERATOR_ID, role="moderator", status="active")
        session.add(moderator)
        created["users"] += 1
    else:
        moderator.role = "moderator"
        moderator.status = "active"
    # The seed must also work on a genuinely empty PostgreSQL database.  Flush
    # the principal before looking up or inserting its session so the FK order
    # never depends on dialect-specific unit-of-work ordering.
    session.flush()

    now = datetime.now(timezone.utc)
    token_hash = keyed_hash(raw_session_token)
    auth = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if auth is None:
        session.add(AuthSession(
            user_id=MODERATOR_ID, token_hash=token_hash, status="active",
            expires_at=now + timedelta(hours=4), last_seen_at=now,
        ))
        created["sessions"] += 1
    else:
        auth.status = "active"
        auth.expires_at = now + timedelta(hours=4)
        auth.revoked_at = None

    if raw_student_session_token is not None:
        _provision_student_browser_authority(
            session,
            raw_student_session_token,
            now,
            created,
        )

    for index, (report_id, reporter_id) in enumerate(zip(REPORT_IDS, REPORTER_IDS, strict=True)):
        approved = index < 3
        report = session.get(InternshipReport, report_id)
        if report is None:
            report = InternshipReport(
                id=report_id, organisation_name="Nyaya Legal Foundation",
                listing_application_ref=f"W4-MOD-{index + 1:02d}",
                experience_start_date=date.today() - timedelta(days=90 + index),
                experience_end_date=date.today() - timedelta(days=60 + index),
                narrative=("The placement safety briefing was incomplete and the working conditions "
                           f"were documented privately for independent moderation case {index + 1}."),
                privacy_mode="anonymous", status="approved" if approved else "moderation_pending",
                idempotency_key=f"wave4-moderation-e2e-report-{index + 1}", version=2,
                support_guidance_required=True, submitted_at=now,
            )
            session.add(report)
            session.flush()
            created["reports"] += 1
        if session.scalar(select(InternshipReportCategory).where(
            InternshipReportCategory.report_id == report_id,
            InternshipReportCategory.category == "unsafe_environment",
        )) is None:
            session.add(InternshipReportCategory(report_id=report_id, category="unsafe_environment"))
        if session.scalar(select(InternshipReportEvidence).where(
            InternshipReportEvidence.report_id == report_id,
            InternshipReportEvidence.scan_state == "clean",
        )) is None:
            session.add(InternshipReportEvidence(
                report_id=report_id,
                object_ref=f"wave4-e2e/{report_id}",
                mime_type="application/pdf",
                size_bytes=1024,
                checksum_sha256=f"{index + 1:064x}",
                scan_state="clean",
                scanner_result_code="fixture_clean",
                retention_policy="configured",
            ))
        if session.scalar(select(ReporterIdentityVault).where(ReporterIdentityVault.report_id == report_id)) is None:
            reporter_ct = encrypt(str(reporter_id))
            session.add(ReporterIdentityVault(
                report_id=report_id, reporter_lookup_hash=keyed_hash(str(reporter_id), lower=True),
                reporter_ciphertext=reporter_ct, key_version=key_version(reporter_ct),
            ))
        if session.scalar(select(ModerationHandoff).where(ModerationHandoff.report_id == report_id)) is None:
            session.add(ModerationHandoff(
                report_id=report_id, state="approved" if approved else "pending",
                assigned_moderator_user_id=MODERATOR_ID if approved else None, version=1,
            ))
        if session.scalar(select(ModerationCase).where(ModerationCase.report_id == report_id)) is None:
            session.add(ModerationCase(
                report_id=report_id, state="approved_aggregate_only" if approved else "pending",
                assigned_moderator_user_id=MODERATOR_ID if approved else None,
                claimed_at=now if approved else None, version=1,
            ))
            created["cases"] += 1
    session.flush()
    return created


def main() -> int:
    database_url = os.getenv("DATABASE_URL", "")
    token = os.getenv("WAVE4_E2E_SESSION_TOKEN", "")
    student_token = os.getenv("WAVE4_E2E_STUDENT_SESSION_TOKEN", "")
    try:
        assert_isolated_target(database_url)
        if not token:
            raise RuntimeError("WAVE4_E2E_SESSION_TOKEN is required")
        if not student_token:
            raise RuntimeError("WAVE4_E2E_STUDENT_SESSION_TOKEN is required")
        _assert_distinct_session_tokens(token, student_token)
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        created = provision(session, token, student_token)
        session.commit()
    print(
        f"seed_wave4_moderation_e2e: {created}; "
        "raw_session_tokens=NOT_LOGGED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
