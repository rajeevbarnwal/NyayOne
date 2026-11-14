// Additive reference-generation support only. This module does not promote rows.
import {execFileSync} from 'node:child_process';
import {resolve} from 'node:path';
import {PNG} from 'pngjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {canonical,digest} from './nyay66-enforcement.mjs';
export const S35_STATES=Object.freeze(["loading", "list", "past", "list-empty", "list-error", "detail", "detail-error", "reschedule", "reschedule-closed", "reschedule-conflict", "cancel-confirm", "cancel-failed", "attendance", "dispute", "disputed", "review", "review-invalid", "review-moderation", "review-edit", "review-window-closed", "prejoin", "prejoin-ready", "prejoin-denied", "join-refused", "video-disabled", "room", "rate-limited", "cancelled-full-refund", "cancelled-no-auto-refund", "refund-pending", "refund-failed", "cancel-stale", "cancel-started", "cancel-invalid", "prejoin-audio-only", "prejoin-no-device", "prejoin-busy", "prejoin-insecure", "prejoin-unsupported", "prejoin-failed", "room-connecting", "room-reconnecting", "room-failed", "room-token-expired", "room-leave-confirm", "left", "reschedule-unavailable", "attendance-pending", "attendance-confirmed", "attendance-refused", "attendance-resolved", "review-refused", "reschedule-wrong-tutor", "review-delete-confirm", "review-deleted", "review-delete-failed"]);
export const S35_VIEWPORTS=Object.freeze([
  Object.freeze({id:'mobile390',preset:'m390',width:390,height:844}),
  Object.freeze({id:'desktop',preset:'d1440',width:1440,height:1024}),
]);
export const S35_PINS=Object.freeze({chromium:'149.0.7827.55',playwright:'1.61.1',platform:'linux-x64'});
// Included in the protected bundle: a new dispatch-workflow revision cannot
// silently claim this capture approval by changing an unprotected policy seal.
const S35_CALIBRATION_WORKFLOW_SHA256='bd3a267530188bcb335a09c7480b372f15efc821d502b7afed99af1a7e1b9437';
export function verifyS35ControlWorkflow(bytes){
  if(digest(bytes)!==S35_CALIBRATION_WORKFLOW_SHA256)throw Error('S35_CONTROL_WORKFLOW_MISMATCH');
  return true;
}
const hash=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
export async function loadS35Source(root){
  // Verifies ZIP, all member hashes, state inventory and embedded assets first.
  // No archive extraction and no execution of the package's helper scripts.
  const data=await loadContinuation(root);
  const html=execFileSync('unzip',['-p',resolve(root,data.archive),'NYAYONE_S01_S35_v3.2.1.08/NYAYONE_S01_S35_v3.2.1.08.html'],{maxBuffer:10*1024*1024});
  if(digest(html)!==data.htmlSha256)throw Error('S35_SOURCE_MISMATCH');
  const states=data.screens.find(s=>s.screen==='S-35').states.map(([state])=>state);
  if(canonical(states)!==canonical(S35_STATES))throw Error('S35_STATE_SOURCE_MISMATCH');
  return {data,html};
}
export function validateS35Pins(actual,fonts){
  for(const [key,value] of Object.entries(S35_PINS))if(actual[key]!==value)throw Error(`S35_CALIBRATION_PIN_MISMATCH:${key}`);
  if(!fonts||!Object.keys(fonts).length||Object.values(fonts).some(value=>!hash(value))||canonical(actual.fonts)!==canonical(fonts))throw Error('S35_FONT_PIN_MISMATCH');
  return true;
}
export function verifyS35PNG(row,bytes){
  if(!hash(row.sha256)||digest(bytes)!==row.sha256)throw Error('S35_REFERENCE_BYTES_MISMATCH');
  const image=PNG.sync.read(bytes);
  if(canonical([image.width,image.height])!==canonical(row.dimensions))throw Error('S35_REFERENCE_DIMENSION_MISMATCH');
  return true;
}
export function validateS35Manifest(manifest,data){
  if(manifest?.schema!==1||manifest.purpose!=='UNIMPORTED_REFERENCE_CALIBRATION'||manifest.screen!=='S-35'||manifest.theme!=='light'
    ||manifest.approval!==data.designApproval||manifest.sourceArchiveSha256!==data.archiveSha256||manifest.sourceSha256!==data.htmlSha256
    ||canonical(manifest.embeddedResources)!==canonical(data.inventory.embeddedResources)
    ||!['producerHead','controlHead'].every(key=>/^[a-f0-9]{40}$/.test(manifest[key]||'')))throw Error('S35_CALIBRATION_SOURCE_MISMATCH');
  validateS35Pins(manifest,manifest.fonts);
  if(canonical(manifest.deferredStates)!==canonical([])||!Array.isArray(manifest.rows)||manifest.rows.length!==112)throw Error('S35_CALIBRATION_INVENTORY');
  const seen=new Set();
  for(const row of manifest.rows){
    const vp=S35_VIEWPORTS.find(v=>v.id===row.viewport),key=`${row.view}:${row.viewport}`;
    if(!vp||!S35_STATES.some(s=>row.view===`s35-${s}`)||seen.has(key)||row.file!==`${row.view}-${row.viewport}-0.png`
      ||!hash(row.sha256)||!Array.isArray(row.sampleHashes)||row.sampleHashes.length!==3||row.sampleHashes.some(h=>h!==row.sha256)
      ||canonical(row.dimensions)!==canonical([vp.width,vp.height]))throw Error('S35_CALIBRATION_ROW_INVALID');
    const surface=row.surface;
    if(!surface||!['controls','headings','masks'].every(k=>Array.isArray(surface[k]))||typeof surface.text!=='string'
      ||surface.overflow!==0||surface.dimensions?.[0]!==vp.width||!Number.isFinite(surface.dimensions?.[1])||surface.dimensions[1]<vp.height
      ||!row.fontStack||typeof row.fontStack.viewport!=='string'||!Array.isArray(row.fontStack.faces)
      ||row.reviewerFrame?.borderRadius!=='0px'||row.reviewerFrame.x!==0||row.reviewerFrame.y!==0)throw Error('S35_CALIBRATION_SURFACE_INVALID');
    seen.add(key);
  }
  return true;
}
