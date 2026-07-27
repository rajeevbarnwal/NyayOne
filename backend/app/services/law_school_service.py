"""SAATHI-63 law-school domain services + deterministic seed.

Comparison bound is BACKEND-AUTHORITATIVE and config-driven (Product decision
2026-07-27: COMPARE_MAX_SCHOOLS default 4, min 2, duplicates prohibited, typed
COMPARE_LIMIT_EXCEEDED with max_allowed, no partial mutation, concurrency-safe).
Seed data is deterministic/local — no scraping, no live provider, no licensing
claims; every material fact carries source name/URL/retrieved-at/freshness.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.wave1 import (
    ComparisonItem, ComparisonSet, LawSchool, LawSchoolFact, LawSchoolProgramme, LawSchoolSource,
)


class CompareError(Exception):
    def __init__(self, status_code: int, code: str, **extra) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.extra = extra


def compare_limits() -> tuple[int, int]:
    return settings.compare_min_schools, settings.compare_max_schools


def create_comparison(session: Session, school_ids: list[uuid.UUID], user_id: uuid.UUID | None) -> ComparisonSet:
    """Validate then create a comparison set ATOMICALLY (no partial mutation)."""
    lo, hi = compare_limits()
    if len(set(school_ids)) != len(school_ids):
        raise CompareError(422, "DUPLICATE_SCHOOL")
    if len(school_ids) < lo:
        raise CompareError(422, "COMPARE_MIN_NOT_MET", min_required=lo)
    if len(school_ids) > hi:
        raise CompareError(422, "COMPARE_LIMIT_EXCEEDED", max_allowed=hi)
    found = session.scalars(select(LawSchool).where(LawSchool.id.in_(school_ids))).all()
    if len(found) != len(school_ids):
        raise CompareError(404, "school_not_found")
    cs = ComparisonSet(user_id=user_id)
    session.add(cs)
    session.flush()
    for pos, sid in enumerate(school_ids):
        session.add(ComparisonItem(set_id=cs.id, school_id=sid, position=pos))
    session.flush()
    return cs


def add_comparison_item(session: Session, set_id: uuid.UUID, school_id: uuid.UUID) -> ComparisonItem:
    """Add one school to an existing set. Concurrency-safe on every backend:
    the limit is enforced by a single ATOMIC conditional INSERT..SELECT whose
    WHERE re-counts the set's items in the same statement — two racing adds
    cannot both observe a below-limit count and both land (verified by test on
    SQLite; on PostgreSQL the set row is additionally locked FOR UPDATE).
    Duplicates are rejected by the unique constraint + explicit check."""
    import sqlalchemy as sa
    from sqlalchemy.exc import IntegrityError

    _, hi = compare_limits()
    cs = session.execute(
        select(ComparisonSet).where(ComparisonSet.id == set_id).with_for_update()
    ).scalar_one_or_none()
    if cs is None:
        raise CompareError(404, "comparison_not_found")
    if session.scalar(select(ComparisonItem).where(
            ComparisonItem.set_id == set_id, ComparisonItem.school_id == school_id)) is not None:
        raise CompareError(422, "DUPLICATE_SCHOOL")
    item_id = uuid.uuid4()
    cnt = (select(func.count()).select_from(ComparisonItem)
           .where(ComparisonItem.set_id == set_id).scalar_subquery())
    stmt = sa.insert(ComparisonItem).from_select(
        ["id", "set_id", "school_id", "position"],
        sa.select(sa.literal(item_id), sa.literal(set_id), sa.literal(school_id), cnt)
        .where(cnt < sa.literal(hi)),
    )
    try:
        result = session.execute(stmt)
    except IntegrityError as exc:
        raise CompareError(422, "DUPLICATE_SCHOOL") from exc
    if (result.rowcount or 0) == 0:
        raise CompareError(422, "COMPARE_LIMIT_EXCEEDED", max_allowed=hi)
    session.flush()
    item = session.get(ComparisonItem, item_id)
    assert item is not None
    return item


# ------------------------------ deterministic seed ------------------------------
_SEED = [
    ("National Law School of India University", "nlsiu-bengaluru", "Karnataka", "national_law_university", "NAAC A++", "CLAT", 285000, 320000, 1),
    ("NALSAR University of Law", "nalsar-hyderabad", "Telangana", "national_law_university", "NAAC A+", "CLAT", 260000, 300000, 2),
    ("The West Bengal National University of Juridical Sciences", "wbnujs-kolkata", "West Bengal", "national_law_university", "NAAC A", "CLAT", 240000, 280000, 4),
    ("National Law University, Delhi", "nlu-delhi", "Delhi", "national_law_university", "NAAC A+", "AILET", 250000, 295000, 3),
    ("Gujarat National Law University", "gnlu-gandhinagar", "Gujarat", "national_law_university", "NAAC A", "CLAT", 230000, 270000, 7),
    ("Symbiosis Law School, Pune", "sls-pune", "Maharashtra", "deemed", "NAAC A", "SLAT", 320000, 385000, 12),
    ("Jindal Global Law School", "jgls-sonipat", "Haryana", "private", "NAAC A", "LSAT-India", 550000, 700000, 5),
    ("Government Law College, Mumbai", "glc-mumbai", "Maharashtra", "government", "NAAC B+", "MH CET Law", 15000, 25000, 20),
    ("Faculty of Law, University of Delhi", "du-law-delhi", "Delhi", "government", "NAAC A+", "DU LLB", 12000, 20000, 8),
    ("ILS Law College, Pune", "ils-pune", "Maharashtra", "government", "NAAC A", "MH CET Law", 40000, 60000, 15),
    ("Christ University School of Law", "christ-law-bengaluru", "Karnataka", "deemed", "NAAC A+", "CUET", 210000, 260000, 18),
    ("Rajiv Gandhi National University of Law", "rgnul-patiala", "Punjab", "national_law_university", "NAAC A", "CLAT", 200000, 240000, 10),
]
_RETRIEVED = datetime(2026, 7, 1, tzinfo=timezone.utc)


def seed_law_schools(session: Session) -> int:
    """Idempotent deterministic seed (development + tests). Returns row count."""
    if session.scalar(select(func.count()).select_from(LawSchool)):
        return 0
    src = LawSchoolSource(name="Institution official website (dev seed)",
                          url="https://example.invalid/dev-seed", retrieved_at=_RETRIEVED, freshness_days=180)
    session.add(src)
    session.flush()
    n = 0
    for name, slug, state, itype, accr, exam, fmin, fmax, rank in _SEED:
        sc = LawSchool(name=name, slug=slug, state=state, institution_type=itype,
                       accreditation=accr, entrance_exam=exam, fees_min=fmin, fees_max=fmax, nirf_rank=rank)
        session.add(sc)
        session.flush()
        session.add(LawSchoolProgramme(school_id=sc.id, degree="BA LLB (Hons)", duration_years=5))
        if itype in ("government", "national_law_university"):
            session.add(LawSchoolProgramme(school_id=sc.id, degree="LLM", duration_years=1))
        for key, value in (("intake", "180 seats (dev seed)"), ("hostel", "Available (dev seed)")):
            session.add(LawSchoolFact(school_id=sc.id, key=key, value=value, source_id=src.id))
        n += 1
    session.flush()
    return n
