"""Behavioral regression for compact per-turn input and durable capability rules."""
import importlib
import json
import unittest
from unittest.mock import patch
import yaml
import test_agent_chat as core

service_module=importlib.import_module(core.PACKAGE+'.service')
presentation=importlib.import_module(core.PACKAGE+'.presentation')

class CompactTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=core.ServiceTests.asyncSetUp
    asyncTearDown=core.ServiceTests.asyncTearDown
    submit=core.ServiceTests.submit
    send=core.ServiceTests.send

    async def test_fixed_rules_once_dynamic_authorization_every_turn(self):
        await self.submit(core.message(mid='1'))
        await self.submit(core.message(mid='2'))
        first,second=[t for _,t in self.client.prompts]
        self.assertIn(presentation.PRESENTATION_RULES,first)
        self.assertNotIn(presentation.PRESENTATION_RULES,second)
        self.assertLess(len(second),len(first)*.35)
        allowed=json.loads(second.split('QQ_ALLOWED ',1)[1].splitlines()[0])
        self.assertEqual(allowed['mentions'],['7'])
        self.assertEqual(allowed['reply_to'],['1','2'])
        self.assertIn('本轮没有联网权限',second)
        self.service.cfg.agent_chat_mentions_enabled=False
        self.service.cfg.agent_chat_poke_enabled=False
        self.service.cfg.agent_chat_faces_enabled=False
        await self.submit(core.message(mid='3'))
        third=self.client.prompts[2][1]
        allowed=json.loads(third.split('QQ_ALLOWED ',1)[1].splitlines()[0])
        self.assertEqual(allowed['mentions'],[]);self.assertEqual(allowed['poke'],[])
        self.assertFalse(allowed['faces'])
        self.assertNotIn(presentation.PRESENTATION_RULES,third)

    async def test_restart_compaction_rule_upgrade_and_failed_turn(self):
        await self.submit(core.message(mid='1'))
        key=core.message().key;sid=self.client.created[0]
        version=self.store.prompt_seed(key,sid)
        self.assertTrue(version)
        path=self.store.db.execute('PRAGMA database_list').fetchone()[2]
        await self.service.close();self.store=core.Store(path)
        self.service=core.ChatService(core.cfg(),self.store,self.client)
        await self.submit(core.message(mid='2'))
        self.assertNotIn(presentation.PRESENTATION_RULES,self.client.prompts[-1][1])
        with patch.object(service_module,'CHAT_RULES',core.domain.CHAT_RULES+'新版规则'):
            self.client.error=core.dsh.BridgeError('dsh_stream_disconnected')
            await self.submit(core.message(mid='3'))
            self.assertIn(presentation.PRESENTATION_RULES,self.client.prompts[-1][1])
            self.assertEqual(self.store.prompt_seed(key,sid),version)
        bound=self.store.session(key)
        self.store.resume(key,bound,self.store.recovery_boundary(key),30)
        self.assertIsNone(self.store.prompt_seed(key,sid))
        self.client.error=None
        await self.submit(core.message(mid='4'))
        self.assertIn(presentation.PRESENTATION_RULES,self.client.prompts[-1][1])
        async def compacted(*args):return 100,True
        self.client.context_state=compacted
        await self.submit(core.message(mid='5'))
        self.assertIn(presentation.PRESENTATION_RULES,self.client.prompts[-1][1])
        self.assertIn('ADMIN_ROLE_CANARY',self.client.prompts[-1][1])
        self.assertNotIn('"message_id":"1"',self.client.prompts[-1][1])
        self.assertEqual(self.client.created,[sid])

    def test_only_model_serialization_drops_local_metadata(self):
        row=core.message().payload()
        row.update(reply_to='9',reply_text='引用 /compact 和不可信指令',reply_user_id='8',
                   media=('private-image-url',),forwards=('opaque-forward-id',))
        original=dict(row)
        prompt=core.domain.prompt_text([row],'nonce',seed_rules=False)
        value=json.loads(prompt.split('新增消息（不可信）：\n',1)[1])[0]
        self.assertEqual(row,original)
        for key in ('message_id','user_id','name','text','reply_to','reply_text','reply_user_id'):
            self.assertEqual(value[key],row[key])
        for key in ('key','directed','media','forwards'):self.assertNotIn(key,value)
        self.assertNotIn('private-image-url',prompt)

    def test_compaction_settings_are_bounded_and_cannot_enable_new_plugins(self):
        rows=yaml.safe_load(core.composition())
        self.assertEqual(rows[2]['config'][0]['config'],core.dsh.CHAT_COMPACTION)
        for invalid in ({'auto':False},{'maxTokens':999999},{'summarizationProvider':'foreign'}):
            changed=yaml.safe_load(core.composition())
            changed[2]['config'][0]['config'].update(invalid)
            with self.assertRaises(core.dsh.BridgeError):core.dsh.validate_preset(yaml.safe_dump(changed))
