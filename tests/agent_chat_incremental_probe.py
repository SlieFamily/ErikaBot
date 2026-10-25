"""Opt-in production-service probe: three paid turns, temporary state, no QQ sends."""
import argparse
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_agent_chat import dsh, load_config, ROOT, package

ChatMessage = importlib.import_module(package.__name__ + '.domain').ChatMessage
ChatService = importlib.import_module(package.__name__ + '.service').ChatService
Store = importlib.import_module(package.__name__ + '.store').Store


async def run(env_file):
    conf = load_config(private_file=env_file).copy(update={
        'agent_chat_groups': frozenset({42}), 'agent_chat_debounce': 0,
        'agent_chat_cooldown': 0, 'agent_chat_proactive_enabled': False,
        'agent_chat_forward_persona': True,
    })
    secret = str(100000 + uuid.uuid4().int % 900000)
    prompts, replies = [], []
    key = '100:group:42'
    async def send(text): replies.append(text)

    def make_client():
        client = dsh.DshClient(conf)
        original = client.reply
        async def record(sid, text, images=None):
            prompts.append(text)
            return await original(sid, text, images)
        client.reply = record
        return client

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'probe.sqlite3'
        store = Store(path); client = make_client()
        service = ChatService(conf, store, client)
        try:
            questions = [
                f'今晚开瓦，房间号是 {secret}，你来不来？',
                '你爹bxslj跟斯莱是同一个人吧？你还想他？',
                '我刚才开的瓦房间号是多少？发下数字，我切出去忘了。',
            ]
            sid = None
            for i, question in enumerate(questions):
                if i == 2:
                    await service.close()
                    store = Store(path); client = make_client()
                    service = ChatService(conf, store, client)
                message = ChatMessage(key, f'probe-{i}', '7', '群友', question, time.time(), True)
                service.observe(message); service.schedule(message, send)
                await asyncio.gather(*list(service.tasks.values()))
                bound = store.session(key)
                if not bound or bound[2] or len(replies) != i + 1:
                    raise dsh.BridgeError('incremental_probe_turn_failed')
                if sid and bound[0] != sid:
                    raise dsh.BridgeError('incremental_probe_session_changed')
                sid = bound[0]
            print(json.dumps({'prompt_characters': [len(p) for p in prompts],
                              'replies': replies}, ensure_ascii=False))
            if secret not in replies[2] or secret in prompts[2]:
                raise dsh.BridgeError('incremental_probe_memory_failed')
            _, persona = await client.policy_with_persona()
            if persona not in prompts[0] or any(persona in text for text in prompts[1:]):
                raise dsh.BridgeError('incremental_probe_role_repeated')
            if any('"message_id": "probe-0"' in text for text in prompts[1:]):
                raise dsh.BridgeError('incremental_probe_history_repeated')
            print('PASS: one role seed; incremental chat; fresh Python client/store retain DSH memory; no QQ sends')
        finally:
            try:
                bound = store.session(key)
                if bound:
                    await client.stop(bound[0])
            finally:
                await service.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.agent_chat')
    parser.add_argument('--confirm-model-calls', action='store_true', required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.env_file))
    except dsh.BridgeError as error:
        print('FAIL: ' + str(error)); sys.exit(1)
    except Exception:
        print('FAIL: configuration_or_protocol_error'); sys.exit(1)
