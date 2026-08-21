import { apiFetch, type ApiOptions } from '../../../lib/apiClient';
import { clearStudentBrowserContext } from './studentBrowserContext';

interface StudentApiLifecycleOptions {
  /** Session discovery handles notification itself to avoid an auth refresh loop. */
  notifyAuthChanged?: boolean;
}

function errorCode(value: unknown): string | null {
  if (!value || typeof value !== 'object') return null;
  const body = value as {
    detail?: unknown;
    error?: { code?: unknown; detail?: unknown };
  };
  if (body.detail && typeof body.detail === 'object') {
    const code = (body.detail as { code?: unknown }).code;
    return typeof code === 'string' ? code : null;
  }
  if (body.error?.detail && typeof body.error.detail === 'object') {
    const code = (body.error.detail as { code?: unknown }).code;
    return typeof code === 'string' ? code : null;
  }
  return typeof body.error?.code === 'string' ? body.error.code : null;
}

/**
 * Student-session-aware fetch boundary. It clones error responses so typed
 * feature adapters retain sole ownership of the original response body.
 */
export async function studentApiFetch(
  path: string,
  opts: ApiOptions = {},
  lifecycle: StudentApiLifecycleOptions = {},
): Promise<Response> {
  const response = await apiFetch(path, opts);
  if (response.status !== 401) return response;

  try {
    const body: unknown = await response.clone().json();
    if (errorCode(body) === 'authentication_required') {
      clearStudentBrowserContext({ notifyAuthChanged: lifecycle.notifyAuthChanged !== false });
    }
  } catch {
    // A malformed 401 is insufficient evidence to destroy a valid OTP flow:
    // incorrect OTP is also 401. Only the exact typed code crosses this boundary.
  }
  return response;
}
