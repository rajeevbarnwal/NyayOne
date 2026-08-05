"""Executable Wave 5 calendar schema proof (SAATHI-285/290/295).

Focus: the composite owner-scoped foreign keys introduced by
``0013_wave5_calendar_interop`` must each be backed by a NAMED index whose
LEADING columns equal the constrained columns IN ORDER, in both the real
alembic-migrated database and the ORM metadata, and ``downgrade()`` must drop
those indexes explicitly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

import app.models  # noqa: F401  (registers every mapper)
from app.db.base import Base
from scripts.wave5_postgres_gate import (
    _legacy_foreign_key_is_indexed,
    foreign_key_is_indexed,
    index_shapes,
    ordered_index_self_test,
)

BACKEND = Path(__file__).resolve().parents[1]
HEAD_REVISION = "0014_saathi60_internships"
PARENT_REVISION = "0012_wave4_moderation"

#: The exact ordered composite-index contract this migration owes its FKs.
COMPOSITE_FK_INDEXES: dict[str, dict[str, list[str]]] = {
    "calendar_events": {
        "ix_calendar_events_event_source_owner": ["event_source_id", "owner_user_id"],
    },
    "calendar_conflicts": {
        "ix_calendar_conflicts_left_event_owner": ["left_event_id", "owner_user_id"],
        "ix_calendar_conflicts_right_event_owner": ["right_event_id", "owner_user_id"],
    },
}

#: The composite FKs those indexes serve. They must survive unchanged.
COMPOSITE_FOREIGN_KEYS: dict[str, list[tuple[list[str], str, list[str]]]] = {
    "calendar_events": [
        (
            ["event_source_id", "owner_user_id"],
            "calendar_event_sources",
            ["id", "owner_user_id"],
        )
    ],
    "calendar_conflicts": [
        (["left_event_id", "owner_user_id"], "calendar_events", ["id", "owner_user_id"]),
        (["right_event_id", "owner_user_id"], "calendar_events", ["id", "owner_user_id"]),
    ],
}

WAVE5_TABLES = {
    "calendar_event_sources",
    "calendar_events",
    "calendar_view_preferences",
    "calendar_reminder_preferences",
    "calendar_conflicts",
    "calendar_export_subscriptions",
    "calendar_export_tokens",
    "calendar_export_revocations",
}


def _alembic(database: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"sqlite+pysqlite:///{database}"},
        capture_output=True,
        text=True,
    )


def _named_index_columns(inspector, table: str) -> dict[str, list[str]]:
    return {
        index["name"]: list(index.get("column_names") or [])
        for index in inspector.get_indexes(table)
        if index.get("name")
    }


# --------------------------------------------------------------------------- #
# D2 — ordered composite indexes exist in the migrated database
# --------------------------------------------------------------------------- #
def test_migration_creates_named_ordered_composite_fk_indexes(alembic_snapshots, tmp_path):
    database = tmp_path / "wave5-schema.db"
    shutil.copyfile(alembic_snapshots["head"], database)
    inspector = inspect(create_engine(f"sqlite+pysqlite:///{database}"))
    assert WAVE5_TABLES <= set(inspector.get_table_names())
    for table, expected in COMPOSITE_FK_INDEXES.items():
        actual = _named_index_columns(inspector, table)
        for name, columns in expected.items():
            assert name in actual, f"{table} is missing {name}"
            # Ordered, not merely present: a set comparison would accept the
            # reversed index that cannot serve the FK lookup.
            assert actual[name] == columns, (name, actual[name])


def test_migration_keeps_the_composite_foreign_keys_intact(alembic_snapshots, tmp_path):
    database = tmp_path / "wave5-fk.db"
    shutil.copyfile(alembic_snapshots["head"], database)
    inspector = inspect(create_engine(f"sqlite+pysqlite:///{database}"))
    for table, expected in COMPOSITE_FOREIGN_KEYS.items():
        actual = [
            (
                list(fk["constrained_columns"]),
                fk["referred_table"],
                list(fk["referred_columns"]),
            )
            for fk in inspector.get_foreign_keys(table)
            if len(fk["constrained_columns"]) > 1
        ]
        for item in expected:
            assert list(item) in [list(row) for row in actual], (table, item, actual)


def test_every_wave5_foreign_key_has_an_ordered_leading_index(alembic_snapshots, tmp_path):
    """The exact predicate the PostgreSQL gate applies, run on SQLite DDL."""
    database = tmp_path / "wave5-fk-index.db"
    shutil.copyfile(alembic_snapshots["head"], database)
    inspector = inspect(create_engine(f"sqlite+pysqlite:///{database}"))
    unindexed: list[str] = []
    for table in sorted(WAVE5_TABLES):
        shapes = index_shapes(
            inspector.get_indexes(table), inspector.get_unique_constraints(table)
        )
        for fk in inspector.get_foreign_keys(table):
            if not foreign_key_is_indexed(fk["constrained_columns"], shapes):
                unindexed.append(f"{table}.{','.join(fk['constrained_columns'])}")
    assert unindexed == []


def test_orm_metadata_and_migration_agree_on_the_composite_indexes():
    for table, expected in COMPOSITE_FK_INDEXES.items():
        declared = {
            index.name: [column.name for column in index.columns]
            for index in Base.metadata.tables[table].indexes
        }
        for name, columns in expected.items():
            assert name in declared, f"{table} ORM metadata is missing {name}"
            assert declared[name] == columns, (name, declared[name])


def test_downgrade_drops_the_composite_indexes_and_reupgrade_restores_them(
    alembic_snapshots, tmp_path
):
    database = tmp_path / "wave5-downgrade.db"
    shutil.copyfile(alembic_snapshots["head"], database)
    down = _alembic(database, "downgrade", PARENT_REVISION)
    assert down.returncode == 0, down.stderr[-2000:]
    after_down = inspect(create_engine(f"sqlite+pysqlite:///{database}"))
    assert not (WAVE5_TABLES & set(after_down.get_table_names()))
    remaining = {
        row[0]
        for row in create_engine(f"sqlite+pysqlite:///{database}")
        .connect()
        .exec_driver_sql("SELECT name FROM sqlite_master WHERE type = 'index'")
        .fetchall()
    }
    for expected in COMPOSITE_FK_INDEXES.values():
        assert not (set(expected) & remaining), sorted(set(expected) & remaining)

    up = _alembic(database, "upgrade", HEAD_REVISION)
    assert up.returncode == 0, up.stderr[-2000:]
    after_up = inspect(create_engine(f"sqlite+pysqlite:///{database}"))
    for table, expected in COMPOSITE_FK_INDEXES.items():
        actual = _named_index_columns(after_up, table)
        for name, columns in expected.items():
            assert actual.get(name) == columns, (name, actual.get(name))


# --------------------------------------------------------------------------- #
# D2 — the gate's ordered-shape predicate, and its negative self-test
# --------------------------------------------------------------------------- #
def test_two_single_column_indexes_do_not_satisfy_a_two_column_foreign_key():
    """NEGATIVE self-test: the old logic passes exactly where the new one fails."""
    fk = ["left_event_id", "owner_user_id"]
    split = [
        {"name": "ix_left_event_id", "column_names": ["left_event_id"]},
        {"name": "ix_owner_user_id", "column_names": ["owner_user_id"]},
    ]
    assert _legacy_foreign_key_is_indexed(fk, split, []) is True
    assert foreign_key_is_indexed(fk, index_shapes(split, [])) is False


def test_ordered_index_predicate_respects_column_order_and_leading_position():
    fk = ["left_event_id", "owner_user_id"]
    assert foreign_key_is_indexed(fk, [("left_event_id", "owner_user_id")])
    assert foreign_key_is_indexed(fk, [("left_event_id", "owner_user_id", "status")])
    assert not foreign_key_is_indexed(fk, [("owner_user_id", "left_event_id")])
    assert not foreign_key_is_indexed(fk, [("status", "left_event_id", "owner_user_id")])
    assert not foreign_key_is_indexed(fk, [("left_event_id",)])
    assert not foreign_key_is_indexed([], [("left_event_id", "owner_user_id")])


def test_gate_ordered_index_self_test_is_fail_closed():
    result = ordered_index_self_test()
    assert result["ok"] is True
    assert result["observations"] == {
        "legacy_accepts_two_single_column_indexes": True,
        "repaired_rejects_two_single_column_indexes": True,
        "repaired_accepts_ordered_composite": True,
        "repaired_rejects_reversed_composite": True,
        "repaired_accepts_longer_index_with_matching_leading_columns": True,
        "repaired_rejects_matching_columns_that_are_not_leading": True,
    }
