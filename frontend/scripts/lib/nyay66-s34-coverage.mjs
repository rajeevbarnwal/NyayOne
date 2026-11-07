// Independent constants avoid reference/continuation import cycles.
export const S34_MEASURED_STATES=Object.freeze(['loading','confirmed','pending-provider','cancelled','error','missing']);
export function hasS34LiveProof(row){
 if(row.screen!=='S-34')return true;
 const p=row.routeProof;
 return row.evidenceKind==='live-route'&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
  &&!!p&&p.path==='/s-34'&&S34_MEASURED_STATES.includes(p.state)&&row.state===`S-34-${p.state}`&&row.designState===p.state
  &&p.requestSequenceVerified===true&&p.serverConfirmationVerified===true&&p.sessionIdentityVerified===true&&p.noInventedPaymentOrJoin===true;
}
