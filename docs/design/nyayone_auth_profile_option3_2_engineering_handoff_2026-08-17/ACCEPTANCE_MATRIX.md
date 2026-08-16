# NyayOne Option 3.2 acceptance matrix

Every mandatory row must have an automated assertion and raw evidence from the exact remote PR head. A green visual review alone is not sufficient.

| ID | Area | Mandatory outcome |
|---|---|---|
| UX-01 | S-03 | Both gateway actions navigate to the correct routes and have accessible names |
| UX-02 | Typography | Every redesigned H1 and H2 declares the Aptos, Calibri, Carlito, system UI stack |
| UX-03 | Icons | Approved SVG icons render, remain non-focusable, and do not replace labels |
| UX-04 | Responsive | No horizontal overflow at 360x800, 390x844, 390x430, and 1440x1024 |
| UX-05 | Targets | Every mobile interactive target measures at least 44 by 44 CSS pixels |
| UX-06 | Rebrand | Redesigned screens contain no visible LegalSaathi copy or newly introduced `legalsaathi.*` keys |
| AUTH-00 | Passwordless | S-03 through S-06 make no password field, mode, toggle, or password-auth request |
| AUTH-01 | Mobile OTP | Correct OTP succeeds only after the exact successful server response |
| AUTH-02 | OTP negative | Blank, malformed, wrong, expired, reused, locked, and rate-limited OTP cannot authenticate |
| AUTH-03 | Resend | Cooldown, provider failure, retry budget, invalidation, and concurrent resend fail closed |
| AUTH-04 | Enumeration | Known, unknown, suspended, and ineligible login or resend inputs have equivalent external contracts |
| AUTH-05 | Email gate | Email OTP remains disabled without unique verified identity ownership and cannot open S-15 anonymously |
| AUTH-06 | Browser secrets | No raw OTP, identity, token, bearer, session value, registration authority, or profile PII exists in Web Storage or evidence; approved masked synthetic destinations are allowed |
| AUTH-07 | Signup session | Signup OTP consumption, user activation, session rotation, cookie creation, and projection return are atomic and replay-safe |
| AUTH-08 | Session defense | Cookie attributes, exact Origin checks, logout, rotation, revocation, and old-cookie replay tests pass |
| AUTH-09 | OTP metadata | Expiry, resend delay, attempts, and status come from safe server metadata and are enforced server-side |
| REG-01 | Consent | Missing Terms acceptance or Privacy Notice acknowledgement returns 422 and creates no registration, OTP, outbox, or audit row |
| REG-02 | Field contract | S-08 contains name, mobile, DOB, Terms, and Privacy acknowledgement; institutional email is absent |
| REG-03 | Enumeration | New, known, duplicate, suspended, and ineligible registrations return the same 202 status and safe body shape without unsafe overwrite |
| REG-04 | Legal copy | Terms acceptance and Privacy Notice acknowledgement use separate fields, versions, labels, and persistence semantics |
| REG-05 | Unicode names | Frontend and backend share an NFC corpus and agree on categories, punctuation, ASCII-space rules, normalization, and 1 through 60 code-point boundaries |
| OWN-01 | Anonymous | Anonymous profile, guardian, and verification reads or mutations fail with zero data change |
| OWN-02 | Cross-user | User A cannot read or mutate User B through a UUID, body field, URL, header, stale browser state, or forged registration identifier |
| OWN-03 | Role | Student cannot perform guardian or institutional-reviewer transitions; authorized role positive tests are separate |
| OWN-04 | Test authority | Production frontend sends no actor-claims or test-auth header and non-test backend rejects either header |
| ROUTE-01 | Mapping | S-07 hosts the popup and S-14 remains the full dashboard |
| ROUTE-02 | Popup | Complete routes to the first incomplete section and dismissal routes to S-14 |
| ROUTE-03 | Email return | Authenticated S-15 returns only to an allowlisted origin without secrets |
| ROUTE-04 | Migration | Legacy S-05 failure and S-09 login links migrate to the new S-05 login-OTP and S-09 signup-only contract |
| ROUTE-05 | Protected routes | Anonymous S-07 and S-10 through S-17 access returns to S-03; wrong roles are denied |
| ROUTE-06 | S-10 section | Only `personal` and `academic` section values are accepted and later incomplete sections cannot be bypassed |
| PROFILE-01 | Projection | Every relevant screen consumes the same versioned onboarding-state response |
| PROFILE-02 | Progress | Version v1 produces only deterministic 0, 34, 67, and 100 values from persisted complete sections |
| PROFILE-03 | New user | A new user never starts at a fabricated 67 percent |
| PROFILE-04 | Save | Personal, academic, and interests each persist before navigation |
| PROFILE-05 | Failure | 401, 403, 409, 422, 429, 500, abort, timeout, and network failure retain route and values |
| PROFILE-06 | Uncertain result | An interrupted response triggers authoritative reconciliation before retry or navigation |
| PROFILE-07 | Resume | Reload and new navigation hydrate the same server state |
| PROFILE-08 | Completeness | Direct route entry cannot bypass earlier required sections |
| PROFILE-09 | Validation | Real field changes resolve errors without a demo or reviewer bypass |
| PROFILE-10 | Concurrency | Stale multi-tab writes return a typed conflict and do not overwrite newer data |
| PROFILE-11 | Model | Normalized tables expose one owner-scoped API/read model without duplicated identity PII |
| POPUP-01 | Lifecycle | Incomplete state opens once per authenticated session; complete or dismissed state continues immediately to S-14 without flash |
| POPUP-02 | Keyboard | Focus enters, real Tab and Shift+Tab wrap, Escape closes, and focus restores |
| POPUP-03 | Persistence | Dismissal survives reload for the same auth session and clears on logout, rotation, actor change, or expiry |
| POPUP-04 | Discoverability | S-14 and S-17 show a completion card until server completion reaches 100 percent |
| GUARD-01 | Adult to minor | Versioned DOB mutation atomically makes guardian required and enters restricted access |
| GUARD-02 | Minor to adult | Versioned DOB mutation makes guardian not required without fabricated verification |
| GUARD-03 | Authority | Student cannot complete guardian consent or institutional verification |
| GUARD-04 | Reviewer | Only an explicit authorized reviewer or approved guardian ceremony can perform positive transitions |
| GUARD-05 | Reload | Limited access remains enforced after reload, new login, and direct navigation |
| A11Y-01 | Errors | Field errors and error summaries are programmatically linked and focusable |
| A11Y-02 | OTP | Full-code paste, platform autofill, numeric input, and correction work |
| A11Y-03 | Dialog | Dialog name, modality, inert background, focus containment, and restore are verified |
| A11Y-04 | Keyboard viewport | Active field and error remain visible and the primary action remains reachable at 390x430 |
| QA-01 | Native | Typecheck, lint, full unit tests, and production build pass |
| QA-02 | Target runtime | PostgreSQL migration, backend, API, ownership, and concurrency gates pass |
| QA-03 | Browser | Real Chromium runs mobile, desktop, keyboard, mobile OTP, and disabled email states |
| QA-04 | Evidence | Reports, screenshots, logs, privacy scan, and SHA256 manifest are complete and verified |
| QA-05 | CI | All required checks pass on the exact remote head and prospective merge |
| QA-06 | Assertion inventory | Every matrix ID maps to at least one executed non-skipped assertion and zero-selector collections fail |

## Seeded oracle checks

The test suite must prove it fails when each defect is deliberately introduced through disposable fixtures or explicit test-only injection:

- S-14 is substituted for the S-07 popup host.
- Progress is hard-coded to 67 percent.
- Empty OTP is accepted.
- A fixed delay navigates without the exact successful response.
- Password mode reappears.
- Consent is unchecked.
- A decomposed valid name, punctuation-only name, tabbed name, or 61-code-point name disagrees across runtimes.
- Registration existence is disclosed.
- A failed save navigates forward.
- A reviewer or demo control marks invalid fields corrected.
- A stale profile write overwrites a newer write.
- Guardian or verification state is changed by a student.
- A forged registration UUID grants authority.
- A raw token or identity is inserted into Web Storage or evidence.
- An icon, target, or selector oracle matches zero elements and reports success.
- A required workflow job fails while its aggregator reports success.

Remove every seeded defect before sealing final evidence. Never commit deliberately broken application source as an oracle test.
