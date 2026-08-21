/**
 * Server-authoritative student profile, settings and DPDP privacy-request
 * adapter (SAATHI-58 / S-17..S-19). Same typed-adapter + error-class pattern as
 * registrationApi.ts: snake_case wire shapes are mapped to camelCase domain
 * types, and non-2xx responses raise a typed SettingsApiError.
 *
 * Privacy: request contents/PII never touch browser storage. Only the opaque
 * server-issued privacy request id may be kept in sessionStorage so polling
 * survives a refresh.
 */
import { newRequestId } from '../../../lib/apiClient';
import { studentApiFetch } from './studentApiClient';
import { clearStudentBrowserContext } from './studentBrowserContext';

export type ThemePreference = 'system' | 'light' | 'dark';
export type PrivacyConsentKind = 'analytics' | 'marketing' | 'share_partners';

export interface PrivacyConsent {
  kind: PrivacyConsentKind;
  enabled: boolean;
}

export interface StudentProfile {
  firstName: string;
  middleName: string | null;
  lastName: string;
  college: string;
  yearOfStudy: string;
  maskedMobile: string;
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

async function jsonRequest<T>(path: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  const response = await studentApiFetch(path, { ...init, headers });
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
  return body;
}

/* ------------------------------- wire shapes ------------------------------ */

interface ProfileWire {
  first_name: string;
  middle_name: string | null;
  last_name: string;
  college: string;
  year_of_study: string;
  masked_mobile: string;
}

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

function mapProfile(wire: ProfileWire): StudentProfile {
  return {
    firstName: wire.first_name,
    middleName: wire.middle_name,
    lastName: wire.last_name,
    college: wire.college,
    yearOfStudy: wire.year_of_study,
    maskedMobile: wire.masked_mobile,
  };
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

/* --------------------------------- profile -------------------------------- */

export async function getStudentProfile(): Promise<StudentProfile> {
  return mapProfile(
    await jsonRequest<ProfileWire>('/api/v1/student/profile', { method: 'GET' }),
  );
}

export async function updateStudentProfile(patch: {
  college?: string;
  yearOfStudy?: string;
}): Promise<StudentProfile> {
  return mapProfile(
    await jsonRequest<ProfileWire>('/api/v1/student/profile', {
      method: 'PATCH',
      body: JSON.stringify({
        college: patch.college,
        year_of_study: patch.yearOfStudy,
      }),
    }),
  );
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
  const wire = await jsonRequest<{ request_id: string; status: 'pending' }>(
    '/api/v1/student/privacy/delete',
    {
      method: 'POST',
      body: JSON.stringify({
        confirmation: input.confirmation,
      }),
    },
  );
  clearStudentBrowserContext({
    notifyAuthChanged: true,
    consumeRegisteredActor: true,
  });
  return { requestId: wire.request_id, status: wire.status };
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

/* --------------------- opaque request-id session persistence --------------- */
/* Only the server-issued opaque id is stored — never request contents or PII. */

function refKey(kind: PrivacyRequestKind): string {
  return `legalsaathi.student.privacy.${kind}.v1`;
}

export function savePrivacyRequestRef(kind: PrivacyRequestKind, requestId: string): void {
  if (typeof window === 'undefined') return;
  try { window.sessionStorage.setItem(refKey(kind), requestId); } catch { /* memory polling still works */ }
}

export function loadPrivacyRequestRef(kind: PrivacyRequestKind): string | null {
  if (typeof window === 'undefined') return null;
  try { return window.sessionStorage.getItem(refKey(kind)); } catch { return null; }
}

export function clearPrivacyRequestRef(kind: PrivacyRequestKind): void {
  if (typeof window === 'undefined') return;
  try { window.sessionStorage.removeItem(refKey(kind)); } catch { /* already unavailable */ }
}
