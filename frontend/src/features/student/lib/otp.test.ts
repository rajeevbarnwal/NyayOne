import { describe, expect, it } from 'vitest';
import {
  createChallenge,
  verify,
  isValidOtpFormat,
  isExpired,
  secondsUntilResend,
  canResend,
  maskDestination,
  createStubOtpSender,
  OTP_TTL_MS,
  OTP_LOCK_MS,
} from './otp';

describe('OTP state machine (SAATHI-53)', () => {
  const t0 = 1_000_000;

  it('validates 6-digit format', () => {
    expect(isValidOtpFormat('429016')).toBe(true);
    expect(isValidOtpFormat('42901')).toBe(false);
    expect(isValidOtpFormat('42901a')).toBe(false);
  });

  it('verifies the correct code', () => {
    const ch = createChallenge('429016', t0);
    expect(verify(ch, '429016', t0).status).toBe('verified');
  });

  it('decrements attempts then locks after 3 wrong tries', () => {
    const ch = createChallenge('429016', t0);
    let r = verify(ch, '000000', t0);
    expect(r.status).toBe('incorrect');
    expect(r.challenge.attemptsLeft).toBe(2);
    r = verify(r.challenge, '000000', t0);
    expect(r.challenge.attemptsLeft).toBe(1);
    r = verify(r.challenge, '000000', t0);
    expect(r.status).toBe('locked');
    expect(r.challenge.lockedUntil).toBe(t0 + OTP_LOCK_MS);
    // Locked stays locked even with the right code.
    expect(verify(r.challenge, '429016', t0).status).toBe('locked');
  });

  it('reports expiry after the TTL', () => {
    const ch = createChallenge('429016', t0);
    expect(isExpired(ch, t0 + OTP_TTL_MS)).toBe(true);
    expect(verify(ch, '429016', t0 + OTP_TTL_MS).status).toBe('expired');
  });

  it('gates resend by cooldown', () => {
    const ch = createChallenge('429016', t0);
    expect(secondsUntilResend(ch, t0)).toBe(30);
    expect(canResend(ch, t0)).toBe(false);
    expect(canResend(ch, t0 + 30_000)).toBe(true);
  });

  it('masks destinations and never sends over the network (stub)', () => {
    expect(maskDestination({ channel: 'sms', ref: '+919812345210' })).toBe('+91 ••••• ••210');
    expect(maskDestination({ channel: 'sms', ref: '9000000042' })).toBe('+91 ••••• ••042');
    expect(maskDestination({ channel: 'sms', ref: '9000000042' })).not.toContain('98');
    const sender = createStubOtpSender();
    const receipt = sender.send({ channel: 'sms', ref: 'x' }, '429016', t0);
    expect(receipt.challengeId).toMatch(/^stub-/);
  });
});
