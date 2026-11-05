import {describe,it,expect,vi,afterEach} from 'vitest';
import {S32_ID,S32_PATHS,S32_MENTOR,s32Route,s32AvailabilityResponse,expectedS32Requests,verifyS32Requests,classifyS32Errors} from './nyay66-s32-fixtures.mjs';
import {S32_STATES} from './nyay66-s32-reference.mjs';
import {readMentorDetail,readMentorAvailability} from '../../src/features/student/tutoring/s32Api';
const origin='http://127.0.0.1:4321';
afterEach(()=>vi.unstubAllGlobals());
describe('S-32 backend-grounded profile and availability fixtures',()=>{
 it('passes production adapters with UUIDs, separate claims, public ratings and integer-paise published prices',async()=>{
  expect(S32_ID).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
  const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(S32_MENTOR)));vi.stubGlobal('fetch',fetch);
  expect(await readMentorDetail(S32_ID)).toEqual(S32_MENTOR);expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(S32_PATHS.detail);
  expect(S32_MENTOR.rating_aggregate.rating_count).toBe(Object.values(S32_MENTOR.rating_aggregate.distribution).reduce((a,b)=>a+b,0));
  for(const state of S32_STATES.filter(s=>!['loading','profile-error','missing','availability-error'].includes(s))){
   const wire=s32AvailabilityResponse(state),q=expectedS32Requests(state).at(-1).search;
   fetch.mockResolvedValue(new Response(JSON.stringify(wire)));expect(await readMentorAvailability(S32_ID,new URLSearchParams(q))).toEqual(wire);
   expect(wire.limit).toBe(50);expect(wire.offset).toBe(0);
   for(const slot of wire.slots){
    expect(slot.status).toBe('available');expect(slot.tutor_id).toBe(S32_ID);expect(slot.price_paise).toBe(S32_MENTOR.session_price_paise);
    expect(Date.parse(slot.start_local)).toBe(Date.parse(slot.start_utc));expect(Date.parse(slot.end_local)).toBe(Date.parse(slot.end_utc));
    expect(Date.parse(slot.end_utc)-Date.parse(slot.start_utc)).toBe(slot.duration_minutes*60_000);
    if(wire.window.from_utc)expect(Date.parse(slot.start_utc)).toBeGreaterThanOrEqual(Date.parse(wire.window.from_utc));
   }
  }
 });
 it('preserves UTC instants across a real timezone change and correctly resolves date/DST windows',()=>{
  const normal=s32AvailabilityResponse('complete'),zone=s32AvailabilityResponse('zone-changed');
  expect(normal.slots.map(s=>s.start_utc)).toEqual(zone.slots.map(s=>s.start_utc));expect(normal.slots[0].start_local).not.toBe(zone.slots[0].start_local);
  const ambiguous=s32AvailabilityResponse('dst-ambiguous'),gap=s32AvailabilityResponse('dst-gap');
  expect(ambiguous.local_resolution.from_local).toEqual({requested_local:'2027-10-31T01:30:00',resolved_local:'2027-10-31T01:30:00+01:00',instant_utc:'2027-10-31T00:30:00+00:00',classification:'ambiguous',dst_adjusted:true});
  expect(gap.local_resolution.from_local).toEqual({requested_local:'2027-03-28T01:30:00',resolved_local:'2027-03-28T02:30:00+01:00',instant_utc:'2027-03-28T01:30:00+00:00',classification:'nonexistent',dst_adjusted:true});
  expect(ambiguous.slots.slice(0,2).map(s=>s.start_local)).toEqual(['2027-10-31T01:30:00+01:00','2027-10-31T01:30:00+00:00']);
  expect(s32AvailabilityResponse('no-slots').slots).toEqual([]);
  const day=s32AvailabilityResponse('day-empty');expect(day.slots).toEqual([]);expect(day.window).toEqual({from_utc:'2027-08-17T18:30:00+00:00',to_utc:'2027-08-18T18:29:59.999999+00:00'});
  expect(day.local_resolution.from_local.classification).toBe('unique');expect(day.local_resolution.from_local.dst_adjusted).toBe(false);
  expect(()=>s32AvailabilityResponse('invented')).toThrow('S32_FIXTURE_SCOPE');
 });
 it('requires the exact session/profile/availability sequence, real timezone/day changes and zero booking writes',()=>{
  for(const state of S32_STATES){
   const requests=expectedS32Requests(state);expect(verifyS32Requests(state,requests)).toBe(true);
   expect(requests[0]).toEqual({method:'GET',path:S32_PATHS.session,search:'',body:null});
   expect(requests.every(r=>r.method==='GET'&&r.body===null)).toBe(true);
   expect(requests.length).toBe(['loading','missing','profile-error'].includes(state)?2:['zone-changed','day-empty'].includes(state)?4:3);
   expect(s32Route(state)).toMatch(/^\/s-32\?tutor=/);
   expect(new URL(s32Route(state),origin).searchParams.get('tz')).toBe(state==='zone-changed'||state.startsWith('dst-')?'Europe/London':'Asia/Kolkata');
   for(const bad of [requests.slice(1),[...requests,requests[0]],requests.map((r,i)=>i?r:{...r,method:'POST'}),requests.map((r,i)=>i?r:{...r,search:'?invented=1'}),requests.map((r,i)=>i?r:{...r,body:{}})])expect(verifyS32Requests(state,bad)).toBe(false);
  }
  expect(verifyS32Requests('invented',[])).toBe(false);
  expect(new URLSearchParams(expectedS32Requests('zone-changed').at(-1).search).get('timezone')).toBe('Europe/London');
  expect(new URLSearchParams(expectedS32Requests('day-empty').at(-1).search).get('date')).toBe('2027-08-18');
 });
 it('requires real 404/500 console and response evidence at exactly the expected endpoint',()=>{
  for(const [state,status,reason]of [['missing',404,'Not Found'],['profile-error',500,'Internal Server Error'],['availability-error',500,'Internal Server Error']]){
   const q=expectedS32Requests(state).at(-1),url=origin+q.path+q.search,http=[{method:'GET',url,status}],messages=[{url,text:`Failed to load resource: the server responded with a status of ${status} (${reason})`}];
   expect(classifyS32Errors(state,origin,messages,http,[],http).errors).toEqual([]);
   for(const args of [[[],http,[],http],[messages,[],[],http],[messages,http,[],[]],[[...messages,...messages],http,[],http],[messages,http,[{url,errorText:'net::ERR_FAILED'}],http],[messages,[{...http[0],status:200}],[],http],[messages,[{...http[0],method:'POST'}],[],http],[[{...messages[0],url:origin+'/other'}],http,[],http]])expect(classifyS32Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
  }
 });
 it('rejects unrelated errors, network failures and false declarations',()=>{
  for(const state of S32_STATES.filter(s=>!['missing','profile-error','availability-error'].includes(s))){
   expect(classifyS32Errors(state,origin,[],[],[],[]).errors).toEqual([]);
   expect(classifyS32Errors(state,origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
   expect(classifyS32Errors(state,origin,[],[{method:'GET',url:origin,status:500}],[],[]).errors).toContain('HTTP_RESPONSE_ERROR');
   expect(classifyS32Errors(state,origin,[],[],[{url:origin}],[]).errors).toContain('NETWORK_ERROR');
   expect(classifyS32Errors(state,origin,[],[],[],[{url:origin}]).errors).toContain('UNEXPECTED_HTTP_DECLARATION');
  }
 });
});
