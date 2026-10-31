// Exact test-only data for the proposed PR84 mobile delete-typed replacement.
// Never imported by capture, evaluation or product code; pins do not grant approval.
import {approveException,canonical} from './nyay66-enforcement.mjs';
import {normalizeS19ExportRasterForTest} from './nyay66-s19-export-reapproval.test-fixture.mjs';
export const s19TypedRasterPredecessor={
  "screen": "S-19",
  "viewport": "mobile390",
  "theme": "light",
  "referenceSha256": "cf43a433557fd344be4b0b75844d15978c0e73dc2dc1c1f4b1fa32fc3e387ec7",
  "liveSha256": "6411a35b6a365e7363684030400ecf0559205518689323a4070b0e8745f707ab",
  "checks": [
    "controls",
    "pixels",
    "text"
  ],
  "reason": "S-19 delete-typed, mobile390, light; exact reference/live image pair only. The settings contract has no profile-name projection: honest P / Your profile fallback replaces prototype AN / Aditi Nair. The confirmed server authority permits the final focused DELETE step, while the final action remains disabled until exact uppercase input. Presentation-only alignment preserves those controls. Residual icon baseline: Keep my account SVG is +1px vertically relative to its own button versus the reference. Button geometry is not relaxed for this offset. No accessibility, overflow, unexpected error, reference, tolerance, enforcement, or unrelated-screen waiver. Synthetic API evidence is not live-backend or independent QA certification.",
  "approvalPr": 70
};
export const s19TypedRasterReplacement={
  "screen": "S-19",
  "viewport": "mobile390",
  "theme": "light",
  "referenceSha256": "cf43a433557fd344be4b0b75844d15978c0e73dc2dc1c1f4b1fa32fc3e387ec7",
  "liveSha256": "e8cc4d92861229cb21a42ddd3af98d3449a7539da547611e11d308bf0b925b05",
  "checks": [
    "controls",
    "pixels",
    "text"
  ],
  "reason": "S-19 delete-typed, mobile390, light; exact reference/live image pair only. The settings contract has no profile-name projection: honest P / Your profile fallback replaces prototype AN / Aditi Nair. The confirmed server authority permits the final focused DELETE step, while the final action remains disabled until exact uppercase input. Presentation-only alignment preserves those controls. Residual icon baseline: Keep my account SVG is +1px vertically relative to its own button versus the reference. Button geometry is not relaxed for this offset. No accessibility, overflow, unexpected error, reference, tolerance, enforcement, or unrelated-screen waiver. Synthetic API evidence is not live-backend or independent QA certification. Capture-raster replacement disclosure for PR #84: the isolated single-row Chromium capture with --disable-partial-raster produces the exact new live image above. Relative to the prior approved live SHA 6411a35b6a365e7363684030400ecf0559205518689323a4070b0e8745f707ab, 21 rounded-border pixels (38 RGB channels) differ by at most one RGB level at x16-373/y567-572. Measured DOM geometry, text, controls, API evidence and accessibility results are identical. The reference image and existing server-derived disclosures, including the +1px Keep my account icon baseline, are retained. This approval covers only this exact mobile delete-typed image pair; no other state or viewport is covered, and no tolerance, reference, enforcement or accessibility rule is changed.",
  "approvalPr": 84
};
export const s19TypedRasterPredecessorHash='c50117ab9b69df418aa96b54e3ed2884ad639d3d7e90d6b3de5a816164b96b32';
export const s19TypedRasterReplacementHash='b3e960e2099f3c0c8f732bd6e4b96091f2f91225e32c84a66f1b7c70da101c2d';
for(const [entry,hash] of [[s19TypedRasterPredecessor,s19TypedRasterPredecessorHash],[s19TypedRasterReplacement,s19TypedRasterReplacementHash]])
  if(approveException(entry,null,{s19:true})!==hash)throw Error('S19_TYPED_REPLACEMENT_PIN_MISMATCH');
export function normalizeS19TypedRasterForTest(exceptions){
  const targets=exceptions.filter(e=>e.screen==='S-19'&&e.viewport==='mobile390'&&e.referenceSha256===s19TypedRasterPredecessor.referenceSha256);
  if(targets.length!==1)throw Error('S19_TYPED_REPLACEMENT_CARDINALITY');
  const target=targets[0];
  if(canonical(target)!==canonical(s19TypedRasterPredecessor)&&canonical(target)!==canonical(s19TypedRasterReplacement))throw Error('S19_TYPED_REPLACEMENT_SCOPE');
  return exceptions.map(e=>structuredClone(e===target?s19TypedRasterPredecessor:e));
}
// Historical snapshot assertions use a clone; each replacement is independently
// exact-checked. The real policy and runtime owner-approval checks are untouched.
export const s19TypedPolicyForTest=policy=>({...policy,exceptions:normalizeS19TypedRasterForTest(normalizeS19ExportRasterForTest(policy.exceptions))});
