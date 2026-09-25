export type StudentAuthTransitionNotice =
  | 'account_deletion_accepted'
  | 'account_deletion_confirmation_invalid'
  | 'account_deletion_failed'
  | 'sign_out_failed';

// Sanitized, process-only completion handoff. It carries no actor, request id,
// token, profile field, or workflow authority and is cleared on the next
// lifecycle transition if the destination never consumes it.
let pendingNotice: StudentAuthTransitionNotice | null = null;
const listeners = new Set<() => void>();

export function subscribeStudentAuthTransitionNotice(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function hasStudentLogoutFailure(): boolean {
  return pendingNotice === 'sign_out_failed';
}

function changed(): void { for (const listener of listeners) listener(); }

export function recordStudentAuthTransitionNotice(
  notice: StudentAuthTransitionNotice,
): void {
  pendingNotice = notice;
  changed();
}

export function consumeStudentAuthTransitionNotice(
  expected: StudentAuthTransitionNotice,
): boolean {
  if (pendingNotice !== expected) return false;
  pendingNotice = null;
  changed();
  return true;
}

export function clearStudentAuthTransitionNotice(): void {
  pendingNotice = null;
  changed();
}
