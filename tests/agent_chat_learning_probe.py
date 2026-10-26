"""Live integration in an isolated DSH profile with synthetic messages; never sends QQ."""
import argparse,asyncio,importlib,json,sys,tempfile,time
from pathlib import Path
from fastapi import FastAPI
import uvicorn
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_agent_chat import dsh,load_config,package
core=lambda name:importlib.import_module(package.__name__+'.'+name)
async def run(env_file,port):
 conf=load_config(private_file=env_file)
 assert conf.agent_chat_dsh_url.endswith(':43125') and port==43126,'isolated ports required'
 conf=conf.copy(update={'agent_chat_enabled':True,'agent_chat_groups':frozenset({42}),
  'agent_chat_timeout':120,'agent_chat_slang_enabled':True,'agent_chat_memory_enabled':False})
 with tempfile.TemporaryDirectory() as folder:
  store=core('store').Store(Path(folder)/'test.sqlite3');client=dsh.DshClient(conf)
  service=core('service').ChatService(conf,store,client);app=FastAPI()
  core('knowledge_bridge').install_route(app,lambda:service.knowledge_hub)
  server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='critical',lifespan='off',access_log=False));server.install_signal_handlers=lambda:None
  task=asyncio.create_task(server.serve())
  while not server.started:
   if task.done():raise RuntimeError('bridge start failed')
   await asyncio.sleep(.05)
  key='100:group:42';sessions=[];learner=None
  try:
   _,persona=await client.policy_with_persona()
   msg=core('domain').ChatMessage(key,'501','7','测试成员','咕咕航线就是约好了又临时放鸽子的意思。请把这个用法记进黑话词库。',time.time(),True)
   scope=service.knowledge_hub.scope(key,[msg.payload()],memory=False)
   sid=await client.create_session();sessions.append(sid)
   prompt=core('domain').prompt_text([msg.payload()],'autolearn-probe',persona=persona)
   prompt+='\n'+core('slang_evolution').SLANG_RULES+'\n请实际使用qq_slang_submit保存这个明确解释，content=咕咕航线，basis=explicit，evidence使用消息501的逐字原文；然后简短回复。'
   answer=await client.reply(sid,prompt,knowledge=scope)
   learned=service.knowledge.known_slang('咕咕航线')
   assert 'qq_slang_submit' in answer.knowledge_calls and learned and not learned[0]['locked'],'native definition not saved'
   print('PASS: live native tool saved a grounded definition, immediately usable without approval',flush=True)
   entry=learned[0];service.knowledge.review_slang(key,entry['id'],'confirm','人工锁定测试释义')
   assert not service.knowledge.evolve_slang(key,entry['id'],dict(content='咕咕航线',meaning='覆盖',basis='explicit',evidence=[dict(message_id='501',quote=msg.text)]),[msg.payload()])
   print('PASS: human lock protected the live learned entry',flush=True)
   # A fresh isolated learner may decide search is needed; host permits only this public term.
   learner=core('learning').SlangLearner(service)
   term='南北绿豆';row=dict(key=key,message_id='502',text='南北绿豆',user_id='7',name='测试成员')
   target=service.knowledge.submit_slang(key,term,[row])
   sid=await learner.client.create_session();sessions.append(sid)
   _,role=await learner.client.policy_with_persona()
   prompt=role+'\n'+core('learning').research_prompt(term,[dict(message_id='502',text=term)])+'\n本例没有本群自定义解释，需要核实公开网络用法，请使用允许的web_search后根据真实来源解释；不足就confirmed=false。'
   answer=await learner.client.reply(sid,prompt,search_enabled=True,research_term=term)
   assert answer.searches>0 and answer.sources,'native AnySearch did not return sources'
   rows=core('knowledge').json_array(answer)
   saved=any(service.knowledge.save_research(target['id'],r,answer.sources,key=key,messages=[row],expected_revision=0) for r in rows)
   assert saved,'live research did not produce an evidence-backed meaning'
   print('PASS: isolated learner used native AnySearch and saved only actual sourced findings',flush=True)
   print('PASS: autonomous slang integration; QQ sends=0; production untouched',flush=True)
  finally:
   for sid in sessions:
    try:await client.stop(sid)
    except Exception:pass
   if learner:await learner.close()
   await service.close();server.should_exit=True;await asyncio.wait_for(task,5)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--env-file',type=Path,required=True);p.add_argument('--port',type=int,required=True);p.add_argument('--confirm-model-calls',action='store_true',required=True);a=p.parse_args()
 try:asyncio.run(run(a.env_file,a.port))
 except Exception as e:print('FAIL:',str(e) if isinstance(e,(AssertionError,dsh.BridgeError)) else type(e).__name__,flush=True);sys.exit(1)
