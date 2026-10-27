"""Worker identity, safety audits, retries and native non-destructive retirement."""
import asyncio,hashlib,importlib,json,unittest
from unittest.mock import patch
import httpx
import test_agent_chat_memory_modes as memory_tests
from test_agent_chat import PACKAGE,cfg,dsh
from test_agent_chat_knowledge import KEY,OTHER,FakeLearnerClient,k
sessions=importlib.import_module(PACKAGE+'.learner_sessions')
memory_learning=importlib.import_module(PACKAGE+'.memory_learning')

class WorkerTests(unittest.IsolatedAsyncioTestCase):
 asyncSetUp=memory_tests.MemoryLearningTests.asyncSetUp
 asyncTearDown=memory_tests.MemoryLearningTests.asyncTearDown
 feed=memory_tests.MemoryLearningTests.feed
 async def test_two_workers_per_group_and_extraction_research_share_one(self):
  for key in (KEY,OTHER):
   for family in ('memory','slang'):
    first=await sessions.acquire(self.learner,key,family,'policy')
    for _ in range(4):self.assertEqual(await sessions.acquire(self.learner,key,family,'policy'),first)
  self.assertEqual(len(self.fake.created),4);self.assertEqual(len(set(self.fake.created)),4)
  self.assertEqual(len(self.fake.checked),16);self.assertFalse(self.fake.archived)
 async def test_repeated_bad_memory_json_keeps_worker_and_inbox_without_cancelling(self):
  self.feed();self.fake.answer='不是JSON'
  for _ in range(3):await memory_learning.run_memory(self.learner,KEY)
  self.assertEqual(len(self.fake.created),1);self.assertEqual(len(self.fake.prompts),3)
  self.assertFalse(self.fake.stopped);self.assertEqual(len(self.service.memory_manager.batch(KEY)),2)
  self.fake.answer='[]';await memory_learning.run_memory(self.learner,KEY)
  self.assertEqual(len(self.fake.created),1);self.assertFalse(self.service.memory_manager.batch(KEY))
 async def test_bad_slang_json_then_research_uses_same_worker(self):
  self.feed(10);self.fake.answer='invalid'
  await self.learner.run(KEY,'extract');first=self.service.knowledge.learning_state(KEY)[2]
  self.fake.answer='[]';await self.learner.run(KEY,'extract')
  self.assertEqual(self.service.knowledge.learning_state(KEY)[2],first)
  self.assertEqual(len(self.fake.created),1);self.assertFalse(self.fake.stopped)
 async def test_timeout_cleanup_then_idle_audit_reuses_same_worker(self):
  self.feed();self.fake.error=dsh.BridgeError('dsh_turn_timeout')
  await memory_learning.run_memory(self.learner,KEY)
  self.assertEqual(self.fake.stopped,self.fake.created)
  self.fake.error=None;await memory_learning.run_memory(self.learner,KEY)
  self.assertEqual(len(self.fake.created),1);self.assertEqual(self.fake.checked,self.fake.created)
 async def test_busy_offline_foreign_or_unverified_worker_never_spawns_or_cancels(self):
  self.feed();self.fake.answer='bad';await memory_learning.run_memory(self.learner,KEY)
  for code in ('recovery_turn_active','dsh_stream_disconnected','recovery_foreign_input','recovery_history_unverified','unsafe_current_session_preset'):
   self.fake.check_error=dsh.BridgeError(code)
   await memory_learning.run_memory(self.learner,KEY)
  self.assertEqual(len(self.fake.created),1);self.assertEqual(len(self.fake.prompts),1)
  self.assertFalse(self.fake.stopped or self.fake.archived)
 async def test_cleanup_failure_preserves_id_and_blocks_new_worker_while_running(self):
  self.feed();self.fake.error=dsh.BridgeError('dsh_turn_timeout')
  async def stop(sid):raise dsh.BridgeError('cannot_confirm_queue_cleared')
  self.fake.stop=stop;await memory_learning.run_memory(self.learner,KEY)
  self.fake.check_error=dsh.BridgeError('recovery_turn_active')
  await memory_learning.run_memory(self.learner,KEY)
  self.assertEqual(len(self.fake.created),1);self.assertEqual(len(self.fake.prompts),1)
 async def test_restart_keeps_identity_and_checks_old_work_before_reuse(self):
  self.feed();self.fake.answer='bad';await memory_learning.run_memory(self.learner,KEY)
  bound=self.service.memory_manager.state(KEY)
  run=self.service.knowledge.begin_learning(KEY,'memory',12)
  knowledge=k.KnowledgeStore(self.store.db)
  manager=memory_tests.memory.MemoryManager(knowledge,self.cfg)
  self.service.knowledge=knowledge;self.learner.store=knowledge;self.service.memory_manager=manager
  self.assertEqual(manager.state(KEY),bound)
  self.assertEqual(self.store.db.execute('SELECT status FROM knowledge_runs WHERE id=?',(run,)).fetchone()[0],'interrupted')
  self.fake.answer='[]';await memory_learning.run_memory(self.learner,KEY)
  self.assertEqual(len(self.fake.created),1);self.assertEqual(self.fake.checked[-1],bound[0])
 async def test_only_explicit_missing_creates_a_replacement(self):
  first=await sessions.acquire(self.learner,KEY,'memory','policy')
  self.fake.check_error=dsh.MissingSession('dsh_session_missing')
  second=await sessions.acquire(self.learner,KEY,'memory','policy')
  self.assertNotEqual(first,second);self.assertFalse(self.fake.archived)
  self.assertEqual(self.service.memory_manager.state(KEY),(second,'policy'))
 async def test_policy_rotation_archives_old_worker_once_after_audit(self):
  first=await sessions.acquire(self.learner,KEY,'slang','old')
  self.fake.archive_error=dsh.BridgeError('dsh_transport_or_protocol_error')
  with self.assertRaises(dsh.BridgeError):await sessions.acquire(self.learner,KEY,'slang','new')
  self.assertEqual(len(self.fake.created),1)
  self.assertEqual(self.service.knowledge.learning_state(KEY)[2:],(first,'old'))
  self.fake.archive_error=None
  new=await sessions.acquire(self.learner,KEY,'slang','new')
  self.assertEqual(self.fake.archived,[first]);self.assertEqual(len(self.fake.created),2)
  self.assertEqual(await sessions.acquire(self.learner,KEY,'slang','new'),new)
  self.assertEqual(self.fake.archived,[first]);self.assertEqual(len(self.fake.created),2)
 async def test_cancelled_task_preserves_worker_and_propagates_cancellation(self):
  self.feed()
  async def cancelled(*a,**kw):raise asyncio.CancelledError()
  self.fake.reply=cancelled
  with self.assertRaises(asyncio.CancelledError):await memory_learning.run_memory(self.learner,KEY)
  self.assertEqual(self.service.memory_manager.state(KEY)[0],self.fake.created[0])
  self.assertEqual(self.fake.stopped,self.fake.created)

class ArchiveTests(unittest.IsolatedAsyncioTestCase):
 async def test_native_archive_requires_confirmation_never_deletes_or_cancels(self):
  calls=[];response={'archivedSessionIds':['worker']}
  def handler(request):
   data=json.loads(request.content);calls.append(data)
   return httpx.Response(200,json={'type':'server-response','rpcId':data['rpcId'],'result':{'ok':True,'value':response}})
  client=dsh.DshClient(cfg(),httpx.AsyncClient(transport=httpx.MockTransport(handler)))
  try:
   await client.archive_session('worker')
   self.assertEqual(calls[0]['method'],'workspace/archiveSession')
   self.assertEqual(calls[0]['payload'],{'args':{'request':{'sessionId':'worker'}}})
   response={}
   with self.assertRaisesRegex(dsh.BridgeError,'session_archive_unconfirmed'):await client.archive_session('worker')
  finally:await client.close()

if __name__=='__main__':unittest.main()
