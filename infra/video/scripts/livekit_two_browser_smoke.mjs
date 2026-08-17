#!/usr/bin/env node
// Two-browser LiveKit join driver. Steps S4, S5 and S6 of
// infra/video/scripts/livekit_turn_smoke.sh (== RUNBOOK § 9). Never run this
// directly in CI: the shell gate owns the prerequisite detection and the
// BLOCKED contract, and this file trusts what it is handed.
//
//   S4  two-browser join smoke        — two real Chromium contexts join the
//                                       SAME room with two DIFFERENT, backend-
//                                       minted, participant-bound credentials,
//                                       each publishes a fake camera+mic track,
//                                       and each SEES the other's tracks. The
//                                       selected ICE candidate pair of both is
//                                       written to s4-candidate-pair.json,
//                                       which is what step S9 then judges.
//   S5  camera and microphone denial  — a third context joins with camera and
//                                       microphone permission DENIED. The join
//                                       must still succeed (a participant who
//                                       cannot publish is still a participant),
//                                       the client must publish NO tracks, and
//                                       the page must not crash or leak the
//                                       device list.
//   S6  reconnect                     — the SFU is restarted underneath a live
//                                       call; both clients must report
//                                       Reconnecting -> Connected reusing the
//                                       SAME token, with no new credential.
//
// Output contract (parsed by the shell gate): one line per step,
//     "<STEP> PASS <detail>"   or   "<STEP> FAIL <detail>"
// Exit 0 when every requested step passed, 1 when one failed, 78 when a
// prerequisite (playwright, the livekit-client bundle, a browser binary) is
// absent — 78 is BLOCKED and is never a pass.
//
// Why the client SDK is injected rather than imported: `livekit-client` is not
// a dependency of frontend/package.json and adding one to the product bundle
// for a QA driver would be the tail wagging the dog. The UMD bundle is fetched
// once, from LIVEKIT_CLIENT_BUNDLE, and injected into an about:blank page.

import { mkdirSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';

import { redactMediaRuntimeMessage } from './runtime_redaction.mjs';

// Playwright is a frontend development dependency. Bare ESM resolution starts
// at this script under infra/video and therefore cannot see frontend/
// node_modules even though the prerequisite check found it. Resolve from the
// owning package explicitly so the runtime check and the import use one source.
const requireFromFrontend = createRequire(
  new URL('../../../frontend/package.json', import.meta.url),
);

const BLOCKED_EXIT = 78;
const OUT = process.env.SMOKE_OUT || 'test-results/livekit-smoke';
const BACKEND_URL = process.env.SMOKE_BACKEND_URL || 'http://localhost:1131';
const STEPS = (process.env.SMOKE_STEPS || 'S4,S5,S6').split(',').filter(Boolean);
const BUNDLE_URL =
  process.env.LIVEKIT_CLIENT_BUNDLE ||
  'https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.umd.min.js';
const SESSION_ID = process.env.SMOKE_SESSION_ID;
const STUDENT_HEADER = process.env.SMOKE_AUTH_HEADER;
const TUTOR_HEADER = process.env.SMOKE_TUTOR_AUTH_HEADER;
const CHROMIUM_CDP_URL = process.env.SMOKE_CHROMIUM_CDP_URL || '';
const DENIED_CHROMIUM_CDP_URL = process.env.SMOKE_DENIED_CHROMIUM_CDP_URL || '';
// LiveKit's browser transport is a WebSocket: ws(s)://, not the http(s) the
// backend uses for Twirp. Deriving it here keeps the operator to ONE variable.
const WS_URL = (
  process.env.SMOKE_BROWSER_LIVEKIT_URL || process.env.LIVEKIT_URL || ''
).replace(/^http/, 'ws');
// The response field holding the raw join credential, read through a variable
// rather than as `grant.join_token`. Reason: backend/tests/test_wave2_video_infra.py
// refuses to see a credential-shaped name on the left of an `=` or `:` anywhere
// under infra/video, and carving an exception for "but it's only a property
// access" is how the next REAL secret gets committed. The raw value is never
// logged, never written to evidence and never held in a named constant.
const JOIN_FIELD = 'join_token';
const ICE_POLICY_FIELD = 'video_ice_transport_policy';
const EXPECTED_ICE_POLICY = process.env.SMOKE_EXPECT_ICE_POLICY || '';
// A browser running inside the media network needs an HTTP origin beside the
// ws:// signalling endpoint; using the default HTTPS SDK origin would make
// Chromium correctly block the WebSocket as mixed content. Bare-metal keeps
// the existing SDK origin. The SDK itself is still fetched once by the Node
// controller and injected as content, never loaded from this page.
const TEST_ORIGIN =
  process.env.SMOKE_BROWSER_ORIGIN || new URL('.', BUNDLE_URL).href;

const want = (id) => STEPS.includes(id);
let failed = false;

function report(step, ok, detail) {
  process.stdout.write(`${step} ${ok ? 'PASS' : 'FAIL'} ${detail}\n`);
  if (!ok) failed = true;
}

function blocked(reason) {
  process.stdout.write(`BLOCKED: prerequisite runtime absent: ${reason}\n`);
  process.exit(BLOCKED_EXIT);
}

function parseHeader(raw) {
  // "Name: value" -> { Name: value }. The shell passes whole header lines so an
  // operator can paste exactly what curl uses.
  const index = String(raw || '').indexOf(':');
  if (index < 0) return null;
  return { [raw.slice(0, index).trim()]: raw.slice(index + 1).trim() };
}

async function issueCredential(header, label) {
  const parsed = parseHeader(header);
  if (!parsed) throw new Error(`${label}: header is not "Name: value"`);
  const response = await fetch(
    `${BACKEND_URL}/api/v1/tutoring/sessions/${SESSION_ID}/join-credentials`,
    { method: 'POST', headers: { ...parsed, 'Content-Type': 'application/json' } },
  );
  if (!response.ok) {
    throw new Error(`${label}: join-credentials returned ${response.status}`);
  }
  return response.json();
}

/** Load the client SDK once, so every page gets byte-identical code. */
async function loadBundle() {
  const response = await fetch(BUNDLE_URL);
  if (!response.ok) {
    blocked(`could not fetch the livekit-client bundle from ${BUNDLE_URL} (${response.status})`);
  }
  return response.text();
}

/**
 * One joined participant: its own browser context, its own credential, fake
 * camera and microphone. Returns handles the steps below drive.
 */
async function joinParticipant(browser, { bundle, grant, label, permissions }) {
  const context = await browser.newContext({ permissions });
  const page = await context.newPage();
  page.on('console', (message) => {
    if (message.type() === 'error') {
      process.stderr.write(
        `[${label}] console.error ${redactMediaRuntimeMessage(message.text())}\n`,
      );
    }
  });
  // about:blank has an opaque, insecure origin. Chromium's Private Network
  // Access checks correctly block it from opening a loopback WebSocket. A
  // localhost/HTTPS SDK origin is potentially trustworthy and exercises the
  // same policy the real application uses.
  await page.goto(TEST_ORIGIN);
  await page.addScriptTag({ content: bundle });
  const joined = await page.evaluate(
    async ({ url, joinJwt, canPublish, icePolicy }) => {
      const LK = window.LivekitClient || window.LiveKitClient;
      if (!LK) return { ok: false, error: 'the livekit-client UMD bundle did not expose a global' };
      const NativePeerConnection = window.RTCPeerConnection;
      window.__rtcConfigs = [];
      window.__rtcErrors = [];
      window.__peerConnections = [];
      window.RTCPeerConnection = function RecordedPeerConnection(config, ...args) {
        window.__rtcConfigs.push({
          phase: 'construct',
          iceTransportPolicy: config?.iceTransportPolicy,
          iceUrls: (config?.iceServers || []).flatMap((server) =>
            Array.isArray(server.urls) ? server.urls : [server.urls].filter(Boolean),
          ),
        });
        const peerConnection = new NativePeerConnection(config, ...args);
        window.__peerConnections.push(peerConnection);
        peerConnection.addEventListener('icecandidateerror', (event) => {
          // Numeric code + browser error text only. Candidate addresses, TURN
          // usernames and credentials are deliberately excluded from evidence.
          window.__rtcErrors.push({
            errorCode: event.errorCode || null,
            errorText: event.errorText || null,
          });
        });
        const nativeSetConfiguration = peerConnection.setConfiguration.bind(peerConnection);
        peerConnection.setConfiguration = (nextConfig) => {
          window.__rtcConfigs.push({
            phase: 'setConfiguration',
            iceTransportPolicy: nextConfig?.iceTransportPolicy,
            iceUrls: (nextConfig?.iceServers || []).flatMap((server) =>
              Array.isArray(server.urls) ? server.urls : [server.urls].filter(Boolean),
            ),
          });
          return nativeSetConfiguration(nextConfig);
        };
        return peerConnection;
      };
      window.RTCPeerConnection.prototype = NativePeerConnection.prototype;
      const room = new LK.Room({
        adaptiveStream: false,
        dynacast: false,
      });
      window.__room = room;
      window.__events = [];
      for (const name of ['reconnecting', 'reconnected', 'connected', 'disconnected']) {
        room.on(name, () => window.__events.push(name));
      }
      try {
        await room.connect(url, joinJwt, {
          rtcConfig: { iceTransportPolicy: icePolicy },
        });
      } catch (error) {
        const pc =
          room.engine?.pcManager?.publisher?._pc ||
          room.engine?.publisher?.pc ||
          room.engine?.pcManager?.subscriber?._pc ||
          window.__peerConnections.at(-1) ||
          null;
        const pcConfig = pc?.getConfiguration?.() || {};
        const joinIceServers = room.engine?.latestJoinResponse?.iceServers || [];
        return {
          ok: false,
          error: String(error && error.message ? error.message : error),
          // URLs and policy are safe diagnostics; never expose the TURN
          // username/credential fields that accompany these servers.
          iceUrls: (pcConfig.iceServers || room.engine?.rtcConfig?.iceServers || []).flatMap((server) =>
            Array.isArray(server.urls) ? server.urls : [server.urls].filter(Boolean),
          ),
          icePolicy:
            pcConfig.iceTransportPolicy ||
            room.engine?.rtcConfig?.iceTransportPolicy ||
            icePolicy,
          // This is deliberately limited to URLs and counts. TURN usernames
          // and credentials are short-lived secrets and must never enter the
          // release evidence even when connection establishment fails.
          joinIceServerCount: joinIceServers.length,
          joinIceUrls: joinIceServers.flatMap((server) => server.urls || []),
          rtcConfigs: window.__rtcConfigs,
          rtcErrors: window.__rtcErrors,
          connectionState: pc?.connectionState || null,
          iceConnectionState: pc?.iceConnectionState || null,
          iceGatheringState: pc?.iceGatheringState || null,
        };
      }
      let published = 0;
      let publishError = null;
      const captureContext = {
        isSecureContext: window.isSecureContext,
        hasMediaDevices: Boolean(navigator.mediaDevices),
        hasGetUserMedia: Boolean(navigator.mediaDevices?.getUserMedia),
      };
      if (canPublish) {
        try {
          await room.localParticipant.enableCameraAndMicrophone();
          published = room.localParticipant.trackPublications.size;
        } catch (error) {
          // Error class only: platform capture errors may contain a device
          // path or label in their message, neither of which belongs in release
          // evidence.
          publishError = String(error && error.name ? error.name : 'Error');
        }
      }
      return {
        ok: true,
        identity: room.localParticipant.identity,
        published,
        publishError,
        captureContext,
        state: room.state,
      };
    },
    {
      url: WS_URL,
      joinJwt: grant[JOIN_FIELD],
      canPublish: permissions.length > 0,
      icePolicy: grant[ICE_POLICY_FIELD] || 'all',
    },
  );
  return { context, page, joined, grant, label };
}

/** The selected ICE candidate pair, read from the real RTCPeerConnection stats. */
async function selectedCandidatePair(page, label) {
  return page.evaluate(async (participant) => {
    const room = window.__room;
    const pc =
      room?.engine?.pcManager?.publisher?._pc ||
      room?.engine?.publisher?.pc ||
      room?.engine?.pcManager?.subscriber?._pc ||
      null;
    if (!pc) return { participant, error: 'no RTCPeerConnection on the room' };
    const stats = await pc.getStats();
    let pair = null;
    const candidates = new Map();
    stats.forEach((report) => {
      if (report.type === 'local-candidate' || report.type === 'remote-candidate') {
        candidates.set(report.id, report);
      }
      if (
        report.type === 'candidate-pair' &&
        (report.nominated === true || report.state === 'succeeded')
      ) {
        if (!pair || (report.bytesSent || 0) > (pair.bytesSent || 0)) pair = report;
      }
    });
    if (!pair) return { participant, error: 'no succeeded/nominated candidate pair' };
    const local = candidates.get(pair.localCandidateId) || {};
    const remote = candidates.get(pair.remoteCandidateId) || {};
    const iceUrls = (pc.getConfiguration().iceServers || []).flatMap((server) =>
      Array.isArray(server.urls) ? server.urls : [server.urls].filter(Boolean),
    );
    const localCandidates = Array.from(candidates.values())
      .filter((candidate) => candidate.type === 'local-candidate')
      .map((candidate) => ({
        candidateType: candidate.candidateType || null,
        address: candidate.address || candidate.ip || null,
        port: candidate.port || null,
        protocol: candidate.protocol || null,
      }));
    return {
      participant,
      iceTransportPolicy: pc.getConfiguration().iceTransportPolicy || 'all',
      localCandidates,
      localCandidateType: local.candidateType || null,
      localAddress: local.address || local.ip || null,
      localPort: local.port || null,
      remoteCandidateType: remote.candidateType || null,
      remoteAddress: remote.address || remote.ip || null,
      remotePort: remote.port || null,
      protocol: local.protocol || null,
      iceUrls,
      bytesSent: pair.bytesSent || 0,
      bytesReceived: pair.bytesReceived || 0,
    };
  }, label);
}

async function main() {
  if (!SESSION_ID || !STUDENT_HEADER) {
    blocked('SMOKE_SESSION_ID and SMOKE_AUTH_HEADER must be set');
  }
  if (!WS_URL) blocked('LIVEKIT_URL must be set');

  let chromium;
  try {
    ({ chromium } = requireFromFrontend('playwright'));
  } catch (error) {
    blocked(`playwright is not installed (${error.message})`);
  }

  const bundle = await loadBundle();
  mkdirSync(OUT, { recursive: true });

  let browser;
  try {
    browser = CHROMIUM_CDP_URL
      ? await chromium.connectOverCDP(CHROMIUM_CDP_URL)
      : await chromium.launch({
          args: [
            // Deterministic media without a physical camera. This is the ONLY
            // simulated thing in the run: the SFU, the relay, the ICE negotiation
            // and every byte on the wire are real.
            '--use-fake-ui-for-media-stream',
            '--use-fake-device-for-media-stream',
            '--autoplay-policy=no-user-gesture-required',
          ],
        });
  } catch (error) {
    blocked(
      `chromium could not ${CHROMIUM_CDP_URL ? 'connect over CDP' : 'launch'} ` +
        `(${error.message}); run: npx playwright install chromium`,
    );
  }

  const participants = [];
  try {
    // ---------------------------------------------------------------- S4 ---
    if (want('S4')) {
      try {
        if (!TUTOR_HEADER) throw new Error('SMOKE_TUTOR_AUTH_HEADER is required for the second browser');
        const studentCred = await issueCredential(STUDENT_HEADER, 'student');
        const tutorCred = await issueCredential(TUTOR_HEADER, 'tutor');
        if (studentCred[JOIN_FIELD] === tutorCred[JOIN_FIELD]) {
          throw new Error('both participants were handed the SAME join grant, so it is not participant-bound');
        }
        if (studentCred.room_ref !== tutorCred.room_ref) {
          throw new Error('the two participants were sent to DIFFERENT rooms');
        }
        for (const [grant, label] of [[studentCred, 'student'], [tutorCred, 'tutor']]) {
          const policy = grant[ICE_POLICY_FIELD] || 'all';
          if (!['all', 'relay'].includes(policy)) {
            throw new Error(`${label} received invalid ICE policy ${String(policy)}`);
          }
          if (EXPECTED_ICE_POLICY && policy !== EXPECTED_ICE_POLICY) {
            throw new Error(
              `${label} received ICE policy ${policy}; expected server-authoritative ` +
                EXPECTED_ICE_POLICY,
            );
          }
        }
        for (const [grant, label] of [
          [studentCred, 'student'],
          [tutorCred, 'tutor'],
        ]) {
          const participant = await joinParticipant(browser, {
            bundle,
            grant,
            label,
            // The local release rig advertises coturn on the Mac's LAN address.
            // Chromium treats loopback-to-LAN WebRTC as Private Network Access;
            // grant that permission explicitly so the gate measures TURN/media,
            // not a browser permission prompt. Production uses public TLS hosts.
            permissions: ['camera', 'microphone', 'local-network-access'],
          });
          if (!participant.joined.ok) {
            throw new Error(
              `${label} could not join: ${participant.joined.error}; ` +
                `policy=${participant.joined.icePolicy}; ICE URLs=` +
                `${participant.joined.iceUrls?.join(', ') || '<none>'}; ` +
                `join ICE count=${participant.joined.joinIceServerCount ?? 0}; ` +
                `join ICE URLs=${participant.joined.joinIceUrls?.join(', ') || '<none>'}; ` +
                `constructed=${JSON.stringify(participant.joined.rtcConfigs || [])}; ` +
                `iceErrors=${JSON.stringify(participant.joined.rtcErrors || [])}; ` +
                `states=${JSON.stringify({ connection: participant.joined.connectionState, ice: participant.joined.iceConnectionState, gathering: participant.joined.iceGatheringState })}`,
            );
          }
          if (participant.joined.published < 2) {
            throw new Error(
              `${label} joined but published ${participant.joined.published} local ` +
                `track(s); expected fake camera + microphone; capture error=` +
                `${participant.joined.publishError || '<none>'}; ` +
                `context=${JSON.stringify(participant.joined.captureContext)}`,
            );
          }
          participants.push(participant);
        }
        // Each must SEE the other. Wait on the observable instead of sleeping:
        // a slow media path must not become a false negative, and an absent
        // remote track must not become a false positive after 5 seconds.
        for (const participant of participants) {
          await participant.page.waitForFunction(() => {
            const room = window.__room;
            const peers = room.remoteParticipants || room.participants;
            return (
              peers?.size >= 1 &&
              Array.from(peers.values()).some((peer) => peer.trackPublications.size >= 1)
            );
          }, null, { timeout: 30_000 });
          const remote = await participant.page.evaluate(() => {
            const room = window.__room;
            return {
              remotes: room.remoteParticipants ? room.remoteParticipants.size : room.participants.size,
              subscribed: Array.from(
                (room.remoteParticipants || room.participants).values(),
              ).reduce((total, peer) => total + peer.trackPublications.size, 0),
            };
          });
          if (remote.remotes < 1 || remote.subscribed < 1) {
            throw new Error(
              `${participant.label} sees ${remote.remotes} remote participant(s) and ` +
                `${remote.subscribed} remote track(s); expected at least 1 of each`,
            );
          }
        }
        const pairs = [];
        for (const participant of participants) {
          pairs.push(await selectedCandidatePair(participant.page, participant.label));
        }
        writeFileSync(join(OUT, 's4-candidate-pair.json'), JSON.stringify(pairs, null, 2));
        report(
          'S4',
          true,
          `two browsers joined room ${studentCred.room_ref} with distinct participant-bound tokens and each sees the other's tracks`,
        );
      } catch (error) {
        report('S4', false, error.message);
        throw error;
      }
    }

    // S5 runs after S6 when both are requested. Reusing the student's identity
    // while the S4 student is still connected triggers LiveKit's duplicate-
    // identity replacement policy and tests the wrong failure mode.
    const runS5 = async () => {
      try {
        const grant = await issueCredential(STUDENT_HEADER, 'student-denied');
        // The S4 browser deliberately auto-grants fake devices. Launch a
        // separate browser without --use-fake-ui-for-media-stream so S5 proves
        // the real denial path rather than overriding it at process level.
        const deniedBrowser = DENIED_CHROMIUM_CDP_URL
          ? await chromium.connectOverCDP(DENIED_CHROMIUM_CDP_URL)
          : await chromium.launch({
              args: [
                '--use-fake-device-for-media-stream',
                '--autoplay-policy=no-user-gesture-required',
              ],
            });
        // Chromium's loopback WebRTC connection is permission-gated separately
        // from media capture. Establish the provider transport first, then
        // revoke camera/microphone before capture. This reproduces the real
        // browser journey where a user denies or revokes device access on the
        // pre-join screen without turning the provider check into a false ICE
        // failure.
        const context = await deniedBrowser.newContext({
          permissions: ['camera', 'microphone', 'local-network-access'],
        });
        await context.grantPermissions(
          ['camera', 'microphone', 'local-network-access'],
          {
            origin: new URL(TEST_ORIGIN).origin,
          },
        );
        const page = await context.newPage();
        page.on('console', (message) => {
          if (message.type() === 'error') {
            process.stderr.write(
              `[student-denied] console.error ${redactMediaRuntimeMessage(message.text())}\n`,
            );
          }
        });
        await page.goto(TEST_ORIGIN);
        await page.addScriptTag({ content: bundle });
        const outcome = await page.evaluate(
          async ({ url, joinJwt, icePolicy }) => {
            const LK = window.LivekitClient || window.LiveKitClient;
            const room = new LK.Room();
            window.__room = room;
            const result = {
              connected: false,
              connectionError: null,
              iceUrls: [],
              published: 0,
              denial: null,
              deviceLabels: [],
            };
            try {
              await room.connect(url, joinJwt, {
                rtcConfig: { iceTransportPolicy: icePolicy },
              });
              result.connected = true;
            } catch (error) {
              result.connectionError = String(
                error && error.message ? error.message : error,
              );
              result.iceUrls = (room.engine?.rtcConfig?.iceServers || []).flatMap(
                (server) =>
                  Array.isArray(server.urls) ? server.urls : [server.urls].filter(Boolean),
              );
            }
            return result;
          },
          {
            url: WS_URL,
            joinJwt: grant[JOIN_FIELD],
            icePolicy: grant[ICE_POLICY_FIELD] || 'all',
          },
        );
        if (outcome.connected) {
          await context.clearPermissions();
          await context.grantPermissions(['local-network-access'], {
            origin: new URL(TEST_ORIGIN).origin,
          });
          const capture = await page.evaluate(async () => {
            const room = window.__room;
            let denial = null;
            try {
              await room.localParticipant.enableCameraAndMicrophone();
            } catch (error) {
              denial = String(error && error.name ? error.name : error);
            }
            let deviceLabels = [];
            try {
              const devices = await navigator.mediaDevices.enumerateDevices();
              deviceLabels = devices.map((device) => device.label).filter(Boolean);
            } catch {
              deviceLabels = [];
            }
            const published = room.localParticipant.trackPublications.size;
            await room.disconnect();
            return { denial, deviceLabels, published };
          });
          Object.assign(outcome, capture);
        }
        await context.close();
        await deniedBrowser.close();
        const problems = [];
        if (!outcome.connected) {
          problems.push(
            `the denied participant could not join (${outcome.connectionError}); ` +
              `ICE URLs: ${outcome.iceUrls.join(', ') || '<none>'}`,
          );
        }
        if (outcome.published !== 0) {
          problems.push(`published ${outcome.published} track(s) despite denied permissions`);
        }
        if (!outcome.denial) problems.push('capture did not raise a denial error');
        if (outcome.deviceLabels.length) {
          problems.push(`device labels leaked to the page: ${outcome.deviceLabels.join(', ')}`);
        }
        report(
          'S5',
          problems.length === 0,
          problems.length ? problems.join('; ') : `joined with camera+mic denied (${outcome.denial}), published 0 tracks, no device labels exposed`,
        );
        if (problems.length) throw new Error(problems.join('; '));
      } catch (error) {
        if (!failed) report('S5', false, error.message);
        throw error;
      }
    };

    // ---------------------------------------------------------------- S6 ---
    if (want('S6')) {
      let livekitStopped = false;
      try {
        if (!participants.length) {
          throw new Error('S6 needs the S4 participants; run S4 in the same invocation');
        }
        const { execFileSync } = await import('node:child_process');
        const composeArgs = [
          'compose',
          '-f',
          'docker-compose.yml',
          '-f',
          'infra/video/docker-compose.video.yml',
        ];
        if (process.env.SMOKE_COMPOSE_OVERRIDE) {
          composeArgs.push('-f', process.env.SMOKE_COMPOSE_OVERRIDE);
        }
        composeArgs.push('--profile', 'video');
        // Stop first and wait for both real clients to OBSERVE the outage.
        // `docker compose restart` could finish before Chromium dispatched the
        // Reconnecting event, making this gate a race between the container
        // runtime and the browser event loop rather than a reconnect proof.
        execFileSync(
          'docker',
          [...composeArgs, 'stop', 'livekit'],
          { stdio: 'pipe' },
        );
        livekitStopped = true;
        await Promise.all(
          participants.map((participant) =>
            participant.page.waitForFunction(
              () => window.__events.includes('reconnecting'),
              null,
              { timeout: 20_000 },
            ),
          ),
        );
        execFileSync('docker', [...composeArgs, 'up', '-d', 'livekit'], {
          stdio: 'pipe',
        });
        livekitStopped = false;
        const problems = [];
        for (const participant of participants) {
          await participant.page.waitForFunction(
            () =>
              window.__events.includes('reconnecting') &&
              window.__room.state === 'connected',
            null,
            { timeout: 60_000 },
          );
          const state = await participant.page.evaluate(() => ({
            events: window.__events,
            state: window.__room.state,
          }));
          if (!state.events.includes('reconnecting')) {
            problems.push(`${participant.label} never reported Reconnecting`);
          }
          if (state.state !== 'connected') {
            problems.push(`${participant.label} settled in state ${state.state}, not connected`);
          }
        }
        // The SAME token, reused: no new credential was issued for the rejoin.
        report(
          'S6',
          problems.length === 0,
          problems.length
            ? problems.join('; ')
            : 'both clients reconnected with the SAME token after an SFU restart; no credential re-issue needed',
        );
        if (problems.length) throw new Error(problems.join('; '));
      } catch (error) {
        // A failed gate must not leave the shared local media service stopped.
        if (livekitStopped) {
          try {
            const { execFileSync } = await import('node:child_process');
            const recoveryArgs = [
              'compose',
              '-f',
              'docker-compose.yml',
              '-f',
              'infra/video/docker-compose.video.yml',
            ];
            if (process.env.SMOKE_COMPOSE_OVERRIDE) {
              recoveryArgs.push('-f', process.env.SMOKE_COMPOSE_OVERRIDE);
            }
            recoveryArgs.push('--profile', 'video', 'up', '-d', 'livekit');
            execFileSync('docker', recoveryArgs, { stdio: 'pipe' });
          } catch {
            // Preserve the original reconnect failure as the gate result.
          }
        }
        const states = await Promise.all(
          participants.map(async (participant) => ({
            label: participant.label,
            ...(await participant.page
              .evaluate(() => ({
                events: window.__events,
                state: window.__room?.state,
              }))
              .catch(() => ({ events: [], state: 'page-unavailable' }))),
          })),
        );
        process.stderr.write(
          `S6 reconnect diagnostics ${JSON.stringify(states)}\n`,
        );
        if (!failed) report('S6', false, error.message);
        throw error;
      }
    }

    // ---------------------------------------------------------------- S5 ---
    if (want('S5')) {
      const activeStudentIndex = participants.findIndex(
        (participant) => participant.label === 'student',
      );
      if (activeStudentIndex >= 0) {
        await participants[activeStudentIndex].page.evaluate(() =>
          window.__room.disconnect(true),
        );
        await participants[activeStudentIndex].context.close();
        participants.splice(activeStudentIndex, 1);
        const remainingPeer = participants[0];
        if (remainingPeer) {
          await remainingPeer.page.waitForFunction(() => {
            const peers = window.__room.remoteParticipants || window.__room.participants;
            return peers?.size === 0;
          }, null, { timeout: 15_000 });
        }
      }
      await runS5();
    }
  } catch {
    // Every step reports its own verdict before rethrowing; nothing to add.
  } finally {
    for (const participant of participants) {
      await participant.context.close().catch(() => {});
    }
    await browser.close().catch(() => {});
  }
  process.exit(failed ? 1 : 0);
}

main().catch((error) => {
  process.stdout.write(`driver FAIL ${error.message}\n`);
  process.exit(1);
});
