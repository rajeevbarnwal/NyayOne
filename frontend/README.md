# LegalSaathi Frontend

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
