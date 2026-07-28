"""SAATHI-120 (F1) — repository-owned, idempotent E2E actor + fixture setup.

QA (independent_option_c_e843116_2026-07-28) proved the clean PostgreSQL
law-school run fails 105 cases because the deterministic dev-claims actors the
frontend/harness use (X-Actor-Claims subs) have no ``users`` rows, so the
save/follow foreign keys correctly reject mutations. This script is the
EXPLICIT setup seam for that state:

    # from a clean ``alembic upgrade head`` database
    python scripts/seed_e2e_actors.py          # backend/ as CWD, or
    python -m scripts.seed_e2e_actors

It provisions, idempotently and concurrency-safely (upsert by natural key —
the fixed primary-key UUID for users, the (user_id, school_id) unique
constraint for fixtures):

  * the exact actor UUIDs the dev claims use:
      - 00000000-0000-4000-8000-0000000000de  (USER_A, role student, active)
      - 00000000-0000-4000-8000-0000000000b2  (USER_B, role student, active)
      - 00000000-0000-4000-8000-0000000000c3  (NON_STUDENT, role lawyer, active)
  * the deterministic 12-school catalog (law_school_service.seed_law_schools,
    itself a per-record natural-key reconciliation);
  * the S-30 contract fixture for USER_A via DIRECT inserts honouring the FKs
    (saved: nlsiu-bengaluru, gnlu-gandhinagar; followed: nlu-delhi,
    nalsar-hyderabad — mirrors frontend/scripts/lawschool_fixture_contract.json
    s30; the E2E suite still resets/reseeds this state through the public API).

NO production endpoint gains any seed side effect; foreign keys stay enforced.
Running twice (or concurrently) never creates duplicate rows.
"""
from __future__ import annotations

import sys
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Deterministic dev-claims actors (mirror of frontend lawSchoolsApi.ts /
# scripts/lawschool-e2e.mjs USER_A / USER_B / NON_STUDENT).
E2E_ACTORS: tuple[tuple[str, str], ...] = (
    ("00000000-0000-4000-8000-0000000000de", "student"),  # USER_A (FE baked-in)
    ("00000000-0000-4000-8000-0000000000b2", "student"),  # USER_B (cross-user cases)
    ("00000000-0000-4000-8000-0000000000c3", "lawyer"),   # NON_STUDENT (403 cases)
)

# S-30 contract fixture (lawschool_fixture_contract.json s30) owned by USER_A.
S30_SAVED_SLUGS: tuple[str, ...] = ("nlsiu-bengaluru", "gnlu-gandhinagar")
S30_FOLLOWED_SLUGS: tuple[str, ...] = ("nlu-delhi", "nalsar-hyderabad")


def _upsert_user(session: Session, user_id: uuid.UUID, role: str) -> bool:
    """Idempotent, race-safe user provisioning by primary key. Returns True
    iff a new row was created. On PostgreSQL uses native ON CONFLICT DO
    NOTHING; elsewhere insert + IntegrityError rollback (loser re-reads)."""
    from app.models.registration import User

    existing = session.get(User, user_id)
    if existing is not None:
        changed = False
        if existing.role != role:
            existing.role = role
            changed = True
        if existing.status != "active":
            existing.status = "active"
            changed = True
        if changed:
            session.flush()
        return False
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(User.__table__).values(
            id=user_id, role=role, status="active"
        ).on_conflict_do_nothing(index_elements=["id"])
        created = bool(session.execute(stmt).rowcount)
        session.flush()
        return created
    try:
        with session.begin_nested():
            session.add(User(id=user_id, role=role, status="active"))
            session.flush()
        return True
    except IntegrityError:
        return False  # raced writer won; row exists


def _upsert_owned(session: Session, model, user_id: uuid.UUID, school_id: uuid.UUID) -> bool:
    """Idempotent insert honouring the (user_id, school_id) natural key."""
    from sqlalchemy import select

    if session.scalar(select(model).where(
            model.user_id == user_id, model.school_id == school_id)) is not None:
        return False
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(model.__table__).values(
            user_id=user_id, school_id=school_id
        ).on_conflict_do_nothing(index_elements=["user_id", "school_id"])
        created = bool(session.execute(stmt).rowcount)
        session.flush()
        return created
    try:
        with session.begin_nested():
            session.add(model(user_id=user_id, school_id=school_id))
            session.flush()
        return True
    except IntegrityError:
        return False


def provision(session: Session) -> dict:
    """Provision actors + catalog + S-30 fixture. Safe to run any number of
    times; returns a summary of what was newly created."""
    from sqlalchemy import select

    from app.models.wave1 import LawSchool, LawSchoolFollow, SavedLawSchool
    from app.services.law_school_service import seed_law_schools

    created_users = sum(
        _upsert_user(session, uuid.UUID(uid), role) for uid, role in E2E_ACTORS
    )
    created_schools = seed_law_schools(session)
    user_a = uuid.UUID(E2E_ACTORS[0][0])
    id_of = {
        slug: sid for sid, slug in session.execute(
            select(LawSchool.id, LawSchool.slug).where(
                LawSchool.slug.in_(S30_SAVED_SLUGS + S30_FOLLOWED_SLUGS))
        ).all()
    }
    missing = [s for s in (*S30_SAVED_SLUGS, *S30_FOLLOWED_SLUGS) if s not in id_of]
    if missing:
        raise RuntimeError(f"catalog incomplete after seed: missing slugs {missing}")
    created_saved = sum(
        _upsert_owned(session, SavedLawSchool, user_a, id_of[slug]) for slug in S30_SAVED_SLUGS
    )
    created_followed = sum(
        _upsert_owned(session, LawSchoolFollow, user_a, id_of[slug]) for slug in S30_FOLLOWED_SLUGS
    )
    session.flush()
    return {
        "actors": [uid for uid, _ in E2E_ACTORS],
        "created_users": created_users,
        "created_schools": created_schools,
        "created_saved": created_saved,
        "created_followed": created_followed,
    }


def main() -> int:
    # Standalone invocation (python scripts/seed_e2e_actors.py): put backend/
    # on sys.path so `app.*` imports resolve exactly as under pytest/uvicorn.
    import pathlib

    backend_root = str(pathlib.Path(__file__).resolve().parent.parent)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        summary = provision(session)
        session.commit()
    print(f"seed_e2e_actors: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
