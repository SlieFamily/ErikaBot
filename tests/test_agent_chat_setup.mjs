import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {setup} from '../scripts/setup_agent_chat_dsh.mjs';

function fixture(t) {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'erika-agent-chat-test-'));
  t.after(() => fs.rmSync(folder, {recursive: true, force: true}));
  fs.writeFileSync(path.join(folder, 'package.json'), JSON.stringify({
    name: 'test', dependencies: {existing: '1.0.0'}, dsh: {profile: {bundles: ['existing']}}
  }));
  return folder;
}

test('setup dry-run is read-only, preserves existing settings and is idempotent', t => {
  const folder = fixture(t);
  assert.equal(setup(folder).applied, false);
  assert.deepEqual(fs.readdirSync(folder), ['package.json']);
  const first = setup(folder, true);
  assert.ok(first.backup);
  const pkg = JSON.parse(fs.readFileSync(path.join(folder, 'package.json')));
  assert.equal(pkg.dependencies.existing, '1.0.0');
  assert.deepEqual(pkg.dsh.profile.bundles, ['existing', 'erika-agent-chat-dsh']);
  assert.equal(fs.realpathSync(path.join(folder, 'node_modules/erika-agent-chat-dsh')), first.target);
  assert.equal(setup(folder, true).backup, null);
  fs.writeFileSync(path.join(first.target, 'guard.mjs'), '// modified');
  assert.throws(() => setup(folder, true), /modified/);
});

test('setup refuses an unrelated directory at its module link', t => {
  const folder = fixture(t);
  fs.mkdirSync(path.join(folder, 'node_modules/erika-agent-chat-dsh'), {recursive: true});
  assert.throws(() => setup(folder, true), /not a link/);
});
