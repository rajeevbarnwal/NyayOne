import { Suspense, lazy } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './queryClient';
import { screenRoutes } from './screenRegistry';
import { AuthProvider, useDerivedAuth } from './authContext';
import { AppShell } from '../components/shell/AppShell';
import { useTheme } from '../hooks/useTheme';
import { studentScreens } from '../features/student/screens';
import { lawyerRoutes } from '../features/lawyer/screens';
import { LawyerGuard } from '../features/lawyer/CaseAuthGuard';
import { mentorRoutes } from '../features/mentor/screens';
import { MentorGuard } from '../features/mentor/MentorSessionScreens';
import { authRoutes } from '../features/auth/screens';
import { PublicCredentialVerification } from '../features/student/credentials/CredentialScreens';

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
              <LawyerGuard stage={r.stage}><Case /></LawyerGuard>
            ) : (
              <Case />
            );
            return <Route key={r.path} path={r.path} element={element} />;
          })}
          {/*
            Mentor / administrator routes (SAATHI-66, QA defect D2). The
            completion action lives here and only here; every route is wrapped in
            MentorGuard so no unauthorised actor mounts it.
          */}
          {mentorRoutes.map((r) => {
            const Mentor = r.Component;
            const element = r.guarded ? (
              <MentorGuard><Mentor /></MentorGuard>
            ) : (
              <Mentor />
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

function AppRoutes() {
  return (
    <Routes>
      <Route path="/verify/:token" element={<PublicVerificationRoute />} />
      <Route path="*" element={<ShellRoutes />} />
    </Routes>
  );
}

function PublicVerificationRoute() {
  // Apply the same stored/system theme tokens without rendering authenticated
  // navigation around the anonymous verification surface.
  useTheme();
  return <PublicCredentialVerification />;
}

export function App() {
  // Reactive auth: derives the live state from the persisted, secret-free lawyer
  // session snapshot and updates immediately on P0.1 create/update/clear/expiry.
  const auth = useDerivedAuth();
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider value={auth}>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
