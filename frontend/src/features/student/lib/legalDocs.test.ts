import { describe, it, expect } from 'vitest';
import { LEGAL_METADATA, TERMS_AND_CONDITIONS_TEXT, PRIVACY_POLICY_TEXT } from './legalDocs';

describe('Legal Documents Engine (S-94 / S-95)', () => {
  it('loads valid metadata with entity name and support email', () => {
    expect(LEGAL_METADATA.title).toContain('LegalSaathi');
    expect(LEGAL_METADATA.entityName).toContain('Veriodion Labs LLP');
    expect(LEGAL_METADATA.supportEmail).toBe('support@nyayone.com');
  });

  it('contains full 23-section Terms & Conditions text extracted from docx', () => {
    expect(TERMS_AND_CONDITIONS_TEXT.length).toBeGreaterThan(5000);
    expect(TERMS_AND_CONDITIONS_TEXT).toContain('Terms & Conditions');
    expect(TERMS_AND_CONDITIONS_TEXT).toContain('Acceptance');
    expect(TERMS_AND_CONDITIONS_TEXT).toContain('Not a law firm; not legal advice');
    expect(TERMS_AND_CONDITIONS_TEXT).toContain('Governing law');
  });

  it('contains full DPDP-aware Privacy Policy text extracted from docx', () => {
    expect(PRIVACY_POLICY_TEXT.length).toBeGreaterThan(10000);
    expect(PRIVACY_POLICY_TEXT).toContain('Privacy Policy');
    expect(PRIVACY_POLICY_TEXT).toContain('What we collect');
    expect(PRIVACY_POLICY_TEXT).toContain('AI features and your content');
  });
});
