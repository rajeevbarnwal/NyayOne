// Test-only exact proposals. These pins never authorize runtime exceptions.
import {withoutS32ProposalsForTest,withoutS32PolicyBytesForTest} from './nyay66-s32-exceptions.test-fixture.mjs';
import {approveException} from './nyay66-enforcement.mjs';
import {normalizeS31Page2ForTest,normalizeS31Page2PolicyBytesForTest} from './nyay66-s31-page2-reapproval.test-fixture.mjs';
export const s31Proposals=[
  {
    "screen": "S-31",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "2fbc6455d035d3404a51a10a39f4de6d9930a82e3da0dc24f1ec2814f283dba3",
    "liveSha256": "b7227c9c52d290cf713f1fa29c0a1af74ecc26d2ef8eae26b1f0fc4b6e445790",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-31 loading, mobile390, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The genuine GET remains pending until context disposal. Loading is announced by the status accessible name rather than the prototype hidden-text inventory; no successful response/count/data is fabricated. Matched DOM-control geometry disclosure (live minus frozen): sessions action: y -20.9219px; search field: y -20.9219px; Subject field: y -20.9219px; Level field: y -20.9219px. The shorter consistent introduction removes one 20.921875px line on mobile, moving subsequent content upward by that amount; any count/code-line offset is additional as disclosed above. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "eab3463bc47b06527baad06f617c1553e87c90e03f344060fa801e4888c02c18",
    "liveSha256": "670b51b12c0a16058b6002e105200ace47698b80f6e150518749f8531f192f63",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-31 loading, desktop, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Desktop retains functional 48px Home/Profile navigation buttons where the prototype has static labels and a semantic h2 for the visible aside title; these add control/heading inventory entries without moving the corresponding visible boxes. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The genuine GET remains pending until context disposal. Loading is announced by the status accessible name rather than the prototype hidden-text inventory; no successful response/count/data is fabricated. Matched DOM-control geometry disclosure (live minus frozen): the paired visible controls retain identical boxes. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "05868a13f5af9821f7855a7ea158d6750fe120a0decb431a1ee2630b3c12a3aa",
    "liveSha256": "11c5d6598400078e12436cf532e931b38ab184755d81f8d9f5312895c42a48b4",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-31 results, mobile390, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Server-shaped results are sorted before pagination: page 1 is Meera/Kavya/Rohan instead of the prototype Meera/Rohan/Farhan order. Cards retain real full-name detail links to /s-32?tutor={id}, server verification flags, decimal rating strings (4.80/4.70/4.60), prices and initials derived from the first two display-name words (AM/AK rather than MK/KM). The summary uses \"highest rated\" and the same confirmed total/page. Names/headlines differ by returned row; mobile third-card height reflects Rohan's wrapping instead of Farhan's. Previous/Next accessible names add \"page\" and real disabled states remain truthful. Matched DOM-control geometry disclosure (live minus frozen): the paired visible controls retain identical boxes. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "c68c617c9924e70be09b8527f82d606d958d78e5ce361ea8f4f5c7c27a16cf6e",
    "liveSha256": "f4ce2212c9f0fb740c3369041994485eb170396c4010f2fe26bec38cde4b6618",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-31 results, desktop, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Desktop retains functional 48px Home/Profile navigation buttons where the prototype has static labels and a semantic h2 for the visible aside title; these add control/heading inventory entries without moving the corresponding visible boxes. Server-shaped results are sorted before pagination: page 1 is Meera/Kavya/Rohan instead of the prototype Meera/Rohan/Farhan order. Cards retain real full-name detail links to /s-32?tutor={id}, server verification flags, decimal rating strings (4.80/4.70/4.60), prices and initials derived from the first two display-name words (AM/AK rather than MK/KM). The summary uses \"highest rated\" and the same confirmed total/page. Names/headlines differ by returned row; mobile third-card height reflects Rohan's wrapping instead of Farhan's. Previous/Next accessible names add \"page\" and real disabled states remain truthful. Matched DOM-control geometry disclosure (live minus frozen): the paired visible controls retain identical boxes. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "8712c4ee8e6bec9246b611a024ed3feb67e745acedbd54c932dd6fe4d1e898e7",
    "liveSha256": "052e35d3bd9f85749e886dbd0e2e45278fd0634e1a507d06a3dbf2edac592636",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-31 filters-open, mobile390, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The actual Subject query is Arbitration. Its synthetic server reply contains two matching records, not the prototype's inconsistent \"3 mentors\" label with five cards. Show the confirmed total, page 1 of 1, supported six sort choices, decimal ratings, server verification flags and derived initials, plus truthful disabled pagination. Subject/Level use free text instead of prototype enum choices. The checkbox helper is an accessible description rather than concatenated label text. Card/detail-link identity and returned data change the lower composition; no client-side invention of server capabilities is approved. Matched DOM-control geometry disclosure (live minus frozen): sessions action: y -20.9219px; search field: y -20.9219px; Subject field: y -20.9219px; Level field: y -20.9219px. The shorter consistent introduction removes one 20.921875px line on mobile, moving subsequent content upward by that amount; any count/code-line offset is additional as disclosed above. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "7049ee664b45bb917ac596706cc611c9a1bb71003f74aae8f605ed12a3a44858",
    "liveSha256": "f290dc83e5786c1abdfd64aed12c8cc861a97f695e42da804c28dbe2aa6b86e9",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-31 filters-open, desktop, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Desktop retains functional 48px Home/Profile navigation buttons where the prototype has static labels and a semantic h2 for the visible aside title; these add control/heading inventory entries without moving the corresponding visible boxes. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The actual Subject query is Arbitration. Its synthetic server reply contains two matching records, not the prototype's inconsistent \"3 mentors\" label with five cards. Show the confirmed total, page 1 of 1, supported six sort choices, decimal ratings, server verification flags and derived initials, plus truthful disabled pagination. Subject/Level use free text instead of prototype enum choices. The checkbox helper is an accessible description rather than concatenated label text. Card/detail-link identity and returned data change the lower composition; no client-side invention of server capabilities is approved. Matched DOM-control geometry disclosure (live minus frozen): the paired visible controls retain identical boxes. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "57f35c8ebb3f9ebb7529f58ef8ebc0cc90b43f2d86849e96fd74e4c0bc0eeb45",
    "liveSha256": "76f3a2b0b0c1ed1ea5861c3116a0a5c36610b67e7e65a54b989edbdc452ed4d7",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-31 no-matches, mobile390, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. Explicit interaction-state variant: retain query \"no-synthetic-match\", the 1-active filter summary, confirmed zero count/page 1 of 1, and disabled Previous/Next controls. The frozen variant omits this query/count/pager context. Clear filters remains a real reset action. Matched DOM-control geometry disclosure (live minus frozen): sessions action: y -20.9219px; search field: y -20.9219px; Subject field: y -20.9219px; Level field: y -20.9219px; Clear filters: y +11.4531px. The shorter consistent introduction removes one 20.921875px line on mobile, moving subsequent content upward by that amount; any count/code-line offset is additional as disclosed above. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "a2d3447ad75f9242be784a919cb3f631917cec9ac74f0d1c0fa5ecab7abbd4f3",
    "liveSha256": "ad03c6aafe9a676dc125aa8f03b606ef9058369b9c942fa4a77ad25a89a6a389",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-31 no-matches, desktop, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Desktop retains functional 48px Home/Profile navigation buttons where the prototype has static labels and a semantic h2 for the visible aside title; these add control/heading inventory entries without moving the corresponding visible boxes. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. Explicit interaction-state variant: retain query \"no-synthetic-match\", the 1-active filter summary, confirmed zero count/page 1 of 1, and disabled Previous/Next controls. The frozen variant omits this query/count/pager context. Clear filters remains a real reset action. Matched DOM-control geometry disclosure (live minus frozen): Clear filters: y +32.375px. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "295e39d744d094e9ca644104cd3012b5970ae2564574133cc43a3831bb44eac7",
    "liveSha256": "8629402443e8aed145e2ef534074026ba5c53c02c617d25837cd029caeddde82",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-31 rate-limited, mobile390, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The API genuinely replies HTTP 429 with rate_limit_exceeded. The real one-second retry interval expires without an automatic GET or frozen clock; the captured Try again is then available. Retain the truthful HTTP/code line and a semantic h2 where the prototype used compact bold text. The error notice has a meaningful 3px focus outline with 3px offset. The added code line moves the action down 16.5px within the notice. Matched DOM-control geometry disclosure (live minus frozen): sessions action: y -20.9219px; search field: y -20.9219px; Subject field: y -20.9219px; Level field: y -20.9219px; Try again: y -4.42188px. The shorter consistent introduction removes one 20.921875px line on mobile, moving subsequent content upward by that amount; any count/code-line offset is additional as disclosed above. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "085bc0638810591e83d597a2ac27b35224597513cc372b46aaa2938e692ad96f",
    "liveSha256": "d79903cf2ade85d75cce26da66ecab99d231b1f2551df966a319400e1f7e7a6b",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-31 rate-limited, desktop, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Desktop retains functional 48px Home/Profile navigation buttons where the prototype has static labels and a semantic h2 for the visible aside title; these add control/heading inventory entries without moving the corresponding visible boxes. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The API genuinely replies HTTP 429 with rate_limit_exceeded. The real one-second retry interval expires without an automatic GET or frozen clock; the captured Try again is then available. Retain the truthful HTTP/code line and a semantic h2 where the prototype used compact bold text. The error notice has a meaningful 3px focus outline with 3px offset. The added code line moves the action down 16.5px within the notice. Matched DOM-control geometry disclosure (live minus frozen): Try again: y +16.5px. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "aa5da5043326e4faa78ebfe074b1c7454bed9935c938b56bf6d9953c673bf898",
    "liveSha256": "9a5e3018821adbe2dcb3b8490ff402e23826daba2e49232935454ad9dfaec6b0",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-31 error, mobile390, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The API genuinely replies HTTP 500. The error copy and Retry action are retained, with a meaningful 3px focus outline and 3px offset around the error notice rather than an unfocused prototype card. Matched DOM-control geometry disclosure (live minus frozen): sessions action: y -20.9219px; search field: y -20.9219px; Subject field: y -20.9219px; Level field: y -20.9219px; Retry: y -20.9219px. The shorter consistent introduction removes one 20.921875px line on mobile, moving subsequent content upward by that amount; any count/code-line offset is additional as disclosed above. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "2c728e1617ef50183af5dae7da3a7b736c60d3bf2b4fa676390f1ced4edc2ff0",
    "liveSha256": "1403d949253ce6cbddd1175e936045c03063bfa2a1c73a13e229abe1d369ce9c",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-31 error, desktop, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Desktop retains functional 48px Home/Profile navigation buttons where the prototype has static labels and a semantic h2 for the visible aside title; these add control/heading inventory entries without moving the corresponding visible boxes. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The API genuinely replies HTTP 500. The error copy and Retry action are retained, with a meaningful 3px focus outline and 3px offset around the error notice rather than an unfocused prototype card. Matched DOM-control geometry disclosure (live minus frozen): the paired visible controls retain identical boxes. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "7a83e5765a72c00e3debbf5a436d23a37cd2752a8236f9574184c88e241303d3",
    "liveSha256": "fb77545740469dc2b654855a92ed4aa4461b5096ac3db03c57aefae701eb1210",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-31 offline, mobile390, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The browser is genuinely offline before mentor discovery; no tutor GET is sent. Retain truthful \"No request was sent. Reconnect and retry.\" instead of \"Mentor search needs a connection.\" and omit the redundant \"No connection\" line. This reduces the retry position by 24px within the card. The alert has a meaningful 3px focus outline with 3px offset. Playwright disables the HTTP cache, so this fixture explicitly replays only previously fetched unchanged logo bytes at the same URL; it does not fake online status or API success. Matched DOM-control geometry disclosure (live minus frozen): sessions action: y -20.9219px; search field: y -20.9219px; Subject field: y -20.9219px; Level field: y -20.9219px; Retry: y -44.9219px. The shorter consistent introduction removes one 20.921875px line on mobile, moving subsequent content upward by that amount; any count/code-line offset is additional as disclosed above. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "09e8487a4ee9dccf8353f088a7d06efff0b5c983c8cefbcd18d218c32a7f6e00",
    "liveSha256": "b398baa82d88444ea3eecf86e6f77db10095cc4536584e6eb8430c0f5dfb598e",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-31 offline, desktop, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Desktop retains functional 48px Home/Profile navigation buttons where the prototype has static labels and a semantic h2 for the visible aside title; these add control/heading inventory entries without moving the corresponding visible boxes. Explicit owner-authorized design variant: use the results-page introduction consistently across loading/filter/empty/error states, instead of the longer variant introduction. The browser is genuinely offline before mentor discovery; no tutor GET is sent. Retain truthful \"No request was sent. Reconnect and retry.\" instead of \"Mentor search needs a connection.\" and omit the redundant \"No connection\" line. This reduces the retry position by 24px within the card. The alert has a meaningful 3px focus outline with 3px offset. Playwright disables the HTTP cache, so this fixture explicitly replays only previously fetched unchanged logo bytes at the same URL; it does not fake online status or API success. Matched DOM-control geometry disclosure (live minus frozen): Retry: y -24px. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "045e6be0a49e52f47befacfc73721ad33766063ffbf4f3b9ae68c4ec0497ab86",
    "liveSha256": "911dffc85653f977298decf9dd5fecb27d3e184c4827ab2ad869537ec8c53538",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-31 page-2, mobile390, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. The real Next action requests offset 3; server-shaped records are sorted before pagination, so page 2 is Farhan/Sneha instead of prototype Kavya/Sneha. Preserve server names/headlines, prices, null ratings and false verification flags, derived AF initials, grammatical \"1 year\", and confirmed total/page. Detail actions are real full-name links; Previous/Next accessible names add \"page\". Keyboard focus on the result summary adds the meaningful visible outline after navigation. Matched DOM-control geometry disclosure (live minus frozen): the paired visible controls retain identical boxes. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  },
  {
    "screen": "S-31",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "df97102363b15c6482ad2e54834a5e27896d8aae355a647b85f1652071526064",
    "liveSha256": "b8ad690b29d337045a9803b728a343bfa229738d61bc44cf9aab0c7bbfb3fe74",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-31 page-2, desktop, light. Exact hosted live-route capture with synthetic API replies at d5b015e0ae80c2d506b3465ad98f5397b208f5b4 (run 41809140046); not live-backend or independent Senior QA evidence. Identity/navigation: a generic person avatar and accessible name \"Your Profile\" replace prototype AN/Aditi Nair. My sessions is a real /s-35 link. Explicit owner-authorized design/interaction variants: retain the visible 48px Search submit button in the search field and backend-supported free-text Subject/Level inputs, rather than inventing closed server enums from the prototype selects. The sort menu offers the supported server sorts and clear labels, including ascending rating/experience. These disclosure controls remain in the DOM when collapsed; their roles/options alter inventories without making hidden controls visible. Desktop retains functional 48px Home/Profile navigation buttons where the prototype has static labels and a semantic h2 for the visible aside title; these add control/heading inventory entries without moving the corresponding visible boxes. The real Next action requests offset 3; server-shaped records are sorted before pagination, so page 2 is Farhan/Sneha instead of prototype Kavya/Sneha. Preserve server names/headlines, prices, null ratings and false verification flags, derived AF initials, grammatical \"1 year\", and confirmed total/page. Detail actions are real full-name links; Previous/Next accessible names add \"page\". Keyboard focus on the result summary adds the meaningful visible outline after navigation. Matched DOM-control geometry disclosure (live minus frozen): the paired visible controls retain identical boxes. The filter inset, checkbox styling, Clear filters icon, compact rate-limit styling, My sessions/Try again icon baselines, and mentor-name underline were corrected in code. No residual icon-baseline waiver is proposed. Exact image pair only: no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 90
  }
];
export const s31ProposalHashes=[
  "6a6fbcc044e5e60384e1d1c2d498e9b05709de65d8bbba173fb5986aa10c5f90",
  "9344e0b3bf1e62d6fe8e6d11bc7ef1b9580d72c80a628320909e08c81dd680dd",
  "f68736b32d9efdc4cbd06d63970959047f02b635affcb1d0bc162c588e4f54db",
  "986198ca7596d9751a601f91c9048b77468e1c6d80db9191dd38a7a47096ef84",
  "13ac58e36aeb736c5fd8b95be26cc2354cf4bf6dbd9e14766b9c3785b2611478",
  "bba1afd23c07c00c2df7a3e6735cd877c44685917652c5b5ab6447832803b1bf",
  "2a7d0a3836f93d2bb3c98abe7ade1a664ef4d678a1246fb28a0cbae0c41946da",
  "1704363210d8ea6ca3ea69ae42da62e2f2ce9f27a0c18b301ed42399ee958946",
  "5c1f7ec2e41928608e453f7d50741191bd020fcc67ced429f4146a1a3b1202a4",
  "9d95b5c030bf42ec07b163a5cde789d63ff83f33ae259ff9bcf4f7456063b8cd",
  "73ef7211373c7bd3204df04a0c7aecc0b04c42b35f3e27f760d5143b4cfa9ce3",
  "d2299038095ec81558404b0d057ac1a0d689d3fe9b149f10c439fa452074de51",
  "98a92e4f9cfd90cbba8457233b58cda3bf764160c5078201d69a427f520c3944",
  "67dcb73fa4d2a97975397f26d41a61c71dea187d935fa5cabde415c6ce111743",
  "9c5e2662bb9ffe99b366bf48237ee41cc7b6932bdbba23444a856b8da39be985",
  "478d3f2dbfabda814bc8f357803777519842483c35a5a0772010f79302092342"
];
for(const [i,e] of s31Proposals.entries())if(approveException(e,null,{s31:true})!==s31ProposalHashes[i])throw Error('S31_PROPOSAL_PIN_MISMATCH');
export function withoutS31ProposalsForTest(exceptions){
 exceptions=withoutS32ProposalsForTest(exceptions);
 const additions=exceptions.filter(e=>e.screen==='S-31');
 if(additions.length){
  const keys=Object.keys(s31Proposals[0]).sort().join(',');
  if(additions.length!==16||additions.some(e=>Object.keys(e).sort().join(',')!==keys))throw Error('S31_PROPOSAL_INVENTORY_CHANGED');
  if(JSON.stringify(normalizeS31Page2ForTest(additions).map(e=>approveException(e,null,{s31:true})))!==JSON.stringify(s31ProposalHashes))throw Error('S31_PROPOSAL_CONTENT_CHANGED');
  if(exceptions.slice(-16).some((e,i)=>e!==additions[i]))throw Error('S31_PROPOSAL_APPEND_ORDER_CHANGED');
 }
 // Only this exact appended set is removed from historical test snapshots.
 return exceptions.filter(e=>e.screen!=='S-31');
}
export function withoutS31PolicyBytesForTest(bytes){
 bytes=withoutS32PolicyBytesForTest(bytes);
 const policy=JSON.parse(bytes);withoutS31ProposalsForTest(policy.exceptions);
 if(!policy.exceptions.some(e=>e.screen==='S-31'))return bytes;
 bytes=normalizeS31Page2PolicyBytesForTest(bytes);
 const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    ');
 const suffix=',\n'+s31Proposals.map(record).join(',\n');
 if(bytes.split(suffix).length!==2||!bytes.endsWith(suffix+'\n  ]\n}\n'))throw Error('S31_PROPOSAL_BYTES_CHANGED');
 return bytes.replace(suffix,'');
}
