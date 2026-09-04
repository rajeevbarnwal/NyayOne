"""Source contract for exact authenticated migration postflight dispatch."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

from app.db import migration_release_guard


ENVIRONMENT = (
    Path(__file__).resolve().parents[1] / "app/db/migrations/env.py"
)
NYAY22_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "app/db/migrations/versions/0023_nyay22_mentor_ceremony.py"
)


def test_nyay22_native_database_name_is_an_exact_disposable_marker() -> None:
    assert "nyay22" in migration_release_guard._ISOLATED_DATABASE_MARKERS


def test_explicit_nyay9_checkpoint_dispatches_its_exact_postflight() -> None:
    source = ENVIRONMENT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "app.db.migration_release_guard"
        for alias in node.names
    }
    assert "NYAY9_REVISION" in imports
    assert "elif requested_revision == NYAY9_REVISION:" in source
    assert "expected_revision = NYAY9_REVISION" in source


def test_unknown_revision_cannot_inherit_a_newer_postflight() -> None:
    source = ENVIRONMENT.read_text(encoding="utf-8")
    assert (
        "else:\n                        expected_revision = "
        '"0020_auth_retention_lifecycle"'
    ) in source


def test_nyay22_downgrade_locks_every_owned_table_before_counting() -> None:
    """PostgreSQL cannot insert durable authority between count and drop."""

    spec = importlib.util.spec_from_file_location(
        "nyay22_migration_lock_contract", NYAY22_MIGRATION
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    executed: list[str] = []

    class Connection:
        dialect = SimpleNamespace(name="postgresql")

        def execute(self, statement):
            executed.append(str(statement))

    module._lock_owned_tables_for_downgrade(
        Connection(), module._OWNED_TABLES
    )
    assert len(module._OWNED_TABLES) == 14
    assert executed == [
        f'LOCK TABLE "{table}" IN ACCESS EXCLUSIVE MODE'
        for table in sorted(module._OWNED_TABLES)
    ]
    source = NYAY22_MIGRATION.read_text(encoding="utf-8")
    downgrade = source[source.index("def downgrade() -> None:") :]
    assert downgrade.index("_lock_owned_tables_for_downgrade") < downgrade.index(
        "SELECT count(*)"
    )
