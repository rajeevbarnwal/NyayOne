#!/usr/bin/env python3
"""Verify every tracked SHA256SUMS.txt against the committed working-tree bytes."""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRY = re.compile(r"^([0-9a-f]{64}) [ *](.+)$")


def tracked_manifests() -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "*SHA256SUMS.txt"], cwd=ROOT, text=True
    )
    return [ROOT / line for line in output.splitlines() if line]


def verify(manifest: Path) -> tuple[int, list[str]]:
    failures: list[str] = []
    seen: set[str] = set()
    count = 0
    base = manifest.parent.resolve()
    base_relative = manifest.parent.relative_to(ROOT)
    tracked_output = subprocess.check_output(
        ["git", "ls-files", "--", base_relative.as_posix()], cwd=ROOT, text=True
    )
    tracked = {
        Path(line).relative_to(base_relative).as_posix()
        for line in tracked_output.splitlines()
        if line
    }
    for number, raw in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        if not raw:
            continue
        match = ENTRY.fullmatch(raw)
        if not match:
            failures.append(f"{manifest.relative_to(ROOT)}:{number}: malformed entry")
            continue
        expected, relative = match.groups()
        if relative in seen:
            failures.append(f"{manifest.relative_to(ROOT)}:{number}: duplicate {relative}")
            continue
        seen.add(relative)
        if relative not in tracked:
            failures.append(f"{manifest.relative_to(ROOT)}:{number}: untracked entry {relative}")
            continue
        candidate = (manifest.parent / relative).resolve()
        if candidate == manifest.resolve() or not candidate.is_relative_to(base):
            failures.append(f"{manifest.relative_to(ROOT)}:{number}: unsafe path {relative}")
            continue
        if not candidate.is_file():
            failures.append(f"{manifest.relative_to(ROOT)}:{number}: missing {relative}")
            continue
        actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if actual != expected:
            failures.append(
                f"{manifest.relative_to(ROOT)}:{number}: checksum mismatch for {relative}"
            )
            continue
        count += 1
    if not seen:
        failures.append(f"{manifest.relative_to(ROOT)}: manifest is empty")
    missing_entries = sorted(tracked - {manifest.name} - seen)
    for relative in missing_entries:
        failures.append(f"{manifest.relative_to(ROOT)}: tracked file is not listed: {relative}")
    return count, failures


def main() -> int:
    manifests = tracked_manifests()
    if not manifests:
        print("no tracked SHA256SUMS.txt manifests found", file=sys.stderr)
        return 1
    verified = 0
    failures: list[str] = []
    for manifest in manifests:
        count, manifest_failures = verify(manifest)
        verified += count
        failures.extend(manifest_failures)
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"SHA-256 manifests passed: {len(manifests)} manifests, {verified} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
