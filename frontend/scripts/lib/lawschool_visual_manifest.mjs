/**
 * SAATHI-120 (QA F3) — TRUTHFUL, fail-closed accounting for the Option C+
 * visual manifest.
 *
 * The previous manifest reported `captured: visEntries.length`, which counted
 * refusal entries as captures: on a fixture-gate failure it claimed
 * "captured: 40" although zero screenshots existed. Evidence must never
 * overstate what physically happened, so the schema now separates:
 *
 *   approvedPairs  — size of the frozen approved deterministic pair matrix
 *   attemptedPairs — approved pairs the harness reached a verdict for
 *                    (including fail-closed refusals recorded without capture)
 *   capturedPairs  — approved pairs with BOTH developed and reference PNGs
 *                    actually written (a sha256 exists for each side)
 *   scoredPairs    — captured pairs where a pixel-diff ratio was computed
 *                    (dimension mismatches are captured but never scored)
 *   passedPairs    — approved pairs whose strict gate is 'pass'
 *   failedPairs    — approved pairs whose strict gate is 'fail'
 *
 * On a fixture-gate failure the truthful values are therefore
 * approved 40 / attempted 40 / captured 0 / scored 0 / passed 0 / failed 40.
 */

/** @returns {{approvedPairs:number,attemptedPairs:number,capturedPairs:number,scoredPairs:number,passedPairs:number,failedPairs:number}} */
export function manifestCounts(visEntries, approvedPairCount) {
  const approved = visEntries.filter((e) => e?.diff?.approvedDeterministicPair === true);
  const captured = approved.filter(
    (e) => typeof e?.developed?.sha256 === 'string' && typeof e?.reference?.sha256 === 'string',
  );
  return {
    approvedPairs: approvedPairCount,
    attemptedPairs: approved.length,
    capturedPairs: captured.length,
    scoredPairs: captured.filter((e) => typeof e.diff.ratio === 'number').length,
    passedPairs: approved.filter((e) => e.diff.gate === 'pass').length,
    failedPairs: approved.filter((e) => e.diff.gate === 'fail').length,
  };
}
