"""Search contract, public-only transport, quotas, continuation and crash recovery."""
import asyncio
import importlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

import httpx

from test_agent_chat import PACKAGE, cfg, domain, dsh, message, Store, ChatService, FakeClient

web = importlib.import_module(PACKAGE + '.search')
RSS = b'<rss><channel><item><title>Example</title><link>https://example.com/article</link><description>Evidence</description></item></channel></rss>'
RESULT = {'status': 'ok', 'results': [{'id': 1, 'title': 'Example', 'url': 'https://example.com/article', 'snippet': 'Evidence'}]}


def action(nonce, query='命运石之门 官方网站'):
    return json.dumps({web.ACTION: {'nonce': nonce, 'query': query}}, ensure_ascii=False)


class ProtocolTests(unittest.TestCase):
    def test_exact_fresh_action_only(self):
        self.assertEqual(web.decision('<thinking>hidden</thinking>' + action('n'), 'n'), '命运石之门 官方网站')
        self.assertIsNone(web.decision('我今天不想打瓦', 'n'))
        for text in [action('old'), '先搜\n' + action('n'), '```json\n' + action('n') + '\n```',
                     '{"agent_chat_search": []}', '{"agent_chat_search":',
                     action('n').replace('"query":', '"url":'), action('n')[:-1] + ',"exec":"x"}']:
            with self.subTest(text=text), self.assertRaises(web.SearchError):
                web.decision(text, 'n')
        self.assertEqual(web.decision(action('n').replace('agent_chat_search', '\\u0061gent_chat_search'), 'n'),
                         '命运石之门 官方网站')
        with self.assertRaises(web.SearchError):
            web.decision(action('n').replace('"query":', '"nonce":"n","query":'), 'n')

    def test_private_queries_never_leave_host(self):
        for q in ['QQ 818353963', '１３８１２３４５６７８', 'person@example.com', 'api_key abc',
                  'E:\\secrets', 'https://127.0.0.1/admin', 'cookie abc', 'abc\nsecret', 'x' * 121]:
            with self.subTest(q=q), self.assertRaises(web.SearchError): web.safe_query(q)
        with self.assertRaises(web.SearchError): web.safe_query('where is SECRET_VALUE', ['SECRET_VALUE'])
        self.assertEqual(web.safe_query('2026 CS2 更新 site:counter-strike.net'), '2026 CS2 更新 site:counter-strike.net')

    def test_rss_bounded_deduplicated_and_no_xml_entities(self):
        self.assertEqual(len(web.parse_rss(RSS)), 1)
        for raw in [b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///x">]><rss/>', b'<html>captcha</html>',
                    b'<rss>broken', b'x' * (web.MAX_BODY + 1), b'<rss>\x00</rss>']:
            with self.subTest(raw=raw[:30]), self.assertRaises(web.SearchError): web.parse_rss(raw)
        items = ''.join(f'<item><title>{i}</title><link>https://example.com/{i}</link>'
                        f'<description>{"a" * 900}</description></item>' for i in range(20))
        result = web.parse_rss(('<rss><channel>' + items + '</channel></rss>').encode())
        self.assertEqual(len(result), 3)
        self.assertEqual(len(result[0]['snippet']), 600)
        for url in ['file:///etc/passwd', 'http://127.0.0.1/x', 'https://user:secret@public.com', 'http://private.local/x']:
            self.assertFalse(web.public_result_url(url))

    def test_sources_only_from_results_and_no_control_leaks(self):
        value = web.final_answer('信息[来源1]。伪造[来源9] https://evil.com/path', RESULT, 600)
        self.assertIn('https://example.com/article', value)
        self.assertNotIn('evil.com', value)
        self.assertNotIn('来源9', value)
        self.assertEqual(web.final_answer(action('n'), RESULT, 600), '')
        self.assertEqual(web.final_answer('[SILENT]', RESULT, 600), '')
        self.assertEqual(web.final_answer(action('n').replace('agent_chat_search', '\\u0061gent_chat_search'), RESULT, 600), '')
        self.assertLessEqual(len(web.final_answer('信息[来源1]' * 300, RESULT, 80)), 80)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_pinned_transport_no_credentials_no_redirects_group_scoped_cache(self):
        requests = []
        async def respond(req):
            requests.append(req)
            self.assertEqual(req.url.host, '8.8.8.8')
            self.assertEqual(req.headers['Host'], 'cn.bing.com')
            self.assertEqual(req.extensions['sni_hostname'], 'cn.bing.com')
            self.assertNotIn('authorization', req.headers)
            self.assertNotIn('cookie', req.headers)
            self.assertNotIn('DSH', str(req.url))
            return httpx.Response(200, content=RSS)
        async def resolve(host): return ['8.8.8.8']
        backend = web.BingSearch(cfg(), httpx.AsyncClient(transport=httpx.MockTransport(respond)), resolve)
        try:
            await backend.search('bot:group:1', '公开主题')
            self.assertTrue((await backend.search('bot:group:1', '公开主题'))['cached'])
            await backend.search('bot:group:2', '公开主题')
            self.assertEqual(len(requests), 2)
        finally: await backend.close()

    async def test_private_dns_mixed_dns_redirect_and_large_response_rejected(self):
        for addresses, response in [(['127.0.0.1'], httpx.Response(200, content=RSS)),
                (['8.8.8.8', '10.1.1.1'], httpx.Response(200, content=RSS)),
                (['8.8.8.8'], httpx.Response(302, headers={'location': 'http://localhost/'})),
                (['8.8.8.8'], httpx.Response(200, headers={'content-length': '9999999'})),
                (['8.8.8.8'], httpx.Response(200, content=b'x' * (web.MAX_BODY + 1)))]:
            async def resolve(host): return addresses
            backend = web.BingSearch(cfg(), httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)), resolve)
            try:
                with self.assertRaises(web.SearchError): await backend.search('group', 'public topic')
            finally: await backend.close()

    async def test_timeout_includes_dns_and_queue(self):
        async def resolve(host): await asyncio.sleep(10)
        backend = web.BingSearch(cfg().copy(update={'agent_chat_search_timeout': .02}), resolve=resolve)
        try:
            with self.assertRaisesRegex(web.SearchError, 'search_timeout'): await backend.search('g', 'public')
        finally: await backend.close()


class SearchClient(FakeClient):
    async def reply(self, sid, text):
        self.prompts.append((sid, text))
        if 'QQ_SEARCH_RESULT' in text:
            if self.error: raise self.error
            return self.answer
        nonce = re.search(r'"nonce": "([a-f0-9]+)"', text)
        return action(nonce[1]) if nonce else '直接回答'


class FakeSearch:
    def __init__(self): self.calls = []; self.error = None; self.callback = None
    async def search(self, key, query):
        self.calls.append((key, query))
        if self.callback: self.callback()
        if self.error: raise self.error
        return RESULT
    async def close(self): pass


class ServiceSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'test.sqlite3'
        self.store = Store(self.path)
        self.client = SearchClient(); self.client.answer = '查到了[来源1]'
        self.backend = FakeSearch(); self.sent = []
        self.service = ChatService(cfg(agent_chat_search_enabled=True), self.store, self.client, self.backend)
    async def asyncTearDown(self):
        await self.service.close(); self.tmp.cleanup()
    async def submit(self, msg=None):
        msg = msg or message()
        async def send(text): self.sent.append(text)
        self.service.observe(msg); self.service.schedule(msg, send)
        await asyncio.gather(*list(self.service.tasks.values()))

    async def test_search_uses_same_session_two_calls_and_no_role_or_chat_replay(self):
        await self.submit()
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(len(self.client.prompts), 2)
        self.assertEqual(self.client.prompts[0][0], self.client.prompts[1][0])
        self.assertNotIn('ADMIN_ROLE_CANARY', self.client.prompts[1][1])
        self.assertNotIn('"message_id"', self.client.prompts[1][1])
        self.assertEqual(self.store.calls(message().key, 0)[0], 2)
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn(web.ACTION, self.sent[0])
        self.assertIn('https://example.com/article', self.sent[0])
        self.assertEqual(self.store.db.execute('SELECT stage FROM searches').fetchone()[0], 'sent')

    async def test_ordinary_conversation_one_call_no_search(self):
        self.service.client = FakeClient()
        await self.submit()
        self.assertEqual(len(self.backend.calls), 0)
        self.assertEqual(len(self.service.client.prompts), 1)

    async def test_random_search_disabled_by_default_and_opt_in(self):
        self.service.cfg.agent_chat_ambient_probability = .1
        with patch.object(self.service, 'quiet', return_value=False), patch('random.random', return_value=0):
            await self.submit(replace(message(), directed=False))
            self.assertEqual(len(self.backend.calls), 0)
            self.service.cfg.agent_chat_search_ambient = True
            await self.submit(replace(message(mid='2'), directed=False))
        self.assertEqual(len(self.backend.calls), 1)

    async def test_bad_action_gives_notice_without_control_leak_or_suspension(self):
        self.service.client = FakeClient()
        self.service.client.answer = action('stale', '818353963')
        await self.submit()
        self.assertEqual(len(self.sent), 1)
        self.assertNotIn('agent_chat_search', self.sent[0])
        self.assertNotIn('818353963', self.sent[0])
        self.assertEqual(self.backend.calls, [])
        self.assertEqual(self.store.session(message().key)[2], 0)

    async def test_cancel_during_search_suspends_and_never_sends(self):
        entered = asyncio.Event()
        async def block(key, query):
            entered.set()
            await asyncio.Event().wait()
        self.backend.search = block
        msg = message()
        async def send(text): self.sent.append(text)
        self.service.observe(msg); self.service.schedule(msg, send)
        await asyncio.wait_for(entered.wait(), 5)
        task = self.service.tasks[msg.key]
        task.cancel(); await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.session(msg.key)[2], 1)
        self.assertEqual(self.store.db.execute('SELECT stage FROM searches').fetchone()[0], 'cancelled')

    async def test_no_search_if_only_one_model_call_remains(self):
        self.service.cfg = cfg(agent_chat_search_enabled=True, agent_chat_max_calls_per_hour=1)
        await self.submit()
        self.assertEqual(len(self.backend.calls), 0)
        self.assertEqual(self.sent, ['直接回答'])

    async def test_search_quota_persists_across_reset(self):
        self.service.cfg = cfg(agent_chat_search_enabled=True, agent_chat_search_max_per_hour=1)
        await self.submit()
        await self.service.reset(message().key)
        await self.submit(message(mid='2'))
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(self.sent[-1], '直接回答')

    async def test_network_failure_is_digested_without_suspending_session(self):
        self.backend.error = web.SearchError('search_timeout')
        self.client.answer = '暂时没查到，先不瞎讲。'
        await self.submit()
        self.assertIn('"status": "unavailable"', self.client.prompts[-1][1])
        self.assertEqual(self.store.session(message().key)[2], 0)
        self.assertEqual(len(self.sent), 1)

    async def test_second_model_failure_suspends_without_qq_send(self):
        self.client.error = dsh.BridgeError('test_timeout')
        await self.submit()
        self.assertEqual(self.store.session(message().key)[2], 1)
        self.assertEqual(self.sent, [])

    async def test_no_recursive_search_or_control_send(self):
        self.client.answer = action('wrong')
        await self.submit()
        self.assertEqual(len(self.backend.calls), 1)
        self.assertEqual(len(self.client.prompts), 2)
        self.assertEqual(self.sent, ['这次查询没能整理出可用答案，你换个关键词再试试。'])

    async def test_completed_search_without_final_text_gives_notice_not_reasoning(self):
        self.client.answer = ''
        await self.submit()
        self.assertEqual(self.sent, ['这次查询没能整理出可用答案，你换个关键词再试试。'])
        self.assertEqual(len(self.client.prompts), 2)
        self.assertEqual(self.store.session(message().key)[2], 0)
        self.assertEqual(self.store.db.execute('SELECT stage FROM searches').fetchone()[0], 'sent')

    async def test_late_arrival_during_search_not_marked_delivered(self):
        self.backend.callback = lambda: self.store.append(message(mid='late'))
        await self.submit()
        sid = self.store.session(message().key)[0]
        after = self.store.delivery(message().key, sid)[0]
        pending, _ = self.store.pending_messages(message().key, 20, after)
        self.assertEqual([m['message_id'] for m in pending], ['late'])

    async def test_deliberate_silence_after_search(self):
        self.client.answer = '[SILENT]'
        await self.submit()
        self.assertFalse(self.sent)
        self.assertEqual(self.store.session(message().key)[2], 0)

    async def test_crash_in_search_chain_not_replayed(self):
        self.store.bind('g', 'sid', 'policy')
        first = self.store.begin('g'); self.store.begin_search('g', first, 6)
        self.store.begin('g'); self.store.search_stage(first, 'answering')
        self.store.close(); self.store = Store(self.path); self.service.store = self.store
        self.assertEqual(self.store.session('g')[2], 1)
        self.assertEqual(self.store.db.execute('SELECT stage FROM searches').fetchone()[0], 'interrupted')
        self.assertEqual(self.store.calls('g', 0)[0], 2)


if __name__ == '__main__': unittest.main()
