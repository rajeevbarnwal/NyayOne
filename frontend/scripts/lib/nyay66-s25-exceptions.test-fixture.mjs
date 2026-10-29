// Test-only pins for the 12 hosted S-25 proposals at d238689; NOT approvals.
// No runtime/evaluator imports this fixture. Actual owner read-back is mandatory.
import {approveException} from './nyay66-enforcement.mjs';
export const s25Proposals=[
  {
    "screen": "S-25",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "d53a7b92b96889c42a7115016ce058382329cadd1244fcff2a92d7b6889fc341",
    "liveSha256": "76c580003bc88226f82693345b847c0c2f80876c25055074e18c124008a83c0c",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-25 loading, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". The saved-list GET remains pending; the skeleton is an accessible Loading saved internships status, not fabricated data. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "659cf24da3c6140ae81842f64320487be94b8801d178609655c62b4959527c78",
    "liveSha256": "812984738060d960f5646b17724de5fa175c39f1a93db0385f04588a23cff95e",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-25 loading, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". Retained desktop route controls: Home and Profile are real 48px buttons instead of static text, changing control inventory and its index-based geometry comparison without moving their visible positions. The aside says \"Withdrawn or unavailable listings are omitted by the catalogue.\" rather than claiming automatic removal after deadlines. The saved-list GET remains pending; the skeleton is an accessible Loading saved internships status, not fabricated data. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "5edcabe8d8b7840cac6ec69d3ec7790b2172e47452c55af464cb578334d98ec6",
    "liveSha256": "87faa8353ee2ac1634683898c7a5963542f3ffd674c01f8bfe1c22caf423279c",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-25 list, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". The three cards and count come from the synthetic saved-list response; Remove controls have listing-specific accessible names and confirmed saved-state semantics. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "ad53dc952abd07ded34aa1ea907d09f4f5500cd44093859390cb4052d123e386",
    "liveSha256": "825aeb82889ac14e920548d79b11242c11ec6206f7291c031b1406a3b774ebc0",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-25 list, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". Retained desktop route controls: Home and Profile are real 48px buttons instead of static text, changing control inventory and its index-based geometry comparison without moving their visible positions. The aside says \"Withdrawn or unavailable listings are omitted by the catalogue.\" rather than claiming automatic removal after deadlines. The three cards and count come from the synthetic saved-list response; Remove controls have listing-specific accessible names and confirmed saved-state semantics. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "c29037dacf9a8634914b0476e735ff41ed7c989184b8fb3b4b09dc775897ee2f",
    "liveSha256": "029c9ad51da8a097c8ac2d95147a08ea48c538ff0afc839cc7367a4acb269022",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-25 empty, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". The empty state follows a confirmed empty server list. Both Browse actions remain functional routes; the filled empty action is preserved. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "531023f5f36f2d7c66dede460f070d11790dc0871ce90f095e90fd0211a25435",
    "liveSha256": "2e83409bce5a922946c99429faa4ea0320c570f938b2469d6b6dd1c56d84912a",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-25 empty, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". Retained desktop route controls: Home and Profile are real 48px buttons instead of static text, changing control inventory and its index-based geometry comparison without moving their visible positions. The aside says \"Withdrawn or unavailable listings are omitted by the catalogue.\" rather than claiming automatic removal after deadlines. The empty state follows a confirmed empty server list. Both Browse actions remain functional routes; the filled empty action is preserved. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "cf5e923beaaf08a4bafe3991a58bf6b8e1a0bcdea83dbc6e1b47cae3efc7c51b",
    "liveSha256": "0455d79dcb15cf610677be430ffa42fcd7f6c0fe73169781653125a1fd815040",
    "checks": [
      "controls",
      "pixels",
      "text"
    ],
    "reason": "S-25 remove-pending, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". A genuine pending DELETE retains all three cards and locks all Remove controls, rather than only the active card, preventing competing mutations; no optimistic removal or success claim. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "d909abc93514f8662f6447b7375c36dd7839d3a690cd3d653ad30b47ba4f3237",
    "liveSha256": "8210f897fa848faa5ff139dd767bb0df811afc1974c9e89c53f160d4ee740c9d",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-25 remove-pending, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". Retained desktop route controls: Home and Profile are real 48px buttons instead of static text, changing control inventory and its index-based geometry comparison without moving their visible positions. The aside says \"Withdrawn or unavailable listings are omitted by the catalogue.\" rather than claiming automatic removal after deadlines. A genuine pending DELETE retains all three cards and locks all Remove controls, rather than only the active card, preventing competing mutations; no optimistic removal or success claim. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "58296a7711c0ae2925bfe06fe8b342973598dc711fec355eb661cb1ad6497454",
    "liveSha256": "c4e2c4d0bc4736accaec1c6c25ffb708ec207b7e8e21668f04472508b0f01033",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-25 remove-failed, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". A genuine DELETE 503 leaves saved state uncertain. Retain the focused error notice \"Could not confirm removal. Reload your saved list.\", the last-known-list warning, Reload saved list action, unavailable saved marks and \"3 in the last known list\", not the prototype's \"Still saved\" assertion. The first card is 161px lower than the frozen reference; the remaining cards are 139px lower because the new notice replaces the prototype's 22px inline failure. These are disclosed truthful-recovery content shifts, not rasterization or a focus-defect waiver. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "76515e848beb50f4c30b4bfb5ea553bf1ed8599c0416cf0e0a88b3d8a8d6f6da",
    "liveSha256": "814a8008dade449c53272248370100d5bacc066412434b0964dc61a16090f7f3",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-25 remove-failed, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". Retained desktop route controls: Home and Profile are real 48px buttons instead of static text, changing control inventory and its index-based geometry comparison without moving their visible positions. The aside says \"Withdrawn or unavailable listings are omitted by the catalogue.\" rather than claiming automatic removal after deadlines. A genuine DELETE 503 leaves saved state uncertain. Retain the focused error notice \"Could not confirm removal. Reload your saved list.\", the last-known-list warning, Reload saved list action, unavailable saved marks and \"3 in the last known list\", not the prototype's \"Still saved\" assertion. The first card is 125px lower than the frozen reference; the remaining cards are 103px lower because the new notice replaces the prototype's 22px inline failure. These are disclosed truthful-recovery content shifts, not rasterization or a focus-defect waiver. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "mobile390",
    "theme": "light",
    "referenceSha256": "37139d72b63ee19e110544a30e8b4f8d193ba8882494c16dbea4dd71a4a87bd5",
    "liveSha256": "0b2cfdb53ee01dcb7f288a5ff1e7c1b805503819bb91a9138aa29214bcc11052",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-25 error, mobile390, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". A genuine saved-list GET 500 is displayed as HTTP 500. Retain \"No saved-list claim is made until the server confirms it.\" rather than \"Nothing was removed\". The extra body line places Retry and the card bottom 19.5px lower; the 4px action-row gap matches the reference. The meaningful error-focus outline is retained, not a waiver of focus loss. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  },
  {
    "screen": "S-25",
    "viewport": "desktop",
    "theme": "light",
    "referenceSha256": "6338bebeb808c8eb17c0628466131ba44c197620d364eb81fa1e7a6f6e5d7ac4",
    "liveSha256": "300fbd5491eaa7dab9128f8fa6a43542646c43b2627d90487202ee3db79ec18e",
    "checks": [
      "controls",
      "geometry",
      "pixels",
      "text"
    ],
    "reason": "S-25 error, desktop, light. Live-route capture with synthetic backend responses; not live-backend or independent QA evidence. Identity delta: generic person avatar with accessible name \"Your Profile\" replaces prototype-only AN/Aditi Nair. Truthful saved-list copy: \"Listings in your saved list.\" replaces the prototype claim that saved listings are still open; the backend does not filter passed deadlines. Retain the privacy disclosure \"Private to your account · organisations are not notified\". Retained desktop route controls: Home and Profile are real 48px buttons instead of static text, changing control inventory and its index-based geometry comparison without moving their visible positions. The aside says \"Withdrawn or unavailable listings are omitted by the catalogue.\" rather than claiming automatic removal after deadlines. A genuine saved-list GET 500 is displayed as HTTP 500. Retain \"No saved-list claim is made until the server confirms it.\" rather than \"Nothing was removed\". The extra body line places Retry and the card bottom 19.5px lower; the 4px action-row gap matches the reference. The meaningful error-focus outline is retained, not a waiver of focus loss. The outlined Browse icon baseline is corrected in code to the frozen reference; no residual icon offset is proposed. No reference, tolerance, evaluator, historical approval or unrelated layout/accessibility defect is covered.",
    "approvalPr": 76
  }
];
export const s25ProposalHashes=[
  "55811d26f055d92f458cfff07f6a43602722690dc11f8be14d96aa22260a4175",
  "ae68775019df0e3f9b0f75b19705c4ea695fc5f05fee096f054931cdd4b32c44",
  "12352ed2e9082265c663c123c765603ca8b8a7ce7a2e49ad6ca46fdb25fab1c7",
  "9fda3afaf94a0d676bc83dd240d562196699b4c99327548c3a16dcdacd1d09c6",
  "69d5fd8d7cdd87fac237f11b7f492e4bd5b3925df8212edeec2d3d12a68cb547",
  "07478adf952f55b1dd717302883467eebc3f92b4fdeb91e372b73e1ca5add26b",
  "1f41e833f20bb0dc6b569fbd110f6793dddac63bfd2cc600fbd585afd8686dbb",
  "cf405ba625c39739c66a55000d8ea5a90f8c7bb00ca97aa31d454712d1c15c0e",
  "1cd328f3f7cee896c5d1a13a7e09dc92b87acdf357cbf209a44d7bb4cc4137d0",
  "b780f83e0a7a35f84d290455b41e51696b5a87e2077a8a52d7c923e3ac56c2a2",
  "0bf7047dd591fe71a01e48c2cab7e6a49cbeb2c52e7c932c4860f5c080d3650b",
  "f58fc0f28b1ff9aea8cd75c70e2c80ea9867badeb7759a1353e7a4c085aade49"
];
export const historicalS25ExceptionsSha256='d8b15671b74e246a832e6a06ebed29b6f0912786f35f885d5a59319de5480aef';
export function withoutS25ProposalsForTest(exceptions){
  const additions=exceptions.filter(e=>e.screen==='S-25');
  if(additions.length){
    const options={r2:true,s18:true,s19:true,s20:true,s21:true,s25:true};
    const keys=Object.keys(s25Proposals[0]).sort().join(',');
    if(additions.length!==12||additions.some(e=>Object.keys(e).sort().join(',')!==keys))
      throw new Error('S25_PROPOSAL_INVENTORY_CHANGED');
    const hashes=additions.map(e=>approveException(e,null,options)).sort();
    if(JSON.stringify(hashes)!==JSON.stringify([...s25ProposalHashes].sort()))
      throw new Error('S25_PROPOSAL_CONTENT_CHANGED');
  }
  // Preserve all other records and their order, without mutating input or policy.
  return exceptions.filter(e=>e.screen!=='S-25');
}
