import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, type StudentSessionPhase } from '../../../app/authContext';
import type { OtpFlowState } from '../lib/registrationApi';
import { isValidOtpInput, normalizeOtpDigits } from '../lib/otpInput';

const otpHook = vi.hoisted(() => ({
  state: null as OtpFlowState | null,
  loading: false,
  loadError: false,
  adopt: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock('../lib/useOtpFlowState', () => ({ useOtpFlowState: () => otpHook }));

import { V34LoginOtp, V34OtpVerify, otpVerificationFailureMessage } from './V34Screens';
import { RegistrationApiError } from '../lib/registrationApi';

const MOBILE_MASK = '••••••3210';
const EMAIL_MASK = 's•••••@example.test';
const source = readFileSync('src/features/student/auth/V34Screens.tsx', 'utf8');
const styles = readFileSync('src/styles/student-option321.css', 'utf8');
const challenge = source.slice(source.indexOf('function V34OtpChallenge('), source.indexOf('export function V34ProfileStep1('));

function pending(purpose: 'login' | 'signup', destinationMasked = MOBILE_MASK): OtpFlowState {
  return {
    status: 'pending', purpose, destinationMasked,
    attemptsLeft: 3, expiresInSeconds: 272, resendInSeconds: 17,
    lockedForSeconds: 0, resendAllowed: false,
  };
}

function render(purpose: 'login' | 'signup' = 'login', phase: StudentSessionPhase = 'anonymous'): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <AuthProvider studentSession={{ phase, refresh: vi.fn(async () => undefined) }}>
        {purpose === 'login' ? <V34LoginOtp theme="light"/> : <V34OtpVerify theme="light"/>}
      </AuthProvider>
    </MemoryRouter>,
  );
}

function footer(html: string): string {
  const content = html.match(/<footer class="v321-legal">(.*?)<\/footer>/su)?.[1];
  expect(content).toBeDefined();
  return content ?? '';
}

function assertNoAccountContext(html: string): void {
  expect(html).not.toContain('data-nyayone-create-context');
  expect(html).not.toContain('Joining as');
  expect(html).not.toContain('aria-label="Change persona"');
  expect(html).not.toContain('English');
}

beforeEach(() => {
  otpHook.state = pending('login');
  otpHook.loading = false;
  otpHook.loadError = false;
  vi.clearAllMocks();
});

describe('NYAY-48 S-05 Revision L verification alignment', () => {
  it('allows only the S-05 primary icon to shrink like the narrow reference (CSS contract)', () => {
    expect(styles).toMatch(/\[data-screen='S-05'\] \.v321-primary > \.v321-revl-icon\s*\{\s*flex: 0 1 auto;\s*\}/u);
    expect(styles).toContain('flex: 0 0 20px;');
  });

  it('matches the S-05 server-metadata emphasis without changing other screens (CSS contract)', () => {
    expect(styles).toMatch(/\[data-screen='S-05'\] \.v34-kv b\s*\{\s*font-weight: 800;\s*\}/u);
  });

  it.each([MOBILE_MASK, EMAIL_MASK])('omits the account-context controls for a pending login flow (%s)', (mask) => {
    otpHook.state = pending('login', mask);
    const html = render();
    expect(html).toContain('data-screen="S-05"');
    expect(html).toContain('Enter the code');
    assertNoAccountContext(html);
  });

  it.each([MOBILE_MASK, EMAIL_MASK])('omits the account-context controls while restoring a login flow (%s)', (mask) => {
    otpHook.state = pending('login', mask);
    otpHook.loading = true;
    const html = render();
    expect(html).toContain('Checking verification state');
    expect(html).toContain('role="status"');
    assertNoAccountContext(html);
  });

  it('omits the account-context controls while the session boundary is pending', () => {
    assertNoAccountContext(render('login', 'pending'));
  });

  it.each([false, true])('preserves the S-09 account context (loading=%s)', (loading) => {
    otpHook.state = pending('signup');
    otpHook.loading = loading;
    const html = render('signup');
    expect(html).toContain('data-screen="S-09"');
    expect(html).toContain('data-nyayone-create-context=""');
    expect(html).toContain('Joining as <b>Student</b>');
    expect(html).toContain('aria-label="Change persona"');
    expect(html).toContain('English');
  });

  it.each([false, true])('orders the S-05 desktop header before brand panel and main (loading=%s)', (loading) => {
    otpHook.loading = loading;
    const html = render();
    const header = html.indexOf('class="v321-topbar"');
    const brand = html.indexOf('class="v321-brandpanel v321-brandpanel--verification"');
    const main = html.indexOf('id="main-content"');
    expect(header).toBeGreaterThanOrEqual(0);
    expect(brand).toBeGreaterThanOrEqual(0);
    expect(main).toBeGreaterThanOrEqual(0);
    expect(header).toBeLessThan(brand);
    expect(brand).toBeLessThan(main);
  });

  it.each([false, true])('uses the aligned S-09 Revision L reading order (loading=%s)', (loading) => {
    otpHook.state = pending('signup');
    otpHook.loading = loading;
    const html = render('signup');
    const brand = html.indexOf('class="v321-brandpanel v321-brandpanel--verification"');
    const header = html.indexOf('class="v321-topbar"');
    const main = html.indexOf('id="main-content"');
    expect(brand).toBeGreaterThanOrEqual(0);
    expect(header).toBeGreaterThanOrEqual(0);
    expect(main).toBeGreaterThanOrEqual(0);
    expect(header).toBeLessThan(brand);
    expect(brand).toBeLessThan(main);
  });

  it.each([false, true])('renders S-05 legal notices as inert prototype text (loading=%s)', (loading) => {
    otpHook.loading = loading;
    const legal = footer(render());
    expect(legal).toContain('<span>Privacy Notice</span>');
    expect(legal).toContain('<span>Terms</span>');
    expect(legal).toContain('<span>Accessibility</span>');
    expect(legal).not.toMatch(/<(?:a|button|input)\b|\bhref=|\btabindex=|\bcontenteditable=|\brole="(?:link|button)"/iu);
  });

  it.each([false, true])('renders S-09 legal notices as owner-approved inert prototype text (loading=%s)', (loading) => {
    otpHook.state = pending('signup');
    otpHook.loading = loading;
    const legal = footer(render('signup'));
    expect(legal).toContain('<span>Privacy Notice</span>');
    expect(legal).toContain('<span>Terms</span>');
    expect(legal).toContain('<span>Accessibility</span>');
    expect(legal).not.toMatch(/<(?:a|button|input)\b|\bhref=|\btabindex=|\bcontenteditable=|\brole="(?:link|button)"/iu);
  });

  it('includes the prototype hidden label without changing the six-digit accessible input name', () => {
    const html = render();
    expect(html).toMatch(/<span class="sr-only">One-time code<\/span>/u);
    expect(html).toMatch(/<input(?=[^>]*aria-label="Six digit code")(?=[^>]*inputMode="numeric")(?=[^>]*autoComplete="one-time-code")(?=[^>]*maxLength="6")(?=[^>]*value="")[^>]*>/u);
    const otp = html.match(/<label class="v34-otp">(.*?)<\/label>/su)?.[1];
    expect(otp?.match(/<span aria-hidden="true"><\/span>/gu)).toHaveLength(6);
  });

  it('keeps the blank verify control disabled and uses server-provided expiry, cooldown and attempt values', () => {
    const html = render();
    expect(html).toMatch(/<button(?=[^>]*aria-label="Verify and continue")(?=[^>]*disabled="")[^>]*>/u);
    expect(html).toContain('Expires in <b class="v321-mono">04:32</b>');
    expect(html).toContain('Resend in <b class="v321-mono">00:17</b>');
    expect(html).toContain('Tries left <b>3</b>');
    expect(html).toMatch(/<button(?=[^>]*class="v321-secondary")(?=[^>]*disabled="")[^>]*>.*?Resend Code/su);
  });

  it('does not grant resend from a zero display countdown without the server boolean', () => {
    otpHook.state = { ...pending('login'), resendInSeconds: 0, resendAllowed: false };
    expect(render()).toMatch(/<button(?=[^>]*class="v321-secondary")(?=[^>]*disabled="")[^>]*>.*?Resend Code/su);
    otpHook.state = { ...pending('login'), resendInSeconds: 0, resendAllowed: true };
    expect(render()).toMatch(/<button(?=[^>]*class="v321-secondary")(?![^>]*disabled=)[^>]*>.*?Resend Code/su);
  });

  it('preserves six-digit shape, input normalization, pending-purpose and lockout guards (source contract)', () => {
    expect(isValidOtpInput('123456')).toBe(true);
    for (const code of ['', '12345', '1234567', 'abcdef', '123 56']) expect(isValidOtpInput(code)).toBe(false);
    expect(normalizeOtpDigits('12x34 5678')).toBe('123456');
    expect(challenge).toContain("if (!isValidOtpInput(code)) { setStatus('Enter all six digits.'); return; }");
    expect(challenge).toContain("if (flow?.status !== 'pending' || flow.purpose !== purpose)");
    expect(challenge).toContain("disabled={busy || code.length !== 6 || flow?.status !== 'pending' || (flow.expiresInSeconds ?? 0) <= 0 || (flow.attemptsLeft ?? 0) <= 0 || (flow.lockedForSeconds ?? 0) > 0}");
    expect(challenge).toContain('await verifyStudentOtp(code)');
    expect(challenge).toContain('await verifyLoginOtp(code)');
    expect(challenge).toContain('otpFlow.adopt(result)');
    expect(challenge).toContain("nav(resumeRoute ?? '/s-07', { replace: true });");
  });

  it('preserves canonical server-lockout and expired-code messages', () => {
    const locked = { ...pending('login'), attemptsLeft: 0, lockedForSeconds: 60 };
    expect(otpVerificationFailureMessage(new RegistrationApiError(429, 'locked', undefined, locked))).toBe('Too many attempts. Try again in 60 seconds.');
    expect(otpVerificationFailureMessage(new RegistrationApiError(410, 'expired'))).toBe('That code has expired. Request a new code when the server allows it.');
    expect(otpVerificationFailureMessage(new Error('synthetic failure'))).toBe('That code could not be verified. Check all six digits.');
  });

  it.each([
    [MOBILE_MASK, '+91 ••••• ••210', 'Change mobile number'],
    [EMAIL_MASK, EMAIL_MASK, 'Change email address'],
  ])('retains masked %s continuity and the identity-specific change control', (mask, expected, changeLabel) => {
    otpHook.state = pending('login', mask);
    const html = render();
    expect(html).toContain(expected);
    expect(html).toContain(`aria-label="${changeLabel}"`);
    expect(html).toContain('<span>Change</span>');
    expect(challenge).toContain("const backRoute = purpose === 'signup' ? '/s-08' : '/s-04';");
    expect(challenge).toContain('onClick={() => nav(backRoute)}');
  });

  it.each(['student@example.test', '9876543210', 'malformed'])('never renders an unmasked identity (%s)', (identity) => {
    otpHook.state = pending('login', identity);
    const html = render();
    expect(html).not.toContain(identity);
    expect(html).toContain('your sign-in identity');
    expect(challenge).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie/u);
  });
});
