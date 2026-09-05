"""NYAY-22 RED contracts for the server-owned mentor session ceremony.

The source of truth is the sealed NYAY-29 contract as reconciled by NYAY-33
(``632dc7158c3b417ed6a4c18819f7310f1a5c1f15``).  These contracts were written
before implementation and now remain as the enforced GREEN acceptance boundary
for the server-owned ceremony.

Each test corresponds to one requested implementation boundary.  Imports of
future implementation symbols are performed inside the test so that pytest
collects all ten contracts and reports ten independent failures instead of one
collection error.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest


BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SEALED_OPENAPI_PATH = (
    REPO
    / "docs"
    / "architecture"
    / "nyay29-tutor-lawyer-ceremony"
    / "CEREMONY_API_CONTRACT.openapi.json"
)
SEALED_OPENAPI = json.loads(SEALED_OPENAPI_PATH.read_text(encoding="utf-8"))


def _red(contract_id: str, detail: str) -> None:
    pytest.fail(f"{contract_id}: {detail}", pytrace=False)


def _resolve(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve a local OpenAPI reference without weakening the comparison."""

    while "$ref" in schema:
        ref = schema["$ref"]
        if not isinstance(ref, str) or not ref.startswith("#/"):
            raise AssertionError(f"unsupported non-local schema reference: {ref!r}")
        value: Any = document
        for part in ref[2:].split("/"):
            value = value[part.replace("~1", "/").replace("~0", "~")]
        if not isinstance(value, dict):
            raise AssertionError(f"schema reference does not resolve to an object: {ref}")
        schema = value
    return schema


def _operation(
    document: dict[str, Any], path: str, method: str, contract_id: str
) -> dict[str, Any]:
    operation = document.get("paths", {}).get(path, {}).get(method.lower())
    if not isinstance(operation, dict):
        _red(contract_id, f"runtime operation {method.upper()} {path} is not wired")
    return operation


def _request_schema(
    document: dict[str, Any], operation: dict[str, Any], contract_id: str
) -> dict[str, Any]:
    try:
        schema = operation["requestBody"]["content"]["application/json"]["schema"]
    except (KeyError, TypeError):
        _red(contract_id, "application/json request schema is missing")
    return _resolve(document, schema)


def _variants(document: dict[str, Any], schema: dict[str, Any]) -> list[dict[str, Any]]:
    schema = _resolve(document, schema)
    return [_resolve(document, item) for item in schema.get("oneOf", [schema])]


def _literal(schema: dict[str, Any]) -> Any:
    if "const" in schema:
        return schema["const"]
    values = schema.get("enum")
    if isinstance(values, list) and len(values) == 1:
        return values[0]
    return None


def _intent_variant(
    document: dict[str, Any], schema: dict[str, Any], intent: str, contract_id: str
) -> dict[str, Any]:
    for variant in _variants(document, schema):
        intent_schema = _resolve(document, variant.get("properties", {}).get("intent", {}))
        if _literal(intent_schema) == intent:
            return variant
    _red(contract_id, f"request variant for intent={intent!r} is missing")


def _runtime_app():
    from fastapi import FastAPI

    from app.api.v1.router import api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    return app


@pytest.fixture(scope="module")
def runtime_app():
    return _runtime_app()


@pytest.fixture(scope="module")
def runtime_openapi(runtime_app):
    return runtime_app.openapi()


@pytest.fixture(scope="module")
def runtime_client(runtime_app):
    from fastapi.testclient import TestClient

    with TestClient(runtime_app, raise_server_exceptions=False) as client:
        yield client


def test_red_01_mentor_session_is_a_distinct_server_owned_session_class() -> None:
    """MentorSession must not be an alias or role bit on AuthSession."""

    import app.models as models

    mentor_session = getattr(models, "MentorSession", None)
    if mentor_session is None:
        _red("NYAY22-RED-01", "app.models.MentorSession is not implemented")

    auth_session = getattr(models, "AuthSession")
    assert mentor_session is not auth_session, (
        "NYAY22-RED-01: MentorSession must be distinct from AuthSession"
    )
    mentor_table = getattr(mentor_session, "__table__", None)
    auth_table = getattr(auth_session, "__table__", None)
    assert mentor_table is not None and auth_table is not None
    assert mentor_table.name == "mentor_sessions"
    assert mentor_table.name != auth_table.name


def test_red_02_rotated_out_is_terminal_and_cannot_return_to_active() -> None:
    """The NYAY-33-corrected predecessor state is terminal ``rotated_out``."""

    import app.models as models

    states = getattr(models, "MENTOR_SESSION_STATES", None)
    terminal_states = getattr(models, "MENTOR_SESSION_TERMINAL_STATES", None)
    transitions = getattr(models, "MENTOR_SESSION_TRANSITIONS", None)
    if states is None or terminal_states is None or transitions is None:
        _red(
            "NYAY22-RED-02",
            "mentor finite-state constants and transition map are not implemented",
        )

    sealed_states = SEALED_OPENAPI["x-nyayone-design-contract"]["sessionStates"]
    assert list(states) == sealed_states
    assert "active" not in terminal_states
    assert "rotated_out" in terminal_states
    assert set(transitions["rotated_out"]) == set(), (
        "NYAY22-RED-02: rotated_out must have no outbound transition"
    )


def test_red_03_session_absolute_and_idle_configuration_fail_closed_at_ceiling() -> None:
    """Configuration may shorten 28,800/1,800 seconds and never lengthen it."""

    from pydantic import ValidationError

    from app.core.config import Settings

    absolute_name = "mentor_session_absolute_ttl_seconds"
    idle_name = "mentor_session_idle_ttl_seconds"
    missing = [
        name for name in (absolute_name, idle_name) if name not in Settings.model_fields
    ]
    if missing:
        _red("NYAY22-RED-03", f"missing fail-closed settings: {', '.join(missing)}")

    ceilings = SEALED_OPENAPI["x-nyayone-design-contract"]["sessionCeilings"]
    absolute_ceiling = ceilings["mentorSessionAbsoluteSeconds"]
    idle_ceiling = ceilings["mentorSessionIdleSeconds"]

    accepted = Settings(
        _env_file=None,
        **{absolute_name: absolute_ceiling, idle_name: idle_ceiling},
    )
    assert 0 < getattr(accepted, absolute_name) <= absolute_ceiling
    assert 0 < getattr(accepted, idle_name) <= idle_ceiling

    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{absolute_name: absolute_ceiling + 1})
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{idle_name: idle_ceiling + 1})


def test_red_04_exchange_requires_exact_explicit_acceptance(
    runtime_openapi: dict[str, Any],
) -> None:
    """Verification previews disclosure; only exchange may consume acceptance."""

    contract_id = "NYAY22-RED-04"
    path = "/api/v1/auth/mentor/ceremony/exchange"
    actual_operation = _operation(runtime_openapi, path, "post", contract_id)
    actual = _intent_variant(
        runtime_openapi,
        _request_schema(runtime_openapi, actual_operation, contract_id),
        "mentor_session",
        contract_id,
    )

    expected = SEALED_OPENAPI["components"]["schemas"]["MentorSessionExchangeRequest"]
    assert set(expected["required"]).issubset(actual.get("required", []))
    properties = actual.get("properties", {})
    assert _literal(_resolve(runtime_openapi, properties["acceptPurpose"])) is True
    assert _literal(_resolve(runtime_openapi, properties["expectedCeremonyState"])) == (
        "proof_verified"
    )
    assert {"purposeCode", "consentReceiptVersion", "acceptanceTextVersion"}.issubset(
        properties
    )


def test_red_05_authority_deletion_requires_fresh_action_bound_step_up(
    runtime_openapi: dict[str, Any],
) -> None:
    """Deletion requires both the live mentor session and one-use step-up."""

    contract_id = "NYAY22-RED-05"
    exchange_path = "/api/v1/auth/mentor/ceremony/exchange"
    exchange_operation = _operation(runtime_openapi, exchange_path, "post", contract_id)
    step_up = _intent_variant(
        runtime_openapi,
        _request_schema(runtime_openapi, exchange_operation, contract_id),
        "authority_deletion_step_up",
        contract_id,
    )
    assert _literal(
        _resolve(
            runtime_openapi,
            step_up["properties"]["acceptAuthorityDeletionStepUp"],
        )
    ) is True

    delete_path = "/api/v1/auth/mentor/authority"
    delete_operation = _operation(runtime_openapi, delete_path, "delete", contract_id)
    security_sets = [set(item) for item in delete_operation.get("security", [])]
    assert {
        "TrustedOrigin",
        "MentorSessionCookie",
        "MentorAuthorityStepUpCookie",
    } in security_sets
    delete_request = _request_schema(runtime_openapi, delete_operation, contract_id)
    assert _literal(
        _resolve(runtime_openapi, delete_request["properties"]["confirmation"])
    ) == "delete_mentor_authority"


def test_red_06_minor_guardian_and_limited_mode_fail_closed() -> None:
    """NYAY-5 guardian proof is server-read and every sensitive denial collapses."""

    contract_id = "NYAY22-RED-06"
    service_path = BACKEND / "app" / "services" / "mentor_ceremony.py"
    if not service_path.is_file():
        _red(contract_id, "server-side mentor subject-sharing gate is not implemented")

    source = service_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(service_path))
    loaded_names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "has_authoritative_guardian_proof" in loaded_names, (
        f"{contract_id}: ceremony must reuse the persisted NYAY-5 guardian authority"
    )
    assert "limited" in string_literals, (
        f"{contract_id}: access_mode=limited must be a server-side denial input"
    )
    assert "AUTHORIZATION_DENIED" in string_literals, (
        f"{contract_id}: guardian/consent denials must use the generic public code"
    )
    assert "CONSENT_OR_POLICY_DENIED" not in source, (
        f"{contract_id}: NYAY-33 removed the enumerating public denial code"
    )


def test_red_07_wire_contract_has_no_client_authority_selectors(
    runtime_openapi: dict[str, Any],
) -> None:
    """Actor, profile, relation, provider, session, and scope stay server-owned."""

    contract_id = "NYAY22-RED-07"
    forbidden = {
        "actorId",
        "userId",
        "ownerId",
        "studentId",
        "subjectId",
        "mentorId",
        "tutorProfileId",
        "profileId",
        "invitationId",
        "engagementId",
        "authorityDomainId",
        "tenantId",
        "sessionId",
        "mentorRole",
        "role",
        "provider",
        "providerId",
        "providerToken",
        "identityProof",
        "proof",
        "nonce",
        "scope",
        "scopes",
        "guardianAuthority",
        "guardianConsent",
    }

    for path, sealed_path_item in SEALED_OPENAPI["paths"].items():
        for method, sealed_operation in sealed_path_item.items():
            actual_operation = _operation(runtime_openapi, path, method, contract_id)
            actual_parameters = []
            for parameter in actual_operation.get("parameters", []):
                actual_parameters.append(_resolve(runtime_openapi, parameter))
            forbidden_parameters = {
                parameter.get("name")
                for parameter in actual_parameters
                if parameter.get("name") in forbidden
            }
            assert not forbidden_parameters, (
                f"{contract_id}: {method.upper()} {path} exposes authority parameters "
                f"{sorted(forbidden_parameters)}"
            )

            if "requestBody" not in sealed_operation:
                continue
            actual_schema = _request_schema(
                runtime_openapi, actual_operation, contract_id
            )
            for variant in _variants(runtime_openapi, actual_schema):
                exposed = set(variant.get("properties", {})) & forbidden
                assert not exposed, (
                    f"{contract_id}: {method.upper()} {path} accepts client authority "
                    f"selectors {sorted(exposed)}"
                )


def test_red_08_every_mutation_uses_nyay9_style_digest_bound_idempotency(
    runtime_openapi: dict[str, Any],
) -> None:
    """Opaque keys are mandatory; same key/different fingerprint conflicts."""

    contract_id = "NYAY22-RED-08"
    for path, sealed_path_item in SEALED_OPENAPI["paths"].items():
        for method, sealed_operation in sealed_path_item.items():
            if method.lower() == "get":
                continue
            actual_operation = _operation(runtime_openapi, path, method, contract_id)
            parameters = [
                _resolve(runtime_openapi, parameter)
                for parameter in actual_operation.get("parameters", [])
            ]
            idempotency = [
                parameter
                for parameter in parameters
                if parameter.get("in") == "header"
                and parameter.get("name", "").casefold() == "idempotency-key"
            ]
            assert len(idempotency) == 1, (
                f"{contract_id}: {method.upper()} {path} must declare one Idempotency-Key"
            )
            assert idempotency[0].get("required") is True

    implementation_sources = [
        BACKEND / "app" / "services" / "mentor_ceremony.py",
        BACKEND / "app" / "models" / "mentor_auth.py",
    ]
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in implementation_sources
        if path.is_file()
    )
    required_markers = {
        "idempotency_key_hash",
        "request_fingerprint",
        "keyed_hash",
        "IDEMPOTENCY_CONFLICT",
    }
    missing = sorted(marker for marker in required_markers if marker not in source)
    assert not missing, (
        f"{contract_id}: missing durable digest/fingerprint semantics {missing}"
    )


def test_red_09_all_request_schemas_are_closed_and_exact(
    runtime_openapi: dict[str, Any],
) -> None:
    """Every JSON body rejects unknown fields and matches the sealed shape."""

    contract_id = "NYAY22-RED-09"
    for path, sealed_path_item in SEALED_OPENAPI["paths"].items():
        for method, sealed_operation in sealed_path_item.items():
            if "requestBody" not in sealed_operation:
                continue
            actual_operation = _operation(runtime_openapi, path, method, contract_id)
            actual_variants = _variants(
                runtime_openapi,
                _request_schema(runtime_openapi, actual_operation, contract_id),
            )
            sealed_variants = _variants(
                SEALED_OPENAPI,
                _request_schema(SEALED_OPENAPI, sealed_operation, contract_id),
            )

            def signatures(variants: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
                return sorted(
                    (
                        tuple(sorted(variant.get("properties", {}))),
                        tuple(sorted(variant.get("required", []))),
                        variant.get("additionalProperties"),
                    )
                    for variant in variants
                )

            assert signatures(actual_variants) == signatures(sealed_variants), (
                f"{contract_id}: {method.upper()} {path} diverges from the sealed "
                "closed request schema"
            )
            assert all(
                variant.get("additionalProperties") is False
                for variant in actual_variants
            )


def test_red_10_public_diagnostics_are_generic_and_pii_safe(runtime_client) -> None:
    """Invalid bodies cannot echo PII or expose internal denial distinctions."""

    contract_id = "NYAY22-RED-10"
    canary = "mentor-pii-canary@example.invalid"
    response = runtime_client.post(
        "/api/v1/auth/mentor/ceremony/initiate",
        headers={
            "Origin": "http://127.0.0.1:1130",
            "Idempotency-Key": "nyay22-red-diagnostic-0001",
        },
        json={
            "intent": "mentor_session",
            "requestedMentorRole": "tutor",
            "purposeCode": "student_guidance",
            "privacyNoticeVersion": "privacy-2026-09.v1",
            # Forbidden client-selected identity data is a planted PII canary.
            "tutorProfileId": canary,
        },
    )

    assert response.status_code == 400, (
        f"{contract_id}: strict invalid input must map to typed HTTP 400, got "
        f"{response.status_code}"
    )
    payload = response.json()
    assert payload.get("detail", {}).get("code") == "INVALID_REQUEST"
    assert payload.get("detail", {}).get("message") == "Request failed"
    assert payload.get("detail", {}).get("retryable") is False
    assert canary not in response.text
    assert response.headers.get("cache-control") == "private, no-store"
    vary = {item.strip().casefold() for item in response.headers.get("vary", "").split(",")}
    assert "cookie" in vary
