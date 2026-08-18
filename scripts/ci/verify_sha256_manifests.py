#!/usr/bin/env python3
"""Verify every tracked SHA256SUMS.txt against the committed working-tree bytes."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENTRY = re.compile(r"^([0-9a-f]{64}) [ *](.+)$")
QA_EVIDENCE_ROOT = Path("QA/evidence")
# PR #3 inherited this exact tracked evidence tree.  Phase 1 deliberately does
# not permit committed evidence to grow or be rewritten: new independently
# sealed artifacts live outside the code PR and are attached to Jira manually.
# The digest binds every relative path and every file's SHA-256, including the
# older SAATHI packages that predate the stricter manifest policy.
FROZEN_QA_EVIDENCE_FILE_COUNT = 68
FROZEN_QA_EVIDENCE_SHA256 = (
    "7a09199f34433951b154e22eee846443adfbda192a296b22acbedd41e24af095"
)


def _opaque_path_label(path: Path | str) -> str:
    value = path.as_posix() if isinstance(path, Path) else str(path)
    return f"path#{hashlib.sha256(value.encode('utf-8', 'surrogatepass')).hexdigest()[:12]}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tracked_manifests() -> list[Path]:
    return [
        ROOT / path
        for path in sorted(tracked_files())
        if path.name == "SHA256SUMS.txt"
    ]


def tracked_files() -> set[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return {
        Path(os.fsdecode(raw))
        for raw in output.split(b"\0")
        if raw
    }


def frozen_qa_evidence_failures(tracked: set[Path]) -> list[str]:
    failures: list[str] = []
    evidence = sorted(
        path
        for path in tracked
        if len(path.parts) >= 2
        and path.parts[0].casefold() == "qa"
        and path.parts[1].casefold() == "evidence"
    )
    digest = hashlib.sha256()
    for relative in evidence:
        candidate = ROOT / relative
        label = _opaque_path_label(relative)
        if not relative.is_relative_to(QA_EVIDENCE_ROOT):
            failures.append(f"{label}: QA evidence path must use canonical casing")
            continue
        if any(
            ord(character) < 32 or ord(character) == 127
            for character in relative.as_posix()
        ):
            failures.append(f"{label}: control characters are forbidden in evidence paths")
            continue
        try:
            mode = candidate.lstat().st_mode
        except OSError as exc:
            failures.append(
                f"{label}: frozen evidence cannot be inspected ({exc.__class__.__name__})"
            )
            continue
        if not stat.S_ISREG(mode):
            failures.append(f"{label}: frozen evidence must be a regular file")
            continue
        path_bytes = relative.as_posix().encode("utf-8", "surrogatepass")
        digest.update(len(path_bytes).to_bytes(8, "big"))
        digest.update(path_bytes)
        digest.update(bytes.fromhex(_sha256_file(candidate)))

    if len(evidence) != FROZEN_QA_EVIDENCE_FILE_COUNT:
        failures.append(
            "tracked QA evidence inventory differs from the frozen PR #3 baseline"
        )
    if not failures and digest.hexdigest() != FROZEN_QA_EVIDENCE_SHA256:
        failures.append("tracked QA evidence bytes differ from the frozen PR #3 baseline")
    return failures


def verify(manifest: Path) -> tuple[int, list[str]]:
    failures: list[str] = []
    seen: set[str] = set()
    count = 0
    manifest_relative = manifest.relative_to(ROOT)
    manifest_label = _opaque_path_label(manifest_relative)
    try:
        manifest_mode = manifest.lstat().st_mode
    except OSError as exc:
        return 0, [f"{manifest_label}: manifest cannot be inspected ({exc.__class__.__name__})"]
    if stat.S_ISLNK(manifest_mode):
        return 0, [f"{manifest_label}: manifest symlink is not allowed"]
    if not stat.S_ISREG(manifest_mode):
        return 0, [f"{manifest_label}: manifest must be a regular file"]
    base = manifest.parent.resolve()
    base_relative = manifest.parent.relative_to(ROOT)
    tracked_output = subprocess.check_output(
        ["git", "ls-files", "-z", "--", base_relative.as_posix()], cwd=ROOT
    )
    tracked = {
        Path(os.fsdecode(raw)).relative_to(base_relative).as_posix()
        for raw in tracked_output.split(b"\0")
        if raw
    }
    try:
        manifest_text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return 0, [f"{manifest_label}: manifest cannot be read ({exc.__class__.__name__})"]
    for number, raw in enumerate(manifest_text.splitlines(), 1):
        if not raw:
            continue
        match = ENTRY.fullmatch(raw)
        if not match:
            failures.append(f"{manifest_label}:{number}: malformed entry")
            continue
        expected, relative = match.groups()
        if relative in seen:
            failures.append(f"{manifest_label}:{number}: duplicate entry")
            continue
        seen.add(relative)
        if relative not in tracked:
            failures.append(f"{manifest_label}:{number}: untracked entry")
            continue
        unresolved = manifest.parent / relative
        if unresolved.is_symlink():
            failures.append(f"{manifest_label}:{number}: symlink is not allowed")
            continue
        candidate = unresolved.resolve()
        if candidate == manifest.resolve() or not candidate.is_relative_to(base):
            failures.append(f"{manifest_label}:{number}: unsafe path")
            continue
        if not candidate.is_file():
            failures.append(f"{manifest_label}:{number}: missing payload")
            continue
        if candidate.stat().st_size == 0:
            failures.append(f"{manifest_label}:{number}: zero-byte payload")
            continue
        actual = _sha256_file(candidate)
        if actual != expected:
            failures.append(
                f"{manifest_label}:{number}: checksum mismatch"
            )
            continue
        count += 1
    if not seen:
        failures.append(f"{manifest_label}: manifest is empty")
    missing_entries = sorted(tracked - {manifest.name} - seen)
    for relative in missing_entries:
        failures.append(f"{manifest_label}: tracked file is not listed ({_opaque_path_label(relative)})")
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
    failures.extend(frozen_qa_evidence_failures(tracked_files()))
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"SHA-256 manifests passed: {len(manifests)} manifests, {verified} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
