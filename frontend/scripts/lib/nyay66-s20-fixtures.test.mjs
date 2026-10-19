import {describe,it,expect,afterEach,vi} from 'vitest';
import {parseS20CatalogueQuery,classifyS20Errors,S20_LISTINGS,S20_QUERY} from './nyay66-s20-fixtures.mjs';
import {browseInternships,readBrowseSaved} from '../../src/features/student/internships/s20Api';
const origin='http://127.0.0.1:4321';
afterEach(()=>vi.unstubAllGlobals());
describe('S-20 fixture server contract',()=>{
  it('parses only real pagination and verified-only server parameters',()=>{
    expect(parseS20CatalogueQuery(new URL(origin+'/api/v1/internships'+S20_QUERY),'GET')).toEqual({page:1,pageSize:20,verifiedOnly:false});
    expect(parseS20CatalogueQuery(new URL(origin+'/api/v1/internships?verified_only=true&page_size=20&page=2'),'GET')).toEqual({page:2,pageSize:20,verifiedOnly:true});
  });
  it.each(['','?page=0&page_size=20&verified_only=false','?page=1.5&page_size=20&verified_only=false','?page=1&page_size=10&verified_only=false','?page=1&page_size=20&verified_only=yes',S20_QUERY+'&search=Delhi',S20_QUERY+'&location=Delhi',S20_QUERY+'&stipend=paid',S20_QUERY+'&page=1',S20_QUERY+'#unexpected'])('rejects unsupported or malformed query %s',query=>{
    expect(()=>parseS20CatalogueQuery(new URL(origin+'/api/v1/internships'+query),'GET')).toThrow('S20_CATALOGUE_QUERY');
  });
  it('rejects a different route or method',()=>{
    expect(()=>parseS20CatalogueQuery(new URL(origin+'/api/v1/internships'+S20_QUERY),'POST')).toThrow();
    expect(()=>parseS20CatalogueQuery(new URL(origin+'/api/v1/other'+S20_QUERY),'GET')).toThrow();
  });
  it('supplies complete synthetic listings accepted by the unchanged product adapter',async()=>{
    vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({items:S20_LISTINGS,total:4,page:1,page_size:20}))).mockResolvedValueOnce(new Response(JSON.stringify({items:[S20_LISTINGS[0]]}))));
    expect((await browseInternships({page:1,verifiedOnly:false})).items).toHaveLength(4);
    expect((await readBrowseSaved())[0].id).toBe(S20_LISTINGS[0].id);
  });
});
describe('S-20 diagnostic classification is narrow and fail-closed',()=>{
  const rules={partial:['GET','/api/v1/student/internships/saved',503,'Service Unavailable'],'save-failed':['PUT',`/api/v1/student/internships/${S20_LISTINGS[0].id}/saved`,503,'Service Unavailable'],error:['GET','/api/v1/internships'+S20_QUERY,500,'Internal Server Error']};
  for(const [state,[method,path,status,reason]] of Object.entries(rules))it(`requires the exact ${state} negative response and rejects unrelated errors`,()=>{
    const responses=[{method,url:origin+path,status}],messages=[{url:origin+path,text:`Failed to load resource: the server responded with a status of ${status} (${reason})`}];
    expect(classifyS20Errors(state,origin,messages,responses,[],responses).errors).toEqual([]);
    for(const args of [[[],responses,[],responses],[messages,[],[],responses],[messages,responses,[],[]],[[...messages,messages[0]],responses,[],responses],[messages,responses,[{method:'GET',url:origin+'/unrelated',errorText:'net::ERR_FAILED'}],responses]])expect(classifyS20Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
  });
  it('requires real browser offline failure; does not broadly suppress requestfailed or console errors',()=>{
    const url=origin+'/api/v1/internships'+S20_QUERY,messages=[{url,text:'Failed to load resource: net::ERR_INTERNET_DISCONNECTED'}],failed=[{method:'GET',url,errorText:'net::ERR_INTERNET_DISCONNECTED'}];
    expect(classifyS20Errors('offline',origin,messages,[],failed,[]).errors).toEqual([]);
    for(const args of [[messages,[],[],[]],[[],[],failed,[]],[messages,[],[{...failed[0],url:origin+'/other'}],[]],[messages,[],[...failed,...failed],[]]])expect(classifyS20Errors('offline',origin,...args).errors.length).toBeGreaterThan(0);
  });
  it('does not allow errors in positive states',()=>{
    expect(classifyS20Errors('results',origin,[],[],[],[]).errors).toEqual([]);
    expect(classifyS20Errors('results',origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
    expect(classifyS20Errors('results',origin,[],[],[{method:'GET',url:origin,errorText:'net::ERR_FAILED'}],[]).errors).toContain('NETWORK_ERROR');
  });
});
