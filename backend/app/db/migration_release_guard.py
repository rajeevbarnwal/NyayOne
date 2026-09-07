"""Fail-closed release approval boundary for the NYAY-19 migration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import types
from typing import Any, Mapping

from alembic import command as alembic_command
from sqlalchemy import text
from sqlalchemy.engine import Connection, URL
from sqlalchemy.exc import SQLAlchemyError


PARENT_REVISION = "0019_otp_security_authority"
TARGET_REVISION = "0020_auth_retention_lifecycle"
TARGET_SOURCE_SHA256 = (
    "8b462f0d35839a0edd7166f4e5881fafaeb368f8816cba673144d3c745270dbe"
)
TARGET_SOURCE_PATH = (
    Path(__file__).resolve().parent
    / "migrations/versions/0020_auth_retention_lifecycle.py"
)
NYAY5_REVISION = "0021_nyay5_profile_boundary"
NYAY5_SOURCE_SHA256 = (
    "439de03dc431a73264db706f77ffb703541619db1f490760d6d685aa173c7c50"
)
NYAY5_SOURCE_PATH = (
    Path(__file__).resolve().parent
    / "migrations/versions/0021_nyay5_profile_boundary.py"
)
NYAY9_REVISION = "0022_nyay9_owner_profile_api"
NYAY9_SOURCE_SHA256 = (
    "e66fcfd7ac270569e05fde17c0563ec7d0245023d8ab9f1c87d941373eb1653a"
)
NYAY9_SOURCE_PATH = (
    Path(__file__).resolve().parent
    / "migrations/versions/0022_nyay9_owner_profile_api.py"
)
NYAY22_REVISION = "0023_nyay22_mentor_ceremony"
NYAY22_SOURCE_SHA256 = (
    "d2a221b00ff785c2748cd7394a57da4cfd34596806078ccc815244626dcb7ce1"
)
NYAY22_SOURCE_PATH = (
    Path(__file__).resolve().parent
    / "migrations/versions/0023_nyay22_mentor_ceremony.py"
)
NYAY11_REVISION = "0024_nyay11_authority_state"
NYAY11_SOURCE_SHA256 = (
    "9e654c22ea584029685746d64ef547b7734b0a9dc5926c23afadba49bf07bf4c"
)
NYAY11_SOURCE_PATH = (
    Path(__file__).resolve().parent
    / "migrations/versions/0024_nyay11_authority_state.py"
)
APPLICATION_HEAD_REVISION = "0025_nyay12_email_identity"
APPLICATION_HEAD_SOURCE_SHA256 = (
    "711ae36e55b66d7050d4acf9781f56fb6de09c918f02e4eacddcedc7ef7d6154"
)
APPLICATION_HEAD_SOURCE_PATH = (
    Path(__file__).resolve().parent
    / "migrations/versions/0025_nyay12_email_identity.py"
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VERSIONS_PATH = TARGET_SOURCE_PATH.parent
MIGRATION_LEDGER_VERIFIER = REPOSITORY_ROOT / "scripts/ci/verify_migration_ledger.py"
HISTORICAL_SOURCE_SHA256 = {
    "0024_nyay11_authority_state.py": (
        "9e654c22ea584029685746d64ef547b7734b0a9dc5926c23afadba49bf07bf4c"
    ),
    "0001_initial_pgvector.py": (
        "0fcdb6c94a2f31023b262aa7aa1720c9503ad6cf587fadb7c34c74dbda8ed3b6"
    ),
    "0002_registration_schema.py": (
        "7af72ddf1f2fb0b62c6cdee96118f0611ad7651747a1345838182d5e4b3bbaec"
    ),
    "0003_registration_security_lifecycle.py": (
        "78b9c4b615e22ab16ea117f276b1c6650d824ddf79a93e152ef61fdfd4b43546"
    ),
    "0004_wave1_foundation.py": (
        "385bb1379543a6218642c6ef6f7edf61721a16ce5472a218008d562a39a908e5"
    ),
    "0005_language_check.py": (
        "40aade919fbe7ea2e9d03901be6969e8ef2799203408f27e6ede1473811fb85f"
    ),
    "0006_lawschool_fact_backfill.py": (
        "a2df7ac37926b10f24a7c621715de2cf4e10a2c1a3deb7af34a95ccd5698764a"
    ),
    "0007_wave3_credentials.py": (
        "da63e6166fb0c1d5598c94e22477cb76903b939c7997996827643c2725c267a8"
    ),
    "0008_wave2_tutoring.py": (
        "fff836ccc283f267568def3c2e5f6962bdda1b4f3e016a1aad77933dfa2c50a8"
    ),
    "0009_wave2_session_pricing.py": (
        "6c6bf34dfe78bc45b82eb3a2418450c0e61e48acf09fb21c42503cd2b308ceb0"
    ),
    "0010_student_login_session.py": (
        "cbc4cc7e41106eebc79f5cc0cf81a0c4a2b4901a9da55e33fba1e158916cbed6"
    ),
    "0011_wave4_private_reporting.py": (
        "4feee798862880a5c49d2d188706c7724a7f0f367e26a6e5ed203731a2ea5774"
    ),
    "0012_wave4_moderation.py": (
        "aea2c15c9858c6ea5f2823a9092b3f586f5f8974cdfa603d8e72338433423dbc"
    ),
    "0013_wave5_calendar_interop.py": (
        "8a9f60b367eeeed423dd37eeb9e91b6602c07ccca3259354a2ba54b6542e9b30"
    ),
    "0014_saathi60_internships.py": (
        "3fe141f2b45e16d21377d25e7ca99f0015580110c4f2c6fb04d252167718bc14"
    ),
    "0015_wave4_public_risk_labels.py": (
        "5b8c01093d062c7281029514ba27c075f0a4f898fb0d078f9dab02243d4f4c6f"
    ),
    "0016_dob_hash_reconcile.py": (
        "b483bad2e23abbd0087856b06cc53fb54021baa2a397c295f3021caf1da0cef6"
    ),
    "0017_registration_invariants.py": (
        "f7b0420779699ceb555ad9ce35016cc8ce7fed9042fe23c44234d6b5eefd03a5"
    ),
    "0018_registration_idempotency.py": (
        "5678a9b2117c5e0397a40052731563e4b5b09664f73f9874b3239c235bb7a862"
    ),
    "0019_otp_security_authority.py": (
        "3513d5400295fb424a6b84e3325286a45c8c57192d5ef91f98ce884d691062d4"
    ),
}
ALL_MIGRATION_SOURCE_SHA256 = {
    **HISTORICAL_SOURCE_SHA256,
    TARGET_SOURCE_PATH.name: TARGET_SOURCE_SHA256,
    NYAY5_SOURCE_PATH.name: NYAY5_SOURCE_SHA256,
    NYAY9_SOURCE_PATH.name: NYAY9_SOURCE_SHA256,
    NYAY22_SOURCE_PATH.name: NYAY22_SOURCE_SHA256,
    APPLICATION_HEAD_SOURCE_PATH.name: APPLICATION_HEAD_SOURCE_SHA256,
}
IRREVERSIBLE_FREEZE_ACK = (
    "I_ACKNOWLEDGE_NYAY19_PRIVACY_FREEZE_IS_IRREVERSIBLE"
)
PREFLIGHT_PATH_ENV = "NYAY19_APPROVED_PREFLIGHT_REPORT"
PREFLIGHT_SHA_ENV = "NYAY19_APPROVED_PREFLIGHT_SHA256"
CHANGE_REFERENCE_ENV = "NYAY19_MAINTENANCE_CHANGE_REFERENCE"
APPROVAL_WINDOW_END_ENV = "NYAY19_APPROVAL_WINDOW_ENDS_AT"
FREEZE_ACK_ENV = "NYAY19_IRREVERSIBLE_FREEZE_ACK"
ISOLATED_EXECUTION_ENV = "NYAY19_ISOLATED_MIGRATION_EXECUTE"
FORCE_APPROVAL_ENV = "NYAY19_FORCE_MIGRATION_APPROVAL"

AUTHORITY_TABLES = (
    "data_subject_requests",
    "deletion_jobs",
    "users",
    "student_registrations",
    "login_attempts",
    "auth_sessions",
    "audit_events",
)
AGGREGATE_KEYS = (
    "accepted_deletion_subjects",
    "accounts_to_suspend",
    "registrations_to_suspend",
    "active_sessions_to_revoke",
    "login_attempt_rows",
    "auth_session_rows",
    "locked_relation_bytes",
)
STATE_KEYS = (
    "parent_revision",
    "target_revision",
    "postgres_major",
    "pgvector_present",
    "change_reference",
    "approval_window_ends_at",
    "preflight_observed_at",
    "target_source_sha256",
    "target_fingerprint",
    "authority_state_digest",
    "aggregates",
)
REPORT_KEYS = (
    "verdict",
    "code",
    *STATE_KEYS,
    "state_fingerprint",
)

_LOCAL_ENVIRONMENTS = {"development", "dev", "local", "test", "testing"}
_ISOLATED_DATABASE_MARKERS = {
    "ci",
    "gate",
    "nyay2",
    "nyay3",
    "nyay4",
    "nyay5",
    "nyay9",
    "nyay11",
    "nyay12",
    "nyay16",
    "nyay17",
    "nyay19",
    "nyay22",
    "qa",
    "scratch",
    "test",
    "testing",
    "w2gate",
}
_NONISOLATED_DATABASE_MARKERS = {"prod", "production", "stage", "staging"}
_ISOLATED_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)
_LIBPQ_ROUTING_ENVIRONMENT = {
    "PGDATABASE",
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGSERVICE",
    "PGSERVICEFILE",
}
_LOWER_SHA256 = re.compile(r"[0-9a-f]{64}")
_CHANGE_REFERENCE = re.compile(r"[A-Z0-9][A-Z0-9._/-]{2,127}")
_UTC_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
)
_MAX_APPROVAL_WINDOW = timedelta(hours=24)
_MAX_REPORT_BYTES = 64 * 1024
_MAX_MIGRATION_SOURCE_BYTES = 2 * 1024 * 1024
_DEFAULT_POSTGRES_PORT = 5432
_ENDPOINT_ROUTING_QUERY_KEYS = {
    "database",
    "dbname",
    "host",
    "hostaddr",
    "port",
    "service",
    "servicefile",
}
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_READ_ONLY_COMMANDS = {
    alembic_command.check: "check",
    alembic_command.current: "current",
}
_RUNTIME_OPERATIONS = {
    "check.<locals>.retrieve_migrations": "check",
    "current.<locals>.display_version": "current",
    "downgrade.<locals>.downgrade": "downgrade",
    "stamp.<locals>.do_stamp": "stamp",
    "upgrade.<locals>.upgrade": "upgrade",
}

_ACCEPTED_SUBJECTS_SQL = (
    "SELECT DISTINCT dsr.user_id FROM public.data_subject_requests AS dsr "
    "JOIN public.deletion_jobs AS job ON job.request_id = dsr.id "
    "WHERE dsr.kind = 'delete' AND dsr.reauth_verified = true "
    "AND dsr.status IN ('pending','processing','complete','failed')"
)


class MigrationApprovalError(RuntimeError):
    """Raised without secret-bearing details when approval is invalid."""


class MigrationTargetNotAuthoritative(RuntimeError):
    """The connected runtime cannot provide PostgreSQL-16 proof."""


@dataclass(frozen=True)
class RuntimeMigrationIntent:
    """Intent independently observed from Alembic's active runtime context."""

    operation: str | None
    destination_revision: object
    as_sql: bool
    tag: object
    dont_mutate: bool


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def state_fingerprint(report: Mapping[str, Any]) -> str:
    """Recompute the exact approved-state fingerprint from report fields."""

    state = {name: report[name] for name in STATE_KEYS}
    return hashlib.sha256(_canonical_json(state)).hexdigest()


def _parse_utc_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or _UTC_TIMESTAMP.fullmatch(value) is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def approval_inputs_are_canonical(
    change_reference: Any,
    approval_window_ends_at: Any,
) -> bool:
    return bool(
        isinstance(change_reference, str)
        and _CHANGE_REFERENCE.fullmatch(change_reference) is not None
        and _parse_utc_timestamp(approval_window_ends_at) is not None
    )


def _approval_metadata_is_exact(report: Mapping[str, Any]) -> bool:
    if not approval_inputs_are_canonical(
        report.get("change_reference"),
        report.get("approval_window_ends_at"),
    ):
        return False
    observed = _parse_utc_timestamp(report.get("preflight_observed_at"))
    window_end = _parse_utc_timestamp(report.get("approval_window_ends_at"))
    if observed is None or window_end is None:
        return False
    duration = window_end - observed
    return timedelta(0) < duration <= _MAX_APPROVAL_WINDOW


def _approval_window_is_current(
    report: Mapping[str, Any],
    now: datetime,
) -> bool:
    if not _approval_metadata_is_exact(report):
        return False
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        return False
    observed = _parse_utc_timestamp(report["preflight_observed_at"])
    window_end = _parse_utc_timestamp(report["approval_window_ends_at"])
    if observed is None or window_end is None:
        return False
    current = now.astimezone(timezone.utc)
    return observed <= current < window_end


def _stable_file_sha256(path: Path) -> str | None:
    if not path.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        return None
    descriptor: int | None = None
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            return None
        digest = hashlib.sha256()
        while True:
            chunk = os.read(descriptor, 64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mode != after.st_mode
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            return None
        return digest.hexdigest()
    except (OSError, TypeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _stable_source_bytes(path: Path) -> bytes | None:
    """Read one bounded regular source inode without following links."""

    if not path.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        return None
    descriptor: int | None = None
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 0 < before.st_size <= _MAX_MIGRATION_SOURCE_BYTES
        ):
            return None
        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mode != after.st_mode
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            return None
        return payload
    except (OSError, TypeError, ValueError):
        return None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def target_source_is_exact() -> bool:
    """Validate the frozen 0020 bytes without following a symlink."""

    observed = _stable_file_sha256(TARGET_SOURCE_PATH)
    return observed is not None and hmac.compare_digest(
        observed,
        TARGET_SOURCE_SHA256,
    )


def source_authority_is_valid() -> bool:
    """Verify exact 0001-0023 bytes, inventory, graph and baseline ledger."""

    expected_names = set(ALL_MIGRATION_SOURCE_SHA256)
    try:
        if VERSIONS_PATH.is_symlink() or not VERSIONS_PATH.is_dir():
            return False
        observed_names = {
            candidate.name
            for candidate in VERSIONS_PATH.iterdir()
            if candidate.suffix == ".py" and candidate.name != "__init__.py"
        }
        if observed_names != expected_names:
            return False
        for filename, expected in ALL_MIGRATION_SOURCE_SHA256.items():
            observed = _stable_file_sha256(VERSIONS_PATH / filename)
            if observed is None or not hmac.compare_digest(observed, expected):
                return False
        if (
            not MIGRATION_LEDGER_VERIFIER.is_file()
            or MIGRATION_LEDGER_VERIFIER.is_symlink()
        ):
            return False
        completed = subprocess.run(
            [sys.executable, str(MIGRATION_LEDGER_VERIFIER)],
            cwd=REPOSITORY_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        return completed.returncode == 0 and target_source_is_exact()
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        return False


def _load_authenticated_migration_module(
    module_id: str,
    path: Path,
    expected_sha256: str,
) -> types.ModuleType:
    """Compile authenticated source bytes directly, never cached bytecode."""

    source = _stable_source_bytes(path)
    if source is None or not hmac.compare_digest(
        hashlib.sha256(source).hexdigest(),
        expected_sha256,
    ):
        raise MigrationApprovalError(
            "NYAY-19 migration source authority rejected; refusing to migrate"
        )
    try:
        code = compile(source, str(path), "exec", dont_inherit=True)
        module = types.ModuleType(module_id)
        module.__file__ = str(path)
        module.__package__ = ""
        exec(code, module.__dict__)
    except Exception:
        raise MigrationApprovalError(
            "NYAY-19 migration source authority rejected; refusing to migrate"
        ) from None
    return module


def install_authenticated_migration_loader() -> Any:
    """Install an exact-source Alembic loader and return its restoration hook."""

    from alembic.util import pyfiles

    original = pyfiles.load_module_py
    versions = VERSIONS_PATH.resolve()

    def load_exact(module_id: str, raw_path: Any) -> types.ModuleType:
        path = Path(raw_path)
        try:
            parent = path.parent.resolve(strict=True)
        except OSError:
            parent = Path()
        if parent != versions or path.suffix != ".py":
            raise MigrationApprovalError(
                "NYAY-19 migration source authority rejected; refusing to migrate"
            )
        expected = ALL_MIGRATION_SOURCE_SHA256.get(path.name)
        if expected is None:
            raise MigrationApprovalError(
                "NYAY-19 migration source authority rejected; refusing to migrate"
            )
        return _load_authenticated_migration_module(module_id, path, expected)

    pyfiles.load_module_py = load_exact

    def restore() -> None:
        pyfiles.load_module_py = original

    return restore


def runtime_migration_intent(context_source: Any) -> RuntimeMigrationIntent:
    """Read mutation intent from the active Alembic EnvironmentContext."""

    invalid = RuntimeMigrationIntent(None, None, False, None, False)
    try:
        options = context_source.get_context().opts
        function = options.get("fn")
        operation = None
        if getattr(function, "__module__", None) == "alembic.command":
            operation = _RUNTIME_OPERATIONS.get(
                getattr(function, "__qualname__", "")
            )
        as_sql = options.get("as_sql")
        if type(as_sql) is not bool:
            return invalid
        return RuntimeMigrationIntent(
            operation=operation,
            destination_revision=options.get("destination_rev"),
            as_sql=as_sql,
            tag=options.get("tag"),
            dont_mutate=options.get("dont_mutate") is True,
        )
    except (AttributeError, KeyError, TypeError):
        return invalid


def _command(config: Any) -> Any | None:
    options = getattr(config, "cmd_opts", None)
    metadata = getattr(options, "cmd", None)
    if not isinstance(metadata, tuple) or len(metadata) != 3:
        return None
    candidate = metadata[0]
    return candidate if callable(candidate) else None


def _database_tokens(url: URL) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", (url.database or "").casefold())
        if token
    }


def _database_name_has_forbidden_marker(url: URL) -> bool:
    database = url.database
    return bool(
        isinstance(database, str)
        and any(
            marker in database.casefold()
            for marker in _NONISOLATED_DATABASE_MARKERS
        )
    )


def _is_explicit_isolated_target(
    connection: Connection,
    *,
    environment: str,
    environ: Mapping[str, str],
) -> bool:
    dialect = connection.dialect.name
    normalized_environment = environment.strip().casefold()
    if dialect == "sqlite":
        return normalized_environment in _LOCAL_ENVIRONMENTS
    if dialect != "postgresql":
        return False
    if environ.get(ISOLATED_EXECUTION_ENV) != "1":
        return False
    if any(name in environ for name in _LIBPQ_ROUTING_ENVIRONMENT):
        return False
    if normalized_environment not in _LOCAL_ENVIRONMENTS | {"stage", "staging"}:
        return False
    url = getattr(getattr(connection, "engine", None), "url", None)
    host = getattr(url, "host", None)
    configured_port = getattr(url, "port", None)
    if not isinstance(host, str) or not host or "%" in host:
        return False
    try:
        configured_address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if not configured_address.is_loopback:
        return False
    if configured_port is not None and (
        type(configured_port) is not int or not 1 <= configured_port <= 65535
    ):
        return False
    # A libpq host/dbname/service query override can point somewhere entirely
    # different while URL.host/database still display the safe-looking values.
    # Disposable ticket gates do not need query parameters, so reject all of
    # them before considering the bypass.
    if getattr(url, "query", None):
        return False
    tokens = _database_tokens(url)
    # Production-like names must not become disposable merely by joining a
    # safe token to a forbidden substring (for example productionclone_qa or
    # stagecopy_nyay19).  The isolated path is intentionally stricter than a
    # token parser because a false negative could authorize irreversible DDL.
    if _database_name_has_forbidden_marker(url):
        return False
    if not tokens & _ISOLATED_DATABASE_MARKERS:
        return False
    try:
        row = connection.execute(
            text(
                "SELECT pg_catalog.current_database()::text, "
                "pg_catalog.host(pg_catalog.inet_server_addr())::text, "
                "pg_catalog.inet_server_port()::integer"
            )
        ).one()
        live_database, live_address, live_port = row
        if (
            not isinstance(live_address, str)
            or not live_address
            or live_address != live_address.strip()
            or "%" in live_address
        ):
            return False
        parsed_live_address = ipaddress.ip_address(live_address)
    except Exception:
        return False
    return bool(
        isinstance(live_database, str)
        and live_database == getattr(url, "database", None)
        and type(live_port) is int
        and 1 <= live_port <= 65535
        and not parsed_live_address.is_unspecified
        and not parsed_live_address.is_multicast
        and (
            parsed_live_address.is_loopback
            or any(
                parsed_live_address.version == network.version
                and parsed_live_address in network
                for network in _ISOLATED_PRIVATE_NETWORKS
            )
        )
    )


def _json_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _read_report_bytes(raw_path: str) -> bytes:
    path = Path(raw_path)
    if not path.is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        raise MigrationApprovalError(
            "NYAY-19 approved preflight is unavailable; refusing to migrate"
        )
    descriptor: int | None = None
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or not 0 < before.st_size <= _MAX_REPORT_BYTES
        ):
            raise OSError
        chunks: list[bytes] = []
        remaining = before.st_size + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 16 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(payload) != before.st_size
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_mode != after.st_mode
            or before.st_uid != after.st_uid
            or before.st_nlink != after.st_nlink
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
        ):
            raise OSError
        return payload
    except (OSError, TypeError, ValueError):
        raise MigrationApprovalError(
            "NYAY-19 approved preflight is unavailable; refusing to migrate"
        ) from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def _report_is_exact(report: Any) -> bool:
    if type(report) is not dict or set(report) != set(REPORT_KEYS):
        return False
    aggregates = report.get("aggregates")
    fingerprints = (
        report.get("target_fingerprint"),
        report.get("authority_state_digest"),
        report.get("state_fingerprint"),
    )
    if (
        report.get("verdict") != "PASS"
        or report.get("code") != "migration_ready"
        or report.get("parent_revision") != PARENT_REVISION
        or report.get("target_revision") != TARGET_REVISION
        or type(report.get("postgres_major")) is not int
        or report["postgres_major"] != 16
        or report.get("pgvector_present") is not True
        or not _approval_metadata_is_exact(report)
        or report.get("target_source_sha256") != TARGET_SOURCE_SHA256
        or not all(
            isinstance(value, str) and _LOWER_SHA256.fullmatch(value)
            for value in fingerprints
        )
        or type(aggregates) is not dict
        or set(aggregates) != set(AGGREGATE_KEYS)
        or not all(
            type(aggregates[name]) is int and aggregates[name] >= 0
            for name in AGGREGATE_KEYS
        )
    ):
        return False
    try:
        expected = state_fingerprint(report)
    except (KeyError, TypeError, ValueError):
        return False
    return hmac.compare_digest(report["state_fingerprint"], expected)


def _approved_report(environ: Mapping[str, str]) -> dict[str, Any]:
    raw_path = environ.get(PREFLIGHT_PATH_ENV, "")
    expected_sha = environ.get(PREFLIGHT_SHA_ENV, "")
    change_reference = environ.get(CHANGE_REFERENCE_ENV, "")
    approval_window_ends_at = environ.get(APPROVAL_WINDOW_END_ENV, "")
    acknowledgement = environ.get(FREEZE_ACK_ENV, "")
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or not isinstance(expected_sha, str)
        or _LOWER_SHA256.fullmatch(expected_sha) is None
        or not approval_inputs_are_canonical(
            change_reference,
            approval_window_ends_at,
        )
        or acknowledgement != IRREVERSIBLE_FREEZE_ACK
    ):
        raise MigrationApprovalError(
            "NYAY-19 migration approval is incomplete; refusing to migrate"
        )
    payload = _read_report_bytes(raw_path)
    if not hmac.compare_digest(hashlib.sha256(payload).hexdigest(), expected_sha):
        raise MigrationApprovalError(
            "NYAY-19 approved preflight digest changed; refusing to migrate"
        )
    try:
        report = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_json_without_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise MigrationApprovalError(
            "NYAY-19 approved preflight is invalid; refusing to migrate"
        ) from None
    if not _report_is_exact(report):
        raise MigrationApprovalError(
            "NYAY-19 approved preflight is invalid; refusing to migrate"
        )
    if not (
        hmac.compare_digest(report["change_reference"], change_reference)
        and hmac.compare_digest(
            report["approval_window_ends_at"],
            approval_window_ends_at,
        )
    ):
        raise MigrationApprovalError(
            "NYAY-19 migration approval metadata changed; refusing to migrate"
        )
    return report


def _count(connection: Connection, sql: str) -> int:
    value = connection.scalar(text(sql))
    if type(value) is not int or value < 0:
        raise RuntimeError("aggregate count rejected")
    return value


def _database_clock(connection: Connection) -> datetime:
    value = connection.scalar(text("SELECT pg_catalog.clock_timestamp()"))
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise RuntimeError("database clock rejected")
    return value.astimezone(timezone.utc)


def _canonical_observed_at(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _establish_public_authority(connection: Connection) -> None:
    if connection.dialect.name != "postgresql":
        raise MigrationTargetNotAuthoritative
    if connection.dialect.default_schema_name != "public":
        raise RuntimeError("schema authority rejected")
    for statement in (
        "SET LOCAL search_path = pg_catalog, public",
        "SET LOCAL TIME ZONE 'UTC'",
        "SET LOCAL DateStyle = 'ISO, YMD'",
        "SET LOCAL bytea_output = 'hex'",
        "SET LOCAL extra_float_digits = 3",
    ):
        connection.exec_driver_sql(statement)
    schemas = connection.scalar(
        text("SELECT pg_catalog.current_schemas(false)")
    )
    public_oid = connection.scalar(
        text("SELECT pg_catalog.to_regnamespace('public')::oid")
    )
    if list(schemas or []) != ["pg_catalog", "public"]:
        raise RuntimeError("schema authority rejected")
    if type(public_oid) is not int or public_oid <= 0:
        raise RuntimeError("schema authority rejected")
    # Frozen 0020's exact catalog queries intentionally use current_schema().
    # With an explicit pg_catalog first entry PostgreSQL returns pg_catalog,
    # making those queries inspect the wrong namespace.  Removing the explicit
    # catalog entry keeps PostgreSQL's implicit pg_catalog-before-public lookup
    # order while making public the one creation/catalog namespace.
    connection.exec_driver_sql("SET LOCAL search_path = public")
    effective_schemas = connection.scalar(
        text("SELECT pg_catalog.current_schemas(true)")
    )
    current_schema = connection.scalar(text("SELECT CURRENT_SCHEMA::text"))
    if list(effective_schemas or []) != ["pg_catalog", "public"]:
        raise RuntimeError("schema authority rejected")
    if current_schema != "public":
        raise RuntimeError("schema authority rejected")


def _validate_platform(connection: Connection) -> None:
    version = _count(
        connection,
        "SELECT pg_catalog.current_setting('server_version_num')::integer",
    )
    if not 160000 <= version < 170000:
        raise MigrationTargetNotAuthoritative
    if _count(
        connection,
        "SELECT count(*)::integer FROM pg_catalog.pg_extension "
        "WHERE extname = 'vector'",
    ) != 1:
        raise MigrationTargetNotAuthoritative


def _prepare_authoritative_transaction(connection: Connection) -> None:
    _establish_public_authority(connection)
    _validate_platform(connection)
    connection.exec_driver_sql(
        "LOCK TABLE public.alembic_version "
        "IN SHARE ROW EXCLUSIVE MODE NOWAIT"
    )


def _current_revision(connection: Connection) -> str:
    try:
        revisions = list(
            connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).scalars()
        )
    except (AttributeError, SQLAlchemyError):
        raise RuntimeError("database revision rejected") from None
    if len(revisions) != 1 or not isinstance(revisions[0], str):
        raise RuntimeError("database revision rejected")
    return revisions[0]


def _normalized_configured_endpoint(connection: Connection) -> tuple[str, int, str]:
    url = getattr(getattr(connection, "engine", None), "url", None)
    try:
        if url.get_backend_name() != "postgresql":
            raise ValueError
        query_keys = {str(key).casefold() for key in url.query}
        if query_keys & _ENDPOINT_ROUTING_QUERY_KEYS:
            raise ValueError
        raw_host = url.host
        raw_port = url.port
        database = url.database
    except (AttributeError, TypeError, ValueError):
        raise RuntimeError("target identity rejected") from None
    if (
        not isinstance(raw_host, str)
        or not raw_host
        or raw_host != raw_host.strip()
        or any(character.isspace() or ord(character) < 32 for character in raw_host)
        or "%" in raw_host
        or not isinstance(database, str)
        or not database
    ):
        raise RuntimeError("target identity rejected")
    host = raw_host[:-1] if raw_host.endswith(".") else raw_host
    if not host or host.endswith("."):
        raise RuntimeError("target identity rejected")
    try:
        configured_address = ipaddress.ip_address(host)
        normalized_host = configured_address.compressed.casefold()
    except ValueError:
        try:
            normalized_host = host.encode("idna").decode("ascii").casefold()
        except (UnicodeError, ValueError):
            raise RuntimeError("target identity rejected") from None
        labels = normalized_host.split(".")
        if (
            len(normalized_host) > 253
            or any(_DNS_LABEL.fullmatch(label) is None for label in labels)
        ):
            raise RuntimeError("target identity rejected")
    port = _DEFAULT_POSTGRES_PORT if raw_port is None else raw_port
    if type(port) is not int or not 1 <= port <= 65535:
        raise RuntimeError("target identity rejected")
    return normalized_host, port, database


def _target_fingerprint(connection: Connection) -> str:
    configured_host, configured_port, configured_database = (
        _normalized_configured_endpoint(connection)
    )
    system_identifier = connection.scalar(
        text(
            "SELECT system_identifier::text "
            "FROM pg_catalog.pg_control_system()"
        )
    )
    rows = list(
        connection.execute(
            text(
                "SELECT oid::bigint, datname::text, CURRENT_USER::text, "
                "pg_catalog.host(pg_catalog.inet_server_addr())::text, "
                "pg_catalog.inet_server_port()::integer, "
                "pg_catalog.pg_postmaster_start_time() "
                "FROM pg_catalog.pg_database "
                "WHERE datname = pg_catalog.current_database()"
            )
        )
    )
    try:
        (
            database_oid,
            database_name,
            database_user,
            live_address,
            live_port,
            postmaster_started_at,
        ) = rows[0]
    except (IndexError, TypeError, ValueError):
        raise RuntimeError("target identity rejected") from None
    if (
        not isinstance(system_identifier, str)
        or not system_identifier
        or len(rows) != 1
        or type(database_oid) is not int
        or database_oid <= 0
        or not isinstance(database_name, str)
        or not database_name
        or database_name != configured_database
        or not isinstance(database_user, str)
        or not database_user
        or not isinstance(live_address, str)
        or not live_address
        or type(live_port) is not int
        or not 1 <= live_port <= 65535
        or not isinstance(postmaster_started_at, datetime)
        or postmaster_started_at.tzinfo is None
        or postmaster_started_at.utcoffset() is None
    ):
        raise RuntimeError("target identity rejected")
    try:
        parsed_live_address = ipaddress.ip_address(live_address)
    except ValueError:
        raise RuntimeError("target identity rejected") from None
    if parsed_live_address.is_unspecified or parsed_live_address.is_multicast:
        raise RuntimeError("target identity rejected")
    normalized_live_address = parsed_live_address.compressed.casefold()
    canonical_postmaster_started_at = postmaster_started_at.astimezone(
        timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    target = {
        "cluster_system_identifier": system_identifier,
        "database_oid": database_oid,
        "database_name": database_name,
        "database_schema": "public",
        "database_user": database_user,
        "configured_host": configured_host,
        "configured_port": configured_port,
        "live_server_address": normalized_live_address,
        "live_server_port": live_port,
        "postmaster_started_at": canonical_postmaster_started_at,
    }
    return hashlib.sha256(_canonical_json(target)).hexdigest()


def _frame_digest(digest: Any, value: str) -> None:
    encoded = value.encode("utf-8", errors="strict")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _authority_state_digest(connection: Connection) -> str:
    """Hash every canonical row while returning no row material."""

    digest = hashlib.sha256(b"nyay19-authority-state-v1\x00")
    for table_name in AUTHORITY_TABLES:
        _frame_digest(digest, table_name)
        statement = text(
            "SELECT row_value.id::text, "
            "pg_catalog.to_jsonb(row_value)::text "
            f"FROM public.{table_name} AS row_value "
            "ORDER BY row_value.id"
        ).execution_options(
            stream_results=True,
            max_row_buffer=256,
        )
        result = connection.execute(statement)
        previous_id: str | None = None
        row_count = 0
        for stable_id, canonical_row in result:
            if (
                not isinstance(stable_id, str)
                or not isinstance(canonical_row, str)
                or (previous_id is not None and stable_id <= previous_id)
            ):
                raise RuntimeError("authority row canonicalization rejected")
            _frame_digest(digest, stable_id)
            _frame_digest(digest, canonical_row)
            previous_id = stable_id
            row_count += 1
        _frame_digest(digest, str(row_count))
    return digest.hexdigest()


def _authority_table_filter() -> str:
    """Return the source-controlled catalog filter for the locked tables."""

    return ",".join(f"'{table_name}'" for table_name in AUTHORITY_TABLES)


def _canonical_function_source(value: Any) -> str:
    if not isinstance(value, str):
        raise RuntimeError("authority catalog rejected")
    return re.sub(r"\s+", " ", value.strip())


def _validate_authority_catalog(connection: Connection) -> None:
    """Reject every code-bearing or row-filtering authority-table mutant.

    The privacy counts and freeze DML are authoritative only when PostgreSQL
    cannot hide rows with RLS/policies or redirect/suppress writes with rules
    and triggers.  Audit append-only protection is the sole expected user
    trigger and its function is bound structurally and semantically here.
    """

    table_filter = _authority_table_filter()
    try:
        relations = list(
            connection.execute(
                text(
                    "SELECT table_row.relname::text AS table_name, "
                    "table_row.relkind::text AS relation_kind, "
                    "table_row.relpersistence::text AS persistence, "
                    "table_row.relispartition AS is_partition, "
                    "table_row.relrowsecurity AS row_security, "
                    "table_row.relforcerowsecurity AS force_row_security "
                    "FROM pg_catalog.pg_class AS table_row "
                    "JOIN pg_catalog.pg_namespace AS namespace_row "
                    "ON namespace_row.oid = table_row.relnamespace "
                    "WHERE namespace_row.nspname = 'public' "
                    f"AND table_row.relname IN ({table_filter}) "
                    "ORDER BY table_row.relname"
                )
            ).mappings().all()
        )
        policies = list(
            connection.execute(
                text(
                    "SELECT table_row.relname::text AS table_name, "
                    "policy_row.polname::text AS policy_name, "
                    "policy_row.polcmd::text AS command, "
                    "policy_row.polpermissive AS permissive, "
                    "policy_row.polroles::text AS roles, "
                    "pg_catalog.pg_get_expr(policy_row.polqual, "
                    "policy_row.polrelid, false) AS using_expression, "
                    "pg_catalog.pg_get_expr(policy_row.polwithcheck, "
                    "policy_row.polrelid, false) AS check_expression "
                    "FROM pg_catalog.pg_policy AS policy_row "
                    "JOIN pg_catalog.pg_class AS table_row "
                    "ON table_row.oid = policy_row.polrelid "
                    "JOIN pg_catalog.pg_namespace AS namespace_row "
                    "ON namespace_row.oid = table_row.relnamespace "
                    "WHERE namespace_row.nspname = 'public' "
                    f"AND table_row.relname IN ({table_filter}) "
                    "ORDER BY table_row.relname, policy_row.polname"
                )
            ).mappings().all()
        )
        rules = list(
            connection.execute(
                text(
                    "SELECT table_row.relname::text AS table_name, "
                    "rule_row.rulename::text AS rule_name, "
                    "rule_row.ev_type::text AS event_type, "
                    "rule_row.ev_enabled::text AS enabled, "
                    "rule_row.is_instead AS is_instead, "
                    "pg_catalog.pg_get_ruledef(rule_row.oid, false) "
                    "AS definition "
                    "FROM pg_catalog.pg_rewrite AS rule_row "
                    "JOIN pg_catalog.pg_class AS table_row "
                    "ON table_row.oid = rule_row.ev_class "
                    "JOIN pg_catalog.pg_namespace AS namespace_row "
                    "ON namespace_row.oid = table_row.relnamespace "
                    "WHERE namespace_row.nspname = 'public' "
                    f"AND table_row.relname IN ({table_filter}) "
                    "AND rule_row.rulename <> '_RETURN' "
                    "ORDER BY table_row.relname, rule_row.rulename"
                )
            ).mappings().all()
        )
        triggers = list(
            connection.execute(
                text(
                    "SELECT table_row.relname::text AS table_name, "
                    "trigger_row.tgname::text AS trigger_name, "
                    "trigger_row.tgenabled::text AS trigger_enabled, "
                    "trigger_row.tgtype::integer AS trigger_type, "
                    "trigger_row.tgnargs::integer AS argument_count, "
                    "trigger_row.tgattr::text = '' "
                    "AS no_column_filter, "
                    "trigger_row.tgqual IS NULL AS no_when_clause, "
                    "trigger_row.tgconstraint = 0 AS not_constraint, "
                    "NOT trigger_row.tgdeferrable AS not_deferrable, "
                    "NOT trigger_row.tginitdeferred AS not_initially_deferred, "
                    "trigger_row.tgparentid = 0 AS not_child_trigger, "
                    "trigger_row.tgoldtable IS NULL "
                    "AND trigger_row.tgnewtable IS NULL "
                    "AS no_transition_tables, "
                    "pg_catalog.encode(trigger_row.tgargs, 'hex') "
                    "AS arguments_hex, "
                    "function_namespace.nspname::text AS function_schema, "
                    "function_row.proname::text AS function_name, "
                    "function_row.prokind::text AS function_kind, "
                    "language_row.lanname::text AS language_name, "
                    "pg_catalog.format_type(function_row.prorettype, NULL) "
                    "= 'trigger' AS returns_trigger, "
                    "pg_catalog.pg_get_function_identity_arguments("
                    "function_row.oid) AS function_arguments, "
                    "function_row.prosrc::text AS function_source, "
                    "function_row.provolatile::text AS function_volatile, "
                    "function_row.proparallel::text AS function_parallel, "
                    "function_row.prosecdef AS security_definer, "
                    "function_row.proleakproof AS leakproof, "
                    "function_row.proisstrict AS function_strict, "
                    "function_row.proconfig AS function_config, "
                    "function_row.proowner = table_row.relowner AS same_owner "
                    "FROM pg_catalog.pg_trigger AS trigger_row "
                    "JOIN pg_catalog.pg_class AS table_row "
                    "ON table_row.oid = trigger_row.tgrelid "
                    "JOIN pg_catalog.pg_namespace AS namespace_row "
                    "ON namespace_row.oid = table_row.relnamespace "
                    "JOIN pg_catalog.pg_proc AS function_row "
                    "ON function_row.oid = trigger_row.tgfoid "
                    "JOIN pg_catalog.pg_namespace AS function_namespace "
                    "ON function_namespace.oid = function_row.pronamespace "
                    "JOIN pg_catalog.pg_language AS language_row "
                    "ON language_row.oid = function_row.prolang "
                    "WHERE namespace_row.nspname = 'public' "
                    f"AND table_row.relname IN ({table_filter}) "
                    "AND NOT trigger_row.tgisinternal "
                    "ORDER BY table_row.relname, trigger_row.tgname"
                )
            ).mappings().all()
        )
    except (AttributeError, SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("authority catalog rejected") from None

    expected_relations = [
        {
            "table_name": table_name,
            "relation_kind": "r",
            "persistence": "p",
            "is_partition": False,
            "row_security": False,
            "force_row_security": False,
        }
        for table_name in sorted(AUTHORITY_TABLES)
    ]
    expected_trigger = {
        "table_name": "audit_events",
        "trigger_name": "trg_audit_events_append_only",
        "trigger_enabled": "O",
        "trigger_type": 27,
        "argument_count": 0,
        "no_column_filter": True,
        "no_when_clause": True,
        "not_constraint": True,
        "not_deferrable": True,
        "not_initially_deferred": True,
        "not_child_trigger": True,
        "no_transition_tables": True,
        "arguments_hex": "",
        "function_schema": "public",
        "function_name": "legalsaathi_audit_append_only",
        "function_kind": "f",
        "language_name": "plpgsql",
        "returns_trigger": True,
        "function_arguments": "",
        "function_source": (
            "BEGIN RAISE EXCEPTION "
            "'audit_events rows are append-only (% blocked)', TG_OP; END;"
        ),
        "function_volatile": "v",
        "function_parallel": "u",
        "security_definer": False,
        "leakproof": False,
        "function_strict": False,
        "function_config": None,
        "same_owner": True,
    }
    actual_relations = [dict(row) for row in relations]
    actual_triggers = [dict(row) for row in triggers]
    try:
        for row in actual_triggers:
            row["function_source"] = _canonical_function_source(
                row.get("function_source")
            )
    except RuntimeError:
        raise RuntimeError("authority catalog rejected") from None
    if (
        actual_relations != expected_relations
        or policies
        or rules
        or actual_triggers != [expected_trigger]
    ):
        raise RuntimeError("authority catalog rejected")


def _hex_residue_is_empty(column: str) -> str:
    expression = column
    for character in "0123456789abcdef":
        expression = f"replace({expression}, '{character}', '')"
    return f"length({expression}) = 0"


def _legacy_deletion_queries() -> tuple[str, ...]:
    accepted_filter = (
        "dsr.kind = 'delete' AND dsr.reauth_verified = true "
        "AND dsr.status IN ('pending','processing','complete','failed')"
    )
    return (
        (
            "SELECT 1 FROM public.data_subject_requests AS dsr "
            "JOIN public.deletion_jobs AS job ON job.request_id = dsr.id "
            "WHERE dsr.kind = 'delete' AND dsr.reauth_verified = true AND ("
            "dsr.status IS NULL OR (dsr.status <> 'cancelled' AND ("
            "dsr.status NOT IN ('pending','processing','complete','failed') OR "
            "dsr.confirmation_hash IS NULL OR length(dsr.confirmation_hash) "
            "<> 64 OR NOT ("
            + _hex_residue_is_empty("dsr.confirmation_hash")
            + ") OR job.status IS NULL OR job.status NOT IN "
            "('pending','processing','complete','failed') OR "
            "job.mode IS NULL OR job.mode NOT IN ('anonymise','delete')))) "
            "LIMIT 1"
        ),
        (
            "SELECT 1 FROM public.data_subject_requests AS dsr "
            f"WHERE {accepted_filter} AND NOT EXISTS (SELECT 1 FROM "
            "public.deletion_jobs AS job WHERE job.request_id = dsr.id) LIMIT 1"
        ),
        (
            "SELECT 1 FROM public.data_subject_requests AS dsr "
            f"WHERE {accepted_filter} AND (SELECT count(*) FROM "
            "public.deletion_jobs AS job WHERE job.request_id = dsr.id) > 1 "
            "LIMIT 1"
        ),
        (
            "WITH targets AS (" + _ACCEPTED_SUBJECTS_SQL + ") "
            "SELECT 1 FROM targets AS target LEFT JOIN public.users AS user_row "
            "ON user_row.id = target.user_id WHERE user_row.id IS NULL OR "
            "user_row.role IS NULL OR user_row.role <> 'student' OR "
            "user_row.status IS NULL OR user_row.status NOT IN "
            "('pending','active','suspended','deleted') LIMIT 1"
        ),
        (
            "WITH targets AS (" + _ACCEPTED_SUBJECTS_SQL + ") "
            "SELECT 1 FROM targets AS target WHERE NOT EXISTS (SELECT 1 FROM "
            "public.student_registrations AS registration_row WHERE "
            "registration_row.user_id = target.user_id) LIMIT 1"
        ),
        (
            "WITH targets AS (" + _ACCEPTED_SUBJECTS_SQL + ") "
            "SELECT 1 FROM targets AS target WHERE (SELECT count(*) FROM "
            "public.student_registrations AS registration_row WHERE "
            "registration_row.user_id = target.user_id) > 1 LIMIT 1"
        ),
        (
            "WITH targets AS (" + _ACCEPTED_SUBJECTS_SQL + ") "
            "SELECT 1 FROM targets AS target JOIN "
            "public.student_registrations AS registration_row ON "
            "registration_row.user_id = target.user_id WHERE "
            "registration_row.status IS NULL OR registration_row.status NOT IN "
            "('otp_pending','otp_verified','active','suspended','deleted') "
            "LIMIT 1"
        ),
    )


def _validate_legacy_deletion_authority(connection: Connection) -> None:
    try:
        for query in _legacy_deletion_queries():
            if connection.scalar(text(query)) is not None:
                raise RuntimeError("legacy deletion authority rejected")
    except RuntimeError:
        raise
    except (AttributeError, SQLAlchemyError, TypeError, ValueError):
        raise RuntimeError("legacy deletion authority rejected") from None


def _target_module() -> Any:
    module = _load_authenticated_migration_module(
        "nyay19_authenticated_0020",
        TARGET_SOURCE_PATH,
        TARGET_SOURCE_SHA256,
    )
    module_path = getattr(module, "__file__", None)
    if (
        not isinstance(module_path, str)
        or Path(module_path).resolve() != TARGET_SOURCE_PATH
        or getattr(module, "revision", None) != TARGET_REVISION
        or getattr(module, "down_revision", None) != PARENT_REVISION
    ):
        raise RuntimeError("migration authority rejected")
    return module


def _nyay5_module() -> Any:
    module = _load_authenticated_migration_module(
        "nyay5_authenticated_0021",
        NYAY5_SOURCE_PATH,
        NYAY5_SOURCE_SHA256,
    )
    module_path = getattr(module, "__file__", None)
    if (
        not isinstance(module_path, str)
        or Path(module_path).resolve() != NYAY5_SOURCE_PATH
        or getattr(module, "revision", None) != NYAY5_REVISION
        or getattr(module, "down_revision", None) != TARGET_REVISION
    ):
        raise RuntimeError("migration authority rejected")
    return module


def _nyay9_module() -> Any:
    module = _load_authenticated_migration_module(
        "nyay9_authenticated_0022",
        NYAY9_SOURCE_PATH,
        NYAY9_SOURCE_SHA256,
    )
    module_path = getattr(module, "__file__", None)
    if (
        not isinstance(module_path, str)
        or Path(module_path).resolve() != NYAY9_SOURCE_PATH
        or getattr(module, "revision", None) != NYAY9_REVISION
        or getattr(module, "down_revision", None) != NYAY5_REVISION
    ):
        raise RuntimeError("migration authority rejected")
    return module


def _nyay22_module() -> Any:
    module = _load_authenticated_migration_module(
        "nyay22_authenticated_0023",
        NYAY22_SOURCE_PATH,
        NYAY22_SOURCE_SHA256,
    )
    module_path = getattr(module, "__file__", None)
    if (
        not isinstance(module_path, str)
        or Path(module_path).resolve() != NYAY22_SOURCE_PATH
        or getattr(module, "revision", None) != NYAY22_REVISION
        or getattr(module, "down_revision", None) != NYAY9_REVISION
    ):
        raise RuntimeError("migration authority rejected")
    return module


def _nyay11_module() -> Any:
    module = _load_authenticated_migration_module(
        "nyay11_authenticated_0024",
        NYAY11_SOURCE_PATH,
        NYAY11_SOURCE_SHA256,
    )
    if (
        getattr(module, "__file__", None) != str(NYAY11_SOURCE_PATH)
        or getattr(module, "revision", None) != NYAY11_REVISION
        or getattr(module, "down_revision", None) != NYAY22_REVISION
    ):
        raise RuntimeError("migration authority rejected")
    return module


def _application_module() -> Any:
    """Authenticated 0025 (NYAY-12) head; its parent is the sealed 0024 checkpoint."""
    module = _load_authenticated_migration_module(
        "nyay12_authenticated_0025",
        APPLICATION_HEAD_SOURCE_PATH,
        APPLICATION_HEAD_SOURCE_SHA256,
    )
    if (
        getattr(module, "__file__", None) != str(APPLICATION_HEAD_SOURCE_PATH)
        or getattr(module, "revision", None) != APPLICATION_HEAD_REVISION
        or getattr(module, "down_revision", None) != NYAY11_REVISION
    ):
        raise RuntimeError("migration authority rejected")
    return module


def _validate_at_head(connection: Connection) -> None:
    module = _target_module()
    module._begin_and_lock(connection, downgrade=True)
    if _current_revision(connection) != TARGET_REVISION:
        raise RuntimeError("head revision changed")
    _validate_authority_catalog(connection)
    module._validate_postflight(connection, head=True)
    _target_fingerprint(connection)
    _validate_legacy_deletion_authority(connection)
    remaining = (
        _count(
            connection,
            "SELECT count(*) FROM public.users WHERE id IN ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AND status NOT IN ('suspended','deleted')",
        ),
        _count(
            connection,
            "SELECT count(*) FROM public.student_registrations "
            "WHERE user_id IN ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AND status NOT IN ('suspended','deleted')",
        ),
        _count(
            connection,
            "SELECT count(*) FROM public.auth_sessions WHERE user_id IN ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AND status = 'active'",
        ),
    )
    if any(remaining):
        raise RuntimeError("privacy freeze incomplete")
    if not source_authority_is_valid():
        raise RuntimeError("migration source changed")


def _validate_nyay5_inherited_authority(
    connection: Connection,
    *,
    expected_revision: str,
    head: bool,
) -> None:
    """Re-prove frozen 0021 schema plus inherited security/privacy authority."""

    module = _nyay5_module()
    if _current_revision(connection) != expected_revision:
        raise RuntimeError("head revision changed")
    _validate_authority_catalog(connection)
    module._validate_postflight(connection, head=head)
    _target_fingerprint(connection)
    _validate_legacy_deletion_authority(connection)
    remaining = (
        _count(
            connection,
            "SELECT count(*) FROM public.users WHERE id IN ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AND status NOT IN ('suspended','deleted')",
        ),
        _count(
            connection,
            "SELECT count(*) FROM public.student_registrations WHERE user_id IN ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AND status NOT IN ('suspended','deleted')",
        ),
        _count(
            connection,
            "SELECT count(*) FROM public.auth_sessions WHERE user_id IN ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AND status = 'active'",
        ),
    )
    if any(remaining) or not source_authority_is_valid():
        raise RuntimeError("NYAY-5 inherited authority validation rejected")


def _validate_nyay5_at_head(connection: Connection) -> None:
    """Re-prove exact 0021 head plus inherited security/privacy authority."""

    _validate_nyay5_inherited_authority(
        connection,
        expected_revision=NYAY5_REVISION,
        head=True,
    )


def _validate_nyay9_at_head(connection: Connection) -> None:
    """Re-prove exact 0022 plus the complete inherited 0021 authority."""

    nyay5_module = _nyay5_module()
    module = _nyay9_module()
    nyay5_module._lock(connection)
    module._lock(connection, include_ledger=True)
    if _current_revision(connection) != NYAY9_REVISION:
        raise RuntimeError("head revision changed")
    _validate_nyay5_inherited_authority(
        connection,
        expected_revision=NYAY9_REVISION,
        head=False,
    )
    module._validate_postflight(connection, head=True)
    if not source_authority_is_valid():
        raise RuntimeError("NYAY-9 migration source changed")


def _validate_nyay22_at_head(connection: Connection) -> None:
    """Keep the authenticated 0023 checkpoint independent from moving head."""

    module = _nyay22_module()
    if (
        _current_revision(connection) != NYAY22_REVISION
        or module.down_revision != NYAY9_REVISION
        or not source_authority_is_valid()
    ):
        raise RuntimeError("NYAY-22 migration source changed")


def _validate_nyay11_at_head(connection: Connection) -> None:
    """Keep the authenticated 0024 checkpoint independent from moving head."""

    module = _nyay11_module()
    if (
        _current_revision(connection) != NYAY11_REVISION
        or module.down_revision != NYAY22_REVISION
        or not source_authority_is_valid()
    ):
        raise RuntimeError("NYAY-11 migration source changed")


def _validate_application_at_head(connection: Connection) -> None:
    """Bind application head to 0025 without granting production migration."""
    module = _application_module()
    if (
        _current_revision(connection) != APPLICATION_HEAD_REVISION
        or module.down_revision != NYAY11_REVISION
        or not source_authority_is_valid()
    ):
        raise RuntimeError("NYAY-12 migration source changed")


def locked_parent_report(
    connection: Connection,
    *,
    change_reference: str,
    approval_window_ends_at: str,
    preflight_observed_at: str | None = None,
) -> dict[str, Any]:
    """Return an aggregate-only report while holding every authority lock."""

    if not source_authority_is_valid():
        raise RuntimeError("migration source rejected")
    if not connection.in_transaction():
        raise RuntimeError("transaction required")
    _prepare_authoritative_transaction(connection)
    if _current_revision(connection) != PARENT_REVISION:
        raise RuntimeError("parent revision rejected")
    module = _target_module()
    module._begin_and_lock(connection, downgrade=False)
    if _current_revision(connection) != PARENT_REVISION:
        raise RuntimeError("parent revision changed")
    _validate_authority_catalog(connection)
    module._upgrade_data_preflight(connection)
    _validate_legacy_deletion_authority(connection)
    database_now = _database_clock(connection)
    observed_at = (
        _canonical_observed_at(database_now)
        if preflight_observed_at is None
        else preflight_observed_at
    )
    approval_metadata = {
        "change_reference": change_reference,
        "approval_window_ends_at": approval_window_ends_at,
        "preflight_observed_at": observed_at,
    }
    if not _approval_window_is_current(approval_metadata, database_now):
        raise RuntimeError("approval window rejected")

    aggregates = {
        "accepted_deletion_subjects": _count(
            connection,
            "SELECT count(*) FROM ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AS subjects",
        ),
        "accounts_to_suspend": _count(
            connection,
            "SELECT count(*) FROM public.users WHERE id IN ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AND status NOT IN ('suspended','deleted')",
        ),
        "registrations_to_suspend": _count(
            connection,
            "SELECT count(*) FROM public.student_registrations WHERE user_id IN ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AND status NOT IN ('suspended','deleted')",
        ),
        "active_sessions_to_revoke": _count(
            connection,
            "SELECT count(*) FROM public.auth_sessions WHERE user_id IN ("
            + _ACCEPTED_SUBJECTS_SQL
            + ") AND status = 'active'",
        ),
        "login_attempt_rows": _count(
            connection, "SELECT count(*) FROM public.login_attempts"
        ),
        "auth_session_rows": _count(
            connection, "SELECT count(*) FROM public.auth_sessions"
        ),
        "locked_relation_bytes": _count(
            connection,
            "SELECT COALESCE(sum(pg_catalog.pg_total_relation_size("
            "pg_catalog.to_regclass('public.' || relation_name))), 0)::bigint "
            "FROM (VALUES ('data_subject_requests'),('deletion_jobs'),('users'),"
            "('student_registrations'),('login_attempts'),('auth_sessions'),"
            "('audit_events')) AS locked(relation_name)",
        ),
    }
    report: dict[str, Any] = {
        "verdict": "PASS",
        "code": "migration_ready",
        "parent_revision": PARENT_REVISION,
        "target_revision": TARGET_REVISION,
        "postgres_major": 16,
        "pgvector_present": True,
        **approval_metadata,
        "target_source_sha256": TARGET_SOURCE_SHA256,
        "target_fingerprint": _target_fingerprint(connection),
        "authority_state_digest": _authority_state_digest(connection),
        "aggregates": aggregates,
    }
    report["state_fingerprint"] = state_fingerprint(report)
    if not _report_is_exact(report) or not source_authority_is_valid():
        raise RuntimeError("report construction rejected")
    return report


def _read_only_intent_agrees(
    command: Any,
    intent: RuntimeMigrationIntent | None,
) -> bool:
    operation = _READ_ONLY_COMMANDS.get(command)
    return bool(
        operation is not None
        and type(intent) is RuntimeMigrationIntent
        and intent.operation == operation
        and intent.destination_revision is None
        and intent.as_sql is False
        and intent.tag is None
        and (operation != "current" or intent.dont_mutate is True)
    )


def _upgrade_intent_agrees(
    config: Any,
    command: Any,
    intent: RuntimeMigrationIntent | None,
) -> bool:
    options = getattr(config, "cmd_opts", None)
    return bool(
        command is alembic_command.upgrade
        and getattr(options, "revision", None) == TARGET_REVISION
        and getattr(options, "sql", None) is False
        and getattr(options, "tag", None) is None
        and type(intent) is RuntimeMigrationIntent
        and intent.operation == "upgrade"
        and intent.destination_revision == TARGET_REVISION
        and intent.as_sql is False
        and intent.tag is None
        and intent.dont_mutate is False
    )


def _nyay5_upgrade_intent_agrees(
    config: Any,
    command: Any,
    intent: RuntimeMigrationIntent | None,
) -> bool:
    """Bind a forward request to only the direct, authenticated 0021 child."""

    options = getattr(config, "cmd_opts", None)
    configured = getattr(options, "revision", None)
    return bool(
        command is alembic_command.upgrade
        and configured == NYAY5_REVISION
        and getattr(options, "sql", None) is False
        and getattr(options, "tag", None) is None
        and type(intent) is RuntimeMigrationIntent
        and intent.operation == "upgrade"
        and intent.destination_revision == NYAY5_REVISION
        and intent.as_sql is False
        and intent.tag is None
        and intent.dont_mutate is False
        and _nyay5_module().down_revision == TARGET_REVISION
    )


def _nyay9_upgrade_intent_agrees(
    config: Any,
    command: Any,
    intent: RuntimeMigrationIntent | None,
) -> bool:
    """Bind a forward request to only the direct, authenticated 0022 child."""

    options = getattr(config, "cmd_opts", None)
    configured = getattr(options, "revision", None)
    # An earlier NYAY-9 approval may authorize only its exact 0021 -> 0022
    # edge.  Once 0023 exists, the moving alias ``head`` must not widen that
    # authority to the mentor-ceremony migration.
    expected_runtime = configured if configured == NYAY9_REVISION else None
    return bool(
        command is alembic_command.upgrade
        and expected_runtime is not None
        and getattr(options, "sql", None) is False
        and getattr(options, "tag", None) is None
        and type(intent) is RuntimeMigrationIntent
        and intent.operation == "upgrade"
        and intent.destination_revision == expected_runtime
        and intent.as_sql is False
        and intent.tag is None
        and intent.dont_mutate is False
        and _nyay9_module().down_revision == NYAY5_REVISION
    )


def _nyay22_upgrade_intent_agrees(
    config: Any,
    command: Any,
    intent: RuntimeMigrationIntent | None,
) -> bool:
    """Recognise 0023 without granting its production mutation authority."""

    options = getattr(config, "cmd_opts", None)
    configured = getattr(options, "revision", None)
    expected_runtime = (
        configured
        if configured == NYAY22_REVISION
        else None
    )
    return bool(
        command is alembic_command.upgrade
        and expected_runtime is not None
        and getattr(options, "sql", None) is False
        and getattr(options, "tag", None) is None
        and type(intent) is RuntimeMigrationIntent
        and intent.operation == "upgrade"
        and intent.destination_revision == expected_runtime
        and intent.as_sql is False
        and intent.tag is None
        and intent.dont_mutate is False
        and _nyay22_module().down_revision == NYAY9_REVISION
    )


def _nyay11_upgrade_intent_agrees(
    config: Any, command: Any, intent: RuntimeMigrationIntent | None,
) -> bool:
    """Recognise the exact 0024 checkpoint; previous approvals never authorize this edge."""
    options = getattr(config, "cmd_opts", None)
    configured = getattr(options, "revision", None)
    return bool(
        command is alembic_command.upgrade
        and configured == NYAY11_REVISION
        and getattr(options, "sql", None) is False
        and getattr(options, "tag", None) is None
        and type(intent) is RuntimeMigrationIntent
        and intent.operation == "upgrade"
        and intent.destination_revision == configured
        and intent.as_sql is False
        and intent.tag is None
        and intent.dont_mutate is False
        and _nyay11_module().down_revision == NYAY22_REVISION
    )


def _application_upgrade_intent_agrees(
    config: Any, command: Any, intent: RuntimeMigrationIntent | None,
) -> bool:
    """Recognise exact new head (0025); previous approvals never authorize this edge."""
    options = getattr(config, "cmd_opts", None)
    configured = getattr(options, "revision", None)
    return bool(
        command is alembic_command.upgrade
        and configured in {APPLICATION_HEAD_REVISION, "head"}
        and getattr(options, "sql", None) is False
        and getattr(options, "tag", None) is None
        and type(intent) is RuntimeMigrationIntent
        and intent.operation == "upgrade"
        and intent.destination_revision == configured
        and intent.as_sql is False
        and intent.tag is None
        and intent.dont_mutate is False
        and _application_module().down_revision == NYAY11_REVISION
    )


def enforce_nyay19_migration_postflight(
    connection: Connection,
    *,
    expected_revision: str = TARGET_REVISION,
) -> None:
    """Re-prove exact head, catalog authority, and privacy-zero before commit."""

    try:
        if not connection.in_transaction():
            raise RuntimeError
        if expected_revision == TARGET_REVISION:
            _validate_at_head(connection)
        elif expected_revision == NYAY5_REVISION:
            _validate_nyay5_at_head(connection)
        elif expected_revision == NYAY9_REVISION:
            _validate_nyay9_at_head(connection)
        elif expected_revision == NYAY22_REVISION:
            _validate_nyay22_at_head(connection)
        elif expected_revision == NYAY11_REVISION:
            _validate_nyay11_at_head(connection)
        elif expected_revision == APPLICATION_HEAD_REVISION:
            _validate_application_at_head(connection)
        else:
            raise RuntimeError
    except Exception:
        raise MigrationApprovalError(
            "NYAY-19 migration postflight rejected; refusing to commit"
        ) from None


def enforce_nyay19_migration_release_guard(
    config: Any,
    connection: Connection,
    *,
    environment: str,
    environ: Mapping[str, str] | None = None,
    runtime_intent: RuntimeMigrationIntent | None = None,
) -> bool:
    """Authorize frozen direct edges without widening an earlier approval."""

    authority = os.environ if environ is None else environ
    if authority.get(FORCE_APPROVAL_ENV) != "1" and _is_explicit_isolated_target(
        connection,
        environment=environment,
        environ=authority,
    ):
        return False

    command = _command(config)
    if command in _READ_ONLY_COMMANDS:
        if _read_only_intent_agrees(command, runtime_intent):
            return False
        raise MigrationApprovalError(
            "NYAY-19 migration command is not authorized; refusing to migrate"
        )
    nyay19_upgrade = _upgrade_intent_agrees(config, command, runtime_intent)
    nyay5_upgrade = bool(
        getattr(getattr(connection, "dialect", None), "name", None)
        == "postgresql"
        and _nyay5_upgrade_intent_agrees(config, command, runtime_intent)
    )
    nyay9_upgrade = bool(
        getattr(getattr(connection, "dialect", None), "name", None)
        == "postgresql"
        and _nyay9_upgrade_intent_agrees(config, command, runtime_intent)
    )
    nyay22_upgrade = bool(
        getattr(getattr(connection, "dialect", None), "name", None)
        == "postgresql"
        and _nyay22_upgrade_intent_agrees(config, command, runtime_intent)
    )
    nyay11_upgrade = bool(
        getattr(getattr(connection, "dialect", None), "name", None)
        == "postgresql"
        and _nyay11_upgrade_intent_agrees(config, command, runtime_intent)
    )
    application_upgrade = bool(
        getattr(getattr(connection, "dialect", None), "name", None)
        == "postgresql"
        and _application_upgrade_intent_agrees(config, command, runtime_intent)
    )
    if not (
        nyay19_upgrade or nyay5_upgrade or nyay9_upgrade or nyay22_upgrade
        or nyay11_upgrade or application_upgrade
    ):
        raise MigrationApprovalError(
            "NYAY-19 migration command is not authorized; refusing to migrate"
        )
    try:
        in_transaction = connection.in_transaction()
    except AttributeError:
        in_transaction = False
    if not in_transaction:
        raise MigrationApprovalError(
            "NYAY-19 migration transaction is unavailable; refusing to migrate"
        )
    if not source_authority_is_valid():
        raise MigrationApprovalError(
            "NYAY-19 migration source authority rejected; refusing to migrate"
        )
    try:
        _prepare_authoritative_transaction(connection)
        revision = _current_revision(connection)
    except Exception:
        raise MigrationApprovalError(
            "NYAY-19 live target rejected; refusing to migrate"
        ) from None
    if application_upgrade:
        if revision == APPLICATION_HEAD_REVISION:
            try:
                _validate_application_at_head(connection)
            except Exception:
                raise MigrationApprovalError(
                    "NYAY-12 head validation rejected; refusing to migrate"
                ) from None
            return True
        raise MigrationApprovalError(
            "NYAY-12 production approval unavailable; refusing to migrate"
        )

    if nyay11_upgrade:
        if revision == NYAY11_REVISION:
            try:
                _validate_nyay11_at_head(connection)
            except Exception:
                raise MigrationApprovalError(
                    "NYAY-11 head validation rejected; refusing to migrate"
                ) from None
            return True
        raise MigrationApprovalError(
            "NYAY-11 production approval unavailable; refusing to migrate"
        )

    if nyay22_upgrade:
        if revision == NYAY22_REVISION:
            try:
                _validate_nyay22_at_head(connection)
            except Exception:
                raise MigrationApprovalError(
                    "NYAY-22 head validation rejected; refusing to migrate"
                ) from None
            return True
        if revision != NYAY9_REVISION:
            raise MigrationApprovalError(
                "NYAY-22 database revision rejected; refusing to migrate"
            )
        try:
            _validate_nyay9_at_head(connection)
        except Exception:
            raise MigrationApprovalError(
                "NYAY-22 parent validation rejected; refusing to migrate"
            ) from None
        raise MigrationApprovalError(
            "NYAY-22 production approval unavailable; refusing to migrate"
        )

    if nyay9_upgrade:
        if revision == NYAY9_REVISION:
            try:
                _validate_nyay9_at_head(connection)
            except Exception:
                raise MigrationApprovalError(
                    "NYAY-9 head validation rejected; refusing to migrate"
                ) from None
            return True
        if revision != NYAY5_REVISION:
            raise MigrationApprovalError(
                "NYAY-9 database revision rejected; refusing to migrate"
            )
        try:
            # Authenticate and re-prove the exact 0021 parent.  The frozen
            # NYAY-19 approval and the absence of a NYAY-5 production approval
            # cannot authorize this distinct 0021->0022 transition.
            _validate_nyay5_at_head(connection)
        except Exception:
            raise MigrationApprovalError(
                "NYAY-9 parent validation rejected; refusing to migrate"
            ) from None
        raise MigrationApprovalError(
            "NYAY-9 production approval unavailable; refusing to migrate"
        )

    if nyay5_upgrade:
        if revision == NYAY5_REVISION:
            try:
                _validate_nyay5_at_head(connection)
            except Exception:
                raise MigrationApprovalError(
                    "NYAY-5 head validation rejected; refusing to migrate"
                ) from None
            return True
        if revision != TARGET_REVISION:
            raise MigrationApprovalError(
                "NYAY-5 database revision rejected; refusing to migrate"
            )
        try:
            # Re-prove the sealed 0020 schema/privacy state before its one
            # ordinary direct-child transition. No 0019 approval is aggregated
            # or bypassed by a request for 0021/head.
            _validate_at_head(connection)
        except Exception:
            raise MigrationApprovalError(
                "NYAY-5 parent validation rejected; refusing to migrate"
            ) from None
        # The unified development kickoff authorizes only disposable local/CI
        # execution (handled by the isolated-target bypass above). No new
        # digest-bound, four-role production approval contract exists for
        # 0021, and the sealed 0019->0020 report cannot be replayed or widened.
        raise MigrationApprovalError(
            "NYAY-5 production approval unavailable; refusing to migrate"
        )

    if revision == TARGET_REVISION:
        try:
            _validate_at_head(connection)
        except Exception:
            raise MigrationApprovalError(
                "NYAY-19 head validation rejected; refusing to migrate"
            ) from None
        return True
    if revision != PARENT_REVISION:
        raise MigrationApprovalError(
            "NYAY-19 database revision rejected; refusing to migrate"
        )

    approved = _approved_report(authority)
    try:
        live = locked_parent_report(
            connection,
            change_reference=approved["change_reference"],
            approval_window_ends_at=approved["approval_window_ends_at"],
            preflight_observed_at=approved["preflight_observed_at"],
        )
    except Exception:
        raise MigrationApprovalError(
            "NYAY-19 live preflight rejected; refusing to migrate"
        ) from None
    if not hmac.compare_digest(_canonical_json(approved), _canonical_json(live)):
        raise MigrationApprovalError(
            "NYAY-19 approved live state changed; refusing to migrate"
        )
    try:
        window_is_current = _approval_window_is_current(
            approved,
            _database_clock(connection),
        )
    except Exception:
        window_is_current = False
    if not window_is_current:
        raise MigrationApprovalError(
            "NYAY-19 migration approval window expired; refusing to migrate"
        )
    return True
