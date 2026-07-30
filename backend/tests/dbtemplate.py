"""A provably-equivalent, ~40x cheaper stand-in for ``Base.metadata.create_all``.

Why this exists
---------------
Almost every test in this suite starts from a fresh SQLite database. Rendering
and executing the DDL for the 53 mapped tables (147 CREATE statements, 243
``sqlite_master`` rows once SQLite's implicit indexes are counted) costs ~26 ms,
and ``drop_all`` another ~8 ms because both walk the metadata issuing an
existence probe per table. Multiplied across the suite that is the single
largest block of wall time in the run -- pure duplicated setup, proving nothing.

What it does instead
--------------------
The schema is built ONCE per pytest session by the real
``Base.metadata.create_all`` into an in-memory template connection. Every
subsequent database is produced by ``sqlite3.Connection.backup()``, which copies
the template's pages verbatim into the destination (~0.6 ms).

Why that is safe
----------------
``backup()`` is a page-level copy, so the destination is bit-for-bit the same
database the real ``create_all`` produced: same tables, same columns, same
CHECK constraints, same explicit and implicit indexes, in the same
``sqlite_master`` order. ``tests/test_db.py::test_schema_template_is_identical_to_create_all``
asserts exactly that, so this optimisation cannot rot silently. Every test still
begins with a pristine, complete schema containing zero rows -- nothing about
what the suite proves changes.

Deliberately NOT named ``test_*`` so pytest does not collect it.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

__all__ = ["create_all", "reset_to_empty_schema", "template_master_rows", "MASTER_QUERY"]

#: Everything SQLite records about a schema: tables, indexes (explicit *and* the
#: implicit ones behind UNIQUE/PK), views, triggers, and their exact SQL.
MASTER_QUERY = "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"

_template: sqlite3.Connection | None = None
_template_engine: Any = None  # kept alive: StaticPool must not close _template


def _template_connection() -> sqlite3.Connection:
    global _template, _template_engine
    if _template is None:
        import app.models  # noqa: F401  (registers every table on Base.metadata)

        from app.db.base import Base

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        # A throwaway engine wired to `conn` so the REAL create_all builds the
        # template. Never disposed: disposing would close `conn`.
        engine = create_engine(
            "sqlite+pysqlite://", creator=lambda: conn, poolclass=StaticPool
        )
        Base.metadata.create_all(engine)
        _template, _template_engine = conn, engine
    return _template


def create_all(engine) -> None:
    """Drop-in replacement for ``Base.metadata.create_all(engine)``.

    Only valid for SQLite engines whose database is empty or discardable: the
    backup replaces the destination database wholesale rather than adding to it.
    That is precisely the "fresh per-test database" case every caller here wants.
    """
    template = _template_connection()
    raw = engine.raw_connection()
    try:
        template.backup(raw.driver_connection)
    finally:
        raw.close()  # returns the connection to the pool (or closes it)


#: Same operation, named for the case where the engine is session-scoped and
#: shared: backing the template over it both (re)creates the schema and empties
#: it, so it replaces a create_all/drop_all pair.
reset_to_empty_schema = create_all


def template_master_rows() -> list[tuple]:
    """``sqlite_master`` of the template, for the equivalence test."""
    return _template_connection().execute(MASTER_QUERY).fetchall()
