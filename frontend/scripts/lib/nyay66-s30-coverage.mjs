// Independent constants avoid a reference/continuation import cycle.
export const S30_MEASURED_STATES=Object.freeze(['loading','both','following-tab','saved-empty','followed-empty','item-pending','item-error','error']);
export function hasS30LiveProof(row){
  if(row.screen!=='S-30')return true;
  const proof=row.routeProof;
  return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
    &&!!proof&&proof.path==='/s-30'&&S30_MEASURED_STATES.includes(proof.state)&&row.state===`S-30-${proof.state}`
    &&proof.requestSequenceVerified===true&&proof.serverConfirmationVerified===true&&proof.membershipVerified===true;
}
