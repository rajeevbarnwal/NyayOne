/**
 * Repo-native import of the independent shared-KvStore contract suite
 * (`kvstore_contract_adversarial.test.ts` @ 4d5fc7f QA) — every assertion kept
 * verbatim. Locks the `KvStore.get<T>(): T | null` contract permanently:
 * a missing key returns null across both drivers and through the shared
 * auth-persistence and draft-workspace services.
 */
import { describe, expect, it, vi } from 'vitest';
import { InMemoryKvStore, LocalKvStore, defaultKvStore, type KvStore } from './kvStore';
import { loadAuthSnapshot } from '../features/auth/lib/authPersistence';
import { DraftWorkspaceService } from '../features/lawyer/lib/draftWorkspace';

describe('Independent shared KvStore contract QA — 49d0f10', () => {
  it('returns null for a missing key as required by KvStore.get<T>(): T | null', () => {
    const store: KvStore = new InMemoryKvStore();
    expect(store.get('never-written')).toBeNull();
  });

  it('keeps in-memory and local-storage drivers semantically aligned when storage is unavailable', () => {
    const memory: KvStore = new InMemoryKvStore();
    const local: KvStore = new LocalKvStore();
    expect(memory.get('missing')).toBe(local.get('missing'));
    expect(local.get('missing')).toBeNull();
  });

  it('preserves declared null semantics through auth persistence on first load', () => {
    expect(loadAuthSnapshot('student', new InMemoryKvStore())).toBeNull();
  });

  it('preserves declared null semantics through shared workspace services', () => {
    expect(new DraftWorkspaceService(new InMemoryKvStore()).get('missing-workspace')).toBeNull();
  });

  it('uses a memory-only default even when localStorage is available', () => {
    const setItem = vi.fn();
    vi.stubGlobal('window', { localStorage: { setItem } });
    const store = defaultKvStore();
    store.set('actor-derived-key', { private: true });
    expect(store.get('actor-derived-key')).toEqual({ private: true });
    expect(setItem).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
