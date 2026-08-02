import { afterEach, describe, expect, it, vi } from 'vitest';
import { actOnModerationCase, createRiskCluster, listModerationCases } from './moderationApi';

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const ITEM = {
  case_id: '00000000-0000-4000-8000-000000000274',
  report_id: '00000000-0000-4000-8000-000000000269',
  organisation_name: 'Nyaya Legal Foundation', categories: ['unsafe_environment'],
  experience_start_date: '2026-05-01', experience_end_date: '2026-05-31',
  evidence_clean: 1, evidence_total: 1, state: 'pending', assigned_to_me: false,
  version: 1, submitted_at: '2026-06-01T00:00:00Z',
};

describe('SAATHI-274 moderator API boundary', () => {
  it('uses the cookie-backed session and never injects a client actor header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ items: [ITEM], total: 1 }));
    vi.stubGlobal('fetch', fetchMock);
    await expect(listModerationCases()).resolves.toEqual([
      expect.objectContaining({ reportId: ITEM.report_id, organisationName: ITEM.organisation_name }),
    ]);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/moderation/internship-reports');
    expect(init.credentials).toBe('include');
    expect(new Headers(init.headers).has('X-Actor-Claims')).toBe(false);
  });

  it('posts the frozen report-id action path, optimistic version and safe idempotency', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({}));
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('crypto', { randomUUID: () => '00000000-0000-4000-8000-000000000001' });
    await actOnModerationCase(ITEM.report_id, 3, 'approve_aggregate_only', 'Evidence meets internal criteria.');
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(`/internship-reports/${ITEM.report_id}/actions`);
    expect(JSON.parse(String(init.body))).toEqual({
      action: 'approve_aggregate_only', reason_code: 'aggregate_criteria_met',
      reason_detail: 'Evidence meets internal criteria.', expected_version: 3,
    });
    expect(new Headers(init.headers).get('Idempotency-Key')).toContain('moderation-approve_aggregate_only-');
  });

  it('creates only an internal cluster and maps publication_ready=false', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      id: 'cluster-1', organisation_name: 'Nyaya Legal Foundation', category: 'unsafe_environment',
      explanation_code: 'organisation_category_time_window', state: 'eligible',
      member_report_ids: ['r1', 'r2', 'r3'], report_count: 3, distinct_reporter_count: 3,
      threshold_met: true, small_count_suppressed: true, moderator_approved: false,
      safety_legal_approved: false, publication_ready: false, public_count: null,
      neutral_label: 'Moderated unsafe environment pattern', version: 1,
    }, 201));
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('crypto', { randomUUID: () => '00000000-0000-4000-8000-000000000002' });
    const cluster = await createRiskCluster(['r1', 'r2', 'r3'], 'unsafe_environment');
    expect(cluster).toMatchObject({ publicationReady: false, publicCount: null, distinctReporterCount: 3 });
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/moderation/risk-clusters');
    expect(url).not.toMatch(/public|publish/);
  });
});

