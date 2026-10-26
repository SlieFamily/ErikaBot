import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import test_agent_chat as core


class ProactiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_equal_quiet_boundaries_allow_every_hour_without_changing_limits(self):
        self.service.cfg.agent_chat_quiet_start = 0
        self.service.cfg.agent_chat_quiet_end = 0
        for hour in range(24):
            self.assertFalse(self.service.quiet(datetime(2026,10,25,hour,tzinfo=timezone.utc).timestamp()))
        self.idle()
        self.assertTrue(self.service.schedule_proactive(self.key, self.send))
        await self.drain()
        self.assertFalse(self.service.schedule_proactive(self.key, self.send))
    send = core.ServiceTests.send
    submit = core.ServiceTests.submit

    async def asyncSetUp(self):
        self.now = datetime(2026, 10, 25, 4, tzinfo=timezone.utc).timestamp()
        self.clock = patch('time.time', return_value=self.now); self.clock.start()
        await core.ServiceTests.asyncSetUp(self)
        self.service.cfg.agent_chat_proactive_enabled = True
        self.service.started_at = self.now - 120
        self.key = '100:group:42'
        self.counter = 0

    async def asyncTearDown(self):
        await core.ServiceTests.asyncTearDown(self)
        self.clock.stop()

    def idle(self):
        self.counter += 1
        self.service.observe(core.message(mid=str(self.counter)))
        with self.store.db:
            self.store.db.execute('UPDATE activity SET last_input=?,last_output=0 WHERE chat_key=?',
                                  (self.now - 901, self.key))

    async def drain(self):
        await asyncio.gather(*list(self.service.tasks.values()))

    async def test_only_one_idle_attempt_until_new_input_and_persisted_across_restart(self):
        self.idle()
        self.assertTrue(self.service.schedule_proactive(self.key, self.send))
        await self.drain()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('自主发言：', self.client.prompts[0][1])
        self.assertFalse(self.service.schedule_proactive(self.key, self.send))
        path = self.store.db.execute('PRAGMA database_list').fetchone()[2]
        self.store.close(); self.store = core.Store(path); self.service.store = self.store
        self.assertFalse(self.service.schedule_proactive(self.key, self.send))
        self.idle()
        self.assertTrue(self.service.schedule_proactive(self.key, self.send))
        await self.drain()
        self.assertEqual(len(self.sent), 2)

    async def test_daily_budget_survives_reset_and_day_rolls_over(self):
        for _ in range(6):
            self.idle()
            self.assertTrue(self.service.schedule_proactive(self.key, self.send))
            await self.drain()
        await self.service.reset(self.key)
        self.idle()
        self.assertFalse(self.service.schedule_proactive(self.key, self.send))
        self.assertEqual(self.store.activity(self.key)[6], 6)
        with self.store.db: self.store.db.execute("UPDATE activity SET day='2026-10-24' WHERE chat_key=?", (self.key,))
        self.assertTrue(self.service.schedule_proactive(self.key, self.send))
        await self.drain()
        self.assertEqual(self.store.activity(self.key)[6], 1)

    async def test_silent_attempt_consumes_idle_opportunity_and_budget(self):
        self.client.answer = '[SILENT]'
        self.idle(); self.service.schedule_proactive(self.key, self.send); await self.drain()
        self.assertEqual(self.sent, [])
        self.assertFalse(self.service.schedule_proactive(self.key, self.send))
        self.assertEqual(self.store.activity(self.key)[6], 1)

    async def test_new_message_during_generation_discards_stale_autonomous_answer(self):
        async def reply(sid, text, images=None, **kwargs):
            self.service.observe(core.message(mid='new'))
            return 'too late'
        self.client.reply = reply
        self.idle(); self.service.schedule_proactive(self.key, self.send); await self.drain()
        self.assertEqual(self.sent, [])

    async def test_quiet_hours_whitelist_private_and_rate_limit(self):
        self.idle()
        for key in ['100:group:43', '100:private:42']:
            self.assertFalse(self.service.schedule_proactive(key, self.send))
        night = datetime(2026, 10, 25, 16, tzinfo=timezone.utc).timestamp()
        self.assertTrue(self.service.quiet(night))
        with patch('time.time', return_value=night):
            self.assertFalse(self.service.schedule_proactive(self.key, self.send))
            with patch('random.random', return_value=0):
                self.assertFalse(self.service.schedule(replace(core.message(), directed=False), self.send))
        self.service.cfg.agent_chat_max_calls_per_hour = 1
        self.store.begin(self.key)
        self.service.schedule_proactive(self.key, self.send); await self.drain()
        self.assertEqual(self.sent, [])

    async def test_night_can_keep_random_and_direct_replies_but_never_idle_speech(self):
        self.service.cfg.agent_chat_ambient_quiet_enabled = False
        self.service.cfg.agent_chat_ambient_probability = .05
        night = datetime(2026, 10, 25, 16, tzinfo=timezone.utc).timestamp()
        with patch('time.time', return_value=night):
            self.idle()
            self.assertTrue(self.service.quiet())
            self.assertFalse(self.service.schedule_proactive(self.key, self.send))
            ambient = replace(core.message(mid='101'), directed=False)
            self.service.observe(ambient)
            with patch('random.random', return_value=.04):
                self.assertTrue(self.service.schedule(ambient, self.send))
            await self.drain()
            self.assertEqual(len(self.sent), 1)
            with patch('random.random', return_value=.06):
                self.assertFalse(self.service.schedule(replace(ambient,message_id='102'), self.send))
            direct = core.message(mid='103');self.service.observe(direct)
            self.assertTrue(self.service.schedule(direct, self.send))
            await self.drain()
            self.assertEqual(len(self.sent), 2)
            self.assertFalse(self.service.schedule_proactive(self.key, self.send))

    async def test_quiet_window_boundaries_remain_exact(self):
        for hour, minute, expected in [(14,59,False),(15,0,True),(0,59,True),(1,0,False)]:
            stamp=datetime(2026,10,25,hour,minute,tzinfo=timezone.utc).timestamp()
            self.assertEqual(self.service.quiet(stamp),expected)
            self.assertEqual(self.service.ambient_quiet(stamp),expected)
        self.service.cfg.agent_chat_ambient_quiet_enabled=False
        self.assertFalse(self.service.ambient_quiet(datetime(2026,10,25,16,tzinfo=timezone.utc).timestamp()))

    async def test_random_probability_and_direct_message_priority(self):
        self.service.cfg.agent_chat_ambient_probability = .1
        direct = core.message()
        ambient = replace(core.message(mid='2'), directed=False)
        self.service.observe(direct); self.service.observe(ambient)
        with patch('random.random', return_value=.2):
            self.assertFalse(self.service.schedule(ambient, self.send))
        self.assertTrue(self.service.schedule(direct, self.send))
        with patch('random.random', return_value=.01):
            self.assertFalse(self.service.schedule(ambient, self.send))
        await self.drain()
        with patch('random.random', return_value=.01):
            self.assertTrue(self.service.schedule(ambient, self.send))
        await self.drain()
        self.assertEqual(len(self.sent), 2)

    async def test_ambient_can_join_unaddressed_chat_and_choose_silence(self):
        self.service.cfg.agent_chat_ambient_probability = .05
        ambient = replace(core.message(), directed=False, text='今天下班路上又下雨了')
        self.service.observe(ambient)
        with patch('random.random', return_value=.01):
            self.assertTrue(self.service.schedule(ambient, self.send))
        await self.drain()
        self.assertEqual(len(self.sent), 1)
        self.assertIn('随机接话机会', self.client.prompts[-1][1])
        self.client.answer = '[SILENT]'
        ambient = replace(ambient, message_id='2', text='刚才那个人私下的事先别聊了')
        self.service.observe(ambient)
        with patch('random.random', return_value=.01):
            self.assertTrue(self.service.schedule(ambient, self.send))
        await self.drain()
        self.assertEqual(len(self.sent), 1)
        await self.submit(core.message(mid='3'))
        self.assertNotIn('随机接话机会', self.client.prompts[-1][1])
