import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { AuthProvider, type AuthState, type StudentSessionPhase } from './authContext';
import { StudentRouteGuard } from './StudentRouteGuard';
import type { GuardianStatus, InstitutionalEmailStatus, StudentProfileProjection } from '../features/student/lib/profileApi';
import { STUDENT_PROFILE_QUERY_KEY } from '../features/student/profile/profileHooks';
import { EmailVerify, RestrictedDashboard } from '../features/student/auth/AuthScreens';

// Consumer regression matrix. These are server projections, not client-authored
// verification claims; the backend/native matrix independently proves all 61
// source/target outcomes. Existing private routes still consume NYAY-5's API.
const AUTH: AuthState = {
  isAuthenticated: true, userId: 'synthetic-owner', roles: ['student'],
  studentVerification: 'verified', lawyerVerification: 'draft', filingRole: null,
  isMinor: false, // A stale/client age hint must never lift server restriction.
};
const GUARDIAN: GuardianStatus[] = ['not_required', 'required_pending', 'verified', 'rejected', 'revoked'];
const INSTITUTION: InstitutionalEmailStatus[] = ['not_provided', 'pending', 'verified', 'rejected', 'expired', 'revoked'];

function projection(guardian: GuardianStatus, institution: InstitutionalEmailStatus): StudentProfileProjection {
  const limited = guardian !== 'not_required' && guardian !== 'verified';
  return {
    profileVersion: 1, completionVersion: 'v1', completionPercent: 100,
    completedSections: ['personal', 'academic', 'interests'], missingRequirements: [],
    nextIncompleteSection: null, isComplete: true, institutionalEmailStatus: institution,
    guardian: { required: guardian !== 'not_required', status: guardian },
    accessMode: limited ? 'limited' : 'full', disabledCapabilities: limited ? ['community', 'sharing'] : [],
    profilePrompt: { shouldShow: false, dismissedForSession: false },
    profile: {
      personal: { firstName: 'Synthetic', middleName: null, lastName: 'Fixture', dateOfBirth: '2000-01-01', preferredLanguage: 'en', city: 'Pune', pronouns: null },
      academic: { college: 'Synthetic College', yearOfStudy: '3', enrolmentNumber: 'SYNTHETIC', institutionalEmail: 'fixture@example.edu', barEnrolmentNumber: null },
      interests: { interests: ['Tax'], goals: ['Research'] },
    },
  };
}

function render(projectionValue: StudentProfileProjection | undefined, path: string, phase: StudentSessionPhase = 'authenticated', child = <span data-authority-private-canary>Private capability</span>) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (projectionValue) queryClient.setQueryData(STUDENT_PROFILE_QUERY_KEY, projectionValue);
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <AuthProvider value={AUTH} studentSession={{ phase, refresh: vi.fn(async () => undefined) }}>
        <MemoryRouter initialEntries={[path]}><StudentRouteGuard>{child}</StudentRouteGuard></MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe('NYAY-11 canonical UI authority projection', () => {
  for (const guardian of GUARDIAN) for (const institution of INSTITUTION) {
    it(`${guardian}/${institution}: only server-disabled capabilities control private mount`, () => {
      const server = projection(guardian, institution);
      for (const path of ['/s-50', '/s-85?mode=share']) {
        const html = render(server, path);
        expect(html.includes('data-authority-private-canary')).toBe(server.accessMode === 'full');
      }
      // Limited users retain the explicit safe owner-profile surface, not all
      // private capabilities. The client does not invent an all-access role.
      expect(render(server, '/s-10')).toContain('data-authority-private-canary');
    });
  }
  it.each(['pending', 'unavailable', 'anonymous'] as const)('denies stale verified projection during %s session authority', (phase) => {
    expect(render(projection('verified', 'verified'), '/s-50', phase)).not.toContain('data-authority-private-canary');
  });
  it('does not grant a private capability while server policy is absent', () => {
    expect(render(undefined, '/s-50')).not.toContain('data-authority-private-canary');
  });
  it.each(INSTITUTION)('institutional %s display exposes no approval/rejection controls', (status) => {
    const html = render(projection('not_required', status), '/s-15', 'authenticated', <EmailVerify />);
    expect(html).toContain(status.replace(/_/gu, ' '));
    expect(html).not.toMatch(/>\s*(Approve|Reject|Mark verified|Verify student)\s*</u);
    expect(html).toContain('only an authorized review');
  });
  it.each(['required_pending', 'rejected', 'revoked'] as const)('guardian %s remains limited without self-verification controls', (status) => {
    const html = render(projection(status, 'verified'), '/s-16', 'authenticated', <RestrictedDashboard />);
    expect(html).toContain('Disabled capabilities: community, sharing.');
    expect(html).toContain('No client action can mark consent verified.');
    expect(html).not.toMatch(/>\s*(Approve|Verify guardian|Grant access)\s*</u);
  });
});
