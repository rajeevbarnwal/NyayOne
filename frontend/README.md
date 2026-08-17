# NyayOne Frontend

Responsive React app for desktop web, mobile web, and future native iOS/Android packaging through Capacitor.

## Key Choices

- React + TypeScript + Vite for the web app.
- Capacitor for native iOS and Android wrappers.
- Keep app logic shared; platform-specific code should live under `src/platform/`.
- Prefer responsive components over separate mobile and desktop screens.

## Structure

```text
src/
  app/          App shell, routing, providers
  assets/       Static frontend assets
  components/   Reusable UI components
  features/     Product workflows by domain
  hooks/        Shared React hooks
  lib/          API clients, utilities, helpers
  platform/     Capacitor/native bridge helpers
  styles/       Global styles and tokens
```

## Local Run (host dev port 1130)

```bash
cd frontend
npm ci
npm run dev -- --port 1130  # http://localhost:1130
npm run build      # tsc + vite production build
npm test           # vitest smoke tests
```

- Server state uses TanStack Query (`src/app/queryClient.ts`).
- Routing is lazy-loaded against the canonical v3.2 screen registry `S-01…S-99` (`src/app/screenRegistry.ts`).
- Dark/light theme is driven by `useTheme` (`src/hooks/useTheme.ts`), persisted to `localStorage["ls-theme"]`, applied via `[data-theme]` + CSS-variable tokens in `styles/global.css`.
