// Local synthetic producer regressions, not hosted conformance or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS32Application,classifyS32Errors,verifyS32Requests,S32_PATHS,frameS32Viewport} from './nyay66-s32-fixtures.mjs';
import {S32_STATES,S32_VIEWPORTS} from './nyay66-s32-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS32Cache} from './nyay66-s32-import.mjs';
import {captureS32Rows} from './nyay66-s32-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S32_STATES)for(const vp of S32_VIEWPORTS)it(`${state} ${vp.id}: genuine route, requests, slot selection and zone/window semantics`,{timeout:30_000},async()=>{
 const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'}),page=await context.newPage();page.setDefaultTimeout(7000);
 const errors=[],messages=[],responses=[],failed=[];
 const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
 page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
 try{
  const proof=await mockS32Application(page,state,origin,errors);assert.deepEqual(errors,[]);
  assert.deepEqual(classifyS32Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
  assert(verifyS32Requests(state,proof.apiRequests));assert.equal(proof.evidenceKind,'live-route');assert(proof.syntheticServer);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
  for(const flag of ['requestSequenceVerified','serverConfirmationVerified','selectionBeforeBookingVerified','timezoneResolutionVerified'])assert.equal(proof.routeProof[flag],true);
  assert.equal(new URL(page.url()).pathname,'/s-32');assert(proof.apiRequests.every(r=>r.method==='GET'));
  const s=proof.detailProof;assert.deepEqual(s.scroll,[0,0]);assert(proof.viewportFraming.focusPreserved);assert.equal(proof.viewportFraming.domModified,false);assert.equal(proof.viewportFraming.pixelPostprocessing,false);
  if(state==='loading'){assert.equal(proof.pendingResponses.length,1);assert.equal(s.loading,true);assert.equal(s.radios.length,0);assert.equal(proof.apiRequests.length,2);}
  if(['missing','profile-error','availability-error'].includes(state)){assert.equal(s.focusRole,'alert');assert.equal(responses[0].status,state==='missing'?404:500);assert.equal(s.radios.length,0);}
  if(state==='selected'){assert.equal(s.radios.filter(r=>r.checked).length,1);assert.equal(s.continueDisabled,false);assert.equal(s.focusSlot,s.radios[0].id);}
  if(['zone-changed','day-empty'].includes(state)){assert(proof.selectionReset.noSelectionWhilePending);assert(proof.selectionReset.continueDisabledWhilePending);assert.equal(s.radios.filter(r=>r.checked).length,0);assert.equal(s.continueDisabled,true);assert.equal(proof.apiRequests.length,4);}
  if(state==='zone-changed'){assert.equal(s.zone,'Europe/London');assert.equal(s.focusId,'s32-zone');assert.match(s.timesHeading,/Europe\/London/);}
  if(state==='day-empty'){assert.equal(s.day,'2027-08-18');assert.equal(s.focusId,'s32-day');assert.match(s.empty,/No open times in this window/);}
  if(state.startsWith('dst-')){assert.equal(s.resolutionNotices.length,1);assert.match(s.resolutionNotices[0],state==='dst-gap'?/does not exist/:/happens twice/);}
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 }finally{page.off('requestfailed',onFailed);await context.close();}
});
it('loads the shipped control font before the profile can mount native select controls',async()=>{
 const context=await browser.newContext({viewport:{width:390,height:844},timezoneId:'Asia/Kolkata'}),page=await context.newPage();
 try{const proof=await mockS32Application(page,'complete',origin,[]);assert.deepEqual(proof.controlFontReadiness,{family:'Public Sans',weight:'400',loadedBeforeProfile:true,loadedFaces:1});}
 finally{await context.close();}
});
it('camera framing preserves real active control, route, DOM and API history and rejects unrelated documents',async()=>{
 const context=await browser.newContext({viewport:{width:390,height:844},timezoneId:'Asia/Kolkata'}),page=await context.newPage();
 try{
  const proof=await mockS32Application(page,'selected',origin,[]),html=await page.locator('.s32-detail').evaluate(e=>e.outerHTML),url=page.url(),requests=JSON.stringify(proof.apiRequests);
  await page.evaluate(()=>window.scrollTo(0,document.documentElement.scrollHeight));assert((await page.evaluate(()=>scrollY))>0);
  const framed=await frameS32Viewport(page);assert.deepEqual(framed.after,[0,0]);assert(framed.focusPreserved);assert.equal(framed.focusSlot,proof.detailProof.focusSlot);
  assert.equal(await page.locator('.s32-detail').evaluate(e=>e.outerHTML),html);assert.equal(page.url(),url);assert.equal(JSON.stringify(proof.apiRequests),requests);
  await page.setContent('<main>Unrelated content</main>');const before=await page.content();await assert.rejects(frameS32Viewport(page),/S32_FRAME_SCOPE/);assert.equal(await page.content(),before);
 }finally{await context.close();}
});
it('22 measured rows, two cold captures, no approved-hash selection, and missing/tampered references fail closed',{timeout:600_000},async()=>{
 const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json')),control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json')));
 const reference=await loadS32Cache(root,policy.s32,await loadContinuation(root),control.fonts);
 const out=await mkdtemp(resolve(tmpdir(),'nyay101-s32-product-capture-test-'));console.log(`S-32 local diagnostic captures (not hosted parity): ${out}`);
 const dirs=['first','second','tampered','missing'].map(n=>resolve(out,n));await Promise.all(dirs.map(d=>mkdir(d)));
 const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
 const first=await captureS32Rows({browser,origin,out:dirs[0],reference});await writeFile(resolve(out,'first-results.json'),JSON.stringify(first,null,2));assert.equal(first.length,22);assert.deepEqual(failures(first),[]);
 assert(first.every(r=>r.evidenceKind==='live-route'&&r.syntheticServer));
 const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true,s27:true,s28:true,s29:true,s30:true,s31:true,s32:true});
 assert.deepEqual(result.failures,[]);assert(result.rows.every(r=>r.verdict!=='CAPTURE-FAILED'&&r.exceptionsApplied.length===0));
 for(const r of result.rows)if(r.accessibility.some(v=>['serious','critical'].includes(v.impact)))assert.equal(r.verdict,'NONCONFORMANT');
 const second=await captureS32Rows({browser,origin,out:dirs[1],reference});await writeFile(resolve(out,'second-results.json'),JSON.stringify(second,null,2));assert.deepEqual(failures(second),[]);
 const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));assert.deepEqual(identities(first),identities(second),'Compare independent cold captures, never choose by an approval hash');
 const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}};
 const rejected=await captureS32Rows({browser,origin,out:dirs[2],reference:tampered});assert(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S32_REFERENCE_BYTES_MISMATCH'));
 const missing=await captureS32Rows({browser,origin,out:dirs[3],reference:{...reference,manifest:{...reference.manifest,rows:[]}}});assert(missing.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S32_REFERENCE_MISSING'));
 assert.equal(first.some(r=>r.apiRequests.some(q=>q.path===S32_PATHS.hold)),false);
});
