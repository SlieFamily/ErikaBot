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
        async def checkpoint(sid, **kwargs):return 30
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

    async def test_idle_cold_session_recovers_without_cancel(self):
        await self.prepare_paused()
        async def cold_cancel(sid):
            raise dsh.MissingSession('dsh_session_missing')
        self.client.stop=cold_cancel
        self.assertEqual(await self.service.recover(message().key),'resumed')
        self.assertEqual(self.store.session(message().key),self.bound)

    async def test_foreign_or_offline_history_never_cancels(self):
        await self.prepare_paused()
        stops=[]
        async def stop(sid):stops.append(sid)
        self.client.stop=stop
        for code in ('recovery_foreign_input','dsh_stream_disconnected','recovery_history_unverified','dsh_session_missing'):
            async def checkpoint(sid):raise dsh.BridgeError(code)
            self.client.recovery_checkpoint=checkpoint
            with self.assertRaisesRegex(dsh.BridgeError,code):
                await self.service.recover(message().key)
            self.assertEqual(self.store.session(message().key)[2],1)
        self.assertEqual(stops,[])

    async def test_active_turn_still_requires_cancel_and_finished_checkpoint(self):
        await self.prepare_paused()
        stops=[]
        async def checkpoint(sid):
            if not stops:raise dsh.BridgeError('recovery_turn_active')
            return 31
        async def stop(sid):stops.append(sid)
        self.client.stop=stop;self.client.recovery_checkpoint=checkpoint
        self.assertEqual(await self.service.recover(message().key),'resumed')
        self.assertEqual(stops,[self.bound[0]])
        self.assertEqual(self.store.delivery(message().key,self.bound[0])[1],31)

    async def test_failed_active_cancel_never_unpauses(self):
        await self.prepare_paused()
        async def checkpoint(sid):raise dsh.BridgeError('recovery_turn_active')
        async def stop(sid):raise dsh.BridgeError('dsh_transport_or_protocol_error')
        self.client.stop=stop;self.client.recovery_checkpoint=checkpoint
        with self.assertRaises(dsh.BridgeError):await self.service.recover(message().key)
        self.assertEqual(self.store.session(message().key)[2],1)

    async def test_owner_skips_uncertain_reply_preserves_history_and_other_groups(self):
        await self.prepare_paused()
        key=message().key
        dispatch=self.store.begin(key);self.store.finish(dispatch,'delivery_uncertain')
        other=self.store.begin('100:group:999');self.store.finish(other,'delivery_uncertain')
        before=len(self.sent);calls=self.store.calls(key,0)[0]
        records=self.store.recent(key,10)
        self.assertEqual(await self.service.recover(key,owner=True),'resumed')
        self.assertEqual(self.store.session(key),self.bound)
        self.assertEqual(self.store.recent(key,10),records)
        self.assertEqual(self.store.calls(key,0)[0],calls)
        self.assertEqual(len(self.sent),before)
        statuses=dict(self.store.db.execute('SELECT id,status FROM dispatches'))
        self.assertEqual(statuses[dispatch],'owner_skipped')
        self.assertEqual(statuses[other],'delivery_uncertain')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM recovery_events').fetchone()[0],1)
        await self.service.recover(key,owner=True)
        self.assertEqual(len(self.sent),before)
        await self.submit(message(mid='new'))
        self.assertEqual(len(self.sent),before+1)
        self.assertEqual(self.store.session(key),self.bound)

    async def test_owner_accepts_finished_foreign_input_even_when_not_paused(self):
        await self.submit(message())
        calls=[]
        async def checkpoint(sid, *, allow_foreign=False):
            calls.append(allow_foreign)
            if not allow_foreign:raise dsh.BridgeError('recovery_foreign_input')
            return 42
        self.client.recovery_checkpoint=checkpoint
        bound=self.store.session(message().key)
        self.assertEqual(await self.service.recover(message().key,owner=True),'resumed')
        self.assertEqual(calls,[True])
        self.assertEqual(self.store.delivery(message().key,bound[0])[1],42)
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.client.stopped,[])

    async def test_owner_cancels_slow_model_and_discards_old_batch(self):
        await self.prepare_paused();key=message().key
        await self.service.recover(key)
        entered=asyncio.Event()
        async def slow(*args,**kwargs):
            entered.set();await asyncio.Event().wait()
        self.client.reply=slow
        second=message(mid='second');self.service.observe(second);self.service.schedule(second,self.send)
        await entered.wait()
        third=message(mid='third');self.service.observe(third);self.service.schedule(third,self.send)
        before=len(self.sent)
        self.assertEqual(await self.service.recover(key,owner=True),'resumed')
        self.assertFalse(self.service.tasks);self.assertFalse(self.service.pending)
        self.assertEqual(len(self.sent),before)
        self.assertEqual(self.store.session(key)[2],0)
        self.assertEqual(self.client.stopped,[self.bound[0]])

    async def test_owner_cancels_send_and_never_replays_its_unknown_result(self):
        await self.prepare_paused();key=message().key
        await self.service.recover(key)
        entered=asyncio.Event()
        async def slow_send(value):entered.set();await asyncio.Event().wait()
        msg=message(mid='second');self.service.observe(msg);self.service.schedule(msg,slow_send)
        await entered.wait()
        before=len(self.sent)
        await self.service.recover(key,owner=True)
        self.assertEqual(self.store.db.execute('SELECT status FROM dispatches ORDER BY id DESC LIMIT 1').fetchone()[0],'owner_skipped')
        self.assertEqual(len(self.sent),before)
        self.assertFalse(self.service.tasks)

    async def test_failed_owner_audit_never_acknowledges_uncertain_reply(self):
        await self.prepare_paused();key=message().key
        dispatch=self.store.begin(key);self.store.finish(dispatch,'delivery_uncertain')
        for code in ('dsh_stream_disconnected','unsafe_current_session_preset','recovery_history_unverified','dsh_session_missing'):
            async def bad(sid,**kwargs):raise dsh.BridgeError(code)
            self.client.recovery_checkpoint=bad
            with self.assertRaisesRegex(dsh.BridgeError,code):await self.service.recover(key,owner=True)
            self.assertEqual(self.store.session(key)[2],1)
            self.assertEqual(self.store.recovery_pending(key),[(dispatch,'delivery_uncertain')])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM recovery_events').fetchone()[0],0)
        self.assertEqual(self.client.stopped,[])

    async def test_owner_cannot_bypass_policy_change(self):
        await self.prepare_paused();key=message().key
        self.client.policy_value='changed'
        with self.assertRaisesRegex(dsh.BridgeError,'recovery_policy_changed'):
            await self.service.recover(key,owner=True)
        self.assertEqual(self.client.stopped,[])
        self.assertEqual(self.store.session(key)[2],1)

    async def test_owner_clears_remote_stale_queue_then_requires_idle_checkpoint(self):
        await self.prepare_paused()
        async def checkpoint(sid,**kwargs):
            if not self.client.stopped:raise dsh.BridgeError('recovery_turn_active')
            return 35
        self.client.recovery_checkpoint=checkpoint
        await self.service.recover(message().key,owner=True)
        self.assertEqual(self.client.stopped,[self.bound[0]])
        self.assertEqual(self.store.delivery(message().key,self.bound[0])[1],35)

    async def test_recovery_locks_out_reset_and_new_requests_and_freezes_boundary(self):
        await self.prepare_paused();key=message().key
        started=asyncio.Event();release=asyncio.Event()
        async def checkpoint(sid,**kwargs):started.set();await release.wait();return 36
        self.client.recovery_checkpoint=checkpoint
        recovering=asyncio.create_task(self.service.recover(key,owner=True))
        await started.wait()
        try:
            with self.assertRaisesRegex(dsh.BridgeError,'recovery_busy'):await self.service.recover(key,owner=True)
            with self.assertRaisesRegex(dsh.BridgeError,'recovery_in_progress'):await self.service.reset(key)
            later=message(mid='later');self.service.observe(later)
            self.assertFalse(self.service.schedule(later,self.send))
            release.set();await recovering
            delivered=self.store.delivery(key,self.bound[0])
            pending,_=self.store.pending_messages(key,10,delivered[0])
            self.assertEqual([m['message_id'] for m in pending],['later'])
        finally:
            release.set();await recovering

    async def test_state_change_during_check_does_not_skip_new_uncertain_dispatch(self):
        await self.prepare_paused();key=message().key
        original=self.store.begin(key);self.store.finish(original,'delivery_uncertain')
        async def checkpoint(sid,**kwargs):
            added=self.store.begin(key);self.store.finish(added,'delivery_uncertain');return 40
        self.client.recovery_checkpoint=checkpoint
        with self.assertRaisesRegex(dsh.BridgeError,'recovery_state_changed'):
            await self.service.recover(key,owner=True)
        self.assertEqual(len(self.store.recovery_pending(key)),2)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM recovery_events').fetchone()[0],0)
        self.assertEqual(self.store.session(key)[2],1)

    async def test_offline_owner_check_pauses_previously_active_binding(self):
        await self.submit(message())
        async def bad(sid,**kwargs):raise dsh.BridgeError('dsh_stream_disconnected')
        self.client.recovery_checkpoint=bad
        with self.assertRaises(dsh.BridgeError):await self.service.recover(message().key,owner=True)
        self.assertEqual(self.store.session(message().key)[2],1)

    async def test_owner_reauthenticates_once_after_cached_cookie_expires(self):
        await self.prepare_paused()
        calls=[]
        async def policy():
            calls.append(1)
            if len(calls)==1:raise dsh.BridgeError('dsh_auth_expired')
            return 'p'
        self.client.policy=policy
        self.assertEqual(await self.service.recover(message().key,owner=True),'resumed')
        self.assertEqual(len(calls),2)

    async def test_owner_cold_queue_cancel_missing_requires_fresh_idle_proof(self):
        await self.prepare_paused()
        cleared=[]
        async def checkpoint(sid,**kwargs):
            if not cleared:raise dsh.BridgeError('recovery_turn_active')
            return 45
        async def stop(sid):
            cleared.append(sid)
            raise dsh.MissingSession('dsh_session_missing')
        self.client.recovery_checkpoint=checkpoint;self.client.stop=stop
        self.assertEqual(await self.service.recover(message().key,owner=True),'resumed')
        self.assertEqual(self.store.delivery(message().key,self.bound[0])[1],45)

    async def test_owner_failed_cancel_with_still_active_remote_keeps_uncertainty(self):
        await self.prepare_paused();key=message().key
        dispatch=self.store.begin(key);self.store.finish(dispatch,'delivery_uncertain')
        async def checkpoint(sid,**kwargs):raise dsh.BridgeError('recovery_turn_active')
        async def stop(sid):raise dsh.BridgeError('dsh_transport_or_protocol_error')
        self.client.recovery_checkpoint=checkpoint;self.client.stop=stop
        with self.assertRaisesRegex(dsh.BridgeError,'recovery_turn_active'):
            await self.service.recover(key,owner=True)
        self.assertEqual(self.store.session(key)[2],1)
        self.assertEqual(self.store.recovery_pending(key),[(dispatch,'delivery_uncertain')])
