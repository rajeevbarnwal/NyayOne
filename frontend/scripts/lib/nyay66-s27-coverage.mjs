// Independent constants avoid a reference/continuation import cycle.
export const S27_MEASURED_STATES=Object.freeze(['loading','results','filters-open','compare','no-results','invalid-filter','error','offline','page-2','sort-fees','sort-nirf']);
export function hasS27LiveProof(row){
  if(row.screen!=='S-27')return true;
  const proof=row.routeProof;
  return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
    &&!!proof&&proof.path==='/s-27'&&S27_MEASURED_STATES.includes(proof.state)&&row.state===`S-27-${proof.state}`
    &&proof.requestSequenceVerified===true&&proof.serverConfirmationVerified===true;
}
