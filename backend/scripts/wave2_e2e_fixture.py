"""Wave 2 tutoring browser-gate fixture and clock helper (SAATHI-124/128, matrix I1/I2/J1).

This is QA plumbing for `scripts/wave2_tutoring_browser_gate.sh`. It is NOT
imported by the application and it changes no production behaviour. Three jobs,
each an explicit subcommand so nothing happens implicitly:

``seed``
    Provision the deterministic tutoring fixture
    (:mod:`app.services.tutoring.seed`) plus the actors the *browser* needs:

    * the student the production frontend authenticates as
      (``00000000-0000-4000-8000-0000000000de``, the ``DEV_ACTOR_CLAIMS`` sub in
      ``frontend/src/features/student/lib/tutoringApi.ts``) — the packaged seed
      creates its own student, which no browser can act as;
    * a rival student used to prove the one-winner slot race in the browser;
    * a DEDICATED review-rate-limit student
      (``00000000-0000-4000-8000-000000004400``) whose ONLY purpose is to
      measure the ``RATE_LIMIT_REVIEW_PER_HOUR`` boundary in N44. It exists
      because the boundary must be measured on an UNSPENT budget: N44 used to
      reuse the rival student, whom N34/N35 had already charged two review
      mutations, so the run reported "last admitted 198, first rejected 199"
      against a configured limit of 200 — a wrong number that still looks
      plausible. No other case may spend this actor's review budget;
    * an admin actor (``review_moderation`` / ``session_cancellations`` carry
      FKs to ``users``);
    * ``--extra-tutors N`` additional published profiles, because S-31 pages at
      10 and the packaged cast is 3, so pagination is otherwise unreachable.

    Emits one JSON document on stdout: ids, and every slot bucketed by how far
    it is from ``now`` (``gt24h`` / ``lt24h``), so the browser driver never has
    to guess which slot exercises which policy branch.

``expire-hold``
    Move a live hold's ``expires_at`` into the past. The hold row is otherwise
    untouched, so the server's own expiry predicate is what the browser then
    observes. This stands in for waiting out ``BOOKING_HOLD_MINUTES`` and is
    reported as a clock shift, never as elapsed wall time.

``shift-session``
    Move a confirmed session (and its slot) by N minutes, so completion and
    attendance — which the server refuses before ``end_utc`` — can be reached
    without a 60 minute wait. Again: a clock shift, declared as one.

``expire-grant`` / ``revoke-grant``
    Put a live video grant into the ``GRANT_EXPIRED`` / ``GRANT_REVOKED`` state
    the browser cannot reach in a 5-minute TTL. ``expire-grant`` moves
    ``expires_at`` into the past and touches nothing else, so the server's own
    expiry predicate is what refuses the join; ``revoke-grant`` sets
    ``revoked_at``, which is the same column the domain's ``revoke()`` writes.

``age-review``
    Move a review's ``edit_deadline_at`` (and ``created_at``) by N seconds, so
    the 7-day edit boundary can be tested from both sides without waiting a
    week. The window is DATA on the row, so shifting the row is exactly what a
    week of real time would do.

``fail-outbox``
    Mark the newest ``tutoring_outbox`` row for a session as a FAILED delivery
    attempt (``status='failed'``, ``attempts+1``) without touching any domain
    row. This is the post-commit dispatch failure the relay is designed to
    survive; the point of the assertion afterwards is that the DOMAIN mutation
    is unchanged and the row is still retryable.

Usage (from ``backend/``, with the same ``DATABASE_URL`` the server will use):

    python scripts/wave2_e2e_fixture.py seed --extra-tutors 12
    python scripts/wave2_e2e_fixture.py expire-hold <hold_id>
    python scripts/wave2_e2e_fixture.py shift-session <session_id> --minutes -95
    python scripts/wave2_e2e_fixture.py expire-grant <session_id>
    python scripts/wave2_e2e_fixture.py revoke-grant <session_id>
    python scripts/wave2_e2e_fixture.py age-review <review_id> --seconds 604805
    python scripts/wave2_e2e_fixture.py fail-outbox <session_id>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parents[1]
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from sqlalchemy import select  # noqa: E402
from sqlalchemy import event as sa_event  # noqa: E402
from sqlalchemy import text as sa_text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import get_sessionmaker  # noqa: E402
from app.core.crypto import encrypt, key_version, keyed_hash  # noqa: E402
from app.models.registration import (  # noqa: E402
    AuthSession,
    Consent,
    StudentProfile,
    StudentRegistration,
    User,
)
from app.models.wave2 import (  # noqa: E402
    BookingHold,
    TutoringOutbox,
    TutorAvailabilitySlot,
    TutorProfile,
    TutorReview,
    TutorSubject,
    TutoringSession,
    VideoSessionGrant,
)
from app.services.tutoring import seed as tutoring_seed  # noqa: E402

#: The student identity resolved from the fixture-only HttpOnly session cookie.
BROWSER_STUDENT_ID = uuid.UUID("00000000-0000-4000-8000-0000000000de")
BROWSER_REGISTRATION_ID = uuid.UUID("00000000-0000-4000-8000-00000000de01")
#: A second student, so "someone else won the slot" is a real second actor.
RIVAL_STUDENT_ID = uuid.UUID("00000000-0000-4000-8000-0000000000b2")
#: The DEDICATED review-rate-limit actor (N44) — single purpose, and the purpose
#: is in the name. ``rate_limit_review_per_hour`` buckets per user id, so the
#: only way to measure the boundary honestly is from an identity whose bucket
#: NOTHING else has touched. The rival student cannot be that identity: N34/N35
#: charge it two ``PATCH /tutoring/reviews/{id}`` calls, which is precisely why
#: N44 reported 198/199 against a configured 200. Nothing but N44 may issue a
#: review mutation as this id.
REVIEW_LIMIT_STUDENT_ID = uuid.UUID("00000000-0000-4000-8000-000000004400")
#: Admin actor for moderation / audited exception rows.
ADMIN_ACTOR_ID = uuid.UUID("00000000-0000-4000-8000-00000000ad01")
#: Namespace for the extra pagination tutors. Fixed forever.
EXTRA_NAMESPACE = uuid.UUID("00000000-0000-4000-8000-000000000128")


@contextmanager
def open_session():
    """A session whose connection will WAIT for the running server's writes.

    These commands run while a real uvicorn is serving the same SQLite file, so
    a write can legitimately arrive mid-transaction. Without a busy timeout the
    driver sees a spurious "database is locked" and reports a PASSING product
    behaviour as a harness failure. Waiting is correct: the lock is held for
    milliseconds, and refusing to wait is what makes the gate flaky.
    """
    maker = get_sessionmaker()
    bind = maker.kw.get("bind") if hasattr(maker, "kw") else None
    is_sqlite = bind is not None and bind.dialect.name == "sqlite"
    if is_sqlite and not getattr(bind, "_wave2_busy_timeout", False):
        # The PRAGMA has to be issued on the RAW connection as it is handed out:
        # setting it from inside an already-open transaction is too late, which
        # is exactly why the first attempt at this still saw "database is locked".
        @sa_event.listens_for(bind, "connect")
        def _busy_timeout(dbapi_connection, _record):  # pragma: no cover - QA plumbing
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA busy_timeout = 20000")
            finally:
                cursor.close()

        bind._wave2_busy_timeout = True
        # Drop any connection that was already pooled without the pragma.
        bind.dispose()
    session = maker()
    try:
        if is_sqlite:
            session.execute(sa_text("PRAGMA busy_timeout = 20000"))
        yield session
    finally:
        session.close()


def _ensure_user(session: Session, user_id: uuid.UUID, role: str) -> int:
    user = session.get(User, user_id)
    if user is not None:
        user.role = role
        user.status = "active"
        user.deleted_at = None
        return 0
    session.add(User(id=user_id, role=role, status="active"))
    session.flush()
    return 1


def _ensure_admin_session(
    session: Session,
    admin_session_token: str,
    now: datetime,
) -> None:
    """Seed only the keyed hash for the isolated M-01 administrator bearer."""

    if len(admin_session_token) < 32:
        raise RuntimeError(
            "WAVE2_E2E_ADMIN_SESSION_TOKEN must contain at least 32 characters"
        )
    token_hash = keyed_hash(admin_session_token)
    for prior in session.scalars(
        select(AuthSession).where(
            AuthSession.user_id == ADMIN_ACTOR_ID,
            AuthSession.status == "active",
        )
    ).all():
        if prior.token_hash != token_hash:
            prior.status = "revoked"
            prior.revoked_at = now
    row = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash)
    )
    if row is None:
        session.add(
            AuthSession(
                user_id=ADMIN_ACTOR_ID,
                token_hash=token_hash,
                status="active",
                expires_at=now + timedelta(hours=4),
                last_seen_at=now,
            )
        )
    else:
        row.user_id = ADMIN_ACTOR_ID
        row.status = "active"
        row.expires_at = now + timedelta(hours=4)
        row.last_seen_at = now
        row.revoked_at = None
        row.deleted_at = None


def _ensure_student_registration_and_session(
    session: Session,
    student_session_token: str,
    now: datetime,
) -> None:
    """Seed genuine student authority while keeping the bearer out of models."""

    if len(student_session_token) < 32:
        raise RuntimeError(
            "WAVE2_E2E_STUDENT_SESSION_TOKEN must contain at least 32 characters"
        )
    mobile = "7000000001"
    dob = "2000-01-01"
    mobile_ct = encrypt(mobile)
    dob_ct = encrypt(dob)
    registration = session.get(StudentRegistration, BROWSER_REGISTRATION_ID)
    if registration is None:
        registration = StudentRegistration(
            id=BROWSER_REGISTRATION_ID,
            user_id=BROWSER_STUDENT_ID,
            first_name="Browser",
            middle_name=None,
            last_name="Fixture",
            mobile_hash=keyed_hash(mobile),
            mobile_ct=mobile_ct,
            dob_hash=keyed_hash(dob),
            dob_ct=dob_ct,
            dob_hash_state="verified",
            key_version=key_version(mobile_ct),
            institution_ref="WAVE2-QA",
            status="active",
            is_minor=False,
        )
        session.add(registration)
        session.flush()
    else:
        registration.user_id = BROWSER_STUDENT_ID
        registration.first_name = "Browser"
        registration.middle_name = None
        registration.last_name = "Fixture"
        registration.mobile_hash = keyed_hash(mobile)
        registration.mobile_ct = mobile_ct
        registration.dob_hash = keyed_hash(dob)
        registration.dob_ct = dob_ct
        registration.dob_hash_state = "verified"
        registration.key_version = key_version(mobile_ct)
        registration.institution_ref = "WAVE2-QA"
        registration.status = "active"
        registration.is_minor = False
        registration.deleted_at = None

    profile = session.scalar(
        select(StudentProfile).where(
            StudentProfile.registration_id == registration.id
        )
    )
    if profile is None:
        session.add(StudentProfile(registration_id=registration.id))

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
                policy_version="wave2-browser-v1",
                accepted_at=now,
            )
        )
    else:
        consent.accepted = True
        consent.policy_version = "wave2-browser-v1"
        consent.accepted_at = now
        consent.deleted_at = None

    token_hash = keyed_hash(student_session_token)
    for prior in session.scalars(
        select(AuthSession).where(
            AuthSession.user_id == BROWSER_STUDENT_ID,
            AuthSession.status == "active",
        )
    ).all():
        if prior.token_hash != token_hash:
            prior.status = "revoked"
            prior.revoked_at = now
    row = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash)
    )
    if row is None:
        session.add(
            AuthSession(
                user_id=BROWSER_STUDENT_ID,
                token_hash=token_hash,
                status="active",
                expires_at=now + timedelta(hours=4),
                last_seen_at=now,
            )
        )
    else:
        row.user_id = BROWSER_STUDENT_ID
        row.status = "active"
        row.expires_at = now + timedelta(hours=4)
        row.last_seen_at = now
        row.revoked_at = None
        row.deleted_at = None


def _extra_tutors(session: Session, count: int, now: datetime) -> list[str]:
    """Deterministic filler profiles so S-31 pagination has more than one page."""
    created: list[str] = []
    for index in range(1, count + 1):
        key = f"qa-page-{index:02d}"
        user_id = uuid.uuid5(EXTRA_NAMESPACE, f"user:{key}")
        tutor_id = uuid.uuid5(EXTRA_NAMESPACE, f"tutor:{key}")
        _ensure_user(session, user_id, "lawyer")
        profile = session.get(TutorProfile, tutor_id)
        display = f"Adv. Pagination Mentor {index:02d}"
        headline = "Fixture profile for S-31 pagination"
        years = 1 + (index % 9)
        if profile is None:
            session.add(
                TutorProfile(
                    id=tutor_id,
                    user_id=user_id,
                    display_name=display,
                    headline=headline,
                    experience_years=years,
                    verified_identity=index % 2 == 0,
                    verified_credentials=index % 3 == 0,
                    source=tutoring_seed.SEED_SOURCE,
                    retrieved_at=now,
                    status="active",
                )
            )
        else:
            profile.display_name = display
            profile.headline = headline
            profile.experience_years = years
            profile.status = "active"
            profile.deleted_at = None
        session.flush()
        exists = session.scalars(
            select(TutorSubject).where(
                TutorSubject.tutor_id == tutor_id,
                TutorSubject.subject == "Legal Research",
                TutorSubject.level == "beginner",
            )
        ).first()
        if exists is None:
            session.add(
                TutorSubject(
                    tutor_id=tutor_id,
                    subject="Legal Research",
                    level="beginner",
                )
            )
        created.append(str(tutor_id))
    return created


def _slot_rows(session: Session, tutor_ids: list[str], now: datetime) -> list[dict]:
    rows = session.scalars(
        select(TutorAvailabilitySlot)
        .where(TutorAvailabilitySlot.tutor_id.in_([uuid.UUID(t) for t in tutor_ids]))
        .order_by(TutorAvailabilitySlot.start_utc)
    ).all()
    out: list[dict] = []
    for slot in rows:
        start = slot.start_utc
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        hours = round((start - now).total_seconds() / 3600.0, 3)
        out.append(
            {
                "slot_id": str(slot.id),
                "tutor_id": str(slot.tutor_id),
                "start_utc": start.isoformat(),
                "end_utc": (
                    slot.end_utc.replace(tzinfo=timezone.utc)
                    if slot.end_utc.tzinfo is None
                    else slot.end_utc
                ).isoformat(),
                "iana_timezone": slot.iana_timezone,
                "status": slot.status,
                "hours_from_now": hours,
                "bucket": "gt24h" if hours >= 24.0 else ("lt24h" if hours > 0 else "past"),
            }
        )
    return out


def cmd_seed(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    admin_session_token = os.getenv("WAVE2_E2E_ADMIN_SESSION_TOKEN", "")
    student_session_token = os.getenv("WAVE2_E2E_STUDENT_SESSION_TOKEN", "")
    with open_session() as session:
        report = tutoring_seed.provision(session, now=now, days=args.days, per_day=args.per_day)
        _ensure_user(session, BROWSER_STUDENT_ID, "student")
        _ensure_user(session, RIVAL_STUDENT_ID, "student")
        _ensure_user(session, REVIEW_LIMIT_STUDENT_ID, "student")
        _ensure_user(session, ADMIN_ACTOR_ID, "admin")
        session.flush()
        _ensure_admin_session(session, admin_session_token, now)
        _ensure_student_registration_and_session(session, student_session_token, now)
        extra = _extra_tutors(session, args.extra_tutors, now)
        session.commit()
        seeded = report.as_dict()
        slots = _slot_rows(session, seeded["tutor_ids"], now)
    payload = {
        "generated_at": now.isoformat(),
        "seed": seeded,
        "extra_tutor_ids": extra,
        "tutor_total": len(seeded["tutor_ids"]) + len(extra),
        "actors": {
            "browser_student": str(BROWSER_STUDENT_ID),
            "browser_student_session": "seeded_hashed_only",
            "rival_student": str(RIVAL_STUDENT_ID),
            # Named, not derived: the driver REFUSES to run N44 if this key is
            # absent, so an old fixture cannot silently send it back to the
            # rival student and back to measuring 198 instead of 200.
            "review_rate_limit_student": str(REVIEW_LIMIT_STUDENT_ID),
            "admin": str(ADMIN_ACTOR_ID),
            "admin_session": "seeded_hashed_only",
            "seed_student": str(tutoring_seed.SEED_STUDENT_ID),
            "tutor_user_ids": {
                spec.key: str(spec.user_id) for spec in tutoring_seed.SEED_TUTORS
            },
            "tutor_profile_ids": {
                spec.key: str(spec.tutor_id) for spec in tutoring_seed.SEED_TUTORS
            },
        },
        "slots": slots,
        "buckets": {
            "gt24h": [s["slot_id"] for s in slots if s["bucket"] == "gt24h"],
            "lt24h": [s["slot_id"] for s in slots if s["bucket"] == "lt24h"],
        },
    }
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def cmd_expire_hold(args: argparse.Namespace) -> int:
    with open_session() as session:
        hold = session.get(BookingHold, uuid.UUID(args.hold_id))
        if hold is None:
            print(json.dumps({"error": "hold_not_found", "hold_id": args.hold_id}))
            return 3
        now = datetime.now(timezone.utc)

        def aware(value: datetime) -> datetime:
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        created_before = aware(hold.created_at)
        expires_before = aware(hold.expires_at)
        # The row carries its own invariant: `ck_booking_holds_expiry_after_created`
        # requires expires_at > created_at. Moving ONLY expires_at into the past
        # violates it, so the whole row is shifted back as a unit and the TTL
        # interval is preserved exactly. That is what the passage of time would
        # have done, and it leaves the server's own expiry predicate — not this
        # script — to decide that the hold is expired.
        ttl = expires_before - created_before
        hold.expires_at = now - timedelta(seconds=args.seconds_ago)
        hold.created_at = hold.expires_at - ttl
        session.commit()
        print(
            json.dumps(
                {
                    "hold_id": args.hold_id,
                    "status": hold.status,
                    "ttl_preserved_seconds": ttl.total_seconds(),
                    "created_at_before": created_before.isoformat(),
                    "created_at_after": aware(hold.created_at).isoformat(),
                    "expires_at_before": expires_before.isoformat(),
                    "expires_at_after": aware(hold.expires_at).isoformat(),
                    "now_utc": now.isoformat(),
                    "mechanism": "clock_shift_on_hold_row (whole row moved back, TTL interval preserved)",
                }
            )
        )
    return 0


def cmd_shift_session(args: argparse.Namespace) -> int:
    delta = timedelta(minutes=args.minutes)
    with open_session() as session:
        row = session.get(TutoringSession, uuid.UUID(args.session_id))
        if row is None:
            print(json.dumps({"error": "session_not_found", "session_id": args.session_id}))
            return 3
        before = (row.start_utc.isoformat(), row.end_utc.isoformat())
        row.start_utc = row.start_utc + delta
        row.end_utc = row.end_utc + delta
        slot = session.get(TutorAvailabilitySlot, row.slot_id)
        slot_shifted = False
        slot_note = "no slot row"
        if slot is not None:
            target = slot.start_utc + delta
            # `uq_tutor_availability_slots_tutor_start` means a tutor cannot have
            # two slots at the same instant. When several fixture sessions on the
            # SAME tutor are shifted to the same "just ended" moment, the second
            # one would collide. The session rows are what the completion and
            # attendance rules read, so the slot is left alone in that case and
            # the fact is REPORTED rather than papered over with a silent retry.
            clash = session.scalars(
                select(TutorAvailabilitySlot).where(
                    TutorAvailabilitySlot.tutor_id == slot.tutor_id,
                    TutorAvailabilitySlot.start_utc == target,
                    TutorAvailabilitySlot.id != slot.id,
                )
            ).first()
            if clash is None:
                slot.start_utc = target
                slot.end_utc = slot.end_utc + delta
                slot_shifted = True
                slot_note = "slot moved with the session"
            else:
                slot_note = (
                    f"slot NOT moved: tutor {slot.tutor_id} already has a slot at "
                    f"{target.isoformat()} (uq_tutor_availability_slots_tutor_start). "
                    "The session rows carry the times the domain reads."
                )
        session.commit()
        print(
            json.dumps(
                {
                    "session_id": args.session_id,
                    "minutes": args.minutes,
                    "start_before": before[0],
                    "end_before": before[1],
                    "start_after": row.start_utc.isoformat(),
                    "end_after": row.end_utc.isoformat(),
                    "slot_shifted": slot_shifted,
                    "slot_note": slot_note,
                    "now_utc": datetime.now(timezone.utc).isoformat(),
                    "mechanism": "clock_shift_on_session_and_slot_rows",
                }
            )
        )
    return 0


def _live_grants(session: Session, session_id: uuid.UUID) -> list[VideoSessionGrant]:
    return list(
        session.scalars(
            select(VideoSessionGrant)
            .where(VideoSessionGrant.session_id == session_id)
            .order_by(VideoSessionGrant.issued_at.desc())
        ).all()
    )


def cmd_expire_grant(args: argparse.Namespace) -> int:
    """Clock-shift EVERY grant on a session so its TTL has elapsed."""
    now = datetime.now(timezone.utc)
    with open_session() as session:
        grants = _live_grants(session, uuid.UUID(args.session_id))
        if not grants:
            print(json.dumps({"error": "no_grants", "session_id": args.session_id}))
            return 3
        changed = []
        for grant in grants:
            def aware(value: datetime) -> datetime:
                return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

            issued_before = aware(grant.issued_at)
            expires_before = aware(grant.expires_at)
            # Same invariant as the hold: `ck_video_session_grants_expiry_after_issued`
            # requires expires_at > issued_at. The whole grant is moved back as a
            # unit with its TTL preserved, so what expires it is the server's own
            # predicate, not a row this script made self-contradictory.
            ttl = expires_before - issued_before
            grant.expires_at = now - timedelta(seconds=args.seconds_ago)
            grant.issued_at = grant.expires_at - ttl
            changed.append(
                {
                    "grant_id": str(grant.id),
                    "participant_ref": grant.participant_ref,
                    "ttl_preserved_seconds": ttl.total_seconds(),
                    "issued_at_before": issued_before.isoformat(),
                    "issued_at_after": aware(grant.issued_at).isoformat(),
                    "expires_at_before": expires_before.isoformat(),
                    "expires_at_after": aware(grant.expires_at).isoformat(),
                }
            )
        session.commit()
        print(
            json.dumps(
                {
                    "session_id": args.session_id,
                    "grants": changed,
                    "mechanism": "clock_shift_on_video_session_grant_rows",
                }
            )
        )
    return 0


def cmd_revoke_grant(args: argparse.Namespace) -> int:
    """Set ``revoked_at`` on every un-revoked grant — the domain's own column."""
    now = datetime.now(timezone.utc)
    with open_session() as session:
        grants = _live_grants(session, uuid.UUID(args.session_id))
        if not grants:
            print(json.dumps({"error": "no_grants", "session_id": args.session_id}))
            return 3
        changed = []
        for grant in grants:
            if grant.revoked_at is not None:
                continue
            grant.revoked_at = now
            changed.append(
                {"grant_id": str(grant.id), "participant_ref": grant.participant_ref}
            )
        session.commit()
        print(
            json.dumps(
                {
                    "session_id": args.session_id,
                    "revoked": changed,
                    "revoked_at": now.isoformat(),
                    "mechanism": "revoked_at_set_on_video_session_grant_rows",
                }
            )
        )
    return 0


def cmd_age_review(args: argparse.Namespace) -> int:
    """Move a review's edit window. The window is DATA on the row.

    Two modes, because the 7-day boundary has to be testable from both sides:

    ``--seconds N``
        age the row by N seconds (deadline and created_at both move back).

    ``--deadline-in-seconds N``
        put the deadline exactly N seconds from NOW — positive for "just inside
        the window", negative or zero for "just outside". This is the mode the
        boundary rows use: ageing by *almost* the whole window leaves the
        deadline a second or two away, and the request itself then takes longer
        than that, which silently turns an inside-the-window case into an
        outside-the-window one.
    """
    with open_session() as session:
        review = session.get(TutorReview, uuid.UUID(args.review_id))
        if review is None:
            print(json.dumps({"error": "review_not_found", "review_id": args.review_id}))
            return 3
        before = review.edit_deadline_at.isoformat()
        if args.deadline_in_seconds is not None:
            target = datetime.now(timezone.utc) + timedelta(seconds=args.deadline_in_seconds)
            delta = (
                review.edit_deadline_at
                if review.edit_deadline_at.tzinfo
                else review.edit_deadline_at.replace(tzinfo=timezone.utc)
            ) - target
        else:
            delta = timedelta(seconds=args.seconds or 0)
        review.edit_deadline_at = review.edit_deadline_at - delta
        review.created_at = review.created_at - delta
        session.commit()
        print(
            json.dumps(
                {
                    "review_id": args.review_id,
                    "seconds": args.seconds,
                    "deadline_in_seconds": args.deadline_in_seconds,
                    "shift_applied_seconds": delta.total_seconds(),
                    "edit_deadline_before": before,
                    "edit_deadline_after": review.edit_deadline_at.isoformat(),
                    "now_utc": datetime.now(timezone.utc).isoformat(),
                    "mechanism": "clock_shift_on_tutor_review_row",
                }
            )
        )
    return 0


def cmd_fail_outbox(args: argparse.Namespace) -> int:
    """Mark the newest outbox row for a session as a failed delivery attempt."""
    now = datetime.now(timezone.utc)
    with open_session() as session:
        row = session.scalars(
            select(TutoringOutbox)
            .where(TutoringOutbox.aggregate_id == uuid.UUID(args.session_id))
            .order_by(TutoringOutbox.created_at.desc())
        ).first()
        if row is None:
            print(json.dumps({"error": "no_outbox_row", "session_id": args.session_id}))
            return 3
        before = {"status": row.status, "attempts": row.attempts}
        row.status = "failed"
        row.attempts = int(row.attempts or 0) + 1
        row.last_error = "e2e_injected_dispatch_failure"
        row.updated_at = now
        session.commit()
        print(
            json.dumps(
                {
                    "outbox_id": str(row.id),
                    "session_id": args.session_id,
                    "kind": row.kind,
                    "before": before,
                    "after": {"status": row.status, "attempts": row.attempts},
                    "mechanism": "post_commit_dispatch_failure_injected_on_outbox_row",
                }
            )
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    seed_p = sub.add_parser("seed", help="provision fixture data and print the id map")
    seed_p.add_argument("--days", type=int, default=3)
    seed_p.add_argument("--per-day", type=int, default=2)
    seed_p.add_argument("--extra-tutors", type=int, default=12)
    seed_p.set_defaults(func=cmd_seed)

    hold_p = sub.add_parser("expire-hold", help="clock-shift a hold's expires_at into the past")
    hold_p.add_argument("hold_id")
    hold_p.add_argument("--seconds-ago", type=int, default=5)
    hold_p.set_defaults(func=cmd_expire_hold)

    shift_p = sub.add_parser("shift-session", help="clock-shift a session and its slot")
    shift_p.add_argument("session_id")
    shift_p.add_argument("--minutes", type=int, required=True)
    shift_p.set_defaults(func=cmd_shift_session)

    exp_g = sub.add_parser("expire-grant", help="clock-shift a session's video grants past their TTL")
    exp_g.add_argument("session_id")
    exp_g.add_argument("--seconds-ago", type=int, default=5)
    exp_g.set_defaults(func=cmd_expire_grant)

    rev_g = sub.add_parser("revoke-grant", help="set revoked_at on a session's video grants")
    rev_g.add_argument("session_id")
    rev_g.set_defaults(func=cmd_revoke_grant)

    age_r = sub.add_parser("age-review", help="move a review's 7-day edit deadline by N seconds")
    age_r.add_argument("review_id")
    age_r.add_argument("--seconds", type=int, default=None)
    age_r.add_argument("--deadline-in-seconds", type=int, default=None,
                       help="put edit_deadline_at exactly N seconds from now (may be negative)")
    age_r.set_defaults(func=cmd_age_review)

    fail_o = sub.add_parser("fail-outbox", help="mark a session's newest outbox row as a failed dispatch")
    fail_o.add_argument("session_id")
    fail_o.set_defaults(func=cmd_fail_outbox)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
