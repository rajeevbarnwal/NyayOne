import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import type { ReactElement } from 'react';
import { publicRiskLabelsKey, type PublicRiskLabelProjection } from '../lib/riskLabelsApi';
import {
  InternshipRiskSignals,
  OrganisationResponse,
  OrganisationResponseSubmittedState,
  PublicRiskLabelPanel,
  validateOrganisationResponse,
} from './RiskLabelScreens';

const ORGANISATION_ID = '00000000-0000-4000-8000-000000000279';
const TOKEN = 'never-render-this-private-token';
const PUBLISHED: PublicRiskLabelProjection = {
  organisationId: ORGANISATION_ID,
  available: true,
  labels: [{
    id: '00000000-0000-4000-8000-000000000280',
    category: 'unpaid_mismatch',
    neutralLabel: 'Moderated stipend expectation pattern',
    publicCount: null,
    lastReviewedAt: '2026-08-02T09:00:00Z',
    sourceType: 'moderated_aggregate',
    status: 'corrected',
    organisationResponse: {
      text: 'We updated the internship terms and introduced a documented review step.',
      lastReviewedAt: '2026-08-03T09:00:00Z',
      kind: 'correction',
    },
  }],
};

function render(path: string, component: ReactElement, seed: (client: QueryClient) => void = () => undefined): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seed(client);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>{component}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SAATHI-279 S-88/S-89 privacy-safe screens', () => {
  it('fails closed by default and does not render a listing label while release approval is absent', () => {
    const direct = render(`/s-88?organisation=${ORGANISATION_ID}`, <InternshipRiskSignals />);
    const compact = render('/s-21?listing=cam', <PublicRiskLabelPanel organisationId={ORGANISATION_ID} compact />);
    expect(direct).toContain('data-screen="S-88"');
    expect(direct).toContain('data-risk-label-state="disabled"');
    expect(direct).toContain('pending counsel, security and target-runtime release approval');
    expect(compact).toBe('');
    expect(direct).not.toContain('Moderated stipend expectation pattern');
  });

  it('renders only approved neutral wording, provenance, count suppression and moderated response when explicitly released', () => {
    const html = render('/s-88', (
      <PublicRiskLabelPanel
        organisationId={ORGANISATION_ID}
        organisationName="Example Chambers"
        releaseEnabled
      />
    ), (client) => client.setQueryData(publicRiskLabelsKey(ORGANISATION_ID), PUBLISHED));
    expect(html).toContain('data-risk-label-state="published"');
    expect(html).toContain('Moderated stipend expectation pattern');
    expect(html).toContain('Moderated aggregate');
    expect(html).toContain('Count withheld for privacy');
    expect(html).toContain('data-risk-label-status="corrected"');
    expect(html).toContain('Approved correction');
    expect(html).toContain('Approved organisation correction');
    expect(html).toContain('We updated the internship terms');
    expect(html).not.toContain('raw allegation');
    expect(html).not.toContain('private-reporter@example.invalid');
    expect(html).not.toContain('00000000-0000-4000-8000-000000000086');
  });

  it('captures the one-time invitation only from a non-transmitted URL fragment without rendering it', () => {
    const html = render(`/s-89#token=${TOKEN}`, <OrganisationResponse releaseEnabled />);
    expect(html).toContain('data-screen="S-89"');
    expect(html).toContain('data-response-state="invited"');
    expect(html).toContain('Organisation response or correction');
    // Native maxlength counts UTF-16 code units and would reject valid
    // 2,000-code-point responses such as emoji. The shared validator owns the
    // exact backend-compatible boundary instead.
    expect(html).not.toContain('maxLength=');
    expect(html).not.toContain(TOKEN);
    expect(html).not.toMatch(/name="token"|value="never-render/i);
  });

  it('rejects a legacy query-string credential so it cannot authorise or propagate beyond the initial web navigation', () => {
    const html = render(`/s-89?token=${TOKEN}`, <OrganisationResponse releaseEnabled />);
    expect(html).toContain('data-risk-label-state="invalid-invitation"');
    expect(html).toContain('A verified invitation is required');
    expect(html).not.toContain(TOKEN);
  });

  it('shows a truthful unavailable state without a token and a moderation-pending success state', () => {
    const unavailable = render('/s-89', <OrganisationResponse releaseEnabled />);
    const submitted = render('/s-89', <OrganisationResponseSubmittedState />);
    expect(unavailable).toContain('A verified invitation is required');
    expect(unavailable).toContain('Return to internships');
    expect(submitted).toContain('data-response-state="moderation-pending"');
    expect(submitted).toContain('Moderation review is pending');
    expect(submitted).toContain('invitation cannot be reused');
  });

  it('enforces the exact 1 and 2,000 character response boundaries and unsafe controls', () => {
    expect(validateOrganisationResponse('')).toContain('1–2,000');
    expect(validateOrganisationResponse('   ')).toContain('1–2,000');
    expect(validateOrganisationResponse('A')).toBeNull();
    expect(validateOrganisationResponse('A'.repeat(2_000))).toBeNull();
    expect(validateOrganisationResponse('A'.repeat(2_001))).toContain('1–2,000');
    expect(validateOrganisationResponse('😀'.repeat(2_000))).toBeNull();
    expect(validateOrganisationResponse('😀'.repeat(2_001))).toContain('1–2,000');
    expect(validateOrganisationResponse('Safe text\u0000')).toContain('control characters');
    expect(validateOrganisationResponse('Unsafe < private allegation >')).toContain('control characters');
  });
});
