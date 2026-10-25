"""Bounded QQ image ingress. No model-controlled URLs, shell calls or arbitrary files."""
import asyncio
import base64
import io
import ipaddress
import logging
from pathlib import Path
import re
import socket
import time
from urllib.parse import urlsplit
import warnings

import httpx
from PIL import Image, ImageOps


class MediaError(Exception):
    pass


def safe_file_ref(value):
    return isinstance(value, str) and '..' not in value and bool(re.fullmatch(r'[A-Za-z0-9_.+=@-]{1,256}', value))


def allowed_url(raw):
    if not isinstance(raw, str) or len(raw) > 4096:
        raise MediaError('invalid_image_url')
    try:
        u = urlsplit(raw)
        host = (u.hostname or '').lower()
        if (u.scheme not in {'http', 'https'} or u.username or u.password or u.fragment or
                u.port not in {None, 80, 443} or any(ord(c) < 33 for c in raw)):
            raise ValueError()
        if not (host == 'qpic.cn' or host.endswith('.qpic.cn') or
                host in {'multimedia.nt.qq.com', 'multimedia.nt.qq.com.cn', 'gxh.vip.qq.com'}):
            raise ValueError()
    except ValueError:
        raise MediaError('image_host_not_allowed') from None
    return host


class _HideMediaQuery(logging.Filter):
    def filter(self, record):
        # CDN rkey/auth parameters must not appear in httpx's global INFO logger.
        value = record.getMessage()
        if '?' in value:
            record.msg = re.sub(r'(https?://[^\s?]+)\?[^\s]+', r'\1?[redacted]', value)
            record.args = ()
        return True


logging.getLogger('httpx').addFilter(_HideMediaQuery())


def normalize_image(data, config):
    if not data or len(data) > config.agent_chat_image_max_bytes:
        raise MediaError('image_size_limit')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {'PNG', 'JPEG', 'WEBP', 'GIF'}:
                    raise MediaError('unsupported_image_format')
                if source.width * source.height > config.agent_chat_image_max_pixels:
                    raise MediaError('image_pixel_limit')
                source.seek(0)  # Animated stickers: first frame only.
                image = ImageOps.exif_transpose(source).convert('RGBA')
                image.thumbnail((1536, 1536))
                canvas = Image.new('RGB', image.size, 'white')
                canvas.paste(image, mask=image.getchannel('A'))
                for quality in (85, 70, 55):
                    output = io.BytesIO()
                    canvas.save(output, format='JPEG', quality=quality)
                    if output.tell() <= 1_000_000:
                        return output.getvalue()
                    canvas.thumbnail((1024, 1024))
    except MediaError:
        raise
    except Exception:
        raise MediaError('invalid_image_bytes') from None
    raise MediaError('normalized_image_too_large')


class MediaResolver:
    def __init__(self, config, http=None, resolve=None):
        self.cfg = config
        self.http = http or httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=0))
        self.resolve = resolve or self._resolve

    async def close(self):
        await self.http.aclose()

    async def _resolve(self, host):
        answers = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return list(dict.fromkeys(item[4][0] for item in answers))

    async def download(self, raw):
        host = allowed_url(raw)
        addresses = await self.resolve(host)
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise MediaError('image_address_not_public')
        # Pin the validated address; a second DNS lookup cannot rebind to the local network.
        target = httpx.URL(raw).copy_with(scheme='https', host=addresses[0], port=None)
        async with self.http.stream('GET', target, headers={'Host': host, 'Accept-Encoding': 'identity'},
                                    extensions={'sni_hostname': host}) as response:
            if response.status_code != 200:
                raise MediaError('image_download_failed')
            if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                raise MediaError('compressed_http_image_not_allowed')
            declared = response.headers.get('content-length')
            if declared and (not declared.isdigit() or int(declared) > self.cfg.agent_chat_image_max_bytes):
                raise MediaError('image_size_limit')
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > self.cfg.agent_chat_image_max_bytes:
                    raise MediaError('image_size_limit')
            return bytes(data)

    def local_bytes(self, raw):
        if not isinstance(raw, str) or raw.startswith(('\\\\', '//')) or '\x00' in raw:
            raise MediaError('local_image_not_allowed')
        path = Path(raw).resolve(strict=True)
        roots = [root.resolve(strict=True) for root in self.cfg.agent_chat_image_cache_roots]
        if not any(path.is_relative_to(root) for root in roots) or not path.is_file():
            raise MediaError('local_image_not_allowed')
        with path.open('rb') as stream:
            data = stream.read(self.cfg.agent_chat_image_max_bytes + 1)
        if len(data) > self.cfg.agent_chat_image_max_bytes:
            raise MediaError('image_size_limit')
        return data

    async def fetch(self, media, call_api):
        # Only structured image segments from allowed QQ events supply these references.
        if media.get('url'):
            try:
                return await self.download(media['url'])
            except Exception:
                pass
        if not safe_file_ref(media.get('file')):
            raise MediaError('invalid_image_reference')
        info = await call_api('get_image', file=media['file'])
        if not isinstance(info, dict):
            raise MediaError('invalid_image_metadata')
        encoded = info.get('base64')
        if isinstance(encoded, str):
            if len(encoded) > (self.cfg.agent_chat_image_max_bytes + 2) // 3 * 4:
                raise MediaError('image_size_limit')
            try:
                return base64.b64decode(encoded, validate=True)
            except ValueError:
                raise MediaError('invalid_image_bytes') from None
        if isinstance(info.get('url'), str) and info['url'].startswith(('http://', 'https://')):
            return await self.download(info['url'])
        if self.cfg.agent_chat_image_cache_roots and info.get('file'):
            return await asyncio.to_thread(self.local_bytes, info['file'])
        raise MediaError('image_unavailable')

    async def prepare(self, messages, call_api):
        candidates, seen = [], set()
        now = time.time()
        for message in reversed(messages):
            if now - float(message.get('timestamp', 0)) > 600:
                continue
            for media in message.get('media', ()):
                ref = (media.get('file', ''), media.get('url', ''))
                if ref in seen or len(candidates) >= self.cfg.agent_chat_image_count:
                    continue
                seen.add(ref)
                candidates.append((message['message_id'], media))
        images, notes = [], []
        for message_id, media in reversed(candidates):
            try:
                raw = await asyncio.wait_for(self.fetch(media, call_api), 12)
                data = await asyncio.to_thread(normalize_image, raw, self.cfg)
                index = len(images) + 1
                images.append({'type': 'image', 'mediaType': 'image/jpeg',
                    'data': base64.b64encode(data).decode('ascii'), 'name': f'qq-image-{index}.jpg'})
                notes.append(f'附件{index}对应消息{message_id}中的图片；动态图片只取首帧。')
            except asyncio.CancelledError:
                raise
            except Exception:
                # No signed URLs, local paths, or remote error strings in model context/logs.
                notes.append(f'消息{message_id}的图片获取或校验失败，没有提供这张图片的像素，不可猜测。')
        return images, '\n'.join(notes)
