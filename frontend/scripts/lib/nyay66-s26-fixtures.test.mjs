import {describe,it,expect,vi,afterEach} from 'vitest';
import {S26_LISTINGS,classifyS26Errors,verifyS26Requests} from './nyay66-s26-fixtures.mjs';
import {readBrowseSaved} from '../../src/features/student/internships/s20Api';
const origin='http://127.0.0.1:4321',saved='/api/v1/student/internships/saved',session='/api/v1/auth/student/session';
const base=[{method:'GET',path:session,search:''},{method:'GET',path:saved,search:''}];
afterEach(()=>vi.unstubAllGlobals());
describe('S-26 synthetic saved-query contracts',()=>{
  it('uses the real saved-list response shape and adapter',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({items:S26_LISTINGS}))));
    expect((await readBrowseSaved()).map(i=>i.id)).toEqual(['summer-associate','policy-research','arbitration-intern']);
  });
  it('requires exactly session authority then the saved GET, never a mutation or invented query',()=>{
    for(const state of ['empty','loading','error','nonempty'])expect(verifyS26Requests(state,base)).toBe(true);
    for(const broken of [base.slice(1),[...base,base[0]],[...base].reverse(),base.map((r,i)=>i?r:{...r,search:'?invented=1'}),base.map((r,i)=>i?r:{...r,method:'POST'})])
      expect(verifyS26Requests('empty',broken)).toBe(false);
    expect(verifyS26Requests('invented',base)).toBe(false);
  });
  it('requires exactly the genuine saved-query HTTP 500, not a synthetic success envelope',()=>{
    const responses=[{method:'GET',url:origin+saved,status:500}],messages=[{url:origin+saved,text:'Failed to load resource: the server responded with a status of 500 (Internal Server Error)'}];
    expect(classifyS26Errors('error',origin,messages,responses,[],responses).errors).toEqual([]);
    for(const args of [[[],responses,[],responses],[messages,[],[],responses],[messages,responses,[],[]],[[...messages,...messages],responses,[],responses],[messages,responses,[{url:origin,errorText:'net::ERR_FAILED'}],responses],[messages,[{...responses[0],status:200}],[],responses],[messages,[{...responses[0],method:'DELETE'}],[],responses]])
      expect(classifyS26Errors('error',origin,...args).errors.length).toBeGreaterThan(0);
  });
  it('rejects unexpected console, network, HTTP and declaration errors on positive states',()=>{
    expect(classifyS26Errors('nonempty',origin,[],[],[],[]).errors).toEqual([]);
    expect(classifyS26Errors('empty',origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
    expect(classifyS26Errors('loading',origin,[],[{url:origin,status:500}],[],[]).errors).toContain('HTTP_RESPONSE_ERROR');
    expect(classifyS26Errors('nonempty',origin,[],[],[{url:origin}],[]).errors).toContain('NETWORK_ERROR');
    expect(classifyS26Errors('empty',origin,[],[],[],[{url:origin}]).errors).toContain('UNEXPECTED_HTTP_DECLARATION');
    expect(classifyS26Errors('invented',origin,[],[],[],[]).errors).toContain('S26_FIXTURE_SCOPE');
  });
});
