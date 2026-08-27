"""Alembic environment. Pulls the DB URL from application settings and targets
the shared declarative metadata so future models autogenerate cleanly."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.base import Base
from app.db.migration_release_guard import (
    APPLICATION_HEAD_REVISION,
    MigrationApprovalError,
    NYAY5_REVISION,
    enforce_nyay19_migration_postflight,
    enforce_nyay19_migration_release_guard,
    install_authenticated_migration_loader,
    runtime_migration_intent,
    source_authority_is_valid,
)

# Import model modules so their tables register on Base.metadata for autogenerate
# and for `alembic upgrade head` (SAATHI-366/448 registration schema).
import app.db.models.audit  # noqa: E402,F401
import app.models  # noqa: E402,F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    # Offline SQL cannot prove the live revision, target identity, transaction,
    # privacy-zero state, or authenticated direct-child parentage. It is
    # deliberately outside the authenticated path and therefore fails closed.
    raise MigrationApprovalError(
        "NYAY migration offline execution is not authorized; refusing to migrate"
    )


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = settings.database_url
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        options = {
            "connection": connection,
            "target_metadata": target_metadata,
            "compare_type": True,
        }
        if connection.dialect.name == "sqlite":
            # Revisions 0018+ explicitly open a real DBAPI transaction before
            # its first DDL. Tell Alembic to own/commit-or-roll-back that
            # transaction so SQLite batch DDL cannot leave a partial revision.
            options.update(transactional_ddl=True, transaction_per_migration=True)
        context.configure(**options)
        with context.begin_transaction():
            # Approval is bound to a freshly recomputed, locked live-state
            # report inside the very transaction that applies 0020.  This
            # closes the preflight-to-execution race for privacy freeze data.
            authenticate_loaded_migrations = enforce_nyay19_migration_release_guard(
                config,
                connection,
                environment=settings.app_env,
                runtime_intent=runtime_migration_intent(context),
            )
            restore_loader = None
            if authenticate_loaded_migrations:
                restore_loader = install_authenticated_migration_loader()
            try:
                context.run_migrations()
                if authenticate_loaded_migrations:
                    # Re-lock and re-prove exact head/catalog/privacy state
                    # inside Alembic's transaction, before its context exits
                    # and can commit the irreversible transition.
                    requested_revision = getattr(
                        getattr(config, "cmd_opts", None), "revision", None
                    )
                    if requested_revision in {
                        APPLICATION_HEAD_REVISION,
                        "head",
                    }:
                        expected_revision = APPLICATION_HEAD_REVISION
                    elif requested_revision == NYAY5_REVISION:
                        expected_revision = NYAY5_REVISION
                    else:
                        expected_revision = "0020_auth_retention_lifecycle"
                    if expected_revision == "0020_auth_retention_lifecycle":
                        # Preserve the sealed NYAY-19 postflight call and its
                        # source-bound operations contract verbatim.
                        enforce_nyay19_migration_postflight(connection)
                    else:
                        enforce_nyay19_migration_postflight(
                            connection, expected_revision=expected_revision
                        )
                if (
                    authenticate_loaded_migrations
                    and not source_authority_is_valid()
                ):
                    raise MigrationApprovalError(
                        "NYAY-19 migration source authority rejected; "
                        "refusing to migrate"
                    )
            finally:
                if restore_loader is not None:
                    restore_loader()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
