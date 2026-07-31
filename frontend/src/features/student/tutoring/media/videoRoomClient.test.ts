/**
 * The live-room media client contract (matrix E1/E3, negative case N45).
 *
 * Three things are pinned here:
 *
 *   1. THE STATE MACHINE. Every member of `VideoRoomState` is reached through
 *      the DETERMINISTIC adapter and observed as an emitted event, including
 *      the drop/reconnect/settle sequence N45 requires. The fake shares
 *      `VideoRoomHub` with the production adapter, so a transition proved here
 *      is the same code the LiveKit adapter runs.
 *   2. EVERY CONTROL. Mute, camera, screen share, device enumeration, device
 *      selection, disconnect and leave — each one is exercised and its effect
 *      observed on the published participant list.
 *   3. THE TYPED REFUSALS. Expiry, revocation, a wrong participant and a
 *      cancelled session each arrive as a named code with a `terminal` and a
 *      `reissuable` verdict, from the provider boundary and from the server's
 *      own error codes.
 *
 * What these tests do NOT prove: that LiveKit reconnects, that an ICE restart
 * works, or that two real browsers exchange media. No self-hosted LiveKit or
 * TURN runtime exists in this environment, so that remains unproven and is
 * reported as such. What IS proved about the production adapter here is its
 * fail-closed path: with no media server configured it refuses in a named
 * state without loading the vendor bundle at all.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  RECONNECTED_SETTLE_MS,
  VIDEO_ROOM_FAILURE_CODES,
  VIDEO_ROOM_STATES,
  VideoRoomHub,
  clearPreferredDevices,
  createVideoRoomClient,
  getPreferredDevices,
  requestedVideoTransport,
  setPreferredDevices,
  videoRoomDeviceName,
  videoRoomFailure,
  videoRoomFailureFromServerCode,
  videoRoomServerUrl,
  type VideoRoomState,
} from './videoRoomClient';
import { DETERMINISTIC_COUNTERPART, createDeterministicVideoRoom } from './fakeVideoRoomClient';
import {
  createLiveKitVideoRoomClient,
  mapLiveKitConnectError,
  mapLiveKitConnectionState,
  mapLiveKitDisconnectReason,
} from './livekitVideoRoomClient';

const CREDENTIAL = {
  token: 'raw-credential-for-this-test-only',
  roomRef: 'room_abc',
  participantRef: 'part_abc',
  permissions: ['publish', 'subscribe'],
};

/** Subscribe to the state stream and return the transitions seen so far. */
function watch(client: { on: (e: 'state', h: (s: VideoRoomState) => void) => () => void }): string[] {
  const seen: string[] = [];
  client.on('state', (state) => seen.push(state));
  return seen;
}

afterEach(() => {
  clearPreferredDevices();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/* ========================================================================== *
 * The deterministic adapter: every state
 * ========================================================================== */

describe('deterministic adapter — every connection state', () => {
  it('reaches connected through connecting, and publishes both participants', async () => {
    const { client } = createDeterministicVideoRoom();
    const seen = watch(client);
    expect(client.getState()).toBe('disconnected');

    await client.connect(CREDENTIAL);

    expect(seen).toEqual(['connecting', 'connected']);
    expect(client.getState()).toBe('connected');
    expect(client.getFailure()).toBeNull();
    const people = client.getParticipants();
    expect(people.map((p) => p.local)).toEqual([true, false]);
    expect(people[0].participantRef).toBe(CREDENTIAL.participantRef);
    expect(people[1].participantRef).toBe(DETERMINISTIC_COUNTERPART);
  });

  it('drives N45: connected -> reconnecting -> reconnected -> connected', async () => {
    const { client, driver } = createDeterministicVideoRoom();
    await client.connect(CREDENTIAL);
    const seen = watch(client);

    driver.dropTransport();
    expect(client.getState()).toBe('reconnecting');
    // A drop is NOT terminal: the room is still working on it.
    expect(client.getFailure()).toEqual({
      code: 'TRANSPORT_LOST', terminal: false, reissuable: true,
    });
    // While reconnecting the remote is still listed but nothing is flowing.
    const dropped = client.getParticipants().find((p) => !p.local);
    expect(dropped?.cameraStream).toBeNull();
    expect(dropped?.cameraEnabled).toBe(false);

    driver.restoreTransport();
    expect(client.getState()).toBe('reconnected');
    expect(client.getFailure()).toBeNull();

    driver.settle();
    expect(client.getState()).toBe('connected');
    expect(seen).toEqual(['reconnecting', 'reconnected', 'connected']);
  });

  it('reaches the terminal failure state and stops there', async () => {
    const { client, driver } = createDeterministicVideoRoom();
    await client.connect(CREDENTIAL);
    const seen = watch(client);

    driver.failTerminally('TRANSPORT_LOST');

    expect(client.getState()).toBe('failed');
    expect(client.getFailure()?.terminal).toBe(true);
    expect(client.getParticipants()).toEqual([]);
    // A terminal failure is terminal: the recovery controls do nothing.
    driver.restoreTransport();
    driver.settle();
    expect(seen).toEqual(['failed']);
  });

  it('returns to disconnected on disconnect and can connect again', async () => {
    const { client } = createDeterministicVideoRoom();
    await client.connect(CREDENTIAL);
    await client.disconnect();
    expect(client.getState()).toBe('disconnected');
    expect(client.getParticipants()).toEqual([]);

    await client.connect(CREDENTIAL);
    expect(client.getState()).toBe('connected');
  });

  it('visits every declared state across the whole lifecycle', async () => {
    const { client, driver } = createDeterministicVideoRoom();
    const seen = watch(client);
    await client.connect(CREDENTIAL);
    driver.dropTransport();
    driver.restoreTransport();
    driver.settle();
    await client.disconnect();
    driver.failTerminally('PROVIDER_UNAVAILABLE');
    const reached = new Set(['disconnected', ...seen]);
    for (const state of VIDEO_ROOM_STATES) {
      expect(reached, `state ${state} was never reached`).toContain(state);
    }
  });
});

/* ========================================================================== *
 * The deterministic adapter: every control
 * ========================================================================== */

describe('deterministic adapter — every control', () => {
  it('mutes and unmutes the microphone', async () => {
    const { client } = createDeterministicVideoRoom();
    await client.connect(CREDENTIAL);
    const local = () => client.getParticipants().find((p) => p.local);
    expect(local()?.microphoneEnabled).toBe(true);
    await client.setMicrophoneEnabled(false);
    expect(local()?.microphoneEnabled).toBe(false);
    await client.setMicrophoneEnabled(true);
    expect(local()?.microphoneEnabled).toBe(true);
  });

  it('turns the camera off and on', async () => {
    const { client } = createDeterministicVideoRoom();
    await client.connect(CREDENTIAL);
    const local = () => client.getParticipants().find((p) => p.local);
    await client.setCameraEnabled(false);
    expect(local()?.cameraEnabled).toBe(false);
    await client.setCameraEnabled(true);
    expect(local()?.cameraEnabled).toBe(true);
  });

  it('reports screen-share state on and off', async () => {
    const { client } = createDeterministicVideoRoom();
    await client.connect(CREDENTIAL);
    const local = () => client.getParticipants().find((p) => p.local);
    expect(local()?.screenShareEnabled).toBe(false);
    await client.setScreenShareEnabled(true);
    expect(local()?.screenShareEnabled).toBe(true);
    await client.setScreenShareEnabled(false);
    expect(local()?.screenShareEnabled).toBe(false);
  });

  it('publishes the participant list on every change', async () => {
    const { client, driver } = createDeterministicVideoRoom();
    await client.connect(CREDENTIAL);
    const lists: number[] = [];
    client.on('participants', (people) => lists.push(people.length));
    driver.addRemoteParticipant('second-counterpart');
    driver.removeRemoteParticipant('second-counterpart');
    expect(lists).toEqual([3, 2]);
  });

  it('enumerates devices without ever reading a label, and selects by id', async () => {
    const devices = [
      { deviceId: 'cam-a', kind: 'videoinput', label: 'FaceTime HD Camera (Built-in)' },
      { deviceId: 'cam-b', kind: 'videoinput', label: 'Elgato' },
      { deviceId: 'mic-a', kind: 'audioinput', label: 'MacBook Pro Microphone' },
      { deviceId: 'spk-a', kind: 'audiooutput', label: 'MacBook Pro Speakers' },
    ];
    vi.stubGlobal('navigator', {
      mediaDevices: { enumerateDevices: () => Promise.resolve(devices) },
    });
    const { client } = createDeterministicVideoRoom();
    const found = await client.listDevices();
    expect(found).toEqual([
      { deviceId: 'cam-a', kind: 'videoinput', ordinal: 1 },
      { deviceId: 'cam-b', kind: 'videoinput', ordinal: 2 },
      { deviceId: 'mic-a', kind: 'audioinput', ordinal: 1 },
    ]);
    // No hardware name survives the projection, in any field.
    expect(JSON.stringify(found)).not.toContain('FaceTime');
    expect(JSON.stringify(found)).not.toContain('MacBook');
    expect(videoRoomDeviceName(found[1])).toBe('Camera 2');
    expect(videoRoomDeviceName(found[2])).toBe('Microphone 1');

    await client.connect(CREDENTIAL);
    await client.selectDevice('videoinput', 'cam-b');
    expect(client.getState()).toBe('connected');
  });

  it('answers with no devices where the platform offers none', async () => {
    vi.stubGlobal('navigator', {});
    const { client } = createDeterministicVideoRoom();
    expect(await client.listDevices()).toEqual([]);
  });

  it('leaves: disconnected, no participants, listeners dropped', async () => {
    const { client, driver } = createDeterministicVideoRoom();
    await client.connect(CREDENTIAL);
    const seen = watch(client);
    await client.leave();
    expect(client.getState()).toBe('disconnected');
    expect(client.getParticipants()).toEqual([]);
    expect(seen).toEqual(['disconnected']);
    // Every listener was dropped, so nothing can be emitted after leaving.
    driver.failTerminally('UNKNOWN');
    expect(seen).toEqual(['disconnected']);
  });
});

/* ========================================================================== *
 * Typed refusals
 * ========================================================================== */

describe('typed refusals', () => {
  it.each([
    ['CREDENTIAL_EXPIRED', true],
    ['CREDENTIAL_REVOKED', true],
    ['WRONG_PARTICIPANT', false],
    ['SESSION_CANCELLED', false],
    ['NOT_ADMITTED', false],
    ['PROVIDER_UNAVAILABLE', true],
  ] as const)('refuses a connect with %s (reissuable=%s)', async (code, reissuable) => {
    const { client, driver } = createDeterministicVideoRoom();
    driver.refuseNextConnect(code);
    await client.connect(CREDENTIAL);
    expect(client.getState()).toBe('failed');
    expect(client.getFailure()).toEqual({ code, terminal: true, reissuable });
    expect(client.getParticipants()).toEqual([]);
  });

  it('refuses a connect with no credential at all', async () => {
    const { client } = createDeterministicVideoRoom();
    await client.connect({ ...CREDENTIAL, token: '' });
    expect(client.getState()).toBe('failed');
    expect(client.getFailure()?.code).toBe('NOT_ADMITTED');
  });

  it('maps the SERVER refusal codes onto the same vocabulary', () => {
    expect(videoRoomFailureFromServerCode('GRANT_EXPIRED').code).toBe('CREDENTIAL_EXPIRED');
    expect(videoRoomFailureFromServerCode('GRANT_REVOKED').code).toBe('CREDENTIAL_REVOKED');
    expect(videoRoomFailureFromServerCode('FORBIDDEN').code).toBe('WRONG_PARTICIPANT');
    expect(videoRoomFailureFromServerCode('NOT_FOUND').code).toBe('WRONG_PARTICIPANT');
    expect(videoRoomFailureFromServerCode('SESSION_STATE_INVALID').code).toBe('SESSION_CANCELLED');
    expect(videoRoomFailureFromServerCode('PROVIDER_UNAVAILABLE').code).toBe('PROVIDER_UNAVAILABLE');
    expect(videoRoomFailureFromServerCode('something-new').code).toBe('UNKNOWN');
  });

  it('gives every declared failure code a terminal and reissuable verdict', () => {
    for (const code of VIDEO_ROOM_FAILURE_CODES) {
      const failure = videoRoomFailure(code);
      expect(failure.code).toBe(code);
      expect(typeof failure.terminal).toBe('boolean');
      expect(typeof failure.reissuable).toBe('boolean');
    }
  });
});

/* ========================================================================== *
 * The shared state machine
 * ========================================================================== */

describe('VideoRoomHub', () => {
  it('settles reconnected back to connected on its own, once', () => {
    vi.useFakeTimers();
    const hub = new VideoRoomHub();
    const seen: string[] = [];
    hub.on('state', (state) => seen.push(state));
    hub.setState('reconnected');
    expect(hub.getState()).toBe('reconnected');
    vi.advanceTimersByTime(RECONNECTED_SETTLE_MS + 10);
    expect(hub.getState()).toBe('connected');
    expect(seen).toEqual(['reconnected', 'connected']);
  });

  it('does not settle a state that moved on before the timer fired', () => {
    vi.useFakeTimers();
    const hub = new VideoRoomHub();
    hub.setState('reconnected');
    hub.setState('failed', videoRoomFailure('TRANSPORT_LOST'));
    vi.advanceTimersByTime(RECONNECTED_SETTLE_MS + 10);
    expect(hub.getState()).toBe('failed');
  });

  it('unsubscribes cleanly', () => {
    const hub = new VideoRoomHub(0);
    const seen: string[] = [];
    const off = hub.on('state', (state) => seen.push(state));
    hub.setState('connecting');
    off();
    hub.setState('connected');
    expect(seen).toEqual(['connecting']);
  });
});

/* ========================================================================== *
 * The pre-join device choice
 * ========================================================================== */

describe('the device choice carried into the room', () => {
  it('is in-memory, additive and clearable', () => {
    expect(getPreferredDevices()).toEqual({});
    setPreferredDevices({ videoinput: 'cam-b' });
    setPreferredDevices({ audioinput: 'mic-a' });
    expect(getPreferredDevices()).toEqual({ videoinput: 'cam-b', audioinput: 'mic-a' });
    clearPreferredDevices();
    expect(getPreferredDevices()).toEqual({});
  });
});

/* ========================================================================== *
 * Runtime adapter selection
 * ========================================================================== */

describe('runtime adapter selection', () => {
  it('is LiveKit unless something explicitly asked for the deterministic one', async () => {
    expect(requestedVideoTransport()).toBe('livekit');
    const client = await createVideoRoomClient();
    expect(client.transport).toBe('livekit');
  });

  it('builds the deterministic adapter when a pre-boot global asks for it', async () => {
    vi.stubGlobal('window', { __legalsaathiVideoTransport: 'deterministic' });
    expect(requestedVideoTransport()).toBe('deterministic');
    const client = await createVideoRoomClient();
    expect(client.transport).toBe('deterministic');
  });

  it('ignores any other value on that global', () => {
    vi.stubGlobal('window', { __legalsaathiVideoTransport: 'livekit-please' });
    expect(requestedVideoTransport()).toBe('livekit');
  });
});

/* ========================================================================== *
 * The production adapter's pure mappings and its fail-closed path
 * ========================================================================== */

describe('the LiveKit adapter', () => {
  it('maps the backend video kill-switch to a named non-reissuable failure', () => {
    expect(videoRoomFailureFromServerCode('VIDEO_CALLS_DISABLED')).toEqual({
      code: 'VIDEO_CALLS_DISABLED', terminal: true, reissuable: false,
    });
  });
  it('maps every LiveKit connection state, and an unknown one to failed', () => {
    expect(mapLiveKitConnectionState('disconnected')).toBe('disconnected');
    expect(mapLiveKitConnectionState('connecting')).toBe('connecting');
    expect(mapLiveKitConnectionState('connected')).toBe('connected');
    expect(mapLiveKitConnectionState('reconnecting')).toBe('reconnecting');
    expect(mapLiveKitConnectionState('signalReconnecting')).toBe('reconnecting');
    expect(mapLiveKitConnectionState('something-a-later-version-added')).toBe('failed');
  });

  it('maps the disconnect reasons that mean something to a participant', () => {
    expect(mapLiveKitDisconnectReason(1)).toBeNull();
    expect(mapLiveKitDisconnectReason(2)?.code).toBe('WRONG_PARTICIPANT');
    expect(mapLiveKitDisconnectReason(4)?.code).toBe('CREDENTIAL_REVOKED');
    expect(mapLiveKitDisconnectReason(5)?.code).toBe('SESSION_CANCELLED');
    expect(mapLiveKitDisconnectReason(10)?.code).toBe('SESSION_CANCELLED');
    expect(mapLiveKitDisconnectReason(3)?.code).toBe('TRANSPORT_LOST');
    expect(mapLiveKitDisconnectReason(undefined)?.code).toBe('TRANSPORT_LOST');
  });

  it('maps a connect-time refusal without claiming to know more than it does', () => {
    expect(mapLiveKitConnectError({ reason: 0 }).code).toBe('NOT_ADMITTED');
    expect(mapLiveKitConnectError({ reason: 1 }).code).toBe('PROVIDER_UNAVAILABLE');
    expect(mapLiveKitConnectError({ reason: 5 }).code).toBe('PROVIDER_UNAVAILABLE');
    expect(mapLiveKitConnectError({ reason: 6 }).code).toBe('PROVIDER_UNAVAILABLE');
    expect(mapLiveKitConnectError({ reason: 7 }).code).toBe('PROVIDER_UNAVAILABLE');
    expect(mapLiveKitConnectError({ reason: 2 }).code).toBe('UNKNOWN');
    expect(mapLiveKitConnectError(new Error('nope')).code).toBe('UNKNOWN');
  });

  it('FAILS CLOSED with a named state when no media server is configured', async () => {
    // This build has no VITE_VIDEO_ROOM_URL, which is exactly the point: the
    // room must say so rather than spin, and must not dial anything.
    expect(videoRoomServerUrl()).toBe('');
    const client = createLiveKitVideoRoomClient();
    const seen = watch(client);
    await client.connect(CREDENTIAL);
    expect(client.getState()).toBe('failed');
    expect(client.getFailure()).toEqual({
      code: 'PROVIDER_NOT_CONFIGURED', terminal: true, reissuable: false,
    });
    expect(seen).toEqual(['failed']);
    await client.leave();
  });
});
