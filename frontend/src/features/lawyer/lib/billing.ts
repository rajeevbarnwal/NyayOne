/**
 * Advance/fee billing logic (SAATHI-12 · Core E04).
 * Invoice state machine; payment verified SERVER-SIDE with idempotency (client
 * success never trusted); manual transfer needs verification; court-fee vs
 * process fee are typed separately in the ledger. Pure + testable; the payment
 * provider is a stub/adapter boundary (no live Razorpay). GST/rate = CA review.
 */

export type InvoiceStatus = 'pending' | 'paid' | 'failed' | 'cancelled' | 'manual_review';

export type LedgerType = 'court_fee_advance' | 'court_fee_proof' | 'process_fee';

export const LEDGER_LABELS: Record<LedgerType, string> = {
  court_fee_advance: 'Court-fee readiness / advance',
  court_fee_proof: 'Court-fee payment proof',
  process_fee: 'Process fee',
};

export interface Invoice {
  readonly id: string;
  readonly status: InvoiceStatus;
  readonly amount: number;
  readonly ledgerType: LedgerType;
  readonly gstPct: number;
}

let invSeq = 700;
export function newInvoice(amount: number, ledgerType: LedgerType, gstPct = 18): Invoice {
  invSeq += 1;
  return { id: `NYAY-INV-${invSeq}`, status: 'pending', amount, ledgerType, gstPct };
}

/** Payment link may be issued only after an invoice exists (is pending). */
export function canIssuePaymentLink(inv: Invoice | null): boolean {
  return !!inv && inv.status === 'pending';
}

export interface PaymentEvent {
  readonly invoiceId: string;
  readonly providerRef: string;
  /** Server-verified signature flag — client-reported success is ignored. */
  readonly serverVerified: boolean;
}

/**
 * Verify a payment event server-side and return the resulting status.
 * Unverified events never mark paid. Idempotent: replaying the same providerRef
 * for an already-paid invoice is a no-op (returns 'paid').
 */
export function applyPaymentEvent(
  inv: Invoice,
  ev: PaymentEvent,
  seenRefs: Set<string>
): { status: InvoiceStatus; deduped: boolean } {
  if (inv.status === 'paid') return { status: 'paid', deduped: true };
  if (seenRefs.has(ev.providerRef)) return { status: inv.status, deduped: true };
  seenRefs.add(ev.providerRef);
  if (!ev.serverVerified) return { status: 'manual_review', deduped: false };
  return { status: 'paid', deduped: false };
}

/** Manual bank transfer: only an explicit verification marks paid. */
export function applyManualVerification(inv: Invoice, verified: boolean): InvoiceStatus {
  if (inv.status === 'paid') return 'paid';
  return verified ? 'paid' : 'manual_review';
}

/** Receipt acknowledgement is only appropriate once paid. */
export function shouldAcknowledge(status: InvoiceStatus): boolean {
  return status === 'paid';
}

export const GST_REVIEW_NOTICE = 'GST/SAC treatment is pending CA review; rates shown are indicative.';
export const PAYMENT_VERIFY_NOTICE = 'Payments are confirmed only after server-side verification.';
