"""ORM models. Importing this package registers all tables on Base.metadata."""
from app.db.models.audit import AuditEvent  # noqa: F401  (shared audit_events table)
from app.models.wave1 import (  # noqa: F401
    ComparisonItem, ComparisonSet, DataSubjectRequest, DeletionJob, ExportJob,
    LawSchool, LawSchoolFact, LawSchoolFollow, LawSchoolProgramme, LawSchoolSource,
    PrivacyPreference, SavedLawSchool, UserSettings,
)
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
from app.models.credentials import (  # noqa: F401
    Credential, CredentialEvidence, CredentialEvidenceScanEvent,
    CredentialIssuer, CredentialOutbox, CredentialReminderJob,
    CredentialRevocation, CredentialShareProjection, CredentialStatusHistory,
    CredentialVerificationEvent, IssuerAuthorisation, VerificationAccessLog,
    VerificationToken,
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
    "CredentialIssuer",
    "Credential",
    "CredentialEvidence",
    "CredentialStatusHistory",
    "CredentialShareProjection",
    "CredentialOutbox",
    "CredentialReminderJob",
    "CredentialEvidenceScanEvent",
    "IssuerAuthorisation",
    "CredentialVerificationEvent",
    "VerificationToken",
    "CredentialRevocation",
    "VerificationAccessLog",
]
