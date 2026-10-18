import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { S20BrowseView, type S20BrowseViewProps } from './S20BrowseView';
import { AppShell } from '../../../components/shell/AppShell';
import { MemoryRouter } from 'react-router-dom';

const props: S20BrowseViewProps = { phase: 'results', items: [], total: 0, page: 1, query: '', stipend: 'any', verifiedOnly: false, saved: [], savedPhase: 'ready', pendingId: null, saveError: null, notice: '', statusCode: null, onNavigate: vi.fn(), onQuery: vi.fn(), onStipend: vi.fn(), onVerified: vi.fn(), onPage: vi.fn(), onClear: vi.fn(), onRetry: vi.fn(async () => undefined), onRetrySaved: vi.fn(async () => undefined), onSave: vi.fn(async () => undefined) };
const listing = { id: 'role', role: 'Research intern', org: 'Synthetic chambers', location: 'Delhi', stipendMonthlyPaise: null, verificationStatus: 'unverified' as const, deadline: '8 Jul 2027', eligibility: '', tags: [], description: '', source: { name: 'Synthetic', url: null, retrievedAt: null, verifiedAt: null } };
const render = (extra: Partial<S20BrowseViewProps> = {}) => renderToStaticMarkup(<S20BrowseView {...props} {...extra}/>);
describe('S-20 Revision L composition and honest states', () => {
  it('keeps the frozen aside eyebrow labels separate from page headings', () => {
    const html = render({ items: [listing], total: 1 });
    expect(html).toContain('<div class="s20-eyebrow" id="S-20-saved">Saved</div>');
    expect(html).toContain('<div class="s20-eyebrow" id="S-20-verification">About verification</div>');
    expect(html.match(/<h1\b/g)).toHaveLength(1);
    expect(html).not.toContain('<h2');
  });
  it('has page-local search, stipend disclosure, title action and no redundant View row', () => {
    const html = render({ items: [listing], total: 1 });
    expect(html).toContain('Browse internships.'); expect(html).toContain('Search this page');
    expect(html).toContain('Filters the listings already loaded on this page.');
    expect(html).toContain('Stipend (this page)'); expect(html).toContain('Listing check (server)');
    expect(html).toContain('Stipend not stated'); expect(html).toContain('Unverified listing');
    expect(html).not.toContain('>View<'); expect(html).not.toContain('3 saved listings');
    expect(html).not.toContain('AN');
  });
  it('hides unknown save marks and provides a retry when only saved data is unavailable', () => {
    const html = render({ items: [listing], total: 1, savedPhase: 'error' });
    expect(html).toContain('Your saved list did not load.');
    expect(html).toContain('saved state unavailable'); expect(html).not.toContain('aria-label="Save Research intern" aria-pressed="false"');
  });
  it.each(['loading', 'error', 'offline'] as const)('does not claim an empty catalogue during %s', phase => {
    const html = render({ phase, savedPhase: 'loading' }); expect(html).not.toContain('No internships are listed right now.');
    expect(html).not.toContain('0 saved listings');
  });
  it('distinguishes server empty, verified empty and local no-match', () => {
    expect(render()).toContain('No internships are listed right now.');
    expect(render({ verifiedOnly: true })).toContain('No verified listings right now.');
    expect(render({ total: 1, query: 'missing' })).toContain('No matching listings');
  });
  it.each(['/s-20', '/S-20/', '/s-20?x=1#y'])('owns one main, sibling aside and no legacy chrome for %s', path => {
    const html = renderToStaticMarkup(<MemoryRouter initialEntries={[path]}><AppShell theme="light" toggleTheme={vi.fn()}><S20BrowseView {...props}/></AppShell></MemoryRouter>);
    expect(html.match(/<main\b/g)).toHaveLength(1);
    expect(html).not.toContain('v34-screen--continuation'); expect(html).not.toContain('ls-bnav');
    expect(html.indexOf('</main>')).toBeLessThan(html.indexOf('<aside'));
  });
});
