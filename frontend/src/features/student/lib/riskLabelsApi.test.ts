import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  RiskLabelApiError,
  getPublicRiskLabels,
  organisationResponseErrorCopy,
  organisationResponseFailureState,
  riskLabelUnavailableState,
  submitOrganisationResponse,
} from './riskLabelsApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const ORGANISATION_ID = '00000000-0000-4000-8000-000000000279';
const LABEL_ID = '00000000-0000-4000-8000-000000000280';

describe('SAATHI-279 risk-label and organisation-response API adapter', () => {
  it('maps only the privacy-safe public aggregate and approved response', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      organisation_id: ORGANISATION_ID,
      available: true,
      labels: [{
        id: LABEL_ID,
        category: 'unpaid_mismatch',
        neutral_label: 'Moderated stipend expectation pattern',
        public_count: null,
        last_reviewed_at: '2026-08-02T09:00:00Z',
        source_type: 'moderated_aggregate',
        status: 'corrected',
        organisation_response: {
          text: 'We updated the published stipend terms and review process.',
          last_reviewed_at: '2026-08-03T09:00:00Z',
          kind: 'correction',
        },
      }, {
        id: 'withdrawn-label-must-not-render',
        category: 'withdrawn',
        neutral_label: 'This must never become public',
        public_count: 100,
        last_reviewed_at: '2026-08-03T09:00:00Z',
        source_type: 'moderated_aggregate',
        status: 'withdrawn',
        organisation_response: null,
      }],
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getPublicRiskLabels(ORGANISATION_ID)).resolves.toEqual({
      organisationId: ORGANISATION_ID,
      available: true,
      labels: [expect.objectContaining({
        id: LABEL_ID,
        neutralLabel: 'Moderated stipend expectation pattern',
        publicCount: null,
        sourceType: 'moderated_aggregate',
        status: 'corrected',
        organisationResponse: expect.objectContaining({
          text: 'We updated the published stipend terms and review process.',
          kind: 'correction',
        }),
      })],
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url).pathname).toBe(`/api/v1/public/internship-risk-labels/${ORGANISATION_ID}`);
    expect(init.credentials).toBe('include');
  });

  it('retains typed fail-closed unavailable states without making them retryable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      detail: { code: 'risk_labels_unavailable', message: 'Not enabled', retryable: false },
    }, 503)));

    const error = await getPublicRiskLabels(ORGANISATION_ID).catch((value) => value);
    expect(error).toEqual(expect.objectContaining<Partial<RiskLabelApiError>>({
      status: 503, code: 'risk_labels_unavailable', retryable: false,
    }));
    expect(riskLabelUnavailableState(error)).toBe('disabled');
  });

  it('sends the one-time token in a dedicated header, never URL or JSON', async () => {
    const rawToken = 'one-time-private-response-token';
    const fetchMock = vi.fn().mockResolvedValue(response({
      id: '00000000-0000-4000-8000-000000000281',
      published_label_id: LABEL_ID,
      state: 'moderation_pending',
      version: 1,
      submitted_at: '2026-08-03T10:00:00Z',
    }, 201));
    vi.stubGlobal('fetch', fetchMock);

    await expect(submitOrganisationResponse(rawToken, 'We corrected the published internship terms.', 'response-key-1')).resolves.toEqual(
      expect.objectContaining({
        state: 'moderation_pending',
        publishedLabelId: LABEL_ID,
        createdAt: '2026-08-03T10:00:00Z',
      }),
    );
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = String(init.body);
    const headers = new Headers(init.headers);
    expect(new URL(url).pathname).toBe('/api/v1/organisation-responses');
    expect(url).not.toContain(rawToken);
    expect(body).not.toContain(rawToken);
    expect(JSON.parse(body)).toEqual({ response_text: 'We corrected the published internship terms.' });
    expect(headers.get('X-Organisation-Response-Token')).toBe(rawToken);
    expect(headers.get('Idempotency-Key')).toBe('response-key-1');
  });

  it('uses one non-enumerating message for invalid, expired and replayed invitations', () => {
    for (const code of ['response_token_invalid', 'response_token_expired', 'response_token_replayed', 'response_token_unavailable']) {
      const error = new RiskLabelApiError(404, code, 'private');
      expect(organisationResponseErrorCopy(error)).toBe(
        'This invitation is invalid, expired or already used. Ask NyayOne for a new verified invitation.',
      );
      expect(organisationResponseFailureState(error)).toBe('invitation-unavailable');
    }
    expect(organisationResponseFailureState(new RiskLabelApiError(503, 'response_service_unavailable', 'private', undefined, true))).toBe('retryable');
    expect(organisationResponseFailureState(new RiskLabelApiError(400, 'response_invalid', 'private'))).toBe('unavailable');
  });

  it('maps response-chain and idempotency conflicts without exposing backend reason text', () => {
    const staleTarget = new RiskLabelApiError(
      409,
      'response_correction_target_changed',
      'private chain reason must not render',
    );
    expect(organisationResponseFailureState(staleTarget)).toBe('invitation-unavailable');
    expect(organisationResponseErrorCopy(staleTarget)).toBe(
      'This correction invitation is no longer current. Ask NyayOne for a new verified invitation.',
    );
    expect(organisationResponseErrorCopy(staleTarget)).not.toContain('private chain reason');

    const conflict = new RiskLabelApiError(
      409,
      'idempotency_conflict',
      'private idempotency reason must not render',
    );
    expect(organisationResponseFailureState(conflict)).toBe('conflict');
    expect(organisationResponseErrorCopy(conflict)).toBe(
      'This submission attempt conflicted with an earlier request. Start a fresh submission attempt.',
    );
    expect(organisationResponseErrorCopy(conflict)).not.toContain('private idempotency reason');
  });
});
