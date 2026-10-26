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
    async def test_empty_or_filtered_final_text_gives_direct_notice_without_retry(self):
        for i, answer in enumerate(['', '<thinking>PRIVATE_CANARY', 'PRIVATE_CANARY</thinking>']):
            self.client.answer = answer
            await self.submit(message(mid=str(i)))
        self.assertEqual(len(self.client.prompts), 3)
        self.assertEqual(self.sent, ['这次没能生成可用的回复，你再问我一次。'] * 3)
        self.assertEqual(self.store.session(message().key)[2], 0)

    async def test_empty_random_reply_stays_silent(self):
        from dataclasses import replace
        from unittest.mock import patch
        self.client.answer = ''
        self.service.cfg.agent_chat_ambient_probability = .1
        with patch.object(self.service, 'quiet', return_value=False), patch('random.random', return_value=0):
            await self.submit(replace(message(), directed=False))
        self.assertEqual(self.sent, [])

    async def test_embedded_reasoning_removed_at_actual_send_boundary(self):
        self.client.answer = 'private</thinking>可见回复'
        await self.submit(message())
        self.assertEqual(self.sent, ['可见回复'])

    async def test_image_unsupported_falls_back_once_without_suspending_text_chat(self):
        requests = []
        async def reply(sid, text, images=None, **kwargs):
            requests.append(images)
            if images:
                raise core.dsh.ImageUnsupported('model_does_not_support_images')
            self.assertIn('不支持图片', text)
            self.assertIn('如果最新问题只涉及文字，正常回答文字问题', text)
            return '这张图我现在看不了'
        async def prepare(history,pending,context=None): return [{'type':'image'}], 'image note'
        self.client.reply = reply
        msg = message()
        self.service.observe(msg)
        self.service.schedule(msg, self.send, prepare)
        import asyncio
        await asyncio.gather(*list(self.service.tasks.values()))
        self.assertEqual(len(requests), 2)
        self.assertEqual(self.store.session(msg.key)[2], 0)
        self.assertEqual(self.sent, ['这张图我现在看不了'])
