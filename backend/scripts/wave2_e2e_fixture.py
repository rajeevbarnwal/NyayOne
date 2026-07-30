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

Usage (from ``backend/``, with the same ``DATABASE_URL`` the server will use):

    python scripts/wave2_e2e_fixture.py seed --extra-tutors 12
    python scripts/wave2_e2e_fixture.py expire-hold <hold_id>
    python scripts/wave2_e2e_fixture.py shift-session <session_id> --minutes -95
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parents[1]
if str(REPO_BACKEND) not in sys.path:
    sys.path.insert(0, str(REPO_BACKEND))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import get_sessionmaker  # noqa: E402
from app.models.registration import User  # noqa: E402
from app.models.wave2 import (  # noqa: E402
    BookingHold,
    TutorAvailabilitySlot,
    TutorProfile,
    TutorSubject,
    TutoringSession,
)
from app.services.tutoring import seed as tutoring_seed  # noqa: E402

#: The sub the production frontend sends in `X-Actor-Claims`.
BROWSER_STUDENT_ID = uuid.UUID("00000000-0000-4000-8000-0000000000de")
#: A second student, so "someone else won the slot" is a real second actor.
RIVAL_STUDENT_ID = uuid.UUID("00000000-0000-4000-8000-0000000000b2")
#: Admin actor for moderation / audited exception rows.
ADMIN_ACTOR_ID = uuid.UUID("00000000-0000-4000-8000-00000000ad01")
#: Namespace for the extra pagination tutors. Fixed forever.
EXTRA_NAMESPACE = uuid.UUID("00000000-0000-4000-8000-000000000128")


def _ensure_user(session: Session, user_id: uuid.UUID, role: str) -> int:
    user = session.get(User, user_id)
    if user is not None:
        user.status = "active"
        user.deleted_at = None
        return 0
    session.add(User(id=user_id, role=role, status="active"))
    session.flush()
    return 1


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
    maker = get_sessionmaker()
    with maker() as session:
        report = tutoring_seed.provision(session, now=now, days=args.days, per_day=args.per_day)
        _ensure_user(session, BROWSER_STUDENT_ID, "student")
        _ensure_user(session, RIVAL_STUDENT_ID, "student")
        _ensure_user(session, ADMIN_ACTOR_ID, "student")
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
            "rival_student": str(RIVAL_STUDENT_ID),
            "admin": str(ADMIN_ACTOR_ID),
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
    maker = get_sessionmaker()
    with maker() as session:
        hold = session.get(BookingHold, uuid.UUID(args.hold_id))
        if hold is None:
            print(json.dumps({"error": "hold_not_found", "hold_id": args.hold_id}))
            return 3
        before = hold.expires_at.isoformat()
        hold.expires_at = datetime.now(timezone.utc) - timedelta(seconds=args.seconds_ago)
        session.commit()
        print(
            json.dumps(
                {
                    "hold_id": args.hold_id,
                    "status": hold.status,
                    "expires_at_before": before,
                    "expires_at_after": hold.expires_at.isoformat(),
                    "mechanism": "clock_shift_on_hold_row",
                }
            )
        )
    return 0


def cmd_shift_session(args: argparse.Namespace) -> int:
    delta = timedelta(minutes=args.minutes)
    maker = get_sessionmaker()
    with maker() as session:
        row = session.get(TutoringSession, uuid.UUID(args.session_id))
        if row is None:
            print(json.dumps({"error": "session_not_found", "session_id": args.session_id}))
            return 3
        before = (row.start_utc.isoformat(), row.end_utc.isoformat())
        row.start_utc = row.start_utc + delta
        row.end_utc = row.end_utc + delta
        slot = session.get(TutorAvailabilitySlot, row.slot_id)
        if slot is not None:
            slot.start_utc = slot.start_utc + delta
            slot.end_utc = slot.end_utc + delta
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
                    "now_utc": datetime.now(timezone.utc).isoformat(),
                    "mechanism": "clock_shift_on_session_and_slot_rows",
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

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
