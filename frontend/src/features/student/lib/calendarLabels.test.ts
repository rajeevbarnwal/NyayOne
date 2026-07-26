/**
 * SAATHI-286 / Product decision 12314 — S-91 manual event type labels.
 * Asserts BOTH the stored enum values (lowercase, persistence contract) and the
 * exact Product-approved accessible names (real text, not CSS capitalization).
 */
import { describe, it, expect } from 'vitest';
import { PERSONAL_EVENT_TYPES, PERSONAL_EVENT_TYPE_LABELS } from './calendar';

describe('S-91 canonical event type labels (SAATHI-286 / Product 12314)', () => {
  it('keeps lowercase enum values for the persistence contract', () => {
    expect([...PERSONAL_EVENT_TYPES]).toEqual(['study', 'deadline', 'meeting', 'reminder', 'other']);
  });

  it('exposes the exact Product-approved accessible names', () => {
    expect(PERSONAL_EVENT_TYPE_LABELS).toEqual({
      study: 'Study', deadline: 'Deadline', meeting: 'Meeting', reminder: 'Reminder', other: 'Other',
    });
    for (const t of PERSONAL_EVENT_TYPES) {
      expect(PERSONAL_EVENT_TYPE_LABELS[t]).toBe(t.charAt(0).toUpperCase() + t.slice(1));
    }
  });

  it('excludes Exam and Moot — those are source classifications, not manual types', () => {
    expect(Object.values(PERSONAL_EVENT_TYPE_LABELS)).not.toContain('Exam');
    expect(Object.values(PERSONAL_EVENT_TYPE_LABELS)).not.toContain('Moot');
  });
});
