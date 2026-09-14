import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, type StudentSessionPhase } from '../../../app/authContext';
import type { OtpFlowState } from '../lib/registrationApi';
import {
  captureActiveProfileReauthDraft,
  clearProfileReauthHandoff,
  resolvedProfileReauthResumeRoute,
  resolveProfileReauthActor,
  restoreCapturedProfileReauthDraft,
  stageActiveProfileReauthDraft,
} from '../profile/profileReauthHandoff';

const otpHook = vi.hoisted(() => ({
  state: null as OtpFlowState | null,
  loading: true,
  loadError: false,
  adopt: vi.fn(),
  refresh: vi.fn(),
}));
const otpHookInvocation = vi.hoisted(() => ({
  enabled: undefined as boolean | undefined,
}));

vi.mock('../lib/useOtpFlowState', () => ({
  useOtpFlowState: (
    _initialState?: OtpFlowState,
    options?: { enabled?: boolean },
  ) => {
    otpHookInvocation.enabled = options?.enabled;
    return otpHook;
  },
}));
import {
  V34Login,
  V34LoginOtp,
  V34OtpVerify,
  V34Register,
  retireStudentOtpPersonaContext,
} from './V34Screens';

const AUTH_SOURCE_PATH = join(
  process.cwd(),
  'src/features/student/auth/V34Screens.tsx',
);
const API_SOURCE_PATH = join(
  process.cwd(),
  'src/features/student/lib/registrationApi.ts',
);
const MANIFEST_PATH = join(
  process.cwd(),
  'test-baselines/nyay7/option-3.2.1-rev-l/manifest.json',
);
const REAUTH_ACTOR_A = '00000000-0000-4000-8000-0000000008a1';
const REAUTH_ACTOR_B = '00000000-0000-4000-8000-0000000008b2';

function retainPersonalReauthIntent(): void {
  const owner = Symbol('nyay8-same-actor-reauth');
  stageActiveProfileReauthDraft(owner, REAUTH_ACTOR_A, {
    section: 'personal',
    value: {
      firstName: 'Aditi',
      middleName: null,
      lastName: 'Rao',
      dateOfBirth: '2000-01-01',
      preferredLanguage: 'en',
      city: 'Pune',
      pronouns: null,
    },
  });
  const captured = captureActiveProfileReauthDraft();
  if (captured === null) throw new Error('reauth_fixture_capture_failed');
  clearProfileReauthHandoff();
  restoreCapturedProfileReauthDraft(captured);
}

function sourceSlice(source: string, start: string, end: string): string {
  return source.slice(source.indexOf(start), source.indexOf(end));
}

function render(component: ComponentType): string {
  return renderToStaticMarkup(
    createElement(MemoryRouter, null, createElement(component)),
  );
}

function renderWithStudentSession(
  component: ComponentType,
  phase: StudentSessionPhase,
): string {
  return renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(
        AuthProvider,
        {
          studentSession: {
            phase,
            refresh: vi.fn(async () => undefined),
          },
          children: createElement(component),
        },
      ),
    ),
  );
}

afterEach(() => {
  otpHook.state = null;
  otpHook.loading = true;
  otpHook.loadError = false;
  otpHook.adopt.mockReset();
  otpHook.refresh.mockReset();
  otpHookInvocation.enabled = undefined;
  clearProfileReauthHandoff();
});

describe('NYAY-8 passwordless mobile authentication RED contracts', () => {
  const authSource = readFileSync(AUTH_SOURCE_PATH, 'utf8');
  const apiSource = readFileSync(API_SOURCE_PATH, 'utf8');

  it('keeps S-04 and S-05 free of password controls and password-auth payloads', () => {
    const s04 = render(V34Login);
    const s05 = render(V34LoginOtp);
    const loginApi = sourceSlice(
      apiSource,
      'export async function startLoginOtp',
      'export async function getStudentSession',
    );

    for (const html of [s04, s05]) {
      expect(html).not.toMatch(/<input[^>]+type="password"/iu);
      expect(html).not.toMatch(/autocomplete="(?:current|new)-password"/iu);
      expect(html).not.toMatch(/(?:show|hide|forgot) password/iu);
    }
    expect(loginApi).toContain("'/api/v1/auth/student/login/otp/start'");
    expect(loginApi).toContain('JSON.stringify({ mobile })');
    expect(loginApi).toContain("'/api/v1/auth/student/login/otp/verify'");
    expect(loginApi).toContain('JSON.stringify({ code })');
    expect(loginApi).not.toMatch(/password/iu);
  });

  it('exposes mobile as the only enabled S-04 channel and a numeric OTP on S-05', () => {
    const s04 = render(V34Login);
    otpHook.state = {
      status: 'pending',
      purpose: 'login',
      destinationMasked: '••••••3210',
      attemptsLeft: 3,
      expiresInSeconds: 300,
      resendInSeconds: 30,
      lockedForSeconds: 0,
      resendAllowed: false,
    };
    otpHook.loading = false;
    const s05 = render(V34LoginOtp);

    expect(s04).toMatch(/<input(?=[^>]*id="v34-login-mobile")(?=[^>]*type="tel")(?=[^>]*inputMode="numeric")[^>]*>/u);
    expect(s04).toMatch(/<button(?=[^>]*aria-pressed="false")(?=[^>]*aria-disabled="true")(?=[^>]*disabled="")[^>]*>.*Verified Email/su);
    expect(s05).toMatch(/<input(?=[^>]*aria-label="Six digit code")(?=[^>]*inputMode="numeric")(?=[^>]*autoComplete="one-time-code")(?=[^>]*maxLength="6")[^>]*>/u);
    expect(s05).toContain('aria-label="Verify and continue"');
  });

  it('does not mount an actionable S-05 challenge until a pending login flow is proven by the server', () => {
    const directS05 = render(V34LoginOtp);

    expect(directS05).toContain('Restoring the server verification state…');
    expect(directS05).not.toContain('aria-label="Six digit code"');
    expect(directS05).not.toContain('aria-label="Verify and continue"');
    expect(directS05).not.toContain('>Resend Code</span>');
  });

  it('serializes cold OTP discovery after canonical session bootstrap and denies every non-anonymous phase', () => {
    otpHook.state = {
      status: 'pending',
      purpose: 'login',
      destinationMasked: '••••••3210',
      attemptsLeft: 3,
      expiresInSeconds: 300,
      resendInSeconds: 30,
      lockedForSeconds: 0,
      resendAllowed: false,
    };
    otpHook.loading = false;

    for (const phase of ['pending', 'authenticated', 'unavailable'] as const) {
      const html = renderWithStudentSession(V34LoginOtp, phase);
      expect.soft(otpHookInvocation.enabled, phase).toBe(false);
      expect.soft(html, phase).not.toContain('aria-label="Six digit code"');
      expect.soft(html, phase).not.toContain('aria-label="Verify and continue"');
    }

    const anonymous = renderWithStudentSession(V34LoginOtp, 'anonymous');
    expect(otpHookInvocation.enabled).toBe(true);
    expect(anonymous).toContain('aria-label="Six digit code"');

    expect(authSource).toContain(
      "useOtpFlowState(undefined, { enabled: session.phase === 'anonymous' })",
    );
  });

  it('keeps verification purpose-bound and waits for the exact server result before navigation', () => {
    const challenge = sourceSlice(
      authSource,
      "function V34OtpChallenge({ purpose }",
      'export function V34ProfileStep1',
    );

    expect(challenge).toContain("flow?.status !== 'pending' || flow.purpose !== purpose");
    expect(challenge).toMatch(/await verifyLoginOtp\(code\)[\s\S]*otpFlow\.adopt\(result\)[\s\S]*nav\(resumeRoute \?\? '\/s-07', \{ replace: true \}\)/u);
    expect(challenge).toContain('disabled={busy || code.length !== 6');
  });

  it('lets a server-proven same-actor reauth intent restore S-10 before the authenticated S-07 fallback', () => {
    retainPersonalReauthIntent();
    const authoritativeSession = {
      status: 200,
      authenticated: true,
      actor: { sub: REAUTH_ACTOR_A, roles: ['student'] },
    } as const;
    expect(authoritativeSession.status).toBe(200);
    expect(authoritativeSession.authenticated).toBe(true);
    expect(authoritativeSession.actor.roles).toContain('student');
    expect(resolveProfileReauthActor(authoritativeSession.actor.sub)).toBe(true);
    expect(resolvedProfileReauthResumeRoute()).toBe('/s-10?section=personal');

    const challenge = sourceSlice(
      authSource,
      "function V34OtpChallenge({ purpose }",
      'export function V34ProfileStep1',
    );
    const authenticatedFallback = sourceSlice(
      challenge,
      "if (session.phase !== 'anonymous')",
      'if (otpFlow.loadError',
    );
    expect(authenticatedFallback).toContain('resolvedProfileReauthResumeRoute()');
    expect(authenticatedFallback).toContain("?? '/s-07'");
    expect(authenticatedFallback.indexOf('resolvedProfileReauthResumeRoute()'))
      .toBeLessThan(authenticatedFallback.indexOf("'/s-07'"));
  });

  it('keeps anonymous S-05 without a proven pending flow fail-closed to S-03', () => {
    const challenge = sourceSlice(
      authSource,
      "function V34OtpChallenge({ purpose }",
      'export function V34ProfileStep1',
    );
    expect(challenge).toContain(
      "if (otpFlow.loadError || flow?.status !== 'pending' || flow.purpose !== purpose)",
    );
    expect(challenge).toContain('return <Navigate to="/s-03" replace');
  });

  it('keeps authenticated S-05 without a resolved reauth intent on the S-07 fallback', () => {
    clearProfileReauthHandoff();
    expect(resolvedProfileReauthResumeRoute()).toBeNull();
    const challenge = sourceSlice(
      authSource,
      "function V34OtpChallenge({ purpose }",
      'export function V34ProfileStep1',
    );
    const authenticatedFallback = sourceSlice(
      challenge,
      "if (session.phase !== 'anonymous')",
      'if (otpFlow.loadError',
    );
    expect(authenticatedFallback).toContain("session.phase === 'authenticated'");
    expect(authenticatedFallback).toContain("'/s-07'");
  });

  it('never restores a retained private route after authoritative different-actor reauth', () => {
    retainPersonalReauthIntent();
    expect(resolveProfileReauthActor(REAUTH_ACTOR_B)).toBe(false);
    expect(resolvedProfileReauthResumeRoute()).toBeNull();
  });

  it.each([
    ['S-04', V34Login],
    ['S-08', V34Register],
    ['S-09', V34OtpVerify],
  ] as const)('carries explicit Student context with a Change action on %s', (_screen, Component) => {
    const html = render(Component);

    expect(html).toContain('data-nyayone-create-context=""');
    expect(html).toContain('Joining as <b>Student</b>');
    expect(html).toContain('data-nyayone-persona-change=""');
    expect(html).toMatch(/<button[^>]*data-nyayone-persona-change=""[^>]*>Change<\/button>/u);
  });

  it.each([
    ['mobile', '••••••3210', true],
    ['mobile', '••••••3210', false],
    ['email', 's•••••@example.test', true],
    ['email', 's•••••@example.test', false],
  ] as const)('omits S-05 persona/language context for %s / %s (loading=%s)', (_channel, destinationMasked, loading) => {
    otpHook.state = {
      status: 'pending', purpose: 'login', destinationMasked,
      attemptsLeft: 3, expiresInSeconds: 300, resendInSeconds: 30,
      lockedForSeconds: 0, resendAllowed: false,
    };
    otpHook.loading = loading;
    const html = renderWithStudentSession(V34LoginOtp, 'anonymous');

    // Owner disposition 15129 removes only the S-05 context. The positive
    // S-04/S-08/S-09 assertions above remain active.
    expect(html).not.toContain('data-nyayone-create-context');
    expect(html).not.toContain('Joining as');
    expect(html).not.toContain('data-nyayone-persona-change');
    expect(html).not.toContain('data-nyayone-persona-trigger');
    expect(html).not.toContain('data-nyayone-language-trigger');
    expect(html).not.toContain('aria-label="Change persona"');
  });

  it('distinguishes identity correction to S-04 from persona Change to S-03 safe focus', () => {
    const challenge = sourceSlice(
      authSource,
      "function V34OtpChallenge({ purpose }",
      'export function V34ProfileStep1',
    );
    const gateway = sourceSlice(
      authSource,
      'export function V34AuthGate',
      'export function V34Login',
    );

    expect(challenge).toContain("const backRoute = purpose === 'signup' ? '/s-08' : '/s-04'");
    expect(challenge).toContain('onClick={() => nav(backRoute)}');
    expect(challenge).toContain("'Change registration details' : 'Change mobile number'");
    expect(authSource).toContain("nav('/s-03', { replace: true, state: { nyay7Focus: 'persona' } })");
    expect(authSource).toContain('aria-label="Change persona"');
    expect(gateway).toContain("?.nyay7Focus !== 'persona'");
    expect(gateway).toContain("'[data-screen=\"S-03\"] [data-nyayone-persona-trigger]'");
    expect(gateway).toContain('?.focus()');
  });

  it('retires the server-owned OTP context before persona Change returns to S-03', () => {
    expect.soft(apiSource).toContain("'/api/v1/auth/student/otp/cancel'");
    expect.soft(apiSource).toMatch(/\/otp\/cancel'[\s\S]{0,180}method: 'POST'[\s\S]{0,120}body: JSON\.stringify\(\{\}\)/u);
    expect.soft(apiSource).toContain("state.status !== 'unavailable' || state.purpose !== null");
    expect.soft(apiSource).toContain("'invalid_otp_cancel_projection'");
    expect.soft(authSource).toContain('cancelStudentOtp');
    expect.soft(authSource).toContain('await retireStudentOtpPersonaContext(');
    expect.soft(authSource).toContain("() => nav('/s-03', { replace: true, state: { nyay7Focus: 'persona' } })");
  });

  it('waits for authoritative cancellation before returning to persona selection', async () => {
    const order: string[] = [];
    let finishCancellation: ((state: OtpFlowState) => void) | undefined;
    const pendingCancellation = new Promise<OtpFlowState>((resolve) => {
      finishCancellation = resolve;
    });
    const retirement = retireStudentOtpPersonaContext(
      () => pendingCancellation,
      () => { order.push('adopt'); },
      () => { order.push('navigate'); },
    );

    await Promise.resolve();
    expect(order).toEqual([]);
    finishCancellation?.({
      status: 'unavailable',
      purpose: null,
      destinationMasked: null,
      attemptsLeft: null,
      expiresInSeconds: null,
      resendInSeconds: null,
      lockedForSeconds: null,
      resendAllowed: false,
    });
    await retirement;

    expect(order).toEqual(['adopt', 'navigate']);
  });

  it('keeps the sealed Option 3.2.1 Revision L authority for S-04 and S-05', () => {
    const manifest = JSON.parse(readFileSync(MANIFEST_PATH, 'utf8')) as {
      revision_l_authority_screens: string[];
      entries: Array<{
        viewport: string;
        screen: string;
        sha256: string;
        authority: string;
      }>;
    };
    const expected = new Map([
      ['1440x1024/S-04', '106da9aba4b25f87c0e8f7b8c9c73dfd0d533aa67a8a83e35f25c25bd4519129'],
      ['1440x1024/S-05', '5d64b5ba642ebe15cc309c859d31417f7a3c6fb1a609ed73f2ea3f1f2db0aec5'],
      ['390x844/S-04', 'e58080b38099d68b98fc62961506d72fa7a919dcb162170723896f950f911a10'],
      ['390x844/S-05', 'c998e65650667f1de9654a3783c88f512e8bbe2f53b3f72f51db3587d6b12794'],
      ['360x800/S-04', '2e2058bcd541fb04a2332cec31d8bb36b08ccd15598ea335c77235298f7454ac'],
      ['360x800/S-05', 'e7427c4e80ea35ee9d10accb474a5d00a3fe2a45aab3ba9145188ee04bf0bd53'],
    ]);

    expect(manifest.revision_l_authority_screens).toEqual(['S-03', 'S-04', 'S-05']);
    for (const baseline of manifest.entries.filter(({ screen }) => ['S-04', 'S-05'].includes(screen))) {
      expect(baseline.sha256).toBe(expected.get(`${baseline.viewport}/${baseline.screen}`));
      expect(baseline.authority).toBe('revision-l-plus-nyay8-contract');
    }
    expect(render(V34Login)).toContain('data-nyayone-design="3.2.1-rev-l"');
    expect(render(V34LoginOtp)).toContain('data-nyayone-design="3.2.1-rev-l"');
  });
});
