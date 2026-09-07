"""Framework validation errors retain the owner-profile cache/privacy boundary."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import register_exception_handlers
from tests.test_nyay9_owner_scoped_profile_api import (  # noqa: F401
    _activate_cookie, _headers, _mounted, nyay9_ctx,
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
