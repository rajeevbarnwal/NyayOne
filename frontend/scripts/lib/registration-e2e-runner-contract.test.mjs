import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const runner = readFileSync(resolve('scripts/registration-e2e.mjs'), 'utf8');

function sourceBetween(start, end) {
  return runner.slice(runner.indexOf(start), runner.indexOf(end));
}

describe('legacy registration browser runner contract', () => {
  it('fills only the current S-08 identity and separate-consent controls', () => {
    const fixture = sourceBetween(
      'async function fillBase',
      '// Explicit negative/boundary cases.',
    );

    for (const label of [
      'FIRST NAME',
      'MIDDLE NAME',
      'LAST NAME',
      'MOBILE NUMBER',
      'DATE OF BIRTH',
    ]) {
      expect(fixture).toContain(`getByLabel('${label}'`);
    }
    expect(fixture).toContain("getByRole('checkbox', { name: 'I accept the Terms.', exact: true })");
    expect(fixture).toContain("getByRole('checkbox', { name: 'I acknowledge the Privacy Notice.', exact: true })");

    for (const retiredLabel of [
      'INSTITUTIONAL EMAIL',
      'COLLEGE OR UNIVERSITY',
      'YEAR OF STUDY',
      'enrolled in, or applying to',
      'accept the terms and DPDP',
    ]) {
      expect(fixture).not.toContain(retiredLabel);
    }
  });

  it('still supplies academic details only after verified registration reaches S-10', () => {
    const fullJourney = sourceBetween(
      '// Full v3.4 S-08 -> server OTP S-09 -> S-10 backend profile persistence.',
      '// v3.4 S-06 recovery is mobile/OTP based and server-authoritative.',
    );

    expect(fullJourney).toContain("registrationResponse.status() === 202");
    expect(fullJourney).toContain("registrationResult?.status === 'accepted'");
    expect(fullJourney).toContain("registrationResult?.next === 'otp'");
    expect(fullJourney).not.toContain("registrationResult?.status === 'pending'");
    expect(fullJourney).toContain("await page.waitForURL('**/s-07')");
    expect(fullJourney).toContain("getByRole('button', { name: 'Complete Profile' })");
    expect(fullJourney).toContain("await page.waitForURL('**/s-10?section=personal')");
    expect(fullJourney).toContain("await page.waitForURL('**/s-10?section=academic')");
    expect(fullJourney).toContain("getByLabel('Institutional email').fill(qaPii.email)");
    expect(fullJourney).toContain("PATCH /api/v1/student/profile/personal");
    expect(fullJourney).toContain("PATCH /api/v1/student/profile/academic");
    expect(fullJourney).toContain("statusResult.body?.status === 'in_review'");
    expect(fullJourney).toContain("record('protected_calls_use_server_actor'");
  });

  it('expects successful recovery to retire the flow and return to S-04', () => {
    const recovery = sourceBetween(
      '// v3.4 S-06 recovery is mobile/OTP based and server-authoritative.',
      '// Responsive/theme and icon-tooltip contract matrix.',
    );

    expect(recovery).toContain("await page.waitForURL('**/s-04')");
    expect(recovery).toContain("getByRole('heading', { name: 'Sign in' })");
    expect(recovery).not.toContain('Recovery verified. You may now sign in again.');
    expect(recovery).toContain("calls.some((r) => r.includes('POST /api/v1/auth/student/recovery/complete'))");
    expect(recovery).toContain("await recoveryCode.waitFor({ state: 'detached' })");
  });

  it('waits for and allows only read-only session discovery on the retired auth prototype', () => {
    const retiredBoundary = sourceBetween(
      '// Retired /auth/student prototype must fail closed',
      "record('browser_page_errors'",
    );

    expect(retiredBoundary).toContain('const sessionDiscoveryRequest = page.waitForRequest');
    expect(retiredBoundary).toContain('await sessionDiscoveryRequest');
    expect(retiredBoundary).toContain('calls.length > 0');
    expect(retiredBoundary).toMatch(
      /calls\.every\([\s\S]*\(call\) => call === 'GET \/api\/v1\/auth\/student\/session'/u,
    );
    expect(retiredBoundary).not.toContain('calls.length === 0');
    expect(retiredBoundary).toContain('sessionDiscoveryOnly');
    expect(retiredBoundary).toContain("await secureLink.getAttribute('href') === '/s-03'");
    expect(retiredBoundary).toContain("await page.locator('input').count() === 0");
  });
});
