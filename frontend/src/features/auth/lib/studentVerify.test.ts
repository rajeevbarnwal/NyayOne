import { describe, expect, it } from 'vitest';
import {
  isInstitutionalEmail,
  validateStudentVerify,
  EMPTY_STUDENT_VERIFY,
  decideStudentVerification,
  minorContextFromDob,
  accountValid,
  proFeaturesUnlocked,
  studentGateReason,
  toStudentAuditEvent,
  MINOR_RULES_MODE,
  type AccountState,
} from './studentVerify';
import type { GuardianConsent } from '../../student/lib/consent';

const NOW = '2026-07-11T00:00:00.000Z';

describe('student institutional verification (SAATHI-3 / P0.2)', () => {
  it('recognises institutional emails', () => {
    expect(isInstitutionalEmail('a@nls.ac.in')).toBe(true);
    expect(isInstitutionalEmail('b@student.edu')).toBe(true);
    expect(isInstitutionalEmail('c@gmail.com')).toBe(false);
  });

  it('validates the two verification methods', () => {
    expect(validateStudentVerify(EMPTY_STUDENT_VERIFY).institutionalEmail).toBeTruthy();
    expect(Object.keys(validateStudentVerify({ ...EMPTY_STUDENT_VERIFY, institutionalEmail: 'a@nls.ac.in' })).length).toBe(0);
    const idErrors = validateStudentVerify({ method: 'college_id', institutionalEmail: '', collegeName: '', idDocumentRef: '' });
    expect(idErrors.collegeName).toBeTruthy();
    expect(idErrors.idDocumentRef).toBeTruthy();
  });

  it('prefers institutional email; routes college-ID fallback to manual_review', () => {
    const emailV = decideStudentVerification({ ...EMPTY_STUDENT_VERIFY, institutionalEmail: 'a@nls.ac.in' }, NOW);
    expect(emailV.status).toBe('verified');
    const idV = decideStudentVerification({ method: 'college_id', institutionalEmail: '', collegeName: 'NLS', idDocumentRef: 'blob:opaque' }, NOW);
    expect(idV.status).toBe('manual_review');
    const badEmail = decideStudentVerification({ ...EMPTY_STUDENT_VERIFY, institutionalEmail: 'a@gmail.com' }, NOW);
    expect(badEmail.status).toBe('rejected');
  });

  it('gates Pro features on a valid account and applies conservative minor default', () => {
    expect(MINOR_RULES_MODE).toBe('conservative');
    const verified = decideStudentVerification({ ...EMPTY_STUDENT_VERIFY, institutionalEmail: 'a@nls.ac.in' }, NOW);

    // Adult verified → valid → Pro unlocked.
    const adult: AccountState = { verification: verified, minor: minorContextFromDob('2000-01-01', NOW) };
    expect(accountValid(adult)).toBe(true);
    expect(proFeaturesUnlocked(adult)).toBe(true);
    expect(studentGateReason(adult)).toBeNull();

    // Minor verified but no guardian consent → NOT valid (conservative default).
    const minorNoConsent: AccountState = { verification: verified, minor: minorContextFromDob('2012-01-01', NOW) };
    expect(accountValid(minorNoConsent)).toBe(false);
    expect(proFeaturesUnlocked(minorNoConsent)).toBe(false);
    expect(studentGateReason(minorNoConsent)).toContain('Guardian consent');

    // Minor with verified guardian consent → valid.
    const gc: GuardianConsent = { guardianName: 'P', relationship: 'parent', consentVersion: 'dpdp-2023.v1', channel: 'email', timestamp: NOW, verificationStatus: 'verified', withdrawn: false };
    const minorConsented: AccountState = { verification: verified, minor: minorContextFromDob('2012-01-01', NOW, gc) };
    expect(accountValid(minorConsented)).toBe(true);
  });

  it('manual_review + rejected accounts do not unlock Pro', () => {
    const idV = decideStudentVerification({ method: 'college_id', institutionalEmail: '', collegeName: 'NLS', idDocumentRef: 'blob:x' }, NOW);
    const st: AccountState = { verification: idV, minor: minorContextFromDob('2000-01-01', NOW) };
    expect(proFeaturesUnlocked(st)).toBe(false);
    expect(studentGateReason(st)).toContain('manual review');
    expect(toStudentAuditEvent(idV, false).status).toBe('manual_review');
  });
});
