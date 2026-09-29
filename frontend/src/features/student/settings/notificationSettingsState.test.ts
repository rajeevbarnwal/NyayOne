import { describe, expect, it } from 'vitest';
import { SettingsApiError, type StudentSettings } from '../lib/settingsApi';
import { beginSettingsChange, confirmedSettings, failSettingsChange, initialSettingsState, validateSettings } from './notificationSettingsState';

const server: StudentSettings = { theme: 'system', language: 'en', notifEmail: true, notifSms: false, notifUpdates: false, version: 7, privacy: [] };
describe('S-18 server-confirmed preference state', () => {
  it('starts loading with no fabricated preferences', () => {
    expect(initialSettingsState).toEqual({ phase: 'loading' });
  });
  it('keeps dirty draft separate from persistence during a versioned save', () => {
    const next = beginSettingsChange(confirmedSettings(server), { notifSms: true });
    expect(next.phase).toBe('saving');
    expect(next.settings).toBe(server);
    expect(next.settings?.notifSms).toBe(false);
    expect(next.pending).toEqual({ notifSms: true });
    expect(next.expectedVersion).toBe(7);
  });
  it('rejects duplicate activation and never mutates during conflict or missing authority', () => {
    const pending = beginSettingsChange(confirmedSettings(server), { notifSms: true });
    expect(beginSettingsChange(pending, { notifEmail: false })).toBe(pending);
    expect(beginSettingsChange(initialSettingsState, { notifSms: true })).toBe(initialSettingsState);
    const conflict = failSettingsChange(pending, new SettingsApiError(409, 'settings_version_conflict'));
    expect(beginSettingsChange(conflict, { notifSms: true })).toBe(conflict);
  });
  it('reports saved only from confirmed server values and the returned version', () => {
    const result = confirmedSettings({ ...server, notifSms: true, version: 8 }, true);
    expect(result.phase).toBe('saved');
    expect(result.settings?.version).toBe(8);
    expect(result.pending).toBeUndefined();
  });
  it('rolls back a failed draft and retains it only for explicit retry', () => {
    const pending = beginSettingsChange(confirmedSettings(server), { theme: 'dark' });
    const failure = failSettingsChange(pending, new Error('network'));
    expect(failure.phase).toBe('network');
    expect(failure.settings?.theme).toBe('system');
    expect(failure.retryPatch).toEqual({ theme: 'dark' });
    expect(failure.pending).toBeUndefined();
  });
  it.each([[401, 'session'], [403, 'forbidden'], [422, 'invalid'], [409, 'conflict']] as const)(
    'handles HTTP %s as %s without claiming persistence', (status, phase) => {
      const pending = beginSettingsChange(confirmedSettings(server), { language: 'en' });
      const result = failSettingsChange(pending, new SettingsApiError(status, status === 409 ? 'settings_version_conflict' : 'http_' + status));
      expect(result.phase).toBe(phase);
      expect(result.pending).toBeUndefined();
      if (status === 401 || status === 403) expect(result.settings).toBeUndefined();
      else expect(result.settings).toBe(server);
      if (status === 422) expect(result.invalidField).toBe('language');
    },
  );
  it.each([
    { ...server, version: undefined }, { ...server, version: -1 },
    { ...server, notifEmail: 'true' }, { ...server, theme: 'invented' },
    { ...server, language: 'invented' }, null,
  ])('fails closed on malformed settings %j', value => {
    expect(() => validateSettings(value)).toThrow('invalid_settings_projection');
  });
  it('validates stored Hindi without claiming that a Hindi interface exists', () => {
    expect(validateSettings({ ...server, language: 'hi' }).language).toBe('hi');
  });
});
