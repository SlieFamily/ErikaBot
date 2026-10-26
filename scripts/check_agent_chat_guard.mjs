#!/usr/bin/env node
// Optional real-engine test. Uses installed DSH libraries, no shell tools or model calls.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {apply} from '../dsh/agent-chat/guard.mjs';

if (!process.argv[2]) throw new Error('Pass the installed DSH node_modules directory');
const require = createRequire(path.resolve(process.argv[2], '../agent-chat-probe.cjs'));
const load = name => import(pathToFileURL(require.resolve(name)).href);
const {Context} = await load('@deepseek-ai/cordis');
const {default: SystemPrompt, renderPrompt} = await load('@deepseek-ai/dsh-system-prompt');
const {apply: applyPersona} = await load('@deepseek-ai/dsh-persona');
const {default: Tools} = await load('@deepseek-ai/dsh-tools');
const {createScope} = await load('@deepseek-ai/dsh-scope');

const root = new Context();
new SystemPrompt(root, {});
new Tools(root, {mode: 'native'});
let invoked = 0;
const definition = name => ({
  name, description: 'In-memory canary; no external side effects',
  parameters: {type: 'object', properties: {}, additionalProperties: false},
  output: {schema: {type: 'string'}, render: value => [{type: 'text', text: value}]},
  execute() { invoked += 1; return 'ran'; }
});
root.tools.register(definition('global_canary'));
root.tools.register(definition('web_search'));
const agent = {id: 'agent-chat-guard-probe'};
const scope = createScope(root, agent);
root.systemPrompt.section({name: 'probe:host-identity', order: 100, text: 'Generic coding assistant'});
applyPersona(scope.ctx, {prefix: 'Dedicated QQ role and fixed protocol', complete: true, includeRuntimeContext: false});
const assembly = await scope.ctx.systemPrompt.assemble({scope: agent, agent, signal: new AbortController().signal});
assert.equal(renderPrompt(assembly), 'Dedicated QQ role and fixed protocol');
// The real registry and event system are used; only the provider configuration is inert.
apply({tools: scope.ctx.tools, on: scope.ctx.on.bind(scope.ctx),
  web: {config: {searchProvider: {get: () => 'anysearch'}}}});
agent.ctx = scope.ctx;
scope.ctx.emit('agent/created', {agent});
assert.equal(scope.ctx.tools.get('global_canary', agent), undefined);
assert.ok(scope.ctx.tools.get('web_search', agent));
const unauthorized = await scope.ctx.tools.execute({
  agent, name: 'web_search', callId: 'unpermitted-search', arguments: {queries: ['public topic']},
  signal: new AbortController().signal
});
assert.equal(unauthorized.isError, true);
assert.match(JSON.stringify(unauthorized), /search is not authorized/);
// Local tools bypass inherited-tool visibility masks, but MUST still hit the guard.
scope.ctx.tools.register(definition('local_canary'));
assert.ok(scope.ctx.tools.get('local_canary', agent));
for (const name of ['global_canary', 'local_canary', 'future_unknown_tool', 'run_code']) {
  const result = await scope.ctx.tools.execute({
    agent, name, callId: 'probe-' + name, arguments: {}, signal: new AbortController().signal
  });
  assert.equal(result.isError, true, name);
  assert.match(JSON.stringify(result), /only native AnySearch web_search is allowed/, name);
}
assert.equal(invoked, 0);
await scope.dispose();
console.log('PASS: installed DSH engine exposes only native search, denies unauthorized search and global/local/unknown/Code Mode execution; canary never ran');
console.log('PASS: complete persona excludes inherited system-prompt identity sections');
