import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './app/App';
import { registerServiceWorker } from './lib/pwa';
import './styles/global.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// PWA cache skeleton — registers only in production builds (no-op in dev/test).
registerServiceWorker();
