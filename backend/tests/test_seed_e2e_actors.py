"""SAATHI-120 (F1) — idempotent E2E actor/fixture setup seam.

Proves scripts/seed_e2e_actors.py against a freshly migrated (schema-complete)
database: running the setup twice creates ZERO duplicate rows, the exact
dev-claims actor UUIDs exist as active users, and the S-30 contract fixture
rows exist exactly once — with foreign keys fully honoured.
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.registration import User
from app.models.wave1 import LawSchool, LawSchoolFollow, SavedLawSchool
from scripts.seed_e2e_actors import (
    E2E_ACTORS, S30_FOLLOWED_SLUGS, S30_SAVED_SLUGS, provision,
)

USER_A = uuid.UUID("00000000-0000-4000-8000-0000000000de")
USER_B = uuid.UUID("00000000-0000-4000-8000-0000000000b2")
NON_STUDENT = uuid.UUID("00000000-0000-4000-8000-0000000000c3")


def _counts(session):
    return {
        "users": session.scalar(select(func.count()).select_from(User)),
        "schools": session.scalar(select(func.count()).select_from(LawSchool)),
        "saved": session.scalar(select(func.count()).select_from(SavedLawSchool)),
        "followed": session.scalar(select(func.count()).select_from(LawSchoolFollow)),
    }


def test_setup_twice_zero_duplicates(db_session):
    first = provision(db_session)
    db_session.commit()
    after_first = _counts(db_session)
    assert first["created_users"] == 3
    assert first["created_schools"] == 12
    assert first["created_saved"] == 2 and first["created_followed"] == 2
    assert after_first == {"users": 3, "schools": 12, "saved": 2, "followed": 2}

    second = provision(db_session)  # idempotent re-run: creates NOTHING new
    db_session.commit()
    after_second = _counts(db_session)
    assert second["created_users"] == 0
    assert second["created_schools"] == 0
    assert second["created_saved"] == 0 and second["created_followed"] == 0
    assert after_second == after_first  # zero duplicate rows

    # No duplicate (user_id, school_id) pairs beyond the unique-constraint truth.
    for model in (SavedLawSchool, LawSchoolFollow):
        pairs = db_session.execute(select(model.user_id, model.school_id)).all()
        assert len(pairs) == len(set(pairs)) == 2


def test_exact_dev_claims_actors_provisioned(db_session):
    provision(db_session)
    db_session.commit()
    assert [uid for uid, _ in E2E_ACTORS] == [
        "00000000-0000-4000-8000-0000000000de",
        "00000000-0000-4000-8000-0000000000b2",
        "00000000-0000-4000-8000-0000000000c3",
    ]
    a = db_session.get(User, USER_A)
    b = db_session.get(User, USER_B)
    c = db_session.get(User, NON_STUDENT)
    assert a is not None and a.role == "student" and a.status == "active"
    assert b is not None and b.role == "student" and b.status == "active"
    assert c is not None and c.role == "lawyer" and c.status == "active"


def test_s30_fixture_rows_honour_fks_and_contract(db_session):
    provision(db_session)
    db_session.commit()
    saved_slugs = db_session.execute(
        select(LawSchool.slug).join(SavedLawSchool, SavedLawSchool.school_id == LawSchool.id)
        .where(SavedLawSchool.user_id == USER_A).order_by(SavedLawSchool.created_at)
    ).scalars().all()
    followed_slugs = db_session.execute(
        select(LawSchool.slug).join(LawSchoolFollow, LawSchoolFollow.school_id == LawSchool.id)
        .where(LawSchoolFollow.user_id == USER_A).order_by(LawSchoolFollow.created_at)
    ).scalars().all()
    assert sorted(saved_slugs) == sorted(S30_SAVED_SLUGS)
    assert sorted(followed_slugs) == sorted(S30_FOLLOWED_SLUGS)
    # every fixture row references a real user and a real school (FKs honoured)
    for row in db_session.scalars(select(SavedLawSchool)).all():
        assert db_session.get(User, row.user_id) is not None
        assert db_session.get(LawSchool, row.school_id) is not None
