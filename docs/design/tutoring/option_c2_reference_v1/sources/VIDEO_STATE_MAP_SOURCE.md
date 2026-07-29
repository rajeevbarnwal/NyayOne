# Video Permission/Device State Map + Provider-Neutral Component Map

## Permission & device states (trigger → state → recovery)
| Trigger | State ID | Recovery |
|---|---|---|
| User clicks Test camera & mic (explicit gesture) | s35-devices | preview starts on grant |
| Browser prompt dismissed | s35-perm-pending | re-invoke from button |
| Camera denied | s35-perm-cam | address-bar unblock → re-check; audio-only join |
| Mic denied | s35-perm-mic | settings → re-check; listen-only join |
| No devices | s35-no-device | connect + re-check; chat-only join |
| Device busy (NotReadable) | s35-device-busy | close other app → re-check |
| Unsupported browser | s35-unsupported | modern browser list |
| Insecure origin | s35-insecure | HTTPS/localhost requirement |
| OverconstrainedError | s35-constraint | auto SD fallback |
| Disconnect mid-call | s35-remote-missing / s35-reconnecting | auto-recover; reconnect keeps the same room |

## Join gates (server-side): s35-join-early-v · s35-pay-unverified · s35-token-expired · s35-wrong-user · s35-ended.
Credential rule: issued on Join, opaque, participant-bound, short TTL; never in URL, storage, fixtures or annotations (the prototype shows only the *rule*, no credential value).

## Room states
waiting → live (tutor joined) → muted / cam-off / autoplay-blocked / remote-missing / degraded / reconnecting / icefail (full reconnect, same session) / tutor-left → leave-confirm → post (all local tracks stopped; camera indicator off; reload does not reacquire).

## Provider-neutral component map
| Component | Owns | Key props/events |
|---|---|---|
| `PreJoin` | identity, authorisation summary, device-test entry, join CTA | session, participantRole, onTest, onJoin |
| `DeviceCheck` | gUM invocation (gesture-only), preview, selectors, level, test tone | devices, onGrant(err), onJoin |
| `VideoRoom` | layout, status strip, control bar, reconnect loop | provider:VideoSessionProvider, session, onLeave |
| `ParticipantTile` | media element/placeholder, name/role, mute/cam badges, active-speaker | participant, stream?, active |
| `DeviceMenu` | mid-call device switching | devices, current, onChange |
| `ConnectionStatus` | text quality, reconnect states | quality, state |
| `AttendanceResolution` | marked/confirm/dispute/resolution timeline | attendance, role, onConfirm/onDispute |

## Deterministic simulation (this prototype)
Local preview: real `getUserMedia` from the button only. Remote tutor: bundled synthetic canvas avatar + animated audio bars (no real person, reduced-motion aware) — developer control documented here, not shown in product UI. Every room/flag state is URL-addressable for screenshot automation.

## Automated fake-media plan (Chromium)
`--use-fake-device-for-media-stream --use-fake-ui-for-media-stream` (+ Playwright `permissions: ['camera','microphone']`), then walk states via `window.__opt.apply(id)` / URL flags and assert: preview plays, tracks stop on leave (`__opt.V.stream === null`), no credential strings anywhere. **Automated fake-media PASS is not a substitute for the manual real-device checklist** (separate doc).