import { useNavigate } from 'react-router-dom';
import { NotificationsSettingsView } from './NotificationsSettingsView';
import { useNotificationSettings } from './useNotificationSettings';
import { PrivacySettingsScreen } from './PrivacySettingsScreen';

export function NotificationsSettings() {
  const nav = useNavigate();
  const { state, change, reload } = useNotificationSettings();
  return <NotificationsSettingsView state={state} onChange={patch => { void change(patch); }} onReload={() => { void reload(); }} onNavigate={nav} />;
}

/** S-19: isolated, server-confirmed privacy controller and focused substates. */
export function PrivacySettings() {
  return <PrivacySettingsScreen/>;
}
