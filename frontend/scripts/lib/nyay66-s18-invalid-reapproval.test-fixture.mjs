// Test-only exact proposal data; these pins never grant owner approval.
import {approveException,canonical} from './nyay66-enforcement.mjs';
export const s18InvalidPredecessor={
  "screen": "S-18",
  "viewport": "desktop",
  "theme": "light",
  "referenceSha256": "7471d75e1e62e9b9af8b0423520e80c6e2ba2bfdd4321abab142fe2fcbea674d",
  "liveSha256": "f89196cfc582138e8544e684dc622e14f4785b1a16e143470e12c732dd8bb393",
  "checks": [
    "controls",
    "geometry",
    "pixels",
    "text"
  ],
  "reason": "S-18 light default save-on-change; exact reference/live images only. Settings has no name projection: honest P / Your profile fallback replaces prototype AN / Aditi Nair. Notification switches use the visible label as accessible name and the help as description. Server fixture Product updates=false replaces prototype true. Hindi remains unavailable/Coming soon; Dark stores a future preference only, not a completed dark UI. Closed-disclosure descendants appear in the unchanged structural inventory; their recorded geometry reflects this capability/helper content, not displacement of visible closed-state controls. Synthetic notification-field 422 uses truthful selected-preference rollback/retry wording rather than a language-only claim; expanded Dark/Hindi annotations and error wrapping intentionally reflow the disclosure and following action. Desktop retains Home/Profile routes plus disabled Research/Calendar/Careers as 48px buttons instead of static prototype labels; their control inventory and header spacing account for the desktop structural flags. The Privacy action icon and, where present, framed retry/back icons sit 1 CSS px below the prototype nested-inline baseline (within the existing 1px geometry tolerance), with identical SVG paths, size and color. This is a disclosed baseline offset, not claimed to be antialiasing. Small raw rasterization differences on otherwise matching paths are included in these exact images. No accessibility, overflow, unknown error, tolerance or reference waiver.",
  "approvalPr": 68
};
export const s18InvalidReplacement={
  "screen": "S-18",
  "viewport": "desktop",
  "theme": "light",
  "referenceSha256": "7471d75e1e62e9b9af8b0423520e80c6e2ba2bfdd4321abab142fe2fcbea674d",
  "liveSha256": "bb8c12e85ccae1010ecee94ba68e0e5468dab6b910d53304812a75099ecf6e38",
  "checks": [
    "controls",
    "geometry",
    "pixels",
    "text"
  ],
  "reason": "S-18 light default save-on-change; exact reference/live images only. Settings has no name projection: honest P / Your profile fallback replaces prototype AN / Aditi Nair. Notification switches use the visible label as accessible name and the help as description. Server fixture Product updates=false replaces prototype true. Hindi remains unavailable/Coming soon; Dark stores a future preference only, not a completed dark UI. Closed-disclosure descendants appear in the unchanged structural inventory; their recorded geometry reflects this capability/helper content, not displacement of visible closed-state controls. Synthetic notification-field 422 uses truthful selected-preference rollback/retry wording rather than a language-only claim; expanded Dark/Hindi annotations and error wrapping intentionally reflow the disclosure and following action. Desktop retains Home/Profile routes plus disabled Research/Calendar/Careers as 48px buttons instead of static prototype labels; their control inventory and header spacing account for the desktop structural flags. The Privacy action icon and, where present, framed retry/back icons sit 1 CSS px below the prototype nested-inline baseline (within the existing 1px geometry tolerance), with identical SVG paths, size and color. This is a disclosed baseline offset, not claimed to be antialiasing. Small raw rasterization differences on otherwise matching paths are included in these exact images. No accessibility, overflow, unknown error, tolerance or reference waiver. Capture-only replacement disclosure for PR #82: only S-18 desktop validation-error now uses version-matched isolated Chromium with --disable-partial-raster. At hosted head 6454ad0933592eb371fce848ad9d18a377ba5024 (run 41331327276), 42 rounded-border pixels differ from the prior approved live SHA f89196cfc582138e8544e684dc622e14f4785b1a16e143470e12c732dd8bb393 by at most one RGB level, within x34-856/y453-759. Live/reference DOM surfaces, text, controls, request evidence, error inventory and accessibility results are identical. The reference and original content/identity disclosures, including the 1 CSS px icon-baseline offset above, are retained. No product change, image retry, approval-hash selection or pixel postprocessing is involved. This replacement covers only this exact desktop validation-error image pair; it does not authorize another state, viewport, reference, tolerance, enforcement or accessibility change.",
  "approvalPr": 82
};
export const s18InvalidPredecessorHash="fa3094fba3ad64b089539336fad86c4a7e207fc8cd768759d4d304f03e6e9dfc";
export const s18InvalidReplacementHash="8ecf1ad9213ae28938a13f1321c9d9bafba48cb10c75623608dbf89735d134b9";
for(const [entry,hash] of [[s18InvalidPredecessor,s18InvalidPredecessorHash],[s18InvalidReplacement,s18InvalidReplacementHash]])
 if(approveException(entry,null,{s18:true})!==hash)throw Error('S18_INVALID_REPLACEMENT_PIN_MISMATCH');
export function normalizeS18InvalidForTest(exceptions){
 const targets=exceptions.filter(e=>e.screen==='S-18'&&e.viewport==='desktop'&&e.referenceSha256===s18InvalidPredecessor.referenceSha256);
 if(targets.length!==1)throw Error('S18_INVALID_REPLACEMENT_CARDINALITY');
 const target=targets[0];
 if(canonical(target)!==canonical(s18InvalidPredecessor)&&canonical(target)!==canonical(s18InvalidReplacement))throw Error('S18_INVALID_REPLACEMENT_SCOPE');
 return exceptions.map(e=>structuredClone(e===target?s18InvalidPredecessor:e));
}
// Raw-byte snapshots substitute only the exact formatted target record. Every
// other byte (including historical whitespace and order) remains comparable.
export function normalizeS18InvalidPolicyBytesForTest(bytes){
 const policy=JSON.parse(bytes);normalizeS18InvalidForTest(policy.exceptions);
 const target=policy.exceptions.find(e=>e.screen==='S-18'&&e.viewport==='desktop'&&e.referenceSha256===s18InvalidPredecessor.referenceSha256);
 if(canonical(target)===canonical(s18InvalidPredecessor))return bytes;
 const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    ');
 const exact=record(s18InvalidReplacement);
 if(bytes.split(exact).length!==2)throw Error('S18_INVALID_REPLACEMENT_BYTES');
 return bytes.replace(exact,record(s18InvalidPredecessor));
}
