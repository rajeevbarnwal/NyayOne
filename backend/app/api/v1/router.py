"""Aggregates all v1 API routers under a single api_router mounted at /api/v1."""
from fastapi import APIRouter

from app.api.v1.auth_student import router as auth_student_router
from app.api.v1.health import router as health_router
from app.api.v1.integrations import router as integrations_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(integrations_router)
api_router.include_router(auth_student_router)
