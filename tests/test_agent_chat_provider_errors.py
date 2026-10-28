import json,unittest
import test_agent_chat as core

class ProviderErrorTests(unittest.TestCase):
    def fail(self,error):
        collector=core.dsh.TurnCollector('mine')
        collector.push({'type':'turn/start','data':{'turn':1}})
        collector.push({'type':'user/message','data':{'source':{'kind':'user','rpcId':'mine'}}})
        collector.push({'type':'assistant/message','data':{'turn':1,'message':{'content':[{'type':'text','text':'not final'}]}}})
        collector.push({'type':'turn/end','data':{'turn':1,'reason':{'kind':'error','error':error}}})
    def test_actual_provider_envelope_is_classified_without_leaking_body(self):
        for body in ({'code':'CONTENT_FILTERED','message':'PRIVATE_BODY'},
                     {'error':{'type':'content_policy_violation','message':'PRIVATE_BODY'}}):
            with self.assertRaisesRegex(core.dsh.BridgeError,'^model_content_filtered$'):
                self.fail({'code':'INVALID_REQUEST','message':'400: '+json.dumps(body)})
    def test_plain_message_text_does_not_masquerade_as_filter_result(self):
        for message in ('CONTENT_FILTERED','400: broken JSON','400: {"message":"CONTENT_FILTERED"}'):
            with self.assertRaisesRegex(core.dsh.BridgeError,'^model_invalid_request$'):
                self.fail({'code':'INVALID_REQUEST','message':message})
        with self.assertRaisesRegex(core.dsh.BridgeError,'^turn_not_completed$'):
            self.fail({'code':'TIMEOUT','message':'CONTENT_FILTERED'})

class ProviderFailureServiceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=core.ServiceTests.asyncSetUp
    asyncTearDown=core.ServiceTests.asyncTearDown
    submit=core.ServiceTests.submit
    send=core.ServiceTests.send
    async def test_filter_is_not_retried_or_automatically_resumed(self):
        self.client.error=core.dsh.BridgeError('model_content_filtered')
        await self.submit(core.message())
        self.assertEqual(len(self.client.prompts),1)
        self.assertEqual(self.store.session(core.message().key)[2],1)
        self.assertTrue(any('内容检查未通过' in message for message in self.sent))
        self.assertFalse(any('连接或处理' in message for message in self.sent))
