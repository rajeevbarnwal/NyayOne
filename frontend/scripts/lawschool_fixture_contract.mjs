/**
 * SAATHI-118/120/121 — shared deterministic fixture contract (single source),
 * CONTRACT v2 (2026-07-28 final closure).
 *
 * ONE contract consumed by BOTH sides of the Option C+ visual oracle:
 *   - developed side: scripts/lawschool-e2e.mjs seeds/verifies server state and
 *     FAILS BEFORE capture if the developed API fixture checksum, visible IDs,
 *     visible fact-row keys OR ANY v2 semantic projection field differs from
 *     this contract;
 *   - reference side: scripts/generate-lawschool-reference-fixture.mjs
 *     regenerates the LSKIT seed embedded in
 *     docs/design/lawschool_reference/option_c_plus/OPTION_C_PLUS_GUIDED_CONFIDENCE.html
 *     from this contract and embeds the same checksum
 *     (window.LSKIT.FIXTURE.checksum).
 *
 * v2 checksum scope (QA F4 remediation — the v1 checksum proved IDs, not the
 * full visible semantic contract): every visible S-27 card field/order/label/
 * formatted value (incl. fees lakh strings), the complete S-28 identity +
 * fact rows with source/freshness copy, ALL 13 approved S-29 rows × school
 * order × labels × formatted values, S-30 group order/names/metalines/CTA
 * labels, plus the option_c_plus token stylesheet hash (light+dark tokens
 * that affect feature pixels). All formatted values come from the SHARED
 * formatter (src/features/student/schools/lawschoolFormat.mjs) also used by
 * the developed UI and the reference generator.
 *
 * FROZEN product facts honoured here: catalog = 12 schools; compare min 2,
 * config max 4. Sample values are always "(sample)"-labelled and never
 * presented as verified claims.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import {
  COMPARE_ROWS, FACT_LABELS, compareRowValue, feesInrBand, feesLakhBand,
  nirfText, programmesText, verifiedText,
} from '../src/features/student/schools/lawschoolFormat.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const CONTRACT_PATH = path.join(HERE, 'lawschool_fixture_contract.json');
export const TOKENS_CSS_RELPATH = 'docs/design/lawschool_reference/option_c_plus/option_c_plus_tokens.css';
const TOKENS_CSS_PATH = path.resolve(HERE, '..', '..', ...TOKENS_CSS_RELPATH.split('/'));

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

/** Shared-formatter input for one contract school (mirrors the live API). */
export function formatInputFor(slug, c = contract) {
  const s = schoolBySlug(slug, c);
  return {
    state: s.state,
    institutionType: s.institutionType,
    accreditation: s.accreditation,
    entranceExam: s.entranceExam,
    feesMin: s.feesMin,
    feesMax: s.feesMax,
    nirfRank: s.nirfRank,
    programmes: programmesFor(slug, c),
    facts: Object.fromEntries(factRowsFor(slug, c).map((r) => [r.key, r.value])),
  };
}

/** ALL 13 approved S-29 rows × school order × labels × formatted values. */
export function s29RowCards(c = contract) {
  return COMPARE_ROWS.map(({ key, label }) => ({
    key,
    label,
    values: c.s29.slugs.map((slug) => compareRowValue(key, formatInputFor(slug, c))),
  }));
}

/** One S-27 result card as the user sees it (order = array order). */
function s27CardFor(slug, c = contract) {
  const s = schoolBySlug(slug, c);
  return {
    slug: s.slug,
    name: s.name,
    state: s.state,
    institutionType: s.institutionType,
    feesLakh: feesLakhBand(s.feesMin, s.feesMax), // reference K.fee() lakh string
    entranceExam: s.entranceExam,
    nirf: nirfText(s.nirfRank),
    compareCta: '+ Compare',
    viewCta: 'View',
  };
}

/** S-28 identity + complete fact-row keys/order/values/source/freshness copy. */
export function s28CardFor(c = contract) {
  const slug = c.s28.slug;
  const s = schoolBySlug(slug, c);
  return {
    slug,
    name: s.name,
    identity: `${s.state} · ${s.institutionType} · ${s.accreditation}.`,
    essentials: [
      { key: 'exam', label: 'Entrance exam', value: s.entranceExam },
      { key: 'fees', label: 'Fee band (sample)', value: feesInrBand(s.feesMin, s.feesMax) },
      { key: 'nirf', label: 'NIRF rank (sample)', value: nirfText(s.nirfRank) },
      { key: 'progs', label: 'Programmes', value: programmesText(programmesFor(slug, c)) },
    ],
    factRows: factRowsFor(slug, c).map((r) => ({
      key: r.key,
      label: FACT_LABELS[r.key],
      value: r.value,
      sourceName: c.sourceName,
      freshness: verifiedText(c.verifiedDate),
    })),
    saved: c.s28.saved,
    followed: c.s28.followed,
  };
}

/** S-30 group order, names, metalines (state + lakh fees + freshness), CTAs. */
export function s30Groups(c = contract) {
  const card = (slug) => {
    const s = schoolBySlug(slug, c);
    return {
      slug,
      name: s.name,
      metaline: `${s.state.toUpperCase()} · ${feesLakhBand(s.feesMin, s.feesMax).toUpperCase()} (SAMPLE) · ${verifiedText(c.verifiedDate).toUpperCase()}`,
      viewCta: 'View',
    };
  };
  return [
    { name: 'Saved', ariaLabel: 'Saved schools', cta: 'Remove from saved', slugs: c.s30.saved, cards: c.s30.saved.map(card) },
    { name: 'Following', ariaLabel: 'Followed schools', cta: 'Stop following', slugs: c.s30.followed, cards: c.s30.followed.map(card) },
  ];
}

/** sha256 of the option_c_plus token stylesheet (light+dark feature tokens). */
export function tokensHash() {
  return crypto.createHash('sha256').update(fs.readFileSync(TOKENS_CSS_PATH, 'utf8').replace(/\r\n/g, '\n')).digest('hex');
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
 * canonical shape (CONTRACT v2). The developed side rebuilds this projection
 * FROM THE LIVE API (through the same shared formatter) before any capture;
 * the reference side embeds the checksum at generation time. Checksums must
 * be equal or the visual phase fails with FIXTURE_CONTRACT_MISMATCH before
 * any pixel is captured.
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
    /* ---- v2 semantic scope (QA F4) ---- */
    s27Cards: c.s27.visibleSlugs.map((slug) => s27CardFor(slug, c)),
    s28Card: s28CardFor(c),
    s29Rows: {
      order: c.s29.slugs,
      labels: COMPARE_ROWS.map((r) => r.label),
      cards: s29RowCards(c),
    },
    s30Groups: s30Groups(c),
    tokens: { file: TOKENS_CSS_RELPATH, sha256: tokensHash() },
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
