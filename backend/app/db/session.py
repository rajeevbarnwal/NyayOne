"""Database engine, session factory, and FastAPI dependency.

The engine is created lazily so importing this module never opens a DB driver or
connection (keeps imports/tests cheap and driver-agnostic).

Two rules are decided here and relied on everywhere else:

* **pooling.** ``StaticPool`` hands the SAME DBAPI connection to every caller.
  That is correct for an IN-MEMORY SQLite database — a second connection would
  be a second, empty database — and it is WRONG for anything else, because two
  concurrent requests then share one connection and therefore one transaction:
  whoever commits first ends the other's transaction (``cannot commit - no
  transaction is active``) and whoever rolls back first discards the other's
  uncommitted rows (a just-created row that reads back as ``404``). A
  FILE-BACKED SQLite database gets an ordinary connection pool, one connection
  per checked-out session, exactly like PostgreSQL.
* **transaction ownership.** See ``get_session``.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

#: How long a SQLite connection waits for another connection's write lock before
#: giving up with ``database is locked``. This is a LOCK WAIT, not a retry: the
#: statement is still executed exactly once, it is only allowed to queue behind
#: the writer that currently holds the file lock. PostgreSQL does the same thing
#: implicitly for ``FOR UPDATE``; SQLite has to be told a number.
SQLITE_BUSY_TIMEOUT_SECONDS = 30


def _sqlite_is_in_memory(url_str: str) -> bool:
    """True only for a database that CANNOT be shared by a second connection.

    ``sqlite://``, ``sqlite:///:memory:`` and an explicit ``?mode=memory`` are
    per-connection databases; every other SQLite URL names a file that any
    number of connections can open.
    """
    url = make_url(url_str)
    database = (url.database or "").strip()
    if database in ("", ":memory:"):
        return True
    mode = url.query.get("mode")
    if isinstance(mode, str):
        return mode == "memory"
    return bool(mode) and "memory" in tuple(mode)


def sqlite_connect_args(url_str: str) -> dict[str, object]:
    """The DBAPI keyword arguments this module gives a SQLite connection.

    Exposed (rather than inlined) so the wiring is assertable: ``create_engine``
    merges ``connect_args`` into the pool's creator, where nothing can read it
    back afterwards.
    """
    if _sqlite_is_in_memory(url_str):
        # One connection IS the database, and it is handed to whichever thread
        # asks for it, so the driver's same-thread guard has to be off.
        return {"check_same_thread": False}
    return {
        # The pool may hand a connection opened on one worker thread to another
        # later; only one Session holds it at a time, so this stays safe.
        "check_same_thread": False,
        # Queue behind another writer's file lock instead of failing instantly.
        "timeout": SQLITE_BUSY_TIMEOUT_SECONDS,
    }


def _make_sqlite_engine(url_str: str) -> Engine:
    if _sqlite_is_in_memory(url_str):
        # The ONLY place StaticPool is legitimate: a single shared connection is
        # the whole point, because the database lives inside that connection.
        # Nothing concurrent is served from this engine in production.
        from sqlalchemy.pool import StaticPool

        return create_engine(
            url_str,
            echo=settings.db_echo,
            connect_args=sqlite_connect_args(url_str),
            poolclass=StaticPool,
        )

    # File-backed: SQLAlchemy's default QueuePool, i.e. INDEPENDENT connections
    # — exactly the guarantee StaticPool does not give, and the one that makes
    # "one transaction per request" true at the connection level too.
    engine = create_engine(
        url_str,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args=sqlite_connect_args(url_str),
    )

    @event.listens_for(engine, "connect")
    def _sqlite_connection_pragmas(dbapi_connection, _record):  # pragma: no cover
        cursor = dbapi_connection.cursor()
        try:
            # WAL lets readers run while a writer holds the write lock, which is
            # what makes overlapping GET/POST traffic on one file behave.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_SECONDS * 1000}")
        finally:
            cursor.close()

    return engine


def _make_engine(url: str) -> Engine:
    # SQLite (used by tests and by the browser gate) does not accept
    # server-style pool sizing on every pool class, so it has its own builder.
    if url.startswith("sqlite"):
        return _make_sqlite_engine(url)
    return create_engine(
        url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return _make_engine(settings.database_url)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(), autoflush=False, expire_on_commit=False, class_=Session
    )


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session and guaranteeing cleanup.

    TRANSACTION OWNERSHIP — THE RULE, ONE OWNER PER REQUEST
    =======================================================
    **The request handler owns the transaction. This dependency does not.**

    Concretely:

    * A handler that CHANGES anything must call ``session.commit()`` itself, or
      delegate to a service that documents that it commits (``otp_service`` and
      ``recovery_service`` do). Committing is how a handler declares "this unit
      of work is complete", and it is what makes commit-then-dispatch orderings
      — commit the rows, only then hand the outbox intents to the relay —
      expressible at all.
    * This dependency NEVER commits. It only cleans up: it rolls back whatever
      is still open when the handler returns or raises, and closes the session.
      A rollback after a successful commit is a no-op on an empty transaction;
      a rollback after a read-only handler simply ends the read transaction.
    * Therefore a handler that mutates and forgets to commit LOSES its work.
      That is deliberate: a silent second commit here is how the same request
      ended up with two owners, and two owners sharing one connection is what
      produced ``sqlite3.OperationalError: cannot commit - no transaction is
      active`` under concurrency.

    Nothing about rollback-on-failure changes: a typed domain error still rolls
    back before the envelope is built (``app.api.v1.tutoring._typed``), and an
    unexpected exception is rolled back here, so a refused request still leaves
    zero partial rows.
    """
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    else:
        # Ends a read-only transaction, or discards work a handler never
        # declared complete. Never a commit — see the rule above.
        session.rollback()
    finally:
        session.close()
