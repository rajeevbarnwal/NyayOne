"""Real-Alembic and ORM schema proof for SAATHI-60."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.models.internships import InternshipListing, SavedInternship
from app.models.registration import User
from app.core.config import settings
from app.services.internship_service import (
    CATALOGUE_SEED,
    listing_out,
    seed_internship_catalogue,
)

BACKEND = Path(__file__).resolve().parents[1]
HEAD = "0015_wave4_public_risk_labels"
PARENT = "0013_wave5_calendar_interop"


def _alembic(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{database}"},
        capture_output=True,
        text=True,
    )


def test_real_migration_has_tables_constraints_indexes_and_seed(alembic_snapshots, tmp_path):
    database = tmp_path / "saathi60-schema.db"
    shutil.copyfile(alembic_snapshots["head"], database)
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    inspector = inspect(engine)
    assert {"internship_listings", "saved_internships"} <= set(
        inspector.get_table_names()
    )
    assert {
        "ix_internship_listings_verification_status",
        "ix_internship_listings_application_deadline",
        "ix_internship_listings_organisation_public_id",
    } <= {item["name"] for item in inspector.get_indexes("internship_listings")}
    assert "organisation_public_id" in {
        item["name"] for item in inspector.get_columns("internship_listings")
    }
    assert {
        "ix_saved_internships_user_id",
        "ix_saved_internships_listing_id",
    } <= {item["name"] for item in inspector.get_indexes("saved_internships")}
    assert {
        "ck_internship_listings_verification_provenance_truthful",
        "ck_internship_listings_stipend_nonnegative",
        "ck_internship_listings_metadata_must_be_null",
    } <= {
        item["name"] for item in inspector.get_check_constraints("internship_listings")
    }
    foreign_keys = {
        tuple(item["constrained_columns"]): (
            item["referred_table"],
            (item.get("options") or {}).get("ondelete"),
        )
        for item in inspector.get_foreign_keys("saved_internships")
    }
    assert foreign_keys == {
        ("listing_id",): ("internship_listings", "CASCADE"),
        ("user_id",): ("users", "CASCADE"),
    }
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(InternshipListing).order_by(InternshipListing.sort_order)
            ).all()
        )
        assert [row.slug for row in rows] == ["cam", "menon", "vidhi"]
        assert rows[0].verification_status == "verified"
        assert rows[0].source_verified_at is not None
        assert all(row.source_verified_at is None for row in rows[1:])


def test_migration_seed_matches_service_seed(alembic_snapshots, tmp_path):
    database = tmp_path / "saathi60-parity.db"
    shutil.copyfile(alembic_snapshots["head"], database)
    with Session(create_engine(f"sqlite+pysqlite:///{database}")) as session:
        rows = {
            row.slug: row
            for row in session.scalars(select(InternshipListing)).all()
        }
    assert set(rows) == {item["slug"] for item in CATALOGUE_SEED}
    for expected in CATALOGUE_SEED:
        actual = rows[expected["slug"]]
        for field in (
            "id",
            "role",
            "organisation",
            "organisation_public_id",
            "location",
            "stipend_monthly_paise",
            "verification_status",
            "application_deadline",
            "eligibility",
            "tags_json",
            "description",
            "source_name",
            "source_url",
            "sort_order",
            "active",
        ):
            assert getattr(actual, field) == expected[field], (actual.slug, field)


def test_upgrade_downgrade_reupgrade_and_check(tmp_path):
    database = tmp_path / "saathi60-lifecycle.db"
    first = _alembic(database, "upgrade", "head")
    assert first.returncode == 0, first.stderr
    engine = create_engine(f"sqlite+pysqlite:///{database}")
    assert engine.connect().exec_driver_sql(
        "SELECT version_num FROM alembic_version"
    ).scalar_one() == HEAD
    down = _alembic(database, "downgrade", PARENT)
    assert down.returncode == 0, down.stderr
    assert not {"internship_listings", "saved_internships"} & set(
        inspect(engine).get_table_names()
    )
    up = _alembic(database, "upgrade", "head")
    assert up.returncode == 0, up.stderr
    check = _alembic(database, "check")
    assert check.returncode == 0, check.stdout + check.stderr


@pytest.mark.parametrize(
    ("changes", "constraint"),
    [
        ({"stipend_monthly_paise": -1}, "stipend_nonnegative"),
        (
            {"verification_status": "verified", "source_verified_at": None},
            "verification_provenance_truthful",
        ),
        (
            {
                "verification_status": "unverified",
                "source_verified_at": CATALOGUE_SEED[0]["source_verified_at"],
            },
            "verification_provenance_truthful",
        ),
        ({"metadata_json": {"unsafe": True}}, "metadata_must_be_null"),
    ],
)
def test_orm_schema_rejects_untruthful_listing(db_session, changes, constraint):
    values = dict(CATALOGUE_SEED[0])
    values.update(changes)
    values["id"] = uuid.uuid4()
    values["slug"] = f"bad-{abs(hash(repr(changes)))}"
    db_session.add(InternshipListing(**values))
    with pytest.raises(IntegrityError) as caught:
        db_session.commit()
    assert constraint in str(caught.value)
    db_session.rollback()


def test_unique_save_constraint(db_session):
    seed_internship_catalogue(db_session)
    user = User(role="student", status="active")
    db_session.add(user)
    db_session.flush()
    cam = db_session.scalar(
        select(InternshipListing).where(InternshipListing.slug == "cam")
    )
    assert cam is not None
    db_session.add_all(
        [
            SavedInternship(user_id=user.id, listing_id=cam.id),
            SavedInternship(user_id=user.id, listing_id=cam.id),
        ]
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_service_catalogue_seed_is_idempotent(db_session):
    seed_internship_catalogue(db_session)
    seed_internship_catalogue(db_session)
    assert [
        row.slug
        for row in db_session.scalars(
            select(InternshipListing).order_by(InternshipListing.sort_order)
        ).all()
    ] == ["cam", "menon", "vidhi"]


def test_catalogue_public_organisation_id_survives_display_name_rename(
    db_session, monkeypatch
):
    seed_internship_catalogue(db_session)
    listing = db_session.scalar(
        select(InternshipListing).where(InternshipListing.slug == "cam")
    )
    before = listing_out(listing).organisation_id
    listing.organisation = "CAM — renamed display label"
    monkeypatch.setattr(
        settings, "registration_lookup_secret", SecretStr("rotated-catalogue-secret")
    )
    db_session.flush()
    after = listing_out(listing).organisation_id
    assert before == after == listing.organisation_public_id
