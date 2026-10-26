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
        ai.config.agent_chat_slang_enabled = True
        ai.config.agent_chat_groups = frozenset({42})

        class FakeService:
            def __init__(self): self.observed = []; self.scheduled = []; self.recovered=[]; self.learned=[]; self.knowledge=None
            def allowed(self, bot_id, group_id, user_id): return group_id == 42 and str(user_id) != str(bot_id)
            def observe(self, message): self.observed.append(message); return True
            def schedule(self, message, send, prepare=None): self.scheduled.append((message, send)); self.prepare = prepare
            async def recover(self,key):self.recovered.append(key);return 'resumed'
            def learn_message(self,message,plain):self.learned.append((message.message_id,plain))

        service = FakeService(); ai.service = service
        sent = []
        api_calls=[]

        class FakeBot(Bot):
            async def call_api(self, api, **data):
                api_calls.append((api,data))
                if api == 'get_forward_msg':
                    return {'messages':[{'sender':{'nickname':'转发成员'},'message':[
                        {'type':'text','data':{'text':'转发测试内容'}},
                        {'type':'image','data':{'file':'a'*32+'.jpg'}}]}]}
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
        assert service.learned[-1][1]=='群内梗', 'ordinary slang still reaches learner when a passive quote replies'
        sent.clear()
        await handle_event(bot, event("群内梗", directed=True))
        assert len(service.scheduled) == 1 and not sent, "AI @ takeover must suppress both passive handlers"
        _, send = service.scheduled.pop()
        await send("[CQ:at,qq=all]")
        assert len(sent[0]) == 1 and sent[0][0].type == "text", "model CQ must remain literal"
        sent.clear()
        learned_before=len(service.learned)
        await handle_event(bot, event("测试语录"))
        assert sent and not service.scheduled, "explicit quote command wins"
        assert len(service.learned)==learned_before, 'explicit commands must not enter learning window'
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
        forwarded=event('看看这段聊天记录',directed=True)
        forwarded.message.append(MessageSegment('forward',{'id':'observed-forward'}))
        await handle_event(bot,forwarded)
        observed,send=service.scheduled.pop()
        assert observed.forwards==('observed-forward',)
        _,notes=await service.prepare([observed.payload()],[observed.payload()])
        assert '转发测试内容' in notes and any(a=='get_forward_msg' for a,_ in api_calls)
        from src.plugins.agent_chat.presentation import parse
        import json
        await send(parse('QQ_REPLY '+json.dumps({'text':'哼😏','reply_to':str(observed.message_id),'faces':['捂脸']}),{str(observed.message_id)}))
        assert [s.type for s in sent[-1]]==['reply','text','face']
        assert api_calls[-1][0]=='send_msg' and api_calls[-1][1]['group_id']==42
        assert api_calls[-1][1]['message'][0].data['id']==str(observed.message_id)
        assert str(api_calls[-1][1]['message'][1].data['text'])=='哼😏'
        # Use the real Bot -> Adapter -> JSON serializer, replacing only the socket.
        adapter=Adapter(nonebot.get_driver());wire=[]
        class CaptureSocket:
            async def send(self,raw):
                frame=json.loads(raw);wire.append(frame)
                asyncio.get_running_loop().call_soon(adapter._result_store.add_result,
                    {'status':'ok','retcode':0,'data':{'message_id':999},'echo':frame['echo']})
        adapter.connections['101']=CaptureSocket()
        native_bot=Bot(adapter,'101')
        for raw,expected in [
            ('QQ_REPLY '+json.dumps({'text':'好呀😏','reply_to':str(observed.message_id),'faces':['捂脸']}),['reply','text','face']),
            ('就这样😂',['text']),
            ('QQ_REPLY '+json.dumps({'text':'','reply_to':'','faces':['可爱']}),['face'])]:
            await native_bot.send(forwarded,ai.outgoing_message(parse(raw,{str(observed.message_id)})))
            assert [part['type'] for part in wire[-1]['params']['message']]==expected
            assert wire[-1]['params']['group_id']==42
        assert wire[0]['params']['message'][0]['data']['id']==str(observed.message_id)
        assert wire[0]['params']['message'][1]['data']['text']=='好呀😏'
        assert wire[0]['params']['message'][2]['data']['id']=='264'
        adapter.connections.clear()
        sent.clear()
        await handle_event(bot,event('ai 恢复',uid=7))
        assert service.recovered==[], 'ordinary group members cannot run recovery'
        service.scheduled.clear()
        await handle_event(bot,event('ai 恢复',uid=1))
        assert service.recovered==['100:group:42'] and not service.scheduled, 'SUPERUSER recovery wins over chat handlers'
        sent.clear()
        before=len(sent)
        await handle_event(bot,event('ai 清空记忆',uid=7))
        assert len(sent)==before, 'ordinary members cannot administer persistent memory'
        service.scheduled.clear()
        import sqlite3
        from src.plugins.agent_chat.knowledge import KnowledgeStore
        db=sqlite3.connect(':memory:');service.knowledge=KnowledgeStore(db)
        ids=[]
        for term in ('测试甲词','测试乙词'):
            item=service.knowledge.submit_slang('100:group:42',term,[{'key':'100:group:42','message_id':term,'text':term,'name':'群友','user_id':'7'}])
            ids.append(item['id'])
        with db:db.execute("UPDATE knowledge_slang SET meaning='测试解释'")
        command='ai 黑话确认 '+','.join(str(i) for i in ids)
        await handle_event(bot,event(command,uid=7))
        assert db.execute("SELECT COUNT(*) FROM knowledge_slang WHERE status='confirmed'").fetchone()[0]==0
        await handle_event(bot,event(command,uid=1))
        assert db.execute("SELECT COUNT(*) FROM knowledge_slang WHERE status='confirmed'").fetchone()[0]==2
        assert '已确认 2 条' in str(sent[-1])
        service.knowledge=None;db.close()
        ai.config.agent_chat_images_enabled = False
        ai.media_resolver = None
        ai.service = None
        await handle_event(bot, event("你好", directed=True))
        assert sent, "disabled AI retains old @ reply"
        print("PASS: real NoneBot dispatch, SuperAna arbitration, mention recovery, literal CQ, image/forward routing, reply+face segments, SUPERUSER recovery, allowlist, disabled fallback")
        os.chdir(ROOT)


if __name__ == "__main__": asyncio.run(main())
