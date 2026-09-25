import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import type { EmailIdentity } from '../lib/profileApi';
import * as profileScreens from './ProfileScreens';

const SOURCE_PATH = join(process.cwd(), 'src/features/student/profile/ProfileScreens.tsx');

function render(component: ComponentType<Record<string, unknown>>, props: Record<string, unknown>): string {
  return renderToStaticMarkup(createElement(MemoryRouter, null, createElement(component, props)));
}

const PENDING: EmailIdentity = {
  id: '00000000-0000-4000-8000-0000000000a1',
  emailMasked: 'p•••••@example.edu',
  state: 'pending',
  isPrimary: false,
  verification: { status: 'active', expiresInSeconds: 250, resendInSeconds: 0, attemptsLeft: 3 },
};
const VERIFIED: EmailIdentity = {
  id: '00000000-0000-4000-8000-0000000000b2',
  emailMasked: 'v•••••@example.edu',
  state: 'verified',
  isPrimary: false,
  verification: { status: 'none', expiresInSeconds: null, resendInSeconds: null, attemptsLeft: null },
};
const PRIMARY: EmailIdentity = { ...VERIFIED, id: '00000000-0000-4000-8000-0000000000c3', emailMasked: 'm•••••@example.edu', isPrimary: true };

function panel(overrides: Record<string, unknown> = {}): string {
  const view = profileScreens.EmailIdentityPanelView as unknown as ComponentType<Record<string, unknown>>;
  return render(view, {
    channelEnabled: true,
    maxIdentities: 3,
    identities: [PENDING, VERIFIED, PRIMARY],
    draftEmail: '',
    draftCodes: {},
    error: null,
    errorTarget: null,
    busy: false,
    onDraftEmail: vi.fn(),
    onAdd: vi.fn(),
    onDraftCode: vi.fn(),
    onVerify: vi.fn(),
    onResend: vi.fn(),
    onRemove: vi.fn(),
    onPrimary: vi.fn(),
    ...overrides,
  });
}

describe('NYAY-12 S-17 sign-in email panel', () => {
  it('renders an accessible region with labelled add form and masked addresses only', () => {
    const markup = panel();
    expect(markup).toMatch(/<section(?=[^>]*aria-labelledby="profile-email-identity-title")(?=[^>]*data-testid="profile-email-identities")[^>]*>/u);
    expect(markup).toContain('id="profile-email-identity-title"');
    expect(markup).toMatch(/<input(?=[^>]*id="profile-email-identity-input")(?=[^>]*type="email")(?=[^>]*inputMode="email")(?=[^>]*autoComplete="email")[^>]*>/u);
    expect(markup).toMatch(/<label[^>]*for="profile-email-identity-input"/u);
    expect(markup).toContain('p•••••@example.edu');
    expect(markup).toContain('v•••••@example.edu');
    expect(markup).toContain('m•••••@example.edu');
    expect(markup).not.toMatch(/[a-z0-9.]+@example\.edu/u);
  });

  it('exposes verify, resend, remove and make-primary controls with accessible names and correct enablement', () => {
    const markup = panel();
    expect(markup).toMatch(/<input(?=[^>]*id="profile-email-identity-code-00000000-0000-4000-8000-0000000000a1")(?=[^>]*autoComplete="one-time-code")(?=[^>]*inputMode="numeric")(?=[^>]*maxLength="6")[^>]*>/u);
    expect(markup).toContain('aria-label="Verify email p•••••@example.edu"');
    expect(markup).toContain('aria-label="Resend code to p•••••@example.edu"');
    expect(markup).toContain('aria-label="Remove email p•••••@example.edu"');
    expect(markup).toContain('aria-label="Remove email v•••••@example.edu"');
    expect(markup).toMatch(/<button(?=[^>]*aria-label="Make primary sign-in email v•••••@example.edu")(?![^>]*disabled)[^>]*>/u);
    expect(markup).not.toContain('aria-label="Make primary sign-in email p•••••@example.edu"');
    expect(markup).not.toContain('aria-label="Make primary sign-in email m•••••@example.edu"');
    expect(markup).toContain('data-testid="profile-email-identity-primary-badge"');
    expect(markup).not.toContain('aria-label="Verify email v•••••@example.edu"');
  });

  it('preserves the typed address and focuses an accessible error on failure', () => {
    const markup = panel({ draftEmail: 'draft@example.edu', error: 'That address could not be added right now.', errorTarget: 'add' });
    expect(markup).toMatch(/<input(?=[^>]*id="profile-email-identity-input")(?=[^>]*value="draft@example.edu")(?=[^>]*aria-invalid="true")(?=[^>]*aria-describedby="profile-email-identity-input-error")[^>]*>/u);
    expect(markup).toMatch(/<[a-z]+(?=[^>]*id="profile-email-identity-input-error")(?=[^>]*role="alert")(?=[^>]*tab[iI]ndex="-1")[^>]*>That address could not be added right now\./u);
    const codeError = panel({ draftCodes: { [PENDING.id]: '123' }, error: 'Enter all six digits.', errorTarget: PENDING.id });
    expect(codeError).toMatch(new RegExp(`<input(?=[^>]*id="profile-email-identity-code-${PENDING.id}")(?=[^>]*value="123")(?=[^>]*aria-invalid="true")[^>]*>`, 'u'));
    expect(codeError).toContain(`id="profile-email-identity-code-${PENDING.id}-error"`);
  });

  it('reflects server limits and channel availability without client authority', () => {
    const full = panel();
    expect(full).toMatch(/<button(?=[^>]*aria-label="Add email")(?=[^>]*disabled)[^>]*>/u);
    const open = panel({ identities: [PRIMARY] });
    expect(open).toMatch(/<button(?=[^>]*aria-label="Add email")(?![^>]*disabled)[^>]*>/u);
    const disabledChannel = panel({ channelEnabled: false, identities: [PRIMARY] });
    expect(disabledChannel).toContain('data-testid="profile-email-identity-channel-status"');
    expect(disabledChannel).toMatch(/not enabled yet/iu);
    const busy = panel({ busy: true, identities: [PRIMARY] });
    expect(busy).toMatch(/<button(?=[^>]*aria-label="Add email")(?=[^>]*disabled)[^>]*>/u);
  });

  it('mounts the panel on S-17 from server state and stays storage-free', () => {
    const source = readFileSync(SOURCE_PATH, 'utf8');
    const profileView = source.slice(source.indexOf('export function ProfileView'), source.length);
    expect(profileView).toContain('<EmailIdentityPanel');
    expect(source).toContain('useEmailIdentities(expanded)');
    const container = source.slice(source.indexOf('export function EmailIdentityPanel('), source.indexOf('export function ProfileView'));
    // Collapsed by default: S-17 issues no identity read until the owner opens the section,
    // and the entry point lives inside an existing row so S-17 gains no vertical height.
    expect(container).toContain('if (!expanded) return null;');
    expect(profileView).toContain('aria-expanded={emailIdentitiesOpen}');
    expect(profileView).toContain('data-testid="profile-email-identity-disclosure"');
    expect(profileView).toContain("aria-label={emailIdentitiesOpen ? 'Hide sign-in emails' : 'Manage sign-in emails'}");
    expect(profileView).toContain('<EmailIdentityPanel expanded={emailIdentitiesOpen} />');
    expect(source).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie/u);
    expect(source).not.toMatch(/state:\s*['"]verified['"]/u);
  });
});
