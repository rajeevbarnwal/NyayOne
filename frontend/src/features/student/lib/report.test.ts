import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import {
  ReportService, ReportError, validateEvidence, submissionErrors, canSubmit,
  toPublicView, toModerationView, SAFEST_PRIVACY, MAX_EVIDENCE_BYTES,
  type EvidenceMeta,
} from './report';

const ev = (over: Partial<EvidenceMeta> = {}): EvidenceMeta => ({ id: 'e1', filename: 'proof.pdf', mimeType: 'application/pdf', sizeBytes: 1000, ...over });

describe('SAATHI-269/271 internship report contract', () => {
  it('writes only the exact NyayOne report namespace', () => {
    const store = new InMemoryKvStore();
    new ReportService('stu-1', store).createDraft('r1', 't0');

    expect(store.get('nyayone.student.reports.v1.stu-1')).not.toBeNull();
    expect(store.get('ls-reports-stu-1')).toBeNull();
  });

  it('never reads or migrates a legacy private report namespace', () => {
    const store = new InMemoryKvStore();
    store.set('ls-reports-stu-1', { reports: { legacy: { private: true } }, audit: [] });

    expect(new ReportService('stu-1', store).get('legacy')).toBeNull();
    expect(store.get('nyayone.student.reports.v1.stu-1')).toBeNull();
  });

  it('TC-269-01: save and resume a valid draft without submitting', () => {
    const store = new InMemoryKvStore();
    new ReportService('stu-1', store).createDraft('r1', '2026-07-12T00:00:00Z', { category: 'unpaid', narrative: 'partial' });
    // fresh service (page reload) resumes the draft
    const resumed = new ReportService('stu-1', store).get('r1');
    expect(resumed?.status).toBe('draft');
    expect(resumed?.category).toBe('unpaid');
    expect(resumed?.narrative).toBe('partial');
  });

  it('TC-269-02: submission requires category, narrative and consent', () => {
    const store = new InMemoryKvStore();
    const svc = new ReportService('stu-1', store);
    svc.createDraft('r1', 't0');
    expect(submissionErrors(svc.get('r1')!)).toEqual(['missing_category', 'missing_narrative', 'missing_consent']);
    svc.saveDraft('r1', { category: 'harassment', narrative: 'n' }, 't1');
    expect(() => svc.submit('r1', 't2')).toThrowError(ReportError); // consent still missing
    svc.saveDraft('r1', { consent: true }, 't3');
    expect(canSubmit(svc.get('r1')!)).toBe(true);
  });

  it('TC-269-03: safest privacy default is anonymous; leaving it needs explicit confirm', () => {
    const store = new InMemoryKvStore();
    const svc = new ReportService('stu-1', store);
    const r = svc.createDraft('r1', 't0');
    expect(r.privacyMode).toBe(SAFEST_PRIVACY);
    expect(SAFEST_PRIVACY).toBe('anonymous');
    expect(() => svc.setPrivacy('r1', 'attributed', false, 't1')).toThrowError(ReportError);
    expect(svc.setPrivacy('r1', 'attributed', true, 't2').privacyMode).toBe('attributed');
  });

  it('TC-269-04: submit once → moderation_pending; repeat submit is idempotent', () => {
    const store = new InMemoryKvStore();
    const svc = new ReportService('stu-1', store);
    svc.createDraft('r1', 't0');
    svc.saveDraft('r1', { category: 'unsafe', narrative: 'n', consent: true }, 't1');
    const first = svc.submit('r1', 't2');
    expect(first.status).toBe('moderation_pending');
    expect(first.submittedAt).toBe('t2');
    const again = svc.submit('r1', 't9'); // idempotent — no change, no throw
    expect(again.status).toBe('moderation_pending');
    expect(again.submittedAt).toBe('t2');
    // exactly one 'submitted' audit event
    expect(svc.auditLog().filter((a) => a.type === 'submitted').length).toBe(1);
  });

  it('TC-269-05: rejects invalid/oversized evidence and preserves form state', () => {
    const store = new InMemoryKvStore();
    const svc = new ReportService('stu-1', store);
    svc.createDraft('r1', 't0');
    svc.saveDraft('r1', { category: 'unpaid', narrative: 'n' }, 't1');
    expect(() => svc.addEvidence('r1', ev({ mimeType: 'application/x-msdownload' }), 't2')).toThrowError(ReportError);
    expect(() => svc.addEvidence('r1', ev({ sizeBytes: MAX_EVIDENCE_BYTES + 1 }), 't2')).toThrowError(ReportError);
    // form/report state preserved (no evidence attached, narrative intact)
    expect(svc.get('r1')!.evidence.length).toBe(0);
    expect(svc.get('r1')!.narrative).toBe('n');
    // valid evidence attaches
    expect(svc.addEvidence('r1', ev(), 't3').evidence.length).toBe(1);
  });

  it('validateEvidence typed errors by code', () => {
    try { validateEvidence(ev({ mimeType: 'text/x' })); } catch (e) { expect((e as ReportError).code).toBe('evidence_type'); }
    try { validateEvidence(ev({ sizeBytes: 0 })); } catch (e) { expect((e as ReportError).code).toBe('evidence_size'); }
  });

  it('TC-269-06: anonymous reports never expose author identity in views or audit', () => {
    const store = new InMemoryKvStore();
    const svc = new ReportService('stu-1', store);
    svc.createDraft('r1', 't0');
    svc.saveDraft('r1', { category: 'harassment', narrative: 'sensitive detail', consent: true }, 't1');
    const rec = svc.submit('r1', 't2');
    // publication gate: a moderation_pending report has NO public view at all
    expect(toPublicView(rec)).toBeNull();
    // moderation view while anonymous: authorId null
    expect(toModerationView(rec).authorId).toBeNull();
    // audit carries no identity or narrative
    const auditStr = JSON.stringify(svc.auditLog());
    expect(auditStr).not.toContain('stu-1');
    expect(auditStr).not.toContain('sensitive detail');
  });

  it('TC-269-06: attributed mode reveals author ONLY to moderation view, never public', () => {
    const store = new InMemoryKvStore();
    const svc = new ReportService('stu-1', store);
    svc.createDraft('r1', 't0');
    svc.setPrivacy('r1', 'attributed', true, 't1');
    svc.saveDraft('r1', { category: 'unpaid', narrative: 'n', consent: true }, 't2');
    const rec = svc.submit('r1', 't3');
    expect(toModerationView(rec).authorId).toBe('stu-1');
    expect(toPublicView(rec)).toBeNull(); // attributed is still not publishable pre-moderation
  });

  it('TC-269-07: cross-user access to drafts/reports is refused', () => {
    const store = new InMemoryKvStore();
    new ReportService('stu-1', store).createDraft('r1', 't0');
    // another user cannot read it
    expect(new ReportService('stu-2', store).get('r1')).toBeNull();
    // another user cannot mutate it — refused (per-user namespace isolates records)
    expect(() => new ReportService('stu-2', store).saveDraft('r1', { narrative: 'x' }, 't1')).toThrowError(ReportError);
    try { new ReportService('stu-2', store).submit('r1', 't1'); } catch (e) { expect(['forbidden', 'not_found']).toContain((e as ReportError).code); }
  });

  it('submitted reports cannot be edited as drafts', () => {
    const store = new InMemoryKvStore();
    const svc = new ReportService('stu-1', store);
    svc.createDraft('r1', 't0');
    svc.saveDraft('r1', { category: 'unsafe', narrative: 'n', consent: true }, 't1');
    svc.submit('r1', 't2');
    expect(() => svc.saveDraft('r1', { narrative: 'edit' }, 't3')).toThrowError(ReportError);
  });

  // --- remediation regressions (independent QA defects) ---------------------
  function submitted(store: InMemoryKvStore, user = 'stu-1') {
    const svc = new ReportService(user, store);
    svc.createDraft('r1', 't0');
    svc.saveDraft('r1', { category: 'unsafe', narrative: 'orig', consent: true }, 't1');
    svc.submit('r1', 't2');
    return svc;
  }

  it('remediation: setPrivacy after submission is rejected (not_mutable)', () => {
    const svc = submitted(new InMemoryKvStore());
    let code = '';
    try { svc.setPrivacy('r1', 'attributed', true, 't3'); } catch (e) { code = (e as ReportError).code; }
    expect(code).toBe('not_mutable');
  });

  it('remediation: addEvidence after submission is rejected (not_mutable)', () => {
    const svc = submitted(new InMemoryKvStore());
    let code = '';
    try { svc.addEvidence('r1', ev(), 't3'); } catch (e) { code = (e as ReportError).code; }
    expect(code).toBe('not_mutable');
  });

  it('remediation: duplicate createDraft cannot overwrite an existing (submitted) report', () => {
    const svc = submitted(new InMemoryKvStore());
    const before = svc.get('r1');
    const auditBefore = svc.auditLog().length;
    let code = '';
    try { svc.createDraft('r1', 't9', { narrative: 'overwrite attempt' }); } catch (e) { code = (e as ReportError).code; }
    expect(code).toBe('duplicate_id');
    expect(svc.get('r1')).toEqual(before); // original preserved
    expect(svc.get('r1')!.narrative).toBe('orig');
    expect(svc.get('r1')!.status).toBe('moderation_pending');
    expect(svc.auditLog().length).toBe(auditBefore); // audit history unchanged
  });

  it('remediation: moderation_pending and draft cannot produce a public view', () => {
    const store = new InMemoryKvStore();
    const svc = submitted(store);
    expect(toPublicView(svc.get('r1')!)).toBeNull();
    svc.createDraft('r2', 't0');
    expect(toPublicView(svc.get('r2')!)).toBeNull();
  });

  it('remediation: original report + audit remain unchanged after every rejected mutation', () => {
    const svc = submitted(new InMemoryKvStore());
    const snap = svc.get('r1');
    const auditLen = svc.auditLog().length;
    const rejected = [
      () => svc.setPrivacy('r1', 'attributed', true, 't3'),
      () => svc.addEvidence('r1', ev(), 't3'),
      () => svc.saveDraft('r1', { narrative: 'x' }, 't3'),
      () => svc.createDraft('r1', 't3'),
    ];
    for (const fn of rejected) { try { fn(); } catch { /* expected rejection */ } }
    expect(svc.get('r1')).toEqual(snap);
    expect(svc.auditLog().length).toBe(auditLen);
  });
});
