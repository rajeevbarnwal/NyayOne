/**
 * Moderated community foundation logic (SAATHI-74 · S10).
 * Enforces the load-bearing rule: raw allegations/content are NOT publicly
 * visible until moderated. Legal-advice requests are redirected, never answered.
 * Pure + testable; no external integrations.
 */

export type ModerationState = 'visible' | 'pending_review' | 'hidden' | 'removed' | 'escalated';

export interface Post {
  readonly id: string;
  readonly channel: string;
  readonly author: string;
  readonly title: string;
  readonly body: string;
  readonly replies: number;
  readonly moderation: ModerationState;
}

/** A post is shown in public feeds/threads ONLY when moderation === 'visible'. */
export function isPubliclyVisible(p: Pick<Post, 'moderation'>): boolean {
  return p.moderation === 'visible';
}

/** Public list = only moderated-visible posts (never raw/pending/removed). */
export function publicPosts(posts: readonly Post[]): Post[] {
  return posts.filter(isPubliclyVisible);
}

/** Body shown publicly, redacted until moderated (defamation/safety guardrail). */
export function publicBody(p: Post): string {
  return isPubliclyVisible(p)
    ? p.body
    : 'This content is under moderation and is not publicly visible.';
}

export type ReportReason = 'harassment' | 'misinformation' | 'spam' | 'off_topic';

export const REPORT_REASONS: ReadonlyArray<{ id: ReportReason; label: string; kind: 'risk' | 'warn' | 'info' }> = [
  { id: 'harassment', label: 'Harassment', kind: 'risk' },
  { id: 'misinformation', label: 'Misinformation', kind: 'warn' },
  { id: 'spam', label: 'Spam', kind: 'warn' },
  { id: 'off_topic', label: 'Off-topic', kind: 'info' },
];

export const REVIEW_SLA_HOURS = 24;

/** Very light legal-advice heuristic → community redirects, never answers advice. */
const ADVICE_RE = /\b(is it legal|can i sue|my case|should i sign|legal advice|what should i do legally)\b/i;
export function looksLikeLegalAdvice(text: string): boolean {
  return ADVICE_RE.test(text);
}

export interface ComposeDraft {
  channel: string;
  title: string;
  body: string;
}
export function validateCompose(d: ComposeDraft): Record<string, string> {
  const e: Record<string, string> = {};
  if (!d.channel) e.channel = 'Choose a channel.';
  if (!d.title.trim()) e.title = 'Add a question or title.';
  if (!d.body.trim()) e.body = 'Write your post.';
  return e;
}

export interface Channel {
  readonly id: string;
  readonly name: string;
  readonly meta: string;
  readonly active: boolean;
}
export const SAMPLE_CHANNELS: readonly Channel[] = [
  { id: 'con', name: 'Constitutional Law', meta: '142 discussions · 12 today', active: true },
  { id: 'moot', name: 'Moot Court & Advocacy', meta: '88 discussions', active: false },
  { id: 'jud', name: 'Judiciary Prep — Karnataka', meta: '54 discussions', active: true },
];

export const SAMPLE_POSTS: readonly Post[] = [
  { id: 'p1', channel: 'Constitutional Law', author: 'R. Sharma · NLSIU', title: 'Does Puttaswamy bind private platforms?', body: 'Discussing horizontal application of privacy.', replies: 12, moderation: 'visible' },
  { id: 'p2', channel: 'Constitutional Law', author: 'anonymous', title: 'Reported thread pending review', body: 'RAW-ALLEGATION-PLACEHOLDER should never render publicly.', replies: 0, moderation: 'pending_review' },
];

export const MODERATION_OUTCOME_COPY =
  'Reviewed against content policy (IT Rules / UGC). Outcomes: keep, add context, or remove. Reporters notified; raw reports stay private.';
export const ADVICE_REDIRECT_COPY =
  'The community is for study discussion. Requests for legal advice are routed to disclaimers and referral paths, not answered as advice.';
export const REPORT_DPDP = 'Moderation designed to reduce defamation and safety risk';
export const ATTRIBUTION_COPY = 'Your posts are attributable to you; anonymity only where allowed';
