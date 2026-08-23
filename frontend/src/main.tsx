import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './app/App';
import { registerServiceWorker } from './lib/pwa';
import { purgeLegacyStudentSessionStorageAtBootstrap } from './features/student/lib/studentLegacyStorage';
import './styles/global.css';

// Run before React can mount. The private-session boundary repeats this purge
// and becomes unavailable if cleanup cannot be proven complete.
purgeLegacyStudentSessionStorageAtBootstrap();

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// PWA cache skeleton — registers only in production builds (no-op in dev/test).
registerServiceWorker();
