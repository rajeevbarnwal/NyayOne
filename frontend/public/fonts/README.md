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
| Public Sans (isolated S-20 rupee fallback) | `s20/PublicSans-v32108-latin-ext.woff2` | 400; exposed only as U+20B9 | SIL OFL 1.1 | Exact v3.2.1.08 continuation Latin-extended payload; alias `NyayOne S20 Rupee` in S-20 listing metadata only |
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

The S-20 rupee supplement is 18,372 bytes, SHA-256
`1c8a26c0ed4312dacc36670714794c9f4b4a0972ccb45f2936646bd8d444d5f8`.
It is extracted byte-for-byte from the `src-cont` Public Sans 400 Latin-extended
face in the frozen v3.2.1.08 canonical ZIP (SHA-256
`0476ec549b3776cc33af52692f71a4029404443f4f02f5b0485b02d5f38cf964`).
The binary is not subsetted or otherwise edited. Its isolated CSS face exposes
only `U+20B9` (₹); its alias is used only by `.s20-meta`. Existing global faces,
font assets, other-screen stacks and reference images remain unchanged.
The supplement lives below `fonts/s20/` so the original top-level calibration
font-pin set remains exact. It is still covered by NYAY-66's recursive protected
bundle inventory; the new bytes require owner integrity approval.

**Still deferred:** `JetBrainsMono-Variable.woff2` (`--font-mono` outside the
law-school scope falls back to the system mono stack until it is added).
