import { describe, expect, it } from 'vitest';
import { SettingsApiError, type StudentSettings } from '../lib/settingsApi';
import type { OtpFlowState } from '../lib/registrationApi';
import {
  beginPrivacyChange, confirmPrivacySave, failPrivacyChange, loadPrivacySettings,
  privacyDeleteReady, privacyRequestMessage, readExportRequest, readExportStatus,
  shouldPollExport, type PrivacySettingsState,
} from './privacySettingsState';

const settings = (): StudentSettings => ({
  theme: 'system', language: 'en', notifEmail: true, notifSms: false, notifUpdates: false, version: 7,
  privacy: [{ kind: 'analytics', enabled: false }, { kind: 'marketing', enabled: false }, { kind: 'share_partners', enabled: false }],
});
const requestId = '1234567890abcdef1234567890abcdef';
const proof = (changes: Partial<OtpFlowState> = {}): OtpFlowState => ({
  status: 'verified', purpose: 'recovery', destinationMasked: null, attemptsLeft: null,
  expiresInSeconds: 120, resendInSeconds: null, lockedForSeconds: null, resendAllowed: false, ...changes,
});

describe('S-19 consent server-confirmation boundary', () => {
  it('keeps a pending consent separate from confirmed values and expected_version', () => {
    const confirmed = settings();
    const loaded = loadPrivacySettings(confirmed);
    const saving = beginPrivacyChange(loaded, { kind: 'analytics', enabled: true });
    expect(saving.phase).toBe('saving');
    expect(saving.settings).toBe(confirmed);
    expect(saving.settings?.privacy[0].enabled).toBe(false);
    expect(saving.settings?.version).toBe(7);
    expect(saving.pendingConsent).toEqual({ kind: 'analytics', enabled: true });
    expect(loaded.phase).toBe('loaded');
  });
  it('only reports saved after a newer version echoes the requested consent', () => {
    const saving = beginPrivacyChange(loadPrivacySettings(settings()), { kind: 'analytics', enabled: true });
    const returned = { ...settings(), version: 8, privacy: [{ kind: 'analytics' as const, enabled: true }, ...settings().privacy.slice(1)] };
    expect(confirmPrivacySave(saving, returned)).toEqual({ phase: 'saved', settings: returned });
  });
  it.each([7, 6])('rejects stale save acknowledgment version %s', version => {
    const saving = beginPrivacyChange(loadPrivacySettings(settings()), { kind: 'analytics', enabled: true });
    expect(() => confirmPrivacySave(saving, { ...settings(), version })).toThrow('invalid_privacy_save_projection');
  });
  it('rejects a newer version that did not save the requested consent', () => {
    const saving = beginPrivacyChange(loadPrivacySettings(settings()), { kind: 'analytics', enabled: true });
    expect(() => confirmPrivacySave(saving, { ...settings(), version: 8 })).toThrow('invalid_privacy_save_projection');
  });
  it('cannot turn a GET response into a successful save', () => {
    expect(() => confirmPrivacySave(loadPrivacySettings(settings()), settings())).toThrow('invalid_privacy_save_projection');
  });
  it('rolls a failed save back and retains only the retry draft', () => {
    const saving = beginPrivacyChange(loadPrivacySettings(settings()), { kind: 'analytics', enabled: true });
    const failed = failPrivacyChange(saving, new Error('offline'));
    expect(failed.phase).toBe('network');
    expect(failed.settings?.privacy[0].enabled).toBe(false);
    expect(failed.pendingConsent).toBeUndefined();
    expect(failed.retryConsent).toEqual({ kind: 'analytics', enabled: true });
  });
  it('requires an explicit authoritative reload after a version conflict', () => {
    const saving = beginPrivacyChange(loadPrivacySettings(settings()), { kind: 'analytics', enabled: true });
    const conflict = failPrivacyChange(saving, new SettingsApiError(409, 'settings_version_conflict'));
    expect(conflict.phase).toBe('conflict');
    expect(conflict.retryConsent).toBeUndefined();
    expect(beginPrivacyChange(conflict, { kind: 'marketing', enabled: true })).toBe(conflict);
    const reloaded = loadPrivacySettings({ ...settings(), version: 10 });
    expect(beginPrivacyChange(reloaded, { kind: 'marketing', enabled: true }).settings?.version).toBe(10);
  });
  it.each(['loading', 'saving', 'conflict', 'session', 'forbidden'] as const)('does not dispatch from %s', phase => {
    const state: PrivacySettingsState = { phase, settings: settings() };
    expect(beginPrivacyChange(state, { kind: 'analytics', enabled: true })).toBe(state);
  });
  it('ignores unchanged consent and refuses invented consent kinds', () => {
    const state = loadPrivacySettings(settings());
    expect(beginPrivacyChange(state, { kind: 'analytics', enabled: false })).toBe(state);
    expect(() => beginPrivacyChange(state, { kind: 'unknown' as 'analytics', enabled: true })).toThrow('invalid_privacy_consent');
  });
  it.each([
    [], [{ kind: 'analytics', enabled: false }],
    [{ kind: 'analytics', enabled: false }, { kind: 'analytics', enabled: false }, { kind: 'share_partners', enabled: false }],
    [{ kind: 'analytics', enabled: 'false' }, { kind: 'marketing', enabled: false }, { kind: 'share_partners', enabled: false }],
    [null, ...settings().privacy.slice(1)],
  ].map(privacy => ({ privacy })))('fails closed on incomplete or malformed canonical consents ($privacy)', ({ privacy }) => {
    expect(() => loadPrivacySettings({ ...settings(), privacy })).toThrow('invalid_privacy_projection');
  });
  it.each([undefined, null, {}, { ...settings(), version: -1 }, { ...settings(), version: 1.5 }])('rejects malformed settings (%j)', value => {
    expect(() => loadPrivacySettings(value)).toThrow();
  });
  it.each([[401, 'session'], [403, 'forbidden'], [422, 'invalid']] as const)('maps HTTP %s without inventing success', (status, phase) => {
    const state = failPrivacyChange(loadPrivacySettings(settings()), new SettingsApiError(status, 'server_error'));
    expect(state.phase).toBe(phase);
    if (status === 401 || status === 403) expect(state.settings).toBeUndefined();
  });
});

describe('S-19 export status is a current-visit server projection', () => {
  it.each(['pending', 'processing', 'complete', 'failed', 'cancelled'] as const)('keeps %s distinct, including idempotent POST replies', status => {
    expect(readExportRequest({ requestId, status })).toEqual({ requestId, status });
    expect(readExportStatus({ requestId, status, kind: 'export', createdAt: null }, requestId)).toEqual({ requestId, status, kind: 'export', createdAt: null });
    expect(privacyRequestMessage(status).title).toBeTruthy();
    expect(shouldPollExport(status)).toBe(status === 'pending' || status === 'processing');
  });
  it.each(['', 'dsr_prototype', '../other', 'a'.repeat(31), 'g'.repeat(32)])('rejects invalid request reference %s', id => {
    expect(() => readExportRequest({ requestId: id, status: 'pending' })).toThrow('invalid_export_projection');
  });
  it.each(['completed', 'accepted', 'unknown', undefined])('rejects invented status %s', status => {
    expect(() => readExportRequest({ requestId, status })).toThrow('invalid_export_projection');
  });
  it('refuses mismatched IDs and deletion records in export status responses', () => {
    const data = { requestId, kind: 'export', status: 'pending', createdAt: null };
    expect(() => readExportStatus(data, 'a'.repeat(32))).toThrow('invalid_export_projection');
    expect(() => readExportStatus({ ...data, kind: 'delete' }, requestId)).toThrow('invalid_export_projection');
  });
  it('does not promise an email, download, or cancellation action', () => {
    const complete = privacyRequestMessage('complete');
    expect(complete.body).toContain('no download or delivery step');
    expect(complete.body).not.toContain('registered email');
    expect(privacyRequestMessage('cancelled').body).toContain('server');
  });
});

describe('S-19 deletion UI cannot manufacture recovery authority', () => {
  it('requires exact DELETE and current server-verified recovery proof', () => {
    expect(privacyDeleteReady('DELETE', proof(), false, false)).toBe(true);
    // otp_flow_service.verified_state deliberately omits a client expiry budget.
    expect(privacyDeleteReady('DELETE', proof({ expiresInSeconds: null }), false, false)).toBe(true);
  });
  it.each(['', 'delete', ' DELETE', 'DELETE ', 'DELETE\n'])('rejects non-exact confirmation %j', typed => {
    expect(privacyDeleteReady(typed, proof(), false, false)).toBe(false);
  });
  it.each([
    null, proof({ purpose: 'signup' }), proof({ purpose: 'login' }), proof({ purpose: null }),
    proof({ status: 'pending' }), proof({ status: 'unavailable' }), proof({ status: 'authenticated' }),
    proof({ expiresInSeconds: 0 }), proof({ expiresInSeconds: -1 }),
  ])('rejects stale, missing or wrong-purpose proof (%j)', flow => {
    expect(privacyDeleteReady('DELETE', flow, false, false)).toBe(false);
  });
  it('fails closed on an authority read failure and a request already in flight', () => {
    expect(privacyDeleteReady('DELETE', proof(), true, false)).toBe(false);
    expect(privacyDeleteReady('DELETE', proof(), false, true)).toBe(false);
  });
});
