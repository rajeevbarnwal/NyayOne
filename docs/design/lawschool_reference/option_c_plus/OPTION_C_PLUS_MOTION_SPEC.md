# Option C+ — Motion Spec (corrected)

Principle: calm, functional, zero decorative motion; nothing moves that carries meaning colour/shape/text doesn't already carry.

| Element | Motion | Duration / easing | Reduced-motion behaviour |
|---|---|---|---|
| Skeleton loaders | background-position shimmer | 1.2s linear infinite | **static** flat placeholder (`@media (prefers-reduced-motion: no-preference)` gate) |
| Removal spinner | rotate | 1s linear infinite | static ring + "Removing…" text (text carries state) |
| Pick-tray progress bar | width change on re-render | instant (no transition) | identical |
| Chip / button state | background & border colour swap | instant | identical |
| Refusal dialog | native `<dialog>` open/close | UA default (no custom animation) | identical |
| Route change (F1) | programmatic `scrollTo(0,0)` — instant jump, **not** smooth-scroll | instant | identical (no `behavior:smooth` anywhere) |
| `focusin` guard (F3) | `scrollBy` instant correction | instant | identical |
| Theme switch | token repaint | instant | identical |

Explicitly absent: parallax, scroll-linked effects, entrance animations, hover lifts/shadows, smooth scrolling, animated charts, the duplicate "shake" (Option A only — removed from the C family). The only looping animations are the two loaders above, both gated by `prefers-reduced-motion`.
