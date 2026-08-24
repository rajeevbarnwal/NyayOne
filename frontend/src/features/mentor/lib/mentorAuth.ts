/**
 * Sprint 1 M-01 is ADMIN-ONLY.
 *
 * A server-issued lawyer/tutor ceremony and verified TutorProfile ownership are
 * a separate deferred security boundary. Until that boundary has its own spec,
 * QA gates and independent review, neither a `lawyer` nor a `tutor` browser
 * identity is promoted into M-01 authority here. In particular, verification
 * state from the lawyer workflow is not tutor authentication.
 *
 * This remains a presentation gate, not server authorization. Every request
 * still uses the HttpOnly session and the server's verdict is final.
 */
import { isOpaqueSubjectId, type AuthState } from '../../../app/authContext';
import type { TutoringActor } from '../../student/lib/tutoringApi';

/** A mixed student/client session may never expose an administrator control. */
const NEVER_ADMIN_SURFACE = new Set(['student', 'client', 'moderator', 'unknown']);

export type MentorAdminActor = TutoringActor & { readonly role: 'admin' };

/**
 * The signed-in administrator, or null when this session may not record
 * completion. `null` means the surface does not mount and no control renders.
 */
export function mentorActorFromAuth(auth: AuthState): MentorAdminActor | null {
  if (!auth.isAuthenticated) return null;
  const userId = (auth.userId ?? '').trim();
  // A masked contact, an email or the "not verified yet" sentinel is not an
  // identity: never fabricate a subject to act with.
  if (!isOpaqueSubjectId(userId, null)) return null;
  if (userId.startsWith('pending_')) return null;
  if (auth.roles.some((role) => NEVER_ADMIN_SURFACE.has(role))) return null;
  if (auth.roles.includes('admin')) return { userId, role: 'admin' };
  return null;
}

/** Guard reason for the mentor routes; null when access is allowed. */
export function mentorRouteDenial(auth: AuthState): string | null {
  if (mentorActorFromAuth(auth)) return null;
  if (!auth.isAuthenticated) return 'Administrator access required';
  return 'This account does not have administrator access to M-01';
}
