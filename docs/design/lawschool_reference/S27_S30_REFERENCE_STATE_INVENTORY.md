# S-27..S-30 Law-School Directory — Reference-State Inventory

**Status: PROPOSED-PENDING-PRODUCT-APPROVAL** (SAATHI-121)
Date: 2026-07-27 · Author: Senior Engineer (Wave 1 closure)

## Why this file exists (and why there are no reference PNGs)

SAATHI-121 requires a visual-parity baseline for the S5 law-school directory
(S-27 search, S-28 detail, S-29 compare, S-30 saved/followed — canonical scope
per screen map v3.2; the older S-33/S-34/S-35 numbering is superseded).
An exhaustive sweep of every approved Option J design HTML found **zero
approved S-27..S-30 visual designs** (details in the Wave-1 lifecycle decision
record). Per the no-invented-baseline rule, engineering must not fabricate a
visual reference. This inventory therefore **proposes** the deterministic state
matrix a reference set must cover, for Product to approve (or replace with an
approved design source). **No reference PNGs are committed because no approved
source exists.** Once Product approves a source, reference captures are
generated from it and recorded in the manifest schema below.

## Deterministic fixtures

Seeded by `backend/app/services/law_school_service.seed_law_schools`
(deterministic, idempotent — no live provider):

| Fixture | Definition |
|---|---|
| `catalog-4` | Full seed: `nlsiu-bengaluru`, `nalsar-hyderabad`, `wbnujs-kolkata`, `nlu-delhi` |
| `compare-2` | `nlsiu-bengaluru`, `nalsar-hyderabad` |
| `compare-4` | `nlsiu-bengaluru`, `nalsar-hyderabad`, `wbnujs-kolkata`, `nlu-delhi` |
| `compare-5-refused` | `compare-4` + one syntactically valid unknown UUID (typed `COMPARE_LIMIT_EXCEEDED`) |
| `student-a` | Dev claims `sub 00000000-0000-4000-8000-0000000000de`, role `student` |
| `anonymous` | No actor claims (401 path) |

## State inventory (each state × screen = one reference capture per viewport × theme)

Status of every row: **PROPOSED-PENDING-PRODUCT-APPROVAL.**

| Screen | loading | empty | validation | conflict | retry-provider-failure | forbidden | success | refresh |
|---|---|---|---|---|---|---|---|---|
| S-27 Search & filter | Query pending ("Loading law schools…") | `q=zz-no-such-school` → "No schools match" + hint | Unsupported sort/institution-type → typed 422 surfaced | Compare tray at limit: add-fifth blocked with typed message | API 5xx/unreachable → ErrorState with Retry, retry succeeds | n/a (public read) | `catalog-4` results with filters/sort/pagination | URL params (`q,state,sort,page`) survive reload |
| S-28 Detail | "Loading school…" | Unknown id → "School not found"; zero facts → "No facts published yet" | Missing `id` param → "No school selected" | Save/follow while signed out → sign-in prompt (401 mapped) | Detail fetch failure → ErrorState with Retry | Non-student role on save/follow → 403 typed | Full detail: facts + source + retrieved-at, Save/Follow toggles (`student-a`) | Saved ✓ / Following ✓ persist across reload |
| S-29 Compare | "Building comparison…" | Under-min selection (0–1 id) → "Select at least 2" | Duplicate ids → deduped/typed `DUPLICATE_SCHOOL`; `compare-5-refused` → "at most 4" | Two parallel compare submissions: valid 200 + over-limit typed 422, no partial mutation | Compare POST failure → ErrorState with Retry, atomic (no partial comparison rows) | `anonymous` → sign-in prompt | `compare-2` and `compare-4` aligned tables | `ids` in URL replay the comparison on reload |
| S-30 Saved & followed | Both lists "Loading …" | "No saved schools yet" / "No followed schools yet" + hints | n/a (no free input) | Unsave/unfollow raced with another session → idempotent no-op | List fetch failure → ErrorState with Retry | `anonymous` → sign-in prompt; non-student → 403 | `student-a` with saved+followed `nlsiu-bengaluru` | Lists re-fetch and match server state after reload |

Viewport × theme matrix per capture: 390 / 430 / 768 / 1024 / 1440 × light / dark.

## Reference-capture manifest schema (to be populated only after Product approval)

Each approved reference capture gets one manifest entry:

```json
{
  "screen": "S-27",
  "state": "empty",
  "source": "<approved design file path or URL — Product-designated>",
  "checksum": "sha256:<hex of the source file at approval time>",
  "viewport": "390x844",
  "theme": "dark",
  "fixture": "catalog-4",
  "dynamic-exclusions": ["retrieved-at timestamps", "comparison_id", "request ids", "focus rings under automation"]
}
```

- `source` must point to a Product-approved artefact; engineering-invented
  captures are not acceptable sources.
- `checksum` pins the approved source so later edits require re-approval.
- `dynamic-exclusions` lists regions/values masked during pixel comparison.

## Gate

Visual-parity for SAATHI-121 stays **blocked** until Product either approves
this proposed inventory (and designates the reference source) or supplies
approved S-27..S-30 designs. Functional/behavioural coverage is independently
automated in `frontend/scripts/lawschool-e2e.mjs` (SAATHI-120).
