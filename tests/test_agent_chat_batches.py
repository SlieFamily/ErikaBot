"""Accepted bursts survive background chatter, in-flight work and transient failures."""
import asyncio
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

import test_agent_chat as core


class BatchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=core.ServiceTests.asyncSetUp
    asyncTearDown=core.ServiceTests.asyncTearDown
    send=core.ServiceTests.send
    submit=core.ServiceTests.submit

    def enqueue(self,mid,uid='7',**kwargs):
        msg=replace(core.message(mid=mid),user_id=uid,name='成员'+uid,**kwargs)
        self.service.observe(msg)
        return self.service.schedule(msg,self.send)

    async def drain(self):
        async def workers():
            while self.service.tasks:await asyncio.gather(*list(self.service.tasks.values()))
        await asyncio.wait_for(workers(),5)
        if self.service.notice_tasks:
            # Progress tasks have been cancelled; bounded immediate notices may remain.
            await asyncio.wait_for(asyncio.gather(*list(self.service.notice_tasks)),5)

    def targets(self,index):
        prompt=self.client.prompts[index][1]
        return json.loads(prompt.split('本轮待答的是以下消息ID对应的直接提问：',1)[1].split('。',1)[0])

    async def test_every_person_in_burst_is_retained_even_if_history_is_evicted(self):
        self.store.history_limit=3
        for mid,uid in [('first','7'),('second','8'),('third','9')]:self.assertTrue(self.enqueue(mid,uid))
        for i in range(12):self.service.observe(core.message(mid='noise-'+str(i),directed=False))
        await self.drain()
        self.assertEqual(len(self.client.prompts),1)
        self.assertEqual(self.targets(0),['first','second','third'])
        for mid in self.targets(0):self.assertIn('"message_id":"'+mid+'"',self.client.prompts[0][1])
        self.assertEqual(len(self.sent),1)

    async def test_arrivals_during_generation_form_a_separate_complete_batch(self):
        entered,release=asyncio.Event(),asyncio.Event();original=self.client.reply
        async def slow(sid,text,*args,**kwargs):
            if not entered.is_set():entered.set();await release.wait()
            return await original(sid,text,*args,**kwargs)
        self.client.reply=slow
        self.enqueue('first')
        await asyncio.wait_for(entered.wait(),2)
        self.enqueue('second','8');self.enqueue('third','9')
        release.set();await self.drain()
        self.assertEqual([self.targets(i) for i in range(2)],[['first'],['second','third']])
        self.assertEqual(len(self.client.created),1)
        self.assertEqual(len(self.sent),2)

    async def test_duplicate_and_ambient_message_cannot_overwrite_direct_batch(self):
        self.assertTrue(self.enqueue('one'))
        self.assertFalse(self.enqueue('one'))
        self.assertTrue(self.enqueue('two','8'))
        self.service.cfg.agent_chat_ambient_probability=.2
        with patch('random.random',return_value=0):self.assertFalse(self.enqueue('ambient',directed=False))
        await self.drain()
        self.assertEqual(self.targets(0),['one','two'])

    async def test_overflow_is_visible_and_retains_previously_accepted_questions(self):
        self.service.cfg.agent_chat_batch_limit=2
        self.assertTrue(self.enqueue('one'));self.assertTrue(self.enqueue('two'))
        self.assertFalse(self.enqueue('three'));self.assertFalse(self.enqueue('four'))
        await self.drain()
        self.assertEqual(self.targets(0),['one','two'])
        self.assertEqual(sum('排满' in s for s in self.sent),1)

    async def test_fresh_question_survives_an_older_question_expiring(self):
        self.enqueue('old');self.service.pending[core.message().key].enqueued_at-=601
        self.enqueue('fresh','8');await self.drain()
        self.assertEqual(self.targets(0),['fresh'])
        self.assertTrue(any('过期' in s for s in self.sent))
        self.assertEqual(len(self.client.prompts),1)

    async def test_slow_batch_gets_one_notice_then_one_answer(self):
        entered,release=asyncio.Event(),asyncio.Event();original=self.client.reply
        self.service.cfg.agent_chat_notice_after=.01
        async def slow(sid,text,*args,**kwargs):
            entered.set();await release.wait();return await original(sid,text,*args,**kwargs)
        self.client.reply=slow
        self.enqueue('one');self.enqueue('two','8');await asyncio.wait_for(entered.wait(),2)
        await asyncio.sleep(.04)
        self.assertEqual(len(self.sent),1);self.assertIn('处理中',self.sent[0])
        release.set();await self.drain()
        self.assertEqual(len(self.sent),2)
        await asyncio.sleep(.02);self.assertEqual(len(self.sent),2)

    async def test_fast_batch_cancels_waiting_notice(self):
        self.service.cfg.agent_chat_notice_after=.03
        self.enqueue('one');await self.drain();await asyncio.sleep(.06)
        self.assertEqual(self.sent,['你好呀'])

    async def test_confirmed_timeout_resumes_future_input_without_replaying_failed_question(self):
        original=self.client.reply;attempts=0
        async def fail_once(sid,text,*args,**kwargs):
            nonlocal attempts
            attempts+=1
            if attempts==1:
                self.enqueue('next','8')
                raise core.dsh.BridgeError('dsh_turn_timeout')
            return await original(sid,text,*args,**kwargs)
        async def clean(sid):return 30
        self.client.reply=fail_once;self.client.recovery_checkpoint=clean
        self.enqueue('failed');await self.drain()
        self.assertEqual(attempts,2)
        self.assertEqual(self.targets(0),['next'])
        self.assertEqual(self.store.session(core.message().key)[2],0)
        self.assertEqual(len(self.client.created),1)
        self.assertTrue(any('先跳过' in s for s in self.sent))
        self.assertEqual(self.sent[-1],'你好呀')

    async def test_foreign_session_or_failed_cancel_keeps_pause(self):
        self.client.error=core.dsh.BridgeError('dsh_turn_timeout')
        async def foreign(sid):raise core.dsh.BridgeError('recovery_foreign_input')
        self.client.recovery_checkpoint=foreign
        await self.submit(core.message())
        self.assertEqual(self.store.session(core.message().key)[2],1)
        charged=self.store.calls(core.message().key,0)[0]
        await self.submit(core.message(mid='next'))
        self.assertEqual(len(self.client.prompts),1)
        self.assertEqual(self.store.calls(core.message().key,0)[0],charged)
        self.assertTrue(any('ai 恢复' in s for s in self.sent))

    async def test_ambient_silence_stays_quiet(self):
        self.client.answer='[SILENT]';self.service.cfg.agent_chat_ambient_probability=.2
        self.service.cfg.agent_chat_quiet_start=self.service.cfg.agent_chat_quiet_end=0
        with patch('random.random',return_value=0):self.assertTrue(self.enqueue('ambient',directed=False))
        await self.drain();self.assertEqual(self.sent,[])

    async def test_uncertain_final_delivery_never_sends_an_error_or_retries(self):
        sends=[]
        async def uncertain(text):sends.append(text);raise TimeoutError()
        msg=core.message();self.service.observe(msg);self.service.schedule(msg,uncertain)
        await self.drain()
        self.assertEqual(sends,['你好呀'])
        self.assertEqual(self.store.session(msg.key)[2],1)
        self.assertEqual(self.store.db.execute('SELECT status FROM dispatches').fetchone()[0],'delivery_uncertain')

    async def test_new_question_during_quota_notice_is_not_erased_at_worker_exit(self):
        self.service.cfg.agent_chat_max_calls_per_hour=1
        await self.submit(core.message(mid='previous'))
        async def notice(text):
            self.sent.append(text)
            if '额度' in text:
                # The prior rolling-window charge expires while the notice is sent.
                with self.store.db:self.store.db.execute('UPDATE dispatches SET created=created-3601')
                self.enqueue('new-after-window')
                await asyncio.sleep(0)
        msg=core.message(mid='limited');self.service.observe(msg);self.service.schedule(msg,notice)
        await self.drain()
        self.assertEqual(len(self.client.prompts),2)
        self.assertEqual(self.targets(1),['new-after-window'])

    async def test_accepted_image_question_survives_history_eviction_for_media_preparation(self):
        self.store.history_limit=2;seen=[]
        async def prepare(recent,pending):
            seen.extend(m['message_id'] for m in recent if m.get('media'));return [],''
        msg=replace(core.message(mid='image-question'),media=({'url':'https://example.invalid/image'},))
        self.service.observe(msg);self.service.schedule(msg,self.send,prepare)
        for i in range(6):self.service.observe(core.message(mid='noise'+str(i),directed=False))
        await self.drain()
        self.assertEqual(seen,['image-question'])
        self.assertEqual(self.targets(0),['image-question'])
