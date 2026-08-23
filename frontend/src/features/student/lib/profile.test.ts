import { describe, expect, it } from 'vitest';
import {
  EMPTY_PROFILE,
  validateStep,
  INSTITUTIONAL_EMAIL_RE,
  INSTITUTIONAL_EMAIL_MAX_LENGTH,
  institutionalEmailError,
  ENROLMENT_RE,
  type ProfileDraft,
} from './profile';

function completeDraft(): ProfileDraft {
  return {
    ...EMPTY_PROFILE,
    fullName: 'Aditi Nair',
    preferredLanguage: 'English',
    dateOfBirth: '2004-03-14',
    college: 'NLSIU',
    yearOfStudy: '4th year',
    enrolmentNumber: 'KA/1234/2023',
    institutionalEmail: 'aditi.nair@nls.ac.in',
    interests: ['Constitutional'],
    careerGoal: 'Litigation & judiciary',
  };
}

describe('profile validation + completeness (SAATHI-55)', () => {
  it('validates institutional email and enrolment format', () => {
    expect(INSTITUTIONAL_EMAIL_RE.test('aditi@nlsiu')).toBe(false);
    expect(INSTITUTIONAL_EMAIL_RE.test('aditi.nair@nls.ac.in')).toBe(true);
    expect(ENROLMENT_RE.test('1234')).toBe(false);
    expect(ENROLMENT_RE.test('KA/1234/2023')).toBe(true);
  });

  it('rejects the exact S-15 empty, malformed and over-length boundaries', () => {
    const suffix = '@nls.ac.in';
    const atLimit = `${'a'.repeat(INSTITUTIONAL_EMAIL_MAX_LENGTH - suffix.length)}${suffix}`;
    expect(institutionalEmailError('')).toBeTruthy();
    expect(institutionalEmailError('not-an-email')).toBeTruthy();
    expect(institutionalEmailError('student@gmail.com')).toContain('institutional email');
    expect(institutionalEmailError(atLimit)).toBeUndefined();
    expect(institutionalEmailError(`a${atLimit}`)).toContain('254 characters or fewer');
    expect(institutionalEmailError('aditi.nair@nls.ac.in')).toBeUndefined();
  });

  it('rejects a future profile date of birth', () => {
    const d = completeDraft();
    d.dateOfBirth = '2027-01-01';
    expect(validateStep(1, d).dateOfBirth).toContain('not in the future');
  });

  it('validates each draft section without deriving server routing', () => {
    const d = { ...EMPTY_PROFILE, interests: [] };
    expect(validateStep(1, d)).toMatchObject({ fullName: expect.any(String), dateOfBirth: expect.any(String) });
    d.fullName = 'Aditi Nair';
    d.dateOfBirth = '2004-03-14';
    d.preferredLanguage = 'English';
    expect(validateStep(1, d)).toEqual({});
  });

  it('treats the optional Bar number as never required', () => {
    const d = completeDraft();
    d.barEnrolmentNumber = '';
    expect(Object.keys(validateStep(2, d))).toHaveLength(0);
  });

  it('validates preferences without awarding a client-side tier', () => {
    const d = completeDraft();
    expect(validateStep(3, d)).toEqual({});
    expect(validateStep(3, { ...d, interests: [], careerGoal: '' })).toMatchObject({
      interests: expect.any(String),
      careerGoal: expect.any(String),
    });
  });
});
