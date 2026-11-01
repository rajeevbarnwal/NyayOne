import {describe,it,expect,vi,afterEach} from 'vitest';
import {S29_SCHOOLS,S29_IDS,S29_COMPARE_PATH,s29Route,s29Ids,s29Response,expectedS29Requests,verifyS29Requests,classifyS29Errors} from './nyay66-s29-fixtures.mjs';
import {S29_STATES} from './nyay66-s29-reference.mjs';
import {readComparison,comparisonValue} from '../../src/features/student/schools/s29Api';
const origin='http://127.0.0.1:4321';
afterEach(()=>vi.unstubAllGlobals());
describe('S-29 backend-grounded synthetic comparison fixtures',()=>{
  it('uses genuine UUIDs and the production POST adapter with ordered detail projections',async()=>{
    expect(Object.isFrozen(S29_SCHOOLS)).toBe(true);
    for(const id of S29_IDS)expect(id).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    for(const state of ['complete','three','incomplete']){
      const wire=s29Response(state),fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(wire)));vi.stubGlobal('fetch',fetch);
      const ids=s29Ids(state),result=await readComparison(ids);
      expect(result.items.map(s=>s.id)).toEqual(ids);expect(result.compareMax).toBe(4);
      expect(result.comparisonId).toBe(wire.comparison_id);
      expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/api/v1/law-schools/compare');
      expect(fetch.mock.calls[0][1].method).toBe('POST');expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({school_ids:ids});
      if(state==='incomplete'){
        expect(comparisonValue(result.items[1],'fees')).toBe('Not provided');
        expect(comparisonValue(result.items[1],'nirf_rank')).toBe('Not provided');
        expect(result.items[1].facts).toEqual([]);
      }
    }
    expect(()=>s29Response('invented')).toThrow('S29_FIXTURE_SCOPE');
  });
  it('requires exact session/POST sequence, IDs, order, body and query; local too-few must send no POST',()=>{
    for(const state of S29_STATES){
      const requests=expectedS29Requests(state),ids=s29Ids(state);
      expect(verifyS29Requests(state,requests)).toBe(true);
      expect(new URL(s29Route(state),origin).searchParams.get('ids')).toBe(ids.join(','));
      expect(requests[0]).toEqual({method:'GET',path:'/api/v1/auth/student/session',search:'',body:null});
      expect(requests.slice(1)).toEqual(state==='too-few'?[]:[{method:'POST',path:S29_COMPARE_PATH,search:'',body:{school_ids:ids}}]);
      for(const bad of [requests.slice(1),[...requests,requests[0]],requests.map((r,i)=>i?r:{...r,method:'POST'}),requests.map((r,i)=>i?r:{...r,search:'?state=complete'}),requests.map((r,i)=>i?r:{...r,body:{}})])expect(verifyS29Requests(state,bad)).toBe(false);
    }
    const request=expectedS29Requests('complete');request[1].body.school_ids.reverse();expect(verifyS29Requests('complete',request)).toBe(false);
    expect(s29Ids('three')).toHaveLength(3);expect(s29Ids('too-few')).toHaveLength(1);
    expect(verifyS29Requests('invented',[])).toBe(false);
  });
  it('requires a genuine HTTP 500 plus matching browser response and console evidence for error',()=>{
    const url=origin+S29_COMPARE_PATH,http=[{method:'POST',url,status:500}];
    const messages=[{url,text:'Failed to load resource: the server responded with a status of 500 (Internal Server Error)'}];
    expect(classifyS29Errors('error',origin,messages,http,[],http).errors).toEqual([]);
    for(const args of [[[],http,[],http],[messages,[],[],http],[messages,http,[],[]],[[...messages,...messages],http,[],http],
      [messages,http,[{url,errorText:'net::ERR_FAILED'}],http],[messages,[{...http[0],status:200}],[],http],
      [messages,[{...http[0],method:'GET'}],[],http],[[{...messages[0],url:origin+'/other'}],http,[],http]])expect(classifyS29Errors('error',origin,...args).errors.length).toBeGreaterThan(0);
  });
  it('never exempts unrelated browser failures, including in the client-only too-few state',()=>{
    for(const state of ['loading','complete','three','incomplete','too-few']){
      expect(classifyS29Errors(state,origin,[],[],[],[]).errors).toEqual([]);
      expect(classifyS29Errors(state,origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
      expect(classifyS29Errors(state,origin,[],[{method:'POST',url:origin,status:500}],[],[]).errors).toContain('HTTP_RESPONSE_ERROR');
      expect(classifyS29Errors(state,origin,[],[],[{url:origin}],[]).errors).toContain('NETWORK_ERROR');
      expect(classifyS29Errors(state,origin,[],[],[],[{url:origin}]).errors).toContain('UNEXPECTED_HTTP_DECLARATION');
    }
    expect(classifyS29Errors('invented',origin,[],[],[],[]).errors).toContain('S29_FIXTURE_SCOPE');
  });
});
