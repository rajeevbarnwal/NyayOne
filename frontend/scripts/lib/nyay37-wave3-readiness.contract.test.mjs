/** NYAY-37 enforced readiness contracts, retained from the accepted tests-first baseline. */
import { readFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';

const producer = readFileSync(new URL('../credential-e2e.mjs', import.meta.url), 'utf8');
const fixtureUrl = new URL('./nyay37-wave3-readiness-variance-fixture.mjs', import.meta.url);
const fixtureSource = existsSync(fixtureUrl) ? readFileSync(fixtureUrl, 'utf8') : '';

function section(start, end) {
  const first = producer.indexOf(start);
  const last = producer.indexOf(end, first + start.length);
  expect(first, `existing function ${start}`).toBeGreaterThanOrEqual(0);
  expect(last, `existing function boundary ${end}`).toBeGreaterThan(first);
  return producer.slice(first, last);
}

function before(source, first, second) {
  expect(source.indexOf(first), `missing readiness step: ${first}`).toBeGreaterThanOrEqual(0);
  expect(source.indexOf(second), `missing later step: ${second}`).toBeGreaterThan(source.indexOf(first));
}

describe('NYAY-37 Wave-3 integration RED contracts', () => {
  it('imports the already-approved response, route and visual readiness seam', () => {
    expect(producer).toMatch(/import\s*\{[^}]*armCanonicalReadiness[^}]*\}\s*from ['"]\.\/lib\/browser-response-readiness\.mjs['"]/u);
    for (const name of ['settleCanonicalReadiness', 'waitForRouteDomSettled', 'waitForVisualCensusSettled']) expect(producer).toContain(name);
  });

  for (const [label, start, end, navigation] of [
    ['functional', 'async function positiveJourney(', 'async function geometryMatrix(', 'await page.goto'],
    ['geometry', 'async function geometryMatrix(', 'async function assertGeometry(', 'await page.goto'],
    ['fresh context', 'async function freshContextPersistence(', 'async function main(', 'await page.goto'],
  ]) {
    it(`${label}: arms canonical authority before first private navigation`, () => {
      const body = section(start, end);
      before(body, 'armCanonicalReadiness(', navigation);
      expect(body).toMatch(/kind:\s*['"]session['"]/u);
    });
    it(`${label}: settles responses and observed route before private sampling`, () => {
      const body = section(start, end);
      before(body, 'settleCanonicalReadiness(', 'waitForRouteDomSettled(');
      const sample = label === 'geometry' ? 'await assertGeometry(' : 'await page.getByRole';
      before(body, 'waitForRouteDomSettled(', sample);
    });
  }

  it('declares server-derived session/profile/OTP-state requirements explicitly, not client authority', () => {
    for (const kind of ['session', 'profile', 'otpState']) expect(producer).toMatch(new RegExp(`kind:\\s*['"]${kind}['"]`, 'u'));
    expect(producer).toContain('settleCanonicalReadiness(');
  });

  it('settles geometry fonts/theme/lockup before metrics and screenshots', () => {
    const body = section('async function assertGeometry(', 'async function freshContextPersistence(');
    before(body, 'await waitForVisualCensusSettled(', 'const metrics = await page.evaluate');
    before(body, 'await waitForVisualCensusSettled(', 'await page.screenshot(');
    expect(body).toMatch(/expectedTheme:\s*theme/u);
    expect(body).toContain('requireRevisionLLockup:');
  });

  it('does not substitute networkidle, fixed sleeps or retries for authoritative readiness', () => {
    expect(producer).not.toMatch(/waitUntil:\s*['"]networkidle['"]|waitForTimeout\s*\(|setTimeout\s*\(/u);
    expect(producer).toContain('readinessAttempts: 1');
    expect(producer).not.toMatch(/READINESS_RETRY|readinessRetries/u);
  });

  it('arms an exact query-free credential-token mutation observer and settles its response', () => {
    expect(producer).not.toContain("response.url().includes('/verification-tokens')");
    expect(producer).toContain('await tokenResponse.finished()');
    expect(producer).toMatch(/search\s*===\s*['"]['"]/u);
  });

  it('records only canonical readiness diagnostics, without URL/query or actor payloads', () => {
    expect(producer).toContain('READINESS_DIAGNOSTIC_FIELDS');
    expect(producer).toContain('readinessDiagnostics');
    expect(producer).not.toContain('queryKeys:');
    expect(producer).not.toMatch(/readinessDiagnostics[^;]*\.json\(\)/u);
  });

  it('executes a seeded Wave-3 variance proof exactly once in the actual producer', () => {
    expect(producer).toContain('runSeededWave3ReadinessVariance({ attempts: 1 })');
    expect(producer).toContain("legacyOutcome === 'FAIL_EARLY_SAMPLE'");
    expect(producer).toContain("settledOutcome === 'PASS'");
  });
});

describe('NYAY-37 deterministic event-driven variance RED contracts', () => {
  async function implementation() {
    expect(existsSync(fixtureUrl), 'NYAY37_SEEDED_WAVE3_VARIANCE_FIXTURE_MISSING').toBe(true);
    return import(fixtureUrl.href);
  }
  it('cannot sample before canonical responses, route, DOM, fonts and theme settle', async () => {
    const { runSeededWave3ReadinessVariance } = await implementation();
    const result = await runSeededWave3ReadinessVariance({ attempts: 1 });
    expect(result).toMatchObject({ attempts: 1, legacyOutcome: 'FAIL_EARLY_SAMPLE', settledOutcome: 'PASS' });
    const sequence = result.events;
    for (const [first, second] of [['arm', 'navigate'], ['navigate', 'response-finished'], ['response-finished', 'route-dom'], ['route-dom', 'font-theme-lockup'], ['font-theme-lockup', 'sample']]) {
      expect(sequence.indexOf(first)).toBeGreaterThanOrEqual(0);
      expect(sequence.indexOf(second)).toBeGreaterThan(sequence.indexOf(first));
    }
  });
  it('refuses a retry budget and contains no clock-sleep readiness', async () => {
    const { runSeededWave3ReadinessVariance } = await implementation();
    await expect(Promise.resolve().then(() => runSeededWave3ReadinessVariance({ attempts: 2 }))).rejects.toThrow();
    expect(fixtureSource).not.toMatch(/setTimeout|waitForTimeout/u);
  });
  it('executes three independent deterministic seeded runs with identical event outcomes', async () => {
    const { runSeededWave3ReadinessVariance } = await implementation();
    const runs = [];
    for (let n = 0; n < 3; n += 1) runs.push(await runSeededWave3ReadinessVariance({ attempts: 1 }));
    expect(runs).toHaveLength(3);
    expect(runs.every(r => r.settledOutcome === 'PASS' && r.attempts === 1)).toBe(true);
    expect(runs[1]).toEqual(runs[0]);
    expect(runs[2]).toEqual(runs[0]);
  });
});

describe('NYAY-37 RED-phase preservation', () => {
  it('keeps the anonymous oracle before canonical student authentication', () => {
    before(producer, 'await runApiNegativeMatrix(context.request);', 'await authenticateStudent(context);');
  });
  it('retains all three assertion group counts and the fatal failure exit', () => {
    for (const group of ['functional', 'negative', 'geometry']) {
      expect(producer).toContain(`${group}Passed: report.${group}.filter`);
      expect(producer).toContain(`${group}Failed: report.${group}.filter`);
    }
    expect(producer).toContain('if (report.failures.length)');
    expect(producer).toContain('process.exit(1)');
  });
  it('keeps the existing runner-contract oracle byte-identical', () => {
    const bytes = readFileSync(new URL('./credential-e2e-runner-contract.test.mjs', import.meta.url));
    expect(createHash('sha256').update(bytes).digest('hex')).toBe('a0f25ddc9ce49f6fb992634a8c43d9f4572626a3d71da53549dd3a905e835eea');
  });
});
