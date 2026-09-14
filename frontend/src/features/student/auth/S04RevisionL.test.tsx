import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { LoginChannels, cancelStudentOtp } from '../lib/registrationApi';
import { retireStudentOtpPersonaContext, V34LoginForm } from './V34Screens';

describe('NYAY-83 S-04 Revision L sign-in screen', () => {
  const render = (channels: LoginChannels | null = null, initialChannel?: 'mobile' | 'email') => (
    renderToStaticMarkup(<MemoryRouter><V34LoginForm theme="light" channels={channels} initialChannel={initialChannel}/></MemoryRouter>)
  );
  const source = readFileSync('src/features/student/auth/V34Screens.tsx', 'utf8');
  const login = source.slice(source.indexOf('export function V34Login('), source.indexOf('export function V34AccountRecovery'));

  it('orders the desktop header before the benefits panel and main in the reading order', () => {
    const html = render();
    const header = html.indexOf('class="v321-topbar"');
    const benefits = html.indexOf('class="v321-brandpanel"');
    const main = html.indexOf('id="main-content"');
    expect(header).toBeGreaterThanOrEqual(0);
    expect(benefits).toBeGreaterThanOrEqual(0);
    expect(main).toBeGreaterThanOrEqual(0);
    expect(header).toBeLessThan(benefits);
    expect(benefits).toBeLessThan(main);
  });

  it('renders the mobile field label in the approved visible title case', () => {
    const label = render().match(/<label\b[^>]*for="v34-login-mobile"[^>]*>(.*?)<\/label>/su)?.[1];
    expect(label).toBeDefined();
    expect(label?.replace(/<[^>]*>/gu, '')).toBe('Mobile Number');
  });

  it('centres each S-04 channel icon and label with the prototype seven-pixel gap', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    const rule = css.match(/\[data-screen='S-04'\] \.v321-segment button\s*\{([^}]*)\}/u)?.[1];
    expect(rule).toBeDefined();
    expect(rule).toContain('display: inline-flex;');
    expect(rule).toContain('align-items: center;');
    expect(rule).toContain('justify-content: center;');
    expect(rule).toContain('gap: 7px;');
  });

  it('preserves the fail-closed mobile-only view when the projection is absent or disables email', () => {
    const html = render();
    expect(html).toBe(render({ mobile: true, email: false }));
    expect(html).toBe(render({ mobile: true, email: false }, 'email'));
    const emailButton = [...html.matchAll(/<button\b[^>]*>.*?<\/button>/gsu)]
      .map(([button]) => button).find((button) => button.includes('Verified Email'));
    expect(emailButton).toContain('aria-disabled="true"');
    expect(emailButton).toContain('disabled=""');
    expect(html).toContain('id="v34-login-mobile"');
    expect(html).not.toContain('id="v34-login-email"');
    expect(html).toContain('Mobile is the only enabled login channel in this release.');
  });

  it('exposes the email input only from the enabled server projection, never by initial selection alone', () => {
    const mobile = render({ mobile: true, email: true });
    const email = render({ mobile: true, email: true }, 'email');
    expect(mobile).toContain('id="v34-login-mobile"');
    expect(mobile).not.toContain('id="v34-login-email"');
    expect(email).toMatch(/<input(?=[^>]*id="v34-login-email")(?=[^>]*type="email")(?=[^>]*inputMode="email")(?=[^>]*autoComplete="email")(?=[^>]*value="")[^>]*>/u);
    expect(email).not.toContain('id="v34-login-mobile"');
    expect(email).toContain('Only an email you have already verified from your profile can sign you in.');
    expect(render(null, 'email')).toBe(render(null, 'mobile'));
  });

  it('keeps the initial mobile value empty with numeric telephone entry semantics and no password', () => {
    const html = render();
    expect(html).toMatch(/<input(?=[^>]*id="v34-login-mobile")(?=[^>]*type="tel")(?=[^>]*inputMode="numeric")(?=[^>]*autoComplete="tel-national")(?=[^>]*value="")[^>]*>/u);
    expect(html).toContain('+91');
    expect(html).not.toMatch(/type="password"/u);
    expect(html).toContain('role="group" aria-label="Sign-in identity"');
  });

  it('retains the approved Student, Change-persona and language context', () => {
    const html = render();
    expect(html).toContain('data-nyayone-create-context=""');
    expect(html).toContain('Joining as <b>Student</b>');
    expect(html).toContain('aria-label="Change persona"');
    expect(html).toContain('>Change</button>');
    expect(html).toContain('English');
  });

  it('keeps the privacy-preserving response copy and the existing OTP action', () => {
    const html = render();
    expect(html).toContain('If these details match an account, we’ll send a sign-in code.');
    expect(html).toContain('For your privacy, the response looks the same either way.');
    expect(html).toContain('aria-label="Send Code"');
    expect(html).not.toContain('aria-label="Send one time code"');
    expect(html).toContain('<span>Send Code</span>');
  });

  it('renders legal notices as inert prototype text with no link, button or tab stop', () => {
    for (const channels of [null, { mobile: true, email: true }]) {
      const footer = render(channels).match(/<footer class="v321-legal">(.*?)<\/footer>/su)?.[1];
      expect(footer).toBeDefined();
      expect(footer).toContain('<span>Privacy Notice</span>');
      expect(footer).toContain('<span>Terms</span>');
      expect(footer).toContain('<span>Accessibility</span>');
      expect(footer).not.toMatch(/<(?:a|button|input)\b|\bhref=|\btabindex=|\bcontenteditable=|\brole="(?:link|button)"/iu);
    }
  });

  it('retains source-level channel guards, validation and OTP destination wiring (not a live-route test)', () => {
    expect(login).toContain('getLoginChannels()');
    expect(login).toContain('.catch(() => { if (active) setChannels(null); })');
    expect(login).toContain("if (next === 'email' && !emailEnabled) return;");
    expect(login).toContain('if (!isValidLoginEmail(email))');
    expect(login).toContain('if (!isValidMobile(mobile))');
    expect(login).toContain('await startEmailLoginOtp(email.trim(), request.signal);');
    expect(login).toContain('await startLoginOtp(mobile, request.signal);');
    expect(login.indexOf("nav('/s-05');")).toBeGreaterThan(login.indexOf('await startLoginOtp(mobile, request.signal);'));
    expect(login).toContain('onChangeStart={() => { setBusy(true); setMobile(\'\'); setEmail(\'\'); setErrors({}); }}');
  });

  it('binds S-04 submission continuation to its mounted current request (source contract)', () => {
    expect(login).toContain('const pendingLogin = useRef<AbortController | null>(null);');
    expect(login).toMatch(/useEffect\(\(\) => \(\) => \{\s*pendingLogin\.current\?\.abort\(\);\s*pendingLogin\.current = null;\s*\}, \[\]\);/u);
    expect(login).toContain('if (busy || pendingLogin.current) return;');
    expect(login).toContain('const isCurrentRequest = () => pendingLogin.current === request && !request.signal.aborted;');
    expect(login).toMatch(/if \(!isCurrentRequest\(\)\) return;\s*nav\('\/s-05'\);/u);
    expect(login).toMatch(/catch \(caught\) \{\s*if \(!isCurrentRequest\(\)\) return;/u);
    expect(login).toMatch(/finally \{\s*if \(isCurrentRequest\(\)\) \{\s*pendingLogin\.current = null;\s*setBusy\(false\);/u);
  });

  it('retires the server OTP context before returning to persona selection', async () => {
    const order: string[] = [];
    const state: Awaited<ReturnType<typeof cancelStudentOtp>> = {
      status: 'unavailable', purpose: null, destinationMasked: null,
      attemptsLeft: null, expiresInSeconds: null, resendInSeconds: null,
      lockedForSeconds: null, resendAllowed: false,
    };
    const retire = vi.fn(async () => { order.push('server-retired'); return state; });
    const onRetired = vi.fn(() => { order.push('adopt-retired'); });
    const returnToPersona = vi.fn(() => { order.push('return-to-persona'); });
    await retireStudentOtpPersonaContext(retire, onRetired, returnToPersona);
    expect(retire).toHaveBeenCalledOnce();
    expect(onRetired).toHaveBeenCalledWith(state);
    expect(returnToPersona).toHaveBeenCalledOnce();
    expect(order).toEqual(['server-retired', 'adopt-retired', 'return-to-persona']);
  });

  it('refuses persona navigation if server context retirement fails', async () => {
    const failed = new Error('synthetic cancellation failure');
    const retire = vi.fn(async () => { throw failed; });
    const onRetired = vi.fn();
    const returnToPersona = vi.fn();
    await expect(retireStudentOtpPersonaContext(retire, onRetired, returnToPersona)).rejects.toBe(failed);
    expect(retire).toHaveBeenCalledOnce();
    expect(onRetired).not.toHaveBeenCalled();
    expect(returnToPersona).not.toHaveBeenCalled();
  });

  it('does not introduce browser identity persistence or a client-controlled channel flag (source contract)', () => {
    expect(login).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie/u);
    expect(login).not.toMatch(/import\.meta\.env\.[A-Z_]*EMAIL/u);
    expect(login).not.toMatch(/email\s*:\s*true/u);
  });
});
