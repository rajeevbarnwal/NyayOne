import { apiFetch } from '../../../lib/apiClient';
import type { InternshipListing } from './internships';

const BASE = '/api/v1/internships';
const SAVED_BASE = '/api/v1/student/internships';

export class InternshipsApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'InternshipsApiError';
  }
}

interface SourceWire {
  name: string;
  url: string | null;
  retrieved_at: string | null;
  verified_at: string | null;
}

interface ListingWire {
  id: string;
  organisation_id: string;
  role: string;
  organisation: string;
  location: string;
  stipend_monthly_paise: number | null;
  verification_status: InternshipListing['verificationStatus'];
  application_deadline: string;
  eligibility: string;
  tags: string[];
  description: string;
  source: SourceWire;
}

interface ListingPageWire {
  items: ListingWire[];
  total: number;
  page: number;
  page_size: number;
}

async function jsonRequest<T>(path: string, init: RequestInit): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, { ...init, headers });
  const body = (await response.json().catch(() => ({}))) as T & {
    detail?: { code?: string; message?: string } | string;
  };
  if (!response.ok) {
    const detail = typeof body.detail === 'object' ? body.detail : undefined;
    throw new InternshipsApiError(
      response.status,
      detail?.code ?? `http_${response.status}`,
      detail?.message ?? 'The internship service could not complete this request.',
    );
  }
  return body;
}

function mapListing(wire: ListingWire): InternshipListing {
  const deadline = /^\d{4}-\d{2}-\d{2}$/.test(wire.application_deadline)
    ? new Date(`${wire.application_deadline}T00:00:00Z`).toLocaleDateString('en-IN', {
        day: 'numeric', month: 'short', timeZone: 'UTC',
      })
    : wire.application_deadline;
  return {
    id: wire.id,
    organisationId: wire.organisation_id,
    role: wire.role,
    org: wire.organisation,
    location: wire.location,
    stipendMonthlyPaise: wire.stipend_monthly_paise,
    verificationStatus: wire.verification_status,
    deadline,
    eligibility: wire.eligibility,
    tags: wire.tags,
    description: wire.description,
    source: {
      name: wire.source.name,
      url: wire.source.url,
      retrievedAt: wire.source.retrieved_at,
      verifiedAt: wire.source.verified_at,
    },
  };
}

export interface InternshipListingPage {
  items: InternshipListing[];
  total: number;
  page: number;
  pageSize: number;
}

export async function listInternships(): Promise<InternshipListingPage> {
  const wire = await jsonRequest<ListingPageWire>(BASE, { method: 'GET' });
  return {
    items: wire.items.map(mapListing),
    total: wire.total,
    page: wire.page,
    pageSize: wire.page_size,
  };
}

export async function getInternship(id: string): Promise<InternshipListing> {
  return mapListing(
    await jsonRequest<ListingWire>(`${BASE}/${encodeURIComponent(id)}`, { method: 'GET' }),
  );
}

export async function listSavedInternships(): Promise<InternshipListing[]> {
  const wire = await jsonRequest<{ items: ListingWire[] }>(`${SAVED_BASE}/saved`, { method: 'GET' });
  return wire.items.map(mapListing);
}

export async function saveInternship(id: string): Promise<{ saved: boolean; listingId: string }> {
  const wire = await jsonRequest<{ saved: boolean; listing_id: string }>(
    `${SAVED_BASE}/${encodeURIComponent(id)}/saved`,
    { method: 'PUT' },
  );
  return { saved: wire.saved, listingId: wire.listing_id };
}

export async function unsaveInternship(id: string): Promise<{ saved: boolean; listingId: string }> {
  const wire = await jsonRequest<{ saved: boolean; listing_id: string }>(
    `${SAVED_BASE}/${encodeURIComponent(id)}/saved`,
    { method: 'DELETE' },
  );
  return { saved: wire.saved, listingId: wire.listing_id };
}
