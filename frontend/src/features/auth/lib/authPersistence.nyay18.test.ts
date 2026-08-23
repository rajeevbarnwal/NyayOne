import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import type { AuthSnapshot } from './authLifecycle';
import {
  AUTH_CHANGE_EVENT,
  loadAuthSnapshot,
  saveAuthSnapshot,
} from './authPersistence';

const lawyer: AuthSnapshot = {
  role: 'lawyer',
  phase: 'verified',
  destinationMasked: null,
  challenge: null,
  consentAt: null,
  subjectId: 'admin-subject',
  updatedAt: 1,
};

describe('NYAY-18 auth namespace retirement', () => {
  it('writes only the NyayOne auth namespace', () => {
    const store = new InMemoryKvStore();
    saveAuthSnapshot(lawyer, store);
    expect(store.get('nyayone.auth.lawyer.v1')).toEqual(lawyer);
    expect(store.get('ls-auth-lawyer')).toBeNull();
  });

  it('deletes an inherited lawyer snapshot without treating it as authority', () => {
    const store = new InMemoryKvStore();
    store.set('ls-auth-lawyer', lawyer);
    expect(loadAuthSnapshot('lawyer', store)).toBeNull();
    expect(store.get('ls-auth-lawyer')).toBeNull();
    expect(store.get('nyayone.auth.lawyer.v1')).toBeNull();
  });

  it('uses only the NyayOne in-tab event name', () => {
    expect(AUTH_CHANGE_EVENT).toBe('nyayone:auth-change');
  });
});
