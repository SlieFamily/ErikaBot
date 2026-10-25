"""Real loopback HTTP + WebSocket test, simulating the documented DSH wire protocol."""
import asyncio
import json
import yaml
from http import HTTPStatus
import socket
import unittest

from fastapi import FastAPI, Request, WebSocket
import uvicorn
import websockets

from test_agent_chat import cfg, composition, dsh


class WireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = FastAPI(); self.ws = None; self.stream = None
        self.prompts = []; self.session_counter = 0; self.mode = "normal"
        self.pages = []; self.page_requests = []

        @self.app.post("/api/{method:path}")
        async def rpc(method: str, request: Request):
            body = await request.json(); payload = body["payload"]["args"]
            if request.headers.get("cookie") != "dsh-auth-test=secret":
                from fastapi.responses import Response
                return Response(status_code=401)
            if method == "agentPresets/list":
                value = {"presets":[{"id":"erika-agent-chat-v1"}]}
            elif method == "agentPresets/read":
                assert payload == {"agentPreset":"erika-agent-chat-v1"}
                value = {"agentPreset":"erika-agent-chat-v1", "content":composition()}
                if self.mode == 'unsafe-composition':
                    rows = yaml.safe_load(value['content'])
                    rows.append({'name': '@deepseek-ai/dsh-tool-bash'})
                    value['content'] = yaml.safe_dump(rows)
            elif method == "session/create":
                self.session_counter += 1
                value = {"sessionId":"session-" + str(self.session_counter), "agentPreset":"erika-agent-chat-v1"}
            elif method == "session/prompt":
                if self.mode == 'image-unsupported':
                    return {'type':'server-response','rpcId':body['rpcId'],
                            'result':{'ok':False,'error':{'code':'session/attachment-invalid',
                            'details':{'reason':'MODEL_DOES_NOT_SUPPORT_IMAGES'},'message':'not exposed'}}}
                self.prompts.append(payload["request"])
                await self.emit({"type":"turn/start", "data":{"turn":3}})
                await self.emit({"type":"user/message", "data":{"source":{"kind":"user","rpcId":body["rpcId"]}}})
                await self.emit({"type":"user/message", "data":{"source":{"kind":"runtime-context"}}})
                if self.mode == "disconnect":
                    await self.ws.close()
                elif self.mode == "tool":
                    await self.emit({"type":"tool/call", "data":{"name":"bash"}})
                else:
                    await self.emit({"type":"assistant/chunk", "data":{"turn":3,"text":"新回复"}})
                    await self.emit({"type":"assistant/message", "data":{"turn":3,"message":{"content":[{"type":"text","text":"新回复"}]}}})
                    await self.emit({"type":"turn/end", "data":{"turn":3,"reason":{"kind":"completed"}}})
                value = {"accepted":True}
            elif method == "session/projections":
                value = {"asOfSeq":2,"values":{"inbox":{"next-turn":[],"next-step":[]}}}
            elif method == "session/page":
                self.page_requests.append(payload['request'])
                value = self.pages.pop(0)
            else:
                value = {"accepted":True}
            return {"type":"server-response","rpcId":body["rpcId"],"result":{"ok":True,"value":value}}

        @self.app.websocket("/api/remote.mux")
        async def stream(ws: WebSocket):
            await ws.accept(); self.ws = ws
            body = await ws.receive_json(); self.stream = body["streamId"]
            sid = body["payload"]["args"]["request"]["address"]["sessionId"]
            # Completed historical output MUST NOT be replayed as a new QQ message.
            snapshot = {"type":"snapshot", "cursor":20, "hasMore":True, "header":{"id":sid,"agentPreset":"erika-agent-chat-v1"},
                        "records":[{"event":{"seq":19,"type":"assistant/message","data":{"turn":1,"message":{"content":[{"type":"text","text":"旧消息"}]}}}},
                                   {"event":{"seq":20,"type":"turn/end","data":{"turn":1,"reason":{"kind":"completed"}}}}],
                        "projections":{"values":{"agentPreset":"erika-agent-chat-v1", "inbox":{"next-turn":[],"next-step":[]}}}}
            if self.mode == "unsafe-preset": snapshot["header"]["agentPreset"] = "standard"
            if self.mode == "old-preset-switch": snapshot["projections"]["values"]["agentPreset"] = "standard"
            await ws.send_json({"type":"item","streamId":self.stream,"value":snapshot})
            try:
                while True: await ws.receive_text()
            except Exception: pass

        self.sock = socket.socket(); self.sock.bind(("127.0.0.1", 0)); self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(self.app, log_level="critical", lifespan="off"))
        self.server.install_signal_handlers = lambda: None
        self.server_task = asyncio.create_task(self.server.serve(sockets=[self.sock]))
        for _ in range(100):
            if self.server.started: break
            await asyncio.sleep(.01)
        self.client = dsh.DshClient(cfg(agent_chat_dsh_url=f"http://127.0.0.1:{self.port}"))

    async def emit(self, event):
        await self.ws.send_json({"type":"item","streamId":self.stream,"value":{"type":"event","event":event}})

    async def asyncTearDown(self):
        await self.client.close()
        self.server.should_exit = True
        await asyncio.wait_for(self.server_task, 5)
        self.sock.close()

    async def test_complete_wire_exchange_no_old_reply_or_double_chunks(self):
        await self.client.policy()
        sid = await self.client.create_session()
        self.assertEqual(await self.client.reply(sid, "QQ_CHAT_EVENT test"), "新回复")
        self.assertEqual(self.prompts[0]["sessionId"], sid)
        self.assertTrue(self.prompts[0]["requestId"])

    async def test_forwarded_persona_is_extracted_only_after_validating_same_preset(self):
        fingerprint, persona = await self.client.policy_with_persona()
        self.assertEqual(fingerprint, dsh.validate_preset(composition()))
        self.assertEqual(persona, yaml.safe_load(composition())[1]['config']['prefix'])
        self.mode = 'unsafe-composition'
        with self.assertRaises(dsh.BridgeError):
            await self.client.policy_with_persona()
        self.assertEqual(self.prompts, [])

    async def test_context_seed_and_unchanged_history(self):
        self.assertEqual(await self.client.context_state('session-1'), (20, True))
        self.assertEqual(await self.client.context_state('session-1', 18), (20, False))
        self.assertEqual(await self.client.context_state('session-1', 20), (20, False))
        self.assertEqual(await self.client.context_state('session-1', 21), (20, True))
        self.assertEqual(self.prompts, [])

    async def test_compaction_before_opening_window_is_detected(self):
        self.pages = [{'hasMore': True, 'records': [
            {'event': {'seq': 16, 'type': 'compaction/summary', 'data': {}}}]}]
        self.assertEqual(await self.client.context_state('session-1', 5), (20, True))
        self.assertEqual(self.page_requests[0]['throughSeq'], 20)
        self.assertEqual(self.page_requests[0]['beforeSeq'], 19)
        self.assertEqual(self.prompts, [])

    async def test_old_compaction_is_not_refreshed_again(self):
        self.pages = [{'hasMore': False, 'records': [
            {'event': {'seq': 5, 'type': 'compaction/summary', 'data': {}}},
            {'event': {'seq': 6, 'type': 'turn/start', 'data': {}}}]}]
        self.assertEqual(await self.client.context_state('session-1', 5), (20, False))

    async def test_long_unverifiable_gap_refreshes_but_never_calls_model(self):
        self.pages = [{'hasMore': True, 'records': [
            {'event': {'seq': seq, 'type': 'turn/end', 'data': {}}}]} for seq in (18, 17, 16)]
        self.assertEqual(await self.client.context_state('session-1', 0), (20, True))
        self.assertEqual(len(self.page_requests), 3)
        self.assertEqual(self.prompts, [])

    async def test_malformed_page_rejected_and_unsafe_preset_checked(self):
        self.pages = [{'hasMore': True, 'records': []}]
        with self.assertRaisesRegex(dsh.BridgeError, 'invalid_context_page'):
            await self.client.context_state('session-1', 0)
        self.mode = 'old-preset-switch'
        with self.assertRaisesRegex(dsh.BridgeError, 'unsafe_current_session_preset'):
            await self.client.context_state('session-1', 18)

    async def test_wrong_preset_rejected_before_prompt(self):
        self.mode = "unsafe-preset"
        with self.assertRaisesRegex(dsh.BridgeError, "unsafe_session_header"):
            await self.client.reply("session-1", "QQ_CHAT_EVENT test")
        self.assertEqual(self.prompts, [])

    async def test_native_image_uses_only_allowed_attachment_fields(self):
        image = {'type':'image','mediaType':'image/jpeg','data':'YWJj','name':'qq-image-1.jpg'}
        await self.client.reply('session-1', 'QQ_CHAT_EVENT image-test', [image])
        self.assertEqual(self.prompts[0]['content'][1], image)
        self.assertEqual(self.prompts[0]['content'][0]['type'], 'text')

    async def test_explicit_image_rejection_has_a_distinct_safe_error(self):
        self.mode = 'image-unsupported'
        with self.assertRaises(dsh.ImageUnsupported):
            await self.client.reply('session-1', 'test',
                [{'type':'image','mediaType':'image/jpeg','data':'YWJj','name':'qq-image-1.jpg'}])

    async def test_disconnect_never_resubmits_prompt(self):
        self.mode = "disconnect"
        with self.assertRaises(dsh.BridgeError):
            await self.client.reply("session-1", "QQ_CHAT_EVENT test")
        self.assertEqual(len(self.prompts), 1)

    async def test_old_preset_switch_outside_history_window_rejected(self):
        self.mode = "old-preset-switch"
        with self.assertRaisesRegex(dsh.BridgeError, "unsafe_current_session_preset"):
            await self.client.reply("session-1", "QQ_CHAT_EVENT test")
        self.assertEqual(self.prompts, [])

    async def test_unexpected_tool_stops_output(self):
        self.mode = "tool"
        with self.assertRaisesRegex(dsh.BridgeError, "unexpected_tool_call"):
            await self.client.reply("session-1", "QQ_CHAT_EVENT test")

    async def test_websocket_redirect_cannot_forward_cookie(self):
        leaked = []
        async def unused(ws):
            await ws.close()
        async def sink(path, headers):
            leaked.append(headers.get("Cookie"))
            return HTTPStatus.FORBIDDEN, [], b"stop"
        async with websockets.serve(unused, "127.0.0.1", 0, process_request=sink) as target:
            port = target.sockets[0].getsockname()[1]
            async def redirect(path, headers):
                return HTTPStatus.FOUND, [("Location", f"ws://127.0.0.1:{port}/stolen")], b"redirect"
            async with websockets.serve(unused, "127.0.0.1", 0, process_request=redirect) as origin:
                port = origin.sockets[0].getsockname()[1]
                client = dsh.DshClient(cfg(agent_chat_dsh_url=f"http://127.0.0.1:{port}"))
                try:
                    with self.assertRaisesRegex(dsh.BridgeError, "dsh_ws_redirect_rejected"):
                        await client.reply("session-1", "test")
                finally:
                    await client.close()
        self.assertEqual(leaked, [])


if __name__ == "__main__": unittest.main()
