import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, type StudentSessionPhase } from '../../../app/authContext';
import type { OtpFlowState } from '../lib/registrationApi';

const otpHook = vi.hoisted(() => ({
  state: null as OtpFlowState | null,
  loading: true,
  loadError: false,
  adopt: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock('../lib/useOtpFlowState', () => ({
  useOtpFlowState: () => otpHook,
}));
vi.mock('../lib/registrationApi', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../lib/registrationApi')>()),
  getLoginChannels: vi.fn(async () => null),
}));

import * as screens from './V34Screens';

const AUTH_SOURCE_PATH = join(process.cwd(), 'src/features/student/auth/V34Screens.tsx');
const EMAIL_MASK = 's•••••@example.edu';

function render(component: ComponentType, props: Record<string, unknown> = {}): string {
  return renderToStaticMarkup(createElement(MemoryRouter, null, createElement(component, props)));
}

function renderWithStudentSession(component: ComponentType, phase: StudentSessionPhase): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(AuthProvider, {
        studentSession: { phase, refresh: vi.fn(async () => undefined) },
        children: createElement(component),
      }),
    ),
  );
}

function pendingLogin(destinationMasked: string): OtpFlowState {
  return {
    status: 'pending',
    purpose: 'login',
    destinationMasked,
    attemptsLeft: 3,
    expiresInSeconds: 300,
    resendInSeconds: 30,
    lockedForSeconds: 0,
    resendAllowed: false,
  };
}

afterEach(() => {
  otpHook.state = null;
  otpHook.loading = true;
  otpHook.loadError = false;
});

describe('NYAY-12 S-04 server-proven channel choice', () => {
  const DISABLED_EMAIL = /<button(?=[^>]*aria-pressed="false")(?=[^>]*aria-disabled="true")(?=[^>]*disabled="")[^>]*>.*Verified Email/su;

  it('renders the fail-closed mobile-only S-04 when no server channel projection exists', () => {
    const s04 = render(screens.V34Login);
    expect(s04).toMatch(DISABLED_EMAIL);
    expect(s04).toMatch(/<input(?=[^>]*id="v34-login-mobile")(?=[^>]*type="tel")[^>]*>/u);
    expect(s04).not.toContain('id="v34-login-email"');
    expect(s04).not.toMatch(/type="password"/u);
  });

  it('keeps the disabled projection byte-identical to the default when the server disables email', () => {
    const form = screens.V34LoginForm as unknown as ComponentType<Record<string, unknown>>;
    const disabled = render(form, { channels: { mobile: true, email: false } });
    expect(disabled).toBe(render(screens.V34Login));
  });

  it('enables the email channel only from the server projection and exposes an accessible email field', () => {
    const form = screens.V34LoginForm as unknown as ComponentType<Record<string, unknown>>;
    const mobileFirst = render(form, { channels: { mobile: true, email: true } });
    expect(mobileFirst).toMatch(/<button(?=[^>]*aria-pressed="false")(?![^>]*disabled)[^>]*>.*Verified Email/su);
    expect(mobileFirst).toContain('id="v34-login-mobile"');
    const emailSelected = render(form, { channels: { mobile: true, email: true }, initialChannel: 'email' });
    expect(emailSelected).toMatch(/<button(?=[^>]*aria-pressed="true")[^>]*>.*Verified Email/su);
    expect(emailSelected).toMatch(/<button(?=[^>]*aria-pressed="false")[^>]*>.*Mobile Number/su);
    expect(emailSelected).toMatch(
      /<input(?=[^>]*id="v34-login-email")(?=[^>]*type="email")(?=[^>]*inputMode="email")(?=[^>]*autoComplete="email")[^>]*>/u,
    );
    expect(emailSelected).not.toContain('id="v34-login-mobile"');
    expect(emailSelected).toContain('role="group" aria-label="Sign-in identity"');
    expect(emailSelected).toMatch(/one-time code by email/iu);
    expect(emailSelected).not.toMatch(/type="password"/u);
    expect(emailSelected).toContain('aria-label="Send Code"');
  });

  it('never asks the client to decide channel availability', () => {
    const source = readFileSync(AUTH_SOURCE_PATH, 'utf8');
    const s04 = source.slice(source.indexOf('export function V34Login'), source.indexOf('export function V34AccountRecovery'));
    expect(s04).toContain('getLoginChannels(');
    expect(s04).toContain('startEmailLoginOtp(');
    expect(s04).not.toMatch(/email\s*:\s*true/u);
    expect(source).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie/u);
    expect(s04).not.toMatch(/import\.meta\.env\.[A-Z_]*EMAIL/u);
  });
});

describe('NYAY-12 S-05 destination continuity', () => {
  it('renders the server-masked email destination and returns to S-04 for changes', () => {
    otpHook.state = pendingLogin(EMAIL_MASK);
    otpHook.loading = false;
    const s05 = renderWithStudentSession(screens.V34LoginOtp, 'anonymous');
    expect(s05).toContain(EMAIL_MASK);
    expect(s05).not.toContain('+91');
    expect(s05).toContain('aria-label="Change email address"');
    expect(s05).toMatch(/<input(?=[^>]*aria-label="Six digit code")(?=[^>]*autoComplete="one-time-code")[^>]*>/u);
    expect(s05).toContain('aria-label="Verify and continue"');
  });

  it('keeps the mobile presentation unchanged for mobile flows', () => {
    otpHook.state = pendingLogin('••••••3210');
    otpHook.loading = false;
    const s05 = renderWithStudentSession(screens.V34LoginOtp, 'anonymous');
    expect(s05).toContain('+91 ••••• ••210');
    expect(s05).toContain('aria-label="Change mobile number"');
    expect(s05).not.toContain('Change email address');
  });

  it('refuses to render a raw or malformed destination', () => {
    otpHook.state = pendingLogin('student@example.edu');
    otpHook.loading = false;
    const s05 = renderWithStudentSession(screens.V34LoginOtp, 'anonymous');
    expect(s05).not.toContain('student@example.edu');
  });
});
