import { describe, expect, it } from 'vitest';
import { ReviewWorkspaceService } from './reviewWorkspace';
import { DraftWorkspaceService } from './draftWorkspace';
import { addComment, clientApprove } from './clientReview';
import { InMemoryKvStore } from '../../../lib/kvStore';

const t = (n: number) => `2026-07-11T00:0${n}:00.000Z`;
const CASE = 'LS-CASE-2026-014';

function setup() {
  const store = new InMemoryKvStore();
  const drafts = new DraftWorkspaceService(store);
  const reviews = new ReviewWorkspaceService(store, drafts);
  const ws = drafts.create(CASE, 'Acme v. Sunrise');
  drafts.setCurrent(ws.workspaceId);
  return { store, drafts, reviews, id: ws.workspaceId };
}

describe('E06→E07 immutable handoff (SAATHI-18 remediation)', () => {
  it('refuses to open when there is no approved version', () => {
    const { reviews, drafts, id } = setup();
    drafts.addVersion(id, { authorId: 'a', createdAt: t(1), changeNote: 'draft', body: 'A', aiGenerated: true });
    expect(reviews.resolve(id)).toBeNull(); // not approved yet → no review context
    expect(reviews.open(id, 'tok', 1000, t(1))).toBeNull();
  });

  it('binds the review to the actual latest approved version (no seed)', () => {
    const { reviews, drafts, id } = setup();
    drafts.addVersion(id, { authorId: 'a', createdAt: t(1), changeNote: 'draft', body: 'A', aiGenerated: true });
    const v1 = drafts.latestVersion(id)!;
    drafts.approve(id, v1.id, 'lawyer:rao', t(2));
    const ctx = reviews.resolve(id)!;
    expect(ctx.approvedVersionId).toBe(v1.id);
    const session = reviews.open(id, 'opaque-tok', 1000, t(2))!;
    expect(session.draftVersionId).toBe(v1.id);
    expect(session.link.url.includes('@')).toBe(false); // no PII in URL
  });

  it('retains the session/version binding across reload', () => {
    const { store, reviews, drafts, id } = setup();
    drafts.addVersion(id, { authorId: 'a', createdAt: t(1), changeNote: 'draft', body: 'A', aiGenerated: true });
    drafts.approve(id, drafts.latestVersion(id)!.id, 'lawyer:rao', t(2));
    const session = reviews.open(id, 'tok', 1000, t(2))!;
    // Reload: fresh services on the same store.
    const drafts2 = new DraftWorkspaceService(store);
    const reviews2 = new ReviewWorkspaceService(store, drafts2);
    const ctx = reviews2.resolve(id)!;
    expect(ctx.session!.draftVersionId).toBe(session.draftVersionId);
    expect(ctx.stale).toBe(false);
  });

  it('marks the review stale when a newer version is created; comments stay on the original', () => {
    const { reviews, drafts, id } = setup();
    drafts.addVersion(id, { authorId: 'a', createdAt: t(1), changeNote: 'draft', body: 'A', aiGenerated: true });
    const v1 = drafts.latestVersion(id)!;
    drafts.approve(id, v1.id, 'lawyer:rao', t(2));
    let session = reviews.open(id, 'tok', 1000, t(2))!;
    session = addComment(session, v1.id, 'Please fix date', 1100, t(2));
    session = clientApprove(session, v1.id, 1200, t(2));
    reviews.update(id, session);
    expect(session.comments[0].draftVersionId).toBe(v1.id);

    // A newer E06 version appears → the existing review is now stale.
    drafts.addVersion(id, { authorId: 'a', createdAt: t(3), changeNote: 'v2', body: 'B', aiGenerated: false });
    const ctx = reviews.resolve(id)!;
    expect(ctx.stale).toBe(true);
    // Comment + approval remain attached to v1, never transferred to the new version.
    expect(ctx.session!.comments[0].draftVersionId).toBe(v1.id);
    expect(ctx.session!.draftVersionId).toBe(v1.id);
    expect(ctx.latestVersionId).not.toBe(v1.id);
  });
});
