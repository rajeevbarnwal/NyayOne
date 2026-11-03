import { afterEach, describe, expect, it, vi } from 'vitest';
import { QueryClient } from '@tanstack/react-query';
import { readPrivateSchools, removePrivateSchool, reconcileSchoolRemoval } from './s30Api';
const item={id:'a',name:'Synthetic School',slug:'a',state:'Delhi',institution_type:'government',accreditation:null,entrance_exam:null,fees_min:null,fees_max:null,nirf_rank:null};
const reply=(v:unknown,status=200)=>new Response(JSON.stringify(v),{status});
afterEach(()=>vi.unstubAllGlobals());
describe('S-30 private list authority',()=>{
 it.each(['saved','followed'] as const)('reads %s with signal and preserves missing values',async kind=>{
  const fetch=vi.fn().mockResolvedValue(reply({items:[{...item,notify_opt_in:false}]}));vi.stubGlobal('fetch',fetch);const signal=new AbortController().signal;
  expect(await readPrivateSchools(kind,signal)).toMatchObject([{id:'a',feesMin:null,entranceExam:null,notifyOptIn:kind==='saved'?null:false}]);
  expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/api/v1/student/law-schools/'+kind);expect(fetch.mock.calls[0][1]).toMatchObject({method:'GET',signal});
 });
 it.each([{}, {items:null},{items:[item,item]},{items:[{...item,id:''}]},{items:[{...item,fees_min:9,fees_max:1}]},{items:[{...item,nirf_rank:0}]},{items:[{...item,fees_min:undefined}]}])('fails closed for malformed list %j',async v=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply(v)));await expect(readPrivateSchools('saved')).rejects.toMatchObject({code:'invalid_response'});});
 it.each([undefined,null,'false',0])('never invents consent from %s',async value=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply({items:[{...item,notify_opt_in:value}]})));await expect(readPrivateSchools('followed')).rejects.toMatchObject({code:'invalid_response'});});
 it.each(['saved','followed'] as const)('requires confirmed %s removal and exact escaped ID',async kind=>{
  const fetch=vi.fn().mockResolvedValue(reply(kind==='saved'?{saved:false}:{followed:false,notify_opt_in:false}));vi.stubGlobal('fetch',fetch);
  await removePrivateSchool(kind,'school/a');expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(`/api/v1/student/law-schools/school%2Fa/${kind==='saved'?'saved':'follow'}`);expect(fetch.mock.calls[0][1].method).toBe('DELETE');
  fetch.mockResolvedValue(reply({saved:true,followed:false,notify_opt_in:true}));await expect(removePrivateSchool(kind,'a')).rejects.toMatchObject({code:'invalid_response'});
 });
 it.each([401,403,404,422,429,503])('keeps actual HTTP %s',async status=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply({detail:{code:'server_code'}},status)));await expect(readPrivateSchools('saved')).rejects.toMatchObject({status,code:'server_code'});});
 it('cancels stale reads, removes only the confirmed membership and invalidates detail',async()=>{
  const c=new QueryClient();c.setQueryData(['law-schools-saved','actor'],[{id:'a'},{id:'b'}]);c.setQueryData(['law-schools-followed','actor'],[{id:'a',notifyOptIn:true}]);c.setQueryData(['s28-detail','actor','a'],{saved:true,followed:true});
  await reconcileSchoolRemoval(c,'actor','saved','a',true,()=>true);
  expect(c.getQueryData(['law-schools-saved','actor'])).toEqual([{id:'b'}]);expect(c.getQueryData(['law-schools-followed','actor'])).toEqual([{id:'a',notifyOptIn:true}]);expect(c.getQueryState(['s28-detail','actor','a'])?.isInvalidated).toBe(true);
 });
 it('uncertain results invalidate without publishing removal; departed actors receive no changes',async()=>{
  const c=new QueryClient(),key=['law-schools-saved','actor'];c.setQueryData(key,[{id:'a'}]);await reconcileSchoolRemoval(c,'actor','saved','a',false,()=>true);expect(c.getQueryData(key)).toEqual([{id:'a'}]);expect(c.getQueryState(key)?.isInvalidated).toBe(true);
  c.setQueryData(key,[{id:'a'}]);await reconcileSchoolRemoval(c,'actor','saved','a',true,()=>false);expect(c.getQueryData(key)).toEqual([{id:'a'}]);expect(c.getQueryState(key)?.isInvalidated).toBe(false);
 });
});
