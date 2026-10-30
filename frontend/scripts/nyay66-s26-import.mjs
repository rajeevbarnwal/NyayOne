// Explicit local candidate import. No network, Git mutation or self-approval.
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {digest} from './lib/nyay66-enforcement.mjs';
import {loadS26Source} from './lib/nyay66-s26-reference.mjs';
import {verifyS26Archive} from './lib/nyay66-s26-import.mjs';
const [archive,output,sourceHead,controlHead,runId,artifactId,archiveSha256]=process.argv.slice(2);
if(!archive||!output||!/^\d+$/.test(runId)||!/^\d+$/.test(artifactId))throw Error('USAGE: archive new-output source-head control-head run-id artifact-id github-archive-sha256');
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..'),{data}=await loadS26Source(root);
const policy=JSON.parse(await readFile(resolve(root,'frontend/scripts/nyay66-policy.json')));
const control=await readFile(resolve(root,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'));
if(digest(control)!==policy.manifestSha256)throw Error('CONTROL_MANIFEST_MISMATCH');
const result=await verifyS26Archive(resolve(archive),{sourceHead,controlHead,archiveSha256},data,JSON.parse(control).fonts);
// Full validation precedes any write; refuse to replace historical evidence.
await mkdir(output,{recursive:false});
for(const [name,bytes] of result.files)await writeFile(resolve(output,name),bytes,{flag:'wx'});
const provenance={status:'CANDIDATE_PENDING_OWNER_INTEGRITY_APPROVAL',runId,artifactId,archiveSha256:result.archiveSha256,sourceHead,controlHead,manifestSha256:result.manifestSha256,referenceRows:8,manualRows:0};
const bytes=JSON.stringify(provenance,null,2)+'\n';await writeFile(resolve(output,'provenance.json'),bytes,{flag:'wx'});
console.log(JSON.stringify({...provenance,provenanceSha256:digest(bytes)},null,2));
