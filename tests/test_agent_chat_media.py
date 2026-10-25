import base64
import importlib
import io
from pathlib import Path
import tempfile
import time
import unittest

import httpx
from PIL import Image
from test_agent_chat import PACKAGE, cfg, domain

media = importlib.import_module(PACKAGE + '.media')


def png(size=(20, 20)):
    output = io.BytesIO()
    Image.new('RGB', size, 'red').save(output, format='PNG')
    return output.getvalue()


class ImageTests(unittest.IsolatedAsyncioTestCase):
    def test_napcat_nt_image_host_is_exactly_allowlisted(self):
        self.assertEqual(media.allowed_url('https://multimedia.nt.qq.com.cn/download?appid=1407'),
                         'multimedia.nt.qq.com.cn')
        for host in ['multimedia.nt.qq.com.cn.evil.test', 'evil.multimedia.nt.qq.com.cn',
                     'multimedia.nt.qq.com.evil.cn']:
            with self.subTest(host=host), self.assertRaises(media.MediaError):
                media.allowed_url('https://' + host + '/download')

    async def test_download_pins_public_dns_and_never_forwards_dsh_credentials(self):
        requests = []
        async def handler(request):
            requests.append(request)
            self.assertEqual(request.url.host, '8.8.8.8')
            self.assertEqual(request.headers['host'], 'gchat.qpic.cn')
            self.assertEqual(request.extensions['sni_hostname'], 'gchat.qpic.cn')
            self.assertNotIn('cookie', request.headers)
            self.assertNotIn('authorization', request.headers)
            return httpx.Response(200, content=png())
        async def resolve(host): return ['8.8.8.8']
        client = media.MediaResolver(cfg(), httpx.AsyncClient(transport=httpx.MockTransport(handler)), resolve)
        try:
            self.assertEqual(await client.download('https://gchat.qpic.cn/a?rkey=private'), png())
            self.assertEqual(len(requests), 1)
        finally:
            await client.close()

    async def test_redirect_private_dns_and_invalid_hosts_are_blocked(self):
        requests = []
        async def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={'location': 'http://127.0.0.1/secrets'})
        async def resolve(host): return ['8.8.8.8']
        client = media.MediaResolver(cfg(), httpx.AsyncClient(transport=httpx.MockTransport(handler)), resolve)
        try:
            with self.assertRaises(media.MediaError): await client.download('https://gchat.qpic.cn/a')
            self.assertEqual(len(requests), 1)
            async def private(host): return ['127.0.0.1']
            client.resolve = private
            with self.assertRaises(media.MediaError): await client.download('https://gchat.qpic.cn/a')
            for url in ['https://gchat.qpic.cn.evil/a', 'file:///secret', 'https://127.0.0.1/',
                        'https://user@qpic.cn/x', 'https://gchat.qpic.cn:8080/x']:
                with self.subTest(url=url), self.assertRaises(media.MediaError): await client.download(url)
            self.assertEqual(len(requests), 1)
        finally:
            await client.close()

    async def test_local_paths_and_oversized_downloads_are_denied(self):
        async def handler(request): return httpx.Response(200, content=b'x' * 100001)
        async def resolve(host): return ['8.8.8.8']
        client = media.MediaResolver(cfg(agent_chat_image_max_bytes=100000),
            httpx.AsyncClient(transport=httpx.MockTransport(handler)), resolve)
        calls = []
        async def api(*a, **kw): calls.append((a, kw)); return {}
        try:
            with self.assertRaises(media.MediaError): await client.download('https://gchat.qpic.cn/a')
            for value in ['../../secret', 'C:\\secret', 'file:///secret', 'http://localhost/x', 'base64://abcd']:
                with self.subTest(value=value), self.assertRaises(media.MediaError):
                    await client.fetch({'file': value}, api)
            self.assertEqual(calls, [])
            with tempfile.TemporaryDirectory() as folder:
                file = Path(folder) / 'outside.png'; file.write_bytes(png())
                with self.assertRaises(media.MediaError): client.local_bytes(str(file))
        finally:
            await client.close()

    async def test_gateway_image_reaches_native_attachment_and_private_refs_stay_out_of_prompt(self):
        resolver = media.MediaResolver(cfg())
        calls = []
        async def api(action, **params):
            calls.append((action, params))
            return {'base64': base64.b64encode(png()).decode()}
        messages = [{'message_id': '42', 'text': '[image]', 'timestamp': time.time(),
                     'media': [{'file': 'abcdef.png'}]}]
        try:
            images, notes = await resolver.prepare(messages, api)
            self.assertEqual(calls, [('get_image', {'file': 'abcdef.png'})])
            self.assertEqual(len(images), 1)
            self.assertEqual(images[0]['mediaType'], 'image/jpeg')
            Image.open(io.BytesIO(base64.b64decode(images[0]['data']))).verify()
            self.assertIn('42', notes)
            self.assertNotIn('abcdef.png', domain.prompt_text(messages, 'nonce'))
            self.assertNotIn('abcdef.png', notes)
        finally:
            await resolver.close()

    def test_invalid_formats_and_pixel_bombs_rejected(self):
        for blob in [b'<svg><script>bad</script></svg>', b'not an image']:
            with self.assertRaises(media.MediaError): media.normalize_image(blob, cfg())
        with self.assertRaises(media.MediaError):
            media.normalize_image(png((400, 400)), cfg(agent_chat_image_max_pixels=100000))


class FailedImages(unittest.IsolatedAsyncioTestCase):
    async def test_failure_returns_honest_note_without_private_paths_or_tokens(self):
        resolver = media.MediaResolver(cfg())
        async def fail(*a, **kw): raise RuntimeError('SECRET_TOKEN and C:/private/file')
        try:
            images, notes = await resolver.prepare([{'message_id':'1','timestamp':time.time(),
                'media':[{'file':'abcdef.png'}]}], fail)
            self.assertEqual(images, [])
            self.assertIn('不可猜测', notes)
            self.assertNotIn('SECRET', notes)
            self.assertNotIn('private', notes)
        finally:
            await resolver.close()
