import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { runInNewContext } from 'node:vm';
import { describe, expect, it } from 'vitest';

const source = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

const BOUNDARY_PATH = 'src/features/student/lib/studentBrowserContext.ts';
const LEGACY_STORAGE_PATH = 'src/features/student/lib/studentLegacyStorage.ts';
const CLIENT_PATH = 'src/features/student/lib/studentApiClient.ts';
const REGISTRATION_PATH = 'src/features/student/lib/registrationApi.ts';
const SETTINGS_API_PATH = 'src/features/student/lib/settingsApi.ts';
const SETTINGS_SCREEN_PATH = 'src/features/student/settings/SettingsScreens.tsx';
const V34_PATH = 'src/features/student/auth/V34Screens.tsx';
const AUTH_CONTEXT_PATH = 'src/app/authContext.tsx';
const NOTICE_PATH = 'src/features/student/lib/studentAuthTransitionNotice.ts';
const V34_BROWSER_GATE_PATH = 'scripts/v34-s11-s26-e2e.mjs';

type Wave1ResponseFixture = {
  url(): string;
  request(): { method(): string };
  status(): number;
  finished(): Promise<Error | null>;
};

function wave1ResponseFixture(url: string, method = 'GET'): Wave1ResponseFixture {
  return {
    url: () => url,
    request: () => ({ method: () => method }),
    status: () => 200,
    finished: async () => null,
  };
}

function extractWave1GateFunction(gate: string, name: string): string {
  const expression = gate.match(
    new RegExp(`(?:async )?function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n\\}`, 'u'),
  )?.[0];
  expect(expression, `missing Wave 1 gate function: ${name}`).toBeDefined();
  return expression ?? '';
}

function assertLegacyStorageContract(value: string): void {
  for (const required of [
    "'legalsaathi.student.profile.v1'",
    "'legalsaathi.student.onboarding.v34'",
    "'legalsaathi.internship.applications.v1'",
    "'legalsaathi.clinical.export-audit.v1'",
    "'legalsaathi.student.registration.v2'",
    "'legalsaathi.student.privacy.export.v1'",
    "'legalsaathi.student.privacy.delete.v1'",
    "'legalsaathi.student.cleanup-registry.v1'",
    "'ls-auth-student'",
    "'ls-auth-lawyer'",
    "'ls-onboarding-seen'",
    "'ls-locale'",
    "'ls-reviewer'",
    "'ls-theme'",
    "'ls-reports-'",
    "'ls-reminder-prefs-'",
    "'ls-draftws-'",
    "'ls-review-'",
    "'ls-filing-'",
    "'nyayone.student.reports.v1.'",
    "'nyayone.student.reminder-prefs.v1.'",
    'export const MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH = 256;',
    'length = storage.length;',
    'if (!Number.isSafeInteger(length) || length < 0) return null;',
    'prefixes.some((prefix) => key.startsWith(prefix))',
    'const snapshot = collectOwnedKeysSnapshot(storage, exactKeys, prefixInventory);',
    'const batch = snapshot.slice(index, index + MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH);',
    'storage.removeItem(key);',
    'const remaining = keysStillPresent(storage, new Set(batch));',
    'if (removalFailed || remaining.size > 0)',
    'const nextGeneration = collectOwnedKeysSnapshot(storage, exactKeys, prefixInventory);',
    'if (nextGeneration === null || nextGeneration.length > 0)',
    'export function purgeLegacyStudentLocalStorage',
    'export function purgeLegacyStudentSessionStorage',
    'export function purgeLegacyStudentSessionStorageAtBootstrap',
    'export function purgeCompleteLegacyBrowserLocalStorage',
  ]) {
    expect(value, `missing NYAY-18 legacy-storage boundary: ${required}`).toContain(required);
  }
  expect(value.match(/length = storage\.length;/gu)).toHaveLength(2);
  expect(value.match(/!Number\.isSafeInteger\(length\) \|\| length < 0/gu)).toHaveLength(2);
  expect(value).not.toMatch(/\.clear\s*\(/);
  expect(value).not.toMatch(/\.getItem\s*\(/);
  expect(value).not.toMatch(/\.setItem\s*\(/);
}

function assertBoundaryContract(value: string): void {
  for (const required of [
    'clearRegistrationAttempt();',
    'resetProfileDraft();',
    'clearProfileConflictDraft();',
    'clearActorSensitiveQueryState();',
    "studentBrowserContextAbortController.abort('student_context_changed');",
    'studentBrowserContextAbortController = new AbortController();',
    'studentBrowserContextGeneration += 1;',
    'export function captureStudentContextFence',
    'export function isStudentContextFenceCurrent',
    "const ACTOR_INDEPENDENT_QUERY_ROOTS = new Set([\n  'public-credential-verification',\n  'public-internship-risk-labels',\n]);",
    'predicate: (query) => !ACTOR_INDEPENDENT_QUERY_ROOTS.has(String(query.queryKey[0] ?? \'\'))',
    'queryClient.getMutationCache().clear();',
    'studentReportStorageKey(id)',
    'studentReminderPrefStorageKey(id)',
    'export const MAX_RETIRED_STUDENT_KEYS_PER_PURGE = MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH;',
    'function clearStudentBrowserContextWithIncomingActorKeys(',
    '[...currentActorKeys(), ...incomingActorKeys],',
    'clearStudentBrowserContextWithIncomingActorKeys(options, actorKeys(actor))',
    'cleanupComplete = purgeLegacyStudentSessionStorage(session).complete && cleanupComplete;',
    'if (!clearStudentBrowserContextWithIncomingActorKeys(options, actorKeys(actor))) return false;',
    "export const STUDENT_AUTH_SESSION_LOCK = 'nyayone.student.auth-session.v1';",
    "export const STUDENT_AUTH_TRANSITION_CHANNEL = 'nyayone.student.auth-transition.v2';",
    "export const STUDENT_AUTH_TRANSITION_STARTED_EVENT = 'nyayone:student-auth-transition-started';",
    "export const STUDENT_AUTH_CHANGED_EVENT = 'nyayone:student-auth-changed';",
    "kind: 'start' | 'ack' | 'nack' | 'end';",
    'run<T>(operation: () => Promise<T>): Promise<T>;',
    'coordinator.locks.request(',
    "{ mode: 'shared', signal: abort.signal }",
    "{ mode: 'exclusive', signal: pending.abort.signal }",
    'export async function withStudentAuthRequestLease',
    'failedTransitions: Set<string>;',
    "coordinator.failedTransitions.has(value.transition) ? 'nack' : 'ack'",
    "new Error('student_auth_transition_local_cleanup_incomplete')",
    "new Error('student_auth_transition_peer_cleanup_incomplete')",
    'notifyTransitionUnavailable(coordinator);',
    'for (const transitionId of coordinator.activeTransitions) listener.onStart(transitionId);',
  ]) {
    expect(value, `missing browser-context boundary: ${required}`).toContain(required);
  }
  expect(value).toMatch(/let observedStudentActor: ObservedStudentActor \| null = null/);
  expect(value.match(/purgeLegacyStudentLocalStorage\(/gu)).toHaveLength(2);
  expect(value).toMatch(/observedStudentActor === null \|\| observedStudentActor\.subject !== actor\.subject/);
  expect(value).toMatch(
    /if \(observedStudentActor === null \|\| observedStudentActor\.subject !== actor\.subject\) \{[\s\S]*clearStudentBrowserContextWithIncomingActorKeys\(options, actorKeys\(actor\)\)[\s\S]*\}\s*observedStudentActor = actor;/,
  );
  expect(value).toMatch(/if \(options\.notifyAuthChanged\) \{[\s\S]*notifyStudentAuthChanged\(\{[\s\S]*preserveProfileReauthHandoff:/);
  expect(value).not.toMatch(/(?:localStorage|sessionStorage|\bstorage)\.clear\s*\(/);
  expect(value).not.toMatch(/setItem\s*\([^\n]*cleanup-registry/);
  expect(value).not.toMatch(/getItem\s*\([^\n]*cleanup-registry/);
  expect(value).not.toMatch(
    /AUTH_TRANSITION_DISCOVERY_MS|kind:\s*['"](?:hello|probe|present)['"]|\{\s*steal:\s*true\s*\}/,
  );
  assertLegacyStorageContract(source(LEGACY_STORAGE_PATH));
}

function assertStudentClientContract(value: string): void {
  expect(value).toMatch(/response\.status !== 401/);
  expect(value).toMatch(/response\.clone\(\)\.json\(\)/);
  expect(value).toContain("const STUDENT_AUTH_LOSS_CODES = new Set([\n  'authentication_required',\n  'session_authority_required',\n]);");
  expect(value).toContain("STUDENT_AUTH_LOSS_CODES.has(errorCode(body) ?? '')");
  expect(value).toMatch(/clearStudentBrowserContext\(\{[\s\S]*notifyAuthChanged:/);
  expect(value).toContain('capturedDraft !== null || hasProfileReauthHandoff()');
  expect(value).toContain('preserveProfileReauthHandoff: preserveRetainedDraft');
}

function assertRegistrationLifecycle(value: string, authContext: string): void {
  expect(value).toMatch(/verifyStudentOtp[\s\S]*withStudentAuthTransition\(async \(transition\) =>/);
  expect(value).toMatch(/verifyLoginOtp[\s\S]*withStudentAuthTransition\(async \(transition\) =>/);
  const discovery = value.match(/export async function getStudentSession\([\s\S]*?\n\}/)?.[0] ?? '';
  expect(discovery).toContain('return null;');
  expect(discovery).not.toContain('clearStudentBrowserContext');
  expect(discovery).not.toContain('observeStudentSessionActor');
  expect(value).toContain("const acceptedServerRoles = new Set([\n    'admin',\n    'legal_reviewer',\n    'moderator',\n    'safety_officer',\n    'student',\n  ]);");
  expect(value).toContain('keys.length !== expectedKeys.length');
  expect(value).toContain('isCanonicalUuid(actor.sub)');
  expect(value).toContain('isCanonicalStudentConsentState(actor.consent_state)');
  expect(value).toMatch(/withStudentAuthTransition[\s\S]*await transition\.run\(async \(\) =>[\s\S]*await getStudentSession\(\{ authTransition: transition \}\)[\s\S]*finally \{[\s\S]*await finishStudentAuthTransition\(transition\)/);
  expect(value).toMatch(/logoutStudent[\s\S]*withStudentAuthTransition\(async \(transition\) =>[\s\S]*\/auth\/student\/logout[\s\S]*authTransition: transition/);
  expect(authContext).toMatch(/applyStudentSessionDiscovery[\s\S]*generation !== currentGeneration[\s\S]*observeStudentSessionActor/);
  expect(authContext).toMatch(/const actor = await getStudentSession\(\)[\s\S]*applyStudentSessionDiscovery\(generation, generationRef\.current, actor\)/);
  expect(authContext).toMatch(/subscribeStudentAuthTransitions\(\{[\s\S]*onStart:[\s\S]*onEnd:/);
}

function assertDeletionLifecycle(api: string, screen: string, authGate: string, notice: string): void {
  expect(api).toMatch(/requestAccountDeletion[\s\S]*withStudentAuthTransition\(async \(transition\) =>[\s\S]*\/privacy\/delete[\s\S]*authTransition: transition[\s\S]*requireAnonymousAfterSuccess: true/);
  expect(api).toContain('function requirePrivacyRequestAccepted(value: unknown)');
  expect(api).toContain("!/^[0-9a-f]{32}$/u.test(wire.request_id)");
  expect(api).toContain("keys[0] !== 'request_id'");
  expect(api).toContain("keys[1] !== 'status'");
  expect(api).toContain("wire.status !== 'pending'");
  expect(api).toMatch(/\/privacy\/delete[\s\S]*?\n {6}202,/);
  const success = screen.match(/async function submitAccountDeletion\(\)[\s\S]*?\n {2}\}/)?.[0] ?? '';
  expect(success).toContain("recordStudentAuthTransitionNotice('account_deletion_accepted')");
  expect(success).toContain("nav('/s-03', { replace: true })");
  expect(success).not.toContain('studentDeletionAccepted');
  expect(screen).not.toContain('const deleteMut = useMutation({');
  expect(authGate).toContain('DELETION REQUEST ACCEPTED');
  expect(authGate).toContain("consumeStudentAuthTransitionNotice('account_deletion_accepted')");
  expect(notice).toContain('let pendingNotice: StudentAuthTransitionNotice | null = null;');
  expect(notice).not.toMatch(/localStorage|sessionStorage|indexedDB/);
  const signOut = authGate.match(/async function signOut\(\)[\s\S]*?\n {2}\}/)?.[0] ?? '';
  expect(signOut).toContain('await logoutStudent()');
  expect(signOut).not.toContain('notifyStudentAuthChanged()');
}

describe('NYAY-19 browser-context source contract', () => {
  it('pins the one complete fail-closed clear boundary', () => {
    assertBoundaryContract(source(BOUNDARY_PATH));
  });

  it('pins exact typed authentication rejection without consuming adapter bodies', () => {
    assertStudentClientContract(source(CLIENT_PATH));
  });

  it('routes student-owned adapters through the lifecycle-aware client', () => {
    for (const path of [
      'src/features/student/lib/registrationApi.ts',
      'src/features/student/lib/settingsApi.ts',
      'src/features/student/lib/calendarApi.ts',
      'src/features/student/lib/internshipsApi.ts',
      'src/features/student/lib/lawSchoolsApi.ts',
      'src/features/student/lib/reportingApi.ts',
      'src/features/student/lib/tutoringApi.ts',
    ]) {
      expect(source(path), path).toContain('studentApiFetch');
    }
    const credentials = source('src/features/student/lib/credentialsApi.ts');
    expect(credentials).toMatch(
      /sessionScope === ['"]student['"][\s\S]*studentApiFetch[\s\S]*apiFetch/,
    );
    expect(credentials).not.toContain('X-Actor-Claims');
    expect(source('src/features/student/lib/riskLabelsApi.ts')).not.toContain('studentApiFetch');
  });

  it('pins anonymous/invalid, rotation, logout and deletion lifecycle wiring', () => {
    assertRegistrationLifecycle(source(REGISTRATION_PATH), source(AUTH_CONTEXT_PATH));
    assertDeletionLifecycle(
      source(SETTINGS_API_PATH),
      source(SETTINGS_SCREEN_PATH),
      source(V34_PATH),
      source(NOTICE_PATH),
    );
  });

  it('gives the authenticated browser gate a complete server session actor', () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    const session = gate.match(
      /if \(url\.pathname === '\/api\/v1\/auth\/student\/session'\)([\s\S]*?)if \(url\.pathname === '\/api\/v1\/student\/settings'\)/,
    )?.[1] ?? '';
    for (const field of [
      "sub: '00000000-0000-4000-8000-000000002701'",
      "roles: ['student']",
      "student_profile_id: '00000000-0000-4000-8000-000000002702'",
      "student_verification: 'verified'",
      'is_minor: false',
      "consent_state: ['registration']",
    ]) {
      expect(session, `missing browser-gate session field: ${field}`).toContain(field);
    }
  });

  it('drives the V34 S-17 edit journey through the canonical profile boundary', () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    for (const field of [
      'const completeProfileProjection = {',
      'let profileProjection = completeProfileProjection',
      'profile_version: 7',
      "completion_version: 'v1'",
      'completion_percent: 100',
      "completed_sections: ['personal', 'academic', 'interests']",
      'next_incomplete_section: null',
      'is_complete: true',
      'personal: {',
      'academic: {',
      'interests: {',
      "page.getByRole('button', { name: 'Edit profile', exact: true })",
      "url.pathname === '/s-10' && url.search === '?section=personal'",
      "page.getByRole('heading', { name: 'About you.', exact: true })",
      "expectedScreen: 'S-10'",
      "page.getByRole('button', { name: 'Continue profile', exact: true })",
      "url.pathname === '/s-10' && url.search === '?section=academic'",
      "url.pathname === '/api/v1/auth/student/verification/email/request'",
      "page.getByRole('button', { name: 'Request verification review', exact: true })",
      "no editable email field on the server-authoritative status screen",
      "Verification review request recorded. Verification remains pending until an authorized review succeeds.",
      "'S-17': 211, 'S-17E': 34",
    ]) {
      expect(gate, `missing canonical V34 profile/edit contract: ${field}`).toContain(field);
    }
    expect(gate).not.toContain('Edit college & year');
  });

  it('keeps the incomplete Wave 1 profile fixture valid under the NYAY-9 projection contract', () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    const incompleteProjection = gate.match(
      /profileProjection = \{([\s\S]*?)const context = await browser\.newContext/u,
    )?.[1] ?? '';

    expect(incompleteProjection).toContain('profile_version: 8');
    expect(incompleteProjection).toContain("completed_sections: ['personal']");
    expect(incompleteProjection).toContain('missing_requirements: [');
    for (const requirement of [
      'academic.college',
      'academic.year_of_study',
      'academic.enrolment_number',
      'interests.interests',
      'interests.goals',
    ]) {
      expect(incompleteProjection).toContain(`'${requirement}'`);
    }
  });

  it('waits for the canonical profile response before sampling profile-owned screens', () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    const profileStateInventory = gate.match(
      /const profileDependentStates = new Set\(\[([\s\S]*?)\]\);/u,
    )?.[1] ?? '';
    for (const state of [
      'S-11', 'S-12', 'S-13', 'S-14', 'S-15', 'S-16', 'S-17', 'S-17E',
    ]) {
      expect(profileStateInventory, `missing profile readiness state: ${state}`).toContain(`'${state}'`);
    }
    expect(gate).toMatch(
      /isExactApiResponse\(\s*response,\s*'GET',\s*'\/api\/v1\/student\/profile',?\s*\)/u,
    );
    const responseReady = gate.indexOf('await finishResponse(await profileResponsePromise)');
    const geometrySample = gate.indexOf('const geometry = await page.evaluate(geometryProbe);');
    expect(responseReady).toBeGreaterThan(0);
    expect(geometrySample).toBeGreaterThan(responseReady);
  });

  it('matches canonical session/profile responses by exact method, origin and query-free URL', () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    expect(gate).toContain("const apiBase = process.env.V34_API_BASE_URL ?? 'http://localhost:1131';");
    expect(gate).toContain('const canonicalApiOrigin = new URL(apiBase).origin;');
    const matcher = runInNewContext(
      `(${extractWave1GateFunction(gate, 'isExactApiResponse')})`,
      { URL, canonicalApiOrigin: 'http://localhost:1131' },
    ) as (response: Wave1ResponseFixture, method: string, pathname: string) => boolean;
    const path = '/api/v1/auth/student/session';

    expect(matcher(wave1ResponseFixture(`http://localhost:1131${path}`), 'GET', path)).toBe(true);
    expect(matcher(wave1ResponseFixture(`http://localhost:1131${path}`, 'POST'), 'GET', path)).toBe(false);
    expect(matcher(wave1ResponseFixture(`http://127.0.0.1:4177${path}`), 'GET', path)).toBe(false);
    expect(matcher(wave1ResponseFixture(`http://localhost:1131${path}?probe=session`), 'GET', path)).toBe(false);
    expect(matcher(wave1ResponseFixture(`http://localhost:1131${path}#probe`), 'GET', path)).toBe(false);
  });

  it('arms and settles exact session plus profile observers before inspecting a private screen', () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    const sessionArm = gate.indexOf('const sessionResponsePromise = profileDependentStates.has(state.id)');
    const profileArm = gate.indexOf('const profileResponsePromise = profileDependentStates.has(state.id)');
    const navigation = gate.indexOf('await page.goto(`${base}${state.path}`');
    const sessionReady = gate.indexOf('await finishResponse(await sessionResponsePromise)');
    const profileReady = gate.indexOf('await finishResponse(await profileResponsePromise)');
    const privateScreenSample = gate.indexOf('await page.locator(`[data-screen="${state.id === \'S-17E\' ? \'S-17\' : state.id}"]`)');

    expect(sessionArm).toBeGreaterThan(0);
    expect(profileArm).toBeGreaterThan(sessionArm);
    expect(navigation).toBeGreaterThan(profileArm);
    expect(sessionReady).toBeGreaterThan(navigation);
    expect(profileReady).toBeGreaterThan(sessionReady);
    expect(privateScreenSample).toBeGreaterThan(profileReady);
  });

  it('emits only privacy-safe response-settlement diagnostics', async () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    const finish = runInNewContext(
      `(${extractWave1GateFunction(gate, 'finishResponse')})`,
      { URL },
    ) as (response: Wave1ResponseFixture) => Promise<Record<string, unknown>>;
    const planted = [
      'actor=student-private',
      'cookie=session-private',
      'otp=123456',
      'token=credential-private',
    ].join('&');
    const diagnostic = await finish(wave1ResponseFixture(
      `http://127.0.0.1:4177/api/v1/student/profile?${planted}`,
    ));
    const serialized = JSON.stringify(diagnostic).toLowerCase();

    expect(diagnostic).toEqual({
      method: 'GET',
      path: '/api/v1/student/profile',
      status: 200,
      finishedError: null,
    });
    expect(serialized).not.toContain('?');
    for (const secretClass of ['actor', 'cookie', 'otp', 'token', '123456', 'student-private']) {
      expect(serialized).not.toContain(secretClass);
    }
  });

  it('redacts raw path, query and error material from generic runtime diagnostics', () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    expect(gate).toContain("import { createRuntimeEvidence, attachRuntimeEvidence, runtimeEvent } from './lib/wave1-runtime-diagnostics.mjs'");
    const collector = source('scripts/lib/wave1-runtime-diagnostics.mjs');
    const contract = JSON.parse(source('scripts/lib/wave1-runtime-diagnostics.json'));
    const attach = runInNewContext(
      `${extractWave1GateFunction(collector, 'canonicalRuntimeRoute')}\n${extractWave1GateFunction(collector, 'runtimeEvent')}\n(${extractWave1GateFunction(collector, 'attachRuntimeEvidence')})`,
      { URL, contract, templates: new Set(contract.routeTemplates) },
    ) as (
      page: { on(event: string, listener: (value: unknown) => void): void; url(): string },
      runtime: Record<string, unknown[]>,
    ) => void;
    const listeners = new Map<string, (value: unknown) => void>();
    const runtime = {
      consoleErrors: [] as unknown[],
      failedRequests: [] as unknown[],
      httpErrors: [] as unknown[],
      pageErrors: [] as unknown[],
      unmatchedApi: [] as unknown[],
    };
    attach({
      on: (event, listener) => { listeners.set(event, listener); },
      url: () => 'http://localhost:4177/s-18?actor=private',
    }, runtime);

    const planted = 'actor-private-cookie-private-otp-123456-token-private';
    listeners.get('console')?.({
      type: () => 'error',
      text: () => planted,
      location: () => ({ url: `http://localhost:4177/assets/${planted}.js?token=${planted}` }),
    });
    listeners.get('pageerror')?.(new Error(planted));
    listeners.get('requestfailed')?.({
      method: () => 'GET',
      url: () => `http://localhost:1131/api/v1/private/${planted}?actor=${planted}`,
      failure: () => ({ errorText: planted }),
    });
    listeners.get('response')?.({
      status: () => 503,
      request: () => ({ method: () => 'POST' }),
      url: () => `http://localhost:1131/api/v1/private/${planted}?token=${planted}`,
    });

    expect(runtime).toEqual({
      consoleErrors: [{ stage: 'console-error', routeTemplate: '/assets/{asset}', method: 'NONE', status: 0, reason: 'NONE' }],
      failedRequests: [{ stage: 'request-failed', method: 'GET', routeTemplate: 'unclassified-route', status: 0, reason: 'OTHER' }],
      httpErrors: [{ stage: 'http-error', status: 503, method: 'POST', routeTemplate: 'unclassified-route', reason: 'NONE' }],
      pageErrors: [{ stage: 'page-error', routeTemplate: '/s-{screen}', method: 'NONE', status: 0, reason: 'NONE' }],
      unmatchedApi: [],
    });
    const serialized = JSON.stringify(runtime).toLowerCase();
    for (const forbidden of [
      'actor', 'cookie', 'otp', '123456', 'token', 'private', '?', 'errorText',
    ]) {
      expect(serialized).not.toContain(forbidden.toLowerCase());
    }
  });

  it('keeps unmatched API diagnostics free of raw URL and path material', () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    const start = gate.indexOf('runtime.unmatchedApi.push(');
    const end = gate.indexOf("return json(501, { detail: { code: 'qa_route_not_stubbed' } });", start);
    const diagnostic = gate.slice(start, end);

    expect(start).toBeGreaterThan(0);
    expect(end).toBeGreaterThan(start);
    expect(diagnostic.trim()).toBe("runtime.unmatchedApi.push(runtimeEvent('unmatched-api', request.url(), request.method()));");
    expect(diagnostic).not.toContain('path:');
    expect(diagnostic).not.toContain('url.pathname');
    expect(diagnostic).not.toContain('url.search');
  });

  it.each([
    ['registration memory', 'clearRegistrationAttempt();'],
    ['profile draft', 'resetProfileDraft();'],
    ['actor-sensitive query cache', 'clearActorSensitiveQueryState();'],
    ['public-query root inventory', "const ACTOR_INDEPENDENT_QUERY_ROOTS = new Set([\n  'public-credential-verification',\n  'public-internship-risk-labels',\n]);"],
    ['mutation cache', 'queryClient.getMutationCache().clear();'],
    ['report actor key', 'studentReportStorageKey(id)'],
    ['reminder actor key', 'studentReminderPrefStorageKey(id)'],
    ['bounded retired-key purge alias', 'export const MAX_RETIRED_STUDENT_KEYS_PER_PURGE = MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH;'],
    ['retired local purge', '[...currentActorKeys(), ...incomingActorKeys],'],
    ['incoming actor pre-publication purge', 'clearStudentBrowserContextWithIncomingActorKeys(options, actorKeys(actor))'],
    ['abort prior actor work', "studentBrowserContextAbortController.abort('student_context_changed');"],
    ['peer cleanup rejection', "new Error('student_auth_transition_peer_cleanup_incomplete')"],
    ['late subscriber replay', 'for (const transitionId of coordinator.activeTransitions) listener.onStart(transitionId);'],
  ])('kills removal of the %s boundary', (_label, needle) => {
    const mutant = source(BOUNDARY_PATH).replace(needle, '/* planted removal */');
    expect(() => assertBoundaryContract(mutant)).toThrow();
  });

  it.each([
    ['onboarding marker', "'legalsaathi.student.onboarding.v34'"],
    ['export reference', "'legalsaathi.student.privacy.export.v1'"],
    ['delete reference', "'legalsaathi.student.privacy.delete.v1'"],
    ['retired registry cleanup', "'legalsaathi.student.cleanup-registry.v1'"],
    ['bounded retired-key purge', 'export const MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH = 256;'],
    ['retired report prefix', "'ls-reports-'"],
    ['session bootstrap purge', 'export function purgeLegacyStudentSessionStorageAtBootstrap'],
    ['complete product purge', 'export function purgeCompleteLegacyBrowserLocalStorage'],
  ])('kills removal of the %s compatibility boundary', (_label, needle) => {
    const mutant = source(LEGACY_STORAGE_PATH).replace(needle, '/* planted removal */');
    expect(mutant).not.toBe(source(LEGACY_STORAGE_PATH));
    expect(() => assertLegacyStorageContract(mutant)).toThrow();
  });

  it.each([
    ['memory actor rotation', 'observedStudentActor === null || observedStudentActor.subject !== actor.subject', 'false'],
    ['unknown query preservation', '!ACTOR_INDEPENDENT_QUERY_ROOTS.has', 'ACTOR_INDEPENDENT_QUERY_ROOTS.has'],
    ['failed peer acknowledgement', "coordinator.failedTransitions.has(value.transition) ? 'nack' : 'ack'", "false ? 'nack' : 'ack'"],
  ])('kills the %s mutant', (_label, needle, replacement) => {
    const original = source(BOUNDARY_PATH);
    const mutant = original.replace(needle, replacement);
    expect(mutant).not.toBe(original);
    expect(() => assertBoundaryContract(mutant)).toThrow();
  });

  it.each([
    ['first-index cap', 'length = storage.length;', 'length = Math.min(storage.length, MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH);'],
    ['hostile length acceptance', 'if (!Number.isSafeInteger(length) || length < 0) return null;', ''],
    ['matching-key batch cap removal', 'snapshot.slice(index, index + MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH)', 'snapshot.slice(index)'],
    ['report prefix removal', "  'ls-reports-',", ''],
    ['silent no-progress verdict', 'if (removalFailed || remaining.size > 0)', 'if (removalFailed)'],
    ['replenished-generation verdict', 'if (nextGeneration === null || nextGeneration.length > 0)', 'if (nextGeneration === null)'],
  ])('kills the %s compatibility mutant', (_label, needle, replacement) => {
    const original = source(LEGACY_STORAGE_PATH);
    const mutant = original.replace(needle, replacement);
    expect(mutant).not.toBe(original);
    expect(() => assertLegacyStorageContract(mutant)).toThrow();
  });

  it.each([
    ['status-only clearing', "response.status !== 401", 'false'],
    ['body consumption', 'response.clone().json()', 'response.json()'],
    ['auth-loss code allowlist', "STUDENT_AUTH_LOSS_CODES.has(errorCode(body) ?? '')", 'response.status === 401'],
    ['auth-loss handoff retention', 'capturedDraft !== null || hasProfileReauthHandoff()', 'false'],
    ['clear removal', 'clearStudentBrowserContext({', 'void ({'],
  ])('kills the %s client mutant', (_label, needle, replacement) => {
    const original = source(CLIENT_PATH);
    const mutant = original.replace(needle, replacement);
    expect(mutant).not.toBe(original);
    expect(() => assertStudentClientContract(mutant)).toThrow();
  });

  it('kills stale discovery side effects and current-generation application removal', () => {
    const registration = source(REGISTRATION_PATH);
    const impure = registration.replace(
      'if (isAnonymousStudentSessionProjection(result)) {\n    return null;',
      'if (isAnonymousStudentSessionProjection(result)) {\n    clearStudentBrowserContext();\n    return null;',
    );
    expect(() => assertRegistrationLifecycle(impure, source(AUTH_CONTEXT_PATH))).toThrow();
    const authMutant = source(AUTH_CONTEXT_PATH).replace(
      'if (generation !== currentGeneration) return false;',
      'if (false) return false;',
    );
    expect(() => assertRegistrationLifecycle(registration, authMutant)).toThrow();
  });

  it('kills logout transition wrapping', () => {
    const mutant = source(REGISTRATION_PATH).replace(
      'export async function logoutStudent(): Promise<void> {\n  await withStudentAuthTransition(async (transition) => {',
      'export async function logoutStudent(): Promise<void> {\n  await (async () => {',
    );
    expect(mutant).not.toBe(source(REGISTRATION_PATH));
    expect(() => assertRegistrationLifecycle(mutant, source(AUTH_CONTEXT_PATH))).toThrow();
  });

  it('kills transition-owned accepted-deletion completion', () => {
    const mutant = source(SETTINGS_SCREEN_PATH).replace(
      "recordStudentAuthTransitionNotice('account_deletion_accepted');",
      '/* planted completion loss */',
    );
    expect(() => assertDeletionLifecycle(
      source(SETTINGS_API_PATH), mutant, source(V34_PATH), source(NOTICE_PATH),
    )).toThrow();
  });

  it('kills the post-deletion anonymous-session proof', () => {
    const mutant = source(SETTINGS_API_PATH).replace(
      '{ requireAnonymousAfterSuccess: true }',
      '{}',
    );
    expect(() => assertDeletionLifecycle(
      mutant, source(SETTINGS_SCREEN_PATH), source(V34_PATH), source(NOTICE_PATH),
    )).toThrow();
  });

  it.each([
    ['strict response parser', 'function requirePrivacyRequestAccepted(value: unknown)', 'function plantedLooseResponse(value: unknown)'],
    ['opaque request-id shape', "!/^[0-9a-f]{32}$/u.test(wire.request_id)", 'false'],
    ['exact 202 response status', '\n      202,', '\n      200,'],
  ])('kills the accepted-deletion %s mutant', (_label, needle, replacement) => {
    const original = source(SETTINGS_API_PATH);
    const mutant = original.replace(needle, replacement);
    expect(mutant).not.toBe(original);
    expect(() => assertDeletionLifecycle(
      mutant, source(SETTINGS_SCREEN_PATH), source(V34_PATH), source(NOTICE_PATH),
    )).toThrow();
  });
});
