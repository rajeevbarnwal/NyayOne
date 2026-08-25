import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  NYAY7_ASSERTION_INVENTORY,
  NYAY7_AUTHORITY_SHA256,
  NYAY7_CHECKS,
  NYAY7_COLOR_SCHEMES,
  NYAY7_EXPANDED_ASSERTION_INVENTORY,
  NYAY7_EXPANDED_CHECKS,
  NYAY7_EXPANDED_VIEWPORTS,
  NYAY7_LANGUAGE_OPTIONS,
  NYAY7_MOBILE_TARGET_MIN,
  NYAY7_PERSONA_OPTIONS,
  NYAY7_SCREENS,
  NYAY7_VISUAL_MAX_MISMATCH_RATIO,
  NYAY7_VIEWPORTS,
  nyay7AssertionName,
  nyay7ExpandedAssertionName,
  summarizeNyay7ExpandedRows,
  summarizeNyay7Rows,
} from './nyay7-ui-contract.mjs';

const root = process.cwd();
const source = (path) => readFileSync(join(root, path), 'utf8');
const sha256 = (path) => createHash('sha256').update(readFileSync(join(root, path))).digest('hex');

describe('NYAY-7 Option 3.2.1 source contract', () => {
  it('pins the corrected Revision L authority and exact viewport/screen matrix', () => {
    expect(NYAY7_AUTHORITY_SHA256).toBe(
      '338d5fd22b5e9e8c3c7599846428c99b151b3adf21907f69998a54fdefe33252',
    );
    expect(NYAY7_VIEWPORTS.map(({ width, height }) => [width, height])).toEqual([
      [1440, 1024], [390, 844], [360, 800],
    ]);
    expect(NYAY7_SCREENS.map(({ id }) => id)).toEqual(['S-03', 'S-04', 'S-05', 'S-08', 'S-09']);
    expect(NYAY7_MOBILE_TARGET_MIN).toBe(44);
    expect(NYAY7_VISUAL_MAX_MISMATCH_RATIO).toBeLessThanOrEqual(0.01);
    expect(NYAY7_ASSERTION_INVENTORY).toHaveLength(3 * 5 * 8);
    expect(new Set(NYAY7_ASSERTION_INVENTORY).size).toBe(NYAY7_ASSERTION_INVENTORY.length);
    expect(nyay7AssertionName('desktop', 'S-03', 'mount')).toBe('desktop:S-03:mount');
  });

  it('keeps expanded light/dark coverage separate from sealed light visual baselines', () => {
    expect(NYAY7_EXPANDED_VIEWPORTS.map(({ width, height }) => [width, height])).toEqual([
      [390, 844], [430, 932], [768, 1024], [1024, 768], [1440, 1024],
    ]);
    expect(NYAY7_COLOR_SCHEMES).toEqual(['light', 'dark']);
    expect(NYAY7_EXPANDED_CHECKS).toEqual([
      'mount',
      'axe-serious-critical',
      'horizontal-overflow',
      'mobile-touch-targets',
      'layout-shift',
      'theme-activation',
      'selector-context-contract',
    ]);
    expect(NYAY7_EXPANDED_CHECKS).not.toContain('visual-baseline');
    expect(NYAY7_EXPANDED_CHECKS).not.toContain('rev-l-token-use');
    expect(NYAY7_EXPANDED_ASSERTION_INVENTORY).toHaveLength(5 * 2 * 5 * 7);
    expect(new Set(NYAY7_EXPANDED_ASSERTION_INVENTORY).size)
      .toBe(NYAY7_EXPANDED_ASSERTION_INVENTORY.length);
    expect(nyay7ExpandedAssertionName('dark', 'width-430', 'S-03', 'mount'))
      .toBe('expanded:dark:width-430:S-03:mount');
  });

  it('pins the Revision L selector order, availability, and exact scripts', () => {
    expect(NYAY7_PERSONA_OPTIONS).toEqual([
      { name: 'Lawyer', selected: 'false', disabled: 'true', text: 'Lawyer Coming soon' },
      { name: 'Student', selected: 'true', disabled: 'false', text: 'Student Available' },
      { name: 'Customer', selected: 'false', disabled: 'true', text: 'Customer Coming soon' },
      { name: 'University', selected: 'false', disabled: 'true', text: 'University Coming soon' },
    ]);
    expect(NYAY7_LANGUAGE_OPTIONS).toEqual([
      { name: 'English', selected: 'true', disabled: 'false', text: 'English Available' },
      { name: 'हिन्दी', selected: 'false', disabled: 'true', text: 'हिन्दी Coming soon' },
      { name: 'ಕನ್ನಡ', selected: 'false', disabled: 'true', text: 'ಕನ್ನಡ Coming soon' },
    ]);
  });

  it('seals all 15 mixed-authority visual baselines and the security supersession', () => {
    const manifest = JSON.parse(source('test-baselines/nyay7/option-3.2.1-rev-l/manifest.json'));
    expect(manifest.schema_version).toBe(2);
    expect(manifest.authority_sha256).toBe(NYAY7_AUTHORITY_SHA256);
    expect(manifest.revision_l_authority_screens).toEqual(['S-03', 'S-04', 'S-05']);
    expect(manifest.security_capture_provenance).toEqual({
      generated_at: '2026-08-24T18:35:40.044Z',
      runner: 'scripts/nyay7-ui-foundation.mjs',
      production_build: true,
      platform: 'darwin-arm64',
      worktree_parent_commit: '933a8a34bd38bcfb5e5ea6e5018f54e6ac2c9719',
    });
    expect(manifest.security_supersession).toEqual({
      effective_date: '2026-08-25',
      authority_tickets: ['NYAY-2', 'NYAY-4', 'NYAY-19'],
      record: 'SECURITY_SUPERSESSION.md',
      screens: {
        'S-08': 'empty-inputs-two-separate-unchecked-consents',
        'S-09': 'pending-otp-final-static-frame-before-server-authoritative-s-07-redirect',
      },
    });
    expect(manifest.entries).toHaveLength(15);
    const identities = manifest.entries.map(({ viewport, screen }) => `${viewport}:${screen}`);
    expect(new Set(identities).size).toBe(15);
    for (const entry of manifest.entries) {
      expect(sha256(join('test-baselines/nyay7/option-3.2.1-rev-l', entry.file))).toBe(entry.sha256);
    }
    const securityContractHashes = new Map([
      ['1440x1024:S-08', '70ce15e76201c816876ae282e906edc942aabd9cf87ec8b72129ae3e02a0ea39'],
      ['1440x1024:S-09', '231f37f3604aa1210809f7aabddfb7f35792c164a6cd0ad39e32d841d2cb9f5d'],
      ['390x844:S-08', '0bb2c19de7bc6135f8b9c42ab11b2b2da0a1ce7595b40bc12ad8e1dc249c5c60'],
      ['390x844:S-09', '91fe93265420db14a631fc17c0f48ebca49da76c68473ce2ca82677e6e73287b'],
      ['360x800:S-08', 'a3fdc5616bd21c1c1b33bebff78feda8ddc0bf3c7096f1f6b30ec656775242c3'],
      ['360x800:S-09', 'bccf2f2c0171cce2ed877d53371ee31a1d9652e9bdecc4d85e76eb3c014fff78'],
    ]);
    const supersededEntries = manifest.entries
      .filter(({ screen }) => ['S-08', 'S-09'].includes(screen));
    expect(supersededEntries).toHaveLength(6);
    expect(manifest.entries.filter(({ authority }) => authority === 'revision-l-source'))
      .toHaveLength(9);
    expect(manifest.entries.every(({ authority }) => (
      ['revision-l-source', 'security-contracts'].includes(authority)
    ))).toBe(true);
    for (const entry of supersededEntries) {
      expect(entry.authority).toBe('security-contracts');
      expect(entry.sha256).toBe(securityContractHashes.get(`${entry.viewport}:${entry.screen}`));
      expect(entry.supersedes_sha256).toMatch(/^[a-f0-9]{64}$/u);
      expect(entry.supersedes_sha256).not.toBe(entry.sha256);
    }
    const supersession = source(
      'test-baselines/nyay7/option-3.2.1-rev-l/SECURITY_SUPERSESSION.md',
    );
    for (const entry of supersededEntries) {
      expect(supersession).toContain(entry.supersedes_sha256);
      expect(supersession).toContain(entry.sha256);
    }
    for (const ticket of manifest.security_supersession.authority_tickets) {
      expect(supersession).toContain(ticket);
    }
    expect(supersession).toMatch(/persistent client-side success screen is\s+intentionally absent/u);
  });

  it('keeps the official brand SVG bytes unchanged', () => {
    expect(sha256('public/brand/nyayone-mark.svg')).toBe(
      '236192781d6e4c1dc11cf332a42962f8bc7334ed83e1cd91c18ca180578da95e',
    );
    expect(sha256('public/brand/nyayone-lockup.svg')).toBe(
      '829f3f1a8c4b340524ccf399c5f0dbed586a559f0b1030d8640ff1d5f6b6afc4',
    );
    expect(sha256('public/brand/nyayone-lockup-reversed.svg')).toBe(
      'f42c8b95145ad77c3782e9d5c9c706fe05bd658286f0100deec8723e56c9cd4e',
    );
  });

  it('defines the exact namespaced palette and geometry without replacing legacy tokens', () => {
    const tokens = source('src/styles/nyayone-tokens.css').toLowerCase();
    for (const literal of [
      '#2e3a8c', '#1c2454', '#c89a3a', '#dfb458', '#efedf6', '#14161a',
      '#ffffff', '#e4e1ef', '#3e4254', '#5c5f7a', '#d8d5e6', '#b9b5cf',
      '#1e6b4a', '#e2f0e9', '#9a2b21', '#f9e8e5', '#7a5a10', '#f7efd9',
      '#f6edda', '#e7e9f7',
    ]) expect(tokens).toContain(literal);
    expect(tokens).toContain('--nyayone-target-min: 44px');
    expect(tokens).toContain('--nyayone-control-min-height: 48px');
    expect(tokens).toContain("--nyayone-font-heading: aptos, calibri, 'nyayone revision l heading', system-ui, sans-serif");
    const fonts = source('src/styles/fonts.css');
    expect(fonts).toContain("font-family: 'NyayOne Revision L Heading'");
    expect(fonts).not.toMatch(/@font-face\s*\{[^}]*font-family:\s*'Carlito'/su);
    expect(source('src/styles/global.css')).toContain("@import './nyayone-tokens.css';");
  });

  it('fails closed for missing, duplicate, skipped, unexecuted, and unknown assertions', () => {
    const complete = NYAY7_ASSERTION_INVENTORY.map((name) => ({
      name, pass: true, executed: true, skipped: false, diagnostics: {},
    }));
    expect(summarizeNyay7Rows(complete)).toMatchObject({ valid: true, failed: 0 });
    expect(summarizeNyay7Rows(complete.slice(1)).valid).toBe(false);
    expect(summarizeNyay7Rows([...complete, complete[0]]).valid).toBe(false);
    expect(summarizeNyay7Rows(complete.map((row, index) => (
      index === 0 ? { ...row, skipped: true } : row
    ))).valid).toBe(false);
    expect(summarizeNyay7Rows(complete.map((row, index) => (
      index === 0 ? { ...row, executed: false } : row
    ))).valid).toBe(false);
    expect(summarizeNyay7Rows([...complete.slice(1), {
      name: 'invented:assertion', pass: true, executed: true, skipped: false,
    }]).valid).toBe(false);
  });

  it('fails the expanded inventory closed independently of the canonical gate', () => {
    const complete = NYAY7_EXPANDED_ASSERTION_INVENTORY.map((name) => ({
      name, pass: true, executed: true, skipped: false, diagnostics: {},
    }));
    expect(summarizeNyay7ExpandedRows(complete)).toMatchObject({
      valid: true,
      total: 350,
      failed: 0,
    });
    expect(summarizeNyay7ExpandedRows(complete.slice(1)).valid).toBe(false);
    expect(summarizeNyay7ExpandedRows([...complete, complete[0]]).valid).toBe(false);
    expect(summarizeNyay7ExpandedRows(complete.map((row, index) => (
      index === 0 ? { ...row, skipped: true } : row
    ))).valid).toBe(false);
  });

  it('runs full-document Axe and every required production observation without rule suppression', () => {
    const runner = source('scripts/nyay7-ui-foundation.mjs');
    expect(runner).toContain('axe.run(document');
    expect(runner).toContain("['critical', 'serious']");
    expect(runner).not.toMatch(/rules\s*:/u);
    for (const check of NYAY7_CHECKS) expect(runner).toContain(`'${check}'`);
    expect(runner).toContain('layout-shift');
    expect(runner).toContain('pixelmatch');
    expect(runner).toContain('data-nyayone-persona-trigger');
    expect(runner).toContain('data-nyayone-language-trigger');
    expect(runner).toContain('NYAY7_EXPANDED_ASSERTION_INVENTORY');
    expect(runner).toContain('NYAY7_COLOR_SCHEMES');
    expect(runner).toContain('NYAY7_EXPANDED_VIEWPORTS');
    expect(runner).toContain("colorScheme: 'light'");
    expect(runner).toContain('colorScheme,');
    const expandedStart = runner.indexOf('// Supplemental responsive/theme matrix.');
    const expandedEnd = runner.indexOf('\n} finally {', expandedStart);
    expect(expandedStart).toBeGreaterThan(-1);
    expect(expandedEnd).toBeGreaterThan(expandedStart);
    expect(runner.slice(expandedStart, expandedEnd)).not.toContain('compareVisual(');
    expect(runner).toContain("destination_masked: '••••••0340'");
    expect(runner).toContain("'access-control-allow-credentials': 'true'");
    expect(runner).toContain("lawyer.click({ force: true })");
    expect(runner).toContain("hindi.click({ force: true })");
    expect(runner).toContain('document.activeElement.blur()');
    expect(runner).toContain('async function navigateToFixtureScreen');
    expect(runner).toContain('async function observeSecuritySupersessionState');
    for (const id of [
      'v34-first', 'v34-middle', 'v34-last', 'v34-mobile', 'v34-dob',
      'v34-terms', 'v34-privacy',
    ]) expect(runner).toContain(`'${id}'`);
    expect(runner).toContain("getByRole('button', { name: 'Verify and continue' })");
    expect(runner).toContain("'Set Up My Profile', 'Skip for Now', 'Code accepted'");
    expect(runner).toContain("history.pushState({}, '', path)");
    const navigationStart = runner.indexOf('async function navigateToFixtureScreen');
    const navigationEnd = runner.indexOf('async function observeAxe', navigationStart);
    const otpNavigation = runner.slice(navigationStart, navigationEnd);
    const layoutReset = otpNavigation.indexOf('window.__nyay7LayoutShift = []');
    const routeTransition = otpNavigation.indexOf("history.pushState({}, '', path)");
    expect(layoutReset).toBeGreaterThan(-1);
    expect(routeTransition).toBeGreaterThan(layoutReset);
  });
});
