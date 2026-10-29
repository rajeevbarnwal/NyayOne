// Hash-bound candidate import only; no product capture or enforcement promotion.
import {readFile,lstat} from 'node:fs/promises';
import {resolve} from 'node:path';
import {execFileSync} from 'node:child_process';
import {canonical,digest} from './nyay66-enforcement.mjs';
import {S25_STATES,S25_VIEWPORTS,validateS25Manifest,validateS25Pins,verifyS25PNG} from './nyay66-s25-reference.mjs';
const hash=x=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
const commit=x=>typeof x==='string'&&/^[a-f0-9]{40}$/.test(x);
const names=()=>['SHA256SUMS','manifest.json','runtime-pins.json',...S25_STATES.flatMap(s=>S25_VIEWPORTS.map(v=>`s25-${s}-${v.id}-0.png`))];
async function regular(path){if(!(await lstat(path)).isFile())throw Error('S25_NONREGULAR_INPUT');return readFile(path);}
function verifyFiles(files,expected,data,fonts){
  const remaining=new Set(names().filter(n=>n!=='SHA256SUMS'));
  for(const line of files.get('SHA256SUMS').toString().trim().split('\n')){
    const m=/^([a-f0-9]{64}) {2}([a-z0-9.-]+)$/.exec(line);
    if(!m||!remaining.delete(m[2])||digest(files.get(m[2]))!==m[1])throw Error('S25_ARTIFACT_CHECKSUM_MISMATCH');
  }
  if(remaining.size)throw Error('S25_ARTIFACT_CHECKSUM_MISMATCH');
  const manifest=JSON.parse(files.get('manifest.json')),pins=JSON.parse(files.get('runtime-pins.json'));
  validateS25Manifest(manifest,data);validateS25Pins(manifest,fonts);validateS25Pins(pins,fonts);
  if(!commit(expected.sourceHead)||!commit(expected.controlHead)||manifest.producerHead!==expected.sourceHead||manifest.controlHead!==expected.controlHead||pins.sourceHead!==expected.sourceHead)throw Error('S25_PRODUCER_HEAD_MISMATCH');
  if(pins.purpose!=='REFERENCE_GENERATION_ONLY_NOT_IMPORT_APPROVAL'||pins.reference!=='s25-v32108'||pins.node!=='v22.21.1')throw Error('S25_RUNTIME_PIN_MISMATCH');
  for(const row of manifest.rows)verifyS25PNG(row,files.get(row.file));
  return {files,manifest,manifestSha256:digest(files.get('manifest.json'))};
}
export async function verifyS25Archive(path,expected,data,fonts){
  const bytes=await regular(path),archiveSha256=digest(bytes);
  if(!hash(expected.archiveSha256)||archiveSha256!==expected.archiveSha256)throw Error('S25_ARCHIVE_DIGEST_MISMATCH');
  // Inspect exact members without extracting paths or executing package helpers.
  const listing=execFileSync('unzip',['-Z1',path],{encoding:'utf8',maxBuffer:100_000}).trim().split('\n');
  if(canonical([...listing].sort())!==canonical(names().sort()))throw Error('S25_ARCHIVE_MEMBER_INVENTORY');
  const files=new Map(listing.map(name=>[name,execFileSync('unzip',['-p',path,name],{maxBuffer:2*1024*1024})]));
  return {...verifyFiles(files,expected,data,fonts),archiveSha256};
}
export async function loadS25Cache(root,config,data,fonts){
  if(!config)return null;
  if(!/^[a-z0-9][a-z0-9.-]*$/.test(config.cache)||!hash(config.manifestSha256)||!hash(config.provenanceSha256))throw Error('S25_INVALID_CACHE_BINDING');
  const cache=resolve(root,'frontend/test-baselines/nyay66',config.cache);
  const provenanceBytes=await regular(resolve(cache,'provenance.json'));
  if(digest(provenanceBytes)!==config.provenanceSha256)throw Error('S25_PROVENANCE_MISMATCH');
  const provenance=JSON.parse(provenanceBytes);
  if(!hash(provenance.archiveSha256)||!/^\d+$/.test(provenance.runId)||!/^\d+$/.test(provenance.artifactId)||provenance.referenceRows!==12||provenance.manualRows!==0)throw Error('S25_PROVENANCE_INVALID');
  const files=new Map(await Promise.all(names().map(async name=>[name,await regular(resolve(cache,name))])));
  if(digest(files.get('manifest.json'))!==config.manifestSha256)throw Error('S25_MANIFEST_BYTES_MISMATCH');
  return {cache,provenance,...verifyFiles(files,provenance,data,fonts)};
}
