import { apiFetch } from '../../../lib/apiClient';

const CLAIMS = 'X-Actor-Claims';
export const DEV_STUDENT_ID = '00000000-0000-4000-8000-0000000000de';
export const DEV_ISSUER_ID = '00000000-0000-4000-8000-0000000000c3';
const STUDENT_CLAIMS = JSON.stringify({ sub: DEV_STUDENT_ID, roles: ['student'] });
const ISSUER_CLAIMS = JSON.stringify({ sub: DEV_ISSUER_ID, roles: ['lawyer'] });

export const CREDENTIAL_TYPES = [
  { value: 'certificate', label: 'Certificate' },
  { value: 'badge', label: 'Badge' },
  { value: 'moot_achievement', label: 'Moot achievement' },
  { value: 'course_completion', label: 'Course completion' },
  { value: 'employment', label: 'Employment' },
  { value: 'other', label: 'Other' },
] as const;

export const PUBLIC_CREDENTIAL_FIELDS = [
  'title',
  'credential_type',
  'status',
  'issue_date',
  'expiry_date',
  'issuer_display_name',
  'verification_timestamp',
  'student_name',
] as const;

export type PublicCredentialField = typeof PUBLIC_CREDENTIAL_FIELDS[number];
export type CredentialStatus =
  | 'self_declared'
  | 'pending_verification'
  | 'verified'
  | 'expired'
  | 'revoked';

export interface CredentialEvidence {
  id: string;
  mime: string;
  sizeBytes: number;
  sha256: string;
  scanState: 'quarantined' | 'clean' | 'infected' | 'retryable_failure' | 'deleted';
}

export interface CredentialRecord {
  id: string;
  title: string;
  credentialType: string;
  status: CredentialStatus;
  issueDate: string;
  expiryDate: string | null;
  issuerId: string | null;
  issuerDisplayName: string | null;
  identifier: string | null;
  version: number;
  evidence: CredentialEvidence[];
  createdAt: string;
  updatedAt: string;
}

export interface CredentialHistoryItem {
  id: string;
  fromStatus: string | null;
  toStatus: string;
  reasonCode: string;
  createdAt: string;
}

export class CredentialsApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly field?: string,
    readonly currentVersion?: number,
  ) {
    super(code);
  }
}

interface EvidenceWire {
  id: string;
  mime: string;
  size_bytes: number;
  sha256: string;
  scan_state: CredentialEvidence['scanState'];
}

interface CredentialWire {
  id: string;
  title: string;
  credential_type: string;
  status: CredentialStatus;
  issue_date: string;
  expiry_date: string | null;
  issuer_id: string | null;
  issuer_display_name: string | null;
  identifier: string | null;
  version: number;
  evidence: EvidenceWire[];
  created_at: string;
  updated_at: string;
}

function mapCredential(wire: CredentialWire): CredentialRecord {
  return {
    id: wire.id,
    title: wire.title,
    credentialType: wire.credential_type,
    status: wire.status,
    issueDate: wire.issue_date,
    expiryDate: wire.expiry_date,
    issuerId: wire.issuer_id,
    issuerDisplayName: wire.issuer_display_name,
    identifier: wire.identifier,
    version: wire.version,
    evidence: wire.evidence.map((item) => ({
      id: item.id,
      mime: item.mime,
      sizeBytes: item.size_bytes,
      sha256: item.sha256,
      scanState: item.scan_state,
    })),
    createdAt: wire.created_at,
    updatedAt: wire.updated_at,
  };
}

export function newIdempotencyKey(prefix: string): string {
  const random = globalThis.crypto?.randomUUID?.()
    ?? `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  actor: 'student' | 'issuer' | 'public' = 'student',
): Promise<T> {
  const headers = new Headers(init.headers);
  if (actor !== 'public') {
    headers.set(CLAIMS, actor === 'issuer' ? ISSUER_CLAIMS : STUDENT_CLAIMS);
  }
  if (!(init.body instanceof FormData) && init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await apiFetch(path, { ...init, headers });
  const body = await response.json().catch(() => ({})) as {
    detail?: { code?: string; field?: string; current_version?: number };
  } & T;
  if (!response.ok) {
    throw new CredentialsApiError(
      response.status,
      body.detail?.code ?? `http_${response.status}`,
      body.detail?.field,
      body.detail?.current_version,
    );
  }
  return body;
}

export async function listCredentials(
  statusFilter?: CredentialStatus,
  page = 1,
): Promise<{ items: CredentialRecord[]; total: number; page: number }> {
  const query = new URLSearchParams({ page: String(page), page_size: '20' });
  if (statusFilter) query.set('status_filter', statusFilter);
  const wire = await request<{ items: CredentialWire[]; total: number; page: number }>(
    `/api/v1/credentials?${query}`,
  );
  return { ...wire, items: wire.items.map(mapCredential) };
}

export async function listCredentialIssuers(): Promise<Array<{
  id: string;
  displayName: string;
  issuerType: string;
}>> {
  const wire = await request<{
    items: Array<{ id: string; display_name: string; issuer_type: string }>;
  }>('/api/v1/credential-issuers');
  return wire.items.map((item) => ({
    id: item.id,
    displayName: item.display_name,
    issuerType: item.issuer_type,
  }));
}

export async function getCredential(id: string): Promise<CredentialRecord> {
  return mapCredential(await request<CredentialWire>(
    `/api/v1/credentials/${encodeURIComponent(id)}`,
  ));
}

export interface CredentialInput {
  title: string;
  credentialType: string;
  issueDate: string;
  expiryDate?: string;
  issuerId?: string;
  identifier?: string;
}

export async function createCredential(
  input: CredentialInput,
  idempotencyKey: string,
): Promise<CredentialRecord> {
  return mapCredential(await request<CredentialWire>('/api/v1/credentials', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({
      title: input.title,
      credential_type: input.credentialType,
      issue_date: input.issueDate,
      expiry_date: input.expiryDate || null,
      issuer_id: input.issuerId || null,
      identifier: input.identifier || null,
    }),
  }));
}

export async function uploadCredentialEvidence(
  credentialId: string,
  file: File,
): Promise<{ id: string; scanState: string; status: CredentialStatus; retryable: boolean }> {
  const body = new FormData();
  body.append('file', file);
  const wire = await request<{
    id: string;
    scan_state: string;
    status: CredentialStatus;
    retryable: boolean;
  }>(`/api/v1/credentials/${encodeURIComponent(credentialId)}/evidence`, {
    method: 'POST',
    body,
  });
  return {
    id: wire.id,
    scanState: wire.scan_state,
    status: wire.status,
    retryable: wire.retryable,
  };
}

export async function deleteCredential(id: string): Promise<void> {
  await request(`/api/v1/credentials/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function createShareProjection(
  credentialId: string,
  fields: PublicCredentialField[],
  idempotencyKey: string,
): Promise<{ id: string; credentialId: string; fields: PublicCredentialField[]; active: boolean }> {
  const wire = await request<{
    id: string;
    credential_id: string;
    fields: PublicCredentialField[];
    active: boolean;
  }>(`/api/v1/credentials/${encodeURIComponent(credentialId)}/share-projections`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ fields }),
  });
  return { id: wire.id, credentialId: wire.credential_id, fields: wire.fields, active: wire.active };
}

export async function createVerificationToken(
  credentialId: string,
  projectionId: string,
  lifetimeDays: number,
  idempotencyKey: string,
): Promise<{ id: string; token: string; verificationUrl: string; expiresAt: string }> {
  const wire = await request<{
    id: string;
    token: string;
    verification_url: string;
    expires_at: string;
  }>(`/api/v1/credentials/${encodeURIComponent(credentialId)}/verification-tokens`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ projection_id: projectionId, lifetime_days: lifetimeDays }),
  });
  return {
    id: wire.id,
    token: wire.token,
    verificationUrl: wire.verification_url,
    expiresAt: wire.expires_at,
  };
}

export async function revokeVerificationToken(
  credentialId: string,
  tokenId: string,
): Promise<void> {
  await request(
    `/api/v1/credentials/${encodeURIComponent(credentialId)}/verification-tokens/${encodeURIComponent(tokenId)}`,
    { method: 'DELETE' },
  );
}

export async function verifyCredential(
  credentialId: string,
  expectedVersion: number,
  idempotencyKey: string,
): Promise<{ status: CredentialStatus; version: number }> {
  return request(
    `/api/v1/issuer/credentials/${encodeURIComponent(credentialId)}/verify`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ expected_version: expectedVersion }),
    },
    'issuer',
  );
}

export async function revokeCredentialAsIssuer(
  credentialId: string,
  expectedVersion: number,
  reason: string,
  idempotencyKey: string,
): Promise<{ status: CredentialStatus; version: number }> {
  return request(
    `/api/v1/issuer/credentials/${encodeURIComponent(credentialId)}/revoke`,
    {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ expected_version: expectedVersion, reason }),
    },
    'issuer',
  );
}

export async function getCredentialHistory(
  credentialId: string,
): Promise<CredentialHistoryItem[]> {
  const wire = await request<{
    items: Array<{
      id: string;
      from_status: string | null;
      to_status: string;
      reason_code: string;
      created_at: string;
    }>;
  }>(`/api/v1/issuer/credentials/${encodeURIComponent(credentialId)}/history`);
  return wire.items.map((item) => ({
    id: item.id,
    fromStatus: item.from_status,
    toStatus: item.to_status,
    reasonCode: item.reason_code,
    createdAt: item.created_at,
  }));
}

export async function getPublicCredentialVerification(token: string): Promise<{
  verification: Partial<Record<PublicCredentialField, string | null>>;
  tokenExpiresAt: string;
}> {
  const wire = await request<{
    verification: Partial<Record<PublicCredentialField, string | null>>;
    token_expires_at: string;
  }>(
    `/api/v1/public/credential-verifications/${encodeURIComponent(token)}`,
    {},
    'public',
  );
  return { verification: wire.verification, tokenExpiresAt: wire.token_expires_at };
}

export function isRetryableCredentialsError(error: unknown): boolean {
  return !(error instanceof CredentialsApiError && error.status >= 400 && error.status < 500);
}
