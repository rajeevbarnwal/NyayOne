"""ORM models. Importing this package registers all tables on Base.metadata."""
from app.models.registration import (  # noqa: F401
    StudentAuditEvent,
    Consent,
    GuardianConsent,
    OtpChallenge,
    StudentProfile,
    StudentRegistration,
    StudentVerification,
    User,
)

__all__ = [
    "User",
    "StudentRegistration",
    "StudentProfile",
    "OtpChallenge",
    "Consent",
    "StudentVerification",
    "GuardianConsent",
    "StudentAuditEvent",
]
