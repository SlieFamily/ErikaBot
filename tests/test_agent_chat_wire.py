"""Real loopback HTTP + WebSocket test, simulating the documented DSH wire protocol."""
import asyncio
import json
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
            elif method == "session/create":
                self.session_counter += 1
                value = {"sessionId":"session-" + str(self.session_counter), "agentPreset":"erika-agent-chat-v1"}
            elif method == "session/prompt":
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
            else:
                value = {"accepted":True}
            return {"type":"server-response","rpcId":body["rpcId"],"result":{"ok":True,"value":value}}

        @self.app.websocket("/api/remote.mux")
        async def stream(ws: WebSocket):
            await ws.accept(); self.ws = ws
            body = await ws.receive_json(); self.stream = body["streamId"]
            sid = body["payload"]["args"]["request"]["address"]["sessionId"]
            # Completed historical output MUST NOT be replayed as a new QQ message.
            snapshot = {"type":"snapshot", "header":{"id":sid,"agentPreset":"erika-agent-chat-v1"},
                        "records":[{"event":{"type":"assistant/message","data":{"turn":1,"message":{"content":[{"type":"text","text":"旧消息"}]}}}},
                                   {"event":{"type":"turn/end","data":{"turn":1,"reason":{"kind":"completed"}}}}],
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

    async def test_wrong_preset_rejected_before_prompt(self):
        self.mode = "unsafe-preset"
        with self.assertRaisesRegex(dsh.BridgeError, "unsafe_session_header"):
            await self.client.reply("session-1", "QQ_CHAT_EVENT test")
        self.assertEqual(self.prompts, [])

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
