from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_liveness() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_api_v1_health() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "legalsaathi-backend"
    assert "version" in body
    assert "environment" in body


def test_request_id_header_present() -> None:
    response = client.get("/health")
    assert response.headers.get("X-Request-ID")


def test_request_id_exposed_via_cors() -> None:
    """Browser JS must be able to read X-Request-ID cross-origin, so CORS must
    expose it. A cross-origin request advertises the exposed header via
    access-control-expose-headers, and the header itself is still returned."""
    origin = "http://localhost:1030"
    for path in ("/health", "/api/v1/health"):
        response = client.get(path, headers={"Origin": origin})
        assert response.status_code == 200
        assert response.headers.get("X-Request-ID")
        exposed = response.headers.get("access-control-expose-headers", "")
        assert "X-Request-ID" in exposed
