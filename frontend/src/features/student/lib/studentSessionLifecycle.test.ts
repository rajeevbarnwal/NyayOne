import { afterEach, describe, expect, it, vi } from 'vitest';
import { queryClient } from '../../../app/queryClient';
import { getProfileDraft, updateProfileDraft } from './profileStore';
import { getRegistrationAttempt, setRegistrationAttempt } from './registrationAttemptStore';
import { getStudentSession, logoutStudent } from './registrationApi';
import {
  STUDENT_CONTEXT_REGISTRY_KEY,
  clearStudentBrowserContext,
  observeStudentSessionActor,
} from './studentBrowserContext';

function storage(map: Map<string, string>): Storage {
  return {
    get length() { return map.size; },
    clear: () => map.clear(),
    getItem: (key) => map.get(key) ?? null,
    key: (index) => [...map.keys()][index] ?? null,
    removeItem: (key) => { map.delete(key); },
    setItem: (key, value) => { map.set(key, value); },
  };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function seedPrivateContext() {
  setRegistrationAttempt({ body: 'private-registration', key: 'private-idempotency' });
  updateProfileDraft({ firstName: 'Aditi', dateOfBirth: '2004-03-14' });
  queryClient.setQueryData(['private-query'], { mobile: '••••••3210' });
  queryClient.getMutationCache().build(queryClient, {
    mutationKey: ['private-mutation'],
    mutationFn: async () => 'private',
  });
}

afterEach(() => {
  clearStudentBrowserContext();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('student session lifecycle teardown', () => {
  it('treats an anonymous session discovery as a full browser-context boundary', async () => {
    const local = new Map<string, string>([
      ['legalsaathi.student.onboarding.v34', 'seen'],
      ['legalsaathi.internship.applications.v1', 'private'],
      ['ls-theme', 'dark'],
      ['ls-locale', 'en'],
    ]);
    const session = new Map<string, string>([
      ['legalsaathi.student.privacy.export.v1', 'opaque-ref'],
    ]);
    vi.stubGlobal('window', {
      localStorage: storage(local),
      sessionStorage: storage(session),
      dispatchEvent: vi.fn(() => true),
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      authenticated: false,
      actor: null,
    })));
    seedPrivateContext();

    await expect(getStudentSession()).resolves.toBeNull();

    expect(getRegistrationAttempt()).toBeNull();
    expect(getProfileDraft().firstName).toBe('');
    expect(queryClient.getQueryCache().getAll()).toEqual([]);
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
    expect(local.has('legalsaathi.student.onboarding.v34')).toBe(false);
    expect(local.has('legalsaathi.internship.applications.v1')).toBe(false);
    expect(session.has('legalsaathi.student.privacy.export.v1')).toBe(false);
    expect(local.get('ls-theme')).toBe('dark');
    expect(local.get('ls-locale')).toBe('en');
  });

  it.each([
    ['null authenticated actor', { authenticated: true, actor: null }],
    ['non-student actor', {
      authenticated: true,
      actor: {
        sub: 'actor', roles: ['lawyer'], student_profile_id: null,
        student_verification: 'draft', is_minor: false, consent_state: [],
      },
    }],
    ['malformed consent state', {
      authenticated: true,
      actor: {
        sub: 'actor', roles: ['student'], student_profile_id: null,
        student_verification: 'draft', is_minor: false, consent_state: 'registration',
      },
    }],
  ])('fails closed and clears for %s', async (_label, sessionBody) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(sessionBody)));
    seedPrivateContext();
    await expect(getStudentSession()).resolves.toBeNull();
    expect(getRegistrationAttempt()).toBeNull();
    expect(queryClient.getQueryCache().getAll()).toEqual([]);
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
  });

  it('clears and notifies exactly once even when the logout request fails', async () => {
    const dispatchEvent = vi.fn(() => true);
    vi.stubGlobal('window', { dispatchEvent });
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network unavailable')));
    seedPrivateContext();

    await expect(logoutStudent()).rejects.toThrow('network unavailable');

    expect(getRegistrationAttempt()).toBeNull();
    expect(queryClient.getQueryCache().getAll()).toEqual([]);
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
  });

  it('a failed stale-actor logout preserves the newer cross-tab actor registry', async () => {
    const local = new Map<string, string>();
    const dispatchEvent = vi.fn(() => true);
    vi.stubGlobal('window', {
      localStorage: storage(local),
      sessionStorage: storage(new Map()),
      dispatchEvent,
    });
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: null });
    local.set(STUDENT_CONTEXT_REGISTRY_KEY, JSON.stringify([
      'ls-reports-student-B',
      'ls-reminder-prefs-student-B',
    ]));
    local.set('ls-reports-student-B', 'private-report-B');
    local.set('ls-reminder-prefs-student-B', 'private-reminder-B');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network unavailable')));

    await expect(logoutStudent()).rejects.toThrow('network unavailable');

    expect(local.get('ls-reports-student-B')).toBe('private-report-B');
    expect(local.get('ls-reminder-prefs-student-B')).toBe('private-reminder-B');
    expect(local.has(STUDENT_CONTEXT_REGISTRY_KEY)).toBe(true);
    expect(dispatchEvent).toHaveBeenCalledTimes(1);
  });
});
