import { afterEach, describe, expect, it, vi } from 'vitest';
import { FakeLockManager, stubNavigatorLocks } from '../../../test/fakeLockManager';

const NOW = '2026-09-04T10:00:00Z';
const LATER = '2026-09-04T11:00:00Z';

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

function setupBrowserBoundary(options: { locks?: boolean; channel?: boolean } = {}): FakeLockManager {
  const locks = new FakeLockManager();
  if (options.locks !== false) stubNavigatorLocks(locks);
  else vi.stubGlobal('navigator', {});
  const browserWindow = new EventTarget() as EventTarget & {
    localStorage: Storage;
    sessionStorage: Storage;
  };
  browserWindow.localStorage = emptyStorage();
  browserWindow.sessionStorage = emptyStorage();
  vi.stubGlobal('window', browserWindow);
  vi.stubGlobal('document', {});
  vi.stubGlobal('location', { origin: 'http://localhost:4173' });
  vi.stubGlobal('BroadcastChannel', options.channel === false ? undefined : TestBroadcastChannel);
  return locks;
}

function verification() {
  return {
    result: 'current_positive',
    provenanceClass: 'nyayone_reviewed_identity',
    policyVersion: 'mentor-proof.v1',
    verifiedAt: NOW,
    currentAt: NOW,
    ownershipBinding: 'tutor_profile_user_equals_actor',
  };
}

function sessionProjection(overrides: Record<string, unknown> = {}) {
  return {
    schemaVersion: 'mentor-session.v1',
    sessionClass: 'mentor',
    mentorRole: 'tutor',
    state: 'active',
    purposeCode: 'student_guidance',
    scopes: ['engagement:read', 'session:rotate', 'session:end'],
    permittedProfileSlices: ['display_name', 'preferred_language'],
    sameActorVerified: true,
    tutorProfileStatus: 'active',
    verification: verification(),
    subjectSharingEligibility: 'allowed',
    consent: {
      purposeCode: 'student_guidance',
      version: 'mentor-consent.v1',
      status: 'granted',
      recordedAt: NOW,
    },
    absoluteLifetimeSeconds: 28_800,
    idleTimeoutSeconds: 1_800,
    issuedAt: NOW,
    expiresAt: LATER,
    ...overrides,
  };
}

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function failure(code: string, status: number): Response {
  return response({ detail: { code, message: 'Request failed', retryable: false } }, status);
}

afterEach(() => {
  vi.resetModules();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  TestBroadcastChannel.reset();
});

describe('NYAY-22 mentor ceremony browser authority seam', () => {
  it('strictly rejects extra projection fields and out-of-policy lifetimes', async () => {
    const api = await import('./mentorCeremonyApi');
    expect(() => api.parseMentorSessionProjection(sessionProjection())).not.toThrow();
    expect(() => api.parseMentorSessionProjection(sessionProjection({ actorId: 'forbidden' })))
      .toThrow('MENTOR_RESPONSE_INVALID');
    expect(() => api.parseMentorSessionProjection(sessionProjection({
      absoluteLifetimeSeconds: 28_801,
    }))).toThrow('MENTOR_RESPONSE_INVALID');
    expect(() => api.parseMentorSessionProjection(sessionProjection({
      idleTimeoutSeconds: 1_801,
    }))).toThrow('MENTOR_RESPONSE_INVALID');
  });

  it('holds the shared session lease until the complete response is observed', async () => {
    const locks = setupBrowserBoundary();
    let releaseResponse!: () => void;
    vi.stubGlobal('fetch', vi.fn(async () => {
      await new Promise<void>((resolve) => { releaseResponse = resolve; });
      return response(sessionProjection());
    }));
    const boundary = await import('../../student/lib/studentBrowserContext');
    const api = await import('./mentorCeremonyApi');
    const subscription = boundary.subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: () => undefined,
    });
    await subscription.ready;

    const read = api.getMentorSession();
    await vi.waitFor(() => expect(locks.heldModes(boundary.STUDENT_AUTH_SESSION_LOCK))
      .toEqual(['shared', 'shared']));
    releaseResponse();
    await expect(read).resolves.toMatchObject({ sessionClass: 'mentor', state: 'active' });
    subscription.unsubscribe();
  });

  it('linearizes exchange then mentor probe then wrapper-owned student probe', async () => {
    setupBrowserBoundary();
    const trace: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname;
      trace.push(`${init?.method ?? 'GET'} ${path}`);
      if (path.endsWith('/ceremony/exchange')) return response(sessionProjection(), 201);
      if (path.endsWith('/auth/mentor/session')) return response(sessionProjection());
      if (path.endsWith('/auth/student/session')) {
        return response({ authenticated: false, actor: null });
      }
      return failure('RESOURCE_UNAVAILABLE', 404);
    }));
    const api = await import('./mentorCeremonyApi');

    const result = await api.exchangeMentorCeremony({
      intent: 'mentor_session',
      expectedCeremonyState: 'proof_verified',
      acceptPurpose: true,
      purposeCode: 'student_guidance',
      consentReceiptVersion: 'mentor-consent.v1',
      acceptanceTextVersion: 'mentor-acceptance.v1',
    }, 'mentor-exchange-browser-0001');

    expect(result.session?.state).toBe('active');
    expect(trace).toEqual([
      'POST /api/v1/auth/mentor/ceremony/exchange',
      'GET /api/v1/auth/mentor/session',
      'GET /api/v1/auth/student/session',
    ]);
  });

  it('rejects a successful rotation whose canonical probe is absent', async () => {
    setupBrowserBoundary();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith('/session/rotate')) return response(sessionProjection());
      if (path.endsWith('/auth/mentor/session')) return failure('AUTHENTICATION_REQUIRED', 401);
      if (path.endsWith('/auth/student/session')) {
        return response({ authenticated: false, actor: null });
      }
      return failure('RESOURCE_UNAVAILABLE', 404);
    }));
    const api = await import('./mentorCeremonyApi');
    await expect(api.rotateMentorSession({
      expectedSessionState: 'active',
      purposeCode: 'student_guidance',
      reasonCode: 'routine_rotation',
    }, 'mentor-rotate-browser-00001')).rejects.toThrow(
      'MENTOR_SESSION_POSTCONDITION_FAILED',
    );
  });

  it('rejects a successful revocation while the canonical probe remains active', async () => {
    setupBrowserBoundary();
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith('/session/revoke')) {
        return response({
          schemaVersion: 'mentor-lifecycle.v1', action: 'revoked', state: 'revoked',
          sessionAuthorityPresent: false, auditEventRecorded: true, effectiveAt: NOW,
        });
      }
      if (path.endsWith('/auth/mentor/session')) return response(sessionProjection());
      if (path.endsWith('/auth/student/session')) {
        return response({ authenticated: false, actor: null });
      }
      return failure('RESOURCE_UNAVAILABLE', 404);
    }));
    const api = await import('./mentorCeremonyApi');
    await expect(api.revokeMentorSession({
      expectedSessionState: 'active',
      purposeCode: 'student_guidance',
      reasonCode: 'mentor_requested',
    }, 'mentor-revoke-browser-00001')).rejects.toThrow(
      'MENTOR_SESSION_POSTCONDITION_FAILED',
    );
  });

  it('denies private mounting when the canonical session is anonymous', async () => {
    setupBrowserBoundary();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(failure('AUTHENTICATION_REQUIRED', 401)));
    const api = await import('./mentorCeremonyApi');
    const mount = vi.fn();
    await expect(api.withServerProvenMentorSession(mount)).rejects.toThrow(
      'MENTOR_SESSION_REQUIRED',
    );
    expect(mount).not.toHaveBeenCalled();
  });

  it('denies every private mount when Web Locks are unavailable', async () => {
    setupBrowserBoundary({ locks: false });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(sessionProjection())));
    const api = await import('./mentorCeremonyApi');
    const mount = vi.fn();
    await expect(api.withServerProvenMentorSession(mount)).rejects.toThrow(
      'student_auth_transition_unavailable',
    );
    expect(mount).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('denies every private mount when BroadcastChannel is unavailable', async () => {
    setupBrowserBoundary({ channel: false });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(sessionProjection())));
    const api = await import('./mentorCeremonyApi');
    const mount = vi.fn();
    await expect(api.withServerProvenMentorSession(mount)).rejects.toThrow(
      'student_auth_transition_unavailable',
    );
    expect(mount).not.toHaveBeenCalled();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('never accepts invalid idempotency material or leaks it in diagnostics', async () => {
    setupBrowserBoundary();
    vi.stubGlobal('fetch', vi.fn());
    const api = await import('./mentorCeremonyApi');
    let caught: unknown;
    try {
      await api.rotateMentorSession({
        expectedSessionState: 'active',
        purposeCode: 'student_guidance',
        reasonCode: 'routine_rotation',
      }, 'short');
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(api.MentorCeremonyApiError);
    expect((caught as Error).message).toBe('INVALID_IDEMPOTENCY_KEY');
    expect((caught as Error).message).not.toContain('short');
    const requestedPaths = vi.mocked(fetch).mock.calls.map(([input]) => new URL(String(input)).pathname);
    expect(requestedPaths).toEqual(['/api/v1/auth/student/session']);
    expect(requestedPaths).not.toContain('/api/v1/auth/mentor/session/rotate');
  });
});
