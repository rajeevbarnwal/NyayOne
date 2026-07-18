import { Suspense, lazy, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './queryClient';
import { screenRoutes } from './screenRegistry';
import { AuthProvider, deriveAuthState } from './authContext';
import { AppShell } from '../components/shell/AppShell';
import { useTheme } from '../hooks/useTheme';
import { studentScreens } from '../features/student/screens';
import { lawyerRoutes } from '../features/lawyer/screens';
import { LawyerGuard } from '../features/lawyer/CaseAuthGuard';
import { authRoutes } from '../features/auth/screens';

// Route-level lazy loading. Screens share one placeholder component in the
// foundation stage; implemented S-01..S-19 screens (student module) render
// their real component via the studentScreens registry.
const ScreenPlaceholder = lazy(() => import('../features/ScreenPlaceholder'));
// Internal token/theme verification route (not part of the S-01..S-99 registry).
const TokenShowcase = lazy(() => import('../features/TokenShowcase'));

function ShellRoutes() {
  const { theme, toggleTheme } = useTheme();
  return (
    <AppShell theme={theme} toggleTheme={toggleTheme}>
      <Suspense fallback={<div className="route-loading">Loading…</div>}>
        <Routes>
          <Route path="/" element={<Navigate to="/s-03" replace />} />
          <Route path="/__tokens" element={<TokenShowcase theme={theme} toggleTheme={toggleTheme} />} />
          {screenRoutes.map((r) => {
            const Screen = studentScreens[r.id];
            return (
              <Route
                key={r.id}
                path={r.path}
                element={Screen ? <Screen theme={theme} toggleTheme={toggleTheme} /> : <ScreenPlaceholder id={r.id} />}
              />
            );
          })}
          {lawyerRoutes.map((r) => {
            const Case = r.Component;
            const element = r.guarded ? (
              <LawyerGuard><Case /></LawyerGuard>
            ) : (
              <Case />
            );
            return <Route key={r.path} path={r.path} element={element} />;
          })}
          {authRoutes.map((r) => {
            const Auth = r.Component;
            return <Route key={r.path} path={r.path} element={<Auth />} />;
          })}
          <Route path="*" element={<div className="route-loading">Not found</div>} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}

export function App() {
  // Derive the live auth state from the persisted, secret-free lawyer session
  // snapshot (anonymous when none / expired). Read once at mount; changing
  // identity requires a re-auth + reload, matching the server-authoritative model.
  const [auth] = useState(() => deriveAuthState());
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider value={auth}>
        <BrowserRouter>
          <ShellRoutes />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
