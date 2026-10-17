import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { PrivacySettingsView, type PrivacySettingsViewProps } from './PrivacySettingsView';
import { loadPrivacySettings } from './privacySettingsState';

const loaded = loadPrivacySettings({ theme: 'system', language: 'en', notifEmail: true, notifSms: false, notifUpdates: false, version: 7, privacy: ['analytics', 'marketing', 'share_partners'].map(kind => ({ kind, enabled: false })) });
const base: PrivacySettingsViewProps = {
  state: loaded, exportState: { phase: 'idle' }, deletion: { stage: 'closed', mobile: '', code: '', typed: '', busy: false, authorityReady: false },
  onNavigate: vi.fn(), onChange: vi.fn(), onReload: vi.fn(), onExport: vi.fn(), onCheckExport: vi.fn(), onDismissExport: vi.fn(),
  onDeleteOpen: vi.fn(), onDeleteClose: vi.fn(), onMobile: vi.fn(), onCode: vi.fn(), onTyped: vi.fn(), onSend: vi.fn(), onVerify: vi.fn(), onDelete: vi.fn(), onStartAgain: vi.fn(),
};
const render = (patch: Partial<PrivacySettingsViewProps> = {}) => renderToStaticMarkup(<PrivacySettingsView {...base} {...patch}/>);

describe('S-19 approved continuation presentation (not conformance evidence)', () => {
  it('uses the frozen heading, named switches and save-on-change copy', () => {
    const html = render();
    expect(html).toContain('Privacy preferences and requests.');
    expect(html.match(/role="switch"/g)).toHaveLength(3);
    for (const label of ['Usage analytics', 'Marketing messages', 'Sharing with partners']) expect(html).toContain(label);
    expect(html).toContain('saves as you change it.');
    expect(html).not.toContain('Save privacy choices');
    expect(html).not.toContain('Saved to your account.');
  });
  it('owns one main with a sibling aside and inert legal notices', () => {
    const html = render();
    expect(html.match(/<main\b/g)).toHaveLength(1);
    expect(html).toMatch(/<\/main><aside/);
    expect(html).toContain('<span>Privacy Notice</span>');
    expect(html).not.toContain('9:41');
    expect(html).not.toContain('<details');
  });
  it('labels pending drafts as saving, not persistence, and disables competing changes', () => {
    const html = render({ state: { ...loaded, phase: 'saving', pendingConsent: { kind: 'analytics', enabled: true } } });
    expect(html).toContain('Saving…');
    expect(html).not.toContain('Saved to your account.');
    expect(html.match(/aria-disabled="true"/g)?.length).toBe(3);
    expect(html).toContain('aria-checked="true"');
  });
  it.each(['loading', 'session', 'forbidden', 'network'] as const)('does not invent settings when %s has no projection', phase => {
    const html = render({ state: { phase } });
    expect(html).not.toContain('role="switch"');
    expect(html).not.toContain('Saved to your account.');
  });
  it('blocks version-conflict switches and exposes an explicit Reload action', () => {
    const html = render({ state: { ...loaded, phase: 'conflict' } });
    expect(html).toContain('Nothing was overwritten. Reload to see the current choices.');
    expect(html).toContain('>Reload</button>');
    expect(html.match(/aria-disabled="true"/g)?.length).toBe(3);
  });
  it.each(['pending', 'processing', 'complete', 'failed', 'cancelled'] as const)('shows the actual %s export state without invented delivery or cancellation', status => {
    const html = render({ exportState: { phase: 'tracked', request: { requestId: 'a'.repeat(32), status } } });
    expect(html).toContain(`Status: ${status}`);
    expect(html).not.toContain('registered email for the secure download');
    expect(html).not.toContain('Cancel export');
    if (status === 'complete') expect(html).toContain('no download or delivery step');
  });
  it('shows status-check failure without falsely overwriting the last server status', () => {
    const html = render({ exportState: { phase: 'check-failed', request: { requestId: 'a'.repeat(32), status: 'processing' } } });
    expect(html).toContain('Status check failed.');
    expect(html).toContain('last confirmed status: processing');
    expect(html).not.toContain('The export request failed.');
  });
  it.each(['mobile', 'code', 'confirm'] as const)('replaces the overview with focused %s deletion substate', stage => {
    const html = render({ deletion: { ...base.deletion, stage } });
    expect(html).not.toContain('role="switch"');
    expect(html).not.toContain('Request a copy of my data</b>');
    expect(html.match(/<h1\b/g)).toHaveLength(1);
    expect(html).toContain('tabindex="-1"');
    expect(html).toContain('aria-current="step"');
    expect(html).not.toContain('123456 verifies');
  });
  it('keeps deletion disabled until exact DELETE plus server authority, never a typed string alone', () => {
    for (const [typed, authorityReady, busy] of [['DELETE', false, false], ['delete', true, false], ['DELETE ', true, false], ['DELETE', true, true]] as const) {
      const html = render({ deletion: { ...base.deletion, stage: 'confirm', typed, authorityReady, busy } });
      expect(html).toMatch(/<button type="submit" class="v321-privacy__button is-danger" disabled=""/);
    }
    const html = render({ deletion: { ...base.deletion, stage: 'confirm', typed: 'DELETE', authorityReady: true } });
    expect(html).toMatch(/<button type="submit" class="v321-privacy__button is-danger">/);
  });
  it('offers useful recovery when an authority read fails instead of preserving a verified capability', () => {
    const html = render({ deletion: { ...base.deletion, stage: 'mobile', mobile: '9999999999', error: 'authority', authorityReady: false } });
    expect(html).toContain('Re-authentication state is unavailable.');
    expect(html).toContain('Try again');
    expect(html).toContain('Registered mobile number');
    expect(html).not.toContain('Type DELETE to continue');
    expect(html).toMatch(/<button type="submit" class="v321-privacy__button is-primary" disabled=""/);
  });
  it('renders the session component with the approved centered error frame and semantic heading', () => {
    const html = render({ state: { phase: 'session' } });
    expect(html).toContain('class="v321-privacy__error"');
    expect(html).toContain('<h2>Your session ended.</h2>');
    expect(html).toContain('class="v321-privacy__error-icon" aria-hidden="true"');
    expect(html).toContain('class="v321-privacy__error-actions"');
    expect(html).toContain('class="v321-privacy__button is-primary"');
    expect(html).toContain('Sign in again');
    expect(html).toContain('Each choice is separate and off unless you turn it on.');
    expect(html).toContain('y="10.5" width="14" height="10"');
  });
  it('places a rejected recovery-start notice after its field, before the Send code action', () => {
    const html = render({ deletion: { ...base.deletion, stage: 'mobile', error: 'start' } });
    expect(html.indexOf('Registered mobile number')).toBeLessThan(html.indexOf('Could not start re-authentication.'));
    expect(html.indexOf('Could not start re-authentication.')).toBeLessThan(html.indexOf('Send code'));
  });
  it('keeps the code mismatch inline with the code field instead of inserting a separate card above it', () => {
    const html = render({ deletion: { ...base.deletion, stage: 'code', error: 'code' } });
    expect(html).toContain('class="v321-privacy__field-error"');
    expect(html).toContain('<span>That code did not match.</span>');
    expect(html.indexOf('Six-digit code')).toBeLessThan(html.indexOf('That code did not match.'));
  });
  it('uses the approved warning and success presentation without changing status semantics', () => {
    expect(render({ state: { ...loaded, phase: 'conflict' } })).toContain('v321-privacy__notice is-warning is-warn');
    expect(render({ exportState: { phase: 'tracked', request: { requestId: 'a'.repeat(32), status: 'complete' } } })).toContain('v321-privacy__notice is-ok');
  });
  it('uses the frozen warning tone for a deletion conflict without altering its specific notice', () => {
    const html = render({ deletion: { ...base.deletion, stage: 'confirm', error: 'conflict', authorityReady: true } });
    expect(html).toContain('v321-privacy__notice is-warning is-warn');
    expect(html).toContain('Something changed on your account while this was processing.');
    expect(html).toContain('Nothing was deleted. Wait a moment and try again.');
  });
});
