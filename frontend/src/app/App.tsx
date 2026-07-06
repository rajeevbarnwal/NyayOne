import { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './queryClient';
import { screenRoutes } from './screenRegistry';
import { useTheme } from '../hooks/useTheme';

// Route-level lazy loading. Screens share one placeholder component in the
// foundation stage; real per-screen modules replace this in later tickets.
const ScreenPlaceholder = lazy(() => import('../features/ScreenPlaceholder'));

function AppShell() {
  const { theme, toggleTheme } = useTheme();
  return (
    <div className="app-shell">
      <header className="app-topbar">
        <span className="brand">
          Legal<span className="brand-accent">Saathi</span>
        </span>
        <button
          type="button"
          className="theme-toggle"
          onClick={toggleTheme}
          aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
        >
          {theme === 'dark' ? 'Light' : 'Dark'}
        </button>
      </header>
      <main className="app-content">
        <Suspense fallback={<div className="route-loading">Loading…</div>}>
          <Routes>
            <Route path="/" element={<Navigate to={screenRoutes[0].path} replace />} />
            {screenRoutes.map((r) => (
              <Route key={r.id} path={r.path} element={<ScreenPlaceholder id={r.id} />} />
            ))}
            <Route path="*" element={<div className="route-loading">Not found</div>} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
