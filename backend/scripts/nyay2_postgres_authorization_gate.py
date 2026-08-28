"""NYAY-2 PostgreSQL 16 authorization and ownership release gate.

This executable is deliberately separate from the ordinary SQLite test suite.
It accepts only an explicit loopback PostgreSQL control URL, creates one
uniquely named scratch database, migrates it to ``head``, exercises the real
FastAPI routes against that database, and removes the scratch database in a
``finally`` block.  The database named by ``--database-url`` is never migrated
or used for product probes.

The JSON report is intentionally aggregate: it contains assertion identifiers,
status codes, counts, and booleans only.  It never contains a database URL,
scratch-database name, UUID, cookie/token, mobile number, email address, or
request/response payload.

Exit codes:

* 0: every required authorization oracle and negative control passed;
* 1: a product assertion, harness assertion, privacy check, or cleanup failed;
* 78: PostgreSQL 16, pgvector, or scratch-database authority was unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, select, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

BLOCKED_EXIT = 78
LIBPQ_AMBIENT_KEYS = frozenset(
    {
        "PGHOST",
        "PGHOSTADDR",
        "PGPORT",
        "PGDATABASE",
        "PGUSER",
        "PGPASSWORD",
        "PGPASSFILE",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGOPTIONS",
        "PGCONNECT_TIMEOUT",
        "PGTARGETSESSIONATTRS",
    }
)
REQUIRED_ASSERTION_IDS = (
    "RUNTIME-POSTGRES-16-PGVECTOR",
    "RUNTIME-ALEMBIC-HEAD-CLEAN",
    "CONTRACT-SIGNUP-MINTS-HTTPONLY-SESSION",
    "AUTH-SIGNUP-BOOTSTRAP-EXPIRES-ON-ACTIVATION",
    "AUTH-ANONYMOUS-401-NO-DELTA",
    "AUTH-OWNER-PROFILE-SUCCESS",
    "AUTH-OWNER-EMAIL-AND-STATUS-SUCCESS",
    "AUTH-CROSS-OWNER-ISOLATION",
    "AUTH-LEGACY-TARGET-SYMMETRY-NO-DELTA",
    "CONTRACT-PROTECTED-UUIDS-REJECTED",
    "AUTH-INVALID-SESSIONS-UNIFORM",
    "AUTH-SOFT-DELETED-PREAUTH-CAPABILITIES-DENIED",
    "AUTH-GUARDIAN-SELF-APPROVAL-DENIED",
    "AUTH-REVIEWER-ROLE-AND-AUDIT",
    "AUTH-EXACT-ORIGIN-MATRIX",
    "MUTANT-OWNERSHIP-PREDICATE",
    "MUTANT-REVIEWER-ROLE",
    "MUTANT-ORIGIN-CHECK",
    "MUTANT-SIGNUP-STATUS-SCOPE",
    "MUTANT-SOFT-DELETED-PREAUTH",
    "HARNESS-AGGREGATE-PRIVACY",
)
SECURITY_TABLES = (
    "users",
    "student_registrations",
    "student_profiles",
    "student_verifications",
    "guardian_consents",
    "otp_challenges",
    "otp_outbox",
    "auth_sessions",
    "audit_events",
)
PROFILE_PATH = "/api/v1/auth/student/profile"
EMAIL_PATH = "/api/v1/auth/student/verification/email/request"
STATUS_PATH = "/api/v1/auth/student/verification/status"
GUARDIAN_PATH = "/api/v1/auth/student/guardian-consent/complete"
REGISTER_PATH = "/api/v1/auth/student/register"
OTP_VERIFY_PATH = "/api/v1/auth/student/otp/verify"
OTP_RESEND_PATH = "/api/v1/auth/student/otp/resend"
LOGIN_START_PATH = "/api/v1/auth/student/login/otp/start"
RECOVERY_START_PATH = "/api/v1/auth/student/recovery/start"
SESSION_PATH = "/api/v1/auth/student/session"
SIGNUP_IDEMPOTENCY_KEY = "nyay2-postgres-gate-signup-0001"
SIGNUP_ACCEPTED_STATUS = 202
TRUSTED_ORIGIN = "http://localhost:1130"
PRIVATE_CAPABILITY_TABLES = (
    "otp_purpose_authorities",
    "otp_flows",
    "registration_idempotency_records",
)
OTP_PUBLIC_STATE_KEYS = frozenset(
    {
        "status",
        "purpose",
        "destination_masked",
        "attempts_left",
        "expires_in_seconds",
        "resend_in_seconds",
        "locked_for_seconds",
        "resend_allowed",
    }
)
ORIGIN_MATRIX_CASES = (
    ("missing", None, False),
    ("null", "null", False),
    ("wildcard", "*", False),
    ("malformed", "not-an-origin", False),
    ("lookalike", "http://localhost.invalid:1130", False),
    ("prefix", "http://localhost:1130.invalid", False),
    ("slash", "http://localhost:1130/", False),
    ("path", "http://localhost:1130/path", False),
    ("userinfo", "http://user@localhost:1130", False),
    ("query", "http://localhost:1130?mode=qa", False),
    ("fragment", "http://localhost:1130#fragment", False),
    ("cross_scheme", "https://localhost:1130", False),
    ("cross_host", "http://127.0.0.1:1130", False),
    ("cross_port", "http://localhost:1131", False),
    ("duplicate", (TRUSTED_ORIGIN, TRUSTED_ORIGIN), False),
    ("trusted", TRUSTED_ORIGIN, True),
)

_UUID_TEXT = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_EMAIL_TEXT = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_MOBILE_TEXT = re.compile(r"(?<!\d)\d{10}(?!\d)")
_URL_TEXT = re.compile(r"(?i)\b(?:postgres(?:ql)?|https?)\+?[^\s:]*://")


class Blocked(RuntimeError):
    """A target-runtime prerequisite was absent; this is never a pass."""


class ScratchCleanupFailure(RuntimeError):
    """The disposable database could not be removed; this is always fatal."""


class ProductGateFailure(RuntimeError):
    """A product/schema assertion failed after the target runtime was available."""


def _reject_ambient_libpq_environment() -> None:
    """Reject libpq routing/credential overrides without echoing their values."""

    if any(key in LIBPQ_AMBIENT_KEYS or key.startswith("PGSSL") for key in os.environ):
        raise Blocked("ambient libpq routing or credential environment is not allowed")


def _safe_local_postgres_url(raw: str) -> URL:
    """Accept only an unambiguous query-free loopback PostgreSQL URL."""

    _reject_ambient_libpq_environment()
    if "://" not in raw:
        raise Blocked("a valid PostgreSQL URL is required")
    authority = re.split(r"[/?#]", raw.split("://", 1)[1], maxsplit=1)[0]
    if "%" in authority or authority.count("@") > 1:
        raise Blocked("the PostgreSQL URL authority is ambiguous")
    try:
        url = make_url(raw)
    except Exception as exc:  # noqa: BLE001 - never disclose the supplied URL
        raise Blocked("a valid PostgreSQL URL is required") from exc
    if url.get_backend_name() != "postgresql":
        raise Blocked("a PostgreSQL URL is required")
    if url.query:
        # libpq query options can replace host/port/credentials even when the
        # visible URL authority is loopback.  This gate needs no query option.
        raise Blocked("the scratch-database gate rejects PostgreSQL URL queries")
    host = (url.host or "").casefold()
    if host == "localhost":
        return url
    try:
        if ipaddress.ip_address(host).is_loopback:
            return url
    except ValueError:
        pass
    raise Blocked("the scratch-database gate accepts loopback PostgreSQL only")


def _database_url(base: URL, database: str) -> str:
    return base.set(database=database).render_as_string(hide_password=False)


def _admin_execute(base: URL, statement: str) -> None:
    admin = create_engine(
        _database_url(base, "postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        with admin.connect() as connection:
            connection.execute(text(statement))
    finally:
        admin.dispose()


def _drop_scratch(base: URL, name: str) -> None:
    # ``name`` is generated from a fixed prefix plus uuid.hex, never user input.
    try:
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:  # pragma: no cover - PostgreSQL <13 fallback
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}"')


def _create_scratch(base: URL, name: str) -> str:
    try:
        _drop_scratch(base, name)
        _admin_execute(base, f'CREATE DATABASE "{name}"')
    except Exception as exc:  # noqa: BLE001 - sanitized prerequisite failure
        raise Blocked("could not create the disposable scratch database") from exc
    return _database_url(base, name)


class _ScratchDatabaseManager:
    """Own exactly one isolated database and make cleanup part of the verdict."""

    def __init__(self, base: URL) -> None:
        self.base = base
        self.records: list[dict[str, Any]] = []

    def run(self, purpose: str, operation: Callable[[str], Any]) -> Any:
        name = f"nyay2_auth_{uuid.uuid4().hex[:12]}"
        record: dict[str, Any] = {
            "purpose": purpose,
            "created": False,
            "cleanup": "NOT_CREATED",
        }
        self.records.append(record)
        scratch_url = _create_scratch(self.base, name)
        record["created"] = True
        try:
            return operation(scratch_url)
        finally:
            try:
                _drop_scratch(self.base, name)
            except Exception as exc:  # noqa: BLE001 - fatal, sanitized cleanup
                record["cleanup"] = "FAIL"
                raise ScratchCleanupFailure(
                    "a disposable NYAY-2 database could not be removed"
                ) from exc
            record["cleanup"] = "PASS"

    @property
    def scratch_created(self) -> bool:
        return any(record["created"] for record in self.records)

    def summary(self) -> dict[str, Any]:
        created = sum(record["created"] is True for record in self.records)
        removed = sum(record["cleanup"] == "PASS" for record in self.records)
        failed = sum(record["cleanup"] == "FAIL" for record in self.records)
        return {
            "created": created,
            "removed": removed,
            "cleanup_failed": failed,
            "all_created_removed": created == removed and failed == 0,
            # Purposes are fixed harness labels; database names are never kept.
            "purposes": [record["purpose"] for record in self.records],
        }


def _run_alembic(scratch_url: str, *arguments: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env={
            **os.environ,
            "APP_ENV": "testing",
            "DATABASE_URL": scratch_url,
            "NYAY19_ISOLATED_MIGRATION_EXECUTE": "1",
        },
        capture_output=True,
        text=True,
        timeout=180,
    )
    # Driver output can contain a credential-bearing URL.  Retain only the
    # command arguments and return code in evidence.
    return {"arguments": list(arguments), "returncode": result.returncode}


def _safe_response_signature(response: Any) -> dict[str, Any]:
    """Summarize a response without retaining request input or response values."""

    signature: dict[str, Any] = {"status_code": int(response.status_code)}
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - a non-JSON failure remains typed by status
        signature["shape"] = "non_json"
        return signature
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        code = detail.get("code")
        signature["shape"] = "typed_detail"
        signature["code"] = code if isinstance(code, str) else "absent"
    elif isinstance(detail, list):
        signature["shape"] = "validation"
        signature["errors"] = sorted(
            {
                (
                    str(item.get("type", "unknown")),
                    ".".join(str(part) for part in item.get("loc", ())),
                )
                for item in detail
                if isinstance(item, dict)
            }
        )
    elif isinstance(payload, dict):
        signature["shape"] = "object"
        signature["keys"] = sorted(str(key) for key in payload)
    else:
        signature["shape"] = "other_json"
    return signature


def _safe_response_object(response: Any) -> dict[str, Any] | None:
    """Return only an object response; malformed JSON remains a failed oracle."""

    try:
        payload = response.json()
    except Exception:  # noqa: BLE001 - response content is never retained
        return None
    return payload if isinstance(payload, dict) else None


def _strict_cookie_attributes(
    raw_header: str,
    cookie_name: str,
) -> dict[str, tuple[str | None, ...]] | None:
    """Parse one Set-Cookie field without last-attribute-wins ambiguity."""

    allowed_attributes = {
        "domain",
        "expires",
        "httponly",
        "max-age",
        "partitioned",
        "path",
        "samesite",
        "secure",
    }
    if not isinstance(raw_header, str) or not raw_header:
        return None
    pieces = raw_header.split(";")
    cookie_pair = pieces[0].strip()
    pair_name, separator, pair_value = cookie_pair.partition("=")
    if (
        separator != "="
        or pair_name.strip() != cookie_name
        or not pair_value
    ):
        return None

    attributes: dict[str, list[str | None]] = {}
    for raw_attribute in pieces[1:]:
        attribute = raw_attribute.strip()
        if not attribute:
            return None
        name, valued, value = attribute.partition("=")
        normalized_name = name.strip().casefold()
        if (
            not normalized_name
            or normalized_name not in allowed_attributes
            or normalized_name in attributes
        ):
            return None
        attributes[normalized_name] = [value.strip() if valued else None]

    required_once = {"httponly", "max-age", "path", "samesite"}
    if not required_once.issubset(attributes) or "domain" in attributes:
        return None
    if attributes["httponly"] != [None]:
        return None
    return {name: tuple(values) for name, values in attributes.items()}


def _named_cookie_contract(
    response: Any,
    cookie_name: str,
    *,
    expected_value: str | None,
    expected_path: str,
    expected_same_site: str,
) -> dict[str, bool]:
    """Inspect one named Set-Cookie without retaining its bearer value."""

    result = {
        "present_once": False,
        "value_matches": False,
        "httponly": False,
        "host_only": False,
        "path_exact": False,
        "same_site_exact": False,
        "persistent": False,
    }
    if (
        not cookie_name
        or not isinstance(expected_value, str)
        or not expected_value
        or expected_path not in {"/", "/api/v1"}
        or expected_same_site not in {"lax", "strict"}
    ):
        return result
    try:
        values = list(response.headers.get_list("set-cookie"))
    except Exception:  # noqa: BLE001 - malformed headers fail closed
        return result
    matching = []
    malformed = False
    for value in values:
        jar = SimpleCookie()
        try:
            jar.load(value)
        except (CookieError, TypeError, ValueError):
            malformed = True
            continue
        if cookie_name in jar:
            # A Set-Cookie field is one cookie. Reject an ambiguously combined
            # field instead of borrowing attributes from an adjacent cookie.
            if tuple(jar) != (cookie_name,):
                malformed = True
                continue
            attributes = _strict_cookie_attributes(value, cookie_name)
            if attributes is None:
                malformed = True
                continue
            matching.append((jar[cookie_name], attributes))
    if malformed or len(matching) != 1:
        return result
    morsel, attributes = matching[0]
    try:
        persistent = int(str(morsel["max-age"])) > 0
    except (TypeError, ValueError):
        persistent = False
    result.update(
        {
            "present_once": True,
            "value_matches": secrets.compare_digest(
                str(morsel.value), expected_value
            ),
            "httponly": attributes.get("httponly") == (None,),
            "host_only": "domain" not in attributes,
            "path_exact": morsel["path"] == expected_path,
            "same_site_exact": (
                str(morsel["samesite"]).casefold() == expected_same_site
            ),
            "persistent": persistent,
        }
    )
    return result


def _cookie_contract_passes(contract: dict[str, Any]) -> bool:
    """Fail closed on an incomplete or false cookie-attribute contract."""

    expected = {
        "present_once",
        "value_matches",
        "httponly",
        "host_only",
        "path_exact",
        "same_site_exact",
        "persistent",
    }
    return set(contract) == expected and all(
        contract.get(key) is True for key in expected
    )


def _ordered_cookie_header_matches(
    raw_header: str,
    *,
    cookie_name: str,
    expected_value: str | None,
    expected_path: str,
    expected_same_site: str,
    expected_max_age: int | None,
) -> bool:
    """Match one exact cookie slot without projecting its bearer value."""

    if (
        not cookie_name
        or expected_path not in {"/", "/api/v1"}
        or expected_same_site not in {"lax", "strict"}
    ):
        return False
    jar = SimpleCookie()
    try:
        jar.load(raw_header)
    except (CookieError, TypeError, ValueError):
        return False
    if tuple(jar) != (cookie_name,):
        return False
    attributes = _strict_cookie_attributes(raw_header, cookie_name)
    if attributes is None:
        return False
    required_attributes = {"httponly", "max-age", "path", "samesite"}
    permitted_attributes = required_attributes | {"secure"}
    if expected_max_age == 0:
        permitted_attributes.add("expires")
    if not required_attributes.issubset(attributes):
        return False
    if not set(attributes).issubset(permitted_attributes):
        return False
    if attributes.get("httponly") != (None,):
        return False
    if "secure" in attributes and attributes["secure"] != (None,):
        return False
    if attributes.get("path") != (expected_path,):
        return False
    same_site = attributes.get("samesite")
    if (
        same_site is None
        or len(same_site) != 1
        or not isinstance(same_site[0], str)
        or same_site[0].casefold() != expected_same_site
    ):
        return False
    try:
        max_age = int(str(attributes["max-age"][0]))
    except (TypeError, ValueError):
        return False
    if expected_max_age is None:
        if max_age <= 0:
            return False
    elif max_age != expected_max_age:
        return False
    actual_value = str(jar[cookie_name].value)
    if expected_value is None:
        return actual_value == ""
    return bool(expected_value) and secrets.compare_digest(
        actual_value, expected_value
    )


def _signup_verify_cookie_contract(
    response: Any,
    *,
    session_cookie_name: str,
    flow_cookie_name: str,
    expected_session_value: str | None,
) -> dict[str, bool]:
    """Require the ordered dual-path rotation emitted by signup verification."""

    result = {
        "exact_set_cookie_count": False,
        "legacy_session_retired_first": False,
        "current_session_issued_second": False,
        "otp_flow_retired_third": False,
    }
    if (
        not session_cookie_name
        or not flow_cookie_name
        or session_cookie_name == flow_cookie_name
        or not isinstance(expected_session_value, str)
        or not expected_session_value
    ):
        return result
    try:
        values = list(response.headers.get_list("set-cookie"))
    except Exception:  # noqa: BLE001 - malformed headers fail closed
        return result
    if len(values) != 3:
        return result
    result.update(
        {
            "exact_set_cookie_count": True,
            "legacy_session_retired_first": _ordered_cookie_header_matches(
                values[0],
                cookie_name=session_cookie_name,
                expected_value=None,
                expected_path="/api/v1",
                expected_same_site="strict",
                expected_max_age=0,
            ),
            "current_session_issued_second": _ordered_cookie_header_matches(
                values[1],
                cookie_name=session_cookie_name,
                expected_value=expected_session_value,
                expected_path="/",
                expected_same_site="lax",
                expected_max_age=None,
            ),
            "otp_flow_retired_third": _ordered_cookie_header_matches(
                values[2],
                cookie_name=flow_cookie_name,
                expected_value=None,
                expected_path="/api/v1",
                expected_same_site="strict",
                expected_max_age=0,
            ),
        }
    )
    return result


def _signup_verify_cookie_contract_passes(contract: dict[str, Any]) -> bool:
    """Fail closed unless every exact signup-verification cookie slot passed."""

    expected = {
        "exact_set_cookie_count",
        "legacy_session_retired_first",
        "current_session_issued_second",
        "otp_flow_retired_third",
    }
    return set(contract) == expected and all(
        contract.get(key) is True for key in expected
    )


def _raw_values_absent_from_json(
    raw_values: tuple[str | None, ...],
    payloads: tuple[Any, ...],
) -> bool:
    """Compare private values locally; never return or report the values."""

    if not raw_values or any(
        not isinstance(value, str) or not value for value in raw_values
    ):
        return False
    try:
        serialized = json.dumps(
            payloads,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return False
    return all(value not in serialized for value in raw_values if value is not None)


def _public_otp_responses_match(
    left: Any,
    right: Any,
    *,
    expected_purpose: str,
    expected_masked_last4: str,
) -> bool:
    """Compare complete public OTP state and its privacy headers in memory."""

    if (
        expected_purpose not in {"login", "recovery"}
        or not isinstance(expected_masked_last4, str)
        or re.fullmatch(r"[0-9]{4}", expected_masked_last4) is None
    ):
        return False
    expected_destination = f"••••••{expected_masked_last4}"
    left_payload = _safe_response_object(left)
    right_payload = _safe_response_object(right)
    if left_payload is None or right_payload is None:
        return False
    if (
        set(left_payload) != OTP_PUBLIC_STATE_KEYS
        or set(right_payload) != OTP_PUBLIC_STATE_KEYS
    ):
        return False

    def is_nonnegative_integer(value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    def is_live_decoy_projection(payload: dict[str, Any]) -> bool:
        destination = payload.get("destination_masked")
        return bool(
            payload.get("status") == "pending"
            and payload.get("purpose") == expected_purpose
            and destination == expected_destination
            and is_nonnegative_integer(payload.get("attempts_left"))
            and payload.get("attempts_left", 0) > 0
            and is_nonnegative_integer(payload.get("expires_in_seconds"))
            and payload.get("expires_in_seconds", 0) > 0
            and is_nonnegative_integer(payload.get("resend_in_seconds"))
            and is_nonnegative_integer(payload.get("locked_for_seconds"))
            and payload.get("locked_for_seconds") == 0
            and payload.get("resend_allowed") is False
        )

    if not is_live_decoy_projection(left_payload):
        return False
    if not is_live_decoy_projection(right_payload):
        return False
    expected_headers = (
        "private, no-store",
        "Cookie",
        "application/json",
    )

    def safe_headers(response: Any) -> tuple[str, str, str]:
        content_type = str(response.headers.get("content-type", ""))
        return (
            str(response.headers.get("cache-control", "")),
            str(response.headers.get("vary", "")),
            content_type.split(";", 1)[0],
        )

    return bool(
        int(left.status_code) == 202
        and int(right.status_code) == 202
        and left_payload == right_payload
        and safe_headers(left) == expected_headers
        and safe_headers(right) == expected_headers
    )


def _privacy_findings(value: Any, path: str = "report") -> list[str]:
    """Return aggregate finding classes; never copy the offending value."""

    findings: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            findings.extend(_privacy_findings(item, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            findings.extend(_privacy_findings(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        checks = (
            ("uuid", _UUID_TEXT),
            ("email", _EMAIL_TEXT),
            ("mobile", _MOBILE_TEXT),
            ("database_or_http_url", _URL_TEXT),
        )
        for label, pattern in checks:
            if pattern.search(value):
                findings.append(f"{path}:{label}")
    return findings


def _assertion(identifier: str, passed: bool, **metrics: Any) -> dict[str, Any]:
    return {"id": identifier, "passed": bool(passed), "metrics": metrics}


def _is_postgresql_16_with_pgvector(
    server_version_num: int, vector_version: object
) -> bool:
    """Pin authoritative evidence to major 16, not merely 16-or-newer."""

    return 160000 <= server_version_num < 170000 and bool(vector_version)


def _bootstrap_expiry_passes(observation: dict[str, Any]) -> bool:
    """Pure fail-closed evaluator for the one-use signup cookie capability."""

    return bool(
        observation.get("resend_status") == 401
        and observation.get("resend_code") == "otp_flow_unavailable"
        and observation.get("verify_status") == 401
        and observation.get("verify_code") == "otp_failed"
        and observation.get("challenge_delta") == 0
        and observation.get("outbox_delta") == 0
        and observation.get("delivery_delta") == 0
        and observation.get("session_delta") == 0
        and observation.get("audit_delta") == 0
        and observation.get("all_security_row_deltas_zero") is True
        and observation.get("business_state_unchanged") is True
        and observation.get("private_capability_state_unchanged") is True
        and observation.get("cookie_issued") is False
    )


def _evaluate_assertions(assertions: list[dict[str, Any]]) -> dict[str, Any]:
    """Fail closed on omissions, duplicates, substitutions, or false values."""

    identifiers = [
        item.get("id") if isinstance(item.get("id"), str) else "<invalid>"
        for item in assertions
    ]
    counts = {
        identifier: identifiers.count(identifier) for identifier in set(identifiers)
    }
    missing_count = sum(
        identifier not in identifiers for identifier in REQUIRED_ASSERTION_IDS
    )
    extra_count = sum(
        identifier not in REQUIRED_ASSERTION_IDS for identifier in identifiers
    )
    duplicate_count = sum(max(0, count - 1) for count in counts.values())
    reordered = bool(
        missing_count == 0
        and extra_count == 0
        and duplicate_count == 0
        and tuple(identifiers) != REQUIRED_ASSERTION_IDS
    )
    exact_inventory = tuple(identifiers) == REQUIRED_ASSERTION_IDS
    passed = sum(
        item.get("id") in REQUIRED_ASSERTION_IDS and item.get("passed") is True
        for item in assertions
    )
    failed = [
        str(item.get("id"))
        for item in assertions
        if item.get("id") in REQUIRED_ASSERTION_IDS and item.get("passed") is not True
    ]
    return {
        "exact_inventory": exact_inventory,
        "required": len(REQUIRED_ASSERTION_IDS),
        "passed": passed,
        "failed": sorted(failed),
        "inventory_failures": {
            "missing": missing_count,
            "extra": extra_count,
            "duplicate": duplicate_count,
            "reordered": reordered,
        },
        "overall_pass": exact_inventory and passed == len(REQUIRED_ASSERTION_IDS),
    }


def _table_counts(session_factory: sessionmaker[Session]) -> dict[str, int]:
    """Count security tables without retaining row identifiers or content."""

    with session_factory() as session:
        return {
            table: int(session.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)
            for table in SECURITY_TABLES
        }


def _business_state_digest(session_factory: sessionmaker[Session]) -> str:
    """Internal equality oracle; the digest is not placed in final evidence."""

    from app.db.models.audit import AuditEvent
    from app.models.registration import (
        AuthSession,
        GuardianConsent,
        OtpChallenge,
        OtpOutbox,
        StudentProfile,
        StudentRegistration,
        StudentVerification,
        User,
    )

    with session_factory() as session:
        rows: list[tuple[Any, ...]] = []
        rows.extend(
            (
                "user",
                str(row.id),
                row.role,
                row.status,
                row.deleted_at.isoformat() if row.deleted_at else None,
            )
            for row in session.scalars(select(User).order_by(User.id))
        )
        rows.extend(
            (
                "registration",
                str(row.id),
                str(row.user_id),
                row.status,
                row.dob_hash_state,
                row.institution_ref,
                row.is_minor,
                row.deleted_at.isoformat() if row.deleted_at else None,
            )
            for row in session.scalars(
                select(StudentRegistration).order_by(StudentRegistration.id)
            )
        )
        rows.extend(
            (
                "profile",
                str(row.id),
                str(row.registration_id),
                row.college,
                row.year_of_study,
                row.enrolment_hash,
                row.institutional_email_hash,
                row.bar_enrolment_hash,
            )
            for row in session.scalars(
                select(StudentProfile).order_by(StudentProfile.id)
            )
        )
        rows.extend(
            (
                "verification",
                str(row.id),
                str(row.registration_id),
                row.method,
                row.status,
            )
            for row in session.scalars(
                select(StudentVerification).order_by(StudentVerification.id)
            )
        )
        rows.extend(
            (
                "guardian",
                str(row.id),
                str(row.registration_id),
                row.status,
                row.verified,
            )
            for row in session.scalars(
                select(GuardianConsent).order_by(GuardianConsent.id)
            )
        )
        rows.extend(
            (
                "challenge",
                str(row.id),
                str(row.registration_id),
                row.purpose,
                row.verifier_hash,
                row.attempts,
                row.max_attempts,
                row.expires_at.isoformat(),
                row.consumed_at.isoformat() if row.consumed_at else None,
                row.locked_until.isoformat() if row.locked_until else None,
            )
            for row in session.scalars(select(OtpChallenge).order_by(OtpChallenge.id))
        )
        rows.extend(
            (
                "outbox",
                str(row.id),
                str(row.challenge_id),
                row.status,
                row.attempts,
                row.code_ct,
                row.destination_ct,
                row.delivered_at.isoformat() if row.delivered_at else None,
            )
            for row in session.scalars(select(OtpOutbox).order_by(OtpOutbox.id))
        )
        rows.extend(
            (
                "session",
                str(row.id),
                str(row.user_id),
                row.token_hash,
                row.status,
                row.expires_at.isoformat(),
                row.last_seen_at.isoformat(),
                row.revoked_at.isoformat() if row.revoked_at else None,
            )
            for row in session.scalars(select(AuthSession).order_by(AuthSession.id))
        )
        rows.extend(
            (
                "audit",
                str(row.id),
                str(row.actor_user_id) if row.actor_user_id else None,
                row.actor_role,
                row.action,
                row.resource_type,
                str(row.resource_id) if row.resource_id else None,
            )
            for row in session.scalars(select(AuditEvent).order_by(AuditEvent.id))
        )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _private_capability_snapshot(
    session_factory: sessionmaker[Session],
    *,
    scope: dict[str, tuple[uuid.UUID, ...]] | None = None,
) -> dict[str, Any]:
    """Fingerprint only OTP capability/ledger rows; values never leave memory."""

    from app.models.registration import (
        OtpFlow,
        OtpPurposeAuthority,
        RegistrationIdempotencyRecord,
    )

    models = {
        "otp_purpose_authorities": OtpPurposeAuthority,
        "otp_flows": OtpFlow,
        "registration_idempotency_records": RegistrationIdempotencyRecord,
    }
    if scope is not None and set(scope) != set(PRIVATE_CAPABILITY_TABLES):
        raise ProductGateFailure("private capability snapshot scope is invalid")
    signatures: list[tuple[Any, ...]] = []
    selected_counts: dict[str, int] = {}
    global_counts: dict[str, int] = {}
    selected_scope: dict[str, tuple[uuid.UUID, ...]] = {}
    with session_factory() as session:
        for table_name in PRIVATE_CAPABILITY_TABLES:
            model = models[table_name]
            all_rows = list(session.scalars(select(model).order_by(model.id)))
            global_counts[table_name] = len(all_rows)
            allowed_ids = (
                {row.id for row in all_rows}
                if scope is None
                else set(scope[table_name])
            )
            selected = [row for row in all_rows if row.id in allowed_ids]
            selected_counts[table_name] = len(selected)
            selected_scope[table_name] = tuple(row.id for row in selected)
            for row in selected:
                signatures.append(
                    (
                        table_name,
                        tuple(
                            (column.name, getattr(row, column.name))
                            for column in row.__table__.columns
                        ),
                    )
                )
    return {
        "scope": selected_scope,
        "counts": selected_counts,
        "global_counts": global_counts,
        "fingerprint": hashlib.sha256(
            repr(signatures).encode("utf-8")
        ).hexdigest(),
    }


def _private_capability_state_unchanged(
    before: dict[str, Any],
    after: dict[str, Any],
) -> bool:
    """Compare scoped capability state without exposing either fingerprint."""

    before_fingerprint = before.get("fingerprint")
    after_fingerprint = after.get("fingerprint")
    return bool(
        isinstance(before_fingerprint, str)
        and isinstance(after_fingerprint, str)
        and before.get("counts") == after.get("counts")
        and secrets.compare_digest(before_fingerprint, after_fingerprint)
    )


def _private_capability_delta_is_exact(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    otp_purpose_authorities: int,
    otp_flows: int,
    registration_idempotency_records: int,
) -> bool:
    """Require the exact bounded global row delta for intentional decoys."""

    expected = {
        "otp_purpose_authorities": otp_purpose_authorities,
        "otp_flows": otp_flows,
        "registration_idempotency_records": registration_idempotency_records,
    }
    before_counts = before.get("global_counts")
    after_counts = after.get("global_counts")
    if not isinstance(before_counts, dict) or not isinstance(after_counts, dict):
        return False
    if set(before_counts) != set(PRIVATE_CAPABILITY_TABLES):
        return False
    if set(after_counts) != set(PRIVATE_CAPABILITY_TABLES):
        return False
    return all(
        after_counts.get(table_name, -1) - before_counts.get(table_name, -1)
        == delta
        for table_name, delta in expected.items()
    )


class _CapturingSender:
    """In-memory OTP provider; values never enter the report."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._idempotent: dict[str, tuple[str, str, str]] = {}

    def send(self, destination: str, code: str) -> None:
        self.sent.append((destination, code))

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> str:
        existing = self._idempotent.get(idempotency_token)
        if existing is not None:
            if existing[:2] != (destination, code):
                raise RuntimeError("OTP provider idempotency conflict")
            return existing[2]
        receipt = f"nyay2-gate-receipt-{len(self._idempotent) + 1}"
        self._idempotent[idempotency_token] = (destination, code, receipt)
        self.send(destination, code)
        return receipt


def _seed_actor(
    session_factory: sessionmaker[Session],
    *,
    label: str,
    role: str = "student",
    registration: bool = True,
    dob_hash_state: str = "verified",
    is_minor: bool = False,
    session_status: str = "active",
    expired: bool = False,
    user_status: str = "active",
    soft_deleted: bool = False,
    registration_deleted: bool = False,
    mobile_value: str | None = None,
    registration_status: str = "active",
) -> dict[str, Any]:
    """Create synthetic authority rows and return handles kept in memory only."""

    from app.core.crypto import encrypt, keyed_hash
    from app.models.registration import (
        AuthSession,
        StudentProfile,
        StudentRegistration,
        StudentVerification,
        User,
    )

    now = datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(32)
    with session_factory() as session:
        user = User(role=role, status=user_status)
        session.add(user)
        session.flush()
        reg = None
        profile = None
        verification = None
        if registration:
            identity = f"nyay2-{label}"
            mobile = mobile_value or f"{identity}-mobile"
            dob_value = "2012-01-02" if is_minor else "2000-01-02"
            reg = StudentRegistration(
                user_id=user.id,
                first_name="Test",
                middle_name=None,
                last_name="Actor",
                mobile_hash=keyed_hash(mobile),
                mobile_ct=encrypt(mobile),
                dob_hash=keyed_hash(dob_value),
                dob_ct=encrypt(dob_value),
                dob_hash_state=dob_hash_state,
                key_version="v1",
                institution_ref="Initial Institute",
                status=registration_status,
                is_minor=is_minor,
            )
            session.add(reg)
            session.flush()
            if soft_deleted:
                # A historical soft-delete can carry otherwise valid-looking
                # state.  Authorization must honor deleted_at itself rather
                # than accidentally relying on status/DOB-state correlation.
                reg.deleted_at = now
            if registration_deleted:
                erased_marker = f"[erased]:{reg.id.hex}"
                reg.status = "deleted"
                reg.dob_hash_state = "erased"
                reg.mobile_hash = erased_marker
                reg.dob_hash = erased_marker
                reg.mobile_ct = "[erased]"
                reg.dob_ct = "[erased]"
            profile = StudentProfile(
                registration_id=reg.id,
                college="Initial Institute",
                year_of_study="Year 1",
                enrolment_ct=encrypt(f"{identity}-enrolment"),
                enrolment_hash=keyed_hash(f"{identity}-enrolment"),
                institutional_email_ct=encrypt(
                    f"{identity}" + chr(64) + "college.invalid"
                ),
                institutional_email_hash=keyed_hash(
                    f"{identity}" + chr(64) + "college.invalid", lower=True
                ),
                key_version="v1",
                preferred_language="en",
                city="Gate City",
            )
            verification = StudentVerification(
                registration_id=reg.id,
                method="institutional_email",
                status="pending",
            )
            session.add_all([profile, verification])
        auth_session = AuthSession(
            user_id=user.id,
            token_hash=keyed_hash(raw_token),
            status=session_status,
            expires_at=now + (-timedelta(minutes=1) if expired else timedelta(hours=1)),
            last_seen_at=now,
            revoked_at=now if session_status == "revoked" else None,
        )
        session.add(auth_session)
        session.commit()
        return {
            "user_id": user.id,
            "registration_id": reg.id if reg else None,
            "profile_id": profile.id if profile else None,
            "verification_id": verification.id if verification else None,
            "token": raw_token,
            "mobile": mobile_value,
        }


def _client(app: FastAPI, cookie_name: str, token: str | None = None) -> TestClient:
    client = TestClient(app, raise_server_exceptions=False)
    if token:
        client.cookies.set(cookie_name, token)
    return client


def _otp_resend_payload() -> dict[str, object]:
    """Return the exact NYAY-4 resend body; UUID authority is prohibited."""

    return {}


def _trusted_mutation_headers() -> dict[str, str]:
    """Bind every cookie-authority mutation to the exact trusted origin."""

    return {"Origin": TRUSTED_ORIGIN}


def _profile_mutation_headers(
    label: str,
    *,
    headers: dict[str, str] | list[tuple[str, str]] | None = None,
) -> dict[str, str] | list[tuple[str, str]]:
    """Add one opaque profile key without normalizing repeated Origin rows."""

    if re.fullmatch(r"[A-Za-z0-9._~-]+", label) is None:
        raise ValueError("profile probe label must be opaque")
    key = f"nyay2-profile-{label}-0001"
    if headers is None:
        return {**_trusted_mutation_headers(), "Idempotency-Key": key}
    if isinstance(headers, list):
        return [*headers, ("Idempotency-Key", key)]
    return {**headers, "Idempotency-Key": key}


def _signup_registration_headers() -> dict[str, str]:
    """Use the current mandatory registration idempotency contract."""

    return {
        **_trusted_mutation_headers(),
        "Idempotency-Key": SIGNUP_IDEMPOTENCY_KEY,
    }


def _signup_registration_payload(mobile: str) -> dict[str, Any]:
    """Use the current independent Terms and Privacy legal authorities."""

    return {
        "first_name": "Gate",
        "last_name": "Signup",
        "mobile": mobile,
        "dob": "2000-01-02",
        "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    }


def _otp_verify_payload(code: str) -> dict[str, str]:
    """Return the exact NYAY-4 verification body; the cookie owns authority."""

    return {"code": code}


def _require_private_signup_flow(
    session_factory: sessionmaker[Session],
    raw_token: str | None,
) -> dict[str, Any]:
    """Resolve private graph handles from the cookie hash, never response JSON."""

    from app.models.registration import OtpFlow
    from app.services.otp_flow_service import flow_token_hash

    if not raw_token:
        raise ProductGateFailure("signup cookie flow graph is unavailable")
    with session_factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(OtpFlow.token_hash == flow_token_hash(raw_token))
        )
        if (
            flow is None
            or flow.registration_id is None
            or flow.authority_id is None
        ):
            raise ProductGateFailure("signup cookie flow graph is unavailable")
        return {
            "registration_id": flow.registration_id,
            "authority_id": flow.authority_id,
            "challenge_id": flow.challenge_id,
        }


def _private_decoy_flow_is_bound(
    session_factory: sessionmaker[Session],
    raw_token: str | None,
    *,
    purpose: str,
) -> bool:
    """Prove a cookie-owned decoy graph has no registration authority."""

    from app.models.registration import OtpFlow, OtpPurposeAuthority
    from app.services.otp_flow_service import flow_token_hash

    if not raw_token or purpose not in {"login", "recovery"}:
        return False
    with session_factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(OtpFlow.token_hash == flow_token_hash(raw_token))
        )
        authority = (
            session.get(OtpPurposeAuthority, flow.authority_id)
            if flow is not None
            else None
        )
        return bool(
            flow is not None
            and authority is not None
            and flow.purpose == purpose
            and authority.purpose == purpose
            and flow.authority_id == authority.id
            and flow.subject_hash == authority.subject_hash
            and flow.registration_id is None
            and authority.registration_id is None
            and flow.challenge_id is None
            and flow.state == "pending"
            and flow.consumed_at is None
        )


def _seed_private_signup_flow(
    session_factory: sessionmaker[Session],
    registration_id: uuid.UUID,
    *,
    destination: str,
    now: datetime | None = None,
) -> str:
    """Create a private stale-capability fixture without serializing its token."""

    from app.models.registration import OtpChallenge, StudentRegistration
    from app.services import otp_flow_service
    from app.services.otp_authority import lock_or_create_registration_authority

    now = now or datetime.now(timezone.utc)
    with session_factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        if registration is None:
            raise ProductGateFailure("signup cookie flow seed is unavailable")
        authority = lock_or_create_registration_authority(
            session, registration, "signup", now
        )
        challenge = session.scalar(
            select(OtpChallenge)
            .where(
                OtpChallenge.registration_id == registration.id,
                OtpChallenge.authority_id == authority.id,
                OtpChallenge.purpose == "signup",
                OtpChallenge.delivery_state == "active",
                OtpChallenge.consumed_at.is_(None),
            )
            .order_by(OtpChallenge.created_at.desc())
        )
        raw_token, _ = otp_flow_service.create_flow(
            session,
            authority,
            now=now,
            destination=destination,
            challenge=challenge,
            registration_id=registration.id,
        )
        session.commit()
        return raw_token


def _unsafe_flow_graph_for_mutation(
    session: Session,
    raw_token: str | None,
) -> tuple[Any, Any] | None:
    """Explicit mutant: retain graph binding but remove account eligibility."""

    from app.models.registration import OtpChallenge, OtpFlow, OtpPurposeAuthority
    from app.services.otp_flow_service import flow_token_hash

    if not raw_token:
        return None
    flow = session.scalar(
        select(OtpFlow)
        .where(OtpFlow.token_hash == flow_token_hash(raw_token))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if flow is None or flow.registration_idempotency_record_id is not None:
        return None
    authority = session.scalar(
        select(OtpPurposeAuthority)
        .where(OtpPurposeAuthority.id == flow.authority_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        authority is None
        or authority.id != flow.authority_id
        or authority.subject_hash != flow.subject_hash
        or authority.purpose != flow.purpose
        or authority.registration_id != flow.registration_id
    ):
        return None
    if flow.challenge_id is not None:
        challenge = session.get(OtpChallenge, flow.challenge_id)
        if (
            challenge is None
            or challenge.authority_id != authority.id
            or challenge.registration_id != flow.registration_id
            or challenge.purpose != flow.purpose
        ):
            return None
    return authority, flow


def _profile_payload(
    marker: str,
    *,
    expected_profile_version: int,
) -> dict[str, Any]:
    marker_roll = (
        int.from_bytes(
            hashlib.sha256(marker.encode("utf-8")).digest()[:3],
            "big",
        )
        % 900_000
        + 100_000
    )
    return {
        "expected_profile_version": expected_profile_version,
        "college": "NALSAR University of Law",
        "year_of_study": "4th",
        "enrolment_number": f"QA/{marker_roll}/2026",
        "institutional_email": (f"gate-{marker}" + chr(64) + "college.invalid"),
        "bar_enrolment_number": None,
    }


def _institutional_email_request_payload() -> dict[str, object]:
    """The saved canonical profile email is the only request authority."""

    return {}


def _email_status_projection_passes(
    *,
    email_status: int,
    email_payload: object,
    status_status: int,
    status_payload: object,
) -> bool:
    """Require the public pending projection and internal review lifecycle."""

    return bool(
        email_status == 202
        and isinstance(email_payload, dict)
        and email_payload.get("institutional_email_status") == "pending"
        and status_status == 200
        and isinstance(status_payload, dict)
        and status_payload.get("status") == "in_review"
    )


def _verification_transition_payload(
    registration_id: object,
    *,
    status: str,
    expected_profile_version: int,
) -> dict[str, object]:
    """Build the review transition's explicit target and profile CAS wire."""

    return {
        "registration_id": str(registration_id),
        "status": status,
        "expected_profile_version": expected_profile_version,
    }


def _current_profile_version(
    session_factory: sessionmaker[Session],
    registration_id: uuid.UUID,
) -> int:
    """Read the synthetic actor's server version for an exact CAS request."""

    from app.models.registration import StudentProfile

    with session_factory() as session:
        profile = session.scalar(
            select(StudentProfile).where(
                StudentProfile.registration_id == registration_id
            )
        )
        if profile is None:
            raise ProductGateFailure("profile CAS fixture is unavailable")
        return int(profile.profile_version)


def _run_api_probes(
    engine: Engine,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Exercise real FastAPI routing, dependencies, ORM, and PostgreSQL commits."""

    from app.api.v1 import auth_student as endpoint
    from app.core import auth as core_auth
    from app.core.auth import ActorContext, Role
    from app.core.config import settings
    from app.core.crypto import KeyRing, keyed_hash, otp_verifier, override_keyring
    from app.db.models.audit import AuditEvent
    from app.db.session import get_session
    from app.models.registration import (
        OtpChallenge,
        OtpPurposeAuthority,
        StudentProfile,
        StudentRegistration,
        StudentVerification,
    )
    from app.services import (
        login_service,
        otp_flow_service,
        otp_service,
        profile_service,
    )
    from app.services.otp_authority import lock_or_create_registration_authority

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    def request_session() -> Iterator[Session]:
        session = factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        else:
            session.rollback()
        finally:
            session.close()

    sender = _CapturingSender()
    app = FastAPI()
    app.include_router(endpoint.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[endpoint.get_otp_sender] = lambda: sender
    app.dependency_overrides[endpoint.get_outbox_session_factory] = lambda: factory

    previous_env = settings.app_env
    previous_origins = list(settings.cors_origins)
    previous_keyring = None
    settings.app_env = "testing"
    settings.cors_origins = [TRUSTED_ORIGIN]
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": b"nyay2-postgres-gate-synthetic-key-v1"},
        )
    )

    assertions: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    try:
        cookie_name = settings.auth_session_cookie_name
        flow_cookie_name = settings.otp_flow_cookie_name
        owner_a = _seed_actor(factory, label="owner-a", is_minor=True)
        owner_b = _seed_actor(factory, label="owner-b")
        missing = _seed_actor(factory, label="missing", registration=False)
        quarantined = _seed_actor(
            factory,
            label="quarantined",
            dob_hash_state="quarantined",
        )
        deleted_user = _seed_actor(factory, label="deleted-user", user_status="deleted")
        soft_deleted = _seed_actor(factory, label="soft-deleted", soft_deleted=True)
        registration_deleted = _seed_actor(
            factory,
            label="registration-deleted",
            registration_deleted=True,
        )
        soft_deleted_resend = _seed_actor(
            factory,
            label="soft-deleted-resend",
            soft_deleted=True,
            session_status="revoked",
            mobile_value="6" * 10,
            registration_status="otp_pending",
        )
        soft_deleted_verify = _seed_actor(
            factory,
            label="soft-deleted-verify",
            soft_deleted=True,
            session_status="revoked",
            mobile_value="5" * 10,
            registration_status="otp_pending",
        )
        soft_deleted_login = _seed_actor(
            factory,
            label="soft-deleted-login",
            soft_deleted=True,
            session_status="revoked",
            mobile_value="4" * 10,
        )
        soft_deleted_recovery = _seed_actor(
            factory,
            label="soft-deleted-recovery",
            soft_deleted=True,
            session_status="revoked",
            mobile_value="3" * 10,
        )
        soft_deleted_rotate = _seed_actor(
            factory,
            label="soft-deleted-rotate",
            soft_deleted=True,
            session_status="revoked",
            mobile_value="2" * 10,
        )
        soft_deleted_mutant = _seed_actor(
            factory,
            label="soft-deleted-mutant",
            soft_deleted=True,
            session_status="revoked",
            mobile_value="8" * 10,
            registration_status="otp_pending",
        )
        signup_code = "1" * 6
        signup_salt = secrets.token_hex(16)
        now = datetime.now(timezone.utc)
        with factory() as session:
            registration = session.get(
                StudentRegistration,
                soft_deleted_verify["registration_id"],
            )
            if registration is None:
                raise ProductGateFailure(
                    "soft-deleted OTP seed registration is unavailable"
                )
            authority = lock_or_create_registration_authority(
                session, registration, "signup", now
            )
            expires_at = now + timedelta(minutes=5)
            session.add(
                OtpChallenge(
                    registration_id=soft_deleted_verify["registration_id"],
                    authority_id=authority.id,
                    purpose="signup",
                    delivery_state="active",
                    verifier_hash=otp_verifier(signup_code, salt=signup_salt),
                    attempts=0,
                    max_attempts=3,
                    expires_at=expires_at,
                    metadata_json={
                        "salt": signup_salt,
                        "issued_at": now.isoformat(),
                    },
                )
            )
            authority.active_expires_at = expires_at
            session.commit()
        soft_deleted_resend_flow = _seed_private_signup_flow(
            factory,
            soft_deleted_resend["registration_id"],
            destination=str(soft_deleted_resend["mobile"]),
            now=now,
        )
        soft_deleted_verify_flow = _seed_private_signup_flow(
            factory,
            soft_deleted_verify["registration_id"],
            destination=str(soft_deleted_verify["mobile"]),
            now=now,
        )
        soft_deleted_mutant_flow = _seed_private_signup_flow(
            factory,
            soft_deleted_mutant["registration_id"],
            destination=str(soft_deleted_mutant["mobile"]),
            now=now,
        )
        revoked = _seed_actor(factory, label="revoked", session_status="revoked")
        expired = _seed_actor(factory, label="expired", expired=True)
        reviewer = _seed_actor(
            factory, label="reviewer", role="legal_reviewer", registration=False
        )

        owner_a_client = _client(app, cookie_name, owner_a["token"])
        owner_b_client = _client(app, cookie_name, owner_b["token"])

        # A real signup OTP proof must mint browser authority without returning
        # the bearer token in JSON or exposing it to JavaScript.
        signup_client = _client(app, cookie_name)
        signup_mobile = "7" * 10
        registered = signup_client.post(
            REGISTER_PATH,
            headers=_signup_registration_headers(),
            json=_signup_registration_payload(signup_mobile),
        )
        registered_payload = _safe_response_object(registered)
        signup_flow_token = signup_client.cookies.get(flow_cookie_name)
        if (
            registered.status_code != SIGNUP_ACCEPTED_STATUS
            or not isinstance(registered_payload, dict)
            or not signup_flow_token
            or len(sender.sent) != 1
        ):
            raise ProductGateFailure("signup cookie flow setup failed")
        registration_id_absent = bool(
            "registration_id" not in registered_payload
            and _UUID_TEXT.search(json.dumps(registered_payload, sort_keys=True))
            is None
        )
        flow_cookie_contract = _named_cookie_contract(
            registered,
            flow_cookie_name,
            expected_value=signup_flow_token,
            expected_path="/api/v1",
            expected_same_site="strict",
        )
        signup_private = _require_private_signup_flow(factory, signup_flow_token)
        signup_registration_id = signup_private["registration_id"]
        delivered_code = sender.sent[-1][1]
        verified = signup_client.post(
            OTP_VERIFY_PATH,
            headers=_trusted_mutation_headers(),
            json=_otp_verify_payload(delivered_code),
        )
        cookie_value = signup_client.cookies.get(cookie_name)
        session_probe = signup_client.get(SESSION_PATH)
        verify_payload = _safe_response_object(verified)
        session_payload = _safe_response_object(session_probe)
        session_cookie_contract = _signup_verify_cookie_contract(
            verified,
            session_cookie_name=cookie_name,
            flow_cookie_name=flow_cookie_name,
            expected_session_value=cookie_value,
        )
        raw_bearers_absent = _raw_values_absent_from_json(
            (signup_flow_token, cookie_value),
            (registered_payload, verify_payload, session_payload),
        )
        signup_passed = bool(
            registered.status_code == SIGNUP_ACCEPTED_STATUS
            and registration_id_absent
            and signup_flow_token
            and len(sender.sent) == 1
            and verified.status_code == 200
            and isinstance(verify_payload, dict)
            and cookie_value
            and _cookie_contract_passes(flow_cookie_contract)
            and _signup_verify_cookie_contract_passes(session_cookie_contract)
            and raw_bearers_absent
            and session_probe.status_code == 200
            and isinstance(session_payload, dict)
            and session_payload.get("authenticated") is True
        )
        assertions.append(
            _assertion(
                "CONTRACT-SIGNUP-MINTS-HTTPONLY-SESSION",
                signup_passed,
                register_status=registered.status_code,
                verify_status=verified.status_code,
                delivery_count=len(sender.sent),
                flow_cookie_present=bool(signup_flow_token),
                registration_id_absent=registration_id_absent,
                cookie_present=bool(cookie_value),
                flow_cookie_contract=flow_cookie_contract,
                session_cookie_contract=session_cookie_contract,
                raw_bearers_absent=raw_bearers_absent,
                session_authenticated=(
                    session_probe.status_code == 200
                    and isinstance(session_payload, dict)
                    and session_payload.get("authenticated") is True
                ),
            )
        )

        # The one-use HttpOnly flow cookie is the only public correlation
        # authority. Once its first proof activates the account, replaying that
        # exact private capability must fail before changing any challenge,
        # delivery, session, audit, or business state.
        bootstrap_client = _client(app, cookie_name)
        bootstrap_client.cookies.set(
            flow_cookie_name, signup_flow_token, path="/api/v1"
        )
        before_counts = _table_counts(factory)
        before_state = _business_state_digest(factory)
        before_private_capabilities = _private_capability_snapshot(factory)
        before_delivery = len(sender.sent)
        bootstrap_resend = bootstrap_client.post(
            OTP_RESEND_PATH,
            headers=_trusted_mutation_headers(),
            json=_otp_resend_payload(),
        )
        replay_code = (
            sender.sent[-1][1]
            if len(sender.sent) > before_delivery
            else delivered_code or "0" * 6
        )
        bootstrap_verify = bootstrap_client.post(
            OTP_VERIFY_PATH,
            headers=_trusted_mutation_headers(),
            json=_otp_verify_payload(replay_code),
        )
        after_counts = _table_counts(factory)
        after_state = _business_state_digest(factory)
        after_private_capabilities = _private_capability_snapshot(factory)
        resend_signature = _safe_response_signature(bootstrap_resend)
        replay_signature = _safe_response_signature(bootstrap_verify)
        bootstrap_observation = {
            "resend_status": bootstrap_resend.status_code,
            "resend_code": resend_signature.get("code"),
            "verify_status": bootstrap_verify.status_code,
            "verify_code": replay_signature.get("code"),
            "challenge_delta": after_counts["otp_challenges"]
            - before_counts["otp_challenges"],
            "outbox_delta": after_counts["otp_outbox"] - before_counts["otp_outbox"],
            "delivery_delta": len(sender.sent) - before_delivery,
            "session_delta": after_counts["auth_sessions"]
            - before_counts["auth_sessions"],
            "audit_delta": after_counts["audit_events"] - before_counts["audit_events"],
            "all_security_row_deltas_zero": before_counts == after_counts,
            "business_state_unchanged": before_state == after_state,
            "private_capability_state_unchanged": (
                _private_capability_state_unchanged(
                    before_private_capabilities,
                    after_private_capabilities,
                )
            ),
            "cookie_issued": bool(
                bootstrap_client.cookies.get(cookie_name)
                or "set-cookie" in bootstrap_resend.headers
                or "set-cookie" in bootstrap_verify.headers
            ),
        }
        bootstrap_expired = _bootstrap_expiry_passes(bootstrap_observation)
        assertions.append(
            _assertion(
                "AUTH-SIGNUP-BOOTSTRAP-EXPIRES-ON-ACTIVATION",
                bootstrap_expired,
                resend_response=resend_signature,
                verify_response=replay_signature,
                challenge_delta=bootstrap_observation["challenge_delta"],
                outbox_delta=bootstrap_observation["outbox_delta"],
                delivery_delta=bootstrap_observation["delivery_delta"],
                session_delta=bootstrap_observation["session_delta"],
                audit_delta=bootstrap_observation["audit_delta"],
                all_security_row_deltas_zero=bootstrap_observation[
                    "all_security_row_deltas_zero"
                ],
                business_state_unchanged=bootstrap_observation[
                    "business_state_unchanged"
                ],
                private_capability_state_unchanged=bootstrap_observation[
                    "private_capability_state_unchanged"
                ],
                cookie_issued=bootstrap_observation["cookie_issued"],
            )
        )

        valid_profile = _profile_payload(
            "owner-a",
            expected_profile_version=_current_profile_version(
                factory, owner_a["registration_id"]
            ),
        )

        # Every affected protected route must reject anonymous authority before
        # any business state changes. Include the status read so the matrix
        # covers the complete owner/reviewer surface, not only mutations.
        anonymous = _client(app, cookie_name)
        anonymous_calls = (
            (
                "profile",
                lambda: anonymous.patch(PROFILE_PATH, json=valid_profile),
            ),
            (
                "email_request",
                lambda: anonymous.post(
                    EMAIL_PATH,
                    json=_institutional_email_request_payload(),
                ),
            ),
            (
                "guardian_complete",
                lambda: anonymous.post(GUARDIAN_PATH, json={}),
            ),
            (
                "verification_transition",
                lambda: anonymous.post(
                    STATUS_PATH,
                    json=_verification_transition_payload(
                        owner_a["registration_id"],
                        status="verified",
                        expected_profile_version=valid_profile[
                            "expected_profile_version"
                        ],
                    ),
                ),
            ),
            ("verification_status", lambda: anonymous.get(STATUS_PATH)),
        )
        anonymous_observations = []
        for label, call in anonymous_calls:
            before_counts = _table_counts(factory)
            before_state = _business_state_digest(factory)
            response = call()
            anonymous_observations.append(
                {
                    "case": label,
                    "signature": _safe_response_signature(response),
                    "row_counts_unchanged": before_counts == _table_counts(factory),
                    "business_state_unchanged": before_state
                    == _business_state_digest(factory),
                }
            )
        anonymous_signatures = [item["signature"] for item in anonymous_observations]
        anonymous_passed = bool(
            all(
                signature.get("status_code") == 401
                and signature.get("code") == "authentication_required"
                for signature in anonymous_signatures
            )
            and len(
                {
                    json.dumps(signature, sort_keys=True)
                    for signature in anonymous_signatures
                }
            )
            == 1
            and all(
                item["row_counts_unchanged"] and item["business_state_unchanged"]
                for item in anonymous_observations
            )
        )
        assertions.append(
            _assertion(
                "AUTH-ANONYMOUS-401-NO-DELTA",
                anonymous_passed,
                cases=len(anonymous_observations),
                uniform_response=(
                    len(
                        {
                            json.dumps(signature, sort_keys=True)
                            for signature in anonymous_signatures
                        }
                    )
                    == 1
                ),
                all_row_counts_unchanged=all(
                    item["row_counts_unchanged"] for item in anonymous_observations
                ),
                all_business_state_unchanged=all(
                    item["business_state_unchanged"] for item in anonymous_observations
                ),
            )
        )

        # The owner succeeds without sending a registration UUID, and audit
        # authority must come from the resolved session.
        owner_response = owner_a_client.patch(
            PROFILE_PATH,
            headers=_profile_mutation_headers("owner-a"),
            json=valid_profile,
        )
        with factory() as session:
            owner_profile = session.scalar(
                select(StudentProfile).where(
                    StudentProfile.registration_id == owner_a["registration_id"]
                )
            )
            owner_audit = session.scalar(
                select(AuditEvent)
                .where(AuditEvent.action == "student.profile.section_updated")
                .order_by(AuditEvent.created_at.desc())
            )
            owner_success = bool(
                owner_response.status_code == 200
                and owner_profile is not None
                and owner_profile.college == valid_profile["college"]
                and owner_profile.enrolment_hash
                == keyed_hash(valid_profile["enrolment_number"])
                and owner_profile.institutional_email_hash
                == keyed_hash(valid_profile["institutional_email"], lower=True)
                and owner_audit is not None
                and owner_audit.actor_user_id == owner_a["user_id"]
                and owner_audit.actor_role == "student"
            )
        assertions.append(
            _assertion(
                "AUTH-OWNER-PROFILE-SUCCESS",
                owner_success,
                response=_safe_response_signature(owner_response),
                owner_row_selected=owner_success,
                audit_actor_bound=bool(
                    owner_audit is not None
                    and owner_audit.actor_user_id == owner_a["user_id"]
                ),
            )
        )

        # Email verification request and status discovery are protected yet do
        # not accept a registration identifier.
        email_response = owner_a_client.post(
            EMAIL_PATH,
            headers={"Origin": TRUSTED_ORIGIN},
            json=_institutional_email_request_payload(),
        )
        status_response = owner_a_client.get(STATUS_PATH)
        email_payload = _safe_response_object(email_response)
        status_payload = _safe_response_object(status_response)
        email_status_passed = _email_status_projection_passes(
            email_status=email_response.status_code,
            email_payload=email_payload,
            status_status=status_response.status_code,
            status_payload=status_payload,
        )
        assertions.append(
            _assertion(
                "AUTH-OWNER-EMAIL-AND-STATUS-SUCCESS",
                email_status_passed,
                email_response=_safe_response_signature(email_response),
                status_response=_safe_response_signature(status_response),
            )
        )

        # Owner B may change only B. There is no target selector in the request.
        with factory() as session:
            profile_a = session.scalar(
                select(StudentProfile).where(
                    StudentProfile.registration_id == owner_a["registration_id"]
                )
            )
            a_before = (
                profile_a.enrolment_hash,
                profile_a.institutional_email_hash,
            ) if profile_a else None
        b_payload = _profile_payload(
            "owner-b",
            expected_profile_version=_current_profile_version(
                factory, owner_b["registration_id"]
            ),
        )
        b_response = owner_b_client.patch(
            PROFILE_PATH,
            headers=_profile_mutation_headers("owner-b"),
            json=b_payload,
        )
        with factory() as session:
            profile_a = session.scalar(
                select(StudentProfile).where(
                    StudentProfile.registration_id == owner_a["registration_id"]
                )
            )
            profile_b = session.scalar(
                select(StudentProfile).where(
                    StudentProfile.registration_id == owner_b["registration_id"]
                )
            )
            cross_isolated = bool(
                b_response.status_code == 200
                and profile_a is not None
                and (
                    profile_a.enrolment_hash,
                    profile_a.institutional_email_hash,
                )
                == a_before
                and profile_b is not None
                and profile_b.college == b_payload["college"]
                and profile_b.enrolment_hash
                == keyed_hash(b_payload["enrolment_number"])
                and profile_b.institutional_email_hash
                == keyed_hash(b_payload["institutional_email"], lower=True)
            )
        assertions.append(
            _assertion(
                "AUTH-CROSS-OWNER-ISOLATION",
                cross_isolated,
                response=_safe_response_signature(b_response),
                selected_authenticated_owner=cross_isolated,
            )
        )

        # Old target-UUID calls are uniformly rejected for another owner's,
        # absent, and quarantined references, with no business delta.
        legacy_payloads = []
        for target in (
            owner_a["registration_id"],
            uuid.uuid4(),
            quarantined["registration_id"],
            soft_deleted["registration_id"],
            registration_deleted["registration_id"],
        ):
            payload = {**b_payload, "registration_id": str(target)}
            before_counts = _table_counts(factory)
            before_state = _business_state_digest(factory)
            response = owner_b_client.patch(
                PROFILE_PATH,
                headers={"Origin": TRUSTED_ORIGIN},
                json=payload,
            )
            legacy_payloads.append(
                {
                    "signature": _safe_response_signature(response),
                    "row_counts_unchanged": before_counts == _table_counts(factory),
                    "business_state_unchanged": before_state
                    == _business_state_digest(factory),
                }
            )
        legacy_signatures = [item["signature"] for item in legacy_payloads]
        legacy_symmetric = bool(
            all(signature.get("status_code") == 422 for signature in legacy_signatures)
            and len({json.dumps(item, sort_keys=True) for item in legacy_signatures})
            == 1
            and all(item["row_counts_unchanged"] for item in legacy_payloads)
            and all(item["business_state_unchanged"] for item in legacy_payloads)
        )
        assertions.append(
            _assertion(
                "AUTH-LEGACY-TARGET-SYMMETRY-NO-DELTA",
                legacy_symmetric,
                cases=len(legacy_payloads),
                uniform_response=bool(
                    legacy_signatures
                    and len(
                        {json.dumps(item, sort_keys=True) for item in legacy_signatures}
                    )
                    == 1
                ),
                all_row_counts_unchanged=all(
                    item["row_counts_unchanged"] for item in legacy_payloads
                ),
                all_business_state_unchanged=all(
                    item["business_state_unchanged"] for item in legacy_payloads
                ),
            )
        )

        # Every protected route rejects old registration UUID authority. GET
        # query strings need an explicit fail-closed guard because FastAPI would
        # otherwise ignore unknown query parameters.
        protected_uuid_responses = [
            owner_a_client.patch(
                PROFILE_PATH,
                headers={"Origin": TRUSTED_ORIGIN},
                json={
                    **valid_profile,
                    "registration_id": str(owner_a["registration_id"]),
                },
            ),
            owner_a_client.post(
                EMAIL_PATH,
                headers={"Origin": TRUSTED_ORIGIN},
                json={
                    "registration_id": str(owner_a["registration_id"]),
                },
            ),
            owner_a_client.post(
                GUARDIAN_PATH,
                headers={"Origin": TRUSTED_ORIGIN},
                json={"registration_id": str(owner_a["registration_id"])},
            ),
            owner_a_client.get(
                STATUS_PATH,
                params={"registration_id": str(owner_a["registration_id"])},
            ),
        ]
        protected_uuid_passed = all(
            response.status_code in {400, 422} for response in protected_uuid_responses
        )
        assertions.append(
            _assertion(
                "CONTRACT-PROTECTED-UUIDS-REJECTED",
                protected_uuid_passed,
                routes=len(protected_uuid_responses),
                rejected=sum(
                    response.status_code in {400, 422}
                    for response in protected_uuid_responses
                ),
                statuses=[
                    response.status_code for response in protected_uuid_responses
                ],
            )
        )

        # Invalid authority classes must produce one non-enumerating response.
        invalid_clients = (
            _client(app, cookie_name, secrets.token_urlsafe(32)),
            _client(app, cookie_name, missing["token"]),
            _client(app, cookie_name, quarantined["token"]),
            _client(app, cookie_name, revoked["token"]),
            _client(app, cookie_name, expired["token"]),
            _client(app, cookie_name, deleted_user["token"]),
            _client(app, cookie_name, soft_deleted["token"]),
            _client(app, cookie_name, registration_deleted["token"]),
        )
        invalid_signatures = []
        invalid_count_deltas = []
        invalid_business_deltas = []
        for invalid_client in invalid_clients:
            before_counts = _table_counts(factory)
            before_state = _business_state_digest(factory)
            response = invalid_client.patch(
                PROFILE_PATH,
                headers={"Origin": TRUSTED_ORIGIN},
                json=valid_profile,
            )
            invalid_signatures.append(_safe_response_signature(response))
            invalid_count_deltas.append(before_counts == _table_counts(factory))
            invalid_business_deltas.append(
                before_state == _business_state_digest(factory)
            )
        invalid_uniform = bool(
            all(item.get("status_code") == 401 for item in invalid_signatures)
            and len({json.dumps(item, sort_keys=True) for item in invalid_signatures})
            == 1
            and all(invalid_count_deltas)
            and all(invalid_business_deltas)
        )
        assertions.append(
            _assertion(
                "AUTH-INVALID-SESSIONS-UNIFORM",
                invalid_uniform,
                cases=len(invalid_signatures),
                uniform_response=bool(
                    invalid_signatures
                    and len(
                        {
                            json.dumps(item, sort_keys=True)
                            for item in invalid_signatures
                        }
                    )
                    == 1
                ),
                all_row_counts_unchanged=all(invalid_count_deltas),
                all_business_state_unchanged=all(invalid_business_deltas),
            )
        )

        # Soft deletion revokes every pre-authentication capability, even when
        # legacy state still looks active/verified. Login/recovery retain their
        # anti-enumerating 202 + cookie-owned decoy-flow behavior but create no real
        # challenge, deliverable outbox row, session, or audit authority.
        preauth_client = _client(app, cookie_name)
        preauth_cases: list[dict[str, Any]] = []

        before_counts = _table_counts(factory)
        before_state = _business_state_digest(factory)
        before_private_capabilities = _private_capability_snapshot(factory)
        before_delivery = len(sender.sent)
        preauth_client.cookies.set(
            flow_cookie_name, soft_deleted_resend_flow, path="/api/v1"
        )
        resend_response = preauth_client.post(
            OTP_RESEND_PATH,
            headers=_trusted_mutation_headers(),
            json=_otp_resend_payload(),
        )
        resend_deleted_signature = _safe_response_signature(resend_response)
        after_private_capabilities = _private_capability_snapshot(factory)
        preauth_cases.append(
            {
                "case": "signup_resend",
                "response": resend_deleted_signature,
                "blocked": bool(
                    resend_response.status_code == 401
                    and resend_deleted_signature.get("code")
                    == "otp_flow_unavailable"
                ),
                "row_counts_unchanged": before_counts == _table_counts(factory),
                "business_state_unchanged": before_state
                == _business_state_digest(factory),
                "private_capabilities_expected": (
                    _private_capability_state_unchanged(
                        before_private_capabilities,
                        after_private_capabilities,
                    )
                ),
                "delivery_count_unchanged": before_delivery == len(sender.sent),
            }
        )

        before_counts = _table_counts(factory)
        before_state = _business_state_digest(factory)
        before_private_capabilities = _private_capability_snapshot(factory)
        before_delivery = len(sender.sent)
        preauth_client.cookies.set(
            flow_cookie_name, soft_deleted_verify_flow, path="/api/v1"
        )
        verify_deleted_response = preauth_client.post(
            OTP_VERIFY_PATH,
            headers=_trusted_mutation_headers(),
            json=_otp_verify_payload(signup_code),
        )
        verify_deleted_signature = _safe_response_signature(verify_deleted_response)
        after_private_capabilities = _private_capability_snapshot(factory)
        preauth_cases.append(
            {
                "case": "signup_consume",
                "response": verify_deleted_signature,
                "blocked": bool(
                    verify_deleted_response.status_code == 401
                    and verify_deleted_signature.get("code") == "otp_failed"
                    and not preauth_client.cookies.get(cookie_name)
                    and "set-cookie" not in verify_deleted_response.headers
                ),
                "row_counts_unchanged": before_counts == _table_counts(factory),
                "business_state_unchanged": before_state
                == _business_state_digest(factory),
                "private_capabilities_expected": (
                    _private_capability_state_unchanged(
                        before_private_capabilities,
                        after_private_capabilities,
                    )
                ),
                "delivery_count_unchanged": before_delivery == len(sender.sent),
            }
        )

        # Compare deleted-account starts with matched unknown-account controls.
        # The inputs share only their public last four digits, and the request
        # clock is held constant so every public state value is exactly equal.
        unknown_control_cases: list[dict[str, Any]] = []
        parity_now = datetime.now(timezone.utc)
        original_request_clock = endpoint._now
        endpoint._now = lambda: parity_now
        try:
            before_counts = _table_counts(factory)
            before_state = _business_state_digest(factory)
            before_private_capabilities = _private_capability_snapshot(factory)
            before_delivery = len(sender.sent)
            login_deleted_response = preauth_client.post(
                LOGIN_START_PATH,
                headers=_trusted_mutation_headers(),
                json={"mobile": soft_deleted_login["mobile"]},
            )
            login_deleted_token = login_deleted_response.cookies.get(flow_cookie_name)
            login_is_decoy = _private_decoy_flow_is_bound(
                factory,
                login_deleted_token,
                purpose="login",
            )
            after_private_capabilities = _private_capability_snapshot(factory)
            existing_after = _private_capability_snapshot(
                factory,
                scope=before_private_capabilities["scope"],
            )
            login_private_expected = bool(
                _private_capability_delta_is_exact(
                    before_private_capabilities,
                    after_private_capabilities,
                    otp_purpose_authorities=1,
                    otp_flows=1,
                    registration_idempotency_records=0,
                )
                and _private_capability_state_unchanged(
                    before_private_capabilities,
                    existing_after,
                )
            )
            preauth_cases.append(
                {
                    "case": "login_start",
                    "response": _safe_response_signature(login_deleted_response),
                    "blocked": bool(
                        login_deleted_response.status_code == 202 and login_is_decoy
                    ),
                    "row_counts_unchanged": before_counts == _table_counts(factory),
                    "business_state_unchanged": before_state
                    == _business_state_digest(factory),
                    "private_capabilities_expected": login_private_expected,
                    "delivery_count_unchanged": before_delivery == len(sender.sent),
                }
            )

            unknown_login_client = _client(app, cookie_name)
            before_counts = _table_counts(factory)
            before_state = _business_state_digest(factory)
            before_private_capabilities = _private_capability_snapshot(factory)
            before_delivery = len(sender.sent)
            login_unknown_response = unknown_login_client.post(
                LOGIN_START_PATH,
                headers=_trusted_mutation_headers(),
                json={"mobile": "9444444444"},
            )
            login_unknown_token = login_unknown_response.cookies.get(flow_cookie_name)
            login_unknown_is_decoy = _private_decoy_flow_is_bound(
                factory,
                login_unknown_token,
                purpose="login",
            )
            after_private_capabilities = _private_capability_snapshot(factory)
            existing_after = _private_capability_snapshot(
                factory,
                scope=before_private_capabilities["scope"],
            )
            login_unknown_private_expected = bool(
                _private_capability_delta_is_exact(
                    before_private_capabilities,
                    after_private_capabilities,
                    otp_purpose_authorities=1,
                    otp_flows=1,
                    registration_idempotency_records=0,
                )
                and _private_capability_state_unchanged(
                    before_private_capabilities,
                    existing_after,
                )
            )
            login_projection_matches_unknown = _public_otp_responses_match(
                login_deleted_response,
                login_unknown_response,
                expected_purpose="login",
                expected_masked_last4=str(soft_deleted_login["mobile"])[-4:],
            )
            login_cookie_contracts = bool(
                _cookie_contract_passes(
                    _named_cookie_contract(
                        login_deleted_response,
                        flow_cookie_name,
                        expected_value=login_deleted_token,
                        expected_path="/api/v1",
                        expected_same_site="strict",
                    )
                )
                and _cookie_contract_passes(
                    _named_cookie_contract(
                        login_unknown_response,
                        flow_cookie_name,
                        expected_value=login_unknown_token,
                        expected_path="/api/v1",
                        expected_same_site="strict",
                    )
                )
            )
            login_raw_bearers_absent = _raw_values_absent_from_json(
                (login_deleted_token, login_unknown_token),
                (
                    _safe_response_object(login_deleted_response),
                    _safe_response_object(login_unknown_response),
                ),
            )
            unknown_control_cases.append(
                {
                    "case": "login_unknown_control",
                    "response": _safe_response_signature(login_unknown_response),
                    "blocked": bool(
                        login_unknown_response.status_code == 202
                        and login_unknown_is_decoy
                        and login_projection_matches_unknown
                        and login_cookie_contracts
                        and login_raw_bearers_absent
                    ),
                    "row_counts_unchanged": before_counts == _table_counts(factory),
                    "business_state_unchanged": before_state
                    == _business_state_digest(factory),
                    "private_capabilities_expected": (
                        login_unknown_private_expected
                    ),
                    "delivery_count_unchanged": before_delivery == len(sender.sent),
                }
            )

            before_counts = _table_counts(factory)
            before_state = _business_state_digest(factory)
            before_private_capabilities = _private_capability_snapshot(factory)
            before_delivery = len(sender.sent)
            recovery_deleted_response = preauth_client.post(
                RECOVERY_START_PATH,
                headers=_trusted_mutation_headers(),
                json={"mobile": soft_deleted_recovery["mobile"]},
            )
            recovery_deleted_token = recovery_deleted_response.cookies.get(
                flow_cookie_name
            )
            recovery_is_decoy = _private_decoy_flow_is_bound(
                factory,
                recovery_deleted_token,
                purpose="recovery",
            )
            after_private_capabilities = _private_capability_snapshot(factory)
            existing_after = _private_capability_snapshot(
                factory,
                scope=before_private_capabilities["scope"],
            )
            recovery_private_expected = bool(
                _private_capability_delta_is_exact(
                    before_private_capabilities,
                    after_private_capabilities,
                    otp_purpose_authorities=1,
                    otp_flows=1,
                    registration_idempotency_records=0,
                )
                and _private_capability_state_unchanged(
                    before_private_capabilities,
                    existing_after,
                )
            )
            preauth_cases.append(
                {
                    "case": "recovery_start",
                    "response": _safe_response_signature(recovery_deleted_response),
                    "blocked": bool(
                        recovery_deleted_response.status_code == 202
                        and recovery_is_decoy
                    ),
                    "row_counts_unchanged": before_counts == _table_counts(factory),
                    "business_state_unchanged": before_state
                    == _business_state_digest(factory),
                    "private_capabilities_expected": recovery_private_expected,
                    "delivery_count_unchanged": before_delivery == len(sender.sent),
                }
            )

            unknown_recovery_client = _client(app, cookie_name)
            before_counts = _table_counts(factory)
            before_state = _business_state_digest(factory)
            before_private_capabilities = _private_capability_snapshot(factory)
            before_delivery = len(sender.sent)
            recovery_unknown_response = unknown_recovery_client.post(
                RECOVERY_START_PATH,
                headers=_trusted_mutation_headers(),
                json={"mobile": "9333333333"},
            )
            recovery_unknown_token = recovery_unknown_response.cookies.get(
                flow_cookie_name
            )
            recovery_unknown_is_decoy = _private_decoy_flow_is_bound(
                factory,
                recovery_unknown_token,
                purpose="recovery",
            )
            after_private_capabilities = _private_capability_snapshot(factory)
            existing_after = _private_capability_snapshot(
                factory,
                scope=before_private_capabilities["scope"],
            )
            recovery_unknown_private_expected = bool(
                _private_capability_delta_is_exact(
                    before_private_capabilities,
                    after_private_capabilities,
                    otp_purpose_authorities=1,
                    otp_flows=1,
                    registration_idempotency_records=0,
                )
                and _private_capability_state_unchanged(
                    before_private_capabilities,
                    existing_after,
                )
            )
            recovery_projection_matches_unknown = _public_otp_responses_match(
                recovery_deleted_response,
                recovery_unknown_response,
                expected_purpose="recovery",
                expected_masked_last4=str(soft_deleted_recovery["mobile"])[-4:],
            )
            recovery_cookie_contracts = bool(
                _cookie_contract_passes(
                    _named_cookie_contract(
                        recovery_deleted_response,
                        flow_cookie_name,
                        expected_value=recovery_deleted_token,
                        expected_path="/api/v1",
                        expected_same_site="strict",
                    )
                )
                and _cookie_contract_passes(
                    _named_cookie_contract(
                        recovery_unknown_response,
                        flow_cookie_name,
                        expected_value=recovery_unknown_token,
                        expected_path="/api/v1",
                        expected_same_site="strict",
                    )
                )
            )
            recovery_raw_bearers_absent = _raw_values_absent_from_json(
                (recovery_deleted_token, recovery_unknown_token),
                (
                    _safe_response_object(recovery_deleted_response),
                    _safe_response_object(recovery_unknown_response),
                ),
            )
            unknown_control_cases.append(
                {
                    "case": "recovery_unknown_control",
                    "response": _safe_response_signature(
                        recovery_unknown_response
                    ),
                    "blocked": bool(
                        recovery_unknown_response.status_code == 202
                        and recovery_unknown_is_decoy
                        and recovery_projection_matches_unknown
                        and recovery_cookie_contracts
                        and recovery_raw_bearers_absent
                    ),
                    "row_counts_unchanged": before_counts == _table_counts(factory),
                    "business_state_unchanged": before_state
                    == _business_state_digest(factory),
                    "private_capabilities_expected": (
                        recovery_unknown_private_expected
                    ),
                    "delivery_count_unchanged": before_delivery == len(sender.sent),
                }
            )
        finally:
            endpoint._now = original_request_clock

        before_counts = _table_counts(factory)
        before_state = _business_state_digest(factory)
        before_private_capabilities = _private_capability_snapshot(factory)
        with factory() as session:
            rotation_registration = session.get(
                StudentRegistration, soft_deleted_rotate["registration_id"]
            )
            assert rotation_registration is not None
            try:
                login_service.rotate_authenticated_session(
                    session, rotation_registration, datetime.now(timezone.utc)
                )
            except login_service.LoginError as exc:
                rotation_blocked = exc.status_code == 401
            else:
                rotation_blocked = False
        preauth_cases.append(
            {
                "case": "session_rotation",
                "blocked": rotation_blocked,
                "row_counts_unchanged": before_counts == _table_counts(factory),
                "business_state_unchanged": before_state
                == _business_state_digest(factory),
                "private_capabilities_expected": (
                    _private_capability_state_unchanged(
                        before_private_capabilities,
                        _private_capability_snapshot(factory),
                    )
                ),
                "delivery_count_unchanged": True,
            }
        )

        preauth_evidence_cases = preauth_cases + unknown_control_cases
        preauth_capabilities_denied = all(
            case["blocked"]
            and case["row_counts_unchanged"]
            and case["business_state_unchanged"]
            and case["private_capabilities_expected"]
            and case["delivery_count_unchanged"]
            for case in preauth_evidence_cases
        )
        assertions.append(
            _assertion(
                "AUTH-SOFT-DELETED-PREAUTH-CAPABILITIES-DENIED",
                preauth_capabilities_denied,
                cases=len(preauth_cases),
                blocked=sum(case["blocked"] for case in preauth_cases),
                unknown_controls=len(unknown_control_cases),
                unknown_controls_passed=sum(
                    case["blocked"] for case in unknown_control_cases
                ),
                all_row_counts_unchanged=all(
                    case["row_counts_unchanged"]
                    for case in preauth_evidence_cases
                ),
                all_business_state_unchanged=all(
                    case["business_state_unchanged"]
                    for case in preauth_evidence_cases
                ),
                all_delivery_counts_unchanged=all(
                    case["delivery_count_unchanged"]
                    for case in preauth_evidence_cases
                ),
                all_private_capabilities_expected=all(
                    case["private_capabilities_expected"]
                    for case in preauth_evidence_cases
                ),
                login_decoy=login_is_decoy,
                recovery_decoy=recovery_is_decoy,
                login_projection_matches_unknown=login_projection_matches_unknown,
                recovery_projection_matches_unknown=(
                    recovery_projection_matches_unknown
                ),
                login_cookie_contracts=login_cookie_contracts,
                recovery_cookie_contracts=recovery_cookie_contracts,
                login_raw_bearers_absent=login_raw_bearers_absent,
                recovery_raw_bearers_absent=recovery_raw_bearers_absent,
                response_statuses=[
                    case["response"]["status_code"]
                    for case in preauth_evidence_cases
                    if "response" in case
                ],
            )
        )

        # Student authority cannot self-approve guardian consent.
        before_counts = _table_counts(factory)
        before_state = _business_state_digest(factory)
        guardian_response = owner_a_client.post(
            GUARDIAN_PATH,
            headers={"Origin": TRUSTED_ORIGIN},
            json={},
        )
        guardian_signature = _safe_response_signature(guardian_response)
        guardian_passed = bool(
            guardian_response.status_code == 403
            and guardian_signature.get("code") == "guardian_self_approval_forbidden"
            and before_counts == _table_counts(factory)
            and before_state == _business_state_digest(factory)
        )
        assertions.append(
            _assertion(
                "AUTH-GUARDIAN-SELF-APPROVAL-DENIED",
                guardian_passed,
                response=guardian_signature,
                row_counts_unchanged=before_counts == _table_counts(factory),
                business_state_unchanged=before_state
                == _business_state_digest(factory),
            )
        )

        # Student denial then trusted reviewer success; the append-only audit
        # row must bind the actual authenticated reviewer identity and role.
        transition_payload = _verification_transition_payload(
            owner_a["registration_id"],
            status="verified",
            expected_profile_version=_current_profile_version(
                factory, owner_a["registration_id"]
            ),
        )
        before_state = _business_state_digest(factory)
        student_transition = owner_a_client.post(
            STATUS_PATH,
            headers={"Origin": TRUSTED_ORIGIN},
            json=transition_payload,
        )
        student_unchanged = before_state == _business_state_digest(factory)
        reviewer_client = _client(app, cookie_name, reviewer["token"])
        invalid_reviewer_targets = []
        for target in (
            uuid.uuid4(),
            quarantined["registration_id"],
            soft_deleted["registration_id"],
            registration_deleted["registration_id"],
        ):
            before_counts = _table_counts(factory)
            before_state = _business_state_digest(factory)
            response = reviewer_client.post(
                STATUS_PATH,
                headers={"Origin": TRUSTED_ORIGIN},
                json=_verification_transition_payload(
                    target,
                    status="verified",
                    expected_profile_version=1,
                ),
            )
            invalid_reviewer_targets.append(
                {
                    "signature": _safe_response_signature(response),
                    "row_counts_unchanged": before_counts == _table_counts(factory),
                    "business_state_unchanged": before_state
                    == _business_state_digest(factory),
                }
            )
        invalid_reviewer_signatures = [
            item["signature"] for item in invalid_reviewer_targets
        ]
        invalid_reviewer_targets_passed = bool(
            all(
                signature.get("status_code") == 404
                for signature in invalid_reviewer_signatures
            )
            and len(
                {
                    json.dumps(signature, sort_keys=True)
                    for signature in invalid_reviewer_signatures
                }
            )
            == 1
            and all(
                item["row_counts_unchanged"] and item["business_state_unchanged"]
                for item in invalid_reviewer_targets
            )
        )
        reviewer_transition = reviewer_client.post(
            STATUS_PATH,
            headers={"Origin": TRUSTED_ORIGIN},
            json=transition_payload,
        )
        with factory() as session:
            verification = session.get(StudentVerification, owner_a["verification_id"])
            audit = session.scalar(
                select(AuditEvent)
                .where(
                    AuditEvent.action == "student.verification.status_changed",
                    AuditEvent.resource_id == owner_a["verification_id"],
                )
                .order_by(AuditEvent.created_at.desc())
            )
            reviewer_passed = bool(
                student_transition.status_code == 403
                and student_unchanged
                and invalid_reviewer_targets_passed
                and reviewer_transition.status_code == 200
                and verification is not None
                and verification.status == "verified"
                and audit is not None
                and audit.actor_user_id == reviewer["user_id"]
                and audit.actor_role == "legal_reviewer"
            )
        assertions.append(
            _assertion(
                "AUTH-REVIEWER-ROLE-AND-AUDIT",
                reviewer_passed,
                student_response=_safe_response_signature(student_transition),
                student_business_state_unchanged=student_unchanged,
                reviewer_response=_safe_response_signature(reviewer_transition),
                invalid_target_cases=len(invalid_reviewer_targets),
                invalid_targets_uniform_no_delta=invalid_reviewer_targets_passed,
                audit_actor_bound=bool(
                    audit is not None and audit.actor_user_id == reviewer["user_id"]
                ),
                audit_role_bound=bool(
                    audit is not None and audit.actor_role == "legal_reviewer"
                ),
            )
        )

        # Exact Origin: every distinct canonicalization/repetition class is
        # exercised natively. All denials preserve full state; only the one
        # configured byte-level origin succeeds.
        origin_cases = ORIGIN_MATRIX_CASES
        origin_observations = []
        for label, origin, should_succeed in origin_cases:
            if isinstance(origin, tuple):
                headers = [("Origin", value) for value in origin]
            else:
                headers = {"Origin": origin} if origin is not None else {}
            headers = _profile_mutation_headers(
                f"origin-{label}", headers=headers
            )
            before_counts = _table_counts(factory)
            before_state = _business_state_digest(factory)
            response = owner_b_client.patch(
                PROFILE_PATH,
                headers=headers,
                json=_profile_payload(
                    f"origin-{label}",
                    expected_profile_version=_current_profile_version(
                        factory, owner_b["registration_id"]
                    ),
                ),
            )
            after_counts = _table_counts(factory)
            after_state = _business_state_digest(factory)
            origin_observations.append(
                {
                    "case": label,
                    "status": response.status_code,
                    "expected": "accept" if should_succeed else "deny",
                    "denied_without_delta": bool(
                        should_succeed
                        or (
                            response.status_code == 403
                            and before_counts == after_counts
                            and before_state == after_state
                        )
                    ),
                }
            )
        origin_passed = all(
            (
                item["status"] == 200
                if item["expected"] == "accept"
                else item["status"] == 403 and item["denied_without_delta"]
            )
            for item in origin_observations
        )
        assertions.append(
            _assertion(
                "AUTH-EXACT-ORIGIN-MATRIX",
                origin_passed,
                cases=len(origin_observations),
                accepted=sum(item["status"] == 200 for item in origin_observations),
                denied=sum(item["status"] == 403 for item in origin_observations),
                all_denials_no_delta=all(
                    item["denied_without_delta"] for item in origin_observations
                ),
            )
        )

        # Deterministic ownership mutant: remove both current owner predicates
        # (the compatibility facade and canonical profile resolver) and force B
        # onto A. The canonical resolver mutant also removes its cookie/user
        # coupling; otherwise the independent session backstop correctly kills
        # the unsafe facade before it can reproduce the ownership vulnerability.
        original_owned_registration = endpoint._owned_registration
        original_profile_authority = profile_service.resolve_authority

        def unsafe_owned_registration(
            session: Session, actor: ActorContext
        ) -> StudentRegistration:
            del actor
            registration = session.get(StudentRegistration, owner_a["registration_id"])
            assert registration is not None
            return registration

        def unsafe_profile_authority(
            session: Session,
            actor_user_id: uuid.UUID | None,
            *,
            for_update: bool = False,
            now: datetime | None = None,
            raw_session_token: str | None = None,
        ) -> Any:
            del actor_user_id, raw_session_token
            return original_profile_authority(
                session,
                owner_a["user_id"],
                for_update=for_update,
                now=now,
                raw_session_token=None,
            )

        mutant_owner_payload = _profile_payload(
            "mutant-owner",
            expected_profile_version=_current_profile_version(
                factory, owner_a["registration_id"]
            ),
        )
        endpoint._owned_registration = unsafe_owned_registration
        profile_service.resolve_authority = unsafe_profile_authority
        try:
            mutant_ownership_response = owner_b_client.patch(
                PROFILE_PATH,
                headers=_profile_mutation_headers("mutant-owner"),
                json=mutant_owner_payload,
            )
        finally:
            endpoint._owned_registration = original_owned_registration
            profile_service.resolve_authority = original_profile_authority
        with factory() as session:
            mutant_profile = session.scalar(
                select(StudentProfile).where(
                    StudentProfile.registration_id == owner_a["registration_id"]
                )
            )
            ownership_mutant_killed = bool(
                mutant_ownership_response.status_code == 200
                and mutant_profile is not None
                and mutant_profile.college == mutant_owner_payload["college"]
                and mutant_profile.enrolment_hash
                == keyed_hash(mutant_owner_payload["enrolment_number"])
                and mutant_profile.institutional_email_hash
                == keyed_hash(
                    mutant_owner_payload["institutional_email"], lower=True
                )
            )
        assertions.append(
            _assertion(
                "MUTANT-OWNERSHIP-PREDICATE",
                ownership_mutant_killed,
                vulnerability_reproduced=ownership_mutant_killed,
                response=_safe_response_signature(mutant_ownership_response),
            )
        )

        # Reset the verification to pending, then bypass both current reviewer
        # checks: route role resolution and commit-time locked-session role
        # revalidation. The composite must reproduce the unsafe outcome while
        # retaining the live exact-session/user lock and every other check.
        with factory() as session:
            row = session.get(StudentVerification, owner_b["verification_id"])
            assert row is not None
            row.status = "pending"
            session.commit()
        original_reviewer_dependency = endpoint._require_verification_reviewer
        original_reviewer_session_lock = (
            login_service.lock_presented_session_for_effect
        )

        def unsafe_reviewer_session_lock(
            session: Session,
            raw_token: str | None,
            *,
            expected_user_id: uuid.UUID,
            now: datetime,
            allowed_roles: frozenset[str],
        ) -> Any:
            del allowed_roles
            return original_reviewer_session_lock(
                session,
                raw_token,
                expected_user_id=expected_user_id,
                now=now,
                allowed_roles=frozenset(
                    {"student", "admin", "legal_reviewer"}
                ),
            )

        app.dependency_overrides[original_reviewer_dependency] = lambda: ActorContext(
            user_id=owner_b["user_id"], roles=frozenset({Role.STUDENT})
        )
        login_service.lock_presented_session_for_effect = (
            unsafe_reviewer_session_lock
        )
        try:
            role_mutant_response = owner_b_client.post(
                STATUS_PATH,
                headers={"Origin": TRUSTED_ORIGIN},
                json=_verification_transition_payload(
                    owner_b["registration_id"],
                    status="verified",
                    expected_profile_version=_current_profile_version(
                        factory, owner_b["registration_id"]
                    ),
                ),
            )
        finally:
            login_service.lock_presented_session_for_effect = (
                original_reviewer_session_lock
            )
            app.dependency_overrides.pop(original_reviewer_dependency, None)
        with factory() as session:
            row = session.get(StudentVerification, owner_b["verification_id"])
            role_mutant_killed = bool(
                role_mutant_response.status_code == 200
                and row is not None
                and row.status == "verified"
            )
        assertions.append(
            _assertion(
                "MUTANT-REVIEWER-ROLE",
                role_mutant_killed,
                vulnerability_reproduced=role_mutant_killed,
                response=_safe_response_signature(role_mutant_response),
            )
        )

        # Remove both current exact-origin backstops: the global consulted by
        # cookie actor resolution and the route dependency FastAPI captured at
        # graph construction. An untrusted request must then succeed, proving
        # the matrix is live without weakening the production guard.
        original_origin_guard = core_auth.require_trusted_cookie_origin
        original_route_origin_guard = endpoint.require_trusted_cookie_origin

        def unsafe_origin_guard(request: Request) -> None:
            del request

        core_auth.require_trusted_cookie_origin = unsafe_origin_guard
        app.dependency_overrides[original_route_origin_guard] = unsafe_origin_guard
        try:
            origin_mutant_response = owner_b_client.patch(
                PROFILE_PATH,
                headers=_profile_mutation_headers(
                    "mutant-origin",
                    headers={"Origin": "http://localhost.invalid:1130"},
                ),
                json=_profile_payload(
                    "mutant-origin",
                    expected_profile_version=_current_profile_version(
                        factory, owner_b["registration_id"]
                    ),
                ),
            )
        finally:
            core_auth.require_trusted_cookie_origin = original_origin_guard
            app.dependency_overrides.pop(original_route_origin_guard, None)
        origin_mutant_killed = origin_mutant_response.status_code == 200
        assertions.append(
            _assertion(
                "MUTANT-ORIGIN-CHECK",
                origin_mutant_killed,
                vulnerability_reproduced=origin_mutant_killed,
                response=_safe_response_signature(origin_mutant_response),
            )
        )

        # NYAY-4 added an independent cookie-flow eligibility backstop around
        # the NYAY-2 signup-purpose predicate.  Remove both reviewed guards as
        # one explicit composite lifecycle mutant; deleting only either guard
        # is now safely backstopped and cannot prove that this oracle still
        # bites. The stale nonterminal cookie must then resend and rotate a
        # second authenticated session.
        original_signup_scope = otp_service.registration_accepts_otp_purpose
        original_flow_resolver = otp_flow_service.resolve_flow

        def unsafe_signup_scope(
            registration: StudentRegistration | None, purpose: str
        ) -> bool:
            del purpose
            return otp_service.registration_is_authorizable(registration)

        status_mutant_flow = _seed_private_signup_flow(
            factory,
            signup_registration_id,
            destination=signup_mobile,
        )
        status_mutant_private = _require_private_signup_flow(
            factory, status_mutant_flow
        )
        # Age the database-owned cooldown so only the two intended lifecycle
        # guards, not rate timing, determine the mutant outcome.
        with factory() as session:
            status_authority = session.get(
                OtpPurposeAuthority,
                status_mutant_private["authority_id"],
            )
            if status_authority is None:
                raise ProductGateFailure(
                    "signup lifecycle mutant authority is unavailable"
                )
            status_authority.cooldown_until = datetime.now(timezone.utc) - timedelta(
                seconds=1
            )
            status_authority.last_issued_at = datetime.now(timezone.utc) - timedelta(
                minutes=1
            )
            status_authority.resend_window_started_at = None
            status_authority.resend_count = 0
            session.commit()
        before_counts = _table_counts(factory)
        before_state = _business_state_digest(factory)
        before_delivery = len(sender.sent)
        status_mutant_client = _client(app, cookie_name)
        status_mutant_client.cookies.set(
            flow_cookie_name, status_mutant_flow, path="/api/v1"
        )
        otp_flow_service.resolve_flow = _unsafe_flow_graph_for_mutation
        otp_service.registration_accepts_otp_purpose = unsafe_signup_scope
        try:
            status_mutant_resend = status_mutant_client.post(
                OTP_RESEND_PATH,
                headers=_trusted_mutation_headers(),
                json=_otp_resend_payload(),
            )
            status_mutant_code = (
                sender.sent[-1][1] if len(sender.sent) > before_delivery else "0" * 6
            )
            status_mutant_verify = status_mutant_client.post(
                OTP_VERIFY_PATH,
                headers=_trusted_mutation_headers(),
                json=_otp_verify_payload(status_mutant_code),
            )
        finally:
            otp_service.registration_accepts_otp_purpose = original_signup_scope
            otp_flow_service.resolve_flow = original_flow_resolver
        after_counts = _table_counts(factory)
        after_state = _business_state_digest(factory)
        signup_scope_mutant_killed = bool(
            status_mutant_resend.status_code == 202
            and status_mutant_verify.status_code == 200
            and status_mutant_client.cookies.get(cookie_name)
            and after_counts["otp_challenges"] == before_counts["otp_challenges"] + 1
            and after_counts["otp_outbox"] == before_counts["otp_outbox"] + 1
            and after_counts["auth_sessions"] == before_counts["auth_sessions"] + 1
            and after_counts["audit_events"] == before_counts["audit_events"] + 1
            and len(sender.sent) == before_delivery + 1
            and after_state != before_state
        )
        assertions.append(
            _assertion(
                "MUTANT-SIGNUP-STATUS-SCOPE",
                signup_scope_mutant_killed,
                vulnerability_reproduced=signup_scope_mutant_killed,
                lifecycle_guards_removed=2,
                resend_response=_safe_response_signature(status_mutant_resend),
                verify_response=_safe_response_signature(status_mutant_verify),
                challenge_created=(
                    after_counts["otp_challenges"]
                    == before_counts["otp_challenges"] + 1
                ),
                outbox_created=(
                    after_counts["otp_outbox"] == before_counts["otp_outbox"] + 1
                ),
                session_rotated=(
                    after_counts["auth_sessions"] == before_counts["auth_sessions"] + 1
                ),
                audit_created=(
                    after_counts["audit_events"] == before_counts["audit_events"] + 1
                ),
                delivery_count_increased=len(sender.sent) == before_delivery + 1,
                cookie_issued=bool(status_mutant_client.cookies.get(cookie_name)),
            )
        )

        # The NYAY-4 cookie resolver independently rejects soft-deleted account
        # graphs. Remove it together with the original NYAY-2 deleted-at
        # predicate as one explicit composite lifecycle mutant. The real resend
        # route must then create and deliver authority.
        original_authorizable = otp_service.registration_is_authorizable
        original_flow_resolver = otp_flow_service.resolve_flow

        def unsafe_authorizable(registration: StudentRegistration | None) -> bool:
            return bool(
                registration is not None
                and registration.status != "deleted"
                and registration.dob_hash_state == "verified"
            )

        before_counts = _table_counts(factory)
        before_state = _business_state_digest(factory)
        before_delivery = len(sender.sent)
        deleted_mutant_client = _client(app, cookie_name)
        deleted_mutant_client.cookies.set(
            flow_cookie_name, soft_deleted_mutant_flow, path="/api/v1"
        )
        otp_flow_service.resolve_flow = _unsafe_flow_graph_for_mutation
        otp_service.registration_is_authorizable = unsafe_authorizable
        try:
            deleted_mutant_response = deleted_mutant_client.post(
                OTP_RESEND_PATH,
                headers=_trusted_mutation_headers(),
                json=_otp_resend_payload(),
            )
        finally:
            otp_service.registration_is_authorizable = original_authorizable
            otp_flow_service.resolve_flow = original_flow_resolver
        after_counts = _table_counts(factory)
        after_state = _business_state_digest(factory)
        soft_delete_mutant_killed = bool(
            deleted_mutant_response.status_code == 202
            and after_counts["otp_challenges"] == before_counts["otp_challenges"] + 1
            and after_counts["otp_outbox"] == before_counts["otp_outbox"] + 1
            and after_state != before_state
            and len(sender.sent) == before_delivery + 1
        )
        assertions.append(
            _assertion(
                "MUTANT-SOFT-DELETED-PREAUTH",
                soft_delete_mutant_killed,
                vulnerability_reproduced=soft_delete_mutant_killed,
                lifecycle_guards_removed=2,
                response=_safe_response_signature(deleted_mutant_response),
                challenge_created=(
                    after_counts["otp_challenges"]
                    == before_counts["otp_challenges"] + 1
                ),
                outbox_created=(
                    after_counts["otp_outbox"] == before_counts["otp_outbox"] + 1
                ),
                delivery_count_increased=len(sender.sent) == before_delivery + 1,
            )
        )

        metrics = {
            "real_http_requests_executed": True,
            "negative_controls_executed": 5,
            "protected_routes_checked": len(anonymous_calls),
            "protected_uuid_contract_routes_checked": len(protected_uuid_responses),
            "invalid_session_classes_checked": len(invalid_clients),
            "origin_cases_checked": len(origin_cases),
            "soft_deleted_preauth_cases_checked": len(preauth_cases),
            "unknown_preauth_controls_checked": len(unknown_control_cases),
            "signup_bootstrap_expiry_cases_checked": 2,
        }
    finally:
        override_keyring(previous_keyring)
        settings.app_env = previous_env
        settings.cors_origins = previous_origins
        app.dependency_overrides.clear()
    return assertions, metrics


def _execute(scratch_url: str) -> dict[str, Any]:
    migration = {
        "upgrade": _run_alembic(scratch_url, "upgrade", "head"),
        "check": None,
    }
    if migration["upgrade"]["returncode"] != 0:
        raise ProductGateFailure("scratch database migration failed")
    migration["check"] = _run_alembic(scratch_url, "check")
    if migration["check"]["returncode"] != 0:
        raise ProductGateFailure("scratch database is not at one Alembic head")

    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            version_num = int(connection.scalar(text("SHOW server_version_num")))
            vector_version = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            revision_count = int(
                connection.scalar(text("SELECT count(*) FROM alembic_version")) or 0
            )
        if not _is_postgresql_16_with_pgvector(version_num, vector_version):
            raise Blocked("PostgreSQL 16 with pgvector is required")
        assertions = [
            _assertion(
                "RUNTIME-POSTGRES-16-PGVECTOR",
                _is_postgresql_16_with_pgvector(version_num, vector_version),
                server_version_num=version_num,
                pgvector_present=bool(vector_version),
            ),
            _assertion(
                "RUNTIME-ALEMBIC-HEAD-CLEAN",
                migration["upgrade"]["returncode"] == 0
                and migration["check"]["returncode"] == 0
                and revision_count == 1,
                upgrade_returncode=migration["upgrade"]["returncode"],
                check_returncode=migration["check"]["returncode"],
                revision_rows=revision_count,
            ),
        ]
        api_assertions, api_metrics = _run_api_probes(engine)
        assertions.extend(api_assertions)
        # This assertion is computed before the report is emitted; a second
        # complete scan in ``main`` can still overturn the final verdict.
        preprivacy_report = {
            "assertions": assertions,
            "api_metrics": api_metrics,
        }
        findings = _privacy_findings(preprivacy_report)
        assertions.append(
            _assertion(
                "HARNESS-AGGREGATE-PRIVACY",
                not findings,
                findings=len(findings),
                scanned=True,
            )
        )
        return {
            "assertions": assertions,
            "api_metrics": api_metrics,
        }
    finally:
        engine.dispose()


def _blocked_report(reason: str) -> dict[str, Any]:
    return {
        "gate": "nyay2_postgres_authorization",
        "status": "BLOCKED",
        "executed": False,
        "reason": reason,
        "assertions": [],
        "evaluation": {
            "exact_inventory": False,
            "required": len(REQUIRED_ASSERTION_IDS),
            "passed": 0,
            "failed": [],
            "inventory_failures": {
                "missing": len(REQUIRED_ASSERTION_IDS),
                "extra": 0,
                "duplicate": 0,
                "reordered": False,
            },
            "overall_pass": False,
        },
        "scratch_cleanup": {
            "created": 0,
            "removed": 0,
            "cleanup_failed": 0,
            "all_created_removed": True,
            "purposes": [],
        },
    }


def _write_report(path: str | None, report: dict[str, Any]) -> None:
    if path:
        Path(path).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="loopback PostgreSQL control URL used only to create a scratch database",
    )
    parser.add_argument("--report", help="optional aggregate JSON report path")
    args = parser.parse_args(argv)

    if not args.database_url:
        report = _blocked_report("explicit loopback PostgreSQL control URL absent")
        _write_report(args.report, report)
        print(json.dumps(report, sort_keys=True))
        return BLOCKED_EXIT

    manager: _ScratchDatabaseManager | None = None
    try:
        base = _safe_local_postgres_url(args.database_url)
        manager = _ScratchDatabaseManager(base)
        result = manager.run("authorization", _execute)
        assertions = result["assertions"]
        evaluation = _evaluate_assertions(assertions)
        report = {
            "gate": "nyay2_postgres_authorization",
            "status": "PASS" if evaluation["overall_pass"] else "FAIL",
            "executed": True,
            "assertions": assertions,
            "evaluation": evaluation,
            "api_metrics": result["api_metrics"],
            "scratch_cleanup": manager.summary(),
        }
        if not report["scratch_cleanup"]["all_created_removed"]:
            report["status"] = "FAIL"
            report["evaluation"]["overall_pass"] = False
        final_findings = _privacy_findings(report)
        report["privacy_scan"] = {
            "scanned": True,
            "findings": len(final_findings),
            "passed": not final_findings,
        }
        if final_findings:
            report["status"] = "FAIL"
            report["evaluation"]["overall_pass"] = False
        exit_code = 0 if report["status"] == "PASS" else 1
    except Blocked as exc:
        report = _blocked_report(str(exc))
        report["executed"] = bool(manager and manager.scratch_created)
        if manager is not None:
            report["scratch_cleanup"] = manager.summary()
            if not report["scratch_cleanup"]["all_created_removed"]:
                report["status"] = "FAIL"
                exit_code = 1
            else:
                exit_code = BLOCKED_EXIT
        else:
            exit_code = BLOCKED_EXIT
    except Exception as exc:  # noqa: BLE001 - fail closed, report class only
        cleanup = (
            manager.summary()
            if manager is not None
            else {
                "created": 0,
                "removed": 0,
                "cleanup_failed": 0,
                "all_created_removed": True,
                "purposes": [],
            }
        )
        report = {
            "gate": "nyay2_postgres_authorization",
            "status": "FAIL",
            "executed": bool(manager and manager.scratch_created),
            "failure_class": type(exc).__name__,
            "assertions": [],
            "evaluation": {
                "exact_inventory": False,
                "required": len(REQUIRED_ASSERTION_IDS),
                "passed": 0,
                "failed": [],
                "inventory_failures": {
                    "missing": len(REQUIRED_ASSERTION_IDS),
                    "extra": 0,
                    "duplicate": 0,
                    "reordered": False,
                },
                "overall_pass": False,
            },
            "scratch_cleanup": cleanup,
        }
        exit_code = 1

    _write_report(args.report, report)
    print(json.dumps(report, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
