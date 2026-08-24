/**
 * Legacy lawyer-demo snapshot persistence.
 *
 * Student OTP state must never enter this store. NYAY-4 moves that lifecycle to
 * the HttpOnly flow cookie and GET /otp/state, so the historical
 * inherited auth entries are retired rather than migrated.
 */
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';
import {
  LEGACY_LAWYER_AUTH_STORAGE_KEY,
  LEGACY_STUDENT_AUTH_STORAGE_KEY,
} from '../../student/lib/studentLegacyStorage';
import type { AuthSnapshot, AuthRole } from './authLifecycle';

const key = (role: AuthRole) => `nyayone.auth.${role}.v1`;
export const RETIRED_STUDENT_AUTH_KEY = LEGACY_STUDENT_AUTH_STORAGE_KEY;
export const RETIRED_LAWYER_AUTH_KEY = LEGACY_LAWYER_AUTH_STORAGE_KEY;

function retiredKey(role: AuthRole): string {
  return role === 'student' ? RETIRED_STUDENT_AUTH_KEY : RETIRED_LAWYER_AUTH_KEY;
}

/**
 * In-SPA auth-change signal (SAATHI-337 reactive-auth remediation). Snapshot
 * create/update/clear dispatch this event so AuthProvider re-derives immediately
 * without a full reload. Cross-tab changes arrive via the native `storage` event.
 */
export const AUTH_CHANGE_EVENT = 'nyayone:auth-change';

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
  store.remove(retiredKey(snap.role));
  if (snap.role === 'student') {
    store.remove(key('student'));
    notifyAuthChanged();
    return;
  }
  store.set(key(snap.role), snap);
  notifyAuthChanged();
}

export function loadAuthSnapshot(role: AuthRole, store: KvStore = defaultKvStore()): AuthSnapshot | null {
  store.remove(retiredKey(role));
  if (role === 'student') {
    store.remove(key('student'));
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
  store.remove(retiredKey(role));
  store.remove(key(role));
  if (options.notifyAuthChanged !== false) notifyAuthChanged();
}

export function retireStudentAuthSnapshot(store: KvStore = defaultKvStore()): void {
  store.remove(RETIRED_STUDENT_AUTH_KEY);
  store.remove(key('student'));
}

// Execute at bundle bootstrap. Reload/state discovery paths call this again so
// late-available Storage implementations cannot resurrect the retired state.
retireStudentAuthSnapshot();
