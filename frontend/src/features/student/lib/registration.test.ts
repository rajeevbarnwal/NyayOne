/**
 * SAATHI-388 / SAATHI-421 — shared registration validation contract tests.
 */
import { describe, it, expect } from 'vitest';
import {
  isValidMobile, MOBILE_ERROR,
  isRegistrableDob, todayLocalISO,
  validateNamePart, validateNameParts, nameErrorMessage, namePartsToPayload, composeDisplayName, fullNameToParts,
  NAME_MAX,
} from './registration';

const CLOCK = new Date('2026-07-26T09:00:00.000+05:30'); // local 2026 test clock

describe('mobile — exactly 10 digits (PO defect 1)', () => {
  it('accepts exactly 10 digits incl. leading zero', () => {
    expect(isValidMobile('9876543210')).toBe(true);
    expect(isValidMobile('0123456789')).toBe(true);
  });
  it('rejects empty / 9 / 11 / 12 digits', () => {
    expect(isValidMobile('')).toBe(false);
    expect(isValidMobile('987654321')).toBe(false);
    expect(isValidMobile('98765432101')).toBe(false);
    expect(isValidMobile('987654321012')).toBe(false);
  });
  it('rejects letters, punctuation, spaces, +91, decimals, sci-notation (no strip-and-accept)', () => {
    for (const bad of ['98765abc10', '98765-43210', '987 654 3210', '+919876543210', '9876543210.0', '9.87654e9', ' 9876543210']) {
      expect(isValidMobile(bad)).toBe(false);
    }
    expect(MOBILE_ERROR).toBe('Mobile number must be exactly 10 digits.');
  });
});

describe('date of birth — real + not future (PO defect 2)', () => {
  it('accepts a real past date', () => {
    expect(isRegistrableDob('2004-03-14', CLOCK)).toBe(true);
    expect(isRegistrableDob(todayLocalISO(CLOCK), CLOCK)).toBe(true); // today allowed
  });
  it('rejects impossible calendar dates', () => {
    expect(isRegistrableDob('2026-02-31', CLOCK)).toBe(false);
    expect(isRegistrableDob('2026-13-01', CLOCK)).toBe(false);
  });
  it('rejects future dates under the 2026 clock', () => {
    expect(isRegistrableDob('2030-01-01', CLOCK)).toBe(false);
    expect(isRegistrableDob('2030-12-31', CLOCK)).toBe(false);
    expect(isRegistrableDob('2026-07-27', CLOCK)).toBe(false); // tomorrow
  });
  it('rejects malformed input', () => {
    expect(isRegistrableDob('', CLOCK)).toBe(false);
    expect(isRegistrableDob('14-03-2004', CLOCK)).toBe(false);
  });
});

describe('split legal name (PO decision: First required, Middle optional, Last required)', () => {
  it('requires first and last, middle optional', () => {
    expect(validateNamePart('Aditi', { required: true })).toBeNull();
    expect(validateNamePart('', { required: true })).toBe('required');
    expect(validateNamePart('', { required: false })).toBeNull();
    const e = validateNameParts({ firstName: '', middleName: '', lastName: '' });
    expect(e.firstName).toBe('required');
    expect(e.lastName).toBe('required');
    expect(e.middleName).toBeUndefined();
  });
  it('accepts Unicode letters, marks, hyphen, apostrophe, period, internal space', () => {
    for (const ok of ['Aditi', 'D’Souza', "O'Brien", 'Jean-Luc', 'A. R.', 'राज', 'Nguyễn', 'van der Berg']) {
      expect(validateNamePart(ok, { required: true })).toBeNull();
    }
  });
  it('rejects digit/markup/control/symbol-only names', () => {
    for (const bad of ['12345', '<script>', '###', '42a']) {
      expect(validateNamePart(bad, { required: true })).toBe('invalid');
    }
  });
  it('enforces max and max+1 boundaries', () => {
    expect(validateNamePart('a'.repeat(NAME_MAX), { required: true })).toBeNull();
    expect(validateNamePart('a'.repeat(NAME_MAX + 1), { required: true })).toBe('too_long');
  });
  it('produces field-specific messages', () => {
    expect(nameErrorMessage('firstName', 'required')).toBe('Enter your first name.');
    expect(nameErrorMessage('lastName', 'too_long')).toBe(`Last name must be ${NAME_MAX} characters or fewer.`);
    expect(nameErrorMessage('firstName', 'invalid')).toContain("aren't allowed");
  });
});

describe('name → payload + display, and legacy compatibility', () => {
  it('maps First/Middle/Last with middle present', () => {
    const p = namePartsToPayload({ firstName: ' Aditi ', middleName: ' Rani ', lastName: ' Nair ' });
    expect(p).toEqual({ firstName: 'Aditi', middleName: 'Rani', lastName: 'Nair' });
    expect(composeDisplayName({ firstName: 'Aditi', middleName: 'Rani', lastName: 'Nair' })).toBe('Aditi Rani Nair');
  });
  it('middle absent → null and no double spaces', () => {
    const p = namePartsToPayload({ firstName: 'Aditi', middleName: '', lastName: 'Nair' });
    expect(p.middleName).toBeNull();
    expect(composeDisplayName({ firstName: 'Aditi', middleName: '', lastName: 'Nair' })).toBe('Aditi Nair');
    expect(composeDisplayName({ firstName: 'Aditi', middleName: '  ', lastName: 'Nair' })).not.toContain('  ');
  });
  it('migrates a legacy fullName-only record without stranding the user', () => {
    expect(fullNameToParts('Aditi Nair')).toEqual({ firstName: 'Aditi', middleName: '', lastName: 'Nair' });
    expect(fullNameToParts('Aditi Rani Kumari Nair')).toEqual({ firstName: 'Aditi', middleName: 'Rani Kumari', lastName: 'Nair' });
    expect(fullNameToParts('Prince')).toEqual({ firstName: 'Prince', middleName: '', lastName: '' });
    expect(fullNameToParts('')).toEqual({ firstName: '', middleName: '', lastName: '' });
  });
});
