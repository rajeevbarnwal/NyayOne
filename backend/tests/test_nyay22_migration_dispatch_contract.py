"""Source contract for exact authenticated migration postflight dispatch."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa

from app.db import migration_release_guard
from app.db.base import Base
import app.models  # noqa: F401 -- register every mapped table in Base.metadata


ENVIRONMENT = (
    Path(__file__).resolve().parents[1] / "app/db/migrations/env.py"
)
NYAY22_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "app/db/migrations/versions/0023_nyay22_mentor_ceremony.py"
)

NYAY22_OWNED_TABLES = frozenset(
    {
        "mentor_retention_blocked_graphs",
        "mentor_audit_links",
        "mentor_rate_buckets",
        "mentor_idempotency_records",
        "mentor_authority_step_ups",
        "mentor_sessions",
        "mentor_consents",
        "mentor_engagements",
        "mentor_subject_consents",
        "mentor_provider_results",
        "mentor_ceremonies",
        "tutor_profile_ownership_proofs",
        "mentor_invitations",
        "mentor_bootstrap_attempts",
    }
)
EXPECTED_NYAY22_FOREIGN_KEYS = frozenset(
    {
        "mentor_audit_links.audit_event_id",
        "mentor_authority_step_ups.actor_user_id",
        "mentor_authority_step_ups.ceremony_id",
        "mentor_authority_step_ups.mentor_session_id",
        "mentor_ceremonies.actor_user_id",
        "mentor_ceremonies.bootstrap_attempt_id",
        "mentor_ceremonies.invitation_id",
        "mentor_ceremonies.ownership_proof_id",
        "mentor_ceremonies.tutor_profile_id",
        "mentor_consents.engagement_id",
        "mentor_engagements.invitation_id",
        "mentor_engagements.mentor_user_id",
        "mentor_engagements.subject_registration_id",
        "mentor_engagements.tutor_profile_id",
        "mentor_invitations.initiator_user_id",
        "mentor_invitations.subject_registration_id",
        "mentor_provider_results.ceremony_id",
        "mentor_sessions.actor_user_id",
        "mentor_sessions.ceremony_id",
        "mentor_sessions.consent_id",
        "mentor_sessions.engagement_id",
        "mentor_sessions.ownership_proof_id",
        "mentor_sessions.subject_consent_id",
        "mentor_sessions.successor_id",
        "mentor_sessions.tutor_profile_id",
        "mentor_subject_consents.granted_by_user_id",
        "mentor_subject_consents.guardian_consent_id",
        "mentor_subject_consents.invitation_id",
        "mentor_subject_consents.subject_registration_id",
        "tutor_profile_ownership_proofs.tutor_profile_id",
        "tutor_profile_ownership_proofs.user_id",
    }
)


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _literal_columns(node: ast.AST) -> tuple[str, ...]:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return ()
    if not all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts):
        return ()
    return tuple(item.value for item in node.elts)


def _migration_foreign_keys_and_index_shapes() -> tuple[
    frozenset[str], dict[str, set[tuple[str, ...]]]
]:
    tree = ast.parse(NYAY22_MIGRATION.read_text(encoding="utf-8"))
    foreign_keys: set[str] = set()
    indexed_shapes: dict[str, set[tuple[str, ...]]] = {
        table: set() for table in NYAY22_OWNED_TABLES
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node) == "create_table" and node.args:
            table_node = node.args[0]
            if not isinstance(table_node, ast.Constant) or table_node.value not in NYAY22_OWNED_TABLES:
                continue
            table = table_node.value
            indexed_shapes[table].add(("id",))
            for item in node.args[1:]:
                if _call_name(item) == "ForeignKeyConstraint" and item.args:
                    columns = _literal_columns(item.args[0])
                    foreign_keys.update(f"{table}.{column}" for column in columns)
                elif _call_name(item) == "UniqueConstraint":
                    columns = tuple(
                        value.value
                        for value in item.args
                        if isinstance(value, ast.Constant) and isinstance(value.value, str)
                    )
                    if columns:
                        indexed_shapes[table].add(columns)
        elif _call_name(node) == "create_index" and len(node.args) >= 3:
            table_node = node.args[1]
            if isinstance(table_node, ast.Constant) and table_node.value in NYAY22_OWNED_TABLES:
                columns = _literal_columns(node.args[2])
                if columns:
                    indexed_shapes[table_node.value].add(columns)
    return frozenset(foreign_keys), indexed_shapes


def _missing_leading_indexes(
    foreign_keys: frozenset[str], indexed_shapes: dict[str, set[tuple[str, ...]]]
) -> list[str]:
    missing: list[str] = []
    for foreign_key in sorted(foreign_keys):
        table, column = foreign_key.split(".", 1)
        if not any(shape and shape[0] == column for shape in indexed_shapes[table]):
            missing.append(foreign_key)
    return missing


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


def test_nyay22_migration_indexes_every_foreign_key_left_prefix() -> None:
    """The unshipped 0023 DDL must satisfy the repository schema gate."""

    foreign_keys, indexed_shapes = _migration_foreign_keys_and_index_shapes()
    assert foreign_keys == EXPECTED_NYAY22_FOREIGN_KEYS
    assert _missing_leading_indexes(foreign_keys, indexed_shapes) == []


def test_nyay22_model_metadata_indexes_every_foreign_key_left_prefix() -> None:
    """ORM-created test databases must retain the same indexed-FK contract."""

    foreign_keys: set[str] = set()
    indexed_shapes: dict[str, set[tuple[str, ...]]] = {}
    for table_name in sorted(NYAY22_OWNED_TABLES):
        table = Base.metadata.tables[table_name]
        foreign_keys.update(
            f"{table_name}.{foreign_key.parent.name}"
            for foreign_key in table.foreign_keys
        )
        shapes = {
            tuple(column.name for column in index.columns)
            for index in table.indexes
        }
        shapes.update(
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if isinstance(constraint, (sa.PrimaryKeyConstraint, sa.UniqueConstraint))
        )
        indexed_shapes[table_name] = shapes

    actual_foreign_keys = frozenset(foreign_keys)
    assert actual_foreign_keys == EXPECTED_NYAY22_FOREIGN_KEYS
    assert _missing_leading_indexes(actual_foreign_keys, indexed_shapes) == []
