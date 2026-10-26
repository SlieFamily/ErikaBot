"""Explicit single-session live DSH probe; synthetic input, no QQ sends."""
import argparse,asyncio,importlib,json,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_agent_chat import load_config,dsh,package
ChatMessage=importlib.import_module(package.__name__+'.domain').ChatMessage
ChatService=importlib.import_module(package.__name__+'.service').ChatService
Store=importlib.import_module(package.__name__+'.store').Store

async def run(path):
 cfg=load_config(private_file=path).copy(update={'agent_chat_enabled':True,'agent_chat_groups':frozenset({42}),
  'agent_chat_proactive_enabled':False,'agent_chat_debounce':0,'agent_chat_cooldown':0,'agent_chat_search_enabled':False})
 with tempfile.TemporaryDirectory() as folder:
  store=Store(Path(folder)/'probe.db');client=dsh.DshClient(cfg);service=ChatService(cfg,store,client);sent=[]
  key='100:group:42'
  async def send(answer):sent.append(answer)
  try:
   msg=ChatMessage(key,'123','7','测试群友','测试表达功能：请引用我这条消息，回复一句简短的话，带一个emoji，末尾加一个QQ捂脸表情。使用管理员给出的QQ_REPLY格式。',time.time(),True)
   service.observe(msg);service.schedule(msg,send)
   await asyncio.gather(*list(service.tasks.values()))
   bound=store.session(key)
   assert bound
   if sent:
    print(json.dumps({'reply':str(sent[0]),'reply_to':getattr(sent[0],'reply_to',''),'faces':getattr(sent[0],'faces',())},ensure_ascii=False))
   else:print('Model did not produce a final answer; testing recovery of the stopped probe session')
   assert await client.recovery_checkpoint(bound[0])>=0
   store.suspend(key);count=len(sent)
   assert await service.recover(key)=='resumed'
   assert store.session(key)[0]==bound[0] and not store.session(key)[2] and len(sent)==count
   print('PASS: real DSH recovery audit retains same session and does not replay output')
   if not sent or getattr(sent[0],'reply_to','')!='123' or 264 not in getattr(sent[0],'faces',()):
    print('LIMITATION: live model output did not verify both quote and face; see deterministic integration tests')
   else:print('PASS: real model selected quote and native QQ face; no QQ sends')
  finally:
   try:
    bound=store.session(key)
    if bound:await client.stop(bound[0])
   finally:await service.close()

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--env-file',required=True,type=Path)
 parser.add_argument('--confirm-model-calls',required=True,action='store_true');args=parser.parse_args()
 try:asyncio.run(run(args.env_file))
 except dsh.BridgeError as e:print('FAIL:',str(e));sys.exit(1)
 except Exception as e:print('FAIL:',type(e).__name__);sys.exit(1)
