import {createHash} from 'node:crypto';
const digest=bytes=>createHash('sha256').update(bytes).digest('hex');
// Validate every listed artifact AND bind each selected sample to those bytes,
// before any output directory or manifest is created.
export async function validateReferenceFiles(report,sums,read){
  const files=new Map();
  for(const line of sums.trim().split('\n')){
    const match=/^([a-f0-9]{64}) {2}([a-z0-9.-]+)$/.exec(line);
    if(!match||files.has(match[2]))throw Error('ARTIFACT_HASH_MISMATCH');
    const [,hash,name]=match;
    const bytes=await read(name);
    if(digest(bytes)!==hash)throw Error('ARTIFACT_HASH_MISMATCH');
    files.set(name,{hash,bytes});
  }
  for(const row of report.rows){
    const sample=files.get(`${row.view}-${row.viewport}-0.png`);
    if(!sample||sample.hash!==row.sampleHashes[0])throw Error('REFERENCE_SAMPLE_HASH_MISMATCH');
  }
  return files;
}
