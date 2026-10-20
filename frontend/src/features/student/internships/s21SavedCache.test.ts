import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { settleS21Saved } from './s21SavedCache';
import type { InternshipListing } from '../lib/internships';

const item: InternshipListing = { id: 'role', role: 'Research intern', org: 'Synthetic chambers', location: 'Delhi', stipendMonthlyPaise: null, verificationStatus: 'unverified', deadline: '8 Jul 2027', eligibility: 'Student', tags: [], description: 'Research', source: { name: 'Synthetic', url: null, retrievedAt: null, verifiedAt: null } };
const key = ['internships-saved', 'actor-a'];
describe('S-21 R2-1 confirmed save/unsave versus pre-commit saved reads', () => {
  it.each([true, false])('a late stale GET cannot overwrite confirmed saved=%s', async saved => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const stale = saved ? [] : [item];
    client.setQueryData(key, stale);
    let release!: (value: InternshipListing[]) => void;
    // Intentionally ignores AbortSignal: cancellation must also fence settlement.
    const read = client.fetchQuery({ queryKey: key, queryFn: () => new Promise<InternshipListing[]>(resolve => { release = resolve; }) }).catch(() => undefined);
    await settleS21Saved(client, 'actor-a', item, saved, () => true);
    expect(client.getQueryData(key)).toEqual(saved ? [item] : []);
    release(stale); await read;
    expect(client.getQueryData(key)).toEqual(saved ? [item] : []);
    expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    client.clear();
  });
  it('invalidates both shared consumers and a legacy S-20 key without touching another actor', async () => {
    const client = new QueryClient();
    client.setQueryData(key, []);
    client.setQueryData(['s20-saved', 'actor-a'], []);
    client.setQueryData(['internships-saved', 'actor-b'], []);
    await settleS21Saved(client, 'actor-a', item, true, () => true);
    expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    expect(client.getQueryState(['s20-saved', 'actor-a'])?.isInvalidated).toBe(true);
    expect(client.getQueryData(['internships-saved', 'actor-b'])).toEqual([]);
    expect(client.getQueryState(['internships-saved', 'actor-b'])?.isInvalidated).toBe(false);
    client.clear();
  });
  it('does not repopulate a cache after the actor generation changes', async () => {
    const client = new QueryClient();
    await settleS21Saved(client, 'actor-a', item, true, () => false);
    expect(client.getQueryData(key)).toBeUndefined();
    client.clear();
  });
  it('rechecks the actor fence after cancellation awaits, without publishing into a replaced session', async () => {
    const client = new QueryClient();
    client.setQueryData(key, []);
    let current = true;
    const original = client.cancelQueries.bind(client);
    vi.spyOn(client, 'cancelQueries').mockImplementation(async (...args) => { await original(...args); current = false; });
    await settleS21Saved(client, 'actor-a', item, true, () => current);
    expect(client.getQueryData(key)).toEqual([]);
    expect(client.getQueryState(key)?.isInvalidated).toBe(false);
    client.clear();
  });
});
