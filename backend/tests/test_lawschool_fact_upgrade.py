"""SAATHI-119 (QA F2) — forward data-upgrade proof for law-school facts.

Builds a REAL parent-state database: alembic upgrade to 0005, then the OLD
(60fe345) 24-fact dev seed recreated inline. ``alembic upgrade head`` must
reconcile it to the approved fixture contract (12 schools, 72 facts, every
(slug, key, value) matching frontend/scripts/lawschool_fixture_contract.json),
re-running the app-level reconciliation must change nothing and create no
duplicates, and downgrade to its parent / re-upgrade must stay clean.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONTRACT = json.loads(
    (REPO / "frontend" / "scripts" / "lawschool_fixture_contract.json").read_text(encoding="utf-8")
)

FACT_KEYS = ["established", "location", "intake", "hostel", "legal_aid_clinics", "moot_teams"]


def expected_facts(school: dict) -> dict[str, str]:
    return {
        "established": f"{school['established']} (sample)",
        "location": f"{school['city']}, {school['state']} (sample)",
        "intake": f"{school['seats']} seats (sample)",
        "hostel": f"{school['hostel']} (sample)",
        "legal_aid_clinics": f"{school['legalAidClinics']} clinics (sample)",
        "moot_teams": f"{school['mootTeams']} teams (sample)",
    }


def alembic(db: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{db}"}
    return subprocess.run([sys.executable, "-m", "alembic", *args],
                          capture_output=True, text=True, env=env, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]))


def seed_old_style(db: str) -> None:
    """Recreate the OLD (parent 60fe345) dev seed: 12 schools, one source,
    programmes, and ONLY intake/hostel facts with '(dev seed)' values."""
    c = sqlite3.connect(db)
    src = uuid.uuid4().hex
    c.execute(
        "INSERT INTO law_school_sources (id, name, url, retrieved_at, freshness_days,"
        " created_at, updated_at) VALUES (?, 'Institution official website (dev seed)',"
        " 'https://example.invalid/dev-seed', '2026-07-01 00:00:00+00:00', 180,"
        " datetime('now'), datetime('now'))", (src,))
    for s in CONTRACT["catalog"]:
        sid = uuid.uuid4().hex
        c.execute(
            "INSERT INTO law_schools (id, name, slug, state, institution_type, accreditation,"
            " entrance_exam, fees_min, fees_max, nirf_rank, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (sid, s["name"], s["slug"], s["state"], s["institutionType"], s["accreditation"],
             s["entranceExam"], s["feesMin"], s["feesMax"], s["nirfRank"]))
        c.execute(
            "INSERT INTO law_school_programmes (id, school_id, degree, duration_years,"
            " created_at, updated_at) VALUES (?, ?, 'BA LLB (Hons)', 5, datetime('now'), datetime('now'))",
            (uuid.uuid4().hex, sid))
        if s["institutionType"] in ("government", "national_law_university"):
            c.execute(
                "INSERT INTO law_school_programmes (id, school_id, degree, duration_years,"
                " created_at, updated_at) VALUES (?, ?, 'LLM', 1, datetime('now'), datetime('now'))",
                (uuid.uuid4().hex, sid))
        for key, value in (("intake", "180 seats (dev seed)"), ("hostel", "Available (dev seed)")):
            c.execute(
                "INSERT INTO law_school_facts (id, school_id, key, value, source_id,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                (uuid.uuid4().hex, sid, key, value, src))
    c.commit()
    c.close()


def snapshot(db: str):
    c = sqlite3.connect(db)
    schools = c.execute("SELECT COUNT(*) FROM law_schools").fetchone()[0]
    facts = c.execute(
        "SELECT s.slug, f.key, f.value, f.source_id FROM law_school_facts f"
        " JOIN law_schools s ON s.id = f.school_id ORDER BY s.slug, f.key").fetchall()
    dup = c.execute(
        "SELECT school_id, key, COUNT(*) FROM law_school_facts GROUP BY school_id, key"
        " HAVING COUNT(*) > 1").fetchall()
    progs = c.execute(
        "SELECT school_id, degree, COUNT(*) FROM law_school_programmes GROUP BY school_id, degree"
        " HAVING COUNT(*) > 1").fetchall()
    sources = c.execute(
        "SELECT COUNT(*) FROM law_school_sources WHERE url='https://example.invalid/dev-seed'"
    ).fetchone()[0]
    c.close()
    return schools, facts, dup, progs, sources


def assert_approved_state(db: str) -> None:
    schools, facts, dup, progs, sources = snapshot(db)
    assert schools == 12
    assert len(facts) == 72, f"expected exactly 72 approved facts, saw {len(facts)}"
    assert dup == [] and progs == []
    assert sources == 1
    by_school: dict[str, dict[str, str]] = {}
    for slug, key, value, source_id in facts:
        assert source_id is not None, f"{slug}.{key} lost its source metadata"
        by_school.setdefault(slug, {})[key] = value
    assert sorted(by_school) == sorted(s["slug"] for s in CONTRACT["catalog"])
    for s in CONTRACT["catalog"]:
        got = by_school[s["slug"]]
        assert sorted(got) == sorted(FACT_KEYS)
        assert got == expected_facts(s), f"fact mismatch for {s['slug']}"


@pytest.fixture(scope="module")
def _parent_template(alembic_snapshots, tmp_path_factory):
    """Parent state built ONCE: alembic's own 0005 schema + the old 24-fact seed.

    ``alembic_snapshots["0005_language_check"]`` is produced by a real alembic
    ``upgrade`` (see ``tests/conftest.py``); this fixture only adds the historical
    seed on top. Building it once removes three duplicate ``python -m alembic
    upgrade 0005_language_check`` subprocesses (~0.85 s each) that all produced
    byte-identical schemas. Each test below still receives its own pristine copy,
    and the forward migration under test is still run by the real alembic CLI.
    """
    template = tmp_path_factory.mktemp("lawschool_parent") / "parent.db"
    shutil.copyfile(alembic_snapshots["0005_language_check"], template)
    seed_old_style(str(template))
    return template


@pytest.fixture()
def parent_db(_parent_template, tmp_path):
    """Parent-state DB: schema at 0005 + old-style 24-fact seed."""
    db = str(tmp_path / "parent.db")
    shutil.copyfile(_parent_template, db)
    schools, facts, *_ = snapshot(db)
    assert schools == 12 and len(facts) == 24  # genuinely the old state
    return db


def test_upgrade_head_backfills_parent_state_db(parent_db):
    r = alembic(parent_db, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-800:]
    assert_approved_state(parent_db)


def test_upgrade_is_idempotent_and_seed_reconciliation_changes_nothing(parent_db):
    assert alembic(parent_db, "upgrade", "head").returncode == 0
    before = snapshot(parent_db)

    # Re-run the app-level reconciliation against the upgraded DB.
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.services.law_school_service import seed_law_schools

    engine = create_engine(f"sqlite+pysqlite:///{parent_db}")
    with Session(engine) as session:
        assert seed_law_schools(session) == 0  # nothing new to create
        session.commit()
    engine.dispose()

    assert snapshot(parent_db) == before  # zero changes, zero duplicates
    assert_approved_state(parent_db)


def test_downgrade_then_reupgrade_clean(parent_db):
    assert alembic(parent_db, "upgrade", "head").returncode == 0
    # Target 0006's parent explicitly: later forward migrations must not turn
    # this historical data-migration test into a no-op.
    assert alembic(parent_db, "downgrade", "0005_language_check").returncode == 0
    schools, facts, dup, _, _ = snapshot(parent_db)
    # policy: only the four added keys are removed; intake/hostel remain.
    assert schools == 12 and len(facts) == 24 and dup == []
    keys = {k for _, k, _, _ in facts}
    assert keys == {"intake", "hostel"}
    r = alembic(parent_db, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-800:]
    assert_approved_state(parent_db)


def test_upgrade_head_is_safe_on_fresh_db(tmp_path):
    """Fresh DB (no seed): 0006 is a no-op; a subsequent seed produces the
    approved state directly."""
    db = str(tmp_path / "fresh.db")
    r = alembic(db, "upgrade", "head")
    assert r.returncode == 0, r.stderr[-800:]
    schools, facts, *_ = snapshot(db)
    assert schools == 0 and facts == []

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.services.law_school_service import seed_law_schools

    engine = create_engine(f"sqlite+pysqlite:///{db}")
    with Session(engine) as session:
        assert seed_law_schools(session) == 12
        session.commit()
    engine.dispose()
    assert_approved_state(db)
