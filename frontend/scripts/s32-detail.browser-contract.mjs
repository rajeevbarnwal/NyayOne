// Synthetic developer regressions, not conformance or independent QA.
import {before,after,it} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {setTimeout as delay} from 'node:timers/promises';
import {preview} from 'vite';
import {chromium} from 'playwright';
import {actor} from './lib/nyay66-fixtures.mjs';
let server,browser,origin;
before(async()=>{server=await preview({preview:{host:'127.0.0.1',port:0},logLevel:'error'});origin=`http://127.0.0.1:${server.httpServer.address().port}`;browser=await chromium.launch();});
after(async()=>{await browser?.close();await new Promise(r=>server?.httpServer.close(r));});
const mentor={id:'mentor-a',display_name:'Synthetic Mentor',headline:'Moot court',experience_years:1,rating_avg:'5.00',rating_count:1,verified_identity:true,verified_credentials:false,status:'active',session_price_paise:89950,currency:'INR',source:'Synthetic registry',source_url:'https://example.test/mentor',retrieved_at:'2026-10-01T00:00:00Z',subjects:[{subject:'Law',level:'Advanced'}],rating_aggregate:{tutor_id:'mentor-a',rating_avg:'5.00',rating_count:1,distribution:{'5':1}}};
const slot=(id='slot-a',start='2027-10-31T00:30:00Z')=>({slot_id:id,tutor_id:mentor.id,start_utc:start,end_utc:new Date(Date.parse(start)+2700000).toISOString(),iana_timezone:'Europe/London',status:'available',start_local:'2027-10-31T01:30:00+01:00',end_local:'2027-10-31T01:15:00+00:00',duration_minutes:45,price_paise:89950,currency:'INR'});
async function using(run,options={}){
 const ctx=await browser.newContext({viewport:{width:390,height:844},timezoneId:'Europe/London'}),p=await ctx.newPage();p.setDefaultTimeout(4000);
 const s={profile:mentor,slots:[slot(),slot('slot-b','2027-10-31T01:30:00Z'),{...slot('held'),status:'held'}],profileStatus:200,availabilityStatus:200,reads:[],held:[],unexpected:[],...options};
 await p.route('**/*',async route=>{const r=route.request(),u=new URL(r.url()),reply=(b,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(b)}).catch(()=>{});
  if(u.origin!==origin&&!(u.origin==='http://localhost:1131'&&u.pathname.startsWith('/api/v1/'))){s.unexpected.push(u.origin);return route.abort();}if(!u.pathname.startsWith('/api/v1/'))return route.continue();
  if(u.pathname==='/api/v1/auth/student/session')return reply(s.signedOut?{authenticated:false,actor:null}:{authenticated:true,actor});
  if(r.method()==='GET'&&u.pathname.startsWith('/api/v1/tutors/')){
   const av=u.pathname.endsWith('/availability');s.reads.push({av,q:Object.fromEntries(u.searchParams),path:u.pathname});const status=av?s.availabilityStatus:s.profileStatus;if(status===401)s.signedOut=true;
   const body=status!==200?{detail:{code:status===401?'authentication_required':status===404?'NOT_FOUND':'server_error',retry_after_seconds:s.retryAfter??0}}:av?{tutor_id:mentor.id,iana_timezone:u.searchParams.get('timezone'),window:{from_utc:null,to_utc:null},local_resolution:s.resolution??{},slots:s.slots.map(x=>({...x,iana_timezone:u.searchParams.get('timezone')})),limit:50,offset:Number(u.searchParams.get('offset'))}:s.profile;
   const done=()=>reply(body,status);if(s.hold=== (av?'availability':'profile')){s.hold=null;s.held.push(done);return;}return done();
  }
  s.unexpected.push(`${r.method()} ${u.pathname}`);return route.abort();
 });try{await run(p,s);assert.deepEqual(s.unexpected,[]);}finally{await ctx.close();}
}
const ready=async p=>{await p.getByRole('heading',{name:'Synthetic Mentor',exact:true}).waitFor();await p.getByRole('radiogroup').waitFor();};
async function held(s){for(let i=0;!s.held.length&&i<400;i++)await delay(10);assert.ok(s.held.length);}
it('Revision L detail uses server facts, one main, device zone and selection before booking',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-32?tutor=mentor-a');await ready(p);assert.equal(await p.locator('main').count(),1);assert.equal(await p.locator('.ls-shell').count(),0);assert.match(await p.locator('main').innerText(),/5.00 from 1 rating\b/);assert.match(await p.locator('main').innerText(),/₹899.50/);
 assert.equal(s.reads.find(r=>r.av).q.timezone,'Europe/London');assert.equal(await p.getByRole('button',{name:'Continue to booking',exact:true}).isDisabled(),true);
 const radios=p.getByRole('radio');await radios.nth(0).press('Space');assert.equal(await radios.nth(0).getAttribute('aria-checked'),'true');assert.match(p.url(),/s-32/);assert.equal(s.reads.length,2);
 await radios.nth(0).press('ArrowRight');assert.equal(await radios.nth(1).getAttribute('aria-checked'),'true');assert.equal(await radios.nth(2).isDisabled(),true);
 await p.route('**/api/v1/booking/holds',r=>r.abort()); // Navigation is tested before mounting S-33, which owns the hold.
 await p.getByRole('button',{name:'Continue to booking',exact:true}).evaluate(e=>e.addEventListener('click',()=>{}));
 assert.equal(await p.getByRole('button',{name:'Continue to booking',exact:true}).isEnabled(),true);
}));
it('DST fall-back times expose distinct offsets, duration and slot price',()=>using(async p=>{await p.goto(origin+'/s-32?tutor=mentor-a&tz=Europe/London');await ready(p);const a=await p.getByRole('radio').nth(0).innerText(),b=await p.getByRole('radio').nth(1).innerText();assert.notEqual(a,b);assert.match(a,/45 min.*₹899.50/s);assert.match(a,/GMT\+1|BST/);assert.match(b,/GMT/);}));
it('changing zone or day clears selection immediately and stale responses cannot replace latest slots',()=>using(async(p,s)=>{
 await p.goto(origin+'/s-32?tutor=mentor-a');await ready(p);await p.getByRole('radio').first().click();s.hold='availability';await p.getByLabel('Show times in',{exact:true}).selectOption('Asia/Kolkata');await held(s);
 assert.equal(await p.getByRole('button',{name:'Continue to booking',exact:true}).isDisabled(),true);s.slots=[slot('latest')];await p.getByLabel('On a single day',{exact:true}).fill('2027-11-01');await p.locator('[data-slot="latest"]').waitFor();await s.held.shift()();await delay(60);assert.equal(await p.locator('[data-slot="slot-a"]').count(),0);assert.equal(s.reads.at(-1).q.date,'2027-11-01');assert.equal(s.reads.at(-1).q.timezone,'Asia/Kolkata');
}));
for(const kind of ['profile','availability'])it(`${kind} retry stays focused while pending, duplicates lock and moved focus is respected`,()=>using(async(p,s)=>{
 await p.goto(origin+'/s-32?tutor=mentor-a');const retry=p.getByRole('button',{name:kind==='profile'?'Retry':'Retry availability',exact:true});await retry.waitFor();s.hold=kind;await retry.press('Enter');await held(s);assert.notEqual(await p.evaluate(()=>document.activeElement.tagName),'BODY');await retry.evaluate(e=>{e.click();e.click();});assert.equal(s.reads.filter(r=>r.av===(kind==='availability')).length,2);await s.held.shift()();await p.waitForFunction(()=>document.activeElement.getAttribute('role')==='alert');
 s[kind==='profile'?'profileStatus':'availabilityStatus']=200;s.hold=kind;await retry.press('Enter');await held(s);await p.getByRole('link',{name:'Mentors',exact:true}).focus();await s.held.shift()();await ready(p);assert.equal(await p.getByRole('link',{name:'Mentors',exact:true}).evaluate(e=>e===document.activeElement),true);
},{[kind==='profile'?'profileStatus':'availabilityStatus']:503}));
it('missing identity sends no profile or availability request',()=>using(async(p,s)=>{await p.goto(origin+'/s-32');await p.getByRole('heading',{name:'Choose a mentor first.',exact:true}).waitFor();assert.equal(s.reads.length,0);}));
it('profile failure never invents price or availability; 404 and malformed success remain distinct',()=>using(async(p,s)=>{await p.goto(origin+'/s-32?tutor=mentor-a');await p.getByRole('alert').waitFor();assert.equal(s.reads.length,1);assert.doesNotMatch(await p.locator('main').innerText(),/No open times|₹0|HTTP 200/);},{profile:{}}));
it('401 retains real session redirect and bounded requests',()=>using(async(p,s)=>{await p.goto(origin+'/s-32?tutor=mentor-a');await p.waitForURL(/\/s-03/);assert.equal(s.reads.length,1);},{profileStatus:401}));
it('offline retry makes no request and reconnect retry clears offline feedback',()=>using(async(p,s)=>{await p.goto(origin+'/s-32?tutor=mentor-a');const retry=p.getByRole('button',{name:'Retry availability',exact:true});await retry.waitFor();await p.context().setOffline(true);await retry.click();await p.getByText('No request was sent. Reconnect and retry.',{exact:true}).waitFor();assert.equal(s.reads.length,2);await p.context().setOffline(false);s.availabilityStatus=200;await retry.click();await ready(p);assert.equal(await p.getByRole('alert').count(),0);},{availabilityStatus:503}));
for(const width of [320,1440])it(`${width}px reflow and serious/critical accessibility`,()=>using(async p=>{await p.setViewportSize({width,height:1024});await p.goto(origin+'/S-32/?tutor=mentor-a');await ready(p);assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await p.addScriptTag({content:await readFile('node_modules/axe-core/axe.min.js','utf8')});assert.deepEqual(await p.evaluate(async()=>(await window.axe.run()).violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>v.id)),[]);for(const x of await p.locator('main button:visible, main select:visible, main input:visible').all())assert.ok((await x.boundingBox()).height>=48);}));
it('Clear day moves focus to the stable times heading while its button disappears',()=>using(async(p,s)=>{await p.goto(origin+'/s-32?tutor=mentor-a&date=2027-10-31');await ready(p);s.hold='availability';await p.getByRole('button',{name:'Clear day',exact:true}).press('Enter');await held(s);assert.equal(await p.evaluate(()=>document.activeElement.id),'s32-times');await s.held.shift()();await ready(p);assert.equal(await p.evaluate(()=>document.activeElement.id),'s32-times');}));
it('429 respects cooldown without automatic calls or permanent lock',()=>using(async(p,s)=>{await p.goto(origin+'/s-32?tutor=mentor-a');const retry=p.getByRole('button',{name:'Retry',exact:true});await retry.waitFor();assert.equal(await retry.getAttribute('aria-disabled'),'true');await retry.evaluate(e=>e.click());assert.equal(s.reads.length,1);await p.waitForFunction(()=>document.querySelector('[role=alert] button')?.getAttribute('aria-disabled')==='false');s.profileStatus=200;await retry.click();await ready(p);assert.equal(s.reads.length,3);},{profileStatus:429,retryAfter:1}));
it('unsafe source URLs are never clickable and null fields remain explicitly unknown',()=>using(async p=>{await p.goto(origin+'/s-32?tutor=mentor-a');await ready(p);assert.equal(await p.locator('main a[href^="javascript:"]').count(),0);assert.match(await p.locator('main').innerText(),/No ratings yet/);},{profile:{...mentor,source_url:'javascript:alert(1)',retrieved_at:null,rating_aggregate:{...mentor.rating_aggregate,rating_count:0,rating_avg:null}}}));
