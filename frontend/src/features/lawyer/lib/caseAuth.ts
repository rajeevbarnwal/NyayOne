/**
 * Bridge between the app AuthContext session and the Core filing workflow's
 * typed actor/role contract (SAATHI-20/22/24/26/28 remediation).
 *
 * The session actor is derived from the authenticated, BCI-verified lawyer
 * identity — never from a caller-supplied raw string. Only a verified lawyer
 * yields a finalize-capable actor; everyone else yields null (denied).
 */
import { canUseLawyerFeatures, evaluateGuard, type AuthState } from '../../../app/authContext';
import type { FilingActor } from './filingWorkflow';

/** The authenticated session actor, or null when the session is not a verified lawyer. */
export function lawyerActorFromAuth(auth: AuthState): FilingActor | null {
  if (!canUseLawyerFeatures(auth)) return null;
  return { id: auth.userId ?? 'lawyer', role: 'lawyer' };
}

/** Guard reason string for the lawyer Core routes; null when access is allowed. */
export function lawyerRouteDenial(auth: AuthState): string | null {
  return evaluateGuard(auth, 'lawyer-features');
}
