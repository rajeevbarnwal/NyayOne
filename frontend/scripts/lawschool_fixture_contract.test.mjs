/**
 * SAATHI-121 — proof that BOTH renderers consume the identical fixture
 * contract: the reference frame's embedded LSKIT fixture, the contract file
 * and the developed-side expectations must agree (ids, keys, checksum), and
 * the checksum must be stable/deterministic.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';
import {
  contract, contractChecksum, checksumOfProjection, fixtureProjection,
  catalogSlugsByName, factRowsFor, programmesFor, s29RowCards, s30Groups, tokensHash,
} from './lawschool_fixture_contract.mjs';
import {
  COMPARE_ROWS, REFERENCE_VERIFIED_DATE,
} from '../src/features/student/schools/lawschoolFormat.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REF_DIR = path.resolve(HERE, '..', '..', 'docs', 'design', 'lawschool_reference', 'option_c_plus');

function embeddedResources() {
  const lines = fs.readFileSync(path.join(REF_DIR, 'OPTION_C_PLUS_GUIDED_CONFIDENCE.html'), 'utf8').split('\n');
  const manifestOpen = lines.findIndex((l) => l.includes('<script type="__bundler/manifest">'));
  const templateOpen = lines.findIndex((l) => l.includes('<script type="__bundler/template">'));
  const manifest = JSON.parse(lines[manifestOpen + 1]);
  const jsKey = Object.keys(manifest).find((k) => manifest[k].mime === 'application/javascript');
  const entry = manifest[jsKey];
  const raw = Buffer.from(entry.data, 'base64');
  const lskit = (entry.compressed ? zlib.gunzipSync(raw) : raw).toString('utf8');
  const template = JSON.parse(lines[templateOpen + 1]);
  return { lskit, template };
}

describe('lawschool fixture contract (shared visual-oracle fixture)', () => {
  it('honours the frozen product facts (catalog 12, compare min 2 / max 4)', () => {
    expect(contract.catalog).toHaveLength(12);
    expect(new Set(contract.catalog.map((s) => s.slug)).size).toBe(12);
    expect(contract.compare).toEqual({ min: 2, max: 4 });
    expect(contract.s29.slugs).toHaveLength(4);
    for (const slug of contract.s29.slugs) {
      expect(contract.catalog.some((s) => s.slug === slug)).toBe(true);
    }
    expect(contract.s30.saved).toHaveLength(2);
    expect(contract.s30.followed).toHaveLength(2);
  });

  it('derives the S-27 pagination state deterministically (6 per page, page 1)', () => {
    expect(contract.s27.pageSize).toBe(6);
    expect(contract.s27.page).toBe(1);
    expect(contract.s27.total).toBe(12);
    expect(contract.s27.pageCount).toBe(2);
    expect(contract.s27.visibleSlugs).toEqual(catalogSlugsByName().slice(0, 6));
  });

  it('labels every sample fact value as sample (never a verified claim)', () => {
    for (const s of contract.catalog) {
      const rows = factRowsFor(s.slug);
      expect(rows.map((r) => r.key)).toEqual(contract.factKeys);
      for (const r of rows) expect(r.value.endsWith('(sample)')).toBe(true);
    }
  });

  it('computes a stable, key-order-independent checksum', () => {
    const a = contractChecksum();
    expect(a).toBe(contractChecksum());
    expect(a).toBe(checksumOfProjection(fixtureProjection()));
    const reversed = JSON.parse(JSON.stringify(fixtureProjection(), null, 0));
    const flip = (o) => {
      if (Array.isArray(o)) return o.map(flip);
      if (o !== null && typeof o === 'object') {
        return Object.fromEntries(Object.keys(o).sort().reverse().map((k) => [k, flip(o[k])]));
      }
      return o;
    };
    expect(checksumOfProjection(flip(reversed))).toBe(a);
  });

  it('matches the developed-side seed rules (programmes per institution type)', () => {
    for (const s of contract.catalog) {
      const progs = programmesFor(s.slug);
      expect(progs[0]).toEqual({ degree: 'BA LLB (Hons)', durationYears: 5 });
      const hasLlm = progs.some((p) => p.degree === 'LLM');
      expect(hasLlm).toBe(s.institutionType === 'government' || s.institutionType === 'national_law_university');
    }
  });

  it('is embedded verbatim in the reference frame (LSKIT.FIXTURE == contract)', () => {
    const { lskit } = embeddedResources();
    const generatedCopy = fs.readFileSync(path.join(REF_DIR, 'OPTION_C_PLUS_LSKIT_GENERATED.js'), 'utf8');
    expect(lskit.replace(/\r\n/g, '\n')).toBe(generatedCopy.replace(/\r\n/g, '\n'));
    const m = lskit.match(/var FIXTURE=([\s\S]*?);\nfunction fmtDate/);
    expect(m).not.toBeNull();
    const fixture = JSON.parse(m[1]);
    expect(fixture.checksum).toBe(contractChecksum());
    expect(fixture.version).toBe(contract.version);
    expect(fixture.catalogSlugsByName).toEqual(catalogSlugsByName());
    expect(fixture.s27Visible).toEqual(contract.s27.visibleSlugs);
    expect(fixture.perPage).toBe(contract.s27.pageSize);
    expect(fixture.s28Slug).toBe(contract.s28.slug);
    expect(fixture.s29Slugs).toEqual(contract.s29.slugs);
    expect(fixture.s30Saved).toEqual(contract.s30.saved);
    expect(fixture.s30Followed).toEqual(contract.s30.followed);
    expect(fixture.factKeys).toEqual(contract.factKeys);
    /* reference SEED ids ARE the contract slugs */
    const seedMatch = lskit.match(/var SEED=([\s\S]*?);\nvar LABELS=/);
    expect(seedMatch).not.toBeNull();
    const seed = JSON.parse(seedMatch[1]);
    expect(seed.map((s) => s.id).sort()).toEqual(contract.catalog.map((s) => s.slug).sort());
  });

  it('pins the reference template states to contract ids (no stale short ids)', () => {
    const { template } = embeddedResources();
    const q = (arr) => `[${arr.map((s) => `'${s}'`).join(',')}]`;
    expect(template).toContain(`S.cmp=${q(contract.s29.slugs)};`);
    expect(template).toContain(`S.saved=${q(contract.s30.saved)};S.followed=${q(contract.s30.followed)};`);
    for (const stale of ["'nlsiu'", "'nalsar'", "'nlud'", "'gnlu'", "'nujs'", "'dsnlu'"]) {
      expect(template.includes(stale)).toBe(false);
    }
    expect(template).toContain('(K.FACTS29||F).map(');
  });
});

describe('fixture contract v2 (full visible semantic scope — QA F4)', () => {
  const APPROVED_LABELS = [
    'State', 'Institution type', 'Accreditation', 'Entrance exam', 'Fees',
    'NIRF rank', 'Programmes', 'Established', 'Location', 'Intake', 'Hostel',
    'Legal aid clinics', 'Moot teams',
  ];

  it('is versioned v2 and stays date-synced with the shared formatter', () => {
    expect(contract.version.startsWith('2.')).toBe(true);
    expect(contract.verifiedDate).toBe(REFERENCE_VERIFIED_DATE);
    expect(COMPARE_ROWS.map((r) => r.label)).toEqual(APPROVED_LABELS);
  });

  it('projects ALL 13 approved S-29 rows in order for every compared school', () => {
    const cards = s29RowCards();
    expect(cards).toHaveLength(13);
    expect(cards.map((c) => c.label)).toEqual(APPROVED_LABELS);
    for (const card of cards) {
      expect(card.values).toHaveLength(contract.s29.slugs.length);
      for (const v of card.values) expect(typeof v).toBe('string');
    }
    const p = fixtureProjection();
    expect(p.s29Rows.labels).toEqual(APPROVED_LABELS);
    expect(p.s29Rows.order).toEqual(contract.s29.slugs);
    expect(p.s27Cards).toHaveLength(6);
    for (const c of p.s27Cards) expect(c.feesLakh).toMatch(/^₹.+ L–₹.+ L \/ yr$/);
    expect(p.s28Card.factRows.map((r) => r.key)).toEqual(contract.factKeys);
    for (const r of p.s28Card.factRows) {
      expect(r.label).toBeTruthy();
      expect(r.sourceName).toBe(contract.sourceName);
      expect(r.freshness).toBe('Verified 1 Jul 2026');
    }
    expect(s30Groups().map((g) => g.name)).toEqual(['Saved', 'Following']);
    expect(p.tokens.sha256).toBe(tokensHash());
    expect(p.tokens.sha256).toMatch(/^[0-9a-f]{64}$/);
  });

  it('FAILS the v2 checksum for a 7-row S-29 projection vs the 13-row reference', () => {
    /* Explicit regression for the QA finding: the v1 checksum PASSED while the
     * developed S-29 rendered only seven rows. A projection whose S-29 schema
     * is truncated to the first seven rows must NEVER checksum-match. */
    const reference = contractChecksum();
    const p = fixtureProjection();
    const sevenRow = {
      ...p,
      s29Rows: {
        ...p.s29Rows,
        labels: p.s29Rows.labels.slice(0, 7),
        cards: p.s29Rows.cards.slice(0, 7),
      },
    };
    expect(sevenRow.s29Rows.cards).toHaveLength(7);
    expect(checksumOfProjection(sevenRow)).not.toBe(reference);
    /* and the full 13-row projection still matches exactly */
    expect(checksumOfProjection(p)).toBe(reference);
  });

  it('covers every v2 semantic field in the checksum (mutation flips it)', () => {
    const reference = contractChecksum();
    const mutate = (fn) => {
      const p = fixtureProjection();
      fn(p);
      return checksumOfProjection(p);
    };
    expect(mutate((p) => { p.s27Cards[0].feesLakh = '₹1 L–₹2 L / yr'; })).not.toBe(reference);
    expect(mutate((p) => { p.s28Card.factRows[0].freshness = 'Verified 2 Jul 2026'; })).not.toBe(reference);
    expect(mutate((p) => { p.s29Rows.cards[4].values[0] = '₹9,99,999–₹9,99,999/yr'; })).not.toBe(reference);
    expect(mutate((p) => { p.s30Groups.reverse(); })).not.toBe(reference);
    expect(mutate((p) => { p.s30Groups[0].cards[0].metaline = 'X'; })).not.toBe(reference);
    expect(mutate((p) => { p.tokens.sha256 = '0'.repeat(64); })).not.toBe(reference);
    expect(mutate((p) => { p.s29Rows.labels[4] = 'Fees (per year)'; })).not.toBe(reference);
  });
});
