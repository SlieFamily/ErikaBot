#!/usr/bin/env node
// Explicit administrator setup only. No shell calls, dependency installation or DSH restart.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

const bundleName = 'erika-agent-chat-dsh';
const source = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../dsh/agent-chat');
const files = ['package.json', 'guard.mjs', 'preset.patch.yml'];
const object = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

export function setup(profilePath, apply = false) {
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
  const contents = files.map(file => fs.readFileSync(path.join(source, file)));
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
  if (!apply) return {profile, target, hash, applied: false};

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
  return {profile, target, hash, applied: true, backup};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args[0] !== '--profile' || !args[1] || args.length > 3 || (args[2] && args[2] !== '--apply')) {
    console.error('Usage: node scripts/setup_agent_chat_dsh.mjs --profile <existing DSH profile directory> [--apply]');
    process.exitCode = 2;
  } else {
    try { console.log(JSON.stringify(setup(args[1], args[2] === '--apply'), null, 2)); }
    catch (error) { console.error(`Setup failed: ${error.message}`); process.exitCode = 1; }
  }
}
