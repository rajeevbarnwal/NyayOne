import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const ROOT = resolve(import.meta.dirname, '../..');
const SHARED = resolve(import.meta.dirname, 'browser-response-readiness.mjs');
const SEEDED_VARIANCE = resolve(
  import.meta.dirname,
  'nyay26-readiness-variance-fixture.mjs',
);
const WAVE1 = resolve(ROOT, 'scripts/v34-s11-s26-e2e.mjs');
const NYAY5 = resolve(ROOT, 'scripts/nyay5-profile-browser.mjs');

const source = (path) => (existsSync(path) ? readFileSync(path, 'utf8') : '');

const sharedSource = source(SHARED);
const seededSource = source(SEEDED_VARIANCE);
const wave1Source = source(WAVE1);
const nyay5Source = source(NYAY5);

function between(whole, start, end) {
  const startIndex = whole.indexOf(start);
  if (startIndex < 0) return '';
  const endIndex = whole.indexOf(end, startIndex + start.length);
  return whole.slice(startIndex, endIndex < 0 ? whole.length : endIndex);
}

describe('NYAY-26 canonical readiness observer contract', () => {
  it('declares the closed session, profile, and OTP-state response inventory', () => {
    expect(sharedSource).toContain('CANONICAL_READINESS_RESPONSES');
    expect(sharedSource).toContain("session: Object.freeze({ method: 'GET', path: '/api/v1/auth/student/session' })");
    expect(sharedSource).toContain("profile: Object.freeze({ method: 'GET', path: '/api/v1/student/profile' })");
    expect(sharedSource).toContain("otpState: Object.freeze({ method: 'GET', path: '/api/v1/auth/student/otp/state' })");
  });

  it('matches only the exact method, origin, path, and query-free URL', () => {
    expect(sharedSource).toContain('export function isCanonicalReadinessResponse');
    expect(sharedSource).toContain('url.origin === apiOrigin');
    expect(sharedSource).toContain('url.pathname === descriptor.path');
    expect(sharedSource).toContain("url.search === ''");
    expect(sharedSource).toContain("url.hash === ''");
    expect(sharedSource).toContain('response.request().method() === descriptor.method');
  });

  it('arms every canonical response listener before the caller can navigate', () => {
    expect(sharedSource).toContain('export function armCanonicalReadiness');
    expect(sharedSource).toContain('page.waitForResponse');
    expect(sharedSource).toContain('Object.freeze([...requirements])');
    expect(sharedSource).not.toContain('waitForTimeout');
  });

  it('settles response bodies and fails closed on non-200 or unfinished responses', () => {
    expect(sharedSource).toContain('export async function settleCanonicalReadiness');
    expect(sharedSource).toContain('await response.finished()');
    expect(sharedSource).toContain('response.status() !== 200');
    expect(sharedSource).toContain('CANONICAL_RESPONSE_STATUS_INVALID');
    expect(sharedSource).toContain('CANONICAL_RESPONSE_UNFINISHED');
  });

  it('restricts response diagnostics to privacy-safe fields', () => {
    expect(sharedSource).toContain('READINESS_DIAGNOSTIC_FIELDS');
    for (const field of ['stage', 'kind', 'method', 'path', 'status', 'errorClass']) {
      expect(sharedSource).toContain(`'${field}'`);
    }
    for (const forbidden of ['query', 'headers', 'body', 'actor', 'cookie', 'otp', 'token']) {
      expect(sharedSource).not.toMatch(new RegExp(`['"]${forbidden}['"]\\s*:`, 'u'));
    }
  });

  it('waits for the observed route and visible DOM only after response settlement', () => {
    expect(sharedSource).toContain('export async function waitForRouteDomSettled');
    expect(sharedSource).toContain('await settledReadiness');
    expect(sharedSource).toContain('await page.waitForURL');
    expect(sharedSource).toContain("waitFor({ state: 'visible' })");
  });

  it('settles fonts, theme, lockup, and two animation frames before visual census', () => {
    expect(sharedSource).toContain('export async function waitForVisualCensusSettled');
    expect(sharedSource).toContain('document.fonts.ready');
    expect(sharedSource).toContain("getAttribute('data-theme')");
    expect(sharedSource).toContain("querySelector('.v321-lockup')");
    expect(sharedSource.match(/requestAnimationFrame/gu)).toHaveLength(2);
  });

  it('provides one deterministic retry-free seeded heading-stack variance reproduction', () => {
    expect(seededSource).toContain('export function runSeededHeadingStackVariance');
    expect(seededSource).toContain("assertion: 'browser:redesigned_heading_stack'");
    expect(seededSource).toContain('attempts: 1');
    expect(seededSource).toContain("legacyOutcome: 'FAIL_EARLY_SAMPLE'");
    expect(seededSource).toContain("settledOutcome: 'PASS'");
    expect(seededSource).not.toContain('waitForTimeout');
    expect(seededSource).not.toContain('retry');
  });
});

describe('NYAY-26 Wave 1 producer integration contract', () => {
  it('imports the shared authoritative readiness seam', () => {
    expect(wave1Source).toContain("from './lib/browser-response-readiness.mjs'");
    for (const symbol of [
      'armCanonicalReadiness',
      'settleCanonicalReadiness',
      'waitForRouteDomSettled',
      'waitForVisualCensusSettled',
    ]) {
      expect(wave1Source).toContain(symbol);
    }
  });

  it('arms session, profile, and OTP-state observers before private navigation', () => {
    const matrix = between(wave1Source, 'for (const state of states)', 'await context.close()');
    const arm = matrix.indexOf('const wave1Readiness = armCanonicalReadiness');
    const navigation = matrix.indexOf('await page.goto(`${base}${state.path}`');
    expect(arm).toBeGreaterThan(-1);
    expect(navigation).toBeGreaterThan(arm);
    expect(matrix).toContain("kind: 'session'");
    expect(matrix).toContain("kind: 'profile'");
    expect(matrix).toContain("kind: 'otpState'");
  });

  it('settles authority before asserting the transitioned private DOM', () => {
    const matrix = between(wave1Source, 'for (const state of states)', 'await context.close()');
    const settle = matrix.indexOf('settleCanonicalReadiness(wave1Readiness)');
    const dom = matrix.indexOf('waitForRouteDomSettled');
    const sample = matrix.indexOf('const geometry = await page.evaluate(geometryProbe)');
    expect(settle).toBeGreaterThan(-1);
    expect(dom).toBeGreaterThan(settle);
    expect(sample).toBeGreaterThan(dom);
  });

  it('binds the heading-stack census to settled font, theme, and lockup state', () => {
    const matrix = between(wave1Source, 'for (const state of states)', 'await context.close()');
    const visualReady = matrix.indexOf('waitForVisualCensusSettled');
    const sample = matrix.indexOf('const geometry = await page.evaluate(geometryProbe)');
    expect(visualReady).toBeGreaterThan(-1);
    expect(sample).toBeGreaterThan(visualReady);
    expect(matrix).toContain("assertion: 'browser:redesigned_heading_stack'");
  });

  it('uses no fixed sleep or retry as a readiness signal', () => {
    const matrix = between(wave1Source, 'for (const state of states)', 'await context.close()');
    expect(matrix).toContain('readinessAttempts: 1');
    expect(matrix).not.toContain('waitForTimeout');
    expect(matrix).not.toMatch(/setTimeout\s*\(/u);
    expect(matrix).not.toMatch(/retry|retries/iu);
  });
});

describe('NYAY-26 NYAY-5 producer integration contract', () => {
  it('imports the shared authoritative readiness seam', () => {
    expect(nyay5Source).toContain("from './lib/browser-response-readiness.mjs'");
    for (const symbol of [
      'armCanonicalReadiness',
      'settleCanonicalReadiness',
      'waitForRouteDomSettled',
      'waitForVisualCensusSettled',
    ]) {
      expect(nyay5Source).toContain(symbol);
    }
  });

  it('arms exact session and profile authority before S-10 navigation', () => {
    const probe = between(nyay5Source, 'async function completeProfileProbe', 'async function promptAndRoutingProbe');
    const arm = probe.indexOf('const s10Readiness = armCanonicalReadiness');
    const navigation = probe.indexOf("page.goto(`${WEB}/s-10?section=personal`");
    expect(arm).toBeGreaterThan(-1);
    expect(navigation).toBeGreaterThan(arm);
    expect(probe).toContain("kind: 'session'");
    expect(probe).toContain("kind: 'profile'");
  });

  it('settles S-10 authority and route DOM before sampling the profile city field', () => {
    const probe = between(nyay5Source, 'async function completeProfileProbe', 'async function promptAndRoutingProbe');
    const settle = probe.indexOf('settleCanonicalReadiness(s10Readiness)');
    const dom = probe.indexOf('waitForRouteDomSettled');
    const city = probe.indexOf("page.locator('#profile-personal-city')");
    expect(settle).toBeGreaterThan(-1);
    expect(dom).toBeGreaterThan(settle);
    expect(city).toBeGreaterThan(dom);
    expect(probe).not.toContain('waitForTimeout');
  });

  it('requires canonical OTP-state settlement before S-05 or S-09 controls are sampled', () => {
    expect(nyay5Source).toContain('const otpRouteReadiness = armCanonicalReadiness');
    expect(nyay5Source).toContain("requirements: [{ kind: 'otpState' }]");
    expect(nyay5Source).toContain('settleCanonicalReadiness(otpRouteReadiness)');
    expect(nyay5Source).toContain("waitForRouteDomSettled(page, '/s-05'");
    expect(nyay5Source).toContain("waitForRouteDomSettled(page, '/s-09'");
  });

  it('binds every visual contract row to settled font, theme, and lockup state', () => {
    const visual = between(nyay5Source, 'async function recordVisualContract', 'async function resetOtp');
    expect(visual).toContain('await waitForVisualCensusSettled(page, {');
    expect(visual).toContain("assertion: 'browser:redesigned_heading_stack'");
    expect(visual).toContain('expectedTheme:');
    expect(visual).toContain('requireRevisionLLockup:');
    expect(visual).not.toContain('waitForTimeout');
  });

  it('executes the seeded variance proof once without a retry path', () => {
    expect(nyay5Source).toContain('runSeededHeadingStackVariance({ attempts: 1 })');
    expect(nyay5Source).toContain("legacyOutcome === 'FAIL_EARLY_SAMPLE'");
    expect(nyay5Source).toContain("settledOutcome === 'PASS'");
    expect(nyay5Source).not.toContain('NYAY26_READINESS_RETRY');
  });
});
