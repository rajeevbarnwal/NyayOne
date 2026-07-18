import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../../app/authContext';
import { lawyerRouteDenial } from './lib/caseAuth';

/**
 * Route/feature guard for the lawyer Core workflow (E08–E12).
 *
 * Denies anonymous / student / client / unverified-lawyer / expired-session
 * actors BEFORE any case data or action renders — the children (screen) are not
 * mounted at all when denied, so no workflow data is fetched and no mutation
 * control is exposed. This is a narrowly scoped router guard; it does not touch
 * AppShell or global navigation. The service layer independently re-checks the
 * actor role as defence in depth.
 */
export function LawyerGuard({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const denied = lawyerRouteDenial(auth);
  if (denied) {
    return (
      <section className="st-screen st-stack" data-testid="lawyer-guard-denied" role="alert" aria-live="polite">
        <div className="st-set__head">
          <p className="st-eyebrow">Restricted · Lawyer workspace</p>
          <h1 className="st-h1">Verified lawyer sign-in required</h1>
          <p className="st-metatag" style={{ marginTop: 4 }}>{denied}</p>
        </div>
        <div className="st-panel">
          <p>
            This case workflow is available only to a signed-in, BCI-verified lawyer. No case data or
            actions are shown until verification is confirmed.
          </p>
          <div className="st-actions">
            <Link className="btn btn--primary tap" to="/auth/lawyer">Go to lawyer sign-in &amp; verification</Link>
          </div>
        </div>
      </section>
    );
  }
  return <>{children}</>;
}
