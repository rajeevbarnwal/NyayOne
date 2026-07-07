/**
 * DPDP data-principal request logic (SAATHI-58 / S3.2): export and delete.
 *
 * Delete requires re-authentication AND a typed confirmation before it can be
 * submitted. Requests are handed to a stub workflow boundary in this batch (no
 * external network calls; server wiring lands with the service-logic ticket).
 */

export type DataRequestType = 'export' | 'delete';
export type DataRequestStatus = 'idle' | 'requested' | 'processing' | 'complete' | 'failed';

export interface DataRequest {
  readonly type: DataRequestType;
  readonly status: DataRequestStatus;
  readonly requestedAt: string | null;
}

/** The exact phrase a user must type to confirm account deletion. */
export const DELETE_CONFIRM_PHRASE = 'DELETE';

export interface DeleteGuard {
  readonly typedConfirmation: string;
  readonly reauthenticated: boolean;
}

/** Delete is only submittable with re-auth + exact typed confirmation. */
export function canSubmitDelete(g: DeleteGuard): boolean {
  return g.reauthenticated && g.typedConfirmation.trim() === DELETE_CONFIRM_PHRASE;
}

export function newRequest(type: DataRequestType): DataRequest {
  return { type, status: 'idle', requestedAt: null };
}

export function submitRequest(type: DataRequestType, nowISO: string): DataRequest {
  return { type, status: 'requested', requestedAt: nowISO };
}

/** Notification-preference model surfaced in settings (S-18). */
export interface NotificationPrefs {
  readonly deadlineReminders: boolean;
  readonly lockscreenSensitiveActivity: boolean;
}

export const DEFAULT_NOTIFICATION_PREFS: NotificationPrefs = {
  deadlineReminders: true,
  // Sensitive activity is OFF by default — never expose it on a locked device
  // without explicit user preference.
  lockscreenSensitiveActivity: false,
};
