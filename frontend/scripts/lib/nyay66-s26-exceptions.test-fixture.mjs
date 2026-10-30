// Test-only proposals; NOT owner approval. Hosted read-back remains mandatory.
import {approveException} from './nyay66-enforcement.mjs';
export const s26Proposals=[
  {
    "screen": "S-26",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "b81eb5c57ffcc65e4a2fda31d6fc2d31d4468206cd5b1ec2a890256826dc1e47",
    "liveSha256": "513ee35af215aaf2ab3377603edc55285112b89d335859320e010b9b27b8529f",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-26 empty, mobile390, light. Hosted live-route measurement with synthetic API responses, not live-backend or independent QA evidence. Identity presentation: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only \"AN\"/\"Aditi Nair\" identity; 235 raw changed pixels lie in the avatar. All pixels outside the avatar match the frozen reference exactly; no residual icon/baseline or layout offset. Empty state is shown only after a successful zero-item saved-list response; Browse internships routes to S-20. No reference, tolerance, historical approval or unrelated defect is covered.",
    "approvalPr": 78
  },
  {
    "screen": "S-26",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "d89600b9a4782aec657e804f84d51c36b4b9693ce255ab1547aeebc265b5deb8",
    "liveSha256": "0178eb61cc7a2901e3e7ba77b603590e5a885af24d040b6f56c2ccf69d9173b6",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-26 empty, desktop, light. Hosted live-route measurement with synthetic API responses, not live-backend or independent QA evidence. Identity presentation: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only \"AN\"/\"Aditi Nair\" identity; 235 raw changed pixels lie in the avatar. Retain real 48px Home and Profile route buttons instead of the prototype static labels. Their added control inventory triggers the index-based geometry comparison; visible header positions and every matched heading/action box are identical (0px offset). All pixels outside the avatar match the frozen reference exactly; no residual icon/baseline or layout offset. Empty state is shown only after a successful zero-item saved-list response; Browse internships routes to S-20. No reference, tolerance, historical approval or unrelated defect is covered.",
    "approvalPr": 78
  },
  {
    "screen": "S-26",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "ed2b61e1b7a9e7285e7c70e706168e167399d2c14c7b94b69f481cfb33ff39d7",
    "liveSha256": "cb4323484f49d6803a1368ab55d413d46e4fa1d398c62bb4ad2a6d108efb97d6",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-26 loading, mobile390, light. Hosted live-route measurement with synthetic API responses, not live-backend or independent QA evidence. Identity presentation: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only \"AN\"/\"Aditi Nair\" identity; 235 raw changed pixels lie in the avatar. All pixels outside the avatar match the frozen reference exactly; no residual icon/baseline or layout offset. The saved-list GET is deliberately pending and disclosed as cancelled at context disposal; no false empty state or invented success. No reference, tolerance, historical approval or unrelated defect is covered.",
    "approvalPr": 78
  },
  {
    "screen": "S-26",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "ea051ce92916242113ec91b5e0c943ba52a94a44dda4e8b7d6d560e0e243b9cc",
    "liveSha256": "6b80aced3a9ad8b67c495eb37faab5383496dfcdddff48a3f535519e675d37b8",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-26 loading, desktop, light. Hosted live-route measurement with synthetic API responses, not live-backend or independent QA evidence. Identity presentation: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only \"AN\"/\"Aditi Nair\" identity; 235 raw changed pixels lie in the avatar. Retain real 48px Home and Profile route buttons instead of the prototype static labels. Their added control inventory triggers the index-based geometry comparison; visible header positions and every matched heading/action box are identical (0px offset). All pixels outside the avatar match the frozen reference exactly; no residual icon/baseline or layout offset. The saved-list GET is deliberately pending and disclosed as cancelled at context disposal; no false empty state or invented success. No reference, tolerance, historical approval or unrelated defect is covered.",
    "approvalPr": 78
  },
  {
    "screen": "S-26",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "6fb62d2be1fc718571cc81116d4dc6189b483446ada1b5823dba703c7fb07819",
    "liveSha256": "db74b6b8bb764debb34b32888e095d425e23913308e5e54cbff745696de2583f",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-26 error, mobile390, light. Hosted live-route measurement with synthetic API responses, not live-backend or independent QA evidence. Identity presentation: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only \"AN\"/\"Aditi Nair\" identity; 235 raw changed pixels lie in the avatar. Interaction-state disclosure: genuine saved-list GET HTTP 500 focuses the role=alert error notice. Retain its visible 3px indigo focus outline with 3px outline offset; the frozen screenshot is unfocused. The 4547 raw changed pixels outside the avatar are confined to the error-card focus outline and adjacent dashed-edge rasterization; no changes occur more than 8px inside the card edge. Heading, Retry button and content positions match exactly; no scroll or baseline shift. This approves the focused visual state only, never focus loss, focus stealing or another functional/accessibility defect. No reference, tolerance, historical approval or unrelated defect is covered.",
    "approvalPr": 78
  },
  {
    "screen": "S-26",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "65955518a671527152a9681c3cd7acd3b8da21db60b56af81b7ac8edd010f811",
    "liveSha256": "2bdc7359676030296e52e18ee78edef3403046092c0596b5cfb6d089e53b4437",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-26 error, desktop, light. Hosted live-route measurement with synthetic API responses, not live-backend or independent QA evidence. Identity presentation: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only \"AN\"/\"Aditi Nair\" identity; 235 raw changed pixels lie in the avatar. Retain real 48px Home and Profile route buttons instead of the prototype static labels. Their added control inventory triggers the index-based geometry comparison; visible header positions and every matched heading/action box are identical (0px offset). Interaction-state disclosure: genuine saved-list GET HTTP 500 focuses the role=alert error notice. Retain its visible 3px indigo focus outline with 3px outline offset; the frozen screenshot is unfocused. The 7887 raw changed pixels outside the avatar are confined to the error-card focus outline and adjacent dashed-edge rasterization; no changes occur more than 8px inside the card edge. Heading, Retry button and content positions match exactly; no scroll or baseline shift. This approves the focused visual state only, never focus loss, focus stealing or another functional/accessibility defect. No reference, tolerance, historical approval or unrelated defect is covered.",
    "approvalPr": 78
  },
  {
    "screen": "S-26",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "3ca72ade05bb63ffac43129918b6652149885df2d34c28c216e2181e6d10e9d6",
    "liveSha256": "86781175f2cf8f1dd9be2ab089d8abb9101585742dbf479555708808e354845b",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-26 nonempty, mobile390, light. Hosted live-route measurement with synthetic API responses, not live-backend or independent QA evidence. Identity presentation: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only \"AN\"/\"Aditi Nair\" identity; 235 raw changed pixels lie in the avatar. All pixels outside the avatar match the frozen reference exactly; no residual icon/baseline or layout offset. The three-item count comes from validated synthetic saved-list data; Open saved internships routes to S-25. No reference, tolerance, historical approval or unrelated defect is covered.",
    "approvalPr": 78
  },
  {
    "screen": "S-26",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "796a11d4e162f60ee6e36ace1514c620aa4d63e8100325bef554f0eae8769e52",
    "liveSha256": "f474664632aa91f7bf4719882b6c968ab5557b0195c44be685b32f4735090801",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-26 nonempty, desktop, light. Hosted live-route measurement with synthetic API responses, not live-backend or independent QA evidence. Identity presentation: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only \"AN\"/\"Aditi Nair\" identity; 235 raw changed pixels lie in the avatar. Retain real 48px Home and Profile route buttons instead of the prototype static labels. Their added control inventory triggers the index-based geometry comparison; visible header positions and every matched heading/action box are identical (0px offset). All pixels outside the avatar match the frozen reference exactly; no residual icon/baseline or layout offset. The three-item count comes from validated synthetic saved-list data; Open saved internships routes to S-25. No reference, tolerance, historical approval or unrelated defect is covered.",
    "approvalPr": 78
  }
];
export const s26ProposalHashes=[
  "f043dfedb59e89ab1b267541de6b3068f38505db33ac2a79a99d2a8e21cef28f",
  "cd68da3b4e82b25856fefdcbffcb1c125205e2707c58c309c762186dc52d4135",
  "a7be5097db2794ff8486d67edac60b29e876fdf997c5e72a8c79f0695df39b80",
  "5a7d183cee5af655e5b800ee3f1d5c13621b965063b8d02ccb804b39261e7bc4",
  "80e2a76b9d60b5eb573a9953c5aa09dc8895762d9552b12dabcf6773118226d3",
  "2caeff8b3f829919d360dc0f875537dd12a01dd5bdb22447253584697c61e125",
  "798d049a592621ce5312abff2189ab2e98c0fef88f5e3ab8939158c4201f6cd9",
  "29eb383d87d8e2ae45f95e9b35f491aca00f1d7ee7db9ea906e7e007337e8e8a"
];
export const historicalS26ExceptionsSha256='e97d03efb6e5d9483341a41f4e9f0cc42e351e9fb61b263155428a857fae14e4';
export function withoutS26ProposalsForTest(exceptions){
  const additions=exceptions.filter(e=>e.screen==='S-26');
  if(additions.length){
    const keys=Object.keys(s26Proposals[0]).sort().join(',');
    if(additions.length!==8||additions.some(e=>Object.keys(e).sort().join(',')!==keys))
      throw new Error('S26_PROPOSAL_INVENTORY_CHANGED');
    const options={r2:true,s18:true,s19:true,s20:true,s21:true,s25:true,s26:true};
    if(JSON.stringify(additions.map(e=>approveException(e,null,options)))!==JSON.stringify(s26ProposalHashes))
      throw new Error('S26_PROPOSAL_CONTENT_CHANGED');
  }
  // Validate additions before excluding them from older test snapshots. Never
  // mutate or normalize any other record; historical byte/order checks remain.
  return exceptions.filter(e=>e.screen!=='S-26');
}
