"""Request middleware: assigns a correlation/request ID and logs each request."""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger, request_id_ctx

logger = get_logger("legalsaathi.request")

REQUEST_ID_HEADER = "X-Request-ID"


def redact_sensitive_path(path: str) -> str:
    """Keep bearer/share tokens out of ordinary request logs."""
    for prefix in (
        "/api/v1/public/credential-verifications/",
        "/api/v1/public/calendar-feeds/",
        "/verify/",
    ):
        if path.startswith(prefix):
            return f"{prefix}:token"
    return path


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach an incoming or generated request ID to the context and response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": redact_sensitive_path(request.url.path),
                    "elapsed_ms": elapsed_ms,
                },
            )
            request_id_ctx.reset(token)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
