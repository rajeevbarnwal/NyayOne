import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../app/authContext';
import { filingActorFromAuth, canEnterStage } from './lib/caseAuth';
import type { FilingAction } from './lib/filingWorkflow';

/**
 * Route/feature guard for the lawyer Core workflow (E01–E12).
 *
 * Denies anonymous / student / client / unverified-lawyer / rejected /
 * expired-session actors BEFORE any case data or action renders — children are
 * not mounted when denied. When a `stage` action set is supplied (E08–E12), the
 * verified actor must hold at least one action for that stage (least-privilege
 * routing: a clerk cannot enter E08 finalize, a billing admin cannot enter the
 * diary/tracking stages, etc.). The service layer independently re-checks each
 * mutation. This is a narrowly scoped router guard; it does not touch AppShell.
 */
export function LawyerGuard({ stage, children }: { stage?: readonly FilingAction[]; children: ReactNode }) {
  const auth = useAuth();
  const actor = filingActorFromAuth(auth);
  if (!actor) {
    return (
      <section className="st-screen st-stack" data-testid="lawyer-guard-denied" role="alert" aria-live="polite">
        <div className="st-set__head">
          <p className="st-eyebrow">Restricted · Lawyer workspace</p>
          <h1 className="st-h1">Verified lawyer sign-in required</h1>
          <p className="st-metatag" style={{ marginTop: 4 }}>Lawyer features are locked until BCI-verified sign-in is complete.</p>
        </div>
        <div className="st-panel">
          <p>
            This case workflow is available only to a signed-in, BCI-verified lawyer workspace member. No case
            data or actions are shown until verification is confirmed.
          </p>
          <div className="st-actions">
            <Link className="btn btn--primary tap" to="/auth/lawyer">Go to lawyer sign-in &amp; verification</Link>
          </div>
        </div>
      </section>
    );
  }
  if (!canEnterStage(auth, stage)) {
    return (
      <section className="st-screen st-stack" data-testid="lawyer-guard-insufficient" role="alert" aria-live="polite">
        <div className="st-set__head">
          <p className="st-eyebrow">Restricted · Insufficient privilege</p>
          <h1 className="st-h1">This stage is not permitted for your role</h1>
          <p className="st-metatag" style={{ marginTop: 4 }}>Your workspace role does not include any action for this case stage.</p>
        </div>
        <div className="st-panel">
          <p>Your verified role has no permitted action at this stage, so no data or controls are shown. Contact a supervising lawyer if you believe this is incorrect.</p>
          <div className="st-actions"><Link className="btn btn--primary tap" to="/case/intake">Back to case intake</Link></div>
        </div>
      </section>
    );
  }
  return <>{children}</>;
}
