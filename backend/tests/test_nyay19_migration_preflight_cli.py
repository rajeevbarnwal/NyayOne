"""Sanitized operator contracts for NYAY-19 migration preflight/execution."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

import scripts.nyay19_migrate as migrate_cli
import scripts.nyay19_migration_preflight as preflight_cli
from app.db.migration_release_guard import (
    APPROVAL_WINDOW_END_ENV,
    CHANGE_REFERENCE_ENV,
    FORCE_APPROVAL_ENV,
    FREEZE_ACK_ENV,
    ISOLATED_EXECUTION_ENV,
    PREFLIGHT_PATH_ENV,
    PREFLIGHT_SHA_ENV,
    TARGET_REVISION,
)


BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def test_preflight_pins_frozen_source_authority():
    assert preflight_cli._source_authority_is_valid() is True
    assert preflight_cli.TARGET_SHA256 == (
        "8b462f0d35839a0edd7166f4e5881fafaeb368f8816cba673144d3c745270dbe"
    )
    assert preflight_cli.source_authority_is_valid() is True


def test_preflight_and_execution_share_frozen_source_authority(monkeypatch):
    monkeypatch.setattr(preflight_cli, "source_authority_is_valid", lambda: False)
    assert preflight_cli._source_authority_is_valid() is False


def test_preflight_cli_requires_and_carries_change_window_metadata(
    tmp_path,
    monkeypatch,
    capsys,
):
    with pytest.raises(SystemExit) as missing:
        preflight_cli.main(["--output", str(tmp_path / "missing.json")])
    assert missing.value.code == 2
    capsys.readouterr()

    observed = {}

    def capture(_url, *, change_reference, approval_window_ends_at):
        observed["change_reference"] = change_reference
        observed["approval_window_ends_at"] = approval_window_ends_at
        return {"verdict": "FAIL", "code": "sanitized"}, 1

    monkeypatch.setattr(preflight_cli, "build_report", capture)
    output = tmp_path / "report.json"
    assert preflight_cli.main(
        [
            "--output",
            str(output),
            "--change-reference",
            "NYAY-19-RELEASE-001",
            "--approval-window-ends-at",
            "2026-08-22T12:00:00Z",
        ]
    ) == 1
    assert observed == {
        "change_reference": "NYAY-19-RELEASE-001",
        "approval_window_ends_at": "2026-08-22T12:00:00Z",
    }


def test_preflight_cli_rejects_noncanonical_window_without_connecting(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        preflight_cli,
        "_source_authority_is_valid",
        lambda: (_ for _ in ()).throw(AssertionError("source must not run")),
    )
    output = tmp_path / "invalid-window.json"
    assert preflight_cli.main(
        [
            "--output",
            str(output),
            "--change-reference",
            "NYAY-19-RELEASE-001",
            "--approval-window-ends-at",
            "2026-08-22T12:00:00+00:00",
        ]
    ) == 1
    expected = {
        "verdict": "FAIL",
        "code": "preflight_rejected",
        "parent_revision": "0019_otp_security_authority",
        "target_revision": "0020_auth_retention_lifecycle",
    }
    assert json.loads(capsys.readouterr().out) == expected
    assert json.loads(output.read_text(encoding="utf-8")) == expected


def test_operations_contract_pins_irreversible_fail_closed_controls():
    migration = preflight_cli.TARGET_PATH.read_text(encoding="utf-8")
    runbook = (
        ROOT / "docs/operations/nyay19-auth-retention-migration.md"
    ).read_text(encoding="utf-8")
    alembic_environment = (
        BACKEND / "app/db/migrations/env.py"
    ).read_text(encoding="utf-8")
    db_gate = (BACKEND / "scripts/db_gate.sh").read_text(encoding="utf-8")

    for required in (
        "SET LOCAL lock_timeout = '5000ms'",
        "SET LOCAL statement_timeout = '30000ms'",
        "IN SHARE ROW EXCLUSIVE MODE NOWAIT",
        "student.auth.deletion_backfill_frozen",
    ):
        assert required in migration
    for required in (
        "PO, Security/Privacy, DBA, and Engineering",
        "pre-freeze backup can resurrect",
        "Forward repair is the default rollback plan",
        "I_ACKNOWLEDGE_NYAY19_PRIVACY_FREEZE_IS_IRREVERSIBLE",
        "one owned singleton schedule",
        "authority_state_digest",
        "approval_window_ends_at",
        "preflight_observed_at",
        "inet_server_addr()",
        "public.alembic_version",
        "new path",
    ):
        assert required in runbook
    assert "enforce_nyay19_migration_release_guard" in alembic_environment
    assert "enforce_nyay19_migration_postflight" in alembic_environment
    assert "runtime_migration_intent" in alembic_environment
    assert "install_authenticated_migration_loader" in alembic_environment
    assert "source_authority_is_valid" in alembic_environment
    run_position = alembic_environment.rindex("context.run_migrations()")
    postflight_position = alembic_environment.index(
        "enforce_nyay19_migration_postflight(connection)"
    )
    restore_position = alembic_environment.index(
        "if restore_loader is not None:",
        postflight_position,
    )
    assert run_position < postflight_position < restore_position
    assert "export NYAY19_ISOLATED_MIGRATION_EXECUTE=1" in db_gate


def test_non_postgres_preflight_is_non_authoritative_and_sanitized(tmp_path):
    database = tmp_path / "nyay19-preflight.db"
    output = tmp_path / "preflight.json"
    database_url = f"sqlite+pysqlite:///{database}"
    sentinel = "sensitive-preflight-sentinel"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/nyay19_migration_preflight.py",
            "--output",
            str(output),
            "--change-reference",
            "NYAY-19-RELEASE-001",
            "--approval-window-ends-at",
            "2026-08-22T12:00:00Z",
        ],
        cwd=BACKEND,
        env={
            **os.environ,
            "APP_ENV": "testing",
            "DATABASE_URL": database_url,
            "REGISTRATION_SECRET": sentinel,
            "REGISTRATION_LOOKUP_SECRET": sentinel,
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 78
    expected = {
        "verdict": "NOT_AUTHORITATIVE",
        "code": "postgresql_16_pgvector_required",
        "parent_revision": "0019_otp_security_authority",
        "target_revision": "0020_auth_retention_lifecycle",
    }
    assert json.loads(result.stdout) == expected
    assert json.loads(output.read_text(encoding="utf-8")) == expected
    assert output.stat().st_mode & 0o777 == 0o600
    combined = result.stdout + result.stderr + output.read_text(encoding="utf-8")
    for forbidden in (database_url, str(database), sentinel):
        assert forbidden not in combined


def test_migration_wrapper_requires_explicit_execute_before_subprocess(
    tmp_path,
    monkeypatch,
    capsys,
):
    def forbidden_subprocess(*_args, **_kwargs):
        raise AssertionError("migration subprocess must not start")

    monkeypatch.setattr(migrate_cli.subprocess, "run", forbidden_subprocess)
    result = migrate_cli.main(
        [
            "--approved-preflight",
            str(tmp_path / "missing.json"),
            "--approved-sha256",
            "a" * 64,
            "--change-reference",
            "NYAY-19-RELEASE-001",
            "--approval-window-ends-at",
            "2026-08-22T12:00:00Z",
            "--acknowledge-irreversible-freeze",
            "I_ACKNOWLEDGE_NYAY19_PRIVACY_FREEZE_IS_IRREVERSIBLE",
        ]
    )
    assert result == 78
    assert json.loads(capsys.readouterr().out) == {
        "verdict": "BLOCKED",
        "code": "explicit_execution_required",
        "target_revision": "0020_auth_retention_lifecycle",
    }


def test_preflight_report_publish_is_atomic_new_only_and_never_overwrites(
    tmp_path,
):
    report = {"verdict": "FAIL", "code": "sanitized"}
    fresh = tmp_path / "fresh.json"
    preflight_cli._write_report(fresh, report)
    assert json.loads(fresh.read_text(encoding="utf-8")) == report
    assert fresh.stat().st_mode & 0o777 == 0o600
    assert fresh.stat().st_nlink == 1

    valuable = tmp_path / "valuable.txt"
    valuable.write_bytes(b"valuable-bytes")
    valuable.chmod(0o600)
    with pytest.raises(OSError):
        preflight_cli._write_report(valuable, report)
    assert valuable.read_bytes() == b"valuable-bytes"

    symlink = tmp_path / "symlink.json"
    symlink.symlink_to(valuable)
    with pytest.raises(OSError):
        preflight_cli._write_report(symlink, report)
    assert symlink.is_symlink()
    assert valuable.read_bytes() == b"valuable-bytes"

    hardlink = tmp_path / "hardlink.json"
    os.link(valuable, hardlink)
    with pytest.raises(OSError):
        preflight_cli._write_report(hardlink, report)
    assert hardlink.read_bytes() == b"valuable-bytes"
    assert valuable.read_bytes() == b"valuable-bytes"
    assert "os.replace" not in Path(preflight_cli.__file__).read_text(
        encoding="utf-8"
    )


def test_preflight_cli_sanitizes_existing_output_refusal(
    tmp_path,
    monkeypatch,
    capsys,
):
    valuable = tmp_path / "approved.json"
    valuable.write_bytes(b"valuable-bytes")
    monkeypatch.setattr(
        preflight_cli,
        "build_report",
        lambda _url, **_metadata: (
            {"verdict": "PASS", "code": "should-not-publish"},
            0,
        ),
    )
    assert preflight_cli.main(
        [
            "--output",
            str(valuable),
            "--change-reference",
            "NYAY-19-RELEASE-001",
            "--approval-window-ends-at",
            "2026-08-22T12:00:00Z",
        ]
    ) == 1
    assert valuable.read_bytes() == b"valuable-bytes"
    assert json.loads(capsys.readouterr().out) == {
        "verdict": "FAIL",
        "code": "preflight_rejected",
        "parent_revision": "0019_otp_security_authority",
        "target_revision": "0020_auth_retention_lifecycle",
    }


def test_migration_wrapper_preserves_symlink_identity_and_forces_approval(
    tmp_path,
    monkeypatch,
    capsys,
):
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    link = tmp_path / "approved.json"
    link.symlink_to(target)
    observed = {}

    def capture_subprocess(args, **kwargs):
        observed["args"] = args
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 1)

    monkeypatch.setattr(migrate_cli.subprocess, "run", capture_subprocess)
    monkeypatch.setenv(ISOLATED_EXECUTION_ENV, "1")
    monkeypatch.setenv("APP_ENV", "testing")
    result = migrate_cli.main(
        [
            "--execute",
            "--approved-preflight",
            str(link),
            "--approved-sha256",
            "a" * 64,
            "--change-reference",
            "NYAY-19-RELEASE-001",
            "--approval-window-ends-at",
            "2026-08-22T12:00:00Z",
            "--acknowledge-irreversible-freeze",
            "I_ACKNOWLEDGE_NYAY19_PRIVACY_FREEZE_IS_IRREVERSIBLE",
        ]
    )
    assert result == 1
    assert observed["args"][-2:] == ["upgrade", TARGET_REVISION]
    assert observed["args"][1:5] == ["-E", "-s", "-m", "alembic"]
    config_index = observed["args"].index("-c")
    assert observed["args"][config_index + 1] == str(BACKEND / "alembic.ini")
    assert observed["env"][PREFLIGHT_PATH_ENV] == str(link.absolute())
    assert observed["env"][APPROVAL_WINDOW_END_ENV] == "2026-08-22T12:00:00Z"
    assert observed["env"][FORCE_APPROVAL_ENV] == "1"
    assert observed["env"]["APP_ENV"] == "production"
    assert ISOLATED_EXECUTION_ENV not in observed["env"]
    assert json.loads(capsys.readouterr().out)["code"] == "migration_rejected"


def test_successful_wrapper_reports_verified_target_not_false_applied(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        migrate_cli.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(args, 0),
    )
    result = migrate_cli.main(
        [
            "--execute",
            "--approved-preflight",
            str(tmp_path / "approved.json"),
            "--approved-sha256",
            "a" * 64,
            "--change-reference",
            "NYAY-19-RELEASE-001",
            "--approval-window-ends-at",
            "2026-08-22T12:00:00Z",
            "--acknowledge-irreversible-freeze",
            "I_ACKNOWLEDGE_NYAY19_PRIVACY_FREEZE_IS_IRREVERSIBLE",
        ]
    )
    assert result == 0
    assert json.loads(capsys.readouterr().out) == {
        "verdict": "PASS",
        "code": "migration_target_verified",
        "target_revision": TARGET_REVISION,
    }


def test_wrapper_allows_verified_noop_without_approval_and_strips_inherited_values(
    monkeypatch,
    capsys,
):
    observed = {}

    def capture_subprocess(args, **kwargs):
        observed["args"] = args
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(migrate_cli.subprocess, "run", capture_subprocess)
    for name in (
        ISOLATED_EXECUTION_ENV,
        PREFLIGHT_PATH_ENV,
        PREFLIGHT_SHA_ENV,
        CHANGE_REFERENCE_ENV,
        APPROVAL_WINDOW_END_ENV,
        FREEZE_ACK_ENV,
    ):
        monkeypatch.setenv(name, "inherited-value-must-not-be-trusted")
    monkeypatch.setenv("ALEMBIC_CONFIG", "/tmp/untrusted-alembic.ini")
    monkeypatch.setenv("PYTHONPATH", "/tmp/untrusted-pythonpath")
    monkeypatch.setenv("PYTHONHOME", "/tmp/untrusted-pythonhome")
    monkeypatch.setenv("__PYVENV_LAUNCHER__", "/tmp/untrusted-python")

    assert migrate_cli.main(["--execute"]) == 0
    assert observed["args"][-2:] == ["upgrade", TARGET_REVISION]
    assert observed["env"]["APP_ENV"] == "production"
    assert observed["env"][FORCE_APPROVAL_ENV] == "1"
    assert observed["args"][1:5] == ["-E", "-s", "-m", "alembic"]
    config_index = observed["args"].index("-c")
    assert observed["args"][config_index + 1] == str(BACKEND / "alembic.ini")
    for name in (
        ISOLATED_EXECUTION_ENV,
        PREFLIGHT_PATH_ENV,
        PREFLIGHT_SHA_ENV,
        CHANGE_REFERENCE_ENV,
        APPROVAL_WINDOW_END_ENV,
        FREEZE_ACK_ENV,
        "ALEMBIC_CONFIG",
        "PYTHONPATH",
        "PYTHONHOME",
        "__PYVENV_LAUNCHER__",
    ):
        assert name not in observed["env"]
    assert json.loads(capsys.readouterr().out) == {
        "verdict": "PASS",
        "code": "migration_target_verified",
        "target_revision": TARGET_REVISION,
    }
