// Test-only entry. Never imported by the application or its production build.
// Render the actual presentation component, not a copied reference DOM.
import { createRoot } from 'react-dom/client';
import { S01R2 } from '../src/features/student/auth/S01R2';
import '../src/styles/global.css';

createRoot(document.getElementById('root')!).render(
  <S01R2 phase="authenticated" retry={() => { throw Error('Resolved fixture cannot retry'); }}/>,
);
