/* Option C2 reference — pure UI rules (v1).
   PROPOSED. These are the *client-side* obligations the reference demonstrates.
   Every one of them is duplicated server-side in production; the server decision
   always wins. Nothing here is an approved API contract. */
(function (root) {
  'use strict';
  var F = root.C2Fixtures.FIXTURES, inr = root.C2Fixtures.inr;

  var R = {
    /* ---- search ---- */
    normaliseSearch: function (raw) {
      var q = String(raw == null ? '' : raw).replace(/\s+/g, ' ').trim();
      if (!q) return { ok: false, code: 'SEARCH_EMPTY', query: '' };
      if (q.length > 120) return { ok: false, code: 'SEARCH_TOO_LONG', query: q.slice(0, 120) };
      return { ok: true, code: null, query: q };
    },
    /* ---- money: integer paise only, never float arithmetic ---- */
    formatPaise: function (p) {
      if (!Number.isInteger(p)) throw new Error('MONEY_NOT_INTEGER_PAISE');
      return inr(p);
    },
    totalPaise: function () {
      return F.money.feePaise + F.money.taxPaise + F.money.discountPaise;
    },
    /* ---- hold urgency: never colour alone ---- */
    holdUrgency: function (secondsLeft) {
      if (secondsLeft <= 0) return { level: 'expired', code: 'HOLD_EXPIRED', nonColourCue: 'wording + released state', announce: true };
      if (secondsLeft < F.hold.urgentAtSeconds) return { level: 'urgent', code: null, nonColourCue: 'bold text + thicker border + underline + wording', announce: true };
      return { level: 'normal', code: null, nonColourCue: 'plain text', announce: false };
    },
    mmss: function (s) {
      s = Math.max(0, s | 0);
      return ('0' + Math.floor(s / 60)).slice(-2) + ':' + ('0' + (s % 60)).slice(-2);
    },
    /* ---- card ---- */
    validateCard: function (fields) {
      var errs = [];
      if (!fields.number) errs.push('CARD_NUMBER_REQUIRED');
      else if (!/^\d{12,19}$/.test(String(fields.number).replace(/\s/g, ''))) errs.push('CARD_NUMBER_MALFORMED');
      if (!fields.expiry) errs.push('CARD_EXPIRY_REQUIRED');
      else if (!/^\d{2}\s*\/\s*\d{2}$/.test(fields.expiry)) errs.push('CARD_EXPIRY_MALFORMED');
      if (!fields.name) errs.push('CARD_NAME_REQUIRED');
      return { ok: errs.length === 0, codes: errs };
    },
    /* ---- payment challenge (never stored, never logged) ---- */
    validateOtp: function (code, attemptsUsed, expired) {
      if (expired) return { ok: false, code: 'AUTH_CHALLENGE_EXPIRED', attemptsLeft: Math.max(0, F.payment.otpMaxAttempts - attemptsUsed) };
      if (attemptsUsed >= F.payment.otpMaxAttempts) return { ok: false, code: 'AUTH_CHALLENGE_LOCKED', attemptsLeft: 0 };
      var s = String(code == null ? '' : code);
      if (!s) return { ok: false, code: 'AUTH_CHALLENGE_REQUIRED', attemptsLeft: F.payment.otpMaxAttempts - attemptsUsed };
      if (!/^\d+$/.test(s) || s.length !== F.payment.otpLength)
        return { ok: false, code: 'AUTH_CHALLENGE_LENGTH', attemptsLeft: F.payment.otpMaxAttempts - attemptsUsed };
      return { ok: true, code: null, attemptsLeft: F.payment.otpMaxAttempts - attemptsUsed };
    },
    /* ---- cancellation window (server-authoritative in production) ---- */
    cancellationOutcome: function (nowIso, startIso) {
      var now = Date.parse(nowIso), start = Date.parse(startIso), ms = start - now;
      if (ms <= 0) return { outcome: 'closed', code: 'SESSION_ALREADY_STARTED', refundPaise: 0 };
      if (ms >= 24 * 3600 * 1000) return { outcome: 'full_refund', code: null, refundPaise: F.money.totalPaise };
      return { outcome: 'admin_exception', code: 'CANCELLATION_WINDOW_CLOSED', refundPaise: 0 };
    },
    /* ---- review ---- */
    validateReview: function (stars, text) {
      var errs = [];
      if (!Number.isInteger(stars) || stars < F.policy.reviewMinStars || stars > F.policy.reviewMaxStars) errs.push('REVIEW_RATING_OUT_OF_RANGE');
      var n = String(text == null ? '' : text).length;
      if (n < F.policy.reviewMinChars) errs.push('REVIEW_TEXT_TOO_SHORT');
      else if (n > F.policy.reviewMaxChars) errs.push('REVIEW_TEXT_TOO_LONG');
      return { ok: errs.length === 0, codes: errs, length: n };
    },
    /* ---- privacy: canaries must never reach URL / storage / logs ---- */
    privacyScan: function (sample) {
      var hits = [];
      F.privacyCanaries.forEach(function (c) { if (String(sample).indexOf(c) >= 0) hits.push(c); });
      return { clean: hits.length === 0, hits: hits };
    }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = R;
  root.C2Rules = R;
})(typeof globalThis !== 'undefined' ? globalThis : this);
