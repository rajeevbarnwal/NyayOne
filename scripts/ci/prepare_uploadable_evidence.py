#!/usr/bin/env python3
"""Create a privacy-safe evidence attestation for CI upload.

Raster, PDF, archive, raw service log and other opaque diagnostic artifacts are
deliberately quarantined: the dependency-free privacy scanner cannot prove that
their rendered or free-form content excludes private narrative. The snapshot
never copies source payloads. It records only controlled aggregate metadata for
valid JSON candidates and quarantined inputs, never source filenames, raw
content hashes, exact lengths or bytes. Complete failed Wave-1 inventories also
export repository-owned assertion IDs and non-linkable keyed comparison hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from pathlib import Path


TEXT_EXTENSIONS = {".csv", ".html", ".md", ".txt"}
ARCHIVE_EXTENSIONS = {
    ".7z", ".bz2", ".docx", ".epub", ".gz", ".pptx", ".rar", ".tar",
    ".tgz", ".trace", ".xlsx", ".xz", ".zip",
}
VISUAL_EXTENSIONS = {
    ".avif", ".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".pdf", ".png",
    ".svg", ".tif", ".tiff", ".webp",
}
MANIFEST_NAME = "SHA256SUMS.txt"
EXPORT_NAME = "EVIDENCE_EXPORT.json"
SENSITIVE_CAPTURE_DIRECTORIES = {
    "credential-objects",
    "dom",
    "net",
    "report-evidence",
    "screenshots",
    "shots",
    "storage",
    "traces",
    "work",
}


MAX_SOURCE_FILE_BYTES = 64 * 1024 * 1024
MAX_EXPECTED_JSON_BYTES = 16 * 1024 * 1024
MAX_SOURCE_FILES = 5_000
MAX_SOURCE_TOTAL_BYTES = 1024 * 1024 * 1024
SIZE_CLASSES = {"up-to-1KiB", "1-16KiB", "16KiB-1MiB", "1-64MiB"}
QUARANTINE_MEDIA_CLASSES = {
    "archive", "free-form-text", "json", "other", "sensitive-capture",
    "service-log", "unapproved-json", "visual",
}
LIMITATION = (
    "Phase 1 uploads an aggregate attestation only; raw test evidence "
    "remains runner-local and is not independently reviewable from this artifact."
)
FAILURE_LIMITATION = (
    "Controlled failure IDs and non-linkable keyed comparison digests only; "
    "raw comparison values and screen content remain runner-local. "
    "The ephemeral HMAC key is discarded and raw values cannot be reconstructed."
)


# Each upload job has an exact producer inventory. The source-relative path is
# never copied into the attestation; the stable artifact id is repository-owned
# metadata and cannot contain runtime PII.
PROFILE_SPECS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "wave1": (
        ("wave1-browser", "results.json", "boolean-rows"),
    ),
    "wave2": (
        ("wave2-postgres", "wave2-db-gate/summary.json", "postgres-assertions"),
    ),
    "wave3": (
        ("credential-browser", "credentials/credential-e2e-report.json", "credential-report"),
        ("registration-browser", "registration/registration_e2e_report.json", "boolean-results"),
        ("auth-browser", "v34-s01-s10/results.json", "boolean-rows"),
        ("nyay22-browser", "nyay22-browser/results.json", "nyay22-browser"),
        ("nyay22-postgres", "nyay22-postgres/summary.json", "nyay22-postgres"),
    ),
    "wave4": (
        ("wave4-postgres", "wave4-postgres/summary.json", "postgres-results"),
        ("reporting-browser", "wave4-browser/results.json", "browser-report"),
        ("moderation-browser", "wave4-moderation-browser/results.json", "browser-report"),
        ("risk-label-browser", "wave4-risk-label-browser/results.json", "wave4-risk-browser"),
        ("risk-label-fixture", "wave4-risk-label-fixture.json", "wave4-risk-fixture"),
    ),
    "wave5-postgres": (
        ("wave5-postgres", "wave5-postgres/summary.json", "postgres-rows"),
    ),
    "wave5-real": (
        ("wave5-real-browser", "wave5-real-browser/wave5-calendar-real-e2e.json", "wave5-browser"),
    ),
    "nyay5": (
        ("nyay5-postgres", "nyay5-postgres/summary.json", "nyay5-postgres"),
        ("nyay5-browser", "nyay5-browser/results.json", "nyay5-browser"),
        (
            "nyay5-orchestrator",
            "nyay5-browser/orchestrator-summary.json",
            "nyay5-orchestrator",
        ),
        (
            "nyay5-acceptance-attestations",
            "nyay5-acceptance/attestations.json",
            "nyay5-acceptance-attestations",
        ),
        (
            "nyay5-acceptance-matrix",
            "nyay5-acceptance/summary.json",
            "nyay5-acceptance-matrix",
        ),
    ),
}

# Contracts pin each producer's repository-reviewed exact assertion inventory.
# Only the sorted identity digest is retained here: assertion text and runtime
# values remain outside uploadable evidence. A PASS cannot shrink, duplicate or
# substitute its assertion inventory without changing one of these digests.
INVENTORY_CONTRACTS: dict[str, tuple[str, str, int, str]] = {
    "wave1-browser": (
        "rows", "area", 1467,
        "250d3429ae3056dc2b117e013196ee896c8d73b3e99dfc61d3ebd27ef66f8f65",
    ),
    "wave2-postgres": (
        "assertions", "id", 30,
        "2618ee569f523fbcf1ee334dd933f908ddae691d7cde1ceabe6d3626f37db027",
    ),
    "registration-browser": (
        "results", "name", 54,
        "f9d114f9dac2d2f158c03d5053645e5c4344884420cce48d1e6cee54692d7997",
    ),
    "auth-browser": (
        "rows", "area", 137,
        "7f226c639f922f8cbaba363effb81e87bb189428eddc27bec809056c290fe60f",
    ),
    "nyay22-browser": (
        "rows", "name", 14,
        "d9febbb9662d7f6e436e214936fc5111e4202e0c8d463b31275be13353315257",
    ),
    "nyay22-postgres": (
        "oracles", "id", 17,
        "99ad80b085b29ff6f5eae3f04bfbbd3d2516af6c3c56333083d81ec5b3a0eab8",
    ),
    "wave4-postgres": (
        "results", "id", 34,
        "b2bf4c116c12d56c32b520a2fede953dd1102ff2980ff0cc91b43656a6fff0c5",
    ),
    "reporting-browser": (
        "rows", "name", 31,
        "62e0eb6e4b8bf5ecedb5826537a78825a117c4b165e0767639ffff04e6a0abb5",
    ),
    "moderation-browser": (
        "rows", "name", 33,
        "5a57116304a8fc67daf4116d15f9e037316033b0933d2a8bb62755084c796a8a",
    ),
    "risk-label-browser": (
        "rows", "name", 234,
        "e6c71c8ad2d48d4e536fae6bab98e33941e9b0c58b7a01822e542409612c70cd",
    ),
    "wave5-postgres": (
        "rows", "id", 17,
        "8c7fda7cc4ee0c38fc57a7758cca1f36ade827769683b5cb583c20ea67bc353a",
    ),
    "wave5-real-browser": (
        "rows", "name", 305,
        "c21aba4487d2936e7c761c2a37ebdb1176bd9037c35b5552140ebc4dffa62478",
    ),
    "nyay5-postgres": (
        "assertions", "id", 21,
        "ced6011b74db2f2b1c890f8ac1d7b3a212ff2aac8f7259e4ef6085e5d4dfd372",
    ),
    "nyay5-browser": (
        "rows", "name", 22,
        "b9e7aa70519d7d16f044b2ac928fb039cce8d2e073bd1b0303f9f58787d28071",
    ),
    "nyay5-acceptance-attestations": (
        "executions", "id", 12,
        "3f22abbff483c686efaabc3d86ab33bd2b8758aa95d4df77b8f306edddb9b328",
    ),
    "nyay5-acceptance-matrix": (
        "assertions", "id", 61,
        "3808f4a08805ec0cc8f904996c9fda428904ae48d8f34e261e3e07791e6d597e",
    ),
}
CREDENTIAL_INVENTORY_CONTRACTS = {
    "functional": (
        12,
        "54e484390e51a3cc5e87f5a75f2fb3b447593e78a8fa597a466f4ece54d29c15",
    ),
    "negative": (
        17,
        "d404111310c14d9b78041c9dd47ca1962fe20898b3596c76d1d238a75c6abc60",
    ),
    "geometry": (
        50,
        "16dcb04559e0b75c8764e2237b26e0ada52245802bddc41a893938f1cf105b08",
    ),
}
EXACT_AGGREGATE_ASSERTION_COUNTS = {
    # Five service-readiness observations, three cleanup observations, and the
    # exact browser exit and private-log-capture verdicts. The source schema is
    # checked key-for-key.
    "nyay5-orchestrator": 10,
}
NYAY5_ACCEPTANCE_EXECUTION_INVENTORY = (
    77,
    "2f38f7d93992911c68f426aad28766d912235ac40bd6937c8ef3fee6105a9662",
)
NYAY5_POSTGRES_MUTANT_COUNT = 29


def _size_class(size: int) -> str:
    if size <= 1_024:
        return "up-to-1KiB"
    if size <= 16_384:
        return "1-16KiB"
    if size <= 1_048_576:
        return "16KiB-1MiB"
    return "1-64MiB"


def _media_class(suffix: str) -> str:
    if suffix == ".json":
        return "json"
    if suffix in TEXT_EXTENSIONS:
        return "free-form-text"
    if suffix in ARCHIVE_EXTENSIONS:
        return "archive"
    if suffix in VISUAL_EXTENSIONS:
        return "visual"
    if suffix == ".log":
        return "service-log"
    return "other"


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Build a JSON object while rejecting every duplicate key.

    Evidence producers are security oracles. Accepting JSON's usual
    last-key-wins behaviour would let a fabricated second ``rows`` or
    ``status`` member replace the report that the producer actually emitted.
    The hook runs for every nested object, so the rejection is recursive.
    """

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON mapping key")
        result[key] = value
    return result


def _strict_json_load(data: bytes) -> object:
    def reject_constant(_value: str) -> object:
        raise ValueError("non-finite JSON number")

    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=reject_constant,
    )


def _read_stable_regular_file(
    path: Path,
    before: os.stat_result,
    *,
    limit: int,
) -> tuple[bytes | None, str | None]:
    """Read one producer file through a single descriptor and detect races."""

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        identity = (
            "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns"
        )
        if any(getattr(before, key) != getattr(opened, key) for key in identity):
            return None, "evidence file changed before the snapshot was opened"
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            data = handle.read(limit + 1)
            after = os.fstat(handle.fileno())
        if len(data) > limit:
            return None, "evidence file exceeds the snapshot size limit"
        if any(getattr(opened, key) != getattr(after, key) for key in identity):
            return None, "evidence file changed while the snapshot was read"
        final = path.lstat()
        if any(getattr(after, key) != getattr(final, key) for key in identity):
            return None, "evidence file changed after the snapshot was read"
        return data, None
    except OSError as exc:
        return None, f"evidence file cannot be snapshotted ({exc.__class__.__name__})"
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _boolean_rows(value: object, key: str) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    rows = value.get(key)
    if not isinstance(rows, list) or not rows:
        return None
    verdicts: list[bool] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("pass"), bool):
            return None
        verdicts.append(row["pass"])
    return len(verdicts), sum(not verdict for verdict in verdicts)


def _identity_digest(identities: list[str]) -> str:
    payload = "\n".join(sorted(identities)) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _inventory(
    value: object,
    *,
    rows_key: str,
    identity_key: str,
    prefix: str = "",
) -> tuple[int, str] | None:
    if not isinstance(value, dict) or not isinstance(value.get(rows_key), list):
        return None
    identities: list[str] = []
    for row in value[rows_key]:
        if not isinstance(row, dict):
            return None
        identity = row.get(identity_key)
        if not isinstance(identity, str) or not identity.strip():
            return None
        identities.append(f"{prefix}{identity}")
    if len(set(identities)) != len(identities):
        return None
    return len(identities), _identity_digest(identities)


def _inventory_matches(artifact_id: str, value: object) -> bool:
    contract = INVENTORY_CONTRACTS.get(artifact_id)
    if contract is None:
        return False
    rows_key, identity_key, expected_count, expected_digest = contract
    actual = _inventory(value, rows_key=rows_key, identity_key=identity_key)
    return actual == (expected_count, expected_digest)


def _status_rows(value: object, key: str) -> tuple[int, int] | None:
    if not isinstance(value, dict):
        return None
    rows = value.get(key)
    if not isinstance(rows, list) or not rows:
        return None
    statuses: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("status") not in {"PASS", "FAIL"}:
            return None
        statuses.append(row["status"])
    return len(statuses), sum(status != "PASS" for status in statuses)


def _failure_list_count(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    failures = value.get("failures")
    return len(failures) if isinstance(failures, list) else None


def _reconcile_declared_counts(
    value: object,
    *,
    total: int,
    failed: int,
    total_key: str = "total",
    passed_key: str = "passed",
    failed_key: str = "failed",
) -> bool:
    if not isinstance(value, dict):
        return False
    declared = (value.get(total_key), value.get(passed_key), value.get(failed_key))
    if declared == (None, None, None):
        return True
    parsed = tuple(_nonnegative_integer(item) for item in declared)
    return parsed == (total, total - failed, failed)


def _safe_result(
    kind: str,
    value: object,
    artifact_id: str,
) -> tuple[dict[str, object] | None, str | None]:
    """Project one producer report to a controlled, value-free attestation."""

    executed = True
    counts: tuple[int, int] | None = None
    state: str | None = None
    inventory_complete = False

    if kind == "boolean-rows":
        counts = _boolean_rows(value, "rows")
        if counts and (
            not isinstance(value, dict)
            or (value.get("total"), value.get("passed"), value.get("failed"))
            != (counts[0], counts[0] - counts[1], counts[1])
        ):
            return None, "declared browser counts do not match assertion rows"
    elif kind == "nyay22-browser":
        counts = _boolean_rows(value, "rows")
        if (
            counts is None
            or not isinstance(value, dict)
            or set(value) != {"schemaVersion", "rows", "summary", "authorityModel"}
            or value.get("schemaVersion") != "nyay22-browser-evidence.v1"
            or value.get("authorityModel") != "withServerProvenMentorSession"
        ):
            return None, "NYAY-22 browser report shape is invalid"
        summary = value.get("summary")
        if (
            not isinstance(summary, dict)
            or set(summary) != {"total", "passed", "failed"}
            or (
                summary.get("total"),
                summary.get("passed"),
                summary.get("failed"),
            ) != (counts[0], counts[0] - counts[1], counts[1])
        ):
            return None, "NYAY-22 browser summary does not match assertion rows"
    elif kind == "nyay22-postgres":
        counts = _status_rows(value, "oracles")
        if (
            counts is None
            or not isinstance(value, dict)
            or set(value)
            != {
                "schema_version",
                "status",
                "classification",
                "postgres_major",
                "pgvector_present",
                "oracles",
                "summary",
            }
            or value.get("schema_version") != "nyay22-mentor-postgres/v1"
            or value.get("status") != "PASS"
            or value.get("classification") != "EXECUTED"
            or value.get("postgres_major") != 16
            or value.get("pgvector_present") is not True
            or any(
                not isinstance(row, dict)
                or set(row) != {"id", "status", "assertions"}
                or row.get("status") != "PASS"
                or _nonnegative_integer(row.get("assertions")) in {None, 0}
                for row in value.get("oracles", [])
            )
        ):
            return None, "NYAY-22 PostgreSQL report shape is invalid"
        summary = value.get("summary")
        if (
            not isinstance(summary, dict)
            or set(summary) != {"passed", "total"}
            or (summary.get("passed"), summary.get("total"))
            != (counts[0] - counts[1], counts[0])
        ):
            return None, "NYAY-22 PostgreSQL summary does not match oracle rows"
    elif kind == "boolean-results":
        counts = _boolean_rows(value, "results")
        if counts and (
            not isinstance(value, dict)
            or value.get("passed") != counts[0] - counts[1]
            or value.get("failed") != counts[1]
        ):
            return None, "declared registration counts do not match assertion rows"
    elif kind == "browser-report":
        counts = _boolean_rows(value, "rows")
        listed_failures = _failure_list_count(value)
        if counts is None or listed_failures is None:
            return None, "browser report rows and failures must be arrays"
        counts = counts[0], max(counts[1], listed_failures)
        if counts[1] > counts[0]:
            return None, "browser report has more failures than assertions"
    elif kind == "credential-report":
        if not isinstance(value, dict):
            counts = None
        else:
            groups = []
            complete_groups = True
            for key in ("functional", "negative", "geometry"):
                group = _boolean_rows({"rows": value.get(key)}, "rows")
                inventory = _inventory(
                    {"rows": value.get(key)},
                    rows_key="rows",
                    identity_key="name",
                    prefix=f"{key}:",
                )
                if group is None or inventory is None:
                    return None, "credential report has an invalid assertion group"
                groups.append(group)
                complete_groups = complete_groups and inventory == (
                    CREDENTIAL_INVENTORY_CONTRACTS[key][0],
                    CREDENTIAL_INVENTORY_CONTRACTS[key][1],
                )
            counts = sum(item[0] for item in groups), sum(item[1] for item in groups)
            listed_failures = _failure_list_count(value)
            if listed_failures is None:
                return None, "credential report failures must be an array"
            counts = counts[0], max(counts[1], listed_failures)
            if counts[1] > counts[0]:
                return None, "credential report has more failures than assertions"
            summary = value.get("summary")
            if not isinstance(summary, dict):
                return None, "credential report summary is missing"
            expected_summary = {
                "functionalPassed": groups[0][0] - groups[0][1],
                "functionalFailed": groups[0][1],
                "negativePassed": groups[1][0] - groups[1][1],
                "negativeFailed": groups[1][1],
                "geometryPassed": groups[2][0] - groups[2][1],
                "geometryFailed": groups[2][1],
            }
            if any(summary.get(key) != expected for key, expected in expected_summary.items()):
                return None, "credential report summary does not match assertion groups"
            inventory_complete = complete_groups
    elif kind in {
        "postgres-assertions", "postgres-results", "postgres-rows",
        "nyay5-postgres",
    }:
        if not isinstance(value, dict):
            return None, "PostgreSQL report must be an object"
        expected_gate = {
            "postgres-assertions": "wave2_postgres",
            "postgres-results": "wave4_postgres",
            "postgres-rows": "wave5_postgres",
            "nyay5-postgres": "nyay5_postgres",
        }[kind]
        if value.get("gate") != expected_gate:
            return None, "PostgreSQL report gate identity is invalid"
        if not isinstance(value.get("executed"), bool):
            return None, "PostgreSQL report executed flag is invalid"
        executed = value["executed"]
        status = value.get("status")
        if status not in {"PASS", "FAIL", "BLOCKED"}:
            return None, "PostgreSQL report status is invalid"
        state = status.lower()
        row_key = {
            "postgres-assertions": "assertions",
            "postgres-results": "results",
            "postgres-rows": "rows",
            "nyay5-postgres": "assertions",
        }[kind]
        rows = value.get(row_key)
        if status == "BLOCKED":
            if executed or rows not in (None, []):
                return None, "PostgreSQL BLOCKED is inconsistent with execution results"
            counts = (0, 0)
        else:
            counts = _status_rows(value, row_key)
            if counts is None:
                return None, "PostgreSQL report has no valid assertion rows"
            if not executed:
                return None, "PostgreSQL PASS/FAIL requires an executed gate"
            if status == "PASS" and counts[1] != 0:
                return None, "PostgreSQL PASS contains a failed assertion"
            if status == "FAIL" and counts[1] == 0:
                return None, "PostgreSQL FAIL has no failed assertion"
        if kind in {"postgres-assertions", "postgres-results", "nyay5-postgres"}:
            failed_assertions = value.get("failed_assertions")
            if not isinstance(failed_assertions, list):
                return None, "PostgreSQL failed-assertion inventory is invalid"
            if len(failed_assertions) != counts[1]:
                return None, "PostgreSQL failed-assertion inventory is inconsistent"
        if kind in {"postgres-assertions", "nyay5-postgres"}:
            expected_exit = {"PASS": 0, "FAIL": 1, "BLOCKED": 78}[status]
            if value.get("exit_code") != expected_exit:
                return None, "PostgreSQL report exit code is inconsistent"
        if kind == "nyay5-postgres" and status == "PASS":
            if value.get("head") != "0021_nyay5_profile_boundary":
                return None, "NYAY-5 PostgreSQL migration head is invalid"
            summary = value.get("assertion_summary")
            if not isinstance(summary, dict) or summary != {
                "exact_inventory": True,
                "failed": [],
                "overall_pass": True,
                "passed": counts[0],
                "required": counts[0],
            }:
                return None, "NYAY-5 PostgreSQL assertion summary is inconsistent"
            cleanup = value.get("scratch_cleanup")
            if not isinstance(cleanup, dict) or not (
                cleanup.get("all_created_removed") is True
                and cleanup.get("inventory_match") is True
                and _nonnegative_integer(cleanup.get("created")) is not None
                and cleanup.get("created") > 0
                and cleanup.get("removed") == cleanup.get("created")
                and cleanup.get("cleanup_failed") == 0
            ):
                return None, "NYAY-5 PostgreSQL scratch cleanup is incomplete"
            mutants = value.get("mutant_inventory")
            if not isinstance(mutants, dict) or set(mutants) != {"named", "killed"}:
                return None, "NYAY-5 PostgreSQL mutant inventory is incomplete"
            named = _nonnegative_integer(mutants.get("named"))
            killed = _nonnegative_integer(mutants.get("killed"))
            if not (
                named == NYAY5_POSTGRES_MUTANT_COUNT
                and killed == NYAY5_POSTGRES_MUTANT_COUNT
            ):
                return None, "NYAY-5 PostgreSQL mutant inventory is incomplete"
            if value.get("privacy_scan") != {
                "scanned": True,
                "findings": 0,
                "passed": True,
            }:
                return None, "NYAY-5 PostgreSQL privacy scan is incomplete"
    elif kind == "nyay5-browser":
        if not isinstance(value, dict):
            return None, "NYAY-5 browser report must be an object"
        if value.get("gate") != "nyay5_profile_browser":
            return None, "NYAY-5 browser gate identity is invalid"
        if value.get("target") != "isolated-loopback-real-api-postgresql-chromium":
            return None, "NYAY-5 browser target-runtime class is invalid"
        if not isinstance(value.get("executed"), bool):
            return None, "NYAY-5 browser executed flag is invalid"
        executed = value["executed"]
        status = value.get("status")
        if status not in {"PASS", "FAIL"}:
            return None, "NYAY-5 browser status is invalid"
        state = status.lower()
        counts = _boolean_rows(value, "rows")
        if counts is None:
            return None, "NYAY-5 browser report has no assertion rows"
        if (value.get("total"), value.get("passed"), value.get("failed")) != (
            counts[0], counts[0] - counts[1], counts[1]
        ):
            return None, "NYAY-5 browser declared counts do not match assertion rows"
        if not executed:
            return None, "NYAY-5 browser report did not execute"
        if status == "PASS" and counts[1] != 0:
            return None, "NYAY-5 browser PASS contains a failed assertion"
        if status == "FAIL" and counts[1] == 0:
            return None, "NYAY-5 browser FAIL has no failed assertion"
        if status == "PASS":
            if value.get("inventoryExact") is not True:
                return None, "NYAY-5 browser assertion inventory is not exact"
            if any(value.get(key) is not None for key in (
                "failureClass", "failureStage", "failureCode"
            )):
                return None, "NYAY-5 browser PASS contains a runtime failure"
            rows = value.get("rows")
            if not all(
                isinstance(row, dict)
                and isinstance(row.get("metrics"), dict)
                and row["metrics"].get("executed") is True
                for row in rows
            ):
                return None, "NYAY-5 browser PASS contains a non-executed assertion"
    elif kind == "nyay5-acceptance-attestations":
        if not isinstance(value, dict) or set(value) != {
            "gate", "status", "executed", "executions",
        }:
            return None, "NYAY-5 acceptance attestation schema is not exact"
        if value.get("gate") != "nyay5_acceptance_attestations_v1":
            return None, "NYAY-5 acceptance attestation identity is invalid"
        status = value.get("status")
        if status not in {"PASS", "FAIL"} or value.get("executed") is not True:
            return None, "NYAY-5 acceptance attestation state is invalid"
        rows = value.get("executions")
        counts = _boolean_rows(value, "executions")
        if counts is None or not isinstance(rows, list):
            return None, "NYAY-5 acceptance attestation executions are invalid"
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "id", "executed", "skipped", "pass", "evidenceCount",
                "selectorCount",
            }:
                return None, "NYAY-5 acceptance execution schema is not exact"
            evidence_count = _nonnegative_integer(row.get("evidenceCount"))
            if not (
                isinstance(row.get("executed"), bool)
                and row.get("skipped") is False
                and isinstance(row.get("pass"), bool)
                and evidence_count is not None
                and row.get("selectorCount") is None
                and (
                    row.get("pass") is False
                    or (row.get("executed") is True and evidence_count > 0)
                )
            ):
                return None, "NYAY-5 acceptance execution verdict is inconsistent"
        if (status == "PASS") != (counts[1] == 0):
            return None, "NYAY-5 acceptance attestation status is inconsistent"
        executed = True
        state = status.lower()
    elif kind == "nyay5-acceptance-matrix":
        if not isinstance(value, dict) or set(value) != {
            "gate", "status", "executed", "total", "passed", "failed",
            "inventoryExact", "assertions", "executionCoverage",
            "executionInventory", "producerStatus", "privacyScan",
        }:
            return None, "NYAY-5 acceptance aggregate schema is not exact"
        if value.get("gate") != "nyay5_acceptance_matrix":
            return None, "NYAY-5 acceptance aggregate identity is invalid"
        status = value.get("status")
        if status not in {"PASS", "FAIL"} or value.get("executed") is not True:
            return None, "NYAY-5 acceptance aggregate state is invalid"
        rows = value.get("assertions")
        if not isinstance(rows, list) or not rows:
            return None, "NYAY-5 acceptance aggregate assertions are unavailable"
        verdicts: list[bool] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "id", "passed", "evidenceCount",
            }:
                return None, "NYAY-5 acceptance assertion schema is not exact"
            evidence_count = _nonnegative_integer(row.get("evidenceCount"))
            if not isinstance(row.get("passed"), bool) or evidence_count is None:
                return None, "NYAY-5 acceptance assertion verdict is invalid"
            if row.get("passed") is True and evidence_count <= 0:
                return None, "NYAY-5 passing assertion has no executed evidence"
            verdicts.append(row["passed"])
        counts = len(verdicts), sum(not passed for passed in verdicts)
        if (value.get("total"), value.get("passed"), value.get("failed")) != (
            counts[0], counts[0] - counts[1], counts[1]
        ):
            return None, "NYAY-5 acceptance aggregate counts are inconsistent"
        coverage = value.get("executionCoverage")
        execution_inventory = value.get("executionInventory")
        producers = value.get("producerStatus")
        privacy = value.get("privacyScan")
        expected_execution_count, expected_execution_sha256 = (
            NYAY5_ACCEPTANCE_EXECUTION_INVENTORY
        )
        green = bool(
            counts[1] == 0
            and value.get("inventoryExact") is True
            and isinstance(coverage, dict)
            and set(coverage) == {
                "pass", "mapped", "missing", "skipped", "unknown", "unique",
            }
            and coverage == {
                "pass": True,
                "mapped": counts[0],
                "missing": 0,
                "skipped": 0,
                "unknown": 0,
                "unique": True,
            }
            and execution_inventory == {
                "count": expected_execution_count,
                "sha256": expected_execution_sha256,
            }
            and producers == {
                "browser": True,
                "postgres": True,
                "otpPostgres": True,
                "attestations": True,
            }
            and privacy == {"passed": True, "findings": 0}
        )
        if (status == "PASS") != green:
            return None, "NYAY-5 acceptance aggregate status is inconsistent"
        executed = True
        state = status.lower()
    elif kind == "nyay5-orchestrator":
        if not isinstance(value, dict) or set(value) != {
            "gate", "executed", "status", "services", "scratchCleanup",
            "browserExitCode", "serviceLogsCaptured",
        }:
            return None, "NYAY-5 orchestrator summary schema is not exact"
        services = value.get("services")
        cleanup = value.get("scratchCleanup")
        if not isinstance(services, dict) or set(services) != {
            "postgresReady", "apiReady", "otpCaptureReady",
            "productionPreviewReady", "serviceWorkerActive",
        }:
            return None, "NYAY-5 orchestrator service schema is not exact"
        if not isinstance(cleanup, dict) or set(cleanup) != {
            "created", "removed", "inventoryMatch",
        }:
            return None, "NYAY-5 orchestrator cleanup schema is not exact"
        if not (
            value.get("gate") == "nyay5-profile-browser-orchestrator-v1"
            and value.get("executed") is True
            and value.get("status") == "PASS"
            and all(item is True for item in services.values())
            and cleanup == {"created": 1, "removed": 1, "inventoryMatch": True}
            and value.get("browserExitCode") == 0
            and value.get("serviceLogsCaptured") is True
        ):
            return None, "NYAY-5 orchestrator did not complete every producer and cleanup"
        return {
            "producerState": "pass",
            "executed": True,
            "assertionCount": EXACT_AGGREGATE_ASSERTION_COUNTS["nyay5-orchestrator"],
            "failedAssertionCount": 0,
            "inventoryComplete": True,
        }, None
    elif kind == "wave5-browser":
        counts = _boolean_rows(value, "rows")
        listed_failures = _failure_list_count(value)
        if counts is None or listed_failures is None or not isinstance(value, dict):
            return None, "Wave 5 rows and failures must be arrays"
        counts = counts[0], max(counts[1], listed_failures)
        if counts[1] > counts[0]:
            return None, "Wave 5 has more failures than assertions"
        if (value.get("total"), value.get("passed"), value.get("failed")) != (
            counts[0], counts[0] - counts[1], counts[1]
        ):
            return None, "Wave 5 declared counts do not match assertion rows"
        if value.get("evidenceClass") != "real-target-runtime-api-postgresql-browser":
            return None, "Wave 5 target-runtime evidence class is invalid"
        if value.get("releaseGate") is not True:
            return None, "Wave 5 release-gate marker is invalid"
        if counts[1] == 0 and value.get("legacyTimezoneNavigationInjected") is not False:
            return None, "Wave 5 PASS cannot use legacy navigation injection"
        if counts[1] == 0 and value.get("fatalError") is not None:
            return None, "Wave 5 PASS cannot contain a fatal error"
    elif kind == "wave4-risk-browser":
        counts = _boolean_rows(value, "rows")
        listed_failures = _failure_list_count(value)
        if counts is None or listed_failures is None or not isinstance(value, dict):
            return None, "Wave 4 risk rows and failures must be arrays"
        counts = counts[0], max(counts[1], listed_failures)
        if counts[1] > counts[0]:
            return None, "Wave 4 risk report has more failures than assertions"
        if value.get("databaseDialect") != "postgresql":
            return None, "Wave 4 risk report did not use PostgreSQL"
        if value.get("target") != "isolated-loopback-real-api-postgresql-chromium":
            return None, "Wave 4 risk report target-runtime class is invalid"
    elif kind == "wave4-risk-fixture":
        if not isinstance(value, dict):
            return None, "Wave 4 risk fixture must be an object"
        expected_keys = {
            "organisation_id",
            "candidate_cluster_id",
            "candidate_version",
            "prepublished_label_id",
            "valid_request_id",
            "expired_request_id",
            "boundary_request_id",
            "database_dialect",
        }
        if set(value) != expected_keys or value.get("database_dialect") != "postgresql":
            return None, "Wave 4 risk fixture schema is invalid"
        uuid_keys = expected_keys - {"candidate_version", "database_dialect"}
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        if not all(
            isinstance(value.get(key), str) and uuid_pattern.fullmatch(value[key])
            for key in uuid_keys
        ):
            return None, "Wave 4 risk fixture UUID schema is invalid"
        if value.get("candidate_version") != "1":
            return None, "Wave 4 risk fixture version is invalid"
        return {
            "candidateType": "fixture",
            "producerState": "valid",
            "executed": False,
            "assertionCount": 0,
            "failedAssertionCount": 0,
            "inventoryComplete": True,
        }, None
    else:
        return None, "unknown evidence producer contract"

    if counts is None or (counts[0] <= 0 and state != "blocked"):
        return None, "evidence producer has no executed assertions"
    if counts[1] < 0 or counts[1] > counts[0]:
        return None, "evidence producer failure count is inconsistent"
    if state is None:
        state = "pass" if counts[1] == 0 else "fail"

    if state != "blocked" and artifact_id != "credential-browser":
        inventory_contract = INVENTORY_CONTRACTS.get(artifact_id)
        if inventory_contract is not None:
            rows_key, identity_key, _, _ = inventory_contract
            if _inventory(
                value,
                rows_key=rows_key,
                identity_key=identity_key,
            ) is None:
                return None, "assertion identity inventory is invalid or duplicated"
            inventory_complete = _inventory_matches(artifact_id, value)
    if state == "pass" and not inventory_complete:
        return None, "PASS assertion inventory is incomplete or substituted"
    return {
        "producerState": state,
        "executed": executed,
        "assertionCount": counts[0],
        "failedAssertionCount": counts[1],
        "inventoryComplete": inventory_complete,
    }, None


def _runtime_contract() -> dict:
    path = Path(__file__).resolve().parents[2] / "frontend/scripts/lib/wave1-runtime-diagnostics.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_categories(value: object) -> list[dict]:
    contract = _runtime_contract()
    if not isinstance(value, dict) or set(value) != set(contract["categories"]):
        raise ValueError("runtime category inventory invalid")
    result = []
    for field, (category, stage) in contract["categories"].items():
        events = value[field]
        if not isinstance(events, list):
            raise ValueError("runtime events invalid")
        grouped = {}
        for event in events:
            if (not isinstance(event, dict)
                    or set(event) != {"stage", "routeTemplate", "method", "status", "reason"}
                    or event["stage"] != stage
                    or event["routeTemplate"] not in contract["routeTemplates"]
                    or event["method"] not in contract["methods"]
                    or event["reason"] not in contract["reasons"]
                    or type(event["status"]) is not int
                    or not (event["status"] == 0 or 400 <= event["status"] <= 599)):
                raise ValueError("runtime event projection invalid")
            key = (event["routeTemplate"], event["method"], event["status"], event["reason"])
            grouped[key] = grouped.get(key, 0) + 1
        result.append({"category": category, "count": len(events), "routes": [
            {"routeTemplate": key[0], "method": key[1], "status": key[2], "reason": key[3], "count": count}
            for key, count in sorted(grouped.items())]})
    return result


def _runtime_categories_valid(value: object) -> bool:
    contract = _runtime_contract()
    if not isinstance(value, list) or len(value) != len(contract["categories"]):
        return False
    for row, (category, _) in zip(value, contract["categories"].values()):
        if (not isinstance(row, dict) or set(row) != {"category", "count", "routes"}
                or row["category"] != category or type(row["count"]) is not int or row["count"] < 0
                or not isinstance(row["routes"], list)):
            return False
        keys = set()
        total = 0
        for route in row["routes"]:
            if (not isinstance(route, dict) or set(route) != {"routeTemplate", "method", "status", "reason", "count"}
                    or route["routeTemplate"] not in contract["routeTemplates"]
                    or route["method"] not in contract["methods"] or route["reason"] not in contract["reasons"]
                    or type(route["status"]) is not int or not (route["status"] == 0 or 400 <= route["status"] <= 599)
                    or type(route["count"]) is not int or route["count"] <= 0):
                return False
            key = (route["routeTemplate"], route["method"], route["status"], route["reason"])
            if key in keys:
                return False
            keys.add(key)
            total += route["count"]
        if total != row["count"]:
            return False
    return True


def _failure_digests(value: dict) -> dict:
    """Export only sealed-inventory IDs and per-export keyed comparisons.

    The random HMAC key is never persisted. This permits within-export equality
    comparison without exposing low-entropy private values to dictionary attacks
    or linking values across runs. It is NOT a raw-content SHA attestation.
    """
    if not _inventory_matches("wave1-browser", value):
        raise ValueError("failed diagnostic inventory is not exact")
    key = os.urandom(32)
    rows = []
    for row in value["rows"]:
        if row["pass"] is not False:
            continue
        identity = row["area"]
        if (not isinstance(identity, str) or len(identity) > 256
                or re.fullmatch(r"[A-Za-z0-9_ .:/()\[\]|=-]+", identity) is None
                or not {"expected", "actual"} <= set(row)):
            raise ValueError("failed diagnostic row is not canonical")
        screens = set(re.findall(r"(?<![A-Z0-9])S-\d{2}(?!\d)", identity))
        if len(screens) > 1:
            raise ValueError("failed diagnostic screen is ambiguous")
        item = {"assertionId": identity,
                "screenId": next(iter(screens)) if screens else "not-screen-specific"}
        for field in ("expected", "actual"):
            canonical = json.dumps(row[field], sort_keys=True, ensure_ascii=True,
                                   allow_nan=False, separators=(",", ":")).encode()
            item[field + "Hash"] = hmac.new(key, canonical, hashlib.sha256).hexdigest()
        if identity == "functional_runtime":
            item["runtimeCategories"] = _runtime_categories(row["actual"])
            canonical = json.dumps(item["runtimeCategories"], sort_keys=True, separators=(",", ":")).encode()
            item["runtimeHash"] = hmac.new(key, canonical, hashlib.sha256).hexdigest()
        rows.append(item)
    return {"contract": "nyay40-failure-digests-v1",
            "hashScheme": "hmac-sha256-ephemeral-key-discarded", "rows": rows}


def _failure_digest_valid(value: object, expected_count: int) -> bool:
    if (type(expected_count) is not int
            or not isinstance(value, dict) or set(value) != {"contract", "hashScheme", "rows"}
            or value["contract"] != "nyay40-failure-digests-v1"
            or value["hashScheme"] != "hmac-sha256-ephemeral-key-discarded"
            or not isinstance(value["rows"], list)
            or len(value["rows"]) != expected_count or expected_count <= 0):
        return False
    identities = set()
    for row in value["rows"]:
        keys = {"assertionId", "screenId", "expectedHash", "actualHash"}
        if isinstance(row, dict) and "runtimeCategories" in row:
            keys |= {"runtimeCategories", "runtimeHash"}
            if (row.get("assertionId") != "functional_runtime"
                    or not _runtime_categories_valid(row["runtimeCategories"])
                    or not isinstance(row.get("runtimeHash"), str)
                    or re.fullmatch(r"[0-9a-f]{64}", row["runtimeHash"]) is None):
                return False
        if (not isinstance(row, dict)
                or set(row) != keys):
            return False
        identity = row["assertionId"]
        if (not isinstance(identity, str) or len(identity) > 256
                or re.fullmatch(r"[A-Za-z0-9_ .:/()\[\]|=-]+", identity) is None
                or identity in identities):
            return False
        identities.add(identity)
        screens = set(re.findall(r"(?<![A-Z0-9])S-\d{2}(?!\d)", identity))
        if len(screens) > 1 or row["screenId"] != (next(iter(screens)) if screens else "not-screen-specific"):
            return False
        if any(not isinstance(row[k], str) or re.fullmatch(r"[0-9a-f]{64}", row[k]) is None
               for k in ("expectedHash", "actualHash")):
            return False
    return True


def prepare(source: Path, destination: Path, profile: str) -> tuple[int, int, list[str]]:
    failures: list[str] = []
    source = source.expanduser()
    destination = destination.expanduser()
    try:
        source_mode = source.lstat().st_mode
    except FileNotFoundError:
        return 0, 0, ["evidence source does not exist"]
    except OSError as exc:
        return 0, 0, [f"evidence source cannot be inspected ({exc.__class__.__name__})"]
    if stat.S_ISLNK(source_mode) or not stat.S_ISDIR(source_mode):
        return 0, 0, ["evidence source must be a regular directory"]
    if destination.exists():
        return 0, 0, ["uploadable evidence destination already exists"]
    if destination.resolve().is_relative_to(source.resolve()):
        return 0, 0, ["uploadable evidence destination must be outside its source"]

    specs = PROFILE_SPECS.get(profile)
    if specs is None:
        return 0, 0, ["unknown evidence producer profile"]
    expected = {relative: (artifact_id, kind) for artifact_id, relative, kind in specs}
    candidates: dict[str, dict[str, object]] = {}
    failure_digests = None
    quarantined: list[dict[str, object]] = []
    files_seen = 0
    total_bytes = 0
    def walk_error(exc: OSError) -> None:
        failures.append(
            f"evidence source cannot be traversed ({exc.__class__.__name__})"
        )

    for current, directories, names in os.walk(
        source,
        topdown=True,
        followlinks=False,
        onerror=walk_error,
    ):
        current_path = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            candidate = current_path / name
            relative = candidate.relative_to(source).as_posix()
            if name.startswith("."):
                failures.append("hidden evidence directory is not allowed")
                continue
            try:
                mode = candidate.lstat().st_mode
            except OSError as exc:
                failures.append(f"evidence directory cannot be inspected ({exc.__class__.__name__})")
                continue
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                failures.append("non-regular evidence directory is not allowed")
                continue
            if "\n" in relative or "\r" in relative:
                failures.append("newline is not allowed in an evidence path")
                continue
            retained.append(name)
        directories[:] = retained

        for name in sorted(names):
            candidate = current_path / name
            relative = candidate.relative_to(source).as_posix()
            if name.startswith("."):
                failures.append("hidden evidence file is not allowed")
                continue
            if "\n" in relative or "\r" in relative:
                failures.append("newline is not allowed in an evidence path")
                continue
            try:
                before = candidate.lstat()
            except OSError as exc:
                failures.append(f"evidence file cannot be inspected ({exc.__class__.__name__})")
                continue
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                failures.append("non-regular evidence file is not allowed")
                continue
            files_seen += 1
            total_bytes += before.st_size
            if files_seen > MAX_SOURCE_FILES:
                failures.append("evidence source contains too many files")
                continue
            if total_bytes > MAX_SOURCE_TOTAL_BYTES:
                failures.append("evidence source exceeds the aggregate size limit")
                continue
            if before.st_size == 0:
                failures.append("zero-byte evidence file is not allowed")
                continue
            if before.st_size > MAX_SOURCE_FILE_BYTES:
                failures.append("evidence file exceeds the attestation size limit")
                continue
            if name == MANIFEST_NAME:
                continue
            if name == EXPORT_NAME:
                failures.append("reserved evidence export filename is not allowed in source")
                continue

            suffix = candidate.suffix.lower()
            sensitive_capture = any(
                part.casefold() in SENSITIVE_CAPTURE_DIRECTORIES
                for part in Path(relative).parts[:-1]
            )
            quarantine_row = {
                "mediaClass": _media_class(suffix),
                "sizeClass": _size_class(before.st_size),
            }
            if sensitive_capture:
                quarantine_row["mediaClass"] = "sensitive-capture"
                quarantined.append(quarantine_row)
                continue
            if relative not in expected:
                if suffix == ".json":
                    quarantine_row["mediaClass"] = "unapproved-json"
                quarantined.append(quarantine_row)
                continue
            if suffix != ".json":
                failures.append("required evidence producer output must be JSON")
                continue
            if before.st_size > MAX_EXPECTED_JSON_BYTES:
                failures.append("required evidence producer output exceeds the JSON limit")
                continue
            data, snapshot_error = _read_stable_regular_file(
                candidate,
                before,
                limit=MAX_EXPECTED_JSON_BYTES,
            )
            if snapshot_error or data is None:
                failures.append(snapshot_error or "evidence snapshot failed")
                continue
            try:
                parsed = _strict_json_load(data)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                failures.append("required evidence producer output is not valid UTF-8 JSON")
                continue
            artifact_id, kind = expected[relative]
            result, error = _safe_result(kind, parsed, artifact_id)
            if error or result is None:
                failures.append(error or "required evidence producer output is invalid")
                continue
            if artifact_id == "wave1-browser" and result["producerState"] == "fail":
                try:
                    failure_digests = _failure_digests(parsed)
                except (TypeError, ValueError):
                    failures.append("failed diagnostic projection is invalid")
                    continue
            candidates[relative] = {
                "artifactId": artifact_id,
                "sizeClass": _size_class(len(data)),
                **result,
            }

    if failures:
        return 0, 0, sorted(set(failures))
    missing = sorted(set(expected) - set(candidates))
    if missing:
        return 0, len(quarantined), ["evidence source is missing required producer output"]

    destination.mkdir(parents=True)
    quarantine_counts: dict[tuple[str, str], int] = {}
    for row in quarantined:
        key = (str(row["mediaClass"]), str(row["sizeClass"]))
        quarantine_counts[key] = quarantine_counts.get(key, 0) + 1
    export = {
        "contract": "nyayone-evidence-attestation-v1",
        "producerProfile": profile,
        "rawEvidenceUploaded": False,
        "assertionContentUploaded": False,
        "pixelPrivacyVerified": False,
        "structuredCandidateCount": len(candidates),
        "quarantinedCount": len(quarantined),
        "structuredCandidates": [candidates[relative] for _, relative, _ in specs],
        "quarantined": [
            {"mediaClass": media_class, "sizeClass": size_class, "count": count}
            for (media_class, size_class), count in sorted(quarantine_counts.items())
        ],
        "limitation": LIMITATION,
    }
    if failure_digests is not None:
        export["contract"] = "nyayone-evidence-attestation-v2"
        export["failureDigests"] = failure_digests
        export["limitation"] = FAILURE_LIMITATION
    (destination / EXPORT_NAME).write_text(
        json.dumps(export, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return len(candidates), len(quarantined), []


def _validate_attestation(
    root: Path,
    *,
    require_all_pass: bool,
) -> list[str]:
    """Validate the complete sealed schema, optionally requiring producer PASS."""

    try:
        root_mode = root.lstat().st_mode
    except OSError:
        return ["evidence attestation directory is unavailable"]
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        return ["evidence attestation root must be a regular directory"]
    export = root / EXPORT_NAME
    manifest = root / MANIFEST_NAME
    try:
        names = {item.name for item in root.iterdir()}
    except OSError:
        return ["evidence attestation directory cannot be inventoried"]
    if names != {EXPORT_NAME, MANIFEST_NAME}:
        return ["evidence attestation inventory is not exact"]
    try:
        export_mode = export.lstat().st_mode
        manifest_mode = manifest.lstat().st_mode
    except OSError:
        return ["evidence attestation seal is unavailable"]
    if (
        stat.S_ISLNK(export_mode)
        or not stat.S_ISREG(export_mode)
        or stat.S_ISLNK(manifest_mode)
        or not stat.S_ISREG(manifest_mode)
    ):
        return ["evidence attestation seal must contain regular files"]
    if export.stat().st_size <= 0 or export.stat().st_size > MAX_EXPECTED_JSON_BYTES:
        return ["evidence attestation export size is invalid"]
    try:
        export_bytes = export.read_bytes()
        manifest_text = manifest.read_text(encoding="utf-8")
        payload = _strict_json_load(export_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return ["evidence attestation seal is not strict UTF-8 text"]
    expected_manifest = (
        f"{hashlib.sha256(export_bytes).hexdigest()}  {EXPORT_NAME}\n"
    )
    if manifest_text != expected_manifest:
        return ["evidence attestation checksum seal is invalid"]
    if not isinstance(payload, dict):
        return ["evidence attestation export must be an object"]
    exact_keys = {
        "assertionContentUploaded", "contract", "limitation", "pixelPrivacyVerified",
        "producerProfile", "quarantined", "quarantinedCount", "rawEvidenceUploaded",
        "structuredCandidateCount", "structuredCandidates",
    }
    diagnostic_version = payload.get("contract") == "nyayone-evidence-attestation-v2"
    if diagnostic_version:
        exact_keys.add("failureDigests")
    if set(payload) != exact_keys:
        return ["evidence attestation top-level schema is not exact"]
    profile = payload.get("producerProfile")
    specs = PROFILE_SPECS.get(profile) if isinstance(profile, str) else None
    if (payload.get("contract") not in {"nyayone-evidence-attestation-v1", "nyayone-evidence-attestation-v2"}
            or specs is None or (diagnostic_version and profile != "wave1")):
        return ["evidence attestation contract is invalid"]
    if (
        payload.get("rawEvidenceUploaded") is not False
        or payload.get("assertionContentUploaded") is not False
        or payload.get("pixelPrivacyVerified") is not False
        or payload.get("limitation") != (FAILURE_LIMITATION if diagnostic_version else LIMITATION)
    ):
        return ["evidence attestation privacy classification is invalid"]
    candidates = payload.get("structuredCandidates")
    if diagnostic_version:
        if (not isinstance(candidates, list) or len(candidates) != 1
                or not isinstance(candidates[0], dict)
                or candidates[0].get("inventoryComplete") is not True
                or not _failure_digest_valid(payload["failureDigests"],
                    candidates[0].get("failedAssertionCount", 0))):
            return ["failed diagnostic schema is invalid"]
    structured_candidate_count = _nonnegative_integer(
        payload.get("structuredCandidateCount")
    )
    if (
        not isinstance(candidates, list)
        or structured_candidate_count != len(specs)
        or len(candidates) != len(specs)
    ):
        return ["evidence attestation has no producer candidates"]
    expected_ids = [artifact_id for artifact_id, _, _ in specs]
    actual_ids = [
        candidate.get("artifactId") if isinstance(candidate, dict) else None
        for candidate in candidates
    ]
    if actual_ids != expected_ids:
        return ["evidence attestation producer inventory is not exact"]
    quarantined = payload.get("quarantined")
    quarantined_count = _nonnegative_integer(payload.get("quarantinedCount"))
    if (
        not isinstance(quarantined, list)
        or quarantined_count is None
        or quarantined_count > MAX_SOURCE_FILES
        or structured_candidate_count + quarantined_count > MAX_SOURCE_FILES
    ):
        return ["evidence attestation quarantine inventory is invalid"]
    quarantine_total = 0
    previous_quarantine_key: tuple[str, str] | None = None
    for row in quarantined:
        if not isinstance(row, dict) or set(row) != {"mediaClass", "sizeClass", "count"}:
            return ["evidence attestation quarantine row schema is invalid"]
        count = _nonnegative_integer(row.get("count"))
        if (
            row.get("mediaClass") not in QUARANTINE_MEDIA_CLASSES
            or row.get("sizeClass") not in SIZE_CLASSES
            or count is None
            or count <= 0
            or count > MAX_SOURCE_FILES
        ):
            return ["evidence attestation quarantine row is invalid"]
        quarantine_key = (str(row["mediaClass"]), str(row["sizeClass"]))
        if (
            previous_quarantine_key is not None
            and quarantine_key <= previous_quarantine_key
        ):
            return ["evidence attestation quarantine rows are not unique and sorted"]
        previous_quarantine_key = quarantine_key
        quarantine_total += count
    if quarantine_total != quarantined_count:
        return ["evidence attestation quarantine count is inconsistent"]
    failures: list[str] = []
    executable = 0
    for candidate, spec in zip(candidates, specs):
        expected_artifact_id, _, expected_kind = spec
        if not isinstance(candidate, dict):
            failures.append("evidence attestation candidate is invalid")
            continue
        if candidate.get("sizeClass") not in SIZE_CLASSES:
            failures.append("evidence attestation candidate size class is invalid")
            continue
        if candidate.get("candidateType") == "fixture":
            assertion_count = _nonnegative_integer(candidate.get("assertionCount"))
            failed_count = _nonnegative_integer(
                candidate.get("failedAssertionCount")
            )
            if set(candidate) != {
                "artifactId", "assertionCount", "candidateType", "executed",
                "failedAssertionCount", "inventoryComplete", "producerState",
                "sizeClass",
            }:
                failures.append("evidence fixture candidate schema is invalid")
                continue
            if not (
                expected_artifact_id == "risk-label-fixture"
                and expected_kind == "wave4-risk-fixture"
                and candidate.get("producerState") == "valid"
                and candidate.get("executed") is False
                and assertion_count == 0
                and failed_count == 0
                and candidate.get("inventoryComplete") is True
            ):
                failures.append("evidence fixture candidate is invalid")
            continue
        executable += 1
        if set(candidate) != {
            "artifactId", "assertionCount", "executed", "failedAssertionCount",
            "inventoryComplete", "producerState", "sizeClass",
        }:
            failures.append("evidence producer candidate schema is invalid")
            continue
        assertion_count = _nonnegative_integer(candidate.get("assertionCount"))
        failed_count = _nonnegative_integer(candidate.get("failedAssertionCount"))
        artifact_id = candidate.get("artifactId")
        if artifact_id == "credential-browser":
            expected_assertion_count = sum(
                contract[0] for contract in CREDENTIAL_INVENTORY_CONTRACTS.values()
            )
        else:
            inventory_contract = (
                INVENTORY_CONTRACTS.get(artifact_id)
                if isinstance(artifact_id, str)
                else None
            )
            expected_assertion_count = (
                inventory_contract[2]
                if inventory_contract is not None
                else EXACT_AGGREGATE_ASSERTION_COUNTS.get(artifact_id)
                if isinstance(artifact_id, str)
                else None
            )
        producer_state = candidate.get("producerState")
        executed = candidate.get("executed")
        inventory_complete = candidate.get("inventoryComplete")
        common_counts_valid = (
            assertion_count is not None
            and failed_count is not None
            and expected_assertion_count is not None
            and 0 <= failed_count <= assertion_count <= expected_assertion_count
            and isinstance(inventory_complete, bool)
        )
        if producer_state == "pass":
            state_valid = (
                common_counts_valid
                and executed is True
                and assertion_count == expected_assertion_count
                and failed_count == 0
                and inventory_complete is True
            )
        elif producer_state == "fail":
            state_valid = (
                common_counts_valid
                and executed is True
                and assertion_count > 0
                and failed_count > 0
                and (
                    inventory_complete is False
                    or assertion_count == expected_assertion_count
                )
            )
        elif producer_state == "blocked":
            state_valid = (
                expected_kind.startswith("postgres-")
                and executed is False
                and assertion_count == 0
                and failed_count == 0
                and inventory_complete is False
            )
        else:
            state_valid = False
        if not state_valid:
            failures.append("evidence producer state is inconsistent")
        elif require_all_pass and producer_state != "pass":
            failures.append("an evidence producer did not execute to a complete PASS")
    if executable == 0:
        failures.append("evidence attestation has no executable producer")
    return sorted(set(failures))


def validate_attestation(root: Path) -> list[str]:
    """Validate exact sealed bytes before any artifact upload."""

    return _validate_attestation(root, require_all_pass=False)


def require_pass(root: Path) -> list[str]:
    """Fail unless a valid sealed attestation says every producer passed."""

    return _validate_attestation(root, require_all_pass=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--profile", choices=sorted(PROFILE_SPECS))
    mode.add_argument("--validate-attestation", action="store_true")
    mode.add_argument("--require-pass", action="store_true")
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    if args.require_pass or args.validate_attestation:
        if len(args.paths) != 1:
            parser.error("attestation validation needs exactly one directory")
        failures = (
            require_pass(args.paths[0])
            if args.require_pass
            else validate_attestation(args.paths[0])
        )
        if failures:
            print("Evidence attestation gate failed:", file=sys.stderr)
            print("\n".join(failures), file=sys.stderr)
            return 1
        print(
            "Evidence producer result gate passed"
            if args.require_pass
            else "Evidence pre-upload attestation validation passed"
        )
        return 0
    if len(args.paths) != 2 or args.profile is None:
        parser.error("--profile needs a source and destination directory")
    included, quarantined, failures = prepare(
        args.paths[0], args.paths[1], args.profile
    )
    if failures:
        print("Evidence export failed:", file=sys.stderr)
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(
        "Privacy-safe evidence attestation created: "
        f"structured_candidates={included} quarantined={quarantined} "
        f"destination={args.paths[1]}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
