import { describe, expect, it } from 'vitest';
import {
  validateMatterFacts,
  EMPTY_MATTER_FACTS,
  addVersion,
  latestVersion,
  versionById,
  approveVersion,
  isVersionApproved,
  canExportForFiling,
  aiContentAwaitingApproval,
  createStubDraftingAssistant,
  draftAuditEvent,
  SAMPLE_MATTER_FACTS,
  type DraftVersion,
  type ApprovalRecord,
} from './drafting';

const t = (n: number) => `2026-07-11T00:0${n}:00.000Z`;

describe('E06 drafting (SAATHI-16)', () => {
  it('validates matter facts', () => {
    expect(Object.keys(validateMatterFacts(EMPTY_MATTER_FACTS)).length).toBe(3);
    expect(Object.keys(validateMatterFacts(SAMPLE_MATTER_FACTS)).length).toBe(0);
  });

  it('keeps append-only version history with stable ids', () => {
    let h: DraftVersion[] = [];
    h = addVersion(h, { authorId: 'assoc:1', createdAt: t(1), changeNote: 'initial', body: 'A', aiGenerated: false });
    h = addVersion(h, { authorId: 'assoc:1', createdAt: t(2), changeNote: 'edit', body: 'B', aiGenerated: false });
    expect(h).toHaveLength(2);
    expect(h[0].body).toBe('A'); // prior version preserved
    expect(h[1].versionNo).toBe(2);
    expect(latestVersion(h)!.body).toBe('B');
    expect(versionById(h, h[0].id)!.versionNo).toBe(1);
  });

  it('blocks export for filing until the latest version is lawyer-approved', () => {
    let h: DraftVersion[] = [];
    const gen = createStubDraftingAssistant().generate(SAMPLE_MATTER_FACTS, 'Plaint');
    h = addVersion(h, { authorId: 'assoc:1', createdAt: t(1), changeNote: 'ai draft', body: gen.body, aiGenerated: true, citations: gen.citations });
    let approvals: ApprovalRecord[] = [];

    // AI content is present but not filing-ready until a lawyer approves.
    expect(aiContentAwaitingApproval(h, approvals)).toBe(true);
    expect(canExportForFiling(h, approvals)).toBe(false);

    approvals = approveVersion(approvals, latestVersion(h)!.id, 'lawyer:rao', t(2));
    expect(isVersionApproved(approvals, latestVersion(h)!.id)).toBe(true);
    expect(canExportForFiling(h, approvals)).toBe(true);
    expect(aiContentAwaitingApproval(h, approvals)).toBe(false);

    // A new edit after approval RE-BLOCKS export until re-approved.
    h = addVersion(h, { authorId: 'assoc:1', createdAt: t(3), changeNote: 'post-approval edit', body: 'C', aiGenerated: false });
    expect(canExportForFiling(h, approvals)).toBe(false);
  });

  it('stub assistant labels output as AI-generated with citations carrying source versions', () => {
    const gen = createStubDraftingAssistant().generate(SAMPLE_MATTER_FACTS, 'Plaint');
    expect(gen.body).toContain('Acme Textiles');
    expect(gen.citations[0].sourceVersion).toBeTruthy();
    expect(gen.citations[0].title).toContain('Civil Procedure');
  });

  it('is idempotent on duplicate approvals and audits events', () => {
    let approvals: ApprovalRecord[] = [];
    approvals = approveVersion(approvals, 'v1-x', 'lawyer:rao', t(1));
    approvals = approveVersion(approvals, 'v1-x', 'lawyer:rao', t(2));
    expect(approvals).toHaveLength(1);
    expect(draftAuditEvent('approved', 'v1-x', 'lawyer:rao', t(1)).type).toBe('approved');
  });
});
