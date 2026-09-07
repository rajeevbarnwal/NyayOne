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
    "registration_dob_reconciliations",
    "student_profiles",
    "otp_challenges",
    "otp_outbox",
    "recovery_sessions",
    "consents",
    "student_verifications",
    "guardian_consents",
    "audit_events",
    # Wave 1 (SAATHI-58 / SAATHI-63)
    "user_settings", "privacy_preferences", "data_subject_requests", "export_jobs", "deletion_jobs",
    "law_schools", "law_school_programmes", "law_school_facts", "law_school_sources",
    "saved_law_schools", "law_school_follows", "comparison_sets", "comparison_items",
    # SAATHI-60 internship discovery and saved listings
    "internship_listings", "saved_internships",
    # NYAY-12 verified-email login identities
    "user_email_identities", "email_identity_mutations", "email_identity_reconciliations",
}

# This immutable one-to-one audit table is deliberately keyed by the parent
# registration UUID.  The primary key is also the physical index that backs
# its only foreign key; requiring a second surrogate UUID or duplicate index
# would weaken the one-row-per-registration contract without adding safety.
PRIMARY_KEY_COLUMNS = {
    "registration_dob_reconciliations": ("registration_id",),
    "student_authority_states": ("registration_id",),
    "institutional_authority_email_proofs": ("user_id",),
}


def _table_key_failures(
    *,
    table: str,
    dialect: str,
    columns: list[dict],
    primary_key: dict,
    indexes: list[dict],
    unique_constraints: list[dict],
    foreign_keys: list[dict],
) -> list[str]:
    """Validate UUID primary keys and indexed, deleting foreign keys."""

    failures: list[str] = []
    column_types = {
        column["name"]: str(column["type"]).upper() for column in columns
    }
    expected_primary_key = PRIMARY_KEY_COLUMNS.get(table, ("id",))
    primary_key_columns = tuple(primary_key.get("constrained_columns") or ())
    primary_uuid_column = expected_primary_key[0]
    if column_types.get(primary_uuid_column) != "UUID" and dialect == "postgresql":
        failures.append(f"{table}.{primary_uuid_column} is not UUID")
    if primary_key_columns != expected_primary_key:
        failures.append(
            f"{table} primary key is not exactly {','.join(expected_primary_key)}"
        )

    # A primary key is already a left-prefix index.  Count it here so a
    # one-to-one child keyed by its parent UUID does not require a redundant
    # second index merely to satisfy this introspection gate.
    indexed_shapes = [
        tuple(index.get("column_names") or []) for index in indexes
    ] + [
        tuple(item.get("column_names") or []) for item in unique_constraints
    ] + [primary_key_columns]
    for item in foreign_keys:
        constrained = tuple(item["constrained_columns"])
        if not any(shape[: len(constrained)] == constrained for shape in indexed_shapes):
            failures.append(
                f"{table}.{','.join(constrained)} foreign key is not indexed"
            )
        if not (item.get("options") or {}).get("ondelete"):
            failures.append(
                f"{table}.{','.join(constrained)} has no explicit ON DELETE"
            )
    return failures


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
        out["failures"].extend(
            _table_key_failures(
                table=table,
                dialect=engine.dialect.name,
                columns=inspector.get_columns(table),
                primary_key=primary_key,
                indexes=indexes,
                unique_constraints=unique_constraints,
                foreign_keys=foreign_keys,
            )
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
