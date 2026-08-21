/**
 * Legacy lawyer-demo snapshot persistence.
 *
 * Student OTP state must never enter this store. NYAY-4 moves that lifecycle to
 * the HttpOnly flow cookie and GET /otp/state, so the historical
 * `ls-auth-student` entry is retired rather than migrated.
 */
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';
import type { AuthSnapshot, AuthRole } from './authLifecycle';

const key = (role: AuthRole) => `ls-auth-${role}`;
export const RETIRED_STUDENT_AUTH_KEY = 'ls-auth-student';

/**
 * In-SPA auth-change signal (SAATHI-337 reactive-auth remediation). Snapshot
 * create/update/clear dispatch this event so AuthProvider re-derives immediately
 * without a full reload. Cross-tab changes arrive via the native `storage` event.
 */
export const AUTH_CHANGE_EVENT = 'ls-auth-change';

export function notifyAuthChanged(): void {
  if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
    window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
  }
}

/** Subscribe to auth-state changes (in-tab event + cross-tab storage). Returns an unsubscribe. */
export function subscribeAuthChange(cb: () => void): () => void {
  if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return () => {};
  window.addEventListener(AUTH_CHANGE_EVENT, cb);
  window.addEventListener('storage', cb);
  return () => {
    window.removeEventListener(AUTH_CHANGE_EVENT, cb);
    window.removeEventListener('storage', cb);
  };
}

export function saveAuthSnapshot(snap: AuthSnapshot, store: KvStore = defaultKvStore()): void {
  if (snap.role === 'student') {
    store.remove(RETIRED_STUDENT_AUTH_KEY);
    notifyAuthChanged();
    return;
  }
  store.set(key(snap.role), snap);
  notifyAuthChanged();
}

export function loadAuthSnapshot(role: AuthRole, store: KvStore = defaultKvStore()): AuthSnapshot | null {
  if (role === 'student') {
    store.remove(RETIRED_STUDENT_AUTH_KEY);
    return null;
  }
  return store.get<AuthSnapshot>(key(role));
}

export interface ClearAuthSnapshotOptions {
  /** Derivation-time cleanup is already inside a refresh and must not recurse. */
  notifyAuthChanged?: boolean;
}

export function clearAuthSnapshot(
  role: AuthRole,
  store: KvStore = defaultKvStore(),
  options: ClearAuthSnapshotOptions = {},
): void {
  store.remove(key(role));
  if (options.notifyAuthChanged !== false) notifyAuthChanged();
}

export function retireStudentAuthSnapshot(store: KvStore = defaultKvStore()): void {
  store.remove(RETIRED_STUDENT_AUTH_KEY);
}

// Execute at bundle bootstrap. Reload/state discovery paths call this again so
// late-available Storage implementations cannot resurrect the retired state.
retireStudentAuthSnapshot();
