#!/usr/bin/env python3
"""Fail-closed static policy checks for NyayOne GitHub Actions workflows."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTION_REF = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
IMAGE_REF = re.compile(r"^\s*image:\s*([^\s#]+)", re.MULTILINE)
PINNED_ACTION = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")
PINNED_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")


def check_workflow(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    failures: list[str] = []

    required_fragments = {
        "least-privilege token": "permissions:\n  contents: read",
        "PRs target main": "pull_request:\n    branches: [main]",
        "pushes target main": "push:\n    branches: [main]",
        "manual dispatch": "workflow_dispatch:",
        "concurrency": "concurrency:",
        "required aggregator": "\n  required:\n",
    }
    for label, fragment in required_fragments.items():
        if fragment not in text:
            failures.append(f"{path}: missing {label}")

    forbidden_fragments = {
        "pull_request_target": "pull_request_target:",
        "write-all token permission": "permissions: write-all",
        "write token permission": "contents: write",
        "path-filtered required checks": "    paths:",
        "path-ignored required checks": "    paths-ignore:",
        "fail-open step": "continue-on-error: true",
        "missing evidence warning": "if-no-files-found: warn",
        "mutable runner image": "runs-on: ubuntu-latest",
        "repository secret reference": "${{ secrets.",
        "unpinned pip upgrade": "pip install --upgrade pip",
    }
    for label, fragment in forbidden_fragments.items():
        if fragment in text:
            failures.append(f"{path}: forbidden {label}")

    for ref in ACTION_REF.findall(text):
        if not PINNED_ACTION.fullmatch(ref):
            failures.append(f"{path}: action is not pinned to 40 hex characters: {ref}")
        if not ref.startswith("actions/"):
            failures.append(f"{path}: action owner is not allowlisted: {ref}")

    for ref in IMAGE_REF.findall(text):
        if not PINNED_IMAGE.fullmatch(ref):
            failures.append(f"{path}: service image is not pinned to sha256: {ref}")

    checkout_starts = [match.start() for match in re.finditer(r"uses:\s*actions/checkout@", text)]
    for start in checkout_starts:
        block = text[start : start + 260]
        if "persist-credentials: false" not in block:
            failures.append(f"{path}: checkout must set persist-credentials: false")
        if "fetch-depth: 0" not in block:
            failures.append(f"{path}: checkout must set fetch-depth: 0")

    jobs_text = text.split("\njobs:\n", maxsplit=1)[1] if "\njobs:\n" in text else ""
    job_count = len(re.findall(r"^  [a-zA-Z0-9_-]+:\n", jobs_text, flags=re.MULTILINE))
    timeout_count = len(
        re.findall(r"^    timeout-minutes:\s*\d+", jobs_text, flags=re.MULTILINE)
    )
    if timeout_count < job_count:
        failures.append(
            f"{path}: every job needs timeout-minutes ({timeout_count}/{job_count})"
        )

    job_ids = set(re.findall(r"^  ([a-zA-Z0-9_-]+):\n", jobs_text, flags=re.MULTILINE))
    required_block = jobs_text.split("\n  required:\n", maxsplit=1)[1] if "\n  required:\n" in jobs_text else ""
    if not re.search(r"^    if:\s*\$\{\{ always\(\) \}\}\s*$", required_block, re.MULTILINE):
        failures.append(f"{path}: required aggregator must run with if: always()")
    needs_match = re.search(r"^    needs:\s*\[([^\]]*)\]", required_block, re.MULTILINE)
    actual_needs = {
        value.strip() for value in needs_match.group(1).split(",") if value.strip()
    } if needs_match else set()
    expected_needs = job_ids - {"required"}
    if actual_needs != expected_needs:
        failures.append(
            f"{path}: required aggregator needs {sorted(actual_needs)}, expected {sorted(expected_needs)}"
        )
    result_contract = (
        "RESULTS: ${{ toJSON(needs) }}",
        'if not results or any(value != "success" for value in results.values()):',
        'sys.exit("one or more required jobs did not succeed")',
    )
    if any(fragment not in required_block for fragment in result_contract):
        failures.append(f"{path}: required aggregator lacks the fail-closed needs result contract")

    for match in re.finditer(r"^\s+[a-zA-Z0-9_-]+:\s*write\s*$", text, re.MULTILINE):
        failures.append(f"{path}: workflow requests a write permission: {match.group(0).strip()}")
    if re.search(r"^\s*permissions:\s*write-all\s*$", text, re.MULTILINE):
        failures.append(f"{path}: workflow requests permissions: write-all")

    return failures


def main() -> int:
    workflow_paths = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    if not workflow_paths:
        print("no workflows found", file=sys.stderr)
        return 1

    failures = [failure for path in workflow_paths for failure in check_workflow(path)]
    required_names: list[tuple[Path, str]] = []
    for path in workflow_paths:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^  required:\n    name:\s*([^\s#]+)", text, re.MULTILINE)
        if not match:
            failures.append(f"{path}: required aggregator needs an explicit stable name")
            continue
        name = match.group(1)
        required_names.append((path, name))
        if not re.fullmatch(r"nyayone-[a-z0-9-]+-required", name):
            failures.append(f"{path}: invalid required check name: {name}")
    counts = {name: sum(candidate == name for _, candidate in required_names) for _, name in required_names}
    for path, name in required_names:
        if counts[name] != 1:
            failures.append(f"{path}: duplicate required check name: {name}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    print(f"NyayOne workflow policy passed for {len(workflow_paths)} workflows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
