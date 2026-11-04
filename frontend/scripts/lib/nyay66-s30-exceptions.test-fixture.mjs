import {withoutS31ProposalsForTest,withoutS31PolicyBytesForTest} from './nyay66-s31-exceptions.test-fixture.mjs';
// Test-only exact proposals. These pins never authorize runtime exceptions.
import {approveException} from './nyay66-enforcement.mjs';
export const s30Proposals=[
  {
    "screen": "S-30",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "23d66ad669d8756b75e7412cfeb7b0cd72a2b8c27ace2d592a913ebcb974a07e",
    "liveSha256": "fac94bb60e9dc8a46724e5d0dc3eb482bc0900d5c78ab98ef2b2cedd4c7686fd",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-30 loading, mobile390, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Both genuine list GETs remain pending at capture: tab counts display an ellipsis rather than the prototype 2/2, and Compare is disabled until a saved-list response confirms eligibility. The accessible loading status/skeleton does not claim success or confirmed membership. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "6f72ce9d760d02d90763add5a978cf9e2205b8a92cce0d1e5d8be8ea9a3c61bb",
    "liveSha256": "bf9cdc44265a2ad75a09c89b6f2452ca44bbca176ca656001823c1b40ad0cefd",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-30 loading, desktop, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. Desktop retains functional 48px Home/Profile buttons instead of static labels and a semantic h2 for the visible Compare saved schools aside. These extra control/heading entries change inventories, not their visible positions. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Both genuine list GETs remain pending at capture: tab counts display an ellipsis rather than the prototype 2/2, and Compare is disabled until a saved-list response confirms eligibility. The accessible loading status/skeleton does not claim success or confirmed membership. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "39c19f9df857c89d8a5d292782e91c758637f5f34108155f1ab264a84f2353bb",
    "liveSha256": "fb6b6b64344db170d6b23c9ac762dc432a9df2fe6849a33b9e9c2ccb878737a7",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-30 both, mobile390, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Saved and Following are independent server-confirmed memberships: the synthetic Saved response contains Kaveri and Sabarmati, while Following contains Kaveri and Vindhya; the frozen example has Vindhya saved and Sabarmati followed. The Kaveri institution type includes server-provided state-established, which can wrap on mobile. Different institution names, locations, fees and entrance-exam values are rendered from those responses, not replaced with prototype values. Both list GETs have succeeded with counts 2/2; membership controls reflect those separate confirmed responses. Residual control/slot geometry (live minus frozen, CSS px; slots compare corresponding card positions even where institution identities differ): School-detail slot 1 [height=7.84375]; School-detail slot 2 [y=7.84375]; Remove/Unfollow school slot 2 [y=7.84375]. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "7e165340a4aa52a222107106e4725a25f3fa1492321f495f153d7bc0f4aa0f4a",
    "liveSha256": "137df684891bedcd53cf33d9e628c44a85fee054a2b36111fc50ab8f18120e98",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-30 both, desktop, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. Desktop retains functional 48px Home/Profile buttons instead of static labels and a semantic h2 for the visible Compare saved schools aside. These extra control/heading entries change inventories, not their visible positions. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Saved and Following are independent server-confirmed memberships: the synthetic Saved response contains Kaveri and Sabarmati, while Following contains Kaveri and Vindhya; the frozen example has Vindhya saved and Sabarmati followed. The Kaveri institution type includes server-provided state-established, which can wrap on mobile. Different institution names, locations, fees and entrance-exam values are rendered from those responses, not replaced with prototype values. Both list GETs have succeeded with counts 2/2; membership controls reflect those separate confirmed responses. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "82f87541a1a108dadf87b6da42f33efe682ad986ebfa83b5e01293e76495ad8a",
    "liveSha256": "089ec6b7ef4a033b965dbbb4a7689c3bd0bf7e7342c788114ff26d5bbc5f6e2b",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-30 following-tab, mobile390, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Saved and Following are independent server-confirmed memberships: the synthetic Saved response contains Kaveri and Sabarmati, while Following contains Kaveri and Vindhya; the frozen example has Vindhya saved and Sabarmati followed. The Kaveri institution type includes server-provided state-established, which can wrap on mobile. Different institution names, locations, fees and entrance-exam values are rendered from those responses, not replaced with prototype values. Kaveri notification consent is on and Vindhya is off. Vindhya has null fee/exam values, shown as Fees not provided / Entrance exam not provided, not fabricated zeros or facts. The Following tab is selected and receives focus after activation. Residual control/slot geometry (live minus frozen, CSS px; slots compare corresponding card positions even where institution identities differ): School-detail slot 1 [height=7.84375]; School-detail slot 2 [y=7.84375]; Remove/Unfollow school slot 2 [y=7.84375]. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "b319a63c02e597e326c3dc03590316b2b2444022e2b0b6711ce9dade0750ff61",
    "liveSha256": "78008f56261b9b555f5ea3620fba8fe8ef346c06a90836bd10cd760583e6514e",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-30 following-tab, desktop, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. Desktop retains functional 48px Home/Profile buttons instead of static labels and a semantic h2 for the visible Compare saved schools aside. These extra control/heading entries change inventories, not their visible positions. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Saved and Following are independent server-confirmed memberships: the synthetic Saved response contains Kaveri and Sabarmati, while Following contains Kaveri and Vindhya; the frozen example has Vindhya saved and Sabarmati followed. The Kaveri institution type includes server-provided state-established, which can wrap on mobile. Different institution names, locations, fees and entrance-exam values are rendered from those responses, not replaced with prototype values. Kaveri notification consent is on and Vindhya is off. Vindhya has null fee/exam values, shown as Fees not provided / Entrance exam not provided, not fabricated zeros or facts. The Following tab is selected and receives focus after activation. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "0d0a4856491c33eb769082625deba42f527b54817f4342fea726e5b7cb5409ba",
    "liveSha256": "f57fb6637d96960caef36563a8e1546b6aba4dd06059c92b171bb1aa3640fe7c",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-30 saved-empty, mobile390, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. The successful Saved response confirms zero items while Following confirms two. The redundant mobile Compare row has been removed in code to match the frozen empty composition; desktop retains its disabled Compare control. No failed or pending response is presented as empty. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "c84cf43a5fe11331f88a739f5fd1fbb2250762d3100c4542c8d0c9809d376fa7",
    "liveSha256": "ff7dafe8038a0001fb546437770ade73cd1200688b447359d4c41e6e7deeb4fd",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-30 saved-empty, desktop, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. Desktop retains functional 48px Home/Profile buttons instead of static labels and a semantic h2 for the visible Compare saved schools aside. These extra control/heading entries change inventories, not their visible positions. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. The successful Saved response confirms zero items while Following confirms two. The redundant mobile Compare row has been removed in code to match the frozen empty composition; desktop retains its disabled Compare control. No failed or pending response is presented as empty. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "19651a5a910ad7a45b7ef299569f5ba376a2e62ae1bebe2612d10165f614b512",
    "liveSha256": "caab6d79ca1c88ad66e35f1c3a6a4c4b50e6b2194923060977434d1ab514bf15",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-30 followed-empty, mobile390, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. The successful Following response confirms zero items while Saved confirms two; Compare remains available for the confirmed saved pair. The Following tab is selected and receives focus after activation. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "7df33a3a9b42ce6f7e88b9ae6fb479dc60a0fc6a5063148ce2778a3f1449f5cb",
    "liveSha256": "bd89e649677fbfd05653cfb6937657af1706bef9914058f07a3263aff4db225f",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-30 followed-empty, desktop, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. Desktop retains functional 48px Home/Profile buttons instead of static labels and a semantic h2 for the visible Compare saved schools aside. These extra control/heading entries change inventories, not their visible positions. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. The successful Following response confirms zero items while Saved confirms two; Compare remains available for the confirmed saved pair. The Following tab is selected and receives focus after activation. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "84149f98d9330ad31ababebb42cbdcc9501840b1c7f3c4c5e5a21dd4af8f7a95",
    "liveSha256": "54728c76c1b76be2b60b072a7dc571175d0f4064609e9b0576c5cc1cd05506db",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-30 item-pending, mobile390, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Saved and Following are independent server-confirmed memberships: the synthetic Saved response contains Kaveri and Sabarmati, while Following contains Kaveri and Vindhya; the frozen example has Vindhya saved and Sabarmati followed. The Kaveri institution type includes server-provided state-established, which can wrap on mobile. Different institution names, locations, fees and entrance-exam values are rendered from those responses, not replaced with prototype values. A genuine DELETE remains pending at capture. Last-confirmed 2/2 counts and list cards stay visible, with no optimistic removal or success. The implementation locks both Remove controls and Compare while this write owns the action lock; the frozen example disables only the first Remove. aria-disabled retains meaningful focus on the initiating Remove control. Its visible focus treatment is an explicitly disclosed interaction-state difference, never a focus-loss waiver. Residual control/slot geometry (live minus frozen, CSS px; slots compare corresponding card positions even where institution identities differ): School-detail slot 1 [height=7.84375]; School-detail slot 2 [y=7.84375]; Remove/Unfollow school slot 2 [y=7.84375]. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "c4dcff6df30d70353f93709c78e908474f5636420a67e416ca7522aa72883851",
    "liveSha256": "8b167bfcdde451086b2e98929b4945d7c122dd65b0a678137294b43919c762a2",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-30 item-pending, desktop, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. Desktop retains functional 48px Home/Profile buttons instead of static labels and a semantic h2 for the visible Compare saved schools aside. These extra control/heading entries change inventories, not their visible positions. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Saved and Following are independent server-confirmed memberships: the synthetic Saved response contains Kaveri and Sabarmati, while Following contains Kaveri and Vindhya; the frozen example has Vindhya saved and Sabarmati followed. The Kaveri institution type includes server-provided state-established, which can wrap on mobile. Different institution names, locations, fees and entrance-exam values are rendered from those responses, not replaced with prototype values. A genuine DELETE remains pending at capture. Last-confirmed 2/2 counts and list cards stay visible, with no optimistic removal or success. The implementation locks both Remove controls and Compare while this write owns the action lock; the frozen example disables only the first Remove. aria-disabled retains meaningful focus on the initiating Remove control. Its visible focus treatment is an explicitly disclosed interaction-state difference, never a focus-loss waiver. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "8ea883b8fe4b0e86f4b6833871fbb9d8da0d9e736daa37fc266d6b77d11b8783",
    "liveSha256": "48adcf6d820999a5a64dcc83be96ac48da2df60352f428f781bc9e771d181add",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-30 item-error, mobile390, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Saved and Following are independent server-confirmed memberships: the synthetic Saved response contains Kaveri and Sabarmati, while Following contains Kaveri and Vindhya; the frozen example has Vindhya saved and Sabarmati followed. The Kaveri institution type includes server-provided state-established, which can wrap on mobile. Different institution names, locations, fees and entrance-exam values are rendered from those responses, not replaced with prototype values. A genuine DELETE returns HTTP 500, leaving its outcome uncertain. Explicit owner-authorized recovery design variant: retain the last-known cards, display Saved (\u2026) until reloaded, lock both Remove controls and Compare, and show \"Could not confirm removal. This is the last known list. Reload to check the server before trying again.\" with a real Reload action. The frozen notice instead promises \"Nothing changed.\" without server confirmation. The warning triangle replaces the frozen cross icon within this explicitly disclosed recovery notice. The additional truthful notice and action increase card height and shift the next card as quantified below. Uncertain Remove controls are unselected/disabled instead of the frozen selected treatment. Meaningful focus is on the inline error notice with its visible outline; this is an explicitly disclosed interaction-state difference, not a waiver of focus behavior. Residual control/slot geometry (live minus frozen, CSS px; slots compare corresponding card positions even where institution identities differ): School-detail slot 1 [height=7.84375]; School-detail slot 2 [y=100.21875]; Remove/Unfollow school slot 2 [y=100.21875]. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "7befb7a06627c660a0edc5a8f06f6d80a6033cb6081bc3764e77f5aad22a75ca",
    "liveSha256": "2cca6d41d6c2de05b840cd678110e1732861c6cc6bf1a88d4e05da1c4239f559",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-30 item-error, desktop, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. Desktop retains functional 48px Home/Profile buttons instead of static labels and a semantic h2 for the visible Compare saved schools aside. These extra control/heading entries change inventories, not their visible positions. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. Saved and Following are independent server-confirmed memberships: the synthetic Saved response contains Kaveri and Sabarmati, while Following contains Kaveri and Vindhya; the frozen example has Vindhya saved and Sabarmati followed. The Kaveri institution type includes server-provided state-established, which can wrap on mobile. Different institution names, locations, fees and entrance-exam values are rendered from those responses, not replaced with prototype values. A genuine DELETE returns HTTP 500, leaving its outcome uncertain. Explicit owner-authorized recovery design variant: retain the last-known cards, display Saved (\u2026) until reloaded, lock both Remove controls and Compare, and show \"Could not confirm removal. This is the last known list. Reload to check the server before trying again.\" with a real Reload action. The frozen notice instead promises \"Nothing changed.\" without server confirmation. The warning triangle replaces the frozen cross icon within this explicitly disclosed recovery notice. The additional truthful notice and action increase card height and shift the next card as quantified below. Uncertain Remove controls are unselected/disabled instead of the frozen selected treatment. Meaningful focus is on the inline error notice with its visible outline; this is an explicitly disclosed interaction-state difference, not a waiver of focus behavior. Residual control/slot geometry (live minus frozen, CSS px; slots compare corresponding card positions even where institution identities differ): School-detail slot 2 [y=56.125]; Remove/Unfollow school slot 2 [y=56.125]. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "ab1f0e895a621ef31f99f946273d8770ab0c5ac6016f745028e5e61ddf5f39b1",
    "liveSha256": "2349c4fbc2a8414be42418e7006250a27e83870be346546c67e9eb29fbf89d5f",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-30 error, mobile390, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. The Saved GET genuinely returns HTTP 500; the independent Following GET succeeds with two. Saved (\u2026) truthfully remains unknown rather than the frozen count 2, and Compare stays disabled until a successful reload. Retry and the error card retain their geometry; meaningful focus adds the visible 3px indigo outline with 3px offset around the error notice, unlike the unfocused frozen image. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  },
  {
    "screen": "S-30",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "d7b12117d878a15b0a5c1b00d88c3e0ceb1c2146ce2fe042f1a6f4d06300b8ac",
    "liveSha256": "c5eda282d0f6446a666c0f81e08980f3862e7f9036e66ddce1198d1ccad636a7",
    "checks": [
      "controls",
      "geometry",
      "headings",
      "pixels",
      "text"
    ],
    "reason": "S-30 error, desktop, light. Exact hosted live-route capture with synthetic API responses at b414113444caae658f2226ae5a48bf332e40cef1 (run 41603871492); not live-backend or independent Senior QA evidence. Identity disclosure: generic person avatar and accessible name \"Your Profile\" replace prototype-only \"AN\" / \"Aditi Nair\". Explicit owner-authorized selected-tab design variant: the implementation visibly highlights the selected Saved/Following tab with a white background, indigo text and shadow using aria-selected; the frozen markup uses aria-selected but its highlight CSS expects aria-pressed. Retain this truthful selected-state styling without changing tab geometry or selection behavior. Desktop retains functional 48px Home/Profile buttons instead of static labels and a semantic h2 for the visible Compare saved schools aside. These extra control/heading entries change inventories, not their visible positions. School-detail actions are real /s-28 route links with full-school accessible names; Find schools is a real /s-27 link where present, instead of prototype buttons. Remove names retain the full school identity with a different word order. The Saved GET genuinely returns HTTP 500; the independent Following GET succeeds with two. Saved (\u2026) truthfully remains unknown rather than the frozen count 2, and Compare stays disabled until a successful reload. Retry and the error card retain their geometry; meaningful focus adds the visible 3px indigo outline with 3px offset around the error notice, unlike the unfocused frozen image. Corresponding visible control boxes have no residual offset; desktop additional semantic/navigation controls are disclosed above. The redundant mobile empty-state Compare row, Compare icon baseline and Find schools rounded stroke caps were corrected in code. No residual icon-baseline-offset waiver is proposed. Exact image pair only; no accessibility, overflow, unexpected-error, behavior, focus loss/stealing, reference, tolerance, enforcement or unrelated-state waiver.",
    "approvalPr": 88
  }
];
export const s30ProposalHashes=[
  "827365b0f324bb93d83472c579a8011e2d2496244435df7aa76e0eed9b7312a2",
  "103adfd4855306e10eb5fa20ed38aee874e425243859e30d05598689d128f670",
  "b6545f9d574271d8b21575b57e1edd5ef3710242bd82ca0466e83042a5871924",
  "6b95f14329e6d6db715d94f33254b89a448303a7a3d6eb86e977d9c0ebb55ea6",
  "c9f7bce4a41e1fc34c30cec60c1a3e564e9fc90cb189419c53aa154f4cf94757",
  "2ea8dd74964a4f9c03730b1e7e99d72057ec7063d598d7ef4711f0fb8e54128d",
  "d51a4a02ed439f184adb39a193da4412de81e33f47b3b2a76e8b0d5996bf3fda",
  "90a56610ffe6c4b26c9977ef77aa66fa119e0d47ad084700c91d5dfd2c4c1d16",
  "8e04fd89e1ad3fbf7efc59b9c1bf1e89ea85017815e6d47ad7a3e0089f4e2a13",
  "f93d28aaad3535fdfd12b4186b67f461c9e508336cae82ce309616cdebfe1fe2",
  "f63d85ba3d9a8a8450ef2242182d5e0b9b9ae4f2f61461b051ea5527532d01ef",
  "194d0fee9010f11077ac7d24126c3542d4f2081461a61cc46ce6852e7af9208e",
  "9cd21856577bc679d53e2cb63b2b47a0ed8d7672c2436d307b8ce62ead059616",
  "30c1c0e3f5a0b60672c8ce38d4d0072d850aec0d9cfedf9402948c6560d84618",
  "73526ea9f02df10a43efeeb36208b891084d9df042a14c7523e031a979f463bd",
  "25cdba4873dec258bebfe80e64995d20fc6df4c9c7e41cbf80543f2937bf005f"
];
for(const [i,e] of s30Proposals.entries())if(approveException(e,null,{s30:true})!==s30ProposalHashes[i])throw Error('S30_PROPOSAL_PIN_MISMATCH');
export function withoutS30ProposalsForTest(exceptions){
 exceptions=withoutS31ProposalsForTest(exceptions);
 const additions=exceptions.filter(e=>e.screen==='S-30');
 if(additions.length){
  const keys=Object.keys(s30Proposals[0]).sort().join(',');
  if(additions.length!==16||additions.some(e=>Object.keys(e).sort().join(',')!==keys))throw Error('S30_PROPOSAL_INVENTORY_CHANGED');
  if(JSON.stringify(additions.map(e=>approveException(e,null,{s30:true})))!==JSON.stringify(s30ProposalHashes))throw Error('S30_PROPOSAL_CONTENT_CHANGED');
  if(exceptions.slice(-16).some((e,i)=>e!==additions[i]))throw Error('S30_PROPOSAL_APPEND_ORDER_CHANGED');
 }
 // Only this exact appended set is removed from historical test snapshots.
 return exceptions.filter(e=>e.screen!=='S-30');
}
export function withoutS30PolicyBytesForTest(bytes){
 bytes=withoutS31PolicyBytesForTest(bytes);
 const policy=JSON.parse(bytes);withoutS30ProposalsForTest(policy.exceptions);
 if(!policy.exceptions.some(e=>e.screen==='S-30'))return bytes;
 const record=e=>JSON.stringify(e,null,2).replace(/^/gm,'    ');
 const suffix=',\n'+s30Proposals.map(record).join(',\n');
 if(bytes.split(suffix).length!==2||!bytes.endsWith(suffix+'\n  ]\n}\n'))throw Error('S30_PROPOSAL_BYTES_CHANGED');
 return bytes.replace(suffix,'');
}
