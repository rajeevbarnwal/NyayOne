"""Module-scoped, pre-materialised FastAPI apps for the per-test HTTP fixtures.

Why this exists
---------------
FastAPI >= 0.141 expands ``include_router`` lazily: the first request against a
fresh app builds that app's effective route table. On this router that costs
~38 ms, against ~2.5 ms for every request afterwards. Fixtures that mounted a
brand-new ``FastAPI()`` per test therefore paid the full 38 ms in every test --
around 3 s across the suite -- to rebuild an identical route table.

What changes and what does not
------------------------------
The app and its ``TestClient`` are built ONCE per module and the route table is
materialised eagerly (``materialise_routes`` is asserted non-empty, so a wiring
regression still fails loudly and fails at setup rather than inside a test).

Everything that is genuinely per-test stays per-test: the caller re-points
``app.dependency_overrides`` for each test, and that is what binds a request to
that test's engine, session class and storage adapter. ``fresh()`` clears the
client's cookie jar so no response state can carry across tests. This is the same
arrangement ``wave2_helpers.ApiRig`` already uses for the Wave 2 API files.
"""
from __future__ import annotations

from typing import Any

__all__ = ["mounted_app"]


def mounted_app(
    *,
    router: Any = None,
    prefix: str = "/api/v1",
    exception_handlers: bool = False,
    raise_server_exceptions: bool = True,
):
    """Build a mounted app + client and resolve its route table up front.

    Returns ``(app, client)``. Call :func:`fresh` at the start of every test that
    reuses them.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from tests.wave2_helpers import materialise_routes

    if router is None:
        from app.api.v1.router import api_router

        router = api_router

    app = FastAPI()
    if exception_handlers:
        from app.core.exceptions import register_exception_handlers

        register_exception_handlers(app)
    app.include_router(router, prefix=prefix)
    client = TestClient(app, raise_server_exceptions=raise_server_exceptions)
    assert materialise_routes(app) > 0  # a wiring regression fails HERE, loudly
    return app, client


def fresh(app, client) -> None:
    """Reset the per-test surface of a reused app/client pair."""
    app.dependency_overrides.clear()
    client.cookies.clear()
