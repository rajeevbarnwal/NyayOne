import {describe,it,expect,vi,afterEach} from 'vitest';
import {S28_SCHOOL,S28_ID,S28_DETAIL_PATH,S28_FOLLOW_PATH,S28_SAVE_PATH,S28_ROUTE,expectedS28Requests,verifyS28Requests,classifyS28Errors,s28DetailResponse} from './nyay66-s28-fixtures.mjs';
import {S28_STATES} from './nyay66-s28-reference.mjs';
import {readSchoolDetail,writeSchoolFollow,writeSchoolSaved} from '../../src/features/student/schools/s28Api';
const origin='http://127.0.0.1:4321';
afterEach(()=>vi.unstubAllGlobals());
describe('S-28 backend-grounded synthetic fixture contracts',()=>{
  it('uses a UUID, the real detail projection and nullable notification knowledge through the product adapter',async()=>{
    expect(S28_ID).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    expect(S28_ROUTE).toBe(`/s-28?id=${S28_ID}`);expect(S28_DETAIL_PATH).toBe(`/api/v1/law-schools/${S28_ID}`);
    for(const state of ['complete','following','save-pending','follow-error']){
      const wire=s28DetailResponse(state);expect(wire).not.toHaveProperty('notify_opt_in');
      const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify(wire)));vi.stubGlobal('fetch',fetch);
      const result=await readSchoolDetail(S28_ID);
      expect(result).toMatchObject({id:S28_ID,name:'Sabarmati Law College',saved:false,followed:state!=='following',notifyOptIn:null,feesMin:410000,feesMax:455000,nirfRank:null});
      expect(result.facts.map(f=>f.key)).toEqual(['established','location','intake','hostel']);
      expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(S28_DETAIL_PATH);
    }
    expect(Object.isFrozen(S28_SCHOOL)).toBe(true);
    expect(()=>s28DetailResponse('invented')).toThrow('S28_FIXTURE_SCOPE');
  });
  it('requires exact session/detail requests and only the state-specific real mutation, including its body',()=>{
    for(const state of S28_STATES){
      const req=expectedS28Requests(state);expect(verifyS28Requests(state,req)).toBe(true);
      expect(req.slice(0,2)).toEqual([{method:'GET',path:'/api/v1/auth/student/session',search:'',body:null},{method:'GET',path:S28_DETAIL_PATH,search:'',body:null}]);
      const extra=state==='following'?{method:'PUT',path:S28_FOLLOW_PATH,search:'',body:{notify_opt_in:false}}
        :state==='save-pending'?{method:'PUT',path:S28_SAVE_PATH,search:'',body:null}
        :state==='follow-error'?{method:'DELETE',path:S28_FOLLOW_PATH,search:'',body:null}:null;
      expect(req.slice(2)).toEqual(extra?[extra]:[]);
      for(const changed of [req.slice(1),[...req,req[0]],req.map((r,i)=>i?r:{...r,method:'POST'}),
        req.map((r,i)=>i?r:{...r,search:'?invented=true'}),req.map((r,i)=>i?r:{...r,body:{}}),
        [...req,{method:'GET',path:'/api/v1/student/law-schools/followed',search:'',body:null}]])expect(verifyS28Requests(state,changed)).toBe(false);
    }
    const req=expectedS28Requests('following');req[2].body.notify_opt_in=true;
    expect(verifyS28Requests('following',req)).toBe(false);
    expect(verifyS28Requests('following',expectedS28Requests('follow-error'))).toBe(false);
    expect(verifyS28Requests('invented',[])).toBe(false);
  });
  it('exercises the supported PUT acknowledgment with no implicit notification opt-in',async()=>{
    const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({followed:true,notify_opt_in:false})));vi.stubGlobal('fetch',fetch);
    await expect(writeSchoolFollow(S28_ID,true,false)).resolves.toEqual({followed:true,notifyOptIn:false});
    expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(S28_FOLLOW_PATH);
    expect(fetch.mock.calls[0][1].method).toBe('PUT');expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({notify_opt_in:false});
    fetch.mockResolvedValue(new Response(JSON.stringify({saved:true})));
    await expect(writeSchoolSaved(S28_ID,true)).resolves.toEqual({saved:true});
    expect(new URL(fetch.mock.calls[1][0]).pathname).toBe(S28_SAVE_PATH);
  });
  it.each([['missing','GET',404,'Not Found'],['error','GET',500,'Internal Server Error'],['follow-error','DELETE',500,'Internal Server Error']])('requires genuine HTTP/browser evidence for %s', (state,method,status,reason)=>{
    const url=origin+(state==='follow-error'?S28_FOLLOW_PATH:S28_DETAIL_PATH),http=[{method,url,status}];
    const messages=[{url,text:`Failed to load resource: the server responded with a status of ${status} (${reason})`}];
    expect(classifyS28Errors(state,origin,messages,http,[],http).errors).toEqual([]);
    for(const args of [[[],http,[],http],[messages,[],[],http],[messages,http,[],[]],
      [[...messages,...messages],http,[],http],[messages,http,[{method,url,errorText:'net::ERR_FAILED'}],http],
      [messages,[{...http[0],status:200}],[],http],[messages,[{...http[0],method:'POST'}],[],http],
      [[{...messages[0],url:origin+'/other'}],http,[],http]])expect(classifyS28Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
  });
  it('does not suppress unrelated console, HTTP or network errors in any successful or pending state',()=>{
    for(const state of ['loading','complete','following','save-pending']){
      expect(classifyS28Errors(state,origin,[],[],[],[]).errors).toEqual([]);
      expect(classifyS28Errors(state,origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
      expect(classifyS28Errors(state,origin,[],[{method:'GET',url:origin,status:500}],[],[]).errors).toContain('HTTP_RESPONSE_ERROR');
      expect(classifyS28Errors(state,origin,[],[],[{url:origin}],[]).errors).toContain('NETWORK_ERROR');
      expect(classifyS28Errors(state,origin,[],[],[],[{url:origin}]).errors).toContain('UNEXPECTED_HTTP_DECLARATION');
    }
    expect(classifyS28Errors('invented',origin,[],[],[],[]).errors).toContain('S28_FIXTURE_SCOPE');
  });
});
