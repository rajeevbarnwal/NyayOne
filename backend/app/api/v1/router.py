"""Aggregates all v1 API routers under a single api_router mounted at /api/v1."""
from fastapi import APIRouter

from app.api.v1.auth_student import router as auth_student_router
from app.api.v1.auth_mentor import router as auth_mentor_router
from app.api.v1.credentials import router as credentials_router
from app.api.v1.law_schools import router as law_schools_router
from app.api.v1.law_schools import student as law_schools_student_router
from app.api.v1.student_settings import router as student_settings_router
from app.api.v1.tutoring import router as tutoring_router
from app.api.v1.health import router as health_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.internship_reports import router as internship_reports_router
from app.api.v1.moderation_reports import router as moderation_reports_router
from app.api.v1.risk_labels import router as risk_labels_router
from app.api.v1.calendar import router as calendar_router
from app.api.v1.internships import router as internships_router
from app.api.v1.internships import student as internships_student_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(integrations_router)
api_router.include_router(auth_student_router)
api_router.include_router(auth_mentor_router)
api_router.include_router(credentials_router)
api_router.include_router(student_settings_router)
api_router.include_router(law_schools_router)
api_router.include_router(law_schools_student_router)
api_router.include_router(tutoring_router)
api_router.include_router(internship_reports_router)
api_router.include_router(moderation_reports_router)
api_router.include_router(risk_labels_router)
api_router.include_router(calendar_router)
api_router.include_router(internships_router)
api_router.include_router(internships_student_router)
