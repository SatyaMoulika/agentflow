/** Regenerate the API's checked-in templates from the frontend's shared registry. */
import { build } from 'esbuild';
import { writeFile } from 'node:fs/promises';
const { outputFiles } = await build({
  stdin: {
    contents: `import { fixtureWorkflows, fixtureIntegrations, defaultSettings } from './src/data/fixtures'; import { nodeRegistry } from './src/lib/node-registry'; export const seed = { workflows:fixtureWorkflows.map(w=>({...w,totalRuns:0,successRate:0,lastRun:undefined})), integrations:fixtureIntegrations.map(i=>({...i,connected:false,connectionName:undefined})), settings:defaultSettings, registry:Object.values(nodeRegistry).map(({type,name,category,description,color,defaultConfig,outputs,comingSoon})=>({type,name,category,description,color,defaultConfig,outputs,comingSoon})) };`,
    resolveDir: process.cwd(),
    loader: 'ts',
  },
  bundle: true,
  write: false,
  platform: 'node',
  format: 'esm',
  packages: 'external',
});
// A workspace-local temporary module resolves external packages through node_modules.
const { pathToFileURL } = await import('node:url');
const { unlink } = await import('node:fs/promises');
const temporary = new URL('../.agentflow-seed-export.mjs', import.meta.url);
try {
  await writeFile(temporary, outputFiles[0].text);
  const { seed } = await import(pathToFileURL(temporary.pathname).href);
  await writeFile(
    new URL('../backend/agentflow/seed.json', import.meta.url),
    JSON.stringify(seed, null, 2) + '\n',
  );
  console.log('Backend templates exported from frontend registry and fixtures.');
} finally {
  await unlink(temporary).catch(() => {});
}
