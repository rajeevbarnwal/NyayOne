import { describe, expect, it } from 'vitest';
import { DraftQueue, InMemoryDraftStore, canTransition } from './draftQueue';
import { queryClient } from '../app/queryClient';

describe('offline draft/sync queue (SAATHI-346)', () => {
  it('happy path: local_draft → queued → syncing → synced', async () => {
    const q = new DraftQueue(new InMemoryDraftStore());
    const d = await q.saveLocal('d1', 'clinical_log', { hours: 3 });
    expect(d.state).toBe('local_draft');
    expect((await q.enqueue('d1')).state).toBe('queued');
    expect((await q.beginSync('d1')).state).toBe('syncing');
    expect((await q.markSynced('d1')).state).toBe('synced');
    expect(await q.pending()).toHaveLength(0);
  });

  it('failure and conflict paths recover to queued', async () => {
    const q = new DraftQueue(new InMemoryDraftStore());
    await q.saveLocal('d2', 'exam_note', {});
    await q.enqueue('d2');
    await q.beginSync('d2');
    expect((await q.markFailed('d2')).state).toBe('sync_failed');
    expect((await q.enqueue('d2')).state).toBe('queued'); // retry
    await q.beginSync('d2');
    expect((await q.markConflict('d2')).state).toBe('conflict');
    expect(await q.pending()).toHaveLength(1);
  });

  it('rejects illegal transitions', async () => {
    const q = new DraftQueue(new InMemoryDraftStore());
    await q.saveLocal('d3', 'k', {});
    await expect(q.markSynced('d3')).rejects.toThrow(); // local_draft -> synced not allowed
    expect(canTransition('local_draft', 'synced')).toBe(false);
    expect(canTransition('syncing', 'synced')).toBe(true);
  });
});

describe('query client config (SAATHI-346)', () => {
  it('has conservative defaults', () => {
    const opts = queryClient.getDefaultOptions();
    expect(opts.queries?.refetchOnWindowFocus).toBe(false);
    expect(opts.queries?.retry).toBe(1);
  });
});
