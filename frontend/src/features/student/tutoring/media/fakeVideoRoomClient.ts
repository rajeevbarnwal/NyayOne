/**
 * The DETERMINISTIC `VideoRoomClient` adapter.
 *
 * Same interface, same state machine (it shares `VideoRoomHub` with the LiveKit
 * adapter, so it cannot drift into transitions the real one does not have), but
 * no server, no signalling and no wall-clock timers. Every transition happens
 * because something asked for it.
 *
 * WHY IT SHIPS RATHER THAN LIVING IN A TEST FOLDER. The point of the browser
 * negative journey is to exercise the PRODUCTION S-35 screen and its REAL
 * adapter boundary. A test-only double linked into a test-only page would
 * prove something about the double. This adapter is selected at RUNTIME behind
 * `requestedVideoTransport()`, so the bytes under test are the shipped screen,
 * the shipped `VideoRoomClient` contract and the shipped rendering of every
 * state — only the transport underneath is deterministic.
 *
 * It is NEVER the default: `requestedVideoTransport()` returns `livekit` unless
 * something explicitly asked for `deterministic` before the app booted.
 *
 * WHAT IT CANNOT DO. It does not prove that LiveKit reconnects, that ICE
 * restarts work, or that two real browsers exchange media. Nothing here should
 * ever be reported as evidence of that.
 *
 * Privacy is identical to the production adapter: the credential is a parameter
 * that is not retained, no device label is read, and nothing is written to
 * storage, a cookie, the URL or the console.
 */
import {
  VideoRoomHub,
  enumerateVideoRoomDevices,
  videoRoomFailure,
  type VideoRoomClient,
  type VideoRoomConnectOptions,
  type VideoRoomDevice,
  type VideoRoomDeviceKind,
  type VideoRoomEventMap,
  type VideoRoomFailure,
  type VideoRoomFailureCode,
  type VideoRoomParticipant,
  type VideoRoomState,
} from './videoRoomClient';

/** The simulated counterpart's participant reference. Opaque, like the real one. */
export const DETERMINISTIC_COUNTERPART = 'deterministic-counterpart';

/**
 * The controls the deterministic adapter offers on top of the interface.
 *
 * These are what a unit test or the browser journey uses to put the room into
 * a state a live server would otherwise have to produce. There is no timer
 * anywhere: `restoreTransport()` and `settle()` are two separate steps
 * precisely so an observer can see `reconnected` rendered without racing.
 */
export interface DeterministicVideoRoomDriver {
  readonly transport: 'deterministic';
  getState(): VideoRoomState;
  getFailure(): VideoRoomFailure | null;
  /** Refuse the NEXT `connect()` with a typed code, as a provider would. */
  refuseNextConnect(code: VideoRoomFailureCode): void;
  /** connected -> reconnecting, and remote media stops flowing. */
  dropTransport(): void;
  /** reconnecting -> reconnected, and remote media flows again. */
  restoreTransport(): void;
  /** reconnected -> connected. */
  settle(): void;
  /** Any state -> failed, with a typed terminal code. */
  failTerminally(code: VideoRoomFailureCode): void;
  addRemoteParticipant(participantRef?: string): void;
  removeRemoteParticipant(participantRef: string): void;
}

interface DriverWindow {
  __legalsaathiVideoRoom?: DeterministicVideoRoomDriver;
}

/* ========================================================================== *
 * Synthetic media
 * ========================================================================== */

interface SyntheticMedia {
  stream: MediaStream;
  stop: () => void;
}

/**
 * A real `MediaStream` with frames actually flowing, produced locally from a
 * canvas. It is genuinely decodable — a `<video>` bound to it reaches
 * `readyState >= 2` with non-zero dimensions — which is what makes "media is
 * flowing again" an OBSERVATION rather than a claim.
 *
 * It is synthetic, and it is only ever described as synthetic. Returns `null`
 * where there is no DOM (the unit tests run in node), and the caller renders
 * the participant with no stream, which is also a state worth having.
 */
function syntheticMedia(seed: number): SyntheticMedia | null {
  if (typeof document === 'undefined') return null;
  const canvas = document.createElement('canvas');
  canvas.width = 320;
  canvas.height = 240;
  const context = canvas.getContext('2d');
  const capture = (canvas as HTMLCanvasElement & {
    captureStream?: (fps?: number) => MediaStream;
  }).captureStream;
  if (!context || typeof capture !== 'function') return null;

  let tick = 0;
  const paint = (): void => {
    tick += 1;
    context.fillStyle = `hsl(${(seed * 47 + tick * 3) % 360} 38% 22%)`;
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = '#e8e2d6';
    context.fillRect(20, 20 + ((tick * 4) % 180), 60, 24);
  };
  paint();
  const stream = capture.call(canvas, 12);
  const timer = setInterval(paint, 100);
  return {
    stream,
    stop: () => {
      clearInterval(timer);
      for (const track of stream.getTracks()) track.stop();
    },
  };
}

/* ========================================================================== *
 * The adapter
 * ========================================================================== */

interface RemoteState {
  participantRef: string;
  media: SyntheticMedia | null;
  seed: number;
}

class FakeVideoRoomClient implements VideoRoomClient {
  readonly transport = 'deterministic' as const;

  /** `0` = no automatic settle: the driver moves `reconnected` on explicitly. */
  private readonly hub = new VideoRoomHub(0);
  private participantRef = 'deterministic-local';
  private ownedStream: MediaStream | null = null;
  private microphoneEnabled = true;
  private cameraEnabled = true;
  private screenShareEnabled = false;
  private screen: SyntheticMedia | null = null;
  private remotes: RemoteState[] = [];
  private refusal: VideoRoomFailureCode | null = null;
  private connected = false;
  private selected: Partial<Record<VideoRoomDeviceKind, string>> = {};

  getState(): VideoRoomState { return this.hub.getState(); }
  getFailure(): VideoRoomFailure | null { return this.hub.getFailure(); }
  getParticipants(): readonly VideoRoomParticipant[] { return this.hub.getParticipants(); }
  getDevices(): readonly VideoRoomDevice[] { return this.hub.getDevices(); }
  /** The device ids currently selected. Ids only; no label exists here. */
  getSelectedDevices(): Readonly<Partial<Record<VideoRoomDeviceKind, string>>> {
    return this.selected;
  }

  on<K extends keyof VideoRoomEventMap>(event: K, handler: VideoRoomEventMap[K]): () => void {
    return this.hub.on(event, handler);
  }

  async connect(options: VideoRoomConnectOptions): Promise<void> {
    // The credential is read for nothing but this guard and is not retained:
    // a caller that forgot to obtain one must not silently reach `connected`.
    if (!options.token) {
      this.hub.setState('failed', videoRoomFailure('NOT_ADMITTED'));
      return;
    }
    this.participantRef = options.participantRef;
    this.ownedStream = options.localStream ?? null;
    this.microphoneEnabled = options.publishAudio !== false;
    this.cameraEnabled = options.publishVideo !== false;
    if (options.devices?.audioinput) this.selected.audioinput = options.devices.audioinput;
    if (options.devices?.videoinput) this.selected.videoinput = options.devices.videoinput;
    this.hub.setState('connecting');
    await Promise.resolve();
    const refusal = this.refusal;
    if (refusal) {
      this.refusal = null;
      this.hub.setState('failed', videoRoomFailure(refusal));
      return;
    }
    this.connected = true;
    this.ensureRemote(DETERMINISTIC_COUNTERPART);
    this.hub.setState('connected');
    this.publish();
    await this.listDevices();
  }

  async disconnect(): Promise<void> {
    this.connected = false;
    this.stopRemotes();
    this.remotes = [];
    this.hub.setState('disconnected');
    this.publish();
  }

  async setMicrophoneEnabled(enabled: boolean): Promise<void> {
    this.microphoneEnabled = enabled;
    for (const track of this.ownedStream?.getAudioTracks() ?? []) track.enabled = enabled;
    this.publish();
  }

  async setCameraEnabled(enabled: boolean): Promise<void> {
    this.cameraEnabled = enabled;
    for (const track of this.ownedStream?.getVideoTracks() ?? []) track.enabled = enabled;
    this.publish();
  }

  async setScreenShareEnabled(enabled: boolean): Promise<void> {
    this.screenShareEnabled = enabled;
    if (enabled) {
      this.screen = this.screen ?? syntheticMedia(99);
    } else {
      this.screen?.stop();
      this.screen = null;
    }
    this.publish();
  }

  async listDevices(): Promise<readonly VideoRoomDevice[]> {
    const devices = await enumerateVideoRoomDevices();
    this.hub.setDevices(devices);
    return devices;
  }

  async selectDevice(kind: VideoRoomDeviceKind, deviceId: string): Promise<void> {
    this.selected[kind] = deviceId;
    this.publish();
  }

  async leave(): Promise<void> {
    await this.disconnect();
    this.screen?.stop();
    this.screen = null;
    for (const track of this.ownedStream?.getTracks() ?? []) track.stop();
    this.ownedStream = null;
    this.hub.dispose();
  }

  /* ------------------------------- the driver ---------------------------- */

  driver(): DeterministicVideoRoomDriver {
    return {
      transport: 'deterministic',
      getState: () => this.hub.getState(),
      getFailure: () => this.hub.getFailure(),
      refuseNextConnect: (code) => { this.refusal = code; },
      dropTransport: () => {
        if (!this.connected) return;
        this.stopRemotes();
        this.hub.setState('reconnecting', videoRoomFailure('TRANSPORT_LOST', { terminal: false }));
        this.publish();
      },
      restoreTransport: () => {
        if (this.hub.getState() !== 'reconnecting') return;
        for (const remote of this.remotes) remote.media = syntheticMedia(remote.seed);
        this.hub.setState('reconnected');
        this.publish();
      },
      settle: () => { this.hub.settle(); },
      failTerminally: (code) => {
        this.connected = false;
        this.stopRemotes();
        this.remotes = [];
        this.hub.setState('failed', videoRoomFailure(code));
        this.publish();
      },
      addRemoteParticipant: (participantRef = DETERMINISTIC_COUNTERPART) => {
        this.ensureRemote(participantRef);
        this.publish();
      },
      removeRemoteParticipant: (participantRef) => {
        for (const remote of this.remotes.filter((r) => r.participantRef === participantRef)) {
          remote.media?.stop();
        }
        this.remotes = this.remotes.filter((r) => r.participantRef !== participantRef);
        this.publish();
      },
    };
  }

  /* ------------------------------- internals ----------------------------- */

  private ensureRemote(participantRef: string): void {
    if (this.remotes.some((r) => r.participantRef === participantRef)) return;
    const seed = this.remotes.length + 1;
    this.remotes.push({ participantRef, seed, media: syntheticMedia(seed) });
  }

  private stopRemotes(): void {
    for (const remote of this.remotes) {
      remote.media?.stop();
      remote.media = null;
    }
  }

  private publish(): void {
    const live = this.hub.getState();
    const flowing = live === 'connected' || live === 'reconnected';
    const local: VideoRoomParticipant = {
      participantRef: this.participantRef,
      local: true,
      microphoneEnabled: this.microphoneEnabled,
      cameraEnabled: this.cameraEnabled,
      screenShareEnabled: this.screenShareEnabled,
      cameraStream: this.cameraEnabled ? this.ownedStream : null,
      screenStream: this.screen?.stream ?? null,
    };
    const remotes: VideoRoomParticipant[] = this.remotes.map((remote) => ({
      participantRef: remote.participantRef,
      local: false,
      microphoneEnabled: flowing,
      cameraEnabled: flowing && !!remote.media,
      screenShareEnabled: false,
      cameraStream: flowing ? remote.media?.stream ?? null : null,
      screenStream: null,
    }));
    this.hub.setParticipants(this.connected || live === 'reconnecting' ? [local, ...remotes] : []);
  }
}

/**
 * Build the deterministic client and expose its driver.
 *
 * The driver is published on a window property so the browser journey can put
 * the PRODUCTION screen through states a live server would otherwise have to
 * produce. It exists only when the deterministic transport was explicitly
 * requested, so a real participant's tab never has one.
 */
export function createFakeVideoRoomClient(): VideoRoomClient {
  const client = new FakeVideoRoomClient();
  if (typeof window !== 'undefined') {
    (window as unknown as DriverWindow).__legalsaathiVideoRoom = client.driver();
  }
  return client;
}

/** The same client, with its driver, for unit tests. */
export function createDeterministicVideoRoom(): {
  client: VideoRoomClient;
  driver: DeterministicVideoRoomDriver;
} {
  const client = new FakeVideoRoomClient();
  return { client, driver: client.driver() };
}
