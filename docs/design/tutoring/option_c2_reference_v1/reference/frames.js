/* Option C2 reference — frame renderers (v1).
   Seven layout families cover all 82 states. Every family is rendered
   full-page at the real browser viewport: there is no device-bezel wrapper,
   so 100dvh, sticky, safe-area and scroll measurements are honest. */
(function (root) {
  'use strict';
  var F = root.C2Fixtures.FIXTURES, inr = root.C2Fixtures.inr;

  var I = {
    search:'<circle class="s" cx="10.5" cy="10.5" r="6.2"/><path class="s" d="M15.5 15.5 21 21"/>',
    chev:'<path class="s" d="M6 9.5 12 15.5 18 9.5"/>',
    lock:'<rect class="s" x="6" y="10.5" width="12" height="9" rx="2.5"/><path class="s" d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    cal:'<rect class="s" x="4" y="5.5" width="16" height="15" rx="3"/><path class="s" d="M8 3.5v4M16 3.5v4"/>',
    timer:'<circle class="s" cx="12" cy="13.5" r="7"/><path class="s" d="M12 10.5v3l2 2M9.5 3.5h5"/>',
    check:'<path class="s" d="m8.5 12.2 2.4 2.4 4.6-4.8"/><circle class="s" cx="12" cy="12" r="9"/>',
    join:'<rect class="s" x="3.5" y="6.5" width="12.5" height="11" rx="3"/><path class="s" d="m16 10.5 4.5-2.5v8L16 13.5"/>',
    leave:'<path class="s" d="M13 4.5H6.5A1.5 1.5 0 0 0 5 6v12a1.5 1.5 0 0 0 1.5 1.5H13M16 8.5 19.5 12 16 15.5M19.5 12H9.5"/>',
    mic:'<rect class="s" x="9.4" y="4" width="5.2" height="10" rx="2.6"/><path class="s" d="M6 11.5a6 6 0 0 0 12 0M12 17.5V20"/>',
    micOff:'<rect class="s" x="9.4" y="4" width="5.2" height="10" rx="2.6"/><path class="s" d="M4.5 4.5l15 15M12 17.5V20M6 11.5a6 6 0 0 0 9.7 4.7"/>',
    cam:'<rect class="s" x="3.5" y="6.5" width="12.5" height="11" rx="3"/><path class="s" d="m16 10.5 4.5-2.5v8L16 13.5"/>',
    camOff:'<rect class="s" x="3.5" y="6.5" width="12.5" height="11" rx="3"/><path class="s" d="m16 10.5 4.5-2.5v8L16 13.5M3.5 4.5l17 15"/>',
    dev:'<rect class="s" x="3.5" y="5" width="13" height="9.5" rx="2"/><path class="s" d="M7.5 18h5"/><rect class="s" x="15.5" y="10" width="5" height="8.5" rx="1.5"/>',
    info:'<circle class="s" cx="12" cy="12" r="9"/><path class="s" d="M12 11v5.5M12 8v.4"/>',
    warn:'<path class="s" d="M12 4.5 21 19.5H3z"/><path class="s" d="M12 10v4M12 16.6v.4"/>',
    copy:'<rect class="s" x="8.5" y="8.5" width="11" height="11" rx="2.5"/><path class="s" d="M6 15H5.5A1.5 1.5 0 0 1 4 13.5v-8A1.5 1.5 0 0 1 5.5 4h8A1.5 1.5 0 0 1 15 5.5V6"/>',
    dl:'<path class="s" d="M12 4.5V14m-3.5-3 3.5 3.5 3.5-3.5M5 17.5v1A1.5 1.5 0 0 0 6.5 20h11a1.5 1.5 0 0 0 1.5-1.5v-1"/>',
    share:'<path class="s" d="M12 14V4.5M8.5 7.5 12 4l3.5 3.5M6 12v6.5A1.5 1.5 0 0 0 7.5 20h9a1.5 1.5 0 0 0 1.5-1.5V12"/>',
    refund:'<circle class="s" cx="12" cy="12" r="7.5"/><path class="s" d="M9.2 9h5.6M9.2 11.6h5.6M9.6 9c2.6 0 3.4 1 3.4 2.2 0 1.4-1.1 2.2-2.8 2.2H9.6l3.4 3.6"/>',
    min:'<path class="s" d="M6 12h12"/>',
    move:'<path class="s" d="M12 4.5v15M4.5 12h15M9.5 7.5 12 5l2.5 2.5M9.5 16.5 12 19l2.5-2.5M7.5 9.5 5 12l2.5 2.5M16.5 9.5 19 12l-2.5 2.5"/>',
    star:'<path class="s" d="m12 4.5 2.4 5 5.4.7-3.9 3.8.9 5.4-4.8-2.6-4.8 2.6.9-5.4L4.2 10.2l5.4-.7z"/>',
    close:'<path class="s" d="M6 6l12 12M18 6 6 18"/>'
  };
  function ic(n, cls){ return '<svg class="ic '+(cls||'')+'" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'+(I[n]||'')+'</svg>'; }
  function esc(t){ return String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
  function por(bg,fg,acc){ return '<svg viewBox="0 0 100 100" aria-hidden="true" focusable="false"><rect width="100" height="100" fill="'+bg+'"/><circle cx="50" cy="42" r="20" fill="'+fg+'"/><path d="M18 84c7-19 17-28 32-28s25 9 32 28z" fill="'+fg+'"/>'+(acc?'<path d="M29 40c0-13 9-22 21-22s21 9 21 22" fill="none" stroke="'+acc+'" stroke-width="4.5" stroke-linecap="round"/>':'')+'</svg>'; }
  function tbar(id){ return '<header class="tbar"><span class="wm"><i>&sect;</i> LegalSaathi</span><span style="flex:1"></span><span class="sid" data-testid="screen-id">'+esc(id)+'</span></header>'; }
  function banner(tone,title,body,code){
    return '<div class="banner '+tone+'" role="'+(tone==='err'?'alert':'status')+'" data-testid="state-banner">'+
      ic(tone==='err'||tone==='warn'?'warn':tone==='ok'?'check':'info')+
      '<div style="min-width:0"><div class="bt">'+esc(title)+'</div>'+(body?'<div class="bd2">'+esc(body)+'</div>':'')+
      (code?'<code class="code">'+esc(code)+'</code>':'')+'</div></div>';
  }
  function typedCode(st){
    var t = st.typedError||'';
    if(!t || t.indexOf('NONE')===0) return '';
    return 'typed error: '+t;
  }

  /* ============================ F1 list — S-31 ============================ */
  function tutcard(t, grad, lead){
    return '<article class="tut" data-testid="tutor-card"><div class="idb" style="background:'+grad+'">'+
      '<span class="por">'+por('#e3f1e9','#0f6b47', lead?'#a8410c':'')+'</span>'+
      '<div style="min-width:0"><div class="nm">'+esc(t.name)+'</div><div class="rl">'+esc(t.practiceArea+' · '+t.city)+'</div></div></div>'+
      '<div class="bd"><div style="display:flex;gap:6px;flex-wrap:wrap">'+
        '<span class="chip g"><span class="d"></span>Verified</span>'+
        '<span class="chip gd"><span class="d"></span>'+esc(t.ratingValue+' · '+t.ratingCount+' reviews')+'</span></div>'+
      '<div class="chip t" style="align-self:flex-start"><span class="d"></span>Next: '+esc(F.slot.dateLabel.replace(', 2026',''))+' · '+esc(F.slot.timeLabel.split('–')[0])+' IST</div>'+
      '<div class="row"><span><span class="fee">'+inr(F.money.feePaise)+'</span>'+
        '<span style="display:block;font-size:11px;color:var(--mut);font-weight:700">'+F.slot.durationMin+' min · taxes at checkout</span></span>'+
        '<a class="btn '+(lead?'jade':'')+'" href="?state=s32-profile" data-testid="view-and-book">'+ic('cal')+'View &amp; book</a></div></div></article>';
  }
  function fList(st){
    var d=st.delta||{}, v=d.variant;
    var head='<div><div class="eyebrow">Digital chambers</div><h1 class="m">Learn live from practising advocates.</h1>'+
      '<p class="m" style="margin-top:5px">Verified mentors, fees upfront in rupees, free cancellation 24 hours ahead.</p></div>';
    var rails=['Arbitration','Criminal','Company','Family','Tax'].map(function(n,i){
      var on = (v==='filtered'? n==='Arbitration' : i===0);
      var col=['var(--jade)','var(--terra)','var(--indigo)','var(--gold)','var(--risk)'][i];
      return '<button class="rail" type="button" aria-pressed="'+on+'" style="color:'+col+'"><i style="background:'+col+'"></i>'+n+'</button>';
    }).join('');
    var shead='<div class="shead"><div class="spill">'+
      '<label for="q31" class="sr">Search mentors by subject, city or name</label>'+
      '<input id="q31" data-testid="search-input" type="search" placeholder="Search subject, city or name" value="'+(v==='empty'?'quantum notary':'')+'">'+
      '<button class="go" type="button" aria-label="Search mentors" data-testid="search-submit">'+ic('search')+'</button></div>'+
      '<div class="railwrap"><div class="rails" role="group" aria-label="Practice area">'+rails+'</div></div></div>';
    var list;
    if(v==='empty'){
      list = banner('info','No mentors match that search','Nothing matched your search in this practice area. Clear the filter or try a broader subject.', typedCode(st))+
        '<button class="btn block" type="button" data-testid="clear-filters">Clear filters and show all mentors</button>'+
        '<p class="m muted" data-testid="result-count">Showing 0 of 0 mentors</p>';
    } else if(v==='filtered'){
      list = '<p class="m muted" data-testid="result-count">Arbitration &amp; ADR · showing 1 of 1 mentor</p>'+
        tutcard(F.tutor,'linear-gradient(135deg,var(--jade),#0a4a32)',1)+
        '<button class="btn block" type="button" data-testid="clear-filters">Clear filter</button>';
    } else {
      list = tutcard(F.tutor,'linear-gradient(135deg,var(--jade),#0a4a32)',1)+
        tutcard(F.tutorAlt,'linear-gradient(135deg,var(--terra),#7d2f08)',0)+
        '<button class="btn block" type="button" data-testid="show-more">Show more mentors (2)</button>'+
        '<p class="m muted" data-testid="result-count">Showing 2 of 4 mentors · page 1</p>';
    }
    return '<main class="route" data-family="list">'+tbar(st.screen)+'<div class="body">'+head+shead+list+'</div></main>';
  }

  /* ==================== F2 profile — S-32 (controlled adaptation) ==================== */
  function fProfile(st){
    var t=F.tutor, av=(st.delta||{}).variant==='availability';
    var slots=[{id:F.slot.id,label:F.slot.label,status:'available'}].concat(F.slotsOther);
    var slotHtml=slots.map(function(s){
      var a=s.status==='available';
      var chip = a?'<span class="chip g"><span class="d"></span>Available</span>'
        : s.status==='held'?'<span class="chip t"><span class="d"></span>Held by another student</span>'
        : '<span class="chip r"><span class="d"></span>Booked</span>';
      return '<button class="slotbtn" type="button" data-testid="slot-'+esc(s.id)+'" data-slot-status="'+s.status+'"'+
        (a?' data-href="?state=s33-summary"':' disabled aria-disabled="true"')+'>'+
        '<span class="sl">'+esc(s.label)+'</span>'+chip+'</button>';
    }).join('');
    return '<main class="route" data-family="profile">'+tbar(st.screen)+'<div class="body">'+
      '<a class="btn" href="?state=s31-default" style="align-self:flex-start" data-testid="back-to-list">&lsaquo; All mentors</a>'+
      '<section class="phead"><div class="idb"><span class="por">'+por('#e3f1e9','#0f6b47','#a8410c')+'</span>'+
        '<div style="min-width:0"><h1>'+esc(t.name)+'</h1><div class="sub">'+esc(t.practiceArea+' · '+t.years+' yrs · '+t.city)+'</div></div></div>'+
        '<div class="bd"><div style="display:flex;gap:6px;flex-wrap:wrap">'+
          '<span class="chip g"><span class="d"></span>Verified mentor</span>'+
          '<span class="chip gd"><span class="d"></span>'+esc(t.ratingValue+' · '+t.ratingCount+' reviews')+'</span>'+
          '<span class="chip i"><span class="d"></span>'+esc(t.languages)+'</span></div>'+
        '<p class="m" data-testid="tutor-bio">'+esc(t.bio)+'</p>'+
        '<div class="feebox"><span><span class="fee">'+inr(F.money.feePaise)+'</span>'+
          '<span style="display:block;font-size:11px;color:var(--mut);font-weight:700">'+F.slot.durationMin+' min · taxes at checkout</span></span>'+
          '<a class="btn jade" href="?state=s32-availability" data-testid="see-availability">'+ic('cal')+'See availability</a></div></div></section>'+
      '<section aria-labelledby="availh"><h2 class="m" id="availh" style="margin-bottom:8px">Availability · '+esc(F.slot.timezoneLabel)+'</h2>'+
        '<div class="slots" data-testid="slot-list">'+slotHtml+'</div></section>'+
      (av?'<div class="edu"><h4>What happens next?</h4><p>Picking a slot holds it for 10 minutes while you pay. Nobody else can take it during your hold, and nothing is charged until the payment provider confirms.</p></div>':'')+
      '<details class="dis"'+(av?'':' open')+'><summary>'+ic('info')+'How sessions run'+ic('chev','cv')+'</summary><div class="dbody">'+
        '<p class="m" style="font-family:var(--font-display);font-style:italic;font-size:15px">&ldquo;'+esc(t.quote)+'&rdquo;</p>'+
        '<div class="kv"><span>Format</span><b>One-to-one video · '+F.slot.durationMin+' min</b></div>'+
        '<div class="kv"><span>Languages</span><b>'+esc(t.languages)+'</b></div>'+
        '<div class="kv"><span>Cancellation</span><b>Free until '+esc(F.policy.freeCancelCutoffLabel)+'</b></div></div></details>'+
      '<p class="svr">server-authoritative: slot status + booking hold (10-minute TTL) · immutable timezone-aware slot ids</p>'+
      '</div></main>';
  }

  /* ============================ F3 checkout — S-33 ============================ */
  function feeRows(){
    return '<div class="kv"><span>Mentoring fee · '+F.slot.durationMin+' min</span><b class="mono">'+inr(F.money.feePaise)+'</b></div>'+
      '<div class="kv"><span>'+esc(F.money.taxLabel)+'</span><b class="mono">'+inr(F.money.taxPaise)+'</b></div>'+
      '<div class="kv"><span>Discount · '+esc(F.money.discountCode)+'</span><b class="mono">'+inr(F.money.discountPaise)+'</b></div>'+
      '<div class="kv"><span><b>Total payable</b></span><b class="mono">'+inr(F.money.totalPaise)+'</b></div>';
  }
  function fCheckout(st){
    var d=st.delta||{}, v=d.variant||'summary', x=d.extra||'', body='', dock='';
    var head='<div><div class="eyebrow">Step 3 of 4 · secure payment</div>'+
      '<h2 class="m" style="margin-top:4px">'+esc(F.tutor.name)+'</h2>'+
      '<p class="m" style="font-size:12.5px">'+esc(F.slot.label)+' · '+esc(F.slot.timezoneLabel)+'</p></div>';
    var urgent=d.urgent?1:0, rem=d.holdRemaining||F.hold.defaultRemaining;
    var hold = (v==='hold'||v==='summary'||v==='card'||v==='otp') ?
      '<div class="holdsticky"><div class="hold" data-urgent="'+urgent+'" role="timer" aria-label="Slot hold time remaining '+rem+'" data-testid="hold-timer">'+
      ic('timer')+'<span class="t">'+esc(rem)+'</span>'+
      '<span style="font-size:12px;color:var(--ink2);flex:1">'+(urgent?'<b>Under two minutes left.</b> ':'')+'Seat held for you. If it ends, the slot is released and <b>nothing is charged</b>.</span></div></div>' : '';
    var protect='<details class="dis"><summary>'+ic('lock')+'How your payment is protected'+ic('chev','cv')+'</summary><div class="dbody">'+
      '<p class="m" style="font-size:12.5px">Card fields are <b>provider-hosted and tokenised</b>. LegalSaathi never sees or stores your card number, CVV or payment one-time code. Your session is created only after the provider confirms payment, never on a screen animation alone.</p></div></details>';
    var fees='<details class="dis"><summary>'+ic('info')+'View fee breakdown'+ic('chev','cv')+'</summary><div class="dbody">'+feeRows()+'</div></details>';
    var tail='<p class="m muted" data-testid="policy-tail">Cancelling later than '+esc(F.policy.freeCancelCutoffLabel)+' means no automatic refund — you can still request an admin exception.</p>';

    if(v==='summary'||v==='hold'){
      body=head+hold+'<span class="chip t" style="align-self:flex-start"><span class="d"></span>'+esc(F.payment.environmentLabel)+'</span>'+
        '<section class="dis" style="border-color:var(--line2)"><div class="dbody" style="padding-top:12px">'+feeRows()+'</div></section>'+protect+tail;
      dock=dockPay('Continue to payment');
    } else if(v==='card'){
      var invalid = x==='validation';
      body=head+hold+'<span class="chip t" style="align-self:flex-start"><span class="d"></span>'+esc(F.payment.environmentLabel)+'</span>'+
        (x==='testhelper'? banner('info','Test-card helper (non-production build only)','Fictional card 4111 1111 1111 1111, any future expiry, any 3-digit code. This helper is absent from production builds.') : '')+
        (invalid? banner('err','Check three fields before paying','Card number, expiry and name on card need attention. Nothing has been submitted or charged.', typedCode(st)) : '')+
        '<div class="fld"><label for="cn">Card number</label><div class="in hosted" id="cn" data-testid="card-number" data-invalid="'+(invalid?1:0)+'"'+(invalid?' aria-describedby="cn-e"':'')+'>'+esc(F.payment.cardNumberDisplay)+'</div>'+
          (invalid?'<span class="err" id="cn-e">'+ic('warn')+'Card number is not complete</span>':'')+'</div>'+
        '<div class="grid2"><div class="fld"><label for="ex">Expiry</label><div class="in hosted" id="ex" data-invalid="'+(invalid?1:0)+'"'+(invalid?' aria-describedby="ex-e"':'')+'>'+esc(F.payment.expiryDisplay)+'</div>'+
          (invalid?'<span class="err" id="ex-e">'+ic('warn')+'Expiry is in the past</span>':'')+'</div>'+
          '<div class="fld"><label for="cv">Security code</label><div class="in hosted" id="cv">'+esc(F.payment.cvvDisplay)+'</div></div></div>'+
        '<div class="fld"><label for="nmc">Name on card</label><div class="in" id="nmc" style="font-family:var(--font-body)" data-invalid="'+(invalid?1:0)+'"'+(invalid?' aria-describedby="nm-e"':'')+'>'+esc(F.payment.nameOnCard)+'</div>'+
          (invalid?'<span class="err" id="nm-e">'+ic('warn')+'Name on card is required</span>':'')+'</div>'+
        protect+fees+tail;
      dock=dockPay('Pay '+inr(F.money.totalPaise));
    } else if(v==='otp'){
      var msg = x==='otp-wrong' ? banner('err','That code did not match','2 of 3 attempts left. Your slot hold is still running and nothing has been charged.', typedCode(st))
        : x==='otp-locked' ? banner('err','Too many attempts','This authentication attempt is locked. Nothing was charged. Start a new payment attempt or choose another slot.', typedCode(st))
        : x==='otp-resent' ? banner('info','A new code was sent','Code 2 of 3 · expires in 4:30. You can request another in 30 seconds.')
        : banner('info','Your bank needs one more step','Enter the 6-digit code your bank sent. LegalSaathi never receives or stores this code.');
      body=head+hold+msg+
        '<div class="fld"><label for="otp">Authentication code</label>'+
          '<input class="in" id="otp" data-testid="otp-input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" '+
          (x==='otp-locked'?'disabled ':'')+'aria-describedby="otp-h" value=""></div>'+
        '<p class="m muted" id="otp-h">Attempts remaining: '+(x==='otp-locked'?'0':x==='otp-wrong'?'2':'3')+' of '+F.payment.otpMaxAttempts+' · code expires in 4:30</p>'+
        '<div class="dockrow"><button class="btn" type="button" data-testid="otp-resend"'+(x==='otp-locked'?' disabled':'')+'>Resend code</button>'+
        '<button class="btn" type="button" data-go="s33-cancelled">Cancel payment</button></div>'+protect;
      dock=dockPay(x==='otp-locked'?'Start a new attempt':'Verify and pay '+inr(F.money.totalPaise), x==='otp-locked');
    } else {
      var map={
        processing:['info','Waiting for your bank to confirm','Do not close this page. We create your session only when the payment provider confirms — never on an animation.'],
        success:['ok','Payment verified by the provider','A server-verified payment event was received. Your booking reference is '+F.refs.booking+'.'],
        declined:['err','Your card was declined','Nothing was charged. Your slot is still held — try another card before the hold ends.'],
        'provider-down':['err','The payment provider is unavailable','Nothing was charged. You can retry safely: the same idempotency key means you cannot be charged twice.'],
        cancelled:['warn','You cancelled before paying','Nothing was charged. The slot stays held until the timer ends.'],
        'hold-expired':['warn','Your hold expired and the slot was released','The 10 minutes ended. Nothing was charged. Pick another slot to continue.'],
        duplicate:['info','Already processed — charged once','This payment already completed. Your repeat submission safely returned the same result; no second booking was created.'],
        retry:['info','Safe to retry','Retrying reuses idempotency key '+F.refs.idempotency+'. You cannot be charged twice.']
      };
      var m=map[x]||['info','Payment status','—'];
      body=head+(x==='hold-expired'?'':hold)+banner(m[0],m[1],m[2],typedCode(st))+
        (x==='success'? '<div class="dis"><div class="dbody" style="padding-top:12px">'+
            '<div class="kv"><span>Booking</span><b class="mono" style="font-size:12px">'+esc(F.refs.booking)+'</b></div>'+
            '<div class="kv"><span>Payment</span><b class="mono" style="font-size:12px">'+esc(F.refs.payment)+'</b></div>'+
            '<div class="kv"><span>Paid</span><b class="mono">'+inr(F.money.totalPaise)+'</b></div></div></div>' : '')+
        (x==='duplicate'||x==='retry'? '<p class="m muted">Idempotency key '+esc(F.refs.idempotency)+' · replay returns the original result.</p>':'')+
        fees+tail;
      var primary = x==='success'?'View booking &amp; receipt' : x==='hold-expired'?'Pick another slot'
        : x==='duplicate'?'Open booking' : x==='processing'?'Waiting for confirmation…' : 'Try again';
      dock=dockPay(primary, x==='processing');
    }
    var overlay = d.overlay==='dialog' ? backWarnDialog() : '';
    return '<main class="route" data-family="checkout">'+tbar(st.screen)+'<div class="body hasdock">'+body+'</div>'+dock+overlay+'</main>';
  }
  function dockPay(label, disabled){
    return '<div class="dock"><div class="top"><span style="font-size:12px;font-weight:800;color:var(--mut)">Total payable</span>'+
      '<span class="tot" data-testid="dock-total">'+inr(F.money.totalPaise)+'</span></div>'+
      '<button class="btn jade block" type="button" data-testid="primary-action"'+(disabled?' disabled aria-disabled="true"':'')+'>'+ic('lock')+esc(label.replace(/&amp;/g,'&'))+'</button>'+
      '<button class="btn block" style="min-height:44px" type="button" data-go="s31-default">'+ic('close')+'Cancel payment</button></div>';
  }
  function backWarnDialog(){
    return '<div class="scrim" data-open="1"></div><div role="dialog" aria-modal="true" aria-labelledby="bwt" data-testid="dialog" class="modal">'+
      '<h2 id="bwt" class="m" style="font-size:17px">Leave payment and release your slot?</h2>'+
      '<p class="m" style="font-size:13px">Your 10-minute hold ends if you leave. Nothing has been charged. Someone else may take '+esc(F.slot.timeLabel)+'.</p>'+
      '<button class="btn jade block" type="button" data-testid="dialog-confirm">Stay and finish paying</button>'+
      '<button class="btn block" type="button" data-testid="dialog-dismiss" data-go="s31-default">Leave and release the slot</button></div>';
  }

  /* ============================ F4 receipt — S-34 ============================ */
  function fReceipt(st){
    var v=(st.delta||{}).variant||'confirmed';
    var pending = v==='pending', early = v==='join-early';
    var top = pending
      ? banner('warn','Not confirmed yet — waiting for the provider','We are waiting for the payment provider to confirm. Nothing more is needed from you. This page updates itself.', typedCode(st))
      : '<div class="band"><span class="seal">'+ic('check')+'</span><div><div class="eyebrow" style="color:var(--jade)">Confirmed &amp; paid</div>'+
        '<h2 class="m" style="margin-top:2px">'+esc(F.tutor.name)+'</h2><p class="m" style="font-size:12.5px">'+esc(F.tutor.practiceArea)+'</p></div></div>';
    var when='<div class="kv" style="border-bottom:none;padding:0"><span style="font-size:13.5px"><b>'+esc(F.slot.label)+'</b>'+
      '<span style="display:block;font-size:12px;color:var(--mut);font-weight:700">'+esc(F.slot.timezoneLabel)+'</span></span>'+
      '<span class="chip '+(v==='join-open'?'g':'i')+'"><span class="d"></span>'+(v==='join-open'?'Join is open now':esc(F.session.joinOpensLabel))+'</span></div>';
    var join = pending ? '<button class="btn block" type="button" disabled aria-disabled="true" data-testid="join-action">'+ic('join')+'Join available once confirmed</button>'
      : early ? '<button class="btn block" type="button" disabled aria-disabled="true" aria-describedby="je" data-testid="join-action">'+ic('join')+'Join opens at 6:15 PM IST</button>'+
                '<p class="m muted" id="je">The room opens 15 minutes before the start so you can test your camera and microphone.</p>'
      : '<a class="btn jade block" href="?state=s35-prejoin" data-testid="join-action">'+ic('join')+'Join session</a>';
    var extra='';
    if(v==='reminders') extra='<div class="dis" open><div class="dbody" style="padding-top:12px">'+
      '<div class="kv"><span>Reminders</span><b>'+esc(F.session.reminders)+'</b></div>'+
      '<div class="kv"><span>Channel</span><b>In-app and email</b></div>'+
      '<div class="kv"><span>Opt out</span><b>Notification settings</b></div></div></div>';
    if(v==='receipt') extra='<div class="dis" open><div class="dbody" style="padding-top:12px">'+
      '<div class="kv"><span>Paid</span><b class="mono">'+inr(F.money.totalPaise)+'</b></div>'+
      '<div class="kv"><span>Method</span><b>'+esc(F.payment.methodDisplay)+'</b></div>'+
      '<div class="kv"><span>Payment ref</span><b class="mono" style="font-size:12px">'+esc(F.refs.payment)+'</b></div>'+
      '<div class="kv"><span>Booking ref</span><b class="mono" style="font-size:12px">'+esc(F.refs.booking)+'</b></div></div></div>';
    if(v==='join-open') extra=banner('ok','Your room is open','Join now to test your camera and microphone before '+esc(F.slot.timeLabel.split('–')[0])+'.');
    return '<main class="route" data-family="receipt">'+tbar(st.screen)+'<div class="body">'+top+when+extra+join+
      '<a class="btn block" href="?state=s35-upcoming" data-testid="manage-action">'+ic('cal')+'Manage session</a>'+
      '<div class="actrow">'+
        '<button class="ib" type="button" aria-label="Copy booking reference">'+ic('copy')+'</button>'+
        '<button class="ib" type="button" aria-label="Share session pass">'+ic('share')+'</button>'+
        '<button class="ib" type="button" aria-label="Download receipt PDF">'+ic('dl')+'</button>'+
        '<span style="flex:1"></span><span class="chip i"><span class="d"></span>Free cancel to 4 Aug</span></div>'+
      '<details class="dis"><summary>'+ic('info')+'Session details'+ic('chev','cv')+'</summary><div class="dbody">'+
        '<div class="kv"><span>Topic</span><b>'+esc(F.session.topic)+'</b></div>'+
        '<div class="kv"><span>Length</span><b>'+F.slot.durationMin+' minutes · one-to-one</b></div>'+
        '<div class="kv"><span>Booking</span><b class="mono" style="font-size:12px">'+esc(F.refs.booking)+'</b></div></div></details>'+
      '</div></main>';
  }

  /* ============================ F5 manage — S-35 ============================ */
  function fManage(st){
    var d=st.delta||{}, v=d.variant||'upcoming', x=d.extra||'', body='', dock='';
    var idhead='<div><span class="chip i"><span class="d"></span>'+esc(F.tutor.practiceArea)+'</span>'+
      '<h2 class="m" style="margin-top:8px">'+esc(F.tutor.name)+'</h2>'+
      '<p class="m" style="font-size:12.5px">'+esc(F.slot.label)+' · '+esc(F.slot.timezoneLabel)+'</p></div>';

    if(v==='refund'){
      var map={
        '':['g','Eligible · 6 days before start','Cancel with a full refund','ok'],
        late:['r','Inside the 24-hour window','No automatic refund','warn'],
        'tutor-cancelled':['g','Cancelled by your mentor','Automatic full refund','ok'],
        req:['i','Refund requested','We have your request','info'],
        proc:['i','Refund processing','Sent to the payment provider','info'],
        ok:['g','Refund settled','Money is back with your bank','ok'],
        fail:['r','Refund failed','Your money is safe — retry below','err'],
        review:['gd','Manual review','A person is checking this refund','info'],
        conflict:['r','This page is out of date','The session changed while you were here','warn'],
        started:['r','The session already started','Cancellation is closed','warn'],
        offline:['r','You are offline','Nothing was lost','warn']
      };
      var m=map[x]||map[''];
      var step = x==='req'?1 : x==='proc'?3 : x==='ok'?5 : x==='fail'?3 : x==='review'?3 : 1;
      var bodyMsg={
        late:'Cancelling now means no automatic refund. You can still ask an administrator to review your case — you will not lose the session while they do.',
        'tutor-cancelled':'Your mentor cancelled. The full amount returns automatically to the card you paid with; you do not need to do anything.',
        req:'We recorded your cancellation and started the refund under reference '+F.refs.refund+'. Repeat requests return this same refund; you cannot be refunded twice.',
        proc:'The payment provider has refund '+F.refs.refund+'. Repeat requests return this same refund; you cannot be refunded twice. Banks usually settle within '+F.policy.refundWindowLabel+'.',
        ok:'Settled on 6 Aug 2026 to '+F.payment.methodDisplay+'.',
        fail:'The provider could not complete the refund. No money left your account twice and nothing is lost. Retrying reuses refund reference '+F.refs.refund+'.',
        review:'This refund needs a manual check. Expected turnaround is two working days; reference '+F.refs.audit+'.',
        conflict:'Someone changed this session after this page loaded. Refresh to see the current state — we will not overwrite the newer change.',
        started:'The scheduled start has passed, so cancellation is closed. You can still go to attendance after the session ends.',
        offline:'You appear to be offline. Nothing was submitted and nothing was lost. Retry when your connection is back.'
      }[x];
      var amountBlock = (x==='conflict'||x==='started'||x==='offline') ? '' :
        '<div class="amt" data-testid="refund-amount"><div style="font-family:var(--font-mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--mut)">'+
        (x==='ok'?'Returned to you':'Returning to you')+'</div><div class="big">'+inr(F.money.totalPaise)+'</div>'+
        '<div style="font-size:12.5px;color:var(--ink2);line-height:1.5">Full amount including GST, back to <b>'+esc(F.payment.methodDisplay)+'</b> — the card you paid with.</div>'+
        '<div style="display:flex;gap:6px;flex-wrap:wrap"><span class="chip g"><span class="d"></span>No deduction</span>'+
        '<span class="chip t"><span class="d"></span>'+esc(F.policy.refundWindowLabel)+'</span></div></div>'+
        '<div class="prog" aria-label="Refund progress: step '+step+' of 5"><span>Step '+step+' of 5</span>'+
        [1,2,3,4,5].map(function(i){return '<i class="'+(i<=step?'on':'')+'"></i>';}).join('')+'</div>';
      body='<div><span class="chip '+m[0]+'"><span class="d"></span>'+esc(m[1])+'</span>'+
        '<h2 class="m" style="margin-top:8px">'+esc(m[2])+'</h2></div>'+
        (bodyMsg?banner(m[3],m[2],bodyMsg,typedCode(st)):'')+amountBlock+
        '<details class="dis"><summary>'+ic('info')+'How the refund works'+ic('chev','cv')+'</summary><div class="dbody steps">'+
          '<div class="s" data-done="1"><span class="n">1</span><div><h4>Session cancelled</h4><p>'+esc(F.tutor.name)+' · '+esc(F.slot.dateLabel)+'</p></div></div>'+
          '<div class="s" data-'+(step>2?'done':'now')+'="1"><span class="n">2</span><div><h4>Policy checked</h4><p>More than 24 hours before start means a full refund.</p></div></div>'+
          '<div class="s"'+(step>=3?' data-now="1"':'')+'><span class="n">3</span><div><h4>Sent to the payment provider</h4><p>Starts the same day.</p></div></div>'+
          '<div class="s"><span class="n">4</span><div><h4>Bank settlement</h4><p>'+esc(F.policy.refundWindowLabel)+'.</p></div></div>'+
          '<div class="s"'+(step===5?' data-done="1"':'')+'><span class="n">5</span><div><h4>Receipt issued</h4><p>Downloadable from your sessions list.</p></div></div></div></details>'+
        '<details class="dis"><summary>'+ic('copy')+'References'+ic('chev','cv')+'</summary><div class="dbody">'+
          '<div class="kv"><span>Booking</span><b class="mono" style="font-size:12px">'+esc(F.refs.booking)+'</b></div>'+
          '<div class="kv"><span>Original payment</span><b class="mono" style="font-size:12px">'+esc(F.refs.payment)+'</b></div>'+
          '<div class="kv"><span>Refund</span><b class="mono" style="font-size:12px">'+esc(F.refs.refund)+'</b></div></div></details>'+
        '<p class="m muted" data-testid="policy-tail">Prefer to keep the mentor? Rescheduling is free at this notice and keeps your payment.</p>';
      var primary = x==='fail'?'Retry refund' : x==='conflict'?'Refresh to current state' : x==='offline'?'Retry when online'
        : x==='ok'?'Download refund receipt' : x==='started'?'Go to attendance' : x==='late'?'Request an admin exception'
        : (x==='req'||x==='proc'||x==='review')?'Track this refund' : 'Cancel & refund '+inr(F.money.totalPaise);
      dock='<div class="dock"><button class="btn '+(x?'':'terra')+' block" type="button" data-testid="primary-action">'+ic('refund')+esc(primary)+'</button>'+
        '<div class="dockrow"><a class="btn" href="?state=s35-reschedule">'+ic('cal')+'Reschedule free</a>'+
        '<a class="btn" href="?state=s34-confirmed">Keep session</a></div></div>';
    } else if(v==='policy'){
      body=idhead+banner('info','What happens if you cancel now','You are more than 24 hours before the start, so cancelling returns the full '+inr(F.money.totalPaise)+' to '+F.payment.methodDisplay+' within '+F.policy.refundWindowLabel+'. Rescheduling is free and keeps your payment.')+
        '<div class="dis" open><div class="dbody" style="padding-top:12px">'+
        '<div class="kv"><span>Free cancellation until</span><b>'+esc(F.policy.freeCancelCutoffLabel)+'</b></div>'+
        '<div class="kv"><span>After that</span><b>Admin exception only</b></div>'+
        '<div class="kv"><span>Reschedule</span><b>Free · payment preserved</b></div></div></div>';
      dock='<div class="dock"><a class="btn terra block" href="?state=s35-cancel-eligible">Continue to cancel</a>'+
        '<a class="btn block" style="min-height:44px" href="?state=s35-upcoming">Back to session</a></div>';
    } else if(v==='reschedule'){
      body=idhead+banner('ok','Rescheduling is free at this notice','Your payment of '+inr(F.money.totalPaise)+' moves to the new slot. Nothing is charged again.')+
        '<h3 class="m">Choose a new slot · '+esc(F.slot.timezoneLabel)+'</h3><div class="slots">'+
        F.slotsOther.map(function(s){var a=s.status==='available';
          return '<button class="slotbtn" type="button" '+(a?'':'disabled aria-disabled="true"')+' data-slot-status="'+s.status+'">'+
          '<span class="sl">'+esc(s.label)+'</span><span class="chip '+(a?'g':s.status==='held'?'t':'r')+'"><span class="d"></span>'+
          (a?'Available':s.status==='held'?'Held':'Booked')+'</span></button>';}).join('')+'</div>';
      dock='<div class="dock"><button class="btn jade block" type="button" data-testid="primary-action">Confirm new slot</button>'+
        '<a class="btn block" style="min-height:44px" href="?state=s35-upcoming">Back to session</a></div>';
    } else if(v==='post'){
      body=idhead+banner('ok','You left the room and your devices were released','Your camera and microphone are no longer in use. Nothing from the session is stored in this browser.')+
        '<div class="dis" open><div class="dbody" style="padding-top:12px">'+
        '<div class="kv"><span>Scheduled</span><b>'+esc(F.slot.timeLabel)+' IST</b></div>'+
        '<div class="kv"><span>Recording</span><b>'+esc(F.session.recording)+'</b></div>'+
        '<div class="kv"><span>Attendance</span><b>Decided after the scheduled end</b></div></div></div>';
      dock='<div class="dock"><a class="btn jade block" href="?state=s35-att-pending">Go to attendance</a></div>';
    } else if(v==='att'){
      var am={
        pending:['info','Attendance is not decided yet','Attendance opens after the scheduled end at '+F.slot.timeLabel.split('–')[1]+' IST. Your mentor marks it first, then you confirm or dispute.'],
        marked:['info','Your mentor marked this session attended','Marked by '+F.tutor.name+' on 5 Aug 2026, 7:16 PM IST. Confirm if that is right, or dispute it.'],
        confirm:['ok','You confirmed attendance','Thank you. Your review is now unlocked.'],
        dispute:['warn','Tell us what happened','Describe the problem in your own words. Do not include personal details about anyone else.'],
        resolution:['info','Waiting for an administrator','Case '+F.refs.audit+' is open. Expected turnaround is two working days. Nothing more is needed from you.'],
        resolved:['ok','Dispute resolved','The session was marked not attended and your refund of '+inr(F.money.totalPaise)+' was approved. Reference '+F.refs.audit+'.'],
        errors:['err','Attendance action refused','Four typed refusals are possible here, each with its own recovery.']
      }[x]||['info','Attendance','—'];
      body=idhead+banner(am[0],am[1],am[2],typedCode(st))+
        (x==='dispute'? '<div class="fld"><label for="dr">Reason</label>'+
          '<textarea class="in" id="dr" data-testid="dispute-reason" rows="4" maxlength="1000" aria-describedby="dr-c" '+
          'style="padding:10px 13px;align-items:flex-start;font-family:var(--font-body);resize:vertical;min-height:96px"></textarea>'+
          '<span class="muted" id="dr-c" aria-live="polite" data-testid="dispute-counter">0 of 1,000 characters</span></div>' : '')+
        (x==='errors'? '<div class="dis" open><div class="dbody" style="padding-top:12px">'+
          '<div class="kv"><span>Before the scheduled end</span><b>ATTENDANCE_TOO_EARLY</b></div>'+
          '<div class="kv"><span>Already recorded</span><b>ATTENDANCE_DUPLICATE</b></div>'+
          '<div class="kv"><span>Wrong role</span><b>ATTENDANCE_FORBIDDEN_ROLE</b></div>'+
          '<div class="kv"><span>Stale view</span><b>ATTENDANCE_STALE</b></div></div></div>'+
          banner('warn','These labels are not an approved API','Attendance and completion authority (W2-6) is Product-pending on SAATHI-65/66. Treat these as UI obligations only.') : '')+
        (x==='marked'||x==='confirm'||x==='resolved'? '<div class="dis" open><div class="dbody" style="padding-top:12px">'+
          '<div class="kv"><span>Session</span><b>'+esc(F.slot.dateLabel)+'</b></div>'+
          '<div class="kv"><span>Mentor</span><b>'+esc(F.tutor.name)+'</b></div>'+
          '<div class="kv"><span>Reference</span><b class="mono" style="font-size:12px">'+esc(F.refs.booking)+'</b></div></div></div>' : '');
      var ap={pending:'Refresh attendance',marked:'Confirm attendance',confirm:'Leave a review',dispute:'Submit dispute',
        resolution:'Track this case',resolved:'Back to sessions',errors:'Refresh to current state'}[x]||'Continue';
      dock='<div class="dock"><button class="btn jade block" type="button" data-testid="primary-action"'+(x==='pending'?'':'')+'>'+esc(ap)+'</button>'+
        (x==='marked'?'<a class="btn block" style="min-height:44px" href="?state=s35-att-dispute">Dispute this</a>':
         x==='dispute'?'<a class="btn block" style="min-height:44px" href="?state=s35-att-marked">Cancel dispute</a>':'')+'</div>';
    } else if(v==='review'){
      var stars=[1,2,3,4,5].map(function(i){
        return '<label class="ib" style="border-radius:12px" data-testid="star-'+i+'">'+
          '<input type="radio" name="stars" value="'+i+'" class="sr"><span class="sr">'+i+' star'+(i>1?'s':'')+'</span>'+ic('star')+'</label>';}).join('');
      if(x==='blocked'){
        body=idhead+banner('warn','Review is locked until attendance is confirmed','Reviews only open after a confirmed attendance record. Confirm attendance, then come back.', typedCode(st));
        dock='<div class="dock"><a class="btn jade block" href="?state=s35-att-marked">Go to attendance</a></div>';
      } else if(x==='done'){
        body=idhead+banner('ok','Thank you — your review was submitted','It goes to moderation before it appears on the mentor profile. You can edit it for 24 hours.');
        dock='<div class="dock"><a class="btn jade block" href="?state=s31-default">Back to mentors</a></div>';
      } else {
        body=idhead+'<fieldset style="border:none;padding:0;margin:0"><legend class="m" style="font-size:13px;font-weight:800;padding:0 0 8px">'+
          'Your rating (1 to 5 stars)</legend><div class="actrow" role="radiogroup" aria-label="Rating out of 5" data-testid="stars">'+stars+'</div></fieldset>'+
          '<div class="fld"><label for="rv">What was useful? (10 to 1,000 characters)</label>'+
          '<textarea class="in" id="rv" data-testid="review-text" rows="5" minlength="10" maxlength="1000" aria-describedby="rv-c" '+
          'style="padding:10px 13px;align-items:flex-start;font-family:var(--font-body);resize:vertical;min-height:110px"></textarea>'+
          '<span class="muted" id="rv-c" aria-live="polite" data-testid="review-counter">0 of 1,000 characters · at least 10 needed</span></div>'+
          banner('info','Reviews are moderated','Do not include names of other people, case numbers or anything you would not want published.');
        dock='<div class="dock"><button class="btn jade block" type="button" data-testid="primary-action">Submit review</button></div>';
      }
    } else {
      body=idhead+'<div class="chip g" style="align-self:flex-start"><span class="d"></span>'+esc(F.session.joinOpensLabel)+'</div>'+
        banner('info','Free cancellation until '+F.policy.freeCancelCutoffLabel,'Cancel before then for a full refund of '+inr(F.money.totalPaise)+', or reschedule free and keep your payment.')+
        '<div class="dis" open><div class="dbody" style="padding-top:12px">'+
        '<div class="kv"><span>Topic</span><b>'+esc(F.session.topic)+'</b></div>'+
        '<div class="kv"><span>Length</span><b>'+F.slot.durationMin+' minutes</b></div>'+
        '<div class="kv"><span>Booking</span><b class="mono" style="font-size:12px">'+esc(F.refs.booking)+'</b></div></div></div>';
      dock='<div class="dock"><a class="btn jade block" href="?state=s35-prejoin">'+ic('join')+'Join session</a>'+
        '<div class="dockrow"><a class="btn" href="?state=s35-policy">Cancel or reschedule</a>'+
        '<a class="btn" href="?state=s34-receipt">Receipt</a></div></div>';
    }
    var overlay = (st.delta||{}).overlay==='dialog' ? refundDialog() : '';
    return '<main class="route" data-family="manage">'+tbar(st.screen)+'<div class="body hasdock">'+body+'</div>'+dock+overlay+'</main>';
  }
  function refundDialog(){
    return '<div class="scrim" data-open="1"></div><div role="dialog" aria-modal="true" aria-labelledby="rdt" data-testid="dialog" class="modal">'+
      '<h2 id="rdt" class="m" style="font-size:17px">Cancel and refund '+inr(F.money.totalPaise)+'?</h2>'+
      '<p class="m" style="font-size:13px">Your session with '+esc(F.tutor.name)+' on '+esc(F.slot.dateLabel)+' will be cancelled. '+
      '<b>'+inr(F.money.totalPaise)+'</b> returns to '+esc(F.payment.methodDisplay)+' within '+esc(F.policy.refundWindowLabel)+'. This cannot be undone.</p>'+
      '<button class="btn terra block" type="button" data-testid="dialog-confirm">Yes, cancel and refund</button>'+
      '<button class="btn block" type="button" data-testid="dialog-dismiss">Keep my session</button></div>';
  }

  /* ======================= F6 prejoin / device — S-35 ======================= */
  function fPrejoin(st){
    var d=st.delta||{}, x=d.extra||st.id, ok=(x==='s35-prejoin'||x==='s35-devices');
    var msg={
      's35-prejoin':['info','You are joining as yourself','Test your camera and microphone before the room opens. Nothing is recorded and no device name leaves your browser.'],
      's35-devices':['info','Device check','Pick the camera and microphone you want to use. Speak to see the level move.'],
      's35-perm-cam':['err','Camera permission is blocked','Your browser is blocking the camera for this site. Open the site permissions in the address bar, allow Camera, then choose Test again. You can also join with audio only.'],
      's35-perm-mic':['err','Microphone permission is blocked','Your mentor will not hear you. Allow Microphone in your browser site settings, then choose Test again.'],
      's35-perm-pending':['warn','We still need your permission','The permission prompt was dismissed. Choose Ask again to show it.'],
      's35-no-device':['err','No camera or microphone found','Connect a device, then choose Test again. You can still join to listen.'],
      's35-device-busy':['err','Your camera is in use by another app','Close the other video app, then choose Test again.'],
      's35-unsupported':['err','This browser cannot run video sessions','Open the session in the latest Chrome, Edge, Safari or Firefox.'],
      's35-insecure':['err','This page is not on a secure connection','Video needs a secure connection. Open the session from the secure link in your confirmation.'],
      's35-constraint':['warn','Your camera cannot use the requested quality','Choose Retry in standard quality to continue.'],
      's35-join-early-v':['warn','The room is not open yet','Join opens at 6:15 PM IST, 15 minutes before the start.'],
      's35-pay-unverified':['err','Payment is not verified yet','We cannot open the room until the payment provider confirms. Check your payment status.'],
      's35-token-expired':['warn','Your join link expired','Join links are short lived for your safety. Get a fresh link to continue.'],
      's35-wrong-user':['err','This session belongs to a different account','Sign in with the account that booked this session.'],
      's35-ended':['warn','This session already ended','You can still confirm attendance and leave a review.']
    }[x]||['info','Pre-join','—'];
    var camOff = ['s35-perm-cam','s35-no-device','s35-device-busy','s35-unsupported','s35-insecure','s35-constraint'].indexOf(x)>=0;
    var eligibility = ['s35-join-early-v','s35-pay-unverified','s35-token-expired','s35-wrong-user','s35-ended'].indexOf(x)>=0;
    var preview = eligibility ? '' :
      '<div class="preview" data-testid="preview">'+(camOff
        ? '<div class="off">'+ic('camOff')+'<div style="margin-top:8px">Camera preview unavailable</div></div>'
        : '<svg viewBox="0 0 400 300" role="img" aria-label="Your camera preview"><rect width="400" height="300" fill="#191207"/><circle cx="200" cy="128" r="52" fill="#50402a"/><path d="M108 268c16-42 44-62 92-62s76 20 92 62z" fill="#50402a"/></svg>')+'</div>';
    var selectors = eligibility ? '' :
      '<div class="devrow"><label for="camsel" style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)">Camera</label>'+
      '<select class="sel" id="camsel" data-testid="camera-select"'+(camOff?' disabled':'')+'><option>Built-in camera</option><option>External camera</option></select></div>'+
      '<div class="devrow"><label for="micsel" style="font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;color:var(--mut)">Microphone</label>'+
      '<select class="sel" id="micsel" data-testid="mic-select"'+(x==='s35-perm-mic'||x==='s35-no-device'?' disabled':'')+'><option>Built-in microphone</option><option>Headset microphone</option></select></div>';
    var primary={
      's35-prejoin':'Test camera and microphone','s35-devices':'Join session',
      's35-perm-cam':'Test again','s35-perm-mic':'Test again','s35-perm-pending':'Ask again',
      's35-no-device':'Test again','s35-device-busy':'Test again','s35-unsupported':'Copy the session link',
      's35-insecure':'Open the secure link','s35-constraint':'Retry in standard quality',
      's35-join-early-v':'Set a reminder','s35-pay-unverified':'Check payment status',
      's35-token-expired':'Get a fresh join link','s35-wrong-user':'Switch account','s35-ended':'Go to attendance'
    }[x]||'Continue';
    var second = (x==='s35-perm-cam'||x==='s35-no-device') ? '<a class="btn" href="?state=s35-room-camoff">Join with audio only</a>' :
      '<a class="btn" href="?state=s35-upcoming">Back to session</a>';
    return '<main class="route" data-family="prejoin">'+tbar(st.screen)+'<div class="body hasdock">'+
      '<div><div class="eyebrow">Before you join</div><h2 class="m" style="margin-top:4px">'+esc(F.tutor.name)+'</h2>'+
      '<p class="m" style="font-size:12.5px">'+esc(F.slot.label)+' · '+esc(F.slot.timezoneLabel)+'</p></div>'+
      banner(msg[0],msg[1],msg[2],typedCode(st))+preview+selectors+
      '<p class="m muted">No media, device name or join credential is written to the address bar, this browser’s storage or any log.</p>'+
      '</div><div class="dock"><button class="btn jade block" type="button" data-testid="primary-action">'+ic(ok?'join':'dev')+esc(primary)+'</button>'+
      '<div class="dockrow">'+second+'</div></div></main>';
  }

  /* ======================= F7 room — S-35 live (REPAIRED) ======================= */
  function fRoom(st, landscape){
    var d=st.delta||{}, veil=d.veil, b=d.banner, micOff=d.mic==='off', camOff=d.cam==='off';
    /* Reference stand-in for live media: a chambers backdrop with the approved C2
       portrait medallion. Deliberately a reference placeholder, not fake footage. */
    var W = landscape ? 820 : 420, H = landscape ? 280 : 830;
    var cx = W / 2, cy = H * 0.46, R = Math.min(W, H) * (landscape ? 0.26 : 0.155);
    var shelf = function (y, n, seed) {
      var out = '<rect x="' + (W * 0.06) + '" y="' + y + '" width="' + (W * 0.30) + '" height="' + Math.max(2, H * 0.010) + '" fill="#3a2d1b"/>';
      for (var i = 0; i < n; i++) {
        var bw = W * 0.026 + ((i + seed) % 3) * W * 0.007;
        var bh = H * 0.070 - ((i + seed) % 4) * H * 0.010;
        out += '<rect x="' + (W * 0.07 + i * (W * 0.040)) + '" y="' + (y - bh) + '" width="' + bw + '" height="' + bh +
          '" rx="' + (W * 0.003) + '" fill="' + ['#4a3a20', '#3f3524', '#54401f', '#463522', '#5a4526', '#3c3020'][(i + seed) % 6] + '"/>';
      }
      return out;
    };
    var tile='<div class="mtile" data-testid="remote-tile">'+
      '<svg viewBox="0 0 '+W+' '+H+'" preserveAspectRatio="xMidYMid slice" role="img" '+
      'aria-label="Mentor video tile — camera on">'+
      '<defs>'+
        '<linearGradient id="rmBg" x1="0" y1="0" x2=".3" y2="1">'+
          '<stop offset="0" stop-color="#261c0f"/><stop offset=".55" stop-color="#1a1208"/><stop offset="1" stop-color="#100b05"/></linearGradient>'+
        '<radialGradient id="rmKey" cx=".5" cy=".42" r=".58">'+
          '<stop offset="0" stop-color="#e6bf6a" stop-opacity=".13"/><stop offset="1" stop-color="#e6bf6a" stop-opacity="0"/></radialGradient>'+
        '<linearGradient id="rmMed" x1="0" y1="0" x2="0" y2="1">'+
          '<stop offset="0" stop-color="#17795121"/><stop offset="1" stop-color="#0f6b4740"/></linearGradient>'+
      '</defs>'+
      '<rect width="'+W+'" height="'+H+'" fill="url(#rmBg)"/>'+
      '<g opacity=".55">'+shelf(H*0.20,6,0)+shelf(H*0.40,5,2)+'</g>'+
      '<rect width="'+W+'" height="'+H+'" fill="url(#rmKey)"/>'+
      '<circle cx="'+cx+'" cy="'+cy+'" r="'+(R*1.30)+'" fill="#0f6b47" fill-opacity=".10"/>'+
      '<circle cx="'+cx+'" cy="'+cy+'" r="'+R+'" fill="url(#rmMed)" stroke="#5fcb9c" stroke-opacity=".55" stroke-width="'+(R*0.045)+'"/>'+
      '<text x="'+cx+'" y="'+(cy + R*0.30)+'" text-anchor="middle" font-family="Newsreader,Georgia,serif" '+
        'font-size="'+(R*0.74)+'" fill="#e8f4ee" fill-opacity=".92" letter-spacing="'+(R*0.03)+'">MK</text>'+
      '<text x="'+cx+'" y="'+(cy + R*1.72)+'" text-anchor="middle" font-family="IBM Plex Mono,monospace" '+
        'font-size="'+(Math.min(W,H)*0.030)+'" fill="#ad9c80" letter-spacing="'+(Math.min(W,H)*0.010)+'">LIVE VIDEO · REFERENCE TILE</text>'+
      '<rect width="'+W+'" height="'+H+'" fill="none" stroke="#000" stroke-opacity=".24" stroke-width="'+(W*0.05)+'"/>'+
      '</svg>'+
      (veil?'<div class="stateveil" data-testid="stage-veil"><b>'+esc(veil[0])+'</b><span>'+esc(veil[1])+'</span></div>':'')+
      (b?'<div class="rbanner '+b[0]+'" role="status" data-testid="room-banner">'+ic('warn')+
         '<div style="min-width:0"><div class="bt">'+esc(b[1])+'</div><div class="bd2">'+esc(b[2])+'</div></div></div>':'')+
      '<div class="nm">'+esc(F.tutor.name)+' · Mentor<span style="width:8px;height:8px;border-radius:50%;background:#5fcb9c"></span></div></div>';
    var self='<div class="self" id="self" data-min="0" data-pos="br" data-testid="self-view">'+
      '<svg viewBox="0 0 100 '+(landscape?75:130)+'" preserveAspectRatio="xMidYMid slice" role="img" aria-label="Your camera tile">'+
      '<defs><linearGradient id="svBg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2e2314"/><stop offset="1" stop-color="#1a1409"/></linearGradient></defs>'+
      '<rect width="100" height="'+(landscape?75:130)+'" fill="url(#svBg)"/>'+
      (camOff?'':'<circle cx="50" cy="'+(landscape?37:65)+'" r="'+(landscape?20:26)+'" fill="#6b5638" fill-opacity=".35" stroke="#8d7350" stroke-opacity=".65" stroke-width="1.6"/>'+
        '<text x="50" y="'+(landscape?44:74)+'" text-anchor="middle" font-family="IBM Plex Mono,monospace" font-size="'+(landscape?15:19)+'" fill="#d9c9ad">AN</text>')+'</svg>'+
      '<div class="nm2">'+(camOff?'Camera off':'You')+'</div>'+
      /* [ADDENDUM RC-5] Move and Minimise live INSIDE the self-view so the tile must be
         large enough to contain two independent 44x44 targets without overlap. When
         minimised, .selfmove is hidden and exactly one 44x44 restore control remains. */
      '<div class="selfctl">'+
      '<button class="sb selfmove" type="button" id="selfmove" aria-label="Move self-view to another corner" data-testid="self-move">'+ic('move')+'</button>'+
      '<button class="sb mini" type="button" id="selfmin" aria-pressed="false" aria-label="Minimise self-view" data-testid="self-min">'+ic('min')+'</button></div></div>';
    var dock='<div class="lctrl" data-testid="control-dock">'+
      '<button class="cb" type="button" id="mic" aria-pressed="'+(micOff?'true':'false')+'" aria-label="'+(micOff?'Unmute microphone':'Mute microphone')+'" data-testid="mic">'+ic(micOff?'micOff':'mic')+'</button>'+
      '<button class="cb" type="button" id="cam" aria-pressed="'+(camOff?'true':'false')+'" aria-label="'+(camOff?'Turn camera on':'Turn camera off')+'" data-testid="cam">'+ic(camOff?'camOff':'cam')+'</button>'+
      '<button class="cb" type="button" id="devbtn" aria-label="Device settings" data-testid="devices">'+ic('dev')+'</button>'+
      '<button class="cb leave" type="button" id="leave" data-testid="leave">'+ic('leave')+'<span>Leave</span></button></div>';
    var sheet='<div class="sheet" id="sheet" role="dialog" aria-modal="false" aria-label="Session details" data-open="0" data-testid="sheet">'+
      '<div class="grab" aria-hidden="true"></div>'+
      '<div style="display:flex;align-items:center;gap:10px"><h2 class="m" style="font-size:17px">Session details</h2><span style="flex:1"></span>'+
      '<button class="ib" type="button" id="sheetclose" aria-label="Close session details" data-testid="sheet-close">'+ic('close')+'</button></div>'+
      '<div class="kv"><span>Focus</span><b>'+esc(F.session.topic)+'</b></div>'+
      '<div class="kv"><span>Mentor</span><b>'+esc(F.tutor.name)+'</b></div>'+
      '<div class="kv"><span>Scheduled</span><b>'+esc(F.slot.timeLabel)+' IST</b></div>'+
      '<div class="kv"><span>Recording</span><b>'+esc(F.session.recording)+'</b></div>'+
      '<p class="m muted" style="margin-top:8px">No media, device name or join credential is kept in your browser. Leaving releases your camera and microphone.</p></div>'+
      '<div class="scrim" id="scrim" data-open="0"></div>';
    var leaveDlg = d.overlay==='leave' ?
      '<div class="scrim" data-open="1"></div><div role="dialog" aria-modal="true" aria-labelledby="lvt" data-testid="dialog" class="modal">'+
      '<h2 id="lvt" class="m" style="font-size:17px">Leave this session?</h2>'+
      '<p class="m" style="font-size:13px">Your camera and microphone are released when you leave. You can rejoin while the session is running.</p>'+
      '<button class="btn terra block" type="button" data-testid="dialog-confirm">Leave the session</button>'+
      '<button class="btn block" type="button" data-testid="dialog-dismiss">Stay in the room</button></div>' : '';
    /* [ADDENDUM RC-1/RC-2/RC-6] .live-host owns the 100vh -> 100dvh cascade and closes
       the percentage height chain; .live is the constrained three-row grid. The room
       advertises readiness only through data-live-room-ready. */
    return '<div class="live-host" data-testid="live-host">'+
      '<main class="route room live" data-family="room" data-live-room-ready="false">'+
      '<div class="lh">'+
        '<span class="chip g" style="font-size:10px;padding:4px 8px"><span class="d"></span>Live</span>'+
        '<span class="t">'+esc(F.session.topic)+'</span><span style="flex:1"></span>'+
        '<span class="m">'+esc(F.session.elapsedLabel)+'</span>'+
        '<button class="cb" type="button" id="sheetbtn" aria-label="Session, connection and privacy details" aria-expanded="false" data-testid="session-info">'+ic('info')+'</button>'+
      '</div>'+
      '<div class="stage">'+tile+self+'</div>'+
      dock+sheet+leaveDlg+'</main></div>';
  }

  var RENDER = { list:fList, profile:fProfile, checkout:fCheckout, receipt:fReceipt, manage:fManage, prejoin:fPrejoin, room:fRoom };
  root.C2Frames = { render:function(st, landscape){ return RENDER[st.layoutFamily](st, landscape); }, ic:ic, esc:esc };
})(typeof globalThis !== 'undefined' ? globalThis : this);
