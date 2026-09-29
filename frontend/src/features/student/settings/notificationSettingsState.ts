import { SettingsApiError, SETTINGS_CONFLICT_CODE, type StudentSettings, type StudentSettingsPatch } from '../lib/settingsApi';

export type SettingsPhase = 'loading' | 'loaded' | 'dirty' | 'saving' | 'saved' | 'invalid' | 'conflict' | 'network' | 'forbidden' | 'session';
export type NotificationPatch = Omit<StudentSettingsPatch, 'privacy'>;
export interface NotificationSettingsState {
  phase: SettingsPhase;
  settings?: StudentSettings;
  pending?: NotificationPatch;
  expectedVersion?: number;
  retryPatch?: NotificationPatch;
  invalidField?: string;
}
export const initialSettingsState: NotificationSettingsState = { phase: 'loading' };

/** S-18 boundary validation; never treat a malformed 2xx body as a saved preference. */
export function validateSettings(value: unknown): StudentSettings {
  const s = value as StudentSettings | null;
  if (!s || !['system', 'light', 'dark'].includes(s.theme) || !['en', 'hi'].includes(s.language)
    || !Number.isSafeInteger(s.version) || s.version < 0
    || [s.notifEmail, s.notifSms, s.notifUpdates].some(v => typeof v !== 'boolean')
    || !Array.isArray(s.privacy)) throw new SettingsApiError(502, 'invalid_settings_projection');
  return s;
}
export function confirmedSettings(value: unknown, saved = false): NotificationSettingsState {
  return { phase: saved ? 'saved' : 'loaded', settings: validateSettings(value) };
}
export function beginSettingsChange(state: NotificationSettingsState, patch: NotificationPatch): NotificationSettingsState {
  if (!state.settings || ['saving', 'loading', 'conflict', 'session', 'forbidden'].includes(state.phase)) return state;
  // The draft is visible only as pending. The confirmed settings/version do not
  // advance until the server responds. One in-flight write owns this version.
  return { phase: 'saving', settings: state.settings, pending: patch, expectedVersion: state.settings.version };
}
export function failSettingsChange(state: NotificationSettingsState, error: unknown): NotificationSettingsState {
  if (error instanceof SettingsApiError) {
    if (error.status === 401) return { phase: 'session' };
    if (error.status === 403) return { phase: 'forbidden' };
    if (error.status === 409 && error.code === SETTINGS_CONFLICT_CODE) return { phase: 'conflict', settings: state.settings };
    if (error.status === 422) return { phase: 'invalid', settings: state.settings, invalidField: error.field ?? Object.keys(state.pending ?? {})[0] };
  }
  return { phase: 'network', settings: state.settings, retryPatch: state.pending };
}
