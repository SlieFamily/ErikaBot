"""DSH slash-RPC / remote.mux adapter. No shell, filesystem or approval forwarding.

Protocol reference: Derpyu520/qq-bridge (MIT); see third_party/qq-bridge-LICENSE.
Unknown wire shapes fail closed. A lost prompt response is never blindly retried.
"""
import asyncio
import hashlib
import json
import logging
import re
import uuid

import httpx
import websockets
from websockets.legacy.client import Connect
import yaml

from .config import GUARD_MODULE, PRESET_ID


class BridgeError(Exception):
    """Only fixed diagnostic codes; never carry remote messages or credentials."""


class MissingSession(BridgeError):
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
    if not isinstance(rows, list) or len(rows) != 3:
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
    if (not isinstance(children, list) or len(children) != 1 or not isinstance(children[0], dict) or
            set(children[0]) - {"id", "name"} or children[0].get("name") != "@deepseek-ai/dsh-compaction-basic"):
        raise BridgeError("unsafe_compaction_configuration")
    persona = rows[1].get("config", {})
    if not isinstance(persona, dict) or set(persona) != {"prefix", "includeRuntimeContext", "complete"}:
        raise BridgeError("unsafe_persona_configuration")
    if (persona["includeRuntimeContext"] is not False or persona["complete"] is not True or
            not isinstance(persona["prefix"], str)):
        raise BridgeError("unsafe_persona_configuration")
    if "{{" in persona["prefix"]:
        raise BridgeError("persona_templates_not_allowed")
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class TurnCollector:
    """Only return a turn containing OUR user message; never replay snapshot output."""
    def __init__(self, rpc_id):
        self.rpc_id = rpc_id
        self.turn = None
        self.owned = False
        self.text = ""

    def push(self, event):
        kind, data = event.get("type"), event.get("data", {})
        if kind == "turn/start":
            self.turn = data.get("turn")
            self.owned, self.text = False, ""
        elif kind == "user/message":
            source = data.get("source", {})
            if source.get("kind") == "runtime-context":
                # DSH emits its own metadata/clearing snapshot in this event channel.
                # It is not another operator's prompt and never establishes ownership.
                return None
            if source.get("kind") == "user" and source.get("rpcId") == self.rpc_id:
                self.owned = True
            else:
                # Dedicated bridge sessions must not be manually chatted in concurrently.
                raise BridgeError("concurrent_session_input")
        elif kind == "tool/call":
            # Defence-in-depth detector, NOT the execution guard. DSH guard enforces denial.
            raise BridgeError("unexpected_tool_call")
        elif kind == "agent-preset/selected" and data.get("agentPreset") != PRESET_ID:
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
            return self.text
        return None


class DshClient:
    def __init__(self, config, http=None, connect=None):
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
            if code in {"session-not-found", "session/not-found"}:
                raise MissingSession("dsh_session_missing")
            raise BridgeError("dsh_rpc_rejected")
        return envelope.get("value")

    async def policy(self):
        listed = await self.rpc("agentPresets/list")
        if not isinstance(listed, dict) or not any(p.get("id") == PRESET_ID and not p.get("broken") for p in listed.get("presets", [])):
            raise BridgeError("safe_preset_missing")
        # Intentionally no fallback if this DSH version cannot inspect the composition.
        preset = await self.rpc("agentPresets/read", {"agentPreset": PRESET_ID})
        if not isinstance(preset, dict) or preset.get("agentPreset") != PRESET_ID:
            raise BridgeError("preset_identity_mismatch")
        return validate_preset(preset.get("content"))

    async def create_session(self):
        value = await self.rpc("session/create", {"agentPreset": PRESET_ID})
        if not isinstance(value, dict) or value.get("agentPreset") != PRESET_ID:
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

    async def reply(self, sid, text):
        try:
            return await asyncio.wait_for(self._reply(sid, text), self.cfg.agent_chat_timeout)
        except asyncio.TimeoutError:
            raise BridgeError("dsh_turn_timeout") from None
        except (OSError, websockets.WebSocketException):
            raise BridgeError("dsh_stream_disconnected") from None

    async def _reply(self, sid, text):
        await self.authenticate()
        ws_url = self.cfg.agent_chat_dsh_url.replace("http", "ws", 1) + "/api/remote.mux"
        stream = str(uuid.uuid4())
        rid = str(uuid.uuid4())
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
            if header.get("id") != sid or header.get("agentPreset") != PRESET_ID:
                raise BridgeError("unsafe_session_header")
            projections = snapshot.get("projections", {}).get("values", {})
            # Header is creation-time only. The projection folds the ENTIRE log,
            # including preset switches older than this bounded snapshot window.
            if projections.get("agentPreset") != PRESET_ID:
                raise BridgeError("unsafe_current_session_preset")
            # Reject a changed preset, unfinished historical turn or queued work.
            open_turns = set()
            for record in snapshot.get("records", []):
                event = record.get("event", record)
                kind, data = event.get("type"), event.get("data", {})
                if kind == "agent-preset/selected" and data.get("agentPreset") != PRESET_ID:
                    raise BridgeError("session_preset_changed")
                if kind == "turn/start": open_turns.add(data.get("turn"))
                if kind == "turn/end": open_turns.discard(data.get("turn"))
            inbox = projections.get("inbox", {})
            if open_turns or any(inbox.get(k) for k in ("next-turn", "next-step")):
                raise BridgeError("session_has_pending_work")
            result = await self.rpc("session/prompt", {"sessionId": sid, "requestId": rid, "mode": "queue",
                                     "content": [{"type": "text", "text": text}]}, rpc_id=rid)
            if not isinstance(result, dict) or result.get("accepted") is not True or result.get("command"):
                raise BridgeError("unexpected_prompt_response")
            collector = TurnCollector(rid)
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
