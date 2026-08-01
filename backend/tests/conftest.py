"""Shared test fixtures. Uses SQLite in-memory so the base-model conventions and
repository patterns can be smoke-tested without a live Postgres, while remaining
dialect-portable to the real Postgres+pgvector runtime."""
from __future__ import annotations

import gc
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from tests import dbtemplate  # noqa: F401  (fast, create_all-equivalent schema builder)

BACKEND = Path(__file__).resolve().parents[1]


def pytest_collection_finish(session: pytest.Session) -> None:
    """Stop the cyclic garbage collector from re-walking a container-heavy heap.

    Collection imports every model, service, FastAPI route and Pydantic schema in
    the project, so the old generation is large and permanent for the rest of the
    run. Freezing it once collection is done (``gc.freeze`` excludes those objects
    from every future collection) and widening the gen-0 threshold removes ~10% of
    the suite's wall time. This is a CPython tuning knob only: reference counting
    is untouched, so objects are still finalised promptly and no test's behaviour
    changes.
    """
    gc.collect()
    gc.freeze()
    gc.set_threshold(50_000, 50, 50)


@pytest.fixture(autouse=True)
def _crypto_test_key():
    """Inject an explicit, non-default test key ring so crypto is deterministic
    and independent of environment settings (SAATHI-366 C3 — tests may inject
    explicit test keys). Also exercises the version-stamp path (active = v1)."""
    from app.core.crypto import KeyRing, override_keyring

    override_keyring(KeyRing(active_version="v1", secrets={"v1": b"unit-test-registration-key-v1"}))
    try:
        yield
    finally:
        override_keyring(None)


@pytest.fixture(autouse=True)
def _explicit_test_application_environment(monkeypatch: pytest.MonkeyPatch):
    """Keep deterministic auth seams independent of the deployment shell.

    PostgreSQL CI deliberately runs with ``APP_ENV=staging`` to exercise
    fail-closed runtime configuration.  Unit and HTTP-contract tests still need
    the explicit test-only ``X-Actor-Claims`` seam, and their loopback
    ``TestClient`` must not accidentally inherit staging cookie policy.  Tests
    that exercise the non-local boundary override this value themselves.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_env", "testing")


@pytest.fixture(autouse=True)
def _explicit_test_video_enablement(monkeypatch: pytest.MonkeyPatch):
    """Unit/HTTP tests opt into the deterministic media seam explicitly.

    Runtime defaults are intentionally disabled/none. Existing service tests
    exercise the enabled contract unless a test overrides this switch to prove
    the disabled path.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "video_calls_enabled", True)
    monkeypatch.setattr(settings, "video_provider", "deterministic")


@pytest.fixture(scope="session")
def engine() -> Engine:
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def db_session(engine: Engine) -> Iterator[Session]:
    # Model modules are imported by the test suite, so their tables are on
    # Base.metadata. Backing the session template over the shared engine both
    # creates the schema and empties it, so it replaces the create_all/drop_all
    # pair this fixture used to run per test (~34 ms -> ~0.6 ms) while handing
    # each test the same thing: a complete schema holding zero rows.
    dbtemplate.reset_to_empty_schema(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# --------------------------------------------------------------------------- #
# Real-alembic database templates (SAATHI runtime work)
# --------------------------------------------------------------------------- #
# Several migration tests need a database whose schema is at a specific historical
# revision, produced by alembic itself rather than by create_all. Each such
# `python -m alembic upgrade <rev>` subprocess costs ~0.85 s, almost all of it
# interpreter start plus the alembic/SQLAlchemy import, and the suite used to pay
# it ~20 times.
#
# These fixtures build the needed revisions ONCE per session, in a single
# subprocess that walks 0004 -> 0005 -> head through the real alembic CLI entry
# point (`alembic.config.main`, exactly what `python -m alembic` calls),
# snapshotting the file after each step. Tests then `shutil.copyfile` a snapshot,
# so every test still starts from a genuinely alembic-migrated database.
#
# Test BODIES keep their own `python -m alembic ...` invocations: the CLI is still
# exercised end to end by
#   * test_wave2_schema.py::test_alembic_lifecycle_upgrade_check_downgrade_reupgrade
#     (check / downgrade / upgrade / check),
#   * test_lawschool_fact_upgrade.py (upgrade head, downgrade, re-upgrade, and the
#     fresh-database upgrade), and
#   * test_wave1_settings_privacy.py::test_f2_migration_maps_legacy_and_guards_unknown
#     (upgrade head, downgrade, re-upgrade, and the must-fail upgrade).
# Only the duplicated *provisioning* runs were removed.

#: Revision snapshots to build, in upgrade order. Keys are what tests ask for.
_ALEMBIC_SNAPSHOTS = ("0004_wave1_foundation", "0005_language_check", "head")

_SNAPSHOT_DRIVER = """
import shutil, sys
import alembic.config
db, pairs = sys.argv[1], sys.argv[2:]
for i in range(0, len(pairs), 2):
    rev, out = pairs[i], pairs[i + 1]
    alembic.config.main(argv=["upgrade", rev], prog="alembic")
    shutil.copyfile(db, out)
"""


@pytest.fixture(scope="session")
def _alembic_snapshot_build(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("alembic_snapshots")
    live = root / "build.db"
    outputs = {rev: root / f"{rev}.db" for rev in _ALEMBIC_SNAPSHOTS}
    argv: list[str] = [str(live)]
    for rev in _ALEMBIC_SNAPSHOTS:
        argv += [rev, str(outputs[rev])]

    result = subprocess.run(
        [sys.executable, "-c", _SNAPSHOT_DRIVER, *argv],
        capture_output=True,
        text=True,
        cwd=str(BACKEND),
        env={**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{live}"},
    )
    assert result.returncode == 0, (
        "building the alembic revision snapshots failed:\n"
        f"{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )
    for rev, path in outputs.items():
        assert path.exists(), f"snapshot for {rev} was not written"
    return outputs, result


@pytest.fixture(scope="session")
def alembic_snapshots(_alembic_snapshot_build) -> dict[str, Path]:
    """``{revision: path}`` of read-only databases migrated by the real alembic.

    Copy one with ``shutil.copyfile`` to get a writable database at that
    revision. Never mutate the snapshots themselves.
    """
    return _alembic_snapshot_build[0]


@pytest.fixture(scope="session")
def alembic_snapshot_run(_alembic_snapshot_build) -> subprocess.CompletedProcess:
    """The real ``CompletedProcess`` of the batched alembic upgrade that produced
    the snapshots -- so a fixture that used to assert ``returncode == 0`` on its
    own upgrade still asserts it against an actual alembic run."""
    return _alembic_snapshot_build[1]


@pytest.fixture()
def alembic_db(alembic_snapshots, tmp_path):
    """``alembic_db(revision, name=...) -> str``: a writable copy of a snapshot."""

    def factory(revision: str, name: str = "db") -> str:
        target = tmp_path / f"{name}.db"
        shutil.copyfile(alembic_snapshots[revision], target)
        return str(target)

    return factory
