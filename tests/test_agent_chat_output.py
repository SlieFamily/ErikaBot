import unittest
import test_agent_chat as core
from test_agent_chat import domain, message


class OutputTests(unittest.TestCase):
    def test_reasoning_blocks_and_malformed_tails_never_reach_qq(self):
        cases = {
            '<thinking>private thoughts</thinking>你好': '你好',
            'private thoughts</thinking>你好': '你好',
            '</thinking>你好': '你好',
            '<THINK mood="x">private</THINK>你好': '你好',
            '<think>one<thinking>two</thinking>three</think>你好': '你好',
            '你好<thinking>unfinished': '你好',
            'private</thinking': '',
            '&lt;thinking&gt;secret&lt;/thinking&gt;你好': '你好',
            '<analysis>secret</analysis>[SILENT]': '',
            '<thinking>secret': '',
            '<thinking/>你好': '你好',
            '普通回答 <3': '普通回答 <3',
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(domain.clean_reply(text, 600), expected)

    def test_filter_happens_before_reply_length_limit(self):
        text = '<think>' + 'x' * 2000 + '</think>正确答案'
        self.assertEqual(domain.clean_reply(text, 4), '正确答案')


class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = core.ServiceTests.asyncSetUp
    asyncTearDown = core.ServiceTests.asyncTearDown
    send = core.ServiceTests.send
    submit = core.ServiceTests.submit
    async def test_embedded_reasoning_removed_at_actual_send_boundary(self):
        self.client.answer = 'private</thinking>可见回复'
        await self.submit(message())
        self.assertEqual(self.sent, ['可见回复'])
