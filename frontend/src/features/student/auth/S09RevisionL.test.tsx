import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '../../../app/authContext';
import type { OtpFlowState } from '../lib/registrationApi';

const otp = vi.hoisted(() => ({ state: null as OtpFlowState | null, loading: false, loadError: false, adopt: vi.fn(), refresh: vi.fn() }));
vi.mock('../lib/useOtpFlowState', () => ({ useOtpFlowState: () => otp }));
import { V34OtpVerify } from './V34Screens';

const render = () => renderToStaticMarkup(<MemoryRouter><AuthProvider studentSession={{ phase: 'anonymous', refresh: vi.fn(async () => undefined) }}><V34OtpVerify theme="light"/></AuthProvider></MemoryRouter>);
beforeEach(() => {
  otp.state = { status: 'pending', purpose: 'signup', destinationMasked: '••••••0340', attemptsLeft: 3, expiresInSeconds: 272, resendInSeconds: 17, lockedForSeconds: 0, resendAllowed: false };
  otp.loading = false;
});

describe('NYAY-87 S-09 Revision L with pending-OTP security supersession', () => {
  it.each([false, true])('orders top navigation, brand and pending form (loading=%s)', (loading) => {
    otp.loading = loading;
    const html = render();
    expect(html.indexOf('class="v321-topbar"')).toBeLessThan(html.indexOf('class="v321-brandpanel'));
    expect(html.indexOf('class="v321-brandpanel')).toBeLessThan(html.indexOf('id="main-content"'));
    expect(html).toContain('Joining as <b>Student</b>');
    expect(html).toContain('English');
  });

  it('uses the approved signup heading stack and confirmation copy with a masked destination', () => {
    const html = render();
    expect(html).toContain('v321-form--signup-otp');
    expect(html).toContain('Verify your new account.');
    expect(html).toContain('One code to <b class="v321-mono">+91 ••••• ••340</b> confirms this account is yours.');
    expect(html).toContain('One-time code');
    expect(html).toContain('aria-label="Change registration details"');
  });

  it('never imports the prototype success or bypass controls into the pending frame', () => {
    const html = render();
    for (const copy of ['Code accepted', 'Account created', 'Set Up My Profile', 'Skip for Now']) expect(html).not.toContain(copy);
    expect(html).toMatch(/<input(?=[^>]*aria-label="Six digit code")(?=[^>]*autoComplete="one-time-code")(?=[^>]*value="")[^>]*>/u);
    expect(html).toMatch(/<button(?=[^>]*aria-label="Verify and continue")(?=[^>]*disabled="")[^>]*>/u);
    expect(html).toContain('Expires in <b class="v321-mono">04:32</b>');
    expect(html).toContain('Resend in <b class="v321-mono">00:17</b>');
    expect(html).toContain('Tries left <b>3</b>');
  });

  it('uses S-09-only spacing and heading sizes without changing login OTP styling', () => {
    const css = readFileSync('src/styles/student-option321.css', 'utf8');
    expect(css).toMatch(/\[data-screen='S-09'\] \.v321-form--signup-otp\s*\{\s*gap: 13px;/u);
    expect(css).toMatch(/\[data-screen='S-09'\] \.v34-title\s*\{\s*font-size: 24px;/u);
    expect(css).toMatch(/\[data-screen='S-09'\] \.v34-title\s*\{\s*font-size: 34px;/u);
    expect(css).toMatch(/\[data-screen='S-09'\] \.v34-lede\s*\{\s*margin: 0; font-size: 13\.5px; line-height: 1\.55;/u);
  });
});
