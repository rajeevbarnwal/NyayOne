import { describe, expect, it } from 'vitest';
import { InMemoryKvStore } from '../../../lib/kvStore';
import {
  ReportService, ReportError, validateEvidence, submissionErrors, canSubmit,
  toPublicView, toModerationView, SAFEST_PRIVACY, MAX_EVIDENCE_BYTES,
  type EvidenceMeta,
} from './report';

const ev = (over: Partial<EvidenceMeta> = {}): EvidenceMeta => ({ id: 'e1', filename: 'proof.pdf', mimeType: 'application/pdf', sizeBytes: 1000, ...over });

describe('SAATHI-269/271 internship report contract', () => {
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
    // public view: no author, no narrative
    const pub = toPublicView(rec);
    expect(Object.keys(pub)).not.toContain('authorId');
    expect(Object.keys(pub)).not.toContain('narrative');
    expect(JSON.stringify(pub)).not.toContain('stu-1');
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
    expect(JSON.stringify(toPublicView(rec))).not.toContain('stu-1');
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
});
