/**
 * SAATHI-118/120/121 — shared deterministic fixture contract (single source).
 *
 * ONE contract consumed by BOTH sides of the Option C+ visual oracle:
 *   - developed side: scripts/lawschool-e2e.mjs seeds/verifies server state and
 *     FAILS BEFORE capture if the developed API fixture checksum, visible IDs
 *     or visible fact-row keys differ from this contract;
 *   - reference side: scripts/generate-lawschool-reference-fixture.mjs
 *     regenerates the LSKIT seed embedded in
 *     docs/design/lawschool_reference/option_c_plus/OPTION_C_PLUS_GUIDED_CONFIDENCE.html
 *     from this contract and embeds the same checksum
 *     (window.LSKIT.FIXTURE.checksum).
 *
 * FROZEN product facts honoured here: catalog = 12 schools; compare min 2,
 * config max 4. Sample values are always "(sample)"-labelled and never
 * presented as verified claims.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const CONTRACT_PATH = path.join(HERE, 'lawschool_fixture_contract.json');

export const contract = JSON.parse(fs.readFileSync(CONTRACT_PATH, 'utf8'));

/* ----------------------------- derived values ------------------------------ */

/** Backend name-sort order (ascending, ASCII/en collation equivalent here). */
export function catalogSlugsByName(c = contract) {
  return [...c.catalog].sort((a, b) => (a.name < b.name ? -1 : 1)).map((s) => s.slug);
}

export function schoolBySlug(slug, c = contract) {
  const s = c.catalog.find((x) => x.slug === slug);
  if (!s) throw new Error(`contract: unknown slug ${slug}`);
  return s;
}

/**
 * Deterministic SAMPLE-labelled fact rows for one school — MUST byte-match the
 * rows produced by backend/app/services/law_school_service.py seed_law_schools
 * (law_school_facts). Key order == contract.factKeys.
 */
export function factRowsFor(slug, c = contract) {
  const s = schoolBySlug(slug, c);
  return [
    { key: 'established', value: `${s.established} (sample)` },
    { key: 'location', value: `${s.city}, ${s.state} (sample)` },
    { key: 'intake', value: `${s.seats} seats (sample)` },
    { key: 'hostel', value: `${s.hostel} (sample)` },
    { key: 'legal_aid_clinics', value: `${s.legalAidClinics} clinics (sample)` },
    { key: 'moot_teams', value: `${s.mootTeams} teams (sample)` },
  ];
}

/** Programme rows exactly as the backend seed creates them. */
export function programmesFor(slug, c = contract) {
  const s = schoolBySlug(slug, c);
  const rows = [{ degree: 'BA LLB (Hons)', durationYears: 5 }];
  if (s.institutionType === 'government' || s.institutionType === 'national_law_university') {
    rows.push({ degree: 'LLM', durationYears: 1 });
  }
  return rows;
}

/* ------------------------------- checksum ---------------------------------- */

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map((k) => [k, canonical(value[k])]));
  }
  return value;
}

/**
 * The semantic fixture the two renderers must share, projected into ONE
 * canonical shape. The developed side rebuilds this projection FROM THE LIVE
 * API before any capture; the reference side embeds the checksum at
 * generation time. Checksums must be equal or the visual phase fails with
 * FIXTURE_CONTRACT_MISMATCH before any pixel is captured.
 */
export function fixtureProjection(c = contract) {
  return {
    version: c.version,
    verifiedDate: c.verifiedDate,
    compare: c.compare,
    factKeys: c.factKeys,
    catalogSlugsByName: catalogSlugsByName(c),
    schools: catalogSlugsByName(c).map((slug) => {
      const s = schoolBySlug(slug, c);
      return {
        slug: s.slug,
        name: s.name,
        state: s.state,
        institutionType: s.institutionType,
        accreditation: s.accreditation,
        entranceExam: s.entranceExam,
        feesMin: s.feesMin,
        feesMax: s.feesMax,
        nirfRank: s.nirfRank,
        programmes: programmesFor(slug, c),
        // key-sorted: the projection is order-independent w.r.t. API fact order
        facts: [...factRowsFor(slug, c)].sort((a, b) => (a.key < b.key ? -1 : 1)),
      };
    }),
    s27: c.s27,
    s28: c.s28,
    s29: c.s29,
    s30: c.s30,
  };
}

/** Checksum of ANY projection object (canonical/key-order independent). */
export function checksumOfProjection(projection) {
  return crypto.createHash('sha256')
    .update(JSON.stringify(canonical(projection)))
    .digest('hex');
}

export function contractChecksum(c = contract) {
  return checksumOfProjection(fixtureProjection(c));
}

export default contract;
