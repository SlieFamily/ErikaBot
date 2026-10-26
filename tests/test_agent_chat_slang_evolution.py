"""Grounded autonomous definitions, administrative locks, version races and backlog."""
import importlib
import json
import sqlite3
import unittest
import test_agent_chat_knowledge as knowledge_tests
from test_agent_chat_knowledge import KEY, OTHER, TOKEN, k, kb, admin
from test_agent_chat import PACKAGE, dsh

class EvolutionTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.store=k.KnowledgeStore(self.db)
        self.messages=[dict(key=KEY,message_id='1',text='咕咕航线就是约好了又临时放鸽子的意思',user_id='7',name='甲'),
                       dict(key=KEY,message_id='2',text='今天又走咕咕航线，约好了却没来',user_id='8',name='乙')]
        self.i=self.store.submit_slang(KEY,'咕咕航线',self.messages)['id']
    def tearDown(self):self.db.close()
    def result(self,**extra):
        return dict(dict(content='咕咕航线',meaning='临时放鸽子的调侃',basis='explicit',
            evidence=[dict(message_id='1',quote=self.messages[0]['text'])]),**extra)
    def learn(self,**extra):return self.store.evolve_slang(KEY,self.i,self.result(**extra),self.messages,expected_revision=self.store.slang_revision(self.i))
    def test_explicit_learning_usable_in_snapshot_and_query_without_human(self):
        self.assertTrue(self.learn());self.assertFalse(self.store.known_slang()[0]['locked'])
        self.assertEqual(self.store.research_targets(KEY),[])
        self.assertIn('临时放鸽子的调侃',self.store.snapshot(OTHER)[1])
        self.assertNotIn('约好了又临时',self.store.snapshot(OTHER)[1])
        self.assertFalse(self.learn(confirmed=False))
    def test_usage_requires_two_distinct_real_messages(self):
        self.assertFalse(self.learn(basis='usage'))
        self.assertTrue(self.learn(basis='usage',evidence=[dict(message_id=m['message_id'],quote=m['text']) for m in self.messages]))
    def test_fabricated_cross_chat_secret_and_mislabelled_evidence_rejected(self):
        for evidence in [[dict(message_id='100',quote=self.messages[0]['text'])],
                         [dict(message_id='1',quote='咕咕航线就是别的意思')],
                         [dict(message_id='2',quote=self.messages[1]['text'])]]:
            self.assertFalse(self.learn(evidence=evidence))
        self.assertFalse(self.store.evolve_slang(OTHER,self.i,self.result(),self.messages))
        with self.assertRaises(k.KnowledgeError):self.learn(meaning='password:secret')
        self.assertEqual(self.store.known_slang(),[])
    def test_search_needs_actual_public_tool_sources(self):
        result=self.result(basis='search',sources=['https://example.com/reference'])
        self.assertFalse(self.store.evolve_slang(KEY,self.i,result,self.messages))
        self.assertTrue(self.store.evolve_slang(KEY,self.i,result,self.messages,sources=result['sources']))
        result['sources']=['http://127.0.0.1/private']
        self.assertFalse(self.store.evolve_slang(KEY,self.i,result,self.messages,sources=result['sources']))
    def test_human_lock_and_stale_result_cannot_overwrite(self):
        revision=self.store.slang_revision(self.i)
        self.assertTrue(self.learn())
        self.assertFalse(self.store.evolve_slang(KEY,self.i,self.result(meaning='旧答案'),self.messages,expected_revision=revision))
        self.store.review_slang(KEY,self.i,'confirm','管理员解释')
        self.assertFalse(self.learn());self.assertTrue(self.store.known_slang()[0]['locked'])
        self.assertEqual(self.store.known_slang()[0]['meaning'],'管理员解释')
        self.store.review_slang(KEY,self.i,'unlock')
        self.assertTrue(self.learn(meaning='新证据解释'))
        self.store.review_slang(KEY,self.i,'reject')
        self.assertFalse(self.learn())
        with self.assertRaises(k.KnowledgeError):self.store.submit_slang(KEY,'咕咕航线',self.messages)
    def test_history_rollback_and_scope(self):
        self.learn();version=self.store.slang_revision(self.i)
        self.learn(meaning='补充含义')
        self.assertIn('临时放鸽子的调侃',admin.handle(self.store,OTHER,f'黑话历史 {self.i}',admin_bot='100'))
        with self.assertRaises(k.KnowledgeError):self.store.slang_versions(self.i,'200')
        self.assertIn('已回退并锁定',admin.handle(self.store,OTHER,f'黑话回退 {self.i} {version}',admin_bot='100'))
        self.assertEqual(self.store.known_slang()[0]['meaning'],'临时放鸽子的调侃')
        self.assertFalse(self.learn())
        self.assertIn('已解锁',admin.handle(self.store,OTHER,f'黑话解锁 {self.i}',admin_bot='100'))
        for n in range(25):self.learn(meaning=f'修订{n}')
        self.assertEqual(len(self.store.slang_versions(self.i,'100')),20)
    def test_existing_confirmed_survives_schema_migration_locked(self):
        self.store.review_slang(KEY,self.i,'confirm','旧人工解释')
        self.db.execute('DROP TABLE knowledge_slang_versions')
        self.db.execute('ALTER TABLE knowledge_slang DROP COLUMN revision')
        self.db.execute('ALTER TABLE knowledge_slang DROP COLUMN basis')
        restored=k.KnowledgeStore(self.db)
        self.assertTrue(restored.known_slang()[0]['locked'])
        self.assertEqual(restored.known_slang()[0]['meaning'],'旧人工解释')
    def test_partial_schema_migration_resumes_safely(self):
        self.db.execute('ALTER TABLE knowledge_slang DROP COLUMN basis')
        k.KnowledgeStore(self.db)
        self.assertTrue(self.learn())

    def test_tool_scope_immediate_definition_idempotency_and_lock(self):
        hub=kb.KnowledgeHub(self.store,TOKEN);scope=hub.scope(KEY,self.messages, memory=False)
        args=self.result();body=dict(session_id='s',rpc_id='r',call_id='c',name='qq_slang_submit',args=args)
        with hub.lease(scope,'s','r'):
            first=hub.handle(body);self.assertTrue(first['meaning_saved'])
            self.assertEqual(first,hub.handle(body));self.assertEqual(self.store.slang_revision(self.i),1)
            self.store.review_slang(KEY,self.i,'confirm','锁定解释')
            self.assertFalse(hub.handle(dict(body,call_id='c2'))['meaning_saved'])
        self.assertEqual(self.store.known_slang()[0]['meaning'],'锁定解释')
    def test_old_backlog_has_a_research_key_without_live_inbox(self):
        self.assertEqual(self.store.window(KEY),[])
        self.assertIn(KEY,self.store.learning_keys())
        self.assertEqual(self.store.research_targets(KEY)[0]['id'],self.i)

class LearningEvidenceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=knowledge_tests.LearningTests.asyncSetUp
    asyncTearDown=knowledge_tests.LearningTests.asyncTearDown
    async def test_context_research_can_save_without_web_search(self):
        rows=[dict(key=KEY,message_id='x',text='咕咕航线就是临时放鸽子的意思')]
        i=self.service.knowledge.submit_slang(KEY,'咕咕航线',rows)['id']
        self.fake.answer=json.dumps([dict(content='咕咕航线',meaning='临时放鸽子',confirmed=True,basis='explicit',
            evidence=[dict(message_id='x',quote=rows[0]['text'])],sources=[])])
        self.assertTrue(await self.learner.tick())
        self.assertEqual(self.service.knowledge.known_slang()[0]['meaning'],'临时放鸽子')
    async def test_explicit_research_request_can_revisit_frequent_words(self):
        self.service.knowledge.submit_slang(KEY,'芜湖起飞',[dict(message_id='old',text='芜湖起飞')])
        with self.store.db:
            self.store.db.execute("UPDATE knowledge_slang SET status='learned',meaning='旧用法',count=128,last_research_count=128")
        knowledge_tests.LearningTests.feed(self)
        row=self.service.knowledge.window(KEY)[0]
        self.fake.answer=json.dumps([dict(content='芜湖起飞',source_id=str(row['seq']),meaning='',needs_search=True)])
        await self.learner.tick()
        self.assertEqual(self.service.knowledge.research_targets(KEY)[0]['content'],'芜湖起飞')

    async def test_failed_research_is_retryable_after_backoff(self):
        i=self.service.knowledge.submit_slang(KEY,'芜湖起飞',[dict(message_id='x',text='芜湖起飞')])['id']
        self.fake.error=dsh.BridgeError('timeout');await self.learner.tick()
        self.assertEqual(self.service.knowledge.research_targets(KEY)[0]['id'],i)
        self.assertFalse(await self.learner.tick())

if __name__=='__main__':unittest.main()
