"""Native AnySearch turns, source correlation, quotas and failure boundaries."""
import asyncio
import importlib
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from test_agent_chat import PACKAGE, cfg, dsh, message, Store, ChatService, FakeClient
web = importlib.import_module(PACKAGE + '.search')
URL = 'https://example.com/article'

class CollectorTests(unittest.TestCase):
    def collector(self, enabled=True):
        calls=[]
        c=dsh.TurnCollector('mine',enabled,lambda:calls.append(1))
        c.push({'type':'turn/start','data':{'turn':1}})
        c.push({'type':'user/message','data':{'source':{'kind':'user','rpcId':'mine'}}})
        return c,calls
    def call(self,c,cid='a',name='web_search'):
        return c.push({'type':'tool/call','data':{'turn':1,'name':name,'callId':cid,'arguments':{'queries':['明日堇sumire']}}})
    def result(self,c,cid='a',error=False,url=URL):
        return c.push({'type':'tool/result','data':{'turn':1,'message':{'toolCallId':cid,'role':'tool',
            'source':{'kind':'tool','callId':cid},'isError':error,
            'content':[{'type':'text','text':'untrusted result'}]},'meta':{'sources':[{'url':url}]}}})
    def finish(self,c,text='答案'):
        c.push({'type':'assistant/message','data':{'turn':1,'message':{'content':[{'type':'reasoning','text':'private'}, {'type':'text','text':text}]}}})
        return c.push({'type':'turn/end','data':{'turn':1,'reason':{'kind':'completed'}}})
    def test_two_native_searches_same_turn_only_final_answer_and_real_sources(self):
        c,called=self.collector()
        c.push({'type':'assistant/message','data':{'turn':1,'message':{'content':[{'type':'text','text':'我去查查'}]}}})
        self.call(c);self.result(c)
        self.call(c,'b');self.result(c,'b',url='http://127.0.0.1/private')
        answer=self.finish(c,'看到了[原文]('+URL+')')
        self.assertEqual(called,[1]);self.assertEqual(answer.searches,2)
        self.assertEqual(answer.sources,(URL,))
        self.assertNotIn('我去查查',answer);self.assertNotIn('private',answer)
    def test_nonsearch_disabled_foreign_and_excess_calls_fail_closed(self):
        for enabled,name in [(False,'web_search'),(True,'bash'),(True,'web_fetch'),(True,'anysearch_batch_search')]:
            c,_=self.collector(enabled)
            with self.assertRaisesRegex(dsh.BridgeError,'unexpected_tool_call'):self.call(c,name=name)
        c,_=self.collector();self.call(c);self.result(c);self.call(c,'b');self.result(c,'b')
        with self.assertRaises(dsh.BridgeError):self.call(c,'c')
        c=dsh.TurnCollector('mine',True)
        with self.assertRaises(dsh.BridgeError):self.call(c)
    def test_unmatched_duplicate_and_missing_results_are_rejected(self):
        c,_=self.collector()
        with self.assertRaises(dsh.BridgeError):self.result(c,'foreign')
        self.call(c)
        with self.assertRaisesRegex(dsh.BridgeError,'incomplete_tool_results'):self.finish(c)
        self.result(c)
        with self.assertRaises(dsh.BridgeError):self.result(c)
    def test_search_error_can_be_explained_without_trusting_error_sources(self):
        c,_=self.collector();self.call(c);self.result(c,error=True)
        answer=self.finish(c,'暂时查不了')
        self.assertEqual(answer.sources,());self.assertEqual(answer,'暂时查不了')
    def test_compacted_surface_endpoint_ids_need_not_be_numeric_order(self):
        c,_=self.collector()
        c.push({'type':'compaction/start','data':{'turn':1,'compactionId':'c'}})
        c.push({'type':'user/message','surfaceOp':{'op':'replace','startSeq':182,'endSeq':158},
            'data':{'source':{'kind':'compact-checkpoint','compactionId':'c'}}})
        self.assertTrue(c.owned)
        for start,end in [(-1,2),(1,-1),(True,2)]:
            with self.assertRaises(dsh.BridgeError):
                c.push({'type':'user/message','surfaceOp':{'op':'replace','startSeq':start,'endSeq':end},
                    'data':{'source':{'kind':'compact-checkpoint','compactionId':'c'}}})

class OutputTests(unittest.TestCase):
    def test_only_returned_public_sources_are_sent(self):
        value=web.final_answer('资料[原文]('+URL+')，假链接 https://evil.com/x', [URL], True,600)
        self.assertIn(URL,value);self.assertNotIn('evil.com',value)
        self.assertNotIn('原文](',value)
        self.assertEqual(web.final_answer('[SILENT]',[URL],True,600),'')
        self.assertEqual(web.final_answer('leak '+web.CONTROL_PREFIX,[],False,600),'')
        self.assertEqual(web.final_answer('<tool_call>{"name":"web_search"}</tool_call>',[],False,600),'')
        self.assertLessEqual(len(web.final_answer('x'*700+' '+URL,[URL],True,100)),100)
    def test_private_source_url_rejected(self):
        for url in ['file:///secret','http://127.0.0.1/x','https://u:p@public.com','https://host.internal/x']:
            self.assertFalse(web.public_result_url(url))

class NativeClient(FakeClient):
    def __init__(self):
        super().__init__();self.answer='查到了[来源]('+URL+')';self.callback=None;self.searches=0;self.enabled=[]
    async def reply(self,sid,text,images=None,*,search_enabled=False,on_search=None):
        self.prompts.append((sid,text));self.enabled.append(search_enabled)
        if search_enabled:
            on_search();self.searches+=1
            if self.callback:await self.callback()
            if self.error:raise self.error
            return dsh.ReplyText(self.answer,1,[URL])
        return '直接回答'

class ServiceSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite3'
        self.store=Store(self.path);self.client=NativeClient();self.sent=[]
        self.service=ChatService(cfg(agent_chat_search_enabled=True),self.store,self.client)
    async def asyncTearDown(self):
        await self.service.close();self.tmp.cleanup()
    async def submit(self,msg=None):
        msg=msg or message()
        async def send(text):self.sent.append(text)
        self.service.observe(msg);self.service.schedule(msg,send)
        await asyncio.gather(*list(self.service.tasks.values()))
    async def test_one_dsh_turn_native_search_and_digestion_no_python_followup(self):
        await self.submit()
        self.assertEqual(len(self.client.prompts),1);self.assertEqual(self.client.searches,1)
        self.assertEqual(self.store.calls(message().key,0)[0],1)
        self.assertEqual(self.store.search_count(message().key),1)
        self.assertEqual(self.store.db.execute('SELECT stage FROM searches').fetchone()[0],'sent')
        self.assertIn(URL,self.sent[0])
    async def test_smalltalk_no_search_does_not_consume_search_quota(self):
        self.service.client=FakeClient();await self.submit()
        self.assertEqual(self.store.search_count(message().key),0)
        self.assertEqual(len(self.service.client.prompts),1)
    async def test_random_search_requires_opt_in(self):
        self.service.cfg.agent_chat_ambient_probability=.1
        with patch.object(self.service,'quiet',return_value=False),patch('random.random',return_value=0):
            await self.submit(replace(message(),directed=False))
            self.assertEqual(self.client.searches,0)
            self.service.cfg.agent_chat_search_ambient=True
            await self.submit(replace(message(mid='2'),directed=False))
            self.assertEqual(self.client.searches,1)
    async def test_search_fits_one_remaining_turn_and_quota_survives_reset(self):
        self.service.cfg=cfg(agent_chat_search_enabled=True,agent_chat_max_calls_per_hour=1)
        await self.submit();self.assertEqual(self.client.searches,1)
        self.service.cfg=cfg(agent_chat_search_enabled=True,agent_chat_search_max_per_hour=1)
        await self.service.reset(message().key)
        await self.submit(message(mid='2'))
        self.assertEqual(self.client.searches,1);self.assertFalse(self.client.enabled[-1])
    async def test_cancel_during_native_search_suspends_no_send(self):
        entered=asyncio.Event()
        async def block():entered.set();await asyncio.Event().wait()
        self.client.callback=block
        task=asyncio.create_task(self.submit())
        await asyncio.wait_for(entered.wait(),5)
        self.service.tasks[message().key].cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertFalse(self.sent);self.assertEqual(self.store.session(message().key)[2],1)
        self.assertEqual(self.store.db.execute('SELECT stage FROM searches').fetchone()[0],'cancelled')
    async def test_model_failure_suspends_and_does_not_retry(self):
        self.client.error=dsh.BridgeError('test_timeout');await self.submit()
        self.assertFalse(self.sent);self.assertEqual(self.store.session(message().key)[2],1)
        self.assertEqual(len(self.client.prompts),1)
    async def test_empty_final_gets_notice_but_silent_stays_silent(self):
        self.client.answer='';await self.submit()
        self.assertEqual(self.sent,['这次查询没能整理出可用答案，你换个关键词再试试。'])
        self.client.answer='[SILENT]';await self.submit(message(mid='2'))
        self.assertEqual(len(self.sent),1)
    async def test_late_arrival_during_native_search_not_marked_delivered(self):
        async def late():self.store.append(message(mid='late'))
        self.client.callback=late;await self.submit()
        sid=self.store.session(message().key)[0]
        after=self.store.delivery(message().key,sid)[0]
        pending,_=self.store.pending_messages(message().key,20,after)
        self.assertEqual([m['message_id'] for m in pending],['late'])
    async def test_internal_search_control_never_published(self):
        self.service.client=FakeClient();self.service.client.answer=web.CONTROL_PREFIX+'private'
        await self.submit();self.assertEqual(len(self.sent),1);self.assertNotIn('private',self.sent[0])
    async def test_interrupted_native_search_not_replayed_after_restart(self):
        for stage in ('searching','answered','sending'):
            key='g-'+stage
            self.store.bind(key,'sid-'+stage,'policy')
            dispatch=self.store.begin(key);self.store.begin_search(key,dispatch,6)
            self.store.search_stage(dispatch,stage)
        self.store.close();self.store=Store(self.path);self.service.store=self.store
        for stage in ('searching','answered','sending'):
            self.assertEqual(self.store.session('g-'+stage)[2],1)
        self.assertEqual(self.store.db.execute('SELECT DISTINCT stage FROM searches').fetchall(),[('interrupted',)])

if __name__ == '__main__':unittest.main()
