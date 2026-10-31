import {describe,it,expect,vi,afterEach} from 'vitest';
import {S27_SCHOOLS,S27_QUERY,parseS27Query,s27Response,expectedS27Requests,verifyS27Requests,classifyS27Errors} from './nyay66-s27-fixtures.mjs';
import {S27_STATES} from './nyay66-s27-reference.mjs';
import {readSchoolSearch} from '../../src/features/student/schools/s27Api';
const origin='http://127.0.0.1:4321',directory='/api/v1/law-schools';
afterEach(()=>vi.unstubAllGlobals());
describe('S-27 synthetic public directory contracts',()=>{
  it('uses actual backend pagination, sorting and public summary shape through the product adapter',async()=>{
    for(const [search,ids,total] of [
      [S27_QUERY,S27_SCHOOLS.slice(0,4).map(s=>s.id),6],
      ['?sort=name&page=2&page_size=4',S27_SCHOOLS.slice(4).map(s=>s.id),6],
      ['?sort=fees&page=1&page_size=4',[4,2,1,0].map(i=>S27_SCHOOLS[i].id),6],
      ['?sort=nirf_rank&page=1&page_size=4',[1,2,0,3].map(i=>S27_SCHOOLS[i].id),6],
      ['?q=no-synthetic-match&sort=name&page=1&page_size=4',[],0],
    ]){
      const query=parseS27Query(new URL(origin+directory+search),'GET');
      vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(s27Response(query)))));
      const result=await readSchoolSearch(new URLSearchParams(search));
      expect(result.items.map(s=>s.id)).toEqual(ids);expect(result.total).toBe(total);
      expect(result.page).toBe(query.page);expect(result.pageSize).toBe(4);expect(result.compareMax).toBe(4);
    }
  });
  it('rejects invented endpoints, mutations, duplicate/unknown query keys and invalid fixture inputs',()=>{
    for(const [path,method] of [[directory+S27_QUERY,'POST'],['/api/v1/student/law-schools'+S27_QUERY,'GET'],
      [directory+S27_QUERY+'&invented=true','GET'],[directory+S27_QUERY+'&sort=fees','GET'],
      [directory+'?sort=name&page=0&page_size=4','GET'],[directory+'?sort=name&page=1&page_size=50','GET'],
      [directory+'?sort=name&page=1','GET'],[directory+S27_QUERY+'#invented','GET']])
      expect(()=>parseS27Query(new URL(origin+path),method)).toThrow('S27_DIRECTORY_QUERY');
  });
  it('requires session read then exactly one public directory GET; offline sends no directory request and compare is local',()=>{
    for(const state of S27_STATES){
      const expected=expectedS27Requests(state);expect(verifyS27Requests(state,expected)).toBe(true);
      expect(expected.length).toBe(state==='offline'?1:2);
      for(const changed of [expected.slice(1),[...expected,expected[0]],expected.map((r,i)=>i?r:{...r,method:'POST'}),
        [...expected,{method:'GET',path:'/api/v1/student/law-schools/saved',search:''}]])expect(verifyS27Requests(state,changed)).toBe(false);
    }
    expect(verifyS27Requests('invented',[])).toBe(false);
    expect(verifyS27Requests('compare',expectedS27Requests('page-2'))).toBe(false);
    expect(verifyS27Requests('sort-fees',expectedS27Requests('sort-nirf'))).toBe(false);
  });
  it('requires the exact genuine 422/500 response and matching browser error, never HTTP 200 pretending to fail',()=>{
    for(const [state,status,reason] of [['invalid-filter',422,'Unprocessable Entity'],['error',500,'Internal Server Error']]){
      const request=expectedS27Requests(state).at(-1),url=origin+request.path+request.search;
      const responses=[{method:'GET',url,status}],messages=[{url,text:`Failed to load resource: the server responded with a status of ${status} (${reason})`}];
      expect(classifyS27Errors(state,origin,messages,responses,[],responses).errors).toEqual([]);
      for(const args of [[[],responses,[],responses],[messages,[],[],responses],[messages,responses,[],[]],
        [[...messages,...messages],responses,[],responses],[messages,responses,[{url,errorText:'net::ERR_FAILED'}],responses],
        [messages,[{...responses[0],status:200}],[],responses],[messages,[{...responses[0],method:'DELETE'}],[],responses]])
        expect(classifyS27Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
    }
  });
  it('rejects unexpected console, HTTP, network and declaration errors even in the offline state',()=>{
    for(const state of S27_STATES.filter(s=>!['invalid-filter','error'].includes(s)))expect(classifyS27Errors(state,origin,[],[],[],[]).errors).toEqual([]);
    expect(classifyS27Errors('offline',origin,[{url:origin,text:'unexpected'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
    expect(classifyS27Errors('loading',origin,[],[{url:origin,status:500}],[],[]).errors).toContain('HTTP_RESPONSE_ERROR');
    expect(classifyS27Errors('offline',origin,[],[],[{url:origin}],[]).errors).toContain('NETWORK_ERROR');
    expect(classifyS27Errors('results',origin,[],[],[],[{url:origin}]).errors).toContain('UNEXPECTED_HTTP_DECLARATION');
    expect(classifyS27Errors('invented',origin,[],[],[],[]).errors).toContain('S27_FIXTURE_SCOPE');
  });
});
