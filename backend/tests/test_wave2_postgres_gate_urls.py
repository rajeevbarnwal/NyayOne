"""Regression tests for credential-safe PostgreSQL gate URL replacement."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.engine import make_url

from scripts import wave2_postgres_gate as gate


PASSWORD = "p@ss:/?#% with spaces"
BASE_URL = make_url(
    "postgresql+psycopg://gate-user@localhost:5432/legalsaathi"
).set(password=PASSWORD).render_as_string(hide_password=False)


@pytest.mark.parametrize("database", ["postgres", "qa_scratch_01"])
def test_database_name_replacement_preserves_credentials(database: str):
    rendered = gate.database_url_for_name(BASE_URL, database)
    parsed = make_url(rendered)

    assert parsed.drivername == "postgresql+psycopg"
    assert parsed.username == "gate-user"
    assert parsed.password == PASSWORD
    assert parsed.host == "localhost"
    assert parsed.port == 5432
    assert parsed.database == database


def test_scratch_url_targets_requested_database_without_masking_password():
    rendered = gate.scratch_url(BASE_URL, "qa_scratch_02")

    assert make_url(rendered).database == "qa_scratch_02"
    assert make_url(rendered).password == PASSWORD
    assert ":***@" not in rendered


def test_old_string_conversion_masks_password_and_is_not_executable_contract():
    old_rendering = str(make_url(BASE_URL).set(database="postgres"))

    assert ":***@" in old_rendering
    assert make_url(old_rendering).password == "***"
    assert gate.database_url_for_name(BASE_URL, "postgres") != old_rendering


def test_admin_execute_uses_postgres_database_and_retains_real_password(monkeypatch):
    observed: dict[str, object] = {}

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, statement):
            observed["statement"] = str(statement)

    class Engine:
        def connect(self):
            return Connection()

        def dispose(self):
            observed["disposed"] = True

    def fake_create_engine(url, **kwargs):
        observed["url"] = url
        observed["kwargs"] = kwargs
        return Engine()

    monkeypatch.setattr("sqlalchemy.create_engine", fake_create_engine)

    gate.admin_execute(BASE_URL, "SELECT 1")

    parsed = make_url(str(observed["url"]))
    assert parsed.database == "postgres"
    assert parsed.password == PASSWORD
    assert observed["kwargs"] == {"isolation_level": "AUTOCOMMIT"}
    assert observed["statement"] == "SELECT 1"
    assert observed["disposed"] is True


def test_diagnostic_serialization_stays_redacted():
    executable = gate.database_url_for_name(BASE_URL, "postgres")
    diagnostic = make_url(executable).render_as_string(hide_password=True)
    evidence = json.dumps({"database_url": diagnostic})

    assert PASSWORD not in diagnostic
    assert PASSWORD not in evidence
    assert ":***@" in diagnostic
