import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from './AppShell';
import { ANONYMOUS_AUTH, AuthProvider, type StudentSessionPhase } from '../../app/authContext';
import { isProtectedStudentPath, StudentRouteGuard } from '../../app/StudentRouteGuard';

function renderShell(url: string, child = <p>Screen-owned content</p>) {
  return renderToStaticMarkup(
    <MemoryRouter initialEntries={[url]}>
      <AppShell theme="light" toggleTheme={vi.fn()}>{child}</AppShell>
    </MemoryRouter>,
  );
}

const paths = Array.from({ length: 26 }, (_, i) => `/s-${String(i + 1).padStart(2, '0')}`);
const variants = [
  (p: string) => p,
  (p: string) => p.toUpperCase(),
  (p: string) => `${p}/`,
  (p: string) => `${p.toUpperCase()}///`,
  (p: string) => `${p}?section=academic&listing=synthetic%2Frole#details`,
  (p: string) => `${p.toUpperCase()}/?section=academic&listing=synthetic%2Frole#details`,
];

describe('PR4 route-aware shell selection', () => {
  for (const path of paths) {
    it.each(variants.map(make => make(path)))('%s has the same shell as its canonical router match', url => {
      // Query-dependent continuation Back links retain their original semantics.
      const suffix = url.includes('?') ? url.slice(url.indexOf('?')) : '';
      const html = renderShell(url);
      expect(html).toBe(renderShell(path + suffix));
      expect(html).not.toContain('class="ls-shell"');
      expect(html).not.toContain('class="ls-bnav"');
      expect(html).not.toContain('aria-label="Ask NyayOne"');
    });
  }

  it.each(['/s-03', '/s-04', '/s-05', '/s-08', '/s-09'])('%s does not add a nested main around screen-owned main', path => {
    const html = renderShell(path.toUpperCase() + '/', <main>Screen-owned main</main>);
    expect(html.match(/<main\b/g)).toHaveLength(1);
    expect(html).toContain('<div class="ls-v34-content"><main>');
  });

  it.each(['/s-01', '/s-02', '/s-06', '/s-07', '/s-10', '/s-11', '/s-12', '/s-13', '/s-14', '/s-15', '/s-16', '/s-17'])(
    '%s keeps the standalone main and no continuation wrapper', path => {
      const html = renderShell(path.toUpperCase() + '/');
      expect(html.match(/<main\b/g)).toHaveLength(1);
      expect(html).toContain('<main class="ls-v34-content" id="main-content">');
      expect(html).not.toContain('v34-screen--continuation');
    },
  );

  it('uses canonical continuation labels and listing-aware Back without rewriting the URL', () => {
    function LocationProbe() {
      const location = useLocation();
      return <output>{location.pathname + location.search + location.hash}</output>;
    }
    const url = '/S-22/?listing=synthetic%2Frole#application';
    const html = renderShell(url, <Routes><Route path="/s-22" element={<LocationProbe />} /></Routes>);
    expect(html).toContain(`>${url}</output>`);
    expect(html).toContain('href="/s-21?listing=synthetic%2Frole"');
    expect(html).toContain('data-v34-screen="S-22"');
    expect(html).toContain('APPLICATION');
  });

  it.each(['/s-120', '/s-12/child', '/s-12-extra', '/s-00', '/s-27', '/s-90', '/__tokens', '/unknown'])(
    '%s does not acquire another screen’s shell via a prefix match', url => {
      expect(renderShell(url)).toContain('class="ls-shell"');
    },
  );

  for (const phase of ['pending', 'unavailable', 'anonymous', 'authenticated'] as StudentSessionPhase[]) {
    it.each(['/s-12', '/S-12/', '/S-17///?panel=email#code'])(
      `%s remains private and does not mount the shell for ${phase} without student authority`, url => {
        const pathname = url.split(/[?#]/)[0];
        expect(isProtectedStudentPath(pathname)).toBe(true);
        const rendered = vi.fn();
        function PrivateChild() { rendered(); return <div>Private canary</div>; }
        const html = renderToStaticMarkup(
          <AuthProvider value={ANONYMOUS_AUTH} studentSession={{ phase, refresh: vi.fn(async () => undefined) }}>
            <MemoryRouter initialEntries={[url]}>
              <StudentRouteGuard><AppShell theme="light" toggleTheme={vi.fn()}><PrivateChild /></AppShell></StudentRouteGuard>
            </MemoryRouter>
          </AuthProvider>,
        );
        expect(rendered).not.toHaveBeenCalled();
        expect(html).not.toContain('Private canary');
        expect(html).not.toContain('ls-shell');
      },
    );
  }
});
