#!/usr/bin/env python3
"""Audit and deterministically replay the NYAY-19 Codex patch ledger.

Raw ledgers remain local and are supplied as ``--ledger ALIAS=PATH`` bindings.
Output is deliberately aggregate: it never emits a ledger path, diff, message,
or source-thread identifier.  Replay always materializes the exact parent in a
new temporary repository; it never writes to the repository passed by the user.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, NoReturn


HERE = Path(__file__).resolve().parent
DEFAULT_SPEC = HERE / "specs" / "nyay19-reconstruction-v1.json"


class AuditError(RuntimeError):
    """A sanitized, release-blocking provenance error."""

    def __init__(self, code: str, *, alias: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.alias = alias


def _fail(code: str, *, alias: str | None = None) -> NoReturn:
    raise AuditError(code, alias=alias)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _load_spec(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("SPEC_UNREADABLE")
    if not isinstance(value, dict) or value.get("version") != 1:
        _fail("SPEC_VERSION_INVALID")
    return value


def _parse_bindings(
    values: Sequence[str], aliases: Sequence[str]
) -> dict[str, Path]:
    bindings: dict[str, Path] = {}
    for value in values:
        alias, separator, raw_path = value.partition("=")
        if not separator or alias not in aliases or alias in bindings:
            _fail("LEDGER_BINDING_INVALID")
        candidate = Path(raw_path).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
            info = resolved.stat()
        except OSError:
            _fail("LEDGER_UNAVAILABLE", alias=alias)
        if candidate.is_symlink() or not stat.S_ISREG(info.st_mode):
            _fail("LEDGER_FILE_TYPE_INVALID", alias=alias)
        bindings[alias] = resolved
    if set(bindings) != set(aliases):
        _fail("LEDGER_BINDINGS_INCOMPLETE")
    inodes = {(path.stat().st_dev, path.stat().st_ino) for path in bindings.values()}
    if len(inodes) != len(bindings):
        _fail("LEDGER_BINDINGS_DUPLICATE_FILE")
    return bindings


def _successful_patch(record: Any) -> Mapping[str, Any] | None:
    if not isinstance(record, Mapping) or record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    if payload.get("type") != "patch_apply_end" or payload.get("success") is not True:
        return None
    if not isinstance(payload.get("call_id"), str):
        return None
    if not isinstance(payload.get("changes"), Mapping):
        return None
    return payload


_TOOL_STATUS_CATEGORIES = (
    "completed",
    "failed",
    "error",
    "aborted",
    "cancelled",
    "in_progress",
    "missing",
    "other",
)


def _tool_status_category(raw_status: Any) -> str:
    if raw_status is None:
        return "missing"
    if isinstance(raw_status, str) and raw_status in _TOOL_STATUS_CATEGORIES[:-2]:
        return raw_status
    return "other"


def _dispatched_tool_call(record: Any) -> Mapping[str, Any] | None:
    if not isinstance(record, Mapping) or record.get("type") != "response_item":
        return None
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        return None
    if (
        payload.get("type") != "custom_tool_call"
        or payload.get("name") != "exec"
        or not isinstance(payload.get("call_id"), str)
        or not isinstance(payload.get("input"), str)
    ):
        return None
    return payload


def _relative_source_path(raw: str, source_root: str) -> str | None:
    if not isinstance(raw, str) or not raw.startswith(source_root):
        return None
    relative = raw[len(source_root) :]
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
        or "\n" in relative
        or "\r" in relative
        or "\t" in relative
    ):
        _fail("SOURCE_PATH_INVALID")
    return path.as_posix()


def _event_signature(changes: Any) -> str:
    # Inherited transcript copies may acquire a new envelope timestamp.  The
    # successful patch outcome is the call ID plus its change body; timestamp
    # is ordering metadata and the earliest observed value wins below.
    return hashlib.sha256(_canonical_json(changes)).hexdigest()


def collect(
    spec: Mapping[str, Any], bindings: Mapping[str, Path]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Globally deduplicate successful calls, then select the strict window/root."""

    aliases = tuple(spec["source_aliases"])
    seen: dict[str, str] = {}
    by_call: dict[str, dict[str, Any]] = {}
    unique_candidates: list[dict[str, Any]] = []
    source_files: dict[str, dict[str, Any]] = {}

    for alias in aliases:
        digest = hashlib.sha256()
        successful_records = 0
        try:
            stream = bindings[alias].open("rb")
        except OSError:
            _fail("LEDGER_UNAVAILABLE", alias=alias)
        with stream:
            for line_number, raw_line in enumerate(stream, start=1):
                digest.update(raw_line)
                try:
                    record = json.loads(raw_line)
                except (UnicodeError, json.JSONDecodeError):
                    _fail("LEDGER_JSON_INVALID", alias=alias)
                payload = _successful_patch(record)
                if payload is None:
                    continue
                successful_records += 1
                call_id = payload["call_id"]
                timestamp = record.get("timestamp")
                changes = payload["changes"]
                signature = _event_signature(changes)
                previous = seen.get(call_id)
                if previous is not None:
                    if previous != signature:
                        _fail("CONFLICTING_DUPLICATE_CALL")
                    existing = by_call[call_id]
                    if isinstance(timestamp, str) and (
                        not isinstance(existing["timestamp"], str)
                        or timestamp < existing["timestamp"]
                    ):
                        existing["timestamp"] = timestamp
                    continue
                seen[call_id] = signature
                event = {
                    "timestamp": timestamp,
                    "call_id": call_id,
                    "owner": alias,
                    "changes": changes,
                    "line": line_number,
                }
                by_call[call_id] = event
                unique_candidates.append(event)
        source_files[alias] = {
            "sha256": digest.hexdigest(),
            "successful_records": successful_records,
        }

    after = spec["window"]["after"]
    through = spec["window"]["through"]
    source_root = spec["source_root"]
    selected: list[dict[str, Any]] = []
    non_root_events = 0
    mixed_root_events = 0

    for event in unique_candidates:
        timestamp = event["timestamp"]
        if not isinstance(timestamp, str) or not (after < timestamp <= through):
            continue
        rooted: dict[str, Any] = {}
        non_root = 0
        for raw_path, change in event["changes"].items():
            relative = _relative_source_path(raw_path, source_root)
            if relative is None:
                non_root += 1
            else:
                rooted[relative] = change
        if rooted and non_root:
            mixed_root_events += 1
            continue
        if non_root and not rooted:
            non_root_events += 1
            continue
        if not rooted:
            continue
        selected.append({**event, "changes": rooted})

    selected.sort(key=lambda item: (item["timestamp"], item["call_id"]))
    summary = _summarize(spec, selected)
    summary["conflicting_duplicates"] = 0
    summary["non_root_events"] = non_root_events
    summary["mixed_root_events"] = mixed_root_events
    summary["source_files"] = source_files
    summary["globally_unique_successful_calls"] = len(seen)
    _validate_summary(spec, summary)
    expected_hashes = spec.get("expected_source_sha256")
    if not isinstance(expected_hashes, Mapping) or set(expected_hashes) != set(aliases):
        _fail("SOURCE_HASH_SPEC_INVALID")
    for alias, expected_hash in expected_hashes.items():
        if source_files[alias]["sha256"] != expected_hash:
            _fail("SOURCE_HASH_MISMATCH", alias=alias)
    return selected, summary


_REPO_STATE_MUTATOR = re.compile(
    r"(?<![\w-])git\s+"
    r"(?:add|am|apply|checkout|clean|commit|merge|mv|rebase|reset|restore|rm|switch)\b",
    re.IGNORECASE,
)
_FILE_MUTATOR = re.compile(
    r"(?:"
    r"(?<![\w-])(?:cp|mv|rm|mkdir|touch|tee)\s+"
    r"|(?<![\w-])(?:sed|perl)\s+-[a-z]*i[a-z]*(?:\s|$)"
    r"|\.write_(?:text|bytes)\s*\("
    r"|shutil\.(?:copy|copy2|copyfile|move)\s*\("
    r")",
    re.IGNORECASE,
)


def audit_non_apply_mutators(
    spec: Mapping[str, Any], bindings: Mapping[str, Path]
) -> dict[str, Any]:
    """Return a path-free aggregate of command-capable, non-patch envelopes.

    The exact command bodies remain private. Their hashes bind this aggregate
    to the pinned ledgers so a separate human review cannot silently drift to
    another command corpus.
    """

    aliases = tuple(spec["source_aliases"])
    seen: dict[str, str] = {}
    by_call: dict[str, dict[str, Any]] = {}
    unique: list[dict[str, Any]] = []
    for alias in aliases:
        try:
            stream = bindings[alias].open("rb")
        except OSError:
            _fail("LEDGER_UNAVAILABLE", alias=alias)
        with stream:
            for line_number, raw_line in enumerate(stream, start=1):
                try:
                    record = json.loads(raw_line)
                except (UnicodeError, json.JSONDecodeError):
                    _fail("LEDGER_JSON_INVALID", alias=alias)
                payload = _dispatched_tool_call(record)
                if payload is None:
                    continue
                call_id = payload["call_id"]
                body = payload["input"]
                raw_status = payload.get("status")
                status_category = _tool_status_category(raw_status)
                status_hash = hashlib.sha256(
                    _canonical_json(raw_status)
                ).hexdigest()
                signature = hashlib.sha256(
                    _canonical_json(
                        {
                            "name": payload["name"],
                            "input": body,
                            "status": raw_status,
                        }
                    )
                ).hexdigest()
                previous = seen.get(call_id)
                if previous is not None:
                    if previous != signature:
                        _fail("CONFLICTING_DUPLICATE_TOOL_CALL")
                    existing = by_call[call_id]
                    timestamp = record.get("timestamp")
                    if isinstance(timestamp, str) and (
                        not isinstance(existing["timestamp"], str)
                        or timestamp < existing["timestamp"]
                    ):
                        existing["timestamp"] = timestamp
                    continue
                seen[call_id] = signature
                event = {
                    "timestamp": record.get("timestamp"),
                    "call_id": call_id,
                    "owner": alias,
                    "body": body,
                    "status_category": status_category,
                    "status_sha256": status_hash,
                    "line": line_number,
                }
                by_call[call_id] = event
                unique.append(event)

    after = spec["window"]["after"]
    through = spec["window"]["through"]
    selected = [
        event
        for event in unique
        if isinstance(event["timestamp"], str)
        and after < event["timestamp"] <= through
        and (
            "tools.exec_command(" in event["body"]
            or "tools.write_stdin(" in event["body"]
        )
    ]
    selected.sort(key=lambda item: (item["timestamp"], item["call_id"]))

    per_source = {
        alias: {
            "command_envelopes": 0,
            "exec_command_invocations": 0,
            "write_stdin_invocations": 0,
            "source_scoped_envelopes": 0,
            "explicit_repo_state_mutator_envelopes": 0,
            "explicit_file_mutator_envelopes": 0,
        }
        for alias in aliases
    }
    source_root = str(spec["source_root"]).rstrip("/")
    command_stream = hashlib.sha256()
    source_scoped = 0
    interactive = 0
    repo_mutators = 0
    file_mutators = 0
    exec_invocations = 0
    write_invocations = 0
    status_categories = {
        category: 0 for category in _TOOL_STATUS_CATEGORIES
    }
    for event in selected:
        owner = event["owner"]
        body = event["body"]
        exec_count = body.count("tools.exec_command(")
        write_count = body.count("tools.write_stdin(")
        is_source_scoped = source_root in body
        is_repo_mutator = bool(_REPO_STATE_MUTATOR.search(body))
        is_file_mutator = bool(_FILE_MUTATOR.search(body))
        body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
        command_stream.update(
            _canonical_json(
                {
                    "timestamp": event["timestamp"],
                    "call_id": event["call_id"],
                    "owner": owner,
                    "body_sha256": body_hash,
                    "status_category": event["status_category"],
                    "status_sha256": event["status_sha256"],
                }
            )
        )
        command_stream.update(b"\n")

        exec_invocations += exec_count
        write_invocations += write_count
        source_scoped += int(is_source_scoped)
        interactive += int(write_count > 0)
        repo_mutators += int(is_repo_mutator)
        file_mutators += int(is_file_mutator)
        status_categories[event["status_category"]] += 1
        counts = per_source[owner]
        counts["command_envelopes"] += 1
        counts["exec_command_invocations"] += exec_count
        counts["write_stdin_invocations"] += write_count
        counts["source_scoped_envelopes"] += int(is_source_scoped)
        counts["explicit_repo_state_mutator_envelopes"] += int(
            is_repo_mutator
        )
        counts["explicit_file_mutator_envelopes"] += int(is_file_mutator)

    return {
        "command_capable_envelopes": len(selected),
        "exec_command_invocations": exec_invocations,
        "write_stdin_invocations": write_invocations,
        "interactive_envelopes": interactive,
        "source_scoped_envelopes": source_scoped,
        "explicit_repo_state_mutator_envelopes": repo_mutators,
        "explicit_file_mutator_envelopes": file_mutators,
        "status_categories": status_categories,
        "command_stream_sha256": command_stream.hexdigest(),
        "conflicting_duplicates": 0,
        "per_source": per_source,
    }


def _validate_non_apply_summary(
    spec: Mapping[str, Any], summary: Mapping[str, Any]
) -> None:
    expected = spec.get("expected_non_apply_audit")
    if not isinstance(expected, Mapping):
        _fail("NON_APPLY_AUDIT_SPEC_INVALID")
    for key, expected_value in expected.items():
        if summary.get(key) != expected_value:
            _fail("NON_APPLY_AUDIT_MISMATCH")
    attestation = spec.get("non_apply_review_attestation")
    if not isinstance(attestation, Mapping):
        _fail("NON_APPLY_ATTESTATION_INVALID")
    linked_fields = (
        "command_stream_sha256",
        "explicit_repo_state_mutator_envelopes",
        "explicit_file_mutator_envelopes",
    )
    if any(
        attestation.get(key) != summary.get(key) for key in linked_fields
    ):
        _fail("NON_APPLY_ATTESTATION_MISMATCH")
    if attestation.get("source_tree_content_mutator_envelopes") != 0:
        _fail("NON_APPLY_ATTESTATION_INVALID")


def _summarize(
    spec: Mapping[str, Any], events: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    per_source = {
        alias: {"events": 0, "changes": 0}
        for alias in spec["source_aliases"]
    }
    types: Counter[str] = Counter()
    paths: set[str] = set()
    moves = 0
    stream_digest = hashlib.sha256()
    for event in events:
        owner = event["owner"]
        per_source[owner]["events"] += 1
        per_source[owner]["changes"] += len(event["changes"])
        normalized_changes: dict[str, Any] = {}
        for path, raw_change in event["changes"].items():
            if not isinstance(raw_change, Mapping):
                _fail("CHANGE_BODY_INVALID")
            change = dict(raw_change)
            change_type = change.get("type")
            if change_type not in {"add", "update", "delete"}:
                _fail("CHANGE_TYPE_INVALID")
            types[change_type] += 1
            paths.add(path)
            move_path = change.get("move_path")
            if move_path is not None:
                if _relative_source_path(move_path, spec["source_root"]) is None:
                    _fail("MOVE_PATH_INVALID")
                moves += 1
            normalized_changes[path] = change
        stream_digest.update(
            _canonical_json(
                {
                    "timestamp": event["timestamp"],
                    "call_id": event["call_id"],
                    "changes": normalized_changes,
                }
            )
        )
        stream_digest.update(b"\n")

    canonical = set(spec["canonical_aliases"])
    supplemental = set(spec["supplemental_aliases"])
    return {
        "events": len(events),
        "changes": sum(len(event["changes"]) for event in events),
        "paths": len(paths),
        "adds": types["add"],
        "updates": types["update"],
        "deletes": types["delete"],
        "moves": moves,
        "canonical_events": sum(per_source[key]["events"] for key in canonical),
        "canonical_changes": sum(per_source[key]["changes"] for key in canonical),
        "supplemental_events": sum(
            per_source[key]["events"] for key in supplemental
        ),
        "supplemental_changes": sum(
            per_source[key]["changes"] for key in supplemental
        ),
        "first": (
            {"timestamp": events[0]["timestamp"], "call_id": events[0]["call_id"]}
            if events
            else None
        ),
        "last": (
            {"timestamp": events[-1]["timestamp"], "call_id": events[-1]["call_id"]}
            if events
            else None
        ),
        "per_source": per_source,
        "selected_stream_sha256": stream_digest.hexdigest(),
    }


def _validate_summary(spec: Mapping[str, Any], summary: Mapping[str, Any]) -> None:
    expected = spec["expected"]
    for key, expected_value in expected.items():
        if key in {"first", "last"}:
            if summary.get(key) != expected_value:
                _fail("LEDGER_BOUNDARY_MISMATCH")
        elif summary.get(key) != expected_value:
            _fail("LEDGER_COUNT_MISMATCH")
    for alias, expected_counts in spec["expected_per_source"].items():
        actual = summary["per_source"].get(alias, {})
        if any(actual.get(key) != value for key, value in expected_counts.items()):
            _fail("LEDGER_SOURCE_SPLIT_MISMATCH", alias=alias)


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    input_bytes: bytes | None = None,
    error_code: str = "REPLAY_COMMAND_FAILED",
) -> str:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        _fail("SUBPROCESS_UNAVAILABLE")
    if completed.returncode != 0:
        _fail(error_code)
    return completed.stdout.decode("utf-8", errors="strict").strip()


def _validate_reconstructed_commit(
    replay_spec: Mapping[str, Any], repo: Path
) -> dict[str, str]:
    """Bind the reconstructed tree proof to its local single-parent commit."""

    reconstructed_commit = replay_spec["reconstructed_commit"]
    resolved_commit = _run(
        [
            "git",
            "rev-parse",
            "--verify",
            f"{reconstructed_commit}^{{commit}}",
        ],
        cwd=repo,
        error_code="RECONSTRUCTED_COMMIT_UNAVAILABLE",
    )
    if resolved_commit != reconstructed_commit:
        _fail("RECONSTRUCTED_COMMIT_UNAVAILABLE")

    ancestry = _run(
        ["git", "rev-list", "--parents", "-n", "1", reconstructed_commit],
        cwd=repo,
        error_code="RECONSTRUCTED_COMMIT_UNAVAILABLE",
    ).split()
    if (
        len(ancestry) != 2
        or ancestry[0] != reconstructed_commit
        or ancestry[1] != replay_spec["parent_commit"]
    ):
        _fail("RECONSTRUCTED_COMMIT_PARENT_MISMATCH")

    reconstructed_tree = _run(
        ["git", "rev-parse", f"{reconstructed_commit}^{{tree}}"],
        cwd=repo,
        error_code="RECONSTRUCTED_COMMIT_UNAVAILABLE",
    )
    if reconstructed_tree != replay_spec["reconstructed_tree"]:
        _fail("RECONSTRUCTED_COMMIT_TREE_MISMATCH")

    subject = _run(
        ["git", "show", "-s", "--format=%s", reconstructed_commit],
        cwd=repo,
        error_code="RECONSTRUCTED_COMMIT_UNAVAILABLE",
    )
    if subject != replay_spec["subject"]:
        _fail("RECONSTRUCTED_COMMIT_SUBJECT_MISMATCH")

    return {
        "reconstructed_commit": reconstructed_commit,
        "reconstructed_tree": reconstructed_tree,
        "subject": subject,
    }


def _patch_for_change(path: str, change: Mapping[str, Any]) -> bytes:
    change_type = change.get("type")
    if change_type == "delete":
        _fail("DELETE_REPLAY_UNSUPPORTED")
    if change_type == "add":
        content = change.get("content")
        if not isinstance(content, str) or not content:
            _fail("ADD_CONTENT_INVALID")
        lines = content.splitlines(keepends=True)
        body = "".join("+" + line for line in lines)
        if lines and not lines[-1].endswith(("\n", "\r")):
            body += "\n\\ No newline at end of file\n"
        patch = (
            f"diff --git a/{path} b/{path}\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            f"+++ b/{path}\n"
            f"@@ -0,0 +1,{len(lines)} @@\n"
            f"{body}"
        )
        return patch.encode("utf-8")
    unified = change.get("unified_diff")
    if not isinstance(unified, str) or not unified.startswith("@@"):
        _fail("UNIFIED_DIFF_INVALID")
    patch = (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"{unified}"
    )
    return patch.encode("utf-8")


def replay(
    spec: Mapping[str, Any], events: Sequence[Mapping[str, Any]], repo: Path
) -> dict[str, Any]:
    """Replay into a new temporary Git repository and return aggregate proof."""

    replay_spec = spec["replay"]
    reconstructed = _validate_reconstructed_commit(replay_spec, repo)
    parent_commit = replay_spec["parent_commit"]
    source_parent_tree = _run(
        ["git", "rev-parse", f"{parent_commit}^{{tree}}"], cwd=repo
    )
    if source_parent_tree != replay_spec["parent_tree"]:
        _fail("PARENT_TREE_MISMATCH")

    with tempfile.TemporaryDirectory(prefix="nyay19-ledger-replay-") as raw_temp:
        workspace = Path(raw_temp)
        _run(["git", "init", "-q"], cwd=workspace)
        _run(["git", "config", "core.autocrlf", "false"], cwd=workspace)
        _run(["git", "config", "core.filemode", "true"], cwd=workspace)
        _run(
            [
                "git",
                "fetch",
                "--quiet",
                "--no-tags",
                "--no-write-fetch-head",
                str(repo),
                parent_commit,
            ],
            cwd=workspace,
        )
        _run(["git", "read-tree", parent_commit], cwd=workspace)
        _run(["git", "checkout-index", "-a", "-f"], cwd=workspace)
        materialized_parent_tree = _run(["git", "write-tree"], cwd=workspace)
        if materialized_parent_tree != replay_spec["parent_tree"]:
            _fail("MATERIALIZED_PARENT_TREE_MISMATCH")

        for event in events:
            for path, change in event["changes"].items():
                patch = _patch_for_change(path, change)
                _run(
                    [
                        "git",
                        "apply",
                        "--unidiff-zero",
                        "--whitespace=nowarn",
                        "-",
                    ],
                    cwd=workspace,
                    input_bytes=patch,
                )
                move_path = change.get("move_path")
                if move_path is not None:
                    destination = _relative_source_path(move_path, spec["source_root"])
                    if destination is None:
                        _fail("MOVE_PATH_INVALID")
                    source_file = workspace / path
                    destination_file = workspace / destination
                    if not source_file.exists() or destination_file.exists():
                        _fail("MOVE_COLLISION")
                    destination_file.parent.mkdir(parents=True, exist_ok=True)
                    source_file.rename(destination_file)

        _run(["git", "add", "-A"], cwd=workspace)
        reconstructed_tree = _run(["git", "write-tree"], cwd=workspace)
        if reconstructed_tree != replay_spec["reconstructed_tree"]:
            _fail("RECONSTRUCTED_TREE_MISMATCH")
        names = _run(
            [
                "git",
                "diff",
                "--name-only",
                materialized_parent_tree,
                reconstructed_tree,
            ],
            cwd=workspace,
        ).splitlines()
        numstat = _run(
            [
                "git",
                "diff",
                "--numstat",
                materialized_parent_tree,
                reconstructed_tree,
            ],
            cwd=workspace,
        ).splitlines()
        insertions = 0
        deletions = 0
        for line in numstat:
            added, removed, _path = line.split("\t", 2)
            if not added.isdecimal() or not removed.isdecimal():
                _fail("BINARY_DELTA_UNSUPPORTED")
            insertions += int(added)
            deletions += int(removed)
        summary_lines = _run(
            [
                "git",
                "diff",
                "--summary",
                materialized_parent_tree,
                reconstructed_tree,
            ],
            cwd=workspace,
        ).splitlines()
        creates = sum(" create mode 100644 " in f" {line} " for line in summary_lines)
        _run(
            [
                "git",
                "diff",
                "--check",
                materialized_parent_tree,
                reconstructed_tree,
            ],
            cwd=workspace,
        )
        db_gate = workspace / "backend" / "scripts" / "db_gate.sh"
        try:
            db_gate_hash = hashlib.sha256(db_gate.read_bytes()).hexdigest()
        except OSError:
            _fail("DB_GATE_UNREADABLE")

    actual = {
        "parent_commit": parent_commit,
        "parent_tree": materialized_parent_tree,
        "reconstructed_commit": reconstructed["reconstructed_commit"],
        "reconstructed_tree": reconstructed_tree,
        "subject": reconstructed["subject"],
        "files": len(names),
        "insertions": insertions,
        "deletions": deletions,
        "create_mode_100644": creates,
        "db_gate_sha256": db_gate_hash,
    }
    for key, value in actual.items():
        if replay_spec.get(key) != value:
            _fail("REPLAY_ORACLE_MISMATCH")
    return actual


def _public_report(
    summary: Mapping[str, Any],
    replay_result: Mapping[str, Any] | None,
    non_apply_result: Mapping[str, Any] | None = None,
    non_apply_attestation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ledger = {
        key: summary[key]
        for key in (
            "events",
            "changes",
            "paths",
            "adds",
            "updates",
            "deletes",
            "moves",
            "canonical_events",
            "canonical_changes",
            "supplemental_events",
            "supplemental_changes",
            "conflicting_duplicates",
            "non_root_events",
            "mixed_root_events",
            "first",
            "last",
            "per_source",
            "selected_stream_sha256",
        )
    }
    source_files = {
        alias: {
            "sha256": values["sha256"],
            "successful_records": values["successful_records"],
        }
        for alias, values in summary["source_files"].items()
    }
    return {
        "status": "PASS",
        "ledger_reconciliation": ledger,
        "source_files": source_files,
        "replay": replay_result,
        "non_apply_mutator_audit": non_apply_result,
        "non_apply_review_attestation": non_apply_attestation,
        "claim_boundary": {
            "original_full_sha": "UNKNOWN_NOT_CLAIMED",
            "original_tree": "UNKNOWN_NOT_CLAIMED",
            "original_author_committer_metadata": "UNKNOWN_NOT_CLAIMED",
            "patch_apply_scope": (
                "COMPLETE_FOR_PINNED_LEDGER_CORPUS_WINDOW_AND_SOURCE_ROOT"
            ),
            "non_apply_scope": (
                "PINNED_COMMAND_CORPUS_AGGREGATE_PLUS_REVIEW_ATTESTATION"
                if non_apply_result is not None
                else "NOT_RUN"
            ),
        },
    }


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    parent = path.parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=parent
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(report, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary, path)
    except OSError:
        _fail("REPORT_WRITE_FAILED")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument(
        "--ledger",
        action="append",
        default=[],
        metavar="ALIAS=PATH",
        help="Bind one required source alias to a local JSONL ledger",
    )
    parser.add_argument(
        "--replay-repo",
        type=Path,
        help="Read Git objects here; replay still occurs only in a new temp repo",
    )
    parser.add_argument(
        "--audit-non-apply-mutators",
        action="store_true",
        help=(
            "Reconcile the aggregate command-capable corpus and its separate "
            "non-apply mutator review attestation"
        ),
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)
    try:
        spec = _load_spec(arguments.spec)
        bindings = _parse_bindings(arguments.ledger, spec["source_aliases"])
        events, summary = collect(spec, bindings)
        replay_result = None
        if arguments.replay_repo is not None:
            replay_result = replay(
                spec,
                events,
                arguments.replay_repo.resolve(strict=True),
            )
        non_apply_result = None
        non_apply_attestation = None
        if arguments.audit_non_apply_mutators:
            non_apply_result = audit_non_apply_mutators(spec, bindings)
            _validate_non_apply_summary(spec, non_apply_result)
            non_apply_attestation = spec["non_apply_review_attestation"]
        report = _public_report(
            summary,
            replay_result,
            non_apply_result,
            non_apply_attestation,
        )
        if arguments.output is not None:
            _write_report(arguments.output, report)
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 0
    except AuditError as error:
        report: dict[str, Any] = {"status": "FAIL", "error": error.code}
        if error.alias is not None:
            report["source_alias"] = error.alias
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return 1
    except (KeyError, TypeError, ValueError):
        print('{"error":"SPEC_SHAPE_INVALID","status":"FAIL"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
