"""Emit a privacy-safe PostgreSQL storage report for the Wave 3 QA database."""
from __future__ import annotations

import json
import os

from sqlalchemy import create_engine, inspect, text

WAVE3_TABLES = (
    "credential_issuers",
    "credentials",
    "credential_evidence",
    "credential_status_history",
    "credential_share_projections",
    "credential_outbox",
    "credential_reminder_jobs",
    "credential_evidence_scan_events",
    "issuer_authorisations",
    "credential_verification_events",
    "verification_tokens",
    "credential_revocations",
    "verification_access_logs",
)

# Repository-owned deterministic QA markers. They must never occur in
# searchable database plaintext even though the browser/API exercised them.
FORBIDDEN_PLAINTEXT = (
    "9000000006",
    "9000000007",
    "9000000097",
    "2004-03-14",
    "2000-01-01",
    "2001-01-02",
    "KA/1234/2023",
    "D/1234/2024",
    "aditi@nls.ac.in",
    "CERT-PRIVATE-2026-0007",
    "credential-e2e-private-marker",
    "moot-certificate.pdf",
)


def main() -> int:
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url, pool_pre_ping=True)
    inspector = inspect(engine)
    if engine.dialect.name != "postgresql":
        raise SystemExit("Wave 3 storage verification requires PostgreSQL")

    tables = sorted(inspector.get_table_names())
    missing_fk_indexes: list[str] = []
    plaintext_hits: list[dict[str, object]] = []
    counts: dict[str, int] = {}

    with engine.connect() as connection:
        for table in tables:
            indexes = [
                tuple(item["column_names"])
                for item in inspector.get_indexes(table)
                if item.get("column_names")
            ]
            indexes.extend(
                tuple(item["column_names"])
                for item in inspector.get_unique_constraints(table)
                if item.get("column_names")
            )
            primary = tuple(
                inspector.get_pk_constraint(table).get("constrained_columns") or ()
            )
            if primary:
                indexes.append(primary)
            for foreign_key in inspector.get_foreign_keys(table):
                columns = tuple(foreign_key.get("constrained_columns") or ())
                if columns and not any(
                    candidate[: len(columns)] == columns for candidate in indexes
                ):
                    missing_fk_indexes.append(f"{table}({','.join(columns)})")

            counts[table] = int(
                connection.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0
            )
            columns = [column["name"] for column in inspector.get_columns(table)]
            if not columns:
                continue
            searchable = " || ' ' || ".join(
                f"coalesce(\"{column}\"::text, '')" for column in columns
            )
            for marker in FORBIDDEN_PLAINTEXT:
                hits = int(
                    connection.scalar(
                        text(
                            f'SELECT count(*) FROM "{table}" '
                            f"WHERE ({searchable}) LIKE :needle"
                        ),
                        {"needle": f"%{marker}%"},
                    )
                    or 0
                )
                if hits:
                    plaintext_hits.append(
                        {"table": table, "marker": marker, "rows": hits}
                    )

        server_version = str(connection.scalar(text("SHOW server_version")))
        pgvector_version = connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        )
        alembic_head = connection.scalar(text("SELECT version_num FROM alembic_version"))
        raw_otp_rows = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM otp_challenges "
                    "WHERE verifier_hash ~ '^[0-9]{6}$'"
                )
            )
            or 0
        )
        delivered_otp_ciphertext_rows = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM otp_outbox "
                    "WHERE status = 'sent' AND code_ct IS NOT NULL"
                )
            )
            or 0
        )
        malformed_token_hash_rows = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM verification_tokens "
                    "WHERE token_hash !~ '^[0-9a-f]{64}$'"
                )
            )
            or 0
        )
        forbidden_audit_snapshot_rows = int(
            connection.scalar(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE EXISTS ("
                    "  SELECT 1 FROM json_each("
                    "    CASE WHEN json_typeof(before_state) = 'object' "
                    "    THEN before_state ELSE '{}'::json END"
                    "  ) "
                    "  WHERE lower(key) IN ("
                    "    'mobile','dob','otp','token','identifier','evidence',"
                    "    'object_ref','email','enrolment'"
                    "  )"
                    ") OR EXISTS ("
                    "  SELECT 1 FROM json_each("
                    "    CASE WHEN json_typeof(after_state) = 'object' "
                    "    THEN after_state ELSE '{}'::json END"
                    "  ) "
                    "  WHERE lower(key) IN ("
                    "    'mobile','dob','otp','token','identifier','evidence',"
                    "    'object_ref','email','enrolment'"
                    "  )"
                    ")"
                )
            )
            or 0
        )

    report = {
        "database": {
            "dialect": engine.dialect.name,
            "serverVersion": server_version,
            "pgvectorVersion": pgvector_version,
            "alembicHead": alembic_head,
            "tableCount": len(tables),
            "tables": tables,
        },
        "wave3": {
            "tablesPresent": sorted(set(WAVE3_TABLES).intersection(tables)),
            "tablesMissing": sorted(set(WAVE3_TABLES).difference(tables)),
            "rowCounts": {table: counts[table] for table in WAVE3_TABLES},
        },
        "privacy": {
            "plaintextMarkersChecked": len(FORBIDDEN_PLAINTEXT),
            "plaintextHits": plaintext_hits,
            "rawOtpVerifierRows": raw_otp_rows,
            "deliveredOtpCiphertextRows": delivered_otp_ciphertext_rows,
            "malformedTokenHashRows": malformed_token_hash_rows,
            "forbiddenAuditSnapshotRows": forbidden_audit_snapshot_rows,
        },
        "foreignKeys": {"missingSupportingIndexes": missing_fk_indexes},
    }
    report["pass"] = (
        not report["wave3"]["tablesMissing"]
        and not plaintext_hits
        and raw_otp_rows == 0
        and delivered_otp_ciphertext_rows == 0
        and malformed_token_hash_rows == 0
        and forbidden_audit_snapshot_rows == 0
        and not missing_fk_indexes
    )
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
