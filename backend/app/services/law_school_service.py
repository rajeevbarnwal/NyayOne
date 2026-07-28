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
    # (name, slug, state, itype, accr, exam, fmin, fmax, rank, city, est, seats, clinics, moots)
    # Sample-fact columns (city/est/seats/clinics/moots) are the SHARED visual
    # fixture contract values — frontend/scripts/lawschool_fixture_contract.json
    # is the single source both the developed harness and the Option C+
    # reference renderer consume; keep the two in byte-exact sync.
    ("National Law School of India University", "nlsiu-bengaluru", "Karnataka", "national_law_university", "NAAC A++", "CLAT", 285000, 320000, 1, "Bengaluru", 1987, 120, 8, 12),
    ("NALSAR University of Law", "nalsar-hyderabad", "Telangana", "national_law_university", "NAAC A+", "CLAT", 260000, 300000, 2, "Hyderabad", 1998, 132, 7, 10),
    ("The West Bengal National University of Juridical Sciences", "wbnujs-kolkata", "West Bengal", "national_law_university", "NAAC A", "CLAT", 240000, 280000, 4, "Kolkata", 1999, 127, 6, 11),
    ("National Law University, Delhi", "nlu-delhi", "Delhi", "national_law_university", "NAAC A+", "AILET", 250000, 295000, 3, "New Delhi", 2008, 110, 9, 9),
    ("Gujarat National Law University", "gnlu-gandhinagar", "Gujarat", "national_law_university", "NAAC A", "CLAT", 230000, 270000, 7, "Gandhinagar", 2003, 180, 6, 9),
    ("Symbiosis Law School, Pune", "sls-pune", "Maharashtra", "deemed", "NAAC A", "SLAT", 320000, 385000, 12, "Pune", 1977, 300, 5, 8),
    ("Jindal Global Law School", "jgls-sonipat", "Haryana", "private", "NAAC A", "LSAT-India", 550000, 700000, 5, "Sonipat", 2009, 400, 7, 10),
    ("Government Law College, Mumbai", "glc-mumbai", "Maharashtra", "government", "NAAC B+", "MH CET Law", 15000, 25000, 20, "Mumbai", 1855, 240, 4, 6),
    ("Faculty of Law, University of Delhi", "du-law-delhi", "Delhi", "government", "NAAC A+", "DU LLB", 12000, 20000, 8, "New Delhi", 1924, 240, 5, 7),
    ("ILS Law College, Pune", "ils-pune", "Maharashtra", "government", "NAAC A", "MH CET Law", 40000, 60000, 15, "Pune", 1924, 300, 4, 6),
    ("Christ University School of Law", "christ-law-bengaluru", "Karnataka", "deemed", "NAAC A+", "CUET", 210000, 260000, 18, "Bengaluru", 2006, 180, 3, 5),
    ("Rajiv Gandhi National University of Law", "rgnul-patiala", "Punjab", "national_law_university", "NAAC A", "CLAT", 200000, 240000, 10, "Patiala", 2006, 196, 3, 6),
]
_RETRIEVED = datetime(2026, 7, 1, tzinfo=timezone.utc)
_SOURCE_NAME = "Institution official website (dev seed)"
_SOURCE_URL = "https://example.invalid/dev-seed"


def _fact_rows(state: str, city: str, est: int, seats: int, clinics: int, moots: int) -> list[tuple[str, str]]:
    """Deterministic SAMPLE-labelled facts (SAATHI-121 fixture contract):
    every value carries "(sample)" — never presented as a verified claim.
    MUST stay byte-identical to frontend/scripts/lawschool_fixture_contract.mjs
    factRowsFor() and to migration 0006_lawschool_fact_backfill."""
    return [
        ("established", f"{est} (sample)"),
        ("location", f"{city}, {state} (sample)"),
        ("intake", f"{seats} seats (sample)"),
        ("hostel", "Available (sample)"),
        ("legal_aid_clinics", f"{clinics} clinics (sample)"),
        ("moot_teams", f"{moots} teams (sample)"),
    ]


def seed_law_schools(session: Session) -> int:
    """Deterministic PER-RECORD reconciliation of the dev/test catalog.

    QA F2 (independent_option_c_42f07a9_2026-07-28): the previous global
    early-return ("any school exists -> do nothing") left upgraded databases
    permanently on the old 24-fact seed. Reconciliation instead upserts by
    natural key — schools by slug, programmes by (school_id, degree), the seed
    source by url, facts by (school_id, key) — updating drifted values in
    place. Re-running is always a no-op (no duplicates ever; the fact natural
    key is also enforced by uq_law_school_facts_school_id). Catalog stays 12.

    Returns the number of NEWLY CREATED schools (12 on a fresh database, 0
    when the catalog already exists — same contract as before).
    """
    src = session.scalars(
        select(LawSchoolSource).where(LawSchoolSource.url == _SOURCE_URL)
        .order_by(LawSchoolSource.created_at)
    ).first()
    if src is None:
        src = LawSchoolSource(name=_SOURCE_NAME, url=_SOURCE_URL,
                              retrieved_at=_RETRIEVED, freshness_days=180)
        session.add(src)
        session.flush()
    created = 0
    for name, slug, state, itype, accr, exam, fmin, fmax, rank, city, est, seats, clinics, moots in _SEED:
        sc = session.scalars(select(LawSchool).where(LawSchool.slug == slug)).first()
        if sc is None:
            sc = LawSchool(name=name, slug=slug, state=state, institution_type=itype,
                           accreditation=accr, entrance_exam=exam, fees_min=fmin, fees_max=fmax, nirf_rank=rank)
            session.add(sc)
            session.flush()
            created += 1
        else:
            for attr, val in (("name", name), ("state", state), ("institution_type", itype),
                              ("accreditation", accr), ("entrance_exam", exam),
                              ("fees_min", fmin), ("fees_max", fmax), ("nirf_rank", rank)):
                if getattr(sc, attr) != val:
                    setattr(sc, attr, val)
        existing_progs = {
            p.degree: p for p in session.scalars(
                select(LawSchoolProgramme).where(LawSchoolProgramme.school_id == sc.id))
        }
        desired_progs = [("BA LLB (Hons)", 5)]
        if itype in ("government", "national_law_university"):
            desired_progs.append(("LLM", 1))
        for degree, years in desired_progs:
            prog = existing_progs.get(degree)
            if prog is None:
                session.add(LawSchoolProgramme(school_id=sc.id, degree=degree, duration_years=years))
            elif prog.duration_years != years:
                prog.duration_years = years
        existing_facts = {
            f.key: f for f in session.scalars(
                select(LawSchoolFact).where(LawSchoolFact.school_id == sc.id))
        }
        for key, value in _fact_rows(state, city, est, seats, clinics, moots):
            fact = existing_facts.get(key)
            if fact is None:
                session.add(LawSchoolFact(school_id=sc.id, key=key, value=value, source_id=src.id))
            else:
                if fact.value != value:
                    fact.value = value
                if fact.source_id is None:
                    fact.source_id = src.id
    session.flush()
    return created
