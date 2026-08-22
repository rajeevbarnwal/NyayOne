import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const source = (path: string) => readFileSync(join(process.cwd(), path), 'utf8');

const BOUNDARY_PATH = 'src/features/student/lib/studentBrowserContext.ts';
const CLIENT_PATH = 'src/features/student/lib/studentApiClient.ts';
const REGISTRATION_PATH = 'src/features/student/lib/registrationApi.ts';
const SETTINGS_API_PATH = 'src/features/student/lib/settingsApi.ts';
const SETTINGS_SCREEN_PATH = 'src/features/student/settings/SettingsScreens.tsx';
const V34_PATH = 'src/features/student/auth/V34Screens.tsx';
const V34_BROWSER_GATE_PATH = 'scripts/v34-s11-s26-e2e.mjs';

function assertBoundaryContract(value: string): void {
  for (const required of [
    'clearRegistrationAttempt();',
    'resetProfileDraft();',
    'clearActorSensitiveQueryState();',
    "const ACTOR_INDEPENDENT_QUERY_ROOTS = new Set(['public-internship-risk-labels']);",
    'predicate: (query) => !ACTOR_INDEPENDENT_QUERY_ROOTS.has(String(query.queryKey[0] ?? \'\'))',
    'queryClient.getMutationCache().clear();',
    "'legalsaathi.student.profile.v1'",
    "'legalsaathi.student.onboarding.v34'",
    "'legalsaathi.internship.applications.v1'",
    "'legalsaathi.clinical.export-audit.v1'",
    "'legalsaathi.student.registration.v2'",
    "'legalsaathi.student.privacy.export.v1'",
    "'legalsaathi.student.privacy.delete.v1'",
    "'ls-auth-student'",
    '`ls-reports-${id}`',
    '`ls-reminder-prefs-${id}`',
    "  'legalsaathi.student.cleanup-registry.v1',\n] as const;",
    'const RETIRED_ACTOR_PREFIXES = [REPORT_KEY_PREFIX, REMINDER_KEY_PREFIX] as const;',
    'export const MAX_RETIRED_STUDENT_KEYS_PER_PURGE = 256;',
    'length = Math.min(storage.length, MAX_RETIRED_STUDENT_KEYS_PER_PURGE);',
    'RETIRED_ACTOR_PREFIXES.some((prefix) => key.startsWith(prefix))',
    '...retiredActorKeys(local)',
  ]) {
    expect(value, `missing browser-context boundary: ${required}`).toContain(required);
  }
  expect(value).toMatch(/let observedStudentActor: ObservedStudentActor \| null = null/);
  expect(value).toMatch(/observedStudentActor !== null && observedStudentActor\.subject !== actor\.subject/);
  expect(value).toMatch(/if \(options\.notifyAuthChanged\) notifyStudentAuthChanged\(\);/);
  expect(value).not.toMatch(/(?:localStorage|sessionStorage|\bstorage)\.clear\s*\(/);
  expect(value).not.toMatch(/setItem\s*\([^\n]*cleanup-registry/);
  expect(value).not.toMatch(/getItem\s*\([^\n]*cleanup-registry/);
  expect(value).not.toMatch(/removeItem\s*\(\s*['"]ls-(?:theme|locale)['"]\s*\)/);
}

function assertStudentClientContract(value: string): void {
  expect(value).toMatch(/response\.status !== 401/);
  expect(value).toMatch(/response\.clone\(\)\.json\(\)/);
  expect(value).toMatch(/errorCode\(body\) === ['"]authentication_required['"]/);
  expect(value).toMatch(/clearStudentBrowserContext\(\{ notifyAuthChanged:/);
}

function assertRegistrationLifecycle(value: string): void {
  expect(value).toMatch(/verifyLoginOtp[\s\S]*state\.status === ['"]authenticated['"][\s\S]*clearStudentBrowserContext\(\)/);
  expect(value).toMatch(/getStudentSession[\s\S]*!isStudentSessionActor\(result\.actor\)[\s\S]*clearStudentBrowserContext\(\)[\s\S]*return null/);
  expect(value).toMatch(/getStudentSession[\s\S]*observeStudentSessionActor\(\{[\s\S]*subject: result\.actor\.sub/);
  expect(value).toMatch(/logoutStudent[\s\S]*let accepted = false;[\s\S]*await jsonRequest[\s\S]*accepted = true;[\s\S]*finally \{[\s\S]*clearStudentBrowserContext\(\{[\s\S]*notifyAuthChanged: true,[\s\S]*consumeRegisteredActor: accepted/);
}

function assertDeletionLifecycle(api: string, screen: string, authGate: string): void {
  expect(api).toMatch(/requestAccountDeletion[\s\S]*clearStudentBrowserContext\(\{[\s\S]*notifyAuthChanged: true,[\s\S]*consumeRegisteredActor: true[\s\S]*return \{ requestId/);
  const success = screen.match(/const deleteMut = useMutation\(\{[\s\S]*?onSuccess:[\s\S]*?onError:/)?.[0] ?? '';
  expect(success).toContain('deletePoll.clear();');
  expect(success).toContain("nav('/s-03'");
  expect(success).toContain('studentDeletionAccepted: true');
  expect(success).not.toContain('deletePoll.track(');
  expect(authGate).toContain('DELETION REQUEST ACCEPTED');
  expect(authGate).toContain('studentDeletionAccepted');
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
    expect(credentials).toMatch(/actor === ['"]student['"][\s\S]*studentApiFetch[\s\S]*apiFetch/);
    expect(source('src/features/student/lib/riskLabelsApi.ts')).not.toContain('studentApiFetch');
  });

  it('pins anonymous/invalid, rotation, logout and deletion lifecycle wiring', () => {
    assertRegistrationLifecycle(source(REGISTRATION_PATH));
    assertDeletionLifecycle(
      source(SETTINGS_API_PATH),
      source(SETTINGS_SCREEN_PATH),
      source(V34_PATH),
    );
  });

  it('gives the authenticated browser gate a complete server session actor', () => {
    const gate = source(V34_BROWSER_GATE_PATH);
    const session = gate.match(
      /if \(url\.pathname === '\/api\/v1\/auth\/student\/session'\)([\s\S]*?)if \(url\.pathname === '\/api\/v1\/student\/settings'\)/,
    )?.[1] ?? '';
    for (const field of [
      "sub: 'student-browser-gate'",
      "roles: ['student']",
      "student_profile_id: 'profile-browser-gate'",
      "student_verification: 'verified'",
      'is_minor: false',
      "consent_state: ['registration']",
    ]) {
      expect(session, `missing browser-gate session field: ${field}`).toContain(field);
    }
  });

  it.each([
    ['registration memory', 'clearRegistrationAttempt();'],
    ['profile draft', 'resetProfileDraft();'],
    ['actor-sensitive query cache', 'clearActorSensitiveQueryState();'],
    ['public-query root inventory', "const ACTOR_INDEPENDENT_QUERY_ROOTS = new Set(['public-internship-risk-labels']);"],
    ['mutation cache', 'queryClient.getMutationCache().clear();'],
    ['onboarding marker', "'legalsaathi.student.onboarding.v34'"],
    ['export reference', "'legalsaathi.student.privacy.export.v1'"],
    ['delete reference', "'legalsaathi.student.privacy.delete.v1'"],
    ['report actor key', '`ls-reports-${id}`'],
    ['reminder actor key', '`ls-reminder-prefs-${id}`'],
    ['retired registry cleanup', "  'legalsaathi.student.cleanup-registry.v1',\n] as const;"],
    ['bounded retired-key purge', 'export const MAX_RETIRED_STUDENT_KEYS_PER_PURGE = 256;'],
    ['retired prefix inventory', 'const RETIRED_ACTOR_PREFIXES = [REPORT_KEY_PREFIX, REMINDER_KEY_PREFIX] as const;'],
    ['retired prefix purge', '...retiredActorKeys(local)'],
  ])('kills removal of the %s boundary', (_label, needle) => {
    const mutant = source(BOUNDARY_PATH).replace(needle, '/* planted removal */');
    expect(() => assertBoundaryContract(mutant)).toThrow();
  });

  it.each([
    ['unbounded purge', 'Math.min(storage.length, MAX_RETIRED_STUDENT_KEYS_PER_PURGE)', 'storage.length'],
    ['report prefix removal', 'RETIRED_ACTOR_PREFIXES = [REPORT_KEY_PREFIX, REMINDER_KEY_PREFIX]', 'RETIRED_ACTOR_PREFIXES = [REMINDER_KEY_PREFIX]'],
    ['memory actor rotation', 'observedStudentActor !== null && observedStudentActor.subject !== actor.subject', 'false'],
    ['unknown query preservation', '!ACTOR_INDEPENDENT_QUERY_ROOTS.has', 'ACTOR_INDEPENDENT_QUERY_ROOTS.has'],
  ])('kills the %s mutant', (_label, needle, replacement) => {
    const original = source(BOUNDARY_PATH);
    const mutant = original.replace(needle, replacement);
    expect(mutant).not.toBe(original);
    expect(() => assertBoundaryContract(mutant)).toThrow();
  });

  it.each([
    ['status-only clearing', "response.status !== 401", 'false'],
    ['body consumption', 'response.clone().json()', 'response.json()'],
    ['inexact auth code', "errorCode(body) === 'authentication_required'", 'response.status === 401'],
    ['clear removal', 'clearStudentBrowserContext({ notifyAuthChanged:', 'void ({ notifyAuthChanged:'],
  ])('kills the %s client mutant', (_label, needle, replacement) => {
    const mutant = source(CLIENT_PATH).replace(needle, replacement);
    expect(() => assertStudentClientContract(mutant)).toThrow();
  });

  it('kills anonymous-session cleanup removal', () => {
    const mutant = source(REGISTRATION_PATH).replace(
      'clearStudentBrowserContext();\n    return null;',
      'return null; /* planted stale context */',
    );
    expect(() => assertRegistrationLifecycle(mutant)).toThrow();
  });

  it('kills logout cleanup removal', () => {
    const mutant = source(REGISTRATION_PATH).replace(
      /clearStudentBrowserContext\(\{\s*notifyAuthChanged: true,\s*consumeRegisteredActor: accepted,\s*\}\);/,
      '/* planted logout cleanup removal */',
    );
    expect(() => assertRegistrationLifecycle(mutant)).toThrow();
  });

  it('kills logout acceptance binding removal', () => {
    const original = source(REGISTRATION_PATH);
    const mutant = original.replace('    accepted = true;\n', '');
    expect(mutant).not.toBe(original);
    expect(() => assertRegistrationLifecycle(mutant)).toThrow();
  });

  it('kills accepted-deletion ref revival', () => {
    const mutant = source(SETTINGS_SCREEN_PATH).replace(
      'deletePoll.clear();',
      "deletePoll.track('planted-stale-ref');",
    );
    expect(() => assertDeletionLifecycle(
      source(SETTINGS_API_PATH), mutant, source(V34_PATH),
    )).toThrow();
  });

  it('kills accepted-deletion browser cleanup removal', () => {
    const mutant = source(SETTINGS_API_PATH).replace(
      /clearStudentBrowserContext\(\{\s*notifyAuthChanged: true,\s*consumeRegisteredActor: true,\s*\}\);/,
      '/* planted deletion cleanup removal */',
    );
    expect(() => assertDeletionLifecycle(
      mutant, source(SETTINGS_SCREEN_PATH), source(V34_PATH),
    )).toThrow();
  });
});
