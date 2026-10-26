"""Queue admission and expiry are independent of gateway timestamps and model timeouts."""
import asyncio
from dataclasses import replace
import time
import unittest

import test_agent_chat as core


class QueueTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = core.ServiceTests.asyncSetUp
    asyncTearDown = core.ServiceTests.asyncTearDown
    send = core.ServiceTests.send
    submit = core.ServiceTests.submit

    async def test_fresh_request_survives_more_than_one_model_timeout_in_queue(self):
        self.service.cfg.agent_chat_queue_timeout = 600
        self.service.slots = asyncio.Semaphore(0)
        msg = core.message()
        self.service.observe(msg)
        self.assertTrue(self.service.schedule(msg, self.send))
        pending = self.service.pending[msg.key]
        pending.enqueued_at -= 301
        # Simulate the same elapsed time in the event timestamp after admission.
        pending.message = replace(msg, timestamp=msg.timestamp - 301)
        await asyncio.sleep(0)
        self.assertFalse(self.client.prompts)
        self.service.slots.release()
        await asyncio.gather(*list(self.service.tasks.values()))
        self.assertEqual(len(self.sent), 1)

    async def test_configured_expiry_drops_request_without_model_call_or_quota_charge(self):
        self.service.cfg.agent_chat_queue_timeout = 180
        msg = core.message()
        self.service.observe(msg)
        self.assertTrue(self.service.schedule(msg, self.send))
        self.service.pending[msg.key].enqueued_at -= 181
        await asyncio.gather(*list(self.service.tasks.values()))
        self.assertFalse(self.client.prompts)
        self.assertEqual(len(self.sent),1)
        self.assertIn("过期",self.sent[0])
        self.assertEqual(self.store.calls(msg.key, 0)[0], 0)

    async def test_old_gateway_snapshot_is_rejected_before_entering_longer_queue(self):
        msg = replace(core.message(), timestamp=time.time() - 121)
        self.service.observe(msg)
        self.assertFalse(self.service.schedule(msg, self.send))
        self.assertFalse(self.service.tasks)
        self.assertFalse(self.client.prompts)

    async def test_sixtieth_turn_allowed_and_sixty_first_still_limited(self):
        self.service.cfg.agent_chat_max_calls_per_hour = 60
        key = core.message().key
        for _ in range(59):
            dispatch = self.store.begin(key)
            self.store.finish(dispatch, 'silent')
        await self.submit(core.message())
        await self.submit(core.message(mid='2'))
        self.assertEqual(len(self.sent), 2)
        self.assertIn("额度",self.sent[-1])
        self.assertEqual(len(self.client.prompts),1)
        self.assertEqual(self.store.calls(key, time.time() - 3600)[0], 60)
