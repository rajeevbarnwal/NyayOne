#!/usr/bin/env python3
"""Reject edits to frozen Alembic history; require forward-only migrations."""

from __future__ import annotations

import re
import subprocess
import sys


VERSIONS = "backend/app/db/migrations/versions/"
LEDGER = "backend/app/db/migrations/MIGRATION_SHA256_LEDGER.json"
BASELINE_LAST_ORDINAL = 15
FORWARD_REVISION = re.compile(
    rf"^{re.escape(VERSIONS)}(?P<ordinal>[0-9]{{4}})_[a-z0-9_]+\.py$"
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def git_path_exists(revision: str, path: str) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{revision}:{path}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def violations_from_name_status(
    changed: str,
    *,
    ledger_existed_at_base: bool,
) -> list[str]:
    """Classify a scoped ``git diff --name-status`` fail closed.

    The ledger may be added once on the baseline-establishing change.  Once it
    exists at the comparison base, every modification, deletion and rename is a
    violation.  Historical migration paths are equally immutable; the only
    allowed additions are canonical revisions whose numeric prefix is after the
    frozen 0015 baseline.
    """

    violations: list[str] = []
    for line in changed.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) < 2:
            violations.append(f"malformed git name-status record: {line}")
            continue
        status = fields[0]
        paths = fields[1:]
        if status == "A" and len(paths) == 1:
            path = paths[0]
            if path == LEDGER and not ledger_existed_at_base:
                continue
            match = FORWARD_REVISION.fullmatch(path)
            if match is not None and int(match.group("ordinal")) > BASELINE_LAST_ORDINAL:
                continue
        violations.append(line)
    return violations


def main() -> int:
    base = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    head = sys.argv[2].strip() if len(sys.argv) > 2 else "HEAD"
    if not base or set(base) == {"0"}:
        base = git("rev-parse", f"{head}^")

    changed = git(
        "diff",
        "--name-status",
        "--find-renames",
        base,
        head,
        "--",
        VERSIONS,
        LEDGER,
    )
    violations = violations_from_name_status(
        changed,
        ledger_existed_at_base=git_path_exists(base, LEDGER),
    )

    if violations:
        print(
            "Applied migration history and its SHA-256 ledger are immutable; "
            "add a canonical forward revision after 0015 instead:",
            file=sys.stderr,
        )
        print("\n".join(violations), file=sys.stderr)
        return 1

    print(f"Migration immutability passed for {base}..{head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
