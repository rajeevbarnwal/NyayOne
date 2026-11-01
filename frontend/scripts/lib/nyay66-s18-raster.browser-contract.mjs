// Real Chromium diagnostic. Never choose screenshots using an approval hash.
import {it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {captureS18Rows} from './nyay66-s18-live.mjs';
import {mockS18Application} from './nyay66-s18-fixtures.mjs';

it('S-18 invalid desktop keeps raw bytes across font-delivery timing and prior S-18 paints',{timeout:180_000},async()=>{
 const server=await preview({preview:{host:'127.0.0.1',port:0},logLevel:'error'}),origin=`http://127.0.0.1:${server.httpServer.address().port}`;
 const policy=JSON.parse(await readFile('scripts/nyay66-policy.json')),cache=resolve('test-baselines/nyay66',policy.s18.cache),manifest=JSON.parse(await readFile(resolve(cache,'manifest.json')));
 // Execute the actual producer for the affected row. Other references are
 // intentionally absent in this focused test and must still fail closed.
 const reference={cache,manifest:{...manifest,rows:manifest.rows.filter(r=>r.view==='s18-invalid'&&r.viewport==='desktop')}};
 const out=await mkdtemp(resolve(tmpdir(),'nyay97-s18-raster-proof-'));let shared;const samples=[];
 function instrument(browser,delay){return new Proxy(browser,{get(target,key){
  if(key==='newContext')return async options=>{const context=await target.newContext(options),newPage=context.newPage.bind(context);context.newPage=async()=>{const page=await newPage(),route=page.route.bind(page);page.route=(pattern,handler)=>route(pattern,async r=>{if(new URL(r.request().url()).pathname.endsWith('.woff2'))await new Promise(done=>setTimeout(done,delay));return handler(r);});return page;};return context;};
  if(key==='browserType')return()=>({name:()=> 'chromium',launch:async options=>instrument(await chromium.launch(options),delay)});
  const value=target[key];return typeof value==='function'?value.bind(target):value;
 }});}
 try{
  shared=await chromium.launch();
  for(const delay of [0,200,500])for(let repeat=0;repeat<2;repeat++){
   // Real earlier S-18 paints, with no DOM mutation, screenshot retry or repaint.
   for(const state of ['loaded','saving','saved']){
    const context=await shared.newContext({viewport:{width:1440,height:1024},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce'});
    try{const page=await context.newPage(),errors=[];await mockS18Application(page,state,origin,errors);await page.screenshot({animations:'disabled'});assert.deepEqual(errors,[]);}finally{await context.close();}
   }
   const dir=resolve(out,`${delay}-${repeat}`);await mkdir(dir);
   const rows=await captureS18Rows({browser:instrument(shared,delay),origin,out:dir,reference});
   const row=rows.find(r=>r.state==='S-18-invalid'&&r.viewport==='desktop');assert.equal(row.measured,true);assert.deepEqual(row.errors,[]);
   assert.equal(rows.filter(r=>r.verdict==='CAPTURE-FAILED'&&r.failure==='S18_REFERENCE_MISSING').length,17);
   assert.deepEqual(row.settingsRequests.map(r=>r.method),['GET','PATCH']);assert.equal(row.evidenceKind,'live-route');
   samples.push({delay,repeat,hash:row.liveSha256,surface:row.liveSurface});
  }
  await writeFile(resolve(out,'samples.json'),JSON.stringify(samples,null,2));console.log('S-18 diagnostic samples:',out);
  assert.equal(new Set(samples.map(r=>JSON.stringify(r.surface))).size,1,'Geometry/text/control proof must stay identical');
  assert.equal(new Set(samples.map(r=>r.hash)).size,1,'All six first screenshots must match, never chosen by an approved hash');
 }finally{await shared?.close();await new Promise(done=>server.httpServer.close(done));}
});
