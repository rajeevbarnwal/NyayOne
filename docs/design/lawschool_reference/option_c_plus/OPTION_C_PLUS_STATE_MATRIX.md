# Option C+ — State Matrix (48 states)

**Artifact:** `OPTION_C_PLUS_GUIDED_CONFIDENCE.html` · every state reachable via **Reviewer → All 48 states**, via product interaction, and (where applicable) by URL. Harness walks all 48 programmatically (`window.__opt.apply(id)`).

| # | State ID | Screen | State | C+ note |
|---|---|---|---|---|
| 1 | `s27-default` | S-27 | Initial / default (12 results) | — |
| 2 | `s27-search` | S-27 | Search result | — |
| 3 | `s27-filtered` | S-27 | Filtered result | — |
| 4 | `s27-sorted` | S-27 | Sorted + selected-sort indication | — |
| 5 | `s27-page` | S-27 | Pagination (page 2) | — |
| 6 | `s27-empty` | S-27 | Empty result | — |
| 7 | `s27-loading` | S-27 | Loading / skeleton | — |
| 8 | `s27-validation` | S-27 | Typed validation error | — |
| 9 | `s27-fail` | S-27 | Provider failure + Retry | — |
| 10 | `s27-tray0` | S-27 | Comparison tray · 0 selected | Step-3 tray visible in empty state (in-flow sticky band, “0 of 4”) |
| 11 | `s27-tray1` | S-27 | Comparison tray · 1 selected | tray “1 of 4 · pick 1 more” |
| 12 | `s27-tray2` | S-27 | Comparison tray · 2 selected | Compare CTA enabled (config min 2) |
| 13 | `s27-tray4` | S-27 | Comparison tray · 4 selected | tray full (config max 4) |
| 14 | `s27-refusal` | S-27 | Fifth-school refusal (typed error) | typed COMPARE_LIMIT_EXCEEDED dialog · no mutation |
| 15 | `s27-dup` | S-27 | Duplicate-school feedback | — |
| 16 | `s27-url` | S-27 | Refreshed URL-state restoration | — |
| 17 | `s28-detail` | S-28 | Full verified detail | — |
| 18 | `s28-loading` | S-28 | Loading | — |
| 19 | `s28-missing` | S-28 | Missing ID | — |
| 20 | `s28-unknown` | S-28 | Unknown school | — |
| 21 | `s28-zero` | S-28 | Zero facts | — |
| 22 | `s28-saved` | S-28 | Save → Saved | — |
| 23 | `s28-follow` | S-28 | Follow → Following | mandated follow copy shown |
| 24 | `s28-signedout` | S-28 | Signed-out action | — |
| 25 | `s28-forbidden` | S-28 | Wrong-role / forbidden | — |
| 26 | `s28-fail` | S-28 | Fetch failure + Retry | — |
| 27 | `s28-restored` | S-28 | Refresh with state restored | — |
| 28 | `s29-2` | S-29 | Compare 2 | — |
| 29 | `s29-4` | S-29 | Compare 4 | — |
| 30 | `s29-min` | S-29 | Below-minimum | — |
| 31 | `s29-dup` | S-29 | Duplicate blocked | — |
| 32 | `s29-refusal` | S-29 | Fifth-school refusal | — |
| 33 | `s29-loading` | S-29 | Loading | — |
| 34 | `s29-fail` | S-29 | Commit failure · no partial result | — |
| 35 | `s29-anon` | S-29 | Anonymous / sign-in | — |
| 36 | `s29-url` | S-29 | URL refresh / replay | — |
| 37 | `s29-narrow` | S-29 | Narrow-screen comparison | stacked fact cards — zero horizontal scroll by design |
| 38 | `s30-both` | S-30 | Saved + followed populated | — |
| 39 | `s30-saved` | S-30 | Saved only | — |
| 40 | `s30-followed` | S-30 | Followed only | teal Following identity |
| 41 | `s30-empty` | S-30 | Both empty | — |
| 42 | `s30-loading` | S-30 | Loading | — |
| 43 | `s30-fail` | S-30 | List-fetch failure + Retry | — |
| 44 | `s30-signedout` | S-30 | Signed-out | — |
| 45 | `s30-forbidden` | S-30 | Wrong-role / forbidden | — |
| 46 | `s30-removing` | S-30 | Unsave / unfollow in progress | — |
| 47 | `s30-idempotent` | S-30 | Idempotent empty after removal | — |
| 48 | `s30-restored` | S-30 | Refreshed / restored session | — |

All 48 IDs statically verified present in the shipped artifact; live render walk is a harness check (see Closure Report execution ledger).
