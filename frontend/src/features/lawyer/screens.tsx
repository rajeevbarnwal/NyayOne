import type { ComponentType } from 'react';
import {
  CaseIntake, CaseRetainer, CaseWorkspace, CaseAdvance, CaseDocuments, CaseDraft, CaseReview,
  CaseFinalize, CaseFiling, CaseDiary, CaseFees, CaseTracking,
} from './CaseScreens';

/**
 * Lawyer / Core civil-litigation routes (Phase 1–2). These sit outside the
 * canonical student S-01..S-99 registry (the Core module has no v3.2 design
 * yet). Each maps a stable /case/* path to its screen.
 */
export interface CaseRoute {
  readonly path: string;
  readonly jira: string;
  readonly Component: ComponentType;
  /** When true, the route is wrapped in the verified-lawyer LawyerGuard. */
  readonly guarded?: boolean;
}

export const lawyerRoutes: readonly CaseRoute[] = [
  { path: '/case/intake', jira: 'SAATHI-6', Component: CaseIntake },
  { path: '/case/retainer', jira: 'SAATHI-8', Component: CaseRetainer },
  { path: '/case/new', jira: 'SAATHI-10', Component: CaseWorkspace },
  { path: '/case/advance', jira: 'SAATHI-12', Component: CaseAdvance },
  { path: '/case/documents', jira: 'SAATHI-14', Component: CaseDocuments },
  { path: '/case/draft', jira: 'SAATHI-16', Component: CaseDraft },
  { path: '/case/review', jira: 'SAATHI-18', Component: CaseReview },
  { path: '/case/finalize', jira: 'SAATHI-20', Component: CaseFinalize, guarded: true },
  { path: '/case/filing', jira: 'SAATHI-22', Component: CaseFiling, guarded: true },
  { path: '/case/diary', jira: 'SAATHI-24', Component: CaseDiary, guarded: true },
  { path: '/case/fees', jira: 'SAATHI-26', Component: CaseFees, guarded: true },
  { path: '/case/tracking', jira: 'SAATHI-28', Component: CaseTracking, guarded: true },
];
