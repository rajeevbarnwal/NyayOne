import { afterEach, describe, expect, it, vi } from 'vitest';
import { queryClient } from '../../../app/queryClient';
import {
  createProjectionMutationOptions,
  STUDENT_PROFILE_QUERY_KEY,
} from '../profile/profileHooks';
import { getProfileDraft, updateProfileDraft } from './profileStore';
import {
  ProfileApiError,
  type ProfileMutationResult,
  type StudentProfileProjection,
} from './profileApi';
import { loadSubmittedApplications, saveSubmittedApplication } from './internships';
import {
  clearRegistrationAttempt,
  getRegistrationAttempt,
  setRegistrationAttempt,
} from './registrationAttemptStore';
import {
  STUDENT_AUTH_SESSION_LOCK,
  STUDENT_AUTH_TRANSITION_CHANNEL,
  STUDENT_AUTH_TRANSITION_STARTED_EVENT,
  STUDENT_AUTH_CHANGED_EVENT,
  MAX_RETIRED_STUDENT_KEYS_PER_PURGE,
  clearStudentBrowserContext,
  observeStudentSessionActor,
  retireLegacyStudentRegistrationState,
} from './studentBrowserContext';
import { FakeLockManager, stubNavigatorLocks } from '../../../test/fakeLockManager';
import {
  captureActiveProfileReauthDraft,
  clearProfileReauthHandoff,
  hasProfileReauthHandoff,
  restoreCapturedProfileReauthDraft,
  stageActiveProfileReauthDraft,
} from '../profile/profileReauthHandoff';

const REAUTH_ACTOR = '00000000-0000-4000-8000-0000000000a1';

function retainReauthDraft(): void {
  stageActiveProfileReauthDraft(Symbol('profile-form'), REAUTH_ACTOR, {
    section: 'interests',
    value: { interests: ['Corporate'], goals: ['Corporate / in-house'] },
  });
  const captured = captureActiveProfileReauthDraft();
  clearProfileReauthHandoff();
  restoreCapturedProfileReauthDraft(captured!);
}

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

class FakeBroadcastChannel {
  static readonly channels = new Map<string, Set<FakeBroadcastChannel>>();

  readonly name: string;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(name: string) {
    this.name = name;
    const peers = FakeBroadcastChannel.channels.get(name) ?? new Set();
    peers.add(this);
    FakeBroadcastChannel.channels.set(name, peers);
  }

  postMessage(data: unknown): void {
    for (const peer of FakeBroadcastChannel.channels.get(this.name) ?? []) {
      if (peer === this) continue;
      queueMicrotask(() => peer.onmessage?.({ data } as MessageEvent));
    }
  }

  close(): void {
    FakeBroadcastChannel.channels.get(this.name)?.delete(this);
  }

  static reset(): void {
    FakeBroadcastChannel.channels.clear();
  }
}

function actorProjection(firstName: string, profileVersion: number): StudentProfileProjection {
  return {
    profileVersion,
    completionVersion: 'v1',
    completionPercent: 0,
    completedSections: [],
    missingRequirements: [
      'academic.college',
      'academic.year_of_study',
      'academic.enrolment_number',
      'interests.interests',
      'interests.goals',
    ],
    nextIncompleteSection: 'personal',
    isComplete: false,
    institutionalEmailStatus: 'not_provided',
    guardian: { required: false, status: 'not_required' },
    accessMode: 'full',
    disabledCapabilities: [],
    profilePrompt: { shouldShow: true, dismissedForSession: false },
    profile: {
      personal: {
        firstName, middleName: null, lastName: 'Owner', dateOfBirth: '2000-01-01',
        preferredLanguage: 'en', city: 'Pune', pronouns: null,
      },
      academic: {
        college: null, yearOfStudy: null, enrolmentNumber: null,
        institutionalEmail: null, barEnrolmentNumber: null,
      },
      interests: { interests: [], goals: [] },
    },
  };
}

function incompleteProfileWire(firstName: string, profileVersion: number): object {
  return {
    profile_version: profileVersion,
    completion_version: 'v1',
    completion_percent: 0,
    completed_sections: [],
    missing_requirements: [
      'personal.preferred_language',
      'personal.city',
      'academic.college',
      'academic.year_of_study',
      'academic.enrolment_number',
      'interests.interests',
      'interests.goals',
    ],
    next_incomplete_section: 'personal',
    is_complete: false,
    institutional_email_status: 'not_provided',
    guardian: { required: false, status: 'not_required' },
    access_mode: 'full',
    disabled_capabilities: [],
    profile_prompt: { should_show: true, dismissed_for_session: false },
    profile: {
      personal: {
        first_name: firstName,
        middle_name: null,
        last_name: 'Owner',
        date_of_birth: '2000-01-01',
        preferred_language: null,
        city: null,
        pronouns: null,
      },
      academic: {
        college: null,
        year_of_study: null,
        enrolment_number: null,
        institutional_email: null,
        bar_enrolment_number: null,
      },
      interests: { interests: [], goals: [] },
    },
  };
}

afterEach(() => {
  clearProfileReauthHandoff();
  clearStudentBrowserContext();
  clearRegistrationAttempt();
  queryClient.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  FakeBroadcastChannel.reset();
});

describe('NYAY-19 student browser-context boundary', () => {
  it('uses only NyayOne-owned transient coordination names', () => {
    expect(STUDENT_AUTH_SESSION_LOCK).toBe('nyayone.student.auth-session.v1');
    expect(STUDENT_AUTH_TRANSITION_CHANNEL).toBe('nyayone.student.auth-transition.v2');
    expect(STUDENT_AUTH_TRANSITION_STARTED_EVENT).toBe('nyayone:student-auth-transition-started');
    expect(STUDENT_AUTH_CHANGED_EVENT).toBe('nyayone:student-auth-changed');
    expect(MAX_RETIRED_STUDENT_KEYS_PER_PURGE).toBe(256);
  });

  it('keeps cookie rotation behind an in-flight shared request lease', async () => {
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = mapStorage(new Map());
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: () => undefined,
    });
    await subscription.ready;
    let finishRequest!: () => void;
    const request = realm.withStudentAuthRequestLease(async () => {
      await new Promise<void>((resolve) => { finishRequest = resolve; });
      return 'response';
    });
    await vi.waitFor(() => expect(locks.heldModes(realm.STUDENT_AUTH_SESSION_LOCK)).toEqual([
      'shared', 'shared',
    ]));

    const transition = realm.startStudentAuthTransition();
    const transitionRun = transition.run(async () => undefined);
    let rotationReady = false;
    void transition.ready.then(() => { rotationReady = true; });
    await vi.waitFor(() => {
      expect(locks.heldModes(realm.STUDENT_AUTH_SESSION_LOCK)).toEqual(['shared']);
      expect(locks.queuedModes(realm.STUDENT_AUTH_SESSION_LOCK)).toEqual(['exclusive']);
    });

    expect(rotationReady).toBe(false);

    finishRequest();
    await expect(request).resolves.toBe('response');
    await transition.ready;
    await transitionRun;
    expect(locks.heldModes(realm.STUDENT_AUTH_SESSION_LOCK)).toEqual(['exclusive']);
    await realm.finishStudentAuthTransition(transition);
    subscription.unsubscribe();
  });

  it('lets an already-dispatched profile GET settle under its shared lease without publishing it to a replacement actor', async () => {
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = mapStorage(new Map());
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    vi.resetModules();
    const { queryClient: realmQueryClient } = await import('../../../app/queryClient');
    const realm = await import('./studentBrowserContext');
    const {
      STUDENT_PROFILE_QUERY_KEY: realmProfileQueryKey,
      STUDENT_PROFILE_QUERY_OPTIONS: realmProfileQueryOptions,
    } = await import('../profile/profileHooks');
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: () => undefined,
    });
    await subscription.ready;
    realm.observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });

    let releaseResponse!: () => void;
    let transportSignal: AbortSignal | undefined;
    const fetchMock = vi.fn((_url: string, init: RequestInit) => (
      new Promise<Response>((resolve, reject) => {
        transportSignal = init.signal ?? undefined;
        releaseResponse = () => resolve(new Response(
          JSON.stringify(incompleteProfileWire('Actor A', 1)),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ));
        init.signal?.addEventListener('abort', () => {
          reject(new DOMException('query cache cancelled transport', 'AbortError'));
        }, { once: true });
      })
    ));
    vi.stubGlobal('fetch', fetchMock);

    let transportAttempt!: Promise<StudentProfileProjection>;
    let transportSettled = false;
    const queryAttempt = realmQueryClient.fetchQuery({
      ...realmProfileQueryOptions,
      queryFn: (context) => {
        transportAttempt = realmProfileQueryOptions.queryFn(context);
        void transportAttempt.finally(() => { transportSettled = true; }).catch(() => undefined);
        return transportAttempt;
      },
    }).catch((error: unknown) => error);
    await vi.waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(locks.heldModes(realm.STUDENT_AUTH_SESSION_LOCK)).toEqual(['shared', 'shared']);
    });

    realm.clearStudentBrowserContext();
    realm.observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });
    await Promise.resolve();

    expect(transportSignal?.aborted ?? false).toBe(false);
    expect(transportSettled).toBe(false);
    expect(locks.heldModes(realm.STUDENT_AUTH_SESSION_LOCK)).toEqual(['shared', 'shared']);
    expect(realmQueryClient.getQueryData(realmProfileQueryKey)).toBeUndefined();

    releaseResponse();
    await expect(transportAttempt).resolves.toEqual(expect.objectContaining({
      profileVersion: 1,
      profile: expect.objectContaining({
        personal: expect.objectContaining({ firstName: 'Actor A' }),
      }),
    }));
    await queryAttempt;
    await vi.waitFor(() => {
      expect(locks.heldModes(realm.STUDENT_AUTH_SESSION_LOCK)).toEqual(['shared']);
    });
    expect(realmQueryClient.getQueryData(realmProfileQueryKey)).toBeUndefined();
    subscription.unsubscribe();
  });

  it('fails closed when Web Locks are unavailable', async () => {
    vi.stubGlobal('window', new EventTarget());
    vi.stubGlobal('document', {});
    vi.stubGlobal('navigator', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const unavailable = vi.fn();

    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: unavailable,
    });

    expect(subscription.available).toBe(false);
    expect(unavailable).toHaveBeenCalledTimes(1);
    await expect(realm.withStudentAuthRequestLease(async () => 'must-not-run')).rejects.toThrow(
      'student_auth_transition_unavailable',
    );
  });

  it('fails closed when cross-realm coordination is unavailable', async () => {
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    vi.stubGlobal('window', new EventTarget());
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', undefined);
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const unavailable = vi.fn();

    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: unavailable,
    });
    const operation = vi.fn(async () => 'must-not-run');
    const transition = realm.startStudentAuthTransition();

    expect(subscription.available).toBe(false);
    expect(unavailable).toHaveBeenCalledTimes(1);
    await expect(transition.run(operation)).rejects.toThrow('student_auth_transition_unavailable');
    expect(operation).not.toHaveBeenCalled();
  });

  it('waits for a delayed live realm shared lease before rotating the cookie', async () => {
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    const delayedRealmRelease = await locks.acquireShared(STUDENT_AUTH_SESSION_LOCK);
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = mapStorage(new Map());
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: () => undefined,
    });
    await subscription.ready;
    const operation = vi.fn(async () => 'rotated');
    const transition = realm.startStudentAuthTransition();
    const run = transition.run(operation);

    await vi.waitFor(() => {
      expect(locks.heldModes(STUDENT_AUTH_SESSION_LOCK)).toEqual(['shared']);
      expect(locks.queuedModes(STUDENT_AUTH_SESSION_LOCK)).toEqual(['exclusive']);
    });
    expect(operation).not.toHaveBeenCalled();

    delayedRealmRelease();
    await expect(run).resolves.toBe('rotated');
    await realm.finishStudentAuthTransition(transition);
    subscription.unsubscribe();
  });

  it('serializes overlapping cookie transitions without reacquiring shared between them', async () => {
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = mapStorage(new Map());
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const phases: string[] = [];
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: (id) => phases.push(`start:${id}`),
      onEnd: (id) => phases.push(`end:${id}`),
      onUnavailable: () => phases.push('unavailable'),
    });
    await subscription.ready;
    const first = realm.startStudentAuthTransition();
    const firstRun = first.run(async () => 'first');
    const secondOperation = vi.fn(async () => 'second');
    const second = realm.startStudentAuthTransition();
    const secondRun = second.run(secondOperation);

    await expect(firstRun).resolves.toBe('first');
    expect(secondOperation).not.toHaveBeenCalled();
    await realm.finishStudentAuthTransition(first);
    await expect(secondRun).resolves.toBe('second');
    expect(locks.heldModes(STUDENT_AUTH_SESSION_LOCK)).toEqual(['exclusive']);
    await realm.finishStudentAuthTransition(second);
    expect(locks.heldModes(STUDENT_AUTH_SESSION_LOCK)).toEqual(['shared']);
    expect(phases).toEqual([
      `start:${first.id}`,
      `start:${second.id}`,
      `end:${first.id}`,
      `end:${second.id}`,
    ]);
    subscription.unsubscribe();
  });

  it('rejects an ordinary request captured after transition start instead of dispatching it under the replacement cookie', async () => {
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = mapStorage(new Map());
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: () => undefined,
    });
    await subscription.ready;
    const transition = realm.startStudentAuthTransition();
    const transitionRun = transition.run(async () => undefined);
    await transition.ready;
    await transitionRun;

    const operation = vi.fn(async () => 'must-not-run');
    const request = realm.withStudentAuthRequestLease(operation);
    const earlyOutcome = await Promise.race([
      request.then(
        () => 'resolved',
        (error: unknown) => error instanceof Error ? error.message : 'rejected',
      ),
      new Promise<string>((resolve) => {
        globalThis.setTimeout(() => resolve('still-queued'), 20);
      }),
    ]);

    await realm.finishStudentAuthTransition(transition);
    await request.catch(() => undefined);
    expect(earlyOutcome).toBe('student_auth_transition_active');
    expect(operation).not.toHaveBeenCalled();
    subscription.unsubscribe();
  });

  it('rejects a request already queued behind a remote transition writer', async () => {
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = mapStorage(new Map());
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const remote = new FakeBroadcastChannel(realm.STUDENT_AUTH_TRANSITION_CHANNEL);
    const onStart = vi.fn();
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart,
      onEnd: () => undefined,
      onUnavailable: () => undefined,
    });
    await subscription.ready;

    let releaseWriter!: () => void;
    let writerAcquired!: () => void;
    const writerReady = new Promise<void>((resolve) => { writerAcquired = resolve; });
    const writerHeld = new Promise<void>((resolve) => { releaseWriter = resolve; });
    const writer = locks.request(
      realm.STUDENT_AUTH_SESSION_LOCK,
      { mode: 'exclusive' },
      async () => {
        writerAcquired();
        await writerHeld;
      },
    );
    const operation = vi.fn(async () => 'must-not-run');

    // The request captures while no transition is active, but queues behind a
    // writer that represents the peer's already-linearized cookie operation.
    const request = realm.withStudentAuthRequestLease(operation);
    await vi.waitFor(() => {
      expect(locks.heldModes(realm.STUDENT_AUTH_SESSION_LOCK)).toEqual(['shared']);
      expect(locks.queuedModes(realm.STUDENT_AUTH_SESSION_LOCK)).toEqual([
        'exclusive',
        'shared',
      ]);
    });
    remote.postMessage({
      version: 2,
      kind: 'start',
      sender: 'realm-remote-1',
      transition: 'transition-rotation-1',
    });

    await writerReady;
    await vi.waitFor(() => expect(onStart).toHaveBeenCalledWith('transition-rotation-1'));
    releaseWriter();
    await expect(request).rejects.toThrow('student_auth_transition_active');
    await writer;
    expect(operation).not.toHaveBeenCalled();
    remote.postMessage({
      version: 2,
      kind: 'end',
      sender: 'realm-remote-1',
      transition: 'transition-rotation-1',
    });
    subscription.unsubscribe();
    remote.close();
  });

  it('erases any reauth handoff for explicit logout/deletion lifecycle teardown', () => {
    retainReauthDraft();
    expect(hasProfileReauthHandoff()).toBe(true);

    clearStudentBrowserContext();

    expect(hasProfileReauthHandoff()).toBe(false);
  });

  it('clears before an identity-free cross-realm auth transition and waits for peer acknowledgement', async () => {
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = mapStorage(new Map());
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    vi.resetModules();
    const { queryClient: realmQueryClient } = await import('../../../app/queryClient');
    const realm = await import('./studentBrowserContext');

    const remote = new FakeBroadcastChannel(STUDENT_AUTH_TRANSITION_CHANNEL);
    const remoteMessages: unknown[] = [];
    remote.onmessage = (event) => {
      remoteMessages.push(event.data);
      const message = event.data as { kind?: string; transition?: string; sender?: string };
      if (message.kind === 'start' && message.transition) {
        remote.postMessage({
          version: 2,
          kind: 'ack',
          sender: 'realm-remote-1',
          transition: message.transition,
        });
      }
    };

    const phases: string[] = [];
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => phases.push('start'),
      onEnd: () => phases.push('end'),
      onUnavailable: () => phases.push('unavailable'),
    });
    await subscription.ready;

    realm.observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const fence = realm.captureStudentContextFence();
    realmQueryClient.setQueryData(['actor-A-private'], { owner: 'A' });
    let startedEvents = 0;
    browserWindow.addEventListener(STUDENT_AUTH_TRANSITION_STARTED_EVENT, () => {
      startedEvents += 1;
      expect(realmQueryClient.getQueryData(['actor-A-private'])).toBeUndefined();
    });

    const transition = realm.startStudentAuthTransition();
    const transitionRun = transition.run(async () => undefined);
    await transition.ready;

    expect(startedEvents).toBe(1);
    expect(phases).toEqual(['start']);
    expect(realm.isStudentContextFenceCurrent(fence)).toBe(false);
    const start = remoteMessages.find((value) => (
      typeof value === 'object' && value !== null && (value as { kind?: string }).kind === 'start'
    ));
    expect(start).toEqual(expect.objectContaining({ version: 2, kind: 'start' }));
    expect(JSON.stringify(start)).not.toMatch(/student|profile|actor|session|role|mobile|email/iu);

    await transitionRun;
    await realm.finishStudentAuthTransition(transition);
    expect(phases).toEqual(['start', 'end']);
    subscription.unsubscribe();
    remote.close();
  });

  it('replays an already-active transition to a late AuthProvider subscriber', async () => {
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = mapStorage(new Map());
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    vi.resetModules();
    const realm = await import('./studentBrowserContext');

    const transition = realm.startStudentAuthTransition();
    const transitionRun = transition.run(async () => undefined);
    const phases: string[] = [];
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => phases.push('start'),
      onEnd: () => phases.push('end'),
      onUnavailable: () => phases.push('unavailable'),
    });
    await transition.ready;
    expect(phases).toEqual(['start']);
    await transitionRun;
    await realm.finishStudentAuthTransition(transition);
    expect(phases).toEqual(['start', 'end']);
    subscription.unsubscribe();
  });

  it('rejects locally before a cookie-mutating operation when an owned-key removal fails', async () => {
    const local = new Map<string, string>([['ls-reports-transition-fails', 'private']]);
    const failingStorage = mapStorage(local);
    failingStorage.removeItem = () => { throw new DOMException('denied'); };
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = failingStorage;
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    stubNavigatorLocks(new FakeLockManager());
    vi.resetModules();
    const { withStudentAuthTransition } = await import('./registrationApi');
    const operation = vi.fn(async () => 'must-not-run');

    await expect(withStudentAuthTransition(operation)).rejects.toThrow(
      'student_auth_transition_local_cleanup_incomplete',
    );
    expect(operation).not.toHaveBeenCalled();
    expect(local.get('ls-reports-transition-fails')).toBe('private');
  });

  it('NACKs a remote cookie transition when any owned-key removal fails', async () => {
    const local = new Map<string, string>([['ls-reports-removal-fails', 'private']]);
    const failingStorage = mapStorage(local);
    failingStorage.removeItem = () => { throw new DOMException('denied'); };
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = failingStorage;
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    stubNavigatorLocks(new FakeLockManager());
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: () => undefined,
    });
    await subscription.ready;
    const remote = new FakeBroadcastChannel(STUDENT_AUTH_TRANSITION_CHANNEL);
    const received: Array<{ kind?: string; transition?: string }> = [];
    remote.onmessage = (event) => { received.push(event.data as { kind?: string; transition?: string }); };
    remote.postMessage({
      version: 2,
      kind: 'start',
      sender: 'realm-remote-1',
      transition: 'transition-remote-1',
    });

    await vi.waitFor(() => expect(received).toContainEqual(expect.objectContaining({
      kind: 'nack',
      transition: 'transition-remote-1',
    })));
    expect(local.get('ls-reports-removal-fails')).toBe('private');
    subscription.unsubscribe();
    remote.close();
  });

  it('keeps the initiator unavailable and performs zero cookie work after a peer NACK', async () => {
    const locks = new FakeLockManager();
    stubNavigatorLocks(locks);
    const browserWindow = new EventTarget() as EventTarget & {
      localStorage: Storage;
      sessionStorage: Storage;
    };
    browserWindow.localStorage = mapStorage(new Map());
    browserWindow.sessionStorage = mapStorage(new Map());
    vi.stubGlobal('window', browserWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const unavailable = vi.fn();
    const subscription = realm.subscribeStudentAuthTransitions({
      onStart: () => undefined,
      onEnd: () => undefined,
      onUnavailable: unavailable,
    });
    await subscription.ready;
    const peerRelease = await locks.acquireShared(STUDENT_AUTH_SESSION_LOCK);
    const peer = new FakeBroadcastChannel(STUDENT_AUTH_TRANSITION_CHANNEL);
    peer.onmessage = (event) => {
      const message = event.data as { kind?: string; transition?: string };
      if (message.kind === 'start' && message.transition) {
        peer.postMessage({
          version: 2,
          kind: 'nack',
          sender: 'realm-peer-1',
          transition: message.transition,
        });
      }
    };
    const operation = vi.fn(async () => 'must-not-run');
    const transition = realm.startStudentAuthTransition();
    const run = transition.run(operation);

    await expect(run).rejects.toThrow('student_auth_transition_peer_cleanup_incomplete');
    await realm.finishStudentAuthTransition(transition);
    expect(unavailable).toHaveBeenCalledTimes(1);
    expect(operation).not.toHaveBeenCalled();
    await expect(realm.withStudentAuthRequestLease(operation)).rejects.toThrow(
      'student_auth_transition_unavailable',
    );
    expect(operation).not.toHaveBeenCalled();
    peerRelease();
    peer.close();
    subscription.unsubscribe();
  });

  it('denies cookie work when browser storage cannot be inspected for retired private state', async () => {
    const inaccessibleWindow = new EventTarget() as EventTarget & {
      readonly localStorage: Storage;
      readonly sessionStorage: Storage;
    };
    Object.defineProperties(inaccessibleWindow, {
      localStorage: { get: () => { throw new DOMException('denied'); } },
      sessionStorage: { get: () => mapStorage(new Map()) },
    });
    vi.stubGlobal('window', inaccessibleWindow);
    vi.stubGlobal('document', {});
    vi.stubGlobal('BroadcastChannel', FakeBroadcastChannel);
    stubNavigatorLocks(new FakeLockManager());
    vi.resetModules();
    const realm = await import('./studentBrowserContext');
    const operation = vi.fn(async () => 'must-not-run');
    const transition = realm.startStudentAuthTransition();

    await expect(transition.run(operation)).rejects.toThrow(
      'student_auth_transition_local_cleanup_incomplete',
    );
    expect(operation).not.toHaveBeenCalled();
  });

  it('retires exact active-student memory, cache, refs and storage while preserving migrated theme state', async () => {
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
    saveSubmittedApplication({
      id: 'private-application', listingId: 'listing', org: 'Private Org',
      role: 'Private Role', meta: 'private', status: 'applied',
    });
    queryClient.setQueryData(['student-profile'], { maskedMobile: '••••••3210' });
    queryClient.getMutationCache().build(queryClient, {
      mutationKey: ['student-settings'],
      mutationFn: async () => ({ private: true }),
    });

    clearStudentBrowserContext({ notifyAuthChanged: true });

    expect(getRegistrationAttempt()).toBeNull();
    expect(getProfileDraft().firstName).toBe('');
    expect(getProfileDraft().dateOfBirth).toBe('');
    expect(loadSubmittedApplications()).toEqual([]);
    expect(queryClient.getQueryCache().getAll()).toEqual([]);
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
    expect([...local.entries()]).toEqual([
      ['ls-theme', 'dark'],
    ]);
    expect([...session.entries()]).toEqual([['unrelated-session-key', 'keep']]);
    expect(localClear).not.toHaveBeenCalled();
    expect(sessionClear).not.toHaveBeenCalled();
    await vi.waitFor(() => expect(dispatchEvent.mock.calls.some(
      ([event]) => (event as Event).type === STUDENT_AUTH_CHANGED_EVENT,
    )).toBe(true));
    expect(dispatchEvent.mock.calls.map(([event]) => (event as Event).type)).toEqual([
      STUDENT_AUTH_TRANSITION_STARTED_EVENT,
      STUDENT_AUTH_CHANGED_EVENT,
    ]);
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

  it('preserves only the exact actor-independent public projection while clearing private queries and every mutation', () => {
    queryClient.setQueryData(['public-internship-risk-labels', 'organisation-A'], { available: true });
    queryClient.setQueryData(['public-credential-verification', 'opaque-token'], { status: 'verified' });
    queryClient.setQueryData(['student-profile'], { private: true });
    queryClient.setQueryData(['unknown-public-looking-key'], { private: true });
    queryClient.getMutationCache().build(queryClient, {
      mutationKey: ['public-internship-risk-labels', 'still-unsafe-as-a-mutation'],
      mutationFn: async () => ({ private: true }),
    });

    clearStudentBrowserContext();

    expect(queryClient.getQueryData(['public-internship-risk-labels', 'organisation-A'])).toEqual({ available: true });
    expect(queryClient.getQueryData(['public-credential-verification', 'opaque-token'])).toEqual({ status: 'verified' });
    expect(queryClient.getQueryData(['student-profile'])).toBeUndefined();
    expect(queryClient.getQueryData(['unknown-public-looking-key'])).toBeUndefined();
    expect(queryClient.getMutationCache().getAll()).toEqual([]);
  });

  it('clears actor memory and all retired app-owned dynamic keys before rotation', () => {
    const local = new Map<string, string>([
      ['nyayone.student.reports.v1.student-A', 'A'],
      ['nyayone.student.reminder-prefs.v1.profile-A', 'A'],
      ['ls-reports-student-B', 'B'],
      ['ls-theme', 'light'],
      ['unrelated', 'keep'],
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
    expect(local.has('nyayone.student.reports.v1.student-A')).toBe(false);
    expect(local.has('nyayone.student.reminder-prefs.v1.profile-A')).toBe(false);
    expect(local.has('ls-reports-student-B')).toBe(false);
    expect(local.get('ls-theme')).toBe('light');
    expect(local.get('unrelated')).toBe('keep');
  });

  it('retires the incoming actor current keys before first ownership is published', () => {
    const local = new Map<string, string>([
      ['nyayone.student.reports.v1.student-A', 'private-report'],
      ['nyayone.student.reminder-prefs.v1.profile-A', 'private-reminder'],
      ['unrelated', 'keep'],
    ]);
    vi.stubGlobal('window', {
      localStorage: mapStorage(local),
      sessionStorage: mapStorage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });

    expect(observeStudentSessionActor({
      subject: 'student-A', studentProfileId: 'profile-A',
    })).toBe(true);

    expect(local.has('nyayone.student.reports.v1.student-A')).toBe(false);
    expect(local.has('nyayone.student.reminder-prefs.v1.profile-A')).toBe(false);
    expect(local.get('unrelated')).toBe('keep');
  });

  it('refuses first ownership when an incoming actor key cannot be removed', () => {
    const ownedKey = 'nyayone.student.reports.v1.student-A';
    const local = new Map<string, string>([[ownedKey, 'private-report']]);
    const failingStorage = mapStorage(local);
    failingStorage.removeItem = (key) => {
      if (key === ownedKey) throw new DOMException('denied');
      local.delete(key);
    };
    vi.stubGlobal('window', {
      localStorage: failingStorage,
      sessionStorage: mapStorage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });

    expect(observeStudentSessionActor({
      subject: 'student-A', studentProfileId: 'profile-A',
    })).toBe(false);
    expect(local.get(ownedKey)).toBe('private-report');
  });

  it('persists no actor registry and retires bounded app-owned prefixes after reload', async () => {
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
    expect([...local.keys()].some((key) => key.includes('cleanup-registry'))).toBe(false);

    // A new JS realm has no in-memory observed actor. An anonymous/expired
    // server session must still retire only the exact actor registered earlier.
    vi.resetModules();
    const restartedRealm = await import('./studentBrowserContext');
    restartedRealm.clearStudentBrowserContext();

    expect(local.has('ls-reports-student-A')).toBe(false);
    expect(local.has('ls-reminder-prefs-profile-A')).toBe(false);
    expect(local.has('legalsaathi.student.cleanup-registry.v1')).toBe(false);
    expect(local.has('ls-reports-student-B')).toBe(false);
    expect(local.get('ls-theme')).toBe('dark');
    expect(local.has('ls-locale')).toBe(false);
  });

  it('purges every retired private namespace and obsolete onboarding state on cold bundle load', () => {
    const local = new Map<string, string>([
      ['legalsaathi.student.profile.v1', 'private-profile'],
      ['legalsaathi.student.onboarding.v34', 'retired-onboarding'],
      ['legalsaathi.internship.applications.v1', 'private-application'],
      ['legalsaathi.clinical.export-audit.v1', 'private-audit'],
      ['legalsaathi.student.cleanup-registry.v1', 'private-registry'],
      ['ls-reports-cold-actor', 'private-report'],
      ['ls-reminder-prefs-cold-actor', 'private-reminder'],
      ['ls-onboarding-seen', 'seen'],
      ['ls-theme', 'dark'],
      ['unrelated', 'keep'],
    ]);
    vi.stubGlobal('window', {
      localStorage: mapStorage(local),
      sessionStorage: mapStorage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });

    retireLegacyStudentRegistrationState();

    expect([...local.entries()]).toEqual([
      ['ls-theme', 'dark'],
      ['unrelated', 'keep'],
    ]);
  });

  it('never writes actor identity to browser storage across multiple realms', async () => {
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

    // StrictMode can resolve either realm anonymous more than once. Retired
    // app-owned prefixes are purged without persisting either actor identity.
    staleActorRealm.clearStudentBrowserContext();
    staleActorRealm.clearStudentBrowserContext();
    expect(local.has('ls-reports-student-B')).toBe(false);
    expect(local.has('ls-reminder-prefs-student-B')).toBe(false);
    expect([...local.keys()].some((key) => key.includes('cleanup-registry'))).toBe(false);
    expect(local.get('ls-theme')).toBe('dark');

    activeActorRealm.clearStudentBrowserContext({ consumeRegisteredActor: true });
    expect(local.has('ls-reports-student-B')).toBe(false);
    expect(local.has('ls-reminder-prefs-student-B')).toBe(false);
  });

  it('retires the former registry without reading it and preserves unrelated keys', () => {
    const local = new Map<string, string>([
      ['legalsaathi.student.cleanup-registry.v1', 'malformed-or-private'],
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

    expect(local.has('legalsaathi.student.cleanup-registry.v1')).toBe(false);
    expect(local.has('ls-reports-student-A')).toBe(false);
    expect(local.has('ls-reminder-prefs-student-A')).toBe(false);
    expect(local.get('ls-theme')).toBe('dark');
  });

  it('finds retired keys after more than 256 unrelated entries and never clears the storage area', () => {
    const local = new Map<string, string>();
    for (let index = 0; index < MAX_RETIRED_STUDENT_KEYS_PER_PURGE + 10; index += 1) {
      local.set(`unrelated-${index}`, 'keep');
    }
    local.set('ls-reports-after-unrelated-boundary', 'private');
    local.set('ls-reminder-prefs-after-unrelated-boundary', 'private');
    const clear = vi.fn();
    vi.stubGlobal('window', {
      localStorage: mapStorage(local, clear),
      sessionStorage: mapStorage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });
    expect(clearStudentBrowserContext()).toBe(true);
    expect(local.size).toBe(MAX_RETIRED_STUDENT_KEYS_PER_PURGE + 10);
    expect(local.has('ls-reports-after-unrelated-boundary')).toBe(false);
    expect(local.has('ls-reminder-prefs-after-unrelated-boundary')).toBe(false);
    expect(clear).not.toHaveBeenCalled();
  });

  it('completes every retired prefix in bounded 256-key batches in one teardown', () => {
    const local = new Map<string, string>([['unrelated', 'keep']]);
    for (let index = 0; index < (MAX_RETIRED_STUDENT_KEYS_PER_PURGE * 2) + 1; index += 1) {
      local.set(`ls-reports-retired-${index}`, 'private');
    }
    vi.stubGlobal('window', {
      localStorage: mapStorage(local),
      sessionStorage: mapStorage(new Map()),
      dispatchEvent: vi.fn(() => true),
    });

    expect(clearStudentBrowserContext()).toBe(true);
    expect([...local.keys()].filter((key) => key.startsWith('ls-reports-'))).toHaveLength(0);
    expect(local.get('unrelated')).toBe('keep');
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

  it('fences a late successful profile mutation before actor B can reuse actor A PII', async () => {
    let resolveMutation!: (value: ProfileMutationResult) => void;
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const mutation = queryClient.getMutationCache().build(
      queryClient,
      createProjectionMutationOptions<void>(queryClient, () => new Promise((resolve) => {
        resolveMutation = resolve;
      })),
    );
    const result = mutation.execute(undefined);
    await Promise.resolve();

    clearStudentBrowserContext();
    observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });
    const actorB = actorProjection('Actor B', 1);
    queryClient.setQueryData(STUDENT_PROFILE_QUERY_KEY, actorB);
    resolveMutation({ projection: actorProjection('Actor A', 2), certainty: 'confirmed' });
    await result;

    expect(queryClient.getQueryData(STUDENT_PROFILE_QUERY_KEY)).toEqual(actorB);
  });

  it('fences a late conflict/error projection after logout and actor rotation', async () => {
    let rejectMutation!: (error: unknown) => void;
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const mutation = queryClient.getMutationCache().build(
      queryClient,
      createProjectionMutationOptions<void>(queryClient, () => new Promise((_resolve, reject) => {
        rejectMutation = reject;
      })),
    );
    const result = mutation.execute(undefined).catch((error: unknown) => error);
    await Promise.resolve();

    clearStudentBrowserContext();
    observeStudentSessionActor({ subject: 'student-B', studentProfileId: 'profile-B' });
    const actorB = actorProjection('Actor B', 1);
    queryClient.setQueryData(STUDENT_PROFILE_QUERY_KEY, actorB);
    rejectMutation(new ProfileApiError(
      409,
      'profile_version_conflict',
      undefined,
      2,
      actorProjection('Actor A', 2),
    ));
    await result;

    expect(queryClient.getQueryData(STUDENT_PROFILE_QUERY_KEY)).toEqual(actorB);
  });

  it('keeps a same-actor 409 projection local until explicit conflict adoption', async () => {
    observeStudentSessionActor({ subject: 'student-A', studentProfileId: 'profile-A' });
    const baseline = actorProjection('Actor A original', 1);
    queryClient.setQueryData(STUDENT_PROFILE_QUERY_KEY, baseline);
    const current = actorProjection('Actor A server winner', 2);
    const mutation = queryClient.getMutationCache().build(
      queryClient,
      createProjectionMutationOptions<void>(queryClient, async () => {
        throw new ProfileApiError(409, 'profile_version_conflict', undefined, 2, current);
      }),
    );

    await mutation.execute(undefined).catch((error: unknown) => error);

    expect(queryClient.getQueryData(STUDENT_PROFILE_QUERY_KEY)).toEqual(baseline);
  });
});
