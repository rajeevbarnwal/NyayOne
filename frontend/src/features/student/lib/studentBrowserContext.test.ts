import { afterEach, describe, expect, it, vi } from 'vitest';
import { queryClient } from '../../../app/queryClient';
import { getProfileDraft, updateProfileDraft } from './profileStore';
import {
  clearRegistrationAttempt,
  getRegistrationAttempt,
  setRegistrationAttempt,
} from './registrationAttemptStore';
import {
  STUDENT_AUTH_CHANGED_EVENT,
  STUDENT_CONTEXT_REGISTRY_KEY,
  clearStudentBrowserContext,
  observeStudentSessionActor,
} from './studentBrowserContext';

function mapStorage(map: Map<string, string>, clear = vi.fn(() => map.clear())): Storage {
  return {
    get length() { return map.size; },
    clear,
    getItem: (key) => map.get(key) ?? null,
    key: (index) => [...map.keys()][index] ?? null,
    removeItem: (key) => { map.delete(key); },
    setItem: (key, value) => { map.set(key, value); },
  };
}

afterEach(() => {
  clearStudentBrowserContext();
  clearRegistrationAttempt();
  queryClient.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('NYAY-19 student browser-context boundary', () => {
  it('retires exact active-student memory, cache, refs and storage but preserves device preferences', () => {
    const local = new Map<string, string>([
      ['legalsaathi.student.profile.v1', '{"firstName":"Aditi"}'],
      ['legalsaathi.student.onboarding.v34', 'seen'],
      ['legalsaathi.internship.applications.v1', '[{"id":"application"}]'],
      ['legalsaathi.clinical.export-audit.v1', '[{"event":"export"}]'],
      ['ls-auth-student', '{"phase":"verified"}'],
      ['ls-reports-student-A', '{"reports":{"private":true}}'],
      ['ls-reminder-prefs-profile-A', '{"prefs":["private"]}'],
      ['ls-theme', 'dark'],
      ['ls-locale', 'hi'],
      ['ls-reviewer', '{"device":"unrelated"}'],
    ]);
    const session = new Map<string, string>([
      ['legalsaathi.student.registration.v2', 'retired-registration'],
      ['legalsaathi.student.privacy.export.v1', 'opaque-export'],
      ['legalsaathi.student.privacy.delete.v1', 'opaque-delete'],
      ['unrelated-session-key', 'keep'],
    ]);
    const localClear = vi.fn();
    const sessionClear = vi.fn();
    const dispatchEvent = vi.fn((_event: Event) => true);
    vi.stubGlobal('window', {
      localStorage: mapStorage(local, localClear),
      sessionStorage: mapStorage(session, sessionClear),
      dispatchEvent,
    });

    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    setRegistrationAttempt({ body: '{"mobile":"private"}', key: 'idem-private' });
    updateProfileDraft({ firstName: 'Aditi', dateOfBirth: '2004-03-14' });
    queryClient.setQueryData(['student-profile'], { maskedMobile: '••••••3210' });
    queryClient.getMutationCache().build(queryClient, {
      mutationKey: ['student-settings'],
      mutationFn: async () => ({ private: true }),
    });

    clearStudentBrowserContext({ notifyAuthChanged: true });

    expect(getRegistrationAttempt()).toBeNull();
    expect(getProfileDraft().firstName).toBe('');
    expect(getProfileDraft().dateOfBirth).toBe('');
    expect(queryClient.getQueryCache().getAll()).toEqual([]);
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
    expect([...local.entries()]).toEqual([
      ['ls-theme', 'dark'],
      ['ls-locale', 'hi'],
      ['ls-reviewer', '{"device":"unrelated"}'],
    ]);
    expect([...session.entries()]).toEqual([['unrelated-session-key', 'keep']]);
    expect(localClear).not.toHaveBeenCalled();
    expect(sessionClear).not.toHaveBeenCalled();
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
    expect((dispatchEvent.mock.calls[0][0] as Event).type).toBe(STUDENT_AUTH_CHANGED_EVENT);
  });

  it('still erases memory and query state when both Storage getters are inaccessible', () => {
    setRegistrationAttempt({ body: 'uncertain-body', key: 'uncertain-key' });
    updateProfileDraft({ firstName: 'Private' });
    queryClient.setQueryData(['private'], 'value');
    const inaccessibleWindow = {
      get localStorage(): Storage { throw new DOMException('denied'); },
      get sessionStorage(): Storage { throw new DOMException('denied'); },
      dispatchEvent: vi.fn(() => true),
    };
    vi.stubGlobal('window', inaccessibleWindow);

    expect(() => clearStudentBrowserContext({ notifyAuthChanged: true })).not.toThrow();
    expect(getRegistrationAttempt()).toBeNull();
    expect(getProfileDraft().firstName).toBe('');
    expect(queryClient.getQueryData(['private'])).toBeUndefined();
    expect(inaccessibleWindow.dispatchEvent).toHaveBeenCalledTimes(1);
  });

  it('clears actor A before recording actor B and removes only A dynamic keys', () => {
    const local = new Map<string, string>([
      ['ls-reports-student-A', 'A'],
      ['ls-reminder-prefs-profile-A', 'A'],
      ['ls-reports-student-B', 'B'],
      ['ls-theme', 'light'],
    ]);
    vi.stubGlobal('window', {
      localStorage: mapStorage(local),
      sessionStorage: mapStorage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    queryClient.setQueryData(['private-A'], { owner: 'A' });

    observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });

    expect(queryClient.getQueryData(['private-A'])).toBeUndefined();
    expect(local.has('ls-reports-student-A')).toBe(false);
    expect(local.has('ls-reminder-prefs-profile-A')).toBe(false);
    expect(local.get('ls-reports-student-B')).toBe('B');
    expect(local.get('ls-theme')).toBe('light');
    expect(JSON.parse(local.get(STUDENT_CONTEXT_REGISTRY_KEY) ?? 'null')).toEqual([
      'ls-reports-student-B',
      'ls-reminder-prefs-student-B',
      'ls-reports-profile-B',
      'ls-reminder-prefs-profile-B',
    ]);
  });

  it('retires only the registered current actor after a full module reload', async () => {
    const local = new Map<string, string>([
      ['ls-reports-student-A', 'private-report-A'],
      ['ls-reminder-prefs-profile-A', 'private-reminder-A'],
      ['ls-reports-student-B', 'private-report-B'],
      ['ls-theme', 'dark'],
      ['ls-locale', 'hi'],
    ]);
    vi.stubGlobal('window', {
      localStorage: mapStorage(local),
      sessionStorage: mapStorage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });

    vi.resetModules();
    const activeRealm = await import('./studentBrowserContext');
    activeRealm.observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    expect(local.has(STUDENT_CONTEXT_REGISTRY_KEY)).toBe(true);

    // A new JS realm has no in-memory observed actor. An anonymous/expired
    // server session must still retire only the exact actor registered earlier.
    vi.resetModules();
    const restartedRealm = await import('./studentBrowserContext');
    restartedRealm.clearStudentBrowserContext();

    expect(local.has('ls-reports-student-A')).toBe(false);
    expect(local.has('ls-reminder-prefs-profile-A')).toBe(false);
    expect(local.has(STUDENT_CONTEXT_REGISTRY_KEY)).toBe(false);
    expect(local.get('ls-reports-student-B')).toBe('private-report-B');
    expect(local.get('ls-theme')).toBe('dark');
    expect(local.get('ls-locale')).toBe('hi');
  });

  it('a stale actor realm never consumes a newer cross-tab actor registry', async () => {
    const local = new Map<string, string>([
      ['ls-reports-student-A', 'private-report-A'],
      ['ls-reminder-prefs-student-A', 'private-reminder-A'],
      ['ls-theme', 'dark'],
    ]);
    vi.stubGlobal('window', {
      localStorage: mapStorage(local),
      sessionStorage: mapStorage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });

    vi.resetModules();
    const staleActorRealm = await import('./studentBrowserContext');
    staleActorRealm.observeStudentSessionActor({ subject: 'student-A', studentProfileId: null });

    vi.resetModules();
    const activeActorRealm = await import('./studentBrowserContext');
    activeActorRealm.observeStudentSessionActor({ subject: 'student-B', studentProfileId: null });
    local.set('ls-reports-student-B', 'private-report-B');
    local.set('ls-reminder-prefs-student-B', 'private-reminder-B');

    // StrictMode can resolve the stale realm anonymous more than once. Its
    // remembered A identity must preserve B's exact keys and cleanup registry.
    staleActorRealm.clearStudentBrowserContext();
    staleActorRealm.clearStudentBrowserContext();
    expect(local.get('ls-reports-student-B')).toBe('private-report-B');
    expect(local.get('ls-reminder-prefs-student-B')).toBe('private-reminder-B');
    expect(JSON.parse(local.get(STUDENT_CONTEXT_REGISTRY_KEY) ?? 'null')).toEqual([
      'ls-reports-student-B',
      'ls-reminder-prefs-student-B',
    ]);
    expect(local.get('ls-theme')).toBe('dark');

    // The server-current B realm (or an accepted terminal mutation) owns B.
    activeActorRealm.clearStudentBrowserContext({ consumeRegisteredActor: true });
    expect(local.has('ls-reports-student-B')).toBe(false);
    expect(local.has('ls-reminder-prefs-student-B')).toBe(false);
    expect(local.has(STUDENT_CONTEXT_REGISTRY_KEY)).toBe(false);
  });

  it.each([
    ['malformed JSON', '{'],
    ['wrong cardinality', JSON.stringify(['ls-reports-student-A'])],
    ['duplicate keys', JSON.stringify([
      'ls-reports-student-A',
      'ls-reminder-prefs-student-A',
      'ls-reports-student-A',
      'ls-reminder-prefs-student-A',
    ])],
    ['cross-prefix key', JSON.stringify([
      'ls-reports-student-A',
      'ls-theme',
    ])],
    ['mismatched pair', JSON.stringify([
      'ls-reports-student-A',
      'ls-reminder-prefs-student-B',
    ])],
    ['unsafe actor id', JSON.stringify([
      'ls-reports-../student-A',
      'ls-reminder-prefs-../student-A',
    ])],
  ])('fails closed for a %s cleanup registry', (_label, registry) => {
    const local = new Map<string, string>([
      [STUDENT_CONTEXT_REGISTRY_KEY, registry],
      ['ls-reports-student-A', 'private-report-A'],
      ['ls-reminder-prefs-student-A', 'private-reminder-A'],
      ['ls-theme', 'dark'],
    ]);
    vi.stubGlobal('window', {
      localStorage: mapStorage(local),
      sessionStorage: mapStorage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });

    clearStudentBrowserContext();

    expect(local.has(STUDENT_CONTEXT_REGISTRY_KEY)).toBe(false);
    expect(local.get('ls-reports-student-A')).toBe('private-report-A');
    expect(local.get('ls-reminder-prefs-student-A')).toBe('private-reminder-A');
    expect(local.get('ls-theme')).toBe('dark');
  });

  it('does not clear a cache merely because the same actor gains a profile id', () => {
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: null });
    queryClient.setQueryData(['same-actor'], 'keep');
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    expect(queryClient.getQueryData(['same-actor'])).toBe('keep');
  });

  it('does not let in-flight query or mutation results repopulate the global caches', async () => {
    let resolveQuery!: (value: { owner: string }) => void;
    let resolveMutation!: (value: { owner: string }) => void;
    const queryPromise = queryClient.fetchQuery({
      queryKey: ['actor-A-query'],
      queryFn: () => new Promise<{ owner: string }>((resolve) => { resolveQuery = resolve; }),
    }).then(() => 'resolved', () => 'cancelled');
    const mutation = queryClient.getMutationCache().build(queryClient, {
      mutationKey: ['actor-A-mutation'],
      mutationFn: () => new Promise<{ owner: string }>((resolve) => { resolveMutation = resolve; }),
    });
    const mutationPromise = mutation.execute(undefined).then(() => 'resolved', () => 'cancelled');
    await Promise.resolve();

    clearStudentBrowserContext();
    resolveQuery({ owner: 'A' });
    resolveMutation({ owner: 'A' });
    await Promise.all([queryPromise, mutationPromise]);

    expect(queryClient.getQueryCache().getAll()).toEqual([]);
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
  });
});
