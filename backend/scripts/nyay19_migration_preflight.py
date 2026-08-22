#!/usr/bin/env python3
"""Read-only, aggregate-only NYAY-19 production migration preflight.

The preflight acquires the immutable 0020 migration's advisory/table lock
boundary, validates the exact 0019 schema/data authority, records only bounded
counts, and rolls the transaction back.  Its mode-0600 report is the object a
PO/Security/DBA approval must bind by whole-file SHA-256.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence

from sqlalchemy import Connection, create_engine


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from app.db.migration_release_guard import (  # noqa: E402
    MigrationTargetNotAuthoritative,
    PARENT_REVISION,
    TARGET_SOURCE_PATH,
    TARGET_SOURCE_SHA256,
    TARGET_REVISION,
    approval_inputs_are_canonical,
    locked_parent_report,
    source_authority_is_valid,
)

TARGET_PATH = TARGET_SOURCE_PATH
TARGET_SHA256 = TARGET_SOURCE_SHA256


NotAuthoritative = MigrationTargetNotAuthoritative


def _source_authority_is_valid() -> bool:
    """Verify frozen 0001-0019 history and the exact reviewed 0020 bytes."""

    return source_authority_is_valid()


def inspect_parent(
    connection: Connection,
    *,
    change_reference: str,
    approval_window_ends_at: str,
) -> dict[str, Any]:
    """Inspect one locked 0019 transaction without returning row values."""

    return locked_parent_report(
        connection,
        change_reference=change_reference,
        approval_window_ends_at=approval_window_ends_at,
    )


def build_report(
    database_url: str,
    *,
    change_reference: str,
    approval_window_ends_at: str,
) -> tuple[dict[str, Any], int]:
    engine = None
    if not approval_inputs_are_canonical(
        change_reference,
        approval_window_ends_at,
    ):
        return {
            "verdict": "FAIL",
            "code": "preflight_rejected",
            "parent_revision": PARENT_REVISION,
            "target_revision": TARGET_REVISION,
        }, 1
    if not _source_authority_is_valid():
        return {
            "verdict": "FAIL",
            "code": "source_authority_rejected",
            "parent_revision": PARENT_REVISION,
            "target_revision": TARGET_REVISION,
        }, 1
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                report = inspect_parent(
                    connection,
                    change_reference=change_reference,
                    approval_window_ends_at=approval_window_ends_at,
                )
            finally:
                transaction.rollback()
        return report, 0
    except NotAuthoritative:
        return {
            "verdict": "NOT_AUTHORITATIVE",
            "code": "postgresql_16_pgvector_required",
            "parent_revision": PARENT_REVISION,
            "target_revision": TARGET_REVISION,
        }, 78
    except Exception:
        return {
            "verdict": "FAIL",
            "code": "preflight_rejected",
            "parent_revision": PARENT_REVISION,
            "target_revision": TARGET_REVISION,
        }, 1
    finally:
        if engine is not None:
            engine.dispose()


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        os.fchmod(descriptor, 0o600)
        written = 0
        while written < len(payload):
            count = os.write(descriptor, payload[written:])
            if count <= 0:
                raise OSError("report write rejected")
            written += count
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        # A hard-link install is atomic on the same filesystem and fails with
        # EEXIST for every existing final object (regular file, link, FIFO,
        # directory).  Unlike replace/rename, it can never overwrite a
        # valuable path.  Removing the temporary name leaves one final link.
        os.link(temporary, path, follow_symlinks=False)
        Path(temporary).unlink()
    except Exception:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            Path(temporary).unlink()
        except OSError:
            pass
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--change-reference", required=True)
    parser.add_argument("--approval-window-ends-at", required=True)
    arguments = parser.parse_args(argv)
    try:
        from app.core.config import settings

        report, exit_code = build_report(
            settings.database_url,
            change_reference=arguments.change_reference,
            approval_window_ends_at=arguments.approval_window_ends_at,
        )
        _write_report(arguments.output, report)
    except Exception:
        report = {
            "verdict": "FAIL",
            "code": "preflight_rejected",
            "parent_revision": PARENT_REVISION,
            "target_revision": TARGET_REVISION,
        }
        exit_code = 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
