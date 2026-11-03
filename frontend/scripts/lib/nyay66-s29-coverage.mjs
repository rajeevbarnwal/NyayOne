// Independent constants avoid a reference/continuation import cycle.
export const S29_MEASURED_STATES=Object.freeze(['loading','complete','three','incomplete','too-few','error']);
export function hasS29LiveProof(row){
  if(row.screen!=='S-29')return true;
  const proof=row.routeProof;
  return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
    &&!!proof&&proof.path==='/s-29'&&S29_MEASURED_STATES.includes(proof.state)&&row.state===`S-29-${proof.state}`
    &&proof.requestSequenceVerified===true&&proof.serverConfirmationVerified===true&&proof.selectionVerified===true;
}
