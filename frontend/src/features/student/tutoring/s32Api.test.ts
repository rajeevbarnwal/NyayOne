import {afterEach,expect,it,vi} from 'vitest';
import {readMentorDetail,readMentorAvailability,availabilityQuery} from './s32Api';
const tutor={id:'mentor/a',display_name:'Synthetic Mentor',headline:null,experience_years:1,rating_avg:'5.00',rating_count:1,verified_identity:true,verified_credentials:false,status:'active',session_price_paise:89950,currency:'INR',source:null,source_url:null,retrieved_at:null,subjects:[{subject:'Law',level:'Advanced'}],rating_aggregate:{tutor_id:'mentor/a',rating_count:1,rating_avg:'5.00',distribution:{'5':1}}};
const slot={slot_id:'slot/a',tutor_id:tutor.id,start_utc:'2027-10-31T00:30:00Z',end_utc:'2027-10-31T01:15:00Z',iana_timezone:'Europe/London',status:'available',start_local:'2027-10-31T01:30:00+01:00',end_local:'2027-10-31T01:15:00+00:00',duration_minutes:45,price_paise:89950,currency:'INR'};
const page={tutor_id:tutor.id,iana_timezone:'Europe/London',window:{from_utc:null,to_utc:null},local_resolution:{},slots:[slot],limit:50,offset:0};
const reply=(body:unknown,status=200)=>new Response(JSON.stringify(body),{status});
afterEach(()=>vi.unstubAllGlobals());
it('empty timezone uses the device default while explicit invalid zones still reach server validation',()=>{
 expect(availabilityQuery(new URLSearchParams('tz='),'Europe/London').get('timezone')).toBe('Europe/London');
 expect(availabilityQuery(new URLSearchParams('tz=Bad/Zone'),'Europe/London').get('timezone')).toBe('Bad/Zone');
});
it('canonicalizes valid uppercase UUIDs for profile, aggregate and availability identity checks',async()=>{
 const id='abcdefab-1234-4567-89ab-abcdef123456';
 const detail={...tutor,id,rating_aggregate:{...tutor.rating_aggregate,tutor_id:id}};
 const availability={...page,tutor_id:id,slots:[{...slot,tutor_id:id}]};
 const fetch=vi.fn().mockResolvedValueOnce(reply(detail)).mockResolvedValueOnce(reply(availability));vi.stubGlobal('fetch',fetch);
 expect(await readMentorDetail(id.toUpperCase())).toEqual(detail);
 expect(await readMentorAvailability(id.toUpperCase(),new URLSearchParams())).toEqual(availability);
 expect(new URL(fetch.mock.calls[0][0]).pathname).toBe(`/api/v1/tutors/${id}`);
 expect(new URL(fetch.mock.calls[1][0]).pathname).toBe(`/api/v1/tutors/${id}/availability`);
});
it('does not make opaque non-UUID identities case-insensitive',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply(tutor)));
 await expect(readMentorDetail(tutor.id.toUpperCase())).rejects.toMatchObject({code:'invalid_response'});
});
for(const price of [0,-1,0.5])it(`rejects invalid profile and slot price ${price} without claiming free tutoring`,async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(reply({...tutor,session_price_paise:price})).mockResolvedValueOnce(reply({...page,slots:[{...slot,price_paise:price}]})));
 await expect(readMentorDetail(tutor.id)).rejects.toMatchObject({code:'invalid_response'});
 await expect(readMentorAvailability(tutor.id,new URLSearchParams())).rejects.toMatchObject({code:'invalid_response'});
});
it('accepts a positive one-paise price without rounding it to zero',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(reply({...tutor,session_price_paise:1})).mockResolvedValueOnce(reply({...page,slots:[{...slot,price_paise:1}]})));
 expect((await readMentorDetail(tutor.id)).session_price_paise).toBe(1);
 expect((await readMentorAvailability(tutor.id,new URLSearchParams())).slots[0].price_paise).toBe(1);
});
it('forwards only supported availability windows and paging without guessing server validation',()=>{
 expect(Object.fromEntries(availabilityQuery(new URLSearchParams('tz=Bad/Zone&date=bad&from_local=2027-10-31T01:30&status=held&price=2&offset=-1'),'Asia/Kolkata'))).toEqual({timezone:'Bad/Zone',date:'bad',from_local:'2027-10-31T01:30',limit:'50',offset:'-1'});
});
it('reads profile and exact server slot instants, duration and price with cancellation and escaped ids',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce(reply(tutor)).mockResolvedValueOnce(reply(page));vi.stubGlobal('fetch',fetch);const signal=new AbortController().signal;
 expect(await readMentorDetail(tutor.id,signal)).toEqual(tutor);expect(await readMentorAvailability(tutor.id,new URLSearchParams('timezone=Europe/London'),signal)).toEqual(page);
 expect(new URL(fetch.mock.calls[0][0]).pathname).toBe('/api/v1/tutors/mentor%2Fa');expect(fetch.mock.calls[1][1]).toMatchObject({method:'GET',signal});
});
for(const body of [{},{...tutor,id:'other'},{...tutor,session_price_paise:undefined},{...tutor,verified_identity:'true'},{...tutor,subjects:null},{...tutor,rating_aggregate:{...tutor.rating_aggregate,tutor_id:'other'}}])it('rejects malformed/foreign profile without inventing facts',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply(body)));await expect(readMentorDetail(tutor.id)).rejects.toMatchObject({code:'invalid_response'});});
for(const body of [{},{...page,tutor_id:'other'},{...page,slots:[slot,slot]},{...page,slots:[{...slot,tutor_id:'other'}]},{...page,slots:[{...slot,start_utc:'not a date'}]},{...page,slots:[{...slot,price_paise:undefined}]},{...page,slots:[{...slot,duration_minutes:0}]},{...page,iana_timezone:'not/a/zone'},{...page,local_resolution:{from_local:{classification:'invented'}}}])it('rejects malformed/foreign availability without claiming no slots',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply(body)));await expect(readMentorAvailability(tutor.id,new URLSearchParams())).rejects.toMatchObject({code:'invalid_response'});});
for(const status of [401,403,404,422,429,503])it(`preserves real HTTP ${status} and retry metadata`,async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue(reply({detail:{code:'server_code',retry_after_seconds:3}},status)));await expect(readMentorDetail(tutor.id)).rejects.toMatchObject({status,code:'server_code',retryAfterSeconds:3});});
