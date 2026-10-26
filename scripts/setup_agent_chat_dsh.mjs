#!/usr/bin/env node
// Explicit administrator setup only. No shell calls, dependency installation or DSH restart.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

const bundleName = 'erika-agent-chat-dsh';
const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../dsh/agent-chat');
export const defaultRole = path.resolve(source, '../../roles/古户绘梨花.md');
const roleMarker = '                __AGENT_CHAT_ROLE_CARD__';
const files = ['package.json', 'guard.mjs', 'knowledge.mjs', 'preset.patch.yml', 'learner.patch.yml'];
const object = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

export function renderPreset(template, role) {
  // YAML treats NEL and Unicode separators as line breaks too. Normalize before indenting.
  const text = role.replace(/^\uFEFF/, '').replace(/\r\n?|\u0085|\u2028|\u2029/g, '\n').trim();
  if (!text || text.length > 12000) throw new Error('Role card must contain 1..12000 characters');
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]/.test(text)) {
    throw new Error('Role card contains unsupported control characters');
  }
  if (text.includes('{{')) throw new Error('Role card must be plain text, without DSH template expressions');
  const lines = template.replace(/\r\n?/g, '\n').split('\n');
  if (lines.filter(line => line === roleMarker).length !== 1) throw new Error('Invalid role template marker');
  // Every line stays inside the fixed YAML literal scalar. Never interpret role content as YAML.
  return lines.flatMap(line => line === roleMarker
    ? text.split('\n').map(part => '                ' + part) : [line]).join('\n');
}

export function setup(profilePath, apply = false, rolePath = defaultRole) {
  const profile = fs.realpathSync(profilePath);
  const packageFile = path.join(profile, 'package.json');
  const original = fs.readFileSync(packageFile, 'utf8');
  const pkg = JSON.parse(original.replace(/^\uFEFF/, ''));
  if (!object(pkg) || (pkg.dependencies !== undefined && !object(pkg.dependencies)) ||
      (pkg.dsh !== undefined && !object(pkg.dsh)) ||
      (pkg.dsh?.profile !== undefined && !object(pkg.dsh.profile)) ||
      (pkg.dsh?.profile?.bundles !== undefined && !Array.isArray(pkg.dsh.profile.bundles))) {
    throw new Error('Unrecognized profile package shape; refusing to replace existing settings');
  }
  const roleFile = fs.realpathSync(rolePath);
  const roleStat = fs.statSync(roleFile);
  if (!roleStat.isFile() || roleStat.size > 65536) throw new Error('Role card must be a UTF-8 file smaller than 64 KiB');
  const role = new TextDecoder('utf-8', {fatal: true}).decode(fs.readFileSync(roleFile));
  const contents = files.map(file => file === 'preset.patch.yml'
    ? Buffer.from(renderPreset(fs.readFileSync(path.join(source, file), 'utf8'), role), 'utf8')
    : fs.readFileSync(path.join(source, file)));
  const digest = crypto.createHash('sha256');
  files.forEach((file, i) => digest.update(file).update('\0').update(contents[i]));
  const hash = digest.digest('hex');
  const ownedRoot = path.join(profile, '.agent-chat', 'bundles');
  const target = path.join(ownedRoot, hash);
  const link = path.join(profile, 'node_modules', bundleName);
  const expected = `link:${target.replaceAll('\\', '/')}`;
  const isOwned = candidate => {
    const rel = path.relative(ownedRoot, candidate);
    return /^[a-f0-9]{64}$/.test(rel);
  };
  const previous = pkg.dependencies?.[bundleName];
  if (previous && previous !== expected && !(previous.startsWith('link:') && isOwned(previous.slice(5)))) {
    throw new Error('Conflicting bundle dependency; refusing to overwrite');
  }
  let oldLink = null;
  try {
    const stat = fs.lstatSync(link);
    if (!stat.isSymbolicLink()) throw new Error('Bundle path exists and is not a link; refusing to overwrite');
    oldLink = path.resolve(path.dirname(link), fs.readlinkSync(link));
    if (oldLink !== target && !isOwned(oldLink)) throw new Error('Bundle link belongs to another installation');
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  // Content-addressed copies keep branch switches from silently changing the live guard.
  if (fs.existsSync(target)) {
    files.forEach((file, i) => {
      if (!fs.readFileSync(path.join(target, file)).equals(contents[i])) {
        throw new Error('Installed bundle content was modified; refusing to reuse');
      }
    });
  }
  pkg.dependencies ??= {};
  pkg.dependencies[bundleName] = expected;
  pkg.dsh ??= {}; pkg.dsh.profile ??= {}; pkg.dsh.profile.bundles ??= [];
  if (!pkg.dsh.profile.bundles.includes(bundleName)) pkg.dsh.profile.bundles.push(bundleName);
  const updated = JSON.stringify(pkg, null, 2) + '\n';
  if (!apply) return {profile, roleFile, target, hash, applied: false};

  let backup = null;
  if (updated !== original) {
    backup = packageFile + `.agent-chat-${Date.now()}.bak`;
    fs.writeFileSync(backup, original, {flag: 'wx', mode: 0o600});
  }
  fs.mkdirSync(target, {recursive: true});
  files.forEach((file, i) => {
    const destination = path.join(target, file);
    if (!fs.existsSync(destination)) fs.writeFileSync(destination, contents[i], {flag: 'wx'});
  });
  fs.mkdirSync(path.dirname(link), {recursive: true});
  if (oldLink !== target) {
    if (oldLink !== null) fs.unlinkSync(link); // Only the previously verified link, never its directory.
    fs.symlinkSync(target, link, process.platform === 'win32' ? 'junction' : 'dir');
  }
  if (updated !== original) {
    const temporary = packageFile + `.agent-chat-${crypto.randomUUID()}.tmp`;
    fs.writeFileSync(temporary, updated, {flag: 'wx', mode: 0o600});
    fs.renameSync(temporary, packageFile);
  }
  return {profile, roleFile, target, hash, applied: true, backup};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  try {
    const options = {};
    for (let i = 0; i < args.length; i++) {
      const arg = args[i];
      if (!['--profile', '--role', '--apply'].includes(arg) || Object.hasOwn(options, arg)) {
        throw new Error('Unknown or duplicate option');
      }
      if (arg === '--apply') options[arg] = true;
      else {
        if (!args[i + 1] || args[i + 1].startsWith('--')) throw new Error('Missing option value');
        options[arg] = args[++i];
      }
    }
    if (!options['--profile']) throw new Error('Missing --profile');
    console.log(JSON.stringify(setup(options['--profile'], !!options['--apply'], options['--role']), null, 2));
  } catch (error) {
    console.error(`Setup failed: ${error.message}`);
    console.error('Usage: node scripts/setup_agent_chat_dsh.mjs --profile <existing DSH profile directory> [--role <UTF-8 Markdown file>] [--apply]');
    process.exitCode = 1;
  }
}
