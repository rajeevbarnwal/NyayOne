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

  it('observes the post-401 resend control by its accessible contract, not a retired class', () => {
    const fullJourney = sourceBetween(
      '// Full v3.4 S-08 -> server OTP S-09 -> S-10 backend profile persistence.',
      '// v3.4 S-06 recovery is mobile/OTP based and server-authoritative.',
    );
    expect(fullJourney).toContain(
      "page.getByRole('button', { name: 'Resend Code', exact: true }).count() === 1",
    );
    expect(fullJourney).not.toContain("page.locator('.v34-textlink').count() === 1");
  });

  it('waits on the approved Revision L S-03 heading before the privacy-safe capture', () => {
    const fullJourney = sourceBetween(
      '// Full v3.4 S-08 -> server OTP S-09 -> S-10 backend profile persistence.',
      '// v3.4 S-06 recovery is mobile/OTP based and server-authoritative.',
    );
    expect(fullJourney).toContain(
      "getByRole('heading', { name: 'Where would you like to begin?', exact: true })",
    );
    expect(fullJourney).not.toContain("name: 'Welcome. Let us get you in.'");
  });

  it('exercises the current S-08 DOB help tooltip in the responsive matrix', () => {
    const matrix = sourceBetween(
      '// Responsive/theme and icon-tooltip contract matrix.',
      '// Retired /auth/student prototype must fail closed',
    );
    expect(matrix).toMatch(
      /getByRole\('button',\s*\{\s*name: 'More information about DATE OF BIRTH',\s*exact: true,?\s*\}\)/u,
    );
    expect(matrix).toContain(
      "/^Required for eligibility; must be on or before \\d{4}-\\d{2}-\\d{2}\\.$/u.test(tooltipText)",
    );
    expect(matrix).not.toContain('More information about MOBILE NUMBER');
    expect(matrix).not.toContain('Exactly 10 digits. The one time code is sent here.');
  });

  it('expects successful recovery to retire the flow, acknowledge R2 success and return to S-04', () => {
    const recovery = sourceBetween(
      '// v3.4 S-06 recovery is mobile/OTP based and server-authoritative.',
      '// Responsive/theme and icon-tooltip contract matrix.',
    );

    expect(recovery).toContain("await page.waitForURL('**/s-04')");
    expect(recovery).toContain("getByRole('heading', { name: 'Sign in' })");
    expect(recovery).not.toContain('Recovery verified. You may now sign in again.');
    expect(recovery).toContain("calls.some((r) => r.includes('POST /api/v1/auth/student/recovery/complete'))");
    expect(recovery).toContain("await recoveryCode.waitFor({ state: 'detached' })");
    expect(recovery).toContain("getByLabel('Registered mobile number', { exact: true })");
    expect(recovery).toContain("getByRole('button', { name: 'Send recovery code', exact: true })");
    expect(recovery).toContain("getByRole('heading', { name: 'Your account is ready.', exact: true })");
    expect(recovery).toContain("getByRole('button', { name: 'Back to sign in', exact: true }).click()");
    for (const id of ['recovery_server_start', 'recovery_server_verify', 'recovery_server_complete', 'recovery_no_email_redirect']) expect(recovery).toContain(`record('${id}'`);
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
