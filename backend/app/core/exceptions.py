"""Baseline exception handling that returns structured, request-id-tagged errors."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_ctx

logger = get_logger("legalsaathi.error")


def _error_body(code: str, message: str, detail: object | None = None) -> dict[str, object]:
    body: dict[str, object] = {
        "error": {"code": code, "message": message},
        "request_id": request_id_ctx.get(),
    }
    if detail is not None:
        body["error"]["detail"] = detail
    return body


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("http_error", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_body("validation_error", "Request validation failed", exc.errors()),
        )

    @app.exception_handler(Exception)
    async def _unhandled_exc(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception")
        return JSONResponse(
            status_code=500,
            content=_error_body("internal_error", "An unexpected error occurred"),
        )
