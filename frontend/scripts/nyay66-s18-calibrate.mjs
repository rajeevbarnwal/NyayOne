// Owner-dispatched, pinned hosted artifact generation. Never import or approve.
import http from 'node:http';
import {readFile,readdir,writeFile,mkdir} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {chromium} from 'playwright';
import {digest} from './lib/nyay66-enforcement.mjs';
import {S18_STATES,S18_VIEWPORTS,loadS18Source,validateS18Pins,validateS18Manifest,verifyS18PNG,verifyS18ControlWorkflow} from './lib/nyay66-s18-reference.mjs';
import {captureS18Sample} from './lib/nyay66-s18-capture.mjs';
const require=createRequire(import.meta.url),controlRoot=resolve(dirname(fileURLToPath(import.meta.url)),'../..'),candidateRoot=resolve('..');
const output=resolve(process.argv[2]||'artifacts/nyay66-s18-calibration');
verifyS18ControlWorkflow(await readFile(resolve(controlRoot,'.github/workflows/nyay66-calibration.yml')));
const {data,html}=await loadS18Source(candidateRoot);
const policy=JSON.parse(await readFile(resolve(controlRoot,'frontend/scripts/nyay66-policy.json')));
const controlBytes=await readFile(resolve(controlRoot,'frontend/test-baselines/nyay66',policy.cache,'manifest.json'));
if(digest(controlBytes)!==policy.manifestSha256)throw Error('S18_CONTROL_MANIFEST_MISMATCH');
const control=JSON.parse(controlBytes),fonts={};
for(const name of (await readdir(resolve(candidateRoot,'frontend/public/fonts'))).filter(n=>n.endsWith('.woff2')).sort())fonts[name]=digest(await readFile(resolve(candidateRoot,'frontend/public/fonts',name)));
const commit=root=>execFileSync('git',['-C',root,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
const manifest={schema:1,purpose:'UNIMPORTED_REFERENCE_CALIBRATION',screen:'S-18',theme:'light',approval:data.designApproval,
  sourceArchiveSha256:data.archiveSha256,sourceSha256:data.htmlSha256,embeddedResources:data.inventory.embeddedResources,
  producerHead:commit(candidateRoot),controlHead:commit(controlRoot),generatedUTC:new Date().toISOString(),
  platform:`${process.platform}-${process.arch}`,playwright:require('playwright/package.json').version,fonts,
  deferredStates:['option-manual'],rows:[]};
let browser,server;
try{
  browser=await chromium.launch();manifest.chromium=browser.version();
  validateS18Pins(manifest,control.fonts);
  for(const key of ['platform','playwright','chromium'])if(manifest[key]!==control[key])throw Error(`S18_CONTROL_PIN_MISMATCH:${key}`);
  await mkdir(output,{recursive:false});
  server=http.createServer((req,res)=>{if(req.url!=='/'){res.writeHead(404).end();return;}res.setHeader('Content-Type','text/html');res.end(html);});
  await new Promise(done=>server.listen(0,'127.0.0.1',done));
  const origin=`http://127.0.0.1:${server.address().port}`;
  for(const state of S18_STATES)for(const vp of S18_VIEWPORTS){
    const sampleHashes=[];let first;
    for(let i=0;i<3;i++){
      const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},deviceScaleFactor:1,locale:'en-IN',timezoneId:'Asia/Kolkata',colorScheme:'light',reducedMotion:'reduce',serviceWorkers:'block'});
      try{
        const page=await context.newPage(),errors=[];page.setDefaultTimeout(20000);
        page.on('pageerror',()=>errors.push('PAGE_ERROR'));
        page.on('console',m=>{if(m.type()==='error')errors.push('CONSOLE_ERROR');});
        page.on('requestfailed',()=>errors.push('REQUEST_FAILED'));
        await context.route('**/*',route=>{const url=route.request().url();if(url===origin+'/'||url.startsWith('data:')||url.startsWith('blob:'))return route.continue();errors.push('OUTBOUND_REQUEST');return route.abort();});
        const sample=await captureS18Sample(page,origin,state,vp);
        if(errors.length)throw Error(`S18_CAPTURE_ERRORS:${errors.join(',')}`);
        sampleHashes.push(digest(sample.bytes));if(i===0)first=sample;
      }finally{await context.close();}
    }
    if(new Set(sampleHashes).size!==1)throw Error(`S18_REFERENCE_VARIANCE:${state}:${vp.id}`);
    const row={view:`s18-${state}`,viewport:vp.id,file:`s18-${state}-${vp.id}-0.png`,sha256:sampleHashes[0],sampleHashes,
      dimensions:[vp.width,vp.height],surface:first.surface,fontStack:first.fontStack,reviewerFrame:first.reviewerFrame};
    verifyS18PNG(row,first.bytes);manifest.rows.push(row);await writeFile(resolve(output,row.file),first.bytes,{flag:'wx'});
    console.log(`${row.view} ${vp.id}: 3/3 byte-identical`);
  }
  validateS18Manifest(manifest,data);
  await writeFile(resolve(output,'manifest.json'),JSON.stringify(manifest,null,2)+'\n',{flag:'wx'});
  const files=(await readdir(output)).sort();
  await writeFile(resolve(output,'SHA256SUMS'),(await Promise.all(files.map(async file=>`${digest(await readFile(resolve(output,file)))}  ${file}`))).join('\n')+'\n',{flag:'wx'});
  console.log('S18_CALIBRATION_OK 18 unimported references; two manual-mode rows remain DESIGN-GAP.');
}finally{if(browser)await browser.close();if(server)await new Promise(done=>server.close(done));}
