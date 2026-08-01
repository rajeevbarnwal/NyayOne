/**
 * The PROVIDER-NEUTRAL live-room media client (matrix E1/E3, video seam W2-9).
 *
 * This is the product's own contract for a real-time room, written so that the
 * S-35 live room depends on NO vendor type. Two adapters implement it:
 *
 *   * `livekitVideoRoomClient.ts` — the production adapter, over the
 *     repository-declared, lockfile-pinned `livekit-client` browser package.
 *   * `fakeVideoRoomClient.ts`   — a DETERMINISTIC in-memory adapter that drives
 *     every state and every control with no server at all. It is what the unit
 *     tests and the browser negative journey use, and it is selected at RUNTIME
 *     so the production screen — not a copy of it — is the thing under test.
 *
 * PRIVACY RULES THIS FILE ENCODES (matrix J1, decision D-05):
 *
 *   1. The raw join credential is an ARGUMENT to `connect()` and nothing else.
 *      No implementation may keep it in a field, hand it back through a getter,
 *      put it in an event payload, or let it reach render state. `connect()`
 *      therefore takes it as a one-shot value and the interface offers no way
 *      to read it back.
 *   2. A device is identified by its opaque `deviceId` and an ORDINAL. The
 *      `label` of a media device is never read, so no device name exists in
 *      this process to leak into state, the DOM, a log or an audit snapshot.
 *   3. Participants are identified by the SERVER's opaque `participantRef`.
 *      There is no display name, no email and no private narrative here.
 *   4. Nothing in this module or its adapters writes to storage, a cookie, the
 *      URL or the console. The static canary in `tutoringPrivacy.test.ts`
 *      enforces that by reading the shipped sources.
 */

/* ========================================================================== *
 * Connection states — explicit, and every one of them is a rendered state
 * ========================================================================== */

/**
 * The provider lifecycle, in the product's own vocabulary.
 *
 * `reconnected` is deliberately its own state rather than an immediate return
 * to `connected`: a participant who has just watched the room drop needs to be
 * told it came back, and a spinner cannot say that. It settles to `connected`
 * on its own after `RECONNECTED_SETTLE_MS` (or immediately, when the
 * deterministic adapter's driver is told to settle it).
 */
export const VIDEO_ROOM_STATES = [
  'disconnected',
  'connecting',
  'connected',
  'reconnecting',
  'reconnected',
  'failed',
] as const;

export type VideoRoomState = (typeof VIDEO_ROOM_STATES)[number];

/** How long `reconnected` is shown before it settles back to `connected`. */
export const RECONNECTED_SETTLE_MS = 2500;

/* ========================================================================== *
 * Typed refusals — a room never fails with a bare spinner
 * ========================================================================== */

/**
 * Every way a room can refuse or fall over, as a CODE the screen branches on.
 * The first four mirror the server's own credential verdicts so that a refusal
 * issued by the API and a refusal issued by the media provider land in exactly
 * one rendering path.
 */
export const VIDEO_ROOM_FAILURE_CODES = [
  'CREDENTIAL_EXPIRED',
  'CREDENTIAL_REVOKED',
  'WRONG_PARTICIPANT',
  'SESSION_CANCELLED',
  'NOT_ADMITTED',
  'VIDEO_CALLS_DISABLED',
  'PROVIDER_NOT_CONFIGURED',
  'PROVIDER_UNAVAILABLE',
  'TRANSPORT_LOST',
  'MEDIA_REFUSED',
  'UNKNOWN',
] as const;

export type VideoRoomFailureCode = (typeof VIDEO_ROOM_FAILURE_CODES)[number];

export interface VideoRoomFailure {
  readonly code: VideoRoomFailureCode;
  /**
   * `true` when the client has stopped trying: the room is in `failed` and only
   * a participant action can move it. `false` is a failure the client is still
   * working through — it accompanies `reconnecting`, never `failed`.
   */
  readonly terminal: boolean;
  /**
   * Whether asking the SERVER for a fresh credential could plausibly help. An
   * expired or revoked grant can be reissued; a wrong participant or a cancelled
   * session cannot, and offering the button would be a lie.
   */
  readonly reissuable: boolean;
}

const REISSUABLE: ReadonlySet<VideoRoomFailureCode> = new Set([
  'CREDENTIAL_EXPIRED',
  'CREDENTIAL_REVOKED',
  'PROVIDER_UNAVAILABLE',
  'TRANSPORT_LOST',
]);

/** Build a typed failure. `terminal` defaults to true because `failed` is. */
export function videoRoomFailure(
  code: VideoRoomFailureCode,
  { terminal = true }: { terminal?: boolean } = {},
): VideoRoomFailure {
  return { code, terminal, reissuable: REISSUABLE.has(code) };
}

/**
 * Map a SERVER refusal code (`tutoringApi`'s typed codes, which come straight
 * from `backend/app/services/tutoring/errors.py`) onto a room failure, so the
 * screen renders one vocabulary whether the refusal came from the credential
 * endpoint or from the media provider.
 */
export function videoRoomFailureFromServerCode(code: string): VideoRoomFailure {
  switch (code) {
    case 'GRANT_EXPIRED':
      return videoRoomFailure('CREDENTIAL_EXPIRED');
    case 'GRANT_REVOKED':
      return videoRoomFailure('CREDENTIAL_REVOKED');
    case 'FORBIDDEN':
    case 'forbidden':
    case 'NOT_FOUND':
      return videoRoomFailure('WRONG_PARTICIPANT');
    case 'SESSION_STATE_INVALID':
      return videoRoomFailure('SESSION_CANCELLED');
    case 'VIDEO_CALLS_DISABLED':
      return videoRoomFailure('VIDEO_CALLS_DISABLED');
    case 'PROVIDER_UNAVAILABLE':
      return videoRoomFailure('PROVIDER_UNAVAILABLE');
    case 'AUTHENTICATION_REQUIRED':
      return videoRoomFailure('NOT_ADMITTED');
    default:
      return videoRoomFailure('UNKNOWN');
  }
}

/* ========================================================================== *
 * Devices — id and ordinal only, never a label
 * ========================================================================== */

export type VideoRoomDeviceKind = 'audioinput' | 'videoinput';

/**
 * A selectable capture device.
 *
 * There is NO name field, on purpose. `MediaDeviceInfo.label` carries the
 * hardware's own string ("FaceTime HD Camera (Built-in)"), which is a stable
 * identifier for a person's machine; the product shows "Camera 1 / Camera 2"
 * built from `ordinal` instead, and the label is never read at all.
 */
export interface VideoRoomDevice {
  readonly deviceId: string;
  readonly kind: VideoRoomDeviceKind;
  /** 1-based position within its kind. The only thing a human sees. */
  readonly ordinal: number;
}

/** The devices a participant chose, if any. Ids only. */
export interface VideoRoomDeviceChoice {
  readonly audioinput?: string;
  readonly videoinput?: string;
}

/* ========================================================================== *
 * Participants
 * ========================================================================== */

export interface VideoRoomParticipant {
  /** The SERVER's opaque participant reference. Never a name. */
  readonly participantRef: string;
  readonly local: boolean;
  readonly microphoneEnabled: boolean;
  readonly cameraEnabled: boolean;
  readonly screenShareEnabled: boolean;
  /** Camera media, once it is flowing. `null` before that, and after release. */
  readonly cameraStream: MediaStream | null;
  /** Screen-share media, once it is flowing. */
  readonly screenStream: MediaStream | null;
}

/* ========================================================================== *
 * The client
 * ========================================================================== */

export interface VideoRoomConnectOptions {
  /**
   * The RAW, short-lived, participant/room/permission-bound credential the
   * server issued. It is consumed by this call and MUST NOT be retained by the
   * implementation, echoed in an event, or exposed through any getter.
   */
  readonly token: string;
  readonly roomRef: string;
  readonly participantRef: string;
  readonly permissions: readonly string[];
  /** Runtime browser endpoint returned by the backend capability/credential. */
  readonly serverUrl?: string | null;
  /** Server-authoritative ICE path. ``relay`` forces TURN; ``all`` permits direct fallback. */
  readonly iceTransportPolicy?: 'all' | 'relay';
  /**
   * Local capture the room already opened for its self-view. Ownership passes
   * to the client: `leave()` stops every track on it.
   */
  readonly localStream?: MediaStream | null;
  readonly devices?: VideoRoomDeviceChoice;
  readonly publishAudio?: boolean;
  readonly publishVideo?: boolean;
}

export interface VideoRoomEventMap {
  /** Any change of connection state, with the failure that explains it. */
  state: (state: VideoRoomState, failure: VideoRoomFailure | null) => void;
  /** The full participant list, local first. Emitted whenever it changes. */
  participants: (participants: readonly VideoRoomParticipant[]) => void;
  /** The selectable device list, whenever it is (re)enumerated. */
  devices: (devices: readonly VideoRoomDevice[]) => void;
}

export type VideoRoomTransport = 'livekit' | 'deterministic';

export interface VideoRoomClient {
  /** Which adapter this is. Rendered, so a run can never be mistaken. */
  readonly transport: VideoRoomTransport;

  getState(): VideoRoomState;
  getFailure(): VideoRoomFailure | null;
  getParticipants(): readonly VideoRoomParticipant[];
  getDevices(): readonly VideoRoomDevice[];

  /** Subscribe. Returns the unsubscribe function. */
  on<K extends keyof VideoRoomEventMap>(event: K, handler: VideoRoomEventMap[K]): () => void;

  connect(options: VideoRoomConnectOptions): Promise<void>;
  /** Stop the transport but keep the object usable for a later `connect()`. */
  disconnect(): Promise<void>;

  setMicrophoneEnabled(enabled: boolean): Promise<void>;
  setCameraEnabled(enabled: boolean): Promise<void>;
  setScreenShareEnabled(enabled: boolean): Promise<void>;

  /** Enumerate capture devices. Ids and ordinals only — never a label. */
  listDevices(): Promise<readonly VideoRoomDevice[]>;
  selectDevice(kind: VideoRoomDeviceKind, deviceId: string): Promise<void>;

  /**
   * Leave for good: disconnect, unpublish, stop EVERY track this client holds
   * (including the stream handed to `connect`) and drop every listener. After
   * this the camera and microphone indicators are off.
   */
  leave(): Promise<void>;
}

/* ========================================================================== *
 * Shared state machine
 * ========================================================================== */

type Listeners = {
  [K in keyof VideoRoomEventMap]: Set<VideoRoomEventMap[K]>;
};

/**
 * The piece of the contract both adapters share: one state, one failure, one
 * participant list, one device list, and the `reconnected -> connected` settle.
 *
 * Keeping it here is what makes the two adapters answer identically — the fake
 * cannot drift into a state machine the real one does not have, because there
 * is only one implementation of the transitions.
 */
export class VideoRoomHub {
  private state: VideoRoomState = 'disconnected';
  private failure: VideoRoomFailure | null = null;
  private participants: readonly VideoRoomParticipant[] = [];
  private devices: readonly VideoRoomDevice[] = [];
  private settleTimer: ReturnType<typeof setTimeout> | null = null;

  private readonly listeners: Listeners = {
    state: new Set(),
    participants: new Set(),
    devices: new Set(),
  };

  /**
   * `0` disables the automatic `reconnected -> connected` settle, which is what
   * the deterministic adapter uses: its driver settles explicitly so a browser
   * assertion can observe `reconnected` without racing a timer.
   */
  constructor(private readonly autoSettleMs: number = RECONNECTED_SETTLE_MS) {}

  on<K extends keyof VideoRoomEventMap>(event: K, handler: VideoRoomEventMap[K]): () => void {
    this.listeners[event].add(handler as never);
    return () => { this.listeners[event].delete(handler as never); };
  }

  getState(): VideoRoomState { return this.state; }
  getFailure(): VideoRoomFailure | null { return this.failure; }
  getParticipants(): readonly VideoRoomParticipant[] { return this.participants; }
  getDevices(): readonly VideoRoomDevice[] { return this.devices; }

  setState(next: VideoRoomState, failure: VideoRoomFailure | null = null): void {
    this.clearSettle();
    const changed = next !== this.state || failure?.code !== this.failure?.code;
    this.state = next;
    this.failure = failure;
    if (next === 'reconnected' && this.autoSettleMs > 0) {
      this.settleTimer = setTimeout(() => {
        this.settleTimer = null;
        if (this.state === 'reconnected') this.setState('connected');
      }, this.autoSettleMs);
    }
    if (changed) for (const fn of this.listeners.state) fn(this.state, this.failure);
  }

  /** Move `reconnected` on to `connected` now. No-op in any other state. */
  settle(): void {
    if (this.state === 'reconnected') this.setState('connected');
  }

  setParticipants(next: readonly VideoRoomParticipant[]): void {
    this.participants = next;
    for (const fn of this.listeners.participants) fn(this.participants);
  }

  setDevices(next: readonly VideoRoomDevice[]): void {
    this.devices = next;
    for (const fn of this.listeners.devices) fn(this.devices);
  }

  /** Drop every listener and pending timer. Called from `leave()`. */
  dispose(): void {
    this.clearSettle();
    this.listeners.state.clear();
    this.listeners.participants.clear();
    this.listeners.devices.clear();
  }

  private clearSettle(): void {
    if (this.settleTimer !== null) {
      clearTimeout(this.settleTimer);
      this.settleTimer = null;
    }
  }
}

/* ========================================================================== *
 * Device enumeration — the one place `enumerateDevices` is allowed
 * ========================================================================== */

/**
 * Enumerate capture devices as `{ deviceId, kind, ordinal }`.
 *
 * `device.label` is NOT read. That is the whole point of this function existing
 * once instead of at every call site: there is exactly one place a label could
 * be picked up, and it does not pick one up.
 */
export async function enumerateVideoRoomDevices(): Promise<readonly VideoRoomDevice[]> {
  const media = typeof navigator === 'undefined' ? undefined : navigator.mediaDevices;
  if (!media?.enumerateDevices) return [];
  const found = await media.enumerateDevices();
  const counters: Record<VideoRoomDeviceKind, number> = { audioinput: 0, videoinput: 0 };
  const out: VideoRoomDevice[] = [];
  for (const device of found) {
    const kind = device.kind === 'audioinput' || device.kind === 'videoinput'
      ? device.kind
      : null;
    if (!kind) continue;
    counters[kind] += 1;
    out.push({ deviceId: device.deviceId, kind, ordinal: counters[kind] });
  }
  return out;
}

/** The human-facing name of a device. Built from the ordinal, never the hardware. */
export function videoRoomDeviceName(device: VideoRoomDevice): string {
  return device.kind === 'videoinput' ? `Camera ${device.ordinal}` : `Microphone ${device.ordinal}`;
}

/* ========================================================================== *
 * The device choice a participant made at pre-join — in memory, nowhere else
 * ========================================================================== */

let preferredDevices: VideoRoomDeviceChoice = {};

/**
 * Carry the pre-join device choice into the room.
 *
 * A module-scoped value, deliberately: the alternative would be the URL (which
 * would publish a stable hardware identifier into history and every referrer)
 * or storage (which the tutoring surface does not touch at all). It lives for
 * the tab's lifetime and is cleared when the participant leaves.
 */
export function setPreferredDevices(choice: VideoRoomDeviceChoice): void {
  preferredDevices = { ...preferredDevices, ...choice };
}

export function getPreferredDevices(): VideoRoomDeviceChoice {
  return preferredDevices;
}

export function clearPreferredDevices(): void {
  preferredDevices = {};
}

/* ========================================================================== *
 * Runtime adapter selection
 * ========================================================================== */

interface TransportWindow {
  __legalsaathiVideoTransport?: string;
}

interface ViteEnv {
  env?: { VITE_VIDEO_ROOM_URL?: string; VITE_VIDEO_TRANSPORT?: string };
}

/** The media server the LiveKit adapter dials. Empty means "not configured". */
export function videoRoomServerUrl(): string {
  return (import.meta as unknown as ViteEnv).env?.VITE_VIDEO_ROOM_URL ?? '';
}

/**
 * Which adapter to build.
 *
 * The deterministic adapter is opt-in and only ever by an explicit request:
 * a `__legalsaathiVideoTransport` global installed BEFORE the app boots (what
 * the browser journey does, so it drives the production screen rather than a
 * copy of it), or a build-time `VITE_VIDEO_TRANSPORT`. With neither, the
 * production LiveKit adapter is what a participant gets.
 */
export function requestedVideoTransport(): VideoRoomTransport {
  const fromWindow = typeof window === 'undefined'
    ? undefined
    : (window as unknown as TransportWindow).__legalsaathiVideoTransport;
  const fromEnv = (import.meta as unknown as ViteEnv).env?.VITE_VIDEO_TRANSPORT;
  return (fromWindow ?? fromEnv) === 'deterministic' ? 'deterministic' : 'livekit';
}

/**
 * Build the client for this runtime.
 *
 * The LiveKit adapter is loaded lazily so the vendor bundle is a separate chunk
 * that a participant only pays for when they actually enter a room.
 */
export async function createVideoRoomClient(): Promise<VideoRoomClient> {
  if (requestedVideoTransport() === 'deterministic') {
    const { createFakeVideoRoomClient } = await import('./fakeVideoRoomClient');
    return createFakeVideoRoomClient();
  }
  const { createLiveKitVideoRoomClient } = await import('./livekitVideoRoomClient');
  return createLiveKitVideoRoomClient();
}
