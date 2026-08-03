"""Governed SAATHI-279 risk-label service.

The public mutation/projection boundary remains deliberately closed by the
binding Product decision.  Candidate review is functional and audited; every
publication/response entry point fails before querying or mutating data.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import ActorContext, Role
from app.core.config import is_isolated_wave4_database_url, settings
from app.core.crypto import decrypt, encrypt, key_version, keyed_hash
from app.models.registration import User
from app.models.wave4 import (
    DuplicateCluster,
    DuplicateClusterMember,
    InternshipReport,
    InternshipReportCategory,
    InternshipReportEvidence,
    ModerationCase,
    NotificationOutbox,
    OrganisationResponse,
    OrganisationResponseRequest,
    PublicationDecision,
    PublishedRiskLabel,
    ResponseModeration,
    RiskSignal,
    RiskSignalApproval,
    ReporterIdentityVault,
)
from app.schemas.risk_labels import (
    OrganisationResponseDecisionIn,
    OrganisationResponseIn,
    OrganisationResponseOut,
    OrganisationResponseRequestIn,
    OrganisationResponseRequestOut,
    PublicOrganisationResponseOut,
    PublicRiskLabelOut,
    PublicRiskLabelsOut,
    PublishedRiskLabelOut,
    RiskLabelCandidateListOut,
    RiskLabelCandidateOut,
    RiskLabelPublishIn,
)
from app.services.audit_service import record_audit_event
from app.services.moderation_service import _months_ago, safe_idempotency
from app.services.organisation_identity import (
    OrganisationIdentityIntegrityError,
    decrypt_bound_organisation,
    normalise_organisation,
    public_organisation_id,
    representative_verification_hash,
)

_NEUTRAL_LABELS = {
    "unpaid_mismatch": "Moderated unpaid or stipend mismatch pattern",
    "excessive_hours": "Moderated excessive-hours pattern",
    "unsafe_environment": "Moderated workplace-safety pattern",
    "harassment": "Moderated workplace-conduct pattern",
    "discrimination": "Moderated equal-treatment concern pattern",
    "misleading_work": "Moderated role-description mismatch pattern",
    "non_response": "Moderated organisation non-response pattern",
    "certificate_withheld": "Moderated certificate-delay pattern",
    "stipend_delay_exploitative": "Moderated stipend-delay pattern",
    "positive_experience": "Moderated positive-experience pattern",
}


@dataclass(frozen=True)
class RiskLabelError(Exception):
    status_code: int
    code: str
    message: str
    retryable: bool = False
    current_version: int | None = None


def _require_moderator(actor: ActorContext) -> None:
    if not actor.is_authenticated:
        raise RiskLabelError(401, "authentication_required", "Authentication required")
    if not (actor.has_role(Role.MODERATOR) or actor.has_role(Role.ADMIN)):
        raise RiskLabelError(403, "moderator_role_required", "Moderator role required")


def _require_current_moderator(session: Session, actor: ActorContext) -> User:
    """Bind claimed moderation authority to the live account at decision time."""
    _require_moderator(actor)
    user = session.scalar(select(User).where(
        User.id == actor.user_id
    ).with_for_update())
    if (
        user is None
        or user.status != "active"
        or user.role not in {"moderator", "admin"}
        or not actor.has_role(Role(user.role))
    ):
        raise RiskLabelError(
            403,
            "response_moderator_not_active",
            "Response moderator is not active",
        )
    return user


def _require_publication_actor(actor: ActorContext) -> None:
    if not actor.is_authenticated:
        raise RiskLabelError(401, "authentication_required", "Authentication required")
    if not any(actor.has_role(role) for role in (
        Role.SAFETY_OFFICER, Role.LEGAL_REVIEWER, Role.ADMIN
    )):
        raise RiskLabelError(403, "risk_publication_role_required", "Risk publication role required")


def _require_current_publication_actor(
    session: Session, actor: ActorContext
) -> User:
    """Bind privileged claims to the live, locked account authority."""
    _require_publication_actor(actor)
    user = session.scalar(select(User).where(User.id == actor.user_id).with_for_update())
    allowed = {"safety_officer", "legal_reviewer", "admin"}
    if (
        user is None
        or user.status != "active"
        or user.role not in allowed
        or not actor.has_role(Role(user.role))
    ):
        raise RiskLabelError(
            403,
            "risk_publication_actor_not_active",
            "Risk publication actor is not active",
        )
    return user


def _audit_role(actor: ActorContext) -> str:
    for role in (Role.ADMIN, Role.SAFETY_OFFICER, Role.LEGAL_REVIEWER, Role.MODERATOR):
        if actor.has_role(role):
            return role.value
    return "authenticated"


def _fingerprint(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _verified_representative_attestation(
    actor: ActorContext,
    organisation_id: uuid.UUID,
    verification_method: str,
    delivery_ref: str,
) -> str:
    """Return the durable organisation-bound proof hash or fail closed.

    A request field is not proof by itself. Manual attestations require the
    legal-reviewer authority. The domain-challenge adapter is intentionally
    unavailable until a real verifier is bound. ``qa_fixture`` is an explicit
    deterministic verifier available only behind the isolated publication gate.
    """
    if verification_method == "manual_legal_review":
        if not actor.has_role(Role.LEGAL_REVIEWER):
            raise RiskLabelError(
                403,
                "representative_verification_authority_required",
                "Legal reviewer verification authority required",
            )
    elif verification_method == "verified_domain_challenge":
        raise RiskLabelError(
            422,
            "representative_verification_method_unavailable",
            "Representative verification method is unavailable",
        )
    elif verification_method == "qa_fixture":
        if not publication_gate_open() or not delivery_ref.casefold().startswith("qa-"):
            raise RiskLabelError(
                422,
                "representative_verification_method_unavailable",
                "Representative verification method is unavailable",
            )
    else:  # DB/service defence in depth if schema validation is bypassed.
        raise RiskLabelError(
            422,
            "representative_verification_method_unavailable",
            "Representative verification method is unavailable",
        )
    return representative_verification_hash(
        organisation_id, verification_method, delivery_ref
    )


def _published_out(row: PublishedRiskLabel) -> PublishedRiskLabelOut:
    return PublishedRiskLabelOut(
        id=row.id,
        organisation_id=row.organisation_id,
        category=row.category,
        neutral_label=row.neutral_label,
        public_count=row.public_count,
        status=row.status,
        last_reviewed_at=_as_utc(row.last_reviewed_at),
        published_at=_as_utc(row.published_at),
        version=row.version,
    )


def publication_gate_open() -> bool:
    # Production enablement remains impossible.  This seam exists exclusively
    # for target-runtime verification against a separately named QA database.
    environment = (settings.app_env or "").strip().casefold()
    test_url = (settings.test_database_url or "").strip()
    actual_url = (settings.database_url or "").strip()
    refs = (
        settings.wave4_security_approval_ref,
        settings.wave4_policy_approval_ref,
        settings.wave4_target_runtime_gate_ref,
    )
    return bool(
        not settings.internship_risk_labels_enabled
        and settings.wave4_gate_allow_publication_test
        and environment in {"test", "testing"}
        and is_isolated_wave4_database_url(actual_url)
        and test_url == actual_url
        and all((value or "").startswith("QA-") for value in refs)
    )


def require_publication_gate() -> None:
    if not publication_gate_open():
        raise RiskLabelError(
            503,
            "risk_labels_unavailable",
            "Public internship risk labels are not available",
            retryable=False,
        )


def _void_response_invitation_outboxes(
    session: Session,
    request_ids: list[uuid.UUID],
    *,
    reason_code: str,
) -> int:
    """Terminally erase bearer material for obsolete invitations.

    This helper is intentionally used by both label revocation and invitation
    renewal.  Expiring a request without voiding its outbox would leave an
    encrypted but still relayable bearer token behind when the provider is
    disabled or a worker is delayed.
    """
    if not request_ids:
        return 0
    outboxes = list(session.scalars(select(NotificationOutbox).where(
        NotificationOutbox.aggregate_type == "organisation_response_request",
        NotificationOutbox.aggregate_id.in_(request_ids),
        NotificationOutbox.event_kind == "organisation_response_requested",
        NotificationOutbox.state.in_(("pending", "processing", "failed")),
        NotificationOutbox.deleted_at.is_(None),
    ).order_by(NotificationOutbox.id).with_for_update()))
    for outbox in outboxes:
        outbox.state = "void"
        outbox.claimed_at = None
        outbox.claim_token = None
        outbox.available_at = None
        outbox.secret_ciphertext = None
        outbox.secret_key_version = None
        outbox.last_error_code = reason_code
    return len(outboxes)


def _revoke_label_response_work(
    session: Session,
    label_id: uuid.UUID,
    *,
    now: datetime,
    reason_code: str,
) -> tuple[int, int]:
    """Cancel unfinished representative work and erase delivery secrets.

    Called while the label row is locked.  Invitation payloads contain ids
    only; encrypted delivery material is irreversibly erased on revocation.
    """
    requests = list(session.scalars(select(OrganisationResponseRequest).where(
        OrganisationResponseRequest.published_label_id == label_id,
        OrganisationResponseRequest.state == "pending",
        OrganisationResponseRequest.deleted_at.is_(None),
    ).order_by(OrganisationResponseRequest.id).with_for_update()))
    request_ids = [row.id for row in requests]
    for row in requests:
        row.state = "revoked"
        row.version += 1
    _void_response_invitation_outboxes(
        session, request_ids, reason_code=reason_code
    )
    pending_responses = list(session.scalars(select(OrganisationResponse).where(
        OrganisationResponse.published_label_id == label_id,
        OrganisationResponse.state == "moderation_pending",
        OrganisationResponse.deleted_at.is_(None),
    ).order_by(OrganisationResponse.id).with_for_update()))
    for response in pending_responses:
        response.state = "rejected"
        response.is_current = False
        response.moderated_at = now
        response.version += 1
    return len(requests), len(pending_responses)


def list_risk_label_candidates(
    session: Session, actor: ActorContext
) -> RiskLabelCandidateListOut:
    _require_moderator(actor)
    rows = list(session.execute(
        select(RiskSignal, DuplicateCluster)
        .join(DuplicateCluster, DuplicateCluster.id == RiskSignal.cluster_id)
        .where(RiskSignal.deleted_at.is_(None), DuplicateCluster.deleted_at.is_(None))
        .order_by(RiskSignal.created_at, RiskSignal.id)
    ).all())
    items: list[RiskLabelCandidateOut] = []
    for signal, cluster in rows:
        try:
            organisation_name = decrypt_bound_organisation(
                cluster.organisation_ciphertext, cluster.organisation_hash
            )
        except OrganisationIdentityIntegrityError:
            # A corrupted/swapped organisation identity is not a candidate.
            # Suppress it rather than exposing or approving the wrong entity.
            continue
        if (
            _NEUTRAL_LABELS.get(cluster.category) is None
            or signal.neutral_label != _NEUTRAL_LABELS[cluster.category]
        ):
            continue
        label = session.scalar(select(PublishedRiskLabel).where(
            PublishedRiskLabel.risk_signal_id == signal.id,
            PublishedRiskLabel.deleted_at.is_(None),
        ))
        items.append(RiskLabelCandidateOut(
            cluster_id=cluster.id,
            risk_signal_id=signal.id,
            organisation_id=public_organisation_id(organisation_name),
            organisation_name=organisation_name,
            category=cluster.category,
            neutral_label=_NEUTRAL_LABELS[cluster.category],
            report_count=signal.report_count,
            distinct_reporter_count=signal.distinct_reporter_count,
            public_count=None if signal.small_count_suppressed else signal.report_count,
            threshold_met=signal.threshold_met,
            small_count_suppressed=signal.small_count_suppressed,
            moderator_approved=signal.moderator_approved,
            safety_legal_approved=signal.safety_legal_approved,
            approval_vetoed=signal.approval_vetoed,
            publication_ready=False,
            published_label_id=label.id if label else None,
            status=label.status if label else "not_published",
            version=signal.version,
        ))
    record_audit_event(
        session,
        action="risk_label_candidate_queue_viewed",
        resource_type="risk_label_candidate_queue",
        actor_user_id=actor.user_id,
        actor_role=_audit_role(actor),
        after_state={
            "result_count": len(items),
            "publication_gate_open": publication_gate_open(),
        },
    )
    session.commit()
    return RiskLabelCandidateListOut(
        items=items, total=len(items), publication_gate_open=publication_gate_open()
    )


def publish_risk_label(
    session: Session,
    actor: ActorContext,
    cluster_id: uuid.UUID,
    payload: RiskLabelPublishIn,
    idempotency_key: str | None,
) -> PublishedRiskLabelOut:
    require_publication_gate()
    _require_publication_actor(actor)
    key = safe_idempotency(idempotency_key)
    fingerprint = _fingerprint({
        "cluster_id": cluster_id,
        "actor_id": actor.user_id,
        **payload.model_dump(),
    })
    prior = session.scalar(select(PublicationDecision).where(
        PublicationDecision.idempotency_key == key
    ))
    if prior:
        if prior.request_fingerprint != fingerprint or prior.published_label_id is None:
            raise RiskLabelError(409, "idempotency_conflict", "Idempotency key already used")
        row = session.get(PublishedRiskLabel, prior.published_label_id)
        if row is None:
            raise RiskLabelError(409, "publication_state_conflict", "Publication state conflicted")
        return _published_out(row)
    cluster = session.scalar(select(DuplicateCluster).where(
        DuplicateCluster.id == cluster_id,
        DuplicateCluster.deleted_at.is_(None),
    ).with_for_update())
    if cluster is None:
        raise RiskLabelError(404, "risk_cluster_not_found", "Risk cluster not found")
    signal = session.scalar(select(RiskSignal).where(
        RiskSignal.cluster_id == cluster.id,
        RiskSignal.deleted_at.is_(None),
    ).with_for_update())
    if signal is None:
        raise RiskLabelError(404, "risk_cluster_not_found", "Risk cluster not found")
    # Re-read the idempotency decision after waiting for cluster/signal locks.
    # Under READ COMMITTED, a concurrent winner is now visible and must be
    # returned before the existing-label guard classifies the request.
    prior = session.scalar(select(PublicationDecision).where(
        PublicationDecision.idempotency_key == key
    ))
    if prior:
        if (
            prior.actor_user_id != actor.user_id
            or prior.risk_signal_id != signal.id
            or prior.request_fingerprint != fingerprint
            or prior.published_label_id is None
        ):
            raise RiskLabelError(409, "idempotency_conflict", "Idempotency key already used")
        winner = session.get(PublishedRiskLabel, prior.published_label_id)
        if winner is None:
            raise RiskLabelError(409, "publication_state_conflict", "Publication state conflicted")
        return _published_out(winner)
    if signal.version != payload.expected_version:
        raise RiskLabelError(409, "stale_risk_signal", "Risk signal changed", current_version=signal.version)
    existing_label = session.scalar(select(PublishedRiskLabel).where(
        PublishedRiskLabel.risk_signal_id == signal.id,
        PublishedRiskLabel.deleted_at.is_(None),
    ).with_for_update())
    if payload.action == "withdraw":
        # Governed aggregate rows lock before authority rows everywhere in the
        # risk-label domain, preventing label/user lock inversion with response
        # invitation creation and concurrent publication decisions.
        _require_current_publication_actor(session, actor)
        if existing_label is None or existing_label.status == "withdrawn":
            raise RiskLabelError(409, "risk_label_not_withdrawable", "Risk label is not withdrawable")
        now = datetime.now(timezone.utc)
        existing_label.status = "withdrawn"
        existing_label.last_reviewed_at = now
        existing_label.version += 1
        revoked_requests, rejected_responses = _revoke_label_response_work(
            session,
            existing_label.id,
            now=now,
            reason_code="label_withdrawn",
        )
        session.add(PublicationDecision(
            risk_signal_id=signal.id,
            published_label_id=existing_label.id,
            actor_user_id=actor.user_id,
            decision="withdraw",
            reason_code=payload.reason_code,
            idempotency_key=key,
            expected_version=payload.expected_version,
            request_fingerprint=fingerprint,
        ))
        session.add(NotificationOutbox(
            aggregate_type="published_risk_label",
            aggregate_id=existing_label.id,
            event_kind="risk_label_withdrawn",
            idempotency_key=f"notification:{key}",
            payload_json={"label_id": str(existing_label.id), "status": "withdrawn"},
            available_at=now,
        ))
        record_audit_event(
            session, action="risk_label_withdrawn", resource_type="published_risk_label",
            resource_id=existing_label.id, actor_user_id=actor.user_id,
            actor_role=_audit_role(actor), after_state={
                "status": "withdrawn",
                "version": existing_label.version,
                "revoked_request_count": revoked_requests,
                "rejected_pending_response_count": rejected_responses,
            },
        )
        session.commit()
        return _published_out(existing_label)
    decisions = list(session.scalars(select(RiskSignalApproval).where(
        RiskSignalApproval.risk_signal_id == signal.id,
        RiskSignalApproval.deleted_at.is_(None),
    ).order_by(RiskSignalApproval.id)))
    approver_ids = sorted(
        {actor.user_id, *(item.actor_user_id for item in decisions)}, key=str
    )
    approval_users = {
        user.id: user
        for user in session.scalars(select(User).where(
            User.id.in_(approver_ids)
        ).order_by(User.id).with_for_update())
    } if approver_ids else {}
    acting_user = approval_users.get(actor.user_id)
    if (
        acting_user is None
        or acting_user.status != "active"
        or acting_user.role not in {"safety_officer", "legal_reviewer", "admin"}
        or not actor.has_role(Role(acting_user.role))
    ):
        raise RiskLabelError(
            403,
            "risk_publication_actor_not_active",
            "Risk publication actor is not active",
        )
    valid_decisions = [
        item for item in decisions
        if (
            (user := approval_users.get(item.actor_user_id)) is not None
            and user.status == "active"
            and user.role == item.actor_role
        )
    ]
    # A recorded rejection remains a veto even if its actor later leaves; an
    # approval, however, contributes to the live quorum only while the account
    # and role remain active/current.
    vetoed = signal.approval_vetoed or any(
        item.decision == "reject" for item in decisions
    )
    moderator_ok = any(
        item.actor_role == "moderator" and item.decision == "approve"
        for item in valid_decisions
    )
    safety_legal_ok = any(
        item.actor_role in {"safety_officer", "legal_reviewer"}
        and item.decision == "approve" for item in valid_decisions
    )
    members = list(session.scalars(select(DuplicateClusterMember).where(
        DuplicateClusterMember.cluster_id == cluster.id,
        DuplicateClusterMember.deleted_at.is_(None),
    ).order_by(DuplicateClusterMember.id).with_for_update()))
    member_ids = [member.report_id for member in members]
    # Canonical source order is report -> case; secondary source rows follow.
    # This matches moderation mutations and prevents publish-vs-moderation
    # deadlocks while the live source snapshot is revalidated.
    reports = list(session.scalars(select(InternshipReport).where(
        InternshipReport.id.in_(member_ids), InternshipReport.deleted_at.is_(None)
    ).order_by(InternshipReport.id).with_for_update()))
    cases = list(session.scalars(select(ModerationCase).where(
        ModerationCase.report_id.in_(member_ids), ModerationCase.deleted_at.is_(None)
    ).order_by(ModerationCase.report_id, ModerationCase.id).with_for_update()))
    evidence_rows = list(session.scalars(select(InternshipReportEvidence).where(
        InternshipReportEvidence.report_id.in_(member_ids),
        InternshipReportEvidence.deleted_at.is_(None),
    ).order_by(InternshipReportEvidence.report_id, InternshipReportEvidence.id).with_for_update()))
    evidence_states = {report_id: [] for report_id in member_ids}
    for evidence in evidence_rows:
        evidence_states[evidence.report_id].append(evidence.scan_state)
    evidence_ok = bool(member_ids) and all(
        states and "clean" in states and all(state == "clean" for state in states)
        for states in evidence_states.values()
    )
    vaults = list(session.scalars(select(ReporterIdentityVault).where(
        ReporterIdentityVault.report_id.in_(member_ids), ReporterIdentityVault.deleted_at.is_(None)
    ).order_by(ReporterIdentityVault.report_id, ReporterIdentityVault.id).with_for_update()))
    reporter_hashes = {row.reporter_lookup_hash for row in vaults}
    category_rows = list(session.scalars(select(InternshipReportCategory).where(
        InternshipReportCategory.report_id.in_(member_ids),
        InternshipReportCategory.category == cluster.category,
        InternshipReportCategory.deleted_at.is_(None),
    ).order_by(InternshipReportCategory.report_id, InternshipReportCategory.id).with_for_update()))
    categories = {row.report_id for row in category_rows}
    cutoff = _months_ago(
        datetime.now(timezone.utc).date(), settings.internship_risk_window_months
    )
    dates = [report.experience_end_date or report.experience_start_date for report in reports]
    current_organisation_hashes = {
        keyed_hash(normalise_organisation(report.organisation_name), lower=True)
        for report in reports
    }
    try:
        organisation_name = decrypt(cluster.organisation_ciphertext)
    except Exception:
        organisation_name = ""
    cluster_identity_bound = (
        bool(organisation_name)
        and keyed_hash(normalise_organisation(organisation_name), lower=True)
        == cluster.organisation_hash
    )
    live_sources_ok = (
        bool(member_ids)
        and
        len(reports) == len(member_ids)
        and len(cases) == len(member_ids)
        and len(vaults) == len(member_ids)
        and all(report.status == "approved" for report in reports)
        and all(case.state == "approved_aggregate_only" for case in cases)
        and all(member.category == cluster.category for member in members)
        and len(categories) == len(member_ids)
        and len(reporter_hashes) >= settings.internship_risk_min_distinct_reporters
        and all(value is not None and value >= cutoff for value in dates)
        and current_organisation_hashes == {cluster.organisation_hash}
        and cluster_identity_bound
        and min(dates) == cluster.window_start
        and max(dates) == cluster.window_end
        and signal.report_count == len(member_ids)
        and signal.distinct_reporter_count == len(reporter_hashes)
    )
    if not (
        signal.threshold_met
        and signal.distinct_reporter_count >= settings.internship_risk_min_distinct_reporters
        and moderator_ok and safety_legal_ok and not vetoed and evidence_ok and live_sources_ok
    ):
        raise RiskLabelError(409, "risk_publication_prerequisites_missing", "Risk publication prerequisites are not met")
    if existing_label:
        raise RiskLabelError(409, "risk_label_already_published", "Risk label is already published")
    now = datetime.now(timezone.utc)
    row = PublishedRiskLabel(
        risk_signal_id=signal.id,
        organisation_id=public_organisation_id(organisation_name),
        neutral_label=_NEUTRAL_LABELS[cluster.category],
        category=cluster.category,
        public_count=(
            None
            if signal.report_count < settings.internship_risk_public_count_suppression
            else signal.report_count
        ),
        status="published",
        last_reviewed_at=now,
        published_at=now,
        version=1,
    )
    signal_id = signal.id
    try:
        # PostgreSQL can report the once-only label/idempotency violation at
        # flush, before commit. Keep the complete write set in this boundary.
        session.add(row)
        session.flush()
        decision = PublicationDecision(
            risk_signal_id=signal_id,
            published_label_id=row.id,
            actor_user_id=actor.user_id,
            decision="publish",
            reason_code=payload.reason_code,
            idempotency_key=key,
            expected_version=payload.expected_version,
            request_fingerprint=fingerprint,
        )
        session.add(decision)
        session.add(NotificationOutbox(
            aggregate_type="published_risk_label",
            aggregate_id=row.id,
            event_kind="risk_label_published",
            idempotency_key=f"notification:{key}",
            payload_json={"label_id": str(row.id), "organisation_id": str(row.organisation_id)},
            available_at=now,
        ))
        record_audit_event(
            session,
            action="risk_label_published",
            resource_type="published_risk_label",
            resource_id=row.id,
            actor_user_id=actor.user_id,
            actor_role=_audit_role(actor),
            after_state={
                "category": row.category,
                "small_count_suppressed": row.public_count is None,
                "version": row.version,
            },
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        prior = session.scalar(select(PublicationDecision).where(
            PublicationDecision.idempotency_key == key
        ))
        if prior is not None:
            if (
                prior.actor_user_id != actor.user_id
                or prior.risk_signal_id != signal_id
                or prior.request_fingerprint != fingerprint
                or prior.decision != "publish"
                or prior.published_label_id is None
            ):
                raise RiskLabelError(
                    409, "idempotency_conflict", "Idempotency key already used"
                )
            winner = session.get(PublishedRiskLabel, prior.published_label_id)
            if winner is not None:
                return _published_out(winner)
        raise RiskLabelError(409, "risk_publication_conflict", "Risk publication conflicted")
    return _published_out(row)


def create_response_request(
    session: Session,
    actor: ActorContext,
    payload: OrganisationResponseRequestIn,
    idempotency_key: str | None,
) -> OrganisationResponseRequestOut:
    require_publication_gate()
    _require_publication_actor(actor)
    key = safe_idempotency(idempotency_key)
    label = session.scalar(select(PublishedRiskLabel).where(
        PublishedRiskLabel.id == payload.published_label_id,
        PublishedRiskLabel.status.in_(("published", "corrected")),
        PublishedRiskLabel.deleted_at.is_(None),
    ).with_for_update())
    if label is None:
        raise RiskLabelError(404, "published_risk_label_not_found", "Published risk label not found")
    current_actor = _require_current_publication_actor(session, actor)
    representative_hash = _verified_representative_attestation(
        actor,
        label.organisation_id,
        payload.verification_method,
        payload.representative_verification_ref,
    )
    if (
        payload.verification_method == "manual_legal_review"
        and current_actor.role != "legal_reviewer"
    ):
        raise RiskLabelError(
            403,
            "representative_verification_authority_required",
            "Legal reviewer verification authority required",
        )
    fingerprint = _fingerprint({
        "label_id": payload.published_label_id,
        "representative_ref_hash": representative_hash,
        "method": payload.verification_method,
        "request_kind": payload.request_kind,
        "actor_id": actor.user_id,
    })
    prior = session.scalar(select(OrganisationResponseRequest).where(
        OrganisationResponseRequest.idempotency_key == key
    ))
    if prior:
        if (
            prior.request_fingerprint != fingerprint
            or prior.requested_by_user_id != actor.user_id
            or prior.published_label_id != payload.published_label_id
            or prior.request_kind != payload.request_kind
        ):
            raise RiskLabelError(409, "idempotency_conflict", "Idempotency key already used")
        return OrganisationResponseRequestOut(
            id=prior.id, published_label_id=prior.published_label_id,
            state=prior.state, expires_at=_as_utc(prior.expires_at), version=prior.version,
        )
    response_lifecycle = list(session.scalars(select(OrganisationResponse).where(
        OrganisationResponse.published_label_id == label.id,
        OrganisationResponse.state.in_(("moderation_pending", "approved")),
        OrganisationResponse.deleted_at.is_(None),
    ).order_by(OrganisationResponse.id).with_for_update()))
    current = [row for row in response_lifecycle if row.is_current and row.state == "approved"]
    target_response_id = None
    if payload.request_kind == "initial":
        now = datetime.now(timezone.utc)
        pending_initials = list(session.scalars(select(OrganisationResponseRequest).where(
            OrganisationResponseRequest.published_label_id == label.id,
            OrganisationResponseRequest.request_kind == "initial",
            OrganisationResponseRequest.state == "pending",
            OrganisationResponseRequest.deleted_at.is_(None),
        ).order_by(OrganisationResponseRequest.id).with_for_update()))
        active_pending = []
        expired_request_ids: list[uuid.UUID] = []
        for pending in pending_initials:
            if _as_utc(pending.expires_at) <= now:
                pending.state = "expired"
                pending.version += 1
                expired_request_ids.append(pending.id)
            else:
                active_pending.append(pending)
        _void_response_invitation_outboxes(
            session,
            expired_request_ids,
            reason_code="invitation_expired",
        )
        if active_pending:
            raise RiskLabelError(
                409,
                "initial_response_invitation_exists",
                "An active initial response invitation already exists",
            )
        if pending_initials:
            session.flush()
        if any(row.supersedes_response_id is None for row in response_lifecycle):
            raise RiskLabelError(
                409,
                "initial_response_already_exists",
                "An initial organisation response already exists",
            )
    else:
        if len(current) != 1:
            raise RiskLabelError(
                409,
                "response_correction_target_missing",
                "Correction or appeal requires exactly one approved current response",
            )
        target_response_id = current[0].id
    raw_token = secrets.token_urlsafe(32)
    token_hash = keyed_hash(raw_token)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=72)
    row = OrganisationResponseRequest(
        published_label_id=label.id,
        target_response_id=target_response_id,
        requested_by_user_id=actor.user_id,
        representative_ref_hash=representative_hash,
        representative_verification_method=payload.verification_method,
        representative_verified_at=now,
        representative_verified_by_user_id=actor.user_id,
        request_kind=payload.request_kind,
        token_hash=token_hash,
        state="pending",
        expires_at=expires,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        version=1,
    )
    try:
        session.add(row)
        session.flush()
        delivery_envelope = json.dumps(
            {
                "organisation_id": str(label.organisation_id),
                "delivery_ref": payload.representative_verification_ref,
                "invitation_token": raw_token,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        token_ciphertext = encrypt(delivery_envelope)
        session.add(NotificationOutbox(
            aggregate_type="organisation_response_request",
            aggregate_id=row.id,
            event_kind="organisation_response_requested",
            idempotency_key=f"notification:{key}",
            payload_json={
                "request_id": str(row.id),
                "label_id": str(label.id),
                "organisation_id": str(label.organisation_id),
            },
            secret_ciphertext=token_ciphertext,
            secret_key_version=key_version(token_ciphertext),
            available_at=now,
        ))
        record_audit_event(
            session,
            action="organisation_response_requested",
            resource_type="organisation_response_request",
            resource_id=row.id,
            actor_user_id=actor.user_id,
            actor_role=_audit_role(actor),
            after_state={"state": "pending", "expires_at": expires.isoformat()},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        winner = session.scalar(select(OrganisationResponseRequest).where(
            OrganisationResponseRequest.idempotency_key == key
        ))
        if winner is not None:
            if (
                winner.request_fingerprint != fingerprint
                or winner.requested_by_user_id != actor.user_id
                or winner.published_label_id != payload.published_label_id
                or winner.request_kind != payload.request_kind
            ):
                raise RiskLabelError(
                    409, "idempotency_conflict", "Idempotency key already used"
                )
            return OrganisationResponseRequestOut(
                id=winner.id, published_label_id=winner.published_label_id,
                state=winner.state, expires_at=_as_utc(winner.expires_at),
                version=winner.version,
            )
        code = (
            "initial_response_invitation_exists"
            if payload.request_kind == "initial"
            else "response_request_conflict"
        )
        message = (
            "An active initial response invitation already exists"
            if payload.request_kind == "initial"
            else "Organisation response request conflicted"
        )
        raise RiskLabelError(409, code, message)
    return OrganisationResponseRequestOut(
        id=row.id, published_label_id=row.published_label_id,
        state=row.state, expires_at=expires, version=row.version,
    )


def submit_response(
    session: Session,
    response_token: str | None,
    payload: OrganisationResponseIn,
    idempotency_key: str | None,
) -> OrganisationResponseOut:
    require_publication_gate()
    key = safe_idempotency(idempotency_key)
    token_hash = keyed_hash(response_token or "")
    text_digest = keyed_hash(payload.response_text)
    fingerprint = _fingerprint({"token_hash": token_hash, "response_digest": text_digest})
    prior = session.scalar(select(OrganisationResponse).where(
        OrganisationResponse.idempotency_key == key
    ))
    if prior:
        if prior.request_fingerprint != fingerprint:
            raise RiskLabelError(409, "idempotency_conflict", "Idempotency key already used")
        return OrganisationResponseOut(
            id=prior.id, published_label_id=prior.published_label_id,
            state=prior.state, version=prior.version, submitted_at=_as_utc(prior.submitted_at),
        )
    request_probe = session.scalar(select(OrganisationResponseRequest).where(
        OrganisationResponseRequest.token_hash == token_hash,
        OrganisationResponseRequest.deleted_at.is_(None),
    ))
    now = datetime.now(timezone.utc)
    if request_probe is None:
        raise RiskLabelError(404, "response_token_unavailable", "Response invitation is unavailable")
    label = session.scalar(select(PublishedRiskLabel).where(
        PublishedRiskLabel.id == request_probe.published_label_id,
        PublishedRiskLabel.deleted_at.is_(None),
    ).with_for_update())
    request = session.scalar(select(OrganisationResponseRequest).where(
        OrganisationResponseRequest.id == request_probe.id,
        OrganisationResponseRequest.deleted_at.is_(None),
    ).execution_options(populate_existing=True).with_for_update())
    if label is None or label.status not in {"published", "corrected"}:
        if label is not None:
            _revoke_label_response_work(
                session, label.id, now=now, reason_code="label_unavailable"
            )
            session.commit()
        raise RiskLabelError(404, "response_token_unavailable", "Response invitation is unavailable")
    # A same-key competitor may have committed while this transaction waited
    # on label/request locks. Refresh/re-read before classifying the token.
    prior = session.scalar(select(OrganisationResponse).where(
        OrganisationResponse.idempotency_key == key
    ))
    if prior is not None:
        if (
            request is None
            or prior.request_fingerprint != fingerprint
            or prior.request_id != request.id
            or prior.published_label_id != label.id
        ):
            raise RiskLabelError(409, "idempotency_conflict", "Idempotency key already used")
        return OrganisationResponseOut(
            id=prior.id, published_label_id=prior.published_label_id,
            state=prior.state, version=prior.version,
            submitted_at=_as_utc(prior.submitted_at),
        )
    if request is None or request.state != "pending":
        raise RiskLabelError(404, "response_token_unavailable", "Response invitation is unavailable")
    if _as_utc(request.expires_at) <= now:
        # Expiry is a terminal state, not only a read-time rejection. Erase
        # any delayed/claimed bearer envelope so a worker cannot deliver it
        # after this response attempt has established expiry.
        request.state = "expired"
        request.version += 1
        _void_response_invitation_outboxes(
            session, [request.id], reason_code="invitation_expired"
        )
        record_audit_event(
            session,
            action="organisation_response_invitation_expired",
            resource_type="organisation_response_request",
            resource_id=request.id,
            after_state={"state": "expired", "version": request.version},
        )
        session.commit()
        raise RiskLabelError(404, "response_token_unavailable", "Response invitation is unavailable")
    ciphertext = encrypt(payload.response_text)
    supersedes = None
    if request.request_kind != "initial":
        current = list(session.scalars(select(OrganisationResponse).where(
            OrganisationResponse.published_label_id == request.published_label_id,
            OrganisationResponse.state == "approved",
            OrganisationResponse.is_current.is_(True),
            OrganisationResponse.deleted_at.is_(None),
        ).order_by(OrganisationResponse.id).with_for_update()))
        if (
            len(current) != 1
            or request.target_response_id is None
            or current[0].id != request.target_response_id
        ):
            raise RiskLabelError(
                409,
                "response_correction_target_changed",
                "Correction or appeal target changed",
            )
        supersedes = current[0]
    row = OrganisationResponse(
        request_id=request.id,
        published_label_id=request.published_label_id,
        supersedes_response_id=supersedes.id if supersedes else None,
        response_ciphertext=ciphertext,
        response_key_version=key_version(ciphertext),
        response_digest=text_digest,
        state="moderation_pending",
        is_current=False,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        version=1,
        submitted_at=now,
    )
    request_id = request.id
    label_id = label.id
    try:
        session.add(row)
        request.state = "responded"
        request.used_at = now
        request.version += 1
        _void_response_invitation_outboxes(
            session, [request.id], reason_code="invitation_consumed"
        )
        session.flush()
        session.add(NotificationOutbox(
            aggregate_type="organisation_response",
            aggregate_id=row.id,
            event_kind="organisation_response_submitted",
            idempotency_key=f"notification:{key}",
            payload_json={"response_id": str(row.id), "label_id": str(row.published_label_id)},
            available_at=now,
        ))
        record_audit_event(
            session,
            action="organisation_response_submitted",
            resource_type="organisation_response",
            resource_id=row.id,
            after_state={"state": row.state, "version": row.version},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        winner = session.scalar(select(OrganisationResponse).where(
            OrganisationResponse.idempotency_key == key
        ))
        if winner is not None:
            if (
                winner.request_fingerprint != fingerprint
                or winner.request_id != request_id
                or winner.published_label_id != label_id
            ):
                raise RiskLabelError(
                    409, "idempotency_conflict", "Idempotency key already used"
                )
            return OrganisationResponseOut(
                id=winner.id, published_label_id=winner.published_label_id,
                state=winner.state, version=winner.version,
                submitted_at=_as_utc(winner.submitted_at),
            )
        raise RiskLabelError(404, "response_token_unavailable", "Response invitation is unavailable")
    return OrganisationResponseOut(
        id=row.id, published_label_id=row.published_label_id,
        state=row.state, version=row.version, submitted_at=now,
    )


def decide_response(
    session: Session,
    actor: ActorContext,
    response_id: uuid.UUID,
    payload: OrganisationResponseDecisionIn,
    idempotency_key: str | None,
) -> OrganisationResponseOut:
    require_publication_gate()
    _require_moderator(actor)
    key = safe_idempotency(idempotency_key)
    fingerprint = _fingerprint({
        "response_id": response_id, "actor_id": actor.user_id, **payload.model_dump()
    })
    prior = session.scalar(select(ResponseModeration).where(
        ResponseModeration.idempotency_key == key
    ))
    if prior:
        if prior.request_fingerprint != fingerprint:
            raise RiskLabelError(409, "idempotency_conflict", "Idempotency key already used")
        row = session.get(OrganisationResponse, prior.response_id)
        return OrganisationResponseOut(
            id=row.id, published_label_id=row.published_label_id,
            state=row.state, version=row.version, submitted_at=_as_utc(row.submitted_at),
        )
    response_probe = session.scalar(select(OrganisationResponse).where(
        OrganisationResponse.id == response_id,
        OrganisationResponse.deleted_at.is_(None),
    ))
    if response_probe is None:
        raise RiskLabelError(404, "organisation_response_not_found", "Organisation response not found")
    label = session.scalar(select(PublishedRiskLabel).where(
        PublishedRiskLabel.id == response_probe.published_label_id,
        PublishedRiskLabel.deleted_at.is_(None),
    ).with_for_update())
    row = session.scalar(select(OrganisationResponse).where(
        OrganisationResponse.id == response_id,
        OrganisationResponse.deleted_at.is_(None),
    ).execution_options(populate_existing=True).with_for_update())
    if label is None or label.status not in {"published", "corrected"}:
        raise RiskLabelError(
            409,
            "published_risk_label_withdrawn",
            "Published risk label is withdrawn",
        )
    _require_current_moderator(session, actor)
    prior = session.scalar(select(ResponseModeration).where(
        ResponseModeration.idempotency_key == key
    ))
    if prior is not None:
        if (
            prior.response_id != response_id
            or prior.actor_user_id != actor.user_id
            or prior.request_fingerprint != fingerprint
            or prior.decision != payload.decision
        ):
            raise RiskLabelError(409, "idempotency_conflict", "Idempotency key already used")
        winner = session.get(OrganisationResponse, prior.response_id)
        return OrganisationResponseOut(
            id=winner.id, published_label_id=winner.published_label_id,
            state=winner.state, version=winner.version,
            submitted_at=_as_utc(winner.submitted_at),
        )
    if row.version != payload.expected_version:
        raise RiskLabelError(409, "stale_organisation_response", "Organisation response changed", current_version=row.version)
    if row.state != "moderation_pending":
        raise RiskLabelError(409, "response_already_decided", "Organisation response is already decided")
    current = list(session.scalars(select(OrganisationResponse).where(
        OrganisationResponse.published_label_id == row.published_label_id,
        OrganisationResponse.is_current.is_(True),
        OrganisationResponse.deleted_at.is_(None),
    ).order_by(OrganisationResponse.id).with_for_update()))
    now = datetime.now(timezone.utc)
    previous = None
    if payload.decision == "approve":
        if row.supersedes_response_id:
            if len(current) != 1 or current[0].id != row.supersedes_response_id:
                raise RiskLabelError(409, "response_chain_conflict", "Response chain changed")
        elif current:
            raise RiskLabelError(
                409,
                "response_chain_conflict",
                "A current organisation response already exists",
            )
        if row.supersedes_response_id:
            # The current-response partial UNIQUE is immediate/non-deferrable.
            # Demote and flush the predecessor under the label lock before the
            # replacement becomes current, while retaining one transaction.
            previous = current[0]
            previous.state = "superseded"
            previous.is_current = False
            previous.version += 1
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                raise RiskLabelError(409, "response_chain_conflict", "Response chain changed")
        row.state = "approved"
        row.is_current = True
    else:
        row.state = "rejected"
        row.is_current = False
    row.moderated_at = now
    row.version += 1
    if payload.decision == "approve" and row.supersedes_response_id:
        label.status = "corrected"
        label.last_reviewed_at = now
        label.version += 1
    session.add(ResponseModeration(
        response_id=row.id,
        actor_user_id=actor.user_id,
        decision=payload.decision,
        reason_code=payload.reason_code,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        response_version=row.version,
    ))
    session.add(NotificationOutbox(
        aggregate_type="organisation_response",
        aggregate_id=row.id,
        event_kind="organisation_response_decided",
        idempotency_key=f"notification:{key}",
        payload_json={"response_id": str(row.id), "state": row.state},
        available_at=now,
    ))
    record_audit_event(
        session,
        action="organisation_response_decided",
        resource_type="organisation_response",
        resource_id=row.id,
        actor_user_id=actor.user_id,
        actor_role=_audit_role(actor),
        after_state={"state": row.state, "version": row.version, "reason_code": payload.reason_code},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        winner_decision = session.scalar(select(ResponseModeration).where(
            ResponseModeration.idempotency_key == key
        ))
        if winner_decision is not None:
            if (
                winner_decision.response_id != response_id
                or winner_decision.actor_user_id != actor.user_id
                or winner_decision.request_fingerprint != fingerprint
                or winner_decision.decision != payload.decision
            ):
                raise RiskLabelError(
                    409, "idempotency_conflict", "Idempotency key already used"
                )
            winner = session.get(OrganisationResponse, winner_decision.response_id)
            if winner is not None:
                return OrganisationResponseOut(
                    id=winner.id, published_label_id=winner.published_label_id,
                    state=winner.state, version=winner.version,
                    submitted_at=_as_utc(winner.submitted_at),
                )
        raise RiskLabelError(409, "response_chain_conflict", "Response chain changed")
    return OrganisationResponseOut(
        id=row.id, published_label_id=row.published_label_id,
        state=row.state, version=row.version, submitted_at=_as_utc(row.submitted_at),
    )


def public_labels(session: Session, organisation_id: uuid.UUID) -> PublicRiskLabelsOut:
    require_publication_gate()
    labels = list(session.scalars(select(PublishedRiskLabel).where(
        PublishedRiskLabel.organisation_id == organisation_id,
        PublishedRiskLabel.status.in_(("published", "corrected")),
        PublishedRiskLabel.deleted_at.is_(None),
    ).order_by(PublishedRiskLabel.category, PublishedRiskLabel.id)))
    labels = [label for label in labels if _public_label_sources_live(session, label)]
    items: list[PublicRiskLabelOut] = []
    for label in labels:
        response = session.scalar(select(OrganisationResponse).where(
            OrganisationResponse.published_label_id == label.id,
            OrganisationResponse.state == "approved",
            OrganisationResponse.is_current.is_(True),
            OrganisationResponse.deleted_at.is_(None),
        ).order_by(OrganisationResponse.moderated_at.desc()))
        response_out = None
        if response is not None:
            request = session.get(OrganisationResponseRequest, response.request_id)
            moderation = session.scalar(select(ResponseModeration).where(
                ResponseModeration.response_id == response.id,
                ResponseModeration.decision == "approve",
                ResponseModeration.response_version == response.version,
                ResponseModeration.deleted_at.is_(None),
            ))
            request_chain_valid = bool(
                request is not None
                and moderation is not None
                and request.deleted_at is None
                and request.published_label_id == label.id
                and request.state == "responded"
                and request.used_at is not None
                and (
                    (
                        request.request_kind == "initial"
                        and request.target_response_id is None
                        and response.supersedes_response_id is None
                    )
                    or (
                        request.request_kind in {"correction", "appeal"}
                        and request.target_response_id is not None
                        and request.target_response_id
                        == response.supersedes_response_id
                    )
                )
            )
            if request_chain_valid:
                try:
                    response_text = decrypt(response.response_ciphertext)
                except Exception:
                    response_text = None
                # Ciphertext is encrypted storage, not an integrity oracle.
                # Bind the decrypted value back to the immutable submission
                # digest before allowing it into the public projection.
                if (
                    response_text is not None
                    and keyed_hash(response_text) == response.response_digest
                ):
                    response_out = PublicOrganisationResponseOut(
                        text=response_text,
                        last_reviewed_at=_as_utc(response.moderated_at),
                        kind=request.request_kind,
                    )
        items.append(PublicRiskLabelOut(
            id=label.id,
            category=label.category,
            neutral_label=_NEUTRAL_LABELS[label.category],
            public_count=label.public_count,
            last_reviewed_at=_as_utc(label.last_reviewed_at),
            source_type=label.source_type,
            status="corrected" if label.status == "corrected" else "approved",
            organisation_response=response_out,
        ))
    return PublicRiskLabelsOut(
        organisation_id=organisation_id, labels=items, available=True
    )


def _public_label_sources_live(
    session: Session, label: PublishedRiskLabel
) -> bool:
    """Revalidate every governed source before exposing a stored label.

    A prior publication decision is not perpetual authority. Time-window
    expiry, source/case/evidence/vault/category invalidation, organisation
    identity drift, count drift, an approval veto, or inactive/role-changed
    approvers all suppress the public projection immediately.
    """
    signal = session.get(RiskSignal, label.risk_signal_id)
    cluster = session.get(DuplicateCluster, signal.cluster_id) if signal else None
    if (
        signal is None or signal.deleted_at is not None
        or cluster is None or cluster.deleted_at is not None
        or signal.approval_vetoed or not signal.threshold_met
        or cluster.category != label.category
        or _NEUTRAL_LABELS.get(label.category) != label.neutral_label
        or _NEUTRAL_LABELS.get(cluster.category) != signal.neutral_label
    ):
        return False
    members = list(session.scalars(select(DuplicateClusterMember).where(
        DuplicateClusterMember.cluster_id == cluster.id,
        DuplicateClusterMember.deleted_at.is_(None),
    ).order_by(DuplicateClusterMember.id)))
    member_ids = [row.report_id for row in members]
    if not member_ids:
        return False
    reports = list(session.scalars(select(InternshipReport).where(
        InternshipReport.id.in_(member_ids),
        InternshipReport.deleted_at.is_(None),
    ).order_by(InternshipReport.id)))
    cases = list(session.scalars(select(ModerationCase).where(
        ModerationCase.report_id.in_(member_ids),
        ModerationCase.deleted_at.is_(None),
    ).order_by(ModerationCase.report_id, ModerationCase.id)))
    evidence = list(session.scalars(select(InternshipReportEvidence).where(
        InternshipReportEvidence.report_id.in_(member_ids),
        InternshipReportEvidence.deleted_at.is_(None),
    ).order_by(InternshipReportEvidence.report_id, InternshipReportEvidence.id)))
    vaults = list(session.scalars(select(ReporterIdentityVault).where(
        ReporterIdentityVault.report_id.in_(member_ids),
        ReporterIdentityVault.deleted_at.is_(None),
    ).order_by(ReporterIdentityVault.report_id, ReporterIdentityVault.id)))
    categories = list(session.scalars(select(InternshipReportCategory).where(
        InternshipReportCategory.report_id.in_(member_ids),
        InternshipReportCategory.category == cluster.category,
        InternshipReportCategory.deleted_at.is_(None),
    ).order_by(InternshipReportCategory.report_id, InternshipReportCategory.id)))
    evidence_by_report = {report_id: [] for report_id in member_ids}
    for row in evidence:
        evidence_by_report[row.report_id].append(row.scan_state)
    reporter_hashes = {row.reporter_lookup_hash for row in vaults}
    category_report_ids = {row.report_id for row in categories}
    dates = [row.experience_end_date or row.experience_start_date for row in reports]
    cutoff = _months_ago(
        datetime.now(timezone.utc).date(), settings.internship_risk_window_months
    )
    try:
        organisation_name = decrypt(cluster.organisation_ciphertext)
    except Exception:
        return False
    organisation_hash = keyed_hash(
        normalise_organisation(organisation_name), lower=True
    )
    report_organisation_hashes = {
        keyed_hash(normalise_organisation(row.organisation_name), lower=True)
        for row in reports
    }
    decisions = list(session.scalars(select(RiskSignalApproval).where(
        RiskSignalApproval.risk_signal_id == signal.id,
        RiskSignalApproval.deleted_at.is_(None),
    ).order_by(RiskSignalApproval.id)))
    publication_decisions = list(session.scalars(select(PublicationDecision).where(
        PublicationDecision.published_label_id == label.id,
        PublicationDecision.deleted_at.is_(None),
    ).order_by(PublicationDecision.id)))
    matching_publications = [
        row for row in publication_decisions
        if row.decision == "publish" and row.risk_signal_id == signal.id
    ]
    users = {
        row.id: row for row in session.scalars(select(User).where(
            User.id.in_({decision.actor_user_id for decision in decisions})
        ).order_by(User.id))
    }
    valid_decisions = [
        decision for decision in decisions
        if (user := users.get(decision.actor_user_id)) is not None
        and user.status == "active" and user.role == decision.actor_role
    ]
    moderator_ok = any(
        row.actor_role == "moderator" and row.decision == "approve"
        for row in valid_decisions
    )
    safety_legal_ok = any(
        row.actor_role in {"safety_officer", "legal_reviewer"}
        and row.decision == "approve" for row in valid_decisions
    )
    return bool(
        len(reports) == len(member_ids)
        and len(cases) == len(member_ids)
        and len(vaults) == len(member_ids)
        and all(row.status == "approved" for row in reports)
        and all(row.state == "approved_aggregate_only" for row in cases)
        and all(row.category == cluster.category for row in members)
        and category_report_ids == set(member_ids)
        and all(
            states and all(state == "clean" for state in states)
            for states in evidence_by_report.values()
        )
        and len(reporter_hashes) >= settings.internship_risk_min_distinct_reporters
        and all(value is not None and value >= cutoff for value in dates)
        and min(dates) == cluster.window_start
        and max(dates) == cluster.window_end
        and organisation_hash == cluster.organisation_hash
        and report_organisation_hashes == {cluster.organisation_hash}
        and public_organisation_id(organisation_name) == label.organisation_id
        and signal.report_count == len(member_ids)
        and signal.distinct_reporter_count == len(reporter_hashes)
        and label.public_count == (
            None
            if signal.report_count
            < settings.internship_risk_public_count_suppression
            else signal.report_count
        )
        and len(matching_publications) == 1
        and all(row.risk_signal_id == signal.id for row in publication_decisions)
        and not any(row.decision == "withdraw" for row in publication_decisions)
        and moderator_ok and safety_legal_ok
        and not any(row.decision == "reject" for row in decisions)
    )
