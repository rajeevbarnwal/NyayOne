"""Render a live-schema data dictionary and Graphviz ERD source."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.core.config import settings


def main() -> None:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "../docs/architecture/data_model")
    output.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url)
    inspector = inspect(engine)
    tables = sorted(name for name in inspector.get_table_names() if name != "alembic_version")
    dictionary = {"dialect": engine.dialect.name, "tables": {}}
    dot = [
        "digraph registration {",
        '  graph [rankdir=LR, bgcolor="white"];',
        '  node [shape=plain, fontname="Helvetica"];',
    ]
    for table in tables:
        columns = inspector.get_columns(table)
        foreign_keys = inspector.get_foreign_keys(table)
        dictionary["tables"][table] = {
            "columns": [
                {"name": c["name"], "type": str(c["type"]), "nullable": c["nullable"]}
                for c in columns
            ],
            "foreign_keys": foreign_keys,
            "indexes": inspector.get_indexes(table),
            "unique_constraints": inspector.get_unique_constraints(table),
            "check_constraints": inspector.get_check_constraints(table),
        }
        rows = "".join(
            f'<TR><TD ALIGN="LEFT">{c["name"]}</TD><TD ALIGN="LEFT">{str(c["type"])}</TD>'
            f'<TD>{"NULL" if c["nullable"] else "NOT NULL"}</TD></TR>'
            for c in columns
        )
        dot.append(
            f'  "{table}" [label=<<TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0">'
            f'<TR><TD COLSPAN="3" BGCOLOR="#16543d"><FONT COLOR="white"><B>{table}</B></FONT></TD></TR>'
            f"{rows}</TABLE>>];"
        )
    for table in tables:
        for fk in inspector.get_foreign_keys(table):
            dot.append(f'  "{table}" -> "{fk["referred_table"]}" [label="{",".join(fk["constrained_columns"])}"];')
    dot.append("}")

    (output / "registration_schema.json").write_text(json.dumps(dictionary, indent=2), encoding="utf-8")
    (output / "registration_erd.dot").write_text("\n".join(dot) + "\n", encoding="utf-8")
    lines = [
        "# LegalSaathi registration data dictionary",
        "",
        f"Generated from the live `{engine.dialect.name}` schema. Alembic is the source of truth.",
        "",
    ]
    for table in tables:
        lines.extend([f"## `{table}`", "", "| Column | Type | Nullable |", "|---|---|---|"])
        for c in dictionary["tables"][table]["columns"]:
            lines.append(f"| `{c['name']}` | `{c['type']}` | {'Yes' if c['nullable'] else 'No'} |")
        lines.append("")
    (output / "registration_data_dictionary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
