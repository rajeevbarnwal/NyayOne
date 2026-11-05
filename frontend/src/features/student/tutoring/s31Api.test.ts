import { afterEach, describe, expect, it, vi } from 'vitest';
import { readMentors, mentorQuery } from './s31Api';
const item={id:'t/a',display_name:'Synthetic Mentor',headline:null,experience_years:0,rating_avg:null,rating_count:0,verified_identity:true,verified_credentials:false,status:'active',session_price_paise:89950,currency:'INR'};
const page={items:[item],total:25,limit:10,offset:0,has_more:true,sort:'rating_desc',allowed_sorts:['rating_desc','name_asc']};
const reply=(v:unknown,status=200)=>new Response(JSON.stringify(v),{status});
afterEach(()=>vi.unstubAllGlobals());
describe('S-31 server authority',()=>{
 it('sends only supported search parameters, retaining invalid values for server validation',()=>{
  const q=mentorQuery(new URLSearchParams('q=Moot&subject=Law&level=Advanced&min_rating=9&min_experience_years=3&verified_only=1&sort=unsupported&offset=-1&limit=3&price=1&slot=tomorrow'));
  expect(Object.fromEntries(q)).toEqual({q:'Moot',subject:'Law',level:'Advanced',min_rating:'9',min_experience_years:'3',verified_only:'true',sort:'unsupported',limit:'3',offset:'-1'});
  expect(Object.fromEntries(mentorQuery(new URLSearchParams()))).toEqual({sort:'rating_desc',limit:'10',offset:'0'});
 });
 it('reads exact server pagination, independent verification and integer paise with abort support',async()=>{
  const fetch=vi.fn().mockResolvedValue(reply(page));vi.stubGlobal('fetch',fetch);const signal=new AbortController().signal;
  expect(await readMentors(new URLSearchParams(),signal)).toEqual(page);
  expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/api/v1/tutors');expect(fetch.mock.calls[0][1]).toMatchObject({method:'GET',signal});
 });
 it.each([{}, {...page,items:null},{...page,items:[item,item]},{...page,total:-1},{...page,limit:0},{...page,has_more:'true'},{...page,allowed_sorts:[]},{...page,items:[{...item,session_price_paise:undefined}]},{...page,items:[{...item,verified_credentials:'false'}]},{...page,items:[{...item,rating_avg:'NaN'}]}])('rejects malformed success without inventing an empty list or price: %j',async body=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply(body)));await expect(readMentors(new URLSearchParams())).rejects.toMatchObject({status:200,code:'invalid_response'});
 });
 it.each([401,403,422,429,503])('preserves real status %s, machine code and retry hint',async status=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply({detail:{code:'server_code',retry_after_seconds:3}},status)));
  await expect(readMentors(new URLSearchParams())).rejects.toMatchObject({status,code:'server_code',retryAfterSeconds:3});
 });
});
