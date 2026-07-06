# Self-hosted fonts (offline, no external requests)

Drop the following variable `.woff2` files here so `src/styles/fonts.css` can serve them
locally. **Do not** add Google Fonts `<link>` tags or any external font URL — fonts must
load only from this directory (offline / app-store safe).

| Family | File expected here | License |
|---|---|---|
| Hanken Grotesk | `HankenGrotesk-Variable.woff2` | SIL OFL 1.1 |
| Newsreader | `Newsreader-Variable.woff2` | SIL OFL 1.1 |
| JetBrains Mono | `JetBrainsMono-Variable.woff2` | SIL OFL 1.1 |

All three are OFL-licensed and may be self-hosted/redistributed. Obtain the `.woff2`
files from the official upstream repositories (or convert the OFL `.ttf`), then commit
them here.

**Deferred:** the binaries are not committed in this foundation change (they aren't
fetchable from the build sandbox). Until they are added, `@font-face` falls back to the
system font stacks defined in `src/styles/tokens.css` — the app still renders correctly
with **zero** external font requests.
