"""Isolated SAATHI-279 browser fixture with no secret-bearing output.

Raw session and response invitation tokens are supplied by environment, stored
only as keyed hashes/encrypted outbox material, and never printed.  The browser
driver receives the same values through its protected process environment.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

# Direct execution sets sys.path[0] to ``backend/scripts`` rather than the
# backend project root.  Establish the same import contract as ``python -m``
# before importing the sibling fixture module.
BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from scripts.seed_wave4_moderation_e2e import (
    MODERATOR_ID,
    assert_isolated_target,
    provision as provision_moderation,
)

SAFETY_ID = uuid.UUID("00000000-0000-4000-8000-0000000000c5")
LEGAL_ID = uuid.UUID("00000000-0000-4000-8000-0000000000c6")
CANDIDATE_CLUSTER_ID = uuid.UUID("00000000-0000-4000-8000-000000002791")
CANDIDATE_SIGNAL_ID = uuid.UUID("00000000-0000-4000-8000-000000002792")
PUBLISHED_CLUSTER_ID = uuid.UUID("00000000-0000-4000-8000-000000002793")
PUBLISHED_SIGNAL_ID = uuid.UUID("00000000-0000-4000-8000-000000002794")
PUBLISHED_LABEL_ID = uuid.UUID("00000000-0000-4000-8000-000000002795")
RESPONSE_REQUEST_ID = uuid.UUID("00000000-0000-4000-8000-000000002796")
EXPIRED_REQUEST_ID = uuid.UUID("00000000-0000-4000-8000-000000002800")
BOUNDARY_REQUEST_ID = uuid.UUID("00000000-0000-4000-8000-000000002801")
BOUNDARY_CLUSTER_ID = uuid.UUID("00000000-0000-4000-8000-000000002807")
BOUNDARY_SIGNAL_ID = uuid.UUID("00000000-0000-4000-8000-000000002808")
BOUNDARY_LABEL_ID = uuid.UUID("00000000-0000-4000-8000-000000002809")
RISK_REPORT_IDS = tuple(
    uuid.UUID(value)
    for value in (
        "00000000-0000-4000-8000-0000000027a1",
        "00000000-0000-4000-8000-0000000027a2",
        "00000000-0000-4000-8000-0000000027a3",
    )
)
RISK_REPORTER_IDS = tuple(
    uuid.UUID(value)
    for value in (
        "00000000-0000-4000-8000-0000000027b1",
        "00000000-0000-4000-8000-0000000027b2",
        "00000000-0000-4000-8000-0000000027b3",
    )
)


def _auth_session(session: Session, user_id: uuid.UUID, token: str, now: datetime) -> None:
    from app.core.crypto import keyed_hash
    from app.models.registration import AuthSession

    token_hash = keyed_hash(token)
    row = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if row is None:
        session.add(AuthSession(
            user_id=user_id,
            token_hash=token_hash,
            status="active",
            expires_at=now + timedelta(hours=4),
            last_seen_at=now,
        ))
    else:
        row.status = "active"
        row.expires_at = now + timedelta(hours=4)
        row.revoked_at = None


def provision(
    session: Session,
    *,
    moderator_token: str,
    safety_token: str,
    legal_token: str,
    response_token: str,
    expired_response_token: str,
    boundary_response_token: str,
) -> dict[str, str]:
    for name, value in {
        "moderator_token": moderator_token,
        "safety_token": safety_token,
        "legal_token": legal_token,
        "response_token": response_token,
        "expired_response_token": expired_response_token,
        "boundary_response_token": boundary_response_token,
    }.items():
        if len(value) < 32:
            raise RuntimeError(f"{name} must contain at least 32 characters")

    from app.core.crypto import encrypt, key_version, keyed_hash
    from app.models.registration import User
    from app.models.wave4 import (
        DuplicateCluster,
        DuplicateClusterMember,
        InternshipReport,
        InternshipReportCategory,
        InternshipReportEvidence,
        ModerationCase,
        ModerationHandoff,
        NotificationOutbox,
        OrganisationResponseRequest,
        PublicationDecision,
        PublishedRiskLabel,
        ReporterIdentityVault,
        RiskSignal,
        RiskSignalApproval,
    )
    from app.services.organisation_identity import (
        public_organisation_id,
        representative_verification_hash,
    )

    provision_moderation(session, moderator_token)
    now = datetime.now(timezone.utc)
    for user_id, role, token in (
        (SAFETY_ID, "safety_officer", safety_token),
        (LEGAL_ID, "legal_reviewer", legal_token),
    ):
        user = session.get(User, user_id)
        if user is None:
            user = User(id=user_id, role=role, status="active")
            session.add(user)
        else:
            user.role = role
            user.status = "active"
        session.flush()
        _auth_session(session, user_id, token, now)

    # SAATHI-279 owns a distinct deterministic source set.  Reusing the
    # SAATHI-274 moderation reports made the two browser suites mutually
    # exclusive because the active report/category membership invariant
    # correctly forbids one report from joining overlapping clusters.
    for index, (report_id, reporter_id) in enumerate(
        zip(RISK_REPORT_IDS, RISK_REPORTER_IDS, strict=True)
    ):
        report = session.get(InternshipReport, report_id)
        if report is None:
            report = InternshipReport(
                id=report_id,
                organisation_name="Nyaya Legal Foundation",
                listing_application_ref=f"W4-RISK-{index + 1:02d}",
                experience_start_date=date.today() - timedelta(days=120 + index),
                experience_end_date=date.today() - timedelta(days=90 + index),
                narrative=(
                    "Independent approved evidence for the governed public-risk "
                    f"projection fixture {index + 1}."
                ),
                privacy_mode="anonymous",
                status="approved",
                idempotency_key=f"wave4-risk-e2e-report-{index + 1}",
                version=2,
                support_guidance_required=True,
                submitted_at=now,
            )
            session.add(report)
            session.flush()
        if session.scalar(select(InternshipReportEvidence).where(
            InternshipReportEvidence.report_id == report_id,
            InternshipReportEvidence.scan_state == "clean",
        )) is None:
            session.add(InternshipReportEvidence(
                report_id=report_id,
                object_ref=f"wave4-risk-e2e/{report_id}",
                mime_type="application/pdf",
                size_bytes=2048,
                checksum_sha256=f"{index + 41:064x}",
                scan_state="clean",
                scanner_result_code="fixture_clean",
                retention_policy="configured",
            ))
        if session.scalar(select(ReporterIdentityVault).where(
            ReporterIdentityVault.report_id == report_id
        )) is None:
            reporter_ct = encrypt(str(reporter_id))
            session.add(ReporterIdentityVault(
                report_id=report_id,
                reporter_lookup_hash=keyed_hash(str(reporter_id), lower=True),
                reporter_ciphertext=reporter_ct,
                key_version=key_version(reporter_ct),
            ))
        if session.scalar(select(ModerationHandoff).where(
            ModerationHandoff.report_id == report_id
        )) is None:
            session.add(ModerationHandoff(
                report_id=report_id,
                state="approved",
                assigned_moderator_user_id=MODERATOR_ID,
                version=1,
            ))
        if session.scalar(select(ModerationCase).where(
            ModerationCase.report_id == report_id
        )) is None:
            session.add(ModerationCase(
                report_id=report_id,
                state="approved_aggregate_only",
                assigned_moderator_user_id=MODERATOR_ID,
                claimed_at=now,
                version=1,
            ))
    session.flush()

    # Every source report must carry the exact category of every deterministic
    # cluster used by the browser gate.  Publication revalidates this live; it
    # must never succeed merely because a fixture pre-filled a RiskSignal.
    for report_id in RISK_REPORT_IDS:
        for category in ("unsafe_environment", "excessive_hours", "non_response"):
            if session.scalar(select(InternshipReportCategory).where(
                InternshipReportCategory.report_id == report_id,
                InternshipReportCategory.category == category,
            )) is None:
                session.add(InternshipReportCategory(
                    report_id=report_id, category=category
                ))
    session.flush()

    source_reports = [session.get(InternshipReport, report_id) for report_id in RISK_REPORT_IDS]
    source_dates = [
        report.experience_end_date or report.experience_start_date
        for report in source_reports
        if report is not None
    ]
    if len(source_dates) != 3 or any(value is None for value in source_dates):
        raise RuntimeError("Wave 4 risk-label source reports are incomplete")
    source_window_start = min(source_dates)
    source_window_end = max(source_dates)

    organisation = "Nyaya Legal Foundation"
    organisation_ct = encrypt(organisation)
    cluster_specs = (
        (CANDIDATE_CLUSTER_ID, CANDIDATE_SIGNAL_ID, "unsafe_environment", "wave4-e2e-candidate"),
        (PUBLISHED_CLUSTER_ID, PUBLISHED_SIGNAL_ID, "excessive_hours", "wave4-e2e-published"),
        (BOUNDARY_CLUSTER_ID, BOUNDARY_SIGNAL_ID, "non_response", "wave4-e2e-boundary"),
    )
    for cluster_id, signal_id, category, idem in cluster_specs:
        cluster = session.get(DuplicateCluster, cluster_id)
        if cluster is None:
            cluster = DuplicateCluster(
                id=cluster_id,
                organisation_hash=keyed_hash(organisation, lower=True),
                organisation_ciphertext=organisation_ct,
                key_version=key_version(organisation_ct),
                category=category,
                window_start=source_window_start,
                window_end=source_window_end,
                explanation_code="organisation_category_time_window_clean_evidence",
                state="eligible",
                idempotency_key=idem,
                actor_user_id=MODERATOR_ID,
                request_fingerprint=keyed_hash(idem),
                version=1,
            )
            session.add(cluster)
            session.flush()
        else:
            cluster.window_start = source_window_start
            cluster.window_end = source_window_end
        for report_id in RISK_REPORT_IDS:
            if session.scalar(select(DuplicateClusterMember).where(
                DuplicateClusterMember.cluster_id == cluster_id,
                DuplicateClusterMember.report_id == report_id,
            )) is None:
                session.add(DuplicateClusterMember(
                    cluster_id=cluster_id, report_id=report_id, category=category
                ))
        signal = session.get(RiskSignal, signal_id)
        if signal is None:
            signal = RiskSignal(
                id=signal_id,
                cluster_id=cluster_id,
                neutral_label=(
                    "Moderated workplace-safety pattern"
                    if category == "unsafe_environment"
                    else (
                        "Moderated excessive-hours pattern"
                        if category == "excessive_hours"
                        else "Moderated organisation non-response pattern"
                    )
                ),
                report_count=3,
                distinct_reporter_count=3,
                threshold_met=True,
                small_count_suppressed=True,
                moderator_approved=True,
                safety_legal_approved=True,
                approval_vetoed=False,
                publication_ready=False,
                version=1,
            )
            session.add(signal)
            session.flush()
        for actor_id, role in (
            (MODERATOR_ID, "moderator"),
            (SAFETY_ID, "safety_officer"),
        ):
            if session.scalar(select(RiskSignalApproval).where(
                RiskSignalApproval.risk_signal_id == signal_id,
                RiskSignalApproval.actor_user_id == actor_id,
            )) is None:
                session.add(RiskSignalApproval(
                    risk_signal_id=signal_id,
                    actor_user_id=actor_id,
                    actor_role=role,
                    decision="approve",
                    reason_code="qa_target_gate_approval",
                ))
    session.flush()

    label = session.get(PublishedRiskLabel, PUBLISHED_LABEL_ID)
    if label is None:
        label = PublishedRiskLabel(
            id=PUBLISHED_LABEL_ID,
            risk_signal_id=PUBLISHED_SIGNAL_ID,
            organisation_id=public_organisation_id(organisation),
            neutral_label="Moderated excessive-hours pattern",
            category="excessive_hours",
            public_count=None,
            status="published",
            last_reviewed_at=now,
            published_at=now,
            version=1,
        )
        session.add(label)
        session.flush()

    boundary_label = session.get(PublishedRiskLabel, BOUNDARY_LABEL_ID)
    if boundary_label is None:
        boundary_label = PublishedRiskLabel(
            id=BOUNDARY_LABEL_ID,
            risk_signal_id=BOUNDARY_SIGNAL_ID,
            organisation_id=public_organisation_id(organisation),
            neutral_label="Moderated organisation non-response pattern",
            category="non_response",
            public_count=None,
            status="published",
            last_reviewed_at=now,
            published_at=now,
            version=1,
        )
        session.add(boundary_label)
        session.flush()

    for seeded_label, seeded_signal, suffix in (
        (label, PUBLISHED_SIGNAL_ID, "published"),
        (boundary_label, BOUNDARY_SIGNAL_ID, "boundary"),
    ):
        decision_key = f"wave4-e2e-{suffix}-publication"
        if session.scalar(select(PublicationDecision).where(
            PublicationDecision.idempotency_key == decision_key
        )) is None:
            session.add(PublicationDecision(
                risk_signal_id=seeded_signal,
                published_label_id=seeded_label.id,
                actor_user_id=SAFETY_ID,
                decision="publish",
                reason_code="qa_governed_publication",
                idempotency_key=decision_key,
                expected_version=1,
                request_fingerprint=keyed_hash(decision_key),
            ))
    session.flush()

    request = session.get(OrganisationResponseRequest, RESPONSE_REQUEST_ID)
    if request is None:
        request = OrganisationResponseRequest(
            id=RESPONSE_REQUEST_ID,
            published_label_id=label.id,
            requested_by_user_id=SAFETY_ID,
            representative_ref_hash=representative_verification_hash(
                label.organisation_id,
                "qa_fixture",
                "qa-verified-representative",
            ),
            representative_verification_method="qa_fixture",
            representative_verified_at=now,
            representative_verified_by_user_id=SAFETY_ID,
            request_kind="initial",
            token_hash=keyed_hash(response_token),
            state="pending",
            expires_at=now + timedelta(hours=72),
            idempotency_key="wave4-e2e-response-request",
            request_fingerprint=keyed_hash("wave4-e2e-response-request"),
            version=1,
        )
        session.add(request)
        session.flush()
        token_ct = encrypt(json.dumps({
            "organisation_id": str(label.organisation_id),
            "delivery_ref": "qa-verified-representative",
            "invitation_token": response_token,
        }, sort_keys=True, separators=(",", ":")))
        session.add(NotificationOutbox(
            aggregate_type="organisation_response_request",
            aggregate_id=request.id,
            event_kind="organisation_response_requested",
            idempotency_key="notification:wave4-e2e-response-request",
            payload_json={
                "request_id": str(request.id),
                "label_id": str(label.id),
                "organisation_id": str(label.organisation_id),
            },
            secret_ciphertext=token_ct,
            secret_key_version=key_version(token_ct),
            available_at=now,
        ))

    invitation_specs = (
        (
            EXPIRED_REQUEST_ID,
            expired_response_token,
            "initial",
            "expired",
            now - timedelta(seconds=1),
            "wave4-e2e-expired-request",
            label,
            None,
        ),
        (
            BOUNDARY_REQUEST_ID,
            boundary_response_token,
            "initial",
            "pending",
            now + timedelta(hours=72),
            "wave4-e2e-boundary-request",
            boundary_label,
            None,
        ),
    )
    for request_id, raw_token, kind, state, expiry, idem, invitation_label, target_id in invitation_specs:
        invitation = session.get(OrganisationResponseRequest, request_id)
        if invitation is None:
            invitation = OrganisationResponseRequest(
                id=request_id,
                published_label_id=invitation_label.id,
                target_response_id=target_id,
                requested_by_user_id=SAFETY_ID,
                representative_ref_hash=representative_verification_hash(
                    invitation_label.organisation_id,
                    "qa_fixture",
                    f"qa-representative:{idem}",
                ),
                representative_verification_method="qa_fixture",
                representative_verified_at=now,
                representative_verified_by_user_id=SAFETY_ID,
                request_kind=kind,
                token_hash=keyed_hash(raw_token),
                state=state,
                expires_at=expiry,
                idempotency_key=idem,
                request_fingerprint=keyed_hash(idem),
                version=1,
            )
            session.add(invitation)
            session.flush()
            if state == "pending":
                token_ct = encrypt(json.dumps({
                    "organisation_id": str(invitation_label.organisation_id),
                    "delivery_ref": f"qa-representative:{idem}",
                    "invitation_token": raw_token,
                }, sort_keys=True, separators=(",", ":")))
                session.add(NotificationOutbox(
                    aggregate_type="organisation_response_request",
                    aggregate_id=invitation.id,
                    event_kind="organisation_response_requested",
                    idempotency_key=f"notification:{idem}",
                    payload_json={
                        "request_id": str(invitation.id),
                        "label_id": str(invitation_label.id),
                        "organisation_id": str(invitation_label.organisation_id),
                    },
                    secret_ciphertext=token_ct,
                    secret_key_version=key_version(token_ct),
                    available_at=now,
                ))
    session.flush()
    return {
        "moderator_user_id": str(MODERATOR_ID),
        "safety_user_id": str(SAFETY_ID),
        "legal_user_id": str(LEGAL_ID),
        "candidate_cluster_id": str(CANDIDATE_CLUSTER_ID),
        "candidate_signal_id": str(CANDIDATE_SIGNAL_ID),
        "candidate_version": "1",
        "prepublished_label_id": str(PUBLISHED_LABEL_ID),
        "valid_request_id": str(RESPONSE_REQUEST_ID),
        "expired_request_id": str(EXPIRED_REQUEST_ID),
        "boundary_request_id": str(BOUNDARY_REQUEST_ID),
        "organisation_id": str(public_organisation_id(organisation)),
    }


def _write_fixture_output(
    path_value: str,
    result: dict[str, str],
    *,
    database_url: str,
) -> None:
    """Atomically write only nonsecret fixture identifiers with mode 0600."""
    if not path_value:
        return
    target = Path(path_value).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    payload = {
        key: result[key]
        for key in (
            "organisation_id",
            "candidate_cluster_id",
            "candidate_version",
            "prepublished_label_id",
            "valid_request_id",
            "expired_request_id",
            "boundary_request_id",
        )
    }
    payload["database_dialect"] = make_url(database_url).get_backend_name()
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, target)
    os.chmod(target, 0o600)


def main() -> int:
    database_url = os.getenv("DATABASE_URL", "")
    values = {
        "moderator_token": os.getenv("WAVE4_E2E_SESSION_TOKEN", ""),
        "safety_token": os.getenv("WAVE4_E2E_SAFETY_SESSION_TOKEN", ""),
        "legal_token": os.getenv("WAVE4_E2E_LEGAL_SESSION_TOKEN", ""),
        "response_token": os.getenv("WAVE4_E2E_RESPONSE_TOKEN", ""),
        "expired_response_token": os.getenv("WAVE4_E2E_EXPIRED_RESPONSE_TOKEN", ""),
        "boundary_response_token": os.getenv("WAVE4_E2E_BOUNDARY_RESPONSE_TOKEN", ""),
    }
    try:
        assert_isolated_target(database_url)
        if any(not value for value in values.values()):
            raise RuntimeError("all Wave 4 E2E token environment variables are required")
    except RuntimeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    from app.db.session import get_sessionmaker

    with get_sessionmaker()() as session:
        result = provision(session, **values)
        session.commit()
    _write_fixture_output(
        os.getenv("WAVE4_E2E_FIXTURE_OUTPUT", ""),
        result,
        database_url=database_url,
    )
    print(json.dumps({"seed_wave4_risk_labels_e2e": result, "raw_tokens": "NOT_LOGGED"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
