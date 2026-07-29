# Motion & Reduced-Motion Spec

| Surface | Motion | Duration | Reduced-motion |
|---|---|---|---|
| Buttons/chips (B/C) | colour/border transition | 180ms ease | instant (gated) |
| Hold countdown | 1s text tick + announce at 2:00 | 1s | identical (text only) |
| Payment processing | spinner rotation | 1s linear loop | static ring + text |
| Synthetic tutor tile | canvas redraw (avatar + audio bars) | 250ms interval | single static frame |
| Route change | instant scroll-to-top + heading focus | instant | identical |
| Dialogs | native <dialog> | UA default | identical |
| Card hover (C) | none (no lift on payment surfaces) | — | — |

No autoplay media, no pulsing, no parallax, no confetti. All loops sit inside `prefers-reduced-motion: no-preference`.