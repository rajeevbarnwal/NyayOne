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

function render(path: string, Component: () => ReactElement): string {
  const client = new QueryClient({
    defaultOptions: { queries: { enabled: false, retry: false } },
  });
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

  it('renders an anonymous public-verification route without private evidence UI', () => {
    const html = render(`/verify/${'A'.repeat(43)}`, PublicCredentialVerification);
    expect(html).toContain('data-screen="VERIFY"');
    expect(html).toContain('Legal<span>Saathi</span>');
    expect(html).not.toMatch(/private identifier|evidence download|issuer notes/i);
  });
});
