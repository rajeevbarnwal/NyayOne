import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  NYAY7_ASSERTION_INVENTORY,
  NYAY7_AUTHORITY_SHA256,
  NYAY7_CHECKS,
  NYAY7_LANGUAGE_OPTIONS,
  NYAY7_MOBILE_TARGET_MIN,
  NYAY7_PERSONA_OPTIONS,
  NYAY7_SCREENS,
  NYAY7_VISUAL_MAX_MISMATCH_RATIO,
  NYAY7_VIEWPORTS,
  nyay7AssertionName,
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

  it('seals all 15 approved visual baselines to the independent QA hashes', () => {
    const manifest = JSON.parse(source('test-baselines/nyay7/option-3.2.1-rev-l/manifest.json'));
    expect(manifest.authority_sha256).toBe(NYAY7_AUTHORITY_SHA256);
    expect(manifest.entries).toHaveLength(15);
    const identities = manifest.entries.map(({ viewport, screen }) => `${viewport}:${screen}`);
    expect(new Set(identities).size).toBe(15);
    for (const entry of manifest.entries) {
      expect(sha256(join('test-baselines/nyay7/option-3.2.1-rev-l', entry.file))).toBe(entry.sha256);
    }
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
    expect(tokens).toContain('--nyayone-font-heading: aptos, calibri, carlito, system-ui, sans-serif');
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
  });
});
