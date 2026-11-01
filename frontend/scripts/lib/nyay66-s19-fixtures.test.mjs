import {describe,it,expect} from 'vitest';
import {classifyS19Errors,S19_NEGATIVE_RESPONSES,mockS19Application} from './nyay66-s19-fixtures.mjs';
const origin='http://127.0.0.1:4321';
it.each(['saved','export-accepted','delete-confirm'])('waits for real font/image readiness before the first %s interaction',async state=>{
  const events=[],stop=Error('FIRST_ACTION_PROBE');let release,source;
  const resources=new Promise(resolve=>{release=resolve;});
  const page={
    route:async()=>{},goto:async()=>{events.push('goto');},
    locator:()=>({waitFor:async()=>{events.push('surface');}}),
    evaluate:async callback=>{source=callback.toString();events.push('resources');await resources;},
    waitForResponse:async()=>{},
    getByRole:()=>({click:async()=>{events.push('action');throw stop;}}),
  };
  const result=mockS19Application(page,state,origin,[]).catch(error=>error);
  await new Promise(resolve=>setImmediate(resolve));
  try{
    expect(events).toEqual(['goto','surface','resources']);
    expect(source).toContain('document.fonts.ready');expect(source).toContain('document.images');
    expect(source).not.toMatch(/setTimeout|scrollTo|\.focus\(|Date|clock/);
  }finally{release();}
  expect(await result).toBe(stop);
  expect(events).toEqual(['goto','surface','resources','action']);
});
it('fails before interaction if font/image readiness fails, without a timed fallback',async()=>{
  const failed=Error('RESOURCE_READINESS_FAILED');let actions=0;
  const page={route:async()=>{},goto:async()=>{},locator:()=>({waitFor:async()=>{}}),
    evaluate:async()=>{throw failed;},getByRole:()=>({click:async()=>{actions++;}})};
  await expect(mockS19Application(page,'saved',origin,[])).rejects.toBe(failed);
  expect(actions).toBe(0);
});
it('deletion-conflict transport uses the backend concurrent_state_changed contract, not a settings-version conflict',async()=>{
  let handler;
  const stop=new Error('transport-only probe');
  const page={route:async(_pattern,callback)=>{handler=callback;},goto:async()=>{throw stop;}};
  const errors=[];
  await expect(mockS19Application(page,'delete-conflict',origin,errors)).rejects.toBe(stop);
  async function post(path,body){
    let response;
    await handler({request:()=>({url:()=>origin+path,method:()=>'POST',postData:()=>JSON.stringify(body),postDataJSON:()=>body}),fulfill:async value=>{response=value;},abort:async()=>{throw Error('unexpected request');}});
    return {status:response.status,body:JSON.parse(response.body)};
  }
  expect((await post('/api/v1/auth/student/recovery/start',{mobile:'9876500340'})).status).toBe(202);
  expect((await post('/api/v1/auth/student/recovery/verify',{code:'123456'})).status).toBe(200);
  expect(await post('/api/v1/student/privacy/delete',{confirmation:'DELETE'})).toEqual({status:409,body:{detail:{code:'concurrent_state_changed'}}});
  expect(errors).toEqual([]);
});
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
