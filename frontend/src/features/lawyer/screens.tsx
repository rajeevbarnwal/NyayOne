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

// The ENTIRE lawyer module requires a verified-lawyer session. Every /case/*
// route is behind the shared LawyerGuard (E01–E12), so anonymous / student /
// client / unverified / rejected / expired actors are denied before any case
// data or mutation control mounts.
export const lawyerRoutes: readonly CaseRoute[] = [
  { path: '/case/intake', jira: 'SAATHI-6', Component: CaseIntake, guarded: true },
  { path: '/case/retainer', jira: 'SAATHI-8', Component: CaseRetainer, guarded: true },
  { path: '/case/new', jira: 'SAATHI-10', Component: CaseWorkspace, guarded: true },
  { path: '/case/advance', jira: 'SAATHI-12', Component: CaseAdvance, guarded: true },
  { path: '/case/documents', jira: 'SAATHI-14', Component: CaseDocuments, guarded: true },
  { path: '/case/draft', jira: 'SAATHI-16', Component: CaseDraft, guarded: true },
  { path: '/case/review', jira: 'SAATHI-18', Component: CaseReview, guarded: true },
  { path: '/case/finalize', jira: 'SAATHI-20', Component: CaseFinalize, guarded: true },
  { path: '/case/filing', jira: 'SAATHI-22', Component: CaseFiling, guarded: true },
  { path: '/case/diary', jira: 'SAATHI-24', Component: CaseDiary, guarded: true },
  { path: '/case/fees', jira: 'SAATHI-26', Component: CaseFees, guarded: true },
  { path: '/case/tracking', jira: 'SAATHI-28', Component: CaseTracking, guarded: true },
];
