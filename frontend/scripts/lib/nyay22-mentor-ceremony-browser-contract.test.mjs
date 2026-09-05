import { describe, expect, it } from 'vitest';
import {
  NYAY22_BROWSER_ASSERTION_INVENTORY,
  assertExactNyay22BrowserInventory,
  canonicalNyay22BrowserFailureCode,
  scanNyay22BrowserEvidence,
} from './nyay22-mentor-ceremony-browser-contract.mjs';

function cleanRows() {
  return NYAY22_BROWSER_ASSERTION_INVENTORY.map((name) => ({
    name,
    expected: 'sealed contract satisfied',
    actual: { verdict: 'satisfied' },
    pass: true,
  }));
}

describe('NYAY-22 real-Chromium evidence contract', () => {
  it('accepts only the exact ordered 14-row inventory including the live lifecycle', () => {
    const rows = cleanRows();
    expect(assertExactNyay22BrowserInventory(rows)).toEqual({
      total: 14,
      passed: 14,
      failed: 0,
    });
  });

  it('fails closed when a row is missing, duplicated, reordered, or extended', () => {
    const rows = cleanRows();
    for (const malformed of [
      rows.slice(1),
      [rows[0], ...rows.slice(0, -1)],
      [rows[1], rows[0], ...rows.slice(2)],
      [...rows, { ...rows[0] }],
    ]) {
      expect(() => assertExactNyay22BrowserInventory(malformed)).toThrow(
        'NYAY22_BROWSER_ASSERTION_INVENTORY_INVALID',
      );
    }
  });

  it('fails closed on malformed row shapes and non-boolean verdicts', () => {
    const rows = cleanRows();
    expect(() => assertExactNyay22BrowserInventory([
      { ...rows[0], unexpected: true },
      ...rows.slice(1),
    ])).toThrow('NYAY22_BROWSER_ASSERTION_INVENTORY_INVALID');
    expect(() => assertExactNyay22BrowserInventory([
      { ...rows[0], pass: 'true' },
      ...rows.slice(1),
    ])).toThrow('NYAY22_BROWSER_ASSERTION_INVENTORY_INVALID');
  });

  it('detects representative PII, credentials, and authority-bearing material', () => {
    for (const evidence of [
      { diagnostic: 'person@example.test' },
      { diagnostic: '9876543210' },
      { diagnostic: '123456' },
      { diagnostic: 'Bearer eyJheaderpayloadsignature' },
      { diagnostic: 'cookie=opaque-browser-capability' },
      { diagnostic: 'actor=private-selector' },
    ]) {
      expect(scanNyay22BrowserEvidence(evidence)).toEqual({
        pass: false,
        code: 'NYAY22_EVIDENCE_PRIVATE',
      });
    }
  });

  it('accepts privacy-safe state, count, and contract-code diagnostics', () => {
    expect(scanNyay22BrowserEvidence({
      state: 'active',
      transitions: 3,
      code: 'MENTOR_SESSION_REQUIRED',
      cookieAttributes: 'host-only HttpOnly SameSite=Lax Path=/',
    })).toEqual({ pass: true, code: 'NYAY22_EVIDENCE_CLEAN' });
  });

  it('maps arbitrary error messages and unknown errno values to one canonical code', () => {
    expect(canonicalNyay22BrowserFailureCode(
      new Error('opaque-value-that-must-never-enter-evidence'),
    )).toBe('NYAY22_BROWSER_FAILURE');
    expect(canonicalNyay22BrowserFailureCode({
      code: 'UNKNOWN_PRIVATE_IDENTIFIER',
      message: 'safe-looking-message',
    })).toBe('NYAY22_BROWSER_FAILURE');
    expect(canonicalNyay22BrowserFailureCode({ code: 'EPERM' })).toBe('SYSTEM_EPERM');
    expect(canonicalNyay22BrowserFailureCode(
      new Error('NYAY22_PRODUCTION_PREVIEW_START_FAILED'),
    )).toBe('NYAY22_PRODUCTION_PREVIEW_START_FAILED');
    expect(canonicalNyay22BrowserFailureCode(
      new Error('NYAY22_LIVE_FIXTURE_INVALID'),
    )).toBe('NYAY22_LIVE_FIXTURE_INVALID');
  });
});
