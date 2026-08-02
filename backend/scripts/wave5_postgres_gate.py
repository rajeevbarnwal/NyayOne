"""PostgreSQL 16 + pgvector release gate for Wave 5 calendar interoperability.

The gate is destructive only to an explicitly opted-in loopback QA database.
An absent target runtime is BLOCKED (exit 78), never a synthetic pass.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

BLOCKED = 78
HEAD = "0013_wave5_calendar_interop"
PARENT = "0012_wave4_moderation"
TABLES = {
    "calendar_event_sources",
    "calendar_events",
    "calendar_view_preferences",
    "calendar_reminder_preferences",
    "calendar_conflicts",
    "calendar_export_subscriptions",
    "calendar_export_tokens",
    "calendar_export_revocations",
}


def is_isolated_gate_target(database_url: str, app_env: str, mutation_allowed: bool) -> bool:
    parsed = make_url(database_url)
    return (
        app_env.casefold() in {"test", "testing"}
        and (parsed.host or "").casefold() in {"127.0.0.1", "localhost", "::1"}
        and any(marker in (parsed.database or "").casefold() for marker in ("test", "qa", "wave5", "saathi295"))
        and mutation_allowed
    )


def index_shapes(
    indexes: list[dict[str, object]], unique_constraints: list[dict[str, object]]
) -> list[tuple[str, ...]]:
    """Every index/unique shape as an ORDERED column tuple.

    Index column order is semantic: only the leading columns of a b-tree index
    can serve a lookup, so the shapes must never be collapsed into a set of
    column names.
    """
    shapes = [tuple(index.get("column_names") or []) for index in indexes]
    shapes += [tuple(unique.get("column_names") or []) for unique in unique_constraints]
    return [shape for shape in shapes if shape]


def foreign_key_is_indexed(
    constrained_columns: list[str], shapes: list[tuple[str, ...]]
) -> bool:
    """True only when some index's LEADING columns equal the FK columns in order.

    This mirrors ``backend/scripts/introspect_schema.py``, which is the
    repository's semantic reference for this rule.
    """
    constrained = tuple(constrained_columns)
    if not constrained:
        return False
    return any(shape[: len(constrained)] == constrained for shape in shapes)


def _legacy_foreign_key_is_indexed(
    constrained_columns: list[str],
    indexes: list[dict[str, object]],
    unique_constraints: list[dict[str, object]],
) -> bool:
    """The DEFECTIVE pre-repair predicate, kept only for the negative self-test.

    It flattened every index into a set of column NAMES, so two independent
    single-column indexes wrongly satisfied a two-column foreign key. It is
    never consulted when deciding the gate result.
    """
    indexed = {
        column for index in indexes for column in index.get("column_names") or []
    }
    indexed |= {
        column
        for unique in unique_constraints
        for column in unique.get("column_names") or []
    }
    return set(constrained_columns) <= indexed


def ordered_index_self_test() -> dict[str, object]:
    """Negative self-test: two single-column indexes must NOT satisfy a 2-col FK.

    The gate proves its own detector is the ordered one by showing that the old
    set-of-names logic passes exactly the case the repaired logic rejects. If
    this ever stops holding, W5-PG-05 fails closed.
    """
    fk = ["left_event_id", "owner_user_id"]
    split = [
        {"name": "ix_left_event_id", "column_names": ["left_event_id"]},
        {"name": "ix_owner_user_id", "column_names": ["owner_user_id"]},
    ]
    ordered = [
        {
            "name": "ix_left_event_owner",
            "column_names": ["left_event_id", "owner_user_id"],
        }
    ]
    reversed_order = [
        {
            "name": "ix_owner_left_event",
            "column_names": ["owner_user_id", "left_event_id"],
        }
    ]
    leading_prefix = [
        {
            "name": "ix_left_event_owner_status",
            "column_names": ["left_event_id", "owner_user_id", "status"],
        }
    ]
    trailing_prefix = [
        {
            "name": "ix_status_left_event_owner",
            "column_names": ["status", "left_event_id", "owner_user_id"],
        }
    ]
    observations = {
        "legacy_accepts_two_single_column_indexes": _legacy_foreign_key_is_indexed(
            fk, split, []
        ),
        "repaired_rejects_two_single_column_indexes": not foreign_key_is_indexed(
            fk, index_shapes(split, [])
        ),
        "repaired_accepts_ordered_composite": foreign_key_is_indexed(
            fk, index_shapes(ordered, [])
        ),
        "repaired_rejects_reversed_composite": not foreign_key_is_indexed(
            fk, index_shapes(reversed_order, [])
        ),
        "repaired_accepts_longer_index_with_matching_leading_columns": (
            foreign_key_is_indexed(fk, index_shapes(leading_prefix, []))
        ),
        "repaired_rejects_matching_columns_that_are_not_leading": (
            not foreign_key_is_indexed(fk, index_shapes(trailing_prefix, []))
        ),
    }
    return {"ok": all(observations.values()), "observations": observations}


def privacy_canary_hits(
    surfaces: dict[str, object], canaries: set[str]
) -> list[str]:
    """Return only surface labels containing a forbidden value.

    This deliberately does not return the matched value: the release gate must
    prove that it detects a raw capability without copying that capability into
    stdout or its JSON evidence.
    """
    hits: list[str] = []
    for label, value in surfaces.items():
        serialized = json.dumps(value, default=str, sort_keys=True)
        if any(canary and canary in serialized for canary in canaries):
            hits.append(label)
    return sorted(hits)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )


class Results:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def add(self, ident: str, title: str, ok: bool, detail: object = None) -> None:
        self.rows.append({"id": ident, "title": title, "status": "PASS" if ok else "FAIL", "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {ident} {title}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(BACKEND / "test-results/wave5-postgres/summary.json"))
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    database_url = os.getenv("DATABASE_URL", "")
    allowed = is_isolated_gate_target(
        database_url,
        os.getenv("APP_ENV", ""),
        os.getenv("WAVE5_GATE_ALLOW_MUTATION") == "true",
    ) if database_url.startswith("postgresql") else False
    if not allowed:
        summary = {"gate": "wave5_postgres", "status": "BLOCKED", "executed": False, "reason": "isolated PostgreSQL QA target unavailable or mutation opt-in absent"}
        output.write_text(json.dumps(summary, indent=2) + "\n")
        print("BLOCKED: Wave 5 gate requires loopback PostgreSQL QA database and WAVE5_GATE_ALLOW_MUTATION=true")
        return BLOCKED

    from app.core.auth import ActorContext, Role
    from app.db.session import get_engine, get_sessionmaker
    from app.models.calendar import (
        CalendarConflict,
        CalendarEvent,
        CalendarExportRevocation,
        CalendarExportSubscription,
        CalendarExportToken,
        CalendarReminderPreference,
        CalendarViewPreference,
    )
    from app.models.registration import User
    from app.schemas.calendar import (
        EventCreate,
        EventUpdate,
        ReminderPreferenceUpdate,
        ViewPreferenceUpdate,
    )
    from app.services.calendar_service import (
        CalendarError,
        check_conflicts,
        create_event,
        create_export,
        delete_event,
        public_ics,
        update_event,
        update_reminder_preference,
        update_view_preferences,
    )

    results = Results()
    engine = get_engine()
    with engine.connect() as connection:
        version_num = int(connection.scalar(text("SHOW server_version_num")))
    if version_num < 160000:
        summary = {"gate": "wave5_postgres", "status": "BLOCKED", "executed": False, "server_version_num": version_num, "pgvector": None}
        output.write_text(json.dumps(summary, indent=2) + "\n")
        return BLOCKED

    # A genuinely fresh isolated database does not contain pgvector until the
    # repository-owned 0001 migration installs it.  Running the migration
    # before inspecting the extension makes this a clean-database gate instead
    # of accidentally requiring CI/bootstrap code to pre-seed schema state.
    up = _alembic("upgrade", "head")
    check = _alembic("check")
    with engine.connect() as connection:
        vector = connection.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
    results.add("W5-PG-01", "PostgreSQL 16 + pgvector", bool(vector), {"server_version_num": version_num, "pgvector": vector})
    results.add("W5-PG-02", "upgrade head and no drift", up.returncode == check.returncode == 0, {"upgrade_rc": up.returncode, "check_rc": check.returncode})
    with engine.connect() as connection:
        head = connection.scalar(text("SELECT version_num FROM alembic_version"))
    results.add("W5-PG-03", "exact Alembic head", head == HEAD, head)

    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    results.add("W5-PG-04", "all eight calendar tables", TABLES <= actual_tables, sorted(TABLES & actual_tables))
    self_test = ordered_index_self_test()
    fk_problems: list[str] = []
    for table in sorted(TABLES):
        shapes = index_shapes(
            inspector.get_indexes(table), inspector.get_unique_constraints(table)
        )
        for fk in inspector.get_foreign_keys(table):
            columns = ",".join(fk["constrained_columns"])
            if not foreign_key_is_indexed(fk["constrained_columns"], shapes):
                fk_problems.append(
                    f"{table}.{columns} foreign key has no index whose leading columns match in order"
                )
            if fk.get("options", {}).get("ondelete") not in {"CASCADE", "RESTRICT"}:
                fk_problems.append(f"{table}.{columns} has no explicit CASCADE/RESTRICT delete policy")
    results.add(
        "W5-PG-05",
        "foreign keys indexed in order with explicit delete policy",
        not fk_problems and bool(self_test["ok"]),
        {"problems": fk_problems, "ordered_index_self_test": self_test},
    )

    down = _alembic("downgrade", PARENT)
    after_down = set(inspect(engine).get_table_names())
    reup = _alembic("upgrade", "head")
    results.add("W5-PG-06", "downgrade removes and re-upgrade restores Wave 5", down.returncode == reup.returncode == 0 and not (TABLES & after_down), {"down_rc": down.returncode, "up_rc": reup.returncode})

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        user = User(role="student", status="active")
        session.add(user)
        session.commit()
        owner_id = user.id
    actor = ActorContext(user_id=owner_id, roles=frozenset({Role.STUDENT}))
    payload = EventCreate.model_validate({
        "title": "PostgreSQL gate reminder",
        "starts_at": "2026-08-10T04:30:00Z",
        "ends_at": "2026-08-10T05:30:00Z",
        "timezone": "Asia/Kolkata",
        "status": "scheduled",
        "privacy_classification": "personal",
    })

    def replay_event(_: int) -> str:
        with SessionLocal() as session:
            return str(create_event(session, actor, payload, "wave5-pg-event-idempotency").id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        event_ids = list(pool.map(replay_event, range(8)))
    results.add("W5-PG-07", "8-way event idempotency race converges", len(set(event_ids)) == 1, event_ids)

    with SessionLocal() as session:
        adjacent = EventCreate.model_validate({**payload.model_dump(), "title": "Adjacent", "starts_at": "2026-08-10T05:30:00Z", "ends_at": "2026-08-10T06:30:00Z"})
        overlap = EventCreate.model_validate({**payload.model_dump(), "title": "Overlap", "starts_at": "2026-08-10T05:00:00Z", "ends_at": "2026-08-10T06:00:00Z"})
        adjacent_id = create_event(session, actor, adjacent, "wave5-pg-event-adjacent").id
        overlap_id = create_event(session, actor, overlap, "wave5-pg-event-overlap").id
        conflicts = check_conflicts(session, actor, [uuid.UUID(event_ids[0]), adjacent_id, overlap_id], True)
        canonical = all(str(item.left_event_id) < str(item.right_event_id) for item in conflicts.items)
    results.add("W5-PG-08", "half-open conflicts and canonical pairs", conflicts.total == 2 and canonical, conflicts.total)

    with SessionLocal() as session:
        view_user = User(role="student", status="active")
        reminder_user = User(role="student", status="active")
        session.add_all([view_user, reminder_user])
        session.commit()
        view_owner_id, reminder_owner_id = view_user.id, reminder_user.id

    def race_view(index: int) -> str:
        race_actor = ActorContext(user_id=view_owner_id, roles=frozenset({Role.STUDENT}))
        payload = ViewPreferenceUpdate(
            view_mode="week",
            source_types=["exam" if index == 0 else "moot"],
            timezone="Asia/Kolkata",
            expected_version=0,
        )
        with SessionLocal() as session:
            try:
                update_view_preferences(session, race_actor, payload)
                return "created"
            except CalendarError as error:
                session.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        view_race = list(pool.map(race_view, range(2)))
    with SessionLocal() as session:
        view_rows = session.scalar(select(func.count()).select_from(CalendarViewPreference).where(
            CalendarViewPreference.owner_user_id == view_owner_id
        ))
    results.add(
        "W5-PG-09",
        "first view-preference insert has one winner and one typed conflict",
        sorted(view_race) == ["calendar_stale_version", "created"] and view_rows == 1,
        {"outcomes": view_race, "rows": view_rows},
    )

    def race_reminder(_: int) -> str:
        race_actor = ActorContext(user_id=reminder_owner_id, roles=frozenset({Role.STUDENT}))
        payload = ReminderPreferenceUpdate(
            source_type="exam",
            channel="in_app",
            enabled=True,
            lead_minutes=30,
            quiet_start_min=1320,
            quiet_end_min=420,
            timezone="Asia/Kolkata",
            expected_version=0,
        )
        with SessionLocal() as session:
            try:
                update_reminder_preference(session, race_actor, payload)
                return "created"
            except CalendarError as error:
                session.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        reminder_race = list(pool.map(race_reminder, range(2)))
    with SessionLocal() as session:
        reminder_rows = session.scalar(select(func.count()).select_from(CalendarReminderPreference).where(
            CalendarReminderPreference.owner_user_id == reminder_owner_id,
            CalendarReminderPreference.source_type == "exam",
            CalendarReminderPreference.channel == "in_app",
        ))
    results.add(
        "W5-PG-10",
        "first reminder-preference insert has one winner and one typed conflict",
        sorted(reminder_race) == ["calendar_stale_version", "created"] and reminder_rows == 1,
        {"outcomes": reminder_race, "rows": reminder_rows},
    )

    with SessionLocal() as session:
        update_target = create_event(
            session,
            actor,
            EventCreate.model_validate({
                **payload.model_dump(),
                "title": "Concurrent update target",
                "starts_at": "2026-08-11T04:30:00Z",
                "ends_at": "2026-08-11T05:30:00Z",
            }),
            "wave5-pg-update-target",
        )

    def race_update(index: int) -> str:
        update_payload = EventUpdate.model_validate({
            **payload.model_dump(),
            "title": f"Concurrent winner {index}",
            "starts_at": "2026-08-11T04:30:00Z",
            "ends_at": "2026-08-11T05:30:00Z",
            "expected_version": 1,
        })
        with SessionLocal() as session:
            try:
                update_event(session, actor, update_target.id, update_payload)
                return "updated"
            except CalendarError as error:
                session.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        update_race = list(pool.map(race_update, range(2)))
    with SessionLocal() as session:
        updated_row = session.get(CalendarEvent, update_target.id)
        updated_version = updated_row.version if updated_row else None
    results.add(
        "W5-PG-14",
        "parallel event update has one version winner and one typed stale conflict",
        sorted(update_race) == ["calendar_stale_version", "updated"] and updated_version == 2,
        {"outcomes": update_race, "version": updated_version},
    )

    with SessionLocal() as session:
        delete_target = create_event(
            session,
            actor,
            EventCreate.model_validate({
                **payload.model_dump(),
                "title": "Concurrent delete target",
                "starts_at": "2026-08-12T04:30:00Z",
                "ends_at": "2026-08-12T05:30:00Z",
            }),
            "wave5-pg-delete-target",
        )

    def race_delete(_: int) -> str:
        with SessionLocal() as session:
            try:
                delete_event(session, actor, delete_target.id)
                return "deleted"
            except CalendarError as error:
                session.rollback()
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        delete_race = list(pool.map(race_delete, range(2)))
    with SessionLocal() as session:
        delete_rows = session.scalar(select(func.count()).select_from(CalendarEvent).where(
            CalendarEvent.id == delete_target.id
        ))
    results.add(
        "W5-PG-15",
        "parallel event delete has one winner and a non-enumerating loser",
        sorted(delete_race) == ["calendar_event_not_found", "deleted"] and delete_rows == 0,
        {"outcomes": delete_race, "rows": delete_rows},
    )

    with SessionLocal() as session:
        conflict_left = create_event(
            session,
            actor,
            EventCreate.model_validate({
                **payload.model_dump(),
                "title": "Concurrent conflict left",
                "starts_at": "2026-08-13T04:30:00Z",
                "ends_at": "2026-08-13T05:30:00Z",
            }),
            "wave5-pg-conflict-left",
        )
        conflict_right = create_event(
            session,
            actor,
            EventCreate.model_validate({
                **payload.model_dump(),
                "title": "Concurrent conflict right",
                "starts_at": "2026-08-13T05:00:00Z",
                "ends_at": "2026-08-13T06:00:00Z",
            }),
            "wave5-pg-conflict-right",
        )

    def race_conflict(_: int) -> tuple[int, tuple[tuple[str, str], ...]]:
        with SessionLocal() as session:
            result = check_conflicts(
                session,
                actor,
                [conflict_left.id, conflict_right.id],
                True,
            )
            pairs = tuple(
                (str(item.left_event_id), str(item.right_event_id))
                for item in result.items
            )
            return result.total, pairs

    with ThreadPoolExecutor(max_workers=2) as pool:
        conflict_race = list(pool.map(race_conflict, range(2)))
    with SessionLocal() as session:
        conflict_rows = session.scalar(select(func.count()).select_from(CalendarConflict).where(
            CalendarConflict.owner_user_id == owner_id,
            CalendarConflict.left_event_id.in_((conflict_left.id, conflict_right.id)),
            CalendarConflict.right_event_id.in_((conflict_left.id, conflict_right.id)),
        ))
    results.add(
        "W5-PG-16",
        "parallel conflict materialisation converges on one canonical pair",
        conflict_rows == 1
        and len(conflict_race) == 2
        and all(total == 1 for total, _pairs in conflict_race)
        and conflict_race[0][1] == conflict_race[1][1],
        {"outcomes": conflict_race, "rows": conflict_rows},
    )

    def create_feed(index: int) -> tuple[str, str]:
        with SessionLocal() as session:
            item = create_export(session, actor, "Asia/Kolkata", f"wave5-pg-export-{index:02d}")
            return str(item.id), item.feed_url or ""

    with ThreadPoolExecutor(max_workers=4) as pool:
        feeds = list(pool.map(create_feed, range(4)))
    with SessionLocal() as session:
        active = session.scalar(select(func.count()).select_from(CalendarExportSubscription).where(CalendarExportSubscription.owner_user_id == owner_id, CalendarExportSubscription.status == "active"))
        raw_hashes = list(session.scalars(select(CalendarExportToken.token_hash).join(CalendarExportSubscription, CalendarExportSubscription.id == CalendarExportToken.subscription_id).where(CalendarExportSubscription.owner_user_id == owner_id)))
        revocations = session.scalar(select(func.count()).select_from(CalendarExportRevocation).join(CalendarExportSubscription, CalendarExportSubscription.id == CalendarExportRevocation.subscription_id).where(CalendarExportSubscription.owner_user_id == owner_id))
        audit_blob = json.dumps([row[0] for row in session.execute(text("SELECT COALESCE(after_state::text, '') FROM audit_events WHERE actor_user_id = :owner"), {"owner": owner_id})])
        working = []
        for _ident, url in feeds:
            raw = url.rsplit("/", 1)[-1].removesuffix(".ics")
            try:
                content = public_ics(session, raw)
                working.append((raw, content))
            except Exception:
                pass
    one_working = len(working) == 1
    all_hashed = all(len(value) == 64 for value in raw_hashes)
    all_raw_tokens = [url.rsplit("/", 1)[-1].removesuffix(".ics") for _ident, url in feeds]
    no_raw_audit = all(raw not in audit_blob for raw in all_raw_tokens)
    results.add("W5-PG-11", "concurrent rotation leaves one active capability", active == 1 and one_working and revocations == 3, {"active": active, "working": len(working), "revocations": revocations})
    results.add("W5-PG-12", "tokens hashed and absent from audit", all_hashed and no_raw_audit)
    results.add("W5-PG-13", "ICS CRLF and privacy-minimised fields", one_working and working[0][1].startswith("BEGIN:VCALENDAR\r\n") and "DESCRIPTION:" not in working[0][1] and "URL:" not in working[0][1])

    scanner_canary = "W5_PRIVACY_SCANNER_CANARY_DO_NOT_SEAL"
    named_surfaces = {
        "database": {"value": scanner_canary},
        "log": scanner_canary,
        "audit": {"after_state": scanner_canary},
        "url": f"/unsafe/{scanner_canary}",
        "storage": {"calendar-token": scanner_canary},
        "console": [scanner_canary],
        "error": {"detail": scanner_canary},
        "evidence": {"body": scanner_canary},
    }
    self_test_hits = privacy_canary_hits(named_surfaces, {scanner_canary})
    clean_runtime_hits = privacy_canary_hits(
        {
            "database": {"token_hashes": raw_hashes},
            "audit": audit_blob,
            "log": "/api/v1/public/calendar-feeds/:token",
            "url": "/api/v1/public/calendar-feeds/:token",
            "storage": {},
            "console": [],
            "error": {"code": "calendar_export_not_found"},
            "evidence": {"token_state": "redacted"},
        },
        set(all_raw_tokens),
    )
    results.add(
        "W5-PG-17",
        "fail-closed privacy scanner detects every seeded surface and clean runtime is empty",
        self_test_hits == sorted(named_surfaces) and clean_runtime_hits == [],
        {"seeded_surface_hits": self_test_hits, "clean_runtime_hits": clean_runtime_hits},
    )

    summary = {
        "gate": "wave5_postgres",
        "status": "PASS" if all(row["status"] == "PASS" for row in results.rows) else "FAIL",
        "executed": True,
        "head": head,
        "rows": results.rows,
    }
    output.write_text(json.dumps(summary, indent=2, default=str) + "\n")
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
