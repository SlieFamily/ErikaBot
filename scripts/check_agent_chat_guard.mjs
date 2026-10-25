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
const {default: SystemPrompt} = await load('@deepseek-ai/dsh-system-prompt');
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
const agent = {id: 'agent-chat-guard-probe'};
const scope = createScope(root, agent);
apply(scope.ctx);
assert.equal(scope.ctx.tools.get('global_canary', agent), undefined);
// Local tools bypass inherited-tool visibility masks, but MUST still hit the guard.
scope.ctx.tools.register(definition('local_canary'));
assert.ok(scope.ctx.tools.get('local_canary', agent));
for (const name of ['global_canary', 'local_canary', 'future_unknown_tool', 'run_code']) {
  const result = await scope.ctx.tools.execute({
    agent, name, callId: 'probe-' + name, arguments: {}, signal: new AbortController().signal
  });
  assert.equal(result.isError, true, name);
  assert.match(JSON.stringify(result), /tool execution is disabled/, name);
}
assert.equal(invoked, 0);
await scope.dispose();
console.log('PASS: installed DSH engine hides inherited tools and denies global/local/unknown/Code Mode execution; canary never ran');
