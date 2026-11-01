// Independent constants avoid a reference/continuation import cycle.
export const S28_MEASURED_STATES=Object.freeze(['loading','complete','following','save-pending','follow-error','missing','error']);
export function hasS28LiveProof(row){
  if(row.screen!=='S-28')return true;
  const proof=row.routeProof;
  return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
    &&!!proof&&proof.path==='/s-28'&&S28_MEASURED_STATES.includes(proof.state)&&row.state===`S-28-${proof.state}`
    &&proof.requestSequenceVerified===true&&proof.serverConfirmationVerified===true;
}
