"""Optional incoming poke reactions: native notice identity, independent chance and no forced answer."""
import asyncio,importlib,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_agent_chat import PACKAGE,cfg,ChatService,Store,FakeClient,domain,message
poke=importlib.import_module(PACKAGE+'.poke')
presentation=importlib.import_module(PACKAGE+'.presentation')
KEY='100:group:42'

class PokeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'db');self.client=FakeClient();self.sent=[]
        self.service=ChatService(cfg(agent_chat_observation_enabled=True,agent_chat_ambient_probability=.2,
            agent_chat_poke_reply_cooldown=0),self.store,self.client)
    async def asyncTearDown(self):await self.service.close();self.tmp.cleanup()
    async def send(self,text):self.sent.append(text)
    def notice(self,offset=0,user=7,group=42):return poke.poke_message('100',user,100,group,int(time.time())+offset)
    async def submit(self,m,roll):
        with patch.object(poke.random,'random',return_value=roll) as draw:
            queued=self.service.schedule_poke(m,self.send)
            await asyncio.gather(*list(self.service.tasks.values()))
            return queued,draw.call_count
    async def test_seventy_percent_silent_even_during_observation_and_not_ambient(self):
        m=message();self.service.observe(m);self.service.schedule(m,self.send)
        await asyncio.gather(*list(self.service.tasks.values()))
        before=len(self.client.prompts)
        self.assertEqual(await self.submit(self.notice(),.3),(False,1))
        self.assertEqual(await self.submit(self.notice(1),.99),(False,1))
        self.assertEqual(len(self.client.prompts),before)
        self.assertEqual(len(self.store.recent(KEY,200)),1)
    async def test_selected_poke_may_silence_without_direct_notice_or_search(self):
        self.client.answer='[SILENT]'
        self.assertEqual(await self.submit(self.notice(),.299),(True,1))
        self.assertFalse(self.sent);self.assertEqual(len(self.client.prompts),1)
        self.assertIn('戳一戳通知',self.client.prompts[0][1])
        self.assertNotIn('本轮待答的是以下消息ID对应的直接提问',self.client.prompts[0][1])
    async def test_successful_reply_opens_two_minute_window_and_configurable(self):
        before=time.monotonic();await self.submit(self.notice(),0)
        self.assertEqual(len(self.sent),1)
        window=self.service.observer.get(KEY)
        self.assertGreaterEqual(window.until,before+120)
        self.assertLess(window.until,time.monotonic()+121)
        self.assertEqual(cfg(agent_chat_observation_seconds=180).agent_chat_observation_seconds,180)
    async def test_duplicate_notice_does_not_reroll_and_cooldown_survives_restart(self):
        m=self.notice();self.assertEqual(await self.submit(m,.99),(False,1))
        self.assertEqual(await self.submit(m,0),(False,0))
        self.service.pokes.cfg.agent_chat_poke_reply_cooldown=30
        await self.submit(self.notice(1),0)
        gate=poke.PokeGate(self.store,self.service.cfg)
        with patch.object(poke.random,'random',return_value=0) as draw:
            self.assertFalse(gate.admit(self.notice(2)));draw.assert_not_called()
    async def test_allowlist_self_other_target_and_old_notice_ignored(self):
        for args in [(100,7,8,42,time.time()),(100,100,100,42,time.time()),(100,7,100,42,time.time()-121)]:
            self.assertIsNone(poke.poke_message(*args))
        self.assertEqual(await self.submit(self.notice(group=999),0),(False,0))
        self.assertEqual(await self.submit(self.notice(group=None),0),(False,0))
        self.service.cfg.agent_chat_private_users=frozenset({7})
        self.assertTrue((await self.submit(self.notice(group=None),0))[0])
        self.service.cfg.agent_chat_poke_reply_enabled=False
        self.assertEqual(await self.submit(self.notice(2),0),(False,0))
    async def test_poke_cannot_replace_pending_direct_question(self):
        direct=message(mid='normal');self.service.observe(direct);self.service.schedule(direct,self.send)
        with patch.object(poke.random,'random',return_value=0):
            self.assertFalse(self.service.schedule_poke(self.notice(),self.send))
        self.assertEqual(self.service.pending[KEY].kind,'direct')
        await asyncio.gather(*list(self.service.tasks.values()))
        self.assertEqual(len(self.client.prompts),1)
    async def test_notice_can_grant_actor_at_or_poke_but_never_quote_or_reaction(self):
        m=self.notice();row=m.payload()
        scope=presentation.social_targets([row],KEY,self.service.cfg)
        self.assertEqual(scope,dict(mentions={'7'},poke={'7'},reaction=set()))
        self.assertEqual(presentation.reply_targets([row],KEY),set())
        plan=presentation.parse('QQ_REPLY '+json.dumps(dict(text='干嘛😏',reply_to=m.message_id,faces=[],mentions=['7'],poke='7',reaction=dict(message_id=m.message_id,emoji='👍'))),set(),True,scope)
        self.assertEqual(plan.mentions,('7',));self.assertEqual(plan.poke,'7')
        self.assertFalse(plan.reply_to);self.assertFalse(plan.reaction)
        self.assertEqual(presentation.social_targets([dict(row,notice='')],KEY,self.service.cfg)['poke'],set())
    async def test_night_does_not_suppress_selected_reactive_poke(self):
        with patch.object(self.service,'quiet',return_value=True):
            self.assertTrue((await self.submit(self.notice(),0))[0])
        self.assertEqual(len(self.sent),1)
    async def test_no_poke_payload_enters_slang_or_memory_learning(self):
        self.service.learn_message=lambda *args: self.fail('notification must not be learned as speech')
        await self.submit(self.notice(),0)
        self.assertEqual(len(self.sent),1)

if __name__=='__main__':unittest.main()
