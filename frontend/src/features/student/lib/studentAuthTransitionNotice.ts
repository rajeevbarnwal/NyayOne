export type StudentAuthTransitionNotice =
  | 'account_deletion_accepted'
  | 'account_deletion_confirmation_invalid'
  | 'account_deletion_failed';

// Sanitized, process-only completion handoff. It carries no actor, request id,
// token, profile field, or workflow authority and is cleared on the next
// lifecycle transition if the destination never consumes it.
let pendingNotice: StudentAuthTransitionNotice | null = null;

export function recordStudentAuthTransitionNotice(
  notice: StudentAuthTransitionNotice,
): void {
  pendingNotice = notice;
}

export function consumeStudentAuthTransitionNotice(
  expected: StudentAuthTransitionNotice,
): boolean {
  if (pendingNotice !== expected) return false;
  pendingNotice = null;
  return true;
}

export function clearStudentAuthTransitionNotice(): void {
  pendingNotice = null;
}
