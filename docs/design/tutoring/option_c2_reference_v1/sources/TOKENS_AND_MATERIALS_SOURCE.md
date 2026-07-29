# Tokens & Materials — three directions

All values are the shipped CSS custom properties in each prototype (`:root[data-theme=light|dark]`). No external assets, fonts self-contained in the bundle, all artwork original inline SVG.

## Measured contrast (WCAG relative luminance)
| Palette | Pair | Colours | Ratio | Result |
|---|---|---|---|---|
| A.light | Body ink / bg | `#191510` on `#f2ece1` | **15.45:1** | AA pass |
| A.light | Secondary / bg | `#4a4034` on `#f2ece1` | **8.61:1** | AA pass |
| A.light | Muted / card | `#6f6250` on `#fffdf8` | **5.84:1** | AA pass |
| A.light | Primary text / card | `#12503a` on `#fffdf8` | **9.25:1** | AA pass |
| A.light | On-primary / primary | `#ffffff` on `#12503a` | **9.4:1** | AA pass |
| A.light | Accent text / accent tint | `#a8480f` on `#fbeadd` | **4.98:1** | AA pass |
| A.light | Gold text / gold tint | `#8a6108` on `#f8eed6` | **4.79:1** | AA pass |
| A.light | Risk text / risk tint | `#8d2a20` on `#f8e7e3` | **7.06:1** | AA pass |
| A.dark | Body ink / bg | `#f4eddf` on `#161209` | **16.03:1** | AA pass |
| A.dark | Secondary / bg | `#d6cab3` on `#161209` | **11.52:1** | AA pass |
| A.dark | Muted / card | `#a99b81` on `#211b12` | **6.25:1** | AA pass |
| A.dark | Primary text / card | `#7cbd9b` on `#211b12` | **7.81:1** | AA pass |
| A.dark | On-primary / primary | `#08150f` on `#7cbd9b` | **8.55:1** | AA pass |
| A.dark | Accent text / accent tint | `#eb9a63` on `#33200f` | **6.89:1** | AA pass |
| A.dark | Gold text / gold tint | `#e3bd67` on `#302512` | **8.39:1** | AA pass |
| A.dark | Risk text / risk tint | `#eb9d8c` on `#331d18` | **7.32:1** | AA pass |
| B.light | Body ink / bg | `#111f2c` on `#eef2f6` | **14.86:1** | AA pass |
| B.light | Secondary / bg | `#3a4f61` on `#eef2f6` | **7.55:1** | AA pass |
| B.light | Muted / card | `#5d7488` on `#ffffff` | **4.86:1** | AA pass |
| B.light | Primary text / card | `#0b5f8a` on `#ffffff` | **6.96:1** | AA pass |
| B.light | On-primary / primary | `#ffffff` on `#0b5f8a` | **6.96:1** | AA pass |
| B.light | Accent text / accent tint | `#0d6b52` on `#e2f0eb` | **5.52:1** | AA pass |
| B.light | Gold text / gold tint | `#8a5a08` on `#f9efd8` | **5.18:1** | AA pass |
| B.light | Risk text / risk tint | `#93281f` on `#f9e8e5` | **6.9:1** | AA pass |
| B.dark | Body ink / bg | `#e9f2f8` on `#0a1219` | **16.63:1** | AA pass |
| B.dark | Secondary / bg | `#c3d5e0` on `#0a1219` | **12.5:1** | AA pass |
| B.dark | Muted / card | `#8ea6b6` on `#122029` | **6.55:1** | AA pass |
| B.dark | Primary text / card | `#5cb6e0` on `#122029` | **7.29:1** | AA pass |
| B.dark | On-primary / primary | `#04141d` on `#5cb6e0` | **8.21:1** | AA pass |
| B.dark | Accent text / accent tint | `#5fc9a6` on `#12291f` | **7.63:1** | AA pass |
| B.dark | Gold text / gold tint | `#e0b761` on `#2c2412` | **8.12:1** | AA pass |
| B.dark | Risk text / risk tint | `#ec9b8b` on `#331e19` | **7.18:1** | AA pass |
| C2.light | Body ink / bg | `#211609` on `#fbf7f0` | **16.62:1** | AA pass |
| C2.light | Secondary / bg | `#4d4234` on `#fbf7f0` | **9.17:1** | AA pass |
| C2.light | Muted / card | `#6f6248` on `#ffffff` | **5.97:1** | AA pass |
| C2.light | Primary text / card | `#0f6b47` on `#ffffff` | **6.53:1** | AA pass |
| C2.light | On-primary / primary | `#ffffff` on `#0f6b47` | **6.53:1** | AA pass |
| C2.light | Accent text / accent tint | `#a8410c` on `#fdeadd` | **5.25:1** | AA pass |
| C2.light | Gold text / gold tint | `#8a6108` on `#faf0d6` | **4.88:1** | AA pass |
| C2.light | Risk text / risk tint | `#98281d` on `#fae9e5` | **6.72:1** | AA pass |
| C2.light | Indigo text / indigo tint | `#3f4796` on `#eceefb` | **7.12:1** | AA pass |
| C2.dark | Body ink / bg | `#f7f0e2` on `#140e06` | **16.91:1** | AA pass |
| C2.dark | Secondary / bg | `#dbcdb7` on `#140e06` | **12.26:1** | AA pass |
| C2.dark | Muted / card | `#ad9d81` on `#1f170d` | **6.67:1** | AA pass |
| C2.dark | Primary text / card | `#5fcb9c` on `#1f170d` | **8.86:1** | AA pass |
| C2.dark | On-primary / primary | `#06180f` on `#5fcb9c` | **9.18:1** | AA pass |
| C2.dark | Accent text / accent tint | `#f2986a` on `#37200f` | **6.89:1** | AA pass |
| C2.dark | Gold text / gold tint | `#e6bf6a` on `#332612` | **8.43:1** | AA pass |
| C2.dark | Risk text / risk tint | `#ef9c8b` on `#361d17` | **7.29:1** | AA pass |
| C2.dark | Indigo text / indigo tint | `#a4abf5` on `#23264a` | **6.72:1** | AA pass |

**0 pairs below 4.5:1 across all six palettes.**

## Material systems
| | A | B | C2 |
|---|---|---|---|
| Ground | warm paper #f2ece1 / walnut #161209 | mist #eef2f6 / navy #0a1219 | cream #fbf7f0 / espresso #140e06 |
| Radii | 2–3px (near-square) | 12–20px | 14–26px |
| Borders | 1px hairline | 1–1.5px | 1.5–2px |
| Shadow | one frame shadow only | one on the rail container | one per composition |
| Saturated surface | none (ink only) | rail gradient tint | checkout trust panel (jade gradient) |
| Mono usage | eyebrows, refs, captions | refs + step micro-type | money, refs, timestamps only |
| Icon accent | saffron | blue | jade + terracotta |

## Typography
A: Newsreader 500/600 + Libre Franklin 400–800 + IBM Plex Mono. B: Schibsted Grotesk 700/800 + Hanken Grotesk 400–800 + JetBrains Mono. C2: Newsreader 600 + Hanken Grotesk 400–800 + IBM Plex Mono.

## Fixtures (all fictional)
₹899.00 fee + ₹161.82 GST − ₹100.00 discount = **₹960.82** (from integer paise 96082) · Wed, 5 Aug 2026 6:30–7:15 PM Asia/Kolkata (IST) · LS-TUT-20260805-0042 · pay_TEST_8f3k2Q · rfnd_TEST_2m9x1L · AUD-2026-000481 · Visa •••• 1111 masked. No PAN/CVV/OTP/join token/personal media in any fixture or annotation.
