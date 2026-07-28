import { describe, expect, it } from 'vitest';
import type { LawSchoolSummary } from '../lib/lawSchoolsApi';
import {
  lawSchoolDetailPath,
  schoolListMetaline,
  stableUniqueSchoolIds,
} from './SchoolScreens';

const school = (
  name: string,
  state: string,
  feesMin: number,
  feesMax: number,
): LawSchoolSummary => ({
  id: `${name}-id`,
  name,
  slug: name.toLowerCase().replace(/ /g, '-'),
  state,
  institutionType: 'national_law_university',
  accreditation: 'NAAC A',
  entranceExam: 'CLAT',
  feesMin,
  feesMax,
  nirfRank: 1,
});

describe('Option C+ frozen screen contracts', () => {
  it('deduplicates overlapping Saved/Followed IDs in stable first-seen order', () => {
    expect(stableUniqueSchoolIds(['nlsiu', 'gnlu', 'nlsiu', 'nlu-delhi', 'gnlu']))
      .toEqual(['nlsiu', 'gnlu', 'nlu-delhi']);
  });

  it('builds the S-28 View destination with the exact school ID and return context', () => {
    const path = lawSchoolDetailPath('school/id', 'state=Karnataka&page_size=6');
    const url = new URL(path, 'https://example.test');
    expect(url.pathname).toBe('/s-28');
    expect(url.searchParams.get('id')).toBe('school/id');
    expect(url.searchParams.get('ret')).toBe('state=Karnataka&page_size=6');
  });

  it.each([
    ['NLSIU', 'Karnataka', 285000, 320000, 'KARNATAKA · ₹2.9 L–₹3.2 L / YR (SAMPLE) · VERIFIED 1 JUL 2026'],
    ['GNLU', 'Gujarat', 230000, 270000, 'GUJARAT · ₹2.3 L–₹2.7 L / YR (SAMPLE) · VERIFIED 1 JUL 2026'],
    ['NLU Delhi', 'Delhi', 250000, 295000, 'DELHI · ₹2.5 L–₹3 L / YR (SAMPLE) · VERIFIED 1 JUL 2026'],
    ['NALSAR', 'Telangana', 260000, 300000, 'TELANGANA · ₹2.6 L–₹3 L / YR (SAMPLE) · VERIFIED 1 JUL 2026'],
  ])('renders the approved S-30 state metaline for %s', (name, state, min, max, expected) => {
    expect(schoolListMetaline(school(name, state, min, max))).toBe(expected);
  });
});
