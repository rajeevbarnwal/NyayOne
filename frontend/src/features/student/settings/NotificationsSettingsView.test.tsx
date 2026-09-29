import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AppShell } from '../../../components/shell/AppShell';
import { NotificationsSettingsView } from './NotificationsSettingsView';
import { confirmedSettings, type SettingsPhase } from './notificationSettingsState';

const loaded = confirmedSettings({ theme: 'system', language: 'en', notifEmail: true, notifSms: false, notifUpdates: false, privacy: [], version: 7 });
const render = (phase: SettingsPhase = 'loaded') => renderToStaticMarkup(<MemoryRouter initialEntries={['/s-18']}><AppShell theme="light" toggleTheme={vi.fn()}><NotificationsSettingsView state={{ ...loaded, phase }} onChange={vi.fn()} onReload={vi.fn()} onNavigate={vi.fn()} /></AppShell></MemoryRouter>);
describe('S-18 approved continuation presentation', () => {
  it('renders the approved heading and three labelled switches', () => {
    const html = render();
    expect(html).toContain('Notifications and appearance.');
    expect(html.match(/role="switch"/g)).toHaveLength(3);
    expect(html).toContain('Each change saves to your account as you make it.');
    expect(html).not.toContain('Saved to your account.</p>');
    expect(html).not.toContain('Save changes');
  });
  it('keeps Hindi unavailable and discloses that Dark stores a preference, not a completed dark UI', () => {
    const html = render();
    expect(html).toContain('Hindi interface is not available yet');
    expect(html).toContain('Coming soon');
    expect(html).toContain('choosing Dark saves the preference for later');
  });
  it.each(['loading', 'saving', 'saved', 'invalid', 'conflict', 'network', 'forbidden', 'session'] as SettingsPhase[])('labels the %s state explicitly', phase => {
    expect(render(phase)).toContain(`data-settings-state="${phase}"`);
  });
  it('uses one main and sibling complementary landmark without legacy chrome', () => {
    const html = renderToStaticMarkup(<MemoryRouter initialEntries={['/S-18/?test=1#state']}><AppShell theme="light" toggleTheme={vi.fn()}><NotificationsSettingsView state={loaded} onChange={vi.fn()} onReload={vi.fn()} onNavigate={vi.fn()} /></AppShell></MemoryRouter>);
    expect(html.match(/<main\b/g)).toHaveLength(1);
    expect(html).toMatch(/<\/main><aside/);
    expect(html).not.toContain('v34-screen--continuation');
  });
  it('keeps legal notices inert, with privacy navigation separately labelled', () => {
    const html = render();
    expect(html).toContain('<span>Privacy Notice</span>');
    expect(html).toContain('Privacy preferences and requests');
  });
  it('retains the prototype nested 20px button icon wrapper around its 18px glyph', () => {
    expect(render()).toMatch(/class="v321-settings__button-icon" aria-hidden="true"><svg width="18" height="18"/);
  });
  it.each(['session', 'forbidden'] as SettingsPhase[])('uses the approved decorative lock tile and action frame for %s', phase => {
    const html = render(phase);
    expect(html).toContain('class="v321-settings__error-icon" aria-hidden="true"');
    expect(html).toContain('class="v321-settings__error-actions"');
    expect(html).toMatch(/v321-settings__error-actions[\s\S]*v321-settings__button-icon/);
    if (phase === 'session') expect(html).toContain('v321-settings__button is-primary');
  });
  it.each(['conflict', 'network'] as SettingsPhase[])('keeps the %s notice in the existing live-region slot without an empty flex sibling', phase => {
    const html = render(phase);
    expect(html).toMatch(/<div aria-live="polite" aria-atomic="true"><div class="v321-settings__notice/);
    expect(html).not.toContain('<div aria-live="polite" aria-atomic="true"></div><div class="v321-settings__notice');
  });
  it('uses the frozen continuation warning paths in the network error notice', () => {
    const html = render('network');
    expect(html).toContain('d="M12 4 21 20H3z"');
    expect(html).toContain('d="M12 10v4.5M12 17.2v.3"');
    expect(html).not.toContain('d="M12 3 2 21h20Z"');
  });
});
