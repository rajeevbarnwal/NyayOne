// Independent constants avoid reference/continuation import cycles.
export const S35_MEASURED_STATES=Object.freeze(["loading", "list", "past", "list-empty", "list-error", "detail", "detail-error", "reschedule", "reschedule-closed", "reschedule-conflict", "cancel-confirm", "cancel-failed", "attendance", "dispute", "disputed", "review", "review-invalid", "review-moderation", "review-edit", "review-window-closed", "prejoin", "prejoin-ready", "prejoin-denied", "join-refused", "video-disabled", "room", "rate-limited", "cancelled-full-refund", "cancelled-no-auto-refund", "refund-pending", "refund-failed", "cancel-stale", "cancel-started", "cancel-invalid", "prejoin-audio-only", "prejoin-no-device", "prejoin-busy", "prejoin-insecure", "prejoin-unsupported", "prejoin-failed", "room-connecting", "room-reconnecting", "room-failed", "room-token-expired", "room-leave-confirm", "left", "reschedule-unavailable", "attendance-pending", "attendance-confirmed", "attendance-refused", "attendance-resolved", "review-refused", "reschedule-wrong-tutor", "review-delete-confirm", "review-deleted", "review-delete-failed"]);
export function s35EvidenceScope(state){
 const gap=['refund-pending','refund-failed'].includes(state),left=state==='left';
 const room=['room','room-connecting','room-reconnecting','room-failed','room-token-expired','room-leave-confirm','left','join-refused'].includes(state);
 const view=left?'attendance':room?'room':['loading','list','past','list-empty','list-error','rate-limited'].includes(state)?'list':state.startsWith('reschedule')?'reschedule':state.startsWith('review')?'review':state.startsWith('attendance')||['dispute','disputed'].includes(state)?'attendance':state.startsWith('prejoin')||state==='video-disabled'?'prejoin':'manage';
 return {kind:gap?'live-capability-gap':left?'live-route-destination':'live-route',view,gap,media:room||state.startsWith('prejoin')};
}
export function hasS35LiveProof(row){
 if(row.screen!=='S-35')return true;
 const p=row.routeProof;
 if(!p||!S35_MEASURED_STATES.includes(p.state))return false;
 const scope=s35EvidenceScope(p.state);
 return row.evidenceKind===scope.kind&&p.view===scope.view
  &&(p.state!=='room-connecting'||row.mediaPhase==='retry-awaiting-server-admission-not-provider-connection')
  &&row.realBackendTested===false&&row.realMediaProviderTested===false
  &&(!scope.media||row.mediaEmulation==='synthetic-browser-devices-and-opt-in-deterministic-transport')
  &&(!scope.gap||(row.capabilityGap==='student-refund-settlement-status-unavailable'&&row.settlementStateObserved===false))
  &&row.syntheticServer===true&&row.navigationFrozen===false&&row.artificialDelay===false
  &&p.path==='/s-35'&&row.state===`S-35-${p.state}`&&row.designState===p.state
  &&p.terminalStateVerified===true&&p.requestSequenceVerified===true&&p.responseScenarioVerified===true&&p.sessionIdentityVerified===true&&p.capabilityLimitsDisclosed===true;
}
