import asyncio
import unittest
import test_agent_chat as base
from test_agent_chat import message,dsh


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=base.ServiceTests.asyncSetUp
    asyncTearDown=base.ServiceTests.asyncTearDown
    submit=base.ServiceTests.submit
    send=base.ServiceTests.send
    async def prepare_paused(self):
        await self.submit(message())
        self.bound=self.store.session(message().key)
        self.store.suspend(message().key)
        async def checkpoint(sid):return 30
        self.client.recovery_checkpoint=checkpoint

    async def test_resume_keeps_session_history_quotas_and_never_sends(self):
        await self.prepare_paused()
        self.store.append(message(mid='2'))
        before=len(self.sent);calls=self.store.calls(message().key,0)[0]
        self.assertEqual(await self.service.recover(message().key),'resumed')
        self.assertEqual(self.store.session(message().key),self.bound)
        self.assertEqual(len(self.store.recent(message().key,10)),2)
        self.assertEqual(len(self.sent),before)
        self.assertEqual(self.store.calls(message().key,0)[0],calls)
        delivered=self.store.delivery(message().key,self.bound[0])
        self.assertEqual(delivered[1:],(30,0))
        self.assertEqual(self.store.pending_messages(message().key,10,delivered[0])[0],[])

    async def test_unsafe_or_offline_recovery_preserves_pause(self):
        await self.prepare_paused()
        async def bad(sid):raise dsh.BridgeError('recovery_foreign_input')
        self.client.recovery_checkpoint=bad
        with self.assertRaises(dsh.BridgeError):await self.service.recover(message().key)
        self.assertEqual(self.store.session(message().key)[2],1)
        self.client.policy_value='changed'
        with self.assertRaisesRegex(dsh.BridgeError,'recovery_policy_changed'):await self.service.recover(message().key)

    async def test_uncertain_delivery_cannot_be_resumed_and_reset_abandons_it(self):
        await self.prepare_paused()
        dispatch=self.store.begin(message().key);self.store.finish(dispatch,'delivery_uncertain')
        with self.assertRaisesRegex(dsh.BridgeError,'recovery_delivery_uncertain'):await self.service.recover(message().key)
        await self.service.reset(message().key)
        self.assertIsNotNone(self.store.recovery_boundary(message().key))

    async def test_send_failure_is_durable_and_does_not_allow_recovery(self):
        async def fail_send(text):raise TimeoutError()
        msg=message();self.store.append(msg);self.service.schedule(msg,fail_send)
        await asyncio.gather(*list(self.service.tasks.values()))
        self.assertEqual(self.store.db.execute('SELECT status FROM dispatches').fetchone()[0],'delivery_uncertain')
        with self.assertRaisesRegex(dsh.BridgeError,'recovery_delivery_uncertain'):await self.service.recover(msg.key)

    async def test_active_or_missing_mapping_does_not_call_or_reset_model(self):
        self.assertEqual(await self.service.recover(message().key),'missing')
        await self.submit(message())
        self.assertEqual(await self.service.recover(message().key),'active')
        self.assertEqual(len(self.client.prompts),1)
