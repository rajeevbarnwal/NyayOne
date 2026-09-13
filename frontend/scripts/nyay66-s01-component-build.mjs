// Invoked separately inside the credential-free CI build container.
// Normal `npm run build` does not emit a component fixture route.
import {build} from 'vite';
import react from '@vitejs/plugin-react';
import {resolve} from 'node:path';
await build({configFile:false,root:resolve('.'),base:'/__nyay66-components/',plugins:[react()],build:{outDir:'dist/__nyay66-components',emptyOutDir:true,rollupOptions:{input:resolve('scripts/nyay66-s01-component.html')}}});
