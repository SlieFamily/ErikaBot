"""Memory controls, grounded incremental extraction and chat priority; no live services."""
import asyncio,importlib,json,sqlite3,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from test_agent_chat import PACKAGE,cfg,domain,Store,ChatService,FakeClient,message,dsh
from test_agent_chat_knowledge import k,kb,admin,learning,KEY,OTHER,TOKEN
memory=importlib.import_module(PACKAGE+'.memory')

class MemoryTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.k=k.KnowledgeStore(self.db)
  self.cfg=cfg(agent_chat_memory_enabled=True,agent_chat_memory_background_enabled=True,agent_chat_knowledge_token=TOKEN)
  self.m=memory.MemoryManager(self.k,self.cfg)
 def tearDown(self):self.db.close()
 def feed(self,n=1,key=KEY,start=0):
  for i in range(start,start+n):
   msg=replace(message(key, str(i)),text='我平时常玩法环，喜欢帮朋友打boss。')
   self.m.feed(msg,msg.text)
 def item(self,batch,**changes):
  return dict(dict(category='memberImpression',content='常玩法环，喜欢帮朋友打boss',target='7',
    evidence=[dict(source_id=batch[0]['source_id'],quote='我平时常玩法环')]),**changes)
 def test_persistent_group_and_global_switches_preserve_memories(self):
  self.k.append_memory(KEY,'activeTopic','周末开黑');self.feed()
  self.m.set(KEY,'background',False);self.assertFalse(self.m.settings(KEY)['background']);self.assertTrue(self.m.settings(OTHER)['background'])
  self.assertEqual(self.m.batch(KEY),[]);self.feed();self.assertEqual(self.m.batch(KEY),[])
  self.m.set('*','background',True);self.assertTrue(self.m.settings(KEY)['background'])
  self.m.set(KEY,'immediate',False);self.m.set('*','enabled',False)
  restored=memory.MemoryManager(self.k,self.cfg)
  self.assertFalse(restored.settings(OTHER)['enabled']);self.assertFalse(restored.settings(KEY)['immediate'])
  self.assertEqual(len(self.k.memory(KEY)),1)
 def test_threshold_clock_minimum_interval_and_no_idle_calls(self):
  self.assertFalse(self.m.due(KEY));self.feed(29);self.assertFalse(self.m.due(KEY))
  self.feed(start=29);self.assertTrue(self.m.due(KEY));self.m.attempt(KEY);self.assertFalse(self.m.due(KEY))
  with patch.object(memory.time,'time',return_value=time.time()+601):self.assertTrue(self.m.due(KEY))
  self.m.set(KEY,'background',False);self.m.set(KEY,'background',True);self.feed(start=100)
  with patch.object(memory.time,'time',return_value=time.time()+601):self.assertTrue(self.m.due(KEY))
 def test_oldest_batch_atomic_ack_new_arrivals_and_no_twenty_message_loss(self):
  self.feed(71);batch=self.m.batch(KEY);self.assertEqual(len(batch),50);self.assertEqual(batch[0]['message_id'],'0')
  self.m.attempt(KEY);self.feed(start=72);rev=self.m.settings(KEY)['revision']
  self.assertEqual(self.m.apply(KEY,batch,rev,[self.item(batch)]),1)
  self.assertEqual(len(self.m.batch(KEY)),22);self.assertEqual(self.m.batch(KEY)[0]['message_id'],'50')
  self.assertEqual(len(self.k.memory(KEY)),1);self.assertEqual(self.k.memory(OTHER),[])
  self.m.apply(KEY,self.m.batch(KEY),rev,[]);self.assertEqual(self.m.batch(KEY),[])
 def test_evidence_rejects_foreign_sources_wrong_targets_and_sensitive_text(self):
  self.feed();batch=self.m.batch(KEY);valid=self.item(batch)
  bad=[self.item(batch,target='8'),self.item(batch,category='pendingThought'),self.item(batch,content='password:secret'),
       self.item(batch,evidence=[dict(source_id='9999',quote='我平时常玩法环')]),self.item(batch,evidence=[dict(source_id=batch[0]['source_id'],quote='不存在')])]
  self.m.attempt(KEY);self.assertEqual(self.m.apply(KEY,batch,self.m.settings(KEY)['revision'],bad+[valid,valid]),1)
 def test_transaction_rolls_back_memory_and_cursor_on_failure(self):
  self.feed();batch=self.m.batch(KEY);self.m.attempt(KEY);original=self.k.append_memory
  def broken(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('fail after write')
  with patch.object(self.k,'append_memory',side_effect=broken),self.assertRaises(RuntimeError):self.m.apply(KEY,batch,self.m.settings(KEY)['revision'],[self.item(batch)])
  self.assertEqual(self.k.memory(KEY),[]);self.assertEqual(len(self.m.batch(KEY)),1)
 def test_disable_reenable_or_forget_invalidates_inflight_results(self):
  self.feed();batch=self.m.batch(KEY);rev=self.m.settings(KEY)['revision']
  self.m.set(KEY,'background',False);self.m.set(KEY,'background',True);self.feed(start=2)
  self.assertIsNone(self.m.apply(KEY,batch,rev,[self.item(batch)]));self.assertEqual(len(self.m.batch(KEY)),1)
  rev=self.m.settings(KEY)['revision'];self.m.invalidate(KEY)
  self.assertIsNone(self.m.apply(KEY,batch,rev,[self.item(batch)]));self.assertEqual(self.m.batch(KEY),[])
 def test_leases_revoked_and_immediate_read_only(self):
  hub=kb.KnowledgeHub(self.k,TOKEN,self.m);scope=hub.scope(KEY,[message().payload()])
  body=dict(session_id='s',rpc_id='r',call_id='c',name='qq_memory_append',args=dict(category='activeTopic',content='开黑'))
  with hub.lease(scope,'s','r'):
   self.assertTrue(hub.handle(body)['ok']);hub.handle(body);self.assertEqual(scope.memory_writes,1)
   self.m.set(KEY,'immediate',False)
   with self.assertRaises(k.KnowledgeError):hub.handle(body)
  readonly=hub.scope(KEY,[]);self.assertEqual(set(readonly.tools)&set(k.MEMORY_TOOLS),{'qq_memory_query'})
 def test_restart_preserves_backlog_and_budget_resets_only_own_session(self):
  self.feed();self.m.bind(KEY,'memory-sid','p');self.k.bind_learner(KEY,'slang-sid','p')
  self.k.begin_learning(KEY,'memory',12);self.m.attempt(KEY)
  restored=k.KnowledgeStore(self.db);manager=memory.MemoryManager(restored,self.cfg)
  self.assertIsNone(manager.state(KEY)[0]);self.assertEqual(restored.learning_state(KEY)[2],'slang-sid')
  self.assertEqual(len(manager.batch(KEY)),1);self.assertEqual(restored.learning_count(),1)
 def test_queue_limits_and_filtered_commands(self):
  for plain in ['ai 即时记忆 关','/ai 状态','password:secret','']:
   self.assertFalse(self.m.feed(message(mid=plain),plain))
  self.feed(1003);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM memory_inbox').fetchone()[0],1000)
  self.assertIn('丢弃 3 条',self.m.describe(KEY))
  with patch.object(memory.time,'time',return_value=time.time()+86401):self.assertEqual(self.m.batch(KEY),[])
 def test_admin_switches_and_space_confirmation_help(self):
  self.assertIn('本群',admin.handle(self.k,KEY,'即时记忆 关',memory=self.m));self.assertFalse(self.m.settings(KEY)['immediate'])
  self.assertIn('所有群',admin.handle(self.k,KEY,'后台记忆 全群 关',memory=self.m));self.assertFalse(self.m.settings(OTHER)['background'])
  self.assertIn('有效记忆',admin.handle(self.k,KEY,'记忆状态',memory=self.m));self.assertIn('1 2 3',admin.HELP)
  self.assertEqual(self.k.learning_count(),0)

class MemoryLearningTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'state')
  self.cfg=cfg(agent_chat_memory_enabled=True,agent_chat_slang_enabled=True,agent_chat_memory_background_enabled=True,
               agent_chat_memory_batch_threshold=2,agent_chat_knowledge_token=TOKEN)
  self.client=FakeClient();self.service=ChatService(self.cfg,self.store,self.client)
  self.fake=FakeClient();self.fake.answer='[]';self.learner=learning.SlangLearner(self.service,self.fake)
 async def asyncTearDown(self):await self.learner.close();await self.service.close();self.tmp.cleanup()
 def feed(self,n=2):
  for i in range(n):
   msg=replace(message(mid=str(i)),text='我平时常玩法环，芜湖起飞');self.service.learn_message(msg,msg.text)
 async def test_silent_incremental_uses_dedicated_session_obeys_chat_priority_shared_quota(self):
  self.feed();self.store.bind(KEY,'chat-session','p');self.service.pending[KEY]=object()
  self.assertFalse(await self.learner.tick());self.service.pending.clear()
  self.assertTrue(await self.learner.tick());self.assertFalse(await self.learner.tick())
  self.assertEqual(self.store.session(KEY),('chat-session','p',0));self.assertEqual(len(self.fake.prompts),1)
  self.assertNotEqual(self.fake.prompts[0][0],'chat-session');self.assertIn('source_id',self.fake.prompts[0][1])
  self.assertEqual(self.service.memory_manager.batch(KEY),[])
  self.feed(10);self.service.cfg.agent_chat_learning_max_per_hour=1
  self.assertFalse(await self.learner.tick())
 async def test_memory_then_slang_both_make_progress(self):
  self.feed(10);self.assertTrue(await self.learner.tick());self.assertTrue(await self.learner.tick())
  kinds=[r[0] for r in self.store.db.execute('SELECT kind FROM knowledge_runs ORDER BY id')]
  self.assertEqual(kinds,['memory','extract'])
 async def test_failure_keeps_inbox_and_never_pauses_chat(self):
  self.feed();self.fake.error=dsh.BridgeError('timeout');self.store.bind(KEY,'chat','p')
  self.assertTrue(await self.learner.tick());self.assertFalse(await self.learner.tick())
  self.assertEqual(len(self.service.memory_manager.batch(KEY)),2);self.assertEqual(self.store.session(KEY)[2],0)
  self.assertIsNone(self.service.memory_manager.state(KEY)[0]);self.assertEqual(self.service.knowledge.learning_count(),1)
 async def test_immediate_saved_in_same_turn_and_false_claim_guard(self):
  sent=[]
  async def send(text):sent.append(str(text))
  async def reply(sid,text,images=None,**kw):
   self.client.prompts.append((sid,text));scope=kw['knowledge']
   with scope.hub.lease(scope,sid,'r'):
    result=scope.hub.handle(dict(session_id=sid,rpc_id='r',call_id='c',name='qq_memory_append',args=dict(category='memberImpression',content='喜欢法环',extra={'target':'7'})))
    self.assertTrue(result['ok'])
   return '记住了，下次喊你玩法环。'
  self.client.reply=reply
  msg=replace(message(mid='900'),text='记住，我平时最喜欢法环。');self.service.observe(msg);self.service.schedule(msg,send);await self.service.tasks[KEY]
  self.assertIn('记住了',sent[-1]);self.assertEqual(len(self.service.knowledge.memory(KEY)),1);self.assertEqual(self.service.knowledge.learning_count(),0)
  self.service.memory_manager.set(KEY,'immediate',False)
  async def no_tool(*a,**kw):self.assertNotIn('qq_memory_append',kw['knowledge'].tools);return '记住了！'
  self.client.reply=no_tool;msg=replace(msg,message_id='901');self.service.observe(msg);self.service.schedule(msg,send);await self.service.tasks[KEY]
  self.assertNotIn('记住了',sent[-1]);self.assertIn('没记好',sent[-1])

if __name__=='__main__':unittest.main()
