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

  it('mounts visual S-05 and S-09 only from real server-issued pending flows', () => {
    const provision = sourceBetween('const requirePendingFlowCookies', 'try {');
    const visualMatrix = sourceBetween(
      'try {',
      'const context = await browser.newContext({ viewport: { width: 390',
    );

    expect(provision).toContain("request.post(`${apiBase}/api/v1/auth/student/login/otp/start`");
    expect(provision).toContain("request.post(`${apiBase}/api/v1/auth/student/register`");
    expect(provision).toContain("request.get(`${apiBase}/api/v1/auth/student/otp/state`");
    expect(provision).toContain("stateBody?.status !== 'pending'");
    expect(provision).toContain('stateBody?.purpose !== purpose');
    expect(provision).toContain("cookie.name === 'nyayone_otp_flow'");
    expect(provision).toContain("process.env.V34_VISUAL_SIGNUP_MOBILE ?? '9000000043'");
    expect(provision).not.toContain('Date.now()');
    expect(provision).not.toContain("page.route('**/api/v1/auth/student/otp/state'");
    expect(visualMatrix).toContain('const visualOtpFlowCookies = await provisionVisualOtpFlows()');
    expect(visualMatrix).toContain("number === 5 ? visualOtpFlowCookies.login");
    expect(visualMatrix).toContain("number === 9 ? visualOtpFlowCookies.signup");
    expect(visualMatrix).toContain('await createPendingVisualContext(');
    expect(visualMatrix).not.toContain("page.route('**/api/v1/auth/student/otp/state'");
  });

  it('never mixes an authenticated session with the isolated S-05/S-09 pending-flow contexts', () => {
    const isolatedFactory = sourceBetween(
      'const createPendingVisualContext',
      'try {',
    );
    const visualMatrix = sourceBetween(
      'try {',
      'const context = await browser.newContext({ viewport: { width: 390',
    );

    expect(isolatedFactory).toContain('await browser.newContext');
    expect(isolatedFactory).toContain('await isolated.addCookies(flowCookies)');
    expect(isolatedFactory).toContain("cookie.name === 'nyayone_session'");
    expect(isolatedFactory).toContain("installedCookies[0]?.name !== 'nyayone_otp_flow'");
    expect(isolatedFactory).toContain('visual OTP context mixed session and pending-flow authority');
    expect(isolatedFactory).not.toContain('/api/v1/auth/student/session');
    expect(isolatedFactory).not.toContain('waitForTimeout');
    expect(visualMatrix).toContain('await context.addCookies(authenticatedCookies)');
    expect(visualMatrix).toContain('await createPendingVisualContext(');
    expect(visualMatrix).toContain('otpStateRequestCount');
    expect(visualMatrix).toContain("request.method() === 'GET'");
    expect(visualMatrix).toContain("'/api/v1/auth/student/otp/state'");
    expect(visualMatrix).toContain("getByLabel('Six digit code').waitFor({ state: 'visible' })");
    expect(visualMatrix).toContain('otpStateRequestCount < 1');
    expect(visualMatrix).not.toContain('waitForTimeout');
    expect(visualMatrix).not.toContain('await context.addCookies(pendingFlowCookies)');
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

  it('proves Change cancels authority before a fresh S-04 to S-05 to S-07 login', () => {
    const login = sourceBetween('const loginCalls = []', 'await context.close()');

    expect(login).toContain("page.route('**/api/v1/auth/student/otp/cancel'");
    expect(login).toContain("route.request().postDataJSON()");
    expect(login).toContain('await route.fetch()');
    expect(login).toContain("getByRole('button', { name: 'Change persona', exact: true })");
    expect(login).toContain("pathWhileCancelResponseDeferred === '/s-05'");
    expect(login).toContain("cancelRequest?.method === 'POST'");
    expect(login).toContain("JSON.stringify(cancelRequest?.body) === '{}'");
    expect(login).toContain("pathAfterCancel === '/s-03'");
    expect(login).toContain('capturedFlowCookie');
    expect(login).toContain('cancelledCode');
    expect(login).toContain('cancelledVerify.status() === 401');
    expect(login).toContain('await page.waitForFunction(() => {');
    expect(login).toContain("candidate.textContent?.trim() === 'Resend Code'");
    expect(login).toContain('button.disabled === false');
    expect(login).not.toContain('waitForTimeout');
    expect(login).toContain("await page.waitForURL('**/s-04')");
    expect(login).toContain("await page.waitForURL('**/s-05')");
    expect(login).toContain("await page.waitForURL('**/s-07')");
  });

  it('preserves the exact 137-row inventory while enriching the existing lifecycle row', () => {
    expect(runner.match(/\brecord\(/gu)).toHaveLength(17);
    expect(runner).toContain('number <= 10');
    expect(runner).toContain("for (const theme of ['light', 'dark'])");
    expect(runner).toContain("{ name: 'mobile', width: 390, height: 844 }");
    expect(runner).toContain("{ name: 'desktop', width: 1440, height: 900 }");
    expect(runner).toContain("record('login_otp_server_lifecycle'");
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
