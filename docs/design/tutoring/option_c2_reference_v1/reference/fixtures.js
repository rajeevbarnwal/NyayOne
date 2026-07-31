/* Option C2 reference — frozen deterministic fixtures (v1).
   PRODUCT_APPROVED values are frozen by the Wave 2 brief and the approved C2 package.
   Money is INTEGER PAISE everywhere; rendering is the only place ₹ appears.
   Nothing here is production-like: every reference/id is explicitly test-only. */
(function (root) {
  'use strict';

  var FIXTURES = {
    contractVersion: 'option-c2-reference-v1',
    tutor: {
      id: 'tut_meera_krishnan',
      name: 'Adv. Meera Krishnan',
      practiceArea: 'Arbitration & ADR',
      city: 'Bengaluru',
      years: 11,
      languages: 'English · Hindi · Kannada',
      ratingValue: 4.8,
      ratingCount: 126,
      verified: true,
      monogram: 'MK',
      bio: 'Arbitration counsel and clause-drafting mentor. Sessions are case-led: bring a live clause or an award you cannot read, and we work it end to end.',
      quote: 'Bring me a bad clause. We will fix it together and you will never draft one again.'
    },
    tutorAlt: {
      id: 'tut_rohan_deshpande',
      name: 'Adv. Rohan Deshpande',
      practiceArea: 'Criminal · BNSS',
      city: 'Mumbai',
      years: 8,
      languages: 'English · Hindi · Marathi',
      ratingValue: 4.7,
      ratingCount: 98,
      verified: true,
      monogram: 'RD',
      bio: 'Trial-craft mentor. Bail applications and cross-examination drills run like a real hearing.',
      quote: 'We will run your bail application like a real hearing.'
    },
    slot: {
      id: 'slt_0805_1830',
      startIso: '2026-08-05T18:30:00+05:30',
      endIso: '2026-08-05T19:15:00+05:30',
      label: 'Wed, 5 Aug 2026 · 6:30–7:15 PM',
      dateLabel: 'Wed, 5 Aug 2026',
      timeLabel: '6:30–7:15 PM',
      durationMin: 45,
      timezone: 'Asia/Kolkata',
      timezoneLabel: 'Asia/Kolkata (IST)',
      status: 'available'
    },
    slotsOther: [
      { id: 'slt_0605_1100', label: 'Thu, 6 Aug 2026 · 11:00–11:45 AM', status: 'held' },
      { id: 'slt_0705_1900', label: 'Fri, 7 Aug 2026 · 7:00–7:45 PM', status: 'booked' },
      { id: 'slt_1005_1000', label: 'Mon, 10 Aug 2026 · 10:00–10:45 AM', status: 'available' }
    ],
    money: {
      currency: 'INR',
      feePaise: 89900,
      taxPaise: 16182,
      discountPaise: -10000,
      totalPaise: 96082,
      totalDisplay: '₹960.82',
      feeDisplay: '₹899.00',
      taxDisplay: '₹161.82',
      discountDisplay: '−₹100.00',
      taxLabel: 'GST (18%)',
      discountCode: 'FIRSTSESSION'
    },
    hold: { ttlSeconds: 600, urgentAtSeconds: 120, defaultRemaining: '07:12' },
    refs: {
      booking: 'LS-TUT-TEST-20260805-0042',
      payment: 'pay_TEST_8f3k2Q',
      refund: 'rfnd_TEST_2m9x1L',
      idempotency: 'idem_TEST_7c41e9',
      audit: 'AUD-TEST-2026-000481',
      joinToken: 'join_TEST_do-not-log',
      note: 'All references are test-only literals. No production identifier, PAN, CVV, payment OTP or PII appears in this package.'
    },
    payment: {
      methodDisplay: 'Visa •••• 1111',
      cardNumberDisplay: '4111 1111 1111 1111',
      expiryDisplay: '12 / 28',
      cvvDisplay: '•••',
      nameOnCard: 'Aditi Nair',
      environmentLabel: 'Test environment · fictional card',
      otpLength: 6,
      otpMaxAttempts: 3
    },
    session: {
      topic: 'Interim relief under Section 9',
      joinOpensLabel: 'Join opens 6:15 PM',
      joinOpensIso: '2026-08-05T18:15:00+05:30',
      elapsedLabel: '12:04 / 45:00',
      recording: 'Not recorded',
      reminders: '7 days · 1 day · 3 hours before'
    },
    policy: {
      freeCancelCutoffIso: '2026-08-04T18:30:00+05:30',
      freeCancelCutoffLabel: 'Tue, 4 Aug 2026 · 6:30 PM IST',
      refundWindowLabel: '5–7 working days',
      reviewMinChars: 10,
      reviewMaxChars: 1000,
      reviewMinStars: 1,
      reviewMaxStars: 5
    },
    /* strings that MUST NOT appear in any URL, storage, log or evidence artefact */
    privacyCanaries: [
      'CANARY-PAN-4111111111111111',
      'CANARY-CVV-737',
      'CANARY-OTP-419273',
      'CANARY-JOINTOKEN-do-not-log',
      'CANARY-NARRATIVE-private-matter'
    ]
  };

  /* Deterministic 64-bit FNV-1a over the canonical (key-sorted) JSON form.
     Reproducible identically in Node and in the browser, no crypto dependency. */
  function canonical(v) {
    if (v === null || typeof v !== 'object') return JSON.stringify(v);
    if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
    return '{' + Object.keys(v).sort().map(function (k) {
      return JSON.stringify(k) + ':' + canonical(v[k]);
    }).join(',') + '}';
  }
  function fnv1a64(str) {
    var h = [0xcbf2, 0x9ce4, 0x8422, 0x2325];
    for (var i = 0; i < str.length; i++) {
      var bytes = [], c = str.charCodeAt(i);
      if (c < 0x80) bytes = [c];
      else if (c < 0x800) bytes = [0xc0 | (c >> 6), 0x80 | (c & 63)];
      else bytes = [0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63)];
      for (var b = 0; b < bytes.length; b++) {
        h[3] ^= bytes[b];
        var t0 = h[3] * 0x01b3, t1 = h[2] * 0x01b3, t2 = h[1] * 0x01b3, t3 = h[0] * 0x01b3;
        t2 += h[3] * 0x0100; t1 += h[2] * 0x0100; t0 += h[1] * 0x0100;
        /* propagate carries, 16 bits per limb */
        var c0 = t0 & 0xffff, r0 = Math.floor(t0 / 0x10000);
        var s1 = t1 + r0, c1 = s1 & 0xffff, r1 = Math.floor(s1 / 0x10000);
        var s2 = t2 + r1, c2 = s2 & 0xffff, r2 = Math.floor(s2 / 0x10000);
        var s3 = t3 + r2, c3 = s3 & 0xffff;
        h = [c3, c2, c1, c0];
      }
    }
    return h.map(function (x) { return ('000' + x.toString(16)).slice(-4); }).join('');
  }

  var canonicalForm = canonical(FIXTURES);
  var CHECKSUM = fnv1a64(canonicalForm);

  var API = {
    FIXTURES: FIXTURES,
    canonical: canonical,
    fnv1a64: fnv1a64,
    canonicalForm: canonicalForm,
    CHECKSUM: CHECKSUM,
    /* paise -> "₹960.82" (integer paise in, string out; never float maths) */
    inr: function (paise) {
      var neg = paise < 0, p = Math.abs(paise);
      var rupees = Math.floor(p / 100), rem = ('0' + (p % 100)).slice(-2);
      var s = String(rupees), lastThree = s.slice(-3), other = s.slice(0, -3);
      if (other) lastThree = ',' + lastThree;
      var grouped = other.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + lastThree;
      return (neg ? '−₹' : '₹') + grouped + '.' + rem;
    }
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = API;
  root.C2Fixtures = API;
  root.__C2_FIXTURE_CHECKSUM = CHECKSUM;
})(typeof globalThis !== 'undefined' ? globalThis : this);
