/**
 * Redacted auth-lifecycle persistence (SAATHI-2 / SAATHI-3 remediation).
 * Stores only a secret-free AuthSnapshot so OTP flow state survives refresh /
 * navigation. Backed by the shared KvStore (localStorage in the browser).
 */
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';
import type { AuthSnapshot, AuthRole } from './authLifecycle';

const key = (role: AuthRole) => `ls-auth-${role}`;

export function saveAuthSnapshot(snap: AuthSnapshot, store: KvStore = defaultKvStore()): void {
  store.set(key(snap.role), snap);
}

export function loadAuthSnapshot(role: AuthRole, store: KvStore = defaultKvStore()): AuthSnapshot | null {
  return store.get<AuthSnapshot>(key(role));
}

export function clearAuthSnapshot(role: AuthRole, store: KvStore = defaultKvStore()): void {
  store.remove(key(role));
}
