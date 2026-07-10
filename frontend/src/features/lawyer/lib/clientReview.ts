/**
 * Send draft for client review logic (SAATHI-18 · Core E07).
 *
 * Pure, testable domain logic. A client review is bound to an IMMUTABLE draft
 * version id. The client-facing link expires, is revocable, and carries no PII.
 *
 * Guardrails (load-bearing):
 *  - Only a lawyer-APPROVED draft version may open a review session.
 *  - Comments and the client approval bind to the exact draft version id; if a
 *    newer version is produced the old review is STALE — its comments/approval
 *    never transfer to the new version.
 *  - Client approval is a recorded PRODUCT approval only. It is NOT lawyer filing
 *    approval, and implies no legal action — the lawyer confirms the next step.
 *  - Notifications are consent-gated and go through an adapter (no external send).
 */

import { makeSecureLink, linkValid, urlHasNoPii, type SecureLink } from './documents';
import { isVersionApproved, type ApprovalRecord } from './drafting';

export type ReviewStatus = 'sent' | 'commented' | 'changes_requested' | 'approved' | 'revoked' | 'expired';

export interface ReviewComment {
  readonly id: string;
  readonly draftVersionId: string; // bound to the reviewed version
  readonly author: 'client' | 'lawyer';
  readonly body: string;
  readonly createdAt: string;
}

export interface AccessLogEntry {
  readonly at: number;
  readonly action: 'opened' | 'commented' | 'approved' | 'revoked' | 'denied_expired' | 'denied_revoked' | 'denied_stale';
}

export interface ReviewSession {
  readonly id: string;
  readonly draftVersionId: string; // immutable binding
  readonly link: SecureLink;
  readonly status: ReviewStatus;
  readonly createdAt: string;
  readonly revoked: boolean;
  readonly comments: readonly ReviewComment[];
  readonly clientApprovedAt: string | null;
  readonly accessLog: readonly AccessLogEntry[];
}

export const CLIENT_APPROVAL_NOTE =
  'Client approval is a recorded product acknowledgement of this draft version. It is not filing authorisation — your lawyer confirms the next step.';

/**
 * Open a review session for a draft version. Refused unless that version is
 * lawyer-approved. The token is opaque; the URL carries no PII.
 */
export function openReview(
  draftVersionId: string,
  approvals: readonly ApprovalRecord[],
  token: string,
  now: number,
  createdAtISO: string,
  ttlMs = 72 * 60 * 60 * 1000
): ReviewSession | null {
  if (!isVersionApproved(approvals, draftVersionId)) return null;
  const link = makeSecureLink(token, now, ttlMs);
  return {
    id: `rev-${draftVersionId}-${now}`,
    draftVersionId,
    link,
    status: 'sent',
    createdAt: createdAtISO,
    revoked: false,
    comments: [],
    clientApprovedAt: null,
    accessLog: [],
  };
}

/** A session is accessible only if not revoked and the link is still valid. */
export function reviewAccessible(s: ReviewSession, now: number): boolean {
  return !s.revoked && linkValid(s.link, now);
}

/**
 * A session is STALE when a newer draft version exists beyond the one it was
 * bound to. Stale sessions must not accept comments/approval — feedback never
 * transfers to a newer version.
 */
export function isStale(s: ReviewSession, latestVersionId: string): boolean {
  return s.draftVersionId !== latestVersionId;
}

function log(s: ReviewSession, entry: AccessLogEntry): AccessLogEntry[] {
  return [...s.accessLog, entry];
}

/** Record a client comment — refused when revoked/expired/stale. */
export function addComment(
  s: ReviewSession,
  latestVersionId: string,
  body: string,
  now: number,
  createdAtISO: string
): ReviewSession {
  if (s.revoked) return { ...s, accessLog: log(s, { at: now, action: 'denied_revoked' }) };
  if (!linkValid(s.link, now)) return { ...s, status: 'expired', accessLog: log(s, { at: now, action: 'denied_expired' }) };
  if (isStale(s, latestVersionId)) return { ...s, accessLog: log(s, { at: now, action: 'denied_stale' }) };
  const comment: ReviewComment = { id: `c${s.comments.length + 1}`, draftVersionId: s.draftVersionId, author: 'client', body, createdAt: createdAtISO };
  return { ...s, status: 'commented', comments: [...s.comments, comment], accessLog: log(s, { at: now, action: 'commented' }) };
}

export function requestChanges(s: ReviewSession, latestVersionId: string, body: string, now: number, createdAtISO: string): ReviewSession {
  const next = addComment({ ...s }, latestVersionId, body, now, createdAtISO);
  if (next.status === 'commented') return { ...next, status: 'changes_requested' };
  return next;
}

/** Record client approval — refused when revoked/expired/stale. Bound to version. */
export function clientApprove(s: ReviewSession, latestVersionId: string, now: number, approvedAtISO: string): ReviewSession {
  if (s.revoked) return { ...s, accessLog: log(s, { at: now, action: 'denied_revoked' }) };
  if (!linkValid(s.link, now)) return { ...s, status: 'expired', accessLog: log(s, { at: now, action: 'denied_expired' }) };
  if (isStale(s, latestVersionId)) return { ...s, accessLog: log(s, { at: now, action: 'denied_stale' }) };
  return { ...s, status: 'approved', clientApprovedAt: approvedAtISO, accessLog: log(s, { at: now, action: 'approved' }) };
}

export function revokeReview(s: ReviewSession, now: number): ReviewSession {
  return { ...s, revoked: true, status: 'revoked', accessLog: log(s, { at: now, action: 'revoked' }) };
}

/** Client approval must NEVER be treated as lawyer filing approval. */
export function isFilingApproval(): boolean {
  return false;
}

/** Whether a client approval should tick the matter checklist item. */
export function checklistClientApproved(s: ReviewSession): boolean {
  return s.status === 'approved' && s.clientApprovedAt !== null;
}

// --- Consent-gated notification (adapter boundary; no external send) ---------

export interface ReviewNotifyConsent {
  readonly channel: 'whatsapp' | 'email';
  readonly optedIn: boolean;
  readonly loggedAt: string | null;
}
export type NotifyOutcome = 'sent' | 'skipped_no_consent';

export function sendReviewLink(consent: ReviewNotifyConsent): NotifyOutcome {
  return consent.optedIn && consent.loggedAt ? 'sent' : 'skipped_no_consent';
}

// --- Audit -------------------------------------------------------------------

export type ReviewAuditType = 'review_sent' | 'review_opened' | 'commented' | 'changes_requested' | 'client_approved' | 'revoked' | 'expired' | 'failure';
export interface ReviewAuditEvent {
  readonly type: ReviewAuditType;
  readonly reviewId: string;
  readonly draftVersionId: string;
  readonly timestamp: string;
}
export function reviewAuditEvent(type: ReviewAuditType, s: ReviewSession, now: string): ReviewAuditEvent {
  return { type, reviewId: s.id, draftVersionId: s.draftVersionId, timestamp: now };
}

/** Re-exported guardrail helper for the UI. */
export { urlHasNoPii };

export const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  sent: 'Sent',
  commented: 'Comments received',
  changes_requested: 'Changes requested',
  approved: 'Client approved',
  revoked: 'Revoked',
  expired: 'Expired',
};
