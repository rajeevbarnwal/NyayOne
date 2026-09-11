// Explicit owner-approved re-baseline tool. Never invoked by a PR verification job.
import {readFile,mkdir,copyFile,writeFile,readdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {digest} from './lib/nyay66-enforcement.mjs';
import {validateCalibration} from './lib/nyay66-conformance.mjs';
const [input,output,approval]=process.argv.slice(2);
if(!input||!output||!approval)throw Error('USAGE: input-directory new-output-directory owner-approval-reference');
const report=JSON.parse(await readFile(resolve(input,'calibration.json')));
if(validateCalibration(report).length||report.platform!=='linux-x64'||report.rows.some(row=>!row.surface))throw Error('INVALID_REFERENCE_CAPTURE');
for(const line of (await readFile(resolve(input,'SHA256SUMS'),'utf8')).trim().split('\n')){
  const [hash,name]=line.split('  ');
  if(!/^[a-z0-9.-]+$/.test(name)||digest(await readFile(resolve(input,name)))!==hash)throw Error('ARTIFACT_HASH_MISMATCH');
}
await mkdir(output,{recursive:false});
const fonts={};
for(const name of (await readdir('public/fonts')).filter(x=>x.endsWith('.woff2')).sort())fonts[name]=digest(await readFile(resolve('public/fonts',name)));
const cache={schema:1,approval,producerHead:report.head,sourceSha256:report.sourceSha256,chromium:report.chromium,playwright:report.playwright,platform:report.platform,fonts,rows:[]};
for(const row of report.rows){
  const file=`${row.view}-${row.viewport}-0.png`;
  await copyFile(resolve(input,file),resolve(output,file));
  cache.rows.push({view:row.view,viewport:row.viewport,file,sha256:row.sampleHashes[0],surface:row.surface});
}
await writeFile(resolve(output,'manifest.json'),JSON.stringify(cache,null,2)+'\n');
console.log(JSON.stringify({rows:cache.rows.length,manifestSha256:digest(await readFile(resolve(output,'manifest.json')))}));
