"""Strict wire contracts for the server-issued mentor ceremony (NYAY-22).

The models in this module implement the request and response shapes sealed by
NYAY-29 and reconciled by NYAY-33.  Browser-supplied identity, ownership,
scope, or session selectors are deliberately absent.  Every object is closed
so a future client field cannot silently become authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints


ContractVersion = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$",
    ),
]
MentorPurposeCode = Literal[
    "student_guidance",
    "legal_education",
    "document_review",
    "case_discussion",
]
MentorRole = Literal["tutor", "lawyer_tutor"]
MentorDisclosureClass = Literal[
    "display_identity",
    "preferred_language",
    "city",
    "education_context",
    "interests",
    "goals",
]
MentorScope = Literal[
    "engagement:read",
    "engagement:respond",
    "profile-slice:read",
    "consent:read",
    "session:rotate",
    "session:end",
]
MentorProfileSlice = Literal[
    "display_name",
    "preferred_language",
    "city",
    "college",
    "year_of_study",
    "interests",
    "goals",
]


class _ClosedContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
    )


def _exact_true(value: object) -> Literal[True]:
    """Refuse numeric/string truthiness at consent and step-up boundaries."""

    if type(value) is not bool or value is not True:
        raise ValueError("explicit acceptance must be the JSON Boolean true")
    return True


ExactTrue = Annotated[Literal[True], BeforeValidator(_exact_true)]


class MentorCeremonyInitiateRequest(_ClosedContract):
    intent: Literal["mentor_session"]
    requested_mentor_role: MentorRole = Field(alias="requestedMentorRole")
    purpose_code: MentorPurposeCode = Field(alias="purposeCode")
    privacy_notice_version: ContractVersion = Field(alias="privacyNoticeVersion")


class MentorIdentityProofRequest(_ClosedContract):
    expected_ceremony_state: Literal["challenge_issued"] = Field(
        alias="expectedCeremonyState"
    )


class MentorSessionExchangeRequest(_ClosedContract):
    intent: Literal["mentor_session"]
    expected_ceremony_state: Literal["proof_verified"] = Field(
        alias="expectedCeremonyState"
    )
    accept_purpose: ExactTrue = Field(alias="acceptPurpose")
    purpose_code: MentorPurposeCode = Field(alias="purposeCode")
    consent_receipt_version: ContractVersion = Field(alias="consentReceiptVersion")
    acceptance_text_version: ContractVersion = Field(alias="acceptanceTextVersion")


class MentorAuthorityStepUpExchangeRequest(_ClosedContract):
    intent: Literal["authority_deletion_step_up"]
    expected_ceremony_state: Literal["proof_verified"] = Field(
        alias="expectedCeremonyState"
    )
    accept_authority_deletion_step_up: ExactTrue = Field(
        alias="acceptAuthorityDeletionStepUp"
    )
    acceptance_text_version: ContractVersion = Field(alias="acceptanceTextVersion")


MentorExchangeRequest = Annotated[
    MentorSessionExchangeRequest | MentorAuthorityStepUpExchangeRequest,
    Field(discriminator="intent"),
]


class MentorLifecycleRequest(_ClosedContract):
    expected_session_state: Literal["active"] = Field(alias="expectedSessionState")
    purpose_code: MentorPurposeCode = Field(alias="purposeCode")
    reason_code: Literal[
        "routine_rotation",
        "mentor_requested",
        "purpose_complete",
        "suspected_compromise",
    ] = Field(alias="reasonCode")


class MentorSessionRecoveryRequest(_ClosedContract):
    intent: Literal["mentor_session"]
    requested_mentor_role: MentorRole = Field(alias="requestedMentorRole")
    purpose_code: MentorPurposeCode = Field(alias="purposeCode")
    recovery_method: Literal["fresh_external_identity"] = Field(alias="recoveryMethod")
    privacy_notice_version: ContractVersion = Field(alias="privacyNoticeVersion")


class MentorAuthorityDeletionStepUpRequest(_ClosedContract):
    intent: Literal["authority_deletion_step_up"]
    recovery_method: Literal["fresh_external_identity"] = Field(alias="recoveryMethod")
    step_up_notice_version: ContractVersion = Field(alias="stepUpNoticeVersion")


MentorRecoveryRequest = Annotated[
    MentorSessionRecoveryRequest | MentorAuthorityDeletionStepUpRequest,
    Field(discriminator="intent"),
]


class MentorAuthorityDeletionRequest(_ClosedContract):
    expected_session_state: Literal["active"] = Field(alias="expectedSessionState")
    expected_step_up_intent: Literal["authority_deletion_step_up"] = Field(
        alias="expectedStepUpIntent"
    )
    confirmation: Literal["delete_mentor_authority"]
    retention_notice_version: ContractVersion = Field(alias="retentionNoticeVersion")


class MentorCeremonyChallenge(_ClosedContract):
    schema_version: Literal["mentor-ceremony.v1"] = Field(alias="schemaVersion")
    status: Literal["accepted"]
    ceremony_state: Literal["challenge_issued"] = Field(alias="ceremonyState")
    next: Literal["external_identity"]
    intent: Literal["mentor_session", "authority_deletion_step_up"]
    expires_in_seconds: int = Field(alias="expiresInSeconds", ge=1, le=900)


class MentorVerificationProvenance(_ClosedContract):
    result: Literal["current_positive"]
    provenance_class: Literal[
        "nyayone_reviewed_identity",
        "approved_federated_attestation",
    ] = Field(alias="provenanceClass")
    policy_version: ContractVersion = Field(alias="policyVersion")
    verified_at: datetime = Field(alias="verifiedAt")
    current_at: datetime = Field(alias="currentAt")
    ownership_binding: Literal["tutor_profile_user_equals_actor"] = Field(
        alias="ownershipBinding"
    )


class MentorPurposeAcceptanceProjection(_ClosedContract):
    schema_version: Literal["mentor-acceptance.v1"] = Field(alias="schemaVersion")
    status: Literal["acceptance_required"]
    ceremony_state: Literal["proof_verified"] = Field(alias="ceremonyState")
    intent: Literal["mentor_session"]
    server_derived_mentor_role: MentorRole = Field(alias="serverDerivedMentorRole")
    purpose_code: MentorPurposeCode = Field(alias="purposeCode")
    consent_receipt_version: ContractVersion = Field(alias="consentReceiptVersion")
    disclosure_classes: list[MentorDisclosureClass] = Field(
        alias="disclosureClasses",
        max_length=7,
        json_schema_extra={"uniqueItems": True},
    )
    acceptance_text_version: ContractVersion = Field(alias="acceptanceTextVersion")
    verification: MentorVerificationProvenance
    expires_in_seconds: int = Field(alias="expiresInSeconds", ge=1, le=900)


class MentorDeletionStepUpAcceptanceProjection(_ClosedContract):
    schema_version: Literal["mentor-acceptance.v1"] = Field(alias="schemaVersion")
    status: Literal["acceptance_required"]
    ceremony_state: Literal["proof_verified"] = Field(alias="ceremonyState")
    intent: Literal["authority_deletion_step_up"]
    deletion_scope: Literal["global_mentor_authority"] = Field(alias="deletionScope")
    acceptance_text_version: ContractVersion = Field(alias="acceptanceTextVersion")
    verification: MentorVerificationProvenance
    expires_in_seconds: int = Field(alias="expiresInSeconds", ge=1, le=300)


MentorAcceptanceProjection = Annotated[
    MentorPurposeAcceptanceProjection | MentorDeletionStepUpAcceptanceProjection,
    Field(discriminator="intent"),
]


class MentorConsentProjection(_ClosedContract):
    purpose_code: MentorPurposeCode = Field(alias="purposeCode")
    version: ContractVersion
    status: Literal["granted"]
    recorded_at: datetime = Field(alias="recordedAt")


class MentorSessionProjection(_ClosedContract):
    schema_version: Literal["mentor-session.v1"] = Field(alias="schemaVersion")
    session_class: Literal["mentor"] = Field(alias="sessionClass")
    mentor_role: MentorRole = Field(alias="mentorRole")
    state: Literal["active"]
    purpose_code: MentorPurposeCode = Field(alias="purposeCode")
    scopes: list[MentorScope] = Field(
        min_length=1,
        max_length=8,
        json_schema_extra={"uniqueItems": True},
    )
    permitted_profile_slices: list[MentorProfileSlice] = Field(
        alias="permittedProfileSlices",
        max_length=7,
        json_schema_extra={"uniqueItems": True},
    )
    same_actor_verified: Literal[True] = Field(alias="sameActorVerified")
    tutor_profile_status: Literal["active"] = Field(alias="tutorProfileStatus")
    verification: MentorVerificationProvenance
    subject_sharing_eligibility: Literal["allowed"] = Field(
        alias="subjectSharingEligibility"
    )
    consent: MentorConsentProjection
    absolute_lifetime_seconds: int = Field(
        alias="absoluteLifetimeSeconds", ge=1, le=28_800
    )
    idle_timeout_seconds: int = Field(alias="idleTimeoutSeconds", ge=1, le=1_800)
    issued_at: datetime = Field(alias="issuedAt")
    expires_at: datetime = Field(alias="expiresAt")


class MentorAuthorityStepUpProjection(_ClosedContract):
    schema_version: Literal["mentor-authority-step-up.v1"] = Field(
        alias="schemaVersion"
    )
    status: Literal["step_up_ready"]
    intent: Literal["authority_deletion_step_up"]
    deletion_scope: Literal["global_mentor_authority"] = Field(alias="deletionScope")
    same_actor_verified: Literal[True] = Field(alias="sameActorVerified")
    verification: MentorVerificationProvenance
    expires_in_seconds: int = Field(alias="expiresInSeconds", ge=1, le=300)


class MentorRevokedOutcome(_ClosedContract):
    schema_version: Literal["mentor-lifecycle.v1"] = Field(alias="schemaVersion")
    action: Literal["revoked"]
    state: Literal["revoked"]
    session_authority_present: Literal[False] = Field(alias="sessionAuthorityPresent")
    audit_event_recorded: Literal[True] = Field(alias="auditEventRecorded")
    effective_at: datetime = Field(alias="effectiveAt")


class MentorLoggedOutOutcome(_ClosedContract):
    schema_version: Literal["mentor-lifecycle.v1"] = Field(alias="schemaVersion")
    action: Literal["logged_out"]
    state: Literal["logged_out"]
    session_authority_present: Literal[False] = Field(alias="sessionAuthorityPresent")
    audit_event_recorded: Literal[True] = Field(alias="auditEventRecorded")
    effective_at: datetime = Field(alias="effectiveAt")


class MentorAuthorityDeletionOutcome(_ClosedContract):
    schema_version: Literal["mentor-lifecycle.v1"] = Field(alias="schemaVersion")
    action: Literal["authority_deletion_scheduled"]
    state: Literal["deletion_pending"]
    session_authority_present: Literal[False] = Field(alias="sessionAuthorityPresent")
    step_up_authority_present: Literal[False] = Field(alias="stepUpAuthorityPresent")
    audit_event_recorded: Literal[True] = Field(alias="auditEventRecorded")
    effective_at: datetime = Field(alias="effectiveAt")


MentorLifecycleOutcome = Annotated[
    MentorRevokedOutcome | MentorLoggedOutOutcome | MentorAuthorityDeletionOutcome,
    Field(discriminator="action"),
]


MentorFailureCode = Literal[
    "INVALID_REQUEST",
    "INVALID_IDEMPOTENCY_KEY",
    "ORIGIN_REJECTED",
    "AUTHENTICATION_REQUIRED",
    "AUTHORIZATION_DENIED",
    "RESOURCE_UNAVAILABLE",
    "IDEMPOTENCY_CONFLICT",
    "CONCURRENT_STATE_CHANGED",
    "CEREMONY_REPLAYED",
    "SESSION_CONFLICT",
    "SESSION_STALE",
    "SESSION_EXPIRED",
    "AUTHORITY_TERMINAL",
    "STEP_UP_REQUIRED",
    "STEP_UP_EXPIRED",
    "RATE_LIMITED",
    "PROVIDER_UNAVAILABLE",
]


class MentorFailureDetail(_ClosedContract):
    code: MentorFailureCode
    message: Literal["Request failed"]
    retryable: bool
    field: Literal["Idempotency-Key", "Origin", "request"] | None = None
    retry_after_seconds: int | None = Field(
        default=None,
        alias="retryAfterSeconds",
        ge=1,
        le=900,
    )


class MentorFailure(_ClosedContract):
    detail: MentorFailureDetail
