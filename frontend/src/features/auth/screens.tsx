import type { ComponentType } from 'react';
import { Link } from 'react-router-dom';

/**
 * The former /auth/* workbenches were interactive design prototypes backed by
 * client-owned OTP/session state. They are deliberately not imported into the
 * production route graph. Canonical student authentication lives under S-03+
 * and is backed only by the HttpOnly server flow.
 */
export function ProductionAuthBoundary() {
  return (
    <section className="st-screen st-stack" data-screen="AUTH-FAIL-CLOSED">
      <div className="st-set__head">
        <p className="st-eyebrow">Authentication</p>
        <h1 className="st-h1">This legacy sign-in route is unavailable</h1>
        <p className="st-item__meta">
          No local OTP or browser-created session can unlock an account.
        </p>
      </div>
      <div className="st-actions">
        <Link className="btn btn--primary tap" to="/s-03">Use secure student sign-in</Link>
      </div>
    </section>
  );
}

/**
 * Phase 0 authentication routes (P0.1–P0.3). These sit outside the student
 * S-01..S-99 registry and the lawyer /case/* routes. Each maps a stable
 * /auth/* path to its screen and its Jira story.
 */
export interface AuthRoute {
  readonly path: string;
  readonly jira: string;
  readonly Component: ComponentType;
}

export const authRoutes: readonly AuthRoute[] = [
  { path: '/auth/lawyer', jira: 'SAATHI-2', Component: ProductionAuthBoundary },
  { path: '/auth/student', jira: 'SAATHI-3', Component: ProductionAuthBoundary },
  { path: '/auth/security', jira: 'SAATHI-4', Component: ProductionAuthBoundary },
];
