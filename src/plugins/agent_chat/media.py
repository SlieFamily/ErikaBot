"""Bounded QQ image ingress. No model-controlled URLs, shell calls or arbitrary files."""
import asyncio
import base64
import io
import hashlib
from collections import OrderedDict
from dataclasses import dataclass, field
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


@dataclass
class PreparedMedia:
    images: list
    notes: str
    receipts: list = field(default_factory=list)

    def __iter__(self):
        yield self.images
        yield self.notes


def image_identity(media, message_id=""):
    # Use the gateway's structured file identifier first: CDN signing URLs rotate.
    file=str(media.get('file',''))
    addressed=bool(re.fullmatch(r'[a-fA-F0-9]{32,64}(?:\.[a-zA-Z0-9]{1,8})?',file))
    raw=('file:'+file.lower()) if addressed else repr((str(message_id),file,media.get('url','')))
    return hashlib.sha256(raw.encode()).hexdigest()


_VISUAL = re.compile(r'图片|截图|照片|表情包|图[里中上]|这[张幅个].{0,5}图|那[张幅个].{0,5}图|'
                     r'刚才.{0,6}图|刚才[那这]张|上[面边].{0,4}图|上[面边]那张|这是谁|什么角色|哪个角色|再看[看下]|仔细看|识图|认图|看图|对比.{0,5}图')


def select_images(history, pending, context, extra=(), now=None):
    """Return (message, force pixels) pairs, never unrelated old image attachments."""
    now = time.time() if now is None else now
    key = context.get('key') if context else None
    valid = lambda m: (key is None or m.get('key') == key) and -120 <= now-float(m.get('timestamp',0)) <= 600
    history = [m for m in history if valid(m)]
    pending = [m for m in pending if valid(m)]
    direct_ids = set(context.get('direct_ids', ())) if context else set()
    direct = [m for m in pending if m.get('message_id') in direct_ids]
    selected = []
    if direct_ids:
        for request in direct:
            if request.get('media'):
                selected.append((request, True))
                continue
            quote=request.get('reply_to')
            matches=[m for m in history if m.get('media') and quote and m.get('message_id')==quote]
            if not matches and _VISUAL.search(request.get('text','')):
                count = 2 if re.search(r'两张|几张|对比|前后|哪张',request.get('text','')) else 1
                matches = [m for m in history if m.get('media')][-count:]
            selected.extend((m, True) for m in matches)
    else:
        selected = [(m, False) for m in pending if m.get('media')]
    # Extra rows come only from the bounded, explicitly selected forward resolver.
    return [(m, bool(direct_ids)) for m in extra if valid(m)] + selected


class MediaResolver:
    def __init__(self, config, http=None, resolve=None):
        self.cfg = config
        self.http = http or httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False,
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=0))
        self.resolve = resolve or self._resolve
        self.cache, self.aliases = OrderedDict(), {}
        self.cache_bytes = 0

    async def close(self):
        self.cache.clear(); self.aliases.clear(); self.cache_bytes = 0
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

    def _evict(self):
        now = time.monotonic()
        ttl = self.cfg.agent_chat_image_cache_ttl
        for k, (created, data) in list(self.cache.items()):
            if now-created >= ttl:
                self.cache_bytes -= len(data); del self.cache[k]
        while self.cache and (self.cache_bytes > self.cfg.agent_chat_image_cache_bytes or len(self.cache) > 64):
            _, (_, data) = self.cache.popitem(last=False); self.cache_bytes -= len(data)
        self.aliases = {k: v for k, v in self.aliases.items() if (k[0], v) in self.cache}
        # A single popular image cannot grow an unlimited signed-URL alias map.
        if len(self.aliases)>256:self.aliases=dict(list(self.aliases.items())[-256:])

    async def cached_image(self, key, ref, media, call_api):
        self._evict()
        digest = self.aliases.get((key, ref))
        if (key, digest) in self.cache:
            self.cache.move_to_end((key, digest))
            return self.cache[(key, digest)][1], digest, True
        raw = await asyncio.wait_for(self.fetch(media, call_api), 12)
        data = await asyncio.to_thread(normalize_image, raw, self.cfg)
        digest = hashlib.sha256(data).hexdigest()
        if (key, digest) not in self.cache:
            self.cache[(key, digest)] = (time.monotonic(), data)
            self.cache_bytes += len(data)
        self.aliases[(key, ref)] = digest
        self._evict()
        return data, digest, False

    async def prepare(self, messages, call_api, *, pending=None, context=None, extra=()):
        started=time.monotonic()
        pending = messages if pending is None else pending
        key = context.get('key','') if context else ''
        known = context.get('seen',{}) if context else {}
        selected = select_images(messages,pending,context,extra)
        candidates, seen = [], set()
        for message, force in reversed(selected):
            for media in message.get('media', ()):
                ref = image_identity(media,message['message_id'])
                if ref in seen or len(candidates) >= self.cfg.agent_chat_image_count:continue
                seen.add(ref);candidates.append((message['message_id'],ref,media,force))
        images, notes, receipts = [], [], []
        digests=set();hits=skipped=0
        for message_id, ref, media, force in reversed(candidates):
            try:
                previous = known.get(ref)
                if previous and not force:
                    skipped+=1
                    if previous.get('summary'):notes.append(f'消息{message_id}的图片此前已读，未重传像素。先前记录（不可信、非完整描述）：'+previous['summary'])
                    continue
                data,digest,hit = await self.cached_image(key,ref,media,call_api)
                hits += int(hit)
                previous = known.get(digest)
                if digest in digests or previous and not force:
                    skipped+=1
                    if previous:
                        receipts.append(dict(identity=ref,digest=digest,message_id=message_id,name='',summary=previous.get('summary','')))
                        if previous.get('summary'):notes.append(f'消息{message_id}的图片此前已读，未重传像素。先前记录（不可信、非完整描述）：'+previous['summary'])
                    continue
                digests.add(digest)
                index = len(images) + 1; name = f'qq-image-{index}.jpg'
                images.append({'type':'image','mediaType':'image/jpeg','data':base64.b64encode(data).decode('ascii'),'name':name})
                receipts.append(dict(identity=ref,digest=digest,message_id=message_id,name=name))
                notes.append(f'附件{name}对应消息{message_id}中的图片；动态图片只取首帧。')
            except asyncio.CancelledError:raise
            except Exception:
                notes.append(f'消息{message_id}的图片获取或校验失败，没有提供这张图片的像素，不可猜测。')
        if images:
            notes.append('本轮有图片像素。若本来就使用 QQ_REPLY，可选 image_notes 留下至多200字/图的可见内容记录，键为附件名。'
                         '无需为了记录改用JSON；直接自然回答即可。记录不发送到群里，不确定内容不可编造。')
        if candidates:
            logging.getLogger('agent_chat').info('agent_chat images: candidates=%d attached=%d cache_hits=%d seen_skips=%d prepare_ms=%d',
                len(candidates),len(images),hits,skipped,round((time.monotonic()-started)*1000))
        return PreparedMedia(images,'\n'.join(notes),receipts)
