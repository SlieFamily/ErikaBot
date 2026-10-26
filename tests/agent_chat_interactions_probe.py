"""One isolated DSH turn with synthetic identities; no QQ sends or production sessions."""
import argparse,asyncio,importlib,json,sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_agent_chat import load_config,dsh,package
M=importlib.import_module(package.__name__+'.domain').ChatMessage
ChatService=importlib.import_module(package.__name__+'.service').ChatService
Store=importlib.import_module(package.__name__+'.store').Store
async def run(path):
 cfg=load_config(private_file=path).copy(update={'agent_chat_enabled':True,'agent_chat_groups':frozenset({42}),
  'agent_chat_proactive_enabled':False,'agent_chat_debounce':0,'agent_chat_cooldown':0,'agent_chat_search_enabled':False,
  'agent_chat_memory_enabled':False,'agent_chat_slang_enabled':False,'agent_chat_timeout':90})
 with tempfile.TemporaryDirectory() as folder:
  store=Store(Path(folder)/'probe.db');client=dsh.DshClient(cfg);service=ChatService(cfg,store,client);sent=[]
  original_reply=client.reply
  async def inspect_reply(*args,**kwargs):
   answer=await original_reply(*args,**kwargs)
   # Synthetic test output only; log protocol shape, never role text or production conversations.
   shape={'prefix':str(answer).startswith('QQ_REPLY '),'length':len(answer)}
   try:
    obj=json.loads(str(answer).split('QQ_REPLY',1)[-1].strip())
    shape['fields']={k:type(v).__name__ for k,v in obj.items()}
    shape['action_values']={k:v for k,v in obj.items() if k in ('mentions','reaction','poke','reply_to','faces')}
   except Exception:shape['format_unrecognized']=True
   print('MODEL_SHAPE',json.dumps(shape,ensure_ascii=False))
   return answer
  client.reply=inspect_reply
  async def send(value):sent.append(value)
  try:
   msg=M('100:group:42','123','7','小七','表达功能测试：请在同一轮自然回复里@我，给这条消息贴一个赞，并轻轻戳我一下。可以配个emoji，别介绍功能。',time.time(),True)
   service.observe(msg);service.schedule(msg,send);await asyncio.gather(*list(service.tasks.values()))
   value=sent[0] if sent else ''
   result=dict(model_calls=1,qq_sends=0,mentions=list(getattr(value,'mentions',())),
       reaction=list(getattr(value,'reaction',())),poke=getattr(value,'poke',''),text_present=bool(str(value)),
       session_paused=bool(store.session(msg.key)[2]) if store.session(msg.key) else None)
   print(json.dumps(result,ensure_ascii=False))
   assert result['mentions']==['7'] and result['reaction']==['123','128077'] and result['poke']=='7','model_did_not_select_all_test_actions'
   print('PASS: real DSH model selected mention, reaction and poke; no QQ sends')
  finally:
   try:
    bound=store.session('100:group:42')
    if bound:await client.stop(bound[0])
   finally:await service.close()
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--env-file',required=True,type=Path)
 parser.add_argument('--confirm-model-calls',required=True,action='store_true');args=parser.parse_args()
 try:asyncio.run(run(args.env_file))
 except Exception as error:print('FAIL',type(error).__name__);sys.exit(1)
