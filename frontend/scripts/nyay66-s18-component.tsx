// Test-only actual presentation component. Production builds do not emit this route.
import { createRoot } from 'react-dom/client';
import { NotificationsSettingsView } from '../src/features/student/settings/NotificationsSettingsView';
import '../src/styles/global.css';
const forbidden = () => { throw Error('Component-only fixture cannot mutate or navigate'); };
createRoot(document.getElementById('root')!).render(
  <div className="ls-v34-content">
    <NotificationsSettingsView state={{ phase: 'session' }} onChange={forbidden} onReload={forbidden} onNavigate={forbidden}/>
  </div>,
);
