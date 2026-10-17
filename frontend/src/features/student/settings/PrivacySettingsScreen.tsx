import { useNavigate } from 'react-router-dom';
import { PrivacySettingsView } from './PrivacySettingsView';
import { usePrivacySettings } from './usePrivacySettings';

export function PrivacySettingsScreen() {
  const nav = useNavigate();
  const { preferences: p, exportFlow: e, deletion: d } = usePrivacySettings();
  return <PrivacySettingsView state={p.state} exportState={e.state} deletion={d.state}
    onNavigate={nav} onChange={p.change} onReload={p.reload}
    onExport={e.request} onCheckExport={e.check} onDismissExport={e.dismiss}
    onDeleteOpen={() => { if (p.state.phase !== 'saving') d.openDelete(); }} onDeleteClose={d.closeDelete}
    onMobile={v => d.edit('mobile', v)} onCode={v => d.edit('code', v)} onTyped={v => d.edit('typed', v)}
    onSend={() => d.recover('send')} onVerify={() => d.recover('verify')} onDelete={d.remove} onStartAgain={d.startAgain}/>
}
