/**
 * Who may act as a MENTOR on the tutoring surface (SAATHI-66, matrix D4;
 * independent-QA defect D2).
 *
 * The server's rule is `attendance.RECORDER_ROLES = ("tutor", "admin")` plus
 * ownership: a tutor may only record on their OWN session, and anyone else is
 * refused with the typed `FORBIDDEN` / `NOT_FOUND` and zero mutation. This
 * module is the CLIENT half of that rule — it decides whether the mentor
 * surface may mount at all, so an unauthorised reader is never offered a
 * control that the server would have to refuse.
 *
 * SECURITY BOUNDARY (stated honestly, same wording as `authContext`): this is
 * client-side derived state used to gate UI and to name the acting subject. It
 * is NOT authorization. The server re-checks role and ownership on every call
 * and its verdict is final; nothing here can grant access to a session.
 *
 * Identity mapping. The app's only authenticated non-student session today is
 * the P0.1 verified-lawyer snapshot, and a Wave 2 tutor profile IS a
 * `lawyer`-role user (`tutor_profiles.user_id`), so a VERIFIED lawyer session
 * acts as `tutor`. An explicit `admin` or `tutor` identity role, when a session
 * carries one, maps straight through — admin first, mirroring the server's
 * `_service_role` precedence. Every other actor (anonymous, student, client,
 * unverified or rejected lawyer, expired session, no opaque subject) is denied.
 */
import { isOpaqueSubjectId, type AuthState } from '../../../app/authContext';
import type { TutoringActor } from '../../student/lib/tutoringApi';

/** Roles that must never be mapped onto a mentor actor, whatever else is claimed. */
const NEVER_MENTOR = new Set(['student', 'client', 'moderator', 'unknown']);

/**
 * The signed-in mentor/administrator, or null when this session may not record
 * completion. `null` means the surface does not mount and no control renders.
 */
export function mentorActorFromAuth(auth: AuthState): TutoringActor | null {
  if (!auth.isAuthenticated) return null;
  const userId = (auth.userId ?? '').trim();
  // A masked contact, an email or the "not verified yet" sentinel is not an
  // identity: never fabricate a subject to act with.
  if (!isOpaqueSubjectId(userId, null)) return null;
  if (userId.startsWith('pending_')) return null;
  if (auth.roles.some((role) => NEVER_MENTOR.has(role))) return null;
  // Most privileged first, exactly like the server's `_service_role`.
  if (auth.roles.includes('admin')) return { userId, role: 'admin' };
  if (auth.roles.includes('tutor')) return { userId, role: 'tutor' };
  // A plain lawyer session is a mentor ONLY once P0.1 verification passed.
  if (auth.roles.includes('lawyer') && auth.lawyerVerification === 'verified') {
    return { userId, role: 'tutor' };
  }
  return null;
}

/** Guard reason for the mentor routes; null when access is allowed. */
export function mentorRouteDenial(auth: AuthState): string | null {
  if (mentorActorFromAuth(auth)) return null;
  if (!auth.isAuthenticated) return 'Mentor sign-in required';
  return 'This account may not record completion for a tutoring session';
}
