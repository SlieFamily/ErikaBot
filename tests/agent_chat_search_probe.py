"""Explicit live native AnySearch probe: one isolated session, no QQ sends."""
import argparse
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_agent_chat import dsh,load_config,ROOT,package
ChatMessage=importlib.import_module(package.__name__+'.domain').ChatMessage
ChatService=importlib.import_module(package.__name__+'.service').ChatService
Store=importlib.import_module(package.__name__+'.store').Store

async def run(env_file):
    conf=load_config(private_file=env_file).copy(update={
        'agent_chat_enabled':True,'agent_chat_groups':frozenset({42}),'agent_chat_debounce':0,
        'agent_chat_cooldown':0,'agent_chat_proactive_enabled':False,
        'agent_chat_search_enabled':True,'agent_chat_forward_persona':True,'agent_chat_timeout':300})
    key='100:group:42';replies=[];turns=[]
    async def send(text):replies.append(text)
    with tempfile.TemporaryDirectory() as folder:
        store=Store(Path(folder)/'probe.sqlite3');client=dsh.DshClient(conf)
        original=client.reply
        async def record(sid,text,images=None,**kwargs):
            answer=await original(sid,text,images,**kwargs)
            turns.append({'searches':getattr(answer,'searches',0),'sources':list(getattr(answer,'sources',()))})
            return answer
        client.reply=record
        service=ChatService(conf,store,client)
        try:
            await client.policy()
            msg=ChatMessage(key,'native-search-probe','7','测试群友',
                '请用联网搜索查一下明日堇sumire是谁，简单介绍，并给我这次查到的来源。',time.time(),True)
            service.observe(msg);service.schedule(msg,send)
            await asyncio.gather(*list(service.tasks.values()))
            print(json.dumps({'turns':turns,'replies':replies},ensure_ascii=False))
            bound=store.session(key)
            if not bound or bound[2] or len(turns)!=1 or not 1<=turns[0]['searches']<=2 or not turns[0]['sources']:
                raise dsh.BridgeError('native_search_probe_failed')
            if len(replies)!=1 or '明日堇' not in replies[0] or not any(url in replies[0] for url in turns[0]['sources']):
                raise dsh.BridgeError('native_search_answer_missing')
            print('PASS: one DSH turn, native AnySearch results and sourced final answer; no QQ sends')
        finally:
            try:
                bound=store.session(key)
                if bound:await client.stop(bound[0])
            finally:await service.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env.agent_chat')
    parser.add_argument('--confirm-model-calls',action='store_true',required=True)
    args=parser.parse_args()
    try:asyncio.run(run(args.env_file))
    except dsh.BridgeError as error:print('FAIL:',str(error));sys.exit(1)
    except Exception as error:print('FAIL:',type(error).__name__);sys.exit(1)
