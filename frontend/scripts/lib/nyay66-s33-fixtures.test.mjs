import {describe,it,expect,vi,afterEach} from 'vitest';
import {S33_STATES} from './nyay66-s33-reference.mjs';
import {s33Wire,S33_PATHS,expectedS33Requests,verifyS33Requests,classifyS33Errors,s33HttpError} from './nyay66-s33-fixtures.mjs';
import {createHold,readHold,createOrder,confirmSession} from '../../src/features/student/tutoring/s33Api';
import {readMentorDetail,readMentorAvailability} from '../../src/features/student/tutoring/s32Api';
import {actor} from './nyay66-fixtures.mjs';
afterEach(()=>vi.unstubAllGlobals());
const origin='http://localhost:1234';
describe('S-33 server-authoritative capture fixtures',()=>{
 it('uses production adapters and real server contracts including alternate tutor and duration',async()=>{
  const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
  for(const state of S33_STATES){
   const w=s33Wire(state),reply=(v,status=200)=>fetch.mockResolvedValue(new Response(JSON.stringify(v),{status}));
   reply(w.mentor);expect(await readMentorDetail(w.mentor.id)).toEqual(w.mentor);
   reply(w.availability);expect(await readMentorAvailability(w.mentor.id,new URLSearchParams('timezone=Asia%2FKolkata&limit=100&offset=0'))).toEqual(w.availability);
   reply(w.hold,201);expect(await createHold(w.slot.slot_id,'hold-test')).toEqual(w.hold);
   reply(w.expired);expect(await readHold(w.hold)).toEqual(w.expired);
   reply(w.order,201);expect(await createOrder(w.hold,'order-test')).toEqual(w.order);
   reply(w.session,201);expect(await confirmSession(w.hold,w.mentor.id,actor.sub,w.order.id)).toEqual(w.session);
   expect(w.order.amount_paise).toBe(w.hold.price_paise);expect(w.hold.price_paise).toBe(w.slot.price_paise);
   expect(Date.parse(w.slot.end_utc)-Date.parse(w.slot.start_utc)).toBe(w.slot.duration_minutes*60000);
  }
  expect(s33Wire('hold-60min').slot.duration_minutes).toBe(60);
  expect(s33Wire('hold-other-mentor').mentor.id).not.toBe(s33Wire('hold-active').mentor.id);
  expect(()=>s33Wire('invented')).toThrow('S33_FIXTURE_SCOPE');
 });
 it('requires exact methods, paths, query and request bodies; no client price, secret or forged confirmation',()=>{
  for(const state of S33_STATES){
   const q=expectedS33Requests(state);expect(verifyS33Requests(state,q)).toBe(true);
   for(const bad of [q.slice(1),[...q,q[0]],q.map((r,i)=>i?r:{...r,method:'POST'}),q.map((r,i)=>i?r:{...r,search:'?x=1'}),q.map(r=>r.method==='POST'?{...r,body:{...r.body,amount_paise:1}}:r)])expect(verifyS33Requests(state,bad)).toBe(false);
   for(const r of q.filter(r=>r.method==='POST'))expect(Object.keys(r.body).sort()).toEqual(r.path===S33_PATHS.confirm?['hold_id']:r.path===S33_PATHS.order?['hold_id','idempotency_key']:['idempotency_key','slot_id']);
  }
 });
 it('uses genuine 409, 400, 429, 503 and 401 statuses, never disguising errors as 200',()=>{
  expect(['slot-conflict','payment-unverified','rate-limited','network','session'].map(s=>s33HttpError(s)?.status)).toEqual([409,400,429,503,401]);
  for(const state of S33_STATES){
   const e=s33HttpError(state),url=e?origin+e.path:'',http=e?[{method:e.method,url,status:e.status}]:[],messages=e?[{url,text:`Failed to load resource: the server responded with a status of ${e.status} (${e.reason})`}]:[];
   expect(classifyS33Errors(state,origin,messages,http,[],http).errors).toEqual([]);
   if(e)for(const args of [[[],http,[],http],[messages,[],[],http],[messages,http,[],[]],[[...messages,...messages],http,[],http],[messages,[{...http[0],status:200}],[],http],[messages,http,[{url}],http]])expect(classifyS33Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
   expect(classifyS33Errors(state,origin,[...messages,{url:origin,text:'unexpected'}],http,[],http).errors).toContain('CONSOLE_ERROR');
  }
 });
});
