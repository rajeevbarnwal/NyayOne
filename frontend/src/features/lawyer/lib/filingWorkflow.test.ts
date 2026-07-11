import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import { DraftWorkspaceService } from './draftWorkspace';
import {
  FilingWorkflowService, latestBundle, canProceedToFiling, checklistComplete, bundleHash,
  CHECKLIST_KEYS, applyFeePayment, applyManualFeeVerification, allocateAdvance, addFeeLine, emptyLedger,
  cnrFormatValid, trackingStale, GST_ENABLED, ECOURTS_POLLING_ENABLED, MILESTONE_CASE_FILED_PCT,
  diaryFormatValid, type FeeLine,
} from './filingWorkflow';

const t = (n: number) => `2026-07-11T0${n}:00:00.000Z`;
const CASE = 'LS-CASE-2026-014';

function setup() {
  const store = new InMemoryKvStore();
  const drafts = new DraftWorkspaceService(store);
  const filing = new FilingWorkflowService(store, drafts);
  const ws = drafts.create(CASE, 'Acme v. Sunrise');
  drafts.setCurrent(ws.workspaceId);
  // seed an approved E06/E07 draft version (the real prerequisite)
  drafts.addVersion(ws.workspaceId, { authorId: 'assoc:1', createdAt: t(1), changeNote: 'draft', body: 'A', aiGenerated: true });
  drafts.approve(ws.workspaceId, drafts.latestVersion(ws.workspaceId)!.id, 'lawyer:rao', t(1));
  return { store, drafts, filing, id: ws.workspaceId, approvedId: drafts.latestApprovedVersion(ws.workspaceId)!.id };
}
function completeAllChecklist(filing: FilingWorkflowService, id: string) {
  for (const k of CHECKLIST_KEYS) filing.setChecklist(id, k, true, t(2));
}

describe('E08 vet & lock final filing bundle (SAATHI-20)', () => {
  it('requires a real lawyer-approved E06/E07 version', () => {
    const store = new InMemoryKvStore();
    const drafts = new DraftWorkspaceService(store);
    const filing = new FilingWorkflowService(store, drafts);
    const ws = drafts.create(CASE, 'X');
    drafts.addVersion(ws.workspaceId, { authorId: 'a', createdAt: t(1), changeNote: 'd', body: 'A', aiGenerated: true });
    expect(filing.initBundle(ws.workspaceId, t(1))).toBeNull(); // not approved yet
    drafts.approve(ws.workspaceId, drafts.latestVersion(ws.workspaceId)!.id, 'lawyer', t(1));
    expect(filing.initBundle(ws.workspaceId, t(1))).not.toBeNull();
  });

  it('gates lock on a complete checklist and makes the bundle immutable', () => {
    const { filing, id, approvedId } = setup();
    let fw = filing.initBundle(id, t(1))!;
    expect(latestBundle(fw)!.sourceDraftVersionId).toBe(approvedId);
    // lock refused while incomplete
    fw = filing.lockBundle(id, 'lawyer:rao', t(2));
    expect(latestBundle(fw)!.locked).toBe(false);
    completeAllChecklist(filing, id);
    fw = filing.lockBundle(id, 'lawyer:rao', t(2));
    const b = latestBundle(fw)!;
    expect(b.locked).toBe(true);
    expect(b.hash).toBeTruthy();
    expect(checklistComplete(b)).toBe(true);
    expect(canProceedToFiling(fw)).toBe(true);
  });

  it('locked bundle is read-only; editing creates a new unlocked version; hash stable', () => {
    const { filing, id } = setup();
    filing.initBundle(id, t(1));
    completeAllChecklist(filing, id);
    let fw = filing.lockBundle(id, 'lawyer:rao', t(2));
    const locked = latestBundle(fw)!;
    // setChecklist is a no-op on a locked bundle
    fw = filing.setChecklist(id, 'metadata', false, t(2));
    expect(latestBundle(fw)!.checklist.metadata).toBe(true);
    // hash is deterministic
    expect(bundleHash(locked)).toBe(locked.hash);
    // edit after lock → new v2 unlocked, filing re-blocked
    fw = filing.editAfterLock(id, t(3));
    expect(latestBundle(fw)!.versionNo).toBe(2);
    expect(latestBundle(fw)!.locked).toBe(false);
    expect(canProceedToFiling(fw)).toBe(false);
  });
});

describe('E09 record court filing (SAATHI-22)', () => {
  function filedSetup() {
    const s = setup();
    s.filing.initBundle(s.id, t(1));
    completeAllChecklist(s.filing, s.id);
    s.filing.lockBundle(s.id, 'lawyer:rao', t(2));
    return s;
  }
  it('requires a locked bundle before filing can be recorded', () => {
    const { filing, id } = setup();
    filing.initBundle(id, t(1)); // not locked
    expect(filing.recordFiling(id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: 'proof://x' }, t(3))).toBeNull();
  });
  it('records filing, triggers 25% milestone, keeps invoice a draft until approval', () => {
    const { filing, id } = filedSetup();
    let fw = filing.recordFiling(id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: 'ok', proofRef: 'proof://abc' }, t(3))!;
    expect(fw.filing!.milestoneReached).toBe(true);
    expect(fw.filing!.milestonePct).toBe(MILESTONE_CASE_FILED_PCT);
    expect(fw.filing!.invoiceStatus).toBe('draft');
    expect(fw.timeline.some((e) => e.stage === 'E09')).toBe(true);
    fw = filing.approveFilingInvoice(id, 'billing', t(3));
    expect(fw.filing!.invoiceStatus).toBe('approved');
  });
  it('corrections append to history', () => {
    const { filing, id } = filedSetup();
    filing.recordFiling(id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'physical', filedBy: 'clerk', notes: '', proofRef: 'p://1' }, t(3));
    const fw = filing.correctFiling(id, 'court', 'District Court', 'lawyer', t(4));
    expect(fw.filing!.court).toBe('District Court');
    expect(fw.filing!.corrections[0].old).toBe('City Civil');
  });
});

describe('E10 diary number (SAATHI-24)', () => {
  function filedSetup() {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, 'lawyer:rao', t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: 'p://1' }, t(3));
    return s;
  }
  it('requires a filing and binds the diary to it; manual entry is not officially validated', () => {
    const { filing, id } = setup();
    expect(filing.captureDiary(id === '' ? '' : id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source: 'manual', receivedDate: t(4), acknowledgementRef: 'ack://1' }, t(4))).toBeNull(); // no filing yet
    const f = filedSetup();
    const fw = f.filing.captureDiary(f.id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source: 'manual', receivedDate: t(4), acknowledgementRef: 'ack://1' }, t(4))!;
    expect(fw.diary!.boundFilingId).toBe(fw.filing!.id);
    expect(fw.diary!.officiallyValidated).toBe(false);
  });
  it('authorised source marks officially validated; correction is append-only', () => {
    const { filing, id } = filedSetup();
    filing.captureDiary(id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source: 'authorised_source', receivedDate: t(4), acknowledgementRef: 'ack://1' }, t(4));
    const fw = filing.correctDiary(id, 'D/2/2026', 'typo', 'lawyer', t(5));
    expect(fw.diary!.officiallyValidated).toBe(true);
    expect(fw.diary!.number).toBe('D/2/2026');
    expect(fw.diary!.history[0].old).toBe('D/1/2026');
    expect(fw.diary!.history[0].reason).toBe('typo');
  });
  it('format validation only applies where a court rule is configured', () => {
    expect(diaryFormatValid('UnconfiguredCourt', 'anything')).toBe(true);
  });
});

describe('E11 fee ledger (SAATHI-26)', () => {
  const line = (id: string, category: FeeLine['category'], amount = 1000): Omit<FeeLine, 'status' | 'allocations'> =>
    ({ id, category, amount, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef: null });
  it('keeps categories distinct and gates paid on a receipt + server verification', () => {
    let ledger = emptyLedger(5000);
    ledger = addFeeLine(ledger, line('L1', 'court_fee'));
    ledger = addFeeLine(ledger, line('L2', 'process_fee'));
    expect(ledger.lines.map((l) => l.category)).toEqual(['court_fee', 'process_fee']);
    // unverified → manual_review
    let r = applyFeePayment(ledger, { lineId: 'L1', providerRef: 'r1', serverVerified: false, receiptRef: 'rc://1' });
    expect(r.ledger.lines[0].status).toBe('manual_review');
    // verified + receipt → paid
    r = applyFeePayment(r.ledger, { lineId: 'L1', providerRef: 'r2', serverVerified: true, receiptRef: 'rc://1' });
    expect(r.ledger.lines[0].status).toBe('paid');
    // verified but NO receipt → not paid
    const noRc = applyFeePayment(ledger, { lineId: 'L2', providerRef: 'r3', serverVerified: true });
    expect(noRc.ledger.lines[1].status).toBe('manual_review');
  });
  it('is idempotent on duplicate provider refs', () => {
    const ledger = addFeeLine(emptyLedger(5000), line('L1', 'court_fee'));
    const first = applyFeePayment(ledger, { lineId: 'L1', providerRef: 'dup', serverVerified: true, receiptRef: 'rc://1' });
    expect(first.deduped).toBe(false);
    const second = applyFeePayment(first.ledger, { lineId: 'L1', providerRef: 'dup', serverVerified: true, receiptRef: 'rc://1' });
    expect(second.deduped).toBe(true);
  });
  it('manual verification requires a receipt; advance allocation prevents double/negative', () => {
    let ledger = addFeeLine(emptyLedger(1500), { ...line('L1', 'court_fee', 1000), receiptRef: 'rc://1' });
    ledger = applyManualFeeVerification(ledger, 'L1', true);
    expect(ledger.lines[0].status).toBe('paid');
    // allocate 800 ok; a further 800 would exceed the 1000 line → refused
    ledger = allocateAdvance(ledger, 'L1', 800);
    expect(ledger.advanceBalance).toBe(700);
    const over = allocateAdvance(ledger, 'L1', 800);
    expect(over).toBe(ledger); // no double/over allocation
    // cannot exceed advance balance
    const neg = allocateAdvance(ledger, 'L1', 100000);
    expect(neg).toBe(ledger);
  });
  it('keeps GST disabled by default pending LCR-007/008', () => {
    expect(GST_ENABLED).toBe(false);
  });
});

describe('E12 CNR & tracking (SAATHI-28)', () => {
  function diarySetup() {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, 'lawyer:rao', t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: 'p://1' }, t(3));
    return s;
  }
  it('validates CNR format without assuming one universal format', () => {
    expect(cnrFormatValid('KABC010001232026')).toBe(true);
    expect(cnrFormatValid('nope')).toBe(false);
    expect(cnrFormatValid('')).toBe(false);
  });
  it('requires filing/diary; tracking stays off until validated + activated; polling disabled', () => {
    const { filing, id } = setup();
    expect(filing.captureCnr(id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026', source: 'manual', sourceType: 'manual' }, t(5))).toBeNull(); // no filing/diary
    const d = diarySetup();
    let fw = d.filing.captureCnr(d.id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026', source: 'manual entry', sourceType: 'manual' }, t(5))!;
    expect(fw.tracking!.validated).toBe(true);
    expect(fw.tracking!.trackingEnabled).toBe(false); // off until activation
    expect(fw.tracking!.courtVerified).toBe(false); // manual is not court-verified
    fw = d.filing.activateTracking(d.id, true, t(6));
    expect(fw.tracking!.trackingEnabled).toBe(true);
    expect(ECOURTS_POLLING_ENABLED).toBe(false); // polling disabled pending LCR-009
  });
  it('does not activate tracking when the identifier is invalid', () => {
    const d = diarySetup();
    d.filing.captureCnr(d.id, { cnr: 'bad', caseNumber: 'x', source: 'manual', sourceType: 'manual' }, t(5));
    const fw = d.filing.activateTracking(d.id, false, t(6));
    expect(fw.tracking!.trackingEnabled).toBe(false);
  });
  it('detects stale tracking data', () => {
    const base = { cnr: 'x', caseNumber: 'y', source: 's', sourceType: 'manual' as const, capturedAt: t(1), validated: true, trackingEnabled: true, courtVerified: false, alertsConsent: false, alertsEnabled: false };
    expect(trackingStale({ ...base, checkedAt: null }, Date.parse(t(2)))).toBe(true);
    expect(trackingStale({ ...base, checkedAt: t(2) }, Date.parse(t(2)) + 1000)).toBe(false);
  });
});

describe('E08→E12 end-to-end chain + persistence (SAATHI-20/22/24/26/28)', () => {
  it('runs the full sequential workflow and restores across reload', () => {
    const { store, filing, id } = setup();
    filing.initBundle(id, t(1));
    completeAllChecklist(filing, id);
    filing.lockBundle(id, 'lawyer:rao', t(2));
    filing.recordFiling(id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: 'p://1' }, t(3));
    filing.captureDiary(id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source: 'manual', receivedDate: t(4), acknowledgementRef: 'ack://1' }, t(4));
    filing.addFee(id, { id: 'L1', category: 'court_fee', amount: 1000, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef: 'rc://1' }, t(5));
    filing.payFee(id, { lineId: 'L1', providerRef: 'r1', serverVerified: true, receiptRef: 'rc://1' }, t(5));
    filing.captureCnr(id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026', source: 'manual', sourceType: 'manual' }, t(6));
    filing.activateTracking(id, true, t(6));

    // reload: fresh services on the same store
    const drafts2 = new DraftWorkspaceService(store);
    const filing2 = new FilingWorkflowService(store, drafts2);
    const fw = filing2.get(id)!;
    expect(latestBundle(fw)!.locked).toBe(true);
    expect(fw.filing!.milestoneReached).toBe(true);
    expect(fw.diary!.boundFilingId).toBe(fw.filing!.id);
    expect(fw.fees.lines[0].status).toBe('paid');
    expect(fw.tracking!.trackingEnabled).toBe(true);
    // audit accumulated across every stage
    expect(fw.audit.length).toBeGreaterThan(8);
    expect(fw.timeline.map((e) => e.stage)).toEqual(['E08', 'E09', 'E10', 'E12']);
  });
});
