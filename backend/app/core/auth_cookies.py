"""Single source of truth for destructive auth-cookie attributes."""
from __future__ import annotations

from fastapi import Response

from app.core.config import settings


def cookie_secure() -> bool:
    return (settings.app_env or "").strip().lower() not in {
        "local",
        "development",
        "dev",
        "test",
        "testing",
    }


def clear_auth_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_session_cookie_name,
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite="lax",
    )
    clear_legacy_auth_session_cookie(response)


def clear_legacy_auth_session_cookie(response: Response) -> None:
    """Expire the pre-NYAY-8 path-scoped actor cookie during migration."""

    response.delete_cookie(
        key=settings.auth_session_cookie_name,
        path="/api/v1",
        secure=cookie_secure(),
        httponly=True,
        samesite="strict",
    )


def clear_otp_flow_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.otp_flow_cookie_name,
        path="/api/v1",
        secure=cookie_secure(),
        httponly=True,
        samesite="strict",
    )
