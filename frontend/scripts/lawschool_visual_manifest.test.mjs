/**
 * SAATHI-120 (QA F3) — unit proof that the visual-manifest accounting is
 * fail-closed and truthful: refusal entries are never counted as captures,
 * dimension mismatches are captured but never scored, and only approved
 * pairs feed pass/fail totals.
 */
import { describe, it, expect } from 'vitest';
import { manifestCounts } from './lib/lawschool_visual_manifest.mjs';

const APPROVED = 40;

const refusal = () => ({
  pair: 'x', diff: { code: 'FIXTURE_CONTRACT_MISMATCH', gate: 'fail', approvedDeterministicPair: true },
});
const scored = (gate, ratio) => ({
  pair: 'x',
  developed: { sha256: 'a'.repeat(64) },
  reference: { sha256: 'b'.repeat(64) },
  diff: { ratio, threshold: 0.02, gate, approvedDeterministicPair: true },
});
const dimensionMismatch = () => ({
  pair: 'x',
  developed: { sha256: 'a'.repeat(64) },
  reference: { sha256: 'b'.repeat(64) },
  diff: { code: 'CAPTURE_DIMENSION_MISMATCH', ratio: null, gate: 'fail', approvedDeterministicPair: true },
});
const advisory = () => ({
  pair: 'x',
  developed: { sha256: 'a'.repeat(64) },
  reference: { sha256: 'b'.repeat(64) },
  diff: { ratio: 0.5, gate: 'advisory', approvedDeterministicPair: false },
});

describe('manifestCounts (fail-closed visual manifest accounting)', () => {
  it('reports 40/40/0/0/0/40 when the fixture gate fails before any capture', () => {
    const entries = Array.from({ length: APPROVED }, refusal);
    expect(manifestCounts(entries, APPROVED)).toEqual({
      approvedPairs: 40, attemptedPairs: 40, capturedPairs: 0,
      scoredPairs: 0, passedPairs: 0, failedPairs: 40,
    });
  });

  it('counts a capture only when BOTH png hashes exist', () => {
    const halfCaptured = {
      pair: 'x', developed: { sha256: 'a'.repeat(64) },
      diff: { gate: 'fail', approvedDeterministicPair: true },
    };
    expect(manifestCounts([halfCaptured], APPROVED).capturedPairs).toBe(0);
    expect(manifestCounts([scored('pass', 0.001)], APPROVED).capturedPairs).toBe(1);
  });

  it('captures but never scores a dimension mismatch', () => {
    const c = manifestCounts([dimensionMismatch()], APPROVED);
    expect(c).toEqual({
      approvedPairs: 40, attemptedPairs: 1, capturedPairs: 1,
      scoredPairs: 0, passedPairs: 0, failedPairs: 1,
    });
  });

  it('separates pass/fail and excludes unapproved advisory pairs entirely', () => {
    const entries = [scored('pass', 0.001), scored('fail', 0.09), dimensionMismatch(), advisory(), refusal()];
    expect(manifestCounts(entries, APPROVED)).toEqual({
      approvedPairs: 40, attemptedPairs: 4, capturedPairs: 3,
      scoredPairs: 2, passedPairs: 1, failedPairs: 3,
    });
  });

  it('is safe on an empty run (nothing attempted)', () => {
    expect(manifestCounts([], APPROVED)).toEqual({
      approvedPairs: 40, attemptedPairs: 0, capturedPairs: 0,
      scoredPairs: 0, passedPairs: 0, failedPairs: 0,
    });
  });
});
