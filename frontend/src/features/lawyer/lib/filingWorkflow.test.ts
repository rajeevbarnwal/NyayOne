import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import { DraftWorkspaceService } from './draftWorkspace';
import {
  FilingWorkflowService, latestBundle, canProceedToFiling, checklistComplete, bundleHash,
  CHECKLIST_KEYS, applyFeePayment, applyManualFeeVerification, allocateAdvance, addFeeLine, emptyLedger,
  cnrFormatValid, trackingStale, GST_ENABLED, ECOURTS_POLLING_ENABLED, MILESTONE_CASE_FILED_PCT,
  diaryFormatValid, type FeeLine,
  canFinalize, authorize, roleCan, validateUpload, statementLineStatus, buildClientStatement,
  ALL_FILING_ACTIONS, FILING_PERMISSIONS,
  attemptAutomatedIdentifierFetch, MAX_UPLOAD_BYTES, type UploadInput, type FilingActor, type FilingAction, type FilingActorRole, type FeeLedger,
} from './filingWorkflow';

const validPdf: UploadInput = { filename: 'proof.pdf', mime: 'application/pdf', size: 1024, present: true };
const LAWYER: FilingActor = { id: 'rao', role: 'lawyer' };
const BILLING: FilingActor = { id: 'bill-1', role: 'billing_admin' };
const CLERK: FilingActor = { id: 'clerk-1', role: 'clerk' };

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
  drafts.approve(ws.workspaceId, drafts.latestVersion(ws.workspaceId)!.id, 'approver', t(1));
  return { store, drafts, filing, id: ws.workspaceId, approvedId: drafts.latestApprovedVersion(ws.workspaceId)!.id };
}
function completeAllChecklist(filing: FilingWorkflowService, id: string) {
  for (const k of CHECKLIST_KEYS) filing.setChecklist(id, k, true, t(2), LAWYER);
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
    fw = filing.lockBundle(id, LAWYER, t(2));
    expect(latestBundle(fw)!.locked).toBe(false);
    completeAllChecklist(filing, id);
    fw = filing.lockBundle(id, LAWYER, t(2));
    const b = latestBundle(fw)!;
    expect(b.locked).toBe(true);
    expect(b.hash).toBeTruthy();
    expect(checklistComplete(b)).toBe(true);
    expect(canProceedToFiling(fw)).toBe(true);
  });

  it('E08 (SAATHI-20/433/434/435): fee-readiness and client-approval are required checklist dimensions', () => {
    // The two Jira dimensions are part of the canonical checklist contract.
    expect(CHECKLIST_KEYS).toContain('fee_readiness');
    expect(CHECKLIST_KEYS).toContain('client_approval');
    const { filing, id } = setup();
    filing.initBundle(id, t(1));
    // Complete every document dimension but leave fee_readiness + client_approval off.
    for (const k of CHECKLIST_KEYS) {
      if (k === 'fee_readiness' || k === 'client_approval') continue;
      filing.setChecklist(id, k, true, t(2), LAWYER);
    }
    let fw = filing.lockBundle(id, LAWYER, t(2));
    expect(latestBundle(fw)!.locked).toBe(false); // lock refused: readiness dims missing
    filing.setChecklist(id, 'fee_readiness', true, t(2), LAWYER);
    fw = filing.lockBundle(id, LAWYER, t(2));
    expect(latestBundle(fw)!.locked).toBe(false); // still refused: client_approval missing
    filing.setChecklist(id, 'client_approval', true, t(2), LAWYER);
    fw = filing.lockBundle(id, LAWYER, t(2));
    expect(latestBundle(fw)!.locked).toBe(true); // all required dimensions satisfied
  });

  it('locked bundle is read-only; editing creates a new unlocked version; hash stable', () => {
    const { filing, id } = setup();
    filing.initBundle(id, t(1));
    completeAllChecklist(filing, id);
    let fw = filing.lockBundle(id, LAWYER, t(2));
    const locked = latestBundle(fw)!;
    // setChecklist is a no-op on a locked bundle
    fw = filing.setChecklist(id, 'metadata', false, t(2), LAWYER);
    expect(latestBundle(fw)!.checklist.metadata).toBe(true);
    // hash is deterministic
    expect(bundleHash(locked)).toBe(locked.hash);
    // edit after lock → new v2 unlocked, filing re-blocked
    fw = filing.editAfterLock(id, t(3), LAWYER);
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
    s.filing.lockBundle(s.id, LAWYER, t(2));
    return s;
  }
  it('requires a locked bundle before filing can be recorded', () => {
    const { filing, id } = setup();
    filing.initBundle(id, t(1)); // not locked
    expect(filing.recordFiling(id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: 'proof://x' }, t(3), LAWYER)).toBeNull();
  });
  it('records filing, triggers 25% milestone, keeps invoice a draft until approval', () => {
    const { filing, id } = filedSetup();
    let fw = filing.recordFiling(id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: 'ok', proofRef: 'proof://abc' }, t(3), LAWYER)!;
    expect(fw.filing!.milestoneReached).toBe(true);
    expect(fw.filing!.milestonePct).toBe(MILESTONE_CASE_FILED_PCT);
    expect(fw.filing!.invoiceStatus).toBe('draft');
    expect(fw.timeline.some((e) => e.stage === 'E09')).toBe(true);
    fw = filing.approveFilingInvoice(id, t(3), BILLING);
    expect(fw.filing!.invoiceStatus).toBe('approved');
  });
  it('corrections append to history', () => {
    const { filing, id } = filedSetup();
    filing.recordFiling(id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'physical', filedBy: 'clerk', notes: '', proofRef: 'p://1' }, t(3), LAWYER);
    const fw = filing.correctFiling(id, 'court', 'District Court', t(4), LAWYER);
    expect(fw.filing!.court).toBe('District Court');
    expect(fw.filing!.corrections[0].old).toBe('City Civil');
  });
});

describe('E10 diary number (SAATHI-24)', () => {
  function filedSetup() {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, LAWYER, t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: 'p://1' }, t(3), LAWYER);
    return s;
  }
  it('requires a filing and binds the diary to it; manual entry is not officially validated', () => {
    const { filing, id } = setup();
    expect(filing.captureDiary(id === '' ? '' : id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source: 'manual', receivedDate: t(4), acknowledgementRef: 'ack://1' }, t(4), LAWYER)).toBeNull(); // no filing yet
    const f = filedSetup();
    const fw = f.filing.captureDiary(f.id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source: 'manual', receivedDate: t(4), acknowledgementRef: 'ack://1' }, t(4), LAWYER)!;
    expect(fw.diary!.boundFilingId).toBe(fw.filing!.id);
    expect(fw.diary!.officiallyValidated).toBe(false);
  });
  it('authorised source marks officially validated; correction is append-only', () => {
    const { filing, id } = filedSetup();
    filing.captureDiary(id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source: 'authorised_source', receivedDate: t(4), acknowledgementRef: 'ack://1' }, t(4), LAWYER);
    const fw = filing.correctDiary(id, 'D/2/2026', 'typo', t(5), LAWYER);
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
  const line = (id: string, category: FeeLine['category'], amount = 1000): Omit<FeeLine, 'status' | 'allocations' | 'receipt'> =>
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
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, LAWYER, t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: 'p://1' }, t(3), LAWYER);
    return s;
  }
  it('validates CNR format without assuming one universal format', () => {
    expect(cnrFormatValid('KABC010001232026')).toBe(true);
    expect(cnrFormatValid('nope')).toBe(false);
    expect(cnrFormatValid('')).toBe(false);
  });
  it('requires filing/diary; tracking stays off until validated + activated; polling disabled', () => {
    const { filing, id } = setup();
    expect(filing.captureCnr(id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026', source: 'manual', sourceType: 'manual' }, t(5), LAWYER)).toBeNull(); // no filing/diary
    const d = diarySetup();
    let fw = d.filing.captureCnr(d.id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026', source: 'manual entry', sourceType: 'manual' }, t(5), LAWYER)!;
    expect(fw.tracking!.validated).toBe(true);
    expect(fw.tracking!.trackingEnabled).toBe(false); // off until activation
    expect(fw.tracking!.courtVerified).toBe(false); // manual is not court-verified
    fw = d.filing.activateTracking(d.id, true, t(6), LAWYER);
    expect(fw.tracking!.trackingEnabled).toBe(true);
    expect(ECOURTS_POLLING_ENABLED).toBe(false); // polling disabled pending LCR-009
  });
  it('does not activate tracking when the identifier is invalid', () => {
    const d = diarySetup();
    d.filing.captureCnr(d.id, { cnr: 'bad', caseNumber: 'x', source: 'manual', sourceType: 'manual' }, t(5), LAWYER);
    const fw = d.filing.activateTracking(d.id, false, t(6), LAWYER);
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
    filing.lockBundle(id, LAWYER, t(2));
    filing.recordFiling(id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: 'p://1' }, t(3), LAWYER);
    filing.captureDiary(id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source: 'manual', receivedDate: t(4), acknowledgementRef: 'ack://1' }, t(4), LAWYER);
    filing.addFee(id, { id: 'L1', category: 'court_fee', amount: 1000, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef: 'rc://1' }, t(5), LAWYER);
    filing.payFee(id, { lineId: 'L1', providerRef: 'r1', serverVerified: true, receiptRef: 'rc://1' }, t(5), LAWYER);
    filing.captureCnr(id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026', source: 'manual', sourceType: 'manual' }, t(6), LAWYER);
    filing.activateTracking(id, true, t(6), LAWYER);

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

// ---------------------------------------------------------------------------
// Phase A remediation — E08 finalize authorisation + audit + notification stub
// (SAATHI-20 / SAATHI-434 / SAATHI-435)
// ---------------------------------------------------------------------------
describe('E08 finalize authorisation, failure audit & notification stub (SAATHI-20/434/435)', () => {
  function ready() {
    const s = setup();
    s.filing.initBundle(s.id, t(1));
    completeAllChecklist(s.filing, s.id);
    return s;
  }

  it('A1: canFinalize authorises only typed lawyer/senior_advocate/firm_partner and NEVER a raw string', () => {
    expect(canFinalize({ id: 'rao', role: 'lawyer' })).toBe(true);
    expect(canFinalize({ id: 'p1', role: 'senior_advocate' })).toBe(true);
    expect(canFinalize({ id: 'p2', role: 'firm_partner' })).toBe(true);
    // raw caller-supplied strings are never authorised (no role:id prefix trust)
    expect(canFinalize('lawyer:rao')).toBe(false);
    expect(canFinalize('lawyer:spoofed-caller')).toBe(false);
    expect(canFinalize('firm_partner:self-asserted')).toBe(false);
    // typed but non-finalize roles / empty id / null are refused
    expect(canFinalize({ id: 'c1', role: 'client' })).toBe(false);
    expect(canFinalize({ id: 'k1', role: 'clerk' })).toBe(false);
    expect(canFinalize({ id: 'b1', role: 'billing_admin' })).toBe(false);
    expect(canFinalize({ id: '', role: 'lawyer' })).toBe(false);
    expect(canFinalize(null)).toBe(false);
    expect(canFinalize(undefined)).toBe(false);
  });

  it('A2: authorised lawyer can lock only after all nine dimensions pass', () => {
    const { filing, id } = ready();
    // sanity: nine dimensions
    expect(CHECKLIST_KEYS.length).toBe(9);
    const fw = filing.lockBundle(id, { id: 'rao', role: 'lawyer' }, t(2));
    expect(latestBundle(fw)!.locked).toBe(true);
    expect(latestBundle(fw)!.lockedBy).toBe('lawyer:rao');
  });

  it('A3: student/client/clerk/billing/unknown/empty actors cannot lock (state unchanged + failure audit)', () => {
    const bad: (FilingActor | undefined)[] = [
      { id: 's1', role: 'student' }, { id: 'c1', role: 'client' }, { id: 'k1', role: 'clerk' },
      { id: 'b1', role: 'billing_admin' }, { id: 'u1', role: 'unknown' }, { id: '', role: 'lawyer' }, undefined,
    ];
    for (const actor of bad) {
      const { filing, id } = ready();
      const fw = filing.lockBundle(id, actor, t(2));
      expect(latestBundle(fw)!.locked).toBe(false); // bundle state unchanged
      expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('unauthorised_actor'))).toBe(true);
    }
  });

  it('A4: incomplete authorised attempt appends failure audit without locking', () => {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); // checklist incomplete
    const fw = s.filing.lockBundle(s.id, LAWYER, t(2));
    expect(latestBundle(fw)!.locked).toBe(false);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('incomplete_checklist'))).toBe(true);
  });

  it('A5: successful lock appends the locked audit and queues ONLY the internal notification stub', () => {
    const { filing, id } = ready();
    const fw = filing.lockBundle(id, LAWYER, t(2));
    expect(fw.audit.some((e) => e.type === 'locked')).toBe(true);
    expect(fw.notifications.length).toBe(1);
    expect(fw.notifications[0].channel).toBe('internal_task');
    expect(fw.notifications[0].kind).toBe('bundle_locked');
    // no whatsapp queued by default; suppression is audited
    expect(fw.notifications.some((n) => n.channel === 'whatsapp')).toBe(false);
    expect(fw.audit.some((e) => e.type === 'notification_suppressed' && (e.ref ?? '').includes('whatsapp'))).toBe(true);
  });

  it('A6: WhatsApp is suppressed by default and only dispatched after explicit lawyer configuration', () => {
    const s1 = ready();
    const def = s1.filing.lockBundle(s1.id, LAWYER, t(2));
    expect(def.notifications.some((n) => n.channel === 'whatsapp')).toBe(false);

    const s2 = ready();
    s2.filing.configureNotifications(s2.id, { whatsappEnabled: true }, t(2), LAWYER);
    const cfg = s2.filing.lockBundle(s2.id, LAWYER, t(2));
    expect(cfg.notifications.some((n) => n.channel === 'whatsapp')).toBe(true);
    expect(cfg.notifications.find((n) => n.channel === 'whatsapp')!.dispatched).toBe(false); // stub only, nothing transmitted
  });

  it('A7: refusals/notifications persist across reload; edit-to-v2 re-blocks filing', () => {
    const { store, filing, id } = ready();
    filing.lockBundle(id, { id: 's1', role: 'student' }, t(2)); // refused + audited
    filing.lockBundle(id, LAWYER, t(2)); // locked + notification
    const filing2 = new FilingWorkflowService(store, new DraftWorkspaceService(store));
    const fw = filing2.get(id)!;
    expect(latestBundle(fw)!.locked).toBe(true);
    expect(fw.notifications.length).toBe(1);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('unauthorised_actor'))).toBe(true);
    const v2 = filing2.editAfterLock(id, t(3), LAWYER);
    expect(latestBundle(v2)!.versionNo).toBe(2);
    expect(canProceedToFiling(v2)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Phase B — E09 filing-proof upload (SAATHI-22/436/438)
// ---------------------------------------------------------------------------
describe('E09 real filing-proof upload (SAATHI-22/436/438)', () => {
  function filed() {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, LAWYER, t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: '' }, t(3), LAWYER);
    return s;
  }
  it('B09.1: validateUpload accepts an allowed PDF and rejects type/size/empty/missing', () => {
    expect(validateUpload(validPdf).ok).toBe(true);
    expect(validateUpload({ filename: 'x.exe', mime: 'application/octet-stream', size: 10, present: true })).toEqual({ ok: false, reason: 'type' });
    expect(validateUpload({ filename: 'big.pdf', mime: 'application/pdf', size: MAX_UPLOAD_BYTES + 1, present: true })).toEqual({ ok: false, reason: 'size' });
    expect(validateUpload({ filename: 'empty.pdf', mime: 'application/pdf', size: 0, present: true })).toEqual({ ok: false, reason: 'empty' });
    expect(validateUpload({ filename: '', mime: 'application/pdf', size: 10, present: false })).toEqual({ ok: false, reason: 'missing' });
    // MIME/extension mismatch is rejected as a type error
    expect(validateUpload({ filename: 'proof.pdf', mime: 'image/gif', size: 10, present: true })).toEqual({ ok: false, reason: 'type' });
  });
  it('B09.2: attach persists safe metadata + opaque ref (no bytes/PII) and audits proof_uploaded', () => {
    const { filing, id } = filed();
    const { fw, validation } = filing.attachFilingProof(id, validPdf, t(4), LAWYER);
    expect(validation.ok).toBe(true);
    expect(fw.filing!.proof!.ref.startsWith('upload_')).toBe(true);
    expect(fw.filing!.proof!.filename).toBe('proof.pdf');
    expect(fw.filing!.proofRef).toBe(fw.filing!.proof!.ref); // reference points at opaque metadata
    expect(fw.audit.some((e) => e.type === 'proof_uploaded')).toBe(true);
    // milestone + invoice gate intact
    expect(fw.filing!.milestoneReached).toBe(true);
    expect(fw.filing!.invoiceStatus).toBe('draft');
  });
  it('B09.3: invalid upload rejected with a reason and no proof stored; persists across reload', () => {
    const { store, filing, id } = filed();
    const { fw, validation } = filing.attachFilingProof(id, { filename: 'v.mp4', mime: 'video/mp4', size: 5, present: true }, t(4), LAWYER);
    expect(validation.ok).toBe(false);
    expect(fw.filing!.proof).toBeNull();
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('proof_upload_rejected'))).toBe(true);
    // reload keeps a successfully-attached proof
    filing.attachFilingProof(id, validPdf, t(5), LAWYER);
    const fw2 = new FilingWorkflowService(store, new DraftWorkspaceService(store)).get(id)!;
    expect(fw2.filing!.proof!.filename).toBe('proof.pdf');
  });
});

// ---------------------------------------------------------------------------
// Phase B — E10 acknowledgement upload (SAATHI-24/439/441)
// ---------------------------------------------------------------------------
describe('E10 acknowledgement upload (SAATHI-24/439/441)', () => {
  function diaried(source: 'manual' | 'authorised_source' = 'manual') {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, LAWYER, t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: '' }, t(3), LAWYER);
    s.filing.captureDiary(s.id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source, receivedDate: t(4), acknowledgementRef: '' }, t(4), LAWYER);
    return s;
  }
  it('B10.1: attaches acknowledgement metadata + ref, keeps manual "not officially validated"', () => {
    const { filing, id } = diaried('manual');
    const { fw, validation } = filing.attachDiaryAcknowledgement(id, { filename: 'ack.png', mime: 'image/png', size: 2048, present: true }, t(5), LAWYER);
    expect(validation.ok).toBe(true);
    expect(fw.diary!.acknowledgement!.ref.startsWith('upload_')).toBe(true);
    expect(fw.diary!.acknowledgementRef).toBe(fw.diary!.acknowledgement!.ref);
    expect(fw.diary!.officiallyValidated).toBe(false); // manual guardrail preserved
    expect(fw.diary!.boundFilingId).toBe(fw.filing!.id); // binding preserved
    expect(fw.audit.some((e) => e.type === 'ack_uploaded')).toBe(true);
  });
  it('B10.2: rejects an invalid acknowledgement and preserves append-only correction history', () => {
    const { filing, id } = diaried('authorised_source');
    filing.attachDiaryAcknowledgement(id, validPdf, t(5), LAWYER);
    const bad = filing.attachDiaryAcknowledgement(id, { filename: 'a.txt', mime: 'text/plain', size: 3, present: true }, t(6), LAWYER);
    expect(bad.validation.ok).toBe(false);
    const fw = filing.correctDiary(id, 'D/2/2026', 'typo', t(7), LAWYER);
    expect(fw.diary!.acknowledgement!.filename).toBe('proof.pdf'); // valid one retained
    expect(fw.diary!.history[0].old).toBe('D/1/2026'); // append-only history intact
    expect(fw.diary!.officiallyValidated).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Phase B — E11 receipt upload + client statement (SAATHI-26/442/444)
// ---------------------------------------------------------------------------
describe('E11 receipt upload + client statement (SAATHI-26/442/444)', () => {
  function feed() {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, LAWYER, t(2));
    s.filing.addFee(s.id, { id: 'L1', category: 'court_fee', amount: 1000, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef: null }, t(5), LAWYER);
    s.filing.addFee(s.id, { id: 'L2', category: 'professional_fee', amount: 5000, payer: 'client', payee: 'firm', date: t(5), mode: 'online', receiptRef: null }, t(5), LAWYER);
    s.filing.addFee(s.id, { id: 'L3', category: 'refund', amount: 200, payer: 'firm', payee: 'client', date: t(5), mode: 'online', receiptRef: null }, t(5), LAWYER);
    return s;
  }
  it('B11.1: receipt upload stores safe metadata/ref but does NOT itself mark the line paid', () => {
    const { filing, id } = feed();
    const { fw, validation } = filing.attachFeeReceipt(id, 'L1', validPdf, t(6), LAWYER);
    expect(validation.ok).toBe(true);
    const l1 = fw.fees.lines.find((l) => l.id === 'L1')!;
    expect(l1.receipt!.ref.startsWith('upload_')).toBe(true);
    expect(l1.receiptRef).toBe(l1.receipt!.ref);
    expect(l1.status).toBe('pending'); // still gated on server-verified payment
    expect(fw.audit.some((e) => e.type === 'receipt_uploaded')).toBe(true);
  });
  it('B11.2: paid remains server-verification + receipt gated and idempotent after upload', () => {
    const { filing, id } = feed();
    filing.attachFeeReceipt(id, 'L1', validPdf, t(6), LAWYER);
    let fw = filing.payFee(id, { lineId: 'L1', providerRef: 'p1', serverVerified: false, receiptRef: 'rc' }, t(6), LAWYER);
    expect(fw.fees.lines.find((l) => l.id === 'L1')!.status).toBe('manual_review'); // unverified
    fw = filing.payFee(id, { lineId: 'L1', providerRef: 'p2', serverVerified: true, receiptRef: 'rc' }, t(6), LAWYER);
    expect(fw.fees.lines.find((l) => l.id === 'L1')!.status).toBe('paid');
    const before = fw.fees.lines.find((l) => l.id === 'L1')!;
    fw = filing.payFee(id, { lineId: 'L1', providerRef: 'p2', serverVerified: true, receiptRef: 'rc' }, t(6), LAWYER); // duplicate
    expect(fw.fees.lines.find((l) => l.id === 'L1')!).toEqual(before);
  });
  it('B11.3: client statement lists every line with pending/paid/refunded and distinct categories + totals', () => {
    const { filing, id } = feed();
    filing.attachFeeReceipt(id, 'L1', validPdf, t(6), LAWYER);
    filing.payFee(id, { lineId: 'L1', providerRef: 'p2', serverVerified: true, receiptRef: 'rc' }, t(6), LAWYER);
    const st = filing.clientStatement(id)!;
    expect(st.lines.length).toBe(3);
    expect(st.lines.map((l) => l.status)).toEqual(['paid', 'pending', 'refunded']);
    expect(st.lines.map((l) => l.category)).toEqual(['court_fee', 'professional_fee', 'refund']);
    expect(st.totalPaid).toBe(1000);
    expect(st.totalPending).toBe(5000);
    expect(st.totalRefunded).toBe(200);
    expect(st.totalBilled).toBe(6000); // refund excluded from billed
    expect(statementLineStatus({ id: 'x', category: 'process_fee', amount: 1, payer: '', payee: '', date: '', mode: '', status: 'manual_review', receiptRef: null, receipt: null, allocations: [] })).toBe('pending');
  });
  it('B11.4: keeps GST disabled by default (LCR-007/008)', () => {
    expect(GST_ENABLED).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Phase B — E12 identifier fallback actions (SAATHI-28/445/447)
// ---------------------------------------------------------------------------
describe('E12 identifier fallback actions (SAATHI-28/445/447)', () => {
  function tracked(cnr: string) {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, LAWYER, t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: '' }, t(3), LAWYER);
    s.filing.captureCnr(s.id, { cnr, caseNumber: 'OS/1/2026', source: 'manual entry', sourceType: 'manual' }, t(4), LAWYER);
    return s;
  }
  it('B12.1: automated fetch is disabled by default and returns an actionable manual-entry result', () => {
    expect(attemptAutomatedIdentifierFetch().reason).toBe('polling_disabled');
    expect(ECOURTS_POLLING_ENABLED).toBe(false);
    const { filing, id } = tracked('bad');
    const { fw, result } = filing.attemptIdentifierFetch(id, t(5), LAWYER);
    expect(result.ok).toBe(false);
    expect(result.message.length).toBeGreaterThan(0);
    expect(fw.audit.some((e) => e.type === 'identifier_fetch_attempt')).toBe(true);
  });
  it('B12.2: manual update fixes an invalid identifier, stays not-court-verified, and audits the fallback', () => {
    const { filing, id } = tracked('bad'); // invalid capture
    expect(filing.get(id)!.tracking!.validated).toBe(false);
    const fw = filing.manualUpdateIdentifier(id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026' }, t(5), LAWYER);
    expect(fw.tracking!.validated).toBe(true);
    expect(fw.tracking!.courtVerified).toBe(false); // manual is never court-verified
    expect(fw.tracking!.sourceType).toBe('manual');
    expect(fw.audit.some((e) => e.type === 'identifier_manual_update')).toBe(true);
    expect(fw.audit.some((e) => e.type === 'manual_fallback')).toBe(true);
  });
  it('B12.3: validation-gated activation + refresh persistence hold after manual update', () => {
    const { store, filing, id } = tracked('bad');
    // invalid → activation refused
    let fw = filing.activateTracking(id, true, t(5), LAWYER);
    expect(fw.tracking!.trackingEnabled).toBe(false);
    // manual fix → now activatable
    filing.manualUpdateIdentifier(id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026' }, t(5), LAWYER);
    fw = filing.activateTracking(id, true, t(6), LAWYER);
    expect(fw.tracking!.trackingEnabled).toBe(true);
    const fw2 = new FilingWorkflowService(store, new DraftWorkspaceService(store)).get(id)!;
    expect(fw2.tracking!.trackingEnabled).toBe(true);
    expect(fw2.tracking!.courtVerified).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Round-3 Fix 1 — session-bound actor is written to audit (not hard-coded)
// (SAATHI-20/22/24/26/28)
// ---------------------------------------------------------------------------
describe('session actor identity in audit records (Fix 1)', () => {
  it('C1: successful lock records the passed session actor — never a hard-coded role', () => {
    const adv: FilingActor = { id: 'adv-1', role: 'senior_advocate' };
    const { filing, id } = setup();
    filing.initBundle(id, t(1));
    for (const k of CHECKLIST_KEYS) filing.setChecklist(id, k, true, t(2), adv);
    const fw = filing.lockBundle(id, adv, t(2));
    expect(latestBundle(fw)!.lockedBy).toBe('senior_advocate:adv-1');
    const lockAudit = fw.audit.find((e) => e.type === 'locked');
    expect(lockAudit!.actor).toBe('senior_advocate:adv-1');
    // every audit actor is the passed session actor — no hard-coded lawyer/billing fallback
    const actors = fw.audit.map((e) => e.actor).filter((a) => a !== 'system');
    expect(actors.every((a) => a === 'senior_advocate:adv-1')).toBe(true);
  });
  it('C2: downstream mutations attribute audit to the session actor when supplied', () => {
    const { filing, id } = setup();
    filing.initBundle(id, t(1));
    completeAllChecklist(filing, id);
    const actor = { id: 'adv-9', role: 'firm_partner' as const };
    filing.lockBundle(id, actor, t(2));
    filing.recordFiling(id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: '', notes: '', proofRef: '' }, t(3), actor);
    const fw = filing.addFee(id, { id: 'L1', category: 'court_fee', amount: 100, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef: null }, t(5), actor);
    expect(fw.audit.find((e) => e.type === 'filing_recorded')!.actor).toBe('firm_partner:adv-9');
    expect(fw.audit.find((e) => e.type === 'fee_added')!.actor).toBe('firm_partner:adv-9');
  });
});

// ---------------------------------------------------------------------------
// Round-3 Fix 3 — E10 lawyer-approved client-status notification gate
// (SAATHI-24/439/441)
// ---------------------------------------------------------------------------
describe('E10 client-status notification approval gate (SAATHI-24/439/441)', () => {
  function diaried() {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, LAWYER, t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: '' }, t(3), LAWYER);
    s.filing.captureDiary(s.id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source: 'manual', receivedDate: t(4), acknowledgementRef: '' }, t(4), LAWYER);
    return s;
  }
  it('F3.1: suppressed by default — no client notification is queued', () => {
    const { filing, id } = diaried();
    expect(filing.diaryClientStatusQueued(filing.get(id)!)).toBe(false);
    expect(filing.get(id)!.notifications.some((n) => n.kind === 'diary_client_status')).toBe(false);
  });
  it('F3.2: a disallowed actor cannot approve — failure audit, nothing queued', () => {
    const { filing, id } = diaried();
    const fw = filing.approveDiaryClientStatus(id, { id: 'c1', role: 'client' }, t(5));
    expect(fw.notifications.some((n) => n.kind === 'diary_client_status')).toBe(false);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('diary_notify_refused'))).toBe(true);
  });
  it('F3.3: lawyer approval queues one privacy-safe stub and is idempotent', () => {
    const { filing, id } = diaried();
    let fw = filing.approveDiaryClientStatus(id, { id: 'rao', role: 'lawyer' }, t(5));
    expect(fw.notifications.filter((n) => n.kind === 'diary_client_status').length).toBe(1);
    const stub = fw.notifications.find((n) => n.kind === 'diary_client_status')!;
    expect(stub.dispatched).toBe(false); // stub only, nothing transmitted
    expect(stub.id.includes('/')).toBe(false); // no PII/path in the id
    expect(fw.audit.some((e) => e.type === 'comm_approved' && (e.ref ?? '').includes('diary_client_status'))).toBe(true);
    // idempotent: repeated approval does not duplicate
    fw = filing.approveDiaryClientStatus(id, { id: 'rao', role: 'lawyer' }, t(6));
    expect(fw.notifications.filter((n) => n.kind === 'diary_client_status').length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// Round-3 Fix 4 — E11 advance allocation + client-statement shortfall math
// (SAATHI-26/442/444)
// ---------------------------------------------------------------------------
describe('E11 advance allocation + shortfall math (SAATHI-26/442/444)', () => {
  const mk = (id: string, category: FeeLine['category'], amount: number): Omit<FeeLine, 'status' | 'allocations' | 'receipt'> =>
    ({ id, category, amount, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef: null });

  it('F4.1: exact QA regression — pending shortfall is ₹12,500 (advance applied to the line)', () => {
    let ledger = emptyLedger(50000);
    ledger = addFeeLine(ledger, { ...mk('L1', 'court_fee', 1000), receiptRef: 'rcL1' });
    ledger = addFeeLine(ledger, mk('L2', 'process_fee', 2500));
    ledger = addFeeLine(ledger, mk('L3', 'professional_fee', 60000));
    ledger = addFeeLine(ledger, mk('L4', 'refund', 200));
    ledger = applyManualFeeVerification(ledger, 'L1', true); // court fee paid (receipt + verified)
    ledger = allocateAdvance(ledger, 'L3', 50000); // advance applied to the professional fee line
    const st = buildClientStatement(ledger);
    expect(st.totalBilled).toBe(63500); // 1000 + 2500 + 60000
    expect(st.totalPaid).toBe(1000);
    expect(st.advanceApplied).toBe(50000);
    expect(st.totalPending).toBe(12500); // 2500 + (60000 - 50000)
    expect(st.totalRefunded).toBe(200);
  });

  it('F4.2: partial / exact / over allocation edge cases', () => {
    let ledger = addFeeLine(emptyLedger(5000), mk('L1', 'court_fee', 1000));
    // partial
    ledger = allocateAdvance(ledger, 'L1', 400);
    expect(buildClientStatement(ledger).totalPending).toBe(600);
    // exact (top up to full)
    ledger = allocateAdvance(ledger, 'L1', 600);
    expect(buildClientStatement(ledger).totalPending).toBe(0);
    // over-allocation refused (would exceed the line's remaining amount)
    const before = ledger;
    ledger = allocateAdvance(ledger, 'L1', 100);
    expect(ledger).toBe(before);
    // cannot exceed advance balance
    let l2 = addFeeLine(emptyLedger(300), mk('X', 'court_fee', 100000));
    const b2 = l2;
    l2 = allocateAdvance(l2, 'X', 100000);
    expect(l2).toBe(b2);
  });

  it('F4.3: multiple lines + refund/adjustment excluded from billed/pending', () => {
    let ledger = emptyLedger(0);
    ledger = addFeeLine(ledger, mk('L1', 'court_fee', 500));
    ledger = addFeeLine(ledger, mk('L2', 'tax', 90));
    ledger = addFeeLine(ledger, mk('L3', 'adjustment', 40));
    ledger = addFeeLine(ledger, mk('L4', 'refund', 10));
    const st = buildClientStatement(ledger);
    expect(st.totalBilled).toBe(590); // court + tax only
    expect(st.totalPending).toBe(590);
    expect(st.totalRefunded).toBe(50); // adjustment + refund
    expect(st.lines.map((l) => l.status)).toEqual(['pending', 'pending', 'refunded', 'refunded']);
  });
});

// ---------------------------------------------------------------------------
// Round-4 C — least-privilege persona/action matrix (SAATHI-20/22/24/26/28)
// ---------------------------------------------------------------------------
describe('least-privilege permission matrix', () => {
  it('MX1: only lawyer/senior_advocate/firm_partner may lock (E08 final)', () => {
    for (const role of ['lawyer', 'senior_advocate', 'firm_partner'] as FilingActorRole[]) {
      expect(roleCan(role, 'lock')).toBe(true);
    }
    for (const role of ['associate', 'clerk', 'billing_admin', 'client', 'student', 'unknown'] as FilingActorRole[]) {
      expect(roleCan(role, 'lock')).toBe(false);
    }
  });
  it('MX2: clerk covers E09/E10/E12 capture only — never lock, notifications or billing', () => {
    expect(roleCan('clerk', 'filing_record')).toBe(true);
    expect(roleCan('clerk', 'diary_capture')).toBe(true);
    expect(roleCan('clerk', 'cnr_capture')).toBe(true);
    expect(roleCan('clerk', 'identifier_manual')).toBe(true);
    for (const a of ['lock', 'notify_config', 'diary_notify', 'invoice_approve', 'fee_add', 'fee_pay', 'fee_allocate', 'fee_receipt'] as FilingAction[]) {
      expect(roleCan('clerk', a)).toBe(false);
    }
  });
  it('MX3: billing_admin covers E09 invoice + E11 fees only — never lock', () => {
    for (const a of ['invoice_approve', 'fee_add', 'fee_pay', 'fee_allocate', 'fee_receipt'] as FilingAction[]) {
      expect(roleCan('billing_admin', a)).toBe(true);
    }
    for (const a of ['lock', 'checklist', 'diary_capture', 'cnr_capture'] as FilingAction[]) {
      expect(roleCan('billing_admin', a)).toBe(false);
    }
  });
  it('MX4: associate = every action except final lock', () => {
    expect(roleCan('associate', 'lock')).toBe(false);
    for (const a of ALL_FILING_ACTIONS.filter((x) => x !== 'lock')) expect(roleCan('associate', a)).toBe(true);
  });
  it('MX5: client/student/unknown have zero permitted actions', () => {
    for (const role of ['client', 'student', 'unknown'] as FilingActorRole[]) {
      expect(FILING_PERMISSIONS[role].length).toBe(0);
      for (const a of ALL_FILING_ACTIONS) expect(authorize({ id: 'x', role }, a)).toBe(false);
    }
  });
  it('MX6: authorize refuses empty id, unknown role and missing actor for every action', () => {
    for (const a of ALL_FILING_ACTIONS) {
      expect(authorize(undefined, a)).toBe(false);
      expect(authorize({ id: '', role: 'lawyer' }, a)).toBe(false);
      expect(authorize({ id: 'x', role: 'nope' as FilingActorRole }, a)).toBe(false);
    }
  });
});

// ---------------------------------------------------------------------------
// Round-4 D — every privileged mutation refuses missing / wrong-role / raw actors
// (SAATHI-20/22/24/26/28)
// ---------------------------------------------------------------------------
describe('service mutations require a verified authorised actor', () => {
  function locked() {
    const s = setup();
    s.filing.initBundle(s.id, t(1));
    completeAllChecklist(s.filing, s.id);
    s.filing.lockBundle(s.id, LAWYER, t(2));
    s.filing.recordFiling(s.id, { court: 'C', benchLocation: '', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: '' }, t(3), LAWYER);
    s.filing.captureDiary(s.id, { number: 'D/1/2026', court: 'C', year: '2026', source: 'manual', receivedDate: t(4), acknowledgementRef: '' }, t(4), LAWYER);
    return s;
  }
  const CLIENT: FilingActor = { id: 'c1', role: 'client' };

  it('D1: E08 checklist/lock/edit refuse missing + wrong-role actors (state unchanged + failure audit)', () => {
    const s = setup();
    s.filing.initBundle(s.id, t(1));
    // missing actor cannot tick the checklist
    let fw = s.filing.setChecklist(s.id, 'pleading', true, t(2), undefined); // missing actor explicitly
    expect(latestBundle(fw)!.checklist.pleading).toBe(false);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('checklist_refused'))).toBe(true);
    // client cannot tick either
    fw = s.filing.setChecklist(s.id, 'pleading', true, t(2), CLIENT);
    expect(latestBundle(fw)!.checklist.pleading).toBe(false);
    // complete via authorised lawyer, then a clerk cannot lock
    completeAllChecklist(s.filing, s.id);
    fw = s.filing.lockBundle(s.id, CLERK, t(2));
    expect(latestBundle(fw)!.locked).toBe(false);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('lock_refused:unauthorised_actor'))).toBe(true);
  });
  it('D2: E09 record/proof/invoice/correct refuse missing/wrong-role actors', () => {
    const s = locked();
    // recordFiling without actor → null (QA regression parity)
    const s2 = setup();
    s2.filing.initBundle(s2.id, t(1)); completeAllChecklist(s2.filing, s2.id); s2.filing.lockBundle(s2.id, LAWYER, t(2));
    expect(s2.filing.recordFiling(s2.id, { court: 'C', benchLocation: '', filedAt: t(3), mode: 'e-filing', filedBy: 'lawyer:self-asserted', notes: '', proofRef: '' }, t(3), undefined)).toBeNull();
    // invoice approval: only billing/lawyer; a clerk is refused
    const before = s.filing.get(s.id)!.filing!.invoiceStatus;
    const fw = s.filing.approveFilingInvoice(s.id, t(5), CLERK);
    expect(fw.filing!.invoiceStatus).toBe(before);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('invoice_approve_refused'))).toBe(true);
  });
  it('D3: E11 fee add/pay/allocate refuse a non-billing, non-lawyer actor (clerk)', () => {
    const s = locked();
    const fw = s.filing.addFee(s.id, { id: 'L1', category: 'court_fee', amount: 100, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef: null }, t(5), CLERK);
    expect(fw.fees.lines.length).toBe(0);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('fee_add_refused'))).toBe(true);
    // billing_admin is allowed
    const ok = s.filing.addFee(s.id, { id: 'L1', category: 'court_fee', amount: 100, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef: null }, t(5), BILLING);
    expect(ok.fees.lines.length).toBe(1);
  });
  it('D4: E12 capture/activate/manual refuse a missing actor', () => {
    const s = locked();
    expect(s.filing.captureCnr(s.id, { cnr: 'KABC010001232026', caseNumber: 'X', source: 'manual', sourceType: 'manual' }, t(5), undefined)).toBeNull();
    // authorised capture, then a missing actor cannot activate
    s.filing.captureCnr(s.id, { cnr: 'KABC010001232026', caseNumber: 'X', source: 'manual', sourceType: 'manual' }, t(5), LAWYER);
    const fw = s.filing.activateTracking(s.id, true, t(6), undefined);
    expect(fw.tracking!.trackingEnabled).toBe(false);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('tracking_activate_refused'))).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Round-4 (moved) — independent QA edge cases now permanent
// source: independent QA regression pack for cd44a3d (19 July 2026)
// ---------------------------------------------------------------------------
describe('Independent QA security regression (moved from cd44a3d QA pack)', () => {
  function readyForFiling() {
    const s = setup();
    s.filing.initBundle(s.id, t(1));
    completeAllChecklist(s.filing, s.id);
    s.filing.lockBundle(s.id, { id: 'opaque-user-1', role: 'lawyer' }, t(2));
    return s;
  }
  it('QA1: does not authorize a raw caller-supplied lawyer:* string', () => {
    expect(canFinalize('lawyer:spoofed-caller')).toBe(false);
  });
  it('QA2: refuses E09 mutation when the session actor is omitted', () => {
    const { filing, id } = readyForFiling();
    const result = filing.recordFiling(id, {
      court: 'City Civil', benchLocation: '', filedAt: t(5), mode: 'e-filing',
      filedBy: 'lawyer:self-asserted', notes: '', proofRef: '',
    }, t(5), undefined);
    expect(result).toBeNull();
  });
  it('QA3: does not double-count advance plus later full receipt payment', () => {
    let ledger = addFeeLine(emptyLedger(500), { id: 'L1', category: 'court_fee', amount: 1000, payer: 'client', payee: 'court', date: t(1), mode: 'online', receiptRef: 'receipt-1' });
    ledger = allocateAdvance(ledger, 'L1', 400);
    ledger = applyManualFeeVerification(ledger, 'L1', true);
    const statement = buildClientStatement(ledger);
    expect(statement.totalPaid + statement.advanceApplied).toBeLessThanOrEqual(statement.totalBilled);
  });
});

// ---------------------------------------------------------------------------
// Round-4 E — allocation/payment conservation invariant (SAATHI-26/442/444)
// ---------------------------------------------------------------------------
describe('E11 conservation: gross billed = paid + advance-applied + pending', () => {
  const mk = (id: string, amount: number, receiptRef: string | null = null): Omit<FeeLine, 'status' | 'allocations' | 'receipt'> =>
    ({ id, category: 'court_fee', amount, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef });
  const invariant = (led: FeeLedger) => {
    const st = buildClientStatement(led);
    expect(st.totalPaid + st.advanceApplied + st.totalPending).toBe(st.totalBilled);
  };

  it('CV1: allocation then full manual receipt releases the advance (no double count)', () => {
    let ledger = addFeeLine(emptyLedger(500), mk('L1', 1000, 'rc'));
    ledger = allocateAdvance(ledger, 'L1', 400); // balance 100
    ledger = applyManualFeeVerification(ledger, 'L1', true); // full receipt → advance released
    const st = buildClientStatement(ledger);
    expect(st.totalPaid).toBe(1000);
    expect(st.advanceApplied).toBe(0);
    expect(st.totalPending).toBe(0);
    expect(ledger.advanceBalance).toBe(500); // 100 + released 400
    invariant(ledger);
  });
  it('CV2: allocation then full server-verified payment releases the advance', () => {
    let ledger = addFeeLine(emptyLedger(1000), mk('L1', 1000, 'rc'));
    ledger = allocateAdvance(ledger, 'L1', 600); // balance 400
    const r = applyFeePayment(ledger, { lineId: 'L1', providerRef: 'p1', serverVerified: true, receiptRef: 'rc' });
    expect(r.ledger.advanceBalance).toBe(1000); // 400 + released 600
    invariant(r.ledger);
  });
  it('CV3: allocation then partial (unverified) payment keeps advance applied to pending', () => {
    let ledger = addFeeLine(emptyLedger(1000), mk('L1', 1000));
    ledger = allocateAdvance(ledger, 'L1', 400);
    const r = applyFeePayment(ledger, { lineId: 'L1', providerRef: 'p1', serverVerified: false, receiptRef: 'rc' });
    const st = buildClientStatement(r.ledger);
    expect(st.totalPaid).toBe(0);
    expect(st.advanceApplied).toBe(400);
    expect(st.totalPending).toBe(600);
    invariant(r.ledger);
  });
  it('CV4: invariant holds for multiple lines + refund/adjustment', () => {
    let ledger = emptyLedger(2000);
    ledger = addFeeLine(ledger, mk('L1', 1000, 'rc'));
    ledger = addFeeLine(ledger, { ...mk('L2', 3000), category: 'professional_fee' });
    ledger = addFeeLine(ledger, { ...mk('L3', 500), category: 'refund' });
    ledger = allocateAdvance(ledger, 'L2', 2000);
    ledger = applyManualFeeVerification(ledger, 'L1', true);
    invariant(ledger);
    expect(buildClientStatement(ledger).totalRefunded).toBe(500);
  });
});
