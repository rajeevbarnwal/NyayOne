"""Source/pure contract for the isolated NYAY-5 browser gate control plane."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


BACKEND = Path(__file__).resolve().parents[1]
CONTROL = BACKEND / "scripts/nyay5_browser_gate_control.py"


def _module():
    return importlib.import_module("scripts.nyay5_browser_gate_control")


def test_control_plane_is_literal_loopback_and_marker_scoped() -> None:
    control = _module()
    accepted = control.validated_control_url(
        "postgresql+psycopg://synthetic:synthetic@127.0.0.1:5432/nyayone_ci"
    )
    assert accepted.host == "127.0.0.1"
    for rejected in (
        "postgresql://synthetic:synthetic@localhost:5432/nyayone_ci",
        "postgresql://synthetic:synthetic@database.internal:5432/nyayone_ci",
        "postgresql://synthetic:synthetic@127.0.0.1:5432/nyayone_ci?sslmode=disable",
    ):
        with pytest.raises(ValueError):
            control.validated_control_url(rejected)
    assert control.SCRATCH_PREFIX == "nyay5_profile_browser_"
    assert control.valid_scratch_name(f"{control.SCRATCH_PREFIX}{'a' * 32}") is True
    assert control.valid_scratch_name("production_nyay5") is False


def test_denial_fixture_inventory_is_exact_and_never_stdout() -> None:
    control = _module()
    assert control.DENIAL_FIXTURE_STATES == (
        "expired",
        "revoked",
        "deleted",
        "wrong_role",
    )
    source = CONTROL.read_text(encoding="utf-8")
    assert "os.open" in source and "0o600" in source
    assert "json.dump" in source
    assert "print(fixture" not in source
    assert "AuthSession" in source
    assert "StudentRegistration" in source
    assert 'dob_hash_state="erased" if erased else "verified"' in source
    assert 'mobile_ct="[erased]" if erased else encrypt(mobile)' in source
    assert "if not erased:" in source


def test_private_fixture_adds_one_admin_cookie_and_exactly_two_ended_m01_targets() -> None:
    control = _module()
    assert control.M01_FIXTURE_SESSION_COUNT == 2
    source = CONTROL.read_text(encoding="utf-8")

    assert 'role="admin"' in source
    assert "keyed_hash(admin_token)" in source
    assert "AuthSession(" in source
    assert "TutorProfile(" in source
    assert "TutorAvailabilitySlot(" in source
    assert "TutoringSession(" in source
    assert 'status="confirmed"' in source
    assert "now - timedelta(hours=" in source
    assert '"admin_session_token": admin_token' in source
    assert '"session_ids": m01_session_ids' in source
    assert '"m01": {' in source
    # Raw bearer and opaque row ids are written only to the private 0600 file.
    assert "print(admin_token" not in source
    assert "print(m01_session_ids" not in source


def test_drop_refuses_every_unowned_database_name() -> None:
    control = _module()
    for name in ("", "postgres", "nyayone_ci", "nyay5_profile_browser_prod"):
        assert control.valid_scratch_name(name) is False


def test_create_prepares_pgvector_before_publishing_private_state() -> None:
    source = CONTROL.read_text(encoding="utf-8")
    extension = source.index('CREATE EXTENSION IF NOT EXISTS vector')
    state = source.index('_write_private_json(\n            state_path', extension)
    assert extension < state


def test_denial_fixtures_require_the_authoritative_application_head() -> None:
    """The browser scratch DB is upgraded to ``head``, not the NYAY-5 checkpoint."""

    source = CONTROL.read_text(encoding="utf-8")
    seed = source[source.index("def seed_denial_fixtures") :]
    seed = seed[: seed.index("def ", 1)]

    assert "revision != postgres_gate.BEHAVIOR_HEAD" in seed
    assert "revision != postgres_gate.PINNED_HEAD" not in seed
