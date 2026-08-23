import { afterEach, describe, expect, it } from 'vitest';
import {
  clearStudentAuthTransitionNotice,
  consumeStudentAuthTransitionNotice,
  recordStudentAuthTransitionNotice,
} from './studentAuthTransitionNotice';

afterEach(() => clearStudentAuthTransitionNotice());

describe('sanitized auth-transition completion notice', () => {
  it('hands accepted deletion to the public gate exactly once', () => {
    recordStudentAuthTransitionNotice('account_deletion_accepted');
    expect(consumeStudentAuthTransitionNotice('account_deletion_accepted')).toBe(true);
    expect(consumeStudentAuthTransitionNotice('account_deletion_accepted')).toBe(false);
  });

  it('does not let one destination consume a notice owned by another destination', () => {
    recordStudentAuthTransitionNotice('account_deletion_confirmation_invalid');
    expect(consumeStudentAuthTransitionNotice('account_deletion_accepted')).toBe(false);
    expect(consumeStudentAuthTransitionNotice('account_deletion_confirmation_invalid')).toBe(true);
  });

  it('clears an unconsumed notice at the next authority transition', () => {
    recordStudentAuthTransitionNotice('account_deletion_failed');
    clearStudentAuthTransitionNotice();
    expect(consumeStudentAuthTransitionNotice('account_deletion_failed')).toBe(false);
  });
});
