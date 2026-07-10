import { describe, expect, it } from 'vitest';
import {
  isReliableForLegalUse,
  confirmTags,
  isAllowedFile,
  makeSecureLink,
  linkValid,
  urlHasNoPii,
  checklistProgress,
  SAMPLE_CHECKLIST,
} from './documents';

describe('document collection (SAATHI-14 / E05)', () => {
  it('treats OCR as assistive until the lawyer confirms tags', () => {
    const doc = { id: 'd1', filename: 'a.pdf', ocrText: '...', ocrConfirmed: false, tags: [] as string[] };
    expect(isReliableForLegalUse(doc)).toBe(false);
    const confirmed = confirmTags(doc, ['agreement']);
    expect(isReliableForLegalUse(confirmed)).toBe(true);
    expect(confirmed.tags).toEqual(['agreement']);
  });

  it('accepts only allowed file types', () => {
    expect(isAllowedFile('scan.PDF')).toBe(true);
    expect(isAllowedFile('photo.jpeg')).toBe(true);
    expect(isAllowedFile('malware.exe')).toBe(false);
  });

  it('builds expiring links with no PII in the URL', () => {
    const l = makeSecureLink('opaque-token-123', 1_000);
    expect(linkValid(l, 2_000)).toBe(true);
    expect(linkValid(l, 1_000 + 24 * 60 * 60 * 1000 + 1)).toBe(false);
    expect(urlHasNoPii(l.url)).toBe(true);
    expect(urlHasNoPii('/u/john@x.in')).toBe(false);
    expect(urlHasNoPii('/u/9876543210')).toBe(false);
  });

  it('computes checklist progress', () => {
    const p = checklistProgress(SAMPLE_CHECKLIST);
    expect(p.total).toBe(4);
    expect(p.received).toBe(2);
  });
});
