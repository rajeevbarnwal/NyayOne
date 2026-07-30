"""Deterministic local seed for the Wave 2 tutoring vertical (SAATHI-123/127 P2).

Same contract as ``scripts/seed_e2e_actors`` / ``scripts/seed_wave3_e2e``:

* **Deterministic.** Every id is a fixed UUID (or a ``uuid5`` derived from a
  stable name), so a browser journey, a fixture and a bug report all refer to
  the same rows on any machine.
* **Idempotent.** Re-running reconciles the existing rows instead of creating
  duplicates; every natural key is guarded by a UNIQUE constraint anyway
  (``uq_tutor_profiles_user_id``, ``uq_tutor_subjects_tutor_subject_level``,
  ``uq_tutor_availability_slots_start``).
* **Offline.** No scraping, no live provider, no network. Tutor facts are marked
  ``source='seed_fixture'`` so a seeded claim can never be mistaken for a
  verified, provenance-carrying one.
* **No commit.** The caller owns the transaction, exactly like the services.

Instants: slot starts are computed from an explicit UTC anchor and the slot's
retained IANA zone is stored alongside, matching the frozen time model. The
default zone (``Asia/Kolkata``) has no DST, so the fixture never depends on a
DST policy; :func:`dst_probe_slots` exists for the tests that DO exercise the
ambiguous / non-existent local times, in ``America/New_York``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.registration import User
from app.models.wave2 import TutorAvailabilitySlot, TutorProfile, TutorSubject
from app.services.tutoring import availability

#: Namespace for derived ids. Fixed forever: changing it renames every row.
SEED_NAMESPACE = uuid.UUID("00000000-0000-4000-8000-000000000123")
#: Anchor for the fixture calendar. Callers pass ``now`` for relative slots.
DEFAULT_TIMEZONE = availability.DEFAULT_TIMEZONE
SEED_SOURCE = "seed_fixture"
SLOT_MINUTES = 60


def _id(name: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, name)


@dataclass(frozen=True)
class SeedTutor:
    """One fixture tutor: account + profile + subjects."""

    key: str
    display_name: str
    headline: str
    experience_years: int
    subjects: tuple[tuple[str, str], ...]
    verified_identity: bool = True
    verified_credentials: bool = True
    status: str = "active"
    iana_timezone: str = DEFAULT_TIMEZONE

    @property
    def user_id(self) -> uuid.UUID:
        return _id(f"user:{self.key}")

    @property
    def tutor_id(self) -> uuid.UUID:
        return _id(f"tutor:{self.key}")


#: The frozen fixture cast. Deliberately small, deliberately varied (ratings are
#: NOT seeded: a rating may only ever come from a published review).
SEED_TUTORS: tuple[SeedTutor, ...] = (
    SeedTutor(
        key="constitutional",
        display_name="Adv. Meera Iyer",
        headline="Constitutional law and moot preparation",
        experience_years=11,
        subjects=(("Constitutional Law", "advanced"), ("Moot Court", "intermediate")),
    ),
    SeedTutor(
        key="contracts",
        display_name="Adv. Rohan Deshpande",
        headline="Contracts and drafting clinics",
        experience_years=6,
        subjects=(("Contract Law", "beginner"), ("Legal Drafting", "intermediate")),
    ),
    SeedTutor(
        key="criminal",
        display_name="Adv. Fatima Sheikh",
        headline="Criminal procedure and trial advocacy",
        experience_years=14,
        subjects=(("Criminal Law", "advanced"),),
        verified_credentials=False,
    ),
)

#: A seeded student so a hold/booking journey has an actor.
SEED_STUDENT_ID = _id("user:student")


@dataclass
class SeedReport:
    """Counts only — a seed report is operator output, never PII."""

    users: int = 0
    tutors: int = 0
    subjects: int = 0
    slots: int = 0
    tutor_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "users": self.users,
            "tutors": self.tutors,
            "subjects": self.subjects,
            "slots": self.slots,
            "tutor_ids": list(self.tutor_ids),
        }


def _ensure_user(session: Session, user_id: uuid.UUID, role: str) -> int:
    user = session.get(User, user_id)
    if user is not None:
        user.status = "active"
        user.deleted_at = None
        return 0
    # Tutors sign in as 'lawyer' accounts: USER_ROLES has no 'tutor' member, and
    # the tutor identity lives on tutor_profiles.
    session.add(User(id=user_id, role=role, status="active"))
    session.flush()
    return 1


def slot_starts(
    anchor_utc: datetime, *, days: int = 3, per_day: int = 2
) -> list[datetime]:
    """Deterministic future slot starts: 10:00 and 15:00 UTC on the next N days."""
    if anchor_utc.tzinfo is None:
        anchor_utc = anchor_utc.replace(tzinfo=timezone.utc)
    hours = (10, 15, 18, 20)[:per_day]
    base = anchor_utc.replace(minute=0, second=0, microsecond=0)
    starts: list[datetime] = []
    for day in range(1, days + 1):
        for hour in hours:
            starts.append((base + timedelta(days=day)).replace(hour=hour))
    return starts


def provision(
    session: Session,
    *,
    now: datetime | None = None,
    days: int = 3,
    per_day: int = 2,
) -> SeedReport:
    """Create/reconcile the fixture tutors, subjects and availability. No commit."""
    now = now or datetime.now(timezone.utc)
    report = SeedReport()
    report.users += _ensure_user(session, SEED_STUDENT_ID, "student")

    for spec in SEED_TUTORS:
        report.users += _ensure_user(session, spec.user_id, "lawyer")
        profile = session.get(TutorProfile, spec.tutor_id)
        if profile is None:
            profile = TutorProfile(
                id=spec.tutor_id,
                user_id=spec.user_id,
                display_name=spec.display_name,
                headline=spec.headline,
                experience_years=spec.experience_years,
                verified_identity=spec.verified_identity,
                verified_credentials=spec.verified_credentials,
                source=SEED_SOURCE,
                retrieved_at=now,
                status=spec.status,
            )
            session.add(profile)
            report.tutors += 1
        else:
            profile.display_name = spec.display_name
            profile.headline = spec.headline
            profile.experience_years = spec.experience_years
            profile.verified_identity = spec.verified_identity
            profile.verified_credentials = spec.verified_credentials
            profile.source = SEED_SOURCE
            profile.retrieved_at = now
            profile.status = spec.status
            profile.deleted_at = None
        session.flush()

        for subject, level in spec.subjects:
            exists = session.scalars(
                select(TutorSubject).where(
                    TutorSubject.tutor_id == spec.tutor_id,
                    TutorSubject.subject == subject,
                    TutorSubject.level == level,
                )
            ).first()
            if exists is None:
                session.add(
                    TutorSubject(
                        id=_id(f"subject:{spec.key}:{subject}:{level}"),
                        tutor_id=spec.tutor_id,
                        subject=subject,
                        level=level,
                    )
                )
                report.subjects += 1
        session.flush()

        for start_utc in slot_starts(now, days=days, per_day=per_day):
            exists = session.scalars(
                select(TutorAvailabilitySlot).where(
                    TutorAvailabilitySlot.tutor_id == spec.tutor_id,
                    TutorAvailabilitySlot.start_utc == start_utc,
                )
            ).first()
            if exists is not None:
                continue
            session.add(
                TutorAvailabilitySlot(
                    id=_id(f"slot:{spec.key}:{start_utc.isoformat()}"),
                    tutor_id=spec.tutor_id,
                    start_utc=start_utc,
                    end_utc=start_utc + timedelta(minutes=SLOT_MINUTES),
                    iana_timezone=spec.iana_timezone,
                    status="available",
                )
            )
            report.slots += 1
        session.flush()
        report.tutor_ids.append(str(spec.tutor_id))
    return report


# --------------------------------------------------------------------------- #
# DST probe fixtures (used by the timezone tests, not by the browser journeys)
# --------------------------------------------------------------------------- #

#: Local wall times that DO NOT exist / happen TWICE in America/New_York 2026.
DST_ZONE = "America/New_York"
DST_NONEXISTENT_LOCAL = datetime(2026, 3, 8, 2, 30)  # spring forward: never happens
DST_AMBIGUOUS_LOCAL = datetime(2026, 11, 1, 1, 30)  # fall back: happens twice


def dst_probe_slots(
    session: Session,
    tutor_id: uuid.UUID,
    *,
    zone_name: str = DST_ZONE,
) -> dict[str, TutorAvailabilitySlot]:
    """Create one slot at an ambiguous and one at a non-existent local time.

    The stored instant comes from ``availability.resolve_local_instant``, so the
    frozen DST policy (earlier fold for ambiguous, push forward past the gap for
    non-existent) is what lands in the database — and the IANA zone is retained
    on the row so the label can be re-rendered.
    """
    created: dict[str, TutorAvailabilitySlot] = {}
    for label, local in (
        ("ambiguous", DST_AMBIGUOUS_LOCAL),
        ("nonexistent", DST_NONEXISTENT_LOCAL),
    ):
        resolved = availability.resolve_local_instant(local, zone_name)
        row = TutorAvailabilitySlot(
            id=_id(f"dst:{label}:{zone_name}:{local.isoformat()}"),
            tutor_id=tutor_id,
            start_utc=resolved.instant_utc,
            end_utc=resolved.instant_utc + timedelta(minutes=SLOT_MINUTES),
            iana_timezone=zone_name,
            status="available",
        )
        session.add(row)
        created[label] = row
    session.flush()
    return created
