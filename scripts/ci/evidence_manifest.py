#!/usr/bin/env python3
"""Seal or verify a complete SHA-256 manifest for one evidence directory."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
from pathlib import Path


MANIFEST_NAME = "SHA256SUMS.txt"
ENTRY = re.compile(r"^([0-9a-f]{64})  ([^\r\n]+)$")


def _inventory(root: Path) -> tuple[dict[str, Path], list[str]]:
    failures: list[str] = []
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError:
        return {}, [f"{root}: evidence path does not exist"]
    except OSError as exc:
        return {}, [f"{root}: evidence path cannot be inspected ({exc.__class__.__name__})"]
    if stat.S_ISLNK(root_mode):
        return {}, [f"{root}: evidence root must not be a symlink"]
    if not stat.S_ISDIR(root_mode):
        return {}, [f"{root}: evidence root must be a directory"]

    files: dict[str, Path] = {}
    def walk_error(exc: OSError) -> None:
        failures.append(
            f"{root}: evidence directory cannot be traversed ({exc.__class__.__name__})"
        )

    for current, directories, names in os.walk(
        root,
        topdown=True,
        followlinks=False,
        onerror=walk_error,
    ):
        current_path = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            candidate = current_path / name
            if name.startswith("."):
                failures.append(
                    f"{candidate.relative_to(root).as_posix()}: hidden evidence path is not allowed"
                )
                continue
            try:
                file_stat = candidate.lstat()
                mode = file_stat.st_mode
            except OSError as exc:
                failures.append(
                    f"{candidate.relative_to(root).as_posix()}: cannot inspect node ({exc.__class__.__name__})"
                )
                continue
            if stat.S_ISLNK(mode):
                failures.append(f"{candidate.relative_to(root).as_posix()}: symlink is not allowed")
                continue
            if not stat.S_ISDIR(mode):
                failures.append(
                    f"{candidate.relative_to(root).as_posix()}: unsupported directory node"
                )
                continue
            retained.append(name)
        directories[:] = retained
        for name in sorted(names):
            candidate = current_path / name
            relative = candidate.relative_to(root).as_posix()
            if name.startswith("."):
                failures.append(f"{relative}: hidden evidence path is not allowed")
                continue
            try:
                file_stat = candidate.lstat()
                mode = file_stat.st_mode
            except OSError as exc:
                failures.append(f"{relative}: cannot inspect node ({exc.__class__.__name__})")
                continue
            if stat.S_ISLNK(mode):
                failures.append(f"{relative}: symlink is not allowed")
            elif not stat.S_ISREG(mode):
                failures.append(f"{relative}: unsupported non-regular node")
            elif file_stat.st_size == 0:
                failures.append(f"{relative}: zero-byte evidence payload is not allowed")
            elif "\n" in relative or "\r" in relative:
                failures.append(f"{relative!r}: newline is not allowed in an evidence path")
            elif relative != MANIFEST_NAME:
                files[relative] = candidate
    if not files:
        failures.append(f"{root}: evidence directory contains zero payload files")
    return files, failures


def seal(root: Path) -> tuple[int, list[str]]:
    files, failures = _inventory(root)
    if failures:
        return 0, failures
    rows: list[str] = []
    for relative, path in sorted(files.items()):
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            failures.append(f"{relative}: cannot read file ({exc.__class__.__name__})")
            continue
        rows.append(f"{digest}  {relative}")
    if failures:
        return 0, failures
    manifest = root / MANIFEST_NAME
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return len(rows), []


def verify(root: Path) -> tuple[int, list[str]]:
    files, failures = _inventory(root)
    manifest = root / MANIFEST_NAME
    if not manifest.exists():
        failures.append(f"{MANIFEST_NAME}: manifest is missing")
        return 0, failures
    if manifest.is_symlink() or not manifest.is_file():
        failures.append(f"{MANIFEST_NAME}: manifest must be a regular file")
        return 0, failures
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        failures.append(f"{MANIFEST_NAME}: cannot read manifest ({exc.__class__.__name__})")
        return 0, failures

    seen: dict[str, str] = {}
    for number, line in enumerate(lines, 1):
        match = ENTRY.fullmatch(line)
        if not match:
            failures.append(f"{MANIFEST_NAME}:{number}: malformed entry")
            continue
        digest, relative = match.groups()
        if relative in seen:
            failures.append(f"{MANIFEST_NAME}:{number}: duplicate entry {relative}")
            continue
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts or relative == MANIFEST_NAME:
            failures.append(f"{MANIFEST_NAME}:{number}: unsafe path {relative}")
            continue
        seen[relative] = digest

    expected_paths = set(files)
    listed_paths = set(seen)
    for relative in sorted(expected_paths - listed_paths):
        failures.append(f"{MANIFEST_NAME}: payload is not listed: {relative}")
    for relative in sorted(listed_paths - expected_paths):
        failures.append(f"{MANIFEST_NAME}: listed payload is missing: {relative}")
    verified = 0
    for relative in sorted(expected_paths & listed_paths):
        try:
            actual = hashlib.sha256(files[relative].read_bytes()).hexdigest()
        except OSError as exc:
            failures.append(f"{relative}: cannot read file ({exc.__class__.__name__})")
            continue
        if actual != seen[relative]:
            failures.append(f"{relative}: checksum mismatch")
        else:
            verified += 1
    return verified, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--seal", action="store_true")
    action.add_argument("--verify", action="store_true")
    parser.add_argument("evidence_dir", type=Path)
    args = parser.parse_args()

    root = args.evidence_dir.expanduser()
    if args.seal:
        count, failures = seal(root)
        action_name = "sealed"
        if not failures:
            verified, failures = verify(root)
            count = verified
    else:
        count, failures = verify(root)
        action_name = "verified"
    if failures:
        print("Evidence manifest gate failed:", file=sys.stderr)
        print("\n".join(sorted(set(failures))), file=sys.stderr)
        return 1
    print(f"Evidence manifest {action_name}: files={count} root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
