// Developer producer tests only: synthetic APIs and local Chromium, not hosted parity or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,mkdir,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS31Application,classifyS31Errors,verifyS31Requests,S31_PATHS,frameS31Page2Viewport} from './nyay66-s31-fixtures.mjs';
import {S31_STATES,S31_VIEWPORTS} from './nyay66-s31-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS31Cache} from './nyay66-s31-import.mjs';
import {captureS31Rows} from './nyay66-s31-live.mjs';
import {finalizeEnforcement,digest} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
for(const state of S31_STATES)for(const vp of S31_VIEWPORTS)it(`${state} ${vp.id}: actual private route, server query/page and truthful claims`,{timeout:30_000},async()=>{
  const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(7000);
  const errors=[],messages=[],responses=[],failed=[];
  const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
  page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});
  page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
  try{
    const proof=await mockS31Application(page,state,origin,errors);
    assert.deepEqual(errors,[]);assert.deepEqual(classifyS31Errors(state,origin,messages,responses,failed,proof.expectedHttpErrors).errors,[]);
    assert.equal(verifyS31Requests(state,proof.apiRequests),true);assert.equal(proof.evidenceKind,'live-route');
    assert.equal(proof.syntheticServer,true);assert.equal(proof.navigationFrozen,false);assert.equal(proof.artificialDelay,false);
    assert.equal(new URL(page.url()).pathname,'/s-31');assert.equal(proof.routeProof.requestSequenceVerified,true);
    assert.equal(proof.routeProof.serverConfirmationVerified,true);assert.equal(proof.routeProof.searchPaginationVerified,true);
    const snapshot=proof.discoveryProof;
    if(state!=='page-2')assert.equal(proof.viewportFraming,undefined,'other states must keep their original capture path');
    if(state==='loading'){assert.equal(proof.pendingResponses.length,1);assert.equal(snapshot.cards.length,0);assert.equal(snapshot.summary,'');}
    if(state==='offline'){
      assert.equal(await page.evaluate(()=>navigator.onLine),false);assert.equal(proof.apiRequests.length,1);
      assert.equal(await page.locator('.s20-mark').evaluate(i=>i.complete&&i.naturalWidth>0),true,'the real logo must finish loading before disconnection');
      assert.equal(proof.staticAssetCache.testOnly,true);
      assert.equal(proof.staticAssetCache.sha256,digest(await readFile('dist/brand/nyayone-mark.svg')),'offline static cache must replay the actual unchanged build asset');
      await page.getByRole('button',{name:'Retry',exact:true}).press('Enter');assert.equal(proof.apiRequests.length,1,'offline Retry cannot fabricate a request');
      assert.match(await page.getByRole('alert').innerText(),/No request was sent/);
    }
    if(state==='page-2'){
      assert.equal(proof.apiRequests.filter(r=>r.path===S31_PATHS.tutors).length,2);
      assert.equal(new URL(page.url()).searchParams.get('offset'),'3');assert.equal(snapshot.focusId,'s31-results-summary');
      assert.deepEqual(snapshot.scroll,[0,0]);assert.deepEqual(proof.viewportFraming.after,[0,0]);
      assert.equal(proof.viewportFraming.focusPreserved,true);assert.equal(proof.viewportFraming.domModified,false);
      await page.getByRole('button',{name:'Next page',exact:true}).press('Enter');assert.equal(proof.apiRequests.length,3,'last page cannot request an invented page');
    }
    if(state==='filters-open'){assert.equal(snapshot.filtersOpen,true);assert.equal(snapshot.subject,'Arbitration');assert.equal(snapshot.cards.length,2);}
    if(['rate-limited','error'].includes(state)){assert.equal(snapshot.focusRole,'alert');assert.equal(responses[0].status,state==='error'?500:429);}
    if(state==='rate-limited'){assert.equal(snapshot.retryDisabled,'false');assert.equal(proof.apiRequests.length,2,'cooldown expiration must not trigger an automatic search');}
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  }finally{page.off('requestfailed',onFailed);await context.close();}
});
for(const vp of S31_VIEWPORTS)it(`page-2 viewport framing ${vp.id}: identical pixels from top/end scroll history without focus, DOM or request changes`,{timeout:30_000},async()=>{
  const context=await browser.newContext({viewport:{width:vp.width,height:vp.height},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'});
  const page=await context.newPage();page.setDefaultTimeout(7000);
  try{
    const errors=[],proof=await mockS31Application(page,'page-2',origin,errors),requests=JSON.stringify(proof.apiRequests),url=page.url();
    assert.deepEqual(errors,[]);
    let first;
    for(const end of [false,true,false,true]){
      await page.evaluate(async end=>{window.scrollTo({left:0,top:end?document.documentElement.scrollHeight:0,behavior:'instant'});await new Promise(done=>requestAnimationFrame(()=>requestAnimationFrame(done)));},end);
      const starting=await page.evaluate(()=>[scrollX,scrollY]);
      if(end&&vp.id==='mobile390')assert(starting[1]>0,'negative control must actually have a nonzero scroll history');
      const dom=await page.locator('.s31-discovery').evaluate(el=>el.outerHTML),framing=await frameS31Page2Viewport(page);
      assert.deepEqual(framing.before,starting);assert.deepEqual(framing.after,[0,0],'capture origin must not depend on prior scrolling');
      assert.equal(framing.focusId,'s31-results-summary');assert.equal(framing.focusPreserved,true);assert.equal(framing.domModified,false);assert.equal(framing.pixelPostprocessing,false);
      assert.equal(await page.locator('.s31-discovery').evaluate(el=>el.outerHTML),dom);assert.equal(page.url(),url);assert.equal(JSON.stringify(proof.apiRequests),requests);
      assert.equal(await page.evaluate(()=>document.activeElement?.id),'s31-results-summary');
      const bytes=await page.screenshot({animations:'disabled',fullPage:false});
      if(first)assert.equal(digest(bytes),first,'compare raw captures with each other, never with an approval hash');else first=digest(bytes);
    }
    await page.getByRole('searchbox',{name:'Search mentors',exact:true}).focus();
    await assert.rejects(frameS31Page2Viewport(page),/S31_PAGE2_FRAME_FOCUS/);
    assert.equal(await page.evaluate(()=>document.activeElement?.id),'s31-q','framing must never repair or steal product focus');
  }finally{await context.close();}
});
it('page-2 viewport framing rejects an unrelated document without altering it',async()=>{
  const context=await browser.newContext(),page=await context.newPage();
  try{await page.setContent('<main>Unrelated surface</main>');const before=await page.content();await assert.rejects(frameS31Page2Viewport(page),/S31_PAGE2_FRAME_SCOPE/);assert.equal(await page.content(),before);}finally{await context.close();}
});
it('16 measured rows, two cold captures, exact reproducibility and missing/tampered reference rejection',{timeout:600_000},async()=>{
  const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json'));
  const control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json')));
  const reference=await loadS31Cache(root,policy.s31,await loadContinuation(root),control.fonts);
  const out=await mkdtemp(resolve(tmpdir(),'nyay100-s31-product-capture-test-'));
  console.log(`S-31 local diagnostic captures (not hosted parity): ${out}`);
  const dirs=['first','second','tampered','missing'].map(n=>resolve(out,n));await Promise.all(dirs.map(d=>mkdir(d)));
  const failures=rs=>rs.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,viewport:r.viewport,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics}));
  const first=await captureS31Rows({browser,origin,out:dirs[0],reference});await writeFile(resolve(out,'first-results.json'),JSON.stringify(first,null,2));assert.equal(first.length,16);assert.deepEqual(failures(first),[]);
  assert(first.every(r=>r.evidenceKind==='live-route'&&r.syntheticServer));
  const result=finalizeEnforcement(first,{enforced:[],exceptions:[]},[],{r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true,s27:true,s28:true,s29:true,s30:true,s31:true});
  assert.deepEqual(result.failures,[]);assert(result.rows.every(r=>r.verdict!=='CAPTURE-FAILED'&&r.exceptionsApplied.length===0));
  for(const r of result.rows)if(r.accessibility.some(v=>['serious','critical'].includes(v.impact)))assert.equal(r.verdict,'NONCONFORMANT');
  const second=await captureS31Rows({browser,origin,out:dirs[1],reference});await writeFile(resolve(out,'second-results.json'),JSON.stringify(second,null,2));assert.deepEqual(failures(second),[]);
  const identities=rs=>rs.map(r=>({state:r.state,viewport:r.viewport,liveSha256:r.liveSha256,surface:r.liveSurface}));
  assert.deepEqual(identities(first),identities(second),'Compare cold captures; never select by an approval hash');
  const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}};
  const rejected=await captureS31Rows({browser,origin,out:dirs[2],reference:tampered});
  assert(rejected.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S31_REFERENCE_BYTES_MISMATCH'));
  const missing=await captureS31Rows({browser,origin,out:dirs[3],reference:{...reference,manifest:{...reference.manifest,rows:[]}}});
  assert(missing.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S31_REFERENCE_MISSING'));
});
