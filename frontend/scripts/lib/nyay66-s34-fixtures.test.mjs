import {describe,it,expect,vi,afterEach} from 'vitest';
import {S34_STATES} from './nyay66-s34-reference.mjs';
import {s34Wire,expectedS34Requests,verifyS34Requests,classifyS34Errors,s34HttpError} from './nyay66-s34-fixtures.mjs';
import {readSessionDetail} from '../../src/features/student/tutoring/s34Api';
import {actor} from './nyay66-fixtures.mjs';
afterEach(()=>vi.unstubAllGlobals());
const origin='http://localhost:1234';
describe('S-34 session capture fixtures',()=>{
 it('uses the production adapter and server session status, without invented payment/room fields',async()=>{
  const fetch=vi.fn();vi.stubGlobal('fetch',fetch);
  for(const state of ['confirmed','pending-provider','cancelled']){
   const w=s34Wire(state);fetch.mockResolvedValue(new Response(JSON.stringify(w),{status:200}));
   expect(await readSessionDetail(w.id,actor.sub)).toEqual(w);
   expect(w.status).toBe(state==='pending-provider'?'pending_provider':state);
   expect(w).not.toHaveProperty('amount_paise');expect(w).not.toHaveProperty('join_url');expect(w).not.toHaveProperty('payment_status');
   expect(w.student_user_id).toBe(actor.sub);
  }
  expect(()=>s34Wire('invented')).toThrow('S34_FIXTURE_SCOPE');
 });
 it('requires exactly session bootstrap and one GET detail with no query/body/mutation',()=>{
  for(const state of S34_STATES){const q=expectedS34Requests(state);expect(q).toHaveLength(2);expect(verifyS34Requests(state,q)).toBe(true);
   for(const bad of [q.slice(1),[...q,q[1]],q.map((r,i)=>i?{...r,method:'POST'}:r),q.map((r,i)=>i?{...r,search:'?paid=true'}:r),q.map((r,i)=>i?{...r,body:{confirmed:true}}:r),q.map((r,i)=>i?{...r,path:r.path+'x'}:r)])expect(verifyS34Requests(state,bad)).toBe(false);
  }
  expect(verifyS34Requests('invented',[])).toBe(false);
 });
 it('uses real 503/404 and rejects absent, duplicate or unrelated HTTP/console failures',()=>{
  expect(s34HttpError('error').status).toBe(503);expect(s34HttpError('missing').status).toBe(404);
  for(const state of S34_STATES){const e=s34HttpError(state),url=e?origin+e.path:'',http=e?[{method:'GET',url,status:e.status}]:[],messages=e?[{url,text:`Failed to load resource: the server responded with a status of ${e.status} (${e.reason})`}]:[];
   expect(classifyS34Errors(state,origin,messages,http,[],http).errors).toEqual([]);
   if(e)for(const args of [[[],http,[],http],[messages,[],[],http],[messages,http,[],[]],[[...messages,...messages],http,[],http],[messages,[{...http[0],status:200}],[],http],[messages,http,[{url}],http]])expect(classifyS34Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
   expect(classifyS34Errors(state,origin,[...messages,{url:origin,text:'unexpected'}],http,[],http).errors).toContain('CONSOLE_ERROR');
  }
 });
});
