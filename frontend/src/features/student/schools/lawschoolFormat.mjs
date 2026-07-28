/**
 * SAATHI-118/120/121 (F2/F4) — SHARED deterministic law-school formatting.
 *
 * SINGLE SOURCE for every user-visible formatted value the Option C+ visual
 * oracle compares on S-27..S-30. Consumed by:
 *   - the developed UI  (src/features/student/schools/SchoolScreens.tsx),
 *   - the fixture contract projection (scripts/lawschool_fixture_contract.mjs),
 *   - the reference generator (scripts/generate-lawschool-reference-fixture.mjs).
 * Formats mirror the approved reference frame byte-for-byte (LSKIT lakh/fee/
 * fmtDate). Plain ESM (no TS syntax) so Node scripts can import it directly;
 * types live in lawschoolFormat.d.mts.
 */

/** Contract-pinned sample verification date (mirrors
 * scripts/lawschool_fixture_contract.json verifiedDate — sync is asserted by
 * scripts/lawschool_fixture_contract.test.mjs). */
export const REFERENCE_VERIFIED_DATE = '2026-07-01';

/* ------------------------------ currency ---------------------------------- */

/** en-IN digit grouping without locale dependency (deterministic on every
 * Node/browser ICU build): last 3 digits, then groups of 2. */
export function inrAmount(n) {
  const s = String(Math.trunc(Math.abs(n)));
  if (s.length <= 3) return `₹${s}`;
  const head = s.slice(0, -3);
  const groups = [];
  for (let i = head.length; i > 0; i -= 2) groups.unshift(head.slice(Math.max(0, i - 2), i));
  return `₹${groups.join(',')},${s.slice(-3)}`;
}

/** INR-raw fee band (reference r28 "Fee band" / r29 "Fees" row). */
export function feesInrBand(feesMin, feesMax) {
  return `${inrAmount(feesMin)}–${inrAmount(feesMax)}/yr`;
}

/** Reference LSKIT lakh(): '₹'+(n/100000).toFixed(1).replace(/\.0$/,'')+' L' */
export function lakhAmount(n) {
  return `₹${(n / 100000).toFixed(1).replace(/\.0$/, '')} L`;
}

/** Reference LSKIT fee(): lakh band with ' / yr' — used by the reference S-27
 * result cards ("Costs about …") and S-30 card metalines. */
export function feesLakhBand(feesMin, feesMax) {
  return `${lakhAmount(feesMin)}–${lakhAmount(feesMax)} / yr`;
}

/* ------------------------------ labels ------------------------------------ */

/** Reference TYPE_LABELS (display labels; wire values stay canonical). */
export const INSTITUTION_TYPE_LABELS = {
  national_law_university: 'National Law University · state-established',
  deemed: 'Deemed university',
  private: 'Private university',
  government: 'Government law college',
};

export function institutionTypeLabel(t) {
  return INSTITUTION_TYPE_LABELS[t] ?? t;
}

/** Approved display labels for the six 0006-backfilled fact rows. */
export const FACT_LABELS = {
  established: 'Established',
  location: 'Location',
  intake: 'Intake',
  hostel: 'Hostel',
  legal_aid_clinics: 'Legal aid clinics',
  moot_teams: 'Moot teams',
};

/* --------------------------- S-29 row schema ------------------------------ */

/**
 * APPROVED 13-row S-29 comparison schema — frozen order and labels
 * (SAATHI-63/118 Option C+ final closure, 2026-07-28). The first seven rows
 * project catalogue columns; the last six are the law_school_facts keys.
 */
export const COMPARE_ROWS = Object.freeze([
  { key: 'state', label: 'State' },
  { key: 'institution_type', label: 'Institution type' },
  { key: 'accreditation', label: 'Accreditation' },
  { key: 'entrance_exam', label: 'Entrance exam' },
  { key: 'fees', label: 'Fees' },
  { key: 'nirf_rank', label: 'NIRF rank' },
  { key: 'programmes', label: 'Programmes' },
  { key: 'established', label: 'Established' },
  { key: 'location', label: 'Location' },
  { key: 'intake', label: 'Intake' },
  { key: 'hostel', label: 'Hostel' },
  { key: 'legal_aid_clinics', label: 'Legal aid clinics' },
  { key: 'moot_teams', label: 'Moot teams' },
]);

export function nirfText(rank) {
  return rank !== null && rank !== undefined ? `#${rank}` : 'Not ranked';
}

export function programmesText(progs) {
  return progs && progs.length
    ? progs.map((p) => `${p.degree} (${p.durationYears} yrs)`).join(' · ')
    : 'Not listed';
}

/**
 * Deterministic formatted value for one approved S-29 row.
 * @param key one of COMPARE_ROWS[].key
 * @param s   { state, institutionType, accreditation, entranceExam, feesMin,
 *              feesMax, nirfRank, programmes, facts: {key: value} }
 */
export function compareRowValue(key, s) {
  switch (key) {
    case 'state': return s.state;
    case 'institution_type': return institutionTypeLabel(s.institutionType);
    case 'accreditation': return s.accreditation;
    case 'entrance_exam': return s.entranceExam;
    case 'fees': return feesInrBand(s.feesMin, s.feesMax);
    case 'nirf_rank': return nirfText(s.nirfRank);
    case 'programmes': return programmesText(s.programmes);
    default:
      return (s.facts && s.facts[key]) ?? 'Not available · not yet verified from an official source';
  }
}

/* ------------------------ source / freshness copy ------------------------- */

/** Reference LSKIT fmtDate(): '1 Jul 2026' (TZ-independent). */
export function verifiedText(isoDate = REFERENCE_VERIFIED_DATE) {
  const [y, m, d] = isoDate.slice(0, 10).split('-').map(Number);
  const M = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  return `Verified ${d} ${M[m - 1]} ${y}`;
}

/** Reference COPY.source (S-29 footer, source/freshness treatment). */
export function referenceSourceFoot() {
  return `Source: institution website · sample verification ${verifiedText().replace('Verified ', '')} · prototype data, not production facts`;
}

/** Reference COPY.responsible (S-29 footer second line). */
export const REFERENCE_RESPONSIBLE_COPY =
  'Verify every fact on the institution’s official website before acting on it. '
  + 'This directory shows sample prototype data with source and freshness context; it is not admission guidance.';
