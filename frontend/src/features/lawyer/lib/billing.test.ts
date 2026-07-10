import { describe, expect, it } from 'vitest';
import {
  newInvoice,
  canIssuePaymentLink,
  applyPaymentEvent,
  applyManualVerification,
  shouldAcknowledge,
  LEDGER_LABELS,
} from './billing';

describe('advance billing state machine (SAATHI-12 / E04)', () => {
  it('issues a payment link only after an invoice exists (pending)', () => {
    expect(canIssuePaymentLink(null)).toBe(false);
    const inv = newInvoice(5000, 'court_fee_advance');
    expect(inv.status).toBe('pending');
    expect(canIssuePaymentLink(inv)).toBe(true);
  });

  it('marks paid only on server-verified events; unverified → manual_review', () => {
    const inv = newInvoice(5000, 'court_fee_advance');
    const seen = new Set<string>();
    expect(applyPaymentEvent(inv, { invoiceId: inv.id, providerRef: 'r1', serverVerified: false }, seen).status).toBe('manual_review');
    const seen2 = new Set<string>();
    expect(applyPaymentEvent(inv, { invoiceId: inv.id, providerRef: 'r2', serverVerified: true }, seen2).status).toBe('paid');
  });

  it('is idempotent on duplicate provider refs and paid invoices', () => {
    const inv = newInvoice(5000, 'process_fee');
    const seen = new Set<string>();
    const first = applyPaymentEvent(inv, { invoiceId: inv.id, providerRef: 'dup', serverVerified: true }, seen);
    expect(first.deduped).toBe(false);
    const second = applyPaymentEvent(inv, { invoiceId: inv.id, providerRef: 'dup', serverVerified: true }, seen);
    expect(second.deduped).toBe(true);
    const paid = { ...inv, status: 'paid' as const };
    expect(applyPaymentEvent(paid, { invoiceId: inv.id, providerRef: 'x', serverVerified: true }, new Set()).deduped).toBe(true);
  });

  it('manual verification and receipt gating', () => {
    const inv = newInvoice(1000, 'court_fee_advance');
    expect(applyManualVerification(inv, false)).toBe('manual_review');
    expect(applyManualVerification(inv, true)).toBe('paid');
    expect(shouldAcknowledge('paid')).toBe(true);
    expect(shouldAcknowledge('pending')).toBe(false);
  });

  it('types ledger entries separately', () => {
    expect(LEDGER_LABELS.court_fee_advance).not.toBe(LEDGER_LABELS.process_fee);
    expect(LEDGER_LABELS.court_fee_proof).toContain('proof');
  });
});
