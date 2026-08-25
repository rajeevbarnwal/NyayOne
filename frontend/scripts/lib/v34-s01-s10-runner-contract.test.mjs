import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const runner = readFileSync(resolve('scripts/v34-s01-s10-e2e.mjs'), 'utf8');

function sourceBetween(start, end) {
  const startIndex = runner.indexOf(start);
  return runner.slice(startIndex, runner.indexOf(end, startIndex + start.length));
}

describe('S-01-S-10 Chromium runner source contract', () => {
  it('provisions and installs a canonical server session before private visual mounts', () => {
    const provision = sourceBetween('const provisionLoginStudent', 'try {');
    const visualMatrix = sourceBetween('try {', 'const context = await browser.newContext({ viewport: { width: 390');

    expect(provision).toContain('terms_accepted: true');
    expect(provision).toContain('privacy_notice_acknowledged: true');
    expect(provision).not.toContain('consent: { accepted: true');
    expect(provision).toContain('response.status() !== 202');
    expect(provision).toContain('return cookies');
    expect(visualMatrix).toContain('const authenticatedCookies = await provisionLoginStudent()');
    expect(visualMatrix).toContain('await context.addCookies(authenticatedCookies)');
  });

  it('keeps 44px enforcement exact while recognizing only desktop Revision L legal text links', () => {
    const visualMatrix = sourceBetween(
      'try {',
      'const context = await browser.newContext({ viewport: { width: 390',
    );
    expect(visualMatrix).toContain(
      "allowDesktopLegalTextLinks: viewport.name === 'desktop'",
    );
    expect(visualMatrix).toContain(
      "allowDesktopLegalTextLinks && element.matches('.v321-legal a')",
    );
    expect(visualMatrix).toContain('target.width < 44 || target.height < 44');
    expect(visualMatrix).not.toContain('targetMinimum');
  });

  it('models the current core-only S-08 form and exact accepted projection', () => {
    const registration = sourceBetween(
      "await page.route('**/api/v1/auth/student/register'",
      "await page.goto(`${base}/s-03`)",
    );

    expect(registration).toContain('status: 202');
    expect(registration).toContain("status: 'accepted', next: 'otp'");
    expect(registration).toContain("getByRole('checkbox', { name: 'I accept the Terms.', exact: true })");
    expect(registration).toContain("getByRole('checkbox', { name: 'I acknowledge the Privacy Notice.', exact: true })");
    for (const retiredLabel of [
      "getByLabel('INSTITUTIONAL EMAIL')",
      "getByLabel('COLLEGE OR UNIVERSITY')",
      "getByLabel('YEAR OF STUDY')",
      'enrolled in, or applying to',
    ]) {
      expect(registration).not.toContain(retiredLabel);
    }
    expect(registration).toContain("page.locator('#v34-mobile-error').isVisible()");
    expect(registration).toContain("page.locator('#v34-dob-error').isVisible()");
    expect(registration).toContain("page.locator('#v34-first-error').isVisible()");
    expect(registration).toContain("page.locator('#v34-last-error').isVisible()");
    expect(registration).toContain("mobile9Error === 'Mobile number must be exactly 10 digits.'");
    expect(registration).toContain("mobile11Error === 'Mobile number must be exactly 10 digits.'");
    expect(registration).toContain("futureDobError === 'Enter a valid date of birth that is not in the future.'");
    expect(registration).toContain("name61Error === 'First name must be 60 characters or fewer.'");
    expect(registration).toContain("retiredFieldCount === 0");
  });

  it('follows login through the dedicated S-05 challenge route', () => {
    const login = sourceBetween('const loginCalls = []', 'await context.close()');

    expect(login).not.toContain("getByRole('button', { name: 'Use a one time code' })");
    expect(login).toContain("await page.waitForURL('**/s-05')");
    expect(login).not.toContain("await page.waitForURL('**/s-09')");
  });

  it('samples the exact current S-08 icon tooltip CTA', () => {
    const tooltip = sourceBetween(
      "await page.goto(`${base}/s-08`);\n  const iconActions",
      'await resetOtp();',
    );
    expect(tooltip).toContain(
      "getByRole('button', { name: 'Send one time code', exact: true })",
    );
    expect(tooltip).toContain('item.tip === item.aria');
    expect(tooltip).toContain('item.svg === 1');
    expect(tooltip).not.toContain("await page.goto(`${base}/s-03`)");
    expect(tooltip).not.toContain("querySelectorAll('.v34-iconbtn')");
  });
});
