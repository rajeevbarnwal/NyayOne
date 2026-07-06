from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """Readiness/liveness detail for the API v1 surface."""
    return {
        "status": "ok",
        "service": "legalsaathi-backend",
        "version": settings.app_version,
        "environment": settings.app_env,
    }
