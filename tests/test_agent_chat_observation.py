"""Post-send observation is event driven, bounded and independent of ambient lottery."""
import asyncio
import importlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from test_agent_chat import PACKAGE,cfg,ChatService,Store,FakeClient,domain

KEY='100:group:42'
class ObservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db')
        self.client=FakeClient();self.sent=[]
        self.service=ChatService(cfg(agent_chat_observation_enabled=True,agent_chat_ambient_probability=0,
            agent_chat_ambient_quiet_enabled=False),self.store,self.client)
    async def asyncTearDown(self):await self.service.close();self.tmp.cleanup()
    async def send(self,text):self.sent.append(text)
    async def ask(self,mid,directed=False,user='7',text='那下一局呢？',reply_to='',send=None):
        m=domain.ChatMessage(KEY,str(mid),user,'群友',text,time.time(),directed,reply_to=reply_to)
        self.service.observe(m);queued=self.service.schedule(m,send or self.send)
        await asyncio.gather(*list(self.service.tasks.values()))
        return queued
    async def test_related_followup_bypasses_lottery_and_reuses_session(self):
        await self.ask(1,True);sid=self.store.session(KEY)[0]
        self.assertTrue(await self.ask(2))
        self.assertEqual(len(self.sent),2);self.assertEqual(self.store.session(KEY)[0],sid)
        self.assertIn('发送后观察',self.client.prompts[-1][1])
        self.assertFalse(await self.ask(3,user='8'))
        self.assertFalse(self.service.tasks);self.assertFalse(self.service.slots.locked())
        before=len(self.client.prompts);await asyncio.sleep(.01);self.assertEqual(len(self.client.prompts),before)
    async def test_three_calls_do_not_reset_observation_budget(self):
        await self.ask(1,True);window=self.service.observer.get(KEY);deadline=window.until
        for i in range(2,5):self.assertTrue(await self.ask(i))
        self.assertEqual(window.calls,3);self.assertEqual(window.until,deadline)
        self.assertFalse(await self.ask(5));self.assertEqual(len(self.sent),4)
    async def test_expiry_and_silent_or_goodbye_end_observation(self):
        await self.ask(1,True);self.service.observer.get(KEY).until=time.monotonic()-1
        self.assertFalse(await self.ask(2))
        await self.ask(3,True);self.client.answer='[SILENT]'
        self.assertTrue(await self.ask(4));self.assertIsNone(self.service.observer.get(KEY))
        self.client.answer='好啊';await self.ask(5,True)
        self.assertFalse(await self.ask(6,text='晚安'));self.assertIsNone(self.service.observer.get(KEY))
    async def test_direct_requests_remain_unconditional_and_reset_window(self):
        await self.ask(1,True);old=self.service.observer.get(KEY).generation
        self.service.observer.get(KEY).calls=3
        self.assertTrue(await self.ask(2,True,user='8'))
        self.assertGreater(self.service.observer.get(KEY).generation,old)
        self.assertEqual(self.service.observer.get(KEY).calls,0)
        await self.service.reset(KEY);self.assertIsNone(self.service.observer.get(KEY))
    async def test_failed_uncertain_or_empty_answer_does_not_arm(self):
        async def failed(text):return False
        await self.ask(1,True,send=failed);self.assertIsNone(self.service.observer.get(KEY))
        self.client.answer='<thinking>reason</thinking>'
        await self.ask(2,True);self.assertIsNone(self.service.observer.get(KEY))
        async def uncertain(text):raise OSError('lost ack')
        self.client.answer='回复';await self.ask(3,True,send=uncertain)
        self.assertIsNone(self.service.observer.get(KEY))
    async def test_nighttime_only_blocks_idle_speech(self):
        await self.ask(1,True)
        with patch.object(self.service,'quiet',return_value=True):
            self.assertTrue(await self.ask(2))
            self.assertFalse(self.service.due(self.store.activity(KEY),time.time()))
    async def test_reply_to_observed_anchor_can_join_and_other_group_isolated(self):
        await self.ask(1,True)
        self.assertTrue(await self.ask(2,user='8',reply_to='1'))
        self.assertIn('8',self.service.observer.get(KEY).participants)
        other=domain.ChatMessage('100:group:43','3','7','群友','接着聊',time.time())
        self.service.observe(other);self.assertIsNone(self.service.observer.offer(other))
    async def test_expired_pending_or_already_consumed_followup_skips_model(self):
        await self.ask(1,True)
        m=domain.ChatMessage(KEY,'2','7','群友','继续',time.time());self.service.observe(m)
        generation=self.service.observer.offer(m)
        self.service.observer.get(KEY).until=time.monotonic()-1
        self.assertFalse(self.service.observer.claim(m,generation))
        self.assertEqual(len(self.client.prompts),1)
    async def test_restart_does_not_replay_observation(self):
        await self.ask(1,True)
        observer=importlib.import_module(PACKAGE+'.observation').ReplyObserver(self.service.cfg,self.store)
        self.assertIsNone(observer.get(KEY))

if __name__=='__main__':unittest.main()
