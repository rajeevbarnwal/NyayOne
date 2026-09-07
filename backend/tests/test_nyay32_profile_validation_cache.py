"""Framework validation errors retain the owner-profile cache/privacy boundary."""
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.core.exceptions import register_exception_handlers
from tests.test_nyay9_owner_scoped_profile_api import (  # noqa: F401
    _activate_cookie, _headers, _mounted, _personal, _academic, _interests, nyay9_ctx,
)
from app.api.v1.student_settings import _require_empty_profile_query


OWNER_PATHS = (
    "/api/v1/student/profile",
    "/api/v1/student/profile/personal",
    "/api/v1/student/profile/academic",
    "/api/v1/student/profile/interests",
    "/api/v1/student/profile/prompt-dismiss",
    "/api/v1/auth/student/profile",
)


@pytest.mark.parametrize("path", [
    "/api/v1/student/profile/personal",
    "/api/v1/student/profile/academic",
    "/api/v1/student/profile/interests",
    "/api/v1/student/profile/prompt-dismiss",
    "/api/v1/auth/student/profile",
])
def test_framework_422_is_private_without_echoing_input(nyay9_ctx, path):
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="cache")
    response = nyay9_ctx["client"].request(
        "POST" if path.endswith("prompt-dismiss") else "PATCH", path,
        headers=_headers(idempotency_key="1b4e28ba-2fa1-4d90-a1bc-412f82ec25a0"),
        json={"unexpected": "private-sentinel@example.invalid"},
    )
    assert response.status_code == 422
    assert response.headers.get("cache-control") == "private, no-store"
    assert response.headers.get("vary") == "Cookie"
    assert "private-sentinel" not in response.text
    assert '"input"' not in response.text


@pytest.mark.parametrize("path", [
    "/api/v1/student/profile-other",
    "/api/v1/student/profile/personal/extra",
    "/api/v1/auth/student/profile-other",
    "/unrelated",
])
def test_header_scope_is_exact_not_a_prefix_allowlist(path):
    app = FastAPI()
    register_exception_handlers(app)
    app.post(path)(lambda payload: payload)
    # A required query argument generates the ordinary framework 422.
    response = TestClient(app).post(path)
    assert response.status_code == 422
    assert "cache-control" not in response.headers
    assert "vary" not in response.headers


def test_auth_and_origin_rejections_keep_precedence(nyay9_ctx):
    client = nyay9_ctx["client"]
    denied = client.patch("/api/v1/student/profile/personal", json={})
    assert denied.status_code == 401
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="origin")
    denied = client.patch("/api/v1/student/profile/personal", json={},
                          headers={"Origin": "https://untrusted.invalid"})
    assert denied.status_code == 403


@pytest.mark.parametrize("path", OWNER_PATHS)
def test_explicit_query_guard_422_is_private_on_exact_six_paths(path):
    app = FastAPI()
    register_exception_handlers(app)

    @app.get(path)
    def probe(request: Request):
        _require_empty_profile_query(request)
        raise AssertionError("query guard must reject")

    response = TestClient(app).get(path, params={"selector": "private-sentinel"})
    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "validation_error", "field": "query", "message": "Request failed",
    }
    assert "private-sentinel" not in response.text
    assert response.headers.get("cache-control") == "private, no-store"
    assert response.headers.get("vary") == "Cookie"


@pytest.mark.parametrize("method,path,payload", [
    ("GET", OWNER_PATHS[0], None),
    ("PATCH", OWNER_PATHS[1], _personal(1)),
    ("PATCH", OWNER_PATHS[2], _academic(1)),
    ("PATCH", OWNER_PATHS[3], _interests(1)),
    ("POST", OWNER_PATHS[4], {}),
])
def test_real_authenticated_profile_query_rejection_is_private(nyay9_ctx, method, path, payload):
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="query-cache")
    response = nyay9_ctx["client"].request(
        method, path, params={"selector": "private-sentinel"}, json=payload,
        headers=_headers(idempotency_key="profile-" + "a" * 48),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "query"
    assert "private-sentinel" not in response.text
    assert nyay9_ctx["owner_profile"].profile_version == 1
    assert response.headers.get("cache-control") == "private, no-store"
    assert response.headers.get("vary") == "Cookie"


@pytest.mark.parametrize("vary", [None, "Accept-Encoding", "Accept-Encoding, cookie"])
def test_scoped_422_preserves_unrelated_headers_and_existing_vary(vary):
    app = FastAPI()
    register_exception_handlers(app)
    original = {"cAcHe-CoNtRoL": "public, max-age=60", "X-Probe": "retained", "Retry-After": "7"}
    if vary is not None:
        original["vArY"] = vary
    before = dict(original)

    @app.get(OWNER_PATHS[0])
    def probe():
        raise HTTPException(422, detail={"code": "safe_probe"}, headers=original)

    response = TestClient(app).get(OWNER_PATHS[0])
    assert response.json()["detail"]["code"] == "safe_probe"
    assert response.headers["x-probe"] == "retained"
    assert response.headers["retry-after"] == "7"
    assert original == before
    assert response.headers.get_list("cache-control") == ["private, no-store"]
    tokens = [token.strip().lower() for token in response.headers["vary"].split(",")]
    assert tokens.count("cookie") == 1
    assert set(tokens) == ({"cookie"} if vary is None else {"cookie", "accept-encoding"})


@pytest.mark.parametrize("path,status", [
    ("/api/v1/student/profile-other", 422),
    ("/api/v1/student/profile/personal/extra", 422),
    ("/api/v1/auth/student/profile-other", 422),
    ("/unrelated", 422),
    (OWNER_PATHS[0], 401), (OWNER_PATHS[1], 403),
    (OWNER_PATHS[2], 409), (OWNER_PATHS[5], 429),
])
def test_unrelated_explicit_errors_preserve_status_body_and_headers(path, status):
    app = FastAPI()
    register_exception_handlers(app)
    original = {"Cache-Control": "no-cache", "Vary": "Origin", "X-Probe": "retained"}

    @app.get(path)
    def probe():
        raise HTTPException(status, detail={"code": "safe_probe"}, headers=original)

    response = TestClient(app).get(path)
    assert response.status_code == status
    assert response.json()["detail"] == {"code": "safe_probe", "message": "Request failed"}
    for key, value in original.items():
        assert response.headers[key] == value


def test_query_rejection_still_follows_session_and_origin_authority(nyay9_ctx):
    client = nyay9_ctx["client"]
    path = OWNER_PATHS[1] + "?selector=private-sentinel"
    assert client.patch(path, json=_personal(1)).status_code == 401
    _activate_cookie(nyay9_ctx, nyay9_ctx["owner"], token_suffix="query-origin")
    response = client.patch(path, json=_personal(1), headers={"Origin": "https://untrusted.invalid"})
    assert response.status_code == 403
    assert "private-sentinel" not in response.text
    assert nyay9_ctx["owner_profile"].profile_version == 1
