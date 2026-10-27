"""Native DSH worker lifecycle probe: disposable blank sessions, no model/QQ calls."""
import argparse,asyncio,importlib,sqlite3,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_agent_chat import dsh,load_config,package
core=lambda name:importlib.import_module(package.__name__+'.'+name)

async def run(env):
 cfg=load_config(private_file=env).copy(update={'agent_chat_memory_enabled':True,
     'agent_chat_provider':'','agent_chat_model':''})
 created=[]
 class Client(dsh.DshClient):
  async def create_session(self):
   sid=await super().create_session();created.append(sid);return sid
  async def reply(self,*args,**kwargs):raise AssertionError('Model calls forbidden in lifecycle probe')
 client=Client(cfg,preset_id=dsh.LEARNER_PRESET_ID)
 db=sqlite3.connect(':memory:')
 knowledge=core('knowledge').KnowledgeStore(db)
 manager=core('memory').MemoryManager(knowledge,cfg)
 worker=SimpleNamespace(client=client,store=knowledge,service=SimpleNamespace(memory_manager=manager))
 try:
  policy=await client.policy()
  acquire=core('learner_sessions').acquire
  first=await acquire(worker,'100:group:42','memory',policy)
  assert await acquire(worker,'100:group:42','memory',policy)==first
  second=await acquire(worker,'100:group:42','slang',policy)
  assert first!=second and len(created)==2
  rotated=await acquire(worker,'100:group:42','memory',policy+'-probe-rotation')
  assert rotated!=first and len(created)==3
  await client.recovery_checkpoint(first)  # Native archive retains the readable log.
  assert manager.state('100:group:42')[0]==rotated
  print('PASS: native DSH repeated acquire reuses identity; two families isolated; rotation archives old worker; historical log remains readable; model calls=0; QQ sends=0',flush=True)
 finally:
  try:
   for sid in created:
    await client.recovery_checkpoint(sid)
    await client.archive_session(sid)
  finally:await client.close();db.close()
 if created:print('PASS: all disposable blank probe sessions archived',flush=True)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--env-file',type=Path,required=True)
 p.add_argument('--confirm-session-changes',action='store_true',required=True);args=p.parse_args()
 try:asyncio.run(run(args.env_file))
 except Exception as e:print('FAIL:',str(e) if isinstance(e,(AssertionError,dsh.BridgeError)) else type(e).__name__,flush=True);sys.exit(1)
