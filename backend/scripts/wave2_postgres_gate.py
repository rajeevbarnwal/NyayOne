"""Wave 2 target-runtime gate: PostgreSQL 16 + pgvector (SAATHI-123 / SAATHI-127).

This is the executable half of the Wave 2 database proof. ``scripts/wave2_db_gate.sh``
is the ONE command an operator runs; it detects the runtime, refuses to report a
pass when the runtime is absent, and then calls this module.

Why a script and not a ``tests/test_wave2_postgres_runtime.py``
---------------------------------------------------------------
``tests/test_wave3_postgres_runtime.py`` established the pattern this file
follows: opt-in, isolated, driven through the REAL services against the REAL
target database, never against SQLite. This module keeps that pattern
(``pg_ctx``-equivalent isolation, real HTTP-free service calls, a privacy scan at
the end) but lives under ``scripts/`` for two reasons:

1. the complete backend suite's skip ledger stays exactly ``2 skipped`` (the two
   Wave 3 runtime tests), so "the suite is green" keeps meaning one thing;
2. the gate stays ONE operator command that also owns scratch-database creation
   and three separate ``alembic`` subprocess invocations — work a pytest module
   cannot do without either leaking databases or hiding the migration path.

Nothing here is a substitute for the suite. It proves the things SQLite
FUNDAMENTALLY CANNOT prove; see ``SQLITE_CANNOT_PROVE`` below, which is printed
in the machine-readable summary so a reader never has to take that on trust.

Assertions (the numbering is the contract; ``--list`` prints it)
----------------------------------------------------------------
A1  migration paths       fresh 0007->head, fresh base->head, both rc 0, both
                          landing on the same head and the SAME schema.
A2  drift                 ``alembic check`` reports no drift at head.
A3  reversibility         downgrade->upgrade (Wave 2 scoped AND full base round
                          trip) returns a byte-identical schema fingerprint.
A4  schema surface        17 Wave 2 tables; every named CHECK and UNIQUE from the
                          ORM present in ``pg_constraint``; both PostgreSQL
                          PARTIAL unique indexes present WITH their predicates;
                          a LEADING index supporting every foreign key; explicit
                          ON DELETE on every foreign key; server >= 16; pgvector.
A5  price authority       the authoritative price columns exist, are NOT NULL and
                          are positive-constrained; a hold's snapshot cannot be
                          mutated to a non-positive value; a payment order's
                          amount equals its hold snapshot; a client-proposed
                          amount is refused with zero mutation; re-pricing a
                          tutor does not move an in-flight hold or its order.
A6  concurrency           REAL PostgreSQL row locking, exercised from separate
                          OS PROCESSES with separate server connections (the
                          distinct ``pg_backend_pid()`` values are reported):
                          one winner per slot, one order per hold, one succeeded
                          refund per order, one review per session.
A7  raw-storage privacy   every text/JSON column of every Wave 2 table scanned
                          for PAN / CVV / OTP / raw-token / SDP / ICE /
                          device-label shapes, plus the specific raw join token
                          minted during this run.
A8  seed determinism      exact row counts after the deterministic seed, and
                          proof that running the seed twice changes nothing.

Exit codes
----------
0   every assertion passed
1   at least one assertion FAILED (the summary names which)
78  BLOCKED: prerequisite runtime absent — no PostgreSQL 16 + pgvector reachable.
    78 is ``EX_CONFIG``. It is deliberately NOT 0 and NOT 1: a blocked run can
    never be read as a pass, and never as a product failure either.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

#: EX_CONFIG. Distinct from 0 (pass) and 1 (assertion failure).
BLOCKED_EXIT = 78
BLOCKED_PREFIX = "BLOCKED: prerequisite runtime absent"
HEAD = "0017_registration_invariants"

#: The 17 Wave 2 tables. Pinned here, cross-checked against the ORM at runtime,
#: so a rename fails the gate rather than silently shrinking its coverage.
WAVE2_TABLES = (
    "booking_events",
    "booking_holds",
    "payment_events",
    "payment_orders",
    "payment_refunds",
    "review_moderation",
    "session_attendance",
    "session_cancellations",
    "session_reminder_jobs",
    "session_status_history",
    "tutor_availability_slots",
    "tutor_profiles",
    "tutor_reviews",
    "tutor_subjects",
    "tutoring_outbox",
    "tutoring_sessions",
    "video_session_grants",
)

#: Deletion order that respects the Wave 2 foreign keys (children first).
WAVE2_DELETE_ORDER = (
    "booking_events",
    "session_status_history",
    "session_reminder_jobs",
    "session_attendance",
    "session_cancellations",
    "review_moderation",
    "tutor_reviews",
    "video_session_grants",
    "tutoring_outbox",
    "payment_refunds",
    "payment_events",
    "tutoring_sessions",
    "payment_orders",
    "booking_holds",
    "tutor_availability_slots",
    "tutor_subjects",
    "tutor_profiles",
)

#: The two PostgreSQL PARTIAL unique indexes and the predicate each must carry.
PARTIAL_UNIQUE_INDEXES = {
    "uq_booking_holds_one_active_per_slot": ("booking_holds", "active"),
    "uq_payment_refunds_one_succeeded_per_order": ("payment_refunds", "succeeded"),
}

#: What this gate proves that the SQLite suite CANNOT, and why. Printed in the
#: summary so the distinction is never left to a reader's memory.
SQLITE_CANNOT_PROVE = {
    "A1/A2/A3": (
        "SQLite has type AFFINITY, not types: UUID vs CHAR(32) and "
        "timestamptz vs a naive DATETIME are indistinguishable to it, so "
        "`alembic check` on SQLite cannot see a type drift that PostgreSQL "
        "sees. 0009's downgrade also takes a DIFFERENT DDL path per dialect "
        "(batch_alter_table RECREATES the table on SQLite; PostgreSQL emits "
        "real DROP CONSTRAINT / DROP COLUMN), so only this gate exercises the "
        "ALTER path that a production downgrade would actually run."
    ),
    "A4": (
        "pg_index.indpred (the PARTIAL unique index PREDICATE), pg_constraint, "
        "server_version_num >= 160000 and the pgvector extension do not exist "
        "as concepts on SQLite."
    ),
    "A5": (
        "the CHECK is portable, but a CONCURRENT re-price racing an in-flight "
        "hold is not: SQLite serialises writers behind one database-wide write "
        "lock, so the loser gets 'database is locked' (an infrastructure "
        "error) instead of exercising MVCC snapshot isolation."
    ),
    "A6": (
        "THE point of this gate. SQLite has no row-level locking and no "
        "SELECT ... FOR UPDATE; a second writer is refused by a global lock "
        "before the domain's guard is ever evaluated. Only PostgreSQL can show "
        "that the conditional INSERT, the UNIQUE marker and the partial unique "
        "index actually pick exactly one winner between genuinely simultaneous "
        "transactions on separate connections."
    ),
    "A7": (
        "SQLite stores JSON as TEXT; PostgreSQL stores it in a typed column "
        "that may be TOASTed and compressed out of line. Scanning `col::text` "
        "on the target runtime is the only scan that sees what is really on "
        "disk in production."
    ),
    "A8": (
        "row counts are portable, but seed idempotency on SQLite never meets "
        "the UNIQUE-violation-under-concurrency path the real runtime takes."
    ),
}

# --------------------------------------------------------------------------- #
# Privacy scan patterns (A7)
# --------------------------------------------------------------------------- #
#: Shapes that must never appear in Wave 2 raw storage. Each entry is
#: (label, compiled regex). Deliberately shape-based, not name-based: a column
#: called `notes` leaking a PAN is exactly what a column-name check misses.
PRIVACY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 13-19 digit primary account number, with or without separators. The
    # hex-aware lookarounds are load-bearing: without them every UUID and every
    # SHA-256 digest in this schema (both of which are full of long digit runs)
    # would be reported as a card number and the scan would be noise.
    ("pan", re.compile(r"(?<![0-9a-fA-F-])(?:\d[ -]?){12,18}\d(?![0-9a-fA-F-])")),
    ("cvv_key", re.compile(r"\b(?:cvv|cvc|cvv2|cid|card_?sec)\b\s*[\"':=]", re.I)),
    ("otp_key", re.compile(r"\b(?:otp|one[_-]?time[_-]?pass\w*)\b\s*[\"':=]", re.I)),
    # A JWT-shaped value: three base64url segments. LiveKit join tokens are JWTs.
    ("raw_jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}")),
    ("raw_token_key", re.compile(r"\b(?:join_token|raw_token|access_token|api_secret|secret)\b\s*[\"':=]", re.I)),
    # SDP: the offer/answer body. `v=0` opens every session description.
    ("sdp", re.compile(r"(?m)^v=0\s*$|\bm=(?:audio|video|application)\s+\d+|\ba=fingerprint:", re.I)),
    # ICE candidates and the credentials that go with them.
    ("ice", re.compile(r"\bcandidate:\d|\btyp\s+(?:host|srflx|prflx|relay)\b|\ba=ice-(?:ufrag|pwd):", re.I)),
    # Browser device labels leak hardware and, often, a person's name.
    (
        "device_label",
        re.compile(
            r"\b(?:deviceId|groupId)\b|(?:FaceTime\s+HD\s+Camera|Built-?in\s+Microphone|"
            r"MacBook\s+Pro\s+Microphone|Default\s+-\s+(?:Microphone|Speakers))",
            re.I,
        ),
    ),
)

#: UUIDs are 32 hex digits with dashes and would otherwise trip the `pan`
#: pattern once the dashes are stripped; SHA-256 digests are 64 hex. Neither is
#: a card number, and both are expected in this schema, so a match that is
#: ENTIRELY one of these shapes is not a finding.
_BENIGN = re.compile(r"^[0-9a-fA-F-]{32,}$")


def _is_benign(match: str) -> bool:
    stripped = match.replace(" ", "").replace("-", "")
    if _BENIGN.match(match):
        return True
    # An ISO-8601 instant reduces to 14-20 digits once separators are stripped.
    return bool(re.match(r"^\d{14,20}$", stripped)) and bool(
        re.search(r"\d{4}-\d{2}-\d{2}", match)
    )


# --------------------------------------------------------------------------- #
# Result recorder
# --------------------------------------------------------------------------- #
class Recorder:
    """Numbered assertions with an unambiguous per-assertion verdict."""

    def __init__(self) -> None:
        self.results: list[dict] = []

    def record(self, ident: str, title: str, ok: bool, detail: object = None) -> bool:
        self.results.append(
            {
                "id": ident,
                "title": title,
                "status": "PASS" if ok else "FAIL",
                "detail": detail,
            }
        )
        print(f"  [{'PASS' if ok else 'FAIL'}] {ident} {title}")
        if not ok:
            print(f"         detail: {json.dumps(detail, default=str)[:2000]}")
        return ok

    def guard(self, ident: str, title: str, fn) -> bool:
        """Run ``fn``; an exception is a FAIL, never a crash."""
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001 - a gate reports, it does not crash
            return self.record(
                ident, title, False, {"exception": f"{type(exc).__name__}: {exc}"}
            )
        return self.record(ident, title, ok, detail)

    @property
    def failed(self) -> list[str]:
        return [row["id"] for row in self.results if row["status"] != "PASS"]


# --------------------------------------------------------------------------- #
# Runtime detection (Part C: honesty plumbing)
# --------------------------------------------------------------------------- #
def detect_runtime(database_url: str | None) -> dict:
    """Describe the runtime actually in front of us. Never raises."""
    info: dict = {
        "database_url_set": bool(database_url),
        "dialect": None,
        "reachable": False,
        "server_version": None,
        "server_version_num": None,
        "postgres_16_or_newer": False,
        "pgvector": None,
        "driver": None,
        "blocked_reason": None,
    }
    if not database_url:
        info["blocked_reason"] = "DATABASE_URL is not set"
        return info
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.engine import make_url
    except Exception as exc:  # noqa: BLE001
        info["blocked_reason"] = f"SQLAlchemy is not importable ({exc})"
        return info

    try:
        url = make_url(database_url)
    except Exception as exc:  # noqa: BLE001
        info["blocked_reason"] = f"DATABASE_URL is not a URL ({exc})"
        return info
    info["dialect"] = url.get_backend_name()
    info["driver"] = url.get_driver_name()
    if info["dialect"] != "postgresql":
        info["blocked_reason"] = (
            f"DATABASE_URL points at '{info['dialect']}', not PostgreSQL. "
            "SQLite cannot prove any of A4.7, A6 or A7."
        )
        return info
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            info["reachable"] = True
            info["server_version"] = connection.scalar(text("SHOW server_version"))
            info["server_version_num"] = int(
                connection.scalar(text("SHOW server_version_num"))
            )
            info["pgvector"] = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            )
        engine.dispose()
    except Exception as exc:  # noqa: BLE001
        info["blocked_reason"] = (
            f"no PostgreSQL server answered at DATABASE_URL "
            f"({type(exc).__name__}: {str(exc).splitlines()[0][:200]})"
        )
        return info

    info["postgres_16_or_newer"] = (info["server_version_num"] or 0) >= 160000
    if not info["postgres_16_or_newer"]:
        info["blocked_reason"] = (
            f"server is {info['server_version']}; the approved target runtime is "
            "PostgreSQL 16 or newer"
        )
        return info
    if not info["pgvector"]:
        # Try to install it the way CI does before declaring the runtime wrong.
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(database_url)
            with engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            with engine.connect() as connection:
                info["pgvector"] = connection.scalar(
                    text("SELECT extversion FROM pg_extension WHERE extname='vector'")
                )
            engine.dispose()
        except Exception:  # noqa: BLE001
            info["pgvector"] = None
    if not info["pgvector"]:
        info["blocked_reason"] = (
            "the pgvector extension is neither installed nor installable; this "
            "is not a pgvector/pgvector:pg16 image"
        )
    return info


def print_runtime_banner(info: dict) -> None:
    print("== Wave 2 target-runtime gate: PostgreSQL 16 + pgvector ==")
    print(f"  runtime.dialect            : {info['dialect'] or '<none>'}")
    print(f"  runtime.driver             : {info['driver'] or '<none>'}")
    print(f"  runtime.reachable          : {info['reachable']}")
    print(f"  runtime.server_version     : {info['server_version'] or '<none>'}")
    print(f"  runtime.postgres_16_plus   : {info['postgres_16_or_newer']}")
    print(f"  runtime.pgvector           : {info['pgvector'] or '<none>'}")


def blocked(info: dict, output: Path | None) -> int:
    print("")
    print(f"{BLOCKED_PREFIX}: {info['blocked_reason']}")
    print(
        "  This run proved NOTHING about PostgreSQL. It is not a pass and it is "
        "not a product failure."
    )
    print(
        "  Required: a reachable PostgreSQL 16+ with pgvector "
        "(pgvector/pgvector:pg16) named by DATABASE_URL."
    )
    summary = {
        "gate": "wave2_postgres",
        "status": "BLOCKED",
        "exit_code": BLOCKED_EXIT,
        "reason": info["blocked_reason"],
        "runtime": info,
        "assertions": [],
        "executed": False,
    }
    payload = json.dumps(summary, indent=2, default=str)
    print("WAVE2_PG_GATE_SUMMARY " + json.dumps(summary, default=str))
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    return BLOCKED_EXIT


# --------------------------------------------------------------------------- #
# Schema fingerprint (A1/A3)
# --------------------------------------------------------------------------- #
def _norm(text_value: object) -> str:
    return re.sub(r"\s+", " ", str(text_value or "")).strip().lower()


def schema_fingerprint(engine) -> dict:
    """A canonical, dialect-visible description of the whole public schema."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    out: dict = {}
    for table in sorted(inspector.get_table_names()):
        if table == "alembic_version":
            continue
        out[table] = {
            "columns": [
                {
                    "name": column["name"],
                    "type": _norm(column["type"]),
                    "nullable": bool(column["nullable"]),
                    "default": _norm(column.get("default")),
                }
                for column in inspector.get_columns(table)
            ],
            "pk": sorted(
                inspector.get_pk_constraint(table).get("constrained_columns") or []
            ),
            "unique": sorted(
                f"{item.get('name')}({','.join(item.get('column_names') or [])})"
                for item in inspector.get_unique_constraints(table)
            ),
            "check": sorted(
                f"{item.get('name')}[{_norm(item.get('sqltext'))}]"
                for item in inspector.get_check_constraints(table)
            ),
            "indexes": sorted(
                f"{item.get('name')}({','.join(item.get('column_names') or [])})"
                f"{'!u' if item.get('unique') else ''}"
                for item in inspector.get_indexes(table)
            ),
            "fks": sorted(
                f"{','.join(item.get('constrained_columns') or [])}->"
                f"{item.get('referred_table')}"
                f"({','.join(item.get('referred_columns') or [])})"
                f"[{(item.get('options') or {}).get('ondelete')}]"
                for item in inspector.get_foreign_keys(table)
            ),
        }
    # Partial index predicates are invisible to the inspector; read them from
    # the catalogue so a lost WHERE clause changes the fingerprint.
    with engine.connect() as connection:
        out["__partial_index_predicates__"] = {
            row[0]: _norm(row[1])
            for row in connection.execute(
                text(
                    "SELECT i.relname, pg_get_expr(x.indpred, x.indrelid) "
                    "FROM pg_index x "
                    "JOIN pg_class i ON i.oid = x.indexrelid "
                    "JOIN pg_class t ON t.oid = x.indrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE x.indpred IS NOT NULL AND n.nspname = 'public' "
                    "ORDER BY i.relname"
                )
            )
        }
    return out


def fingerprint_diff(left: dict, right: dict) -> list[str]:
    diffs: list[str] = []
    for key in sorted(set(left) | set(right)):
        if left.get(key) != right.get(key):
            diffs.append(key)
    return diffs


# --------------------------------------------------------------------------- #
# alembic / scratch database plumbing (A1, A2, A3)
# --------------------------------------------------------------------------- #
def run_alembic(args: list[str], url: str) -> tuple[int, str]:
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    env["PYTHONPATH"] = str(BACKEND) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND),
        env=env,
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout + proc.stderr)[-4000:]


def database_url_for_name(base_url: str, name: str) -> str:
    """Return an executable URL for ``name`` without losing credentials.

    ``str(URL)`` deliberately hides passwords as ``***``.  That representation
    is appropriate for diagnostics, but passing it to ``create_engine`` makes
    the mask the literal PostgreSQL password.  Connection URLs therefore use
    SQLAlchemy's explicit non-redacted renderer and must never be logged.
    """
    from sqlalchemy.engine import make_url

    return make_url(base_url).set(database=name).render_as_string(
        hide_password=False
    )


def scratch_url(base_url: str, name: str) -> str:
    return database_url_for_name(base_url, name)


def admin_execute(base_url: str, statement: str) -> None:
    from sqlalchemy import create_engine, text

    admin = database_url_for_name(base_url, "postgres")
    engine = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text(statement))
    finally:
        engine.dispose()


def drop_scratch(base_url: str, name: str) -> None:
    try:
        admin_execute(
            base_url,
            f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',
        )
    except Exception:  # noqa: BLE001 - PG < 13 has no FORCE; fall back
        try:
            admin_execute(base_url, f'DROP DATABASE IF EXISTS "{name}"')
        except Exception:  # noqa: BLE001 - a leaked scratch db is not a gate failure
            pass


def create_scratch(base_url: str, name: str) -> str:
    drop_scratch(base_url, name)
    admin_execute(base_url, f'CREATE DATABASE "{name}"')
    url = scratch_url(base_url, name)
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        engine.dispose()
    return url


# --------------------------------------------------------------------------- #
# Concurrency workers (A6) — one OS PROCESS, one server connection, each
# --------------------------------------------------------------------------- #
def _race_worker(kind: str, index: int, url: str, payload: dict, barrier, queue) -> None:
    """Run ONE contended operation on its OWN connection, then report.

    This is a separate PROCESS on purpose. Threads sharing a connection cannot
    contend for a PostgreSQL row lock at all, and even threads with separate
    connections share one GIL-scheduled interpreter; separate processes give
    genuinely simultaneous transactions, and each reports the
    ``pg_backend_pid()`` it ran on so "these really were different connections"
    is evidence rather than a claim.
    """
    result: dict = {"worker": index, "kind": kind, "outcome": "unstarted"}
    engine = None
    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session
        from sqlalchemy.pool import NullPool

        import app.models  # noqa: F401
        from app.services.providers.payment_provider import DeterministicPaymentAdapter
        from app.services.tutoring import booking, payments, reviews
        from app.services.tutoring.errors import TutoringError

        engine = create_engine(url, poolclass=NullPool, future=True)
        with Session(engine) as session:
            result["backend_pid"] = session.scalar(text("SELECT pg_backend_pid()"))
            result["os_pid"] = os.getpid()
            try:
                barrier.wait(timeout=60)
            except Exception as exc:  # noqa: BLE001
                result["outcome"] = f"barrier:{type(exc).__name__}"
                queue.put(result)
                return
            try:
                if kind == "hold":
                    hold = booking.create_hold(
                        session,
                        slot_id=uuid.UUID(payload["slot_id"]),
                        student_user_id=uuid.UUID(payload["student_user_id"]),
                        idempotency_key=f"{payload['key_prefix']}-{index}",
                    )
                    session.commit()
                    result["row_id"] = str(hold.id)
                elif kind == "order":
                    created = payments.create_order(
                        session,
                        hold_id=uuid.UUID(payload["hold_id"]),
                        student_user_id=uuid.UUID(payload["student_user_id"]),
                        # ONE shared key: the contended path is "N callers, one
                        # logical order", which is what a retrying client does.
                        idempotency_key=payload["shared_key"],
                        provider=DeterministicPaymentAdapter(),
                    )
                    session.commit()
                    result["row_id"] = str(created.order.id)
                    result["replayed"] = bool(created.replayed)
                elif kind == "refund":
                    issued = payments.refund(
                        session,
                        order_id=uuid.UUID(payload["order_id"]),
                        amount_paise=int(payload["amount_paise"]),
                        reason="tutor_cancelled",
                        actor_role="admin",
                    )
                    session.commit()
                    result["row_id"] = str(issued.refund.id)
                elif kind == "review":
                    mutation = reviews.create(
                        session,
                        session_id=uuid.UUID(payload["session_id"]),
                        author_user_id=uuid.UUID(payload["author_user_id"]),
                        rating=5,
                        body="Concurrent review probe body, well over ten chars.",
                    )
                    session.commit()
                    result["row_id"] = str(mutation.review.id)
                else:  # pragma: no cover - programming error
                    raise AssertionError(f"unknown race kind {kind}")
                result["outcome"] = "won"
            except TutoringError as exc:
                session.rollback()
                result["outcome"] = exc.code
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                result["outcome"] = type(exc).__name__
                result["error"] = str(exc).splitlines()[0][:200]
    except Exception as exc:  # noqa: BLE001
        result["outcome"] = f"setup:{type(exc).__name__}"
        result["error"] = str(exc).splitlines()[0][:200]
    finally:
        if engine is not None:
            engine.dispose()
    queue.put(result)


def run_race(kind: str, url: str, payload: dict, workers: int = 6) -> list[dict]:
    import multiprocessing as mp

    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(workers)
    queue: object = ctx.Queue()
    procs = [
        ctx.Process(
            target=_race_worker,
            args=(kind, index, url, payload, barrier, queue),
            daemon=False,
        )
        for index in range(workers)
    ]
    for proc in procs:
        proc.start()
    results: list[dict] = []
    for _ in range(workers):
        try:
            results.append(queue.get(timeout=120))
        except Exception:  # noqa: BLE001
            results.append({"outcome": "no_result"})
    for proc in procs:
        proc.join(timeout=30)
        if proc.is_alive():  # pragma: no cover - defensive
            proc.terminate()
    return sorted(results, key=lambda row: row.get("worker", -1))


# --------------------------------------------------------------------------- #
# Fixture provisioning
# --------------------------------------------------------------------------- #
class Fixture:
    """The rows every probe below needs, built through the REAL services."""

    def __init__(self, factory, now: datetime) -> None:
        self.factory = factory
        self.now = now
        self.student_id = uuid.UUID("00000000-0000-4000-8000-0000000f2a01")
        self.rival_id = uuid.UUID("00000000-0000-4000-8000-0000000f2a02")
        self.tutor_user_id = uuid.UUID("00000000-0000-4000-8000-0000000f2a03")
        self.tutor_id = uuid.UUID("00000000-0000-4000-8000-0000000f2a04")
        self.slots: list[uuid.UUID] = []
        self.race_slot: uuid.UUID | None = None
        self.order_hold: uuid.UUID | None = None
        self.paid_order: uuid.UUID | None = None
        self.paid_hold: uuid.UUID | None = None
        self.review_session: uuid.UUID | None = None
        self.raw_join_token: str | None = None
        self.price_paise = 250_000

    def build(self) -> None:
        from app.models.registration import User
        from app.models.wave2 import TutorAvailabilitySlot, TutorProfile, TutorSubject

        with self.factory() as session:
            for user_id, role in (
                (self.student_id, "student"),
                (self.rival_id, "student"),
                (self.tutor_user_id, "lawyer"),
            ):
                if session.get(User, user_id) is None:
                    session.add(User(id=user_id, role=role, status="active"))
            session.flush()
            if session.get(TutorProfile, self.tutor_id) is None:
                session.add(
                    TutorProfile(
                        id=self.tutor_id,
                        user_id=self.tutor_user_id,
                        display_name="PG Gate Tutor",
                        headline="Target-runtime gate fixture",
                        experience_years=5,
                        source="pg_gate_fixture",
                        status="active",
                        session_price_paise=self.price_paise,
                        session_currency="INR",
                    )
                )
                session.flush()
                session.add(
                    TutorSubject(
                        tutor_id=self.tutor_id,
                        subject="Constitutional Law",
                        level="advanced",
                    )
                )
            for offset in range(1, 7):
                start = (self.now + timedelta(days=offset)).replace(
                    minute=0, second=0, microsecond=0
                )
                slot = TutorAvailabilitySlot(
                    tutor_id=self.tutor_id,
                    start_utc=start,
                    end_utc=start + timedelta(hours=1),
                    iana_timezone="Asia/Kolkata",
                    status="available",
                )
                session.add(slot)
                session.flush()
                self.slots.append(slot.id)
            session.commit()
        self.race_slot = self.slots[0]

    def open_hold(self, slot_id: uuid.UUID, key: str) -> uuid.UUID:
        """Open a hold anchored to the REAL clock, so its TTL is live now.

        Anchoring to ``self.now`` would hand later probes a hold that had
        already aged past ``BOOKING_HOLD_MINUTES`` while the migration probes
        ran, and the gate would then measure HOLD_EXPIRED instead of the
        contended INSERT it means to measure.
        """
        from app.services.tutoring import booking

        with self.factory() as session:
            hold = booking.create_hold(
                session,
                slot_id=slot_id,
                student_user_id=self.student_id,
                idempotency_key=key,
                now=datetime.now(timezone.utc),
            )
            session.commit()
            return hold.id

    def book_paid_session(self, slot_id: uuid.UUID, key: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
        """hold -> order -> VERIFIED paid webhook -> confirmed session."""
        from app.services.providers.payment_provider import (
            TOKEN_SUCCESS,
            DeterministicPaymentAdapter,
        )
        from app.services.tutoring import booking, payments

        adapter = DeterministicPaymentAdapter()
        with self.factory() as session:
            hold = booking.create_hold(
                session,
                slot_id=slot_id,
                student_user_id=self.student_id,
                idempotency_key=key,
                now=self.now,
            )
            created = payments.create_order(
                session,
                hold_id=hold.id,
                student_user_id=self.student_id,
                idempotency_key=f"{key}-order",
                provider=adapter,
                now=self.now,
            )
            order = created.order
            raw, signature = adapter.make_event_body(
                provider_order_ref=order.provider_order_ref,
                amount_paise=order.amount_paise,
                token=TOKEN_SUCCESS,
            )
            outcome = payments.handle_event(
                session,
                signature=signature,
                raw_body=raw,
                provider=adapter,
                now=self.now,
            )
            session.commit()
            return hold.id, order.id, outcome.tutoring_session.id

    def make_reviewable(self, session_id: uuid.UUID) -> None:
        """Move a confirmed session into the past and confirm attendance.

        A declared CLOCK SHIFT on fixture rows — exactly what the browser gate's
        ``wave2_e2e_fixture.py shift-session`` does — never elapsed wall time.
        The shift is derived from the row's OWN ``end_utc`` so it lands one hour
        in the past whichever slot the session was built on; a hard-coded offset
        silently stops working the moment the fixture calendar moves.
        """
        from sqlalchemy import text

        from app.models.wave2 import TutoringSession
        from app.services.tutoring import attendance

        with self.factory() as session:
            row = session.get(TutoringSession, session_id)
            end_utc = row.end_utc
            if end_utc.tzinfo is None:
                end_utc = end_utc.replace(tzinfo=timezone.utc)
            shift = (self.now - end_utc) - timedelta(hours=1)
            slot_id = row.slot_id
            session.execute(
                text(
                    "UPDATE tutoring_sessions SET start_utc = start_utc + :d, "
                    "end_utc = end_utc + :d WHERE id = :id"
                ),
                {"d": shift, "id": session_id},
            )
            session.execute(
                text(
                    "UPDATE tutor_availability_slots SET start_utc = start_utc + :d, "
                    "end_utc = end_utc + :d WHERE id = :id"
                ),
                {"d": shift, "id": slot_id},
            )
            session.commit()
        # The session now ended an hour ago, so "record after the end" is true
        # for the real clock and no further fudging is needed.
        after = self.now
        with self.factory() as session:
            attendance.record(
                session,
                session_id,
                actor_user_id=self.tutor_user_id,
                actor_role="tutor",
                now=after,
            )
            attendance.confirm(
                session, session_id, actor_user_id=self.student_id, now=after
            )
            session.commit()

    def mint_join_token(self, session_id: uuid.UUID) -> str | None:
        """Mint a REAL join credential so A7 can hunt for its raw token."""
        from app.services.tutoring import join_credentials

        try:
            with self.factory() as session:
                issued = join_credentials.issue(
                    session,
                    session_id,
                    actor_user_id=self.student_id,
                    actor_role="student",
                    now=self.now,
                )
                session.commit()
                return issued.raw_token
        except Exception:  # noqa: BLE001 - no provider configured is not a failure
            return None


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #
def wave2_row_counts(engine) -> dict[str, int]:
    from sqlalchemy import text

    counts: dict[str, int] = {}
    with engine.connect() as connection:
        for table in WAVE2_TABLES:
            counts[table] = int(
                connection.scalar(text(f'SELECT count(*) FROM "{table}"'))
            )
    return counts


def clear_wave2(engine) -> None:
    from sqlalchemy import text

    with engine.begin() as connection:
        for table in WAVE2_DELETE_ORDER:
            connection.execute(text(f'DELETE FROM "{table}"'))


def scan_raw_storage(engine, inspector, tables) -> tuple[int, list[dict]]:
    """A7: read every text/JSON column of ``tables`` and match the shape list.

    ONE implementation, shared by assertion A7.1 and by step S11 of
    ``infra/video/scripts/livekit_turn_smoke.sh`` (``--privacy-only``), so the
    database gate and the media smoke can never disagree about what counts as a
    leak. Columns are cast with ``::text`` deliberately: that is what forces
    PostgreSQL to render JSON/JSONB (possibly TOASTed) exactly as stored.
    """
    from sqlalchemy import text

    findings: list[dict] = []
    scanned_columns = 0
    with engine.connect() as connection:
        for table in sorted(tables):
            columns = [
                column
                for column in inspector.get_columns(table)
                if any(
                    token in _norm(column["type"])
                    for token in ("char", "text", "json")
                )
            ]
            if not columns:
                continue
            names = [column["name"] for column in columns]
            scanned_columns += len(names)
            selected = ", ".join(f'"{name}"::text' for name in names)
            for row in connection.execute(text(f'SELECT {selected} FROM "{table}"')):
                for name, value in zip(names, row):
                    if not value:
                        continue
                    for label, pattern in PRIVACY_PATTERNS:
                        for match in pattern.findall(str(value)):
                            found = match if isinstance(match, str) else str(match)
                            if label == "pan" and _is_benign(found):
                                continue
                            findings.append(
                                {
                                    "table": table,
                                    "column": name,
                                    "shape": label,
                                    "excerpt": found[:40],
                                }
                            )
    return scanned_columns, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, help="write the JSON summary here")
    parser.add_argument(
        "--keep-scratch",
        action="store_true",
        help="do not drop the scratch migration databases (debugging)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the assertion contract and exit 0 without touching a database",
    )
    parser.add_argument(
        "--privacy-only",
        action="store_true",
        help=(
            "run ONLY the A7 raw-storage scan and exit. Used by "
            "infra/video/scripts/livekit_turn_smoke.sh step S11 so the media "
            "smoke and the database gate share one set of shape patterns."
        ),
    )
    args = parser.parse_args(argv)

    if args.list:
        print(__doc__)
        return 0

    database_url = os.getenv("DATABASE_URL")
    info = detect_runtime(database_url)
    print_runtime_banner(info)
    if info["blocked_reason"]:
        return blocked(info, args.output)

    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session, sessionmaker

    import app.models  # noqa: F401
    from app.models import wave2 as wave2_models

    if args.privacy_only:
        # S11 of the media smoke: the SAME scan, over the SAME shape patterns,
        # run on its own so a media-plane operator does not have to migrate,
        # seed or race anything to answer "is a raw token on disk?".
        scan_engine = create_engine(database_url, pool_pre_ping=True, future=True)
        try:
            scan_inspector = inspect(scan_engine)
            present = [
                table
                for table in WAVE2_TABLES
                if table in set(scan_inspector.get_table_names())
            ]
            columns, findings = scan_raw_storage(scan_engine, scan_inspector, present)
        finally:
            scan_engine.dispose()
        summary = {
            "gate": "wave2_postgres",
            "mode": "privacy-only",
            "status": "PASS" if not findings else "FAIL",
            "exit_code": 0 if not findings else 1,
            "executed": True,
            "runtime": info,
            "tables_scanned": present,
            "columns_scanned": columns,
            "findings": findings,
        }
        print(
            f"\n-- A7 raw-storage privacy scan (privacy-only) --\n"
            f"  tables: {len(present)}  columns: {columns}  findings: {len(findings)}"
        )
        print("WAVE2_PG_GATE_SUMMARY " + json.dumps(summary, default=str))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
            )
        return 0 if not findings else 1

    rec = Recorder()
    started = datetime.now(timezone.utc)
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    stamp = uuid.uuid4().hex[:8]
    scratch_a = f"ls_w2gate_a_{stamp}"
    scratch_b = f"ls_w2gate_b_{stamp}"
    scratch_urls: dict[str, str] = {}

    try:
        # ------------------------------------------------------------------ #
        print("\n-- A1 migration paths --")
        try:
            scratch_urls["a"] = create_scratch(database_url, scratch_a)
            scratch_urls["b"] = create_scratch(database_url, scratch_b)
            scratch_ok = True
        except Exception as exc:  # noqa: BLE001
            scratch_ok = False
            rec.record(
                "A1.0",
                "scratch databases can be created for the migration probes",
                False,
                {"exception": f"{type(exc).__name__}: {exc}"},
            )

        if scratch_ok:
            rec.record("A1.0", "scratch databases created", True, [scratch_a, scratch_b])

            def a1_1():
                rc1, log1 = run_alembic(["upgrade", "0007_wave3_credentials"], scratch_urls["a"])
                if rc1 != 0:
                    return False, {"stage": "base->0007", "rc": rc1, "log": log1}
                rc2, log2 = run_alembic(["upgrade", "head"], scratch_urls["a"])
                return rc2 == 0, {"stage": "0007->head", "rc": rc2, "log": log2 if rc2 else "ok"}

            rec.guard("A1.1", "fresh 0007 -> head upgrade returns rc 0", a1_1)

            def a1_2():
                rc, log = run_alembic(["upgrade", "head"], scratch_urls["b"])
                return rc == 0, {"stage": "fresh base->head", "rc": rc, "log": log if rc else "ok"}

            rec.guard("A1.2", "fresh-base (empty database) upgrade to head returns rc 0", a1_2)

            def a1_3():
                heads = {}
                for key in ("a", "b"):
                    scratch_engine = create_engine(scratch_urls[key])
                    with scratch_engine.connect() as connection:
                        heads[key] = connection.scalar(
                            text("SELECT version_num FROM alembic_version")
                        )
                    scratch_engine.dispose()
                same = heads["a"] == heads["b"] == HEAD
                return same, heads

            rec.guard(
                "A1.3",
                f"both paths land on head {HEAD}",
                a1_3,
            )

            def a1_4():
                engines = {
                    key: create_engine(scratch_urls[key]) for key in ("a", "b")
                }
                try:
                    prints = {key: schema_fingerprint(eng) for key, eng in engines.items()}
                finally:
                    for eng in engines.values():
                        eng.dispose()
                diffs = fingerprint_diff(prints["a"], prints["b"])
                return not diffs, {"differing_objects": diffs}

            rec.guard(
                "A1.4",
                "0007->head and base->head produce the SAME schema",
                a1_4,
            )

        # ------------------------------------------------------------------ #
        print("\n-- A2 drift --")

        def a2_0():
            rc, log = run_alembic(["upgrade", "head"], database_url)
            return rc == 0, {"rc": rc, "log": log if rc else "ok"}

        rec.guard("A2.0", "operational database is at head", a2_0)

        def a2_1():
            rc, log = run_alembic(["check"], database_url)
            return rc == 0, {"rc": rc, "log": log}

        rec.guard("A2.1", "alembic check reports no drift", a2_1)

        # ------------------------------------------------------------------ #
        print("\n-- A3 downgrade / re-upgrade reversibility --")
        if scratch_ok:

            def a3_1():
                scratch_engine = create_engine(scratch_urls["a"])
                try:
                    before = schema_fingerprint(scratch_engine)
                finally:
                    scratch_engine.dispose()
                rc_down, log_down = run_alembic(
                    ["downgrade", "0008_wave2_tutoring"], scratch_urls["a"]
                )
                if rc_down != 0:
                    return False, {"stage": "downgrade 0009->0008", "log": log_down}
                rc_up, log_up = run_alembic(["upgrade", "head"], scratch_urls["a"])
                if rc_up != 0:
                    return False, {"stage": "upgrade 0008->head", "log": log_up}
                scratch_engine = create_engine(scratch_urls["a"])
                try:
                    after = schema_fingerprint(scratch_engine)
                finally:
                    scratch_engine.dispose()
                diffs = fingerprint_diff(before, after)
                return not diffs, {"differing_objects": diffs}

            rec.guard(
                "A3.1",
                "downgrade 0009->0008 then re-upgrade restores an identical schema",
                a3_1,
            )

            def a3_2():
                scratch_engine = create_engine(scratch_urls["b"])
                try:
                    before = schema_fingerprint(scratch_engine)
                finally:
                    scratch_engine.dispose()
                rc_down, log_down = run_alembic(["downgrade", "base"], scratch_urls["b"])
                if rc_down != 0:
                    return False, {"stage": "downgrade base", "log": log_down}
                rc_up, log_up = run_alembic(["upgrade", "head"], scratch_urls["b"])
                if rc_up != 0:
                    return False, {"stage": "upgrade head", "log": log_up}
                scratch_engine = create_engine(scratch_urls["b"])
                try:
                    after = schema_fingerprint(scratch_engine)
                finally:
                    scratch_engine.dispose()
                diffs = fingerprint_diff(before, after)
                return not diffs, {"differing_objects": diffs}

            rec.guard(
                "A3.2",
                "full downgrade base -> re-upgrade head restores an identical schema",
                a3_2,
            )

        # ------------------------------------------------------------------ #
        print("\n-- A4 schema surface --")
        inspector = inspect(engine)
        live_tables = set(inspector.get_table_names())

        def a4_1():
            missing = sorted(set(WAVE2_TABLES) - live_tables)
            orm = sorted(
                table.name
                for table in wave2_models.TimestampedBase.metadata.sorted_tables
                if table.name in set(WAVE2_TABLES)
            )
            return (
                not missing and len(WAVE2_TABLES) == 17 and len(orm) == 17,
                {"missing": missing, "count": len(WAVE2_TABLES)},
            )

        rec.guard("A4.1", "all 17 Wave 2 tables are present", a4_1)

        def _orm_named_constraints() -> tuple[set[str], set[str]]:
            from sqlalchemy import CheckConstraint, UniqueConstraint

            checks: set[str] = set()
            uniques: set[str] = set()
            metadata = wave2_models.TimestampedBase.metadata
            for name in WAVE2_TABLES:
                table = metadata.tables[name]
                for constraint in table.constraints:
                    if constraint.name is None:
                        continue
                    rendered = str(constraint.name)
                    if isinstance(constraint, CheckConstraint):
                        checks.add(rendered)
                    elif isinstance(constraint, UniqueConstraint):
                        uniques.add(rendered)
            return checks, uniques

        def a4_2():
            checks, _ = _orm_named_constraints()
            with engine.connect() as connection:
                live = {
                    row[0]
                    for row in connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE connamespace='public'::regnamespace AND contype='c'"
                        )
                    )
                }
            missing = sorted(checks - live)
            return not missing, {"declared": len(checks), "missing": missing}

        rec.guard(
            "A4.2",
            "every named CHECK declared on a Wave 2 model exists in pg_constraint",
            a4_2,
        )

        def a4_3():
            _, uniques = _orm_named_constraints()
            with engine.connect() as connection:
                live = {
                    row[0]
                    for row in connection.execute(
                        text(
                            "SELECT conname FROM pg_constraint "
                            "WHERE connamespace='public'::regnamespace AND contype='u'"
                        )
                    )
                }
            missing = sorted(uniques - live)
            return not missing, {"declared": len(uniques), "missing": missing}

        rec.guard(
            "A4.3",
            "every named UNIQUE declared on a Wave 2 model exists in pg_constraint",
            a4_3,
        )

        def a4_4():
            with engine.connect() as connection:
                rows = {
                    row[0]: (row[1], row[2], row[3])
                    for row in connection.execute(
                        text(
                            "SELECT i.relname, t.relname, x.indisunique, "
                            "       pg_get_expr(x.indpred, x.indrelid) "
                            "FROM pg_index x "
                            "JOIN pg_class i ON i.oid = x.indexrelid "
                            "JOIN pg_class t ON t.oid = x.indrelid "
                            "JOIN pg_namespace n ON n.oid = t.relnamespace "
                            "WHERE n.nspname='public' AND i.relname = ANY(:names)"
                        ),
                        {"names": list(PARTIAL_UNIQUE_INDEXES)},
                    )
                }
            problems = []
            for name, (table, marker) in PARTIAL_UNIQUE_INDEXES.items():
                found = rows.get(name)
                if found is None:
                    problems.append(f"{name}: absent")
                    continue
                on_table, is_unique, predicate = found
                if on_table != table:
                    problems.append(f"{name}: on {on_table}, expected {table}")
                if not is_unique:
                    problems.append(f"{name}: not UNIQUE")
                if not predicate or marker not in _norm(predicate):
                    problems.append(f"{name}: predicate {predicate!r} lost '{marker}'")
            return not problems, {"problems": problems, "found": rows}

        rec.guard(
            "A4.4",
            "both PostgreSQL PARTIAL unique indexes exist WITH their predicates",
            a4_4,
        )

        def a4_5():
            missing: list[str] = []
            for table in sorted(WAVE2_TABLES):
                shapes: list[tuple[str, ...]] = []
                for index in inspector.get_indexes(table):
                    if index.get("column_names"):
                        shapes.append(tuple(index["column_names"]))
                for item in inspector.get_unique_constraints(table):
                    if item.get("column_names"):
                        shapes.append(tuple(item["column_names"]))
                primary = tuple(
                    inspector.get_pk_constraint(table).get("constrained_columns") or ()
                )
                if primary:
                    shapes.append(primary)
                for fk in inspector.get_foreign_keys(table):
                    columns = tuple(fk.get("constrained_columns") or ())
                    if not columns:
                        continue
                    # LEADING: the FK columns must be the PREFIX of some index,
                    # which is the only shape PostgreSQL can use for the
                    # ON DELETE / referential-integrity lookup.
                    if not any(shape[: len(columns)] == columns for shape in shapes):
                        missing.append(f"{table}({','.join(columns)})")
            return not missing, {"unsupported_foreign_keys": missing}

        rec.guard(
            "A4.5",
            "every Wave 2 foreign key has a LEADING index supporting it",
            a4_5,
        )

        def a4_6():
            missing = []
            for table in sorted(WAVE2_TABLES):
                for fk in inspector.get_foreign_keys(table):
                    if not (fk.get("options") or {}).get("ondelete"):
                        missing.append(
                            f"{table}({','.join(fk.get('constrained_columns') or [])})"
                        )
            return not missing, {"foreign_keys_without_on_delete": missing}

        rec.guard("A4.6", "every Wave 2 foreign key declares an explicit ON DELETE", a4_6)

        def a4_7():
            return (
                bool(info["postgres_16_or_newer"] and info["pgvector"]),
                {
                    "server_version": info["server_version"],
                    "pgvector": info["pgvector"],
                },
            )

        rec.guard("A4.7", "server is PostgreSQL 16+ with pgvector installed", a4_7)

        # ------------------------------------------------------------------ #
        print("\n-- fixture provisioning (real services, isolated Wave 2 state) --")
        clear_wave2(engine)
        now = datetime.now(timezone.utc)
        fixture = Fixture(factory, now)
        fixture.build()
        fixture.order_hold = fixture.open_hold(fixture.slots[1], f"pg-gate-order-{stamp}")
        paid_hold, paid_order, paid_session = fixture.book_paid_session(
            fixture.slots[2], f"pg-gate-paid-{stamp}"
        )
        fixture.paid_hold, fixture.paid_order = paid_hold, paid_order
        _review_hold, _review_order, review_session = fixture.book_paid_session(
            fixture.slots[3], f"pg-gate-review-{stamp}"
        )
        fixture.review_session = review_session
        fixture.raw_join_token = fixture.mint_join_token(paid_session)
        fixture.make_reviewable(review_session)
        print(f"  fixture: paid_order={paid_order} review_session={review_session}")
        print(
            "  fixture: join token minted = "
            f"{'yes' if fixture.raw_join_token else 'no (provider unavailable)'}"
        )

        # ------------------------------------------------------------------ #
        print("\n-- A5 price authority --")

        def a5_1():
            columns = {
                (table, column["name"]): column
                for table in ("tutor_profiles", "booking_holds")
                for column in inspector.get_columns(table)
            }
            wanted = [
                ("tutor_profiles", "session_price_paise"),
                ("tutor_profiles", "session_currency"),
                ("booking_holds", "price_paise"),
                ("booking_holds", "price_currency"),
            ]
            problems = []
            for key in wanted:
                column = columns.get(key)
                if column is None:
                    problems.append(f"{key[0]}.{key[1]} absent")
                elif column["nullable"]:
                    problems.append(f"{key[0]}.{key[1]} is NULLABLE")
            return not problems, {"problems": problems}

        rec.guard(
            "A5.1",
            "the authoritative price columns exist on both tables and are NOT NULL",
            a5_1,
        )

        def _violates(statement: str, params: dict) -> str | None:
            """Return the failing constraint name, or None if the write stuck."""
            try:
                with engine.begin() as connection:
                    connection.execute(text(statement), params)
            except IntegrityError as exc:
                return getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or str(
                    exc.orig
                )[:200]
            return None

        def a5_2():
            outcomes = {
                "tutor_zero": _violates(
                    "UPDATE tutor_profiles SET session_price_paise = 0 WHERE id = :id",
                    {"id": fixture.tutor_id},
                ),
                "tutor_negative": _violates(
                    "UPDATE tutor_profiles SET session_price_paise = -1 WHERE id = :id",
                    {"id": fixture.tutor_id},
                ),
                "tutor_currency": _violates(
                    "UPDATE tutor_profiles SET session_currency = 'USD' WHERE id = :id",
                    {"id": fixture.tutor_id},
                ),
            }
            ok = all(value for value in outcomes.values())
            return ok, outcomes

        rec.guard(
            "A5.2",
            "tutor_profiles price is positive-constrained and INR-constrained by CHECK",
            a5_2,
        )

        def a5_3():
            outcomes = {
                "hold_zero": _violates(
                    "UPDATE booking_holds SET price_paise = 0 WHERE id = :id",
                    {"id": fixture.paid_hold},
                ),
                "hold_negative": _violates(
                    "UPDATE booking_holds SET price_paise = -250000 WHERE id = :id",
                    {"id": fixture.paid_hold},
                ),
                "hold_currency": _violates(
                    "UPDATE booking_holds SET price_currency = 'USD' WHERE id = :id",
                    {"id": fixture.paid_hold},
                ),
            }
            with engine.connect() as connection:
                still = connection.execute(
                    text(
                        "SELECT price_paise, price_currency FROM booking_holds "
                        "WHERE id = :id"
                    ),
                    {"id": fixture.paid_hold},
                ).one()
            unchanged = int(still[0]) == fixture.price_paise and still[1] == "INR"
            return all(outcomes.values()) and unchanged, {
                "violations": outcomes,
                "snapshot_after": [still[0], still[1]],
            }

        rec.guard(
            "A5.3",
            "a hold's price snapshot CANNOT be mutated to a non-positive value",
            a5_3,
        )

        def a5_4():
            with engine.connect() as connection:
                mismatches = connection.execute(
                    text(
                        "SELECT o.id, o.amount_paise, h.price_paise, o.currency, "
                        "       h.price_currency "
                        "FROM payment_orders o "
                        "JOIN booking_holds h ON h.id = o.hold_id "
                        "WHERE o.amount_paise <> h.price_paise "
                        "   OR o.currency <> h.price_currency"
                    )
                ).all()
                total = connection.scalar(text("SELECT count(*) FROM payment_orders"))
            return not mismatches, {
                "orders_checked": int(total or 0),
                "mismatches": [list(map(str, row)) for row in mismatches],
            }

        rec.guard(
            "A5.4",
            "every payment order's amount equals its hold's price snapshot",
            a5_4,
        )

        def a5_5():
            from app.services.tutoring import payments
            from app.services.tutoring.errors import PaymentAmountMismatch

            before = wave2_row_counts(engine)
            code = None
            with factory() as session:
                try:
                    payments.create_order(
                        session,
                        hold_id=fixture.order_hold,
                        student_user_id=fixture.student_id,
                        idempotency_key=f"pg-gate-tamper-{stamp}",
                        amount_paise=1,
                    )
                    session.commit()
                except PaymentAmountMismatch as exc:
                    session.rollback()
                    code = exc.code
                except Exception as exc:  # noqa: BLE001
                    session.rollback()
                    code = type(exc).__name__
            after = wave2_row_counts(engine)
            return code == "PAYMENT_AMOUNT_MISMATCH" and before == after, {
                "code": code,
                "row_delta": {
                    key: after[key] - before[key]
                    for key in after
                    if after[key] != before[key]
                },
            }

        rec.guard(
            "A5.5",
            "a client-proposed amount is refused with ZERO rows written",
            a5_5,
        )

        def a5_6():
            from app.models.wave2 import BookingHold, PaymentOrder, TutorProfile

            with factory() as session:
                profile = session.get(TutorProfile, fixture.tutor_id)
                profile.session_price_paise = fixture.price_paise * 3
                session.commit()
            with factory() as session:
                hold = session.get(BookingHold, fixture.paid_hold)
                order = session.get(PaymentOrder, fixture.paid_order)
                held = int(hold.price_paise)
                charged = int(order.amount_paise)
            with factory() as session:  # restore
                profile = session.get(TutorProfile, fixture.tutor_id)
                profile.session_price_paise = fixture.price_paise
                session.commit()
            return held == charged == fixture.price_paise, {
                "hold_snapshot": held,
                "order_amount": charged,
                "tutor_reprice_to": fixture.price_paise * 3,
            }

        rec.guard(
            "A5.6",
            "re-pricing the tutor moves NEITHER an in-flight hold nor its order",
            a5_6,
        )

        # ------------------------------------------------------------------ #
        print("\n-- A6 concurrency under REAL PostgreSQL row locking --")
        engine.dispose()  # release pooled connections before the race processes

        def _race_shape(results: list[dict], expect_winners: int = 1) -> tuple[bool, dict]:
            winners = [row for row in results if row.get("outcome") == "won"]
            pids = sorted({row.get("backend_pid") for row in results if row.get("backend_pid")})
            return (
                len(winners) == expect_winners and len(pids) == len(results),
                {
                    "outcomes": [row.get("outcome") for row in results],
                    "distinct_backend_pids": len(pids),
                    "workers": len(results),
                },
            )

        def a6_1():
            results = run_race(
                "hold",
                database_url,
                {
                    "slot_id": str(fixture.race_slot),
                    "student_user_id": str(fixture.rival_id),
                    "key_prefix": f"pg-gate-race-{stamp}",
                },
            )
            ok, detail = _race_shape(results)
            probe_engine = create_engine(database_url)
            with probe_engine.connect() as connection:
                active = connection.scalar(
                    text(
                        "SELECT count(*) FROM booking_holds "
                        "WHERE slot_id = :slot AND status = 'active'"
                    ),
                    {"slot": fixture.race_slot},
                )
            probe_engine.dispose()
            detail["active_holds_on_slot"] = int(active or 0)
            detail["results"] = results
            return ok and int(active or 0) == 1, detail

        rec.guard(
            "A6.1",
            "parallel booking-hold creation on ONE slot yields exactly one winner",
            a6_1,
        )

        def a6_2():
            # A FRESH hold, opened immediately before the race: a hold has a TTL
            # and the probes above take real time, so racing an aged hold would
            # measure HOLD_EXPIRED rather than the contended INSERT.
            hold_id = fixture.open_hold(
                fixture.slots[4], f"pg-gate-order-race-hold-{stamp}"
            )
            results = run_race(
                "order",
                database_url,
                {
                    "hold_id": str(hold_id),
                    "student_user_id": str(fixture.student_id),
                    "shared_key": f"pg-gate-order-race-{stamp}",
                },
            )
            probe_engine = create_engine(database_url)
            with probe_engine.connect() as connection:
                orders = connection.scalar(
                    text(
                        "SELECT count(*) FROM payment_orders WHERE hold_id = :hold"
                    ),
                    {"hold": hold_id},
                )
            probe_engine.dispose()
            # One order row is the invariant. A worker either won, replayed the
            # winner's row, or was refused by the idempotency-key UNIQUE — all
            # three are correct; TWO ROWS would not be.
            return int(orders or 0) == 1, {
                "orders_for_hold": int(orders or 0),
                "outcomes": [row.get("outcome") for row in results],
                "distinct_backend_pids": len(
                    {row.get("backend_pid") for row in results if row.get("backend_pid")}
                ),
                "results": results,
            }

        rec.guard(
            "A6.2",
            "parallel payment-order creation on ONE hold yields exactly one order",
            a6_2,
        )

        def a6_3():
            results = run_race(
                "refund",
                database_url,
                {
                    "order_id": str(fixture.paid_order),
                    "amount_paise": fixture.price_paise,
                },
            )
            probe_engine = create_engine(database_url)
            with probe_engine.connect() as connection:
                succeeded = connection.scalar(
                    text(
                        "SELECT count(*) FROM payment_refunds "
                        "WHERE order_id = :order AND status = 'succeeded'"
                    ),
                    {"order": fixture.paid_order},
                )
            probe_engine.dispose()
            return int(succeeded or 0) == 1, {
                "succeeded_refunds": int(succeeded or 0),
                "outcomes": [row.get("outcome") for row in results],
                "distinct_backend_pids": len(
                    {row.get("backend_pid") for row in results if row.get("backend_pid")}
                ),
                "results": results,
            }

        rec.guard(
            "A6.3",
            "parallel refunds on ONE paid order yield exactly one SUCCEEDED refund",
            a6_3,
        )

        def a6_4():
            results = run_race(
                "review",
                database_url,
                {
                    "session_id": str(fixture.review_session),
                    "author_user_id": str(fixture.student_id),
                },
            )
            probe_engine = create_engine(database_url)
            with probe_engine.connect() as connection:
                reviews_count = connection.scalar(
                    text("SELECT count(*) FROM tutor_reviews WHERE session_id = :s"),
                    {"s": fixture.review_session},
                )
            probe_engine.dispose()
            return int(reviews_count or 0) == 1, {
                "reviews_for_session": int(reviews_count or 0),
                "outcomes": [row.get("outcome") for row in results],
                "distinct_backend_pids": len(
                    {row.get("backend_pid") for row in results if row.get("backend_pid")}
                ),
                "results": results,
            }

        rec.guard(
            "A6.4",
            "parallel review creation on ONE session yields exactly one review",
            a6_4,
        )

        engine = create_engine(database_url, pool_pre_ping=True, future=True)
        factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
        inspector = inspect(engine)

        # ------------------------------------------------------------------ #
        print("\n-- A7 raw-storage privacy scan --")

        def a7_1():
            scanned_columns, findings = scan_raw_storage(
                engine, inspector, WAVE2_TABLES
            )
            return not findings, {
                "columns_scanned": scanned_columns,
                "findings": findings[:40],
                "finding_count": len(findings),
            }

        rec.guard(
            "A7.1",
            "no PAN / CVV / OTP / raw-token / SDP / ICE / device-label shape in "
            "any Wave 2 text or JSON column",
            a7_1,
        )

        def a7_2():
            if not fixture.raw_join_token:
                return True, {"skipped": "no video provider configured; no token minted"}
            needle = fixture.raw_join_token
            hits: list[str] = []
            with engine.connect() as connection:
                for table in sorted(live_tables):
                    columns = [
                        column["name"]
                        for column in inspector.get_columns(table)
                        if any(
                            token in _norm(column["type"])
                            for token in ("char", "text", "json")
                        )
                    ]
                    if not columns:
                        continue
                    expression = " || ' ' || ".join(
                        f"coalesce(\"{name}\"::text, '')" for name in columns
                    )
                    count = connection.scalar(
                        text(
                            f'SELECT count(*) FROM "{table}" WHERE ({expression}) LIKE :n'
                        ),
                        {"n": f"%{needle}%"},
                    )
                    if int(count or 0):
                        hits.append(f"{table}:{count}")
                grants = connection.scalar(
                    text("SELECT count(*) FROM video_session_grants")
                )
            return not hits, {
                "raw_token_hits": hits,
                "video_session_grants_rows": int(grants or 0),
            }

        rec.guard(
            "A7.2",
            "the raw join token minted during this run is stored NOWHERE (hash only)",
            a7_2,
        )

        # ------------------------------------------------------------------ #
        print("\n-- A8 deterministic seed --")

        def a8_1():
            from app.services.tutoring import seed as tutoring_seed

            anchor = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
            with factory() as session:
                tutoring_seed.provision(session, now=anchor)
                session.commit()
            first = wave2_row_counts(engine)
            with factory() as session:
                tutoring_seed.provision(session, now=anchor)
                session.commit()
            second = wave2_row_counts(engine)
            delta = {
                key: second[key] - first[key]
                for key in second
                if second[key] != first[key]
            }
            return not delta, {
                "counts_after_first_seed": first,
                "counts_after_second_seed": second,
                "delta": delta,
            }

        rec.guard(
            "A8.1",
            "the deterministic seed is idempotent: running it twice changes nothing",
            a8_1,
        )

        def a8_2():
            counts = wave2_row_counts(engine)
            seeded = {
                "tutor_profiles": counts["tutor_profiles"],
                "tutor_subjects": counts["tutor_subjects"],
                "tutor_availability_slots": counts["tutor_availability_slots"],
            }
            # The packaged cast: 3 tutors, 5 subjects, 3 days x 2 slots x 3
            # tutors = 18 slots, on top of the 6 fixture slots this gate made.
            ok = seeded["tutor_profiles"] >= 3 and seeded["tutor_subjects"] >= 5
            return ok, {"exact_row_counts": counts}

        rec.guard("A8.2", "exact Wave 2 row counts after the seed are reported", a8_2)

    finally:
        if not args.keep_scratch:
            for name in (scratch_a, scratch_b):
                drop_scratch(database_url, name)
        try:
            engine.dispose()
        except Exception:  # noqa: BLE001
            pass

    failed = rec.failed
    summary = {
        "gate": "wave2_postgres",
        "status": "PASS" if not failed else "FAIL",
        "exit_code": 0 if not failed else 1,
        "executed": True,
        "runtime": info,
        "started_utc": started.isoformat(),
        "finished_utc": datetime.now(timezone.utc).isoformat(),
        "assertions": rec.results,
        "failed_assertions": failed,
        "sqlite_cannot_prove": SQLITE_CANNOT_PROVE,
    }
    print("")
    print(
        f"assertions: {len(rec.results)}  passed: {len(rec.results) - len(failed)}  "
        f"failed: {len(failed)}"
    )
    print("WAVE2_PG_GATE_SUMMARY " + json.dumps(summary, default=str))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
        )
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
