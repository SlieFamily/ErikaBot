import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {setup, renderPreset, defaultRole} from '../scripts/setup_agent_chat_dsh.mjs';

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
  assert.equal(first.roleFile, fs.realpathSync(defaultRole));
  const preset = fs.readFileSync(path.join(first.target, 'preset.patch.yml'), 'utf8');
  const card = fs.readFileSync(defaultRole, 'utf8').replace(/\r\n?/g, '\n').trim();
  assert.ok(preset.includes(card.split('\n').map(line => '                ' + line).join('\n')));
  assert.ok(!preset.includes('__AGENT_CHAT_ROLE_CARD__'));
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

test('selecting or editing a role creates a new immutable preset while preserving the old one', t => {
  const folder = fixture(t);
  const roleFile = path.join(folder, 'custom role.md');
  fs.writeFileSync(roleFile, '# Custom role\nConcise and curious.');
  const first = setup(folder, true, roleFile);
  const previous = fs.readFileSync(path.join(first.target, 'preset.patch.yml'));
  fs.writeFileSync(roleFile, '# Custom role\nWarm and thoughtful.');
  const preview = setup(folder, false, roleFile);
  assert.notEqual(preview.hash, first.hash);
  assert.equal(fs.realpathSync(path.join(folder, 'node_modules/erika-agent-chat-dsh')), first.target);
  const second = setup(folder, true, roleFile);
  assert.equal(second.hash, preview.hash);
  assert.ok(fs.readFileSync(path.join(first.target, 'preset.patch.yml')).equals(previous));
  assert.ok(fs.readFileSync(path.join(first.target, 'guard.mjs')).equals(
    fs.readFileSync(path.join(second.target, 'guard.mjs'))));
  const script = fileURLToPath(new URL('../scripts/setup_agent_chat_dsh.mjs', import.meta.url));
  const result = JSON.parse(execFileSync(process.execPath,
    [script, '--role', roleFile, '--profile', folder], {encoding: 'utf8'}));
  assert.equal(result.hash, second.hash);
  assert.equal(result.applied, false);
});

test('invalid role files fail before modifying the profile', t => {
  const folder = fixture(t);
  const roleFile = path.join(folder, 'role.md');
  const original = fs.readFileSync(path.join(folder, 'package.json'));
  for (const bad of ['', '{{ process.env.SECRET }}', 'a'.repeat(12001), 'hello\u0000', Buffer.from([0xff])]) {
    fs.writeFileSync(roleFile, bad);
    assert.throws(() => setup(folder, true, roleFile));
    assert.ok(fs.readFileSync(path.join(folder, 'package.json')).equals(original));
    assert.ok(!fs.existsSync(path.join(folder, '.agent-chat')));
  }
  assert.throws(() => renderPreset('no marker', 'hello'), /marker/);
});
