// A typed negative-state fixture is evidence, not a broken capture. Only these
// two exact S-06 responses may explain one Chromium resource-error diagnostic.
// Fixture declarations alone are insufficient: a separately observed response
// must match method, URL and status. Everything remains in the report.
const NEGATIVE_STATES={
  's06-wrong':{path:'/api/v1/auth/student/recovery/verify',status:401,reason:'Unauthorized'},
  's06-neterr':{path:'/api/v1/auth/student/recovery/start',status:503,reason:'Service Unavailable'},
};
const sameResponse=(a,b)=>a?.method===b?.method&&a?.url===b?.url&&a?.status===b?.status;

export function classifyConsoleErrors({state,origin,consoleErrors=[],expectedHttpErrors=[],httpResponses=[]}) {
  const rule=NEGATIVE_STATES[state];
  const permitted=rule?{method:'POST',url:origin+rule.path,status:rule.status}:null;
  const expected=expectedHttpErrors.length===1&&permitted&&sameResponse(expectedHttpErrors[0],permitted)
    ?expectedHttpErrors[0]:null;
  const consumedResponses=new Set();
  let consumedExpected=false;
  const errors=[];
  const diagnostics=consoleErrors.map(error=>{
    const responseIndex=expected&&!consumedExpected
      ?httpResponses.findIndex((response,index)=>!consumedResponses.has(index)&&sameResponse(response,expected)):-1;
    const exactMessage=rule&&`Failed to load resource: the server responded with a status of ${rule.status} (${rule.reason})`;
    if(responseIndex>=0&&error.text===exactMessage&&error.url===expected.url){
      consumedExpected=true;consumedResponses.add(responseIndex);
      return {...error,classification:'EXPECTED_SYNTHETIC_HTTP_ERROR',response:{...expected}};
    }
    errors.push('CONSOLE_ERROR');
    return {...error,classification:'UNEXPECTED_CONSOLE_ERROR'};
  });
  const responseDiagnostics=httpResponses.map((response,index)=>{
    const matched=consumedResponses.has(index);
    if(!matched)errors.push('HTTP_RESPONSE_ERROR');
    return {...response,classification:matched?'EXPECTED_SYNTHETIC_HTTP_ERROR':'UNEXPECTED_HTTP_ERROR'};
  });
  const unmatchedExpected=consumedExpected?[]:expectedHttpErrors.map(response=>({...response}));
  // These two negative states require the complete declaration/response/
  // diagnostic match. Missing all evidence is not a clean successful capture.
  if(unmatchedExpected.length||(rule&&!consumedExpected))errors.push('EXPECTED_HTTP_ERROR_UNOBSERVED');
  return {consoleErrorCount:consoleErrors.length,expectedHttpErrorCount:Number(consumedExpected),
    consoleErrors:diagnostics,httpErrorResponses:responseDiagnostics,unmatchedExpectedHttpErrors:unmatchedExpected,errors};
}
