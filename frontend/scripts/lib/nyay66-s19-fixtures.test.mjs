import {describe,it,expect} from 'vitest';
import {classifyS19Errors,S19_NEGATIVE_RESPONSES} from './nyay66-s19-fixtures.mjs';
const origin='http://127.0.0.1:4321';
describe('S-19 negative HTTP diagnostics are exact and fail closed',()=>{
  for(const [state,rules] of Object.entries(S19_NEGATIVE_RESPONSES))it(`requires declared and observed ${state} errors without suppressing unrelated diagnostics`,()=>{
    const responses=rules.map(r=>({method:r.method,url:origin+r.path,status:r.status}));
    const messages=rules.map(r=>({url:origin+r.path,text:`Failed to load resource: the server responded with a status of ${r.status} (${r.reason})`}));
    expect(classifyS19Errors(state,origin,messages,responses,responses).errors).toEqual([]);
    for(const args of [[[],responses,responses],[messages,[],responses],[messages,responses,[]],[[...messages,messages[0]],responses,responses],[[{...messages[0],url:origin+'/unrelated'}],responses,responses]])expect(classifyS19Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
  });
  it('does not allow errors on a positive state',()=>{
    expect(classifyS19Errors('loaded',origin,[],[],[]).errors).toEqual([]);
    expect(classifyS19Errors('loaded',origin,[{url:origin,text:'unexpected'}],[],[]).errors).toContain('CONSOLE_ERROR');
    expect(classifyS19Errors('loaded',origin,[],[{method:'GET',url:origin,status:500}],[]).errors).toContain('HTTP_RESPONSE_ERROR');
  });
});
