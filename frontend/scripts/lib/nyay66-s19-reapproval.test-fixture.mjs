// Test-only regression data. Never imported by capture, evaluation or production.
// Pins are not approval: the hosted gate must still read the owner's exact comment.
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {approveException,canonical} from './nyay66-enforcement.mjs';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const options={r2:true,s18:true,s19:true,s20:true};
const before=JSON.parse(execFileSync('git',['show','48eeac1973053eb2fd8e4080091dd345bf08db69:frontend/scripts/nyay66-policy.json'],{cwd:root}));
export const s19RasterPredecessor=before.exceptions.find(e=>e.screen==='S-19'&&e.viewport==='mobile390'&&e.referenceSha256==='616c28709cda73e29591c57e75b25931cae0703f86a1c92b6b2ee97385d3e1ef');
if(approveException(s19RasterPredecessor,null,options)!=='94ffad6c1ef1010a9e86c331d0cd52623ff9517d59641f0f222ba1b773000127')throw Error('S19_PREDECESSOR_PIN_MISMATCH');
export const s19RasterReplacement={...s19RasterPredecessor,
  liveSha256:'5d0d65991eab65170212526da6ef4305ece72b912b14934e3888748800db81d7',
  reason:s19RasterPredecessor.reason+' Capture-path replacement on PR72: the isolated same-version Chromium capture with partial raster disabled produces the stable newer rounded-card border pattern. Relative to the historical approved live image, exactly 21 pixels / 38 channels change by at most 1 RGB level at x16 y561 width358 height6; recorded text, controls, geometry and overflow are identical. This is a disclosed test-capture raster artifact, not a product change or functional/accessibility waiver. The existing +1px Use a different number icon-baseline disclosure remains unchanged. No reference, tolerance, evaluator, enforcement or unrelated approval changes; historical evidence and the prior approval remain preserved.',
  approvalPr:72,
};
// Normalize a CLONE only inside tests so every old byte/order/hash assertion
// remains intact. No broad PR72 allowance and no change to the real policy.
export function normalizeS19RasterForTest(exceptions){
  const targets=exceptions.filter(e=>e.screen==='S-19'&&e.viewport==='mobile390'&&e.referenceSha256===s19RasterPredecessor.referenceSha256);
  if(targets.length!==1)throw Error('S19_REPLACEMENT_CARDINALITY');
  const target=targets[0];
  if(canonical(target)!==canonical(s19RasterPredecessor)&&canonical(target)!==canonical(s19RasterReplacement))throw Error('S19_REPLACEMENT_SCOPE');
  return exceptions.map(e=>structuredClone(e===target?s19RasterPredecessor:e));
}
