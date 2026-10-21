import {describe,it,expect,vi,afterEach} from 'vitest';
import {S25_LISTINGS,classifyS25Errors,verifyS25Requests} from './nyay66-s25-fixtures.mjs';
import {readBrowseSaved} from '../../src/features/student/internships/s20Api';
const origin='http://127.0.0.1:4321',saved='/api/v1/student/internships/saved',remove='/api/v1/student/internships/summer-associate/saved',session='/api/v1/auth/student/session';
const calls=items=>items.map(([method,path])=>({method,path,search:''}));
afterEach(()=>vi.unstubAllGlobals());
describe('S-25 synthetic backend contracts',()=>{
  it('uses the real saved-list response shape and adapter, not injected UI state',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({items:S25_LISTINGS}))));
    expect((await readBrowseSaved()).map(i=>i.id)).toEqual(['summer-associate','policy-research','arbitration-intern']);
  });
  it('requires the exact GET/DELETE sequence, including failure revalidation',()=>{
    const base=calls([['GET',session],['GET',saved]]),pending=[...base,...calls([['DELETE',remove]])],failed=[...pending,...calls([['GET',saved]])];
    for(const state of ['loading','list','empty','error'])expect(verifyS25Requests(state,base)).toBe(true);
    expect(verifyS25Requests('remove-pending',pending)).toBe(true);expect(verifyS25Requests('remove-failed',failed)).toBe(true);
    for(const broken of [base.slice(1),[...base,base[0]],[...base].reverse(),base.map((r,i)=>i?r:{...r,search:'?invented=1'}),base.map((r,i)=>i?r:{...r,method:'POST'})])expect(verifyS25Requests('list',broken)).toBe(false);
    expect(verifyS25Requests('remove-pending',base)).toBe(false);expect(verifyS25Requests('remove-failed',pending)).toBe(false);expect(verifyS25Requests('remove-failed',[...failed,failed[2]])).toBe(false);expect(verifyS25Requests('invented',base)).toBe(false);
  });
  for(const [state,method,path,status,reason] of [['remove-failed','DELETE',remove,503,'Service Unavailable'],['error','GET',saved,500,'Internal Server Error']])it(`requires exactly the genuine ${state} HTTP failure`,()=>{
    const responses=[{method,url:origin+path,status}],messages=[{url:origin+path,text:`Failed to load resource: the server responded with a status of ${status} (${reason})`}];
    expect(classifyS25Errors(state,origin,messages,responses,[],responses).errors).toEqual([]);
    for(const args of [[[],responses,[],responses],[messages,[],[],responses],[messages,responses,[],[]],[[...messages,...messages],responses,[],responses],[messages,responses,[{url:origin,errorText:'net::ERR_FAILED'}],responses],[messages,[{...responses[0],status:400}],[],responses],[messages,[{...responses[0],method:'PUT'}],[],responses]])expect(classifyS25Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
  });
  it('rejects unexpected console, network, HTTP and declaration errors on positive states',()=>{
    expect(classifyS25Errors('list',origin,[],[],[],[]).errors).toEqual([]);
    expect(classifyS25Errors('list',origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
    expect(classifyS25Errors('list',origin,[],[{url:origin,status:500}],[],[]).errors).toContain('HTTP_RESPONSE_ERROR');
    expect(classifyS25Errors('list',origin,[],[],[{url:origin}],[]).errors).toContain('NETWORK_ERROR');
    expect(classifyS25Errors('list',origin,[],[],[],[{url:origin}]).errors).toContain('UNEXPECTED_HTTP_DECLARATION');
    expect(classifyS25Errors('invented',origin,[],[],[],[]).errors).toContain('S25_FIXTURE_SCOPE');
  });
});
