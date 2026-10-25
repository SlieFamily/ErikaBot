"""Exercise NoneBot 2's real dispatch against their_ana in a temporary DB directory."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    with tempfile.TemporaryDirectory() as td:
        os.chdir(td)
        Path("db").mkdir()
        import nonebot
        nonebot.init(_env_file=None, driver="~fastapi", superusers={"1"}, command_start={"/", ""}, log_level="ERROR")
        from nonebot.adapters.onebot.v11 import Adapter, Bot, GroupMessageEvent, Message, MessageSegment
        from nonebot.adapters.onebot.v11.bot import _check_reply, _check_at_me
        from nonebot.message import handle_event
        ai_plugin = nonebot.load_plugin("src.plugins.agent_chat")
        ana_plugin = nonebot.load_plugin("src.plugins.their_ana")
        assert ai_plugin and ana_plugin, "plugins must load"
        ai, ana = ai_plugin.module, ana_plugin.module
        ai.config.agent_chat_takeover_mentions = True

        class FakeService:
            def __init__(self): self.observed = []; self.scheduled = []
            def allowed(self, bot_id, group_id, user_id): return group_id == 42 and str(user_id) != str(bot_id)
            def observe(self, message): self.observed.append(message); return True
            def schedule(self, message, send, prepare=None): self.scheduled.append((message, send)); self.prepare = prepare

        service = FakeService(); ai.service = service
        sent = []

        class FakeBot(Bot):
            async def send(self, event, message, **kwargs):
                sent.append(Message(message))
                return {"message_id": 999}
            async def call_api(self, api, **data):
                if api == 'get_msg':
                    return {'time': int(time.time()), 'message_type': 'group', 'message_id': 123,
                            'real_id': 123, 'sender': {'user_id': 8, 'nickname': '发图者'},
                            'message': [{'type': 'image', 'data': {'file': 'b' * 32 + '.jpg'}}]}
                sent.append(Message(data.get("message", "")))
                return {"message_id": 999}

        bot = FakeBot(Adapter(nonebot.get_driver()), "100")
        ana.model.GetReRule = lambda: "(群内梗)"
        ana.model.GetAna = lambda *args: "旧语录"
        idx = 0

        def event(text, directed=False, group=42, uid=7):
            nonlocal idx
            idx += 1
            return GroupMessageEvent.parse_obj(dict(time=int(time.time()), self_id=100, post_type="message",
                message_type="group", sub_type="normal", message_id=idx, group_id=group, user_id=uid,
                message=[{"type":"text","data":{"text":text}}], original_message=[{"type":"text","data":{"text":text}}],
                raw_message=text, font=0, sender={"user_id":uid,"nickname":"群友","role":"member"}, to_me=directed))

        await handle_event(bot, event("普通聊天"))
        assert len(service.scheduled) == 1, "SuperAna's broad match must not claim a no-hit message"
        assert not sent
        service.scheduled.clear()
        await handle_event(bot, event("群内梗"))
        assert len(sent) == 1 and not service.scheduled, "advanced quote must suppress AI"
        sent.clear()
        await handle_event(bot, event("群内梗", directed=True))
        assert len(service.scheduled) == 1 and not sent, "AI @ takeover must suppress both passive handlers"
        _, send = service.scheduled.pop()
        await send("[CQ:at,qq=all]")
        assert len(sent[0]) == 1 and sent[0][0].type == "text", "model CQ must remain literal"
        sent.clear()
        await handle_event(bot, event("测试语录"))
        assert sent and not service.scheduled, "explicit quote command wins"
        sent.clear()
        before = len(service.observed)
        await handle_event(bot, event("你好", group=99))
        await handle_event(bot, event("你好", uid=100))
        assert len(service.observed) == before, "non-allowed groups and bot echoes excluded"
        ai.config.agent_chat_images_enabled = True
        class FakeMedia:
            async def prepare(self, history, call_api): return [], 'checked'
        ai.media_resolver = FakeMedia()
        picture = event('这是什么图', directed=True)
        picture.message.append(MessageSegment.image('a' * 32 + '.jpg'))
        await handle_event(bot, picture)
        assert service.scheduled[-1][0].media[0]['file'] == 'a' * 32 + '.jpg'
        assert service.prepare is not None, 'only unclaimed allowed events schedule media preparation'
        service.scheduled.clear()
        quoted = event('这个人是谁')
        quoted.message = Message([MessageSegment.reply(123), MessageSegment.at(100), MessageSegment.text('这个人是谁')])
        quoted.original_message = quoted.message.copy()
        await _check_reply(bot, quoted)
        _check_at_me(bot, quoted)
        assert not quoted.is_tome(), 'reproduce upstream removal of mention after quoting another sender'
        await handle_event(bot, quoted)
        assert service.scheduled[-1][0].directed, 'original structured bot mention must survive quote preprocessing'
        assert service.scheduled[-1][0].media[0]['file'] == 'b' * 32 + '.jpg'
        service.scheduled.clear()
        for mention in [MessageSegment.at(8), MessageSegment.at('all'), MessageSegment.text('[CQ:at,qq=100]')]:
            other = event('看图')
            other.original_message = Message([mention, MessageSegment.text('看图')])
            await handle_event(bot, other)
            assert not service.scheduled[-1][0].directed, 'other targets and literal CQ text are not a bot mention'
            service.scheduled.clear()
        ai.config.agent_chat_images_enabled = False
        ai.media_resolver = None
        ai.service = None
        await handle_event(bot, event("你好", directed=True))
        assert sent, "disabled AI retains old @ reply"
        print("PASS: real NoneBot dispatch, SuperAna no-hit/hit, @ takeover, quoted-image mention recovery, literal CQ, image routing, allowlist, disabled fallback")
        os.chdir(ROOT)


if __name__ == "__main__": asyncio.run(main())
