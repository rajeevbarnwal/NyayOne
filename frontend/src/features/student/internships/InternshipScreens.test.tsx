import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { AuthProvider, type AuthState } from '../../../app/authContext';
import type { InternshipListing } from '../lib/internships';
import {
  InternshipApply,
  InternshipBrowse,
  InternshipDetail,
  InternshipEmpty,
  InternshipSaved,
} from './InternshipScreens';

const STUDENT: AuthState = {
  isAuthenticated: true,
  userId: '00000000-0000-4000-8000-000000000060',
  roles: ['student'],
  studentVerification: 'verified',
  lawyerVerification: 'draft',
  filingRole: null,
  isMinor: false,
};

const CAM: InternshipListing = {
  id: 'cam', role: 'Summer Associate, disputes', org: 'Cyril Amarchand Mangaldas', location: 'Mumbai',
  stipendMonthlyPaise: 4_000_000, verificationStatus: 'verified', deadline: '9 Jul',
  eligibility: '3rd–4th year', tags: ['Disputes'], description: 'Commercial disputes work.',
  source: { name: 'CAM careers', url: null, retrievedAt: '2026-06-28T00:00:00+05:30', verifiedAt: '2026-06-28T00:00:00+05:30' },
};
const MENON: InternshipListing = {
  id: 'menon', role: 'Judicial research assistant', org: 'Chambers of Sr. Adv. R. Menon', location: 'Delhi HC',
  stipendMonthlyPaise: 1_500_000, verificationStatus: 'unverified', deadline: '8 Jul',
  eligibility: '2nd year+', tags: ['Research'], description: 'Judicial research support.',
  source: { name: 'Sample fixture', url: null, retrievedAt: null, verifiedAt: null },
};

function render(
  path: string,
  component: React.ReactElement,
  seed: (client: QueryClient) => void = () => undefined,
  auth: AuthState = STUDENT,
): string {
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } });
  seed(client);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <AuthProvider value={auth}>
        <MemoryRouter initialEntries={[path]}>{component}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe('SAATHI-60 internship screens', () => {
  it('renders server catalogue/saved truth and no first-visit fake seed', () => {
    const html = render('/s-20', <InternshipBrowse />, (client) => {
      client.setQueryData(['internships-catalogue'], { items: [CAM, MENON], total: 2, page: 1, pageSize: 20 });
      client.setQueryData(['internships-saved', STUDENT.userId], [MENON]);
    });
    expect(html).toContain('Summer Associate, disputes');
    expect(html).toContain('Judicial research assistant');
    expect(html).toContain('Verified listing');
    expect(html).toContain('Unverified listing');
    expect(html).toContain('aria-pressed="true"');
  });

  it('uses the selected Menon identity on detail and never falls back to CAM', () => {
    const html = render('/s-21?listing=menon', <InternshipDetail />, (client) => {
      client.setQueryData(['internship', 'menon'], MENON);
      client.setQueryData(['internships-saved', STUDENT.userId], []);
    });
    expect(html).toContain('Judicial research assistant');
    expect(html).toContain('Chambers of Sr. Adv. R. Menon');
    expect(html).not.toContain('Cyril Amarchand Mangaldas');
    expect(html).toContain('Source: Sample fixture · unverified · not affiliated');
  });

  it('keeps the selected Menon identity in the application flow', () => {
    const html = render('/s-22?listing=menon', <InternshipApply />, (client) => {
      client.setQueryData(['internship', 'menon'], MENON);
    });
    expect(html).toContain('Chambers of Sr. Adv. R. Menon · Judicial research assistant');
    expect(html).not.toContain('Cyril Amarchand Mangaldas');
  });

  it('fails closed for a missing listing identity instead of showing CAM', () => {
    const html = render('/s-21', <InternshipDetail />);
    expect(html).toContain('Listing unavailable');
    expect(html).toContain('listing link is incomplete');
    expect(html).not.toContain('Summer Associate, disputes');
  });

  it('renders account-backed saved and genuine empty states', () => {
    const savedHtml = render('/s-25', <InternshipSaved />, (client) => {
      client.setQueryData(['internships-saved', STUDENT.userId], [MENON]);
    });
    expect(savedHtml).toContain('Private to your account · organisations are not notified');
    expect(savedHtml).toContain('Judicial research assistant');
    expect(savedHtml).not.toContain('See empty state');

    const emptyHtml = render('/s-26', <InternshipEmpty />, (client) => {
      client.setQueryData(['internships-saved', STUDENT.userId], []);
    });
    expect(emptyHtml).toContain('No saved internships yet');
    expect(emptyHtml).toContain('Browse listings');
  });

  it('does not claim account state to an anonymous visitor', () => {
    const html = render('/s-25', <InternshipSaved />, () => undefined, {
      ...STUDENT, isAuthenticated: false, userId: null, roles: [], studentVerification: 'draft',
    });
    expect(html).toContain('Sign in to view saved internships');
    expect(html).toContain('Go to sign in');
  });

  it('does not tell an authenticated non-student to sign in again', () => {
    const html = render('/s-25', <InternshipSaved />, () => undefined, {
      ...STUDENT, roles: ['lawyer'], studentVerification: 'draft', lawyerVerification: 'verified',
    });
    expect(html).toContain('Student account required');
    expect(html).toContain('available only to student accounts');
    expect(html).not.toContain('Go to sign in');
  });
});
