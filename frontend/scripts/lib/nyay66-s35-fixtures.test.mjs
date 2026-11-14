import {describe,it,expect} from 'vitest';
import {S35_STATES} from './nyay66-s35-reference.mjs';
import {s35Plan,verifyS35Requests,classifyS35Errors,S35_IDS} from './nyay66-s35-fixtures.mjs';
describe('S-35 synthetic API and browser evidence contract',()=>{
 it.each(S35_STATES)('%s has a closed request plan and explicit evidence limitations',state=>{
  const p=s35Plan(state);expect(p.state).toBe(state);expect(p.steps[0].path).toBe('/api/v1/auth/student/session');
  expect(p.steps.every(s=>['GET','POST','PATCH','DELETE'].includes(s.method))).toBe(true);
  expect(verifyS35Requests(state,p.steps.map(({method,path,search,body})=>({method,path,search,body})))).toBe(true);
  expect(verifyS35Requests(state,[])).toBe(false);
  expect(verifyS35Requests(state,[...p.steps.map(({method,path,search,body})=>({method,path,search,body})),{method:'GET',path:'/invented',search:'',body:null}])).toBe(false);
  expect(p.realBackendTested).toBe(false);expect(p.realMediaProviderTested).toBe(false);
 });
 it('refuses unknown states and never invents a student settlement read',()=>{
  expect(()=>s35Plan('invented')).toThrow('S35_FIXTURE_SCOPE');
  for(const state of S35_STATES)expect(s35Plan(state).steps.some(s=>s.path.includes('/refund'))).toBe(false);
  for(const state of ['refund-pending','refund-failed'])expect(s35Plan(state).capabilityGap).toBe('student-refund-settlement-status-unavailable');
 });
 it('pins real backend error codes/statuses, versions and review creation before editing',()=>{
  expect(s35Plan('room').steps.find(s=>s.path.endsWith('/join-credentials')).status).toBe(201);
  expect(s35Plan('rate-limited').steps[1]).toMatchObject({status:429,response:{detail:{code:'rate_limit_exceeded',retry_after_seconds:30}}});
  expect(s35Plan('cancel-stale').steps.find(s=>s.method==='POST')).toMatchObject({status:409,response:{detail:{code:'SESSION_STALE_VERSION'}},body:{expected_version:1}});
  expect(s35Plan('reschedule-wrong-tutor').steps.find(s=>s.method==='POST')).toMatchObject({status:422,response:{detail:{code:'VALIDATION_ERROR'}},body:{expected_version:1,new_slot_id:S35_IDS.nextSlot}});
  for(const state of ['review-edit','review-delete-confirm','review-deleted','review-delete-failed'])expect(s35Plan(state).steps.some(s=>s.method==='POST'&&s.path.endsWith('/review'))).toBe(true);
 });
 it('does not excuse unexpected browser/network errors or missing expected HTTP errors',()=>{
  expect(classifyS35Errors('list','http://local',[],[],[],[]).errors).toEqual([]);
  expect(classifyS35Errors('list','http://local',[{text:'unexpected',url:'http://local'}],[],[],[]).errors).toContain('CONSOLE_ERROR');
  expect(classifyS35Errors('list-error','http://local',[],[],[],[]).errors).toContain('S35_EXPECTED_HTTP_ERROR_UNOBSERVED');
 });
});
