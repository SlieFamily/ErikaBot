import assert from 'node:assert/strict';
import test from 'node:test';
import {apply} from '../dsh/agent-chat/guard.mjs';

test('guard denies known, unknown, MCP and indirect execution capabilities', () => {
  let guard, filter;
  apply({tools: {guard: fn => {guard = fn;}, restrict: value => {filter = value;}}});
  assert.deepEqual(filter, {allow: []});
  for (const name of ['bash','pwsh','read','write','subagent','plugin_manager',
    'read_mcp_resource','mcp__filesystem__read_file','run_code','future_dangerous_tool','']) {
    assert.equal(typeof guard({name}), 'string', name);
  }
  assert.equal(typeof guard(), 'string');
});

test('unsupported or global restriction fails preset loading', () => {
  assert.throws(() => apply({tools: {}}));
  assert.throws(() => apply({tools: {guard() {}, restrict() {throw Error('unscoped');}}}), /unscoped/);
});
