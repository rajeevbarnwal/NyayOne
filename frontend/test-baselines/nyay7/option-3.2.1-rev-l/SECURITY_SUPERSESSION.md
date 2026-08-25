# S-08/S-09 security-contract supersession

Effective 2026-08-25, the Product Owner invalidated the NyayOne Option 3.2.1
Revision L S-08 and S-09 mockup states where they conflict with the merged
NYAY-2, NYAY-4, and NYAY-19 security and privacy contracts. Revision L remains
the visual authority for S-03, S-04, and S-05; only the six S-08/S-09 canonical
captures named in `manifest.json` are superseded.

## Authoritative capture states

- **S-08:** Fresh registration state with every identity input empty. Terms and
  Privacy Notice are two distinct, visible, programmatically required, and
  unchecked acknowledgements. No PII is planted in the baseline.
- **S-09:** Pending OTP state, captured as the final stable static frame before
  verification. A successful server-authoritative verification immediately
  replaces this route with S-07. A persistent client-side success screen is
  intentionally absent.

The S-09 fixture supplies only the server-shaped pending OTP projection needed
to render the pre-redirect frame. It does not synthesize successful verification
or bypass the production redirect. The screenshots were emitted by the
production build through the fail-closed Playwright gate at the three canonical
viewports. No authentication, session, consent, or OTP product logic was changed
to create these references.

## Sealed SHA-256 replacements

| Viewport | Screen | Superseded Revision L | Security-contract baseline |
|---|---|---|---|
| 1440x1024 | S-08 | `04cb846ffa2ed9379982ba97715fa524c80a24e8dafe10f91c572c17e9f03c66` | `70ce15e76201c816876ae282e906edc942aabd9cf87ec8b72129ae3e02a0ea39` |
| 1440x1024 | S-09 | `ca3ea07af59078dc775b63d5395a2aa63cf582058db04f8bdd74b47a8f8b6f82` | `231f37f3604aa1210809f7aabddfb7f35792c164a6cd0ad39e32d841d2cb9f5d` |
| 390x844 | S-08 | `ff2bb433ee15733bdaba5413d4d8b97fc811a5d30c54cb89295350fb4c1bf608` | `0bb2c19de7bc6135f8b9c42ab11b2b2da0a1ce7595b40bc12ad8e1dc249c5c60` |
| 390x844 | S-09 | `a4277eae27d2e1c8cbf3c21e0d51856f73b93a5a242e11f5f5692f4fc1281e29` | `91fe93265420db14a631fc17c0f48ebca49da76c68473ce2ca82677e6e73287b` |
| 360x800 | S-08 | `836824be082af1fa91f13f4659e02003b996ef8247bd341b6f6a6c625fa996eb` | `a3fdc5616bd21c1c1b33bebff78feda8ddc0bf3c7096f1f6b30ec656775242c3` |
| 360x800 | S-09 | `b8ab19542afb775ece07b59b015c0f87d1e1393f72e3a63c28166eb8a1e998a5` | `bccf2f2c0171cce2ed877d53371ee31a1d9652e9bdecc4d85e76eb3c014fff78` |

The source-contract test pins these values independently of the manifest and
fails closed if an image, authority marker, or this supersession record is
removed or changed without review.

## Capture provenance and oracle posture

- Production runner: `scripts/nyay7-ui-foundation.mjs`
- Worktree parent: `933a8a34bd38bcfb5e5ea6e5018f54e6ac2c9719`
- Final capture timestamp: `2026-08-24T18:35:40.044Z`
- Platform: macOS arm64; Node `22.21.1`; Playwright/Chromium `1.61.1`
- Pre-supersession report SHA-256: `5b6ee79a6777e899b5c8ad07cdb0ca84e849398ba2c37c63ee7ac3f6e94e2ddb`
- Final GREEN report SHA-256: `337dda0bfa9c21988172996cef51b7cd56ad5885e366f1fc02ec374822f20cc4`
- Final gate: canonical 120/120 and expanded responsive/theme 350/350

All 15 visual assertions remain blocking and use the same one-percent mismatch
threshold and common comparison path. No Axe rule, responsive assertion,
selector contract, timeout, or visual threshold was relaxed. The eventual GREEN
commit is the immutable repository identity for these captured bytes.
