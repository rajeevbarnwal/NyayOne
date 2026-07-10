import { describe, expect, it } from 'vitest';
import {
  openReview,
  reviewAccessible,
  isStale,
  addComment,
  requestChanges,
  clientApprove,
  revokeReview,
  isFilingApproval,
  checklistClientApproved,
  sendReviewLink,
  reviewAuditEvent,
  urlHasNoPii,
  type ReviewSession,
} from './clientReview';
import { approveVersion, type ApprovalRecord } from './drafting';

const ISO = '2026-07-11T00:00:00.000Z';
const DAY = 24 * 60 * 60 * 1000;

function approvedSession(now = 1_000): { s: ReviewSession; approvals: ApprovalRecord[] } {
  const approvals = approveVersion([], 'v1-x', 'lawyer:rao', ISO);
  const s = openReview('v1-x', approvals, 'opaque-token-abc', now, ISO)!;
  return { s, approvals };
}

describe('E07 client review (SAATHI-18)', () => {
  it('opens a review only for a lawyer-approved version; link carries no PII', () => {
    // Not approved → refused.
    expect(openReview('v1-x', [], 'tok', 1_000, ISO)).toBeNull();
    const { s } = approvedSession();
    expect(s.status).toBe('sent');
    expect(urlHasNoPii(s.link.url)).toBe(true);
    expect(s.draftVersionId).toBe('v1-x');
  });

  it('expires and revokes; blocks access accordingly', () => {
    const { s } = approvedSession(1_000);
    expect(reviewAccessible(s, 2_000)).toBe(true);
    expect(reviewAccessible(s, 1_000 + 3 * DAY + 1)).toBe(false); // 72h ttl elapsed
    const revoked = revokeReview(s, 2_000);
    expect(revoked.revoked).toBe(true);
    expect(reviewAccessible(revoked, 2_100)).toBe(false);
  });

  it('binds comments/approval to the version and blocks stale reviews', () => {
    const { s } = approvedSession(1_000);
    // Same version → comment accepted.
    const commented = addComment(s, 'v1-x', 'Please fix the date', 2_000, ISO);
    expect(commented.comments).toHaveLength(1);
    expect(commented.comments[0].draftVersionId).toBe('v1-x');
    // A newer version exists → stale → comment refused, logged.
    expect(isStale(s, 'v2-y')).toBe(true);
    const staleComment = addComment(s, 'v2-y', 'late comment', 2_100, ISO);
    expect(staleComment.comments).toHaveLength(0);
    expect(staleComment.accessLog.some((e) => e.action === 'denied_stale')).toBe(true);
    // Stale approval also refused.
    const staleApprove = clientApprove(s, 'v2-y', 2_200, ISO);
    expect(staleApprove.status).not.toBe('approved');
  });

  it('records client approval distinct from filing approval and ticks checklist', () => {
    const { s } = approvedSession(1_000);
    const approved = clientApprove(s, 'v1-x', 2_000, ISO);
    expect(approved.status).toBe('approved');
    expect(checklistClientApproved(approved)).toBe(true);
    // Guardrail: client approval is NOT filing approval.
    expect(isFilingApproval()).toBe(false);
  });

  it('requests changes and refuses on expired link', () => {
    const { s } = approvedSession(1_000);
    const rc = requestChanges(s, 'v1-x', 'Add prayer clause', 2_000, ISO);
    expect(rc.status).toBe('changes_requested');
    const expired = addComment(s, 'v1-x', 'too late', 1_000 + 3 * DAY + 5, ISO);
    expect(expired.status).toBe('expired');
    expect(expired.accessLog.some((e) => e.action === 'denied_expired')).toBe(true);
  });

  it('gates the review-link notification on consent and audits', () => {
    expect(sendReviewLink({ channel: 'whatsapp', optedIn: false, loggedAt: null })).toBe('skipped_no_consent');
    expect(sendReviewLink({ channel: 'whatsapp', optedIn: true, loggedAt: ISO })).toBe('sent');
    const { s } = approvedSession();
    expect(reviewAuditEvent('review_sent', s, ISO).draftVersionId).toBe('v1-x');
  });
});
