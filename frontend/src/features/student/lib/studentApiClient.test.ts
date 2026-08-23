import { afterEach, describe, expect, it, vi } from 'vitest';
import { queryClient } from '../../../app/queryClient';
import { studentApiFetch } from './studentApiClient';
import {
  clearStudentBrowserContext,
  STUDENT_AUTH_CHANGED_EVENT,
  STUDENT_AUTH_TRANSITION_STARTED_EVENT,
} from './studentBrowserContext';
import {
  clearProfileReauthHandoff,
  hasProfileReauthHandoff,
  resolveProfileReauthActor,
  stageActiveProfileReauthDraft,
  takeResolvedProfileReauthDraft,
} from '../profile/profileReauthHandoff';
import { FakeLockManager, stubNavigatorLocks } from '../../../test/fakeLockManager';

const ACTOR_A = '00000000-0000-4000-8000-0000000000a1';

function jsonResponse(body: unknown, status = 401): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function emptyStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, value); },
  };
}

class TestBroadcastChannel {
  static readonly channels = new Map<string, Set<TestBroadcastChannel>>();

  readonly name: string;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(name: string) {
    this.name = name;
    const peers = TestBroadcastChannel.channels.get(name) ?? new Set();
    peers.add(this);
    TestBroadcastChannel.channels.set(name, peers);
  }

  postMessage(data: unknown): void {
    for (const peer of TestBroadcastChannel.channels.get(this.name) ?? []) {
      if (peer !== this) queueMicrotask(() => peer.onmessage?.({ data } as MessageEvent));
    }
  }

  close(): void {
    TestBroadcastChannel.channels.get(this.name)?.delete(this);
  }

  static reset(): void {
    TestBroadcastChannel.channels.clear();
  }
}

afterEach(() => {
  clearProfileReauthHandoff();
  clearStudentBrowserContext();
  queryClient.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  TestBroadcastChannel.reset();
});

describe('studentApiFetch authentication lifecycle', () => {
  it.each([
    ['detail envelope', { detail: { code: 'authentication_required' } }],
    ['error envelope', { error: { code: 'authentication_required' } }],
    ['nested error detail', { error: { detail: { code: 'authentication_required' } } }],
  ])('clears on the exact typed code in the %s and leaves the original body readable', async (_label, body) => {
    const dispatchEvent = vi.fn((_event: Event) => true);
    vi.stubGlobal('window', { dispatchEvent });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(body)));
    queryClient.setQueryData(['private-student'], { owner: 'student-A' });

    const response = await studentApiFetch('/api/v1/student/private');

    expect(await response.json()).toEqual(body);
    expect(queryClient.getQueryData(['private-student'])).toBeUndefined();
    expect(dispatchEvent.mock.calls.map(([event]) => (event as Event).type)).toEqual([
      STUDENT_AUTH_TRANSITION_STARTED_EVENT,
      STUDENT_AUTH_CHANGED_EVENT,
    ]);
  });

  it.each(['authentication_required', 'session_authority_required'])(
    'preserves one active profile draft across exact %s auth loss for same-actor reauth',
    async (code) => {
      const dispatchEvent = vi.fn(() => true);
      vi.stubGlobal('window', { dispatchEvent });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: { code } })));
      stageActiveProfileReauthDraft(Symbol('personal-form'), ACTOR_A, {
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

      const response = await studentApiFetch('/api/v1/student/profile/personal', {
        method: 'PATCH',
      });

      expect(await response.json()).toEqual({ detail: { code } });
      expect(resolveProfileReauthActor(ACTOR_A)).toBe(true);
      expect(takeResolvedProfileReauthDraft(ACTOR_A, 'personal')).toEqual(expect.objectContaining({
        firstName: 'Aditi',
        city: 'Pune',
      }));
      expect(dispatchEvent).toHaveBeenCalled();
    },
  );

  it('keeps a captured draft through the delayed Web-Locks auth-loss teardown', async () => {
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = emptyStorage();
    browserWindow.sessionStorage = emptyStorage();
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', TestBroadcastChannel);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      detail: { code: 'authentication_required' },
    })));
    vi.resetModules();
    const client = await import('./studentApiClient');
    const handoff = await import('../profile/profileReauthHandoff');
    const boundary = await import('./studentBrowserContext');
    handoff.stageActiveProfileReauthDraft(Symbol('personal-form'), ACTOR_A, {
      section: 'personal',
      value: {
        firstName: 'Aditi', middleName: null, lastName: 'Rao',
        dateOfBirth: '2000-01-01', preferredLanguage: 'en', city: 'Pune', pronouns: null,
      },
    });
    const transitionEnded = new Promise<void>((resolve) => {
      browserWindow.addEventListener(boundary.STUDENT_AUTH_CHANGED_EVENT, () => resolve(), {
        once: true,
      });
    });

    await client.studentApiFetch('/api/v1/student/profile/personal', { method: 'PATCH' });
    await transitionEnded;

    expect(handoff.hasProfileReauthHandoff()).toBe(true);
    expect(handoff.resolveProfileReauthActor(ACTOR_A)).toBe(true);
    expect(handoff.takeResolvedProfileReauthDraft(ACTOR_A, 'personal')).toEqual(
      expect.objectContaining({ firstName: 'Aditi', city: 'Pune' }),
    );
  });

  it.each(['authentication_required', 'session_authority_required'])(
    'keeps the first retained draft across a second concurrent %s response',
    async (code) => {
      vi.stubGlobal('window', { dispatchEvent: vi.fn(() => true) });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: { code } })));
      stageActiveProfileReauthDraft(Symbol('personal-form'), ACTOR_A, {
        section: 'personal',
        value: {
          firstName: 'Aditi', middleName: null, lastName: 'Rao',
          dateOfBirth: '2000-01-01', preferredLanguage: 'en', city: 'Pune', pronouns: null,
        },
      });

      await studentApiFetch('/api/v1/student/profile/personal', { method: 'PATCH' });
      expect(hasProfileReauthHandoff()).toBe(true);
      await studentApiFetch('/api/v1/student/profile/academic', { method: 'PATCH' });

      expect(hasProfileReauthHandoff()).toBe(true);
      expect(resolveProfileReauthActor(ACTOR_A)).toBe(true);
      expect(takeResolvedProfileReauthDraft(ACTOR_A, 'personal')).toEqual(expect.objectContaining({
        firstName: 'Aditi', city: 'Pune',
      }));
    },
  );

  it.each([
    ['incorrect OTP', { detail: { code: 'incorrect_otp' } }],
    ['step-up required', { detail: { code: 'reauth_required' } }],
    ['near-match code', { detail: { code: 'authentication_required_later' } }],
    ['untyped 401', { detail: 'authentication_required' }],
  ])('does not clear a still-valid student context for %s', async (_label, body) => {
    const dispatchEvent = vi.fn(() => true);
    vi.stubGlobal('window', { dispatchEvent });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(body)));
    queryClient.setQueryData(['private-student'], 'retain');

    await studentApiFetch('/api/v1/auth/student/otp/verify');

    expect(queryClient.getQueryData(['private-student'])).toBe('retain');
    expect(dispatchEvent).not.toHaveBeenCalled();
  });

  it('fails closed without consuming or throwing on malformed non-JSON 401 bodies', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('not-json', { status: 401 })));
    queryClient.setQueryData(['private-student'], 'retain-until-typed-proof');

    const response = await studentApiFetch('/api/v1/auth/student/otp/verify');

    expect(await response.text()).toBe('not-json');
    expect(queryClient.getQueryData(['private-student'])).toBe('retain-until-typed-proof');
  });

  it('can suppress notification for the session bootstrap while still clearing', async () => {
    const dispatchEvent = vi.fn(() => true);
    vi.stubGlobal('window', { dispatchEvent });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
      detail: { code: 'authentication_required' },
    })));
    queryClient.setQueryData(['private-student'], 'clear');

    await studentApiFetch(
      '/api/v1/auth/student/session',
      {},
      { notifyAuthChanged: false },
    );

    expect(queryClient.getQueryData(['private-student'])).toBeUndefined();
    expect(dispatchEvent).not.toHaveBeenCalled();
  });
});
