import { describe, expect, it, vi } from 'vitest';
import type { OtpFlowState } from '../lib/registrationApi';
import { canVerifyRecovery, recoveryView, runRecoveryCompletion } from './S06Recovery';

const pending: OtpFlowState = { status: 'pending', purpose: 'recovery', destinationMasked: '••••••0340', attemptsLeft: 3, expiresInSeconds: 272, resendInSeconds: 22, lockedForSeconds: 0, resendAllowed: false };
const verified: OtpFlowState = { status: 'verified', purpose: 'recovery', destinationMasked: null, attemptsLeft: null, expiresInSeconds: null, resendInSeconds: null, lockedForSeconds: null, resendAllowed: false };
const retired: OtpFlowState = { ...verified, status: 'unavailable', purpose: null };

describe('NYAY-85 S-06 recovery authority and continuation', () => {
  it('requires a complete code and current server recovery capability', () => {
    expect(canVerifyRecovery(pending, '123456', false, false)).toBe(true);
    for (const code of ['', '12345', '1234567', '12ab56']) expect(canVerifyRecovery(pending, code, false, false)).toBe(false);
    for (const state of [null, { ...pending, purpose: 'login' as const }, verified, { ...pending, attemptsLeft: 0 }, { ...pending, expiresInSeconds: 0 }, { ...pending, lockedForSeconds: 1 }]) expect(canVerifyRecovery(state, '123456', false, false)).toBe(false);
    expect(canVerifyRecovery(pending, '123456', true, false)).toBe(false);
    expect(canVerifyRecovery(pending, '123456', false, true)).toBe(false);
  });
  it('derives expiry and lockout from server state, not demonstration values', () => {
    expect(recoveryView(pending, 'entry', false)).toBe('challenge');
    expect(recoveryView({ ...pending, expiresInSeconds: 0 }, 'wrong', false)).toBe('expired');
    expect(recoveryView({ ...pending, lockedForSeconds: 60 }, 'wrong', false)).toBe('locked');
    expect(recoveryView({ ...pending, attemptsLeft: 0 }, 'wrong', false)).toBe('locked');
    expect(recoveryView(pending, 'wrong', true)).toBe('neterr');
    expect(recoveryView({ ...pending, purpose: 'login' }, 'entry', false)).toBe('entry');
    // A reload with an unconsumed proof must offer reconciliation, not a new start.
    expect(recoveryView(verified, 'entry', false)).toBe('neterr');
  });
  it('retires the rejected-resend message only when the server grants resend', () => {
    expect(recoveryView({ ...pending, resendInSeconds: 0 }, 'cooldown', false)).toBe('cooldown');
    expect(recoveryView({ ...pending, resendAllowed: true }, 'cooldown', false)).toBe('challenge');
  });
  it('requires verified recovery before completing and retired state before success', async () => {
    const complete = vi.fn(async () => retired), current = () => true;
    await expect(runRecoveryCompletion(async () => verified, complete, current)).resolves.toEqual(retired);
    expect(complete).toHaveBeenCalledTimes(1);
    complete.mockClear();
    await expect(runRecoveryCompletion(async () => pending, complete, current)).rejects.toThrow('invalid_recovery_verification');
    expect(complete).not.toHaveBeenCalled();
    await expect(runRecoveryCompletion(async () => verified, async () => verified, current)).rejects.toThrow('invalid_recovery_completion');
  });
  it('does not dispatch completion or publish success after leaving S-06', async () => {
    const complete = vi.fn(async () => retired);
    await expect(runRecoveryCompletion(async () => verified, complete, () => false)).rejects.toThrow('recovery_abandoned');
    expect(complete).not.toHaveBeenCalled();
    let active = true;
    await expect(runRecoveryCompletion(async () => verified, async () => { active = false; return retired; }, () => active)).rejects.toThrow('recovery_abandoned');
  });
});
