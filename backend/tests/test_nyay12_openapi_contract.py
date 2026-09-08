"""NYAY-12 review S2: the published OpenAPI is the enforced closed contract."""
from __future__ import annotations

import pytest

from tests.test_nyay12_email_identity_red import Ctx, _key, EMAIL_START, CHANNELS, ROOT

IDENTITY_STATES = ["pending", "verified", "removed"]
VERIFICATION_STATUSES = ["none", "pending_delivery", "active", "failed", "expired"]


@pytest.fixture()
def ctx(monkeypatch: pytest.MonkeyPatch) -> Ctx:
    return Ctx(monkeypatch)


def _resolve(document, schema):
    seen = set()
    while "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/components/schemas/") and ref not in seen
        seen.add(ref)
        schema = document["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    return schema


def _request_schema(document, method, path):
    operation = document["paths"][path][method]
    body = operation["requestBody"]
    assert body.get("required") is True, "NYAY12_OPENAPI_REQUEST_BODY_OPTIONAL"
    return _resolve(document, body["content"]["application/json"]["schema"])


def _response_schema(document, method, path, status):
    operation = document["paths"][path][method]
    return _resolve(document, operation["responses"][status]["content"]["application/json"]["schema"])


def _identity_schema(document, container):
    identity = _resolve(document, container["properties"]["identity"])
    assert identity.get("additionalProperties") is False
    assert set(identity["required"]) == {"id", "email_masked", "state", "is_primary", "verification"}
    assert identity["properties"]["state"]["enum"] == IDENTITY_STATES
    verification = _resolve(document, identity["properties"]["verification"])
    assert verification.get("additionalProperties") is False
    assert verification["properties"]["status"]["enum"] == VERIFICATION_STATUSES
    for relative in ("expires_in_seconds", "resend_in_seconds", "attempts_left"):
        branch = verification["properties"][relative]
        assert any(option.get("type") == "null" for option in branch.get("anyOf", [])) and any(
            option.get("type") == "integer" and option.get("minimum") == 0 for option in branch.get("anyOf", [])
        ), relative
    return identity


def test_lifecycle_request_bodies_are_required_closed_models(ctx: Ctx):
    document = ctx.app.openapi()
    add = _request_schema(document, "post", ROOT)
    assert add.get("additionalProperties") is False and add["required"] == ["email"]
    assert add["properties"]["email"]["type"] == "string" and add["properties"]["email"]["maxLength"] == 254
    verify = _request_schema(document, "post", ROOT + "/{identity_id}/verify")
    assert verify.get("additionalProperties") is False and verify["required"] == ["code"]
    assert verify["properties"]["code"]["pattern"] == "^[0-9]{6}$"
    for path in (ROOT + "/{identity_id}/resend", ROOT + "/{identity_id}/primary"):
        empty = _request_schema(document, "post", path)
        assert empty.get("additionalProperties") is False and not empty.get("properties")
    assert "requestBody" not in document["paths"][ROOT + "/{identity_id}"]["delete"]
    start = _request_schema(document, "post", EMAIL_START)
    assert start.get("additionalProperties") is False and start["required"] == ["email"]


def test_lifecycle_response_schemas_publish_closed_enums(ctx: Ctx):
    document = ctx.app.openapi()
    for method, path, status, expected in (
        ("post", ROOT, "202", "accepted"),
        ("post", ROOT + "/{identity_id}/verify", "200", "verified"),
        ("post", ROOT + "/{identity_id}/resend", "202", "accepted"),
        ("delete", ROOT + "/{identity_id}", "200", "removed"),
        ("post", ROOT + "/{identity_id}/primary", "200", "primary"),
    ):
        schema = _response_schema(document, method, path, status)
        assert schema.get("additionalProperties") is False and set(schema["required"]) == {"status", "identity"}
        assert schema["properties"]["status"].get("enum") == [expected] or schema["properties"]["status"].get("const") == expected, (path, schema["properties"]["status"])
        _identity_schema(document, schema)
    listing = _response_schema(document, "get", ROOT, "200")
    assert set(listing["required"]) == {"login_channel_enabled", "max_identities", "identities"}
    assert listing.get("additionalProperties") is False
    items = _resolve(document, listing["properties"]["identities"]["items"])
    assert items["properties"]["state"]["enum"] == IDENTITY_STATES
    channels = _response_schema(document, "get", CHANNELS, "200")
    assert channels.get("additionalProperties") is False and channels["required"] == ["channels"]
    row = _resolve(document, channels["properties"]["channels"]["items"])
    assert row["properties"]["channel"]["enum"] == ["mobile", "email"] and row["properties"]["enabled"]["type"] == "boolean"
    start = _response_schema(document, "post", EMAIL_START, "202")
    assert set(start["required"]) >= {"status", "purpose", "destination_masked", "attempts_left", "expires_in_seconds", "resend_in_seconds", "locked_for_seconds", "resend_allowed"}


def test_runtime_matches_the_published_contract_with_auth_precedence_and_private_422(ctx: Ctx):
    anonymous = ctx.new_client()
    # Auth precedence: a malformed body from an anonymous caller is still 401, never 422.
    for path, body in ((ROOT, {"email": 5}), (ROOT + "/{}/verify".format("00000000-0000-4000-8000-000000000000"), {"code": "x"})):
        response = anonymous.post(path, json=body, headers={"Idempotency-Key": _key("openapi")})
        assert response.status_code == 401, (path, response.text)
    owner = ctx.client
    ctx.register_student(owner, "9876543210")
    for path, body in (
        (ROOT, {"email": 5}), (ROOT, {"email": "a@example.test", "extra": 1}), (ROOT, {}),
        (ROOT + "/00000000-0000-4000-8000-000000000000/verify", {"code": "12345"}),
        (ROOT + "/00000000-0000-4000-8000-000000000000/verify", {"code": "123456", "extra": True}),
        (ROOT + "/00000000-0000-4000-8000-000000000000/resend", {"code": "123456"}),
        (ROOT + "/00000000-0000-4000-8000-000000000000/primary", {"is_primary": True}),
    ):
        response = owner.post(path, json=body, headers={"Idempotency-Key": _key("openapi")})
        assert response.status_code == 422, (path, body, response.text)
        assert response.headers["cache-control"] == "private, no-store"
        assert "cookie" in {t.strip().casefold() for t in response.headers["vary"].split(",")}
        assert "example.test" not in response.text
    # A wrong-but-well-formed key on a well-formed body keeps its typed 422 with private headers.
    bad_key = owner.post(ROOT, json={"email": "a@example.test"}, headers={"Idempotency-Key": "short"})
    assert bad_key.status_code == 422 and bad_key.json()["detail"]["code"] == "invalid_idempotency_key"
    assert bad_key.headers["cache-control"] == "private, no-store"
