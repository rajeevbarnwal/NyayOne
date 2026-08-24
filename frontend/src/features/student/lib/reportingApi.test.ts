import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  ReportingApiError,
  createInternshipReport,
  getInternshipReportStatus,
  reportingErrorCopy,
  updateInternshipReport,
  uploadInternshipReportEvidence,
} from './reportingApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

const WIRE = {
  id: '00000000-0000-4000-8000-000000000269',
  organisation_name: 'Example Chambers',
  listing_application_ref: 'APP-2026-86',
  experience_start_date: '2026-01-01',
  experience_end_date: '2026-01-31',
  categories: ['positive_experience'],
  narrative: 'A factual account with enough detail to pass the minimum narrative boundary.',
  privacy_mode: 'anonymous',
  consent_accepted: true,
  consent_version: 'internship-report-v1',
  status: 'draft',
  support_guidance_required: false,
  evidence: [],
  version: 1,
  submitted_at: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('private internship-reporting API contract', () => {
  it('maps the report and sends the fixed ten-category/private fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(WIRE, 201));
    vi.stubGlobal('fetch', fetchMock);
    const result = await createInternshipReport({
      organisationName: 'Example Chambers',
      listingApplicationRef: 'APP-2026-86',
      experienceStartDate: '2026-01-01',
      experienceEndDate: '2026-01-31',
      categories: ['positive_experience'],
      narrative: WIRE.narrative,
      privacyMode: 'anonymous',
      consentAccepted: true,
      consentVersion: 'internship-report-v1',
    }, 'internship-report-idempotency-1');
    expect(result).toEqual(expect.objectContaining({
      organisationName: 'Example Chambers',
      listingApplicationRef: 'APP-2026-86',
      privacyMode: 'anonymous',
    }));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/internship-reports');
    expect(new Headers(init.headers).get('Idempotency-Key')).toBe('internship-report-idempotency-1');
    expect(new Headers(init.headers).has('X-Actor-Claims')).toBe(false);
    expect(init.credentials).toBe('include');
    expect(JSON.parse(String(init.body))).toEqual(expect.objectContaining({
      organisation_name: 'Example Chambers',
      listing_application_ref: 'APP-2026-86',
      privacy_mode: 'anonymous',
      consent_version: 'internship-report-v1',
    }));
  });

  it('does not silently clear omitted fields on a partial update', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ ...WIRE, narrative: 'Updated factual account with enough detail for the server-side submission policy.' }));
    vi.stubGlobal('fetch', fetchMock);
    await updateInternshipReport(WIRE.id, 1, { narrative: 'Updated factual account with enough detail for the server-side submission policy.' });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body))).toEqual({
      narrative: 'Updated factual account with enough detail for the server-side submission policy.',
      expected_version: 1,
    });
  });

  it('uploads evidence as multipart without setting a JSON content type', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      id: 'evidence-1', mime_type: 'application/pdf', size_bytes: 9,
      checksum_sha256: 'a'.repeat(64), scan_state: 'clean', retryable: false,
    }));
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['%PDF-1.7'], 'evidence.pdf', { type: 'application/pdf' });
    const result = await uploadInternshipReportEvidence(WIRE.id, 1, file);
    expect(result.scanState).toBe('clean');
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has('Content-Type')).toBe(false);
  });

  it('maps reporter-only status and keeps a typed non-enumerating error', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        id: WIRE.id, status: 'moderation_pending', privacy_mode: 'anonymous',
        support_guidance_required: false, evidence_total: 1, evidence_clean: 1,
        version: 3, submitted_at: '2026-01-02T00:00:00Z',
      }))
      .mockResolvedValueOnce(response({ detail: { code: 'internship_report_not_found' } }, 404));
    vi.stubGlobal('fetch', fetchMock);
    await expect(getInternshipReportStatus(WIRE.id)).resolves.toEqual(expect.objectContaining({ evidenceClean: 1 }));
    await expect(getInternshipReportStatus('unknown')).rejects.toMatchObject({ status: 404, code: 'internship_report_not_found' });
    expect(reportingErrorCopy(new ReportingApiError(404, 'internship_report_not_found'))).toContain('unavailable');
  });
});
