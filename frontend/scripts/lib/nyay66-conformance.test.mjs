import { describe, expect, it } from 'vitest';
import { PNG } from 'pngjs';
import {
  SOURCE_SHA256, VIEWS, VIEWPORTS, coverage, comparePixels,
  validateCalibration, classifyObservation,
} from './nyay66-conformance.mjs';

const image = () => new PNG({ width: 2, height: 2, fill: true });
const report = () => ({
  sourceSha256: SOURCE_SHA256, head: 'a'.repeat(40), purpose: 'REFERENCE_CALIBRATION_ONLY',
  rows: VIEWS.flatMap(view => VIEWPORTS.map(viewport => ({
    view, viewport: viewport.id, executed: true, sampleHashes: ['b'.repeat(64), 'b'.repeat(64), 'b'.repeat(64)],
    dimensions: [viewport.width, viewport.height], runtimeErrors: 0, blockedRequests: 0,
    deltas: [{ meanAbsDiff: 0, mismatchRatio: 0 }, { meanAbsDiff: 0, mismatchRatio: 0 }],
  }))),
});

describe('NYAY-66 calibration integrity', () => {
  it('covers 17 canonical routes plus popup without inventing gap references', () => {
    expect(VIEWS).toHaveLength(15);
    expect(coverage()).toHaveLength(18);
    expect(coverage().filter(row => row.status === 'DESIGN-GAP').map(row => row.screen)).toEqual(['S-01', 'S-02', 'S-06']);
    expect(coverage().find(row => row.screen === 'S-10').views).toEqual(['s10a', 's10b']);
    expect(coverage().find(row => row.screen === 'S-07-popup').views).toEqual(['s14p']);
    expect(coverage('dark').every(row => row.status === 'DESIGN-GAP')).toBe(true);
  });
  it('accepts complete executed calibration, never calling it application parity', () => {
    expect(validateCalibration(report())).toEqual([]);
    expect(coverage().some(row => row.status === 'PARITY')).toBe(false);
  });
  for (const [name, mutate] of [
    ['source mismatch', r => { r.sourceSha256 = '0'.repeat(64); }],
    ['invalid head', r => { r.head = 'main'; }],
    ['missing panel', r => r.rows.pop()],
    ['duplicate panel', r => { r.rows[1] = r.rows[0]; }],
    ['unknown view', r => { r.rows[0].view = 's01'; }],
    ['unexecuted row', r => { r.rows[0].executed = false; }],
    ['empty capture hash', r => { r.rows[0].sampleHashes[0] = ''; }],
    ['missing sample', r => r.rows[0].sampleHashes.pop()],
    ['missing comparison', r => r.rows[0].deltas.pop()],
    ['wrong dimensions', r => { r.rows[0].dimensions[0] = 1; }],
    ['runtime error', r => { r.rows[0].runtimeErrors = 1; }],
    ['outbound request', r => { r.rows[0].blockedRequests = 1; }],
    ['boolean count', r => { r.rows[0].runtimeErrors = false; }],
    ['NaN metric', r => { r.rows[0].deltas[0].meanAbsDiff = NaN; }],
    ['negative metric', r => { r.rows[0].deltas[0].mismatchRatio = -1; }],
    ['oversized ratio', r => { r.rows[0].deltas[0].mismatchRatio = 2; }],
    ['parity mislabelling', r => { r.purpose = 'LIVE_PARITY'; }],
  ]) it(`refuses ${name}`, () => {
    const value = report(); mutate(value); expect(validateCalibration(value).length).toBeGreaterThan(0);
  });
  it('computes exact RGB difference and detects a single changed pixel', () => {
    const a = image(), b = image(); b.data[0] = 255;
    expect(comparePixels(a, a)).toEqual({ meanAbsDiff: 0, mismatchRatio: 0 });
    expect(comparePixels(a, b)).toEqual({ meanAbsDiff: 21.25, mismatchRatio: 0.25 });
  });
  it('rejects size mismatch rather than resize the oracle', () => {
    expect(() => comparePixels(image(), new PNG({ width: 3, height: 2 }))).toThrow('DIMENSION_MISMATCH');
  });
});

describe('NYAY-66 progressive verdicts', () => {
  const good = { reference: true, executed: true, pixels: true, structure: true, accessibility: true };
  it('cannot enforce without numeric owner approval', () => {
    expect(() => classifyObservation(good, { enforced: true, toleranceApproval: null })).toThrow('TOLERANCE_APPROVAL_REQUIRED');
  });
  it('does not mark a design gap as pass', () => {
    expect(classifyObservation({ ...good, reference: false }, {})).toEqual({ verdict: 'DESIGN-GAP', blocking: false });
  });
  it('reports pending calibration without claiming parity', () => {
    expect(classifyObservation(good, {})).toEqual({ verdict: 'CALIBRATION-PENDING', blocking: false });
  });
  it('blocks a regression in an enforced screen', () => {
    expect(classifyObservation({ ...good, pixels: false }, { enforced: true, toleranceApproval: 'owner:15380' })).toEqual({ verdict: 'REGRESSION', blocking: true });
  });
  it('reports unfixed screens without masking them as successful evidence', () => {
    expect(classifyObservation({ ...good, pixels: false }, { toleranceApproval: 'owner:15380' })).toEqual({ verdict: 'NONCONFORMANT', blocking: false });
  });
  for (const field of ['executed', 'pixels', 'structure', 'accessibility']) {
    it(`cannot pass an absent ${field} proof`, () => {
      const row = { ...good }; delete row[field];
      expect(classifyObservation(row, { enforced: true, toleranceApproval: 'owner:15380' }).blocking).toBe(true);
    });
  }
});
