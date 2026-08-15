#!/usr/bin/env python3
"""Reject edits to existing Alembic revisions; require forward-only migrations."""

from __future__ import annotations

import subprocess
import sys


VERSIONS = "backend/app/db/migrations/versions/"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


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
    )
    violations = []
    for line in changed.splitlines():
        if not line:
            continue
        status, *_paths = line.split("\t")
        if status != "A":
            violations.append(line)

    if violations:
        print("Applied migration history is immutable; add a forward revision instead:", file=sys.stderr)
        print("\n".join(violations), file=sys.stderr)
        return 1

    print(f"Migration immutability passed for {base}..{head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
