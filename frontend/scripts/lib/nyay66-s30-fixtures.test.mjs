import {describe,it,expect,vi,afterEach} from 'vitest';
import {S30_SCHOOLS,S30_IDS,S30_PATHS,s30Response,expectedS30Requests,verifyS30Requests,classifyS30Errors} from './nyay66-s30-fixtures.mjs';
import {S30_STATES} from './nyay66-s30-reference.mjs';
import {readPrivateSchools} from '../../src/features/student/schools/s30Api';
const origin='http://127.0.0.1:4321';
afterEach(()=>vi.unstubAllGlobals());
describe('S-30 backend-grounded synthetic private-list fixtures',()=>{
  it('uses UUID identities and production list adapters with independent membership and consent',async()=>{
    expect(Object.isFrozen(S30_SCHOOLS)).toBe(true);
    for(const id of S30_IDS)expect(id).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    for(const state of S30_STATES)for(const kind of ['saved','followed']){
      const wire=s30Response(state,kind),fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(wire)));vi.stubGlobal('fetch',fetch);
      const result=await readPrivateSchools(kind);
      expect(result.map(s=>s.id)).toEqual(wire.items.map(s=>s.id));
      expect(result.map(s=>s.notifyOptIn)).toEqual(wire.items.map(s=>kind==='saved'?null:s.notify_opt_in));
      expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(S30_PATHS[kind]);
      expect(fetch.mock.calls[0][1].method).toBe('GET');
    }
    expect(s30Response('both','saved').items.map(s=>s.id)).not.toEqual(s30Response('both','followed').items.map(s=>s.id));
    expect(s30Response('following-tab','followed').items.map(s=>s.notify_opt_in)).toEqual([true,false]);
    expect(s30Response('saved-empty','saved').items).toEqual([]);
    expect(s30Response('saved-empty','followed').items).toHaveLength(2);
    expect(s30Response('followed-empty','followed').items).toEqual([]);
    expect(s30Response('followed-empty','saved').items).toHaveLength(2);
    expect(()=>s30Response('invented','saved')).toThrow('S30_FIXTURE_SCOPE');
    expect(()=>s30Response('both','invented')).toThrow('S30_LIST_KIND');
  });
  it('requires one session read, both independent GETs, then only the declared DELETE',()=>{
    for(const state of S30_STATES){
      const requests=expectedS30Requests(state);
      expect(verifyS30Requests(state,requests)).toBe(true);
      expect(requests.slice(0,3)).toEqual([
        {method:'GET',path:'/api/v1/auth/student/session',search:'',body:null},
        {method:'GET',path:S30_PATHS.saved,search:'',body:null},
        {method:'GET',path:S30_PATHS.followed,search:'',body:null},
      ]);
      expect(requests.slice(3)).toEqual(state.startsWith('item-')?[{method:'DELETE',path:S30_PATHS.remove,search:'',body:null}]:[]);
      for(const bad of [requests.slice(1),[...requests,requests[0]],requests.toReversed(),requests.map((r,i)=>i?r:{...r,method:'POST'}),requests.map((r,i)=>i?r:{...r,search:'?state=both'}),requests.map((r,i)=>i?r:{...r,body:{}})])expect(verifyS30Requests(state,bad)).toBe(false);
    }
    expect(verifyS30Requests('invented',[])).toBe(false);
  });
  it('requires actual 500 HTTP, console and declaration evidence for only the exact failed endpoint',()=>{
    for(const [state,method,path] of [['error','GET',S30_PATHS.saved],['item-error','DELETE',S30_PATHS.remove]]){
      const url=origin+path,http=[{method,url,status:500}],messages=[{url,text:'Failed to load resource: the server responded with a status of 500 (Internal Server Error)'}];
      expect(classifyS30Errors(state,origin,messages,http,[],http).errors).toEqual([]);
      for(const args of [[[],http,[],http],[messages,[],[],http],[messages,http,[],[]],[[...messages,...messages],http,[],http],
        [messages,http,[{url,errorText:'net::ERR_FAILED'}],http],[messages,[{...http[0],status:200}],[],http],
        [messages,[{...http[0],method:'POST'}],[],http],[[{...messages[0],url:origin+'/other'}],http,[],http]])expect(classifyS30Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
    }
  });
  it('never exempts unrelated browser errors, network failures or false HTTP declarations',()=>{
    for(const state of S30_STATES.filter(s=>!['error','item-error'].includes(s))){
      expect(classifyS30Errors(state,origin,[],[],[],[]).errors).toEqual([]);
      expect(classifyS30Errors(state,origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
      expect(classifyS30Errors(state,origin,[],[{method:'GET',url:origin,status:500}],[],[]).errors).toContain('HTTP_RESPONSE_ERROR');
      expect(classifyS30Errors(state,origin,[],[],[{url:origin}],[]).errors).toContain('NETWORK_ERROR');
      expect(classifyS30Errors(state,origin,[],[],[],[{url:origin}]).errors).toContain('UNEXPECTED_HTTP_DECLARATION');
    }
    expect(classifyS30Errors('invented',origin,[],[],[],[]).errors).toContain('S30_FIXTURE_SCOPE');
  });
});
