import type { OtpFlowState } from '../lib/registrationApi';
import {
  SETTINGS_CONFLICT_CODE, SettingsApiError,
  type PrivacyConsent, type PrivacyRequestStatus, type StudentSettings,
} from '../lib/settingsApi';
import { validateSettings, type SettingsPhase } from './notificationSettingsState';

/** S-19 only. Pending drafts never become the shared, confirmed settings cache. */
export interface PrivacySettingsState {
  phase: SettingsPhase;
  settings?: StudentSettings;
  pendingConsent?: PrivacyConsent;
  retryConsent?: PrivacyConsent;
}

export const PRIVACY_KINDS = ['analytics', 'marketing', 'share_partners'] as const;
const REQUEST_STATUSES: readonly PrivacyRequestStatus[] = ['pending', 'processing', 'complete', 'failed', 'cancelled'];

export function loadPrivacySettings(value: unknown): PrivacySettingsState {
  const settings = validateSettings(value);
  const kinds = new Set<string>();
  for (const entry of settings.privacy) {
    if (!entry || !PRIVACY_KINDS.includes(entry.kind) || typeof entry.enabled !== 'boolean' || kinds.has(entry.kind)) {
      throw new SettingsApiError(502, 'invalid_privacy_projection');
    }
    kinds.add(entry.kind);
  }
  // GET synthesizes all three canonical consents, including false defaults.
  if (kinds.size !== PRIVACY_KINDS.length) throw new SettingsApiError(502, 'invalid_privacy_projection');
  return { phase: 'loaded', settings };
}

export function beginPrivacyChange(state: PrivacySettingsState, consent: PrivacyConsent): PrivacySettingsState {
  if (!state.settings || ['loading', 'saving', 'conflict', 'session', 'forbidden'].includes(state.phase)) return state;
  if (!PRIVACY_KINDS.includes(consent.kind) || typeof consent.enabled !== 'boolean') {
    throw new SettingsApiError(422, 'invalid_privacy_consent');
  }
  const current = state.settings.privacy.find(entry => entry.kind === consent.kind);
  if (!current || current.enabled === consent.enabled) return state;
  return { phase: 'saving', settings: state.settings, pendingConsent: { ...consent } };
}

export function confirmPrivacySave(state: PrivacySettingsState, value: unknown): PrivacySettingsState {
  const confirmed = loadPrivacySettings(value);
  if (state.phase !== 'saving' || !state.settings || !state.pendingConsent || !confirmed.settings
    || confirmed.settings.version <= state.settings.version
    || !confirmed.settings.privacy.some(entry => entry.kind === state.pendingConsent!.kind && entry.enabled === state.pendingConsent!.enabled)) {
    throw new SettingsApiError(502, 'invalid_privacy_save_projection');
  }
  return { ...confirmed, phase: 'saved' };
}

export function failPrivacyChange(state: PrivacySettingsState, error: unknown): PrivacySettingsState {
  if (error instanceof SettingsApiError) {
    if (error.status === 401) return { phase: 'session' };
    if (error.status === 403) return { phase: 'forbidden' };
    if (error.status === 409 && error.code === SETTINGS_CONFLICT_CODE) return { phase: 'conflict', settings: state.settings };
    if (error.status === 422) return { phase: 'invalid', settings: state.settings, retryConsent: state.pendingConsent };
  }
  return { phase: 'network', settings: state.settings, retryConsent: state.pendingConsent };
}

export interface ExportSnapshot {
  requestId: string;
  status: PrivacyRequestStatus;
}

/** POST may replay the original request at its current status under its key. */
export function readExportRequest(value: unknown): ExportSnapshot {
  const record = value as Partial<ExportSnapshot> | null;
  if (!record || typeof record.requestId !== 'string' || !/^[a-f0-9]{32}$/.test(record.requestId)
    || !REQUEST_STATUSES.includes(record.status as PrivacyRequestStatus)) {
    throw new SettingsApiError(502, 'invalid_export_projection');
  }
  return { requestId: record.requestId, status: record.status as PrivacyRequestStatus };
}

export function readExportStatus(value: unknown, expectedId: string): ExportSnapshot & { kind: 'export'; createdAt: string | null } {
  const snapshot = readExportRequest(value);
  const record = value as { kind?: unknown; createdAt?: unknown };
  if (snapshot.requestId !== expectedId || record.kind !== 'export'
    || (record.createdAt !== null && (typeof record.createdAt !== 'string' || !Number.isFinite(Date.parse(record.createdAt))))) {
    throw new SettingsApiError(502, 'invalid_export_projection');
  }
  return { ...snapshot, kind: 'export', createdAt: record.createdAt as string | null };
}

export function shouldPollExport(status: PrivacyRequestStatus): boolean {
  return status === 'pending' || status === 'processing';
}

export function privacyRequestMessage(status: PrivacyRequestStatus): { title: string; body: string } {
  return {
    pending: { title: 'Export requested.', body: 'Status: pending. The server prepares it and reports its status here.' },
    processing: { title: 'Your export is being prepared.', body: 'Status: processing.' },
    complete: { title: 'Your export is complete.', body: 'Status: complete, as returned by the server. This release has no download or delivery step on this screen; you can request another copy at any time.' },
    failed: { title: 'The export request failed.', body: 'Status: failed. You can request it again.' },
    cancelled: { title: 'The export request was cancelled.', body: 'Status: cancelled, as returned by the server. You can request another copy.' },
  }[status];
}

/** This enables a UI action only. The backend consumes and revalidates the proof.
 * A verified server projection has a null expiry budget; do not invent a timer.
 */
export function privacyDeleteReady(typed: string, flow: OtpFlowState | null, authorityReadFailed: boolean, busy: boolean): boolean {
  return !authorityReadFailed && !busy && typed === 'DELETE'
    && flow?.purpose === 'recovery' && flow.status === 'verified'
    && (flow.expiresInSeconds === null || flow.expiresInSeconds > 0);
}
