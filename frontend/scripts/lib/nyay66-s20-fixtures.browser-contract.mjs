// Real Chromium + synthetic API. Local runs are diagnostics, not hosted parity.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {readFile,mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {mockS20Application,installS20Server,classifyS20Errors,S20_LISTINGS} from './nyay66-s20-fixtures.mjs';
import {S20_STATES,S20_VIEWPORTS} from './nyay66-s20-reference.mjs';
import {loadContinuation} from './nyay66-continuation.mjs';
import {loadS20Cache} from './nyay66-s20-import.mjs';
import {captureS20Rows} from './nyay66-s20-live.mjs';
import {finalizeEnforcement} from './nyay66-enforcement.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0,strictPort:false},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
async function using(test,width=390){const context=await browser.newContext({viewport:{width,height:844},locale:'en-IN',timezoneId:'Asia/Kolkata',reducedMotion:'reduce',serviceWorkers:'block'});const page=await context.newPage();page.setDefaultTimeout(7000);try{await test(page);}finally{await context.close();}}
for(const state of S20_STATES)for(const vp of S20_VIEWPORTS)it(`${state} ${vp.id}: real S-20 route, truthful request sequence and diagnostics`,{timeout:30_000},()=>using(async page=>{
  const errors=[],messages=[],responses=[],failed=[];
  const onFailed=r=>failed.push({method:r.method(),url:r.url(),errorText:r.failure()?.errorText});
  page.on('requestfailed',onFailed);page.on('pageerror',()=>errors.push('PAGE_ERROR'));
  page.on('console',m=>{if(m.type()==='error')messages.push({url:m.location().url,text:m.text()});});
  page.on('response',r=>{if(r.status()>=400)responses.push({method:r.request().method(),url:r.url(),status:r.status()});});
  const evidence=await mockS20Application(page,state,origin,errors);
  assert.deepEqual(errors,[]);assert.deepEqual(classifyS20Errors(state,origin,messages,responses,failed,evidence.expectedHttpErrors).errors,[]);
  assert.equal(new URL(page.url()).pathname,'/s-20');assert.equal(evidence.evidenceKind,'live-route');assert.equal(evidence.syntheticServer,true);
  assert.equal(evidence.navigationFrozen,false);assert.equal(evidence.artificialDelay,false);
  assert.equal(evidence.catalogueRequests.length,state==='verified-empty'?2:1);
  if(state==='verified-empty')assert.equal(evidence.catalogueRequests[1].verifiedOnly,true);
  if(state==='offline'){
    assert.equal(await page.evaluate(()=>navigator.onLine),false);
    assert.equal(evidence.fontsPrimedBeforeOffline,true);
    assert.equal(await page.evaluate(()=>[...document.fonts].every(face=>face.status==='loaded')),true);
  }
  if(state==='partial'||state==='save-failed')assert.equal(await page.locator('.s20-save[aria-pressed]').count(),0);
  if(state==='save-failed')assert.equal(evidence.apiRequests.filter(r=>r.method==='PUT').length,1);
  if(state==='local-empty')assert.equal(await page.getByLabel('Search this page').inputValue(),'No synthetic match');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  page.off('requestfailed',onFailed);
},vp.width));
it('page-local filters never invent server parameters; server pagination and verified-only reset remain real',{timeout:30_000},()=>using(async page=>{
  const errors=[],server=await installS20Server(page,'results',origin,errors,{paginated:true});
  await page.goto(origin+'/s-20');await page.getByText('Page 1 of 2',{exact:true}).waitFor();
  await page.getByLabel('Search this page').fill('Second page only');await page.getByText('No matching listings',{exact:true}).waitFor();
  assert.equal(server.catalogueRequests.length,1);
  await page.getByRole('button',{name:'Next page',exact:true}).click();await page.getByText('Second page only',{exact:true}).waitFor();
  assert.equal(server.catalogueRequests.at(-1).page,2);
  await page.getByLabel('Search this page').fill('');await page.locator('.s20-filters summary').click();
  await page.getByRole('button',{name:'Paid',exact:true}).click();assert.equal(server.catalogueRequests.length,2);
  await page.getByRole('button',{name:'Verified listings only',exact:true}).click();
  await page.getByText(S20_LISTINGS[0].role,{exact:true}).waitFor();
  assert.deepEqual(server.catalogueRequests.at(-1),{page:1,pageSize:20,verifiedOnly:true});assert.deepEqual(errors,[]);
}));
it('20-row measurement producer emits verified hashes and unwaived comparison evidence; tampered PNGs fail closed',{timeout:180_000},async()=>{
  const root=resolve('..'),policy=JSON.parse(await readFile('scripts/nyay66-policy.json'));
  const control=JSON.parse(await readFile(resolve('test-baselines/nyay66',policy.cache,'manifest.json')));
  const reference=await loadS20Cache(root,policy.s20,await loadContinuation(root),control.fonts);
  const out=await mkdtemp(resolve(tmpdir(),'nyay92-s20-capture-test-'));
  try{
    const rows=await captureS20Rows({browser,origin,out,reference});
    assert.equal(rows.length,20);
    assert.deepEqual(rows.filter(r=>!r.executed||!r.measured||r.errors.length).map(r=>({state:r.state,failure:r.failure,errors:r.errors,diagnostics:r.consoleDiagnostics})),[]);
    assert.equal(rows.every(r=>r.evidenceKind==='live-route'&&r.syntheticServer),true);
    const result=finalizeEnforcement(rows,{enforced:[],exceptions:[]},[],{r2:true,s18:true,s19:true,s20:true});
    assert.deepEqual(result.failures,[]);assert.equal(result.rows.some(r=>r.verdict==='CAPTURE-FAILED'),false);
    assert.equal(result.rows.every(r=>r.exceptionsApplied.length===0),true);
    const tampered={...reference,manifest:{...reference.manifest,rows:reference.manifest.rows.map(r=>({...r,sha256:'0'.repeat(64)}))}};
    const failures=await captureS20Rows({browser,origin,out,reference:tampered});
    assert.equal(failures.every(r=>r.verdict==='CAPTURE-FAILED'&&!r.measured&&r.failure==='S20_REFERENCE_BYTES_MISMATCH'),true);
  }finally{await rm(out,{recursive:true,force:true});}
});
