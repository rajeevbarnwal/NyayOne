"""Verify that a completed QA registration did not persist raw sensitive data.

This gate uses synthetic QA fixture values only. It never decrypts production
data and writes a boolean/shape report rather than copying database values.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.core.config import settings

SYNTHETIC_SENSITIVE_VALUES = (
    "9000000006",
    "2004-03-14",
    "KA/1234/2023",
    "aditi@nls.ac.in",
    "D/1234/2024",
)
SENSITIVE_AUDIT_KEYS = {
    "mobile",
    "dob",
    "institutional_email",
    "enrolment_number",
    "bar_enrolment_number",
    "otp",
    "code",
}


def _contains_sensitive_key(value: object) -> bool:
    if isinstance(value, dict):
        return bool(SENSITIVE_AUDIT_KEYS.intersection(value)) or any(
            _contains_sensitive_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    engine = create_engine(settings.database_url)
    inspector = inspect(engine)
    failures: list[str] = []
    report: dict[str, object] = {
        "dialect": engine.dialect.name,
        "synthetic_fixture_values_absent": True,
        "otp_outbox_payload_erased_after_delivery": True,
        "audit_snapshots_exclude_sensitive_keys": True,
        "counts": {},
        "failures": failures,
    }

    table_names = set(inspector.get_table_names())
    required = {
        "users",
        "student_registrations",
        "student_profiles",
        "otp_challenges",
        "otp_outbox",
        "consents",
        "student_verifications",
        "guardian_consents",
        "audit_events",
    }
    missing = sorted(required - table_names)
    if missing:
        failures.append(f"missing tables: {', '.join(missing)}")

    with engine.connect() as connection:
        for table in sorted(required & table_names):
            report["counts"][table] = connection.scalar(
                text(f'SELECT count(*) FROM "{table}"')  # table names are fixed above
            )

        if "otp_outbox" in table_names:
            live_payloads = connection.scalar(
                text(
                    "SELECT count(*) FROM otp_outbox "
                    "WHERE status = 'sent' AND code_ct IS NOT NULL"
                )
            )
            if live_payloads:
                report["otp_outbox_payload_erased_after_delivery"] = False
                failures.append("sent OTP outbox rows retain encrypted code payload")

        if "audit_events" in table_names:
            rows = connection.execute(
                text("SELECT before_state, after_state FROM audit_events")
            )
            for before_state, after_state in rows:
                for state in (before_state, after_state):
                    if isinstance(state, str):
                        try:
                            state = json.loads(state)
                        except json.JSONDecodeError:
                            pass
                    if _contains_sensitive_key(state):
                        report["audit_snapshots_exclude_sensitive_keys"] = False
                        failures.append("audit snapshot contains a sensitive field name")
                        break

    if engine.dialect.name == "sqlite":
        database = engine.url.database
        if database and database != ":memory:":
            raw = Path(database).read_bytes()
            for value in SYNTHETIC_SENSITIVE_VALUES:
                if value.encode() in raw:
                    report["synthetic_fixture_values_absent"] = False
                    failures.append("raw synthetic sensitive fixture found in SQLite file")
                    break
    else:
        # On server databases, search text-cast rows without returning values.
        with engine.connect() as connection:
            for table in sorted(required & table_names):
                columns = [column["name"] for column in inspector.get_columns(table)]
                if not columns:
                    continue
                expression = " || ' ' || ".join(
                    f"coalesce(\"{column}\"::text, '')" for column in columns
                )
                for value in SYNTHETIC_SENSITIVE_VALUES:
                    count = connection.scalar(
                        text(
                            f'SELECT count(*) FROM "{table}" '
                            f"WHERE ({expression}) LIKE :needle"
                        ),
                        {"needle": f"%{value}%"},
                    )
                    if count:
                        report["synthetic_fixture_values_absent"] = False
                        failures.append(
                            f"raw synthetic sensitive fixture found in {table}"
                        )
                        break

    payload = json.dumps(report, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
