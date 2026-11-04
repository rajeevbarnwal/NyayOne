// Synthetic developer browser regressions. Not conformance or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {setTimeout as delay} from 'node:timers/promises';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {actor} from './lib/nyay66-fixtures.mjs';
let server,browser,origin;
before(async()=>{server=await preview({build:{outDir:process.env.S31_BASE_DIST??'dist'},preview:{host:'127.0.0.1',port:0},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(done=>server?.httpServer.close(done));});
const tutor=(id='a')=>({id,display_name:`Synthetic Mentor ${id}`,headline:'Moot court',experience_years:5,rating_avg:'4.80',rating_count:31,verified_identity:true,verified_credentials:false,status:'active',session_price_paise:89950,currency:'INR'});
async function using(run,options={}){
 const context=await browser.newContext({viewport:{width:390,height:844},reducedMotion:'reduce'}),p=await context.newPage();p.setDefaultTimeout(4000);
 const s={items:[tutor()],total:25,status:200,hold:false,held:[],reads:[],unexpected:[],...options};
 await p.route('**/*',async route=>{const r=route.request(),u=new URL(r.url()),reply=(v,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(v)}).catch(()=>{});
  if(u.origin!==origin&&!(u.origin==='http://localhost:1131'&&u.pathname.startsWith('/api/v1/'))){s.unexpected.push(u.origin);return route.abort();}if(!u.pathname.startsWith('/api/v1/'))return route.continue();
  if(u.pathname==='/api/v1/auth/student/session')return reply(s.signedOut?{authenticated:false,actor:null}:{authenticated:true,actor});
  if(u.pathname==='/api/v1/tutors'&&r.method()==='GET'){
   const q=Object.fromEntries(u.searchParams);s.reads.push(q);if(s.status===401)s.signedOut=true;
   const status=s.status,body=s.malformed?{}:status===200?{items:s.items,total:s.total,offset:Number(q.offset),limit:Number(q.limit),has_more:Number(q.offset)+s.items.length<s.total,sort:q.sort,allowed_sorts:['rating_desc','rating_asc','experience_desc','experience_asc','name_asc','newest']}:{detail:{code:status===401?'authentication_required':status===429?'rate_limit_exceeded':'unavailable',retry_after_seconds:s.retryAfter??0}};
   const done=()=>reply(body,status);if(s.hold){s.hold=false;s.held.push(done);return;}return done();
  }
  s.unexpected.push(`${r.method()} ${u.pathname}`);return route.abort();
 });try{await run(p,s);assert.deepEqual(s.unexpected,[]);}catch(e){console.error({url:p.url(),text:(await p.locator('body').innerText()).slice(0,1500),reads:s.reads,unexpected:s.unexpected});throw e;}finally{await context.close();}
}
const cards=p=>p.locator('.s31-discovery article');
const ready=async p=>{await p.getByRole('heading',{name:'Find a mentor.',exact:true}).waitFor();await cards(p).first().waitFor();};
async function held(s){for(let i=0;!s.held.length&&i<400;i++)await delay(10);assert.ok(s.held.length);}
it('loading S-31 leaves historical school CSS cascade overrides intact',()=>using(async p=>{
 await p.setViewportSize({width:1440,height:1024});await p.goto(origin+'/s-31');await ready(p);
 // Production-bundle probes catch a repeated shared-CSS import overriding
 // earlier school-specific rules, without changing their behavioral fixtures.
 const actual=await p.evaluate(()=>{
  const probe=document.createElement('div');probe.innerHTML='<div class="v321-internships s27-search"><section class="s20-card"><h2 class="s20-eyebrow">Saved schools</h2></section></div><div class="v321-internships s28-detail"><div class="s20-actions s28-actions"><button class="s20-btn">Save</button><button class="s20-btn">Follow</button></div></div>';
  document.body.append(probe);
  try{return {schoolEyebrowMargin:getComputedStyle(probe.querySelector('.s20-eyebrow')).marginBottom,schoolActionGap:getComputedStyle(probe.querySelector('.s28-actions')).gap};}finally{probe.remove();}
 });
 assert.deepEqual(actual,{schoolEyebrowMargin:'0px',schoolActionGap:'9px'});
}));
it('Revision L discovery shows server price, ratings and separate verified claims, one main, no legacy shell',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31');await ready(p);assert.equal(await p.locator('main').count(),1);assert.equal(await p.locator('.ls-shell').count(),0);
 assert.match(await cards(p).innerText(),/₹899.50 per session/);assert.match(await cards(p).innerText(),/4.80.*31/);assert.match(await cards(p).innerText(),/Identity verified/);assert.doesNotMatch(await cards(p).innerText(),/Credentials verified|Next available|60 min|free cancellation/);
 assert.equal(s.reads.length,1);assert.equal(await p.getByRole('link',{name:/Synthetic Mentor a/}).getAttribute('href'),'/s-32?tutor=a');
}));
it('search/filters/sort are server-side, reset offset, and restore drafts with Back',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31?offset=10');await ready(p);await p.getByText('Filters and sort',{exact:true}).click();
 await p.getByRole('searchbox',{name:'Search mentors',exact:true}).fill('Arbitration');await p.getByLabel('Subject',{exact:true}).fill('Custom subject');await p.getByLabel('Level',{exact:true}).fill('Advanced');
 await p.getByLabel('Minimum rating',{exact:true}).selectOption('4.5');await p.getByLabel('Minimum experience',{exact:true}).selectOption('5');await p.getByLabel('Verified mentors only',{exact:true}).check();await p.getByLabel('Sort by',{exact:true}).selectOption('name_asc');
 await p.getByRole('button',{name:'Show mentors',exact:true}).press('Enter');await p.waitForURL('**q=Arbitration*');await ready(p);
 assert.deepEqual(s.reads.at(-1),{q:'Arbitration',subject:'Custom subject',level:'Advanced',min_rating:'4.5',min_experience_years:'5',verified_only:'true',sort:'name_asc',limit:'10',offset:'0'});
 assert.equal(await cards(p).count(),1,'do not locally filter a server-selected result');await p.goBack();await p.waitForURL('**offset=10');assert.equal(await p.getByRole('searchbox',{name:'Search mentors',exact:true}).inputValue(),'');assert.equal(await p.getByLabel('Subject',{exact:true}).inputValue(),'');
}));
it('pagination keeps focused controls while pending, duplicate-locks, then focuses summary',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31');await ready(p);s.hold=true;const next=p.getByRole('button',{name:'Next page',exact:true});await next.press('Enter');await held(s);
 assert.equal(await next.evaluate(e=>e===document.activeElement),true);await next.evaluate(e=>{e.click();e.click();});assert.equal(s.reads.length,2);assert.equal(s.reads[1].offset,'10');
 await s.held.shift()();await p.waitForFunction(()=>document.activeElement?.id==='s31-results-summary');
 s.hold=true;await p.getByRole('button',{name:'Previous page',exact:true}).press('Enter');await held(s);await p.getByRole('searchbox',{name:'Search mentors',exact:true}).focus();await s.held.shift()();await ready(p);assert.equal(await p.getByRole('searchbox').evaluate(e=>e===document.activeElement),true);
}));
it('initial loading and malformed 2xx never claim no results or free prices',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31');await held(s);await p.getByRole('status',{name:'Loading mentors'}).waitFor();assert.doesNotMatch(await p.locator('main').innerText(),/0 mentors|No mentors match|Free/);
 await s.held.shift()();await p.getByRole('alert').waitFor();assert.doesNotMatch(await p.getByRole('alert').innerText(),/HTTP 200|No mentors match/);
},{hold:true,malformed:true}));
for(const status of [422,429,503])it(`HTTP ${status}: repeated Retry retains focus and request count is bounded`,()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31');await p.getByRole('alert').waitFor();await p.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');assert.match(await p.getByRole('alert').innerText(),new RegExp(`HTTP ${status}`));
 const retry=p.getByRole('button',{name:status===429?'Try again':'Retry',exact:true});s.hold=true;await retry.press('Enter');await held(s);assert.notEqual(await p.evaluate(()=>document.activeElement.tagName),'BODY');await retry.evaluate(e=>{e.click();e.click();});assert.equal(s.reads.length,2);
 await s.held.shift()();await p.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');
 s.status=200;s.hold=true;await retry.press('Enter');await held(s);await p.getByRole('searchbox').focus();await s.held.shift()();await ready(p);assert.equal(await p.getByRole('searchbox').evaluate(e=>e===document.activeElement),true);
},{status}));
it('429 cooldown advances without sending automatic search requests',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31');const retry=p.getByRole('button',{name:'Try again',exact:true});await retry.waitFor();assert.equal(await retry.getAttribute('aria-disabled'),'true');await retry.evaluate(e=>e.click());assert.equal(s.reads.length,1);
 await p.waitForFunction(()=>document.querySelector('[data-s31-retry]')?.getAttribute('aria-disabled')==='false');assert.equal(s.reads.length,1);
},{status:429,retryAfter:1}));
it('offline Retry sends nothing and online pending feedback stops claiming offline',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31');await p.getByRole('alert').waitFor();await p.context().setOffline(true);await p.getByRole('button',{name:'Retry',exact:true}).press('Enter');await p.getByText('No request was sent. Reconnect and retry.',{exact:true}).waitFor();assert.equal(s.reads.length,1);
 await p.context().setOffline(false);s.hold=true;s.status=200;await p.getByRole('button',{name:'Retry',exact:true}).press('Enter');await held(s);assert.doesNotMatch(await p.getByRole('alert').innerText(),/offline|No request was sent/);await s.held.shift()();await ready(p);assert.equal(await p.getByRole('alert').count(),0);
},{status:503}));
it('zero results and out-of-range pages preserve server total and recovery',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31?offset=40');await p.getByRole('heading',{name:'No mentors on this page.',exact:true}).waitFor();assert.match(await p.locator('main').innerText(),/25 mentors/);s.total=0;
 await p.getByRole('button',{name:'Clear filters',exact:true}).press('Enter');await p.getByRole('heading',{name:'No mentors match.',exact:true}).waitFor();assert.equal(s.reads.at(-1).offset,'0');assert.notEqual(await p.evaluate(()=>document.activeElement.tagName),'BODY');
},{items:[]}));
it('401 retains the shared session-expiry redirect, no private results',()=>using(async(p,s)=>{await p.goto(origin+'/s-31');await p.waitForURL(/\/s-03/);assert.equal(await cards(p).count(),0);assert.equal(s.reads.length,1);},{status:401}));
it('320px reflow, 48px controls, no serious/critical axe, long Unicode names',()=>using(async(p)=>{
 await p.setViewportSize({width:320,height:844});await p.goto(origin+'/s-31');await ready(p);await p.getByText('Filters and sort',{exact:true}).click();assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 for(const e of await p.locator('.s31-discovery button:visible, .s31-discovery input:visible, .s31-discovery select:visible, .s31-discovery summary:visible, .s31-discovery a:visible').all()){const target=await e.evaluate(el=>{const hit=el.matches('input[type=checkbox]')?el.closest('label'):el;return hit.getBoundingClientRect().height;});assert.ok(target>=48,await e.getAttribute('id'));}
 await p.addScriptTag({content:await readFile('node_modules/axe-core/axe.min.js','utf8')});assert.deepEqual(await p.evaluate(async()=>(await window.axe.run()).violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>v.id)),[]);
},{items:[{...tutor(),display_name:'अदिति 名 Mentor WithAReallyLongUnbrokenNameWithoutSpaces',headline:null,rating_avg:null,rating_count:0}]}));
it('a superseded slow search cannot replace the latest response or steal moved focus',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31');await ready(p);s.hold=true;s.items=[tutor('older')];
 const search=p.getByRole('searchbox',{name:'Search mentors',exact:true});await search.fill('older');await search.press('Enter');await held(s);
 s.items=[tutor('latest')];await search.fill('latest');await search.press('Enter');await p.getByRole('link',{name:/Synthetic Mentor latest/}).waitFor();await search.focus();
 await s.held.shift()();await delay(60);assert.equal(await p.getByRole('link',{name:/Synthetic Mentor older/}).count(),0);assert.equal(await p.getByRole('link',{name:/Synthetic Mentor latest/}).count(),1);assert.equal(await search.evaluate(e=>e===document.activeElement),true);assert.equal(s.reads.length,3);
}));
it('anonymous students redirect before any mentor read',()=>using(async(p,s)=>{await p.goto(origin+'/s-31');await p.waitForURL(/\/s-03/);assert.equal(s.reads.length,0);assert.equal(await cards(p).count(),0);},{signedOut:true}));
it('desktop case/slash route preserves one main, sessions link and keyboard-search label',()=>using(async p=>{
 await p.setViewportSize({width:1440,height:1024});await p.goto(origin+'/S-31/?sort=name_asc#results');await ready(p);assert.equal(await p.locator('main').count(),1);assert.equal(await p.locator('.s20-related').isVisible(),false);assert.equal(await p.locator('aside').getByRole('link',{name:'My sessions',exact:true}).getAttribute('href'),'/s-35');assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await p.getByRole('searchbox',{name:'Search mentors',exact:true}).press('Tab');assert.equal(await p.getByRole('button',{name:'Search mentors',exact:true}).evaluate(e=>e===document.activeElement),true);
}));
it('frozen compact My sessions action, card link typography and offline icon are preserved',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-31');await ready(p);
 const sessions=p.locator('.s20-related').getByRole('link',{name:'My sessions',exact:true});assert.ok((await sessions.boundingBox()).width<200,'mobile related action must remain intrinsic width');
 assert.equal(await sessions.evaluate(e=>getComputedStyle(e).textDecorationLine),'none');assert.equal(await cards(p).first().locator('.s20-title').evaluate(e=>getComputedStyle(e).textDecorationLine),'none');
 s.status=503;await p.reload();await p.getByRole('alert').waitFor();await p.context().setOffline(true);await p.getByRole('button',{name:'Retry',exact:true}).click();
 assert.equal(await p.locator('.s20-state-icon path[d="M4 4l16 16"]').count(),1,'offline uses frozen offline primitive');
}));

// Frozen v3.2.1.08 presentation contract; existing behavior probes remain above.
for (const width of [390, 1440]) {
 it(`S-31 ${width}: My sessions uses the frozen nested icon baseline`,()=>using(async p=>{
  await p.setViewportSize({width,height:1024});await p.goto(origin+'/s-31');await ready(p);
  const link=p.locator(width>=900?'aside':'.s20-related').getByRole('link',{name:'My sessions',exact:true});
  assert.equal((await link.locator('svg').boundingBox()).y-(await link.boundingBox()).y,14);assert.equal(await link.getAttribute('href'),'/s-35');
 }));
 it(`S-31 ${width}: mentor name typography has no inherited internship underline`,()=>using(async p=>{
  await p.setViewportSize({width,height:1024});await p.goto(origin+'/s-31');await ready(p);
  const link=cards(p).first().getByRole('link');assert.equal(await link.locator('span').evaluate(e=>getComputedStyle(e).textDecorationLine),'none');
  assert.equal(await link.getAttribute('href'),'/s-32?tutor=a');await link.focus();assert.equal(await link.evaluate(e=>getComputedStyle(e).outlineStyle),'solid');
 }));

 it(`S-31 ${width}: expanded filter fields start immediately below the summary`,()=>using(async p=>{
  await p.setViewportSize({width,height:1024});await p.goto(origin+'/s-31');await ready(p);await p.getByText('Filters and sort',{exact:true}).click();
  const summary=await p.locator('.s20-filters summary').boundingBox(),field=await p.locator('.s20-filter-body .s20-field').first().boundingBox();
  assert.equal(field.y,summary.y+summary.height,'frozen filter body has no extra 4px top inset');
 }));
 it(`S-31 ${width}: verified checkbox has a compact bordered 48px label target`,()=>using(async(p,s)=>{
  await p.setViewportSize({width,height:1024});await p.goto(origin+'/s-31');await ready(p);await p.getByText('Filters and sort',{exact:true}).click();
  const row=p.locator('.s31-check'),box=await row.boundingBox(),input=p.getByRole('checkbox',{name:'Verified mentors only'});
  assert.equal(await row.evaluate(e=>getComputedStyle(e).borderTopStyle),'solid');
  assert.equal(await row.evaluate(e=>getComputedStyle(e).borderRadius),'12px');
  assert.equal(await row.locator('b').evaluate(e=>getComputedStyle(e).fontSize),'13.5px');
  const glyph=await input.boundingBox();assert.equal(glyph.width,22);assert.equal(glyph.height,22);assert.ok(box.height>=48);
  assert.equal(glyph.x-box.x,13);assert.equal(await row.evaluate(e=>getComputedStyle(e).gap),'12px');
  await row.click({position:{x:box.width-6,y:box.height/2}});assert.equal(await input.isChecked(),true,'entire label is an active touch target');
  await input.press('Space');assert.equal(await input.isChecked(),false,'native keyboard behavior is retained');assert.equal(s.reads.length,1,'checkbox only edits a draft');
 }));
 it(`S-31 ${width}: empty Clear filters retains the frozen 18px icon and 48px action`,()=>using(async p=>{
  await p.setViewportSize({width,height:1024});await p.goto(origin+'/s-31');const clear=p.getByRole('button',{name:'Clear filters',exact:true});await clear.waitFor();
  assert.equal(await clear.locator('svg path[d="M4 6h16M7 12h10M10 18h4"]').count(),1);assert.equal((await clear.locator('svg').boundingBox()).width,18);assert.ok((await clear.boundingBox()).height>=48);
 },{items:[],total:0}));
 it(`S-31 ${width}: real HTTP 429 uses a compact clock notice and outlined retry`,()=>using(async p=>{
  await p.setViewportSize({width,height:1024});await p.goto(origin+'/s-31');const alert=p.getByRole('alert');await alert.waitFor();
  const clock=alert.locator('svg').first(),h=alert.getByRole('heading'),retry=alert.getByRole('button',{name:'Try again'}),box=await alert.boundingBox(),heading=await h.boundingBox();
  assert.equal(await clock.locator('circle[cx="12"][cy="12"][r="8.5"]').count(),2);assert.equal((await clock.boundingBox()).width,18);
  assert.equal(heading.x-box.x,43,'4px warning border + 12px padding + 18px clock + 9px gap');
  assert.equal(heading.y-box.y,10,'notice starts at 9px padding plus border');
  assert.equal(await h.evaluate(e=>getComputedStyle(e).fontSize),'12.5px');assert.equal(await h.evaluate(e=>getComputedStyle(e).lineHeight),'18.75px');
  assert.equal(await retry.evaluate(e=>getComputedStyle(e).backgroundColor),'rgb(255, 255, 255)');assert.equal(await retry.locator('svg').evaluate(e=>getComputedStyle(e).color),'rgb(46, 58, 140)');
  assert.equal((await retry.locator('svg').boundingBox()).y-(await retry.boundingBox()).y,14,'frozen nested icon wrapper preserves its baseline');assert.ok((await retry.boundingBox()).height>=48);assert.match(await alert.innerText(),/HTTP 429.*rate_limit_exceeded/);assert.equal(await alert.getAttribute('tabindex'),'-1');
 },{status:429}));
}
