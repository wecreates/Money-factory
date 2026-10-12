// Private companion process. The existing Content Control renderer stays canonical.
import {resolve} from 'node:path';
import {createApp} from './vendor/toonflow-app/apps/server/src/app';
import config from './vendor/toonflow-app/electrobun.config';

const root = resolve(import.meta.dirname, 'vendor/toonflow-app');
if (!process.env.TOONFLOW_DATA_DIR) throw new Error('TOONFLOW_DATA_DIR must point to persistent worker storage');
const app = await createApp({
  appVersion: config.app.version,
  webRoot: resolve(root, 'build/web'),
  dataDirectory: resolve(process.env.TOONFLOW_DATA_DIR),
  toolsRoot: resolve(root, 'build/tools'),
  nodesRoot: resolve(root, 'build/nodes'),
  extRoot: resolve(root, 'build/ext'),
  providersRoot: resolve(root, 'packages/providers/src'),
  skillsRoot: resolve(root, 'packages/skills'),
});
app.listen(3000, '127.0.0.1', () => console.log('Toonflow private worker listening on 127.0.0.1:3000'));
