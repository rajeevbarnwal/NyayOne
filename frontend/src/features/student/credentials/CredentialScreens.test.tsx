import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import {
  CredentialAdd,
  CredentialPending,
  CredentialShare,
  CredentialWallet,
  PublicCredentialVerification,
} from './CredentialScreens';
import type { CredentialRecord } from '../lib/credentialsApi';

function render(
  path: string,
  Component: () => ReactElement,
  credential?: CredentialRecord,
): string {
  const client = new QueryClient({
    defaultOptions: { queries: { enabled: false, retry: false } },
  });
  if (credential) client.setQueryData(['credential', credential.id], credential);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Component />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('canonical S-82..S-85 credential screens', () => {
  it('renders a server-backed wallet with no local-storage language', () => {
    const html = render('/s-82', CredentialWallet);
    expect(html).toContain('data-screen="S-82"');
    expect(html).toContain('Your verified story');
    expect(html).not.toMatch(/localStorage|sessionStorage|mock verified/i);
  });

  it('renders strict dates and allowlisted evidence input', () => {
    const html = render('/s-83', CredentialAdd);
    expect(html).toContain('data-screen="S-83"');
    expect(html).toContain('type="date"');
    expect(html).toContain('.pdf,.png,.jpg,.jpeg,.webp');
    expect(html).toContain('max 10 MB');
  });

  it('renders pending/issuer authority and share privacy states', () => {
    const pending = render('/s-84', CredentialPending);
    const share = render('/s-85', CredentialShare);
    expect(pending).toContain('data-screen="S-84"');
    expect(pending).toContain('Select a credential');
    expect(share).toContain('data-screen="S-85"');
    expect(share).toContain('Select a verified credential');
  });

  it('never mounts issuer mutation controls on the student status route', () => {
    const credential: CredentialRecord = {
      id: '00000000-0000-4000-8000-000000000253',
      title: 'Moot Certificate',
      credentialType: 'moot_achievement',
      status: 'pending_verification',
      issueDate: '2026-01-01',
      expiryDate: null,
      issuerId: '00000000-0000-4000-8000-000000000258',
      issuerDisplayName: 'Legal Skills Council',
      identifier: null,
      version: 3,
      evidence: [],
      createdAt: '2026-01-01T00:00:00Z',
      updatedAt: '2026-01-01T00:00:00Z',
    };
    const html = render(
      `/s-84?credential=${encodeURIComponent(credential.id)}`,
      CredentialPending,
      credential,
    );
    expect(html).toContain('data-screen="S-84"');
    expect(html).not.toMatch(/>\s*Verify credential\s*</i);
    expect(html).not.toMatch(/>\s*Revoke as issuer\s*</i);
    expect(html).toContain('Issuer review is available only in the separate authorised issuer workspace.');
  });

  it('renders an anonymous public-verification route without private evidence UI', () => {
    const html = render(`/verify/${'A'.repeat(43)}`, PublicCredentialVerification);
    expect(html).toContain('data-screen="VERIFY"');
    expect(html).toContain('Nyay<span>One</span>');
    expect(html).not.toMatch(/private identifier|evidence download|issuer notes/i);
  });
});
