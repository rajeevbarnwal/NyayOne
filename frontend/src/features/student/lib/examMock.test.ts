import { describe, expect, it } from 'vitest';
import {
  evaluateAnswers,
  weakSections,
  revisionQueue,
  SAMPLE_MOCK,
  SAMPLE_RESULT,
  ANALYTICS_SECTIONS,
  AIBE_SUBJECTS,
  WEAK_SECTION_THRESHOLD,
} from './exam';

describe('exam mock/result/analytics/revision (SAATHI-152/157/167)', () => {
  it('scores answers against the sample mock', () => {
    expect(evaluateAnswers({ q12: 1, q13: 1 })).toBe(2);
    expect(evaluateAnswers({ q12: 0, q13: 1 })).toBe(1);
    expect(evaluateAnswers({})).toBe(0);
    expect(SAMPLE_MOCK.every((q) => q.correctIndex < q.options.length)).toBe(true);
  });
  it('flags weak sections below threshold', () => {
    const weak = weakSections(SAMPLE_RESULT.sections);
    expect(weak).toContain('GK');
    expect(weak).not.toContain('Legal Reasoning');
    expect(WEAK_SECTION_THRESHOLD).toBe(70);
  });
  it('orders the revision queue weakest-first', () => {
    const q = revisionQueue(ANALYTICS_SECTIONS);
    expect(q[0]).toBe('GK & Current Affairs');
  });
  it('exposes a source-versioned AIBE subject map', () => {
    expect(AIBE_SUBJECTS.reduce((n, s) => n + s.items, 0)).toBeGreaterThan(0);
    expect(AIBE_SUBJECTS.some((s) => s.subject.includes('Professional Ethics'))).toBe(true);
  });
});
