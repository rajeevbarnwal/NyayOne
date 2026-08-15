#!/usr/bin/env python3
"""Reject common raw authorization credentials from uploadable CI evidence."""

from __future__ import annotations

import re
import sys
from pathlib import Path


PATTERNS = {
    "authorization bearer": re.compile(
        rb"authorization[\"']?\s*[:=]\s*[\"']?\s*bearer\s+[A-Za-z0-9._~-]{12,}",
        re.I,
    ),
    "raw auth field": re.compile(
        rb'"(?:access_token|auth_token|onboarding_capability|session_token)"\s*:\s*"[^"\s]{12,}"',
        re.I,
    ),
    "credential cookie": re.compile(
        rb"(?:set-cookie|cookie)[\"']?\s*[:=]\s*[\"']?[^\r\n]{0,2048}(?:session|auth|token)[^=;\s]*=[A-Za-z0-9._~-]{16,}",
        re.I,
    ),
    "jwt-like credential": re.compile(
        rb"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
    ),
}


def scan(root: Path) -> list[str]:
    if not root.exists():
        return []
    failures: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        for label, pattern in PATTERNS.items():
            if pattern.search(data):
                failures.append(f"{path}: {label}")
    return failures


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: scan_evidence.py EVIDENCE_DIR", file=sys.stderr)
        return 2
    failures = scan(Path(sys.argv[1]))
    if failures:
        print("Raw credential material found in evidence:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Evidence privacy scan passed: {sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
