# S-04/S-05 NYAY-8 authentication-context supersession

Effective 2026-08-25, NYAY-8 adds an explicit Student persona indicator and a
visible Change action to S-04 and S-05. The Change action does not perform a
client-only route change: it waits for the server to retire the current OTP
authority, clears page-memory OTP state, and only then replaces the route with
S-03. S-05 also remains non-actionable until the server proves an exact pending
login flow.

Those accepted product requirements intentionally change pixels in the six
previous Revision L S-04/S-05 references. Revision L remains authoritative for
tokens, typography, spacing, surfaces, responsive behavior, and component
geometry. NYAY-8 supersedes only the captured authentication state:

- **S-04:** Student context and Change are visible; the mobile input is empty.
- **S-05:** Student context and Change are visible only alongside a
  server-proven pending login projection. The OTP field remains mobile-only and
  purpose-bound.

## Sealed SHA-256 replacements

| Viewport | Screen | Superseded Revision L | Revision L + NYAY-8 contract |
|---|---|---|---|
| 1440x1024 | S-04 | `aa423164eeb06c5b7808d5832e358b2d779f8d89104abb44d1598750650f2a65` | `106da9aba4b25f87c0e8f7b8c9c73dfd0d533aa67a8a83e35f25c25bd4519129` |
| 1440x1024 | S-05 | `b033f0a85040ce83a0b9d4798935193df8058010ef4069c6ce44f78c50b7fc93` | `5d64b5ba642ebe15cc309c859d31417f7a3c6fb1a609ed73f2ea3f1f2db0aec5` |
| 390x844 | S-04 | `3f137f782f9dc5cf816dcd1d3e7d9a318d2e0d7eb80bd00dca93ddf36fd0cd6c` | `e58080b38099d68b98fc62961506d72fa7a919dcb162170723896f950f911a10` |
| 390x844 | S-05 | `93ccfca131abce3a791585d0f6df762173872ac69dd81994ca0270049ff9a931` | `c998e65650667f1de9654a3783c88f512e8bbe2f53b3f72f51db3587d6b12794` |
| 360x800 | S-04 | `9851a2fe80158a0310c8f69a2176fa0f41f5346795c041e3e91f95833753fd55` | `2e2058bcd541fb04a2332cec31d8bb36b08ccd15598ea335c77235298f7454ac` |
| 360x800 | S-05 | `a5e0b383494c9ede308a7135fa6b380889b905a5797511e7a208bd3f115d0395` | `e7427c4e80ea35ee9d10accb474a5d00a3fe2a45aab3ba9145188ee04bf0bd53` |

## Capture and oracle posture

- Production runner: `scripts/nyay7-ui-foundation.mjs`
- Base commit: `0ac8fb77cd736a7b5edde28d0d08790d00bc2d09`
- Capture timestamp: `2026-08-25T09:20:48.844Z`
- Platform: macOS arm64, production Vite build, Playwright Chromium
- Pre-reconciliation gate: 350/350 expanded; 114/120 canonical, with only
  these six intentional pixel changes failing

All 15 visual comparisons remain blocking through the same common comparison
path and unchanged one-percent threshold. No Axe rule, responsive assertion,
selector contract, timeout, authentication boundary, OTP oracle, or privacy
scanner was disabled, allowlisted, skipped, or weakened.
