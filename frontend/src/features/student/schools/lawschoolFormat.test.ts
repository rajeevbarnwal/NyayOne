/**
 * SAATHI-118 (F2) — shared law-school formatter + approved 13-row S-29 schema.
 * The same module drives the developed UI, the fixture contract projection and
 * the reference generator; these tests freeze order, labels and formatting.
 */
import { describe, it, expect } from 'vitest';
import {
  COMPARE_ROWS,
  FACT_LABELS,
  INSTITUTION_TYPE_LABELS,
  compareRowValue,
  feesInrBand,
  feesLakhBand,
  inrAmount,
  lakhAmount,
  nirfText,
  programmesText,
  verifiedText,
  referenceSourceFoot,
  type CompareFormatInput,
} from './lawschoolFormat.mjs';

const APPROVED_ORDER = [
  'State', 'Institution type', 'Accreditation', 'Entrance exam', 'Fees',
  'NIRF rank', 'Programmes', 'Established', 'Location', 'Intake', 'Hostel',
  'Legal aid clinics', 'Moot teams',
];

describe('approved 13-row S-29 schema', () => {
  it('has exactly 13 rows in the approved order with approved labels', () => {
    expect(COMPARE_ROWS).toHaveLength(13);
    expect(COMPARE_ROWS.map((r) => r.label)).toEqual(APPROVED_ORDER);
  });

  it('keeps the six fact keys aligned with the backend seed keys', () => {
    expect(COMPARE_ROWS.slice(7).map((r) => r.key)).toEqual(
      ['established', 'location', 'intake', 'hostel', 'legal_aid_clinics', 'moot_teams'],
    );
    for (const { key, label } of COMPARE_ROWS.slice(7)) {
      expect(FACT_LABELS[key]).toBe(label);
    }
  });

  it('formats every row value deterministically (NLSIU sample)', () => {
    const nlsiu: CompareFormatInput = {
      state: 'Karnataka',
      institutionType: 'national_law_university',
      accreditation: 'NAAC A++',
      entranceExam: 'CLAT',
      feesMin: 285000,
      feesMax: 320000,
      nirfRank: 1,
      programmes: [
        { degree: 'BA LLB (Hons)', durationYears: 5 },
        { degree: 'LLM', durationYears: 1 },
      ],
      facts: {
        established: '1987 (sample)',
        location: 'Bengaluru, Karnataka (sample)',
        intake: '120 seats (sample)',
        hostel: 'Available (sample)',
        legal_aid_clinics: '8 clinics (sample)',
        moot_teams: '12 teams (sample)',
      },
    };
    expect(COMPARE_ROWS.map((r) => compareRowValue(r.key, nlsiu))).toEqual([
      'Karnataka',
      'National Law University · state-established',
      'NAAC A++',
      'CLAT',
      '₹2,85,000–₹3,20,000/yr',
      '#1',
      'BA LLB (Hons) (5 yrs) · LLM (1 yrs)',
      '1987 (sample)',
      'Bengaluru, Karnataka (sample)',
      '120 seats (sample)',
      'Available (sample)',
      '8 clinics (sample)',
      '12 teams (sample)',
    ]);
  });
});

describe('currency formatting (reference LSKIT parity)', () => {
  it('formats lakh amounts exactly like the reference lakh()', () => {
    expect(lakhAmount(285000)).toBe('₹2.9 L');
    expect(lakhAmount(320000)).toBe('₹3.2 L');
    expect(lakhAmount(200000)).toBe('₹2 L');
    expect(lakhAmount(15000)).toBe('₹0.1 L'); // 0.15 rounds down in IEEE-754, same as the reference
    expect(lakhAmount(700000)).toBe('₹7 L');
  });

  it('formats the reference fee() lakh band (S-27 cards, S-30 metaline)', () => {
    expect(feesLakhBand(285000, 320000)).toBe('₹2.9 L–₹3.2 L / yr');
    expect(feesLakhBand(12000, 20000)).toBe('₹0.1 L–₹0.2 L / yr');
  });

  it('formats INR-raw amounts with deterministic en-IN grouping', () => {
    expect(inrAmount(285000)).toBe('₹2,85,000');
    expect(inrAmount(15000)).toBe('₹15,000');
    expect(inrAmount(700)).toBe('₹700');
    expect(inrAmount(1234567)).toBe('₹12,34,567');
  });

  it('formats the INR-raw band (S-28 fee band, S-29 Fees row)', () => {
    expect(feesInrBand(285000, 320000)).toBe('₹2,85,000–₹3,20,000/yr');
  });
});

describe('labels and freshness copy', () => {
  it('maps institution types to reference display labels', () => {
    expect(INSTITUTION_TYPE_LABELS.national_law_university).toBe('National Law University · state-established');
    expect(compareRowValue('institution_type', { institutionType: 'deemed' } as CompareFormatInput)).toBe('Deemed university');
  });

  it('formats NIRF and programmes deterministically', () => {
    expect(nirfText(3)).toBe('#3');
    expect(nirfText(null)).toBe('Not ranked');
    expect(programmesText([])).toBe('Not listed');
    expect(programmesText([{ degree: 'LLB', durationYears: 3 }])).toBe('LLB (3 yrs)');
  });

  it('renders the reference verified/freshness copy (TZ-independent)', () => {
    expect(verifiedText()).toBe('Verified 1 Jul 2026');
    expect(verifiedText('2026-12-31')).toBe('Verified 31 Dec 2026');
    expect(referenceSourceFoot()).toBe(
      'Source: institution website · sample verification 1 Jul 2026 · prototype data, not production facts',
    );
  });
});
