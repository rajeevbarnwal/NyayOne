// Test fixtures only: the 16 measured S-21 proposals, NOT owner approvals.
// Hosted read-back remains mandatory; no policy or evaluator imports this file.
import {approveException} from './nyay66-enforcement.mjs';
export const s21Proposals=[
  {
    "screen": "S-21",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "e30fc7449903554537b2357966a13d1be2ebb43825f30311d0031d7db1024eff",
    "liveSha256": "3146d72a82891a32cff676e5e92d54ad53bb9b0e9400518b7401338f54654a2c",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-21 loading, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Loading is an accessible \"Loading internship\" status and genuine unresolved GET, rather than the prototype hidden Loading span; no fabricated completed listing. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "31ed63858ef1222aa5cb611b4713b335198a191f9f1349da2e0d88927871a4b9",
    "liveSha256": "6c95265f2ccca9ae0b67192e22e2be32293f96641f70e82f449e324b92adf197",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 loading, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Retained desktop navigation delta: Home and Profile are real 48px route buttons rather than prototype static text; this changes the control inventory and index-based geometry comparison, not their visible positions. Loading is an accessible \"Loading internship\" status and genuine unresolved GET, rather than the prototype hidden Loading span; no fabricated completed listing. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "1529f011cf88f10c3b8abcdad0c4b19bc66c7b3092b2f0ecd23b43503392dfdc",
    "liveSha256": "5c2c1895b82661fb7f3a7aabc7117763ef728fb2e0f2d2ab1f34a2427b6066cd",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 complete, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 18.59375px and 18.59375px lower respectively; this is disclosed content height, not antialiasing. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "fa019a88299bae4f4f154ad1fc4b2bc21184ba4a2254b0e21dc45dfffaf1a855",
    "liveSha256": "3affd453b161265f9097a9ee07bae368f22c96c7182f967effe03a0739e71b87",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 complete, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Retained desktop navigation delta: Home and Profile are real 48px route buttons rather than prototype static text; this changes the control inventory and index-based geometry comparison, not their visible positions. Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 18.59375px and 18.59375px lower respectively; this is disclosed content height, not antialiasing. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "cdacbaef8de4821221703daa5fc4efd4313517b7c5b5f343fdf10c8014f8d700",
    "liveSha256": "acd43daa4cf50b1ca129f8c331db79b212149a199000e208396b23150a14c93d",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 saved, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 18.59375px and 18.59375px lower respectively; this is disclosed content height, not antialiasing. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "5f35ebc9851c9e2635ba09acc9944c768fdb2052f634ca7db81f019041c42671",
    "liveSha256": "3e1aaa44a4e7c294c11cab00811530ab6d9d3f1f47516798f23fab02255af00d",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 saved, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Retained desktop navigation delta: Home and Profile are real 48px route buttons rather than prototype static text; this changes the control inventory and index-based geometry comparison, not their visible positions. Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 18.59375px and 18.59375px lower respectively; this is disclosed content height, not antialiasing. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "89eef61f10762c77d8c3643a38be1594002544593a00ac7c8451f4c221847046",
    "liveSha256": "477384b6b1d66067bf4ddf92de752ea2b0f1bb7c70ee88b8ece4fe2b85dca388",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 save-pending, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 18.59375px and 18.59375px lower respectively; this is disclosed content height, not antialiasing. Saving remains pending and aria-disabled until the PUT response; no early success claim. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "9930b3b323bab7f4f4034e9c59f81e60e14088ccb31a6060a429f48e89e02f62",
    "liveSha256": "4f4c1b7980854687312c605a549edc23fdd2ff19c21a32830c82063bc558bf4d",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 save-pending, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Retained desktop navigation delta: Home and Profile are real 48px route buttons rather than prototype static text; this changes the control inventory and index-based geometry comparison, not their visible positions. Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 18.59375px and 18.59375px lower respectively; this is disclosed content height, not antialiasing. Saving remains pending and aria-disabled until the PUT response; no early success claim. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "a367d59ca4ece9887d9eb95cc0bccc515d170cc7a2915180056de3dc36ff5d97",
    "liveSha256": "5c5a6e6175619ca17171e61456c0c2949409f708e589d9704e3f8543ca97e18b",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 save-failed, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 54.59375px and 54.59375px lower respectively; this is disclosed content height, not antialiasing. Failure-truthfulness delta: genuine PUT 503 cannot prove \"Nothing changed\". Show \"Could not confirm this change\" and uncertainty wording; replace mutation retry with \"Reload saved state\" GET, and disable the unknown saved mark. Reload is 71px wider and 36px lower than prototype Try again. The meaningful error-notice focus outline is retained after the focus race was fixed in code; this does not waive focus loss. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "48c2c9fe0afa7cd2b29b6aa18d281ac7da2f44649cc6d93f110bf6df02e589d5",
    "liveSha256": "159c6f02e3e46195e62276813221f1acbd21e44ec5fc439b89dde9296ad96e41",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 save-failed, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Retained desktop navigation delta: Home and Profile are real 48px route buttons rather than prototype static text; this changes the control inventory and index-based geometry comparison, not their visible positions. Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 18.59375px and 18.59375px lower respectively; this is disclosed content height, not antialiasing. Failure-truthfulness delta: genuine PUT 503 cannot prove \"Nothing changed\". Show \"Could not confirm this change\" and uncertainty wording; replace mutation retry with \"Reload saved state\" GET, and disable the unknown saved mark. Reload is 71px wider and 0px lower than prototype Try again. The meaningful error-notice focus outline is retained after the focus race was fixed in code; this does not waive focus loss. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "854d4249a8dd52530870b2c15dcc66f911c9ceae85dbc2c852bdd039feca3927",
    "liveSha256": "13277ead3d74ffe40b427b40ade2bcc9fd79c1db92427954ca4aceadc0c2a249",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 session, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 18.59375px and 18.59375px lower respectively; this is disclosed content height, not antialiasing. Session-authority delta: genuine PUT 401 clears student authority through the production handler. Retain \"Saving requires your student account\", Sign in again and disabled \"Saved state unavailable\", not the prototype enabled Save listing. Focus is restored to the notice through remount; its visible outline is retained, not a waiver of a functional defect. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "a61d9238080546de3417cdcc7a04dda9b82f598dfb1adf35717eb538b8d29696",
    "liveSha256": "320e2570b2005d723257ba54569363701819beddaf4301ec68c2e7d906db2f1c",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 session, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Retained desktop navigation delta: Home and Profile are real 48px route buttons rather than prototype static text; this changes the control inventory and index-based geometry comparison, not their visible positions. Provenance delta: retain the shared source verification/non-affiliation disclosure plus retrieved/verified dates on a second line. The source action and Save/Apply row are 18.59375px and 18.59375px lower respectively; this is disclosed content height, not antialiasing. Session-authority delta: genuine PUT 401 clears student authority through the production handler. Retain \"Saving requires your student account\", Sign in again and disabled \"Saved state unavailable\", not the prototype enabled Save listing. Focus is restored to the notice through remount; its visible outline is retained, not a waiver of a functional defect. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "9ec88a6768d52e891cf924ee3d871838d78e076c995c6337e6576008061efd56",
    "liveSha256": "365627c7663bc54d22ec5bfcd260440c631e37184c6644fa930521601df4eb0f",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-21 missing, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". The visible HTTP 404 is the genuine GET response; the missing-listing body and Browse internships action are otherwise retained. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "3f4ad9c91f30e7dda4cf48a2c3ae5fc80546bea6748389a273c4c42f1fe39e61",
    "liveSha256": "e0c6203366764d2a5e1655889369b9d7acae06a0a749ce172404fad873552cf4",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 missing, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Retained desktop navigation delta: Home and Profile are real 48px route buttons rather than prototype static text; this changes the control inventory and index-based geometry comparison, not their visible positions. The visible HTTP 404 is the genuine GET response; the missing-listing body and Browse internships action are otherwise retained. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "db56343f99fa7a1a20d9cb2e8aec760f007fbb806a987fe53990e6fd216e9653",
    "liveSha256": "8f7f25304b13e94b9d41b15e640b0182325749ed852046233ef840ab28d1773f",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-21 error, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". The visible HTTP 500 is the genuine GET response; transport errors and malformed 2xx do not manufacture an HTTP code. The error body and Retry action are otherwise retained. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  },
  {
    "screen": "S-21",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "788cae47425f9b127bd3067ad8444602723906c397efb2dab28ddeb858a348d6",
    "liveSha256": "0405590a916f72b768d00e78e6a026dce6a2d899b043b47c9267b07d4fb23775",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-21 error, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces the prototype-only AN/Aditi Nair identity; no fabricated user initials. Retained accessibility/navigation delta: the unchanged visible Internships back control is named \"Back to internships\". Retained desktop navigation delta: Home and Profile are real 48px route buttons rather than prototype static text; this changes the control inventory and index-based geometry comparison, not their visible positions. The visible HTTP 500 is the genuine GET response; transport errors and malformed 2xx do not manufacture an HTTP code. The error body and Retry action are otherwise retained. No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.",
    "approvalPr": 74
  }
];
export const s21ProposalHashes=[
  "3daf8d67b10e8b75fad39ef520ec24a42c92afbd0bed14adb8a3d6b396a3a830",
  "3bf6241d952b7ce0daebeb181083cd866b06492fba966985c585ea84c9e442ca",
  "6690f49146094574b4f5812df13988c05d47f05639b3f5992fc5ecfd322c80c8",
  "384ca589f9fd4cefc365170e16b6065042b2c210761c036c2dc64f8d3447e44b",
  "6b22279b3e8658f453c11cf8e0702184a513904125433133ecb840f556666b8d",
  "4eb4b0b681abcb0ffbd3277cf047e32f40cb43635e42a883f8108049f0c4dced",
  "c7345280f9daaf6ec19276acc34a41c0143b72fca0c6b705d745c4ce0f75ada8",
  "e6d8e14f3a6b405885278ca013ddefba9bca2054db17f836aa91e2627632ac02",
  "90bf4bb858528377f6f0ad2ab1f646c6570b9b21317f80c453de9bff387620f4",
  "b9636f09783e4c0ba64da47ae278d6a073c4b4b147935149b5a07c4034e320ac",
  "fa1ede3c7dd6714ddb8cb4b5f31e58facedb5a2cb7e8eb4958246132ffc086c1",
  "667d881791cd4941fa5e4b98d1baf873e5fe89124457fc19ebcbb6778500f260",
  "3f7c01e15905092dd41beaf257148b97378a28f507cc6867a699e8b5eccafc1d",
  "9347ef722adbdcaef6502a97a929e37841bde6b4895eaaf432255cf7a959302c",
  "fdba67685f6937422f28b6ae8526e780182619850c4d34cc7b185bb172440698",
  "ca0682706742b194c0a6d22510da413da962ac8a00558209f7d56091dfe11ed0"
];
export const historicalExceptionsSha256='83e9d6f966360866cadb702150920f171929166e7be95848bde36208d08baebf';
// Round 2 test-only candidates. Keep the original sixteen entries/hashes above
// intact. These ten exact replacements are NOT owner approval or policy binding.
export const s21Round2Pins=[
  [2,'6320cddadc60e597871d346fe452a81dbd80fe88afbeb0da7d9bc897a171a73c','19063e59405afa1cb553b8b431bf963cf914beeb6d0962a88154687a4718aa8c',[230,580,307,589]],
  [3,'cff573e09a7a64f4e91459f123595128355c3c297638fe06cf037baf14f83886','983cc88c211b1245de8f960acfebea31a69ddde3f435704ca7c0979214f96aa9',[248,555,325,564]],
  [4,'f35a25cfacfe0f7d8c29bae968178400daa7a6024268dbc6179f4a7f788ac7c0','e2207077b686e014828f5ed9bc2af58782b5b7c0cdb66578e61a35741a8fed07',[230,580,307,589]],
  [5,'dd07cc411b1e6c8e648bec7ab3756651fc6a1a408a88c9e3d571c2c87869f5ba','47d334a121eb9dfd8233064486805012fc4cced1b37babe1efe2778b29880fd9',[248,555,325,564]],
  [6,'bd035e8289e2fa35a1f3a2a9efd8e44dd0abdab266067a6ecdfb61ec1bca1a53','b5741327c1000bf642e69caf96e3ae966ec16970933e5b89c651212374ee7d94',[230,580,307,589]],
  [7,'6615207b96a548e45c1c6061541bf31fc9ac8fb1ade315e25bfe281f4d81fafb','0f6bda9e1476aaa3f8c459395015601d436d81bf85f0aa9550148dd448863645',[248,555,325,564]],
  [8,'03033516eff0ecea2faa03c2a28f669a35e48256228c7bfd4c72f7be6f94be0d','8ebcd08067c6484ba4b33a0ba72646956a916662834738b50888874700483e83',[230,741,307,750]],
  [9,'0500c6a0de207f1d3d6574a251f50d891983b333a1771fd160132b3a454c422f','88865ed6e8586f30f7d684573d99f709bba97c124ccd368296a3ae5376ed075a',[248,680,325,689]],
  [10,'633b82475e14db52c836723da9745ec046e3dbb9b5b26130ca7ac17d83ba6402','1abc179cfe79ffcded9436e02965604239bc4555fce579c424c8c9ff99ae3f2d',[230,705,307,714]],
  [11,'8a5cdd5a5acc5dfc4c4f98e67f6f2ca5743c681877db37f5c3aed48e217bc24b','f6a208fff9a11c794d68e2d78145362720a0e49a8d0ba2b76848834a5401d45f',[248,680,325,689]],
].map(([index,liveSha256,hash,bounds])=>({index,liveSha256,hash,bounds}));
export const s21Round2Proposals=s21Proposals.map((entry,index)=>{
  const pin=s21Round2Pins.find(p=>p.index===index);
  if(!pin)return structuredClone(entry);
  const retained=entry.reason.replace('No reference, tolerance, evaluator or historical approval change; no unrelated CSS defect or unmeasured functional failure is covered.','').trim();
  return {...structuredClone(entry),liveSha256:pin.liveSha256,
    reason:retained+' QA-S21-5 corrected destination-disclosure rendering: the safe source URL host example.test is now visible beside Open source listing and replaces the untrusted free-text source name in its new-tab accessible disclosure. Relative to the previously approved f9c84dce image, exactly 414 pixels change inside ['+pin.bounds.join(', ')+'] (inclusive x1,y1,x2,y2), solely the added host text; headings and control geometry are identical, with zero additional positional offset. This replaces only this exact S-21 pair to represent the implemented fix, not to waive the functional defect. Previously disclosed reference-relative offsets remain as stated above. All 162 historical rows and the other unaffected approvals remain unchanged. No reference, tolerance or evaluator change; no unrelated layout, accessibility or functional defect is covered.'};
});
export const s21Round2ProposalHashes=s21ProposalHashes.map((hash,index)=>s21Round2Pins.find(p=>p.index===index)?.hash??hash);
export function withoutS21ProposalsForTest(exceptions){
  const additions=exceptions.filter(e=>e.screen==='S-21');
  if(additions.length){
    const options={r2:true,s18:true,s19:true,s20:true,s21:true};
    const keys=Object.keys(s21Proposals[0]).sort().join(',');
    if(additions.length!==16||additions.some(e=>Object.keys(e).sort().join(',')!==keys))
      throw new Error('S21_PROPOSAL_INVENTORY_CHANGED');
    const hashes=additions.map(e=>approveException(e,null,options)).sort();
    const pinnedSets=[s21ProposalHashes,s21Round2ProposalHashes];
    if(!pinnedSets.some(pins=>JSON.stringify(hashes)===JSON.stringify([...pins].sort())))
      throw new Error('S21_PROPOSAL_CONTENT_CHANGED');
  }
  // Only the complete original set or its ten exact Round 2 replacements is
  // removed for historical comparisons; partial mixtures fail closed. Those
  // comparisons still pin all old bytes; this never mutates input or policy,
  // and the unchanged runtime gate still requires actual owner comments.
  return exceptions.filter(e=>e.screen!=='S-21');
}
