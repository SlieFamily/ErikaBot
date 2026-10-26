"""Opt-in isolated DSH regression: compact input, native summary, retained identity and facts. No QQ sends."""
import argparse,asyncio,importlib,json,sys,tempfile,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_agent_chat import load_config,dsh,package
M=importlib.import_module(package.__name__+'.domain').ChatMessage
ChatService=importlib.import_module(package.__name__+'.service').ChatService
Store=importlib.import_module(package.__name__+'.store').Store

async def snapshot(client,sid):
 stream=str(uuid.uuid4())
 async with client.connect(client.cfg.agent_chat_dsh_url.replace('http','ws',1)+'/api/remote.mux',extra_headers={'Cookie':client.cookie},open_timeout=10,close_timeout=2,max_size=2000000) as ws:
  await ws.send(json.dumps({'type':'open','streamId':stream,'endpoint':'session/follow','payload':{'args':{'request':{'address':{'kind':'session','sessionId':sid},'maxMessages':20}}}}))
  async with asyncio.timeout(20):
   async for raw in ws:
    snap=client.frame(raw,stream)
    if snap and snap.get('type')=='snapshot':return snap

async def run(path):
 cfg=load_config(private_file=path).copy(update={'agent_chat_enabled':True,'agent_chat_groups':frozenset({42}),
  'agent_chat_proactive_enabled':False,'agent_chat_debounce':0,'agent_chat_cooldown':0,'agent_chat_search_enabled':False,
  'agent_chat_memory_enabled':False,'agent_chat_slang_enabled':False,'agent_chat_timeout':240})
 assert cfg.agent_chat_dsh_url=='http://127.0.0.1:43125','Isolated test instance required'
 with tempfile.TemporaryDirectory() as folder:
  store=Store(Path(folder)/'probe.db');client=dsh.DshClient(cfg);service=ChatService(cfg,store,client)
  sent=[];prompts=[];sid=None
  original=client.reply
  async def record(sid,text,*args,**kwargs):
   prompts.append(text);return await original(sid,text,*args,**kwargs)
  client.reply=record
  async def send(value):sent.append(value)
  async def turn(mid,text):
   msg=M('100:group:42',mid,'7','测试群友',text,time.time(),True)
   service.observe(msg);assert service.schedule(msg,send)
   await asyncio.gather(*list(service.tasks.values()))
   assert not store.session(msg.key)[2],'turn_paused'
   return sent[-1]
  try:
   secret='青柠'+str(uuid.uuid4().int%100000)
   await turn('101',f'独立测试：今晚开黑房间暗号是{secret}，只需在回复中复述暗号，不用存为长期记忆。下面只是聊天背景，不用展开：'+('大家平时也会聊电影和游戏。'*80))
   sid=store.session('100:group:42')[0]
   print('PASS turn 1: role and protocol seeded',flush=True)
   value=await turn('102','表达测试：请引用我这条消息、@我，并带一个QQ自带表情或emoji，自然说一句即可。')
   assert value.reply_to=='102' and value.mentions==('7',),'compact_turn_actions_failed'
   assert '群聊协议：' not in prompts[1] and len(prompts[1])<1000
   print('PASS turn 2: compact prompt retained reply/@ behavior',flush=True)
   before=await snapshot(client,sid);cut=before['cursor']
   # Human maintenance RPC is used only by this isolated test, never forwarded from QQ.
   rid=str(uuid.uuid4())
   body={'type':'client-request','rpcId':rid,'method':'commands/execute',
         'payload':{'args':{'agentId':sid,'line':'/compact','submittedAttachments':[]}}}
   response=await client.http.post(cfg.agent_chat_dsh_url+'/api/commands/execute',
       headers={'Cookie':client.cookie},json=body,timeout=240)
   envelope=response.json()
   assert envelope.get('result',{}).get('ok'), 'native_compact_rpc_failed'
   result=envelope['result'].get('value')
   assert result and result.get('result',{}).get('kind')=='success','native_compact_not_admitted'
   async with asyncio.timeout(240):
    while True:
     snap=await snapshot(client,sid)
     events=[r['event'] for r in snap['records'] if r['event']['seq']>cut]
     if any(e['type']=='compaction/end' for e in events):break
     await asyncio.sleep(2)
   assert any(e['type']=='compaction/summary' for e in events),'summary_not_created'
   summary=next(e['data'] for e in events if e['type']=='compaction/summary')
   print('PASS native DSH compaction committed; summary keys='+','.join(summary),flush=True)
   value=await turn('103','刚才开黑暗号是什么？另外你叫什么，你的母亲是谁？一起简短回答。')
   assert secret in str(value),'summary_lost_fact'
   assert '绘梨花' in str(value) and '贝伦' in str(value),'summary_lost_persona'
   assert '群聊协议：' in prompts[2] and secret not in prompts[2]
   assert store.session('100:group:42')[0]==sid
   print(json.dumps({'completed':3,'native_summaries':1,'prompt_characters':[len(p) for p in prompts],
     'fact_retained':True,'role_retained':True,'qq_sends':0,'real_group_sessions_touched':0}),flush=True)
   print('PASS: compact turns, native summary, protocol reseed and original session continuity',flush=True)
  finally:
   try:
    if sid:await client.stop(sid)
   finally:await service.close()

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--env-file',required=True,type=Path)
 parser.add_argument('--confirm-model-calls',required=True,action='store_true');args=parser.parse_args()
 try:asyncio.run(run(args.env_file))
 except Exception as error:print('FAIL',type(error).__name__,str(error) if isinstance(error,(AssertionError,dsh.BridgeError)) else '');sys.exit(1)
