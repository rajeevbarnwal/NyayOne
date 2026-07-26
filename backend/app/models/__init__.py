"""ORM models. Importing this package registers all tables on Base.metadata."""
from app.db.models.audit import AuditEvent  # noqa: F401  (shared audit_events table)
from app.models.registration import (  # noqa: F401
    Consent,
    GuardianConsent,
    OtpChallenge,
    OtpOutbox,
    RecoverySession,
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
    "OtpOutbox",
    "RecoverySession",
    "Consent",
    "StudentVerification",
    "GuardianConsent",
    "AuditEvent",
]
