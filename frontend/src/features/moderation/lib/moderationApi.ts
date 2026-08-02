import { apiFetch } from '../../../lib/apiClient';

export interface ModerationQueueItem {
  caseId: string;
  reportId: string;
  organisationName: string;
  categories: string[];
  experienceStartDate: string | null;
  experienceEndDate: string | null;
  evidenceClean: number;
  evidenceTotal: number;
  state: string;
  assignedToMe: boolean;
  version: number;
  submittedAt: string | null;
}

export interface ModerationCase extends ModerationQueueItem {
  listingApplicationRef: string;
  narrative: string;
  privacyMode: string;
  supportGuidanceRequired: boolean;
  scanStates: string[];
}

export interface RiskCluster {
  id: string;
  organisationName: string;
  category: string;
  explanationCode: string;
  state: string;
  memberReportIds: string[];
  reportCount: number;
  distinctReporterCount: number;
  thresholdMet: boolean;
  smallCountSuppressed: boolean;
  moderatorApproved: boolean;
  safetyLegalApproved: boolean;
  publicationReady: false;
  publicCount: number | null;
  neutralLabel: string;
  version: number;
}

interface QueueItemWire {
  case_id: string;
  report_id: string;
  organisation_name: string;
  categories: string[];
  experience_start_date: string | null;
  experience_end_date: string | null;
  evidence_clean: number;
  evidence_total: number;
  state: string;
  assigned_to_me: boolean;
  version: number;
  submitted_at: string | null;
}

interface CaseWire extends QueueItemWire {
  listing_application_ref: string;
  narrative: string;
  privacy_mode: string;
  support_guidance_required: boolean;
  scan_states: string[];
}

interface ClusterWire {
  id: string;
  organisation_name: string;
  category: string;
  explanation_code: string;
  state: string;
  member_report_ids: string[];
  report_count: number;
  distinct_reporter_count: number;
  threshold_met: boolean;
  small_count_suppressed: boolean;
  moderator_approved: boolean;
  safety_legal_approved: boolean;
  publication_ready: false;
  public_count: number | null;
  neutral_label: string;
  version: number;
}

export class ModerationApiError extends Error {
  constructor(readonly status: number, readonly code: string, readonly currentVersion?: number) {
    super(code);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, { ...init, headers });
  const body = await response.json().catch(() => ({})) as T & {
    detail?: { code?: string; current_version?: number };
  };
  if (!response.ok) {
    throw new ModerationApiError(
      response.status,
      body.detail?.code ?? `http_${response.status}`,
      body.detail?.current_version,
    );
  }
  return body;
}

function mapQueue(item: QueueItemWire): ModerationQueueItem {
  return {
    caseId: item.case_id,
    reportId: item.report_id,
    organisationName: item.organisation_name,
    categories: item.categories,
    experienceStartDate: item.experience_start_date,
    experienceEndDate: item.experience_end_date,
    evidenceClean: item.evidence_clean,
    evidenceTotal: item.evidence_total,
    state: item.state,
    assignedToMe: item.assigned_to_me,
    version: item.version,
    submittedAt: item.submitted_at,
  };
}

function mapCluster(item: ClusterWire): RiskCluster {
  return {
    id: item.id,
    organisationName: item.organisation_name,
    category: item.category,
    explanationCode: item.explanation_code,
    state: item.state,
    memberReportIds: item.member_report_ids,
    reportCount: item.report_count,
    distinctReporterCount: item.distinct_reporter_count,
    thresholdMet: item.threshold_met,
    smallCountSuppressed: item.small_count_suppressed,
    moderatorApproved: item.moderator_approved,
    safetyLegalApproved: item.safety_legal_approved,
    publicationReady: item.publication_ready,
    publicCount: item.public_count,
    neutralLabel: item.neutral_label,
    version: item.version,
  };
}

export async function listModerationCases(state?: string): Promise<ModerationQueueItem[]> {
  const suffix = state ? `?state=${encodeURIComponent(state)}` : '';
  const body = await request<{ items: QueueItemWire[]; total: number }>(
    `/api/v1/moderation/internship-reports${suffix}`,
  );
  return body.items.map(mapQueue);
}

export async function getModerationCase(reportId: string): Promise<ModerationCase> {
  const item = await request<CaseWire>(
    `/api/v1/moderation/internship-reports/${encodeURIComponent(reportId)}`,
  );
  return {
    ...mapQueue(item),
    listingApplicationRef: item.listing_application_ref,
    narrative: item.narrative,
    privacyMode: item.privacy_mode,
    supportGuidanceRequired: item.support_guidance_required,
    scanStates: item.scan_states,
  };
}

export async function actOnModerationCase(
  reportId: string,
  expectedVersion: number,
  action: 'claim' | 'needs_information' | 'approve_aggregate_only' | 'reject',
  reasonDetail: string,
): Promise<void> {
  const reasonCodes = {
    claim: 'review_started',
    needs_information: 'more_information_required',
    approve_aggregate_only: 'aggregate_criteria_met',
    reject: 'insufficient_or_unverifiable',
  } as const;
  await request(`/api/v1/moderation/internship-reports/${encodeURIComponent(reportId)}/actions`, {
    method: 'POST',
    headers: { 'Idempotency-Key': `moderation-${action}-${crypto.randomUUID()}` },
    body: JSON.stringify({
      action,
      reason_code: reasonCodes[action],
      reason_detail: reasonDetail,
      expected_version: expectedVersion,
    }),
  });
}

export async function createRiskCluster(reportIds: string[], category: string): Promise<RiskCluster> {
  return mapCluster(await request<ClusterWire>('/api/v1/moderation/risk-clusters', {
    method: 'POST',
    headers: { 'Idempotency-Key': `risk-cluster-${crypto.randomUUID()}` },
    body: JSON.stringify({ report_ids: reportIds, category }),
  }));
}

export async function getRiskCluster(clusterId: string): Promise<RiskCluster> {
  return mapCluster(await request<ClusterWire>(
    `/api/v1/moderation/risk-clusters/${encodeURIComponent(clusterId)}`,
  ));
}
