import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { V34Register, splashDestination } from './V34Screens';
import { normalizeOtpDigits } from '../lib/otpInput';

describe('S-01 server-session bootstrap', () => {
  it('uses the approved NyayOne name and exact display type stack on every redesigned shell', () => {
    const authSource = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    const shellSource = readFileSync(join(process.cwd(), 'src/components/shell/AppShell.tsx'), 'utf8');
    const styles = readFileSync(join(process.cwd(), 'src/styles/student-v34.css'), 'utf8');
    const continuationShell = shellSource.slice(shellSource.indexOf('function V34Brand'));

    expect(authSource).not.toContain('>LegalSaathi<');
    expect(authSource).toContain('<b>NyayOne</b>');
    expect(authSource).toContain('id="S-01-title">NyayOne</h1>');
    expect(continuationShell).not.toContain('LegalSaathi');
    expect(continuationShell).toContain('aria-label="NyayOne home"');
    expect(continuationShell).toContain('<b>NyayOne</b>');
    expect(continuationShell).toContain('data-tip="Ask NyayOne"');
    expect(styles).toContain('--v34-display: Aptos, Calibri, Carlito, system-ui, sans-serif;');
    expect(styles).toContain('.v34-screen h1, .v34-screen h2 { font-family: var(--v34-display); }');
    expect(styles).not.toContain("--v34-display: 'Space Grotesk'");
  });

  it('uses the supplied brand mark and non-focusable SVG icons instead of text glyphs', () => {
    const authSource = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    const shellSource = readFileSync(join(process.cwd(), 'src/components/shell/AppShell.tsx'), 'utf8');
    const continuationShell = shellSource.slice(shellSource.indexOf('function V34ShellIcon'));
    const mark = readFileSync(join(process.cwd(), 'public/brand/nyayone-mark.svg'), 'utf8');

    expect(mark).toContain('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">');
    expect(authSource).toContain('src="/brand/nyayone-mark.svg"');
    expect(continuationShell).toContain('src="/brand/nyayone-mark.svg"');
    expect(authSource).not.toMatch(/[§▣¶⌂]/u);
    expect(continuationShell).not.toContain('{item.glyph}');
    expect(authSource).toContain('tabIndex={-1} focusable="false"');
    expect(continuationShell).toContain('tabIndex={-1} focusable="false"');
  });

  it('never routes while session authority is pending or unavailable', () => {
    expect(splashDestination('pending', false)).toBeNull();
    expect(splashDestination('pending', true)).toBeNull();
    expect(splashDestination('unavailable', false)).toBeNull();
  });

  it('routes only after the canonical session phase settles', () => {
    expect(splashDestination('authenticated', false)).toBe('/s-07');
    expect(splashDestination('authenticated', true)).toBe('/s-07');
    expect(splashDestination('anonymous', false)).toBe('/s-02');
    expect(splashDestination('anonymous', true)).toBe('/s-03');
  });

  it('uses only the inherited allowlisted onboarding preference key', () => {
    const source = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    expect(source).toContain("const ONBOARDING_SEEN_KEY = 'ls-onboarding-seen'");
    expect(source).not.toContain("const ONBOARDING_SEEN_KEY = 'legalsaathi.student.onboarding.v34'");
  });

  it('enters S-07 after signup and restores only a proven login reauth route', () => {
    const source = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    const verifyScreen = source.slice(
      source.indexOf('function V34OtpChallenge'),
      source.indexOf('export function V34ProfileStep1'),
    );
    expect(verifyScreen).not.toContain("nav('/s-10'");
    expect(verifyScreen).not.toContain("nav('/s-16'");
    expect(verifyScreen).not.toContain('getStudentSession()');
    expect(verifyScreen).toContain("purpose === 'login'");
    expect(verifyScreen).toContain('resolvedProfileReauthResumeRoute()');
    expect(verifyScreen).toContain("nav(resumeRoute ?? '/s-07', { replace: true })");
  });

  it('keeps S-03 through S-06 passwordless and routes login OTP through S-05', () => {
    const source = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    const authBoundary = source.slice(
      source.indexOf('export function V34AuthGate'),
      source.indexOf('export function V34VerifiedHome'),
    );
    const otpBoundary = source.slice(
      source.indexOf('function V34OtpChallenge'),
      source.indexOf('export function V34ProfileStep1'),
    );
    const routeMap = readFileSync(join(process.cwd(), 'src/features/student/screens.tsx'), 'utf8');

    expect(authBoundary.toLowerCase()).not.toContain('password');
    expect(authBoundary).not.toContain("nav('/s-09')");
    expect(authBoundary).toContain("await startLoginOtp(mobile)");
    expect(authBoundary).toContain("nav('/s-05')");
    expect(otpBoundary).toContain("flow.purpose !== purpose");
    expect(otpBoundary).toContain('purpose="login"');
    expect(otpBoundary).toContain('purpose="signup"');
    expect(routeMap).toMatch(/'S-05': V34LoginOtp/);
    expect(routeMap).toMatch(/'S-06': V34AccountRecovery/);
    expect(routeMap).toMatch(/'S-09': V34OtpVerify/);
  });

  it('normalizes a formatted six-digit clipboard payload before native maxlength truncation', () => {
    expect(normalizeOtpDigits('12a34 56')).toBe('123456');
    expect(normalizeOtpDigits('1234567')).toBe('123456');

    const source = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    const otpBoundary = source.slice(
      source.indexOf('function V34OtpChallenge'),
      source.indexOf('export function V34ProfileStep1'),
    );
    expect(otpBoundary).toContain('onPaste={(event) => {');
    expect(otpBoundary).toContain('event.preventDefault()');
    expect(otpBoundary).toContain("event.clipboardData.getData('text')");
    expect(otpBoundary).toContain('normalizeOtpDigits(event.target.value)');
  });

  it('collects Terms and Privacy Notice acknowledgements separately on S-08', () => {
    const source = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    const registerScreen = source.slice(
      source.indexOf('export function V34Register'),
      source.indexOf('function V34OtpChallenge'),
    );

    expect(registerScreen).toContain('termsAccepted');
    expect(registerScreen).toContain('privacyNoticeAcknowledged');
    expect(registerScreen).toContain('I accept the Terms');
    expect(registerScreen).toContain('I acknowledge the Privacy Notice');
    expect(registerScreen).not.toContain('I accept the terms and DPDP privacy notice');
    expect(registerScreen).not.toContain('lawDeclaration');
  });

  it('marks every S-08 identity and legal-consent control as programmatically required', () => {
    const html = renderToStaticMarkup(
      createElement(MemoryRouter, null, createElement(V34Register)),
    );
    for (const id of ['v34-first', 'v34-last', 'v34-mobile', 'v34-dob', 'v34-terms', 'v34-privacy']) {
      expect(html).toMatch(new RegExp(`<input(?=[^>]*id="${id}")(?=[^>]*required="")[^>]*>`));
    }
    expect(html).toContain('id="s08-error-summary"');
    expect(html).toContain('tabindex="-1"');
    const source = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    expect(source).toContain("terms: 'v34-terms'");
    expect(source).toContain("privacy: 'v34-privacy'");
    expect(source).toContain('errorSummaryRef.current?.focus()');
  });

  it('keeps every S-07 rendering branch labelled by an in-tree heading', () => {
    const source = readFileSync(join(process.cwd(), 'src/features/student/auth/V34Screens.tsx'), 'utf8');
    const prompt = source.slice(
      source.indexOf('export function V34VerifiedHome'),
      source.indexOf('export function V34Register'),
    );
    expect(prompt.match(/id="S-07-title"/g)).toHaveLength(3);
  });
});
