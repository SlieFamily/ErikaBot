"""Explicit real DSH/model integration in an isolated profile; never connects to QQ."""
import argparse
import asyncio
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time

from fastapi import FastAPI
import uvicorn

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_agent_chat import dsh,load_config,package
core=lambda name:importlib.import_module(package.__name__+'.'+name)


async def run(env_file,port,provider='',model=''):
    conf=load_config(private_file=env_file)
    if conf.agent_chat_dsh_url.endswith((':43120',':8080')) or port in (43120,8080):
        raise ValueError('Use isolated DSH and knowledge ports for this probe')
    conf=conf.copy(update={'agent_chat_enabled':True,'agent_chat_groups':frozenset({42}),
        'agent_chat_timeout':300,'agent_chat_memory_enabled':True,'agent_chat_slang_enabled':True})
    if bool(provider)!=bool(model):raise ValueError('Set both provider and model for isolated sessions')
    if provider:conf=conf.copy(update={'agent_chat_provider':provider,'agent_chat_model':model})
    with tempfile.TemporaryDirectory() as folder:
        store=core('store').Store(Path(folder)/'probe.sqlite3')
        client=dsh.DshClient(conf)
        service=core('service').ChatService(conf,store,client)
        app=FastAPI();core('knowledge_bridge').install_route(app,lambda:service.knowledge_hub)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='critical',lifespan='off',access_log=False))
        server.install_signal_handlers=lambda:None
        task=asyncio.create_task(server.serve())
        while not server.started:
            if task.done():raise RuntimeError('test bridge did not start')
            await asyncio.sleep(.05)
        sessions=[]
        learner=None
        result={}
        key='100:group:42'
        try:
            _,persona=await client.policy_with_persona()
            scope=service.knowledge_hub.scope(key,[{'user_id':'7','name':'离线测试群友','message_id':'1','text':'周末喜欢玩法环'}])
            sid=await client.create_session();sessions.append(sid)
            msg=core('domain').ChatMessage(key,'1','7','离线测试群友',
                '绘梨花，帮我记一下我的游戏偏好：周末我喜欢玩法环。以后再聊时也希望你记得。',time.time(),True)
            prompt=core('domain').prompt_text([msg.payload()],'knowledge-probe',persona=persona)
            prompt+='\n本轮轻量记忆工具可用。需要持久记住的具体群友偏好可使用 qq_memory_append 记录；不要只口头说已记住。'
            answer=await client.reply(sid,prompt,knowledge=scope)
            assert 'qq_memory_append' in answer.knowledge_calls,'model did not append memory'
            assert service.knowledge.memory(key,'memberImpression'),'native tool did not persist memory'
            assert not service.knowledge.memory('100:group:43'),'memory crossed groups'
            result['native_append']=True
            print('PASS: native memory tool persisted scoped data',flush=True)
            # A brand new DSH session receives neither the old text nor a memory snapshot.
            sid=await client.create_session();sessions.append(sid)
            msg=core('domain').ChatMessage(key,'2','7','离线测试群友',
                '绘梨花，还记得我周末喜欢玩什么游戏吗？查一下你留过的群友印象。',time.time(),True)
            prompt=core('domain').prompt_text([msg.payload()],'knowledge-recall',persona=persona)
            prompt+='\n本轮轻量记忆工具可用；缺少过去偏好时可用 qq_memory_query 查询 memberImpression，不要凭空猜测。'
            answer=await client.reply(sid,prompt,knowledge=scope)
            assert 'qq_memory_query' in answer.knowledge_calls and '法环' in str(answer),'new session did not retrieve persistent memory'
            result['new_session_recall']=True
            print('PASS: a new DSH session queried persistent memory',flush=True)
            for n in range(10):
                msg=core('domain').ChatMessage(key,str(n+10),'7','离线测试群友',f'第{n+1}局终于赢了，这波芜湖起飞',time.time())
                service.learn_message(msg,msg.text)
            learner=core('learning').SlangLearner(service)
            # Preserve production's bounded90s learner timeout; an upstream failure must fail this probe.
            await learner.run(key,'extract')
            candidates=service.knowledge.slang_for_admin(key)+service.knowledge.slang_for_admin(key,'learned')
            chosen=next((row for row in candidates if row['content']=='芜湖起飞'),None)
            assert chosen,'live extractor failed to ground the actual phrase'
            result['grounded_extraction']=True
            print('PASS: learner extracted a phrase present in synthetic chat',flush=True)
            await learner.run(key,'research',chosen)
            draft=next(row for row in service.knowledge.slang_for_admin(key,'learned') if row['id']==chosen['id'])
            assert draft['meaning'],'research did not produce a grounded definition'
            assert service.knowledge.known_slang(),'automatic definition not available'
            service.knowledge.review_slang(key,draft['id'],'confirm')
            assert service.knowledge.known_slang()[0]['meaning']==draft['meaning']
            result.update(anysearch_draft=True,manual_confirmation=True,qq_sends=0)
            print('PASS: Autonomous definition usable before human locking; no QQ sends',flush=True)
            print(json.dumps(result),flush=True)
        finally:
            for sid in sessions:
                try:await client.stop(sid)
                except Exception:pass
            if learner:await learner.close()
            await service.close()
            server.should_exit=True
            await asyncio.wait_for(task,5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,required=True)
    parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--confirm-model-calls',action='store_true',required=True)
    parser.add_argument('--provider',default='')
    parser.add_argument('--model',default='')
    args=parser.parse_args()
    try:asyncio.run(run(args.env_file,args.port,args.provider,args.model))
    except Exception as error:
        print('FAIL:',str(error) if isinstance(error,(AssertionError,dsh.BridgeError)) else type(error).__name__,flush=True)
        sys.exit(1)
