import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { StudentScreen } from '../components';
import { LEGAL_METADATA, TERMS_AND_CONDITIONS_TEXT, PRIVACY_POLICY_TEXT } from '../lib/legalDocs';
import '../../../styles/legal.css';

export function TermsScreen() {
  const nav = useNavigate();
  const [tab, setTab] = useState<'terms' | 'privacy'>('terms');

  return (
    <StudentScreen screenId="S-94" className="legal-screen">
      <div className="legal-header">
        <button type="button" className="btn tap" onClick={() => nav(-1)} data-testid="legal-back-btn" style={{ marginBottom: 12 }}>
          ← Back
        </button>
        <h1 className="legal-title">Legal Terms & Compliance</h1>
        <div className="legal-meta">
          {LEGAL_METADATA.entityName} · Effective Date: {LEGAL_METADATA.effectiveDate}
        </div>
      </div>

      <div className="legal-nav-tabs" role="tablist" aria-label="Legal documents">
        <button
          role="tab"
          type="button"
          aria-selected={tab === 'terms'}
          className={tab === 'terms' ? 'active' : ''}
          onClick={() => setTab('terms')}
          data-testid="tab-terms"
        >
          Terms & Conditions
        </button>
        <button
          role="tab"
          type="button"
          aria-selected={tab === 'privacy'}
          className={tab === 'privacy' ? 'active' : ''}
          onClick={() => setTab('privacy')}
          data-testid="tab-privacy"
        >
          Privacy Policy (DPDP-aware)
        </button>
      </div>

      <div className="legal-card" data-testid="legal-content-card">
        <div className="legal-text-content">
          {tab === 'terms' ? TERMS_AND_CONDITIONS_TEXT : PRIVACY_POLICY_TEXT}
        </div>

        <div className="legal-actions">
          <span style={{ fontSize: '0.85rem', color: 'var(--text3)' }}>
            Grievances: {LEGAL_METADATA.supportEmail}
          </span>
          <button type="button" className="btn tap" onClick={() => window.print()}>
            Print / Save PDF
          </button>
        </div>
      </div>
    </StudentScreen>
  );
}

export function PrivacyScreen() {
  const nav = useNavigate();
  const [tab, setTab] = useState<'terms' | 'privacy'>('privacy');

  return (
    <StudentScreen screenId="S-95" className="legal-screen">
      <div className="legal-header">
        <button type="button" className="btn tap" onClick={() => nav(-1)} data-testid="legal-back-btn" style={{ marginBottom: 12 }}>
          ← Back
        </button>
        <h1 className="legal-title">Privacy Policy & DPDP Disclosure</h1>
        <div className="legal-meta">
          {LEGAL_METADATA.entityName} · Effective Date: {LEGAL_METADATA.effectiveDate}
        </div>
      </div>

      <div className="legal-nav-tabs" role="tablist" aria-label="Legal documents">
        <button
          role="tab"
          type="button"
          aria-selected={tab === 'terms'}
          className={tab === 'terms' ? 'active' : ''}
          onClick={() => setTab('terms')}
          data-testid="tab-terms"
        >
          Terms & Conditions
        </button>
        <button
          role="tab"
          type="button"
          aria-selected={tab === 'privacy'}
          className={tab === 'privacy' ? 'active' : ''}
          onClick={() => setTab('privacy')}
          data-testid="tab-privacy"
        >
          Privacy Policy (DPDP-aware)
        </button>
      </div>

      <div className="legal-card" data-testid="legal-content-card">
        <div className="legal-text-content">
          {tab === 'privacy' ? PRIVACY_POLICY_TEXT : TERMS_AND_CONDITIONS_TEXT}
        </div>

        <div className="legal-actions">
          <span style={{ fontSize: '0.85rem', color: 'var(--text3)' }}>
            Data Protection Officer: {LEGAL_METADATA.supportEmail}
          </span>
          <button type="button" className="btn tap" onClick={() => window.print()}>
            Print / Save PDF
          </button>
        </div>
      </div>
    </StudentScreen>
  );
}
