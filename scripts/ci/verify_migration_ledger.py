#!/usr/bin/env python3
"""Verify the immutable Alembic baseline ledger against exact repository bytes.

The ledger freezes migrations 0001 through 0015 at the first NyayOne-native
baseline.  It is deliberately not an inventory of future migrations: revisions
after 0015 must be forward additions and are governed by
``check_migration_immutability.py``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
LEDGER_RELATIVE = Path("backend/app/db/migrations/MIGRATION_SHA256_LEDGER.json")
VERSIONS_RELATIVE = Path("backend/app/db/migrations/versions")
BASELINE_COMMIT = "be979a569118e2538f9572981b7ca731f0902631"
BASELINE_POLICY = "immutable-baseline-forward-revisions-only"
BASELINE_LAST_ORDINAL = 15
SHA256 = re.compile(r"^[0-9a-f]{64}$")
VERSION_FILE = re.compile(r"^(?P<ordinal>[0-9]{4})_[a-z0-9_]+\.py$")

EXPECTED_CHAIN: tuple[tuple[str, str, str | None], ...] = (
    ("0001_initial_pgvector.py", "0001_initial_pgvector", None),
    ("0002_registration_schema.py", "0002_registration_schema", "0001_initial_pgvector"),
    (
        "0003_registration_security_lifecycle.py",
        "0003_registration_security",
        "0002_registration_schema",
    ),
    ("0004_wave1_foundation.py", "0004_wave1_foundation", "0003_registration_security"),
    ("0005_language_check.py", "0005_language_check", "0004_wave1_foundation"),
    (
        "0006_lawschool_fact_backfill.py",
        "0006_lawschool_fact_backfill",
        "0005_language_check",
    ),
    ("0007_wave3_credentials.py", "0007_wave3_credentials", "0006_lawschool_fact_backfill"),
    ("0008_wave2_tutoring.py", "0008_wave2_tutoring", "0007_wave3_credentials"),
    (
        "0009_wave2_session_pricing.py",
        "0009_wave2_session_pricing",
        "0008_wave2_tutoring",
    ),
    (
        "0010_student_login_session.py",
        "0010_student_login_session",
        "0009_wave2_session_pricing",
    ),
    (
        "0011_wave4_private_reporting.py",
        "0011_wave4_private_reporting",
        "0010_student_login_session",
    ),
    ("0012_wave4_moderation.py", "0012_wave4_moderation", "0011_wave4_private_reporting"),
    (
        "0013_wave5_calendar_interop.py",
        "0013_wave5_calendar_interop",
        "0012_wave4_moderation",
    ),
    ("0014_saathi60_internships.py", "0014_saathi60_internships", "0013_wave5_calendar_interop"),
    (
        "0015_wave4_public_risk_labels.py",
        "0015_wave4_public_risk_labels",
        "0014_saathi60_internships",
    ),
)

EXPECTED_DRIFT: tuple[dict[str, str], ...] = (
    {
        "revision": "0002_registration_schema",
        "priorSha256Prefix": "9fa88564",
        "acceptedSha256": "7af72ddf1f2fb0b62c6cdee96118f0611ad7651747a1345838182d5e4b3bbaec",
        "acceptedAtCommit": "fd7779fae042aae7f1026f1285db1c949317ee7c",
        "reason": "metadata-driven create_all was replaced by explicit immutable Alembic operations",
        "disposition": "accepted-pre-baseline-correction",
        "priorDigestAuthority": "documented-investigation-prefix-only",
    },
    {
        "revision": "0008_wave2_tutoring",
        "priorSha256Prefix": "56ff833b",
        "acceptedSha256": "fff836ccc283f267568def3c2e5f6962bdda1b4f3e016a1aad77933dfa2c50a8",
        "acceptedAtCommit": "f05654f8dffa6614c4c538e29d9ce822abdd4a5a",
        "reason": "guarded marker CHECK constraints were repaired to close a SQL three-valued-logic hole",
        "disposition": "accepted-pre-baseline-correction",
        "priorDigestAuthority": "documented-investigation-prefix-only",
    },
    {
        "revision": "0013_wave5_calendar_interop",
        "priorSha256Prefix": "0f18c3e9",
        "acceptedSha256": "8a9f60b367eeeed423dd37eeb9e91b6602c07ccca3259354a2ba54b6542e9b30",
        "acceptedAtCommit": "56eadf684e08b21e0351f32d83ec226cfa1ddb63",
        "reason": "ordered composite indexes were added for owner-scoped composite foreign keys",
        "disposition": "accepted-pre-baseline-correction",
        "priorDigestAuthority": "documented-investigation-prefix-only",
    },
)


class DuplicateKeyError(ValueError):
    """Raised when JSON would otherwise apply last-key-wins semantics."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _literal_assignment(path: Path, name: str) -> tuple[object | None, str | None]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return None, f"cannot parse {path}: {exc}"

    values: list[ast.expr | None] = []
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                values.append(node.value)
        elif isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                values.append(node.value)
    if len(values) != 1 or values[0] is None:
        return None, f"{path}: expected exactly one literal {name} assignment"
    try:
        value = ast.literal_eval(values[0])
    except (ValueError, TypeError, SyntaxError):
        return None, f"{path}: {name} must be a literal string or null"
    if value is not None and not isinstance(value, str):
        return None, f"{path}: {name} must be a literal string or null"
    return value, None


def _canonical_relative_path(raw: object) -> str | None:
    if not isinstance(raw, str) or not raw:
        return None
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        return None
    if path.as_posix() != raw:
        return None
    return raw


def _verify_forward_graph(
    candidates: list[tuple[int, Path, str]],
    *,
    baseline_revisions: list[str],
) -> list[str]:
    """Require post-baseline migrations to extend one literal linear chain."""

    failures: list[str] = []
    candidates.sort(key=lambda item: (item[0], item[2]))
    actual_ordinals = [ordinal for ordinal, _candidate, _relative in candidates]
    expected_ordinals = list(
        range(
            BASELINE_LAST_ORDINAL + 1,
            BASELINE_LAST_ORDINAL + 1 + len(candidates),
        )
    )
    if actual_ordinals != expected_ordinals:
        failures.append(
            "forward migration ordinals must be unique and contiguous after 0015: "
            f"expected {expected_ordinals}, got {actual_ordinals}"
        )

    seen_revisions = set(baseline_revisions)
    previous_revision = EXPECTED_CHAIN[-1][1]
    graph: list[tuple[str, str | None]] = [
        (revision, down_revision)
        for _filename, revision, down_revision in EXPECTED_CHAIN
    ]
    for _ordinal, candidate, relative in candidates:
        expected_revision = candidate.stem
        actual_revision, revision_error = _literal_assignment(candidate, "revision")
        actual_down, down_error = _literal_assignment(candidate, "down_revision")
        branch_labels, branch_error = _literal_assignment(candidate, "branch_labels")
        depends_on, depends_error = _literal_assignment(candidate, "depends_on")

        if revision_error:
            failures.append(revision_error)
        elif actual_revision != expected_revision:
            failures.append(
                f"{relative}: revision must equal filename stem {expected_revision}"
            )
        if isinstance(actual_revision, str):
            if actual_revision in seen_revisions:
                failures.append(f"{relative}: duplicate revision id {actual_revision}")
            seen_revisions.add(actual_revision)

        if down_error:
            failures.append(down_error)
        elif actual_down != previous_revision:
            failures.append(
                f"{relative}: down_revision must be immediate predecessor "
                f"{previous_revision}"
            )
        if branch_error:
            failures.append(branch_error)
        elif branch_labels is not None:
            failures.append(f"{relative}: branch_labels must be literal None")
        if depends_error:
            failures.append(depends_error)
        elif depends_on is not None:
            failures.append(f"{relative}: depends_on must be literal None")

        if isinstance(actual_revision, str) and (
            actual_down is None or isinstance(actual_down, str)
        ) and not down_error:
            graph.append((actual_revision, actual_down))
        previous_revision = expected_revision

    graph_nodes = [revision for revision, _parent in graph]
    if len(graph_nodes) != len(set(graph_nodes)):
        failures.append("migration graph revision ids must be globally unique")
    roots = [revision for revision, parent in graph if parent is None]
    if roots != [EXPECTED_CHAIN[0][1]]:
        failures.append(
            "migration graph must have exactly one root: "
            f"expected {[EXPECTED_CHAIN[0][1]]}, got {roots}"
        )
    referenced_parents = {
        parent for _revision, parent in graph if isinstance(parent, str)
    }
    heads = sorted(set(graph_nodes) - referenced_parents)
    expected_head = candidates[-1][1].stem if candidates else EXPECTED_CHAIN[-1][1]
    if heads != [expected_head]:
        failures.append(
            "migration graph must have exactly one linear head: "
            f"expected {[expected_head]}, got {heads}"
        )

    return failures


def verify(root: Path = ROOT) -> list[str]:
    """Return every ledger failure; an empty list is the only pass verdict."""

    failures: list[str] = []
    ledger_path = root / LEDGER_RELATIVE
    if not ledger_path.is_file() or ledger_path.is_symlink():
        return [f"missing or unsafe migration ledger: {LEDGER_RELATIVE.as_posix()}"]
    try:
        ledger_text = ledger_path.read_text(encoding="utf-8")
        document = json.loads(
            ledger_text,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
        return [f"migration ledger is not strict JSON: {exc}"]

    if not isinstance(document, dict):
        return ["migration ledger root must be an object"]
    canonical_text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if ledger_text != canonical_text:
        failures.append("migration ledger bytes are not canonical UTF-8 JSON")
    expected_top_keys = {"schemaVersion", "baseline", "knownHistoricalDrift", "migrations"}
    if set(document) != expected_top_keys:
        failures.append("migration ledger top-level keys differ from the exact schema")
    if document.get("schemaVersion") != 1 or isinstance(document.get("schemaVersion"), bool):
        failures.append("migration ledger schemaVersion must be integer 1")

    expected_baseline = {
        "commit": BASELINE_COMMIT,
        "firstRevision": EXPECTED_CHAIN[0][1],
        "lastRevision": EXPECTED_CHAIN[-1][1],
        "migrationCount": BASELINE_LAST_ORDINAL,
        "policy": BASELINE_POLICY,
    }
    baseline = document.get("baseline")
    if (
        baseline != expected_baseline
        or not isinstance(baseline, dict)
        or type(baseline.get("migrationCount")) is not int
    ):
        failures.append("migration ledger baseline metadata differs from the exact contract")

    drift = document.get("knownHistoricalDrift")
    if drift != list(EXPECTED_DRIFT):
        failures.append("known historical drift registry differs from the investigated contract")

    raw_migrations = document.get("migrations")
    if not isinstance(raw_migrations, list):
        return failures + ["migration ledger migrations must be an array"]
    if len(raw_migrations) != len(EXPECTED_CHAIN):
        failures.append(
            f"migration ledger must contain exactly {len(EXPECTED_CHAIN)} baseline entries"
        )

    ledger_paths: list[str] = []
    ledger_revisions: list[str] = []
    accepted_by_revision: dict[str, str] = {}
    entry_keys = {"ordinal", "revision", "downRevision", "path", "sha256"}
    for index, raw_entry in enumerate(raw_migrations, start=1):
        label = f"migration ledger entry {index}"
        if not isinstance(raw_entry, dict):
            failures.append(f"{label} must be an object")
            continue
        if set(raw_entry) != entry_keys:
            failures.append(f"{label} keys differ from the exact schema")
        if type(raw_entry.get("ordinal")) is not int or raw_entry.get("ordinal") != index:
            failures.append(f"{label} ordinal must be integer {index}")
        if index > len(EXPECTED_CHAIN):
            continue

        expected_filename, expected_revision, expected_down = EXPECTED_CHAIN[index - 1]
        expected_path = (VERSIONS_RELATIVE / expected_filename).as_posix()
        path_text = _canonical_relative_path(raw_entry.get("path"))
        if path_text is None:
            failures.append(f"{label} path is not a canonical repository-relative path")
            continue
        ledger_paths.append(path_text)
        revision = raw_entry.get("revision")
        if not isinstance(revision, str):
            failures.append(f"{label} revision must be a string")
        else:
            ledger_revisions.append(revision)
        if path_text != expected_path:
            failures.append(f"{label} path must be {expected_path}")
        if revision != expected_revision or raw_entry.get("downRevision") != expected_down:
            failures.append(f"{label} revision chain differs from the frozen baseline")

        expected_digest = raw_entry.get("sha256")
        if not isinstance(expected_digest, str) or not SHA256.fullmatch(expected_digest):
            failures.append(f"{label} sha256 must be 64 lowercase hexadecimal characters")
            continue
        if isinstance(revision, str):
            accepted_by_revision[revision] = expected_digest
        candidate = root / path_text
        if not candidate.is_file() or candidate.is_symlink():
            failures.append(f"{label} target is missing or unsafe: {path_text}")
            continue
        actual_digest = _sha256(candidate)
        if actual_digest != expected_digest:
            failures.append(
                f"{label} SHA-256 mismatch: expected {expected_digest}, got {actual_digest}"
            )
        actual_revision, revision_error = _literal_assignment(candidate, "revision")
        actual_down, down_error = _literal_assignment(candidate, "down_revision")
        if revision_error:
            failures.append(revision_error)
        elif actual_revision != revision:
            failures.append(f"{path_text}: source revision differs from ledger")
        if down_error:
            failures.append(down_error)
        elif actual_down != raw_entry.get("downRevision"):
            failures.append(f"{path_text}: source down_revision differs from ledger")

    if len(set(ledger_paths)) != len(ledger_paths):
        failures.append("migration ledger paths must be unique")
    if len(set(ledger_revisions)) != len(ledger_revisions):
        failures.append("migration ledger revisions must be unique")

    for drift_entry in EXPECTED_DRIFT:
        revision = drift_entry["revision"]
        if accepted_by_revision.get(revision) != drift_entry["acceptedSha256"]:
            failures.append(f"known drift accepted SHA-256 is not the ledger digest for {revision}")

    versions = root / VERSIONS_RELATIVE
    if not versions.is_dir() or versions.is_symlink():
        failures.append(f"missing or unsafe migration versions directory: {VERSIONS_RELATIVE}")
    else:
        ledger_path_set = set(ledger_paths)
        forward_candidates: list[tuple[int, Path, str]] = []
        for candidate in sorted(versions.glob("*.py")):
            relative = candidate.relative_to(root).as_posix()
            if not candidate.is_file() or candidate.is_symlink():
                failures.append(f"migration target is unsafe: {relative}")
                continue
            if relative in ledger_path_set:
                continue
            match = VERSION_FILE.fullmatch(candidate.name)
            if match is None:
                failures.append(f"unledgered migration filename is not canonical: {relative}")
                continue
            ordinal = int(match.group("ordinal"))
            if ordinal <= BASELINE_LAST_ORDINAL:
                failures.append(f"unledgered migration overlaps the frozen baseline: {relative}")
                continue
            forward_candidates.append((ordinal, candidate, relative))
        failures.extend(
            _verify_forward_graph(
                forward_candidates,
                baseline_revisions=ledger_revisions,
            )
        )

    return failures


def main() -> int:
    failures = verify()
    if failures:
        print("Migration SHA-256 ledger verification failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print(
        "Migration SHA-256 ledger verified: "
        f"{len(EXPECTED_CHAIN)} immutable revisions at {BASELINE_COMMIT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
