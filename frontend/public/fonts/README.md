# Self-hosted fonts (offline, no external requests)

`src/styles/fonts.css` serves these files locally. **Do not** add Google Fonts
`<link>` tags or any external font URL — fonts must load only from this directory
(offline / app-store safe).

| Family | File | Weights | License | Provenance |
|---|---|---|---|---|
| Hanken Grotesk | `HankenGrotesk-Variable-latin.woff2` | 400–800 (variable, latin subset) | SIL OFL 1.1 | Option C+ reference package payload (2026-07-27) |
| Newsreader | `Newsreader-Variable-latin.woff2` | 200–800 (variable, latin subset) | SIL OFL 1.1 | Option C+ reference package payload (2026-07-27) |
| IBM Plex Mono | `IBMPlexMono-{Regular,Medium,SemiBold}-latin.woff2` | 400 / 500 / 600 (latin subset) | SIL OFL 1.1 | Option C+ reference package payload (2026-07-27) |
| Public Sans | `PublicSans-latin.woff2` | 400–800 mapped from the approved latin payload | SIL OFL 1.1 | NyayOne 3.2.1 Revision L authoring artifact |
| Carlito | `Carlito-{Regular,Bold}-latin.woff2` | 400 / 700 (latin subset) | SIL OFL 1.1 | Revision L artifact; registered under the isolated `NyayOne Revision L Heading` alias |
| Space Grotesk | `SpaceGrotesk-latin.woff2` | 500 / 600 mapped from the approved latin payload | SIL OFL 1.1 | NyayOne 3.2.1 Revision L authoring artifact |
| Spectral | `Spectral-{Light,Semibold}-latin.woff2` | 300 / 600 (latin subset) | SIL OFL 1.1 | NyayOne 3.2.1 Revision L authoring artifact |
| Spline Sans Mono | `SplineSansMono-latin.woff2` | 400–600 mapped from the approved latin payload | SIL OFL 1.1 | NyayOne 3.2.1 Revision L authoring artifact |

These are the exact OFL woff2 payloads embedded in the approved Option C+ baseline
frames (`docs/design/lawschool_reference/option_c_plus/OPTION_C_PLUS_GUIDED_CONFIDENCE.html`),
extracted so the developed screens rasterise with the same glyphs as the reference
(SAATHI-121 40-pair visual gate). All three families are OFL-licensed and may be
self-hosted/redistributed.

The Revision L payloads are likewise the exact embedded latin WOFF2 bytes from
the provenance-corrected authoring artifact (SHA-256
`338d5fd22b5e9e8c3c7599846428c99b151b3adf21907f69998a54fdefe33252`).
They are namespaced to the NYAY-7 token layer where needed so adding the
approved files does not change legacy-screen fallback typography.

**Still deferred:** `JetBrainsMono-Variable.woff2` (`--font-mono` outside the
law-school scope falls back to the system mono stack until it is added).
