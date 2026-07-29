# Option C2 reference v1 — LegalSaathi Wave 2 tutoring (S-31…S-35)

Executable, measured design reference for the approved Option C2 direction.
Owning tickets: **SAATHI-125** (S-31…S-34) and **SAATHI-129** (S-35).

Start with `SOURCE_OF_TRUTH.md`.

| File | What it is |
|---|---|
| `SOURCE_OF_TRUTH.md` | provenance, what is approved, what is proposed, what is pending |
| `PRODUCT_DECISION_REGISTER.md` | 18 decisions traced to live Jira comments, or marked absent |
| `STATE_INVENTORY.json` | all 82 states, 13 attributes each |
| `SCREEN_ROUTE_API_BINDING_MATRIX.md` | screens, routes, obligations — no invented API names |
| `DETERMINISTIC_FIXTURE_CONTRACT.json` | frozen fixtures + checksum + privacy canaries |
| `RESPONSIVE_GEOMETRY_BUDGETS.md` | budgets and the 1,968 measured rows behind them |
| `ACCESSIBILITY_AND_INTERACTION_SPEC.md` | targets, focus, announcements, non-colour cues |
| `TOKEN_COMPONENT_MOTION_SPEC.md` | tokens, components, motion, the live-room repair rules |
| `IMPLEMENTATION_HANDOFF.md` | what to rely on, what not to, and how to reproduce |
| `VISUAL_BASELINE_MANIFEST.json` | 40 reference captures with per-file SHA-256 |
| `MEASURED_GEOMETRY_RESULTS.json` | 1,968 real Chromium rows |
| `BEFORE_AFTER_LIVE_ROOM.json` | the reproduced defect, its root cause and the repair |
| `NEGATIVE_TEST_RESULTS.md` / `.json` | 81 executable negative cases |
| `NATIVE_GATE_RESULTS.json` | frontend gate return codes for this branch |
| `reference/` | the offline executable reference (open `index.html`) |
| `tests/`, `tools/` | the executable equality test and the measurement/checksum tools |
| `sources/` | read-only copies of every upstream source used |
| `captures/` | the reference PNGs |
| `SHA256SUMS.txt` | checksums of every file above |

Open `reference/index.html?state=s35-room-live&chrome=1` to browse all 82 states.
Fully offline: no network request, no cookie, no web storage.
