import {describe,expect,it} from 'vitest';
import {readFileSync} from 'node:fs';
import {classifyConsoleErrors} from './nyay66-console-errors.mjs';

const origin='http://127.0.0.1:54321';
const tuple=(status=401)=>({method:'POST',url:origin+'/api/v1/auth/student/recovery/'+(status===401?'verify':'start'),status});
const message=(status=401)=>({text:`Failed to load resource: the server responded with a status of ${status} (${status===401?'Unauthorized':'Service Unavailable'})`,url:tuple(status).url});
const input=(status=401)=>({state:status===401?'s06-wrong':'s06-neterr',origin,expectedHttpErrors:[tuple(status)],httpResponses:[tuple(status)],consoleErrors:[message(status)]});

describe('S-06 expected synthetic HTTP error diagnostics',()=>{
  for(const status of [401,503])it(`classifies only the exact observed ${status} response once and retains the diagnostic`,()=>{
    const result=classifyConsoleErrors(input(status));
    expect(result.errors).toEqual([]);
    expect(result.consoleErrorCount).toBe(1);
    expect(result.expectedHttpErrorCount).toBe(1);
    expect(result.consoleErrors).toEqual([{...message(status),classification:'EXPECTED_SYNTHETIC_HTTP_ERROR',response:tuple(status)}]);
  });
  it('preserves normal empty captures',()=>expect(classifyConsoleErrors({state:'s05',origin})).toEqual({consoleErrorCount:0,expectedHttpErrorCount:0,consoleErrors:[],httpErrorResponses:[],unmatchedExpectedHttpErrors:[],errors:[]}));
  for(const status of [401,503]){
    for(const mode of ['omitted','empty'])it(`refuses ${status} negative-state evidence when all arrays are ${mode}`,()=>{
      const value={state:status===401?'s06-wrong':'s06-neterr',origin,
        ...(mode==='empty'?{expectedHttpErrors:[],httpResponses:[],consoleErrors:[]}:{})};
      const result=classifyConsoleErrors(value);
      expect(result.errors).toEqual(['EXPECTED_HTTP_ERROR_UNOBSERVED']);
      expect(result.expectedHttpErrorCount).toBe(0);
    });
    for(const field of ['expectedHttpErrors','httpResponses','consoleErrors'])it(`requires ${field} for the ${status} negative state`,()=>{
      const value=input(status);delete value[field];
      const result=classifyConsoleErrors(value);
      expect(result.errors).toContain('EXPECTED_HTTP_ERROR_UNOBSERVED');
      expect(result.expectedHttpErrorCount).toBe(0);
    });
  }
  for(const [name,mutate] of [
    ['unmatched message',x=>x.consoleErrors[0].text='Application crashed'],
    ['message prefix',x=>x.consoleErrors[0].text='prefix '+x.consoleErrors[0].text],
    ['message suffix',x=>x.consoleErrors[0].text+='\nApplication crashed'],
    ['status text',x=>x.consoleErrors[0].text=x.consoleErrors[0].text.replace('Unauthorized','Forbidden')],
    ['console URL',x=>x.consoleErrors[0].url=origin+'/unexpected'],
    ['missing console URL',x=>delete x.consoleErrors[0].url],
    ['console status',x=>x.consoleErrors[0].text=x.consoleErrors[0].text.replace('401','503')],
    ['response method',x=>x.httpResponses[0].method='GET'],
    ['response URL',x=>x.httpResponses[0].url=origin+'/unexpected'],
    ['response status',x=>x.httpResponses[0].status=403],
    ['missing response',x=>x.httpResponses=[]],
    ['receipt method',x=>x.expectedHttpErrors[0].method='GET'],
    ['receipt URL',x=>x.expectedHttpErrors[0].url=origin+'/unexpected'],
    ['receipt status',x=>x.expectedHttpErrors[0].status=403],
    ['missing receipt',x=>x.expectedHttpErrors=[]],
    ['wrong state',x=>x.state='s06-entry'],
    ['other screen',x=>x.state='s01-error'],
    ['other origin',x=>x.origin='http://127.0.0.1:54322'],
    ['duplicate receipt',x=>x.expectedHttpErrors.push({...x.expectedHttpErrors[0]})],
  ])it(`does not suppress ${name}`,()=>{
    const value=input();mutate(value);
    const result=classifyConsoleErrors(value);
    expect(result.errors.length).toBeGreaterThan(0);
    expect(result.expectedHttpErrorCount).toBe(0);
    expect(result.consoleErrors[0].classification).toBe('UNEXPECTED_CONSOLE_ERROR');
  });
  it('does not reuse a receipt or response for a duplicate console event',()=>{
    const value=input();value.consoleErrors.push({...value.consoleErrors[0]});
    const result=classifyConsoleErrors(value);
    expect(result.consoleErrorCount).toBe(2);expect(result.expectedHttpErrorCount).toBe(1);
    expect(result.errors).toContain('CONSOLE_ERROR');
    expect(result.consoleErrors.map(x=>x.classification)).toEqual(['EXPECTED_SYNTHETIC_HTTP_ERROR','UNEXPECTED_CONSOLE_ERROR']);
  });
  it('does not hide a second unexpected response to the same endpoint',()=>{
    const value=input();value.httpResponses.push({...value.httpResponses[0]});
    const result=classifyConsoleErrors(value);
    expect(result.expectedHttpErrorCount).toBe(1);
    expect(result.errors).toContain('HTTP_RESPONSE_ERROR');
    expect(result.httpErrorResponses.map(x=>x.classification)).toEqual(['EXPECTED_SYNTHETIC_HTTP_ERROR','UNEXPECTED_HTTP_ERROR']);
  });
  it('keeps unrelated errors alongside the expected resource diagnostic',()=>{
    const value=input();value.consoleErrors.push({text:'TypeError in application',url:origin+'/assets/app.js'});
    const result=classifyConsoleErrors(value);
    expect(result.expectedHttpErrorCount).toBe(1);expect(result.consoleErrorCount).toBe(2);
    expect(result.errors).toEqual(['CONSOLE_ERROR']);
  });
  it('refuses unobserved expected errors rather than claiming negative-state coverage',()=>{
    const value=input();value.httpResponses=[];value.consoleErrors=[];
    const result=classifyConsoleErrors(value);
    expect(result.errors).toContain('EXPECTED_HTTP_ERROR_UNOBSERVED');
    expect(result.expectedHttpErrorCount).toBe(0);
  });
  it('classifies from snapshots without mutating supplied evidence',()=>{
    const value=input();const before=JSON.stringify(value);classifyConsoleErrors(value);
    expect(JSON.stringify(value)).toBe(before);
  });
});

describe('evaluator diagnostic wiring',()=>{
  it('retains page and network failures and binds resource diagnostics to independent responses',()=>{
    const source=readFileSync(new URL('../nyay66-live.mjs',import.meta.url),'utf8');
    expect(source).toContain("page.on('pageerror',()=>errors.push('PAGE_ERROR'))");
    expect(source).toContain("const recordNetworkFailure=()=>errors.push('NETWORK_ERROR')");
    expect(source).toContain("page.on('requestfailed',recordNetworkFailure)");
    expect(source).toContain("page.off('requestfailed',recordNetworkFailure)");
    expect(source).toContain("page.on('response'");
    expect(source).toContain('response.request().method()');
    expect(source).toContain('expectedHttpErrors:row.expectedHttpErrors');
    expect(source).toContain('errors.push(...consoleDiagnostics.errors)');
    expect(source).toContain('row.consoleDiagnostics=consoleDiagnostics');
  });
});
