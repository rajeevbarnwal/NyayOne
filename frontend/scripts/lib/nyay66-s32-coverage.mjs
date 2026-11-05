// Independent constants avoid a reference/continuation import cycle.
export const S32_MEASURED_STATES=Object.freeze(['loading','complete','selected','availability-error','no-slots','profile-error','missing','zone-changed','day-empty','dst-ambiguous','dst-gap']);
export function hasS32LiveProof(row){
 if(row.screen!=='S-32')return true;
 const proof=row.routeProof;
 return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
  &&!!proof&&proof.path==='/s-32'&&S32_MEASURED_STATES.includes(proof.state)&&row.state===`S-32-${proof.state}`&&row.designState===proof.state
  &&proof.requestSequenceVerified===true&&proof.serverConfirmationVerified===true&&proof.selectionBeforeBookingVerified===true&&proof.timezoneResolutionVerified===true;
}
