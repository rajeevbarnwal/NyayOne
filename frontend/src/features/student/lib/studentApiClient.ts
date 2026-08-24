import { apiFetch, type ApiOptions } from '../../../lib/apiClient';
import {
  clearStudentBrowserContext,
  type StudentAuthTransition,
  withStudentAuthRequestLease,
} from './studentBrowserContext';
import {
  captureActiveProfileReauthDraft,
  hasProfileReauthHandoff,
  restoreCapturedProfileReauthDraft,
} from '../profile/profileReauthHandoff';

const STUDENT_AUTH_LOSS_CODES = new Set([
  'authentication_required',
  'session_authority_required',
]);

export interface StudentApiLifecycleOptions {
  /** Session discovery handles notification itself to avoid an auth refresh loop. */
  notifyAuthChanged?: boolean;
  /** Exact process-only capability proving this request runs inside the exclusive cookie transition. */
  authTransition?: StudentAuthTransition;
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
  const response = await withStudentAuthRequestLease(async () => {
    const result = await apiFetch(path, opts);
    // Retain the shared request lease until the complete response has been
    // observed. Feature adapters still own the untouched original body.
    await result.clone().arrayBuffer();
    return result;
  }, lifecycle.authTransition);
  if (response.status !== 401) return response;

  try {
    const body: unknown = await response.clone().json();
    if (STUDENT_AUTH_LOSS_CODES.has(errorCode(body) ?? '')) {
      const capturedDraft = captureActiveProfileReauthDraft();
      // The transition-start teardown can run asynchronously after this
      // response handler returns. Preserve either the newly captured draft or
      // an earlier concurrent 401 handoff through that second teardown; a
      // normal logout/deletion still calls the boundary without this option.
      const preserveRetainedDraft = capturedDraft !== null || hasProfileReauthHandoff();
      clearStudentBrowserContext({
        notifyAuthChanged: lifecycle.notifyAuthChanged !== false,
        preserveProfileReauthHandoff: preserveRetainedDraft,
      });
      // Ordinary teardown must erase every active/retained draft first. Only the
      // exact snapshot captured from this failing form is then reinstalled, and
      // it remains unusable until a fresh session proves the same actor.
      if (capturedDraft !== null) restoreCapturedProfileReauthDraft(capturedDraft);
    }
  } catch {
    // A malformed 401 is insufficient evidence to destroy a valid OTP flow:
    // incorrect OTP is also 401. Only the exact typed code crosses this boundary.
  }
  return response;
}
