// Only approved S-19 default states. Manual-save mode remains unmeasured.
export const S19_MEASURED_STATES=Object.freeze(['loading','loaded','saving','saved','conflict','network','export-accepted','export-processing','export-complete','export-failed','request-not-found','delete-confirm','delete-invalid','delete-reauth','delete-reauth-rejected','delete-reauth-required','delete-conflict','delete-accepted','session','export-check-failed','delete-mobile-invalid','delete-start-failed','delete-rate-limited','delete-code-expired','delete-typed']);
export const S19_COVERAGE_APPROVAL='NYAY-91:16160';
export function hasS19RouteProof(row){
  if(!['S-19-session','S-19-delete-accepted'].includes(row.state))return true;
  const route=row.liveRouteBehavior;
  return row.coverageApproval===S19_COVERAGE_APPROVAL&&route?.executed===true&&route.from==='/s-19'&&route.to==='/s-03'
    &&route.syntheticServer===true&&route.artificialDelay===false&&route.navigationFrozen===false&&route.sessionAnonymous===true
    &&(row.state==='S-19-session'?row.evidenceKind==='component-visual':row.evidenceKind==='live-redirect-destination'&&route.deletionAccepted===true&&route.noticeObserved===true);
}
