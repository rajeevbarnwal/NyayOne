/**
 * Redacted auth-lifecycle persistence (SAATHI-2 / SAATHI-3 remediation).
 * Stores only a secret-free AuthSnapshot so OTP flow state survives refresh /
 * navigation. Backed by the shared KvStore (localStorage in the browser).
 */
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';
import type { AuthSnapshot, AuthRole } from './authLifecycle';

const key = (role: AuthRole) => `ls-auth-${role}`;

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
  store.set(key(snap.role), snap);
  notifyAuthChanged();
}

export function loadAuthSnapshot(role: AuthRole, store: KvStore = defaultKvStore()): AuthSnapshot | null {
  return store.get<AuthSnapshot>(key(role));
}

export function clearAuthSnapshot(role: AuthRole, store: KvStore = defaultKvStore()): void {
  store.remove(key(role));
  notifyAuthChanged();
}
