import {describe,it,expect} from 'vitest';
import {formatSessionTimes} from './s34Presentation';
describe('S-34 server-time presentation',()=>{
 it('uses the returned timezone and frozen readable date/time style',()=>{
  expect(formatSessionTimes({start_utc:'2026-08-18T13:00:00Z',end_utc:'2026-08-18T13:45:00Z',iana_timezone:'Asia/Kolkata'})).toEqual({start:'Tue 18 Aug 2026, 6:30 PM',end:'7:15 PM'});
 });
 it('includes the end date across a local midnight rather than implying the same day',()=>{
  expect(formatSessionTimes({start_utc:'2026-08-18T18:00:00Z',end_utc:'2026-08-18T19:00:00Z',iana_timezone:'Asia/Kolkata'})).toEqual({start:'Tue 18 Aug 2026, 11:30 PM',end:'Wed 19 Aug 2026, 12:30 AM'});
 });
 it('uses each instant in the server zone and disambiguates repeated DST wall times',()=>{
  expect(formatSessionTimes({start_utc:'2026-11-01T05:30:00Z',end_utc:'2026-11-01T06:30:00Z',iana_timezone:'America/New_York'})).toEqual({start:'Sun 1 Nov 2026, 1:30 AM (GMT-4)',end:'1:30 AM (GMT-5)'});
 });
 it('does not fall back to a device timezone for invalid input',()=>{
  expect(()=>formatSessionTimes({start_utc:'invalid',end_utc:'2026-08-18T13:45:00Z',iana_timezone:'Asia/Kolkata'})).toThrow();
  expect(()=>formatSessionTimes({start_utc:'2026-08-18T13:00:00Z',end_utc:'2026-08-18T13:45:00Z',iana_timezone:'Invalid/Zone'})).toThrow();
 });
});
