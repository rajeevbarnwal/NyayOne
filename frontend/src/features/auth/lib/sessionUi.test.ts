import { describe, expect, it } from 'vitest';
import {
  DEFAULT_SESSION_POLICY, issueSession, expiryWarning, isUnusualLogin, revokeAllOtherDevices,
  type DeviceRecord,
} from './session';

const P = DEFAULT_SESSION_POLICY;
const T0 = 1_000_000;

describe('P0.3 derived UI states (SAATHI-4 remediation)', () => {
  it('flags an expiry warning within the threshold', () => {
    const s = issueSession('u1', 'd1', T0);
    expect(expiryWarning(s, T0 + 1)).toBe(false);
    expect(expiryWarning(s, T0 + P.sessionTtlMs - 60_000)).toBe(true); // 1 min left
    expect(expiryWarning(s, T0 + P.sessionTtlMs + 1)).toBe(false); // already expired
  });

  it('detects an unusual (unknown/revoked) login device', () => {
    const known: DeviceRecord[] = [
      { deviceId: 'd1', label: 'This device', lastSeen: T0, current: true, revoked: false },
      { deviceId: 'd2', label: 'Old phone', lastSeen: T0, current: false, revoked: true },
    ];
    expect(isUnusualLogin('d1', known)).toBe(false);
    expect(isUnusualLogin('d2', known)).toBe(true); // revoked → treated as unusual
    expect(isUnusualLogin('d9', known)).toBe(true); // unknown
  });

  it('logs out all other devices but keeps the current one', () => {
    const devices: DeviceRecord[] = [
      { deviceId: 'd1', label: 'This device', lastSeen: T0, current: true, revoked: false },
      { deviceId: 'd2', label: 'Laptop', lastSeen: T0, current: false, revoked: false },
      { deviceId: 'd3', label: 'Tablet', lastSeen: T0, current: false, revoked: false },
    ];
    const next = revokeAllOtherDevices(devices);
    expect(next.find((d) => d.deviceId === 'd1')!.revoked).toBe(false);
    expect(next.filter((d) => d.revoked)).toHaveLength(2);
  });
});
