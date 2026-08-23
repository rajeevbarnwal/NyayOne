import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import {
  CredentialsApiError,
  PUBLIC_CREDENTIAL_FIELDS,
  createCredential,
  createShareProjection,
  createVerificationToken,
  getPublicCredentialVerification,
  isRetryableCredentialsError,
  listCredentials,
  verifyCredential,
  uploadCredentialEvidence,
} from './credentialsApi';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

const WIRE = {
  id: '00000000-0000-4000-8000-000000000253',
  title: 'Moot Certificate',
  credential_type: 'moot_achievement',
  status: 'verified',
  issue_date: '2026-01-01',
  expiry_date: null,
  issuer_id: '00000000-0000-4000-8000-000000000258',
  issuer_display_name: 'Legal Skills Council',
  identifier: 'PRIVATE-1',
  version: 3,
  evidence: [{
    id: 'evidence-1',
    mime: 'application/pdf',
    size_bytes: 120,
    sha256: 'a'.repeat(64),
    scan_state: 'clean',
  }],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
};

describe('credential adapter wire contract', () => {
  it('maps list wire values without browser persistence', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      items: [WIRE], total: 1, page: 1, page_size: 20,
    })));
    const result = await listCredentials('verified');
    expect(result.items[0]).toEqual(expect.objectContaining({
      credentialType: 'moot_achievement',
      issuerDisplayName: 'Legal Skills Council',
      evidence: [expect.objectContaining({ sizeBytes: 120, scanState: 'clean' })],
    }));
    // The adapter itself never calls either browser storage API; the native
    // Node test environment deliberately has neither object installed.
    expect('localStorage' in globalThis).toBe(false);
    expect('sessionStorage' in globalThis).toBe(false);
  });

  it('sends canonical snake_case fields and idempotency', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(WIRE, 201));
    vi.stubGlobal('fetch', fetchMock);
    await createCredential({
      title: 'Moot Certificate',
      credentialType: 'moot_achievement',
      issueDate: '2026-01-01',
      issuerId: WIRE.issuer_id,
    }, 'credential-idem-0001');
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get('Idempotency-Key')).toBe('credential-idem-0001');
    expect(JSON.parse(String(init.body))).toEqual({
      title: 'Moot Certificate',
      credential_type: 'moot_achievement',
      issue_date: '2026-01-01',
      expiry_date: null,
      issuer_id: WIRE.issuer_id,
      identifier: null,
    });
  });

  it('uploads multipart evidence without forcing JSON content type', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      id: 'ev-1', scan_state: 'clean', status: 'pending_verification', retryable: false,
    }));
    vi.stubGlobal('fetch', fetchMock);
    const file = new File(['%PDF-1.7'], 'proof.pdf', { type: 'application/pdf' });
    const result = await uploadCredentialEvidence(WIRE.id, file);
    expect(result).toEqual({
      id: 'ev-1', scanState: 'clean', status: 'pending_verification', retryable: false,
    });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has('Content-Type')).toBe(false);
  });

  it('uses only allowlisted share fields and maps a one-time token', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        id: 'projection-1',
        credential_id: WIRE.id,
        fields: PUBLIC_CREDENTIAL_FIELDS,
        active: true,
      }))
      .mockResolvedValueOnce(response({
        id: 'token-1',
        token: 'A'.repeat(43),
        verification_url: `https://example.test/verify/${'A'.repeat(43)}`,
        expires_at: '2026-10-27T00:00:00Z',
      }));
    vi.stubGlobal('fetch', fetchMock);
    const projection = await createShareProjection(
      WIRE.id,
      [...PUBLIC_CREDENTIAL_FIELDS],
      'projection-idem-1',
    );
    const token = await createVerificationToken(
      WIRE.id,
      projection.id,
      90,
      'token-idem-0001',
    );
    expect(projection.fields).toEqual(PUBLIC_CREDENTIAL_FIELDS);
    expect(token.verificationUrl).toMatch(/^https:\/\/.+\/verify\/[A-Za-z0-9_-]{43}$/);
  });

  it('public verification never sends the development actor header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      verification: { title: 'Moot Certificate', status: 'verified' },
      token_expires_at: '2026-10-27T00:00:00Z',
    }));
    vi.stubGlobal('fetch', fetchMock);
    await getPublicCredentialVerification('A'.repeat(43));
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).has('X-Actor-Claims')).toBe(false);
  });

  it('uses only the current HttpOnly session for student and issuer authority', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({ items: [], total: 0, page: 1, page_size: 20 }))
      .mockResolvedValueOnce(response({ status: 'verified', version: 4 }));
    vi.stubGlobal('fetch', fetchMock);

    await listCredentials();
    await verifyCredential(WIRE.id, 3, 'issuer-review-1');

    for (const [, init] of fetchMock.mock.calls as Array<[string, RequestInit]>) {
      expect(new Headers(init.headers).has('X-Actor-Claims')).toBe(false);
      expect(init.credentials).toBe('include');
    }
  });
});

describe('credential query retry boundary', () => {
  const retry = (failureCount: number, error: unknown) =>
    isRetryableCredentialsError(error) && failureCount < 1;

  it('does not retry typed 4xx', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      detail: { code: 'verification_not_found' },
    }, 404));
    vi.stubGlobal('fetch', fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry, retryDelay: 0 } } });
    await expect(client.fetchQuery({
      queryKey: ['public', 'bad'],
      queryFn: () => getPublicCredentialVerification('A'.repeat(43)),
    })).rejects.toMatchObject({ status: 404, code: 'verification_not_found' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('retries network/5xx at most once', async () => {
    // A real fetch produces a fresh Response for each retry. Reusing a single
    // body would make the second lease-observation clone fail before the typed
    // adapter can classify the second 503.
    const fetchMock = vi.fn().mockImplementation(async () => response({
      detail: { code: 'internal_error' },
    }, 503));
    vi.stubGlobal('fetch', fetchMock);
    const client = new QueryClient({ defaultOptions: { queries: { retry, retryDelay: 0 } } });
    await expect(client.fetchQuery({
      queryKey: ['credentials'],
      queryFn: () => listCredentials(),
    })).rejects.toBeInstanceOf(CredentialsApiError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
