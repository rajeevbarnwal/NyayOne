"""Pure harness tests for the opt-in NYAY-2 PostgreSQL authorization gate.

These tests prove fail-closed routing, exact assertion inventory, cleanup, and
aggregate evidence privacy.  They do not claim PostgreSQL/API behavior; that
evidence comes only from executing ``scripts/nyay2_postgres_authorization_gate``
against the disposable PostgreSQL 16 + pgvector runtime.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import scripts.nyay2_postgres_authorization_gate as gate
from scripts.nyay2_postgres_authorization_gate import (
    BLOCKED_EXIT,
    LIBPQ_AMBIENT_KEYS,
    ORIGIN_MATRIX_CASES,
    REQUIRED_ASSERTION_IDS,
    SIGNUP_ACCEPTED_STATUS,
    Blocked,
    ProductGateFailure,
    ScratchCleanupFailure,
    _ScratchDatabaseManager,
    _business_state_digest,
    _bootstrap_expiry_passes,
    _cookie_contract_passes,
    _evaluate_assertions,
    _is_postgresql_16_with_pgvector,
    _named_cookie_contract,
    _otp_resend_payload,
    _otp_verify_payload,
    _private_capability_delta_is_exact,
    _private_capability_snapshot,
    _private_capability_state_unchanged,
    _privacy_findings,
    _private_decoy_flow_is_bound,
    _public_otp_responses_match,
    _raw_values_absent_from_json,
    _reject_ambient_libpq_environment,
    _require_private_signup_flow,
    _safe_local_postgres_url,
    _safe_response_object,
    _safe_response_signature,
    _seed_actor,
    _seed_private_signup_flow,
    _signup_registration_headers,
    _signup_registration_payload,
    _trusted_mutation_headers,
    _unsafe_flow_graph_for_mutation,
)


@pytest.fixture(autouse=True)
def _without_ambient_libpq_authority(monkeypatch):
    for key in tuple(gate.os.environ):
        if key in LIBPQ_AMBIENT_KEYS or key.startswith("PGSSL"):
            monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    "key",
    tuple(sorted(LIBPQ_AMBIENT_KEYS))
    + ("PGSSLMODE", "PGSSLCERT", "PGSSLKEY", "PGSSLROOTCERT"),
)
def test_ambient_libpq_authority_is_rejected_without_value_disclosure(monkeypatch, key):
    monkeypatch.setenv(key, "sensitive-value-must-not-be-reported")
    with pytest.raises(
        Blocked,
        match="ambient libpq routing or credential environment is not allowed",
    ) as caught:
        _reject_ambient_libpq_environment()
    assert "sensitive-value" not in str(caught.value)


@pytest.mark.parametrize(
    "url",
    (
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?host=evil.example",
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?hostaddr=203.0.113.7",
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?port=6543",
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?host=%2Ftmp",
        "postgresql+psycopg://qa:secret@localhost:5432/postgres?options=-cstatement_timeout%3D0",
        "postgresql+psycopg:///postgres?host=%2Fvar%2Frun%2Fpostgresql",
    ),
)
def test_safe_url_rejects_every_query_routing_surface(url):
    with pytest.raises(Blocked, match="rejects PostgreSQL URL queries"):
        _safe_local_postgres_url(url)


@pytest.mark.parametrize(
    "url",
    (
        "postgresql+psycopg://qa:secret@localhost:5432/postgres",
        "postgresql+psycopg://qa:secret@127.0.0.1:5432/postgres",
        "postgresql+psycopg://qa:secret@[::1]:5432/postgres",
    ),
)
def test_safe_url_accepts_only_query_free_loopback_authority(url):
    parsed = _safe_local_postgres_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert not parsed.query


@pytest.mark.parametrize(
    "url, message",
    (
        ("sqlite:///tmp/qa.db", "PostgreSQL URL is required"),
        (
            "postgresql+psycopg://qa:secret@example.invalid:5432/postgres",
            "accepts loopback PostgreSQL only",
        ),
        (
            "postgresql+psycopg://qa:p%40ss@localhost:5432/postgres",
            "authority is ambiguous",
        ),
        (
            "postgresql+psycopg://qa:secret@localhost@evil.invalid:5432/postgres",
            "authority is ambiguous",
        ),
        (
            "postgresql+psycopg://qa:secret@local%68ost:5432/postgres",
            "authority is ambiguous",
        ),
    ),
)
def test_safe_url_rejects_dialect_remote_and_ambiguous_authority(url, message):
    with pytest.raises(Blocked, match=message):
        _safe_local_postgres_url(url)


def _passing_assertions() -> list[dict]:
    return [
        {"id": identifier, "passed": True, "metrics": {}}
        for identifier in REQUIRED_ASSERTION_IDS
    ]


def test_evaluator_requires_exact_inventory_and_every_true():
    evaluation = _evaluate_assertions(_passing_assertions())
    assert evaluation == {
        "exact_inventory": True,
        "required": len(REQUIRED_ASSERTION_IDS),
        "passed": len(REQUIRED_ASSERTION_IDS),
        "failed": [],
        "inventory_failures": {
            "missing": 0,
            "extra": 0,
            "duplicate": 0,
            "reordered": False,
        },
        "overall_pass": True,
    }


@pytest.mark.parametrize(
    "version_num, vector_version, expected",
    (
        (159999, "0.8.6", False),
        (160000, "0.8.6", True),
        (169999, "0.8.6", True),
        (170000, "0.8.6", False),
        (180000, "0.8.6", False),
        (160000, None, False),
        (160000, "", False),
    ),
)
def test_runtime_is_pinned_to_postgresql_major_16_with_pgvector(
    version_num, vector_version, expected
):
    assert _is_postgresql_16_with_pgvector(version_num, vector_version) is expected


@pytest.mark.parametrize("identifier", REQUIRED_ASSERTION_IDS)
def test_each_required_assertion_independently_fails_the_gate(identifier):
    assertions = _passing_assertions()
    next(item for item in assertions if item["id"] == identifier)["passed"] = False
    evaluation = _evaluate_assertions(assertions)
    assert evaluation["exact_inventory"] is True
    assert evaluation["overall_pass"] is False
    assert evaluation["failed"] == [identifier]


def test_evaluator_rejects_missing_duplicate_and_substituted_assertions():
    missing = _passing_assertions()[:-1]
    duplicate = _passing_assertions() + [_passing_assertions()[0]]
    substituted = _passing_assertions()
    substituted[-1] = {
        "id": "OPTIONAL-SUBSTITUTE",
        "passed": True,
        "metrics": {},
    }
    for assertions in (missing, duplicate, substituted):
        evaluation = _evaluate_assertions(assertions)
        assert evaluation["exact_inventory"] is False
        assert evaluation["overall_pass"] is False


def test_evaluator_rejects_reordered_exact_assertion_set():
    assertions = _passing_assertions()
    assertions[0], assertions[1] = assertions[1], assertions[0]
    evaluation = _evaluate_assertions(assertions)
    assert evaluation["exact_inventory"] is False
    assert evaluation["inventory_failures"] == {
        "missing": 0,
        "extra": 0,
        "duplicate": 0,
        "reordered": True,
    }
    assert evaluation["overall_pass"] is False


def _passing_bootstrap_expiry_observation() -> dict:
    return {
        "resend_status": 401,
        "resend_code": "otp_flow_unavailable",
        "verify_status": 401,
        "verify_code": "otp_failed",
        "challenge_delta": 0,
        "outbox_delta": 0,
        "delivery_delta": 0,
        "session_delta": 0,
        "audit_delta": 0,
        "all_security_row_deltas_zero": True,
        "business_state_unchanged": True,
        "private_capability_state_unchanged": True,
        "cookie_issued": False,
    }


def test_bootstrap_expiry_evaluator_accepts_only_exact_bounded_no_delta_case():
    assert _bootstrap_expiry_passes(_passing_bootstrap_expiry_observation())


@pytest.mark.parametrize(
    "field, unsafe_value",
    (
        ("resend_status", 202),
        ("resend_code", "resend_cooldown"),
        ("verify_status", 200),
        ("verify_code", "incorrect_otp"),
        ("challenge_delta", 1),
        ("outbox_delta", 1),
        ("delivery_delta", 1),
        ("session_delta", 1),
        ("audit_delta", 1),
        ("all_security_row_deltas_zero", False),
        ("business_state_unchanged", False),
        ("private_capability_state_unchanged", False),
        ("cookie_issued", True),
    ),
)
def test_each_bootstrap_expiry_false_green_mutation_is_rejected(field, unsafe_value):
    observation = _passing_bootstrap_expiry_observation()
    observation[field] = unsafe_value
    assert _bootstrap_expiry_passes(observation) is False


def test_cookie_flow_request_payloads_exclude_registration_uuid_authority():
    assert _otp_resend_payload() == {}
    assert _otp_verify_payload("123456") == {"code": "123456"}
    assert "registration_id" not in _otp_verify_payload("123456")


def test_named_cookie_contract_is_exact_private_and_never_returns_its_value():
    raw_token = "private-cookie-capability-must-not-be-serialized"
    response = _Response(
        201,
        {"status": "pending"},
        header_items=(
            ("Cache-Control", "private, no-store"),
            ("Vary", "Cookie"),
            ("Content-Type", "application/json"),
            (
                "Set-Cookie",
                "nyayone_otp_flow="
                f"{raw_token}; HttpOnly; Max-Age=300; Path=/api/v1; "
                "SameSite=strict",
            ),
        ),
    )

    contract = _named_cookie_contract(
        response,
        "nyayone_otp_flow",
        expected_value=raw_token,
    )

    assert contract == {
        "present_once": True,
        "value_matches": True,
        "httponly": True,
        "host_only": True,
        "expected_path": True,
        "samesite_strict": True,
        "persistent": True,
    }
    assert _cookie_contract_passes(contract)
    assert raw_token not in json.dumps(contract, sort_keys=True)


def test_named_session_cookie_cannot_borrow_httponly_from_flow_cookie_deletion():
    raw_session = "private-session-capability-must-not-be-serialized"
    response = _Response(
        200,
        {"status": "authenticated"},
        header_items=(
            (
                "Set-Cookie",
                "nyayone_session="
                f"{raw_session}; Max-Age=3600; Path=/api/v1; SameSite=strict",
            ),
            (
                "Set-Cookie",
                "nyayone_otp_flow=; HttpOnly; Max-Age=0; Path=/api/v1; "
                "SameSite=strict",
            ),
        ),
    )

    session_contract = _named_cookie_contract(
        response,
        "nyayone_session",
        expected_value=raw_session,
    )

    assert session_contract["httponly"] is False
    assert _cookie_contract_passes(session_contract) is False
    assert raw_session not in json.dumps(session_contract, sort_keys=True)


def test_named_cookie_contract_fails_closed_on_duplicate_or_scoped_cookie():
    raw_token = "private-cookie-capability"
    duplicate = _Response(
        201,
        {},
        header_items=(
            (
                "Set-Cookie",
                f"flow={raw_token}; HttpOnly; Path=/api/v1; SameSite=strict",
            ),
            (
                "Set-Cookie",
                f"flow={raw_token}; HttpOnly; Path=/api/v1; SameSite=strict",
            ),
        ),
    )
    scoped = _Response(
        201,
        {},
        header_items=(
            (
                "Set-Cookie",
                "flow="
                f"{raw_token}; Domain=example.invalid; HttpOnly; Path=/; "
                "SameSite=lax",
            ),
        ),
    )

    assert not _cookie_contract_passes(
        _named_cookie_contract(duplicate, "flow", expected_value=raw_token)
    )
    assert not _cookie_contract_passes(
        _named_cookie_contract(scoped, "flow", expected_value=raw_token)
    )


@pytest.mark.parametrize(
    "httponly_attribute",
    (
        "HttpOnly=false",
        "HttpOnly=0",
        "HttpOnly=",
        "HttpOnly=true",
    ),
)
def test_named_cookie_contract_requires_exact_valueless_httponly(
    httponly_attribute,
):
    raw_token = "private-cookie-capability"
    response = _Response(
        201,
        {},
        header_items=(
            (
                "Set-Cookie",
                f"flow={raw_token}; {httponly_attribute}; Max-Age=300; "
                "Path=/api/v1; SameSite=strict",
            ),
        ),
    )

    assert not _cookie_contract_passes(
        _named_cookie_contract(response, "flow", expected_value=raw_token)
    )


@pytest.mark.parametrize(
    "attributes",
    (
        "HttpOnly; HttpOnly; Max-Age=300; Path=/api/v1; SameSite=strict",
        "HttpOnly; Max-Age=300; Path=/; Path=/api/v1; SameSite=strict",
        "HttpOnly; Max-Age=300; Path=/api/v1; SameSite=lax; SameSite=strict",
        "HttpOnly; Max-Age=0; Max-Age=300; Path=/api/v1; SameSite=strict",
        "Domain=example.invalid; Domain=; HttpOnly; Max-Age=300; "
        "Path=/api/v1; SameSite=strict",
    ),
)
def test_named_cookie_contract_rejects_duplicate_attributes(attributes):
    raw_token = "private-cookie-capability"
    response = _Response(
        201,
        {},
        header_items=(("Set-Cookie", f"flow={raw_token}; {attributes}"),),
    )

    assert not _cookie_contract_passes(
        _named_cookie_contract(response, "flow", expected_value=raw_token)
    )


def test_raw_cookie_values_must_be_absent_from_every_json_projection():
    flow_token = "private-flow-value"
    session_token = "private-session-value"
    safe = ({"status": "pending"}, {"authenticated": True})

    assert _raw_values_absent_from_json((flow_token, session_token), safe)
    assert not _raw_values_absent_from_json(
        (flow_token, session_token),
        (*safe, {"flow_token": flow_token}),
    )
    assert not _raw_values_absent_from_json((None,), safe)


def test_private_signup_flow_is_resolved_only_from_cookie_hash(db_session, engine):
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    actor = _seed_actor(
        factory,
        label="private-cookie-flow",
        mobile_value="9876500011",
        registration_status="otp_pending",
    )
    raw_token = _seed_private_signup_flow(
        factory,
        actor["registration_id"],
        destination="9876500011",
    )

    private = _require_private_signup_flow(factory, raw_token)

    assert private["registration_id"] == actor["registration_id"]
    assert private["challenge_id"] is None
    assert raw_token not in json.dumps(private, default=str)


def test_missing_private_signup_flow_fails_sanitized(db_session, engine):
    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    raw_token = "private-cookie-capability-must-not-be-disclosed"

    with pytest.raises(
        ProductGateFailure,
        match="signup cookie flow graph is unavailable",
    ) as caught:
        _require_private_signup_flow(factory, raw_token)

    assert raw_token not in str(caught.value)


def test_private_decoy_flow_requires_exact_cookie_graph_binding(db_session, engine):
    from app.core.crypto import keyed_hash
    from app.services import otp_flow_service
    from app.services.otp_authority import lock_or_create_authority

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    with factory() as session:
        now = gate.datetime.now(gate.timezone.utc)
        authority = lock_or_create_authority(
            session,
            subject_hash=keyed_hash("nyay2-private-decoy"),
            purpose="login",
            registration_id=None,
            now=now,
        )
        raw_token, _ = otp_flow_service.create_flow(
            session,
            authority,
            now=now,
            destination="9876500033",
            challenge=None,
            registration_id=None,
        )
        session.commit()

    assert _private_decoy_flow_is_bound(factory, raw_token, purpose="login")
    assert not _private_decoy_flow_is_bound(
        factory, raw_token, purpose="recovery"
    )
    assert not _private_decoy_flow_is_bound(factory, None, purpose="login")


def test_explicit_mutant_removes_cookie_flow_eligibility_but_keeps_graph_binding(
    db_session, engine
):
    from app.services import otp_flow_service

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    actor = _seed_actor(
        factory,
        label="soft-deleted-cookie-flow",
        mobile_value="9876500022",
        registration_status="otp_pending",
        soft_deleted=True,
    )
    raw_token = _seed_private_signup_flow(
        factory,
        actor["registration_id"],
        destination="9876500022",
    )

    with factory() as session:
        assert otp_flow_service.resolve_flow(session, raw_token) is None
    with factory() as session:
        graph = _unsafe_flow_graph_for_mutation(session, raw_token)
        assert graph is not None
        authority, flow = graph
        assert authority.id == flow.authority_id
        assert authority.registration_id == flow.registration_id


def test_private_capability_snapshot_detects_each_bounded_state_mutation(
    db_session, engine
):
    from app.models.registration import (
        OtpFlow,
        OtpPurposeAuthority,
        RegistrationIdempotencyRecord,
    )

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    actor = _seed_actor(
        factory,
        label="private-capability-fingerprint",
        mobile_value="9876500044",
        registration_status="otp_pending",
    )
    _seed_private_signup_flow(
        factory,
        actor["registration_id"],
        destination="9876500044",
    )
    with factory() as session:
        session.add(
            RegistrationIdempotencyRecord(
                idempotency_key_hash="a" * 64,
                request_fingerprint="b" * 64,
                request_fingerprint_version="v1",
                state="neutralized",
                outcome_code="registration_neutralized",
                registration_id=None,
                outbox_id=None,
            )
        )
        session.commit()

    before = _private_capability_snapshot(factory)
    with factory() as session:
        authority = session.scalar(select(OtpPurposeAuthority))
        assert authority is not None
        authority.failed_attempts = 1
        session.commit()
    after_authority = _private_capability_snapshot(factory)
    assert not _private_capability_state_unchanged(before, after_authority)

    with factory() as session:
        flow = session.scalar(select(OtpFlow))
        assert flow is not None
        flow.expires_at = flow.expires_at + timedelta(seconds=1)
        session.commit()
    after_flow = _private_capability_snapshot(factory)
    assert not _private_capability_state_unchanged(after_authority, after_flow)

    with factory() as session:
        ledger = session.scalar(select(RegistrationIdempotencyRecord))
        assert ledger is not None
        ledger.request_fingerprint = "c" * 64
        session.commit()
    after_ledger = _private_capability_snapshot(factory)
    assert not _private_capability_state_unchanged(after_flow, after_ledger)


def test_private_capability_snapshot_isolates_one_intended_decoy_graph(
    db_session, engine
):
    from app.core.crypto import keyed_hash
    from app.services import otp_flow_service
    from app.services.otp_authority import lock_or_create_authority

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    actor = _seed_actor(
        factory,
        label="private-capability-baseline",
        mobile_value="9876500055",
        registration_status="otp_pending",
    )
    _seed_private_signup_flow(
        factory,
        actor["registration_id"],
        destination="9876500055",
    )
    before = _private_capability_snapshot(factory)

    with factory() as session:
        now = gate.datetime.now(gate.timezone.utc)
        authority = lock_or_create_authority(
            session,
            subject_hash=keyed_hash("nyay2-isolated-decoy"),
            purpose="login",
            registration_id=None,
            now=now,
        )
        otp_flow_service.create_flow(
            session,
            authority,
            now=now,
            destination="9876500066",
            challenge=None,
            registration_id=None,
        )
        session.commit()

    after = _private_capability_snapshot(factory)
    existing_after = _private_capability_snapshot(
        factory,
        scope=before["scope"],
    )

    assert _private_capability_delta_is_exact(
        before,
        after,
        otp_purpose_authorities=1,
        otp_flows=1,
        registration_idempotency_records=0,
    )
    assert _private_capability_state_unchanged(before, existing_after)


def test_business_digest_kills_session_telemetry_mutant(db_session, engine):
    """A denied request cannot false-green after touching session telemetry."""

    from app.models.registration import AuthSession

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    _seed_actor(factory, label="digest-mutant")
    before = _business_state_digest(factory)
    with factory() as session:
        row = session.scalar(select(AuthSession))
        assert row is not None
        row.last_seen_at = row.last_seen_at + timedelta(seconds=1)
        session.commit()
    assert _business_state_digest(factory) != before


def test_business_digest_kills_registration_deleted_at_mutant(db_session, engine):
    """The registration authority bit must participate in the no-delta oracle."""

    from datetime import datetime, timezone

    from app.models.registration import StudentRegistration

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    _seed_actor(factory, label="deleted-at-digest-mutant")
    before = _business_state_digest(factory)
    with factory() as session:
        row = session.scalar(select(StudentRegistration))
        assert row is not None
        row.deleted_at = datetime.now(timezone.utc)
        session.commit()
    assert _business_state_digest(factory) != before


def test_business_digest_kills_challenge_authority_mutant(db_session, engine):
    """A challenge/outbox regression cannot hide behind unchanged row owners."""

    from datetime import datetime, timezone

    from app.core.crypto import otp_verifier
    from app.models.registration import OtpChallenge, StudentRegistration
    from app.services.otp_authority import lock_or_create_registration_authority

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    actor = _seed_actor(factory, label="challenge-mutant")
    before = _business_state_digest(factory)
    now = datetime.now(timezone.utc)
    with factory() as session:
        registration = session.get(StudentRegistration, actor["registration_id"])
        assert registration is not None
        authority = lock_or_create_registration_authority(
            session, registration, "signup", now
        )
        expires_at = now + timedelta(minutes=5)
        session.add(
            OtpChallenge(
                registration_id=actor["registration_id"],
                authority_id=authority.id,
                purpose="signup",
                delivery_state="active",
                verifier_hash=otp_verifier("1" * 6, salt="synthetic-salt"),
                attempts=0,
                max_attempts=3,
                expires_at=expires_at,
                metadata_json={"salt": "synthetic-salt"},
            )
        )
        authority.active_expires_at = expires_at
        session.commit()
    assert _business_state_digest(factory) != before


class _Headers:
    def __init__(self, items=()):
        self._items = tuple((str(key), str(value)) for key, value in items)

    def get_list(self, name: str):
        expected = name.casefold()
        return [value for key, value in self._items if key.casefold() == expected]

    def get(self, name: str, default=None):
        values = self.get_list(name)
        return ", ".join(values) if values else default


class _Response:
    def __init__(
        self,
        status_code: int,
        payload,
        *,
        json_failure: bool = False,
        header_items=(),
    ):
        self.status_code = status_code
        self.payload = payload
        self.json_failure = json_failure
        self.headers = _Headers(header_items)

    def json(self):
        if self.json_failure:
            raise ValueError("not json")
        return self.payload


def test_response_signature_keeps_typed_code_but_not_payload_values():
    secret = "private-value"
    signature = _safe_response_signature(
        _Response(
            403,
            {
                "detail": {
                    "code": "forbidden",
                    "message": secret,
                    "target": "ignored",
                }
            },
        )
    )
    assert signature == {
        "status_code": 403,
        "shape": "typed_detail",
        "code": "forbidden",
    }
    assert secret not in json.dumps(signature)


def test_response_signature_removes_validation_input_and_messages():
    secret = "attacker-controlled-value"
    signature = _safe_response_signature(
        _Response(
            422,
            {
                "detail": [
                    {
                        "type": "extra_forbidden",
                        "loc": ["body", "registration_id"],
                        "msg": secret,
                        "input": secret,
                    }
                ]
            },
        )
    )
    assert signature == {
        "status_code": 422,
        "shape": "validation",
        "errors": [("extra_forbidden", "body.registration_id")],
    }
    assert secret not in json.dumps(signature)


def test_response_signature_classifies_non_json_without_copying_body():
    assert _safe_response_signature(_Response(500, None, json_failure=True)) == {
        "status_code": 500,
        "shape": "non_json",
    }


def test_response_object_fails_closed_on_non_object_or_invalid_json():
    assert _safe_response_object(_Response(200, {"status": "safe"})) == {
        "status": "safe"
    }
    assert _safe_response_object(_Response(200, ["unsafe-shape"])) is None
    assert _safe_response_object(_Response(500, None, json_failure=True)) is None


def _otp_projection(
    *,
    status="pending",
    purpose="login",
    destination_masked="••••••0033",
):
    return {
        "status": status,
        "purpose": purpose,
        "destination_masked": destination_masked,
        "attempts_left": 3,
        "expires_in_seconds": 300,
        "resend_in_seconds": 30,
        "locked_for_seconds": 0,
        "resend_allowed": False,
    }


def _safe_otp_header_items():
    return (
        ("Cache-Control", "private, no-store"),
        ("Vary", "Cookie"),
        ("Content-Type", "application/json"),
    )


def test_public_otp_response_match_requires_full_projection_and_safe_headers():
    known = _Response(202, _otp_projection(), header_items=_safe_otp_header_items())
    unknown = _Response(202, _otp_projection(), header_items=_safe_otp_header_items())

    assert _public_otp_responses_match(
        known,
        unknown,
        expected_purpose="login",
        expected_masked_last4="0033",
    )
    assert not _public_otp_responses_match(
        known,
        _Response(
            202,
            _otp_projection(status="known_account"),
            header_items=_safe_otp_header_items(),
        ),
        expected_purpose="login",
        expected_masked_last4="0033",
    )
    assert not _public_otp_responses_match(
        known,
        _Response(
            202,
            {**_otp_projection(), "account_exists": True},
            header_items=_safe_otp_header_items(),
        ),
        expected_purpose="login",
        expected_masked_last4="0033",
    )
    assert not _public_otp_responses_match(
        known,
        _Response(
            202,
            _otp_projection(),
            header_items=(
                ("Cache-Control", "public"),
                ("Vary", "Cookie"),
                ("Content-Type", "application/json"),
            ),
        ),
        expected_purpose="login",
        expected_masked_last4="0033",
    )


@pytest.mark.parametrize(
    "purpose, destination_masked",
    (
        ("recovery", "••••••0033"),
        ("login", "••••••9999"),
    ),
)
def test_public_otp_response_match_rejects_same_wrong_projection(
    purpose,
    destination_masked,
):
    projection = _otp_projection(
        purpose=purpose,
        destination_masked=destination_masked,
    )
    known = _Response(202, projection, header_items=_safe_otp_header_items())
    unknown = _Response(202, projection, header_items=_safe_otp_header_items())

    assert not _public_otp_responses_match(
        known,
        unknown,
        expected_purpose="login",
        expected_masked_last4="0033",
    )


def test_public_otp_response_match_accepts_expected_recovery_projection():
    projection = _otp_projection(
        purpose="recovery",
        destination_masked="••••••7788",
    )
    known = _Response(202, projection, header_items=_safe_otp_header_items())
    unknown = _Response(202, projection, header_items=_safe_otp_header_items())

    assert _public_otp_responses_match(
        known,
        unknown,
        expected_purpose="recovery",
        expected_masked_last4="7788",
    )


@pytest.mark.parametrize(
    "value, finding",
    (
        ({"value": "a2ef7107-0f9b-4b8d-b4a1-22e6c4375e9c"}, "uuid"),
        ({"value": "person@example.invalid"}, "email"),
        ({"value": "9876543210"}, "mobile"),
        ({"value": "postgresql://user:secret@localhost/db"}, "database_or_http_url"),
        ({"value": "https://example.invalid/path"}, "database_or_http_url"),
    ),
)
def test_privacy_scan_reports_only_path_and_class(value, finding):
    results = _privacy_findings(value)
    assert results == [f"report.value:{finding}"]
    assert value["value"] not in json.dumps(results)


def test_expected_aggregate_report_shape_is_privacy_safe():
    report = {
        "gate": "nyay2_postgres_authorization",
        "status": "PASS",
        "executed": True,
        "assertions": _passing_assertions(),
        "evaluation": _evaluate_assertions(_passing_assertions()),
        "api_metrics": {
            "real_http_requests_executed": True,
            "negative_controls_executed": 3,
            "protected_routes_checked": 5,
            "protected_uuid_contract_routes_checked": 4,
        },
        "scratch_cleanup": {
            "created": 1,
            "removed": 1,
            "cleanup_failed": 0,
            "all_created_removed": True,
            "purposes": ["authorization"],
        },
    }
    assert _privacy_findings(report) == []


def test_scratch_manager_cleans_after_success(monkeypatch):
    created: list[str] = []
    removed: list[str] = []
    monkeypatch.setattr(
        gate,
        "_create_scratch",
        lambda _base, name: created.append(name) or "postgresql://scratch",
    )
    monkeypatch.setattr(
        gate,
        "_drop_scratch",
        lambda _base, name: removed.append(name),
    )
    manager = _ScratchDatabaseManager(object())
    assert manager.run("authorization", lambda url: url) == "postgresql://scratch"
    assert removed == created
    assert manager.summary() == {
        "created": 1,
        "removed": 1,
        "cleanup_failed": 0,
        "all_created_removed": True,
        "purposes": ["authorization"],
    }


def test_scratch_manager_cleans_when_operation_fails(monkeypatch):
    created: list[str] = []
    removed: list[str] = []
    monkeypatch.setattr(
        gate,
        "_create_scratch",
        lambda _base, name: created.append(name) or "postgresql://scratch",
    )
    monkeypatch.setattr(
        gate,
        "_drop_scratch",
        lambda _base, name: removed.append(name),
    )
    manager = _ScratchDatabaseManager(object())

    def fail(_url):
        raise RuntimeError("forced")

    with pytest.raises(RuntimeError, match="forced"):
        manager.run("authorization", fail)
    assert removed == created
    assert manager.summary()["all_created_removed"] is True


def test_scratch_cleanup_failure_is_fatal_and_sanitized(monkeypatch):
    monkeypatch.setattr(
        gate, "_create_scratch", lambda _base, _name: "postgresql://scratch"
    )

    def fail_drop(_base, _name):
        raise RuntimeError("credential-bearing-driver-error")

    monkeypatch.setattr(gate, "_drop_scratch", fail_drop)
    manager = _ScratchDatabaseManager(object())
    with pytest.raises(
        ScratchCleanupFailure,
        match="disposable NYAY-2 database could not be removed",
    ) as caught:
        manager.run("authorization", lambda _url: True)
    assert "credential-bearing" not in str(caught.value)
    assert manager.summary()["cleanup_failed"] == 1
    assert manager.summary()["all_created_removed"] is False


def test_unsafe_url_is_rejected_before_any_scratch_creation(monkeypatch, capsys):
    calls: list[str] = []
    monkeypatch.setattr(
        gate,
        "_create_scratch",
        lambda *_args: calls.append("created") or "unexpected",
    )
    result = gate.main(
        [
            "--database-url",
            "postgresql+psycopg://qa:secret@example.invalid:5432/postgres",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert result == BLOCKED_EXIT
    assert calls == []
    assert report["status"] == "BLOCKED"
    assert report["executed"] is False
    assert "secret" not in json.dumps(report)


def test_missing_url_is_blocked_without_execution(capsys):
    result = gate.main([])
    report = json.loads(capsys.readouterr().out)
    assert result == BLOCKED_EXIT
    assert report["status"] == "BLOCKED"
    assert report["executed"] is False
    assert report["scratch_cleanup"]["created"] == 0


def test_blocked_after_scratch_creation_reports_executed(monkeypatch, capsys):
    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", _FakeManager)

    def blocked_after_execution(_url):
        raise Blocked("target runtime unavailable")

    monkeypatch.setattr(gate, "_execute", blocked_after_execution)
    result = gate.main(["--database-url", "opaque-test-authority"])
    report = json.loads(capsys.readouterr().out)
    assert result == BLOCKED_EXIT
    assert report["status"] == "BLOCKED"
    assert report["executed"] is True
    assert report["scratch_cleanup"]["created"] == 1
    assert report["scratch_cleanup"]["removed"] == 1


@pytest.mark.parametrize("returncodes", ((1,), (0, 1)))
def test_migration_or_head_failure_is_product_failure_not_blocked(
    monkeypatch, returncodes
):
    outcomes = iter(returncodes)
    monkeypatch.setattr(
        gate,
        "_run_alembic",
        lambda _url, *_arguments: {
            "arguments": [],
            "returncode": next(outcomes),
        },
    )
    with pytest.raises(ProductGateFailure):
        gate._execute("not-retained")


class _FakeManager:
    cleanup_ok = True

    def __init__(self, _base):
        self.scratch_created = True

    def run(self, _purpose, operation):
        return operation("not-retained")

    def summary(self):
        return {
            "created": 1,
            "removed": 1 if self.cleanup_ok else 0,
            "cleanup_failed": 0 if self.cleanup_ok else 1,
            "all_created_removed": self.cleanup_ok,
            "purposes": ["authorization"],
        }


def test_main_pass_requires_exact_assertions_privacy_and_cleanup(
    monkeypatch, capsys, tmp_path: Path
):
    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", _FakeManager)
    monkeypatch.setattr(
        gate,
        "_execute",
        lambda _url: {
            "assertions": _passing_assertions(),
            "api_metrics": {"real_http_requests_executed": True},
        },
    )
    report_path = tmp_path / "aggregate.json"
    result = gate.main(
        [
            "--database-url",
            "opaque-test-authority",
            "--report",
            str(report_path),
        ]
    )
    stdout_report = json.loads(capsys.readouterr().out)
    disk_report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 0
    assert stdout_report == disk_report
    assert disk_report["status"] == "PASS"
    assert disk_report["evaluation"]["overall_pass"] is True
    assert disk_report["privacy_scan"] == {
        "scanned": True,
        "findings": 0,
        "passed": True,
    }


def test_main_cannot_pass_when_cleanup_fails(monkeypatch, capsys):
    class CleanupFailManager(_FakeManager):
        cleanup_ok = False

    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", CleanupFailManager)
    monkeypatch.setattr(
        gate,
        "_execute",
        lambda _url: {
            "assertions": _passing_assertions(),
            "api_metrics": {"real_http_requests_executed": True},
        },
    )
    result = gate.main(["--database-url", "opaque-test-authority"])
    report = json.loads(capsys.readouterr().out)
    assert result == 1
    assert report["status"] == "FAIL"
    assert report["evaluation"]["overall_pass"] is False


def test_main_cannot_pass_when_assertion_is_missing(monkeypatch, capsys):
    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", _FakeManager)
    monkeypatch.setattr(
        gate,
        "_execute",
        lambda _url: {
            "assertions": _passing_assertions()[:-1],
            "api_metrics": {"real_http_requests_executed": True},
        },
    )
    result = gate.main(["--database-url", "opaque-test-authority"])
    report = json.loads(capsys.readouterr().out)
    assert result == 1
    assert report["status"] == "FAIL"
    assert report["evaluation"]["exact_inventory"] is False


def test_main_cannot_pass_privacy_leak(monkeypatch, capsys):
    assertions = _passing_assertions()
    assertions[0]["metrics"] = {"forbidden": "a2ef7107-0f9b-4b8d-b4a1-22e6c4375e9c"}
    monkeypatch.setattr(gate, "_safe_local_postgres_url", lambda _raw: object())
    monkeypatch.setattr(gate, "_ScratchDatabaseManager", _FakeManager)
    monkeypatch.setattr(
        gate,
        "_execute",
        lambda _url: {
            "assertions": assertions,
            "api_metrics": {"real_http_requests_executed": True},
        },
    )
    result = gate.main(["--database-url", "opaque-test-authority"])
    report = json.loads(capsys.readouterr().out)
    assert result == 1
    assert report["status"] == "FAIL"
    assert report["privacy_scan"]["findings"] == 1


def test_source_contains_real_routes_and_all_five_mutant_oracles():
    source = Path(gate.__file__).read_text(encoding="utf-8")
    for route in (
        gate.PROFILE_PATH,
        gate.EMAIL_PATH,
        gate.STATUS_PATH,
        gate.GUARDIAN_PATH,
        gate.REGISTER_PATH,
        gate.OTP_VERIFY_PATH,
        gate.OTP_RESEND_PATH,
        gate.LOGIN_START_PATH,
        gate.RECOVERY_START_PATH,
    ):
        assert route in source
    assert "unsafe_owned_registration" in source
    assert "original_reviewer_dependency" in source
    assert "original_origin_guard" in source
    assert "unsafe_signup_scope" in source
    assert "unsafe_authorizable" in source
    assert "_unsafe_flow_graph_for_mutation" in source
    assert 'registered.json().get("registration_id")' not in source
    assert "registration_reference" not in source
    assert "uuid.UUID(str(" not in source
    assert "flow_cookie_contract=flow_cookie_contract" in source
    assert "session_cookie_contract=session_cookie_contract" in source
    assert '"private_capability_state_unchanged"' in source
    assert "login_projection_matches_unknown" in source
    assert "recovery_projection_matches_unknown" in source
    assert '"unknown_preauth_controls_checked"' in source
    assert "TestClient" in source


def test_signup_bootstrap_uses_the_current_idempotency_header_contract():
    assert _signup_registration_headers() == {
        "Origin": gate.TRUSTED_ORIGIN,
        "Idempotency-Key": "nyay2-postgres-gate-signup-0001",
    }
    assert _trusted_mutation_headers() == {"Origin": gate.TRUSTED_ORIGIN}


def test_signup_bootstrap_uses_current_separate_legal_acknowledgement_contract():
    assert len(REQUIRED_ASSERTION_IDS) == 21
    assert SIGNUP_ACCEPTED_STATUS == 202
    assert _signup_registration_payload("7" * 10) == {
        "first_name": "Gate",
        "last_name": "Signup",
        "mobile": "7" * 10,
        "dob": "2000-01-02",
        "terms_accepted": True,
        "terms_version": "terms-2026-08.v1",
        "privacy_notice_acknowledged": True,
        "privacy_notice_version": "privacy-2026-08.v1",
    }
    assert "consent" not in _signup_registration_payload("7" * 10)


def test_profile_and_reviewer_probes_use_current_cas_request_contracts():
    assert gate._profile_payload(
        "owner-a", expected_profile_version=3
    ) == {
        "expected_profile_version": 3,
        "college": "NALSAR University of Law",
        "year_of_study": "4th",
        "enrolment_number": "QA/874440/2026",
        "institutional_email": "gate-owner-a@college.invalid",
        "bar_enrolment_number": None,
    }


def test_email_request_and_status_probe_uses_current_public_internal_projection():
    assert gate._email_status_projection_passes(
        email_status=202,
        email_payload={"institutional_email_status": "pending"},
        status_status=200,
        status_payload={"status": "in_review"},
    )
    for field, value in (
        ("email_status", 422),
        ("email_payload", {"institutional_email_status": "not_provided"}),
        ("status_status", 401),
        ("status_payload", {"status": "pending"}),
    ):
        observation = {
            "email_status": 202,
            "email_payload": {"institutional_email_status": "pending"},
            "status_status": 200,
            "status_payload": {"status": "in_review"},
        }
        observation[field] = value
        assert not gate._email_status_projection_passes(**observation)
    assert gate._institutional_email_request_payload() == {}
    assert gate._verification_transition_payload(
        "00000000-0000-4000-8000-000000000001",
        status="verified",
        expected_profile_version=4,
    ) == {
        "registration_id": "00000000-0000-4000-8000-000000000001",
        "status": "verified",
        "expected_profile_version": 4,
    }


def test_seed_actor_starts_at_current_academic_mutation_prerequisite(
    db_session, engine
):
    from app.models.registration import StudentProfile

    factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    actor = _seed_actor(factory, label="current-profile-prerequisite")

    with factory() as session:
        profile = session.scalar(
            select(StudentProfile).where(
                StudentProfile.registration_id == actor["registration_id"]
            )
        )
        assert profile is not None
        assert profile.profile_version == 1
        assert profile.preferred_language == "en"
        assert profile.city == "Gate City"


def test_origin_mutant_removes_both_current_cookie_origin_backstops():
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "core_auth.require_trusted_cookie_origin = unsafe_origin_guard" in source
    assert (
        "app.dependency_overrides[original_route_origin_guard] = "
        "unsafe_origin_guard" in source
    )
    assert "app.dependency_overrides.pop(original_route_origin_guard, None)" in source


def test_current_composite_mutants_remove_every_independent_backstop():
    source = Path(gate.__file__).read_text(encoding="utf-8")
    compact_source = " ".join(source.split())
    assert "original_profile_authority = profile_service.resolve_authority" in source
    assert "profile_service.resolve_authority = unsafe_profile_authority" in source
    assert "profile_service.resolve_authority = original_profile_authority" in source
    assert (
        "original_reviewer_session_lock = ( "
        "login_service.lock_presented_session_for_effect )" in compact_source
    )
    assert (
        "login_service.lock_presented_session_for_effect = "
        "( unsafe_reviewer_session_lock )" in compact_source
    )
    assert (
        "login_service.lock_presented_session_for_effect = "
        "( original_reviewer_session_lock )" in compact_source
    )


def test_ownership_mutant_prepares_every_fallible_input_before_global_overrides():
    source = Path(gate.__file__).read_text(encoding="utf-8")
    payload = source.index('mutant_owner_payload = _profile_payload(')
    endpoint_override = source.index(
        "endpoint._owned_registration = unsafe_owned_registration"
    )
    authority_override = source.index(
        "profile_service.resolve_authority = unsafe_profile_authority"
    )
    restoration = source.index(
        "profile_service.resolve_authority = original_profile_authority"
    )

    # Database lookup and payload validation can raise. They must finish before
    # either process-global production function is replaced; the request itself
    # remains covered by the existing try/finally restoration boundary.
    assert payload < endpoint_override < authority_override < restoration


def test_owner_audit_probe_tracks_the_canonical_profile_event():
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert 'AuditEvent.action == "student.profile.section_updated"' in source
    assert 'AuditEvent.action == "student.profile.academic_updated"' not in source


def test_origin_matrix_inventory_is_exact_and_includes_duplicate_header_case():
    labels = tuple(item[0] for item in ORIGIN_MATRIX_CASES)
    assert labels == (
        "missing",
        "null",
        "wildcard",
        "malformed",
        "lookalike",
        "prefix",
        "slash",
        "path",
        "userinfo",
        "query",
        "fragment",
        "cross_scheme",
        "cross_host",
        "cross_port",
        "duplicate",
        "trusted",
    )
    assert ORIGIN_MATRIX_CASES[-2][1] == (gate.TRUSTED_ORIGIN,) * 2
    assert sum(bool(item[2]) for item in ORIGIN_MATRIX_CASES) == 1
