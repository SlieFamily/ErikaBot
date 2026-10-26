"""Session role bootstrap and durable incremental input, including recovery boundaries."""
import asyncio
import unittest

import test_agent_chat as core


class IncrementalTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = core.ServiceTests.asyncSetUp
    asyncTearDown = core.ServiceTests.asyncTearDown
    submit = core.ServiceTests.submit
    send = core.ServiceTests.send

    def payloads(self, index):
        return self.client.prompts[index][1]

    async def test_role_once_and_new_messages_only_including_passive_observations(self):
        await self.submit(core.message(mid='one'))
        self.service.observe(core.message(mid='passive', directed=False))
        await self.submit(core.message(mid='two'))
        self.assertIn('ADMIN_ROLE_CANARY', self.payloads(0))
        self.assertNotIn('ADMIN_ROLE_CANARY', self.payloads(1))
        self.assertIn('完整角色设定', self.payloads(1))
        self.assertNotIn('"message_id":"one"', self.payloads(1))
        for mid in ('passive', 'two'):
            self.assertIn('"message_id":"' + mid + '"', self.payloads(1))

    async def test_restart_retains_delivery_marker(self):
        await self.submit(core.message(mid='one'))
        path = self.store.db.execute('PRAGMA database_list').fetchone()[2]
        await self.service.close()
        self.store = core.Store(path)
        self.client.closed = False
        self.service = core.ChatService(core.cfg(), self.store, self.client)
        await self.submit(core.message(mid='two'))
        self.assertEqual(len(self.client.created), 1)
        self.assertNotIn('ADMIN_ROLE_CANARY', self.payloads(1))
        self.assertNotIn('"message_id":"one"', self.payloads(1))

    async def test_compaction_refreshes_role_but_not_already_seen_chat(self):
        await self.submit(core.message(mid='one'))
        async def compacted(sid, since=None): return 100, True
        self.client.context_state = compacted
        await self.submit(core.message(mid='two'))
        self.assertIn('ADMIN_ROLE_CANARY', self.payloads(1))
        self.assertNotIn('"message_id":"one"', self.payloads(1))

    async def test_missing_session_rebuilds_full_prompt_and_context(self):
        await self.submit(core.message(mid='one'))
        original = self.client.reply
        async def missing_once(sid, text, images=None, **kwargs):
            if sid == 'session-0': raise core.dsh.MissingSession('dsh_session_missing')
            return await original(sid, text)
        self.client.reply = missing_once
        await self.submit(core.message(mid='two'))
        self.assertEqual(len(self.client.created), 2)
        self.assertIn('ADMIN_ROLE_CANARY', self.payloads(1))
        self.assertIn('"message_id":"one"', self.payloads(1))
        self.assertIn('"message_id":"two"', self.payloads(1))

    async def test_failed_turn_does_not_advance_delivery(self):
        await self.submit(core.message(mid='one'))
        before = self.store.delivery(core.message().key, 'session-0')
        self.client.error = core.dsh.BridgeError('dsh_stream_disconnected')
        await self.submit(core.message(mid='two'))
        self.assertEqual(self.store.delivery(core.message().key, 'session-0'), before)
        self.assertEqual(self.store.session(core.message().key)[2], 1)

    async def test_new_input_during_generation_remains_pending_and_silence_is_acknowledged(self):
        original = self.client.reply
        async def receive_during_turn(sid, text, images=None, **kwargs):
            self.service.observe(core.message(mid='arrived-later', directed=False))
            return await original(sid, text)
        self.client.reply = receive_during_turn
        self.client.answer = '[SILENT]'
        await self.submit(core.message(mid='one'))
        self.assertEqual(len(self.sent), 1)  # Direct silence produces a clarification.
        self.client.reply = original
        await self.submit(core.message(mid='two'))
        self.assertNotIn('"message_id":"one"', self.payloads(1))
        self.assertIn('"message_id":"arrived-later"', self.payloads(1))
        self.assertNotIn('ADMIN_ROLE_CANARY', self.payloads(1))

    async def test_legacy_session_bootstraps_without_rotating_or_resetting(self):
        await self.submit(core.message(mid='one'))
        self.store.db.execute('DROP TABLE delivery'); self.store.db.commit()
        path = self.store.db.execute('PRAGMA database_list').fetchone()[2]
        self.store.close(); self.store = core.Store(path); self.service.store = self.store
        await self.submit(core.message(mid='two'))
        self.assertEqual(len(self.client.created), 1)
        self.assertIn('ADMIN_ROLE_CANARY', self.payloads(1))
        self.assertIn('"message_id":"one"', self.payloads(1))

    async def test_reset_and_forward_toggle_require_new_seed(self):
        self.service.cfg.agent_chat_forward_persona = False
        await self.submit(core.message(mid='one'))
        self.assertNotIn('ADMIN_ROLE_CANARY', self.payloads(0))
        self.service.cfg.agent_chat_forward_persona = True
        await self.submit(core.message(mid='two'))
        self.assertIn('ADMIN_ROLE_CANARY', self.payloads(1))
        await self.service.reset(core.message().key)
        await self.submit(core.message(mid='three'))
        self.assertIn('ADMIN_ROLE_CANARY', self.payloads(2))
        self.assertNotIn('"message_id":"one"', self.payloads(2))

    async def test_image_lookup_still_sees_recent_context(self):
        await self.submit(core.message(mid='picture'))
        seen = []
        async def prepare(history,pending):
            seen.extend(m['message_id'] for m in history)
            return [], ''
        msg = core.message(mid='ask-picture')
        self.service.observe(msg); self.service.schedule(msg, self.send, prepare)
        await asyncio.gather(*list(self.service.tasks.values()))
        self.assertEqual(seen, ['picture', 'ask-picture'])
        self.assertNotIn('"message_id":"picture"', self.payloads(1))
