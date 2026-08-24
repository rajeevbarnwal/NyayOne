import { describe, expect, it } from 'vitest';
import type { KvStore } from '../../../lib/kvStore';
import type { ReviewSession } from './clientReview';
import { DraftWorkspaceService } from './draftWorkspace';
import { FilingWorkflowService } from './filingWorkflow';
import { ReviewWorkspaceService } from './reviewWorkspace';

class RecordingKvStore implements KvStore {
  readonly reads: string[] = [];
  readonly writes: string[] = [];
  readonly removals: string[] = [];
  readonly values = new Map<string, unknown>();

  constructor(entries: readonly (readonly [string, unknown])[] = []) {
    for (const [key, value] of entries) this.values.set(key, value);
  }

  get<T>(key: string): T | null {
    this.reads.push(key);
    return this.values.has(key) ? this.values.get(key) as T : null;
  }

  set<T>(key: string, value: T): void {
    this.writes.push(key);
    this.values.set(key, value);
  }

  remove(key: string): void {
    this.removals.push(key);
    this.values.delete(key);
  }
}

const REVIEW: ReviewSession = {
  id: 'review-nyay18',
  draftVersionId: 'draft-nyay18',
  link: { token: 'opaque', url: '/u/opaque', expiresAt: 2_000_000_000_000 },
  status: 'sent',
  createdAt: '2026-08-23T00:00:00.000Z',
  revoked: false,
  comments: [],
  clientApprovedAt: null,
  accessLog: [],
};

function expectOnlyNyayOneActiveKeys(store: RecordingKvStore): void {
  expect([...store.reads, ...store.writes]).not.toEqual(
    expect.arrayContaining([expect.stringMatching(/^ls-/)]),
  );
}

describe('NYAY-18 lawyer workflow browser namespaces', () => {
  it('uses versioned NyayOne draft keys and never reads inherited draft values', () => {
    const workspaceId = 'WS-CASE-NYAY18';
    const store = new RecordingKvStore([
      [`ls-draftws-${workspaceId}`, { workspaceId, title: 'legacy private draft' }],
      ['ls-draftws-current', workspaceId],
    ]);
    const service = new DraftWorkspaceService(store);

    expect(service.get(workspaceId)).toBeNull();
    expect(service.getCurrent()).toBeNull();
    const created = service.create('CASE-NYAY18', 'NyayOne draft');
    service.setCurrent(created.workspaceId);

    expect(store.reads).toContain(`nyayone.lawyer.draft-workspace.v1.${workspaceId}`);
    expect(store.reads).toContain('nyayone.lawyer.draft-workspace.v1.current');
    expect(store.writes).toContain(`nyayone.lawyer.draft-workspace.v1.${workspaceId}`);
    expect(store.writes).toContain('nyayone.lawyer.draft-workspace.v1.current');
    expectOnlyNyayOneActiveKeys(store);
  });

  it('uses a versioned NyayOne review key and never reads inherited review values', () => {
    const workspaceId = 'WS-REVIEW-NYAY18';
    const store = new RecordingKvStore([[`ls-review-${workspaceId}`, REVIEW]]);
    const service = new ReviewWorkspaceService(store);

    expect(service.loadSession(workspaceId)).toBeNull();
    service.saveSession(workspaceId, REVIEW);

    expect(store.reads).toEqual([`nyayone.lawyer.review-workspace.v1.${workspaceId}`]);
    expect(store.writes).toEqual([`nyayone.lawyer.review-workspace.v1.${workspaceId}`]);
    expectOnlyNyayOneActiveKeys(store);
  });

  it('uses a versioned NyayOne filing key and never reads inherited filing values', () => {
    const workspaceId = 'WS-FILING-NYAY18';
    const store = new RecordingKvStore([[`ls-filing-${workspaceId}`, { workspaceId }]]);
    const service = new FilingWorkflowService(store);

    expect(service.get(workspaceId)).toBeNull();

    expect(store.reads).toEqual([`nyayone.lawyer.filing-workflow.v1.${workspaceId}`]);
    expectOnlyNyayOneActiveKeys(store);
  });
});
