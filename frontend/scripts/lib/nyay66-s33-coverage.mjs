// Independent constants avoid reference/continuation cycles.
export const S33_MEASURED_STATES=Object.freeze(['hold-creating','hold-active','slot-conflict','hold-expired','order-pending','payment-failed','creating-session','payment-unverified','confirmed','rate-limited','network','session','hold-60min','hold-other-mentor']);
export function hasS33LiveProof(row){
 if(row.screen!=='S-33')return true;
 const p=row.routeProof,session=p?.state==='session';
 return row.evidenceKind===(session?'live-redirect-destination':'live-route')&&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
  &&!!p&&p.path==='/s-33'&&S33_MEASURED_STATES.includes(p.state)&&row.state===`S-33-${p.state}`&&row.designState===p.state
  &&p.requestSequenceVerified===true&&p.serverConfirmationVerified===true&&p.holdAuthorityVerified===true&&p.paymentAuthorityVerified===true
  &&(!session||p.destination==='/s-03'&&p.sessionCleared===true&&p.httpStatus===401);
}
