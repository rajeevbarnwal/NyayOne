import {describe,it,expect,vi,afterEach} from 'vitest';
import {S31_TUTORS,S31_PATHS,s31Response,expectedS31Requests,verifyS31Requests,classifyS31Errors} from './nyay66-s31-fixtures.mjs';
import {S31_STATES} from './nyay66-s31-reference.mjs';
import {readMentors} from '../../src/features/student/tutoring/s31Api';
const origin='http://127.0.0.1:4321';
afterEach(()=>vi.unstubAllGlobals());
describe('S-31 backend-grounded synthetic discovery fixtures',()=>{
  it('uses production adapters, server pagination/sort, independent claims and paise prices',async()=>{
    expect(Object.isFrozen(S31_TUTORS)).toBe(true);
    for(const t of S31_TUTORS)expect(t.id).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    for(const state of ['results','filters-open','no-matches','page-2']){
      const wire=s31Response(state),fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(wire)));vi.stubGlobal('fetch',fetch);
      const query=expectedS31Requests(state).at(-1).search;
      expect(await readMentors(new URLSearchParams(query))).toEqual(wire);
      expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(S31_PATHS.tutors);
      expect(new URL(fetch.mock.calls[0][0]).search).toBe(query);expect(fetch.mock.calls[0][1].method).toBe('GET');
    }
    const first=s31Response('results'),second=s31Response('page-2');
    expect(first.total).toBe(5);expect(first.limit).toBe(3);expect(first.offset).toBe(0);expect(first.has_more).toBe(true);
    expect(second.offset).toBe(3);expect(second.items).toHaveLength(2);expect(second.has_more).toBe(false);
    expect(new Set([...first.items,...second.items].map(t=>t.id)).size).toBe(5);
    const ratings=[...first.items,...second.items].map(t=>t.rating_avg===null?-1:Number(t.rating_avg));expect(ratings).toEqual([...ratings].sort((a,b)=>b-a));
    expect(s31Response('no-matches').total).toBe(0);expect(s31Response('no-matches').items).toEqual([]);
    expect(s31Response('filters-open').items).toHaveLength(2);
    expect(first.items.some(t=>t.verified_identity&&!t.verified_credentials)).toBe(true);
    expect(S31_TUTORS.some(t=>t.rating_avg===null&&t.rating_count===0)).toBe(true);
    expect(()=>s31Response('invented')).toThrow('S31_FIXTURE_SCOPE');
  });
  it('requires the exact authenticated query sequence, actual pagination, and no offline API read',()=>{
    for(const state of S31_STATES){
      const requests=expectedS31Requests(state);expect(verifyS31Requests(state,requests)).toBe(true);
      expect(requests[0]).toEqual({method:'GET',path:S31_PATHS.session,search:'',body:null});
      expect(requests.length).toBe(state==='offline'?1:state==='page-2'?3:2);
      if(state==='page-2')expect(requests.slice(1).map(r=>new URLSearchParams(r.search).get('offset'))).toEqual(['0','3']);
      for(const bad of [requests.slice(1),[...requests,requests[0]],requests.map((r,i)=>i?r:{...r,method:'POST'}),requests.map((r,i)=>i?r:{...r,search:'?unexpected=1'}),requests.map((r,i)=>i?r:{...r,body:{}})])expect(verifyS31Requests(state,bad)).toBe(false);
    }
    expect(verifyS31Requests('invented',[])).toBe(false);
  });
  it('requires real HTTP 429/500 console and response evidence at the exact tutor endpoint',()=>{
    for(const [state,status,reason] of [['rate-limited',429,'Too Many Requests'],['error',500,'Internal Server Error']]){
      const url=origin+S31_PATHS.tutors+expectedS31Requests(state).at(-1).search;
      const http=[{method:'GET',url,status}],messages=[{url,text:`Failed to load resource: the server responded with a status of ${status} (${reason})`}];
      expect(classifyS31Errors(state,origin,messages,http,[],http).errors).toEqual([]);
      for(const args of [[[],http,[],http],[messages,[],[],http],[messages,http,[],[]],[[...messages,...messages],http,[],http],[messages,http,[{url,errorText:'net::ERR_FAILED'}],http],[messages,[{...http[0],status:200}],[],http],[messages,[{...http[0],method:'POST'}],[],http],[[{...messages[0],url:origin+'/other'}],http,[],http]])expect(classifyS31Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
    }
  });
  it('does not exempt unrelated errors, network failures or false declarations (including offline)',()=>{
    for(const state of S31_STATES.filter(s=>!['error','rate-limited'].includes(s))){
      expect(classifyS31Errors(state,origin,[],[],[],[]).errors).toEqual([]);
      expect(classifyS31Errors(state,origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
      expect(classifyS31Errors(state,origin,[],[{method:'GET',url:origin,status:500}],[],[]).errors).toContain('HTTP_RESPONSE_ERROR');
      expect(classifyS31Errors(state,origin,[],[],[{url:origin}],[]).errors).toContain('NETWORK_ERROR');
      expect(classifyS31Errors(state,origin,[],[],[],[{url:origin}]).errors).toContain('UNEXPECTED_HTTP_DECLARATION');
    }
    expect(classifyS31Errors('invented',origin,[],[],[],[]).errors).toContain('S31_FIXTURE_SCOPE');
  });
});
