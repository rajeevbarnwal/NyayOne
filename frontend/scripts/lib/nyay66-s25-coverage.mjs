// Independent constants avoid a reference/continuation import cycle.
export const S25_MEASURED_STATES=Object.freeze(['loading','list','empty','remove-pending','remove-failed','error']);
export function hasS25LiveProof(row){
  if(row.screen!=='S-25')return true;
  const proof=row.routeProof;
  return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
    &&!!proof&&proof.path==='/s-25'&&S25_MEASURED_STATES.includes(proof.state)&&row.state===`S-25-${proof.state}`
    &&proof.requestSequenceVerified===true&&proof.serverConfirmationVerified===true;
}
