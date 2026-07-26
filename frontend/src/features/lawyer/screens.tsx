import type { ComponentType } from 'react';
import {
  CaseIntake, CaseRetainer, CaseWorkspace, CaseAdvance, CaseDocuments, CaseDraft, CaseReview,
  CaseFinalize, CaseFiling, CaseDiary, CaseFees, CaseTracking,
} from './CaseScreens';
import type { FilingAction } from './lib/filingWorkflow';

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
  /**
   * Least-privilege stage actions (E08–E12). The verified actor must hold at
   * least one to enter; each mutation still enforces its own action. Routes
   * without this (E01–E07) require only verified workspace membership.
   */
  readonly stage?: readonly FilingAction[];
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
  { path: '/case/finalize', jira: 'SAATHI-20', Component: CaseFinalize, guarded: true, stage: ['checklist', 'lock', 'edit_after_lock', 'notify_config'] },
  { path: '/case/filing', jira: 'SAATHI-22', Component: CaseFiling, guarded: true, stage: ['filing_record', 'filing_proof', 'invoice_approve', 'filing_correct'] },
  { path: '/case/diary', jira: 'SAATHI-24', Component: CaseDiary, guarded: true, stage: ['diary_capture', 'diary_ack', 'diary_correct', 'diary_notify'] },
  { path: '/case/fees', jira: 'SAATHI-26', Component: CaseFees, guarded: true, stage: ['fee_add', 'fee_pay', 'fee_allocate', 'fee_receipt'] },
  { path: '/case/tracking', jira: 'SAATHI-28', Component: CaseTracking, guarded: true, stage: ['cnr_capture', 'tracking_activate', 'identifier_fetch', 'identifier_manual'] },
];
