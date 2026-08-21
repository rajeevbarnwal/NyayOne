"""NYAY-4 PostgreSQL 16 OTP-security characterization and release gate.

This gate is intentionally opt-in. It accepts only an explicit, query-free
loopback PostgreSQL control URL, creates disposable databases, migrates through
the exact 0018/0019 boundary, exercises the real OTP services and relay with
concurrent PostgreSQL sessions, and removes every scratch database in ``finally``
blocks. Running this module without both ``--execute`` and
``NYAY4_POSTGRES_GATE=1`` exits 78 before any database is contacted.

Evidence is aggregate-only: assertion IDs, statuses, counts, booleans, bounded
durations, and version numbers. Raw subjects, mobile numbers, IP addresses,
flow/cookie/provider tokens, OTPs, ciphertext, hashes, UUIDs, URLs, database
names, and exception payloads are never emitted.

Exit codes:

* 0: every exact assertion, mutant, privacy, and cleanup oracle passed;
* 1: a product, migration, harness, privacy, or cleanup assertion failed;
* 78: the explicitly routed PostgreSQL 16 + pgvector authority was unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import bindparam, create_engine, func, inspect, make_url, select, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool


BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

BLOCKED_EXIT = 78
PREVIOUS_REVISION = "0018_registration_idempotency"
PINNED_HEAD = "0019_otp_security_authority"
OPT_IN_ENV = "NYAY4_POSTGRES_GATE"
SCRATCH_PREFIX = "nyay4_otp_"

# Every account-bearing fixture below coexists in the one authoritative
# behavior database. Keeping the inventory centralized makes an accidental
# cross-subprobe uniqueness collision a pre-database gate failure.
BEHAVIOR_FIXTURE_MOBILES = {
    "initial_login_known": "9100001111",
    "initial_login_decoy": "9200001111",
    "initial_recovery_known": "9300002222",
    "initial_recovery_decoy": "9400002222",
    "expired_active": "9500003333",
    "lockout": "9510007001",
    "failed_resend": "9510007002",
    "claim": "9510007003",
    "provider": "9510007004",
    "registration_finalizer": "9510007005",
    "retry": "9510007006",
    "rate_forwarded": "9510007999",
    "rate_real": "9510007881",
    "rate_decoy": "9510007882",
    "cookie_known": "9510008111",
    "cookie_decoy": "9520008111",
    "metadata": "9510008222",
    "concurrent_verify": "9510008333",
    "concurrent_resend": "9510008444",
    "alternation_login_known": "9510008666",
    "alternation_login_decoy": "9520008666",
    "alternation_recovery_known": "9530008777",
    "alternation_recovery_decoy": "9540008777",
    "neutralized_concurrency": "9510008555",
    "neutralized_lifecycle": "9600004444",
    "pending_expired": "9700000001",
    "pending_missing": "9700000002",
    "verify_symmetry_real": "9800005555",
    "verify_symmetry_decoy": "9900005555",
    "maintenance_expired": "9910001001",
    "maintenance_recent": "9910001002",
    "maintenance_preserved": "9910001003",
}

# 0001..0015 are pinned by the repository migration ledger.  These three
# reviewed forward revisions post-date that baseline and are pinned here so an
# NYAY-4 branch cannot silently rewrite its predecessor history.
POST_LEDGER_HISTORICAL_SHA256 = {
    "0016_dob_hash_reconcile.py": (
        "b483bad2e23abbd0087856b06cc53fb54021baa2a397c295f3021caf1da0cef6"
    ),
    "0017_registration_invariants.py": (
        "f7b0420779699ceb555ad9ce35016cc8ce7fed9042fe23c44234d6b5eefd03a5"
    ),
    "0018_registration_idempotency.py": (
        "5678a9b2117c5e0397a40052731563e4b5b09664f73f9874b3239c235bb7a862"
    ),
}

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

# The exact ordered 16-point release matrix. Evaluator order is deliberate:
# no later green assertion may substitute for an earlier missing control.
REQUIRED_ASSERTION_IDS = (
    "RUNTIME-POSTGRES-16-PGVECTOR",
    "MIGRATION-0018-0019-LIFECYCLE-IMMUTABLE",
    "MIGRATION-POPULATED-UPGRADE-DOWNGRADE-REFUSAL",
    "SCHEMA-AUTHORITY-FLOW-RATE-OUTBOX-EXACT",
    "CONTRACT-LOCKOUT-SURVIVES-RESEND",
    "CONCURRENCY-WRONG-VERIFY-CUMULATIVE",
    "CONCURRENCY-RESEND-ONE-STAGED-ONE-ACTIVE",
    "CONTRACT-FAILED-RESEND-PRESERVES-ACTIVE",
    "CONTRACT-RATE-BUDGETS-IDENTITY-IP-GLOBAL",
    "CONTRACT-COOKIE-ORIGIN-RELOAD-SYMMETRY",
    "CONTRACT-SERVER-METADATA-TYPED-OUTCOMES",
    "CONTRACT-OUTBOX-CLAIM-LEASE-FENCING",
    "CONTRACT-PROVIDER-IDEMPOTENCY-EXACTLY-ONCE",
    "CONTRACT-RETRY-BACKOFF-EXHAUSTION-ERASURE",
    "CONTRACT-PRODUCTION-CONFIG-FAIL-CLOSED",
    "HARNESS-MUTANTS-PRIVACY-SCRATCH-CLEANUP",
)

REQUIRED_MUTANT_IDS = (
    "RESET-AUTHORITY-ON-RESEND",
    "OMIT-AUTHORITY-FOR-UPDATE",
    "STORE-RAW-SUBJECT",
    "STORE-RAW-IP",
    "DROP-IDENTITY-BUDGET",
    "DROP-IP-BUDGET",
    "DROP-GLOBAL-BUDGET",
    "TRUST-X-FORWARDED-FOR",
    "CLEAR-CLAIM-BEFORE-ACK",
    "RANDOMIZE-PROVIDER-RETRY-KEY",
    "MARK-SENT-BEFORE-PROVIDER",
    "ACCEPT-NONIDEMPOTENT-PROVIDER",
    "COUNT-ALREADY-SENT-AS-DELIVERED",
    "ALLOW-STALE-CLAIM-FINALIZE",
    "HOT-LOOP-FAILED-DELIVERY",
    "RETAIN-CIPHERTEXT-AFTER-EXHAUSTION",
    "ACTIVATE-RESEND-BEFORE-DELIVERY",
    "DROP-ORIGIN-BOUNDARY",
    "EXPOSE-REGISTRATION-UUID",
    "HARDCODE-CLIENT-ATTEMPTS",
    "HARDCODE-CLIENT-COOLDOWN",
    "HARDCODE-CLIENT-EXPIRY",
    "CLIENT-RESETS-RESEND-TIMER",
    "AGGREGATOR-ZERO-SELECTOR",
    "MISSING-GATE-COMMAND",
)

OTP_POSITIVE_INTEGER_FIELDS = (
    "otp_challenge_ttl_seconds",
    "otp_resend_cooldown_seconds",
    "otp_lockout_seconds",
    "otp_max_attempts",
    "otp_attempt_window_seconds",
    "otp_resend_window_seconds",
    "otp_max_resends_per_window",
    "otp_issue_rate_window_seconds",
    "otp_issue_identity_limit",
    "otp_issue_ip_limit",
    "otp_issue_global_limit",
    "otp_resend_rate_window_seconds",
    "otp_resend_identity_limit",
    "otp_resend_ip_limit",
    "otp_resend_global_limit",
    "otp_verify_rate_window_seconds",
    "otp_verify_identity_limit",
    "otp_verify_ip_limit",
    "otp_verify_global_limit",
    "otp_outbox_lease_seconds",
    "otp_outbox_max_attempts",
    "otp_outbox_retry_base_seconds",
    "otp_outbox_retry_max_seconds",
    "otp_rate_bucket_retention_seconds",
)

REQUIRED_CONFIG_REJECTION_CASES = frozenset(
    {
        "delivery_disabled_production",
        "provider_none",
        "provider_capturing",
        "provider_unknown",
        "provider_insecure_url",
        "provider_ambiguous_url",
        "provider_invalid_textual_port",
        "provider_out_of_range_port",
        "provider_url_whitespace",
        "provider_missing_url",
        "provider_missing_token",
        "provider_missing_idempotency",
        "provider_timeout_zero",
        "provider_timeout_bool",
        "provider_timeout_nonfinite",
        "retry_max_below_base",
        *(f"nonpositive:{field}" for field in OTP_POSITIVE_INTEGER_FIELDS),
    }
)

EXPECTED_OTP_TABLES = (
    "otp_purpose_authorities",
    "otp_flows",
    "otp_rate_limit_buckets",
    "otp_challenges",
    "otp_outbox",
)
EXPECTED_SCHEMA_TABLES = (*EXPECTED_OTP_TABLES, "registration_idempotency_records")

# Independent, literal 0019 physical-schema contract. These values are not
# derived from ORM metadata or the migration under test.
_ID = ("uuid", None, False, None)
_CREATED = ("timestamp", None, False, "now")
_UPDATED = ("timestamp", None, False, "now")
_DELETED = ("timestamp", None, True, None)
_METADATA = ("json", None, True, None)
EXPECTED_0019_COLUMNS: dict[
    str, tuple[tuple[str, str, int | None, bool, str | None], ...]
] = {
    "otp_purpose_authorities": (
        ("id", *_ID),
        ("subject_hash", "varchar", 64, False, None),
        ("registration_id", "uuid", None, True, None),
        ("purpose", "varchar", 16, False, None),
        ("failed_attempts", "integer", None, False, "0"),
        ("max_attempts", "integer", None, False, "3"),
        ("locked_until", "timestamp", None, True, None),
        ("attempt_window_started_at", "timestamp", None, True, None),
        ("last_issued_at", "timestamp", None, True, None),
        ("cooldown_until", "timestamp", None, True, None),
        ("resend_window_started_at", "timestamp", None, True, None),
        ("resend_count", "integer", None, False, "0"),
        ("max_resends", "integer", None, False, "3"),
        ("active_expires_at", "timestamp", None, True, None),
        ("generation", "integer", None, False, "0"),
        ("created_at", *_CREATED),
        ("updated_at", *_UPDATED),
        ("deleted_at", *_DELETED),
        ("metadata_json", *_METADATA),
    ),
    "otp_rate_limit_buckets": (
        ("id", *_ID),
        ("scope", "varchar", 16, False, None),
        ("subject_hash", "varchar", 64, False, None),
        ("action", "varchar", 16, False, None),
        ("window_started_at", "timestamp", None, False, None),
        ("window_seconds", "integer", None, False, None),
        ("request_count", "integer", None, False, None),
        ("max_requests", "integer", None, False, None),
        ("created_at", *_CREATED),
        ("updated_at", *_UPDATED),
    ),
    "otp_flows": (
        ("id", *_ID),
        ("token_hash", "varchar", 64, False, None),
        ("authority_id", "uuid", None, False, None),
        ("subject_hash", "varchar", 64, False, None),
        ("purpose", "varchar", 16, False, None),
        ("registration_id", "uuid", None, True, None),
        ("challenge_id", "uuid", None, True, None),
        ("registration_idempotency_record_id", "uuid", None, True, None),
        ("destination_masked_ct", "varchar", 600, True, None),
        ("key_version", "varchar", 8, True, None),
        ("state", "varchar", 24, False, None),
        ("expires_at", "timestamp", None, False, None),
        ("consumed_at", "timestamp", None, True, None),
        ("created_at", *_CREATED),
        ("updated_at", *_UPDATED),
        ("deleted_at", *_DELETED),
        ("metadata_json", *_METADATA),
    ),
    "otp_challenges": (
        ("id", *_ID),
        ("registration_id", "uuid", None, False, None),
        ("verifier_hash", "varchar", 64, False, None),
        ("attempts", "integer", None, False, "0"),
        ("max_attempts", "integer", None, False, "3"),
        ("expires_at", "timestamp", None, False, None),
        ("consumed_at", "timestamp", None, True, None),
        ("locked_until", "timestamp", None, True, None),
        ("created_at", *_CREATED),
        ("updated_at", *_UPDATED),
        ("deleted_at", *_DELETED),
        ("metadata_json", *_METADATA),
        ("purpose", "varchar", 16, False, "signup"),
        ("authority_id", "uuid", None, False, None),
        ("delivery_state", "varchar", 24, False, "pending_delivery"),
    ),
    "otp_outbox": (
        ("id", *_ID),
        ("challenge_id", "uuid", None, False, None),
        ("destination_ct", "varchar", 600, True, None),
        ("code_ct", "varchar", 600, True, None),
        ("key_version", "varchar", 8, False, "v1"),
        ("purpose", "varchar", 16, False, "signup"),
        ("status", "varchar", 16, False, "pending"),
        ("attempts", "integer", None, False, "0"),
        ("last_error", "varchar", 200, True, None),
        ("delivered_at", "timestamp", None, True, None),
        ("created_at", *_CREATED),
        ("updated_at", *_UPDATED),
        ("deleted_at", *_DELETED),
        ("metadata_json", *_METADATA),
        ("provider_idempotency_key", "varchar", 64, False, None),
        ("claim_token_hash", "varchar", 64, True, None),
        ("claimed_at", "timestamp", None, True, None),
        ("lease_expires_at", "timestamp", None, True, None),
        ("next_attempt_at", "timestamp", None, True, None),
        ("provider_receipt_hash", "varchar", 64, True, None),
        ("provider_receipt_key_version", "varchar", 8, True, None),
        ("legacy_destination_retained", "boolean", None, False, "false"),
        ("max_attempts", "integer", None, False, "5"),
    ),
    "registration_idempotency_records": (
        ("id", *_ID),
        ("idempotency_key_hash", "varchar", 64, False, None),
        ("request_fingerprint", "varchar", 64, True, None),
        ("request_fingerprint_version", "varchar", 16, True, None),
        ("state", "varchar", 24, False, None),
        ("outcome_code", "varchar", 40, True, None),
        ("registration_id", "uuid", None, True, None),
        ("outbox_id", "uuid", None, True, None),
        ("created_at", *_CREATED),
        ("updated_at", *_UPDATED),
    ),
}

EXPECTED_0019_PRIMARY_KEYS = {
    table: (f"pk_{table}", ("id",)) for table in EXPECTED_SCHEMA_TABLES
}
EXPECTED_0019_UNIQUES = {
    "otp_purpose_authorities": {
        ("uq_otp_purpose_authorities_subject_purpose", ("subject_hash", "purpose")),
        (
            "uq_otp_purpose_authorities_registration_purpose",
            ("registration_id", "purpose"),
        ),
    },
    "otp_rate_limit_buckets": {
        (
            "uq_otp_rate_limit_buckets_scope_subject_action",
            ("scope", "subject_hash", "action"),
        )
    },
    "otp_flows": {
        ("uq_otp_flows_token_hash", ("token_hash",)),
        (
            "uq_otp_flows_registration_idempotency_record_id",
            ("registration_idempotency_record_id",),
        ),
    },
    "otp_challenges": set(),
    "otp_outbox": {
        ("uq_otp_outbox_challenge_id", ("challenge_id",)),
        (
            "uq_otp_outbox_provider_idempotency_key",
            ("provider_idempotency_key",),
        ),
    },
    "registration_idempotency_records": {
        (
            "uq_registration_idempotency_records_idempotency_key_hash",
            ("idempotency_key_hash",),
        ),
        (
            "uq_registration_idempotency_records_registration_id",
            ("registration_id",),
        ),
        ("uq_registration_idempotency_records_outbox_id", ("outbox_id",)),
    },
}
EXPECTED_0019_FOREIGN_KEYS = {
    "otp_purpose_authorities": {
        (
            "fk_otp_authority_registration",
            ("registration_id",),
            "student_registrations",
            ("id",),
            "CASCADE",
        )
    },
    "otp_rate_limit_buckets": set(),
    "otp_flows": {
        (
            "fk_otp_flows_authority_id_otp_purpose_authorities",
            ("authority_id",),
            "otp_purpose_authorities",
            ("id",),
            "CASCADE",
        ),
        (
            "fk_otp_flows_registration_id_student_registrations",
            ("registration_id",),
            "student_registrations",
            ("id",),
            "CASCADE",
        ),
        (
            "fk_otp_flows_challenge_id_otp_challenges",
            ("challenge_id",),
            "otp_challenges",
            ("id",),
            "SET NULL",
        ),
        (
            "fk_otp_flow_registration_idempotency",
            ("registration_idempotency_record_id",),
            "registration_idempotency_records",
            ("id",),
            "RESTRICT",
        ),
    },
    "otp_challenges": {
        (
            "fk_otp_challenges_registration_id_student_registrations",
            ("registration_id",),
            "student_registrations",
            ("id",),
            "CASCADE",
        ),
        (
            "fk_otp_challenges_authority",
            ("authority_id",),
            "otp_purpose_authorities",
            ("id",),
            "CASCADE",
        ),
    },
    "otp_outbox": {
        (
            "fk_otp_outbox_challenge_id_otp_challenges",
            ("challenge_id",),
            "otp_challenges",
            ("id",),
            "CASCADE",
        )
    },
    "registration_idempotency_records": {
        (
            "fk_reg_idem_registration",
            ("registration_id",),
            "student_registrations",
            ("id",),
            "SET NULL",
        ),
        (
            "fk_reg_idem_outbox",
            ("outbox_id",),
            "otp_outbox",
            ("id",),
            "SET NULL",
        ),
    },
}

EXPECTED_0019_CHECKS = {
    "otp_purpose_authorities": {
        "ck_otp_purpose_authorities_subject_hash_shape",
        "ck_otp_purpose_authorities_purpose",
        "ck_otp_purpose_authorities_failed_attempts_nonneg",
        "ck_otp_purpose_authorities_max_attempts_positive",
        "ck_otp_purpose_authorities_max_attempts_bounded",
        "ck_otp_purpose_authorities_failed_attempts_le_max",
        "ck_otp_purpose_authorities_resend_count_nonneg",
        "ck_otp_purpose_authorities_max_resends_positive",
        "ck_otp_purpose_authorities_max_resends_bounded",
        "ck_otp_purpose_authorities_resend_count_within_limit",
        "ck_otp_purpose_authorities_generation_nonneg",
    },
    "otp_rate_limit_buckets": {
        "ck_otp_rate_limit_buckets_scope",
        "ck_otp_rate_limit_buckets_action",
        "ck_otp_rate_limit_buckets_subject_hash_shape",
        "ck_otp_rate_limit_buckets_window_seconds_positive",
        "ck_otp_rate_limit_buckets_window_seconds_bounded",
        "ck_otp_rate_limit_buckets_request_count_nonnegative",
        "ck_otp_rate_limit_buckets_max_requests_positive",
        "ck_otp_rate_limit_buckets_max_requests_bounded",
        "ck_otp_rate_limit_buckets_request_count_within_limit",
    },
    "otp_flows": {
        "ck_otp_flows_purpose",
        "ck_otp_flows_state",
        "ck_otp_flows_token_hash_shape",
        "ck_otp_flows_subject_hash_shape",
        "ck_otp_flows_challenge_requires_registration",
        "ck_otp_flows_consumption_shape",
        "ck_otp_flows_verified_links",
        "ck_otp_flows_destination_shape",
    },
    "otp_challenges": {
        "ck_otp_challenges_ck_otp_challenges_purpose",
        "ck_otp_challenges_ck_otp_challenges_attempts_nonneg",
        "ck_otp_challenges_ck_otp_challenges_max_positive",
        "ck_otp_challenges_ck_otp_challenges_attempts_le_max",
        "ck_otp_challenges_delivery_state",
        "ck_otp_challenges_delivery_state_consumed_at",
    },
    "otp_outbox": {
        "ck_otp_outbox_ck_otp_outbox_attempts_nonneg",
        "ck_otp_outbox_status",
        "ck_otp_outbox_max_attempts_positive",
        "ck_otp_outbox_max_attempts_bounded",
        "ck_otp_outbox_attempts_le_max",
        "ck_otp_outbox_provider_idempotency_key_shape",
        "ck_otp_outbox_claim_shape",
        "ck_otp_outbox_claim_token_hash_shape",
        "ck_otp_outbox_payload_shape",
        "ck_otp_outbox_legacy_destination_terminal",
        "ck_otp_outbox_retry_shape",
        "ck_otp_outbox_provider_receipt_shape",
        "ck_otp_outbox_provider_receipt_hash_shape",
    },
    "registration_idempotency_records": {
        "ck_registration_idempotency_records_state",
        "ck_registration_idempotency_records_key_hash_shape",
        "ck_registration_idempotency_records_request_fingerprint_shape",
        "ck_registration_idempotency_records_state_links",
    },
}

EXPECTED_0019_INDEXES = {
    "otp_purpose_authorities": {
        (
            "ix_otp_purpose_authorities_registration_id",
            ("registration_id",),
            False,
            None,
        )
    },
    "otp_rate_limit_buckets": set(),
    "otp_flows": {
        ("ix_otp_flows_authority_id", ("authority_id",), False, None),
        ("ix_otp_flows_challenge_id", ("challenge_id",), False, None),
        ("ix_otp_flows_registration_id", ("registration_id",), False, None),
        (
            "ix_otp_flows_registration_idempotency_record_id",
            ("registration_idempotency_record_id",),
            False,
            None,
        ),
        (
            "uq_otp_flows_one_nonterminal_per_authority",
            ("authority_id",),
            True,
            "state in ('pending','code_sent','verified','locked')",
        ),
    },
    "otp_challenges": {
        ("ix_otp_challenges_registration_id", ("registration_id",), False, None),
        ("ix_otp_challenges_authority_id", ("authority_id",), False, None),
        (
            "uq_otp_challenges_one_active_per_registration_purpose",
            ("registration_id", "purpose"),
            True,
            "consumed_at is null",
        ),
        (
            "uq_otp_challenges_one_active_per_authority",
            ("authority_id",),
            True,
            "authority_id is not null and delivery_state='active'",
        ),
        (
            "uq_otp_challenges_one_pending_delivery_per_authority",
            ("authority_id",),
            True,
            "authority_id is not null and delivery_state='pending_delivery'",
        ),
    },
    "otp_outbox": {("ix_otp_outbox_challenge_id", ("challenge_id",), False, None)},
    "registration_idempotency_records": set(),
}


def _hex_check_contract(column: str) -> str:
    expression = column
    for character in "0123456789abcdef":
        expression = f"replace({expression}, '{character}', '')"
    return f"length({column}) = 64 AND length({expression}) = 0"


EXPECTED_0019_CHECK_SQL = {
    "ck_otp_purpose_authorities_subject_hash_shape": _hex_check_contract(
        "subject_hash"
    ),
    "ck_otp_purpose_authorities_purpose": (
        "purpose IN ('signup', 'recovery', 'login')"
    ),
    "ck_otp_purpose_authorities_failed_attempts_nonneg": "failed_attempts >= 0",
    "ck_otp_purpose_authorities_max_attempts_positive": "max_attempts > 0",
    "ck_otp_purpose_authorities_max_attempts_bounded": "max_attempts <= 10",
    "ck_otp_purpose_authorities_failed_attempts_le_max": (
        "failed_attempts <= max_attempts"
    ),
    "ck_otp_purpose_authorities_resend_count_nonneg": "resend_count >= 0",
    "ck_otp_purpose_authorities_max_resends_positive": "max_resends > 0",
    "ck_otp_purpose_authorities_max_resends_bounded": "max_resends <= 10",
    "ck_otp_purpose_authorities_resend_count_within_limit": (
        "resend_count <= max_resends"
    ),
    "ck_otp_purpose_authorities_generation_nonneg": "generation >= 0",
    "ck_otp_rate_limit_buckets_scope": "scope IN ('identity', 'ip', 'global')",
    "ck_otp_rate_limit_buckets_action": "action IN ('issue', 'resend', 'verify')",
    "ck_otp_rate_limit_buckets_subject_hash_shape": _hex_check_contract("subject_hash"),
    "ck_otp_rate_limit_buckets_window_seconds_positive": "window_seconds > 0",
    "ck_otp_rate_limit_buckets_window_seconds_bounded": "window_seconds <= 86400",
    "ck_otp_rate_limit_buckets_request_count_nonnegative": "request_count >= 0",
    "ck_otp_rate_limit_buckets_max_requests_positive": "max_requests > 0",
    "ck_otp_rate_limit_buckets_max_requests_bounded": "max_requests <= 100000",
    "ck_otp_rate_limit_buckets_request_count_within_limit": (
        "request_count <= max_requests"
    ),
    "ck_otp_flows_purpose": "purpose IN ('signup', 'recovery', 'login')",
    "ck_otp_flows_state": (
        "state IN ('pending', 'code_sent', 'verified', 'locked', 'expired', "
        "'consumed', 'failed')"
    ),
    "ck_otp_flows_token_hash_shape": _hex_check_contract("token_hash"),
    "ck_otp_flows_subject_hash_shape": _hex_check_contract("subject_hash"),
    "ck_otp_flows_challenge_requires_registration": (
        "registration_id IS NOT NULL OR challenge_id IS NULL"
    ),
    "ck_otp_flows_consumption_shape": (
        "(state IN ('expired', 'consumed', 'failed') AND consumed_at IS NOT NULL) "
        "OR (state IN ('pending', 'code_sent', 'verified', 'locked') AND "
        "consumed_at IS NULL)"
    ),
    "ck_otp_flows_verified_links": (
        "state <> 'verified' OR "
        "(registration_id IS NOT NULL AND challenge_id IS NOT NULL)"
    ),
    "ck_otp_flows_destination_shape": (
        "(state IN ('pending', 'code_sent', 'locked') AND "
        "destination_masked_ct IS NOT NULL AND key_version IS NOT NULL) OR "
        "(state IN ('verified', 'expired', 'consumed', 'failed') AND "
        "destination_masked_ct IS NULL AND key_version IS NULL)"
    ),
    "ck_otp_challenges_ck_otp_challenges_purpose": (
        "purpose IN ('signup', 'recovery', 'login')"
    ),
    "ck_otp_challenges_ck_otp_challenges_attempts_nonneg": "attempts >= 0",
    "ck_otp_challenges_ck_otp_challenges_max_positive": "max_attempts > 0",
    "ck_otp_challenges_ck_otp_challenges_attempts_le_max": ("attempts <= max_attempts"),
    "ck_otp_challenges_delivery_state": (
        "delivery_state IN ('pending_delivery', 'active', 'consumed', "
        "'superseded', 'void')"
    ),
    "ck_otp_challenges_delivery_state_consumed_at": (
        "(delivery_state = 'active' AND consumed_at IS NULL) OR "
        "(delivery_state <> 'active' AND consumed_at IS NOT NULL)"
    ),
    "ck_otp_outbox_ck_otp_outbox_attempts_nonneg": "attempts >= 0",
    "ck_otp_outbox_status": (
        "status IN ('pending', 'claimed', 'sent', 'failed', 'void')"
    ),
    "ck_otp_outbox_max_attempts_positive": "max_attempts > 0",
    "ck_otp_outbox_max_attempts_bounded": "max_attempts <= 10",
    "ck_otp_outbox_attempts_le_max": "attempts <= max_attempts",
    "ck_otp_outbox_provider_idempotency_key_shape": _hex_check_contract(
        "provider_idempotency_key"
    ),
    "ck_otp_outbox_claim_shape": (
        "(status = 'claimed' AND claim_token_hash IS NOT NULL AND "
        "claimed_at IS NOT NULL AND lease_expires_at IS NOT NULL AND "
        "lease_expires_at > claimed_at) OR "
        "(status <> 'claimed' AND claim_token_hash IS NULL AND "
        "claimed_at IS NULL AND lease_expires_at IS NULL)"
    ),
    "ck_otp_outbox_claim_token_hash_shape": (
        "claim_token_hash IS NULL OR (" + _hex_check_contract("claim_token_hash") + ")"
    ),
    "ck_otp_outbox_payload_shape": (
        "(status IN ('pending', 'claimed', 'failed') AND code_ct IS NOT NULL "
        "AND destination_ct IS NOT NULL AND legacy_destination_retained = false) "
        "OR (status IN ('sent', 'void') AND code_ct IS NULL AND "
        "((destination_ct IS NULL AND legacy_destination_retained = false) OR "
        "(destination_ct IS NOT NULL AND legacy_destination_retained = true)))"
    ),
    "ck_otp_outbox_legacy_destination_terminal": (
        "legacy_destination_retained = false OR status IN ('sent', 'void')"
    ),
    "ck_otp_outbox_retry_shape": (
        "(status = 'failed' AND next_attempt_at IS NOT NULL) OR "
        "(status <> 'failed' AND next_attempt_at IS NULL)"
    ),
    "ck_otp_outbox_provider_receipt_shape": (
        "(provider_receipt_hash IS NULL AND provider_receipt_key_version IS NULL) "
        "OR (status = 'sent' AND provider_receipt_hash IS NOT NULL AND "
        "provider_receipt_key_version = 'v1')"
    ),
    "ck_otp_outbox_provider_receipt_hash_shape": (
        "provider_receipt_hash IS NULL OR ("
        + _hex_check_contract("provider_receipt_hash")
        + ")"
    ),
    "ck_registration_idempotency_records_state": (
        "state IN ('pending', 'succeeded', 'failed', 'retired', 'erased', "
        "'neutralized')"
    ),
    "ck_registration_idempotency_records_key_hash_shape": _hex_check_contract(
        "idempotency_key_hash"
    ),
    "ck_registration_idempotency_records_request_fingerprint_shape": (
        "((state IN ('pending', 'succeeded', 'failed', 'neutralized') AND "
        "request_fingerprint_version = 'v1' AND request_fingerprint IS NOT NULL "
        "AND length(request_fingerprint) = 64 AND "
        + _hex_check_contract("request_fingerprint")
        + ") OR (state IN ('retired', 'erased') AND request_fingerprint IS NULL "
        "AND request_fingerprint_version IS NULL))"
    ),
    "ck_registration_idempotency_records_state_links": (
        "(state = 'pending' AND registration_id IS NOT NULL AND outbox_id IS NOT NULL "
        "AND outcome_code IS NULL) OR "
        "(state = 'succeeded' AND registration_id IS NOT NULL AND outbox_id IS NULL "
        "AND outcome_code IS NULL) OR "
        "(state = 'failed' AND registration_id IS NULL AND outbox_id IS NULL AND "
        "outcome_code = 'otp_delivery_failed') OR "
        "(state = 'neutralized' AND registration_id IS NULL AND outbox_id IS NULL "
        "AND outcome_code = 'registration_neutralized') OR "
        "(state IN ('retired', 'erased') AND registration_id IS NULL AND "
        "outbox_id IS NULL AND outcome_code = 'registration_replay_expired')"
    ),
}

_UUID_TEXT = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_EMAIL_TEXT = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_MOBILE_TEXT = re.compile(r"(?<!\d)\d{10}(?!\d)")
_OTP_TEXT = re.compile(r"(?<!\d)\d{6}(?!\d)")
_IP_TEXT = re.compile(
    r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)"
)
_URL_TEXT = re.compile(r"(?i)\b(?:postgres(?:ql)?|https?)\+?[^\s:]*://")
_HEX64_TEXT = re.compile(r"(?i)(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
_CIPHERTEXT_TEXT = re.compile(r"\bv[0-9]+:[A-Za-z0-9_-]{24,}={0,2}\b")

_FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "database_url",
        "scratch_database",
        "database_name",
        "mobile",
        "destination",
        "subject",
        "subject_hash",
        "ip",
        "ip_hash",
        "otp",
        "code",
        "cookie",
        "flow_token",
        "flow_token_hash",
        "provider_token",
        "provider_idempotency_key",
        "claim_token",
        "ciphertext",
        "registration_id",
        "challenge_id",
        "authority_id",
        "outbox_id",
        "user_id",
        "payload",
        "request",
        "response_body",
        "exception",
        "traceback",
    }
)


class Blocked(RuntimeError):
    """The authoritative runtime is absent or routing is unsafe."""


class ProductGateFailure(RuntimeError):
    """A product, migration, or harness invariant failed."""


class ScratchCleanupFailure(RuntimeError):
    """A disposable database remained or could not be inventoried."""


class _CertifiedGateProvider:
    """Named, in-memory provider contract for retry/idempotency evidence.

    The double models a provider that binds one opaque token to one exact
    destination/code payload and durably records acceptance before returning an
    acknowledgement.  It can lose the first acknowledgement after acceptance,
    which is the only honest way to characterize the local crash window.  Its
    private payload map is never serialized into evidence.
    """

    contract_name = "nyay4_gate_idempotent_provider_v1"

    def __init__(
        self,
        *,
        lose_ack_after_accept_once: bool = False,
        fail_before_accept_count: int = 0,
        callback: Callable[[], None] | None = None,
    ) -> None:
        self.calls = 0
        self._accepted: dict[str, tuple[str, str, str]] = {}
        self._lose_ack_after_accept_once = lose_ack_after_accept_once
        self._ack_lost = False
        self._fail_before_accept_count = fail_before_accept_count
        self._callback = callback

    @property
    def acceptance_count(self) -> int:
        return len(self._accepted)

    def _private_accepted_codes(self) -> tuple[str, ...]:
        """Return private in-process codes for verification probes only.

        Callers must never place the values in an observation or exception.
        """

        return tuple(payload[1] for payload in self._accepted.values())

    def send_idempotent(
        self,
        destination: str,
        code: str,
        *,
        idempotency_token: str,
    ) -> str:
        from app.services.otp_sender import OtpSendError

        self.calls += 1
        if self._callback is not None:
            self._callback()
        existing = self._accepted.get(idempotency_token)
        if existing is not None:
            if existing[:2] != (destination, code):
                raise OtpSendError("otp provider idempotency conflict")
            return existing[2]
        if self._fail_before_accept_count > 0:
            self._fail_before_accept_count -= 1
            raise OtpSendError("otp provider unavailable")
        receipt = f"gate-receipt-{len(self._accepted) + 1}"
        self._accepted[idempotency_token] = (destination, code, receipt)
        if self._lose_ack_after_accept_once and not self._ack_lost:
            self._ack_lost = True
            raise OtpSendError("otp provider acknowledgement lost")
        return receipt


def _is_exact_bool(value: object) -> bool:
    return value is True or value is False


def _behavior_fixture_mobile_inventory_is_unique(
    inventory: Mapping[str, str] | None = None,
) -> bool:
    source = BEHAVIOR_FIXTURE_MOBILES if inventory is None else inventory
    values = list(source.values())
    return bool(
        source
        and all(re.fullmatch(r"[0-9]{10}", value) for value in values)
        and len(values) == len(set(values))
    )


def _behavior_fixture_mobile(name: str) -> str:
    if not _behavior_fixture_mobile_inventory_is_unique():
        raise ProductGateFailure("NYAY-4 behavior fixture inventory is unsafe")
    try:
        return BEHAVIOR_FIXTURE_MOBILES[name]
    except KeyError as exc:
        raise ProductGateFailure("NYAY-4 behavior fixture is unreviewed") from exc


def _exact_keys(observation: Mapping[str, Any], expected: set[str]) -> bool:
    return set(observation) == expected


def _reject_ambient_libpq_environment(
    environment: Mapping[str, str] | None = None,
) -> None:
    source = os.environ if environment is None else environment
    if any(key in LIBPQ_AMBIENT_KEYS or key.startswith("PGSSL") for key in source):
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
    except Exception as exc:  # supplied URL remains private
        raise Blocked("a valid PostgreSQL URL is required") from exc
    if url.get_backend_name() != "postgresql":
        raise Blocked("a PostgreSQL URL is required")
    if url.query:
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
    engine = create_engine(
        _database_url(base, "postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text(statement))
    finally:
        engine.dispose()


def _drop_scratch(base: URL, name: str) -> None:
    try:
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    except Exception:  # pragma: no cover - compatibility fallback
        _admin_execute(base, f'DROP DATABASE IF EXISTS "{name}"')


def _create_scratch(base: URL, name: str) -> str:
    try:
        _drop_scratch(base, name)
        _admin_execute(base, f'CREATE DATABASE "{name}"')
    except Exception as exc:
        raise Blocked("could not create the disposable scratch database") from exc
    return _database_url(base, name)


def _scratch_database_inventory(base: URL) -> set[str]:
    """Return private scratch names in-memory; names never enter evidence."""

    engine = create_engine(_database_url(base, "postgres"), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            return {
                str(value)
                for value in connection.scalars(
                    text(
                        "SELECT datname FROM pg_database "
                        "WHERE datname LIKE 'nyay4_otp_%'"
                    )
                )
            }
    finally:
        engine.dispose()


class _ScratchDatabaseManager:
    """Own scratch databases and make verified removal part of the verdict."""

    def __init__(self, base: URL) -> None:
        self.base = base
        self.records: list[dict[str, Any]] = []
        self._owned_names: set[str] = set()
        try:
            self._baseline = _scratch_database_inventory(base)
        except Exception as exc:
            raise Blocked("could not inventory disposable scratch databases") from exc

    def run(self, purpose: str, operation: Callable[[str], Any]) -> Any:
        name = f"{SCRATCH_PREFIX}{uuid.uuid4().hex[:12]}"
        record = {"purpose": purpose, "created": False, "cleanup": "NOT_CREATED"}
        self.records.append(record)
        self._owned_names.add(name)
        scratch_url = _create_scratch(self.base, name)
        record["created"] = True
        try:
            return operation(scratch_url)
        finally:
            try:
                _drop_scratch(self.base, name)
                if name in _scratch_database_inventory(self.base):
                    raise ScratchCleanupFailure(
                        "a disposable NYAY-4 database remained after cleanup"
                    )
            except ScratchCleanupFailure:
                record["cleanup"] = "FAIL"
                raise
            except Exception as exc:
                record["cleanup"] = "FAIL"
                raise ScratchCleanupFailure(
                    "a disposable NYAY-4 database could not be removed"
                ) from exc
            record["cleanup"] = "PASS"

    @property
    def scratch_created(self) -> bool:
        return any(record["created"] is True for record in self.records)

    def summary(self) -> dict[str, Any]:
        created = sum(record["created"] is True for record in self.records)
        removed = sum(record["cleanup"] == "PASS" for record in self.records)
        failed = sum(record["cleanup"] == "FAIL" for record in self.records)
        try:
            final = _scratch_database_inventory(self.base)
            inventory_match = bool(
                final == self._baseline and not self._owned_names.intersection(final)
            )
        except Exception:
            inventory_match = False
        return {
            "created": created,
            "removed": removed,
            "failed": failed,
            "purposes": [record["purpose"] for record in self.records],
            "inventory_match": inventory_match,
            "all_created_removed": (
                created == removed and failed == 0 and inventory_match
            ),
        }


def _runtime_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "postgres_major",
                "pgvector_present",
                "loopback",
                "query_free",
                "ambient_rejected",
            },
        )
        and observation["postgres_major"] == 16
        and observation["pgvector_present"] is True
        and observation["loopback"] is True
        and observation["query_free"] is True
        and observation["ambient_rejected"] is True
    )


def _migration_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "start_revision",
                "head_revision",
                "single_head",
                "upgrade",
                "downgrade",
                "reupgrade",
                "alembic_check",
                "historical_digest_unchanged",
                "row_projection_unchanged",
                "parent_validator_exact",
                "multi_step_downgrade_reupgrade",
                "upgrade_failure_atomic",
                "downgrade_failure_atomic",
                "retry_after_induced_failure",
            },
        )
        and observation["start_revision"] == PREVIOUS_REVISION
        and observation["head_revision"] == PINNED_HEAD
        and observation["single_head"] is True
        and observation["upgrade"] is True
        and observation["downgrade"] is True
        and observation["reupgrade"] is True
        and observation["alembic_check"] is True
        and observation["historical_digest_unchanged"] is True
        and observation["row_projection_unchanged"] is True
        and observation["parent_validator_exact"] is True
        and observation["multi_step_downgrade_reupgrade"] is True
        and observation["upgrade_failure_atomic"] is True
        and observation["downgrade_failure_atomic"] is True
        and observation["retry_after_induced_failure"] is True
    )


def _populated_migration_observation_passes(
    observation: Mapping[str, Any],
) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "legacy_rows",
                "authority_rows",
                "flow_rows",
                "challenge_authority_nonnull",
                "flow_authority_nonnull",
                "raw_subject_columns",
                "raw_ip_columns",
                "old_writer_challenge_rejected",
                "legacy_destination_writer_rejected",
                "post_upgrade_restart_status",
                "post_upgrade_restart_cookie_issued",
                "post_upgrade_restart_uuid_exposed",
                "post_upgrade_resend_status",
                "post_upgrade_provider_acceptances",
                "post_upgrade_verify_status",
                "post_upgrade_registration_active",
                "post_upgrade_ledger_retired",
                "post_upgrade_terminal_replays_uniform",
                "post_upgrade_terminal_replays_zero_delta",
                "downgrade_rejected",
                "revision_unchanged",
                "schema_unchanged",
                "rows_unchanged",
            },
        )
        and isinstance(observation["legacy_rows"], int)
        and observation["legacy_rows"] > 0
        and observation["authority_rows"] == observation["legacy_rows"]
        # A migration cannot safely mint a raw HttpOnly bearer capability for
        # an already-running browser. Legacy challenges receive stable
        # authority, but deliberately no flow; clients restart the ceremony.
        and observation["flow_rows"] == 0
        and observation["challenge_authority_nonnull"] is True
        and observation["flow_authority_nonnull"] is True
        and observation["raw_subject_columns"] == 0
        and observation["raw_ip_columns"] == 0
        and observation["old_writer_challenge_rejected"] is True
        and observation["legacy_destination_writer_rejected"] is True
        # `flow_rows == 0` is safe only when runtime can recover the exact
        # pre-upgrade bootstrap authority. Prove the original key holder can
        # receive a fresh verifier, finish signup, and leave a terminal key
        # tombstone without exposing the registration UUID.
        and observation["post_upgrade_restart_status"] == 201
        and observation["post_upgrade_restart_cookie_issued"] is True
        and observation["post_upgrade_restart_uuid_exposed"] is False
        and observation["post_upgrade_resend_status"] == 202
        and observation["post_upgrade_provider_acceptances"] == 1
        and observation["post_upgrade_verify_status"] == 200
        and observation["post_upgrade_registration_active"] is True
        and observation["post_upgrade_ledger_retired"] is True
        and observation["post_upgrade_terminal_replays_uniform"] is True
        and observation["post_upgrade_terminal_replays_zero_delta"] is True
        and observation["downgrade_rejected"] is True
        and observation["revision_unchanged"] is True
        and observation["schema_unchanged"] is True
        and observation["rows_unchanged"] is True
    )


def _schema_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "exact_tables",
                "exact_columns",
                "exact_primary_keys",
                "exact_unique_constraints",
                "exact_foreign_keys",
                "exact_check_constraints",
                "exact_indexes",
                "challenge_authority_nonnull",
                "flow_authority_nonnull",
                "provider_key_shape",
                "claim_state_shape",
                "neutralized_ledger_shape",
                "raw_sensitive_columns",
            },
        )
        and all(
            observation[field] is True
            for field in (
                "exact_tables",
                "exact_columns",
                "exact_primary_keys",
                "exact_unique_constraints",
                "exact_foreign_keys",
                "exact_check_constraints",
                "exact_indexes",
                "challenge_authority_nonnull",
                "flow_authority_nonnull",
                "provider_key_shape",
                "claim_state_shape",
                "neutralized_ledger_shape",
            )
        )
        and observation["raw_sensitive_columns"] == 0
    )


def _lockout_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "configured_max_attempts",
                "configured_lock_seconds",
                "wrong_statuses",
                "wrong_codes",
                "attempts_after_wrong",
                "locked",
                "resend_status",
                "resend_code",
                "attempts_after_resend",
                "lock_deadline_unchanged",
                "new_delivery_delta",
            },
        )
        and isinstance(observation["configured_max_attempts"], int)
        and observation["configured_max_attempts"] > 0
        and isinstance(observation["configured_lock_seconds"], int)
        and observation["configured_lock_seconds"] > 0
        and len(observation["wrong_statuses"]) == observation["configured_max_attempts"]
        and observation["wrong_statuses"][-1] == 423
        and observation["wrong_codes"][-1] == "locked"
        and observation["attempts_after_wrong"]
        == observation["configured_max_attempts"]
        and observation["locked"] is True
        and observation["resend_status"] in {423, 429}
        and observation["resend_code"] in {"locked", "resend_locked"}
        and observation["attempts_after_resend"]
        == observation["configured_max_attempts"]
        and observation["lock_deadline_unchanged"] is True
        and observation["new_delivery_delta"] == 0
    )


def _concurrent_verify_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "workers",
                "completed",
                "deadlocks",
                "successes",
                "typed_failures",
                "stored_attempts",
                "configured_max_attempts",
                "locked",
                "active_challenges",
                "deliverable_outboxes",
            },
        )
        and observation["workers"] >= observation["configured_max_attempts"] + 2
        and observation["completed"] == observation["workers"]
        and observation["deadlocks"] == 0
        and observation["successes"] == 0
        and observation["typed_failures"] == observation["workers"]
        and observation["stored_attempts"] == observation["configured_max_attempts"]
        and observation["locked"] is True
        and observation["active_challenges"] == 1
        and observation["deliverable_outboxes"] <= 1
    )


def _resend_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "workers",
                "completed",
                "deadlocks",
                "accepted_resends",
                "typed_rejections",
                "authority_rows",
                "staged_challenges",
                "active_challenges",
                "deliverable_outboxes",
                "attempts_unchanged",
                "lock_unchanged",
                "resend_budget_delta",
                "expired_active_status_before_resend",
                "expired_active_resend_allowed",
                "expired_active_resend_status",
                "expired_active_replacement_active",
                "expired_active_attempts_unchanged",
                "expired_active_delivery_delta",
                "alternation_purposes",
                "fractional_retry_after_ceil",
                "exhausted_start_status",
                "exhausted_start_zero_delivery",
                "alternation_real_decoy_equal",
            },
        )
        and observation["workers"] >= 4
        and observation["completed"] == observation["workers"]
        and observation["deadlocks"] == 0
        and observation["accepted_resends"] == 1
        and observation["typed_rejections"] == observation["workers"] - 1
        and observation["authority_rows"] == 1
        and observation["staged_challenges"] == 1
        and observation["active_challenges"] == 1
        and observation["deliverable_outboxes"] == 1
        and observation["attempts_unchanged"] is True
        and observation["lock_unchanged"] is True
        and observation["resend_budget_delta"] == 1
        and observation["expired_active_status_before_resend"] == "pending"
        and observation["expired_active_resend_allowed"] is True
        and observation["expired_active_resend_status"] == 202
        and observation["expired_active_replacement_active"] is True
        and observation["expired_active_attempts_unchanged"] is True
        and observation["expired_active_delivery_delta"] == 1
        and observation["alternation_purposes"] == ["login", "recovery"]
        and observation["fractional_retry_after_ceil"] is True
        and observation["exhausted_start_status"] == 429
        and observation["exhausted_start_zero_delivery"] is True
        and observation["alternation_real_decoy_equal"] is True
    )


def _failed_resend_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "status",
                "code",
                "prior_active_unchanged",
                "prior_verification_succeeds",
                "replacement_active",
                "replacement_deliverable",
                "provider_acceptances",
                "authority_unchanged",
            },
        )
        and observation["status"] == 502
        and observation["code"] == "otp_delivery_failed"
        and observation["prior_active_unchanged"] is True
        and observation["prior_verification_succeeds"] is True
        and observation["replacement_active"] is False
        and observation["replacement_deliverable"] is False
        and observation["provider_acceptances"] == 0
        and observation["authority_unchanged"] is True
    )


def _rate_observation_passes(observation: Mapping[str, Any]) -> bool:
    expected_dimensions = {
        "identity_issue",
        "identity_resend",
        "identity_verify",
        "ip_issue",
        "ip_resend",
        "ip_verify",
        "global_issue",
        "global_resend",
        "global_verify",
    }
    return bool(
        _exact_keys(
            observation,
            {
                "dimensions",
                "limits_positive",
                "accepted_equal_limits",
                "next_rejected",
                "retry_after_exact",
                "real_decoy_symmetric",
                "untrusted_forwarded_for_ignored",
                "raw_identity_rows",
                "raw_ip_rows",
                "retention_preserves_active_budgets",
                "maintenance_entrypoint_executed",
                "aged_buckets_purged",
                "active_recent_buckets_preserved",
            },
        )
        and set(observation["dimensions"]) == expected_dimensions
        and observation["limits_positive"] is True
        and observation["accepted_equal_limits"] is True
        and observation["next_rejected"] is True
        and observation["retry_after_exact"] is True
        and observation["real_decoy_symmetric"] is True
        and observation["untrusted_forwarded_for_ignored"] is True
        and observation["raw_identity_rows"] == 0
        and observation["raw_ip_rows"] == 0
        and observation["retention_preserves_active_budgets"] is True
        and observation["maintenance_entrypoint_executed"] is True
        and observation["aged_buckets_purged"] is True
        and observation["active_recent_buckets_preserved"] is True
    )


def _cookie_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "start_statuses",
                "start_signatures_equal",
                "timing_ratio_within_bound",
                "timing_samples_per_class",
                "timing_p95_ratio_milli",
                "timing_bound_milli",
                "cookie_httponly",
                "cookie_secure_nonlocal",
                "cookie_samesite",
                "raw_flow_token_rows",
                "uuid_in_response",
                "reload_status",
                "reload_metadata_equal",
                "origin_missing_status",
                "origin_bad_status",
                "origin_good_status",
                "invalid_expired_consumed_signatures_equal",
                "invalid_expired_consumed_values_equal",
                "terminal_verify_zero_delta",
                "initial_exhaustion_purposes",
                "initial_exhaustion_known_decoy_shapes_equal",
                "initial_exhaustion_known_decoy_values_equal",
                "initial_exhaustion_symmetry_through_flow_ttl",
                "fully_expired_status",
                "fully_expired_known_decoy_values_equal",
                "neutralized_key_request_bound",
                "neutralized_exact_replay_stable",
                "neutralized_live_mutations_conflict",
                "neutralized_concurrent_mismatch_linearized",
                "neutralized_expired_mutations_uniform",
                "neutralized_removed_mutations_uniform",
                "pending_expired_mutations_uniform",
                "pending_missing_mutations_uniform",
                "lifecycle_replay_zero_provider",
                "lifecycle_replay_zero_delta",
            },
        )
        and observation["start_statuses"] == [202, 202]
        and observation["start_signatures_equal"] is True
        and observation["timing_ratio_within_bound"] is True
        and observation["timing_samples_per_class"] >= 8
        and 0
        <= observation["timing_p95_ratio_milli"]
        <= observation["timing_bound_milli"]
        and observation["timing_bound_milli"] == 2000
        and observation["cookie_httponly"] is True
        and observation["cookie_secure_nonlocal"] is True
        and observation["cookie_samesite"] in {"lax", "strict"}
        and observation["raw_flow_token_rows"] == 0
        and observation["uuid_in_response"] is False
        and observation["reload_status"] == 200
        and observation["reload_metadata_equal"] is True
        and observation["origin_missing_status"] == 403
        and observation["origin_bad_status"] == 403
        and observation["origin_good_status"] in {200, 202}
        and observation["invalid_expired_consumed_signatures_equal"] is True
        and observation["invalid_expired_consumed_values_equal"] is True
        and observation["terminal_verify_zero_delta"] is True
        and observation["initial_exhaustion_purposes"] == ["login", "recovery"]
        and observation["initial_exhaustion_known_decoy_shapes_equal"] is True
        and observation["initial_exhaustion_known_decoy_values_equal"] is True
        and observation["initial_exhaustion_symmetry_through_flow_ttl"] is True
        and observation["fully_expired_status"] == "unavailable"
        and observation["fully_expired_known_decoy_values_equal"] is True
        and observation["neutralized_key_request_bound"] is True
        and observation["neutralized_exact_replay_stable"] is True
        and observation["neutralized_live_mutations_conflict"] is True
        and observation["neutralized_concurrent_mismatch_linearized"] is True
        and observation["neutralized_expired_mutations_uniform"] is True
        and observation["neutralized_removed_mutations_uniform"] is True
        and observation["pending_expired_mutations_uniform"] is True
        and observation["pending_missing_mutations_uniform"] is True
        and observation["lifecycle_replay_zero_provider"] is True
        and observation["lifecycle_replay_zero_delta"] is True
    )


def _metadata_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "fields_exact",
                "attempts_from_authority",
                "cooldown_from_database",
                "expiry_from_database",
                "lock_from_database",
                "retry_after_matches",
                "bounded_clock_skew",
                "typed_outcomes_exact",
                "no_local_clock_authority",
            },
        )
        and all(observation[field] is True for field in observation)
    )


def _claim_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "workers",
                "completed",
                "deadlocks",
                "claims_won",
                "provider_callbacks",
                "provider_acceptances",
                "newly_delivered_sum",
                "active_claims",
                "row_locks_during_callback",
                "canary_lock_succeeded",
                "resend_while_claimed_rejected",
                "registration_finalizer_interleaving_passed",
            },
        )
        and observation["workers"] >= 2
        and observation["completed"] == observation["workers"]
        and observation["deadlocks"] == 0
        and observation["claims_won"] == 1
        and observation["provider_callbacks"] == 1
        and observation["provider_acceptances"] == 1
        and observation["newly_delivered_sum"] == 1
        and observation["active_claims"] == 0
        and observation["row_locks_during_callback"] == 0
        and observation["canary_lock_succeeded"] is True
        and observation["resend_while_claimed_rejected"] is True
        and observation["registration_finalizer_interleaving_passed"] is True
    )


def _provider_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "provider_contract_name",
                "provider_contract_certified",
                "real_provider_exactly_once_claimed",
                "provider_calls",
                "provider_acceptances",
                "ack_loss_injected",
                "retry_succeeded",
                "stable_key",
                "key_is_hmac64",
                "same_payload",
                "payload_conflict_rejected",
                "database_sent_once",
                "otp_ciphertext_erased",
            },
        )
        and observation["provider_contract_name"] == "nyay4_gate_idempotent_provider_v1"
        and observation["provider_contract_certified"] is True
        and observation["real_provider_exactly_once_claimed"] is False
        and observation["provider_calls"] >= 2
        and observation["provider_acceptances"] == 1
        and observation["ack_loss_injected"] is True
        and observation["retry_succeeded"] is True
        and observation["stable_key"] is True
        and observation["key_is_hmac64"] is True
        and observation["same_payload"] is True
        and observation["payload_conflict_rejected"] is True
        and observation["database_sent_once"] is True
        and observation["otp_ciphertext_erased"] is True
    )


def _retry_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "lease_expired_reclaimed",
                "new_claim_token",
                "stale_finalize_rejected",
                "stale_finalize_state_unchanged",
                "backoff_positive",
                "immediate_retry_claims",
                "attempts_at_terminal",
                "configured_max_attempts",
                "terminal_status",
                "otp_ciphertext_erased",
                "destination_ciphertext_erased",
                "initial_exhaustion_recovery_same_authority",
                "initial_exhaustion_recovery_succeeded",
                "initial_exhaustion_stale_payload_rows",
                "initial_exhaustion_exactly_one_acceptance_each",
                "initial_exhaustion_exactly_one_delivered_each",
                "aged_legacy_destinations_purged",
                "active_recent_outboxes_preserved",
                "expired_flows_terminalized",
                "expired_flow_key_reuse_blocked",
                "maintenance_counts_aggregate_only",
            },
        )
        and observation["lease_expired_reclaimed"] is True
        and observation["new_claim_token"] is True
        and observation["stale_finalize_rejected"] is True
        and observation["stale_finalize_state_unchanged"] is True
        and observation["backoff_positive"] is True
        and observation["immediate_retry_claims"] == 0
        and observation["attempts_at_terminal"]
        == observation["configured_max_attempts"]
        and observation["configured_max_attempts"] > 0
        and observation["terminal_status"] in {"failed", "void"}
        and observation["otp_ciphertext_erased"] is True
        and observation["destination_ciphertext_erased"] is True
        and observation["initial_exhaustion_recovery_same_authority"] is True
        and observation["initial_exhaustion_recovery_succeeded"] is True
        and observation["initial_exhaustion_stale_payload_rows"] == 0
        and observation["initial_exhaustion_exactly_one_acceptance_each"] is True
        and observation["initial_exhaustion_exactly_one_delivered_each"] is True
        and observation["aged_legacy_destinations_purged"] is True
        and observation["active_recent_outboxes_preserved"] is True
        and observation["expired_flows_terminalized"] is True
        and observation["expired_flow_key_reuse_blocked"] is True
        and observation["maintenance_counts_aggregate_only"] is True
    )


def _config_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "cases",
                "all_rejected",
                "production_booted",
                "valid_real_provider_booted",
                "provider_contract_certified",
                "errors_sanitized",
            },
        )
        and set(observation["cases"]) == REQUIRED_CONFIG_REJECTION_CASES
        and observation["all_rejected"] is True
        and observation["production_booted"] is False
        and observation["valid_real_provider_booted"] is True
        and observation["provider_contract_certified"] is True
        and observation["errors_sanitized"] is True
    )


def _seeded_mutants_are_killed(results: Mapping[str, bool]) -> bool:
    return bool(
        set(results) == set(REQUIRED_MUTANT_IDS)
        and all(value is True for value in results.values())
    )


def _seeded_mutant_results(
    observations: Mapping[str, Mapping[str, Any]],
) -> dict[str, bool]:
    """Inject each reviewed vulnerable outcome into the strict evaluators."""

    required = {
        "schema",
        "lockout",
        "verify",
        "resend",
        "failed_resend",
        "rate",
        "cookie",
        "claim",
        "provider",
        "retry",
        "config",
        "harness",
    }
    if set(observations) != required:
        return {identifier: False for identifier in REQUIRED_MUTANT_IDS}

    baseline_evaluators = {
        "schema": _schema_observation_passes,
        "lockout": _lockout_observation_passes,
        "verify": _concurrent_verify_observation_passes,
        "resend": _resend_observation_passes,
        "failed_resend": _failed_resend_observation_passes,
        "rate": _rate_observation_passes,
        "cookie": _cookie_observation_passes,
        "claim": _claim_observation_passes,
        "provider": _provider_observation_passes,
        "retry": _retry_observation_passes,
        "config": _config_observation_passes,
        "harness": _harness_observation_passes,
    }
    if any(
        not baseline_evaluators[name](observations[name])
        for name in sorted(required)
    ):
        return {identifier: False for identifier in REQUIRED_MUTANT_IDS}

    def killed(
        section: str,
        evaluator: Callable[[Mapping[str, Any]], bool],
        field: str,
        value: Any,
    ) -> bool:
        mutated = deepcopy(dict(observations[section]))
        mutated[field] = value
        return not evaluator(mutated)

    def rate_without(dimension: str) -> list[str]:
        return sorted(set(observations["rate"]["dimensions"]) - {dimension})

    return {
        "RESET-AUTHORITY-ON-RESEND": killed(
            "lockout", _lockout_observation_passes, "attempts_after_resend", 0
        ),
        "OMIT-AUTHORITY-FOR-UPDATE": (
            killed(
                "verify",
                _concurrent_verify_observation_passes,
                "stored_attempts",
                observations["verify"]["workers"],
            )
            and killed("resend", _resend_observation_passes, "accepted_resends", 2)
        ),
        "STORE-RAW-SUBJECT": killed(
            "schema", _schema_observation_passes, "raw_sensitive_columns", 1
        ),
        "STORE-RAW-IP": killed("rate", _rate_observation_passes, "raw_ip_rows", 1),
        "DROP-IDENTITY-BUDGET": killed(
            "rate",
            _rate_observation_passes,
            "dimensions",
            rate_without("identity_verify"),
        ),
        "DROP-IP-BUDGET": killed(
            "rate",
            _rate_observation_passes,
            "dimensions",
            rate_without("ip_verify"),
        ),
        "DROP-GLOBAL-BUDGET": killed(
            "rate",
            _rate_observation_passes,
            "dimensions",
            rate_without("global_verify"),
        ),
        "TRUST-X-FORWARDED-FOR": killed(
            "rate",
            _rate_observation_passes,
            "untrusted_forwarded_for_ignored",
            False,
        ),
        "CLEAR-CLAIM-BEFORE-ACK": killed(
            "claim", _claim_observation_passes, "claims_won", 2
        ),
        "RANDOMIZE-PROVIDER-RETRY-KEY": killed(
            "provider", _provider_observation_passes, "stable_key", False
        ),
        "MARK-SENT-BEFORE-PROVIDER": killed(
            "provider", _provider_observation_passes, "database_sent_once", False
        ),
        "ACCEPT-NONIDEMPOTENT-PROVIDER": (
            killed(
                "provider",
                _provider_observation_passes,
                "provider_contract_certified",
                False,
            )
            and killed(
                "config",
                _config_observation_passes,
                "provider_contract_certified",
                False,
            )
        ),
        "COUNT-ALREADY-SENT-AS-DELIVERED": killed(
            "claim", _claim_observation_passes, "newly_delivered_sum", 2
        ),
        "ALLOW-STALE-CLAIM-FINALIZE": killed(
            "retry", _retry_observation_passes, "stale_finalize_rejected", False
        ),
        "HOT-LOOP-FAILED-DELIVERY": killed(
            "retry", _retry_observation_passes, "immediate_retry_claims", 1
        ),
        "RETAIN-CIPHERTEXT-AFTER-EXHAUSTION": killed(
            "retry",
            _retry_observation_passes,
            "destination_ciphertext_erased",
            False,
        ),
        "ACTIVATE-RESEND-BEFORE-DELIVERY": killed(
            "failed_resend",
            _failed_resend_observation_passes,
            "replacement_active",
            True,
        ),
        "DROP-ORIGIN-BOUNDARY": killed(
            "cookie", _cookie_observation_passes, "origin_missing_status", 200
        ),
        "EXPOSE-REGISTRATION-UUID": killed(
            "cookie", _cookie_observation_passes, "uuid_in_response", True
        ),
        "HARDCODE-CLIENT-ATTEMPTS": killed(
            "harness", _harness_observation_passes, "frontend_server_authority", False
        ),
        "HARDCODE-CLIENT-COOLDOWN": killed(
            "harness", _harness_observation_passes, "frontend_server_authority", False
        ),
        "HARDCODE-CLIENT-EXPIRY": killed(
            "harness", _harness_observation_passes, "frontend_server_authority", False
        ),
        "CLIENT-RESETS-RESEND-TIMER": killed(
            "harness", _harness_observation_passes, "frontend_server_authority", False
        ),
        "AGGREGATOR-ZERO-SELECTOR": killed(
            "harness", _harness_observation_passes, "gate_command_present", False
        ),
        "MISSING-GATE-COMMAND": killed(
            "harness", _harness_observation_passes, "gate_command_present", False
        ),
    }


def _harness_observation_passes(observation: Mapping[str, Any]) -> bool:
    return bool(
        _exact_keys(
            observation,
            {
                "mutants",
                "privacy_findings",
                "privacy_scanned",
                "scratch_created",
                "scratch_removed",
                "scratch_failed",
                "scratch_purposes",
                "scratch_inventory_match",
                "all_created_removed",
                "frontend_server_authority",
                "gate_command_present",
            },
        )
        and _seeded_mutants_are_killed(observation["mutants"])
        and observation["privacy_findings"] == 0
        and observation["privacy_scanned"] is True
        and observation["scratch_created"] == 3
        and observation["scratch_removed"] == 3
        and observation["scratch_failed"] == 0
        and observation["scratch_purposes"]
        == ["migration_lifecycle", "migration_populated", "behavior"]
        and observation["scratch_inventory_match"] is True
        and observation["all_created_removed"] is True
        and observation["frontend_server_authority"] is True
        and observation["gate_command_present"] is True
    )


def _safe_response_signature(status: int, body: Mapping[str, Any]) -> dict[str, Any]:
    """Return only bounded response shape; never retain response values."""

    detail = body.get("detail")
    code_present = isinstance(detail, Mapping) and isinstance(detail.get("code"), str)
    return {
        "status": int(status),
        "top_level_keys": sorted(str(key) for key in body),
        "detail_keys": (
            sorted(str(key) for key in detail) if isinstance(detail, Mapping) else []
        ),
        "code_present": code_present,
    }


def _privacy_findings(report: Mapping[str, Any]) -> list[str]:
    """Scan aggregate evidence without copying a matched secret into findings."""

    findings: list[str] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if key_text.casefold() in _FORBIDDEN_REPORT_KEYS:
                    findings.append(f"forbidden_key:{child_path}")
                visit(child, child_path)
        elif isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(report, "")
    serialized = json.dumps(report, sort_keys=True, separators=(",", ":"))
    patterns = (
        ("uuid", _UUID_TEXT),
        ("email", _EMAIL_TEXT),
        ("mobile", _MOBILE_TEXT),
        ("otp", _OTP_TEXT),
        ("ip", _IP_TEXT),
        ("url", _URL_TEXT),
        ("hash64", _HEX64_TEXT),
        ("ciphertext", _CIPHERTEXT_TEXT),
    )
    for label, pattern in patterns:
        if pattern.search(serialized):
            findings.append(f"pattern:{label}")
    return findings


def _privacy_observation_projection(
    *,
    runtime: Mapping[str, Any],
    migration: Mapping[str, Any],
    populated: Mapping[str, Any],
    behavior: Mapping[str, Mapping[str, Any]],
    config: Mapping[str, Any],
    harness: Mapping[str, Any],
) -> dict[str, Any]:
    """Disambiguate two aggregate labels before scanning private observations.

    ``cookie`` names the public cookie-contract assertion section, not a cookie
    value, and ``failed_resend.code`` is a bounded typed outcome, not an OTP.
    No values are removed: the two labels are renamed and every other key and
    value remains subject to the same forbidden-key and secret-shape scan.
    """

    if "cookie" not in behavior or "failed_resend" not in behavior:
        raise ProductGateFailure("NYAY-4 privacy projection inventory is incomplete")
    if not _cookie_observation_passes(behavior["cookie"]):
        raise ProductGateFailure("NYAY-4 privacy projection cookie shape is unsafe")
    if not _failed_resend_observation_passes(behavior["failed_resend"]):
        raise ProductGateFailure("NYAY-4 privacy projection outcome shape is unsafe")
    failed_resend = dict(behavior["failed_resend"])
    failed_resend["typed_outcome"] = failed_resend.pop("code")
    behavior_projection = dict(behavior)
    behavior_projection["failed_resend"] = failed_resend
    behavior_projection["cookie_contract"] = behavior_projection.pop("cookie")
    return {
        "runtime": runtime,
        "migration": migration,
        "populated": populated,
        **behavior_projection,
        "config": config,
        "harness": harness,
    }


def _evaluate_assertions(assertions: list[Mapping[str, Any]]) -> dict[str, Any]:
    identifiers = [str(item.get("id", "")) for item in assertions]
    expected = list(REQUIRED_ASSERTION_IDS)
    missing = [identifier for identifier in expected if identifier not in identifiers]
    extra = [identifier for identifier in identifiers if identifier not in expected]
    duplicate = len(identifiers) - len(set(identifiers))
    exact_inventory = identifiers == expected and duplicate == 0
    failed = [
        str(item.get("id", "")) for item in assertions if item.get("passed") is not True
    ]
    return {
        "exact_inventory": exact_inventory,
        "required": len(expected),
        "passed": sum(item.get("passed") is True for item in assertions),
        "failed": failed,
        "inventory_failures": {
            "missing": len(missing),
            "extra": len(extra),
            "duplicate": duplicate,
            "reordered": (
                not missing and not extra and duplicate == 0 and identifiers != expected
            ),
        },
        "overall_pass": bool(exact_inventory and not failed),
    }


def _run_alembic(scratch_url: str, *arguments: str) -> dict[str, Any]:
    """Run Alembic while retaining no stdout, stderr, URL, or database name."""

    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND,
        env={**os.environ, "APP_ENV": "testing", "DATABASE_URL": scratch_url},
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    return {"arguments": list(arguments), "returncode": result.returncode}


def _historical_migration_bytes_unchanged(repo_root: Path | None = None) -> bool:
    """Verify the exact immutable 0001..0018 migration byte inventory."""

    root = BACKEND.parent if repo_root is None else repo_root
    ledger_path = root / "backend/app/db/migrations/MIGRATION_SHA256_LEDGER.json"
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        migrations = ledger["migrations"]
        if (
            ledger.get("schemaVersion") != 1
            or ledger.get("baseline", {}).get("migrationCount") != 15
            or len(migrations) != 15
            or [item.get("ordinal") for item in migrations] != list(range(1, 16))
        ):
            return False
        for item in migrations:
            path = root / str(item["path"])
            if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
                return False
        versions = root / "backend/app/db/migrations/versions"
        for filename, expected in POST_LEDGER_HISTORICAL_SHA256.items():
            if (
                hashlib.sha256((versions / filename).read_bytes()).hexdigest()
                != expected
            ):
                return False
    except (KeyError, OSError, TypeError, ValueError):
        return False
    return True


def _schema_digest(engine: Engine, tables: tuple[str, ...]) -> str:
    """Private exact schema oracle; the digest never enters evidence."""

    def stable(value: Any) -> Any:
        if isinstance(value, Mapping):
            return tuple(
                sorted((str(key), stable(item)) for key, item in value.items())
            )
        if isinstance(value, (list, tuple)):
            return tuple(stable(item) for item in value)
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        # SQLAlchemy reflected predicates may be TextClause instances whose
        # repr contains a process-local address. Their SQL bytes are stable.
        return " ".join(str(value).split())

    inspector = inspect(engine)
    available = set(inspector.get_table_names())
    snapshot: list[Any] = []
    for table in tables:
        if table not in available:
            snapshot.append((table, "absent"))
            continue
        snapshot.append(
            (
                table,
                tuple(
                    (
                        column["name"],
                        str(column["type"]),
                        bool(column["nullable"]),
                        str(column.get("default")),
                    )
                    for column in inspector.get_columns(table)
                ),
                stable(inspector.get_pk_constraint(table)),
                tuple(
                    sorted(
                        (
                            stable(item)
                            for item in inspector.get_unique_constraints(table)
                        ),
                        key=repr,
                    )
                ),
                tuple(
                    sorted(
                        (stable(item) for item in inspector.get_foreign_keys(table)),
                        key=repr,
                    )
                ),
                tuple(
                    sorted(
                        (
                            stable(item)
                            for item in inspector.get_check_constraints(table)
                        ),
                        key=repr,
                    )
                ),
                tuple(
                    sorted(
                        (stable(item) for item in inspector.get_indexes(table)),
                        key=repr,
                    )
                ),
            )
        )
    return hashlib.sha256(repr(snapshot).encode("utf-8")).hexdigest()


def _row_projection_digest(
    engine: Engine,
    table: str,
    columns: tuple[str, ...],
) -> str:
    """Internal equality oracle; the digest is never included in evidence."""

    selected = ", ".join(f'"{column}"' for column in columns)
    with engine.connect() as connection:
        rows = [
            tuple(row)
            for row in connection.execute(
                text(f'SELECT {selected} FROM "{table}" ORDER BY 1')
            )
        ]
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    return str(revision) if revision is not None else None


def _seed_parent_registration(engine: Engine) -> None:
    """Insert one 0018-valid, no-key registration for row-preservation proof."""

    user_id = uuid.uuid4()
    registration_id = uuid.uuid4()
    user_value: object = user_id.hex if engine.dialect.name == "sqlite" else user_id
    registration_value: object = (
        registration_id.hex if engine.dialect.name == "sqlite" else registration_id
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, role, status) "
                "VALUES (:id, 'student', 'pending')"
            ),
            {"id": user_value},
        )
        connection.execute(
            text(
                "INSERT INTO student_registrations "
                "(id, user_id, first_name, middle_name, last_name, "
                "mobile_hash, mobile_ct, dob_hash, dob_ct, dob_hash_state, "
                "key_version, institution_ref, status, is_minor, "
                "idempotency_key, idempotency_key_legacy) VALUES "
                "(:id, :user_id, 'Synthetic', NULL, 'Lifecycle', "
                ":mobile_hash, '[sealed]', :dob_hash, '[sealed]', 'verified', "
                "'v1', NULL, 'otp_pending', false, NULL, false)"
            ),
            {
                "id": registration_value,
                "user_id": user_value,
                "mobile_hash": hashlib.sha256(
                    registration_id.bytes + b"mobile"
                ).hexdigest(),
                "dob_hash": hashlib.sha256(registration_id.bytes + b"dob").hexdigest(),
            },
        )


def _seed_behavior_legacy_destinations(
    engine: Engine,
    *,
    aged_at: datetime,
    recent_at: datetime,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed two authentic 0018 terminal destinations before 0019 owns them."""

    from app.core.crypto import active_key_version, encrypt

    outbox_ids: list[uuid.UUID] = []
    with engine.begin() as connection:
        for label, outbox_updated_at in (
            ("aged", aged_at),
            ("recent", recent_at),
        ):
            user_id = uuid.uuid4()
            registration_id = uuid.uuid4()
            challenge_id = uuid.uuid4()
            outbox_id = uuid.uuid4()
            outbox_ids.append(outbox_id)
            values = {
                "user_id": _database_uuid(engine, user_id),
                "registration_id": _database_uuid(engine, registration_id),
                "challenge_id": _database_uuid(engine, challenge_id),
                "outbox_id": _database_uuid(engine, outbox_id),
                "mobile_hash": hashlib.sha256(
                    registration_id.bytes + b"behavior-legacy-mobile"
                ).hexdigest(),
                "mobile_ct": encrypt(f"legacy-{label}-mobile"),
                "dob_hash": hashlib.sha256(
                    registration_id.bytes + b"behavior-legacy-dob"
                ).hexdigest(),
                "dob_ct": encrypt(f"legacy-{label}-dob"),
                "key_version": active_key_version(),
                "verifier_hash": hashlib.sha256(
                    challenge_id.bytes + b"behavior-legacy-verifier"
                ).hexdigest(),
                "expires_at": recent_at,
                "consumed_at": recent_at,
                "destination_ct": encrypt(f"legacy-{label}-destination"),
                "delivered_at": recent_at,
                "outbox_created_at": outbox_updated_at,
                "outbox_updated_at": outbox_updated_at,
            }
            connection.execute(
                text(
                    "INSERT INTO users (id, role, status) "
                    "VALUES (:user_id, 'student', 'active')"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO student_registrations "
                    "(id, user_id, first_name, middle_name, last_name, "
                    "mobile_hash, mobile_ct, dob_hash, dob_ct, dob_hash_state, "
                    "key_version, institution_ref, status, is_minor, "
                    "idempotency_key, idempotency_key_legacy) VALUES "
                    "(:registration_id, :user_id, 'Legacy', NULL, 'Fixture', "
                    ":mobile_hash, :mobile_ct, :dob_hash, :dob_ct, 'verified', "
                    ":key_version, NULL, 'active', false, NULL, false)"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO otp_challenges "
                    "(id, registration_id, purpose, verifier_hash, attempts, "
                    "max_attempts, expires_at, consumed_at, locked_until, "
                    "metadata_json) VALUES "
                    "(:challenge_id, :registration_id, 'login', "
                    ":verifier_hash, 0, 3, :expires_at, :consumed_at, NULL, NULL)"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO otp_outbox "
                    "(id, challenge_id, destination_ct, code_ct, key_version, "
                    "purpose, status, attempts, last_error, delivered_at, "
                    "metadata_json, created_at, updated_at) VALUES "
                    "(:outbox_id, :challenge_id, :destination_ct, NULL, "
                    ":key_version, 'login', 'sent', 0, NULL, :delivered_at, "
                    "NULL, :outbox_created_at, :outbox_updated_at)"
                ),
                values,
            )
    return outbox_ids[0], outbox_ids[1]


def _database_uuid(engine: Engine, value: uuid.UUID) -> object:
    return value.hex if engine.dialect.name == "sqlite" else value


def _seed_populated_parent(engine: Engine, *, rows: int = 2) -> dict[str, Any]:
    """Create realistic 0018 rows, including one completed keyed signup.

    The first row deliberately models the dangerous rolling-upgrade case: the
    NYAY-17 ledger says provider delivery succeeded, the registration is still
    ``otp_pending``, and the browser has no post-0019 flow bearer.  The raw
    values returned here stay inside the probe and are never serialized into
    evidence.  A second unrelated row keeps the authority backfill cardinality
    oracle from becoming a one-row special case.
    """

    from datetime import datetime, timedelta, timezone

    from app.core.crypto import active_key_version, encrypt, keyed_hash, otp_verifier
    from app.schemas.registration import StudentRegisterRequest
    from app.services.registration_service import (
        registration_idempotency_key_hash,
        registration_request_fingerprint,
    )

    now = datetime.now(timezone.utc)
    payload = _nyay4_registration_payload("9510006101")
    request = StudentRegisterRequest.model_validate(payload)
    idempotency_key = "nyay4-populated-restart-key-v1"
    signup_code = "610101"
    signup_salt = uuid.uuid4().hex
    signup_registration_id: uuid.UUID | None = None
    with engine.begin() as connection:
        for index in range(rows):
            user_id = uuid.uuid4()
            registration_id = uuid.uuid4()
            challenge_id = uuid.uuid4()
            outbox_id = uuid.uuid4()
            if index == 0:
                signup_registration_id = registration_id
                mobile = payload["mobile"]
                dob = payload["dob"]
                first_name = payload["first_name"]
                last_name = payload["last_name"]
                mobile_hash = keyed_hash(mobile)
                mobile_ct = encrypt(mobile)
                dob_hash = keyed_hash(dob)
                dob_ct = encrypt(dob)
                verifier_hash = otp_verifier(signup_code, salt=signup_salt)
                metadata_json = json.dumps(
                    {"salt": signup_salt, "issued_at": now.isoformat()},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                destination_ct = encrypt(mobile)
                code_ct = None
                outbox_status = "sent"
                delivered_at = now
                purpose = "signup"
            else:
                first_name = "Legacy"
                last_name = "Probe"
                mobile_hash = hashlib.sha256(
                    registration_id.bytes + b"legacy-mobile"
                ).hexdigest()
                mobile_ct = "[sealed]"
                dob_hash = hashlib.sha256(
                    registration_id.bytes + b"legacy-dob"
                ).hexdigest()
                dob_ct = "[sealed]"
                verifier_hash = hashlib.sha256(
                    challenge_id.bytes + b"legacy-verifier"
                ).hexdigest()
                metadata_json = None
                destination_ct = "[sealed]"
                code_ct = "[sealed]"
                outbox_status = "pending"
                delivered_at = None
                purpose = "login"
            values = {
                "user_id": _database_uuid(engine, user_id),
                "registration_id": _database_uuid(engine, registration_id),
                "challenge_id": _database_uuid(engine, challenge_id),
                "outbox_id": _database_uuid(engine, outbox_id),
                "first_name": first_name,
                "last_name": last_name,
                "mobile_hash": mobile_hash,
                "mobile_ct": mobile_ct,
                "dob_hash": dob_hash,
                "dob_ct": dob_ct,
                "key_version": active_key_version(),
                "verifier_hash": verifier_hash,
                "expires_at": now + timedelta(minutes=5 + index),
                "purpose": purpose,
                "metadata_json": metadata_json,
                "destination_ct": destination_ct,
                "code_ct": code_ct,
                "outbox_status": outbox_status,
                "delivered_at": delivered_at,
            }
            connection.execute(
                text(
                    "INSERT INTO users (id, role, status) "
                    "VALUES (:user_id, 'student', 'pending')"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO student_registrations "
                    "(id, user_id, first_name, middle_name, last_name, "
                    "mobile_hash, mobile_ct, dob_hash, dob_ct, dob_hash_state, "
                    "key_version, institution_ref, status, is_minor, "
                    "idempotency_key, idempotency_key_legacy) VALUES "
                    "(:registration_id, :user_id, :first_name, NULL, :last_name, "
                    ":mobile_hash, :mobile_ct, :dob_hash, :dob_ct, 'verified', "
                    ":key_version, NULL, 'otp_pending', false, NULL, false)"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO otp_challenges "
                    "(id, registration_id, purpose, verifier_hash, attempts, "
                    "max_attempts, expires_at, consumed_at, locked_until, "
                    "metadata_json) VALUES "
                    "(:challenge_id, :registration_id, :purpose, "
                    ":verifier_hash, 0, 3, :expires_at, NULL, NULL, "
                    ":metadata_json)"
                ),
                values,
            )
            connection.execute(
                text(
                    "INSERT INTO otp_outbox "
                    "(id, challenge_id, destination_ct, code_ct, key_version, "
                    "purpose, status, attempts, last_error, delivered_at, "
                    "metadata_json) VALUES "
                    "(:outbox_id, :challenge_id, :destination_ct, :code_ct, "
                    ":key_version, :purpose, :outbox_status, 0, NULL, "
                    ":delivered_at, NULL)"
                ),
                values,
            )
            if index == 0:
                connection.execute(
                    text(
                        "INSERT INTO registration_idempotency_records "
                        "(id, idempotency_key_hash, request_fingerprint, "
                        "request_fingerprint_version, state, outcome_code, "
                        "registration_id, outbox_id) VALUES "
                        "(:id, :key_hash, :fingerprint, 'v1', 'succeeded', "
                        "NULL, :registration_id, NULL)"
                    ),
                    {
                        "id": _database_uuid(engine, uuid.uuid4()),
                        "key_hash": registration_idempotency_key_hash(
                            idempotency_key
                        ),
                        "fingerprint": registration_request_fingerprint(request),
                        "registration_id": _database_uuid(engine, registration_id),
                    },
                )
    if signup_registration_id is None:
        raise ProductGateFailure("populated migration restart seed is missing")
    return {
        "payload": payload,
        "idempotency_key": idempotency_key,
        "registration_id": signup_registration_id,
        "issued_at": now,
    }


def _tables_projection_digest(engine: Engine, tables: tuple[str, ...]) -> str:
    inspector = inspect(engine)
    projections = []
    for table in tables:
        columns = tuple(item["name"] for item in inspector.get_columns(table))
        projections.append((table, _row_projection_digest(engine, table, columns)))
    return hashlib.sha256(repr(projections).encode("utf-8")).hexdigest()


def _run_populated_restart_probe(
    engine: Engine, seed: Mapping[str, Any]
) -> dict[str, Any]:
    """Restart and complete one migrated NYAY-17 signup without a minted flow.

    Migration 0019 cannot manufacture an HttpOnly bearer.  Runtime must still
    let the holder of the original exact idempotency key reconstruct a bounded
    signup flow, request a fresh provider-delivered verifier, and complete the
    ceremony.  Otherwise a successfully delivered 0018 registration becomes a
    permanent bootstrap dead-end immediately after upgrade.
    """

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings
    from app.models.registration import (
        RegistrationIdempotencyRecord,
        StudentRegistration,
    )
    from app.services.registration_service import registration_idempotency_key_hash

    provider = _CertifiedGateProvider()
    sender_holder: dict[str, Any] = {"sender": provider}
    app, factory = _build_behavior_app(engine, sender_holder)
    payload = dict(seed["payload"])
    key = str(seed["idempotency_key"])
    registration_id = seed["registration_id"]
    issued_at = seed["issued_at"]
    restart_at = issued_at + timedelta(
        seconds=settings.otp_resend_cooldown_seconds + 1
    )
    original_now = endpoint._now
    endpoint._now = lambda: restart_at
    origin = settings.cors_origins[0]
    restart_status = resend_status = verify_status = 500
    cookie_issued = False
    uuid_exposed = True
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = origin
            restart = client.post(
                "/api/v1/auth/student/register",
                headers={"Idempotency-Key": key},
                json=payload,
            )
            restart_status = restart.status_code
            cookie_issued = bool(
                client.cookies.get(settings.otp_flow_cookie_name)
            )
            restart_body = restart.text.casefold()
            uuid_exposed = bool(
                "registration_id" in restart_body
                or str(registration_id).casefold() in restart_body
                or getattr(registration_id, "hex", "").casefold()
                in restart_body
            )
            if restart.status_code == 201 and cookie_issued:
                resend = client.post(
                    "/api/v1/auth/student/otp/resend",
                    json={},
                )
                resend_status = resend.status_code
                accepted_codes = provider._private_accepted_codes()
                if resend.status_code == 202 and len(accepted_codes) == 1:
                    verify = client.post(
                        "/api/v1/auth/student/otp/verify",
                        json={"code": accepted_codes[0]},
                    )
                    verify_status = verify.status_code
    finally:
        endpoint._now = original_now

    key_hash = registration_idempotency_key_hash(key)
    with factory() as session:
        registration = session.get(StudentRegistration, registration_id)
        ledger = session.scalar(
            select(RegistrationIdempotencyRecord).where(
                RegistrationIdempotencyRecord.idempotency_key_hash == key_hash
            )
        )
        registration_active = bool(
            registration is not None and registration.status == "active"
        )
        ledger_retired = bool(
            ledger is not None
            and ledger.state == "retired"
            and ledger.outcome_code == "registration_replay_expired"
            and ledger.request_fingerprint is None
            and ledger.request_fingerprint_version is None
            and ledger.registration_id is None
            and ledger.outbox_id is None
        )

    # Once activation wins, original and mutated content are deliberately
    # indistinguishable. The tombstone remains a permanent key reservation and
    # neither request may enqueue or deliver another OTP.
    watched = (
        "student_registrations",
        "registration_idempotency_records",
        "otp_flows",
        "otp_challenges",
        "otp_outbox",
    )
    before = _tables_projection_digest(engine, watched)
    calls_before = provider.calls
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers["Origin"] = origin
        exact = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": key},
            json=payload,
        )
        mutated = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": key},
            json=_nyay4_canonical_mutations(payload)[0],
        )
    after = _tables_projection_digest(engine, watched)
    expected_terminal = (409, "registration_replay_expired", "Idempotency-Key")
    return {
        "restart_status": restart_status,
        "restart_cookie_issued": cookie_issued,
        "restart_uuid_exposed": uuid_exposed,
        "resend_status": resend_status,
        "provider_acceptances": provider.acceptance_count,
        "verify_status": verify_status,
        "registration_active": registration_active,
        "ledger_retired": ledger_retired,
        "terminal_replays_uniform": bool(
            _response_error_identity(exact) == expected_terminal
            and _response_error_identity(mutated) == expected_terminal
            and exact.content == mutated.content
        ),
        "terminal_replays_zero_delta": bool(
            before == after and provider.calls == calls_before
        ),
    }


def _run_populated_migration_probe(scratch_url: str) -> dict[str, Any]:
    """Prove legacy authority backfill and fail-closed 0019 downgrade."""

    from datetime import datetime, timezone

    parent = _run_alembic(scratch_url, "upgrade", PREVIOUS_REVISION)
    if parent["returncode"] != 0:
        raise ProductGateFailure("populated probe could not install exact parent")
    engine = create_engine(scratch_url, poolclass=NullPool)
    tables = (
        "student_registrations",
        "otp_challenges",
        "otp_outbox",
        "otp_purpose_authorities",
        "otp_rate_limit_buckets",
        "otp_flows",
    )
    try:
        populated_seed = _seed_populated_parent(engine)
        upgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        if upgrade["returncode"] != 0:
            raise ProductGateFailure("populated probe could not install 0019")
        inspector = inspect(engine)
        with engine.connect() as connection:
            legacy_rows = int(
                connection.scalar(text("SELECT count(*) FROM otp_challenges")) or 0
            )
            authority_rows = int(
                connection.scalar(text("SELECT count(*) FROM otp_purpose_authorities"))
                or 0
            )
            flow_rows = int(
                connection.scalar(text("SELECT count(*) FROM otp_flows")) or 0
            )
            challenge_authority_nonnull = (
                int(
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM otp_challenges "
                            "WHERE authority_id IS NULL"
                        )
                    )
                    or 0
                )
                == 0
            )
            flow_authority_nonnull = (
                int(
                    connection.scalar(
                        text(
                            "SELECT count(*) FROM otp_flows WHERE authority_id IS NULL"
                        )
                    )
                    or 0
                )
                == 0
            )

        sensitive_names = {
            "mobile",
            "mobile_number",
            "raw_mobile",
            "ip",
            "ip_address",
            "raw_ip",
        }
        owned_columns = {
            item["name"]
            for table in EXPECTED_SCHEMA_TABLES[:3]
            for item in inspector.get_columns(table)
        }
        raw_subject_columns = len(
            owned_columns & (sensitive_names - {"ip", "ip_address", "raw_ip"})
        )
        raw_ip_columns = len(owned_columns & {"ip", "ip_address", "raw_ip"})

        restart = _run_populated_restart_probe(engine, populated_seed)

        with engine.connect() as connection:
            registration_value = connection.scalar(
                text("SELECT id FROM student_registrations ORDER BY id LIMIT 1")
            )
        old_writer_challenge_rejected = False
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO otp_challenges "
                        "(id, registration_id, purpose, verifier_hash, attempts, "
                        "max_attempts, expires_at, consumed_at, locked_until, "
                        "metadata_json) VALUES "
                        "(:id, :registration_id, 'signup', :verifier_hash, 0, 3, "
                        ":expires_at, :consumed_at, NULL, NULL)"
                    ),
                    {
                        "id": _database_uuid(engine, uuid.uuid4()),
                        "registration_id": registration_value,
                        "verifier_hash": "0" * 64,
                        "expires_at": datetime.now(timezone.utc),
                        "consumed_at": datetime.now(timezone.utc),
                    },
                )
        except SQLAlchemyError:
            old_writer_challenge_rejected = True

        legacy_destination_writer_rejected = False
        with engine.connect() as connection:
            writable_destination_id = connection.scalar(
                text(
                    "SELECT id FROM otp_outbox "
                    "WHERE legacy_destination_retained=false "
                    "ORDER BY id LIMIT 1"
                )
            )
        if writable_destination_id is not None:
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE otp_outbox "
                            "SET legacy_destination_retained=true WHERE id=:id"
                        ),
                        {"id": writable_destination_id},
                    )
            except SQLAlchemyError:
                legacy_destination_writer_rejected = True

        before_schema = _schema_digest(engine, tables)
        before_rows = _tables_projection_digest(engine, tables)
        refused = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        return {
            "legacy_rows": legacy_rows,
            "authority_rows": authority_rows,
            "flow_rows": flow_rows,
            "challenge_authority_nonnull": challenge_authority_nonnull,
            "flow_authority_nonnull": flow_authority_nonnull,
            "raw_subject_columns": raw_subject_columns,
            "raw_ip_columns": raw_ip_columns,
            "old_writer_challenge_rejected": old_writer_challenge_rejected,
            "legacy_destination_writer_rejected": (legacy_destination_writer_rejected),
            "post_upgrade_restart_status": restart["restart_status"],
            "post_upgrade_restart_cookie_issued": restart[
                "restart_cookie_issued"
            ],
            "post_upgrade_restart_uuid_exposed": restart["restart_uuid_exposed"],
            "post_upgrade_resend_status": restart["resend_status"],
            "post_upgrade_provider_acceptances": restart[
                "provider_acceptances"
            ],
            "post_upgrade_verify_status": restart["verify_status"],
            "post_upgrade_registration_active": restart["registration_active"],
            "post_upgrade_ledger_retired": restart["ledger_retired"],
            "post_upgrade_terminal_replays_uniform": restart[
                "terminal_replays_uniform"
            ],
            "post_upgrade_terminal_replays_zero_delta": restart[
                "terminal_replays_zero_delta"
            ],
            "downgrade_rejected": refused["returncode"] != 0,
            "revision_unchanged": _current_revision(engine) == PINNED_HEAD,
            "schema_unchanged": _schema_digest(engine, tables) == before_schema,
            "rows_unchanged": _tables_projection_digest(engine, tables) == before_rows,
        }
    finally:
        engine.dispose()


def _run_migration_lifecycle_probe(scratch_url: str) -> dict[str, Any]:
    """Exercise clean populated-parent 0018→0019→0018→0019 lifecycle."""

    parent = _run_alembic(scratch_url, "upgrade", PREVIOUS_REVISION)
    if parent["returncode"] != 0:
        raise ProductGateFailure("migration to the exact NYAY-4 parent failed")
    engine = create_engine(scratch_url, poolclass=NullPool)
    changed_tables = (
        "users",
        "student_registrations",
        "otp_challenges",
        "otp_outbox",
        *EXPECTED_SCHEMA_TABLES[:3],
    )
    try:
        inspector = inspect(engine)
        if set(EXPECTED_SCHEMA_TABLES[:3]).intersection(inspector.get_table_names()):
            raise ProductGateFailure("NYAY-4 objects exist below revision 0019")
        _seed_parent_registration(engine)
        registration_columns = tuple(
            item["name"] for item in inspector.get_columns("student_registrations")
        )
        parent_schema = _schema_digest(engine, changed_tables)
        parent_rows = _row_projection_digest(
            engine, "student_registrations", registration_columns
        )

        # Force a late, schema-global index-name collision. 0019 must roll the
        # whole migration back: revision, historical rows, and every earlier
        # DDL operation remain byte-equivalent. The private probe object is
        # removed before the real upgrade and never appears in evidence.
        with engine.begin() as connection:
            connection.execute(
                text("CREATE INDEX ix_otp_flows_authority_id ON users (id)")
            )
        parent_with_collision = _schema_digest(engine, changed_tables)
        failed_upgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        upgrade_failure_atomic = bool(
            failed_upgrade["returncode"] != 0
            and _current_revision(engine) == PREVIOUS_REVISION
            and _schema_digest(engine, changed_tables) == parent_with_collision
            and _row_projection_digest(
                engine, "student_registrations", registration_columns
            )
            == parent_rows
            and not set(EXPECTED_SCHEMA_TABLES[:3]).intersection(
                inspect(engine).get_table_names()
            )
        )
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_otp_flows_authority_id"))
        if not upgrade_failure_atomic:
            raise ProductGateFailure("0019 induced upgrade failure was not atomic")

        upgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        if upgrade["returncode"] != 0:
            raise ProductGateFailure("migration to the exact NYAY-4 head failed")
        head_schema = _schema_digest(engine, changed_tables)
        upgrade_rows_preserved = (
            _row_projection_digest(
                engine, "student_registrations", registration_columns
            )
            == parent_rows
        )
        check = _run_alembic(scratch_url, "check")

        import importlib

        historical_parent = importlib.import_module(
            "app.db.migrations.versions.0018_registration_idempotency"
        )
        downgrade = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        parent_validator_after_downgrade = False
        if downgrade["returncode"] == 0:
            try:
                with engine.connect() as connection:
                    historical_parent._validate_head_schema(connection)
            except Exception:
                parent_validator_after_downgrade = False
            else:
                parent_validator_after_downgrade = True
        downgrade_exact = bool(
            downgrade["returncode"] == 0
            and _current_revision(engine) == PREVIOUS_REVISION
            and _schema_digest(engine, changed_tables) == parent_schema
            and parent_validator_after_downgrade
            and _row_projection_digest(
                engine, "student_registrations", registration_columns
            )
            == parent_rows
        )
        reupgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        reupgrade_exact = bool(
            reupgrade["returncode"] == 0
            and _current_revision(engine) == PINNED_HEAD
            and _schema_digest(engine, changed_tables) == head_schema
            and _row_projection_digest(
                engine, "student_registrations", registration_columns
            )
            == parent_rows
        )

        # A dependent view makes the final challenge-column removal fail after
        # earlier downgrade operations have started. PostgreSQL transactional
        # DDL and SQLite's explicit BEGIN IMMEDIATE must restore the full head.
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE VIEW nyay4_atomic_downgrade_probe AS "
                    "SELECT authority_id FROM otp_challenges"
                )
            )
        head_before_failed_downgrade = _schema_digest(engine, changed_tables)
        rows_before_failed_downgrade = _row_projection_digest(
            engine, "student_registrations", registration_columns
        )
        failed_downgrade = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        downgrade_failure_atomic = bool(
            failed_downgrade["returncode"] != 0
            and _current_revision(engine) == PINNED_HEAD
            and _schema_digest(engine, changed_tables) == head_before_failed_downgrade
            and _row_projection_digest(
                engine, "student_registrations", registration_columns
            )
            == rows_before_failed_downgrade
            and "nyay4_atomic_downgrade_probe" in inspect(engine).get_view_names()
        )
        with engine.begin() as connection:
            connection.execute(text("DROP VIEW nyay4_atomic_downgrade_probe"))
        if not downgrade_failure_atomic:
            raise ProductGateFailure("0019 induced downgrade failure was not atomic")
        retry_down = _run_alembic(scratch_url, "downgrade", PREVIOUS_REVISION)
        parent_validator_after_retry = False
        if retry_down["returncode"] == 0:
            try:
                with engine.connect() as connection:
                    historical_parent._validate_head_schema(connection)
            except Exception:
                parent_validator_after_retry = False
            else:
                parent_validator_after_retry = True
        retry_up = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        retry_after_induced_failure = bool(
            retry_down["returncode"] == 0
            and parent_validator_after_retry
            and retry_up["returncode"] == 0
            and _current_revision(engine) == PINNED_HEAD
            and _schema_digest(engine, changed_tables) == head_schema
            and _row_projection_digest(
                engine, "student_registrations", registration_columns
            )
            == parent_rows
        )

        # Exercise the real multi-revision path used by historical lifecycle
        # gates. A downgrade that merely writes version 0018 while leaving a
        # near-miss CHECK can pass a local digest yet make 0018 refuse its own
        # subsequent downgrade. Require the immutable 0017 validator too, then
        # prove a byte-equivalent return to 0019.
        older_revision = "0017_registration_invariants"
        multi_down = _run_alembic(scratch_url, "downgrade", older_revision)
        older_validator_exact = False
        if multi_down["returncode"] == 0:
            historical_older = importlib.import_module(
                "app.db.migrations.versions.0017_registration_invariants"
            )
            try:
                with engine.connect() as connection:
                    historical_older._validate_head_schema(connection)
            except Exception:
                older_validator_exact = False
            else:
                older_validator_exact = True
        multi_up = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        multi_step_downgrade_reupgrade = bool(
            multi_down["returncode"] == 0
            and older_validator_exact
            and multi_up["returncode"] == 0
            and _current_revision(engine) == PINNED_HEAD
            and _schema_digest(engine, changed_tables) == head_schema
            and _row_projection_digest(
                engine, "student_registrations", registration_columns
            )
            == parent_rows
        )

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "app/db/migrations"))
        heads = ScriptDirectory.from_config(config).get_heads()
        return {
            "start_revision": PREVIOUS_REVISION,
            "head_revision": _current_revision(engine),
            "single_head": heads == [PINNED_HEAD],
            "upgrade": bool(upgrade["returncode"] == 0 and upgrade_rows_preserved),
            "downgrade": downgrade_exact,
            "reupgrade": reupgrade_exact,
            "alembic_check": check["returncode"] == 0,
            "historical_digest_unchanged": (_historical_migration_bytes_unchanged()),
            "row_projection_unchanged": bool(
                upgrade_rows_preserved and downgrade_exact and reupgrade_exact
            ),
            "parent_validator_exact": bool(
                parent_validator_after_downgrade
                and parent_validator_after_retry
            ),
            "multi_step_downgrade_reupgrade": (
                multi_step_downgrade_reupgrade
            ),
            "upgrade_failure_atomic": upgrade_failure_atomic,
            "downgrade_failure_atomic": downgrade_failure_atomic,
            "retry_after_induced_failure": retry_after_induced_failure,
        }
    finally:
        engine.dispose()


def _runtime_probe(base: URL) -> dict[str, Any]:
    engine = create_engine(_database_url(base, "postgres"), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            version_num = int(connection.scalar(text("SHOW server_version_num")))
            vector = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
    except Exception as exc:
        raise Blocked("could not verify PostgreSQL 16 plus pgvector") from exc
    finally:
        engine.dispose()
    return {
        "postgres_major": version_num // 10000,
        "pgvector_present": bool(vector),
        "loopback": True,
        "query_free": True,
        "ambient_rejected": True,
    }


def _require_core_contract() -> None:
    """Fail closed until the exact 0019 core/model/service seams are importable."""

    try:
        if not _behavior_fixture_mobile_inventory_is_unique():
            raise ProductGateFailure("NYAY-4 behavior fixture inventory is unsafe")
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "app/db/migrations"))
        scripts = ScriptDirectory.from_config(config)
        if scripts.get_heads() != [PINNED_HEAD]:
            raise ProductGateFailure("NYAY-4 exact Alembic head is unavailable")
        for table in EXPECTED_SCHEMA_TABLES:
            if table not in _expected_metadata_tables():
                raise ProductGateFailure("NYAY-4 exact model inventory is unavailable")
    except ProductGateFailure:
        raise
    except Exception as exc:
        raise ProductGateFailure("NYAY-4 core contract is unavailable") from exc


def _expected_metadata_tables() -> set[str]:
    import app.models  # noqa: F401
    from app.db.base import Base

    return set(Base.metadata.tables)


def _normalise_reflected_any_array_sql(value: object, historical: Any) -> object:
    """Translate PostgreSQL's literal-only ``= ANY(ARRAY[..])`` to ``IN``.

    PostgreSQL reflects a declared ``IN`` predicate as an ``= ANY`` tree with
    redundant grouping and varchar/text casts. The immutable 0018 parser can
    represent the target ``IN`` semantics, but its recursive ``ANY`` shortcut
    stops before one of PostgreSQL's outer grouping tokens. Keep the immutable
    parser untouched and admit only the exact equivalent reflected shape here:
    one non-empty ARRAY argument containing string literals and commas only.
    """

    protected, literals_by_token = historical._protect_sql_literals(value)
    if not re.search(r"\bany\s*\(", protected, flags=re.IGNORECASE):
        return value
    if re.search(
        r"::(?:character varying|varchar)\s*\(",
        protected,
        flags=re.IGNORECASE,
    ):
        raise ValueError("unsupported reflected ANY/ARRAY syntax")
    if re.search(r"\ball\s*\(", protected, flags=re.IGNORECASE):
        raise ValueError("unsupported reflected ANY/ARRAY syntax")
    text_value = protected.casefold().replace('"', "")
    text_value = re.sub(
        r"::(?:text|character varying|varchar)(?:\[\])?",
        "",
        text_value,
    )
    text_value = text_value.replace("[", "(").replace("]", ")")
    literals: dict[str, str] = {}
    for index, (placeholder, literal) in enumerate(literals_by_token.items()):
        token = f"__literal{index}__"
        text_value = text_value.replace(placeholder, token)
        literals[token] = literal
    tokens = historical._TOKEN.findall(text_value)
    if "".join(tokens) != re.sub(r"\s+", "", text_value):
        raise ValueError("unsupported reflected ANY/ARRAY syntax")

    output: list[str] = []
    index = 0
    replacements = 0
    while index < len(tokens):
        if tokens[index] == "any":
            raise ValueError("unsupported reflected ANY/ARRAY syntax")
        if not (
            tokens[index] == "="
            and index + 1 < len(tokens)
            and tokens[index + 1] == "any"
        ):
            output.append(tokens[index])
            index += 1
            continue

        cursor = index + 2
        if cursor >= len(tokens) or tokens[cursor] != "(":
            raise ValueError("unsupported reflected ANY/ARRAY syntax")
        cursor += 1
        redundant_groups = 0
        while cursor < len(tokens) and tokens[cursor] == "(":
            redundant_groups += 1
            cursor += 1
        if (
            cursor + 2 >= len(tokens)
            or tokens[cursor] != "array"
            or tokens[cursor + 1] != "("
        ):
            raise ValueError("unsupported reflected ANY/ARRAY syntax")
        cursor += 2

        array_tokens: list[str] = []
        if cursor >= len(tokens) or not tokens[cursor].startswith("__literal"):
            raise ValueError("unsupported reflected ANY/ARRAY syntax")
        while True:
            if not tokens[cursor].startswith("__literal"):
                raise ValueError("unsupported reflected ANY/ARRAY syntax")
            array_tokens.append(tokens[cursor])
            cursor += 1
            if cursor >= len(tokens):
                raise ValueError("unsupported reflected ANY/ARRAY syntax")
            if tokens[cursor] == ")":
                cursor += 1
                break
            if tokens[cursor] != "," or cursor + 1 >= len(tokens):
                raise ValueError("unsupported reflected ANY/ARRAY syntax")
            array_tokens.append(",")
            cursor += 1

        for _group in range(redundant_groups):
            if cursor >= len(tokens) or tokens[cursor] != ")":
                raise ValueError("unsupported reflected ANY/ARRAY syntax")
            cursor += 1
        if cursor >= len(tokens) or tokens[cursor] != ")":
            raise ValueError("unsupported reflected ANY/ARRAY syntax")
        cursor += 1
        output.extend(("in", "(", *array_tokens, ")"))
        index = cursor
        replacements += 1

    if replacements == 0:
        raise ValueError("unsupported reflected ANY/ARRAY syntax")
    normalized = " ".join(output)
    for token, literal in literals.items():
        normalized = normalized.replace(token, literal)
    return normalized


def _canonical_check_sql(value: object) -> object:
    # 0018 is byte-pinned above and supplies a quote-aware parser that handles
    # PostgreSQL's reflected `= ANY(ARRAY[..])` representation without erasing
    # grouping or literal boundaries. 0019 itself is never trusted as oracle.
    import importlib

    historical = importlib.import_module(
        "app.db.migrations.versions.0018_registration_idempotency"
    )
    protected, literals = historical._protect_sql_literals(value)
    # The immutable 0018 grammar did not need bare < or >. 0019 has only
    # simple identifier/number comparisons, so encode those as explicit
    # functions before invoking the quote-aware parser. Literals stay opaque.
    protected = re.sub(
        r"\b([a-z_][a-z0-9_]*)\s*>\s*([a-z_][a-z0-9_]*|[0-9]+)\b",
        r"greater_than(\1,\2)",
        protected,
        flags=re.IGNORECASE,
    )
    protected = re.sub(
        r"\b([a-z_][a-z0-9_]*)\s*<\s*([a-z_][a-z0-9_]*|[0-9]+)\b",
        r"less_than(\1,\2)",
        protected,
        flags=re.IGNORECASE,
    )
    for token, literal in literals.items():
        protected = protected.replace(token, literal)
    protected = _normalise_reflected_any_array_sql(protected, historical)
    return historical._canonical_check(protected)


def _canonical_default(value: object, *, expected_kind: str) -> str | None:
    if value is None:
        return None
    source = str(value).strip().casefold()
    source = re.sub(
        r"::(?:text|character varying|varchar|boolean|integer|bigint)"
        r"(?:\([0-9]+\))?",
        "",
        source,
    ).strip()
    while source.startswith("(") and source.endswith(")"):
        source = source[1:-1].strip()
    if source in {"current_timestamp", "current_timestamp()", "now()"}:
        return "now"
    if len(source) >= 2 and source[0] == source[-1] == "'":
        source = source[1:-1]
    if expected_kind == "boolean" and source in {"0", "false"}:
        return "false"
    return source


def _column_type_contract(
    column: Mapping[str, Any], *, dialect_name: str
) -> tuple[str, int | None] | None:
    column_type = column.get("type")
    rendered = str(column_type).casefold()
    class_name = type(column_type).__name__.casefold()
    if "uuid" in class_name or rendered == "uuid":
        return ("uuid", None)
    if dialect_name == "sqlite" and rendered == "char(32)":
        return ("uuid", None)
    if "varchar" in rendered or "string" in class_name:
        return ("varchar", getattr(column_type, "length", None))
    if "int" in rendered or "integer" in class_name:
        return ("integer", None)
    if "bool" in rendered or "boolean" in class_name:
        return ("boolean", None)
    if "json" in rendered or "json" in class_name:
        return ("json", None)
    if "timestamp" in rendered or "datetime" in rendered:
        if dialect_name == "postgresql" and not bool(
            getattr(column_type, "timezone", False)
        ):
            return None
        return ("timestamp", None)
    return None


def _columns_are_exact(inspector: Any, dialect_name: str) -> bool:
    for table, expected in EXPECTED_0019_COLUMNS.items():
        actual = inspector.get_columns(table)
        if [item.get("name") for item in actual] != [item[0] for item in expected]:
            return False
        for column, (_, kind, length, nullable, default) in zip(actual, expected):
            if _column_type_contract(column, dialect_name=dialect_name) != (
                kind,
                length,
            ):
                return False
            if bool(column.get("nullable")) is not nullable:
                return False
            if _canonical_default(column.get("default"), expected_kind=kind) != default:
                return False
    return True


def _primary_keys_are_exact(inspector: Any) -> bool:
    return all(
        (
            item.get("name"),
            tuple(item.get("constrained_columns") or ()),
        )
        == EXPECTED_0019_PRIMARY_KEYS[table]
        for table in EXPECTED_SCHEMA_TABLES
        for item in (inspector.get_pk_constraint(table),)
    )


def _unique_constraints_are_exact(inspector: Any) -> bool:
    for table, expected in EXPECTED_0019_UNIQUES.items():
        raw = inspector.get_unique_constraints(table)
        actual = {
            (str(item.get("name")), tuple(item.get("column_names") or ()))
            for item in raw
            if item.get("name")
        }
        if len(raw) != len(expected) or actual != expected:
            return False
    return True


def _foreign_keys_are_exact(inspector: Any) -> bool:
    for table, expected in EXPECTED_0019_FOREIGN_KEYS.items():
        raw = inspector.get_foreign_keys(table)
        actual = set()
        for item in raw:
            if not item.get("name") or item.get("referred_schema") not in {
                None,
                "public",
            }:
                return False
            options = {
                str(key).casefold(): str(value).upper()
                for key, value in (item.get("options") or {}).items()
                if value is not None
            }
            if set(options) - {"ondelete"}:
                return False
            actual.add(
                (
                    str(item["name"]),
                    tuple(item.get("constrained_columns") or ()),
                    str(item.get("referred_table")),
                    tuple(item.get("referred_columns") or ()),
                    options.get("ondelete", ""),
                )
            )
        if len(raw) != len(expected) or actual != expected:
            return False
    return True


def _postgresql_check_constraint_sql(
    engine: Engine,
) -> dict[tuple[str, str], object] | None:
    """Read balanced PostgreSQL CHECK expressions from the owning catalog.

    SQLAlchemy's PostgreSQL Inspector strips an outer parenthesis pair with a
    non-balance-aware regular expression. For root-OR CHECKs, the first and
    last parentheses can belong to different branches, producing invalid SQL.
    Inspector remains authoritative for exact object names/cardinality; only
    the expression bytes come from PostgreSQL's own balanced deparser.
    """

    statement = text(
        "SELECT cls.relname, con.conname, "
        "pg_get_expr(con.conbin, con.conrelid, false) "
        "FROM pg_constraint AS con "
        "JOIN pg_class AS cls ON cls.oid = con.conrelid "
        "JOIN pg_namespace AS ns ON ns.oid = cls.relnamespace "
        "WHERE con.contype = 'c' "
        "AND ns.nspname = current_schema() "
        "AND cls.relname IN :table_names "
        "ORDER BY cls.relname, con.conname"
    ).bindparams(bindparam("table_names", expanding=True))
    try:
        with engine.connect() as connection:
            rows = list(
                connection.execute(
                    statement,
                    {"table_names": tuple(EXPECTED_0019_CHECKS)},
                )
            )
    except SQLAlchemyError:
        return None
    output: dict[tuple[str, str], object] = {}
    for table, name, sqltext in rows:
        key = (str(table), str(name))
        if key in output or sqltext is None:
            return None
        output[key] = sqltext
    return output


def _check_constraints_are_exact(
    inspector: Any, engine: Engine
) -> tuple[bool, dict[str, bool]]:
    exact_by_name: dict[str, bool] = {}
    catalog_sql: dict[tuple[str, str], object] | None = None
    if engine.dialect.name == "postgresql":
        catalog_sql = _postgresql_check_constraint_sql(engine)
        expected_keys = {
            (table, name)
            for table, names in EXPECTED_0019_CHECKS.items()
            for name in names
        }
        if catalog_sql is None or set(catalog_sql) != expected_keys:
            return False, exact_by_name
    for table, expected_names in EXPECTED_0019_CHECKS.items():
        raw = inspector.get_check_constraints(table)
        if any(item.get("dialect_options") for item in raw):
            return False, exact_by_name
        actual_names = {str(item.get("name")) for item in raw if item.get("name")}
        if len(raw) != len(expected_names) or actual_names != expected_names:
            return False, exact_by_name
        for item in raw:
            name = str(item["name"])
            try:
                actual_sql = (
                    catalog_sql[(table, name)]
                    if catalog_sql is not None
                    else item.get("sqltext")
                )
                exact_by_name[name] = _canonical_check_sql(
                    actual_sql
                ) == _canonical_check_sql(EXPECTED_0019_CHECK_SQL[name])
            except (KeyError, TypeError, ValueError):
                exact_by_name[name] = False
    return all(exact_by_name.values()), exact_by_name


def _index_predicate(item: Mapping[str, Any], dialect_name: str) -> object | None:
    options = item.get("dialect_options") or {}
    value = options.get(f"{dialect_name}_where")
    if value is None:
        return None
    return _canonical_check_sql(value)


def _indexes_are_exact(inspector: Any, dialect_name: str) -> bool:
    for table, expected in EXPECTED_0019_INDEXES.items():
        raw = [
            item
            for item in inspector.get_indexes(table)
            if not item.get("duplicates_constraint")
        ]
        expected_canonical = {
            (
                name,
                columns,
                unique,
                _canonical_check_sql(predicate) if predicate is not None else None,
            )
            for name, columns, unique, predicate in expected
        }
        try:
            actual = {
                (
                    str(item.get("name")),
                    tuple(item.get("column_names") or ()),
                    bool(item.get("unique")),
                    _index_predicate(item, dialect_name),
                )
                for item in raw
            }
        except (TypeError, ValueError):
            return False
        if len(raw) != len(expected) or actual != expected_canonical:
            return False
    return True


def _legacy_destination_trigger_is_exact(engine: Engine) -> bool:
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "postgresql":
                rows = list(
                    connection.execute(
                        text(
                            "SELECT t.tgname, pg_get_triggerdef(t.oid), "
                            "pg_get_functiondef(t.tgfoid) FROM pg_trigger t "
                            "WHERE t.tgrelid='otp_outbox'::regclass "
                            "AND NOT t.tgisinternal AND t.tgname LIKE "
                            "'trg_otp_outbox_no_new_legacy_destination%'"
                        )
                    )
                )
                if len(rows) != 1 or rows[0][0] != (
                    "trg_otp_outbox_no_new_legacy_destination"
                ):
                    return False
                combined = " ".join(str(value).casefold() for value in rows[0][1:])
                return all(
                    term in combined
                    for term in (
                        "before insert or update of legacy_destination_retained",
                        "new.legacy_destination_retained = true",
                        "old.legacy_destination_retained = false",
                        "23514",
                    )
                )
            rows = list(
                connection.execute(
                    text(
                        "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
                        "AND tbl_name='otp_outbox' AND name LIKE "
                        "'trg_otp_outbox_no_new_legacy_destination%' "
                        "ORDER BY name"
                    )
                )
            )
        if [row[0] for row in rows] != [
            "trg_otp_outbox_no_new_legacy_destination_insert",
            "trg_otp_outbox_no_new_legacy_destination_update",
        ]:
            return False
        definitions = " ".join(str(row[1]).casefold() for row in rows)
        return all(
            term in definitions
            for term in (
                "new.legacy_destination_retained = 1",
                "old.legacy_destination_retained = 0",
                "raise(abort, 'new legacy otp destinations are forbidden')",
            )
        )
    except SQLAlchemyError:
        return False


def _exact_schema_observation(engine: Engine) -> dict[str, Any]:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    otp_tables = {name for name in table_names if name.startswith("otp_")}
    checks_exact, checks = _check_constraints_are_exact(inspector, engine)
    columns = {
        item["name"]
        for table in EXPECTED_SCHEMA_TABLES
        for item in inspector.get_columns(table)
    }
    sensitive = {
        "mobile",
        "mobile_number",
        "raw_mobile",
        "ip",
        "ip_address",
        "raw_ip",
        "otp",
        "code",
        "provider_token",
        "claim_token",
    }
    provider_checks = {
        "ck_otp_outbox_provider_idempotency_key_shape",
        "ck_otp_outbox_provider_receipt_shape",
        "ck_otp_outbox_provider_receipt_hash_shape",
    }
    claim_checks = {
        "ck_otp_outbox_status",
        "ck_otp_outbox_claim_shape",
        "ck_otp_outbox_claim_token_hash_shape",
        "ck_otp_outbox_retry_shape",
        "ck_otp_outbox_payload_shape",
    }
    return {
        "exact_tables": otp_tables == set(EXPECTED_OTP_TABLES),
        "exact_columns": _columns_are_exact(inspector, engine.dialect.name),
        "exact_primary_keys": _primary_keys_are_exact(inspector),
        "exact_unique_constraints": _unique_constraints_are_exact(inspector),
        "exact_foreign_keys": _foreign_keys_are_exact(inspector),
        "exact_check_constraints": checks_exact,
        "exact_indexes": _indexes_are_exact(inspector, engine.dialect.name),
        "challenge_authority_nonnull": not bool(
            next(
                item
                for item in inspector.get_columns("otp_challenges")
                if item["name"] == "authority_id"
            )["nullable"]
        ),
        "flow_authority_nonnull": not bool(
            next(
                item
                for item in inspector.get_columns("otp_flows")
                if item["name"] == "authority_id"
            )["nullable"]
        ),
        "provider_key_shape": all(checks.get(name) is True for name in provider_checks),
        "claim_state_shape": bool(
            all(checks.get(name) is True for name in claim_checks)
            and _legacy_destination_trigger_is_exact(engine)
        ),
        "neutralized_ledger_shape": all(
            checks.get(name) is True
            for name in EXPECTED_0019_CHECKS[
                "registration_idempotency_records"
            ]
        ),
        "raw_sensitive_columns": len(columns & sensitive),
    }


def _run_exact_schema_probe(scratch_url: str) -> dict[str, Any]:
    upgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
    if upgrade["returncode"] != 0:
        raise ProductGateFailure("exact 0019 schema probe migration failed")
    engine = create_engine(scratch_url, poolclass=NullPool)
    try:
        return _exact_schema_observation(engine)
    finally:
        engine.dispose()


def _run_configuration_probe() -> dict[str, Any]:
    """Exercise the real boot validator without retaining configured values."""

    from pydantic import SecretStr

    from app.core.config import ConfigurationError, settings
    from app.services.otp_sender import HttpOtpSender, IdempotentOtpSender

    private_token = "nyay4-private-provider-token-sentinel"
    private_url = "https://otp-provider.example.invalid/send"
    valid = {
        "app_env": "production",
        "otp_delivery_enabled": True,
        "otp_provider": "http",
        "otp_provider_url": private_url,
        "otp_provider_token": SecretStr(private_token),
        "otp_provider_supports_idempotency": True,
        "otp_provider_timeout_s": 1.0,
    }

    def rejected(update: Mapping[str, Any]) -> tuple[bool, bool]:
        candidate = settings.model_copy(update={**valid, **update}, deep=True)
        private_values = [private_token, private_url]
        for field in ("otp_provider_url", "otp_provider_token"):
            value = update.get(field)
            if isinstance(value, SecretStr):
                value = value.get_secret_value()
            if isinstance(value, str) and value:
                private_values.append(value)
        try:
            candidate.validate_otp_configuration()
        except ConfigurationError as exc:
            message = str(exc)
            return True, all(value not in message for value in private_values)
        return False, False

    cases: dict[str, Mapping[str, Any]] = {
        "delivery_disabled_production": {"otp_delivery_enabled": False},
        "provider_none": {"otp_provider": "none"},
        "provider_capturing": {"otp_provider": "capturing"},
        "provider_unknown": {"otp_provider": "unknown"},
        "provider_insecure_url": {
            "otp_provider_url": "http://otp-provider.example.invalid/send"
        },
        "provider_ambiguous_url": {"otp_provider_url": private_url + "?token=private"},
        "provider_invalid_textual_port": {
            "otp_provider_url": "https://otp-provider.example.invalid:notaport/send"
        },
        "provider_out_of_range_port": {
            "otp_provider_url": "https://otp-provider.example.invalid:70000/send"
        },
        "provider_url_whitespace": {"otp_provider_url": f" {private_url} "},
        "provider_missing_url": {"otp_provider_url": None},
        "provider_missing_token": {"otp_provider_token": None},
        "provider_missing_idempotency": {"otp_provider_supports_idempotency": False},
        "provider_timeout_zero": {"otp_provider_timeout_s": 0.0},
        "provider_timeout_bool": {"otp_provider_timeout_s": True},
        "provider_timeout_nonfinite": {"otp_provider_timeout_s": float("nan")},
        "retry_max_below_base": {
            "otp_outbox_retry_base_seconds": 10,
            "otp_outbox_retry_max_seconds": 9,
        },
        **{f"nonpositive:{field}": {field: 0} for field in OTP_POSITIVE_INTEGER_FIELDS},
    }
    outcomes = {name: rejected(update) for name, update in cases.items()}
    valid_candidate = settings.model_copy(update=valid, deep=True)
    valid_real_provider_booted = True
    try:
        valid_candidate.validate_otp_configuration()
    except ConfigurationError:
        valid_real_provider_booted = False
    provider_contract_certified = isinstance(
        HttpOtpSender(private_url, private_token, 1.0), IdempotentOtpSender
    )
    return {
        "cases": sorted(outcomes),
        "all_rejected": all(item[0] for item in outcomes.values()),
        "production_booted": any(not item[0] for item in outcomes.values()),
        "valid_real_provider_booted": valid_real_provider_booted,
        "provider_contract_certified": provider_contract_certified,
        "errors_sanitized": all(item[1] for item in outcomes.values()),
    }


def _build_behavior_app(
    engine: Engine,
    sender_holder: Mapping[str, Any],
) -> tuple[FastAPI, sessionmaker[Session]]:
    """Bind the real OTP router to one isolated behavior database."""

    from app.api.v1 import auth_student as endpoint
    from app.core.exceptions import register_exception_handlers
    from app.db.session import get_session

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )

    def request_session():
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

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(endpoint.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = request_session
    app.dependency_overrides[endpoint.get_otp_sender] = lambda: sender_holder[
        "sender"
    ]
    app.dependency_overrides[endpoint.get_outbox_session_factory] = lambda: factory
    return app, factory


def _seed_active_registration(
    factory: sessionmaker[Session],
    mobile: str,
) -> None:
    """Create a minimal authorizable account without staging an OTP graph."""

    from app.core.crypto import active_key_version, encrypt, keyed_hash
    from app.models.registration import StudentRegistration, User

    with factory() as session:
        user = User(role="student", status="active")
        session.add(user)
        session.flush()
        session.add(
            StudentRegistration(
                user_id=user.id,
                first_name="Gate",
                middle_name=None,
                last_name="Subject",
                mobile_hash=keyed_hash(mobile),
                mobile_ct=encrypt(mobile),
                dob_hash=keyed_hash(f"nyay4-gate-dob:{mobile}"),
                dob_ct=encrypt("2000-01-01"),
                dob_hash_state="verified",
                key_version=active_key_version(),
                institution_ref=None,
                status="active",
                is_minor=False,
                idempotency_key=None,
                idempotency_key_legacy=False,
            )
        )
        session.commit()


def _flow_private_inventory(
    factory: sessionmaker[Session], raw_token: str
) -> dict[str, Any]:
    """Return private graph state; callers expose only comparisons/counts."""

    from app.models.registration import OtpChallenge, OtpFlow, OtpOutbox
    from app.services.otp_flow_service import flow_token_hash

    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(OtpFlow.token_hash == flow_token_hash(raw_token))
        )
        if flow is None:
            raise ProductGateFailure("OTP behavior flow graph disappeared")
        active = int(
            session.scalar(
                select(func.count(OtpChallenge.id)).where(
                    OtpChallenge.authority_id == flow.authority_id,
                    OtpChallenge.delivery_state == "active",
                )
            )
            or 0
        )
        delivered = int(
            session.scalar(
                select(func.count(OtpOutbox.id))
                .join(OtpChallenge, OtpOutbox.challenge_id == OtpChallenge.id)
                .where(
                    OtpChallenge.authority_id == flow.authority_id,
                    OtpOutbox.status == "sent",
                )
            )
            or 0
        )
        payload_rows = int(
            session.scalar(
                select(func.count(OtpOutbox.id))
                .join(OtpChallenge, OtpOutbox.challenge_id == OtpChallenge.id)
                .where(
                    OtpChallenge.authority_id == flow.authority_id,
                    (OtpOutbox.code_ct.is_not(None))
                    | (OtpOutbox.destination_ct.is_not(None)),
                )
            )
            or 0
        )
        return {
            "authority": flow.authority_id,
            "challenge": flow.challenge_id,
            "has_registration": flow.registration_id is not None,
            "state": flow.state,
            "active": active,
            "delivered": delivered,
            "payload_rows": payload_rows,
        }


def _run_initial_exhaustion_probe(engine: Engine) -> dict[str, Any]:
    """Prove initial relay exhaustion remains non-enumerating and recoverable.

    This deliberately tests both login and recovery. A real candidate whose
    first provider attempt exhausts must project exactly like the matching
    decoy for the entire public flow lifetime. A later explicit resend must
    reuse the same stable authority, erase the failed payload, and create one
    provider acceptance/one delivered replacement only.
    """

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings

    original_now = endpoint._now
    original_max_attempts = settings.otp_outbox_max_attempts
    original_cooldown = settings.otp_resend_cooldown_seconds
    # Keep provider callbacks on the same wall-clock epoch. The route clock is
    # still explicitly advanced for projection checks below, but the relay
    # intentionally obtains its own authoritative UTC timestamp.
    fixed = datetime.now(timezone.utc)
    clock = {"now": fixed}
    endpoint._now = lambda: clock["now"]
    settings.otp_outbox_max_attempts = 1
    settings.otp_resend_cooldown_seconds = 2
    sender_holder: dict[str, Any] = {"sender": _CertifiedGateProvider()}
    app, factory = _build_behavior_app(engine, sender_holder)
    origin = settings.cors_origins[0]
    cases = (
        (
            "login",
            "/api/v1/auth/student/login/otp/start",
            _behavior_fixture_mobile("initial_login_known"),
            _behavior_fixture_mobile("initial_login_decoy"),
        ),
        (
            "recovery",
            "/api/v1/auth/student/recovery/start",
            _behavior_fixture_mobile("initial_recovery_known"),
            _behavior_fixture_mobile("initial_recovery_decoy"),
        ),
    )
    shapes_equal: list[bool] = []
    values_equal: list[bool] = []
    ttl_symmetric: list[bool] = []
    fully_expired_unavailable: list[bool] = []
    same_authority: list[bool] = []
    recovered: list[bool] = []
    no_stale_payload: list[bool] = []
    exactly_one_acceptance: list[bool] = []
    exactly_one_delivered: list[bool] = []
    try:
        for purpose, start_path, known_mobile, decoy_mobile in cases:
            _seed_active_registration(factory, known_mobile)
            failing = _CertifiedGateProvider(fail_before_accept_count=1)
            sender_holder["sender"] = failing
            with TestClient(app, raise_server_exceptions=False) as known_client:
                known_client.headers["Origin"] = origin
                known_start = known_client.post(
                    start_path, json={"mobile": known_mobile}
                )
                known_token = known_client.cookies.get(
                    settings.otp_flow_cookie_name
                )
                if known_start.status_code != 202 or not known_token:
                    raise ProductGateFailure(
                        "initial-exhaustion known start contract failed"
                    )
                before = _flow_private_inventory(factory, known_token)

                sender_holder["sender"] = _CertifiedGateProvider()
                with TestClient(app, raise_server_exceptions=False) as decoy_client:
                    decoy_client.headers["Origin"] = origin
                    decoy_start = decoy_client.post(
                        start_path, json={"mobile": decoy_mobile}
                    )
                    decoy_token = decoy_client.cookies.get(
                        settings.otp_flow_cookie_name
                    )
                    if decoy_start.status_code != 202 or not decoy_token:
                        raise ProductGateFailure(
                            "initial-exhaustion decoy start contract failed"
                        )
                    shapes_equal.append(
                        set(known_start.json()) == set(decoy_start.json())
                    )
                    values_equal.append(known_start.json() == decoy_start.json())
                    checkpoints_equal = []
                    final_known_state: Mapping[str, Any] | None = None
                    final_decoy_state: Mapping[str, Any] | None = None
                    for offset in (
                        1,
                        settings.otp_challenge_ttl_seconds + 1,
                        settings.otp_flow_ttl_seconds - 1,
                        settings.otp_flow_ttl_seconds,
                    ):
                        clock["now"] = fixed + timedelta(seconds=offset)
                        known_state = known_client.get(
                            "/api/v1/auth/student/otp/state"
                        )
                        decoy_state = decoy_client.get(
                            "/api/v1/auth/student/otp/state"
                        )
                        checkpoints_equal.append(
                            known_state.status_code == decoy_state.status_code == 200
                            and known_state.json() == decoy_state.json()
                        )
                        if offset == settings.otp_flow_ttl_seconds:
                            final_known_state = known_state.json()
                            final_decoy_state = decoy_state.json()
                    ttl_symmetric.append(all(checkpoints_equal))
                    fully_expired_unavailable.append(
                        final_known_state == final_decoy_state
                        and final_known_state is not None
                        and final_known_state.get("status") == "unavailable"
                    )

                # Recover before the common flow TTL through the public resend
                # path. The failed candidate remains a terminal erased row.
                clock["now"] = fixed + timedelta(
                    seconds=settings.otp_resend_cooldown_seconds + 1
                )
                succeeding = _CertifiedGateProvider()
                sender_holder["sender"] = succeeding
                resend = known_client.post(
                    "/api/v1/auth/student/otp/resend", json={}
                )
                after = _flow_private_inventory(factory, known_token)
                same_authority.append(before["authority"] == after["authority"])
                recovered.append(
                    resend.status_code == 202
                    and after["active"] == 1
                    and after["challenge"] is not None
                )
                no_stale_payload.append(after["payload_rows"] == 0)
                exactly_one_acceptance.append(succeeding.acceptance_count == 1)
                exactly_one_delivered.append(after["delivered"] == 1)
            clock["now"] = fixed
        return {
            "purposes": [item[0] for item in cases],
            "known_decoy_shapes_equal": all(shapes_equal),
            "known_decoy_values_equal": all(values_equal),
            "symmetry_through_flow_ttl": all(ttl_symmetric),
            "fully_expired_status": (
                "unavailable" if all(fully_expired_unavailable) else "invalid"
            ),
            "fully_expired_known_decoy_values_equal": all(
                fully_expired_unavailable
            ),
            "recovery_same_authority": all(same_authority),
            "recovery_succeeded": all(recovered),
            "stale_payload_rows": 0 if all(no_stale_payload) else 1,
            "exactly_one_acceptance_each": all(exactly_one_acceptance),
            "exactly_one_delivered_each": all(exactly_one_delivered),
        }
    finally:
        endpoint._now = original_now
        settings.otp_outbox_max_attempts = original_max_attempts
        settings.otp_resend_cooldown_seconds = original_cooldown


def _run_expired_active_resend_probe(engine: Engine) -> dict[str, Any]:
    """Recover an expired verifier through the still-live cookie flow."""

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings
    from app.models.registration import OtpPurposeAuthority

    original_now = endpoint._now
    original_cooldown = settings.otp_resend_cooldown_seconds
    original_challenge_ttl = settings.otp_challenge_ttl_seconds
    original_flow_ttl = settings.otp_flow_ttl_seconds
    fixed = datetime.now(timezone.utc)
    clock = {"now": fixed}
    endpoint._now = lambda: clock["now"]
    settings.otp_resend_cooldown_seconds = 2
    settings.otp_challenge_ttl_seconds = 3
    settings.otp_flow_ttl_seconds = 30
    first_sender = _CertifiedGateProvider()
    sender_holder: dict[str, Any] = {"sender": first_sender}
    app, factory = _build_behavior_app(engine, sender_holder)
    mobile = _behavior_fixture_mobile("expired_active")
    try:
        _seed_active_registration(factory, mobile)
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = settings.cors_origins[0]
            started = client.post(
                "/api/v1/auth/student/login/otp/start",
                json={"mobile": mobile},
            )
            raw_token = client.cookies.get(settings.otp_flow_cookie_name)
            if started.status_code != 202 or not raw_token:
                raise ProductGateFailure("expired-active setup failed")
            before = _flow_private_inventory(factory, raw_token)
            with factory() as session:
                attempts_before = session.scalar(
                    select(OtpPurposeAuthority.failed_attempts).where(
                        OtpPurposeAuthority.id == before["authority"]
                    )
                )

            clock["now"] = fixed + timedelta(
                seconds=settings.otp_challenge_ttl_seconds + 1
            )
            state = client.get("/api/v1/auth/student/otp/state")
            state_body = state.json()
            replacement_sender = _CertifiedGateProvider()
            sender_holder["sender"] = replacement_sender
            resend = client.post("/api/v1/auth/student/otp/resend", json={})
            after = _flow_private_inventory(factory, raw_token)
            with factory() as session:
                attempts_after = session.scalar(
                    select(OtpPurposeAuthority.failed_attempts).where(
                        OtpPurposeAuthority.id == before["authority"]
                    )
                )
        return {
            "status_before_resend": state_body.get("status"),
            "expires_zero": state_body.get("expires_in_seconds") == 0,
            "resend_allowed": state_body.get("resend_allowed") is True,
            "resend_status": resend.status_code,
            "same_authority": before["authority"] == after["authority"],
            "replacement_active": (
                after["active"] == 1
                and after["challenge"] is not None
                and after["challenge"] != before["challenge"]
            ),
            "attempts_unchanged": attempts_before == attempts_after,
            "delivery_delta": after["delivered"] - before["delivered"],
            "provider_acceptance_delta": replacement_sender.acceptance_count,
            "stale_payload_rows": after["payload_rows"],
        }
    finally:
        endpoint._now = original_now
        settings.otp_resend_cooldown_seconds = original_cooldown
        settings.otp_challenge_ttl_seconds = original_challenge_ttl
        settings.otp_flow_ttl_seconds = original_flow_ttl


def _run_lockout_probe(engine: Engine) -> dict[str, Any]:
    """Prove the stable signup authority cannot be reset through resend."""

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings
    from app.models.registration import OtpPurposeAuthority

    original_now = endpoint._now
    fixed = datetime.now(timezone.utc)
    endpoint._now = lambda: fixed
    sender = _CertifiedGateProvider()
    sender_holder: dict[str, Any] = {"sender": sender}
    app, factory = _build_behavior_app(engine, sender_holder)
    payload = _nyay4_registration_payload(_behavior_fixture_mobile("lockout"))
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = settings.cors_origins[0]
            started = client.post(
                "/api/v1/auth/student/register",
                headers={"Idempotency-Key": "nyay4-lockout-0001"},
                json=payload,
            )
            raw_token = client.cookies.get(settings.otp_flow_cookie_name)
            codes = sender._private_accepted_codes()
            if started.status_code != 201 or not raw_token or len(codes) != 1:
                raise ProductGateFailure("lockout setup failed")
            wrong_code = "000000" if codes[0] != "000000" else "000001"
            inventory = _flow_private_inventory(factory, raw_token)
            wrong_statuses: list[int] = []
            wrong_codes: list[str | None] = []
            for _ in range(settings.otp_max_attempts):
                response = client.post(
                    "/api/v1/auth/student/otp/verify",
                    json={"code": wrong_code},
                )
                wrong_statuses.append(response.status_code)
                wrong_codes.append(_response_error_identity(response)[1])
            with factory() as session:
                authority = session.get(
                    OtpPurposeAuthority, inventory["authority"]
                )
                if authority is None:
                    raise ProductGateFailure("lockout authority disappeared")
                attempts_after_wrong = authority.failed_attempts
                locked = bool(
                    authority.locked_until is not None
                    and authority.locked_until > fixed.replace(tzinfo=None)
                    if authority.locked_until is not None
                    and authority.locked_until.tzinfo is None
                    else authority.locked_until is not None
                    and authority.locked_until > fixed
                )
                lock_deadline = authority.locked_until
            deliveries_before = sender.acceptance_count
            resend = client.post("/api/v1/auth/student/otp/resend", json={})
            with factory() as session:
                authority = session.get(
                    OtpPurposeAuthority, inventory["authority"]
                )
                if authority is None:
                    raise ProductGateFailure("lockout authority disappeared")
                attempts_after_resend = authority.failed_attempts
                lock_deadline_unchanged = authority.locked_until == lock_deadline
        return {
            "configured_max_attempts": settings.otp_max_attempts,
            "configured_lock_seconds": settings.otp_lockout_seconds,
            "wrong_statuses": wrong_statuses,
            "wrong_codes": wrong_codes,
            "attempts_after_wrong": attempts_after_wrong,
            "locked": locked,
            "resend_status": resend.status_code,
            "resend_code": _response_error_identity(resend)[1],
            "attempts_after_resend": attempts_after_resend,
            "lock_deadline_unchanged": lock_deadline_unchanged,
            "new_delivery_delta": sender.acceptance_count - deliveries_before,
        }
    finally:
        endpoint._now = original_now


def _run_failed_resend_probe(engine: Engine) -> dict[str, Any]:
    """Exhaust a staged resend without displacing the delivered verifier."""

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings
    from app.core.crypto import decrypt
    from app.models.registration import (
        OtpChallenge,
        OtpFlow,
        OtpOutbox,
        OtpPurposeAuthority,
        StudentRegistration,
    )
    from app.services import otp_outbox, otp_service
    from app.services.otp_flow_service import flow_token_hash
    from app.services.otp_sender import OtpSendError

    original_now = endpoint._now
    fixed = datetime.now(timezone.utc)
    endpoint._now = lambda: fixed
    initial_sender = _CertifiedGateProvider()
    sender_holder: dict[str, Any] = {"sender": initial_sender}
    app, factory = _build_behavior_app(engine, sender_holder)
    mobile = _behavior_fixture_mobile("failed_resend")
    try:
        _seed_active_registration(factory, mobile)
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = settings.cors_origins[0]
            started = client.post(
                "/api/v1/auth/student/login/otp/start", json={"mobile": mobile}
            )
            raw_token = client.cookies.get(settings.otp_flow_cookie_name)
        codes = initial_sender._private_accepted_codes()
        if started.status_code != 202 or not raw_token or len(codes) != 1:
            raise ProductGateFailure("failed-resend setup failed")

        resend_at = fixed + timedelta(
            seconds=settings.otp_resend_cooldown_seconds + 1
        )
        with factory() as session:
            flow = session.scalar(
                select(OtpFlow).where(OtpFlow.token_hash == flow_token_hash(raw_token))
            )
            if flow is None or flow.registration_id is None or flow.challenge_id is None:
                raise ProductGateFailure("failed-resend flow graph disappeared")
            registration = session.get(StudentRegistration, flow.registration_id)
            authority = session.get(OtpPurposeAuthority, flow.authority_id)
            if registration is None or authority is None:
                raise ProductGateFailure("failed-resend authority disappeared")
            prior_id = flow.challenge_id
            attempts_before = authority.failed_attempts
            locked_before = authority.locked_until
            candidate, intent = otp_service.resend(
                session,
                registration.id,
                resend_at,
                purpose="login",
                destination=decrypt(registration.mobile_ct),
            )
            candidate_id = candidate.id
            session.commit()

        failed_sender = _CertifiedGateProvider(
            fail_before_accept_count=settings.otp_outbox_max_attempts
        )
        failures = 0
        delivery_now = resend_at
        for _ in range(settings.otp_outbox_max_attempts):
            # Advance from the persisted retry authority instead of assuming a
            # particular backoff constant. A hot-loop rejection is not a
            # provider attempt and must not be miscounted as exhaustion.
            with factory() as session:
                current = session.get(OtpOutbox, intent.outbox_id)
                if current is None:
                    raise ProductGateFailure("failed-resend outbox disappeared")
                if current.next_attempt_at is not None:
                    next_attempt = current.next_attempt_at
                    if next_attempt.tzinfo is None:
                        next_attempt = next_attempt.replace(tzinfo=timezone.utc)
                    delivery_now = max(
                        delivery_now,
                        next_attempt + timedelta(microseconds=1),
                    )
            with factory() as session:
                try:
                    otp_outbox.run_delivery(
                        session,
                        intent,
                        failed_sender,
                        raise_on_failure=True,
                        now=delivery_now,
                    )
                except OtpSendError:
                    failures += 1

        with factory() as session:
            authority = session.scalar(
                select(OtpPurposeAuthority).where(
                    OtpPurposeAuthority.id == flow.authority_id
                )
            )
            prior = session.get(OtpChallenge, prior_id)
            candidate = session.get(OtpChallenge, candidate_id)
            replacement = session.scalar(
                select(OtpOutbox).where(OtpOutbox.challenge_id == candidate_id)
            )
            if authority is None or prior is None or candidate is None or replacement is None:
                raise ProductGateFailure("failed-resend terminal graph disappeared")
            prior_active_unchanged = bool(
                prior.delivery_state == "active" and prior.consumed_at is None
            )
            replacement_active = candidate.delivery_state == "active"
            replacement_deliverable = bool(
                replacement.status in {"pending", "claimed", "failed"}
                and replacement.code_ct is not None
                and replacement.destination_ct is not None
            )
            authority_unchanged = bool(
                authority.failed_attempts == attempts_before
                and authority.locked_until == locked_before
            )

        with factory() as session:
            try:
                verified = otp_service.verify(
                    session,
                    flow.registration_id,
                    codes[0],
                    resend_at,
                    purpose="login",
                    challenge_id=prior_id,
                )
            except otp_service.OtpError:
                prior_verification_succeeds = False
            else:
                prior_verification_succeeds = verified.id == prior_id
        return {
            "status": 502 if failures == settings.otp_outbox_max_attempts else 500,
            "code": "otp_delivery_failed" if failures else "unknown",
            "prior_active_unchanged": prior_active_unchanged,
            "prior_verification_succeeds": prior_verification_succeeds,
            "replacement_active": replacement_active,
            "replacement_deliverable": replacement_deliverable,
            "provider_acceptances": failed_sender.acceptance_count,
            "authority_unchanged": authority_unchanged,
        }
    finally:
        endpoint._now = original_now


def _stage_login_delivery(
    factory: sessionmaker[Session],
    *,
    mobile: str,
    now: datetime,
) -> dict[str, Any]:
    """Commit one real login candidate for direct relay characterization."""

    from app.services import login_service

    with factory() as session:
        raw_token, flow, intent = login_service.start_flow(session, mobile, now)
        if intent is None or flow.registration_id is None or flow.challenge_id is None:
            raise ProductGateFailure("relay staging did not create a real graph")
        session.commit()
        return {
            "token": raw_token,
            "registration": flow.registration_id,
            "authority": flow.authority_id,
            "challenge": flow.challenge_id,
            "outbox": intent.outbox_id,
            "intent": intent,
        }


def _run_registration_finalizer_interleaving_probe(engine: Engine) -> bool:
    """Force the NYAY-17 registration finalizer to overlap a relay worker.

    The finalizer and generic relay converge on the same lease/fencing seam.
    Pausing after the finalizer's provider claim proves the competing relay can
    observe the committed lease and return without a second callback, while
    the finalizer subsequently closes the ledger exactly once.
    """

    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.models.registration import (
        OtpOutbox,
        RegistrationIdempotencyRecord,
    )
    from app.schemas.registration import StudentRegisterRequest
    from app.services import otp_outbox, registration_service

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    key = "nyay4-finalizer-relay-interleave-v1"
    payload = StudentRegisterRequest.model_validate(
        _nyay4_registration_payload(
            _behavior_fixture_mobile("registration_finalizer")
        )
    )
    now = datetime.now(timezone.utc)
    with factory() as session:
        result = registration_service.register_student(
            session, payload, key, now=now
        )
        if result.delivery is None:
            raise ProductGateFailure("registration finalizer staging lost delivery")
        intent = result.delivery
        session.commit()

    callback_entered = threading.Event()
    release_callback = threading.Event()

    def callback() -> None:
        callback_entered.set()
        if not release_callback.wait(timeout=10):
            raise RuntimeError("registration finalizer callback timed out")

    provider = _CertifiedGateProvider(callback=callback)
    key_hash = registration_service.registration_idempotency_key_hash(key)

    def finalize() -> bool:
        try:
            with factory() as session:
                registration_service.finalize_pending_registration(
                    session, key_hash, provider
                )
            return True
        except Exception:
            return False

    def relay() -> tuple[bool, bool]:
        try:
            with factory() as session:
                return (
                    otp_outbox.run_delivery(
                        session,
                        intent,
                        provider,
                        raise_on_failure=False,
                        now=now,
                    ),
                    True,
                )
        except Exception:
            return False, False

    finalizer_ok = False
    relay_result: tuple[bool, bool] = (True, False)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(finalize)
        if not callback_entered.wait(timeout=10):
            release_callback.set()
            return False
        second = executor.submit(relay)
        relay_result = second.result(timeout=10)
        release_callback.set()
        finalizer_ok = first.result(timeout=10)

    with factory() as session:
        record = session.scalar(
            select(RegistrationIdempotencyRecord).where(
                RegistrationIdempotencyRecord.idempotency_key_hash == key_hash
            )
        )
        outbox = session.get(OtpOutbox, intent.outbox_id)
        terminal = bool(
            record is not None
            and record.state == "succeeded"
            and record.outbox_id is None
            and outbox is not None
            and outbox.status == "sent"
            and outbox.code_ct is None
            and outbox.destination_ct is None
        )
    return bool(
        finalizer_ok
        and relay_result == (False, True)
        and provider.calls == 1
        and provider.acceptance_count == 1
        and terminal
    )


def _run_claim_concurrency_probe(engine: Engine) -> dict[str, Any]:
    """Run two relay workers while the first provider callback is paused."""

    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.core.config import settings
    from app.core.crypto import decrypt
    from app.models.registration import (
        OtpChallenge,
        OtpOutbox,
        OtpPurposeAuthority,
        StudentRegistration,
    )
    from app.services import otp_outbox, otp_service

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    now = datetime.now(timezone.utc)
    mobile = _behavior_fixture_mobile("claim")
    _seed_active_registration(factory, mobile)
    graph = _stage_login_delivery(factory, mobile=mobile, now=now)
    callback_entered = threading.Event()
    release_callback = threading.Event()
    canary_lock_succeeded = False
    provider_callbacks = 0
    callback_failures = 0

    def callback() -> None:
        nonlocal canary_lock_succeeded, provider_callbacks, callback_failures
        provider_callbacks += 1
        try:
            with factory() as session:
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(text("SET LOCAL lock_timeout = '750ms'"))
                authority = session.scalar(
                    select(OtpPurposeAuthority)
                    .where(OtpPurposeAuthority.id == graph["authority"])
                    .with_for_update(nowait=True)
                )
                challenge = session.scalar(
                    select(OtpChallenge)
                    .where(OtpChallenge.id == graph["challenge"])
                    .with_for_update(nowait=True)
                )
                outbox = session.scalar(
                    select(OtpOutbox)
                    .where(OtpOutbox.id == graph["outbox"])
                    .with_for_update(nowait=True)
                )
                canary_lock_succeeded = all(
                    item is not None for item in (authority, challenge, outbox)
                )
                session.rollback()
        except Exception:
            callback_failures += 1
        callback_entered.set()
        if not release_callback.wait(timeout=10):
            callback_failures += 1

    provider = _CertifiedGateProvider(callback=callback)

    def deliver() -> tuple[bool, bool]:
        try:
            with factory() as session:
                return (
                    otp_outbox.run_delivery(
                        session,
                        graph["intent"],
                        provider,
                        raise_on_failure=False,
                        now=now,
                    ),
                    False,
                )
        except Exception:
            return False, True

    first_result: tuple[bool, bool] = (False, True)
    second_result: tuple[bool, bool] = (False, True)
    resend_same_claim = False
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(deliver)
        if not callback_entered.wait(timeout=10):
            release_callback.set()
            raise ProductGateFailure("relay provider callback did not start")

        # The callback can independently lock every graph row, proving the
        # lease transaction committed before external provider I/O.
        with factory() as session:
            registration = session.get(
                StudentRegistration, graph["registration"]
            )
            if registration is None:
                release_callback.set()
                raise ProductGateFailure("relay registration disappeared")
            candidate, same_intent = otp_service.resend(
                session,
                registration.id,
                now + timedelta(seconds=settings.otp_resend_cooldown_seconds + 1),
                purpose="login",
                destination=decrypt(registration.mobile_ct),
            )
            resend_same_claim = bool(
                candidate.id == graph["challenge"]
                and same_intent.outbox_id == graph["outbox"]
            )
            session.commit()

        second = executor.submit(deliver)
        second_result = second.result(timeout=10)
        release_callback.set()
        first_result = first.result(timeout=10)

    with factory() as session:
        outbox = session.get(OtpOutbox, graph["outbox"])
        active_claims = int(
            session.scalar(
                select(func.count(OtpOutbox.id)).where(
                    OtpOutbox.status == "claimed"
                )
            )
            or 0
        )
        terminal_sent = outbox is not None and outbox.status == "sent"
    results = (first_result, second_result)
    deadlocks = sum(int(item[1]) for item in results) + callback_failures
    finalizer_interleaving = _run_registration_finalizer_interleaving_probe(engine)
    return {
        "workers": 2,
        "completed": 2,
        "deadlocks": deadlocks,
        "claims_won": provider_callbacks,
        "provider_callbacks": provider_callbacks,
        "provider_acceptances": provider.acceptance_count,
        "newly_delivered_sum": sum(int(item[0]) for item in results),
        "active_claims": active_claims,
        "row_locks_during_callback": 0 if canary_lock_succeeded else 1,
        "canary_lock_succeeded": canary_lock_succeeded,
        "resend_while_claimed_rejected": resend_same_claim and terminal_sent,
        "registration_finalizer_interleaving_passed": finalizer_interleaving,
    }


def _run_provider_idempotency_probe(engine: Engine) -> dict[str, Any]:
    """Recover provider acceptance plus lost acknowledgement without replay."""

    from app.models.registration import OtpOutbox
    from app.services import otp_outbox
    from app.services.otp_sender import OtpSendError

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    now = datetime.now(timezone.utc)
    mobile = _behavior_fixture_mobile("provider")
    _seed_active_registration(factory, mobile)
    graph = _stage_login_delivery(factory, mobile=mobile, now=now)
    with factory() as session:
        before = session.get(OtpOutbox, graph["outbox"])
        if before is None:
            raise ProductGateFailure("provider probe outbox disappeared")
        stable_provider_key = before.provider_idempotency_key

    provider = _CertifiedGateProvider(lose_ack_after_accept_once=True)
    with factory() as session:
        first = otp_outbox.run_delivery(
            session,
            graph["intent"],
            provider,
            raise_on_failure=False,
            now=now,
        )
    with factory() as session:
        failed = session.get(OtpOutbox, graph["outbox"])
        if failed is None or failed.next_attempt_at is None:
            raise ProductGateFailure("provider acknowledgement-loss state missing")
        retry_at = (
            failed.next_attempt_at.replace(tzinfo=timezone.utc)
            if failed.next_attempt_at.tzinfo is None
            else failed.next_attempt_at.astimezone(timezone.utc)
        )
    with factory() as session:
        immediate = otp_outbox.run_delivery(
            session,
            graph["intent"],
            provider,
            raise_on_failure=False,
            now=now,
        )
    with factory() as session:
        retry = otp_outbox.run_delivery(
            session,
            graph["intent"],
            provider,
            raise_on_failure=False,
            now=retry_at + timedelta(seconds=1),
        )

    with factory() as session:
        terminal = session.get(OtpOutbox, graph["outbox"])
        if terminal is None:
            raise ProductGateFailure("provider terminal outbox disappeared")
        stable_key = terminal.provider_idempotency_key == stable_provider_key
        sent_count = int(
            session.scalar(
                select(func.count(OtpOutbox.id)).where(
                    OtpOutbox.id == graph["outbox"],
                    OtpOutbox.status == "sent",
                )
            )
            or 0
        )
        ciphertext_erased = terminal.code_ct is None

    payload_conflict_rejected = False
    try:
        provider.send_idempotent(
            "changed-private-destination",
            "000000",
            idempotency_token=stable_provider_key,
        )
    except OtpSendError:
        payload_conflict_rejected = True
    return {
        "provider_contract_name": provider.contract_name,
        "provider_contract_certified": True,
        # Only this named in-memory contract is characterized. A deployed
        # provider needs its own certification before any exactly-once claim.
        "real_provider_exactly_once_claimed": False,
        "provider_calls": provider.calls,
        "provider_acceptances": provider.acceptance_count,
        "ack_loss_injected": first is False and provider.calls >= 2,
        "retry_succeeded": retry is True and immediate is False,
        "stable_key": stable_key,
        "key_is_hmac64": bool(
            len(stable_provider_key) == 64
            and set(stable_provider_key) <= set("0123456789abcdef")
        ),
        "same_payload": retry is True,
        "payload_conflict_rejected": payload_conflict_rejected,
        "database_sent_once": sent_count == 1,
        "otp_ciphertext_erased": ciphertext_erased,
    }


def _run_retry_lease_probe(engine: Engine) -> dict[str, Any]:
    """Prove lease recovery, stale-token fencing, backoff, and erasure."""

    from app.core.config import settings
    from app.models.registration import OtpOutbox
    from app.services import otp_outbox

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    now = datetime.now(timezone.utc)
    mobile = _behavior_fixture_mobile("retry")
    _seed_active_registration(factory, mobile)
    graph = _stage_login_delivery(factory, mobile=mobile, now=now)

    with factory() as session:
        first_claim = otp_outbox._claim(
            session, graph["intent"], now=now, commit=True
        )
    if first_claim is False or first_claim is True:
        raise ProductGateFailure("retry probe first lease was not acquired")
    with factory() as session:
        blocked_claim = otp_outbox._claim(
            session,
            graph["intent"],
            now=now + timedelta(seconds=settings.otp_outbox_lease_seconds - 1),
            commit=True,
        )
    reclaim_at = now + timedelta(seconds=settings.otp_outbox_lease_seconds + 1)
    with factory() as session:
        second_claim = otp_outbox._claim(
            session, graph["intent"], now=reclaim_at, commit=True
        )
    if second_claim is False or second_claim is True:
        raise ProductGateFailure("retry probe expired lease was not reclaimed")

    with factory() as session:
        before = session.get(OtpOutbox, graph["outbox"])
        if before is None:
            raise ProductGateFailure("retry probe outbox disappeared")
        before_stale = (
            before.status,
            before.attempts,
            before.claim_token_hash,
            before.claimed_at,
            before.lease_expires_at,
            before.next_attempt_at,
            before.code_ct,
            before.destination_ct,
        )
        stale_result = otp_outbox._finalize_success(
            session,
            first_claim,
            receipt="stale-private-receipt",
            now=reclaim_at,
            commit=True,
        )
    with factory() as session:
        after = session.get(OtpOutbox, graph["outbox"])
        if after is None:
            raise ProductGateFailure("retry probe outbox disappeared")
        after_stale = (
            after.status,
            after.attempts,
            after.claim_token_hash,
            after.claimed_at,
            after.lease_expires_at,
            after.next_attempt_at,
            after.code_ct,
            after.destination_ct,
        )
        otp_outbox._finalize_failure(
            session, second_claim, now=reclaim_at, commit=True
        )

    with factory() as session:
        failed = session.get(OtpOutbox, graph["outbox"])
        if failed is None or failed.next_attempt_at is None:
            raise ProductGateFailure("retry backoff state disappeared")
        failed_next = (
            failed.next_attempt_at.replace(tzinfo=timezone.utc)
            if failed.next_attempt_at.tzinfo is None
            else failed.next_attempt_at.astimezone(timezone.utc)
        )
        backoff_positive = failed_next > reclaim_at
        immediate = otp_outbox._claim(
            session,
            graph["intent"],
            now=reclaim_at,
            commit=True,
        )

    # Drive every remaining retry through the real claim/failure state machine.
    while True:
        with factory() as session:
            row = session.get(OtpOutbox, graph["outbox"])
            if row is None:
                raise ProductGateFailure("retry terminal outbox disappeared")
            if row.status == "void":
                break
            if row.next_attempt_at is None:
                raise ProductGateFailure("retry row lost its bounded backoff")
            claim_at = (
                row.next_attempt_at.replace(tzinfo=timezone.utc)
                if row.next_attempt_at.tzinfo is None
                else row.next_attempt_at.astimezone(timezone.utc)
            ) + timedelta(seconds=1)
            claim = otp_outbox._claim(
                session, graph["intent"], now=claim_at, commit=True
            )
        if claim is False or claim is True:
            raise ProductGateFailure("retry row could not be reclaimed")
        with factory() as session:
            otp_outbox._finalize_failure(
                session, claim, now=claim_at, commit=True
            )

    with factory() as session:
        terminal = session.get(OtpOutbox, graph["outbox"])
        if terminal is None:
            raise ProductGateFailure("retry terminal outbox disappeared")
        return {
            "lease_expired_reclaimed": blocked_claim is False,
            "new_claim_token": first_claim.token_hash != second_claim.token_hash,
            "stale_finalize_rejected": stale_result is False,
            "stale_finalize_state_unchanged": before_stale == after_stale,
            "backoff_positive": backoff_positive,
            "immediate_retry_claims": int(immediate not in {False, True}),
            "attempts_at_terminal": terminal.attempts,
            "configured_max_attempts": terminal.max_attempts,
            "terminal_status": terminal.status,
            "otp_ciphertext_erased": terminal.code_ct is None,
            "destination_ciphertext_erased": terminal.destination_ct is None,
        }


def _compose_retry_observation(
    lease: Mapping[str, Any],
    initial_exhaustion: Mapping[str, Any],
    maintenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Merge independent real-service probes into the exact retry oracle."""

    return {
        **dict(lease),
        "initial_exhaustion_recovery_same_authority": initial_exhaustion[
            "recovery_same_authority"
        ],
        "initial_exhaustion_recovery_succeeded": initial_exhaustion[
            "recovery_succeeded"
        ],
        "initial_exhaustion_stale_payload_rows": initial_exhaustion[
            "stale_payload_rows"
        ],
        "initial_exhaustion_exactly_one_acceptance_each": initial_exhaustion[
            "exactly_one_acceptance_each"
        ],
        "initial_exhaustion_exactly_one_delivered_each": initial_exhaustion[
            "exactly_one_delivered_each"
        ],
        "aged_legacy_destinations_purged": maintenance[
            "aged_legacy_destination_purged"
        ],
        "active_recent_outboxes_preserved": maintenance[
            "recent_legacy_destination_preserved"
        ],
        "expired_flows_terminalized": maintenance["expired_flow_terminalized"],
        "expired_flow_key_reuse_blocked": maintenance[
            "expired_key_reuse_blocked"
        ],
        "maintenance_counts_aggregate_only": maintenance[
            "counts_aggregate_only"
        ],
    }


def _run_rate_budget_probe(engine: Engine) -> dict[str, Any]:
    """Exercise all durable abuse-budget dimensions at exact configured limits."""

    from sqlalchemy import delete as sa_delete

    from app.core.config import settings
    from app.models.registration import OtpRateLimitBucket
    from app.services import otp_authority

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    actions = ("issue", "resend", "verify")
    scopes = ("identity", "ip", "global")
    dimensions: list[str] = []
    exact_acceptance: list[bool] = []
    next_rejected: list[bool] = []
    exact_retry: list[bool] = []
    original: dict[str, Any] = {}
    for action in actions:
        for suffix in (
            "rate_window_seconds",
            "identity_limit",
            "ip_limit",
            "global_limit",
        ):
            name = f"otp_{action}_{suffix}"
            original[name] = getattr(settings, name)

    try:
        for action in actions:
            window_field = f"otp_{action}_rate_window_seconds"
            setattr(settings, window_field, 61)
            for scope in scopes:
                dimensions.append(f"{scope}_{action}")
                for candidate in scopes:
                    setattr(
                        settings,
                        f"otp_{action}_{candidate}_limit",
                        2 if candidate == scope else 100,
                    )
                with factory() as session:
                    session.execute(sa_delete(OtpRateLimitBucket))
                    session.commit()
                subject = otp_authority.authority_subject_for_mobile(
                    f"8{len(dimensions):09d}"
                )
                accepted = 0
                for _ in range(2):
                    with factory() as session:
                        otp_authority.consume_rate_budgets(
                            session,
                            subject_hash=subject,
                            client_ip="198.51.100.44",
                            action=action,
                            now=datetime.now(timezone.utc).replace(microsecond=0),
                        )
                    accepted += 1
                fixed = datetime.now(timezone.utc).replace(microsecond=0)
                rejected = False
                retry = None
                try:
                    with factory() as session:
                        otp_authority.consume_rate_budgets(
                            session,
                            subject_hash=subject,
                            client_ip="198.51.100.44",
                            action=action,
                            now=fixed,
                        )
                except otp_authority.RateLimitExceeded as exc:
                    rejected = True
                    retry = exc.retry_after_seconds
                exact_acceptance.append(accepted == 2)
                next_rejected.append(rejected)
                exact_retry.append(retry in {60, 61})

        # Clear the dimension fixtures, restore production choices, and bind
        # the actual HTTP peer boundary. Distinct X-Forwarded-For values must
        # still consume the same immediate-peer IP bucket.
        for name, value in original.items():
            setattr(settings, name, value)
        with factory() as session:
            session.execute(sa_delete(OtpRateLimitBucket))
            session.commit()
        sender_holder: dict[str, Any] = {"sender": _CertifiedGateProvider()}
        app, _ = _build_behavior_app(engine, sender_holder)
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = settings.cors_origins[0]
            forwarded_statuses = []
            for value in ("203.0.113.10", "203.0.113.11"):
                response = client.post(
                    "/api/v1/auth/student/login/otp/start",
                    headers={"X-Forwarded-For": value},
                    json={"mobile": _behavior_fixture_mobile("rate_forwarded")},
                )
                forwarded_statuses.append(response.status_code)
        with factory() as session:
            ip_rows = list(
                session.scalars(
                    select(OtpRateLimitBucket).where(
                        OtpRateLimitBucket.scope == "ip",
                        OtpRateLimitBucket.action == "issue",
                    )
                )
            )
            identity_rows = list(
                session.scalars(
                    select(OtpRateLimitBucket).where(
                        OtpRateLimitBucket.scope == "identity"
                    )
                )
            )
            raw_identity_rows = sum(
                int(
                    len(row.subject_hash) != 64
                    or bool(set(row.subject_hash) - set("0123456789abcdef"))
                )
                for row in identity_rows
            )
            raw_ip_rows = sum(
                int(
                    len(row.subject_hash) != 64
                    or bool(set(row.subject_hash) - set("0123456789abcdef"))
                )
                for row in ip_rows
            )
            forwarded_ignored = bool(
                forwarded_statuses == [202, 202]
                and len(ip_rows) == 1
                and ip_rows[0].request_count == 2
            )

        # Both a real and decoy subject enter the same three-row service shape;
        # the budget layer receives only an opaque authority subject.
        real_subject = otp_authority.authority_subject_for_mobile(
            _behavior_fixture_mobile("rate_real")
        )
        decoy_subject = otp_authority.authority_subject_for_mobile(
            _behavior_fixture_mobile("rate_decoy")
        )

        def aggregate_shape(subject: str) -> list[tuple[str, str, int, int]]:
            with factory() as session:
                session.execute(sa_delete(OtpRateLimitBucket))
                session.commit()
            with factory() as session:
                otp_authority.consume_rate_budgets(
                    session,
                    subject_hash=subject,
                    client_ip="198.51.100.45",
                    action="issue",
                    now=datetime.now(timezone.utc).replace(microsecond=0),
                )
            with factory() as session:
                return sorted(
                    (
                        row.scope,
                        row.action,
                        row.request_count,
                        row.max_requests,
                    )
                    for row in session.scalars(select(OtpRateLimitBucket))
                )

        real_decoy_symmetric = (
            aggregate_shape(real_subject) == aggregate_shape(decoy_subject)
        )
        return {
            "dimensions": sorted(dimensions),
            "limits_positive": all(
                isinstance(value, int) and value > 0 for value in original.values()
            ),
            "accepted_equal_limits": all(exact_acceptance),
            "next_rejected": all(next_rejected),
            "retry_after_exact": all(exact_retry),
            "real_decoy_symmetric": real_decoy_symmetric,
            "untrusted_forwarded_for_ignored": forwarded_ignored,
            "raw_identity_rows": raw_identity_rows,
            "raw_ip_rows": raw_ip_rows,
        }
    finally:
        for name, value in original.items():
            setattr(settings, name, value)


def _run_cookie_projection_probe(engine: Engine) -> dict[str, Any]:
    """Compare repeated known/decoy starts, cookies, reload, and Origin."""

    import math
    import time

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings
    from app.models.registration import OtpFlow

    original_now = endpoint._now
    original_env = settings.app_env
    original_limits = (
        settings.otp_issue_identity_limit,
        settings.otp_issue_ip_limit,
        settings.otp_issue_global_limit,
    )
    fixed = datetime.now(timezone.utc)
    clock = {"now": fixed}
    endpoint._now = lambda: clock["now"]
    settings.app_env = "production"
    settings.otp_issue_identity_limit = 100
    settings.otp_issue_ip_limit = 1000
    settings.otp_issue_global_limit = 10000
    sender_holder: dict[str, Any] = {"sender": _CertifiedGateProvider()}
    app, factory = _build_behavior_app(engine, sender_holder)
    origin = settings.cors_origins[0]
    known_mobile = _behavior_fixture_mobile("cookie_known")
    decoy_mobile = _behavior_fixture_mobile("cookie_decoy")

    def start(client: TestClient, mobile: str):
        began = time.perf_counter_ns()
        response = client.post(
            "/api/v1/auth/student/login/otp/start",
            headers={"Origin": origin},
            json={"mobile": mobile},
        )
        return response, max(1, time.perf_counter_ns() - began)

    try:
        _seed_active_registration(factory, known_mobile)
        raw_tokens: list[str] = []
        known_durations: list[int] = []
        decoy_durations: list[int] = []
        exact_pairs: list[bool] = []
        with (
            TestClient(
                app,
                base_url="https://testserver",
                raise_server_exceptions=False,
            ) as known_client,
            TestClient(
                app,
                base_url="https://testserver",
                raise_server_exceptions=False,
            ) as decoy_client,
        ):
            first_known, _ = start(known_client, known_mobile)
            first_decoy, _ = start(decoy_client, decoy_mobile)
            cookie_header = first_known.headers.get("set-cookie", "")
            for client in (known_client, decoy_client):
                token = client.cookies.get(settings.otp_flow_cookie_name)
                if token:
                    raw_tokens.append(token)
            if first_known.status_code != 202 or first_decoy.status_code != 202:
                raise ProductGateFailure("cookie projection setup failed")
            exact_pairs.append(first_known.content == first_decoy.content)

            # The initial provider path is deliberately excluded from timing;
            # repeated cooldown starts execute the stable non-enumerating path.
            for _ in range(8):
                # Batch four identical requests per sample so an unrelated
                # scheduler pause on one sub-millisecond TestClient request
                # cannot manufacture an account-enumeration failure. The
                # measured work is still real HTTP/service/DB work in both
                # classes, and the authoritative PG run retains eight
                # independent paired samples.
                known_batch = [start(known_client, known_mobile) for _ in range(4)]
                decoy_batch = [start(decoy_client, decoy_mobile) for _ in range(4)]
                known, known_ns = known_batch[-1][0], sum(
                    item[1] for item in known_batch
                )
                decoy, decoy_ns = decoy_batch[-1][0], sum(
                    item[1] for item in decoy_batch
                )
                known_durations.append(known_ns)
                decoy_durations.append(decoy_ns)
                exact_pairs.append(
                    all(item[0].status_code == 202 for item in known_batch)
                    and all(item[0].status_code == 202 for item in decoy_batch)
                    and all(
                        item[0].content == known.content for item in known_batch
                    )
                    and all(
                        item[0].content == decoy.content for item in decoy_batch
                    )
                    and known.content == decoy.content
                )
                for client in (known_client, decoy_client):
                    token = client.cookies.get(settings.otp_flow_cookie_name)
                    if token:
                        raw_tokens.append(token)

            state_one = known_client.get("/api/v1/auth/student/otp/state")
            state_two = known_client.get("/api/v1/auth/student/otp/state")
            missing_origin = known_client.post(
                "/api/v1/auth/student/otp/resend", json={}
            )
            bad_origin = known_client.post(
                "/api/v1/auth/student/otp/resend",
                headers={"Origin": "https://untrusted.example.invalid"},
                json={},
            )
            clock["now"] = fixed + timedelta(
                seconds=settings.otp_resend_cooldown_seconds + 1
            )
            good_origin = known_client.post(
                "/api/v1/auth/student/otp/resend",
                headers={"Origin": origin},
                json={},
            )

        def p95(values: list[int]) -> int:
            return sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)]

        known_p95 = p95(known_durations)
        decoy_p95 = p95(decoy_durations)
        timing_ratio_milli = math.ceil(
            max(known_p95, decoy_p95) * 1000 / min(known_p95, decoy_p95)
        )
        with factory() as session:
            stored = set(session.scalars(select(OtpFlow.token_hash)))
        raw_flow_token_rows = sum(int(token in stored) for token in raw_tokens)
        all_bodies = (first_known.content, first_decoy.content, state_one.content)
        uuid_in_response = any(
            re.search(
                rb"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                body,
                flags=re.IGNORECASE,
            )
            is not None
            for body in all_bodies
        )
        lower_cookie = cookie_header.casefold()
        return {
            "start_statuses": [first_known.status_code, first_decoy.status_code],
            "start_signatures_equal": all(exact_pairs),
            "timing_ratio_within_bound": timing_ratio_milli <= 2000,
            "timing_samples_per_class": len(known_durations),
            "timing_p95_ratio_milli": timing_ratio_milli,
            "timing_bound_milli": 2000,
            "cookie_httponly": "httponly" in lower_cookie,
            "cookie_secure_nonlocal": "secure" in lower_cookie,
            "cookie_samesite": (
                "strict" if "samesite=strict" in lower_cookie else "invalid"
            ),
            "raw_flow_token_rows": raw_flow_token_rows,
            "uuid_in_response": uuid_in_response,
            "reload_status": state_two.status_code,
            "reload_metadata_equal": state_one.content == state_two.content,
            "origin_missing_status": missing_origin.status_code,
            "origin_bad_status": bad_origin.status_code,
            "origin_good_status": good_origin.status_code,
        }
    finally:
        endpoint._now = original_now
        settings.app_env = original_env
        (
            settings.otp_issue_identity_limit,
            settings.otp_issue_ip_limit,
            settings.otp_issue_global_limit,
        ) = original_limits


def _compose_cookie_observation(
    base: Mapping[str, Any],
    initial: Mapping[str, Any],
    neutralized: Mapping[str, Any],
    pending: Mapping[str, Any],
    verify: Mapping[str, Any],
    *,
    neutralized_concurrent_mismatch_linearized: bool,
) -> dict[str, Any]:
    return {
        **dict(base),
        "invalid_expired_consumed_signatures_equal": bool(
            verify["expired_values_equal"] and verify["consumed_values_equal"]
        ),
        "invalid_expired_consumed_values_equal": bool(
            verify["expired_values_equal"] and verify["consumed_values_equal"]
        ),
        "terminal_verify_zero_delta": bool(
            verify["expired_real_zero_delta"]
            and verify["expired_decoy_zero_delta"]
            and verify["consumed_real_zero_delta"]
            and verify["consumed_decoy_zero_delta"]
        ),
        "initial_exhaustion_purposes": initial["purposes"],
        "initial_exhaustion_known_decoy_shapes_equal": initial[
            "known_decoy_shapes_equal"
        ],
        "initial_exhaustion_known_decoy_values_equal": initial[
            "known_decoy_values_equal"
        ],
        "initial_exhaustion_symmetry_through_flow_ttl": initial[
            "symmetry_through_flow_ttl"
        ],
        "fully_expired_status": initial["fully_expired_status"],
        "fully_expired_known_decoy_values_equal": initial[
            "fully_expired_known_decoy_values_equal"
        ],
        "neutralized_key_request_bound": neutralized["key_request_bound"],
        "neutralized_exact_replay_stable": neutralized["exact_replay_stable"],
        "neutralized_live_mutations_conflict": neutralized[
            "live_mutations_conflict"
        ],
        "neutralized_concurrent_mismatch_linearized": (
            neutralized_concurrent_mismatch_linearized
        ),
        "neutralized_expired_mutations_uniform": neutralized[
            "expired_mutations_uniform"
        ],
        "neutralized_removed_mutations_uniform": neutralized[
            "removed_mutations_uniform"
        ],
        "pending_expired_mutations_uniform": pending[
            "expired_mutations_uniform"
        ],
        "pending_missing_mutations_uniform": pending["missing_mutations_uniform"],
        "lifecycle_replay_zero_provider": bool(
            neutralized["zero_provider"] and pending["zero_provider"]
        ),
        "lifecycle_replay_zero_delta": bool(
            neutralized["zero_delta_after_terminal"]
            and pending["zero_delta_after_terminal"]
        ),
    }


def _run_metadata_probe(engine: Engine) -> dict[str, Any]:
    """Bind every public timer/attempt value to persisted authority columns."""

    import math

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings
    from app.models.registration import OtpFlow, OtpPurposeAuthority
    from app.services.otp_flow_service import flow_token_hash

    original_now = endpoint._now
    fixed = datetime.now(timezone.utc).replace(microsecond=0)
    endpoint._now = lambda: fixed
    sender = _CertifiedGateProvider()
    sender_holder: dict[str, Any] = {"sender": sender}
    app, factory = _build_behavior_app(engine, sender_holder)
    payload = _nyay4_registration_payload(_behavior_fixture_mobile("metadata"))

    def as_utc(value: datetime) -> datetime:
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = settings.cors_origins[0]
            started = client.post(
                "/api/v1/auth/student/register",
                headers={"Idempotency-Key": "nyay4-metadata-0001"},
                json=payload,
            )
            raw_token = client.cookies.get(settings.otp_flow_cookie_name)
            codes = sender._private_accepted_codes()
            if started.status_code != 201 or not raw_token or len(codes) != 1:
                raise ProductGateFailure("metadata setup failed")
            state = client.get("/api/v1/auth/student/otp/state")
            body = state.json()
            malformed = client.post(
                "/api/v1/auth/student/otp/verify", json={"code": "123"}
            )
            cooldown = client.post("/api/v1/auth/student/otp/resend", json={})
            wrong_code = "000000" if codes[0] != "000000" else "000001"
            wrong_responses = [
                client.post(
                    "/api/v1/auth/student/otp/verify",
                    json={"code": wrong_code},
                )
                for _ in range(settings.otp_max_attempts)
            ]

        with factory() as session:
            flow = session.scalar(
                select(OtpFlow).where(OtpFlow.token_hash == flow_token_hash(raw_token))
            )
            authority = (
                session.get(OtpPurposeAuthority, flow.authority_id)
                if flow is not None
                else None
            )
            if flow is None or authority is None or authority.last_issued_at is None:
                raise ProductGateFailure("metadata authority disappeared")
            verifier_expiry = as_utc(authority.last_issued_at) + timedelta(
                seconds=settings.otp_challenge_ttl_seconds
            )
            expected_expiry = max(
                0,
                math.ceil(
                    (min(as_utc(flow.expires_at), verifier_expiry) - fixed).total_seconds()
                ),
            )
            expected_cooldown = max(
                0,
                math.ceil(
                    (as_utc(authority.cooldown_until) - fixed).total_seconds()
                ),
            ) if authority.cooldown_until is not None else 0
            expected_lock = max(
                0,
                math.ceil((as_utc(authority.locked_until) - fixed).total_seconds()),
            ) if authority.locked_until is not None else 0
            attempts_match = bool(
                body.get("attempts_left") == settings.otp_max_attempts
                and authority.failed_attempts == settings.otp_max_attempts
            )

        cooldown_retry = int(cooldown.headers.get("Retry-After", "0") or 0)
        locked_response = wrong_responses[-1]
        locked_retry = int(locked_response.headers.get("Retry-After", "0") or 0)
        exact_fields = {
            "status",
            "purpose",
            "destination_masked",
            "attempts_left",
            "expires_in_seconds",
            "resend_in_seconds",
            "locked_for_seconds",
            "resend_allowed",
        }
        return {
            "fields_exact": set(body) == exact_fields,
            "attempts_from_authority": attempts_match,
            "cooldown_from_database": body.get("resend_in_seconds") == expected_cooldown,
            "expiry_from_database": body.get("expires_in_seconds") == expected_expiry,
            "lock_from_database": locked_retry == expected_lock,
            "retry_after_matches": bool(
                cooldown.status_code == 429
                and cooldown_retry == expected_cooldown
                and locked_response.status_code == 423
                and locked_retry == expected_lock
            ),
            "bounded_clock_skew": bool(
                abs(int(body.get("expires_in_seconds") or 0) - expected_expiry) <= 1
                and abs(int(body.get("resend_in_seconds") or 0) - expected_cooldown) <= 1
            ),
            "typed_outcomes_exact": bool(
                malformed.status_code == 422
                and _response_error_identity(cooldown)[1] == "resend_cooldown"
                and _response_error_identity(wrong_responses[0])[1] == "incorrect_otp"
                and _response_error_identity(locked_response)[1] == "locked"
            ),
            "no_local_clock_authority": bool(
                body.get("expires_in_seconds") == expected_expiry
                and body.get("resend_in_seconds") == expected_cooldown
            ),
        }
    finally:
        endpoint._now = original_now


def _prepare_signup_race_graph(
    engine: Engine,
    *,
    mobile: str,
    key: str,
) -> tuple[sessionmaker[Session], dict[str, Any]]:
    """Commit one delivered signup verifier and return private graph handles."""

    from app.core.config import settings
    from app.models.registration import OtpFlow
    from app.services.otp_flow_service import flow_token_hash

    sender_holder: dict[str, Any] = {"sender": _CertifiedGateProvider()}
    app, factory = _build_behavior_app(engine, sender_holder)
    payload = _nyay4_registration_payload(mobile)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.headers["Origin"] = settings.cors_origins[0]
        response = client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": key},
            json=payload,
        )
        raw_token = client.cookies.get(settings.otp_flow_cookie_name)
    codes = sender_holder["sender"]._private_accepted_codes()
    if response.status_code != 201 or not raw_token or len(codes) != 1:
        raise ProductGateFailure("signup race graph setup failed")
    with factory() as session:
        flow = session.scalar(
            select(OtpFlow).where(OtpFlow.token_hash == flow_token_hash(raw_token))
        )
        if flow is None or flow.registration_id is None or flow.challenge_id is None:
            raise ProductGateFailure("signup race flow graph disappeared")
        return factory, {
            "registration": flow.registration_id,
            "authority": flow.authority_id,
            "challenge": flow.challenge_id,
            "code": codes[0],
        }


def _run_concurrent_verify_probe(engine: Engine) -> dict[str, Any]:
    """Race wrong-code verifiers through real PostgreSQL service sessions."""

    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.core.config import settings
    from app.models.registration import OtpChallenge, OtpOutbox, OtpPurposeAuthority
    from app.services import otp_service

    factory, graph = _prepare_signup_race_graph(
        engine,
        mobile=_behavior_fixture_mobile("concurrent_verify"),
        key="nyay4-concurrent-verify-0001",
    )
    wrong_code = "000000" if graph["code"] != "000000" else "000001"
    workers = settings.otp_max_attempts + 2
    barrier = threading.Barrier(workers)
    now = datetime.now(timezone.utc)

    def worker() -> tuple[str, int | None]:
        try:
            barrier.wait(timeout=10)
            with factory() as session:
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(text("SET LOCAL statement_timeout = '10s'"))
                otp_service.verify(
                    session,
                    graph["registration"],
                    wrong_code,
                    now,
                    purpose="signup",
                    challenge_id=graph["challenge"],
                )
        except otp_service.OtpError as exc:
            return "typed", exc.status_code
        except Exception:
            return "deadlock", None
        return "success", 200

    with ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = list(executor.map(lambda _: worker(), range(workers)))
    with factory() as session:
        authority = session.get(OtpPurposeAuthority, graph["authority"])
        if authority is None:
            raise ProductGateFailure("concurrent verify authority disappeared")
        active = int(
            session.scalar(
                select(func.count(OtpChallenge.id)).where(
                    OtpChallenge.authority_id == authority.id,
                    OtpChallenge.delivery_state == "active",
                )
            )
            or 0
        )
        deliverable = int(
            session.scalar(
                select(func.count(OtpOutbox.id))
                .join(OtpChallenge, OtpOutbox.challenge_id == OtpChallenge.id)
                .where(
                    OtpChallenge.authority_id == authority.id,
                    OtpOutbox.status.in_(("pending", "claimed", "failed")),
                )
            )
            or 0
        )
        return {
            "workers": workers,
            "completed": len(outcomes),
            "deadlocks": sum(kind == "deadlock" for kind, _ in outcomes),
            "successes": sum(kind == "success" for kind, _ in outcomes),
            "typed_failures": sum(kind == "typed" for kind, _ in outcomes),
            "stored_attempts": authority.failed_attempts,
            "configured_max_attempts": authority.max_attempts,
            "locked": authority.locked_until is not None,
            "active_challenges": active,
            "deliverable_outboxes": deliverable,
        }


def _run_concurrent_resend_probe(engine: Engine) -> dict[str, Any]:
    """Race resends; only one candidate/budget increment may commit."""

    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.core.config import settings
    from app.core.crypto import decrypt
    from app.models.registration import (
        OtpChallenge,
        OtpOutbox,
        OtpPurposeAuthority,
        StudentRegistration,
    )
    from app.services import otp_service

    factory, graph = _prepare_signup_race_graph(
        engine,
        mobile=_behavior_fixture_mobile("concurrent_resend"),
        key="nyay4-concurrent-resend-0001",
    )
    workers = 4
    barrier = threading.Barrier(workers)
    now = datetime.now(timezone.utc) + timedelta(
        seconds=settings.otp_resend_cooldown_seconds + 1
    )
    with factory() as session:
        authority = session.get(OtpPurposeAuthority, graph["authority"])
        if authority is None:
            raise ProductGateFailure("concurrent resend authority disappeared")
        attempts_before = authority.failed_attempts
        lock_before = authority.locked_until
        resend_before = authority.resend_count

    def worker() -> str:
        try:
            barrier.wait(timeout=10)
            with factory() as session:
                if session.get_bind().dialect.name == "postgresql":
                    session.execute(text("SET LOCAL statement_timeout = '10s'"))
                registration = session.get(
                    StudentRegistration, graph["registration"]
                )
                if registration is None:
                    return "deadlock"
                otp_service.resend(
                    session,
                    registration.id,
                    now,
                    purpose="signup",
                    destination=decrypt(registration.mobile_ct),
                )
                session.commit()
                return "accepted"
        except otp_service.OtpError:
            return "typed"
        except Exception:
            return "deadlock"

    with ThreadPoolExecutor(max_workers=workers) as executor:
        outcomes = list(executor.map(lambda _: worker(), range(workers)))
    with factory() as session:
        authority = session.get(OtpPurposeAuthority, graph["authority"])
        if authority is None:
            raise ProductGateFailure("concurrent resend authority disappeared")
        authority_rows = int(
            session.scalar(
                select(func.count(OtpPurposeAuthority.id)).where(
                    OtpPurposeAuthority.id == graph["authority"]
                )
            )
            or 0
        )
        staged = int(
            session.scalar(
                select(func.count(OtpChallenge.id)).where(
                    OtpChallenge.authority_id == authority.id,
                    OtpChallenge.delivery_state == "pending_delivery",
                )
            )
            or 0
        )
        active = int(
            session.scalar(
                select(func.count(OtpChallenge.id)).where(
                    OtpChallenge.authority_id == authority.id,
                    OtpChallenge.delivery_state == "active",
                )
            )
            or 0
        )
        deliverable = int(
            session.scalar(
                select(func.count(OtpOutbox.id))
                .join(OtpChallenge, OtpOutbox.challenge_id == OtpChallenge.id)
                .where(
                    OtpChallenge.authority_id == authority.id,
                    OtpOutbox.status.in_(("pending", "claimed", "failed")),
                )
            )
            or 0
        )
        return {
            "workers": workers,
            "completed": len(outcomes),
            "deadlocks": outcomes.count("deadlock"),
            "accepted_resends": outcomes.count("accepted"),
            "typed_rejections": outcomes.count("typed"),
            "authority_rows": authority_rows,
            "staged_challenges": staged,
            "active_challenges": active,
            "deliverable_outboxes": deliverable,
            "attempts_unchanged": authority.failed_attempts == attempts_before,
            "lock_unchanged": authority.locked_until == lock_before,
            "resend_budget_delta": authority.resend_count - resend_before,
        }


def _compose_resend_observation(
    concurrent: Mapping[str, Any],
    expired_active: Mapping[str, Any],
    alternation: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        **dict(concurrent),
        "expired_active_status_before_resend": expired_active[
            "status_before_resend"
        ],
        "expired_active_resend_allowed": expired_active["resend_allowed"],
        "expired_active_resend_status": expired_active["resend_status"],
        "expired_active_replacement_active": expired_active[
            "replacement_active"
        ],
        "expired_active_attempts_unchanged": expired_active[
            "attempts_unchanged"
        ],
        "expired_active_delivery_delta": expired_active["delivery_delta"],
        "alternation_purposes": alternation["purposes"],
        "fractional_retry_after_ceil": alternation[
            "fractional_retry_after_ceil"
        ],
        "exhausted_start_status": alternation["exhausted_start_status"],
        "exhausted_start_zero_delivery": alternation[
            "exhausted_start_zero_delivery"
        ],
        "alternation_real_decoy_equal": alternation["real_decoy_equal"],
    }


def _run_start_resend_alternation_probe(engine: Engine) -> dict[str, Any]:
    """Share one cooldown/window across public starts and explicit resends."""

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings

    original_now = endpoint._now
    names = (
        "otp_resend_cooldown_seconds",
        "otp_resend_window_seconds",
        "otp_max_resends_per_window",
        "otp_issue_identity_limit",
        "otp_issue_ip_limit",
        "otp_issue_global_limit",
        "otp_resend_identity_limit",
        "otp_resend_ip_limit",
        "otp_resend_global_limit",
    )
    original = {name: getattr(settings, name) for name in names}
    settings.otp_resend_cooldown_seconds = 2
    settings.otp_resend_window_seconds = 60
    settings.otp_max_resends_per_window = 2
    settings.otp_issue_identity_limit = 100
    settings.otp_issue_ip_limit = 1000
    settings.otp_issue_global_limit = 10000
    settings.otp_resend_identity_limit = 100
    settings.otp_resend_ip_limit = 1000
    settings.otp_resend_global_limit = 10000
    fixed = datetime.now(timezone.utc).replace(microsecond=0)
    clock = {"now": fixed}
    endpoint._now = lambda: clock["now"]
    sender = _CertifiedGateProvider()
    sender_holder: dict[str, Any] = {"sender": sender}
    app, _ = _build_behavior_app(engine, sender_holder)
    origin = settings.cors_origins[0]
    cases = (
        (
            "login",
            "/api/v1/auth/student/login/otp/start",
            _behavior_fixture_mobile("alternation_login_known"),
            _behavior_fixture_mobile("alternation_login_decoy"),
        ),
        (
            "recovery",
            "/api/v1/auth/student/recovery/start",
            _behavior_fixture_mobile("alternation_recovery_known"),
            _behavior_fixture_mobile("alternation_recovery_decoy"),
        ),
    )
    fractional: list[bool] = []
    statuses: list[int] = []
    zero_delivery: list[bool] = []
    equal: list[bool] = []
    try:
        for purpose, start_path, known_mobile, decoy_mobile in cases:
            _seed_active_registration(
                sessionmaker(
                    bind=engine,
                    autoflush=False,
                    expire_on_commit=False,
                    class_=Session,
                ),
                known_mobile,
            )
            with (
                TestClient(app, raise_server_exceptions=False) as known_client,
                TestClient(app, raise_server_exceptions=False) as decoy_client,
            ):
                known_start = known_client.post(
                    start_path,
                    headers={"Origin": origin},
                    json={"mobile": known_mobile},
                )
                decoy_start = decoy_client.post(
                    start_path,
                    headers={"Origin": origin},
                    json={"mobile": decoy_mobile},
                )
                if known_start.status_code != 202 or decoy_start.status_code != 202:
                    raise ProductGateFailure("start/resend alternation setup failed")

                # Fractional time just inside cooldown must ceil to one second
                # identically for known and decoy flows.
                clock["now"] = fixed + timedelta(seconds=1, microseconds=750000)
                early_known = known_client.post(
                    "/api/v1/auth/student/otp/resend",
                    headers={"Origin": origin},
                    json={},
                )
                early_decoy = decoy_client.post(
                    "/api/v1/auth/student/otp/resend",
                    headers={"Origin": origin},
                    json={},
                )
                fractional.append(
                    early_known.status_code == early_decoy.status_code == 429
                    and early_known.headers.get("Retry-After") == "1"
                    and early_decoy.headers.get("Retry-After") == "1"
                    and early_known.content == early_decoy.content
                )

                for offset in (2.25, 4.5):
                    whole, fraction = divmod(offset, 1)
                    clock["now"] = fixed + timedelta(
                        seconds=int(whole), microseconds=int(fraction * 1_000_000)
                    )
                    known = known_client.post(
                        "/api/v1/auth/student/otp/resend",
                        headers={"Origin": origin},
                        json={},
                    )
                    decoy = decoy_client.post(
                        "/api/v1/auth/student/otp/resend",
                        headers={"Origin": origin},
                        json={},
                    )
                    if known.status_code != 202 or decoy.status_code != 202:
                        raise ProductGateFailure("resend window setup failed")

                calls_before = sender.acceptance_count
                watched = (
                    "otp_purpose_authorities",
                    "otp_flows",
                    "otp_challenges",
                    "otp_outbox",
                )
                before = _tables_projection_digest(engine, watched)
                clock["now"] = fixed + timedelta(
                    seconds=6, microseconds=750000
                )
                exhausted_known = known_client.post(
                    start_path,
                    headers={"Origin": origin},
                    json={"mobile": known_mobile},
                )
                exhausted_decoy = decoy_client.post(
                    start_path,
                    headers={"Origin": origin},
                    json={"mobile": decoy_mobile},
                )
                after = _tables_projection_digest(engine, watched)
                statuses.append(exhausted_known.status_code)
                zero_delivery.append(
                    sender.acceptance_count == calls_before and before == after
                )
                equal.append(
                    exhausted_known.status_code
                    == exhausted_decoy.status_code
                    == 429
                    and exhausted_known.content == exhausted_decoy.content
                    and exhausted_known.headers.get("Retry-After")
                    == exhausted_decoy.headers.get("Retry-After")
                )
            clock["now"] = fixed
        return {
            "purposes": [item[0] for item in cases],
            "fractional_retry_after_ceil": all(fractional),
            "exhausted_start_status": 429 if statuses == [429, 429] else 500,
            "exhausted_start_zero_delivery": all(zero_delivery),
            "real_decoy_equal": all(equal),
        }
    finally:
        endpoint._now = original_now
        for name, value in original.items():
            setattr(settings, name, value)


def _run_neutralized_concurrency_probe(engine: Engine) -> dict[str, Any]:
    """Race distinct payloads for one duplicate-signup idempotency key."""

    import threading
    from concurrent.futures import ThreadPoolExecutor

    from app.core.config import settings
    from app.models.registration import OtpFlow, RegistrationIdempotencyRecord
    from app.services.registration_service import registration_idempotency_key_hash

    sender = _CertifiedGateProvider()
    sender_holder: dict[str, Any] = {"sender": sender}
    app, factory = _build_behavior_app(engine, sender_holder)
    payload = _nyay4_registration_payload(
        _behavior_fixture_mobile("neutralized_concurrency")
    )
    mutation = _nyay4_canonical_mutations(payload)[0]
    key = "nyay4-neutralized-race-0001"
    _seed_active_registration(factory, payload["mobile"])
    barrier = threading.Barrier(2)

    def worker(body: Mapping[str, Any]) -> tuple[int, str | None, bool]:
        try:
            barrier.wait(timeout=10)
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    "/api/v1/auth/student/register",
                    headers={
                        "Origin": settings.cors_origins[0],
                        "Idempotency-Key": key,
                    },
                    json=dict(body),
                )
                return response.status_code, _response_error_identity(response)[1], True
        except Exception:
            return 500, None, False

    bodies = (payload, mutation)
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(worker, bodies))
    winner_indexes = [index for index, item in enumerate(outcomes) if item[0] == 201]
    loser_indexes = [
        index
        for index, item in enumerate(outcomes)
        if item[:2] == (409, "idempotency_conflict")
    ]
    if len(winner_indexes) != 1 or len(loser_indexes) != 1:
        return {"linearized": False, "deadlocks": sum(not item[2] for item in outcomes)}
    watched = ("registration_idempotency_records", "otp_flows")
    before = _tables_projection_digest(engine, watched)
    with TestClient(app, raise_server_exceptions=False) as client:
        winner = client.post(
            "/api/v1/auth/student/register",
            headers={
                "Origin": settings.cors_origins[0],
                "Idempotency-Key": key,
            },
            json=bodies[winner_indexes[0]],
        )
        loser = client.post(
            "/api/v1/auth/student/register",
            headers={
                "Origin": settings.cors_origins[0],
                "Idempotency-Key": key,
            },
            json=bodies[loser_indexes[0]],
        )
    after = _tables_projection_digest(engine, watched)
    with factory() as session:
        key_hash = registration_idempotency_key_hash(key)
        ledger_rows = int(
            session.scalar(
                select(func.count(RegistrationIdempotencyRecord.id)).where(
                    RegistrationIdempotencyRecord.idempotency_key_hash == key_hash
                )
            )
            or 0
        )
        flow_rows = int(
            session.scalar(
                select(func.count(OtpFlow.id)).join(
                    RegistrationIdempotencyRecord,
                    OtpFlow.registration_idempotency_record_id
                    == RegistrationIdempotencyRecord.id,
                ).where(
                    RegistrationIdempotencyRecord.idempotency_key_hash == key_hash
                )
            )
            or 0
        )
    return {
        "linearized": bool(
            winner.status_code == 201
            and _response_error_identity(loser)[1] == "idempotency_conflict"
            and ledger_rows == 1
            and flow_rows == 1
            and before == after
            and sender.calls == 0
        ),
        "deadlocks": sum(not item[2] for item in outcomes),
    }


def _compose_rate_observation(
    rate: Mapping[str, Any], maintenance: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        **dict(rate),
        "retention_preserves_active_budgets": maintenance[
            "recent_bucket_preserved"
        ],
        "maintenance_entrypoint_executed": maintenance["entrypoint_executed"],
        "aged_buckets_purged": maintenance["aged_bucket_purged"],
        "active_recent_buckets_preserved": maintenance[
            "recent_bucket_preserved"
        ],
    }


def _nyay4_registration_payload(mobile: str) -> dict[str, Any]:
    return {
        "first_name": "Asha",
        "middle_name": None,
        "last_name": "Sen",
        "mobile": mobile,
        "dob": "2000-01-02",
        "consent": {
            "accepted": True,
            "policy_version": "dpdp-2023.v1",
        },
        "college": "Synthetic Law University",
        "year_of_study": "Year 2",
        "enrolment_number": "QA/1001/2026",
        "institutional_email": "synthetic@law.invalid",
        "bar_enrolment_number": "QA-BAR-1",
    }


def _nyay4_canonical_mutations(
    payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    replacements: tuple[tuple[str, Any], ...] = (
        ("first_name", "Maya"),
        ("middle_name", "Devi"),
        ("last_name", "Rao"),
        ("mobile", "7999994444"),
        ("dob", "2000-01-03"),
        ("consent.accepted", False),
        ("consent.policy_version", "dpdp-2023.v2"),
        ("college", "Other Law University"),
        ("year_of_study", "Year 3"),
        ("enrolment_number", "QA/9999/2026"),
        ("institutional_email", "changed@law.invalid"),
        ("bar_enrolment_number", "QA-BAR-CHANGED"),
    )
    mutations: list[dict[str, Any]] = []
    for path, replacement in replacements:
        candidate = deepcopy(dict(payload))
        if "." in path:
            parent, child = path.split(".", 1)
            candidate[parent] = dict(candidate[parent])
            candidate[parent][child] = replacement
        else:
            candidate[path] = replacement
        mutations.append(candidate)
    return mutations


def _response_error_identity(response: Any) -> tuple[int, str | None, str | None]:
    try:
        body = response.json()
    except Exception:
        return response.status_code, None, None
    detail = body.get("detail") if isinstance(body, Mapping) else None
    return (
        response.status_code,
        detail.get("code") if isinstance(detail, Mapping) else None,
        detail.get("field") if isinstance(detail, Mapping) else None,
    )


def _run_neutralized_registration_probe(engine: Engine) -> dict[str, Any]:
    """Prove duplicate signup keys remain bound through flow lifecycle."""

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings
    from app.models.registration import OtpFlow, RegistrationIdempotencyRecord
    from app.services import otp_flow_service, registration_service

    original_now = endpoint._now
    fixed = datetime.now(timezone.utc)
    clock = {"now": fixed}
    endpoint._now = lambda: clock["now"]
    sender = _CertifiedGateProvider()
    sender_holder: dict[str, Any] = {"sender": sender}
    app, factory = _build_behavior_app(engine, sender_holder)
    payload = _nyay4_registration_payload(
        _behavior_fixture_mobile("neutralized_lifecycle")
    )
    mutations = _nyay4_canonical_mutations(payload)
    watched_tables = (
        "registration_idempotency_records",
        "otp_flows",
        "otp_purpose_authorities",
        "otp_challenges",
        "otp_outbox",
        "student_registrations",
    )

    def post(client: TestClient, key: str, body: Mapping[str, Any]):
        return client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": key},
            json=dict(body),
        )

    try:
        _seed_active_registration(factory, payload["mobile"])
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = settings.cors_origins[0]
            key = "nyay4-neutralized-live-0001"
            created = post(client, key, payload)
            raw_token = client.cookies.get(settings.otp_flow_cookie_name)
            if created.status_code != 201 or not raw_token:
                raise ProductGateFailure("neutralized setup failed")
            live_digest = _tables_projection_digest(engine, watched_tables)
            replay = post(client, key, payload)
            replay_stable = bool(
                replay.status_code == 201
                and replay.content == created.content
                and client.cookies.get(settings.otp_flow_cookie_name) == raw_token
                and _tables_projection_digest(engine, watched_tables) == live_digest
            )
            live_conflicts = []
            for mutation in mutations:
                response = post(client, key, mutation)
                live_conflicts.append(
                    _response_error_identity(response)
                    == (409, "idempotency_conflict", "Idempotency-Key")
                    and _tables_projection_digest(engine, watched_tables)
                    == live_digest
                )

            # Lifecycle wins before content comparison. The first expired
            # replay performs one terminal transition; every later mutation is
            # the byte-identical bounded lifecycle response with zero delta.
            clock["now"] = fixed + timedelta(
                seconds=settings.otp_flow_ttl_seconds + 1
            )
            expired_exact = post(client, key, payload)
            terminal_digest = _tables_projection_digest(engine, watched_tables)
            expired_responses = [post(client, key, item) for item in mutations]
            expired_uniform = bool(
                _response_error_identity(expired_exact)
                == (409, "registration_replay_expired", "Idempotency-Key")
                and all(
                    response.content == expired_exact.content
                    and _response_error_identity(response)
                    == (409, "registration_replay_expired", "Idempotency-Key")
                    for response in expired_responses
                )
                and _tables_projection_digest(engine, watched_tables)
                == terminal_digest
            )
            with factory() as session:
                retired = session.scalar(
                    select(RegistrationIdempotencyRecord).where(
                        RegistrationIdempotencyRecord.idempotency_key_hash
                        == registration_service.registration_idempotency_key_hash(key)
                    )
                )
                terminal_shape = bool(
                    retired is not None
                    and retired.state == "retired"
                    and retired.request_fingerprint is None
                    and retired.request_fingerprint_version is None
                    and retired.registration_id is None
                    and retired.outbox_id is None
                )

            # A missing flow has the same precedence and cannot free the key.
            clock["now"] = fixed
            removed_key = "nyay4-neutralized-removed-0002"
            removed_created = post(client, removed_key, payload)
            removed_token = client.cookies.get(settings.otp_flow_cookie_name)
            if removed_created.status_code != 201 or not removed_token:
                raise ProductGateFailure("neutralized removal setup failed")
            with factory() as session:
                flow = session.scalar(
                    select(OtpFlow).where(
                        OtpFlow.token_hash
                        == otp_flow_service.flow_token_hash(removed_token)
                    )
                )
                if flow is None:
                    raise ProductGateFailure("neutralized removal flow missing")
                session.delete(flow)
                session.commit()
            removed_exact = post(client, removed_key, payload)
            removed_terminal = _tables_projection_digest(engine, watched_tables)
            removed_responses = [
                post(client, removed_key, item) for item in mutations
            ]
            removed_uniform = bool(
                _response_error_identity(removed_exact)
                == (409, "registration_replay_expired", "Idempotency-Key")
                and all(response.content == removed_exact.content for response in removed_responses)
                and _tables_projection_digest(engine, watched_tables)
                == removed_terminal
            )
            with factory() as session:
                removed_record = session.scalar(
                    select(RegistrationIdempotencyRecord).where(
                        RegistrationIdempotencyRecord.idempotency_key_hash
                        == registration_service.registration_idempotency_key_hash(
                            removed_key
                        )
                    )
                )
                removed_terminal_shape = bool(
                    removed_record is not None
                    and removed_record.state == "retired"
                    and removed_record.request_fingerprint is None
                    and removed_record.request_fingerprint_version is None
                )
        return {
            "key_request_bound": bool(all(live_conflicts)),
            "exact_replay_stable": replay_stable,
            "live_mutations_conflict": bool(all(live_conflicts)),
            "expired_mutations_uniform": expired_uniform and terminal_shape,
            "removed_mutations_uniform": (
                removed_uniform and removed_terminal_shape
            ),
            "zero_provider": sender.acceptance_count == 0,
            "zero_delta_after_terminal": bool(
                expired_uniform and removed_uniform
            ),
            "mutation_count": len(mutations),
        }
    finally:
        endpoint._now = original_now


def _registration_bootstrap_terminal_shape(
    factory: sessionmaker[Session],
    *,
    key: str,
    authority_id: Any,
) -> bool:
    from app.models.registration import (
        OtpChallenge,
        OtpOutbox,
        RegistrationIdempotencyRecord,
    )
    from app.services.registration_service import registration_idempotency_key_hash

    with factory() as session:
        record = session.scalar(
            select(RegistrationIdempotencyRecord).where(
                RegistrationIdempotencyRecord.idempotency_key_hash
                == registration_idempotency_key_hash(key)
            )
        )
        challenges = list(
            session.scalars(
                select(OtpChallenge).where(
                    OtpChallenge.authority_id == authority_id
                )
            )
        )
        outboxes = list(
            session.scalars(
                select(OtpOutbox)
                .join(OtpChallenge, OtpOutbox.challenge_id == OtpChallenge.id)
                .where(OtpChallenge.authority_id == authority_id)
            )
        )
        return bool(
            record is not None
            and record.state == "retired"
            and record.request_fingerprint is None
            and record.request_fingerprint_version is None
            and record.registration_id is None
            and record.outbox_id is None
            and challenges
            and all(
                challenge.delivery_state
                not in {"pending_delivery", "active"}
                for challenge in challenges
            )
            and outboxes
            and all(
                row.status == "void"
                and row.code_ct is None
                and row.destination_ct is None
                for row in outboxes
            )
        )


def _run_pending_registration_lifecycle_probe(engine: Engine) -> dict[str, Any]:
    """Expire/miss a real pending signup flow without leaving relay authority."""

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings
    from app.models.registration import OtpFlow
    from app.services.otp_flow_service import flow_token_hash

    original_now = endpoint._now
    fixed = datetime.now(timezone.utc)
    clock = {"now": fixed}
    endpoint._now = lambda: clock["now"]
    sender_holder: dict[str, Any] = {"sender": _CertifiedGateProvider()}
    app, factory = _build_behavior_app(engine, sender_holder)
    watched_tables = (
        "registration_idempotency_records",
        "otp_flows",
        "otp_purpose_authorities",
        "otp_challenges",
        "otp_outbox",
        "student_registrations",
    )

    def post(client: TestClient, key: str, body: Mapping[str, Any]):
        return client.post(
            "/api/v1/auth/student/register",
            headers={"Idempotency-Key": key},
            json=dict(body),
        )

    cases: list[bool] = []
    graph_terminal: list[bool] = []
    zero_provider: list[bool] = []
    zero_delta: list[bool] = []
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = settings.cors_origins[0]
            for index, mode in enumerate(("expired", "missing"), start=1):
                clock["now"] = fixed
                payload = _nyay4_registration_payload(
                    _behavior_fixture_mobile(f"pending_{mode}")
                )
                key = f"nyay4-real-{mode}-000{index}"
                failing = _CertifiedGateProvider(fail_before_accept_count=1)
                sender_holder["sender"] = failing
                created = post(client, key, payload)
                raw_token = client.cookies.get(settings.otp_flow_cookie_name)
                if created.status_code != 201 or not raw_token:
                    raise ProductGateFailure("pending lifecycle setup failed")
                inventory = _flow_private_inventory(factory, raw_token)
                if mode == "expired":
                    clock["now"] = fixed + timedelta(
                        seconds=settings.otp_flow_ttl_seconds + 1
                    )
                else:
                    with factory() as session:
                        flow = session.scalar(
                            select(OtpFlow).where(
                                OtpFlow.token_hash == flow_token_hash(raw_token)
                            )
                        )
                        if flow is None:
                            raise ProductGateFailure(
                                "pending lifecycle flow disappeared early"
                            )
                        session.delete(flow)
                        session.commit()
                exact = post(client, key, payload)
                terminal_digest = _tables_projection_digest(engine, watched_tables)
                calls_after_terminal = failing.calls
                mutations = [
                    post(client, key, mutation)
                    for mutation in _nyay4_canonical_mutations(payload)
                ]
                cases.append(
                    _response_error_identity(exact)
                    == (409, "registration_replay_expired", "Idempotency-Key")
                    and all(response.content == exact.content for response in mutations)
                )
                graph_terminal.append(
                    _registration_bootstrap_terminal_shape(
                        factory,
                        key=key,
                        authority_id=inventory["authority"],
                    )
                )
                zero_provider.append(failing.calls == calls_after_terminal)
                zero_delta.append(
                    _tables_projection_digest(engine, watched_tables)
                    == terminal_digest
                )
        return {
            "expired_mutations_uniform": cases[0],
            "missing_mutations_uniform": cases[1],
            "expired_graph_terminal": graph_terminal[0],
            "missing_graph_terminal": graph_terminal[1],
            "zero_provider": all(zero_provider),
            "zero_delta_after_terminal": all(zero_delta),
            "mutation_count_each": 12,
        }
    finally:
        endpoint._now = original_now


def _run_signup_verify_symmetry_probe(engine: Engine) -> dict[str, Any]:
    """Compare real/decoy signup verification at terminal boundaries."""

    from app.api.v1 import auth_student as endpoint
    from app.core.config import settings
    from app.models.registration import OtpFlow
    from app.services.otp_flow_service import flow_token_hash

    original_now = endpoint._now
    fixed = datetime.now(timezone.utc)
    clock = {"now": fixed}
    endpoint._now = lambda: clock["now"]
    sender = _CertifiedGateProvider()
    sender_holder: dict[str, Any] = {"sender": sender}
    app, factory = _build_behavior_app(engine, sender_holder)
    watched_tables = (
        "registration_idempotency_records",
        "otp_flows",
        "otp_purpose_authorities",
        "otp_challenges",
        "otp_outbox",
        "student_registrations",
    )
    real_payload = _nyay4_registration_payload(
        _behavior_fixture_mobile("verify_symmetry_real")
    )
    decoy_payload = _nyay4_registration_payload(
        _behavior_fixture_mobile("verify_symmetry_decoy")
    )
    try:
        _seed_active_registration(factory, decoy_payload["mobile"])
        with (
            TestClient(app, raise_server_exceptions=False) as real_client,
            TestClient(app, raise_server_exceptions=False) as decoy_client,
        ):
            for client in (real_client, decoy_client):
                client.headers["Origin"] = settings.cors_origins[0]
            real = real_client.post(
                "/api/v1/auth/student/register",
                headers={"Idempotency-Key": "nyay4-real-expiry-0001"},
                json=real_payload,
            )
            decoy = decoy_client.post(
                "/api/v1/auth/student/register",
                headers={"Idempotency-Key": "nyay4-decoy-expiry-0001"},
                json=decoy_payload,
            )
            real_token = real_client.cookies.get(settings.otp_flow_cookie_name)
            decoy_token = decoy_client.cookies.get(settings.otp_flow_cookie_name)
            if (
                real.status_code != 201
                or decoy.status_code != 201
                or not real_token
                or not decoy_token
            ):
                raise ProductGateFailure("verify symmetry setup failed")
            calls_before = sender.calls
            clock["now"] = fixed + timedelta(
                seconds=settings.otp_challenge_ttl_seconds + 1
            )
            before_real = _tables_projection_digest(engine, watched_tables)
            real_expired = real_client.post(
                "/api/v1/auth/student/otp/verify", json={"code": "000000"}
            )
            after_real = _tables_projection_digest(engine, watched_tables)
            before_decoy = after_real
            decoy_expired = decoy_client.post(
                "/api/v1/auth/student/otp/verify", json={"code": "000000"}
            )
            after_decoy = _tables_projection_digest(engine, watched_tables)

            # Terminal consumed capabilities share one byte-identical bounded
            # response and cannot consume another attempt or mutate authority.
            with factory() as session:
                for token in (real_token, decoy_token):
                    flow = session.scalar(
                        select(OtpFlow).where(
                            OtpFlow.token_hash == flow_token_hash(token)
                        )
                    )
                    if flow is None:
                        raise ProductGateFailure("verify symmetry flow disappeared")
                    flow.state = "consumed"
                    flow.consumed_at = clock["now"]
                    flow.destination_masked_ct = None
                    flow.key_version = None
                session.commit()
            consumed_before = _tables_projection_digest(engine, watched_tables)
            real_consumed = real_client.post(
                "/api/v1/auth/student/otp/verify", json={"code": "000000"}
            )
            consumed_mid = _tables_projection_digest(engine, watched_tables)
            decoy_consumed = decoy_client.post(
                "/api/v1/auth/student/otp/verify", json={"code": "000000"}
            )
            consumed_after = _tables_projection_digest(engine, watched_tables)
        return {
            "expired_status": real_expired.status_code,
            "expired_code": _response_error_identity(real_expired)[1],
            "expired_values_equal": real_expired.content == decoy_expired.content,
            "expired_real_zero_delta": before_real == after_real,
            "expired_decoy_zero_delta": before_decoy == after_decoy,
            "consumed_status": real_consumed.status_code,
            "consumed_code": _response_error_identity(real_consumed)[1],
            "consumed_values_equal": real_consumed.content == decoy_consumed.content,
            "consumed_real_zero_delta": consumed_before == consumed_mid,
            "consumed_decoy_zero_delta": consumed_mid == consumed_after,
            "provider_delta": sender.calls - calls_before,
        }
    finally:
        endpoint._now = original_now


def _run_maintenance_entrypoint_probe(
    engine: Engine,
    *,
    legacy_outbox_ids: tuple[uuid.UUID, uuid.UUID],
) -> dict[str, Any]:
    """Exercise the scheduled retention entrypoint over every NYAY-4 surface.

    The worker, rather than its individual helpers, owns the assertion.  Test
    rows deliberately include one expired signup capability, one old and one
    recent abuse bucket, and one old and one recent grandfathered terminal
    destination.  The returned observation is aggregate-only.
    """

    from app.core.config import settings
    from app.core.crypto import keyed_hash
    from app.models.registration import (
        OtpFlow,
        OtpOutbox,
        OtpRateLimitBucket,
        RegistrationIdempotencyRecord,
    )
    from app.services import otp_flow_service, registration_service
    from app.workers import retention as retention_worker

    now = datetime.now(timezone.utc)
    old = now - timedelta(
        seconds=max(
            settings.otp_rate_bucket_retention_seconds,
            settings.otp_outbox_legacy_destination_retention_seconds,
        )
        + 60
    )
    sender_holder: dict[str, Any] = {"sender": _CertifiedGateProvider()}
    app, factory = _build_behavior_app(engine, sender_holder)
    origin = settings.cors_origins[0]
    expired_payload = _nyay4_registration_payload(
        _behavior_fixture_mobile("maintenance_expired")
    )
    expired_key = "nyay4-maintenance-expired-0001"
    recent_mobile = _behavior_fixture_mobile("maintenance_recent")
    preserved_mobile = _behavior_fixture_mobile("maintenance_preserved")
    original_get_sessionmaker = retention_worker.get_sessionmaker

    try:
        # A duplicate signup produces a durable neutralized key reservation and
        # a browser flow without provider I/O. Retention must expire both as a
        # uniform, non-reusable tombstone.
        _seed_active_registration(factory, expired_payload["mobile"])
        _seed_active_registration(factory, recent_mobile)
        _seed_active_registration(factory, preserved_mobile)
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = origin
            expired_start = client.post(
                "/api/v1/auth/student/register",
                headers={"Idempotency-Key": expired_key},
                json=expired_payload,
            )
            expired_token = client.cookies.get(settings.otp_flow_cookie_name)
            if expired_start.status_code != 201 or not expired_token:
                raise ProductGateFailure("maintenance expired-flow setup failed")

        # Two ordinary delivered login rows supply an aged grandfathered
        # ciphertext and a recent control that must remain byte-present.
        login_tokens: list[str] = []
        for mobile in (recent_mobile, preserved_mobile):
            with TestClient(app, raise_server_exceptions=False) as client:
                client.headers["Origin"] = origin
                started = client.post(
                    "/api/v1/auth/student/login/otp/start",
                    json={"mobile": mobile},
                )
                raw_token = client.cookies.get(settings.otp_flow_cookie_name)
                if started.status_code != 202 or not raw_token:
                    raise ProductGateFailure("maintenance outbox setup failed")
                login_tokens.append(raw_token)

        with factory() as session:
            expired_flow = session.scalar(
                select(OtpFlow).where(
                    OtpFlow.token_hash
                    == otp_flow_service.flow_token_hash(expired_token)
                )
            )
            recent_flow = session.scalar(
                select(OtpFlow).where(
                    OtpFlow.token_hash
                    == otp_flow_service.flow_token_hash(login_tokens[1])
                )
            )
            if expired_flow is None or recent_flow is None:
                raise ProductGateFailure("maintenance flow graph disappeared")
            expired_flow.expires_at = old
            expired_flow_id = expired_flow.id
            recent_flow_id = recent_flow.id

            grandfathered_ids = set(
                session.scalars(
                    select(OtpOutbox.id).where(
                        OtpOutbox.legacy_destination_retained.is_(True)
                    )
                )
            )
            aged_outbox = session.get(OtpOutbox, legacy_outbox_ids[0])
            recent_outbox = session.get(OtpOutbox, legacy_outbox_ids[1])
            if not (
                grandfathered_ids == set(legacy_outbox_ids)
                and aged_outbox is not None
                and recent_outbox is not None
                and aged_outbox.status == recent_outbox.status == "sent"
                and aged_outbox.code_ct is None
                and recent_outbox.code_ct is None
                and aged_outbox.destination_ct is not None
                and recent_outbox.destination_ct is not None
                and aged_outbox.legacy_destination_retained is True
                and recent_outbox.legacy_destination_retained is True
                and len(aged_outbox.provider_idempotency_key) == 64
                and len(recent_outbox.provider_idempotency_key) == 64
            ):
                raise ProductGateFailure(
                    "maintenance grandfathered migration fixture is invalid"
                )
            aged_outbox.updated_at = old
            recent_outbox.updated_at = now
            aged_outbox_id = aged_outbox.id
            recent_outbox_id = recent_outbox.id

            aged_bucket = OtpRateLimitBucket(
                scope="identity",
                subject_hash=keyed_hash("nyay4-maintenance-aged-bucket"),
                action="issue",
                window_started_at=old,
                window_seconds=60,
                request_count=1,
                max_requests=2,
                created_at=old,
                updated_at=old,
            )
            recent_bucket = OtpRateLimitBucket(
                scope="identity",
                subject_hash=keyed_hash("nyay4-maintenance-recent-bucket"),
                action="issue",
                window_started_at=now,
                window_seconds=60,
                request_count=1,
                max_requests=2,
                created_at=now,
                updated_at=now,
            )
            session.add_all((aged_bucket, recent_bucket))
            session.commit()
            aged_bucket_id = aged_bucket.id
            recent_bucket_id = recent_bucket.id

        # This is the production scheduled maintenance seam. Override only its
        # database factory so the worker operates on the isolated probe DB.
        retention_worker.get_sessionmaker = lambda: factory
        counts = retention_worker.run_retention_once()

        with factory() as session:
            aged_bucket_absent = session.get(OtpRateLimitBucket, aged_bucket_id) is None
            recent_bucket_present = (
                session.get(OtpRateLimitBucket, recent_bucket_id) is not None
            )
            aged_row = session.get(OtpOutbox, aged_outbox_id)
            recent_row = session.get(OtpOutbox, recent_outbox_id)
            terminal_flow = session.get(OtpFlow, expired_flow_id)
            live_flow = session.get(OtpFlow, recent_flow_id)
            ledger = session.scalar(
                select(RegistrationIdempotencyRecord).where(
                    RegistrationIdempotencyRecord.idempotency_key_hash
                    == registration_service.registration_idempotency_key_hash(
                        expired_key
                    )
                )
            )
            tombstone_shape = bool(
                terminal_flow is not None
                and terminal_flow.state == "expired"
                and terminal_flow.destination_masked_ct is None
                and terminal_flow.key_version is None
                and ledger is not None
                and ledger.state == "retired"
                and ledger.request_fingerprint is None
                and ledger.request_fingerprint_version is None
                and ledger.registration_id is None
                and ledger.outbox_id is None
            )
            aged_destination_erased = bool(
                aged_row is not None
                and aged_row.destination_ct is None
                and aged_row.legacy_destination_retained is False
            )
            recent_destination_preserved = bool(
                recent_row is not None
                and recent_row.destination_ct is not None
                and recent_row.legacy_destination_retained is True
            )
            recent_flow_preserved = bool(
                live_flow is not None
                and live_flow.state in {"pending", "code_sent", "locked"}
            )

        # The public key reservation remains unusable after maintenance. Exact
        # and mutated payloads share one bounded response with no provider call.
        calls_before = sender_holder["sender"].calls
        with TestClient(app, raise_server_exceptions=False) as client:
            client.headers["Origin"] = origin
            exact = client.post(
                "/api/v1/auth/student/register",
                headers={"Idempotency-Key": expired_key},
                json=expired_payload,
            )
            mutation = client.post(
                "/api/v1/auth/student/register",
                headers={"Idempotency-Key": expired_key},
                json=_nyay4_canonical_mutations(expired_payload)[0],
            )
        expected_count_keys = {
            "registrations",
            "otp_challenges",
            "recovery_sessions",
            "otp_flows",
            "otp_terminal_flows",
            "otp_authorities",
            "otp_terminal_challenges",
            "otp_terminal_outboxes",
            "otp_expired_registrations",
            "otp_rate_limit_buckets",
            "otp_legacy_destinations",
        }
        return {
            "entrypoint_executed": True,
            "counts_aggregate_only": bool(
                set(counts) == expected_count_keys
                and all(type(value) is int and value >= 0 for value in counts.values())
            ),
            "aged_bucket_purged": aged_bucket_absent,
            "recent_bucket_preserved": recent_bucket_present,
            "aged_legacy_destination_purged": aged_destination_erased,
            "recent_legacy_destination_preserved": recent_destination_preserved,
            "expired_flow_terminalized": tombstone_shape,
            "recent_flow_preserved": recent_flow_preserved,
            "expired_key_reuse_blocked": bool(
                _response_error_identity(exact)
                == (409, "registration_replay_expired", "Idempotency-Key")
                and exact.content == mutation.content
                and sender_holder["sender"].calls == calls_before
            ),
        }
    finally:
        retention_worker.get_sessionmaker = original_get_sessionmaker


def _clear_behavior_rate_buckets(engine: Engine) -> None:
    """Isolate independent behavior cases without weakening any case budget."""

    with engine.begin() as connection:
        connection.execute(text("DELETE FROM otp_rate_limit_buckets"))


def _run_behavior_probe(scratch_url: str) -> dict[str, Mapping[str, Any]]:
    """Execute the full real-service behavior matrix on one exact-head DB."""

    from app.core.config import settings
    from app.core.crypto import KeyRing, override_keyring

    original_environment = settings.app_env
    engine: Engine | None = None
    override_keyring(
        KeyRing(
            active_version="v1",
            secrets={"v1": os.urandom(32)},
            lookup_secret=os.urandom(32),
        )
    )
    settings.app_env = "testing"
    try:
        parent = _run_alembic(scratch_url, "upgrade", PREVIOUS_REVISION)
        if parent["returncode"] != 0:
            raise ProductGateFailure("behavior probe could not install exact 0018")
        fixture_now = datetime.now(timezone.utc)
        fixture_old = fixture_now - timedelta(
            seconds=max(
                settings.otp_rate_bucket_retention_seconds,
                settings.otp_outbox_legacy_destination_retention_seconds,
            )
            + 60
        )
        parent_engine = create_engine(scratch_url, poolclass=NullPool)
        try:
            legacy_outbox_ids = _seed_behavior_legacy_destinations(
                parent_engine,
                aged_at=fixture_old,
                recent_at=fixture_now,
            )
        finally:
            parent_engine.dispose()
        upgrade = _run_alembic(scratch_url, "upgrade", PINNED_HEAD)
        if upgrade["returncode"] != 0:
            raise ProductGateFailure("behavior probe could not install exact 0019")
        engine = create_engine(scratch_url, poolclass=NullPool)
        schema = _exact_schema_observation(engine)

        lockout = _run_lockout_probe(engine)
        _clear_behavior_rate_buckets(engine)

        concurrent_verify = _run_concurrent_verify_probe(engine)
        concurrent_resend = _run_concurrent_resend_probe(engine)

        expired_active = _run_expired_active_resend_probe(engine)
        _clear_behavior_rate_buckets(engine)
        alternation = _run_start_resend_alternation_probe(engine)
        _clear_behavior_rate_buckets(engine)
        resend = _compose_resend_observation(
            concurrent_resend, expired_active, alternation
        )

        failed_resend = _run_failed_resend_probe(engine)
        _clear_behavior_rate_buckets(engine)

        cookie_base = _run_cookie_projection_probe(engine)
        _clear_behavior_rate_buckets(engine)
        initial_exhaustion = _run_initial_exhaustion_probe(engine)
        _clear_behavior_rate_buckets(engine)
        neutralized = _run_neutralized_registration_probe(engine)
        _clear_behavior_rate_buckets(engine)
        pending = _run_pending_registration_lifecycle_probe(engine)
        _clear_behavior_rate_buckets(engine)
        verify_symmetry = _run_signup_verify_symmetry_probe(engine)
        _clear_behavior_rate_buckets(engine)
        neutralized_race = _run_neutralized_concurrency_probe(engine)
        _clear_behavior_rate_buckets(engine)
        cookie = _compose_cookie_observation(
            cookie_base,
            initial_exhaustion,
            neutralized,
            pending,
            verify_symmetry,
            neutralized_concurrent_mismatch_linearized=bool(
                neutralized_race.get("linearized") is True
                and neutralized_race.get("deadlocks") == 0
            ),
        )

        metadata = _run_metadata_probe(engine)
        _clear_behavior_rate_buckets(engine)
        claim = _run_claim_concurrency_probe(engine)
        provider = _run_provider_idempotency_probe(engine)
        retry_base = _run_retry_lease_probe(engine)

        rate_base = _run_rate_budget_probe(engine)
        maintenance = _run_maintenance_entrypoint_probe(
            engine,
            legacy_outbox_ids=legacy_outbox_ids,
        )
        rate = _compose_rate_observation(rate_base, maintenance)
        retry = _compose_retry_observation(
            retry_base, initial_exhaustion, maintenance
        )
        return {
            "schema": schema,
            "lockout": lockout,
            "verify": concurrent_verify,
            "resend": resend,
            "failed_resend": failed_resend,
            "rate": rate,
            "cookie": cookie,
            "metadata": metadata,
            "claim": claim,
            "provider": provider,
            "retry": retry,
        }
    finally:
        settings.app_env = original_environment
        override_keyring(None)
        if engine is not None:
            engine.dispose()


def _run_harness_source_probe() -> dict[str, bool]:
    """Run the sealed frontend authority tests and pin final DB-gate wiring."""

    root = BACKEND.parent
    frontend = root / "frontend"

    def command_passes(arguments: list[str], *, cwd: Path) -> bool:
        try:
            completed = subprocess.run(
                arguments,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
                env={**os.environ, "CI": "true"},
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return completed.returncode == 0

    authority_tests = command_passes(
        [
            "npm",
            "test",
            "--",
            "--run",
            "src/features/student/lib/otpAuthority.contract.test.ts",
        ],
        cwd=frontend,
    )
    browser_contract_tests = command_passes(
        [
            "npm",
            "test",
            "--",
            "--run",
            "scripts/lib/nyay4-otp-runner-contract.test.mjs",
        ],
        cwd=frontend,
    )
    try:
        package = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
        package_command_exact = bool(
            package.get("scripts", {}).get("qa:nyay4:otp-negative")
            == "node scripts/nyay4-otp-browser-negative.mjs"
            and "preqa:nyay4:otp-negative" not in package.get("scripts", {})
            and "postqa:nyay4:otp-negative" not in package.get("scripts", {})
        )
        workflow = (
            root / ".github/workflows/wave3-credential-trust-gate.yml"
        ).read_text(encoding="utf-8")
        browser_ci_unconditional = bool(
            workflow.count("run: npm run qa:nyay4:otp-negative") == 1
            and "npm run qa:nyay4:otp-negative || true" not in workflow
            and "continue-on-error: true" not in workflow
        )
    except (OSError, TypeError, ValueError):
        package_command_exact = False
        browser_ci_unconditional = False

    expected_native = (
        'NYAY4_POSTGRES_GATE=1 "$PY" scripts/nyay4_postgres_otp_gate.py '
        '--execute --database-url "$DATABASE_URL" '
        '--output test-results/nyay4-postgres/summary.json'
    )
    try:
        db_gate_source = (BACKEND / "scripts/db_gate.sh").read_text(
            encoding="utf-8"
        )
        executable = re.sub(r"\\\s*\n", " ", db_gate_source)
        commands = [
            " ".join(line.strip().split())
            for line in executable.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        nyay17_position = next(
            index
            for index, command in enumerate(commands)
            if "scripts/nyay17_postgres_idempotency_gate.py" in command
        )
        nyay4_positions = [
            index
            for index, command in enumerate(commands)
            if "scripts/nyay4_postgres_otp_gate.py" in command
        ]
        gate_command_present = bool(
            len(nyay4_positions) == 1
            and nyay4_positions[0] > nyay17_position
            and commands[nyay4_positions[0]] == expected_native
            and commands[-1] == expected_native
            and "set -euo pipefail" in commands
        )
    except (OSError, StopIteration):
        gate_command_present = False

    return {
        "frontend_server_authority": bool(
            authority_tests
            and browser_contract_tests
            and package_command_exact
            and browser_ci_unconditional
        ),
        "gate_command_present": gate_command_present,
    }


def run_gate(base: URL) -> dict[str, Any]:
    """Execute the exact three-scratch authoritative release gate."""

    runtime = _runtime_probe(base)
    if not _runtime_observation_passes(runtime):
        raise Blocked("PostgreSQL 16 plus pgvector is required")
    _require_core_contract()
    manager = _ScratchDatabaseManager(base)
    migration: Mapping[str, Any] | None = None
    populated: Mapping[str, Any] | None = None
    behavior: Mapping[str, Mapping[str, Any]] | None = None
    try:
        migration = manager.run(
            "migration_lifecycle", _run_migration_lifecycle_probe
        )
        populated = manager.run(
            "migration_populated", _run_populated_migration_probe
        )
        behavior = manager.run("behavior", _run_behavior_probe)
    finally:
        cleanup = manager.summary()
    if (
        migration is None
        or populated is None
        or behavior is None
        or cleanup["all_created_removed"] is not True
    ):
        raise ProductGateFailure("NYAY-4 scratch execution or cleanup failed")

    config = _run_configuration_probe()
    source = _run_harness_source_probe()
    placeholder_mutants = {
        identifier: True for identifier in REQUIRED_MUTANT_IDS
    }
    harness: dict[str, Any] = {
        "mutants": placeholder_mutants,
        "privacy_findings": 0,
        "privacy_scanned": True,
        "scratch_created": cleanup["created"],
        "scratch_removed": cleanup["removed"],
        "scratch_failed": cleanup["failed"],
        "scratch_purposes": cleanup["purposes"],
        "scratch_inventory_match": cleanup["inventory_match"],
        "all_created_removed": cleanup["all_created_removed"],
        "frontend_server_authority": source["frontend_server_authority"],
        "gate_command_present": source["gate_command_present"],
    }
    mutant_inputs = {
        "schema": behavior["schema"],
        "lockout": behavior["lockout"],
        "verify": behavior["verify"],
        "resend": behavior["resend"],
        "failed_resend": behavior["failed_resend"],
        "rate": behavior["rate"],
        "cookie": behavior["cookie"],
        "claim": behavior["claim"],
        "provider": behavior["provider"],
        "retry": behavior["retry"],
        "config": config,
        "harness": harness,
    }
    harness["mutants"] = _seeded_mutant_results(mutant_inputs)

    privacy_observations = _privacy_observation_projection(
        runtime=runtime,
        migration=migration,
        populated=populated,
        behavior=behavior,
        config=config,
        harness=harness,
    )
    findings = _privacy_findings(privacy_observations)
    harness["privacy_findings"] = len(findings)

    assertion_rows = [
        {
            "id": REQUIRED_ASSERTION_IDS[0],
            "passed": _runtime_observation_passes(runtime),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[1],
            "passed": _migration_observation_passes(migration),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[2],
            "passed": _populated_migration_observation_passes(populated),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[3],
            "passed": _schema_observation_passes(behavior["schema"]),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[4],
            "passed": _lockout_observation_passes(behavior["lockout"]),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[5],
            "passed": _concurrent_verify_observation_passes(
                behavior["verify"]
            ),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[6],
            "passed": _resend_observation_passes(behavior["resend"]),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[7],
            "passed": _failed_resend_observation_passes(
                behavior["failed_resend"]
            ),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[8],
            "passed": _rate_observation_passes(behavior["rate"]),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[9],
            "passed": _cookie_observation_passes(behavior["cookie"]),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[10],
            "passed": _metadata_observation_passes(behavior["metadata"]),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[11],
            "passed": _claim_observation_passes(behavior["claim"]),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[12],
            "passed": _provider_observation_passes(behavior["provider"]),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[13],
            "passed": _retry_observation_passes(behavior["retry"]),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[14],
            "passed": _config_observation_passes(config),
        },
        {
            "id": REQUIRED_ASSERTION_IDS[15],
            "passed": _harness_observation_passes(harness),
        },
    ]
    evaluated = _evaluate_assertions(assertion_rows)
    killed = sum(harness["mutants"].values())
    report = {
        "gate": "nyay4_postgres_otp",
        "status": "PASS" if evaluated["overall_pass"] else "FAIL",
        "executed": True,
        "head": PINNED_HEAD,
        "postgres_major": runtime["postgres_major"],
        "pgvector_present": runtime["pgvector_present"],
        "assertion_ids": list(REQUIRED_ASSERTION_IDS),
        "assertions": evaluated,
        "mutants": {"required": len(REQUIRED_MUTANT_IDS), "killed": killed},
        "scratch": {
            "created": cleanup["created"],
            "removed": cleanup["removed"],
            "failed": cleanup["failed"],
            "inventory_match": cleanup["inventory_match"],
        },
        "provider_contract": {
            "certified": behavior["provider"]["provider_contract_certified"],
            "acceptances": behavior["provider"]["provider_acceptances"],
            "real_provider_exactly_once_claimed": behavior["provider"][
                "real_provider_exactly_once_claimed"
            ],
        },
        "privacy_findings": len(findings),
        "limitations": [
            "provider acceptance is exactly-once only under the named "
            "idempotent provider contract",
            "no uninstrumented network-syscall absence is claimed",
        ],
    }
    if _privacy_findings(report):
        raise ProductGateFailure("NYAY-4 aggregate report privacy scan failed")
    return report


def _blocked_report(reason: str) -> dict[str, Any]:
    return {
        "gate": "nyay4_postgres_otp",
        "status": "BLOCKED",
        "executed": False,
        "reason": reason,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--database-url", default=os.getenv("NYAY4_POSTGRES_ADMIN_URL"))
    parser.add_argument("--output")
    arguments = parser.parse_args(argv)

    if not arguments.execute or os.getenv(OPT_IN_ENV) != "1":
        report = _blocked_report("explicit execution opt-in is required")
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        return BLOCKED_EXIT
    try:
        if not arguments.database_url:
            raise Blocked("an explicit loopback PostgreSQL control URL is required")
        base = _safe_local_postgres_url(arguments.database_url)
        report = run_gate(base)
        exit_code = 0 if report.get("status") == "PASS" else 1
    except Blocked as exc:
        report = _blocked_report(str(exc))
        exit_code = BLOCKED_EXIT
    except Exception:  # never copy exception/URL/provider details into evidence
        report = {
            "gate": "nyay4_postgres_otp",
            "status": "FAIL",
            "executed": True,
            "reason": "authoritative gate rejected product or harness state",
        }
        exit_code = 1

    findings = _privacy_findings(report)
    if findings:
        report = {
            "gate": "nyay4_postgres_otp",
            "status": "FAIL",
            "executed": report.get("executed") is True,
            "reason": "aggregate evidence privacy validation failed",
            "privacy_findings": len(findings),
        }
        exit_code = 1
    serialized = json.dumps(report, sort_keys=True, separators=(",", ":"))
    if arguments.output:
        Path(arguments.output).write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
