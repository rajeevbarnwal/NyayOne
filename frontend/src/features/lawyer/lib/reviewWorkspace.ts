/**
 * Client-review persistence + E06→E07 handoff (SAATHI-18 remediation · E07).
 *
 * Persists the review session bound to a specific, immutable approved draft
 * version so the binding survives refresh. Staleness is computed against the
 * live latest version of the draft workspace, so a newer E06 version marks the
 * existing review stale WITHOUT moving its comments/approval.
 *
 * There is NO hard-coded seed version — the approved version is resolved from the
 * persisted DraftWorkspace.
 */
import { openReview, type ReviewSession } from './clientReview';
import { DraftWorkspaceService } from './draftWorkspace';
import { defaultKvStore, type KvStore } from '../../../lib/kvStore';

const REVIEW_WORKSPACE_KEY_PREFIX = 'nyayone.lawyer.review-workspace.v1.';
const rKey = (workspaceId: string) => `${REVIEW_WORKSPACE_KEY_PREFIX}${workspaceId}`;

export interface ReviewContext {
  readonly workspaceId: string;
  readonly approvedVersionId: string;
  readonly latestVersionId: string;
  readonly session: ReviewSession | null;
  readonly stale: boolean;
}

export class ReviewWorkspaceService {
  constructor(
    private store: KvStore = defaultKvStore(),
    private drafts: DraftWorkspaceService = new DraftWorkspaceService(store),
  ) {}

  /** Resolve the current review context, or null when nothing can be reviewed. */
  resolve(workspaceId?: string): ReviewContext | null {
    const id = workspaceId ?? this.drafts.getCurrent();
    if (!id) return null;
    const approved = this.drafts.latestApprovedVersion(id);
    if (!approved) return null; // E07 refuses to open when no approved version exists
    const latest = this.drafts.latestVersion(id);
    const session = this.loadSession(id);
    const boundVersion = session ? session.draftVersionId : approved.id;
    return {
      workspaceId: id,
      approvedVersionId: approved.id,
      latestVersionId: latest ? latest.id : approved.id,
      session,
      stale: !!latest && boundVersion !== latest.id,
    };
  }

  loadSession(workspaceId: string): ReviewSession | null {
    return this.store.get<ReviewSession>(rKey(workspaceId));
  }

  saveSession(workspaceId: string, session: ReviewSession): void {
    this.store.set(rKey(workspaceId), session);
  }

  /** Open a review bound to the latest approved version; persisted for refresh. */
  open(workspaceId: string, token: string, now: number, createdAtISO: string): ReviewSession | null {
    const approved = this.drafts.latestApprovedVersion(workspaceId);
    if (!approved) return null;
    const session = openReview(approved.id, this.drafts.get(workspaceId)!.approvals, token, now, createdAtISO);
    if (session) this.saveSession(workspaceId, session);
    return session;
  }

  /** Persist a mutated session (comment/approve/revoke happen via pure fns). */
  update(workspaceId: string, session: ReviewSession): ReviewSession {
    this.saveSession(workspaceId, session);
    return session;
  }
}
