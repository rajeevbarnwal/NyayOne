type SessionTimes = {start_utc:string;end_utc:string;iana_timezone:string};
// Display only: UTC instants and the timezone remain the validated server record.
export function formatSessionTimes({start_utc,end_utc,iana_timezone}:SessionTimes){
 const formatter=new Intl.DateTimeFormat('en-GB',{timeZone:iana_timezone,weekday:'short',day:'numeric',month:'short',year:'numeric',hour:'numeric',minute:'2-digit',hour12:true,timeZoneName:'shortOffset'});
 const parts=(instant:string)=>Object.fromEntries(formatter.formatToParts(new Date(instant)).filter(p=>p.type!=='literal').map(p=>[p.type,p.value]));
 const start=parts(start_utc),end=parts(end_utc);
 const date=(p:Record<string,string>)=>`${p.weekday} ${Number(p.day)} ${p.month} ${p.year}`;
 const time=(p:Record<string,string>)=>`${Number(p.hour)}:${p.minute} ${p.dayPeriod.toUpperCase()}`;
 const offsetChanged=start.timeZoneName!==end.timeZoneName;
 const suffix=(p:Record<string,string>)=>offsetChanged?` (${p.timeZoneName})`:'';
 return {start:`${date(start)}, ${time(start)}${suffix(start)}`,end:`${date(start)!==date(end)?date(end)+', ':''}${time(end)}${suffix(end)}`};
}
