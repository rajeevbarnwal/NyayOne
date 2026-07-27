/** D1/D2 remediation — RAW API wire values, not pre-normalized UI fixtures. */
import { describe, expect, it } from 'vitest';
import {
  COLLEGE_OPTIONS, LANGUAGE_OPTIONS, YEAR_OPTIONS,
  labelFor, toCanonicalCollege, toCanonicalYear,
} from './catalog';

describe('catalog wire values (D1/D2)', () => {
  it('college options use canonical server values, labels separate', () => {
    const nlsiu = COLLEGE_OPTIONS[0];
    expect(nlsiu.value).toBe('National Law School of India University'); // raw wire value
    expect(nlsiu.label).toBe('National Law School of India University (NLSIU)');
    // No option uses its display label as the wire value where they differ.
    expect(COLLEGE_OPTIONS.some((o) => o.value.includes('(NLSIU)'))).toBe(false);
  });

  it('raw server college/year values hydrate to an existing option (D1)', () => {
    // Values exactly as returned by GET /student/profile for the QA seed user.
    expect(COLLEGE_OPTIONS.some((o) => o.value === toCanonicalCollege('National Law School of India University'))).toBe(true);
    expect(YEAR_OPTIONS.some((o) => o.value === toCanonicalYear('3rd'))).toBe(true);
  });

  it('legacy stored values map safely onto canonical codes', () => {
    expect(toCanonicalCollege('NLSIU')).toBe('National Law School of India University');
    expect(toCanonicalCollege('National Law School of India University (NLSIU)')).toBe('National Law School of India University');
    expect(toCanonicalYear('3rd year')).toBe('3rd');
    expect(toCanonicalYear('4th year · B.A. LL.B. (Hons.)')).toBe('4th');
    expect(toCanonicalYear('LL.M.')).toBe('llm');
  });

  it('language options use en/hi wire codes with display labels (D2)', () => {
    expect(LANGUAGE_OPTIONS.map((o) => o.value)).toEqual(['en', 'hi']);
    expect(labelFor(LANGUAGE_OPTIONS, 'en')).toBe('English');
    expect(labelFor(LANGUAGE_OPTIONS, 'hi')).toBe('हिन्दी (Hindi)');
    // A raw backend default of 'en' selects an existing option — no 'Select…'.
    expect(LANGUAGE_OPTIONS.some((o) => o.value === 'en')).toBe(true);
  });

  it('unknown values pass through (never silently swapped)', () => {
    expect(toCanonicalCollege('Somewhere Else')).toBe('Somewhere Else');
    expect(labelFor(COLLEGE_OPTIONS, 'Somewhere Else')).toBe('Somewhere Else');
  });
});
