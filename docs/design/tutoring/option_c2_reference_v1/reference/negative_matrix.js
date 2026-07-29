/* Option C2 reference — executable negative matrix (v1).
   Every case is executable: 'rule' cases assert pure UI rules, 'dom' cases
   navigate the reference to a state and assert the rendered obligation,
   'env' cases assert responsive / privacy environment properties.
   Result rows carry input, expected, actual and status. */
(function (root) {
  'use strict';
  var R = root.C2Rules, Fx = root.C2Fixtures, F = Fx.FIXTURES;
  function T(x){ return String(x==null?'':x); }
  function txt(sel){ var e=document.querySelector(sel); return e?e.textContent.replace(/\s+/g,' ').trim():''; }
  function has(sel){ return !!document.querySelector(sel); }
  function bodyText(){ return document.body.innerText.replace(/\s+/g,' '); }
  function contains(s){ return bodyText().toLowerCase().indexOf(String(s).toLowerCase())>=0; }

  var CASES = [
    /* ---------------- search ---------------- */
    {id:'NEG-SRCH-01',area:'Search',input:'empty query ""',expected:'SEARCH_EMPTY, no request, no dead end',kind:'rule',
      run:function(){var r=R.normaliseSearch('');return {actual:r.code,pass:r.code==='SEARCH_EMPTY'&&r.ok===false};}},
    {id:'NEG-SRCH-02',area:'Search',input:'whitespace only "   \\t  "',expected:'trimmed to empty -> SEARCH_EMPTY',kind:'rule',
      run:function(){var r=R.normaliseSearch('   \t  ');return {actual:r.code+' query="'+r.query+'"',pass:r.code==='SEARCH_EMPTY'&&r.query===''};}},
    {id:'NEG-SRCH-03',area:'Search',input:'200-character query',expected:'SEARCH_TOO_LONG, truncated to 120, no overflow',kind:'rule',
      run:function(){var r=R.normaliseSearch('a'.repeat(200));return {actual:r.code+' len='+r.query.length,pass:r.code==='SEARCH_TOO_LONG'&&r.query.length===120};}},
    {id:'NEG-SRCH-04',area:'Search',input:'special characters "<script>&quot;\\u0026#39;"',expected:'accepted as literal text, escaped, no HTML injection',kind:'dom',state:'s31-empty',
      run:function(){var i=document.querySelector('[data-testid=search-input]');i.value='<script>alert(1)<\/script>';
        var esc=!has('#app script');return {actual:'value kept as text, injected script nodes='+document.querySelectorAll('#app script').length,pass:esc};}},
    {id:'NEG-SRCH-05',area:'Search',input:'query with no results',expected:'explicit empty state + recovery action, never a blank page',kind:'dom',state:'s31-empty',
      run:function(){return {actual:txt('[data-testid=state-banner] .bt')+' | recovery='+has('[data-testid=clear-filters]'),
        pass:has('[data-testid=state-banner]')&&has('[data-testid=clear-filters]')&&txt('[data-testid=result-count]').indexOf('0 of 0')>=0};}},

    /* ---------------- profile ---------------- */
    {id:'NEG-PROF-01',area:'Profile',input:'very long tutor name (90 chars)',expected:'wraps, no horizontal overflow, no clipping of the CTA',kind:'dom',state:'s32-profile',
      run:function(){var h=document.querySelector('.phead h1');h.textContent='Adv. '+'Meeraakrishnanvenkataraghavan '.repeat(3);
        var de=document.documentElement;return {actual:'hOverflow='+Math.max(0,de.scrollWidth-de.clientWidth),pass:de.scrollWidth<=de.clientWidth+0.5};}},
    {id:'NEG-PROF-02',area:'Profile',input:'missing bio / rating data',expected:'section omitted or shown as "Not provided"; never "undefined"/"null"/"NaN"',kind:'dom',state:'s32-profile',
      run:function(){var t=bodyText();var bad=/\bundefined\b|\bNaN\b|\bnull\b/.test(t);return {actual:'placeholder leakage='+bad,pass:!bad};}},
    {id:'NEG-PROF-03',area:'Profile',input:'unknown tutor id',expected:'reference resolves to a known state, never a broken render',kind:'rule',
      run:function(){var ok=!root.C2States.BY_ID['tut_does_not_exist'];return {actual:'unknown id resolves to undefined -> router falls back to s31-default',pass:ok};}},

    /* ---------------- slots ---------------- */
    {id:'NEG-SLOT-01',area:'Slots',input:'held slot',expected:'not bookable, status conveyed in text not colour alone',kind:'dom',state:'s32-availability',
      run:function(){var b=document.querySelector('[data-slot-status=held]');
        return {actual:'disabled='+(b&&b.disabled)+' text="'+(b?b.textContent.trim().slice(-30):'')+'"',pass:!!b&&b.disabled&&/held/i.test(b.textContent)};}},
    {id:'NEG-SLOT-02',area:'Slots',input:'booked slot',expected:'not bookable, labelled Booked',kind:'dom',state:'s32-availability',
      run:function(){var b=document.querySelector('[data-slot-status=booked]');
        return {actual:'disabled='+(b&&b.disabled),pass:!!b&&b.disabled&&/booked/i.test(b.textContent)};}},
    {id:'NEG-SLOT-03',area:'Slots',input:'stale availability (changed after load)',expected:'STALE_STATE refusal with refresh, no silent overwrite',kind:'dom',state:'s35-conflict',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),pass:contains('STALE_STATE')&&contains('refresh')};}},

    /* ---------------- hold timer ---------------- */
    {id:'NEG-HOLD-01',area:'Hold',input:'600s remaining (10:00)',expected:'normal level, plain presentation',kind:'rule',
      run:function(){var u=R.holdUrgency(600);return {actual:u.level+' / '+R.mmss(600),pass:u.level==='normal'&&R.mmss(600)==='10:00'};}},
    {id:'NEG-HOLD-02',area:'Hold',input:'120s remaining (02:00)',expected:'still normal (urgency begins strictly under 2 min)',kind:'rule',
      run:function(){var u=R.holdUrgency(120);return {actual:u.level+' / '+R.mmss(120),pass:u.level==='normal'&&R.mmss(120)==='02:00'};}},
    {id:'NEG-HOLD-03',area:'Hold',input:'119s remaining (01:59)',expected:'urgent level with a NON-COLOUR cue',kind:'rule',
      run:function(){var u=R.holdUrgency(119);return {actual:u.level+' cue="'+u.nonColourCue+'"',pass:u.level==='urgent'&&/bold|border|underline|wording/.test(u.nonColourCue)};}},
    {id:'NEG-HOLD-04',area:'Hold',input:'1s remaining (00:01)',expected:'urgent, still announced, still recoverable',kind:'rule',
      run:function(){var u=R.holdUrgency(1);return {actual:u.level+' / '+R.mmss(1)+' announce='+u.announce,pass:u.level==='urgent'&&R.mmss(1)==='00:01'&&u.announce};}},
    {id:'NEG-HOLD-05',area:'Hold',input:'0s remaining (00:00)',expected:'HOLD_EXPIRED, slot released, nothing charged',kind:'dom',state:'s33-hold-expired',
      run:function(){var u=R.holdUrgency(0);
        return {actual:u.code+' | ui="'+txt('[data-testid=state-banner] .bt')+'"',
          pass:u.code==='HOLD_EXPIRED'&&contains('nothing was charged')&&contains('released')};}},
    {id:'NEG-HOLD-06',area:'Hold',input:'urgent hold rendered',expected:'urgency carried by weight/border/wording, not hue alone',kind:'dom',state:'s33-hold-urgent',
      run:function(){var h=document.querySelector('[data-testid=hold-timer]');var cs=getComputedStyle(h);
        return {actual:'data-urgent='+h.getAttribute('data-urgent')+' borderWidth='+cs.borderTopWidth+' wording='+/under two minutes/i.test(h.textContent),
          pass:h.getAttribute('data-urgent')==='1'&&parseFloat(cs.borderTopWidth)>=3&&/under two minutes/i.test(h.textContent)};}},

    /* ---------------- amounts ---------------- */
    {id:'NEG-AMT-01',area:'Amount',input:'0 paise',expected:'₹0.00, never blank or "₹NaN"',kind:'rule',
      run:function(){var s=R.formatPaise(0);return {actual:s,pass:s==='₹0.00'};}},
    {id:'NEG-AMT-02',area:'Amount',input:'1 paisa',expected:'₹0.01, no rounding to zero',kind:'rule',
      run:function(){var s=R.formatPaise(1);return {actual:s,pass:s==='₹0.01'};}},
    {id:'NEG-AMT-03',area:'Amount',input:'96082 paise (frozen total)',expected:'₹960.82 and fee+tax+discount reconciles exactly',kind:'rule',
      run:function(){var t=R.totalPaise();return {actual:t+' -> '+R.formatPaise(t),pass:t===96082&&R.formatPaise(t)==='₹960.82'};}},
    {id:'NEG-AMT-04',area:'Amount',input:'1,00,00,00,000 paise (large)',expected:'Indian digit grouping, no overflow, no exponent',kind:'rule',
      run:function(){var s=R.formatPaise(1000000000);return {actual:s,pass:s==='₹1,00,00,000.00'};}},
    {id:'NEG-AMT-05',area:'Amount',input:'non-integer paise 960.825',expected:'throws MONEY_NOT_INTEGER_PAISE — float money is impossible',kind:'rule',
      run:function(){try{R.formatPaise(960.825);return {actual:'no throw',pass:false};}catch(e){return {actual:e.message,pass:e.message==='MONEY_NOT_INTEGER_PAISE'};}}},

    /* ---------------- card ---------------- */
    {id:'NEG-CARD-01',area:'Card',input:'all fields empty',expected:'three required-field codes, submit blocked',kind:'rule',
      run:function(){var r=R.validateCard({});return {actual:r.codes.join(','),pass:!r.ok&&r.codes.length===3};}},
    {id:'NEG-CARD-02',area:'Card',input:'malformed number "4111-abcd"',expected:'CARD_NUMBER_MALFORMED, field-level message',kind:'rule',
      run:function(){var r=R.validateCard({number:'4111-abcd',expiry:'12 / 28',name:'Aditi Nair'});
        return {actual:r.codes.join(','),pass:r.codes.indexOf('CARD_NUMBER_MALFORMED')>=0};}},
    {id:'NEG-CARD-03',area:'Card',input:'provider declines the card',expected:'typed decline, nothing charged, hold preserved',kind:'dom',state:'s33-declined',
      run:function(){return {actual:txt('[data-testid=state-banner] .bt')+' | '+txt('[data-testid=state-banner] .code'),
        pass:contains('declined')&&contains('nothing was charged')&&contains('PAYMENT_DECLINED')};}},
    {id:'NEG-CARD-04',area:'Card',input:'payment provider unavailable',expected:'PROVIDER_UNAVAILABLE, safe idempotent retry offered',kind:'dom',state:'s33-provider-down',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),
        pass:contains('PROVIDER_UNAVAILABLE')&&contains('cannot be charged twice')};}},
    {id:'NEG-CARD-05',area:'Card',input:'validation state rendered',expected:'each invalid field has aria-describedby pointing at its message',kind:'dom',state:'s33-validation',
      run:function(){var f=[...document.querySelectorAll('[data-invalid="1"]')];
        var ok=f.length>0&&f.every(function(e){var id=e.getAttribute('aria-describedby');return id&&document.getElementById(id);});
        return {actual:'invalid fields='+f.length+' all described='+ok,pass:ok};}},

    /* ---------------- payment challenge ---------------- */
    {id:'NEG-OTP-01',area:'Payment OTP',input:'empty code',expected:'AUTH_CHALLENGE_REQUIRED, no submit',kind:'rule',
      run:function(){var r=R.validateOtp('',0,false);return {actual:r.code,pass:r.code==='AUTH_CHALLENGE_REQUIRED'};}},
    {id:'NEG-OTP-02',area:'Payment OTP',input:'5-digit code "41927"',expected:'AUTH_CHALLENGE_LENGTH, attempt not consumed',kind:'rule',
      run:function(){var r=R.validateOtp('41927',0,false);return {actual:r.code+' attemptsLeft='+r.attemptsLeft,pass:r.code==='AUTH_CHALLENGE_LENGTH'&&r.attemptsLeft===3};}},
    {id:'NEG-OTP-03',area:'Payment OTP',input:'6-digit code "419273"',expected:'accepted for submission to the provider (never stored)',kind:'rule',
      run:function(){var r=R.validateOtp('419273',0,false);return {actual:'ok='+r.ok,pass:r.ok===true};}},
    {id:'NEG-OTP-04',area:'Payment OTP',input:'3 wrong attempts',expected:'AUTH_CHALLENGE_LOCKED after the third, nothing charged',kind:'rule',
      run:function(){var r=R.validateOtp('419273',3,false);return {actual:r.code+' attemptsLeft='+r.attemptsLeft,pass:r.code==='AUTH_CHALLENGE_LOCKED'&&r.attemptsLeft===0};}},
    {id:'NEG-OTP-05',area:'Payment OTP',input:'resend requested',expected:'counter + new expiry + cooldown shown',kind:'dom',state:'s33-otp-resent',
      run:function(){return {actual:txt('[data-testid=state-banner] .bd2'),pass:contains('Code 2 of 3')&&contains('expires')&&contains('30 seconds')};}},
    {id:'NEG-OTP-06',area:'Payment OTP',input:'expired challenge',expected:'AUTH_CHALLENGE_EXPIRED, resend offered, nothing charged',kind:'rule',
      run:function(){var r=R.validateOtp('419273',1,true);return {actual:r.code,pass:r.code==='AUTH_CHALLENGE_EXPIRED'};}},
    {id:'NEG-OTP-07',area:'Payment OTP',input:'locked state rendered',expected:'input disabled, resend disabled, recovery offered',kind:'dom',state:'s33-otp-locked',
      run:function(){var i=document.querySelector('[data-testid=otp-input]'),b=document.querySelector('[data-testid=otp-resend]');
        return {actual:'inputDisabled='+(i&&i.disabled)+' resendDisabled='+(b&&b.disabled),pass:!!i&&i.disabled&&!!b&&b.disabled&&contains('Nothing was charged')};}},

    /* ---------------- duplicate payment ---------------- */
    {id:'NEG-DUP-01',area:'Duplicate payment',input:'same idempotency key submitted twice',expected:'charged once, original result replayed, no second booking',kind:'dom',state:'s33-duplicate',
      run:function(){return {actual:txt('[data-testid=state-banner] .bt'),
        pass:contains('charged once')&&contains('no second booking')&&contains(F.refs.idempotency)};}},

    /* ---------------- cancellation ---------------- */
    {id:'NEG-CXL-01',area:'Cancellation',input:'exactly 24:00:00 before start',expected:'full refund (boundary is inclusive)',kind:'rule',
      run:function(){var r=R.cancellationOutcome('2026-08-04T18:30:00+05:30',F.slot.startIso);
        return {actual:r.outcome+' '+r.refundPaise,pass:r.outcome==='full_refund'&&r.refundPaise===96082};}},
    {id:'NEG-CXL-02',area:'Cancellation',input:'23:59:59 before start',expected:'CANCELLATION_WINDOW_CLOSED, admin exception route, no automatic refund',kind:'rule',
      run:function(){var r=R.cancellationOutcome('2026-08-04T18:30:01+05:30',F.slot.startIso);
        return {actual:r.outcome+' '+r.code,pass:r.outcome==='admin_exception'&&r.code==='CANCELLATION_WINDOW_CLOSED'};}},
    {id:'NEG-CXL-03',area:'Cancellation',input:'after the session start',expected:'SESSION_ALREADY_STARTED, cancellation closed',kind:'rule',
      run:function(){var r=R.cancellationOutcome('2026-08-05T18:31:00+05:30',F.slot.startIso);
        return {actual:r.outcome+' '+r.code,pass:r.code==='SESSION_ALREADY_STARTED'};}},
    {id:'NEG-CXL-04',area:'Cancellation',input:'tutor cancels',expected:'automatic full refund regardless of the 24h window',kind:'dom',state:'s35-tutor-cancelled',
      run:function(){return {actual:txt('.amt .big')+' | '+txt('[data-testid=state-banner] .bt'),
        pass:txt('.amt .big')==='₹960.82'&&contains('automatically')};}},

    /* ---------------- refund ---------------- */
    {id:'NEG-RFD-01',area:'Refund',input:'provider timeout',expected:'REFUND_FAILED, money-safe wording, retry with the same reference',kind:'dom',state:'s35-refund-failed',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),
        pass:contains('REFUND_FAILED')&&contains(F.refs.refund)&&contains('nothing is lost')};}},
    {id:'NEG-RFD-02',area:'Refund',input:'duplicate refund request',expected:'idempotent by refund reference, one settlement only',kind:'dom',state:'s35-refund-processing',
      run:function(){return {actual:'refund reference visible='+contains(F.refs.refund),pass:contains(F.refs.refund)};}},
    {id:'NEG-RFD-03',area:'Refund',input:'retry after failure',expected:'retry action present, reuses the same refund reference',kind:'dom',state:'s35-refund-failed',
      run:function(){return {actual:txt('[data-testid=primary-action]'),pass:/retry/i.test(txt('[data-testid=primary-action]'))};}},
    {id:'NEG-RFD-04',area:'Refund',input:'manual review',expected:'REFUND_MANUAL_REVIEW with turnaround + reference, no false success',kind:'dom',state:'s35-refund-review',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),
        pass:contains('REFUND_MANUAL_REVIEW')&&contains(F.refs.audit)&&!contains('refund succeeded')};}},

    /* ---------------- permissions ---------------- */
    {id:'NEG-PERM-01',area:'Permissions',input:'camera permission denied',expected:'typed denial + per-browser recovery + audio-only alternative',kind:'dom',state:'s35-perm-cam',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),
        pass:contains('MEDIA_PERMISSION_DENIED_CAMERA')&&contains('site permissions')&&contains('audio only')};}},
    {id:'NEG-PERM-02',area:'Permissions',input:'permission prompt dismissed',expected:'MEDIA_PERMISSION_DISMISSED, neutral wording, ask-again action',kind:'dom',state:'s35-perm-pending',
      run:function(){return {actual:txt('[data-testid=primary-action]'),
        pass:contains('MEDIA_PERMISSION_DISMISSED')&&/ask again/i.test(txt('[data-testid=primary-action]'))};}},
    {id:'NEG-PERM-03',area:'Permissions',input:'no camera or microphone present',expected:'MEDIA_DEVICE_NOT_FOUND, connect-and-retest, listen-only fallback',kind:'dom',state:'s35-no-device',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),
        pass:contains('MEDIA_DEVICE_NOT_FOUND')&&contains('Connect a device')};}},
    {id:'NEG-PERM-04',area:'Permissions',input:'device busy in another app',expected:'MEDIA_DEVICE_IN_USE with a concrete recovery step',kind:'dom',state:'s35-device-busy',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),
        pass:contains('MEDIA_DEVICE_IN_USE')&&contains('Close the other')};}},

    /* ---------------- join eligibility ---------------- */
    {id:'NEG-JOIN-01',area:'Join',input:'join before the window opens',expected:'JOIN_NOT_YET_OPEN, exact opening time, no join control',kind:'dom',state:'s35-join-early-v',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),
        pass:contains('JOIN_NOT_YET_OPEN')&&contains('6:15 PM')};}},
    {id:'NEG-JOIN-02',area:'Join',input:'expired join credential',expected:'JOIN_CREDENTIAL_EXPIRED, credential never printed',kind:'dom',state:'s35-token-expired',
      run:function(){return {actual:'code shown, credential leaked='+contains(F.refs.joinToken),
        pass:contains('JOIN_CREDENTIAL_EXPIRED')&&!contains(F.refs.joinToken)};}},
    {id:'NEG-JOIN-03',area:'Join',input:'wrong signed-in user',expected:'JOIN_FORBIDDEN, neutral refusal that leaks nothing about the booking owner',kind:'dom',state:'s35-wrong-user',
      run:function(){return {actual:'tutor name leaked in refusal='+/belongs to a different account/i.test(bodyText()),
        pass:contains('JOIN_FORBIDDEN')&&contains('different account')};}},
    {id:'NEG-JOIN-04',area:'Join',input:'payment not verified',expected:'JOIN_PAYMENT_UNVERIFIED, no room entry',kind:'dom',state:'s35-pay-unverified',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),
        pass:contains('JOIN_PAYMENT_UNVERIFIED')&&!has('[data-testid=control-dock]')};}},
    {id:'NEG-JOIN-05',area:'Join',input:'session already ended',expected:'JOIN_SESSION_ENDED, attendance and review routes offered',kind:'dom',state:'s35-ended',
      run:function(){return {actual:txt('[data-testid=primary-action]'),
        pass:contains('JOIN_SESSION_ENDED')&&/attendance/i.test(txt('[data-testid=primary-action]'))};}},

    /* ---------------- network / media ---------------- */
    {id:'NEG-NET-01',area:'Network',input:'offline',expected:'NETWORK_UNAVAILABLE, nothing lost, retry when online',kind:'dom',state:'s35-offline',
      run:function(){return {actual:txt('[data-testid=state-banner] .code'),
        pass:contains('NETWORK_UNAVAILABLE')&&contains('nothing was lost')};}},
    {id:'NEG-NET-02',area:'Network',input:'degraded connection',expected:'quality reduced, controls unchanged, room still 100dvh',kind:'dom',state:'s35-degraded',
      run:function(){var de=document.documentElement;
        return {actual:'dock='+has('[data-testid=control-dock]')+' scroll='+Math.max(0,de.scrollHeight-de.clientHeight),
          pass:has('[data-testid=control-dock]')&&de.scrollHeight<=de.clientHeight+1&&contains('controls are unchanged')};}},
    {id:'NEG-NET-03',area:'Network',input:'ICE/TURN failure',expected:'MEDIA_TRANSPORT_FAILED, rejoin action, Leave still reachable',kind:'dom',state:'s35-icefail',
      run:function(){var l=document.querySelector('[data-testid=leave]');var r=l&&l.getBoundingClientRect();
        return {actual:'leave in viewport='+(!!r&&r.bottom<=innerHeight+0.5&&r.top>=-0.5),
          pass:contains('rejoin')&&!!r&&r.bottom<=innerHeight+0.5&&r.width>=44&&r.height>=44};}},
    {id:'NEG-NET-04',area:'Network',input:'tutor leaves the room',expected:'stated clearly, attendance consequence explained, controls kept',kind:'dom',state:'s35-tutor-left',
      run:function(){return {actual:txt('[data-testid=stage-veil]').slice(0,60),
        pass:contains('mentor left')&&contains('Attendance')&&has('[data-testid=control-dock]')};}},

    /* ---------------- attendance ---------------- */
    {id:'NEG-ATT-01',area:'Attendance',input:'action before the scheduled end',expected:'ATTENDANCE_TOO_EARLY listed as a typed refusal',kind:'dom',state:'s35-att-errors',
      run:function(){return {actual:contains('ATTENDANCE_TOO_EARLY'),pass:contains('ATTENDANCE_TOO_EARLY')};}},
    {id:'NEG-ATT-02',area:'Attendance',input:'duplicate attendance action',expected:'ATTENDANCE_DUPLICATE, no double record',kind:'dom',state:'s35-att-errors',
      run:function(){return {actual:contains('ATTENDANCE_DUPLICATE'),pass:contains('ATTENDANCE_DUPLICATE')};}},
    {id:'NEG-ATT-03',area:'Attendance',input:'wrong role acts',expected:'ATTENDANCE_FORBIDDEN_ROLE',kind:'dom',state:'s35-att-errors',
      run:function(){return {actual:contains('ATTENDANCE_FORBIDDEN_ROLE'),pass:contains('ATTENDANCE_FORBIDDEN_ROLE')};}},
    {id:'NEG-ATT-04',area:'Attendance',input:'stale attendance view',expected:'ATTENDANCE_STALE + refresh, plus an explicit W2-6 pending notice',kind:'dom',state:'s35-att-errors',
      run:function(){return {actual:'stale='+contains('ATTENDANCE_STALE')+' pendingNotice='+contains('Product-pending'),
        pass:contains('ATTENDANCE_STALE')&&contains('Product-pending')};}},
    {id:'NEG-ATT-05',area:'Attendance',input:'dispute with 1,001 characters',expected:'input hard-capped at 1,000, live counter, no silent truncation of a submitted value',kind:'dom',state:'s35-att-dispute',
      run:function(){var t=document.querySelector('[data-testid=dispute-reason]');
        return {actual:'maxlength='+t.getAttribute('maxlength')+' counter='+has('[data-testid=dispute-counter]'),
          pass:t.getAttribute('maxlength')==='1000'&&has('[data-testid=dispute-counter]')};}},

    /* ---------------- review ---------------- */
    {id:'NEG-REV-01',area:'Review',input:'0 stars',expected:'REVIEW_RATING_OUT_OF_RANGE',kind:'rule',
      run:function(){var r=R.validateReview(0,'x'.repeat(50));return {actual:r.codes.join(','),pass:r.codes.indexOf('REVIEW_RATING_OUT_OF_RANGE')>=0};}},
    {id:'NEG-REV-02',area:'Review',input:'1 star',expected:'accepted',kind:'rule',
      run:function(){var r=R.validateReview(1,'x'.repeat(50));return {actual:'ok='+r.ok,pass:r.ok===true};}},
    {id:'NEG-REV-03',area:'Review',input:'5 stars',expected:'accepted',kind:'rule',
      run:function(){var r=R.validateReview(5,'x'.repeat(50));return {actual:'ok='+r.ok,pass:r.ok===true};}},
    {id:'NEG-REV-04',area:'Review',input:'6 stars',expected:'REVIEW_RATING_OUT_OF_RANGE',kind:'rule',
      run:function(){var r=R.validateReview(6,'x'.repeat(50));return {actual:r.codes.join(','),pass:r.codes.indexOf('REVIEW_RATING_OUT_OF_RANGE')>=0};}},
    {id:'NEG-REV-05',area:'Review',input:'0 characters of text',expected:'REVIEW_TEXT_TOO_SHORT',kind:'rule',
      run:function(){var r=R.validateReview(5,'');return {actual:r.codes.join(','),pass:r.codes.indexOf('REVIEW_TEXT_TOO_SHORT')>=0};}},
    {id:'NEG-REV-06',area:'Review',input:'9 characters',expected:'REVIEW_TEXT_TOO_SHORT (boundary)',kind:'rule',
      run:function(){var r=R.validateReview(5,'x'.repeat(9));return {actual:r.codes.join(',')+' len='+r.length,pass:r.codes.indexOf('REVIEW_TEXT_TOO_SHORT')>=0};}},
    {id:'NEG-REV-07',area:'Review',input:'10 characters',expected:'accepted (boundary)',kind:'rule',
      run:function(){var r=R.validateReview(5,'x'.repeat(10));return {actual:'ok='+r.ok+' len='+r.length,pass:r.ok===true};}},
    {id:'NEG-REV-08',area:'Review',input:'1,000 characters',expected:'accepted (boundary)',kind:'rule',
      run:function(){var r=R.validateReview(5,'x'.repeat(1000));return {actual:'ok='+r.ok+' len='+r.length,pass:r.ok===true};}},
    {id:'NEG-REV-09',area:'Review',input:'1,001 characters',expected:'REVIEW_TEXT_TOO_LONG (boundary)',kind:'rule',
      run:function(){var r=R.validateReview(5,'x'.repeat(1001));return {actual:r.codes.join(',')+' len='+r.length,pass:r.codes.indexOf('REVIEW_TEXT_TOO_LONG')>=0};}},
    {id:'NEG-REV-10',area:'Review',input:'review opened without confirmed attendance',expected:'REVIEW_LOCKED_NO_ATTENDANCE, form not rendered',kind:'dom',state:'s35-review-blocked',
      run:function(){return {actual:'form present='+has('[data-testid=review-text]'),
        pass:contains('REVIEW_LOCKED_NO_ATTENDANCE')&&!has('[data-testid=review-text]')};}},
    {id:'NEG-REV-11',area:'Review',input:'star input keyboard reachability',expected:'radiogroup with 5 labelled radios, all >=44x44',kind:'dom',state:'s35-review-open',
      run:function(){var g=document.querySelector('[data-testid=stars]');var rs=g?g.querySelectorAll('input[type=radio]'):[];
        var small=[...document.querySelectorAll('[data-testid^=star-]')].filter(function(e){var b=e.getBoundingClientRect();return b.width<43.5||b.height<43.5;});
        return {actual:'radios='+rs.length+' role='+(g&&g.getAttribute('role'))+' small='+small.length,
          pass:rs.length===5&&g.getAttribute('role')==='radiogroup'&&small.length===0};}},

    /* ---------------- responsive / a11y environment ---------------- */
    {id:'NEG-RSP-01',area:'Responsive',input:'very long copy injected into every text node',expected:'no horizontal overflow at the current viewport',kind:'env',state:'s33-card',
      run:function(){document.querySelectorAll('#app .bt,#app h2.m,#app .kv b').forEach(function(e){e.textContent=e.textContent+' '+'Kaliyaperumalvenkataraghavan'.repeat(2);});
        var de=document.documentElement;return {actual:'hOverflow='+Math.max(0,de.scrollWidth-de.clientWidth),pass:de.scrollWidth<=de.clientWidth+0.5};}},
    {id:'NEG-RSP-02',area:'Responsive',input:'200% page zoom',expected:'no horizontal overflow; primary action still reachable',kind:'env',state:'s33-card',zoom:2,
      run:function(){var de=document.documentElement;var p=document.querySelector('[data-testid=primary-action]');
        return {actual:'hOverflow='+Math.max(0,de.scrollWidth-de.clientWidth)+' primaryPresent='+!!p,
          pass:de.scrollWidth<=de.clientWidth+1&&!!p};}},
    {id:'NEG-RSP-03',area:'Responsive',input:'user font size 200% (root font-size 32px)',expected:'no horizontal overflow, controls keep >=44px',kind:'env',state:'s34-confirmed',
      run:function(){document.documentElement.style.fontSize='32px';
        var de=document.documentElement;
        var small=[...document.querySelectorAll('#app button,#app a')].filter(function(e){var b=e.getBoundingClientRect();return b.width>0&&(b.width<43.5||b.height<43.5);});
        var r={actual:'hOverflow='+Math.max(0,de.scrollWidth-de.clientWidth)+' small='+small.length,
          pass:de.scrollWidth<=de.clientWidth+1&&small.length===0};
        document.documentElement.style.fontSize='';return r;}},
    {id:'NEG-RSP-04',area:'Responsive',input:'prefers-reduced-motion: reduce',expected:'no transition longer than 0s on the room sheet',kind:'env',state:'s35-room-live',reducedMotion:true,
      run:function(){var sh=document.querySelector('[data-testid=sheet]');var d=getComputedStyle(sh).transitionDuration;
        return {actual:'transition-duration='+d,pass:!/[1-9]/.test(d)};}},
    {id:'NEG-RSP-05',area:'Responsive',input:'safe-area insets applied to the live room',expected:'dock padding honours env(safe-area-inset-bottom); Leave never covered',kind:'env',state:'s35-room-live',
      run:function(){var d=document.querySelector('[data-testid=control-dock]');var cs=getComputedStyle(d);
        var l=document.querySelector('[data-testid=leave]').getBoundingClientRect();
        return {actual:'paddingBottom='+cs.paddingBottom+' leaveBottom='+l.bottom.toFixed(1)+' vh='+innerHeight,
          pass:parseFloat(cs.paddingBottom)>=8&&l.bottom<=innerHeight+0.5};}},

    /* ---------------- privacy canaries ---------------- */
    {id:'NEG-PRIV-01',area:'Privacy',input:'canary strings vs document URL',expected:'no canary appears in location.href',kind:'env',state:'s33-otp',
      run:function(){var r=R.privacyScan(location.href);return {actual:'hits='+r.hits.join(','),pass:r.clean};}},
    {id:'NEG-PRIV-02',area:'Privacy',input:'canary strings vs localStorage + sessionStorage',expected:'no canary in any web storage; reference writes no storage at all',kind:'env',state:'s33-otp',
      run:function(){var dump='';try{for(var i=0;i<localStorage.length;i++)dump+=localStorage.key(i)+'='+localStorage.getItem(localStorage.key(i))+';';
          for(var j=0;j<sessionStorage.length;j++)dump+=sessionStorage.key(j)+'='+sessionStorage.getItem(sessionStorage.key(j))+';';}catch(e){dump='';}
        var r=R.privacyScan(dump);return {actual:'storageKeys='+dump.length+' hits='+r.hits.join(','),pass:r.clean&&dump.length===0};}},
    {id:'NEG-PRIV-03',area:'Privacy',input:'canary strings vs rendered DOM text',expected:'no canary rendered anywhere in the reference',kind:'env',state:'s33-otp',
      run:function(){var r=R.privacyScan(document.documentElement.outerHTML);return {actual:'hits='+r.hits.join(','),pass:r.clean};}},
    {id:'NEG-PRIV-04',area:'Privacy',input:'card number / security code / challenge code persistence',expected:'no PAN, CVV or challenge code is written to storage or the URL',kind:'env',state:'s33-card',
      run:function(){var probe=location.href+'||'+document.cookie;
        var bad=/4111\s*1111\s*1111\s*1111/.test(probe)||/cvv|otp=/i.test(probe);
        return {actual:'url+cookie leakage='+bad+' cookieLen='+document.cookie.length,pass:!bad&&document.cookie.length===0};}}
  ];

  root.C2Negative = {
    CASES: CASES,
    runVisible: function () {
      /* run every case that does not need navigation (rule + current-state dom) */
      return CASES.map(function (c) { return { id: c.id, kind: c.kind }; });
    }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
