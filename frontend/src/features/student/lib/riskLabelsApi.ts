import { apiFetch } from '../../../lib/apiClient';

const PUBLIC_LABEL_BASE = '/api/v1/public/internship-risk-labels';
const ORGANISATION_RESPONSE_BASE = '/api/v1/organisation-responses';

export type RiskLabelSourceType = 'moderated_aggregate';
export type PublicRiskLabelStatus = 'approved' | 'corrected';
export type OrganisationResponseKind = 'initial' | 'correction' | 'appeal';

export interface ApprovedOrganisationResponse {
  text: string;
  lastReviewedAt: string;
  kind: OrganisationResponseKind;
}

export interface PublicRiskLabel {
  id: string;
  category: string;
  neutralLabel: string;
  publicCount: number | null;
  lastReviewedAt: string;
  sourceType: RiskLabelSourceType;
  status: PublicRiskLabelStatus;
  organisationResponse: ApprovedOrganisationResponse | null;
}

export interface PublicRiskLabelProjection {
  organisationId: string;
  labels: PublicRiskLabel[];
  available: boolean;
}

export interface SubmittedOrganisationResponse {
  id: string;
  publishedLabelId: string;
  state: 'moderation_pending';
  version: number;
  createdAt: string;
}

interface OrganisationResponseWire {
  text: string;
  last_reviewed_at: string;
  kind: OrganisationResponseKind;
}

interface PublicRiskLabelWire {
  id: string;
  category: string;
  neutral_label: string;
  public_count: number | null;
  last_reviewed_at: string;
  source_type: RiskLabelSourceType;
  status: PublicRiskLabelStatus;
  organisation_response: OrganisationResponseWire | null;
}

interface PublicRiskLabelProjectionWire {
  organisation_id: string;
  labels: PublicRiskLabelWire[];
  available: boolean;
}

interface SubmittedOrganisationResponseWire {
  id: string;
  published_label_id: string;
  state: 'moderation_pending';
  version: number;
  submitted_at: string;
}

interface ErrorDetail {
  code?: string;
  message?: string;
  field?: string;
  retryable?: boolean;
}

export class RiskLabelApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly field?: string,
    readonly retryable = false,
  ) {
    super(message);
    this.name = 'RiskLabelApiError';
  }
}

async function jsonRequest<T>(path: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, { ...init, headers });
  const body = await response.json().catch(() => ({})) as T & {
    detail?: ErrorDetail | string;
  };
  if (!response.ok) {
    const detail = typeof body.detail === 'object' ? body.detail : undefined;
    throw new RiskLabelApiError(
      response.status,
      detail?.code ?? `http_${response.status}`,
      detail?.message ?? 'This public safety signal is unavailable.',
      detail?.field,
      Boolean(detail?.retryable),
    );
  }
  return body;
}

function mapResponse(item: OrganisationResponseWire): ApprovedOrganisationResponse | null {
  if (!['initial', 'correction', 'appeal'].includes(item.kind)) return null;
  return { text: item.text, lastReviewedAt: item.last_reviewed_at, kind: item.kind };
}

function mapLabel(item: PublicRiskLabelWire): PublicRiskLabel | null {
  // A withdrawn or otherwise unknown state must publish nothing even if an
  // upstream regression accidentally includes it in the public projection.
  if (!['approved', 'corrected'].includes(item.status) || item.source_type !== 'moderated_aggregate') return null;
  return {
    id: item.id,
    category: item.category,
    neutralLabel: item.neutral_label,
    publicCount: item.public_count,
    lastReviewedAt: item.last_reviewed_at,
    sourceType: item.source_type,
    status: item.status,
    organisationResponse: item.organisation_response ? mapResponse(item.organisation_response) : null,
  };
}

export function publicRiskLabelsKey(organisationId: string): readonly [string, string] {
  return ['public-internship-risk-labels', organisationId] as const;
}

export async function getPublicRiskLabels(organisationId: string): Promise<PublicRiskLabelProjection> {
  const wire = await jsonRequest<PublicRiskLabelProjectionWire>(
    `${PUBLIC_LABEL_BASE}/${encodeURIComponent(organisationId)}`,
    { method: 'GET' },
  );
  return {
    organisationId: wire.organisation_id,
    labels: wire.labels.map(mapLabel).filter((label): label is PublicRiskLabel => label !== null),
    available: wire.available,
  };
}

export function newOrganisationResponseIdempotencyKey(): string {
  const random = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
  return `organisation-response-${random}`;
}

export async function submitOrganisationResponse(
  token: string,
  responseText: string,
  idempotencyKey = newOrganisationResponseIdempotencyKey(),
): Promise<SubmittedOrganisationResponse> {
  const wire = await jsonRequest<SubmittedOrganisationResponseWire>(ORGANISATION_RESPONSE_BASE, {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
      'X-Organisation-Response-Token': token,
    },
    body: JSON.stringify({ response_text: responseText }),
  });
  return {
    id: wire.id,
    publishedLabelId: wire.published_label_id,
    state: wire.state,
    version: wire.version,
    createdAt: wire.submitted_at,
  };
}

export type RiskLabelUnavailableState =
  | 'disabled'
  | 'insufficient'
  | 'approval_pending'
  | 'permission'
  | 'retryable'
  | 'unavailable';

export function riskLabelUnavailableState(error: unknown): RiskLabelUnavailableState {
  if (!(error instanceof RiskLabelApiError)) return 'retryable';
  if (['risk_labels_disabled', 'risk_labels_unavailable'].includes(error.code)) return 'disabled';
  if (['risk_threshold_not_met', 'risk_label_insufficient_evidence'].includes(error.code)) return 'insufficient';
  if (['risk_approval_required', 'risk_label_approval_incomplete'].includes(error.code)) return 'approval_pending';
  if ([401, 403].includes(error.status)) return 'permission';
  if (error.retryable || error.status >= 500) return 'retryable';
  return 'unavailable';
}

export function riskLabelErrorCopy(error: unknown): string {
  const state = riskLabelUnavailableState(error);
  const values: Record<RiskLabelUnavailableState, string> = {
    disabled: 'Public organisation safety signals are not enabled.',
    insufficient: 'No aggregate signal meets the publication threshold.',
    approval_pending: 'No aggregate signal has completed independent approval.',
    permission: 'You do not have permission to view this safety signal.',
    retryable: 'The safety-signal service is temporarily unavailable. Retry safely.',
    unavailable: 'No public aggregate signal is available.',
  };
  return values[state];
}

export function organisationResponseErrorCopy(error: unknown): string {
  if (!(error instanceof RiskLabelApiError)) {
    return 'The response could not be submitted. Retry without sharing the invitation link.';
  }
  if (['response_token_unavailable', 'response_token_expired', 'response_token_replayed', 'response_token_invalid'].includes(error.code)) {
    return 'This invitation is invalid, expired or already used. Ask LegalSaathi for a new verified invitation.';
  }
  if (error.code === 'response_correction_target_changed') {
    return 'This correction invitation is no longer current. Ask LegalSaathi for a new verified invitation.';
  }
  if (error.code === 'idempotency_conflict') {
    return 'This submission attempt conflicted with an earlier request. Start a fresh submission attempt.';
  }
  if (error.code === 'organisation_response_length_invalid' || error.field === 'response_text') {
    return 'Use 1–2,000 characters for the organisation response or correction.';
  }
  if (error.status === 429) return 'Too many attempts. Request a fresh invitation later.';
  if (error.retryable || error.status >= 500) return 'The response service is temporarily unavailable. Retry safely.';
  return 'The response could not be submitted. Ask LegalSaathi for a new verified invitation.';
}

export type OrganisationResponseFailureState = 'invitation-unavailable' | 'conflict' | 'retryable' | 'unavailable';

export function organisationResponseFailureState(error: unknown): OrganisationResponseFailureState {
  if (!(error instanceof RiskLabelApiError)) return 'retryable';
  if (['response_token_unavailable', 'response_token_expired', 'response_token_replayed', 'response_token_invalid'].includes(error.code)) {
    return 'invitation-unavailable';
  }
  if (error.code === 'response_correction_target_changed') return 'invitation-unavailable';
  if (error.code === 'idempotency_conflict' && error.status === 409) return 'conflict';
  if (error.retryable || error.status >= 500) return 'retryable';
  return 'unavailable';
}
