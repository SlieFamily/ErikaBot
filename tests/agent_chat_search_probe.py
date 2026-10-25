"""Opt-in live search + DSH probe. Temporary state, isolated session, no QQ sends."""
import argparse
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_agent_chat import dsh, load_config, ROOT, package

ChatMessage = importlib.import_module(package.__name__ + '.domain').ChatMessage
ChatService = importlib.import_module(package.__name__ + '.service').ChatService
Store = importlib.import_module(package.__name__ + '.store').Store
BingSearch = importlib.import_module(package.__name__ + '.search').BingSearch


async def run(env_file):
    conf = load_config(private_file=env_file).copy(update={
        'agent_chat_enabled': True, 'agent_chat_groups': frozenset({42}), 'agent_chat_debounce': 0,
        'agent_chat_cooldown': 0, 'agent_chat_proactive_enabled': False,
        'agent_chat_search_enabled': True, 'agent_chat_forward_persona': True})
    key, prompts, replies, queries = '100:group:42', [], [], []
    async def send(text): replies.append(text)
    with tempfile.TemporaryDirectory() as folder:
        store = Store(Path(folder) / 'search-probe.sqlite3')
        client = dsh.DshClient(conf); backend = BingSearch(conf)
        original_reply, original_search = client.reply, backend.search
        async def record_reply(sid, text, images=None):
            prompts.append((sid, text))
            return await original_reply(sid, text, images)
        async def record_search(chat, query, focus=''):
            result = await original_search(chat, query, focus=focus)
            queries.append({'query': query, 'status': result['status'], 'results': len(result['results'])})
            return result
        client.reply, backend.search = record_reply, record_search
        service = ChatService(conf, store, client, backend)
        try:
            for i, question in enumerate(['晚上好绘梨花，今天打瓦被队友气笑了。',
                'VALORANT 最近发布的补丁公告是哪个版本？给我一句主要变化和来源。',
                'STEINS;GATE RE:BOOT 官网页面现在写的发售日是哪天？给我官网来源。']):
                msg = ChatMessage(key, f'public-probe-{i}', '7', '群友', question, time.time(), True)
                service.observe(msg); service.schedule(msg, send)
                await asyncio.gather(*list(service.tasks.values()))
                if i == 0 and (queries or len(prompts) != 1 or len(replies) != 1):
                    raise dsh.BridgeError('probe_smalltalk_not_single_turn')
            print(json.dumps({'searches': queries, 'model_turns': len(prompts),
                              'replies': replies}, ensure_ascii=False))
            bound = store.session(key)
            if not bound or bound[2] or len(queries) != 2 or any(q['status'] != 'ok' for q in queries):
                raise dsh.BridgeError('probe_search_not_completed')
            if len(prompts) != 5 or len(replies) != 3 or len({sid for sid, _ in prompts}) != 1:
                raise dsh.BridgeError('probe_continuation_failed')
            if any('agent_chat_search' in reply for reply in replies):
                raise dsh.BridgeError('probe_control_leak')
            if 'https://steinsgate.jp/' not in replies[-1]:
                raise dsh.BridgeError('probe_official_source_missing')
            print('PASS: smalltalk one turn; autonomous search + same-session digestion; no QQ sends')
        finally:
            try:
                bound = store.session(key)
                if bound: await client.stop(bound[0])
            finally: await service.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.agent_chat')
    parser.add_argument('--confirm-model-calls', action='store_true', required=True)
    args = parser.parse_args()
    try: asyncio.run(run(args.env_file))
    except dsh.BridgeError as error:
        print('FAIL: ' + str(error)); sys.exit(1)
    except Exception:
        print('FAIL: configuration_or_protocol_error'); sys.exit(1)
