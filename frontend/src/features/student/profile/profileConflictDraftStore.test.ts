import { afterEach, describe, expect, it } from 'vitest';
import {
  clearProfileConflictDraft,
  preserveProfileConflictDraft,
  takeProfileConflictDraft,
} from './profileConflictDraftStore';

afterEach(() => {
  clearProfileConflictDraft();
});

describe('process-memory profile conflict draft handoff', () => {
  it('retains an academic draft until its own section can restore it exactly once', () => {
    const draft = {
      section: 'academic' as const,
      value: {
        college: 'NLSIU',
        yearOfStudy: '3',
        enrolmentNumber: 'KA/1234/2023',
        institutionalEmail: 'student@nls.ac.in',
        barEnrolmentNumber: null,
      },
    };
    preserveProfileConflictDraft(draft);

    expect(takeProfileConflictDraft('interests')).toBeNull();
    expect(takeProfileConflictDraft('academic')).toEqual(draft);
    expect(takeProfileConflictDraft('academic')).toBeNull();
  });

  it('retains an interests draft without browser storage and clears on lifecycle teardown', () => {
    preserveProfileConflictDraft({
      section: 'interests',
      value: { interests: ['Privacy'], goals: ['Policy'] },
    });

    clearProfileConflictDraft();

    expect(takeProfileConflictDraft('interests')).toBeNull();
  });
});
