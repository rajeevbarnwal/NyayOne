/**
 * Privacy canaries for the Wave 2 tutoring surface (matrix J1, decisions D-05
 * and D-14; reference ACCESSIBILITY_AND_INTERACTION_SPEC §9).
 *
 * Two independent gates, because either alone can be fooled:
 *   1. RUNTIME — every adapter call in the full journey runs against spying
 *      storage, cookie and history objects, and nothing may be written. The
 *      credential response deliberately carries a canary string that must not
 *      appear in any storage write, cookie, URL, request body or query key.
 *   2. STATIC — the shipped tutoring sources are read from disk and must not
 *      contain a storage API, a media-plane API, a device-label read or a
 *      console call at all. This catches a leak added on a code path a unit
 *      test never reaches.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  cancelSession,
  confirmAttendance,
  createBookingHold,
  createPaymentOrder,
  createReview,
  createTutoringSession,
  disputeAttendance,
  getAvailability,
  getBookingHold,
  getTutor,
  getTutoringSession,
  issueJoinCredentials,
  listTutoringSessions,
  redactJoinCredential,
  rescheduleSession,
  searchTutors,
} from '../lib/tutoringApi';

/** Values that must never reach storage, a cookie, the URL, a log or a body. */
const CANARIES = {
  pan: '4111111111111111',
  cvv: '737',
  otp: '408215',
  joinToken: 'jointoken-CANARY-must-never-persist',
  sdp: 'v=0\r\no=- 46117 2 IN IP4 127.0.0.1',
  ice: 'candidate:842163049 1 udp 1677729535 192.0.2.10 54321 typ srflx',
  deviceLabel: 'FaceTime HD Camera (Built-in)',
} as const;

interface Write { key: string; value: string }

function spyStorage(sink: Write[]): Storage {
  return {
    get length() { return 0; },
    clear: () => {},
    getItem: () => null,
    key: () => null,
    removeItem: () => {},
    setItem: (key: string, value: string) => { sink.push({ key, value }); },
  } as unknown as Storage;
}

describe('runtime canaries: no forbidden value is ever persisted', () => {
  let writes: Write[];
  let cookies: string[];
  let historyUrls: string[];
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    writes = [];
    cookies = [];
    historyUrls = [];
    vi.stubGlobal('localStorage', spyStorage(writes));
    vi.stubGlobal('sessionStorage', spyStorage(writes));
    vi.stubGlobal('document', {
      get cookie() { return ''; },
      set cookie(value: string) { cookies.push(value); },
    });
    vi.stubGlobal('history', {
      pushState: (_s: unknown, _t: string, url: string) => { historyUrls.push(url); },
      replaceState: (_s: unknown, _t: string, url: string) => { historyUrls.push(url); },
    });
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const respond = (body: unknown, status = 200): void => {
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }));
  };

  it('runs the whole journey without writing to storage, a cookie or the URL', async () => {
    respond({ items: [], total: 0, limit: 20, offset: 0, has_more: false, sort: 'rating_desc', allowed_sorts: [] });
    await searchTutors({ q: 'arbitration' });

    respond({
      id: 't', display_name: 'Adv. A', headline: null, experience_years: 3,
      rating_avg: null, rating_count: 0, verified_identity: true, verified_credentials: false,
      status: 'published', source: 'self_declared', source_url: null, retrieved_at: null,
      subjects: [], rating_aggregate: { tutor_id: 't', rating_count: 0, rating_avg: null, distribution: {} },
    });
    await getTutor('t');

    respond({
      tutor_id: 't', iana_timezone: 'Asia/Kolkata',
      window: { from_utc: null, to_utc: null }, local_resolution: {}, slots: [], limit: 50, offset: 0,
    });
    await getAvailability('t');

    const hold = { id: 'h', slot_id: 's', status: 'active', expires_at: '2026-08-05T12:10:00+00:00', hold_minutes: 10 };
    respond(hold, 201);
    await createBookingHold({ slotId: 's', idempotencyKey: 'k' });
    respond({ ...hold, expired: false });
    await getBookingHold('h');

    respond({
      id: 'o', hold_id: 'h', provider: 'deterministic', provider_order_ref: 'ord_1',
      amount_paise: 96082, currency: 'INR', status: 'created',
      // Issuer display crumbs are all the API returns — never a PAN.
      brand: 'Visa', masked_last4: '1111',
    }, 201);
    await createPaymentOrder({ holdId: 'h', amountPaise: 96082, idempotencyKey: 'o' });

    const session = {
      id: 'sess', slot_id: 's', tutor_id: 't', student_user_id: 'u', order_id: 'o',
      status: 'scheduled', version: 1,
      start_utc: '2026-08-05T13:00:00+00:00', end_utc: '2026-08-05T13:45:00+00:00',
      iana_timezone: 'Asia/Kolkata',
      start_local: '2026-08-05T18:30:00+05:30', end_local: '2026-08-05T19:15:00+05:30',
      attendance_state: 'marked', attendance_version: 1,
    };
    respond({ ...session, replayed: false, reminder_jobs: 3 }, 201);
    await createTutoringSession('h');
    respond({ items: [session], role: 'student', limit: 50, offset: 0 });
    await listTutoringSessions();
    respond(session);
    await getTutoringSession('sess');
    respond({ ...session, reminders_revoked: 0 });
    await rescheduleSession({ sessionId: 'sess', newSlotId: 's2', expectedVersion: 1 });
    respond({ ...session, status: 'cancelled', refund: null, refund_id: null, reminders_revoked: 1 });
    await cancelSession({ sessionId: 'sess', expectedVersion: 1 });

    const attendance = {
      session_id: 'sess', state: 'confirmed', version: 2, recorded_by_role: 'tutor',
      recorded_at: null, confirmed_at: null, disputed_at: null, resolved_at: null,
      resolution: null, session_status: 'completed',
    };
    respond(attendance);
    await confirmAttendance({ sessionId: 'sess', expectedVersion: 1 });
    respond({ ...attendance, state: 'disputed' });
    await disputeAttendance({ sessionId: 'sess', expectedVersion: 2, reasonCode: 'tutor_absent' });

    // E1 — the ONE response that legitimately carries a raw credential, plus
    // media-plane values the client must refuse to retain even if handed them.
    respond({
      session_id: 'sess', grant_id: 'g', room_ref: 'room_1', participant_ref: 'part_1',
      permissions: ['publish'], join_token: CANARIES.joinToken,
      issued_at: null, expires_at: null, ttl_seconds: 300, superseded: false,
      sdp: CANARIES.sdp, ice_candidate: CANARIES.ice, device_label: CANARIES.deviceLabel,
    }, 201);
    const credential = await issueJoinCredentials('sess');
    expect(credential.joinToken).toBe(CANARIES.joinToken);

    respond({
      id: 'r', session_id: 'sess', tutor_id: 't', rating: 5, body: null, published: false,
      edit_deadline_at: null, deleted: false, moderation_state: 'pending', rating_aggregate: null,
    }, 201);
    await createReview({ sessionId: 'sess', rating: 5 });

    // ---- the assertions -------------------------------------------------- //
    expect(writes).toEqual([]);
    expect(cookies).toEqual([]);
    expect(historyUrls).toEqual([]);

    const allCanaries = Object.values(CANARIES);
    const bodies = fetchMock.mock.calls
      .map(([, init]) => String((init as RequestInit | undefined)?.body ?? ''))
      .join('\n');
    const urls = fetchMock.mock.calls.map(([url]) => String(url)).join('\n');
    for (const canary of allCanaries) {
      expect(bodies).not.toContain(canary);
      expect(urls).not.toContain(canary);
    }

    // The adapter must not smuggle a media-plane field back out either.
    const projected = JSON.stringify(redactJoinCredential(credential));
    expect(projected).not.toContain(CANARIES.joinToken);
    expect(projected).not.toContain(CANARIES.sdp);
    expect(projected).not.toContain(CANARIES.ice);
    expect(projected).not.toContain(CANARIES.deviceLabel);
    expect(projected).toContain('[redacted]');
  });

  it('never sends a card, security code or authentication code field', async () => {
    respond({
      id: 'o', hold_id: 'h', provider: 'deterministic', provider_order_ref: 'ord_1',
      amount_paise: 1, currency: 'INR', status: 'created', brand: null, masked_last4: null,
    }, 201);
    await createPaymentOrder({ holdId: 'h', amountPaise: 1, idempotencyKey: 'o' });
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    for (const forbidden of [
      'pan', 'card_number', 'cardNumber', 'cvv', 'cvc', 'security_code',
      'otp', 'one_time_code', 'expiry', 'exp_month', 'exp_year', 'name_on_card',
      'sdp', 'ice_candidate', 'device_label',
    ]) {
      expect(Object.keys(body)).not.toContain(forbidden);
    }
    expect(Object.keys(body).sort()).toEqual(
      ['amount_paise', 'currency', 'hold_id', 'idempotency_key'],
    );
  });

  it('refuses a PAN typed into the token field without touching the network', async () => {
    await expect(createPaymentOrder({
      holdId: 'h', amountPaise: 1, idempotencyKey: 'o', paymentToken: CANARIES.pan,
    })).rejects.toMatchObject({ code: 'FORBIDDEN_PAYMENT_FIELD', field: 'payment_token' });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(writes).toEqual([]);
    // The rejection itself must not carry the value it refused.
    try {
      await createPaymentOrder({
        holdId: 'h', amountPaise: 1, idempotencyKey: 'o', paymentToken: CANARIES.pan,
      });
    } catch (error) {
      expect(String((error as Error).message)).not.toContain(CANARIES.pan);
    }
  });
});

/* ========================================================================== *
 * Static canaries over the shipped sources
 * ========================================================================== */

const ROOT = join(process.cwd(), 'src', 'features', 'student');
const SOURCES = [
  join(ROOT, 'lib', 'tutoringApi.ts'),
  join(ROOT, 'lib', 'tutoringRules.ts'),
  join(ROOT, 'tutoring', 'TutoringPrimitives.tsx'),
  join(ROOT, 'tutoring', 'TutorDiscoveryScreens.tsx'),
  join(ROOT, 'tutoring', 'BookingScreens.tsx'),
  join(ROOT, 'tutoring', 'SessionScreens.tsx'),
];

/** Source with block and line comments removed, so prose cannot pass or fail a gate. */
function code(path: string): string {
  return readFileSync(path, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/.*$/gm, '$1 ');
}

describe('static canaries over the shipped tutoring sources', () => {
  it('reads every source it claims to check', () => {
    for (const path of SOURCES) expect(code(path).length).toBeGreaterThan(200);
  });

  it('contains no web-storage, cookie or URL-persistence API at all', () => {
    for (const path of SOURCES) {
      const source = code(path);
      for (const forbidden of [
        'localStorage', 'sessionStorage', 'document.cookie', 'indexedDB',
        'openDatabase', 'window.name', 'caches.open',
      ]) {
        expect(source, `${path} must not use ${forbidden}`).not.toContain(forbidden);
      }
    }
  });

  it('contains no media-plane API, so no SDP or ICE candidate can exist', () => {
    for (const path of SOURCES) {
      const source = code(path);
      for (const forbidden of [
        'RTCPeerConnection', 'RTCSessionDescription', 'RTCIceCandidate',
        'createOffer', 'createAnswer', 'setLocalDescription', 'setRemoteDescription',
        'onicecandidate', 'addIceCandidate', 'localDescription', 'remoteDescription',
      ]) {
        expect(source, `${path} must not use ${forbidden}`).not.toContain(forbidden);
      }
    }
  });

  it('never reads a media device label', () => {
    // Every `x.label` read in the tutoring sources must have a receiver on this
    // allow-list. Adding `device.label` (or `d.label` inside an
    // enumerateDevices map) breaks this assertion immediately.
    const ALLOWED_RECEIVERS = new Set(['countdown', 't', 'labels']);
    for (const path of SOURCES) {
      const source = code(path);
      const receivers = [...source.matchAll(/([A-Za-z_$][\w$]*)\s*\.label\b/g)]
        .map((match) => match[1]);
      for (const receiver of receivers) {
        expect(ALLOWED_RECEIVERS, `${path} reads .label on ${receiver}`).toContain(receiver);
      }
    }
  });

  it('enumerates devices for a COUNT only, in exactly one place', () => {
    const users = SOURCES.filter((path) => code(path).includes('enumerateDevices'));
    expect(users).toHaveLength(1);
    const source = code(users[0]);
    // The only properties read off an enumerated device.
    expect(source).toMatch(/\.kind === 'videoinput'/);
    expect(source).toMatch(/\.kind === 'audioinput'/);
  });

  it('logs nothing at all from the tutoring surface', () => {
    for (const path of SOURCES) {
      expect(code(path), `${path} must not log`).not.toMatch(/\bconsole\s*\./);
    }
  });

  it('declares no input capable of holding a card number, code or OTP', () => {
    for (const path of SOURCES) {
      const source = code(path);
      for (const forbidden of [
        'autocomplete="cc-number"', 'autocomplete="cc-csc"', 'autocomplete="cc-exp"',
        'autocomplete="one-time-code"', 'autoComplete="cc-number"', 'autoComplete="cc-csc"',
        'autoComplete="one-time-code"',
      ]) {
        expect(source, `${path} must not declare ${forbidden}`).not.toContain(forbidden);
      }
    }
  });

  it('keeps the raw join credential in a ref and only renders the redaction', () => {
    const room = code(join(ROOT, 'tutoring', 'SessionScreens.tsx'));
    // The raw credential is a ref, never React state.
    expect(room).toMatch(/rawCredential\s*=\s*useRef<JoinCredential \| null>\(null\)/);
    expect(room).toMatch(/useState<RedactedJoinCredential \| null>\(null\)/);
    // It is dropped on unmount and on leave.
    expect(room.match(/rawCredential\.current = null/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
    // The raw token is never handed to render state or a query cache.
    expect(room).not.toMatch(/setCredential\(\s*issued\s*\)/);
    expect(room).not.toMatch(/setQueryData\([^)]*credential/i);
  });
});
