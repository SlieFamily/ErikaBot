import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import test_agent_chat as core


class ProactiveTests(unittest.IsolatedAsyncioTestCase):
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
        self.assertIn('自主发言机会', self.client.prompts[0][1])
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
        async def reply(sid, text):
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
