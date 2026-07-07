import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { railItems, splitBottomNav } from './navItems';
import type { ThemeMode } from '../../hooks/useTheme';

/**
 * Option J "Chambers" app shell (SAATHI-343): desktop chambers rail + top
 * command bar + Ask command spine, and a mobile bottom nav with a central Ask.
 * Wraps the existing S-01..S-99 routes (children) without changing routing.
 * Theme is owned by App (single ls-theme source) and passed in.
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
  return (
    <div className="ls-shell">
      {/* Desktop chambers rail */}
      <nav className="ls-rail" aria-label="Primary">
        <div className="ls-rail__brand">
          <span className="ls-rail__mark" aria-hidden>LS</span>
          <span className="ls-rail__word">Legal<span className="brand-accent">Saathi</span></span>
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
          <button type="button" className="ls-ask" aria-label="Ask LegalSaathi">
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
          <button type="button" className="ls-bnav__ask" aria-label="Ask LegalSaathi">
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
