// Independent constants avoid a reference/continuation import cycle.
export const S26_MEASURED_STATES=Object.freeze(['empty','loading','error','nonempty']);
export function hasS26LiveProof(row){
  if(row.screen!=='S-26')return true;
  const proof=row.routeProof;
  return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
    &&!!proof&&proof.path==='/s-26'&&S26_MEASURED_STATES.includes(proof.state)&&row.state===`S-26-${proof.state}`
    &&proof.requestSequenceVerified===true&&proof.serverConfirmationVerified===true;
}
