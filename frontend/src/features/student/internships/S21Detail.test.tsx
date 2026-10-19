import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AuthProvider, type AuthState } from '../../../app/authContext';
import { AppShell } from '../../../components/shell/AppShell';
import { InternshipDetail } from './InternshipScreens';

const auth: AuthState = { isAuthenticated: true, userId: 'synthetic', roles: ['student'], studentVerification: 'verified', lawyerVerification: 'draft', filingRole: null, isMinor: false };
const item = { id: 'synthetic-role', role: 'Research intern', org: 'Synthetic chambers', location: 'Delhi', stipendMonthlyPaise: null, verificationStatus: 'unverified', deadline: '8 Jul 2027', eligibility: 'Students', tags: ['Research'], description: 'Research support', source: { name: 'Synthetic source', url: 'https://example.test/role', retrievedAt: null, verifiedAt: null } };
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
