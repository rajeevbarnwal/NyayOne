/**
 * Offline draft / sync queue (SAATHI-346) for low-connectivity flows.
 *
 * State machine per draft: local_draft → queued → syncing → synced,
 * with failure paths sync_failed and conflict. Persistence is behind a
 * DraftStore driver: production uses IndexedDB (IndexedDbDraftStore), tests use
 * an in-memory driver — so behavior is unit-testable without a browser/IndexedDB.
 */
export type DraftState =
  | 'local_draft'
  | 'queued'
  | 'syncing'
  | 'synced'
  | 'sync_failed'
  | 'conflict';

export interface Draft {
  id: string;
  kind: string; // e.g. 'clinical_log', 'exam_note'
  data: unknown;
  state: DraftState;
  updatedAt: number;
}

export interface DraftStore {
  put(draft: Draft): Promise<void>;
  get(id: string): Promise<Draft | undefined>;
  list(): Promise<Draft[]>;
  delete(id: string): Promise<void>;
}

/** In-memory driver (tests / SSR fallback). */
export class InMemoryDraftStore implements DraftStore {
  private map = new Map<string, Draft>();
  async put(d: Draft) { this.map.set(d.id, { ...d }); }
  async get(id: string) { return this.map.get(id); }
  async list() { return [...this.map.values()]; }
  async delete(id: string) { this.map.delete(id); }
}

/** Valid forward transitions for the sync state machine. */
const TRANSITIONS: Record<DraftState, DraftState[]> = {
  local_draft: ['queued'],
  queued: ['syncing'],
  syncing: ['synced', 'sync_failed', 'conflict'],
  sync_failed: ['queued'],
  conflict: ['queued', 'local_draft'],
  synced: [],
};

export function canTransition(from: DraftState, to: DraftState): boolean {
  return TRANSITIONS[from]?.includes(to) ?? false;
}

export class DraftQueue {
  constructor(private store: DraftStore) {}

  async saveLocal(id: string, kind: string, data: unknown): Promise<Draft> {
    const draft: Draft = { id, kind, data, state: 'local_draft', updatedAt: Date.now() };
    await this.store.put(draft);
    return draft;
  }

  private async transition(id: string, to: DraftState): Promise<Draft> {
    const d = await this.store.get(id);
    if (!d) throw new Error(`draft not found: ${id}`);
    if (!canTransition(d.state, to)) throw new Error(`illegal transition ${d.state} -> ${to}`);
    const next = { ...d, state: to, updatedAt: Date.now() };
    await this.store.put(next);
    return next;
  }

  enqueue(id: string) { return this.transition(id, 'queued'); }
  beginSync(id: string) { return this.transition(id, 'syncing'); }
  markSynced(id: string) { return this.transition(id, 'synced'); }
  markFailed(id: string) { return this.transition(id, 'sync_failed'); }
  markConflict(id: string) { return this.transition(id, 'conflict'); }

  async pending(): Promise<Draft[]> {
    return (await this.store.list()).filter((d) => d.state !== 'synced');
  }
}
