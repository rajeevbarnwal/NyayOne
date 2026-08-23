import { queryClient } from '../../../app/queryClient';
import { resetProfileDraft } from './profileStore';
import { clearRegistrationAttempt } from './registrationAttemptStore';
import { clearSubmittedApplications } from './internships';
import { clearProfileConflictDraft } from '../profile/profileConflictDraftStore';
import { clearProfileReauthHandoff } from '../profile/profileReauthHandoff';
import { clearStudentAuthTransitionNotice } from './studentAuthTransitionNotice';
import {
  MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH,
  purgeLegacyStudentLocalStorage,
  purgeLegacyStudentSessionStorage,
  studentReminderPrefStorageKey,
  studentReportStorageKey,
} from './studentLegacyStorage';

export const STUDENT_AUTH_CHANGED_EVENT = 'nyayone:student-auth-changed';
export const STUDENT_AUTH_SESSION_LOCK = 'nyayone.student.auth-session.v1';
export const STUDENT_AUTH_TRANSITION_STARTED_EVENT = 'nyayone:student-auth-transition-started';
export const STUDENT_AUTH_TRANSITION_CHANNEL = 'nyayone.student.auth-transition.v2';

const AUTH_TRANSITION_VERSION = 2 as const;
const AUTH_TRANSITION_ACK_TIMEOUT_MS = 15_000;

type StudentAuthTransitionMessage = {
  version: typeof AUTH_TRANSITION_VERSION;
  kind: 'start' | 'ack' | 'nack' | 'end';
  sender: string;
  transition: string;
};

export interface StudentAuthTransition {
  /** Process-only correlation. It is never an actor, session, or browser-stored value. */
  readonly id: string;
  readonly ready: Promise<void>;
  /** Run the one cookie operation and its authoritative session probe under the exclusive lease. */
  run<T>(operation: () => Promise<T>): Promise<T>;
}

export interface StudentAuthTransitionListener {
  onStart: (transitionId: string) => void;
  onEnd: (transitionId: string) => void;
  onUnavailable: () => void;
}

interface RealmSharedLease {
  acquired: Promise<void>;
  request: Promise<unknown>;
  release: () => void;
  abort: AbortController;
  held: boolean;
}

interface PendingTransitionOperation {
  handle: StudentAuthTransition;
  abort: AbortController;
  ready: Promise<void>;
  resolveReady: () => void;
  rejectReady: (error: Error) => void;
  operationRequested: Promise<void>;
  resolveOperationRequested: () => void;
  operation: (() => Promise<unknown>) | null;
  resolveOperation: (value: unknown) => void;
  rejectOperation: (error: unknown) => void;
  releaseExclusive: () => void;
  exclusiveReleased: Promise<void>;
  exclusiveRequest: Promise<unknown>;
  exclusiveHeld: boolean;
  operationStarted: boolean;
  operationSettled: boolean;
  finished: boolean;
  failed: boolean;
  failure: Error | null;
  timer: ReturnType<typeof globalThis.setTimeout>;
}

interface StudentAuthTransitionCoordinator {
  channel: BroadcastChannel;
  locks: LockManager;
  realmId: string;
  listeners: Set<StudentAuthTransitionListener>;
  pendingTransitions: Map<string, PendingTransitionOperation>;
  activeTransitions: Set<string>;
  failedTransitions: Set<string>;
  realmLease: RealmSharedLease | null;
  stickyUnavailable: boolean;
  ready: Promise<void>;
}

export interface StudentAuthTransitionSubscription {
  readonly available: boolean;
  readonly ready: Promise<void>;
  unsubscribe: () => void;
}

let authTransitionCoordinator: StudentAuthTransitionCoordinator | null = null;
const pendingTransitionHandles = new WeakMap<StudentAuthTransition, PendingTransitionOperation>();
const directStudentAuthTransitions = new WeakSet<StudentAuthTransition>();
let transitionNonce = 0;

/** @deprecated Import the NYAY-18 compatibility-boundary constant directly. */
export const MAX_RETIRED_STUDENT_KEYS_PER_PURGE = MAX_LEGACY_STUDENT_KEYS_PER_PURGE_BATCH;

// This projection is anonymous and contains only the server-approved public
// aggregate. Every other query root remains actor-sensitive by default.
const ACTOR_INDEPENDENT_QUERY_ROOTS = new Set(['public-internship-risk-labels']);

interface ObservedStudentActor {
  subject: string;
  studentProfileId: string | null;
}

// Actor identity is held only in this JS realm. It is never copied to
// localStorage/sessionStorage, including indirectly inside a cleanup registry.
let observedStudentActor: ObservedStudentActor | null = null;
let studentBrowserContextGeneration = 0;
let studentBrowserContextAbortController = new AbortController();

export interface StudentContextFence {
  generation: number;
  subject: string | null;
  signal: AbortSignal;
}

/** Capture the exact in-memory actor generation that owns an async callback. */
export function captureStudentContextFence(): StudentContextFence {
  return {
    generation: studentBrowserContextGeneration,
    subject: observedStudentActor?.subject ?? null,
    signal: studentBrowserContextAbortController.signal,
  };
}

/** Reject callbacks that outlive logout, expiry, deletion, or actor rotation. */
export function isStudentContextFenceCurrent(fence: StudentContextFence): boolean {
  return fence.generation === studentBrowserContextGeneration
    && fence.subject === (observedStudentActor?.subject ?? null)
    && !fence.signal.aborted;
}

function isBrowserRealm(): boolean {
  return typeof window !== 'undefined' && typeof document !== 'undefined';
}

function availableStorage(kind: 'localStorage' | 'sessionStorage'): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window[kind];
  } catch {
    return null;
  }
}

function actorKeys(actor: ObservedStudentActor): string[] {
  const ids = new Set([
    actor.subject,
    actor.studentProfileId,
  ].filter((value): value is string => Boolean(value)));
  return [...ids].flatMap((id) => [
    studentReportStorageKey(id),
    studentReminderPrefStorageKey(id),
  ]);
}

function currentActorKeys(): string[] {
  return observedStudentActor ? actorKeys(observedStudentActor) : [];
}

function clearActorSensitiveQueryState(): void {
  queryClient.removeQueries({
    predicate: (query) => !ACTOR_INDEPENDENT_QUERY_ROOTS.has(String(query.queryKey[0] ?? '')),
  });
  queryClient.getMutationCache().clear();
}

export interface ClearStudentBrowserContextOptions {
  /** Notify the same-tab auth provider after the teardown is complete. */
  notifyAuthChanged?: boolean;
  /** Retained API compatibility; cleanup no longer consumes browser actor state. */
  consumeRegisteredActor?: boolean;
  /** Keep only a separately captured canonical-401 handoff pending reauth. */
  preserveProfileReauthHandoff?: boolean;
}

/**
 * Fail-closed identity boundary for logout, expiry, actor rotation and accepted
 * account deletion. The whole singleton TanStack cache is actor-sensitive
 * because current private query keys are not actor-scoped.
 */
function clearStudentBrowserContextWithIncomingActorKeys(
  options: ClearStudentBrowserContextOptions = {},
  incomingActorKeys: readonly string[] = [],
): boolean {
  studentBrowserContextAbortController.abort('student_context_changed');
  studentBrowserContextAbortController = new AbortController();
  studentBrowserContextGeneration += 1;
  try { clearRegistrationAttempt(); } catch { /* memory-only dependency */ }
  try { resetProfileDraft(); } catch { /* memory reset happens before storage */ }
  try { clearSubmittedApplications(); } catch { /* memory-only dependency */ }
  try { clearProfileConflictDraft(); } catch { /* memory-only dependency */ }
  if (!options.preserveProfileReauthHandoff) {
    try { clearProfileReauthHandoff(); } catch { /* memory-only dependency */ }
  }
  try { clearActorSensitiveQueryState(); } catch { /* continue through storage + event */ }

  const local = availableStorage('localStorage');
  let cleanupComplete = true;
  if (local) {
    cleanupComplete = purgeLegacyStudentLocalStorage(
      local,
      [...currentActorKeys(), ...incomingActorKeys],
    ).complete;
  } else if (isBrowserRealm()) {
    cleanupComplete = false;
  }
  const session = availableStorage('sessionStorage');
  if (session) {
    cleanupComplete = purgeLegacyStudentSessionStorage(session).complete && cleanupComplete;
  } else if (isBrowserRealm()) {
    cleanupComplete = false;
  }

  observedStudentActor = null;
  if (options.notifyAuthChanged) {
    notifyStudentAuthChanged({
      preserveProfileReauthHandoff: options.preserveProfileReauthHandoff,
    });
  }
  return cleanupComplete;
}

export function clearStudentBrowserContext(
  options: ClearStudentBrowserContextOptions = {},
): boolean {
  return clearStudentBrowserContextWithIncomingActorKeys(options);
}

/** Record the actor owning singleton memory, clearing before actor rotation. */
export function observeStudentSessionActor(
  actor: ObservedStudentActor,
  options: Pick<ClearStudentBrowserContextOptions, 'preserveProfileReauthHandoff'> = {},
): boolean {
  if (observedStudentActor === null || observedStudentActor.subject !== actor.subject) {
    // The incoming server actor is known at this point but is not published
    // yet. Retire both prior-owner and incoming-owner exact durable keys before
    // authenticated state can mount in a cold realm or after rotation.
    if (!clearStudentBrowserContextWithIncomingActorKeys(options, actorKeys(actor))) return false;
  }
  observedStudentActor = actor;
  return true;
}

function opaqueTransitionId(prefix: 'realm' | 'transition'): string {
  transitionNonce += 1;
  let entropy: number;
  try {
    const values = new Uint32Array(1);
    globalThis.crypto.getRandomValues(values);
    entropy = values[0] ?? 0;
  } catch {
    entropy = Math.floor(Math.random() * 0xffff_ffff);
  }
  return `${prefix}-${entropy.toString(36)}-${transitionNonce.toString(36)}`;
}

function isTransitionMessage(value: unknown): value is StudentAuthTransitionMessage {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const message = value as Record<string, unknown>;
  const allowed = ['kind', 'sender', 'transition', 'version'];
  const keys = Object.keys(message).sort();
  if (keys.length !== allowed.length || !keys.every((key, index) => key === allowed[index])) return false;
  if (message.version !== AUTH_TRANSITION_VERSION
    || !['start', 'ack', 'nack', 'end'].includes(String(message.kind))
    || typeof message.sender !== 'string'
    || !/^realm-[a-z0-9]+-[a-z0-9]+$/u.test(message.sender)) return false;
  return typeof message.transition === 'string'
    && /^transition-[a-z0-9]+-[a-z0-9]+$/u.test(message.transition);
}

function transitionMessage(
  coordinator: StudentAuthTransitionCoordinator,
  kind: StudentAuthTransitionMessage['kind'],
  transition: string,
): StudentAuthTransitionMessage {
  return { version: AUTH_TRANSITION_VERSION, kind, sender: coordinator.realmId, transition };
}

function notifyTransitionStart(
  transitionId: string,
  options: Pick<ClearStudentBrowserContextOptions, 'preserveProfileReauthHandoff'> = {},
): boolean {
  try { clearStudentAuthTransitionNotice(); } catch { /* sanitized process-only notice */ }
  const cleanupComplete = clearStudentBrowserContext(options);
  for (const listener of authTransitionCoordinator?.listeners ?? []) {
    listener.onStart(transitionId);
  }
  if (typeof window !== 'undefined') {
    try { window.dispatchEvent(new Event(STUDENT_AUTH_TRANSITION_STARTED_EVENT)); } catch { /* fail closed in memory */ }
  }
  return cleanupComplete;
}

function notifyTransitionEnd(transitionId: string): void {
  for (const listener of authTransitionCoordinator?.listeners ?? []) {
    listener.onEnd(transitionId);
  }
  if (typeof window !== 'undefined') {
    try { window.dispatchEvent(new Event(STUDENT_AUTH_CHANGED_EVENT)); } catch { /* subscriber still ran */ }
  }
}

function notifyTransitionUnavailable(coordinator: StudentAuthTransitionCoordinator): void {
  if (coordinator.stickyUnavailable) return;
  coordinator.stickyUnavailable = true;
  for (const listener of coordinator.listeners) listener.onUnavailable();
}

function acquireRealmSharedLease(coordinator: StudentAuthTransitionCoordinator): Promise<void> {
  if (coordinator.stickyUnavailable) {
    return Promise.reject(new Error('student_auth_transition_unavailable'));
  }
  if (coordinator.realmLease) return coordinator.realmLease.acquired;
  const abort = new AbortController();
  let resolveAcquired!: () => void;
  let rejectAcquired!: (error: unknown) => void;
  let release!: () => void;
  const acquired = new Promise<void>((resolve, reject) => {
    resolveAcquired = resolve;
    rejectAcquired = reject;
  });
  const released = new Promise<void>((resolve) => { release = resolve; });
  const lease: RealmSharedLease = {
    acquired,
    request: Promise.resolve(),
    release,
    abort,
    held: false,
  };
  coordinator.realmLease = lease;
  lease.request = coordinator.locks.request(
    STUDENT_AUTH_SESSION_LOCK,
    { mode: 'shared', signal: abort.signal },
    async () => {
      if (coordinator.realmLease !== lease || coordinator.stickyUnavailable) return;
      lease.held = true;
      resolveAcquired();
      await released;
      lease.held = false;
    },
  ).catch((error: unknown) => {
    if (coordinator.realmLease === lease) {
      rejectAcquired(error);
      notifyTransitionUnavailable(coordinator);
    }
  }).finally(() => {
    if (coordinator.realmLease === lease && !lease.held) coordinator.realmLease = null;
  });
  return acquired;
}

function releaseRealmSharedLease(coordinator: StudentAuthTransitionCoordinator): Promise<unknown> {
  const lease = coordinator.realmLease;
  if (!lease) return Promise.resolve();
  coordinator.realmLease = null;
  if (lease.held) lease.release();
  else lease.abort.abort('student_auth_transition_started');
  return lease.request.catch(() => undefined);
}

function settleTransitionFailure(
  pending: PendingTransitionOperation,
  error: Error,
): void {
  if (pending.failed || pending.finished) return;
  pending.failed = true;
  pending.failure = error;
  globalThis.clearTimeout(pending.timer);
  pending.rejectReady(error);
  pending.rejectOperation(error);
  pending.resolveOperationRequested();
  if (!pending.exclusiveHeld) pending.abort.abort(error.message);
}

function completeRemoteTransition(
  coordinator: StudentAuthTransitionCoordinator,
  transitionId: string,
): void {
  if (!coordinator.activeTransitions.delete(transitionId)) return;
  coordinator.failedTransitions.delete(transitionId);
  if (coordinator.stickyUnavailable) return;
  if (coordinator.activeTransitions.size > 0) {
    notifyTransitionEnd(transitionId);
    return;
  }
  void acquireRealmSharedLease(coordinator).then(
    () => notifyTransitionEnd(transitionId),
    () => notifyTransitionUnavailable(coordinator),
  );
}

function handleTransitionMessage(
  coordinator: StudentAuthTransitionCoordinator,
  value: unknown,
): void {
  if (!isTransitionMessage(value) || value.sender === coordinator.realmId) return;
  if (value.kind === 'start') {
    const isNew = !coordinator.activeTransitions.has(value.transition);
    coordinator.activeTransitions.add(value.transition);
    if (isNew && !notifyTransitionStart(value.transition)) {
      coordinator.failedTransitions.add(value.transition);
      notifyTransitionUnavailable(coordinator);
    }
    if (!coordinator.failedTransitions.has(value.transition)) {
      void releaseRealmSharedLease(coordinator);
    }
    coordinator.channel.postMessage(transitionMessage(
      coordinator,
      coordinator.failedTransitions.has(value.transition) ? 'nack' : 'ack',
      value.transition,
    ));
    return;
  }
  if (value.kind === 'end') {
    completeRemoteTransition(coordinator, value.transition);
    return;
  }
  if (value.kind === 'nack') {
    const pending = coordinator.pendingTransitions.get(value.transition);
    if (pending) {
      notifyTransitionUnavailable(coordinator);
      settleTransitionFailure(
        pending,
        new Error('student_auth_transition_peer_cleanup_incomplete'),
      );
    }
  }
}

function ensureTransitionCoordinator(): StudentAuthTransitionCoordinator | null {
  if (authTransitionCoordinator) return authTransitionCoordinator;
  const locks = typeof navigator !== 'undefined' ? navigator.locks : undefined;
  if (!isBrowserRealm()
    || typeof globalThis.BroadcastChannel !== 'function'
    || !locks
    || typeof locks.request !== 'function') return null;
  try {
    const coordinator: StudentAuthTransitionCoordinator = {
      channel: new globalThis.BroadcastChannel(STUDENT_AUTH_TRANSITION_CHANNEL),
      locks,
      realmId: opaqueTransitionId('realm'),
      listeners: new Set(),
      pendingTransitions: new Map(),
      activeTransitions: new Set(),
      failedTransitions: new Set(),
      realmLease: null,
      stickyUnavailable: false,
      ready: Promise.resolve(),
    };
    coordinator.channel.onmessage = (event) => handleTransitionMessage(coordinator, event.data);
    authTransitionCoordinator = coordinator;
    coordinator.ready = acquireRealmSharedLease(coordinator).catch(() => undefined);
    return coordinator;
  } catch {
    return null;
  }
}

/**
 * Subscribe before session discovery. A browser without both BroadcastChannel
 * and Web Locks is unsupported for private student UI.
 */
export function subscribeStudentAuthTransitions(
  listener: StudentAuthTransitionListener,
): StudentAuthTransitionSubscription {
  const coordinator = ensureTransitionCoordinator();
  if (!coordinator) {
    listener.onUnavailable();
    return { available: false, ready: Promise.resolve(), unsubscribe: () => undefined };
  }
  coordinator.listeners.add(listener);
  if (coordinator.stickyUnavailable) listener.onUnavailable();
  for (const transitionId of coordinator.activeTransitions) listener.onStart(transitionId);
  return {
    available: !coordinator.stickyUnavailable,
    ready: coordinator.ready,
    unsubscribe: () => { coordinator.listeners.delete(listener); },
  };
}

function directStudentAuthTransition(
  id: string,
  options: Pick<ClearStudentBrowserContextOptions, 'preserveProfileReauthHandoff'>,
): StudentAuthTransition {
  notifyTransitionStart(id, options);
  const handle: StudentAuthTransition = {
    id,
    ready: Promise.resolve(),
    run: async <T>(operation: () => Promise<T>) => operation(),
  };
  directStudentAuthTransitions.add(handle);
  return handle;
}

function rejectedStudentAuthTransition(id: string, error: Error): StudentAuthTransition {
  const rejected = Promise.reject(error);
  void rejected.catch(() => undefined);
  return {
    id,
    ready: rejected,
    run: async () => { throw error; },
  };
}

function beginLocalTransition(
  coordinator: StudentAuthTransitionCoordinator,
  pending: PendingTransitionOperation,
  options: Pick<ClearStudentBrowserContextOptions, 'preserveProfileReauthHandoff'>,
): void {
  void coordinator.ready.then(() => {
    if (coordinator.stickyUnavailable) {
      settleTransitionFailure(pending, new Error('student_auth_transition_unavailable'));
      return;
    }
    pending.exclusiveRequest = coordinator.locks.request(
      STUDENT_AUTH_SESSION_LOCK,
      { mode: 'exclusive', signal: pending.abort.signal },
      async () => {
        pending.exclusiveHeld = true;
        globalThis.clearTimeout(pending.timer);
        pending.resolveReady();
        await pending.operationRequested;
        if (!pending.failed && pending.operation) {
          try {
            const value = await pending.operation();
            pending.operationSettled = true;
            pending.resolveOperation(value);
          } catch (error) {
            pending.operationSettled = true;
            pending.rejectOperation(error);
          }
        }
        await pending.exclusiveReleased;
      },
    );
    // Attach the rejection observer before cleanup can synchronously abort the
    // queued exclusive request. Otherwise a local purge failure can surface as
    // an unhandled AbortError even though the transition itself fails closed.
    void pending.exclusiveRequest.catch((error: unknown) => {
      if (!pending.failed && !pending.finished) {
        settleTransitionFailure(
          pending,
          error instanceof Error ? error : new Error('student_auth_transition_unavailable'),
        );
      }
    });

    if (!notifyTransitionStart(pending.handle.id, options)) {
      notifyTransitionUnavailable(coordinator);
      settleTransitionFailure(
        pending,
        new Error('student_auth_transition_local_cleanup_incomplete'),
      );
      return;
    }
    coordinator.activeTransitions.add(pending.handle.id);
    void releaseRealmSharedLease(coordinator);
    coordinator.channel.postMessage(transitionMessage(coordinator, 'start', pending.handle.id));
    pending.timer = globalThis.setTimeout(() => {
      if (!pending.exclusiveHeld) {
        settleTransitionFailure(
          pending,
          new Error('student_auth_transition_peer_unavailable'),
        );
      }
    }, AUTH_TRANSITION_ACK_TIMEOUT_MS);
  }, () => {
    settleTransitionFailure(pending, new Error('student_auth_transition_unavailable'));
  });
}

/** Queue one exclusive cookie transition behind every realm/request shared lease. */
export function startStudentAuthTransition(
  options: Pick<ClearStudentBrowserContextOptions, 'preserveProfileReauthHandoff'> = {},
): StudentAuthTransition {
  const id = opaqueTransitionId('transition');
  if (!isBrowserRealm()) return directStudentAuthTransition(id, options);
  const coordinator = ensureTransitionCoordinator();
  if (!coordinator) {
    notifyTransitionStart(id, options);
    return rejectedStudentAuthTransition(id, new Error('student_auth_transition_unavailable'));
  }
  let resolveReady!: () => void;
  let rejectReady!: (error: Error) => void;
  const ready = new Promise<void>((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });
  void ready.catch(() => undefined);
  let resolveOperationRequested!: () => void;
  const operationRequested = new Promise<void>((resolve) => {
    resolveOperationRequested = resolve;
  });
  let resolveOperation!: (value: unknown) => void;
  let rejectOperation!: (error: unknown) => void;
  const operationResult = new Promise<unknown>((resolve, reject) => {
    resolveOperation = resolve;
    rejectOperation = reject;
  });
  void operationResult.catch(() => undefined);
  let releaseExclusive!: () => void;
  const exclusiveReleased = new Promise<void>((resolve) => { releaseExclusive = resolve; });
  // The handle and pending record intentionally close over each other; the
  // handle cannot be invoked until after the record is initialized below.
  // eslint-disable-next-line prefer-const
  let pending!: PendingTransitionOperation;
  const handle: StudentAuthTransition = {
    id,
    ready,
    run: async <T>(operation: () => Promise<T>): Promise<T> => {
      const current = pendingTransitionHandles.get(handle);
      if (current !== pending || pending.failed || pending.finished) {
        throw pending.failure ?? new Error('student_auth_transition_unavailable');
      }
      if (pending.operationStarted) {
        throw new Error('student_auth_transition_operation_already_started');
      }
      pending.operationStarted = true;
      pending.operation = operation;
      pending.resolveOperationRequested();
      return operationResult as Promise<T>;
    },
  };
  pending = {
    handle,
    abort: new AbortController(),
    ready,
    resolveReady,
    rejectReady,
    operationRequested,
    resolveOperationRequested,
    operation: null,
    resolveOperation,
    rejectOperation,
    releaseExclusive,
    exclusiveReleased,
    exclusiveRequest: Promise.resolve(),
    exclusiveHeld: false,
    operationStarted: false,
    operationSettled: false,
    finished: false,
    failed: false,
    failure: null,
    timer: globalThis.setTimeout(() => undefined, 0),
  };
  pendingTransitionHandles.set(handle, pending);
  coordinator.pendingTransitions.set(id, pending);
  beginLocalTransition(coordinator, pending, options);
  return handle;
}

/** End before releasing exclusive; reacquire shared before private rediscovery. */
export async function finishStudentAuthTransition(transition: StudentAuthTransition): Promise<void> {
  if (directStudentAuthTransitions.delete(transition)) {
    notifyTransitionEnd(transition.id);
    return;
  }
  const coordinator = ensureTransitionCoordinator();
  const pending = pendingTransitionHandles.get(transition);
  if (!coordinator || !pending || pending.finished) return;
  pending.finished = true;
  globalThis.clearTimeout(pending.timer);
  const wasActive = coordinator.activeTransitions.has(transition.id);
  if (wasActive) {
    coordinator.channel.postMessage(transitionMessage(coordinator, 'end', transition.id));
  }
  if (!pending.operationStarted) {
    pending.rejectOperation(new Error('student_auth_transition_operation_missing'));
    pending.resolveOperationRequested();
  }
  if (pending.exclusiveHeld) pending.releaseExclusive();
  else pending.abort.abort('student_auth_transition_finished');
  await pending.exclusiveRequest.catch(() => undefined);
  coordinator.pendingTransitions.delete(transition.id);
  pendingTransitionHandles.delete(transition);
  coordinator.activeTransitions.delete(transition.id);
  coordinator.failedTransitions.delete(transition.id);
  if (coordinator.stickyUnavailable) return;
  if (coordinator.activeTransitions.size === 0) {
    try {
      await acquireRealmSharedLease(coordinator);
    } catch {
      notifyTransitionUnavailable(coordinator);
      return;
    }
  }
  if (wasActive) notifyTransitionEnd(transition.id);
}

/** Hold a shared lease through response observation; exact transition owners run under exclusive. */
export async function withStudentAuthRequestLease<T>(
  operation: () => Promise<T>,
  transition?: StudentAuthTransition,
): Promise<T> {
  if (!isBrowserRealm()) return operation();
  if (transition) {
    if (directStudentAuthTransitions.has(transition)) return operation();
    const pending = pendingTransitionHandles.get(transition);
    if (!pending || !pending.exclusiveHeld || pending.failed || pending.finished) {
      throw new Error('student_auth_transition_capability_invalid');
    }
    return operation();
  }
  const coordinator = ensureTransitionCoordinator();
  if (!coordinator || coordinator.stickyUnavailable) {
    throw new Error('student_auth_transition_unavailable');
  }
  // A request first captured after teardown has a fresh null-actor fence. Do not
  // let it queue behind the exclusive lease and dispatch under the replacement
  // cookie before authoritative session rediscovery publishes that actor.
  if (coordinator.activeTransitions.size > 0) {
    throw new Error('student_auth_transition_active');
  }
  const fence = captureStudentContextFence();
  await acquireRealmSharedLease(coordinator);
  try {
    return await coordinator.locks.request(
      STUDENT_AUTH_SESSION_LOCK,
      { mode: 'shared', signal: fence.signal },
      async () => {
        if (coordinator.activeTransitions.size > 0) {
          throw new Error('student_auth_transition_active');
        }
        if (!isStudentContextFenceCurrent(fence) || coordinator.stickyUnavailable) {
          throw new Error('student_context_changed');
        }
        return operation();
      },
    );
  } catch (error) {
    // A peer start clears the generation fence while an ordinary request is
    // still queued behind the writer. Web Locks reports that as AbortError;
    // expose the stable boundary verdict and never let transport code infer a
    // retry under the replacement cookie.
    if (coordinator.activeTransitions.size > 0) {
      const boundaryError = new Error('student_auth_transition_active') as Error & {
        cause: unknown;
      };
      boundaryError.cause = error;
      throw boundaryError;
    }
    if (!isStudentContextFenceCurrent(fence)) {
      const boundaryError = new Error('student_context_changed') as Error & { cause: unknown };
      boundaryError.cause = error;
      throw boundaryError;
    }
    throw error;
  }
}

/**
 * Publish an already-observed authority loss as an ordered start/end pair so
 * every realm clears before any realm rediscovers the cookie.
 */
export function notifyStudentAuthChanged(
  options: Pick<ClearStudentBrowserContextOptions, 'preserveProfileReauthHandoff'> = {},
): void {
  const transition = startStudentAuthTransition(options);
  void transition.run(async () => undefined).catch(() => undefined).finally(() => {
    void finishStudentAuthTransition(transition);
  });
}

/**
 * Cold-realm bounded cleanup. Every key here belongs to a retired private app
 * namespace; approved device preferences and unrelated browser data survive.
 */
export function retireLegacyStudentRegistrationState(): boolean {
  const local = availableStorage('localStorage');
  let cleanupComplete = true;
  if (local) {
    cleanupComplete = purgeLegacyStudentLocalStorage(local).complete;
  } else if (isBrowserRealm()) {
    cleanupComplete = false;
  }
  const session = availableStorage('sessionStorage');
  if (session) {
    cleanupComplete = purgeLegacyStudentSessionStorage(session).complete && cleanupComplete;
  } else if (isBrowserRealm()) {
    cleanupComplete = false;
  }
  return cleanupComplete;
}
