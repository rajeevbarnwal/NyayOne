/**
 * The PRODUCTION `VideoRoomClient` adapter, over LiveKit.
 *
 * The vendor is `livekit-client`, DECLARED in frontend/package.json and PINNED
 * to an exact version in frontend/package-lock.json. It is imported by module
 * specifier and resolved by the bundler like every other dependency: there is
 * no CDN `<script>` tag, no UMD global, and nothing is fetched from a third
 * party at runtime. The import is dynamic purely so the vendor bundle is a
 * separate chunk a participant only pays for on entering a room.
 *
 * WHAT THIS FILE IS AND IS NOT.
 *   * It is the only place in the product that knows LiveKit exists. Nothing
 *     vendor-shaped escapes: the screen sees `VideoRoomState`,
 *     `VideoRoomFailure`, `VideoRoomParticipant` and `VideoRoomDevice`.
 *   * It is NOT infrastructure QA. `infra/video/scripts/livekit_two_browser_smoke.mjs`
 *     drives a CDN bundle in a blank page to prove a server is alive; that is a
 *     different artefact for a different question and is not a substitute for
 *     this adapter.
 *
 * PRIVACY.
 *   * The raw join credential is a parameter of `connect()` and is handed
 *     straight to `room.connect(url, token)`. It is never assigned to a field of
 *     this object, never re-emitted, never rendered and never logged. There is
 *     no getter that could return it.
 *   * `device.label` is never read: enumeration goes through
 *     `enumerateVideoRoomDevices()`, which yields ids and ordinals only.
 *   * Participants are keyed by the SERVER's opaque participant reference,
 *     which is exactly the LiveKit `identity` the server minted the grant for.
 *   * Nothing here writes to storage, a cookie, the URL or the console.
 */
import type {
  ConnectionState,
  RemoteParticipant,
  RemoteTrack,
  RemoteTrackPublication,
  Room,
} from 'livekit-client';
import {
  VideoRoomHub,
  enumerateVideoRoomDevices,
  videoRoomFailure,
  videoRoomServerUrl,
  type VideoRoomClient,
  type VideoRoomConnectOptions,
  type VideoRoomDevice,
  type VideoRoomDeviceKind,
  type VideoRoomEventMap,
  type VideoRoomFailure,
  type VideoRoomParticipant,
  type VideoRoomState,
} from './videoRoomClient';

type LiveKitModule = typeof import('livekit-client');

/** Secret-free Room RTC options derived from the server-authoritative policy. */
export function liveKitConnectOptions(
  policy: VideoRoomConnectOptions['iceTransportPolicy'],
): { rtcConfig: RTCConfiguration } {
  return { rtcConfig: { iceTransportPolicy: policy ?? 'all' } };
}

/* ========================================================================== *
 * Vendor -> product mappings, kept as pure functions so they are testable
 * ========================================================================== */

/**
 * LiveKit's `ConnectionState` is a STRING enum, so it maps by value and a
 * version that adds a member lands in the exhaustive `default`.
 *
 * `signalReconnecting` is reported as `reconnecting`: from a participant's point
 * of view a signal-only reconnection is the same event as a full one — the room
 * is currently trying to come back — and inventing a sixth word for it would be
 * a distinction with no user meaning.
 */
export function mapLiveKitConnectionState(state: string): VideoRoomState {
  switch (state) {
    case 'disconnected': return 'disconnected';
    case 'connecting': return 'connecting';
    case 'connected': return 'connected';
    case 'reconnecting':
    case 'signalReconnecting': return 'reconnecting';
    default: return 'failed';
  }
}

/**
 * LiveKit's `DisconnectReason` is a NUMERIC protobuf enum. It is mapped by its
 * wire numbers, taken from `@livekit/protocol`'s generated
 * `livekit_models.DisconnectReason`, because those numbers are the stable part
 * of the contract; the TypeScript member names are a generator artefact.
 *
 *   1 CLIENT_INITIATED    we asked to leave — not a failure at all
 *   2 DUPLICATE_IDENTITY  someone else joined as this participant
 *   4 PARTICIPANT_REMOVED the server ejected this participant (grant revoked)
 *   5 ROOM_DELETED / 10 ROOM_CLOSED   the room itself is gone
 *   everything else       the transport was lost
 */
export function mapLiveKitDisconnectReason(reason: number | undefined): VideoRoomFailure | null {
  switch (reason) {
    case 1: return null;
    case 2: return videoRoomFailure('WRONG_PARTICIPANT');
    case 4: return videoRoomFailure('CREDENTIAL_REVOKED');
    case 5:
    case 10: return videoRoomFailure('SESSION_CANCELLED');
    default: return videoRoomFailure('TRANSPORT_LOST');
  }
}

/**
 * A connect-time refusal. `ConnectionErrorReason` is numeric:
 * 0 NotAllowed, 1 ServerUnreachable, 2 InternalError, 3 Cancelled,
 * 4 LeaveRequest, 5 Timeout, 6 WebSocket, 7 ServiceNotFound.
 *
 * `NotAllowed` is the provider rejecting the credential. It is reported as
 * NOT_ADMITTED rather than guessing between expiry, revocation and the wrong
 * participant: the provider does not tell us which, and the SERVER already
 * answers that question authoritatively with GRANT_EXPIRED / GRANT_REVOKED /
 * FORBIDDEN on the credential call. Inventing a more specific code here would
 * be the client claiming to know something it does not.
 */
export function mapLiveKitConnectError(error: unknown): VideoRoomFailure {
  const reason = (error as { reason?: unknown } | null)?.reason;
  if (typeof reason !== 'number') return videoRoomFailure('UNKNOWN');
  if (reason === 0) return videoRoomFailure('NOT_ADMITTED');
  if (reason === 1 || reason === 5 || reason === 6 || reason === 7) {
    return videoRoomFailure('PROVIDER_UNAVAILABLE');
  }
  return videoRoomFailure('UNKNOWN');
}

/* ========================================================================== *
 * The adapter
 * ========================================================================== */

class LiveKitVideoRoomClient implements VideoRoomClient {
  readonly transport = 'livekit' as const;

  private readonly hub = new VideoRoomHub();
  private livekit: LiveKitModule | null = null;
  private room: Room | null = null;
  private participantRef = '';
  private ownedStream: MediaStream | null = null;
  private left = false;

  getState(): VideoRoomState { return this.hub.getState(); }
  getFailure(): VideoRoomFailure | null { return this.hub.getFailure(); }
  getParticipants(): readonly VideoRoomParticipant[] { return this.hub.getParticipants(); }
  getDevices(): readonly VideoRoomDevice[] { return this.hub.getDevices(); }

  on<K extends keyof VideoRoomEventMap>(event: K, handler: VideoRoomEventMap[K]): () => void {
    return this.hub.on(event, handler);
  }

  async connect(options: VideoRoomConnectOptions): Promise<void> {
    if (this.left) return;
    const url = options.serverUrl?.trim() || videoRoomServerUrl();
    this.participantRef = options.participantRef;
    this.ownedStream = options.localStream ?? null;
    if (!url) {
      /*
       * FAIL CLOSED, and say so. With no media server configured for this
       * build there is nothing to dial, so the room reports a terminal,
       * NAMED state instead of spinning forever pretending to connect. The
       * vendor bundle is not even fetched.
       */
      this.hub.setState('failed', videoRoomFailure('PROVIDER_NOT_CONFIGURED'));
      return;
    }
    this.hub.setState('connecting');
    try {
      const livekit = await import('livekit-client');
      if (this.left) return;
      this.livekit = livekit;
      const room = new livekit.Room({
        adaptiveStream: true,
        dynacast: true,
      });
      this.room = room;
      this.bind(room, livekit);
      // The raw credential is passed through and not retained by this object.
      await room.connect(url, options.token, liveKitConnectOptions(options.iceTransportPolicy));
      if (this.left) {
        await room.disconnect();
        return;
      }
      await this.publishLocal(options);
      this.hub.setState('connected');
      this.refreshParticipants();
      await this.listDevices();
    } catch (error) {
      this.hub.setState('failed', mapLiveKitConnectError(error));
    }
  }

  /**
   * Publish the capture the room already opened for its self-view, rather than
   * asking the platform for the camera a second time: one prompt, one device
   * indicator, and the preview the participant approved is exactly what is sent.
   */
  private async publishLocal(options: VideoRoomConnectOptions): Promise<void> {
    const room = this.room;
    const stream = options.localStream;
    if (!room || !stream) return;
    const wantAudio = options.publishAudio !== false;
    const wantVideo = options.publishVideo !== false;
    for (const track of stream.getAudioTracks()) {
      if (wantAudio) await room.localParticipant.publishTrack(track);
    }
    for (const track of stream.getVideoTracks()) {
      if (wantVideo) await room.localParticipant.publishTrack(track);
    }
  }

  private bind(room: Room, livekit: LiveKitModule): void {
    const { RoomEvent } = livekit;
    room.on(RoomEvent.ConnectionStateChanged, (state: ConnectionState) => {
      const mapped = mapLiveKitConnectionState(String(state));
      // `Reconnected` owns the transition out of `reconnecting`; a bare
      // `connected` arriving while we are showing `reconnected` must not cut
      // that state short, because the participant is being told the room came
      // back and has not read it yet.
      if (mapped === 'connected' && this.hub.getState() === 'reconnected') return;
      if (mapped === 'disconnected' && this.hub.getState() === 'failed') return;
      this.hub.setState(mapped, mapped === 'reconnecting'
        ? videoRoomFailure('TRANSPORT_LOST', { terminal: false })
        : null);
    });
    room.on(RoomEvent.Reconnecting, () => {
      this.hub.setState('reconnecting', videoRoomFailure('TRANSPORT_LOST', { terminal: false }));
    });
    room.on(RoomEvent.Reconnected, () => {
      this.hub.setState('reconnected');
      this.refreshParticipants();
    });
    room.on(RoomEvent.Disconnected, (reason?: number) => {
      const failure = mapLiveKitDisconnectReason(reason);
      this.hub.setState(failure ? 'failed' : 'disconnected', failure);
      this.refreshParticipants();
    });
    const touched = (): void => this.refreshParticipants();
    room.on(RoomEvent.ParticipantConnected, touched);
    room.on(RoomEvent.ParticipantDisconnected, touched);
    room.on(RoomEvent.TrackSubscribed, (
      _track: RemoteTrack,
      _publication: RemoteTrackPublication,
      _participant: RemoteParticipant,
    ) => this.refreshParticipants());
    room.on(RoomEvent.TrackUnsubscribed, touched);
    room.on(RoomEvent.TrackMuted, touched);
    room.on(RoomEvent.TrackUnmuted, touched);
    room.on(RoomEvent.LocalTrackPublished, touched);
    room.on(RoomEvent.LocalTrackUnpublished, touched);
    room.on(RoomEvent.MediaDevicesChanged, () => { void this.listDevices(); });
  }

  /** Project the vendor's participants onto the product's shape. */
  private refreshParticipants(): void {
    const room = this.room;
    const livekit = this.livekit;
    if (!room || !livekit) {
      this.hub.setParticipants([]);
      return;
    }
    const { Track } = livekit;
    const streamOf = (
      publication: { track?: { mediaStreamTrack?: MediaStreamTrack } } | undefined,
    ): MediaStream | null => {
      const media = publication?.track?.mediaStreamTrack;
      if (!media || typeof MediaStream === 'undefined') return null;
      return new MediaStream([media]);
    };

    const local = room.localParticipant;
    const out: VideoRoomParticipant[] = [{
      participantRef: local.identity || this.participantRef,
      local: true,
      microphoneEnabled: local.isMicrophoneEnabled,
      cameraEnabled: local.isCameraEnabled,
      screenShareEnabled: local.isScreenShareEnabled,
      cameraStream: streamOf(local.getTrackPublication(Track.Source.Camera)),
      screenStream: streamOf(local.getTrackPublication(Track.Source.ScreenShare)),
    }];
    for (const remote of room.remoteParticipants.values()) {
      out.push({
        participantRef: remote.identity,
        local: false,
        microphoneEnabled: remote.isMicrophoneEnabled,
        cameraEnabled: remote.isCameraEnabled,
        screenShareEnabled: remote.isScreenShareEnabled,
        cameraStream: streamOf(remote.getTrackPublication(Track.Source.Camera)),
        screenStream: streamOf(remote.getTrackPublication(Track.Source.ScreenShare)),
      });
    }
    this.hub.setParticipants(out);
  }

  async setMicrophoneEnabled(enabled: boolean): Promise<void> {
    for (const track of this.ownedStream?.getAudioTracks() ?? []) track.enabled = enabled;
    await this.room?.localParticipant.setMicrophoneEnabled(enabled);
    this.refreshParticipants();
  }

  async setCameraEnabled(enabled: boolean): Promise<void> {
    for (const track of this.ownedStream?.getVideoTracks() ?? []) track.enabled = enabled;
    await this.room?.localParticipant.setCameraEnabled(enabled);
    this.refreshParticipants();
  }

  async setScreenShareEnabled(enabled: boolean): Promise<void> {
    await this.room?.localParticipant.setScreenShareEnabled(enabled);
    this.refreshParticipants();
  }

  async listDevices(): Promise<readonly VideoRoomDevice[]> {
    const devices = await enumerateVideoRoomDevices();
    this.hub.setDevices(devices);
    return devices;
  }

  async selectDevice(kind: VideoRoomDeviceKind, deviceId: string): Promise<void> {
    await this.room?.switchActiveDevice(kind, deviceId);
    this.refreshParticipants();
  }

  async disconnect(): Promise<void> {
    const room = this.room;
    this.room = null;
    if (room) await room.disconnect();
    this.hub.setState('disconnected');
    this.hub.setParticipants([]);
  }

  async leave(): Promise<void> {
    this.left = true;
    await this.disconnect();
    // FULL DEVICE RELEASE. Stopping the tracks is what actually turns the
    // camera and microphone indicators off; disabling them does not.
    for (const track of this.ownedStream?.getTracks() ?? []) track.stop();
    this.ownedStream = null;
    this.livekit = null;
    this.hub.dispose();
  }
}

export function createLiveKitVideoRoomClient(): VideoRoomClient {
  return new LiveKitVideoRoomClient();
}
