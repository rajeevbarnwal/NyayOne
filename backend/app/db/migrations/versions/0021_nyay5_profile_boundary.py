"""Install the normalized server-authoritative profile boundary (NYAY-5).

Revision ID: 0021_nyay5_profile_boundary
Revises: 0020_auth_retention_lifecycle

This is a forward-only addition from the sealed 0020 head.  No identity PII is
duplicated: legal names and encrypted DOB remain in student_registrations.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import Connection

revision: str = "0021_nyay5_profile_boundary"
down_revision: str | None = "0020_auth_retention_lifecycle"
branch_labels = None
depends_on = None

_UUID = sa.Uuid(as_uuid=True)
_PG_ADVISORY_LOCK_KEY = 4353333856519384237

_OLD_VERIFICATION_STATUS = "status IN ('pending', 'in_review', 'verified', 'rejected')"
_NEW_VERIFICATION_STATUS = (
    "status IN ('pending', 'in_review', 'verified', 'rejected', 'expired', 'revoked')"
)
_OLD_GUARDIAN_STATUS = "status IN ('pending', 'sent', 'verified', 'rejected')"
_NEW_GUARDIAN_STATUS = (
    "status IN ('pending', 'sent', 'verified', 'rejected', 'revoked')"
)
_OLD_GUARDIAN_CONSISTENCY = (
    "(status = 'verified' AND verified = true) OR "
    "(status IN ('pending', 'sent', 'rejected') AND verified = false)"
)
_NEW_GUARDIAN_CONSISTENCY = (
    "(status = 'verified' AND verified = true) OR "
    "(status IN ('pending', 'sent', 'rejected', 'revoked') AND verified = false)"
)
_OLD_REGISTRATION_FINGERPRINT = (
    "((state IN ('pending', 'succeeded', 'failed', 'neutralized') AND "
    "request_fingerprint_version = 'v1' AND request_fingerprint IS NOT NULL "
    "AND length(request_fingerprint) = 64 AND "
    "length(replace(replace(replace(replace(replace(replace(replace(replace("
    "replace(replace(replace(replace(replace(replace(replace(replace("
    "request_fingerprint, '0', ''), '1', ''), '2', ''), '3', ''), '4', ''), "
    "'5', ''), '6', ''), '7', ''), '8', ''), '9', ''), 'a', ''), 'b', ''), "
    "'c', ''), 'd', ''), 'e', ''), 'f', '')) = 0) OR "
    "(state IN ('retired', 'erased') AND request_fingerprint IS NULL AND "
    "request_fingerprint_version IS NULL))"
)
_NEW_REGISTRATION_FINGERPRINT = _OLD_REGISTRATION_FINGERPRINT.replace(
    "request_fingerprint_version = 'v1'",
    "request_fingerprint_version IN ('v1', 'v2')",
)
_VERIFICATION_PROOF = (
    "(status = 'verified' AND verified_email_hash IS NOT NULL) OR "
    "(status <> 'verified' AND verified_email_hash IS NULL)"
)
_EXISTING_AUTHORITY_TABLES = (
    "student_profiles",
    "student_registrations",
    "auth_sessions",
    "student_verifications",
    "guardian_consents",
    "consents",
    "registration_idempotency_records",
)
_NEW_AUTHORITY_TABLES = (
    "student_profile_interests",
    "student_profile_goals",
    "auth_session_profile_prompts",
)


class Nyay5ProfileMigrationError(RuntimeError):
    """Sanitized migration rejection with no profile data or identifiers."""


class Nyay5ProfileDowngradeError(RuntimeError):
    """Downgrade would discard profile/session data or a new enum state."""


def _validate_postgres_table_authority(
    connection: Connection,
    table_names: tuple[str, ...],
) -> None:
    """Reject ambient PostgreSQL authority that can rewrite profile DML."""

    if connection.dialect.name != "postgresql":
        return
    names = tuple(dict.fromkeys(table_names))
    catalog = connection.execute(
        sa.text(
            "SELECT c.relname::text, c.relkind::text, c.relpersistence::text, "
            "c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname IN :table_names"
        ).bindparams(sa.bindparam("table_names", expanding=True)),
        {"table_names": names},
    ).all()
    if (
        {row[0] for row in catalog} != set(names)
        or len(catalog) != len(names)
        or any(
            row[1] != "r"
            or row[2] != "p"
            or bool(row[3])
            or bool(row[4])
            for row in catalog
        )
    ):
        raise Nyay5ProfileMigrationError(
            "NYAY-5 profile authority validation rejected"
        )

    drift_queries = (
        "SELECT count(*) FROM pg_catalog.pg_policy AS p "
        "JOIN pg_catalog.pg_class AS c ON c.oid = p.polrelid "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname IN :table_names",
        "SELECT count(*) FROM pg_catalog.pg_rewrite AS r "
        "JOIN pg_catalog.pg_class AS c ON c.oid = r.ev_class "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname IN :table_names "
        "AND r.rulename <> '_RETURN'",
        "SELECT count(*) FROM pg_catalog.pg_trigger AS t "
        "JOIN pg_catalog.pg_class AS c ON c.oid = t.tgrelid "
        "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'public' AND c.relname IN :table_names "
        "AND NOT t.tgisinternal",
    )
    for query in drift_queries:
        count = connection.scalar(
            sa.text(query).bindparams(
                sa.bindparam("table_names", expanding=True)
            ),
            {"table_names": names},
        )
        if type(count) is not int or count != 0:
            raise Nyay5ProfileMigrationError(
                "NYAY-5 profile authority validation rejected"
            )


def _timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    ]


def _lock(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        sa.text("SELECT pg_catalog.pg_advisory_xact_lock(:key)"),
        {"key": _PG_ADVISORY_LOCK_KEY},
    )
    connection.execute(
        sa.text(
            "LOCK TABLE student_profiles, student_registrations, auth_sessions, "
            "student_verifications, guardian_consents, consents, "
            "registration_idempotency_records IN ACCESS EXCLUSIVE MODE"
        )
    )


def _existing_inventory(connection: Connection) -> None:
    inspector = sa.inspect(connection)
    required = {
        "student_profiles",
        "student_registrations",
        "auth_sessions",
        "student_verifications",
        "guardian_consents",
        "consents",
        "registration_idempotency_records",
    }
    if not required <= set(inspector.get_table_names()):
        raise Nyay5ProfileMigrationError("NYAY-5 profile migration rejected unsafe schema")
    columns = {row["name"] for row in inspector.get_columns("student_profiles")}
    if {
        "city",
        "preferred_language",
        "pronouns",
        "profile_version",
    } & columns:
        raise Nyay5ProfileMigrationError("NYAY-5 profile migration rejected unsafe schema")
    verification_columns = {
        row["name"]
        for row in inspector.get_columns("student_verifications")
    }
    if "verified_email_hash" in verification_columns:
        raise Nyay5ProfileMigrationError(
            "NYAY-5 profile migration rejected unsafe schema"
        )
    if {
        "student_profile_interests",
        "student_profile_goals",
        "auth_session_profile_prompts",
    } & set(inspector.get_table_names()):
        raise Nyay5ProfileMigrationError("NYAY-5 profile migration rejected unsafe schema")
    _validate_postgres_table_authority(connection, _EXISTING_AUTHORITY_TABLES)
    missing_profiles = connection.scalar(
        sa.text(
            "SELECT count(*) FROM student_registrations AS registration "
            "LEFT JOIN student_profiles AS profile "
            "ON profile.registration_id = registration.id "
            "WHERE registration.deleted_at IS NULL "
            "AND registration.status <> 'deleted' AND profile.id IS NULL"
        )
    )
    if missing_profiles:
        raise Nyay5ProfileMigrationError("NYAY-5 profile migration rejected unsafe data")


def _create_value_table(table: str) -> None:
    op.create_table(
        table,
        sa.Column("profile_id", _UUID, nullable=False),
        sa.Column("value", sa.String(80), nullable=False),
        sa.Column("id", _UUID, nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["student_profiles.id"],
            name=f"fk_{table}_profile_id_student_profiles",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "profile_id", "value", name=f"uq_{table}_profile_id_value"
        ),
        sa.CheckConstraint(
            "length(value) >= 1 AND length(value) <= 80",
            name="value_length",
        ),
    )
    op.create_index(f"ix_{table}_profile_id", table, ["profile_id"])


def _replace_status_constraints(*, forward: bool) -> None:
    verification = _NEW_VERIFICATION_STATUS if forward else _OLD_VERIFICATION_STATUS
    guardian = _NEW_GUARDIAN_STATUS if forward else _OLD_GUARDIAN_STATUS
    consistency = (
        _NEW_GUARDIAN_CONSISTENCY if forward else _OLD_GUARDIAN_CONSISTENCY
    )
    with op.batch_alter_table("student_verifications") as batch:
        batch.drop_constraint(
            op.f(
                "ck_student_verifications_ck_student_verifications_status"
                if forward
                else "ck_student_verifications_status"
            ),
            type_="check",
        )
        batch.create_check_constraint(
            "status"
            if forward
            else op.f(
                "ck_student_verifications_ck_student_verifications_status"
            ),
            verification,
        )
    with op.batch_alter_table("guardian_consents") as batch:
        batch.drop_constraint(
            op.f("ck_guardian_consents_verified_matches_status"), type_="check"
        )
        batch.drop_constraint(
            op.f(
                "ck_guardian_consents_ck_guardian_consents_status"
                if forward
                else "ck_guardian_consents_status"
            ),
            type_="check",
        )
        batch.create_check_constraint(
            "status"
            if forward
            else op.f("ck_guardian_consents_ck_guardian_consents_status"),
            guardian,
        )
        batch.create_check_constraint("verified_matches_status", consistency)


def _replace_registration_fingerprint_constraint(*, forward: bool) -> None:
    expression = (
        _NEW_REGISTRATION_FINGERPRINT
        if forward
        else _OLD_REGISTRATION_FINGERPRINT
    )
    with op.batch_alter_table("registration_idempotency_records") as batch:
        batch.drop_constraint(
            op.f(
                "ck_registration_idempotency_records_request_fingerprint_shape"
            ),
            type_="check",
        )
        batch.create_check_constraint(
            op.f(
                "ck_registration_idempotency_records_request_fingerprint_shape"
            ),
            expression,
        )


def upgrade() -> None:
    connection = op.get_bind()
    _lock(connection)
    _existing_inventory(connection)

    with op.batch_alter_table("student_verifications") as batch:
        batch.add_column(
            sa.Column("verified_email_hash", sa.String(64), nullable=True)
        )

    with op.batch_alter_table("student_profiles") as batch:
        batch.add_column(sa.Column("city", sa.String(120), nullable=True))
        batch.add_column(
            sa.Column("preferred_language", sa.String(16), nullable=True)
        )
        batch.add_column(sa.Column("pronouns", sa.String(60), nullable=True))
        batch.add_column(
            sa.Column(
                "profile_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch.create_check_constraint(
            "preferred_language",
            "preferred_language IS NULL OR preferred_language IN ('en', 'hi')",
        )
        batch.create_check_constraint(
            "profile_version_positive", "profile_version >= 1"
        )

    _create_value_table("student_profile_interests")
    _create_value_table("student_profile_goals")
    op.create_table(
        "auth_session_profile_prompts",
        sa.Column("auth_session_id", _UUID, nullable=False),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", _UUID, nullable=False),
        *_timestamp_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_auth_session_profile_prompts"),
        sa.ForeignKeyConstraint(
            ["auth_session_id"],
            ["auth_sessions.id"],
            name="fk_auth_session_profile_prompts_auth_session_id_auth_sessions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "auth_session_id",
            name="uq_auth_session_profile_prompts_auth_session_id",
        ),
    )
    op.create_index(
        "ix_auth_session_profile_prompts_auth_session_id",
        "auth_session_profile_prompts",
        ["auth_session_id"],
    )
    _replace_status_constraints(forward=True)
    _replace_registration_fingerprint_constraint(forward=True)
    # No guardian proof-consumption ceremony or authoritative provenance
    # exists at this revision. Legacy positive row flags therefore cannot be
    # carried forward as authorization.
    connection.execute(
        sa.text(
            "UPDATE guardian_consents SET status = 'revoked', verified = false "
            "WHERE status = 'verified' OR verified = true"
        )
    )
    # Historical positive institutional rows predate the authorized reviewer
    # provenance bound to a profile version. Preserve no anonymous positive.
    connection.execute(
        sa.text(
            "UPDATE student_verifications SET status = 'revoked' "
            "WHERE status = 'verified'"
        )
    )
    with op.batch_alter_table("student_verifications") as batch:
        batch.create_check_constraint(
            "verified_email_proof",
            _VERIFICATION_PROOF,
        )
    _validate_postflight(connection, head=False)


def _check_columns(
    inspector: sa.Inspector,
    table: str,
    expected: dict[str, tuple[bool, type, int | None]],
) -> None:
    reflected = {row["name"]: row for row in inspector.get_columns(table)}
    for name, (nullable, kind, length) in expected.items():
        column = reflected.get(name)
        if column is None or bool(column["nullable"]) is not nullable:
            raise Nyay5ProfileMigrationError("NYAY-5 profile schema validation rejected")
        type_matches = isinstance(column["type"], kind)
        if kind is sa.Uuid and inspector.bind.dialect.name == "sqlite":
            type_matches = (
                isinstance(column["type"], sa.CHAR)
                and column["type"].length == 32
            )
        if not type_matches:
            raise Nyay5ProfileMigrationError("NYAY-5 profile schema validation rejected")
        if length is not None and getattr(column["type"], "length", None) != length:
            raise Nyay5ProfileMigrationError("NYAY-5 profile schema validation rejected")


def _canonical_check(expression: str) -> str:
    return " ".join(expression.lower().split())


def _check_constraint(
    inspector: sa.Inspector,
    table: str,
    name: str,
    expression: str,
) -> None:
    if inspector.bind.dialect.name == "postgresql":
        connection = inspector.bind
        preparer = connection.dialect.identifier_preparer
        quoted_table = preparer.quote_identifier(table)
        temp_table = preparer.quote_identifier("_nyay5_expected_check")
        expected_name = "_nyay5_expected_check_constraint"
        quoted_expected_name = preparer.quote_identifier(expected_name)
        actual = connection.scalar(
            sa.text(
                "SELECT pg_catalog.pg_get_constraintdef(c.oid, true) "
                "FROM pg_catalog.pg_constraint AS c "
                "JOIN pg_catalog.pg_class AS r ON r.oid = c.conrelid "
                "JOIN pg_catalog.pg_namespace AS n ON n.oid = r.relnamespace "
                "WHERE n.nspname = 'public' AND r.relname = :table_name "
                "AND c.conname = :constraint_name AND c.contype = 'c'"
            ),
            {"table_name": table, "constraint_name": name},
        )
        if not isinstance(actual, str):
            raise Nyay5ProfileMigrationError(
                "NYAY-5 profile schema validation rejected"
            )
        connection.execute(
            sa.text(f"DROP TABLE IF EXISTS pg_temp.{temp_table}")
        )
        try:
            # Ask the target PostgreSQL server to parse the expected source on
            # a transaction-local table with the exact live column types. This
            # yields the same pg_get_constraintdef representation as the real
            # constraint (including IN -> ANY and type casts) without executing
            # the ambient constraint or weakening comparison to string tokens.
            connection.execute(
                sa.text(
                    f"CREATE TEMP TABLE pg_temp.{temp_table} "
                    f"(LIKE public.{quoted_table}) ON COMMIT DROP"
                )
            )
            connection.execute(
                sa.text(
                    f"ALTER TABLE pg_temp.{temp_table} "
                    f"ADD CONSTRAINT {quoted_expected_name} CHECK ({expression})"
                )
            )
            expected = connection.scalar(
                sa.text(
                    "SELECT pg_catalog.pg_get_constraintdef(c.oid, true) "
                    "FROM pg_catalog.pg_constraint AS c "
                    "JOIN pg_catalog.pg_class AS r ON r.oid = c.conrelid "
                    "JOIN pg_catalog.pg_namespace AS n ON n.oid = r.relnamespace "
                    "WHERE n.oid = pg_catalog.pg_my_temp_schema() "
                    "AND r.relname = :table_name "
                    "AND c.conname = :constraint_name AND c.contype = 'c'"
                ),
                {
                    "table_name": "_nyay5_expected_check",
                    "constraint_name": expected_name,
                },
            )
        finally:
            connection.execute(
                sa.text(f"DROP TABLE IF EXISTS pg_temp.{temp_table}")
            )
        if not isinstance(expected, str) or _canonical_check(
            actual
        ) != _canonical_check(expected):
            raise Nyay5ProfileMigrationError(
                "NYAY-5 profile schema validation rejected"
            )
        return
    checks = {
        str(row.get("name")): _canonical_check(str(row.get("sqltext") or ""))
        for row in inspector.get_check_constraints(table)
    }
    if checks.get(name) != _canonical_check(expression):
        raise Nyay5ProfileMigrationError(
            "NYAY-5 profile schema validation rejected"
        )


def _validate_new_table_catalog(inspector: sa.Inspector, table: str) -> None:
    """Pin the complete normalized-table catalog used by authenticated head checks."""

    prompt = table == "auth_session_profile_prompts"
    if table not in _NEW_AUTHORITY_TABLES:
        raise Nyay5ProfileMigrationError(
            "NYAY-5 profile schema validation rejected"
        )
    parent_column = "auth_session_id" if prompt else "profile_id"
    parent_table = "auth_sessions" if prompt else "student_profiles"
    expected_columns = {
        parent_column: (False, sa.Uuid, None),
        **(
            {"dismissed_at": (False, sa.DateTime, None)}
            if prompt
            else {"value": (False, sa.String, 80)}
        ),
        "id": (False, sa.Uuid, None),
        "created_at": (False, sa.DateTime, None),
        "updated_at": (False, sa.DateTime, None),
        "deleted_at": (True, sa.DateTime, None),
        "metadata_json": (True, sa.JSON, None),
    }
    columns = {row["name"]: row for row in inspector.get_columns(table)}
    if set(columns) != set(expected_columns):
        raise Nyay5ProfileMigrationError(
            "NYAY-5 profile schema validation rejected"
        )
    _check_columns(inspector, table, expected_columns)
    if inspector.bind.dialect.name == "postgresql" and any(
        getattr(columns[name]["type"], "timezone", None) is not True
        for name in ("created_at", "updated_at", "deleted_at")
    ):
        raise Nyay5ProfileMigrationError(
            "NYAY-5 profile schema validation rejected"
        )

    expected_fk = f"fk_{table}_{parent_column}_{parent_table}"
    expected_uq = (
        f"uq_{table}_{parent_column}"
        if prompt
        else f"uq_{table}_profile_id_value"
    )
    expected_uq_columns = (
        [parent_column] if prompt else ["profile_id", "value"]
    )
    primary_key = inspector.get_pk_constraint(table)
    foreign_keys = inspector.get_foreign_keys(table)
    uniques = inspector.get_unique_constraints(table)
    explicit_indexes = [
        row
        for row in inspector.get_indexes(table)
        if not row.get("duplicates_constraint")
    ]
    index_unique = (
        explicit_indexes[0].get("unique")
        if len(explicit_indexes) == 1
        else None
    )
    if not (
        primary_key.get("name") == f"pk_{table}"
        and primary_key.get("constrained_columns") == ["id"]
        and len(foreign_keys) == 1
        and foreign_keys[0].get("name") == expected_fk
        and foreign_keys[0].get("constrained_columns") == [parent_column]
        and foreign_keys[0].get("referred_table") == parent_table
        and foreign_keys[0].get("referred_columns") == ["id"]
        and str(
            foreign_keys[0].get("options", {}).get("ondelete", "")
        ).upper()
        == "CASCADE"
        and len(uniques) == 1
        and uniques[0].get("name") == expected_uq
        and uniques[0].get("column_names") == expected_uq_columns
        and len(explicit_indexes) == 1
        and explicit_indexes[0].get("name")
        == f"ix_{table}_{parent_column}"
        and explicit_indexes[0].get("column_names") == [parent_column]
        and (index_unique is False or index_unique == 0)
    ):
        raise Nyay5ProfileMigrationError(
            "NYAY-5 profile schema validation rejected"
        )

    checks = inspector.get_check_constraints(table)
    expected_check = f"ck_{table}_value_length"
    if prompt:
        if checks:
            raise Nyay5ProfileMigrationError(
                "NYAY-5 profile schema validation rejected"
            )
        return
    if {row.get("name") for row in checks} != {expected_check}:
        raise Nyay5ProfileMigrationError(
            "NYAY-5 profile schema validation rejected"
        )
    _check_constraint(
        inspector,
        table,
        expected_check,
        "length(value) >= 1 AND length(value) <= 80",
    )


def _validate_postflight(connection: Connection, *, head: bool) -> None:
    """Validate the exact new boundary before the migration may commit."""

    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    additions = {
        "student_profile_interests",
        "student_profile_goals",
        "auth_session_profile_prompts",
    }
    if not additions <= tables:
        raise Nyay5ProfileMigrationError("NYAY-5 profile schema validation rejected")
    _validate_postgres_table_authority(
        connection, _EXISTING_AUTHORITY_TABLES + _NEW_AUTHORITY_TABLES
    )
    _check_columns(
        inspector,
        "student_profiles",
        {
            "city": (True, sa.String, 120),
            "preferred_language": (True, sa.String, 16),
            "pronouns": (True, sa.String, 60),
            "profile_version": (False, sa.Integer, None),
        },
    )
    _check_columns(
        inspector,
        "student_verifications",
        {"verified_email_hash": (True, sa.String, 64)},
    )
    _check_constraint(
        inspector,
        "student_verifications",
        "ck_student_verifications_status",
        _NEW_VERIFICATION_STATUS,
    )
    _check_constraint(
        inspector,
        "student_verifications",
        "ck_student_verifications_verified_email_proof",
        _VERIFICATION_PROOF,
    )
    _check_constraint(
        inspector,
        "guardian_consents",
        "ck_guardian_consents_status",
        _NEW_GUARDIAN_STATUS,
    )
    _check_constraint(
        inspector,
        "guardian_consents",
        "ck_guardian_consents_verified_matches_status",
        _NEW_GUARDIAN_CONSISTENCY,
    )
    _check_constraint(
        inspector,
        "registration_idempotency_records",
        "ck_registration_idempotency_records_request_fingerprint_shape",
        _NEW_REGISTRATION_FINGERPRINT,
    )
    for table in _NEW_AUTHORITY_TABLES:
        _validate_new_table_catalog(inspector, table)
    invalid_versions = connection.scalar(
        sa.text("SELECT count(*) FROM student_profiles WHERE profile_version < 1")
    )
    if invalid_versions:
        raise Nyay5ProfileMigrationError("NYAY-5 profile schema validation rejected")
    unproven_guardian_positives = connection.scalar(
        sa.text(
            "SELECT count(*) FROM guardian_consents "
            "WHERE status = 'verified' OR verified = true"
        )
    )
    if unproven_guardian_positives:
        raise Nyay5ProfileMigrationError(
            "NYAY-5 guardian authority validation rejected"
        )
    unproven_verification_positives = connection.scalar(
        sa.text(
            "SELECT count(*) FROM student_verifications AS verification "
            "LEFT JOIN student_profiles AS profile "
            "ON profile.registration_id = verification.registration_id "
            "WHERE (verification.status = 'verified' AND "
            "(verification.verified_email_hash IS NULL OR "
            "profile.institutional_email_hash IS NULL OR "
            "verification.verified_email_hash <> profile.institutional_email_hash)) "
            "OR (verification.status <> 'verified' AND "
            "verification.verified_email_hash IS NOT NULL)"
        )
    )
    if unproven_verification_positives:
        raise Nyay5ProfileMigrationError(
            "NYAY-5 verification authority validation rejected"
        )
    if head:
        revision_value = connection.scalar(
            sa.text("SELECT version_num FROM alembic_version")
        )
        if revision_value != revision:
            raise Nyay5ProfileMigrationError("NYAY-5 profile head validation rejected")


def _downgrade_is_lossless(connection: Connection) -> None:
    probes = (
        "SELECT count(*) FROM student_profile_interests",
        "SELECT count(*) FROM student_profile_goals",
        "SELECT count(*) FROM auth_session_profile_prompts",
        "SELECT count(*) FROM student_profiles WHERE city IS NOT NULL "
        "OR preferred_language IS NOT NULL OR pronouns IS NOT NULL "
        "OR profile_version <> 1",
        "SELECT count(*) FROM student_verifications "
        "WHERE status IN ('expired', 'revoked')",
        "SELECT count(*) FROM student_verifications "
        "WHERE verified_email_hash IS NOT NULL",
        "SELECT count(*) FROM guardian_consents WHERE status = 'revoked'",
        "SELECT count(*) FROM registration_idempotency_records "
        "WHERE request_fingerprint_version = 'v2'",
    )
    if any(connection.scalar(sa.text(query)) for query in probes):
        raise Nyay5ProfileDowngradeError(
            "NYAY-5 downgrade rejected retained profile or lifecycle state"
        )


def downgrade() -> None:
    connection = op.get_bind()
    _lock(connection)
    _validate_postflight(connection, head=False)
    _downgrade_is_lossless(connection)
    _replace_registration_fingerprint_constraint(forward=False)
    with op.batch_alter_table("student_verifications") as batch:
        batch.drop_constraint(
            op.f("ck_student_verifications_verified_email_proof"),
            type_="check",
        )
        batch.drop_column("verified_email_hash")
    _replace_status_constraints(forward=False)
    op.drop_index(
        "ix_auth_session_profile_prompts_auth_session_id",
        table_name="auth_session_profile_prompts",
    )
    op.drop_table("auth_session_profile_prompts")
    for table in ("student_profile_goals", "student_profile_interests"):
        op.drop_index(f"ix_{table}_profile_id", table_name=table)
        op.drop_table(table)
    with op.batch_alter_table("student_profiles") as batch:
        batch.drop_constraint(
            op.f("ck_student_profiles_profile_version_positive"), type_="check"
        )
        batch.drop_constraint(
            op.f("ck_student_profiles_preferred_language"), type_="check"
        )
        batch.drop_column("profile_version")
        batch.drop_column("pronouns")
        batch.drop_column("preferred_language")
        batch.drop_column("city")
