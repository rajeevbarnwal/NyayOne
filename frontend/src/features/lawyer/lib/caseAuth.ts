/**
 * Bridge between the app AuthContext session and the Core filing workflow's
 * typed actor/role contract (SAATHI-20/22/24/26/28 remediation).
 *
 * The session actor is derived from the authenticated, BCI-verified lawyer
 * workspace claim — never from a caller-supplied raw string. The verified
 * legal-workspace authorisation claim (`auth.filingRole`) maps to the real
 * `FilingActorRole` (lawyer / senior_advocate / firm_partner / associate /
 * clerk / billing_admin); a missing/expired/unverified/wrong-role/no-subject
 * claim yields null (denied) and is NEVER silently upgraded to lawyer. The
 * actor id is always the opaque subject (`auth.userId`).
 */
import { canUseLawyerFeatures, evaluateGuard, type AuthState } from '../../../app/authContext';
import { FILING_ACTOR_ROLES, roleCan, type FilingActor, type FilingActorRole, type FilingAction } from './filingWorkflow';

/** Roles that can never be a legal-workspace actor even if claimed. */
const NON_WORKSPACE_ROLES = new Set(['student', 'client', 'unknown']);

/**
 * The authenticated session actor mapped to its real workspace role, or null
 * when the session is not a verified workspace member with a known functional
 * role. The role comes from the verified `filingRole` claim, defaulting to base
 * `lawyer` only when the claim is absent (a plain verified lawyer); an unknown
 * or non-workspace claim is denied.
 */
export function filingActorFromAuth(auth: AuthState): FilingActor | null {
  if (!canUseLawyerFeatures(auth)) return null; // membership + P0.1 verified
  const role = (auth.filingRole ?? 'lawyer').trim();
  if (!(FILING_ACTOR_ROLES as readonly string[]).includes(role)) return null; // unknown claim → deny
  if (NON_WORKSPACE_ROLES.has(role)) return null; // never a workspace actor
  const id = (auth.userId ?? '').trim();
  if (!id) return null; // opaque subject required
  return { id, role: role as FilingActorRole };
}

/** Legacy alias — prefer filingActorFromAuth. */
export const lawyerActorFromAuth = filingActorFromAuth;

/** Guard reason string for the lawyer Core routes; null when access is allowed. */
export function lawyerRouteDenial(auth: AuthState): string | null {
  return evaluateGuard(auth, 'lawyer-features');
}

/**
 * Whether the verified session actor may enter a route for a given stage.
 * A route with `stageActions` renders only when the actor holds at least one of
 * those actions (least-privilege at the route); each mutation still enforces its
 * own action. Routes without `stageActions` (E01–E07) require only verified
 * workspace membership.
 */
export function canEnterStage(auth: AuthState, stageActions?: readonly FilingAction[]): boolean {
  const actor = filingActorFromAuth(auth);
  if (!actor) return false;
  if (!stageActions || stageActions.length === 0) return true;
  return stageActions.some((a) => roleCan(actor.role, a));
}
