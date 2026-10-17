// Test-only actual presentation. Normal production builds do not emit this route.
import { createRoot } from 'react-dom/client';
import { PrivacySettingsView } from '../src/features/student/settings/PrivacySettingsView';
import '../src/styles/global.css';
const forbidden = () => { throw Error('Component-only fixture cannot mutate or navigate'); };
createRoot(document.getElementById('root')!).render(<div className="ls-v34-content">
  <PrivacySettingsView state={{phase:'session'}} exportState={{phase:'idle'}}
    deletion={{stage:'closed',mobile:'',code:'',typed:'',busy:false,authorityReady:false}}
    onNavigate={forbidden} onChange={forbidden} onReload={forbidden} onExport={forbidden}
    onCheckExport={forbidden} onDismissExport={forbidden} onDeleteOpen={forbidden} onDeleteClose={forbidden}
    onMobile={forbidden} onCode={forbidden} onTyped={forbidden} onSend={forbidden} onVerify={forbidden}
    onDelete={forbidden} onStartAgain={forbidden}/>
</div>);
