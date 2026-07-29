# Token & Component Inventory — Options A · B · C

## Palettes (CSS custom properties on `:root[data-theme]`)
| Option | Light | Dark | Accent logic |
|---|---|---|---|
| A Trusted Chambers | paper `#f6f4ef` / card `#fcfbf8` / ink `#1a1815` / bottle-green `#1e4634` | `#16130e` / `#1e1a13` / `#f0ebdf` / sage `#7fb094` | one green accent; claret `#8a2b2b` risk; amber `#7a5a1e` caution; steel `#2f4b63` info |
| B Guided Fintech | mist `#f3f6f7` / white / ink `#14222b` / teal `#0c6b70` + indigo `#4353ae` | `#0e1519` / `#162026` / `#ecf2f4` / `#5ecfc5` + `#a7b2f2` | teal = progress/trust; indigo = secondary action; amber/rust states |
| C Live Marketplace | cream `#fbf6ee` / white / ink `#271a0d` / jade `#116b44` + terracotta `#a63d0e` | `#171008` / `#221a10` / `#f4ecdd` / `#63d3a0` + `#f59e6b` | jade = money-safe; terracotta = energy/CTA; teal info |

Type: A = Newsreader + Libre Franklin + IBM Plex Mono · B = Schibsted + Hanken Grotesk + JetBrains Mono · C = Hanken Grotesk 800 + IBM Plex Mono. Radii: A 3–6px sharp · B 10–16px soft · C 16–24px pill.

## Measured contrast (shipped tokens, WCAG luminance)
| Palette | Pair | Colours | Ratio | Result |
|---|---|---|---|---|
| A.light | Body ink / bg | `#1a1815` on `#f6f4ef` | **16.12:1** | AA pass |
| A.light | Secondary / bg | `#453f37` on `#f6f4ef` | **9.46:1** | AA pass |
| A.light | Muted / card | `#6b6459` on `#fcfbf8` | **5.65:1** | AA pass |
| A.light | Provenance / card | `#756d5b` on `#fcfbf8` | **4.96:1** | AA pass |
| A.light | Primary text / card | `#1e4634` on `#fcfbf8` | **10.24:1** | AA pass |
| A.light | On-primary / primary | `#ffffff` on `#1e4634` | **10.6:1** | AA pass |
| A.light | Warn / warn-bg | `#7a5a1e` on `#f5efdf` | **5.53:1** | AA pass |
| A.light | Risk / risk-bg | `#8a2b2b` on `#f7ecec` | **7.38:1** | AA pass |
| A.light | Info / info-bg | `#2f4b63` on `#e9eef3` | **7.8:1** | AA pass |
| A.dark | Body ink / bg | `#f0ebdf` on `#16130e` | **15.57:1** | AA pass |
| A.dark | Secondary / bg | `#cfc7b6` on `#16130e` | **11.02:1** | AA pass |
| A.dark | Muted / card | `#a89f8c` on `#1e1a13` | **6.6:1** | AA pass |
| A.dark | Provenance / card | `#958c79` on `#1e1a13` | **5.2:1** | AA pass |
| A.dark | Primary text / card | `#7fb094` on `#1e1a13` | **7.04:1** | AA pass |
| A.dark | On-primary / primary | `#10160f` on `#7fb094` | **7.47:1** | AA pass |
| A.dark | Warn / warn-bg | `#d9b664` on `#2c2414` | **7.9:1** | AA pass |
| A.dark | Risk / risk-bg | `#e09a8a` on `#2e1d19` | **7.01:1** | AA pass |
| A.dark | Info / info-bg | `#8fb0c9` on `#1c242c` | **6.89:1** | AA pass |
| B.light | Body ink / bg | `#14222b` on `#f3f6f7` | **14.95:1** | AA pass |
| B.light | Secondary / bg | `#3c4f5c` on `#f3f6f7` | **7.84:1** | AA pass |
| B.light | Muted / card | `#5d707c` on `#ffffff` | **5.15:1** | AA pass |
| B.light | Provenance / card | `#62747f` on `#ffffff` | **4.86:1** | AA pass |
| B.light | Primary text / card | `#0c6b70` on `#ffffff` | **6.26:1** | AA pass |
| B.light | On-primary / primary | `#ffffff` on `#0c6b70` | **6.26:1** | AA pass |
| B.light | Warn / warn-bg | `#7a5a14` on `#f5eedb` | **5.5:1** | AA pass |
| B.light | Risk / risk-bg | `#963126` on `#f8e9e6` | **6.44:1** | AA pass |
| B.light | Info / info-bg | `#34557a` on `#e9eff6` | **6.65:1** | AA pass |
| B.dark | Body ink / bg | `#ecf2f4` on `#0e1519` | **16.29:1** | AA pass |
| B.dark | Secondary / bg | `#c6d4da` on `#0e1519` | **12.13:1** | AA pass |
| B.dark | Muted / card | `#93a6af` on `#162026` | **6.55:1** | AA pass |
| B.dark | Provenance / card | `#8296a0` on `#162026` | **5.38:1** | AA pass |
| B.dark | Primary text / card | `#5ecfc5` on `#162026` | **8.83:1** | AA pass |
| B.dark | On-primary / primary | `#062421` on `#5ecfc5` | **8.74:1** | AA pass |
| B.dark | Warn / warn-bg | `#ddb964` on `#2d2513` | **8.08:1** | AA pass |
| B.dark | Risk / risk-bg | `#e79d8b` on `#33211c` | **6.98:1** | AA pass |
| B.dark | Info / info-bg | `#93b7dc` on `#1b2836` | **7.16:1** | AA pass |
| C.light | Body ink / bg | `#271a0d` on `#fbf6ee` | **15.74:1** | AA pass |
| C.light | Secondary / bg | `#544a3b` on `#fbf6ee` | **8.07:1** | AA pass |
| C.light | Muted / card | `#71654f` on `#ffffff` | **5.71:1** | AA pass |
| C.light | Provenance / card | `#75694f` on `#ffffff` | **5.4:1** | AA pass |
| C.light | Primary text / card | `#116b44` on `#ffffff` | **6.54:1** | AA pass |
| C.light | On-primary / primary | `#ffffff` on `#116b44` | **6.54:1** | AA pass |
| C.light | Warn / warn-bg | `#8a5a0c` on `#fbf0d4` | **5.22:1** | AA pass |
| C.light | Risk / risk-bg | `#9c2b23` on `#f9e9e6` | **6.4:1** | AA pass |
| C.light | Info / info-bg | `#0e6470` on `#e4f2f3` | **5.95:1** | AA pass |
| C.dark | Body ink / bg | `#f4ecdd` on `#171008` | **16.06:1** | AA pass |
| C.dark | Secondary / bg | `#d8cbb4` on `#171008` | **11.78:1** | AA pass |
| C.dark | Muted / card | `#ab9c7f` on `#221a10` | **6.37:1** | AA pass |
| C.dark | Provenance / card | `#9c8d70` on `#221a10` | **5.28:1** | AA pass |
| C.dark | Primary text / card | `#63d3a0` on `#221a10` | **9.28:1** | AA pass |
| C.dark | On-primary / primary | `#08241a` on `#63d3a0` | **8.89:1** | AA pass |
| C.dark | Warn / warn-bg | `#ffd072` on `#342812` | **9.96:1** | AA pass |
| C.dark | Risk / risk-bg | `#f0998a` on `#361f19` | **7.04:1** | AA pass |
| C.dark | Info / info-bg | `#6fd0d8` on `#14313a` | **7.64:1** | AA pass |

**0 failures across all 54 pairs.**

## Shared component contract (same behaviour, three skins)
Hold band/stepper/context-bar (sticky, in-flow, `role=timer`, non-colour urgency) · fee ledger/table from integer paise · hosted-field card inputs (visual treatment marked PROVIDER-HOSTED; never real inputs for PAN/CVV) · OTP boxes + attempts/resend/expiry · status chips (dot/diamond/triangle/square glyph + label) · banners with mono kicker + typed wire code · slot buttons (available/held/booked = state + text) · refund/attendance progress rows · video: PreJoin, DeviceCheck, ParticipantTile (video/canvas + name/role + mute/cam badges + active-speaker outline+text), ControlBar (44–48px), ConnectionStatus text, leave-confirm, post-session · stars (radiogroup) + 10–1,000-char review field · reviewer rig (dashed, baseline-hidden).

Server-authority annotations (`.svr`) render in the prototype but are **hidden in baseline mode** — they are engineering notes, not product copy.