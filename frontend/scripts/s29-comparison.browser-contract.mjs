// Developer Chromium probes with synthetic API responses; not conformance or independent QA.
import { before, after, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdir } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import { preview } from 'vite';
import { chromium } from 'playwright';
import { actor } from './lib/nyay66-fixtures.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
const school=id=>({id,name:`Synthetic Law School ${id}`,slug:id,state:id==='a'?'Delhi':'Kerala',institution_type:'government',accreditation:null,entrance_exam:'CLAT',fees_min:null,fees_max:null,nirf_rank:null,programmes:[{degree:'LLB',duration_years:3}],facts:[{key:'hostel',value:'Available',source_name:'Institution publication',source_url:'https://example.test/facts',retrieved_at:'2026-07-01T00:00:00Z'}],saved:false,followed:false});
async function using(run,options={}){
 const context=await browser.newContext({viewport:{width:options.width??390,height:844},reducedMotion:'reduce'}),page=await context.newPage();page.setDefaultTimeout(5000);
 const s={requests:[],status:200,code:'unavailable',extra:{},hold:false,held:[],unexpected:[],...options};
 await page.route('**/*',async route=>{const req=route.request(),url=new URL(req.url());const reply=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)}).catch(()=>{});
  if(url.origin!==origin&&!(url.origin==='http://localhost:1131'&&url.pathname.startsWith('/api/v1/'))){s.unexpected.push(url.origin);return route.abort();}
  if(!url.pathname.startsWith('/api/v1/'))return route.continue();
  if(url.pathname==='/api/v1/auth/student/session')return reply(s.sessionUnavailable?{detail:{code:'unavailable'}}:s.signedOut?{authenticated:false}:{authenticated:true,actor},s.sessionUnavailable?503:200);
  if(url.pathname==='/api/v1/law-schools/compare'){
   assert.equal(req.method(),'POST');const ids=req.postDataJSON().school_ids;s.requests.push(ids);
   const status=s.status,body=status===200?{comparison_id:`cmp-${s.requests.length}`,compare_max:4,items:ids.map(school)}:{detail:{code:s.code,...s.extra}};
   const done=()=>{if(status===401)s.signedOut=true;return reply(s.malformed?{}:body,status);};if(s.hold){s.hold=false;s.held.push(done);return;}return done();
  }
  if(url.pathname.startsWith('/api/v1/law-schools/'))return reply(school(decodeURIComponent(url.pathname.split('/').pop())));
  s.unexpected.push(req.method()+' '+url.pathname);return route.abort();
 });
 try{await run(page,s);assert.deepEqual(s.unexpected,[]);}finally{await context.close();}
}
const url=(ids='a,b')=>`${origin}/s-29?${new URLSearchParams({ids})}`;
const ready=page=>page.getByRole('table').first().waitFor();
async function held(s){const end=Date.now()+5000;while(!s.held.length&&Date.now()<end)await delay(10);assert.ok(s.held.length);}
it('Revision L comparison renders one main, ordered server figures and truthful provenance',()=>using(async(page,s)=>{
 await page.goto(url());await ready(page);assert.equal(await page.locator('main').count(),1);assert.equal(await page.locator('.ls-shell').count(),0);
 await page.getByRole('heading',{name:'Compare schools.',exact:true}).waitFor();
 await page.locator('summary').filter({hasText:'Published facts'}).click();
 assert.deepEqual(await page.locator('tbody th').allTextContents(),['State','Institution type','Accreditation','Entrance exam','Fees','NIRF rank','Programmes','Established','Location','Intake','Hostel','Legal aid clinics','Moot teams']);
 assert.equal(s.requests.length,1);assert.match(await page.locator('main').innerText(),/Not provided/);assert.doesNotMatch(await page.locator('main').innerText(),/verified|prototype|sample data/i);
 await page.getByText('Where these figures come from',{exact:true}).click();assert.equal(await page.getByRole('link',{name:/Institution publication/}).first().getAttribute('href'),'https://example.test/facts');
}));
it('Differences only is local, off by default, retains selection and does not POST',()=>using(async(page,s)=>{
 await page.goto(url());await ready(page);const toggle=page.getByRole('switch',{name:'Differences only',exact:true});assert.equal(await toggle.getAttribute('aria-checked'),'false');
 await toggle.press('Space');assert.equal(await toggle.getAttribute('aria-checked'),'true');assert.equal(await page.locator('tbody tr:visible').count(),1);assert.equal(s.requests.length,1);assert.equal(new URL(page.url()).searchParams.get('ids'),'a,b');
}));
it('removal sends fewer IDs once, keeps focus while pending, and shows no stale comparison',()=>using(async(page,s)=>{
 await page.goto(url('a,b,c'));await ready(page);s.hold=true;
 const remove=page.getByRole('button',{name:'Remove Synthetic Law School c from comparison',exact:true});await remove.focus();await remove.evaluate(el=>{el.click();el.click();});await held(s);
 assert.deepEqual(s.requests,[['a','b','c'],['a','b']]);assert.notEqual(await page.evaluate(()=>document.activeElement?.tagName),'BODY');await s.held.shift()();await ready(page);
 assert.notEqual(await page.evaluate(()=>document.activeElement?.tagName),'BODY');assert.equal(await page.getByRole('link',{name:'Synthetic Law School c',exact:true}).count(),0);
 await page.getByRole('button',{name:'Remove Synthetic Law School b from comparison',exact:true}).press('Enter');await page.getByRole('alert').waitFor();assert.equal(s.requests.length,2);assert.equal(await page.locator('table').count(),0);
}));
it('detail link preserves comparison IDs for the S-28 return route',()=>using(async page=>{
 await page.goto(url());await ready(page);await page.getByRole('link',{name:'Synthetic Law School a',exact:true}).first().click();
 await page.getByRole('link',{name:'Comparison',exact:true}).waitFor();const back=await page.getByRole('link',{name:'Comparison',exact:true}).getAttribute('href');assert.equal(new URL(back,origin).searchParams.get('ids'),'a,b');
}));
for(const status of [404,422,429,503])it(`HTTP ${status} is truthful; Retry does not lose focus or duplicate POSTs`,()=>using(async(page,s)=>{
 await page.goto(url());await page.getByRole('alert').waitFor();assert.match(await page.locator('main').innerText(),new RegExp(`HTTP ${status}`));assert.match(await page.locator('main').innerText(),/server_code/);
 const retry=page.getByRole('button',{name:'Retry',exact:true});s.hold=true;await retry.focus();await retry.evaluate(el=>{el.click();el.click();});await held(s);assert.equal(s.requests.length,2);assert.notEqual(await page.evaluate(()=>document.activeElement?.tagName),'BODY');
 await s.held.shift()();await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
},{status,code:'server_code'}));
it('late retry failure does not steal focus after the user moves away',()=>using(async(page,s)=>{
 await page.goto(url());await page.getByRole('alert').waitFor();s.hold=true;await page.getByRole('button',{name:'Retry',exact:true}).press('Enter');await held(s);
 const back=page.getByRole('link',{name:'Find a law school',exact:true});await back.focus();await s.held.shift()();await page.waitForFunction(()=>!document.querySelector('[aria-busy=true]'));
 assert.equal(await back.evaluate(el=>el===document.activeElement),true);
},{status:503}));
it('explicit empty/duplicate URL selections stay below minimum with no fabricated server error or POST',()=>using(async(page,s)=>{
 for(const ids of ['', 'a,a']){await page.goto(url(ids));await page.getByRole('alert').waitFor();assert.match(await page.locator('main').innerText(),/at least 2 schools/);assert.doesNotMatch(await page.locator('main').innerText(),/HTTP|COMPARE_MIN_NOT_MET/);}
 assert.equal(s.requests.length,0);
}));
it('server limit/error extras remain authoritative and no contradictory successful table renders',()=>using(async page=>{
 await page.goto(url('a,b,c,d,e'));await page.getByRole('alert').waitFor();const text=await page.locator('main').innerText();assert.match(text,/COMPARE_LIMIT_EXCEEDED/);assert.match(text,/max_allowed/);assert.match(text,/3/);assert.equal(await page.locator('table').count(),0);
},{status:422,code:'COMPARE_LIMIT_EXCEEDED',extra:{max_allowed:3}}));
it('initial malformed success is not displayed as a comparison or a fabricated HTTP failure',()=>using(async(page,s)=>{
 await page.goto(url());await page.getByRole('alert').waitFor();assert.match(await page.locator('main').innerText(),/response could not be verified/);assert.doesNotMatch(await page.locator('main').innerText(),/HTTP 200|cmp-/);assert.equal(await page.locator('table').count(),0);assert.equal(s.requests.length,1);
},{malformed:true}));
it('expired retry survives session remount with focus on the sign-in notice and no repeated POST',()=>using(async(page,s)=>{
 await page.goto(url());await page.getByRole('alert').waitFor();s.status=401;s.code='authentication_required';
 await page.getByRole('button',{name:'Retry',exact:true}).press('Enter');await page.getByRole('link',{name:'Sign in',exact:true}).waitFor();
 await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');assert.equal(s.requests.length,2);assert.equal(await page.locator('table').count(),0);
},{status:503}));
it('session discovery failure sends no comparison POST; explicit Retry recovers safely',()=>using(async(page,s)=>{
 await page.goto(url());await page.getByRole('alert').waitFor();assert.equal(s.requests.length,0);s.sessionUnavailable=false;
 await page.getByRole('button',{name:'Retry',exact:true}).press('Enter');await ready(page);assert.notEqual(await page.evaluate(()=>document.activeElement?.tagName),'BODY');assert.equal(s.requests.length,1);
},{sessionUnavailable:true}));
it('offline Retry says no request was sent and recovers only after an explicit online Retry',()=>using(async(page,s)=>{
 await page.goto(url());await page.getByRole('alert').waitFor();await page.evaluate(()=>Object.defineProperty(navigator,'onLine',{get:()=>false,configurable:true}));
 await page.getByRole('button',{name:'Retry',exact:true}).press('Enter');await page.getByText('You are offline. No request was sent. Reconnect and retry.').waitFor();assert.equal(s.requests.length,1);
 s.status=200;await page.evaluate(()=>Object.defineProperty(navigator,'onLine',{get:()=>true,configurable:true}));await page.getByRole('button',{name:'Retry',exact:true}).press('Enter');await ready(page);assert.equal(s.requests.length,2);assert.notEqual(await page.evaluate(()=>document.activeElement?.tagName),'BODY');
},{status:503}));
it('four-school server capacity, school icons and switch geometry follow the approved primitives',()=>using(async page=>{
 await page.goto(url('a,b,c,d'));await ready(page);assert.match(await page.locator('main').innerText(),/4 of 4 schools/);assert.equal(await page.getByRole('link',{name:'Add another school',exact:true}).getAttribute('aria-disabled'),'true');
 assert.equal(await page.getByRole('button',{name:'Remove Synthetic Law School a from comparison',exact:true}).locator('path').first().getAttribute('d'),'M6 7h12l-1 13H7z');
 const track=await page.getByRole('switch',{name:'Differences only',exact:true}).locator('span').boundingBox();assert.equal(track.height,26);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
}));
for(const width of [320,390,1440])it(`${width}px reflow, label-in-name, 48px actions and axe`,()=>using(async page=>{
 await page.goto(url());await ready(page);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(width===1440){const table=await page.getByRole('table').first().boundingBox(),metric=await page.locator('thead .s29-metric').first().boundingBox();assert.ok(Math.abs(metric.width/table.width-.28)<.002,'desktop metric column keeps the frozen 28% allocation');}
 for(const action of await page.locator('.s29-comparison button:visible,.s29-comparison a:visible,.s29-comparison summary:visible').all()){const box=await action.boundingBox();assert.ok(box.height>=48,`${await action.innerText()}: ${box.height}`);}
 await page.addScriptTag({content:await readFile('node_modules/axe-core/axe.min.js','utf8')});const failures=await page.evaluate(async()=> (await window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.filter(x=>['serious','critical'].includes(x.impact)));assert.deepEqual(failures.map(x=>({id:x.id,nodes:x.nodes.map(n=>n.target)})),[]);
 if(process.env.S29_DIAGNOSTICS){await mkdir(process.env.S29_DIAGNOSTICS,{recursive:true});await page.screenshot({path:`${process.env.S29_DIAGNOSTICS}/s29-${width}.png`,fullPage:true});}
},{width}));
