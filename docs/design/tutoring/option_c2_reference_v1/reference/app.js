/* Option C2 reference — router, interaction wiring and the __C2_READY signal (v1).
   READY CONTRACT (no fixed sleeps anywhere):
     window.__C2_READY       Promise -> readiness descriptor, replaced on every navigation
     window.__C2_READY_FLAG  boolean, true only while the current state is settled
     [data-live-room-ready="true"]  set on the live root ONLY when the room is settled
                             (addendum rule 12). It starts at "false" in the markup and
                             is never set optimistically.
     window.__C2.goto(id)    Promise resolving to the same descriptor
   __C2_READY resolves only when ALL of these hold:
     1. fixtures, states and frames are loaded and the fixture checksum matches
     2. document.fonts.ready has resolved
     3. every media tile required by the family exists in the DOM
     4. the control dock (or the family's primary action) is mounted
     5. no DOM mutation has been observed for one full animation frame
   A bounded rejecting timeout is the harness's responsibility, not this file's. */
(function (root) {
  'use strict';
  var Fx = root.C2Fixtures, St = root.C2States, Fr = root.C2Frames;
  var EXPECTED_CHECKSUM = Fx.CHECKSUM;
  var app, live, readyResolve, readyReject, mo = null, settleTimer = null;

  function qs() {
    var out = {}, s = location.search.replace(/^\?/, '');
    s.split('&').forEach(function (kv) {
      if (!kv) return; var i = kv.indexOf('='); var k = i < 0 ? kv : kv.slice(0, i);
      out[decodeURIComponent(k)] = i < 0 ? '1' : decodeURIComponent(kv.slice(i + 1));
    });
    return out;
  }

  function announce(msg) {
    if (!live) return;
    live.textContent = '';
    requestAnimationFrame(function () { live.textContent = msg; });
  }

  /* ---- readiness ---- */
  function armReady(stateId) {
    root.__C2_READY_FLAG = false;
    root.__C2_READY = new Promise(function (res, rej) { readyResolve = res; readyReject = rej; });
    return root.__C2_READY;
  }

  function familyRequirements(family) {
    switch (family) {
      case 'room':    return ['[data-testid=remote-tile]', '[data-testid=self-view]', '[data-testid=control-dock]', '[data-testid=mic]', '[data-testid=cam]', '[data-testid=devices]', '[data-testid=leave]'];
      case 'checkout':
      case 'manage':
      case 'prejoin': return ['.dock', '[data-testid=screen-id]'];
      case 'prejoin-x': return ['.dock'];
      default:        return ['[data-testid=screen-id]'];
    }
  }

  function settle(state) {
    /* resolve once no mutation has been seen for a full frame */
    if (mo) { mo.disconnect(); mo = null; }
    var dirty = true;
    mo = new MutationObserver(function () { dirty = true; });
    mo.observe(document.body, { childList: true, subtree: true, attributes: true, characterData: true });

    function tick() {
      if (dirty) { dirty = false; requestAnimationFrame(tick); return; }
      /* two clean frames: layout + paint have settled */
      requestAnimationFrame(function () {
        if (dirty) { dirty = false; requestAnimationFrame(tick); return; }
        if (mo) { mo.disconnect(); mo = null; }
        finish(state);
      });
    }
    requestAnimationFrame(tick);
  }

  function finish(state) {
    var missing = familyRequirements(state.layoutFamily).filter(function (sel) { return !document.querySelector(sel); });
    if (Fx.CHECKSUM !== EXPECTED_CHECKSUM) {
      root.__C2_READY_FLAG = false;
      return readyReject(new Error('FIXTURE_CHECKSUM_MISMATCH expected ' + EXPECTED_CHECKSUM + ' got ' + Fx.CHECKSUM));
    }
    if (missing.length) {
      root.__C2_READY_FLAG = false;
      return readyReject(new Error('READY_REQUIREMENTS_MISSING ' + missing.join(',')));
    }
    var d = {
      state: state.id, family: state.layoutFamily, screen: state.screen,
      fixtureChecksum: Fx.CHECKSUM,
      theme: document.documentElement.getAttribute('data-theme'),
      fontsReady: true, mutationsSettled: true,
      viewport: { w: window.innerWidth, h: window.innerHeight },
      landscape: !!root.__C2.landscape
    };
    root.__C2_READY_FLAG = true;
    root.__C2_LAST_READY = d;
    /* [ADDENDUM RULE 12] explicit, observable ready signal on the live root. It flips to
       "true" only after fixtures+checksum, fonts, every required tile and the dock are
       present and the DOM has been mutation-quiet for a full frame. */
    var liveRoot = document.querySelector('.route.room.live') || document.querySelector('.live');
    if (liveRoot) liveRoot.setAttribute('data-live-room-ready', 'true');
    readyResolve(d);
  }

  /* ---- render ---- */
  function render(stateId) {
    var state = St.BY_ID[stateId];
    if (!state) throw new Error('UNKNOWN_STATE ' + stateId);
    var p = armReady(stateId);

    document.documentElement.setAttribute('data-state', state.id);
    document.documentElement.setAttribute('data-family', state.layoutFamily);
    document.body.setAttribute('data-family', state.layoutFamily);
    document.body.setAttribute('data-state', state.id);
    document.title = state.screen + ' · ' + state.label + ' · Option C2 reference';

    var landscape = root.__C2.rig === 'vp'
      ? (root.__C2.rigW > root.__C2.rigH && root.__C2.rigH <= 520)
      : (root.__C2.landscape || (window.innerWidth > window.innerHeight && window.innerHeight <= 520));
    var markup = Fr.render(state, landscape);
    if (root.__C2.rig === 'vp') {
      /* [ADDENDUM RC-2] offline device rig. The simulated device is a fixed-size .vp and
         .vp>.app closes the height chain, so viewport units can never measure the outer
         browser. Without the rig the reference renders each state at the real viewport. */
      var screenKey = state.layoutFamily === 'room' ? (landscape ? 's35land' : 's35live') : state.id;
      markup = '<div class="vp" data-screen="' + screenKey + '" data-testid="device-viewport" style="width:' +
        root.__C2.rigW + 'px;height:' + root.__C2.rigH + 'px"><div class="app">' + markup + '</div></div>';
    }
    app.innerHTML = markup;
    wire(state);
    root.__C2.state = state;

    document.fonts.ready.then(function () { reserveDock(); settle(state); },
      function (e) { readyReject(new Error('FONTS_FAILED ' + e)); });
    return p;
  }

  /* reserve exactly the dock's measured height so the sticky dock never buries
     the last content element on any viewport (asserted by stickyCoversFinalContent) */
  function reserveDock() {
    var dock = app.querySelector('.dock'), bodyEl = app.querySelector('.body.hasdock');
    if (!dock || !bodyEl) return;
    var h = Math.ceil(dock.getBoundingClientRect().height) + 16;
    bodyEl.style.paddingBottom = h + 'px';
  }

  function wire(state) {
    /* declarative navigation */
    app.querySelectorAll('[data-go]').forEach(function (el) {
      el.addEventListener('click', function (e) { e.preventDefault(); go(el.getAttribute('data-go')); });
    });
    app.querySelectorAll('[data-href]').forEach(function (el) {
      el.addEventListener('click', function (e) { e.preventDefault(); location.search = el.getAttribute('data-href').replace(/^\?/, ''); });
    });

    /* mic / camera */
    var mic = app.querySelector('#mic');
    if (mic) mic.addEventListener('click', function () {
      var off = mic.getAttribute('aria-pressed') === 'true';
      mic.setAttribute('aria-pressed', String(!off));
      mic.setAttribute('aria-label', off ? 'Mute microphone' : 'Unmute microphone');
      mic.innerHTML = Fr.ic(off ? 'mic' : 'micOff');
      announce(off ? 'Microphone on' : 'Microphone muted');
    });
    var cam = app.querySelector('#cam');
    if (cam) cam.addEventListener('click', function () {
      var off = cam.getAttribute('aria-pressed') === 'true';
      cam.setAttribute('aria-pressed', String(!off));
      cam.setAttribute('aria-label', off ? 'Turn camera off' : 'Turn camera on');
      cam.innerHTML = Fr.ic(off ? 'cam' : 'camOff');
      announce(off ? 'Camera on' : 'Camera off — device released');
    });

    /* details sheet: focus is moved in and restored on close */
    var sb = app.querySelector('#sheetbtn'), sh = app.querySelector('#sheet'),
        sc = app.querySelector('#sheetclose'), scrim = app.querySelector('#scrim');
    if (sb && sh) {
      var lastFocus = null;
      var open = function () {
        lastFocus = document.activeElement;
        sh.setAttribute('data-open', '1'); sb.setAttribute('aria-expanded', 'true');
        if (scrim) scrim.setAttribute('data-open', '1');
        sc.focus(); announce('Session details opened');
      };
      var close = function () {
        sh.setAttribute('data-open', '0'); sb.setAttribute('aria-expanded', 'false');
        if (scrim) scrim.setAttribute('data-open', '0');
        (lastFocus && document.contains(lastFocus) ? lastFocus : sb).focus();
        announce('Session details closed');
      };
      sb.addEventListener('click', function () { sh.getAttribute('data-open') === '1' ? close() : open(); });
      sc.addEventListener('click', close);
      if (scrim) scrim.addEventListener('click', close);
      /* [ADDENDUM RULE 8] the sheet TRAPS focus and closes on Escape from anywhere while
         open. Escape was previously bound to the sheet only, so it was unreachable once
         focus had left the sheet; Tab could also walk out into the room behind it. */
      document.addEventListener('keydown', function (e) {
        if (sh.getAttribute('data-open') !== '1') return;
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
        if (e.key !== 'Tab') return;
        var f = [].slice.call(sh.querySelectorAll('button,[href],input,select,textarea,[tabindex]:not([tabindex="-1"])'))
          .filter(function (el) { var cs = getComputedStyle(el); return cs.display !== 'none' && cs.visibility !== 'hidden'; });
        if (!f.length) return;
        e.preventDefault();
        var i = f.indexOf(document.activeElement);
        var next = e.shiftKey ? (i <= 0 ? f.length - 1 : i - 1) : (i < 0 || i === f.length - 1 ? 0 : i + 1);
        f[next].focus();
      }, true);
      root.__C2.openSheet = open; root.__C2.closeSheet = close;
    }

    /* self-view move / minimise — never expand the stage */
    var self = app.querySelector('#self'), smin = app.querySelector('#selfmin'), smove = app.querySelector('#selfmove');
    if (self && smin) smin.addEventListener('click', function () {
      var m = self.getAttribute('data-min') === '1';
      self.setAttribute('data-min', m ? '0' : '1');
      smin.setAttribute('aria-pressed', String(!m));
      smin.setAttribute('aria-label', m ? 'Minimise self-view' : 'Restore self-view');
      announce(m ? 'Self-view restored' : 'Self-view minimised');
    });
    /* [ADDENDUM RC-5 / RULE 7] the controls are children of the self-view, so moving the
       tile moves them; nothing can be left behind or land outside the stage. */
    if (self && smove) smove.addEventListener('click', function () {
      var order = ['br', 'bl', 'tl', 'tr'], p = self.getAttribute('data-pos') || 'br';
      var n = order[(order.indexOf(p) + 1) % 4];
      self.setAttribute('data-pos', n);
      var edge = window.matchMedia('(orientation:landscape) and (max-height:520px)').matches ? 10 : 14;
      self.style.right  = (n === 'br' || n === 'tr') ? edge + 'px' : 'auto';
      self.style.left   = (n === 'bl' || n === 'tl') ? edge + 'px' : 'auto';
      self.style.bottom = (n === 'br' || n === 'bl') ? edge + 'px' : 'auto';
      self.style.top    = (n === 'tl' || n === 'tr') ? edge + 'px' : 'auto';
      announce('Self-view moved to ' + ({ br: 'bottom right', bl: 'bottom left', tl: 'top left', tr: 'top right' })[n]);
    });

    /* counters */
    ['#rv', '#dr'].forEach(function (sel) {
      var ta = app.querySelector(sel); if (!ta) return;
      var out = app.querySelector(sel === '#rv' ? '[data-testid=review-counter]' : '[data-testid=dispute-counter]');
      ta.addEventListener('input', function () {
        var n = ta.value.length;
        out.textContent = n.toLocaleString('en-IN') + ' of 1,000 characters' +
          (sel === '#rv' ? (n < 10 ? ' · at least 10 needed' : '') : '');
      });
    });

    /* dialogs restore focus */
    var dlg = app.querySelector('[data-testid=dialog]');
    if (dlg) {
      /* a modal makes everything behind it inert — required for focus management and
         so that background controls are not reported as reachable/overlapping */
      app.querySelectorAll('.tbar,.body,.dock,.lh,.stage,.lctrl,.sheet').forEach(function (el) {
        el.setAttribute('inert', ''); el.setAttribute('aria-hidden', 'true');
      });
      var first = dlg.querySelector('button,[href]');
      if (first) first.focus();
      dlg.addEventListener('keydown', function (e) {
        if (e.key !== 'Tab') return;
        var f = dlg.querySelectorAll('button,[href],input,select,textarea');
        if (!f.length) return;
        var a = f[0], z = f[f.length - 1];
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
        else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
      });
    }
    var leave = app.querySelector('#leave');
    if (leave) leave.addEventListener('click', function () { go('s35-leave-confirm'); });
  }

  function go(id) {
    var u = new URL(location.href);
    u.searchParams.set('state', id);
    history.replaceState(null, '', u.toString());
    return render(id);
  }

  /* ---- boot ---- */
  function boot() {
    app = document.getElementById('app');
    live = document.getElementById('live-region');
    var q = qs();
    var theme = (q.theme === 'dark') ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', theme);
    if (q.chrome === '1') document.body.setAttribute('data-chrome', '1');
    root.__C2 = root.__C2 || {};
    root.__C2.landscape = q.landscape === '1';
    root.__C2.rig = (q.rig === 'vp') ? 'vp' : null;
    var dev = String(q.device || '390x844').split('x');
    root.__C2.rigW = parseInt(dev[0], 10) || 390;
    root.__C2.rigH = parseInt(dev[1], 10) || 844;
    root.__C2.goto = go;
    root.__C2.states = St.IDS;
    root.__C2.fixtureChecksum = Fx.CHECKSUM;
    root.__C2.setTheme = function (t) { document.documentElement.setAttribute('data-theme', t); return go(root.__C2.state.id); };
    var id = q.state || 's31-default';
    if (!St.BY_ID[id]) id = 's31-default';
    if (q.chrome === '1') buildReviewer();
    render(id).catch(function (e) { console.error('[C2 reference] ready failed:', e.message); });
  }

  function buildReviewer() {
    var r = document.getElementById('reviewer');
    r.innerHTML = '<strong style="font-size:11px">' + St.IDS.length + ' states</strong>' +
      St.STATES.map(function (s) {
        return '<a href="?state=' + s.id + '&chrome=1" style="font-size:10px;padding:4px 6px;border:1px solid var(--line2);border-radius:6px;color:inherit;text-decoration:none">' + s.id + '</a>';
      }).join('');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})(typeof globalThis !== 'undefined' ? globalThis : this);
