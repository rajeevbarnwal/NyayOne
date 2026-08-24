# NYAY-7 · NyayOne 3.2.1 foundation contract

## Authority and precedence

Appearance is pinned to the provenance-corrected Claude Design Revision L source:

- Source: `NYAYONE_OPTION3_2_1_REVL_SOURCE.html`
- SHA-256: `338d5fd22b5e9e8c3c7599846428c99b151b3adf21907f69998a54fdefe33252`
- Independent native-QA verdict: `READY_TO_FREEZE_REV_L`
- Independent inventory: 170/170 declared entries verified; no missing, undeclared, unsafe, or symlink paths.

The tracked Option 3.2 engineering handoff remains authoritative for product behavior and security, with this precedence:

1. `ENGINEERING_CONTRACT.md`
2. `SCREEN_MAP.md`
3. `ACCEPTANCE_MATRIX.md`
4. `IMPLEMENTATION_PLAN.md`
5. Revision L for appearance and the final 3.2.1 selector delta

Prototype JavaScript is never application logic. Authentication, authorization, OTP, consent, session, route ownership, and storage boundaries remain server-authoritative.

## Final screen delta

- S-03 owns the persona and interface-language selectors inside the new-account path.
- S-04 and S-05 contain no persona or locale authority.
- S-08 and S-09 carry the create-account Student/English context.
- Persona order is Lawyer, Student, Customer, University. Only Student is available and selected.
- Interface-language order is English, हिन्दी, ಕನ್ನಡ. Only English is available and selected.
- Unavailable choices remain visible, programmatically disabled, and carry the text “Coming soon”.
- Persona and locale are presentation/routing intent only and are never persisted as authority.

## Required production gates

- True viewports: 1440×1024, 390×844, and 360×800.
- Five default screens: S-03, S-04, S-05, S-08, and S-09.
- Zero serious or critical Axe violations; no Axe rule is disabled.
- Every visible interactive target is at least 44×44 CSS pixels in mobile viewports.
- Zero horizontal overflow and cumulative layout shift no greater than 0.1.
- Approved baseline images are copied byte-for-byte under `frontend/test-baselines/nyay7/option-3.2.1-rev-l` and sealed by `manifest.json`.
