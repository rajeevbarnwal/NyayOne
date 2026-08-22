import { describe, expect, it } from 'vitest';
import {
  nextPhase, redactChallenge, snapshotHasNoSecret, AUTH_PHASE_LABELS,
  type AuthSnapshot,
} from './authLifecycle';
import { createChallenge } from '../../student/lib/otp';
import { saveAuthSnapshot, loadAuthSnapshot } from './authPersistence';
import { InMemoryKvStore } from '../../../lib/kvStore';

describe('auth lifecycle reducer (SAATHI-2/3 remediation)', () => {
  it('sequences the full lifecycle happy path', () => {
    let p = nextPhase('entry', 'select_role');
    expect(p).toBe('register');
    p = nextPhase(p, 'submit_registration'); expect(p).toBe('otp_sent');
    p = nextPhase(p, 'begin_otp_entry'); expect(p).toBe('otp_entry');
    p = nextPhase(p, 'otp_verified'); expect(p).toBe('consent');
    p = nextPhase(p, 'give_consent'); expect(p).toBe('details');
    p = nextPhase(p, 'result_verified'); expect(p).toBe('verified');
  });

  it('routes to manual_review and rejected with retry', () => {
    expect(nextPhase('details', 'result_manual')).toBe('manual_review');
    expect(nextPhase('details', 'result_rejected')).toBe('rejected');
    expect(nextPhase('rejected', 'retry')).toBe('details');
    expect(nextPhase('manual_review', 'result_verified')).toBe('verified');
  });

  it('otp retry returns to otp_sent (resend) and reset returns to entry', () => {
    expect(nextPhase('otp_entry', 'retry')).toBe('otp_sent');
    expect(nextPhase('pending', 'reset')).toBe('entry');
  });

  it('ignores illegal (phase,event) pairs', () => {
    expect(nextPhase('entry', 'otp_verified')).toBe('entry');
    expect(nextPhase('verified', 'retry')).toBe('verified');
    expect(AUTH_PHASE_LABELS.manual_review).toBe('Manual review');
  });

  it('redacts the OTP code and keeps snapshots secret-free', () => {
    const ch = createChallenge('429016', 1000);
    const red = redactChallenge(ch);
    expect((red as Record<string, unknown>).code).toBeUndefined();
    expect(red.expiresAt).toBe(ch.expiresAt);
    const snap: AuthSnapshot = { role: 'lawyer', phase: 'otp_entry', destinationMasked: '+91 98••• ••210', challenge: red, consentAt: null, updatedAt: 1000 };
    expect(snapshotHasNoSecret(snap)).toBe(true);
    // A snapshot that accidentally carried the code would be rejected.
    const bad = { ...snap, challenge: { ...red, code: '429016' } } as unknown as AuthSnapshot;
    expect(snapshotHasNoSecret(bad)).toBe(false);
  });

  it('rejects and erases the retired student OTP snapshot', () => {
    const store = new InMemoryKvStore();
    const ch = createChallenge('429016', 1000);
    const snap: AuthSnapshot = { role: 'student', phase: 'otp_entry', destinationMasked: 'aa•••@nls.ac.in', challenge: redactChallenge(ch), consentAt: null, updatedAt: 1000 };
    saveAuthSnapshot(snap, store);
    expect(loadAuthSnapshot('student', store)).toBeNull();

    // A stale pre-NYAY-4 value planted directly in storage is deleted on read.
    store.set('ls-auth-student', snap);
    expect(loadAuthSnapshot('student', store)).toBeNull();
    expect(store.get('ls-auth-student')).toBeNull();
  });
});
