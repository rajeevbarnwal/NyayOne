import { describe, expect, it } from 'vitest';
import {
  isPubliclyVisible,
  publicPosts,
  publicBody,
  looksLikeLegalAdvice,
  validateCompose,
  REPORT_REASONS,
  SAMPLE_POSTS,
  validateReply,
} from './community';

describe('community moderation — not public until moderated (SAATHI-74)', () => {
  it('only moderated-visible posts are public', () => {
    expect(isPubliclyVisible({ moderation: 'visible' })).toBe(true);
    expect(isPubliclyVisible({ moderation: 'pending_review' })).toBe(false);
    expect(isPubliclyVisible({ moderation: 'removed' })).toBe(false);
    expect(publicPosts(SAMPLE_POSTS).map((p) => p.id)).toEqual(['p1']);
  });
  it('redacts raw content of un-moderated posts', () => {
    const pending = SAMPLE_POSTS.find((p) => p.moderation === 'pending_review')!;
    expect(publicBody(pending)).not.toContain('RAW-ALLEGATION');
    expect(publicBody(pending)).toContain('under moderation');
  });
  it('detects legal-advice requests for redirect', () => {
    expect(looksLikeLegalAdvice('Can I sue my landlord?')).toBe(true);
    expect(looksLikeLegalAdvice('Discussing Puttaswamy horizontal application')).toBe(false);
  });
  it('validates compose and exposes report reasons', () => {
    expect(Object.keys(validateCompose({ channel: '', title: '', body: '' })).length).toBe(3);
    expect(Object.keys(validateCompose({ channel: 'Con', title: 'Q', body: 'B' })).length).toBe(0);
    expect(REPORT_REASONS.find((r) => r.id === 'harassment')?.kind).toBe('risk');
  });
  it('validates replies before publishing', () => {
    expect(validateReply('   ')).toContain('Enter a reply');
    expect(validateReply('Can I sue my landlord?')).toContain('legal advice');
    expect(validateReply('The judgment distinguishes the earlier ratio.')).toBeNull();
  });
});
