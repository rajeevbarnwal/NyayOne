import {describe,it,expect} from 'vitest';
import {classifyS18Errors} from './nyay66-s18-fixtures.mjs';
const origin='http://127.0.0.1:4321',url=origin+'/api/v1/student/settings';
describe('S-18 typed negative-response capture diagnostics',()=>{
  for(const [state,method,status,reason] of [['invalid','PATCH',422,'Unprocessable Entity'],['conflict','PATCH',409,'Conflict'],['network','PATCH',503,'Service Unavailable'],['forbidden','GET',403,'Forbidden'],['session','GET',401,'Unauthorized']]){
    const response={method,url,status},consoleError={url,text:`Failed to load resource: the server responded with a status of ${status} (${reason})`};
    it(`accepts ${state} only with the exact declaration, observed response and browser diagnostic`,()=>{
      expect(classifyS18Errors(state,origin,[consoleError],[response],[response]).errors).toEqual([]);
      for(const args of [[[],[response],[response]],[[consoleError],[],[response]],[[consoleError],[response],[]],
        [[consoleError,consoleError],[response],[response]],[[consoleError],[{...response,method:'DELETE'}],[response]],
        [[{...consoleError,url:origin+'/different'}],[response],[response]]])expect(classifyS18Errors(state,origin,...args).errors.length).toBeGreaterThan(0);
    });
  }
  it('never suppresses unrelated console/HTTP failures or permits errors on a success state',()=>{
    expect(classifyS18Errors('loaded',origin,[],[],[]).errors).toEqual([]);
    expect(classifyS18Errors('loaded',origin,[{url,text:'unexpected'}],[],[]).errors).toContain('CONSOLE_ERROR');
    expect(classifyS18Errors('saved',origin,[],[{method:'PATCH',url,status:503}],[]).errors).toContain('HTTP_RESPONSE_ERROR');
  });
});
