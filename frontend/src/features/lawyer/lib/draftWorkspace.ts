/**
 * Draft workspace repository/service (SAATHI-16 remediation · E06).
 *
 * Wraps the pure drafting domain logic (drafting.ts) with a persistence boundary
 * so a case's draft versions + approval records survive refresh/reload and can be
 * handed to the client-review flow (E07) WITHOUT any hard-coded seed version.
 *
 * Persistence uses the shared KvStore. The app default is memory-only; callers
 * may inject another driver at an explicit boundary.
 */
import {
  addVersion, approveVersion, latestVersion as latestOf, isVersionApproved, canExportForFiling,
  type DraftVersion, type ApprovalRecord, type NewVersionInput,
} from './drafting';
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';

export interface DraftWorkspace {
  readonly caseId: string;
  readonly workspaceId: string;
  readonly title: string;
  readonly versions: DraftVersion[];
  readonly approvals: ApprovalRecord[];
  readonly updatedAt: number;
}

const DRAFT_WORKSPACE_KEY_PREFIX = 'nyayone.lawyer.draft-workspace.v1.';
const wsKey = (id: string) => `${DRAFT_WORKSPACE_KEY_PREFIX}${id}`;
const CURRENT_KEY = `${DRAFT_WORKSPACE_KEY_PREFIX}current`;

/** Stable, deterministic workspace id derived from the case id. */
export function workspaceIdFor(caseId: string): string {
  return `WS-${caseId}`;
}

export class DraftWorkspaceService {
  constructor(private store: KvStore = defaultKvStore()) {}

  private save(ws: DraftWorkspace): DraftWorkspace {
    const next = { ...ws, updatedAt: Date.now() };
    this.store.set(wsKey(ws.workspaceId), next);
    return next;
  }

  /** Create (or return existing) workspace for a case. Idempotent per case id. */
  create(caseId: string, title: string): DraftWorkspace {
    const workspaceId = workspaceIdFor(caseId);
    const existing = this.get(workspaceId);
    if (existing) return existing;
    const ws: DraftWorkspace = { caseId, workspaceId, title, versions: [], approvals: [], updatedAt: Date.now() };
    return this.save(ws);
  }

  get(workspaceId: string): DraftWorkspace | null {
    return this.store.get<DraftWorkspace>(wsKey(workspaceId));
  }

  /** Append an immutable version (persisted). */
  addVersion(workspaceId: string, input: NewVersionInput): DraftWorkspace {
    const ws = this.require(workspaceId);
    const versions = addVersion(ws.versions, input);
    return this.save({ ...ws, versions });
  }

  /** Record a lawyer approval for a specific version (persisted, idempotent). */
  approve(workspaceId: string, versionId: string, lawyerId: string, now: string): DraftWorkspace {
    const ws = this.require(workspaceId);
    const approvals = approveVersion(ws.approvals, versionId, lawyerId, now);
    return this.save({ ...ws, approvals });
  }

  latestVersion(workspaceId: string): DraftVersion | null {
    const ws = this.get(workspaceId);
    return ws ? latestOf(ws.versions) : null;
  }

  /** Most recent version that carries a lawyer approval (E06→E07 handoff source). */
  latestApprovedVersion(workspaceId: string): DraftVersion | null {
    const ws = this.get(workspaceId);
    if (!ws) return null;
    for (let i = ws.versions.length - 1; i >= 0; i -= 1) {
      if (isVersionApproved(ws.approvals, ws.versions[i].id)) return ws.versions[i];
    }
    return null;
  }

  canExport(workspaceId: string): boolean {
    const ws = this.get(workspaceId);
    return ws ? canExportForFiling(ws.versions, ws.approvals) : false;
  }

  /** Pointer used to hand a case from E06 to E07 without a fixture. */
  setCurrent(workspaceId: string): void {
    this.store.set(CURRENT_KEY, workspaceId);
  }
  getCurrent(): string | null {
    return this.store.get<string>(CURRENT_KEY);
  }

  private require(workspaceId: string): DraftWorkspace {
    const ws = this.get(workspaceId);
    if (!ws) throw new Error(`workspace not found: ${workspaceId}`);
    return ws;
  }
}
