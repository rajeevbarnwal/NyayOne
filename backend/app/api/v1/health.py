from fastapi import APIRouter

from app.core.config import settings
from app.db.ping import check_database

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


@router.get("/health/db")
def health_check_db() -> dict[str, object]:
    """Developer probe: reports whether the database is reachable (non-fatal)."""
    return check_database()
