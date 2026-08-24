#!/usr/bin/env python3
"""Produce executed, privacy-safe NYAY-5 acceptance attestations.

The producer executes each native/CI command itself and derives evidence rows
from the real browser, PostgreSQL, orchestrator, screenshot, and manifest
artifacts. It never accepts caller-supplied PASS booleans.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence


CI_DIRECTORY = Path(__file__).resolve().parent
if str(CI_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(CI_DIRECTORY))
from evidence_manifest import verify as verify_manifest


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
EXECUTION_IDS = (
    "native:frontend-typecheck",
    "native:frontend-lint",
    "native:frontend-unit",
    "native:frontend-production-build",
    "evidence:browser-report",
    "evidence:screenshots",
    "evidence:service-logs",
    "evidence:privacy-scan",
    "evidence:sha256-manifest",
    "ci:policy-verifier",
    "ci:required-job-fail-closed",
    "ci:prospective-merge",
)
EXPECTED_COMMANDS: dict[str, tuple[str, ...]] = {
    "native:frontend-typecheck": ("npm", "run", "typecheck"),
    "native:frontend-lint": ("npm", "run", "lint"),
    "native:frontend-unit": ("npm", "run", "test:run"),
    "native:frontend-production-build": ("npm", "run", "build"),
    "ci:policy-verifier": (
        sys.executable,
        "scripts/ci/verify_nyayone_ci.py",
    ),
    "ci:required-job-fail-closed": (
        sys.executable,
        "-m",
        "unittest",
        "scripts.ci.test_ci_policies.PolicyOracleTests."
        "test_nyay5_required_pipeline_cannot_skip_a_producer_or_attestation",
    ),
}
SHA256 = re.compile(r"^[0-9a-f]{40}$")
PULL_REQUEST_REF = re.compile(r"^refs/pull/[1-9][0-9]*/merge$")


def _strict_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON mapping key")
        result[key] = value
    return result


def _read_json(path: Path) -> object | None:
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            return None
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_strict_json_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("non-finite JSON number")
            ),
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return None


def _command_runner(command: Sequence[str], cwd: Path) -> bool:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


def _head_reader(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _row(
    identity: str,
    *,
    executed: bool,
    passed: bool,
    evidence_count: int,
) -> dict[str, object]:
    return {
        "id": identity,
        "executed": executed,
        "skipped": False,
        "pass": passed,
        "evidenceCount": evidence_count if evidence_count > 0 else 0,
        "selectorCount": None,
    }


def _browser_observation(value: object) -> tuple[bool, int, bool]:
    if not isinstance(value, dict):
        return False, 0, False
    rows = value.get("rows")
    if not isinstance(rows, list) or not rows:
        return False, 0, False
    names = [row.get("name") for row in rows if isinstance(row, dict)]
    unique = (
        len(names) == len(rows)
        and all(isinstance(name, str) and name for name in names)
        and len(names) == len(set(names))
    )
    rows_pass = all(
        isinstance(row, dict)
        and row.get("pass") is True
        and isinstance(row.get("metrics"), dict)
        and row["metrics"].get("executed") is True
        for row in rows
    )
    basic_pass = bool(
        value.get("gate") == "nyay5_profile_browser"
        and value.get("target")
        == "isolated-loopback-real-api-postgresql-chromium"
        and value.get("status") == "PASS"
        and value.get("executed") is True
        and value.get("inventoryExact") is True
        and value.get("total") == len(rows)
        and value.get("passed") == len(rows)
        and value.get("failed") == 0
        and unique
        and rows_pass
        and all(
            value.get(key) is None
            for key in ("failureClass", "failureStage", "failureCode")
        )
    )
    privacy_pass = any(
        isinstance(row, dict)
        and row.get("name") == "evidence_privacy_and_mutants"
        and row.get("pass") is True
        and isinstance(row.get("metrics"), dict)
        and row["metrics"].get("executed") is True
        for row in rows
    )
    screenshots = value.get("artifacts")
    screenshot_count = (
        screenshots.get("screenshots")
        if isinstance(screenshots, dict)
        and isinstance(screenshots.get("screenshots"), int)
        and not isinstance(screenshots.get("screenshots"), bool)
        else 0
    )
    return basic_pass, screenshot_count, privacy_pass


def _screenshot_observation(root: Path, declared: int) -> tuple[bool, int]:
    directory = root / "screenshots"
    try:
        if stat.S_ISLNK(directory.lstat().st_mode) or not directory.is_dir():
            return False, 0
        files = sorted(directory.glob("*.png"))
        safe = all(
            not stat.S_ISLNK(path.lstat().st_mode)
            and stat.S_ISREG(path.lstat().st_mode)
            and path.stat().st_size > 0
            for path in files
        )
    except OSError:
        return False, 0
    return safe and declared > 0 and len(files) == declared, len(files)


def _orchestrator_observation(value: object) -> tuple[bool, bool]:
    if not isinstance(value, dict) or set(value) != {
        "gate",
        "executed",
        "status",
        "services",
        "scratchCleanup",
        "browserExitCode",
        "serviceLogsCaptured",
    }:
        return False, False
    services = value.get("services")
    cleanup = value.get("scratchCleanup")
    passed = bool(
        value.get("gate") == "nyay5-profile-browser-orchestrator-v1"
        and value.get("executed") is True
        and value.get("status") == "PASS"
        and isinstance(services, dict)
        and set(services) == {
            "postgresReady",
            "apiReady",
            "otpCaptureReady",
            "productionPreviewReady",
            "serviceWorkerActive",
        }
        and all(item is True for item in services.values())
        and cleanup == {"created": 1, "removed": 1, "inventoryMatch": True}
        and value.get("browserExitCode") == 0
        and value.get("serviceLogsCaptured") is True
    )
    return passed, value.get("serviceLogsCaptured") is True


def _privacy_observation(
    browser_privacy: bool,
    postgres: object,
    otp_postgres: object,
) -> tuple[bool, int]:
    postgres_pass = bool(
        isinstance(postgres, dict)
        and postgres.get("gate") == "nyay5_postgres"
        and postgres.get("status") == "PASS"
        and postgres.get("executed") is True
        and postgres.get("privacy_scan")
        == {"scanned": True, "findings": 0, "passed": True}
    )
    otp_pass = bool(
        isinstance(otp_postgres, dict)
        and otp_postgres.get("gate") == "nyay4_postgres_otp"
        and otp_postgres.get("status") == "PASS"
        and otp_postgres.get("executed") is True
        and otp_postgres.get("privacy_findings") == 0
    )
    return browser_privacy and postgres_pass and otp_pass, 3


def _prospective_merge_observation(
    root: Path,
    environment: Mapping[str, str],
    head_reader: Callable[[Path], str],
) -> bool:
    event = environment.get("GITHUB_EVENT_NAME", "")
    sha = environment.get("GITHUB_SHA", "")
    ref = environment.get("GITHUB_REF", "")
    base_ref = environment.get("GITHUB_BASE_REF", "")
    if SHA256.fullmatch(sha) is None or head_reader(root) != sha:
        return False
    if event == "pull_request":
        return PULL_REQUEST_REF.fullmatch(ref) is not None and base_ref == "main"
    if event in {"push", "workflow_dispatch"}:
        return ref == "refs/heads/main" and base_ref == ""
    return False


def build_attestation(
    *,
    root: Path,
    browser: Path,
    orchestrator: Path,
    postgres: Path,
    otp_postgres: Path,
    manifest_root: Path,
    environment: Mapping[str, str],
    command_runner: Callable[[Sequence[str], Path], bool] = _command_runner,
    head_reader: Callable[[Path], str] = _head_reader,
) -> dict[str, object]:
    command_results: dict[str, bool] = {}
    for identity, command in EXPECTED_COMMANDS.items():
        cwd = FRONTEND if identity.startswith("native:frontend-") else root
        command_results[identity] = command_runner(command, cwd)

    browser_value = _read_json(browser)
    orchestrator_value = _read_json(orchestrator)
    postgres_value = _read_json(postgres)
    otp_postgres_value = _read_json(otp_postgres)
    browser_pass, declared_screenshots, browser_privacy = _browser_observation(
        browser_value
    )
    screenshots_pass, screenshot_count = _screenshot_observation(
        manifest_root, declared_screenshots
    )
    orchestrator_pass, service_logs_captured = _orchestrator_observation(
        orchestrator_value
    )
    privacy_pass, privacy_count = _privacy_observation(
        browser_privacy, postgres_value, otp_postgres_value
    )
    manifest_count, manifest_failures = verify_manifest(manifest_root)
    manifest_pass = manifest_count > 0 and not manifest_failures
    prospective_pass = _prospective_merge_observation(
        root, environment, head_reader
    )

    facts: dict[str, tuple[bool, bool, int]] = {
        identity: (True, passed, 1 if passed else 0)
        for identity, passed in command_results.items()
    }
    facts.update({
        "evidence:browser-report": (
            browser_value is not None,
            browser_pass,
            len(browser_value.get("rows", []))
            if isinstance(browser_value, dict) and browser_pass else 0,
        ),
        "evidence:screenshots": (
            manifest_root.exists(), screenshots_pass, screenshot_count
        ),
        "evidence:service-logs": (
            orchestrator_value is not None,
            orchestrator_pass and service_logs_captured,
            4 if orchestrator_pass and service_logs_captured else 0,
        ),
        "evidence:privacy-scan": (
            all(value is not None for value in (
                browser_value, postgres_value, otp_postgres_value
            )),
            privacy_pass,
            privacy_count if privacy_pass else 0,
        ),
        "evidence:sha256-manifest": (
            manifest_root.exists(), manifest_pass,
            manifest_count if manifest_pass else 0,
        ),
        "ci:prospective-merge": (True, prospective_pass, 1 if prospective_pass else 0),
    })
    executions = [
        _row(
            identity,
            executed=facts[identity][0],
            passed=facts[identity][1],
            evidence_count=facts[identity][2],
        )
        for identity in EXECUTION_IDS
    ]
    passed = all(row["pass"] is True for row in executions)
    return {
        "gate": "nyay5_acceptance_attestations_v1",
        "status": "PASS" if passed else "FAIL",
        "executed": True,
        "executions": executions,
    }


def _write_report(path: Path, report: dict[str, object]) -> None:
    if not path.is_absolute():
        raise ValueError("NYAY-5 attestation output must be absolute")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise ValueError("NYAY-5 attestation parent must not be a symlink")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--orchestrator", type=Path, required=True)
    parser.add_argument("--postgres", type=Path, required=True)
    parser.add_argument("--otp-postgres", type=Path, required=True)
    parser.add_argument("--manifest-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence_paths = (
        args.browser,
        args.orchestrator,
        args.postgres,
        args.otp_postgres,
        args.manifest_root,
        args.output,
    )
    if any(not path.is_absolute() for path in evidence_paths):
        parser.error("all NYAY-5 evidence paths must be absolute")
    report = build_attestation(
        root=ROOT,
        browser=args.browser,
        orchestrator=args.orchestrator,
        postgres=args.postgres,
        otp_postgres=args.otp_postgres,
        manifest_root=args.manifest_root,
        environment=os.environ,
    )
    _write_report(args.output, report)
    print(json.dumps({
        "gate": report["gate"],
        "status": report["status"],
        "executed": report["executed"],
    }))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
