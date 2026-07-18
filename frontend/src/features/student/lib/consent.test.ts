import { describe, expect, it } from 'vitest';
import {
  computeAge,
  isMinor,
  guardianConsentRequired,
  guardianConsentSatisfied,
  capabilityAllowed,
  onboardingGate,
  registrationConsentComplete,
  isValidDateOfBirth,
  type GuardianConsent,
} from './consent';

const gc: GuardianConsent = {
  guardianName: 'R. Nair',
  relationship: 'parent',
  consentVersion: 'v1',
  channel: 'app',
  timestamp: '2026-07-07',
  verificationStatus: 'verified',
  withdrawn: false,
};

describe('age gate + guardian consent (SAATHI-53/58)', () => {
  it('computes age and minor status', () => {
    expect(computeAge('2004-03-14', '2026-07-07')).toBe(22);
    expect(computeAge('2010-12-01', '2026-07-07')).toBe(15);
    expect(isMinor('2010-12-01', '2026-07-07')).toBe(true);
    expect(isMinor('2004-03-14', '2026-07-07')).toBe(false);
  });

  it('rejects future and impossible dates of birth', () => {
    expect(isValidDateOfBirth('2004-03-14', '2026-07-07T00:00:00.000Z')).toBe(true);
    expect(isValidDateOfBirth('2027-01-01', '2026-07-07T00:00:00.000Z')).toBe(false);
    expect(isValidDateOfBirth('2026-02-31', '2026-07-07T00:00:00.000Z')).toBe(false);
  });

  it('requires and evaluates guardian consent for minors', () => {
    expect(guardianConsentRequired('2010-12-01', '2026-07-07')).toBe(true);
    expect(guardianConsentSatisfied(gc)).toBe(true);
    expect(guardianConsentSatisfied({ ...gc, withdrawn: true })).toBe(false);
    expect(guardianConsentSatisfied({ ...gc, verificationStatus: 'pending' })).toBe(false);
    expect(guardianConsentSatisfied(null)).toBe(false);
  });

  it('blocks restricted capabilities for minors until consent clears', () => {
    expect(capabilityAllowed('ai_research', { isMinor: true })).toBe(false);
    expect(capabilityAllowed('ai_research', { isMinor: true, guardianConsent: gc })).toBe(true);
    expect(capabilityAllowed('ai_research', { isMinor: false })).toBe(true);
  });

  it('derives the onboarding gate', () => {
    expect(onboardingGate({ isMinor: true })).toBe('guardian_consent_pending');
    expect(onboardingGate({ isMinor: true, guardianConsent: gc })).toBe('ok');
    expect(onboardingGate({ isMinor: false })).toBe('ok');
  });

  it('requires all mandatory registration consents', () => {
    const base = { version: 'v', acceptedTerms: true, acceptedPrivacy: true, lawStudentDeclared: true, timestamp: 't' };
    expect(registrationConsentComplete(base)).toBe(true);
    expect(registrationConsentComplete({ ...base, acceptedPrivacy: false })).toBe(false);
    expect(registrationConsentComplete({ ...base, lawStudentDeclared: false })).toBe(false);
  });
});
