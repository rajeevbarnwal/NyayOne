import type { ComponentType } from 'react';
import { CaseIntake, CaseRetainer, CaseWorkspace, CaseAdvance, CaseDocuments } from './CaseScreens';

/**
 * Lawyer / Core civil-litigation routes (Phase 1–2). These sit outside the
 * canonical student S-01..S-99 registry (the Core module has no v3.2 design
 * yet). Each maps a stable /case/* path to its screen.
 */
export interface CaseRoute {
  readonly path: string;
  readonly jira: string;
  readonly Component: ComponentType;
}

export const lawyerRoutes: readonly CaseRoute[] = [
  { path: '/case/intake', jira: 'SAATHI-6', Component: CaseIntake },
  { path: '/case/retainer', jira: 'SAATHI-8', Component: CaseRetainer },
  { path: '/case/new', jira: 'SAATHI-10', Component: CaseWorkspace },
  { path: '/case/advance', jira: 'SAATHI-12', Component: CaseAdvance },
  { path: '/case/documents', jira: 'SAATHI-14', Component: CaseDocuments },
];
