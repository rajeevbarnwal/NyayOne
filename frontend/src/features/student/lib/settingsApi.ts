/**
 * Server-authoritative student settings and DPDP privacy-request adapter
 * (SAATHI-58 / S-18..S-19). Same typed-adapter + error-class pattern as
 * registrationApi.ts: snake_case wire shapes are mapped to camelCase domain
 * types, and non-2xx responses raise a typed SettingsApiError.
 *
 * Privacy: request contents and server-issued workflow identifiers never touch
 * browser storage. Callers may retain the current polling reference only in
 * component memory; the server remains the durable source of truth.
 */
import { newRequestId } from '../../../lib/apiClient';
import { studentApiFetch, type StudentApiLifecycleOptions } from './studentApiClient';
import { withStudentAuthTransition } from './registrationApi';

export type ThemePreference = 'system' | 'light' | 'dark';
export type PrivacyConsentKind = 'analytics' | 'marketing' | 'share_partners';

export interface PrivacyConsent {
  kind: PrivacyConsentKind;
  enabled: boolean;
}

export interface StudentSettings {
  theme: ThemePreference;
  language: string;
  notifEmail: boolean;
  notifSms: boolean;
  notifUpdates: boolean;
  version: number;
  privacy: PrivacyConsent[];
}

export interface StudentSettingsPatch {
  theme?: ThemePreference;
  language?: string;
  notifEmail?: boolean;
  notifSms?: boolean;
  notifUpdates?: boolean;
  privacy?: PrivacyConsent[];
}

export type PrivacyRequestKind = 'export' | 'delete';
export type PrivacyRequestStatus =
  | 'pending'
  | 'processing'
  | 'complete'
  | 'failed'
  | 'cancelled';

export interface PrivacyRequest {
  requestId: string;
  kind: PrivacyRequestKind;
  status: PrivacyRequestStatus;
  createdAt: string;
}

export interface PrivacyRequestAccepted {
  requestId: string;
  status: 'pending';
}

/** Typed error codes surfaced by the settings/privacy endpoints. */
export const SETTINGS_CONFLICT_CODE = 'settings_version_conflict';
export const REAUTH_REQUIRED_CODE = 'reauth_required';

export class SettingsApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly field?: string,
  ) {
    super(code);
  }
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit,
  expectedStatus?: number,
  lifecycle: StudentApiLifecycleOptions = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  const response = await studentApiFetch(path, { ...init, headers }, lifecycle);
  const body = (await response.json().catch(() => ({}))) as {
    detail?: { code?: string; field?: string } | string;
  } & T;
  if (!response.ok) {
    const detail = typeof body.detail === 'object' ? body.detail : undefined;
    throw new SettingsApiError(
      response.status,
      detail?.code ?? `http_${response.status}`,
      detail?.field,
    );
  }
  if (expectedStatus !== undefined && response.status !== expectedStatus) {
    throw new SettingsApiError(502, 'invalid_settings_response_status');
  }
  return body;
}

/* ------------------------------- wire shapes ------------------------------ */

interface SettingsWire {
  theme: ThemePreference;
  language: string;
  notif_email: boolean;
  notif_sms: boolean;
  notif_updates: boolean;
  version: number;
  privacy: Array<{ kind: PrivacyConsentKind; enabled: boolean }>;
}

interface PrivacyRequestWire {
  request_id: string;
  kind: PrivacyRequestKind;
  status: PrivacyRequestStatus;
  created_at: string;
}

function requirePrivacyRequestAccepted(value: unknown): PrivacyRequestAccepted {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new SettingsApiError(502, 'invalid_privacy_request_projection');
  }
  const wire = value as Record<string, unknown>;
  const keys = Object.keys(wire).sort();
  if (
    keys.length !== 2
    || keys[0] !== 'request_id'
    || keys[1] !== 'status'
    || typeof wire.request_id !== 'string'
    || !/^[0-9a-f]{32}$/u.test(wire.request_id)
    || wire.status !== 'pending'
  ) {
    throw new SettingsApiError(502, 'invalid_privacy_request_projection');
  }
  return { requestId: wire.request_id, status: wire.status };
}

function mapSettings(wire: SettingsWire): StudentSettings {
  return {
    theme: wire.theme,
    language: wire.language,
    notifEmail: wire.notif_email,
    notifSms: wire.notif_sms,
    notifUpdates: wire.notif_updates,
    version: wire.version,
    privacy: wire.privacy.map((p) => ({ kind: p.kind, enabled: p.enabled })),
  };
}

/* -------------------------------- settings -------------------------------- */

export async function getStudentSettings(): Promise<StudentSettings> {
  return mapSettings(
    await jsonRequest<SettingsWire>('/api/v1/student/settings', { method: 'GET' }),
  );
}

/**
 * Optimistic-concurrency PATCH: the caller passes the version it last saw. A
 * stale version raises SettingsApiError(409, 'settings_version_conflict') —
 * refetch and reapply.
 */
export async function updateStudentSettings(
  patch: StudentSettingsPatch,
  expectedVersion: number,
): Promise<StudentSettings> {
  return mapSettings(
    await jsonRequest<SettingsWire>('/api/v1/student/settings', {
      method: 'PATCH',
      body: JSON.stringify({
        theme: patch.theme,
        language: patch.language,
        notif_email: patch.notifEmail,
        notif_sms: patch.notifSms,
        notif_updates: patch.notifUpdates,
        privacy: patch.privacy?.map((p) => ({ kind: p.kind, enabled: p.enabled })),
        expected_version: expectedVersion,
      }),
    }),
  );
}

/* --------------------------- DPDP privacy requests ------------------------- */

export async function requestDataExport(
  idempotencyKey: string = newRequestId(),
): Promise<PrivacyRequestAccepted> {
  const wire = await jsonRequest<{ request_id: string; status: 'pending' }>(
    '/api/v1/student/privacy/export',
    { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey } },
  );
  return { requestId: wire.request_id, status: wire.status };
}

export async function requestAccountDeletion(input: {
  confirmation: string;
}): Promise<PrivacyRequestAccepted> {
  return withStudentAuthTransition(async (transition) => {
    const wire = await jsonRequest<unknown>(
      '/api/v1/student/privacy/delete',
      {
        method: 'POST',
        body: JSON.stringify({
          confirmation: input.confirmation,
        }),
      },
      202,
      { notifyAuthChanged: false, authTransition: transition },
    );
    return requirePrivacyRequestAccepted(wire);
  }, { requireAnonymousAfterSuccess: true });
}

export async function getPrivacyRequest(requestId: string): Promise<PrivacyRequest> {
  const wire = await jsonRequest<PrivacyRequestWire>(
    `/api/v1/student/privacy/requests/${encodeURIComponent(requestId)}`,
    { method: 'GET' },
  );
  return {
    requestId: wire.request_id,
    kind: wire.kind,
    status: wire.status,
    createdAt: wire.created_at,
  };
}
