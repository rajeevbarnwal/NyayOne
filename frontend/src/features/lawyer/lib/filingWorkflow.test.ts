import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import { DraftWorkspaceService } from './draftWorkspace';
import {
  FilingWorkflowService, latestBundle, canProceedToFiling, checklistComplete, bundleHash,
  CHECKLIST_KEYS, applyFeePayment, applyManualFeeVerification, allocateAdvance, addFeeLine, emptyLedger,
  cnrFormatValid, trackingStale, GST_ENABLED, ECOURTS_POLLING_ENABLED, MILESTONE_CASE_FILED_PCT,
  diaryFormatValid, type FeeLine,
  parseActor, canFinalize, validateUpload, statementLineStatus,
  attemptAutomatedIdentifierFetch, MAX_UPLOAD_BYTES, type UploadInput,
} from './filingWorkflow';

const validPdf: UploadInput = { filename: 'proof.pdf', mime: 'application/pdf', size: 1024, present: true };

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

  it('E08 (SAATHI-20/433/434/435): fee-readiness and client-approval are required checklist dimensions', () => {
    // The two Jira dimensions are part of the canonical checklist contract.
    expect(CHECKLIST_KEYS).toContain('fee_readiness');
    expect(CHECKLIST_KEYS).toContain('client_approval');
    const { filing, id } = setup();
    filing.initBundle(id, t(1));
    // Complete every document dimension but leave fee_readiness + client_approval off.
    for (const k of CHECKLIST_KEYS) {
      if (k === 'fee_readiness' || k === 'client_approval') continue;
      filing.setChecklist(id, k, true, t(2));
    }
    let fw = filing.lockBundle(id, 'lawyer:rao', t(2));
    expect(latestBundle(fw)!.locked).toBe(false); // lock refused: readiness dims missing
    filing.setChecklist(id, 'fee_readiness', true, t(2));
    fw = filing.lockBundle(id, 'lawyer:rao', t(2));
    expect(latestBundle(fw)!.locked).toBe(false); // still refused: client_approval missing
    filing.setChecklist(id, 'client_approval', true, t(2));
    fw = filing.lockBundle(id, 'lawyer:rao', t(2));
    expect(latestBundle(fw)!.locked).toBe(true); // all required dimensions satisfied
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

  it('A1: parseActor/canFinalize authorise only lawyer/senior_advocate/firm_partner', () => {
    expect(canFinalize('lawyer:rao')).toBe(true);
    expect(canFinalize({ id: 'p1', role: 'senior_advocate' })).toBe(true);
    expect(canFinalize({ id: 'p2', role: 'firm_partner' })).toBe(true);
    expect(canFinalize('student:unauthorised')).toBe(false);
    expect(canFinalize('client:someone')).toBe(false);
    expect(canFinalize('clerk:desk')).toBe(false);
    expect(canFinalize('')).toBe(false);
    expect(canFinalize('   ')).toBe(false);
    expect(canFinalize(null)).toBe(false);
    // an un-roled bare string is never trusted as authorised
    expect(parseActor('totally-unknown').role).toBe('unknown');
    expect(canFinalize('totally-unknown')).toBe(false);
  });

  it('A2: authorised lawyer can lock only after all nine dimensions pass', () => {
    const { filing, id } = ready();
    // sanity: nine dimensions
    expect(CHECKLIST_KEYS.length).toBe(9);
    const fw = filing.lockBundle(id, { id: 'rao', role: 'lawyer' }, t(2));
    expect(latestBundle(fw)!.locked).toBe(true);
    expect(latestBundle(fw)!.lockedBy).toBe('lawyer:rao');
  });

  it('A3: student/client/unknown/empty actors cannot lock (state unchanged + failure audit)', () => {
    for (const bad of ['student:unauthorised', 'client:x', 'clerk:y', '', 'unroled-string']) {
      const { filing, id } = ready();
      const fw = filing.lockBundle(id, bad, t(2));
      expect(latestBundle(fw)!.locked).toBe(false); // bundle state unchanged
      expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('unauthorised_actor'))).toBe(true);
    }
  });

  it('A4: incomplete authorised attempt appends failure audit without locking', () => {
    const s = setup();
    s.filing.initBundle(s.id, t(1)); // checklist incomplete
    const fw = s.filing.lockBundle(s.id, 'lawyer:rao', t(2));
    expect(latestBundle(fw)!.locked).toBe(false);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('incomplete_checklist'))).toBe(true);
  });

  it('A5: successful lock appends the locked audit and queues ONLY the internal notification stub', () => {
    const { filing, id } = ready();
    const fw = filing.lockBundle(id, 'lawyer:rao', t(2));
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
    const def = s1.filing.lockBundle(s1.id, 'lawyer:rao', t(2));
    expect(def.notifications.some((n) => n.channel === 'whatsapp')).toBe(false);

    const s2 = ready();
    s2.filing.configureNotifications(s2.id, { whatsappEnabled: true }, t(2));
    const cfg = s2.filing.lockBundle(s2.id, 'lawyer:rao', t(2));
    expect(cfg.notifications.some((n) => n.channel === 'whatsapp')).toBe(true);
    expect(cfg.notifications.find((n) => n.channel === 'whatsapp')!.dispatched).toBe(false); // stub only, nothing transmitted
  });

  it('A7: refusals/notifications persist across reload; edit-to-v2 re-blocks filing', () => {
    const { store, filing, id } = ready();
    filing.lockBundle(id, 'student:unauthorised', t(2)); // refused + audited
    filing.lockBundle(id, 'lawyer:rao', t(2)); // locked + notification
    const filing2 = new FilingWorkflowService(store, new DraftWorkspaceService(store));
    const fw = filing2.get(id)!;
    expect(latestBundle(fw)!.locked).toBe(true);
    expect(fw.notifications.length).toBe(1);
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('unauthorised_actor'))).toBe(true);
    const v2 = filing2.editAfterLock(id, t(3));
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
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, 'lawyer:rao', t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: '' }, t(3));
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
    const { fw, validation } = filing.attachFilingProof(id, validPdf, t(4));
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
    const { fw, validation } = filing.attachFilingProof(id, { filename: 'v.mp4', mime: 'video/mp4', size: 5, present: true }, t(4));
    expect(validation.ok).toBe(false);
    expect(fw.filing!.proof).toBeNull();
    expect(fw.audit.some((e) => e.type === 'failure' && (e.ref ?? '').includes('proof_upload_rejected'))).toBe(true);
    // reload keeps a successfully-attached proof
    filing.attachFilingProof(id, validPdf, t(5));
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
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, 'lawyer:rao', t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: '' }, t(3));
    s.filing.captureDiary(s.id, { number: 'D/1/2026', court: 'City Civil', year: '2026', source, receivedDate: t(4), acknowledgementRef: '' }, t(4));
    return s;
  }
  it('B10.1: attaches acknowledgement metadata + ref, keeps manual "not officially validated"', () => {
    const { filing, id } = diaried('manual');
    const { fw, validation } = filing.attachDiaryAcknowledgement(id, { filename: 'ack.png', mime: 'image/png', size: 2048, present: true }, t(5));
    expect(validation.ok).toBe(true);
    expect(fw.diary!.acknowledgement!.ref.startsWith('upload_')).toBe(true);
    expect(fw.diary!.acknowledgementRef).toBe(fw.diary!.acknowledgement!.ref);
    expect(fw.diary!.officiallyValidated).toBe(false); // manual guardrail preserved
    expect(fw.diary!.boundFilingId).toBe(fw.filing!.id); // binding preserved
    expect(fw.audit.some((e) => e.type === 'ack_uploaded')).toBe(true);
  });
  it('B10.2: rejects an invalid acknowledgement and preserves append-only correction history', () => {
    const { filing, id } = diaried('authorised_source');
    filing.attachDiaryAcknowledgement(id, validPdf, t(5));
    const bad = filing.attachDiaryAcknowledgement(id, { filename: 'a.txt', mime: 'text/plain', size: 3, present: true }, t(6));
    expect(bad.validation.ok).toBe(false);
    const fw = filing.correctDiary(id, 'D/2/2026', 'typo', 'lawyer', t(7));
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
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, 'lawyer:rao', t(2));
    s.filing.addFee(s.id, { id: 'L1', category: 'court_fee', amount: 1000, payer: 'client', payee: 'court', date: t(5), mode: 'online', receiptRef: null }, t(5));
    s.filing.addFee(s.id, { id: 'L2', category: 'professional_fee', amount: 5000, payer: 'client', payee: 'firm', date: t(5), mode: 'online', receiptRef: null }, t(5));
    s.filing.addFee(s.id, { id: 'L3', category: 'refund', amount: 200, payer: 'firm', payee: 'client', date: t(5), mode: 'online', receiptRef: null }, t(5));
    return s;
  }
  it('B11.1: receipt upload stores safe metadata/ref but does NOT itself mark the line paid', () => {
    const { filing, id } = feed();
    const { fw, validation } = filing.attachFeeReceipt(id, 'L1', validPdf, t(6));
    expect(validation.ok).toBe(true);
    const l1 = fw.fees.lines.find((l) => l.id === 'L1')!;
    expect(l1.receipt!.ref.startsWith('upload_')).toBe(true);
    expect(l1.receiptRef).toBe(l1.receipt!.ref);
    expect(l1.status).toBe('pending'); // still gated on server-verified payment
    expect(fw.audit.some((e) => e.type === 'receipt_uploaded')).toBe(true);
  });
  it('B11.2: paid remains server-verification + receipt gated and idempotent after upload', () => {
    const { filing, id } = feed();
    filing.attachFeeReceipt(id, 'L1', validPdf, t(6));
    let fw = filing.payFee(id, { lineId: 'L1', providerRef: 'p1', serverVerified: false, receiptRef: 'rc' }, t(6));
    expect(fw.fees.lines.find((l) => l.id === 'L1')!.status).toBe('manual_review'); // unverified
    fw = filing.payFee(id, { lineId: 'L1', providerRef: 'p2', serverVerified: true, receiptRef: 'rc' }, t(6));
    expect(fw.fees.lines.find((l) => l.id === 'L1')!.status).toBe('paid');
    const before = fw.fees.lines.find((l) => l.id === 'L1')!;
    fw = filing.payFee(id, { lineId: 'L1', providerRef: 'p2', serverVerified: true, receiptRef: 'rc' }, t(6)); // duplicate
    expect(fw.fees.lines.find((l) => l.id === 'L1')!).toEqual(before);
  });
  it('B11.3: client statement lists every line with pending/paid/refunded and distinct categories + totals', () => {
    const { filing, id } = feed();
    filing.attachFeeReceipt(id, 'L1', validPdf, t(6));
    filing.payFee(id, { lineId: 'L1', providerRef: 'p2', serverVerified: true, receiptRef: 'rc' }, t(6));
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
    s.filing.initBundle(s.id, t(1)); completeAllChecklist(s.filing, s.id); s.filing.lockBundle(s.id, 'lawyer:rao', t(2));
    s.filing.recordFiling(s.id, { court: 'City Civil', benchLocation: 'Blr', filedAt: t(3), mode: 'e-filing', filedBy: 'clerk', notes: '', proofRef: '' }, t(3));
    s.filing.captureCnr(s.id, { cnr, caseNumber: 'OS/1/2026', source: 'manual entry', sourceType: 'manual' }, t(4));
    return s;
  }
  it('B12.1: automated fetch is disabled by default and returns an actionable manual-entry result', () => {
    expect(attemptAutomatedIdentifierFetch().reason).toBe('polling_disabled');
    expect(ECOURTS_POLLING_ENABLED).toBe(false);
    const { filing, id } = tracked('bad');
    const { fw, result } = filing.attemptIdentifierFetch(id, t(5));
    expect(result.ok).toBe(false);
    expect(result.message.length).toBeGreaterThan(0);
    expect(fw.audit.some((e) => e.type === 'identifier_fetch_attempt')).toBe(true);
  });
  it('B12.2: manual update fixes an invalid identifier, stays not-court-verified, and audits the fallback', () => {
    const { filing, id } = tracked('bad'); // invalid capture
    expect(filing.get(id)!.tracking!.validated).toBe(false);
    const fw = filing.manualUpdateIdentifier(id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026' }, t(5));
    expect(fw.tracking!.validated).toBe(true);
    expect(fw.tracking!.courtVerified).toBe(false); // manual is never court-verified
    expect(fw.tracking!.sourceType).toBe('manual');
    expect(fw.audit.some((e) => e.type === 'identifier_manual_update')).toBe(true);
    expect(fw.audit.some((e) => e.type === 'manual_fallback')).toBe(true);
  });
  it('B12.3: validation-gated activation + refresh persistence hold after manual update', () => {
    const { store, filing, id } = tracked('bad');
    // invalid → activation refused
    let fw = filing.activateTracking(id, true, t(5));
    expect(fw.tracking!.trackingEnabled).toBe(false);
    // manual fix → now activatable
    filing.manualUpdateIdentifier(id, { cnr: 'KABC010001232026', caseNumber: 'OS/1/2026' }, t(5));
    fw = filing.activateTracking(id, true, t(6));
    expect(fw.tracking!.trackingEnabled).toBe(true);
    const fw2 = new FilingWorkflowService(store, new DraftWorkspaceService(store)).get(id)!;
    expect(fw2.tracking!.trackingEnabled).toBe(true);
    expect(fw2.tracking!.courtVerified).toBe(false);
  });
});
