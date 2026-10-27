"""Inspect or explicitly switch existing bridge sessions via DSH's native API.

Defaults to read-only. Does not prompt the model, cancel work, send QQ messages,
change presets, modify the bridge database or automatically lift a suspension.
"""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import sqlite3
import sys
import time
import uuid

from check_agent_chat import ROOT, dsh, load_config

TABLES = (('sessions', 'chat'), ('knowledge_learning_state', 'slang'), ('memory_learning_state', 'memory'))


def read_bindings(path):
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        result = []
        for table, family in TABLES:
            paused = 'suspended' if family == 'chat' else '0'
            for key, sid, policy, suspended in db.execute(
                f'SELECT chat_key,session_id,policy,{paused} FROM {table} WHERE session_id IS NOT NULL'
            ):
                result.append(dict(family=family, chat=key, sid=sid, policy=policy, suspended=bool(suspended)))
        return sorted(result, key=lambda row: (row['family'], row['chat']))


def matches(selection, target):
    return isinstance(selection, dict) and all(selection.get(k) == v for k, v in target.items())


async def archived_sessions(client):
    async def read():
        await client.authenticate()
        stream = str(uuid.uuid4())
        async with client.connect(
            client.cfg.agent_chat_dsh_url.replace('http', 'ws', 1) + '/api/remote.mux',
            extra_headers={'Cookie': client.cookie}, open_timeout=10, close_timeout=2, max_size=2_000_000,
        ) as ws:
            await ws.send(json.dumps(dict(type='open', streamId=stream, endpoint='workspace/follow', payload={'args': {}})))
            async for raw in ws:
                frame = client.frame(raw, stream)
                if frame and frame.get('type') == 'baseline':
                    ids = frame.get('value', {}).get('archivedSessionIds')
                    if not isinstance(ids, list) or not all(isinstance(s, str) for s in ids):
                        raise dsh.BridgeError('invalid_archive_baseline')
                    return set(ids)
        raise dsh.BridgeError('archive_baseline_missing')
    return await asyncio.wait_for(read(), 15)


def validate_target(catalog, target):
    model = next((m for g in catalog.get('groups', []) if g.get('id') == target['provider']
                  for m in g.get('models', []) if m.get('id') == target['model']), None)
    if model is None:
        raise dsh.BridgeError('target_model_not_available')
    effort = target.get('reasoningEffort')
    if effort and not any(e.get('id') == effort for e in model.get('reasoning', {}).get('efforts', [])):
        raise dsh.BridgeError('target_reasoning_effort_not_available')


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    # The report contains selection metadata only, never API keys or message text.
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    temp.replace(path)


async def switch_bound(clients, bindings, archived, target, apply=False, report_path=None):
    chat = clients['chat']
    before = bindings()
    initial_catalog = await chat.rpc('session/modelCatalog')
    initial_default = {k: initial_catalog.get('default', {}).get(k) for k in ('provider', 'model', 'reasoningEffort')}
    report = dict(created=time.time(), target=target, apply=apply, default_before=initial_default, bindings_before=before, sessions=[])
    if apply:
        if report_path is None or report_path.exists():
            raise dsh.BridgeError('report_path_missing_or_exists')
        save_report(report_path, report)
    for row in before:
        entry = dict(family=row['family'], chat=row['chat'], sid=row['sid'], suspended=row['suspended'])
        report['sessions'].append(entry)
        client = clients[row['family']]
        try:
            if row not in bindings():
                raise dsh.BridgeError('binding_changed')
            if row['sid'] in archived:
                raise dsh.BridgeError('bound_session_archived')
            v = (await chat.rpc('session/projections', {'sessionId': row['sid']})).get('values', {})
            current = v.get('modelSelection', {}).get('next', {})
            entry['before'] = {k: current[k] for k in ('provider', 'model', 'reasoningEffort') if k in current}
            if not target:
                entry['status'] = 'status'
                continue
            if matches(current, target):
                entry['status'] = 'already_selected'
                continue
            items = (await chat.rpc('session/list')).get('items', [])
            item = next((i for i in items if i.get('sessionId') == row['sid']), None)
            if item is None:
                raise dsh.BridgeError('dsh_session_missing')
            if item.get('running') or any(v.get('inbox', {}).get(k) != [] for k in ('next-turn', 'next-step')):
                raise dsh.BridgeError('session_busy')
            await client.recovery_checkpoint(row['sid'])
            if row not in bindings():
                raise dsh.BridgeError('binding_changed')
            if apply:
                # Persist rollback metadata before every native mutation.
                entry['status'] = 'selecting'
                save_report(report_path, report)
                result = await chat.rpc('session/selectModel', {'sessionId': row['sid'], **target})
                after = (await chat.rpc('session/projections', {'sessionId': row['sid']})).get('values', {}).get('modelSelection', {}).get('next')
                if not matches(result.get('selected'), target) or not matches(after, target):
                    raise dsh.BridgeError('selection_not_confirmed')
                entry['status'] = 'selected'
            else:
                entry['status'] = 'ready'
        except dsh.BridgeError as error:
            entry.update(status='skipped', reason=str(error))
        finally:
            if apply:
                save_report(report_path, report)
    report['bindings_preserved'] = before == bindings()
    catalog = await chat.rpc('session/modelCatalog')
    report['default'] = {k: catalog.get('default', {}).get(k) for k in ('provider', 'model', 'reasoningEffort')}
    # Selecting an already-selected session also saves the deployment default.
    # If no switch was needed, align the default only through an audited idle binding.
    if apply and not matches(report['default'], target):
        eligible = next((r for r in report['sessions'] if r['status'] in ('selected', 'already_selected')), None)
        if eligible:
            try:
                if not any(r['sid'] == eligible['sid'] for r in bindings()):
                    raise dsh.BridgeError('binding_changed')
                await clients[eligible['family']].recovery_checkpoint(eligible['sid'])
                await chat.rpc('session/selectModel', {'sessionId': eligible['sid'], **target})
                catalog = await chat.rpc('session/modelCatalog')
                report['default'] = {k: catalog.get('default', {}).get(k) for k in ('provider', 'model', 'reasoningEffort')}
            except dsh.BridgeError as error:
                report['default_error'] = str(error)
    report['bindings_preserved'] = before == bindings()
    report['complete'] = (report['bindings_preserved'] and
        all(r['status'] in ('status', 'ready', 'selected', 'already_selected') for r in report['sessions']) and
        (not apply or matches(report['default'], target)))
    if apply:
        save_report(report_path, report)
    return report


async def main(args):
    cfg = load_config(private_file=args.env_file)
    if args.apply and (cfg.agent_chat_provider or cfg.agent_chat_model):
        raise dsh.BridgeError('bridge_model_pinned_use_dsh_selection_workflow')
    target = dict(provider=args.provider, model=args.model) if args.provider else None
    if args.reasoning_effort:
        target['reasoningEffort'] = args.reasoning_effort
    path = cfg.agent_chat_state_path
    if not path.is_absolute():
        path = ROOT / path
    chat = dsh.DshClient(cfg)
    learner = dsh.DshClient(cfg, preset_id=dsh.LEARNER_PRESET_ID)
    try:
        catalog = await chat.rpc('session/modelCatalog')
        if not target:
            print('可选模型（provider / model）：')
            for group in catalog.get('groups', []):
                for model in group.get('models', []):
                    print(' ', group['id'], '/', model['id'])
        else:
            validate_target(catalog, target)
        print('DSH 当前默认：', {k: catalog.get('default', {}).get(k) for k in ('provider', 'model', 'reasoningEffort')})
        report_path = ROOT / 'data/agent_chat/model-switches' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json')
        report = await switch_bound({'chat': chat, 'slang': learner, 'memory': learner},
            lambda: read_bindings(path), await archived_sessions(chat), target, args.apply, report_path)
        for row in report['sessions']:
            print(row['family'], row['chat'].split(':')[-1], row['sid'],
                  row.get('before', {}), '暂停=' + str(row['suspended']), row['status'], row.get('reason', ''))
        print('绑定及暂停状态保持：', report['bindings_preserved'], '；默认模型：', report['default'])
        if args.apply:
            print('切换记录：', report_path)
        print('全部完成。' if report['complete'] else '有会话未完成；等待忙碌回合结束或处理错误后重跑同一命令。')
        print('本命令不测试模型回答质量，不解除暂停，不重发旧消息。')
        return 0 if report['complete'] else 2
    finally:
        await chat.close()
        await learner.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.agent_chat')
    parser.add_argument('--provider')
    parser.add_argument('--model')
    parser.add_argument('--reasoning-effort')
    parser.add_argument('--apply', action='store_true', help='明确执行切换；不加此项只检查')
    args = parser.parse_args()
    if bool(args.provider) != bool(args.model) or (args.apply or args.reasoning_effort) and not args.provider:
        parser.error('--provider 和 --model 必须一起填写，执行切换必须明确目标')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    try:
        sys.exit(asyncio.run(main(args)))
    except dsh.BridgeError as error:
        print('未完成：', str(error)); sys.exit(2)
    except Exception as error:
        print('未完成：本地配置或连接检查失败（' + type(error).__name__ + '）；未自动重试。'); sys.exit(2)
