/**
 * Retainer & fee-agreement logic (SAATHI-8 · Core E02).
 * Load-bearing guardrail: contingent-fee, success-fee, proceeds-sharing, and
 * outcome-linked billing clauses are BLOCKED BY DEFAULT at the generation layer
 * and may only be enabled by a Legal-Counsel-Review-approved firm/jurisdiction
 * config. No success guarantee/outcome metric is ever shown. Pure + testable.
 */

export type FeeClause =
  | 'fixed'
  | 'hourly'
  | 'retainer'
  | 'contingent'
  | 'success'
  | 'proceeds_sharing'
  | 'outcome_linked';

/** Clauses blocked by default unless an LCR-approved config enables them. */
export const RESTRICTED_CLAUSES: readonly FeeClause[] = [
  'contingent',
  'success',
  'proceeds_sharing',
  'outcome_linked',
];

export interface FirmFeeConfig {
  /** Only an LCR-approved config may set this true to allow restricted clauses. */
  readonly lcrApproved: boolean;
  readonly enabledRestrictedClauses: readonly FeeClause[];
  readonly approvedBy?: string;
}

export const DEFAULT_FEE_CONFIG: FirmFeeConfig = { lcrApproved: false, enabledRestrictedClauses: [] };

/** Whether a clause may be generated/previewed/sent under the given config. */
export function isClauseAllowed(clause: FeeClause, cfg: FirmFeeConfig = DEFAULT_FEE_CONFIG): boolean {
  if (!RESTRICTED_CLAUSES.includes(clause)) return true;
  return cfg.lcrApproved && cfg.enabledRestrictedClauses.includes(clause);
}

/** Filter a requested clause set to only those allowed; returns blocked list too. */
export function applyClausePolicy(
  requested: readonly FeeClause[],
  cfg: FirmFeeConfig = DEFAULT_FEE_CONFIG
): { allowed: FeeClause[]; blocked: FeeClause[] } {
  const allowed: FeeClause[] = [];
  const blocked: FeeClause[] = [];
  for (const c of requested) (isClauseAllowed(c, cfg) ? allowed : blocked).push(c);
  return { allowed, blocked };
}

export type SigningStatus = 'draft' | 'awaiting_signature' | 'signed' | 'uploaded';

export interface SignatureRecord {
  readonly fileHash: string;
  readonly signer: string;
  readonly signedAt: string;
  readonly source: 'e-sign' | 'manual_upload';
}

export function makeSignatureRecord(
  fileHash: string,
  signer: string,
  signedAt: string,
  source: 'e-sign' | 'manual_upload'
): SignatureRecord {
  return { fileHash, signer, signedAt, source };
}

/** Case creation unlocks only once the retainer is signed/uploaded. */
export function retainerComplete(status: SigningStatus): boolean {
  return status === 'signed' || status === 'uploaded';
}

export const FEE_CLAUSE_LABELS: Record<FeeClause, string> = {
  fixed: 'Fixed fee',
  hourly: 'Hourly',
  retainer: 'Monthly retainer',
  contingent: 'Contingent fee',
  success: 'Success fee',
  proceeds_sharing: 'Proceeds-sharing',
  outcome_linked: 'Outcome-linked',
};

export const RESTRICTED_CLAUSE_NOTICE =
  'Contingent, success, proceeds-sharing and outcome-linked fees are blocked by default and require Legal Counsel Review before a firm may enable them.';
export const NO_GUARANTEE_NOTICE = 'This generator shows no success guarantee or outcome prediction.';
export const SAMPLE_TEMPLATES = ['Standard engagement (firm-approved)', 'Retainer + hourly (firm-approved)'];
