#!/usr/bin/env python3
"""Execute the guarded NYAY-19 production migration after exact approval."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.migration_release_guard import (  # noqa: E402
    APPROVAL_WINDOW_END_ENV,
    CHANGE_REFERENCE_ENV,
    FORCE_APPROVAL_ENV,
    FREEZE_ACK_ENV,
    ISOLATED_EXECUTION_ENV,
    PREFLIGHT_PATH_ENV,
    PREFLIGHT_SHA_ENV,
    TARGET_REVISION,
)


def _emit(verdict: str, code: str) -> None:
    print(
        json.dumps(
            {
                "verdict": verdict,
                "code": code,
                "target_revision": TARGET_REVISION,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-preflight", type=Path)
    parser.add_argument("--approved-sha256")
    parser.add_argument("--change-reference")
    parser.add_argument("--approval-window-ends-at")
    parser.add_argument("--acknowledge-irreversible-freeze")
    arguments = parser.parse_args(argv)
    if not arguments.execute:
        _emit("BLOCKED", "explicit_execution_required")
        return 78

    # Keep the operator-supplied final path component intact so O_NOFOLLOW in
    # the Alembic guard can reject a symlink instead of receiving its resolved
    # target.  This production wrapper also removes the disposable-gate bypass
    # and forces the production guard even if launched from a test shell.  All
    # inherited approval values are removed first: an exact verified 0020 may
    # proceed as a no-op without them, while 0019 remains fail closed unless the
    # operator supplies the complete approved bundle on this invocation.
    environment = dict(os.environ)
    for name in tuple(environment):
        if name == "ALEMBIC_CONFIG" or name.startswith("PYTHON"):
            environment.pop(name, None)
    environment.pop("__PYVENV_LAUNCHER__", None)
    for name in (
        ISOLATED_EXECUTION_ENV,
        PREFLIGHT_PATH_ENV,
        PREFLIGHT_SHA_ENV,
        CHANGE_REFERENCE_ENV,
        APPROVAL_WINDOW_END_ENV,
        FREEZE_ACK_ENV,
    ):
        environment.pop(name, None)
    environment.update(
        {
            "APP_ENV": "production",
            FORCE_APPROVAL_ENV: "1",
        }
    )
    if arguments.approved_preflight is not None:
        environment[PREFLIGHT_PATH_ENV] = os.path.abspath(
            os.fspath(arguments.approved_preflight)
        )
    if arguments.approved_sha256 is not None:
        environment[PREFLIGHT_SHA_ENV] = arguments.approved_sha256
    if arguments.change_reference is not None:
        environment[CHANGE_REFERENCE_ENV] = arguments.change_reference
    if arguments.approval_window_ends_at is not None:
        environment[APPROVAL_WINDOW_END_ENV] = arguments.approval_window_ends_at
    if arguments.acknowledge_irreversible_freeze is not None:
        environment[FREEZE_ACK_ENV] = arguments.acknowledge_irreversible_freeze
    # The Alembic environment independently validates the mode-0600 report,
    # whole-file digest, exact acknowledgement, and change reference before it
    # can open an upgrade transaction.  Suppress driver output because URLs and
    # credentials may appear in exception strings.
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-E",
                "-s",
                "-m",
                "alembic",
                "-c",
                os.fspath(BACKEND / "alembic.ini"),
                "upgrade",
                TARGET_REVISION,
            ],
            cwd=BACKEND,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        _emit("FAIL", "migration_process_unavailable")
        return 1
    if completed.returncode != 0:
        _emit("FAIL", "migration_rejected")
        return 1
    # The same command is intentionally valid as a verified no-op when the
    # target is already exact.  Do not claim that this invocation mutated it.
    _emit("PASS", "migration_target_verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
