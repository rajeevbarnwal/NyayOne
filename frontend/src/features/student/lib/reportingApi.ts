import { studentApiFetch } from './studentApiClient';

export const REPORT_CATEGORIES = [
  ['unpaid_mismatch', 'Unpaid or stipend mismatch'],
  ['excessive_hours', 'Excessive hours'],
  ['unsafe_environment', 'Unsafe environment'],
  ['harassment', 'Harassment'],
  ['discrimination', 'Discrimination'],
  ['misleading_work', 'Misleading or misrepresented work'],
  ['non_response', 'Organisation stopped responding'],
  ['certificate_withheld', 'Certificate withheld'],
  ['stipend_delay_exploitative', 'Stipend delay or exploitative work'],
  ['positive_experience', 'Positive experience'],
] as const;

export type ReportCategory = typeof REPORT_CATEGORIES[number][0];
export type ReportPrivacyMode = 'anonymous' | 'private_to_platform';

export interface ReportEvidence {
  id: string;
  mimeType: string;
  sizeBytes: number;
  checksumSha256: string;
  scanState: 'quarantined' | 'clean' | 'infected' | 'retryable_failure' | 'deleted';
  retryable: boolean;
}

export interface InternshipReport {
  id: string;
  organisationName: string;
  listingApplicationRef: string;
  experienceStartDate: string | null;
  experienceEndDate: string | null;
  categories: ReportCategory[];
  narrative: string;
  privacyMode: ReportPrivacyMode;
  consentAccepted: boolean;
  consentVersion: string | null;
  status: string;
  supportGuidanceRequired: boolean;
  evidence: ReportEvidence[];
  version: number;
  submittedAt: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ReportDraftInput {
  organisationName?: string;
  listingApplicationRef?: string;
  experienceStartDate?: string;
  experienceEndDate?: string;
  categories?: ReportCategory[];
  narrative?: string;
  privacyMode?: ReportPrivacyMode;
  consentAccepted?: boolean;
  consentVersion?: string;
}

export interface ReportStatus {
  id: string;
  status: string;
  privacyMode: ReportPrivacyMode;
  supportGuidanceRequired: boolean;
  evidenceTotal: number;
  evidenceClean: number;
  version: number;
  submittedAt: string | null;
}

interface EvidenceWire {
  id: string;
  mime_type: string;
  size_bytes: number;
  checksum_sha256: string;
  scan_state: ReportEvidence['scanState'];
  retryable: boolean;
}

interface ReportWire {
  id: string;
  organisation_name: string;
  listing_application_ref: string;
  experience_start_date: string | null;
  experience_end_date: string | null;
  categories: ReportCategory[];
  narrative: string;
  privacy_mode: ReportPrivacyMode;
  consent_accepted: boolean;
  consent_version: string | null;
  status: string;
  support_guidance_required: boolean;
  evidence: EvidenceWire[];
  version: number;
  submitted_at: string | null;
  created_at: string;
  updated_at: string;
}

interface StatusWire {
  id: string;
  status: string;
  privacy_mode: ReportPrivacyMode;
  support_guidance_required: boolean;
  evidence_total: number;
  evidence_clean: number;
  version: number;
  submitted_at: string | null;
}

export class ReportingApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly field?: string,
    readonly currentVersion?: number,
    readonly retryable = false,
  ) {
    super(code);
  }
}

function mapEvidence(item: EvidenceWire): ReportEvidence {
  return {
    id: item.id,
    mimeType: item.mime_type,
    sizeBytes: item.size_bytes,
    checksumSha256: item.checksum_sha256,
    scanState: item.scan_state,
    retryable: item.retryable,
  };
}

function mapReport(item: ReportWire): InternshipReport {
  return {
    id: item.id,
    organisationName: item.organisation_name,
    listingApplicationRef: item.listing_application_ref,
    experienceStartDate: item.experience_start_date,
    experienceEndDate: item.experience_end_date,
    categories: item.categories,
    narrative: item.narrative,
    privacyMode: item.privacy_mode,
    consentAccepted: item.consent_accepted,
    consentVersion: item.consent_version,
    status: item.status,
    supportGuidanceRequired: item.support_guidance_required,
    evidence: item.evidence.map(mapEvidence),
    version: item.version,
    submittedAt: item.submitted_at,
    createdAt: item.created_at,
    updatedAt: item.updated_at,
  };
}

function wireInput(input: ReportDraftInput) {
  const wire: Record<string, unknown> = {};
  const supplied = (key: keyof ReportDraftInput) => Object.prototype.hasOwnProperty.call(input, key);
  if (supplied('organisationName')) wire.organisation_name = input.organisationName;
  if (supplied('listingApplicationRef')) wire.listing_application_ref = input.listingApplicationRef;
  if (supplied('experienceStartDate')) wire.experience_start_date = input.experienceStartDate || null;
  if (supplied('experienceEndDate')) wire.experience_end_date = input.experienceEndDate || null;
  if (supplied('categories')) wire.categories = input.categories;
  if (supplied('narrative')) wire.narrative = input.narrative;
  if (supplied('privacyMode')) wire.privacy_mode = input.privacyMode;
  if (supplied('consentAccepted')) wire.consent_accepted = input.consentAccepted;
  if (supplied('consentVersion')) wire.consent_version = input.consentVersion;
  return wire;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData) && init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await studentApiFetch(path, { ...init, headers });
  const body = await response.json().catch(() => ({})) as {
    detail?: {
      code?: string;
      field?: string;
      current_version?: number;
      retryable?: boolean;
    };
  } & T;
  if (!response.ok) {
    throw new ReportingApiError(
      response.status,
      body.detail?.code ?? `http_${response.status}`,
      body.detail?.field,
      body.detail?.current_version,
      Boolean(body.detail?.retryable),
    );
  }
  return body;
}

export function newReportIdempotencyKey(): string {
  const random = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
  return `internship-report-${random}`;
}

export async function createInternshipReport(
  input: ReportDraftInput,
  idempotencyKey = newReportIdempotencyKey(),
): Promise<InternshipReport> {
  return mapReport(await request<ReportWire>('/api/v1/internship-reports', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify(wireInput(input)),
  }));
}

export async function listInternshipReports(): Promise<InternshipReport[]> {
  const body = await request<{ items: ReportWire[]; total: number }>('/api/v1/internship-reports');
  return body.items.map(mapReport);
}

export async function getInternshipReport(id: string): Promise<InternshipReport> {
  return mapReport(await request<ReportWire>(`/api/v1/internship-reports/${encodeURIComponent(id)}`));
}

export async function updateInternshipReport(
  id: string,
  version: number,
  input: ReportDraftInput,
): Promise<InternshipReport> {
  return mapReport(await request<ReportWire>(`/api/v1/internship-reports/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ ...wireInput(input), expected_version: version }),
  }));
}

export async function uploadInternshipReportEvidence(
  id: string,
  version: number,
  file: File,
): Promise<ReportEvidence> {
  const form = new FormData();
  form.append('expected_version', String(version));
  form.append('file', file);
  return mapEvidence(await request<EvidenceWire>(
    `/api/v1/internship-reports/${encodeURIComponent(id)}/evidence`,
    { method: 'POST', body: form },
  ));
}

export async function submitInternshipReport(id: string, version: number): Promise<InternshipReport> {
  return mapReport(await request<ReportWire>(
    `/api/v1/internship-reports/${encodeURIComponent(id)}/submit`,
    { method: 'POST', body: JSON.stringify({ expected_version: version }) },
  ));
}

export async function getInternshipReportStatus(id: string): Promise<ReportStatus> {
  const item = await request<StatusWire>(`/api/v1/internship-reports/${encodeURIComponent(id)}/status`);
  return {
    id: item.id,
    status: item.status,
    privacyMode: item.privacy_mode,
    supportGuidanceRequired: item.support_guidance_required,
    evidenceTotal: item.evidence_total,
    evidenceClean: item.evidence_clean,
    version: item.version,
    submittedAt: item.submitted_at,
  };
}

export function reportingErrorCopy(error: unknown): string {
  if (!(error instanceof ReportingApiError)) return 'The reporting service is unavailable. Please retry.';
  const copy: Record<string, string> = {
    organisation_required: 'Enter the organisation name.',
    listing_application_reference_required: 'Enter the listing or application reference.',
    experience_start_date_required: 'Enter the experience start date.',
    experience_end_date_required: 'Enter the experience end date.',
    future_experience_start_date: 'The start date cannot be in the future.',
    future_experience_end_date: 'The end date cannot be in the future.',
    experience_end_before_start: 'The end date cannot be before the start date.',
    category_required: 'Choose at least one category.',
    narrative_length_invalid: 'Use 50–5,000 characters for the factual account.',
    consent_required: 'Consent is required before private submission.',
    consent_version_stale: 'The consent notice changed. Review and accept it again.',
    evidence_file_limit: 'You may attach up to five evidence files.',
    evidence_too_large: 'Each evidence file must be 5 MiB or smaller.',
    unsupported_evidence_type: 'Use a PDF, PNG, JPG or JPEG file.',
    mime_mismatch: 'The selected file type does not match its contents.',
    extension_mismatch: 'The filename extension does not match the file contents.',
    duplicate_evidence: 'This evidence file is already attached.',
    infected_evidence: 'The file was rejected by malware screening.',
    evidence_scanner_unavailable: 'The file remains quarantined. Retry when scanning is available.',
    stale_report_version: 'This draft changed in another session. Reload and retry.',
    report_not_mutable: 'A submitted report cannot be edited.',
    internship_report_not_found: 'This report is unavailable.',
  };
  return copy[error.code] ?? `Request failed (${error.code}).`;
}
