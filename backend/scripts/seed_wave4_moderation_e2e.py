"""Isolated-runtime-only SAATHI-274 browser fixture.

This script refuses to run unless APP_ENV is testing, an explicit seed flag is
present, and the database name/path visibly denotes an isolated QA database.
The raw opaque session token comes from the process environment, is stored only
as a keyed hash, and is never printed or written to evidence.
"""
from __future__ import annotations

import os
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
REPORT_IDS = tuple(uuid.UUID(f"00000000-0000-4000-8000-{2740 + index:012d}") for index in range(4))
REPORTER_IDS = tuple(uuid.UUID(f"00000000-0000-4000-8000-{8600 + index:012d}") for index in range(4))


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


def provision(session: Session, raw_session_token: str) -> dict[str, int]:
    if len(raw_session_token) < 32:
        raise RuntimeError("WAVE4_E2E_SESSION_TOKEN must contain at least 32 characters")
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

    created = {"users": 0, "sessions": 0, "reports": 0, "cases": 0}
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
    try:
        assert_isolated_target(database_url)
        if not token:
            raise RuntimeError("WAVE4_E2E_SESSION_TOKEN is required")
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        created = provision(session, token)
        session.commit()
    print(f"seed_wave4_moderation_e2e: {created}; raw_session_token=NOT_LOGGED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
