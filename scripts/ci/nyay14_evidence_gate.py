#!/usr/bin/env python3
"""Validate and seal exact-head independent-QA evidence for NYAY-14.

The gate is deliberately standard-library only.  It treats evidence as hostile
input, reports stable finding codes without echoing sensitive values, and does
not create a manifest, report, archive, or merge authorization unless every
required contract is satisfied.
"""

from __future__ import annotations

import argparse
import importlib.util
import hashlib
import io
import json
import math
import os
import re
import shlex
import stat
import sys
import tarfile
import tempfile
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Mapping, Sequence


SCHEMA_VERSION = "nyay14-evidence/v1"
FUTURE_SCHEMA_VERSION = "nyay14-evidence/v2"
CONTACT_SHEET_POLICY_VERSION = "nyay27-contact-sheet-contract/v1"
SUPPORTED_SCHEMA_VERSIONS = (SCHEMA_VERSION, FUTURE_SCHEMA_VERSION)
HISTORICAL_V1_PACKAGE_SHA256 = (
    "a822ccace60c2c067553bff9c33866a329a811d048d846c9c46317c73bda357f",
)
CLASSIFICATIONS = ("PASS", "FAIL", "BLOCKED", "HEAD_CHANGED", "handoff-only")
RAW_CATEGORIES = (
    "backend",
    "postgresql-migration",
    "postgresql-concurrency",
    "frontend-native",
    "chromium",
)
MANIFEST_NAME = "SHA256SUMS.txt"
PACKAGE_RECORD_NAME = "VALIDATED_PACKAGE.json"
_MAX_ARCHIVE_EXPANDED_BYTES = 512 * 1024 * 1024
_MAX_ARCHIVE_COMPRESSED_BYTES = 512 * 1024 * 1024
_MAX_ARCHIVE_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 4096

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_UTC_RFC3339 = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)
_MANIFEST_ROW = re.compile(r"^([0-9a-f]{64})  ([^\r\n]+)$")
_NESTED_ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".7z",
    ".rar",
)


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


def _strict_json_loads(text: str) -> object:
    return json.loads(text, parse_constant=_reject_json_constant)


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _looks_like_nested_archive(payload: bytes) -> bool:
    """Recognize archives by content so renaming cannot bypass the seal."""

    if payload.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return True
    try:
        if zipfile.is_zipfile(io.BytesIO(payload)):
            return True
    except (OSError, ValueError):
        return True
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as bundle:
            bundle.getmembers()
            return True
    except (OSError, tarfile.TarError):
        pass
    if payload.startswith((b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00")):
        return True
    return any(
        marker in payload
        for marker in (
            b"7z\xbc\xaf\x27\x1c",
            b"Rar!\x1a\x07\x00",
            b"Rar!\x1a\x07\x01\x00",
        )
    )


def _dedupe(codes: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(codes))


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_git_sha(value: object) -> bool:
    return isinstance(value, str) and _GIT_SHA.fullmatch(value) is not None


def _safe_relative(value: object) -> Path | None:
    if not isinstance(value, str) or not value or "\\" in value:
        return None
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or any(part in ("", ".", "..") for part in candidate.parts):
        return None
    return Path(*candidate.parts)


def _inside(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_exclusive(path: Path, payload: bytes) -> str | None:
    """Create one regular file without following or replacing an existing node."""

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(path, flags, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                metadata = path.lstat()
                if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
                    path.unlink()
            except OSError:
                pass
        return "EXCLUSIVE_WRITE_FAILED"
    return None


def _remove_owned_file(path: Path) -> None:
    try:
        metadata = path.lstat()
        if stat.S_ISREG(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
            path.unlink()
    except OSError:
        pass


def _git_subcommand(operation: str) -> str | None:
    try:
        tokens = shlex.split(operation)
    except ValueError:
        return "invalid"
    if (
        not tokens
        or Path(tokens[0]).name != "git"
        or any(any(marker in token for marker in (";", "&&", "||", "|", "`", "$(", ">", "<")) for token in tokens)
    ):
        return "invalid"
    index = 1
    options_with_values = {"-C", "--git-dir", "--work-tree", "--namespace"}
    while index < len(tokens):
        token = tokens[index]
        if token in options_with_values:
            index += 2
            continue
        if token.startswith(("--git-dir=", "--work-tree=", "--namespace=")):
            index += 1
            continue
        if token == "-c" or token.startswith("-c="):
            return "invalid"
        if token.startswith("-"):
            index += 1
            continue
        return token.lower()
    return "invalid"


def _protected_operation_is_readonly(operation: str) -> bool:
    try:
        tokens = shlex.split(operation)
    except ValueError:
        return False
    if not tokens or Path(tokens[0]).name != "git":
        return False
    normalized = ("git", *tokens[1:])
    return normalized in {
        ("git", "status", "--porcelain=v1", "-z"),
        ("git", "rev-parse", "HEAD"),
        ("git", "rev-parse", "--show-toplevel"),
    }


def validate_classification(value: object) -> list[str]:
    return [] if value in CLASSIFICATIONS else ["INVALID_CLASSIFICATION"]


def classify(state: Mapping[str, object]) -> str:
    """Return the deterministic, fail-closed classification for one run."""

    if bool(state.get("headChanged")):
        return "HEAD_CHANGED"
    if bool(state.get("failed")):
        return "FAIL"
    if bool(state.get("blocked")):
        return "BLOCKED"
    if bool(state.get("handoffOnly")):
        return "handoff-only"
    return "PASS"


def validate_provenance(
    provenance: object,
    authoritative_remote_head: str,
    authoritative_repository: str | None = None,
    authoritative_base: str | None = None,
    authoritative_prospective_merge: str | None = None,
) -> list[str]:
    codes: list[str] = []
    if not isinstance(provenance, Mapping):
        return ["MISSING_PROVENANCE"]

    required = (
        "repository",
        "base",
        "reviewedHead",
        "remoteHead",
        "prospectiveMerge",
        "capturedAt",
    )
    if any(not _is_nonempty_string(provenance.get(field)) for field in required):
        codes.append("MISSING_PROVENANCE")

    repository = provenance.get("repository")
    if _is_nonempty_string(repository):
        parts = str(repository).split("/")
        if len(parts) != 2 or not all(parts):
            codes.append("INVALID_REPOSITORY")

    for field in ("base", "reviewedHead", "remoteHead", "prospectiveMerge"):
        value = provenance.get(field)
        if value is not None and not _is_git_sha(value):
            codes.append("INVALID_GIT_SHA")
    if not _is_git_sha(authoritative_remote_head):
        codes.append("INVALID_GIT_SHA")

    runtime = provenance.get("runtime")
    runtime_fields = ("os", "architecture", "python", "node", "chromium")
    if not isinstance(runtime, Mapping) or any(
        not _is_nonempty_string(runtime.get(field)) for field in runtime_fields
    ):
        codes.append("MISSING_RUNTIME_VERSION")
    elif any(
        not re.search(r"\d", str(runtime.get(field)))
        for field in ("python", "node", "chromium")
    ):
        codes.append("MISSING_RUNTIME_VERSION")

    captured_at = provenance.get("capturedAt")
    if not isinstance(captured_at, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", captured_at
    ) is None:
        codes.append("INVALID_CAPTURE_TIME")

    authoritative_values = (
        ("repository", authoritative_repository, _is_nonempty_string),
        ("base", authoritative_base, _is_git_sha),
        ("prospectiveMerge", authoritative_prospective_merge, _is_git_sha),
    )
    for field, authoritative, validator in authoritative_values:
        if authoritative is not None:
            if not validator(authoritative) or provenance.get(field) != authoritative:
                codes.append("PROVENANCE_MISMATCH")

    reviewed = provenance.get("reviewedHead")
    recorded_remote = provenance.get("remoteHead")
    if (
        _is_git_sha(authoritative_remote_head)
        and _is_git_sha(reviewed)
        and _is_git_sha(recorded_remote)
        and (reviewed != authoritative_remote_head or recorded_remote != authoritative_remote_head)
    ):
        codes.append("HEAD_CHANGED")
    return _dedupe(codes)


def validate_readbacks(package: object) -> list[str]:
    if not isinstance(package, Mapping):
        return ["EXACT_HEAD_READBACK_INVALID", "EXACT_MERGE_READBACK_INVALID"]
    provenance = package.get("provenance")
    readbacks = package.get("readbacks")
    if not isinstance(provenance, Mapping) or not isinstance(readbacks, Mapping):
        return ["EXACT_HEAD_READBACK_INVALID", "EXACT_MERGE_READBACK_INVALID"]

    exact_head = readbacks.get("exactHead")
    exact_merge = readbacks.get("exactMerge")
    codes: list[str] = []

    def valid_readback(value: object, kind: str, sha: object) -> bool:
        return (
            isinstance(value, Mapping)
            and value.get("kind") == kind
            and value.get("sha") == sha
            and _is_nonempty_string(value.get("capturedAt"))
            and _is_nonempty_string(value.get("artifactId"))
        )

    if not valid_readback(exact_head, "remote-head", provenance.get("reviewedHead")):
        codes.append("EXACT_HEAD_READBACK_INVALID")
    if not valid_readback(exact_merge, "merge-commit", provenance.get("prospectiveMerge")):
        codes.append("EXACT_MERGE_READBACK_INVALID")
    if isinstance(exact_head, Mapping) and isinstance(exact_merge, Mapping):
        if (
            exact_head.get("capturedAt") == exact_merge.get("capturedAt")
            or exact_head.get("artifactId") == exact_merge.get("artifactId")
            or exact_head.get("sha") == exact_merge.get("sha")
        ):
            codes.extend(("EXACT_HEAD_READBACK_INVALID", "EXACT_MERGE_READBACK_INVALID"))
    return _dedupe(codes)


def validate_raw_logs(
    inventory: object,
    evidence_root: Path,
    expected_schema_version: str = SCHEMA_VERSION,
) -> list[str]:
    if not isinstance(inventory, list):
        return ["MISSING_RAW_LOG"]
    root = Path(evidence_root).resolve(strict=False)
    codes: list[str] = []
    categories: list[str] = []
    ids: list[str] = []
    paths: list[str] = []

    for row in inventory:
        if not isinstance(row, Mapping):
            codes.append("UNSAFE_RAW_LOG")
            continue
        category = row.get("category")
        artifact_id = row.get("id")
        raw_path = row.get("path")
        expected_digest = row.get("sha256")
        if isinstance(category, str):
            categories.append(category)
        if isinstance(artifact_id, str):
            ids.append(artifact_id)
        if isinstance(raw_path, str):
            paths.append(raw_path)
        if category not in RAW_CATEGORIES:
            codes.append("UNEXPECTED_RAW_LOG")
        if not _is_nonempty_string(artifact_id) or not _is_sha256(expected_digest):
            codes.append("UNSAFE_RAW_LOG")
        relative = _safe_relative(raw_path)
        if relative is None:
            codes.append("UNSAFE_RAW_LOG")
            continue
        candidate = root / relative
        try:
            metadata = candidate.lstat()
            safe = (
                _inside(candidate, root)
                and stat.S_ISREG(metadata.st_mode)
                and not stat.S_ISLNK(metadata.st_mode)
                and metadata.st_size > 0
            )
            if not safe:
                codes.append("UNSAFE_RAW_LOG")
                continue
            if _is_sha256(expected_digest) and _hash_file(candidate) != expected_digest:
                codes.append("RAW_LOG_CHECKSUM_MISMATCH")
            try:
                document = _strict_json_loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                codes.append("RAW_LOG_FORMAT_INVALID")
                continue
            assertions = document.get("assertions") if isinstance(document, Mapping) else None
            if (
                not isinstance(document, Mapping)
                or document.get("schemaVersion") != expected_schema_version
                or not isinstance(assertions, list)
                or not assertions
                or any(
                    not isinstance(assertion, Mapping)
                    or not _is_nonempty_string(assertion.get("id"))
                    or not isinstance(assertion.get("pass"), bool)
                    or not _is_integer(assertion.get("executed"))
                    or assertion.get("executed", 0) <= 0
                    for assertion in assertions
                )
            ):
                codes.append("RAW_LOG_FORMAT_INVALID")
            elif any(assertion.get("pass") is not True for assertion in assertions):
                codes.append("RAW_ASSERTION_FAILURE")
        except OSError:
            codes.append("UNSAFE_RAW_LOG")

    for category in RAW_CATEGORIES:
        if categories.count(category) != 1:
            codes.append("MISSING_RAW_LOG" if category not in categories else "DUPLICATE_RAW_LOG")
    if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
        codes.append("DUPLICATE_RAW_LOG")
    raw_root = root / "raw"
    if raw_root.is_dir() and not raw_root.is_symlink():
        discovered = {
            path.relative_to(root).as_posix()
            for path in raw_root.rglob("*")
            if path.is_file() or path.is_symlink()
        }
        if discovered != set(paths):
            codes.append("UNLISTED_RAW_LOG")
    return _dedupe(codes)


def _json_pointer(document: object, pointer: str) -> tuple[bool, object]:
    if pointer == "":
        return True, document
    if not pointer.startswith("/"):
        return False, None
    current = document
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit() and int(token) < len(current):
            current = current[int(token)]
        else:
            return False, None
    return True, current


def validate_metric_traceability(package: object, evidence_root: Path) -> list[str]:
    if not isinstance(package, Mapping):
        return ["UNTRACEABLE_METRIC"]
    inventory = package.get("rawLogs")
    metrics = package.get("metrics")
    if not isinstance(inventory, list) or not isinstance(metrics, list) or not metrics:
        return ["UNTRACEABLE_METRIC"]
    by_id = {
        row.get("id"): row
        for row in inventory
        if isinstance(row, Mapping) and _is_nonempty_string(row.get("id"))
    }
    codes: list[str] = []
    root = Path(evidence_root).resolve(strict=False)
    for metric in metrics:
        if not isinstance(metric, Mapping):
            codes.append("UNTRACEABLE_METRIC")
            continue
        artifact_id = metric.get("artifactId")
        pointer = metric.get("jsonPointer")
        line_range = metric.get("lineRange")
        artifact = by_id.get(artifact_id)
        if (
            artifact is None
            or not _is_sha256(metric.get("sha256"))
            or metric.get("sha256") != artifact.get("sha256")
            or (not _is_nonempty_string(pointer) and not _is_nonempty_string(line_range))
        ):
            codes.append("UNTRACEABLE_METRIC")
            continue
        relative = _safe_relative(artifact.get("path"))
        if relative is None:
            codes.append("UNTRACEABLE_METRIC")
            continue
        target = root / relative
        try:
            if _hash_file(target) != artifact.get("sha256"):
                codes.append("UNTRACEABLE_METRIC")
                continue
            if _is_nonempty_string(pointer):
                document = _strict_json_loads(target.read_text(encoding="utf-8"))
                found, raw_value = _json_pointer(document, str(pointer))
                if not found:
                    codes.append("UNTRACEABLE_METRIC")
                    continue
                if metric.get("id") == "required-gate-count":
                    expected_value: object = len(inventory)
                elif isinstance(raw_value, list):
                    expected_value = len(raw_value)
                else:
                    expected_value = raw_value
                if metric.get("value") != expected_value:
                    codes.append("METRIC_VALUE_MISMATCH")
            else:
                match = re.fullmatch(r"([1-9]\d*)-([1-9]\d*)", str(line_range))
                if match is None:
                    codes.append("UNTRACEABLE_METRIC")
                    continue
                start, end = (int(value) for value in match.groups())
                lines = target.read_text(encoding="utf-8").splitlines()
                if end < start or end > len(lines):
                    codes.append("UNTRACEABLE_METRIC")
                elif metric.get("value") != end - start + 1:
                    codes.append("METRIC_VALUE_MISMATCH")
        except (OSError, UnicodeError, json.JSONDecodeError):
            codes.append("UNTRACEABLE_METRIC")
    return _dedupe(codes)


def validate_assertion_groups(groups: object) -> list[str]:
    if not isinstance(groups, list) or not groups:
        return ["MISSING_ASSERTIONS"]
    codes: list[str] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, Mapping) or not _is_nonempty_string(group.get("id")):
            codes.append("INVALID_ASSERTION_GROUP")
            continue
        group_id = str(group["id"])
        if group_id in seen:
            codes.append("INVALID_ASSERTION_GROUP")
        seen.add(group_id)
        executed = group.get("executed")
        passed = group.get("passed")
        failed = group.get("failed")
        if not _is_integer(executed) or executed <= 0:
            codes.append("ZERO_EXECUTED")
            continue
        if (
            not _is_integer(passed)
            or not _is_integer(failed)
            or passed < 0
            or failed < 0
            or passed + failed != executed
        ):
            codes.append("ASSERTION_COUNT_MISMATCH")
        elif failed:
            codes.append("ASSERTION_FAILURE")
    return _dedupe(codes)


def _visual_key(row: Mapping[str, object]) -> tuple[object, object, object, object]:
    viewport = row.get("viewport")
    if isinstance(viewport, Mapping):
        return (
            row.get("screen") if isinstance(row.get("screen"), str) else None,
            row.get("state") if isinstance(row.get("state"), str) else None,
            viewport.get("width") if _is_integer(viewport.get("width")) else None,
            viewport.get("height") if _is_integer(viewport.get("height")) else None,
        )
    return (
        row.get("screen") if isinstance(row.get("screen"), str) else None,
        row.get("state") if isinstance(row.get("state"), str) else None,
        None,
        None,
    )


def validate_visual_matrix(
    rows: object,
    expected_rows: object,
    _evidence_root: Path,
) -> list[str]:
    if not isinstance(rows, list) or not rows:
        return ["VISUAL_MATRIX_MISSING"]
    expected = expected_rows if isinstance(expected_rows, list) else []
    codes: list[str] = []
    if not expected:
        codes.append("APPROVED_VISUAL_MATRIX_MISSING")
    expected_by_key = {
        _visual_key(row): row for row in expected if isinstance(row, Mapping)
    }
    keys: list[tuple[object, object, object, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            codes.append("VISUAL_ROW_INVALID")
            continue
        viewport = row.get("viewport")
        basic_valid = (
            _is_nonempty_string(row.get("screen"))
            and _is_nonempty_string(row.get("state"))
            and isinstance(viewport, Mapping)
            and _is_integer(viewport.get("width"))
            and _is_integer(viewport.get("height"))
            and int(viewport.get("width", 0)) > 0
            and int(viewport.get("height", 0)) > 0
            and _is_nonempty_string(row.get("approvedReference"))
            and _is_git_sha(row.get("testedHead"))
        )
        if not basic_valid:
            codes.append("VISUAL_ROW_INVALID")
        if any(
            not _is_nonempty_string(row.get(field))
            for field in ("baselineArtifactId", "liveArtifactId", "comparisonArtifactId")
        ):
            codes.append("VISUAL_ARTIFACT_MISSING")
        executed = row.get("executed")
        metric = row.get("metric")
        if (
            not _is_integer(executed)
            or executed <= 0
            or not isinstance(metric, Mapping)
            or not _is_finite_number(metric.get("value"))
            or float(metric.get("value", -1)) < 0
            or not _is_finite_number(metric.get("threshold"))
            or float(metric.get("threshold", -1)) < 0
            or not _is_nonempty_string(metric.get("unit"))
        ):
            codes.append("VISUAL_ROW_INVALID")
        elif float(metric["value"]) > float(metric["threshold"]):
            codes.append("VISUAL_THRESHOLD_EXCEEDED")
        key = _visual_key(row)
        keys.append(key)
        expected_row = expected_by_key.get(key)
        if expected and expected_row is None:
            codes.append("VISUAL_MATRIX_MISMATCH")
        elif expected_row is not None:
            if row.get("approvedReference") != expected_row.get("approvedReference"):
                codes.append("UNAPPROVED_DESIGN_REFERENCE")
            if row.get("testedHead") != expected_row.get("testedHead"):
                codes.append("VISUAL_HEAD_MISMATCH")
    if len(keys) != len(set(keys)):
        codes.append("DUPLICATE_VISUAL_ROW")
    if expected and set(keys) != set(expected_by_key):
        codes.append("VISUAL_MATRIX_MISMATCH")
    return _dedupe(codes)


def _contact_sheet_artifact(
    package: Mapping[str, object],
    *,
    artifact_id: object,
    path: object,
) -> Mapping[str, object] | None:
    artifacts = package.get("evidenceArtifacts")
    if not isinstance(artifacts, list):
        return None
    matches = [
        row
        for row in artifacts
        if isinstance(row, Mapping)
        and row.get("id") == artifact_id
        and row.get("path") == path
    ]
    return matches[0] if len(matches) == 1 else None


def _contact_sheet_file(
    evidence_root: Path,
    raw_path: object,
) -> tuple[Path | None, int | None, str | None]:
    relative = _safe_relative(raw_path)
    if relative is None:
        return None, None, None
    root = evidence_root.resolve(strict=False)
    target = root / relative
    try:
        metadata = target.lstat()
        if (
            not _inside(target, root)
            or stat.S_ISLNK(metadata.st_mode)
            or not stat.S_ISREG(metadata.st_mode)
        ):
            return None, None, None
        return target, metadata.st_size, _hash_file(target)
    except OSError:
        return None, None, None


def _valid_contact_sheet_png(target: Path) -> bool:
    """Require a closed-world, metadata-free PNG with bounded decoded pixels.

    Contact-sheet text is sealed and scanned through the rendered-text sidecar.
    Consequently the image container accepts only the three chunks required for
    a non-interlaced true-colour raster. This prevents an otherwise unscanned
    ancillary chunk from becoming a covert PII or credential channel.
    """

    try:
        payload = target.read_bytes()
    except OSError:
        return False
    if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset = 8
    seen_ihdr = False
    seen_idat = False
    idat_finished = False
    idat_payload = bytearray()
    expected_decoded_bytes: int | None = None
    while offset < len(payload):
        if offset + 12 > len(payload):
            return False
        length = int.from_bytes(payload[offset : offset + 4], "big")
        kind = payload[offset + 4 : offset + 8]
        end = offset + 12 + length
        if length > 64 * 1024 * 1024 or end > len(payload):
            return False
        body = payload[offset + 8 : offset + 8 + length]
        declared_crc = int.from_bytes(payload[offset + 8 + length : end], "big")
        if zlib.crc32(kind + body) & 0xFFFFFFFF != declared_crc:
            return False
        if kind not in {b"IHDR", b"IDAT", b"IEND"}:
            return False
        if not seen_ihdr:
            if kind != b"IHDR" or length != 13:
                return False
            width = int.from_bytes(body[0:4], "big")
            height = int.from_bytes(body[4:8], "big")
            bit_depth, colour_type, compression, filtering, interlace = body[8:13]
            channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour_type)
            if (
                width <= 0
                or height <= 0
                or width > 32768
                or height > 32768
                or width * height > 32_000_000
                or bit_depth != 8
                or channels is None
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                return False
            expected_decoded_bytes = height * (1 + width * channels)
            seen_ihdr = True
        elif kind == b"IHDR":
            return False
        if kind == b"IDAT":
            if idat_finished:
                return False
            seen_idat = True
            idat_payload.extend(body)
            if len(idat_payload) > 64 * 1024 * 1024:
                return False
        elif seen_idat:
            idat_finished = True
        if kind == b"IEND":
            if (
                length != 0
                or not seen_ihdr
                or not seen_idat
                or end != len(payload)
                or expected_decoded_bytes is None
            ):
                return False
            try:
                decompressor = zlib.decompressobj()
                decoded = decompressor.decompress(
                    bytes(idat_payload), expected_decoded_bytes + 1
                )
                if (
                    len(decoded) > expected_decoded_bytes
                    or decompressor.unconsumed_tail
                ):
                    return False
                remaining = expected_decoded_bytes - len(decoded)
                decoded += decompressor.flush(remaining + 1)
            except zlib.error:
                return False
            return (
                decompressor.eof
                and not decompressor.unused_data
                and not decompressor.unconsumed_tail
                and len(decoded) == expected_decoded_bytes
            )
        offset = end
    return False


def _repository_privacy_scan_passes(target: Path, declared_path: object) -> bool:
    """Run the repository scanner over one textual visual-evidence record.

    The scanner's detailed strings can contain fragments from hostile input,
    so this boundary deliberately collapses every scanner finding or error to a
    boolean. Callers publish only the static NYAY-27 finding code.
    """

    scanner_path = Path(__file__).resolve().with_name("scan_evidence.py")
    module_name = "_nyay27_repository_evidence_scanner"
    try:
        spec = importlib.util.spec_from_file_location(module_name, scanner_path)
        if spec is None or spec.loader is None:
            return False
        scanner = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = scanner
        spec.loader.exec_module(scanner)
        payload = target.read_bytes()
        path_findings = scanner._path_findings(
            "contact-sheet-sidecar",
            str(declared_path),
        )
        _scanned, findings, errors = scanner._dispatch_payload(
            "contact-sheet-sidecar",
            "contact-sheet-sidecar.txt",
            payload,
            depth=0,
            archive_depth=0,
        )
        return not path_findings and not findings and not errors
    except Exception:
        return False
    finally:
        sys.modules.pop(module_name, None)


def _valid_utc_rfc3339(value: object) -> bool:
    if not isinstance(value, str) or _UTC_RFC3339.fullmatch(value) is None:
        return False
    try:
        # Round-tripping through date parsing rejects impossible calendar dates.
        import datetime

        datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def validate_combined_contact_sheet(
    package: object,
    evidence_root: Path,
    *,
    authoritative_reviewed_head: str,
    authoritative_source_archive_sha256: str,
    authoritative_ticket_type: str,
    authoritative_panel_roles: Sequence[str],
    contract: object,
) -> list[str]:
    """Validate the NYAY-27 v2 combined visual-evidence boundary.

    All authority inputs are supplied independently of the package. Historical
    v1 evidence never enters this function; if it does, it is treated as an
    attempted downgrade rather than trusting a package-controlled timestamp.
    """

    if not isinstance(package, Mapping):
        return ["CONTACT_SHEET_MISSING"]
    codes: list[str] = []
    if package.get("schemaVersion") != FUTURE_SCHEMA_VERSION:
        codes.append("HISTORICAL_SEAL_MISMATCH")
    if (
        not isinstance(contract, Mapping)
        or contract.get("schemaVersion") != CONTACT_SHEET_POLICY_VERSION
        or contract.get("futureEvidenceSchemaVersion") != FUTURE_SCHEMA_VERSION
        or contract.get("legacyEvidenceSchemaVersion") != SCHEMA_VERSION
        or authoritative_ticket_type not in {"ui", "non-ui"}
        or not _is_git_sha(authoritative_reviewed_head)
        or not _is_sha256(authoritative_source_archive_sha256)
        or not isinstance(authoritative_panel_roles, Sequence)
        or isinstance(authoritative_panel_roles, (str, bytes))
        or not authoritative_panel_roles
        or any(not _is_nonempty_string(role) for role in authoritative_panel_roles)
    ):
        codes.append("CONTACT_SHEET_PROVENANCE_MISMATCH")

    allowed_publishers = contract.get("publishers") if isinstance(contract, Mapping) else None
    ticket = package.get("ticket")
    package_provenance = package.get("provenance")
    if (
        not isinstance(allowed_publishers, list)
        or package.get("publisher") not in allowed_publishers
        or not isinstance(ticket, Mapping)
        or ticket.get("type") != authoritative_ticket_type
        or not isinstance(package_provenance, Mapping)
        or package_provenance.get("reviewedHead") != authoritative_reviewed_head
    ):
        codes.append("CONTACT_SHEET_PROVENANCE_MISMATCH")

    sheet = package.get("combinedContactSheet")
    if not isinstance(sheet, Mapping):
        return _dedupe([*codes, "CONTACT_SHEET_MISSING"])

    sheet_id = sheet.get("artifactId")
    sheet_path = sheet.get("path")
    declared_sheet_sha = sheet.get("sha256")
    artifact = _contact_sheet_artifact(
        package,
        artifact_id=sheet_id,
        path=sheet_path,
    )
    target, size, actual_sheet_sha = _contact_sheet_file(Path(evidence_root), sheet_path)
    if target is None:
        codes.append("CONTACT_SHEET_MISSING")
    elif size == 0:
        codes.append("CONTACT_SHEET_EMPTY")
    if artifact is None:
        codes.append("CONTACT_SHEET_UNMANIFESTED")
    elif (
        artifact.get("sha256") != declared_sheet_sha
        or (
            "bytes" in artifact
            and (not _is_integer(artifact.get("bytes")) or artifact.get("bytes") != size)
        )
    ):
        codes.append("CONTACT_SHEET_HASH_MISMATCH")
    if (
        not _is_sha256(declared_sheet_sha)
        or actual_sheet_sha != declared_sheet_sha
    ):
        codes.append("CONTACT_SHEET_HASH_MISMATCH")
    if (
        target is None
        or not isinstance(sheet_path, str)
        or Path(sheet_path).suffix.lower() != ".png"
        or not _valid_contact_sheet_png(target)
    ):
        codes.append("CONTACT_SHEET_FORMAT_MISMATCH")

    provenance = sheet.get("provenance")
    package_reviewed_head = (
        package_provenance.get("reviewedHead")
        if isinstance(package_provenance, Mapping)
        else None
    )
    if (
        not isinstance(provenance, Mapping)
        or provenance.get("sheetSha256") != declared_sheet_sha
        or provenance.get("sheetSha256") != actual_sheet_sha
        or provenance.get("sourceArchiveSha256")
        != authoritative_source_archive_sha256
        or provenance.get("reviewedHead") != authoritative_reviewed_head
        or provenance.get("reviewedHead") != package_reviewed_head
        or not _valid_utc_rfc3339(provenance.get("generatedAt"))
    ):
        codes.append("CONTACT_SHEET_PROVENANCE_MISMATCH")

    expected_format = (
        "ui-design-parity" if authoritative_ticket_type == "ui" else "rendered-evidence"
    )
    if sheet.get("format") != expected_format:
        codes.append("CONTACT_SHEET_FORMAT_MISMATCH")
    panels = sheet.get("panels")
    panel_count = sheet.get("panelCount")
    if (
        not isinstance(panels, list)
        or not panels
        or not _is_integer(panel_count)
        or panel_count <= 0
    ):
        codes.append("CONTACT_SHEET_ZERO_PANELS")
    panel_rows = panels if isinstance(panels, list) else []
    roles = [
        row.get("role") if isinstance(row, Mapping) else None for row in panel_rows
    ]
    ids = [row.get("id") if isinstance(row, Mapping) else None for row in panel_rows]
    panel_artifact_ids = [
        row.get("artifactId") if isinstance(row, Mapping) else None
        for row in panel_rows
    ]
    artifact_inventory = {
        row.get("id")
        for collection in (package.get("rawLogs"), package.get("evidenceArtifacts"))
        if isinstance(collection, list)
        for row in collection
        if isinstance(row, Mapping) and _is_nonempty_string(row.get("id"))
    }
    required_roles = list(authoritative_panel_roles)
    if authoritative_ticket_type == "ui" and required_roles != [
        "approved-baseline",
        "live-implementation",
    ]:
        codes.append("CONTACT_SHEET_PANEL_SET_INVALID")
    panel_set_valid = (
        _is_integer(panel_count)
        and panel_count == len(panel_rows)
        and panel_count > 0
        and roles == required_roles
        and all(_is_nonempty_string(value) for value in ids)
        and len(ids) == len(set(ids))
        and all(_is_nonempty_string(value) for value in panel_artifact_ids)
        and all(value in artifact_inventory for value in panel_artifact_ids)
    )
    if authoritative_ticket_type == "ui":
        positions = [
            row.get("position") if isinstance(row, Mapping) else None
            for row in panel_rows
        ]
        panel_set_valid = panel_set_valid and positions == ["left", "right"]
    if not panel_set_valid:
        codes.append("CONTACT_SHEET_PANEL_SET_INVALID")

    sidecar = sheet.get("renderedTextSidecar")
    if not isinstance(sidecar, Mapping):
        sidecar = sheet.get("pixelContentScanRecord")
    if not isinstance(sidecar, Mapping):
        return _dedupe([*codes, "CONTACT_SHEET_SIDECAR_MISSING"])
    sidecar_id = sidecar.get("artifactId")
    sidecar_path = sidecar.get("path")
    declared_sidecar_sha = sidecar.get("sha256")
    sidecar_artifact = _contact_sheet_artifact(
        package,
        artifact_id=sidecar_id,
        path=sidecar_path,
    )
    sidecar_target, sidecar_size, actual_sidecar_sha = _contact_sheet_file(
        Path(evidence_root), sidecar_path
    )
    if sidecar_target is None or sidecar_size in (None, 0) or sidecar_artifact is None:
        codes.append("CONTACT_SHEET_SIDECAR_MISSING")
    if sidecar_artifact is not None and (
        sidecar_artifact.get("sha256") != declared_sidecar_sha
        or (
            "bytes" in sidecar_artifact
            and (
                not _is_integer(sidecar_artifact.get("bytes"))
                or sidecar_artifact.get("bytes") != sidecar_size
            )
        )
    ):
        codes.append("CONTACT_SHEET_SIDECAR_HASH_MISMATCH")
    if (
        not _is_sha256(declared_sidecar_sha)
        or actual_sidecar_sha != declared_sidecar_sha
    ):
        codes.append("CONTACT_SHEET_SIDECAR_HASH_MISMATCH")

    scan = sidecar.get("privacyScan")
    bindings = sidecar.get("contentBindings")
    expected_binding_lines = {
        f"sheetSha256={declared_sheet_sha}",
        f"sourceArchiveSha256={authoritative_source_archive_sha256}",
        f"reviewedHead={authoritative_reviewed_head}",
        f"panelCount={panel_count}",
        "panelRoles=" + ",".join(str(role) for role in roles),
    }
    binding_claim_valid = (
        isinstance(bindings, Mapping)
        and bindings.get("sheetSha256") == declared_sheet_sha
        and bindings.get("sourceArchiveSha256")
        == authoritative_source_archive_sha256
        and bindings.get("reviewedHead") == authoritative_reviewed_head
        and bindings.get("panelCount") == panel_count
        and bindings.get("panelRoles") == roles
    )
    scan_claim_valid = (
        isinstance(scan, Mapping)
        and scan.get("scanner") == "scripts/ci/scan_evidence.py"
        and _is_nonempty_string(scan.get("scannerVersion"))
        and _is_integer(scan.get("executed"))
        and scan.get("executed", 0) > 0
        and scan.get("findings") == 0
        and scan.get("passed") is True
    )
    sidecar_binds_content = False
    if sidecar_target is not None:
        try:
            rendered_text = sidecar_target.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            rendered_text = ""
        sidecar_binds_content = expected_binding_lines.issubset(
            set(rendered_text.splitlines())
        )
    if not binding_claim_valid or not sidecar_binds_content:
        codes.append("CONTACT_SHEET_PROVENANCE_MISMATCH")
    if (
        not scan_claim_valid
        or sidecar_target is None
        or not _repository_privacy_scan_passes(sidecar_target, sidecar_path)
    ):
        codes.append("CONTACT_SHEET_PRIVACY_SCAN_FAILED")
    return _dedupe(codes)


def validate_evidence_artifacts(artifacts: object, evidence_root: Path) -> list[str]:
    if not isinstance(artifacts, list) or not artifacts:
        return ["UNTRACEABLE_EVIDENCE_ARTIFACT"]
    root = Path(evidence_root).resolve(strict=False)
    codes: list[str] = []
    ids: list[str] = []
    paths: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            codes.append("UNTRACEABLE_EVIDENCE_ARTIFACT")
            continue
        artifact_id = artifact.get("id")
        raw_path = artifact.get("path")
        expected = artifact.get("sha256")
        if isinstance(artifact_id, str):
            ids.append(artifact_id)
        if isinstance(raw_path, str):
            paths.append(raw_path)
        relative = _safe_relative(raw_path)
        if (
            not _is_nonempty_string(artifact_id)
            or relative is None
            or not _is_sha256(expected)
        ):
            codes.append("UNTRACEABLE_EVIDENCE_ARTIFACT")
            continue
        target = root / relative
        try:
            metadata = target.lstat()
            if (
                not _inside(target, root)
                or stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size <= 0
                or _hash_file(target) != expected
            ):
                codes.append("UNTRACEABLE_EVIDENCE_ARTIFACT")
        except OSError:
            codes.append("UNTRACEABLE_EVIDENCE_ARTIFACT")
    if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
        codes.append("UNTRACEABLE_EVIDENCE_ARTIFACT")
    return _dedupe(codes)


def validate_artifact_references(package: object) -> list[str]:
    if not isinstance(package, Mapping):
        return ["UNTRACEABLE_EVIDENCE_ARTIFACT"]
    raw_logs = package.get("rawLogs")
    artifacts = package.get("evidenceArtifacts")
    raw_ids = {
        row.get("id")
        for row in raw_logs or []
        if isinstance(row, Mapping) and _is_nonempty_string(row.get("id"))
    }
    evidence_ids = {
        row.get("id")
        for row in artifacts or []
        if isinstance(row, Mapping) and _is_nonempty_string(row.get("id"))
    }
    if raw_ids & evidence_ids:
        return ["UNTRACEABLE_EVIDENCE_ARTIFACT"]
    all_ids = raw_ids | evidence_ids
    referenced: list[object] = []
    for group in package.get("assertionGroups") or []:
        if isinstance(group, Mapping):
            artifact_ids = group.get("artifactIds")
            if not isinstance(artifact_ids, list) or not artifact_ids:
                return ["UNTRACEABLE_EVIDENCE_ARTIFACT"]
            referenced.extend(artifact_ids)
    for row in package.get("visualComparisons") or []:
        if isinstance(row, Mapping):
            referenced.extend(
                row.get(field)
                for field in (
                    "baselineArtifactId",
                    "liveArtifactId",
                    "comparisonArtifactId",
                )
            )
    quality = package.get("qualityResults")
    if isinstance(quality, Mapping):
        for name in ("accessibility", "privacy", "credentials", "seededOracle"):
            value = quality.get(name)
            if isinstance(value, Mapping):
                referenced.append(value.get("artifactId"))
    readbacks = package.get("readbacks")
    if isinstance(readbacks, Mapping):
        for name in ("exactHead", "exactMerge"):
            value = readbacks.get(name)
            if isinstance(value, Mapping):
                referenced.append(value.get("artifactId"))
    if not referenced or any(
        not _is_nonempty_string(reference) or reference not in all_ids
        for reference in referenced
    ):
        return ["UNTRACEABLE_EVIDENCE_ARTIFACT"]
    return []


def validate_quality_results(results: object) -> list[str]:
    if not isinstance(results, Mapping):
        return [
            "ACCESSIBILITY_RESULT_INVALID",
            "PRIVACY_RESULT_INVALID",
            "CREDENTIAL_RESULT_INVALID",
            "SEEDED_ORACLE_INVALID",
        ]
    codes: list[str] = []

    accessibility = results.get("accessibility")
    if not (
        isinstance(accessibility, Mapping)
        and _is_integer(accessibility.get("executed"))
        and accessibility.get("executed", 0) > 0
        and _is_nonempty_string(accessibility.get("tool"))
        and _is_nonempty_string(accessibility.get("toolVersion"))
        and _is_sha256(accessibility.get("ruleInventoryDigest"))
        and _is_integer(accessibility.get("serious"))
        and _is_integer(accessibility.get("critical"))
        and _is_nonempty_string(accessibility.get("artifactId"))
    ):
        codes.append("ACCESSIBILITY_RESULT_INVALID")
    elif accessibility.get("serious", 0) or accessibility.get("critical", 0):
        codes.append("ACCESSIBILITY_VIOLATION")

    privacy = results.get("privacy")
    if not (
        isinstance(privacy, Mapping)
        and _is_integer(privacy.get("executed"))
        and privacy.get("executed", 0) > 0
        and _is_nonempty_string(privacy.get("scanner"))
        and _is_nonempty_string(privacy.get("scannerVersion"))
        and _is_integer(privacy.get("findings"))
        and privacy.get("findings", -1) >= 0
        and _is_nonempty_string(privacy.get("artifactId"))
    ):
        codes.append("PRIVACY_RESULT_INVALID")
    elif privacy.get("findings", 0):
        codes.append("PRIVACY_FINDING")

    credentials = results.get("credentials")
    if not (
        isinstance(credentials, Mapping)
        and _is_integer(credentials.get("executed"))
        and credentials.get("executed", 0) > 0
        and _is_integer(credentials.get("findings"))
        and credentials.get("findings", -1) >= 0
        and _is_nonempty_string(credentials.get("artifactId"))
    ):
        codes.append("CREDENTIAL_RESULT_INVALID")
    elif credentials.get("findings", 0):
        codes.append("CREDENTIAL_FINDING")

    oracle = results.get("seededOracle")
    oracle_shape_valid = (
        isinstance(oracle, Mapping)
        and _is_integer(oracle.get("executed"))
        and oracle.get("executed", 0) > 0
        and _is_integer(oracle.get("planted"))
        and oracle.get("planted", 0) > 0
        and _is_integer(oracle.get("detected"))
        and oracle.get("detected", -1) >= 0
        and _is_nonempty_string(oracle.get("artifactId"))
    )
    if not oracle_shape_valid:
        codes.append("SEEDED_ORACLE_INVALID")
    if (
        isinstance(oracle, Mapping)
        and _is_integer(oracle.get("executed"))
        and _is_integer(oracle.get("planted"))
        and _is_integer(oracle.get("detected"))
        and (
            oracle.get("detected") != oracle.get("planted")
            or oracle.get("executed") < oracle.get("planted")
        )
    ):
        codes.append("SEEDED_ORACLE_SURVIVED")
    return _dedupe(codes)


def _sensitive_kinds(text: str) -> set[str]:
    kinds: set[str] = set()
    for email in re.findall(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text):
        if not email.lower().endswith("@example.test"):
            kinds.add("email")
    patterns = {
        "mobile": r"(?<!\d)\+91[\s-]*\d{5}[\s-]*\d{5}(?!\d)",
        "otp": r"(?i)[\"']?\botp[\"']?\s*[:=]\s*[\"']?\d{4,8}\b",
        "cookie": (
            r"(?i)[\"']?(?:nyayone_session|session_cookie|cookie)[\"']?\s*[:=]\s*"
            r"[\"']?(?!<redacted>|\[redacted\]|redacted)[^\"'\s,;}]+"
        ),
        "token": (
            r"(?i)[\"']?(?:authorization|auth_token|session_token)[\"']?\s*[:=]\s*"
            r"[\"']?(?:bearer\s+)?(?!redacted\b|<redacted>\b|\[redacted\]\b)"
            r"[^\"'\s,;}]+"
        ),
        "password": (
            r"(?i)[\"']?\bpassword[\"']?\s*[:=]\s*"
            r"[\"']?(?!<redacted>|\[redacted\]|redacted)[^\"'\s,;}]+"
        ),
    }
    for kind, pattern in patterns.items():
        if re.search(pattern, text):
            kinds.add(kind)
    return kinds


def scan_before_seal(evidence_root: Path) -> dict[str, object]:
    root = Path(evidence_root)
    codes: list[str] = []
    counts: dict[str, int] = {}
    try:
        root_mode = root.lstat().st_mode
    except OSError:
        return {"codes": ["EVIDENCE_ROOT_UNAVAILABLE"], "sealAllowed": False, "findingCounts": {}}
    if not stat.S_ISDIR(root_mode) or stat.S_ISLNK(root_mode):
        return {"codes": ["EVIDENCE_ROOT_UNSAFE"], "sealAllowed": False, "findingCounts": {}}

    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        retained: list[str] = []
        for name in directories:
            candidate = current_path / name
            try:
                mode = candidate.lstat().st_mode
            except OSError:
                codes.append("UNREADABLE_EVIDENCE")
                continue
            if stat.S_ISLNK(mode):
                codes.append("UNSAFE_ARTIFACT_NODE")
            else:
                retained.append(name)
        directories[:] = retained
        for name in files:
            candidate = current_path / name
            try:
                metadata = candidate.lstat()
                if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                    codes.append("UNSAFE_ARTIFACT_NODE")
                    continue
                payload = candidate.read_bytes()
            except OSError:
                codes.append("UNREADABLE_EVIDENCE")
                continue
            text = payload.decode("utf-8", errors="ignore")
            kinds = _sensitive_kinds(candidate.relative_to(root).as_posix() + "\n" + text)
            for kind in kinds:
                counts[kind] = counts.get(kind, 0) + 1
            if kinds:
                codes.append("PII_OR_SECRET_DETECTED")
    unique = _dedupe(codes)
    return {"codes": unique, "sealAllowed": not unique, "findingCounts": counts}


def _inventory(
    root: Path,
    *,
    existing_manifest_allowed: bool,
) -> tuple[dict[str, Path], set[str], list[str]]:
    safe: dict[str, Path] = {}
    all_nodes: set[str] = set()
    codes: list[str] = []
    try:
        mode = root.lstat().st_mode
    except OSError:
        return {}, set(), ["EVIDENCE_ROOT_UNAVAILABLE"]
    if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        return {}, set(), ["EVIDENCE_ROOT_UNSAFE"]

    for current, directories, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        retained: list[str] = []
        for name in sorted(directories):
            candidate = current_path / name
            relative = candidate.relative_to(root).as_posix()
            try:
                node_mode = candidate.lstat().st_mode
            except OSError:
                codes.append("UNSAFE_ARTIFACT_NODE")
                continue
            if name.startswith("."):
                codes.append("HIDDEN_ARTIFACT")
            elif stat.S_ISLNK(node_mode) or not stat.S_ISDIR(node_mode):
                all_nodes.add(relative)
                codes.append("UNSAFE_ARTIFACT_NODE")
            else:
                retained.append(name)
        directories[:] = retained
        for name in sorted(files):
            candidate = current_path / name
            relative = candidate.relative_to(root).as_posix()
            if relative == MANIFEST_NAME:
                try:
                    manifest_mode = candidate.lstat().st_mode
                except OSError:
                    codes.append("UNSAFE_MANIFEST_NODE")
                    continue
                if stat.S_ISLNK(manifest_mode) or not stat.S_ISREG(manifest_mode):
                    codes.append("UNSAFE_MANIFEST_NODE")
                elif not existing_manifest_allowed:
                    codes.append("MANIFEST_ALREADY_EXISTS")
                continue
            all_nodes.add(relative)
            try:
                metadata = candidate.lstat()
            except OSError:
                codes.append("UNSAFE_ARTIFACT_NODE")
                continue
            if name.startswith(".") or any(part.startswith(".") for part in PurePosixPath(relative).parts):
                codes.append("HIDDEN_ARTIFACT")
            elif stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                codes.append("UNSAFE_ARTIFACT_NODE")
            elif metadata.st_size == 0:
                codes.append("ZERO_BYTE_ARTIFACT")
            elif relative.lower().endswith(_NESTED_ARCHIVE_SUFFIXES):
                codes.append("NESTED_ARCHIVE")
            elif "\n" in relative or "\r" in relative:
                codes.append("UNSAFE_ARTIFACT_PATH")
            else:
                try:
                    payload = candidate.read_bytes()
                except OSError:
                    codes.append("UNREADABLE_EVIDENCE")
                    continue
                if _looks_like_nested_archive(payload):
                    codes.append("NESTED_ARCHIVE")
                else:
                    safe[relative] = candidate
    return safe, all_nodes, _dedupe(codes)


def _evidence_snapshot(evidence_root: Path) -> tuple[dict[str, str], list[str]]:
    """Hash the input-owned evidence tree, excluding gate-owned seal files."""

    files, all_nodes, codes = _inventory(
        Path(evidence_root), existing_manifest_allowed=True
    )
    files.pop(PACKAGE_RECORD_NAME, None)
    all_nodes.discard(PACKAGE_RECORD_NAME)
    if set(files) != all_nodes:
        codes.append("EVIDENCE_INVENTORY_UNSAFE")
    snapshot: dict[str, str] = {}
    for relative, path in sorted(files.items()):
        try:
            snapshot[relative] = _hash_file(path)
        except OSError:
            codes.append("UNREADABLE_EVIDENCE")
    return snapshot, _dedupe(codes)


def _seal_source_snapshot(
    evidence_root: Path, *, include_manifest: bool
) -> tuple[dict[str, str], list[str]]:
    root = Path(evidence_root)
    files, all_nodes, codes = _inventory(
        root, existing_manifest_allowed=include_manifest
    )
    if set(files) != all_nodes:
        codes.append("EVIDENCE_INVENTORY_UNSAFE")
    snapshot: dict[str, str] = {}
    for relative, path in sorted(files.items()):
        try:
            snapshot[relative] = _hash_file(path)
        except OSError:
            codes.append("UNREADABLE_EVIDENCE")
    if include_manifest:
        manifest = root / MANIFEST_NAME
        try:
            metadata = manifest.lstat()
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_size <= 0
            ):
                raise OSError("unsafe manifest")
            snapshot[MANIFEST_NAME] = _hash_file(manifest)
        except OSError:
            codes.append("MANIFEST_MISSING")
    return snapshot, _dedupe(codes)


def generate_manifest(evidence_root: Path) -> dict[str, object]:
    root = Path(evidence_root)
    initial_snapshot, initial_codes = _seal_source_snapshot(
        root, include_manifest=False
    )
    privacy = scan_before_seal(root)
    files, _all_nodes, inventory_codes = _inventory(
        root, existing_manifest_allowed=False
    )
    codes = [*initial_codes, *privacy["codes"], *inventory_codes]
    if not files:
        codes.append("EMPTY_EVIDENCE")
    current_snapshot: dict[str, str] = {}
    for relative, path in sorted(files.items()):
        try:
            current_snapshot[relative] = _hash_file(path)
        except OSError:
            codes.append("UNREADABLE_EVIDENCE")
    if current_snapshot != initial_snapshot:
        codes.append("EVIDENCE_CHANGED_DURING_SEAL")
    if codes:
        return {"codes": _dedupe(codes), "entries": 0}
    rows = [f"{current_snapshot[relative]}  {relative}" for relative in sorted(files)]
    error = _write_exclusive(
        root / MANIFEST_NAME,
        ("\n".join(rows) + "\n").encode("utf-8"),
    )
    if error:
        return {"codes": ["MANIFEST_WRITE_FAILED"], "entries": 0}
    post_privacy = scan_before_seal(root)
    verification = verify_manifest(root)
    final_snapshot, final_codes = _seal_source_snapshot(
        root, include_manifest=True
    )
    final_snapshot.pop(MANIFEST_NAME, None)
    post_codes = [
        *post_privacy["codes"],
        *verification["codes"],
        *final_codes,
    ]
    if final_snapshot != initial_snapshot:
        post_codes.append("EVIDENCE_CHANGED_DURING_SEAL")
    if post_codes:
        _remove_owned_file(root / MANIFEST_NAME)
        return {"codes": _dedupe(post_codes), "entries": 0}
    return {"codes": [], "entries": len(rows), "manifest": MANIFEST_NAME}


def _parse_manifest_text(text: str) -> tuple[dict[str, str], list[str]]:
    entries: dict[str, str] = {}
    codes: list[str] = []
    for line in text.splitlines():
        match = _MANIFEST_ROW.fullmatch(line)
        if not match:
            codes.append("MALFORMED_MANIFEST")
            continue
        expected, raw_path = match.groups()
        relative = _safe_relative(raw_path)
        if relative is None or raw_path == MANIFEST_NAME:
            codes.append("UNSAFE_MANIFEST_PATH")
            continue
        normalized = relative.as_posix()
        if normalized in entries:
            codes.append("DUPLICATE_MANIFEST_ENTRY")
            continue
        entries[normalized] = expected
    if not entries:
        codes.append("EMPTY_MANIFEST")
    return entries, _dedupe(codes)


def verify_manifest(evidence_root: Path) -> dict[str, object]:
    root = Path(evidence_root)
    files, all_nodes, codes = _inventory(root, existing_manifest_allowed=True)
    manifest = root / MANIFEST_NAME
    try:
        metadata = manifest.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0:
            raise OSError("unsafe manifest")
        text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {"codes": _dedupe([*codes, "MANIFEST_MISSING"]), "entries": 0}
    entries, parse_codes = _parse_manifest_text(text)
    codes.extend(parse_codes)
    if set(entries) != all_nodes:
        codes.append("INVENTORY_MISMATCH")
    verified = 0
    for relative in sorted(set(entries) & set(files)):
        try:
            actual = _hash_file(files[relative])
        except OSError:
            codes.append("UNREADABLE_ARTIFACT")
            continue
        if actual != entries[relative]:
            codes.append("CHECKSUM_MISMATCH")
        else:
            verified += 1
    return {"codes": _dedupe(codes), "entries": verified}


def build_clean_archive(evidence_root: Path, archive_path: Path) -> dict[str, object]:
    root = Path(evidence_root).resolve(strict=False)
    target = Path(archive_path).resolve(strict=False)
    if _inside(target, root):
        return {"codes": ["UNSAFE_ARCHIVE_DESTINATION"], "members": []}
    if target.exists() or target.is_symlink():
        return {"codes": ["ARCHIVE_ALREADY_EXISTS"], "members": []}
    initial_snapshot, initial_codes = _seal_source_snapshot(
        root, include_manifest=True
    )
    privacy = scan_before_seal(root)
    verified = verify_manifest(root)
    validated_snapshot, validated_codes = _seal_source_snapshot(
        root, include_manifest=True
    )
    pre_codes = [
        *initial_codes,
        *privacy["codes"],
        *verified["codes"],
        *validated_codes,
    ]
    if validated_snapshot != initial_snapshot:
        pre_codes.append("EVIDENCE_CHANGED_DURING_SEAL")
    if pre_codes:
        return {"codes": _dedupe(pre_codes), "members": []}
    entries, parse_codes = _parse_manifest_text((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    if parse_codes:
        return {"codes": parse_codes, "members": []}
    members = [*sorted(entries), MANIFEST_NAME]
    descriptor: int | None = None
    created = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(target, flags, 0o600)
        created = True
        with os.fdopen(descriptor, "wb") as archive_stream:
            descriptor = None
            with tarfile.open(
                fileobj=archive_stream,
                mode="w:gz",
                format=tarfile.PAX_FORMAT,
            ) as bundle:
                for relative in members:
                    path = root / relative
                    info = bundle.gettarinfo(str(path), arcname=relative)
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    with path.open("rb") as stream:
                        bundle.addfile(info, stream)
            archive_stream.flush()
            os.fsync(archive_stream.fileno())
    except (OSError, tarfile.TarError):
        if descriptor is not None:
            os.close(descriptor)
        if created:
            _remove_owned_file(target)
        return {"codes": ["ARCHIVE_BUILD_FAILED"], "members": []}
    post_privacy = scan_before_seal(root)
    post_manifest = verify_manifest(root)
    final_snapshot, final_codes = _seal_source_snapshot(
        root, include_manifest=True
    )
    archive_verification = verify_clean_archive(target)
    post_codes = [
        *post_privacy["codes"],
        *post_manifest["codes"],
        *final_codes,
        *archive_verification["codes"],
    ]
    if final_snapshot != initial_snapshot:
        post_codes.append("EVIDENCE_CHANGED_DURING_SEAL")
    member_digests = archive_verification.get("memberSha256")
    if (
        archive_verification.get("manifestSha256")
        != initial_snapshot.get(MANIFEST_NAME)
    ):
        post_codes.append("ARCHIVE_MANIFEST_BINDING_MISMATCH")
    package_digest = initial_snapshot.get(PACKAGE_RECORD_NAME)
    if package_digest is not None and (
        not isinstance(member_digests, Mapping)
        or member_digests.get(PACKAGE_RECORD_NAME) != package_digest
    ):
        post_codes.append("ARCHIVE_PACKAGE_BINDING_MISMATCH")
    if post_codes:
        _remove_owned_file(target)
        return {"codes": _dedupe(post_codes), "members": []}
    return {
        "codes": [],
        "members": members,
        "sha256": archive_verification.get("archiveSha256"),
    }


def _unsafe_archive_name(name: str) -> bool:
    if "\\" in name:
        return True
    path = PurePosixPath(name)
    return path.is_absolute() or any(part in ("", ".", "..") for part in path.parts)


class _TarFramingValidator:
    """Validate logical tar framing without mistaking zero bytes in payloads for EOF."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.data_bytes_remaining = 0
        self.zero_headers = 0
        self.eof_seen = False
        self.code: str | None = None

    def feed(self, payload: bytes) -> None:
        if self.code is not None:
            return
        self.buffer.extend(payload)
        while len(self.buffer) >= 512 and self.code is None:
            block = bytes(self.buffer[:512])
            del self.buffer[:512]
            if self.eof_seen:
                if any(block):
                    self.code = "ARCHIVE_TRAILING_DATA"
                continue
            if self.data_bytes_remaining:
                used = min(self.data_bytes_remaining, 512)
                if used < 512 and any(block[used:]):
                    self.code = "ARCHIVE_TRAILING_DATA"
                    continue
                self.data_bytes_remaining -= used
                continue
            if block == bytes(512):
                self.zero_headers += 1
                if self.zero_headers == 2:
                    self.eof_seen = True
                continue
            if self.zero_headers:
                self.code = "ARCHIVE_FORMAT_INVALID"
                continue
            if any(block[500:512]):
                self.code = "UNSAFE_ARCHIVE_METADATA"
                continue
            try:
                size = tarfile.nti(block[124:136])
            except (ValueError, OverflowError):
                self.code = "ARCHIVE_FORMAT_INVALID"
                continue
            if not isinstance(size, int) or size < 0:
                self.code = "ARCHIVE_FORMAT_INVALID"
                continue
            self.data_bytes_remaining = size

    def finish(self) -> list[str]:
        if self.code is not None:
            return [self.code]
        if self.eof_seen and self.buffer:
            return [
                "ARCHIVE_TRAILING_DATA"
                if any(self.buffer)
                else "ARCHIVE_FORMAT_INVALID"
            ]
        if (
            self.data_bytes_remaining
            or not self.eof_seen
            or self.zero_headers < 2
        ):
            return ["ARCHIVE_FORMAT_INVALID"]
        return []


def _validate_single_gzip_stream(stream: BinaryIO) -> list[str]:
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    decompressed_bytes = 0
    framing = _TarFramingValidator()
    metadata_codes: list[str] = []
    privacy_tail = ""
    try:
        stream.seek(0)
        header = stream.read(10)
        if len(header) != 10 or header[:3] != b"\x1f\x8b\x08":
            return ["ARCHIVE_FORMAT_INVALID"]
        if header[3] != 0:
            metadata_codes.append("UNSAFE_ARCHIVE_METADATA")
        stream.seek(0)
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            pending = chunk
            while pending:
                output = decoder.decompress(pending, 1024 * 1024)
                decompressed_bytes += len(output)
                if decompressed_bytes > _MAX_ARCHIVE_EXPANDED_BYTES:
                    return _dedupe([*metadata_codes, "ARCHIVE_EXPANSION_LIMIT"])
                decoded = privacy_tail + output.decode("utf-8", errors="ignore")
                if _sensitive_kinds(decoded):
                    metadata_codes.append("PII_OR_SECRET_DETECTED")
                privacy_tail = decoded[-1024:]
                framing.feed(output)
                if framing.code is not None:
                    return _dedupe([*metadata_codes, framing.code])
                pending = decoder.unconsumed_tail
                if decoder.eof:
                    if decoder.unused_data or pending or stream.read(1):
                        return _dedupe([*metadata_codes, "ARCHIVE_TRAILING_DATA"])
                    return _dedupe([*metadata_codes, *framing.finish()])
        if not decoder.eof:
            return _dedupe([*metadata_codes, "ARCHIVE_FORMAT_INVALID"])
    except (OSError, zlib.error):
        return _dedupe([*metadata_codes, "ARCHIVE_FORMAT_INVALID"])
    return metadata_codes


def _tar_metadata_codes(
    global_pax_headers: Mapping[str, str], member: tarfile.TarInfo
) -> list[str]:
    codes: list[str] = []
    metadata_document = {
        "globalPax": dict(global_pax_headers),
        "memberPax": dict(member.pax_headers),
        "uname": member.uname,
        "gname": member.gname,
        "linkname": member.linkname,
    }
    metadata_text = json.dumps(
        metadata_document, sort_keys=True, ensure_ascii=False, allow_nan=False
    )
    if _sensitive_kinds(metadata_text):
        codes.append("PII_OR_SECRET_DETECTED")
    if global_pax_headers:
        codes.append("UNSAFE_ARCHIVE_METADATA")
    for key, value in member.pax_headers.items():
        allowed = (
            (key == "path" and value == member.name)
            or (key == "size" and value == str(member.size))
        )
        if not allowed:
            codes.append("UNSAFE_ARCHIVE_METADATA")
    if (
        member.uid != 0
        or member.gid != 0
        or member.uname != ""
        or member.gname != ""
        or member.mtime != 0
        or member.linkname != ""
    ):
        codes.append("UNSAFE_ARCHIVE_METADATA")
    return _dedupe(codes)


def _file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def verify_clean_archive(archive_path: Path) -> dict[str, object]:
    archive = Path(archive_path)
    codes: list[str] = []
    payloads: dict[str, bytes] = {}
    names: list[str] = []
    archive_sha256: str | None = None
    try:
        metadata = archive.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0:
            raise OSError("unsafe archive")
        if metadata.st_size > _MAX_ARCHIVE_COMPRESSED_BYTES:
            return {"codes": ["ARCHIVE_COMPRESSED_SIZE_LIMIT"], "members": []}
        with archive.open("rb") as source, tempfile.SpooledTemporaryFile(
            max_size=8 * 1024 * 1024, mode="w+b"
        ) as snapshot:
            opened_before = os.fstat(source.fileno())
            if _file_identity(opened_before) != _file_identity(metadata):
                return {"codes": ["ARCHIVE_CHANGED_DURING_VERIFICATION"], "members": []}
            digest = hashlib.sha256()
            copied = 0
            while True:
                chunk = source.read(64 * 1024)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > _MAX_ARCHIVE_COMPRESSED_BYTES:
                    return {"codes": ["ARCHIVE_COMPRESSED_SIZE_LIMIT"], "members": []}
                digest.update(chunk)
                snapshot.write(chunk)
            opened_after_copy = os.fstat(source.fileno())
            if _file_identity(opened_after_copy) != _file_identity(opened_before):
                return {"codes": ["ARCHIVE_CHANGED_DURING_VERIFICATION"], "members": []}
            archive_sha256 = digest.hexdigest()

            gzip_codes = _validate_single_gzip_stream(snapshot)
            fatal_gzip_codes = {
                "ARCHIVE_EXPANSION_LIMIT",
                "ARCHIVE_FORMAT_INVALID",
                "ARCHIVE_TRAILING_DATA",
            }
            if fatal_gzip_codes.intersection(gzip_codes):
                return {
                    "codes": gzip_codes,
                    "members": [],
                    "archiveSha256": archive_sha256,
                }
            codes.extend(gzip_codes)
            snapshot.seek(0)
            with tarfile.open(fileobj=snapshot, mode="r:*") as bundle:
                members = bundle.getmembers()
                if len(members) > _MAX_ARCHIVE_MEMBERS:
                    return {
                        "codes": ["ARCHIVE_MEMBER_COUNT_LIMIT"],
                        "members": [],
                        "archiveSha256": archive_sha256,
                    }
                aggregate_member_bytes = 0
                for member in members:
                    name = member.name
                    codes.extend(_tar_metadata_codes(bundle.pax_headers, member))
                    if name in names:
                        codes.append("DUPLICATE_ARCHIVE_MEMBER")
                    names.append(name)
                    if _unsafe_archive_name(name):
                        codes.append("UNSAFE_ARCHIVE_PATH")
                    if any(part.startswith(".") for part in PurePosixPath(name).parts):
                        codes.append("HIDDEN_ARCHIVE_MEMBER")
                    if name.lower().endswith(_NESTED_ARCHIVE_SUFFIXES):
                        codes.append("NESTED_ARCHIVE")
                    if not member.isfile():
                        codes.append("UNSUPPORTED_ARCHIVE_NODE")
                        continue
                    if member.size <= 0:
                        codes.append("ZERO_BYTE_ARTIFACT")
                        continue
                    if member.size > _MAX_ARCHIVE_MEMBER_BYTES:
                        codes.append("ARCHIVE_MEMBER_TOO_LARGE")
                        continue
                    aggregate_member_bytes += member.size
                    if aggregate_member_bytes > _MAX_ARCHIVE_EXPANDED_BYTES:
                        return {
                            "codes": ["ARCHIVE_EXPANSION_LIMIT"],
                            "members": [],
                            "archiveSha256": archive_sha256,
                        }
                    extracted = bundle.extractfile(member)
                    if extracted is None:
                        codes.append("UNREADABLE_ARCHIVE_MEMBER")
                        continue
                    payload = extracted.read()
                    payloads[name] = payload
                    if name != MANIFEST_NAME and _looks_like_nested_archive(payload):
                        codes.append("NESTED_ARCHIVE")
                    if _sensitive_kinds(
                        name + "\n" + payload.decode("utf-8", errors="ignore")
                    ):
                        codes.append("PII_OR_SECRET_DETECTED")

            opened_after_validation = os.fstat(source.fileno())
            current_metadata = archive.lstat()
            if (
                _file_identity(opened_after_validation) != _file_identity(opened_before)
                or _file_identity(current_metadata) != _file_identity(opened_before)
            ):
                codes.append("ARCHIVE_CHANGED_DURING_VERIFICATION")
    except (OSError, tarfile.TarError):
        return {"codes": ["ARCHIVE_UNREADABLE"], "members": []}

    manifest_payload = payloads.get(MANIFEST_NAME)
    if manifest_payload is None:
        codes.append("MANIFEST_MISSING")
        return {"codes": _dedupe(codes), "members": sorted(set(names))}
    try:
        manifest_text = manifest_payload.decode("utf-8")
    except UnicodeError:
        codes.append("MALFORMED_MANIFEST")
        return {"codes": _dedupe(codes), "members": sorted(set(names))}
    entries, parse_codes = _parse_manifest_text(manifest_text)
    codes.extend(parse_codes)
    expected_members = set(entries) | {MANIFEST_NAME}
    if set(names) != expected_members:
        codes.append("ARCHIVE_INVENTORY_MISMATCH")
    for relative, expected in entries.items():
        payload = payloads.get(relative)
        if payload is None:
            continue
        if hashlib.sha256(payload).hexdigest() != expected:
            codes.append("CHECKSUM_MISMATCH")

    member_digests = {
        name: hashlib.sha256(payload).hexdigest() for name, payload in payloads.items()
    }
    package_payload = payloads.get(PACKAGE_RECORD_NAME)
    if package_payload is not None:
        try:
            package_document = _strict_json_loads(package_payload.decode("utf-8"))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            codes.append("PACKAGE_RECORD_INVALID")
        else:
            if not isinstance(package_document, Mapping):
                codes.append("PACKAGE_RECORD_INVALID")
            else:
                declared_rows: list[object] = []
                for field in ("rawLogs", "evidenceArtifacts"):
                    rows = package_document.get(field)
                    if not isinstance(rows, list):
                        codes.append("PACKAGE_ARTIFACT_BINDING_MISMATCH")
                        continue
                    declared_rows.extend(rows)
                for row in declared_rows:
                    if not isinstance(row, Mapping):
                        codes.append("PACKAGE_ARTIFACT_BINDING_MISMATCH")
                        continue
                    path = row.get("path")
                    digest = row.get("sha256")
                    if (
                        not isinstance(path, str)
                        or not _is_sha256(digest)
                        or entries.get(path) != digest
                        or member_digests.get(path) != digest
                    ):
                        codes.append("PACKAGE_ARTIFACT_BINDING_MISMATCH")
    return {
        "codes": _dedupe(codes),
        "members": sorted(set(names)),
        "memberSha256": member_digests,
        "manifestSha256": member_digests.get(MANIFEST_NAME),
        "archiveSha256": archive_sha256,
    }


def _archive_binding_codes(
    verification: Mapping[str, object],
    *,
    manifest_sha256: str,
    package_sha256: str,
) -> list[str]:
    codes: list[str] = []
    member_digests = verification.get("memberSha256")
    if verification.get("manifestSha256") != manifest_sha256:
        codes.append("ARCHIVE_MANIFEST_BINDING_MISMATCH")
    if (
        not isinstance(member_digests, Mapping)
        or member_digests.get(PACKAGE_RECORD_NAME) != package_sha256
    ):
        codes.append("ARCHIVE_PACKAGE_BINDING_MISMATCH")
    return codes


def render_pr_comment(package: Mapping[str, object], result: Mapping[str, object]) -> str:
    provenance = package.get("provenance") if isinstance(package.get("provenance"), Mapping) else {}
    limitations = package.get("limitations")
    if isinstance(limitations, list) and limitations:
        limitation_text = "; ".join(str(item) for item in limitations)
    else:
        limitation_text = "MISSING"
    return "\n".join(
        (
            "## NYAY-14 Exact-Head QA Evidence",
            "",
            f"- Reviewed head: `{provenance.get('reviewedHead', 'MISSING')}`",
            f"- Evidence archive: `{result.get('archiveLocation', 'MISSING')}`",
            f"- Archive SHA-256: `{result.get('archiveSha256', 'MISSING')}`",
            f"- Manifest SHA-256: `{result.get('manifestSha256', 'MISSING')}`",
            f"- Validated package SHA-256: `{result.get('packageSha256', 'MISSING')}`",
            f"- Limitations: {limitation_text}",
            f"- Verdict: **{result.get('verdict', 'MISSING')}**",
            "",
        )
    )


def validate_pr_comment(
    package: Mapping[str, object],
    result: Mapping[str, object],
    comment: object,
) -> list[str]:
    provenance = package.get("provenance") if isinstance(package.get("provenance"), Mapping) else {}
    required_values = (
        provenance.get("reviewedHead"),
        result.get("archiveLocation"),
        result.get("archiveSha256"),
        result.get("manifestSha256"),
        result.get("packageSha256"),
        result.get("verdict"),
    )
    limitations = package.get("limitations")
    valid = (
        isinstance(comment, str)
        and all(_is_nonempty_string(value) and str(value) in comment for value in required_values)
        and _is_git_sha(provenance.get("reviewedHead"))
        and _is_sha256(result.get("archiveSha256"))
        and _is_sha256(result.get("manifestSha256"))
        and _is_sha256(result.get("packageSha256"))
        and result.get("verdict") in CLASSIFICATIONS
        and isinstance(limitations, list)
        and bool(limitations)
        and "Limitations" in comment
        and comment == render_pr_comment(package, result)
    )
    return [] if valid else ["PR_COMMENT_INVALID"]


def render_guarded_merge_commands(repository: str, pr_number: int, reviewed_head: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must use owner/name form")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise ValueError("PR number must be a positive integer")
    if not _is_git_sha(reviewed_head):
        raise ValueError("reviewed head must be a full lowercase Git SHA")
    return "\n".join(
        (
            "set -euo pipefail",
            f'test "$(gh repo view {repository} --json visibility --jq .visibility)" = "PRIVATE"',
            f'test "$(gh pr view {pr_number} --repo {repository} --json state --jq .state)" = "OPEN"',
            f'test "$(gh pr view {pr_number} --repo {repository} --json isDraft --jq .isDraft)" = "false"',
            f'test "$(gh pr view {pr_number} --repo {repository} --json baseRefName --jq .baseRefName)" = "main"',
            f'test "$(gh pr view {pr_number} --repo {repository} --json headRefOid --jq .headRefOid)" = "{reviewed_head}"',
            f'test "$(gh pr view {pr_number} --repo {repository} --json mergeStateStatus --jq .mergeStateStatus)" = "CLEAN"',
            f"gh pr checks {pr_number} --repo {repository} --required",
            f"gh pr merge {pr_number} --repo {repository} --merge --match-head-commit {reviewed_head}",
            "",
        )
    )


def render_post_merge_validation(repository: str, pr_number: int, reviewed_head: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("repository must use owner/name form")
    if not isinstance(pr_number, int) or isinstance(pr_number, bool) or pr_number <= 0:
        raise ValueError("PR number must be a positive integer")
    if not _is_git_sha(reviewed_head):
        raise ValueError("reviewed head must be a full lowercase Git SHA")
    return "\n".join(
        (
            "set -euo pipefail",
            f'test "$(gh pr view {pr_number} --repo {repository} --json state --jq .state)" = "MERGED"',
            f'NYAY14_MERGE_SHA="$(gh pr view {pr_number} --repo {repository} --json mergeCommit --jq .mergeCommit.oid)"',
            'test -n "$NYAY14_MERGE_SHA"',
            "git fetch origin main",
            f'git merge-base --is-ancestor {reviewed_head} "$NYAY14_MERGE_SHA"',
            f"git merge-base --is-ancestor {reviewed_head} origin/main",
            'git merge-base --is-ancestor "$NYAY14_MERGE_SHA" origin/main',
            'test "$(git rev-list --parents -n 1 "$NYAY14_MERGE_SHA" | wc -w | tr -d " ")" = "3"',
            "",
        )
    )


def validate_protected_checkout(
    *,
    before: object,
    after: object,
    execution_root: Path,
    protected_root: Path,
    operations: Sequence[str],
) -> list[str]:
    codes: list[str] = []
    required_seal_keys = {"head", "entries", "statusSha256", "nulStatusSha256"}
    for seal in (before, after):
        if (
            not isinstance(seal, Mapping)
            or set(seal) != required_seal_keys
            or not _is_git_sha(seal.get("head"))
            or not _is_integer(seal.get("entries"))
            or seal.get("entries", -1) < 0
            or not _is_sha256(seal.get("statusSha256"))
            or not _is_sha256(seal.get("nulStatusSha256"))
        ):
            codes.append("PROTECTED_CHECKOUT_SEAL_INVALID")
    if before != after:
        codes.append("PROTECTED_CHECKOUT_CHANGED")
    if _inside(Path(execution_root), Path(protected_root)):
        codes.append("UNSAFE_EXECUTION_ROOT")
    for operation in operations:
        if not _protected_operation_is_readonly(str(operation)):
            codes.append("PROTECTED_CHECKOUT_MUTATION")
            break
    return _dedupe(codes)


def validate_package(
    package: object,
    *,
    evidence_root: Path,
    authoritative_remote_head: str,
    authoritative_repository: str | None = None,
    authoritative_base: str | None = None,
    authoritative_prospective_merge: str | None = None,
    authoritative_visual_matrix: object = None,
    authoritative_evidence_schema_version: str,
    authoritative_source_archive_sha256: str | None = None,
    authoritative_ticket_type: str | None = None,
    authoritative_contact_sheet_panel_roles: Sequence[str] | None = None,
    contact_sheet_contract: object = None,
    execution_root: Path | None = None,
    protected_root: Path | None = None,
    report_path: Path | None = None,
    archive_path: Path | None = None,
) -> dict[str, object]:
    codes: list[str] = []
    if not isinstance(package, Mapping):
        return {
            "schemaVersion": SCHEMA_VERSION,
            "verdict": "FAIL",
            "codes": ["INVALID_PACKAGE"],
            "mergeAuthorized": False,
        }
    root = Path(evidence_root).resolve(strict=False)
    initial_snapshot, initial_snapshot_codes = _evidence_snapshot(root)
    codes.extend(initial_snapshot_codes)
    declared_schema = package.get("schemaVersion")
    if declared_schema not in SUPPORTED_SCHEMA_VERSIONS:
        codes.append("INVALID_SCHEMA_VERSION")
    required_schema = authoritative_evidence_schema_version
    if required_schema not in SUPPORTED_SCHEMA_VERSIONS:
        codes.append("INVALID_SCHEMA_VERSION")
    if required_schema == FUTURE_SCHEMA_VERSION and declared_schema != FUTURE_SCHEMA_VERSION:
        codes.append("SCHEMA_DOWNGRADE")
    claimed = package.get("claimedVerdict")
    codes.extend(validate_classification(claimed))
    if any(
        value is None
        for value in (
            authoritative_repository,
            authoritative_base,
            authoritative_prospective_merge,
        )
    ):
        codes.append("AUTHORITATIVE_PROVENANCE_REQUIRED")
    provenance_codes = validate_provenance(
        package.get("provenance"),
        authoritative_remote_head,
        authoritative_repository,
        authoritative_base,
        authoritative_prospective_merge,
    )
    codes.extend(provenance_codes)
    # The v2 bump applies to the sealed package envelope. Raw-log producers
    # retain their independently versioned v1 assertion-document format.
    raw_schema = SCHEMA_VERSION
    codes.extend(
        validate_raw_logs(
            package.get("rawLogs"),
            Path(evidence_root),
            raw_schema,
        )
    )
    codes.extend(validate_assertion_groups(package.get("assertionGroups")))
    codes.extend(validate_metric_traceability(package, Path(evidence_root)))
    codes.extend(validate_evidence_artifacts(package.get("evidenceArtifacts"), Path(evidence_root)))
    codes.extend(validate_artifact_references(package))

    visual_rows = package.get("visualComparisons")
    package_approved_rows = package.get("approvedVisualComparisons")
    if not isinstance(authoritative_visual_matrix, list) or not authoritative_visual_matrix:
        codes.append("APPROVED_VISUAL_MATRIX_MISSING")
        approved_rows: object = []
    else:
        approved_rows = authoritative_visual_matrix
        try:
            approved_payload = (
                json.dumps(
                    authoritative_visual_matrix,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError):
            codes.append("APPROVED_VISUAL_MATRIX_INVALID")
        else:
            approved_digest = hashlib.sha256(approved_payload).hexdigest()
            if (
                package_approved_rows != authoritative_visual_matrix
                or package.get("approvedVisualMatrixSha256") != approved_digest
            ):
                codes.append("APPROVED_VISUAL_MATRIX_MISMATCH")
    codes.extend(validate_visual_matrix(visual_rows, approved_rows, Path(evidence_root)))
    provenance = package.get("provenance")
    reviewed_head = provenance.get("reviewedHead") if isinstance(provenance, Mapping) else None
    if isinstance(visual_rows, list) and any(
        not isinstance(row, Mapping) or row.get("testedHead") != reviewed_head
        for row in visual_rows
    ):
        codes.append("VISUAL_HEAD_MISMATCH")
    codes.extend(validate_quality_results(package.get("qualityResults")))
    codes.extend(validate_readbacks(package))
    if (
        declared_schema == FUTURE_SCHEMA_VERSION
        or required_schema == FUTURE_SCHEMA_VERSION
    ):
        if contact_sheet_contract is None:
            try:
                contact_sheet_contract = _strict_json_loads(
                    Path(__file__)
                    .resolve()
                    .with_name("nyay27_contact_sheet_contract.json")
                    .read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, ValueError):
                contact_sheet_contract = None
        if (
            authoritative_source_archive_sha256 is None
            or authoritative_ticket_type is None
            or authoritative_contact_sheet_panel_roles is None
        ):
            codes.append("CONTACT_SHEET_PROVENANCE_MISMATCH")
        codes.extend(
            validate_combined_contact_sheet(
                package,
                Path(evidence_root),
                authoritative_reviewed_head=authoritative_remote_head,
                authoritative_source_archive_sha256=(
                    authoritative_source_archive_sha256 or ""
                ),
                authoritative_ticket_type=authoritative_ticket_type or "",
                authoritative_panel_roles=(
                    authoritative_contact_sheet_panel_roles or ()
                ),
                contract=contact_sheet_contract,
            )
        )
    limitations = package.get("limitations")
    if not isinstance(limitations, list) or not limitations:
        codes.append("LIMITATIONS_MISSING")

    try:
        package_payload = (
            json.dumps(
                package,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError):
        package_payload = b""
        codes.append("INVALID_PACKAGE")
    if package_payload and _sensitive_kinds(package_payload.decode("utf-8")):
        codes.append("PII_OR_SECRET_DETECTED")

    privacy = scan_before_seal(Path(evidence_root))
    codes.extend(str(code) for code in privacy.get("codes", []))

    protected = package.get("protectedCheckout")
    if (
        execution_root is None
        or protected_root is None
        or not isinstance(protected, Mapping)
        or not isinstance(protected.get("operations"), list)
    ):
        codes.append("PROTECTED_CHECKOUT_SEAL_MISSING")
    else:
        codes.extend(
            validate_protected_checkout(
                before=protected.get("before"),
                after=protected.get("after"),
                execution_root=Path(execution_root),
                protected_root=Path(protected_root),
                operations=tuple(str(value) for value in protected["operations"]),
            )
        )
        if _inside(Path(evidence_root), Path(protected_root)):
            codes.append("UNSAFE_EVIDENCE_ROOT")

    report_target = Path(report_path).resolve(strict=False) if report_path is not None else None
    archive_target = Path(archive_path).resolve(strict=False) if archive_path is not None else None
    if report_target is None or archive_target is None:
        codes.append("SEALED_OUTPUT_REQUIRED")
    else:
        if report_target == archive_target:
            codes.append("OUTPUT_PATH_ALIAS")
        if _inside(report_target, root) or _inside(archive_target, root):
            codes.append("UNSAFE_OUTPUT_DESTINATION")
        if protected_root is not None and (
            _inside(report_target, Path(protected_root))
            or _inside(archive_target, Path(protected_root))
        ):
            codes.append("UNSAFE_OUTPUT_DESTINATION")
        if any(path.exists() or path.is_symlink() for path in (report_target, archive_target)):
            codes.append("OUTPUT_ALREADY_EXISTS")
    for owned_name in (MANIFEST_NAME, PACKAGE_RECORD_NAME):
        owned_path = root / owned_name
        if owned_path.exists() or owned_path.is_symlink():
            codes.append("OUTPUT_ALREADY_EXISTS")

    validated_snapshot, validated_snapshot_codes = _evidence_snapshot(root)
    codes.extend(validated_snapshot_codes)
    if validated_snapshot != initial_snapshot:
        codes.append("EVIDENCE_CHANGED_DURING_VALIDATION")

    codes = _dedupe(codes)

    head_changed = "HEAD_CHANGED" in codes
    non_head_codes = [code for code in codes if code != "HEAD_CHANGED"]
    failed = bool(non_head_codes)
    blocked = not failed and bool(package.get("blockedReasons"))
    handoff_only = not failed and not blocked and package.get("handoffOnly") is True
    verdict = classify(
        {
            "headChanged": head_changed,
            "failed": failed,
            "blocked": blocked,
            "handoffOnly": handoff_only,
        }
    )
    if claimed in CLASSIFICATIONS and claimed != verdict:
        codes = _dedupe([*codes, "CLAIMED_VERDICT_MISMATCH"])
        if verdict != "HEAD_CHANGED":
            verdict = "FAIL"
    result: dict[str, object] = {
        "schemaVersion": (
            declared_schema
            if declared_schema in SUPPORTED_SCHEMA_VERSIONS
            else FUTURE_SCHEMA_VERSION
        ),
        "verdict": verdict,
        "codes": codes,
        "mergeAuthorized": False,
    }
    if verdict != "PASS" or claimed != "PASS":
        return result

    assert report_target is not None and archive_target is not None
    package_record = root / PACKAGE_RECORD_NAME
    manifest_path = root / MANIFEST_NAME
    created = (package_record, manifest_path, archive_target, report_target)

    def publication_failure(failure_codes: Iterable[str]) -> dict[str, object]:
        for path in created:
            _remove_owned_file(path)
        result["codes"] = _dedupe(failure_codes)
        result["verdict"] = "FAIL"
        result["mergeAuthorized"] = False
        result.pop("archiveLocation", None)
        result.pop("archiveSha256", None)
        result.pop("manifestSha256", None)
        result.pop("packageSha256", None)
        return result

    try:
        package_record.parent.mkdir(parents=True, exist_ok=True)
        report_target.parent.mkdir(parents=True, exist_ok=True)
        archive_target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return publication_failure(["OUTPUT_DIRECTORY_UNAVAILABLE"])
    if _write_exclusive(package_record, package_payload):
        return publication_failure(["PACKAGE_RECORD_WRITE_FAILED"])
    result["packageSha256"] = _hash_file(package_record)

    manifest_result = generate_manifest(root)
    if manifest_result["codes"]:
        return publication_failure(manifest_result["codes"])
    result["manifestSha256"] = _hash_file(manifest_path)
    post_manifest_snapshot, post_manifest_codes = _evidence_snapshot(root)
    if post_manifest_codes or post_manifest_snapshot != validated_snapshot:
        return publication_failure(
            [*post_manifest_codes, "EVIDENCE_CHANGED_DURING_SEAL"]
        )

    archive_result = build_clean_archive(root, archive_target)
    if archive_result["codes"]:
        return publication_failure(archive_result["codes"])
    verification = verify_clean_archive(archive_target)
    binding_codes = _archive_binding_codes(
        verification,
        manifest_sha256=str(result["manifestSha256"]),
        package_sha256=str(result["packageSha256"]),
    )
    if verification["codes"] or binding_codes:
        return publication_failure([*verification["codes"], *binding_codes])
    result["archiveLocation"] = str(archive_target)
    result["archiveSha256"] = verification.get("archiveSha256")
    result["mergeAuthorized"] = True
    report_payload = (
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    if _write_exclusive(report_target, report_payload):
        return publication_failure(["REPORT_WRITE_FAILED"])
    final_verification = verify_clean_archive(archive_target)
    final_binding_codes = _archive_binding_codes(
        final_verification,
        manifest_sha256=str(result["manifestSha256"]),
        package_sha256=str(result["packageSha256"]),
    )
    final_snapshot, final_snapshot_codes = _evidence_snapshot(root)
    if (
        final_verification["codes"]
        or final_binding_codes
        or final_snapshot_codes
        or final_snapshot != validated_snapshot
        or final_verification.get("archiveSha256") != result["archiveSha256"]
        or _hash_file(package_record) != result["packageSha256"]
        or _hash_file(manifest_path) != result["manifestSha256"]
    ):
        return publication_failure(
            [
                *final_verification["codes"],
                *final_binding_codes,
                *final_snapshot_codes,
                "POST_PUBLICATION_INTEGRITY_FAILED",
            ]
        )
    return result


def _read_json(path: Path) -> object:
    return _strict_json_loads(path.read_text(encoding="utf-8"))


def _emit(result: Mapping[str, object]) -> None:
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


def _exit_for_verdict(verdict: object) -> int:
    return {
        "PASS": 0,
        "FAIL": 1,
        "BLOCKED": 2,
        "HEAD_CHANGED": 3,
        "handoff-only": 4,
    }.get(verdict, 1)


def _classified_failure(*codes: str) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "verdict": "FAIL",
        "codes": _dedupe(codes),
        "mergeAuthorized": False,
    }


def _any_path_alias(paths: Sequence[Path]) -> bool:
    resolved = [path.resolve(strict=False) for path in paths]
    if len(resolved) != len(set(resolved)):
        return True
    for index, left in enumerate(paths):
        for right in paths[index + 1 :]:
            try:
                if left.exists() and right.exists() and os.path.samefile(left, right):
                    return True
            except OSError:
                return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    validate = subcommands.add_parser("validate", help="validate and optionally seal a package")
    validate.add_argument("--package", type=Path, required=True)
    validate.add_argument("--evidence-root", type=Path, required=True)
    validate.add_argument("--authoritative-repository", required=True)
    validate.add_argument("--authoritative-base", required=True)
    validate.add_argument("--authoritative-remote-head", required=True)
    validate.add_argument("--authoritative-prospective-merge", required=True)
    validate.add_argument("--approved-visual-matrix", type=Path, required=True)
    validate.add_argument(
        "--authoritative-evidence-schema-version",
        choices=SUPPORTED_SCHEMA_VERSIONS,
        default=FUTURE_SCHEMA_VERSION,
        help="authoritative package generation; defaults to the enforced v2 boundary",
    )
    validate.add_argument(
        "--authoritative-source-archive-sha256",
        help="digest of the independently sealed source archive embedded by the sheet",
    )
    validate.add_argument(
        "--authoritative-ticket-type",
        choices=("ui", "non-ui"),
    )
    validate.add_argument(
        "--authoritative-contact-sheet-panel-role",
        action="append",
        default=[],
        help="repeat in the approved panel order; package declarations are not authority",
    )
    validate.add_argument(
        "--historical-v1-package-sha256",
        help="exact external file seal required only for explicit v1 re-validation",
    )
    validate.add_argument("--protected-root", type=Path, required=True)
    validate.add_argument("--execution-root", type=Path, default=Path.cwd())
    validate.add_argument("--report", type=Path, required=True)
    validate.add_argument("--archive", type=Path, required=True)

    manifest = subcommands.add_parser("manifest", help="generate a complete SHA-256 manifest")
    manifest.add_argument("--evidence-root", type=Path, required=True)
    manifest.add_argument("--protected-root", type=Path, required=True)
    verify = subcommands.add_parser("verify-manifest", help="verify manifest and exact inventory")
    verify.add_argument("--evidence-root", type=Path, required=True)
    archive = subcommands.add_parser("build-archive", help="build a clean manifest-bound tar archive")
    archive.add_argument("--evidence-root", type=Path, required=True)
    archive.add_argument("--archive", type=Path, required=True)
    archive.add_argument("--protected-root", type=Path, required=True)
    verify_archive = subcommands.add_parser("verify-archive", help="verify a clean archive")
    verify_archive.add_argument("--archive", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            input_and_outputs = (
                args.package,
                args.approved_visual_matrix,
                args.report,
                args.archive,
            )
            if _any_path_alias(input_and_outputs):
                result = _classified_failure("OUTPUT_PATH_ALIAS")
                _emit(result)
                return 1
            protected_root = args.protected_root.resolve(strict=False)
            execution_root = args.execution_root.resolve(strict=False)
            evidence_root = args.evidence_root.resolve(strict=False)
            if (
                _inside(execution_root, protected_root)
                or _inside(evidence_root, protected_root)
                or any(_inside(path, protected_root) for path in input_and_outputs)
            ):
                result = _classified_failure("UNSAFE_EXECUTION_ROOT")
                _emit(result)
                return 1
            package_bytes = args.package.read_bytes()
            package_document = _strict_json_loads(package_bytes.decode("utf-8"))
            package_file_sha256 = hashlib.sha256(package_bytes).hexdigest()
            if args.authoritative_evidence_schema_version == SCHEMA_VERSION and (
                not _is_sha256(args.historical_v1_package_sha256)
                or args.historical_v1_package_sha256 != package_file_sha256
                or package_file_sha256 not in HISTORICAL_V1_PACKAGE_SHA256
            ):
                result = _classified_failure("HISTORICAL_SEAL_MISMATCH")
                _emit(result)
                return 1
            approved_document = _read_json(args.approved_visual_matrix)
            if isinstance(approved_document, Mapping):
                approved_matrix = approved_document.get("approvedVisualComparisons")
            else:
                approved_matrix = approved_document
            result = validate_package(
                package_document,
                evidence_root=args.evidence_root,
                authoritative_repository=args.authoritative_repository,
                authoritative_base=args.authoritative_base,
                authoritative_remote_head=args.authoritative_remote_head,
                authoritative_prospective_merge=args.authoritative_prospective_merge,
                authoritative_visual_matrix=approved_matrix,
                authoritative_evidence_schema_version=(
                    args.authoritative_evidence_schema_version
                ),
                authoritative_source_archive_sha256=(
                    args.authoritative_source_archive_sha256
                ),
                authoritative_ticket_type=args.authoritative_ticket_type,
                authoritative_contact_sheet_panel_roles=(
                    tuple(args.authoritative_contact_sheet_panel_role)
                ),
                execution_root=args.execution_root,
                protected_root=args.protected_root,
                report_path=args.report,
                archive_path=args.archive,
            )
            _emit(result)
            return _exit_for_verdict(result.get("verdict"))
        if args.command == "manifest":
            if _inside(args.evidence_root, args.protected_root):
                result = {"codes": ["UNSAFE_EVIDENCE_ROOT"]}
            else:
                result = generate_manifest(args.evidence_root)
        elif args.command == "verify-manifest":
            result = verify_manifest(args.evidence_root)
        elif args.command == "build-archive":
            if _inside(args.evidence_root, args.protected_root) or _inside(
                args.archive, args.protected_root
            ):
                result = {"codes": ["UNSAFE_OUTPUT_DESTINATION"]}
            else:
                result = build_clean_archive(args.evidence_root, args.archive)
        else:
            result = verify_clean_archive(args.archive)
    except Exception:
        if args.command == "validate":
            result = _classified_failure("INPUT_UNREADABLE")
        else:
            result = {"codes": ["INPUT_UNREADABLE"]}
    _emit(result)
    return 1 if result.get("codes") else 0


if __name__ == "__main__":
    raise SystemExit(main())
