import { describe, expect, it } from 'vitest';
import {
  DEFAULT_SESSION_POLICY,
  issueSession,
  isSessionActive,
  canRefresh,
  refreshSession,
  revokeSession,
  requiresReauth,
  markReauthenticated,
  isSensitiveAction,
  revokeDevice,
  deviceActive,
  FRESH_ATTEMPTS,
  isLockedOut,
  registerFailure,
  registerSuccess,
  fingerprint,
  securityEvent,
  biometricCapability,
  createStubSecurityNotifier,
  type DeviceRecord,
} from './session';

const P = DEFAULT_SESSION_POLICY;
const T0 = 1_000_000;

describe('session/device/account security (SAATHI-4 / P0.3)', () => {
  it('issues sessions that expire and refresh within policy', () => {
    const s = issueSession('u1', 'd1', T0);
    expect(isSessionActive(s, T0 + 1)).toBe(true);
    expect(isSessionActive(s, T0 + P.sessionTtlMs + 1)).toBe(false);
    // Refresh within the refresh window slides the access window forward.
    const r = refreshSession(s, T0 + P.sessionTtlMs + 10, P);
    expect(r).not.toBeNull();
    expect(isSessionActive(r!, T0 + P.sessionTtlMs + 11)).toBe(true);
    // Refresh refused after the refresh window lapses.
    expect(canRefresh(s, T0 + P.refreshTtlMs + 1)).toBe(false);
    expect(refreshSession(s, T0 + P.refreshTtlMs + 1, P)).toBeNull();
  });

  it('revoked session cannot refresh or stay active', () => {
    const s = revokeSession(issueSession('u1', 'd1', T0));
    expect(isSessionActive(s, T0 + 1)).toBe(false);
    expect(refreshSession(s, T0 + 1, P)).toBeNull();
  });

  it('requires re-auth for stale sessions before sensitive actions', () => {
    const s = issueSession('u1', 'd1', T0);
    expect(requiresReauth(s, T0 + 1)).toBe(false);
    expect(requiresReauth(s, T0 + P.reauthWithinMs + 1)).toBe(true);
    const re = markReauthenticated(s, T0 + P.reauthWithinMs + 2);
    expect(requiresReauth(re, T0 + P.reauthWithinMs + 3)).toBe(false);
    expect(isSensitiveAction('change_password')).toBe(true);
    expect(isSensitiveAction('view_dashboard')).toBe(false);
  });

  it('revokes devices and blocks their sessions', () => {
    const devices: DeviceRecord[] = [
      { deviceId: 'd1', label: 'Pixel · Chrome', lastSeen: T0, current: true, revoked: false },
      { deviceId: 'd2', label: 'Laptop · Firefox', lastSeen: T0, current: false, revoked: false },
    ];
    const next = revokeDevice(devices, 'd2');
    expect(deviceActive(next, 'd2')).toBe(false);
    expect(deviceActive(next, 'd1')).toBe(true);
  });

  it('rate-limits and locks out after repeated failures', () => {
    let a = FRESH_ATTEMPTS;
    for (let i = 0; i < P.maxFailedAttempts; i += 1) a = registerFailure(a, T0, P);
    expect(isLockedOut(a, T0 + 1)).toBe(true);
    expect(isLockedOut(a, T0 + P.lockMs + 1)).toBe(false);
    // A success clears the counter.
    expect(registerSuccess().failures).toBe(0);
  });

  it('never exposes raw secrets — fingerprints are stable + non-reversible', () => {
    const fp = fingerprint('super-secret-otp-123456');
    expect(fp.startsWith('fp_')).toBe(true);
    expect(fp).not.toContain('123456');
    expect(fingerprint('a')).toBe(fingerprint('a'));
    expect(fingerprint('a')).not.toBe(fingerprint('b'));
  });

  it('treats biometric as a capability boundary and routes notifications via adapter', () => {
    expect(biometricCapability(false)).toBe('unavailable');
    expect(biometricCapability(true)).toBe('available');
    const sink: ReturnType<typeof securityEvent>[] = [];
    const notifier = createStubSecurityNotifier(sink);
    notifier.notify(securityEvent('login_failed', 'u1', 'd1', T0));
    expect(sink).toHaveLength(1);
    expect(sink[0].type).toBe('login_failed');
  });
});
