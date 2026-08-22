"""Synthetic contract tests for the durable NYAY-19 ledger auditor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.provenance.nyay19_replay_audit import (
    AuditError,
    _public_report,
    audit_non_apply_mutators,
    collect,
    replay,
)


ROOT = "/recorded/root/"


def _event(timestamp: str, call_id: str, changes: dict) -> dict:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "patch_apply_end",
            "call_id": call_id,
            "success": True,
            "changes": changes,
        },
    }


def _change(path: str, *, kind: str = "update") -> dict[str, dict]:
    change = {
        "type": kind,
        "move_path": None,
    }
    if kind == "add":
        change["content"] = "created\n"
    else:
        change["unified_diff"] = "@@ -1 +1 @@\n-old\n+new\n"
    return {path: change}


def _tool_event(
    timestamp: str,
    call_id: str,
    body: str,
    *,
    status: str | None = "completed",
) -> dict:
    payload = {
        "type": "custom_tool_call",
        "name": "exec",
        "call_id": call_id,
        "input": body,
    }
    if status is not None:
        payload["status"] = status
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": payload,
    }


def _write_ledger(path: Path, records: list[dict]) -> str:
    payload = b"".join(
        json.dumps(record, sort_keys=True).encode("utf-8") + b"\n"
        for record in records
    )
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


class LedgerCollectionTests(unittest.TestCase):
    def test_db_gate_runs_provenance_tests_from_repository_root(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        source = (repository / "backend/scripts/db_gate.sh").read_text(
            encoding="utf-8"
        )
        expected = (
            '(\n  cd "$REPO_ROOT"\n'
            '  "$PY" -m unittest scripts.provenance.test_nyay19_replay_audit\n'
            ")"
        )

        self.assertIn(
            'REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"',
            source,
        )
        self.assertIn(expected, source)

    def test_deduplicates_before_window_and_filters_root_strictly(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp = Path(raw_temp)
            duplicate = _change(f"{ROOT}one.txt")
            first_records = [
                _event(
                    "2026-01-01T00:00:00.000Z",
                    "at-open-boundary",
                    _change(f"{ROOT}ignored.txt"),
                ),
                _event("2026-01-01T00:00:01.000Z", "call-one", duplicate),
                _event(
                    "2026-01-01T00:00:01.500Z",
                    "diagnostic",
                    _change("/tmp/diagnostic.txt"),
                ),
            ]
            second_records = [
                _event("2026-01-01T00:00:01.250Z", "call-one", duplicate),
                _event(
                    "2026-01-01T00:00:02.000Z",
                    "call-two",
                    _change(f"{ROOT}two.txt", kind="add"),
                ),
            ]
            first = temp / "first.jsonl"
            second = temp / "second.jsonl"
            hashes = {
                "a": _write_ledger(first, first_records),
                "b": _write_ledger(second, second_records),
            }
            spec = {
                "source_aliases": ["a", "b"],
                "canonical_aliases": ["a"],
                "supplemental_aliases": ["b"],
                "source_root": ROOT,
                "window": {
                    "after": "2026-01-01T00:00:00.000Z",
                    "through": "2026-01-01T00:00:02.000Z",
                },
                "expected_per_source": {
                    "a": {"events": 1, "changes": 1},
                    "b": {"events": 1, "changes": 1},
                },
                "expected": {
                    "events": 2,
                    "changes": 2,
                    "paths": 2,
                    "adds": 1,
                    "updates": 1,
                    "deletes": 0,
                    "moves": 0,
                    "canonical_events": 1,
                    "canonical_changes": 1,
                    "supplemental_events": 1,
                    "supplemental_changes": 1,
                    "conflicting_duplicates": 0,
                    "non_root_events": 1,
                    "mixed_root_events": 0,
                    "first": {
                        "timestamp": "2026-01-01T00:00:01.000Z",
                        "call_id": "call-one",
                    },
                    "last": {
                        "timestamp": "2026-01-01T00:00:02.000Z",
                        "call_id": "call-two",
                    },
                },
                "expected_source_sha256": hashes,
            }

            events, summary = collect(spec, {"a": first, "b": second})

            self.assertEqual(
                [event["call_id"] for event in events],
                ["call-one", "call-two"],
            )
            self.assertEqual(summary["non_root_events"], 1)
            report = _public_report(summary, None)
            serialized = json.dumps(report)
            self.assertNotIn(str(temp), serialized)
            self.assertNotIn("/tmp/diagnostic.txt", serialized)

    def test_conflicting_duplicate_is_fatal_even_outside_window(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp = Path(raw_temp)
            first = temp / "first.jsonl"
            second = temp / "second.jsonl"
            hashes = {
                "a": _write_ledger(
                    first,
                    [
                        _event(
                            "2025-01-01T00:00:00.000Z",
                            "same",
                            _change(f"{ROOT}one.txt"),
                        )
                    ],
                ),
                "b": _write_ledger(
                    second,
                    [
                        _event(
                            "2025-01-01T00:00:00.000Z",
                            "same",
                            _change(f"{ROOT}two.txt"),
                        )
                    ],
                ),
            }
            spec = {
                "source_aliases": ["a", "b"],
                "canonical_aliases": ["a"],
                "supplemental_aliases": ["b"],
                "source_root": ROOT,
                "window": {
                    "after": "2026-01-01T00:00:00.000Z",
                    "through": "2026-01-01T00:00:01.000Z",
                },
                "expected_per_source": {},
                "expected": {},
                "expected_source_sha256": hashes,
            }
            with self.assertRaisesRegex(AuditError, "CONFLICTING_DUPLICATE_CALL"):
                collect(spec, {"a": first, "b": second})


class NonApplyMutatorAuditTests(unittest.TestCase):
    def test_audit_is_aggregate_deduplicated_and_source_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp = Path(raw_temp)
            source_read = (
                'tools.exec_command({cmd:"git status --short",'
                f'workdir:"{ROOT.rstrip("/")}"}})'
            )
            source_write = (
                'tools.exec_command({cmd:"cp first second",'
                f'workdir:"{ROOT.rstrip("/")}"}})'
            )
            first = temp / "first.jsonl"
            second = temp / "second.jsonl"
            _write_ledger(
                first,
                [
                    _tool_event(
                        "2026-01-01T00:00:00.000Z", "outside", source_write
                    ),
                    _tool_event(
                        "2026-01-01T00:00:01.000Z", "read", source_read
                    ),
                    _tool_event(
                        "2026-01-01T00:00:01.250Z", "write", source_write
                    ),
                    _tool_event(
                        "2026-01-01T00:00:01.500Z",
                        "failed-write",
                        source_write,
                        status="failed",
                    ),
                    _tool_event(
                        "2026-01-01T00:00:01.750Z",
                        "aborted-write",
                        source_write,
                        status="aborted",
                    ),
                ],
            )
            _write_ledger(
                second,
                [
                    _tool_event(
                        "2026-01-01T00:00:01.125Z", "read", source_read
                    ),
                    _tool_event(
                        "2026-01-01T00:00:02.000Z",
                        "interactive",
                        "tools.write_stdin({session_id:7,chars:\"\"})",
                    ),
                ],
            )
            spec = {
                "source_aliases": ["a", "b"],
                "source_root": ROOT,
                "window": {
                    "after": "2026-01-01T00:00:00.000Z",
                    "through": "2026-01-01T00:00:02.000Z",
                },
            }

            summary = audit_non_apply_mutators(
                spec, {"a": first, "b": second}
            )

            self.assertEqual(summary["command_capable_envelopes"], 5)
            self.assertEqual(summary["exec_command_invocations"], 4)
            self.assertEqual(summary["write_stdin_invocations"], 1)
            self.assertEqual(summary["source_scoped_envelopes"], 4)
            self.assertEqual(summary["explicit_file_mutator_envelopes"], 3)
            self.assertEqual(summary["explicit_repo_state_mutator_envelopes"], 0)
            self.assertEqual(summary["status_categories"]["completed"], 3)
            self.assertEqual(summary["status_categories"]["failed"], 1)
            self.assertEqual(summary["status_categories"]["aborted"], 1)
            serialized = json.dumps(summary)
            self.assertNotIn(ROOT, serialized)
            self.assertNotIn("cp first second", serialized)

    def test_audit_rejects_conflicting_tool_duplicate_before_window(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp = Path(raw_temp)
            first = temp / "first.jsonl"
            second = temp / "second.jsonl"
            _write_ledger(
                first,
                [_tool_event("2025-01-01T00:00:00.000Z", "same", "one")],
            )
            _write_ledger(
                second,
                [_tool_event("2025-01-01T00:00:00.000Z", "same", "two")],
            )
            spec = {
                "source_aliases": ["a", "b"],
                "source_root": ROOT,
                "window": {
                    "after": "2026-01-01T00:00:00.000Z",
                    "through": "2026-01-01T00:00:01.000Z",
                },
            }

            with self.assertRaisesRegex(
                AuditError, "CONFLICTING_DUPLICATE_TOOL_CALL"
            ):
                audit_non_apply_mutators(spec, {"a": first, "b": second})

    def test_audit_rejects_duplicate_call_with_conflicting_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            temp = Path(raw_temp)
            first = temp / "first.jsonl"
            second = temp / "second.jsonl"
            body = 'tools.exec_command({cmd:"true",workdir:"/tmp"})'
            _write_ledger(
                first,
                [
                    _tool_event(
                        "2025-01-01T00:00:00.000Z",
                        "same",
                        body,
                        status="failed",
                    )
                ],
            )
            _write_ledger(
                second,
                [
                    _tool_event(
                        "2025-01-01T00:00:00.000Z",
                        "same",
                        body,
                        status="aborted",
                    )
                ],
            )
            spec = {
                "source_aliases": ["a", "b"],
                "source_root": ROOT,
                "window": {
                    "after": "2026-01-01T00:00:00.000Z",
                    "through": "2026-01-01T00:00:01.000Z",
                },
            }

            with self.assertRaisesRegex(
                AuditError, "CONFLICTING_DUPLICATE_TOOL_CALL"
            ):
                audit_non_apply_mutators(spec, {"a": first, "b": second})


class ReplayTests(unittest.TestCase):
    @staticmethod
    def _git(repo: Path, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.stdout.strip()

    def _fixture(self, repo: Path) -> tuple[dict, list[dict]]:
        self._git(repo, "init", "-q")
        self._git(repo, "config", "user.name", "Provenance Test")
        self._git(repo, "config", "user.email", "provenance@example.invalid")
        (repo / "backend/scripts").mkdir(parents=True)
        (repo / "backend/scripts/db_gate.sh").write_text(
            "set -eu\n", encoding="utf-8"
        )
        (repo / "sample.txt").write_text("one\n", encoding="utf-8")
        self._git(repo, "add", "-A")
        self._git(repo, "commit", "-q", "-m", "parent")
        parent = self._git(repo, "rev-parse", "HEAD")
        parent_tree = self._git(repo, "rev-parse", "HEAD^{tree}")

        (repo / "sample.txt").write_text("one\ntwo\n", encoding="utf-8")
        self._git(repo, "add", "sample.txt")
        self._git(repo, "commit", "-q", "-m", "reconstructed subject")
        reconstructed_commit = self._git(repo, "rev-parse", "HEAD")
        final_tree = self._git(repo, "rev-parse", "HEAD^{tree}")
        db_gate_hash = hashlib.sha256(
            (repo / "backend/scripts/db_gate.sh").read_bytes()
        ).hexdigest()
        spec = {
            "source_root": ROOT,
            "replay": {
                "parent_commit": parent,
                "parent_tree": parent_tree,
                "reconstructed_commit": reconstructed_commit,
                "reconstructed_tree": final_tree,
                "subject": "reconstructed subject",
                "files": 1,
                "insertions": 1,
                "deletions": 0,
                "create_mode_100644": 0,
                "db_gate_sha256": db_gate_hash,
            },
        }
        events = [
            {
                "timestamp": "2026-01-01T00:00:01.000Z",
                "call_id": "update",
                "owner": "a",
                "changes": {
                    "sample.txt": {
                        "type": "update",
                        "unified_diff": "@@ -1 +1,2 @@\n one\n+two\n",
                        "move_path": None,
                    }
                },
            }
        ]
        return spec, events

    def test_replay_reads_exact_parent_but_never_writes_source_repo(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            repo = Path(raw_temp)
            spec, events = self._fixture(repo)
            source_status_before = self._git(repo, "status", "--porcelain=v1")

            result = replay(spec, events, repo)

            self.assertEqual(
                result["reconstructed_commit"],
                spec["replay"]["reconstructed_commit"],
            )
            self.assertEqual(
                result["reconstructed_tree"],
                spec["replay"]["reconstructed_tree"],
            )
            self.assertEqual(
                self._git(repo, "status", "--porcelain=v1"),
                source_status_before,
            )

    def test_replay_rejects_missing_reconstructed_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            repo = Path(raw_temp)
            spec, events = self._fixture(repo)
            spec["replay"]["reconstructed_commit"] = "0" * 40

            with self.assertRaisesRegex(
                AuditError, "RECONSTRUCTED_COMMIT_UNAVAILABLE"
            ):
                replay(spec, events, repo)

    def test_replay_rejects_wrong_reconstructed_parent(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            repo = Path(raw_temp)
            spec, events = self._fixture(repo)
            spec["replay"]["parent_commit"] = spec["replay"][
                "reconstructed_commit"
            ]

            with self.assertRaisesRegex(
                AuditError, "RECONSTRUCTED_COMMIT_PARENT_MISMATCH"
            ):
                replay(spec, events, repo)

    def test_replay_rejects_wrong_reconstructed_subject(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            repo = Path(raw_temp)
            spec, events = self._fixture(repo)
            spec["replay"]["subject"] = "wrong subject"

            with self.assertRaisesRegex(
                AuditError, "RECONSTRUCTED_COMMIT_SUBJECT_MISMATCH"
            ):
                replay(spec, events, repo)

    def test_replay_rejects_wrong_reconstructed_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw_temp:
            repo = Path(raw_temp)
            spec, events = self._fixture(repo)
            spec["replay"]["reconstructed_tree"] = "0" * 40

            with self.assertRaisesRegex(
                AuditError, "RECONSTRUCTED_COMMIT_TREE_MISMATCH"
            ):
                replay(spec, events, repo)


if __name__ == "__main__":
    unittest.main()
