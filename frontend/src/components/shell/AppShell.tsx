import type { ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { railItems, splitBottomNav } from './navItems';
import type { ThemeMode } from '../../hooks/useTheme';

/**
 * Option J "Chambers" app shell (SAATHI-343): desktop chambers rail + top
 * command bar + Ask command spine, and a mobile bottom nav with a central Ask.
 * Wraps the existing S-01..S-99 routes (children) without changing routing.
 * Theme is owned by App (single NyayOne device-preference source) and passed in.
 */
export function AppShell({
  children,
  theme,
  toggleTheme,
}: {
  children: ReactNode;
  theme: ThemeMode;
  toggleTheme: () => void;
}) {
  const location = useLocation();
  // S-11 now owns its Revision L profile shell; all other continuation routes stay unchanged.
  if (location.pathname === '/s-11') {
    return <main className="ls-v34-content" id="main-content">{children}</main>;
  }
  // S-12 owns its Revision L completion shell; incomplete/loading authority is unchanged.
  if (location.pathname === '/s-12') {
    return <main className="ls-v34-content" id="main-content">{children}</main>;
  }
  // S-13 owns the Revision L resume shell; other continuation routes are unchanged.
  if (location.pathname === '/s-13') {
    return <main className="ls-v34-content" id="main-content">{children}</main>;
  }
  // v3.4 S-01…S-10 own their responsive auth/app shell. Rendering the legacy
  // global shell around them would duplicate navigation and invalidate the
  // approved 900px single-shell contract.
  if (/^\/s-(?:0[34589])$/.test(location.pathname)) {
    return <div className="ls-v34-content">{children}</div>;
  }
  if (/^\/s-(?:0[1-9]|10)$/.test(location.pathname)) {
    return <main className="ls-v34-content" id="main-content">{children}</main>;
  }
  if (/^\/s-(?:1[1-9]|2[0-6])$/.test(location.pathname)) {
    return (
      <V34ContinuationShell pathname={location.pathname} search={location.search} theme={theme} toggleTheme={toggleTheme}>
        {children}
      </V34ContinuationShell>
    );
  }
  return (
    <div className="ls-shell">
      {/* Desktop chambers rail */}
      <nav className="ls-rail" aria-label="Primary">
        <div className="ls-rail__brand">
          <span className="ls-rail__mark" aria-hidden>N1</span>
          <span className="ls-rail__word">Nyay<span className="brand-accent">One</span></span>
        </div>
        <ul className="ls-rail__list">
          {railItems.map((it) => (
            <li key={it.id}>
              <NavLink to={it.to} className="ls-rail__link">
                <span className="ls-rail__glyph" aria-hidden>{it.glyph}</span>
                <span>{it.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <div className="ls-main">
        {/* Top command bar */}
        <header className="ls-topbar">
          <button type="button" className="ls-ask" aria-label="Ask NyayOne">
            <span className="ls-ask__glyph" aria-hidden>⌕</span>
            <span className="ls-ask__text">Ask a question or search…</span>
          </button>
          <div className="ls-topbar__actions">
            <button
              type="button"
              className="theme-toggle"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            >
              {theme === 'dark' ? 'Light' : 'Dark'}
            </button>
          </div>
        </header>

        <main className="ls-content" id="main-content">{children}</main>

        {/* Mobile bottom nav with central Ask spine. splitBottomNav renders every
            configured item (3 left, 2 right) so none is dropped. */}
        <nav className="ls-bnav" aria-label="Primary mobile">
          {splitBottomNav().left.map((it) => (
            <NavLink key={it.id} to={it.to} className="ls-bnav__item">
              <span className="ls-bnav__glyph" aria-hidden>{it.glyph}</span>
              <span className="ls-bnav__label">{it.label}</span>
            </NavLink>
          ))}
          <button type="button" className="ls-bnav__ask" aria-label="Ask NyayOne">
            <span aria-hidden>⌕</span>
          </button>
          {splitBottomNav().right.map((it) => (
            <NavLink key={it.id} to={it.to} className="ls-bnav__item">
              <span className="ls-bnav__glyph" aria-hidden>{it.glyph}</span>
              <span className="ls-bnav__label">{it.label}</span>
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}

const V34_BACK: Record<string, string> = {
  '/s-11': '/s-10', '/s-12': '/s-11', '/s-13': '/s-14', '/s-14': '/s-07',
  '/s-15': '/s-14', '/s-16': '/s-14', '/s-17': '/s-14', '/s-18': '/s-17',
  '/s-19': '/s-17', '/s-20': '/s-14', '/s-21': '/s-20', '/s-22': '/s-21',
  '/s-23': '/s-22', '/s-24': '/s-20', '/s-25': '/s-20', '/s-26': '/s-25',
};

const V34_LABELS: Record<string, string> = {
  '/s-11': 'PREFERENCES', '/s-12': 'SETUP COMPLETE', '/s-13': 'RESUME SETUP',
  '/s-14': 'STUDENT HOME', '/s-15': 'EMAIL VERIFICATION', '/s-16': 'RESTRICTED ACCESS',
  '/s-17': 'PROFILE', '/s-18': 'SETTINGS', '/s-19': 'PRIVACY & CONSENT',
  '/s-20': 'INTERNSHIPS', '/s-21': 'ROLE DETAIL', '/s-22': 'APPLICATION',
  '/s-23': 'SUBMITTED', '/s-24': 'APPLICATION TRACKER', '/s-25': 'SAVED', '/s-26': 'SAVED · EMPTY',
};

const V34_MOBILE_NAV = [
  { label: 'Home', to: '/s-14', icon: 'home' },
  { label: 'Calendar', to: '/s-90', icon: 'calendar' },
  { label: 'Prep', to: '/s-55', icon: 'prep' },
  { label: 'Career', to: '/s-20', icon: 'career' },
  { label: 'Community', to: '/s-50', icon: 'community' },
] as const;

function V34ShellIcon({ name, size = 21 }: { name: string; size?: number }) {
  const line = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  return (
    <svg className={`v34c-icon v34c-icon--${name}`} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" tabIndex={-1} focusable="false">
      {name === 'back' && <path d="m15 5-7 7 7 7" {...line}/>}
      {name === 'sun' && <><circle cx="12" cy="12" r="4" {...line}/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" {...line}/></>}
      {name === 'moon' && <path d="M20 15A8.5 8.5 0 0 1 9 4a9 9 0 1 0 11 11Z" {...line}/>}
      {name === 'home' && <><path d="m3 11 9-7 9 7" {...line}/><path d="M5 10v10h14V10M9 20v-6h6v6" {...line}/></>}
      {name === 'calendar' && <><rect x="3" y="5" width="18" height="16" rx="2" {...line}/><path d="M7 3v4m10-4v4M3 10h18" {...line}/></>}
      {name === 'prep' && <><circle cx="12" cy="12" r="9" {...line}/><circle cx="12" cy="12" r="4" {...line}/><path d="M12 3v5m9 4h-5m-4 9v-5M3 12h5" {...line}/></>}
      {name === 'career' && <><rect x="3" y="7" width="18" height="13" rx="2" {...line}/><path d="M9 7V4h6v3m-3 4v5m-2-2h4" {...line}/></>}
      {name === 'community' && <><path d="M4 5h16v11H9l-5 4V5Z" {...line}/><path d="M8 9h8m-8 3h5" {...line}/></>}
      {name === 'research' && <><circle cx="10" cy="10" r="6" {...line}/><path d="m14.5 14.5 5 5M10 7v6m-3-3h6" {...line}/></>}
      {name === 'internships' && <><rect x="3" y="7" width="18" height="13" rx="2" {...line}/><path d="M9 7V4h6v3m-3 4v5m-2-2h4" {...line}/></>}
      {name === 'tutors' && <><circle cx="9" cy="8" r="4" {...line}/><path d="M2.5 21c.5-4.3 3-6.5 6.5-6.5 2.2 0 4 .8 5.1 2.2M18 13v8m-4-4h8" {...line}/></>}
      {name === 'schools' && <><path d="M3 21h18M5 21V9l7-5 7 5v12M9 12h2m2 0h2m-6 4h2m2 0h2" {...line}/></>}
      {name === 'moot' && <><path d="M12 3v17M7 6h10M5 9l-3 6h6L5 9Zm14 0-3 6h6l-3-6ZM8 21h8" {...line}/></>}
      {name === 'digests' && <><path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2V4Z" {...line}/><path d="M9 8h6m-6 4h6m-6 4h4" {...line}/></>}
      {name === 'exam' && <><path d="m4 17-.8 3.8L7 20l11-11-3-3L4 17Z" {...line}/><path d="m13.5 7.5 3 3" {...line}/></>}
      {name === 'clinical' && <><circle cx="12" cy="12" r="9" {...line}/><path d="M12 7v10M7 12h10" {...line}/></>}
      {name === 'profile' && <><circle cx="12" cy="8" r="4" {...line}/><path d="M4 21c.8-4.2 3.6-6.5 8-6.5s7.2 2.3 8 6.5" {...line}/></>}
    </svg>
  );
}

function V34Brand() {
  return (
    <NavLink to="/s-14" className="v34c-brand" aria-label="NyayOne home">
      <img className="v34c-brand__mark" src="/brand/nyayone-mark.svg" alt="" aria-hidden="true" draggable="false"/>
      <span><b>NyayOne</b><small>STUDENT MODULE</small></span>
    </NavLink>
  );
}

function V34ContinuationShell({
  children,
  pathname,
  search,
  theme,
  toggleTheme,
}: {
  children: ReactNode;
  pathname: string;
  search: string;
  theme: ThemeMode;
  toggleTheme: () => void;
}) {
  const screenId = pathname.slice(1).toUpperCase();
  const setup = /^\/s-1[1-3]$/.test(pathname);
  const listing = new URLSearchParams(search).get('listing');
  const staticBack = V34_BACK[pathname] ?? '/s-14';
  const back = listing && (pathname === '/s-22' || pathname === '/s-23')
    ? `${pathname === '/s-22' ? '/s-21' : '/s-22'}?listing=${encodeURIComponent(listing)}`
    : staticBack;
  return (
    <div className={`v34-screen v34-screen--continuation${setup ? ' v34-screen--setup' : ''}`} data-v34-screen={screenId}>
      <aside className="v34c-rail" aria-label={setup ? 'Profile setup' : 'Primary'}>
        <V34Brand/>
        {setup ? (
          <div className="v34c-setupsteps" aria-label="Profile setup steps">
            {[
              ['1', 'Personal', '/s-10'], ['2', 'Academic', '/s-10'], ['3', 'Preferences', '/s-11'],
            ].map(([n, label, to], index) => (
              <NavLink key={`${n}-${label}`} to={to} className={pathname === '/s-11' && index === 2 ? 'is-on' : ''}>
                <b>{n}</b><span><strong>{label}</strong><small>{index < 2 ? 'Saved' : 'Current step'}</small></span>
              </NavLink>
            ))}
            <div className="v34-rule"/>
            <p>Your private academic record stays separate from public profile information.</p>
          </div>
        ) : (
          <nav className="v34c-railnav" aria-label="Student module">
            {railItems.map((item) => (
              <NavLink key={item.id} to={item.to} className={({ isActive }) => isActive ? 'is-on' : undefined}>
                <V34ShellIcon name={item.id}/><span>{item.label}</span>
              </NavLink>
            ))}
          </nav>
        )}
        <span className="v34-grow"/>
        <p className="v34c-railnote">TIER 2 · Private fields are never shown publicly.</p>
      </aside>

      <div className="v34-pane">
        <div className="v34-status" aria-hidden><span>9:41</span><span>100</span></div>
        <header className="v34c-head">
          <NavLink to={back} className="v34c-back" aria-label={`Back from ${screenId}`}>
            <V34ShellIcon name="back" size={18}/><span>Back</span>
          </NavLink>
          <span className="v34c-screenid">{screenId} · {V34_LABELS[pathname] ?? 'STUDENT'}</span>
          <span className="v34-grow"/>
          <V34Brand/>
          <button type="button" className="v34-theme" onClick={toggleTheme} aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}>
            <V34ShellIcon name={theme === 'dark' ? 'moon' : 'sun'}/>
          </button>
        </header>
        <main className="v34c-content" id="main-content">{children}</main>
        {!setup && (
          <nav className="v34c-tabbar" aria-label="Primary mobile">
            {V34_MOBILE_NAV.map((item) => (
              <NavLink key={item.label} to={item.to} className={({ isActive }) => isActive ? 'is-on' : undefined}>
                <V34ShellIcon name={item.icon}/><span>{item.label}</span>
              </NavLink>
            ))}
          </nav>
        )}
        <NavLink className="v34c-ask" to="/s-36" aria-label="Ask a legal research question" data-tip="Ask NyayOne">
          <V34ShellIcon name="research" size={25}/>
        </NavLink>
      </div>
    </div>
  );
}
