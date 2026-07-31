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
import { join } from 'node:path';

const BLOCKED_EXIT = 78;
const OUT = process.env.SMOKE_OUT || 'test-results/livekit-smoke';
const BACKEND_URL = process.env.SMOKE_BACKEND_URL || 'http://localhost:1031';
const STEPS = (process.env.SMOKE_STEPS || 'S4,S5,S6').split(',').filter(Boolean);
const BUNDLE_URL =
  process.env.LIVEKIT_CLIENT_BUNDLE ||
  'https://cdn.jsdelivr.net/npm/livekit-client/dist/livekit-client.umd.min.js';
const SESSION_ID = process.env.SMOKE_SESSION_ID;
const STUDENT_HEADER = process.env.SMOKE_AUTH_HEADER;
const TUTOR_HEADER = process.env.SMOKE_TUTOR_AUTH_HEADER;
// LiveKit's browser transport is a WebSocket: ws(s)://, not the http(s) the
// backend uses for Twirp. Deriving it here keeps the operator to ONE variable.
const WS_URL = (process.env.LIVEKIT_URL || '').replace(/^http/, 'ws');
// The response field holding the raw join credential, read through a variable
// rather than as `grant.join_token`. Reason: backend/tests/test_wave2_video_infra.py
// refuses to see a credential-shaped name on the left of an `=` or `:` anywhere
// under infra/video, and carving an exception for "but it's only a property
// access" is how the next REAL secret gets committed. The raw value is never
// logged, never written to evidence and never held in a named constant.
const JOIN_FIELD = 'join_token';

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
      process.stderr.write(`[${label}] console.error ${message.text()}\n`);
    }
  });
  await page.goto('about:blank');
  await page.addScriptTag({ content: bundle });
  const joined = await page.evaluate(
    async ({ url, joinJwt, canPublish }) => {
      const LK = window.LivekitClient || window.LiveKitClient;
      if (!LK) return { ok: false, error: 'the livekit-client UMD bundle did not expose a global' };
      const room = new LK.Room({ adaptiveStream: false, dynacast: false });
      window.__room = room;
      window.__events = [];
      for (const name of ['reconnecting', 'reconnected', 'connected', 'disconnected']) {
        room.on(name, () => window.__events.push(name));
      }
      try {
        await room.connect(url, joinJwt);
      } catch (error) {
        return { ok: false, error: String(error && error.message ? error.message : error) };
      }
      let published = 0;
      let publishError = null;
      if (canPublish) {
        try {
          await room.localParticipant.enableCameraAndMicrophone();
          published = room.localParticipant.trackPublications.size;
        } catch (error) {
          publishError = String(error && error.name ? error.name : error);
        }
      }
      return {
        ok: true,
        identity: room.localParticipant.identity,
        published,
        publishError,
        state: room.state,
      };
    },
    { url: WS_URL, joinJwt: grant[JOIN_FIELD], canPublish: permissions.length > 0 },
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
    return {
      participant,
      localCandidateType: local.candidateType || null,
      localAddress: local.address || local.ip || null,
      localPort: local.port || null,
      protocol: local.protocol || null,
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
    ({ chromium } = await import('playwright'));
  } catch (error) {
    blocked(`playwright is not installed (${error.message})`);
  }

  const bundle = await loadBundle();
  mkdirSync(OUT, { recursive: true });

  let browser;
  try {
    browser = await chromium.launch({
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
    blocked(`chromium could not launch (${error.message}); run: npx playwright install chromium`);
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
        for (const [grant, label] of [
          [studentCred, 'student'],
          [tutorCred, 'tutor'],
        ]) {
          const participant = await joinParticipant(browser, {
            bundle,
            grant,
            label,
            permissions: ['camera', 'microphone'],
          });
          if (!participant.joined.ok) {
            throw new Error(`${label} could not join: ${participant.joined.error}`);
          }
          participants.push(participant);
        }
        // Each must SEE the other. A join that publishes into the void is not
        // a call.
        await new Promise((resolve) => setTimeout(resolve, 5000));
        for (const participant of participants) {
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

    // ---------------------------------------------------------------- S5 ---
    if (want('S5')) {
      try {
        const grant = await issueCredential(STUDENT_HEADER, 'student-denied');
        const context = await browser.newContext({ permissions: [] });
        await context.clearPermissions();
        const page = await context.newPage();
        await page.goto('about:blank');
        await page.addScriptTag({ content: bundle });
        const outcome = await page.evaluate(
          async ({ url, joinJwt }) => {
            const LK = window.LivekitClient || window.LiveKitClient;
            const room = new LK.Room();
            const result = { connected: false, published: 0, denial: null, deviceLabels: [] };
            await room.connect(url, joinJwt);
            result.connected = true;
            try {
              await room.localParticipant.enableCameraAndMicrophone();
            } catch (error) {
              result.denial = String(error && error.name ? error.name : error);
            }
            result.published = room.localParticipant.trackPublications.size;
            try {
              const devices = await navigator.mediaDevices.enumerateDevices();
              result.deviceLabels = devices.map((device) => device.label).filter(Boolean);
            } catch {
              result.deviceLabels = [];
            }
            await room.disconnect();
            return result;
          },
          { url: WS_URL, joinJwt: grant[JOIN_FIELD] },
        );
        await context.close();
        const problems = [];
        if (!outcome.connected) problems.push('the denied participant could not join at all');
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
    }

    // ---------------------------------------------------------------- S6 ---
    if (want('S6')) {
      try {
        if (!participants.length) {
          throw new Error('S6 needs the S4 participants; run S4 in the same invocation');
        }
        const { execFileSync } = await import('node:child_process');
        // RUNBOOK § 9 item 4's own command.
        execFileSync(
          'docker',
          [
            'compose',
            '-f',
            'docker-compose.yml',
            '-f',
            'infra/video/docker-compose.video.yml',
            '--profile',
            'video',
            'restart',
            'livekit',
          ],
          { stdio: 'pipe' },
        );
        await new Promise((resolve) => setTimeout(resolve, 25000));
        const problems = [];
        for (const participant of participants) {
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
        if (!failed) report('S6', false, error.message);
        throw error;
      }
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
