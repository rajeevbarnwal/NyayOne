import type { ComponentType } from 'react';
import { LawyerVerify, StudentVerify, AccountSecurity } from './AuthScreens';

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
  { path: '/auth/lawyer', jira: 'SAATHI-2', Component: LawyerVerify },
  { path: '/auth/student', jira: 'SAATHI-3', Component: StudentVerify },
  { path: '/auth/security', jira: 'SAATHI-4', Component: AccountSecurity },
];
