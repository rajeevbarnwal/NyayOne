import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ANONYMOUS_AUTH, AuthProvider, type AuthState } from '../../app/authContext';
import { ModerationGuard, ModerationQueueScreen, RiskClusterScreen } from './ModerationScreens';
import { moderationRoutes } from './screens';
import type { ModerationQueueItem, RiskCluster } from './lib/moderationApi';

const MODERATOR: AuthState = {
  isAuthenticated: true,
  userId: '00000000-0000-4000-8000-0000000000c4',
  roles: ['moderator'], studentVerification: 'draft', lawyerVerification: 'draft',
  filingRole: null, isMinor: false,
};

const CASE: ModerationQueueItem = {
  caseId: 'case-1', reportId: 'report-1', organisationName: 'Nyaya Legal Foundation',
  categories: ['unsafe_environment'], experienceStartDate: '2026-05-01', experienceEndDate: '2026-05-31',
  evidenceClean: 1, evidenceTotal: 1, state: 'approved_aggregate_only', assignedToMe: true,
  version: 3, submittedAt: '2026-06-01T00:00:00Z',
};

function render(path: string, auth: AuthState, element: React.ReactElement, seed?: (client: QueryClient) => void): string {
  const client = new QueryClient({ defaultOptions: { queries: { enabled: false, retry: false } } });
  seed?.(client);
  return renderToStaticMarkup(
    <QueryClientProvider client={client}><AuthProvider value={auth}><MemoryRouter initialEntries={[path]}>{element}</MemoryRouter></AuthProvider></QueryClientProvider>,
  );
}

describe('SAATHI-274 internal moderation screens', () => {
  it('keeps all routes outside the public student registry and behind one guard', () => {
    expect(moderationRoutes.map((item) => item.path)).toEqual([
      '/moderation/internship-reports',
      '/moderation/internship-reports/:reportId',
      '/moderation/risk-clusters/:clusterId',
    ]);
    expect(moderationRoutes.every((item) => item.jira === 'SAATHI-274')).toBe(true);
  });

  it('denies anonymous and student sessions before queue content mounts', () => {
    for (const auth of [ANONYMOUS_AUTH, { ...MODERATOR, roles: ['student'] as const }]) {
      const html = render('/moderation/internship-reports', auth as AuthState, <ModerationGuard><ModerationQueueScreen /></ModerationGuard>);
      expect(html).toContain('Moderator sign-in required');
      expect(html).not.toContain('Nyaya Legal Foundation');
      expect(html).not.toContain('Internship report queue');
    }
  });

  it('renders the moderator queue, 44px actions and internal-only cluster builder', () => {
    const html = render('/moderation/internship-reports', MODERATOR, <ModerationGuard><ModerationQueueScreen /></ModerationGuard>, (client) => {
      client.setQueryData(['moderation-cases'], [CASE]);
    });
    expect(html).toContain('data-screen="MOD-01"');
    expect(html).toContain('Nyaya Legal Foundation');
    expect(html).toContain('Include in internal cluster');
    expect(html).toContain('Public labels off');
    expect(html).not.toMatch(/publish organisation|publish label|public allegation/i);
  });

  it('renders a truthful empty queue after the server returns zero cases', () => {
    const html = render('/moderation/internship-reports', MODERATOR, <ModerationGuard><ModerationQueueScreen /></ModerationGuard>, (client) => {
      client.setQueryData(['moderation-cases'], []);
    });
    expect(html).toContain('data-testid="moderation-empty"');
    expect(html).toContain('No reports need moderation.');
    expect(html).not.toContain('Review private case');
  });

  it('renders suppression and the hard publication kill-switch in the risk preview', () => {
    const cluster: RiskCluster = {
      id: 'cluster-1', organisationName: 'Nyaya Legal Foundation', category: 'unsafe_environment',
      explanationCode: 'organisation_category_time_window', state: 'eligible', memberReportIds: ['r1', 'r2', 'r3'],
      reportCount: 3, distinctReporterCount: 3, thresholdMet: true, smallCountSuppressed: true,
      moderatorApproved: true, safetyLegalApproved: true, publicationReady: false,
      publicCount: null, neutralLabel: 'Moderated unsafe environment pattern', version: 3,
    };
    const html = render('/moderation/risk-clusters/cluster-1', MODERATOR, <ModerationGuard><RiskClusterScreen /></ModerationGuard>, (client) => {
      // This static-render test mounts the screen directly (without a Route
      // matcher), so useParams is empty and the cached query key reflects it.
      client.setQueryData(['risk-cluster', ''], cluster);
    });
    expect(html).toContain('data-screen="MOD-03"');
    expect(html).toContain('Suppressed');
    expect(html).toContain('Public publication kill-switch: OFF');
    expect(html).toContain('publication_ready');
    expect(html).toContain('SAATHI-279 implementation and Product-approved safe defaults are complete.');
    expect(html).toContain('SAATHI-452 records Counsel/Policy and Security/Privacy approval');
    expect(html).not.toContain('until SAATHI-279 and SAATHI-452 receive');
  });
});
