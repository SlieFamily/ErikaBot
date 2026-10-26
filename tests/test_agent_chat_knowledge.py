import asyncio
import importlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from test_agent_chat import PACKAGE, cfg, domain, dsh, Store, ChatService, FakeClient, message

k=importlib.import_module(PACKAGE+'.knowledge')
kb=importlib.import_module(PACKAGE+'.knowledge_bridge')
learning=importlib.import_module(PACKAGE+'.learning')
admin=importlib.import_module(PACKAGE+'.knowledge_admin')
KEY='100:group:42'
OTHER='100:group:43'
TOKEN='a'*64


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.store=k.KnowledgeStore(self.db)

    def tearDown(self):self.db.close()

    def sample(self,mid='1',text='今天芜湖起飞',key=KEY):
        return {'key':key,'message_id':mid,'text':text,'name':'群友','user_id':'7'}

    def test_scoped_expiry_merge_capacity_and_member_identity(self):
        with patch.object(k.time,'time',return_value=1000):
            self.store.append_memory(KEY,'activeTopic','约战',{'participants':['甲'],'pendingQuestion':'周末吗'})
            self.store.append_memory(KEY,'activeTopic','约战',{'participants':['乙']})
            self.store.append_memory(KEY,'pendingThought','想聊法环')
            self.store.append_memory(KEY,'memberImpression','喜欢法环',{'target':'7'},{'7':'群友'})
            self.assertEqual(self.store.memory(OTHER),[])
            topic=self.store.memory(KEY,'activeTopic')[0]
            self.assertEqual(topic['extra']['participants'],['甲','乙'])
            self.assertEqual(topic['extra']['pendingQuestion'],'周末吗')
            with self.assertRaises(k.KnowledgeError):
                self.store.append_memory(KEY,'memberImpression','好人',{'target':'重名'},{'7':'重名','8':'重名'})
            for n in range(25):self.store.append_memory(KEY,'activeTopic',f'话题{n}')
            self.assertEqual(len(self.store.memory(KEY,'activeTopic')),20)
        with patch.object(k.time,'time',return_value=1000+7201):
            self.assertEqual(self.store.memory(KEY,'pendingThought'),[])
        with patch.object(k.time,'time',return_value=1000+86401):
            self.assertEqual(len(self.store.memory(KEY)),1)
            self.assertEqual(self.store.memory(KEY)[0]['extra']['target'],'7')

    def test_persistence_and_reset_are_separate_from_memory(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(Path(folder)/'state')
            knowledge=k.KnowledgeStore(store.db)
            knowledge.append_memory(KEY,'memberImpression','喜欢FPS',{'target':'7'},{'7':'群友'})
            store.bind(KEY,'session-one','policy')
            store.reset(KEY)
            store.close()
            store=Store(Path(folder)/'state')
            self.assertEqual(len(k.KnowledgeStore(store.db).memory(KEY)),1)
            self.assertIsNone(store.session(KEY))
            store.close()

    def test_restart_invalidates_interrupted_learner_but_keeps_budget(self):
        self.store.bind_learner(KEY,'uncertain-session','p')
        run=self.store.begin_learning(KEY,'research',12)
        restored=k.KnowledgeStore(self.db)
        self.assertIsNone(restored.learning_state(KEY)[2])
        self.assertEqual(restored.learning_count(),1)
        self.assertEqual(self.db.execute('SELECT status FROM knowledge_runs WHERE id=?',(run,)).fetchone()[0],'interrupted')

    def test_snapshot_is_bounded_revisioned_and_clears_deleted_items(self):
        for n in range(8):self.store.add_manual_slang('词条'+str(n),'解'*300)
        for n in range(20):self.store.append_memory(KEY,'activeTopic',str(n)+'话'*195)
        stamp,text=self.store.snapshot(KEY)
        self.assertLess(len(text),6200)
        self.assertTrue(self.store.needs_snapshot(KEY,'s',stamp))
        self.store.delivered(KEY,'s',stamp)
        self.assertFalse(self.store.needs_snapshot(KEY,'s',stamp))
        self.assertTrue(self.store.needs_snapshot(KEY,'new-session',stamp))
        self.store.clear_memory(KEY)
        new,text=self.store.snapshot(KEY)
        self.assertNotEqual(new,stamp)
        self.assertIn('"memory":[]',text)

    def test_grounded_candidate_counts_dedup_rejected_review_and_no_evidence_leak(self):
        rows=[self.sample(str(n)) for n in range(30)]
        result=self.store.submit_slang(KEY,'芜湖起飞',rows)
        i=result['id']
        self.assertEqual(result['new_evidence'],20)
        self.assertEqual(self.store.submit_slang(KEY,'芜湖起飞',rows)['new_evidence'],0)
        self.assertEqual(self.store.slang_for_admin(OTHER),[])
        self.assertEqual(self.store.confirmed_slang(),[])
        with self.assertRaises(k.KnowledgeError):self.store.review_slang(OTHER,i,'confirm','解释')
        with self.assertRaises(k.KnowledgeError):self.store.submit_slang(KEY,'凭空编造',rows)
        self.store.review_slang(KEY,i,'confirm','开心或起飞的调侃')
        text=self.store.snapshot(OTHER)[1]
        self.assertIn('开心或起飞的调侃',text)
        self.assertNotIn('今天芜湖起飞',text)
        self.store.review_slang(KEY,i,'reject')
        with self.assertRaises(k.KnowledgeError):self.store.submit_slang(KEY,'芜湖起飞',[self.sample('new')])

    def test_research_thresholds_attempt_backoff_and_manual_confirmation(self):
        i=self.store.submit_slang(KEY,'芜湖起飞',[self.sample()])['id']
        self.assertEqual(self.store.research_targets(KEY),[])
        self.store.submit_slang(KEY,'芜湖起飞',[self.sample('2')])
        self.assertEqual(self.store.research_targets(KEY)[0]['id'],i)
        self.store.research_attempted(i,2)
        self.assertEqual(self.store.research_targets(KEY),[])
        result={'content':'芜湖起飞','confirmed':True,'meaning':'调侃成功','sources':['https://example.com/source']}
        self.assertFalse(self.store.save_research(i,result,[]))
        self.assertTrue(self.store.save_research(i,result,result['sources']))
        self.assertEqual(self.store.confirmed_slang(),[])
        self.store.review_slang(KEY,i,'confirm')
        self.assertEqual(self.store.confirmed_slang()[0]['meaning'],'调侃成功')

    def test_model_submit_rate_limit_and_sensitive_data(self):
        for n in range(2):self.store.submit_slang(KEY,'芜湖起飞',[self.sample(str(n))],from_model=True)
        with self.assertRaises(k.KnowledgeError):
            self.store.submit_slang(KEY,'芜湖起飞',[self.sample('third')],from_model=True)
        for value in ['sk-abcdefghijklmnop','password:secret','QQ_BRIDGE_SEARCH_POLICY x','[CQ:at,qq=all]']:
            with self.assertRaises(k.KnowledgeError):self.store.append_memory(KEY,'activeTopic',value)
        with self.assertRaises(k.KnowledgeError):self.store.append_memory(KEY,'pendingThought','念头',{'expiresAtMs':-1})

    def test_learner_json_ignores_reasoning_and_grounding_is_literal(self):
        self.assertEqual(k.json_array('<thinking>[{"content":"假话"}]</thinking>\n```json\n[]\n```'),[])
        self.assertEqual(k.json_array('说明\n[{"content":"真词"}]')[0]['content'],'真词')
        with self.assertRaises(k.KnowledgeError):k.json_array('没有JSON')

    def test_admin_removal_scope_and_manual_global_definition(self):
        self.store.append_memory(OTHER,'activeTopic','别群话题')
        i=self.store.memory(OTHER)[0]['id']
        self.assertIn('0 条',admin.handle(self.store,KEY,f'忘记 {i}'))
        self.assertEqual(len(self.store.memory(OTHER)),1)
        self.assertIn('已确认',admin.handle(self.store,KEY,'黑话添加 芜湖起飞 | 兴奋时的调侃'))
        self.assertIn('兴奋时的调侃',admin.handle(self.store,OTHER,'黑话 已确认'))


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db=sqlite3.connect(':memory:');self.store=k.KnowledgeStore(self.db)
        self.hub=kb.KnowledgeHub(self.store,TOKEN)
        self.scope=self.hub.scope(KEY,[{'user_id':'7','name':'群友','message_id':'1','text':'芜湖起飞'}])
        self.app=FastAPI();kb.install_route(self.app,lambda:self.hub)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,client=('127.0.0.1',123)),base_url='http://127.0.0.1')

    async def asyncTearDown(self):await self.client.aclose();self.db.close()

    def body(self,**changes):
        return dict(dict(session_id='s',rpc_id='r',call_id='c',name='qq_memory_append',args={'category':'activeTopic','content':'一起玩游戏'}),**changes)

    async def post(self,body,token=TOKEN):
        return await self.client.post('/agent-chat/knowledge',json=body,headers={'Authorization':'Bearer '+token})

    async def test_auth_session_rpc_scope_and_idempotence(self):
        self.assertEqual((await self.post(self.body(),token='wrong')).status_code,403)
        self.assertEqual((await self.post(self.body())).json()['error'],'inactive_bridge_turn')
        with self.hub.lease(self.scope,'s','r'):
            self.assertEqual((await self.post(self.body(rpc_id='foreign'))).json()['error'],'inactive_bridge_turn')
            result=(await self.post(self.body())).json()
            self.assertTrue(result['ok'])
            self.assertEqual((await self.post(self.body())).json(),result)
            self.assertEqual(len(self.store.memory(KEY)),1)
            self.assertEqual(self.store.memory(OTHER),[])
            changed=self.body(args={'category':'activeTopic','content':'different'})
            self.assertEqual((await self.post(changed)).json()['error'],'call_id_reused')
            self.assertEqual((await self.post(self.body(call_id='other',args={'category':'activeTopic','content':'x','key':OTHER}))).json()['error'],'unexpected_argument')
        self.assertFalse(self.hub.leases)
        self.assertEqual((await self.post(self.body())).json()['error'],'inactive_bridge_turn')

    async def test_size_remote_access_and_per_turn_limits(self):
        response=await self.client.post('/agent-chat/knowledge',content=b'x'*8193,headers={'Authorization':'Bearer '+TOKEN})
        self.assertEqual(response.status_code,413)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app,client=('192.0.2.1',5)),base_url='http://test') as remote:
            self.assertEqual((await remote.post('/agent-chat/knowledge',json=self.body(),headers={'Authorization':'Bearer '+TOKEN})).status_code,403)
        with self.hub.lease(self.scope,'s','r'):
            for n in range(6):self.assertTrue((await self.post(self.body(call_id=str(n),name='qq_memory_query',args={}))).json()['ok'])
            self.assertEqual((await self.post(self.body(call_id='7'))).json()['error'],'knowledge_turn_limit')

    async def test_grant_does_not_enable_other_family_or_ungrounded_context(self):
        scope=self.hub.scope(KEY,[],memory=False)
        with self.hub.lease(scope,'s','r'):
            self.assertEqual((await self.post(self.body())).json()['error'],'tool_not_authorized')
            body=self.body(name='qq_slang_submit',args={'content':'凭空编造','context':'群里刚刚说了凭空编造'})
            self.assertEqual((await self.post(body)).json()['error'],'slang_not_grounded_in_chat')


class LearningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cfg=cfg(agent_chat_memory_enabled=True,agent_chat_slang_enabled=True,agent_chat_knowledge_token=TOKEN)
        self.client=FakeClient();self.store=Store(Path(self.tmp.name)/'db')
        self.service=ChatService(self.cfg,self.store,self.client)
        self.fake=FakeClient();self.learner=learning.SlangLearner(self.service,self.fake)

    async def asyncTearDown(self):
        await self.learner.close();await self.service.close();self.tmp.cleanup()

    def feed(self,n=10):
        for i in range(n):
            m=domain.ChatMessage(KEY,str(i),'7','群友','芜湖起飞',time.time())
            self.service.learn_message(m,m.text)

    async def test_extraction_is_grounded_and_research_stays_draft(self):
        self.feed()
        rows=self.service.knowledge.window(KEY)
        self.fake.answer=json.dumps([{'content':'芜湖起飞','source_id':str(rows[0]['seq'])},
                                    {'content':'杜撰词条','source_id':str(rows[0]['seq'])}])
        self.assertTrue(await self.learner.tick())
        result=self.service.knowledge.slang_for_admin(KEY)
        self.assertEqual(len(result),1);self.assertEqual(result[0]['count'],10)
        result[0].update(confirmed=True,meaning='兴奋的调侃',sources=['https://example.com/source'])
        self.fake.answer=dsh.ReplyText(json.dumps([result[0]]),1,result[0]['sources'])
        self.assertTrue(await self.learner.tick())
        self.assertEqual(self.service.knowledge.confirmed_slang(),[])
        self.assertEqual(self.service.knowledge.slang_for_admin(KEY)[0]['meaning'],'兴奋的调侃')
        self.assertFalse(await self.learner.tick())

    async def test_learning_failure_quota_restart_and_chat_priority(self):
        self.feed();self.store.bind(KEY,'chat-session','original-policy')
        self.service.pending[KEY]=object()
        self.assertFalse(await self.learner.tick());self.service.pending.clear()
        self.fake.error=dsh.BridgeError('timeout')
        self.assertTrue(await self.learner.tick())
        self.assertEqual(self.store.session(KEY),('chat-session','original-policy',0))
        self.assertEqual(self.service.knowledge.learning_count(),1)
        self.assertFalse(await self.learner.tick())
        self.assertIsNone(self.service.knowledge.learning_state(KEY)[2])
        self.assertIsNone(self.service.knowledge.begin_learning(KEY,'extract',1))

    async def test_incremental_snapshot_survives_reset_and_tool_changes(self):
        self.service.knowledge.append_memory(KEY,'memberImpression','喜欢法环',{'target':'7'},{'7':'群友'})
        sent=[]
        async def send(text):sent.append(text)
        async def ask(mid):
            m=message(mid=mid);self.service.observe(m);self.service.schedule(m,send)
            await self.service.tasks[KEY]
        await ask('1');await ask('2')
        self.assertIn('喜欢法环',self.client.prompts[0][1]);self.assertNotIn('喜欢法环',self.client.prompts[1][1])
        self.service.knowledge.clear_memory(KEY)
        await ask('3');self.assertIn('"memory":[]',self.client.prompts[-1][1])
        self.service.knowledge.append_memory(KEY,'activeTopic','周末开黑')
        await self.service.reset(KEY);await ask('4')
        self.assertIn('周末开黑',self.client.prompts[-1][1])
        self.assertNotEqual(self.client.prompts[0][0],self.client.prompts[-1][0])

    async def test_plaintext_window_filters_commands_private_and_stale_messages(self):
        for text in ['/ai 重置','ai黑话添加','password:secret','[CQ:at,qq=all]']:
            self.service.learn_message(message(mid=text),text)
        private=domain.ChatMessage('100:private:7','1','7','群友','芜湖起飞',time.time())
        self.service.learn_message(private,private.text)
        self.assertEqual(self.service.knowledge.window(KEY),[])
        self.feed(85);self.assertEqual(len(self.service.knowledge.window(KEY)),80)


class KnowledgeCollectorTests(unittest.TestCase):
    def collector(self):
        c=dsh.TurnCollector('r',knowledge_tools=k.TOOLS)
        c.push({'type':'turn/start','data':{'turn':1}})
        c.push({'type':'user/message','data':{'source':{'kind':'user','rpcId':'r'}}})
        return c

    def test_only_correlated_granted_calls_and_final_text_are_accepted(self):
        c=self.collector()
        c.push({'type':'assistant/message','data':{'turn':1,'message':{'content':[{'type':'text','text':'我记一下'}]}}})
        c.push({'type':'tool/call','data':{'turn':1,'name':'qq_memory_query','callId':'c'}})
        with self.assertRaises(dsh.BridgeError):c.push({'type':'turn/end','data':{'turn':1,'reason':'completed'}})
        c.push({'type':'tool/result','data':{'turn':1,'message':{'role':'tool','toolCallId':'c','source':{'kind':'tool','callId':'c'}}}})
        self.assertEqual(c.push({'type':'turn/end','data':{'turn':1,'reason':'completed'}}),'')
        with self.assertRaises(dsh.BridgeError):self.collector().push({'type':'tool/call','data':{'turn':1,'name':'bash','callId':'x'}})

    def test_exact_harness_repeat_notice_requires_observed_tools(self):
        notice={'type':'user/message','surfaceOp':'append','data':{'source':{'kind':'repeat-tool-reminder','form':'notice','summary':'qq_memory_query × 3'}}}
        with self.assertRaises(dsh.BridgeError):self.collector().push(notice)
        c=self.collector()
        for n in range(3):c.push({'type':'tool/call','data':{'turn':1,'name':'qq_memory_query','callId':str(n)}})
        self.assertIsNone(c.push(notice));self.assertTrue(c.owned)
        notice['data']['source']['rpcId']='forged'
        with self.assertRaises(dsh.BridgeError):c.push(notice)


class PrivateSetupTests(unittest.TestCase):
    def test_setup_empty_example_token_dry_run_idempotence_and_conflict(self):
        from test_agent_chat import ROOT
        spec=importlib.util.spec_from_file_location('knowledge_setup_test',ROOT/'scripts/setup_agent_chat_knowledge.py')
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);env=root/'bridge.env';profile=root/'profile';profile.mkdir()
            (profile/'package.json').write_text('{}')
            original='AGENT_CHAT_MEMORY_ENABLED=false\nAGENT_CHAT_KNOWLEDGE_TOKEN=\nKEEP=literal${value}\n'
            env.write_text(original)
            self.assertFalse(helper.setup(env,profile)['applied'])
            self.assertEqual(env.read_text(),original);self.assertFalse((profile/'.agent-chat').exists())
            result=helper.setup(env,profile,8081,True)
            private=json.loads((profile/'.agent-chat/knowledge-bridge.json').read_text())
            self.assertEqual(len(private['token']),64);self.assertNotIn(private['token'],json.dumps(result))
            updated=env.read_text();self.assertIn('KEEP=literal${value}',updated)
            helper.setup(env,profile,8081,True);self.assertEqual(env.read_text(),updated)
            env.write_text(updated.replace(private['token'],'b'*64))
            with self.assertRaises(ValueError):helper.setup(env,profile,8081,True)


if __name__=='__main__':unittest.main()
