// Explicit candidate staging only. No network, Git mutation or self-approval.
import {readFile,writeFile,mkdir,lstat} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {digest} from './lib/nyay66-enforcement.mjs';
import {verifyR2Calibration,R2_SOURCE_PATH,R2_SOURCE_SHA256} from './lib/nyay66-r2.mjs';
const [input,output,head,runId,artifactId,archiveSha256]=process.argv.slice(2);
if(!input||!output||!/^\d+$/.test(runId)||!/^\d+$/.test(artifactId)||!/^[a-f0-9]{64}$/.test(archiveSha256))throw Error('USAGE: input new-output source-head run-id artifact-id downloaded-archive-sha256');
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
if(digest(await readFile(resolve(root,R2_SOURCE_PATH)))!==R2_SOURCE_SHA256)throw Error('R2_SOURCE_BYTES_MISMATCH');
const policy=JSON.parse(await readFile(resolve(root,'frontend/scripts/nyay66-policy.json')));
const control=await readFile(resolve(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'));
if(digest(control)!==policy.manifestSha256)throw Error('CONTROL_MANIFEST_MISMATCH');
const read=async name=>{const path=resolve(input,name);if(!(await lstat(path)).isFile())throw Error('R2_NONREGULAR_INPUT');return readFile(path);};
const sums=await read('SHA256SUMS');
const verified=await verifyR2Calibration(sums.toString('utf8'),read,head,JSON.parse(control).fonts);
// Nothing is written until the full inventory validates. Refuse overwrite.
await mkdir(output,{recursive:false});
for(const [name,bytes] of verified.files)await writeFile(resolve(output,name),bytes,{flag:'wx'});
await writeFile(resolve(output,'SHA256SUMS'),sums,{flag:'wx'});
const provenance={status:'CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL',runId,artifactId,archiveSha256,sourceHead:head,manifestSha256:verified.manifestSha256,referencePanels:42,liveEntryStateViewports:9,unmeasuredStateViewports:33};
await writeFile(resolve(output,'provenance.json'),JSON.stringify(provenance,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify(provenance));
