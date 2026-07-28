/**
 * SAATHI-118 (F2) — shared law-school formatter + approved 13-row S-29 schema.
 * The same module drives the developed UI, the fixture contract projection and
 * the reference generator; these tests freeze order, labels and formatting.
 */
import { describe, it, expect } from 'vitest';
import {
  APPROVED_SHORT_HANDLES,
  COMPARE_ROWS,
  FACT_LABELS,
  INSTITUTION_TYPE_LABELS,
  REGIONS,
  REGION_STATES,
  S28_FACT_KEY_ORDER,
  compareRowValue,
  factSourceLine,
  monogramText,
  regionOfState,
  shortHandle,
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

/* ------------------- Option C+ reference-owned taxonomy ------------------- */

describe('S-28 essentials literal order (independent of FACT_SEMANTIC_ORDER)', () => {
  it('freezes the six-key order literally', () => {
    // Written out verbatim on purpose: a backend ordering regression must FAIL
    // here rather than be mirrored through a shared constant.
    expect([...S28_FACT_KEY_ORDER]).toEqual(
      ['established', 'location', 'intake', 'hostel', 'legal_aid_clinics', 'moot_teams'],
    );
  });

  it('labels every literal key with the approved display label', () => {
    expect(S28_FACT_KEY_ORDER.map((k) => FACT_LABELS[k])).toEqual(
      ['Established', 'Location', 'Intake', 'Hostel', 'Legal aid clinics', 'Moot teams'],
    );
  });

  it('renders the frozen-fixture source row wording from a real retrieved_at', () => {
    expect(factSourceLine('2026-07-01T05:30:00+05:30')).toBe(
      'Source: institution website · sample verification 1 Jul 2026 · prototype data, not production facts',
    );
    expect(factSourceLine(null)).toBe(referenceSourceFoot());
  });
});

describe('approved short handles and monograms (reference SEED shorts)', () => {
  it('maps all 12 catalogue names to the approved shorts', () => {
    expect(APPROVED_SHORT_HANDLES).toEqual({
      'National Law School of India University': 'NLSIU',
      'NALSAR University of Law': 'NALSAR',
      'The West Bengal National University of Juridical Sciences': 'WBNUJS',
      'National Law University, Delhi': 'NLU Delhi',
      'Gujarat National Law University': 'GNLU',
      'Symbiosis Law School, Pune': 'SLS Pune',
      'Jindal Global Law School': 'JGLS',
      'Government Law College, Mumbai': 'GLC Mumbai',
      'Faculty of Law, University of Delhi': 'DU Law',
      'ILS Law College, Pune': 'ILS Pune',
      'Christ University School of Law': 'Christ Law',
      'Rajiv Gandhi National University of Law': 'RGNUL',
    });
  });

  it('derives reference monograms from the approved short, not word initials', () => {
    expect(monogramText('NALSAR University of Law')).toBe('NA'); // not 'NU'
    expect(monogramText('Christ University School of Law')).toBe('CL'); // not 'CU'
    expect(monogramText('Faculty of Law, University of Delhi')).toBe('DU'); // not 'FO'
    expect(monogramText('National Law School of India University')).toBe('NL');
  });

  it('falls back deterministically for names outside the approved map', () => {
    expect(shortHandle('Some New College of Law')).toBe('SNCL');
  });
});

describe('reference region taxonomy (S-27 Where? chips)', () => {
  it('offers the five reference regions', () => {
    expect([...REGIONS]).toEqual(['North', 'South', 'East', 'West', 'Central']);
  });

  it('assigns every catalogue state to its frozen-fixture region', () => {
    expect(regionOfState('Karnataka')).toBe('South');
    expect(regionOfState('Telangana')).toBe('South');
    expect(regionOfState('West Bengal')).toBe('East');
    expect(regionOfState('Delhi')).toBe('North');
    expect(regionOfState('Haryana')).toBe('North');
    expect(regionOfState('Punjab')).toBe('North');
    expect(regionOfState('Gujarat')).toBe('West');
    expect(regionOfState('Maharashtra')).toBe('West');
  });

  it('never maps one state to two regions', () => {
    const all = REGIONS.flatMap((r) => [...REGION_STATES[r]]);
    expect(new Set(all).size).toBe(all.length);
  });
});
