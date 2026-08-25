import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const runner = readFileSync(resolve('scripts/wave4-reporting-e2e.mjs'), 'utf8');
const workflow = readFileSync(resolve('../.github/workflows/wave4-private-reporting-gate.yml'), 'utf8');

describe('Wave 4 private reporting browser authority contract', () => {
  it('uses a distinct hashed-only student bearer and validates its exact server projection', () => {
    expect(runner).toContain("process.env.WAVE4_E2E_STUDENT_SESSION_TOKEN");
    expect(runner).toContain('WAVE4_E2E_STUDENT_SESSION_TOKEN with at least 32 characters is required');
    expect(runner).toContain("name: COOKIE, value: STUDENT_SESSION_TOKEN");
    expect(runner).toContain("path: '/'");
    expect(runner).toContain('httpOnly: true');
    expect(runner).toContain("sameSite: 'Lax'");
    expect(runner).toContain('validWave4StudentSession(body, ACTOR_A)');
  });

  it('keeps negative and cross-user claims probes cookie-free', () => {
    expect(runner).toContain('async function cookieFreeRequestContext()');
    expect(runner).toContain('const negativeContext = await cookieFreeRequestContext();');
    expect(runner).toContain('const crossUserContext = await cookieFreeRequestContext();');
    expect(runner.indexOf('await negativeApiMatrix(browser);')).toBeLessThan(
      runner.indexOf('await positiveJourney(browser);'),
    );
  });

  it('authenticates every private S-86/S-87 browser context without weakening the route guard', () => {
    expect(runner).toContain('async function authenticatedStudentContext(browser, options = {})');
    expect(runner).toContain("failureStage = 'positive_session';");
    expect(runner).toContain("failureStage = `geometry_session_${width}x${height}_${theme}`;");
    expect(runner).not.toContain("headers: claims(),\n    status: 200");
  });

  it('emits only privacy-safe failure class, stage, and pathname diagnostics', () => {
    expect(runner).toContain('failureClass: safeFailureClass(error)');
    expect(runner).toContain('failureStage');
    expect(runner).toContain('currentPath: safeCurrentPath()');
    expect(runner).toContain("new Set(['/s-03', '/s-86', '/s-87']).has(pathname)");
    expect(runner).not.toContain('report.failures.push(String(error))');
    expect(runner).not.toContain('message: error.message');
  });
});

describe('Wave 4 CI failure diagnostic artifact contract', () => {
  it('generates and seeds a separate student token without logging it', () => {
    expect(workflow).toContain('"WAVE4_E2E_STUDENT_SESSION_TOKEN",');
    expect(workflow).toContain('Generated seven isolated credentials; raw values were not logged');
    expect(workflow).toContain('"WAVE4_E2E_STUDENT_SESSION_TOKEN",\n              "WAVE4_E2E_SAFETY_SESSION_TOKEN"');
  });

  it('uploads only the sanitized reporting result when the producer fails', () => {
    expect(workflow).toContain('name: Upload privacy-safe S-86/S-87 failure diagnostic');
    expect(workflow).toContain('if: ${{ failure() }}');
    expect(workflow).toContain('name: wave4-reporting-failure-diagnostic');
    expect(workflow).toContain('path: ${{ github.workspace }}/test-results/wave4-browser/results.json');
    expect(workflow).toContain('if-no-files-found: error');
    expect(workflow).toContain('include-hidden-files: false');
  });
});
