"""DSH slash-RPC / remote.mux adapter. No shell, filesystem or approval forwarding.

Protocol reference: Derpyu520/qq-bridge (MIT); see third_party/qq-bridge-LICENSE.
Unknown wire shapes fail closed. A lost prompt response is never blindly retried.
"""
import asyncio
import contextlib
import hashlib
import json
import logging
import re
import time
import uuid

import httpx
import websockets
from websockets.legacy.client import Connect
import yaml

from .config import GUARD_MODULE, PRESET_ID, LEARNER_PRESET_ID
from .knowledge import TOOLS
from .search import CONTROL_PREFIX, public_result_url


CHAT_COMPACTION = {"thresholdRatio": 0.25, "headroomTokens": 8192, "retainTokens": 8192,
                   "maxTokens": 4096, "compactionRetries": 0}


class BridgeError(Exception):
    """Only fixed diagnostic codes; never carry remote messages or credentials."""


class MissingSession(BridgeError):
    pass


class ImageUnsupported(BridgeError):
    """DSH explicitly refused images before accepting or executing a prompt."""
    pass


class _RedactAuthURL(logging.Filter):
    def filter(self, record):
        # httpx's INFO access log otherwise includes the launch token in the URL.
        value = record.getMessage()
        if "token=" in value:
            record.msg = re.sub(r"([?&]token=)[^\s&\"']+", r"\1[REDACTED]", value)
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_RedactAuthURL())


class _NoRedirectConnect(Connect):
    def handle_redirect(self, uri):
        # websockets otherwise forwards extra_headers (including Cookie) on redirects.
        raise BridgeError("dsh_ws_redirect_rejected")


def validate_preset(content):
    """Validate the *actual* composition, never infer safety from a preset name."""
    if not isinstance(content, str) or len(content) > 32000:
        raise BridgeError("invalid_preset")
    try:
        rows = yaml.safe_load(content)
    except yaml.YAMLError:
        raise BridgeError("invalid_preset") from None
    if not isinstance(rows, list) or len(rows) != 4:
        raise BridgeError("unsafe_preset_composition")
    expected = [GUARD_MODULE, "@deepseek-ai/dsh-persona"]
    for row, name in zip(rows[:2], expected):
        if not isinstance(row, dict) or row.get("name") != name or set(row) - {"id", "name", "config"}:
            raise BridgeError("unsafe_preset_composition")
    if rows[0].get("config", {}) != {}:
        raise BridgeError("unsafe_preset_configuration")
    compression = rows[2]
    if (not isinstance(compression, dict) or
            set(compression) - {"id", "name", "group", "isolate", "config"} or
            compression.get("name") != "cordis:group" or compression.get("group") is not True or
            compression.get("isolate") != {"compaction": True}):
        raise BridgeError("unsafe_compaction_scope")
    children = compression.get("config")
    if (not isinstance(children, list) or len(children) not in (1, 2) or not isinstance(children[0], dict) or
            set(children[0]) - {"id", "name", "config"} or children[0].get("name") != "@deepseek-ai/dsh-compaction-basic" or
            children[0].get("config", {}) not in ({}, CHAT_COMPACTION)):
        raise BridgeError("unsafe_compaction_configuration")
    if len(children) == 2 and (children[0].get("config") != CHAT_COMPACTION or
            not isinstance(children[1], dict) or set(children[1]) - {"id", "name"} or
            children[1].get("name") != "@deepseek-ai/dsh-command-compact"):
        raise BridgeError("unsafe_compaction_configuration")
    persona = rows[1].get("config", {})
    if not isinstance(persona, dict) or set(persona) != {"prefix", "includeRuntimeContext", "complete"}:
        raise BridgeError("unsafe_persona_configuration")
    if (persona["includeRuntimeContext"] is not False or persona["complete"] is not True or
            not isinstance(persona["prefix"], str)):
        raise BridgeError("unsafe_persona_configuration")
    if "{{" in persona["prefix"]:
        raise BridgeError("persona_templates_not_allowed")
    web = rows[3]
    if (not isinstance(web, dict) or set(web) - {'id', 'name', 'config'} or
            web.get('name') != '@deepseek-ai/dsh-tool-web' or web.get('config') != {
                'search': True, 'fetch': False, 'searchMaxResults': 3,
                'searchMaxQueries': 1, 'searchTimeoutMs': 20000}):
        raise BridgeError('unsafe_search_configuration')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ReplyText(str):
    def __new__(cls, text, searches=0, sources=(), knowledge_calls=()):
        value = super().__new__(cls, text)
        value.searches, value.sources = searches, tuple(sources)
        value.knowledge_calls=tuple(knowledge_calls)
        return value


class TurnCollector:
    """Only return a turn containing OUR user message; never replay snapshot output."""
    def __init__(self, rpc_id, search_enabled=False, on_search=None, knowledge_tools=(), preset_id=PRESET_ID):
        self.rpc_id = rpc_id
        self.preset_id = preset_id
        self.knowledge_tools = set(knowledge_tools) & set(TOOLS)
        self.knowledge_calls, self.knowledge_results = {}, set()
        self.turn = None
        self.owned = False
        self.text = ""
        self.compactions = set()
        self.search_enabled, self.on_search = search_enabled, on_search
        self.search_calls, self.search_results, self.sources = set(), set(), []

    def push(self, event):
        kind, data = event.get("type"), event.get("data", {})
        if kind == "turn/start":
            self.turn = data.get("turn")
            self.owned, self.text = False, ""
            self.compactions.clear()
        elif kind == "compaction/start" and self.turn is not None and data.get("turn") == self.turn:
            cid = data.get("compactionId")
            if isinstance(cid, str) and cid:
                self.compactions.add(cid)
        elif kind == "compaction/end":
            self.compactions.discard(data.get("compactionId"))
        elif kind == "user/message":
            source = data.get("source", {})
            if source.get("kind") == "runtime-context":
                # DSH emits its own metadata/clearing snapshot in this event channel.
                # It is not another operator's prompt and never establishes ownership.
                return None
            if (source.get('kind') == 'model-selection' and source.get('form') == 'notice' and
                    set(source) <= {'kind', 'form', 'summary'} and
                    isinstance(source.get('summary'), str) and event.get('surfaceOp') == 'append'):
                # Harness emits this metadata when an administrator changes the model.
                # It is neither a foreign human prompt nor proof of our turn ownership.
                return None
            if (self.owned and source.get('kind')=='repeat-tool-reminder' and source.get('form')=='notice' and
                    set(source)=={'kind','form','summary'} and event.get('surfaceOp')=='append' and
                    isinstance(source.get('summary'),str)):
                reminder=re.fullmatch(r'([a-z_]+) × ([2-6])',source['summary'])
                if (reminder and reminder[1] in self.knowledge_calls.values() and
                        int(reminder[2])<=len(self.knowledge_calls)):
                    # Harness's bounded reminder after observed tool calls is metadata,
                    # never a second operator prompt or evidence of turn ownership.
                    return None
            op = event.get("surfaceOp", {})
            if (source.get("kind") == "compact-checkpoint" and
                    source.get("compactionId") in self.compactions and isinstance(op, dict) and
                    op.get("op") == "replace" and type(op.get("startSeq")) is int and
                    type(op.get("endSeq")) is int and op["startSeq"] >= 0 and op["endSeq"] >= 0):
                # DSH's correlated history replacement is not a second human input.
                # Endpoints follow surface order, not numeric order after compaction.
                # Never establish ownership or copy the summary into the QQ answer.
                return None
            if source.get("kind") == "user" and source.get("rpcId") == self.rpc_id:
                self.owned = True
            else:
                # Dedicated bridge sessions must not be manually chatted in concurrently.
                raise BridgeError("concurrent_session_input")
        elif kind == "tool/call":
            # Defence-in-depth detector, NOT the host-side execution guard.
            cid = data.get('callId')
            if data.get('name') in self.knowledge_tools:
                if (not self.owned or data.get('turn') != self.turn or not isinstance(cid,str) or not cid or
                        cid in self.knowledge_calls or cid in self.search_calls or len(self.knowledge_calls)>=6):
                    raise BridgeError('unexpected_knowledge_call')
                self.knowledge_calls[cid] = data['name']
                self.text = ''
                return None
            if (not self.search_enabled or not self.owned or data.get('turn') != self.turn or
                    data.get('name') != 'web_search' or not isinstance(cid, str) or not cid or
                    cid in self.search_calls or cid in self.knowledge_calls or len(self.search_calls) >= 2):
                raise BridgeError("unexpected_tool_call")
            if not self.search_calls and self.on_search:
                self.on_search()
            self.search_calls.add(cid)
            self.text = ''  # Never send the pre-tool "let me search" text as an answer.
        elif kind == 'tool/result' and data.get('turn') == self.turn:
            message = data.get('message', {})
            cid = message.get('toolCallId')
            source = message.get('source', {})
            if cid in self.knowledge_calls:
                if (cid in self.knowledge_results or message.get('role') != 'tool' or
                        source.get('kind') != 'tool' or source.get('callId') != cid):
                    raise BridgeError('unexpected_knowledge_result')
                self.knowledge_results.add(cid)
                return None
            if (cid not in self.search_calls or cid in self.search_results or
                    message.get('role') != 'tool' or source.get('kind') != 'tool' or source.get('callId') != cid):
                raise BridgeError('unexpected_tool_result')
            self.search_results.add(cid)
            if not message.get('isError'):
                meta = data.get('meta', {})
                for row in meta.get('sources', [])[:3] if isinstance(meta, dict) else []:
                    url = public_result_url(row.get('url')) if isinstance(row, dict) else ''
                    if url and url not in self.sources:
                        self.sources.append(url)
        elif kind == "agent-preset/selected" and data.get("agentPreset") != self.preset_id:
            raise BridgeError("session_preset_changed")
        elif kind == "assistant/message" and self.owned and data.get("turn") == self.turn:
            blocks = data.get("message", {}).get("content", [])
            self.text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            if len(self.text) > 16000:
                raise BridgeError("oversized_reply")
        elif kind == "turn/end" and self.owned and data.get("turn") == self.turn:
            reason = data.get("reason", {})
            reason = reason.get("kind") if isinstance(reason, dict) else reason
            if reason != "completed":
                raise BridgeError("turn_not_completed")
            if self.search_calls != self.search_results or set(self.knowledge_calls) != self.knowledge_results:
                raise BridgeError('incomplete_tool_results')
            return ReplyText(self.text, len(self.search_calls), self.sources, self.knowledge_calls.values())
        return None


class DshClient:
    def __init__(self, config, http=None, connect=None, *, preset_id=PRESET_ID):
        if preset_id not in (PRESET_ID,LEARNER_PRESET_ID):
            raise BridgeError("invalid_bridge_preset")
        self.preset_id = preset_id
        self.cfg = config
        self.http = http or httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False)
        self.connect = connect or _NoRedirectConnect
        self.cookie = config.agent_chat_dsh_cookie.get_secret_value()
        self.auth_lock = asyncio.Lock()

    async def close(self):
        await self.http.aclose()

    async def authenticate(self):
        async with self.auth_lock:
            if self.cookie:
                return
            token = self.cfg.agent_chat_dsh_token.get_secret_value()
            if not token:
                raise BridgeError("dsh_auth_missing")
            try:
                response = await self.http.get(self.cfg.agent_chat_dsh_url + "/", params={"token": token})
                cookies = response.headers.get_list("set-cookie")
                found = [c.split(";", 1)[0] for c in cookies if c.startswith("dsh-auth-")]
                if len(found) != 1:
                    raise BridgeError("dsh_auth_failed")
                self.cookie = found[0]
            except httpx.HTTPError:
                raise BridgeError("dsh_unreachable") from None

    async def rpc(self, method, payload=None, rpc_id=None):
        await self.authenticate()
        rid = rpc_id or str(uuid.uuid4())
        if method == "agentPresets/list":
            args = {}
        elif method == "agentPresets/read":
            args = {"agentPreset": (payload or {}).get("agentPreset")}
        else:
            args = {"_request" if method == "session/list" else "request": payload or {}}
        body = {"type": "client-request", "rpcId": rid, "method": method, "payload": {"args": args}}
        try:
            async with self.http.stream("POST", self.cfg.agent_chat_dsh_url + "/api/" + method,
                                        headers={"Cookie": self.cookie}, json=body) as response:
                if response.status_code == 401:
                    self.cookie = ""
                    raise BridgeError("dsh_auth_expired")
                if response.status_code != 200:
                    raise BridgeError("dsh_http_error")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2_000_000:
                        raise BridgeError("dsh_response_too_large")
                    chunks.append(chunk)
            result = json.loads(b"".join(chunks))
        except (httpx.HTTPError, ValueError):
            raise BridgeError("dsh_transport_or_protocol_error") from None
        if not isinstance(result, dict) or result.get("type") != "server-response" or result.get("rpcId") != rid:
            raise BridgeError("dsh_protocol_mismatch")
        envelope = result.get("result", {})
        if envelope.get("ok") is not True:
            code = envelope.get("error", {}).get("code", "")
            if (code == 'session/attachment-invalid' and
                    envelope.get('error', {}).get('details', {}).get('reason') == 'MODEL_DOES_NOT_SUPPORT_IMAGES'):
                raise ImageUnsupported('model_does_not_support_images')
            if code in {"session-not-found", "session/not-found"}:
                raise MissingSession("dsh_session_missing")
            raise BridgeError("dsh_rpc_rejected")
        return envelope.get("value")

    async def policy(self):
        fingerprint, _ = await self.policy_with_persona()
        return fingerprint

    async def policy_with_persona(self):
        """Fingerprint and role come from one validated preset read, never chat text."""
        listed = await self.rpc("agentPresets/list")
        if not isinstance(listed, dict) or not any(p.get("id") == self.preset_id and not p.get("broken") for p in listed.get("presets", [])):
            raise BridgeError("safe_preset_missing")
        # Intentionally no fallback if this DSH version cannot inspect the composition.
        preset = await self.rpc("agentPresets/read", {"agentPreset": self.preset_id})
        if not isinstance(preset, dict) or preset.get("agentPreset") != self.preset_id:
            raise BridgeError("preset_identity_mismatch")
        content = preset.get("content")
        fingerprint = validate_preset(content)
        return fingerprint, yaml.safe_load(content)[1]["config"]["prefix"]

    async def create_session(self):
        value = await self.rpc("session/create", {"agentPreset": self.preset_id})
        if not isinstance(value, dict) or value.get("agentPreset") != self.preset_id:
            raise BridgeError("session_preset_mismatch")
        sid = value.get("sessionId")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", sid):
            raise BridgeError("invalid_session_id")
        if self.cfg.agent_chat_model:
            await self.rpc("session/selectModel", {"sessionId": sid, "provider": self.cfg.agent_chat_provider,
                                                   "model": self.cfg.agent_chat_model})
        return sid

    async def stop(self, sid):
        # cancel alone does not clear DSH's pending inbox. Clear first, then cancel.
        failure = None
        try:
            projections = await self.rpc("session/projections", {"sessionId": sid})
            # DSH returns null when no projection service is attached.
            if projections is not None and not isinstance(projections, dict):
                raise BridgeError("invalid_projections")
            values = (projections or {}).get("values", {})
            inbox = values.get("inbox", {})
            for boundary in ("next-turn", "next-step"):
                items = inbox.get(boundary, [])
                if not isinstance(items, list):
                    raise BridgeError("invalid_inbox")
                for item in items:
                    if not isinstance(item.get("id"), str):
                        raise BridgeError("invalid_inbox_item")
                    await self.rpc("session/updateQueue", {"sessionId": sid, "itemId": item["id"], "action": {"kind": "remove"}})
        except Exception as exc:
            failure = exc
        try:
            await self.rpc("session/cancel", {"sessionId": sid})
        finally:
            if failure:
                raise BridgeError("cannot_confirm_queue_cleared") from None

    async def reply(self, sid, text, images=None, *, search_enabled=False, on_search=None, knowledge=None, research_term=""):
        try:
            return await asyncio.wait_for(self._reply(sid, text, images, search_enabled, on_search, knowledge, research_term), self.cfg.agent_chat_timeout)
        except asyncio.TimeoutError:
            raise BridgeError("dsh_turn_timeout") from None
        except (OSError, websockets.WebSocketException):
            raise BridgeError("dsh_stream_disconnected") from None

    async def context_state(self, sid, since=None):
        """Inspect durable events, never model text, for loss of the initial role seed."""
        try:
            return await asyncio.wait_for(self._context_state(sid, since), 15)
        except asyncio.TimeoutError:
            raise BridgeError("dsh_context_timeout") from None
        except (OSError, websockets.WebSocketException):
            raise BridgeError("dsh_stream_disconnected") from None

    async def recovery_checkpoint(self, sid):
        try:
            return await asyncio.wait_for(self._recovery_checkpoint(sid), 15)
        except asyncio.TimeoutError:
            raise BridgeError('recovery_check_timeout') from None
        except (OSError, websockets.WebSocketException):
            raise BridgeError('dsh_stream_disconnected') from None

    async def _recovery_checkpoint(self, sid):
        await self.authenticate()
        stream = str(uuid.uuid4())
        async with self.connect(self.cfg.agent_chat_dsh_url.replace('http','ws',1)+'/api/remote.mux',
                extra_headers={'Cookie':self.cookie},open_timeout=10,close_timeout=2,max_size=2_000_000) as ws:
            await ws.send(json.dumps({'type':'open','streamId':stream,'endpoint':'session/follow',
                'payload':{'args':{'request':{'address':{'kind':'session','sessionId':sid},'maxMessages':20}}}}))
            snapshot = None
            async for raw in ws:
                frame = self.frame(raw,stream)
                if frame and frame.get('type') == 'snapshot':
                    snapshot = frame
                    break
        if (not snapshot or snapshot.get('header',{}).get('id') != sid or
                snapshot.get('header',{}).get('agentPreset') != self.preset_id or
                snapshot.get('projections',{}).get('values',{}).get('agentPreset') != self.preset_id):
            raise BridgeError('unsafe_current_session_preset')
        inbox = snapshot['projections']['values'].get('inbox')
        if not isinstance(inbox,dict) or any(inbox.get(k) != [] for k in ('next-turn','next-step')):
            raise BridgeError('recovery_turn_active')
        cut = snapshot.get('cursor')
        if type(cut) is not int or cut < -1:
            raise BridgeError('invalid_context_cursor')
        page, before, latest_turn, owner = snapshot, cut+1, None, False
        owner_seq, turn_seq = -1, -1
        for _ in range(8):
            records = page.get('records')
            if not isinstance(records,list) or type(page.get('hasMore')) is not bool:
                raise BridgeError('invalid_context_page')
            events = [r.get('event',{}) for r in records if isinstance(r,dict)]
            seqs = [e.get('seq') for e in events]
            if (len(events)!=len(records) or any(type(s) is not int or s<0 for s in seqs) or
                    seqs != sorted(set(seqs)) or seqs and seqs[-1]>=before):
                raise BridgeError('invalid_context_page')
            for event in reversed(events):
                kind, data = event.get('type'), event.get('data',{})
                if latest_turn is None and kind in {'turn/start','turn/end'}:
                    latest_turn = kind
                    turn_seq = event['seq']
                    if kind != 'turn/end':
                        raise BridgeError('recovery_turn_active')
                if not owner and kind == 'user/message' and data.get('source',{}).get('kind') == 'user':
                    source, blocks = data.get('source',{}), data.get('content',[])
                    try:
                        first = blocks[0]['text'].split('\n',1)[0]
                        if not first.startswith(CONTROL_PREFIX): raise ValueError()
                        control = json.loads(first[len(CONTROL_PREFIX):])
                        if (control.get('version')!=1 or control.get('sessionId')!=sid or
                                not source.get('rpcId') or control.get('rpcId')!=source['rpcId']): raise ValueError()
                    except (ValueError,KeyError,IndexError,TypeError,AttributeError):
                        raise BridgeError('recovery_foreign_input') from None
                    owner = True
                    owner_seq = event['seq']
            if latest_turn and owner:
                if owner_seq >= turn_seq: raise BridgeError('recovery_history_unverified')
                return cut
            if not page['hasMore']:
                if latest_turn is None and not owner: return cut  # Never-used session.
                raise BridgeError('recovery_history_unverified')
            if not seqs: raise BridgeError('invalid_context_page')
            before = seqs[0]
            page = await self.rpc('session/page',{'address':{'kind':'session','sessionId':sid},
                'throughSeq':cut,'beforeSeq':before,'maxMessages':20})
            if not isinstance(page,dict): raise BridgeError('invalid_context_page')
        raise BridgeError('recovery_history_unverified')

    async def _context_state(self, sid, since):
        await self.authenticate()
        ws_url = self.cfg.agent_chat_dsh_url.replace("http", "ws", 1) + "/api/remote.mux"
        stream = str(uuid.uuid4())
        async with self.connect(ws_url, extra_headers={"Cookie": self.cookie},
                                open_timeout=10, close_timeout=2, max_size=2_000_000, max_queue=32) as ws:
            await ws.send(json.dumps({"type": "open", "streamId": stream, "endpoint": "session/follow",
                "payload": {"args": {"request": {"address": {"kind": "session", "sessionId": sid}, "maxMessages": 2}}}}))
            snapshot = None
            async for raw in ws:
                frame = self.frame(raw, stream)
                if frame and frame.get("type") == "snapshot":
                    snapshot = frame
                    break
            if snapshot is None:
                raise BridgeError("missing_snapshot")
        if (snapshot.get("header", {}).get("id") != sid or
                snapshot.get("header", {}).get("agentPreset") != self.preset_id or
                snapshot.get("projections", {}).get("values", {}).get("agentPreset") != self.preset_id):
            raise BridgeError("unsafe_current_session_preset")
        cut = snapshot.get("cursor")
        if type(cut) is not int or cut < -1:
            raise BridgeError("invalid_context_cursor")
        if since is None or cut < since:
            return cut, True
        if cut == since:
            return cut, False
        page, before = snapshot, cut + 1
        # Bound local work. If a long gap cannot be proved intact, re-seed conservatively.
        for attempt in range(4):
            records = page.get("records")
            if not isinstance(records, list) or type(page.get("hasMore")) is not bool:
                raise BridgeError("invalid_context_page")
            events = [r.get("event", {}) for r in records if isinstance(r, dict)]
            if len(events) != len(records) or any(type(e.get("seq")) is not int for e in events):
                raise BridgeError("invalid_context_page")
            seqs = [e["seq"] for e in events]
            if seqs and (seqs != sorted(set(seqs)) or seqs[-1] >= before or seqs[0] < 0):
                raise BridgeError("invalid_context_page")
            if any(e["seq"] > since and
                   (e.get("type", "").startswith("compaction/") or
                    isinstance(e.get("surfaceOp"), dict)) for e in events):
                return cut, True
            if not page["hasMore"] or seqs and seqs[0] <= since + 1:
                return cut, False
            if not seqs:
                raise BridgeError("invalid_context_page")
            before = seqs[0]
            if attempt < 3:
                page = await self.rpc("session/page", {"address": {"kind": "session", "sessionId": sid},
                    "throughSeq": cut, "beforeSeq": before, "maxMessages": 4})
                if not isinstance(page, dict):
                    raise BridgeError("invalid_context_page")
        return cut, True

    async def _reply(self, sid, text, images=None, search_enabled=False, on_search=None, knowledge=None, research_term=""):
        rid = str(uuid.uuid4())
        lease = knowledge.hub.lease(knowledge,sid,rid) if knowledge else contextlib.nullcontext()
        with lease:
            return await self._reply_bound(sid,text,images,search_enabled,on_search,knowledge,research_term,rid)

    async def _reply_bound(self, sid, text, images, search_enabled, on_search, knowledge, research_term, rid):
        control = {'version': 1, 'sessionId': sid, 'rpcId': rid,
                   'enabled': bool(search_enabled), 'expires': int(time.time() * 1000) + 300000}
        if knowledge:
            control['knowledge'] = [family for family,prefix in (('memory','qq_memory_'),('slang','qq_slang_'))
                                    if any(tool.startswith(prefix) for tool in knowledge.tools)]
        if research_term:
            control['researchTerm'] = research_term
        content = [{"type": "text", "text": CONTROL_PREFIX + json.dumps(control) + '\n' + text}]
        for image in images or []:
            if (len(content) > 4 or set(image) != {"type", "mediaType", "data", "name"} or
                    image["type"] != "image" or image["mediaType"] != "image/jpeg" or
                    not isinstance(image["data"], str) or len(image["data"]) > 1_400_000 or
                    not re.fullmatch(r"qq-image-[1-4]\.jpg", image["name"])):
                raise BridgeError("invalid_image_input")
            content.append(image)
        await self.authenticate()
        ws_url = self.cfg.agent_chat_dsh_url.replace("http", "ws", 1) + "/api/remote.mux"
        stream = str(uuid.uuid4())
        async with self.connect(ws_url, extra_headers={"Cookie": self.cookie},
                                open_timeout=10, close_timeout=2, max_size=2_000_000, max_queue=32) as ws:
            await ws.send(json.dumps({"type": "open", "streamId": stream, "endpoint": "session/follow",
                "payload": {"args": {"request": {"address": {"kind": "session", "sessionId": sid}, "maxMessages": 20}}}}))
            snapshot = None
            async for raw in ws:
                frame = self.frame(raw, stream)
                if frame and frame.get("type") == "snapshot":
                    snapshot = frame
                    break
            if snapshot is None:
                raise BridgeError("missing_snapshot")
            header = snapshot.get("header", {})
            if header.get("id") != sid or header.get("agentPreset") != self.preset_id:
                raise BridgeError("unsafe_session_header")
            projections = snapshot.get("projections", {}).get("values", {})
            # Header is creation-time only. The projection folds the ENTIRE log,
            # including preset switches older than this bounded snapshot window.
            if projections.get("agentPreset") != self.preset_id:
                raise BridgeError("unsafe_current_session_preset")
            # Reject a changed preset, unfinished historical turn or queued work.
            open_turns = set()
            for record in snapshot.get("records", []):
                event = record.get("event", record)
                kind, data = event.get("type"), event.get("data", {})
                if kind == "agent-preset/selected" and data.get("agentPreset") != self.preset_id:
                    raise BridgeError("session_preset_changed")
                if kind == "turn/start": open_turns.add(data.get("turn"))
                if kind == "turn/end": open_turns.discard(data.get("turn"))
            inbox = projections.get("inbox", {})
            if open_turns or any(inbox.get(k) for k in ("next-turn", "next-step")):
                raise BridgeError("session_has_pending_work")
            result = await self.rpc("session/prompt", {"sessionId": sid, "requestId": rid, "mode": "queue",
                                     "content": content}, rpc_id=rid)
            if not isinstance(result, dict) or result.get("accepted") is not True or result.get("command"):
                raise BridgeError("unexpected_prompt_response")
            collector = TurnCollector(rid, search_enabled, on_search, knowledge.tools if knowledge else (), self.preset_id)
            async for raw in ws:
                value = self.frame(raw, stream)
                if value and value.get("type") == "event":
                    reply = collector.push(value.get("event", {}))
                    if reply is not None:
                        return reply
            raise BridgeError("dsh_stream_ended")

    @staticmethod
    def frame(raw, stream):
        try:
            frame = json.loads(raw)
        except (ValueError, TypeError):
            raise BridgeError("invalid_stream_frame") from None
        if not isinstance(frame, dict):
            raise BridgeError("invalid_stream_frame")
        if frame.get("streamId") != stream:
            return None
        if frame.get("type") in {"error", "end"}:
            error = frame.get("error", {})
            if isinstance(error, dict) and error.get("code") in {"session-not-found", "session/not-found"}:
                raise MissingSession("dsh_session_missing")
            raise BridgeError("dsh_follow_failed")
        return frame.get("value") if frame.get("type") == "item" else None
