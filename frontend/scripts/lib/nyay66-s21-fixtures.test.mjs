import {describe,it,expect,vi,afterEach} from 'vitest';
import {S21_LISTING,classifyS21Errors,verifyS21Requests} from './nyay66-s21-fixtures.mjs';
import {readInternshipDetail} from '../../src/features/student/internships/s21Api';
import {readBrowseSaved} from '../../src/features/student/internships/s20Api';
const origin='http://127.0.0.1:4321',detail='/api/v1/internships/arbitration-intern',saved='/api/v1/student/internships/saved',save='/api/v1/student/internships/arbitration-intern/saved',session='/api/v1/auth/student/session';
afterEach(()=>vi.unstubAllGlobals());
describe('S-21 synthetic API contract',()=>{
  it('uses a complete backend-shaped listing accepted by both real adapters',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response(JSON.stringify(S21_LISTING))).mockResolvedValueOnce(new Response(JSON.stringify({items:[S21_LISTING]}))));
    expect((await readInternshipDetail(S21_LISTING.id)).id).toBe(S21_LISTING.id);
    expect((await readBrowseSaved())[0].id).toBe(S21_LISTING.id);
  });
  const calls=(items)=>items.map(([method,path])=>({method,path,search:''}));
  it('rejects extra requests, query parameters, wrong methods and missing mutation proof',()=>{
    const base=calls([['GET',session],['GET',detail],['GET',saved]]);
    expect(verifyS21Requests('complete',base)).toBe(true);
    expect(verifyS21Requests('save-pending',[...base,...calls([['PUT',save]])])).toBe(true);
    for(const broken of [base.slice(1),[...base,base[0]],base.map((r,i)=>i?r:{...r,search:'?invented=true'}),base.map((r,i)=>i?r:{...r,method:'POST'})])expect(verifyS21Requests('complete',broken)).toBe(false);
    expect(verifyS21Requests('save-pending',base)).toBe(false);expect(verifyS21Requests('invented',base)).toBe(false);
  });
  for(const [state,method,path,status,reason] of [['save-failed','PUT',save,503,'Service Unavailable'],['session','PUT',save,401,'Unauthorized'],['missing','GET',detail,404,'Not Found'],['error','GET',detail,500,'Internal Server Error']])it(`only classifies the exact ${state} failure as expected`,()=>{
    const responses=[{method,url:origin+path,status}],messages=[{url:origin+path,text:`Failed to load resource: the server responded with a status of ${status} (${reason})`}];
    expect(classifyS21Errors(state,origin,messages,responses,[],responses).errors).toEqual([]);
    for(const args of [[[],responses,[],responses],[messages,[],[],responses],[messages,responses,[],[]],[[...messages,...messages],responses,[],responses],[messages,responses,[{url:origin,errorText:'net::ERR_FAILED'}],responses],[messages,[{...responses[0],status:400}],[],responses]])expect(classifyS21Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
  });
  it('rejects unexpected errors on positive states',()=>{
    expect(classifyS21Errors('complete',origin,[],[],[],[]).errors).toEqual([]);
    expect(classifyS21Errors('complete',origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
    expect(classifyS21Errors('complete',origin,[],[],[{url:origin}],[]).errors).toContain('NETWORK_ERROR');
  });
});
