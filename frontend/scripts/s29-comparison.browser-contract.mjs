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
   const status=s.status,body=status===200?{comparison_id:`00000000-0000-4000-8000-${String(s.requests.length).padStart(12,'0')}`,compare_max:4,items:ids.map(s.project??school)}:{detail:{code:s.code,...s.extra}};
   if(status===200&&s.comparisonId)body.comparison_id=s.comparisonId;
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
it('approved mobile three-school pairs use keyboard radios, preserve server selection, and restore desktop columns',()=>using(async(page,s)=>{
 await page.goto(url('a,b,c'));await ready(page);
 const group=page.getByRole('group',{name:'Show two of the three schools',exact:true});await group.waitFor();
 const radios=group.getByRole('radio');assert.equal(await radios.count(),3);assert.equal(await radios.nth(0).isChecked(),true);
 assert.equal(await page.getByRole('table').first().locator('thead a').count(),2);
 await radios.nth(0).focus();await radios.nth(0).press('ArrowRight');assert.equal(await radios.nth(1).isChecked(),true);
 assert.deepEqual(await page.getByRole('table').first().locator('thead a').allTextContents(),['Synthetic Law School a','Synthetic Law School c']);
 await radios.nth(1).press('ArrowRight');assert.deepEqual(await page.getByRole('table').first().locator('thead a').allTextContents(),['Synthetic Law School b','Synthetic Law School c']);
 await page.getByRole('switch',{name:'Differences only',exact:true}).press('Space');assert.equal(await page.locator('tbody tr:visible').count(),0);
 assert.deepEqual(s.requests,[['a','b','c']]);assert.equal(new URL(page.url()).searchParams.get('ids'),'a,b,c');
 await page.setViewportSize({width:1440,height:1024});await page.waitForFunction(()=>document.querySelector('thead').querySelectorAll('a').length===3);
 assert.equal(await group.count(),0);assert.equal(await page.locator('tbody tr:visible').count(),1);assert.deepEqual(s.requests,[['a','b','c']]);
 await page.setViewportSize({width:320,height:844});await group.waitFor();assert.equal(await radios.nth(2).isChecked(),true);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 for(const label of await group.locator('label').all())assert.ok((await label.boundingBox()).height>=48);
 await page.addScriptTag({content:await readFile('node_modules/axe-core/axe.min.js','utf8')});const serious=await page.evaluate(async()=>(await window.axe.run()).violations.filter(x=>['serious','critical'].includes(x.impact)).map(x=>x.id));assert.deepEqual(serious,[]);
}));
it('removing the selected mobile pair member resets pair view without losing the remaining server IDs',()=>using(async(page,s)=>{
 await page.goto(url('a,b,c'));await ready(page);await page.getByRole('radio').nth(2).check();s.hold=true;
 await page.getByRole('button',{name:'Remove Synthetic Law School c from comparison',exact:true}).press('Enter');await held(s);await s.held.shift()();await ready(page);
 assert.deepEqual(s.requests,[['a','b','c'],['a','b']]);assert.equal(await page.getByRole('radio').count(),0);assert.deepEqual(await page.getByRole('table').first().locator('thead a').allTextContents(),['Synthetic Law School a','Synthetic Law School b']);
 assert.notEqual(await page.evaluate(()=>document.activeElement?.tagName),'BODY');
}));
it('removal sends fewer IDs once, keeps focus while pending, and shows no stale comparison',()=>using(async(page,s)=>{
 await page.goto(url('a,b,c'));await ready(page);await page.getByRole('radio').nth(1).check();s.hold=true;
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
 if(width===1440){const table=await page.getByRole('table').first().boundingBox(),metric=await page.locator('thead .s29-metric').first().boundingBox();assert.ok(Math.abs(metric.width-table.width/3)<1,'desktop columns keep the frozen fixed-table equal allocation');}
 for(const action of await page.locator('.s29-comparison button:visible,.s29-comparison a:visible,.s29-comparison summary:visible').all()){const box=await action.boundingBox();assert.ok(box.height>=48,`${await action.innerText()}: ${box.height}`);}
 await page.addScriptTag({content:await readFile('node_modules/axe-core/axe.min.js','utf8')});const failures=await page.evaluate(async()=> (await window.axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations.filter(x=>['serious','critical'].includes(x.impact)));assert.deepEqual(failures.map(x=>({id:x.id,nodes:x.nodes.map(n=>n.target)})),[]);
 if(process.env.S29_DIAGNOSTICS){await mkdir(process.env.S29_DIAGNOSTICS,{recursive:true});await page.screenshot({path:`${process.env.S29_DIAGNOSTICS}/s29-${width}.png`,fullPage:true});}
},{width}));

// Corrective geometry measured from the frozen v3.2.1.08 DOM. These checks
// exercise rendered layout and keyboard controls; they do not change a gate.
for(const count of [2,3,4])it(`presentation: ${count}-school desktop columns stay equal`,()=>using(async page=>{
 await page.goto(url(['a','b','c','d'].slice(0,count).join(',')));await ready(page);
 for(const table of await page.locator('table').all()){
  const widths=await table.locator('thead th').evaluateAll(nodes=>nodes.map(n=>n.getBoundingClientRect().width));
  assert.ok(Math.max(...widths)-Math.min(...widths)<1,JSON.stringify(widths));
 }
},{width:1440}));
for(const width of [320,390,1440])it(`presentation: ${width}px actions retain equal widths, one row and full-width Add`,()=>using(async page=>{
 await page.goto(url());await ready(page);
 const row=page.locator('.s29-remove'),buttons=await row.locator('button').all(),boxes=await Promise.all(buttons.map(b=>b.boundingBox()));
 assert.ok(Math.abs(boxes[0].y-boxes[1].y)<1,'Remove actions must stay on one row');
 assert.ok(Math.abs(boxes[0].width-boxes[1].width)<1,'Remove actions must share the available width');
 assert.ok(Math.abs((await page.getByRole('link',{name:'Add another school',exact:true}).boundingBox()).width-(await row.boundingBox()).width)<1,'Add spans the same content width');
 for(const button of buttons){assert.ok((await button.boundingBox()).height>=48);assert.equal(await button.evaluate(e=>getComputedStyle(e).paddingLeft),'10px');}
 const wrappers=await page.locator('.s29-remove .s20-action-icon,.s29-add .s20-action-icon').evaluateAll(nodes=>nodes.map(e=>({box:e.getBoundingClientRect().toJSON(),display:getComputedStyle(e).display,svg:e.querySelector('svg').getBoundingClientRect().toJSON()})));
 for(const x of wrappers){assert.equal(x.box.width,20);assert.equal(x.box.height,20);assert.equal(x.svg.width,18);assert.equal(x.svg.height,18);assert.equal(x.display,'inline-flex');}
},{width}));
it('presentation: disclosure arrows follow the labels and preserve native keyboard opening',()=>using(async page=>{
 await page.goto(url());await ready(page);
 const facts=page.locator('details').first(),summary=facts.locator('summary');
 const arrows=await page.locator('summary').evaluateAll(nodes=>nodes.map(e=>({last:e.lastElementChild?.getAttribute('aria-hidden'),svg:e.lastElementChild?.querySelector('svg')?.getAttribute('width'),first:e.firstElementChild?.textContent})));
 assert.deepEqual(arrows,[{last:'true',svg:'18',first:'Published facts'},{last:'true',svg:'18',first:'Where these figures come from'}]);
 assert.equal(await facts.getAttribute('open'),'');await summary.press('Enter');assert.equal(await facts.getAttribute('open'),null);
 await summary.press('Space');assert.equal(await facts.getAttribute('open'),'');assert.equal(await summary.evaluate(e=>e===document.activeElement),true);
}));
it('presentation: missing figures retain frozen inherited ink, bold weight and italic',()=>using(async page=>{
 await page.goto(url());await ready(page);
 const style=await page.locator('td .s29-na').first().evaluate(e=>{const s=getComputedStyle(e);return {color:s.color,weight:s.fontWeight,style:s.fontStyle};});
 assert.deepEqual(style,{color:'rgb(20, 22, 26)',weight:'700',style:'italic'});
}));
it('presentation: desktop Differences only card retains the frozen 70px height and centered switch',()=>using(async page=>{
 await page.goto(url());await ready(page);const card=await page.locator('.s29-diff').boundingBox(),button=await page.getByRole('switch',{name:'Differences only',exact:true}).boundingBox();
 assert.equal(card.height,70);assert.ok(Math.abs(button.y+button.height/2-card.y-card.height/2)<1);
},{width:1440}));
it('presentation: colored action glyphs retain the frozen nested-wrapper baseline',()=>using(async page=>{
 await page.goto(url());await ready(page);
 for(const action of await page.locator('.s29-remove button,.s29-add').all()){
  const box=await action.boundingBox(),glyph=await action.locator('svg').boundingBox();
  assert.equal(glyph.y+glyph.height/2-(box.y+box.height/2),-1,'the frozen colored wrapper puts its glyph 1px above the action center');
 }
},{width:1440}));


it('QA-S29-01 preserves search query through detail and comparison return links',()=>using(async page=>{
 const ret='state=Karnataka&sort=name&page=2';await page.goto(url()+'&ret='+encodeURIComponent(ret));await ready(page);
 await page.getByRole('link',{name:'Synthetic Law School a',exact:true}).first().click();
 await page.getByRole('link',{name:'Comparison',exact:true}).click();await ready(page);
 for(const name of ['Find a law school','Add another school'])assert.equal(await page.getByRole('link',{name,exact:true}).getAttribute('href'),'/s-27?'+ret);
}));
for(const [status,code,extra,copy] of [
 [404,'school_not_found',{},/school could not be found/i],
 [422,'COMPARE_LIMIT_EXCEEDED',{max_allowed:3},/limited to 3 schools/i],
 [422,'validation_error',{},/selection could not be accepted/i],
 [422,'COMPARE_MIN_NOT_MET',{min_required:3},/at least 3 schools/i]
])it(`QA-S29-02 ${code} gives actionable correction after direct-link/reload`,()=>using(async(page,s)=>{
 await page.goto(url('a,b,c,d'));await page.getByRole('alert').waitFor();
 assert.match(await page.getByRole('alert').innerText(),copy);assert.equal(await page.getByRole('button',{name:'Retry',exact:true}).count(),0);
 assert.equal(await page.getByRole('link',{name:'Change schools',exact:true}).getAttribute('href'),'/s-27');
 // The URL selection can be corrected even though an initial deep link has no tray.
 const remove=page.getByRole('button',{name:'Remove school 4 from comparison',exact:true});await remove.waitFor();s.status=200;s.hold=true;
 await remove.press('Enter');await held(s);assert.deepEqual(s.requests,[['a','b','c','d'],['a','b','c']]);
 assert.notEqual(await page.evaluate(()=>document.activeElement.tagName),'BODY');await s.held.shift()();await ready(page);
 assert.equal(new URL(page.url()).searchParams.get('ids'),'a,b,c');assert.notEqual(await page.evaluate(()=>document.activeElement.tagName),'BODY');
},{status,code,extra}));
it('QA-S29-02 does not invent missing server min/max values',()=>using(async page=>{
 await page.goto(url());await page.getByRole('alert').waitFor();const text=await page.getByRole('alert').innerText();assert.match(text,/server comparison limit/i);assert.doesNotMatch(text,/limited to [0-9]+/);
},{status:422,code:'COMPARE_LIMIT_EXCEEDED'}));
for(const width of [320,360,390])it(`QA-S29-03 ${width}px four-school values and controls are readable and keyboard reachable`,()=>using(async(page,s)=>{
 await page.goto(url('a,b,c,d'));await ready(page);
 const pairs=page.getByRole('group',{name:'Show two of the 4 schools',exact:true}),radios=pairs.getByRole('radio');assert.equal(await radios.count(),6);
 const seen=new Set();
 for(let i=0;i<6;i++){
  if(i===0)await radios.nth(0).focus();else await radios.nth(i-1).press('ArrowRight');
  assert.equal(await radios.nth(i).isChecked(),true);
  for(const name of await page.getByRole('table').first().locator('thead a').allTextContents())seen.add(name);
  for(const button of await page.locator('.s29-remove button').all()){
   const box=await button.boundingBox();assert.ok(box.height>=48);
   const layout=await button.evaluate(e=>({scroll:e.scrollWidth,width:e.clientWidth}));assert.ok(layout.scroll<=layout.width+1,JSON.stringify(layout));
  }
  const fees=await page.getByRole('table').first().locator('tbody tr').filter({has:page.getByRole('rowheader',{name:'Fees',exact:true})}).locator('td').evaluateAll(cells=>cells.map(cell=>{
   const node=[...cell.childNodes].find(n=>n.nodeType===Node.TEXT_NODE);const range=document.createRange();range.setStart(node,0);range.setEnd(node,'₹2,85,000'.length);return [...range.getClientRects()].length;
  }));assert.deepEqual(fees,[1,1],'a rupee amount must not split mid-number');
 }
 assert.equal(seen.size,4);assert.equal(s.requests.length,1);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.setViewportSize({width:1440,height:1024});await page.waitForFunction(()=>document.querySelector('thead').querySelectorAll('a').length===4);
 assert.equal(await pairs.count(),0);assert.equal(s.requests.length,1);
},{width,project:id=>({...school(id),name:`National Law School ${id}`,fees_min:285000,fees_max:285000})}));
it('QA-S29-04 rejects a fabricated non-UUID comparison identity in the rendered page',()=>using(async page=>{
 await page.goto(url());await page.getByRole('alert').waitFor();assert.equal(await page.locator('table').count(),0);assert.match(await page.getByRole('alert').innerText(),/response could not be verified/);assert.doesNotMatch(await page.locator('aside').innerText(),/fabricated-identity/);
},{comparisonId:'fabricated-identity'}));
it('QA-S29-05 no differences reports the shown pair and no empty tables or invented fact count',()=>using(async(page,s)=>{
 await page.goto(url('a,b,c'));await ready(page);await page.getByRole('switch',{name:'Differences only',exact:true}).press('Space');
 await page.getByText('Every compared figure is the same for the schools shown.',{exact:true}).waitFor();
 assert.equal(await page.locator('table').count(),0);assert.match(await page.locator('summary').first().innerText(),/0 differing figures/);assert.doesNotMatch(await page.locator('main').innerText(),/6 more figures/);
 await page.getByText('No published facts differ for the schools shown.',{exact:true}).waitFor();
 await page.getByRole('radio').nth(1).check();await page.getByRole('table').first().waitFor();assert.equal(await page.locator('tbody tr:visible').count(),1);
 assert.equal(await page.getByText('Every compared figure is the same for the schools shown.',{exact:true}).count(),0);assert.equal(s.requests.length,1);
 await page.getByRole('switch',{name:'Differences only',exact:true}).press('Space');assert.match(await page.locator('summary').first().innerText(),/6 more figures/);
},{project:id=>({...school(id),state:id==='c'?'Kerala':'Delhi'})}));
it('QA-S29-05 only differing published facts reports the actual count and keeps nonempty table',()=>using(async page=>{
 await page.goto(url());await ready(page);await page.getByRole('switch',{name:'Differences only',exact:true}).press('Space');
 assert.equal(await page.locator('table').count(),1);assert.match(await page.locator('summary').first().innerText(),/1 differing figure/);assert.equal(await page.locator('tbody tr').count(),1);
 await page.getByText('No core figures differ for the schools shown.',{exact:true}).waitFor();
},{project:id=>({...school(id),state:'Delhi',facts:[{...school(id).facts[0],value:id==='a'?'Available':'Not offered'}]})}));

for(const [status,code,extra,ids,removeIndex] of [
 [404,'school_not_found',{},'a,b,c,dead',4],
 [422,'COMPARE_LIMIT_EXCEEDED',{max_allowed:4},'a,b,c,d,e',2]
]){
 it(`QA-S29-07 ${status} corrected selection has its own pending state, not the preceding error`,()=>using(async(page,s)=>{
  await page.goto(url(ids));await page.getByRole('alert').waitFor();s.status=200;s.hold=true;
  await page.getByRole('button',{name:`Remove school ${removeIndex} from comparison`,exact:true}).press('Enter');await held(s);
  await page.getByRole('status',{name:'Loading comparison',exact:true}).waitFor();
  assert.equal(await page.getByRole('status',{name:'Loading comparison',exact:true}).getAttribute('aria-busy'),'true');
  assert.equal(await page.getByRole('alert').count(),0);assert.equal(await page.locator('.s29-correction').count(),0);
  assert.doesNotMatch(await page.locator('main').innerText(),/HTTP|school_not_found|COMPARE_LIMIT_EXCEEDED/);
  assert.equal(await page.locator('h1').evaluate(el=>el===document.activeElement),true);
  const remaining=ids.split(',').filter((_,i)=>i!==removeIndex-1);assert.deepEqual(s.requests,[ids.split(','),remaining]);
  await s.held.shift()();await ready(page);assert.equal(await page.locator('h1').evaluate(el=>el===document.activeElement),true);
 },{status,code,extra}));
 for(const interaction of ['Tab','second click','outside focus'])it(`QA-S29-08 ${status} ${interaction} during correction preserves meaningful focus`,()=>using(async(page,s)=>{
  await page.goto(url(ids));await page.getByRole('alert').waitFor();s.status=200;s.hold=true;
  const button=page.getByRole('button',{name:`Remove school ${removeIndex} from comparison`,exact:true}),box=await button.boundingBox();
  await button.click();await held(s);
  if(interaction==='Tab')await page.keyboard.press('Tab');
  if(interaction==='second click'){await delay(120);await page.mouse.click(box.x+box.width/2,box.y+box.height/2);}
  const outside=page.getByRole('link',{name:'Find a law school',exact:true});if(interaction==='outside focus')await outside.focus();
  await s.held.shift()();await ready(page);
  await page.waitForFunction(()=>document.activeElement!==document.body);
  if(interaction==='outside focus')assert.equal(await outside.evaluate(el=>el===document.activeElement),true,'never steal deliberate navigation focus');
  assert.deepEqual(s.requests,[ids.split(','),ids.split(',').filter((_,i)=>i!==removeIndex-1)]);
 },{status,code,extra}));
}
it('QA-S29-07 consecutive correction failures belong to the new selection and remain recoverable',()=>using(async(page,s)=>{
 await page.goto(url('a,b,c,dead'));await page.getByRole('alert').waitFor();s.status=422;s.code='COMPARE_LIMIT_EXCEEDED';s.extra={max_allowed:2};s.hold=true;
 await page.getByRole('button',{name:'Remove school 4 from comparison',exact:true}).press('Enter');await held(s);
 await page.getByRole('status',{name:'Loading comparison',exact:true}).waitFor();await s.held.shift()();
 await page.getByText('Comparison is limited to 2 schools. Remove schools to meet the server limit.',{exact:true}).waitFor();
 await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
 assert.equal(await page.getByRole('button',{name:/Remove school \d from comparison/}).count(),3);
 assert.doesNotMatch(await page.getByRole('alert').innerText(),/404|school_not_found/);
 s.status=200;await page.getByRole('button',{name:'Remove school 3 from comparison',exact:true}).press('Enter');await ready(page);
 assert.deepEqual(s.requests,[['a','b','c','dead'],['a','b','c'],['a','b']]);
},{status:404,code:'school_not_found'}));
for(const status of [404,422])it(`QA-S29-07 ${status} pending feedback renders without an artificially held response`,()=>using(async(page,s)=>{
 for(let repetition=0;repetition<5;repetition++){
  s.status=status;await page.goto(url('a,b,c,dead'));await page.getByRole('alert').waitFor();
  await page.evaluate(()=>{
   window.s29PendingSeen=false;
   window.s29PendingObserver=new MutationObserver(()=>{if(document.querySelector('[role="status"][aria-label="Loading comparison"][aria-busy="true"]'))window.s29PendingSeen=true;});
   window.s29PendingObserver.observe(document.querySelector('main'),{subtree:true,childList:true,attributes:true});
  });
  s.status=200;await page.getByRole('button',{name:'Remove school 4 from comparison',exact:true}).press('Enter');await ready(page);
  assert.equal(await page.evaluate(()=>{window.s29PendingObserver.disconnect();return window.s29PendingSeen;}),true);
  assert.deepEqual(s.requests.slice(-2),[['a','b','c','dead'],['a','b','c']]);
  assert.equal(await page.locator('h1').evaluate(el=>el===document.activeElement),true);
 }
 assert.equal(s.requests.length,10);
},{status,code:status===404?'school_not_found':'COMPARE_LIMIT_EXCEEDED',extra:status===422?{max_allowed:3}:{}}));
for(const outcome of [422,503])it(`QA-S29-08 correction HTTP ${outcome} does not steal deliberate outside focus`,()=>using(async(page,s)=>{
 await page.goto(url('a,b,c,dead'));await page.getByRole('alert').waitFor();s.status=outcome;s.code=outcome===422?'COMPARE_LIMIT_EXCEEDED':'unavailable';s.extra={max_allowed:2};s.hold=true;
 await page.getByRole('button',{name:'Remove school 4 from comparison',exact:true}).press('Enter');await held(s);
 await page.getByRole('status',{name:'Loading comparison',exact:true}).waitFor();
 const back=page.getByRole('link',{name:'Find a law school',exact:true});await back.focus();await s.held.shift()();await page.getByRole('alert').waitFor();
 assert.equal(await back.evaluate(el=>el===document.activeElement),true);assert.equal(s.requests.length,2);
 assert.match(await page.getByRole('alert').innerText(),new RegExp(`HTTP ${outcome}`));
},{status:404,code:'school_not_found'}));
