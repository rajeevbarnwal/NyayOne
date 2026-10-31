// Exact test-only desktop export-failed replacement data; pins never grant approval.
// Runtime capture, evaluation and production must not import this module.
import {approveException,canonical} from './nyay66-enforcement.mjs';
export const s19ExportRasterPredecessor={
  "screen": "S-19",
  "viewport": "desktop",
  "theme": "light",
  "referenceSha256": "8f725f2894a81303b1b56d9d05f77d373fe728fc08b3b0ec2d506ad8497bc99d",
  "liveSha256": "a9dce0a2886f178afaabee4f78b559ae3111c36cf92da2581c718e22b7b35bfe",
  "checks": [
    "controls",
    "geometry",
    "pixels",
    "text"
  ],
  "reason": "S-19 export-failed, desktop, light; exact reference/live image pair only. The settings contract has no profile-name projection: honest P / Your profile fallback replaces prototype AN / Aditi Nair. The failed request retains its real 32-character ID and offers Request again/Dismiss; ID wrapping accounts for downstream vertical movement. Residual icon baseline: Request a copy of my data SVG is +1px vertically relative to its own button versus the reference; Request again SVG is +1px vertically relative to its own button versus the reference; Dismiss SVG is +1px vertically relative to its own button versus the reference; Delete my account SVG is +1px vertically relative to its own button versus the reference. Button geometry is not relaxed for this offset. Desktop retains Home/Profile navigation and disabled Research/Calendar/Careers as 48px buttons rather than static prototype labels, accounting for header control-inventory/geometry flags. No accessibility, overflow, unexpected error, reference, tolerance, enforcement, or unrelated-screen waiver. Synthetic API evidence is not live-backend or independent QA certification.",
  "approvalPr": 70
};
export const s19ExportRasterReplacement={
  "screen": "S-19",
  "viewport": "desktop",
  "theme": "light",
  "referenceSha256": "8f725f2894a81303b1b56d9d05f77d373fe728fc08b3b0ec2d506ad8497bc99d",
  "liveSha256": "a17b7b3006e79e3338de07d5770583d5d9d4579990162d5e48bf293fc0430606",
  "checks": [
    "controls",
    "geometry",
    "pixels",
    "text"
  ],
  "reason": "S-19 export-failed, desktop, light; exact reference/live image pair only. The settings contract has no profile-name projection: honest P / Your profile fallback replaces prototype AN / Aditi Nair. The failed request retains its real 32-character ID and offers Request again/Dismiss; ID wrapping accounts for downstream vertical movement. Residual icon baseline: Request a copy of my data SVG is +1px vertically relative to its own button versus the reference; Request again SVG is +1px vertically relative to its own button versus the reference; Dismiss SVG is +1px vertically relative to its own button versus the reference; Delete my account SVG is +1px vertically relative to its own button versus the reference. Button geometry is not relaxed for this offset. Desktop retains Home/Profile navigation and disabled Research/Calendar/Careers as 48px buttons rather than static prototype labels, accounting for header control-inventory/geometry flags. No accessibility, overflow, unexpected error, reference, tolerance, enforcement, or unrelated-screen waiver. Synthetic API evidence is not live-backend or independent QA certification. Capture-raster replacement disclosure for PR #84: the isolated single-row Chromium capture with --disable-partial-raster produces the exact new live image above. Relative to the prior approved live SHA a9dce0a2886f178afaabee4f78b559ae3111c36cf92da2581c718e22b7b35bfe, 10 rounded-border pixels (18 RGB channels) differ by at most one RGB level at x34-36/y775-780. The new bytes match the previous hosted capture before isolation; isolation also passes local varied-font-timing reproducibility checks. Measured DOM geometry, text, controls, API evidence and accessibility results are identical to the prior approved capture. The reference image and all prior functional/design-variant disclosures are retained. This approval covers only this exact desktop export-failed image pair; no other state or viewport, reference, tolerance, enforcement or accessibility rule is changed. No images were selected by hash or postprocessed.",
  "approvalPr": 84
};
export const s19ExportRasterReplacementHash='498e9cdb01e52679f0046de5d2697fe85126d3d758d1841c086a9977cd70fd15';
export const s19ExportRasterPredecessorHash=approveException(s19ExportRasterPredecessor,null,{s19:true});
if(approveException(s19ExportRasterReplacement,null,{s19:true})!==s19ExportRasterReplacementHash)throw Error('S19_EXPORT_REPLACEMENT_PIN_MISMATCH');
export function normalizeS19ExportRasterForTest(exceptions){
  const targets=exceptions.filter(e=>e.screen==='S-19'&&e.viewport==='desktop'&&e.referenceSha256===s19ExportRasterPredecessor.referenceSha256);
  if(targets.length!==1)throw Error('S19_EXPORT_REPLACEMENT_CARDINALITY');
  const target=targets[0];
  if(canonical(target)!==canonical(s19ExportRasterPredecessor)&&canonical(target)!==canonical(s19ExportRasterReplacement))throw Error('S19_EXPORT_REPLACEMENT_SCOPE');
  return exceptions.map(e=>structuredClone(e===target?s19ExportRasterPredecessor:e));
}
