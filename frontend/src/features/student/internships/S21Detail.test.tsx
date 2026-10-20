import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AuthProvider, type AuthState } from '../../../app/authContext';
import { AppShell } from '../../../components/shell/AppShell';
import { InternshipDetail } from './InternshipScreens';
import { S21DetailView, type S21DetailViewProps } from './S21DetailView';
import type { InternshipListing } from '../lib/internships';

const auth: AuthState = { isAuthenticated: true, userId: 'synthetic', roles: ['student'], studentVerification: 'verified', lawyerVerification: 'draft', filingRole: null, isMinor: false };
const item: InternshipListing = { id: 'synthetic-role', role: 'Research intern', org: 'Synthetic chambers', location: 'Delhi', stipendMonthlyPaise: null, verificationStatus: 'unverified', deadline: '8 Jul 2027', eligibility: 'Students', tags: ['Research'], description: 'Research support', source: { name: 'Synthetic source', url: 'https://example.test/role', retrievedAt: null, verifiedAt: null } };
function render(path = '/s-21?listing=synthetic-role', saved: unknown = []) {
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } });
  client.setQueryData(['internship', item.id], item);
  if (saved !== null) client.setQueryData(['internships-saved', auth.userId], saved);
  return renderToStaticMarkup(<QueryClientProvider client={client}><AuthProvider value={auth}><MemoryRouter initialEntries={[path]}><AppShell theme="light" toggleTheme={() => undefined}><InternshipDetail/></AppShell></MemoryRouter></AuthProvider></QueryClientProvider>);
}
describe('S-21 approved detail composition', () => {
  it('shows exact listing, truthful provenance and the reserved Apply control', () => {
    const html = render();
    expect(html).toContain('About this internship');
    expect(html).toContain('Research intern');
    expect(html).toContain('Not stated');
    expect(html).toContain('Open source listing');
    expect(html).toContain('Apply is not available yet.');
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*>[\s\S]*?Apply<\/button>/);
    expect(html).not.toContain('/s-22');
  });
  it('retains the saved-list return context and unknown marks stay unknown', () => {
    expect(render('/s-21?listing=synthetic-role&from=s25')).toContain('Back to saved internships');
    expect(render('/s-21?listing=synthetic-role', null)).not.toContain('aria-pressed="false"');
  });
  it.each(['/s-21?listing=synthetic-role', '/S-21/?listing=synthetic-role#detail'])('owns one main with sibling aside at %s', path => {
    const html = render(path);
    expect(html.match(/<main\b/g)).toHaveLength(1);
    expect(html).not.toContain('v34-screen--continuation');
    expect(html.indexOf('</main>')).toBeLessThan(html.indexOf('<aside'));
  });
});

const view = (extra: Partial<S21DetailViewProps> = {}) => renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><S21DetailView
  focus={{ current: null }} phase="detail" item={item} savedState="unsaved" busy={false}
  failure="" notice="" fromSaved={false} onNavigate={() => undefined}
  onToggle={async () => undefined} onRetry={async () => undefined} onRetrySaved={async () => undefined} {...extra}/></QueryClientProvider>);
describe('S-21 presentation corrections preserve action authority', () => {
  it('restores indigo tag markers, decorative source/Apply icons and source new-tab disclosure', () => {
    const html = view();
    expect(html).toContain('s21-tag');
    expect(html).toMatch(/s21-tag[^>]*><span[^>]*aria-hidden="true"/);
    expect(html.match(/s21-icon--send/g)).toHaveLength(2);
    expect(html).toContain('(opens example.test in a new tab)');
    expect(html).toContain('aria-disabled="true"');
    expect(html).not.toContain('/s-22');
  });
  it('uses indigo unsaved/retry and gold saved icons without changing the saved state', () => {
    expect(view()).toContain('s21-action-indigo');
    const saved = view({ savedState: 'saved' });
    expect(saved).toContain('s21-action-gold');
    expect(saved).toContain('aria-pressed="true"');
    expect(view({ savedState: 'uncertain', failure: 'Cannot confirm.' })).not.toContain('aria-pressed=');
    expect(view({ savedState: 'uncertain', failure: 'Cannot confirm.' })).toContain('s21-save-error');
  });
  it('restores the session lock/sign-in icons while retaining the unavailable saved mark', () => {
    const html = view({ savedState: 'anonymous' });
    expect(html).toContain('s21-icon--lock');
    expect(html).toContain('s21-icon--login');
    expect(html).toContain('Saved state unavailable');
    expect(html).not.toContain('aria-pressed=');
  });
});

describe('Senior QA S-21 source and stipend regressions', () => {
  it('QA-S21-3 uses the same IST calendar date in both provenance lines', () => {
    const html = view({ item: { ...item, verificationStatus: 'verified', source: { ...item.source,
      retrievedAt: '2026-09-02T02:00:00+05:30', verifiedAt: '2026-09-02T02:00:00+05:30' } } });
    expect(html.match(/verified 2 Sept 2026/g)).toHaveLength(2);
    expect(html).toContain('Retrieved 2 Sept 2026');
    expect(html).not.toContain('1 Sept 2026');
  });
  it.each([[49, '₹0.49'], [150, '₹1.50'], [12345, '₹123.45'], [0, '₹0'], [100000, '₹1,000']])(
    'QA-S21-4 preserves exact stipend paise %s', (paise, text) => {
      expect(view({ item: { ...item, stipendMonthlyPaise: Number(paise) } })).toContain(`${text} per month`);
    });
  it('QA-S21-5 discloses the actual destination host, not the untrusted source name', () => {
    const html = view({ item: { ...item, source: { ...item.source, name: 'Official Registry', url: 'https://unrelated.example.test/role' } } });
    expect(html).toContain('(opens unrelated.example.test in a new tab)');
    expect(html).not.toContain('(opens Official Registry');
    expect(html).toMatch(/class="s21-source-host"[^>]*>unrelated\.example\.test</);
  });
  it('QA-S21-6 handles empty names and malformed provenance without implying verification', () => {
    const html = view({ item: { ...item, source: { name: '  ', url: null, retrievedAt: 'bad-date', verifiedAt: 'bad-date' } } });
    expect(html).toContain('Source not provided');
    expect(html).toContain('not verified');
    expect(html).not.toContain('Invalid Date');
    expect(html).not.toContain('; verified not provided');
    const verified = view({ item: { ...item, verificationStatus: 'verified', source: { ...item.source, verifiedAt: 'bad-date' } } });
    expect(verified).not.toContain('Invalid Date');
  });
});
