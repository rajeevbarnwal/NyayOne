from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from alembic import command as alembic_command
import pytest

import app.db.migration_release_guard as guard


def _config(revision: str):
    return SimpleNamespace(
        cmd_opts=SimpleNamespace(
            cmd=(alembic_command.upgrade, [], []),
            revision=revision,
            sql=False,
            tag=None,
        )
    )


def _intent(revision: str):
    return guard.RuntimeMigrationIntent(
        operation="upgrade",
        destination_revision=revision,
        as_sql=False,
        tag=None,
        dont_mutate=False,
    )


def _connection():
    return SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        engine=SimpleNamespace(url=None),
        in_transaction=lambda: True,
    )


def test_nyay5_is_an_exact_disposable_database_marker():
    assert "nyay5" in guard._ISOLATED_DATABASE_MARKERS


@pytest.mark.parametrize("requested", ["0021_nyay5_profile_boundary", "head"])
def test_nonisolated_guard_denies_0020_to_nyay5_without_new_exact_approval(
    monkeypatch, requested
):
    monkeypatch.setattr(guard, "source_authority_is_valid", lambda: True)
    monkeypatch.setattr(
        guard,
        "_nyay5_module",
        lambda: SimpleNamespace(down_revision=guard.TARGET_REVISION),
    )
    monkeypatch.setattr(guard, "_prepare_authoritative_transaction", lambda _: None)
    monkeypatch.setattr(
        guard, "_current_revision", lambda _: "0020_auth_retention_lifecycle"
    )
    observed = []
    monkeypatch.setattr(guard, "_validate_at_head", lambda _: observed.append("0020"))

    with pytest.raises(
        guard.MigrationApprovalError,
        match="NYAY-5 production approval unavailable",
    ):
        guard.enforce_nyay19_migration_release_guard(
            _config(requested),
            _connection(),
            environment="production",
            environ={guard.FORCE_APPROVAL_ENV: "1"},
            runtime_intent=_intent(requested),
        )
    assert observed == ["0020"]


@pytest.mark.parametrize("requested", ["0021_nyay5_profile_boundary", "head"])
def test_forward_head_cannot_skip_the_digest_approved_0019_to_0020_transition(
    monkeypatch, requested
):
    monkeypatch.setattr(guard, "source_authority_is_valid", lambda: True)
    monkeypatch.setattr(guard, "_prepare_authoritative_transaction", lambda _: None)
    monkeypatch.setattr(
        guard, "_current_revision", lambda _: "0019_otp_security_authority"
    )
    with pytest.raises(guard.MigrationApprovalError, match="database revision rejected"):
        guard.enforce_nyay19_migration_release_guard(
            _config(requested),
            _connection(),
            environment="production",
            environ={guard.FORCE_APPROVAL_ENV: "1"},
            runtime_intent=_intent(requested),
        )


def test_postflight_dispatch_can_validate_exact_nyay5_head(monkeypatch):
    observed = []
    monkeypatch.setattr(
        guard, "_validate_nyay5_at_head", lambda candidate: observed.append(candidate)
    )
    connection = SimpleNamespace(in_transaction=lambda: True)
    guard.enforce_nyay19_migration_postflight(
        connection, expected_revision="0021_nyay5_profile_boundary"
    )
    assert observed == [connection]


def test_offline_migration_environment_is_explicitly_fail_closed():
    source = (guard.VERSIONS_PATH.parent / "env.py").read_text(encoding="utf-8")
    body = source.split("def run_migrations_offline() -> None:", 1)[1].split(
        "def run_migrations_online() -> None:", 1
    )[0]
    assert "raise MigrationApprovalError" in body


def test_authenticated_nyay5_loader_executes_exact_source_bytes():
    module = guard._nyay5_module()
    assert Path(module.__file__).resolve() == guard.APPLICATION_HEAD_SOURCE_PATH
    assert module.revision == guard.APPLICATION_HEAD_REVISION
    assert module.down_revision == guard.TARGET_REVISION
    assert callable(module._validate_postflight)


def test_authenticated_nyay5_loader_rejects_swapped_and_symlinked_source(tmp_path):
    swapped = tmp_path / guard.APPLICATION_HEAD_SOURCE_PATH.name
    swapped.write_bytes(guard.APPLICATION_HEAD_SOURCE_PATH.read_bytes() + b"\n")
    with pytest.raises(guard.MigrationApprovalError):
        guard._load_authenticated_migration_module(
            "nyay5_swapped",
            swapped,
            guard.APPLICATION_HEAD_SOURCE_SHA256,
        )

    linked = tmp_path / "linked_0021.py"
    linked.symlink_to(guard.APPLICATION_HEAD_SOURCE_PATH)
    with pytest.raises(guard.MigrationApprovalError):
        guard._load_authenticated_migration_module(
            "nyay5_linked",
            linked,
            guard.APPLICATION_HEAD_SOURCE_SHA256,
        )


def test_authenticated_alembic_loader_rejects_uninventoried_extra_source(tmp_path):
    from alembic.util import pyfiles

    extra = tmp_path / "0022_unapproved.py"
    extra.write_text("revision = '0022_unapproved'\n", encoding="utf-8")
    restore = guard.install_authenticated_migration_loader()
    try:
        with pytest.raises(guard.MigrationApprovalError):
            pyfiles.load_module_py("unapproved", str(extra))
    finally:
        restore()
