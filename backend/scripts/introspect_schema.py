"""Failing schema/constraint introspection gate for registration storage."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.core.config import settings

EXPECTED_TABLES = {
    "users",
    "student_registrations",
    "student_profiles",
    "otp_challenges",
    "otp_outbox",
    "recovery_sessions",
    "consents",
    "student_verifications",
    "guardian_consents",
    "audit_events",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    engine = create_engine(settings.database_url)
    inspector = inspect(engine)
    tables = [name for name in inspector.get_table_names() if name != "alembic_version"]
    out: dict = {
        "dialect": engine.dialect.name,
        "server_version": None,
        "extensions": [],
        "audit_append_only_triggers": [],
        "tables": {},
        "failures": [],
    }
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            out["server_version"] = connection.scalar(text("SHOW server_version"))
            out["extensions"] = list(
                connection.scalars(
                    text("SELECT extname FROM pg_extension ORDER BY extname")
                )
            )
            out["audit_append_only_triggers"] = list(
                connection.scalars(
                    text(
                        """
                        SELECT tgname
                        FROM pg_trigger t
                        JOIN pg_class c ON c.oid = t.tgrelid
                        WHERE c.relname = 'audit_events' AND NOT t.tgisinternal
                        ORDER BY tgname
                        """
                    )
                )
            )
        elif engine.dialect.name == "sqlite":
            out["audit_append_only_triggers"] = list(
                connection.scalars(
                    text(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type = 'trigger' AND tbl_name = 'audit_events'
                        ORDER BY name
                        """
                    )
                )
            )
    for table in sorted(tables):
        indexes = inspector.get_indexes(table)
        unique_constraints = inspector.get_unique_constraints(table)
        foreign_keys = inspector.get_foreign_keys(table)
        primary_key = inspector.get_pk_constraint(table)
        out["tables"][table] = {
            "columns": [
                {
                    "name": column["name"],
                    "type": str(column["type"]),
                    "nullable": column["nullable"],
                }
                for column in inspector.get_columns(table)
            ],
            "primary_key": primary_key.get("constrained_columns", []),
            "indexes": sorted(index["name"] for index in indexes if index.get("name")),
            "unique_constraints": sorted(
                constraint["name"]
                for constraint in unique_constraints
                if constraint.get("name")
            ),
            "check_constraints": sorted(
                constraint["name"]
                for constraint in inspector.get_check_constraints(table)
                if constraint.get("name")
            ),
            "foreign_keys": [
                {
                    "columns": item["constrained_columns"],
                    "referred_table": item["referred_table"],
                    "referred_columns": item["referred_columns"],
                    "ondelete": (item.get("options") or {}).get("ondelete"),
                }
                for item in foreign_keys
            ],
        }
        columns = {column["name"]: str(column["type"]).upper() for column in inspector.get_columns(table)}
        if columns.get("id") != "UUID" and engine.dialect.name == "postgresql":
            out["failures"].append(f"{table}.id is not UUID")
        if primary_key.get("constrained_columns") != ["id"]:
            out["failures"].append(f"{table} primary key is not exactly id")
        indexed_shapes = [
            tuple(index.get("column_names") or [])
            for index in indexes
        ] + [
            tuple(item.get("column_names") or [])
            for item in unique_constraints
        ]
        for item in foreign_keys:
            constrained = tuple(item["constrained_columns"])
            if not any(shape[: len(constrained)] == constrained for shape in indexed_shapes):
                out["failures"].append(
                    f"{table}.{','.join(constrained)} foreign key is not indexed"
                )
            if not (item.get("options") or {}).get("ondelete"):
                out["failures"].append(
                    f"{table}.{','.join(constrained)} has no explicit ON DELETE"
                )
    missing = EXPECTED_TABLES - set(out["tables"])
    out["expected_tables_present"] = not missing
    out["missing_tables"] = sorted(missing)
    if engine.dialect.name == "postgresql":
        out["postgresql_16_or_newer"] = int(str(out["server_version"]).split(".", 1)[0]) >= 16
        out["pgvector_present"] = "vector" in out["extensions"]
    if not out["audit_append_only_triggers"]:
        out["failures"].append("audit_events append-only trigger is missing")
    payload = json.dumps(out, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if missing or out["failures"]:
        raise SystemExit(1)
    if engine.dialect.name == "postgresql" and (
        not out["postgresql_16_or_newer"] or not out["pgvector_present"]
    ):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
