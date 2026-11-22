/** One isolated text-only Ruflo agent. Launched only by local_batch.py. */
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';
const job = JSON.parse(readFileSync(0, 'utf8'));
const endpoint = new URL(job.endpoint);
if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1' || endpoint.username || endpoint.password || endpoint.search || endpoint.hash || endpoint.pathname !== '/') throw Error('Loopback endpoint required');
const nativeFetch = globalThis.fetch;
let calls = 0;
globalThis.fetch = async (resource, options) => {
  const url = new URL(typeof resource === 'string' || resource instanceof URL ? resource : resource.url);
  if (url.href !== new URL('/v1/chat/completions', endpoint).href || options?.method !== 'POST' || ++calls > 1) throw Error('Only one local inference request is allowed');
  return nativeFetch(resource, {...options, redirect: 'error'});
};
process.env.RUFLO_PROVIDER = 'ollama';
process.env.OLLAMA_BASE_URL = endpoint.origin;
const packageRoot = join(job.runtime, 'node_modules/@claude-flow/cli');
if (JSON.parse(readFileSync(join(packageRoot, 'package.json'))).version !== '3.56.7') throw Error('Expected pinned @claude-flow/cli 3.56.7');
const { agentTools } = await import(pathToFileURL(join(packageRoot, 'dist/src/mcp-tools/agent-tools.js')));
const { executeAgentTask } = await import(pathToFileURL(join(packageRoot, 'dist/src/mcp-tools/agent-execute-core.js')));
const spawned = await agentTools.find(x => x.name === 'agent_spawn').handler({agentId: job.id, agentType: 'researcher', config: {provider: 'ollama', model: job.model}});
if (!spawned.success) throw Error('Ruflo registration failed');
const result = await executeAgentTask({agentId: job.id, prompt: job.prompt,
  systemPrompt: 'You are a text-only production planning assistant. Return the requested text. You have no tools, file access, or publishing authority. Never claim actions have been executed.',
  maxTokens: job.max_tokens, temperature: 0, timeoutMs: job.timeout_seconds * 1000});
const state = JSON.parse(readFileSync('.claude-flow/agents/store.json', 'utf8')).agents[job.id];
const completed = result.success === true && result.model === job.model && Number.isInteger(result.usage?.outputTokens) && result.usage.outputTokens > 0 && typeof result.output === 'string' && result.output.trim().length > 0 && calls === 1 && state.taskCount === 1 && state.status === 'idle';
process.stdout.write('\nCYZOR_RESULT=' + JSON.stringify({status: completed ? 'PASS' : 'FAIL', id: job.id,
  model: result.model, output: result.output, usage: result.usage, duration_ms: result.durationMs,
  inference_requests: calls, task_count: state.taskCount, error: completed ? undefined : result.error || 'Execution evidence incomplete',
  publication_enabled: false, scope: 'One text-only inference; not autonomous code execution or creative approval'}) + '\n');
process.exitCode = completed ? 0 : 2;
