# S-01–S-10 v3.4 integration

## Reference provenance

- Product-supplied folder: `/Users/rajeevbarnwal/Desktop/Codes/LegalSaathi/docs/design/v3.4/`
- Implemented handoff: `# Enterprise Legal AI_ Trust & Auditability/handoff/LegalSaathi_v3.3_S01-S10.html`
- Source SHA-256: `c1114480e12787ef3ae2b2dd41d015f146fb15b934daf65caa9d7406cabc29d5`
- The folder is named v3.4, while the handoff document identifies itself as v3.3. This discrepancy is preserved in this record rather than silently renamed.

The handoff explicitly replaces S-01–S-10 and defines the following canonical mapping:

| Screen | Ownership |
|---|---|
| S-01 | Splash and session check |
| S-02 | First-launch onboarding |
| S-03 | Authentication gate |
| S-04 | Login |
| S-05 | Login failure |
| S-06 | Password recovery |
| S-07 | Verified home |
| S-08 | Student registration |
| S-09 | OTP verification |
| S-10 | Profile setup, personal step |

## Production integration decisions

- The visual system is implemented as scoped `.v34-*` CSS. No global token or downstream S-11–S-99 visual ownership was changed.
- S-01–S-10 own their application shell. The legacy rail/topbar/bottom navigation is suppressed only for those routes.
- The reference registration omitted date of birth, even though the existing API and eligibility rules require it. Date of birth is retained and future dates are explicitly rejected.
- Institutional email, college/university, year of study and optional Bar enrolment remain visible. These legacy data fields were not silently dropped.
- First, middle and last names remain distinct through the registration API payload. S-10 uses the preferred-name presentation defined by the new reference.
- S-06 uses the existing non-enumerating recovery start/verify/complete API lifecycle.
- S-08 and S-09 use the existing server registration and OTP APIs. No fixed OTP or mock-success path was added.
- The application does not yet expose production student password-session or login-OTP endpoints. S-04 password submission therefore shows the generic S-05 failure state, while login OTP reports that it is unavailable; neither path fabricates authentication. Server-backed registration OTP remains available on S-08/S-09.
- Icon-only actions use inline SVG plus an accessible name and matching tooltip text (`aria-label` and `data-tip`). Running-prose links remain text links.
- Academic profile entry remains reachable from S-10 through `?step=academic`, followed by the existing S-11 and S-12 flow.

## Verification

Run the isolated visual/negative gate while the frontend is available:

```bash
cd frontend
V34_BASE_URL=http://127.0.0.1:4174 \
V34_EVIDENCE_DIR=/Users/rajeevbarnwal/Documents/LegalSaathi/QA/v34_s01_s10_integration_2026-08-01 \
npm run qa:v34:s01-s10
```

The gate covers all ten screens at 390×844 and 1440×900, in both themes, plus strict mobile-length, future-date, empty, special-character, maximum-length, split-name payload, legacy-field parity and icon-tooltip assertions.

The full server-backed registration runner remains `npm run qa:registration`; it now follows S-08 → S-09 → S-10 and exercises the HTTP OTP-capture provider.
