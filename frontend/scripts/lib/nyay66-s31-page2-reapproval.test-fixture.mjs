// Test-only exact capture-framing proposal. These pins never grant runtime approval.
import {approveException,canonical} from './nyay66-enforcement.mjs';
export const s31Page2Predecessor={
  "screen": "S-31",
  "viewport": "mobile390",
  "theme": "light",
  "referenceSha256": "045e6be0a49e52f47befacfc73721ad33766063ffbf4f3b9ae68c4ec0497ab86",
  "liveSha256": "911dffc85653f977298decf9dd5fecb27d3e184c4827ab2ad869537ec8c53538",
  "checks": [
    "controls",
    "geometry",
    "pixels",
    "text"
  ],
  "reason": "S-31 page-2, mobile390, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. The real Next action requests offset 3; server-shaped records are sorted before pagination, so page 2 is Farhan/Sneha instead of prototype Kavya/Sneha. Preserve server names/headlines, prices, null ratings and false verification flags, derived AF initials, grammatical \"1 year\", and confirmed total/page. Detail actions are real full-name links; Previous/Next accessible names add \"page\". Keyboard focus on the result summary adds the meaningful visible outline after navigation. Matched DOM-control geometry disclosure (live minus frozen): the paired visible controls retain identical boxes. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
  "approvalPr": 90
};
export const s31Page2Replacement={
  "screen": "S-31",
  "viewport": "mobile390",
  "theme": "light",
  "referenceSha256": "045e6be0a49e52f47befacfc73721ad33766063ffbf4f3b9ae68c4ec0497ab86",
  "liveSha256": "1415cc882ab17f824ecb280491795c496c3bd0f218204e8ddfcf21f98507bbdd",
  "checks": [
    "controls",
    "geometry",
    "pixels",
    "text"
  ],
  "reason": "S-31 page-2, mobile390, light. Exact hosted live-route capture with synthetic API replies at 1ea4890a2329edebc485f6fb3b89bc3962f398b2 (run 41874672362); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. The real Next action requests offset 3; server-shaped records are sorted before pagination, so page 2 is Farhan/Sneha instead of prototype Kavya/Sneha. Preserve server names/headlines, prices, null ratings and false verification flags, derived AF initials, grammatical \"1 year\", and confirmed total/page. Detail actions are real full-name links; Previous/Next accessible names add \"page\". Keyboard focus on the result summary adds the meaningful visible outline after navigation. Matched DOM-control geometry disclosure (live minus frozen): the paired visible controls retain identical boxes. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver. Capture-framing replacement disclosure: the S-31-only test fixture now records a deterministic document-top viewport AFTER the genuine Next request to offset 3 and successful product focus handoff. The previously approved mobile image recorded scrollY=10; this exact replacement records scrollY=0. The fixed header is unchanged while the body appears 10px lower in the viewport. Content, request order, focused element s31-results-summary, visible focus outline, product behavior and underlying document dimensions are unchanged. The report labels viewportFraming.testOnly=true, before/after scroll, focusPreserved=true, domModified=false and pixelPostprocessing=false. This is a capture-framing difference, not server-data-only drift, antialiasing or a functional/accessibility waiver. The fixture does not repair or move focus, alter DOM/CSS, delay responses, select retry images or change reference/tolerance/enforcement rules. It fails closed if focus is missing or changes. Only this exact reference/live pair and the already-disclosed identity/data/design/interaction differences above are covered; the other 247 approval records remain unchanged.",
  "approvalPr": 90
};
export const s31Page2ReplacementHash="daafec02c95e0c5f33baa7e318502d9b08c9c8a0ab1b7f55e53d1b76d4ef16d0";
if(approveException(s31Page2Replacement,null,{s31:true})!==s31Page2ReplacementHash)throw Error('S31_PAGE2_REPLACEMENT_PIN_MISMATCH');
export function normalizeS31Page2ForTest(exceptions){
 const targets=exceptions.filter(e=>e.screen==='S-31'&&e.viewport==='mobile390'&&e.referenceSha256===s31Page2Predecessor.referenceSha256);
 if(targets.length!==1)throw Error('S31_PAGE2_REPLACEMENT_CARDINALITY');
 const target=targets[0];
 if(canonical(target)!==canonical(s31Page2Predecessor)&&canonical(target)!==canonical(s31Page2Replacement))throw Error('S31_PAGE2_REPLACEMENT_SCOPE');
 return exceptions.map(e=>structuredClone(e===target?s31Page2Predecessor:e));
}
// Substitute only this exact formatted proposal in historical byte snapshots.
// Runtime policy and approvals are never modified by these test-only helpers.
export function normalizeS31Page2PolicyBytesForTest(bytes){
 const policy=JSON.parse(bytes);normalizeS31Page2ForTest(policy.exceptions);
 const target=policy.exceptions.find(e=>e.screen==='S-31'&&e.viewport==='mobile390'&&e.referenceSha256===s31Page2Predecessor.referenceSha256);
 if(canonical(target)===canonical(s31Page2Predecessor))return bytes;
 const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    '),exact=record(s31Page2Replacement);
 if(bytes.split(exact).length!==2)throw Error('S31_PAGE2_REPLACEMENT_BYTES');
 return bytes.replace(exact,record(s31Page2Predecessor));
}
