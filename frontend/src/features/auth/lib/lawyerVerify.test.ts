import { describe, expect, it } from 'vitest';
import {
  validateLawyerProfile,
  EMPTY_LAWYER_PROFILE,
  createStubEnrolmentSource,
  runEnrolmentCheck,
  statusForLookup,
  recordManualOverride,
  canAccessLawyerFeatures,
  lawyerGateReason,
  lawyerConsentComplete,
  toLawyerAuditEvent,
  containsOutcomeClaim,
  BCI_PROFILE_DISPLAY_ENABLED,
  type VerificationRecord,
} from './lawyerVerify';

const NOW = '2026-07-11T00:00:00.000Z';

describe('lawyer verification (SAATHI-2 / P0.1)', () => {
  it('validates enrolment number format + required fields', () => {
    expect(Object.keys(validateLawyerProfile(EMPTY_LAWYER_PROFILE)).length).toBe(3);
    const ok = validateLawyerProfile({ fullName: 'A. Rao', enrolmentNumber: 'D/1234/2015', stateBarCouncil: 'Bar Council of Delhi' });
    expect(Object.keys(ok).length).toBe(0);
    const bad = validateLawyerProfile({ fullName: 'A. Rao', enrolmentNumber: '1234', stateBarCouncil: 'Bar Council of Delhi' });
    expect(bad.enrolmentNumber).toBeTruthy();
  });

  it('maps enrolment lookups to verification statuses', () => {
    expect(statusForLookup('active')).toBe('verified');
    expect(statusForLookup('not_found')).toBe('rejected');
    expect(statusForLookup('unavailable')).toBe('manual_review');
  });

  it('runs the stub enrolment check deterministically', () => {
    const src = createStubEnrolmentSource();
    const verified = runEnrolmentCheck({ fullName: 'A', enrolmentNumber: 'D/1234/2016', stateBarCouncil: 'X' }, src, NOW);
    expect(verified.status).toBe('verified');
    const rejected = runEnrolmentCheck({ fullName: 'A', enrolmentNumber: 'D/1235/2016', stateBarCouncil: 'X' }, src, NOW);
    expect(rejected.status).toBe('rejected');
    const manual = runEnrolmentCheck({ fullName: 'A', enrolmentNumber: 'D/0000/2016', stateBarCouncil: 'X' }, src, NOW);
    expect(manual.status).toBe('manual_review');
  });

  it('gates lawyer features until verified; automation cannot clear', () => {
    const rejected: VerificationRecord = { status: 'rejected', checker: 'system:enrolment', timestamp: NOW };
    expect(canAccessLawyerFeatures(rejected)).toBe(false);
    expect(canAccessLawyerFeatures(null)).toBe(false);
    // Unauthorised override does nothing.
    const noAuth = recordManualOverride(rejected, { authorised: false, reason: 'x', reviewer: 'bot' }, NOW);
    expect(noAuth.status).toBe('rejected');
    // Authorised override with no reason does nothing.
    const noReason = recordManualOverride(rejected, { authorised: true, reason: '   ', reviewer: 'admin:1' }, NOW);
    expect(noReason.status).toBe('rejected');
    // Authorised human override with a reason clears it.
    const cleared = recordManualOverride(rejected, { authorised: true, reason: 'Verified enrolment certificate manually', reviewer: 'admin:1' }, NOW);
    expect(cleared.status).toBe('verified');
    expect(canAccessLawyerFeatures(cleared)).toBe(true);
    expect(toLawyerAuditEvent(cleared).overrideReason).toContain('manually');
  });

  it('produces restricted-state reasons for the gate', () => {
    expect(lawyerGateReason({ status: 'verified', checker: 's', timestamp: NOW })).toBeNull();
    expect(lawyerGateReason({ status: 'manual_review', checker: 's', timestamp: NOW })).toContain('manual review');
    expect(lawyerGateReason(null)).toContain('locked');
  });

  it('keeps BCI profile display disabled by default (LCR-002)', () => {
    expect(BCI_PROFILE_DISPLAY_ENABLED).toBe(false);
  });

  it('flags outcome/competence claims and requires consent', () => {
    expect(containsOutcomeClaim('95% win rate, best lawyer in Delhi')).toBe(true);
    expect(containsOutcomeClaim('Civil litigation, enrolled 2015')).toBe(false);
    expect(lawyerConsentComplete({ acceptedTerms: true, acceptedPrivacy: true, timestamp: NOW })).toBe(true);
    expect(lawyerConsentComplete({ acceptedTerms: true, acceptedPrivacy: false, timestamp: NOW })).toBe(false);
  });
});
