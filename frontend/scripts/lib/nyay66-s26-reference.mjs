// Additive reference-generation support only. This module does not promote rows.
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {PNG} from 'pngjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {canonical,digest} from './nyay66-enforcement.mjs';
export const S26_STATES=Object.freeze(['empty','loading','error','nonempty']);
export const S26_VIEWPORTS=Object.freeze([
  Object.freeze({id:'mobile390',preset:'m390',width:390,height:844}),
  Object.freeze({id:'desktop',preset:'d1440',width:1440,height:1024}),
]);
export const S26_PINS=Object.freeze({chromium:'149.0.7827.55',playwright:'1.61.1',platform:'linux-x64'});
// Included in the protected bundle: a new dispatch-workflow revision cannot
// silently claim this capture approval by changing an unprotected policy seal.
const S26_CALIBRATION_WORKFLOW_SHA256='13a90d17da895af02705ad8a18e39540db380b8ab3707e9621336cd3e1afc9db';
export function verifyS26ControlWorkflow(bytes){
  if(digest(bytes)!==S26_CALIBRATION_WORKFLOW_SHA256)throw Error('S26_CONTROL_WORKFLOW_MISMATCH');
  return true;
}
const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
export async function loadS26Source(root){
  // Verifies ZIP, all member hashes, state inventory and embedded assets first.
  // No archive extraction and no execution of the package's helper scripts.
  const data=await loadContinuation(root);
  const html=execFileSync('unzip',['-p',resolve(root,data.archive),'NYAYONE_S01_S35_v3.2.1.08/NYAYONE_S01_S35_v3.2.1.08.html'],{maxBuffer:10*1024*1024});
  if(digest(html)!==data.htmlSha256)throw Error('S26_SOURCE_MISMATCH');
  const states=data.screens.find(s=>s.screen==='S-26').states.map(([state])=>state);
  if(canonical(states)!==canonical(S26_STATES))throw Error('S26_STATE_SOURCE_MISMATCH');
  return {data,html};
}
export function validateS26Pins(actual,fonts){
  for(const [key,value] of Object.entries(S26_PINS))if(actual[key]!==value)throw Error(`S26_CALIBRATION_PIN_MISMATCH:${key}`);
  if(!fonts||!Object.keys(fonts).length||Object.values(fonts).some(value=>!hash(value))||canonical(actual.fonts)!==canonical(fonts))throw Error('S26_FONT_PIN_MISMATCH');
  return true;
}
export function verifyS26PNG(row,bytes){
  if(!hash(row.sha256)||digest(bytes)!==row.sha256)throw Error('S26_REFERENCE_BYTES_MISMATCH');
  const image=PNG.sync.read(bytes);
  if(canonical([image.width,image.height])!==canonical(row.dimensions))throw Error('S26_REFERENCE_DIMENSION_MISMATCH');
  return true;
}
export function validateS26Manifest(manifest,data){
  if(manifest?.schema!==1||manifest.purpose!=='UNIMPORTED_REFERENCE_CALIBRATION'||manifest.screen!=='S-26'||manifest.theme!=='light'
    ||manifest.approval!==data.designApproval||manifest.sourceArchiveSha256!==data.archiveSha256||manifest.sourceSha256!==data.htmlSha256
    ||canonical(manifest.embeddedResources)!==canonical(data.inventory.embeddedResources)
    ||!['producerHead','controlHead'].every(key=>/^[a-f0-9]{40}$/.test(manifest[key]||'')))throw Error('S26_CALIBRATION_SOURCE_MISMATCH');
  validateS26Pins(manifest,manifest.fonts);
  if(canonical(manifest.deferredStates)!==canonical([])||!Array.isArray(manifest.rows)||manifest.rows.length!==8)throw Error('S26_CALIBRATION_INVENTORY');
  const seen=new Set();
  for(const row of manifest.rows){
    const vp=S26_VIEWPORTS.find(v=>v.id===row.viewport),key=`${row.view}:${row.viewport}`;
    if(!vp||!S26_STATES.some(s=>row.view===`s26-${s}`)||seen.has(key)||row.file!==`${row.view}-${row.viewport}-0.png`
      ||!hash(row.sha256)||!Array.isArray(row.sampleHashes)||row.sampleHashes.length!==3||row.sampleHashes.some(h=>h!==row.sha256)
      ||canonical(row.dimensions)!==canonical([vp.width,vp.height]))throw Error('S26_CALIBRATION_ROW_INVALID');
    const surface=row.surface;
    if(!surface||!['controls','headings','masks'].every(k=>Array.isArray(surface[k]))||typeof surface.text!=='string'
      ||surface.overflow!==0||surface.dimensions?.[0]!==vp.width||!Number.isFinite(surface.dimensions?.[1])||surface.dimensions[1]<vp.height
      ||!row.fontStack||typeof row.fontStack.viewport!=='string'||!Array.isArray(row.fontStack.faces)
      ||row.reviewerFrame?.borderRadius!=='0px'||row.reviewerFrame.x!==0||row.reviewerFrame.y!==0)throw Error('S26_CALIBRATION_SURFACE_INVALID');
    seen.add(key);
  }
  return true;
}
