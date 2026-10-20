// Independent constants avoid a reference/continuation import cycle.
export const S21_MEASURED_STATES=Object.freeze(['loading','complete','saved','save-pending','save-failed','session','missing','error']);
export function hasS21LiveProof(row){
  if(row.screen!=='S-21')return true;
  const proof=row.routeProof;
  return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
    &&!!proof&&proof.path==='/s-21'&&proof.listing==='arbitration-intern'&&S21_MEASURED_STATES.includes(proof.state)
    &&row.state===`S-21-${proof.state}`&&proof.requestSequenceVerified===true&&proof.applyDisabled===true
    &&(proof.state!=='session'||(row.sessionInvalidation?.observedAnonymous===true
      &&row.sessionInvalidation.responseCode==='authentication_required'&&row.sessionInvalidation.productionHandler===true));
}
