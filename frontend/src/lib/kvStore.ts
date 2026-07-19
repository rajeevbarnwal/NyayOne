/**
 * Small synchronous key/value persistence abstraction (SAATHI-2/3/4/16/18
 * remediation). Mirrors the DraftStore driver pattern (lib/draftQueue.ts): an
 * interface with a browser driver (localStorage — the convention already used by
 * useTheme + TraceabilityBanner) and an in-memory driver for tests/SSR.
 *
 * Synchronous by design so React screens can restore state during the first
 * render after a refresh without an async round-trip.
 *
 * NEVER store raw OTPs, passwords, session tokens or other secrets here — only
 * redacted, non-sensitive snapshots. Callers are responsible for redaction.
 */
export interface KvStore {
  get<T>(key: string): T | null;
  set<T>(key: string, value: T): void;
  remove(key: string): void;
}

/** In-memory driver (tests / SSR fallback). */
export class InMemoryKvStore implements KvStore {
  private map = new Map<string, string>();
  get<T>(key: string): T | null {
    const raw = this.map.get(key);
    // A key that was never written is genuinely absent (undefined); a key that
    // was written-then-removed carries a JSON `null` tombstone and reads back as
    // null. This distinction lets callers tell "no value yet" from "explicitly
    // cleared" while keeping every truthy / `== null` guard working unchanged.
    if (raw === undefined) return undefined as unknown as T | null;
    return raw === 'null' ? null : (JSON.parse(raw) as T);
  }
  set<T>(key: string, value: T): void {
    this.map.set(key, JSON.stringify(value));
  }
  remove(key: string): void {
    this.map.set(key, JSON.stringify(null)); // tombstone → get() returns null, not undefined
  }
}

/** localStorage-backed driver, guarded for non-browser environments. */
export class LocalKvStore implements KvStore {
  private canUse(): boolean {
    try {
      return typeof window !== 'undefined' && !!window.localStorage;
    } catch {
      return false;
    }
  }
  get<T>(key: string): T | null {
    if (!this.canUse()) return null;
    try {
      const raw = window.localStorage.getItem(key);
      return raw == null ? null : (JSON.parse(raw) as T);
    } catch {
      return null;
    }
  }
  set<T>(key: string, value: T): void {
    if (!this.canUse()) return;
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* quota / disabled — treat as best-effort */
    }
  }
  remove(key: string): void {
    if (!this.canUse()) return;
    try {
      window.localStorage.removeItem(key);
    } catch {
      /* no-op */
    }
  }
}

let singleton: KvStore | null = null;
/** Default app store: localStorage in the browser, in-memory otherwise. */
export function defaultKvStore(): KvStore {
  if (singleton) return singleton;
  const local = new LocalKvStore();
  // Probe: if localStorage is unusable, fall back to in-memory.
  singleton = typeof window !== 'undefined' && (() => { try { return !!window.localStorage; } catch { return false; } })()
    ? local
    : new InMemoryKvStore();
  return singleton;
}
