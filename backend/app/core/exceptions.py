"""Privacy-safe exception handling with stable, typed API error contracts."""
from __future__ import annotations

import re
from collections.abc import Mapping

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_ctx

logger = get_logger("nyayone.error")

# Closed owner-profile surface: framework errors happen before route handlers
# can attach their private projection headers. Do not expand this by prefix.
_OWNER_PROFILE_VALIDATION_PATHS = frozenset({
    "/api/v1/student/profile",
    "/api/v1/student/profile/personal",
    "/api/v1/student/profile/academic",
    "/api/v1/student/profile/interests",
    "/api/v1/student/profile/prompt-dismiss",
    "/api/v1/auth/student/profile",
    "/api/v1/auth/student/email-identities",
})
# Closed set of *route templates* (exact match on the matched route's path
# template, never a prefix) for NYAY-12 lifecycle routes whose path carries an
# identity id. Framework 422s on these keep the private projection headers.
_OWNER_PROFILE_VALIDATION_ROUTES = frozenset({
    "/api/v1/auth/student/email-identities/{identity_id}/verify",
    "/api/v1/auth/student/email-identities/{identity_id}/resend",
    "/api/v1/auth/student/email-identities/{identity_id}/primary",
    "/api/v1/auth/student/email-identities/{identity_id}",
})


_OWNER_PROFILE_VALIDATION_ROUTE_PATTERNS = tuple(
    re.compile("^" + re.escape(template).replace(r"\{identity_id\}", "[^/]+") + "$")
    for template in sorted(_OWNER_PROFILE_VALIDATION_ROUTES)
)


def _owner_validation_surface(request: Request) -> bool:
    """Exact path or full match on one closed route template; never a prefix."""

    path = request.url.path
    if path in _OWNER_PROFILE_VALIDATION_PATHS:
        return True
    return any(pattern.fullmatch(path) for pattern in _OWNER_PROFILE_VALIDATION_ROUTE_PATTERNS)


def _detail_body(detail: Mapping[str, object]) -> dict[str, object]:
    """Return the single error envelope consumed by browser/API clients."""
    return {"detail": dict(detail), "request_id": request_id_ctx.get()}


def _safe_validation_errors(exc: RequestValidationError) -> list[dict[str, object]]:
    """Expose validation metadata without echoing submitted PII.

    Pydantic's default ``errors()`` payload contains the rejected ``input`` and
    occasionally a context object. Registration inputs include mobile, DOB,
    email and enrolment identifiers, so neither is safe to return or log.
    """
    safe: list[dict[str, object]] = []
    for error in exc.errors():
        safe.append(
            {
                "type": str(error.get("type", "value_error")),
                "loc": [str(part) for part in error.get("loc", ())],
                "msg": str(error.get("msg", "Invalid value")),
            }
        )
    return safe


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, Mapping):
            detail = dict(exc.detail)
            detail.setdefault("code", "http_error")
            detail.setdefault("message", "Request failed")
        else:
            detail = {"code": "http_error", "message": str(exc.detail)}
        response = JSONResponse(
            status_code=exc.status_code,
            content=_detail_body(detail),
            headers=exc.headers,
        )
        if exc.status_code == 422 and _owner_validation_surface(request):
            # Exception responses replace the route's Response object, including
            # its headers. Retain unrelated exception headers and Vary tokens.
            response.headers["Cache-Control"] = "private, no-store"
            vary = ", ".join(response.headers.getlist("vary"))
            if "cookie" not in {token.strip().lower() for token in vary.split(",")}:
                vary = f"{vary}, Cookie" if vary else "Cookie"
            response.headers["Vary"] = vary
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = _safe_validation_errors(exc)
        field = next(
            (
                str(error["loc"][-1])
                for error in errors
                if error.get("loc")
            ),
            None,
        )
        detail: dict[str, object] = {
            "code": "validation_error",
            "message": "Request validation failed",
            "errors": errors,
        }
        if field is not None:
            detail["field"] = field
        return JSONResponse(
            status_code=422,
            content=_detail_body(detail),
            headers=(
                {"Cache-Control": "private, no-store", "Vary": "Cookie"}
                if _owner_validation_surface(request)
                else None
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception")
        return JSONResponse(
            status_code=500,
            content=_detail_body(
                {"code": "internal_error", "message": "An unexpected error occurred"}
            ),
        )
