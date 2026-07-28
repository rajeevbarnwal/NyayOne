"""Law-school fact backfill / reconciliation (SAATHI-119, QA F2).

An upgraded database from the 60fe345 parent state keeps the OLD dev-seed
facts forever: 12 schools with only ``intake`` ("180 seats (dev seed)") and
``hostel`` ("Available (dev seed)") — 24 rows, none matching the approved
Option C+ fixture contract (frontend/scripts/lawschool_fixture_contract.json).
The application seed alone cannot be trusted to run on deployed databases, so
this FORWARD DATA MIGRATION reconciles every known catalog school to the six
approved sample-labelled facts:

  established / location / intake / hostel / legal_aid_clinics / moot_teams

Behaviour (idempotent by the natural key ``(school_id, key)``, which is also
enforced by ``uq_law_school_facts_school_id``):
  * UPDATE existing rows (the old intake/hostel dev-seed values) to the
    approved contract values and attach the seed source where missing;
  * INSERT missing keys with deterministic UUIDv5 ids and the seed source;
  * schools are matched by slug — unknown slugs (fresh/empty databases, or
    databases that never seeded) are skipped, so the migration is safe on
    fresh AND parent-state databases and on re-runs.

The seed source row ("Institution official website (dev seed)",
https://example.invalid/dev-seed) is reused when present; otherwise ONE
deterministic source row is created (only if at least one catalog school
exists).

Data-migration policy (downgrade): ``downgrade`` removes ONLY the four keys
this revision may have introduced (established, location, legal_aid_clinics,
moot_teams) for the known catalog slugs. The pre-upgrade intake/hostel VALUES
are not restored — they were unversioned dev-seed strings, restoring them
would destroy the approved values, and forward data reconciliations in this
repository are deliberately non-destructive in both directions. Nothing else
is deleted.

Raw SQL over bound lightweight table metadata only — no ORM imports, so the
migration stays valid regardless of future model changes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_lawschool_fact_backfill"
down_revision: Union[str, None] = "0005_language_check"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)

_schools = sa.table(
    "law_schools",
    sa.column("id", _UUID),
    sa.column("slug", sa.String(200)),
)
_sources = sa.table(
    "law_school_sources",
    sa.column("id", _UUID),
    sa.column("name", sa.String(120)),
    sa.column("url", sa.String(400)),
    sa.column("retrieved_at", sa.DateTime(timezone=True)),
    sa.column("freshness_days", sa.Integer),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
_facts = sa.table(
    "law_school_facts",
    sa.column("id", _UUID),
    sa.column("school_id", _UUID),
    sa.column("key", sa.String(80)),
    sa.column("value", sa.String(400)),
    sa.column("source_id", _UUID),
)

_SOURCE_NAME = "Institution official website (dev seed)"
_SOURCE_URL = "https://example.invalid/dev-seed"
# (slug, state, city, established, seats, clinics, moots) — MUST stay
# byte-identical to lawschool_fixture_contract.json / law_school_service._SEED.
_CATALOG = [
    ("nlsiu-bengaluru", "Karnataka", "Bengaluru", 1987, 120, 8, 12),
    ("nalsar-hyderabad", "Telangana", "Hyderabad", 1998, 132, 7, 10),
    ("wbnujs-kolkata", "West Bengal", "Kolkata", 1999, 127, 6, 11),
    ("nlu-delhi", "Delhi", "New Delhi", 2008, 110, 9, 9),
    ("gnlu-gandhinagar", "Gujarat", "Gandhinagar", 2003, 180, 6, 9),
    ("sls-pune", "Maharashtra", "Pune", 1977, 300, 5, 8),
    ("jgls-sonipat", "Haryana", "Sonipat", 2009, 400, 7, 10),
    ("glc-mumbai", "Maharashtra", "Mumbai", 1855, 240, 4, 6),
    ("du-law-delhi", "Delhi", "New Delhi", 1924, 240, 5, 7),
    ("ils-pune", "Maharashtra", "Pune", 1924, 300, 4, 6),
    ("christ-law-bengaluru", "Karnataka", "Bengaluru", 2006, 180, 3, 5),
    ("rgnul-patiala", "Punjab", "Patiala", 2006, 196, 3, 6),
]

_ADDED_KEYS = ("established", "location", "legal_aid_clinics", "moot_teams")


def _fact_rows(state: str, city: str, est: int, seats: int, clinics: int, moots: int):
    return [
        ("established", f"{est} (sample)"),
        ("location", f"{city}, {state} (sample)"),
        ("intake", f"{seats} seats (sample)"),
        ("hostel", "Available (sample)"),
        ("legal_aid_clinics", f"{clinics} clinics (sample)"),
        ("moot_teams", f"{moots} teams (sample)"),
    ]


def _det_uuid(kind: str, *parts: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, "legalsaathi:" + kind + ":" + ":".join(parts))


def _school_ids_by_slug(bind) -> dict[str, uuid.UUID]:
    slugs = [c[0] for c in _CATALOG]
    rows = bind.execute(
        sa.select(_schools.c.slug, _schools.c.id).where(_schools.c.slug.in_(slugs))
    ).all()
    return {slug: sid for slug, sid in rows}


def upgrade() -> None:
    bind = op.get_bind()
    by_slug = _school_ids_by_slug(bind)
    if not by_slug:
        return  # fresh/never-seeded database — nothing to reconcile

    source_id = bind.execute(
        sa.select(_sources.c.id).where(_sources.c.url == _SOURCE_URL)
        .order_by(_sources.c.created_at).limit(1)
    ).scalar_one_or_none()
    if source_id is None:
        source_id = _det_uuid("law_school_source", _SOURCE_URL)
        bind.execute(sa.insert(_sources).values(
            id=source_id, name=_SOURCE_NAME, url=_SOURCE_URL,
            retrieved_at=datetime(2026, 7, 1, tzinfo=timezone.utc), freshness_days=180,
        ))

    for slug, state, city, est, seats, clinics, moots in _CATALOG:
        school_id = by_slug.get(slug)
        if school_id is None:
            continue
        existing = dict(bind.execute(
            sa.select(_facts.c.key, _facts.c.value).where(_facts.c.school_id == school_id)
        ).all())
        for key, value in _fact_rows(state, city, est, seats, clinics, moots):
            if key in existing:
                if existing[key] != value:
                    bind.execute(
                        sa.update(_facts)
                        .where(_facts.c.school_id == school_id, _facts.c.key == key)
                        .values(value=value, source_id=source_id)
                    )
            else:
                bind.execute(sa.insert(_facts).values(
                    id=_det_uuid("law_school_fact", slug, key),
                    school_id=school_id, key=key, value=value, source_id=source_id,
                ))


def downgrade() -> None:
    """Remove ONLY the four keys this revision may have introduced (see the
    data-migration policy in the module docstring); intake/hostel values are
    intentionally left at the approved values — nothing destructive."""
    bind = op.get_bind()
    by_slug = _school_ids_by_slug(bind)
    if not by_slug:
        return
    bind.execute(
        sa.delete(_facts).where(
            _facts.c.school_id.in_(list(by_slug.values())),
            _facts.c.key.in_(list(_ADDED_KEYS)),
        )
    )
