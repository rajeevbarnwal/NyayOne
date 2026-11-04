// Independent constants avoid a reference/continuation import cycle.
export const S31_MEASURED_STATES=Object.freeze(['loading','results','filters-open','no-matches','rate-limited','error','offline','page-2']);
export function hasS31LiveProof(row){
  if(row.screen!=='S-31')return true;
  const proof=row.routeProof;
  return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
    &&!!proof&&proof.path==='/s-31'&&S31_MEASURED_STATES.includes(proof.state)&&row.state===`S-31-${proof.state}`
    &&proof.requestSequenceVerified===true&&proof.serverConfirmationVerified===true&&proof.searchPaginationVerified===true;
}
