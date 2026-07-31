"""Wave 2 deterministic seed proofs (SAATHI-123/127 P2).

The seed's contract, as documented in ``app.services.tutoring.seed``:

* **Deterministic** — every id is a ``uuid5`` derived from a frozen namespace, so
  a fixture, a browser journey and a bug report name the same rows everywhere;
* **Idempotent** — re-running with the same anchor creates nothing and duplicates
  nothing, it reconciles the rows that already exist;
* **Offline / provenanced** — every fact is marked ``source='seed_fixture'`` and
  no rating is ever seeded (a rating may only come from a published review);
* **No commit** — the caller owns the transaction.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.registration import User
from app.models.wave2 import TutorAvailabilitySlot, TutorProfile, TutorSubject
from app.services.tutoring import availability
from app.services.tutoring import seed as tutoring_seed
from tests.wave2_helpers import T0

pytestmark = pytest.mark.usefixtures("db_session")

#: Derived from the frozen cast, not hard-coded twice.
EXPECTED_TUTORS = len(tutoring_seed.SEED_TUTORS)
EXPECTED_USERS = EXPECTED_TUTORS + 1  # + the seeded student
EXPECTED_SUBJECTS = sum(len(spec.subjects) for spec in tutoring_seed.SEED_TUTORS)


def _counts(db_session) -> dict[str, int]:
    return {
        "users": len(db_session.scalars(select(User)).all()),
        "tutors": len(db_session.scalars(select(TutorProfile)).all()),
        "subjects": len(db_session.scalars(select(TutorSubject)).all()),
        "slots": len(db_session.scalars(select(TutorAvailabilitySlot)).all()),
    }


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_every_seed_id_is_derived_from_the_frozen_namespace():
    assert tutoring_seed.SEED_NAMESPACE == uuid.UUID(
        "00000000-0000-4000-8000-000000000123"
    )
    assert tutoring_seed.SEED_STUDENT_ID == uuid.uuid5(
        tutoring_seed.SEED_NAMESPACE, "user:student"
    )
    for spec in tutoring_seed.SEED_TUTORS:
        assert spec.user_id == uuid.uuid5(
            tutoring_seed.SEED_NAMESPACE, f"user:{spec.key}"
        )
        assert spec.tutor_id == uuid.uuid5(
            tutoring_seed.SEED_NAMESPACE, f"tutor:{spec.key}"
        )
        # Stable across calls: the property is pure.
        assert spec.tutor_id == spec.tutor_id and spec.user_id != spec.tutor_id
    assert len({spec.tutor_id for spec in tutoring_seed.SEED_TUTORS}) == EXPECTED_TUTORS


def test_slot_starts_are_deterministic_and_anchored_in_utc():
    starts = tutoring_seed.slot_starts(T0, days=3, per_day=2)
    assert starts == [
        datetime(2026, 7, 2, 10, tzinfo=timezone.utc),
        datetime(2026, 7, 2, 15, tzinfo=timezone.utc),
        datetime(2026, 7, 3, 10, tzinfo=timezone.utc),
        datetime(2026, 7, 3, 15, tzinfo=timezone.utc),
        datetime(2026, 7, 4, 10, tzinfo=timezone.utc),
        datetime(2026, 7, 4, 15, tzinfo=timezone.utc),
    ]
    # A naive anchor is interpreted as UTC, never as local time.
    assert tutoring_seed.slot_starts(T0.replace(tzinfo=None), days=3, per_day=2) == starts
    # Every start is in the FUTURE relative to the anchor, on the hour.
    assert all(start > T0 for start in starts)
    assert {(s.minute, s.second, s.microsecond) for s in starts} == {(0, 0, 0)}
    assert len(tutoring_seed.slot_starts(T0, days=1, per_day=1)) == 1
    assert len(tutoring_seed.slot_starts(T0, days=4, per_day=4)) == 16


# --------------------------------------------------------------------------- #
# Counts + internal consistency
# --------------------------------------------------------------------------- #


def test_provision_produces_the_expected_counts(db_session):
    report = tutoring_seed.provision(db_session, now=T0, days=3, per_day=2)
    db_session.commit()

    assert report.users == EXPECTED_USERS == 4
    assert report.tutors == EXPECTED_TUTORS == 3
    assert report.subjects == EXPECTED_SUBJECTS == 5
    assert report.slots == EXPECTED_TUTORS * 6 == 18
    assert report.tutor_ids == [str(spec.tutor_id) for spec in tutoring_seed.SEED_TUTORS]
    assert _counts(db_session) == {
        "users": 4, "tutors": 3, "subjects": 5, "slots": 18
    }
    # The report is COUNTS + ids only: never a display name or any other PII.
    blob = repr(report.as_dict())
    assert set(report.as_dict()) == {"users", "tutors", "subjects", "slots", "tutor_ids"}
    for spec in tutoring_seed.SEED_TUTORS:
        assert spec.display_name not in blob


def test_provision_does_not_commit(db_session):
    tutoring_seed.provision(db_session, now=T0, days=1, per_day=1)
    assert _counts(db_session)["tutors"] == EXPECTED_TUTORS
    db_session.rollback()
    assert _counts(db_session) == {"users": 0, "tutors": 0, "subjects": 0, "slots": 0}


def test_every_seeded_profile_and_subject_is_internally_consistent(db_session):
    tutoring_seed.provision(db_session, now=T0, days=3, per_day=2)
    db_session.commit()

    student = db_session.get(User, tutoring_seed.SEED_STUDENT_ID)
    assert (student.role, student.status, student.deleted_at) == (
        "student", "active", None,
    )

    for spec in tutoring_seed.SEED_TUTORS:
        # Tutors sign in as 'lawyer' accounts; the tutor identity is the profile.
        account = db_session.get(User, spec.user_id)
        assert (account.role, account.status) == ("lawyer", "active")

        profile = db_session.get(TutorProfile, spec.tutor_id)
        assert profile.user_id == spec.user_id
        assert profile.display_name == spec.display_name
        assert profile.headline == spec.headline
        assert profile.experience_years == spec.experience_years
        assert profile.verified_identity is spec.verified_identity
        assert profile.verified_credentials is spec.verified_credentials
        assert profile.status == spec.status == "active"
        # Provenance: a seeded claim can never be mistaken for a verified one.
        assert profile.source == tutoring_seed.SEED_SOURCE == "seed_fixture"
        assert profile.retrieved_at is not None
        # Ratings are NEVER seeded: only a published review may create one.
        assert (profile.rating_avg, profile.rating_count) == (None, 0)

        subjects = db_session.scalars(
            select(TutorSubject).where(TutorSubject.tutor_id == spec.tutor_id)
        ).all()
        assert {(s.subject, s.level) for s in subjects} == set(spec.subjects)
        for row in subjects:
            assert row.id == uuid.uuid5(
                tutoring_seed.SEED_NAMESPACE,
                f"subject:{spec.key}:{row.subject}:{row.level}",
            )


def test_every_seeded_slot_is_internally_consistent(db_session):
    tutoring_seed.provision(db_session, now=T0, days=3, per_day=2)
    db_session.commit()
    expected_starts = set(tutoring_seed.slot_starts(T0, days=3, per_day=2))

    for spec in tutoring_seed.SEED_TUTORS:
        slots = db_session.scalars(
            select(TutorAvailabilitySlot).where(
                TutorAvailabilitySlot.tutor_id == spec.tutor_id
            )
        ).all()
        assert len(slots) == len(expected_starts)
        starts = set()
        for slot in slots:
            start = slot.start_utc.replace(tzinfo=timezone.utc) if slot.start_utc.tzinfo is None else slot.start_utc
            end = slot.end_utc.replace(tzinfo=timezone.utc) if slot.end_utc.tzinfo is None else slot.end_utc
            assert end - start == timedelta(minutes=tutoring_seed.SLOT_MINUTES)
            assert end > start
            assert start > T0  # every fixture slot is bookable, never in the past
            assert slot.status == "available"
            assert slot.iana_timezone == spec.iana_timezone
            assert slot.iana_timezone == availability.DEFAULT_TIMEZONE == "Asia/Kolkata"
            assert slot.id == uuid.uuid5(
                tutoring_seed.SEED_NAMESPACE,
                f"slot:{spec.key}:{start.isoformat()}",
            )
            starts.add(start)
        # One slot per (tutor, start): no duplicate and no missing instant.
        assert starts == expected_starts


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


def test_running_the_seed_twice_changes_nothing(db_session):
    first = tutoring_seed.provision(db_session, now=T0, days=3, per_day=2)
    db_session.commit()
    before = _counts(db_session)
    fingerprint = {
        (str(row.tutor_id), row.start_utc, row.status)
        for row in db_session.scalars(select(TutorAvailabilitySlot)).all()
    }

    second = tutoring_seed.provision(db_session, now=T0, days=3, per_day=2)
    db_session.commit()

    # A replay creates NOTHING...
    assert (second.users, second.tutors, second.subjects, second.slots) == (0, 0, 0, 0)
    assert second.tutor_ids == first.tutor_ids
    # ...and duplicates nothing.
    assert _counts(db_session) == before
    assert {
        (str(row.tutor_id), row.start_utc, row.status)
        for row in db_session.scalars(select(TutorAvailabilitySlot)).all()
    } == fingerprint


def test_the_seed_reconciles_drifted_rows_instead_of_duplicating_them(db_session):
    tutoring_seed.provision(db_session, now=T0, days=1, per_day=1)
    db_session.commit()
    spec = tutoring_seed.SEED_TUTORS[0]

    # Drift: someone renamed, suspended and soft-deleted the fixture tutor, and
    # deactivated the seeded student account.
    profile = db_session.get(TutorProfile, spec.tutor_id)
    profile.display_name = "Renamed By Hand"
    profile.status = "suspended"
    profile.source = "self_declared"
    profile.deleted_at = T0
    student = db_session.get(User, tutoring_seed.SEED_STUDENT_ID)
    student.status = "suspended"
    student.deleted_at = T0
    db_session.commit()

    report = tutoring_seed.provision(db_session, now=T0, days=1, per_day=1)
    db_session.commit()

    assert (report.users, report.tutors, report.subjects, report.slots) == (0, 0, 0, 0)
    profile = db_session.get(TutorProfile, spec.tutor_id)
    assert profile.display_name == spec.display_name
    assert profile.status == "active"
    assert profile.source == tutoring_seed.SEED_SOURCE
    assert profile.deleted_at is None
    student = db_session.get(User, tutoring_seed.SEED_STUDENT_ID)
    assert (student.status, student.deleted_at) == ("active", None)
    assert _counts(db_session)["tutors"] == EXPECTED_TUTORS


def test_a_smaller_calendar_seeds_fewer_slots_without_touching_the_cast(db_session):
    report = tutoring_seed.provision(db_session, now=T0, days=1, per_day=1)
    db_session.commit()
    assert report.slots == EXPECTED_TUTORS  # one slot each
    assert _counts(db_session) == {
        "users": EXPECTED_USERS,
        "tutors": EXPECTED_TUTORS,
        "subjects": EXPECTED_SUBJECTS,
        "slots": EXPECTED_TUTORS,
    }


# --------------------------------------------------------------------------- #
# DST probe fixtures
# --------------------------------------------------------------------------- #


def test_dst_probe_slots_are_deterministic_and_retain_their_zone(db_session):
    tutoring_seed.provision(db_session, now=T0, days=1, per_day=1)
    tutor_id = tutoring_seed.SEED_TUTORS[0].tutor_id
    probes = tutoring_seed.dst_probe_slots(db_session, tutor_id)
    db_session.commit()

    assert set(probes) == {"ambiguous", "nonexistent"}
    for label, local in (
        ("ambiguous", tutoring_seed.DST_AMBIGUOUS_LOCAL),
        ("nonexistent", tutoring_seed.DST_NONEXISTENT_LOCAL),
    ):
        resolved = availability.resolve_local_instant(local, tutoring_seed.DST_ZONE)
        row = db_session.get(TutorAvailabilitySlot, probes[label].id)
        stored = (
            row.start_utc.replace(tzinfo=timezone.utc)
            if row.start_utc.tzinfo is None
            else row.start_utc
        )
        assert stored == resolved.instant_utc
        assert row.iana_timezone == tutoring_seed.DST_ZONE  # zone RETAINED
        assert row.status == "available"
        assert row.id == uuid.uuid5(
            tutoring_seed.SEED_NAMESPACE,
            f"dst:{label}:{tutoring_seed.DST_ZONE}:{local.isoformat()}",
        )
