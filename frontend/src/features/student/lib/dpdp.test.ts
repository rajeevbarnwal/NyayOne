import { describe, expect, it } from 'vitest';
import {
  canSubmitDelete,
  submitRequest,
  DELETE_CONFIRM_PHRASE,
  DEFAULT_NOTIFICATION_PREFS,
} from './dpdp';

describe('DPDP export/delete controls (SAATHI-58)', () => {
  it('requires re-auth AND exact typed confirmation to delete', () => {
    expect(canSubmitDelete({ typedConfirmation: DELETE_CONFIRM_PHRASE, reauthenticated: false })).toBe(false);
    expect(canSubmitDelete({ typedConfirmation: 'delete', reauthenticated: true })).toBe(false);
    expect(canSubmitDelete({ typedConfirmation: DELETE_CONFIRM_PHRASE, reauthenticated: true })).toBe(true);
  });

  it('records export/delete requests', () => {
    expect(submitRequest('export', '2026-07-07').status).toBe('requested');
    expect(submitRequest('delete', '2026-07-07').type).toBe('delete');
  });

  it('defaults lock-screen sensitive activity to off', () => {
    expect(DEFAULT_NOTIFICATION_PREFS.lockscreenSensitiveActivity).toBe(false);
    expect(DEFAULT_NOTIFICATION_PREFS.deadlineReminders).toBe(true);
  });
});
